"""Tests of the agreement rule and evidence sources, and of the pre-run legality and race check."""


# ---- Tests of the agreement rule and the evidence sources ------------------------------------------------

import importlib.util
import os
import re
import shutil
from pathlib import Path

import pytest

from offload.engine import expected as E
from offload.engine import fsource as F
from offload.engine import fuzz
from offload.engine import transforms as T
from offload.engine.gen import all_programs

ROOT = Path(__file__).resolve().parent.parent.parent
GFORTRAN = shutil.which("gfortran")
AMDFLANG = os.path.exists(E.AMDFLANG)


def ev(tag, value=None, status=None):
    return E.Evidence(tag, status or ("value" if value else "no_value"),
                      value)


@pytest.fixture(scope="module")
def seed18():
    return fuzz.generate(18, "fuzz-1")


@pytest.fixture(scope="module")
def cat52():
    return {p.id: p for p in all_programs(52) if p.legal}


# --- the agreement rule -------------------------------------------------------------

def test_two_independent_sources_trust():
    v = E.decide([ev("model", "checksum=1"), ev("elision", "checksum=1")])
    assert v.status == "trusted" and v.value == "checksum=1"
    assert v.agreeing == ("elision", "model")


def test_model_needs_elision_or_metamorphic():
    v = E.decide([ev("model", "check=pass"), ev("probe", "check=pass")])
    assert v.status == "provisional" and "only" in v.reason
    v = E.decide([ev("model", "check=pass"), ev("probe", "check=pass"),
                  ev("metamorphic", "check=pass")])
    assert v.status == "trusted"
    v = E.decide([ev("elision", "x=1"), ev("probe", "x=1")])
    assert v.status == "trusted"


def test_one_source_is_provisional():
    assert E.decide([ev("model", "checksum=1")]).status == "provisional"
    assert E.decide([]).status == "provisional"


def test_consensus_never_counts():
    v = E.decide([ev("model", "checksum=1"),
                  ev("consensus_only", "checksum=1")])
    assert v.status == "provisional"
    assert v.hints == (("consensus_only", "checksum=1"),)


def test_disagreement_is_recorded_not_resolved():
    v = E.decide([ev("model", "checksum=1"), ev("elision", "checksum=2"),
                  ev("metamorphic", "checksum=1"),
                  ev("probe", "checksum=1")])
    assert v.status == "disputed" and v.value is None
    assert "suspected model bug" in v.reason
    assert ("elision", "checksum=2") in v.values


def test_consensus_disagreeing_does_not_dispute():
    v = E.decide([ev("model", "a"), ev("elision", "a"),
                  ev("consensus_only", "b")])
    assert v.status == "trusted"


def test_one_evidence_per_tag():
    with pytest.raises(ValueError):
        E.decide([ev("model", "a"), ev("model", "a")])


def test_evidence_validation():
    with pytest.raises(ValueError):
        E.Evidence("oracle", "value", "a")
    with pytest.raises(ValueError):
        E.Evidence("model", "value", None)
    with pytest.raises(ValueError):
        E.Evidence("model", "no_value", "a")
    e = E.Evidence("probe", "value", "a", "d", (("afar", "a"),))
    assert E.Evidence.from_dict(e.to_dict()) == e


def test_disposition_is_kept():
    v = E.decide([ev("model", "check=pass"), ev("elision", "check=pass")])
    note = E.disposition_note("unaudited_no_passing_original", v)
    assert note.startswith("unaudited_no_passing_original; ")
    assert "trusted (elision+model)" in note


# --- recorded and run evidence ---------------------------------------------------------

def test_metamorphic_stable_witness():
    e = E.metamorphic_evidence([("cce20", "original", "c=5"),
                                ("cce20", "split", "c=7"),
                                ("cce21", "original", "c=7"),
                                ("cce21", "split", "c=7"),
                                ("afar", "split", None)])
    assert e.status == "value" and e.value == "c=7"
    assert "cce21" in e.detail and "relation violated on cce20" in e.detail


def test_metamorphic_single_run_is_no_witness():
    e = E.metamorphic_evidence([("afar", "original", "c=1"),
                                ("cce19", "split", "c=1")])
    assert e.status == "no_value"


def test_metamorphic_conflict():
    e = E.metamorphic_evidence([("afar", "original", "c=1"),
                                ("afar", "split", "c=1"),
                                ("cce19", "original", "c=2"),
                                ("cce19", "split", "c=2")])
    assert e.status == "conflict"


def test_probe_needs_held_assertions():
    e = E.probe_evidence([("afar", False, "c=1"), ("cce19", True, "c=2")])
    assert e.status == "value" and e.value == "c=2"
    assert E.probe_evidence([("afar", False, "c=1")]).status == "no_value"
    assert E.probe_evidence([], "no data construct").status == \
        "inapplicable"


def test_consensus_evidence():
    e = E.consensus_evidence([("a", "x"), ("b", "x"), ("c", "y"),
                              ("d", None)])
    assert e.status == "value" and e.value == "x"
    assert E.consensus_evidence([("a", "x"), ("b", "y")]).status == \
        "no_value"


def test_assess_combines_runs():
    runs = [E.ToolRun("cce20", "original", "checksum=5", 0),
            E.ToolRun("cce20", "split_combined", "checksum=7", 0),
            E.ToolRun("cce21", "original", "checksum=7", 0),
            E.ToolRun("cce21", "split_combined", "checksum=7", 0),
            E.ToolRun("cce21", "probe", "checksum=7", 0, True),
            E.ToolRun("afar", "probe", "checksum=7", 0, False)]
    evs, v = E.assess(E.model_evidence("checksum=7"),
                      E.Evidence("elision", "inapplicable", detail="x"),
                      runs)
    tags = {e.tag: e for e in evs}
    assert tags["metamorphic"].value == "checksum=7"
    assert tags["probe"].value == "checksum=7"
    assert tags["consensus_only"].status == "no_value"
    assert v.status == "trusted"
    assert v.agreeing == ("metamorphic", "model", "probe")


def test_value_of():
    assert E.value_of("x\nRESULT checksum=12 ran_on_host=0\n") == \
        "checksum=12"
    assert E.value_of("RESULT ran_on_host=1 check=fail\n") == "check=fail"
    assert E.value_of("RESULT ran_on_host=1 check=fail\n" * 2) is None
    assert E.value_of("") is None


# --- the source model ----------------------------------------------------------------

def test_statements_and_clauses(seed18):
    st = F.statements(seed18.source)
    dirs = [F.parse_dir(s) for s in st if s.kind == "dir"]
    t = next(d for d in dirs if d.name == "target")
    assert [c.text() for c in t.clause("map")][0] == \
        "map(always, from: o1)"
    assert t.clause("map")[0].modifiers() == ["always", "from"]
    assert t.clause("map")[3].items() == ["p1", "lp1"]
    assert F.leaves_of("target teams distribute parallel do simd") == \
        ["target", "teams", "distribute", "parallel", "do", "simd"]
    assert F.leaves_of("target enter data") == ["target enter data"]
    decl = F.declarations(st)
    assert decl["o1"].extents == ("n",) and decl["ia"].allocatable
    assert decl["n"].parameter


def test_every_catalog_and_sample_fuzz_program_parses():
    for v in (50, 52, 60):
        for p in all_programs(v):
            for s in F.statements(p.source):
                if s.kind == "dir":
                    F.parse_dir(s, v)
            F.main_program(F.statements(p.source))
    for seed in range(1, 41):
        for s in F.statements(fuzz.generate(seed).source):
            if s.kind == "dir":
                F.parse_dir(s)


# --- elision applicability -------------------------------------------------------------

UNRESOLVED_C1 = (18, 209, 357, 485, 992, 1003, 1283, 1331, 1422, 1495,
                 1525, 1540, 1639, 1759, 1980, 2064, 2206, 2345)


def test_elision_applies_to_the_c1_programs_without_present():
    bad = [s for s in UNRESOLVED_C1
           if not E.elision_applicability(
               fuzz.generate(s, "fuzz-1").source).ok]
    assert bad == [1525, 1759]
    a = E.elision_applicability(fuzz.generate(1759, "fuzz-1").source)
    assert a.reasons == ["present modifier"]


def _mut(src, old, new):
    assert old in src
    return src.replace(old, new)


@pytest.mark.parametrize("old,new,why,both", [
    # the lastprivate of a split construct reaches the host only by a map
    ("map(tofrom: p1, lp1)", "map(tofrom: p1) map(to: lp1)",
     "lp1 is read on the host", True),
    ("map(tofrom: p1, lp1)", "map(tofrom: p1)",
     "lp1 is read on the host", True),
    # a combined construct's lastprivate is mapped tofrom (5.2 §17.2):
    # without the clause the host keeps the old value
    ("order(unconstrained: concurrent) lastprivate(lp2)",
     "order(unconstrained: concurrent)", "lp2 is read on the host", True),
    # an output the data region maps to only, without always on the
    # kernel, never comes back
    ("map(tofrom: o1, o2, o3)", "map(to: o1) map(tofrom: o2, o3)",
     None, False),
])
def test_elision_detects_device_dependence(seed18, old, new, why, both):
    src = _mut(seed18.source, old, new)
    if old.startswith("map(tofrom: o1"):
        src = _mut(src, "map(always, from: o1)", "map(from: o1)")
    a = E.elision_applicability(src)
    assert not a.ok
    if why:
        assert why in a.why
    labels = {"copy semantics" in r for r in a.reasons}
    assert (len(a.reasons) == 2) == both and True in labels


def test_elision_detects_reference_count_dependence(seed18):
    # host update without target update: only the always map on the
    # next kernel refreshes the device copy; without it the kernel reads a
    # stale copy under the reference-count rules (an unconditional copy
    # would hide it): the result depends on reference counts
    src = _mut(seed18.source, "!$omp target update to(ia)", "continue")
    assert E.elision_applicability(src).ok
    src = _mut(src, "map(always, tofrom: ia)", "map(tofrom: ia)")
    a = E.elision_applicability(src)
    assert not a.ok and len(a.reasons) == 1
    assert "ia is read on the device" in a.why
    assert "[copy semantics]" in a.why


def test_elision_keeps_spec_equivalent_mutants(seed18):
    # always on an output read by no later kernel changes nothing
    src = _mut(seed18.source, "map(always, from: o1)", "map(from: o1)")
    assert E.elision_applicability(src).ok


def test_elision_runtime_queries_and_guards(cat52):
    a = E.elision_applicability(cat52["omp52-clause-schedule"].source)
    assert not a.ok and "omp_get_thread_num" in a.why
    tp = cat52["omp52-directive-target_parallel"].source
    assert E.elision_applicability(tp).ok
    # the same guard directly in a teams region runs once per team
    bad = tp.replace("!$omp target parallel map", "!$omp target teams map")
    bad = bad.replace("!$omp end target parallel", "!$omp end target teams")
    a = E.elision_applicability(bad)
    assert not a.ok and "once per team" in a.why


def test_elision_private_copies_are_device_semantics(cat52):
    a = E.elision_applicability(cat52["omp52-clause-private"].source)
    assert not a.ok and "is read on the host" in a.why
    a = E.elision_applicability(cat52["omp52-clause-firstprivate"].source)
    assert not a.ok


def test_elision_floating_point_reduction(seed18):
    src = _mut(seed18.source, "  integer :: i, j, jj, p1, p2, lp1, lp2, "
               "lp3\n", "  integer :: i, j, jj, p1, p2, lp1, lp2, lp3\n"
               "  real :: rr\n")
    src = _mut(src, "lastprivate(lp1) dist_schedule(static)",
               "lastprivate(lp1) dist_schedule(static) reduction(+: rr)")
    a = E.elision_applicability(src)
    assert not a.ok and "floating-point reduction" in a.why


def test_elision_conditional_lastprivate_needs_conditional(seed18):
    src = _mut(seed18.source, "lastprivate(conditional: lp3)",
               "lastprivate(lp3)")
    a = E.elision_applicability(src)
    assert not a.ok and "lp3" in a.why


def test_elision_rule_names_every_exclusion():
    for word in ("present", "declare target", "reference count",
                 "omp_get_thread_num", "floating-point", "linear",
                 "race-free"):
        assert word in E.ELISION_RULE


def test_copy_independent_ignores_queries(cat52):
    src = cat52["omp52-clause-dist_schedule"].source
    assert not E.elision_applicability(src).ok
    assert E.copy_independent(src).ok


def test_presence_snapshots(seed18):
    snaps = E.presence_snapshots(seed18.source)
    lines = seed18.source.splitlines()
    first = snaps[0]
    assert first[0] == "before" and "target data" in lines[first[1]]
    assert not any(first[2].values())
    after_begin = snaps[1]
    assert after_begin[2]["ia"] and after_begin[2]["o3"]
    last = snaps[-1]
    assert "end target data" in lines[last[1]]
    assert not last[2]["ia"]


# --- base-language programs: structures, pointers, internal procedures ------

BASE_PROG = """\
program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 8
  type :: nd_t
    integer :: k(n)
  end type nd_t
  type :: rec_t
    integer :: a(n)
    integer :: s
    type(nd_t) :: nd
  end type rec_t
  type(rec_t) :: dr
  integer, target :: tgc(n)
  integer, pointer :: po(:)
  integer :: o(n)
  integer :: i, hf
  integer(8) :: cs
  do i = 1, n
    dr%a(i) = i
    dr%nd%k(i) = 2 * i
    tgc(i) = 3 * i
  end do
  dr%s = 5
  o = 0
  hf = 0
  po => tgc
  !$omp target map(to: dr%a, dr%s, dr%nd) map(tofrom: o, hf)
    hf = merge(1, 0, omp_is_initial_device())
    do i = 1, n
      o(i) = dr%a(i) + dr%s + dr%nd%k(i)
    end do
  !$omp end target
  !$omp target map(tofrom: po)
    do i = 1, n
      po(i) = po(i) + 1
    end do
  !$omp end target
  call kp(o)
  cs = 0
  do i = 1, n
    cs = cs + o(i) + tgc(i)
  end do
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', hf
contains
  subroutine kp(o)
    integer, intent(inout) :: o(:)
    integer :: i
    !$omp target map(tofrom: o)
    do i = 1, n
      o(i) = o(i) * 2
    end do
    !$omp end target
  end subroutine kp
end program p
"""
# o(i) = 2 * (i + 5 + 2i), tgc(i) = 3i + 1: sum over i = 1..8 of 9i + 11
BASE_VALUE = "checksum=412"


def test_designators_keep_component_paths():
    assert F.designators("o(i) = dr%nd%k(mod(j, n) + 1) + ds(i)%u") == \
        ["o", "i", "dr%nd%k", "mod", "j", "n", "ds%u", "i"]
    assert F.designators("x /= 1.5d0 .and. 'a%b' == c") == ["x", "c"]


def test_type_definitions_are_not_variables():
    st = F.statements(BASE_PROG)
    decls = F.declarations(st)
    assert "dr" in decls and "a" not in decls and "k" not in decls
    t = F.type_defs(st)
    assert list(t) == ["nd_t", "rec_t"]
    assert t["rec_t"]["a"].extents == ("n",)
    assert t["rec_t"]["nd"].type == "type(nd_t)"


def test_main_program_stops_at_contains():
    st = F.statements(BASE_PROG)
    start, stop = F.main_program(st)
    assert st[start].text == "do i = 1, n"
    assert st[stop].lower == "contains"
    procs = F.internal_procedures(st)
    assert list(procs) == ["kp"] and procs["kp"].dummies == ["o"]
    assert procs["kp"].decls["o"].intent == "inout"
    assert procs["kp"].body[0].kind == "dir"


def test_elision_applies_to_structures_pointers_and_procedures():
    a = E.elision_applicability(BASE_PROG)
    assert a.ok, a.why
    assert E.copy_independent(BASE_PROG).ok


@pytest.mark.parametrize("old,new,why", [
    # 5.2 §13.8: a referenced element of a structure with mapped
    # elements must be mapped too
    ("map(to: dr%a, dr%s, dr%nd)", "map(to: dr%a, dr%s)",
     "dr%nd%k is referenced but only other parts of dr are mapped"),
    # a pointer is attached only when it is a map list item
    ("!$omp target map(tofrom: po)", "!$omp target map(tofrom: tgc)",
     "pointer po is referenced in a target region without being attached"),
    # the device writes through the pointer and nothing brings them back
    ("!$omp target map(tofrom: po)", "!$omp target map(to: po)",
     "tgc is read on the host"),
    # parts of a present structure are one storage block
    ("  !$omp target map(to: dr%a, dr%s, dr%nd) map(tofrom: o, hf)\n",
     "  !$omp target enter data map(to: dr%a)\n"
     "  !$omp target map(to: dr%a, dr%s, dr%nd) map(tofrom: o, hf)\n",
     "a part of the structure that is not on the device"),
    # a pointer actual argument may be passed as a copy: not while its
    # target is present
    ("  call kp(o)\n", "  !$omp target enter data map(to: tgc)\n"
     "  call kp(po)\n  !$omp target exit data map(from: tgc)\n",
     "actual argument po of kp is present on the device at the call"),
    # an absent optional dummy argument may not be referenced
    ("    integer, intent(inout) :: o(:)\n",
     "    integer, intent(inout) :: o(:)\n"
     "    integer, intent(in), optional :: z(:)\n", None),
])
def test_elision_base_language_violations(old, new, why):
    src = _mut(BASE_PROG, old, new)
    a = E.elision_applicability(src)
    if why is None:
        # declared, absent and unused: still applicable; named in a map
        # clause: ignored; referenced: a violation
        assert a.ok, a.why
        src = _mut(_mut(src, "subroutine kp(o)", "subroutine kp(o, z)"),
                   "    !$omp target map(tofrom: o)\n",
                   "    !$omp target map(tofrom: o) map(to: z)\n")
        assert E.elision_applicability(src).ok
        src = _mut(src, "o(i) = o(i) * 2", "o(i) = o(i) * 2 + z(i)")
        a = E.elision_applicability(src)
        assert not a.ok and "absent optional dummy argument" in a.why
        return
    assert not a.ok and why in a.why, a.why


def test_elision_implicit_whole_structure_map():
    src = _mut(BASE_PROG, "map(to: dr%a, dr%s, dr%nd) map(tofrom: o, hf)",
               "map(tofrom: o, hf)")
    assert E.elision_applicability(src).ok


def test_elision_strided_update_of_the_written_section():
    src = _mut(BASE_PROG, "  call kp(o)\n", """\
  !$omp target enter data map(to: tgc)
  do i = 1, n, 2
    tgc(i) = tgc(i) + 7
  end do
  !$omp target update to(tgc(1:n:2))
  !$omp target map(tofrom: o)
    do i = 1, n
      o(i) = o(i) + tgc(i)
    end do
  !$omp end target
  !$omp target exit data map(release: tgc)
  call kp(o)
""")
    assert E.elision_applicability(src).ok
    bad = _mut(src, "update to(tgc(1:n:2))", "update to(tgc(2:n:2))")
    a = E.elision_applicability(bad)
    assert not a.ok and "tgc is read on the device" in a.why


@pytest.mark.parametrize("group", ["derived", "alloc"])
def test_base_language_exclusions_are_rules_not_parse_failures(group):
    """Every derived/alloc program of the stage campaigns (seeds 1-300)
    that elision does not apply to is out for a stated rule or a copy
    dependence, never because the analysis cannot read it."""
    for seed in range(1, 301):
        a = E.elision_applicability(
            fuzz.generate(seed, "fuzz-3", (group,)).source)
        assert "not understood" not in a.why, (seed, a.why)


# --- the elided build -------------------------------------------------------------------

@pytest.mark.gfortran
@pytest.mark.skipif(not GFORTRAN, reason="gfortran is not installed")
def test_elided_fuzz_program_prints_the_model_value(seed18):
    v, note = E.run_elided(seed18.source, "gfortran")
    assert v == f"checksum={seed18.expected}", note


@pytest.mark.gfortran
@pytest.mark.skipif(not GFORTRAN, reason="gfortran is not installed")
def test_elided_base_program_prints_its_value():
    v, note = E.run_elided(BASE_PROG, "gfortran")
    assert v == BASE_VALUE, note


@pytest.mark.gfortran
@pytest.mark.skipif(not GFORTRAN, reason="gfortran is not installed")
@pytest.mark.parametrize("group,seed", [("derived", 1), ("alloc", 3)])
def test_elided_base_language_fuzz_program_prints_the_model_value(group,
                                                                  seed):
    # derived 1: whole, component and implicit structure maps; alloc 3: a
    # kernel in an internal subroutine, a pointer component and pointer
    # outputs
    p = fuzz.generate(seed, "fuzz-3", (group,))
    assert E.elision_applicability(p.source).ok
    v, note = E.run_elided(p.source, "gfortran")
    assert v == f"checksum={p.expected}", note


def test_elided_source_drops_only_sentinel_lines():
    src = ("program p\n"
           "  integer :: i, s\n"
           "  s = 0\n"
           "  !$omp target teams distribute parallel do &\n"
           "  !$omp& reduction(+: s) map(tofrom: s)\n"
           "  do i = 1, 4\n"
           "    s = s + i   ! not a directive: !$omp\n"
           "  end do\n"
           "!$  s = s + 100\n"
           "  !$OMP END TARGET TEAMS DISTRIBUTE PARALLEL DO\n"
           "  print *, s\n"
           "end program p\n")
    assert E.elided_source(src) == (
        "program p\n"
        "  integer :: i, s\n"
        "  s = 0\n"
        "  do i = 1, 4\n"
        "    s = s + i   ! not a directive: !$omp\n"
        "  end do\n"
        "  print *, s\n"
        "end program p\n")


def test_elided_source_of_a_fuzz_program(seed18):
    el = E.elided_source(seed18.source)
    kept = [ln for ln in seed18.source.splitlines()
            if not ln.lstrip().startswith("!$")]
    assert el.splitlines() == kept
    assert len(kept) < len(seed18.source.splitlines())


@pytest.mark.gfortran
@pytest.mark.skipif(not GFORTRAN, reason="gfortran is not installed")
def test_elided_source_is_what_the_elided_build_runs(seed18):
    # the shown program builds to the same value as the original built
    # without OpenMP (its sentinel lines are comments there)
    assert E.run_elided(E.elided_source(seed18.source), "gfortran") == \
        E.run_elided(seed18.source, "gfortran")


@pytest.mark.skipif(not (GFORTRAN and AMDFLANG),
                    reason="gfortran or amdflang missing")
def test_elision_evidence_both_compilers(cat52):
    e = E.elision_evidence(cat52["omp52-directive-target_parallel"].source)
    assert e.status == "value" and e.value == "check=pass"
    assert dict(e.observations) == {"gfortran": "check=pass",
                                    "amdflang": "check=pass"}
    e = E.elision_evidence(cat52["omp52-clause-private"].source)
    assert e.status == "inapplicable"


# --- the rewrites -------------------------------------------------------------------------

def test_split_clauses_follow_17_2():
    cl = F._clauses("map(to: a) firstprivate(x, y) lastprivate(lp) "
                    "reduction(+: r) map(tofrom: y) if(lt) thread_limit(8) "
                    "num_teams(2) private(t) nowait")
    tgt, inner = T.split_clauses("teams distribute", cl, 52)
    assert "map(to: a)" in tgt and "nowait" in tgt
    assert "firstprivate(x)" in tgt            # y is mapped: inner only
    assert "firstprivate(x, y)" in inner
    assert "map(tofrom: lp, r)" in tgt         # 5.2 §17.2
    assert "lastprivate(lp)" in inner and "reduction(+: r)" in inner
    assert "if(lt)" in tgt and "if(lt)" not in inner   # teams: 6.0 only
    assert "thread_limit(8)" in tgt and "thread_limit(8)" in inner
    assert "num_teams(2)" in inner and "private(t)" in inner


def test_split_combined_seed18(seed18):
    out = T.TRANSFORMS["split_combined"].apply(seed18.source)
    assert "!$omp parallel do order(unconstrained: concurrent) " \
        "lastprivate(lp2)" in out
    assert "map(tofrom: lp2)" in out
    assert out.count("!$omp end target\n") == 3


def test_enter_exit_data_types(seed18):
    out = T.TRANSFORMS["enter_exit_data"].apply(seed18.source)
    assert "!$omp target enter data map(alloc: o1) map(to: ib) " \
        "map(to: ia, p2) map(to: p1, lp1)" in out
    assert "!$omp target exit data map(from: o1) map(from: ib) " \
        "map(release: ia, p2) map(from: p1, lp1)" in out


def test_if_false_and_its_precondition(seed18):
    out = T.TRANSFORMS["if_false"].apply(seed18.source)
    assert "!$omp target data map(to: ia, ib, ic) map(tofrom: o1, o2, " \
        "o3) if(.false.)" in out
    assert out.count("if(target: .false.)") == 3
    assert "if(.false.)" in out.split("target update to(ia)")[1][:20]
    with pytest.raises(T.NotApplicable, match="present"):
        T.TRANSFORMS["if_false"].apply(
            fuzz.generate(1759, "fuzz-1").source)


def test_clause_settings(seed18, cat52):
    out = T.TRANSFORMS["num_teams_1"].apply(seed18.source)
    assert "!$omp teams thread_limit(64) num_teams(1)" in out
    out = T.TRANSFORMS["schedule_static_1"].apply(seed18.source)
    assert "schedule(static, 1)" in out
    with pytest.raises(T.NotApplicable, match="runtime routine"):
        T.TRANSFORMS["num_teams_1"].apply(
            cat52["omp52-clause-dist_schedule"].source)
    with pytest.raises(T.NotApplicable, match="nothing to rewrite"):
        T.TRANSFORMS["split_combined"].apply(
            cat52["omp52-clause-schedule"].source)


@pytest.mark.gfortran
@pytest.mark.skipif(not GFORTRAN, reason="gfortran is not installed")
def test_rewrites_of_seed18_are_legal(seed18):
    for name, out in T.variants(seed18.source).items():
        assert isinstance(out, str), (name, out)
        assert E.variant_legality(out, 52, "fuzz") is None, name


@pytest.mark.gfortran
@pytest.mark.skipif(not GFORTRAN, reason="gfortran is not installed")
def test_presence_probe(seed18, cat52):
    out = T.presence_probe(seed18.source)
    assert "!$omp target enter data map(to: probe_cal)" in out
    assert out.count("PROBE presence=") == 1
    assert "integer, allocatable, target :: ia(:)" in out
    assert "if (omp_target_is_present(c_loc(ia), omp_get_default_device()" \
        ") /= 0) probe_ok = .false." in out
    assert E.variant_legality(out, 52, "fuzz") is None
    neg = T.presence_probe(cat52["omp52-clause-map-present"].source)
    assert neg.count("PROBE presence=") == 2


def test_transform_docs_name_every_transform():
    doc = (ROOT / "docs" / "tooling" / "expected-behaviour.md").read_text()
    for name in T.TRANSFORMS:
        assert f"`{name}`" in doc
    for tag in E.TAGS:
        assert f"`{tag}`" in doc


# --- the report's evaluation ----------------------------------------------------------------

def _tool():
    spec = importlib.util.spec_from_file_location(
        "expected_tool", ROOT / "tools" / "derive" / "expected.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_evaluate_stored_record():
    X = _tool()
    rec = {"key": "c1:1", "model": "checksum=7", "model_detail": "",
           "elision": E.Evidence("elision", "value", "checksum=7")
           .to_dict(),
           "variants": {"split_combined": "ok", "probe": "n/a: probe: x"},
           "runs": [E.ToolRun("cce20", "original", "checksum=5").to_dict(),
                    E.ToolRun("cce20", "split_combined",
                              "checksum=7").to_dict()]}
    evs, v = X.evaluate(rec)
    assert v.status == "trusted" and v.agreeing == ("elision", "model")
    assert {e.tag: e.status for e in evs}["probe"] == "inapplicable"
    assert X.wrong_toolchains(rec, v) == ["cce20"]
    assert X.settled_by(v) == "elision + model"


def test_xnack0_command_names_flux_and_both_sets(capsys):
    X = _tool()
    X.main(["xnack0-command"])
    out = capsys.readouterr().out
    assert "flux alloc" in out and "--xnack 0" in out
    assert "fuzz --run c1" in out and "catalog" in out


def test_unstable_toolchain_is_no_probe_witness():
    # seed 1003 of c1: CCE 20 prints another value for the original than
    # for the host-execution rewrite, so its held probe does not count
    runs = [E.ToolRun("cce20", "original", "checksum=5", 0),
            E.ToolRun("cce20", "if_false", "checksum=7", 1),
            E.ToolRun("cce20", "probe", "checksum=5", 0, True)]
    evs, v = E.assess(E.model_evidence("checksum=7"),
                      E.Evidence("elision", "value", "checksum=7"), runs)
    tags = {e.tag: e for e in evs}
    assert tags["probe"].status == "no_value"
    assert "relation violated on cce20" in tags["metamorphic"].detail
    assert v.status == "trusted"


# --- Independence, memory modes and the first minor case -----------------------------------------------

def wit(tag, value, *witnesses):
    return E.Evidence(tag, "value", value, witnesses=tuple(witnesses))


def test_sources_record_their_witnesses():
    m = E.metamorphic_evidence([("afar", "original", "c=1"),
                                ("afar", "split", "c=1"),
                                ("cce19", "original", "c=1")])
    assert m.witnesses == ("afar",)
    p = E.probe_evidence([("afar", False, "c=1"), ("cce19", True, "c=1")])
    assert p.witnesses == ("cce19",)
    assert E.Evidence.from_dict(m.to_dict()) == m


def test_metamorphic_and_probe_on_one_compiler_are_one_source():
    # the same toolchain behind both: one source, not two
    v = E.decide([wit("metamorphic", "c=1", "cce19"),
                  wit("probe", "c=1", "cce19")])
    assert v.status == "provisional"
    assert "one source" in v.reason
    # one compiler family (CCE 19/20/21 share bugs) counts as one compiler
    v = E.decide([wit("metamorphic", "c=1", "cce20"),
                  wit("probe", "c=1", "cce21")])
    assert v.status == "provisional"
    # any shared family is enough to merge them
    v = E.decide([wit("metamorphic", "c=1", "afar", "cce19"),
                  wit("probe", "c=1", "afar", "cce19")])
    assert v.status == "provisional"
    # different compilers behind each: two sources
    v = E.decide([wit("metamorphic", "c=1", "afar"),
                  wit("probe", "c=1", "cce19")])
    assert v.status == "trusted"


def test_merged_metamorphic_probe_still_partners_the_fuzz_model():
    v = E.decide([E.model_evidence("checksum=1"),
                  wit("metamorphic", "checksum=1", "afar"),
                  wit("probe", "checksum=1", "afar")])
    assert v.status == "trusted"


def test_catalog_model_counts_only_with_elision():
    only_el = ("elision",)
    v = E.decide([E.model_evidence("check=pass"),
                  wit("metamorphic", "check=pass", "afar")],
                 model_partners=only_el)
    assert v.status == "provisional"
    assert "elision" in v.reason
    v = E.decide([E.model_evidence("check=pass"),
                  wit("metamorphic", "check=pass", "cce19"),
                  wit("probe", "check=pass", "cce19")],
                 model_partners=only_el)
    assert v.status == "provisional"
    v = E.decide([E.model_evidence("check=pass"),
                  ev("elision", "check=pass")], model_partners=only_el)
    assert v.status == "trusted"


def test_evaluate_catalog_record_without_elision_is_provisional():
    # omp52-clause-is_device_ptr shape: metamorphic on AFAR only + the
    # program's own check
    X = _tool()
    rec = {"key": "52:p", "kind": "catalog", "model": "check=pass",
           "model_detail": "the program's own oracle",
           "elision": E.Evidence("elision", "inapplicable",
                                 detail="is_device_ptr").to_dict(),
           "variants": {"enter_exit_data": "ok", "probe": "n/a: x"},
           "runs": [E.ToolRun("afar", "original", "check=pass", 0).to_dict(),
                    E.ToolRun("afar", "enter_exit_data", "check=pass",
                              0).to_dict()]}
    evs, v = X.evaluate(rec)
    assert {e.tag: e.status for e in evs}["metamorphic"] == "value"
    assert v.status == "provisional"
    rec["kind"] = "fuzz"
    assert X.evaluate(rec)[1].status == "trusted"


def test_assess_refuses_mixed_memory_modes():
    runs = [E.ToolRun("afar", "original", "check=pass", 0, xnack=1),
            E.ToolRun("afar", "if_false", "check=pass", 1, xnack=0)]
    with pytest.raises(ValueError, match="memory mode"):
        E.assess(E.model_evidence("check=pass"),
                 E.Evidence("elision", "inapplicable", detail="x"), runs)


def test_probe_runs_one_per_toolchain():
    with pytest.raises(ValueError, match="one probe run per toolchain"):
        E.probe_evidence([("afar", True, "c=1"), ("afar", False, "c=2")])


def test_copy_mode_runs_are_a_separate_verdict():
    # map-self shape: AFAR copies with `self` at HSA_XNACK=0, so its
    # copy-mode original differs from its HSA_XNACK=1 value; that must not
    # make AFAR violate the metamorphic relation of the HSA_XNACK=1 runs
    X = _tool()
    rec = {"key": "60:map-self", "kind": "catalog", "model": "check=pass",
           "model_detail": "", "elision": E.Evidence(
               "elision", "value", "check=pass").to_dict(),
           "variants": {"enter_exit_data": "ok", "probe": "ok"},
           "runs": [E.ToolRun("afar", "original", "check=pass", 0).to_dict(),
                    E.ToolRun("afar", "enter_exit_data", "check=pass",
                              0).to_dict(),
                    E.ToolRun("afar", "probe", "check=pass", 0,
                              True).to_dict()]}
    x0 = {"key": "60:map-self", "variants": {"enter_exit_data": "ok",
                                             "probe": "ok"},
          "runs": [E.ToolRun("afar", "original", "check=fail", 0,
                             xnack=0).to_dict(),
                   E.ToolRun("afar", "enter_exit_data", "check=fail", 0,
                             xnack=0).to_dict(),
                   E.ToolRun("afar", "probe", "check=fail", 0, False,
                             xnack=0).to_dict()]}
    evs, v = X.evaluate(rec)
    tags = {e.tag: e for e in evs}
    assert "violated" not in tags["metamorphic"].detail
    assert tags["probe"].witnesses == ("afar",)
    assert v.status == "trusted"
    evs0, v0 = X.evaluate_copy_mode(rec, x0)
    tags0 = {e.tag: e for e in evs0}
    assert tags0["metamorphic"].value == "check=fail"
    assert tags0["probe"].status == "no_value"
    assert v0.status == "disputed"
    # the report keeps the HSA_XNACK=1 verdict and adds the copy-mode one
    text = X.render([], [dict(rec, version=60, program="map-self",
                              audit="", mismatches=[])],
                    {}, {"60:map-self": x0}, {})
    row = next(ln for ln in text.splitlines() if "`map-self`" in ln)
    assert "| trusted; copy mode: disputed |" in row


def test_elision_needs_every_build(monkeypatch):
    monkeypatch.setattr(E, "run_elided", lambda s, c: (
        ("checksum=3", "") if c == "gfortran" else
        (None, "amdflang build failed")))
    ap = E.Applicability(True)
    e = E.elision_evidence("x", applicability=ap)
    assert e.status == "no_value" and "amdflang build failed" in e.detail


# --- The fuzz set follows the host-path validity rule -------------------------------

def test_unresolved_seeds_include_failed_host_references(tmp_path):
    from offload.engine import fuzz_exec as fe
    X = _tool()
    d = tmp_path / "fuzz" / "r"
    d.mkdir(parents=True)
    rows = [
        # failed reference, no host run prints the model: in the set
        fe.ProgramResult(1, "fuzz-1", "ok", expected=5, host_ref_tc="afar",
                         host_ref_failed=True, results={
                             "afar": fe.TcResult("afar", "agree", ""),
                             "cce19": fe.TcResult("cce19", "agree", "",
                                                  host_checksum=6)}),
        # failed reference, another host run prints the model: not in it
        fe.ProgramResult(2, "fuzz-1", "ok", expected=5, host_ref_tc="afar",
                         host_ref_failed=True, results={
                             "cce19": fe.TcResult("cce19", "agree", "",
                                                  host_checksum=5)}),
        fe.ProgramResult(3, "fuzz-1", "ok", expected=5, host_ref_tc="afar",
                         host_ref=4, host_mismatch=True, results={
                             "afar": fe.TcResult("afar", "agree", "",
                                                 host_checksum=4)}),
        fe.ProgramResult(4, "fuzz-1", "ok", expected=5, host_ref_tc="afar",
                         host_ref=5)]
    (d / "programs.jsonl").write_text(
        "\n".join(p.to_json() for p in rows) + "\n")
    assert X.unresolved_seeds("r", base=tmp_path / "fuzz") == [1, 3]


def test_fuzz_report_shows_the_owner_validity():
    X = _tool()
    rec = {"key": "c1:9", "seed": 9, "kernels": ["k"],
           "model": "checksum=7", "model_detail": "",
           "elision": E.Evidence("elision", "inapplicable",
                                 detail=["present modifier"]).to_dict(),
           "variants": {"probe": "n/a: x"},
           "runs": [E.ToolRun("afar", "original", "checksum=7").to_dict()]}
    text = X.render([rec], [], {}, {}, {}, validity={9: {
        "validity": "noncompliant", "witnesses": [],
        "host_path_failure": []}})
    assert "## The 1 c1 programs no host run reproduced" in text
    row = next(ln for ln in text.splitlines() if ln.startswith("| 9 |"))
    assert "noncompliant" in row
    text = X.render([rec], [], {}, {}, {}, validity={9: {
        "validity": "valid", "witnesses": ["elision"],
        "host_path_failure": ["afar"]}})
    row = next(ln for ln in text.splitlines() if ln.startswith("| 9 |"))
    assert "valid (host_path_failure: afar)" in row


def test_fuzz_report_names_seeds_that_left_or_entered_the_set():
    """The set is re-derived from the campaign (host rechecks included);
    a measured seed that left it stays in the table and is named, a seed
    that entered it without records is named as not measured."""
    X = _tool()
    rec = {"key": "c1:9", "seed": 9, "kernels": ["k"],
           "model": "checksum=7", "model_detail": "",
           "elision": E.Evidence("elision", "value", "checksum=7").to_dict(),
           "variants": {"probe": "n/a: x"},
           "runs": [E.ToolRun("cce20", "original", "checksum=5").to_dict()]}
    text = X.render([rec], [], {}, {}, {}, validity={9: {
        "validity": "valid", "witnesses": ["cce20", "elision"],
        "host_path_failure": []}}, current=[11])
    assert "## The 1 c1 programs no host run reproduced" in text
    assert "left the set: 9" in text
    assert "entered the set without expected-source runs: 11" in text
    row = next(ln for ln in text.splitlines() if ln.startswith("| 9 |"))
    assert "valid (host witness: cce20)" in row


# --- Code executed once per team or thread -------------------------------------------------------------

REDUNDANT = """program p
  implicit none
  integer :: s, x, t, i
  integer :: b(8)
  s = 0
  x = 0
  b = 0
  !$omp target teams reduction(+: s) map(tofrom: s)
  s = s + 1
  !$omp end target teams
  !$omp target parallel map(tofrom: x)
  x = x + 1
  !$omp end target parallel
  print '(a,a)', 'RESULT ran_on_host=0 check=', merge('pass', 'fail', s > 0)
end program p
"""

ONCE = """program p
  use omp_lib, only: omp_get_team_num, omp_get_thread_num
  implicit none
  integer :: s, x, t, i, j
  integer :: b(8)
  s = 0
  x = 0
  b = 0
  !$omp target teams distribute parallel do map(tofrom: b)
  do i = 1, 8
    do j = 1, 2
      b(i) = b(i) + j
    end do
  end do
  !$omp target teams map(tofrom: x)
  if (omp_get_team_num() == 0) x = 7
  !$omp end target teams
  !$omp target parallel private(t) map(tofrom: s)
  t = 3
  !$omp single
  s = s + 1
  !$omp end single
  !$omp end target parallel
  !$omp target teams private(t) map(tofrom: x)
  t = 1
  !$omp distribute
  do i = 1, 8
    t = t + i
  end do
  !$omp end target teams
  print '(a,a)', 'RESULT ran_on_host=0 check=', merge('pass', 'fail', s > 0)
end program p
"""


def test_redundant_writes_are_detected():
    r = E.redundant_execution(REDUNDANT)
    assert len(r) == 2, r
    assert "line 9: s is written once per team" in r[0]
    assert "line 12: x is written once per thread" in r[1]
    a = E.elision_applicability(REDUNDANT)
    assert not a.ok and "once per team" in a.why


def test_worksharing_guards_and_private_copies_run_once():
    assert E.redundant_execution(ONCE) == []


def test_a_parallel_do_inside_teams_runs_once_per_team():
    src = ONCE.replace(
        "!$omp target teams distribute parallel do map(tofrom: b)",
        "!$omp target teams map(tofrom: b)\n  !$omp parallel do")
    src = src.replace("  end do\n  !$omp target teams map(tofrom: x)",
                      "  end do\n  !$omp end target teams\n"
                      "  !$omp target teams map(tofrom: x)", 1)
    r = E.redundant_execution(src)
    assert any("b is written once per team" in x for x in r), r


def test_loop_bind_names_the_region_it_workshares():
    base = """program p
  implicit none
  integer :: i
  integer :: b(8)
  b = 0
  !$omp target teams map(tofrom: b)
  !$omp loop{}
  do i = 1, 8
    b(i) = i
  end do
  !$omp end target teams
  print '(a,a)', 'RESULT ran_on_host=0 check=', merge('pass', 'fail', b(1) > 0)
end program p
"""
    assert E.redundant_execution(base.format("")) == []
    assert E.redundant_execution(base.format(" bind(teams)")) == []
    assert E.redundant_execution(base.format(" bind(thread)"))


def test_team_and_thread_rewrites_skip_redundant_code():
    vs = T.variants(REDUNDANT, 52, ["num_teams_1", "num_teams_3",
                                    "thread_limit_32", "if_false"])
    for name, v in vs.items():
        assert isinstance(v, T.NotApplicable), name
        assert "once per team" in str(v), (name, v)
    vs = T.variants(ONCE, 52, ["num_teams_3", "thread_limit_32"])
    assert all(isinstance(v, str) for v in vs.values()), vs


def test_redundant_catalog_programs_were_already_excluded():
    """No current program hits this, and the case is kept: a legal
    catalog program with a write the detector reports (the bind programs
    guard by a variable holding omp_get_team_num()) is already outside
    elision and the team/thread rewrites by a runtime routine (rule 2)."""
    hits = []
    for v in (50, 52, 60):
        for p in all_programs(v):
            if not p.legal:
                continue
            try:
                r = E.redundant_execution(p.source, v)
            except F.SourceError:
                continue
            if r:
                why = E._Analysis(p.source, v).static_exclusions()[0]
                assert any(w.startswith("runtime routine") for w in why), \
                    (p.id, r, why)
                hits.append(p.id)
    assert hits and all("bind" in h for h in hits), hits


# --- The catalog set and partial reruns -----------------------------------

def test_catalog_set_leaves_out_host_device_programs():
    from offload.engine.report import Mismatch, Row
    X = _tool()
    rows = [Row("omp.clause.depend.depobj", "afar", 1, "rejected", False,
                version=52, program_id=pid, scope=scope)
            for pid, scope in (("omp52-clause-depend-depobj", "device"),
                               ("omp52-clause-depend-depobj-hostdev",
                                "host+device"))]
    mism = [Mismatch("omp.clause.depend.depobj", "afar", "supported",
                     "rejected", version=52)]
    sel = X.catalog_set(table=rows, mism=mism, summ={"versions": {}})
    assert list(sel) == [(52, "omp52-clause-depend-depobj")]


def test_partial_rerun_merges_into_the_stored_records():
    X = _tool()
    old = [{"key": "52:a", "program": "a", "version": 52, "atom": "x",
            "mismatches": [], "audit": "old", "runs": [1]},
           {"key": "52:b", "program": "b", "version": 52, "atom": "y",
            "mismatches": [], "audit": "", "runs": [2]},
           {"key": "52:gone", "program": "gone", "version": 52,
            "atom": "z", "mismatches": [], "audit": "", "runs": []}]
    new = [{"key": "52:b", "program": "b", "version": 52, "atom": "y",
            "mismatches": [], "audit": "", "runs": [3]}]
    sel = {(52, "a"): {"atom": "x", "mismatches": [], "audit": "valid"},
           (52, "b"): {"atom": "y", "mismatches": [], "audit": ""}}
    out = X.merge_records(old, new, sel)
    assert [r["key"] for r in out] == ["52:a", "52:b"]
    assert out[0]["runs"] == [1] and out[0]["audit"] == "valid"
    assert out[1]["runs"] == [3]


def _rec_x1_x0():
    rec = {"key": "52:p", "kind": "catalog", "model": "check=pass",
           "model_detail": "", "source": "program p\nend program p\n",
           "version": 52,
           "elision": E.Evidence("elision", "inapplicable",
                                 detail="x").to_dict(),
           "variants": {"probe": "n/a: x"},
           "runs": [E.ToolRun("afar", "original", "check=pass",
                              0).to_dict()]}
    x0 = {"key": "52:p", "variants": {"enter_exit_data": "ok",
                                      "probe": "n/a: x"},
          "runs": [E.ToolRun("afar", "original", "check=pass", 0,
                             xnack=0).to_dict(),
                   E.ToolRun("afar", "enter_exit_data", "check=pass", 0,
                             xnack=0).to_dict()]}
    return rec, x0


def test_copy_mode_runs_add_witnesses_to_a_copy_independent_program(
        monkeypatch):
    """For a copy-independent program the HSA_XNACK=0 runs are
    more runs of the same toolchains (metamorphic and probe witnesses,
    never a new source); the model still needs elision."""
    X = _tool()
    rec, x0 = _rec_x1_x0()
    monkeypatch.setattr(X.E, "copy_independent",
                        lambda s, v=52: E.Applicability(True))
    evs, v = X.evaluate_both(rec, x0)
    tags = {e.tag: e for e in evs}
    assert tags["metamorphic"].status == "value"
    assert tags["metamorphic"].witnesses == ("afar",)
    assert v.status == "provisional"  # catalog model counts only w/ elision
    rec["kind"] = "fuzz"
    assert X.evaluate_both(rec, x0)[1].status == "trusted"
    # a toolchain whose copy-mode value differs violates the relation
    x0["runs"][1]["value"] = "check=fail"
    evs, _ = X.evaluate_both(rec, x0)
    assert "violated" in {e.tag: e for e in evs}["metamorphic"].detail


def test_copy_mode_runs_stay_apart_for_a_copy_dependent_program(
        monkeypatch):
    X = _tool()
    rec, x0 = _rec_x1_x0()
    rec["kind"] = "fuzz"
    monkeypatch.setattr(X.E, "copy_independent",
                        lambda s, v=52: E.Applicability(False, ["maps"]))
    evs, v = X.evaluate_both(rec, x0)
    assert {e.tag: e for e in evs}["metamorphic"].status == "inapplicable"
    assert v.status == "provisional"
    assert X.evaluate_both(rec, None)[1].status == "provisional"


def test_probe_runs_of_both_modes_merge_per_toolchain(monkeypatch):
    X = _tool()
    rec, x0 = _rec_x1_x0()
    rec["variants"]["probe"] = "ok"
    x0["variants"]["probe"] = "ok"
    rec["runs"].append(E.ToolRun("afar", "probe", "check=pass", 0,
                                 True).to_dict())
    x0["runs"].append(E.ToolRun("afar", "probe", "check=pass", 0, False,
                                xnack=0).to_dict())
    monkeypatch.setattr(X.E, "copy_independent",
                        lambda s, v=52: E.Applicability(True))
    evs, _ = X.evaluate_both(rec, x0)
    assert {e.tag: e for e in evs}["probe"].status == "no_value"


def test_one_rewrite_in_two_modes_is_no_metamorphic_witness(monkeypatch):
    X = _tool()
    rec, x0 = _rec_x1_x0()
    rec["kind"] = "fuzz"
    rec["runs"] = [E.ToolRun("afar", "enter_exit_data", "check=pass",
                             0).to_dict()]
    x0["runs"] = [E.ToolRun("afar", "enter_exit_data", "check=pass", 0,
                            xnack=0).to_dict()]
    monkeypatch.setattr(X.E, "copy_independent",
                        lambda s, v=52: E.Applicability(True))
    evs, _ = X.evaluate_both(rec, x0)
    assert {e.tag: e for e in evs}["metamorphic"].status != "value"


def test_gfx90a_runs_are_more_runs_of_the_same_compilers(monkeypatch):
    """The gfx90a (Tioga) runs of a copy-independent program are
    additional runs of the same compilers: afar_g90 witnesses as afar,
    never as a new independent source."""
    X = _tool()
    rec, _ = _rec_x1_x0()
    monkeypatch.setattr(X.E, "copy_independent",
                        lambda s, v=52: E.Applicability(True))
    g90 = {"key": "52:p", "variants": {"enter_exit_data": "ok",
                                       "probe": "n/a: x"},
           "runs": [E.ToolRun("afar_g90", "original", "check=pass", 0,
                              xnack=0).to_dict(),
                    E.ToolRun("afar_g90", "enter_exit_data", "check=pass",
                              0, xnack=0).to_dict(),
                    E.ToolRun("cce19_g90", "original", "check=pass", 0,
                              xnack=0).to_dict()]}
    evs, v = X.evaluate_both(rec, None, g90)
    tags = {e.tag: e for e in evs}
    assert tags["metamorphic"].witnesses == ("afar",)
    assert set(tags["consensus_only"].witnesses) <= {"afar", "cce19"}
    rec["kind"] = "fuzz"
    _, x0 = _rec_x1_x0()
    assert X.evaluate_both(rec, x0, g90)[1].status == "trusted"
    # a gfx90a value that differs violates its compiler's relation
    g90["runs"][1]["value"] = "check=fail"
    evs, _ = X.evaluate_both(rec, None, g90)
    assert "violated" in {e.tag: e for e in evs}["metamorphic"].detail


def test_gfx90a_records_load_next_to_the_copy_mode_ones(tmp_path):
    import json
    X = _tool()
    p = tmp_path / "catalog.jsonl"
    (tmp_path / "catalog.g90.xnack0.jsonl").write_text(
        json.dumps({"key": "52:p", "runs": []}) + "\n")
    assert set(X._g90(p)) == {"52:p"}


def test_elided_run_sets_no_core_without_preexec_fn(monkeypatch):
    """A preexec_fn runs Python in the forked child; in a threaded
    parent (the sample tests' thread pools) that can deadlock before exec
    (it hung the suite twice). The core limit is set by the shell
    instead."""
    import subprocess as sp
    seen = []

    class R:
        returncode, stdout, stderr = 0, "RESULT ran_on_host=1 check=pass\n", ""

    def fake(cmd, **kw):
        seen.append((cmd, kw))
        return R()
    monkeypatch.setattr(E.subprocess, "run", fake)
    E.run_elided("program p\nend program p\n", "gfortran")
    run = seen[-1]
    assert "preexec_fn" not in run[1]
    assert run[0][:2] == ["bash", "-c"] and "ulimit -c 0" in run[0][2]


# --- Hand derivations and the triage of disputed verdicts ---------

DERIVED = """! Generated by compliance.gen (OpenMP 5.2, free-form Fortran). Do not edit.
! id: omp52-clause-x
! derivation (check=pass): x is 3 + (i - 1) on iteration i (5.2 §5.4.6 p.117),
! derivation: so b(i) = 2*i + 1 = ref(i); after the loop x = n + 3
program gen_prog
  print *, 'RESULT ran_on_host=0 check=pass'
end program gen_prog
"""


def test_derivation_evidence_reads_the_program_header():
    e = E.derivation_evidence(DERIVED)
    assert (e.tag, e.status, e.value) == ("derivation", "value", "check=pass")
    assert "5.2 §5.4.6 p.117" in e.detail and "after the loop" in e.detail
    assert E.derivation_evidence("program p\nend program p\n").status == \
        "no_value"
    # only the header counts: a comment in the body is no derivation
    body = "program p\n! derivation (check=pass): no\nend program p\n"
    assert E.derivation_evidence(body).status == "no_value"


def test_catalog_model_counts_with_a_derivation():
    assert "derivation" in E.INDEPENDENT
    assert "derivation" in E.CATALOG_MODEL_PARTNERS
    v = E.decide([E.model_evidence("check=pass"),
                  ev("derivation", "check=pass")],
                 model_partners=E.CATALOG_MODEL_PARTNERS)
    assert v.status == "trusted" and v.agreeing == ("derivation", "model")
    v = E.decide([E.model_evidence("check=pass"),
                  ev("derivation", "check=fail")],
                 model_partners=E.CATALOG_MODEL_PARTNERS)
    assert v.status == "disputed"


def _disputed_rec():
    return {"key": "52:p", "kind": "catalog", "version": 52, "program": "p",
            "model": "check=pass", "model_detail": "",
            "elision": E.Evidence("elision", "inapplicable",
                                  detail="x").to_dict(),
            "variants": {"enter_exit_data": "ok", "probe": "ok"},
            "runs": [E.ToolRun("afar", "original", "check=fail", 0).to_dict(),
                     E.ToolRun("afar", "enter_exit_data", "check=fail",
                               0).to_dict(),
                     E.ToolRun("afar", "probe", "check=fail", 0,
                               probe=True).to_dict()]}


def test_triage_withdraws_the_witnesses_a_finding_shows_wrong():
    X = _tool()
    rec = _disputed_rec()
    assert X.evaluate(rec)[1].status == "disputed"
    tri = {"disposition": "compiler_wrong", "withdraw": ["afar"],
           "finding": "data/findings/x.f90"}
    evs, v = X.evaluate(rec, triage=tri, derivation=ev("derivation",
                                                       "check=pass"),
                        matrix_ok=lambda *a: True)
    assert v.status == "trusted" and v.value == "check=pass"
    assert {e.tag: e.status for e in evs}["metamorphic"] != "value"
    # without the withdrawal the toolchain's stable wrong value disputes
    v = X.evaluate(rec, derivation=ev("derivation", "check=pass"))[1]
    assert v.status == "disputed"


def test_triage_implementation_defined_is_no_support_verdict():
    X = _tool()
    tri = {"disposition": "implementation_defined",
           "quote": "the size of the chunks is unspecified"}
    v = X.evaluate(_disputed_rec(), triage=tri)[1]
    assert v.status == "implementation_defined"
    assert "unspecified" in v.reason
    assert "implementation_defined" in E.VERDICTS


def test_committed_triage_entries_are_complete():
    """catalog/expected_triage.yaml: every entry names a known disposition
    and a spec citation; compiler_wrong needs a finding file that exists and
    the toolchains it withdraws; implementation_defined quotes the spec."""
    X = _tool()
    tri = X.load_triage()
    assert tri, "Records its dispositions"
    for (v, pid), t in tri.items():
        assert t["disposition"] in X.TRIAGE_DISPOSITIONS, pid
        assert re.search(r"§[\d.]+.*p\.\s*\d+", t["cite"]), pid
        if t["disposition"] == "compiler_wrong":
            assert (ROOT / t["finding"]).is_file(), pid
            assert t["withdraw"], pid
        if t["disposition"] == "implementation_defined":
            assert t["quote"], pid


def test_triage_withdraws_exactly_the_toolchains_of_its_finding():
    """A compiler_wrong entry withdraws the toolchains
    its finding names (data/findings/index.yaml), no fewer (a CCE 20/21
    witness printing the expected value would otherwise count) and no
    more (withdrawal only with a finding)."""
    import yaml
    X = _tool()
    idx = {e["file"]: e for e in yaml.safe_load(
        (ROOT / "data" / "findings" / "index.yaml").read_text())["findings"]}
    for (v, pid), t in X.load_triage().items():
        if t["disposition"] != "compiler_wrong":
            continue
        f = idx[t["finding"].removeprefix("data/findings/")]
        # `also_findings` names the findings of the
        # other withdrawn toolchains (CCE's bind(thread) failures are the
        # guarded-loop finding's); withdrawal still needs a finding
        tcs = set(f["toolchains"])
        for g in t.get("also_findings") or ():
            tcs |= set(idx[g.removeprefix("data/findings/")]["toolchains"])
        assert sorted(t["withdraw"]) == sorted(tcs), pid


def test_triage_states_why_a_compiler_wrong_program_stays_needs_human():
    """The 5.0 compiler_wrong programs (no C port, every
    compiler withdrawn: no executed witness) carry a stated needs_human
    reason; the report and the confirmer's reason show it."""
    X = _tool()
    tri = X.load_triage()
    for pid in ("omp50-clause-schedule", "omp50-clause-schedule-static",
                "omp50-clause-schedule-chunk_size",
                "omp50-clause-bind-thread"):
        assert "no executed witness" in tri[(50, pid)]["needs_human"], pid
    for (v, pid), t in tri.items():
        if v != 50:
            assert "needs_human" not in t, pid


def test_trusted_needs_an_executed_witness():
    """A verdict is trusted only
    with a positive executed witness besides the two agreeing sources: a
    run that printed the value on the device (any compiler, GPU, memory
    mode; withdrawn runs excluded), the sequential elision, or a correct
    run of the program or its C port in the matrix. Oracle + derivation
    alone is `derived`."""
    X = _tool()
    assert "derived" in E.VERDICTS
    rec = _disputed_rec()
    tri = {"disposition": "compiler_wrong", "withdraw": ["afar"],
           "finding": "data/findings/x.f90", "cite": "5.2 §1 p.1"}
    der = ev("derivation", "check=pass")
    v = X.evaluate(rec, triage=tri, derivation=der,
                   matrix_ok=lambda *a: False)[1]
    assert v.status == "derived" and "no executed witness" in v.reason
    v = X.evaluate(rec, triage=tri, derivation=der,
                   matrix_ok=lambda *a: True)[1]
    assert v.status == "trusted"
    # an executed run with the value is a witness by itself
    rec2 = _disputed_rec()
    rec2["runs"].append(E.ToolRun("cce19", "original", "check=pass",
                                  0).to_dict())
    v = X.evaluate(rec2, triage=tri, derivation=der,
                   matrix_ok=lambda *a: False)[1]
    assert v.status == "trusted"


def test_witness_mode_and_withdrawal():
    """For a copy-dependent
    program the executed witness must come from the verdict's memory mode
    (the copy-mode verdict: HSA_XNACK=0 rows, MI300A X0 and gfx90a); a
    withdrawn compiler's matrix row is no witness."""
    X = _tool()
    rows = {("52", "omp52-c-p", "afar", 1)}
    have = frozenset((int(v), p, t, x) for v, p, t, x in rows)
    rec = {"version": 52, "program": "omp52-p"}
    # X1-only witness: counts for a copy-independent verdict or the main
    # (X1) verdict, not for the copy-mode verdict of a copy-dependent one
    assert X.matrix_witness(rec, None, (), have)
    assert X.matrix_witness(rec, 1, (), have)
    assert not X.matrix_witness(rec, 0, (), have)
    # the withdrawal names Fortran compilers: the C port's row stays a
    # witness, the program's own row of a withdrawn compiler does not
    assert X.matrix_witness(rec, None, ("afar",), have)
    own = frozenset({(52, "omp52-p", "afar", 1)})
    assert X.matrix_witness(rec, None, (), own)
    assert not X.matrix_witness(rec, None, ("afar",), own)
    g90 = frozenset({(52, "omp52-p", "afar_g90", 0)})
    assert X.matrix_witness(rec, 0, (), g90)
    assert not X.matrix_witness(rec, 0, ("afar",), g90)
    # GCC is never a witness, nor a twin whose rows are support-table cells only
    for t in ("gcc", "gcc_g90", "afar_mi300x"):
        assert not X.matrix_witness(rec, None, (), frozenset({(52, "omp52-p", t, 0)})), t
    # evaluate passes the mode: copy mode of a copy-dependent record
    seen = []
    tri = {"disposition": "compiler_wrong", "withdraw": ["afar"],
           "finding": "data/findings/x.f90", "cite": "5.2 §1 p.1"}
    der = ev("derivation", "check=pass")
    X.evaluate(_disputed_rec(), mode=_disputed_rec(), triage=tri,
               derivation=der, copy_dependent=True,
               matrix_ok=lambda r, x, g: seen.append((x, tuple(g))) or False)
    assert seen == [(0, ("afar",))]
    seen.clear()
    X.evaluate(_disputed_rec(), triage=tri, derivation=der,
               copy_dependent=False,
               matrix_ok=lambda r, x, g: seen.append((x, tuple(g))) or False)
    assert seen == [(None, ("afar",))]


def test_nvhpc_runs_are_another_compiler_family(monkeypatch):
    """NVHPC's separate-memory runs of a copy-independent catalog
    program join its evidence under their own toolchain, another family:
    a metamorphic witness of its own (unlike a gfx90a twin)."""
    X = _tool()
    rec, _ = _rec_x1_x0()
    monkeypatch.setattr(X.E, "copy_independent",
                        lambda s, v=52: E.Applicability(True))
    nv = {"key": "52:p", "variants": {"enter_exit_data": "ok",
                                      "probe": "n/a: x"},
          "runs": [E.ToolRun("nvhpc", "original", "check=pass", 0,
                             xnack=0).to_dict(),
                   E.ToolRun("nvhpc", "enter_exit_data", "check=pass", 0,
                             xnack=0).to_dict()]}
    evs, _ = X.evaluate_both(rec, None, None, nv)
    tags = {e.tag: e for e in evs}
    assert "nvhpc" in tags["metamorphic"].witnesses
    # nothing to look up for a record without an NVHPC run
    monkeypatch.setattr(X, "nv_of", lambda r: None)
    evs2, _ = X.evaluate_both(rec, None, None)
    assert "nvhpc" not in {e.tag: e for e in evs2}["metamorphic"].witnesses


# ---- The pre-run legality and race check (offload.engine.prerun) -----------------------------------------



from offload.engine import prerun as PR

FRESH = ROOT / "data" / "bench" / "fresh"
DRAFTS = ROOT / "data" / "reports" / "fresh-drafts"


def rules(text: str, lang: str = "f90"):
    return PR.rules_witness((text, lang))


def test_old_stress_lin_race_refused():
    from offload.engine import stress as S
    p = S.build("clauses", 8, 1)
    assert "private(tp, lin)" in p.source
    ok, why = PR.rules_witness(p)
    assert ok, why                          # the fixed generator: no race
    old = [(n, t.replace("private(tp, lin)", "private(tp)"))
           for n, t in p.files]

    class Old:
        files, lang, model = old, p.lang, p.model
    ok, why = PR.rules_witness(Old)
    assert not ok
    assert any(w.startswith("race:") and " lin is written" in w
               for w in why), why
    ok, why = PR.check(Old, frontend=False)
    assert not ok


@pytest.mark.parametrize("name,lang,rule", [
    ("fresh-042.c", "c", "uses-allocators-traits-constant"),
    ("fresh-042.c", "c", "alloc-in-target-predefined"),
    ("fresh-070.f90", "f90", "declare-target-module-variable"),
    ("fresh-076.f90", "f90", "acc-loop-reduction-data-clause"),
])
@pytest.mark.needs_bench("fresh/cases.yaml")
def test_non_conforming_fresh_programs_refused(name, lang, rule):
    ok, why = rules((FRESH / name).read_text(), lang)
    assert ok is False, why
    assert any(w.startswith(f"restriction: {rule}:") for w in why), why
    ok, _ = PR.check(((FRESH / name).read_text(), lang), frontend=False)
    assert not ok


@pytest.mark.parametrize("name,lang", [("d042-dyn.c", "c"),
                                       ("d070-declare.f90", "f90"),
                                       ("d076-copy.f90", "f90")])
def test_their_conforming_forms_pass_the_rules(name, lang):
    ok, why = rules((DRAFTS / name).read_text(), lang)
    assert ok, why


LOOP_UPDATE = """program p
  implicit none
  integer :: i
  real(8) :: a(100), s
  a = 1.0d0
  s = 0.0d0
  !$omp target teams loop map(to: a) map(tofrom: s)
  do i = 1, 100
    s = s + a(i)
  end do
  print *, s
end program p
"""

LOOP_UPDATE_NESTED = """program p
  implicit none
  integer :: i
  real(8) :: a(100), s
  a = 1.0d0
  s = 0.0d0
  !$omp target teams map(to: a) map(tofrom: s)
  !$omp loop
  do i = 1, 100
    s = s + a(i)
  end do
  !$omp end target teams
  print *, s
end program p
"""

LOOP_UPDATE_C = """#include <stdio.h>
int main(void) {
  double a[100], s = 0.0;
  for (int i = 0; i < 100; i++) a[i] = 1.0;
#pragma omp target teams loop map(to: a) map(tofrom: s)
  for (int i = 0; i < 100; i++)
    s += a[i];
  printf("%f\\n", s);
  return 0;
}
"""


@pytest.mark.parametrize("text,lang", [(LOOP_UPDATE, "f90"),
                                       (LOOP_UPDATE_NESTED, "f90"),
                                       (LOOP_UPDATE_C, "c")])
def test_unreduced_update_in_loop_refused(text, lang):
    ok, why = rules(text, lang)
    assert ok is False
    assert any(w.startswith("race:") and "s is updated" in w for w in why), \
        why
    # with the reduction it is legal
    fixed = text.replace("loop map(", "loop reduction(+: s) map(") if \
        "teams loop" in text else text.replace("!$omp loop",
                                               "!$omp loop reduction(+: s)")
    ok, why = rules(fixed, lang)
    assert ok, why


def test_distribute_across_teams_shared_scalar_refused():
    text = LOOP_UPDATE.replace("teams loop", "teams distribute")
    ok, why = rules(text)
    assert ok is False and any("s is updated" in w for w in why)


def test_protected_and_private_writes_pass():
    atomic = LOOP_UPDATE.replace("    s = s + a(i)",
                                 "    !$omp atomic update\n    s = s + a(i)"
                                 ).replace("teams loop", "teams distribute "
                                           "parallel do")
    ok, why = rules(atomic)
    assert ok, why
    private = LOOP_UPDATE.replace("map(tofrom: s)", "private(t)").replace(
        "real(8) :: a(100), s", "real(8) :: a(100), s, t").replace(
        "    s = s + a(i)", "    t = a(i)\n    a(i) = t * 2")
    ok, why = rules(private)
    assert ok, why


def test_one_witness_is_not_enough():
    ok, why = PR.check((LOOP_UPDATE.replace("loop map(", "loop reduction("
                                            "+: s) map("), "f90"),
                       frontend=False)
    assert not ok
    assert any("witness unavailable" in w for w in why)


@pytest.mark.gpu
def test_two_witnesses_accept_a_legal_program():
    from offload.engine.toolchains import AFAR_BIN
    if not Path(f"{AFAR_BIN}/amdflang").exists():
        pytest.skip("no AFAR front end here")
    ok, why = PR.check((LOOP_UPDATE.replace("loop map(", "loop reduction("
                                            "+: s) map("), "f90"))
    assert ok, why
    ok, why = PR.check((LOOP_UPDATE, "f90"))
    assert not ok


@pytest.mark.gpu
def test_witnesses_disagree_go_to_review():
    """offload.engine.rules rejects the race, the front end accepts it: the
    program is refused, and the reasons say the witnesses disagree."""
    from offload.engine.toolchains import AFAR_BIN
    if not Path(f"{AFAR_BIN}/amdflang").exists():
        pytest.skip("no AFAR front end here")
    ok, why = PR.check((LOOP_UPDATE, "f90"))
    assert not ok and any("witnesses disagree" in w for w in why), why


def test_a_guarded_write_of_one_iteration_is_not_a_race():
    """`if (i == 1) x = ...` may be one iteration's write: not reported;
    an update under an IF still is."""
    one = LOOP_UPDATE.replace("    s = s + a(i)", "    if (i == 1) t = a(i)"
                              ).replace("real(8) :: a(100), s",
                                        "real(8) :: a(100), s, t")
    ok, why = rules(one)
    assert ok, why
    upd = LOOP_UPDATE.replace("    s = s + a(i)",
                              "    if (a(i) > 0) s = s + a(i)")
    ok, why = rules(upd)
    assert ok is False and any("s is updated" in w for w in why)
    blk = LOOP_UPDATE.replace("    s = s + a(i)",
                              "    if (i == 100) then\n      t = a(i)\n"
                              "    end if").replace(
        "real(8) :: a(100), s", "real(8) :: a(100), s, t")
    ok, why = rules(blk)
    assert ok, why
    c = LOOP_UPDATE_C.replace("    s += a[i];",
                              "    if (i == 0) { t = a[i]; }").replace(
        "double a[100], s = 0.0;", "double a[100], s = 0.0, t = 0.0;")
    ok, why = rules(c, "c")
    assert ok, why


def test_fuzz_runner_never_compiles_a_refused_program(monkeypatch):
    from offload.engine import fuzz_exec as FX
    from offload.engine.fuzz import CheckResult
    monkeypatch.setattr(FX, "check", lambda *a, **k: CheckResult("ok"))
    monkeypatch.setattr(FX, "stored_check", lambda prog: None)
    monkeypatch.setattr(PR, "check", lambda prog: (False, ["race: s"]))

    def boom(*a, **k):
        raise AssertionError("compiled a refused program")
    monkeypatch.setattr(FX, "run_toolchain", boom)
    pr = FX.run_program(3, toolchains=("afar",))
    assert pr.check == "prerun" and "race: s" in pr.check_detail
    assert pr.results == {}


def test_stress_runner_never_compiles_a_refused_program(monkeypatch):
    import importlib.util
    import json
    spec = importlib.util.spec_from_file_location(
        "stress_cli", ROOT / "tools" / "campaigns" / "stress.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    from offload.engine import stress_exec as X
    monkeypatch.setattr(PR, "check", lambda prog: (False, ["race: lin"]))
    monkeypatch.delenv("COMPLIANT_PRERUN_STORED", raising=False)

    def boom(*a, **k):
        raise AssertionError("compiled a refused program")
    monkeypatch.setattr(X, "execute", boom)
    out = cli.run_task(({"axis": "clauses", "size": 8, "model": "omp",
                         "layout": "single", "seed": 1}, "afar", (1, 0),
                        "O2", {"compile_s": 900, "mem_gib": 32,
                               "run_s": 120}))
    rows = [json.loads(x) for x in out.splitlines()]
    assert [r["cls"] for r in rows] == ["prerun_refused"] * 2
    assert all("race: lin" in r["reason"] for r in rows)


@pytest.mark.gpu
def test_openacc_programs_reach_the_front_end_through_a_stub_module():
    """AFAR flang has no openacc.mod: the check gives it a declarations-
    only stub with the API names the program uses, so an OpenACC program
    is judged by its directives, not refused for a missing module."""
    from offload.engine.toolchains import AFAR_BIN
    if not Path(f"{AFAR_BIN}/amdflang").exists():
        pytest.skip("no AFAR front end here")
    from offload.engine import stress as S
    p = S.build("scalars.declare", 20, 1, "acc")
    ok, why = PR.frontend_witness(p)
    assert ok is True, why
    stub = PR.openacc_stub(["if (acc_on_device(acc_device_not_host)) x=1"])
    assert "logical, external :: acc_on_device" in stub
    assert "acc_device_not_host = 0" in stub


ARRAY = """program p
  implicit none
  integer, parameter :: n = 100
  integer :: i, k
  real(8) :: a(n), b(n), c(2*n)
  a = 0.0d0
  b = 1.0d0
  !$omp target teams distribute parallel do map(tofrom: a, c) map(to: b)
  do i = 2, n
    BODY
  end do
  print *, a(1)
end program p
"""


@pytest.mark.parametrize("body,race", [
    ("a(1) = a(1) + b(i)", "the subscript depends on no loop variable"),
    ("a(i) = a(i-1) + b(i)", "a loop-carried dependence"),
    ("a(i) = b(i) * 2.0d0", None),
    ("k = 2*i\n    c(k) = b(i)", None),
    ("if (i == 2) a(1) = b(i)", None),
])
def test_array_races(body, race):
    """Fix: an element every iteration writes, and a
    loop-carried dependence through an array, are races."""
    src = ARRAY.replace("BODY", body)
    if "k = 2*i" in body:
        src = src.replace("map(to: b)", "map(to: b) private(k)")
    ok, why = rules(src)
    if race is None:
        assert ok, why
    else:
        assert ok is False and any(race in w for w in why), why


CLAIM = """program p
  implicit none
  integer, parameter :: n = 100
  integer :: i, cnt, slot
  type t
    integer :: loc(3)
  end type t
  type(t) :: recs(n)
  cnt = 0
  !$omp target teams distribute parallel do map(tofrom: cnt, recs) private(slot)
  do i = 1, n
    CLAIMBLOCK
    recs(slot)%loc(1) = i
  end do
  print *, cnt
end program p
"""


CAP = "!$omp atomic capture\n    cnt = cnt + 1\n    slot = cnt\n    !$omp end atomic"


@pytest.mark.parametrize("block,extra,ok", [
    # a slot taken by an atomic capture of a counter that goes up by a
    # constant is unique to the iteration (OpenMP 5.2 15.8.4: the atomic
    # regions on x are mutually exclusive): no race
    (CAP, "", True),
    ("!$omp atomic capture\n    slot = cnt\n    cnt = cnt + 1\n"
     "    !$omp end atomic\n    slot = slot + 1", "", True),
    # another atomic update of the counter with a positive constant step keeps the values distinct
    ("!$omp atomic update\n    cnt = cnt + 2\n" + CAP, "", True),
    # the step depends on the iteration: the captured values may repeat
    ("!$omp atomic capture\n    cnt = cnt + mod(i, 2)\n    slot = cnt\n"
     "    !$omp end atomic", "", False),
    # no capture: slot is some constant, every iteration writes recs(slot)
    ("slot = 3", "", False),
    # A step of 0 hands every iteration the same value
    ("!$omp atomic capture\n    cnt = cnt + 0\n    slot = cnt\n    !$omp end atomic", "", False),
    ("!$omp atomic capture\n    slot = cnt\n    cnt = cnt + 0\n    !$omp end atomic", "", False),
    # a reduction or firstprivate counter is a different variable in every thread
    (CAP, " reduction(+: cnt)", False),
    (CAP, " firstprivate(cnt)", False),
    # the counter is written by something other than a positive constant step
    ("!$omp atomic write\n    cnt = 0\n" + CAP, "", False),
    ("cnt = 0\n    " + CAP, "", False),
    (CAP + "\n    !$omp atomic write\n    cnt = 0", "", False),
])
def test_slot_claimed_by_atomic_capture_is_not_a_race(block, extra, ok):
    got, why = rules(CLAIM.replace("CLAIMBLOCK", block).replace("private(slot)", "private(slot)" + extra))
    race = [w for w in why if "depends on no loop variable" in w]
    if ok:
        assert got and not race, why
    else:
        assert got is False and race, why


CLAIM_C = """#include <stdio.h>
int main(void) {
  int g[200];
  int cnt[1] = {0};
#pragma omp target teams distribute parallel for map(tofrom: cnt[0:1], g[0:200])
  for (int i = 0; i < 100; i++) {
    int v;
    CLAIMC
    int pad = 0;    /* the rule takes the statement after an atomic block as protected by it */
    g[v] = i;
  }
  printf("%d\\n", cnt[0]);
  return 0;
}
"""

CLAIM_C_SCALAR = CLAIM_C.replace("int cnt[1] = {0};", "int cnt = 0;").replace(
    "map(tofrom: cnt[0:1], g[0:200])", "map(tofrom: cnt, g[0:200])EXTRA").replace(
    'printf("%d\\n", cnt[0]);', 'printf("%d\\n", cnt);')


@pytest.mark.parametrize("block,ok", [
    ("#pragma omp atomic capture\n    { v = cnt[0]; cnt[0] += 1; }", True),
    ("#pragma omp atomic capture\n    { cnt[0] += 1; v = cnt[0]; }", True),
    ("#pragma omp atomic capture\n    v = cnt[0]++;", True),
    # No negative case existed for C
    ("#pragma omp atomic capture\n    { v = cnt[0]; cnt[0] += 0; }", False),
    ("#pragma omp atomic capture\n    { cnt[0] += 0; v = cnt[0]; }", False),
    ("cnt[0] = 0;\n    #pragma omp atomic capture\n    { v = cnt[0]; cnt[0] += 1; }", False),
    ("#pragma omp atomic write\n    cnt[0] = 0;\n    #pragma omp atomic capture\n    v = cnt[0]++;", False),
    ("v = 3;", False),                    # no capture: every iteration writes g[3]
])
def test_slot_claimed_by_atomic_capture_is_not_a_race_c(block, ok):
    got, why = PR.rules_witness((CLAIM_C.replace("CLAIMC", block), "c"))
    race = [w for w in why if "depends on no loop variable" in w]
    assert (not race) if ok else race, why


@pytest.mark.parametrize("extra,ok", [
    ("", True),
    (" reduction(+: cnt)", False),
    (" firstprivate(cnt)", False),
])
def test_slot_claimed_by_atomic_capture_needs_a_shared_counter_c(extra, ok):
    src = CLAIM_C_SCALAR.replace("CLAIMC", "#pragma omp atomic capture\n    { v = cnt; cnt += 1; }").replace(
        "EXTRA", extra)
    got, why = PR.rules_witness((src, "c"))
    race = [w for w in why if "depends on no loop variable" in w]
    assert (not race) if ok else race, why


ALIAS_C = """#include <stdio.h>
int main(void) {
  double a[100], *p = a;
  for (int i = 0; i < 100; i++) a[i] = i;
#pragma omp target teams distribute parallel for map(tofrom: a[0:100])
  for (int i = 1; i < 100; i++)
    p[i] = a[i - 1] + 1.0;
  printf("%f\\n", a[99]);
  return 0;
}
"""

ALIAS_F = """program p
  implicit none
  integer :: i
  real(8), target :: a(100)
  real(8), pointer :: q(:)
  a = 1.0d0
  q => a
  !$omp target teams distribute parallel do map(tofrom: a)
  do i = 1, 99
    q(i) = a(i+1) + 1.0d0
  end do
  print *, a(1)
end program p
"""


@pytest.mark.parametrize("text,lang", [(ALIAS_C, "c"), (ALIAS_F, "f90")])
def test_a_race_through_aliasing(text, lang):
    """An array written through a pointer to it and
    read under its own name at another subscript."""
    ok, why = rules(text, lang)
    assert ok is False and any("alias" in w for w in why), why
    fixed = text.replace("a[i - 1]", "a[i]").replace("a(i+1)", "a(i)")
    ok, why = rules(fixed, lang)
    assert ok, why


def test_a_front_end_only_refusal_is_a_candidate_afar_defect(monkeypatch):
    """The rules accept, the AFAR front end alone refuses: the
    program is refused (two witnesses), but never silently: the reasons
    carry FRONTEND_ONLY and the reports count it as a candidate AFAR
    front-end defect."""
    from offload.engine import fuzz_report as FR
    from offload.engine import stress_report as SR
    ok_src = LOOP_UPDATE.replace("map(tofrom: s)",
                                 "map(tofrom: s) reduction(+: s)")
    assert rules(ok_src)[0], rules(ok_src)
    monkeypatch.setattr(PR, "frontend_witness", lambda p, t=600: (
        False, ["frontend: amdflang: error: something it should accept"]))
    ok, why = PR.check((ok_src, "f90"))
    assert not ok and PR.FRONTEND_ONLY in why
    assert PR.refusal_kind(why) == "frontend_only"
    assert "candidate AFAR front-end defect" in FR.reject_cause(
        "prerun", "; ".join(why))
    rows = [{"id": "kernels-omp-4-1-partition", "cls": "prerun_refused",
             "layout": "partition", "reason": "; ".join(why)},
            {"id": "kernels-omp-4-2-partition", "cls": "prerun_refused",
             "layout": "partition",
             "reason": "rules: cannot read it: ProgramError: x; witness "
             "unavailable: legality needs two witnesses"}]
    got = SR.prerun_refusals(rows)
    assert got == {("frontend_only", "partition"):
                   ["kernels-omp-4-1-partition"],
                   ("unreadable", "partition"):
                   ["kernels-omp-4-2-partition"]}


def test_c_openacc_reads_a_stub_openacc_h():
    """The C OpenACC witnesses read a
    declarations-only openacc.h (AFAR's amdclang has none)."""
    src = ("#include <openacc.h>\n#include <stdio.h>\nint main(void) {\n"
           "  int on = 0;\n#pragma acc parallel copyout(on)\n"
           "  on = acc_on_device(acc_device_not_host);\n"
           "  printf(\"%d\\n\", on);\n  return 0;\n}\n")
    files, lang, model, _ = PR._files_of((src, "c", "acc"))
    assert "#include <openacc.h>" not in files[0][1]
    assert "acc_device_not_host = 3" in files[0][1]
    files, *_ = PR._files_of((src.replace("acc", "omp"), "c", "omp"))
    assert "typedef enum" not in files[0][1]


def test_an_inner_loop_bounded_by_the_iteration_is_no_race():
    """The catalog's nowait-hostdev form: each outer iteration writes its
    own range through an inner loop whose bounds depend on it; an inner
    loop with constant bounds writes the same range in every iteration."""
    own = ARRAY.replace("BODY", "do k = (i-1)*2 + 1, i*2\n      c(k) = b(i)\n"
                        "    end do").replace("map(to: b)",
                                             "map(to: b) private(k)")
    ok, why = rules(own)
    assert ok, why
    every = ARRAY.replace("BODY", "do k = 1, n\n      c(k) = b(i)\n"
                          "    end do").replace("map(to: b)",
                                               "map(to: b) private(k)")
    ok, why = rules(every)
    assert ok is False and any("depends on no loop variable" in w
                               for w in why), why


def test_fortran_target_region_with_a_clause_ends_at_its_end_directive():
    # `target map(...)` was read as a construct named "target
    # map", whose end directive never comes: the region ran to the end of
    # the file, and a module procedure after it that reads a module
    # variable was refused (declare-target-module-variable)
    src = """program p
  implicit none
  integer :: x
  x = 0
!$omp target map(tofrom: x)
  x = 1
!$omp end target
  print *, x
end program p
module m
  integer :: v
contains
  subroutine s()
    v = 1
    call t(v)
  end subroutine
end module m
"""
    dirs = PR._directives(src, "f90", "omp")
    assert PR._regions(src, "f90", dirs, "target") == [(5, 7)]
    assert PR.extra(src, "f90") == []
    assert PR._construct_name("target teams map(to: a)") == ["target",
                                                             "teams"]
    assert PR._construct_name("parallel copy(a)") == ["parallel"]
