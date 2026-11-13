"""Kernel idiom miner: the statement shapes inside device regions of real code.

Generators vary directives and data mapping; this module lists what the
statements inside a kernel look like. It is a lexical reader. Counts are of source statements (a Fypp ``#:for`` body counts once,
a macro expands to nothing).

* Fortran, with MFC's Fypp macros: ``!$omp target`` and ``!$acc`` compute
  constructs, ``$:GPU_PARALLEL_LOOP``, ``#:call GPU_PARALLEL``, and device
  routines (``$:GPU_ROUTINE``, ``declare target``, ``!$acc routine``).
* C and C++: ``#pragma omp target`` and ``#pragma acc`` compute constructs,
  and bodies in ``declare target`` regions or after ``acc routine``.

``fortran_regions`` and ``c_regions`` return ``Region`` records whose
statements carry idiom tags (``TAGS``). ``tally`` counts, per tag, the
statements, files and distinct kernels using it."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

# --- the vocabulary ----------------------------------------------------------------------

TARGET_KINDS = ("var", "whole-array", "elem", "section", "comp", "elem-comp",
                "comp-elem", "comp-section", "elem-comp-elem",
                "elem-comp-section", "nested-comp", "ptr-comp",
                "ptr-comp-elem", "alloc-comp", "alloc-comp-elem", "deref")

INTRINSIC_GROUPS = {
    "merge": "merge", "min": "minmax", "max": "minmax", "fmin": "minmax",
    "fmax": "minmax", "mod": "mod", "modulo": "mod", "abs": "abs-sign",
    "fabs": "abs-sign", "sign": "abs-sign", "sqrt": "math", "exp": "math",
    "log": "math", "log10": "math", "sin": "math", "cos": "math",
    "tan": "math", "atan": "math", "atan2": "math", "tanh": "math",
    "sinh": "math", "cosh": "math", "asin": "math", "acos": "math",
    "pow": "math", "cbrt": "math", "hypot": "math", "fma": "math",
    "int": "convert", "real": "convert", "dble": "convert",
    "floor": "convert", "ceiling": "convert", "nint": "convert",
    "ceil": "convert", "sum": "reduce", "product": "reduce",
    "maxval": "reduce", "minval": "reduce", "any": "reduce", "all": "reduce",
    "count": "reduce", "norm2": "reduce", "dot_product": "reduce",
    "maxloc": "reduce", "minloc": "reduce", "matmul": "matmul",
    "size": "shape", "ubound": "shape", "lbound": "shape", "shape": "shape",
    "iand": "bit", "ior": "bit", "ieor": "bit", "ishft": "bit",
    "btest": "bit", "not": "bit", "spread": "array-construct",
    "pack": "array-construct", "cshift": "array-construct",
    "eoshift": "array-construct", "transpose": "array-construct",
    "huge": "inquiry", "tiny": "inquiry", "epsilon": "inquiry",
}
_FORTRAN_KW = {"if", "do", "while", "select", "case", "where", "forall",
               "associate", "call", "print", "write", "read", "allocate",
               "deallocate", "return", "stop", "exit", "cycle", "goto",
               "else", "end", "then", "elseif"}


@dataclass
class Region:
    kind: str                      # loop | block | routine
    file: str
    line: int
    lang: str = "f"
    collapse: int = 1
    name: str = ""
    stmts: list = field(default_factory=list)    # (line, set of tags)
    flags: set = field(default_factory=set)      # region-level idioms

    @property
    def rid(self) -> str:
        return f"{self.file}:{self.line}"

    def all_tags(self) -> set:
        out = set(self.flags)
        for _, t in self.stmts:
            out |= t
        return out


# --- text helpers -------------------------------------------------------------------------

def _strip_comment(line: str) -> str:
    q = None
    for i, ch in enumerate(line):
        if q:
            if ch == q:
                q = None
        elif ch in "'\"":
            q = ch
        elif ch == "!":
            return line[:i]
    return line


def _split_top(s: str, sep: str = ";") -> list[str]:
    out, buf, depth, q = [], [], 0, None
    for ch in s:
        if q:
            buf.append(ch)
            if ch == q:
                q = None
        elif ch in "'\"":
            q = ch
            buf.append(ch)
        elif ch in "([":
            depth += 1
            buf.append(ch)
        elif ch in ")]":
            depth -= 1
            buf.append(ch)
        elif ch == sep and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf))
    return [x.strip() for x in out if x.strip()]


def _match(s: str, i: int) -> int:
    """Index of the bracket that closes the one at s[i] (len(s) if none)."""
    pairs = {"(": ")", "[": "]", "{": "}"}
    open_, close = s[i], pairs[s[i]]
    depth = 0
    for j in range(i, len(s)):
        if s[j] == open_:
            depth += 1
        elif s[j] == close:
            depth -= 1
            if depth == 0:
                return j
    return len(s)


def _top_equals(s: str) -> int:
    """Index of the assignment '=' at depth 0, or -1 ('==', '<=', '=>' ..
    are not assignments here; '=>' is a pointer assignment)."""
    depth, q = 0, None
    for i, ch in enumerate(s):
        if q:
            if ch == q:
                q = None
            continue
        if ch in "'\"":
            q = ch
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif ch == "=" and depth == 0:
            prev = s[i - 1] if i else ""
            nxt = s[i + 1] if i + 1 < len(s) else ""
            if prev in "=<>/!" or nxt in "=>":
                continue
            return i
    return -1


# --- Fortran: logical lines ----------------------------------------------------------------

_SENTINEL = re.compile(r"^!\$(omp|acc)\s*&?\s*", re.I)


def _fortran_lines(text: str) -> list[tuple[int, str, str]]:
    """(line, kind, text): kind is dir (an OpenMP/OpenACC directive), fypp
    ($: or @: macro call), pp (a # line, Fypp #: included) or stmt."""
    raw = text.replace("\r", "").split("\n")
    out, i = [], 0
    while i < len(raw):
        ln, s = i + 1, raw[i].strip()
        i += 1
        if not s:
            continue
        if _SENTINEL.match(s) and not s.startswith("!$omp&"):
            body = _strip_comment_dir(s)
            while body.endswith("&") and i < len(raw):
                nxt = raw[i].strip()
                i += 1
                nxt = _SENTINEL.sub("", nxt) if _SENTINEL.match(nxt) else nxt
                body = body[:-1].rstrip() + " " + \
                    _strip_comment_dir(nxt).lstrip("& ")
            out.append((ln, "dir", re.sub(r"\s+", " ", body)))
            continue
        if s.startswith("!"):
            continue
        s = _strip_comment(s).rstrip()
        if not s:
            continue
        while s.endswith("&") and i < len(raw):
            nxt = _strip_comment(raw[i].strip()).strip()
            i += 1
            s = s[:-1].rstrip() + " " + nxt.lstrip("& ")
        s = re.sub(r"\$\{[^}]*\}\$", "X", s)
        s = re.sub(r"@\{[^}]*\}@", "X", s)
        if s.startswith("#"):
            out.append((ln, "pp", s))
        elif s.startswith(("$:", "@:")):
            out.append((ln, "fypp", s))
        else:
            for part in _split_top(s):
                out.append((ln, "stmt", part))
    return out


def _strip_comment_dir(s: str) -> str:
    # a directive's own '!' is its sentinel; a later ' !' starts a comment
    m = re.match(r"^(!\$\w+)(.*)$", s)
    if not m:
        return _strip_comment(s)
    return (m.group(1) + _strip_comment(m.group(2))).rstrip()


_PROC = re.compile(
    r"^(?:(?:pure|elemental|recursive|impure|module|non_recursive)\s+)*"
    r"(?:(?:real|integer|logical|complex|double\s+precision|character|type)"
    r"\s*(?:\([^)]*\))?\s*(?:\*\s*\d+)?\s+)?(subroutine|function)\s+(\w+)"
    r"\s*(?:\(([^)]*)\))?", re.I)
_END_PROC = re.compile(r"^end\s*(subroutine|function)\b", re.I)
_DO = re.compile(r"^(?:\w+\s*:\s*)?do\b(?!\s*while)|^(?:\w+\s*:\s*)?do\s+while\b",
                 re.I)
_ENDDO = re.compile(r"^end\s*do\b", re.I)


def _procs(lines):
    """[(name, start_idx, end_idx, dummies)] by position in lines."""
    stack, out = [], []
    for k, (_, kind, t) in enumerate(lines):
        if kind != "stmt":
            continue
        if _END_PROC.match(t):
            if stack:
                name, st, dums = stack.pop()
                out.append((name, st, k, dums))
            continue
        m = _PROC.match(t)
        if m and not t.lower().startswith("end"):
            dums = {d.strip().lower() for d in (m.group(3) or "").split(",")
                    if d.strip()}
            stack.append((m.group(2).lower(), k, dums))
    return out


_DECL_LIST = re.compile(r"\b(?:enter|to|link)\s*\(([^)]*)\)", re.I)


def _routine_marker(kind: str, t: str):
    """True when this line marks the enclosing procedure as device code;
    a list of names when it names procedures (declare target (f))."""
    tl = t.lower()
    if kind == "fypp" and tl.startswith("$:gpu_routine"):
        m = re.search(r"function_name\s*=\s*'(\w+)'", tl)
        return [m.group(1)] if m else True
    if kind == "dir":
        if re.match(r"!\$omp\s+declare\s+target\b", tl):
            rest = re.sub(r"device_type\s*\([^)]*\)", "", tl)
            names = re.findall(r"\(([^)]*)\)", rest)
            if not names:
                return True
            return [n.strip() for x in names for n in x.split(",")]
        m = re.match(r"!\$acc\s+routine\b\s*(?:\((\w+)\))?", tl)
        if m:
            return [m.group(1)] if m.group(1) else True
    return None


def device_routines(text: str) -> set:
    lines = _fortran_lines(text)
    procs = _procs(lines)
    names = {p[0] for p in procs}
    out = set()
    for k, (_, kind, t) in enumerate(lines):
        mk = _routine_marker(kind, t)
        if mk is None:
            continue
        if mk is True or isinstance(mk, list) and not any(
                n.lower() in names for n in mk):
            inner = [p for p in procs if p[1] < k < p[2]]
            if inner:
                out.add(min(inner, key=lambda p: p[2] - p[1])[0])
        else:
            out |= {n.lower() for n in mk if n.lower() in names}
    return out


def declared_pointer_components(text: str) -> tuple[set, set]:
    """(pointer components, allocatable components) of the derived types
    declared in the text."""
    ptr, alloc, in_type = set(), set(), False
    for _, kind, t in _fortran_lines(text):
        if kind != "stmt":
            continue
        tl = t.lower()
        if re.match(r"^type\s*(,[^:]*)?(::)?\s*\w+\s*$", tl) and \
                not tl.startswith("type ("):
            in_type = True
            continue
        if re.match(r"^end\s*type\b", tl):
            in_type = False
            continue
        if in_type and "::" in tl:
            attrs, ents = tl.split("::", 1)
            names = [re.match(r"\s*(\w+)", e).group(1)
                     for e in _split_top(ents, ",") if re.match(r"\s*\w+", e)]
            if re.search(r"\bpointer\b", attrs):
                ptr |= set(names)
            if re.search(r"\ballocatable\b", attrs):
                alloc |= set(names)
    return ptr, alloc


def declared_arrays(lines) -> set:
    """Names declared as arrays in the declaration statements of `lines`."""
    out = set()
    for _, kind, t in lines:
        if kind != "stmt" or "::" not in t:
            continue
        attrs, ents = t.lower().split("::", 1)
        dim = re.search(r"\bdimension\b", attrs)
        for e in _split_top(ents, ","):
            m = re.match(r"\s*(\w+)\s*(\()?", e)
            if m and (dim or m.group(2)):
                out.add(m.group(1))
    return out


# --- Fortran: classifying a statement ----------------------------------------------------

def _parts(lhs: str):
    """[(name, sub)] of an lvalue; sub is None, "elem" or "section"."""
    parts, depth, buf = [], 0, []
    for ch in lhs:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "%" and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    out = []
    for p in parts:
        p = p.strip()
        m = re.match(r"^(\w+)\s*(.*)$", p)
        if not m:
            return None
        name, rest = m.group(1), m.group(2)
        if not rest:
            out.append((name, None))
        elif rest.startswith("("):
            inner = rest[1:_match(rest, 0)]
            out.append((name, "section" if ":" in _depth0(inner) else "elem"))
        else:
            return None
    return out


def _depth0(s: str) -> str:
    out, depth = [], 0
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0:
            out.append(ch)
    return "".join(out)


def _target_kind(parts, arrays, ptr, alloc) -> str:
    n = len(parts)
    subs = [s for _, s in parts]
    if n == 1:
        s = subs[0]
        if s is None:
            return "whole-array" if parts[0][0] in arrays else "var"
        return s
    last_name, last_sub = parts[-1]
    if n >= 3:
        return "nested-comp"
    if last_name in ptr:
        return "ptr-comp-elem" if last_sub == "elem" else "ptr-comp"
    if last_name in alloc:
        return "alloc-comp-elem" if last_sub == "elem" else "alloc-comp"
    first = subs[0]
    if first is None and last_sub is None:
        return "comp"
    if first == "elem" and last_sub is None:
        return "elem-comp"
    if first is None and last_sub == "elem":
        return "comp-elem"
    if first is None and last_sub == "section":
        return "comp-section"
    if first == "elem" and last_sub == "elem":
        return "elem-comp-elem"
    if first == "elem" and last_sub == "section":
        return "elem-comp-section"
    return "comp"


def _ctor_spans(rhs: str):
    """[(start, end)] of array constructors '[...]' and '(/.../)'."""
    spans, i = [], 0
    while i < len(rhs):
        if rhs[i] == "[":
            j = _match(rhs, i)
            spans.append((i, j))
            i += 1
        elif rhs.startswith("(/", i):
            j = rhs.find("/)", i + 2)
            if j >= 0:
                spans.append((i, j + 1))
            i += 2
        else:
            i += 1
    return spans


def _rhs_tags(rhs: str, t: set):
    for name in re.findall(r"\b([a-z_]\w*)\s*\(", rhs):
        g = INTRINSIC_GROUPS.get(name)
        if g:
            t.add(f"intr.{g}")
    if "reshape" in rhs:
        t.add("ac.reshape")


def classify_fortran(stmt: str, arrays=(), pointer_comps=(), alloc_comps=(),
                     routines=()) -> set:
    arrays, ptr, alloc = set(arrays), set(pointer_comps), set(alloc_comps)
    s = re.sub(r"\s+", " ", stmt.strip().lower())
    t: set = set()
    if not s:
        return t
    s = re.sub(r"^\d+\s+", "", s)                      # a statement label
    if re.match(r"^(?:\w+\s*:\s*)?do\s+while\b", s):
        t.add("ctl.do-while")
        return t
    if re.match(r"^(?:\w+\s*:\s*)?do\s+concurrent\b", s):
        t.add("ctl.do-concurrent")
        return t
    if re.match(r"^(?:\w+\s*:\s*)?do\b", s):
        t.add("ctl.do")
        return t
    if re.match(r"^end\b|^else\s*$|^case\b|^continue$|^contains$|^use\b|"
                r"^implicit\b|^then$", s):
        return t
    if re.match(r"^else\s*if\b", s):
        t.add("ctl.else-if")
        return t
    m = re.match(r"^(?:\w+\s*:\s*)?if\s*\(", s)
    if m:
        close = _match(s, m.end() - 1)
        rest = s[close + 1:].strip()
        if rest == "then":
            t.add("ctl.if-block")
            return t
        if rest:
            t.add("ctl.if-single")
            return t | classify_fortran(rest, arrays, ptr, alloc, routines)
        return t
    if re.match(r"^select\s*case\b", s):
        t.add("ctl.select")
        return t
    m = re.match(r"^(exit|cycle)\b\s*(\w*)", s)
    if m:
        t.add(f"ctl.{m.group(1)}" + ("-named" if m.group(2) else ""))
        return t
    if re.match(r"^go\s*to\b", s):
        t.add("ctl.goto")
        return t
    if re.match(r"^return\b", s):
        t.add("ctl.return")
        return t
    if re.match(r"^(stop|error\s+stop)\b", s):
        t.add("ctl.stop")
        return t
    m = re.match(r"^call\s+(\w+)", s)
    if m:
        t.add("call.user")
        if m.group(1) in routines:
            t.add("call.device-routine")
        for a in _ctor_spans(s):
            t.add("ac.arg")
        _rhs_tags(s, t)
        return t
    if re.match(r"^(allocate|deallocate)\s*\(", s):
        t.add("mem.allocate")
        return t
    if re.match(r"^(print|write\s*\(|read\s*\()", s):
        t.add("io.print")
        return t
    if re.match(r"^where\b", s):
        t.add("ctl.where")
        return t
    if re.match(r"^forall\b", s):
        t.add("ctl.forall")
        return t
    if re.match(r"^associate\b", s):
        t.add("ctl.associate")
        return t
    if "::" in s:
        return t                                       # a declaration
    if re.match(r"^(integer|real|logical|complex|character|type|double)\b", s):
        return t
    k = _top_equals(s)
    if k < 0:
        if "=>" in s:
            t.add("ptr.assign")
        return t
    lhs, rhs = s[:k].strip(), s[k + 1:].strip()
    parts = _parts(lhs)
    if parts is None:
        return t
    kind = _target_kind(parts, arrays, ptr, alloc)
    t.add(f"tgt.{kind}")
    spans = _ctor_spans(rhs)
    if spans:
        st, en = spans[0]
        if len(spans) >= 1 and st == 0 and en == len(rhs) - 1 or \
                (rhs.startswith("(/") and rhs.endswith("/)")):
            t.add("ac." + ("var" if kind == "whole-array" else kind))
            if re.search(r"\(\s*\w+\s*,\s*\w+\s*=", rhs):
                t.add("ac.implied-do")
        else:
            inside_call = rhs[:st].rstrip().endswith(("(", ","))
            t.add("ac.arg" if inside_call else "ac.expr")
    _rhs_tags(rhs, t)
    return t


# --- Fortran: regions ----------------------------------------------------------------------

_OMP_NAMES = {"target", "teams", "distribute", "parallel", "do", "simd",
              "loop", "workshare", "masked", "for"}
_ACC_NAMES = {"parallel", "kernels", "serial", "loop"}
_ATOMIC_FORMS = ("read", "write", "update", "capture", "compare")


def _directive_start(kind: str, t: str):
    """(region kind, directive text) when this line opens a device region."""
    tl = t.lower()
    if kind == "fypp":
        if tl.startswith("$:gpu_parallel_loop"):
            return "loop"
        return None
    if kind == "pp":
        if re.match(r"^#:call\s+gpu_parallel\b", tl):
            return "block"
        return None
    if kind != "dir":
        return None
    m = re.match(r"!\$omp\s+(.*)$", tl)
    if m:
        rest = m.group(1)
        if not rest.startswith("target"):
            return None
        if re.match(r"target\s+(data|enter|exit|update|declare)\b", rest):
            return None
        names = []
        for tok in re.findall(r"[a-z_]+|\(", rest):
            if tok in _OMP_NAMES:
                names.append(tok)
            else:
                break
        return "loop" if set(names) & {"do", "loop", "distribute", "simd"} \
            else "block"
    m = re.match(r"!\$acc\s+(.*)$", tl)
    if m:
        names = []
        for tok in re.findall(r"[a-z_]+|\(", m.group(1)):
            if tok in _ACC_NAMES:
                names.append(tok)
            else:
                break
        if not names or names[0] not in ("parallel", "kernels", "serial"):
            return None
        return "loop" if "loop" in names else "block"
    return None


def _clause_list(text: str, clause: str) -> list[str]:
    out = []
    for m in re.finditer(clause + r"\s*[=(]\s*'?\[?([^)\]']*)", text, re.I):
        out += [x.strip().lower() for x in m.group(1).split(",")
                if x.strip()]
    return out


def _collapse_of(text: str) -> int:
    m = re.search(r"collapse\s*[=(]\s*(\d+)", text, re.I)
    return int(m.group(1)) if m else 1


def _is_atomic(kind, t):
    tl = t.lower()
    if kind == "dir":
        m = re.match(r"!\$(?:omp|acc)\s+atomic\b(.*)$", tl)
        if m:
            f = [w for w in re.findall(r"[a-z_]+", m.group(1))
                 if w in _ATOMIC_FORMS]
            return f[0] if f else "update"
    if kind == "fypp" and tl.startswith("$:gpu_atomic"):
        m = re.search(r"atomic\s*=\s*'(\w+)'", tl)
        return m.group(1) if m else "update"
    return None


def _is_atomic_end(kind, t):
    tl = t.lower()
    return (kind == "dir" and re.match(r"!\$(omp|acc)\s+end\s+atomic", tl)) \
        or (kind == "fypp" and tl.startswith("$:end_gpu_atomic_capture"))


def _atomic_op(rhs: str) -> str:
    m = re.match(r"^(max|min|iand|ior|ieor)\s*\(", rhs)
    if m:
        return "minmax" if m.group(1) in ("max", "min") else "bit"
    depth = 0
    for ch in rhs:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and ch in "+-*/":
            return {"+": "add", "-": "sub", "*": "mul", "/": "div"}[ch]
    if re.search(r"\.(and|or|eqv|neqv)\.", rhs):
        return "logical"
    return "other"


def _assign(s: str):
    s = s.strip().lower()
    k = _top_equals(s)
    if k < 0:
        return None
    return s[:k].strip(), s[k + 1:].strip()


def _refs(rhs: str, lhs: str) -> bool:
    return re.search(r"(?<![\w%])" + re.escape(lhs) + r"(?![\w%(])", rhs) \
        is not None if "(" not in lhs and "%" not in lhs else lhs in rhs


def _atomic_tags(form: str, body: list[str], arrays, ptr, alloc) -> set:
    t = {"atomic.any", f"atomic.form.{form}"}
    asg = [_assign(b) for b in body]
    asg = [a for a in asg if a]
    if not asg:
        return t

    def tk(lv):
        parts = _parts(lv)
        return _target_kind(parts, arrays, ptr, alloc) if parts else "var"
    if form in ("update", "compare"):
        lv, rv = asg[0]
        t.add(f"atomic.{form}.{tk(lv)}")
        t.add(f"atomic.op.{_atomic_op(rv)}")
    elif form == "write":
        t.add(f"atomic.write.{tk(asg[0][0])}")
    elif form == "read":
        t.add(f"atomic.read.{tk(asg[0][1])}")
    elif form == "capture" and len(asg) >= 2:
        (l1, r1), (l2, r2) = asg[0], asg[1]
        if _refs(r2, l2) and r1.replace(" ", "") == l2.replace(" ", ""):
            shape, x = "fetch-update", l2
            op = _atomic_op(r2)
        elif _refs(r1, l1) and r2.replace(" ", "") == l1.replace(" ", ""):
            shape, x = "update-fetch", l1
            op = _atomic_op(r1)
        elif r1.replace(" ", "") == l2.replace(" ", ""):
            shape, x, op = "read-write", l2, "write"
        else:
            shape, x, op = "other", l1, "other"
        t.add(f"atomic.capture.{shape}.{tk(x)}")
        t.add(f"atomic.op.{op}")
    elif form == "capture":
        t.add("atomic.capture.stmt")
    return t


def fortran_regions(text: str, file: str = "?", routines=None,
                    comps=None) -> list[Region]:
    """`comps`: (pointer components, allocatable components) of the whole
    project (a type is usually declared in another file); default: this
    text's own."""
    lines = _fortran_lines(text)
    procs = _procs(lines)
    ptr, alloc = comps if comps is not None else \
        declared_pointer_components(text)
    routines = set(routines) if routines is not None else \
        device_routines(text)
    out: list[Region] = []
    n = len(lines)
    taken = [False] * n

    def enclosing(k):
        inner = [p for p in procs if p[1] < k < p[2]]
        return min(inner, key=lambda p: p[2] - p[1]) if inner else None

    def arrays_before(k):
        p = enclosing(k)
        lo = p[1] if p else 0
        return declared_arrays(lines[lo:k]), (p[3] if p else set())

    def walk(rg: Region, idxs, directive_text, arrays, dummies):
        pr = set(_clause_list(directive_text, "private")) | \
            set(_clause_list(directive_text, "firstprivate"))
        if pr & arrays:
            rg.flags.add("priv.array")
        if pr and not (pr & arrays):
            rg.flags.add("priv.scalar-only")
        if re.search(r"reduction", directive_text, re.I):
            rg.flags.add("red.clause")
        rg.flags.add(f"loop.collapse{min(rg.collapse, 3)}")
        loops, own = [], rg.collapse if rg.kind == "loop" else 0
        j = 0
        idxs = list(idxs)
        while j < len(idxs):
            k = idxs[j]
            ln, kind, t = lines[k]
            j += 1
            form = _is_atomic(kind, t)
            if form:
                body = []
                if form == "capture":
                    while j < len(idxs) and not _is_atomic_end(
                            lines[idxs[j]][1], lines[idxs[j]][2]):
                        if lines[idxs[j]][1] == "stmt":
                            body.append(lines[idxs[j]][2])
                        j += 1
                    j += 1
                else:
                    while j < len(idxs) and lines[idxs[j]][1] != "stmt":
                        j += 1
                    if j < len(idxs):
                        body.append(lines[idxs[j]][2])
                        j += 1
                rg.stmts.append((ln, _atomic_tags(form, body, arrays, ptr,
                                                   alloc)))
                continue
            if kind != "stmt":
                continue
            tags = classify_fortran(t, arrays, ptr, alloc, routines)
            if "ctl.do" in tags or "ctl.do-while" in tags or \
                    "ctl.do-concurrent" in tags:
                loops.append(t)
                if len(loops) > own:
                    tags.add("loop.inner")
            elif _ENDDO.match(t):
                if loops:
                    loops.pop()
            inner = len(loops) - own
            if ("ctl.exit" in tags or "ctl.exit-named" in tags or
                    "ctl.cycle" in tags or "ctl.cycle-named" in tags) and \
                    inner >= 1:
                tags.add("loop.search")
                if inner >= 2 or "ctl.exit-named" in tags:
                    tags.add("loop.search-nested")
            rg.stmts.append((ln, tags))

    k = 0
    while k < n:
        ln, kind, t = lines[k]
        rk = _directive_start(kind, t) if not taken[k] else None
        if rk is None:
            k += 1
            continue
        # the directive may continue on the next lines (Fypp macro calls are
        # already joined); the body is what follows
        arrays, dummies = arrays_before(k)
        rg = Region(rk, file, ln, "f", _collapse_of(t))
        j = k + 1
        if rk == "loop":
            while j < n and lines[j][1] != "stmt":
                j += 1
            if j >= n or not _DO.match(lines[j][2]):
                k += 1
                continue
            depth, e = 0, j
            while e < n:
                if lines[e][1] == "stmt":
                    if _DO.match(lines[e][2]):
                        depth += 1
                    elif _ENDDO.match(lines[e][2]):
                        depth -= 1
                        if depth == 0:
                            break
                e += 1
            idxs = range(j, min(e + 1, n))
        else:
            tl = t.lower()
            if kind == "pp":
                end_re = re.compile(r"^#:endcall\s+gpu_parallel", re.I)
            elif tl.startswith("!$omp"):
                end_re = re.compile(r"^!\$omp\s+end\s+target", re.I)
            else:
                end_re = re.compile(r"^!\$acc\s+end\s+(parallel|kernels|"
                                    r"serial)", re.I)
            e = j
            while e < n and not (lines[e][1] in ("dir", "pp") and
                                 end_re.match(lines[e][2])):
                e += 1
            idxs = range(j, e)
        for q in idxs:
            taken[q] = True
        walk(rg, idxs, t, arrays, dummies)
        out.append(rg)
        k += 1
    # device routines: the whole procedure body
    for name, st, en, dums in procs:
        if name in routines:
            arrays = declared_arrays(lines[st:en])
            rg = Region("routine", file, lines[st][0], "f", 1, name)
            idxs = [q for q in range(st + 1, en)]
            walk(rg, idxs, "", arrays, dums)
            local = {a for a in arrays if a not in dums}
            decl_lines = [lines[q][2].lower() for q in idxs
                          if lines[q][1] == "stmt" and "::" in lines[q][2]]
            fixed = False
            for d in decl_lines:
                attrs, ents = d.split("::", 1)
                if re.search(r"allocatable|pointer|parameter|intent", attrs):
                    continue
                for e in _split_top(ents, ","):
                    m = re.match(r"\s*(\w+)", e)
                    if m and m.group(1) in local:
                        fixed = True
            if fixed:
                rg.flags.add("local.fixed-array")
            out.append(rg)
    return out


# --- C and C++ ---------------------------------------------------------------------------------

_C_TYPES = r"(?:const\s+|unsigned\s+|signed\s+|struct\s+|volatile\s+)*" \
           r"(?:int|float|double|char|long|short|size_t|bool|_Bool|" \
           r"u?int\d+_t|\w+_t|real_t|real|T|auto|ptrdiff_t|[A-Z]\w*)"
_C_DECL = re.compile(r"^(?:" + _C_TYPES + r")(?:\s+long)*\s*\**\s*(\w+)\s*(\[|=|$)")
_C_LIBM = {"fabs", "fmax", "fmin", "sqrt", "exp", "log", "pow", "sin", "cos",
           "tan", "floor", "ceil", "fma", "abs", "min", "max", "sizeof",
           "sqrtf", "expf", "powf", "fabsf", "fmaxf", "fminf", "atan2",
           "tanh", "cbrt", "hypot", "log10", "atan", "round", "fmod"}


def _c_clean(src: str) -> str:
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("\n" * src.count("\n", i, j))
            i = j
        elif c == '"':
            j = i + 1
            while j < n and src[j] != '"':
                j += 2 if src[j] == "\\" else 1
            out.append('""')
            i = j + 1
        elif c == "'":
            j = i + 1
            while j < n and src[j] != "'":
                j += 2 if src[j] == "\\" else 1
            out.append("'0'")
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _c_pragmas(src: str):
    """(text with every pragma replaced by a marker, pragma list)."""
    pragmas, out = [], []
    lines = src.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^\s*#\s*pragma\s+(.*)$", line)
        if m:
            body, extra = m.group(1), 0
            while body.rstrip().endswith("\\") and i + 1 < len(lines):
                i += 1
                extra += 1
                body = body.rstrip()[:-1] + " " + lines[i].strip()
            pragmas.append(re.sub(r"\s+", " ", body).strip())
            out.append(f"\x01{len(pragmas) - 1}\x02" + "\n" * (extra))
        elif re.match(r"^\s*#", line):
            out.append("")
        else:
            out.append(line)
        i += 1
    return "\n".join(out), pragmas


_C_TOK = re.compile(r"\x01(\d+)\x02")


def _c_tokens(body: str):
    """Statement tokens of a C block: ('pragma', n), ('head', text) for a
    for/while/if/else/do/switch header, ('open', header), ('close', ''),
    ('stmt', text)."""
    out, buf, i, n, depth = [], [], 0, len(body), 0

    def flush(kind="stmt"):
        text = "".join(buf).strip()
        buf.clear()
        if text:
            out.append((kind, text))
    while i < n:
        c = body[i]
        m = _C_TOK.match(body, i)
        if m:
            flush()
            out.append(("pragma", int(m.group(1))))
            i = m.end()
            continue
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        if depth == 0 and c == "{":
            hdr = "".join(buf).strip()
            buf.clear()
            if re.search(r"(=|\(\s*\w+(\s+\w+)*\s*\*?\s*(\[\s*\])?\s*\))\s*$",
                         hdr):                     # a brace initializer
                j = _match(body, i)
                buf.append(hdr + " {" + body[i + 1:j] + "}")
                i = j + 1
                continue
            out.append(("open", hdr))
            i += 1
            continue
        if depth == 0 and c == "}":
            flush()
            out.append(("close", ""))
            i += 1
            continue
        if depth == 0 and c == ";":
            flush()
            i += 1
            continue
        buf.append(c)
        i += 1
        if depth == 0:
            t = "".join(buf).strip()
            if re.match(r"^(for|while|if|switch)\s*\(", t) and \
                    t.endswith(")"):
                # a header without a block: it ends at the next token
                k = i
                while k < n and body[k] in " \t\n":
                    k += 1
                if k < n and body[k] != "{":
                    out.append(("head", t))
                    buf.clear()
            elif t in ("else", "do"):
                k = i
                while k < n and body[k] in " \t\n":
                    k += 1
                if k < n and body[k] != "{":
                    out.append(("head", t))
                    buf.clear()
    flush()
    return out


def _c_lvalue_parts(lv: str):
    """[(name, sub, arrow)] of `a[i].b->c[2]`; None when not an lvalue."""
    lv = lv.strip()
    deref = lv.startswith("*")
    lv = lv.lstrip("*( ").rstrip(") ") if deref else lv
    toks = re.findall(r"->|\.|\w+|\[[^\]]*\]", lv)
    parts, cur = [], None
    arrow = False
    for tk in toks:
        if tk in (".", "->"):
            arrow = arrow or tk == "->"
            continue
        if tk.startswith("["):
            if cur is None:
                return None
            cur[1] = True
            continue
        cur = [tk, False]
        parts.append(cur)
    return ([(a, b) for a, b in parts], arrow, deref) if parts else None


def _c_kind(parts, arrow, deref) -> str:
    if deref:
        return "deref"
    n = len(parts)
    if n == 1:
        return "elem" if parts[0][1] else "var"
    if n >= 3:
        return "nested-comp"
    a, b = parts[0][1], parts[1][1]
    return {(False, False): "comp", (True, False): "elem-comp",
            (False, True): "comp-elem", (True, True): "elem-comp-elem"}[(a, b)]


_C_ASSIGN = re.compile(r"(?<![=!<>+\-*/%&|^])(<<=|>>=|[+\-*/%&|^]?=)(?!=)")


def _c_split_assign(s: str):
    depth = 0
    for i, ch in enumerate(s):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif depth == 0 and ch == "=":
            j = i
            while j > 0 and s[j - 1] in "+-*/%&|^<>":
                j -= 1
            prev = s[j - 1] if j else ""
            nxt = s[i + 1] if i + 1 < len(s) else ""
            if nxt == "=" or (j == i and prev in "=!<>"):
                continue
            return s[:j].strip(), s[j:i + 1], s[i + 1:].strip()
    return None


def classify_c(stmt: str, routines=()) -> set:
    s = re.sub(r"\s+", " ", stmt.strip())
    t: set = set()
    if not s:
        return t
    if re.match(r"^(break)\b", s):
        t.add("ctl.break")
        return t
    if re.match(r"^continue\b", s):
        t.add("ctl.continue")
        return t
    if re.match(r"^return\b", s):
        t.add("ctl.return")
        return t
    if re.match(r"^goto\b", s):
        t.add("ctl.goto")
        return t
    if re.match(r"^(for|while|do)\b", s):
        t.add("ctl.loop")
        return t
    if re.match(r"^if\b", s):
        t.add("ctl.if-block")
        return t
    if re.match(r"^else\b", s):
        return t
    if re.match(r"^switch\b", s):
        t.add("ctl.select")
        return t
    for fn in re.findall(r"\b([A-Za-z_]\w*)\s*\(", s):
        if fn in INTRINSIC_GROUPS:
            t.add(f"intr.{INTRINSIC_GROUPS[fn]}")
        if fn in ("memcpy", "memset", "memmove"):
            t.add("c.memcpy")
        elif fn in ("printf", "fprintf", "puts"):
            t.add("io.print")
        elif fn in ("malloc", "free", "calloc", "new", "delete"):
            t.add("mem.allocate")
        elif fn in routines:
            t.add("call.device-routine")
            t.add("call.user")
        elif fn not in _C_LIBM and fn not in ("if", "while", "for",
                                              "switch", "sizeof", "int",
                                              "double", "float", "long",
                                              "char", "bool", "size_t"):
            t.add("call.user")
    if re.search(r"\)\s*\{", s) and re.search(
            r"\(\s*(?:struct\s+)?\w+\s*(\[\s*\])?\s*\)\s*\{", s):
        t.add("c.compound-literal")
    if "?" in s:
        t.add("expr.ternary")
    if re.search(r"\w\s%\s?\w|\w%\w", s):
        t.add("intr.mod")
    m = _C_DECL.match(s)
    if m and "(" not in s.split("=")[0]:
        if m.group(2) == "[":
            t.add("local.fixed-array")
            if re.search(r"=\s*\{", s):
                t.add("c.brace-init")
        elif m.group(2) == "=" and re.search(r"=\s*\{", s):
            t.add("c.brace-init")
        asg = _c_split_assign(s)
        if asg and not t & {"local.fixed-array"}:
            t.add("tgt.var")
        return t
    asg = _c_split_assign(s)
    inc = re.match(r"^(\+\+|--)\s*(.+)$|^(.+?)\s*(\+\+|--)$", s)
    lv = None
    if asg:
        lv = asg[0]
    elif inc:
        lv = inc.group(2) or inc.group(3)
        t.add("op.incdec")
    if lv:
        pr = _c_lvalue_parts(lv)
        if pr:
            parts, arrow, deref = pr
            t.add(f"tgt.{_c_kind(parts, arrow, deref)}")
            if arrow:
                t.add("tgt.arrow")
    return t


def _c_atomic_tags(form: str, body: list[str], block: bool) -> set:
    t = {"atomic.any", f"atomic.form.{form}"}

    def kd(lv):
        pr = _c_lvalue_parts(lv)
        return _c_kind(*pr) if pr else "var"
    if form in ("update", "compare"):
        if body:
            a = _c_split_assign(body[0])
            inc = re.match(r"^(\+\+|--)\s*(.+)$|^(.+?)\s*(\+\+|--)$",
                           body[0].strip())
            lv = a[0] if a else (inc.group(2) or inc.group(3)) if inc else ""
            t.add(f"atomic.{form}.{kd(lv)}")
            op = a[1] if a else "++"
            t.add("atomic.op." + {"+=": "add", "-=": "sub", "*=": "mul",
                                  "/=": "div", "++": "add", "--": "sub",
                                  "=": "other"}.get(op, "bit"))
    elif form == "write" and body:
        a = _c_split_assign(body[0])
        t.add(f"atomic.write.{kd(a[0]) if a else 'var'}")
    elif form == "read" and body:
        a = _c_split_assign(body[0])
        t.add(f"atomic.read.{kd(a[2]) if a else 'var'}")
    elif form == "capture":
        if block and len(body) >= 2:
            a1, a2 = _c_split_assign(body[0]), _c_split_assign(body[1])
            inc2 = re.match(r"^(.+?)\s*(\+\+|--)$|^(\+\+|--)\s*(.+)$",
                            body[1].strip())
            if a1 and a1[1] == "=" and (a2 or inc2):
                x = a2[0] if a2 else inc2.group(1) or inc2.group(4)
                same = a1[2].replace(" ", "") == x.replace(" ", "")
                t.add(f"atomic.capture.{'fetch-update' if same else 'other'}"
                      f".{kd(x)}")
            elif a1 and a2 and a2[1] == "=":
                t.add(f"atomic.capture.update-fetch.{kd(a1[0])}")
            else:
                t.add("atomic.capture.other.var")
        elif body:
            a = _c_split_assign(body[0])
            x = re.sub(r"(\+\+|--)|^\s*(\+\+|--)", "", a[2]) if a else ""
            t.add(f"atomic.capture.stmt.{kd(x.strip()) if x else 'var'}")
    return t


def _c_walk(rg: Region, body: str, pragmas, routines, own: int):
    toks = _c_tokens(body)
    rg.flags.add(f"loop.collapse{min(rg.collapse, 3)}")
    stack, loops, pending = [], 0, 0
    i, n = 0, len(toks)
    line_of = {}
    while i < n:
        kind, val = toks[i]
        i += 1
        if kind == "pragma":
            p = pragmas[val].lower()
            m = re.match(r"(?:omp|acc)\s+atomic\b(.*)$", p)
            if m:
                f = [w for w in re.findall(r"[a-z_]+", m.group(1))
                     if w in _ATOMIC_FORMS]
                form = f[0] if f else "update"
                block, stm = False, []
                if i < n and toks[i][0] == "open" and not toks[i][1]:
                    block = True
                    i += 1
                    while i < n and toks[i][0] != "close":
                        if toks[i][0] == "stmt":
                            stm.append(toks[i][1])
                        i += 1
                    i += 1
                elif i < n and toks[i][0] == "stmt":
                    stm.append(toks[i][1])
                    i += 1
                rg.stmts.append((0, _c_atomic_tags(form, stm, block)))
            continue
        if kind in ("head", "open"):
            head = val
            is_loop = bool(re.match(r"^(for|while|do)\b", head))
            tags = classify_c(head, routines) if head else set()
            if is_loop:
                loops += 1
                if loops > own:
                    tags.add("loop.inner")
            if kind == "open":
                stack.append(is_loop)
            elif is_loop:
                pending += 1
            if tags:
                rg.stmts.append((0, tags))
            continue
        if kind == "close":
            if stack and stack.pop():
                loops -= 1
            continue
        tags = classify_c(val, routines)
        inner = loops - own
        if tags & {"ctl.break", "ctl.continue"} and inner >= 1:
            tags.add("loop.search")
            if inner >= 2:
                tags.add("loop.search-nested")
        if pending:
            loops -= pending
            pending = 0
        rg.stmts.append((0, tags))


def _c_body_after(text: str, pos: int):
    """The statement that follows position pos: (start, end) of the text
    of a block, a for/while statement, or a single statement."""
    n = len(text)
    i = pos
    while i < n and (text[i].isspace() or _C_TOK.match(text, i)):
        m = _C_TOK.match(text, i)
        i = m.end() if m else i + 1
    if i >= n:
        return None
    if text[i] == "{":
        return i, _match(text, i) + 1
    m = re.match(r"(for|while|if)\s*\(", text[i:])
    if m:
        j = _match(text, i + m.end() - 1) + 1
        sub = _c_body_after(text, j)
        return (i, sub[1]) if sub else (i, j)
    j = text.find(";", i)
    return (i, j + 1) if j >= 0 else None


def c_regions(text: str, file: str = "?", routines=()) -> list[Region]:
    src, pragmas = _c_pragmas(_c_clean(text))
    out = []
    routines = set(routines)
    k = 0
    for m in _C_TOK.finditer(src):
        idx = int(m.group(1))
        p = pragmas[idx].lower()
        kind = None
        if re.match(r"omp\s+target\b(?!\s+(data|enter|exit|update|declare))",
                    p) or re.match(r"acc\s+(parallel|kernels|serial)\b", p):
            kind = "loop" if re.search(r"\b(for|loop|distribute|simd)\b", p) \
                else "block"
        if kind is None:
            continue
        # the construct's directive lines run on until the body starts
        dirtext, pos = p, m.end()
        while True:
            m2 = _C_TOK.match(src, pos)
            while m2 is None and pos < len(src) and src[pos].isspace():
                pos += 1
                m2 = _C_TOK.match(src, pos)
            if m2 and re.match(r"(omp|acc)\s+(teams|distribute|parallel|"
                               r"for|loop|simd|do)\b",
                               pragmas[int(m2.group(1))].lower()):
                dirtext += " " + pragmas[int(m2.group(1))].lower()
                pos = m2.end()
                continue
            break
        if re.search(r"\b(for|loop|distribute|simd)\b", dirtext):
            kind = "loop"
        span = _c_body_after(src, pos)
        if not span:
            continue
        line = src.count("\n", 0, m.start()) + 1
        rg = Region(kind, file, line, "c", _collapse_of(dirtext))
        body = src[span[0]:span[1]]
        if kind == "loop" and body.lstrip().startswith("for"):
            _c_walk(rg, body, pragmas, routines, rg.collapse)
        else:
            _c_walk(rg, body, pragmas, routines, 0)
        pr = set(_clause_list(dirtext, "private")) | \
            set(_clause_list(dirtext, "firstprivate"))
        if re.search(r"reduction", dirtext):
            rg.flags.add("red.clause")
        if pr:
            rg.flags.add("priv.clause")
        out.append(rg)
        k += 1
    # device routines: functions between declare target and end declare target
    for m in re.finditer(r"\x01(\d+)\x02", src):
        p = pragmas[int(m.group(1))].lower()
        if re.match(r"omp\s+declare\s+target\s*$", p):
            end = None
            for m2 in re.finditer(r"\x01(\d+)\x02", src[m.end():]):
                if re.match(r"omp\s+end\s+declare\s+target",
                            pragmas[int(m2.group(1))].lower()):
                    end = m.end() + m2.start()
                    break
            span = src[m.end():end] if end else ""
            out += _c_routines(span, pragmas, file, src.count(
                "\n", 0, m.start()) + 1, routines)
        elif re.match(r"acc\s+routine\b", p):
            out += _c_routines(src[m.end():m.end() + 20000].split("\n\n")[0],
                               pragmas, file, src.count("\n", 0, m.start()) + 1,
                               routines, one=True)
    return out


def _c_routines(span: str, pragmas, file, line, routines, one=False):
    out, i, n, depth = [], 0, len(span), 0
    head_start = 0
    while i < n:
        c = span[i]
        if c == "{" and depth == 0:
            hdr = span[head_start:i].strip()
            j = _match(span, i)
            if "(" in hdr and not re.match(r"^(struct|enum|union|typedef)",
                                           hdr):
                mm = re.search(r"(\w+)\s*\([^)]*\)\s*(const)?\s*$", hdr)
                rg = Region("routine", file, line, "c", 1,
                            mm.group(1) if mm else "")
                _c_walk(rg, span[i:j + 1], pragmas, routines, 0)
                out.append(rg)
            i = j + 1
            head_start = i
            if one:
                break
            continue
        if c == ";" and depth == 0:
            head_start = i + 1
        i += 1
    return out


def c_device_routines(text: str) -> set:
    src, pragmas = _c_pragmas(_c_clean(text))
    out = set()
    for m in re.finditer(r"\x01(\d+)\x02", src):
        p = pragmas[int(m.group(1))].lower()
        if re.match(r"omp\s+declare\s+target\s*$", p):
            end = None
            for m2 in re.finditer(r"\x01(\d+)\x02", src[m.end():]):
                if re.match(r"omp\s+end\s+declare\s+target",
                            pragmas[int(m2.group(1))].lower()):
                    end = m.end() + m2.start()
                    break
            for r in _c_routines(src[m.end():end] if end else "", pragmas,
                                 "?", 0, set()):
                out.add(r.name)
    return out


# --- the counts -----------------------------------------------------------------------------

# the idiom classes: a class counts a
# statement (and its file and kernel) once however many of its tags match
GROUPS = {
    "G01 array constructor into the component of an element of a derived-type array (the student's)":
        ("ac.elem-comp",),
    "G02 array constructor into any derived-type component (component, section of a component, nested)":
        ("ac.comp", "ac.elem-comp", "ac.comp-section", "ac.elem-comp-section",
         "ac.nested-comp"),
    "G03 array constructor into a plain array or a section of one":
        ("ac.var", "ac.section", "ac.elem"),
    "G04 array constructor inside an expression or an argument":
        ("ac.expr", "ac.arg", "ac.reshape"),
    "G05 write through a pointer component of an element (q(i)%sf(j,k,l) = x)":
        ("tgt.ptr-comp-elem", "tgt.ptr-comp"),
    "G06 element write of a component array of an element (a(i)%b(k) = x, a%b(k) = x, a(i)%b = x)":
        ("tgt.elem-comp-elem", "tgt.comp-elem", "tgt.elem-comp",
         "tgt.nested-comp", "tgt.alloc-comp-elem", "tgt.alloc-comp"),
    "G07 atomic update (any target)": ("atomic.form.update",),
    "G08 atomic capture (either order, any target)":
        ("atomic.form.capture",),
    "G09 atomic read, write or compare": (
        "atomic.form.read", "atomic.form.write", "atomic.form.compare"),
    "G10 exit or cycle out of an inner (search) loop":
        ("loop.search", "ctl.exit", "ctl.cycle", "ctl.exit-named",
         "ctl.break", "ctl.continue"),
    "G11 named exit out of nested loops": ("loop.search-nested",
                                           "ctl.exit-named"),
    "G12 private or local fixed-size array (automatic temporary)":
        ("priv.array", "local.fixed-array"),
    "G13 call of a declare target procedure": ("call.device-routine",),
    "G14 elemental math intrinsic (sqrt, exp, ...)": ("intr.math",),
    "G15 min/max/abs/sign/merge/mod": ("intr.minmax", "intr.abs-sign",
                                       "intr.merge", "intr.mod"),
    "G16 sum/product/maxval/minval/any/all inside a kernel":
        ("intr.reduce", "intr.matmul"),
    "G17 whole-array or section assignment": ("tgt.whole-array",
                                              "tgt.section"),
    "G18 select case / else if chains": ("ctl.select", "ctl.else-if"),
    "G19 reduction clause on the kernel": ("red.clause",),
    "G20 collapse(3) loop nest": ("loop.collapse3",),
    "G21 scalar element write (a(i,j,k) = x)": ("tgt.elem",),
    "G22 integer or logical scalar write": ("tgt.var",),
    "G23 do while": ("ctl.do-while",),
    "G24 input/output or allocation in a kernel": ("io.print",
                                                   "mem.allocate"),
}


def tally(regions) -> dict:
    """tag -> {stmts, files, kernels}: the statements carrying the tag, the
    files and the distinct regions (kernels or device routines) that have
    it. A region-level flag counts in `kernels` and `files` only. The
    entries named in GROUPS count each statement once per class."""
    stm: dict = defaultdict(int)
    files: dict = defaultdict(set)
    kern: dict = defaultdict(set)
    for r in regions:
        for _, tags in r.stmts:
            for tg in tags:
                stm[tg] += 1
                files[tg].add(r.file)
                kern[tg].add(r.rid)
            for g, members in GROUPS.items():
                if tags & set(members):
                    stm[g] += 1
                    files[g].add(r.file)
                    kern[g].add(r.rid)
        for tg in r.flags:
            files[tg].add(r.file)
            kern[tg].add(r.rid)
            for g, members in GROUPS.items():
                if tg in members:
                    files[g].add(r.file)
                    kern[g].add(r.rid)
    return {tg: {"stmts": stm.get(tg, 0), "files": len(files[tg]),
                 "kernels": len(kern[tg])} for tg in files}
