"""A harvested test (one variant of its RUN lines) as a self-checking
catalog program (`convert`).

The program is the original text with a provenance header and a self-check
appended (offload.engine.harvest.c_runtime, f_runtime). In C, -D flags become
#define lines and `main` is renamed hv_orig_main. In Fortran, -D flags and
#define / #ifdef lines are applied by `preprocess` (object-like macros and
defined() only) and the main program becomes `subroutine hv_orig_main`.

Expected result: exit status 0 and, when the variant pipes to FileCheck,
output matching its CHECK lines (offload.engine.harvest.checks). `oracle` is
`filecheck` or `exit_status`. `spec_version` is the lowest of 5.0, 5.2, 6.0
at which parse_directive reads every directive, raised to the RUN line's
-fopenmp-version. `holdout` marks programs whose sha256 is in the lowest
30% of the hash space."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from offload.engine.harvest import c_runtime as CR
from offload.engine.harvest import checks as K
from offload.engine.harvest import f_runtime as FR

VERSIONS = (50, 52, 60)
HOLDOUT_FRACTION = 0.30


class ConvertError(ValueError):
    """The test cannot be converted (the reason is recorded)."""


@dataclass
class Converted:
    id: str
    record: str
    variant: int
    lang: str
    model: str
    version: int
    source: str
    oracle: str
    checks: int
    prefixes: list
    stderr: bool
    modes: tuple
    edits: list = field(default_factory=list)
    grammar_errors: list = field(default_factory=list)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.source.encode()).hexdigest()

    @property
    def holdout(self) -> bool:
        # By code, so that programs that differ only
        # in comments fall on one side (the sealed harvest of 2026-10-26 was
        # split by text; tools/campaigns/harvest.py convert refuses to redo it)
        return holdout_by_code(self.source, self.lang)

    def harness(self):
        """The offload.engine.gen.Program the harness runs."""
        from offload.engine.gen import Program as HP
        return HP(id=self.id, lang=self.lang, source=self.source,
                  atoms=frozenset({f"harvest.{self.record}"}),
                  primary_atom=f"harvest.{self.record}", legal=True,
                  violates=None, observable=True,
                  needs=("zero_copy",) if self.modes == ("unified",) else (),
                  evidence="copy_mode_only" if self.modes == ("copy",)
                  else "construct", model=self.model)


def holdout(text: str) -> bool:
    h = int(hashlib.sha256(text.encode()).hexdigest(), 16)
    return h < int(HOLDOUT_FRACTION * (1 << 256))


def program_id(record_id: str, variant: int, nvariants: int) -> str:
    """hv-<source>-<path>: the record id with separators as '-', the
    extension dropped; -v<k> for the k-th kept variant when there are more."""
    src, rest = record_id.split("/", 1)
    rest = re.sub(r"\.(c|f90|F90|f95)$", "", rest)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", rest).strip("-").lower()
    pid = f"hv-{src}-{slug}"
    return pid + (f"-v{variant + 1}" if nvariants > 1 else "")


# --- the spec version -------------------------------------------------------------------

def directives(text: str, lang: str, model: str = "omp") -> list[str]:
    """The directives of a program, each as its physical lines (sentinel
    included)."""
    out = []
    lines = text.splitlines()
    k = 0
    pre = (rf"^\s*#\s*pragma\s+{model}\b" if lang == "c"
           else rf"^\s*!\${model}\b(?!&)")
    while k < len(lines):
        if re.match(pre, lines[k], re.I):
            body = [lines[k]]
            if lang == "c":
                while body[-1].rstrip().endswith("\\") and k + 1 < len(lines):
                    k += 1
                    body.append(lines[k])
            else:
                while re.sub(r"!(?!\$).*$", "", body[-1]).rstrip().endswith(
                        "&") and k + 1 < len(lines):
                    k += 1
                    body.append(lines[k])
            out.append("\n".join(body))
        k += 1
    return out


def grammar_errors(text: str, lang: str, version: int,
                   model: str = "omp") -> list[str]:
    from offload.engine.grammar import GrammarError, parse_directive
    errs = []
    for d in directives(text, lang, model):
        try:
            parse_directive(d, "c" if lang == "c" else "f90", version)
        except GrammarError as e:
            errs.append(f"{e.code}: {' '.join(d.split())[:120]}")
        except Exception as e:          # a parser limit is no version error
            errs.append(f"parser: {type(e).__name__}: "
                        f"{' '.join(d.split())[:80]}")
    return errs


_FLAG_VERSION = {45: 50, 50: 50, 51: 52, 52: 52, 60: 60, 61: 60}


def spec_version(text: str, lang: str, flags: list[str],
                 model: str = "omp") -> tuple[int, list[str]]:
    """(version, the grammar's errors at it)."""
    if model == "acc":
        return 34, grammar_errors(text, lang, 34, "acc")
    floor = 50
    for f in flags:
        m = re.fullmatch(r"-fopenmp-version=(\d+)", f)
        if m:
            floor = max(floor, _FLAG_VERSION.get(int(m.group(1)), 52))
    best = None
    for v in VERSIONS:
        if v < floor:
            continue
        errs = grammar_errors(text, lang, v, model)
        if not errs:
            return v, []
        if best is None or len(errs) < len(best[1]):
            best = (v, errs)
    return best if best else (60, [])


# --- C ----------------------------------------------------------------------------------

def _c_code_spans(text: str) -> list[tuple[int, int]]:
    """[(start, end)] of the code outside comments, strings and character
    constants."""
    spans, i, n, start = [], 0, len(text), 0
    while i < n:
        c = text[i]
        if text.startswith("//", i):
            spans.append((start, i))
            j = text.find("\n", i)
            i = n if j < 0 else j
            start = i
        elif text.startswith("/*", i):
            spans.append((start, i))
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            start = i
        elif c in "\"'":
            spans.append((start, i))
            j = i + 1
            while j < n and text[j] != c:
                j += 2 if text[j] == "\\" else 1
            i = j + 1
            start = i
        else:
            i += 1
    spans.append((start, n))
    return [(a, b) for a, b in spans if b > a]


def rename_main(text: str) -> tuple[str, int]:
    """(text, call kind) with every ``main(`` in code renamed
    ``hv_orig_main(``; call kind 0: main without parameters, 1: with argc
    and argv, 2: void main. ConvertError when there is no definition."""
    m = None
    for a, b in _c_code_spans(text):
        m = re.search(r"\b(int|void)?\s*\bmain\s*\(([^)]*)\)\s*\{", text[a:b])
        if m:
            break
    if m is None:
        raise ConvertError("no_main")
    params = m.group(2).strip()
    kind = 2 if m.group(1) == "void" else (
        1 if params and params != "void" else 0)
    out, last = [], 0
    for a, b in _c_code_spans(text):
        out.append(text[last:a])
        out.append(re.sub(r"\bmain(\s*\()", r"hv_orig_main\1", text[a:b]))
        last = b
    out.append(text[last:])
    return "".join(out), kind


def _c_str(s: str) -> str:
    out = []
    for ch in s:
        o = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif o < 32 or o == 127:
            out.append(f"\\{o:03o}")
        elif ch == "?":
            out.append("\\?")           # no trigraphs
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _pattern_data(cs: list[K.Check], lang: str) -> list[tuple]:
    """(kind code, mode, pattern text, defs text) per check."""
    out = []
    for c in cs:
        if c.kind == "EMPTY":
            out.append((CR.KIND_CODE["EMPTY"], 0, "", ""))
            continue
        p = K.compile_pattern(c.pattern, lang)
        if p.mode == "tokens":
            out.append((CR.KIND_CODE[c.kind], 0, "\002".join(p.segments), ""))
        else:
            out.append((CR.KIND_CODE[c.kind], 1, p.regex,
                        ";".join(f"{n}={g}" for n, g in p.defs)))
    return out


def c_data(cs: list[K.Check], merge: bool, args: list[str]) -> str:
    rows = _pattern_data(cs, "c")
    n = len(rows)
    rows = rows or [(0, 0, "", "")]
    lines = [f"static const int hv_n = {n};",
             "static const int hv_kind[] = {" + ", ".join(
                 str(r[0]) for r in rows) + "};",
             "static const int hv_mode[] = {" + ", ".join(
                 str(r[1]) for r in rows) + "};",
             "static const char *const hv_pat[] = {\n  " + ",\n  ".join(
                 _c_str(r[2]) for r in rows) + "};",
             "static const char *const hv_defs[] = {\n  " + ",\n  ".join(
                 _c_str(r[3]) for r in rows) + "};",
             f"static const int hv_merge = {1 if merge else 0};"]
    return "\n".join(lines)


def _c_call(kind: int, args: list[str]) -> str:
    if kind == 2:
        return "  hv_orig_main();"
    if kind == 0:
        return "  rc = hv_orig_main();"
    if not args:
        return "  rc = hv_orig_main(argc, argv);"
    av = ", ".join(["argv[0]"] + [_c_str(a) for a in args] + ["0"])
    return (f"  char *hv_av[] = {{{av}}};\n"
            f"  rc = hv_orig_main({len(args) + 1}, hv_av);")


def _defines(flags: list[str], lang: str) -> list[str]:
    out = []
    for f in flags:
        m = re.fullmatch(r"-D([A-Za-z_]\w*)(?:=(.*))?", f)
        if m:
            out.append(f"#define {m.group(1)} " + (m.group(2) if m.group(2)
                                                   is not None else "1"))
        m = re.fullmatch(r"-U([A-Za-z_]\w*)", f)
        if m:
            out.append(f"#undef {m.group(1)}")
    return out


def _main_body_end(text: str) -> int | None:
    """The offset of the closing brace of hv_orig_main's body."""
    spans = _c_code_spans(text)
    m = None
    for a, b in spans:
        m = re.search(r"\bhv_orig_main\s*\([^)]*\)\s*\{", text[a:b])
        if m:
            start = a + m.end()
            break
    if m is None:
        return None
    depth = 1
    for a, b in spans:
        if b <= start:
            continue
        for k in range(max(a, start), b):
            if text[k] == "{":
                depth += 1
            elif text[k] == "}":
                depth -= 1
                if depth == 0:
                    return k
    return None


def implicit_return(text: str) -> tuple[str, bool]:
    """C: reaching the closing brace of main returns 0 (C11 5.1.2.2.3);
    the renamed function would return an indeterminate value. A
    ``return 0;`` before the closing brace when the body does not end with
    a return statement."""
    end = _main_body_end(text)
    if end is None:
        return text, False
    code = "".join(text[a:b] for a, b in _c_code_spans(text[:end]))
    if re.search(r"\breturn\b[^;{}]*;\s*$", code) or \
            re.search(r"\bexit\s*\([^;]*\)\s*;\s*$", code):
        return text, False
    return (text[:end] + "  return 0; /* Main's implicit "
            "return */\n" + text[end:]), True


def convert_c(text: str, cs: list[K.Check], v: dict) -> tuple[str, list]:
    body, kind = rename_main(text)
    edits = ["main renamed hv_orig_main"]
    if kind in (0, 1):
        body, added = implicit_return(body)
        if added:
            edits.append("return 0 at the end of main (its implicit "
                         "return)")
    defs = _defines(v.get("flags", []), "c")
    if defs:
        edits.append("the variant's -D/-U flags as #define/#undef lines")
    runtime = CR.RUNTIME.replace("@@DATA@@", c_data(
        cs, v.get("stderr", False), v.get("args", [])))
    runtime = runtime.replace("@@CALL@@", _c_call(kind, v.get("args", [])))
    src = CR.PRELUDE + "".join(d + "\n" for d in defs) + body
    if not src.endswith("\n"):
        src += "\n"
    return src + runtime, edits


# --- Fortran ----------------------------------------------------------------------------

class _PP:
    def __init__(self, defs: dict):
        self.defs = dict(defs)

    def cond(self, expr: str) -> bool:
        e = expr.strip()
        e = re.sub(r"defined\s*\(\s*(\w+)\s*\)|defined\s+(\w+)",
                   lambda m: "1" if (m.group(1) or m.group(2)) in self.defs
                   else "0", e)
        e = re.sub(r"\b[A-Za-z_]\w*\b", lambda m: str(self.defs.get(
            m.group(0), "0")) if m.group(0) not in ("and", "or", "not")
            else m.group(0), e)
        e = e.replace("&&", " and ").replace("||", " or ")
        e = re.sub(r"!(?!=)", " not ", e)
        if not re.fullmatch(r"[\d\s()<>=!+\-*/andortn]*", e):
            raise ConvertError("preprocessor: unsupported #if expression")
        try:
            return bool(eval(e, {"__builtins__": {}}, {}))  # noqa: S307
        except Exception:
            raise ConvertError("preprocessor: unsupported #if expression")


def preprocess(text: str, flags: list[str]) -> tuple[str, bool]:
    """(text, changed) with #define/#undef/#ifdef/#ifndef/#if/#elif/#else/
    #endif applied and object-like macros substituted; ConvertError for a
    function-like macro or an #include."""
    if not re.search(r"^\s*#", text, re.M):
        return text, False
    defs = {}
    for f in flags:
        m = re.fullmatch(r"-D([A-Za-z_]\w*)(?:=(.*))?", f)
        if m:
            defs[m.group(1)] = m.group(2) if m.group(2) is not None else "1"
    pp = _PP(defs)
    out, stack = [], []          # stack of (active, taken)
    for line in text.splitlines():
        s = line.strip()
        active = all(a for a, _ in stack)
        m = re.match(r"^#\s*(\w+)\s*(.*)$", s)
        if m and s.startswith("#"):
            d, rest = m.group(1), m.group(2).strip()
            if d in ("ifdef", "ifndef"):
                name = rest.split()[0] if rest else ""
                c = (name in pp.defs) == (d == "ifdef")
                stack.append((active and c, c))
            elif d == "if":
                c = pp.cond(rest) if active else False
                stack.append((active and c, c))
            elif d == "elif":
                if not stack:
                    raise ConvertError("preprocessor: #elif without #if")
                _, taken = stack.pop()
                outer = all(a for a, _ in stack)
                c = (not taken) and outer and pp.cond(rest)
                stack.append((c, taken or c))
            elif d == "else":
                if not stack:
                    raise ConvertError("preprocessor: #else without #if")
                _, taken = stack.pop()
                outer = all(a for a, _ in stack)
                stack.append((outer and not taken, True))
            elif d == "endif":
                if stack:
                    stack.pop()
            elif d == "define" and active:
                mm = re.match(r"^([A-Za-z_]\w*)(\()?\s*(.*)$", rest)
                if not mm:
                    raise ConvertError("preprocessor: bad #define")
                if mm.group(2):
                    raise ConvertError("preprocessor: function-like macro")
                pp.defs[mm.group(1)] = mm.group(3) or "1"
            elif d == "undef" and active:
                pp.defs.pop(rest.split()[0] if rest else "", None)
            elif d == "include" and active:
                raise ConvertError("preprocessor: #include")
            elif active and d not in ("pragma", "line"):
                raise ConvertError(f"preprocessor: #{d}")
            out.append("")
            continue
        if not active:
            out.append("")
            continue
        for name, val in pp.defs.items():
            if name in line:
                line = _subst(line, name, val)
        out.append(line)
    return "\n".join(out) + "\n", True


def _subst(line: str, name: str, val: str) -> str:
    """Substitute a macro outside character literals and ! comments
    (directive lines keep their sentinel)."""
    res, i, q = [], 0, None
    while i < len(line):
        c = line[i]
        if q:
            res.append(c)
            if c == q:
                q = None
            i += 1
            continue
        if c in "'\"":
            q = c
            res.append(c)
            i += 1
            continue
        if c == "!" and not re.match(r"!\$(omp|acc)", line[i:], re.I):
            res.append(line[i:])
            break
        m = re.match(rf"\b{re.escape(name)}\b", line[i:])
        if m and (i == 0 or not (line[i - 1].isalnum() or line[i - 1] == "_")):
            res.append(val)
            i += len(name)
            continue
        res.append(c)
        i += 1
    return "".join(res)


_UNIT_START = re.compile(
    r"^\s*(?:(?:recursive|pure|elemental|impure|non_recursive|module)\s+|"
    r"(?:integer|real|logical|complex|character|double\s+precision|"
    r"type\s*\(\s*\w+\s*\)|class\s*\(\s*\w+\s*\))(?:\s*\([^)]*\))?(?:\s*\*\s*"
    r"\d+)?\s+)*(subroutine|function)\s+\w+", re.I)
_MODULE = re.compile(r"^\s*(module|submodule)\b(?!\s+procedure\b)"
                     r"(?:\s*\([^)]*\))?\s+\w+\s*$", re.I)
_BLOCKDATA = re.compile(r"^\s*block\s*data\b", re.I)
_PROGRAM = re.compile(r"^\s*program\s+(\w+)", re.I)
_END_UNIT = re.compile(r"^\s*end\s*(?:(program|subroutine|function|module|"
                       r"submodule|block\s*data)\b.*)?$", re.I)
_INTERFACE = re.compile(r"^\s*(abstract\s+)?interface\b", re.I)
_END_INTERFACE = re.compile(r"^\s*end\s*interface\b", re.I)


def _code(line: str) -> str:
    """A Fortran line without its trailing comment (outside strings)."""
    q = None
    for i, c in enumerate(line):
        if q:
            if c == q:
                q = None
        elif c in "'\"":
            q = c
        elif c == "!":
            return line[:i]
    return line


def main_program_span(lines: list[str]) -> tuple[int, int, str]:
    """(index of the program statement, index of its end statement, name);
    ConvertError when there is none."""
    start = None
    stack: list[str] = []
    in_iface = 0
    for k, raw in enumerate(lines):
        line = _code(raw)
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if _INTERFACE.match(line):
            in_iface += 1
            continue
        if _END_INTERFACE.match(line):
            in_iface = max(0, in_iface - 1)
            continue
        m = _PROGRAM.match(line)
        if m and not stack:
            start, name = k, m.group(1)
            stack.append("program")
            continue
        if _UNIT_START.match(line) or _MODULE.match(line) or \
                _BLOCKDATA.match(line):
            stack.append("unit")
            continue
        if _END_UNIT.match(line) and stack:
            kind = stack.pop()
            if kind == "program" and start is not None:
                return start, k, name
    raise ConvertError("no_program_statement")


_SPEC_HEAD = re.compile(r"^\s*(use\b|import\b|implicit\b)", re.I)


def convert_f(text: str, cs: list[K.Check], v: dict) -> tuple[str, list]:
    edits = []
    text, changed = preprocess(text, v.get("flags", []))
    if changed:
        edits.append("preprocessor directives applied (#define, #if)")
    lines = text.splitlines()
    p, e, name = main_program_span(lines)
    # the bare SAVE goes after the USE, IMPORT and IMPLICIT statements
    k = p + 1
    ins = k
    cont = False
    while k < e:
        code = _code(lines[k]).strip()
        if cont:
            cont = code.endswith("&")
            k += 1
            ins = k
            continue
        if not code or code.startswith("#"):
            k += 1
            continue
        if _SPEC_HEAD.match(code):
            cont = code.endswith("&")
            k += 1
            ins = k
            continue
        break
    body = lines[p + 1:e]
    has_save = any(re.search(r"^\s*save\b|,\s*save\b", _code(ln), re.I)
                   for ln in body)
    lines[p] = "subroutine hv_orig_main"
    edits.append(f"main program {name} as subroutine hv_orig_main")
    lines[e] = "end subroutine hv_orig_main"
    if not has_save:
        lines.insert(ins, "save")
        edits.append("a bare save (a main program's variables are saved)")
    else:
        edits.append("no bare save: the program has a SAVE of its own")
    rows = _pattern_data(cs, "f90")
    data, sets = f_data(rows, v.get("stderr", False))
    req = device_requires(text)
    if req:
        edits.append(f"the self-check's module states {req}")
    runtime = FR.RUNTIME.replace("@@DATA@@", data).replace(
        "@@SET@@", sets).replace("@@REQUIRES@@", f"!$omp requires {req}"
                                 if req else "")
    return "\n".join(lines) + "\n" + runtime, edits


_GLOBAL_REQS = ("reverse_offload", "unified_address",
                "unified_shared_memory", "self_maps")


def device_requires(text: str) -> str:
    """The device-global requirements of a Fortran program's requires
    directives (5.2 §8.2), as one clause list ('' for none)."""
    found = []
    for d in directives(text, "f90"):
        body = " ".join(re.sub(r"!\$omp&?", " ", d, flags=re.I).split())
        if re.match(r"requires\b", body, re.I):
            for r in _GLOBAL_REQS:
                if re.search(rf"\b{r}\b", body, re.I) and r not in found:
                    found.append(r)
    return " ".join(found)


def _f_str(s: str, width: int = 60) -> str:
    """A Fortran character expression of `s` (achar() for control
    characters), split across continuation lines."""
    parts, cur = [], ""
    for ch in s:
        if ord(ch) < 32 or ord(ch) == 127:
            if cur:
                parts.append("'" + cur.replace("'", "''") + "'")
                cur = ""
            parts.append(f"achar({ord(ch)})")
        else:
            cur += ch
            if len(cur) >= width:
                parts.append("'" + cur.replace("'", "''") + "'")
                cur = ""
    if cur or not parts:
        parts.append("'" + cur.replace("'", "''") + "'")
    return " // &\n      ".join(parts)


def f_data(rows: list[tuple], merge: bool) -> tuple[str, str]:
    n = len(rows)
    pl = max([len(r[2]) for r in rows] + [1])
    data = (f"  integer, parameter :: hv_n = {n}\n"
            f"  integer, parameter :: hv_merge = {1 if merge else 0}\n"
            f"  integer, parameter :: hv_pl = {pl}")
    sets = ["    hv_kind = 0", "    hv_pat = ' '"]
    for i, r in enumerate(rows, start=1):
        sets.append(f"    hv_kind({i}) = {r[0]}")
        sets.append(f"    hv_pat({i}) = {_f_str(r[2])}")
    return data, "\n".join(sets)


# --- the program -----------------------------------------------------------------------

def _modes(record: dict, v: dict, text: str) -> tuple:
    x = v.get("env", {}).get("HSA_XNACK")
    if x == "1" or "unified_shared_memory" in [
            r.lower() for r in record.get("requires", [])] or re.search(
            r"^\s*(#\s*pragma\s+omp|!\$omp)\s+requires\b[^\n]*"
            r"unified_shared_memory", text, re.I | re.M):
        return ("unified",)
    if x == "0":
        return ("copy",)
    return ("copy", "unified")


def _header(record: dict, v: dict, k: int, version: int, oracle: str,
            nchecks: int, edits: list, lang: str, bugfix: dict | None,
            text: str) -> list[str]:
    add = (record.get("history") or {}).get("added") or {}
    lines = [
        "Harvested test (tools/campaigns/harvest.py convert; do not edit)",
        f"source: {record['source']} {record['path']} at "
        f"{record['commit'][:12]}",
        f"license: {record['license']}",
        f"original sha256: {hashlib.sha256(text.encode()).hexdigest()}",
    ]
    if add:
        lines.append(f"added by: {add.get('commit', '')[:12]} "
                     f"{add.get('date', '')} {add.get('subject', '')}")
    if bugfix:
        lines.append(f"bug fix: {bugfix['kind']}"
                     + (f" {', '.join(bugfix['refs'])}" if bugfix['refs']
                        else ""))
    if record.get("aomp_issues"):
        lines.append("AOMP issues naming it: " + ", ".join(
            f"#{i['number']} ({i['state'].lower()})"
            for i in record["aomp_issues"]))
    if record.get("xfail") or record.get("unsupported") or \
            record.get("requires"):
        lines.append("lit: REQUIRES " + ",".join(record.get("requires", []))
                     + "; UNSUPPORTED " + ",".join(record.get(
                         "unsupported", [])) + "; XFAIL " + ",".join(
                         record.get("xfail", [])))
    if record["source"] == "aomp":
        lines.append(f"suite: {record['suite']}")
    lines += [
        f"variant {k + 1}: flags {' '.join(v.get('flags', [])) or '(none)'}"
        f"; environment {v.get('env') or '(none)'}"
        f"; arguments {' '.join(v.get('args', [])) or '(none)'}",
        f"spec version: {version // 10}.{version % 10} (the grammar reads "
        "every directive at it; at least the RUN line's -fopenmp-version)",
        "expected: exit status 0" + (
            f" and the output ({'stdout and stderr' if v.get('stderr') else 'stdout'}) "
            f"matches the {nchecks} {'/'.join(v.get('prefixes', []))} lines "
            "(offload/engine/harvest/checks.py: FileCheck order, numbers by value)"
            if oracle == "filecheck" else
            " (the test's own check; no FileCheck lines)"),
        "self-check: RESULT ran_on_host=<0|1> check=<pass|fail>",
        "edits: " + "; ".join(edits + ["self-check appended"]),
    ]
    if lang == "c":
        return ["/*"] + [" * " + ln.replace("*/", "* /") for ln in lines] + \
            [" */"]
    return ["! " + ln for ln in lines]


def convert(record: dict, k: int, v: dict, text: str, nvariants: int,
            bugfix: dict | None = None) -> Converted:
    lang = record["lang"]
    # a test with device routines and no directive is an OpenMP program
    model = "omp" if record["model"] == "none" else record["model"]
    if model != "omp":
        raise ConvertError(f"model {model}: only OpenMP is converted")
    prefixes = v.get("prefixes", [])
    cs = K.parse_checks(text, tuple(prefixes)) if prefixes else []
    oracle = "filecheck" if cs else "exit_status"
    if lang == "c":
        body, edits = convert_c(text, cs, v)
    elif lang == "f90":
        body, edits = convert_f(text, cs, v)
    else:
        raise ConvertError(f"language {lang}")
    version, gerr = spec_version(text, lang, v.get("flags", []), model)
    head = _header(record, v, k, version, oracle, len(cs), edits, lang,
                   bugfix, text)
    if lang == "c":
        src = CR.PRELUDE + "\n".join(head) + "\n" + body[len(CR.PRELUDE):]
    else:
        src = "\n".join(head) + "\n" + body
    return Converted(id=program_id(record["id"], k, nvariants),
                     record=record["id"], variant=k, lang=lang, model=model,
                     version=version, source=src, oracle=oracle,
                     checks=len(cs), prefixes=prefixes,
                     stderr=bool(v.get("stderr")),
                     modes=_modes(record, v, text), edits=edits,
                     grammar_errors=gerr)


# --- Programs by code ---------------------------------

def _code_text(text: str, lang: str) -> str:
    """A program's code: comments (the header among them) dropped, runs of
    white space folded to one blank. Fortran directives are code."""
    if lang == "c":
        # string literals are code too: put them back from the spans' gaps
        out, last = [], 0
        for a, b in _c_code_spans(text):
            gap = text[last:a]
            if gap.lstrip().startswith(("\"", "'")):
                out.append(gap)
            out.append(text[a:b])
            last = b
        code = " ".join(out)
    else:
        lines = []
        for ln in text.splitlines():
            if re.match(r"^\s*!\$(omp|acc)", ln, re.I):
                lines.append(ln)
            else:
                lines.append(_code(ln))
        code = "\n".join(lines)
    return " ".join(code.split())


def code_key(text: str, lang: str) -> str:
    """sha256 of a program's code (``_code_text``): two programs with the
    same key differ only in comments and blanks."""
    return hashlib.sha256(_code_text(text, lang).encode()).hexdigest()


def holdout_by_code(text: str, lang: str) -> bool:
    """The holdout split by code, not by text: a program whose code another
    program shares (two RUN variants that differ only in an ignored flag,
    the same test in two suites) falls on the same side as it."""
    return int(code_key(text, lang), 16) < int(HOLDOUT_FRACTION * (1 << 256))


def distinct_variants(record: dict, ks: list[int], text: str
                      ) -> tuple[list[int], dict[int, list[int]]]:
    """The variants (indices `ks` of record["variants"]) whose converted
    program is distinct by code and memory modes, in order, and for each
    kept one the variants merged into it."""
    kept, merged, seen = [], {}, {}
    for k in ks:
        try:
            p = convert(record, 0, record["variants"][k], text, 1)
        except ConvertError:
            kept.append(k)
            continue
        key = (code_key(p.source, p.lang), p.modes)
        if key in seen:
            merged.setdefault(seen[key], []).append(k)
            continue
        seen[key] = k
        kept.append(k)
    return kept, merged
