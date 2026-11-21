"""OpenACC fuzz programs (generator fuzz-acc1, offload.engine.fuzz_acc)."""
import re
import shutil

import pytest

from offload.engine import fuzz, fuzz_acc, fuzz_exec


def test_an_acc_program_is_openacc_only_and_passes_the_openacc_rules():
    for s in range(1, 81):
        p = fuzz.generate(s, "fuzz-acc1")
        assert p.model == "acc" and p.lang == "f90" and p.gen_version == "fuzz-acc1"
        assert "! generator: fuzz-acc1" in p.source and "!$acc " in p.source
        assert "!$omp" not in p.source and not re.search(r"\bomp_\w+", p.source)
        assert fuzz_acc.check_rules_acc(p.source) is None, s


def test_deferred_tasks_are_one_async_queue_waited_on():
    """A nowait kernel or data task is async(1); each taskwait is wait(1), and the program waits
    before its checksum."""
    seen = 0
    for s in range(1, 200):
        p = fuzz.generate(s, "fuzz-acc1")
        if "async(" not in p.source:
            continue
        seen += 1
        assert set(re.findall(r"async\((\d+)\)", p.source)) == {"1"}
        body, tail = p.source.split("! fuzz: checksum")
        assert "!$acc wait(1)" in body.rsplit("async(1)", 1)[1], s
    assert seen > 5


def test_the_frame_has_no_openmp_line_left():
    with pytest.raises(ValueError, match="no OpenACC form"):
        fuzz_acc.acc_frame("  !$omp masked\n")


def test_check_routes_an_acc_program_to_the_openacc_checks(monkeypatch):
    p = fuzz.generate(3, "fuzz-acc1")
    monkeypatch.setattr(fuzz_acc, "check_acc", lambda src, expected=None: fuzz.CheckResult("rules", "acc"))
    assert fuzz.check(p.source, expected=p.expected) == fuzz.CheckResult("rules", "acc")


def test_the_runner_builds_an_acc_program_with_the_openacc_model():
    assert fuzz_exec.toolchain_for("cce21", "f90", "acc").model == "acc"
    assert fuzz_exec.toolchain_for("cce21", "f90").model == "omp"


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="needs gfortran (the elided run)")
def test_the_elided_run_of_an_acc_program_is_the_model():
    for s in (2, 14):
        p = fuzz.generate(s, "fuzz-acc1")
        assert fuzz_acc.check_defined_acc(p.source, p.expected) is None, s
        assert fuzz_exec.elision_value(p.source) == p.expected
    p = fuzz.generate(2, "fuzz-acc1")
    assert "the model" in fuzz_acc.check_defined_acc(p.source, p.expected + 1)
