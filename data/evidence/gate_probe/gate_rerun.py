#!/usr/bin/env python3
"""Rerun review-queue entries with the gate's own runner
(offload.engine.gate_stored.rerun, as tools/campaigns/gate.py run does) in fresh build
directories, REPEATS times each, with WORKERS concurrent reruns (the gate
ran 24 per node). Compute node only:
    python3 -I data/evidence/gate_probe/gate_rerun.py OUT.jsonl K[,K...] REPEATS WORKERS"""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def one(args):
    k, rep, root = args
    import jobs as J
    from offload.engine import gate as G
    from offload.engine import gate_stored as GS
    rec, item = J.queue()[k]
    env = dict(G.environments(item, root)[0])
    env["path"] = os.path.join(root, f"r{rep}", os.path.basename(env["path"]))
    os.makedirs(os.path.dirname(env["path"]), exist_ok=True)
    try:
        r = GS.rerun(item, env)
    except Exception as e:          # recorded
        r = {"outcome": "harness_error", "reason": repr(e)[:300]}
    r.update({"k": k, "cell": rec["cell"], "rep": rep,
              "observed": "|".join(G.observe(r))})
    return r


def main() -> int:
    out, ks, reps, workers = sys.argv[1], sys.argv[2], int(sys.argv[3]), \
        int(sys.argv[4])
    root = os.environ.get("T48_TMP") or "/tmp"
    tasks = [(int(k), r, root) for r in range(reps) for k in ks.split(",")]
    with ProcessPoolExecutor(workers) as ex, open(out, "a") as fh:
        for r in ex.map(one, tasks):
            fh.write(json.dumps(r) + "\n")
            fh.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
