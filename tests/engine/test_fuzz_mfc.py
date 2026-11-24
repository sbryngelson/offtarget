"""The MFC-pattern generators (offload.engine.fuzz_mfc): programs in the shapes of MFC's generated
OpenMP and OpenACC builds, deterministic per seed, within Fortran's line length, accepted by the
rules engine, with the model's checksum in their header."""
import re

import pytest

from offload.engine import fuzz, fuzz_mfc as M


@pytest.mark.parametrize("version", M.VERSIONS)
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
