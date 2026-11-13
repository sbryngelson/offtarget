#!/usr/bin/env python3
"""The reproduction gate (offload.engine.gate) over campaigns. Run on compute
nodes only (tools/jobs/run_gate.sh; wingtip: tools/jobs/run_wingtip_gate.sh).

    python3 -I tools/campaigns/gate.py apply-stored --campaign catalog|all
        [--budget-gpu-h 10] [--per-signature 3]
    python3 -I tools/campaigns/gate.py run --campaign catalog --machine tuolumne
        --envs a,b,d [--workers 24] [--limit-s 3000] [--shard 0/2]
    python3 -I tools/campaigns/gate.py report

apply-stored samples the stored failing rows of a campaign under its GPU-hour
budget (results/gate/<campaign>/plan.jsonl). run reruns the planned rows of
one machine in the given environments. report writes results/gate/verdicts.jsonl,
data/reports/gate-changes/<campaign>.tsv.
The budget (BUDGET_GPU_H) is a hard stop: run logs GPU-hours in
results/gate/ledger.jsonl and starts no rerun once it is reached."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine import gate as G          # noqa: E402
from offload.engine import gate_stored as GS  # noqa: E402

OUT = ROOT / "results" / "gate"
# the stated budget per campaign, GPU-hours
BUDGET_GPU_H = {"catalog": 12.0, "widen": 4.0, "stress": 5.0, "fuzz": 6.0,
                "evidence": 3.0}
RERUNS_PER_GPU = {"tuolumne": 2, "tioga": 2, "wingtip": 1}
GPUS_PER_NODE = {"tuolumne": 4, "tioga": 4, "wingtip": 1}
OVERHEAD = 0.15                 # queue wait and idle tail, of the budget
BASE_WORKERS = 8                # per node: the limits hold at this load
LEDGER = OUT / "ledger.jsonl"


def spent_gpu_h(camp: str) -> float:
    """GPU-hours the ledger records for a campaign."""
    return sum(float(d.get("gpu_h") or 0) for d in _jl(LEDGER)
               if d.get("campaign") == camp)


# measured busy GPU-hours over the model's estimate, per campaign (for example the linter KB rerun): the model prices a catalog-style run failure at its full
# run limit, which most runs do not reach, and underprices the stress and
# fuzz compiles
CALIBRATION = {"catalog": 0.23, "widen": 0.23, "canary": 0.23,
               "fuzz": 1.08, "stress": 1.38, "evidence": 0.75}


def gpu_cost_s(item: dict) -> float:
    """GPU-seconds of one rerun of an item on its machine (the model's
    estimate times its campaign's measured calibration)."""
    return G.cost_s(item) / RERUNS_PER_GPU.get(item.get("machine"), 6) * \
        CALIBRATION.get(item.get("campaign") or item.get("kind"), 1.0)


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


def known_signatures(exclude: str) -> set:
    """Signatures gated before (by an earlier plan whose reruns gave a
    verdict): not 'new'."""
    out = set()
    for d in G.load_verdicts().values():
        if d.get("campaign") != exclude and d.get("signature") and \
                not d.get("inherited"):
            out.add(d["signature"])
    return out


def cmd_apply_stored(a) -> int:
    camps = GS.CAMPAIGNS if a.campaign == "all" else [a.campaign]
    for camp in camps:
        stats: dict = {}
        items = GS.items(camp, stats)
        budget_h = a.budget_gpu_h if a.budget_gpu_h is not None else \
            BUDGET_GPU_H[camp]
        budget_s = budget_h * 3600
        p = G.plan(items, budget_s, a.per_signature,
                   known=known_signatures(camp), cost=gpu_cost_s,
                   overhead_s=OVERHEAD * budget_s)
        d = OUT / camp
        d.mkdir(parents=True, exist_ok=True)
        with (d / "plan.jsonl").open("w") as fh:
            for r in p["rows"]:
                fh.write(json.dumps(r) + "\n")
        summary = {
            "campaign": camp, "rows": len(p["rows"]),
            "signatures": len({r["signature"] for r in p["rows"]}),
            "budget_gpu_h": budget_h, "per_signature": a.per_signature,
            "reruns_per_gpu": RERUNS_PER_GPU,
            "planned_gpu_h": round(p["spent_s"] / 3600, 2),
            "all_rows_gpu_h": round(p["total_s"] / 3600, 2),
            "over_budget": p["over_budget"],
            "overhead_gpu_h": round(OVERHEAD * budget_s / 3600, 2),
            "sample": {k: sum(r["sample"] == k for r in p["rows"])
                       for k in ("all", "own", "new", "runtime", "sampled",
                                 "inherited", "unchecked")},
            "by_machine": {m: sum(r["machine"] == m and r["sample"] not in
                                  ("inherited", "unchecked", "own")
                                  for r in p["rows"])
                           for m in ("tuolumne", "tioga", "wingtip")},
            "stats": stats, "date": time.strftime("%Y-%m-%dT%H:%M:%S")}
        (d / "plan.json").write_text(json.dumps(summary, indent=1) + "\n")
        print(json.dumps(summary))
    return 0


def _done(camp: str) -> set:
    """(cell, env) with a valid rerun; a (c) counts only in the path of
    the cell's (a) and on another node (any other (c) is run
    again)."""
    a_runs = _a_runs(camp)
    out = set()
    for p in sorted((OUT / camp / "reruns").glob("*.jsonl")):
        for r in _jl(p):
            if G.outcome_class(r) not in G.NOT_EVIDENCE and \
                    not G.killed(r):
                a = a_runs.get(r["cell"])
                if r["env"] == "c" and a and (
                        r.get("path") != a["path"] or
                        G.node_key(r.get("node")) ==
                        G.node_key(a.get("node"))):
                    continue
                out.add((r["cell"], r["env"]))
    return out


def _a_runs(camp: str) -> dict:
    """cell -> its recorded valid (a) rerun."""
    out = {}
    for p in sorted((OUT / camp / "reruns").glob("*.jsonl")):
        for r in _jl(p):
            if r.get("env") == "a" and r.get("path") and \
                    G.outcome_class(r) not in G.NOT_EVIDENCE:
                out[r["cell"]] = r
    return out


def _a_paths(camp: str) -> dict:
    """cell -> the build path of its recorded (a) rerun: (c) runs in it
    (a (c) in another path confounds node and path)."""
    return {c: r["path"] for c, r in _a_runs(camp).items()}


def _here() -> str:
    from offload.engine.provenance import node as _node
    node = _node()
    if os.environ.get("COMPLIANT_RUN_SLOTS"):
        node = f"{node}:gpu{os.environ.get('CUDA_VISIBLE_DEVICES', 'all')}"
    return node


def _task(args) -> list[dict]:
    item, envs, root, a_path = args
    out = []
    for env in G.environments(item, root):
        if env["env"] not in envs:
            continue
        made = None
        if env["env"] == "c" and a_path:
            env = dict(env, path=a_path)
            made = a_path
            os.makedirs(os.path.dirname(a_path), exist_ok=True)
        try:
            r = GS.rerun(item, env)
        except Exception as e:           # recorded, never dropped
            import traceback
            r = {"env": env["env"], "path": env["path"],
                 "outcome": "harness_error",
                 "reason": f"gate runner: {e!r}"[:300],
                 "traceback": traceback.format_exc()[-1500:]}
        if made:
            # (a)'s build directory, made again here for (c): removed (its
            # parent, an earlier job's root, is removed empty by the job
            # script)
            import shutil
            shutil.rmtree(made, ignore_errors=True)
        r["cell"] = item["cell"]
        r["campaign"] = item["campaign"]
        r["environment"] = env["environment"]
        if os.environ.get("COMPLIANT_RUN_SLOTS"):
            # one host (wingtip): (c) is another GPU
            r["node"] = f"{r.get('node', '')}:gpu" \
                f"{os.environ.get('CUDA_VISIBLE_DEVICES', 'all')}"
        out.append(r)
    return out


def cmd_run(a) -> int:
    from concurrent.futures import (FIRST_COMPLETED,
                                    ProcessPoolExecutor, wait)
    camp = a.campaign
    envs = tuple(a.envs.split(","))
    plan = [r for r in _jl(OUT / camp / "plan.jsonl")
            if r["sample"] not in ("inherited", "unchecked", "own")
            and r["machine"] == a.machine]
    if a.shard:
        k, n = map(int, a.shard.split("/"))
        import zlib
        plan = [r for r in plan if zlib.crc32(r["cell"].encode()) % n == k]
    done = _done(camp)
    # tasks: (a, d) in one task, in order (one path: never at once), (b)
    # and (c) each in its own
    todo = []
    for r in plan:
        for group in (("a", "d"), ("b",), ("c",)):
            want = tuple(e for e in group if e in envs and
                         (r["cell"], e) not in done)
            if want:
                todo.append((r, want))
    # the plan's order of tiers (new defect signatures, run-time rows,
    # samples), the cheapest first within a tier: a stop cuts the
    # expensive tail of the last tier
    tier = {"all": 0, "new": 0, "runtime": 1, "sampled": 2}
    todo.sort(key=lambda t: (tier.get(t[0]["sample"], 3),
                             G.cost_s(t[0]) * len(t[1])))
    root = G.gate_tmp()
    a_paths = _a_paths(camp) if "c" in envs else {}
    if "c" in envs:
        # (c) is another node (wingtip: another GPU) than the row's (a):
        # a row whose (a) ran here is left to the other half's job
        a_node = {c: r.get("node") for c, r in _a_runs(camp).items()}
        here = _here()
        same = [t for t in todo if "c" in t[1] and
                G.node_key(a_node.get(t[0]["cell"])) == G.node_key(here)]
        if same:
            print(f"{len(same)} rows' (a) ran on {here}: their (c) is "
                  "left to another node", flush=True)
        todo = [t for t in todo if t not in same]
    os.environ["GATE_LOAD_FACTOR"] = str(max(1.0, a.workers / BASE_WORKERS))
    # the hard stop: no rerun starts once the campaign's ledger reaches
    # its budget (this run's own GPU-hours counted as it goes)
    budget_h = a.budget_gpu_h if a.budget_gpu_h is not None else \
        BUDGET_GPU_H.get(camp, 0)
    gpus = a.gpus or GPUS_PER_NODE.get(a.machine, 4)
    left_h = budget_h - spent_gpu_h(camp)
    if left_h <= 0:
        print(f"{camp}: budget {budget_h} GPU-h spent (ledger): nothing "
              "started", flush=True)
        return 0
    limit_s = left_h * 3600 / (gpus * max(1, a.concurrent))
    if a.limit_s:
        limit_s = min(limit_s, a.limit_s)
    d = OUT / camp / "reruns"
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"{os.uname().nodename}.{''.join(envs)}.{os.getpid()}.jsonl"
    t0 = time.time()
    print(f"{camp} {a.machine} envs {','.join(envs)}: {len(todo)} tasks "
          f"of {len(plan)} planned rows, {a.workers} workers, "
          f"root {root}", flush=True)
    n = 0
    with ProcessPoolExecutor(a.workers) as ex, out.open("a") as fh:
        futs = {}
        it = iter(todo)

        def submit() -> bool:
            if time.time() - t0 > limit_s:
                return False
            nxt = next(it, None)
            if nxt is None:
                return False
            item, want = nxt
            futs[ex.submit(_task, (item, want, root,
                                   a_paths.get(item["cell"])))] = item
            return True
        for _ in range(a.workers * 2):
            if not submit():
                break
        while futs:
            finished, _ = wait(list(futs), return_when=FIRST_COMPLETED)
            for f in finished:
                futs.pop(f)
                for r in f.result():
                    fh.write(json.dumps(r) + "\n")
                fh.flush()
                n += 1
                if n % 25 == 0:
                    print(f"{n}/{len(todo)} in {time.time() - t0:.0f} s",
                          flush=True)
                submit()
    secs = time.time() - t0
    with LEDGER.open("a") as fh:
        fh.write(json.dumps({"campaign": camp, "machine": a.machine,
                             "node": os.uname().nodename, "envs": a.envs,
                             "gpus": gpus, "seconds": round(secs),
                             "gpu_h": round(secs * gpus / 3600, 3),
                             "tasks": n, "workers": a.workers,
                             "date": time.strftime("%Y-%m-%dT%H:%M:%S")})
                 + "\n")
    print(f"done {n} rows in {secs:.0f} s -> {out}", flush=True)
    return 0


def cmd_canaries(a) -> int:
    """Measure the canaries of toolchains and modes here (their rows to
    --out; the differences from catalog/canaries.yaml printed)."""
    from concurrent.futures import ThreadPoolExecutor
    from offload.engine import canary
    cells = [(t, x) for t in a.toolchains for x in a.xnack]
    with ThreadPoolExecutor(len(cells)) as ex:
        res = list(ex.map(lambda c: canary.run_for(c[0], c[1], a.timeout),
                          cells))
    rows = [r for rs in res for r in rs]
    canary.write(rows, Path(a.out))
    for r in rows:
        print(r["toolchain"], r["xnack"], r["canary"], r["outcome"],
              (r.get("reason") or "")[:100])
    bad = canary.check(rows)
    print("CHANGED:\n  " + "\n  ".join(bad) if bad else "all canaries "
          "as in catalog/canaries.yaml")
    return 1 if bad else 0


def cmd_findings(a) -> int:
    """Gate findings' reproducers (the legality review of a finding whose
    linked cells the gate did not confirm): plan them into
    results/gate/findings/plan.jsonl (--plan), or report the verdicts of
    their reruns (--verdicts; the original is the rerun in (a))."""
    d = OUT / "data" / "findings"
    if a.plan:
        d.mkdir(parents=True, exist_ok=True)
        items = GS.finding_items(a.plan)
        old = {r["cell"]: r for r in _jl(d / "plan.jsonl")}
        old.update({r["cell"]: r for r in items})
        (d / "plan.jsonl").write_text("".join(json.dumps(r) + "\n"
                                              for r in old.values()))
        (d / "plan.json").write_text(json.dumps({
            "campaign": "findings", "rows": len(old), "signatures":
            len(old), "budget_gpu_h": 0, "planned_gpu_h": 0,
            "sample": {"all": len(old)}, "by_machine": {},
            "date": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
        print(f"{len(items)} items planned -> {d / 'plan.jsonl'}")
        return 0
    from offload.engine import gate_report as GP
    reruns = GP._reruns("findings")
    out = []
    for item in _jl(d / "plan.jsonl"):
        rs = reruns.get(item["cell"], [])
        a_run = next((r for r in rs if r["env"] == "a"), None)
        if a_run is None:
            v = {"verdict": None, "missing": list(G.ENVS)}
        else:
            try:
                v = G.judge(a_run, rs)
            except ValueError:
                v = {"verdict": None}
        out.append({"cell": item["cell"], **{k: v.get(k) for k in (
            "verdict", "missing", "condition")},
            "reruns": [f"{r['env']}:{'|'.join(G.observe(r))[:80]}"
                       for r in rs]})
        print(json.dumps(out[-1]))
    (d / "verdicts.jsonl").write_text("".join(json.dumps(r) + "\n"
                                              for r in out))
    return 0


def cmd_report(a) -> int:
    from offload.engine import gate_report as GP
    camps = GS.CAMPAIGNS if not a.campaign else a.campaign
    GP.report(camps, prerun=not a.no_prerun)
    return 0


def cmd_rules_pass(a) -> int:
    """The static rules pass over the programs of the gated
    rows (results/gate/<campaign>/illegal.jsonl; compute node)."""
    from offload.engine import gate_report as GP
    camps = GS.CAMPAIGNS if not a.campaign else a.campaign
    for camp in camps:
        print(camp, json.dumps(GP.rules_pass(camp, a.workers)), flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("apply-stored")
    p.add_argument("--campaign", required=True,
                   choices=list(GS.CAMPAIGNS) + ["all"])
    p.add_argument("--budget-gpu-h", type=float)
    p.add_argument("--per-signature", type=int, default=G.PER_SIGNATURE)
    r = sub.add_parser("run")
    r.add_argument("--campaign", required=True,
                   choices=list(GS.CAMPAIGNS) + ["findings"])
    r.add_argument("--machine", required=True)
    r.add_argument("--envs", default="a,b,d")
    r.add_argument("--workers", type=int, default=BASE_WORKERS,
                   help="per node (more scale the time limits)")
    r.add_argument("--limit-s", type=float, default=0,
                   help="submit no new row after this many seconds")
    r.add_argument("--shard")
    r.add_argument("--budget-gpu-h", type=float,
                   help="the campaign's budget (default BUDGET_GPU_H)")
    r.add_argument("--gpus", type=int, default=0,
                   help="GPUs this run holds (default: the machine's per "
                   "node)")
    r.add_argument("--concurrent", type=int, default=1,
                   help="runs of this campaign at once (they share the "
                   "budget left)")
    fd = sub.add_parser("findings")
    g = fd.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan", nargs="+", metavar="FINDING")
    g.add_argument("--verdicts", action="store_true")
    cn = sub.add_parser("canaries")
    cn.add_argument("--toolchains", nargs="+", required=True)
    cn.add_argument("--xnack", type=int, nargs="+", required=True)
    cn.add_argument("--timeout", type=int, default=120)
    cn.add_argument("--out", required=True)
    rp = sub.add_parser("report")
    rp.add_argument("--campaign", nargs="*")
    rp.add_argument("--no-prerun", action="store_true")
    rl = sub.add_parser("rules-pass")
    rl.add_argument("--campaign", nargs="*")
    rl.add_argument("--workers", type=int, default=16)
    a = ap.parse_args(argv)
    return {"apply-stored": cmd_apply_stored, "run": cmd_run,
            "canaries": cmd_canaries, "findings": cmd_findings,
            "report": cmd_report, "rules-pass": cmd_rules_pass}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
