"""The application corpus harness (offload.engine.apps)."""
import pytest

from offload.engine import apps as A


@pytest.mark.needs_bench("apps/manifest.yaml")
def test_manifest_loads_and_ids_are_unique():
    apps = A.load()
    assert "prk" in apps and "babelstream" in apps
    ids = [p.id for a in apps.values() for p in a.programs]
    assert len(ids) == len(set(ids))
    for a in apps.values():
        assert len(a.commit) == 40, a.id
        assert a.license
        for p in a.programs:
            assert p.lang in ("f90", "c") and p.model in ("omp", "acc")
            assert p.runs, p.id
            for r in p.runs:
                assert r.check or r.check_fn, p.id
                if r.check_fn:
                    assert r.check_fn in A.CHECKS


def test_manifest_sources_exist_in_the_clones():
    apps = A.load()
    for a in apps.values():
        if not a.path.exists():
            pytest.skip(f"{a.id} not cloned (tools/campaigns/app_bench.py fetch)")
        for p in a.programs:
            for name, path in A.source_paths(p, a):
                assert path.is_file(), (p.id, name)


def test_module_order_puts_modules_first():
    files = {"main.f90": "program p\n use m2\nend program\n",
             "b.f90": "module m2\n use m1\nend module m2\n",
             "a.f90": "module m1\nend module m1\n"}
    assert A.module_order(files) == ["a.f90", "b.f90", "main.f90"]
    assert A.module_deps(files)["b.f90"] == ["a.f90"]
    # an intrinsic or unknown module is no dependency; module procedure
    # is no module
    files = {"x.f90": "module x\n use iso_c_binding\ncontains\n"
                      " module procedure f\nend module\n"}
    assert A.module_deps(files) == {"x.f90": []}


def test_error_locations_of_each_compiler():
    flang = ("/a/b/k.F90:130:64: error: expected '=>'\n"
             "/a/b/k.F90:130:52: in the context: pointer assignment\n"
             "/a/b/other.F90:3:1: error: elsewhere\n")
    assert A.error_locations(flang, "k.F90") == [
        {"line": 130, "msg": "expected '=>'"}]
    cce = ("ftn-1519 ftn: ERROR MAIN, File = ../../x/k.F90, Line = 130, "
           "Column = 52 \n  Invalid clause \"GPU_SCHEDULE\" for directive\n")
    assert A.error_locations(cce, "k.F90") == [
        {"line": 130, "msg": "Invalid clause \"GPU_SCHEDULE\" for directive"}]
    nv = "NVFORTRAN-S-0155-Bad thing in clause (/x/k.F90: 12)\n"
    assert A.error_locations(nv, "k.F90") == [
        {"line": 12, "msg": "Bad thing in clause"}]
    mlir = ('loc("/x/mw.F90":428:11): error: not yet implemented: '
            'Unhandled clause depend\n')
    assert A.error_locations(mlir, "mw.F90") == [
        {"line": 428, "msg": "not yet implemented: Unhandled clause depend"}]
    edg = '"/x/k.c", line 7: error: identifier "q" is undefined\n'
    assert A.error_locations(edg, "k.c") == [
        {"line": 7, "msg": 'identifier "q" is undefined'}]


def test_compile_outcome_classes():
    assert A.compile_outcome("afar", "f90", 0, "") == ("ok", "")
    assert A.compile_outcome("afar", "f90", None, "")[0] == "timeout"
    oc, why = A.compile_outcome("afar", "f90", 1, "x.f90:1:1: error: bad\n")
    assert oc == "rejected"
    oc, _ = A.compile_outcome("afar", "f90", 139, "Segmentation fault\n")
    assert oc == "ice"


def test_judge_run():
    r = A.Run("run", check="Solution validate")
    assert A.judge_run(0, "x\nSolution validates\n", r)[0] == \
        "correct_on_device"
    assert A.judge_run(1, "Solution validates\n", r)[0] == "run_error"
    assert A.judge_run(0, "ERROR\n", r)[0] == "wrong_answer"
    assert A.judge_run(None, "", r)[0] == "timeout"
    assert A.judge_run(-11, "", r)[0] == "crash"
    assert A.judge_run(139, "", r)[0] == "crash"
    f = A.Run("run", check="Triad", fail="Validation failed")
    assert A.judge_run(0, "Triad\nValidation failed on A\n", f)[0] == \
        "wrong_answer"
    assert A.judge_run(0, "Triad 1.0\n", f)[0] == "correct_on_device"


def test_check_miniweather():
    good = " d_mass:   1.2E-15\n d_te:   -3.0E-06\n"
    assert A.check_miniweather(good)[0]
    assert not A.check_miniweather(" d_mass: NaN\n d_te: NaN\n")[0]
    assert not A.check_miniweather(" d_mass: 1e-15\n d_te: 3e-6\n")[0]
    assert not A.check_miniweather(" d_mass: 1e-10\n d_te: -3e-6\n")[0]
    assert not A.check_miniweather("nothing")[0]


def test_overall_is_the_first_failing_stage():
    ok = {"outcome": "ok"}
    assert A.overall({"files": [ok], "link": ok, "runs": [
        {"outcome": "correct_on_device"}]}) == ("run", "correct_on_device")
    assert A.overall({"files": [ok, {"outcome": "ice"}], "link": None,
                      "runs": []}) == ("compile", "ice")
    assert A.overall({"files": [ok], "link": {"outcome": "rejected"},
                      "runs": []}) == ("link", "rejected")
    assert A.overall({"files": [ok], "link": ok, "runs": [
        {"outcome": "wrong_answer"}, {"outcome": "crash"}]}) == \
        ("run", "crash")


def test_applicable():
    p = A.AppProgram("x", "a", "f90", "acc", ["x.f90"])
    assert A.applicable(p, "afar") == "AFAR has no OpenACC"
    assert A.applicable(p, "cce19") is None
    c = A.AppProgram("y", "a", "c", "acc", ["y.c"])
    assert A.applicable(c, "cce20") is not None
    assert A.applicable(c, "nvhpc") is None


# --- MFC test outcomes and reruns ---------------------------------------------

_MFC_LOG = """\
 Test pre_process and simulation | Only 0045D9F8, 8D6E051E, 32A3A936 (3 tests)
     ( 1/3)    1D -> Bubbles -> nb=1                                 3.00    0045D9F8
     Still running (>2min) 8D6E051E  1D -> Phase Change model 6 -> 3 Fluid(s)
     ✗ FAILED: 1D -> Phase Change model 6 -> 3 Fluid(s) -> mod...
       UUID: 8D6E051E
       Attempts: 1
       Error: Test tests/8D6E051E: 1D -> Phase Change model 6 exceeded 1 hour timeout. This may indicate a hung simulation or misconfigured case.
       Hint: Test may be hanging - check case configuration

     ✗ FAILED: 1D -> Hypoelasticity -> 1 Fluid(s) -> cont_damage
       UUID: 32A3A936
       Attempts: 1
       Error: Test tests/32A3A936: 1D -> Hypoelasticity: Variable n°28 (1-indexed) in D/cons.1.00.000050.dat is not within tolerance:

     ( 3/3)    1D -> Smoothing                                       3.05    4201674B
mfc test rc=1
"""

_MFC_RERUN = """\
 Test pre_process and simulation | Only 8D6E051E (1 test)
     (  1/  1)    1D -> Phase Change model 6 -> 3 Fluid(s) -> mod...  205.52    8D6E051E
mfc test rc=0
"""


def test_mfc_outcome_classes():
    assert A.mfc_outcome("Test tests/X: a: Failed to execute MFC (memory "
                         "access fault by GPU).") == "crash"
    assert A.mfc_outcome("Test tests/X: a exceeded 1 hour timeout. This may "
                         "indicate a hung simulation") == "timeout"
    assert A.mfc_outcome("Test tests/X: Variable n 1 in D/cons.1.dat is not "
                         "within tolerance") == "wrong_answer"


def _mfc_tree(tmp_path, rerun=None):
    d = tmp_path / "wingtip" / "mfc" / "nvhpc-mp"
    d.mkdir(parents=True)
    (d / "build.log").write_text("mfc build rc=0\n")
    (d / "test.copy.log").write_text(_MFC_LOG)
    if rerun is not None:
        (d / "test.copy.rerun.log").write_text(rerun)
    return d


@pytest.mark.needs_bench("apps/manifest.yaml")
def test_mfc_records_timeout_is_not_a_wrong_answer(tmp_path, monkeypatch):
    _mfc_tree(tmp_path)
    monkeypatch.setattr(A, "OUT", tmp_path)
    (rec,) = A.mfc_records()
    runs = {r["name"]: r for r in rec["runs"]}
    assert runs["8D6E051E"]["outcome"] == "timeout"
    assert runs["32A3A936"]["outcome"] == "wrong_answer"
    assert runs["0045D9F8"]["outcome"] == "correct_on_device"
    assert rec["toolchain"] == "nvhpc" and rec["host"] == "wingtip"


@pytest.mark.needs_bench("apps/manifest.yaml")
def test_mfc_records_a_rerun_alone_replaces_the_first_run(tmp_path,
                                                          monkeypatch):
    _mfc_tree(tmp_path, rerun=_MFC_RERUN)
    monkeypatch.setattr(A, "OUT", tmp_path)
    (rec,) = A.mfc_records()
    runs = {r["name"]: r for r in rec["runs"]}
    r = runs["8D6E051E"]
    assert r["outcome"] == "correct_on_device"
    assert "rerun alone" in r["reason"] and "timeout" in r["reason"]
    # tests the rerun did not run keep their first outcome
    assert runs["32A3A936"]["outcome"] == "wrong_answer"


@pytest.mark.needs_bench("apps/manifest.yaml")
def test_mfc_records_an_unfinished_rerun_is_ignored(tmp_path, monkeypatch):
    _mfc_tree(tmp_path, rerun=_MFC_RERUN.replace("mfc test rc=0\n", ""))
    monkeypatch.setattr(A, "OUT", tmp_path)
    (rec,) = A.mfc_records()
    runs = {r["name"]: r for r in rec["runs"]}
    assert runs["8D6E051E"]["outcome"] == "timeout"


@pytest.mark.needs_bench("apps/manifest.yaml")
def test_mfc_records_a_rerun_does_not_replace_a_first_run_wrong_answer(
        tmp_path, monkeypatch):
    # Only a first-run timeout (the host's load) is
    # replaced; a wrong answer that passes alone stays a wrong answer (a
    # nondeterministic failure is still a failure), the rerun in its reason
    rerun = _MFC_RERUN.replace("8D6E051E", "32A3A936")
    _mfc_tree(tmp_path, rerun=rerun)
    monkeypatch.setattr(A, "OUT", tmp_path)
    (rec,) = A.mfc_records()
    runs = {r["name"]: r for r in rec["runs"]}
    r = runs["32A3A936"]
    assert r["outcome"] == "wrong_answer"
    assert "rerun alone: passed" in r["reason"]
    assert "not within tolerance" in r["reason"]


@pytest.mark.needs_bench("apps/manifest.yaml")
def test_mfc_records_skip_workaround_working_copies(tmp_path, monkeypatch):
    # <tc>-<gpu>-<variant> working copies (tools/jobs/run_mfc.sh
    # MFC_VARIANT) are not corpus records, by an explicit rule
    d = _mfc_tree(tmp_path)
    v = d.parent / "nvhpc-mp-nolines"
    v.mkdir()
    (v / "build.log").write_text("mfc build rc=0\n")
    (v / "test.copy.log").write_text(_MFC_LOG)
    monkeypatch.setattr(A, "OUT", tmp_path)
    recs = A.mfc_records()
    assert len(recs) == 1 and recs[0]["toolchain"] == "nvhpc"
    assert A.mfc_dir_key("nvhpc-mp-nolines") is None
    assert A.mfc_dir_key("cce20-mp-o0cbc") is None
    assert A.mfc_dir_key("nvhpc269-acc") == ("nvhpc269", "acc")
