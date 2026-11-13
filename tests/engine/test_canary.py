"""Canaries (offload.engine.canary, catalog/canaries.yaml)."""
import json
from pathlib import Path

import pytest

from offload.engine import canary as CN
from offload.engine import harness
from offload.engine.harness import Outcome, Result

ROOT = Path(__file__).resolve().parent.parent.parent


def rows_as_expected(tc: str, xnack: int = 1) -> list[dict]:
    spec = CN.load()
    out = []
    for kind, want in spec["toolchains"][tc].items():
        out.append({"canary": kind, "canary_program": want["program"],
                    "toolchain": tc, "xnack": xnack,
                    "outcome": want["outcome"],
                    "reason": (want.get("reason") or "") + " the rest"})
    return out


def test_canaries_cover_every_measured_toolchain():
    from offload.engine.confirm import machines as M
    spec = CN.load()
    want = {t for m in M.load().values() for t in m.toolchains}
    assert want <= set(spec["toolchains"])
    for name, p in spec["programs"].items():
        if "file" in p:
            assert (ROOT / p["file"]).is_file(), name
        else:
            assert CN.program(name).id == p["catalog"], name
    for tc, kinds in spec["toolchains"].items():
        assert set(kinds) == set(CN.KINDS), tc
        assert kinds["racy"]["outcome"] == "refused"
        assert kinds["hang"]["outcome"] == "wrong_answer" and \
            kinds["hang"]["reason"] == "timeout"
        assert kinds["pass"]["outcome"] == "correct_on_device"


def test_canaries_cover_every_registered_toolchain():
    """A regression toolchain (cce21_4) is no machine column, but the
    campaigns that run it (tools/campaigns/harvest.py harvest2) run the canaries of
    every toolchain they name and refuse one that has none."""
    from offload.engine.toolchains import TOOLCHAINS
    assert set(TOOLCHAINS) <= set(CN.load()["toolchains"])


def test_cce21_4_canaries_are_cce21s():
    """cce/21.0.4 is the same CCE 21 family as 21.0.3: the same five
    canary programs and outcomes (measured on Tuolumne,
    results/gate/canaries/tuolumne.cce21_4.jsonl)."""
    toolchains = CN.load()["toolchains"]
    assert toolchains["cce21_4"] == toolchains["cce21"]


def test_changed_canary_stops_report(tmp_path):
    rows = rows_as_expected("cce19") + rows_as_expected("afar")
    assert CN.check(rows) == []
    assert CN.require_unchanged(rows) == 10
    # a known wrong answer silently starts passing
    changed = [dict(r) for r in rows]
    w = next(r for r in changed if r["canary"] == "wrong" and
             r["toolchain"] == "cce19")
    w["outcome"], w["reason"] = "correct_on_device", "ran_on_host=0"
    bad = CN.check(changed)
    assert len(bad) == 1 and "wrong" in bad[0] and "cce19" in bad[0] and \
        "schedule-static" in bad[0]
    with pytest.raises(CN.CanaryChanged, match="not written"):
        CN.require_unchanged(changed)
    # a report writer stops before it writes anything
    run = tmp_path / "run"
    run.mkdir()
    (run / "canaries.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in changed))
    from offload.engine import fuzz_report
    md = tmp_path / "report.md"
    with pytest.raises(CN.CanaryChanged):
        fuzz_report.write_report(run, md)
    assert not md.exists()
    # the stress report reads canaries of its runs
    from offload.engine import stress_report as SR
    out = SR.OUT
    try:
        SR.OUT = tmp_path
        with pytest.raises(CN.CanaryChanged):
            SR.load(["run"])
        assert SR.load(["run"], canaries=False) == ({}, [])
    finally:
        SR.OUT = out
    # a matrix file's canaries (support table)
    m = tmp_path / "matrix.xnack1.jsonl"
    m.write_text("")
    (tmp_path / "matrix.xnack1.canaries.jsonl").write_text(
        (run / "canaries.jsonl").read_text())
    assert CN.files_for(m) == [tmp_path / "matrix.xnack1.canaries.jsonl"]
    # a hang the timeout did not end
    h = [dict(r) for r in rows]
    next(r for r in h if r["canary"] == "hang")["reason"] = "ran_on_host=0"
    assert any("hang" in b for b in CN.check(h))
    # a campaign recorded before canaries existed has none: nothing to stop
    assert CN.require_unchanged([{"program_id": "x", "outcome": "rejected"}
                                 ]) == 0


def test_racy_canary_refused_before_run(tmp_path):
    """The racy canary is never compiled: the pre-run check refuses it."""
    spec = CN.load()
    ran = []

    def runner(prog, tc, xnack, opt, timeout_s, repeats):
        ran.append(prog.id)
        kind = {"canary-hang": "hang"}.get(prog.id) or next(
            k for k, v in spec["toolchains"]["afar"].items()
            if CN.program(v["program"], spec).id == prog.id)
        want = spec["toolchains"]["afar"][kind]
        return Result(prog.id, prog.primary_atom, tuple(prog.atoms), "afar",
                      xnack, opt, Outcome(want["outcome"]),
                      (want.get("reason") or "x") + ": fake", False, "", None,
                      "", "")
    rows = CN.run_for("afar", 1, 120, spec, runner=runner,
                      tc=harness.Toolchain("afar", "", "false"))
    racy = next(r for r in rows if r["canary"] == "racy")
    assert racy["outcome"] == "refused"
    assert "race:" in racy["reason"] and " s is updated" in racy["reason"]
    assert "canary-racy" not in ran and len(ran) == 4
    assert CN.check(rows) == []


@pytest.mark.gpu
def test_hang_canary_ended_by_the_timeout():
    from offload.engine.toolchains import TOOLCHAINS, detect_gpu
    if detect_gpu()[0] != "gfx942":
        pytest.skip("needs an MI300A node")
    prog = CN.program("hang")
    r = harness.run_program(prog, TOOLCHAINS["afar"], 1, timeout_s=8,
                            repeats=1)
    row = {"canary": "hang", "toolchain": "afar", "xnack": 1,
           "outcome": str(r.outcome), "reason": r.reason}
    assert CN.check([row]) == []


def test_a_campaign_without_canaries_stops_its_report_unless_exempt(tmp_path):
    """A campaign recorded with
    provenance and no canary of a toolchain and mode it ran stops its
    report; an exemption with a reason lets it through; a toolchain absent
    from catalog/canaries.yaml is an error; a campaign recorded before
    (no provenance) has none and is not stopped."""
    new = [{"toolchain": "cce19", "xnack": 1, "git_rev": "abc"}]
    old = [{"toolchain": "cce19", "xnack": 1}]
    with pytest.raises(CN.CanaryMissing, match="missing"):
        CN.require_unchanged([], "x", campaign_rows=new)
    assert CN.require_unchanged([], "x", campaign_rows=old) == 0
    part = [r for r in rows_as_expected("cce19") if r["canary"] != "hang"]
    with pytest.raises(CN.CanaryMissing, match="hang missing on cce19"):
        CN.require_unchanged(part, "x", campaign_rows=new)
    assert CN.require_unchanged(rows_as_expected("cce19"), "x",
                                campaign_rows=new) == 5
    p = tmp_path / "canaries.jsonl"
    with pytest.raises(ValueError):
        CN.exempt(p, "  ")
    CN.exempt(p, "a probe campaign of one program")
    assert CN.require_unchanged([p], "x", campaign_rows=new) == 0
    with pytest.raises(CN.CanaryMissing, match="no canaries"):
        CN.require_unchanged([], "x", campaign_rows=[
            {"toolchain": "cce99", "xnack": 1, "git_rev": "abc"}])
    with pytest.raises(KeyError):
        CN.add_to_campaign(tmp_path / "c.jsonl", ["cce99"], [1])
    # a merged file of old and new runs: only the cells recorded with provenance need canaries
    mixed = old + [{"toolchain": "afar_mi350x", "xnack": 0, "git_rev": "abc"}]
    with pytest.raises(CN.CanaryMissing, match="afar_mi350x") as e:
        CN.require_unchanged([], "x", campaign_rows=mixed)
    assert "cce19" not in str(e.value)
    assert CN.require_unchanged(rows_as_expected("afar_mi350x", 0), "x", campaign_rows=mixed) == 5
