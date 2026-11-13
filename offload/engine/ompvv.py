"""Reading omp_vv tests as text (the corpus is untrusted data).

- ``directive_lines`` / ``atoms_of``: the catalog atoms a test's directive
  lines use (for tools/derive/ompvv_compare.py and the support table's suite
  column). C sources (``is_c``) are read from ``#pragma omp`` lines.
- ``copy_semantics``: whether a test's result depends on host and device
  copies being separate, so that it can pass only in copy mode (HSA_XNACK=0).
  Two shapes are detected: a device write to a ``to`` or ``alloc`` mapped
  variable that nothing copies back, and a host write to an already mapped
  variable with no ``target update to``. C sources are turned into the same
  statement stream (``_c_statements``) so one detector serves both. The check
  is textual and errs towards flagging; it picks the mode a verdict is read
  in and never judges the test.
- ``suite_verdicts``: per atom and toolchain, how many narrow suite tests pass
  and fail, each read in its mode (HSA_XNACK=1, or 0 for a copy-semantics test).
"""
from __future__ import annotations

import collections
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CORPUS = ROOT / "corpus"

# Corpus/omp_vv is a clone of the active upstream suite at this
# commit (docs/tooling/setup.md; tools/regenerate.py --check ompvv-corpus); the
# archived SOLLVE/sollve_vv d978684 it replaced is in results/archive/
# ompvv-sollve-d978684/ (the old baselines) and data/reports/
# ompvv-upstream-rerun.md (what changed)
UPSTREAM = {"repo": "OpenMP-Validation-and-Verification/OpenMP_VV",
            "url": "https://github.com/OpenMP-Validation-and-Verification/"
                   "OpenMP_VV.git",
            "commit": "f7d95b342b9330ecac735ed31b9fb193d8f60a9b",
            "date": "2026-09-17"}
OLD_CORPUS = {"repo": "SOLLVE/sollve_vv", "commit": "d978684"}

HEADLINE_XNACK = 1
COPY_XNACK = 0


def is_c(text: str) -> bool:
    return bool(re.search(r"^\s*#\s*pragma\s+omp\b", text, re.M))


def _c_directive_lines(text):
    """#pragma omp lines, backslash continuations joined, comments
    dropped."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    out, cur = [], None
    for raw in text.splitlines():
        s = re.sub(r"//.*$", "", raw).rstrip()
        if cur is not None:
            cur += " " + s.strip().rstrip("\\").strip()
            if not s.endswith("\\"):
                out.append(cur)
                cur = None
            continue
        m = re.match(r"\s*#\s*pragma\s+omp\s+(.*)$", s)
        if not m:
            continue
        body = m.group(1)
        if body.endswith("\\"):
            cur = body.rstrip("\\").strip()
        else:
            out.append(body.strip())
    return out


def directive_lines(text):
    """Free-form !$omp lines, `&` continuations joined (C, #pragma
    omp lines)."""
    if is_c(text):
        return _c_directive_lines(text)
    out, cur = [], None
    for raw in text.splitlines():
        s = raw.strip()
        if cur is not None:
            cur += " " + re.sub(r"^!\$omp\s*&?", "", s, flags=re.I).strip()
            if not cur.endswith("&"):
                out.append(cur)
                cur = None
            else:
                cur = cur[:-1].rstrip()
            continue
        m = re.match(r"!\$omp\s+(.*)$", s, re.I)
        if not m:
            continue
        body = re.sub(r"\s*!.*$", "", m.group(1))
        if body.endswith("&"):
            cur = body[:-1].rstrip()
        else:
            out.append(body)
    return out


def clause_items(rest):
    """[(clause name, text inside its parentheses)] of a directive remainder."""
    out, i = [], 0
    for m in re.finditer(r"\b([a-z_]+)\b", rest):
        if m.start() < i:
            continue
        j = m.end()
        arg = ""
        k = j
        while k < len(rest) and rest[k] == " ":
            k += 1
        if k < len(rest) and rest[k] == "(":
            depth, e = 0, k
            while e < len(rest):
                depth += rest[e] == "("
                depth -= rest[e] == ")"
                e += 1
                if depth == 0:
                    break
            arg = rest[k + 1:e - 1]
            i = e
        out.append((m.group(1), arg))
    return out


def atoms_of(text, directives, clauses, all_atoms):
    """(directive atoms, clause atoms incl. modifiers) used by one source."""
    dirs, cls = set(), set()
    for line in directive_lines(text):
        low = line.lower()
        if low.startswith("end "):
            continue
        words = re.findall(r"[a-z_]+", low.split("(")[0])
        name = ""
        for n in range(len(words), 0, -1):
            cand = "_".join(words[:n])
            if cand in directives:
                name = cand
                break
        if name:
            dirs.add(name)
        rest = low[len(name.replace("_", " ")):] if name else low
        for c, arg in clause_items(rest):
            if c not in clauses:
                continue
            cls.add("omp.clause." + c)
            for tok in re.findall(r"[a-z_]+", arg):
                a = "omp.clause.%s.%s" % (c, tok)
                if a in all_atoms:
                    cls.add(a)
    return dirs, cls


# --- copy semantics ------------------------------------------------------------------

def _c_units(text: str) -> list[tuple]:
    """("dir", text) for a pragma, ("tok", text) for the other tokens of a
    C source (comments, strings and other preprocessor lines dropped)."""
    text = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group()),
                  text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'', '0',
                  text)
    out = []
    lines = text.split("\n")
    k = 0
    while k < len(lines):
        s = lines[k]
        if s.lstrip().startswith("#"):
            group = [s]
            while group[-1].rstrip().endswith("\\") and k + 1 < len(lines):
                k += 1
                group.append(lines[k])
            k += 1
            m = re.match(r"\s*#\s*pragma\s+omp\s+(.*)$", " ".join(
                g.rstrip().rstrip("\\") for g in group))
            if m:
                out.append(("dir", " ".join(m.group(1).split())))
            continue
        for t in re.findall(r"[A-Za-z_]\w*|\d[\w.]*|->|\+\+|--|[-+*/%&|^]="
                            r"|==|!=|<=|>=|&&|\|\||\S", s):
            out.append(("tok", t))
        k += 1
    return out


def _c_statement(toks: list[str]) -> str:
    """A C statement as the Fortran-like text the detector reads."""
    s = " ".join(toks)
    s = re.sub(r"\s*->\s*|\s*\.\s*(?=[A-Za-z_])", "%", s)
    s = s.replace("[", "(").replace("]", ")")
    m = re.match(r"^(.*?)\s*([-+*/%&|^])=\s*(.*)$", s)
    if m and "==" not in s[:m.start(2) + 1]:
        s = f"{m.group(1)} = {m.group(1)} {m.group(2)} {m.group(3)}"
    m = re.match(r"^(?:\+\+|--)\s*(.*)$|^(.*?)\s*(?:\+\+|--)$", s)
    if m:
        v = m.group(1) or m.group(2)
        s = f"{v} = {v} + 1"
    return s.lower()


_C_BLOCK_KEYS = ("target", "target data")


def _c_statements(text: str) -> list[tuple]:
    """The (is_directive, text) stream of a C source for copy_semantics
    (see the module docstring)."""
    units = _c_units(text)
    out: list[tuple] = []
    pos = [0]

    def peek():
        return units[pos[0]] if pos[0] < len(units) else (None, None)

    def take():
        u = peek()
        pos[0] += 1
        return u

    def balanced(open_, close):
        depth, toks = 0, []
        while True:
            k, t = take()
            if k is None:
                return toks
            if t == open_:
                depth += 1
            elif t == close:
                depth -= 1
            toks.append(t)
            if depth == 0:
                return toks

    def statement():
        k, t = peek()
        if k is None:
            return
        if k == "dir":
            take()
            low = t.lower()
            out.append((True, low))
            if low.startswith("target data") or (
                    _COMPUTE.match(low) and not low.startswith(
                        ("target update", "target enter", "target exit"))):
                statement()
                out.append((True, "end target data"
                            if low.startswith("target data") else
                            "end target"))
            return
        if t == "{":
            take()
            while peek()[0] is not None and peek()[1] != "}":
                statement()
            take()
            return
        if t in ("for", "while", "switch", "if"):
            take()
            hdr = balanced("(", ")")
            if t == "for":
                parts = " ".join(hdr[1:-1]).split(";")
                if parts and parts[0].strip():
                    out.append((False, _c_statement(parts[0].split())))
            statement()
            if t == "if" and peek()[1] == "else":
                take()
                statement()
            return
        if t == "do":
            take()
            statement()
            take()  # while
            balanced("(", ")")
            if peek()[1] == ";":
                take()
            return
        toks = []
        depth = 0
        while True:
            k, t = take()
            if k is None or k == "dir":
                if k == "dir":
                    pos[0] -= 1
                break
            if t in "({[":
                depth += 1
            elif t in ")}]":
                depth -= 1
            if t == ";" and depth <= 0:
                break
            if t == "{" and depth == 1 and toks and toks[-1] == ")":
                # a function body: read it as a compound statement
                pos[0] -= 1
                depth = 0
                statement()
                return
            toks.append(t)
        if toks:
            out.append((False, _c_statement(toks)))

    guard = 0
    while peek()[0] is not None and guard < 100000:
        statement()
        guard += 1
    return out


def _statements(text):
    """(is_directive, lowercase text) per statement, `&` continuations
    joined, comments and preprocessor lines dropped (C: _c_statements)."""
    if is_c(text):
        return _c_statements(text)
    out, cur, cur_dir = [], None, False
    for raw in text.splitlines():
        s = raw.strip()
        if s.startswith("#"):
            continue
        is_dir = bool(re.match(r"!\$omp\b", s, re.I))
        if is_dir:
            s = re.sub(r"^!\$omp\s*&?", "", s, flags=re.I)
        elif s.startswith("!"):
            continue
        s = re.sub(r"\s*!.*$", "", s) if not is_dir else \
            re.sub(r"\s+!.*$", "", s)
        if cur is not None:
            s = s.lstrip("&").strip()
            cur += " " + s
        else:
            cur, cur_dir = s, is_dir
        if cur.endswith("&"):
            cur = cur[:-1].rstrip()
            continue
        if cur:
            out.append((cur_dir, cur.lower()))
        cur = None
    return out


def _base(item: str) -> str:
    """The variable designator of a list item without subscripts:
    ``a(1:s)`` -> ``a``, ``t%arr(i)`` -> ``t%arr`` (C: ``a[0:n]`` -> ``a``,
    ``s.v`` / ``p->v`` -> ``s%v``)."""
    item = re.sub(r"\s*->\s*|\s*\.\s*(?=[A-Za-z_])", "%", item)
    item = item.replace("[", "(").replace("]", ")")
    depth, out = 0, []
    for ch in item:
        depth += ch == "("
        if depth == 0:
            out.append(ch)
        depth -= ch == ")"
    return re.sub(r"\s+", "", "".join(out))


def _split_top(text: str) -> list[str]:
    parts, depth, cur = [], 0, []
    for ch in text:
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]


def _top_colon(arg: str) -> tuple[str, str]:
    """(modifiers, list) of a clause argument split at its first colon
    outside parentheses; ("", arg) without one."""
    depth = 0
    for i, ch in enumerate(arg):
        depth += ch == "("
        depth -= ch == ")"
        if ch == ":" and depth == 0:
            return arg[:i], arg[i + 1:]
    return "", arg


def _maps(directive: str) -> dict[str, set[str]]:
    """map type -> variable bases, of the map clauses of one directive (a
    map without a type is tofrom); also 'update_to' / 'update_from' for
    the motion clauses of target update."""
    out: dict[str, set[str]] = collections.defaultdict(set)
    for name, arg in clause_items(directive):
        if name == "map":
            head, items = _top_colon(arg)
            words = re.findall(r"[a-z_]+", re.sub(r"\(.*?\)", "", head))
            mtype = next((w for w in words if w in (
                "to", "from", "tofrom", "alloc", "release", "delete")),
                "tofrom")
            out[mtype] |= {_base(i) for i in _split_top(items)}
        elif name in ("to", "from") and directive.startswith("target update"):
            items = _top_colon(arg)[1]
            out["update_" + name] |= {_base(i) for i in _split_top(items)}
    return out


def _defaultmap_to(directive: str) -> bool:
    return any(n == "defaultmap" and re.match(r"\s*to\b", a)
               for n, a in clause_items(directive))


_LHS = re.compile(r"^([a-z_][\w%]*(?:\s*\([^=]*\))?(?:\s*%\s*[\w]+"
                  r"(?:\s*\([^=]*\))?)*)\s*=(?!=)")


def _assigned(stmt: str) -> str | None:
    """The variable base a Fortran assignment statement assigns, or None."""
    s = re.sub(r"^\d+\s+", "", stmt)
    s = re.sub(r"^if\s*\(.*?\)\s*(?=[a-z_][\w%]*\s*(\(|=|%))", "", s)
    m = _LHS.match(s)   # `do i = 1, n`, declarations, `if (a == b)` do not match
    return _base(m.group(1)) if m else None


def _covers(mapped: str, var: str) -> bool:
    return (var == mapped or var.startswith(mapped + "%")
            or mapped.startswith(var + "%"))


_UNIT = re.compile(r"(?:[a-z]+(?:\s*\([^)]*\))?\s+)*"
                   r"(?:function|subroutine|program)\s+\w+")
_COMPUTE = re.compile(r"target\b(?!\s+(data|enter|exit|update)\b)")
_LOOP_WORDS = {"do", "simd", "loop", "distribute"}


def copy_semantics(text: str) -> list[str]:
    """Why a test's result depends on copy semantics (see the module
    docstring); [] when it does not."""
    stmts = _statements(text)
    c_src = is_c(text)
    update_from, update_to, exit_from = set(), set(), set()
    for is_dir, s in stmts:
        if is_dir:
            m = _maps(s)
            update_from |= m.get("update_from", set())
            update_to |= m.get("update_to", set())
            if s.startswith("target exit data"):
                exit_from |= m.get("from", set()) | m.get("tofrom", set())
    back = update_from | exit_from

    setdev = any(not d and re.match(r"call\s+omp_set_default_device\b", st)
                 for d, st in stmts)
    cands: list[tuple[int, str, str]] = []   # (index, kind, var)
    on_device: list[bool] = []   # per statement: inside a compute region
    # stack of (kind, to_or_alloc vars, all mapped vars, defaultmap_to,
    #           end condition) ; kind: data | compute
    stack: list[dict] = []
    entered: set[str] = set()      # target enter data: still mapped
    entered_to: set[str] = set()
    do_depth = 0
    for idx, (is_dir, s) in enumerate(stmts):
        on_device.append(any(r["kind"] == "compute" for r in stack))
        if is_dir:
            if s.startswith("end "):
                body = s[4:].strip()
                if body.startswith("target") and stack:
                    # close the innermost region of this kind
                    kind = "data" if re.match(r"target\s+data\b", body) \
                        else "compute"
                    for k in range(len(stack) - 1, -1, -1):
                        if stack[k]["kind"] == kind and \
                                stack[k]["end"] == "end":
                            del stack[k:]
                            break
                continue
            m = _maps(s)
            if s.startswith("target enter data"):
                entered |= set().union(*m.values()) if m else set()
                entered_to |= m.get("to", set()) | m.get("alloc", set())
                continue
            if s.startswith("target exit data"):
                gone = set().union(*m.values()) if m else set()
                entered -= gone
                entered_to -= gone
                continue
            if s.startswith("target update"):
                continue
            if s.startswith("target data"):
                stack.append({"kind": "data", "words": s.split(),
                              "to": m.get("to", set()) | m.get("alloc",
                                                               set()),
                              "all": set().union(*m.values()) if m
                              else set(),
                              "dm": False, "end": "end"})
                continue
            if _COMPUTE.match(s):
                words = set(re.findall(r"[a-z_]+", s.split("(")[0]))
                # C: every region is closed by a synthesized end target
                loop = bool(words & _LOOP_WORDS) and not c_src
                stack.append({"kind": "compute", "words": s.split(),
                              "to": m.get("to", set()) | m.get("alloc",
                                                               set()),
                              "all": set().union(*m.values()) if m
                              else set(),
                              "dm": _defaultmap_to(s),
                              "end": "loop" if loop else "end",
                              "depth": do_depth,
                              "multi": do_depth > 0 and (setdev or any(
                                  n == "device" for n, _ in
                                  clause_items(s)))})
            continue
        # a Fortran statement
        if re.match(r"do\b", s) and not re.match(r"do\s*=", s):
            do_depth += 1
        elif re.match(r"end\s*do\b", s):
            do_depth -= 1
            while stack and stack[-1]["end"] == "loop" and \
                    do_depth <= stack[-1]["depth"]:
                stack.pop()
        on_device[idx] = any(r["kind"] == "compute" for r in stack)
        var = _assigned(s)
        if var is None:
            continue
        inside = [r for r in stack if r["kind"] == "compute"]
        if inside:
            top = inside[-1]
            explicit = set().union(*(r["all"] for r in inside))
            # the outermost mapping of var decides whether it comes back
            # at the end (an inner map(alloc) of a tofrom-mapped array
            # does not stop the copy back)
            outer = [(r["to"], r["all"]) for r in stack]
            if any(_covers(v, var) for v in entered):
                outer.insert(0, (entered_to, entered))
            first = next((to for to, al in outer
                          if any(_covers(v, var) for v in al)), None)
            hit = None
            if first is not None:
                hit = next((v for v in first if _covers(v, var)), None)
            elif top["dm"] and not any(_covers(v, var) for v in explicit):
                hit = var
            if hit is not None and not any(_covers(b, var) for b in back):
                cands.append((idx, "device", var))
            # one host variable, a copy per device: a target region in a
            # loop that picks the device (device(...) clause, or a file that
            # calls omp_set_default_device) writes data an enter data or
            # target data mapped
            outer_all = set().union(*(r["all"] for r in stack
                                      if r["kind"] == "data")) | entered
            if top.get("multi") and any(_covers(v, var) for v in outer_all):
                cands.append((idx, "multi", var))
        else:
            mapped = set().union(*(r["all"] for r in stack)) | entered
            hit = next((v for v in mapped if _covers(v, var)), None)
            if hit is not None and not any(_covers(u, var)
                                           for u in update_to):
                cands.append((idx, "host", var))
    unit, units = 0, []
    for is_dir, st in stmts:
        if not is_dir and _UNIT.match(st):
            unit += 1
        units.append(unit)

    def local(var: str, u: int) -> bool:
        name = re.escape(var.split("%")[0])
        return any(units[j] == u and "::" in st and re.search(
            rf"::.*(?<![\w%]){name}\b", st)
            for j, (d, st) in enumerate(stmts) if not d)

    why = []
    for idx, kind, var in cands:
        loc = local(var, units[idx])
        rx = re.compile(r"(?<![\w%])" + re.escape(var).replace("%", r"\s*%\s*")
                        + r"\b")
        for j in range(len(stmts)):
            # later in the same procedure, or anywhere for a variable
            # the procedure does not declare (module or host associated)
            if j == idx or (units[j] == units[idx] and j < idx) or (
                    units[j] != units[idx] and loc):
                continue
            is_dir, s = stmts[j]
            if kind == "multi":   # the per-device copies are the point
                why.append(f"a device-selecting loop writes {var}, which "
                           "is mapped on several devices: one copy per "
                           "device only without zero-copy")
                break
            if is_dir or on_device[j] != (kind == "host"):
                continue
            if _assigned(s) == var and not rx.search(s.split("=", 1)[1]):
                continue   # overwritten, not read
            if rx.search(s):
                why.append(
                    f"device writes {var} (mapped to/alloc, no copy back); "
                    "the host reads it" if kind == "device" else
                    f"host writes {var} while it is mapped (no update to); "
                    "a target region reads it")
                break
    return list(dict.fromkeys(why))


# --- suite verdicts ------------------------------------------------------------------

def verdict_mode(text: str) -> int:
    """The HSA_XNACK value a suite test's verdict is read in."""
    return COPY_XNACK if copy_semantics(text) else HEADLINE_XNACK


def suite_verdicts(baseline: list[dict], atoms: set[str],
                   corpus_root: Path = CORPUS) -> dict[tuple, list[int]]:
    """(atom, toolchain) -> [narrow passes, narrow fails], each omp_vv test
    read at its mode (``test_mode``); a test without a row in its mode is
    left out. "Narrow" = at most one base clause of the slice."""
    dir_names = {a[len("omp.directive."):] for a in atoms
                 if a.startswith("omp.directive.") and a.count(".") == 2}
    cl_names = {a[len("omp.clause."):] for a in atoms
                if a.startswith("omp.clause.") and a.count(".") == 2}
    status: dict[tuple, str] = {}
    for b in baseline:
        if b.get("repo") != "omp_vv" or b["status"] == "harness_error":
            continue
        status[(b["path"], b["toolchain"], int(b["xnack"]))] = b["status"]
    out: dict[tuple, list[int]] = collections.defaultdict(lambda: [0, 0])
    for path in sorted({p for p, _, _ in status}):
        f = Path(corpus_root) / "omp_vv" / path
        if not f.is_file():
            continue
        text = f.read_text(errors="replace")
        dirs, cls = atoms_of(text, dir_names, cl_names, atoms)
        if len({c for c in cls if c.count(".") == 2}) > 1:
            continue
        mode = verdict_mode(text)
        tags = [f"omp.directive.{d}" for d in dirs] + sorted(cls)
        for tc in {t for p, t, _ in status if p == path}:
            st = status.get((path, tc, mode))
            if st is None:
                continue
            for atom in tags:
                out[(atom, tc)][0 if st == "pass" else 1] += 1
    return dict(out)
