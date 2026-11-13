"""Tests of the fuzz campaign analysis, the fortran-oop generator, the stress generator and the CCE ftn split-CIF-record rule."""


# ---- The campaign analysis (offload/engine/fuzz_campaign.py) ------------------------------------------

from offload.engine import fuzz_campaign as FC


def P(seed, feats, cls, mode="unified", reasons=None, validity="valid"):
    return FC.Prog("r", mode, seed, frozenset(feats), dict(cls),
                   reasons or {}, validity)


def test_rates_skip_noncompliant_and_split_crashes():
    ps = [P(1, [], {"afar": "agree"}),
          P(2, [], {"afar": "run_error"}, reasons={"afar": "crash: SIGSEGV"}),
          P(3, [], {"afar": "wrong_code"}, validity="noncompliant"),
          P(4, [], {"afar": "timeout"}, mode="copy",
            reasons={"afar": "compile_timeout"})]
    r = FC.rates(ps)
    assert r["unified"]["afar"] == {"agree": 1, "crash": 1}
    assert r["copy"]["afar"] == {"compile_timeout": 1}


def test_interaction_needs_both_features():
    A, B, C = "base:dc:mapper", "dir:teams", "clause:if"
    ps = []
    k = 0
    for i in range(40):        # A and B: half fail
        k += 1
        ps.append(P(k, [A, B], {"cce21": "wrong_code" if i % 2 else
                                "agree"}))
    for i in range(40):        # A without B: rarely
        k += 1
        ps.append(P(k, [A, C], {"cce21": "wrong_code" if i == 0 else
                                "agree"}))
    for i in range(40):        # B without A: rarely
        k += 1
        ps.append(P(k, ["base:ty:real4", B], {"cce21": "wrong_code" if
                                              i == 0 else "agree"}))
    rows = FC.fail_rows(ps, "cce21")
    got = FC.interactions(rows)
    assert [(r["base"], r["omp"]) for r in got][:1] == [(A, B)]
    top = got[0]
    assert top["programs"] == 40 and top["failures"] == 20
    assert top["base_without"] == [1, 40] and top["omp_without"] == [1, 40]
    # a base feature that fails as often alone explains the pair
    got = FC.interactions(rows, alone={A: (6, 12), B: (0, 50)})
    assert got[0]["explained_alone"]
    got = FC.interactions(rows, alone={A: (0, 12), B: (0, 50)})
    assert not got[0]["explained_alone"]
    # too few programs: nothing
    assert FC.interactions(rows, min_n=41) == []


def test_compile_rejections_are_not_pair_failures():
    ps = [P(1, ["base:x:y", "dir:target"], {"cce19": "compile_reject"}),
          P(2, ["base:x:y", "dir:target"], {"cce19": "timeout"},
            reasons={"cce19": "compile_timeout"}),
          P(3, ["base:x:y", "dir:target"], {"cce19": "ice"})]
    assert len(FC.fail_rows(ps, "cce19")) == 1
    assert FC.fail_rows(ps, "cce19", fail=("ice",))[0][1]


def test_copy_mode_compares_the_same_seeds():
    ps = [P(1, [], {"afar": "agree"}), P(1, [], {"afar": "wrong_code"},
                                         mode="copy"),
          P(2, [], {"afar": "run_error"}, reasons={"afar": "crash: x"}),
          P(2, [], {"afar": "agree"}, mode="copy"),
          P(3, [], {"afar": "agree"}),                  # no copy run
          P(4, [], {"afar": "agree"}), P(4, [], {"afar": "agree"},
                                         mode="copy")]
    got = FC.copy_mode(ps)["afar"]
    assert got["pairs"] == 3
    assert got["only_copy"] == [(1, "agree", "wrong_code")]
    assert got["only_unified"] == [(2, "crash", "agree")]


def test_reject_drivers_name_the_later_form():
    b = [{"case": {"toolchain": "cce19", "outcome": "rejected",
                   "reason": "diagnostic: ftn-1725 ftn: ERROR M, File = "
                   "a.f90, Line = 3, Column = 4 | x"},
          "verdict": "unsupported", "rule": "R11c-later-form-unclaimed",
          "reason": "later form declare-target-enter (the enter ...)"},
         {"case": {"toolchain": "cce19", "outcome": "rejected",
                   "reason": "diagnostic: ftn-1747 ftn: ERROR M, File = "
                   "a.f90, Line = 9, Column = 4 | stride of \"IB\""},
          "verdict": "compiler_bug", "rule": "R11-compile-rejection",
          "reason": ""}]
    got = FC.reject_drivers(b)["cce19"]
    assert got[0][3] == "later form declare-target-enter"
    assert 'stride of "X"' in got[1][3]


def test_features_that_always_occur_together_are_one_row():
    A, B1, B2 = "base:al:x", "kernel:inred", "dir:taskgroup"
    ps, k = [], 0
    for i in range(40):
        k += 1
        ps.append(P(k, [A, B1, B2], {"t": "wrong_code" if i % 2 else
                                     "agree"}))
    for i in range(40):
        k += 1
        ps.append(P(k, [A, "dir:x"], {"t": "agree"}))
    for i in range(40):
        k += 1
        ps.append(P(k, ["base:y", B1, B2], {"t": "agree"}))
    got = FC.interactions(FC.fail_rows(ps, "t"))
    assert len(got) == 1
    assert set(got[0]["omp"].split(" / ")) == {B1, B2}


# ---- fortran-oop stage 3: generator fuzz-5 and its base-language group ``oop`` ---------------------------

import hashlib
import re

import pytest

from offload.engine import fuzz
from offload.engine import fuzz_base as fb
from offload.engine import prerun

GOLDEN = {
    ("fuzz-1", ()):
        "179bdd54ad28ad456ee972f5615236d6426e85af4c1cf8bc110cc9b5a0af24fe",
    ("fuzz-2", ()):
        "a994dee158be1001c905902100667fb45f7ff06284d62adf1010bcaf072196c2",
    ("fuzz-3", ()):
        "8d94a15b85ebe35b67e548f216e21a1964d7abe842ff468551faafa017621496",
    ("fuzz-3", ("derived",)):
        "0e66ca3d7b4f2acac185a8f51b8571e4e0a28970becd5a52adc74c73e65e6797",
    ("fuzz-4", ()):
        "18075f8e4e3af936b63a7622ce255b6ed493d4c869e36025c1b88d8890d298ea",
    ("fuzz-4", ("types", "derived", "alloc", "declare", "multitu")):
        "4012b81bfb803e907ee78c243d11a6baf515fe3cb8b2142093477c6450ffaf5d",
    ("fuzz-4", ("declare",)):
        "f87d09da5a12749e9350d27ea5e1b48a528a5659da7482e2e55e5cca7165fc2b",
    ("fuzz-4s50", ()):
        "1e53191e203a15b632a7bfde0e041679b37bd281674ad27b362f322572574338",
    ("fuzz-4s50", ("derived", "alloc")):
        "d879200898e23eff150f4011caeff4ecfed4bc8b1d4e860e10aebcd8763cad03",
}


@pytest.mark.parametrize("key", sorted(GOLDEN), ids=str)
def test_old_versions_are_byte_identical(key):
    v, base = key
    h = hashlib.sha256()
    for s in range(1, 31):
        h.update(fuzz.generate(s, v, base).source.encode())
    assert h.hexdigest() == GOLDEN[key]


def test_defaults_unchanged():
    assert fuzz.GEN_VERSION == "fuzz-4"
    assert fb.BASE_GROUPS == ("types", "derived", "alloc", "declare",
                              "multitu")
    assert "fuzz-5" in fuzz.GEN_VERSIONS
    assert fb.ALL_GROUPS == fb.BASE_GROUPS + ("oop",)


def _body(src: str) -> str:
    return "\n".join(ln for ln in src.split("\n")
                     if not ln.startswith("! generator:"))


@pytest.mark.parametrize("base", [(), ("derived", "declare"),
                                  ("types", "derived", "alloc", "declare",
                                   "multitu")], ids=str)
def test_fuzz5_without_oop_is_the_fuzz4_program(base):
    for s in range(1, 21):
        a = fuzz.generate(s, "fuzz-4", base)
        b = fuzz.generate(s, "fuzz-5", base)
        assert _body(a.source) == _body(b.source)
        assert a.expected == b.expected
        assert "! generator: fuzz-5" in b.source


def test_oop_needs_fuzz5():
    with pytest.raises(ValueError, match="fuzz-5"):
        fuzz.generate(1, "fuzz-4", ("oop",))


def _oop(seeds=range(1, 41), base=("oop",)):
    return [fuzz.generate(s, "fuzz-5", base) for s in seeds]


def test_oop_programs_use_the_oop_machinery():
    progs = _oop()
    called = [p for p in progs if re.search(r"\boo\d\(", p.source.split(
        "program fuzz_prog")[1])]
    assert len(called) >= 10
    feats = set().union(*(p.features for p in progs))
    for f in ("dispatch", "override", "inherit", "select", "unlimited"):
        assert f"base:oop:{f}" in feats, f
    p = called[0]
    mod = p.source.split("module fuzz_omod")[1].split("end module fuzz_omod")[0]
    assert "type, extends(ob_t) :: ox_t" in mod
    assert "class(ob_t), intent(in) :: s" in mod
    assert "procedure :: f => ob_f" in mod
    assert all(mod.count("!$omp declare target") >= 3 for _ in [0])


def test_oop_bundle_puts_the_module_in_its_own_file():
    for p in _oop(range(1, 31), ("multitu", "oop")):
        if "module fuzz_omod" in p.source:
            assert f"{fb.FILE_MARK}fuzz_omod.f90" in p.source
            return
    pytest.fail("no multitu+oop program with fuzz_omod")


@pytest.mark.parametrize("seed", range(1, 21))
def test_oop_programs_pass_the_rules(seed):
    p = fuzz.generate(seed, "fuzz-5", ("oop", "derived"))
    ok, why = prerun.rules_witness((p.source, "f90", "omp", 52))
    assert ok, why


def _fortran_model(k1, a1, p1, x):
    """mod with the sign of the dividend (Fortran MOD)."""
    r = abs(x * a1 + k1) % p1
    return r if x * a1 + k1 >= 0 else -r


def test_oop_function_models_follow_fortran():
    """Each device function's model equals an independent reading of its
    Fortran text (MOD truncates toward zero)."""
    def fmod(a, b):
        r = abs(a) % b
        return r if a >= 0 else -r
    seen = 0
    for p in _oop(range(1, 41)):
        g = fuzz._Gen(p.seed, "fuzz-5", ("oop",))
        g.build()
        consts = g.oop_consts
        for fn in g.ofuncs:
            for x in (-37, -1, 0, 5, 123):
                c = consts
                ob = fmod(x * c["a1"] + c["k"][fn.name], c["p1"])
                if fn.name == "oo1":
                    want = ob
                elif fn.name == "oo2":
                    want = fmod(ob + c["j"][fn.name] * c["a2"], c["p2"])
                elif fn.name == "oo3":
                    want = fmod(ob + c["j"][fn.name] * c["a2"], c["p2"]) + \
                        c["k"][fn.name]
                elif fn.name == "oo4":
                    want = (x + c["j"][fn.name]) + (x - c["k2"][fn.name])
                else:
                    want = fmod(3 * x + c["j"][fn.name], 1009) + \
                        fmod(x + c["k2"][fn.name], 1009)
                assert fn.body.ev({"x": x}, {}) == want, (p.seed, fn.name)
                seen += 1
    assert seen >= 50


def test_group_since_compares_by_version_order(monkeypatch):
    """A group allowed since fuzz-5 stays allowed in a later
    generator version."""
    monkeypatch.setattr(fb, "GROUP_SINCE", {"oop": "fuzz-4"})
    assert fuzz.generate(3, "fuzz-5", ("oop",)).source


# ---- The 16 AFAR run failures of the fuzz-5 oop sample (results/fuzz/oop5-0, oop5-1) are not about the oop group: ----

from pathlib import Path


from offload.engine import fuzz, prerun

ROOT = Path(__file__).resolve().parent.parent.parent
DOC = ROOT / "data" / "reports" / "fuzz5-oop-afar.md"
DIR = ROOT / "data" / "reports" / "fuzz5-oop-afar"

SEEDS = {"oop5-0": (33, 35, 87, 89, 94, 121), "oop5-1": (157, 165, 166, 167, 183, 213, 231, 275, 288, 294)}
CLUSTERS = {"A": 8, "B": 6, "C": 2}


def _rows():
    rows = []
    for line in DOC.read_text().splitlines():
        m = re.match(r"\|\s*(oop5-[01]):(\d+)\s*\|\s*(\d+)\s*\|\s*([ABC])\b", line)
        if m:
            rows.append((m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)))
    return rows


def test_table_lists_the_sixteen_seeds_with_the_generators_values():
    rows = _rows()
    assert sorted((r, s) for r, s, _, _ in rows) == sorted((r, s) for r, ss in SEEDS.items() for s in ss)
    for _run, seed, expected, _cl in rows:
        assert fuzz.generate(seed, "fuzz-5", ("derived", "oop")).expected == expected, seed


def test_clusters_partition_the_sixteen():
    count = {}
    for _r, _s, _e, cl in _rows():
        count[cl] = count.get(cl, 0) + 1
    assert count == CLUSTERS


@pytest.mark.parametrize("path", sorted(DIR.glob("*.f90")) if DIR.is_dir() else [], ids=lambda p: p.name)
def test_reproducers_are_legal_by_the_rules(path):
    ok, why = prerun.rules_witness((path.read_text(), "f90"))
    assert ok, why


def test_every_reproducer_header_is_complete_and_its_control_exists():
    files = sorted(DIR.glob("*.f90"))
    assert len(files) >= 20
    for p in files:
        head = [ln for ln in p.read_text().splitlines() if ln.startswith("!")]
        text = "\n".join(head)
        for key in ("expected (the host run", "observed HSA_XNACK=1", "observed HSA_XNACK=0", "legality:", "build:"):
            assert key in text, (p.name, key)
        m = re.search(r"! control \(one change, correct\): (\S+\.f90)", text)
        if m:
            assert (DIR / m.group(1)).is_file(), (p.name, m.group(1))


def test_doc_names_every_reproducer():
    doc = DOC.read_text()
    for p in sorted(DIR.glob("*.f90")):
        assert p.name in doc, p.name


# ---- The stress generator (offload.engine.stress), its executor's ----------------------------------------

import random
import shutil


from offload.engine import stress as S
from offload.engine import stress_exec as X


def small(axis):
    sw = S.SWEEPS[axis]
    return sw[0] if axis != "names" else 63


@pytest.mark.parametrize("model", ["omp", "acc"])
@pytest.mark.parametrize("axis", S.AXES)
def test_every_axis_builds_deterministically(axis, model):
    if model == "acc" and axis in S.ACC_EXCLUDED:
        with pytest.raises(ValueError):
            S.build(axis, small(axis), 1, model)
        return
    a = S.build(axis, small(axis), 1, model)
    b = S.build(axis, small(axis), 1, model)
    assert a.source == b.source and a.expected == b.expected
    assert a.expected == sum(a.per_kernel.values()) % S.P
    assert "RESULT checksum=" in a.source
    want = {"oo": "unspecified", "tuimp": "illegal_probe"}.get(axis,
                                                                "legal")
    assert a.legality == want, (axis, a.legality, a.cite)
    # every kernel prints its own value
    for k in a.kernels:
        assert f"'K {k.name} '" in a.source


@pytest.mark.parametrize("model", ["omp", "acc"])
def test_split_axes_keep_one_variant(model):
    names = S.axis_names(model)
    assert "oo.polymap" in names and "scalars.implicit" in names or \
        model == "acc"
    for a in names:
        base = a.split(".")[0]
        sw = S.SWEEPS[base]
        p = S.build(a, sw[0] if base != "names" else 63, 1, model)
        if "." in a:
            var = a.split(".", 1)[1]
            assert all(S.kernel_variant(k) == var for k in p.kernels)
        want = "unspecified" if a == "oo.polymap" else \
            "illegal_probe" if a == "tuimp" else "legal"
        assert p.legality == want, (a, p.legality)


def test_seed_and_size_change_programs():
    assert S.build("private", 8, 1).source != S.build("private", 8, 2).source
    assert S.build("private", 8, 1).source != S.build("private", 9, 1).source


def test_limits_label_illegal_probes():
    assert S.build("names", 63, 1).legality == "legal"
    p = S.build("names", 64, 1)
    assert p.legality == "illegal_probe" and "name" in p.limits["violations"]
    assert "63 characters" in p.cite
    ok = S.build("contlines", 200, 1)
    assert ok.legality == "legal" and ok.limits["max_continuations"] <= 255
    bad = S.build("contlines", 300, 1)
    assert bad.legality == "illegal_probe"
    assert "cont" in bad.limits["violations"]
    for p in (S.build("private", 2048, 1), S.build("exprs", 1024, 1)):
        assert p.limits["max_line"] <= 132


def test_cross_module_implicit_declare_target_is_a_probe_in_every_layout():
    """For Fortran a compilation unit is a program unit (5.2 §1.2.2), so a
    chain of procedures in other modules without declare target is
    cross-unit even in one file (F7)."""
    one = S.build("tuimp", 3, 1, layout="single")
    many = S.build("tuimp", 3, 1, layout="per_unit")
    assert one.legality == many.legality == "illegal_probe"
    assert "§1.2.2" in one.cite and "13.8" in one.cite
    assert one.expected == many.expected
    plain = S.build("tu", 5, 1, layout="per_unit")
    assert plain.legality == "legal" and len(plain.files) >= 10
    assert any(n.endswith(".c") for n, _ in plain.files)        # bind(C)
    assert any("submodule" in t for _, t in plain.files)


def test_polymap_programs_declare_openmp_60():
    p = S.build("oo.polymap", 1, 1)
    assert p.legality == "unspecified" and "OpenMP 6.0" in p.source
    assert "6.0 §7.9.6" in p.cite and "§5.7.2" in p.cite
    assert "OpenMP 6.0" not in S.build("oo.tbp", 1, 1).source


def test_axes_with_a_polymap_kernel_have_a_new_revision():
    """Declaring OpenMP 6.0 changed the text of every program with a
    polymap kernel, so each such axis's revision is above 2, the revision
    before that change."""
    for axis in ("oo.polymap", "oo"):
        p = S.build(axis, 2, 1)
        if "OpenMP 6.0" in p.source:
            assert p.rev >= 2 and S.axis_rev(axis) == p.rev
    assert S.build("oo", 2, 1).rev == 3


def test_programs_record_their_revision():
    assert S.build("clauses", 8, 1).rev == S.AXIS_REV["clauses"]
    assert S.build("private", 8, 1).rev == 1
    assert S.build("clauses", 8, 1).meta()["rev"] == S.AXIS_REV["clauses"]
    from offload.engine import stress_c as C
    assert C.build_c("contlines", 8, 1).rev == 2


def test_layouts_keep_the_value_and_module_order():
    base = S.build("random", 12, 3)
    for layout in S.LAYOUTS:
        p = S.build("random", 12, 3, layout=layout)
        assert p.expected == base.expected
        defined = set()
        for name, text in p.files:
            if not name.endswith(".f90"):
                continue
            for u in re.findall(r"^\s*use (\w+)", text, re.M):
                if u not in ("omp_lib", "openacc", "iso_c_binding"):
                    assert u in defined or re.search(
                        rf"^module {u}\s*$", text, re.M), (layout, u)
            defined |= set(re.findall(r"^module (\w+)\s*$", text, re.M))


def test_pack_keeps_lines_short_and_continues_directives():
    lines = S.pack("target", [f"map(to: a{k:04d})" for k in range(50)],
                   "  ", "!$omp", 80)
    assert all(len(ln) <= 82 for ln in lines)
    assert lines[0].startswith("  !$omp target")
    assert all(ln.startswith("  !$omp& ") for ln in lines[1:])
    assert all(ln.endswith(" &") for ln in lines[:-1])


def test_clauses_axis_covers_every_allowed_clause():
    from offload.engine.fuzz import allowed_clauses
    allowed = allowed_clauses("target teams distribute parallel do simd")
    assert allowed <= set(S.CLAUSE_ORDER) | set(S.NOT_FILLED)
    k = S.build("clauses", 64, 1).kernels[0]
    names = [c for c, _ in k.plan()]
    assert len(names) == 64
    assert set(names) >= {c for c in S.CLAUSE_ORDER if c in allowed}


def test_shrink_variants_are_smaller_and_valued():
    for axis in ("private", "nest", "dtnest", "template", "scalars",
                 "clauses", "calls"):
        p = S.build(axis, S.SWEEPS[axis][2], 1)
        for k in p.kernels:
            for s in k.smaller():
                assert s.describe() != k.describe()
                s.value()
                assert s.body()


def test_scalar_routes_cover_both_models():
    o = S.build("scalars", 2, 1, "omp")
    a = S.build("scalars", 2, 1, "acc")
    feats_o = {f for f in o.features if f.startswith("route:")}
    feats_a = {f for f in a.features if f.startswith("route:")}
    assert {"route:implicit", "route:present_implicit", "route:declare",
            "route:target_attr", "route:dm_tofrom"} <= feats_o
    assert {"route:implicit_kernels", "route:data_copy",
            "route:enter_implicit"} <= feats_a
    # an observation the specification leaves undefined is printed, not
    # counted
    assert re.search(r"OBS k\d+ to host", o.source)
    assert not S.ScalarsKernel.elision_valid


def test_runtime_model_closed_form():
    k = S.RuntimeKernel("k0001", S.Opts(), random.Random(1),
                        variant="iters", size=3000, c=17)
    assert k.value() == sum((i * 17) % 1009 for i in range(1, 3001)) % S.P


def test_classify_compile_and_steps():
    out = ("STRESS_TIME a.f90 123456 1.50 rc=0\n"
           "LLVM ERROR: out of memory\n"
           "STRESS_TIME b.f90 9999 0.20 rc=1\n")
    steps = X.parse_steps(out)
    assert [s["step"] for s in steps] == ["a.f90", "b.f90"]
    assert steps[0]["rss_kib"] == 123456 and steps[1]["rc"] == 1
    tc = X.tc_for("afar", "omp")
    cls, why = X.classify_compile(tc, 1, out, steps)
    assert cls == "compile_oom"
    assert X.classify_compile(tc, None, "", [])[0] == "compile_timeout"


def test_build_script_limits_every_step():
    tc = X.tc_for("cce20", "omp")
    sc = X.build_script(tc, ["a.f90", "b.c", "main.f90"], "p.out", "-O2",
                        "/tmp/x", 32 * X.GIB, staticlib=True)
    assert sc.count("ulimit -v 33554432") == 5      # 3 compiles, ar, link
    assert sc.count("timeout --foreground --kill-after=10 900 ") == 5
    assert "craycc" in sc and "-lstress" in sc and "module load" in sc


def test_variants_per_vendor():
    assert X.variant_flags(X.tc_for("nvhpc", "omp"), "nordc") == \
        "-O2 -gpu=nordc"
    assert X.variant_flags(X.tc_for("afar", "omp"), "nordc") is None
    assert X.variant_flags(X.tc_for("afar", "omp"), "noinline") is None
    assert X.variant_flags(X.tc_for("cce19", "omp"), "lto", "c") == \
        "-O2 -flto"


def test_judge_reads_kernel_lines():
    p = S.build("kernels", 3, 1)

    class Ex:
        rc = 0
        timed_out = False
        stderr = ""
    ex = Ex()
    lines = [f"K {k} {v}" for k, v in p.per_kernel.items()]
    ex.stdout = "\n".join(lines + [f"RESULT checksum={p.expected} "
                                   "ran_on_host=0"]) + "\n"
    assert X.judge(p, ex)[0] == "agree"
    bad = dict(p.per_kernel)
    first = next(iter(bad))
    ex.stdout = ex.stdout.replace(f"K {first} {bad[first]}", f"K {first} 7")
    ex.stdout = ex.stdout.replace(f"checksum={p.expected}", "checksum=5")
    cls, why, info = X.judge(p, ex)
    assert cls == "wrong_code" and info["k"][first] == 7


@pytest.mark.gfortran
@pytest.mark.skipif(shutil.which("gfortran") is None and
                    not __import__("pathlib").Path(
                        "/usr/tce/bin/gfortran").exists(),
                    reason="gfortran not found")
@pytest.mark.parametrize("axis,size,model", [
    ("private", 64, "omp"), ("reduction", 64, "acc"), ("dtnest", 3, "omp"),
    ("oo", 3, "omp"), ("tu", 3, "omp"), ("template", 8, "acc"),
    ("args", 25, "omp"), ("clauses", 28, "omp"), ("random", 8, "omp")])
def test_elision_agrees_with_the_model(axis, size, model):
    p = S.build(axis, size, 2, model, layout="per_unit" if axis == "tu"
                else "single")
    e = X.elide(p)
    assert e["ok"], e


# --- C programs, the report, the shrinker -------------------------------------------------------

from offload.engine import stress_c as SC          # noqa: E402
from offload.engine import stress_min as SM        # noqa: E402
from offload.engine import stress_report as SR     # noqa: E402


@pytest.mark.parametrize("axis", SC.C_AXES)
def test_c_axes_build(axis):
    a = SC.build_c(axis, SC.C_SWEEPS[axis][0], 1)
    b = SC.build_c(axis, SC.C_SWEEPS[axis][0], 1)
    assert a.source == b.source and a.lang == "c"
    assert a.expected == sum(a.per_kernel.values()) % S.P
    want = "illegal_probe" if axis == "tuimp" else "legal"
    assert a.legality == want
    assert any(n == "st.h" for n, _ in a.files)


def test_c_limits_are_implementation_defined():
    assert SC.build_c("args", 127, 1).legality == "legal"
    assert SC.build_c("args", 128, 1).legality == "impl_defined"
    assert SC.build_c("names", 63, 1).legality == "legal"
    p = SC.build_c("names", 255, 1)
    assert p.legality == "impl_defined" and "5.2.4.1" in p.cite


def test_c_continuation_pragma_one_item_per_line():
    p = SC.build_c("contlines", 64, 1)
    text = dict(p.files)["stress.c"]
    assert text.count("\\\n") >= 64
    assert "private( \\" in text


def _row(**kw):
    base = {"id": "x-omp-8-1", "toolchain": "cce19", "mode": 1,
            "variant": "O2", "cls": "agree", "reason": "", "legality":
            "legal", "axis": "x", "size": 8, "model": "omp", "lang": "f90",
            "steps": [{"step": "a.f90", "rss_kib": 2048, "s": 1.5, "rc": 0}],
            "peak_rss_kib": 2048, "bad_kernels": [], "obs": {}}
    base.update(kw)
    return base


def test_report_counts_only_valid_legal_rows():
    progs = {"x-omp-8-1": {"id": "x-omp-8-1", "gate": {"stage": "ok"},
                           "elision": {"ok": True}, "lines": 50,
                           "kernels": ["k0001:private(nitems=8)"]},
             "x-omp-16-1": {"id": "x-omp-16-1", "gate": {"stage": "rules"},
                            "elision": {"ok": True}}}
    rows = [_row(cls="wrong_code", bad_kernels=["k0001"],
                 reason="checksum=1 expected=2"),
            _row(id="x-omp-8-1", toolchain="afar"),
            _row(id="x-omp-16-1", size=16, cls="wrong_code"),
            _row(id="x-omp-8-1", toolchain="cce20", cls="wrong_code",
                 legality="unspecified")]
    f = SR.findings(progs, rows)
    assert list(f) == ["cce|f90/omp|wrong_code|x:private"]
    assert f["cce|f90/omp|wrong_code|x:private"]["agree_elsewhere"] == 1


def test_report_timeouts_need_a_smaller_sibling():
    progs = {i: {"id": i, "gate": {"stage": "ok"}, "elision": {"ok": True},
                 "lines": 10} for i in ("x-omp-8-1", "x-omp-64-1")}
    big = _row(id="x-omp-64-1", size=64, cls="compile_timeout",
               reason="compile_timeout")
    assert not SR.findings(progs, [big])
    small = _row(id="x-omp-8-1", size=8)
    assert SR.findings(progs, [big, small])


def test_breakpoints_relative_to_the_real_maximum():
    rows = [_row(size=s, id=f"x-omp-{s}-1",
                 cls="agree" if s < 64 else "run_error",
                 reason="exit_status: 1") for s in (1, 8, 64)]
    b = SR.breakpoints({}, rows, {"x": {"max": 16}})
    assert b[0]["first_fail"] == 64 and b[0]["largest_agree"] == 8
    assert b[0]["fail_over_real"] == 4.0


def test_failure_keys_of_the_shrinker():
    assert SM.failure_key("ice", "ice: INTERNAL COMPILER ERROR at line 12") \
        == SM.failure_key("ice", "ice: INTERNAL COMPILER ERROR at line 99")
    assert SM.failure_key("run_error", "crash: SIGABRT") == "crash"
    assert SM.failure_key("wrong_code", "checksum=1") == "wrong_code"


def test_shrinker_keeps_the_wrong_kernels(monkeypatch):
    p = S.build("kernels", 6, 1)
    victim = p.kernels[3].name

    def fake(prog, tc, modes, variant, lim=None, keep=None):
        bad = [victim] if any(k.name == victim for k in prog.kernels) else []
        r = X.Row(prog.id, tc, modes[0], variant,
                  "wrong_code" if bad else "agree", "checksum=1 expected=2"
                  if bad else "")
        r.bad_kernels = bad
        return [r]
    monkeypatch.setattr(X, "execute", fake)
    row = {"id": p.id, "toolchain": "cce19", "mode": 1, "variant": "O2",
           "cls": "wrong_code", "reason": "checksum=1 expected=2",
           "bad_kernels": [victim], "limits": {"compile_s": 900}}
    res = SM.minimize(p, row, log=lambda m: None)
    assert [k.name for k in res.prog.kernels] == [victim]
    assert res.prog.kernels[0].p["n"] <= p.kernels[3].p["n"]


def _alive(pid: int) -> bool:
    import os
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:  # a zombie of an exited group member is not running
        st = open(f"/proc/{pid}/stat").read().split()[2]
        return st != "Z"
    except OSError:
        return False


@pytest.mark.parametrize("how", ["run_group", "execute"])
def test_timeouts_kill_the_whole_process_group(tmp_path, how):
    """A compile or run that exceeds its limit leaves no process behind:
    the stress runner's helpers (run_group: gate, elision; the harness's
    _execute: compiles and device runs, also on wingtip) kill the process
    group, grandchildren included."""
    import subprocess
    import time
    from offload.engine import harness
    pidf = tmp_path / "pid"
    script = f"sleep 300 & echo $! > {pidf}; wait"
    if how == "run_group":
        try:      # the in-job limit (rc 124) or the parent's (raises)
            r = X.run_group(["bash", "-c", script], tmp_path, 1)
            assert r.returncode in X.TIMEOUT_RC
        except subprocess.TimeoutExpired:
            pass
    else:
        ex = harness._execute(f"exec bash -c '{script}'\n", tmp_path, 1)
        assert ex.timed_out
    pid = int(pidf.read_text())
    for _ in range(50):
        if not _alive(pid):
            break
        time.sleep(0.1)
    assert not _alive(pid)


_TERM_PROOF = ("bash -c \"trap '' TERM; sleep 300\" & echo $! > {pidf}; "
               "trap '' TERM; sleep 300")


def _gone(pid: int, wait_s: float = 20) -> bool:
    import time
    t0 = time.time()
    while time.time() - t0 < wait_s:
        if not _alive(pid):
            return True
        time.sleep(0.1)
    return False


def test_run_group_kills_a_term_ignoring_grandchild_at_the_limit(tmp_path):
    """A grandchild that ignores
    SIGTERM is dead once run_group returns from its limit (the group gets
    SIGKILL; --foreground's timeout alone would leave it)."""
    import subprocess
    pidf = tmp_path / "pid"
    try:
        X.run_group(["bash", "-c", _TERM_PROOF.format(pidf=pidf)],
                    tmp_path, 1)
    except subprocess.TimeoutExpired:
        pass
    assert _gone(int(pidf.read_text()))


_RUNNER = (
    "import sys\n"
    "from offload.engine import harness, stress_exec as X\n"
    "w = harness.watch_group\n"
    "def rec(pgid, limit_s, *a, **k):\n"
    "    dog = w(pgid, limit_s, *a, **k)\n"
    "    open(sys.argv[3], 'w').write(str(dog.proc.pid))\n"
    "    return dog\n"
    "harness.watch_group = rec\n"
    "X.run_group(['bash', '-c', sys.argv[1]], sys.argv[2], int(sys.argv[4]))\n")


def _runner(tmp_path, limit_s: int):
    """A Python process running run_group on a TERM-ignoring script with
    `limit_s`; returns (runner, grandchild pid, watchdog pid)."""
    import subprocess
    import sys
    import time
    from pathlib import Path
    pidf, dogf = tmp_path / "pid", tmp_path / "dog"
    root = Path(X.__file__).resolve().parent.parent.parent
    runner = subprocess.Popen(
        [sys.executable, "-c", _RUNNER, _TERM_PROOF.format(pidf=pidf),
         str(tmp_path), str(dogf), str(limit_s)], cwd=root)
    t0 = time.time()
    while not (pidf.exists() and pidf.read_text().strip() and
               dogf.exists() and dogf.read_text().strip()):
        assert time.time() - t0 < 30, "the run did not start"
        time.sleep(0.1)
    return runner, int(pidf.read_text()), int(dogf.read_text())


def test_run_group_kills_a_term_ignoring_grandchild_with_its_runner(tmp_path):
    """Fix: the runner (a Python process running run_group
    with a 300 s limit) is killed with SIGKILL; the harness watchdog sees
    its pipe close, and the run's TERM-ignoring grandchild is dead within
    seconds (TERM, then KILL after KILL_AFTER_S), not at the limit; the
    watchdog exits too."""
    import os
    import signal
    runner, pid, dog = _runner(tmp_path, 300)
    assert _alive(pid) and _alive(dog)
    os.kill(runner.pid, signal.SIGKILL)
    runner.wait()
    assert _gone(pid, 30), "a grandchild outlived its killed runner"
    assert _gone(dog, 10), "the watchdog outlived its run"


def test_run_group_watchdog_fires_for_a_stopped_runner(tmp_path):
    """Fix: with the runner stopped (its own timer cannot fire),
    the watchdog itself ends the TERM-ignoring group at the limit plus
    WATCHDOG_GRACE_S (then KILL after KILL_AFTER_S), and exits."""
    import os
    import signal
    import time
    runner, pid, dog = _runner(tmp_path, 2)
    os.kill(runner.pid, signal.SIGSTOP)
    try:
        t0 = time.time()
        assert _gone(pid, 40), "the watchdog did not end the group"
        assert time.time() - t0 < 40
        assert _gone(dog, 10), "the watchdog did not exit"
    finally:
        os.kill(runner.pid, signal.SIGKILL)
        runner.wait()


def test_run_group_leaves_no_watchdog(tmp_path, monkeypatch):
    """Fix: after a normal return and after a timeout, the
    watchdog of the run is gone (stopped by the runner)."""
    import subprocess
    from offload.engine import harness
    dogs = []
    real = harness.watch_group

    def rec(*a, **k):
        d = real(*a, **k)
        dogs.append(d)
        return d
    monkeypatch.setattr(harness, "watch_group", rec)
    r = X.run_group(["bash", "-c", "echo ok"], tmp_path, 30)
    assert r.returncode == 0 and r.stdout.strip() == "ok"
    try:
        X.run_group(["bash", "-c", "sleep 300"], tmp_path, 1)
    except subprocess.TimeoutExpired:
        pass
    assert len(dogs) == 2
    for d in dogs:
        assert d.proc.poll() is not None and d.runner_end is None
        assert _gone(d.proc.pid, 5)


def test_run_scripts_carry_the_limit_inside_the_job(tmp_path):
    """The device run's limit holds inside the job (timeout
    --kill-after=10), even if the runner dies; the line still starts with
    exec (the run lock of a shared node applies)."""
    from offload.engine import harness
    tc = X.tc_for("cce19", "omp")
    sc = X.in_job_limit(harness.run_script(tc, "/x/prog.out", 1, True,
                                           str(tmp_path)), 120)
    assert sc.rstrip().split("\n")[-1] == \
        "exec timeout --foreground --kill-after=10 120 /x/prog.out"
    # a hung program dies at the limit without the parent's help
    ex = harness._execute(X.in_job_limit("exec sleep 300\n", 1), tmp_path,
                          30)
    assert ex.rc == 124


def test_inner_timeouts_do_not_escape_the_group_kill(tmp_path):
    """F5: the structure build_script emits (a step
    under the in-job timeout) whose compiler leaves a grandchild that
    ignores SIGTERM: after the runner's limit nothing of it is alive. With
    a plain `timeout` (no --foreground) the step left the process group and
    survived."""
    import time
    from offload.engine import harness
    pidf = tmp_path / "pid"
    fake = tmp_path / "fakecc"
    fake.write_text("#!/bin/bash\ntrap '' TERM\n"
                    f"bash -c \"trap '' TERM; sleep 300\" & echo $! > {pidf}\n"
                    "sleep 300\n")
    fake.chmod(0o755)
    script = X._step(str(fake), "fake.f90", 4 * X.GIB, 300) + "\n"
    t0 = time.time()
    ex = harness._execute(script, tmp_path, 3)
    assert time.time() - t0 < 60
    pid = int(pidf.read_text())
    for _ in range(100):
        if not _alive(pid):
            break
        time.sleep(0.1)
    assert not _alive(pid), "a grandchild outlived the build limit"
    del ex


# ---- The CCE ftn split-CIF-record rule (tools/campaigns/ftn_cif_split.py) --------------------------------

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "ftn_cif_split", ROOT / "tools" / "campaigns" / "ftn_cif_split.py")
S_5 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S_5)

BASE = "/tmp/base"


def _line(prefix_len: int, tail: str) -> str:
    return "9\x1e" + "x" * (prefix_len - 2) + tail


def test_hit_at_the_first_split():
    # characters 0..1022 fit in fgets(buf, 1024); the next chunk starts at 1023
    line = _line(1023, "-1-abc")
    assert S_5.hits([line], BASE, BASE) == [(1, 1023)]


def test_one_off_or_other_numbers_are_no_hit():
    for tail in ("Q-1-abc", "-12abc", "-2-abc", "1-abc", "+1-abc"):
        assert S_5.hits([_line(1023, tail)], BASE, BASE) == [], tail
    assert S_5.hits([_line(1022, "-1-abc")], BASE, BASE) == []


def test_later_splits_and_short_lines():
    line = _line(2046, "-1/")
    assert S_5.hits([line], BASE, BASE) == [(1, 2046)]
    assert S_5.hits(["9\x1e-1"], BASE, BASE) == []      # the real end record
    assert S_5.hits([_line(1023, "-1")], BASE, BASE) == [(1, 1023)]


def test_the_directory_is_substituted():
    # the record holds the source path; a longer directory shifts the split
    line = "9\x1e" + "y" * 1000 + BASE + "/s.f90" + "z" * 100
    p = BASE + "/" + "a" * 11 + "-1"
    assert len(line.replace(BASE, p)) > 1030
    assert line.replace(BASE, p)[1023:1025] == "-1"
    assert S_5.hits([line], BASE, p) == [(1, 1023)]
    assert S_5.hits([line], BASE, p.replace("-1", "-2")) == []


def test_design_places_the_split_in_the_named_record():
    rec = "9\x1e" + ("q" * 18 + BASE + "/s.f90:1)") * 12
    lines = ["9\x1eshort", rec]
    p = S_5.design(lines, BASE, "/tmp/r", 60, 2)
    assert p is not None and len(p) == 60 and p.startswith("/tmp/r/")
    assert S_5.hits(lines, BASE, p) == [(2, 1023)]
    assert S_5.hits(lines, BASE, p.replace("-1", "-2")) == []
    assert S_5.design(lines, BASE, "/tmp/r", 60, 1) is None


def test_eval_rows(tmp_path):
    log = tmp_path / "s.log"
    log.write_text("6 1 free():_invalid_pointer /tmp/base msgs=0 last=\n"
                   "0 0 - /tmp/other msgs=3 last=Line=43\n"
                   "garbage\n")
    line = "9\x1e" + "x" * (1021 - len(BASE)) + BASE + "-1z"
    rows = S_5.eval_rows([line], BASE, [log])
    assert [(r["predicted"], r["aborted"], r["dir"]) for r in rows] == [
        (True, True, "/tmp/base"), (False, False, "/tmp/other")]
