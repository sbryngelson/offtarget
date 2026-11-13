"""Tests of the campaign interface and runner, the gate's review queue, the GCC 16.2 campaigns and findings, the generic reducer and the vendor checks' runner."""
from __future__ import annotations


# ---- The campaign interface (offload/engine/campaign.py), the generic runner -----------------------------

import where
import importlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from offload.engine import campaign as C
from offload.engine import gate as GT
from offload.engine import toolchains as T
from tests import toolchain_scan as SCAN

ROOT = Path(__file__).resolve().parent.parent.parent


def _tool():
    spec = importlib.util.spec_from_file_location("campaign_tool", ROOT / "tools" / "campaign.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# --- the toy campaign and its fake runner --------------------------------------------

@pytest.fixture
def toy():
    """The registry entry of the toy campaign, for the test's duration."""
    C.MODULES["toy"] = "tests.toy_campaign"
    try:
        yield C.get("toy")
    finally:
        C.unregister("toy")


class FakeRunner:
    """offload.engine.campaign's runner interface without a compiler: a
    program fails on the toolchains of `bad` (a wrong answer whose printed
    value differs), passes elsewhere; every rerun reproduces the stored
    outcome; (c) runs on another node."""
    parallel = "thread"

    def __init__(self, bad: dict):
        self.bad = bad          # (program id, toolchain) -> True
        self.runs = 0
        self.reruns = []

    def prerun(self, p) -> dict:
        return {"id": p.id, "ok": True, "reasons": [], "rules": True,
                "rules_why": [], "afar_fe": True, "afar_why": []}

    def witness(self, p) -> dict:
        return {"program": p.id, "sha256": C.sha256(p.source), "checker": "fake",
                "result": "accept", "message": ""}

    def _row(self, prog, toolchain, xnack, opt, node):
        from offload.engine.reduce import fake_row
        tgt = SimpleNamespace(toolchain=toolchain, mode=xnack, opt=opt,
                              label=f"{toolchain}/{xnack}")
        cls = "wrong_answer" if self.bad.get((prog.id, toolchain)) else "correct"
        row = fake_row(cls, prog.source, tgt, program_id=prog.id)
        row.update(lang=prog.lang, node=node, machine="fake", arch="x")
        return row

    @staticmethod
    def here() -> str:
        """The node this fake runs on: offload.engine.provenance.node (the tests
        monkeypatch it to move between nodes)."""
        from offload.engine import provenance
        return provenance.node()

    def run(self, prog, toolchain, xnack, *, version, timeout_s, opt="-O2"):
        self.runs += 1
        return self._row(prog, toolchain, xnack, opt, self.here())

    def rerun(self, prog, toolchain, xnack, env, *, version, timeout_s, opt="-O2"):
        self.reruns.append(env["env"])
        row = self._row(prog, toolchain, xnack, opt, self.here())
        return {"env": env["env"], "path": env["path"], "node": row["node"],
                "repeat": env.get("repeat", 0), "seconds": 0.1, "date": "2026-11-03",
                "outcome": row["outcome"], "reason": row["reason"], "flaky": False,
                "stdout": row["stdout"], "toolchain_build": "fake 1.0",
                "build_dir": env["path"], "git_rev": "", "compile_log": row["stderr"]}


def test_the_toy_campaign_is_one_module_and_a_registry_entry(toy):
    """Nothing but tests/toy_campaign.py and the MODULES entry: the gate kind,
    its value signature and compile limit are declared by registering."""
    assert C.names()[-1] == "toy" and toy.name == "toy"
    assert GT.KINDS["toy"] == {"prefix": "toy_", "signature": "program"}
    assert "toy" in GT.VALUE_KINDS and GT.COMPILE_LIMIT_S["toy"] == 900
    assert toy.check() == []
    tg = toy.caps.targets()
    reg = T.registry()
    assert set(tg) == {"tuolumne", "wingtip"}
    assert tg["tuolumne"][0] == [n for n in reg.of_machine("tuolumne")]
    assert tg["wingtip"][1] == sorted(reg.toolchains["nvhpc"].xnack_modes)
    # deterministic programs
    assert [p.id for p in toy.programs(3, 2)] == [p.id for p in toy.programs(3, 2)]
    assert toy.programs(3, 2, step=2)[2].id == "toy-f90-5"


@pytest.fixture
def nodes(monkeypatch):
    """The fake machine's nodes: `at("node-a")` moves the runner (and
    offload.engine.provenance.node, which the gate's placement reads)."""
    from offload.engine import provenance
    state = {"node": "node-a"}
    monkeypatch.setattr(provenance, "node", lambda: state["node"])

    def at(node: str) -> None:
        state["node"] = node
    return at


def test_toy_campaign_end_to_end_through_the_generic_runner(toy, tmp_path, nodes):
    T_ = _tool()
    results = tmp_path / "results"
    reg = T.registry()
    tcs = reg.of_machine("tuolumne")
    cce = [t for t in tcs if reg.toolchains[t].family_id == "cce"]
    ids = [p.id for p in toy.programs(3, 3)]
    bad = {(ids[0], t): True for t in cce}          # the first program fails on CCE
    bad[(ids[4], cce[0])] = True                    # an unspecified program too (observation)
    fake = FakeRunner(bad)

    def go(*args):
        return T_.main(["--results", str(results), "toy", *args], runner=fake)

    assert go("gen", "--name", "t", "--n", "3", "--seed", "3") == 0
    d = results / "toy" / "t"
    meta = json.loads((d / "meta.json").read_text())
    assert meta == {"n": 3, "seed": 3}
    rows = [json.loads(ln) for ln in (d / "programs.jsonl").read_text().splitlines()]
    assert [r["id"] for r in rows] == ids and all("sha" in r for r in rows)
    assert (d / "src" / f"{ids[1]}.c").is_file() and (d / "src" / f"{ids[0]}.f90").is_file()
    # the draw is regenerated and checked on every later command
    run = C.Run(toy, d)
    assert [p.id for p in run.programs()] == ids
    # prerun and witness through the fake runner; legality is legal everywhere
    assert go("prerun", "--name", "t", "--workers", "2") == 0
    assert len(C.read_jsonl(d / "prerun.jsonl")) == len(ids)
    assert go("witness", "--name", "t") == 0
    assert go("legality", "--name", "t") == 0
    leg = json.loads((d / "legality.json").read_text())
    assert all(all(r["legal_for"].values()) for r in leg.values())
    # the run: every (program, toolchain, mode) of the machine, resumable
    assert go("run", "--name", "t", "--machine", "tuolumne", "--workers", "2") == 0
    cells = {(r["program_id"], r["toolchain"], r["xnack"]) for r in run.rows()}
    assert len(cells) == len(ids) * len(tcs) * 2 and fake.runs == len(cells)
    assert go("run", "--name", "t", "--machine", "tuolumne") == 0
    assert fake.runs == len(cells)                  # nothing run twice
    r0 = next(r for r in run.rows() if r["program_id"] == ids[0] and r["toolchain"] == cce[0])
    assert r0["outcome"] == "wrong_answer" and r0["campaign"] == "toy"
    assert r0["expected"] == {"r": 8} and r0["observed"] == {"r": 0}
    assert r0["mode"] == ("copy" if r0["xnack"] == 0 else "unified")
    # the gate: only defined programs' failures are items; (a, b, d) on the
    # row's node, then (c) on another node (the rule the gate stands on)
    items = run.gate_items()
    assert {it["ident"] for it in items} == {ids[0]}
    assert all(it["kind"] == "toy" and it["cell"].startswith("toy|") for it in items)
    gate_root = str(tmp_path / "gate")
    assert go("gate", "--name", "t", "--machine", "tuolumne", "--envs", "a,b,d",
              "--node", "same", "--root", gate_root) == 0
    assert sorted(set(fake.reruns)) == ["a", "b", "d"]
    n_abd = len(fake.reruns)
    # (c) asked for on the node of (a): the placement takes nothing
    assert go("gate", "--name", "t", "--machine", "tuolumne", "--envs", "c",
              "--node", "other", "--root", gate_root) == 0
    assert len(fake.reruns) == n_abd
    nodes("node-b")
    assert go("gate", "--name", "t", "--machine", "tuolumne", "--envs", "c",
              "--node", "other", "--root", gate_root) == 0
    assert sorted(set(fake.reruns)) == ["a", "b", "c", "d"]
    reruns = C.read_jsonl(d / "gate_reruns.jsonl")
    by_cell = {}
    for r in reruns:
        by_cell.setdefault(r["cell"], {}).setdefault(r["env"], set()).add(r["node"])
    assert len(by_cell) == len(items)
    for cell, envs in by_cell.items():
        assert envs["a"] == envs["b"] == envs["d"] == {"node-a"}, cell
        assert envs["c"] == {"node-b"}, cell
        assert envs["c"].isdisjoint(envs["a"]), f"{cell}: (c) ran on the node of (a)"
    v = run.verdicts()
    assert v and all(x["verdict"] == "confirmed" and x["own"] for x in v.values())
    assert all(x["node_distinct"] for x in v.values())
    nodes("node-a")
    # the report and the clusters
    assert go("report", "--name", "t") == 0
    matrix = (d / "matrix.md").read_text()
    assert "WA*" in matrix and f"| {ids[0]} |" in matrix
    summary = run.summary()
    assert summary["gate"] == {"confirmed": len(cce) * 2}
    assert go("cluster", "--name", "t") == 0
    cs = json.loads((d / "clusters.json").read_text())
    assert cs and cs[0]["signature"] == "wrong:r" and cs[0]["confirmed"] >= 1
    # the confirmer (stored evidence only) and the findings plan
    verdicts_file = GT.VERDICTS_FILE
    assert go("confirm", "--name", "t") == 0
    # the confirmer points the gate at the run's own verdicts only while it runs: a later load_verdicts()
    # in the same process must still read results/verdicts.jsonl (a leak made every later gate "not_gated")
    assert GT.VERDICTS_FILE == verdicts_file
    conf = C.read_jsonl(d / "confirm.jsonl")
    assert {o["program"] for o in conf} == {ids[0]}
    assert all(o["gate"] == "confirmed" and o["legality"] == "legal" for o in conf)
    assert all(o["verdict"] != "error" for o in conf), conf
    assert go("findings-plan", "--name", "t") == 0
    plan = (d / "findings_plan.md").read_text()
    assert "tools/new_finding.py" in plan and ids[0] in plan and "--campaign toy" in plan


def test_gate_c_on_the_node_of_a_is_no_evidence(toy, tmp_path, nodes):
    """A (c) rerun on the node that ran (a) is not another node: the judge
    leaves the cell without a verdict (the plan must put them apart)."""
    results = tmp_path / "results"
    reg = T.registry()
    cce = [t for t in reg.of_machine("tuolumne") if reg.toolchains[t].family_id == "cce"]
    ids = [p.id for p in toy.programs(1, 1)]
    fake = FakeRunner({(ids[0], cce[0]): True})
    run = C.Run(toy, results / "toy" / "t")
    run.gen(1, 1)
    run.prerun(fake, workers=1, log=lambda *a: None)
    run.run("tuolumne", fake, toolchains=[cce[0]], modes=[0], log=lambda *a: None)
    # every environment on one node: no placement asked for
    run.gate("tuolumne", fake, envs="a,b,c,d", root=str(tmp_path / "g"), log=lambda *a: None)
    v = run.verdicts()
    assert len(v) == 1
    rec = next(iter(v.values()))
    assert not rec["node_distinct"] and "c" not in rec["envs"]


def test_the_runner_refuses_a_machine_the_campaign_does_not_measure(toy, tmp_path):
    T_ = _tool()
    with pytest.raises(SystemExit):
        T_.main(["--results", str(tmp_path), "toy", "run", "--name", "t", "--machine", "tioga"],
                runner=FakeRunner({}))


def test_gen_refuses_an_undeclared_draw_option(toy, tmp_path):
    with pytest.raises(ValueError):
        C.Run(toy, tmp_path / "x").gen(1, 2, bogus=3)


def test_a_campaign_the_catalog_cannot_satisfy_is_refused_with_the_reason(monkeypatch):
    class Bad(C.Campaign):
        name = "bad"
        caps = C.Capabilities(("f90",), ("omp",), families={"mars": None, "wingtip": ("intel",)})

        def programs(self, seed=0, n=0, **opts):
            return []
    with pytest.raises(ValueError) as e:
        C.register(Bad())
    msg = str(e.value)
    assert "machine mars is not in catalog/machines.yaml" in msg
    assert "family intel is not in catalog/toolchains.yaml" in msg
    assert "no toolchain of wingtip compiles the campaign" in msg
    assert "bad" not in C.names()
    # the command line reports it instead of a traceback
    monkeypatch.setattr(C, "get", lambda name: (_ for _ in ()).throw(ValueError("campaign bad: x")))
    with pytest.raises(SystemExit) as se:
        _tool().main(["list"])
    assert "refused: campaign bad: x" in str(se.value)


# --- the confirmer's legality keys on the label, never on gating -----------

def test_an_unspecified_program_s_cell_is_never_legal_for_the_confirmer():
    """oop gates every program; the confirmer still gets legality `unknown`
    for an unspecified program's cell, whatever the witnesses say."""
    oop = C.get("oop")
    ps = oop.programs()
    unspec = [p for p in ps if p.legality == "unspecified"]
    defined = [p for p in ps if p.legality == "defined"]
    assert unspec and defined
    reg = T.registry()
    cce = next(t for t in reg.of_machine("tuolumne") if reg.toolchains[t].family_id == "cce")
    every = {f: True for f in reg.families}
    leg = {p.id: {"legal_for": every, "afar_fe": True, "nvhpc_fe": True, "cce_fe": None}
           for p in ps}
    run = C.Run(oop, Path("/nonexistent"))
    for p in unspec:
        assert oop.gated(p)
        st = run.cell_legality(p, cce, leg)
        assert st.status == "unknown" and p.why[:40] in st.basis, p.id
    st = run.cell_legality(defined[0], cce, leg)
    assert st.status == "legal"


def test_confirm_labels_an_unspecified_cell_unknown_even_when_gated(toy, tmp_path, nodes):
    """The toy with every program gated (oop's shape): the unspecified
    program's failing cells are confirmed with legality unknown, never a
    compiler bug."""
    T_ = _tool()

    class ToyAll(type(toy)):
        name = "toyall"

        def gated(self, p):
            return True
    C.register(ToyAll())
    try:
        results = tmp_path / "results"
        reg = T.registry()
        cce = [t for t in reg.of_machine("tuolumne") if reg.toolchains[t].family_id == "cce"]
        ids = [p.id for p in toy.programs(3, 3)]
        unspec = [p.id for p in toy.programs(3, 3) if p.legality == "unspecified"]
        assert unspec
        fake = FakeRunner({(pid, t): True for pid in unspec for t in cce})

        def go(*args):
            return T_.main(["--results", str(results), "toyall", *args], runner=fake)
        assert go("gen", "--name", "t", "--n", "3", "--seed", "3") == 0
        assert go("prerun", "--name", "t", "--workers", "2") == 0
        assert go("witness", "--name", "t") == 0
        assert go("run", "--name", "t", "--machine", "tuolumne", "--workers", "2") == 0
        d = results / "toyall" / "t"
        run = C.Run(C.get("toyall"), d)
        assert {it["ident"] for it in run.gate_items()} == set(unspec)   # gated, as oop does
        assert go("gate", "--name", "t", "--machine", "tuolumne", "--envs", "a,b,d",
                  "--node", "same", "--root", str(tmp_path / "g")) == 0
        nodes("node-b")
        assert go("gate", "--name", "t", "--machine", "tuolumne", "--envs", "c",
                  "--node", "other", "--root", str(tmp_path / "g")) == 0
        assert go("confirm", "--name", "t") == 0
        conf = C.read_jsonl(d / "confirm.jsonl")
        assert {o["program"] for o in conf} == set(unspec) and len(conf) == len(unspec) * len(cce) * 2
        assert all(o["gate"] == "confirmed" for o in conf)
        assert all(o["legality"] == "unknown" for o in conf), conf
        assert not any(o["verdict"] == "compiler_bug" for o in conf), conf
        assert ids[0] not in {o["program"] for o in conf}
    finally:
        C.unregister("toyall")
        nodes("node-a")


OOP_MAIN = ROOT / "results" / "oop" / "main"


@pytest.mark.skipif(not (OOP_MAIN / "confirm.jsonl").is_file(),
                    reason="results/oop/main (git-ignored) is not here")
def test_oop_confirm_over_the_stored_run_equals_the_recorded_output(tmp_path):
    """`oop confirm --name main` over a copy of the stored inputs gives, per
    case, the outcome, gate verdict and legality that master's tools/campaigns/oop.py
    recorded in results/oop/main/confirm.jsonl (498 cases; the unspecified
    programs' 46 cells with legality unknown). The confirmer's verdict,
    rule and finding links are not compared: they follow the findings
    index and the confirmer's rules, which moved since that file was
    written (2026-10-29)."""
    import shutil
    d = tmp_path / "results" / "oop" / "main"
    d.mkdir(parents=True)
    shutil.copytree(OOP_MAIN / "src", d / "src")
    for p in OOP_MAIN.iterdir():
        if p.is_file() and p.name.startswith(("programs", "prerun", "witness", "rows",
                                              "gate_reruns", "confirm_evidence")):
            shutil.copy2(p, d / p.name)        # the parts' mtime order decides the row order
    run = C.Run(C.get("oop"), d, "results/oop/main")
    run.confirm(log=lambda *a: None)
    keys = ("program", "toolchain", "mode", "outcome", "gate", "legality")

    def cells(text):
        return [tuple(o[k] for k in keys) for o in map(json.loads, text.splitlines())]
    got = cells((d / "confirm.jsonl").read_text())
    want = cells((OOP_MAIN / "confirm.jsonl").read_text())
    assert len(got) == len(want) == 498
    assert sorted(got) == sorted(want)
    rows = [json.loads(ln) for ln in (d / "confirm.jsonl").read_text().splitlines()]
    unspec = {p.id for p in C.get("oop").programs() if p.legality != "defined"}
    assert sum(1 for o in rows if o["program"] in unspec) == 46
    assert all(o["legality"] == "unknown" for o in rows if o["program"] in unspec)
    assert not any(o["verdict"] == "compiler_bug" for o in rows if o["legality"] == "unknown")


# --- the registered campaigns ----------------------------------------------------------

def _module_hits(mod_name: str) -> list[str]:
    mod = importlib.import_module(mod_name)
    pat = SCAN.pattern()
    return [t for _, t in SCAN.code_text(Path(mod.__file__)) if pat.search(t)]


@pytest.mark.parametrize("name", sorted(C.MODULES))
def test_registered_campaigns_declare_toolchains_through_the_catalog_only(name):
    """No registered toolchain id or version in a campaign module, in the
    interface or in the generic runner: the targets are the catalog's
    families per machine (Capabilities)."""
    camp = C.get(name)
    assert camp.check() == []
    assert _module_hits(C.MODULES[name]) == []
    for mod in ("offload.engine.campaign",):
        assert _module_hits(mod) == []
    tool = ROOT / "tools" / "campaign.py"
    pat = SCAN.pattern()
    assert [t for _, t in SCAN.code_text(tool) if pat.search(t)] == []
    # the drivers no longer carry a toolchain list, so they left the allow-list
    assert f"tools/{name}.py" not in SCAN.allowlist()


def test_nested_and_oop_keep_their_recorded_targets_and_gate_kinds():
    """The record behind the stored rows (the former TARGETS tables of
    tools/campaigns/nested.py and tools/campaigns/oop.py), now derived from the catalog."""
    want = {"tuolumne": (["afar", "cce19", "cce20", "cce21", "cce21_4"], [0, 1]),
            "tioga": (["gcc_g90"], [0]),
            "wingtip": (["nvhpc", "nvhpc269", "gcc_sm80"], [0, 2])}
    for name in ("nested", "oop"):
        camp = C.get(name)
        assert camp.caps.targets() == want, name
        assert GT.KINDS[name] == {"prefix": f"{name}_", "signature": "program"}
        assert name in GT.VALUE_KINDS and GT.COMPILE_LIMIT_S[name] == 900
    assert C.get("nested").labels == C.LABELS
    assert C.get("oop").labels == ("defined", "unspecified")
    assert C.mode_name(0) == "copy" and C.mode_name(1) == "unified" and C.mode_name(2) == "unified"


def test_the_driver_wrappers_see_the_same_targets():
    for tool, name in (("nested.py", "nested"), ("oop.py", "oop")):
        spec = importlib.util.spec_from_file_location(f"drv_{name}", where.tool(tool))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        assert m.TARGETS == C.get(name).caps.targets()
        assert m.MODE_NAME == {0: "copy", 1: "unified", 2: "unified"}


def test_a_release_added_to_the_catalog_is_measured_with_no_code_change(tmp_path, monkeypatch):
    """The fake releases of tests/cluster/test_reports.py reach the
    campaigns' targets through the catalog."""
    import yaml
    from tests.cluster.test_reports import FAKE
    data = yaml.safe_load(T.CATALOG.read_text())
    data["toolchains"].update(FAKE)
    p = tmp_path / "toolchains.yaml"
    p.write_text(yaml.safe_dump(data, sort_keys=False))
    monkeypatch.setenv(T.CATALOG_ENV, str(p))
    T.reset()
    try:
        nested = C.get("nested")
        assert nested.caps.toolchains("tuolumne")[-1] == "cce99"
        assert nested.caps.toolchains("wingtip") == ("nvhpc", "nvhpc269", "gcc_sm80", "nvhpc99")
        assert C.get("oop").caps.toolchains("tuolumne")[-1] == "cce99"
    finally:
        monkeypatch.delenv(T.CATALOG_ENV)
        T.reset()
    assert "cce99" not in C.get("nested").caps.toolchains("tuolumne")


def test_nested_draw_is_the_generator_s(tmp_path):
    """The generic gen of the nested campaign writes what tools/campaigns/nested.py gen
    wrote: the meta in the draw's key order and the programs of
    nested_gen.pilot with the recorded options."""
    from offload.engine import nested_gen as G
    run = C.Run(C.get("nested"), tmp_path / "t")
    want = G.pilot(60, 5, min_cover=8, legacy=False, max_tries=600)
    assert run.gen(5, 60, min_cover=8, legacy=False, max_tries=600) == len(want)
    assert (tmp_path / "t" / "meta.json").read_text() == \
        '{"n": 60, "seed": 5, "min_cover": 8, "legacy": false, "max_tries": 600}'
    assert [p.id for p in run.programs()] == [p.id for p in want]
    rows = [json.loads(ln) for ln in (tmp_path / "t" / "programs.jsonl").read_text().splitlines()]
    assert set(rows[0]) == {"id", "family", "lang", "model", "version", "legality", "why",
                            "expected", "rules", "cites", "axes", "title", "sha"}
    # a legacy draw records only n and seed
    run2 = C.Run(C.get("nested"), tmp_path / "u")
    run2.gen(2, 40)
    assert json.loads((tmp_path / "u" / "meta.json").read_text()) == {"n": 40, "seed": 2}


BIG = ROOT / "results" / "nested" / "big"


@pytest.mark.skipif(not (BIG / "programs.jsonl").is_file(),
                    reason="results/nested/big/programs.jsonl (git-ignored) is not here")
def test_the_seed_11_draw_gives_the_same_1055_programs():
    """The second draw behind data/findings/nested (seed 11, n 1000) is
    regenerated unchanged through the interface."""
    run = C.Run(C.get("nested"), BIG)
    ps = run.programs()
    stored = [json.loads(ln) for ln in (BIG / "programs.jsonl").read_text().splitlines()]
    assert len(ps) == len(stored) == 1055
    assert [p.id for p in ps] == [r["id"] for r in stored]
    assert [C.sha256(p.source) for p in ps] == [r["sha"] for r in stored]


def test_oop_programs_ignore_the_draw_and_keep_their_record_fields(tmp_path):
    from offload.engine import oop_gen as G
    run = C.Run(C.get("oop"), tmp_path / "main")
    assert [p.id for p in run.programs()] == [p.id for p in G.programs()]
    run.gen(0, 0)
    assert not (tmp_path / "main" / "meta.json").exists()      # a hand-listed campaign has none
    rows = [json.loads(ln) for ln in (tmp_path / "main" / "programs.jsonl").read_text().splitlines()]
    assert set(rows[0]) == {"id", "family", "variant", "model", "version", "legality", "why",
                            "expected", "modes", "cites", "title", "sha"}


# --- submission: the machines' conventions -----------------------------------------------

def test_submission_commands_follow_the_queue_rules():
    T_ = _tool()
    nested = C.get("nested")
    logs = "mkdir -p results/nested/logs && "
    pb = T_.submission(nested, "tuolumne", "run abd", "main", 3000, 16)
    assert pb.startswith(logs + "flux batch -q pbatch -N1") and "tools/jobs/run_campaign.sh nested" in pb
    assert "--output=results/nested/logs/run.{{id}}.log" in pb and pb.endswith("main 3000 16")
    assert "-t 55m" in pb                        # the limit plus five minutes of slack
    pd = T_.submission(nested, "tuolumne", "run", "main", 1500, 16, queue="pdebug")
    assert "flux run -q pdebug" in pd and "--job-name=compile-test-nested-main" in pd
    assert "-t 30m" in pd and pd.endswith("main 1500 16") and "flux batch" not in pd
    assert pd.count("-q pdebug") == 1
    # the default limit on pdebug: the script's limit shrinks to the queue's longest job
    pd = T_.submission(nested, "tuolumne", "run abd", "main", 3000, 16, queue="pdebug")
    assert "-t 30m" in pd and pd.endswith("'run abd' main 1500 16"), pd
    tio = T_.submission(nested, "tioga", "run", "main", 1800, 8)
    assert tio.startswith("ssh tio ") and "MACHINE=tioga" in tio and "-q pdebug" in tio
    assert "--job-name=compile-test-nested-main" in tio and "/nested-lane" in tio
    assert "-t 35m" in tio and "--requires=host:tioga[34-39]" in tio
    tio = T_.submission(nested, "tioga", "run", "main", 9000, 8)
    assert "-t 60m" in tio and "run main 3300 8" in tio, tio
    # (c) kept off the node of (a)
    c = T_.submission(nested, "tuolumne", "c", "main", 1200, 8, not_host="tuolumne1010")
    assert "--requires=-host:tuolumne1010" in c and "--job-name=nested-c" in c
    wt = T_.submission(nested, "wingtip", "run gate", "main", 3000, 4)
    assert wt.startswith("ssh wingtip ") and "tools/jobs/wingtip_capped.sh tools/jobs/run_wingtip_campaign.sh nested" in wt
    assert " 2 main" in wt and "mkdir -p results/nested/logs" in wt   # at most 2 workers per GPU
    assert T_.lane_root(nested, "wingtip").endswith("/nested-lane")


def test_submit_obeys_the_catalog_s_pdebug_rules():
    reg = T.registry()
    assert reg.pdebug["tuolumne"]["max_minutes"] == 30
    assert reg.pdebug["tioga"]["max_minutes"] == 60 and reg.pdebug["tioga"]["hosts"] == "tioga[34-39]"
    T_ = _tool()
    assert T_._capped(3000, 30) == (1500, 30) and T_._capped(1500, 30) == (1500, 30)
    assert T_._capped(1200, 60) == (1200, 25)


def test_the_generic_job_scripts_are_executable_and_bounded():
    for name in ("run_campaign.sh", "run_wingtip_campaign.sh", "campaign_remote.sh"):
        p = where.tool(name)
        assert p.stat().st_mode & 0o111, name
    text = (ROOT / "tools" / "jobs" / "run_campaign.sh").read_text()
    assert "flux batch -q pbatch" in text and "-q pdebug" in text
    assert "timeout -k 10" in text and 'tools/campaign.py "$CAMP"' in text
    wt = (ROOT / "tools" / "jobs" / "run_wingtip_campaign.sh").read_text()
    assert re.search(r'^\. .*wingtip_cap\.sh" \|\| exit 1', wt, re.M)
    assert "COMPLIANT_RUN_SLOTS=1" in wt and "WAIT_END" in wt


def test_list_names_every_campaign(capsys):
    assert _tool().main(["list"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("nested: kind nested") and "\noop: kind oop" in out
    assert "tuolumne: afar, cce19, cce20, cce21, cce21_4; modes [0, 1]" in out


# ---- The decided review queue of the reproduction gate ---------------------------------------------------


import yaml

sys.path.insert(0, str(ROOT / "data" / "evidence" / "gate_probe"))

import gate_queue as GQ  # noqa: E402
import observed as O  # noqa: E402
import checksum_trace as T_2  # noqa: E402

DOC = yaml.safe_load((ROOT / "catalog" / "gate_queue.yaml").read_text())


def test_every_entry_has_a_verdict_of_the_brief_and_a_group():
    groups = {g["id"]: g for g in DOC["groups"]}
    assert set(DOC["verdicts"]) == {"illegal", "unspecified",
                                    "environment_defect",
                                    "nondeterministic_defect", "ours",
                                    "undecided"}
    cells = [e["cell"] for e in DOC["entries"]]
    assert len(cells) == 97 and len(set(cells)) == 97
    for e in DOC["entries"]:
        g = groups[e["group"]]
        assert e["verdict"] in DOC["verdicts"]
        assert e["counts_as"] in ("failure", "none")
        # an entry may differ from its group's verdict, with a reason
        if e["verdict"] != g["verdict"]:
            assert e["verdict_reason"].strip() and \
                not e["verdict_reason"].startswith("the group's")
        for key in ("legality", "determinism", "action"):
            assert g[key].strip()


def test_each_verdict_is_consistent_with_the_entrys_own_evidence():
    """An entry's verdict rests on its own evidence."""
    for e in DOC["entries"]:
        v, one = e["verdict"], e.get("within_one_environment") or ""
        # a row that stops counting is never called a defect
        if v in ("illegal", "unspecified", "undecided"):
            assert e["counts_as"] == "none", e["k"]
        if v.endswith("_defect"):
            assert e["counts_as"] == "failure", e["k"]
        if v == "nondeterministic_defect":
            # disagreement within one environment, seen here or stated
            assert "disagree" in one or e["nondeterminism_basis"], e["k"]
        if v == "environment_defect":
            # not if this task's own runs in one directory disagree
            assert "the runs in one directory disagree" not in one, e["k"]
        if v == "undecided":
            # never reproduced: no probe run of the entry failed
            assert set(e["probe_runs"]) <= {"pass"}, e["k"]
            assert all(o.startswith("correct") for o in
                       list(e["gate_runner_low_load"]) +
                       list(e["gate_runner_gate_load"])), e["k"]


def test_findings_named_by_the_queue_exist():
    for e in DOC["entries"]:
        f = (e.get("finding") or "").split(" (")[0]
        if f:
            assert (ROOT / "data" / "findings" / f).is_file(), f


def test_rendered_page_is_current():
    assert (ROOT / "data" / "reports" / "gate-queue.md").read_text() == \
        GQ.render(DOC)


SRC = """program fuzz_prog
  implicit none
  integer :: i, r1a
  integer(8) :: cs
  integer :: o1(3)
  ! fuzz: checksum
  cs = 0
  cs = modulo(cs * 31_8 + int(r1a, 8), 2147483629_8)
  do i = 1, 3
    cs = modulo(cs * 31_8 + int(o1(i), &
        & 8), 2147483629_8)
  end do
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', 0
end program fuzz_prog
"""


def test_trace_prints_every_checksum_term_and_finds_the_wrong_one():
    text, stmts = T_2.instrument(SRC)
    assert stmts == ["r1a", "o1(i)"]
    assert "print '(a,i0,a,i0)', 'T ', 0, ' ', int(r1a, 8)" in text
    assert "print '(a,i0,a,i0)', 'T ', 1, ' ', int(o1(i), 8)" in text
    # the continuation stays whole, the print comes after it
    lines = text.splitlines()
    k = next(i for i, ln in enumerate(lines) if "int(o1(i), &" in ln)
    assert lines[k + 1].strip().startswith("& 8)")
    assert "'T ', 1" in lines[k + 2]
    ref = T_2.parse("T 0 5\nT 1 1\nT 1 2\nT 1 3\n")
    dev = T_2.parse("T 0 5\nT 1 1\nT 1 0\nT 1 3\n")
    assert T_2.differences(dev, ref, stmts) == {"o1(i)": [(2, 0, 2)]}
    assert T_2.differences(ref, ref, stmts) == {}


def test_observed_classes():
    assert O.classify({"rc": 0, "stdout": "RESULT checksum=7 ran_on_host=0",
                       "timed_out": False}, 7) == "pass"
    assert O.classify({"rc": 0, "stdout": "RESULT checksum=8 ran_on_host=0",
                       "timed_out": False}, 7) == "wrong"
    assert O.classify({"rc": -6, "stdout": "RESULT checksum=8 ran_on_host=0",
                       "timed_out": False}, 7) == "crash SIGABRT after cs=8"
    assert O.classify({"rc": 1, "stdout": "", "timed_out": False}, 7) == \
        "exit 1"
    assert O.classify({"rc": None, "stdout": "", "timed_out": True}, 7) == \
        "timeout"
    assert O.classify({"rc": 0, "stdout":
                       "RESULT ran_on_host=0 check=fail",
                       "timed_out": False}, None) == "wrong (check=fail)"


# ---- GCC 16.2 (gcc_g90, gcc_sm80) on the harvest --------------------------



sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]


# --- the fuzz sample --------------------------------------------------------------

def _rec(seed, gv="fuzz-3", base=(), check="ok", validity="valid", exp=7):
    return {"seed": seed, "gen_version": gv, "base": list(base),
            "check": check, "validity": validity, "expected": exp}


def test_sample_is_proportional_deterministic_and_legal_only():
    import parity as PA
    strata = {"a": [_rec(s) for s in range(1, 301)],
              "b": [_rec(s, "fuzz-4s50") for s in range(1, 101)]
              + [_rec(101, "fuzz-4s50", check="flang"),
                 _rec(102, "fuzz-4s50", validity="noncompliant")]}
    s1 = PA.sample(strata, 80)
    assert s1 == PA.sample(strata, 80)
    assert sum(len(v) for v in s1.values()) == 80
    assert len(s1["a"]) == 60 and len(s1["b"]) == 20
    assert 101 not in s1["b"] and 102 not in s1["b"]
    assert s1["a"] == sorted(s1["a"])
    # a larger sample keeps the smaller one's seeds (ranked by hash)
    s2 = PA.sample(strata, 160)
    assert set(s1["a"]) <= set(s2["a"]) and set(s1["b"]) <= set(s2["b"])


def test_old_records_without_validity_are_valid():
    import parity as PA
    assert PA.eligible(_rec(1, "fuzz-1", validity=None))
    assert not PA.eligible(_rec(1, validity="noncompliant"))
    assert not PA.eligible(_rec(1, check="rules"))


def test_strata_cover_every_generator_version_and_base_set():
    import parity as PA
    keys = {(s["gen_version"], tuple(s["base"])) for s in PA.STRATA.values()}
    assert ("fuzz-1", ()) in keys and ("fuzz-3", ()) in keys
    assert ("fuzz-4s50", ()) in keys
    allb = ("types", "derived", "alloc", "declare", "multitu")
    assert ("fuzz-3", allb) in keys and ("fuzz-4s50", allb) in keys
    for g in allb:
        assert ("fuzz-3", (g,)) in keys
    # one stratum per program set: no two strata run the same programs
    assert len(keys) == len(PA.STRATA)
    # NVHPC ran the fuzz-4s50 campaigns in full (n0x0, n1x0)
    assert {k for k, s in PA.STRATA.items() if s.get("nvhpc_ran")} == \
        {"n0", "n1"}


def test_checks_file_has_what_stored_check_matches():
    import parity as PA
    recs = [_rec(5, base=("types",), exp=11) | {"check_detail": "x",
                                                "results": {"afar": {}}}]
    line = PA.check_lines(recs, {5})[0]
    d = json.loads(line)
    assert d == {"seed": 5, "gen_version": "fuzz-3", "base": ["types"],
                 "expected": 11, "check": "ok", "check_detail": "x"}


# --- harvest-known: GCC compiles every model and language ---------------------------

def test_harvest_known_runs_every_program_on_gcc():
    import harvest_known as HK
    rows = [{"id": "a", "toolchains": ["afar", "nvhpc"]},
            {"id": "b", "toolchains": ["nvhpc"]}]
    got = HK.run_groups(rows, ["gcc_sm80"])
    assert got == [(["gcc_sm80"], ["a", "b"])]
    # the other toolchains keep the program's own list
    got = HK.run_groups(rows, ["afar", "nvhpc"])
    assert got == [(["afar"], ["a"]), (["nvhpc"], ["a", "b"])]


# --- stress: GCC build variants ---------------------------------------------------------

def test_stress_variants_for_gcc():
    from offload.engine import stress_exec as X
    from offload.engine.toolchains import TOOLCHAINS
    sm = TOOLCHAINS["gcc_sm80"]
    assert X.variant_flags(sm, "O2") == "-O2"
    assert X.variant_flags(sm, "O0") == "-O0"
    assert X.variant_flags(sm, "lto") == "-O2 -flto"
    assert X.variant_flags(sm, "noinline") == "-O2 -fno-inline"
    assert X.variant_flags(sm, "noinline", "c") == "-O2 -fno-inline"
    assert X.variant_flags(sm, "staticlib") == "-O2"
    assert X.variant_flags(sm, "nordc") is None


# --- applications: GCC preprocesses a lower-case .f90 with -cpp ------------------------

def test_apps_preprocess_flag_for_gcc():
    """A lower-case .f90 with defines gets -cpp in GCC's compile line (and
    no other family's flag); a C source gets none."""
    from offload.engine import apps as A
    f = A.AppProgram(id="x", app="x", lang="f90", model="omp", sources=["a.f90"],
                     defines=["N=4"])
    for tc in ("gcc_sm80", "gcc_g90"):
        line = A.compile_flags(A.toolchain(tc, f, 0), f, "a.f90", "-O2").split()
        assert "-cpp" in line and "-Mpreprocess" not in line and "-eZ" not in line
        assert "-DN=4" in line
    c = A.AppProgram(id="y", app="y", lang="c", model="omp", sources=["a.c"], defines=["N=4"])
    assert "-cpp" not in A.compile_flags(A.toolchain("gcc_sm80", c, 0), c, "a.c", "-O2").split()


@pytest.mark.needs_bench("apps/manifest.yaml")
def test_mfc_is_not_applicable_to_gcc():
    from offload.engine import apps as A
    mfc = [p for p in A.programs().values() if p.sources == ["@mfc"]]
    assert mfc
    for p in mfc:
        for tc in ("gcc_sm80", "gcc_g90"):
            assert A.applicable(p, tc) == "MFC's build refuses GPU offload with GNU compilers"
        assert A.applicable(p, "nvhpc") is None


# --- stress: the GCC sweeps and their pre-run check ------------------------------------

def test_stress_sweeps_mirror_the_nvhpc_sweeps():
    import parity as PA
    sw = PA.STRESS_SWEEPS
    assert set(sw) == {"pg-omp", "pg-acc", "pg-c", "pg-var"}
    for k in ("pg-omp", "pg-acc", "pg-c"):
        assert "--axes all" in sw[k] and "--sizes key" in sw[k]
    assert "nordc" not in sw["pg-var"] and "lto" in sw["pg-var"]
    # the runner's ARGS form: + for space, commas kept
    assert PA.stress_step("pg-var", "gcc_sm80").startswith(
        "stress:pg-var:gcc_sm80:--axes+tu.plain,")


def test_stress_check_specs_are_unique_programs():
    import parity as PA
    specs = PA.stress_specs()
    ids = [PA.stress_pid(s) for s in specs]
    assert len(ids) == len(set(ids))
    assert any(s["model"] == "c" for s in specs)
    assert any(s["layout"] == "partition" for s in specs)


# --- fuzz: gate items and the confirmer's rows ------------------------------------------

def _fuzz_rec(seed, cls, tc="gcc_sm80", **kw):
    return {"seed": seed, "gen_version": "fuzz-3", "base": ["types"],
            "check": "ok", "validity": "valid", "expected": 9,
            "features": [], "kernels": [], "flags": 0, "lines": 1,
            "results": {tc: {"toolchain": tc, "cls": cls, "reason": "r",
                             "checksum": 8, "ran_on_host": 0,
                             "flaky": False, "runs": [], "output": "o",
                             **kw}}}


def test_fuzz_idents_follow_the_copy_mode_campaign_of_the_program_set():
    import parity as PA
    # b<k> ran in unified mode only; x0-<group> is the same programs in copy
    assert PA.FUZZ_IDENT["b1"] == "x0-types"
    assert PA.FUZZ_IDENT["b5"] == "x0-multitu"
    assert PA.FUZZ_IDENT["s1"] == "s1" and PA.FUZZ_IDENT["n0"] == "n0"
    assert PA.FUZZ_IDENT["c1"] == "c1" and PA.FUZZ_IDENT["b0"] == "b0"
    assert PA.stratum_of_run("par-b1-gcc_sm80") == "b1"
    assert PA.stratum_of_run("par-s1-nvhpc-nvhpc269") == "s1"


def test_fuzz_items_are_the_failing_rows_only():
    import parity as PA
    recs = [_fuzz_rec(1, "agree"), _fuzz_rec(2, "wrong_code"),
            _fuzz_rec(3, "harness_error"),
            {**_fuzz_rec(4, "wrong_code"), "validity": "noncompliant"}]
    its = PA.fuzz_items_of(recs, "par-b1-gcc_sm80", xnack=0)
    assert [it["ident"] for it in its] == ["x0-types:2"]
    it = its[0]
    assert it["cell"] == "fuzz|par-b1-gcc_sm80:2|gcc_sm80|0"
    assert it["machine"] == "wingtip" and it["kind"] == "fuzz"
    assert it["locator"]["base"] == ["types"] and it["locator"]["seed"] == 2


def test_stress_items_read_the_checked_programs(tmp_path):
    import parity as PA
    run = tmp_path / "stress" / "pg-omp"
    run.mkdir(parents=True)
    prog = {"id": "kernels-omp-4-1", "axis": "kernels", "size": 4, "seed": 1,
            "model": "omp", "lang": "f90", "layout": "single",
            "legality": "legal", "gate": {"stage": "ok"}, "elision": None}
    bad = dict(prog, id="kernels-omp-8-1", gate={"stage": "flang"})
    checked = tmp_path / "checked.jsonl"
    checked.write_text(json.dumps(prog) + "\n" + json.dumps(bad) + "\n")
    rows = [{"id": "kernels-omp-4-1", "toolchain": "gcc_g90", "mode": 0,
             "variant": "O2", "cls": "wrong_code", "axis": "kernels"},
            {"id": "kernels-omp-8-1", "toolchain": "gcc_g90", "mode": 0,
             "variant": "O2", "cls": "wrong_code", "axis": "kernels"},
            {"id": "kernels-omp-4-1", "toolchain": "gcc_sm80", "mode": 0,
             "variant": "O2", "cls": "agree", "axis": "kernels"}]
    (run / "rows.jsonl").write_text("".join(json.dumps(r) + "\n"
                                            for r in rows))
    its = PA.stress_items(tmp_path / "stress", checked)
    assert [(i["ident"], i["toolchain"]) for i in its] == \
        [("kernels-omp-4-1", "gcc_g90")]
    assert its[0]["machine"] == "tioga"
    assert its[0]["cell"] == "stress|kernels-omp-4-1|gcc_g90|0|O2"


# --- Tioga has no /p/lustre5: AFAR's front end from the /p/vast1 copy -------------------

def test_afar_bin_falls_back_to_the_vast_copy_only_without_lustre():
    from offload.engine import toolchains as T
    L, V = "/lustre/afar/bin", "/vast/afar/bin"
    assert T._afar_bin(L, V, isdir={L, V}.__contains__) == L
    assert T._afar_bin(L, V, isdir={V}.__contains__) == V      # Tioga
    assert T._afar_bin(L, V, isdir=set().__contains__) == L    # wingtip
    assert T.AFAR_BIN.endswith("592954c/bin")


# --- harvest: the confirmer on some toolchains only --------------------------------------

def test_harvest_confirm_todo_filters_toolchains_and_passing_rows():
    import harvest as HV
    from offload.engine.confirm.ingest import row_of_result
    rs = [{"program_id": "p", "toolchain": t, "xnack": 0, "outcome": o,
           "reason": "", "kind": "harvest"}
          for t, o in (("gcc_sm80", "wrong_answer"), ("nvhpc", "rejected"),
                       ("gcc_g90", "correct_on_device"))]
    rows = [row_of_result(r) for r in rs]
    got = HV.confirm_todo(rows, toolchains={"gcc_sm80", "gcc_g90"})
    assert [r.toolchain for r in got] == ["gcc_sm80"]
    assert len(HV.confirm_todo(rows)) == 2


def test_harvest_known_confirm_writes_where_told(tmp_path):
    import harvest_known as HK
    assert HK.confirm_out(None) == HK.OUT
    assert HK.confirm_out(str(tmp_path)) == tmp_path
    assert HK.judged("gcc_sm80", {"gcc_sm80"}) and not HK.judged("nvhpc", {"gcc_sm80"})
    assert HK.judged("nvhpc", None)


def test_summary_counts_runs_and_failures_per_source(tmp_path):
    import parity as PA
    m = tmp_path / "wingtip" / "results"
    (m / "harvest" / "parity").mkdir(parents=True)
    (m / "harvest" / "parity" / "rows.part.x.1.jsonl").write_text(
        json.dumps({"program_id": "a", "toolchain": "gcc_sm80", "xnack": 0,
                    "outcome": "wrong_answer"}) + "\n" +
        json.dumps({"program_id": "b", "toolchain": "gcc_sm80", "xnack": 0,
                    "outcome": "correct_on_device"}) + "\n")
    (m / "fuzz" / "par-b0-gcc_sm80").mkdir(parents=True)
    (m / "fuzz" / "par-b0-gcc_sm80" / "programs.jsonl").write_text(
        json.dumps(_fuzz_rec(1, "agree")) + "\n" +
        json.dumps(_fuzz_rec(2, "wrong_code")) + "\n")
    s = PA.summary([tmp_path / "wingtip"])
    assert s[("harvest", "gcc_sm80")] == {"run": 2, "failing": 1}
    assert s[("fuzz", "gcc_sm80")] == {"run": 2, "failing": 1}


# --- the fuzz minimizer on another machine: "also fails on" there only ----------------

def test_minimizer_also_checks_only_the_given_toolchains():
    from offload.engine import fuzz_report as FR
    assert FR.also_candidates("gcc_g90", None) == [
        t for t in FR.REPORT_ORDER if t != "gcc_g90"]
    assert FR.also_candidates("gcc_g90", ["afar_g90", "gcc_g90",
                                          "cce21_g90"]) == \
        ["afar_g90", "cce21_g90"]


# --- harvest: the confirmer's run directory (the other families' rows and the lanes') ----

def test_harvest_combine_takes_dev_rows_and_the_lanes(tmp_path):
    import parity as PA
    hs = tmp_path / "results" / "harvest"
    (hs / "main").mkdir(parents=True)
    (hs / "programs.jsonl").write_text(
        json.dumps({"id": "d", "holdout": False}) + "\n" +
        json.dumps({"id": "h", "holdout": True}) + "\n")
    (hs / "main" / "rows.part.n.1.jsonl").write_text(
        json.dumps({"program_id": "d", "toolchain": "afar"}) + "\n" +
        json.dumps({"program_id": "h", "toolchain": "afar"}) + "\n")
    lane = tmp_path / "lane" / "results" / "harvest" / "parity"
    lane.mkdir(parents=True)
    (lane / "rows.part.t.2.jsonl").write_text(
        json.dumps({"program_id": "d", "toolchain": "gcc_g90"}) + "\n")
    (lane / "gate_reruns.part.t.2.jsonl").write_text(
        json.dumps({"cell": "harvest|d|gcc_g90|0", "env": "a"}) + "\n" +
        json.dumps({"cell": "harvest|h|gcc_g90|0", "env": "a"}) + "\n")
    out = PA.harvest_combine(hs, ["main"], [tmp_path / "lane"], "harvest")
    rows = [json.loads(x) for f in sorted(out.glob("rows*.jsonl"))
            for x in f.read_text().splitlines()]
    assert sorted(r["toolchain"] for r in rows) == ["afar", "gcc_g90"]
    assert all(r["program_id"] == "d" for r in rows)
    reruns = (out / "gate_reruns.part.lane.jsonl").read_text().splitlines()
    assert [json.loads(x)["cell"] for x in reruns] == ["harvest|d|gcc_g90|0"]


# --- the fuzz minimizer for GCC: its ICE location form, separate memory --------------

def test_ice_signature_drops_gcc_source_locations():
    from offload.engine.fuzz_min import ice_signature
    a = ice_signature("ice: <tmpdir>/fuzz-2082.f90:96:44: internal compiler error: in "
                      "simplify_subreg, at simplify-rtx.cc:8291")
    b = ice_signature("ice: fuzz_prog.f90:97:44: internal compiler error: in "
                      "simplify_subreg, at simplify-rtx.cc:8291")
    assert a == b
    assert "simplify_subreg" in a and "8291" in a


def test_minimize_takes_the_memory_mode(monkeypatch):
    """tools/campaigns/fuzz.py minimize --xnack 0 sets the runs' memory mode before
    the minimizer starts (GCC: separate memory only)."""
    import fuzz as FZ
    from offload.engine import fuzz_exec as fe
    seen = {}
    monkeypatch.setattr(fe, "XNACK", 1)
    monkeypatch.setattr(FZ.fuzz_report, "minimize_run",
                        lambda *a, **k: seen.update(xnack=fe.XNACK, also=k.get("also")))
    monkeypatch.setattr(sys, "argv", ["fuzz.py", "minimize", "--run-id", "r", "--xnack", "0",
                                      "--also", "gcc_g90"])
    assert FZ.main() == 0
    assert seen == {"xnack": 0, "also": ["gcc_g90"]}


def test_minimized_header_names_the_memory_mode(monkeypatch):
    from offload.engine import fuzz_exec as fe
    from offload.engine import fuzz_min as fm
    monkeypatch.setattr(fe, "XNACK", 0)
    h = fm.finding_header(7, fm.Failure("gcc_g90", "ice", "x", 0), "e", "o", "fuzz-3")
    assert "HSA_XNACK=0" in h and "HSA_XNACK=1" not in h


def test_a_minimized_fuzz_finding_of_gcc_g90_is_scoped_to_gfx90a(tmp_path):
    from offload.engine.confirm import findings as FI
    p = ROOT / "data" / "findings" / "fuzz" / "par-s1-2082-gcc_g90.f90"
    f = FI._fuzz_finding(p)
    assert f.toolchains == ("gcc_g90",) and f.arch == ("gfx90a",)
    assert f.modes == ("copy",)
    old = ROOT / "data" / "findings" / "fuzz" / "b3-9-cce21.f90"
    assert FI._fuzz_finding(old).arch == ("gfx942",)


def test_gcc_ice_site():
    from offload.engine.confirm.findings import site_of
    assert site_of("ice: internal compiler error: in simplify_subreg, at simplify-rtx.cc:8291") == \
        "simplify-rtx.cc:8291"
    assert site_of("ice: x.f90:3:4: internal compiler error: in lower_omp_target, at omp-low.cc:13204") == \
        "omp-low.cc:13204"
    assert site_of("ice: lto1: internal compiler error: Segmentation fault") is None


def test_gate_verdicts_inherit_for_sampled_compile_rows(tmp_path, monkeypatch):
    import parity as PA
    from offload.engine import gate as G
    monkeypatch.setattr(PA, "GATE", tmp_path)
    rows = [{"cell": f"fuzz|r:{k}|nvhpc|0", "kind": "fuzz", "campaign": "fuzz", "ident": f"x:{k}",
             "toolchain": "nvhpc", "xnack": 0, "cls": "compile_reject",
             "reason": "diagnostic: NVFORTRAN-S-0034-Syntax error at or near :", "sample": s,
             "signature": "nvhpc|compile_reject|syntax"}
            for k, s in ((1, "new"), (2, "inherited"))]
    (tmp_path / "fuzz").mkdir()
    (tmp_path / "fuzz" / "plan.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    monkeypatch.setattr(G, "judge", lambda it, rr: {"verdict": "confirmed"} if rr
                        else (_ for _ in ()).throw(ValueError("none")))
    (tmp_path / "fuzz" / "reruns").mkdir()
    (tmp_path / "fuzz" / "reruns" / "x.jsonl").write_text(json.dumps({"cell": rows[0]["cell"], "env": "a"}) + "\n")
    v = PA.gate_verdicts("fuzz")
    assert v[rows[0]["cell"]]["verdict"] == "confirmed"
    assert v[rows[1]["cell"]]["verdict"] == "confirmed" and v[rows[1]["cell"]]["inherited"]


def test_gate_plan_toolchain_filter():
    import parity as PA
    its = [{"toolchain": "gcc_sm80"}, {"toolchain": "nvhpc"}]
    assert PA.only_toolchains(its, ["gcc_sm80"]) == [{"toolchain": "gcc_sm80"}]
    assert PA.only_toolchains(its, None) == its


def test_gate_plan_only_cells(tmp_path, monkeypatch):
    import argparse
    import parity as PA
    its = [{"cell": f"fuzz|r:{k}|nvhpc|0", "toolchain": "nvhpc", "kind": "fuzz", "campaign": "fuzz",
            "ident": f"r:{k}", "machine": "wingtip", "xnack": 0, "cls": "compile_reject",
            "reason": "diagnostic: NVFORTRAN-S-0034-Syntax error at or near :", "compile_s": 1.0}
           for k in (1, 2, 3)]
    keep = tmp_path / "cells.txt"
    keep.write_text(its[1]["cell"] + "\n")
    monkeypatch.setattr(PA, "GATE", tmp_path)
    monkeypatch.setattr(PA, "fuzz_items", lambda: its)
    PA.cmd_gate_plan(argparse.Namespace(campaigns=["fuzz"], toolchains=["nvhpc"], budget_h=None,
                                        only_cells=str(keep)))
    rows = [json.loads(x) for x in (tmp_path / "fuzz" / "plan.jsonl").read_text().splitlines()]
    assert [r["cell"] for r in rows] == [its[1]["cell"]]


# --- the gate's (c) on another node (parity) --------------------------------

def _crow(k, cls, reason, sig):
    return {"cell": f"fuzz|r:{k}|gcc_g90|0", "kind": "fuzz", "campaign": "fuzz", "ident": f"x:{k}",
            "toolchain": "gcc_g90", "xnack": 0, "cls": cls, "outcome": "rejected"
            if cls == "compile_reject" else "wrong_answer", "reason": reason, "signature": sig,
            "sample": "all"}


def test_c_cells_take_run_time_rows_and_one_per_compile_signature():
    import parity as PA
    sig = "gcc_g90|compile_reject|error: array is not contiguous at (1)"
    plan = [_crow(1, "compile_reject", "diagnostic: Error: Array is not contiguous at (1)", sig),
            _crow(2, "compile_reject", "diagnostic: Error: Array is not contiguous at (1)", sig),
            _crow(3, "wrong_code", "check_fail: ran_on_host=0 check=fail", "w"),
            dict(_crow(4, "wrong_code", "check_fail: x", "w"), toolchain="gcc_sm80")]
    assert PA.c_cells(plan, "gcc_g90") == [plan[0]["cell"], plan[2]["cell"]]


def test_c_status_inherits_only_a_confirmed_node_distinct_signature():
    import parity as PA
    sig = "gcc_g90|compile_reject|error: array is not contiguous at (1)"
    plan = [_crow(1, "compile_reject", "diagnostic: Error: Array is not contiguous at (1)", sig),
            _crow(2, "compile_reject", "diagnostic: Error: Array is not contiguous at (1)", sig),
            _crow(3, "wrong_code", "check_fail: ran_on_host=0 check=fail", "w"),
            _crow(4, "wrong_code", "check_fail: ran_on_host=0 check=fail", "w")]
    judged = {plan[0]["cell"]: {"verdict": "confirmed", "node_distinct": True},
              plan[1]["cell"]: {"verdict": "confirmed", "node_distinct": False},
              plan[2]["cell"]: {"verdict": "confirmed", "node_distinct": True},
              plan[3]["cell"]: {"verdict": "confirmed", "node_distinct": False}}
    st = PA.c_status(plan, judged)
    assert [st[r["cell"]] for r in plan] == ["own", "inherited", "own", "missing"]
    judged[plan[0]["cell"]]["verdict"] = "environment"
    assert PA.c_status(plan, judged)[plan[1]["cell"]] == "missing"


def test_gate_run_cells_limits_the_plan(tmp_path, monkeypatch):
    import argparse
    import gate as GT
    import parity as PA
    monkeypatch.setattr(PA, "GATE", tmp_path)
    (tmp_path / "fuzz").mkdir()
    (tmp_path / "fuzz" / "plan.jsonl").write_text(
        "".join(json.dumps({"cell": c}) + "\n" for c in ("x", "y")))
    (tmp_path / "cells").write_text("y\n")
    seen = {}
    monkeypatch.setattr(GT, "cmd_run", lambda ns: seen.update(
        plan=GT._jl(GT.OUT / "fuzz" / "plan.jsonl")) or 0)
    for attr in ("_jl", "OUT", "LEDGER"):
        monkeypatch.setattr(GT, attr, getattr(GT, attr))
    ns = argparse.Namespace(campaign="fuzz", machine="tioga", envs="c", shard=None,
                            workers=1, limit_s=1, cells=str(tmp_path / "cells"))
    assert PA.cmd_gate_run(ns) == 0
    assert seen["plan"] == [{"cell": "y"}]


def test_tioga_runner_refuses_a_c_step_on_a_node_of_a(tmp_path):
    """Parity: the Tioga runner starts no (c) step without the
    nodes of (a), nor on one of them; other steps are not held."""
    import socket
    import subprocess
    sh = ROOT / "tools" / "jobs" / "run_parity_tioga.sh"
    here = socket.gethostname().split(".")[0]

    def go(steps, hosts=None):
        env = {"PATH": "/usr/bin:/bin", "PY": "/bin/false"}
        if hosts is not None:
            env["A_HOSTS"] = hosts
        return subprocess.run(["bash", "-c", 'set -- "$@"; src=$(sed -n "/^NODE=/,/^done$/p" "$0"); '
                               'eval "$src"; echo pass', str(sh), *steps],
                              env=env, capture_output=True, text=True)
    r = go(["0:pgate:fuzz:c:0"], f"x,{here}")
    assert r.returncode == 2 and "refused" in r.stdout
    r = go(["0:hgate:harvest:gcc_g90:c:1"])
    assert r.returncode == 2 and "needs A_HOSTS" in r.stdout
    assert "pass" in go(["0:pgate:fuzz:c:0"], "tioga39-not-here").stdout
    assert "pass" in go(["0:pgate:fuzz:a,b,d:0@hgate:harvest:gcc_g90:a,b,d:1"]).stdout


# ---- GCC 16.2's findings from the harvests and the stress sweeps ---------



from offload.engine.confirm import findings as FI
from offload.engine.site import header as H

FINDINGS = ROOT / "data" / "findings"
SOURCES = ("harvest", "apps", "stress", "fuzz")

# (toolchain, lang, outcome, reason as the harness stores it, program id, finding)
LINKS = [
    ("gcc_g90", "c", "rejected", "diagnostic: <tmpdir>/x.c:43:48: error: expected ']' before ':' token",
     "hv-llvm-offloading-strided-update-strided-update-from", "gcc-c-strided-section-rejected.c"),
    ("gcc_sm80", "c", "ice", "ice: <tmpdir>/x.c:20:9: internal compiler error: in install_var_field, at "
     "omp-low.cc:806", "hv-llvm-mapping-map-ordering-tgt-data-alloc-from", "gcc-c-target-data-two-maps-ice.c"),
    ("gcc_g90", "c", "ice", "ice: <tmpdir>/h2-ompex-target-struct-map-4-c.c:59:11: internal compiler error: Segmentation fault",
     "h2-ompex-target-struct-map-4-c", "gcc-c-target-data-struct-pointer-section-ice.c"),
    ("gcc_sm80", "c", "ice", "ice: <tmpdir>/h2-ompex-target-struct-map-4-c.c:59:11: internal compiler error: Segmentation fault",
     "h2-ompex-target-struct-map-4-c", "gcc-c-target-data-struct-pointer-section-ice.c"),
    ("gcc_g90", "f90", "ice", "ice: internal compiler error: in gfc_omp_clause_default_ctor, at "
     "fortran/trans-openmp.cc:840", "hv-aomp-smoke-fails-flang-324387", "gcc-teams-simd-matmul-allocatable-ice.f90"),
    ("gcc_sm80", "c", "rejected", "diagnostic: <tmpdir>/x.c:20:9: error: 'x' appears more than once in map "
     "clauses", "hv-llvm-mapping-map-ordering-tgt-alloc-tofrom", "gcc-c-same-item-two-maps-rejected.c"),
    ("gcc_g90", "f90", "rejected", "diagnostic: Error: Symbol 'a' present on multiple clauses at (1)",
     "h2-gomp-f-target-map-multi-1", "gcc-same-item-two-maps-rejected.f90"),
    ("gcc_g90", "f90", "run_error", "exit_status: 1", "hk-007", "gcc-acc-declare-create-allocatable-not-mapped.f90"),
    ("gcc_sm80", "f90", "run_error", "exit_status: 1", "hk-087", "gcc-acc-declare-create-allocatable-not-mapped.f90"),
    ("gcc_g90", "c", "wrong_answer", "check_fail: ran_on_host=0 check=fail", "prk-c-stencil-acc",
     "gcc-acc-c-tile-partial-tiles-wrong.c"),
    ("gcc_g90", "f90", "wrong_answer", "check_fail: ran_on_host=0 check=fail", "prk-f-stencil-acc",
     "gcc-acc-tile-partial-tiles-wrong.f90"),
    ("gcc_g90", "f90", "ice", "ice: internal compiler error: in lower_omp_target, at omp-low.cc:13204",
     "template.declared_alloc-omp-8-1", "gcc-declare-target-allocatable-component-ice.f90"),
    ("gcc_sm80", "f90", "rejected", "diagnostic: Error: !$OMP DECLARE REDUCTION padd not found at (1)",
     "n1:41", "gcc-declare-reduction-module-not-found.f90"),
    ("gcc_g90", "f90", "rejected", "diagnostic: Error: Array is not contiguous at (1)", "x0-alloc:10",
     "gcc-strided-target-update-rejected.f90"),
    ("gcc_g90", "f90", "rejected", "diagnostic: Error: Symbol 'o1' present on multiple clauses at (1)", "b0:227",
     "gcc-target-simd-map-nontemporal-rejected.f90"),
    ("gcc_g90", "f90", "ice", "ice: internal compiler error: in simplify_subreg, at simplify-rtx.cc:8291",
     "s1:80", "par-s1-2082-gcc_g90.f90"),
]


def _entries():
    data = yaml.safe_load((FINDINGS / "index.yaml").read_text())
    return [e for e in data["findings"]
            if e["file"].split("/")[0] in SOURCES and Path(e["file"]).name.startswith("gcc-")]


@pytest.mark.parametrize("tc, lang, outcome, reason, prog, finding", LINKS)
def test_a_parity_cell_links_one_gcc_finding(tc, lang, outcome, reason, prog, finding):
    hits = []
    for f in FI.load_index():
        m = FI.match(f, tc, lang, outcome, reason, "", prog, mode="copy")
        if m and m[0] == "duplicate" and set(f.toolchains) <= {"gcc_g90", "gcc_sm80"}:
            hits.append(Path(f.file).name)
    assert hits == [finding]


def test_every_parity_gcc_finding_file_is_indexed_and_scoped():
    entries = {e["file"]: e for e in _entries()}
    files = sorted(f"{s}/{p.name}" for s in SOURCES for p in (FINDINGS / s).glob("gcc-*.*")
                   if p.suffix in (".c", ".f90"))
    assert files and sorted(entries) == files
    for e in entries.values():
        assert set(e["toolchains"]) <= {"gcc_g90", "gcc_sm80"} and e["toolchains"], e["file"]
        assert e["modes"] == ["copy"], e["file"]
        assert set(e["arch"]) <= {"gfx90a", "sm_80"}, e["file"]
        assert e["lang"] == ("c" if e["file"].endswith(".c") else "f90"), e["file"]
        assert e.get("programs"), e["file"]


def test_parity_gcc_findings_have_a_site_block_and_no_placeholder():
    for e in _entries():
        path = FINDINGS / e["file"]
        h = H.parse(path)
        assert h.title and h.summary, e["file"]
        for text in (h.title, h.summary):
            assert not any(w in f" {text.lower()} " for w in (" we ", " our ", " i ")), e["file"]
        text = path.read_text()
        for ph in ("PROBES", "GATE", "OTHERS", "APPOBS"):
            assert ph not in text.replace("PROBESCTL", ""), (e["file"], ph)
        assert "PROBESCTL" not in text, e["file"]
        assert all(len(ln) <= 132 for ln in text.splitlines()), e["file"]


# The Examples' target_struct_map.4 internal compiler error, hand-reduced
GCC_STRUCT = FINDINGS / "harvest" / "gcc-c-target-data-struct-pointer-section-ice.c"


def _code(path):
    """The program's lines: no header comments, no site block, no blank lines."""
    out, in_site = [], False
    for ln in path.read_text().splitlines():
        if ln.startswith("// site:"):
            in_site = True
        if in_site or ln.startswith("//") or not ln.strip():
            continue
        out.append(ln.strip())
    return out


def _entry_of(name):
    data = yaml.safe_load((FINDINGS / "index.yaml").read_text())
    return next(e for e in data["findings"] if e["file"] == "harvest/" + name)


def test_gcc_control_differs_from_the_reproducer_in_the_order_of_the_map_list_only():
    ctl = FINDINGS / "harvest" / "controls" / "gcc-c-target-data-struct-pointer-section-control.c"
    a = [x for x in _code(GCC_STRUCT) if not x.startswith("/*")]
    b = [x for x in _code(ctl) if not x.startswith("/*")]
    assert [(x, y) for x, y in zip(a, b) if x != y] == [
        ("#pragma omp target data map(s.p[:4], s.p, s.a)", "#pragma omp target data map(s.p, s.p[:4], s.a)")]
    assert len(a) == len(b)


def test_gcc_finding_is_its_own_defect_and_names_the_harvested_program():
    e = _entry_of("gcc-c-target-data-struct-pointer-section-ice.c")
    assert e["toolchains"] == ["gcc_g90", "gcc_sm80"] and e["outcome"] == "ice"
    assert "Segmentation fault" in e["message"] and e["programs"] == ["h2-ompex-target-struct-map-4-c"]
    # the other ICE of the same repeat family is a different defect with another message
    assert "install_var_field" in _entry_of("gcc-c-target-data-two-maps-ice.c")["message"]
    assert "not the defect of gcc-c-target-data-two-maps-ice.c" in GCC_STRUCT.read_text()


# ---- The CCE finding on the OpenMP Examples' target_struct_map.4 ----------------



HARVEST = ROOT / "data" / "findings" / "harvest"
CCE = HARVEST / "cce-c-implicit-struct-map-partly-present.c"


def _code_5(path: Path) -> list[str]:
    """The program's lines: no header comments, no site block, no blank lines."""
    out, in_site = [], False
    for ln in path.read_text().splitlines():
        if ln.startswith("// site:"):
            in_site = True
        if in_site or ln.startswith("//") or not ln.strip():
            continue
        out.append(ln.strip())
    return out


def _entry(name: str) -> dict:
    data = yaml.safe_load((ROOT / "data" / "findings" / "index.yaml").read_text())
    return next(e for e in data["findings"] if e["file"] == "harvest/" + name)


def test_cce_finding_stays_cce_only_and_says_how_nvhpc_fails():
    assert _entry("cce-c-implicit-struct-map-partly-present.c")["toolchains"] == ["cce19", "cce20", "cce21"]
    lines = CCE.read_text().splitlines()
    text = re.sub(r"\s*\n//\s*", " ", "\n".join(lines))   # the header's wrapped lines as one
    assert "variable in data clause is partially present on the device" in text
    assert "NVHPC" in text and "failing another way" in text
    assert all(len(ln) <= 132 for ln in lines)


def test_cce_controls_are_files_and_each_makes_one_change():
    whole = HARVEST / "controls" / "cce-c-implicit-struct-map-partly-present-whole-control.c"
    only = HARVEST / "controls" / "cce-c-implicit-struct-map-partly-present-target-only-control.c"
    base = _code_5(CCE)
    pragma = re.compile(r"#pragma omp target")
    for ctl, expect in ((whole, ["#pragma omp target data map(s.big, s.p[:N], s.p, s.a, s.b)"]),
                        (only, ["#pragma omp target map(s.p[:N], s.a, s.b) map(from: dev)"])):
        got = _code_5(ctl)
        assert [x for x in got if pragma.match(x) and x not in base] == expect, ctl.name
        assert ctl.name in CCE.read_text(), ctl.name


# ---- GCC 16.2's own findings (data/findings/gcc/) -------




GCC_DIR = ROOT / "data" / "findings" / "gcc"
MAND = "mandatory_failed_device_pass_without: exit_status: 1"
FAIL = "check_fail: ran_on_host=0 check=fail"

# (toolchain, lang, outcome, reason as the harness stores it, catalog program, finding)
LINKS_6 = [
    ("gcc_sm80", "c", "run_error", MAND, "omp52-c-clause-in_reduction-plus",
     "gcc-c-target-in-task-mandatory-device-not-found.c"),
    ("gcc_g90", "c", "run_error", MAND, "omp60-c-clause-in_reduction-max",
     "gcc-c-target-in-task-mandatory-device-not-found.c"),
    ("gcc_g90", "f90", "run_error", MAND, "omp60-clause-in_reduction-eqv",
     "gcc-target-in-task-mandatory-device-not-found.f90"),
    ("gcc_g90", "f90", "wrong_answer", FAIL, "omp50-clause-defaultmap-pointer",
     "gcc-defaultmap-to-pointer-copy-back.f90"),
    ("gcc_sm80", "f90", "run_error", "exit_status: 1", "acc34-clause-detach",
     "gcc-acc-detach-delete-attach-underflow.f90"),
    ("gcc_g90", "c", "run_error", "exit_status: 1", "acc34-c-clause-detach",
     "gcc-acc-c-detach-delete-attach-underflow.c"),
    ("gcc_sm80", "c", "rejected", "diagnostic: <tmpdir>/x.c:30:3: error: expected an OpenMP clause "
     "before 'induction'", "omp60-c-clause-induction", "gcc-c-omp60-unimplemented-rejected.c"),
    ("gcc_sm80", "c", "rejected", "diagnostic: <tmpdir>/x.c:9:3: error: 'simd' undeclared",
     "omp60-c-clause-aligned-directive_name", "gcc-c-omp60-unimplemented-rejected.c"),
    ("gcc_g90", "f90", "rejected", "diagnostic: Error: Failed to match clause at (1)",
     "omp60-clause-replayable", "gcc-omp60-unimplemented-rejected.f90"),
    ("gcc_g90", "f90", "rejected", "diagnostic: Error: Unclassifiable OpenMP directive at (1)",
     "omp60-clause-linear-ref", "gcc-omp60-unimplemented-rejected.f90"),
    # The 6.0 forms no row of GCC's table covers are a finding of their own
    ("gcc_sm80", "c", "rejected", "diagnostic: <tmpdir>/x.c:9:3: error: expected 'unified_address'",
     "omp60-c-clause-device_safesync-directive_name", "gcc-c-omp60-undocumented-rejected.c"),
    ("gcc_g90", "f90", "rejected", "diagnostic: Error: Expected ALLOC, TO, FROM, TOFROM, FIRSTPRIVATE",
     "omp60-clause-defaultmap-private", "gcc-omp60-undocumented-rejected.f90"),
    ("gcc_sm80", "c", "rejected", "not_implemented: <tmpdir>/x.c:4:1: sorry, unimplemented: "
     "'uses_allocators' clause", "omp52-c-clause-uses_allocators-traits",
     "gcc-c-uses-allocators-traits-unimplemented.c"),
    ("gcc_g90", "f90", "rejected", "not_implemented: sorry, unimplemented: 'uses_allocators' clause "
     "with traits and memory spaces", "omp60-clause-uses_allocators-memspace",
     "gcc-uses-allocators-traits-unimplemented.f90"),
    ("gcc_g90", "f90", "rejected", "diagnostic: Error: Unclassifiable OpenMP directive at (1)",
     "omp52-clause-to-mapper", "gcc-declare-mapper-rejected.f90"),
    ("gcc_sm80", "c", "rejected", "diagnostic: <tmpdir>/x.c:9:3: error: 'from' clause with modifier "
     "other than 'iterator' or 'present'", "omp50-c-clause-from-mapper", "gcc-c-motion-mapper-rejected.c"),
    ("gcc_sm80", "f90", "rejected", "diagnostic: Error: 'i' not specified in enclosing 'parallel'",
     "omp52-clause-bind-thread", "gcc-loop-bind-default-none-rejected.f90"),
    ("gcc_g90", "f90", "rejected", "diagnostic: Error: Unclassifiable OpenACC directive at (1)",
     "acc34-directive-shutdown", "gcc-acc-init-set-shutdown-rejected.f90"),
    ("gcc_sm80", "f90", "rejected", "diagnostic: Error: Failed to match clause at (1)",
     "acc34-clause-bind", "gcc-acc-bind-device-type-rejected.f90"),
    ("gcc_sm80", "c", "rejected", "diagnostic: <tmpdir>/x.c:9:3: error: expected an OpenACC clause "
     "before '(' token", "acc34-c-clause-device_type", "gcc-acc-c-bind-device-type-rejected.c"),
    ("gcc_g90", "f90", "rejected", "diagnostic: Error: 'lv' with 'link' clause used in 'routine' "
     "function", "acc34-clause-link", "gcc-acc-link-in-routine-rejected.f90"),
    ("gcc_g90", "c", "rejected", "diagnostic: <tmpdir>/x.c:9:3: error: 'lv' with 'link' clause used in "
     "'routine' function", "acc34-c-clause-link", "gcc-acc-c-link-in-routine-rejected.c"),
    ("gcc_sm80", "f90", "rejected", "diagnostic: Error: ALLOCATABLE object 'a' in USE_DEVICE clause at (1)",
     "acc34-directive-host_data", "gcc-acc-use-device-allocatable-rejected.f90"),
    ("gcc_sm80", "f90", "rejected", "diagnostic: Error: Invalid expression after 'collapse(' at (1)",
     "acc34-clause-collapse-force", "gcc-acc-gang-dim-collapse-force-rejected.f90"),
    ("gcc_g90", "c", "rejected", "diagnostic: <tmpdir>/x.c:9:3: error: 'dim' undeclared",
     "acc34-c-clause-gang-dim", "gcc-acc-c-gang-dim-rejected.c"),
]


def _gcc_entries():
    data = yaml.safe_load((ROOT / "data" / "findings" / "index.yaml").read_text())
    return [e for e in data["findings"] if e["file"].startswith("gcc/")]


@pytest.mark.parametrize("tc, lang, outcome, reason, prog, finding", LINKS_6)
def test_a_gate_confirmed_gcc_cell_links_one_gcc_finding(tc, lang, outcome, reason, prog, finding):
    hits = []
    for f in FI.load_index():
        m = FI.match(f, tc, lang, outcome, reason, "", prog, mode="copy")
        if m and m[0] == "duplicate":
            hits.append(Path(f.file).name)
    assert hits == [finding]


def test_every_gcc_finding_file_is_indexed_and_scoped():
    entries = {e["file"]: e for e in _gcc_entries()}
    files = sorted(p.name for p in GCC_DIR.glob("*.*") if p.suffix in (".c", ".f90"))
    assert files and sorted(Path(f).name for f in entries) == files
    for e in entries.values():
        assert set(e["toolchains"]) <= {"gcc_g90", "gcc_sm80"} and e["toolchains"], e["file"]
        assert e["modes"] == ["copy"], e["file"]
        assert set(e["arch"]) <= {"gfx90a", "sm_80"}, e["file"]
        assert e["lang"] == ("c" if e["file"].endswith(".c") else "f90"), e["file"]
        assert e.get("programs"), e["file"]
        # the site's model rule (offload.engine.site.matrix.derive_case): an OpenACC finding's
        # name has an "acc" word
        is_acc = "acc" in Path(e["file"]).stem.split("-")
        assert is_acc == all(p.startswith("acc") for p in e["programs"]), e["file"]


def test_gcc_findings_have_a_site_block_and_a_kind_from_their_outcome():
    for e in _gcc_entries():
        h = H.parse(ROOT / "data" / "findings" / e["file"])
        assert h.title and h.summary, e["file"]
        for text in (h.title, h.summary):
            assert not any(w in f" {text.lower()} " for w in (" we ", " our ", " i ")), e["file"]
        rejected = e["outcome"] == "rejected"
        assert rejected == e["file"].endswith(("-rejected.c", "-rejected.f90", "-unimplemented.c",
                                               "-unimplemented.f90")), e["file"]
        if h.same_as:
            assert (ROOT / "data" / "findings" / (h.same_as + Path(e["file"]).suffix)).exists() or \
                any((ROOT / "data" / "findings").glob(h.same_as + ".*")), e["file"]


# ---- GCC 16.2 with OpenMP/OpenACC offload as a compiler family under test -------------------------------

import dataclasses


from offload.engine.confirm import machines as M
from offload.engine.toolchains import TOOLCHAINS

G90 = TOOLCHAINS["gcc_g90"]
SM = TOOLCHAINS["gcc_sm80"]


def test_gcc_toolchains_and_machines():
    assert (G90.machine, G90.arch, G90.kind) == ("tioga", "gfx90a", "gcc")
    assert (SM.machine, SM.arch, SM.kind) == ("wingtip", "sm_80", "gcc")
    for tc in (G90, SM):
        assert tc.fc.endswith("/bin/gfortran") and tc.cc.endswith("/bin/gcc")
        assert tc.xnack_modes == (0,)
        assert tc.name in M.load()[tc.machine].toolchains
        assert M.family_of(tc.name) == "gcc"
    assert "16.2" in G90.fc and "16.2" in SM.fc


def test_gcc_flags_amdgcn():
    assert G90.flags() == ("-fopenmp -foffload=amdgcn-amdhsa "
                           "-foffload-options=amdgcn-amdhsa=-march=gfx90a")
    c = dataclasses.replace(G90, lang="c")
    assert c.flags() == G90.flags()
    assert c.compile_cmd("a.c", "a.out").split()[0].endswith("/bin/gcc")
    acc = dataclasses.replace(G90, model="acc")
    assert acc.flags().startswith("-fopenacc -foffload=amdgcn-amdhsa ")
    assert "-fopenmp" not in acc.flags()
    assert dataclasses.replace(G90, extra="-lm").flags().endswith(" -lm")


def test_gcc_flags_nvptx_and_the_wingtip_mode_flag_by_vendor():
    w = M.load()["wingtip"]
    # NVHPC's flags are unchanged; GCC's separate memory is its default
    assert w.flags("copy") == "-gpu=mem:separate"
    assert w.flags("copy", "nvhpc") == "-gpu=mem:separate"
    assert w.flags("copy", "gcc") == ""
    assert w.flags("managed", "gcc") == "-gpu=mem:managed"
    with pytest.raises(ValueError):
        SM.flags()             # wingtip's mode is chosen at compile time
    with pytest.raises(ValueError):
        SM.for_mode(2)         # no managed mode
    f = SM.for_mode(0)
    assert f.flags() == ("-fopenmp -foffload=nvptx-none "
                         "-foffload-options=nvptx-none=-march=sm_80 "
                         "-foffload-options=nvptx-none=-latomic")
    # GCC's manual: nvptx offload code may call libatomic, which the offload
    # link does not add by itself (ruling: in the recipe)
    assert "-latomic" not in G90.flags()
    assert dataclasses.replace(f, model="acc").flags().startswith(
        "-fopenacc -foffload=nvptx-none ")
    assert TOOLCHAINS["nvhpc"].for_mode(0).flags() == \
        "-mp=gpu -gpu=cc80 -gpu=mem:separate"


def test_bad_vendor_flags_are_refused():
    base = {"arch": "sm_80", "access": "local", "headline_mode": "copy",
            "scheduler": {"kind": "direct"}}
    for vf in (["gcc"], {"gcc": 1}):
        with pytest.raises(ValueError):
            M.load(data={"version": 1, "machines": {"x": {**base, "modes": {
                "copy": {"flags": "-a", "row_key": 0, "vendor_flags": vf}}}}})
    with pytest.raises(ValueError):  # a run-time mode has no flags to vary
        M.load(data={"version": 1, "machines": {"x": {**base, "modes": {
            "copy": {"env": {"X": "0"}, "row_key": 0,
                     "vendor_flags": {"gcc": ""}}}}}})


def test_gcc_run_env_is_its_own_runtime():
    env = G90.run_env(0)
    root = G90.fc.rsplit("/bin/", 1)[0]
    assert env["HSA_XNACK"] == "0"
    # libgomp and libgfortran of the release, then ROCm's HSA runtime that
    # libgomp's GCN plugin opens
    assert env["LD_LIBRARY_PATH"].split(":") == [f"{root}/lib64",
                                                 "/opt/rocm-7.2.1/lib"]
    with pytest.raises(ValueError):
        G90.run_env(1)         # Tioga: HSA_XNACK=0 only
    env = SM.for_mode(0).run_env(0)
    assert env == {"LD_LIBRARY_PATH": SM.fc.rsplit("/bin/", 1)[0] + "/lib64"}
    # nvptx-as verifies the PTX with CUDA 13.1's ptxas, found on PATH
    assert "/usr/local/cuda/bin" in SM.prelude


def test_gcc_has_no_openmp_version_flag():
    from offload.engine.run_matrix import version_flags
    for v in (50, 52, 60):
        for lang in ("f90", "c"):
            assert version_flags("gcc_g90", v, lang) == ""
            assert version_flags("gcc_sm80", v, lang) == ""
    assert version_flags("afar", 60) == "-fopenmp-version=60"
    assert version_flags("afar_g90", 52, "c") == "-fopenmp-version=52"


def test_gcc_family_and_message_tables():
    from offload.engine.harness import table_key
    from offload.engine.toolchains import family
    assert family("gcc_g90") == family("gcc_sm80") == "gcc"
    assert table_key("gcc_g90", "c") == "gcc:c"
    assert family("cce21_g90") == "cce19" and family("nvhpc269") == "nvhpc"


def test_registry_and_report_know_gcc():
    from offload.engine import report as R
    from offload.engine.toolchains import NVIDIA_TOOLCHAINS, check_registry
    assert check_registry() == []
    assert R.TC_NAME["gcc_g90"] == "GCC 16.2 gfx90a"
    assert R.TC_NAME["gcc_sm80"] == "GCC 16.2"
    assert "gcc_sm80" in NVIDIA_TOOLCHAINS
    assert R.nv_modes("gcc_sm80") == (0,)
    assert R.nv_modes("nvhpc") == (0, 2)


def test_compiler_version_banners_are_kept(monkeypatch):
    from offload.engine import toolchains as T
    out = ("GNU Fortran (GCC) 16.2.0\nCopyright (C) 2026 Free Software "
           "Foundation, Inc.\n")

    class R:
        stdout = out
    monkeypatch.setattr(T.subprocess, "run", lambda *a, **k: R)
    T._VERSIONS.clear()
    try:
        assert T.compiler_version(G90) == "GNU Fortran (GCC) 16.2.0"
        R.stdout = "gcc (GCC) 16.2.0\nCopyright\n"
        assert T.compiler_version(dataclasses.replace(G90, lang="c")) == \
            "gcc (GCC) 16.2.0"
    finally:
        T._VERSIONS.clear()


def test_wrong_arch_without_a_visible_nvidia_gpu(monkeypatch):
    from offload.engine import harness as H
    monkeypatch.setattr(H, "detect_gpu", lambda: ("", ""))
    assert H.wrong_arch(SM).startswith("environment: no_gpu")
    assert H.wrong_arch(TOOLCHAINS["nvhpc"]).startswith("environment: no_gpu")
    assert H.wrong_arch(G90) is None  # no rocminfo: unknown, as before
    monkeypatch.setattr(H, "detect_gpu", lambda: ("gfx942", "MI300A"))
    assert "wrong_arch" in H.wrong_arch(G90)


# --- under test only ----------------------------------------------------------

def test_gcc_is_under_test_only():
    assert M.under_test_only() == {"gcc"}
    assert M.load()  # the entry is checked on load
    with pytest.raises(ValueError):
        M.load(data={"version": 1, "machines": {},
                     "families": {"gcc": ["gcc_g90"]},
                     "under_test_only": {"nosuch": "why"}})
    with pytest.raises(ValueError):
        M.load(data={"version": 1, "machines": {},
                     "families": {"gcc": ["gcc_g90"]},
                     "under_test_only": {"gcc": ""}})


def test_gcc_cells_are_never_collected_for_another_familys_case():
    from offload.engine.confirm.collectors import (compared_toolchains,
                                               headline_toolchains)
    from offload.engine.confirm.model import Case, ProgramRef
    assert "gcc_g90" not in headline_toolchains("gfx90a")
    assert "afar_g90" in headline_toolchains("gfx90a")
    assert "gcc_sm80" not in headline_toolchains("sm_80")
    assert set(headline_toolchains("sm_80")) == {"nvhpc", "nvhpc269"}
    ref = ProgramRef("catalog", "omp52-x", text="program p\nend\n")
    amd = Case(ref, "afar_g90", "tioga", "gfx90a", "copy", "rejected",
               "diagnostic: x")
    assert "gcc_sm80" not in compared_toolchains(amd)
    assert "nvhpc" in compared_toolchains(amd)


def test_a_gcc_compile_is_no_legality_witness():
    from offload.engine.confirm.facts import Facts
    from offload.engine.confirm.legality import Legality
    from offload.engine.confirm.model import Case, Evidence, ProgramRef, Run
    ref = ProgramRef("catalog", "omp52-x", text="program p\nend\n")
    c = Case(ref, "afar_g90", "tioga", "gfx90a", "copy", "rejected",
             "diagnostic: x")
    e = Evidence("other_toolchains", "gcc_g90", "gfx90a", "copy",
                 runs=(Run("correct_on_device", 0, 0, "ran"),), value=None)
    f = Facts(c, legality=Legality("legal", "t"))
    f.evidence["other_toolchains"] = [e]
    assert not f.family_witness(e, "compile")
    assert not f.family_witness(e, "run")
    assert not f.other_family_compiles()
    # another family is still a witness for a gcc case
    g = Case(ref, "gcc_g90", "tioga", "gfx90a", "copy", "rejected",
             "diagnostic: x")
    e2 = Evidence("other_toolchains", "afar_g90", "gfx90a", "copy",
                  runs=(Run("correct_on_device", 0, 0, "ran"),), value=None)
    f2 = Facts(g, legality=Legality("legal", "t"))
    f2.evidence["other_toolchains"] = [e2]
    assert f2.family_witness(e2, "compile")


# --- the vendor packets' check runner -----------------------------------------

def _run_checks():
    import importlib.util
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent.parent / "data/vendor/checks/run_checks.py"
    spec = importlib.util.spec_from_file_location("run_checks_gcc", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_run_checks_recipe_of_gcc_matches_the_toolchains():
    rc = _run_checks()
    assert rc.family("gcc_g90") == rc.family("gcc_sm80") == "gcc"
    assert rc.family("nvhpc269") == "nvhpc" and rc.family("cce21") == "cce"
    assert rc.modes_of("gcc", "tioga") == (0,)
    assert rc.modes_of("gcc", "wingtip") == (0,)
    # GCC on the MI300A runs both memory modes (measured); the MI300X and MI350X run copy memory
    assert rc.modes_of("gcc", "tuolumne") == (0, 1)
    assert rc.modes_of("gcc", "mi300x") == rc.modes_of("gcc", "mi350x") == (0,)
    assert {rc.GCC_TARGET[m] for m in ("tuolumne", "tioga", "mi300x", "mi350x")} == {"amdgcn-amdhsa"}
    assert rc.modes_of("nvhpc", "wingtip") == (0, 2)
    assert rc.modes_of("afar", "tuolumne") == (0, 1)
    for tc, machine in (("gcc_g90", "tioga"), ("gcc_sm80", "wingtip")):
        t = TOOLCHAINS[tc].for_mode(0)
        for lang, model in (("f90", "omp"), ("c", "omp"), ("f90", "acc")):
            pre, cmd, env = rc.recipe(tc, machine, lang, model, "", "-O2", 0,
                                      "x.src", "repro")
            u = dataclasses.replace(t, lang=lang, model=model)
            assert cmd == f"{u.compiler()} {u.flags()} -O2 x.src -o repro"
            assert env == {"LD_LIBRARY_PATH": t.run_env(0)["LD_LIBRARY_PATH"]}
            assert pre == ([TOOLCHAINS[tc].prelude] if TOOLCHAINS[tc].prelude
                           else [])


# --- the smoke subset ---------------------------------------------------------

def _subset():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "tools"))
    import gcc_subset
    return gcc_subset


def test_pick_is_evenly_spaced_sorted_and_deterministic():
    S = _subset()
    ids = [f"p{i:03d}" for i in range(100)][::-1]
    got = S.pick(ids, 10)
    assert got == [f"p{i:03d}" for i in range(0, 100, 10)]
    assert S.pick(ids, 10) == got
    assert S.pick(["b", "a"], 5) == ["a", "b"]   # fewer than n: all
    assert S.pick([], 3) == []
    assert len(S.pick(ids, 7)) == 7 and len(set(S.pick(ids, 7))) == 7


def test_subset_programs_are_legal_and_of_their_slice():
    from types import SimpleNamespace as NS
    S = _subset()
    progs = [(52, NS(id=f"omp52-a{i}", legal=i % 2 == 0)) for i in range(10)]
    got = S.subset(progs, 3)
    assert got == ["omp52-a0", "omp52-a2", "omp52-a6"]  # of a0 a2 a4 a6 a8


def test_execute_scrubs_the_callers_libgomp_environment(tmp_path,
                                                        monkeypatch):
    from offload.engine import harness as H
    for k in ("GOMP_DEBUG", "GOMP_STACKSIZE", "GCN_STACK_SIZE",
              "GOMP_NVPTX_LOWLAT_POOL"):
        monkeypatch.setenv(k, "7")
    ex = H._execute("env", tmp_path, 20)
    assert ex.rc == 0
    for k in ("GOMP_DEBUG", "GOMP_STACKSIZE", "GCN_STACK_SIZE",
              "GOMP_NVPTX_LOWLAT_POOL"):
        assert f"{k}=" not in ex.stdout


def _elf(machine: int, flags: int) -> bytes:
    import struct
    ident = b"\x7fELF" + bytes([2, 1, 1, 64]) + bytes(8)
    return ident + struct.pack("<HHIQQQI", 3, machine, 1, 0, 0, 0, flags) + \
        bytes(16)


def test_gcn_targets_read_the_embedded_code_objects():
    from offload.engine.toolchains import gcn_targets
    host = _elf(62, 0)                      # x86-64: not a GPU image
    exe = host + b"pad" + _elf(224, 0x3f | 0x100) + b"x" + \
        _elf(224, 0x4c | 0x200) + _elf(224, 0x3f | 0x100)
    assert gcn_targets(exe) == ["amdgcn-amd-amdhsa--gfx90a",
                                "amdgcn-amd-amdhsa--gfx942:xnack-"]
    assert gcn_targets(_elf(224, 0x3f | 0x300)) == [
        "amdgcn-amd-amdhsa--gfx90a:xnack+"]
    assert gcn_targets(host) == []
    assert gcn_targets(_elf(224, 0x7e)) == ["amdgcn-amd-amdhsa--mach0x7e"]


# --- GCC's messages (captured: tests/data/messages/gcc_*.txt) ------------------

def test_gcc_c_error_directive_is_read_as_for_clang():
    from offload.engine import harness as H
    from offload.engine.gen import PROBE_TOKEN
    from tests.engine.test_findings_nogpu import message
    tc = dataclasses.replace(G90, lang="c")
    warn = H._diagnostic(tc, "warning", PROBE_TOKEN,
                         message("gcc_c_error_warning"))
    assert warn and "encountered: " + PROBE_TOKEN in warn
    err = H._diagnostic(tc, "error", PROBE_TOKEN, message("gcc_c_error_fatal"))
    assert err and err.endswith(PROBE_TOKEN)
    assert H._diagnostic(tc, "error", PROBE_TOKEN,
                         message("gcc_c_error_warning")) is None


def test_gcc_dropped_declare_target_compiles_as_ignored():
    from offload.engine.harness import classify_message
    from tests.engine.test_findings_nogpu import message
    found = classify_message("gcc_g90", message("gcc_ignored_declare_target"),
                             ("ignored",))
    assert found[0] == "ignored" and "is ignored" in found[1]


@pytest.mark.parametrize("name,line", [
    ("gcc_link_unresolved_atomic",
     "unresolved symbol __atomic_compare_exchange_16"),
    ("gcc_link_undefined_probe", "ld: error: undefined symbol: ext_fn_")])
def test_gcc_offload_link_failures_are_the_programs(name, line):
    """nvptx-ld's "unresolved symbol X" names no referrer: it links the
    program's device image with the toolchain's archives, so it is the
    program's (link_undefined_symbol, a rejection); lld (amdgcn, called as
    "ld") names the program's object in the compile's directory."""
    from offload.engine.harness import _undefined_symbols, classify_message
    from tests.engine.test_findings_nogpu import message
    text = message(name)
    assert _undefined_symbols(text) == ("link_undefined", line)
    assert classify_message("gcc_sm80", text)[0] == "link_undefined"
    # a toolchain file as referrer is the environment, as for AFAR
    if name == "gcc_link_undefined_probe":
        sys_ref = text.replace("<tmpdir>/ccsIVO56.o",
                               "/opt/gcc-16.2/lib/x.a(y.o)")
        assert sys_ref != text
        assert _undefined_symbols(sys_ref)[0] == "environment"


# --- the lane's gate and repeat runs (tools/campaigns/gcc_lane.py) ------------------------

def _lane():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "tools"))
    import gcc_lane
    return gcc_lane


def test_lane_gate_reads_only_gcc_rows_of_its_own_files(monkeypatch):
    L = _lane()
    assert L.catalog_files() == [f"gcc/{tc}/matrix.{t}.x{x}.jsonl"
                                 for tc, xs in (("gcc", (0, 1)), ("gcc_g90", (0,)), ("gcc_sm80", (0,)))
                                 for x in xs for t in ("f90", "c", "acc", "accc")]
    from offload.engine import gate_stored as GS
    seen = {}

    def fake(camp, files):
        seen["files"] = list(files)
        return [{"toolchain": "gcc_sm80", "cell": "a"},
                {"toolchain": "nvhpc", "cell": "b"}]
    monkeypatch.setattr(GS, "harness_items", fake)
    assert [i["cell"] for i in L.items("catalog")] == ["a"]
    assert seen["files"] == L.catalog_files()
    assert str(L.GATE).endswith("results/gcc/gate")


def test_repeat_summary_counts_each_run_class():
    L = _lane()
    rows = [{"program_id": "p", "outcome": "correct_on_device", "reason": ""},
            {"program_id": "p", "outcome": "wrong_answer", "reason": "timeout"},
            {"program_id": "p", "outcome": "wrong_answer",
             "reason": "check_fail: ran_on_host=0 check=fail"},
            {"program_id": "q", "outcome": "unobservable", "reason": ""}]
    assert L.repeat_summary(rows) == {
        "p": {"pass": 1, "timeout": 1, "wrong": 1, "runs": 3},
        "q": {"pass": 1, "runs": 1}}


def test_run_checks_runs_every_case_with_all_arches():
    rc = _run_checks()
    cases = [{"id": "a", "arch": ["gfx942"], "vendor": "hpe", "repro": "s"},
             {"id": "b", "arch": ["gfx90a"], "vendor": "amd", "repro": "s",
              "control": "t"},
             {"id": "c", "arch": ["sm_80"], "vendor": "nvidia", "repro": "s",
              "vendor_machine": ["wingtip"]}]
    got = rc.select_jobs(cases, ["gcc_g90"], ["repro"], "tioga")
    assert [j["case"]["id"] for j in got] == ["b"]      # as before
    got = rc.select_jobs(cases, ["gcc_g90"], ["repro"], "tioga",
                         all_arches=True)
    assert [j["case"]["id"] for j in got] == ["a", "b", "c"]
    assert [j["variant"] for j in rc.select_jobs(
        cases, ["afar_g90"], ["repro", "control"], "tioga")] == [
        "repro", "control"]


# --- GCC: a compiler-generated assembly file's error is no rejection ---

GCC_ICE = """<tmpdir>/p.f90: In function 'MAIN__._omp_fn.0':
<tmpdir>/p.f90:12:3: internal compiler error: in expand_expr_real_1, at expr.cc:10950
0x1a2b3c expand_expr_real_1(tree_node*, rtx_def*, machine_mode, expand_modifier, rtx_def**, bool)
Please submit a full bug report, with preprocessed source (by using -freport-bug).
mkoffload: fatal error: x86_64-pc-linux-gnu-accel-amdgcn-amdhsa-gcc returned 1 exit status
compilation terminated.
lto-wrapper: fatal error: /p/gcc/libexec/gcc/x86_64-pc-linux-gnu/16.2.0//accel/amdgcn-amdhsa/mkoffload returned 1 exit status
collect2: error: ld returned 1 exit status
"""
GCC_ASM = """/tmp/ccA1b2C3.s:123:5: error: invalid operand for instruction
        v_mov_b32 v0, s[4:5]
        ^
gcn mkoffload: fatal error: x86_64-pc-linux-gnu-accel-amdgcn-amdhsa-gcc returned 1 exit status
compilation terminated.
lto-wrapper: fatal error: mkoffload returned 1 exit status
collect2: error: ld returned 1 exit status
"""


@pytest.mark.parametrize("text", [GCC_ICE, GCC_ASM])
@pytest.mark.parametrize("lang", ["f90", "c"])
def test_gcc_ice_and_assembler_errors_are_never_a_rejection(text, lang):
    """INVENTED texts in the forms GCC prints (an ICE with the mkoffload
    trailer; llvm-mc, the amdgcn assembler, refusing a generated .s file):
    either is the compiler's own failure, never a diagnosed rejection."""
    from offload.engine.harness import classify_message
    found = classify_message("gcc_g90", text, lang=lang)
    assert found is None or found[0] == "ice", found


def test_the_programs_own_located_error_is_still_a_diagnostic():
    from offload.engine.harness import classify_message
    from tests.engine.test_findings_nogpu import message
    assert classify_message("gcc_g90", message(
        "gcc_acc_located_lower_error"))[0] == "error"
    assert classify_message("gcc_g90", message("gcc_c_syntax_error"),
                            lang="c")[0] == "error"


# --- GCC: GCC rows in the result files ---------------------------

def test_report_accepts_gcc_rows_or_says_why_not():
    """The support tables give every GCC install a column: gcc an AMD one (its MI300A modes,
    then its twins), gcc_sm80 an NVIDIA-style one; none is left out."""
    from offload.engine import report as R
    from offload.engine.toolchains import GCC_TOOLCHAINS, registry
    assert not set(R.REPORT_EXCLUDED) & set(GCC_TOOLCHAINS)
    assert "gcc" in R.ALL_TOOLCHAINS and "gcc_sm80" in R.NVIDIA_TOOLCHAINS
    assert set(GCC_TOOLCHAINS) == {"gcc", "gcc_sm80", *registry().twins_of("gcc")}


def test_no_gcc_checker_ever_witnesses_legality():
    """GCC: an independent checker of a family under test only,
    or any program of a GCC install, is refused, whatever its name."""
    from offload.engine.confirm import witness as W
    from offload.engine.toolchains import GCC_SM80_ROOT
    base = {"kind": "offload_compiler", "witness_only": True, "lang": "c",
            "machine": "wingtip"}
    for entry in ({**base, "family": "gcc", "command": "cc -c"},
                  {**base, "family": "nvhpc", "command":
                   f"{GCC_SM80_ROOT}/bin/x86_64-pc-linux-gnu-gcc -c"},
                  {**base, "command": f"{GCC_SM80_ROOT}/bin/cpp"}):
        with pytest.raises(ValueError):
            W.validate({"x": entry})


def test_the_gate_prices_a_gcc_compile_from_its_measurements():
    """The estimate is of the order of the measured
    compiles (medians 0.3 s on Tioga, 0.8 s on wingtip), a few seconds."""
    from offload.engine import gate as G
    assert 0.3 <= G.COMPILE_S["gcc"] <= 5


def test_nvptx_unresolved_symbol_with_a_system_referrer_is_the_environment():
    """GCC: the referrer-less nvptx line counts as the program's,
    but a system file referencing an undefined symbol in the same output
    still makes it the environment."""
    from offload.engine.harness import _undefined_symbols
    text = ("unresolved symbol __atomic_compare_exchange_16\n"
            "/usr/bin/ld: /usr/lib64/libfoo.so: undefined reference to `bar'\n")
    assert _undefined_symbols(text)[0] == "environment"


def test_run_checks_drops_the_callers_libgomp_settings(monkeypatch):
    """GCC: the vendor-check runs drop GOMP_* and GCN_* as the
    harness does; the recipe's own environment is kept."""
    rc = _run_checks()
    monkeypatch.setenv("GOMP_DEBUG", "1")
    monkeypatch.setenv("GCN_STACK_SIZE", "9")
    env = rc.base_env({"LD_LIBRARY_PATH": "/x"})
    assert "GOMP_DEBUG" not in env and "GCN_STACK_SIZE" not in env
    assert env["LD_LIBRARY_PATH"] == "/x" and "PATH" in env


# --- probe and contention runs (tools/campaigns/gcc_probe.py) -----------------------------

def _probe():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "tools"))
    import gcc_probe
    return gcc_probe


def test_probe_run_class():
    P = _probe()
    assert P.run_class(0, "RESULT ran_on_host=0 check=pass\n", "") == "pass"
    assert P.run_class(0, "RESULT ran_on_host=1 check=pass\n", "") == "host"
    assert P.run_class(0, "RESULT ran_on_host=0 check=fail\n", "") == "wrong"
    assert P.run_class(None, "", "") == "timeout"
    assert P.run_class(1, "", "libgomp: OMP_TARGET_OFFLOAD is set to "
                       "MANDATORY, but device not found\n") == \
        "device_not_found"
    assert P.run_class(1, "", "libgomp: OMP_TARGET_OFFLOAD is set to "
                       "MANDATORY, but only the host device is available") \
        == "host_only"
    assert P.run_class(-11, "", "") == "crash"
    assert P.run_class(0, " bad=           0\n", "") == "pass"   # bad= form
    assert P.run_class(0, " bad=           3\n", "") == "wrong"
    assert P.run_class(2, "", "") == "exit"


def test_probe_summary():
    P = _probe()
    rows = [{"program": "x", "offload": "mandatory", "class": "pass"},
            {"program": "x", "offload": "mandatory", "class": "timeout"},
            {"program": "x", "offload": "unset", "class": "pass"}]
    assert P.summary(rows) == {"x mandatory": {"pass": 1, "timeout": 1},
                               "x unset": {"pass": 1}}


def test_probe_builds_an_openacc_file_as_openacc(tmp_path):
    P = _probe()
    acc = tmp_path / "d.f90"
    acc.write_text("program p\n  !$acc enter data copyin(x)\nend program p\n")
    omp = tmp_path / "t.c"
    omp.write_text("int main(void) {\n#pragma omp target\n  {}\n  return 0;\n}\n")
    assert P.model_of(acc) == "acc"
    assert P.model_of(omp) == "omp"


# ---- The generic reducer (offload.engine.reduce, tools/reduce.py) -----------------------------

import subprocess


from offload.engine import reduce as RD


# a padded reproducer of the map(always) finding: an unrelated kernel, extra
# clauses, an extra list item and an unused array around the one trigger
PADDED = """program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer :: a(n), b(n), unused(n)
  integer :: i, r, h, s
  a = [(i, i = 1, n)]
  b = 0
  r = 0
  s = 0
  h = -1
  !$omp target teams distribute parallel do map(tofrom: b) num_teams(2) thread_limit(32)
  do i = 1, n
    b(i) = 2 * a(i)
  end do
  !$omp end target teams distribute parallel do
  s = sum(b)
  !$omp target map(to: a, b) map(always, tofrom: r) map(tofrom: h) defaultmap(none)
    h = merge(1, 0, omp_is_initial_device())
    r = a(5) + mod(s, 7) * 0
  !$omp end target
  print '(a,i0,a,i0)', 'r= ', r, ' h= ', h
  print '(a,i0,a,a)', 'RESULT ran_on_host=', merge(1, 0, h == 1), ' check=', merge('pass', 'fail', r == 5 .and. h == 0)
end program p
"""

C_PADDED = """#include <stdio.h>
#include <omp.h>
int main(void) {
  int a[64], b[64], r = 0, h = -1, s = 0;
  for (int i = 0; i < 64; i++) { a[i] = i + 1; b[i] = 0; }
  #pragma omp target teams distribute parallel for map(tofrom: b) num_teams(2) thread_limit(32)
  for (int i = 0; i < 64; i++) b[i] = 2 * a[i];
  for (int i = 0; i < 64; i++) s += b[i];
  #pragma omp target map(to: a, b) map(always, tofrom: r) map(tofrom: h) defaultmap(none)
  {
    h = omp_is_initial_device();
    r = a[4] + (s % 7) * 0;
  }
  printf("r= %d h= %d\\n", r, h);
  printf("RESULT ran_on_host=%d check=%s\\n", h == 1, (r == 5 && h == 0) ? "pass" : "fail");
  return 0;
}
"""

NV = RD.Target("nvhpc", 0)
NV269 = RD.Target("nvhpc269", 0)


def _trigger(text: str) -> bool:
    """The defect's trigger: one target directive with map(always, tofrom:)
    after a map(to:) clause."""
    for ln in text.splitlines():
        s = ln.strip().lower()
        if not (s.startswith("!$omp target") or s.startswith("#pragma omp target")):
            continue
        if "map(to:" in s and "map(always, tofrom:" in s and \
                s.index("map(to:") < s.index("map(always, tofrom:"):
            return True
    return False


def _wrong_if_trigger(text: str, target: RD.Target):
    if "omp_is_initial_device" not in text:
        return "correct"          # the fallback flag went: the harness would read pass
    return "wrong_answer" if _trigger(text) else "correct"


def _witness_ok(text: str, lang: str):
    return True, []


REF_R5 = RD.FakeReference(lambda text: ({"r": "5"}, ""))    # the fake rows print r= 0 (wrong) or r= 5


def _judge(tmp_path, runner, targets=(NV,), witness=_witness_ok, **kw) -> RD.Judge:
    kw.setdefault("reference", REF_R5)
    return RD.Judge(runner, list(targets), RD.Signature("wrong_answer", "result ran_on_host=0 check=fail"),
                    "f90", witness=witness, rows_path=tmp_path / "candidates.jsonl",
                    name="t", **kw)


# --- signatures -----------------------------------------------------------------------

def test_signature_of_rows_uses_the_gate_class_and_the_normalized_line():
    wrong = RD.fake_row("wrong_answer", PADDED, NV)
    assert RD.signature(wrong) == RD.Signature("wrong_answer", "result ran_on_host=0 check=fail")
    ice1 = RD.fake_row("ice", PADDED, NV, msg="NVFORTRAN-F-0000-Internal compiler error. size 12 (/tmp/x1.f90: 17)")
    ice2 = RD.fake_row("ice", PADDED, NV269, msg="NVFORTRAN-F-0000-Internal compiler error. size 98 (/tmp/y7.f90: 3)")
    assert RD.signature(ice1).cls == "ice" and RD.signature(ice1) == RD.signature(ice2)
    rej = RD.fake_row("rejected", PADDED, NV, msg="NVFORTRAN-S-0155-Compiler failed to translate OpenMP region (/t/a.f90: 6)")
    assert RD.signature(rej).cls == "rejected" and RD.signature(rej) != RD.signature(ice1)
    crash = RD.fake_row("crash", PADDED, NV, msg="SIGSEGV")
    assert RD.signature(crash) == RD.Signature("crash", "SIGSEGV")
    assert RD.signature(RD.fake_row("timeout", PADDED, NV)) == RD.Signature("timeout", "timeout")
    err = RD.fake_row("run_error", PADDED, NV, msg="Accelerator Fatal Error: call to cuEventQuery returned error 700")
    assert RD.signature(err).cls == "run_error" and "exit_status" in RD.signature(err).key
    assert RD.signature(RD.fake_row("correct", PADDED, NV)).cls == "correct_on_device"
    assert str(RD.signature(crash)) == "crash: SIGSEGV"


def test_an_ignored_compile_note_does_not_change_the_signature():
    """NVHPC's 'not yet implemented, ignored' note makes the harness class
    accepted_ignored; the failure is the run's."""
    row = RD.fake_row("wrong_answer", PADDED, NV)
    row.update(outcome="accepted_ignored",
               reason="ignored: NVFORTRAN-W-0547-OpenMP feature, SAFELEN, not yet implemented in this version "
                      "of the compiler. (x.f90: 13); run: wrong_answer: check_fail: ran_on_host=0 check=fail")
    assert RD.signature(row) == RD.Signature("wrong_answer", "result ran_on_host=0 check=fail")
    good = RD.fake_row("correct", PADDED, NV)
    good.update(outcome="accepted_ignored", reason="ignored: NVFORTRAN-W-0547-...; run: correct_on_device: "
                "ran_on_host=0 check=pass")
    assert RD.run_class(good) == "correct_on_device"
    assert RD.signature(good).cls == "correct_on_device"


def test_signature_from_a_fuzz_campaign_record():
    rec = {"seed": 2019, "gen_version": "fuzz-1", "base": [], "check": "ok", "expected": 5,
           "results": {"nvhpc": {"toolchain": "nvhpc", "cls": "wrong_code", "reason": "checksum=1 ran_on_host=0 expected=5"},
                       "nvhpc269": {"toolchain": "nvhpc269", "cls": "agree", "reason": ""}}}
    found = RD.failures_of_record(rec, mode=0)
    assert [t.toolchain for t, _ in found] == ["nvhpc"]
    assert found[0][1] == RD.Signature("wrong_answer", "result ran_on_host=0 check=fail")


# --- steps ----------------------------------------------------------------------------

def test_steps_are_a_registered_table_ordered_by_level():
    names = [s.name for s in RD.steps_for("f90")]
    assert names and names == [s.name for s in sorted(RD.steps_for("f90"), key=lambda s: s.level)]
    assert {"block", "unwrap", "statement", "clause", "clause-item", "modifier", "expression"} <= set(names)

    @RD.step("test-only", level=2, langs=("c",))
    def _only_c(text, lang):
        return [RD.Candidate("nothing", text)]
    try:
        assert "test-only" in [s.name for s in RD.steps_for("c")]
        assert "test-only" not in [s.name for s in RD.steps_for("f90")]
    finally:
        RD.unregister("test-only")


def test_block_candidates_keep_fortran_balanced():
    cands = RD.candidates(PADDED, "f90", levels=(1,))
    whats = [c.what for c in cands]
    assert any(w.startswith("delete construct") for w in whats)
    assert any(w.startswith("unwrap") for w in whats)
    assert any(w.startswith("delete statement") for w in whats)
    for c in cands:
        assert c.text != PADDED
        assert c.text.lower().count("!$omp end target") == \
            len([ln for ln in c.text.lower().splitlines() if ln.strip().startswith("!$omp target")])
        assert c.text.count("end do") == len([ln for ln in c.text.splitlines() if ln.strip().startswith("do ")])
        assert "program p" in c.text and "end program p" in c.text and "RESULT" in c.text
    # a construct deletion removes the whole first kernel
    gone = next(c for c in cands if c.what.startswith("delete construct") and "distribute" in c.what)
    assert "b(i) = 2 * a(i)" not in gone.text and "!$omp target map(to: a, b)" in gone.text


def test_clause_candidates_fortran_and_c():
    for text, lang in ((PADDED, "f90"), (C_PADDED, "c")):
        cands = RD.candidates(text, lang, levels=(2,))
        texts = [c.text for c in cands]
        assert any("map(always, tofrom: r) map(tofrom: h) defaultmap(none)" in t and "map(to: a, b)" not in t
                   for t in texts), "delete one clause"
        assert any("map(to: a)" in t and "map(to: a, b)" not in t for t in texts), "drop a list item"
        assert any("map(tofrom: r)" in t and "map(always, tofrom: r)" not in t for t in texts), "drop a modifier"
        assert any("thread_limit" not in t for t in texts)
        for c in cands:
            assert c.text != text
            assert c.text.count("(") == c.text.count(")")
    # a C construct shortens to a prefix (the pragma stays on its loop)
    cs = RD.candidates(C_PADDED, "c", levels=(2,))
    assert any("#pragma omp target teams distribute map(tofrom: b)" in c.text for c in cs)


def test_expression_candidates_shrink_bounds_and_extents():
    assert RD.extent_literals(PADDED, "f90") == [64] and 5 in RD.index_literals(PADDED, "f90")
    assert RD.extent_literals(C_PADDED, "c") == [64] and RD.index_literals(C_PADDED, "c") == {4}
    assert RD.extent_literals(HAND_PADDED, "f90") == [64]
    small = PADDED.replace("n = 64", "n = 8")
    assert not any(c.what.startswith("halve") for c in RD.candidates(small, "f90", levels=(3,))), "a(5) needs n >= 5"
    f = RD.candidates(PADDED, "f90", levels=(3,))
    assert any("parameter :: n = 32" in c.text for c in f), "a parameter halves"
    assert any("r = a(5)\n" in c.text for c in f), "a sum becomes one operand"
    c = RD.candidates(C_PADDED, "c", levels=(3,))
    assert any("int a[32]" in c_.text for c_ in c)
    assert any("i < 32" in c_.text for c_ in c)
    assert any("r = a[4];" in c_.text for c_ in c)


# --- the judge ------------------------------------------------------------------------

def test_illegal_candidate_is_never_run(tmp_path):
    runner = RD.FakeRunner(_wrong_if_trigger)
    judge = _judge(tmp_path, runner, witness=lambda t, l: (False, ["rules: violates X"]))
    ok, why = judge(PADDED)
    assert not ok and "illegal" in why and runner.calls == 0


def test_a_changed_failure_is_rejected(tmp_path):
    def classify(text, target):
        return "rejected" if "thread_limit" not in text else "wrong_answer"
    judge = _judge(tmp_path, RD.FakeRunner(classify))
    assert judge(PADDED)[0]
    ok, why = judge(PADDED.replace(" thread_limit(32)", ""))
    assert not ok and "signature" in why and "rejected" in why


def test_the_failure_must_hold_on_every_target(tmp_path):
    def classify(text, target):
        return "wrong_answer" if target.toolchain == "nvhpc" else "correct"
    judge = _judge(tmp_path, RD.FakeRunner(classify), targets=(NV, NV269))
    ok, why = judge(PADDED)
    assert not ok and "nvhpc269" in why


def test_every_candidate_run_is_a_row(tmp_path):
    runner = RD.FakeRunner(_wrong_if_trigger)
    judge = _judge(tmp_path, runner)
    judge(PADDED)
    judge(PADDED.replace(" thread_limit(32)", ""))
    rows = [json.loads(ln) for ln in (tmp_path / "candidates.jsonl").read_text().splitlines()]
    assert len(rows) == 2 and {r["toolchain"] for r in rows} == {"nvhpc"}
    assert all(r["program_id"].startswith("t~c") and r["sha"] and r["outcome"] for r in rows)
    assert rows[0]["sha"] != rows[1]["sha"]


def test_the_judge_caches_by_text(tmp_path):
    runner = RD.FakeRunner(_wrong_if_trigger)
    judge = _judge(tmp_path, runner)
    judge(PADDED)
    judge(PADDED)
    assert runner.calls == 1


# --- the reduction --------------------------------------------------------------------

def test_reduction_shrinks_to_the_trigger_and_stays_legal(tmp_path):
    seen = []

    def witness(text, lang):
        seen.append(text)
        return True, []
    runner = RD.FakeRunner(_wrong_if_trigger)
    judge = _judge(tmp_path, runner, witness=witness)
    res = RD.reduce(PADDED, "f90", judge, checkpoint=tmp_path / "ck.json")
    out = res.text
    assert res.lines_after <= res.lines_before - 8, res.steps
    assert _trigger(out) and "omp_is_initial_device" in out
    if "a(5)" in out:        # the simplification may have made r = 5; while a(5) is read, n stays >= 5
        assert "n = 2" not in out and "n = 4" not in out, "an extent never shrinks below an index it is read at"
    assert "distribute" not in out, "the unrelated kernel is gone"
    assert "thread_limit" not in out and "defaultmap" not in out
    assert "unused" not in out, "the unused array is gone"
    assert "map(to: a, b)" not in out, "the list item nobody needs is gone"
    assert "map(always, tofrom: r)" in out
    assert "RESULT" in out and "end program p" in out
    # every text the judge ran had passed the witness first
    assert len(seen) >= runner.calls
    assert res.steps and res.candidates_judged == runner.calls
    assert res.budget_used["candidates"] == runner.calls


def test_reduction_is_deterministic_for_a_seed(tmp_path):
    a = RD.reduce(PADDED, "f90", _judge(tmp_path / "a", RD.FakeRunner(_wrong_if_trigger)), seed=3)
    b = RD.reduce(PADDED, "f90", _judge(tmp_path / "b", RD.FakeRunner(_wrong_if_trigger)), seed=3)
    assert a.text == b.text and a.steps == b.steps


def test_checkpoint_resumes_within_the_budget(tmp_path):
    ck = tmp_path / "ck.json"
    r1 = RD.FakeRunner(_wrong_if_trigger)
    j1 = _judge(tmp_path / "1", r1, budget=RD.Budget(candidates=4))
    part = RD.reduce(PADDED, "f90", j1, checkpoint=ck)
    assert part.stopped == "budget" and r1.calls <= 4
    saved = json.loads(ck.read_text())
    assert saved["text"] == part.text
    assert len(saved["tried"]) >= r1.calls         # candidates the flag or witness rejected are judged too
    seen2 = []

    def classify2(text, target):
        seen2.append(RD.sha(text))
        return _wrong_if_trigger(text, target)
    r2 = RD.FakeRunner(classify2)
    j2 = _judge(tmp_path / "2", r2)
    whole = RD.reduce(PADDED, "f90", j2, checkpoint=ck)
    assert whole.stopped == "done" and _trigger(whole.text), (whole.steps, whole.stopped)
    assert not (set(seen2) & set(saved["tried"])), "the resumed run reran a judged candidate"
    # the resumed run ends at a fixpoint: reducing its result again accepts nothing
    again = RD.reduce(whole.text, "f90", _judge(tmp_path / "3", RD.FakeRunner(_wrong_if_trigger)))
    assert again.steps == [], (whole.steps, again.steps)


def test_reduction_refuses_when_the_original_does_not_fail(tmp_path):
    judge = _judge(tmp_path, RD.FakeRunner(lambda t, g: "correct"))
    with pytest.raises(RD.NoFailure):
        RD.reduce(PADDED, "f90", judge)


# --- controls -------------------------------------------------------------------------

def test_controls_are_one_change_and_pass_on_every_target(tmp_path):
    reduced = RD.reduce(PADDED, "f90", _judge(tmp_path / "r", RD.FakeRunner(_wrong_if_trigger))).text
    runner = RD.FakeRunner(_wrong_if_trigger)
    judge = _judge(tmp_path / "c", runner, targets=(NV, NV269))
    ctls = RD.controls(reduced, "f90", judge)
    assert ctls, "the always modifier removed, or the clauses reordered"
    whats = [c.what for c in ctls]
    assert any("always" in w for w in whats)
    assert any("order" in w or "swap" in w for w in whats)
    for c in ctls:
        diff = RD.one_change(reduced, c.text)
        assert diff is not None, c.what                # exactly one line changed or removed
        assert not _trigger(c.text)
        assert "omp_is_initial_device" in c.text
        assert set(c.passed) == {"nvhpc/0", "nvhpc269/0"}
    # a control that passes on one release only is reported, not kept
    def classify(text, target):
        if _trigger(text):
            return "wrong_answer"
        return "correct" if target.toolchain == "nvhpc" else "wrong_answer"
    judge2 = _judge(tmp_path / "d", RD.FakeRunner(classify), targets=(NV, NV269))
    assert RD.controls(reduced, "f90", judge2) == []


def test_one_change_counts_lines():
    a = "x\ny\nz\n"
    assert RD.one_change(a, "x\nz\n") == "line 2 removed"
    assert RD.one_change(a, "x\nY\nz\n") == "line 2 changed"
    assert RD.one_change(a, "X\nY\nz\n") is None
    assert RD.one_change(a, a) is None
    # a block construct's directive and end directive are one construct
    blk = "program p\n!$omp target parallel\n  h = 1\n!$omp end target parallel\nend program p\n"
    assert RD.one_change(blk, "program p\n  h = 1\nend program p\n") == "directive pair removed"
    assert RD.one_change(blk, blk.replace("target parallel", "target")) == "directive pair changed"
    loop = "program p\n!$omp target parallel do\ndo i = 1, 2\nend do\nend program p\n"
    assert RD.one_change(loop, "program p\n!$omp target\ndo i = 1, 2\nend do\n!$omp end target\nend program p\n") \
        == "directive changed and end directive added"
    assert RD.one_change(blk, "program p\nend program p\n") is None
    # a continued directive is one logical line
    wrapped = ("program p\n!$omp target parallel do map(always, tofrom: hf1) defaultmap(to: scalar) &\n"
               "!$omp& reduction(min: r1a) depend(inout: r1a)\ndo i = 1, 2\nend do\nend program p\n")
    one = wrapped.replace(" &\n!$omp& reduction(min: r1a) depend(inout: r1a)", " reduction(min: r1a)")
    assert RD.one_change(wrapped, one) == "line 2 changed"


# --- the fuzz output contract ---------------------------------------------------------

FUZZ_TAIL = """  cs = 0
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o1(i), 8), 2147483629_8)
  end do
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', max(hf1, hf2, 0)
end program fuzz_prog
"""


def test_fuzz_contract_rewrites_the_result_line_with_the_reference():
    c = RD.FuzzContract(reference=lambda text: 785692182)
    assert c.applies(FUZZ_TAIL) and not c.applies(PADDED)
    out = c.prepare(FUZZ_TAIL)
    assert "RESULT checksum=" not in out
    assert "'checksum= ', cs" in out
    assert "'RESULT ran_on_host=', max(hf1, hf2, 0), ' check=', merge('pass', 'fail', cs == 785692182_8)" in out
    assert RD.FuzzContract(reference=lambda text: "no_value: x").prepare(FUZZ_TAIL) is None
    assert RD.PlainContract().prepare(PADDED) == PADDED


def test_elision_reference_uses_only_installed_compilers(monkeypatch):
    from offload.engine import expected as E
    seen = {}

    def fake(text, compilers=()):
        seen["compilers"] = compilers
        return E.Evidence("elision", "value", "checksum=42", "", ())
    monkeypatch.setattr(E, "elision_evidence", fake)
    monkeypatch.setattr(E, "AMDFLANG", "/nonexistent/amdflang")
    monkeypatch.setattr(E, "GFORTRAN", "/nonexistent/gfortran")
    assert "no elision compiler" in RD.elision_reference(FUZZ_TAIL)
    monkeypatch.setattr(E, "GFORTRAN", sys.executable)        # any installed file stands in
    assert RD.elision_reference(FUZZ_TAIL) == 42
    assert seen["compilers"] == ("gfortran",)


# --- rows in, rows out ----------------------------------------------------------------

def test_from_row_gives_the_program_target_and_signature(tmp_path):
    src = tmp_path / "p.f90"
    src.write_text(PADDED)
    rows = tmp_path / "rows.jsonl"
    r = RD.fake_row("wrong_answer", PADDED, NV)
    r.update(program_id="p", file=str(src))
    good = RD.fake_row("correct", PADDED, NV269)
    good.update(program_id="p", file=str(src))
    rows.write_text(json.dumps(r) + "\n" + json.dumps(good) + "\n")
    job = RD.from_rows([rows], "p", root=tmp_path)
    assert job.text == PADDED and job.lang == "f90"
    assert job.targets == [NV] and job.signature == RD.Signature("wrong_answer", "result ran_on_host=0 check=fail")
    with pytest.raises(RD.NoFailure):
        RD.from_rows([rows], "nobody", root=tmp_path)


def test_fuzz_min_minimize_runs_on_the_shared_driver(monkeypatch):
    from offload.engine import fuzz_min as fm
    called = []
    real = RD.greedy

    def spy(*a, **k):
        called.append(1)
        return real(*a, **k)
    monkeypatch.setattr(RD, "greedy", spy)
    src = FUZZ_SMALL
    oracle = lambda text: (True, "fake")           # noqa: E731
    oracle.calls = 0
    res = fm.minimize(src, oracle, workers=1, max_rounds=2)
    assert called and res.lines_after <= res.lines_before


FUZZ_SMALL = """program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 4
  integer :: o1(n)
  integer :: i, hf1
  integer(8) :: cs
  o1 = 0
  hf1 = 0
  ! fuzz: kernels
  !$omp target map(tofrom: o1, hf1)
    hf1 = merge(1, 0, omp_is_initial_device())
    do i = 1, n
      o1(i) = i
    end do
  !$omp end target
  ! fuzz: checksum
  cs = 0
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o1(i), 8), 2147483629_8)
  end do
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', max(hf1, 0)
end program fuzz_prog
"""


def test_the_device_flag_must_be_a_call_not_the_import(tmp_path):
    runner = RD.FakeRunner(lambda t, g: "wrong_answer")
    judge = _judge(tmp_path, runner)
    judge.device_flag = True
    gone = PADDED.replace("    h = merge(1, 0, omp_is_initial_device())\n", "    h = 0\n")
    assert "omp_is_initial_device" in gone          # the use line still names it
    ok, why = judge(gone)
    assert not ok and "flag" in why and runner.calls == 0
    assert RD.has_device_flag(PADDED) and not RD.has_device_flag(gone)


FUZZ_EMPTY_MODULE = """module fuzz_mod
  implicit none
contains
end module fuzz_mod
program fuzz_prog
  use omp_lib, only: omp_get_team_num, omp_is_initial_device
  implicit none
  integer :: hf1
  hf1 = 0
  ! fuzz: kernels
  !$omp target map(tofrom: hf1)
    hf1 = merge(1, 0, omp_is_initial_device())
  !$omp end target
  ! fuzz: checksum
  print '(a,i0,a,i0)', 'RESULT checksum=', 0, ' ran_on_host=', max(hf1, 0)
end program fuzz_prog
"""


def test_fuzz_tidy_removes_an_empty_module_and_unused_imports():
    cands = RD.candidates(FUZZ_EMPTY_MODULE, "f90", levels=(4,))
    texts = [c.text for c in cands]
    assert any("module fuzz_mod" not in t and "program fuzz_prog" in t for t in texts), "empty module"
    assert any("use omp_lib, only: omp_is_initial_device" in t for t in texts), "unused import name"
    assert all("omp_is_initial_device" in t for t in texts)


def test_fuzz_programs_use_the_fuzz_min_steps():
    names = [s.name for s in RD.steps_for("f90", FUZZ_SMALL)]
    assert names[0].startswith("fuzz") and "block" not in names
    cands = RD.candidates(FUZZ_SMALL, "f90", levels=(1, 2))
    assert any("delete clause" in c.what or "drop" in c.what for c in cands)


# --- the review's probes: the output oracle, the keys, flaky rows, resume -------------

# the map(always) finding padded with an unrelated kernel, an extra scalar, a temporary and an
# unused array; `r` must come out 5 (a(5)), `h` is the host flag
HAND_PADDED = """program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer :: a(64), b(64), unused(64)
  integer :: i, r, h, s, x
  a = [(i, i = 1, 64)]
  b = 0
  r = 0
  s = 0
  x = 1
  h = -1
  !$omp target teams distribute parallel do map(tofrom: b)
  do i = 1, 64
    b(i) = 2 * a(i)
  end do
  !$omp end target teams distribute parallel do
  s = sum(b)
  !$omp target map(to: a, x) map(always, tofrom: r) map(tofrom: h)
    h = merge(1, 0, omp_is_initial_device())
    r = a(5) + x - 1
  !$omp end target
  print '(a,i0,a,i0)', 'r= ', r, ' h= ', h
  print '(a,i0,a,a)', 'RESULT ran_on_host=', merge(1, 0, h == 1), ' check=', merge('pass', 'fail', r == 5 .and. h == 0)
end program p
"""


def _model_r(text: str) -> int:
    """What a conforming program computes for r: a(5) + x - 1 when that statement is there, else r's
    initial value (0) or nothing at all."""
    if "r = a(5) + x - 1" not in text:
        return 0 if "r = 0" in text else -99
    return 5 if "x = 1" in text else -98          # x undefined: some garbage


def _conforming_but_trigger(text: str, target: RD.Target):
    """A compiler that is right except for the finding: with the trigger present r keeps its host
    value (0 when initialised)."""
    r = 0 if _trigger(text) and "r = 0" in text else _model_r(text)
    if "omp_is_initial_device" not in text.replace("use omp_lib, only: omp_is_initial_device", ""):
        return "fell_back_to_host"
    row = RD.fake_row("wrong_answer" if r != 5 else "correct", text, target)
    row["stdout"] = f"r= {r} h= 0\n" + row["stdout"].splitlines()[-1] + "\n"
    return row


def _reference(text: str):
    return {"r": str(_model_r(text))}, ""


def _oracle_judge(tmp_path, runner=None, **kw) -> RD.Judge:
    return RD.Judge(runner or RD.FakeRunner(_conforming_but_trigger), [NV],
                    RD.Signature("wrong_answer", "result ran_on_host=0 check=fail"), "f90", witness=_witness_ok,
                    rows_path=tmp_path / "c.jsonl", name="hp", reference=RD.FakeReference(_reference), **kw)


def test_probe2_a_broken_computation_is_not_the_identical_failure(tmp_path):
    judge = _oracle_judge(tmp_path)
    ok, why = judge(HAND_PADDED)
    assert ok and "wrong: r=0" in judge.signature.key
    gone = HAND_PADDED.replace("    r = a(5) + x - 1\n", "")
    ok, why = judge(gone)
    assert not ok and "agrees with the reference" in why
    no_trigger = HAND_PADDED.replace(" map(always, tofrom: r)", " map(tofrom: r)")
    ok, why = judge(no_trigger)
    assert not ok and "correct_on_device" in why


def test_probe3_the_reduction_keeps_the_computation_and_the_trigger(tmp_path):
    res = RD.reduce(HAND_PADDED, "f90", _oracle_judge(tmp_path), checkpoint=tmp_path / "ck.json")
    out = res.text
    assert "r = a(5) + x - 1" in out and "x = 1" in out and "r = 0" in out
    assert _trigger(out) and "omp_is_initial_device" in out
    assert "distribute" not in out and "unused" not in out
    assert res.signature.key.endswith("wrong: r=0")


def test_probe1_an_assignment_that_is_read_is_never_deleted():
    cands = [c for c in RD.candidates(HAND_PADDED, "f90", levels=(1,)) if c.what.startswith("delete statement")]
    for c in cands:
        assert "x = 1" in c.text, c.what                              # x is read
        assert "r = a(5) + x - 1" in c.text, c.what                   # r is printed
        assert "h = merge(1, 0, omp_is_initial_device())" in c.text, c.what
        assert "a = [(i, i = 1, 64)]" in c.text, c.what               # a is read
    assert any("s = sum(b)" not in c.text for c in cands), "an assignment nothing reads goes"
    c_prog = "int main(void) {\n  int i = 0, r = 0;\n  while (i < 2) { i++; }\n  r = i;\n  printf(\"r= %d\\n\", r);\n  return 0;\n}\n"
    assert not any("i++" not in c.text for c in RD.candidates(c_prog, "c", levels=(1,)))


def test_a_wrong_answer_without_a_reference_is_refused(tmp_path):
    judge = RD.Judge(RD.FakeRunner(_conforming_but_trigger), [NV],
                     RD.Signature("wrong_answer", "result ran_on_host=0 check=fail"), "f90", witness=_witness_ok,
                     rows_path=tmp_path / "c.jsonl", name="hp")
    with pytest.raises(RD.NoReference):
        judge(HAND_PADDED)
    # the fuzz contract carries its own reference
    c = RD.FuzzContract(reference=lambda text: 0)
    j2 = RD.Judge(RD.FakeRunner(lambda t, g: "wrong_answer"), [NV],
                  RD.Signature("wrong_answer", "result ran_on_host=0 check=fail"), "f90", witness=_witness_ok,
                  rows_path=tmp_path / "f.jsonl", name="fz", contract=c)
    assert j2(FUZZ_SMALL)[0]


def test_a_wrong_answer_is_not_judged_by_an_oracle_when_another_failure_is_reduced(tmp_path):
    """A candidate that turns the reduced compile failure into a wrong answer is another failure, not a
    request for the output oracle (a HeCBench compile-failure reduction hit this)."""
    judge = RD.Judge(RD.FakeRunner(lambda t, g: "wrong_answer"), [NV], RD.Signature("ice", "x"), "f90",
                     witness=_witness_ok, rows_path=tmp_path / "c.jsonl", name="ice")
    ok, why = judge(HAND_PADDED)
    assert not ok and "signature" in why


def test_reference_selection_refuses_the_target_family():
    with pytest.raises(ValueError):
        RD.reference_for("host:nvhpc269", "f90", [NV])
    assert RD.reference_for(None, "f90", [NV]) is None
    assert RD.reference_for("elision", "f90", [NV]).name == "elision"
    with pytest.raises(ValueError):
        RD.reference_for("elision", "c", [NV])                # no C elision here
    assert RD.printed_values("r= 0 h= 1\nRESULT ran_on_host=0 check=fail\n", exclude={"h"}) == {"r": "0"}
    assert RD.flag_names(HAND_PADDED) == {"h"}


def test_elision_reference_ignores_the_flag_in_the_check_line(monkeypatch):
    """The hand-written findings use the host flag in their RESULT line; the
    elision analysis calls that inapplicable, but the reference compares
    the other printed values only."""
    from offload.engine import expected as E
    seen = {}

    def applicability(text, version=52):
        seen["text"] = text
        return E.Applicability(True, [], frozenset())
    monkeypatch.setattr(E, "elision_applicability", applicability)
    ran = {}

    def run_elided(text, c, extra=(), env=None, value=None):
        ran["text"] = text
        return "r= 5 s= 4160 h= 0\nRESULT ran_on_host=0 check=pass\n", ""
    monkeypatch.setattr(E, "run_elided", run_elided)
    monkeypatch.setattr(RD, "elision_compilers", lambda: ("gfortran",))
    vals, why = RD.ElisionReference().values(HAND_PADDED, "f90")
    assert vals == {"r": "5", "s": "4160"} and why == ""
    assert "h == 0" not in ran["text"], "the reference runs the flag-neutralized program"
    # the reference must pass its own check: a candidate whose check no longer holds is rejected
    monkeypatch.setattr(E, "run_elided", lambda text, c, extra=(), env=None, value=None: (
        "r= 5 s= 0 h= 0\nRESULT ran_on_host=0 check=fail\n", ""))
    vals, why = RD.ElisionReference().values(HAND_PADDED, "f90")
    assert vals is None and "self-check fails" in why
    monkeypatch.setattr(E, "run_elided", run_elided)
    # the analysis saw the program with the flag's uses neutralized (so its copy-semantics walk runs)
    # and the flag's assignment and the reads of r kept
    assert "h == 1" not in seen["text"] and "h == 0" not in seen["text"] and "' h= ', h" not in seen["text"]
    assert "h = merge(1, 0, omp_is_initial_device())" in seen["text"] and "'r= ', r" in seen["text"]
    monkeypatch.setattr(E, "elision_applicability", lambda text, version=52: E.Applicability(
        False, ["line 23: r is read on the host from a copy that differs from sequential execution"], frozenset()))
    vals, why = RD.ElisionReference().values(HAND_PADDED, "f90")
    assert vals is None and "copy that differs" in why
    fl = RD.flagless(HAND_PADDED)
    assert fl != HAND_PADDED and "  h = -1\n" in fl and "0 = -1" not in fl
    assert RD.flagless(FUZZ_SMALL).count("hf1") == 4        # declared, mapped, set to 0, set from the flag


def test_an_unmapped_flag_is_not_a_device_run(tmp_path):
    """With map(tofrom: h) gone the host h stays -1: the RESULT line still says ran_on_host=0, but the
    printed flag shows no device run reached the host."""
    def classify(text, target):
        row = RD.fake_row("wrong_answer", text, target)
        h = "0" if "map(tofrom: h)" in text else "-1"
        row["stdout"] = f"r= 0 h= {h}\nRESULT ran_on_host=0 check=fail\n"
        return row
    judge = _oracle_judge(tmp_path, RD.FakeRunner(classify))
    assert judge(HAND_PADDED)[0]
    ok, why = judge(HAND_PADDED.replace(" map(tofrom: h)", ""))
    assert not ok and "flag" in why


def test_probe4_run_error_and_crash_keys_carry_the_message():
    a = RD.fake_row("run_error", PADDED, NV, msg="Accelerator Fatal Error: call to cuEventQuery returned error 700 (CUDA_ERROR_ILLEGAL_ADDRESS)")
    b = RD.fake_row("run_error", PADDED, NV, msg="Fortran runtime error: Index '9' of dimension 1 of array 'a' above upper bound of 8")
    assert RD.signature(a) != RD.signature(b) and RD.signature(a).cls == "run_error"
    assert "cueventquery" in RD.signature(a).key and RD.signature(a).key.startswith("exit_status: 1")
    c1 = RD.fake_row("crash", PADDED, NV, msg="SIGSEGV")
    assert RD.signature(c1) == RD.Signature("crash", "SIGSEGV")
    c2 = dict(RD.fake_row("crash", PADDED, NV, msg="SIGSEGV"), stderr="--- run ---\nFortran runtime error: bad\n")
    assert RD.signature(c1) != RD.signature(c2) and RD.signature(c2).key.startswith("SIGSEGV")
    # the key is at least as fine as the gate's and the matrix's
    assert RD.signature(a).key.split(" | ")[0] == "exit_status: 1"


def test_probe5_a_timeout_needs_a_device_construct_left(tmp_path):
    hang = "program p\n  use omp_lib, only: omp_is_initial_device\n  implicit none\n  integer :: h\n  h = -1\n" \
           "  !$omp target parallel map(tofrom: h)\n    !$omp barrier\n    h = merge(1, 0, omp_is_initial_device())\n" \
           "  !$omp end target parallel\n  print '(a,i0,a,a)', 'RESULT ran_on_host=', h, ' check=', merge('pass', 'fail', h == 0)\nend program p\n"
    judge = RD.Judge(RD.FakeRunner(lambda t, g: "timeout"), [NV], RD.Signature("timeout", "timeout"), "f90",
                     witness=_witness_ok, rows_path=tmp_path / "t.jsonl", name="hang")
    assert judge(hang)[0]
    ok, why = judge(hang.replace("  !$omp target parallel map(tofrom: h)\n", "").replace("  !$omp end target parallel\n", ""))
    assert not ok and "device construct" in why


def test_probe7_a_flaky_row_is_not_the_failure(tmp_path):
    def flaky(text, target):
        row = RD.fake_row("wrong_answer", text, target)
        row.update(flaky=True, reason=row["reason"] + "; repeats: correct_on_device | wrong_answer")
        return row
    judge = _judge(tmp_path, RD.FakeRunner(flaky))
    ok, why = judge(PADDED)
    assert not ok and "flaky" in why


def test_probe6_a_compile_timeout_is_not_evidence(tmp_path):
    def slow(text, target):
        row = RD.fake_row("timeout", text, target)
        row.update(outcome="harness_error", reason="compile_timeout")
        return row
    judge = RD.Judge(RD.FakeRunner(slow), [NV], None, "f90", witness=_witness_ok, rows_path=tmp_path / "t.jsonl",
                     name="slow")
    ok, why = judge(PADDED)
    assert not ok and "not evidence" in why and judge.signature is None


def test_a_harness_error_row_is_rejected(tmp_path):
    def broken(text, target):
        row = RD.fake_row("wrong_answer", text, target)
        row.update(outcome="harness_error", reason="environment: no_gpu")
        return row
    judge = _judge(tmp_path, RD.FakeRunner(broken))
    ok, why = judge(PADDED)
    assert not ok and "harness error" in why


def test_probe8_resume_refuses_other_targets_or_signature(tmp_path):
    ck = tmp_path / "ck.json"
    RD.reduce(PADDED, "f90", _judge(tmp_path / "a", RD.FakeRunner(_wrong_if_trigger), budget=RD.Budget(candidates=3)),
              checkpoint=ck)
    with pytest.raises(RD.CheckpointMismatch):
        RD.reduce(PADDED, "f90", _judge(tmp_path / "b", RD.FakeRunner(_wrong_if_trigger), targets=(NV, NV269)),
                  checkpoint=ck)
    other = RD.Judge(RD.FakeRunner(_wrong_if_trigger), [NV], RD.Signature("crash", "SIGSEGV"), "f90",
                     witness=_witness_ok, rows_path=tmp_path / "c.jsonl", name="t")
    with pytest.raises(RD.CheckpointMismatch):
        RD.reduce(PADDED, "f90", other, checkpoint=ck)
    with pytest.raises(RD.CheckpointMismatch):
        RD.reduce(PADDED, "f90", _judge(tmp_path / "d", RD.FakeRunner(_wrong_if_trigger)), levels=(2,), checkpoint=ck)


def test_header_says_when_no_witness_ran():
    res = RD.Reduction("x", 10, 5, ["s"], "wrong_answer", 3, {"candidates": 3, "seconds": 1.0}, "done",
                       RD.Signature("wrong_answer", "k"))
    with_w = RD.reduction_header("n", "seed 1", [NV], res, Path("out"), "f90", RD.rules_witness.__name__)
    assert "legality rules witness" in with_w and "exploration" not in with_w
    without = RD.reduction_header("n", "seed 1", [NV], res, Path("out"), "f90", "none")
    assert "no legality witness: exploration only" in without and "passed the legality" not in without


# --- the mutation gaps -------------------------------------------------------------------

def test_controls_filters_candidates_that_are_not_one_change(tmp_path):
    @RD.step("two-change", level=0, langs=("f90",), controls=True)
    def two(text, lang):          # two directive lines changed: not one construct's pair
        return [RD.Candidate("two changes", text.replace(" thread_limit(32)", "").replace(" defaultmap(none)", ""))]
    try:
        reduced = PADDED
        judge = _judge(tmp_path, RD.FakeRunner(lambda t, g: "correct"))
        kept = RD.controls(reduced, "f90", judge, limit=50)
        assert not any(c.what == "two changes" for c in kept)
        assert "two changes" not in [c.what for c in RD.control_candidates(reduced, "f90")]
    finally:
        RD.unregister("two-change")


def test_the_order_seed_changes_the_candidate_order_not_the_result(tmp_path):
    seqs = {}
    for seed in (None, 3, 4):
        seen = []

        def classify(text, target, seen=seen):
            seen.append(RD.sha(text))
            return _wrong_if_trigger(text, target)
        res = RD.reduce(PADDED, "f90", _judge(tmp_path / str(seed), RD.FakeRunner(classify)), seed=seed)
        seqs[seed] = (tuple(seen), res.text)
    assert len({s for s, _ in seqs.values()}) == 3, "three different runner-call sequences"
    for _, text in seqs.values():            # greedy paths differ; every one ends at the trigger
        assert _trigger(text) and "distribute" not in text and "unused" not in text


def test_candidates_are_distinct():
    @RD.step("twice", level=1, langs=("f90",))
    def twice(text, lang):
        c = RD.Candidate("same", text.replace(" thread_limit(32)", ""))
        return [c, RD.Candidate("same again", c.text), RD.Candidate("unchanged", text)]
    try:
        cands = RD.candidates(PADDED, "f90", levels=(1,))
        texts = [c.text for c in cands]
        assert len(texts) == len(set(texts)) and PADDED not in texts
        assert [c.what for c in cands if c.what.startswith("same")] == ["same"]
    finally:
        RD.unregister("twice")


def test_a_seconds_budget_stops_the_run(tmp_path):
    import time as T

    def slow(text, target):
        T.sleep(0.01)
        return _wrong_if_trigger(text, target)
    judge = _judge(tmp_path, RD.FakeRunner(slow), budget=RD.Budget(seconds=0.015))
    res = RD.reduce(PADDED, "f90", judge)
    assert res.stopped == "budget" and res.candidates_judged <= 3


def test_c_controls(tmp_path):
    runner = RD.FakeRunner(_wrong_if_trigger)
    judge = RD.Judge(runner, [NV], RD.Signature("wrong_answer", "result ran_on_host=0 check=fail"), "c",
                     witness=_witness_ok, rows_path=tmp_path / "c.jsonl", name="c")
    ctls = RD.controls(C_PADDED, "c", judge)
    assert any("always" in c.what for c in ctls) and any("swap" in c.what for c in ctls)
    for c in ctls:
        assert RD.one_change(C_PADDED, c.text) is not None and not _trigger(c.text)


def test_harness_runner_check_refuses_what_this_node_cannot_run():
    r = RD.HarnessRunner()
    with pytest.raises(RD.RunnerUnavailable):
        r.check([RD.Target("no-such-toolchain", 0)])
    with pytest.raises(RD.RunnerUnavailable):
        r.check([RD.Target("nvhpc", 7)])


def test_fuzz_min_keeps_what_the_oracle_demands(monkeypatch):
    from offload.engine import fuzz_min as fm

    def oracle(text):
        return ("map(tofrom: o1, hf1)" in text and "o1(i) = i" in text), "fake"
    res = fm.minimize(FUZZ_SMALL, oracle, workers=1, max_rounds=5)
    assert "map(tofrom: o1, hf1)" in res.source and "o1(i) = i" in res.source
    assert res.lines_after < res.lines_before


# --- the tool and the guide -----------------------------------------------------------

def test_cli_help_explains_the_flow():
    out = subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "reduce.py"), "--help"],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    for word in ("--from-row", "--seed", "--program", "--target", "witness", "controls", "new_finding.py",
                 "checkpoint", "budget"):
        assert word in out.stdout, word


def test_contributing_has_the_reduce_runbook():
    doc = (ROOT / "docs" / "tooling" / "contributing.md").read_text()
    assert "Reduce a failing program" in doc
    sec = doc.split("Reduce a failing program", 1)[1]
    for word in ("tools/reduce.py", "--from-row", "--seed", "run_wingtip_reduce.sh", "new_finding.py",
                 "does not decide", "pdebug", "offload/engine/reduce.py"):
        assert word in sec, word


# ---- The vendor checks' runner (data/vendor/checks/run_checks.py): the run environment of a case ---------




def _rc():
    spec = importlib.util.spec_from_file_location("run_checks", ROOT / "data/vendor/checks/run_checks.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_run_sees_one_device_unless_the_case_asks_for_all():
    """Each run is pinned to the GPU it was given (ROCR_VISIBLE_DEVICES on AMD, CUDA_VISIBLE_DEVICES
    on wingtip); a case with `devices: {tc: all}` leaves every device of the node visible on that
    toolchain (the declare-mapper GCC finding faults on the MI250X only with all eight GCDs visible)."""
    RC = _rc()
    base = {"PATH": "/bin", "ROCR_VISIBLE_DEVICES": "0,1,2,3,4,5,6,7", "CUDA_VISIBLE_DEVICES": "0,1"}
    case = {"id": "x", "symptom": "crash:", "expect": "ok"}
    e = RC.run_env(case, "repro", "gcc_g90", "tioga", 3, 0, base)
    assert e["ROCR_VISIBLE_DEVICES"] == "3" and e["HSA_XNACK"] == "0" and e["OMP_TARGET_OFFLOAD"] == "mandatory"
    e = RC.run_env(case, "repro", "nvhpc", "wingtip", 2, 0, base)
    assert e["CUDA_VISIBLE_DEVICES"] == "2" and "HSA_XNACK" not in e
    allv = dict(case, devices={"gcc_g90": "all"})
    e = RC.run_env(allv, "repro", "gcc_g90", "tioga", 3, 0, base)
    assert "ROCR_VISIBLE_DEVICES" not in e and e["HSA_XNACK"] == "0"
    e = RC.run_env(allv, "control", "gcc_g90", "tioga", 3, 0, base)   # the control runs the same way
    assert "ROCR_VISIBLE_DEVICES" not in e
    e = RC.run_env(allv, "repro", "gcc_sm80", "wingtip", 1, 0, base)   # another toolchain: pinned
    assert e["CUDA_VISIBLE_DEVICES"] == "1"
    e = RC.run_env(dict(case, devices={"*": "all"}), "repro", "cce21", "tuolumne", 1, 1, base)
    assert "ROCR_VISIBLE_DEVICES" not in e and e["HSA_XNACK"] == "1"
    e = RC.run_env(dict(case, run_env={"X": "1"}), "repro", "afar", "tuolumne", 1, 1, base)
    assert e["X"] == "1" and e["ROCR_VISIBLE_DEVICES"] == "1"


# ---- A hung checker call fails the sample test instead of hanging it -----------------------------

import threading


from tests.bounded import bounded_map


def test_bounded_map_returns_in_order():
    assert bounded_map(lambda x: x * 2, range(20), workers=4) == \
        [x * 2 for x in range(20)]


def test_a_hang_fails_within_the_budget():
    gate = threading.Event()
    try:
        with pytest.raises(pytest.fail.Exception, match="a hang"):
            bounded_map(lambda x: gate.wait(30) if x == 3 else x, range(8),
                        workers=2, budget_s=0.5)
    finally:
        gate.set()


def test_flang_timeout_kills_the_whole_process_group(monkeypatch):
    """The flang call runs in a subshell (the prelude); a timeout kills
    the subshell's children too, and returns promptly."""
    import time
    from types import SimpleNamespace
    from offload.engine import flang_oracle as FO
    monkeypatch.setattr(FO, "_TC", SimpleNamespace(prelude="",
                                                   fc="sleep 60; true"))
    monkeypatch.setattr(FO, "_TIMEOUT", 1)
    t = time.monotonic()
    with pytest.raises(FO.FlangError, match="timed out"):
        FO._dump("program p\nend program p\n", 52, sema=True)
    assert time.monotonic() - t < 15
