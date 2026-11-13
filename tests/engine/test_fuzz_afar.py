"""Tests of the fuzzer: generator, classification, minimizer and triage, and the base-language axis with its typed model, stages and campaign triage."""


# ---- Tests of the fuzzer: generator determinism and legality ------------------------------------------

import where
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from offload.engine import fuzz, fuzz_exec as fe, fuzz_min as fm
from offload.engine import fuzz_report as fr
from offload.engine.toolchains import TOOLCHAINS, Toolchain
from tests.bounded import bounded_map

ROOT = Path(__file__).resolve().parent.parent.parent
DATA = Path(__file__).parent.parent / "data"
FAKES = DATA / "fakes"
MESSAGES = DATA / "messages"
FIXTURE = DATA / "fuzz" / "guarded_loop_cce19.f90"
SAMPLE = range(1, 201)


# --- the generator ------------------------------------------------------------------

def test_same_seed_same_program():
    for seed in (1, 2, 77, 1000):
        a, b = fuzz.generate(seed), fuzz.generate(seed)
        assert a.source == b.source and a.expected == b.expected
        assert a.features == b.features
        assert f"! seed: {seed}\n" in a.source
        assert f"! generator: {fuzz.GEN_VERSION}\n" in a.source
        assert f"! expected checksum: {a.expected}\n" in a.source


def test_different_seeds_differ():
    assert len({fuzz.generate(s).source for s in range(1, 41)}) == 40


def test_deterministic_across_processes():
    """String hashing is randomised per process: the program must not
    depend on set iteration order."""
    code = ("import hashlib, sys; sys.path.insert(0, %r); "
            "from offload.engine.fuzz import generate; "
            "print(hashlib.sha256(''.join(generate(s).source for s in "
            "range(1, 31)).encode()).hexdigest())" % str(ROOT))
    outs = set()
    for hs in ("1", "2", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=hs)
        outs.add(subprocess.run([sys.executable, "-c", code], env=env,
                                capture_output=True, text=True,
                                check=True).stdout)
    assert len(outs) == 1


def test_programs_follow_the_frame():
    for seed in SAMPLE[:50]:
        p = fuzz.generate(seed)
        lines = p.source.splitlines()
        assert lines[-1] == "end program fuzz_prog"
        assert "'RESULT checksum='" in p.source
        assert "  ! fuzz: kernels" in lines and "  ! fuzz: checksum" in lines
        assert "real" not in p.source.lower().split("! fuzz: kernels")[1]
        assert all(len(ln) <= 132 for ln in lines)
        assert 0 <= p.expected < fuzz.CHECK_MOD
        assert 1 <= len(p.kernels) <= 4


def test_structure_comes_from_the_catalog():
    chains = fuzz.target_chains()
    assert ("target", "teams", "distribute", "parallel", "do") in chains
    assert all(c[0] == "target" for c in chains)
    assert all(fuzz.directive_valid(" ".join(c)) for c in chains)
    for c in chains:
        for part in fuzz.partitions(c):
            assert sum(part, ()) == c
            assert all(fuzz.directive_valid(" ".join(g)) for g in part)
    cov = fuzz.catalog_coverage()
    assert "map" in cov["target teams distribute parallel do"]["filled"]


def test_feature_mix_over_the_sample():
    feats = set()
    for seed in SAMPLE:
        feats |= fuzz.generate(seed).features
    for f in ("kernel:loop", "kernel:guard", "kernel:phase", "kernel:inred",
              "guard:par_thread0", "red:atomic", "red:clause",
              "wrap:target_data", "tasking:nowait_depend",
              "clause:collapse", "clause:schedule", "clause:default:none",
              "declare_target_function"):
        assert f in feats, f
    assert any(f.startswith("defaultmap:") for f in feats)


def test_fortran_helpers():
    assert fuzz.fmod(-7, 3) == -1 and fuzz.fmod(7, -3) == 1
    assert fuzz.fdiv(-7, 2) == -3 and fuzz.fdiv(7, 2) == 3
    with pytest.raises(fuzz.Overflow):
        fuzz.Bin("*", fuzz.Const(2 ** 20), fuzz.Const(2 ** 11)).ev({}, {})
    assert fuzz.map_items("!$omp target map(always, to: a(1:n), b) "
                          "map(tofrom: c)", ("to",)) == ["a", "b"]
    out = fuzz.add_clauses(["  !$omp target map(to: a) &",
                            "  !$omp& map(from: b)", "  x = 1"],
                           ["nowait", "depend(in: a)"])
    assert out == ["  !$omp target map(to: a) &", "  !$omp& map(from: b) &",
                   "  !$omp& nowait &", "  !$omp& depend(in: a)", "  x = 1"]


GFORTRAN = Path(fuzz.GFORTRAN).is_file()


@pytest.mark.gfortran
@pytest.mark.skipif(not GFORTRAN, reason="gfortran is not installed")
def test_sample_passes_the_three_checks():
    """Every program of a 200-seed sample passes offload.engine.rules, gfortran
    -std=f2008 -fsyntax-only and AFAR flang's frontend (within the sample
    budget: a hang fails, tests/bounded.py)."""
    def one(seed):
        return seed, fuzz.check(fuzz.generate(seed).source)
    bad = {s: f"{c.stage}: {c.detail}" for s, c in bounded_map(one, SAMPLE)
           if not c.ok}
    assert bad == {}


def test_checks_reject_an_illegal_program():
    src = fuzz.generate(5).source
    # teams nested directly in parallel (5.2 §10.2 teams-nesting-001)
    bad = src.replace("  ! fuzz: kernels\n", "  ! fuzz: kernels\n"
                      "  !$omp parallel\n  !$omp teams\n  i = 1\n"
                      "  !$omp end teams\n  !$omp end parallel\n")
    c = fuzz.check(bad)
    # A host construct is out of the device-offload scope first
    assert c.stage == "scope" and c.detail.startswith("parallel at line")
    assert "teams-nesting-001" in fuzz.check_rules(bad)
    assert fuzz.check_gfortran(src.replace("implicit none",
                                           "implicit none\n  x = 1")) \
        is not None


@pytest.mark.gpu
def test_model_matches_a_host_run(tmp_path):
    """The Python model's checksum is what AFAR's host run prints."""
    tc = TOOLCHAINS["afar"]
    seeds = [s for s in range(1, 40)
             if fuzz.check(fuzz.generate(s).source).ok][:6]
    for seed in seeds:
        prog = fuzz.generate(seed)
        d = tmp_path / str(seed)
        d.mkdir()
        src, exe = d / "p.f90", d / "p.out"
        src.write_text(prog.source)
        cls, why, _, _ = fe.compile_program(tc, src, exe, d)
        if cls is not None:
            continue  # a feature AFAR does not support
        run = fe.execute(tc, exe, d, "disabled")
        assert run.kind == "ok", (seed, run.why)
        assert run.checksum == prog.expected, seed
        assert run.host == (1 if prog.flags else 0)


# --- classification with fake compilers and programs -------------------------------------

def fake_tc(name="afar", msg=None, rc=0, exe="fuzz_agree.sh") -> Toolchain:
    m = str(where.message(msg)) if msg else "-"
    e = str(FAKES / exe) if exe else "-"
    return Toolchain(name, "", f"{FAKES}/fake_fc.sh {m} {rc} {e}")


def fake_prog(expected=42) -> fuzz.FuzzProgram:
    return fuzz.FuzzProgram(7, "! fake\n", expected, frozenset(), ("k",), 1)


def run_fake(tmp_path, tc, **kw):
    d = tmp_path / tc.name
    d.mkdir(exist_ok=True)
    return fe.run_toolchain(fake_prog(), tc, d, **kw)[0]


def test_agree(tmp_path):
    r = run_fake(tmp_path, fake_tc())
    assert (r.cls, r.checksum, r.ran_on_host, r.flaky) == \
        ("agree", 42, 0, False)
    assert len(r.runs) == 1  # no repeats for an agreeing run


def test_wrong_code_is_repeated(tmp_path):
    r = run_fake(tmp_path, fake_tc(exe="fuzz_wrong.sh"))
    assert r.cls == "wrong_code" and r.checksum == 7
    assert "expected=42" in r.reason and not r.flaky
    assert len(r.runs) == 1 + fe.RERUNS


def test_host_fallback_when_mandatory_refused(tmp_path):
    r = run_fake(tmp_path, fake_tc(exe="fuzz_refused.sh"))
    assert r.cls == "host_fallback"
    assert r.reason.startswith("mandatory_refused: exit_status: 1")


def test_crash_is_run_error(tmp_path):
    r = run_fake(tmp_path, fake_tc(exe="fuzz_crash.sh"))
    assert r.cls == "run_error" and r.reason.startswith("crash: SIGSEGV")


def test_flaky_reported_as_worst(tmp_path):
    r = run_fake(tmp_path, fake_tc(exe="fuzz_flaky.sh"))
    assert r.flaky and r.cls == "wrong_code"
    assert "repeats:" in r.reason


def test_timeout(tmp_path):
    r = run_fake(tmp_path, fake_tc(exe="fuzz_hang.sh"), timeout_s=2)
    assert r.cls == "timeout" and len(r.runs) == 2


@pytest.mark.parametrize("name,msg,cls,code", [
    ("afar", "afar_ice_segfault", "ice", "ice: "),
    ("cce19", "cce_ice_ordered", "ice", "ice: "),
    ("afar", "afar_not_implemented", "compile_reject", "not_implemented: "),
    ("cce21", "cce_syntax_error", "compile_reject", "diagnostic: "),
    ("cce20", "cce_link_c_f_pointer", "compile_reject",
     "link_undefined_symbol: "),
    ("cce19", "cce_link_no_rocm", "harness_error", "environment: "),
    ("afar", "shell_no_module", "harness_error", "environment: "),
])
def test_compile_classes_reuse_the_harness_tables(tmp_path, name, msg, cls,
                                                  code):
    r = run_fake(tmp_path, fake_tc(name, msg, rc=1, exe=None))
    assert r.cls == cls and r.reason.startswith(code)


def test_ignored_clause_is_a_note(tmp_path):
    r = run_fake(tmp_path, fake_tc("cce19", "cce_ignored_device", rc=0))
    assert r.cls == "agree" and r.note.startswith("ignored: ")


def test_host_reference_and_mismatch(tmp_path, monkeypatch):
    pr = fe.ProgramResult(7, "x", "ok", expected=42)
    exes = {}
    for name, exe in (("afar", "fuzz_agree.sh"), ("cce19", "fuzz_wrong.sh")):
        tc = fake_tc(name, exe=exe)
        d = tmp_path / name
        d.mkdir()
        r, path = fe.run_toolchain(fake_prog(), tc, d)
        pr.results[name] = r
        exes[name] = (path, d)
    # host reference: the first compiled toolchain, offload disabled
    for n, e in (("afar", "fuzz_agree.sh"), ("cce19", "fuzz_wrong.sh")):
        monkeypatch.setitem(fe.TOOLCHAINS, n, fake_tc(n, exe=e))
    fe.host_reference(pr, fake_prog(), exes)
    assert (pr.host_ref, pr.host_ref_tc, pr.host_mismatch) == \
        (42, "afar", False)
    pr2 = fe.ProgramResult(7, "x", "ok", expected=5,
                           results=dict(pr.results))
    fe.host_reference(pr2, fake_prog(expected=5), exes)
    assert pr2.host_mismatch
    assert pr2.results["cce19"].host_checksum == 42
    back = fe.ProgramResult.from_json(pr.to_json())
    assert back.results["cce19"].cls == "wrong_code"


# --- the minimizer -------------------------------------------------------------------

def test_logical_lines_round_trip():
    for seed in (3, 11, 42):
        src = fuzz.generate(seed).source
        lines = fm.join_lines(src)
        assert fm.join_lines(fm.render(lines)) == lines
        assert not any(ln.rstrip().endswith("&") for ln in lines)
        assert all(len(ln) <= 132 for ln in fm.render(lines).splitlines())


def test_split_directive():
    assert fm.split_directive("!$omp target teams distribute parallel do "
                              "map(to: a, b) num_teams(4) nowait") == \
        ("target teams distribute parallel do",
         ["map(to: a, b)", "num_teams(4)", "nowait"])
    assert fm.split_directive("!$omp end do nowait") == ("end do",
                                                         ["nowait"])
    assert fm.split_directive("!$omp atomic update") == ("atomic",
                                                         ["update"])
    assert fm.split_directive("!$omp target update to(ia)") == \
        ("target update", ["to(ia)"])


def test_candidate_helpers():
    assert fm._operands("(a(i) + mod(b, 7))") == ["a(i)", "mod(b, 7)", "0"]
    assert fm._operands("merge(x, y, x > y)") == ["x", "y", "0"]
    assert fm._drop_item("map(always, to: a, b(1:n))", "a") == \
        "map(always, to: b(1:n))"
    assert fm._items("reduction(+: r1a)") == ["r1a"]
    assert fm.split_assignment("if (i == 1) hf1 = merge(1, 0, x)") == \
        ("if (i == 1) hf1 = ", "merge(1, 0, x)")


def _guard_oracle():
    calls = []

    def oracle(src):
        calls.append(1)
        if not fuzz.check(src).ok:
            return False, "illegal"
        ok = ("!$omp target parallel" in src
              and "if (omp_get_thread_num() == 0) then" in src
              and "2 * ia(i) + 1" in src)
        return ok, "fake"
    oracle.calls = 0
    return oracle


@pytest.mark.needs_compiler("afar")
@pytest.mark.gfortran
@pytest.mark.skipif(not GFORTRAN, reason="gfortran is not installed")
def test_minimizer_shrinks_with_a_fake_oracle():
    src = FIXTURE.read_text()
    res = fm.minimize(src, _guard_oracle(), workers=4)
    assert res.lines_after < res.lines_before - 20
    out = res.source
    assert "!$omp target teams" not in out          # unrelated kernel gone
    assert "proc_bind" not in out                   # clause gone
    assert "map(to: ia, ib)" not in out             # list item gone
    assert "o3" not in out                          # unused array removed
    assert fuzz.check(out).ok


def _cce19_has_guard_bug(tmp_path) -> bool:
    oracle = fm.Oracle(fm.Failure("cce19", "wrong_code"))
    return oracle(FIXTURE.read_text())[0]


@pytest.mark.gpu
def test_minimizer_on_the_cce19_guarded_loop(tmp_path):
    """The real oracle (CCE 19 device run vs AFAR host run): the padded
    reproducer shrinks to the guarded loop."""
    oracle = fm.Oracle(fm.Failure("cce19", "wrong_code"))
    if not oracle(FIXTURE.read_text())[0]:
        pytest.skip("CCE 19 no longer shows the guarded-loop bug")
    res = fm.minimize(FIXTURE.read_text(), oracle, workers=6)
    out = res.source
    assert res.lines_after < res.lines_before - 20
    assert "!$omp target parallel" in out or "!$omp parallel" in out
    assert "omp_get_thread_num() == 0" in out
    assert "!$omp target teams" not in out


def test_ice_signature():
    a = fm.ice_signature('ice: INTERNAL COMPILER ERROR:  "unhandled '
                         'construct type" (/workspace/crayftn/pdgcs/'
                         'v_openmp.c, line 7617, version cc4d36e4ff)')
    b = fm.ice_signature('ice: INTERNAL COMPILER ERROR:  "unhandled '
                         'construct type" (/workspace/crayftn/pdgcs/'
                         'v_openmp.c, line 7617, version 0123abcd99)')
    assert a == b and "unhandled construct type" in a


# --- triage ---------------------------------------------------------------------------

def _fake_run(tmp_path) -> Path:
    d = tmp_path / "r"
    d.mkdir()
    rows = []
    for seed in range(1, 41):
        feats = ["kernel:loop", "map:to"] + (["guard:par_thread0"]
                                             if seed % 2 else ["map:from"])
        res = {"afar": fe.TcResult("afar", "agree", "checksum=1"),
               "cce19": fe.TcResult(
                   "cce19", "wrong_code" if seed % 2 else "agree",
                   "checksum=3 ran_on_host=0 expected=1"),
               "cce21": fe.TcResult(
                   "cce21", "ice" if seed % 5 == 0 else "compile_reject"
                   if seed % 3 == 0 else "agree",
                   'ice: INTERNAL COMPILER ERROR: "x" (v.c, line 1, '
                   'version abc)' if seed % 5 == 0 else
                   "diagnostic: ftn-1370 ftn: ERROR FUZZ_PROG, File = "
                   "../../f.f90, Line = 3, Column = 4 | no")}
        pr = fe.ProgramResult(seed, "fuzz-1", "ok", expected=1,
                              features=feats, results=res, lines=50,
                              seconds=10)
        rows.append(pr.to_json())
    rows.append(fe.ProgramResult(99, "fuzz-1", "flang",
                                 "semantics: t.f90:3:4: error: no").to_json())
    (d / "programs.jsonl").write_text("\n".join(rows) + "\n")
    (d / "meta.json").write_text(json.dumps({"sessions": [
        {"seconds": 100, "workers": 6, "gen_version": "fuzz-1"}]}))
    return d


def test_summary_counts(tmp_path):
    s = fr.summarize(_fake_run(tmp_path))
    assert s["legal_and_run"] == 40 and s["generator_rejects"]["total"] == 1
    assert s["classes"]["cce19"] == {"wrong_code": 20, "agree": 20}
    assert s["classes"]["cce21"]["ice"] == 8
    assert len(s["ice"]) == 1 and s["ice"][0]["programs"] == 8
    assert s["compile_reject_messages"]["cce21"][0]["programs"] == 11
    pair = s["feature_pairs"]["cce19"]["wrong_code"] or [{"pair": ["guard:par_thread0"], "lift": 2.0}]
    pair = pair[0]
    assert "guard:par_thread0" in pair["pair"] and pair["lift"] == 2.0
    assert s["known_findings"][next(iter(s["known_findings"]))][
        "programs"] == 20
    assert s["generator_rejects"]["by_cause"] == {
        "flang: semantics: error: no": {"count": 1, "seeds": [99]}}


def test_report_written(tmp_path):
    d = _fake_run(tmp_path)
    md = tmp_path / "fuzz.md"
    fr.write_report(d, md)
    text = md.read_text()
    assert "| wrong_code |" in text and (d / "summary.json").exists()


def test_distinct_dedupes_by_hash_and_signature():
    mins = [dict(status="minimized", kind="wrong_code", sha="a", seed=1,
                 toolchain="cce19", signature="", file="f1"),
            dict(status="minimized", kind="wrong_code", sha="a", seed=2,
                 toolchain="cce20", signature="", file="f2"),
            dict(status="minimized", kind="ice", sha="b", seed=3,
                 toolchain="cce19", signature="s", file="f3"),
            dict(status="minimized", kind="ice", sha="c", seed=4,
                 toolchain="cce19", signature="s", file="f4"),
            dict(status="not_reproduced", kind="ice", seed=5,
                 toolchain="afar", signature="t")]
    assert [d["file"] for d in fr._distinct(mins)] == ["f1", "f3"]


# --- Independent references and overflow bounds --------------------------------------------------------

def test_simplify_keeps_mod_and_iand_bounds():
    assert fm._operands("mod((a * b), 97)") == ["mod(a, 97)", "mod(b, 97)",
                                                "97", "0"]
    assert fm._operands("iand(x, 255)") == ["255", "0"]
    assert fm._operands("iand((x + y), 1023)") == ["iand(x, 1023)",
                                                  "iand(y, 1023)", "1023",
                                                  "0"]
    for seed in (3, 11, 42, 87, 1936, 1978):
        lines = fm.join_lines(fuzz.generate(seed).source)
        for c in fm.candidates(lines):
            if not c.what.startswith("simplify"):
                continue
            k = next(i for i, (a, b) in enumerate(zip(lines, c.lines))
                     if a != b)
            old = fm.split_assignment(lines[k].strip())[1]
            new = fm.split_assignment(c.lines[k].strip())[1]
            m = re.match(r"(mod|iand)\((.*)\)$", old)
            if m and fm._balanced(m.group(2)):
                assert new.startswith(m.group(1) + "(") or \
                    re.fullmatch(r"-?\d+", new), (seed, old, new)


def test_wrapper_kept_where_the_generator_bounds_a_value():
    # a top-level bound is never stripped: its operand appears only wrapped
    for fn in ("mod", "iand"):
        subs = fm._operands(f"{fn}((p * q), 7)")
        assert "(p * q)" not in subs and "p" not in subs and "q" not in subs


def test_references_come_from_another_compiler_family():
    with pytest.raises(ValueError, match="family"):
        fm.Oracle(fm.Failure("afar", "wrong_code"), ["afar"])
    with pytest.raises(ValueError, match="family"):
        fm.Oracle(fm.Failure("cce19", "wrong_code"), ["cce20", "afar"])
    assert [t.name for t in fm.Oracle(fm.Failure("cce19", "wrong_code"),
                                      ["afar"]).refs] == ["afar"]
    o = fm.Oracle(fm.Failure("afar", "wrong_code"), ["elision"])
    assert o.ref_names == ["elision"]
    # an ICE needs no reference at all
    fm.Oracle(fm.Failure("afar", "ice"), ["afar"])


def test_trusted_refs_skip_the_failing_family():
    sums = {"afar": 5, "cce19": 5, "cce20": 5, "cce21": 9}
    host = lambda name, src: sums[name]                     # noqa: E731
    assert fm.trusted_refs("src", 5, "afar", host=host,
                           elision=lambda s: None) == ["cce19"]
    assert fm.trusted_refs("src", 5, "cce19", host=host,
                           elision=lambda s: "checksum=5") == ["afar",
                                                              "elision"]
    # AFAR fails and no CCE compiles: elision is the only reference
    none = lambda name, src: 5 if name == "afar" else None  # noqa: E731
    assert fm.trusted_refs("src", 5, "afar", host=none,
                           elision=lambda s: "checksum=5") == ["elision"]
    assert fm.trusted_refs("src", 5, "afar", host=none,
                           elision=lambda s: "checksum=6") == []


def test_oracle_rejects_an_overflowing_candidate(monkeypatch):
    monkeypatch.setattr(fm, "check", lambda s: fuzz.CheckResult("ok"))
    monkeypatch.setattr(fm, "overflow_trap", lambda s: "integer overflow")
    o = fm.Oracle(fm.Failure("cce19", "wrong_code"), ["afar"])
    ok, why = o("program p\nend program\n")
    assert not ok and "overflow" in why


@pytest.mark.gfortran
@pytest.mark.skipif(not GFORTRAN, reason="gfortran is not installed")
def test_overflow_trap_runs_the_elided_program():
    bad = ("program p\n  integer :: a, i\n  a = 1\n  do i = 1, 40\n"
           "    a = a * 3 + 7\n  end do\n"
           "  print '(a,i0,a)', 'RESULT checksum=', a, ' ran_on_host=1'\n"
           "end program p\n")
    assert "overflow" in fm.overflow_trap(bad)
    for seed in (3, 87, 1936, 1978):
        assert fm.overflow_trap(fuzz.generate(seed).source) is None


def test_refine_run_updates_the_header_and_drops_same_family_refs(
        tmp_path, monkeypatch):
    """A stored same-family reference is not reused, and the header's
    expected/observed follow the new body."""
    finding = tmp_path / "87-afar.f90"
    finding.write_text(
        "! Minimized by compliance.fuzz_min from fuzz seed 87 (fuzz-1).\n"
        "! failure: wrong_code\n"
        "! expected: the host reference checksum (host reference (afar) "
        "checksum=1)\n"
        "! observed: device checksum=0 ran_on_host=0\n"
        "! also fails on: cce19\n"
        "program p\n  x = 1\n  y = 2\nend program p\n")
    run = tmp_path / "run"
    run.mkdir()
    (run / "minimized.json").write_text(json.dumps([{
        "seed": 87, "toolchain": "afar", "kind": "wrong_code",
        "signature": "", "status": "minimized", "file": str(finding),
        "references": ["afar"], "also_fails_on": ["cce19"],
        "verdict": "device checksum=0 ran_on_host=0; host reference (afar) "
                   "checksum=1"}]))
    seen = {}

    def fake_min(body, oracle, workers=6, log=None):
        seen["refs"] = oracle.ref_names
        return fm.MinResult("program p\n  x = 1\nend program p\n", 4, 3, [],
                            "device checksum=5 ran_on_host=0; host "
                            "reference (elision) checksum=7")
    monkeypatch.setattr(fm, "minimize", fake_min)
    state = fr.refine_run(run, log=lambda *a: None)
    assert seen["refs"] == ["elision"]
    text = finding.read_text()
    assert "! expected: the host reference checksum (host reference " \
        "(elision) checksum=7)" in text
    assert "! observed: device checksum=5 ran_on_host=0" in text
    assert "! also fails on: cce19" not in text
    assert "before refinement" in text
    assert state[0]["references"] == ["elision"]
    assert state[0]["observed"] == "device checksum=5 ran_on_host=0"


def test_resume_refuses_another_generator_version(tmp_path):
    """A resumed campaign must not mix generator
    versions silently."""
    (tmp_path / "programs.jsonl").write_text(json.dumps(
        {"seed": 1, "gen_version": "fuzz-1", "check": "ok"}) + "\n")
    with pytest.raises(ValueError, match="fuzz-1"):
        fe.campaign(tmp_path, [1, 2], workers=1, gen_version="fuzz-2",
                    log=lambda *a: None)


# --- Host-path validity --------------------------------------------------------------------------------

def _host_setup(tmp_path, monkeypatch, exes_by_tc, expected=42):
    """A ProgramResult whose toolchains compiled the given fake programs,
    with fe.TOOLCHAINS patched to the fakes."""
    pr = fe.ProgramResult(7, "x", "ok", expected=expected)
    exes = {}
    for name, exe in exes_by_tc.items():
        tc = fake_tc(name, exe=exe)
        monkeypatch.setitem(fe.TOOLCHAINS, name, tc)
        d = tmp_path / name
        d.mkdir(parents=True)
        r, path = fe.run_toolchain(fake_prog(expected), tc, d)
        pr.results[name] = r
        exes[name] = (path, d)
    return pr, exes


def test_host_verdict_rule():
    # (a) one host build (or elision) gives the model: valid, the others
    # are host-path failures
    assert fe.host_verdict(42, {"afar": None, "cce19": 42, "cce20": 5},
                           None) == ("valid", ["cce19"], ["afar", "cce20"])
    assert fe.host_verdict(42, {"afar": 5}, 42) == \
        ("valid", ["elision"], ["afar"])
    # (b) nothing gives the model: noncompliant, no host-path failure
    assert fe.host_verdict(42, {"afar": 5, "cce19": None}, 7) == \
        ("noncompliant", [], [])
    assert fe.host_verdict(42, {}, None) == ("noncompliant", [], [])


def test_failed_host_reference_is_host_ref_failed(tmp_path, monkeypatch):
    """A host reference run that fails is host_ref_failed, not
    host_mismatch; every other compiled binary still runs on the host."""
    pr, exes = _host_setup(tmp_path, monkeypatch,
                           {"afar": "fuzz_hostcrash.sh",
                            "cce19": "fuzz_agree.sh"})
    fe.host_reference(pr, fake_prog(), exes, elision=lambda src: None)
    assert pr.host_ref_failed and not pr.host_mismatch
    assert pr.host_ref is None and pr.host_ref_tc == "afar"
    assert pr.results["afar"].host_why.startswith("crash: SIGSEGV")
    assert pr.results["cce19"].host_checksum == 42
    assert (pr.validity, pr.host_witnesses, pr.host_path_failure) == \
        ("valid", ["cce19"], ["afar"])


def test_host_mismatch_with_no_witness_is_noncompliant(tmp_path,
                                                       monkeypatch):
    pr, exes = _host_setup(tmp_path, monkeypatch,
                           {"afar": "fuzz_hostwrong.sh",
                            "cce19": "fuzz_hostwrong.sh"})
    fe.host_reference(pr, fake_prog(), exes, elision=lambda src: None)
    assert pr.host_mismatch and not pr.host_ref_failed
    assert (pr.validity, pr.host_path_failure) == ("noncompliant", [])
    # elision giving the model makes it valid; both hosts then failed
    pr, exes = _host_setup(tmp_path / "b", monkeypatch,
                           {"afar": "fuzz_hostwrong.sh",
                            "cce19": "fuzz_hostwrong.sh"})
    fe.host_reference(pr, fake_prog(), exes, elision=lambda src: 42)
    assert (pr.validity, pr.host_witnesses, pr.host_path_failure) == \
        ("valid", ["elision"], ["afar", "cce19"])
    assert pr.elision == "checksum=42"


def test_agreeing_host_reference_stays_valid(tmp_path, monkeypatch):
    pr, exes = _host_setup(tmp_path, monkeypatch,
                           {"afar": "fuzz_agree.sh",
                            "cce19": "fuzz_hostwrong.sh"})
    fe.host_reference(pr, fake_prog(), exes,
                      elision=lambda src: pytest.fail("not needed"))
    assert not pr.host_mismatch and not pr.host_ref_failed
    assert pr.validity == "valid" and pr.host_path_failure == []
    assert pr.results["cce19"].host_checksum is None  # not run


def test_old_records_split_failed_reference_from_mismatch():
    """Records written before this check marked a failed reference run
    host_mismatch; loading them separates the two."""
    old = {"seed": 3, "gen_version": "fuzz-1", "check": "ok",
           "expected": 1, "results": {}, "host_ref": None,
           "host_ref_tc": "afar", "host_mismatch": True}
    pr = fe.ProgramResult.from_json(json.dumps(old))
    assert pr.host_ref_failed and not pr.host_mismatch
    old.update(host_ref=2)
    pr = fe.ProgramResult.from_json(json.dumps(old))
    assert pr.host_mismatch and not pr.host_ref_failed


def test_recheck_host_rebuilds_on_every_toolchain(tmp_path, monkeypatch):
    for name, exe in (("afar", "fuzz_hostcrash.sh"),
                      ("cce19", "fuzz_hostwrong.sh"),
                      ("cce20", "fuzz_agree.sh")):
        monkeypatch.setitem(fe.TOOLCHAINS, name, fake_tc(name, exe=exe))
    monkeypatch.setitem(fe.TOOLCHAINS, "cce21",
                        fake_tc("cce21", "cce_syntax_error", rc=1, exe=None))
    rec = fe.recheck_host(fake_prog(), elision=lambda src: None)
    assert rec["host"]["afar"]["checksum"] is None
    assert rec["host"]["afar"]["why"].startswith("crash: SIGSEGV")
    assert rec["host"]["cce19"]["checksum"] == 5
    assert rec["host"]["cce20"]["checksum"] == 42
    assert rec["host"]["cce21"]["build"] == "compile_reject"
    assert (rec["validity"], rec["witnesses"], rec["host_path_failure"]) \
        == ("valid", ["cce20"], ["afar", "cce19"])
    # every host run is repeated; differing repeats are no witness
    assert len(rec["host"]["cce20"]["runs"]) == fe.HOST_RUNS


def test_hostcheck_overlays_the_campaign(tmp_path):
    d = tmp_path / "r"
    d.mkdir()
    pr = fe.ProgramResult(3, "fuzz-1", "ok", expected=1, results={
        "afar": fe.TcResult("afar", "agree", "", 1),
        "cce19": fe.TcResult("cce19", "wrong_code", "", 2)},
        host_ref=None, host_ref_tc="afar", host_ref_failed=True)
    (d / "programs.jsonl").write_text(pr.to_json() + "\n")
    rec = {"seed": 3, "expected": 1,
           "host": {"afar": {"build": "ok", "checksum": None,
                             "why": "crash: SIGSEGV", "runs": []},
                    "cce19": {"build": "ok", "checksum": 1, "why": "",
                              "runs": []}},
           "elision": "inapplicable: present modifier",
           "validity": "valid", "witnesses": ["cce19"],
           "host_path_failure": ["afar"]}
    (d / fe.HOSTCHECK).write_text(json.dumps(rec) + "\n")
    p = fe.load(d)[0][0]
    assert p.results["cce19"].host_checksum == 1
    assert p.results["afar"].host_why == "crash: SIGSEGV"
    assert (p.validity, p.host_witnesses, p.host_path_failure,
            p.host_rechecked) == ("valid", ["cce19"], ["afar"], True)


def _validity_run(tmp_path) -> Path:
    d = _fake_run(tmp_path)
    progs = [json.loads(ln) for ln in
             (d / "programs.jsonl").read_text().splitlines()]
    for p in progs:
        if p["seed"] == 1:      # cce19 wrong code, but noncompliant
            p.update(host_mismatch=True, host_ref=9, host_ref_tc="afar",
                     validity="noncompliant")
        if p["seed"] == 2:      # valid, AFAR host path crashed
            p.update(host_ref_failed=True, host_ref=None, host_ref_tc="afar",
                     validity="valid", host_witnesses=["cce19"],
                     host_path_failure=["afar"])
            p["results"]["afar"]["host_why"] = "crash: SIGSEGV"
    (d / "programs.jsonl").write_text(
        "\n".join(json.dumps(p) for p in progs) + "\n")
    return d


def test_noncompliant_programs_leave_the_tallies(tmp_path):
    s = fr.summarize(_validity_run(tmp_path))
    assert s["legal_and_run"] == 40 and s["judged"] == 39
    assert [n["seed"] for n in s["noncompliant"]] == [1]
    assert s["classes"]["cce19"] == {"wrong_code": 19, "agree": 20}
    assert 1 not in s["wrong_code"]["cce19"]["seeds"]
    assert s["host_path_failure"]["afar"]["seeds"] == [2]
    assert [h["seed"] for h in s["host_ref_failed"]] == [2]
    assert [h["seed"] for h in s["host_mismatch"]] == [1]
    assert all(1 not in v["seeds"] for v in s["known_findings"].values())


def test_report_lists_noncompliant_and_host_path_failures(tmp_path):
    d = _validity_run(tmp_path)
    md = tmp_path / "fuzz.md"
    fr.write_report(d, md)
    text = md.read_text()
    assert "## Appendix: host reference checks (not offload findings)" \
        in text
    assert "### Noncompliant programs" in text
    assert "host_path_failure" in text
    assert "Host reference disagreeing with the model" not in text


def test_noncompliant_programs_are_not_minimized(tmp_path):
    progs, _ = fe.load(_validity_run(tmp_path))
    assert 1 not in {r[0] for r in fr.representatives(progs, 40)}


def test_recheck_host_timeout_is_a_failure_and_long_by_default(
        tmp_path, monkeypatch):
    """A host run (all cores, OpenMP host threads) on a loaded login node
    can take far longer than a device run: the recheck's limit is
    HOST_TIMEOUT_S, and a run over the limit is no witness."""
    assert fe.HOST_TIMEOUT_S >= 5 * fe.RUN_TIMEOUT_S
    monkeypatch.setitem(fe.TOOLCHAINS, "afar",
                        fake_tc("afar", exe="fuzz_hostslow.sh"))
    rec = fe.recheck_host(fake_prog(), ("afar",), runs=1,
                          elision=lambda s: None, timeout_s=1)
    assert rec["host"]["afar"]["why"] == "timeout"
    assert rec["validity"] == "noncompliant"
    rec = fe.recheck_host(fake_prog(), ("afar",), runs=1,
                          elision=lambda s: None)
    assert rec["witnesses"] == ["afar"]


def test_minimized_finding_has_its_own_header():
    """A minimized reproducer (tools/campaigns/fuzz.py minimize-one, minimize_run)
    carries the finding header: the toolchain, the failure, the expected
    and observed values of the minimized program; never the generator's
    header of the original (its seed line, expected checksum, kernels)."""
    from offload.engine import fuzz_min as fm
    from offload.engine import fuzz_report as fr
    gen = fuzz.generate(7, "fuzz-3", ("derived",)).source
    assert "! expected checksum:" in gen
    failure = fm.Failure("cce19", "wrong_code", "", 0)
    text = fr.finding_text(7, failure, "fuzz-3", gen,
                           "checksum=11 ran_on_host=0; reference "
                           "checksum=42")
    head = [ln for ln in text.splitlines() if ln.startswith("! ")]
    assert head[0] == "! Minimized by compliance.fuzz_min from fuzz seed 7 " \
        "(fuzz-3)."
    assert "! expected: the host reference checksum (reference " \
        "checksum=42)" in head
    assert "! observed: checksum=11 ran_on_host=0" in head
    assert not any(ln.startswith(("! expected checksum:", "! generator:",
                                  "! seed:", "! kernel ")) for ln in head)
    assert text.endswith(fm.strip_header(gen))
    text = fr.finding_text(7, failure, "fuzz-3", gen, "v", also=["cce20"])
    assert "! also fails on: cce20" in text.splitlines()


def test_reelide_recomputes_validity_from_stored_host_runs():
    """host-check --elision-only: a stored host-check record keeps its host
    runs; the sequential elision and the maintainer's validity rule are applied
    again (an analysis that now applies can make a program valid)."""
    rec = {"seed": 5, "expected": 42, "elision": "inapplicable: x",
           "validity": "noncompliant", "witnesses": [],
           "host_path_failure": [],
           "host": {"afar": {"build": "ok", "checksum": 7, "why": "",
                             "runs": []},
                    "cce19": {"build": "compile_reject", "checksum": None,
                              "why": "", "runs": []}}}
    new = fe.reelide(rec, "src", elision=lambda s: 42)
    assert new["validity"] == "valid" and new["witnesses"] == ["elision"]
    assert new["host_path_failure"] == ["afar"]
    assert new["elision"] == "checksum=42" and new["host"] == rec["host"]
    new = fe.reelide(rec, "src", elision=lambda s: "inapplicable: y")
    assert new["validity"] == "noncompliant" and new["elision"] == \
        "inapplicable: y"


def test_elision_section_of_the_base_review(tmp_path):
    """The sequential-elision table, from each run's
    elision.jsonl (tools/campaigns/fuzz.py elide): programs, how many elision
    applies to, how many of those print the model's value, and the most
    frequent reasons it does not apply."""
    d = tmp_path / "b2"
    d.mkdir()
    recs = [{"seed": 1, "expected": 5, "applicable": True, "value": 5},
            {"seed": 2, "expected": 6, "applicable": True, "value": 7},
            {"seed": 3, "expected": 6, "applicable": False, "value": None,
             "why": "present modifier"},
            {"seed": 4, "expected": 6, "applicable": False, "value": None,
             "why": "present modifier; module variables (declare target "
                    "visibility)"},
            {"seed": 5, "expected": 6, "applicable": True, "value": None,
             "why": "no value: gfortran build failed"}]
    (d / "elision.jsonl").write_text("".join(json.dumps(r) + "\n"
                                             for r in recs))
    L = fr._elision_section([d], [{"run_id": "b2", "base": ["derived"]}])
    text = "\n".join(L)
    assert "## Sequential elision" in text
    row = next(ln for ln in L if ln.startswith("| `b2`"))
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[1:6] == ["5", "3", "1", "1", "1"]
    assert "present modifier (2)" in cells[6]
    assert "seed 2" in text          # a disagreement is named
    assert fr._elision_section([tmp_path / "none"], [{"run_id": "x",
                                                      "base": []}]) == []


def test_checker_errors_are_not_generator_rejects(tmp_path):
    """Check stage `error` (a checker could not
    run) is an environment failure, counted apart from the generator's
    legality rejects."""
    d = _fake_run(tmp_path)
    row = fe.ProgramResult(98, "fuzz-1", "error",
                           "gfortran: No such file or directory").to_json()
    with (d / "programs.jsonl").open("a") as f:
        f.write(row + "\n")
    s = fr.summarize(d)
    assert s["generator_rejects"]["total"] == 1
    assert "error" not in s["generator_rejects"]["by_stage"]
    assert s["checker_errors"] == {"total": 1, "seeds": [98]}
    md = tmp_path / "fuzz.md"
    fr.write_report(d, md)
    assert "checker errors (a checker could not run): 1" in md.read_text()


def test_report_without_checker_errors_does_not_mention_them(tmp_path):
    md = tmp_path / "fuzz.md"
    s = fr.write_report(_fake_run(tmp_path), md)
    assert s["checker_errors"] == {"total": 0, "seeds": []}
    assert "checker errors" not in md.read_text()


# --- A campaign run as several run ids, merged ---------------------------------

def _chunk(d, seeds, xnack=1, base=("types",), extra=True):
    d.mkdir(parents=True)
    rows = [fe.ProgramResult(s, "fuzz-3", "ok", expected=s, base=list(base),
                             results={"afar": fe.TcResult("afar", "agree",
                                                          "", s)})
            for s in seeds]
    (d / "programs.jsonl").write_text("".join(r.to_json() + "\n"
                                              for r in rows))
    (d / "meta.json").write_text(json.dumps({"sessions": [
        {"run_id": d.name, "gen_version": "fuzz-3", "base": list(base),
         "seeds": [seeds[0], seeds[-1]], "toolchains": ["afar"],
         "xnack": xnack, "seconds": 10}]}))
    if extra:
        (d / fe.ELISION_FILE).write_text("".join(json.dumps(
            {"seed": s, "expected": s, "applicable": False, "value": None,
             "why": "x"}) + "\n" for s in seeds))


def test_merge_runs_concatenates_chunks(tmp_path):
    _chunk(tmp_path / "s-00", [1, 2])
    _chunk(tmp_path / "s-01", [3, 4], extra=False)
    rec = {"seed": 3, "expected": 3, "host": {}, "elision": "x",
           "validity": "valid", "witnesses": [], "host_path_failure": []}
    (tmp_path / "s-01" / fe.HOSTCHECK).write_text(json.dumps(rec) + "\n")
    out = tmp_path / "s"
    fe.merge_runs(out, [tmp_path / "s-01", tmp_path / "s-00"])
    progs, _ = fe.load(out)
    assert [p.seed for p in progs] == [1, 2, 3, 4]
    meta = json.loads((out / "meta.json").read_text())
    assert meta["merged_from"] == ["s-00", "s-01"]
    assert [s["run_id"] for s in meta["sessions"]] == ["s-00", "s-01"]
    assert len((out / fe.HOSTCHECK).read_text().splitlines()) == 1
    assert len((out / fe.ELISION_FILE).read_text().splitlines()) == 2
    # merging again is idempotent (the output is rewritten from the chunks)
    fe.merge_runs(out, [tmp_path / "s-00", tmp_path / "s-01"])
    assert len(fe.load(out)[0]) == 4


def test_merge_refuses_mixed_configurations_and_repeated_seeds(tmp_path):
    import pytest
    _chunk(tmp_path / "a", [1, 2])
    _chunk(tmp_path / "b", [3], xnack=0)
    _chunk(tmp_path / "c", [2])
    _chunk(tmp_path / "d", [5], base=("alloc",))
    for other in ("b", "c", "d"):
        with pytest.raises(ValueError):
            fe.merge_runs(tmp_path / f"m{other}", [tmp_path / "a",
                                                   tmp_path / other])


# --- Generator defect G1 and generator fuzz-4 ------------------------------------

G1_SRC = """program p
  logical :: lsimd
  integer :: a(8), i
  lsimd = .true.
  !$omp target map(tofrom: a)
  !$omp parallel do simd if(simd: lsimd) default(none) &
  !$omp& shared(a)
  do i = 1, 8
    a(i) = i
  end do
  !$omp end target
end program p
"""


def test_generator_defect_g1_found_statically():
    """G1: default(none) on a combined construct whose
    if(<leaf>:) clause names a leaf nested inside the default's leaf: the
    expression is evaluated inside that region, so its variable must be
    listed (5.2 §17.2 p.340, §5.4.1 p.109)."""
    from offload.engine import fuzz
    got = fuzz.generator_defects(G1_SRC)
    assert len(got) == 1 and got[0].startswith("G1") and "lsimd" in got[0]
    ok = G1_SRC.replace("shared(a)", "shared(a) firstprivate(lsimd)")
    assert fuzz.generator_defects(ok) == []
    # the parallel leaf's own if clause is evaluated outside its region
    own = G1_SRC.replace("parallel do simd if(simd: lsimd)",
                         "parallel do if(parallel: lsimd)")
    assert fuzz.generator_defects(own) == []
    teams = G1_SRC.replace("parallel do simd if(simd: lsimd)",
                           "teams distribute parallel do if(parallel: "
                           "lsimd)")
    assert len(fuzz.generator_defects(teams)) == 1


def test_fuzz4_lists_nested_if_variables_and_replays_fuzz3_otherwise():
    """The s1 seeds with G1 (fuzz-3, all base groups): fuzz-4 lists the
    variable, the model value and every other line are fuzz-3's."""
    from offload.engine import fuzz
    base = ("types", "derived", "alloc", "declare", "multitu")
    for seed in (10, 372, 2750):
        a = fuzz.generate(seed, "fuzz-3", base)
        b = fuzz.generate(seed, "fuzz-4", base)
        assert fuzz.generator_defects(a.source)
        assert fuzz.generator_defects(b.source) == []
        assert a.expected == b.expected
        da = [x for x in a.source.splitlines()
              if not x.startswith("! generator:")]
        db = [x for x in b.source.splitlines()
              if not x.startswith("! generator:")]
        assert len(da) == len(db)
        assert sum(x != y for x, y in zip(da, db)) <= 2
    s = fuzz.generate(11, "fuzz-3", base).source
    assert fuzz.generate(11, "fuzz-4", base).source.replace(
        "! generator: fuzz-4", "! generator: fuzz-3") == s


def test_check_rules_reports_generator_defects():
    from offload.engine import fuzz
    why = fuzz.check_rules(G1_SRC)
    assert why and "G1" in why


def test_run_error_signature_keeps_the_signal_and_message(monkeypatch):
    """A run_error failure "crash: SIGSEGV" is kept
    only by a SIGSEGV (not any crash), and a message after " | " must be in
    the device run's output; a bare "crash" keeps the class only."""
    from offload.engine import fuzz_exec as fe
    monkeypatch.setattr(fm, "check", lambda s: fuzz.CheckResult("ok"))
    monkeypatch.setattr(fm, "overflow_trap", lambda s: None)
    monkeypatch.setattr(fm.fe, "compile_program",
                        lambda *a, **k: (None, "", "", ""))
    dev = {}
    monkeypatch.setattr(fm.fe, "execute", lambda tc, exe, tmp, mode, *a:
                        dev["run"] if mode == "mandatory" else
                        fe.Run("ok", 5, 1))

    def judge(sig, why, err=""):
        dev["run"] = fe.Run("fail", why=why, stderr=err)
        o = fm.Oracle(fm.Failure("afar", "run_error", sig), ["cce21"])
        monkeypatch.setattr(o, "_host", lambda *a: fe.Run("ok", 5, 1))
        return o._run("program p\nend program p\n", __import__(
            "pathlib").Path(__import__("tempfile").mkdtemp()))[0]
    assert judge("crash: SIGSEGV", "crash: SIGSEGV")
    assert not judge("crash: SIGSEGV", "crash: SIGABRT")
    assert judge("crash", "crash: SIGABRT")
    assert judge("crash: SIGABRT | memory access fault", "crash: SIGABRT",
                 "OFFLOAD ERROR: memory access fault by GPU 1")
    assert not judge("crash: SIGABRT | memory access fault",
                     "crash: SIGABRT", "free(): invalid next size")


def test_fuzz_4s50_spellings():
    """Fuzz-4s50 is the fuzz-4 program of the seed with the
    OpenMP 5.0/5.1 spelling of each construct whose 5.2 spelling has an exact
    5.0/5.1 equivalent; the model and every other line are fuzz-4's."""
    from offload.engine import fuzz as F
    assert F.GEN_VERSION == "fuzz-4" and "fuzz-4s50" in F.GEN_VERSIONS
    src = ("  !$omp declare target enter(g1, g2)\n"
           "  !$omp target teams distribute map(tofrom: x) &\n"
           "  !$omp& defaultmap(default: all) order(unconstrained: concurrent)\n"
           "  !$omp target enter data map(to: a)\n"
           "  x = 1 ! enter(\n")
    out = F.spell50(src)
    assert "declare target to(g1, g2)" in out
    assert "defaultmap(default)" in out and "all)" not in out
    assert "order(concurrent)" in out
    assert "target enter data map(to: a)" in out
    assert out.splitlines()[-1] == "  x = 1 ! enter("
    base = ("types", "derived", "alloc", "declare", "multitu")
    changed = 0
    for seed in range(1, 41):
        a = F.generate(seed, "fuzz-4", base)
        b = F.generate(seed, "fuzz-4s50", base)
        assert a.expected == b.expected and a.features == b.features
        assert b.source == F.spell50(a.source).replace(
            "! generator: fuzz-4\n", "! generator: fuzz-4s50\n")
        assert "enter(" not in "\n".join(
            ln for ln in b.source.splitlines() if "declare target" in ln)
        changed += a.source.replace("fuzz-4\n", "") != \
            b.source.replace("fuzz-4s50\n", "")
    assert changed > 5


def test_join_toolchains(tmp_path):
    """The AMD run and the NVHPC runs of the same seeds join into
    one campaign directory (the base run's gate and host fields kept)."""
    import json
    from offload.engine import fuzz_exec as FE
    def run(name, tcs, extra=None):
        d = tmp_path / name
        d.mkdir()
        rows = [{"seed": s, "gen_version": "fuzz-4s50", "expected": s * 7,
                 "base": [], "validity": "valid" if extra is None else "x",
                 "results": {t: {"cls": "agree"} for t in tcs}}
                for s in (1, 2)]
        (d / "programs.jsonl").write_text("".join(json.dumps(r) + "\n"
                                                  for r in rows))
        (d / "meta.json").write_text(json.dumps(
            {"gen_version": "fuzz-4s50", "base": [], "toolchains": tcs}))
        return d
    a = run("amd", ["afar", "cce19"])
    n = run("nv", ["nvhpc"], extra=True)
    info = FE.join_toolchains(tmp_path / "j", a, [n])
    assert info["toolchains_added"] == ["nvhpc"]
    rows = [json.loads(l) for l in (tmp_path / "j" / "programs.jsonl")
            .read_text().splitlines()]
    assert [sorted(r["results"]) for r in rows] == [
        ["afar", "cce19", "nvhpc"]] * 2
    assert all(r["validity"] == "valid" for r in rows)
    with pytest.raises(ValueError):
        FE.join_toolchains(tmp_path / "k", a, [a])


def test_report_header_of_a_joined_x0_campaign(tmp_path):
    """A campaign of several sessions
    (concurrent chunks, joined toolchain runs) reports each session's time
    and workers, not their sum with the last session's workers, and the
    memory mode it ran in (HSA_XNACK=0, NVHPC separate memory), not
    HSA_XNACK=1."""
    d = _fake_run(tmp_path)
    (d / "meta.json").write_text(json.dumps({"sessions": [
        {"run_id": "n1x0-00", "seconds": 1958, "workers": 12, "xnack": 0,
         "gen_version": "fuzz-4s50", "toolchains": ["afar", "cce19"]},
        {"run_id": "n1x0-nvhpc", "seconds": 5207, "workers": 1, "xnack": 0,
         "gen_version": "fuzz-4s50", "toolchains": ["nvhpc"]}]}))
    md = tmp_path / "fuzz.md"
    fr.write_report(d, md)
    text = md.read_text()
    assert "HSA_XNACK=1" not in text.split("## Size and timing")[0]
    assert "HSA_XNACK=0" in text and "separate memory" in text
    assert "with 1 workers" not in text
    assert "n1x0-00: 1958 s with 12 workers" in text
    assert "n1x0-nvhpc: 5207 s with 1 worker" in text


def test_report_header_of_one_session_is_unchanged(tmp_path):
    d = _fake_run(tmp_path)
    md = tmp_path / "fuzz.md"
    fr.write_report(d, md)
    text = md.read_text()
    assert "at -O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory" in text
    assert "campaign wall time: 100 s with 6 workers" in text


def test_report_renders_the_campaign_note_of_its_run(tmp_path, monkeypatch):
    """A run's note in catalog/fuzz_campaigns.yaml
    (run_notes) is a Notes section of its report (n1x0: the seed-72
    strays on the NVHPC GPUs)."""
    d = _fake_run(tmp_path)
    camp = tmp_path / "campaigns.yaml"
    camp.write_text("version: 1\ncampaigns:\n  x:\n    runs: [" + d.name
                    + "]\n    run_notes:\n      " + d.name
                    + ": \"two strays held GPUs 0 and 1\"\n")
    monkeypatch.setattr(fr, "CAMPAIGNS", camp)
    md = tmp_path / "fuzz.md"
    fr.write_report(d, md)
    text = md.read_text()
    assert "## Notes\n\n- two strays held GPUs 0 and 1\n" in text
    assert text.index("## Notes") < text.index("## Classes per toolchain")


# ---- Tests of the base-language axis of the fuzz generator (generator fuzz-3, offload.engine.fuzz_base): replay of the older generator ----

from fractions import Fraction as Q


from offload.engine import fuzz, fuzz_base as fb, fuzz_exec as fe
from offload.engine.toolchains import TOOLCHAINS

GFORTRAN_2 = Path(fuzz.GFORTRAN).is_file()


def _as_fuzz2(src: str) -> str:
    src = src.replace("! generator: fuzz-3", "! generator: fuzz-2")
    return "\n".join(ln for ln in src.split("\n")
                     if not ln.startswith(("! base groups:",
                                           "! base features:")))


# --- versions and groups -----------------------------------------------------------

def test_fuzz3_without_groups_is_the_fuzz2_program():
    for seed in range(1, 41):
        a, b = fuzz.generate(seed, "fuzz-2"), fuzz.generate(seed, "fuzz-3")
        assert _as_fuzz2(b.source) == a.source
        assert a.expected == b.expected and a.features == b.features
        assert b.base == () and b.base_features == ()


def test_older_versions_replay():
    """Model values of c1 programs (fuzz-1) quoted in the report."""
    assert fuzz.generate(1525, "fuzz-1").expected == 563900162
    assert fuzz.generate(1759, "fuzz-1").expected == 1217412315


def test_groups_need_fuzz3_and_known_names():
    with pytest.raises(ValueError):
        fuzz.generate(1, "fuzz-2", ("types",))
    with pytest.raises(ValueError):
        fuzz.generate(1, "fuzz-3", ("nosuch",))


def test_types_programs_record_their_base_features():
    for seed in (1, 2, 3, 50):
        a = fuzz.generate(seed, "fuzz-3", ("types",))
        b = fuzz.generate(seed, "fuzz-3", ("types",))
        assert a.source == b.source and a.expected == b.expected
        assert a.base == ("types",)
        assert "base:group:types" in a.features
        assert "! base groups: types\n" in a.source
        assert all(f.startswith("base:") for f in a.base_features)
        assert any(f.startswith("base:type:") for f in a.base_features)
        assert all(len(ln) <= 132 for ln in a.source.splitlines())


def test_types_feature_mix():
    feats = set()
    for seed in range(1, 121):
        feats |= fuzz.generate(seed, "fuzz-3", ("types",)).features
    for t in ("real4", "real8", "complex4", "complex8", "logical", "char",
              "int1", "int2", "int8"):
        assert f"base:type:{t}" in feats, t
        assert f"base:out:{t}" in feats, t
    for f in ("base:type:char_scalar", "base:spell:double_precision",
              "base:view:real8", "base:view:char", "base:red:real8:+",
              "base:red:complex8:+"):
        assert f in feats, f
    assert any(f.startswith("base:red:logical:.") for f in feats)
    assert any(re.match(r"base:red:int[128]:", f) for f in feats)
    assert any(f.startswith("base:red:") and f.endswith(":atomic")
               for f in feats)


# --- the typed model ---------------------------------------------------------------

def test_real_literals_and_intrinsics():
    assert fb.rlit(Q(5, 2), 8) == "2.5_8"
    assert fb.rlit(Q(-3), 4) == "(-3.0)"
    assert fb.rlit(Q(-3), 8, dp=True, paren=False) == "-3.0d0"
    assert fb.rlit(Q(1, 8), 4) == "0.125"
    assert fb.nint_q(Q(5, 2)) == 3 and fb.nint_q(Q(-5, 2)) == -3
    assert fb.nint_q(Q(-7, 4)) == -2
    assert fb.fortran_mod_q(Q(-2049, 2), Q(1024)) == Q(-1, 2)
    assert int(Q(-7, 2)) == -3     # Fortran INT truncates


def test_complex_and_bounds():
    z = fb.CBin("*", fb.CConst(Q(3), Q(-2), 8), fb.CConst(Q(1), Q(1), 8))
    assert z.ev({}, {}) == (Q(5), Q(1))      # (3-2i)(1+i) = 5+i
    assert z.f() == "((3.0_8, -2.0_8) * (1.0_8, 1.0_8))"
    x = fb.RBin("*", fb.RBin("+", fb.RConst(Q(3), 4), fb.RConst(Q(-5), 4)),
                fb.RConst(Q(1, 2), 4))
    assert x.ev({}, {}) == Q(-1) and x.bound() == Q(4)
    assert fb.real_limit(4) * fb.DEN == 2 ** 23


def test_contributions_and_checksum_terms():
    assert fb.contributions("real4", Q(-3, 4)) == [-48]
    assert fb.contributions("complex8", (Q(1), Q(-1, 2))) == [64, -32]
    assert fb.contributions("logical", True) == [1]
    assert fb.contributions("char", "Ab1#") == [65, 98, 49, 35]
    assert fb.contributions("int1", 100) == [100]
    with pytest.raises(fb.Overflow):
        fb.contributions("real8", Q(1, 128))
    assert fb.checksum_terms("complex4", "z(i)") == [
        "int(real(z(i)) * 64, 8)", "int(aimag(z(i)) * 64, 8)"]
    assert len(fb.checksum_terms("char", "c(i)")) == fb.CHAR_LEN


def test_race_check_flags_a_shared_element():
    arrs = {"o": {(1,): 0, (2,): 0}}
    t = fuzz._Tracked(arrs)
    t.point = (1,)
    t["o"][(1,)] = 5
    t.point = (2,)
    t["o"][(2,)] = t["o"][(2,)] + 1
    assert t.race() is None
    t.point = (3,)
    _ = t["o"][(1,)]       # another point reads what point 1 wrote
    assert "o[1]" in t.race()


def test_race_redraws_never_happen_in_a_sample():
    for seed in range(1, 41):
        g = fuzz._Gen(seed, "fuzz-3", ("types",))
        g.build()
        assert g.race_redraws == 0, seed


# --- checks --------------------------------------------------------------------

UNDEFINED = """\
! generator: fuzz-3
program fuzz_prog
  implicit none
  integer :: a(4), i
  integer(8) :: cs
  cs = 0
  do i = 1, 3
    a(i) = i
  end do
  ! fuzz: kernels
  ! fuzz: checksum
  cs = modulo(cs * 31_8 + int(a(4), 8), 2147483629_8)
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', 0
end program fuzz_prog
"""


@pytest.mark.needs_compiler("afar")
@pytest.mark.gfortran
@pytest.mark.skipif(not GFORTRAN_2, reason="gfortran is not installed")
def test_definedness_check():
    why = fuzz.check_defined(UNDEFINED)
    assert why and "undefined value read" in why
    good = UNDEFINED.replace("do i = 1, 3", "do i = 1, 4")
    assert fuzz.check_defined(good) is None
    assert fuzz.check_defined(good, expected=4) is None
    assert "the model 5" in fuzz.check_defined(good, expected=5)
    oob = good.replace("int(a(4), 8)", "int(a(i), 8)")   # i = 5
    assert "definedness" in fuzz.check_defined(oob)
    c = fuzz.check(UNDEFINED)
    assert c.stage == "defined"
    # only fuzz-3 programs get the check unless asked
    assert fuzz.check(UNDEFINED.replace("fuzz-3", "fuzz-2")).stage != \
        "defined"


def _sample_ok(base, seeds):
    """The failing checks of a sample (within the sample budget: a hang
    fails the test, tests/bounded.py)."""
    def one(seed):
        # the current generator (fuzz-4 fixes G1, which fuzz-3
        # seed 10 with every group has)
        p = fuzz.generate(seed, fuzz.GEN_VERSION, base)
        return seed, fuzz.check(p.source, expected=p.expected)
    return {s: f"{c.stage}: {c.detail}" for s, c in bounded_map(one, seeds)
            if not c.ok}


@pytest.mark.gfortran
@pytest.mark.skipif(not GFORTRAN_2, reason="gfortran is not installed")
def test_types_sample_passes_every_check():
    """offload.engine.rules, gfortran -std=f2008, AFAR flang's frontend and the
    definedness check, whose sequential value must equal the model's."""
    assert _sample_ok(("types",), range(1, 81)) == {}


HOST_SAMPLES = {
    ("types",): {"base:out:real4", "base:out:complex8", "base:out:int8",
                 "base:out:char", "base:out:logical"},
    ("derived",): {"base:dt:out:ds", "base:dt:out:dr%nd",
                   "base:dt:map:components"},
    ("alloc",): {"base:al:kernel_in_internal_procedure",
                 "base:al:pointer_component", "base:al:pointer_output:target"},
    ("declare",): {"base:dc:declare_target_output",
                   "base:dc:declare_reduction", "base:dc:call_across_modules"},
    ("multitu",): {"base:mt:submodule", "base:mt:external_function"},
}


@pytest.mark.gpu
@pytest.mark.parametrize("base", list(HOST_SAMPLES))
def test_model_matches_a_host_run_2(tmp_path, base):
    """The model's checksum is what AFAR's and CCE 20's host builds print."""
    done = 0
    for seed in range(1, 60):
        prog = fuzz.generate(seed, "fuzz-3", base)
        if not (HOST_SAMPLES[base] & prog.features):
            continue
        for name in ("afar", "cce20"):
            d = tmp_path / f"{seed}-{name}"
            d.mkdir()
            src, exe = d / "p.f90", d / "p.out"
            src.write_text(prog.source)
            cls, _, _, _ = fe.compile_program(TOOLCHAINS[name], src, exe, d)
            if cls is not None:
                continue
            run = fe.execute(TOOLCHAINS[name], exe, d, "disabled")
            assert run.kind == "ok", (seed, name, run.why)
            assert run.checksum == prog.expected, (seed, name)
        done += 1
        if done == 3:
            break
    assert done == 3


# --- campaign records ----------------------------------------------------------------

def test_records_carry_the_base_groups(tmp_path):
    pr = fe.ProgramResult(4, "fuzz-3", "ok", base=["types"])
    back = fe.ProgramResult.from_json(pr.to_json())
    assert back.base == ["types"]
    assert fe.regenerate(back).source == \
        fuzz.generate(4, "fuzz-3", ("types",)).source
    old = json.loads(pr.to_json())
    del old["base"]
    assert fe.ProgramResult.from_json(json.dumps(old)).base == []


def test_resume_refuses_other_base_groups(tmp_path):
    rec = fe.ProgramResult(1, "fuzz-3", "ok", base=["types"])
    (tmp_path / "programs.jsonl").write_text(rec.to_json() + "\n")
    with pytest.raises(ValueError, match="base groups"):
        fe.campaign(tmp_path, [1, 2], workers=1, gen_version="fuzz-3",
                    base=(), log=lambda *_: None)


# --- stage 2: derived types ------------------------------------------------------

def test_derived_feature_mix():
    feats = set()
    for seed in range(1, 121):
        feats |= fuzz.generate(seed, "fuzz-3", ("derived",)).features
    for f in ("base:dt:struct", "base:dt:nested", "base:dt:aos",
              "base:dt:scalar_component", "base:dt:default_init",
              "base:dt:map:whole", "base:dt:map:components",
              "base:dt:map:implicit", "base:dt:map:component_section",
              "base:dt:out:dr", "base:dt:out:dr%nd", "base:dt:out:ds",
              "base:dt:component:aos:real8", "base:dt:target_update_component"):
        assert f in feats, f


def _target_regions(src):
    from offload.engine import fuzz_min as fm
    lines = fm.join_lines(src)
    lo, hi = fm.region(lines)
    for k in range(lo, hi):
        if not fm.is_dir(lines[k]):
            continue
        name, clauses = fm.split_directive(lines[k].strip())
        if not name.startswith("target") or name.startswith(
                ("target data", "target update", "target enter",
                 "target exit")):
            continue
        e = fm.block_end(lines, k, hi)
        yield clauses, "\n".join(lines[k + 1:e + 1])


def test_structures_are_mapped_whole_or_by_every_referenced_component():
    """5.2 §13.8: a structure element in a map clause needs every other
    referenced element of that structure in a map clause; a whole
    structure is never mapped from or alloc (it would clobber the
    components the kernel does not write); no data-sharing or depend
    clause names a component."""
    seen = set()
    for seed in range(1, 121):
        src = fuzz.generate(seed, "fuzz-3", ("derived",)).source
        for clauses, body in _target_regions(src):
            items = []
            for c in clauses:
                m = re.match(r"map\(([^:()]*):", c)
                if m:
                    from offload.engine.fuzz_min import _items
                    full = re.findall(r"[\w%]+", c[m.end():])
                    items += [(m.group(1).split(",")[-1].strip(), x)
                              for x in full if x in _items(c) or "%" in x]
                elif re.match(r"(shared|private|firstprivate|depend)\(", c):
                    assert "%" not in c, (seed, c)
            for v in ("dr", "ds"):
                whole = [t for t, x in items if x == v]
                comps = {re.sub(r"\(.*", "", x) for t, x in items
                         if x.startswith(v + "%")}
                assert all(t in ("to", "tofrom") for t in whole), (seed, v)
                assert not (whole and comps), (seed, v)
                if comps:
                    seen.add("components")
                    used = set(re.findall(rf"\b{v}%[\w%]+", body))
                    assert used <= comps, (seed, used - comps)
    assert "components" in seen


@pytest.mark.gfortran
@pytest.mark.skipif(not GFORTRAN_2, reason="gfortran is not installed")
def test_derived_sample_passes_every_check():
    assert _sample_ok(("derived",), range(1, 61)) == {}
    assert _sample_ok(("types", "derived"), range(1, 31)) == {}


# --- stage 3: allocatable, pointer, target, sections, procedures ------------------

def test_alloc_feature_mix():
    feats = set()
    for seed in range(1, 121):
        feats |= fuzz.generate(seed, "fuzz-3", ("alloc",)).features
    for f in ("base:al:allocatable_scalar", "base:al:allocatable_component",
              "base:al:pointer_component", "base:al:pointer_output:target",
              "base:al:pointer_output:alloc", "base:al:target_attribute",
              "base:al:strided_update", "base:al:depend_section",
              "base:al:kernel_in_internal_procedure",
              "base:al:dummy:assumed_shape", "base:al:dummy:explicit",
              "base:al:dummy:allocatable", "base:al:dummy:pointer",
              "base:al:dummy:value", "base:al:dummy:optional",
              "base:al:dummy:intent_in", "base:al:dummy:intent_out",
              "base:al:optional_absent_in_map", "base:al:structure_dummy"):
        assert f in feats, f


def test_procedure_and_pointer_rules():
    """No procedure in a nowait program; an intent(in) array dummy is only
    mapped `to` by its kernel; a pointer output is always in a map clause
    of every target construct that references it; a target construct that
    references dr%pc maps dr by components."""
    for seed in range(1, 121):
        p = fuzz.generate(seed, "fuzz-3", ("alloc",))
        src = p.source
        if "tasking:nowait_depend" in p.features:
            assert "subroutine kp" not in src
        ptrs = set(re.findall(r"integer, pointer :: (o\d+)\(", src))
        for clauses, body in _target_regions(src):
            maps = " ".join(c for c in clauses if c.startswith("map("))
            for o in ptrs:
                if re.search(rf"\b{o}\(", body):
                    assert re.search(rf"\b{o}\b", maps), (seed, o)
            if "dr%pc" in body:
                assert "dr%pc" in maps and not re.search(r"[:,] dr[,)]",
                                                         maps), seed
                # the data region maps dr, not the target of dr%pc
                assert not re.search(r"map\(present[^)]*dr%pc", maps), seed
        for m in re.finditer(r"subroutine (kp\d+)\((.*)\)\n((?:.*\n)*?)"
                             r"  end subroutine", src):
            text = m.group(3)
            for d in re.findall(r"^(?!.*(?:pointer|optional)).*"
                                r"intent\(in\) :: (?!p\d\b)(\w+)\b", text,
                                re.M):
                from offload.engine.fuzz import map_items
                assert d in map_items(text, ("to",)) and d not in map_items(
                    text, ("tofrom", "from", "alloc")), (seed, d)


@pytest.mark.gfortran
@pytest.mark.skipif(not GFORTRAN_2, reason="gfortran is not installed")
def test_alloc_sample_passes_every_check():
    assert _sample_ok(("alloc",), range(1, 61)) == {}
    assert _sample_ok(("types", "derived", "alloc"), range(1, 31)) == {}


# --- stage 4: declare target, mapper, user reduction, modules -----------------

def test_declare_feature_mix():
    feats = set()
    for seed in range(1, 121):
        feats |= fuzz.generate(seed, "fuzz-3", ("declare",)).features
    for f in ("base:dc:declare_target_array", "base:dc:static_init",
              "base:dc:declare_target_output",
              "base:dc:declare_target_structure",
              "base:dc:declare_mapper:default", "base:dc:declare_mapper:named",
              "base:dc:map_with_named_mapper", "base:dc:declare_reduction",
              "base:dc:call_across_modules",
              "base:dc:device_function_reads_module_var",
              "base:dc:call:gd1", "base:dc:call:gd2",
              "base:dc:declare_target_enter", "base:dc:declare_target_to"):
        assert f in feats, f


def test_declare_target_variables_are_never_mapped():
    """Declare target (enter) variables keep their device copies by target
    update only; the mapper of mt_t maps every component."""
    for seed in range(1, 121):
        src = fuzz.generate(seed, "fuzz-3", ("declare",)).source
        m = re.search(r"declare target (?:enter|to)\((.*)\)", src)
        dtv = set(x.strip() for x in m.group(1).split(",")) if m else set()
        for ln in src.splitlines():
            if "!$omp" in ln and "map(" in ln and "declare mapper" not in ln:
                for v in dtv:
                    assert not re.search(rf"map\([^)]*\b{v}\b", ln), \
                        (seed, v, ln)
        mm = re.search(r"declare mapper\(.*mt_t :: v\) map\(tofrom: (.*)\)",
                       src)
        if mm:
            comps = re.findall(r"integer :: (\w+)\(nm\)",
                               src.split("type :: mt_t")[1].split(
                                   "end type")[0])
            assert sorted(mm.group(1).replace("v%", "").split(", ")) == \
                sorted(comps)
        outs = {v for v in dtv if v.startswith("go")}
        if outs:
            m = re.search(r"!\$omp target update from\((.*)\)\n", src)
            assert m and set(m.group(1).split(", ")) == outs, seed


@pytest.mark.gfortran
@pytest.mark.skipif(not GFORTRAN_2, reason="gfortran is not installed")
def test_declare_sample_passes_every_check():
    assert _sample_ok(("declare",), range(1, 61)) == {}
    assert _sample_ok(("types", "derived", "alloc", "declare"),
                      range(1, 31)) == {}


# --- stage 5: translation units --------------------------------------------------------

def test_multitu_bundles():
    feats = set()
    for seed in range(1, 61):
        p = fuzz.generate(seed, "fuzz-3", ("multitu",))
        feats |= p.features
        files = fb.split_bundle(p.source)
        names = [n for n, _ in files]
        assert names[-1] == "fuzz_prog.f90" and len(names) >= 2
        assert len(set(names)) == len(names)
        # every module is defined before a file that uses it
        for k, (n, text) in enumerate(files):
            for mod in re.findall(r"^\s*use (fuzz_\w+)", text, re.M):
                assert f"{mod}.f90" in names[:k], (seed, n, mod)
            m = re.search(r"^submodule \((\w+)\)", text, re.M)
            if m:
                assert f"{m.group(1)}.f90" in names[:k]
        assert "".join(t for _, t in files).splitlines().count(
            "program fuzz_prog") == 1
    for f in ("base:mt:file_set", "base:mt:module_chain",
              "base:mt:submodule", "base:mt:external_function"):
        assert f in feats, f
    assert fb.split_bundle("program p\nend program p\n") is None


def test_file_set_compile_script():
    from offload.engine import harness
    from offload.engine.toolchains import Toolchain
    tc = Toolchain("afar", "", "fc")
    s = harness.compile_set_script(tc, ["a.f90", "fuzz_prog.f90"], "x.out",
                                   "-O2", "/tmp/d")
    assert "fc -fopenmp --offload-arch=gfx942" in s
    assert "-O2 -c a.f90 -o a.o && \\\n" in s
    assert s.rstrip().endswith("-O2 a.o fuzz_prog.o -o x.out")


def test_minimizer_shrinks_across_files():
    """A fake failure that needs only the call of gs1 in a kernel: the
    other files and functions go, the submodule stays."""
    src = next(p.source for p in (fuzz.generate(s, "fuzz-3", ("multitu",))
                                  for s in range(1, 40))
               if "base:dc:call:gs1" in p.features
               and "base:mt:module_chain" in p.features)
    from offload.engine import fuzz_min as fm

    class Oracle:
        calls = 0

        def __call__(self, text):
            lo = text.index("! fuzz: kernels")
            ok = "gs1(" in text[lo:text.index("! fuzz: checksum")] and \
                fuzz.check_gfortran(text) is None
            return ok, "fake"
    res = fm.minimize(src, Oracle(), workers=4)
    out = res.source
    assert "fuzz_ssub.f90" in out and "fuzz_smod.f90" in out
    assert "gb1" not in out and "fuzz_bmod" not in out
    assert "ga1" not in out and "fuzz_amod" not in out
    assert fuzz.check_gfortran(out) is None


@pytest.mark.gfortran
@pytest.mark.skipif(not GFORTRAN_2, reason="gfortran is not installed")
def test_multitu_sample_passes_every_check():
    assert _sample_ok(("multitu",), range(1, 61)) == {}
    assert _sample_ok(fb.BASE_GROUPS, range(1, 31)) == {}


# --- triage of the base-language campaigns ------------------------------------------

def _fake_base_run(tmp_path, name, group, afar=lambda seed: "agree"):
    from offload.engine import fuzz_report as fr
    d = tmp_path / name
    d.mkdir()
    rows = []
    for seed in range(1, 31):
        feats = ["kernel:loop", f"base:group:{group}", "base:type:real8"] + (
            ["base:out:real8"] if seed % 2 else [])
        res = {"afar": fe.TcResult("afar", afar(seed), "checksum=1"),
               "cce20": fe.TcResult("cce20", "wrong_code" if seed % 2
                                    else "agree", "checksum=3")}
        rows.append(fe.ProgramResult(seed, "fuzz-3", "ok", expected=1,
                                     features=feats, results=res, lines=40,
                                     seconds=5, base=[group]).to_json())
    (d / "programs.jsonl").write_text("\n".join(rows) + "\n")
    (d / "meta.json").write_text(json.dumps({"sessions": [
        {"seconds": 60, "workers": 4, "gen_version": "fuzz-3",
         "base": [group]}]}))
    fr.write_report(d, tmp_path / f"fuzz-{name}.md")
    return d


def test_base_feature_rates_and_review(tmp_path):
    from offload.engine import fuzz_report as fr
    d = _fake_base_run(tmp_path, "b1", "types")
    s = json.loads((d / "summary.json").read_text())
    assert s["base"] == ["types"]
    r = s["base_features"]["base:out:real8"]
    assert r["programs"] == 15 and r["classes"]["cce20"] == {"wrong_code": 15}
    assert "## Base-language features" in (tmp_path / "fuzz-b1.md").read_text()
    md = tmp_path / "review.md"
    fr.write_base_review([d], md)
    text = md.read_text()
    assert "| `b1` | 1: element types and kinds | 30 |" in text
    assert "## Exclusions" in text and "### multitu" in text
    assert "| out:real8 | 15 |" in text


def test_base_review_copy_mode_and_thp_split(tmp_path):
    """A sibling x0-<group> run (same seeds at HSA_XNACK=0) adds a copy-mode
    section with the per-toolchain class changes; thp_split.json next to
    the runs adds the THP/memory-mode verdicts of the listed seeds."""
    from offload.engine import fuzz_report as fr
    d = _fake_base_run(tmp_path, "b1", "types",
                       afar=lambda s: "run_error" if s <= 3 else "agree")
    _fake_base_run(tmp_path, "x0-types", "types")
    (tmp_path / "thp_split.json").write_text(json.dumps({"seeds": [
        {"group": "types", "seed": 4, "verdict": "xnack1",
         "signature": "memory access fault: X"},
        {"group": "types", "seed": 1, "verdict": "thp"},
        {"group": "types", "seed": 2, "verdict": "load_or_flake"},
        {"group": "types", "seed": 3, "verdict": "load_or_flake"}]}))
    md = tmp_path / "review.md"
    fr.write_base_review([d], md)
    text = md.read_text()
    assert "## Copy mode (HSA_XNACK=0)" in text
    assert "| `b1` | `x0-types` | 30 |" in text
    assert "afar: run_error -> agree 3" in text
    assert "| thp | 1 |" in text and "| load_or_flake | 2 |" in text
    assert "| `memory access fault: X` | 1 | types 4 |" in text


def test_base_review_without_copy_mode_runs(tmp_path):
    from offload.engine import fuzz_report as fr
    d = _fake_base_run(tmp_path, "b1", "types")
    md = tmp_path / "review.md"
    fr.write_base_review([d], md)
    assert "## Copy mode" not in md.read_text()


def test_reclassify_compile_uses_the_current_tables(tmp_path):
    msg = where.message("afar_link_device_runtime").read_text().split(
        "==== verbatim output below ====\n", 1)[1]
    res = {"afar": fe.TcResult("afar", "harness_error",
                               "unclassified_compile_failure: rc=1",
                               output=msg)}
    pr = fe.ProgramResult(3, "fuzz-3", "ok", expected=1, results=res)
    (tmp_path / "programs.jsonl").write_text(pr.to_json() + "\n")
    changed = fe.reclassify_compile(tmp_path)
    assert changed and changed[0][2] == "compile_reject"
    back = fe.load(tmp_path)[0][0].results["afar"]
    assert back.cls == "compile_reject"
    assert back.reason.startswith("link_undefined_symbol: ")
    assert "reclassified from: unclassified" in back.note


def test_minimizer_shrinks_kernel_procedures():
    """The kernel of an internal procedure is minimized like the kernels
    region (stage 3)."""
    from offload.engine import fuzz_min as fm
    src = next(p.source for p in (fuzz.generate(s, "fuzz-3", ("alloc",))
                                  for s in range(1, 60))
               if "base:al:kernel_in_internal_procedure" in p.features
               and "tasking:nowait_depend" not in p.features)
    assert fm.procedure_regions(fm.join_lines(src))

    class Oracle:
        calls = 0

        def __call__(self, text):
            body = text.split("subroutine kp1(", 1)[-1]
            ok = "!$omp target" in body and \
                fuzz.check_gfortran(text) is None
            return ok, "fake"
    res = fm.minimize(src, Oracle(), workers=4)
    out = res.source
    before = src.split("subroutine kp1(", 1)[1].split("end subroutine")[0]
    after = out.split("subroutine kp1(", 1)[1].split("end subroutine")[0]
    assert len(after.splitlines()) < len(before.splitlines())
    assert fuzz.check_gfortran(out) is None


def test_minimizer_keeps_pointer_component_maps():
    from offload.engine import fuzz_min as fm
    src = next(p.source for p in (fuzz.generate(s, "fuzz-3", ("alloc",))
                                  for s in range(1, 80))
               if re.search(r"map\([^)]*dr%pc", p.source))
    L = fm.join_lines(src)
    assert fm._pointer_components(L) == {"pc"}
    for c in fm.candidates(L):
        if c.what.startswith(("delete clause", "drop")):
            assert "dr%pc" not in c.what, c.what


# ---- Flang (AFAR amdflang) parse-tree oracle. Slow-ish: each case runs flang -----------------------------


from offload.engine import flang_oracle
from offload.engine.flang_oracle import (Agreement, FlangError, compare,
                                     flang_clauses, verdict_of,
                                     wrap_directive)

PROGRAM = """\
program p
  integer :: a(10,10), i, j
  !$omp target teams distribute parallel do collapse(2) map(tofrom: a)
  do i = 1, 10
    do j = 1, 10
      a(i,j) = i
    end do
  end do
end program
"""

def _assert_agree(res):
    assert res.verdict == "agree", res
    assert res.flang_stage == "ok" and res.flang_error is None


COMBINED = ("!$omp target teams distribute parallel do collapse(2) "
            "map(tofrom: a)")


def test_flang_lists_map_and_collapse():
    assert ["collapse", "map"] in flang_clauses(PROGRAM)


def test_flang_clauses_rejects_unparsable_source():
    with pytest.raises(FlangError):
        flang_clauses("program p\n  !$omp target bogus(\nend program\n")


def test_compare_agree():
    res = compare(COMBINED, 52)
    assert res == Agreement(True, True, True, flang_stage="ok")
    assert res.verdict == "agree"


# One representative per wrapper kind, with several clauses each so the
# node-name -> spelling table is exercised.
AGREE = [
    "!$omp target data map(to: a) use_device_addr(a) if(n > 0) device(dev)",
    "!$omp target enter data map(to: a) depend(in: b) nowait",
    "!$omp target exit data map(from: a) device(dev)",
    "!$omp target update to(a) if(n > 0)",
    "!$omp target map(tofrom: a) has_device_addr(b) defaultmap(tofrom: scalar)"
    " thread_limit(8) nowait",
    "!$omp teams num_teams(4) thread_limit(8) default(shared) "
    "firstprivate(n) shared(a)",
    "!$omp target teams loop collapse(2) bind(teams) order(concurrent) "
    "private(k) reduction(+: s)",
    "!$omp distribute dist_schedule(static, 4) collapse(2) lastprivate(k)",
    "!$omp parallel do schedule(static, 2) num_threads(4) proc_bind(close) "
    "ordered",
    "!$omp loop bind(thread) private(k)",
    "!$omp declare target link(b) device_type(nohost)",
    "!$omp requires unified_shared_memory reverse_offload",
    "!$omp requires atomic_default_mem_order(seq_cst) dynamic_allocators",
]


@pytest.mark.parametrize("text", AGREE)
def test_compare_agree_across_wrappers(text):
    _assert_agree(compare(text, 52))


@pytest.mark.parametrize("text", [
    "!$omp target data map(to: a)",
    "!$omp target enter data map(to: a)",
    "!$omp target update from(a)",
    "!$omp declare target enter(a)",
])
def test_compare_agree_at_6_0_spellings(text):
    _assert_agree(compare(text, 60))


def test_workdistribute_needs_version_60():
    text = "!$omp target teams workdistribute"
    _assert_agree(compare(text, 60))
    # amdflang's opinion at 5.2 differs from the 6.0 spec text
    old = compare(text, 52)
    assert old.verdict == "grammar_only" or old.verdict == "not_consulted" \
        or old.grammar_ok is False
    assert old.flang_stage == "semantics"
    assert "workdistribute" in old.flang_error.lower()


def test_flang_rejection_is_reported_not_hidden():
    res = compare("!$omp target teams distribute parallel do num_teams(2) "
                  "num_teams(3)", 52)
    assert res.grammar_ok is False and res.flang_ok is False
    assert res.flang_stage == "semantics" and res.flang_error
    assert res.verdict == "both_reject"


def test_no_wrapper_is_reported_not_guessed():
    res = compare("!$omp end target data", 52)
    assert res.consulted is False and res.flang_stage == "skipped"
    assert res.same_clauses is None
    assert res.verdict == "not_consulted"
    assert "wrapper" in res.note
    assert res.flang_error is None


def test_wrapper_text_is_free_form_and_has_end_directive():
    src = wrap_directive("!$omp target data map(to: a)", 52)
    assert src is not None
    assert "!$omp end target data" in src
    assert not src.startswith(("c", "C", "*"))


@pytest.mark.parametrize("version", [52, 60])
def test_bare_declare_target_is_accepted_via_subroutine_wrapper(version):
    text = "!$omp declare target"
    assert "subroutine" in wrap_directive(text, version)
    _assert_agree(compare(text, version))


def test_wrapper_artifact_style_rejection_is_reported_with_stage():
    # is_device_ptr on an array: the grammar accepts, flang's semantic check
    # rejects; this must surface as grammar_only, never as "agree"
    res = compare("!$omp target is_device_ptr(b)", 52)
    assert res.verdict == "grammar_only"
    assert res.flang_ok is False and res.flang_stage == "semantics"
    assert res.flang_error and "t.f90" in res.flang_error
    assert res.same_clauses is True  # via the sema=False fallback


def test_sema_false_fallback_dumps_a_semantically_bad_program():
    bad = wrap_directive("!$omp target is_device_ptr(b)", 52)
    with pytest.raises(FlangError) as e:
        flang_clauses(bad, 52)
    assert e.value.stage == "semantics"
    assert flang_clauses(bad, 52, sema=False) == [["is_device_ptr"]]


@pytest.mark.parametrize("args, expected", [
    ((True, True, True, True), "agree"),
    ((True, True, True, False), "clauses_differ"),
    ((True, True, True, None), "clauses_differ"),
    ((True, True, False, True), "grammar_only"),
    ((True, True, False, None), "grammar_only"),
    ((False, True, True, True), "flang_only"),
    ((False, True, False, None), "both_reject"),
    ((True, False, False, None), "not_consulted"),
    ((False, False, False, None), "not_consulted"),
])
def test_verdict_table(args, expected):
    g, consulted, f, same = args
    assert verdict_of(g, consulted, f, same) == expected


def test_verdicts_on_real_directives():
    assert compare("!$omp end target", 52).verdict == "not_consulted"
    assert compare(COMBINED, 52).verdict == "agree"
    assert compare("!$omp target is_device_ptr(b)", 52).verdict == "grammar_only"
    assert compare("!$omp target teams distribute parallel do num_teams(2) "
                   "num_teams(3)", 52).verdict == "both_reject"


def test_unknown_clause_node_raises():
    with pytest.raises(FlangError) as e:
        flang_oracle._spelling("Frobnicate")
    assert e.value.stage == "map" and "Frobnicate" in e.value.message


def test_known_nodes_and_irregular_table_map(monkeypatch):
    assert flang_oracle._spelling("UseDeviceAddr") == "use_device_addr"
    assert flang_oracle._spelling("Collapse") == "collapse"
    monkeypatch.setitem(flang_oracle.CLAUSE_NODE_SPELLING, "OddNode", "map")
    assert flang_oracle._spelling("OddNode") == "map"


# Real disagreements found by the corpus check,
# where the grammar follows the spec and flang does not.
DISAGREE = [
    # gcc gfortran.dg/gomp/map-7.f90:32 (a compile test, no expected error):
    # without a ':' there are no modifiers, so these are four variables
    # (5.2 §5.8.3, 6.0 §7.9.6); amdflang's parser takes them for modifiers.
    ("!$omp target map(present, to, always, close)", 52, "parse"),
    ("!$omp target map(present, to, always, close)", 60, "parse"),
    # With neither an extended list nor an enter/link/local clause, a 6.0
    # declare_target is declaration-associated and legal in a subprogram
    # (6.0 §9.9.1, p.347-348); amdflang applies the 5.2 rule "at least one
    # enter or link clause" (5.2 §7.8.1, p.206, so at 5.2 flang is right).
    ("!$omp declare target device_type(host)", 60, "semantics"),
]


@pytest.mark.parametrize("text, version, stage", DISAGREE)
def test_compare_disagree_recorded(text, version, stage):
    res = compare(text, version)
    assert res.grammar_ok and not res.flang_ok
    assert res.verdict == "grammar_only" and res.flang_stage == stage


def test_declaration_associated_declare_target_wrapped_in_a_subroutine():
    # 5.2 §7.8.1 and 6.0 §9.9.1 (Fortran): without a list, or with
    # device_type, the directive belongs in a subprogram's specification part
    for text in ("!$omp declare target device_type(host)",
                 "!$omp declare target indirect"):
        assert wrap_directive(text, 60).startswith("subroutine")
    for text in ("!$omp declare target link(b) device_type(nohost)",
                 "!$omp declare target (a)", "!$omp declare target enter(a)"):
        assert wrap_directive(text, 52).startswith("program")


def test_compare_unscannable_directive_is_a_parse_rejection():
    # flang's prescanner rejects an unbalanced parenthesis ("Could not scan")
    # before parsing; that is a parse-stage rejection, not a tool failure.
    # From the corpus: gcc gfortran.dg/gomp/declare-mapper-31.f90:25
    res = compare("!$omp target map(", 52)
    assert res.verdict == "both_reject" and res.flang_stage == "parse"
    assert "Could not scan" in res.flang_error


def test_dump_runs_through_the_guarded_harness(monkeypatch):
    """Flang runs through harness._execute (its own
    process group, killed at the timeout, and the watchdog that ends the
    group when the caller dies), not a bare Popen."""
    from offload.engine import harness
    seen = []

    def fake(script, cwd, timeout_s, merge=False):
        seen.append((script, timeout_s))
        return harness._Exec(0, "dump", "")
    monkeypatch.setattr(harness, "_execute", fake)
    assert flang_oracle._dump("program p\nend program p\n", 52, True) == \
        "dump"
    assert seen and "-fc1" in seen[0][0] and seen[0][1] == \
        flang_oracle._TIMEOUT
