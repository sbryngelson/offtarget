#!/usr/bin/env python3
"""The leads of runs (offload.engine.leads): each failure checked against the catalog's findings,
grouped by signature; known, related and new groups, each new one with the program to reduce.

    python3 -I tools/campaigns/leads.py scan RUN_DIR [RUN_DIR ...]   # results/fuzz/<run>
    python3 -I tools/campaigns/leads.py plan RUN_DIR [RUN_DIR ...]   # the reduction queue
    python3 -I tools/campaigns/leads.py reduce [--minutes M]          # a compute node: run the queue
    python3 -I tools/campaigns/leads.py recheck                       # the reduced programs vs the catalog
    python3 -I tools/campaigns/leads.py advance [--minutes M]         # a compute node: the confirmer on new ones

scan writes results/leads/<campaign>.jsonl (one group per line) and prints the counts and the new and
mixed groups. plan appends a tools/reduce.py command per new or mixed group to results/leads/queue.jsonl;
reduce runs the unfinished ones in order within M minutes (tools/jobs/run_leads_reduce.sh; each
reduction resumes from its checkpoint); recheck asks the catalog again about each finished reduction
and writes results/leads/rechecked.jsonl."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from offload.engine import leads as LD  # noqa: E402

OUT = ROOT / "results" / "leads"


def scan(run_dir: Path) -> list:
    groups = LD.fuzz_groups(run_dir)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"fuzz-{Path(run_dir).name}.jsonl"
    with path.open("w") as fh:
        for g in groups:
            rep = g.representative.failure
            fh.write(json.dumps({"family": g.family, "signature": g.signature, "status": g.status,
                                 "findings": list(g.findings), "failures": len(g.leads),
                                 "unexplained": sorted({lead.failure.program_id for lead in g.unexplained}, key=int),
                                 "programs": sorted({lead.failure.program_id for lead in g.leads}, key=int),
                                 "toolchains": sorted({lead.failure.toolchain for lead in g.leads}),
                                 "representative": {"program_id": rep.program_id, "toolchain": rep.toolchain,
                                                    "mode": rep.mode, "lines": rep.lines}}) + "\n")
    c = Counter(g.status for g in groups)
    print(f"{run_dir}: {sum(len(g.leads) for g in groups)} failures in {len(groups)} groups: "
          f"{c['known']} known, {c['related']} related, {c['mixed']} mixed, {c['unsupported']} declared unsupported, "
          f"{c['new']} new "
          f"-> {path.relative_to(ROOT)}")
    for g in groups:
        if g.status in ("new", "mixed"):
            rep = g.representative.failure
            print(f"  {g.status:5} {g.family:6} {len(g.unexplained):4}/{len(g.leads):<4} unexplained  seed "
                  f"{rep.program_id} on {rep.toolchain}/{rep.mode} ({rep.lines} lines)  {g.signature[:80]}")
    return groups


QUEUE = OUT / "queue.jsonl"


def _meta(run_dir: Path) -> dict:
    p = Path(run_dir) / "meta.json"
    return ((json.loads(p.read_text()).get("sessions") or [{}])[0]) if p.is_file() else {}


def plan(run_dir: Path) -> int:
    groups = LD.fuzz_groups(run_dir)
    meta = _meta(run_dir)
    q = LD.reduce_queue(groups, str(Path(run_dir).relative_to(ROOT) if Path(run_dir).is_absolute() else run_dir),
                        meta.get("opt") or "-O2", int(meta.get("xnack") or 0))
    have = {json.loads(x)["name"] for x in QUEUE.read_text().splitlines() if x.strip()} if QUEUE.is_file() else set()
    OUT.mkdir(parents=True, exist_ok=True)
    new = [e for e in q if e["name"] not in have]
    with QUEUE.open("a") as fh:
        for e in new:
            fh.write(json.dumps(e) + "\n")
    print(f"{run_dir}: {len(new)} reductions queued ({len(q) - len(new)} already) -> {QUEUE.relative_to(ROOT)}")
    return 0


def _done(e: dict) -> bool:
    d = ROOT / e["argv"][-1]
    return (d / "report.md").is_file() or (d / "covered.json").is_file()


def _result(e: dict):
    """(reduced program path, its failing row on the target) of a finished reduction, or None."""
    d = ROOT / e["argv"][-1]
    prog = next((p for p in sorted(d.glob(e["name"] + ".*")) if p.suffix in (".f90", ".c", ".F90")), None)
    rows = d / "rows.jsonl"
    if prog is None or not rows.is_file() or not (d / "report.md").is_file():
        return None
    tc = e["target"].split("/")[0]
    row = next((json.loads(x) for x in rows.read_text().splitlines()
                if x.strip() and json.loads(x).get("toolchain") == tc), {})
    return prog, row


def reduce(minutes: float) -> int:
    """The unfinished reductions of the queue, in order, until `minutes` pass (a compute node)."""
    end = time.time() + minutes * 60
    todo = [json.loads(x) for x in QUEUE.read_text().splitlines() if x.strip()] if QUEUE.is_file() else []
    todo = sorted((e for e in todo if not _done(e)), key=lambda e: tuple(e.get("priority") or (9, 0)))
    print(f"{len(todo)} reductions left")
    every = [json.loads(x) for x in QUEUE.read_text().splitlines() if x.strip()] if QUEUE.is_file() else []
    for e in todo:
        left = (end - time.time()) / 60
        if left < 3:
            break
        # a lead a finished reduction already explains is not reduced again
        provs = [LD.provisional(d, r[0].read_text(), r[1]) for d in every if "text" in d and (r := _result(d))]
        by = LD.covered(e, provs) if "text" in e else None
        if by:
            out = ROOT / e["argv"][-1]
            out.mkdir(parents=True, exist_ok=True)
            (out / "covered.json").write_text(json.dumps({"by": by}) + "\n")
            print(f"covered {e['name']} by {by}", flush=True)
            continue
        argv = list(e["argv"])
        i = argv.index("--budget-minutes")
        argv[i + 1] = str(int(min(float(argv[i + 1]), left - 1)))
        print(f"reduce {e['name']} ({argv[i + 1]} min)", flush=True)
        subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "reduce.py"), *argv], cwd=ROOT)
    print(f"{sum(1 for e in todo if not _done(e))} reductions left")
    return 0


def recheck() -> int:
    """Each finished reduction's program asked of the catalog with its failure (the reduction keeps
    the failure's signature on its target): known, related or new."""
    from offload.engine.confirm import findings as F
    entries = [json.loads(x) for x in QUEUE.read_text().splitlines() if x.strip()] if QUEUE.is_file() else []
    out = []
    for e in entries:
        got = _result(e)
        if got is None:
            continue
        prog, row = got
        tc = e["target"].split("/")[0]
        lang = "c" if prog.suffix == ".c" else "f90"
        outcome = __import__("offload.engine.gate", fromlist=["outcome_class"]).outcome_class(dict(row, toolchain=tc))
        hits = F.dedupe(tc, lang, outcome, row.get("reason") or "", prog.read_text(), related=True,
                        output=row.get("output") or "")
        kind = "known" if any(h["kind"] == "duplicate" for h in hits) else ("related" if hits else "new")
        out.append({"name": e["name"], "family": e["family"], "group": e["group"], "status": kind, "target": e["target"],
                    "findings": [h["file"] for h in hits], "program": str(prog.relative_to(ROOT)),
                    "lines": sum(1 for x in prog.read_text().splitlines() if x.strip())})
        print(f"  {kind:7} {e['name']:40} {out[-1]['lines']:4} lines  {', '.join(out[-1]['findings'][:2])}")
    (OUT / "rechecked.jsonl").write_text("".join(json.dumps(r) + "\n" for r in out))
    return 0


def advance(minutes: float) -> int:
    """The confirmer (tools/confirm.py case --run --draft) on each reduction recheck found new, once:
    it runs the case and the evidence cells, applies the legality witnesses, decides the verdict and
    writes a draft (results/confirm/drafts/; promoting one is a person's step). Its result is the
    reduction's confirm.json."""
    end = time.time() + minutes * 60
    path = OUT / "rechecked.jsonl"
    rows = [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.is_file() else []
    for r in rows:
        if r["status"] != "new":
            continue
        prog = ROOT / r["program"]
        done = prog.parent / "confirm.json"
        if done.is_file():
            continue
        if (end - time.time()) / 60 < 3:
            break
        tc, xn = r["target"].split("/")
        mode = LD.MODES.get(int(xn), "copy")
        argv = [sys.executable, "-I", str(ROOT / "tools" / "confirm.py"), "case", str(prog), "--toolchain", tc,
                "--mode", mode, "--run", "--draft"]
        print(f"confirm {r['name']}", flush=True)
        p = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=max(60, int(end - time.time())))
        last = next((x for x in reversed(p.stdout.splitlines()) if x.strip().startswith("{")), "")
        try:
            res = json.loads(last)
        except ValueError:
            res = {"verdict": "error", "reason": (p.stderr or p.stdout)[-400:]}
        done.write_text(json.dumps(res) + "\n")
        print(f"  {res.get('verdict')}  {res.get('draft') or res.get('reason', '')[:100]}", flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("runs", nargs="+", type=Path)
    pl = sub.add_parser("plan")
    pl.add_argument("runs", nargs="+", type=Path)
    rd = sub.add_parser("reduce")
    rd.add_argument("--minutes", type=float, default=25)
    sub.add_parser("recheck")
    ad = sub.add_parser("advance")
    ad.add_argument("--minutes", type=float, default=10)
    a = ap.parse_args(argv)
    if a.cmd == "advance":
        return advance(a.minutes)
    if a.cmd == "reduce":
        return reduce(a.minutes)
    if a.cmd == "recheck":
        return recheck()
    for r in a.runs:
        scan(r) if a.cmd == "scan" else plan(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
