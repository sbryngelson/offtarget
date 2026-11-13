"""tools/repo/check_findings.py: every finding's header claims against the recorded rows, with a ratchet
(catalog/findings_claims_baseline.yaml may only shrink)."""
import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
spec = importlib.util.spec_from_file_location("check_findings", ROOT / "tools" / "repo" / "check_findings.py")
CF = importlib.util.module_from_spec(spec)
sys.modules["check_findings"] = CF
spec.loader.exec_module(CF)

from offload.engine.finding_claims import Violation  # noqa: E402


def V(f, c, r="why"):
    return Violation(f, c, r)


def entry(f, c, mode="committed"):
    return {"finding": f, "claim": c, "reason": "r", "mode": mode}


def test_a_violation_outside_the_baseline_is_new():
    new, stale = CF.compare([V("a.c", "control x"), V("b.c", "other-families afar")],
                            [entry("a.c", "control x")], "full")
    assert [v.key for v in new] == [("b.c", "other-families afar")] and stale == []


def test_a_fixed_baseline_entry_is_stale_in_full_mode():
    new, stale = CF.compare([], [entry("a.c", "control x", "full")], "full")
    assert new == [] and [e["claim"] for e in stale] == ["control x"]


def test_committed_mode_only_judges_entries_it_can_decide():
    base = [entry("a.c", "control x", "full"), entry("b.c", "gate-envs afar mi300a-u", "committed")]
    new, stale = CF.compare([], base, "committed")
    assert [e["finding"] for e in stale] == ["b.c"]


def test_a_todo_is_never_baselined():
    with pytest.raises(SystemExit):
        CF.write_baseline_entries([V("a.c", "todo line 3")], [V("a.c", "todo line 3")], Path("/dev/null"))


def test_baseline_entries_record_the_mode_that_decides_them():
    full = [V("a.c", "control x"), V("b.c", "control y")]
    committed = [V("a.c", "control x")]
    es = CF.baseline_entries(full, committed)
    assert {e["finding"]: e["mode"] for e in es} == {"a.c": "committed", "b.c": "full"}
    assert all(e["reason"] for e in es)


def test_every_finding_file_is_listed_once_and_controls_are_not():
    rels = CF.finding_files()
    assert rels and len(rels) == len(set(rels))
    assert not any("/controls/" in r for r in rels)
    assert "afar-cce19-character-defaultmap.f90" in rels
    assert any(r.startswith("nested/") for r in rels)


def test_a_draft_with_an_unresolved_todo_fails_the_findings_checks(tmp_path):
    d = tmp_path / "data" / "findings"
    d.mkdir(parents=True)
    (d / "x.c").write_text("// # Finding (t): TODO(human) title\n#include <stdio.h>\nint main(void){return 0;}\n")
    assert CF.todo_problems(d, [])[0].startswith("x.c:1")


def test_todo_in_the_index_or_the_readme_fails(tmp_path):
    f = tmp_path / "other.md"
    f.write_text("| `x.c` | TODO(human) |\n")
    assert CF.todo_problems(tmp_path / "none", [f])[0].startswith("other.md:1")


def test_the_baseline_is_well_formed():
    data = yaml.safe_load(CF.BASELINE.read_text())
    seen = set()
    for e in data["violations"]:
        assert set(e) == {"finding", "claim", "reason", "mode"}, e
        assert e["mode"] in ("committed", "full")
        assert not e["claim"].startswith("todo")
        assert (e["finding"], e["claim"]) not in seen
        seen.add((e["finding"], e["claim"]))
        assert (CF.FINDINGS / e["finding"]).is_file(), e["finding"]


def test_no_finding_holds_a_todo_and_the_claims_match_the_baseline():
    mode = CF.detect_mode()
    if mode == "none":
        pytest.skip("no recorded rows to check against")
    found = CF.collect(mode=mode)
    new, stale = CF.compare(found, CF.load_baseline(), mode)
    assert not new, "claims with no recorded row behind them (not in the baseline):\n" + \
        "\n".join(f"  {v.finding}: {v.claim}: {v.reason}" for v in new[:40])
    assert not stale, "baseline entries that no longer hold (remove them):\n" + \
        "\n".join(f"  {e['finding']}: {e['claim']}" for e in stale[:40])
    assert CF.todo_problems() == []


def test_committed_violations_are_a_subset_of_the_full_ones():
    if CF.detect_mode() != "full":
        pytest.skip("full mode: the campaign rows are on Tuolumne (left for it)")
    full = {v.key for v in CF.collect(mode="full")}
    committed = {v.key for v in CF.collect(mode="committed")}
    assert committed <= full, sorted(committed - full)[:10]
