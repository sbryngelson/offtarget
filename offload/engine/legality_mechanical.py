"""The mechanical legality evidence of a finding, with no AI reading: the rules engine's verdict and
reasons (offload.engine.prerun.rules_witness), the result hazards (prerun.result_hazards), a second
witness of another compiler family and the source of the expected value, from the finding's cells in
the committed rows (offload.engine.site.matrix). offload.engine.legality_review.verdict reads it.

The second witness: a toolchain of a family that does not fail the program, other than GCC (never
evidence of legality), built and ran it correctly; or, on a compute node (``frontend=True``), AMD's
front end accepts it when AFAR is not a failing family. The expected value of a wrong answer: a run
of another family, GCC included (a value, not a legality claim), printed it ("other-family"); else the
program checks its own result ("self-check": a RESULT line with check=)."""
from __future__ import annotations

import re

NOT_A_WITNESS = {"gcc"}         # a family that is never evidence that a program is legal


def _family(tc: str) -> str:
    from offload.engine.site import matrix as M
    return M.VERSIONS[tc][0]


def evidence(text: str, lang: str, model: str, outcome: str, cells: list, frontend: bool = False) -> dict:
    from offload.engine import prerun
    ok, why = prerun.rules_witness((text, lang, model))
    rules = "accept" if ok else ("reject" if ok is False else "unreadable")
    hazards = prerun.result_hazards((text, lang, model))
    failing = {_family(c.tc) for c in cells if c.state == "fails-like"}
    others = [c for c in cells if c.state == "correct" and _family(c.tc) not in failing]
    witness = "accept" if any(_family(c.tc) not in NOT_A_WITNESS for c in others) else "same-family"
    if witness != "accept" and frontend and "afar" not in failing:
        f_ok, f_why = prerun.frontend_witness((text, lang, model))
        witness = {True: "accept", False: "reject"}.get(f_ok, "unavailable")
    if others:
        expected = "other-family"
    elif re.search(r"RESULT[^\n]*check=", text):
        expected = "self-check"
    else:
        expected = "none"
    return {"rules": rules, "rules_why": list(why)[:6], "hazards": hazards, "witness": witness,
            "expected": expected, "outcome": outcome, "failing": sorted(failing),
            "witnesses": sorted({c.tc for c in others})}
