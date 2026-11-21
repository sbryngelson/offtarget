"""A C fuzz program (generator fuzz-6c) in the campaign runner: it is written as a .c file, built with
each toolchain's C compiler, checked by the pre-run check as C, and its elision is the C program's."""
import re
import shutil
from pathlib import Path

import pytest

from offload.engine import fuzz, fuzz_exec


def _c_program():
    return next(p for p in (fuzz.generate(s, "fuzz-6c", ()) for s in range(1, 40))
                if not p.source.startswith(fuzz.UNTRANSLATED))


def test_a_c_program_is_built_as_c(tmp_path, monkeypatch):
    seen = {}

    def compile_program(tc, src, exe, tmp, *a, **k):
        seen["suffix"], seen["lang"] = Path(src).suffix, tc.lang
        return "compile_error", "stub", "", ""

    monkeypatch.setattr(fuzz_exec, "compile_program", compile_program)
    monkeypatch.setattr(fuzz_exec, "_provenance", lambda tc, tmp, cls: {})
    res, exe = fuzz_exec.run_toolchain(_c_program(), fuzz_exec.toolchain_for("afar", "c"), tmp_path)
    assert seen == {"suffix": ".c", "lang": "c"} and exe is None


def test_a_fortran_program_keeps_the_fortran_toolchain():
    assert fuzz_exec.toolchain_for("afar", "f90").lang == "f90"
    assert fuzz_exec.toolchain_for("cce21", "c").lang == "c"


def test_the_prerun_check_reads_a_c_program_as_c(monkeypatch):
    p = _c_program()
    got = {}
    from offload.engine import prerun
    monkeypatch.setattr(fuzz_exec, "check", lambda src, expected=None: fuzz.CheckResult("ok"))
    def prerun_check(prog):
        got["lang"] = prog[1]
        return False, ["stop"]

    monkeypatch.setattr(prerun, "check", prerun_check)
    monkeypatch.setattr(fuzz_exec, "generate", lambda *a, **k: p)
    pr = fuzz_exec.run_program(p.seed, ("afar",), gen_version="fuzz-6c")
    assert got["lang"] == "c" and pr.check == "prerun"


@pytest.mark.skipif(shutil.which("gcc") is None, reason="needs gcc (the C elision)")
def test_the_elision_of_a_c_program_is_its_sequential_c_run():
    p = _c_program()
    assert fuzz_exec.elision_value(p.source) == p.expected


@pytest.mark.skipif(shutil.which("gcc") is None, reason="needs gcc (the C elision)")
def test_the_elision_stubs_every_api_routine_a_c_program_calls():
    """omp_get_thread_num and omp_get_team_num (the guard kernels) have their sequential values."""
    p = next(p for p in (fuzz.generate(s, "fuzz-6c", ()) for s in range(1, 400))
             if "omp_get_thread_num(" in p.source and "omp_get_team_num(" in p.source)
    assert fuzz_exec.elision_value(p.source) == p.expected


def test_an_atomic_max_or_min_is_not_translated():
    """Fortran's atomic update takes max and min (5.2 §15.8.4); C's does not, so such a program
    is refused at translation, not written as a conditional the C front end rejects."""
    p = fuzz.generate(75, "fuzz-6c", ())
    assert p.source.startswith(fuzz.UNTRANSLATED) and "atomic" in p.source
    for s in range(1, 300):
        src = fuzz.generate(s, "fuzz-6c", ()).source
        assert not re.search(r"#pragma omp atomic[^\n]*\n\s*(\w+) = \(\(?\1 [<>]", src), s


def test_a_c_build_is_classified_with_the_c_compilers_messages(tmp_path, monkeypatch):
    """A CCE C compiler crash is an ice (the cce:c table), not an unclassified failure."""
    from offload.engine import harness
    out = "PLEASE submit a bug report to HPE at https://support.hpe.com/ and include the crash backtrace\n"
    monkeypatch.setattr(harness, "_execute", lambda *a, **k: harness._Exec(1, out, ""))
    src = tmp_path / "p.c"
    src.write_text("int main(void) { return 0; }\n")
    cls, reason, _, _ = fuzz_exec.compile_program(fuzz_exec.toolchain_for("cce21", "c"), src, tmp_path / "x", tmp_path)
    assert cls == "ice", (cls, reason)
