"""Tests of the harvests: FileCheck lines, harvested programs as self-checking tests, the filters and the inventory, a finding's reproducer, and tools/campaigns/harvest.py."""


# ---- FileCheck lines of harvested tests (offload.engine.harvest.checks) ---------------------------------

import pytest

from offload.engine.harvest import checks as K


C_TEST = """\
// RUN: %libomptarget-compile-run-and-check-generic
int main() {
  // CHECK: Result: 10
  // CHECK-NEXT: done
  // CHECK-NOT: error
  // CHECK-SAME: x
  // OTHER: not mine
  // CHECK-LABEL: tail
  // CHECK-COUNT-2: rep
  return 0;
}
"""


def test_parse_kinds_prefixes_and_expansion():
    cs = K.parse_checks(C_TEST)
    assert [(c.kind, c.pattern) for c in cs] == [
        ("CHECK", "Result: 10"), ("NEXT", "done"), ("NOT", "error"),
        ("SAME", "x"), ("CHECK", "tail"), ("CHECK", "rep"),
        ("CHECK", "rep")]
    other = K.parse_checks(C_TEST, ("OTHER",))
    assert [(c.kind, c.pattern) for c in other] == [("CHECK", "not mine")]
    both = K.parse_checks(C_TEST, ("OTHER", "CHECK"))
    assert len(both) == 8 and both[3].pattern == "x"


def test_fortran_comment_checks():
    text = "program p\n  print *, 1\nend program\n! CHECK: 1\n!CHECK-NEXT: 2.\n"
    cs = K.parse_checks(text)
    assert [(c.kind, c.pattern) for c in cs] == [("CHECK", "1"),
                                                 ("NEXT", "2.")]


def test_prefix_needs_a_boundary():
    # MYCHECK: is another prefix, not CHECK
    assert K.parse_checks("// MYCHECK: a\n// XCHECK-NEXT: b\n") == []


def test_tokens():
    toks = [t.text for t in K.tokenize("a[0] = 30.299999237060547, x_1 T")]
    assert toks == ["a", "[", "0", "]", "=", "30.299999237060547", ",",
                    "x_1", "T"]
    toks = [t.text for t in K.tokenize("1.0D+00 -2 .5e-3")]
    assert toks == ["1.0D+00", "-", "2", ".5e-3"]


def test_numeric_equality():
    eq = K.token_equal
    assert eq("40.", "40.00000")
    assert eq("30.299999237060547", "30.2999992")
    assert eq("1", "1.0")
    assert not eq("2", "20")
    assert not eq("10", "11")
    assert not eq("30.3", "30.4")
    assert eq("1.0D+00", "1.")


def test_compile_modes_and_unsupported():
    p = K.compile_pattern("x = {{.*}} done")
    assert p.mode == "tokens" and p.segments == ["x =", "done"]
    p = K.compile_pattern("addr {{0[xX][0-9a-fA-F]+}} end")
    assert p.mode == "regex"
    assert p.regex == "addr (0[xX][0-9a-fA-F]+) end"
    p = K.compile_pattern("a.b [[V:[0-9]+]] c")
    assert p.mode == "regex" and p.defs == [("V", 1)]
    assert p.regex == r"a\.b ([0-9]+) c"
    with pytest.raises(K.Unsupported):
        K.compile_pattern("[[#%x,ADDR:]]")
    with pytest.raises(K.Unsupported):
        K.compile_pattern("line [[@LINE]]")
    q = K.compile_pattern("use [[V]] here")
    assert q.uses == ["V"] and "\x01V\x01" in q.regex
    with pytest.raises(K.Unsupported):
        K.compile_pattern("{{[0-9]+}} x", lang="f90")


def _m(checks_text, out, lang="c"):
    return K.match(K.parse_checks(checks_text), out, lang)[0]


def test_match_basic_order_next_same():
    chk = "// CHECK: a 1\n// CHECK-NEXT: b\n// CHECK-SAME: c\n"
    assert _m(chk, "zz\n a  1 \nb q c\n")
    assert not _m(chk, "a 1\nzz\nb c\n")       # NEXT not on next line
    assert not _m(chk, "b c\na 1\n")           # order
    assert not _m(chk, "a 1\nc b\n")           # SAME after the match


def test_match_numeric_formats_fortran():
    chk = "! CHECK: 2. 4. 6.\n! CHECK: 30.299999237060547\n"
    assert _m(chk, "   2.000000       4.000000       6.000000\n 30.29999924\n",
              "f90")
    assert not _m(chk, " 2. 4. 7.\n 30.3\n", "f90")


def test_match_word_boundaries_like_substrings():
    assert _m("// CHECK: PASS\n", "Test PASSED\n")
    assert _m("// CHECK: Success: x\n", "Success: x=1\n")
    assert not _m("// CHECK: Succ ess\n", "Success\n")


def test_match_not_and_dag_and_empty():
    chk = "// CHECK: begin\n// CHECK-NOT: error\n// CHECK: end\n"
    assert _m(chk, "begin\nok\nend\n")
    assert not _m(chk, "begin\nerror 1\nend\n")
    assert not _m("// CHECK: x\n// CHECK-NOT: bad\n", "x\nbad\n")
    dag = "// CHECK-DAG: two\n// CHECK-DAG: one\n// CHECK: three\n"
    assert _m(dag, "one\ntwo\nthree\n")
    assert not _m(dag, "one\nthree\n")
    assert _m("// CHECK: a\n// CHECK-EMPTY:\n// CHECK-NEXT: b\n", "a\n\nb\n")
    assert not _m("// CHECK: a\n// CHECK-EMPTY:\n", "a\nb\n")


def test_match_regex_and_variables():
    chk = ("// CHECK: ptr = [[P:0x[0-9a-f]+]]\n"
           "// CHECK: again [[P]]\n")
    assert _m(chk, "ptr = 0xab12\nagain 0xab12\n")
    assert not _m(chk, "ptr = 0xab12\nagain 0xab13\n")
    assert _m("// CHECK: n={{[0-9]+}}{{$}}\n", "n=42\n")
    assert not _m("// CHECK: n={{[0-9]+}}{{$}}\n", "n=42x\n")


def test_no_checks_matches_anything():
    assert K.match([], "whatever\n", "c")[0]


def test_fortran_stream_ignores_commas_and_records():
    chk = "! CHECK: 1 2 3 4 5 6\n! CHECK-NEXT: done\n"
    assert _m(chk, " 1, 2, 3,\n 4, 5, 6\n done\n", "f90")
    assert _m(chk, " 1 2 3 4 5 6 7\n\n done\n", "f90")
    assert not _m(chk, " 1 2 3 4 5 7\n done\n", "f90")
    assert not _m("! CHECK: a\n! CHECK-NOT: bad\n! CHECK: z\n",
                  "a\nbad\nz\n", "f90")
    assert _m("! CHECK: (2.,10.)\n", " (2.000000,10.00000)\n", "f90")
    assert _m("! CHECK: x\n! CHECK-EMPTY:\n", "x\ny\n", "f90")


def test_fortran_repeat_counts():
    chk = "! CHECK: 0 2 3 4 5 0 0 0 0 0\n! CHECK: 42. 42. 42.\n"
    assert _m(chk, "  0,  2,  3,  4,  5,  5*0\n  3*42.\n", "f90")
    assert not _m(chk, "  0,  2,  3,  4,  5,  4*0\n 3*42.\n", "f90")
    # a product in the text is not a repeat count (blanks around *)
    assert not _m("! CHECK: 2 2 2\n", " 3 * 2\n", "f90")


# ---- Harvested tests as self-checking programs -----------------------------------------------------------


from offload.engine.harvest import convert as C
from offload.engine.harvest import inventory as I

C_TEST_2 = """\
// RUN: %libomptarget-compile-run-and-check-generic
#include <omp.h>
#include <stdio.h>
int main(int argc, char **argv) {
  int x = 0;
  printf("in main() now\\n"); /* main( in a comment */
#pragma omp target map(tofrom: x)
  x = 1;
  printf("x = %d\\n", x);
  // CHECK: x = 1
  return 0;
}
"""

F_TEST = """\
! RUN: %libomptarget-compile-fortran-run-and-check-generic
module m
contains
  subroutine s(a)
    integer :: a
    a = 1
  end subroutine
end module
program main
  use m
  implicit none
  integer :: x
  x = 0
!$omp target map(tofrom: x)
  x = 2
!$omp end target
  call inner()
  print *, x
contains
  subroutine inner()
  end subroutine
end program main
! CHECK: 2
"""


def test_rename_main_outside_strings_and_comments():
    out, kind = C.rename_main(C_TEST_2)
    assert kind == 1
    assert "int hv_orig_main(int argc, char **argv)" in out
    assert '"in main() now\\n"' in out and "main( in a comment" in out
    _, k0 = C.rename_main("int main(void) { return 0; }")
    _, k2 = C.rename_main("void main() { }")
    assert (k0, k2) == (0, 2)
    with pytest.raises(C.ConvertError):
        C.rename_main("int f(void) { return 0; }")


def test_convert_c():
    r = I.llvm_record("offloading/a.c", C_TEST_2)
    p = C.convert(r | {"commit": "0" * 40, "history": {}}, 0,
                  r["variants"][0], C_TEST_2, 1)
    assert p.id == "hv-llvm-offloading-a" and p.lang == "c"
    assert p.oracle == "filecheck" and p.checks == 1
    assert p.source.startswith("#define _DEFAULT_SOURCE 1\n/*")
    assert "rc = hv_orig_main(argc, argv);" in p.source
    assert 'static const char *const hv_pat[] = {\n  "x =\\0021"' not in \
        p.source
    assert 'static const int hv_n = 1;' in p.source
    assert "RESULT ran_on_host=%d check=%s" in p.source
    assert p.version == 50 and p.modes == ("copy", "unified")
    hp = p.harness()
    assert hp.id == p.id and hp.lang == "c" and hp.needs == ()


def test_c_args_and_defines():
    v = {"flags": ["-DN=4", "-UX", "-O3"], "prefixes": [], "args": ["7"],
         "stderr": True}
    src, edits = C.convert_c(C_TEST_2, [], v)
    assert "#define N 4\n#undef X\n" in src
    assert 'char *hv_av[] = {argv[0], "7", 0};' in src
    assert "static const int hv_merge = 1;" in src
    assert "static const int hv_n = 0;" in src


def test_fortran_main_as_subroutine_with_save():
    r = I.llvm_record("offloading/fortran/b.f90", F_TEST)
    p = C.convert(r | {"commit": "0" * 40, "history": {}}, 0,
                  r["variants"][0], F_TEST, 1)
    lines = p.source.splitlines()
    k = lines.index("subroutine hv_orig_main")
    assert lines[k + 1].strip() == "use m"
    assert lines[k + 2].strip() == "implicit none"
    assert lines[k + 3] == "save"
    assert "end subroutine hv_orig_main" in lines
    # the contained subroutine's end and the module's end are untouched
    assert "  end subroutine" in lines and "end module" in lines
    assert "program hv_main" in p.source
    assert "    hv_pat(1) = '2'" in p.source
    assert p.version == 52


def test_fortran_save_kept_when_the_program_saves():
    t = F_TEST.replace("integer :: x", "integer, save :: x")
    r = I.llvm_record("offloading/fortran/b.f90", t)
    p = C.convert(r | {"commit": "0" * 40, "history": {}}, 0,
                  r["variants"][0], t, 1)
    assert "\nsave\n" not in p.source


def test_fortran_no_program_statement():
    with pytest.raises(C.ConvertError):
        C.main_program_span(["integer :: x", "x = 1", "end"])


def test_preprocess():
    t = ("#define N 10\n#ifdef USE_GPU\nx = N\n#else\nx = 0\n#endif\n"
         "#if defined(A) && N > 5\ny = 1\n#endif\nprint *, 'N'\n")
    out, changed = C.preprocess(t, ["-DUSE_GPU"])
    assert changed
    assert out.split("\n")[2] == "x = 10" and "x = 0" not in out
    assert "y = 1" not in out and "print *, 'N'" in out
    out, _ = C.preprocess(t, ["-DA"])
    assert "y = 1" in out and "x = 0" in out
    with pytest.raises(C.ConvertError):
        C.preprocess("#define F(x) x\n", [])
    with pytest.raises(C.ConvertError):
        C.preprocess('#include "a.h"\n', [])
    assert C.preprocess("x = 1\n", []) == ("x = 1\n", False)


def test_spec_version_from_the_grammar():
    t = "int main(){\n#pragma omp target teams loop\nfor(;;);}\n"
    v, errs = C.spec_version(t, "c", [])
    assert v == 50 and not errs
    v, _ = C.spec_version(t, "c", ["-fopenmp-version=51"])
    assert v == 52
    t60 = "int main(){\n#pragma omp target map(to: x) depend(inoutset: x)\n}\n"
    v, _ = C.spec_version(t60, "c", [])
    assert v >= 52


def test_f_str_quotes_and_controls():
    s = C._f_str("it's" + "\002" + "x" * 70)
    assert "'it''s'" in s and "achar(2)" in s and "&\n" in s


def test_holdout_is_the_lowest_30_percent():
    texts = [f"program {i}" for i in range(2000)]
    n = sum(C.holdout(t) for t in texts)
    assert 520 < n < 680
    assert C.holdout(texts[0]) == C.holdout(texts[0])
    # sha256 as a fraction of 2**256: "program 0" 0.016, "program 7" 0.125,
    # "program 6" 0.331 (just above the cut), "program 1" 0.578
    assert C.holdout("program 0") and C.holdout("program 7")
    assert not C.holdout("program 6") and not C.holdout("program 1")


def test_program_ids():
    assert C.program_id("aomp/smoke/flang-288446", 0, 1) == \
        "hv-aomp-smoke-flang-288446"
    assert C.program_id("llvm/offloading/fortran/x_y.f90", 1, 2) == \
        "hv-llvm-offloading-fortran-x-y-v2"


def test_pattern_data_modes():
    cs = K.parse_checks("// CHECK: a {{.*}} b\n// CHECK-NOT: c [[V:x+]]\n"
                        "// CHECK-EMPTY:\n")
    rows = C._pattern_data(cs, "c")
    assert rows[0] == (0, 0, "a\002b", "")
    assert rows[1][:2] == (3, 1) and rows[1][3] == "V=1"
    assert rows[2] == (5, 0, "", "")


def test_fortran_requires_copied_to_the_self_check():
    t = F_TEST.replace("  implicit none\n", "  implicit none\n"
                       "!$omp requires unified_shared_memory\n", 1)
    r = I.llvm_record("offloading/fortran/b.f90", t)
    p = C.convert(r | {"commit": "0" * 40, "history": {}}, 0,
                  r["variants"][0], t, 1)
    k = p.source.index("module hv_selfcheck")
    assert "!$omp requires unified_shared_memory" in p.source[k:k + 300]
    assert p.modes == ("unified",)


def test_fortran_self_check_passes_the_restriction_checks():
    from offload.engine import prerun
    r = I.llvm_record("offloading/fortran/b.f90", F_TEST.replace(
        "!$omp target map(tofrom: x)", "!$omp target map(tofrom: x)"))
    p = C.convert(r | {"commit": "0" * 40, "history": {}}, 0,
                  r["variants"][0], F_TEST, 1)
    assert prerun.extra(p.source, "f90") == []


def test_main_falling_off_its_end_returns_zero():
    t = 'int main() {\n  int x = 1;\n  { x++; }\n  printf("}");\n}\n'
    out, kind = C.rename_main(t)
    got, added = C.implicit_return(out)
    assert added and got.rstrip().endswith(
        "return 0; /* Main's implicit return */\n}")
    t2 = "int main() {\n  if (1) { return 1; }\n  return 0;\n}\n"
    assert C.implicit_return(C.rename_main(t2)[0]) == \
        (C.rename_main(t2)[0], False)


# --- Variants and twins by program code ---------------

def test_code_key_ignores_comments_header_and_blanks():
    a = "/* header v1 */\nint main(){\n  return 0; // x\n}\n"
    b = "/* header variant 2: flags -O3 */\nint main(){\n    return 0;\n}\n"
    assert C.code_key(a, "c") == C.code_key(b, "c")
    assert C.code_key(a, "c") != C.code_key(a.replace("0;", "1;"), "c")
    f1 = "! variant 1\nprogram p\n!$omp target\n x = 1 ! set\n!$omp end target\nend\n"
    f2 = "! variant 2: flags -O3\nprogram p\n!$omp target\n x = 1\n!$omp end target\nend\n"
    assert C.code_key(f1, "f90") == C.code_key(f2, "f90")
    # a directive is code, not a comment
    f3 = f2.replace("!$omp target\n", "!$omp target map(tofrom: x)\n")
    assert C.code_key(f3, "f90") != C.code_key(f2, "f90")


def test_holdout_split_is_by_code():
    a = "/* from the smoke suite */\nint main(){return 0;}\n"
    b = "/* from smoke-fails, another header */\nint main(){ return 0; }\n"
    assert C.holdout_by_code(a, "c") == C.holdout_by_code(b, "c")


def test_identical_variants_merge_before_the_split():
    t = ("// RUN: %libomptarget-compile-run-and-check-generic\n"
         "// RUN: %libomptarget-compileopt-run-and-check-generic\n"
         "#include <stdio.h>\nint main(){\n#pragma omp target\n{}\n"
         "printf(\"ok\\n\");\n// CHECK: ok\nreturn 0;}\n")
    r = I.llvm_record("offloading/two.c", t) | {"commit": "0" * 40,
                                                  "history": {}}
    assert len(r["variants"]) == 2
    kept, merged = C.distinct_variants(r, [0, 1], t)
    assert kept == [0] and merged == {0: [1]}
    # a -D flag makes the code differ: both stay
    r2 = dict(r)
    r2["variants"] = [r["variants"][0], dict(r["variants"][1],
                                             flags=["-O3", "-DN=4"])]
    kept, merged = C.distinct_variants(r2, [0, 1], t)
    assert kept == [0, 1] and merged == {}


# ---- The harvest filters (offload.engine.harvest.filters): every test ------------------------------------

from offload.engine.harvest import filters as F

C_OK = """\
// RUN: %libomptarget-compile-run-and-check-generic
#include <omp.h>
#include <stdio.h>
int main() {
  int x = 0;
#pragma omp target map(tofrom: x)
  x = 1;
  printf("x = %d\\n", x);
  // CHECK: x = 1
  return 0;
}
"""


def _rec(text, rel="offloading/a.c"):
    return I.llvm_record(rel, text)


def _reasons(text, rel="offloading/a.c", files=None):
    r = _rec(text, rel)
    return F.classify(r, {r["files"][0]: text} if files is None else files)


def test_plain_test_is_kept():
    v = _reasons(C_OK)
    assert v["keep"], v
    assert v["variants"][0]["keep"]


def test_cpp_is_counted_not_run():
    v = _reasons(C_OK, "offloading/a.cpp")
    assert not v["keep"] and v["reasons"] == ["cpp"]


def test_extensions_and_internals():
    for code, why in (("ompx_sync_block_acq_rel();", "llvm_extension"),
                      ("__builtin_amdgcn_s_sleep(1);", "llvm_extension"),
                      ("__tgt_target_kernel(0);", "runtime_internals"),
                      ("llvm_omp_target_alloc_host(4, 0);",
                       "nonspec_routine"),
                      ("omp_get_mapped_ptr(0, 0); omp_foo_bar(1);",
                       "nonspec_routine"),
                      ("#include <omp-tools.h>", "ompt"),
                      ("#include <mpi.h>", "mpi"),
                      ('FILE *f = fopen("in.txt", "r");', "needs_files")):
        v = _reasons(C_OK.replace("int x = 0;", "int x = 0; " + code))
        assert not v["keep"] and why in v["reasons"], (code, v)


def test_host_only_is_out_of_scope():
    t = C_OK.replace("#pragma omp target map(tofrom: x)",
                     "#pragma omp parallel")
    v = _reasons(t)
    assert not v["keep"] and "host_only" in v["reasons"]
    # the device API alone is offload
    t2 = t.replace("int x = 0;", "int x = 0; void *p = omp_target_alloc(4, "
                   "0);")
    assert _reasons(t2)["keep"]


def test_variant_reasons():
    t = C_OK.replace(
        "// RUN: %libomptarget-compile-run-and-check-generic",
        "// RUN: %libomptarget-compile-generic -fopenmp-target-jit\n"
        "// RUN: env LIBOMPTARGET_INFO=4 %libomptarget-run-generic\n"
        "// RUN: %libomptarget-compile-generic -O3 -DN=4\n"
        "// RUN: env OMP_NUM_TEAMS=2 %libomptarget-run-generic\n"
        "// RUN: %not --crash %libomptarget-run-generic 2>&1 | "
        "%fcheck-generic\n"
        "// RUN: %libomptarget-run-amdgcn-amd-amdhsa | "
        "%fcheck-amdgcn-amd-amdhsa\n"
        "// RUN: %libomptarget-run-generic | %fcheck-generic")
    v = _reasons(t)
    rs = [x["reasons"] for x in v["variants"]]
    assert "llvm_flag" in rs[0] and "llvm_env" in rs[0]
    assert rs[1] == ["needs_omp_env"]
    assert rs[2] == ["expects_failure"]
    assert rs[3] == ["target_specific"]
    assert rs[4] == []
    assert v["keep"]


def test_xfail_and_smoke_fails_are_kept_and_flagged():
    t = C_OK + "// XFAIL: amdgcn-amd-amdhsa\n// UNSUPPORTED: nvptx64-nvidia-cuda\n"
    v = _reasons(t)
    assert v["keep"]
    assert "upstream_xfail_amd" in v["flags"]
    assert "upstream_unsupported_nvidia" in v["flags"]


def test_requires_llvm_only_features():
    for req, why in (("libc", "llvm_libc"), ("ompt", "ompt"),
                     ("libomptarget-debug", "llvm_debug")):
        v = _reasons(C_OK + f"// REQUIRES: {req}\n")
        assert not v["keep"] and why in v["reasons"], req


def test_filecheck_unsupported_and_llvm_messages():
    t = C_OK.replace("// CHECK: x = 1", "// CHECK: x = [[#X:]]")
    v = _reasons(t)
    assert not v["keep"] and "filecheck_unsupported" in \
        v["variants"][0]["reasons"]
    t = C_OK.replace("// CHECK: x = 1", "// CHECK: omptarget message: x")
    v = _reasons(t)
    assert "checks_llvm_message" in v["variants"][0]["reasons"]


def test_fortran_and_flags():
    t = ("! RUN: %libomptarget-compile-fortran-run-and-check-generic\n"
         "program p\n  integer :: x\n  x = 0\n!$omp target map(tofrom:x)\n"
         "  x = 1\n!$omp end target\n  print *, x\nend program\n! CHECK: 1\n")
    v = _reasons(t, "offloading/fortran/p.f90")
    assert v["keep"], v
    assert F.allowed_flag("-fopenmp-version=52") and F.allowed_flag("-O3")
    assert F.allowed_flag("-DN=4") and F.allowed_flag("-g")
    assert not F.allowed_flag("-fopenmp-assume-no-thread-state")
    assert not F.allowed_flag("-Xarch_device")
    assert not F.allowed_flag("-mllvm")


def test_multi_file_and_mixed():
    mk = ("TESTNAME = m\nTESTSRC_MAIN = m.c\nTESTSRC_AUX = n.c\nCLANG = clang\n"
          "OMP_BIN = $(AOMP)/bin/$(CLANG)\nCC = $(OMP_BIN)\n")
    src = {"m.c": C_OK, "n.c": "int n(void){return 1;}\n"}
    r = I.aomp_record("smoke/m", mk, src)
    v = F.classify(r, {f: src[f.split("/")[-1]] for f in r["files"]})
    assert not v["keep"] and "multi_file" in v["reasons"]


def test_sanitizer_and_libc_directories():
    v = _reasons(C_OK, "sanitizer/use_after_free_3.c")
    assert not v["keep"] and "sanitizer" in v["reasons"]
    v = _reasons(C_OK, "libc/malloc_parallel.c")
    assert not v["keep"] and "llvm_libc" in v["reasons"]


# ---- The inventory of harvested tests (offload.engine.harvest.inventory) ---------------------------------

from offload.engine.harvest import history as H


LLVM_C = """\
// RUN: %libomptarget-compile-generic -fopenmp-version=51 -DFOO=2
// RUN: env LIBOMPTARGET_INFO=16 %libomptarget-run-generic 2>&1 \\
// RUN:   | %fcheck-generic --check-prefix=INFO
// RUN: %libomptarget-run-generic | %fcheck-generic
// REQUIRES: gpu
// UNSUPPORTED: nvptx64-nvidia-cuda
// XFAIL: amdgcn-amd-amdhsa
#include <omp.h>
int main() {
#pragma omp target
  {}
  // CHECK: done
  // INFO: Launching kernel
  return 0;
}
"""


def test_llvm_record_fields():
    r = I.llvm_record("offloading/x.c", LLVM_C)
    assert r["lang"] == "c" and r["model"] == "omp"
    assert r["requires"] == ["gpu"]
    assert r["unsupported"] == ["nvptx64-nvidia-cuda"]
    assert r["xfail"] == ["amdgcn-amd-amdhsa"]
    assert r["checks"] == {"CHECK": 1, "INFO": 1}
    assert len(r["run"]) == 3
    vs = r["variants"]
    assert len(vs) == 2
    info, plain = vs
    assert info["env"] == {"LIBOMPTARGET_INFO": "16"}
    assert info["prefixes"] == ["INFO"] and info["stderr"]
    assert info["flags"] == ["-fopenmp-version=51", "-DFOO=2"]
    assert plain["prefixes"] == ["CHECK"] and not plain["stderr"]
    assert plain["env"] == {} and not plain["fail"]
    assert "amdgcn-amd-amdhsa" in r["arch"]


def test_llvm_run_and_check_shorthand_and_fail():
    t = ("// RUN: %libomptarget-compileopt-run-and-check-generic\n"
         "// RUN: %not --crash %libomptarget-run-generic 2>&1 | "
         "%fcheck-generic --check-prefixes=A,B\n"
         "int main(){return 0;}\n")
    r = I.llvm_record("api/y.c", t)
    a, b = r["variants"]
    assert a["flags"] == ["-O3"] and a["prefixes"] == ["CHECK"]
    assert b["fail"] and b["prefixes"] == ["A", "B"] and b["stderr"]


def test_llvm_compile_only_and_fortran_and_cpp():
    r = I.llvm_record("a/z.c", "// RUN: %libomptarget-compile-generic "
                      "-S -emit-llvm -o - | FileCheck %s\nint main(){}\n")
    assert r["variants"] == [] and r["compile_only"]
    f = I.llvm_record("offloading/fortran/q.f90",
                      "! RUN: %libomptarget-compile-fortran-run-and-check-"
                      "generic\nprogram p\n!$omp target\n!$omp end target\n"
                      "end program\n! CHECK: 1\n")
    assert f["lang"] == "f90" and f["variants"][0]["prefixes"] == ["CHECK"]
    assert f["variants"][0]["flags"] == ["-fopenmp-version=52"]
    c = I.llvm_record("a/w.cpp", "// RUN: %libomptarget-compilexx-run-and-"
                      "check-generic\nint main(){}\n")
    assert c["lang"] == "cpp"


def test_llvm_target_specific_variant():
    t = ("// RUN: %libomptarget-compile-amdgcn-amd-amdhsa && "
         "%libomptarget-run-amdgcn-amd-amdhsa | %fcheck-amdgcn-amd-amdhsa\n"
         "int main(){return 0;}\n")
    v = I.llvm_record("a/t.c", t)["variants"][0]
    assert v["triple"] == "amdgcn-amd-amdhsa"


AOMP_MAKE = """\
include ../../Makefile.defs

TESTNAME     = foo
TESTSRC_MAIN = foo.c
TESTSRC_AUX  = bar.c
TESTSRC_ALL  = $(TESTSRC_MAIN) $(TESTSRC_AUX)

CLANG        = clang
OMP_BIN      = $(AOMP)/bin/$(CLANG)
CC           = $(OMP_BIN) $(VERBOSE)
CFLAGS       = -O3
OMP_FLAGS   += -fopenmp-target-xteam-reduction
RUNENV      += OMP_NUM_TEAMS=4
RUNCMD      = ./$(TESTNAME) 2>&1 | $(FILECHECK) $(TESTSRC_MAIN)
SUPPORTED    = gfx90a,gfx942
include ../Makefile.rules
"""


def test_aomp_makefile():
    m = I.parse_makefile(AOMP_MAKE)
    assert m["TESTSRC_MAIN"] == "foo.c" and m["TESTSRC_AUX"] == "bar.c"
    r = I.aomp_record("smoke/foo", AOMP_MAKE,
                      {"foo.c": "#include <omp.h>\nint main(){\n#pragma omp "
                       "target\n{}\n// CHECK: x\nreturn 0;}\n",
                       "bar.c": "int bar(){return 1;}\n"})
    assert r["files"] == ["smoke/foo/foo.c", "smoke/foo/bar.c"]
    assert r["lang"] == "c" and r["suite"] == "smoke"
    v = r["variants"][0]
    assert v["prefixes"] == ["CHECK"] and v["stderr"]
    assert v["env"] == {"OMP_NUM_TEAMS": "4"}
    assert "-fopenmp-target-xteam-reduction" in v["flags"]
    assert "-O3" in v["flags"]
    assert r["supported"] == "gfx90a,gfx942"


def test_aomp_flang_and_no_check():
    mk = ("TESTNAME = f\nTESTSRC_MAIN = f.f90\nTESTSRC_AUX =\n"
          "FLANG ?= flang\nOMP_BIN = $(AOMP)/bin/$(FLANG)\n"
          "CC = $(OMP_BIN)\ninclude ../Makefile.rules\n")
    r = I.aomp_record("smoke-fails/f", mk, {"f.f90": "program f\n!$omp "
                                            "target\n!$omp end target\nend\n"})
    assert r["lang"] == "f90" and r["suite"] == "smoke-fails"
    assert r["variants"][0]["prefixes"] == []


def test_aomp_cpp_by_compiler():
    mk = ("TESTNAME = g\nTESTSRC_MAIN = g.c\nCLANG = clang++\n"
          "OMP_BIN = $(AOMP)/bin/$(CLANG)\nCC = $(OMP_BIN)\n")
    r = I.aomp_record("smoke/g", mk, {"g.c": "int main(){}\n"})
    assert r["lang"] == "cpp"


def test_issue_refs():
    msg = ("[OpenMP] Fix map of struct member (#91234)\n\n"
           "Fixes #90001. See also https://github.com/llvm/llvm-project/"
           "issues/88888 and PR42 and bugs.llvm.org/show_bug.cgi?id=50967\n"
           "Differential Revision: https://reviews.llvm.org/D12345")
    refs = H.issue_refs(msg)
    assert refs["fixes"] == ["llvm#90001"]
    assert "llvm#88888" in refs["issues"]
    assert "bugzilla#50967" in refs["issues"]
    assert "bugzilla#42" in refs["issues"]
    assert refs["pr"] == ["llvm#91234"]
    assert refs["reviews"] == ["D12345"]
    assert H.is_fix(msg)
    assert not H.is_fix("[OpenMP] Add a new test for teams")
    assert H.is_fix("[Offload] Fix crash when mapping zero-length arrays")


def test_aomp_ticket_from_name():
    assert H.name_tickets("flang-288446") == ["amd#288446"]
    assert H.name_tickets("bugz-50967-c") == ["bugzilla#50967"]
    assert H.name_tickets("issue_001") == ["aomp#1"]
    assert H.name_tickets("veccopy") == []


GITLOG = (
    "\x1ecommit\x1fabc123\x1f2024-01-02\x1f[OpenMP] Fix X\n\nFixes #77\x1f\n"
    "A\topenmp/libomptarget/test/offloading/x.c\n"
    "\x1ecommit\x1fdef456\x1f2024-04-22\x1f[Offload] Move libomptarget to "
    "offload\x1f\nD\topenmp/libomptarget/test/offloading/x.c\n"
    "A\toffload/test/offloading/x.c\n"
    "\x1ecommit\x1f999\x1f2025-01-01\x1f[Offload] Fix Y (#5)\x1f\n"
    "M\toffload/test/offloading/x.c\n")


def test_history_add_commit_through_the_move():
    h = H.parse_log(GITLOG, roots=("offload/test/",
                                   "openmp/libomptarget/test/"))
    rec = h["offloading/x.c"]
    assert rec["added"]["commit"] == "abc123"
    assert rec["added"]["fixes"] == ["llvm#77"]
    # later commits that touched it with a fix
    assert [c["commit"] for c in rec["fix_commits"]] == ["abc123", "999"]


def test_aomp_custom_run_rule():
    mk = ("TESTNAME = h\nTESTSRC_MAIN = h.c\nCLANG = clang\n"
          "OMP_BIN = $(AOMP)/bin/$(CLANG)\nCC = $(OMP_BIN)\n"
          "RUNENV = OMP_NUM_THREADS=2\n"
          "run: $(TESTNAME)\n\techo hi\n\t$(RUNENV) ./$(TESTNAME) 1\n"
          "\tLIBOMPTARGET_KERNEL_TRACE=1 ./$(TESTNAME) 2>&1 | $(FILECHECK) "
          "$(TESTSRC_MAIN)\n\treadelf -s a.out\n")
    r = I.aomp_record("smoke/h", mk, {"h.c": "int main(){}\n"})
    a, b = r["variants"]
    assert a["env"] == {"OMP_NUM_THREADS": "2"} and a["args"] == ["1"]
    assert b["env"] == {"LIBOMPTARGET_KERNEL_TRACE": "1"}
    assert b["prefixes"] == ["CHECK"] and b["stderr"]
    assert r["tools"] == ["readelf"]


def test_history_key_function_follows_suite_moves():
    log = ("\x1ecommit\x1fa1\x1f2021-01-01\x1fadd flang-1234 for SWDEV\x1f\n"
           "A\ttest/smoke-fails/flang-123456/x.f90\n"
           "\x1ecommit\x1fb2\x1f2022-01-01\x1fmove to smoke\x1f\n"
           "D\ttest/smoke-fails/flang-123456/x.f90\n"
           "A\ttest/smoke/flang-123456/x.f90\n")
    h = H.parse_log(log, roots=("test/",), repo="aomp",
                    key_of=lambda p: p.split("/")[1])
    assert h["flang-123456"]["added"]["commit"] == "a1"


# ---- A finding's reproducer through the harvest ------------------------------------------------------------------

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]

import harvest_probe as HP  # noqa: E402


def _r(env, node, value="check=fail", outcome="wrong_answer", **kw):
    d = {"env": env, "node": node, "outcome": outcome,
         "reason": "check_fail: ran_on_host=0 check=fail",
         "stdout": "a: 1 2\nRESULT ran_on_host=0 check=fail\n",
         "path": f"/tmp/{env}", "repeat": 1 if env == "d" else 0}
    d.update(kw)
    return d


def test_gate_cell_of_a_finding():
    row = HP.gate_row("data/findings/harvest/x.f90", "afar", 0)
    assert row["kind"] == "harvest" and row["cell"].startswith("finding|")
    envs = HP.gate_envs(row, "/tmp/root")
    assert [e["env"] for e in envs] == ["a", "b", "c", "d"]


def test_judge_confirmed_and_not():
    stored = {"outcome": "wrong_answer", "reason":
              "check_fail: ran_on_host=0 check=fail", "flaky": False,
              "stdout": "a: 1 2\nRESULT ran_on_host=0 check=fail\n"}
    reruns = [_r("a", "n1"), _r("b", "n1"), _r("d", "n1"), _r("c", "n2")]
    v = HP.judge_finding(stored, reruns, "data/findings/harvest/x.f90",
                         "afar", 0)
    assert v["verdict"] == "confirmed" and v["node_distinct"]
    ok = dict(reruns[3], outcome="correct_on_device",
              reason="ran_on_host=0 check=pass",
              stdout="RESULT ran_on_host=0 check=pass\n")
    v = HP.judge_finding(stored, reruns[:3] + [ok],
                         "data/findings/harvest/x.f90", "afar", 0)
    assert v["verdict"] != "confirmed"


# --- The strided findings link only strided updates -------------
# A target update from without a stride is no instance of the strided
# findings (the confirmer's construct vocabulary has no stride: the index
# key carries one it never sees).

PLAIN = """program p
  real(8) :: a(8)
  !$omp target data map(to: a)
  !$omp target
  a = a + 1
  !$omp end target
  !$omp target update from(a(1:4))
  !$omp end target data
end program p
"""


def _strided(name):
    from offload.engine.confirm import findings as FI
    return next(f for f in FI.load_index() if f.file.endswith(name))


def test_a_plain_update_is_no_strided_instance():
    from offload.engine.confirm import findings as FI
    f = _strided("afar-flang-strided-target-update.f90")
    assert FI.match(f, "afar", "f90", "wrong_answer", "check_fail: x",
                    PLAIN, "fuzz:s1:1:afar:gfx942:copy", "copy") is None
    assert FI.match(f, "afar", "f90", "wrong_answer", "check_fail: x",
                    PLAIN, "catalog:x", "copy") is None
    c = _strided("cce-c-strided-target-update.c")
    plain_c = ("int main(void){ int a[8];\n#pragma omp target update "
               "from(a[0:4])\n return 0; }\n")
    assert FI.match(c, "cce21", "c", "wrong_answer", "check_fail: x",
                    plain_c, "catalog:y", "copy") is None


# ---- tools/campaigns/harvest.py serves harvest2 through HARVEST_SET -------------------------------------

import json
import os
import subprocess


PROBE = r"""
import json, sys
sys.path[:0] = ["tools/campaigns", "tools"]
import harvest as HV
GT = HV._register()
print(json.dumps({"out": str(HV.OUT.relative_to(HV.ROOT)),
                  "holdout": str(HV.HOLDOUT.relative_to(HV.ROOT)),
                  "copy_only": str(HV.COPY_ONLY.relative_to(HV.ROOT)),
                  "kind": HV.KIND, "prefix": HV.CASE_PREFIX,
                  "tuolumne": HV.TARGETS["tuolumne"][0],
                  "kinds": sorted(GT.KINDS)}))
"""


def probe(env_set):
    env = dict(os.environ)
    env.pop("HARVEST_SET", None)
    if env_set:
        env["HARVEST_SET"] = env_set
    out = subprocess.run([sys.executable, "-c", PROBE], cwd=ROOT, env=env,
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out.strip().splitlines()[-1])


def test_default_is_the_49a_harvest():
    d = probe(None)
    assert d["out"] == "results/harvest" and d["kind"] == "harvest"
    assert d["holdout"] == "data/bench/harvest-holdout"
    assert d["copy_only"] == "catalog/harvest_copy_only.yaml"
    assert "cce21_4" not in d["tuolumne"]


def test_harvest2_set():
    d = probe("harvest2")
    assert d["out"] == "results/harvest2" and d["kind"] == "harvest2"
    assert d["holdout"] == "data/bench/harvest2-holdout"
    assert d["prefix"] == "harvest2-holdout-"
    assert d["copy_only"] == "catalog/harvest2_copy_only.yaml"
    assert d["tuolumne"] == ["afar", "cce19", "cce20", "cce21", "cce21_4"]
    assert "harvest2" in d["kinds"]


def test_an_unknown_set_is_refused():
    env = dict(os.environ, HARVEST_SET="nope")
    r = subprocess.run([sys.executable, "-c", PROBE], cwd=ROOT, env=env,
                       capture_output=True, text=True)
    assert r.returncode != 0


def test_holdout_run_copy_is_found(tmp_path, monkeypatch):
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    import harvest as HV
    monkeypatch.setattr(HV, "OUT", tmp_path)
    (tmp_path / "holdout-src").mkdir()
    (tmp_path / "holdout-src" / "x.c").write_text("int main(void){return 0;}\n")
    assert HV.src_path({"file": "x.c"}) == tmp_path / "holdout-src" / "x.c"
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "x.c").write_text("x")
    assert HV.src_path({"file": "x.c"}) == tmp_path / "src" / "x.c"


def test_a_checker_crash_is_recorded_as_unreadable(tmp_path, monkeypatch):
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    import harvest as HV
    from offload.engine import prerun
    monkeypatch.setattr(HV, "OUT", tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "x.c").write_text("int main(void){return 0;}\n")

    def boom(*a, **k):
        raise TypeError("'<' not supported")
    monkeypatch.setattr(prerun, "check", boom)
    r = HV._prerun_one({"id": "x", "file": "x.c", "lang": "c", "model": "omp",
                        "version": 52, "sha256": "s"})
    assert r["ok"] is False and r["kind"] == "unreadable"


def test_openacc_cells_only_where_the_model_is_compiled():
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    import harvest as HV
    progs = [{"id": "ca", "lang": "c", "model": "acc", "modes": ["copy"]},
             {"id": "fa", "lang": "f90", "model": "acc", "modes": ["copy"]},
             {"id": "co", "lang": "c", "model": "omp", "modes": ["copy"]}]
    got = {(p["id"], t) for p, t, x in HV.cells(
        progs, ["afar", "cce21", "nvhpc"], [0], {"ca", "fa", "co"}, set())}
    assert ("ca", "afar") not in got and ("ca", "cce21") not in got
    assert ("ca", "nvhpc") in got and ("fa", "cce21") in got
    assert ("fa", "afar") not in got and ("co", "afar") in got


def _hv():
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    try:
        import harvest
    finally:
        sys.path.remove(str(ROOT / "tools"))
    return harvest


def test_parts_read_oldest_first_not_by_file_name(tmp_path):
    """A retry's part can sort before the old part by name (node name, pid); readers that let
    the last row win must still see the retry last."""
    import os
    path = tmp_path / "rows.jsonl"
    old = tmp_path / "rows.part.zeta.9.jsonl"
    new = tmp_path / "rows.part.alpha.1.jsonl"
    old.write_text('{"id": "p", "obs": "old"}\n')
    new.write_text('{"id": "p", "obs": "retry"}\n')
    os.utime(old, ns=(1_000_000_000, 1_000_000_000))
    os.utime(new, ns=(2_000_000_000, 2_000_000_000))
    assert [r["obs"] for r in _hv()._jlp(path)] == ["old", "retry"]


def test_the_base_file_is_read_before_its_parts(tmp_path):
    import os
    path = tmp_path / "rows.jsonl"
    path.write_text('{"id": "p", "obs": "base"}\n')
    part = tmp_path / "rows.part.a.1.jsonl"
    part.write_text('{"id": "p", "obs": "part"}\n')
    os.utime(path, ns=(5_000_000_000, 5_000_000_000))     # newer than the part, still first
    os.utime(part, ns=(1_000_000_000, 1_000_000_000))
    assert [r["obs"] for r in _hv()._jlp(path)] == ["base", "part"]




@pytest.mark.parametrize("tool", ["dataenv", "oop"])
def test_other_campaign_tools_read_parts_oldest_first_too(tmp_path, tool):
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    try:
        mod = __import__(tool)
    finally:
        sys.path.remove(str(ROOT / "tools"))
    path = tmp_path / "rows.jsonl"
    old = tmp_path / "rows.part.zeta.9.jsonl"
    new = tmp_path / "rows.part.alpha.1.jsonl"
    old.write_text('{"id": "p", "obs": "old"}\n')
    new.write_text('{"id": "p", "obs": "retry"}\n')
    os.utime(old, ns=(1_000_000_000, 1_000_000_000))
    os.utime(new, ns=(2_000_000_000, 2_000_000_000))
    assert [r["obs"] for r in mod._jl(path)] == ["old", "retry"]


# ---- tools/campaigns/harvest.py: cells and the failure value the gate keys on ------------------------------------



import harvest as HV  # noqa: E402


def test_hv_value_names_the_failed_check():
    out = ("HV| x = 2\nHV-FAIL CHECK not found: x = 1\n"
           "RESULT ran_on_host=0 check=fail\n")
    assert HV.hv_value(out) == "check=fail CHECK not found: x = 1"
    assert HV.hv_value("RESULT ran_on_host=0 check=pass\n") == "check=pass"
    assert HV.hv_value("") is None
    # the second run's line wins (the harness concatenates both runs)
    two = out + "HV-FAIL CHECK not found: y\nRESULT ran_on_host=1 check=fail\n"
    assert HV.hv_value(two).endswith("y")


def test_cells_follow_modes_and_prerun():
    progs = [{"id": "a", "modes": ["copy", "unified"]},
             {"id": "b", "modes": ["unified"]},
             {"id": "c", "modes": ["copy", "unified"]}]
    got = HV.cells(progs, ["afar", "nvhpc"], [0, 1, 2], {"a", "b"})
    assert ("a", "afar", 0) in {(p["id"], t, x) for p, t, x in got}
    keys = {(p["id"], t, x) for p, t, x in got}
    assert ("b", "afar", 0) not in keys and ("b", "afar", 1) in keys
    assert ("b", "nvhpc", 2) in keys and ("b", "nvhpc", 0) not in keys
    assert not any(p["id"] == "c" for p, _, _ in got)


def test_gate_kind_registered():
    GT = HV._register()
    assert GT.KINDS["harvest"] == {"prefix": "harvest_",
                                   "signature": "program"}
    env = GT.environments({"kind": "harvest", "cell": "harvest|x|afar|1"},
                          root="/tmp/x")
    assert env[0]["path"].startswith("/tmp/x/harvest_")


def test_owner_splits_rows_of_other_allocations():
    alloc = ["n1", "n2"]
    assert HV._owner({"node": "n2", "cell": "c"}, alloc) == "n2"
    owners = {HV._owner({"node": "old", "cell": f"c{k}"}, alloc)
              for k in range(20)}
    assert owners == {"n1", "n2"}


def test_gate_priority_puts_bug_fix_tests_and_new_signatures_first():
    def it(pid, tc, cls="wrong_answer", reason="check_fail: x"):
        return {"kind": "harvest", "ident": pid, "toolchain": tc,
                "xnack": 0, "outcome": cls, "reason": reason,
                "value": "check=fail x", "cell": f"harvest|{pid}|{tc}|0"}
    items = [it("bf", "cce19"), it("bf", "cce20"), it("plain", "cce19"),
             it("c1", "cce19", "rejected", "diagnostic: no such clause"),
             it("c2", "cce19", "rejected", "diagnostic: no such clause")]
    progs = {"bf": {"bugfix": {"kind": "fixes_issue"}}, "plain": {},
             "c1": {}, "c2": {}}
    t = HV.gate_priority(items, progs)
    assert t["harvest|bf|cce19|0"] == 0 and t["harvest|bf|cce20|0"] == 0
    assert t["harvest|plain|cce19|0"] == 2
    # one compile-time signature: its first row leads, the other inherits
    assert sorted([t["harvest|c1|cce19|0"], t["harvest|c2|cce19|0"]]) == \
        [2, 4]


def test_convert_is_frozen_once_the_holdout_is_sealed(tmp_path, monkeypatch):
    sealed = tmp_path / "harvest-holdout"
    sealed.mkdir()
    (sealed / "SEAL").write_text("sealed\n")
    monkeypatch.setattr(HV, "HOLDOUT", sealed)
    monkeypatch.setattr(HV, "OUT", tmp_path / "out")
    assert HV.main(["convert"]) == 1
    assert not (tmp_path / "out" / "programs.jsonl").exists()


# --- The confirmer reads the current pre-run verdicts --

def _jlw(path, rows):
    import json
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def _prerun_fixture(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    _jlw(out / "programs.jsonl", [
        {"id": "a", "sha256": "A2", "holdout": False},
        {"id": "b", "sha256": "B2", "holdout": False}])
    # main file: a refused on an earlier text, b missing
    _jlw(out / "prerun.jsonl", [
        {"id": "a", "ok": False, "reasons": ["race: x"], "sha256": "A1",
         "kind": "race"}])
    # the current verdicts live only in per-writer parts
    _jlw(out / "prerun.part.n1.1.jsonl", [
        {"id": "a", "ok": True, "reasons": [], "sha256": "A2", "kind": ""}])
    _jlw(out / "prerun.part.n2.2.jsonl", [
        {"id": "b", "ok": True, "reasons": [], "sha256": "B2", "kind": ""}])
    monkeypatch.setattr(HV, "OUT", out)
    return out


def test_prerun_rows_are_current_and_complete(tmp_path, monkeypatch):
    _prerun_fixture(tmp_path, monkeypatch)
    pre = HV.prerun_rows()
    assert pre["a"]["ok"] and pre["a"]["sha256"] == "A2"
    assert pre["b"]["ok"]


def test_confirm_context_uses_the_current_prerun_verdicts(tmp_path,
                                                         monkeypatch):
    _prerun_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(HV, "rows", lambda name: [])
    monkeypatch.setattr(HV, "verdicts", lambda name: {})
    ctx = HV.confirm_context("main")
    assert ctx["pre"] == HV.prerun_rows()
    from offload.engine.confirm.legality import Legality  # noqa: F401
    lg = HV._legality({"id": "a"}, "cce21", ctx["pre"], {})
    assert lg.status == "legal"


# --- Dev compiler_bug programs become candidates -------

def test_candidates_dev_only_and_not_covered():
    conf = [
        {"program": "p1", "toolchain": "nvhpc", "verdict": "compiler_bug",
         "rule": "R11-compile-rejection", "reason": "rejected: S-0155 x",
         "holdout": False, "findings": []},
        {"program": "p2", "toolchain": "cce21", "verdict": "compiler_bug",
         "rule": "R10b-own-link-or-hang", "reason": "link: omp_get_level",
         "holdout": False, "findings": ["data/findings/x.c"]},
        {"program": "p3", "toolchain": "cce21", "verdict": "compiler_bug",
         "rule": "R10-compile-ice", "reason": "ice", "holdout": True,
         "findings": []},
        {"program": "p4", "toolchain": "afar", "verdict": "compiler_bug",
         "rule": "R10-compile-ice", "reason": "ice: y", "holdout": False,
         "findings": []},
        {"program": "p5", "toolchain": "afar", "verdict": "needs_human",
         "rule": "R22-expected-weak", "reason": "", "holdout": False,
         "findings": []}]
    pmap = {f"p{k}": {"record": f"llvm/t{k}.c"} for k in range(1, 6)}
    covered = {"llvm/t4.c"}
    cs = HV.candidates(conf, pmap, covered)
    assert [c["test"] for c in cs] == ["llvm/t1.c"]
    assert cs[0]["families"] == ["nvhpc"]
    assert "documented support" in cs[0]["missing"]


# --- Tests that assume separate memory ---------------

def _row(pid, tc, x, cls):
    outcome = {"ok": "correct_on_device", "wa": "wrong_answer"}[cls]
    return {"program_id": pid, "toolchain": tc, "xnack": x,
            "outcome": outcome,
            "reason": "" if cls == "ok" else "check_fail: x"}


def test_separate_memory_programs():
    rs = [
        # copy passes, shared fails on every family that runs it: separate
        _row("s", "afar", 0, "ok"), _row("s", "afar", 1, "wa"),
        _row("s", "cce21", 0, "ok"), _row("s", "cce21", 1, "wa"),
        _row("s", "nvhpc", 0, "ok"), _row("s", "nvhpc", 2, "wa"),
        # one compiler fails only in shared mode, another passes there:
        # a unified-memory defect candidate, not a separate-memory test
        _row("u", "afar", 0, "ok"), _row("u", "afar", 1, "wa"),
        _row("u", "cce21", 0, "ok"), _row("u", "cce21", 1, "ok"),
        # fails everywhere: not storage dependence
        _row("f", "afar", 0, "wa"), _row("f", "afar", 1, "wa")]
    assert HV.separate_memory_programs(rs) == {"s"}


def test_copy_only_rows_are_not_applicable():
    rs = [_row("s", "afar", 0, "ok"), _row("s", "afar", 1, "wa"),
          _row("s", "nvhpc", 2, "wa"), _row("t", "afar", 1, "wa")]
    kept = HV.drop_not_applicable(rs, {"s"})
    assert [(r["program_id"], r["xnack"]) for r in kept] == \
        [("s", 0), ("t", 1)]
    progs = [{"id": "s", "modes": ["copy", "unified"]},
             {"id": "t", "modes": ["copy", "unified"]}]
    got = HV.cells(progs, ["afar", "nvhpc"], [0, 1, 2], {"s", "t"},
                   copy_only={"s"})
    assert sorted((p["id"], t, x) for p, t, x in got) == [
        ("s", "afar", 0), ("s", "nvhpc", 0),
        ("t", "afar", 0), ("t", "afar", 1), ("t", "nvhpc", 0),
        ("t", "nvhpc", 2)]


def test_copy_only_list_is_dev_only():
    rs = [_row(p, "afar", 0, "ok") for p in ("d", "h")] + \
         [_row(p, "afar", 1, "wa") for p in ("d", "h")]
    pmap = {"d": {"holdout": False}, "h": {"holdout": True}}
    assert HV.copy_only_programs(rs, pmap) == ["d"]


def test_a_finding_covers_its_upstream_directory():
    conf = [{"program": p, "toolchain": "cce21", "verdict": "compiler_bug",
             "rule": "R12b-wrong-answer", "reason": "", "holdout": False,
             "findings": []} for p in ("a", "b")]
    pmap = {"a": {"record": "llvm/offloading/strided_update/x.c"},
            "b": {"record": "llvm/offloading/other.c"}}
    covered = HV.covered_tests({"new": [{"upstream": [
        "the 25 non-holdout tests of llvm/offloading/strided_update/"]}],
        "linked": [{"upstream": ["llvm/z.c"]}]})
    assert [c["test"] for c in HV.candidates(conf, pmap, covered)] == \
        ["llvm/offloading/other.c"]


# --- The holdout outcomes, the seal, the report's
# redaction and the confirmer's inputs, on a small made-up harvest ----------

import json  # noqa: E402
from argparse import Namespace  # noqa: E402

DEV, HOLD = "hv-llvm-dev-one", "hv-llvm-secret-hold"


def _fake_harvest(tmp_path, monkeypatch, copy_only=()):
    out = tmp_path / "out"
    (out / "main").mkdir(parents=True)

    def jl(path, rs):
        path.write_text("".join(json.dumps(r) + "\n" for r in rs))
    progs = [{"id": i, "record": f"llvm/{i[8:].replace('-', '_')}.c",
              "holdout": h, "bugfix": {"kind": "llvm-fix", "refs": ["#1"]},
              "source": "llvm", "lang": "c", "oracle": "filecheck",
              "modes": ["copy", "unified"], "sha256": f"s-{i}"}
             for i, h in ((DEV, False), (HOLD, True))]
    jl(out / "programs.jsonl", progs)
    jl(out / "inventory.jsonl", [{"source": "llvm", "lang": "c"}] * 2)
    jl(out / "filtered.jsonl", [{"id": p["record"], "keep": True,
                                 "reasons": []} for p in progs])
    rs = []
    for p in progs:
        for t, x, o in (("afar", 0, "wrong_answer"),
                        ("afar", 1, "wrong_answer"),
                        ("cce21", 0, "correct_on_device")):
            rs.append({"program_id": p["id"], "toolchain": t, "xnack": x,
                       "outcome": o, "reason": "check_fail: x",
                       "sha256": p["sha256"]})
    jl(out / "main" / "rows.jsonl", rs)
    jl(out / "main" / "confirm.jsonl", [
        {"program": p["id"], "toolchain": "afar", "mode": "copy",
         "verdict": "compiler_bug", "rule": "R12b-wrong-answer",
         "gate": "confirmed", "holdout": p["holdout"],
         "findings": ["data/findings/x.c"], "legality": "legal"}
        for p in progs])
    ver = {f"harvest|{p['id']}|afar|{x}": {
        "verdict": "confirmed", "own": True,
        "item": {"toolchain": "afar", "xnack": x, "ident": p["id"]}}
        for p in progs for x in (0, 1)}
    monkeypatch.setattr(HV, "OUT", out)
    monkeypatch.setattr(HV, "TARGETS", {
        "tuolumne": (["afar", "cce20", "cce21"], [0, 1])})
    monkeypatch.setattr(HV, "prerun_rows", lambda: {
        p["id"]: {"id": p["id"], "ok": True, "kind": "ok"} for p in progs})
    monkeypatch.setattr(HV, "verdicts", lambda name, budget_h=None: ver)
    monkeypatch.setattr(HV, "pinned", lambda: {
        "llvm": {"commit": "0" * 40}, "aomp": {"commit": "1" * 40}})
    monkeypatch.setattr(HV, "load_copy_only", lambda: set(copy_only))
    return progs


def test_report_never_names_a_holdout_program(tmp_path, monkeypatch):
    _fake_harvest(tmp_path, monkeypatch)
    text = HV.render("main")
    assert "dev_one" in text           # the dev program is named
    assert "secret" not in text         # the holdout's id and path are not
    assert "a holdout program" in text  # its unrun cell is counted
    # no outcome count of the holdout: the per-compiler
    # table and the funnel count the dev program's rows only
    assert "| afar X0 | 1 | 0 | wrong_answer 1 |" in text
    assert "| failing rows (non-holdout, as every count below) | 2 |" in text
    assert "holdout rows linked" not in text


def test_report_counts_the_not_applicable_rows(tmp_path, monkeypatch):
    _fake_harvest(tmp_path, monkeypatch, copy_only=[DEV])
    text = HV.render("main")
    assert "| not applicable (unified/managed rows of copy-only dev " \
        "programs) | 1 | 1 programs" in text
    assert "afar X1 | 0 |" not in text and "| afar X1 |" not in text


def test_holdout_outcomes(tmp_path, monkeypatch):
    _fake_harvest(tmp_path, monkeypatch)
    monkeypatch.setattr(HV, "TARGETS", {
        "tuolumne": (["afar", "cce20"], [0, 1]),
        "wingtip": (["nvhpc"], [0, 2])})
    monkeypatch.setattr(HV, "holdout_cases", lambda: [
        {"case": "harvest-holdout-001", "id": HOLD, "modes": ["copy"]},
        {"case": "harvest-holdout-002", "id": "hv-refused",
         "modes": ["copy", "unified"]}])
    got = HV.holdout_outcomes("main")
    assert got == [
        ["harvest-holdout-001", "afar", "copy", "wrong_answer", "confirmed"],
        ["harvest-holdout-001", "afar", "unified", "not_applicable", ""],
        ["harvest-holdout-001", "cce20", "copy", "not_run", ""],
        ["harvest-holdout-001", "cce20", "unified", "not_applicable", ""],
        ["harvest-holdout-001", "nvhpc", "copy", "not_run", ""],
        ["harvest-holdout-001", "nvhpc", "managed", "not_applicable", ""],
        ["harvest-holdout-002", "afar", "copy", "refused", ""],
        ["harvest-holdout-002", "afar", "unified", "refused", ""],
        ["harvest-holdout-002", "cce20", "copy", "refused", ""],
        ["harvest-holdout-002", "cce20", "unified", "refused", ""],
        ["harvest-holdout-002", "nvhpc", "copy", "refused", ""],
        ["harvest-holdout-002", "nvhpc", "managed", "refused", ""]]


def test_seal_once_and_it_checks(tmp_path, monkeypatch):
    import fresh_bench as FB
    hold = tmp_path / "harvest-holdout"
    hold.mkdir()
    (hold / "harvest-holdout-001.c").write_text("int main(void){}\n")
    (hold / "cases.yaml").write_text("cases: []\n")
    monkeypatch.setattr(HV, "HOLDOUT", hold)
    rows_ = [["harvest-holdout-001", "afar", "copy", "not_run", ""]]
    monkeypatch.setattr(HV, "holdout_outcomes", lambda name: rows_)
    a = Namespace(name="main", commit="abc123", allow_missing_machine=[])
    assert HV.cmd_seal(a) == 2 and not (hold / "SEAL").exists()
    rows_[0][3] = "correct_on_device"
    assert HV.cmd_seal(a) == 0
    paths = [hold / "harvest-holdout-001.c"]
    assert FB.check_seal(hold / "SEAL", paths, hold / "cases.yaml",
                         hold / "outcomes.csv") == []
    assert "harvest-holdout-001,afar,copy,correct_on_device," in \
        (hold / "outcomes.csv").read_text()
    assert HV.cmd_seal(a) == 1          # once
    (hold / "outcomes.csv").write_text("changed\n")
    assert FB.check_seal(hold / "SEAL", paths, hold / "cases.yaml",
                         hold / "outcomes.csv")


def test_confirm_context_leaves_out_copy_only_shared_rows(tmp_path,
                                                          monkeypatch):
    _fake_harvest(tmp_path, monkeypatch, copy_only=[DEV])
    cx = HV.confirm_context("main")
    keys = {(r["program_id"], r["xnack"]) for r in cx["rows"]}
    assert (DEV, 1) not in keys and (DEV, 0) in keys and (HOLD, 1) in keys
    assert set(cx["by_prog"]) == {DEV, HOLD}
    assert cx["pre"][DEV]["ok"]
