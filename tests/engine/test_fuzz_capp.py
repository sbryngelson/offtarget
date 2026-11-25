"""The C swarm generators (offload.engine.fuzz_capp): the fuzz-app1 swarm in C's forms of its data,
deterministic per seed, accepted by the rules engine, with OpenACC's pointer rule kept and the
model's checksum the elided C run's."""
import re
import shutil

import pytest

from offload.engine import fuzz, fuzz_acc, fuzz_capp as C


@pytest.mark.parametrize("version", C.VERSIONS)
def test_a_seed_gives_one_c_program_the_rules_engine_accepts(version):
    for s in range(1, 41):
        p = fuzz.generate(s, version)
        assert p.source == fuzz.generate(s, version).source and p.lang == "c"
        assert p.model == ("acc" if version == C.GEN_ACC else "omp")
        assert fuzz.is_c(p.source) and fuzz.is_c_acc(p.source) == (version == C.GEN_ACC)
        assert f"// expected checksum: {p.expected}" in p.source and "lang:c" in p.features
        rules = fuzz_acc.check_rules_acc if version == C.GEN_ACC else fuzz.check_rules
        assert rules(p.source) is None, (s, rules(p.source))
        if version == C.GEN:
            assert fuzz.check_scope(p.source) is None, s


def test_every_shape_and_residency_is_drawn():
    seen = {f for s in range(1, 201) for v in C.VERSIONS for f in fuzz.generate(s, v).features}
    for shape in C.SHAPES:
        assert f"mfc2:shape={shape}" in seen
    for res in ("declare", "enter", "map"):
        assert f"mfc2:residency={res}" in seen
    # a structure is never given data clauses on the kernel (one clause list cannot name its levels)
    for s in range(1, 201):
        f = fuzz.generate(s, C.GEN).features
        assert not ({"mfc2:shape=nested", "mfc2:shape=flat"} & f and "mfc2:residency=map" in f), s


def test_the_c_text_of_an_expression_has_the_models_value():
    """C's / and % truncate toward zero like Fortran's, & | ^ are iand ior ieor, the ternary is merge."""
    e = fuzz.Intr("mod", (fuzz.Bin("-", fuzz.Var("j"), fuzz.Const(9)), fuzz.Const(4)))
    assert C.c(e) == "((j - 9) % 4)" and e.ev({"j": 2}, {}) == -3
    m = fuzz.Merge(fuzz.Var("a"), fuzz.Var("b"), fuzz.Cond("/=", fuzz.Var("a"), fuzz.Const(0)))
    assert C.c(m) == "(a != 0 ? a : b)"
    assert C.c(fuzz.Intr("max", (fuzz.Var("m"), fuzz.Var("nv")))) == "IMAX(M, NV)"
    assert C.c(C.CRef("nested", "qa", fuzz.Var("i"), (fuzz.Var("j"), fuzz.Var("k"), fuzz.Var("l")))) == \
        "qa.vf[i].sf[IX(j, k, l)]"


def test_an_openacc_pointer_shape_names_its_sections_on_every_kernel():
    """A C pointer is a scalar to OpenACC (3.4 §2.6.2: firstprivate in a parallel construct): a kernel
    over a pointer shape lists its sections in present (or a data clause), whatever the clause form."""
    n = 0
    for s in range(1, 120):
        p = fuzz.generate(s, C.GEN_ACC)
        if not {"mfc2:shape=plain", "mfc2:shape=flat"} & p.features:
            continue
        n += 1
        for ln in p.source.splitlines():
            if re.match(r"#pragma acc (parallel|kernels) loop", ln):
                assert re.search(r"\b(present|copyin|copy)\([^)]*\bqa\[0:", ln), (s, ln)
    assert n > 20


def test_updates_move_leaf_arrays_only():
    """An update of a level that holds pointers would overwrite the attached device pointers."""
    for s in range(1, 120):
        for v in C.VERSIONS:
            src = fuzz.generate(s, v).source
            for ln in src.splitlines():
                if re.match(r"#pragma (omp target update|acc update)", ln):
                    assert not re.search(r"\bq[ab](\.vf)?\[0:NV\]", ln), (v, s, ln)


@pytest.mark.skipif(shutil.which("gcc") is None, reason="needs gcc (the C base-language check)")
@pytest.mark.parametrize("version", C.VERSIONS)
def test_the_c_checks_pass_and_the_elided_run_is_the_model(version):
    """check(): the rules, the C11 base check, and the elided program's run under the undefined-
    behaviour sanitizer printing the model's checksum; a wrong model value fails at "defined"."""
    for s in range(1, 7):
        p = fuzz.generate(s, version)
        r = fuzz.check(p.source, expected=p.expected)
        assert r.ok, (s, r)
    p = fuzz.generate(3, version)
    assert fuzz.check(p.source, expected=p.expected + 1).stage == "defined"


def test_a_campaign_refuses_a_toolchain_that_does_not_compile_its_programs(tmp_path):
    """CCE compiles OpenACC for Fortran only (catalog/toolchains.yaml): a C OpenACC campaign naming it stops
    before any program runs, with the catalog's reason, instead of recording every program as crashed."""
    from offload.engine import fuzz_exec as FX
    with pytest.raises(ValueError, match="cce19.*OpenACC for Fortran only"):
        FX.campaign(tmp_path / "run", [1], workers=1, toolchains=("gcc", "cce19"), gen_version=C.GEN_ACC, log=lambda *a: None)
    assert not (tmp_path / "run" / "programs.jsonl").exists()
