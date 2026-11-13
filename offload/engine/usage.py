"""The usage profile of real offload codes: what the fuzzer is steered toward
and what the stress sweeps must cover.

A light scanner for Fortran (free-form ``!$omp`` / ``!$acc``) and C
(``#pragma omp`` / ``#pragma acc``). Per file it records directives (construct,
clauses with list lengths, lines spanned), offload regions (feature set in one
vocabulary: ``dir:``, ``clause:``, ``map:``, ``red:``, ``base:``; loop depth,
collapse, implicitly shared scalars), procedures, modules and derived types
(argument counts, device routines and variables, components, EXTENDS chains)
and, for C, struct nesting, pointer members and ``declare target`` blocks.

``profile`` aggregates a code base into distributions and maxima, module
dependency depth and device call-chain depth. ``region_features`` also runs on
generated programs (offload.engine.fuzz_steer), so one extractor counts both.
tests/test_offload.py checks it against hand counts.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

LIST_CLAUSES = frozenset({
    "private", "firstprivate", "lastprivate", "shared", "map", "reduction",
    "in_reduction", "task_reduction", "depend", "is_device_ptr",
    "use_device_ptr", "use_device_addr", "has_device_addr", "copy",
    "copyin", "copyout", "create", "present", "no_create", "delete",
    "attach", "detach", "deviceptr", "device_resident", "link", "to",
    "from", "enter", "linear", "aligned", "nontemporal", "allocate",
    "device", "host", "self", "use_device", "cache", "uniform",
    "inclusive", "exclusive", "affinity"})
OMP_COMPUTE_FIRST = "target"
OMP_DATA_ONLY = ("target data", "target enter data", "target exit data",
                 "target update")
ACC_COMPUTE = ("parallel", "kernels", "serial")
CONSTRUCT_WORDS = frozenset({
    "target", "teams", "distribute", "parallel", "do", "for", "simd",
    "loop", "data", "enter", "exit", "update", "declare", "end", "kernels",
    "serial", "routine", "atomic", "critical", "single", "master",
    "masked", "taskloop", "task", "taskwait", "taskgroup", "barrier",
    "wait", "host_data", "begin", "ordered", "section", "sections",
    "workshare", "flush", "scan", "cache", "init", "shutdown", "set",
    "metadirective", "interop", "dispatch", "scope", "tile", "unroll",
    "read", "write", "capture", "requires", "allocate", "allocators",
    "reduction", "mapper", "variant", "simd", "seq", "gang", "worker",
    "vector", "independent", "auto"})
# words that are clauses even without a parenthesised argument
BARE_CLAUSES = frozenset({
    "nowait", "seq", "gang", "worker", "vector", "independent", "auto",
    "untied", "mergeable", "nogroup", "finalize", "if_present", "read",
    "write", "update", "capture", "compare", "seq_cst", "acq_rel",
    "acquire", "release", "relaxed", "inbranch", "notinbranch", "nohost",
    "async", "wait", "unified_shared_memory", "unified_address",
    "reverse_offload", "dynamic_allocators", "self_maps"})
ACC_LOOP_CLAUSE = ("gang", "worker", "vector", "seq", "independent", "auto")
TYPE_SPEC = re.compile(
    r"^(integer|real|logical|complex|character|double\s+precision|"
    r"double\s+complex|type\s*\(|class\s*\()", re.I)


# --- low-level text handling ---------------------------------------------------------------

def _strip_f_comment(line: str) -> str:
    """The line without a trailing ``!`` comment (strings respected)."""
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


def split_top(text: str, sep: str = ",") -> list[str]:
    """`text` split at top-level `sep` (not inside parentheses, brackets or
    strings); empty items dropped."""
    out, depth, cur, q = [], 0, [], None
    for ch in text:
        if q:
            cur.append(ch)
            if ch == q:
                q = None
            continue
        if ch in "'\"":
            q = ch
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == sep and depth == 0:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur).strip())
    return [x for x in out if x]


@dataclass
class Directive:
    model: str                # omp | acc
    name: str                 # leaves joined by " " ("target teams distribute")
    clauses: list             # [(clause, modifier text, item count, items)]
    lines: int                # physical lines (1 + continuations)
    length: int               # characters of the joined directive
    line: int                 # first line number (1-based)
    text: str = ""

    def clause_names(self) -> list[str]:
        return [c[0] for c in self.clauses]


_MODIFIED = {"map": True, "reduction": True, "in_reduction": True,
             "task_reduction": True, "depend": True, "linear": False,
             "aligned": False, "allocate": True, "to": True, "from": True,
             "lastprivate": True, "device": True, "copyin": True,
             "copyout": True, "create": True}


def _clause_items(name: str, arg: str) -> tuple[str, list[str]]:
    """(modifier text, items) of a clause argument: a modifier before the
    first top-level ':' (map(always, tofrom: a, b)) is split off for the
    clauses that take one."""
    mod = ""
    if _MODIFIED.get(name):
        depth = 0
        for i, ch in enumerate(arg):
            if ch in "([":
                depth += 1
            elif ch in ")]":
                depth -= 1
            elif ch == ":" and depth == 0:
                # a Fortran array section a(1:n) is inside parentheses, so a
                # top-level colon is the modifier separator
                mod, arg = arg[:i].strip(), arg[i + 1:]
                break
    if name in ("aligned", "linear") and ":" in arg:
        arg = arg.rsplit(":", 1)[0]
    return mod, split_top(arg)


NAME_WORDS = {
    "omp": frozenset({
        "target", "teams", "distribute", "parallel", "do", "for", "simd",
        "loop", "data", "enter", "exit", "update", "declare", "end",
        "atomic", "critical", "single", "master", "masked", "taskloop",
        "task", "taskwait", "taskgroup", "barrier", "begin", "ordered",
        "section", "sections", "workshare", "flush", "scan", "requires",
        "metadirective", "interop", "dispatch", "scope", "tile", "unroll",
        "allocate", "allocators", "reduction", "mapper", "variant",
        "taskyield", "cancel", "cancellation", "point", "threadprivate",
        "error", "nothing", "assume", "assumes", "depobj"}),
    "acc": frozenset({
        "parallel", "kernels", "serial", "loop", "data", "enter", "exit",
        "update", "declare", "end", "routine", "atomic", "wait", "init",
        "shutdown", "set", "host_data", "cache"}),
}
ATOMIC_WORDS = frozenset({"read", "write", "update", "capture", "compare"})
NAMED_FIRST = frozenset({"routine", "critical", "cache", "wait"})


def _close_paren(s: str, j: int) -> int:
    depth, k = 0, j
    while k < len(s):
        if s[k] == "(":
            depth += 1
        elif s[k] == ")":
            depth -= 1
            if depth == 0:
                return k
        k += 1
    return len(s)


def parse_directive(body: str, model: str, line: int = 0,
                    nlines: int = 1) -> Directive:
    """`body`: the directive text after the sentinel (``target teams
    map(to: a) private(x)``). The name is the leading construct words;
    the rest are clauses (with or without an argument)."""
    s = body.strip()
    words, clauses, i = [], [], 0
    names = NAME_WORDS[model]
    while i < len(s):
        m = re.match(r"[\s,]*([A-Za-z_][A-Za-z_0-9]*)\s*", s[i:])
        if not m:
            i += 1
            continue
        w = m.group(1).lower()
        j = i + m.end()
        paren = j < len(s) and s[j] == "("
        arg = None
        if paren:
            k = _close_paren(s, j)
            arg = s[j + 1:k]
            j = k + 1
        in_name = not clauses
        if in_name and paren:
            if w in NAMED_FIRST and (not words or words == ["end"]):
                words.append(w)
                items = split_top(arg)
                clauses.append((w, "", len(items), items))
                i = j
                continue
            if w == "target" and words and words[-1] == "declare":
                words.append(w)
                mod, items = _clause_items("declare_target", arg)
                clauses.append(("declare_target", mod, len(items), items))
                i = j
                continue
            if w in ("reduction", "mapper", "variant", "simd") and \
                    words and words[-1] == "declare":
                words.append(w)
                clauses.append(("declare_" + w, "", 1, [arg]))
                i = j
                continue
            if w == "flush" or w == "depobj":
                words.append(w)
                i = j
                continue
            in_name = False
        if in_name:
            if w in ATOMIC_WORDS and words and words[-1] == "atomic":
                pass
            elif w == "update" and (not words or words[-1] in
                                    ("target", "end")):
                pass
            elif w in ATOMIC_WORDS and not (w == "update" and not words):
                in_name = False
            elif w not in names:
                in_name = False
            elif model == "acc" and w == "wait" and words:
                in_name = False
        if in_name:
            words.append(w)
        else:
            if arg is None:
                clauses.append((w, "", 0, []))
            else:
                mod, items = _clause_items(w, arg)
                clauses.append((w, mod, len(items), items))
        i = j
    return Directive(model, " ".join(words), clauses, nlines, len(s), line,
                     s)


# --- a small preprocessor (#if/#ifdef/#else/#endif with known defines) ---------------------

def _cpp_value(expr: str, defines: dict) -> bool:
    e = expr.strip()
    e = re.sub(r"defined\s*\(\s*(\w+)\s*\)|defined\s+(\w+)",
               lambda m: "1" if (m.group(1) or m.group(2)) in defines
               else "0", e)
    e = re.sub(r"\b([A-Za-z_]\w*)\b",
               lambda m: str(defines.get(m.group(1), 0)) if
               str(defines.get(m.group(1), 0)).lstrip("-").isdigit()
               else "1", e)
    e = e.replace("&&", " and ").replace("||", " or ")
    e = re.sub(r"!(?!=)", " not ", e)
    try:
        return bool(eval(e, {"__builtins__": {}}, {}))
    except Exception:
        return False


def preprocess(text: str, defines=()) -> str:
    """`text` with the lines of false #if branches blanked (line numbers
    kept) and every directive line blanked. `defines`: names or NAME=value."""
    defs = {}
    for d in defines:
        k, _, v = d.partition("=")
        defs[k] = v if v else 1
    out, stack = [], []        # stack of (taking, taken_any)
    for line in text.splitlines():
        st = line.strip()
        m = re.match(r"^#\s*(if|ifdef|ifndef|elif|else|endif)\b(.*)$", st)
        live = all(t for t, _ in stack)
        if m:
            kw, rest = m.group(1), m.group(2)
            if kw in ("if", "ifdef", "ifndef"):
                v = (rest.strip().split()[0] in defs) if kw == "ifdef" \
                    and rest.strip() else \
                    (rest.strip().split()[0] not in defs) if kw == "ifndef" \
                    and rest.strip() else _cpp_value(rest, defs)
                stack.append((v, v))
            elif kw == "elif" and stack:
                t, any_ = stack.pop()
                v = (not any_) and _cpp_value(rest, defs)
                stack.append((v, any_ or v))
            elif kw == "else" and stack:
                t, any_ = stack.pop()
                stack.append((not any_, True))
            elif kw == "endif" and stack:
                stack.pop()
            out.append("")
            continue
        if st.startswith("#") and not st.startswith("#pragma"):
            out.append("")
            continue
        out.append(line if live else "")
    return "\n".join(out)


# --- Fortran ------------------------------------------------------------------------------

_SENT = re.compile(r"^\s*!\$(omp|acc)(&?)\s?(.*)$", re.I)


def fortran_statements(text: str) -> list[tuple[int, int, str, str | None]]:
    """[(first line, physical lines, joined text, model or None)]: free-form
    statements and directives with continuations joined; comment and blank
    lines between continuation lines are skipped; ``#`` lines dropped;
    ``;`` separated statements split."""
    lines = text.splitlines()
    out = []
    i = 0
    n = len(lines)
    while i < n:
        raw = lines[i]
        if raw.lstrip().startswith("#"):
            i += 1
            continue
        m = _SENT.match(raw)
        if m:
            model = m.group(1).lower()
            body = _strip_f_comment(m.group(3))
            start, phys = i, 1
            while body.rstrip().endswith("&"):
                body = body.rstrip()[:-1]
                i += 1
                while i < n and not _SENT.match(lines[i]) and (
                        not lines[i].strip() or
                        lines[i].lstrip().startswith(("!", "#"))):
                    i += 1
                if i >= n:
                    break
                m2 = _SENT.match(lines[i])
                if not m2:
                    break
                nxt = _strip_f_comment(m2.group(3)).lstrip()
                if nxt.startswith("&"):
                    nxt = nxt[1:]
                body += " " + nxt
                phys += 1
            out.append((start + 1, phys, body.strip(), model))
            i += 1
            continue
        s = raw.strip()
        if not s or s.startswith("!"):
            i += 1
            continue
        stmt = _strip_f_comment(raw).rstrip()
        start, phys = i, 1
        while stmt.endswith("&"):
            stmt = stmt[:-1]
            i += 1
            while i < n and (not lines[i].strip() or
                             lines[i].lstrip().startswith("#") or
                             lines[i].lstrip().startswith("!") and
                             not _SENT.match(lines[i])):
                i += 1
            if i >= n:
                break
            nxt = _strip_f_comment(lines[i]).strip()
            if nxt.startswith("&"):
                nxt = nxt[1:]
            stmt += " " + nxt.rstrip()
            phys += 1
        for part in split_top(stmt.strip(), ";"):
            out.append((start + 1, phys, part, None))
        i += 1
    return out


@dataclass
class Proc:
    name: str
    kind: str                       # subroutine | function
    nargs: int
    nlocals: int = 0
    device: bool = False
    optional: int = 0
    value: int = 0
    class_dummies: int = 0
    calls: set = field(default_factory=set)
    file: str = ""


@dataclass
class DType:
    name: str
    components: int = 0
    alloc: int = 0
    pointer: int = 0
    children: set = field(default_factory=set)   # component derived types
    extends: str | None = None
    bindings: int = 0
    nopass: int = 0
    pass_obj: int = 0
    generic: int = 0
    deferred: int = 0
    abstract: bool = False
    parameterized: bool = False


@dataclass
class Region:
    model: str
    name: str
    line: int
    features: set = field(default_factory=set)
    loop_depth: int = 0
    collapse: int = 0
    implicit_scalars: int = 0
    explicit_items: int = 0
    nested_directives: int = 0
    statements: int = 0
    calls: set = field(default_factory=set)
    idents: set = field(default_factory=set)   # names not declared locally
    last: int = 0
    proc: str = ""


@dataclass
class FileScan:
    path: str
    lang: str
    lines: int = 0
    directives: list = field(default_factory=list)
    regions: list = field(default_factory=list)
    procs: list = field(default_factory=list)
    modules: dict = field(default_factory=dict)    # name -> info dict
    uses: set = field(default_factory=set)         # modules used anywhere
    use_only: list = field(default_factory=list)   # list lengths
    types: dict = field(default_factory=dict)      # name -> DType
    select_type: int = 0
    max_line: int = 0
    max_stmt_lines: int = 0
    submodules: int = 0
    interfaces: int = 0
    bind_c: int = 0


_PROC_HEAD = re.compile(
    r"^(?:(?:pure|elemental|recursive|impure|module|non_recursive)\s+|"
    r"(?:integer|real|logical|complex|double\s+precision|type\s*\([^)]*\)|"
    r"class\s*\([^)]*\))(?:\s*\(\s*(?:kind\s*=\s*)?\w+\s*\))?\s+|"
    r"(?:real|integer|complex|logical)\s*\*\s*\d+\s+)*"
    r"(subroutine|function)\s+(\w+)\s*(?:\(([^)]*)\))?", re.I)
_END = re.compile(r"^end\s*(subroutine|function|module|program|type|"
                  r"interface|submodule|block\s*data|select)?\b", re.I)


def _decl_entities(stmt: str) -> tuple[str, list[str]]:
    """(type-spec + attributes, entity names) of a declaration statement."""
    if "::" in stmt:
        spec, ents = stmt.split("::", 1)
    else:
        m = re.match(r"^(\w+(?:\s*\([^)]*\))?(?:\s*\*\s*\d+)?)\s+(.*)$",
                     stmt)
        if not m:
            return stmt, []
        spec, ents = m.group(1), m.group(2)
    names = []
    for e in split_top(ents):
        mm = re.match(r"\s*([A-Za-z_]\w*)", e)
        if mm:
            names.append(mm.group(1).lower())
    return spec.lower(), names


def _ent_is_scalar(stmt: str, name: str) -> bool:
    if "dimension" in stmt.split("::")[0].lower():
        return False
    ents = stmt.split("::", 1)[1] if "::" in stmt else stmt
    for e in split_top(ents):
        mm = re.match(r"\s*([A-Za-z_]\w*)\s*(\(|\*|=|$)", e)
        if mm and mm.group(1).lower() == name:
            return mm.group(2) != "("
    return True


def _features_of(d: Directive) -> set:
    f = set()
    for leaf in d.name.split():
        if leaf != "end":
            f.add(f"dir:{leaf}")
    for c, mod, n, items in d.clauses:
        f.add(f"clause:{c}")
        if c == "map":
            mods = [m.strip().lower() for m in re.split(r"[ ,]+", mod)
                    if m.strip()]
            typ = next((m for m in mods if m in ("to", "from", "tofrom",
                                                  "alloc", "release",
                                                  "delete")), "tofrom")
            f.add(f"map:{typ}")
            for m in mods:
                if m in ("always", "close", "present"):
                    f.add(f"map:mod:{m}")
            if any("%" in it for it in items):
                f.add("map:component")
            if any(re.search(r"\(.*:.*\)", it) for it in items):
                f.add("map:section")
        elif c in ("reduction", "in_reduction", "task_reduction"):
            op = mod.split(",")[-1].strip().lower()
            if op:
                f.add(f"red:{op}")
        elif c in ("default", "defaultmap") and items:
            f.add(f"clause:{c}:{items[0].lower().split(':')[0].strip()}")
    return f


def _loop_depth(stmts: list[str]) -> int:
    depth = best = 0
    for s in stmts:
        low = s.lower()
        if re.match(r"^(\w+\s*:\s*)?do\b(?!\s*while)", low) and \
                not re.match(r"^do\s*$", low) or \
                re.match(r"^(\w+\s*:\s*)?do\s+concurrent\b", low):
            depth += 1
            best = max(best, depth)
        elif re.match(r"^(\w+\s*:\s*)?do\s*$", low) or \
                re.match(r"^(\w+\s*:\s*)?do\s+while\b", low):
            depth += 1
            best = max(best, depth)
        elif re.match(r"^end\s*do\b", low):
            depth = max(0, depth - 1)
    return best


_IDENT = re.compile(r"(?<![%\w])([A-Za-z_]\w*)(?!\s*%)\b")
_KEYWORDS = frozenset("""
if then else elseif endif do end enddo call return exit cycle while and or
not true false eq ne lt le gt ge eqv neqv select case default where
elsewhere forall associate block continue stop print write read
""".split())


def scan_fortran(text: str, path: str = "") -> FileScan:
    fs = FileScan(path, "f90")
    raw_lines = text.splitlines()
    fs.lines = len(raw_lines)
    fs.max_line = max((len(ln) for ln in raw_lines), default=0)
    stmts = fortran_statements(text)
    # scope tracking
    stack: list[tuple[str, str]] = []      # (kind, name)
    proc: Proc | None = None
    procs_stack: list[Proc] = []
    decls: dict = {}                        # name -> (stmt, scalar)
    module_decls: dict = defaultdict(dict)
    in_contains: dict = {}
    cur_type: DType | None = None
    in_type_contains = False
    region: Region | None = None
    region_stmts: list[str] = []
    region_end = None
    region_listed: set = set()
    region_depth_stack: list = []
    args: set = set()
    for (ln, phys, s, model) in stmts:
        fs.max_stmt_lines = max(fs.max_stmt_lines, phys)
        if model:
            d = parse_directive(s, model, ln, phys)
            fs.directives.append(d)
            name = d.name
            if region is not None:
                if name.startswith("end ") and \
                        name[4:] == region.name:
                    _close_region(region, region_stmts, decls, args,
                                  region_listed)
                    fs.regions.append(region)
                    region = None
                    continue
                region.features |= _features_of(d)
                region.nested_directives += 1
                for c, mod, n, items in d.clauses:
                    region_listed |= {re.split(r"[(%]", it)[0].strip()
                                      .lower() for it in items}
                continue
            if _is_compute(d):
                region = Region(model, name, ln, _features_of(d))
                region.proc = proc.name if proc is not None else ""
                region_listed = set()
                for c, mod, n, items in d.clauses:
                    region.explicit_items += n
                    region_listed |= {re.split(r"[(%]", it)[0].strip()
                                      .lower() for it in items}
                    if c == "collapse" and items:
                        try:
                            region.collapse = int(items[0])
                        except ValueError:
                            region.collapse = -1
                region_stmts = []
                # a combined construct with a loop ends with its loop (no
                # end directive is required in Fortran)
                region.combined_loop = any(
                    w in name.split() for w in ("do", "loop", "simd")) \
                    if model == "omp" else "loop" in name.split()
                region.open_do = 0
                region.seen_do = False
                continue
            if model == "omp" and name.startswith("declare target") or \
                    model == "acc" and name.startswith("routine"):
                _mark_device(d, proc, stack, fs, module_decls)
            if model == "acc" and name.startswith("declare"):
                _mark_device(d, proc, stack, fs, module_decls)
            continue
        low = s.lower()
        if region is not None:
            region_stmts.append(s)
            region.statements += 1
            for mm in re.finditer(r"\bcall\s+(\w+)", low):
                region.calls.add(mm.group(1))
            for mm in re.finditer(r"\b([a-z_]\w*)\s*\(", low):
                region.calls.add(mm.group(1))
            if re.match(r"^(\w+\s*:\s*)?do\b", low):
                region.open_do += 1
                region.seen_do = True
            elif re.match(r"^end\s*do\b", low):
                region.open_do -= 1
            if region.combined_loop and region.seen_do and \
                    region.open_do <= 0:
                _close_region(region, region_stmts, decls, args,
                              region_listed)
                fs.regions.append(region)
                region = None
            continue
        # derived types
        mt = re.match(r"^type\s*(?:,\s*([^:]*?))?\s*(?:::)?\s*(\w+)\s*"
                      r"(\([^)]*\))?\s*$", low)
        if mt and not low.startswith("type(") and \
                not low.startswith("type (") and \
                not re.match(r"^type\s+is\b", low):
            attrs = mt.group(1) or ""
            cur_type = DType(mt.group(2))
            em = re.search(r"extends\s*\(\s*(\w+)\s*\)", attrs)
            cur_type.extends = em.group(1) if em else None
            cur_type.abstract = "abstract" in attrs
            cur_type.parameterized = bool(mt.group(3))
            fs.types[cur_type.name] = cur_type
            in_type_contains = False
            continue
        if cur_type is not None:
            if re.match(r"^end\s*type\b", low):
                cur_type = None
                continue
            if low == "contains":
                in_type_contains = True
                continue
            if in_type_contains:
                if low.startswith("generic"):
                    cur_type.generic += 1
                    cur_type.bindings += 1
                elif low.startswith("procedure") or low.startswith("final"):
                    cur_type.bindings += 1
                    if "nopass" in low:
                        cur_type.nopass += 1
                    else:
                        cur_type.pass_obj += 1
                    if "deferred" in low:
                        cur_type.deferred += 1
                continue
            if TYPE_SPEC.match(low) or low.startswith("procedure"):
                spec, names = _decl_entities(low)
                cur_type.components += len(names)
                if "allocatable" in spec:
                    cur_type.alloc += len(names)
                if "pointer" in spec:
                    cur_type.pointer += len(names)
                tm = re.match(r"^(?:type|class)\s*\(\s*(\w+)", spec)
                if tm:
                    cur_type.children.add(tm.group(1))
            continue
        if re.match(r"^select\s+type\b", low) or \
                re.match(r"^\w+\s*:\s*select\s+type\b", low):
            fs.select_type += 1
        if re.match(r"^(abstract\s+)?interface\b", low):
            fs.interfaces += 1
        if "bind(c" in low.replace(" ", ""):
            fs.bind_c += 1
        mm = re.match(r"^module\s+(\w+)\s*$", low)
        if mm and mm.group(1) != "procedure":
            stack.append(("module", mm.group(1)))
            fs.modules[mm.group(1)] = {"vars": 0, "device_vars": 0,
                                       "uses": set(), "scalars": set(),
                                       "device_names": set()}
            continue
        if re.match(r"^submodule\b", low):
            fs.submodules += 1
            sm = re.match(r"^submodule\s*\(\s*(\w+)", low)
            stack.append(("submodule", sm.group(1) if sm else "?"))
            continue
        mm = re.match(r"^program\s+(\w+)", low)
        if mm:
            stack.append(("program", mm.group(1)))
            continue
        mu = re.match(r"^use\b\s*(?:,\s*\w+\s*::)?\s*(?:::)?\s*(\w+)\s*(,.*)?$",
                      low)
        if mu:
            fs.uses.add(mu.group(1))
            if stack and stack[-1][0] == "module":
                fs.modules[stack[-1][1]]["uses"].add(mu.group(1))
            if mu.group(2) and "only" in mu.group(2):
                rest = mu.group(2).split(":", 1)[1] if ":" in mu.group(2) \
                    else ""
                fs.use_only.append(len(split_top(rest)))
            continue
        mp = _PROC_HEAD.match(low)
        if mp and not low.startswith("end"):
            argl = [a.strip() for a in (mp.group(3) or "").split(",")
                    if a.strip()]
            p = Proc(mp.group(2), mp.group(1), len(argl), file=path)
            procs_stack.append((proc, decls, args))
            proc, decls, args = p, {}, set(argl)
            fs.procs.append(p)
            stack.append((mp.group(1), mp.group(2)))
            continue
        me = _END.match(low)
        if me and (low == "end" or me.group(1)):
            kind = (me.group(1) or "").lower()
            if stack:
                k, nm = stack.pop()
                if k in ("subroutine", "function"):
                    if proc is not None:
                        proc.nlocals = len([x for x in decls
                                            if x not in args])
                    proc, decls, args = procs_stack.pop() if procs_stack \
                        else (None, {}, set())
            del kind
            continue
        if low == "contains":
            if stack:
                in_contains[stack[-1]] = True
            continue
        if TYPE_SPEC.match(low) and (
                "::" in low or re.match(r"^(integer|real|logical|"
                                        r"double precision)\s+\w", low)):
            spec, names = _decl_entities(low)
            if proc is not None:
                for nm in names:
                    decls[nm] = (s, _ent_is_scalar(s, nm) and
                                 "dimension" not in spec)
                if args:
                    hit = [x for x in names if x in args]
                    if "optional" in spec:
                        proc.optional += len(hit)
                    if "value" in spec:
                        proc.value += len(hit)
                    if spec.startswith("class"):
                        proc.class_dummies += len(hit)
            elif stack and stack[-1][0] == "module" and \
                    "parameter" not in spec:
                fs.modules[stack[-1][1]]["vars"] += len(names)
                for nm in names:
                    if _ent_is_scalar(s, nm) and "dimension" not in spec \
                            and "allocatable" not in spec and \
                            "pointer" not in spec:
                        fs.modules[stack[-1][1]]["scalars"].add(nm)
                    module_decls[stack[-1][1]][nm] = (
                        s, _ent_is_scalar(s, nm))
            elif stack and stack[-1][0] == "program":
                for nm in names:
                    decls[nm] = (s, _ent_is_scalar(s, nm) and
                                 "dimension" not in spec)
            continue
        if proc is not None:
            for mm in re.finditer(r"\b([a-z_]\w*)\s*\(", low):
                proc.calls.add(mm.group(1))
            for mm in re.finditer(r"\bcall\s+(\w+)", low):
                proc.calls.add(mm.group(1))
    if region is not None:
        _close_region(region, region_stmts, decls, args, region_listed)
        fs.regions.append(region)
    # module scalars visible in regions are counted only through procs'
    # own declarations (a conservative count)
    return fs


def _is_compute(d: Directive) -> bool:
    w = d.name.split()
    if not w or w[0] == "end":
        return False
    if d.model == "omp":
        return w[0] == "target" and (len(w) == 1 or w[1] not in (
            "data", "enter", "exit", "update"))
    return w[0] in ACC_COMPUTE


def _mark_device(d: Directive, proc, stack, fs, module_decls) -> None:
    items = []
    for c, mod, n, its in d.clauses:
        if c in ("declare_target", "to", "enter", "link", "create",
                 "copyin", "device_resident", "routine"):
            items += [it.lower() for it in its]
    if d.model == "acc" and d.name.startswith("routine"):
        if proc is not None and (not items or proc.name in items):
            proc.device = True
        return
    if not items and proc is not None:
        proc.device = True
        return
    if stack and stack[-1][0] == "module":
        mod = stack[-1][1]
        hit = {it for it in items if it in module_decls[mod]}
        fs.modules[mod]["device_vars"] += len(hit)
        fs.modules[mod]["device_names"] |= hit
    if proc is not None and proc.name in items:
        proc.device = True


def _close_region(region: Region, stmts: list[str], decls: dict,
                  args: set, listed: set) -> None:
    region.loop_depth = _loop_depth(stmts)
    used = set()
    for s in stmts:
        low = s.lower()
        if low.startswith(("call ", "end", "do ")) and \
                not low.startswith("do "):
            pass
        for mm in _IDENT.finditer(low):
            used.add(mm.group(1))
    loopvars = set()
    for s in stmts:
        mm = re.match(r"^(?:\w+\s*:\s*)?do\s+(\w+)\s*=", s.lower())
        if mm:
            loopvars.add(mm.group(1))
    scal = [nm for nm in used if nm in decls and decls[nm][1] and
            nm not in listed and nm not in loopvars and nm not in _KEYWORDS]
    region.implicit_scalars = len(scal)
    region.idents = {nm for nm in used if nm not in decls and
                     nm not in listed and nm not in _KEYWORDS}
    for nm in used:
        if nm in decls:
            st = decls[nm][0].lower()
            if st.startswith("type") or st.startswith("class"):
                region.features.add("base:derived")
                if st.startswith("class"):
                    region.features.add("base:class")
            if "allocatable" in st:
                region.features.add("base:allocatable")
            if "pointer" in st:
                region.features.add("base:pointer")
    if region.loop_depth >= 3:
        region.features.add("base:loop_nest3")
    if region.collapse >= 2:
        region.features.add(f"clause:collapse{min(region.collapse, 3)}")
    if any(re.match(r"^call\b", x.lower()) or
           re.search(r"\bcall\s+\w", x.lower()) for x in stmts):
        region.features.add("base:call")


# --- C ------------------------------------------------------------------------------------

def c_pragmas(text: str) -> list[tuple[int, int, str, str]]:
    """[(line, physical lines, body after 'omp'/'acc', model)] with
    backslash continuations joined; _Pragma("omp ...") too."""
    lines = text.splitlines()
    out, i = [], 0
    while i < len(lines):
        m = re.match(r"^\s*#\s*pragma\s+(omp|acc)\b(.*)$", lines[i])
        if m:
            body, phys, start = m.group(2), 1, i
            while body.rstrip().endswith("\\") and i + 1 < len(lines):
                body = body.rstrip()[:-1] + " " + lines[i + 1].strip()
                i += 1
                phys += 1
            body = re.sub(r"//.*$", "", body)
            body = re.sub(r"/\*.*?\*/", " ", body)
            out.append((start + 1, phys, body.strip(), m.group(1)))
        else:
            for mm in re.finditer(r'_Pragma\s*\(\s*"(omp|acc)\s+([^"]*)"',
                                  lines[i]):
                out.append((i + 1, 1, mm.group(2), mm.group(1)))
        i += 1
    return out


def _c_strip(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"),
                  text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def scan_c(text: str, path: str = "") -> FileScan:
    fs = FileScan(path, "c")
    lines = text.splitlines()
    fs.lines = len(lines)
    fs.max_line = max((len(ln) for ln in lines), default=0)
    prag = c_pragmas(text)
    code = _c_strip(text)
    clines = code.splitlines()
    for ln, phys, body, model in prag:
        d = parse_directive(body, model, ln, phys)
        fs.directives.append(d)
        fs.max_stmt_lines = max(fs.max_stmt_lines, phys)
        if _is_compute(d):
            r = Region(model, d.name, ln, _features_of(d))
            listed = set()
            for c, mod, n, items in d.clauses:
                r.explicit_items += n
                listed |= {re.split(r"[\[.\->]", it)[0].strip()
                           for it in items}
                if c == "collapse" and items:
                    try:
                        r.collapse = int(items[0])
                    except ValueError:
                        r.collapse = -1
            # the associated statement: braces from the next line
            body_lines, depth, started = [], 0, False
            for k in range(ln + phys - 1, min(len(clines), ln + 4000)):
                t = clines[k]
                if t.lstrip().startswith("#pragma"):
                    if started or not t.strip():
                        dd = parse_directive(
                            re.sub(r"^\s*#\s*pragma\s+(omp|acc)", "", t),
                            model, k + 1)
                        r.features |= _features_of(dd)
                        r.nested_directives += 1
                    continue
                body_lines.append(t)
                depth += t.count("{") - t.count("}")
                if "{" in t or re.search(r"\bfor\s*\(", t):
                    started = True
                if started and depth <= 0 and (";" in t or "}" in t):
                    break
            btxt = "\n".join(body_lines)
            r.loop_depth = _c_loop_depth(btxt)
            r.statements = btxt.count(";")
            r.calls = set(re.findall(r"\b([A-Za-z_]\w*)\s*\(", btxt)) - {
                "for", "if", "while", "switch", "return", "sizeof"}
            if r.calls:
                r.features.add("base:call")
            if "->" in btxt:
                r.features.add("base:pointer_member")
            if re.search(r"\.\w+\s*\[|->\w+\s*\[", btxt):
                r.features.add("base:struct_array_member")
            if r.loop_depth >= 3:
                r.features.add("base:loop_nest3")
            if r.collapse >= 2:
                r.features.add(f"clause:collapse{min(r.collapse, 3)}")
            fs.regions.append(r)
    # structs
    for mm in re.finditer(r"\bstruct\s+(\w+)\s*\{([^{}]*)\}", code):
        t = DType(mm.group(1))
        members = [x.strip() for x in mm.group(2).split(";") if x.strip()]
        t.components = len(members)
        t.pointer = sum(1 for x in members if "*" in x)
        for x in members:
            sm = re.match(r"^(?:const\s+)?struct\s+(\w+)", x)
            if sm:
                t.children.add(sm.group(1))
        fs.types[t.name] = t
    for mm in re.finditer(r"typedef\s+struct\s*(\w*)\s*\{([^{}]*)\}\s*(\w+)",
                          code):
        t = DType(mm.group(3))
        members = [x.strip() for x in mm.group(2).split(";") if x.strip()]
        t.components = len(members)
        t.pointer = sum(1 for x in members if "*" in x)
        fs.types[t.name] = t
    # functions: definitions at file scope
    device = False
    dev_depth = 0
    for k, t in enumerate(clines):
        if re.match(r"^\s*#\s*pragma\s+omp\s+(begin\s+)?declare\s+target"
                    r"\s*$", t):
            device = True
            dev_depth += 1
        elif re.match(r"^\s*#\s*pragma\s+omp\s+end\s+declare\s+target", t):
            dev_depth = max(0, dev_depth - 1)
            device = dev_depth > 0
    for mm in re.finditer(
            r"^[ \t]*(?:static\s+|inline\s+|extern\s+)*[A-Za-z_][\w \t\*]*?"
            r"\b([A-Za-z_]\w*)\s*\(([^;{)]*)\)\s*\{", code, re.M):
        name = mm.group(1)
        if name in ("if", "for", "while", "switch", "return"):
            continue
        params = [p for p in split_top(mm.group(2)) if p.strip() not in
                  ("void", "")]
        p = Proc(name, "function", len(params), file=path)
        # body: count locals (declarations at depth 1)
        start = mm.end()
        depth, k = 1, start
        while k < len(code) and depth:
            if code[k] == "{":
                depth += 1
            elif code[k] == "}":
                depth -= 1
            k += 1
        body = code[start:k]
        p.nlocals = len(re.findall(
            r"^\s*(?:const\s+)?(?:int|long|double|float|char|short|unsigned|"
            r"size_t|struct\s+\w+|[A-Za-z_]\w*_t)\b[^;(]*;", body, re.M))
        p.calls = set(re.findall(r"\b([A-Za-z_]\w*)\s*\(", body))
        fs.procs.append(p)
    # device functions by name in declare target lists / between begin/end
    text_dev = re.findall(r"#\s*pragma\s+omp\s+(?:begin\s+)?declare\s+"
                          r"target\b(.*?)#\s*pragma\s+omp\s+end\s+declare"
                          r"\s+target", code, re.S)
    devnames = set()
    for blk in text_dev:
        devnames |= set(re.findall(r"\b([A-Za-z_]\w*)\s*\([^;{)]*\)\s*[{;]",
                                   blk))
    for d in fs.directives:
        for c, mod, n, its in d.clauses:
            if c in ("declare_target", "to", "enter") or \
                    d.name.startswith("routine"):
                devnames |= {x.strip() for x in its}
    for p in fs.procs:
        if p.name in devnames:
            p.device = True
    fs.uses = set(re.findall(r'^\s*#\s*include\s*"([^"]+)"', text, re.M))
    return fs


def _c_loop_depth(btxt: str) -> int:
    depth = best = 0
    stack = []
    for tok in re.finditer(r"\bfor\s*\(|\{|\}", btxt):
        t = tok.group(0)
        if t.startswith("for"):
            depth += 1
            best = max(best, depth)
            stack.append("for")
        elif t == "{":
            stack.append("{")
        else:
            while stack and stack[-1] == "for":
                stack.pop()
                depth -= 1
            if stack:
                stack.pop()
            while stack and stack[-1] == "for":
                stack.pop()
                depth -= 1
    return best


# --- whole programs --------------------------------------------------------------------------

def scan(text: str, path: str, defines=None) -> FileScan | None:
    low = path.lower()
    if defines is not None:
        text = preprocess(text, defines)
    if low.endswith((".f90", ".f", ".f95", ".f03", ".f08", ".fpp", ".F90")):
        return scan_fortran(text, path)
    if low.endswith((".c", ".h", ".cc", ".cpp", ".cxx", ".hpp")):
        return scan_c(text, path)
    return None


def region_features(source: str, lang: str = "f90") -> list[set]:
    """The feature sets of every offload region of one program text
    (generated programs: offload.engine.fuzz_steer)."""
    fs = scan_fortran(source) if lang == "f90" else scan_c(source)
    return [r.features for r in fs.regions]


def _dist(values) -> dict:
    v = sorted(values)
    if not v:
        return {"n": 0, "max": 0, "p50": 0, "p90": 0, "p99": 0, "mean": 0}

    def q(p):
        return v[min(len(v) - 1, int(p * (len(v) - 1) + 0.5))]
    return {"n": len(v), "max": v[-1], "p50": q(0.5), "p90": q(0.9),
            "p99": q(0.99), "mean": round(sum(v) / len(v), 2)}


def type_depth(types: dict) -> dict:
    """name -> nesting depth (1: no derived-type components)."""
    memo: dict = {}

    def depth(n, seen=()):
        if n in memo:
            return memo[n]
        t = types.get(n)
        if t is None or n in seen:
            return 0
        d = 1 + max((depth(c, seen + (n,)) for c in t.children
                     if c in types), default=0)
        memo[n] = d
        return d
    return {n: depth(n) for n in types}


def extends_depth(types: dict) -> dict:
    out = {}
    for n in types:
        d, cur, seen = 0, n, set()
        while cur in types and types[cur].extends and cur not in seen:
            seen.add(cur)
            cur = types[cur].extends
            d += 1
        out[n] = d
    return out


def module_dag_depth(files: list[FileScan]) -> int:
    defined = {}
    for f in files:
        for m, info in f.modules.items():
            defined[m] = info["uses"]
    memo = {}

    def depth(m, seen=()):
        if m in memo:
            return memo[m]
        if m in seen:
            return 0
        d = 1 + max((depth(u, seen + (m,)) for u in defined.get(m, ())
                     if u in defined), default=0)
        memo[m] = d
        return d
    return max((depth(m) for m in defined), default=0)


def device_call_chains(files: list[FileScan]) -> tuple[int, int]:
    """(longest device call chain from an offload region through device
    routines, the most file crossings along such a chain)."""
    procs = {}
    for f in files:
        for p in f.procs:
            procs.setdefault(p.name.lower(), p)
    best_len = best_x = 0
    memo = {}

    def walk(name, fil, seen):
        key = (name, fil)
        if key in memo:
            return memo[key]
        p = procs.get(name)
        if p is None or name in seen:
            return (0, 0)
        bl = bx = 0
        for c in p.calls:
            c = c.lower()
            q = procs.get(c)
            if q is None or not (q.device or p.device):
                continue
            ln, x = walk(c, q.file, seen | {name})
            bl = max(bl, ln)
            bx = max(bx, x + (1 if q.file != p.file else 0))
        memo[key] = (bl + 1, bx)
        return memo[key]
    for f in files:
        for r in f.regions:
            for c in r.calls:
                q = procs.get(c.lower())
                if q is None:
                    continue
                ln, x = walk(c.lower(), q.file, frozenset())
                best_len = max(best_len, ln)
                best_x = max(best_x, x + (1 if q.file != f.path else 0))
    return best_len, best_x


def profile_files(files: list[FileScan]) -> dict:
    """Distributions and maxima of one code base."""
    dirs = [d for f in files for d in f.directives]
    regs = [r for f in files for r in f.regions]
    lists = defaultdict(list)
    for d in dirs:
        for c, mod, n, items in d.clauses:
            if c in LIST_CLAUSES or c.startswith("declare_"):
                lists[c].append(n)
    procs = [p for f in files for p in f.procs]
    dev = [p for p in procs if p.device]
    types = {}
    for f in files:
        types.update(f.types)
    tdepth = type_depth(types)
    edepth = extends_depth(types)
    mods = [m for f in files for m in f.modules.values()]
    clen = defaultdict(int)
    for d in dirs:
        clen[len(d.clauses)] += 1
    off_files = [f for f in files if f.directives]
    calls_len, calls_x = device_call_chains(files)
    mod_scalars, mod_dev = set(), set()
    for f in files:
        for m in f.modules.values():
            mod_scalars |= m.get("scalars", set())
            mod_dev |= m.get("device_names", set())
    reg_mod = [len(r.idents & mod_scalars) for r in regs]
    reg_mod_nodev = [len((r.idents & mod_scalars) - mod_dev) for r in regs]
    feat = Counter()
    pairs = Counter()
    for r in regs:
        fs = sorted(r.features)
        feat.update(fs)
        for i in range(len(fs)):
            for j in range(i + 1, len(fs)):
                pairs[f"{fs[i]} & {fs[j]}"] += 1
    return {
        "files": len(files),
        "offload_files": len(off_files),
        "lines": sum(f.lines for f in files),
        "directives": len(dirs),
        "regions": len(regs),
        "max_line_length": max((f.max_line for f in files), default=0),
        "directive_lines": _dist([d.lines for d in dirs]),
        "directive_chars": _dist([d.length for d in dirs]),
        "clauses_per_directive": _dist([len(d.clauses) for d in dirs]),
        "list_length": {c: _dist(v) for c, v in sorted(lists.items())},
        "region_loop_depth": _dist([r.loop_depth for r in regs]),
        "region_collapse": _dist([max(0, r.collapse) for r in regs]),
        "region_implicit_scalars": _dist([r.implicit_scalars for r in regs]),
        "region_module_scalars": _dist(reg_mod),
        "region_module_scalars_not_device": _dist(reg_mod_nodev),
        "region_scalars_total": _dist([r.implicit_scalars + m for r, m in
                                       zip(regs, reg_mod)]),
        "region_explicit_items": _dist([r.explicit_items for r in regs]),
        "region_statements": _dist([r.statements for r in regs]),
        "routine_args": _dist([p.nargs for p in procs]),
        "device_routine_args": _dist([p.nargs for p in dev]),
        "routine_locals": _dist([p.nlocals for p in procs]),
        "device_routine_locals": _dist([p.nlocals for p in dev]),
        "device_routines": len(dev),
        "optional_dummies": sum(p.optional for p in procs),
        "value_dummies": sum(p.value for p in procs),
        "class_dummies": sum(p.class_dummies for p in procs),
        "module_vars": _dist([m["vars"] for m in mods]),
        "module_device_vars": _dist([m["device_vars"] for m in mods]),
        "use_only_length": _dist([n for f in files for n in f.use_only]),
        "types": len(types),
        "type_components": _dist([t.components for t in types.values()]),
        "type_alloc_components": _dist([t.alloc for t in types.values()]),
        "type_pointer_components": _dist([t.pointer
                                          for t in types.values()]),
        "type_nesting_depth": _dist(list(tdepth.values())),
        "extends_depth": _dist(list(edepth.values())),
        "type_bound_procedures": sum(t.bindings for t in types.values()),
        "nopass_bindings": sum(t.nopass for t in types.values()),
        "generic_bindings": sum(t.generic for t in types.values()),
        "deferred_bindings": sum(t.deferred for t in types.values()),
        "abstract_types": sum(t.abstract for t in types.values()),
        "parameterized_types": sum(t.parameterized for t in types.values()),
        "select_type": sum(f.select_type for f in files),
        "submodules": sum(f.submodules for f in files),
        "interface_blocks": sum(f.interfaces for f in files),
        "bind_c": sum(f.bind_c for f in files),
        "module_dag_depth": module_dag_depth(files),
        "device_call_depth": calls_len,
        "device_call_file_crossings": calls_x,
        "max_statement_lines": max((f.max_stmt_lines for f in files),
                                   default=0),
        "region_features": dict(feat.most_common()),
        "region_pairs": dict(pairs.most_common(400)),
    }
