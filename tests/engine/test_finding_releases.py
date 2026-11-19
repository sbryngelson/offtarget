"""The generated `releases` line of a finding header (offload/engine/finding_releases.py)."""
from offload.engine import finding_header as H
from offload.engine import finding_releases as FR
from offload.engine.site.matrix import Cell

T = ("mi300a-u", "mi300a-c", "mi250x", "mi300x", "mi350x")


def cells(tc, state, targets=T):
    return [Cell(tc, "", t, state) for t in targets]


def test_two_releases_that_fail_alike_are_one_clause():
    cs = cells("afar", "fails-like") + cells("afar244", "fails-like")
    assert FR.value("x", cs) == "AFAR 24.3.0 and 24.4.0 fail it the same way"


def test_a_fixed_release_is_named_with_what_it_does():
    cs = cells("afar", "fails-like") + cells("afar244", "correct")
    assert FR.value("x", cs) == "AFAR 24.3.0 fails it the same way; AFAR 24.4.0 runs it correctly"


def test_targets_that_disagree_are_listed():
    cs = cells("afar", "fails-like", T[:1]) + cells("afar", "correct", T[1:2]) + \
        cells("afar244", "fails-like")
    assert FR.value("x", cs) == ("AFAR 24.3.0 fails it the same way on MI300A unified and runs it "
                                 "correctly on MI300A copy; AFAR 24.4.0 fails it the same way")


def test_a_family_without_the_failure_or_with_one_release_is_left_out():
    # NVHPC runs it correctly in both releases (not the finding's family); GCC is one release
    cs = cells("afar", "fails-like") + cells("afar244", "fails-like") + \
        cells("nvhpc", "correct", ("a100-s",)) + cells("nvhpc269", "correct", ("a100-s",)) + \
        cells("gcc", "fails-like", ("mi250x",)) + cells("gcc_sm80", "correct", ("a100-s",))
    assert FR.value("x", cs) == "AFAR 24.3.0 and 24.4.0 fail it the same way"
    assert FR.value("x", cells("afar", "fails-like")) is None
    assert FR.value("x", cells("afar", "unknown") + cells("afar244", "na")) is None


def test_the_line_names_the_releases_it_is_about():
    ms = H.mentions("AFAR 24.3.0 and 24.4.0 fail it the same way; CCE 21.0.3 runs it correctly")
    assert [(m.family, m.tcs) for m in ms] == [("afar", ("afar", "afar244")), ("cce", ("cce21",))]


SRC = """! # Finding (x): title
!
! - toolchains and modes that fail: afar; modes: unified, copy
! - build: amdflang -fopenmp
!   --offload-arch=gfx942
! - expected: ok
!
! more text
program p
end program
"""


def test_the_bullet_goes_after_the_first_bullets_and_is_replaced_in_place():
    once = FR.apply(SRC, "AFAR 24.3.0 and 24.4.0 fail it the same way")
    lines = once.splitlines()
    assert lines[6] == "! - releases: AFAR 24.3.0 and 24.4.0 fail it the same way" and lines[7] == "!"
    assert H.parse(once).get("releases") == "AFAR 24.3.0 and 24.4.0 fail it the same way"
    long = "; ".join(["AFAR 24.3.0 fails it the same way on MI300A unified and runs it correctly"] * 3)
    twice = FR.apply(once, long)
    assert twice.count("- releases:") == 1 and H.parse(twice).get("releases") == long
    assert FR.apply(twice, FR.value("x", [])) == SRC == FR.strip(twice)
    assert FR.apply(twice, long) == twice


def test_a_prose_header_gets_the_line_at_its_end_and_a_file_without_one_is_left_alone():
    src = "// Schedule(static) in a target region:\n// prose.\nint main() { return 0; }\n"
    out = FR.apply(src, "AFAR 24.3.0 and 24.4.0 fail it the same way")
    assert out.splitlines()[2] == "// - releases: AFAR 24.3.0 and 24.4.0 fail it the same way"
    assert FR.strip(out) == src
    bare = "int main() { return 0; }\n"
    assert FR.apply(bare, "AFAR 24.3.0 and 24.4.0 fail it the same way") == bare


def test_a_quoted_block_inside_a_bullet_stays_whole():
    src = ("// # Finding (x): t\n//\n// - rule: a patch\n//       @@ -1 +1 @@\n//       \n"
           "//       +   fence();\n//\nint x;\n")
    out = FR.apply(src, "AFAR 24.3.0 fails it the same way; AFAR 24.4.0 runs it correctly")
    assert out.splitlines()[6].startswith("// - releases:") and FR.strip(out) == src
