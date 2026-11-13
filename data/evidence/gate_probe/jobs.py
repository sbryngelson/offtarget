"""The probe jobs of the gate's review queue entries (one JSON
line per job for data/evidence/gate_probe/probe.py). The queue entries are the
rerun rows of results/gate/verdicts.jsonl with legality_review set, in
the order (campaign, verdict, signature); a job names its entry by its
cell. Usage (login node, no compiler runs):
    python3 -I data/evidence/gate_probe/jobs.py OUT_DIR"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def queue() -> list[tuple[dict, dict]]:
    from offload.engine import gate_report as GP
    recs = [json.loads(x) for x in
            (ROOT / "results/gate/verdicts.jsonl").read_text().splitlines()]
    q = [r for r in recs if r.get("legality_review") and
         not r.get("inherited")]
    q.sort(key=lambda r: (r["campaign"], r["verdict"], r["signature"]))
    items = {}
    for c in sorted({r["campaign"] for r in q}):
        for it in GP._jl(GP.OUT / c / "plan.jsonl"):
            items[it["cell"]] = it
    return [(r, items[r["cell"]]) for r in q]


def program(rec: dict, item: dict):
    """(files [(name, text)], lang, model) of an entry's program."""
    from offload.engine import gate_report as GP
    from offload.engine.fuzz_base import split_bundle
    p = GP._program_of(rec, item)
    if p is None:
        return None
    if not isinstance(p, tuple):        # a stress program
        return [list(f) for f in p.files], p.lang, p.model
    text, lang = p[0], p[1]
    files = split_bundle(text)
    if files:
        return [list(f) for f in files], lang, p[2]
    name = "prog.c" if lang == "c" else "prog.f90"
    return [[name, text]], lang, p[2]


def instrumented(files: list) -> tuple[list, list]:
    import checksum_trace as T
    out, stmts = [], []
    for name, text in files:
        if T.MARK in text:
            text, stmts = T.instrument(text)
        out.append([name, text])
    return out, stmts


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    meta = []
    for k, (rec, item) in enumerate(queue()):
        p = program(rec, item)
        meta.append({"k": k, "cell": rec["cell"], "has_program":
                     p is not None})
    (out / "queue.json").write_text(json.dumps(meta, indent=1))
