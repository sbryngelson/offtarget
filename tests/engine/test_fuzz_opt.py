"""The fuzz campaign's optimization level (tools/campaigns/fuzz.py run --opt): a run records the level
it builds with, a resumed run keeps it, and the minimizer rebuilds at the run's level."""
import importlib.util
import json
from types import SimpleNamespace

import pytest

from offload.engine import fuzz_exec
from offload.engine.root import ROOT


def _fuzz_cli(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("fuzz_cli", ROOT / "tools" / "campaigns" / "fuzz.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(fuzz_exec, "OPT", fuzz_exec.OPT)       # put back after the test
    from offload.engine import canary, harness, toolchains
    monkeypatch.setattr(harness, "detect_thp", lambda: "never")
    monkeypatch.setattr(toolchains, "compiler_version", lambda tc: "v")
    monkeypatch.setattr(canary, "add_to_campaign", lambda *a, **k: [])
    seen = {}
    monkeypatch.setattr(fuzz_exec, "campaign", lambda out, seeds, *a, **k: seen.setdefault("opt", fuzz_exec.OPT))
    return cli, seen


def _run_args(**kw):
    a = dict(run_id="r", gen_version="fuzz-4", base_features=None, seeds=[1, 2], start=1, count=2,
             toolchains=["gcc"], workers=1, reruns=1, xnack=0, canaries_exempt=None, opt="-O2")
    a.update(kw)
    return SimpleNamespace(**a)


def test_a_run_builds_at_its_optimization_level_and_records_it(tmp_path, monkeypatch):
    cli, seen = _fuzz_cli(tmp_path, monkeypatch)
    assert cli.cmd_run(_run_args(opt="-O3")) == 0
    assert seen["opt"] == "-O3"
    meta = json.loads((tmp_path / "results" / "fuzz" / "r" / "meta.json").read_text())
    assert meta["sessions"][-1]["opt"] == "-O3"


def test_a_resumed_run_keeps_its_optimization_level(tmp_path, monkeypatch):
    """A second session at another level would mix two levels in one programs.jsonl."""
    cli, seen = _fuzz_cli(tmp_path, monkeypatch)
    assert cli.cmd_run(_run_args(opt="-O3")) == 0
    assert cli.cmd_run(_run_args(opt="-O3")) == 0
    with pytest.raises(SystemExit, match="-O3"):
        cli.cmd_run(_run_args(opt="-O0"))


def test_the_minimizer_rebuilds_at_the_runs_level(tmp_path, monkeypatch):
    cli, _ = _fuzz_cli(tmp_path, monkeypatch)
    cli.cmd_run(_run_args(opt="-O0"))
    monkeypatch.setattr(fuzz_exec, "OPT", "-O2")
    got = {}
    monkeypatch.setattr(cli.fuzz_report, "minimize_run", lambda *a, **k: got.setdefault("opt", fuzz_exec.OPT))
    cli.cmd_minimize(SimpleNamespace(run_id="r", xnack=None, only=None, workers=1, limit=4, also=None))
    assert got["opt"] == "-O0"
