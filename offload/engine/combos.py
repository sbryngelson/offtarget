"""Directive combination matrix.

For every ordering of two or three distinct leaf directives of ``LEAVES``
(target, teams, distribute, parallel, do, simd, loop, and at 6.0
workdistribute) this module builds two small free-form programs: ``combined``,
one compound directive naming the leaves in that order (``!$omp teams target``),
and ``nested``, the leaves as separate constructs, each inside the previous.

Each is classified by the spec, independently of ``offload.engine.rules``.
``spec_combined`` says whether the name is a conforming compound directive
(5.2: section 17.3; 6.0: the Appendix D grammar). ``spec_nested`` says whether
the nesting conforms, from the ``DIRECT`` table and the region-wide rules.
``ours`` is the catalog's answer (the grammar parses every directive and
``offload.engine.rules.violations`` is empty). ``flang`` (tools/
combination_matrix.py) is AFAR amdflang's check of the same program.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations

from offload.engine.grammar import GrammarError
from offload.engine.rules import ProgramError, parse_program, violations

BASE = ("target", "teams", "distribute", "parallel", "do", "simd", "loop")
LEAVES = {52: BASE, 60: BASE + ("workdistribute",)}
LOOP_LEAVES = {"distribute", "do", "simd", "loop"}
SIZES = (2, 3)


def orders(version: int, sizes=SIZES) -> list[tuple[str, ...]]:
    return [p for k in sizes for p in permutations(LEAVES[version], k)]


# --- programs ----------------------------------------------------------------------

_HEAD = ["program p", "  implicit none", "  integer, parameter :: n = 8",
         "  integer :: i, j, k", "  real :: a(n), b(n)", "  a = 1.0",
         "  b = 0.0"]
_TAIL = ["  print *, b(1)", "end program p"]


def combined_source(seq: tuple) -> str:
    name = " ".join(seq)
    if set(seq) & LOOP_LEAVES:
        body = ["do i = 1, n", "  b(i) = a(i)", "end do"]
    elif "workdistribute" in seq:
        body = ["b = a"]
    else:
        body = ["b(1) = a(1)"]
    lines = [f"!$omp {name}"] + body + [f"!$omp end {name}"]
    return "\n".join(_HEAD + ["  " + x for x in lines] + _TAIL) + "\n"


def _nest(seq: tuple, loops: int) -> list[str]:
    var = "ijk"[loops - 1] if loops else None
    if not seq:
        return [f"b({var}) = a({var})" if var else "b(1) = a(1)"]
    leaf, rest = seq[0], seq[1:]
    if leaf in LOOP_LEAVES:
        v = "ijk"[loops]
        inner = _nest(rest, loops + 1)
        return [f"!$omp {leaf}", f"do {v} = 1, n"] + ["  " + x for x in inner] \
            + ["end do", f"!$omp end {leaf}"]
    inner = _nest(rest, loops) if rest or leaf != "workdistribute" \
        else ["b = a"]
    return [f"!$omp {leaf}"] + ["  " + x for x in inner] + [f"!$omp end {leaf}"]


def nested_source(seq: tuple) -> str:
    return "\n".join(_HEAD + ["  " + x for x in _nest(seq, 0)] + _TAIL) + "\n"


def source(seq: tuple, form: str) -> str:
    return combined_source(seq) if form == "combined" else nested_source(seq)


def ours(seq: tuple, form: str, version: int) -> tuple[bool, str]:
    """(accepted, why not): the grammar parses every directive and no
    static rule is violated."""
    try:
        found = violations(parse_program(source(seq, form), version), version)
    except (GrammarError, ProgramError) as err:
        return False, str(err).split("\n")[0]
    return not found, ", ".join(found)


# --- the spec, independently of offload.engine.rules -------------------------------------

# the constructs that may be the closest enclosing construct of another
# (lexically, nothing in between): 5.2 §17.1, §10.2, §10.4, §11.6, §11.7,
# §13.8 and §17.1's worksharing rule; 6.0 §12.2 (teams-nestable), §12.3,
# §12.4 (SIMDizable), §13 (a worksharing region encountered by all
# threads of its team, Appendix C), §13.5, §13.7, §15.8
DIRECT = {
    "target": {"teams", "parallel", "do", "simd", "loop"},
    "teams": {"distribute", "parallel", "loop"},
    "distribute": {"target", "parallel", "do", "simd", "loop"},
    "parallel": {"target", "parallel", "do", "simd", "loop"},
    "do": {"target", "parallel", "simd", "loop"},
    "simd": {"simd", "loop"},
    "loop": {"parallel", "simd", "loop"},
    "workdistribute": set(),
}
# outermost construct of a main program (the implicit parallel region)
TOP = {"target", "teams", "parallel", "do", "simd"}


def spec_nested(seq: tuple, version: int) -> bool:
    if seq[0] not in TOP:
        return False  # distribute/workdistribute need teams; loop needs bind
    for k in range(1, len(seq)):
        parent, child = seq[k - 1], seq[k]
        ok = DIRECT[parent] | ({"workdistribute"} if parent == "teams"
                               and version >= 60 else set())
        if child not in ok:
            return False
        for anc in seq[:k]:
            if anc == "simd" and child not in ("simd", "loop"):
                return False
            if anc == "workdistribute":
                return False
            if anc == "target" and child == "target":
                return False
            if anc == "loop" and version < 60 and child not in (
                    "loop", "parallel", "simd"):
                return False
    return True


def _name_52(seq: tuple) -> bool:
    """5.2 §17.3, restricted to LEAVES."""
    if len(seq) == 1:
        return True
    a, b = seq[0], seq[1:]
    if not _name_52(b):
        return False
    if a == "do":
        return b == ("simd",)
    if a == "parallel":
        return b in (("loop",), ("do",), ("do", "simd"))
    if a == "distribute":
        return b == ("simd",) or (b[0] == "parallel" and "do" in b)
    if a == "teams":
        return b in (("loop",), ("distribute",)) or b[0] == "distribute"
    if a == "target":
        return b in (("simd",), ("parallel",), ("teams",)) \
            or b[0] == "teams" \
            or (b[0] == "parallel" and bool({"loop", "do"} & set(b)))
    return False


# 6.0 Appendix D productions restricted to LEAVES (task, taskloop, masked,
# single, sections, workshare, target_data and the data-motion directives
# are outside the matrix)
def _composite(s):
    return s in (("distribute", "parallel", "do"),
                 ("distribute", "parallel", "do", "simd"),
                 ("distribute", "simd"), ("do", "simd"))


def _parallel_dir(s):
    return s == ("parallel",) or _par_comb(s)


def _teams_dir(s):
    return s == ("teams",) or _teams_comb(s)


def _target_dir(s):
    return s == ("target",) or _target_comb(s)


def _par_comb(s):
    if len(s) < 2 or s[0] != "parallel":
        return False
    r = s[1:]
    return r in (("loop",), ("do",), ("do", "simd"), ("simd",)) \
        or _target_dir(r)


def _target_comb(s):
    if len(s) < 2 or s[0] != "target":
        return False
    r = s[1:]
    return r in (("loop",), ("simd",)) or _parallel_dir(r) or _teams_dir(r)


def _teams_comb(s):
    if len(s) < 2 or s[0] != "teams":
        return False
    r = s[1:]
    pnw = r in (("distribute",), ("loop",), ("workdistribute",)) or (
        r[0] == "distribute" and _composite(r))
    return pnw or r == ("simd",) or _parallel_dir(r) or _target_dir(r)


def _name_60(seq: tuple) -> bool:
    return len(set(seq)) == len(seq) and (
        _composite(seq) or _par_comb(seq) or _target_comb(seq)
        or _teams_comb(seq)) and spec_nested(seq, 60)


def spec_combined(seq: tuple, version: int) -> bool:
    """Whether the leaves in this order form a conforming compound name
    and the construct may appear outermost in a main program (an orphaned
    compound starting with distribute or loop is not)."""
    ok = _name_52(seq) if version < 60 else _name_60(seq)
    return ok and seq[0] in TOP


def spec(seq: tuple, form: str, version: int) -> bool:
    return spec_combined(seq, version) if form == "combined" \
        else spec_nested(seq, version)


@dataclass(frozen=True)
class Cell:
    version: int
    form: str  # combined | nested
    order: tuple
    spec: bool
    ours: bool
    why: str  # our grammar error or violated rules


def cells(versions=(52, 60)) -> list[Cell]:
    out = []
    for v in versions:
        for seq in orders(v):
            for form in ("combined", "nested"):
                ok, why = ours(seq, form, v)
                out.append(Cell(v, form, seq, spec(seq, form, v), ok, why))
    return out
