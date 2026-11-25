"""The MFC-pattern generators (offload.engine.fuzz_mfc): programs in the shapes of MFC's generated
OpenMP and OpenACC builds, deterministic per seed, within Fortran's line length, accepted by the
rules engine, with the model's checksum in their header."""
import re

import pytest

from offload.engine import fuzz, fuzz_mfc as M


@pytest.mark.parametrize("version", (M.GEN, M.GEN_ACC))
def test_a_seed_gives_one_program_in_mfcs_patterns(version):
    a, b = fuzz.generate(7, version), fuzz.generate(7, version)
    assert a.source == b.source and a.expected == b.expected and a.gen_version == version
    s = a.source
    assert "type(scalar_field), allocatable :: vf(:)" in s and "%vf(i)%sf(j, k, l)" in s
    if version == M.GEN:
        assert a.model == "omp" and "defaultmap(present:allocatable)" in s and "declare target (qa, qb)" in s
        assert "target enter data map(always,alloc:qa%vf(i)%sf)" in s
    else:
        assert a.model == "acc" and fuzz.is_acc(s) and "default(present)" in s and "declare create(qa, qb)" in s
        assert "routine seq" in s and "enter data create(qa%vf(i)%sf)" in s
    assert f"! expected checksum: {a.expected}" in s and fuzz.is_mfc(s)


def test_every_line_fits_fortrans_free_form_limit():
    for seed in range(1, 120):
        for v in M.VERSIONS:
            assert all(len(x) <= 132 for x in fuzz.generate(seed, v).source.splitlines()), (seed, v)


def test_the_rules_engine_accepts_the_programs():
    from offload.engine import prerun
    for seed in range(1, 40):
        for v in M.VERSIONS:
            p = fuzz.generate(seed, v)
            ok, why = prerun.rules_witness((p.source, "f90", p.model))
            assert ok, (seed, v, why)


def test_the_features_name_mfcs_patterns():
    feats = set().union(*(fuzz.generate(s, M.GEN).features for s in range(1, 60)))
    assert {"mfc:collapse3", "mfc:collapse4", "mfc:atomic", "mfc:routine", "mfc:neighbour",
            "mfc:seq-equations", "mfc:private-array"} <= feats


def test_a_front_end_refusal_the_specification_contradicts_is_no_legality_evidence(monkeypatch):
    """AFAR flang refuses a second defaultmap clause of another category; OpenMP 5.2 §5.8.7 allows
    one per category (MFC's kernels carry four), so that refusal does not keep a program from the
    compilers. Any other refusal still does."""
    from offload.engine import flang_oracle as FO
    msg = "t.f90:70:10: error: At most one DEFAULTMAP clause can appear on TARGET TEAMS DISTRIBUTE PARALLEL DO directive"

    def refuse(*a, **k):
        raise FO.FlangError("semantics", msg)
    monkeypatch.setattr(FO, "_dump", refuse)
    assert fuzz.check_flang("program p\nend program p\n") is None

    def other(*a, **k):
        raise FO.FlangError("semantics", msg + "\nt.f90:9:3: error: something else is wrong")
    monkeypatch.setattr(FO, "_dump", other)
    assert "something else" in fuzz.check_flang("program p\nend program p\n")


def test_the_campaigns_front_end_witness_passes_a_refusal_the_specification_contradicts(monkeypatch):
    from types import SimpleNamespace
    from offload.engine import harness, prerun
    out = "prog.f90:70:10: error: At most one DEFAULTMAP clause can appear on TARGET TEAMS DISTRIBUTE PARALLEL DO directive\n"
    monkeypatch.setattr(harness, "_execute", lambda *a, **k: SimpleNamespace(rc=1, stdout=out, timed_out=False))
    import pathlib
    monkeypatch.setattr(pathlib.Path, "exists", lambda self: True)
    ok, why = prerun.frontend_witness((fuzz.generate(1, M.GEN).source, "f90", "omp"))
    assert ok is True, why
    monkeypatch.setattr(harness, "_execute", lambda *a, **k: SimpleNamespace(rc=1, stdout=out + "prog.f90:9:1: error: bad\n",
                                                                              timed_out=False))
    ok, why = prerun.frontend_witness((fuzz.generate(1, M.GEN).source, "f90", "omp"))
    assert ok is False and "bad" in why[0]


@pytest.mark.parametrize("version", (M.GEN2, M.GEN2_ACC))
def test_a_swarm_program_switches_on_its_own_subset_of_the_patterns(version):
    """fuzz-mfc2 and fuzz-mfcacc2: each program draws its shape, residency, clause list and routine
    form (and the rates of the other patterns), so no one pattern is in every program."""
    progs = [fuzz.generate(s, version) for s in range(1, 120)]
    assert fuzz.generate(5, version).source == progs[4].source
    for key, values in M.SWARM.items():
        got = {v for p in progs for v in values if f"mfc2:{key}={v}" in p.features}
        assert got == set(values), (key, got)
    assert any("mfc:atomic" in p.features for p in progs) and any("mfc:atomic" not in p.features for p in progs)
    assert all(len(x) <= 132 for p in progs for x in p.source.splitlines())


def test_a_scalar_updated_atomically_without_a_declare_directive_has_a_data_clause():
    """OpenACC 3.4 §2.6.2: a scalar with no visible data clause is firstprivate in a parallel
    construct; OpenMP: a scalar is firstprivate in a target construct. A kernel that updates tot
    atomically names it in a data clause unless a declare directive makes it device data."""
    for v, clause in ((M.GEN2, "map(tofrom: tot)"), (M.GEN2_ACC, "copy(tot)")):
        for s in range(1, 150):
            p = fuzz.generate(s, v)
            if "mfc:atomic" in p.features and "mfc2:residency=declare" not in p.features:
                assert clause in p.source, (v, s)


def test_the_rules_engine_accepts_the_swarm_programs():
    from offload.engine import prerun
    for seed in range(1, 40):
        for v in (M.GEN2, M.GEN2_ACC):
            p = fuzz.generate(seed, v)
            ok, why = prerun.rules_witness((p.source, "f90", p.model))
            assert ok, (seed, v, why)


@pytest.mark.parametrize("version", ("fuzz-app1", "fuzz-appacc1"))
def test_a_profile_swarm_program_carries_its_code_base_and_the_rules_accept_it(version):
    """fuzz-app1 and fuzz-appacc1: each program picks a code base of catalog/fuzz_profile.json and
    draws the swarm with its weights; the code base is a feature, and the rules engine accepts the
    programs (a teams loop kernel has no atomic: OpenMP 5.2 §11.7)."""
    from offload.engine import prerun
    progs = [fuzz.generate(s, version) for s in range(1, 80)]
    codes = {f for p in progs for f in p.features if f.startswith("app:")}
    assert len(codes) >= 8 and all(sum(f.startswith("app:") for f in p.features) == 1 for p in progs)
    assert all(fuzz.is_mfc(p.source) and p.gen_version == version for p in progs)
    for p in progs[:40]:
        ok, why = prerun.rules_witness((p.source, "f90", p.model))
        assert ok, (p.seed, why)


def test_asynchronous_kernels_are_waited_for_before_the_host_reads_their_results():
    for v, wait in (("fuzz-app1", "!$omp taskwait"), ("fuzz-appacc1", "!$acc wait(1)")):
        for s in range(1, 200):
            p = fuzz.generate(s, v)
            if "mfc:async" in p.features:
                src = p.source
                assert wait in src.split("! fuzz: checksum", 1)[1].split("\n")[1], (v, s)


def test_the_elision_reads_a_generated_programs_module_variables():
    """A generated MFC or application program moves every module variable it reads on the host
    (update from, exit data) and the reducer keeps each copy-back, so the module-variable exclusion
    of the elision (separate host and device copies) does not apply to it; it still applies to any
    other program."""
    from offload.engine import expected as E
    p = fuzz.generate(3, M.GEN2)
    an = E._Analysis(p.source, 52)
    assert not any("module variables" in w for w in an.static_exclusions()[0])
    other = p.source.replace("! generator: fuzz-mfc2", "! generator: something-else")
    assert any("module variables" in w for w in E._Analysis(other, 52).static_exclusions()[0])


def test_a_generated_openacc_wrong_answer_is_reduced_against_the_elision():
    from offload.engine import leads as LD
    p = fuzz.generate(3, M.GEN2_ACC)
    f = LD.Failure("fuzz:r", "3", "cce19", "f90", "acc", "copy", "wrong_answer", "", p.source, 9, (), ("cce19",))
    assert not LD._elision_blind(f)


def test_the_model_counts_an_atomic_after_the_i_loop_once_a_point():
    """The atomic and the reduction follow the do i = 1, nv loop, so they run once a grid point with
    its last t2; the checksums are what the sequential build of each program printed."""
    from offload.engine import fuzz
    printed = {2: 1118808969, 3: 1577312487, 17: 1441722991, 20: 2051844923, 21: 744, 24: 646928778,
               28: 1605659929, 29: 664528584}
    assert {s: fuzz.generate(s, "fuzz-mfc2").expected for s in printed} == printed
