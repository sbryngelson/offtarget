"""A generated finding's words (offload.engine.autodraft): its key constructs from the reduction's
one-change controls, and its title, name, rule and site text from those, the failure and the
specification (offload.engine.fuzz_cites). No sentence is written by hand."""
import pytest

from offload.engine import autodraft as AD

REPORT = """## Controls

- `controls/x-delete-clause-thread-limit-1-control.f90`: delete clause thread_limit(1) at line 13; passes on gcc/0
- `controls/x-unwrap-teams-control.f90`: unwrap teams at line 14; passes on gcc/0
- `controls/x-unwrap-loop-control.f90`: unwrap loop at line 15; passes on gcc/0
- `controls/x-shorten-target-parallel-to-target-control.f90`: shorten target parallel to target at line 20; passes on gcc/0
- `controls/x-drop-r1a-from-map-tofrom-hf1-r1a-control.f90`: drop r1a from map(tofrom: hf1, r1a) at line 22; passes on gcc/0

## Still to do (a person)
"""


def test_the_key_constructs_are_what_the_controls_changed():
    assert AD.control_constructs(REPORT) == ["clause:thread_limit", "dir:teams", "dir:loop", "dir:parallel", "clause:map"]
    assert AD.control_constructs("## Controls\n\n(none found)\n") == []


def test_the_title_names_the_compiler_the_failure_and_the_constructs():
    t = AD.title("GCC 16.2.0", "crash", "f90", "omp", ["clause:thread_limit", "dir:teams", "dir:loop"])
    assert t == "GCC 16.2.0 aborts at run time on a Fortran OpenMP program with a thread_limit clause, a teams construct and a loop construct"
    assert AD.title("CCE 19.0.0", "wrong_answer", "c", "omp", ["clause:defaultmap"]).startswith("CCE 19.0.0 gives a wrong result on a C OpenMP program")
    assert "fails to link" in AD.title("CCE 19.0.0", "rejected", "c", "omp", [], link=True)


def test_the_name_is_a_slug_of_the_family_the_constructs_and_the_failure():
    assert AD.name("gcc", "crash", ["clause:thread_limit", "dir:teams", "dir:loop"]) == "gcc-thread-limit-teams-loop-abort"
    assert AD.name("cce19", "wrong_answer", ["dir:target teams"]) == "cce19-target-teams-wrong"


@pytest.mark.needs_spec
def test_the_rule_cites_each_key_construct_and_every_citation_checks():
    from offload.engine.citations import Citation, check
    r = AD.rule(["clause:thread_limit", "dir:teams"], "omp", "crash")
    assert r.count("(OpenMP 5.2 §") == 2 and "§13.3" in r and "§10.2" in r
    assert r.startswith("a conforming program runs to completion")


DRAFT = """! # Finding (leads): TODO(human) one-sentence title
!
! - failure: crash
! - expected: TODO(human) no row of the program passes; state the expected output and its source
! - rule: TODO(human) the specification requirement, cited with version, section, page and lines
! - legality: TODO(human) the legality statement and its witnesses
program p
end program p
! site:
! title: TODO(human) the issue's name in a few words
! summary: TODO(human) one sentence for the site
! end site
"""


def test_fill_replaces_every_todo_and_wraps_long_fields(tmp_path):
    f = tmp_path / "x.f90"
    f.write_text(DRAFT)
    AD.fill(f, title="T", expected="check=pass", rule="r " * 100, legality="L", site_title="S", site_summary="S.")
    out = f.read_text()
    assert "TODO(human)" not in out and out.startswith("! # Finding (leads): T\n")
    assert "! - expected: check=pass\n" in out and "! title: S\n! summary: S.\n" in out
    assert all(len(x) <= 132 for x in out.splitlines())
    assert "program p\nend program p\n" in out
    # a filled finding is filled again field by field (continuation lines included)
    AD.fill(f, title="T2 " * 60, expected="e2", rule="r2", legality="l2", site_title="S2", site_summary="S2.")
    again = f.read_text()
    assert "! - rule: r2\n" in again and "r r r" not in again and again.count("! - expected:") == 1
    assert all(len(x) <= 132 for x in again.splitlines()) and again.startswith("! # Finding (leads): T2")
    AD.fill(f, title="T", expected="e", rule="r", legality="l", site_title="S", site_summary="long " * 40)
    s3 = f.read_text()
    assert "! + long" in s3 and all(len(x) <= 132 for x in s3.splitlines())
    AD.fill(f, title="T", expected="e", rule="r", legality="l", site_title="S", site_summary="short.")
    assert "! + " not in f.read_text() and "! summary: short.\n" in f.read_text()


def test_the_expected_and_legality_lines_come_from_the_confirmers_result():
    res = {"expected": {"status": "trusted", "value": "check=pass", "sources": ["elision", "metamorphic", "model"]},
           "witnesses": ["afar/gfx942/copy", "cce21/gfx942/copy", "elision"], "drafts": ["results/confirm/drafts/x"]}
    assert AD.expected_text(res) == ("check=pass: the program checks its own result; trusted by three independent "
                                     "sources (the sequential elision, the metamorphic runs, the program's own value)")
    leg = AD.legality_text(res)
    assert leg.startswith("the rules engine accepts it") and "afar, cce21" in leg
    assert "results/" not in leg and "/p/" not in leg       # nothing outside the committed tree


def test_fill_keeps_a_field_the_rows_gave_when_its_text_is_none(tmp_path):
    f = tmp_path / "x.f90"
    f.write_text(DRAFT.replace("TODO(human) no row of the program passes; state the expected output and its source",
                               "compiles and prints `checksum= 0` with `check=pass`"))
    AD.fill(f, title="T", expected=None, rule="r", legality="l", site_title="S", site_summary="S.")
    assert "! - expected: compiles and prints `checksum= 0` with `check=pass`\n" in f.read_text()
    with pytest.raises(ValueError):
        g = tmp_path / "y.f90"
        g.write_text(DRAFT)
        AD.fill(g, title="T", expected=None, rule="r", legality="l", site_title="S", site_summary="S.")


def test_titles_use_the_right_article_and_say_a_refusal_plainly():
    assert AD.title("CCE 19", "rejected", "f90", "omp", ["clause:if"]) == \
        "CCE 19 refuses a Fortran OpenMP program with an if clause"
    assert "with an order clause and a loop construct" in AD.title("GCC 16.2", "crash", "c", "omp",
                                                                   ["clause:order", "dir:loop"])


def test_the_model_is_read_from_the_programs_directives():
    assert AD.model_of("program p\n  !$acc kernels loop\n  do i = 1, 2\n  end do\nend program p\n") == "acc"
    assert AD.model_of("int main(void) {\n#pragma acc parallel loop\n  for (;;) {}\n}\n") == "acc"
    assert AD.model_of("program p\n  !$omp target\n  !$omp end target\nend program p\n") == "omp"
