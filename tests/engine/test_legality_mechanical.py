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
    return SimpleNamespace(tc=tc, state=state, outcome="RUN_OK" if state == "correct" else "RUN_FAIL")


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
