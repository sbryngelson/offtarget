"""The comment headers tools/reduce.py writes on a reduction and its controls stay within Fortran's
132-character free-form line (tests/engine/test_findings.py checks every committed finding file)."""
from pathlib import Path
from types import SimpleNamespace

from offload.engine import reduce as RD

LONG = "x" * 60


def test_a_reduction_header_wraps_at_132_characters():
    res = SimpleNamespace(signature="ice: " + LONG * 3, lines_before=200, lines_after=20, steps=[1] * 9,
                          candidates_judged=99)
    tgt = [SimpleNamespace(label="cce21/0"), SimpleNamespace(label="cce19/0")]
    for lang, lead in (("f90", "!"), ("c", "//")):
        head = RD.reduction_header("n" * 50, "results/" + LONG, tgt, res, Path("results/reduce/" + LONG), lang, "rules_witness")
        assert all(len(ln) <= 132 and ln.startswith(lead) for ln in head.splitlines()), head


def test_a_control_header_wraps_at_132_characters():
    c = SimpleNamespace(what="delete clause independent at line 20", passed=["cce21/0", "cce19/0"])
    for lang, lead in (("f90", "!"), ("c", "//")):
        head = RD.control_header("cce-acc-kernels-nested-loop-reduction-lost", ".f90", c, lang, "rules_witness")
        assert all(len(ln) <= 132 and ln.startswith(lead) for ln in head.splitlines()), head
        assert "passes on cce21/0, cce19/0." in " ".join(ln[len(lead):].strip() for ln in head.splitlines())
