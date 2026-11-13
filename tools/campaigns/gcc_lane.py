#!/usr/bin/env python3
"""The GCC lane (gcc_g90 on Tioga, gcc_sm80 on wingtip): the reproduction
gate over its own rows, and repeat runs of programs that fail sometimes.
Rows stay in results/gcc/<toolchain>/ (tools/jobs/run_gcc_full.sh);
``tools/campaigns/run_matrix.py replace`` merges them into the full results.
The gate (offload.engine.gate) keeps its files under results/gcc/gate/<campaign>/.

    python3 -I tools/campaigns/gcc_lane.py gate-plan
    python3 -I tools/campaigns/gcc_lane.py gate-run --machine wingtip --envs a,b,d \\
        --workers 2 --limit-s 3600        # wingtip: one GPU, run lock
    python3 -I tools/campaigns/gcc_lane.py gate-run --machine tioga --envs a,b,d \\
        --workers 8 --limit-s 3000        # Tioga: inside one batch job
    python3 -I tools/campaigns/gcc_lane.py gate-verdicts
    python3 -I tools/campaigns/gcc_lane.py repeat --toolchain gcc_g90 --runs 15 \\
        --programs omp50-clause-depend-out ...   # results/gcc/<tc>/repeat.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]

LANE = ROOT / "results" / "gcc"
GATE = LANE / "gate"
from offload.engine.toolchains import registry as _registry  # noqa: E402
# the lane's toolchains: GCC's catalog entries of lane `gcc` (MI300A, Tioga's MI250X, wingtip's A100)
TOOLCHAINS = _registry().of_lane("gcc")
TAGS = ("f90", "c", "acc", "accc")
CAMPAIGNS = ("catalog",)


def catalog_files(toolchains=TOOLCHAINS) -> list[str]:
    """The lane's full-catalog row files, relative to results/: one per set and memory mode."""
    from offload.engine.toolchains import TOOLCHAINS as _TC
    return [f"gcc/{tc}/matrix.{t}.x{x}.jsonl" for tc in toolchains
            for x in sorted(_TC[tc].xnack_modes) for t in TAGS]


def _jl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out = []
    for ln in path.read_text().splitlines():
        if ln.strip():
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                pass
    return out


def items(camp: str) -> list[dict]:
    """The failing legal GCC rows of a campaign as gate items
    (offload.engine.gate_stored.harness_items on the lane's files)."""
    from offload.engine import gate_stored as GS
    return [it for it in GS.harness_items(camp, catalog_files())
            if it["toolchain"] in TOOLCHAINS]


def cmd_gate_plan(a) -> int:
    from offload.engine import gate as G
    for camp in CAMPAIGNS:
        p = G.plan(items(camp), budget_s=float("inf"))
        d = GATE / camp
        d.mkdir(parents=True, exist_ok=True)
        (d / "plan.jsonl").write_text("".join(json.dumps(r) + "\n"
                                              for r in p["rows"]))
        print(camp, len(p["rows"]), "rows,",
              Counter((r["machine"], r["sample"]) for r in p["rows"]),
              f"{p['total_s'] / 3600:.2f} serial rerun hours")
    return 0


def cmd_gate_run(a) -> int:
    """tools/campaigns/gate.py run on the lane's plan (its output paths patched to
    results/gcc/gate; no budget: the lane's plan is its budget)."""
    import gate as GT                       # tools/campaigns/gate.py
    GT.OUT = GATE
    GT.LEDGER = GATE / "ledger.jsonl"
    ns = argparse.Namespace(campaign=a.campaign, machine=a.machine,
                            envs=a.envs, shard=a.shard, workers=a.workers,
                            limit_s=a.limit_s, budget_gpu_h=1e9, gpus=1,
                            concurrent=a.workers)
    return GT.cmd_run(ns)


def reruns_of(camp: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for p in sorted((GATE / camp / "reruns").glob("*.jsonl")):
        for r in _jl(p):
            out[r["cell"]].append(r)
    return out


def verdicts(camp: str) -> dict[str, dict]:
    """cell -> the gate's judgement (offload.engine.gate.judge) of each planned
    row; a row without its four environments has verdict None."""
    from offload.engine import gate as G
    rr = reruns_of(camp)
    out = {}
    for it in _jl(GATE / camp / "plan.jsonl"):
        try:
            v = G.judge(it, rr.get(it["cell"], []))
        except ValueError:
            v = {"verdict": None, "missing": list(G.ENVS)}
        out[it["cell"]] = {"cell": it["cell"], "campaign": camp,
                           "toolchain": it["toolchain"], "ident": it["ident"],
                           "outcome": it["outcome"],
                           "reason": (it.get("reason") or "")[:300],
                           "signature": it.get("signature"), **v}
    return out


def cmd_gate_verdicts(a) -> int:
    rows = []
    for camp in CAMPAIGNS:
        rows += list(verdicts(camp).values())
    GATE.mkdir(parents=True, exist_ok=True)
    (GATE / "verdicts.jsonl").write_text("".join(json.dumps(r) + "\n"
                                                 for r in rows))
    print(Counter((r["campaign"], r["toolchain"], r["verdict"]) for r in rows))
    return 0


# --- repeat runs ----------------------------------------------------------------

def repeat_summary(rows: list[dict]) -> dict:
    """program -> counts of each run's class (``pass``: correct on the
    device; ``timeout``; ``wrong``: any other failure) over its repeat rows
    (one row per run)."""
    out: dict = {}
    for r in rows:
        c = out.setdefault(r["program_id"], Counter())
        if r["outcome"] in ("correct_on_device", "unobservable"):
            c["pass"] += 1
        elif "timeout" in (r.get("reason") or ""):
            c["timeout"] += 1
        else:
            c["wrong"] += 1
        c["runs"] += 1
    return {k: dict(v) for k, v in out.items()}


def cmd_repeat(a) -> int:
    """Each program `runs` times on one toolchain through the harness, one
    run per call (repeats=1: a timeout does not stop the series), one row
    per run in results/gcc/<tc>/repeat.jsonl."""
    import dataclasses
    from offload.engine import harness as H
    from offload.engine.confirm.execute import toolchain_for
    from offload.engine.confirm.programs import catalog_program, catalog_ref
    out = LANE / a.toolchain / "repeat.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a") as fh:
        for pid in a.programs:
            prog = catalog_program(pid)
            tc = toolchain_for(catalog_ref(pid, prog), a.toolchain)
            for k in range(a.runs):
                r = H.run_program(prog, tc, 0, "-O2", timeout_s=a.timeout,
                                  repeats=1)
                d = {**dataclasses.asdict(r), "outcome": str(r.outcome),
                     "run": k}
                fh.write(json.dumps(d) + "\n")
                fh.flush()
                print(pid, k, d["outcome"], d["reason"][:80], flush=True)
    rows = [r for r in _jl(out) if r["program_id"] in a.programs]
    print(json.dumps(repeat_summary(rows), indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gate-plan")
    r = sub.add_parser("gate-run")
    r.add_argument("--campaign", default="catalog", choices=list(CAMPAIGNS))
    r.add_argument("--machine", required=True, choices=("tioga", "wingtip"))
    r.add_argument("--envs", default="a,b,d")
    r.add_argument("--shard")
    r.add_argument("--workers", type=int, default=2)
    r.add_argument("--limit-s", type=float, default=3600)
    sub.add_parser("gate-verdicts")
    p = sub.add_parser("repeat")
    p.add_argument("--toolchain", required=True, choices=TOOLCHAINS)
    p.add_argument("--programs", nargs="+", required=True)
    p.add_argument("--runs", type=int, default=15)
    p.add_argument("--timeout", type=int, default=120)
    a = ap.parse_args(argv)
    return {"gate-plan": cmd_gate_plan, "gate-run": cmd_gate_run,
            "gate-verdicts": cmd_gate_verdicts, "repeat": cmd_repeat}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
