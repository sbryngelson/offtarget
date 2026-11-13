"""Tests of the harvest2 sources (AOMP, the OpenMP Examples, libgomp, training and application programs), the holdout rows and the dev/holdout split."""


# ---- AOMP's test suites beyond smoke and smoke-fails -----------------------------------------------

from offload.engine.harvest2 import aomp as A

F_STOP = """! SPDX-License-Identifier:  MIT
program p
  integer :: a(4)
  a = 0
!$omp target map(tofrom: a)
  a = 1
!$omp end target
  if (any(a /= 1)) then
    print *, "======= FORTRAN Test Failed! ======="
    stop 1
  end if
  print *, "======= FORTRAN Test Passed! ======="
end program
"""

F_PRINT_BOTH = F_STOP.replace("    stop 1\n", "")
F_VALUES = """program p
  integer :: a(4)
!$omp target map(from: a)
  a = 1
!$omp end target
  print *, a
  print *, "======= FORTRAN Test Passed! ======="
end program
"""


def test_map_test_oracles():
    r = A.map_test("fortran-map-tests/t.f90", F_STOP, "c" * 40)
    assert r["reasons"] == [] and r["checks"] == ["CHECK: Test Passed"]
    assert r["license"].startswith("MIT")
    r = A.map_test("fortran-map-tests/t.f90", F_PRINT_BOTH, "c" * 40)
    assert r["reasons"] == []
    assert r["checks"] == ["CHECK-NOT: Test Failed", "CHECK: Test Passed"]
    r = A.map_test("fortran-map-tests/t.f90", F_VALUES, "c" * 40)
    assert r["reasons"] == ["no_self_check"]


def test_map_test_conversion():
    r = A.map_test("fortran-map-tests/t-1.f95", F_STOP, "c" * 40)
    p = A.convert_map_test(r, F_STOP)
    assert p["id"] == "h2-aomp-fortran-map-tests-t-1"
    assert p["oracle"] == "filecheck" and p["lang"] == "f90"
    assert "subroutine hv_orig_main" in p["source"]
    assert p["source"].startswith("! Harvested test")


def test_smoke_suites_exclude_the_sanitizer_suite():
    assert "smoke-asan" not in A.SMOKE_SUITES
    assert "smoke-fort" in A.SMOKE_SUITES and "smoke" not in A.SMOKE_SUITES


def test_relabel_49a_program():
    src = "! Harvested test (tools/campaigns/harvest.py convert; do not edit)\n! x\n"
    assert A.relabel(src, "f90").startswith(
        "! Harvested test (tools/campaigns/harvest2.py aomp; do not edit)")


# ---- The OpenMP Examples as harvest programs -------------------------------------------------------------

from offload.engine.harvest2 import examples as E

C_EX = """/*
* @@name:	t.1
* @@type:	C
* @@operation:	run
* @@expect:	success
* @@version:	omp_5.0
*/
#include <stdio.h>
int main()
{
   int s = 0;
   #pragma omp target map(tofrom: s)
   s = 42;
   printf("s = %d\\n", s);   //OUTPUT: s = 42
   return 0;
}
"""

F_EX = """! @@name:	t.1
! @@type:	F-free
! @@operation:	run
! @@expect:	success
! @@version:	omp_5.0
program p
  integer :: s
  s = 0
  !$omp target map(tofrom: s)
  s = 42
  !$omp end target
  if (s /= 42) error stop 1
end program
"""


def test_tags_are_read():
    t = E.tags(C_EX)
    assert t == {"name": "t.1", "type": "C", "operation": "run",
                 "expect": "success", "version": "omp_5.0"}


def test_selection():
    assert E.selected(C_EX)
    assert not E.selected(C_EX.replace("run", "compile"))
    assert not E.selected(C_EX.replace("success", "rt-error"))
    assert not E.selected(C_EX.replace("#pragma omp target map(tofrom: s)",
                                       "#pragma omp parallel"))


def test_c_example_with_documented_output():
    p = E.convert("devices/sources/t.1.c", C_EX,
                  {"checks": ["CHECK: s = 42"]}, commit="a" * 40)
    assert p["oracle"] == "filecheck" and p["checks"] == 1
    assert p["id"] == "h2-ompex-t-1-c"
    assert "hv_orig_main" in p["source"]
    assert "OpenMP Architecture Review Board" in p["source"]
    assert p["modes"] == ["copy", "unified"]
    assert p["version"] == 50


def test_fortran_example_checks_itself():
    p = E.convert("devices/sources/t.1.f90", F_EX,
                  {"oracle": "exit_status", "modes": ["copy"]}, commit="a" * 40)
    assert p["oracle"] == "exit_status" and p["modes"] == ["copy"]
    assert p["id"] == "h2-ompex-t-1-f90"
    assert "subroutine hv_orig_main" in p["source"]


# ---- GCC's libgomp testsuite as harvest programs ---------------------------------------------------------

from offload.engine.harvest2 import gomp as G

C_OMP = """/* { dg-do run } */
/* { dg-additional-options "-O2 -Wno-deprecated-openmp -DN=8" } */
#include <stdlib.h>
int main (void)
{
  int a[N];
  #pragma omp target map(from: a)
  for (int i = 0; i < N; i++) a[i] = i;
  for (int i = 0; i < N; i++) if (a[i] != i) __builtin_abort ();
  return 0;
}
"""

C_ACC = """/* { dg-do run } */
/* { dg-skip-if "" { *-*-* } { "*" } { "-DACC_MEM_SHARED=0" } } */
#include <openacc.h>
#include <stdlib.h>
int main (void)
{
  int x = 1;
#pragma acc parallel copy(x)
  x = 2;
#if ACC_MEM_SHARED
  if (x != 2) abort ();
#else
  if (x != 2) abort ();
#endif
  return 0;
}
"""

F_OMP = """! { dg-do run }
program p
  implicit none
  integer :: x
  x = 0
!$omp target map(tofrom: x)
  x = 1
!$omp end target
  if (x /= 1) call abort
end program p
"""


def rec(text, path="libgomp.c/t.c", **kw):
    return G.record(path, text, commit="0" * 40, **kw)


def test_dg_directives_are_parsed():
    d = G.parse_dg(C_OMP)
    assert d["do"] == ("run", "")
    assert d["options"] == ["-O2", "-Wno-deprecated-openmp", "-DN=8"]
    d = G.parse_dg('/* { dg-do run { target openacc_nvidia_accel_selected } } */\n'
                   '/* { dg-set-target-env-var OMP_NUM_TEAMS "4" } */\n'
                   '/* { dg-shouldfail "x" } */\n'
                   '/* { dg-additional-sources "b.c" } */\n'
                   '/* { dg-require-effective-target omp_usm } */\n'
                   '/* { dg-additional-options "-foffload=-lm" { target offload_target_nvptx } } */\n')
    assert d["do"] == ("run", "openacc_nvidia_accel_selected")
    assert d["env"] == {"OMP_NUM_TEAMS": "4"}
    assert d["shouldfail"] and d["sources"] == ["b.c"]
    assert d["effective"] == ["omp_usm"]
    assert d["target_options"] == [("-foffload=-lm", "offload_target_nvptx")]
    assert d["options"] == []


def test_default_action_is_run():
    assert G.parse_dg("int main(){}\n")["do"] == ("run", "")


def test_a_plain_offload_test_is_kept_in_both_modes():
    r = G.classify(rec(C_OMP), C_OMP)
    assert r["reasons"] == [], r
    assert r["modes"] == ["copy", "unified"]
    assert r["defines"] == ["-DN=8"]


def test_filters_record_reasons():
    def why(text, path="libgomp.c/t.c"):
        return G.classify(rec(text, path), text)["reasons"]
    assert "compile_only" in why(C_OMP.replace("dg-do run", "dg-do compile"))
    assert "expects_failure" in why('/* { dg-shouldfail "" } */\n' + C_OMP)
    assert "target_specific" in why(C_OMP.replace(
        "dg-do run", "dg-do run { target openacc_nvidia_accel_selected }"))
    assert "gcc_flag" in why('/* { dg-additional-options "-fopenacc-dim=32" } */\n'
                             + C_OMP)
    assert "vendor_env" in why(
        '/* { dg-set-target-env-var GOMP_DEBUG "1" } */\n' + C_OMP)
    assert "needs_omp_env" in why(
        '/* { dg-set-target-env-var OMP_NUM_TEAMS "4" } */\n' + C_OMP)
    assert why('/* { dg-set-target-env-var OMP_TARGET_OFFLOAD "mandatory" } */\n'
               + C_OMP) == []
    assert "multi_file" in why('/* { dg-additional-sources "b.c" } */\n' + C_OMP)
    assert "host_only" in why("int main(void){\n#pragma omp parallel\n{}\n}\n")
    assert "cpp" in why(C_OMP, "libgomp.c++/t.C")
    assert "gnu_extension" in why(C_OMP.replace("return 0;",
                                                "asm volatile (\"\");\n return 0;"))
    assert "gnu_extension" in why(C_OMP.replace("return 0;",
                                                "__builtin_alloca (4);\n return 0;"))
    assert "runtime_internals" in why(
        C_ACC.replace("x = 2;", "x = __builtin_goacc_parlevel_id (0);"),
        "libgomp.oacc-c-c++-common/t.c")
    assert "arch_specific" in why(C_ACC.replace("#if ACC_MEM_SHARED",
                                                "#if ACC_DEVICE_TYPE_nvidia"),
                                  "libgomp.oacc-c-c++-common/t.c")
    assert "skipped_upstream" in why('/* { dg-skip-if "" { *-*-* } } */\n' + C_OMP)
    assert "interop" in why('/* { dg-require-effective-target openacc_cuda } */\n'
                            + C_OMP)
    assert "nonspec_routine" in why(C_OMP.replace("return 0;",
                                                  "omp_foo_bar ();\n return 0;"))


def test_memory_modes():
    usm = '/* { dg-require-effective-target omp_usm } */\n' + C_OMP
    assert G.classify(rec(usm), usm)["modes"] == ["unified"]
    nsh = '/* { dg-require-effective-target offload_device_nonshared_as } */\n' + C_OMP
    assert G.classify(rec(nsh), nsh)["modes"] == ["copy"]
    r = G.classify(rec(C_ACC, "libgomp.oacc-c-c++-common/t.c"), C_ACC)
    assert r["reasons"] == [] and r["modes"] == ["copy"]
    assert "-DACC_MEM_SHARED=0" in r["defines"]


def test_local_includes_are_inlined(tmp_path):
    d = tmp_path / "libgomp.c"
    d.mkdir()
    (tmp_path / "libgomp.c-c++-common").mkdir()
    (tmp_path / "libgomp.c-c++-common" / "inc.c").write_text("int helper = 3;\n")
    (d / "h.h").write_text('#include "../libgomp.c-c++-common/inc.c"\n')
    text = '#include <stdio.h>\n#include "h.h"\nint main(void){return 0;}\n'
    out, incs = G.inline_includes(text, d / "t.c")
    assert "int helper = 3;" in out and "#include <stdio.h>" in out
    assert incs == ["libgomp.c/h.h", "libgomp.c-c++-common/inc.c"]
    out, incs = G.inline_includes("include 'm.f90'\nend\n", d / "t.f90")
    assert incs == [None]
    out, incs = G.inline_includes('#ifdef P\n#include "papi.h"\n#endif\n', d / "t.c",
                                  skip=("papi.h",))
    assert incs == [] and '#include "papi.h"' in out


def test_gnu_builtins_are_rewritten():
    out, edits = G.rewrite_builtins(C_OMP.replace("return 0;",
                                                  "__builtin_printf (\"x\");\n return 0;"), "c")
    assert "__builtin_" not in out
    assert "abort ()" in out and "printf (" in out
    assert out.index("#include <stdio.h>") < out.index("int main")
    assert edits
    out, edits = G.rewrite_builtins(
        "static int __attribute__((noinline, noclone)) f (void) { return 1; }\n"
        "__attribute__ ((noipa)) int g (void) { return 2; }\n"
        "__attribute__((aligned (8))) int h;\n", "c")
    assert out.count("__attribute__") == 1 and "aligned" in out
    assert "static int f (void)" in out and "int g (void)" in out
    out, edits = G.rewrite_builtins(F_OMP, "f90")
    assert "call abort" not in out and "error stop" in out


def test_c_conversion_is_self_checking():
    r = rec(C_OMP)
    p = G.convert(r, C_OMP)
    assert p["lang"] == "c" and p["model"] == "omp"
    assert "hv_orig_main" in p["source"] and "RESULT ran_on_host" in p["source"]
    assert "#define N 8" in p["source"]
    assert "__builtin_abort ()" not in p["source"]
    assert p["oracle"] == "exit_status"
    assert "license: GPL-3.0-or-later" in p["source"]
    assert p["id"] == "h2-gomp-c-t"


def test_acc_conversion_uses_an_openacc_host_probe():
    r = rec(C_ACC, "libgomp.oacc-c-c++-common/t.c")
    p = G.convert(r, C_ACC)
    assert p["model"] == "acc"
    assert "#pragma omp" not in p["source"] and "<omp.h>" not in p["source"]
    assert "#pragma acc serial copyout(h)" in p["source"]
    assert "#define ACC_MEM_SHARED 0" in p["source"]
    assert p["id"] == "h2-gomp-acc-ccc-t"
    fa = F_OMP.replace("!$omp target map(tofrom: x)", "!$acc parallel copy(x)").replace(
        "!$omp end target", "!$acc end parallel")
    p = G.convert(rec(fa, "libgomp.oacc-fortran/t.f90"), fa)
    assert "use omp_lib" not in p["source"].lower()
    assert "!$omp" not in p["source"].lower()
    assert "!$acc serial copyout(h)" in p["source"]


def test_fortran_conversion():
    p = G.convert(rec(F_OMP, "libgomp.fortran/t.f90"), F_OMP)
    assert "subroutine hv_orig_main" in p["source"]
    assert "error stop" in p["source"] and "call abort" not in p["source"]


def test_simple_dg_output_becomes_check_lines():
    t = C_OMP.replace("return 0;", 'printf ("The answer is 42\\n");\n return 0;') + \
        '/* { dg-output "The answer is 42(\\n|\\r\\n|\\r)+" } */\n'
    r = rec(t)
    c = G.classify(r, t)
    assert c["reasons"] == [] and c["checks"] == ["CHECK: The answer is 42"]
    p = G.convert(r, t)
    assert p["oracle"] == "filecheck"
    t2 = C_OMP + '/* { dg-output "a.*\\[0-9\\]+" } */\n'
    assert "dg_output_regex" in G.classify(rec(t2), t2)["reasons"]


# ---- Training, example and application programs made -----------------------------------------------------

import pytest

from offload.engine.harvest2 import hand as H

C_SAXPY = """#include <stdio.h>
int main(void) {
  int n = 8; float y[8];
  #pragma omp target teams distribute parallel for map(from: y)
  for (int i = 0; i < n; i++) y[i] = 2.0f * i;
  printf("y[0] %f\\n", y[0]);
}
"""

F_ACC = """program p
  real :: y(8)
  integer :: i
  !$acc parallel loop copyout(y)
  do i = 1, 8
    y(i) = 2.0 * i
  end do
  print *, y(1)
end program
"""


def entry(**kw):
    e = {"id": "h2-x-saxpy", "repo": "o/r", "commit": "b" * 40,
         "path": "src/saxpy.c", "license": "MIT",
         "url": "https://github.com/o/r/blob/bbbbbbbbbbbb/src/saxpy.c",
         "why": "y(i) = 2i, recomputed on the host"}
    e.update(kw)
    return e


def test_edits_apply_exactly_once():
    out, notes = H.apply_edits(C_SAXPY, [
        {"old": '  printf("y[0] %f\\n", y[0]);\n',
         "new": '  printf("y[0] %f\\n", y[0]);\n'
                '  for (int i = 0; i < n; i++) if (y[i] != 2.0f * i) return 1;\n',
         "why": "a host check of every y(i)"}])
    assert "return 1;" in out and notes == ["a host check of every y(i)"]
    with pytest.raises(H.EditError):
        H.apply_edits(C_SAXPY, [{"old": "not there", "new": "x", "why": "w"}])
    with pytest.raises(H.EditError):
        H.apply_edits("a a", [{"old": "a", "new": "b", "why": "w"}])
    out, _ = H.apply_edits("a a", [{"old": "a", "new": "b", "why": "w", "count": 2}])
    assert out == "b b"


def test_c_program_with_exit_status_oracle():
    e = entry(edits=[{"old": "}\n", "new": "  return y[3] == 6.0f ? 0 : 1;\n}\n",
                      "why": "y(3) checked"}])
    p = H.convert(e, C_SAXPY)
    assert p["id"] == "h2-x-saxpy" and p["lang"] == "c" and p["model"] == "omp"
    assert p["oracle"] == "exit_status"
    assert "hv_orig_main" in p["source"]
    assert "edits: y(3) checked" in p["source"].replace("\n * ", " ")
    assert p["gpl"] is False and p["source_kind"] == "training"
    assert p["copyleft"] is False
    q = H.convert({**e, "license": "CC-BY-SA-4.0"}, C_SAXPY)
    assert q["copyleft"] is True and q["gpl"] is False


def test_acc_fortran_program_with_checks():
    e = entry(id="h2-x-acc", path="src/p.f90", checks=["CHECK: 2."],
              url="https://github.com/o/r/blob/bbbbbbbbbbbb/src/p.f90")
    p = H.convert(e, F_ACC)
    assert p["model"] == "acc" and p["oracle"] == "filecheck"
    assert "!$acc serial copyout(h)" in p["source"]
    assert "use omp_lib" not in p["source"]


def test_an_entry_needs_a_self_check():
    with pytest.raises(H.EditError):
        H.convert(entry(), C_SAXPY)


def test_other_files_are_appended():
    e = entry(append=["src/compute.c"], self_checking=True)
    p = H.convert(e, C_SAXPY, {"src/compute.c": "int helper(void) { return 1; }\n"})
    assert "/* Appended src/compute.c */" in p["source"]
    assert "int helper(void)" in p["source"]
    assert "the example's other files appended: src/compute.c" in p["edits"]


def test_modules_are_put_first():
    e = entry(path="src/p.f90", prepend=["src/m.f90"], self_checking=True,
              url="https://github.com/o/r/blob/bbbbbbbbbbbb/src/p.f90")
    p = H.convert(e, F_ACC, {"src/m.f90": "module m\nend module m\n"})
    assert p["source"].index("\nmodule m") < p["source"].index("\nsubroutine hv_orig_main")


def test_tabs_are_expanded_when_asked():
    e = entry(path="src/p.f90", detab=True, self_checking=True,
              url="https://github.com/o/r/blob/bbbbbbbbbbbb/src/p.f90")
    p = H.convert(e, F_ACC.replace("  real :: y(8)", "\treal :: y(8)"))
    assert "\t" not in p["source"]
    assert p["edits"][0].startswith("tabs replaced by spaces")


def test_local_includes_are_inlined_when_asked(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "t.h").write_text("int helper(void);\n")
    text = '#include "t.h"\n' + C_SAXPY
    e = entry(inline=True, self_checking=True)
    p = H.convert(e, text, None, tmp_path)
    assert "int helper(void);" in p["source"] and '#include "t.h"' not in p["source"]
    assert any(n.startswith("local includes inlined") for n in p["edits"])


# ---- The holdout's outcomes.csv rows (tools/campaigns/harvest.py) -----------------------------------------

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
import harvest as HV  # noqa: E402

TARGETS = {"tuolumne": (["afar", "cce21"], [0]),
           "tioga": (["cce21_g90"], [0])}
CASES = [
    {"id": "h2-x-omp", "lang": "c", "model": "omp", "modes": ["copy"],
     "case": "harvest2-holdout-001"},
    {"id": "h2-x-acc", "lang": "c", "model": "acc", "modes": ["copy"],
     "case": "harvest2-holdout-002"},
    {"id": "h2-x-ref", "lang": "f90", "model": "omp", "modes": ["copy"],
     "case": "harvest2-holdout-003"},
]


def _fake(monkeypatch, rows):
    monkeypatch.setattr(HV, "TARGETS", TARGETS)
    monkeypatch.setattr(HV, "holdout_cases", lambda: CASES)
    monkeypatch.setattr(HV, "rows", lambda name, applicable=True: rows)
    monkeypatch.setattr(HV, "prerun_rows", lambda: {
        "h2-x-omp": {"ok": True}, "h2-x-acc": {"ok": True},
        "h2-x-ref": {"ok": False}})
    monkeypatch.setattr(HV, "KIND", "harvest2")
    monkeypatch.setattr(HV, "verdicts", lambda name: {
        "harvest2|h2-x-omp|cce21|0": {"verdict": "confirmed"}})


def _row(pid, tc, outcome, reason=""):
    return {"program_id": pid, "toolchain": tc, "xnack": 0,
            "outcome": outcome, "reason": reason, "stdout": "", "stderr": ""}


ROWS = [_row("h2-x-omp", "afar", "correct_on_device"),
        _row("h2-x-omp", "cce21", "wrong_answer", "check_fail: x"),
        _row("h2-x-acc", "cce21", "correct_on_device")]


def test_holdout_outcomes_classes(monkeypatch):
    _fake(monkeypatch, ROWS)
    out = {(r[0], r[1]): r[3:] for r in HV.holdout_outcomes("main")}
    assert out[("harvest2-holdout-001", "afar")] == ["correct_on_device", ""]
    assert out[("harvest2-holdout-001", "cce21")][1] == "confirmed"
    # OpenACC C: AFAR and CCE compile no such program (model_supported)
    assert out[("harvest2-holdout-002", "afar")] == ["not_applicable", ""]
    assert out[("harvest2-holdout-002", "cce21")] == ["not_applicable", ""]
    assert out[("harvest2-holdout-003", "afar")] == ["refused", ""]
    # no row on Tioga: not run
    assert out[("harvest2-holdout-001", "cce21_g90")] == ["not_run", ""]


def _seal_dir(tmp_path, monkeypatch, seal_text=None):
    d = tmp_path / "harvest2-holdout"
    d.mkdir()
    for c in CASES:
        (d / (c["case"] + (".c" if c["lang"] == "c" else ".f90"))).write_text("x\n")
    (d / "cases.yaml").write_text("cases: []\n")
    if seal_text is not None:
        (d / "SEAL").write_text(seal_text)
    monkeypatch.setattr(HV, "HOLDOUT", d)
    monkeypatch.setattr(HV, "CASE_PREFIX", "harvest2-holdout-")
    return d


def _seal(allow=()):
    return HV.cmd_seal(argparse.Namespace(name="main", commit="abc1234",
                                          allow_missing_machine=list(allow)))


def test_seal_refuses_a_missing_cell_off_the_named_machine(tmp_path, monkeypatch):
    _fake(monkeypatch, ROWS[:1])         # cce21 on Tuolumne not run either
    d = _seal_dir(tmp_path, monkeypatch, "# Seal\ncases: 3\n")
    assert _seal() == 2
    assert _seal(["tioga"]) == 2         # the Tuolumne cell is not excused
    assert not (d / "outcomes.csv").exists()


def test_seal_completes_a_split_time_seal_once(tmp_path, monkeypatch):
    _fake(monkeypatch, ROWS)
    d = _seal_dir(tmp_path, monkeypatch, "# Seal\ncases: 3\n")
    assert _seal() == 2                  # Tioga not run, not allowed
    assert _seal(["tioga"]) == 0
    text = (d / "SEAL").read_text()
    assert "outcomes_sha256:" in text and "commit: abc1234" in text
    assert "harvest2-holdout-001,cce21_g90,copy,not_run," in (d / "outcomes.csv").read_text()
    assert _seal(["tioga"]) == 1         # sealed already


def test_unknown_machine_is_refused(tmp_path, monkeypatch):
    _fake(monkeypatch, ROWS)
    _seal_dir(tmp_path, monkeypatch)
    with pytest.raises(SystemExit):
        _seal(["nowhere"])


# --- Environment (c) on another node than (a) ------------------------

def test_c_on_another_node_picks_rows_whose_c_shared_the_a_node():
    items = [{"cell": "k|p1|cce21|0"}, {"cell": "k|p2|cce21|0"},
             {"cell": "k|p3|cce21|0"}, {"cell": "k|p4|cce21|0"}]
    reruns = [
        # p1: (c) ran on (a)'s node: no node change, needs a (c) elsewhere
        {"cell": "k|p1|cce21|0", "env": "a", "node": "n1"},
        {"cell": "k|p1|cce21|0", "env": "c", "node": "n1"},
        # p2: (c) already on another node
        {"cell": "k|p2|cce21|0", "env": "a", "node": "n1"},
        {"cell": "k|p2|cce21|0", "env": "c", "node": "n2"},
        # p3: (a) ran on this node: (c) cannot run here
        {"cell": "k|p3|cce21|0", "env": "a", "node": "here"},
        {"cell": "k|p3|cce21|0", "env": "c", "node": "here"},
        # p4: no (a) yet: not this step's business
    ]
    assert HV.c_other_node_items(items, reruns, "here") == [items[0]]


# ---- The dev/holdout split of the harvest2 programs ------------------------------------------------------

from offload.engine.harvest import convert as HC
from offload.engine.harvest2 import split as S


def prog(pid, source, lang="c", copyleft=False):
    return {"id": pid, "lang": lang, "source": source, "copyleft": copyleft,
            "sha256": HC.hashlib.sha256(source.encode()).hexdigest()}


def test_holdout_is_the_lowest_30_percent_of_the_code_hash_space():
    progs = [prog(f"h2-x-{k}", f"int main(void) {{ return {k}; }}\n")
             for k in range(200)]
    plan = S.plan(progs)
    hold = [p for p in plan if p["set"] == "holdout"]
    assert all(HC.holdout_by_code(p["source"], p["lang"]) == (p["set"] == "holdout")
               for p in plan)
    assert 0.2 < len(hold) / len(plan) < 0.4


def test_names_and_directories():
    a = prog("h2-a", "int main(void) { return 0; }\n")
    b = prog("h2-b", "program p\nend program p\n", lang="f90", copyleft=True)
    plan = {p["id"]: p for p in S.plan([a, b])}
    for p in plan.values():
        if p["set"] == "dev":
            assert p["path"] == ("copyleft/" if p["copyleft"] else "") + \
                p["id"] + (".c" if p["lang"] == "c" else ".f90")
        else:
            assert p["path"].endswith(".c" if p["lang"] == "c" else ".f90")
            assert "harvest2-holdout-" in p["path"]
            assert p["path"].startswith("copyleft/") == p["copyleft"]


def test_holdout_numbers_follow_program_ids():
    progs = [prog(f"h2-{k:03d}", f"int main(void) {{ return {k}; }} /* {k} */\n")
             for k in range(60)]
    hold = [p for p in S.plan(progs) if p["set"] == "holdout"]
    ids = [p["id"] for p in hold]
    assert ids == sorted(ids)
    assert [p["case"] for p in hold] == [f"harvest2-holdout-{k:03d}"
                                         for k in range(1, len(hold) + 1)]


def test_seal_text_names_the_set_and_digests(tmp_path):
    (tmp_path / "harvest2-holdout-001.c").write_text("x")
    (tmp_path / "cases.yaml").write_text("cases: []\n")
    text = S.seal_text("abc1234", [tmp_path / "harvest2-holdout-001.c"],
                       tmp_path / "cases.yaml")
    assert text.startswith("# Seal of bench/harvest2-holdout")
    assert "commit: abc1234" in text and "cases: 1" in text
    assert "sha256: " in text and "cases_yaml_sha256: " in text


def test_programs_differing_only_in_comments_fall_on_one_side():
    progs = []
    for k in range(40):
        code = f"int main(void) {{ return {k}; }}\n"
        progs.append(prog(f"h2-a-{k}", "/* header A */\n" + code))
        progs.append(prog(f"h2-b-{k}", "/* another header */\n// note\n" + code))
    sets = {p["id"]: p["set"] for p in S.plan(progs)}
    assert all(sets[f"h2-a-{k}"] == sets[f"h2-b-{k}"] for k in range(40))


def test_dev_cases_name_no_holdout_program():
    a = prog("h2-a", "int main(void) { return 1; }\n")
    rows = S.plan([a] + [prog(f"h2-z{k}", f"int main(void) {{ return {k + 2}; }}\n")
                         for k in range(30)])
    hold = [p["id"] for p in rows if p["set"] == "holdout"]
    dev = [p for p in rows if p["set"] == "dev"]
    assert hold and dev
    dev[0]["similar"] = [{"set": "harvest2", "id": hold[0], "jaccard": 0.9},
                         {"set": "harvest2", "id": dev[-1]["id"], "jaccard": 0.7}]
    sim = S.dev_similar(rows)[dev[0]["id"]]
    assert [x["id"] for x in sim] == [dev[-1]["id"]]


# ---- The conversion tables count only the dev programs ------------------------

import json

import harvest2 as H2  # noqa: E402


def _w(p, rows):
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_tables_count_dev_programs_only(tmp_path, monkeypatch):
    monkeypatch.setattr(H2, "OUT", tmp_path)
    ids = [f"h2-gomp-c-t{k}" for k in range(5)] + ["h2-amd-c-a", "h2-amd-c-b"]
    _w(tmp_path / "split.jsonl", [{"id": i, "set": "dev" if k < 3 or i == "h2-amd-c-a"
                                   else "holdout"} for k, i in enumerate(ids)])
    _w(tmp_path / "programs.jsonl", [{"id": i, "lang": "c", "model": "omp"} for i in ids])
    _w(tmp_path / "rules.jsonl", [{"id": i, "kind": "pass"} for i in ids])
    _w(tmp_path / "gomp.jsonl", [{"id": i, "reasons": [], "program": i} for i in ids[:5]]
       + [{"id": "x", "reasons": ["host_only: no target"]}])
    for f in ("aomp.jsonl", "examples.jsonl"):
        _w(tmp_path / f, [])
    _w(tmp_path / "hand.jsonl", [{"id": i, "program": i, "reasons": [],
                                  "repo": "amd/HPCTrainingExamples"} for i in ids[5:]])
    text = "\n".join(H2.table_lines())
    assert "Funnel" not in text and "| read |" not in text
    hand = [ln for ln in text.splitlines() if ln.startswith("| amd/HPCTrainingExamples")]
    assert hand and len(hand[0].split("|")) == 5, hand   # repository, license, skips only
    langs = [ln for ln in text.splitlines() if ln.startswith("| C | OpenMP")]
    assert langs[0].split("|")[3].strip() == "4", langs        # 3 gomp + 1 hand dev
