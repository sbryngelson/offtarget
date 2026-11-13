"""A program's files, the directives in them with their lines, atoms and regions.

A program is one or more files. Free-form Fortran (.f90 .f95 .f03 .f08,
any case) and C (.c .h) are read; other files are reported as unsupported.

Directives are Fortran !$omp and !$acc (continued with a trailing &) and C
#pragma omp and #pragma acc. Each is parsed with
offload.engine.grammar.parse_directive at the requested version, then at the
other versions. If all fail, the name and each clause are parsed one by one
so a rejected clause still yields its atom. An unknown directive name is an
`unknown` occurrence. Regions record where each construct's associated code
ends. Device code is code in a compute construct, in a procedure with a
clause-less declare target (OpenACC routine), or in C between begin and end
declare target."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from offload.engine.catalog import directive_atom, model_of
from offload.engine.grammar import (Clause, Directive, GrammarError, _close_paren,
                                _c_line, _fortran_line, _parser, _Raw,
                                _tokenize, parse_directive)
from offload.engine.offload_scope import ACC_MACHINERY, OMP_MACHINERY

FORTRAN_EXT = {".f90", ".f95", ".f03", ".f08"}
C_EXT = {".c", ".h"}
VERSIONS = {"omp": (52, 60, 50), "acc": (34,)}
# OpenACC in C is parsed (the same grammar and atoms as
# Fortran OpenACC); False restores v2's reading (every #pragma acc unknown)
PARSE_C_ACC = True
_F_SENT = re.compile(r"^\s*!\$(omp|acc)(?![a-z0-9_])", re.I)
_C_SENT = re.compile(r"^\s*#\s*pragma\s+(omp|acc)\b", re.I)
_COMPUTE_ACC = {"parallel", "kernels", "serial"}
_DEVICE_DATA = {"target data", "target enter data", "target exit data",
                "target update"}


def lang_of(path: str) -> str | None:
    ext = Path(path).suffix.lower()
    if ext in FORTRAN_EXT:
        return "f90"
    if ext in C_EXT:
        return "c"
    return None


@dataclass
class Issue:
    code: str       # a GrammarError code, "unknown_directive", "region", ...
    message: str


@dataclass
class Occurrence:
    file: str
    line: int                     # first physical line of the directive
    last_line: int                # last physical line of the directive
    text: str                     # the directive as written (lines joined)
    model: str                    # omp | acc
    lang: str                     # f90 | c
    name: str | None = None       # catalog directive key (None: unknown)
    end: bool = False             # a Fortran end directive
    clauses: list = field(default_factory=list)
    atoms: frozenset = frozenset()
    version: int | None = None    # the version the directive parsed at
    issues: list = field(default_factory=list)
    region: tuple | None = None   # (first line, last line) of its code
    parent: int | None = None     # index of the enclosing occurrence
    device_unit: bool = False     # in a declare target procedure / range
    kind: str = "host"            # compute | machinery | device | host
    tolerant: bool = False        # parsed clause by clause

    @property
    def loc(self) -> str:
        return f"{self.file}:{self.line}"

    def clause_names(self) -> list[str]:
        return [c.name for c in self.clauses]


@dataclass
class SourceFile:
    path: str
    text: str
    lang: str | None


@dataclass
class Program:
    files: list
    occurrences: list
    version: int
    notes: list = field(default_factory=list)   # (file, line, message)

    @property
    def lang(self) -> str:
        langs = {f.lang for f in self.files if f.lang}
        return "c" if langs == {"c"} else "f90"

    @property
    def text(self) -> str:
        # Joined once (detectors read it per occurrence)
        got = self.__dict__.get("_text")
        if got is None:
            got = self.__dict__["_text"] = "\n".join(f.text
                                                    for f in self.files)
        return got

    def ancestors(self, i: int) -> list[int]:
        out, p = [], self.occurrences[i].parent
        while p is not None:
            out.append(p)
            p = self.occurrences[p].parent
        return out

    def children(self, i: int) -> list[int]:
        return [k for k, o in enumerate(self.occurrences) if o.parent == i]


def read_files(paths) -> list[SourceFile]:
    return [SourceFile(str(p), Path(p).read_text(errors="replace"),
                       lang_of(str(p))) for p in paths]


# --- one directive -------------------------------------------------------------

def is_compute(name: str | None, model: str) -> bool:
    if not name:
        return False
    first = name.split()[0]
    if model == "acc":
        return first in _COMPUTE_ACC
    return first == "target" and name not in _DEVICE_DATA


def _generic(parser, spelling, end, raws, model, issues):
    """The directive clause by clause (every version failed)."""
    from offload.engine.grammar import base_name
    keys = [k for k in parser.index[spelling]
            if not parser.sk.directive(k).languages
            or parser.lang in parser.sk.directive(k).languages] or \
        parser.index[spelling]
    key = keys[0]
    atoms = {directive_atom(key, model)}
    allowed = parser.allowed(key)
    by_spelling = {s["text"]: c for c in allowed
                   for s in parser.sk.clauses[c]["spellings"]}
    clauses = []
    for raw in raws:
        ckey = by_spelling.get(raw.name)
        cname = raw.name if model == "omp" else base_name(
            ckey or raw.name)
        if ckey is None:
            if raw.name in parser.clause_spellings:
                cname = raw.name if model == "omp" else \
                    parser.clause_spellings[raw.name]
                issues.append(Issue("clause_not_allowed",
                                    f"{raw.name} is not allowed on {key}"))
                atoms.add(f"{model}.clause.{cname}")
            else:
                issues.append(Issue("unknown_clause",
                                    f"no clause named {raw.name!r}"))
            clauses.append(parser.generic(raw))
            continue
        try:
            clause, feats = parser.clause(key, raw,
                                          parser.grammar.clauses.get(ckey))
        except GrammarError as e:
            issues.append(Issue(e.code, str(e).split(": ", 1)[-1]))
            clause, feats = parser.generic(raw), set()
        clauses.append(clause)
        atoms.add(f"{model}.clause.{cname}")
        atoms.update(f"{model}.clause.{cname}.{f}" for f in feats)
    return Directive(key, clauses, frozenset(atoms), end)


def parse_one(text: str, lang: str, version: int, model: str
              ) -> tuple[Directive | None, int | None, list, bool]:
    """(directive, version it parsed at, issues, tolerant)."""
    glang = "c" if lang == "c" else "f90"
    order = [version] + [v for v in VERSIONS[model] if v != version] \
        if model == "omp" else [34]
    first = None
    for v in order:
        try:
            d = parse_directive(text, glang, v)
            issues = [] if v == order[0] else [Issue(
                first.code, f"{first} (parsed as {_vname(v)})")]
            return d, v, issues, False
        except GrammarError as e:
            first = first or e
    issues = [Issue(first.code, str(first).split(": ", 1)[-1])]
    if first.code in ("fixed_form",):
        return None, None, issues, False
    from offload.engine.catalog import default_grammar, default_skeleton
    v = order[0]
    parser = _parser(default_skeleton(model), default_grammar(model),
                     "C" if lang == "c" else "Fortran", v)
    try:
        line = _c_line(text) if lang == "c" else _fortran_line(text, model)
        toks = _tokenize(line)
        spelling, end, toks = (parser.c_name(toks) if lang == "c"
                               else parser.fortran_name(toks))
        if spelling is None:
            return None, None, issues, False
        i, raws = 0, []
        if i < len(toks) and toks[i].text == "(":
            i = _close_paren(toks, i, spelling) + 1
        while i < len(toks):
            t = toks[i]
            if t.text == ",":
                i += 1
                continue
            if t.kind != "name":
                issues.append(Issue("unknown_clause",
                                    f"unreadable clause text {line[t.start:]!r}"))
                break
            if i + 1 < len(toks) and toks[i + 1].text == "(":
                j = _close_paren(toks, i + 1, t.text)
                raws.append(_Raw(t.text, line[toks[i + 1].end:toks[j].start]))
                i = j + 1
            else:
                raws.append(_Raw(t.text, None))
                i += 1
        sub: list = []
        d = _generic(parser, spelling, end, raws, model, sub)
        issues += [s for s in sub if s.message not in
                   {x.message for x in issues}]
        return d, v, issues, True
    except GrammarError as e:
        issues.append(Issue(e.code, str(e).split(": ", 1)[-1]))
        return None, None, issues, False


def _vname(v: int) -> str:
    from offload.engine.catalog import spec_name
    return spec_name(v)


# --- directives of a file --------------------------------------------------------

def _is_f_comment(raw: str) -> bool:
    s = raw.lstrip()
    return not s or (s.startswith("!") and not _F_SENT.match(raw))


def _strip_bang(text: str) -> str:
    quote = None
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "!":
            return text[:i]
    return text


def fortran_items(text: str):
    """(first line, last line, kind, text): kind "dir" (raw directive text,
    continuation lines included, model in the text), "stmt" (one
    lower-cased statement, continuation joined, comments stripped)."""
    lines = text.splitlines()
    n = 0
    while n < len(lines):
        raw = lines[n]
        start = n + 1
        if _F_SENT.match(raw):
            group = [raw]
            while _strip_bang(_F_SENT.sub("", group[-1], count=1)
                              ).rstrip().endswith("&"):
                n += 1
                while n < len(lines) and _is_f_comment(lines[n]):
                    n += 1
                if n >= len(lines):
                    break
                group.append(lines[n])
            n += 1
            yield start, n, "dir", "\n".join(group)
            continue
        s = raw.lstrip()
        if _is_f_comment(raw) or s.startswith("#") or (
                s.startswith("!$") and not re.match(r"!\$[\s&]", s)):
            n += 1
            continue
        if s.startswith("!$"):
            s = s[2:]
        body = _strip_bang(s).rstrip()
        while body.endswith("&"):
            n += 1
            while n < len(lines) and _is_f_comment(lines[n]):
                n += 1
            if n >= len(lines):
                break
            nxt = _strip_bang(lines[n].lstrip()).rstrip()
            body = body[:-1] + (nxt[1:] if nxt.startswith("&") else nxt)
        n += 1
        for part in _split_semicolons(body):
            yield start, n, "stmt", " ".join(part.lower().split())


def _split_semicolons(text: str) -> list[str]:
    parts, cur, quote = [], [], None
    for ch in text:
        if quote:
            quote = None if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif ch == ";":
            parts.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    parts.append("".join(cur))
    return [p for p in parts if p.strip()]


_DO = re.compile(r"^(?:[a-z_]\w*\s*:\s*)?do(?![\w=])\s*(\d+)?")
_END_DO = re.compile(r"^end\s*do\b")
_LABELLED = re.compile(r"^(\d+)\s+(.*)$")
_UNIT_HEAD = re.compile(
    r"^(?:program\s+\w+|module\s+(?!procedure\b)\w+|submodule\s*\(.*|"
    r"(?:[\w(),=*:]+\s+)*?(?:subroutine|function)\s+([a-z_]\w*)\s*"
    r"(?:\(.*|result\b.*|bind\b.*)?)$")
_UNIT_END = re.compile(r"^end(?:\s*(?:program|subroutine|function|module|"
                       r"submodule|procedure|block\s*data)\b.*)?$")


def _assoc(name: str | None, model: str) -> str:
    if not name:
        return "standalone"
    from offload.engine.rules import association
    try:
        return association(name, model)
    except Exception:
        return "standalone"


def _fortran_occurrences(f: SourceFile, version: int) -> list[Occurrence]:
    occs: list[Occurrence] = []
    stack: list = []        # ["dir", idx, kind, pending] / ["do", label] /
    #                         ["unit", name, start, declare]
    units: list = []        # (start, end, device)
    just_closed = None
    pending_stmt: list = []  # one-statement constructs waiting for theirs

    def close(frame, line):
        if frame[0] == "dir":
            o = occs[frame[1]]
            o.region = (o.line, line)
        elif frame[0] == "unit":
            units.append((frame[2], line, frame[3]))

    for first, last, kind, text in fortran_items(f.text):
        if kind == "dir":
            model = _F_SENT.match(text).group(1).lower()
            v = version if model == "omp" else 34
            d, pv, issues, tol = parse_one(text, "f90", v, model)
            o = Occurrence(f.path, first, last, text.strip(), model, "f90",
                           d.name if d else None, bool(d and d.end),
                           list(d.clauses) if d else [],
                           d.atoms if d else frozenset(), pv, issues,
                           tolerant=tol)
            if d is None:
                o.issues.insert(0, Issue("unknown_directive",
                                         issues[0].message if issues
                                         else "unreadable directive"))
            if o.end:
                if just_closed is not None and \
                        occs[just_closed].name == o.name:
                    just_closed = None
                    continue
                for k in range(len(stack) - 1, -1, -1):
                    fr = stack[k]
                    if fr[0] == "dir" and occs[fr[1]].name == o.name:
                        for g in reversed(stack[k:]):
                            close(g, first)
                        del stack[k:]
                        break
                    if fr[0] == "unit":
                        break
                just_closed = None
                continue
            just_closed = None
            idx = len(occs)
            occs.append(o)
            how = _assoc(o.name, model)
            if model == "acc" and o.name and o.name.endswith("loop"):
                how = "loop"
            if how == "block":
                stack.append(["dir", idx, "block", False])
            elif how == "loop":
                stack.append(["dir", idx, "loop", True])
            elif how == "statement":
                pending_stmt.append(idx)
            # a declare target / routine in a procedure's own
            # specification part makes the procedure device code
            if o.name in ("declare target", "routine") and not any(
                    c.name in ("to", "enter", "link") or c.args
                    for c in o.clauses
                    if c.name != "device_type") and not any(
                    c.name == "device_type" and "host" in
                    " ".join(c.args).lower() for c in o.clauses):
                for fr in reversed(stack):
                    if fr[0] == "unit":
                        fr[3] = True
                        break
            continue
        # a statement
        just_closed = None
        if pending_stmt:
            for idx in pending_stmt:
                occs[idx].region = (occs[idx].line, last)
            pending_stmt = []
        m = _LABELLED.match(text)
        label, body = (m.group(1), m.group(2)) if m else (None, text)
        if label:
            # a labelled statement ends the label DO loops waiting for it
            while stack and stack[-1][0] == "do" and stack[-1][1] == label:
                stack.pop()
                _end_loop_dirs(stack, occs, first)
        dm = _DO.match(body)
        if dm:
            top = stack[-1] if stack else None
            if top and top[0] == "dir" and top[2] == "loop" and top[3]:
                top[3] = False
            stack.append(["do", dm.group(1)])
            continue
        if _END_DO.match(body):
            for k in range(len(stack) - 1, -1, -1):
                if stack[k][0] == "do":
                    for g in reversed(stack[k + 1:]):
                        close(g, first)
                    del stack[k:]
                    break
            closed = _end_loop_dirs(stack, occs, first)
            if closed is not None:
                just_closed = closed
            continue
        hm = _UNIT_HEAD.match(body)
        if hm and not body.startswith("end"):
            stack.append(["unit", hm.group(1) or "", first, False])
            continue
        if _UNIT_END.match(body):
            for k in range(len(stack) - 1, -1, -1):
                if stack[k][0] == "unit":
                    for g in reversed(stack[k:]):
                        close(g, first)
                    del stack[k:]
                    break
            continue
        # a statement after a loop directive that is not a DO: the
        # construct has no loop (malformed or an unsupported form)
        top = stack[-1] if stack else None
        if top and top[0] == "dir" and top[2] == "loop" and top[3]:
            occs[top[1]].issues.append(Issue(
                "region", "no DO loop follows the loop directive"))
            close(top, first)
            stack.pop()
    end_line = len(f.text.splitlines())
    for fr in reversed(stack):
        close(fr, end_line)
    for idx in pending_stmt:
        occs[idx].region = (occs[idx].line, end_line)
    for o in occs:
        if any(a <= o.line <= b and dev for a, b, dev in units):
            o.device_unit = True
    return occs


def _end_loop_dirs(stack, occs, line):
    """Close the loop directives whose DO loop just ended; the last one
    closed (its optional end directive may follow)."""
    closed = None
    while stack and stack[-1][0] == "dir" and stack[-1][2] == "loop" \
            and not stack[-1][3]:
        fr = stack.pop()
        occs[fr[1]].region = (occs[fr[1]].line, line)
        closed = fr[1]
    return closed


# --- C ---------------------------------------------------------------------------

_PP = re.compile(r"#(?:\\\n|[^\n])*")
_C_TOKEN = re.compile(r"""
    (?P<id>[A-Za-z_]\w*)
  | (?P<str>"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')
  | (?P<op>[{}();])
  | (?P<other>[^\s\w{}();#"']+|\d\w*)
""", re.X)


def _c_tokens(text: str):
    """(kind, text, first line, last line) tokens of a comment-free C
    source; a preprocessor line (with its continuations) is one token."""
    from offload.engine.c_program import _strip_comments
    src = _strip_comments(text)
    pos, line, out = 0, 1, []
    while pos < len(src):
        ch = src[pos]
        if ch == "\n":
            line += 1
            pos += 1
            continue
        if ch.isspace():
            pos += 1
            continue
        if ch == "#" and not src[src.rfind("\n", 0, pos) + 1:pos].strip():
            m = _PP.match(src, pos)
        else:
            m = _C_TOKEN.match(src, pos)
        if not m or m.end() == pos:
            pos += 1
            continue
        tok = m.group(0)
        kind = "pp" if m.re is _PP else m.lastgroup
        nl = tok.count("\n")
        out.append((kind, tok, line, line + nl))
        line += nl
        pos = m.end()
    return out


def _c_statement_end(toks, i):
    """Index of the last token of the statement starting at toks[i]."""
    if i >= len(toks):
        return len(toks) - 1
    kind, t = toks[i][0], toks[i][1]
    if kind == "pp":
        return _c_statement_end(toks, i + 1)
    if t == "{":
        depth = 0
        for j in range(i, len(toks)):
            if toks[j][1] == "{":
                depth += 1
            elif toks[j][1] == "}":
                depth -= 1
                if depth == 0:
                    return j
        return len(toks) - 1
    if t in ("for", "while", "if", "switch"):
        j = i + 1
        if j < len(toks) and toks[j][1] == "(":
            depth = 0
            for k in range(j, len(toks)):
                if toks[k][1] == "(":
                    depth += 1
                elif toks[k][1] == ")":
                    depth -= 1
                    if depth == 0:
                        j = k
                        break
        end = _c_statement_end(toks, j + 1)
        if t == "if" and end + 1 < len(toks) and toks[end + 1][1] == "else":
            end = _c_statement_end(toks, end + 2)
        return end
    if t == "do":
        end = _c_statement_end(toks, i + 1)
        for k in range(end + 1, len(toks)):
            if toks[k][1] == ";":
                return k
        return len(toks) - 1
    depth = 0
    for j in range(i, len(toks)):
        x = toks[j][1]
        if x in "({":
            depth += 1
        elif x in ")}":
            depth -= 1
            if depth < 0:
                return j - 1
        elif x == ";" and depth <= 0:
            return j
    return len(toks) - 1


def _c_occurrences(f: SourceFile, version: int) -> list[Occurrence]:
    toks = _c_tokens(f.text)
    occs: list[Occurrence] = []
    ranges: list = []          # declare target ranges [start, end|None, host]
    for i, (kind, t, l0, l1) in enumerate(toks):
        if kind != "pp":
            continue
        m = _C_SENT.match(t)
        if not m:
            continue
        model = m.group(1).lower()
        v = version if model == "omp" else 34
        if model == "acc" and not PARSE_C_ACC:
            o = Occurrence(f.path, l0, l1, t.strip(), model, "c",
                           issues=[Issue("unknown_directive",
                                         "OpenACC in C is not in the "
                                         "catalog (OpenACC is measured in "
                                         "Fortran only)")])
            occs.append(o)
            continue
        d, pv, issues, tol = parse_one(t, "c", v, model)
        o = Occurrence(f.path, l0, l1, " ".join(t.replace("\\\n", " ")
                                                 .split()), model, "c",
                       d.name if d else None, False,
                       list(d.clauses) if d else [],
                       d.atoms if d else frozenset(), pv, issues,
                       tolerant=tol)
        if d is None:
            o.issues.insert(0, Issue("unknown_directive",
                                     issues[0].message if issues
                                     else "unreadable directive"))
        name = o.name or ""
        if model == "acc" and name == "routine" and not re.match(
                r"\s*#\s*pragma\s+acc\s+routine\s*\(", t):
            # A routine directive without a name
            # applies to the function definition that follows it (OpenACC
            # 3.4 §2.15.1): that function's body is device code
            body = _c_next_function(toks, i)
            if body is not None:
                ranges.append([l0, body, False])
        if name in ("begin declare target",) or (
                name == "declare target" and not o.clauses):
            ranges.append([l0, None, False])
        elif name == "declare target" and all(
                c.name == "device_type" for c in o.clauses):
            ranges.append([l0, None, any("host" in " ".join(c.args)
                                         for c in o.clauses)])
        elif name == "end declare target":
            for r in reversed(ranges):
                if r[1] is None:
                    r[1] = l0
                    break
        how = _assoc(o.name, model)
        if how in ("block", "loop", "statement") and o.name:
            e = _c_statement_end(toks, i + 1)
            o.region = (l0, toks[e][3] if e < len(toks) else l1)
        occs.append(o)
    nlines = len(f.text.splitlines())
    for o in occs:
        if any(a < o.line < (b or nlines + 1) and not host
               for a, b, host in ranges):
            o.device_unit = True
    return occs


def _c_next_function(toks, i):
    """The last line of the brace block of the function definition after
    token i (the first top-level `{` that follows a `)`), or None."""
    prev = None
    for j in range(i + 1, len(toks)):
        kind, t = toks[j][0], toks[j][1]
        if kind == "pp":
            continue
        if t == "{" and prev == ")":
            e = _c_statement_end(toks, j)
            return toks[e][3] if e < len(toks) else None
        if t in (";", "}") and prev != ")":
            if t == ";":
                return None
        prev = t
    return None


# --- the program -------------------------------------------------------------------

def _machinery(name: str | None, model: str) -> bool:
    if not name:
        return False
    if model == "acc":
        return name in ACC_MACHINERY or name.split()[0] in (
            "enter", "exit")
    # declarations that apply wherever the procedure runs (a declare simd
    # or declare variant procedure may be called from device code)
    return name in OMP_MACHINERY or name in (
        "end declare target", "declare simd", "declare variant",
        "begin declare variant", "end declare variant")


def build(files: list[SourceFile], version: int = 52) -> Program:
    """The program of `files` (one program, modules across files)."""
    occs: list[Occurrence] = []
    notes = []
    for f in files:
        if f.lang is None:
            notes.append((f.path, 0, "not read: only free-form "
                          "Fortran (.f90 .F90 ...) and C (.c .h) are read"))
            continue
        try:
            got = (_c_occurrences(f, version) if f.lang == "c"
                   else _fortran_occurrences(f, version))
        except Exception as e:     # never silently: the file is a note
            notes.append((f.path, 0, f"not read: {type(e).__name__}: {e}"))
            continue
        occs.extend(got)
    # parents by region containment: the latest earlier occurrence of the
    # same file whose region contains the line (a stack of open
    # regions per file, linear in the occurrences)
    open_: dict = {}
    for i, o in enumerate(occs):
        st = open_.setdefault(o.file, [])
        while st and occs[st[-1]].region[1] < o.line:
            st.pop()
        best = None
        for k in reversed(st):
            p = occs[k]
            if p.region[0] <= o.line <= p.region[1] and o.line > p.last_line:
                best = k
                break
        o.parent = best
        if o.region:
            st.append(i)
    prog = Program(files, occs, version, notes)
    has_tasks = any(is_compute(o.name, o.model) or o.name in _DEVICE_DATA
                    for o in occs
                    if any(c.name in ("nowait", "depend", "in_reduction")
                           for c in o.clauses))
    for i, o in enumerate(occs):
        anc = prog.ancestors(i)
        if is_compute(o.name, o.model):
            o.kind = "compute"
        elif any(is_compute(occs[a].name, occs[a].model) for a in anc) \
                or o.device_unit:
            o.kind = "device"
        elif _machinery(o.name, o.model) or (
                o.model == "omp" and o.name in ("taskwait", "taskgroup")
                and has_tasks):
            o.kind = "machinery"
        else:
            o.kind = "host"
    return prog


def load(paths, version: int = 52) -> Program:
    return build(read_files(paths), version)


def from_texts(files: list[tuple[str, str]], version: int = 52) -> Program:
    """A program from (name, text) pairs (tests, the validation)."""
    return build([SourceFile(n, t, lang_of(n)) for n, t in files], version)
