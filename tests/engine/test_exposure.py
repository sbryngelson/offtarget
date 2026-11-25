"""Exposure (offload.engine.exposure): a finding's trigger as the ingredients its own evidence
proves necessary, and the public code that has every one of them."""
from pathlib import Path

from offload.engine import exposure as E, usage as U

TARGET_PRINT = """program p
  integer :: x
  x = 1
!$omp target map(tofrom: x)
  print *, 'in target', x
!$omp end target
end program p
"""


def test_a_region_keeps_its_words_without_strings_or_comments():
    r = U.scan(TARGET_PRINT, "p.f90").regions[0]
    assert {"print", "x"} <= r.words
    assert "target" not in r.words and "in" not in r.words   # the string's words are not code
    c = U.scan('void f(int *a){\n#pragma omp target\n{ a[0] = 1; /* nowait */ puts("go"); }\n}\n',
               "f.c").regions[0]
    assert {"a", "puts"} <= c.words and "nowait" not in c.words and "go" not in c.words


MIN = """! Minimized by compliance.fuzz_min from fuzz seed 7 (fuzz-1).
! toolchain: afar (-O2)
program fuzz_prog
  integer :: x
  x = 0
!$omp target teams map(tofrom: x)
  x = ishft(x, 1)
!$omp end target teams
  print '(a)', 'RESULT ran_on_host=0 check=pass'
end program fuzz_prog
"""


def test_a_minimized_program_needs_all_it_kept_inside_its_regions(tmp_path):
    f = tmp_path / "fuzz" / "7-afar.f90"
    f.parent.mkdir()
    f.write_text(MIN)
    s = E.signature(f, tmp_path)
    assert s.kind == "minimal"
    (part,) = s.parts
    assert {"dir:target", "dir:teams", "map:tofrom"} <= part.features
    assert "ishft" in part.words and "print" not in part.words    # the harness is outside
    assert "x" not in part.words                                   # a declared name varies


HAND = """! - title: a print in a target region crashes
! - control: controls/print-crash-no-print-control.f90 runs
program p
  character(len=4) :: s
!$omp target map(from: s) nowait
  s = 'abcd'
  print *, s
!$omp end target
!$omp taskwait
end program p
"""
CONTROL = HAND.replace("  print *, s\n", "").replace(" nowait", "")


def test_each_passing_control_adds_the_ingredient_it_removed(tmp_path):
    f = tmp_path / "print-crash.f90"
    f.write_text(HAND)
    (tmp_path / "controls").mkdir()
    (tmp_path / "controls" / "print-crash-no-print-control.f90").write_text(CONTROL)
    s = E.signature(f, tmp_path)
    assert s.kind == "controls"
    (req,) = s.requirements
    assert "clause:nowait" in req.features and "dir:target" in req.features
    assert "print" in req.words
    assert "character" not in req.words       # both have it: the control does not prove it needed
    assert "s" not in req.words


DETACH = """// - control: controls/d-no-detach-control.c runs
#include <stdlib.h>
struct S { int *p; } q;
int main(void) {
  int buf[4];
  q.p = buf;
#pragma acc enter data copyin(q, q.p[0:4])
#pragma acc parallel loop present(q)
  for (int i = 0; i < 4; i++) q.p[i] = i;
#pragma acc exit data detach(q.p) delete(q)
  return 0;
}
"""


def test_a_removed_clause_on_a_standalone_directive_counts_for_the_file(tmp_path):
    f = tmp_path / "d.c"
    f.write_text(DETACH)
    (tmp_path / "controls").mkdir()
    (tmp_path / "controls" / "d-no-detach-control.c").write_text(
        DETACH.replace(" detach(q.p)", ""))
    (req,) = E.signature(f, tmp_path).requirements
    assert "clause:detach" in req.file_features
    assert {"dir:parallel", "dir:loop"} <= req.features and not req.words


def test_a_control_that_removes_only_names_proves_nothing(tmp_path):
    f = tmp_path / "n.f90"
    f.write_text(HAND)
    (tmp_path / "controls").mkdir()
    (tmp_path / "controls" / "print-crash-no-print-control.f90").write_text(
        HAND.replace("s = 'abcd'", "s(1:1) = 'a'").replace(":: s", ":: s, t"))
    assert E.signature(f, tmp_path) is None


def test_names_are_what_the_program_declares():
    n = E.names(HAND, "h.f90")
    assert "s" in n and "p" in n and "print" not in n and "character" not in n
    c = E.names(DETACH, "d.c")
    assert {"q", "p", "buf", "i", "s", "main"} <= c and not {"int", "struct", "return"} & c


def test_no_control_and_no_reduction_is_not_measurable(tmp_path):
    f = tmp_path / "plain.f90"
    f.write_text(HAND.replace("! - control: controls/print-crash-no-print-control.f90 runs\n", ""))
    assert E.signature(f, tmp_path) is None


def _rec(repo, text, name="a.f90"):
    return E.record(text, name, repo)


def test_a_file_counts_only_with_every_ingredient_and_a_repo_once():
    sig = E.Signature("minimal", parts=[E.Part(frozenset({"dir:target", "dir:teams"}),
                                               frozenset({"ishft"}))])
    hit = MIN.replace("Minimized", "Written")
    no_word = hit.replace("ishft(x, 1)", "x + 1")
    no_teams = hit.replace("target teams", "target")
    other = hit.replace("x = ishft(x, 1)", "x = ishft(x, 1) + y")
    recs = [_rec("org/a", hit), _rec("org/a", hit + "\n! copy\n", "b.f90"),
            _rec("org/b", no_word), _rec("org/c", no_teams), _rec("org/d", hit),
            _rec("org/e", other)]
    got = E.count({"f": sig}, recs)
    # copies (a fork, a vendored file, one with another comment) are one use
    assert got["f"] == {"repos": 2, "files": 2}


def test_a_file_needs_the_standalone_directive_features_too():
    sig = E.Signature("controls", requirements=[E.Part(frozenset({"dir:parallel"}),
                                                       file_features=frozenset({"clause:detach"}))])
    recs = [_rec("o/a", DETACH, "a.c"), _rec("o/b", DETACH.replace(" detach(q.p)", ""), "b.c")]
    assert E.count({"f": sig}, recs)["f"] == {"repos": 1, "files": 1}


def test_every_committed_finding_gets_a_signature_or_none():
    root = Path(__file__).resolve().parents[2] / "data" / "findings"
    sigs = E.signatures(root)
    assert len(sigs) > 300
    kinds = {s.kind for s in sigs.values() if s}
    assert kinds == {"minimal", "controls"}


def test_a_removed_modifier_is_an_ingredient(tmp_path):
    prog = """// - control: controls/u-plain-control.c runs
int main(void) {
  int a[4] = {0};
#pragma omp target enter data map(to: a)
#pragma omp target
  a[0] = 1;
#pragma omp target update to(iterator(k = 0:1): a[k:1])
  return 0;
}
"""
    f = tmp_path / "u.c"
    f.write_text(prog)
    (tmp_path / "controls").mkdir()
    (tmp_path / "controls" / "u-plain-control.c").write_text(
        prog.replace("iterator(k = 0:1): a[k:1]", "a[0:1]"))
    (req,) = E.signature(f, tmp_path).requirements
    assert "mod:to:iterator" in req.file_features


def _obs(tc, target, failed, cls="wrong_answer"):
    from offload.engine.finding_rows import Obs
    return Obs(tc, target, "a", "", not failed, failed, "", "site-rows", cls=cls)


def test_a_control_job_runs_where_the_finding_fails_with_another_family_as_reference():
    obs = [_obs("gcc", "mi300a-c", True), _obs("gcc", "mi300a-c", True),
           _obs("afar", "mi300a-c", False, "correct"), _obs("nvhpc", "a100-s", True)]
    job = E.control_job("fuzz/x.f90", obs, local={"gcc", "afar", "cce19"})
    assert job["targets"] == ["gcc/0"] and job["reference"] in ("host:afar", "host:cce19")
    assert E.control_job("fuzz/y.f90", [_obs("nvhpc", "a100-s", True)], local={"gcc"}) is None


def test_generated_controls_join_the_header_controls(tmp_path):
    f = tmp_path / "print-crash.f90"
    f.write_text(HAND.replace("! - control: controls/print-crash-no-print-control.f90 runs\n", ""))
    assert E.signature(f, tmp_path) is None
    extra = tmp_path / "gen"
    (extra / E.job_slug("print-crash.f90") / "controls").mkdir(parents=True)
    (extra / E.job_slug("print-crash.f90") / "controls" / "c1-control.f90").write_text(
        HAND.replace(" nowait", ""))
    (req,) = E.signature(f, tmp_path, extra).requirements
    assert "clause:nowait" in req.features


def test_only_loose_or_unmeasured_findings_queue():
    loose = E.Signature("controls", requirements=[E.Part(frozenset({"dir:target", "dir:parallel"}))])
    tight = E.Signature("controls", requirements=[E.Part(frozenset({"dir:target", "clause:if"}),
                                                         frozenset({"stop"}))])
    assert E.wants_controls(None) and E.wants_controls(loose)
    assert not E.wants_controls(tight)
    assert not E.wants_controls(E.Signature("minimal", parts=[E.Part(frozenset({"dir:target"}))]))


def test_the_control_job_uses_the_compiler_the_finding_names_not_the_most_failing():
    obs = [_obs("cce21", "mi300a-u", True, "rejected")] * 4 + [_obs("afar", "mi300a-c", True)]
    job = E.control_job("x.c", obs, local={"afar", "cce21", "gcc"}, named=({"afar"}, {0}))
    assert job["targets"] == ["afar/0"] and job["reference"] == "host:gcc"


def test_the_named_compilers_come_from_the_index_or_the_header():
    assert E.named_compilers({"toolchains": ["afar", "afar244"], "modes": ["copy"]}, "") == \
        ({"afar", "afar244"}, {0})
    head = "! # Finding (GCC 16.2): x\n!\n! - toolchains and modes that fail: gcc (GCC 16.2.0); modes: copy; -O2\n"
    tcs, modes = E.named_compilers(None, head)
    assert "gcc" in tcs and not {"afar", "cce21"} & tcs and modes == {0}
    fz = "! Minimized by compliance.fuzz_min from fuzz seed 1 (fuzz-1).\n! toolchain: afar (-O2, HSA_XNACK=1)\n"
    assert E.named_compilers(None, fz) == ({"afar"}, {1})


def test_directive_names_alone_are_no_measure(tmp_path):
    f = tmp_path / "t.f90"
    f.write_text(HAND.replace("! - control: controls/print-crash-no-print-control.f90 runs\n", "")
                 .replace("!$omp target map(from: s) nowait", "!$omp target teams map(from: s) nowait")
                 .replace("!$omp end target\n", "!$omp end target teams\n"))
    extra = tmp_path / "gen"
    (extra / "t" / "controls").mkdir(parents=True)
    (extra / "t" / "controls" / "unwrap-control.f90").write_text(
        f.read_text().replace("target teams", "target"))
    s = E.signature(f, tmp_path, extra)
    assert s is not None and E.ingredients(s) == 0
    assert not E.measurable(s) and E.measurable(E.Signature("minimal", parts=[E.Part(frozenset({"dir:target"}))]))


TWO = """program p
  integer :: a(8)
!$omp target map(tofrom: a) nowait depend(out: a)
  a = 1
!$omp end target
!$omp target parallel map(to: a) nowait depend(in: a)
  a = a
!$omp end target parallel
!$omp taskwait
end program p
"""


def test_a_clause_removed_from_one_of_two_regions_counts_on_that_region(tmp_path):
    f = tmp_path / "two.f90"
    f.write_text(TWO)
    extra = tmp_path / "gen"
    (extra / "two" / "controls").mkdir(parents=True)
    (extra / "two" / "controls" / "c-control.f90").write_text(
        TWO.replace("map(tofrom: a) nowait depend(out: a)", "map(tofrom: a) depend(out: a)"))
    (req,) = E.signature(f, tmp_path, extra).requirements
    assert req.features == {"dir:target", "clause:nowait"}


def test_a_match_says_where_and_examples_link_pinned_code():
    sig = E.Signature("minimal", parts=[E.Part(frozenset({"dir:target", "dir:teams"}), frozenset({"ishft"}))])
    hit = MIN.replace("Minimized", "Written")
    a = E.record(hit, "src/a.f90", "org/a", sha="abc123", stars=5)
    b = E.record(hit.replace("ishft(x, 1)", "ishft(x, 1) + y"), "b.f90", "org/b", sha="def456", stars=50)
    assert E.match_line(sig, a) == 6 and E.match_line(sig, E.record(MIN.replace("ishft", "iand"), "c.f90", "o/c")) is None
    got = E.count({"f": sig}, [a, b], examples=5)
    ex = got["f"]["examples"]
    assert [x["repo"] for x in ex] == ["org/b", "org/a"]        # most stars first
    assert ex[1]["url"] == "https://github.com/org/a/blob/abc123/src/a.f90#L6"
    assert E.count({"f": sig}, [a, b], examples=5, gone={"org/b"})["f"]["examples"][0]["repo"] == "org/a"


def test_examples_need_two_proven_ingredients():
    one = E.Signature("controls", requirements=[E.Part(frozenset({"dir:target"}), frozenset({"stop"}))])
    two = E.Signature("controls", requirements=[E.Part(frozenset({"dir:target", "clause:if"}), frozenset({"stop"}))])
    assert not E.shows_examples(one) and E.shows_examples(two)
    assert E.shows_examples(E.Signature("minimal", parts=[E.Part(frozenset({"dir:target"}))]))


def test_compiler_trees_and_test_suites_are_not_application_code():
    for repo, path in (("someone/llvm-project", "clang/test/OpenMP/target_map.c"),
                       ("someone/llvm", "openmp/libomptarget/test/mapping/a.c"),
                       ("x/clang", "test/OpenMP/a.cpp"),
                       ("x/aomp", "test/smoke/red/red.c"),
                       ("x/gcc", "gcc/testsuite/gfortran.dg/gomp/a.f90"),
                       ("x/suite", "Tests/validation/acc_copy.c")):
        assert not E.is_application(repo, path), path
    for repo, path in (("BeauJoh/HeCBench", "lid-driven-cavity-omp/calculate_v.h"),
                       ("fspiga/FluTAS", "src/apps/main__two_phase_ht.f90"),
                       ("me/latest", "src/contest/solver.f90")):
        assert E.is_application(repo, path), path


def test_a_function_pointer_is_a_name():
    src = "int add1(int x) { return x + 1; }\nint main(void) {\n  int (*f)(int) = add1;\n  int (*g[2])(int);\n  return f(1);\n}\n"
    assert {"f", "g", "add1", "x"} <= E.names(src, "p.c")


def test_an_openacc_finding_never_gets_afar_as_its_reference():
    obs = [_obs("cce20", "mi300a-u", True), _obs("afar", "mi300a-u", False, "correct")]
    job = E.control_job("x.f90", obs, local={"afar", "cce20", "gcc"}, model="acc")
    assert job["reference"] == "host:gcc"


DETAIL_F = """module m
  real(8), allocatable :: buf(:)
  !$acc declare create(buf)
contains
  subroutine s(c, n)
    character(len=*), intent(in) :: c
    integer, intent(in) :: n
    integer :: i
    complex :: z
    !$acc parallel loop present(buf)
    do i = 1, n
      buf(i) = real(ichar(c(1:1)), 8) + real(z)
    end do
  end subroutine s
end module m
"""


def test_a_region_records_the_types_and_attributes_of_what_it_uses():
    (r,) = U.scan(DETAIL_F, "m.f90").regions
    assert {"type:character", "attr:dummy", "type:complex", "attr:module", "attr:allocatable",
            "type:real"} <= r.detail
    assert not any(d.startswith(("type:", "attr:")) for d in r.features)     # the profile's features stay
    c = U.scan("struct S { int *p; };\nint main(void) {\n  static double w[4];\n  struct S s;\n"
               "#pragma omp target map(tofrom: s, w)\n  { w[0] = s.p[0]; }\n  return 0;\n}\n", "c.c").regions[0]
    assert {"type:struct", "type:double", "attr:static", "attr:array"} <= c.detail


def test_resemblance_needs_every_region_with_its_detail(tmp_path):
    f = tmp_path / "r.f90"
    f.write_text(DETAIL_F)
    sim = E.resemblance(f)
    assert sim and any("type:character" in p.detail for p in sim)
    same = E.record(DETAIL_F, "a.f90", "o/a")
    other = E.record(DETAIL_F.replace("character(len=*), intent(in) :: c", "integer, intent(in) :: c")
                     .replace("ichar(c(1:1))", "c"), "b.f90", "o/b")
    got = E.count_similar({"r.f90": sim}, [same, other])
    assert got["r.f90"] == {"repos": 1, "files": 1}


def test_the_self_check_flag_is_not_part_of_the_resemblance(tmp_path):
    prog = """program p
  use openacc, only: acc_on_device, acc_device_host
  integer, parameter :: n = 8
  integer :: a(n), i, hf
  hf = 0
  !$acc parallel copy(hf) num_gangs(1)
  hf = merge(1, 0, acc_on_device(acc_device_host))
  !$acc end parallel
  !$acc parallel loop copy(a, hf)
  do i = 1, n
    a(i) = ishft(i, 1)
  end do
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hf, ' check=', merge('pass', 'fail', a(1) == 2)
end program p
"""
    f = tmp_path / "h.f90"
    f.write_text(prog)
    (part,) = E.resemblance(f)
    assert not part.words and "clause:num_gangs" not in part.features    # the flag's region is gone
    assert "clause:copy" in part.features and "attr:parameter" not in part.detail
    assert "copy(a)" in E.unharnessed(prog) and "num_gangs" in E.unharnessed(prog)


def test_the_same_ingredient_from_two_controls_counts_once():
    q = E.Part(frozenset({"dir:parallel", "dir:loop", "clause:present"}))
    assert E.ingredients(E.Signature("controls", requirements=[q, q])) == 1
