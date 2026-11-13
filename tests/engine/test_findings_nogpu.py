"""Tests of row provenance, the baseline run and the harness with fake compilers and programs."""


# ---- Provenance on every row (offload.engine.provenance) -------------------------------------------------

import where
import dataclasses
from pathlib import Path

from offload.engine import harness
from offload.engine import provenance as PV
from offload.engine.gen import Program
from offload.engine.toolchains import Toolchain

FAKES = Path(__file__).parent.parent / "data" / "fakes"
MESSAGES = Path(__file__).parent.parent / "data" / "messages"


def fake_tc(name="afar", msg=None, rc=0, exe="exe_device_pass.sh"):
    m = str(where.message(msg)) if msg else "-"
    e = "-" if exe is None else str(FAKES / exe)
    cmd = f"{FAKES}/fake_fc.sh {m} {rc} {e}"
    return Toolchain(name, "", cmd, cc=cmd)


def prog(**kw) -> Program:
    base = dict(id="fake-prog", lang="fortran", source="! fake\n",
                atoms=frozenset({"omp.directive.target"}),
                primary_atom="omp.directive.target", legal=True,
                violates=None, observable=True)
    base.update(kw)
    return Program(**base)


CASES = [  # every path of run_program that returns a row
    ("pass", fake_tc()),
    ("fail", fake_tc(exe="exe_device_fail.sh")),
    ("reject", fake_tc("afar", "afar_syntax_error", 1, None)),
    ("ice", fake_tc("cce19", "cce_ice_ordered", 1, None)),
    ("environment", fake_tc("afar", "afar_link_quadmath", 1, None)),
    ("ignored", fake_tc("afar", "afar_ignored_reverse_offload", 0)),
    ("no_result", fake_tc(exe="exe_no_result.sh")),
    ("no_executable", fake_tc(exe=None)),
]


def test_every_harness_row_has_provenance():
    seen = set()
    for name, tc in CASES:
        r = harness.run_program(prog(), tc, 1, timeout_s=20, repeats=1)
        d = dataclasses.asdict(r)
        assert PV.missing(d) == [], (name, PV.missing(d))
        seen.add(r.outcome)
        failing = r.outcome not in ("correct_on_device", "unobservable",
                                    "harness_error")
        assert d["gate"] == ("pending" if failing else "n/a"), name
        assert d["node"] and d["env_hash"] and d["toolchain_build"]
        assert d["build_dir"].startswith("/") and \
            Path(d["build_dir"]).name.startswith("harness_")
    assert len(seen) >= 5
    # a toolchain for another arch is never built: still complete
    other = Toolchain("afar_g90", "", "true", arch="gfx90a")
    from offload.engine.toolchains import detect_gpu
    if detect_gpu()[0] == "gfx942":
        r = harness.run_program(prog(), other, 0, timeout_s=5, repeats=1)
        assert r.outcome == "harness_error"
        assert PV.missing(dataclasses.asdict(r)) == []


def test_env_hash_is_order_independent_and_sensitive():
    assert PV.env_hash({"A": "1", "B": "2"}) == PV.env_hash({"B": "2",
                                                            "A": "1"})
    assert PV.env_hash({"HSA_XNACK": "1"}) != PV.env_hash({"HSA_XNACK": "0"})


def test_modules_of_a_prelude():
    assert PV.modules_of("module load cce/19.0.0 craype-accel-amd-gfx942"
                         " rocm\nexport X=1") == (
        "cce/19.0.0", "craype-accel-amd-gfx942", "rocm")


def test_rows_of_older_tasks_read_back(tmp_path):
    """A row written before provenance existed has no provenance fields; it reads
    back with empty ones (and the reader keeps the new ones)."""
    import json
    r = harness.run_program(prog(), fake_tc(), 1, timeout_s=20, repeats=1)
    p = tmp_path / "rows.jsonl"
    harness.write_jsonl([r], p)
    back = harness.read_jsonl(p)[0]
    assert back == r
    d = json.loads(p.read_text())
    for f in PV.FIELDS:
        if f != "flags":
            d.pop(f)
    p.write_text(json.dumps(d) + "\n")
    old = harness.read_jsonl(p)[0]
    assert old.gate == "" and old.build_dir == ""


def test_stress_and_fuzz_rows_have_provenance():
    from offload.engine import fuzz_exec, stress_exec
    row = stress_exec.Row("x", "afar", 1, "O2", "agree")
    for f in PV.FIELDS:
        assert f in row.as_dict(), f
    tr = fuzz_exec.TcResult("afar", "agree", "")
    for f in PV.FIELDS:
        assert f in dataclasses.asdict(tr), f


# ---- Tests of offload.engine.baseline (existing-corpus run, exit code only) ---------------------------

import csv

from offload.engine.baseline import read_baseline, run_baseline, select_files

FIELDS = ["repo", "path", "lang", "model", "kind", "spec_dir",
          "n_directives", "directives"]


def fake_tc_2(rc: int = 0, exe: str | None = "exe_device_pass.sh") -> Toolchain:
    e = str(FAKES / exe) if exe else "-"
    return Toolchain("afar", "", f"{FAKES}/fake_fc.sh - {rc} {e}")


def corpus(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "corpus"
    rows = [
        # selected: free-form Fortran run test with a target directive
        dict(repo="omp_vv", path="tests/5.0/a/test_a.F90",
             directives="target teams;parallel do"),
        dict(repo="omp_vv", path="tests/4.5/b/test_b.F90",
             directives="target"),
        # not selected: not a test, no target directive, fixed form, C,
        # other repo
        dict(repo="omp_vv", path="template/ompvv_template.F90",
             directives="target"),
        dict(repo="omp_vv", path="tests/4.5/c/test_c.F90",
             directives="parallel do"),
        dict(repo="omp_vv", path="tests/4.5/d/test_d.F",
             directives="target"),
        dict(repo="omp_vv", path="tests/4.5/e/test_e.c", lang="c",
             directives="target"),
        dict(repo="aomp", path="x/test_x.f90", directives="target"),
    ]
    for r in rows:
        f = root / r["repo"] / r["path"]
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("! fake test\n")
    inc = root / "omp_vv" / "ompvv"
    inc.mkdir(parents=True)
    (inc / "ompvv.F90").write_text("! fake header\n")
    index = tmp_path / "index.csv"
    with index.open("w", newline="") as fh:
        w = csv.DictWriter(fh, FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({"lang": "fortran", "model": "omp", "kind": "run",
                        "spec_dir": "", "n_directives": "1", **r})
    return index, root


def test_selection(tmp_path):
    index, root = corpus(tmp_path)
    assert [r["path"] for r in select_files(index, ["omp_vv"])] == [
        "tests/4.5/b/test_b.F90", "tests/5.0/a/test_a.F90"]


def test_baseline_exit_code_only(tmp_path):
    index, root = corpus(tmp_path)
    ok = tmp_path / "ok.jsonl"
    n = run_baseline(index, ["omp_vv"], fake_tc_2(), 0, ok, corpus_root=root,
                     timeout_s=20)
    assert n == 2
    rows = read_baseline(ok)
    assert {r["status"] for r in rows} == {"pass"}
    assert all(r["run_rc"] == 0 and r["compile_rc"] == 0 for r in rows)
    assert all(r["xnack"] == 0 and r["toolchain"] == "afar" for r in rows)

    # a program that exits non-zero fails, even though it prints a
    # passing RESULT-like line (exit code is the only criterion)
    bad = tmp_path / "bad.jsonl"
    run_baseline(index, ["omp_vv"], fake_tc_2(exe="exe_abort.sh"), 1, bad,
                 corpus_root=root, timeout_s=20)
    rows = read_baseline(bad)
    assert {r["status"] for r in rows} == {"fail"}
    assert all(r["stage"] == "run" for r in rows)

    # a compile failure fails at the compile stage, without a run
    cfail = tmp_path / "cfail.jsonl"
    run_baseline(index, ["omp_vv"], fake_tc_2(rc=1, exe=None), 0, cfail,
                 corpus_root=root, timeout_s=20)
    rows = read_baseline(cfail)
    assert {(r["status"], r["stage"], r["run_rc"]) for r in rows} == {
        ("fail", "compile", None)}


def test_include_dir_copied_next_to_source(tmp_path):
    # the fake program lists its working directory: ompvv/ must be there
    index, root = corpus(tmp_path)
    exe = tmp_path / "exe_ls.sh"
    exe.write_text("#!/bin/bash\nls ompvv\n")
    exe.chmod(0o755)
    tc = Toolchain("afar", "", f"{FAKES}/fake_fc.sh - 0 {exe}")
    out = tmp_path / "ls.jsonl"
    run_baseline(index, ["omp_vv"], tc, 0, out, corpus_root=root,
                 timeout_s=20)
    rows = read_baseline(out)
    assert all("ompvv.F90" in r["stdout"] for r in rows)
    assert all("-I./ompvv" in r["flags"] for r in rows)


def test_copy_semantics_paths_and_rerun_baseline(tmp_path):
    from offload.engine.baseline import copy_semantics_paths, rerun_baseline
    index, root = corpus(tmp_path)
    (root / "omp_vv" / "tests/4.5/b/test_b.F90").write_text(
        "program t\n  integer :: a(4)\n  a = 1\n"
        "  !$omp target map(to: a)\n    a = 0\n  !$omp end target\n"
        "  if (any(a /= 1)) stop 1\nend program t\n")
    paths = copy_semantics_paths(index, ["omp_vv"], corpus_root=root)
    assert paths == {"tests/4.5/b/test_b.F90"}
    out = tmp_path / "b.jsonl"
    run_baseline(index, ["omp_vv"], fake_tc_2(exe="exe_abort.sh"), 1, out,
                 corpus_root=root, timeout_s=20)
    n = rerun_baseline(index, ["omp_vv"], paths, [fake_tc_2()], 1, out,
                       corpus_root=root, timeout_s=20)
    rows = read_baseline(out)
    assert n == 1 and len(rows) == 2
    assert {r["path"]: r["status"] for r in rows} == {
        "tests/4.5/b/test_b.F90": "pass", "tests/5.0/a/test_a.F90": "fail"}
    only = tmp_path / "only.jsonl"
    assert run_baseline(index, ["omp_vv"], fake_tc_2(), 0, only,
                        corpus_root=root, timeout_s=20, only=paths) == 1


def test_baseline_rows_record_machine_arch_gpu(tmp_path, monkeypatch):
    """A gfx90a twin's rows say where they ran; on a node of the
    other arch every file is a harness error, never a fail."""
    import dataclasses
    from offload.engine import harness
    index, root = corpus(tmp_path)
    g90 = dataclasses.replace(fake_tc_2(), name="afar_g90", arch="gfx90a",
                              machine="tioga", xnack_modes=(0,))
    monkeypatch.setattr(harness, "detect_gpu",
                        lambda: ("gfx90a", "AMD Instinct MI250X"))
    out = tmp_path / "g.jsonl"
    run_baseline(index, ["omp_vv"], g90, 0, out, corpus_root=root,
                 timeout_s=20)
    rows = read_baseline(out)
    assert {(r["status"], r["machine"], r["arch"], r["gpu"], r["device"])
            for r in rows} == {("pass", "tioga", "gfx90a",
                                "gfx90a AMD Instinct MI250X",
                                "gfx90a (AMD Instinct MI250X)")}
    monkeypatch.setattr(harness, "detect_gpu",
                        lambda: ("gfx942", "AMD Instinct MI300A"))
    run_baseline(index, ["omp_vv"], g90, 0, out, corpus_root=root,
                 timeout_s=20)
    rows = read_baseline(out)
    assert {r["status"] for r in rows} == {"harness_error"}
    assert all("wrong_arch" in r["reason"] for r in rows)


def _exe(tmp_path: Path, name: str, body: str) -> Path:
    exe = tmp_path / name
    exe.write_text("#!/bin/bash\n" + body)
    exe.chmod(0o755)
    return exe


def test_suite_result_line_overrides_a_wrapped_exit_status(tmp_path):
    """The current OpenMP_VV C header returns the error count
    itself (`return err;`), so a count that is a multiple of 256 exits 0;
    a run that exits 0 but reports "Test failed" is a fail, and a test
    that reports "Test skipped" (OMPVV_CHECK_TO_SKIP, exit status -667 &
    255) says nothing about the compiler: a harness_error, never a fail."""
    index, root = corpus(tmp_path)
    wrapped = _exe(tmp_path, "exe_wrapped.sh",
                   'echo "[OMPVV_RESULT: test_a.c] Test failed on the '
                   'device."\nexit 0\n')
    out = tmp_path / "w.jsonl"
    run_baseline(index, ["omp_vv"],
                 Toolchain("afar", "", f"{FAKES}/fake_fc.sh - 0 {wrapped}"),
                 1, out, corpus_root=root, timeout_s=20)
    rows = read_baseline(out)
    assert {(r["status"], r["stage"], r["run_rc"]) for r in rows} == {
        ("fail", "run", 0)}
    assert all(r["reason"].startswith("suite_reported_failure")
               for r in rows)
    skipped = _exe(tmp_path, "exe_skip.sh",
                   'echo "[OMPVV_RESULT: test_a.c] Test skipped on the '
                   'device."\nexit 109\n')
    out = tmp_path / "s.jsonl"
    run_baseline(index, ["omp_vv"],
                 Toolchain("afar", "", f"{FAKES}/fake_fc.sh - 0 {skipped}"),
                 1, out, corpus_root=root, timeout_s=20)
    rows = read_baseline(out)
    assert {(r["status"], r["stage"]) for r in rows} == {
        ("harness_error", "run")}
    assert all(r["reason"].startswith("suite_skipped") for r in rows)
    # a passing line with exit 0 stays a pass (Fortran prints
    # "[OMPVV_RESULT test_a.F90] Test passed on the device.")
    ok = _exe(tmp_path, "exe_ok.sh",
              'echo "[OMPVV_RESULT test_a.F90] Test passed on the device."\n')
    out = tmp_path / "o.jsonl"
    run_baseline(index, ["omp_vv"],
                 Toolchain("afar", "", f"{FAKES}/fake_fc.sh - 0 {ok}"),
                 1, out, corpus_root=root, timeout_s=20)
    assert {r["status"] for r in read_baseline(out)} == {"pass"}


# ---- Tests of offload.engine.harness with fake compilers and fake programs -------------------------------

import json
import os
import re
import time

import pytest

from offload.engine.harness import (NOTES, PATTERNS, Outcome, Result,
                                classify_message, compile_script,
                                program_from_file, read_jsonl, run_program,
                                run_script, write_jsonl)

DATA = Path(__file__).parent.parent / "data"
FAKES_3 = DATA / "fakes"
MESSAGES_3 = DATA / "messages"
CONTROLS = DATA / "controls"
SEPARATOR = "==== verbatim output below ===="


def message(name: str) -> str:
    text = where.message(name).read_text()
    return text.split(SEPARATOR + "\n", 1)[1]


def fake_tc_3(name: str = "afar", msg: str | None = None, rc: int = 0,
            exe: str | Path | None = "exe_device_pass.sh") -> Toolchain:
    m = str(where.message(msg)) if msg else "-"
    if exe is None:
        e = "-"
    else:
        e = str(exe if Path(exe).is_absolute() else FAKES_3 / exe)
    cmd = f"{FAKES_3}/fake_fc.sh {m} {rc} {e}"
    return Toolchain(name, "", cmd, cc=cmd)  # cc: C programs




def run(tc, p=None, **kw) -> Result:
    kw.setdefault("timeout_s", 20)
    kw.setdefault("repeats", 1)
    return run_program(p or prog(), tc, 1, **kw)


def script(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(0o755)
    return path


# --- compile classification ---------------------------------------------------

def test_link_failure_is_harness_error():
    r = run(fake_tc_3("afar", "afar_link_quadmath", 1, None))
    assert r.outcome == Outcome.harness_error
    assert r.reason.startswith("environment:")
    assert "unable to find library -lquadmath" in r.reason


def test_missing_rocm_at_link_is_harness_error_not_rejected():
    # Without rocm, CCE's link prints undefined references as well; the
    # environment pattern must win over the undefined-symbol one.
    r = run(fake_tc_3("cce19", "cce_link_no_rocm", 1, None))
    assert r.outcome == Outcome.harness_error
    assert r.reason.startswith("environment:")


@pytest.mark.parametrize("msg", ["shell_no_module", "lmod_unknown_module",
                                 "shell_missing_compiler"])
def test_shell_environment_failures_are_harness_errors(msg):
    r = run(fake_tc_3("cce19", msg, 127, None))
    assert r.outcome == Outcome.harness_error


@pytest.mark.parametrize("tc,msg", [("afar", "afar_syntax_error"),
                                    ("afar", "afar_clause_not_allowed"),
                                    ("cce19", "cce_syntax_error"),
                                    ("cce19", "cce_invalid_clause")])
def test_compile_error_is_rejected(tc, msg):
    r = run(fake_tc_3(tc, msg, 1, None))
    assert r.outcome == Outcome.rejected
    assert r.reason.startswith("diagnostic:")
    assert r.stdout == ""


@pytest.mark.parametrize("tc,msg", [("afar", "afar_not_implemented"),
                                    ("cce19", "cce_deferred"),
                                    ("cce19", "cce_unsupported_construct")])
def test_not_implemented_is_rejected(tc, msg):
    r = run(fake_tc_3(tc, msg, 1, None))
    assert r.outcome == Outcome.rejected
    assert r.reason.startswith("not_implemented:")


@pytest.mark.parametrize("tc,msg,rc", [("afar", "afar_ice_segfault", 254),
                                       ("afar", "afar_ice_llvm_verifier", 1),
                                       ("afar", "afar_ice_fir_verification", 1),
                                       ("cce19", "cce_ice_ordered", 1),
                                       ("cce19", "cce_ice_addrspacecast", 1)])
def test_ice_is_rejected_with_reason_ice(tc, msg, rc):
    r = run(fake_tc_3(tc, msg, rc, None))
    assert r.outcome == Outcome.rejected
    assert r.reason.startswith("ice:")


@pytest.mark.parametrize("msg", ["cce_link_c_f_pointer", "cce_link_ompit"])
def test_undefined_symbol_from_compiler_code_is_rejected(msg):
    # real: the reference comes from the program's own (generated) objects
    r = run(fake_tc_3("cce19", msg, 1, None))
    assert r.outcome == Outcome.rejected
    assert r.reason.startswith("link_undefined_symbol:")


@pytest.mark.parametrize("msg", ["cce_invented_old_runtime",
                                 "cce_invented_libsci"])
def test_undefined_symbol_referenced_by_a_system_library_is_harness_error(msg):
    # invented messages (see their headers): the reference comes from a
    # system shared library, i.e. the environment
    r = run(fake_tc_3("cce19", msg, 1, None))
    assert r.outcome == Outcome.harness_error
    assert r.reason.startswith("environment:")
    assert ".so: undefined reference" in r.reason


def test_killed_compiler_is_harness_error_not_ice():
    # real: flang frontend SIGKILLed (OOM killer or external kill)
    r = run(fake_tc_3("afar", "afar_frontend_killed", 254, None))
    assert r.outcome == Outcome.harness_error
    assert "unable to execute command: Killed" in r.reason


def test_undefined_symbol_with_unknown_referrer_is_not_a_rejection(tmp_path):
    msg = tmp_path / "m.txt"
    msg.write_text(f"{SEPARATOR}\nlld: error: undefined symbol: foo\n")
    fc = f"{FAKES_3}/fake_fc.sh {msg} 1 -"
    r = run(Toolchain("cce19", "", fc))
    assert r.outcome == Outcome.harness_error


def test_temp_dir_name_is_scrubbed_from_results(tmp_path):
    # a fake compiler that quotes the source path in a flang-style error
    fc = script(tmp_path, "fc.sh",
                'src=${@: -3:1}\necho "$src:3:1: error: bad" >&2\n'
                'echo "../../$(basename $(dirname $src))/x.f90: more" >&2\n'
                "exit 1\n")
    r = run(Toolchain("afar", "", str(fc)))
    assert r.outcome == Outcome.rejected
    assert r.reason == "diagnostic: <tmpdir>/fake-prog.f90:3:1: error: bad"
    assert "harness-" not in r.stderr and "../../<tmpdir>/x.f90" in r.stderr


def test_unrecognised_compile_failure_is_harness_error():
    r = run(fake_tc_3("afar", None, 1, None))
    assert r.outcome == Outcome.harness_error
    assert r.reason.startswith("unclassified_compile_failure")


def test_compile_success_without_executable_is_harness_error():
    r = run(fake_tc_3("afar", None, 0, None))
    assert r.outcome == Outcome.harness_error
    assert r.reason.startswith("no_executable")


@pytest.mark.parametrize("tc,msg", [("afar", "afar_ignored_reverse_offload"),
                                    ("cce19", "cce_ignored_device")])
def test_ignored_warning_is_accepted_ignored(tc, msg):
    r = run(fake_tc_3(tc, msg, 0), repeats=3)
    assert r.outcome == Outcome.accepted_ignored
    assert r.reason.startswith("ignored:")
    # the program is still run once, for information
    assert "ran_on_host=0 check=pass" in r.reason


@pytest.mark.parametrize("tc,msg", [("afar", "afar_version_warning_not_ignored"),
                                    ("cce19", "cce_single_thread_warning")])
def test_other_warnings_do_not_make_accepted_ignored(tc, msg):
    r = run(fake_tc_3(tc, msg, 0))
    assert r.outcome == Outcome.correct_on_device


# --- run classification ---------------------------------------------------------

def test_device_pass_is_correct_on_device():
    r = run(fake_tc_3())
    assert r.outcome == Outcome.correct_on_device
    assert r.stdout.strip() == "RESULT ran_on_host=0 check=pass"
    assert not r.flaky


def test_host_run_is_fallback():
    r = run(fake_tc_3(exe="exe_host_pass.sh"))
    assert r.outcome == Outcome.fell_back_to_host


def test_mandatory_failure_then_host_run_is_fallback():
    r = run(fake_tc_3(exe="exe_mandatory_refused.sh"))
    assert r.outcome == Outcome.fell_back_to_host
    assert "without mandatory" in r.reason


def test_mandatory_failure_then_host_check_fail_is_wrong_answer():
    r = run(fake_tc_3(exe="exe_mandatory_refused_check_fail.sh"))
    assert r.outcome == Outcome.wrong_answer


def test_check_fail_is_wrong_answer():
    r = run(fake_tc_3(exe="exe_device_fail.sh"))
    assert r.outcome == Outcome.wrong_answer
    assert r.reason.startswith("check_fail")


def test_crash_is_wrong_answer_with_reason_crash():
    r = run(fake_tc_3(exe="exe_abort.sh"))
    assert r.outcome == Outcome.wrong_answer
    assert r.reason.startswith("crash")
    assert "SIGABRT" in r.reason


def test_multiple_result_lines_have_their_own_reason(tmp_path):
    exe = script(tmp_path, "two.sh",
                 'echo "RESULT ran_on_host=0 check=pass"\n'
                 'echo "RESULT ran_on_host=0 check=pass"\n')
    r = run(fake_tc_3(exe=exe))
    assert r.outcome == Outcome.wrong_answer
    assert r.reason.startswith("multiple_result_lines")


def test_second_run_timeout_stops_repeats(tmp_path):
    counter = tmp_path / "count"
    exe = script(tmp_path, "t.sh",
                 f"n=$(cat {counter} 2>/dev/null || echo 0)\n"
                 f"echo $((n + 1)) > {counter}\n"
                 'if [ "$OMP_TARGET_OFFLOAD" = mandatory ]; then exit 1; fi\n'
                 "sleep 1000\n")
    r = run(fake_tc_3(exe=exe), timeout_s=1, repeats=3)
    assert r.outcome == Outcome.wrong_answer and "timeout" in r.reason
    assert counter.read_text().strip() == "2"  # one primary + one second run


@pytest.mark.parametrize("tc,msg,note", [
    ("cce19", "cce_single_thread_warning", "ftn-7256"),
    ("afar", "afar_version_warning_not_ignored", "version_warning")])
def test_recognised_notes_are_appended_to_the_reason(tc, msg, note):
    r = run(fake_tc_3(tc, msg, 0))
    assert r.outcome == Outcome.correct_on_device
    assert r.reason.endswith(f"; note: {note}")


def test_missing_result_line_is_wrong_answer():
    r = run(fake_tc_3(exe="exe_no_result.sh"))
    assert r.outcome == Outcome.wrong_answer
    assert r.reason.startswith("no_result_line")


def test_runtime_loader_failure_is_harness_error():
    r = run(fake_tc_3("cce19", exe="exe_missing_lib.sh"))
    assert r.outcome == Outcome.harness_error
    assert r.reason.startswith("environment:")


def _alive(pid: int) -> bool:
    """`pid` has not exited (a zombie has): /proc where there is one, else ps."""
    import os
    import subprocess
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    if Path("/proc/self").exists():
        try:
            return Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1][0] != "Z"
        except (OSError, IndexError):
            return False
    st = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(st) and not st.startswith("Z")


def test_timeout_is_wrong_answer_with_reason(tmp_path):
    pidfile = tmp_path / "child.pid"
    exe = script(tmp_path, "hang.sh",
                 f"sleep 1000 &\necho $! > {pidfile}\nwait\n")
    t0 = time.monotonic()
    r = run(fake_tc_3(exe=exe), timeout_s=2, repeats=3)
    assert time.monotonic() - t0 < 15  # one run, no repeats after a timeout
    assert r.outcome == Outcome.wrong_answer
    assert r.reason == "timeout"
    pid = int(pidfile.read_text())
    for _ in range(50):
        if not _alive(pid):
            break
        time.sleep(0.1)
    assert not _alive(pid), "a child of the timed-out program survived"


def test_disagreeing_repeats_are_flaky(tmp_path):
    counter = tmp_path / "count"
    exe = script(tmp_path, "flaky.sh",
                 f"n=$(cat {counter} 2>/dev/null || echo 0)\n"
                 f"echo $((n + 1)) > {counter}\n"
                 'if [ "$n" = 1 ]; then\n'
                 '  echo "RESULT ran_on_host=0 check=fail"\n'
                 "else\n"
                 '  echo "RESULT ran_on_host=0 check=pass"\n'
                 "fi\n")
    r = run(fake_tc_3(exe=exe), repeats=3)
    assert counter.read_text().strip() == "3"
    assert r.flaky
    assert r.outcome == Outcome.wrong_answer  # the worst of the three
    assert r.reason.startswith("check_fail")
    assert "repeats:" in r.reason


def test_agreeing_repeats_run_full_count_and_are_not_flaky(tmp_path):
    counter = tmp_path / "count"
    exe = script(tmp_path, "count.sh",
                 f"n=$(cat {counter} 2>/dev/null || echo 0)\n"
                 f"echo $((n + 1)) > {counter}\n"
                 'echo "RESULT ran_on_host=0 check=pass"\n')
    r = run(fake_tc_3(exe=exe), repeats=3)
    assert counter.read_text().strip() == "3"
    assert not r.flaky
    assert r.outcome == Outcome.correct_on_device


def test_rejected_is_not_repeated(tmp_path):
    counter = tmp_path / "count"
    syntax_error = where.message("afar_syntax_error")
    fc = script(tmp_path, "fc.sh",
                f"n=$(cat {counter} 2>/dev/null || echo 0)\n"
                f"echo $((n + 1)) > {counter}\n"
                f"exec {FAKES_3}/fake_fc.sh {syntax_error} 1 - \"$@\"\n")
    r = run(Toolchain("afar", "", str(fc)), repeats=3)
    assert r.outcome == Outcome.rejected
    assert counter.read_text().strip() == "1"


def test_declarative_is_unobservable():
    r = run(fake_tc_3(), prog(observable=False))
    assert r.outcome == Outcome.unobservable
    assert r.observable is False


def test_unobservable_program_that_falls_back_is_still_fallback():
    r = run(fake_tc_3(exe="exe_host_pass.sh"), prog(observable=False))
    assert r.outcome == Outcome.fell_back_to_host


# --- environment of the run ---------------------------------------------------------

def test_run_script_disables_core_dumps_and_is_not_strict():
    tc = Toolchain("cce19", ". /etc/profile >/dev/null 2>&1\nmodule load x",
                   "ftn")
    s = run_script(tc, "/tmp/x/a.out", xnack=0, mandatory=True)
    assert "ulimit -c 0" in s
    assert s.index("ulimit -c 0") < s.index("a.out")
    assert "export HSA_XNACK=0" in s
    assert "export OMP_TARGET_OFFLOAD=mandatory" in s
    assert not re.search(r"set -[a-z]*[eu]", s)
    assert "|" not in s
    s2 = run_script(tc, "/tmp/x/a.out", xnack=1, mandatory=False)
    assert "unset OMP_TARGET_OFFLOAD" in s2
    assert "export HSA_XNACK=1" in s2
    s3 = run_script(tc, "/tmp/x/a.out", xnack=1, mandatory=True,
                    tmpdir="/tmp/x")
    # /etc/profile in the prelude resets TMPDIR: export it after the prelude
    assert s3.index("module load x") < s3.index("export TMPDIR=/tmp/x") \
        < s3.index("exec")


def test_compile_script_sets_tmpdir_after_the_prelude():
    tc = Toolchain("cce19", ". /etc/profile >/dev/null 2>&1\nmodule load x",
                   "ftn")
    s = compile_script(tc, "/tmp/x/p.f90", "/tmp/x/p.out", "-O2", "/tmp/x")
    assert s.index("ulimit -c 0") < s.index("module load x") \
        < s.index("export TMPDIR=/tmp/x") < s.index("ftn -fopenmp -O2")
    assert s.rstrip().endswith(
        Toolchain("cce19", "", "ftn").compile_cmd("/tmp/x/p.f90",
                                                   "/tmp/x/p.out", "-O2"))
    assert "|" not in s and not re.search(r"set -[a-z]*[eu]", s)


RESET_TMPDIR = "export TMPDIR=/var/tmp/not-the-run-dir"


def test_prelude_resetting_tmpdir_does_not_escape_the_run_dir(tmp_path):
    # like /etc/profile in the CCE prelude; the compiler and the program
    # must still see the per-run directory as TMPDIR
    fc = script(tmp_path, "fc.sh",
                'if [ "$(cd "$TMPDIR" && pwd -P)" != "$(pwd -P)" ]; then '
                'echo "TMPDIR=$TMPDIR" >&2; exit 1; fi\n'
                f'exec {FAKES_3}/fake_fc.sh - 0 {FAKES_3}/exe_core_check.sh "$@"\n')
    r = run(Toolchain("cce19", RESET_TMPDIR, str(fc)))
    assert r.outcome == Outcome.correct_on_device, r.stderr


def test_program_sees_core_dumps_off_xnack_and_tmpdir():
    r = run(fake_tc_3(exe="exe_core_check.sh"))
    assert r.outcome == Outcome.correct_on_device
    tc = Toolchain("cce19", RESET_TMPDIR,
                   fake_tc_3(exe="exe_core_check.sh").fc)
    assert run(tc).outcome == Outcome.correct_on_device


@pytest.mark.parametrize("xnack", [0, 1])
def test_xnack_value_reaches_the_program(tmp_path, xnack):
    exe = script(tmp_path, "x.sh",
                 f'if [ "$HSA_XNACK" = "{xnack}" ]; then c=pass; else c=fail; fi\n'
                 'echo "RESULT ran_on_host=0 check=$c"\n')
    r = run_program(prog(), fake_tc_3(exe=exe), xnack, timeout_s=20, repeats=1)
    assert r.outcome == Outcome.correct_on_device
    assert r.xnack == xnack


def test_temp_dir_is_removed(tmp_path):
    where = tmp_path / "where"
    exe = script(tmp_path, "w.sh",
                 f'pwd > {where}\necho "RESULT ran_on_host=0 check=pass"\n')
    run(fake_tc_3(exe=exe))
    d = Path(where.read_text().strip())
    assert d.name and not d.exists()


# --- Result content ------------------------------------------------------------------

def test_result_carries_program_markers():
    p = prog(id="omp52-clause-x", needs=("zero_copy",), evidence="copy_mode_only",
             legal=False, violates="OMP52-target-map-001",
             atoms=frozenset({"omp.directive.target", "omp.clause.map"}))
    r = run(fake_tc_3(), p, opt="-O0", thp="always")
    assert r.needs == ("zero_copy",)
    assert r.evidence == "copy_mode_only"
    assert r.legal is False and r.violates == "OMP52-target-map-001"
    assert r.atoms == ("omp.clause.map", "omp.directive.target")
    assert r.primary_atom == "omp.directive.target"
    assert r.version == 52
    assert r.thp == "always"
    assert r.opt == "-O0" and "-O0" in r.flags
    assert "--offload-arch=gfx942" in r.flags
    assert r.toolchain == "afar" and r.rocm is None


def test_version_defaults_to_zero_without_a_spec_id():
    assert run(fake_tc_3(), prog(id="control-x")).version == 0
    assert run(fake_tc_3(), prog(id="control-x"), version=60).version == 60


def test_thp_is_detected_when_not_given():
    r = run(fake_tc_3())
    assert r.thp in {"always", "madvise", "never", "unknown"}


def test_jsonl_round_trip(tmp_path):
    a = run(fake_tc_3(), prog(needs=("zero_copy",)))
    b = run(fake_tc_3("cce19", "cce_syntax_error", 1, None))
    path = tmp_path / "r.jsonl"
    write_jsonl([a, b], path)
    lines = path.read_text().splitlines()
    assert len(lines) == 2 and json.loads(lines[0])["outcome"] == a.outcome
    back = read_jsonl(path)
    assert back == [a, b]
    assert isinstance(back[0].outcome, Outcome)
    assert isinstance(back[0].atoms, tuple) and isinstance(back[0].needs, tuple)


# --- program_from_file ------------------------------------------------------------

def test_program_from_file_wraps_a_control():
    p = program_from_file(CONTROLS / "hang.f90")
    assert p.id == "hang" and p.legal and p.observable
    assert "program hang" in p.source
    q = program_from_file(CONTROLS / "hang.f90", id="ctl-hang", observable=False)
    assert q.id == "ctl-hang" and not q.observable


def test_program_from_file_reads_generated_header(tmp_path):
    from offload.engine.gen import generate
    g = next(iter(generate(["omp.directive.target"], 52)))
    path = tmp_path / "g.f90"
    path.write_text(g.source)
    p = program_from_file(path)
    assert (p.id, p.primary_atom, p.legal, p.observable, p.needs, p.evidence) \
        == (g.id, g.primary_atom, g.legal, g.observable, g.needs, g.evidence)


# --- the message table against captured real output -----------------------------

EXPECTED = {
    # name: (toolchain, category or None)
    "afar_syntax_error": ("afar", "error"),
    "afar_clause_not_allowed": ("afar", "error"),
    "afar_mlir_op_not_allowed": ("afar", "error"),
    "afar_unknown_directive": ("afar", "error"),
    "afar_not_implemented": ("afar", "not_implemented"),
    "afar_ice_segfault": ("afar", "ice"),
    "afar_ice_llvm_verifier": ("afar", "ice"),
    "afar_ice_fir_verification": ("afar", "ice"),
    "afar_ignored_reverse_offload": ("afar", "ignored"),
    "afar_version_warning_not_ignored": ("afar", None),
    "afar_link_quadmath": ("afar", "environment"),
    "afar_link_device_runtime": ("afar", "link_undefined"),
    "afar_run_xnack0_zero_copy": ("afar", None),
    "cce_syntax_error": ("cce19", "error"),
    "cce_invalid_clause": ("cce19", "error"),
    "cce_module_summary": ("cce19", "error"),
    "cce_unknown_directive": ("cce19", "error"),
    "cce_deferred": ("cce19", "not_implemented"),
    "cce_unsupported_construct": ("cce19", "not_implemented"),
    "cce_ice_ordered": ("cce19", "ice"),
    "cce_ice_addrspacecast": ("cce19", "ice"),
    "cce_ignored_device": ("cce19", "ignored"),
    "cce_single_thread_warning": ("cce19", None),
    "cce_link_c_f_pointer": ("cce19", "link_undefined"),
    "cce_link_ompit": ("cce19", "link_undefined"),
    "cce_link_no_rocm": ("cce19", "environment"),
    "cce_run_no_rocm": ("cce19", "environment"),
    "cce_run_xnack0_zero_copy": ("cce19", None),
    "shell_no_module": ("cce19", "environment"),
    "lmod_unknown_module": ("cce19", "environment"),
    "shell_missing_compiler": ("afar", "environment"),
    "afar_frontend_killed": ("afar", "environment"),
    "cce_invented_old_runtime": ("cce19", "environment"),
    "cce_invented_libsci": ("cce19", "environment"),
    # Run output of the present negative probes (no compile
    # category; harness.ERROR_TERMINATION)
    "afar_run_present_map": ("afar", None),
    "afar_run_present_motion": ("afar", None),
    "cce_run_present": ("cce19", None),
    # Run-time capacity limits (CAPACITY, not a
    # compile category)
    "cce_run_large_args": ("cce19", None),
    "afar_run_microtask_args": ("afar", None),
    # Compile output of the error-directive probes
    "afar_error_warning": ("afar", None),
    "afar_error_fatal": ("afar", "error"),
    "cce_error_warning": ("cce19", None),
    "cce_error_fatal": ("cce19", "error"),
    # OpenACC (ftn -h acc): a compile diagnostic and the run
    # output of the present negative probe
    "cce_acc_self_unsupported": ("cce19", "error"),
    "cce_acc_run_present": ("cce19", None),
    # C (amdclang, craycc): the tables "<family>:c"
    "afar_c_syntax_error": ("afar:c", "error"),
    "cce_c_syntax_error": ("cce19:c", "error"),
    "afar_c_error_warning": ("afar:c", None),
    "afar_c_error_fatal": ("afar:c", "error"),
    "afar_c_link_device_error": ("afar:c", "link_undefined"),
    "cce_c_error_warning": ("cce19:c", None),
    "cce_c_error_fatal": ("cce19:c", "error"),
    "afar_c_run_present": ("afar:c", None),
    "cce_c_run_present_assert": ("cce19:c", None),
    # NVHPC 25.11 (nvfortran, nvc) on wingtip; a feature the
    # compiler says it dropped is "not_implemented" in a failed compile and
    # "ignored" in a successful one (harness.run_program asks only for
    # "ignored" then: test_nvhpc_dropped_feature_compiles_as_ignored)
    "nvhpc_ice_nvvm": ("nvhpc", "ice"),
    "nvhpc_not_implemented_linear": ("nvhpc", "not_implemented"),
    "nvhpc_not_supported_gpu_region": ("nvhpc", "not_implemented"),
    "nvhpc_schedule_static_only": ("nvhpc", "not_implemented"),
    "nvhpc_unrecognized_failed": ("nvhpc", "not_implemented"),
    "nvhpc_not_supported_runtime_call": ("nvhpc", "not_implemented"),
    "nvhpc_syntax_error": ("nvhpc", "error"),
    "nvhpc_ignored_aligned": ("nvhpc", "not_implemented"),
    "nvhpc_ignored_unrecognized": ("nvhpc", "not_implemented"),
    "nvhpc_acc_syntax_error": ("nvhpc", "error"),
    "nvhpc_acc_run_present": ("nvhpc", None),
    "nvhpc_c_acc_run_present": ("nvhpc:c", None),  # OpenACC C
    "nvhpc_c_invalid_pragma": ("nvhpc:c", "error"),
    "nvhpc_c_severe": ("nvhpc:c", "error"),
    "nvhpc_c_not_implemented_bind": ("nvhpc:c", "not_implemented"),
    "nvhpc_c_not_supported_requires": ("nvhpc:c", "not_implemented"),
    "nvhpc_c_schedule_static_only": ("nvhpc:c", "not_implemented"),
    "nvhpc_c_gpu_targets_do_not_support": ("nvhpc:c", "not_implemented"),
    "nvhpc_c_not_in_nvidia_subset": ("nvhpc:c", "not_implemented"),
    "nvhpc_c_ice_nvvm": ("nvhpc:c", "ice"),
    "nvhpc_c_ice_internal": ("nvhpc:c", "ice"),
    "nvhpc_c_ice_llvm_opt": ("nvhpc:c", "ice"),
    "nvhpc_c_ice_translate": ("nvhpc:c", "ice"),
    "nvhpc_c_deprecated_note": ("nvhpc:c", None),
    "nvhpc_c_acc_clause_note": ("nvhpc:c", None),
    "nvhpc_c_error_directive": ("nvhpc:c", "error"),
    # A diagnostic, then the front end killed by a signal: ICE
    "nvhpc_acc_fort2_crash": ("nvhpc", "ice"),
    "nvhpc_frontend_killed": ("nvhpc", "environment"),
    "cce_acc_unsupported_construct": ("cce19", "not_implemented"),
    "nvhpc_c_acc_nvcpfe_crash": ("nvhpc:c", "ice"),
    "afar_c_extra_tokens_ignored": ("afar:c", "ignored"),
    "cce_c_extra_tokens_ignored": ("cce19:c", "ignored"),
    "afar_c_modifier_ignored": ("afar:c", "ignored"),
    "cce_c_ice": ("cce19:c", "ice"),
    "cce_c_not_yet_supported": ("cce19:c", "not_implemented"),
    # The widened catalog's C programs
    "afar_c_link_no_libcall": ("afar:c", "not_implemented"),
    "cce_c_unsupported_dynamic_alloca": ("cce19:c", "not_implemented"),
    # GCC 16.2 (gfortran, gcc; offload to amdgcn and nvptx): gfortran's
    # "Error:" / "Fatal Error:" lines, GCC's "sorry, unimplemented",
    # libgomp's present message; C as clang-like "file:L:C: error:"
    "gcc_syntax_error": ("gcc", "error"),
    "gcc_unclassifiable_directive": ("gcc", "error"),
    "gcc_fatal_module": ("gcc", "error"),
    "gcc_acc_located_error": ("gcc", "error"),
    "gcc_f951_error": ("gcc", "error"),
    "gcc_error_fatal": ("gcc", "error"),
    "gcc_error_warning": ("gcc", None),
    "gcc_sorry_unimplemented": ("gcc", "not_implemented"),
    "gcc_ignored_declare_target": ("gcc", "ignored"),
    "gcc_run_present": ("gcc", None),
    "gcc_acc_run_present": ("gcc", None),
    "gcc_c_syntax_error": ("gcc:c", "error"),
    "gcc_c_error_fatal": ("gcc:c", "error"),
    "gcc_c_error_warning": ("gcc:c", None),
    "gcc_c_sorry_unimplemented": ("gcc:c", "not_implemented"),
    # the offload link (mkoffload): nvptx-ld names no referrer (the
    # program's device image: libatomic calls the compiler generated);
    # lld (amdgcn) names the program's own object (the message probes)
    "gcc_link_unresolved_atomic": ("gcc", "link_undefined"),
    "gcc_c_link_unresolved_atomic": ("gcc:c", "link_undefined"),
    "gcc_link_undefined_probe": ("gcc", "link_undefined"),
    "gcc_c_link_undefined_probe": ("gcc:c", "link_undefined"),
    "gcc_c_run_present": ("gcc:c", None),
    # gfortran's middle end diagnoses in gcc's lower-case form (OpenACC loop)
    "gcc_acc_located_lower_error": ("gcc", "error"),
    # coverage parity: GCC 16.2's first captured ICEs (the harvested dev
    # programs on gcc_sm80): front end, middle end and the offload lto1
    "gcc_ice_trans_openmp": ("gcc", "ice"),
    "gcc_ice_gimplify": ("gcc", "ice"),
    "gcc_c_ice_omp_low": ("gcc:c", "ice"),
    "gcc_c_ice_offload_lto1": ("gcc:c", "ice"),
    # a reduced HeCBench program: the offload assembler refuses the compiler's own .s
    "gcc_c_ice_offload_assembler": ("gcc:c", "ice"),
}
# messages used by shell-level (COMMON) patterns for any toolchain
SHELL_MESSAGES = {"shell_no_module", "lmod_unknown_module",
                  "shell_missing_compiler", "cce_run_no_rocm"}


def test_every_captured_message_has_an_expectation():
    files = {p.stem for p in MESSAGES_3.rglob("*.txt")}
    assert files == set(EXPECTED)


def _tc_lang(key: str) -> tuple[str, str]:
    """(toolchain, lang) of an EXPECTED key ("afar:c" is AFAR's C table)."""
    tc, _, lang = key.partition(":")
    return tc, lang or "f90"


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_pattern_table_on_captured_message(name):
    tc, category = EXPECTED[name]
    text = message(name)
    found = classify_message(*_tc_lang(tc)[:1], text,
                             lang=_tc_lang(tc)[1])
    assert (found[0] if found else None) == category
    if found:  # the matched line (CCE: and its message line) quoted verbatim
        for part in found[1].split(" | "):
            assert part in text


def test_gcc_ice_pattern_ignores_echoed_source_text():
    """A diagnostic whose echoed source line holds
    the words is a rejection, not an ICE; the compiler's own line is."""
    text = ("x.f90:3:12:\n\n    3 |   print *, 'internal compiler error: no'\n"
            "      |            1\nError: Unclassifiable statement at (1)\n")
    found = classify_message("gcc", text, lang="f90")
    assert not found or found[0] != "ice"
    assert classify_message("gcc", "lto1: internal compiler error: Segmentation fault\n",
                            lang="c")[0] == "ice"


def test_cce_reason_carries_the_message_text():
    r = run(fake_tc_3("cce19", "cce_invalid_clause", 1, None))
    assert r.reason.startswith("diagnostic: ftn-1519 ftn: ERROR")
    assert 'Invalid clause "SEVERITY" for directive !$OMP PARALLEL DO' \
        in r.reason


def _invented(name: str) -> bool:
    return "INVENTED" in where.message(name).read_text().split(
        SEPARATOR, 1)[0]


def test_every_pattern_matches_a_real_message_of_its_own_toolchain():
    common = set(harness.COMMON_ENVIRONMENT)
    for tc, table in list(PATTERNS.items()) + list(NOTES.items()):
        own = [message(n) for n, (t, _) in EXPECTED.items()
               if t == tc and not _invented(n)]
        if tc.endswith(":c"):
            # A C table reuses its family's environment and link
            # patterns (the same loader, linker and module system), whose
            # real messages are the family's
            base = tc.split(":")[0]
            own += [message(n) for n, (t, c) in EXPECTED.items()
                    if t == base and c in ("environment", "link_undefined")
                    and not _invented(n)]
        shell = [message(n) for n in SHELL_MESSAGES]
        for category, patterns in (table.items() if tc in PATTERNS and
                                   table is PATTERNS[tc] else
                                   [("note", tuple(table.values()))]):
            for pat in patterns:
                texts = own + (shell if pat in common else [])
                assert any(re.search(pat, t, re.M) for t in texts), \
                    f"{tc}/{category}: {pat!r} matches no real {tc} message"


def test_message_files_say_where_they_came_from():
    for p in MESSAGES_3.rglob("*.txt"):
        head = p.read_text().split(SEPARATOR, 1)[0]
        assert "# source:" in head and "# exit status:" in head, p.name


def test_harness_has_no_strict_mode():
    src = Path(harness.__file__).read_text()
    assert not re.search(r"set -[a-z]*[eu]\b", src)


# --- the hang control on the real toolchains ------------------------------------

@pytest.mark.gpu
@pytest.mark.parametrize("name", ["afar", "cce19"])
def test_hang_control_times_out_at_baseline_opt(name):
    # the spin flag must be volatile, or AFAR's optimiser (-O1 and up)
    # deletes the side-effect-free loop and the program completes
    from offload.engine.toolchains import TOOLCHAINS
    p = program_from_file(CONTROLS / "hang.f90", id="control-hang")
    r = run_program(p, TOOLCHAINS[name], 1, opt="-O2", timeout_s=8, repeats=1)
    assert r.outcome == Outcome.wrong_answer
    assert r.reason == "timeout"


def test_cce_reason_quotes_the_root_error_not_the_module_summary():
    found = classify_message("cce19", message("cce_module_summary"))
    assert found is not None
    assert "ftn-1725" in found[1] and "ftn-855" not in found[1]
    assert "INDIRECT, LINK, TO or DEVICE_TYPE" in found[1]


def test_execute_scrubs_the_callers_openmp_environment(tmp_path, monkeypatch):
    for k in ("OMP_NUM_THREADS", "OMP_DEFAULT_DEVICE", "LIBOMPTARGET_INFO",
              "CRAY_ACC_DEBUG", "OMP_TARGET_OFFLOAD", "HSA_XNACK"):
        monkeypatch.setenv(k, "7")
    ex = harness._execute("env", tmp_path, 20)
    assert ex.rc == 0
    for k in ("OMP_NUM_THREADS", "OMP_DEFAULT_DEVICE", "LIBOMPTARGET_INFO",
              "CRAY_ACC_DEBUG", "OMP_TARGET_OFFLOAD", "HSA_XNACK"):
        assert f"{k}=" not in ex.stdout


# --- Negative probes (Program.expect == "error_termination") ----------------

PRESENT_MESSAGES = {"afar_run_present_map": "afar",
                    "afar_run_present_motion": "afar",
                    "cce_run_present": "cce19",
                    # C (the AFAR C programs' runtime is the same)
                    "afar_c_run_present": "afar:c",
                    # NVHPC's OpenACC runtime
                    "nvhpc_acc_run_present": "nvhpc",
                    # NVHPC's OpenACC runtime under nvc
                    "nvhpc_c_acc_run_present": "nvhpc:c",
                    # GCC's libgomp (OpenMP and OpenACC alike)
                    "gcc_run_present": "gcc",
                    "gcc_acc_run_present": "gcc",
                    "gcc_c_run_present": "gcc:c"}


def probe_prog(**kw) -> Program:
    from offload.engine.gen import _legal
    # the program as captured in tests/data/messages (2026-10-18): without
    # the derivation header line, which shifts the line numbers
    # CCE's runtime message names
    g = _legal("omp.clause.map.present", 52)
    kw.setdefault("source", g.source)
    return prog(id="omp52-clause-map-present", evidence="probe",
                expect="error_termination",
                primary_atom="omp.clause.map.present",
                atoms=frozenset({"omp.clause.map.present"}), **kw)


def message_exe(tmp_path: Path, name: str, rc: int) -> Path:
    """A fake program that prints a captured run output to stderr and
    exits with `rc` (128 + n for a signal is a plain exit status here)."""
    path = tmp_path / f"{name}.txt"
    path.write_text(message(name))
    return script(tmp_path, f"{name}.sh", f"cat {path} >&2\nexit {rc}\n")


@pytest.mark.parametrize("name", sorted(PRESENT_MESSAGES))
def test_error_termination_with_the_runtime_message_is_correct(tmp_path,
                                                               name):
    tc, lang = _tc_lang(PRESENT_MESSAGES[name])
    r = run(fake_tc_3(tc, exe=message_exe(tmp_path, name, 1)),
            probe_prog(lang="c" if lang == "c" else "fortran"))
    assert r.outcome == Outcome.correct_on_device
    assert r.reason.startswith("error_termination: ")
    masked = re.sub(r"0x[0-9a-fA-F]+", "0x...", message(name))
    assert r.reason.split(": ", 1)[1].split(";")[0] in masked


def test_probe_that_continues_is_a_check_failure():
    from offload.engine.mutate import kill_kind
    r = run(fake_tc_3(exe="exe_device_fail.sh"), probe_prog())
    assert r.outcome == Outcome.wrong_answer
    assert r.reason.startswith("no_error_termination: ran_on_host=0 "
                               "check=fail")
    assert kill_kind(r) == "check_fail"


def test_probe_crash_without_the_message_is_wrong_answer():
    r = run(fake_tc_3(exe="exe_abort.sh"), probe_prog())
    assert r.outcome == Outcome.wrong_answer
    assert "no expected error message" in r.reason


def test_probe_message_of_the_other_toolchain_does_not_count(tmp_path):
    r = run(fake_tc_3("cce19", exe=message_exe(tmp_path, "afar_run_present_map",
                                             1)), probe_prog())
    assert r.outcome == Outcome.wrong_answer


def test_cce_c_present_assertion_is_no_error_termination(tmp_path):
    # CCE's C runtime asserts on any present map (captured)
    r = run(fake_tc_3("cce19", exe=message_exe(
        tmp_path, "cce_c_run_present_assert", 134)),
        probe_prog(lang="c"))
    assert r.outcome == Outcome.wrong_answer
    assert "no expected error message" in r.reason


@pytest.mark.parametrize("msg", ["nvhpc_ignored_aligned",
                                 "nvhpc_ignored_unrecognized"])
def test_nvhpc_dropped_feature_compiles_as_ignored(msg):
    """Nvfortran warns that it dropped a feature ("OpenMP
    feature, ALIGNED, not yet implemented", "Unrecognized OpenMP
    directive") and builds: accepted_ignored, the run quoted."""
    r = run(fake_tc_3("nvhpc", msg, 0))
    assert r.outcome == Outcome.accepted_ignored
    assert r.reason.startswith("ignored: NVFORTRAN-W-")


def test_nvhpc_failed_compile_with_a_dropped_feature_is_rejected():
    r = run(fake_tc_3("nvhpc", "nvhpc_unrecognized_failed", 2, None))
    assert r.outcome == Outcome.rejected
    assert r.reason.startswith("not_implemented: NVFORTRAN-W-0287-"
                               "Unrecognized OpenMP directive - depobj")


def test_nvhpc_c_rejection_and_ice():
    p = prog(lang="c", source="// fake\n")
    r = run(fake_tc_3("nvhpc", "nvhpc_c_invalid_pragma", 2, None), p)
    assert r.outcome == Outcome.rejected
    assert r.reason.startswith('diagnostic: "<tmpdir>/p.c", line ') \
        or "error: invalid text in pragma" in r.reason
    r = run(fake_tc_3("nvhpc", "nvhpc_c_ice_internal", 2, None), p)
    assert r.reason.startswith("ice: NVC++-F-0000-Internal compiler error")


def test_error_termination_patterns_match_real_output():
    for name, tc in PRESENT_MESSAGES.items():
        assert any(re.search(p, message(name), re.M)
                   for p in harness.ERROR_TERMINATION[tc]), name
    for tc, pats in harness.ERROR_TERMINATION.items():
        for p in pats:
            assert any(re.search(p, message(n), re.M)
                       for n, t in PRESENT_MESSAGES.items() if t == tc), p


def test_program_from_file_reads_expect(tmp_path):
    from offload.engine.gen import generate
    (g,) = [q for q in generate(["omp.clause.to.present"], 52) if q.legal]
    path = tmp_path / "g.f90"
    path.write_text(g.source)
    assert program_from_file(path).expect == "error_termination"



def test_error_termination_reason_has_no_host_address(tmp_path):
    # Repeats compare reasons; an ASLR address would make
    # every probe cell flaky
    r = run(fake_tc_3("afar", exe=message_exe(tmp_path, "afar_run_present_map",
                                            1)), probe_prog())
    assert r.outcome == Outcome.correct_on_device
    assert not re.search(r"0x[0-9a-fA-F]{4,}", r.reason)


def test_cce_present_miss_must_be_at_the_probe_line(tmp_path):
    # CCE's present-table miss names the source line; only a
    # miss at a directive with the present modifier counts
    src = probe_prog().source.splitlines()
    (line,) = [k + 1 for k, x in enumerate(src)
               if x.strip().startswith("!$omp") and "present" in x]
    assert f".f90:{line}" in message("cce_run_present")
    other = "\n".join(src[:line - 1] + ["  ! moved"] + src[line - 1:]) + "\n"
    r = run(fake_tc_3("cce19", exe=message_exe(tmp_path, "cce_run_present", 1)),
            probe_prog(source=other))
    assert r.outcome == Outcome.wrong_answer


# --- Compile-output probes (error directive) ------------------------

def compile_probe(expect: str) -> Program:
    from offload.engine.gen import PROBE_TOKEN
    return prog(id="omp60-clause-message", evidence="probe", expect=expect,
                token=PROBE_TOKEN, primary_atom="omp.clause.message",
                atoms=frozenset({"omp.clause.message"}))


@pytest.mark.parametrize("tc,msg", [("afar", "afar_error_warning"),
                                    ("cce19", "cce_error_warning"),
                                    ("gcc", "gcc_error_warning")])
def test_compile_message_shown_then_run(tc, msg):
    r = run(fake_tc_3(tc, msg, 0), compile_probe("compile_message"))
    assert r.outcome == Outcome.correct_on_device
    assert "compile message: " in r.reason


@pytest.mark.parametrize("tc", ["afar", "cce19"])
def test_compile_message_missing_is_a_check_failure(tc):
    from offload.engine.mutate import kill_kind
    r = run(fake_tc_3(tc), compile_probe("compile_message"))
    assert r.outcome == Outcome.wrong_answer
    assert r.reason.startswith("check_fail: no compile-time message")
    assert kill_kind(r) == "check_fail"


@pytest.mark.parametrize("tc,msg", [("afar", "afar_error_fatal"),
                                    ("cce19", "cce_error_fatal"),
                                    ("gcc", "gcc_error_fatal")])
def test_compile_error_where_a_warning_is_required_fails(tc, msg):
    r = run(fake_tc_3(tc, msg, 1), compile_probe("compile_message"))
    assert r.outcome == Outcome.wrong_answer
    assert r.reason.startswith("check_fail: compile-time error termination")


@pytest.mark.parametrize("tc,msg", [("afar", "afar_error_fatal"),
                                    ("cce19", "cce_error_fatal"),
                                    ("gcc", "gcc_error_fatal")])
def test_compile_error_termination_is_correct(tc, msg):
    r = run(fake_tc_3(tc, msg, 1, None), compile_probe("compile_error"))
    assert r.outcome == Outcome.correct_on_device
    assert r.reason.startswith("compile_error_termination: ")


@pytest.mark.parametrize("tc,msg", [("afar", "afar_error_warning"),
                                    ("cce19", "cce_error_warning"),
                                    ("gcc", "gcc_error_warning")])
def test_compile_without_error_termination_fails(tc, msg):
    r = run(fake_tc_3(tc, msg, 0), compile_probe("compile_error"))
    assert r.outcome == Outcome.wrong_answer
    assert r.reason.startswith("check_fail: no compile-time error "
                               "termination")


@pytest.mark.parametrize("tc,msg", [("afar", "afar_syntax_error"),
                                    ("cce19", "cce_syntax_error")])
@pytest.mark.parametrize("expect", ["compile_message", "compile_error"])
def test_compile_probe_rejection_without_the_token_is_rejected(tc, msg,
                                                               expect):
    r = run(fake_tc_3(tc, msg, 1, None), compile_probe(expect))
    assert r.outcome == Outcome.rejected


# --- The probe line on a continuation ------------------------------------------------------------------

def _continued_probe(present_first: bool) -> str:
    """The map-present probe with its present directive (line 35) split
    over two lines; the present modifier on the first line or on the
    `!$omp&` continuation line."""
    src = probe_prog().source.splitlines()
    k = next(i for i, x in enumerate(src)
             if x.strip().startswith("!$omp") and "present" in x)
    assert k + 1 == 35
    if present_first:
        new = ["  !$omp target map(present, to: a) &", "  !$omp& map(from: b)"]
    else:
        new = ["  !$omp target map(from: b) &", "  !$omp& map(present, to: a)"]
    return "\n".join(src[:k] + new + src[k + 1:]) + "\n"


@pytest.mark.parametrize("present_first", [True, False])
def test_cce_present_miss_on_a_continued_directive(tmp_path, present_first):
    # CCE names the directive's first line (35); the present modifier may
    # be on the !$omp& continuation line
    r = run(fake_tc_3("cce19", exe=message_exe(tmp_path, "cce_run_present", 1)),
            probe_prog(source=_continued_probe(present_first)))
    assert r.outcome == Outcome.correct_on_device, r.reason


def test_probe_line_check_reads_the_whole_directive():
    text = message("cce_run_present")
    cont = _continued_probe(False)
    assert harness.probe_termination("cce19", "fortran", cont, text)
    # the miss named at the continuation line counts too
    assert harness.probe_termination(
        "cce19", "fortran", cont, text.replace(".f90:35", ".f90:36"))
    # a directive without present does not
    src = probe_prog().source.splitlines()
    moved = "\n".join(src[:34] + ["  ! moved"] + src[34:]) + "\n"
    assert harness.probe_termination("cce19", "fortran", moved, text) is None
    # AFAR's message is specific to the modifier: no line check
    assert harness.probe_termination(
        "afar", "fortran", moved, message("afar_run_present_map"))


def test_expected_run_on_uses_the_harness_probe_check():
    """offload.engine.expected reads a run's error termination with
    the harness's check (the line of a CCE present-table miss)."""
    from offload.engine import expected as E
    text = message("cce_run_present")
    src = probe_prog().source.splitlines()
    moved = "\n".join(src[:34] + ["  ! moved"] + src[34:]) + "\n"
    assert E.terminated("cce19", probe_prog().source, text)
    assert E.terminated("cce20", _continued_probe(False), text)
    assert not E.terminated("cce19", moved, text)
    assert E.terminated("afar", moved, message("afar_run_present_map"))


# --- Machine, arch and GPU in every row ----------------------------

def test_result_records_machine_arch_and_gpu(monkeypatch):
    monkeypatch.setattr(harness, "detect_gpu",
                        lambda: ("gfx942", "AMD Instinct MI300A"))
    r = run(fake_tc_3())
    assert (r.machine, r.arch, r.gpu) == ("tuolumne", "gfx942",
                                          "gfx942 AMD Instinct MI300A")
    assert r.device == "gfx942 (AMD Instinct MI300A)"


def test_old_rows_without_the_task30_fields_still_read(tmp_path):
    a = run(fake_tc_3())
    d = {k: v for k, v in dataclasses.asdict(a).items()
         if k not in ("machine", "arch", "gpu")}
    path = tmp_path / "old.jsonl"
    path.write_text(json.dumps(d) + "\n")
    back = read_jsonl(path)[0]
    assert back.arch == "" and back.program_id == a.program_id


def test_toolchain_of_another_arch_is_not_run(monkeypatch):
    """A gfx90a toolchain on a gfx942 node (or the reverse) is an
    environment error, never a result of the program."""
    import dataclasses as dc
    monkeypatch.setattr(harness, "detect_gpu",
                        lambda: ("gfx942", "AMD Instinct MI300A"))
    tc = dc.replace(fake_tc_3("afar_g90"), arch="gfx90a", machine="tioga",
                    xnack_modes=(0,))
    r = run_program(prog(), tc, 0, timeout_s=20, repeats=1)
    assert r.outcome == Outcome.harness_error
    assert r.reason.startswith("environment: wrong_arch")
    assert r.arch == "gfx90a" and r.device == "gfx90a (AMD Instinct MI250X)"


def test_unknown_gpu_does_not_block_a_run(monkeypatch):
    monkeypatch.setattr(harness, "detect_gpu", lambda: ("", ""))
    assert run(fake_tc_3()).outcome == Outcome.correct_on_device


def test_c_math_programs_link_libm():
    """A C program that includes <math.h> (or <complex.h>) links
    -lm, as omp_vv's C tests do; other programs are unchanged."""
    import dataclasses as dc
    from offload.engine.gen import Program
    from offload.engine.harness import with_libm
    from offload.engine.toolchains import TOOLCHAINS
    tc = dc.replace(TOOLCHAINS["afar"], lang="c")
    p = Program("omp52-c-x", "c", "#include <math.h>\nint main(void){}\n",
                frozenset(), "x", True, None, True)
    assert "-lm" in with_libm(tc, p).flags().split()
    q = dc.replace(p, source="#include <stdio.h>\nint main(void){}\n")
    assert with_libm(tc, q) is tc
    f = dc.replace(p, lang="fortran")
    assert with_libm(tc, f) is tc
    assert with_libm(with_libm(tc, p), p).extra.split().count("-lm") == 1


_pid_alive = _alive


def test_a_run_dies_with_its_runner(tmp_path):
    """A program run is in its own process group (so
    the timeout kills the whole group), and it must not outlive the
    process that runs it either: when the runner is killed (a campaign
    stopped by hand, a pool worker that dies), the run gets SIGKILL
    (PR_SET_PDEATHSIG). Seed 72 of n1x0 ran on two A100s for 12.5 hours
    after its first campaign was stopped."""
    import subprocess
    import sys
    import time
    pidf = tmp_path / "pid"
    code = ("import sys; from pathlib import Path; "
            "from offload.engine import harness; "
            f"harness._execute('echo $$ > {pidf}; exec sleep 300\\n', "
            f"Path({str(tmp_path)!r}), 600)")
    runner = subprocess.Popen([sys.executable, "-c", code],
                              cwd=Path(__file__).resolve().parent.parent.parent)
    for _ in range(100):
        if pidf.exists() and pidf.read_text().strip():
            break
        time.sleep(0.1)
    pid = int(pidf.read_text())
    assert _pid_alive(pid)
    runner.kill()
    runner.wait()
    for _ in range(50):
        if not _pid_alive(pid):
            break
        time.sleep(0.1)
    alive = _pid_alive(pid)
    if alive:
        os.kill(pid, 9)
    assert not alive


@pytest.mark.parametrize("ignore_term", [False, True])
@pytest.mark.parametrize("runner_fate", ["killed", "stopped"])
def test_a_grandchild_is_bounded_without_the_runner(tmp_path, runner_fate,
                                                     ignore_term):
    """Fix: PR_SET_PDEATHSIG reaches the direct
    child only; a compiler or program that the script starts (a
    grandchild), even one that ignores SIGTERM, must be gone within the
    bound when the runner is killed, when it is stopped (its own timer
    never fires), and at a plain timeout: the harness's watchdog (outside
    the run's group) sends the group TERM, then KILL after KILL_AFTER_S."""
    import signal as sg
    import subprocess
    import sys
    import time
    from offload.engine import harness
    pidf = tmp_path / "pid"
    T = 3
    child = ("bash -c 'trap \\\"\\\" TERM; exec sleep 300'" if ignore_term
             else "sleep 300")
    code = ("from pathlib import Path; from offload.engine import harness; "
            f"harness._execute(\"{child} & echo $! > {pidf}; wait\\n\", "
            f"Path({str(tmp_path)!r}), {T})")
    root = Path(__file__).resolve().parent.parent.parent
    runner = subprocess.Popen([sys.executable, "-c", code], cwd=root)
    for _ in range(100):
        if pidf.exists() and pidf.read_text().strip():
            break
        time.sleep(0.1)
    pid = int(pidf.read_text())
    t0 = time.time()
    if runner_fate == "killed":
        runner.kill()
        limit = harness.KILL_AFTER_S + 1
    else:
        runner.send_signal(sg.SIGSTOP)
        limit = T + harness.GRACE_S + harness.KILL_AFTER_S + 1
    while _pid_alive(pid) and time.time() - t0 < limit + 5:
        time.sleep(0.2)
    gone_after = time.time() - t0
    alive = _pid_alive(pid)
    if alive:
        os.kill(pid, 9)
    runner.kill()
    runner.wait()
    assert not alive and gone_after <= limit, gone_after


def test_timeout_wrapper_keeps_exit_status_and_signals(tmp_path):
    """The coreutils timeout wrapper passes the script's exit status and
    death signal through, and a run over the limit is still a timeout."""
    from offload.engine import harness
    assert harness._execute("exit 3\n", tmp_path, 20).rc == 3
    assert harness._execute("ulimit -c 0; kill -SEGV $$\n", tmp_path,
                            20).rc == -11
    ex = harness._execute("echo hi; exec sleep 30\n", tmp_path, 1)
    assert ex.timed_out and ex.stdout == "hi\n"


def _watchdogs(own: bool = False) -> list[int]:
    """pids of this user's harness watchdogs (argv[0] "watchdog"); `own`: only
    those this process started (other harness runs of the same user, e.g. a
    campaign on the same machine, start their own and are not this test's)."""
    out = []
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            argv = (d / "cmdline").read_bytes().split(b"\0")
            status = (d / "status").read_text()
            uid = status.split("Uid:")[1].split()[0]
            ppid = int(status.split("PPid:")[1].split()[0])
        except OSError:
            continue
        if own and ppid != os.getpid():
            continue
        if int(uid) == os.getuid() and b"watchdog" in argv[3:4] and \
                any(b"kill -KILL" in a for a in argv):
            out.append(int(d.name))
    return out


@pytest.mark.needs_linux("/proc")
@pytest.mark.parametrize("runner", ["alive", "gone"])
def test_the_watchdog_itself_ends_a_term_ignoring_group(tmp_path, runner):
    """The watchdog alone (not the
    runner's killpg) ends a group whose grandchild ignores TERM, at its own
    deadline while the runner is alive and blocked, or as soon as the
    runner's pipe closes (the runner died); and it exits afterwards."""
    import subprocess
    import time
    from offload.engine import harness
    pidf = tmp_path / "pid"
    grp = subprocess.Popen(
        ["bash", "-c", "bash -c 'trap \"\" TERM; exec sleep 300' & "
         f"echo $! > {pidf}; wait"], start_new_session=True)
    for _ in range(100):
        if pidf.exists() and pidf.read_text().strip():
            break
        time.sleep(0.1)
    pid = int(pidf.read_text())
    # the grandchild ignores TERM only once it is `sleep` (the trap is set before the exec): a
    # watchdog started earlier could end it with TERM and then wait out its KILL delay
    for _ in range(100):
        try:
            if Path(f"/proc/{pid}/comm").read_text().strip() == "sleep":
                break
        except OSError:
            break
        time.sleep(0.05)
    T = 1
    dog = harness._watchdog(grp.pid, T)
    assert dog is not None
    t0 = time.time()
    if runner == "gone":
        dog.close_runner_end()      # what the runner's death does
        limit = harness.KILL_AFTER_S + 1
    else:
        limit = T + harness.GRACE_S + harness.KILL_AFTER_S + 1
    while _pid_alive(pid) and time.time() - t0 < limit + 5:
        time.sleep(0.2)
    gone_after = time.time() - t0
    alive = _pid_alive(pid)
    if alive:
        os.kill(pid, 9)
    grp.wait()
    assert not alive and gone_after <= limit, gone_after
    dog.proc.wait(timeout=5)        # the watchdog exits on its own
    harness._stop_watchdog(dog)
    assert dog.proc.pid not in _watchdogs()


@pytest.mark.needs_linux("/proc")
def test_no_watchdog_outlives_a_run(tmp_path):
    from offload.engine import harness
    before = set(_watchdogs(own=True))
    assert harness._execute("echo ok\n", tmp_path, 30).stdout == "ok\n"
    assert harness._execute("exec sleep 30\n", tmp_path, 1).timed_out
    assert set(_watchdogs(own=True)) <= before


@pytest.mark.needs_linux("/proc")
def test_own_watchdogs_sees_a_watchdog_left_running(tmp_path):
    """The check above still catches a leak: a watchdog this process
    started and did not stop is counted."""
    import subprocess
    from offload.engine import harness
    grp = subprocess.Popen(["sleep", "30"], start_new_session=True)
    dog = harness.watch_group(grp.pid, 60)
    try:
        assert dog.proc.pid in _watchdogs(own=True)
    finally:
        harness.stop_watch(dog)
        grp.kill()
        grp.wait()
    assert dog.proc.pid not in _watchdogs(own=True)


def test_watch_group_is_the_shared_helper(tmp_path):
    """Watch_group(pgid, limit_s, kill_after_s) /
    stop_watch(dog) for callers that start their own process group
    (offload.engine.stress_exec.run_group)."""
    import subprocess
    import time
    from offload.engine import harness
    grp = subprocess.Popen(["bash", "-c", "trap '' TERM; exec sleep 300"],
                           start_new_session=True)
    time.sleep(0.3)
    t0 = time.time()
    dog = harness.watch_group(grp.pid, 1, kill_after_s=1)
    assert grp.wait(timeout=10) == -9 and time.time() - t0 < 5
    dog.proc.wait(timeout=5)
    harness.stop_watch(dog)
    harness.stop_watch(None)


# --- Classification from all of a failure's messages -----------------

@pytest.mark.parametrize("name,key", [("nvhpc_acc_fort2_crash", "nvhpc"),
                                      ("nvhpc_c_acc_nvcpfe_crash",
                                       "nvhpc:c")])
def test_reject_followed_by_front_end_signal_is_an_ice(name, key):
    tc, lang = _tc_lang(key)
    text = message(name)
    found = harness.classify_all(tc, text, lang=lang)
    assert [c for c, _ in found] == ["ice", "error"]
    assert "TERMINATED by signal 11" in found[0][1]
    r = run(fake_tc_3(tc, name, 2, None), prog(lang="c" if lang == "c"
                                              else "fortran"))
    assert r.outcome == Outcome.rejected
    assert r.reason.startswith("ice: ") and "TERMINATED" in r.reason
    # every classified message is recorded, worst first
    assert r.messages.startswith("ice: ") and "|| diagnostic: " in r.messages


def test_messages_of_a_plain_rejection_is_its_one_message():
    r = run(fake_tc_3("cce19", "cce_invalid_clause", 1, None))
    assert r.messages.startswith("diagnostic: ftn-1519") and "||" not in \
        r.messages


def test_stress_classifier_reads_the_c_table_for_c():
    """craycc's clang crash was an unclassified compile
    failure in the stress classifier (it read the Fortran table)."""
    from offload.engine import stress_exec as X
    tc = Toolchain("cce19", "", "true", lang="c")
    cls, reason = X.classify_compile(tc, 1, message("cce_c_ice"), [])
    assert cls == "ice", reason


@pytest.mark.parametrize("name,tc", [("cce_run_large_args", "cce21"),
                                     ("afar_run_microtask_args", "afar")])
def test_capacity_messages(name, tc):
    """The runtime's capacity messages."""
    from offload.engine.harness import capacity_message
    line = capacity_message(tc, message(name))
    assert line and line in message(name)
    assert capacity_message("nvhpc", message(name)) is None
    assert capacity_message(tc, message("cce_run_present")) is None
