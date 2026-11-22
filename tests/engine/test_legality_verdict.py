"""The legality verdict from mechanical evidence and people (offload.engine.legality_review.verdict):
the rules engine, a front end or build of another compiler family, the result hazards, an independent
source of the expected value, a maintainer's ruling and outside evidence. AI readings never decide it
(they are kept as ``advisory``)."""
from offload.engine import legality_review as L

GOOD = {"rules": "accept", "witness": "accept", "hazards": [], "expected": "other-family", "outcome": "wrong_answer"}
YES = {"legal": "yes", "result_required": "yes", "batch_decoy": "caught", "instructions": L.INSTRUCTIONS,
       "quotes": {"ok": 1}, "program": {"ok": 1}}
NO = {**YES, "legal": "no"}


def rec(**kw):
    return {"mechanical": {**GOOD, **kw.pop("mech", {})}, **kw}


def test_rules_witness_and_an_independent_expected_value_check_a_finding():
    assert L.verdict(rec()) == "checked"
    for source in ("self-check", "generator-model"):
        assert L.verdict(rec(mech={"expected": source})) == "checked"


def test_a_refusal_or_compile_crash_needs_no_expected_value():
    for outcome in ("rejected", "ice"):
        assert L.verdict(rec(mech={"outcome": outcome, "expected": "none"})) == "checked"
    assert L.verdict(rec(mech={"outcome": "wrong_answer", "expected": "none"})) == "open"


def test_the_rules_engine_or_a_result_hazard_refutes():
    assert L.verdict(rec(mech={"rules": "reject"})) == "refuted"
    assert L.verdict(rec(mech={"hazards": ["omp-unmapped-scalar-reduction: d ..."]})) == "refuted"
    # a result hazard is about the expected value: a refusal does not depend on one
    assert L.verdict(rec(mech={"hazards": ["omp-unmapped-scalar-reduction: d ..."], "outcome": "rejected",
                               "expected": "none"})) == "checked"


def test_without_a_second_witness_of_another_family_a_finding_is_open():
    for w in ("same-family", "unavailable", "reject"):
        assert L.verdict(rec(mech={"witness": w})) == "open"
    assert L.verdict({}) == "open"


def test_ai_readings_never_decide():
    assert L.verdict(rec(readers=[NO, NO])) == "checked"
    assert L.verdict(rec(mech={"witness": "same-family"}, readers=[YES, YES])) == "open"
    assert L.advisory(rec(readers=[YES, YES])) == "confirmed"


def test_a_ruling_comes_first_and_outside_evidence_settles_an_open_finding():
    ruling = {"ruling": {"quotes": {"ok": 1, "not_found": 0, "wrong_section": 0}}}
    assert L.verdict(rec(mech={"rules": "reject"}, **ruling)) == "ruled"
    assert L.verdict(rec(mech={"witness": "same-family"}, external=[{"source": "vendor"}])) == "supported"
    assert L.verdict(rec(mech={"rules": "reject"}, external=[{"source": "vendor"}])) == "refuted"


def test_every_verdict_has_words():
    assert set(L.WORDS) == set(L.VERDICTS) and set(L.VERDICTS) == {"ruled", "refuted", "supported", "checked", "open"}
