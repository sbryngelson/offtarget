"""Spec-equivalent rewrites of OpenMP Fortran programs.

Each ``Transform`` is a named rewrite with a stated precondition; ``apply``
returns the rewritten source or raises ``NotApplicable`` with the reason. By
the OpenMP 5.2 text a conforming implementation must give the rewritten
program the result of the original (used by ``offload.engine.expected``):
``if_false`` (``if(.false.)`` on data directives and ``if(target: .false.)``
on target constructs, so regions run on the host), ``split_combined`` (``target
X`` becomes ``target`` + ``X``, clauses distributed as 5.2 §17.2 prescribes),
``enter_exit_data`` (map clauses move to enter and exit data directives),
``num_teams_1``, ``num_teams_3``, ``thread_limit_32``, ``schedule_static_1``
and ``schedule_dynamic_3``. Preconditions come from ``offload.engine.expected``.
A rewrite that changes nothing is not applicable, and callers treat a variant
that fails the legality checks the same way. ``presence_probe`` is not a
rewrite: it adds self-checks of the device data environment."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from offload.engine import fsource as F
from offload.engine.grammar import GrammarError, parse_directive


class NotApplicable(Exception):
    """The transform's precondition does not hold (the reason)."""


@dataclass(frozen=True)
class Transform:
    name: str
    precondition: str
    fn: Callable[[str, int], str]

    def apply(self, source: str, version: int = 52) -> str:
        try:
            out = self.fn(source, version)
        except F.SourceError as e:
            raise NotApplicable(f"source not understood: {e}") from e
        if out == source:
            raise NotApplicable("nothing to rewrite")
        return out


def _wrap(indent: str, name: str, clauses: list[str],
          width: int = 96) -> list[str]:
    lines, cur, first = [], f"{indent}!$omp {name}", True
    for c in clauses:
        if len(cur) + 1 + len(c) > width and not first:
            lines.append(cur + " &")
            cur = f"{indent}!$omp& {c}"
        else:
            cur += " " + c
        first = False
    lines.append(cur)
    return lines


def _dirs(source: str, version: int) -> tuple[list[str], list[F.Dir]]:
    lines = source.splitlines()
    dirs = [F.parse_dir(s, version) for s in F.statements(source)
            if s.kind == "dir"]
    return lines, dirs


def _rebuild(lines: list[str], edits: list[tuple[int, int, list[str]]]
             ) -> str:
    """`lines` with each (first, last, replacement) applied (physical line
    ranges, non-overlapping)."""
    out, k = [], 0
    for first, last, new in sorted(edits, key=lambda e: e[0]):
        out += lines[k:first]
        out += new
        k = last + 1
    out += lines[k:]
    return "\n".join(out) + "\n"


def _parses(source: str, version: int) -> None:
    for s in F.statements(source):
        if s.kind == "dir":
            try:
                parse_directive("!$omp " + s.text, "fortran", version)
            except GrammarError as e:
                raise NotApplicable(f"rewritten directive does not parse: "
                                    f"{e}") from e


def _ends(source: str, version: int) -> dict[int, F.Stmt]:
    """Begin-directive first line -> the statement that closes the
    construct: its end directive, or the END DO of a loop construct
    written without one."""
    from offload.engine.expected import build_tree
    stmts = F.statements(source)
    start, end = F.main_program(stmts)
    out: dict[int, F.Stmt] = {}

    def walk(nodes):
        for n in nodes:
            if n.kind in ("dir", "loopdir") and n.end_stmt is not None:
                out[n.stmt.first] = n.end_stmt
            walk(n.children)
    walk(build_tree(stmts, start, end, version))
    return out


# --- if_false ----------------------------------------------------------------

_TARGET_DATA = ("target data", "target enter data", "target exit data",
                "target update")


def _once_per_instance(source: str, version: int) -> None:
    """NotApplicable when a write runs once per team or thread
    (offload.engine.expected.redundant_execution): a
    rewrite that changes the number of teams or threads changes such a
    program's result."""
    from offload.engine.expected import redundant_execution
    red = redundant_execution(source, version)
    if red:
        raise NotApplicable("code runs once per team or thread: "
                            + "; ".join(red))


def _if_false(source: str, version: int) -> str:
    from offload.engine.expected import copy_independent
    ap = copy_independent(source, version)
    if not ap.ok:
        raise NotApplicable("result depends on the device data "
                            f"environment: {ap.why}")
    # on the host a teams or parallel region has an implementation-
    # defined number of teams or threads too
    _once_per_instance(source, version)
    lines, dirs = _dirs(source, version)
    edits = []
    for d in dirs:
        if d.end or not d.base.startswith("target"):
            continue
        if d.clause("if"):
            raise NotApplicable(f"line {d.stmt.first + 1}: an if clause "
                                "is already there")
        add = "if(.false.)" if d.base in _TARGET_DATA else \
            "if(target: .false.)"
        edits.append((d.stmt.first, d.stmt.last,
                      _wrap(d.stmt.indent, d.base,
                            [c.text() for c in d.clauses] + [add])))
    out = _rebuild(lines, edits)
    _parses(out, version)
    return out


# --- split_combined ------------------------------------------------------------

TARGET_ONLY = {"map", "device", "defaultmap", "depend", "nowait",
               "in_reduction", "is_device_ptr", "has_device_addr",
               "uses_allocators"}


def _accepts(name: str, clause: str, version: int) -> bool:
    try:
        parse_directive(f"!$omp {name} {clause}", "fortran", version)
        return True
    except GrammarError:
        return False


def split_clauses(rest: str, clauses: list[F.RawClause], version: int
                  ) -> tuple[list[str], list[str]]:
    """(target clauses, clauses of `rest`) of `target <rest>` (5.2
    §17.2; module docstring)."""
    mapped = {n for c in clauses if c.name == "map"
              for n in (_name(x) for x in c.items()) if n}
    lastp = {n for c in clauses if c.name == "lastprivate"
             for n in (_name(x) for x in c.items()) if n}
    tgt, inner, implied = [], [], []
    for c in clauses:
        if c.name in TARGET_ONLY:
            tgt.append(c.text())
        elif c.name == "if":
            mods = c.modifiers()
            if mods == ["target"]:
                tgt.append(c.text())
            elif mods:
                inner.append(c.text())
            else:
                tgt.append(c.text())
                if _accepts(rest, c.text(), version):
                    inner.append(c.text())
        elif c.name == "firstprivate":
            items = c.items()
            t_items = [x for x in items if _name(x) not in mapped | lastp]
            if t_items:
                tgt.append(f"firstprivate({', '.join(t_items)})")
            if _accepts(rest, c.text(), version):
                inner.append(c.text())
        elif c.name == "thread_limit":
            tgt.append(c.text())
            if _accepts(rest, c.text(), version):
                inner.append(c.text())
        elif c.name in ("lastprivate", "reduction"):
            inner.append(c.text())
            for x in c.items():
                n = _name(x)
                if n and n not in mapped and n not in implied:
                    implied.append(n)
        else:
            inner.append(c.text())
    if implied:
        tgt.append(f"map(tofrom: {', '.join(implied)})")
    return tgt, inner


def _name(item: str) -> str | None:
    m = re.match(r"\s*([A-Za-z_]\w*)", item)
    return m.group(1).lower() if m else None


def _split_combined(source: str, version: int) -> str:
    lines, dirs = _dirs(source, version)
    ends = _ends(source, version)
    edits = []
    for d in dirs:
        if d.end or not d.base.startswith("target ") or \
                d.base in _TARGET_DATA:
            continue
        rest = d.base[len("target "):]
        end = ends.get(d.stmt.first)
        if end is None:
            raise NotApplicable(f"line {d.stmt.first + 1}: {d.base} has no "
                                "end directive")
        tgt, inner = split_clauses(rest, d.clauses, version)
        ind = d.stmt.indent
        edits.append((d.stmt.first, d.stmt.last,
                      _wrap(ind, "target", tgt) + _wrap(ind, rest, inner)))
        if end.kind == "dir":
            tail = end.text[len("end"):].strip()
            tail = re.sub(r"^target\s*", "", tail, flags=re.I)
            edits.append((end.first, end.last,
                          [f"{ind}!$omp end {tail}",
                           f"{ind}!$omp end target"]))
        else:       # END DO of a loop construct without end directive
            edits.append((end.first, end.last,
                          lines[end.first:end.last + 1] +
                          [f"{ind}!$omp end target"]))
    out = _rebuild(lines, edits)
    _parses(out, version)
    return out


# --- enter_exit_data ---------------------------------------------------------------

ENTER_TYPE = {"to": "to", "tofrom": "to", "from": "alloc", "alloc": "alloc",
              "storage": "alloc"}
EXIT_TYPE = {"to": "release", "tofrom": "from", "from": "from",
             "alloc": "release", "storage": "release"}


def _enter_exit_data(source: str, version: int) -> str:
    lines, dirs = _dirs(source, version)
    ends = _ends(source, version)
    edits = []
    for d in dirs:
        if d.end or "target" not in d.leaves or d.base in _TARGET_DATA:
            continue
        if not d.clause("map"):
            continue
        for bad in ("nowait", "if", "device", "depend"):
            if d.clause(bad):
                raise NotApplicable(f"line {d.stmt.first + 1}: {bad} "
                                    "clause")
        end = ends.get(d.stmt.first)
        if end is None:
            raise NotApplicable(f"line {d.stmt.first + 1}: no end "
                                "directive")
        enter, exit_ = [], []
        for c in d.clause("map"):
            mods = c.modifiers()
            if "present" in mods:
                raise NotApplicable("present modifier")
            if any(m.startswith(("iterator", "mapper")) for m in mods):
                raise NotApplicable("iterator or mapper modifier")
            typ = next((m for m in mods if m in ENTER_TYPE), "tofrom")
            items = ", ".join(c.items())
            enter.append(f"map({ENTER_TYPE[typ]}: {items})")
            exit_.append(f"map({EXIT_TYPE[typ]}: {items})")
        ind = d.stmt.indent
        edits.append((d.stmt.first, d.stmt.last,
                      _wrap(ind, "target enter data", enter) +
                      lines[d.stmt.first:d.stmt.last + 1]))
        edits.append((end.first, end.last,
                      lines[end.first:end.last + 1] +
                      _wrap(ind, "target exit data", exit_)))
    out = _rebuild(lines, edits)
    _parses(out, version)
    return out


# --- clause settings -------------------------------------------------------------

def _no_queries(source: str, version: int) -> None:
    from offload.engine.expected import _Analysis
    an = _Analysis(source, version)
    why, _, _ = an.static_exclusions()
    bad = [r for r in why if r.startswith(("runtime routine",
                                           "ran_on_host flag"))]
    if bad:
        raise NotApplicable("a runtime routine can reach the result: " +
                            "; ".join(bad))


def _set_clause(clause: str, value: str, leaf: str,
                skip: tuple = (), multiplicity: bool = False
                ) -> Callable[[str, int], str]:
    """`multiplicity`: the clause sets the number of teams or threads, so
    the program may not run code once per team or thread."""
    def fn(source: str, version: int) -> str:
        _no_queries(source, version)
        if multiplicity:
            _once_per_instance(source, version)
        lines, dirs = _dirs(source, version)
        edits = []
        for d in dirs:
            if d.end or leaf not in d.leaves:
                continue
            if any(d.clause(x) for x in skip):
                raise NotApplicable(f"line {d.stmt.first + 1}: "
                                    f"{', '.join(skip)} clause")
            cl = [c.text() for c in d.clauses if c.name != clause]
            cl.append(f"{clause}({value})")
            if not _accepts(d.base, f"{clause}({value})", version):
                continue
            edits.append((d.stmt.first, d.stmt.last,
                          _wrap(d.stmt.indent, d.base, cl)))
        out = _rebuild(lines, edits)
        _parses(out, version)
        return out
    return fn


TRANSFORMS: dict[str, Transform] = {t.name: t for t in (
    Transform("if_false", "the result does not depend on separate device "
              "copies (expected.copy_independent); no write runs once per "
              "team or thread; no if clause on a target directive",
              _if_false),
    Transform("split_combined", "every combined target construct has an end "
              "directive; the split directives parse", _split_combined),
    Transform("enter_exit_data", "no nowait, if, device or depend clause "
              "and no present, iterator or mapper modifier on a target "
              "construct with map clauses; an end directive",
              _enter_exit_data),
    Transform("num_teams_1", "no runtime routine reaches the result; no "
              "write runs once per team or thread",
              _set_clause("num_teams", "1", "teams", multiplicity=True)),
    Transform("num_teams_3", "no runtime routine reaches the result; no "
              "write runs once per team or thread",
              _set_clause("num_teams", "3", "teams", multiplicity=True)),
    Transform("thread_limit_32", "no runtime routine reaches the result; "
              "no write runs once per team or thread",
              _set_clause("thread_limit", "32", "teams", multiplicity=True)),
    Transform("schedule_static_1", "no runtime routine reaches the result; "
              "no ordered clause",
              _set_clause("schedule", "static, 1", "do", ("ordered",))),
    Transform("schedule_dynamic_3", "no runtime routine reaches the result; "
              "no ordered clause",
              _set_clause("schedule", "dynamic, 3", "do", ("ordered",))),
)}


def variants(source: str, version: int = 52, names=None
             ) -> dict[str, str | NotApplicable]:
    """The rewritten source (or the NotApplicable) of each transform."""
    out: dict = {}
    for name in names or TRANSFORMS:
        try:
            out[name] = TRANSFORMS[name].apply(source, version)
        except NotApplicable as e:
            out[name] = e
    return out


# --- the presence probe ------------------------------------------------------------

PROBE_LINE = re.compile(r"^PROBE presence=(pass|fail)\s*$", re.M)


def presence_probe(source: str, version: int = 52) -> str:
    """`source` with self-checks of the device data environment: a
    calibration (an array mapped by enter data must be present, absent
    after exit data with delete) and, at each host point around a data or
    target construct, ``omp_target_is_present`` of every mapped variable
    against the presence the reference-count rules fix
    (``offload.engine.expected.presence_snapshots``). Points between a nowait
    construct and the next taskwait are skipped. The program prints
    ``PROBE presence=pass|fail`` before its RESULT line and before each
    construct with a present modifier (so an error termination still shows
    the state before it)."""
    from offload.engine.expected import presence_snapshots
    snaps = presence_snapshots(source, version)
    stmts = F.statements(source)
    lines = source.splitlines()
    decls = F.declarations(stmts)
    start, end = F.main_program(stmts)
    # pending deferred target tasks: lines after a nowait construct up to
    # the next taskwait
    pending, busy = [], False
    present_at = []
    for s in stmts:
        if s.kind != "dir":
            continue
        d = F.parse_dir(s, version)
        if busy and (d.base == "taskwait" or d.base == "barrier"):
            pending[-1][1] = s.first
            busy = False
        if not d.end and d.clause("nowait") and "target" in d.leaves[0]:
            if not busy:
                pending.append([s.first, 10 ** 9])
                busy = True
        if not d.end and any("present" in c.modifiers()
                             for c in d.clause("map")):
            present_at.append(s.first)

    def is_pending(line: int) -> bool:
        return any(a <= line <= b for a, b in pending)

    ins_before: dict[int, list[str]] = {}
    ins_after: dict[int, list[str]] = {}
    probed: set[str] = set()
    for where, line, state in snaps:
        if is_pending(line) or (where == "before" and is_pending(line - 1)):
            continue
        ind = lines[line][:len(lines[line]) - len(lines[line].lstrip())]
        chk = []
        for v, pres in sorted(state.items()):
            if v not in decls or decls[v].parameter:
                continue
            probed.add(v)
            op = "==" if pres else "/="
            chk.append(f"{ind}if (omp_target_is_present(c_loc({v}), "
                       f"omp_get_default_device()) {op} 0) probe_ok = "
                       ".false.")
        (ins_before if where == "before" else ins_after).setdefault(
            line, []).extend(chk)
    for line in present_at:
        ind = lines[line][:len(lines[line]) - len(lines[line].lstrip())]
        ins_before.setdefault(line, []).append(
            f"{ind}print '(a,a)', 'PROBE presence=', "
            "merge('pass', 'fail', probe_ok)")
    result = max((s.first for s in stmts[start:end]
                  if s.kind == "code" and "RESULT" in s.text), default=None)
    if result is None:
        raise NotApplicable("no RESULT print")
    ind = lines[result][:len(lines[result]) - len(lines[result].lstrip())]
    ins_before.setdefault(result, []).append(
        f"{ind}print '(a,a)', 'PROBE presence=', "
        "merge('pass', 'fail', probe_ok)")
    # target attribute on the declarations of probed variables
    edits = {}
    for s in stmts[:start]:
        if s.kind != "code" or not F._TYPE.match(s.text):
            continue
        _, ents = F._decl_entities(F._TYPE.match(s.text).group(2))
        if not {n for n, _ in ents} & probed:
            continue
        if s.first != s.last:
            raise NotApplicable(f"line {s.first + 1}: continued declaration")
        if re.search(r"\btarget\b", s.lower) or \
                re.search(r"\bparameter\b", s.lower):
            continue
        txt = lines[s.first]
        m = re.match(r"(\s*)(integer|logical)(\s*\([^)]*\))?(.*)$", txt,
                     re.I)
        if not m:
            raise NotApplicable(f"line {s.first + 1}: declaration form")
        rest = m.group(4)
        if "::" in rest:
            attrs, ents_txt = rest.split("::", 1)
            new = f"{m.group(1)}{m.group(2)}{m.group(3) or ''}" \
                f"{attrs.rstrip()}, target ::{ents_txt}"
        else:
            new = f"{m.group(1)}{m.group(2)}{m.group(3) or ''}, target ::" \
                f"{rest}"
        edits[s.first] = new
    prog = next(i for i, s in enumerate(stmts)
                if s.kind == "code" and re.match(r"program\s+\w+", s.lower))
    first_exec = stmts[start].first
    fi = re.match(r"\s*", lines[first_exec]).group()
    out = []
    for k, ln in enumerate(lines):
        if k == first_exec:
            # the probe's declarations end the specification part; the
            # calibration starts the execution part
            out += [f"{fi}logical :: probe_ok",
                    f"{fi}integer, target :: probe_cal(4)",
                    f"{fi}probe_ok = .true.",
                    f"{fi}!$omp target enter data map(to: probe_cal)",
                    f"{fi}if (omp_target_is_present(c_loc(probe_cal), "
                    "omp_get_default_device()) == 0) probe_ok = .false.",
                    f"{fi}!$omp target exit data map(delete: probe_cal)",
                    f"{fi}if (omp_target_is_present(c_loc(probe_cal), "
                    "omp_get_default_device()) /= 0) probe_ok = .false."]
        if k in ins_before:
            out += ins_before[k]
        out.append(edits.get(k, ln))
        if k == stmts[prog].first:
            out += ["  use omp_lib, only: omp_target_is_present, "
                    "omp_get_default_device",
                    "  use, intrinsic :: iso_c_binding, only: c_loc"]
        if k in ins_after:
            out += ins_after[k]
    return "\n".join(out) + "\n"
