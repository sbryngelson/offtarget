"""The mechanical legality evidence of a finding (offload.engine.legality_mechanical): the rules engine,
the result hazards, a second witness of another compiler family and the source of the expected value,
all computed from the program and the committed rows, with no AI reading."""
from types import SimpleNamespace

from offload.engine import legality_mechanical as LM

PROG = """program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer :: a(8), i, hf
  hf = 1
  !$omp target map(tofrom: a, hf)
  hf = merge(1, 0, omp_is_initial_device())
  do i = 1, 8
    a(i) = i
  end do
  !$omp end target
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hf, ' check=', merge('pass', 'fail', sum(a) == 36)
end program p
"""


def cell(tc, state):
    return SimpleNamespace(tc=tc, state=state, target="mi300a", outcome="RUN_OK" if state == "correct" else "RUN_FAIL")


def test_another_family_that_runs_it_correctly_is_the_witness_and_the_expected_value():
    m = LM.evidence(PROG, "f90", "omp", "wrong_answer", [cell("cce21", "fails-like"), cell("afar", "correct")])
    assert m["rules"] == "accept" and m["witness"] == "accept" and m["expected"] == "other-family"
    assert m["hazards"] == []


def test_gcc_is_never_the_legality_witness_but_may_give_the_expected_value():
    m = LM.evidence(PROG, "f90", "omp", "wrong_answer", [cell("cce21", "fails-like"), cell("gcc", "correct")])
    assert m["witness"] == "same-family" and m["expected"] == "other-family"


def test_a_release_of_the_failing_family_is_no_witness():
    m = LM.evidence(PROG, "f90", "omp", "wrong_answer", [cell("cce21", "fails-like"), cell("cce19", "correct")])
    assert m["witness"] == "same-family"
    assert m["expected"] == "self-check"     # the program checks its own result


def test_the_rules_engine_verdict_and_reasons_are_recorded():
    racy = PROG.replace("  do i = 1, 8\n", "  !$omp parallel do\n  do i = 1, 8\n").replace("    a(i) = i\n", "    hf = i\n    a(i) = i\n")
    m = LM.evidence(racy, "f90", "omp", "wrong_answer", [])
    assert m["rules"] == "reject" and m["rules_why"]


def test_a_stored_front_end_accept_of_another_family_is_the_witness():
    rows = [{"finding": "x", "sha256": "s1", "checker": "afar-frontend", "family": "afar", "result": "accept"}]
    cells = [cell("cce21", "fails-like")]
    assert LM.evidence(PROG, "f90", "omp", "wrong_answer", cells, rows=rows, fid="x", sha="s1")["witness"] == "accept"
    # a row for an old source, or of a failing family, is no witness
    assert LM.evidence(PROG, "f90", "omp", "wrong_answer", cells, rows=rows, fid="x", sha="s2")["witness"] == "same-family"
    afar_fails = [cell("afar", "fails-like")]
    assert LM.evidence(PROG, "f90", "omp", "wrong_answer", afar_fails, rows=rows, fid="x", sha="s1")["witness"] == "same-family"
    rej = [{**rows[0], "result": "reject"}]
    assert LM.evidence(PROG, "f90", "omp", "wrong_answer", cells, rows=rej, fid="x", sha="s1")["witness"] == "reject"


def test_the_findings_that_need_a_front_end_run_are_those_without_a_witness_or_a_current_row():
    rows = [{"finding": "a", "sha256": "s", "checker": "afar-frontend", "family": "afar", "result": "accept"}]
    need = LM.needs_frontend({"a": ("s", {"cce"}), "b": ("s", {"cce"}), "c": ("s", {"afar"}), "d": ("t", set())},
                             rows, witnessed={"d"})
    assert need == ["b"]


def test_the_inputs_hash_changes_with_each_input_of_a_verdict():
    rows = [{"finding": "x", "sha256": "s", "checker": "afar-frontend", "result": "accept"}]
    base = ("s", "wrong_answer", [cell("cce21", "fails-like")], rows, "x", "code")
    h = LM.inputs_hash(*base)
    for i, other in enumerate(("t", "ice", [cell("cce21", "correct")], [{**rows[0], "result": "reject"}], "x", "code2")):
        if i == 4:
            continue
        changed = list(base); changed[i] = other
        assert LM.inputs_hash(*changed) != h, i
    assert LM.inputs_hash(*base[:3], rows + [{**rows[0], "finding": "y"}], "x", "code") == h   # another finding's row
