"""A small model of a free-form Fortran OpenMP source.

Logical statements (``&`` continuations joined, comments stripped), the
directives among them with their raw clauses (name and argument text,
so a transform can re-emit a clause verbatim), the declarations of the
main program and a statement-level read/write split. Used by
``offload.engine.expected`` (the sequential-elision applicability analysis)
and ``offload.engine.transforms`` (the metamorphic rewrites). It handles the
shapes the catalog generator (``offload.engine.gen``) and the fuzzer
(``offload.engine.fuzz``) write; anything else raises ``SourceError`` so the
caller can report the source as out of scope instead of guessing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from offload.engine.grammar import GrammarError, _strip_bang_comment, \
    parse_directive


class SourceError(Exception):
    """A source shape this model does not handle."""


_SENT = re.compile(r"^(\s*)!\$omp(&?)", re.I)
_COND = re.compile(r"^\s*!\$\s", re.I)       # conditional compilation
_ACC = re.compile(r"^\s*!\$acc", re.I)

# Fortran intrinsic procedures and keywords that may appear where a
# variable could (never treated as program variables).
KEYWORDS = frozenset("""
if then else end do while call print write read allocate deallocate
mod modulo merge min max iand ior ieor ishft abs sum all any count int
real dble size lbound ubound present associated c_loc c_f_pointer
c_associated not and or eqv neqv true false program module contains
function subroutine return stop continue exit cycle use only implicit
none integer logical character parameter allocatable target dimension
intent in out inout kind len trim adjustl sign transfer reshape spread
pack maxval minval product dot_product matmul shape iachar achar
""".split())


@dataclass
class Stmt:
    first: int          # first physical line (0-based)
    last: int           # last physical line
    text: str           # logical text without sentinel / comment
    kind: str           # "dir" | "code" | "condcomp" | "acc"
    indent: str = ""

    @property
    def lower(self) -> str:
        return self.text.lower()


@dataclass
class RawClause:
    name: str
    arg: str | None = None      # text inside the parentheses

    def text(self) -> str:
        return self.name if self.arg is None else f"{self.name}({self.arg})"

    def pieces(self) -> list[str]:
        """Top-level comma pieces of the argument."""
        return split_top(self.arg or "", ",")

    def items(self) -> list[str]:
        """The list items (after the last top-level ':' modifier part)."""
        a = self.arg or ""
        parts = split_top(a, ":")
        body = parts[-1] if len(parts) > 1 else a
        return [x for x in split_top(body, ",") if x]

    def modifiers(self) -> list[str]:
        """The words before the last top-level ':' (lowercased)."""
        a = self.arg or ""
        parts = split_top(a, ":")
        if len(parts) < 2:
            return []
        return [w.strip().lower() for p in parts[:-1]
                for w in split_top(p, ",") if w.strip()]


@dataclass
class Dir:
    stmt: Stmt
    name: str               # lowercase words, "end " prefix for an end
    end: bool
    clauses: list[RawClause] = field(default_factory=list)
    args: str | None = None  # "declare target(x)", "critical(name)"

    @property
    def base(self) -> str:
        return self.name[4:] if self.end else self.name

    @property
    def leaves(self) -> list[str]:
        return leaves_of(self.base)

    def clause(self, name: str) -> list[RawClause]:
        return [c for c in self.clauses if c.name == name]


def leaves_of(name: str) -> list[str]:
    """Leaf constructs of a (possibly combined) directive name."""
    words = name.split()
    out, i = [], 0
    while i < len(words):
        w = words[i]
        if w in ("target", "teams", "distribute", "parallel", "do", "simd",
                 "loop", "masked", "taskloop", "workshare", "sections",
                 "single", "task", "taskgroup", "critical", "ordered",
                 "atomic", "scan", "barrier", "taskwait", "masked",
                 "master", "workdistribute", "scope", "section", "flush",
                 "error", "nothing", "requires", "allocate", "allocators",
                 "depobj", "dispatch", "interop", "metadirective", "tile",
                 "unroll", "assume", "assumes", "cancel", "threadprivate"):
            if w == "target" and i + 1 < len(words) and words[i + 1] in (
                    "data", "enter", "exit", "update"):
                j = i + 2 if words[i + 1] == "data" or words[i + 1] == \
                    "update" else i + 3
                out.append(" ".join(words[i:j]))
                i = j
                continue
            out.append(w)
            i += 1
        elif w == "declare":
            out.append(" ".join(words[i:i + 2]))
            i += 2
        elif w in ("cancellation",):
            out.append(" ".join(words[i:i + 2]))
            i += 2
        else:
            out.append(w)
            i += 1
    return out


def split_top(text: str, sep: str) -> list[str]:
    """`text` split at top-level `sep` (outside parentheses and quotes),
    pieces stripped."""
    out, depth, quote, cur = [], 0, None, []
    for ch in text:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif ch == sep and depth == 0:
            out.append("".join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    out.append("".join(cur).strip())
    return out


def statements(source: str) -> list[Stmt]:
    """Logical statements of a free-form source (blank and comment-only
    lines dropped; `;` separated statements are not split: the generated
    sources do not use them)."""
    lines = source.splitlines()
    out: list[Stmt] = []
    k = 0
    while k < len(lines):
        raw = lines[k]
        if _COND.match(raw):
            out.append(Stmt(k, k, raw.strip(), "condcomp"))
            k += 1
            continue
        if _ACC.match(raw):
            out.append(Stmt(k, k, raw.strip(), "acc"))
            k += 1
            continue
        m = _SENT.match(raw)
        if m:
            first, parts = k, []
            indent = m.group(1)
            while True:
                raw = lines[k]
                mm = _SENT.match(raw)
                if mm is None:
                    raise SourceError(f"line {k + 1}: continuation is not a "
                                      "directive line")
                rest = raw[mm.end():]
                if parts:
                    rest = rest.lstrip()
                    if rest.startswith("&"):
                        rest = rest[1:]
                rest = _strip_bang_comment(rest).rstrip()
                cont = rest.endswith("&")
                if cont:
                    rest = rest[:-1]
                parts.append(rest.strip())
                if not cont:
                    break
                k += 1
            out.append(Stmt(first, k, " ".join(p for p in parts if p), "dir",
                            indent))
            k += 1
            continue
        body = _strip_bang_comment(raw).rstrip()
        if not body.strip():
            k += 1
            continue
        first, parts = k, []
        indent = re.match(r"\s*", raw).group()
        while True:
            seg = _strip_bang_comment(lines[k]).strip()
            if parts and seg.startswith("&"):
                seg = seg[1:].strip()
            cont = seg.endswith("&")
            if cont:
                seg = seg[:-1].strip()
            parts.append(seg)
            if not cont:
                break
            k += 1
            if k >= len(lines):
                raise SourceError("source ends in a continuation")
        out.append(Stmt(first, k, " ".join(p for p in parts if p), "code",
                        indent))
        k += 1
    return out


def _clauses(text: str) -> list[RawClause]:
    out, i, n = [], 0, len(text)
    while i < n:
        while i < n and text[i] in " ,\t":
            i += 1
        if i >= n:
            break
        m = re.match(r"[A-Za-z_][A-Za-z0-9_]*", text[i:])
        if not m:
            raise SourceError(f"cannot split clauses of {text!r}")
        name = m.group().lower()
        i += m.end()
        j = i
        while j < n and text[j] == " ":
            j += 1
        if j < n and text[j] == "(":
            depth, k = 0, j
            while k < n:
                if text[k] == "(":
                    depth += 1
                elif text[k] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                k += 1
            if depth:
                raise SourceError(f"unbalanced parentheses in {text!r}")
            out.append(RawClause(name, text[j + 1:k].strip()))
            i = k + 1
        else:
            out.append(RawClause(name))
    return out


def parse_dir(stmt: Stmt, version: int = 52) -> Dir:
    """The directive of a "dir" statement: its name (as the grammar names
    it), whether it is an end directive, its raw clauses."""
    try:
        d = parse_directive("!$omp " + stmt.text, "fortran", version)
    except GrammarError as e:
        raise SourceError(f"line {stmt.first + 1}: {e}") from e
    key = re.sub(r"\s*\(.*\)$", "", d.name).replace("_", " ").lower()
    # the name in the text may be spaced differently ("enddo"): match it
    # character by character with optional blanks
    want = ("end" if d.end else "") + key.replace(" ", "")
    m = re.match(r"[\s_]*".join(re.escape(ch) for ch in want) + r"\b",
                 stmt.text, re.I)
    if not m:
        raise SourceError(f"line {stmt.first + 1}: cannot find the name "
                          f"{key!r} in {stmt.text!r}")
    rest = stmt.text[m.end():].strip()
    args = None
    if rest.startswith("("):
        depth = 0
        for k, ch in enumerate(rest):
            depth += ch == "("
            depth -= ch == ")"
            if depth == 0:
                args, rest = rest[1:k].strip(), rest[k + 1:].strip()
                break
    name =("end " if d.end else "") + key
    return Dir(stmt, name, d.end, _clauses(rest), args)


# --- declarations ------------------------------------------------------------

_TYPE = re.compile(r"^(integer|logical|real|double\s+precision|complex|"
                   r"character|type\s*\(\s*\w+\s*\))(?=\W|$)(.*)$", re.I)


@dataclass
class Var:
    name: str
    type: str
    rank: int = 0
    extents: tuple = ()     # declared extents (text) of an explicit shape
    allocatable: bool = False
    parameter: bool = False
    pointer: bool = False
    target: bool = False
    intent: str = ""        # "in" | "out" | "inout" | ""
    optional: bool = False
    value: bool = False


def _decl_entities(rest: str) -> tuple[list[str], list[tuple]]:
    """Attributes and (name, dims-text or None) of a type declaration's
    remainder (after the type keyword and optional kind)."""
    if "::" in rest:
        attrs_txt, ents_txt = rest.split("::", 1)
    else:
        attrs_txt, ents_txt = "", rest
    attrs = [a.strip().lower() for a in split_top(attrs_txt, ",")
             if a.strip()]
    ents = []
    for e in split_top(ents_txt, ","):
        e = split_top(e, "=")[0].strip() if "=" in e and "==" not in e \
            else e.strip()
        m = re.match(r"(\w+)\s*(\((.*)\))?", e)
        if m:
            ents.append((m.group(1).lower(), m.group(3)))
    return attrs, ents


_TYPEDEF = re.compile(r"^type(?!\s*\()\s*(?:,[^:]*)?(?:::)?\s*(\w+)\s*$",
                      re.I)
_END_TYPE = re.compile(r"^end\s*type\b", re.I)


def type_defs(stmts: list[Stmt]) -> dict[str, dict[str, Var]]:
    """Derived type definitions: type name -> {component: Var} (in
    declaration order). A component with a default initialisation is an
    ordinary component here (its value is defined from the start)."""
    out: dict[str, dict[str, Var]] = {}
    cur = None
    for s in stmts:
        if s.kind != "code":
            continue
        if cur is None:
            m = _TYPEDEF.match(s.text)
            if m:
                cur = out.setdefault(m.group(1).lower(), {})
            continue
        if _END_TYPE.match(s.text):
            cur = None
            continue
        cur.update(_decl_vars(s))
    return out


def _decl_vars(s: Stmt) -> dict[str, Var]:
    m = _TYPE.match(s.text)
    if not m:
        return {}
    tname = re.sub(r"\s+", " ", m.group(1).lower())
    rest = m.group(2)
    if rest.lstrip().startswith("function"):
        return {}
    # a kind selector right after the type: integer(8) :: x
    rest = re.sub(r"^\s*\([^)]*\)", "", rest)
    attrs, ents = _decl_entities(rest.lstrip(", "))
    dim_attr = next((a for a in attrs if a.startswith("dimension")), None)
    out = {}
    for name, dims in ents:
        dims = dims if dims is not None else (
            dim_attr[dim_attr.index("(") + 1:-1] if dim_attr else None)
        ext = tuple(x.strip().lower() for x in split_top(dims, ",")) \
            if dims else ()
        out[name] = Var(name, tname, len(ext),
                        ext if all(x not in (":", "") for x in ext) else (),
                        "allocatable" in attrs, "parameter" in attrs,
                        "pointer" in attrs, "target" in attrs,
                        next((a.split("(", 1)[1].rstrip(")").strip()
                              for a in attrs if a.startswith("intent")), ""),
                        "optional" in attrs, "value" in attrs)
    return out


def declarations(stmts: list[Stmt], lo: int = 0,
                 hi: int | None = None) -> dict[str, Var]:
    """The variables declared in the specification parts of the sources'
    program units in stmts[lo:hi] (later units shadow nothing: the
    generated programs use distinct names; a module function's dummies are
    included too, which is harmless because the analysis only looks at the
    main program). Components of derived type definitions are not
    variables (``type_defs``)."""
    out: dict[str, Var] = {}
    in_type = False
    for s in stmts[lo:hi]:
        if s.kind != "code":
            continue
        if in_type:
            in_type = not _END_TYPE.match(s.text)
            continue
        if _TYPEDEF.match(s.text):
            in_type = True
            continue
        out.update(_decl_vars(s))
    return out


def _spec_end(stmts: list[Stmt], i: int, end: int) -> int:
    """Index of the first statement of stmts[i:end] after the
    specification part that starts at i: USE, IMPLICIT, type declarations,
    derived type definitions, interface blocks and the directives that may
    stand among them (declare, requires, threadprivate, error, nothing,
    assumes)."""
    while i < end:
        t = stmts[i]
        if t.kind == "dir":
            if re.match(r"(declare|requires|threadprivate|error|nothing|"
                        r"assumes)(\b|_)", t.lower):
                i += 1
                continue
            return i
        if t.kind != "code":
            return i
        low = t.lower
        if _TYPEDEF.match(t.text):
            while i < end and not _END_TYPE.match(stmts[i].text):
                i += 1
            i += 1
            continue
        if re.match(r"(abstract\s+)?interface\b", low):
            while i < end and not re.match(r"end\s*interface\b",
                                           stmts[i].lower):
                i += 1
            i += 1
            continue
        if re.match(r"(use|implicit|external|intrinsic|save)\b", low) or \
                _TYPE.match(t.text):
            i += 1
            continue
        return i
    return i


def main_program(stmts: list[Stmt]) -> tuple[int, int]:
    """Indexes (into `stmts`) of the main program's first executable
    statement and of the end of its execution part (its CONTAINS, or its
    `end program`)."""
    start = next((i for i, s in enumerate(stmts)
                  if s.kind == "code" and re.match(r"program\s+\w+", s.lower)),
                 None)
    if start is None:
        raise SourceError("no main program")
    end = next((i for i in range(start + 1, len(stmts))
                if stmts[i].kind == "code"
                and re.match(r"end\s*program\b", stmts[i].lower)), None)
    if end is None:
        # a bare `end` also ends a main program (the
        # cce21-defaultmap-aggregate-flag finding ends that way); an
        # internal subprogram must say `end subroutine`/`end function`
        end = next((i for i in range(len(stmts) - 1, start, -1)
                    if stmts[i].kind == "code"
                    and stmts[i].lower.strip() == "end"), None)
    if end is None:
        raise SourceError("no end program")
    i = _spec_end(stmts, start + 1, end)
    stop = next((k for k in range(i, end) if stmts[k].kind == "code"
                 and stmts[k].lower == "contains"), end)
    return i, stop


@dataclass
class Procedure:
    """An internal subroutine of the main program."""
    name: str
    dummies: list[str]
    decls: dict[str, Var]      # its own declarations (dummies and locals)
    body: list[Stmt]           # its execution part


def internal_procedures(stmts: list[Stmt]) -> dict[str, Procedure]:
    """The internal subroutines of the main program (after its CONTAINS).
    An internal function, a nested CONTAINS or an ENTRY is SourceError."""
    _, stop = main_program(stmts)
    end = next(i for i in range(stop, len(stmts))
               if stmts[i].kind == "code"
               and re.match(r"end\s*program\b", stmts[i].lower))
    out: dict[str, Procedure] = {}
    k = stop + 1 if stop < end else end
    while k < end:
        s = stmts[k]
        m = re.match(r"(?:(?:recursive|pure|impure|elemental|module)\s+)*"
                     r"subroutine\s+(\w+)\s*(?:\((.*)\))?\s*$", s.text,
                     re.I)
        if s.kind != "code" or m is None:
            raise SourceError(f"line {s.first + 1}: internal procedure not "
                              f"understood: {s.text!r}")
        name = m.group(1).lower()
        dummies = [d.strip().lower() for d in split_top(m.group(2) or "", ",")
                   if d.strip()]
        fin = next((j for j in range(k + 1, end) if stmts[j].kind == "code"
                    and re.match(r"end\s*subroutine\b", stmts[j].lower)),
                   None)
        if fin is None:
            raise SourceError(f"line {s.first + 1}: no end subroutine")
        b = _spec_end(stmts, k + 1, fin)
        body = stmts[b:fin]
        for t in body:
            if t.kind == "code" and re.match(r"(contains|entry|return)\b",
                                             t.lower):
                raise SourceError(f"line {t.first + 1}: {t.lower.split()[0]} "
                                  f"in internal procedure {name}")
        out[name] = Procedure(name, dummies, declarations(stmts, k + 1, b),
                              body)
        k = fin + 1
    return out


def rename(text: str, mapping: dict[str, str]) -> str:
    """`text` with every name of `mapping` (lowercase keys) replaced, outside
    string literals and not as a component name (after `%`) or a keyword
    argument name (before a single `=` inside parentheses)."""
    if not mapping:
        return text
    out, k, n = [], 0, len(text)
    while k < n:
        ch = text[k]
        if ch in "'\"":
            j = k + 1
            while j < n and text[j] != ch:
                j += 1
            out.append(text[k:j + 1])
            k = j + 1
            continue
        m = re.match(r"[A-Za-z_]\w*", text[k:])
        if m and (k == 0 or not (text[k - 1].isalnum() or
                                 text[k - 1] in "_%")):
            w = m.group()
            prev = text[:k].rstrip()
            after = text[k + len(w):].lstrip()
            # a component name may also be written after "% "
            new = mapping.get(w.lower(), w)
            if prev.endswith("%") or (after.startswith("=") and
                                      not after.startswith("==") and
                                      text[:k].count("(") >
                                      text[:k].count(")")):
                new = w
            out.append(new)
            k += len(w)
            continue
        if m:
            out.append(m.group())
            k += len(m.group())
            continue
        out.append(ch)
        k += 1
    return "".join(out)


def identifiers(text: str) -> list[str]:
    """Lowercase names in an expression, outside string literals, without
    keyword arguments and `kind` suffixes (31_8)."""
    t = re.sub(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"", " ", text)
    t = re.sub(r"\b\d+_\w+", " ", t)
    t = re.sub(r"\.\w+\.", " ", t)       # .true. .and.
    return [w.lower() for w in re.findall(r"\b[A-Za-z_]\w*\b", t)]


def designators(text: str) -> list[str]:
    """Lowercase data references in an expression, outside string literals:
    a structure component reference is one path (``dr%nd%k(i)`` gives
    ``dr%nd%k``; ``ds(i)%u`` gives ``ds%u``), followed by the references in
    its subscripts. Function names come out as designators too (the
    analysis keeps only declared variables)."""
    t = re.sub(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"", " ", text)
    t = re.sub(r"\b\d+_\w+", " ", t)
    t = re.sub(r"\.\w+\.", " ", t)       # .true. .and.
    t = re.sub(r"\b\d+(\.\d*)?([de][+-]?\d+)?", " ", t, flags=re.I)
    out: list[str] = []
    n, k = len(t), 0
    while k < n:
        m = re.match(r"[A-Za-z_]\w*", t[k:])
        if not m or (k > 0 and (t[k - 1].isalnum() or t[k - 1] in "_%")):
            k += len(m.group()) if m else 1
            continue
        parts, inner = [m.group().lower()], []
        k += m.end()
        while True:
            j = k
            while j < n and t[j] == " ":
                j += 1
            if j < n and t[j] == "(":
                depth, e = 0, j
                while e < n:
                    depth += t[e] == "("
                    depth -= t[e] == ")"
                    if depth == 0:
                        break
                    e += 1
                inner.append(t[j + 1:e])
                k = e + 1
                continue
            if j < n and t[j] == "%":
                mm = re.match(r"\s*([A-Za-z_]\w*)", t[j + 1:])
                if mm:
                    parts.append(mm.group(1).lower())
                    k = j + 1 + mm.end()
                    continue
            break
        out.append("%".join(parts))
        for x in inner:
            out += designators(x)
    return out
