"""The program tree of a C source: ``offload.engine.rules.ProgramTree`` for
``#pragma omp`` directives.

``parse_c_program(source, version)`` scans a C11 source and returns the same
``ProgramTree`` the Fortran scanner builds, with ``tree.lang == "c"``.
``offload.engine.rules.parse_program`` calls it for a C source.
The fields follow the Fortran meaning. A block-associated directive applies to the next statement and a
loop-associated one to the next ``for`` loop, whose variable, bounds and
intervening statements are recorded when the loop is canonical.
``end declare target`` is the paired end of the ``begin declare target``
before it. Declarations follow C block scope, and ``tree.extra`` holds
``substatement``, ``loops`` and ``ctypes`` for the C rules.
It is not a C parser: there is no preprocessing, so both branches of an
``#if`` are scanned. It raises ``ProgramError`` on unbalanced braces or
parentheses and on an unpaired ``end declare target``."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from offload.engine.grammar import GrammarError, parse_directive

_PRAGMA_OMP = re.compile(r"^\s*#\s*pragma\s+omp\b")
# OpenACC C programs (#pragma acc, version 34)
_PRAGMA_OF = {"omp": _PRAGMA_OMP,
              "acc": re.compile(r"^\s*#\s*pragma\s+acc\b")}
_C_SOURCE = re.compile(r"^\s*#\s*pragma\s+(omp|acc)\b", re.M)

TYPE_WORDS = {"void", "char", "short", "int", "long", "float", "double",
              "signed", "unsigned", "_Bool", "bool", "_Complex", "struct",
              "union", "enum", "const", "volatile", "restrict", "static",
              "extern", "register", "auto", "_Atomic", "inline", "typedef",
              "_Thread_local", "_Alignas", "_Noreturn"}
KNOWN_TYPEDEFS = {"bool", "size_t", "omp_allocator_handle_t",
                  "omp_alloctrait_t", "omp_depend_t", "omp_memspace_handle_t",
                  "omp_impex_t", "intptr_t", "uintptr_t", "int64_t",
                  "int32_t", "uint64_t", "uint32_t", "omp_interop_t",
                  "omp_event_handle_t", "omp_lock_t", "omp_nest_lock_t"}
_INT_WORDS = {"char", "short", "int", "long", "signed", "unsigned",
              "size_t", "intptr_t", "uintptr_t", "int64_t", "int32_t",
              "uint64_t", "uint32_t"}
_QUALIFIERS = {"const", "volatile", "restrict", "static", "extern",
               "register", "auto", "_Atomic", "inline", "_Thread_local",
               "typedef", "_Noreturn"}


def is_c_source(source: str) -> bool:
    """A C source: it has a ``#pragma omp`` line (a Fortran source of the
    project never does: free-form Fortran directives are ``!$omp``)."""
    return bool(_C_SOURCE.search(source))


# --- lexing --------------------------------------------------------------------

@dataclass
class Tok:
    kind: str   # id, num, str, op, pragma
    text: str
    line: int


_OPS = ("<<=", ">>=", "...", "->", "++", "--", "<<", ">>", "<=", ">=", "==",
        "!=", "&&", "||", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=",
        "##")
_TOKEN = re.compile(r"""
    (?P<id>[A-Za-z_]\w*)
  | (?P<num>\.?\d(?:[\w.]|[eEpP][+-])*)
  | (?P<str>"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')
  | (?P<op>""" + "|".join(re.escape(o) for o in _OPS) + r"""|[^\s\w])
""", re.X)


def _strip_comments(source: str) -> str:
    """The source with comments replaced by blanks (newlines kept, so line
    numbers stay), strings untouched."""
    out, i, n = [], 0, len(source)
    while i < n:
        c = source[i]
        if c in "\"'":
            j = i + 1
            while j < n and source[j] != c and source[j] != "\n":
                j += 2 if source[j] == "\\" else 1
            out.append(source[i:j + 1])
            i = j + 1
        elif source.startswith("//", i):
            j = source.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif source.startswith("/*", i):
            j = source.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(re.sub(r"[^\n]", " ", source[i:j]))
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def lex(source: str, model: str = "omp") -> list[Tok]:
    """Tokens of a C source; a ``#pragma omp`` line (continuations joined)
    is one ``pragma`` token; other preprocessor lines are dropped."""
    text = _strip_comments(source)
    lines = text.split("\n")
    toks: list[Tok] = []
    k = 0
    while k < len(lines):
        raw, start = lines[k], k + 1
        if raw.lstrip().startswith("#"):
            group = [raw]
            while group[-1].rstrip().endswith("\\") and k + 1 < len(lines):
                k += 1
                group.append(lines[k])
            k += 1
            if _PRAGMA_OF[model].match(raw):
                joined = " ".join(g.rstrip().rstrip("\\") for g in group)
                toks.append(Tok("pragma", joined.strip(), start))
            continue
        pos = 0
        while pos < len(raw):
            m = _TOKEN.search(raw, pos)
            if not m:
                break
            toks.append(Tok(m.lastgroup, m.group(), start))
            pos = m.end()
        k += 1
    return toks


# --- the scanner --------------------------------------------------------------

@dataclass
class _For:
    var: str | None
    line: int
    bounds: tuple = ("", "", "")
    canon: dict = field(default_factory=dict)
    loops: list = field(default_factory=list)  # nested _For / _Blk
    directive: bool = False
    transform: bool = False  # a loop-associated directive in the body
    stmts: int = 0
    branches: list = field(default_factory=list)  # (kind, line)


@dataclass
class _Blk:
    line: int
    loops: list = field(default_factory=list)
    directive: bool = False
    transform: bool = False
    stmts: int = 0
    branches: list = field(default_factory=list)


_CANON_INIT = re.compile(r"^(?:(?P<type>[\w\s*]+?)\s+)?(?P<var>[A-Za-z_]\w*)"
                         r"\s*=\s*(?P<lb>.+)$", re.S)
_RELOPS = ("<=", ">=", "!=", "<", ">")


def _canonical(init: str, test: str, incr: str) -> dict:
    """Canonical loop form facts of a for header (5.2 §4.4.1, 6.0 §6.4.1):
    {var, lb, bound, relop, var_left, step (+1/-1/+k/-k text), sign,
    declared, type} or {} when the header does not have the shape."""
    m = _CANON_INIT.match(init.strip())
    if not m:
        return {}
    var = m.group("var")
    typ = (m.group("type") or "").strip()
    if typ and not set(typ.replace("*", " ").split()) <= (
            TYPE_WORDS | KNOWN_TYPEDEFS):
        return {}
    test = test.strip()
    relop = var_left = bound = None
    for op in _RELOPS:
        parts = _split_op(test, op)
        if parts is None:
            continue
        lhs, rhs = (p.strip() for p in parts)
        if lhs == var and not re.search(rf"\b{re.escape(var)}\b", rhs):
            relop, var_left, bound = op, True, rhs
        elif rhs == var and not re.search(rf"\b{re.escape(var)}\b", lhs):
            relop, var_left, bound = op, False, lhs
        break
    if relop is None:
        return {}
    v = re.escape(var)
    incr = " ".join(incr.split())
    sign = step = None
    for pat, s, st in ((rf"^(?:\+\+\s*{v}|{v}\s*\+\+)$", "+", "1"),
                       (rf"^(?:--\s*{v}|{v}\s*--)$", "-", "1")):
        if re.match(pat, incr):
            sign, step = s, st
    if sign is None:
        mm = re.match(rf"^{v}\s*([+-])=\s*(.+)$", incr) or re.match(
            rf"^{v}\s*=\s*{v}\s*([+-])\s*(.+)$", incr)
        if mm:
            sign, step = mm.group(1), mm.group(2).strip()
        else:
            mm = re.match(rf"^{v}\s*=\s*(.+?)\s*\+\s*{v}$", incr)
            if mm:
                sign, step = "+", mm.group(1).strip()
    if sign is None:
        return {}
    return {"var": var, "lb": m.group("lb").strip(), "bound": bound,
            "relop": relop, "var_left": var_left, "sign": sign,
            "step": step, "declared": bool(typ), "type": typ}


def _split_op(text: str, op: str):
    """(lhs, rhs) at the one top-level occurrence of a relational `op`."""
    depth, i = 0, 0
    hits = []
    while i < len(text):
        c = text[i]
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif depth == 0 and text.startswith(op, i):
            # do not take "<" out of "<<", "<=" or "->"
            before = text[i - 1] if i else ""
            after = text[i + len(op):i + len(op) + 1]
            if not (op in ("<", ">") and (after in "<>=" and after
                                          or before in "<>-" and before)):
                hits.append(i)
                i += len(op)
                continue
        i += 1
    if len(hits) != 1:
        return None
    return text[:hits[0]], text[hits[0] + len(op):]


def _ctype_class(words: list[str]) -> str:
    ws = set(words)
    if ws & {"struct", "union"}:
        return "type"
    if ws & {"_Bool", "bool"}:
        return "logical"
    if ws & {"float", "double"}:
        return "real"
    if ws & _INT_WORDS or "enum" in ws:
        return "integer"
    return "other"


class _Scanner:
    def __init__(self, source: str, version: int):
        from offload.engine.rules import Assoc, ProgramTree, ProgramError
        self.Assoc, self.Error = Assoc, ProgramError
        from offload.engine.catalog import model_of
        self.model = model_of(version)
        self.toks = lex(source, self.model)
        self.pos = 0
        self.version = version
        self.tree = ProgramTree([], [], [], {})
        self.tree.lang = "c"
        self.tree.extra = {"substatement": set(), "loops": {}, "ctypes": {},
                           "struct_members": {}}
        self.typedefs = set(KNOWN_TYPEDEFS)
        self.nscopes = 0
        self.scopes = [0]
        self.dirs: list[int] = []   # open directives (indices), innermost last
        self.frames: list = []      # open _For / _Blk frames
        self.delimited: list[int] = []
        # enclosing iteration/switch statements: ("for", frame) / ("while",
        # None) / ("do", None) / ("switch", None), innermost last
        self.loopstack: list = []
        self.tree.extra["jumps"] = []   # (kind, line, target frame id)
        self.tree.extra["iters"] = []   # (line, enclosing for-frame ids)
        # Every frame stays alive for the whole parse, so the frame
        # ids above (id()) are never reused by a later frame; a popped _For
        # that no parent kept could be freed and its id given to another
        # loop, which made an illegal variant read as violating a second
        # rule (seen on wingtip: omp52-c-illegal-collapse-loop-001)
        self._alive: list = []

    # -- token helpers --
    def peek(self, k=0) -> Tok | None:
        j = self.pos + k
        return self.toks[j] if j < len(self.toks) else None

    def next(self) -> Tok:
        t = self.peek()
        if t is None:
            raise self.Error("unexpected end of the C source")
        self.pos += 1
        return t

    def expect(self, text: str) -> Tok:
        t = self.next()
        if t.text != text:
            raise self.Error(f"line {t.line}: expected {text!r}, got "
                             f"{t.text!r}")
        return t

    def balanced(self, open_: str, close: str) -> list[Tok]:
        """Tokens up to the matching `close` (the opening one consumed)."""
        depth, out = 1, []
        while True:
            t = self.next()
            if t.text == open_:
                depth += 1
            elif t.text == close:
                depth -= 1
                if depth == 0:
                    return out
            out.append(t)

    def until_semicolon(self) -> list[Tok]:
        out, depth = [], 0
        while True:
            t = self.next()
            if t.text in "([{":
                depth += 1
            elif t.text in ")]}":
                depth -= 1
                if depth < 0:
                    raise self.Error(f"line {t.line}: unbalanced {t.text!r}")
            elif t.text == ";" and depth == 0:
                return out
            elif t.kind == "pragma":
                raise self.Error(f"line {t.line}: directive inside a "
                                 "statement")
            out.append(t)

    @staticmethod
    def text(toks: list[Tok]) -> str:
        """Compact C text of tokens: blanks between words and around binary
        operators, none around ``.``, ``->``, inside brackets, before
        ``(``/``[`` of a name, or after a unary ``*``/``&``/``!``/``-``."""
        out = ""
        prev: Tok | None = None
        unary = False
        for t in toks:
            x = t.text
            if not out:
                out = x
            elif x in (".", "->", ")", "]", ",", ";") or (
                    x in ("(", "[") and prev is not None and (
                        prev.kind == "id" or prev.text in (")", "]"))) or (
                    prev is not None and prev.text in (".", "->", "(", "[")) \
                    or unary:
                out += x
            else:
                out += " " + x
            if x == ",":
                out += ""
            unary = x in ("*", "&", "!", "-", "~") and (
                prev is None or prev.kind == "op" and prev.text not in (
                    ")", "]") or prev.text in ("return",))
            prev = t
        return out.replace(",", ", ").replace(",  ", ", ")

    # -- recording --
    def stmt(self, line: int, text: str) -> None:
        clean = re.sub(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'', "", text)
        self.tree.statements.append((line, " ".join(clean.lower().split()),
                                     tuple(self.scopes)))
        if self.dirs:
            self.tree.assoc[self.dirs[-1]].stmts += 1
        if self.frames:
            self.frames[-1].stmts += 1

    def open_scope(self, kind: str = "block", name: str | None = None):
        self.nscopes += 1
        self.scopes.append(self.nscopes)
        if kind != "block":
            self.tree.units[self.nscopes] = (kind, name)
        return self.nscopes

    def close_scope(self):
        self.scopes.pop()

    def is_decl_start(self) -> bool:
        t = self.peek()
        if t is None or t.kind != "id":
            return False
        if t.text in TYPE_WORDS:
            return True
        if t.text in self.typedefs:
            nxt = self.peek(1)
            return nxt is not None and (nxt.kind == "id" or nxt.text == "*")
        return False

    # -- declarations --
    def declaration(self, toks: list[Tok], line: int) -> None:
        """Record the declarators of one declaration (its tokens without
        the ';')."""
        words, k = [], 0

        def base_seen():
            return any(w not in _QUALIFIERS for w in words)

        while k < len(toks) and (
                toks[k].text in TYPE_WORDS
                or (toks[k].text in self.typedefs and not base_seen())):
            if toks[k].text in ("struct", "union", "enum"):
                kw = toks[k].text
                words.append(kw)
                k += 1
                tag = None
                if k < len(toks) and toks[k].kind == "id":
                    tag = toks[k].text
                    words.append(tag)
                    k += 1
                if k < len(toks) and toks[k].text == "{":
                    k = self.struct_body(toks, k, kw, tag, words)
                continue
            words.append(toks[k].text)
            k += 1
        typedef = "typedef" in words
        sid = self.scopes[-1]
        cls = _ctype_class(words)
        base = " ".join(w for w in words if w not in ("static", "extern",
                                                      "typedef", "register",
                                                      "auto", "inline"))
        for decl in _split_top_toks(toks[k:]):
            name, ptr, arr, func = _declarator(decl, self.typedefs)
            if name is None:
                continue
            if typedef:
                self.typedefs.add(name)
                # What the typedef names (the declare mapper rule
                # resolves a typedef'd struct)
                self.tree.extra.setdefault("typedefs", {})[name] = \
                    base + (" *" * ptr) + (" []" if arr else "")
                continue
            if func:
                continue  # a prototype: not a variable
            key = (sid, name)
            self.tree.decls[key] = "pointer" if ptr else "plain"
            self.tree.vtypes[key] = cls
            self.tree.extra["ctypes"][key] = base + (" *" * ptr) + (
                " []" if arr else "")
            if arr:
                self.tree.arrays.add(key)
            if sid == 0 or "static" in words:
                self.tree.saved.add(key)
            tag = next((words[j + 1] for j, w in enumerate(words[:-1])
                        if w in ("struct", "union")), None)
            if tag:
                self.tree.vartypes[key] = tag
        self.stmt(line, self.text(toks))

    def struct_body(self, toks, k, kw, tag, words) -> int:
        """Members of a struct/union definition starting at toks[k] == '{';
        returns the index after the closing brace."""
        depth, j = 0, k
        while j < len(toks):
            if toks[j].text == "{":
                depth += 1
            elif toks[j].text == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        inner = toks[k + 1:j]
        if kw == "enum":
            # enumeration constants: named constants of the scope
            for d in _split_top_toks(inner):
                if d and d[0].kind == "id":
                    key = (self.scopes[-1], d[0].text)
                    self.tree.params.add(key)
                    self.tree.decls[key] = "plain"
                    self.tree.vtypes[key] = "integer"
            return j + 1
        members = {}
        for decl_toks in _split_semis(inner):
            mw, m = [], 0
            while m < len(decl_toks) and (decl_toks[m].text in TYPE_WORDS or
                                          decl_toks[m].text in self.typedefs):
                mw.append(decl_toks[m].text)
                m += 1
            bitfield = any(t.text == ":" for t in decl_toks[m:])
            for d in _split_top_toks(decl_toks[m:]):
                name, ptr, arr, _ = _declarator(d, self.typedefs)
                if name:
                    members[name] = ("pointer" if ptr else "plain",
                                     None, bitfield)
        if tag:
            self.tree.types[(self.scopes[-1], tag)] = {
                n: (a, t) for n, (a, t, _) in members.items()}
            self.tree.extra["struct_members"][(self.scopes[-1], tag)] = {
                "kind": kw, "bitfields": {n for n, v in members.items()
                                          if v[2]}}
        return j + 1

    # -- directives --
    def directive(self, t: Tok, substatement: bool = False) -> None:
        from offload.engine.rules import association
        try:
            d = parse_directive(t.text, "c", self.version)
        except GrammarError:
            raise
        if d.name == "end declare target":
            if not self.delimited:
                raise self.Error(f"line {t.line}: end declare target without "
                                 "begin declare target")
            i = self.delimited.pop()
            self.tree.ends[i] = d
            self.tree.assoc[i].end_line = t.line
            return
        idx = len(self.tree.directives)
        self.tree.directives.append(d)
        if self.dirs:
            self.tree.nesting.append((self.dirs[-1], idx))
        how = association(d.name, self.model)
        if self.frames:
            self.frames[-1].directive = True
            self.frames[-1].transform |= how == "loop"
        a = self.Assoc(kind=how if how in ("block", "loop", "statement")
                       else "standalone", line=t.line, unit=1,
                       scope=tuple(self.scopes))
        self.tree.assoc.append(a)
        if substatement and how not in ("block", "loop", "statement"):
            self.tree.extra["substatement"].add(idx)
        delimited = self.model == "omp" and (
            d.name == "begin declare target" or (
                d.name == "declare target" and not d.clauses and not d.args
                and self.version < 60))
        if delimited:
            self.delimited.append(idx)
            return
        if how == "loopseq":
            raise self.Error(f"line {t.line}: loop-sequence directive "
                             f"{d.name!r} is not supported")
        if how not in ("block", "loop", "statement"):
            return
        self.dirs.append(idx)
        saved_frames = self.frames
        self.frames = []
        nxt = self.peek()
        if how == "loop" and nxt is not None and nxt.text == "for":
            top = self.for_statement(owner=idx)
            dos, known = _chain(top)
            a.loop_depth = len(dos)
            a.loop_vars = tuple(f.var for f in dos)
            a.depth_known = known
            a.loop_bounds = tuple(f.bounds for f in dos)
            a.intervening = tuple(
                f.stmts + _between(f, dos[k + 1] if k + 1 < len(dos)
                                   else None) for k, f in enumerate(dos))
            self.tree.extra["loops"][idx] = {
                "canon": [f.canon for f in dos],
                "chain": [id(f) for f in dos], "top": id(top),
                "lines": [f.line for f in dos]}
        elif how == "loop" and nxt is not None and nxt.kind == "pragma":
            p = parse_directive(nxt.text, "c", self.version)
            if association(p.name, self.model) == "loop":
                raise self.Error(f"line {nxt.line}: loop-transforming or "
                                 f"loop directive {p.name!r} between a "
                                 "loop directive and its loop is not "
                                 "supported")
            self.statement()
        else:
            self.statement()
        self.frames = saved_frames
        self.dirs.pop()
        a.end_line = self.last_line

    # -- statements --
    def compound(self) -> None:
        self.expect("{")
        self.open_scope()
        blk = _Blk(self.peek(-1).line if self.pos else 0)
        self._alive.append(blk)
        if self.frames:
            self.frames[-1].loops.append(blk)
        self.frames.append(blk)
        while True:
            t = self.peek()
            if t is None:
                raise self.Error("unclosed '{'")
            if t.text == "}":
                self.next()
                self.last_line = t.line
                break
            self.statement(in_compound=True)
        self.frames.pop()
        self.close_scope()

    def for_statement(self, owner: int | None = None) -> _For:
        t = self.expect("for")
        self.expect("(")
        header = self.balanced("(", ")")
        parts = _split_semis(header, keep_empty=True)
        if len(parts) != 3:
            raise self.Error(f"line {t.line}: for header without two ';'")
        init, test, incr = (self.text(p) for p in parts)
        canon = _canonical(init, test, incr)
        self.open_scope()
        if canon.get("declared"):
            key = (self.scopes[-1], canon["var"])
            self.tree.decls[key] = "plain"
            words = canon["type"].replace("*", " ").split()
            self.tree.vtypes[key] = _ctype_class(words)
            self.tree.extra["ctypes"][key] = canon["type"]
        elif init.strip() and not canon:
            m = re.match(r"^((?:[\w]+\s+)+)\**\s*([A-Za-z_]\w*)\s*=",
                         init.strip())
            if m and set(m.group(1).split()) <= TYPE_WORDS | self.typedefs:
                self.tree.decls[(self.scopes[-1], m.group(2))] = "plain"
        f = _For(canon.get("var"), t.line,
                 (canon.get("lb", ""), canon.get("bound", ""),
                  canon.get("step", "")) if canon else ("", "", ""), canon)
        self._alive.append(f)
        self.tree.extra["iters"].append((t.line, self.enclosing_fors(),
                                         id(f)))
        if self.frames and owner is None:
            self.frames[-1].loops.append(f)
        self.stmt(t.line, f"for ({init}; {test}; {incr})")
        if self.frames:
            self.frames[-1].stmts -= 1  # the header is the loop itself
            self.frames[-1].branches.append(("iteration", t.line))
        self.frames.append(f)
        self.loopstack.append(("for", f))
        self.substatement()
        self.loopstack.pop()
        self.frames.pop()
        self.close_scope()
        return f

    def enclosing_fors(self) -> tuple:
        return tuple(id(x) for k, x in self.loopstack if k == "for")

    def jump(self, kind: str, line: int) -> None:
        """Record the statement a break/continue applies to."""
        target = None
        for k, x in reversed(self.loopstack):
            if kind == "continue" and k == "switch":
                continue
            target = id(x) if k == "for" else k
            break
        self.tree.extra["jumps"].append((kind, line, target,
                                         self.enclosing_fors()))

    def substatement(self) -> None:
        """The statement of an if/else/while/for/do (a directive there must
        be an executable construct, 5.2 §3.1 p.54)."""
        t = self.peek()
        if t is not None and t.kind == "pragma":
            self.next()
            self.directive(t, substatement=True)
            from offload.engine.rules import association
            d = self.tree.directives[-1] if self.tree.directives else None
            if d is not None and association(d.name, self.model) not in (
                    "block", "loop", "statement"):
                self.statement()  # the statement that follows the pragma
            return
        self.statement()

    def statement(self, in_compound: bool = False) -> None:
        t = self.peek()
        if t is None:
            raise self.Error("a statement is missing at the end")
        if t.kind == "pragma":
            self.next()
            self.directive(t)
            self.last_line = t.line
            return
        if t.text == "{":
            self.compound()
            return
        if t.text == ";":
            self.next()
            self.last_line = t.line
            return
        if t.text == "for":
            self.for_statement()
            return
        if t.text in ("while", "switch"):
            self.next()
            self.expect("(")
            cond = self.balanced("(", ")")
            self.stmt(t.line, f"{t.text} ({self.text(cond)})")
            if t.text == "while":
                self.tree.extra["iters"].append((t.line,
                                                 self.enclosing_fors(), None))
            self.loopstack.append((t.text, None))
            self.substatement()
            self.loopstack.pop()
            return
        if t.text == "do":
            self.next()
            self.stmt(t.line, "do")
            self.tree.extra["iters"].append((t.line, self.enclosing_fors(),
                                             None))
            self.loopstack.append(("do", None))
            self.substatement()
            self.loopstack.pop()
            self.expect("while")
            self.expect("(")
            cond = self.balanced("(", ")")
            self.expect(";")
            self.last_line = self.peek(-1).line
            return
        if t.text == "if":
            self.next()
            self.expect("(")
            cond = self.balanced("(", ")")
            self.stmt(t.line, f"if ({self.text(cond)})")
            self.substatement()
            if self.peek() is not None and self.peek().text == "else":
                self.next()
                self.substatement()
            return
        if t.kind == "id" and self.peek(1) is not None and \
                self.peek(1).text == ":" and t.text not in ("default",):
            self.next()
            self.next()
            self.substatement()
            return
        if t.text in ("break", "continue"):
            self.jump(t.text, t.line)
        if self.is_decl_start():
            toks = self.until_semicolon()
            self.declaration(toks, t.line)
            self.last_line = self.peek(-1).line
            return
        toks = self.until_semicolon()
        self.stmt(t.line, self.text(toks))
        self.last_line = self.peek(-1).line

    # -- file scope --
    def external(self) -> None:
        t = self.peek()
        if t.kind == "pragma":
            self.next()
            self.directive(t)
            return
        if t.text == ";":
            self.next()
            return
        # a function definition: declaration tokens up to ')' then '{'
        start = self.pos
        depth, j = 0, self.pos
        while j < len(self.toks):
            x = self.toks[j]
            if x.kind == "pragma" and depth == 0:
                break
            if x.text in "([":
                depth += 1
            elif x.text in ")]":
                depth -= 1
            elif depth == 0 and x.text in (";", "{", "="):
                break
            j += 1
        if j < len(self.toks) and self.toks[j].text == "{" and \
                self.toks[j - 1].text == ")":
            self.function(start, j)
            return
        toks = self.until_semicolon()
        self.declaration(toks, t.line)

    def function(self, start: int, brace: int) -> None:
        head = self.toks[start:brace]
        # the name: the identifier before the parameter list
        k = len(head) - 1
        depth = 0
        while k >= 0:
            if head[k].text == ")":
                depth += 1
            elif head[k].text == "(":
                depth -= 1
                if depth == 0:
                    break
            k -= 1
        name = head[k - 1].text if k > 0 else "?"
        params = head[k + 1:-1]
        self.stmt(head[0].line, self.text(head))
        sid = self.open_scope("program" if name == "main" else "function",
                              name)
        self.tree.decls[(0, name)] = "plain"  # the function's name
        for p in _split_top_toks(params):
            words = [x.text for x in p]
            if words in (["void"], []):
                continue
            pname, ptr, arr, _ = _declarator(
                [x for x in p if x.text not in TYPE_WORDS
                 and x.text not in self.typedefs or x is p[-1]])
            if pname:
                self.tree.decls[(sid, pname)] = "pointer" if ptr or arr \
                    else "plain"
                cls = _ctype_class(words)
                self.tree.vtypes[(sid, pname)] = cls
                self.tree.extra["ctypes"][(sid, pname)] = " ".join(
                    w for w in words if w != pname)
        self.pos = brace
        saved_dirs, saved_loops = self.dirs, self.loopstack
        self.dirs, self.loopstack = [], []
        self.compound()
        self.dirs, self.loopstack = saved_dirs, saved_loops
        self.close_scope()

    def run(self):
        self.last_line = 0
        while self.peek() is not None:
            self.external()
        if self.delimited:
            i = self.delimited[-1]
            raise self.Error(f"#pragma omp {self.tree.directives[i].name} "
                             f"(line {self.tree.assoc[i].line}) is never "
                             "closed by end declare target")
        return self.tree


def _split_semis(toks: list[Tok], keep_empty: bool = False) -> list:
    out, cur, depth = [], [], 0
    for t in toks:
        if t.text in "([{":
            depth += 1
        elif t.text in ")]}":
            depth -= 1
        if t.text == ";" and depth == 0:
            out.append(cur)
            cur = []
            continue
        cur.append(t)
    if cur or keep_empty:
        out.append(cur)
    return [c for c in out if c or keep_empty]


def _split_top_toks(toks: list[Tok]) -> list[list[Tok]]:
    out, cur, depth = [], [], 0
    for t in toks:
        if t.text in "([{":
            depth += 1
        elif t.text in ")]}":
            depth -= 1
        if t.text == "," and depth == 0:
            out.append(cur)
            cur = []
            continue
        cur.append(t)
    if cur:
        out.append(cur)
    return out


def _declarator(toks: list[Tok], typedefs=frozenset()) -> tuple:
    """(name, pointer depth, array, function) of one declarator (tokens up
    to an initializer; leading type words and typedef names skipped)."""
    eq = next((k for k, t in enumerate(toks) if t.text == "="), len(toks))
    d = toks[:eq]
    # bit-field width
    colon = next((k for k, t in enumerate(d) if t.text == ":"), len(d))
    d = d[:colon]
    lead = 0
    while lead < len(d) - 1 and (d[lead].text in TYPE_WORDS
                                 or d[lead].text in typedefs):
        lead += 1
    names = [t for t in d[lead:] if t.kind == "id"
             and t.text not in TYPE_WORDS]
    if not names:
        return None, 0, False, False
    name = names[0].text
    k = d.index(names[0])
    ptr = sum(1 for t in d[:k] if t.text == "*")
    after = [t.text for t in d[k + 1:]]
    return name, ptr, "[" in after, bool(after) and after[0] == "("


def _chain(f: _For) -> tuple:
    if f.var is None:
        return [], True
    inner, known = _body_chain(f)
    return [f] + inner, known


def _body_chain(frame) -> tuple:
    if frame.transform:
        return [], False
    loops = [c for c in frame.loops if isinstance(c, _For) or _has_loop(c)]
    if len(loops) != 1 or frame.directive:
        return [], True
    inner = loops[0]
    return _body_chain(inner) if isinstance(inner, _Blk) else _chain(inner)


def _has_loop(blk) -> bool:
    return any(isinstance(c, _For) or (isinstance(c, _Blk) and _has_loop(c))
               for c in blk.loops)


def _between(frame, target) -> int:
    """Statements in the compound statements of `frame` (recursively) that
    are not inside `target` (None: all of them)."""
    n = 0
    for c in frame.loops:
        if c is target or not isinstance(c, _Blk):
            continue
        n += c.stmts + _between(c, target)
    return n


def _contains(frame, target) -> bool:
    return any(c is target or (isinstance(c, _Blk) and _contains(c, target))
               for c in frame.loops)


def parse_c_program(source: str, version: int):
    """The ProgramTree of a C source (see the module docstring). B:
    ``extra["macros"]``: object-like macros whose value is an integer
    literal (``#define N 1024``)."""
    tree = _Scanner(source, version).run()
    tree.extra["macros"] = {
        m.group(1): int(m.group(2)) for m in re.finditer(
            r"^\s*#\s*define\s+([A-Za-z_]\w*)\s+\(?\s*(-?\d+)\s*\)?\s*$",
            source, re.M)}
    return tree
