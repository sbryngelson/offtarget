#!/usr/bin/env python3
"""The application corpus (data/bench/apps/, offload.engine.apps).

    python3 -I tools/campaigns/app_bench.py fetch                 # clone at the pinned commits
    python3 -I tools/campaigns/app_bench.py list
    python3 -I tools/campaigns/app_bench.py run --toolchains afar cce19 [--modes unified copy]
                                      [--programs ID ...] [--jobs N] [--tag T]
    python3 -I tools/campaigns/app_bench.py summary               # data/bench/apps/ground_truth.jsonl

``run`` builds each program file by file, links it and runs it in every
requested mode. It builds once per toolchain where memory modes are run-time
settings, and once per mode where they are compile flags (NVHPC). One record
per program, toolchain and mode is appended to
results/apps/runs/<toolchain>.<mode>.jsonl; a program already recorded there
is skipped (delete its line to redo it). ``summary`` writes the committed
ground truth: every record without logs, plus the run metadata."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine import apps as A  # noqa: E402


def fetch() -> int:
    bad = 0
    for app in A.load().values():
        dst = app.path
        if dst.exists():
            head = subprocess.run(["git", "-C", str(dst), "rev-parse",
                                   "HEAD"], capture_output=True,
                                  text=True).stdout.strip()
            if head == app.commit:
                print(f"{app.id}: at {app.commit[:12]}")
                continue
            print(f"{app.id}: at {head[:12]}, want {app.commit[:12]}: "
                  "fetching")
            r = subprocess.run(["git", "-C", str(dst), "fetch", "--depth",
                                "1", "origin", app.commit])
            r = subprocess.run(["git", "-C", str(dst), "checkout", "-q",
                                app.commit])
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            r = subprocess.run(["git", "init", "-q", str(dst)])
            subprocess.run(["git", "-C", str(dst), "remote", "add",
                            "origin", app.repo])
            subprocess.run(["git", "-C", str(dst), "fetch", "-q", "--depth",
                            "1", "origin", app.commit])
            r = subprocess.run(["git", "-C", str(dst), "checkout", "-q",
                                "FETCH_HEAD"])
        if r.returncode:
            bad += 1
            print(f"{app.id}: checkout failed")
    return 1 if bad else 0


_lock = threading.Lock()


def _append(path: Path, rec: dict) -> None:
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            fh.write(json.dumps(rec) + "\n")


def run(toolchains, modes, only, jobs, tag="") -> None:
    from offload.engine.confirm import machines as M
    from offload.engine.toolchains import TOOLCHAINS
    apps = A.load()
    progs = A.programs(apps)
    work = []
    for tcn in toolchains:
        machine = M.load()[TOOLCHAINS[tcn].machine]
        ms = [m for m in (modes or machine.modes) if m in machine.modes]
        for pid, prog in progs.items():
            if only and pid not in only:
                continue
            if prog.sources == ["@mfc"]:     # tools/jobs/run_mfc.sh
                continue
            why = A.applicable(prog, tcn)
            todo = []
            for m in ms:
                out = A.OUT / "runs" / f"{tcn}.{m}{tag}.jsonl"
                done = {r["program"] for r in A.read_records(out)}
                if pid not in done:
                    todo.append(m)
            if not todo:
                continue
            if why:
                for m in todo:
                    _append(A.OUT / "runs" / f"{tcn}.{m}{tag}.jsonl",
                            {"program": pid, "app": prog.app,
                             "toolchain": tcn, "mode": m,
                             "outcome": "not_applicable", "reason": why})
                continue
            if machine.compile_time_modes:
                for m in todo:
                    work.append((pid, tcn, [m], machine.row_key(m)))
            else:
                work.append((pid, tcn, todo, None))
    print(f"{len(work)} builds", flush=True)
    gpus = 4

    def one(item, k):
        pid, tcn, ms, row_key = item
        prog = progs[pid]
        app = apps[prog.app]
        tagdir = f"{tcn}" + (f".{ms[0]}" if row_key is not None else "")
        bdir = A.OUT / "build" / tagdir / pid
        built = A.build(prog, app, tcn, bdir, row_key)
        for m in ms:
            runs = None
            if built["exe"]:
                runs = A.run_program(prog, app, tcn, built["exe"], m,
                                     bdir / f"run.{m}", gpu=k % gpus)
            rec = A.record(prog, tcn, m, built, runs)
            _append(A.OUT / "runs" / f"{tcn}.{m}{tag}.jsonl", rec)
            print(f"{pid} {tcn} {m}: {rec['stage']} {rec['outcome']} "
                  + "; ".join(f"{f['file']}={f['outcome']}"
                              for f in rec["files"]
                              if f["outcome"] != "ok")[:300], flush=True)

    with ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = [ex.submit(one, w, k) for k, w in enumerate(work)]
        for f in futs:
            f.result()


def summary(out: Path) -> int:
    recs = []
    for d in (A.OUT / "runs", A.OUT / "wingtip" / "runs"):
        for p in sorted(d.glob("*.jsonl")) if d.exists() else ():
            if p.stem.count(".") > 1:  # tagged trial files are not merged
                continue
            recs += A.read_records(p)
    recs += A.mfc_records()
    # the manifest's current needs and legality decisions
    progs = A.programs()
    for r in recs:
        p = progs.get(r["program"])
        if p is not None:
            r["needs"] = list(p.needs)
            r["legality"] = p.legality.get("status", "legal")
    for r in recs:
        for f in r.get("files") or ():
            f.pop("seconds", None)
        for x in r.get("runs") or ():
            x.pop("seconds", None)
        r.pop("date", None)
    recs.sort(key=lambda r: (r["app"], r["program"], r["toolchain"],
                             r["mode"]))
    out.write_text("".join(json.dumps(r, sort_keys=True) + "\n"
                           for r in recs))
    print(f"{len(recs)} records -> {out}")
    return 0


SHORT = {"correct_on_device": "ok", "wrong_answer": "wrong", "run_error":
         "run", "crash": "crash", "timeout": "hang", "rejected": "rej",
         "ice": "ICE", "not_applicable": "", "harness_error": "env"}


def table(gt: Path) -> str:
    """The ground truth as a markdown table: one row per program, one
    column per toolchain and mode (ok, wrong, run, crash, hang, rej, ICE;
    MFC: the failing share of its tests); legality and needs marked."""
    recs = A.read_records(gt)
    cols = ["afar.unified", "afar.copy", "cce19.unified", "cce19.copy",
            "cce20.unified", "cce20.copy", "cce21.unified", "cce21.copy",
            "nvhpc.copy", "nvhpc.managed", "nvhpc269.copy",
            "nvhpc269.managed"]
    by = {}
    for r in recs:
        by.setdefault(r["program"], {})[f"{r['toolchain']}.{r['mode']}"] = r
    progs = A.programs()
    lines = ["| program | " + " | ".join(c.replace(".", " ") for c in cols)
             + " |", "|---" * (len(cols) + 1) + "|"]
    for pid in progs:
        if pid not in by:
            continue
        p = progs[pid]
        tag = ""
        if p.legality.get("status", "legal") != "legal":
            tag = f" ({p.legality['status']})"
        elif p.needs:
            tag = " (unified only)"
        cells = []
        for c in cols:
            r = by[pid].get(c)
            if r is None:
                cells.append("-" if not c.startswith(("afar",)) or
                             p.model != "acc" else "")
                continue
            o = SHORT.get(r.get("outcome"), r.get("outcome", "?"))
            runs = r.get("runs") or []
            if pid.startswith("mfc") and runs and r["stage"] == "run":
                bad = sum(x["outcome"] != "correct_on_device" for x in runs)
                o = f"{bad}/{len(runs)}" if bad else "ok"
            cells.append(o)
        lines.append(f"| {pid}{tag} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("fetch")
    sp.add_parser("list")
    r = sp.add_parser("run")
    r.add_argument("--toolchains", nargs="+", required=True)
    r.add_argument("--modes", nargs="+")
    r.add_argument("--programs", nargs="+")
    r.add_argument("--jobs", type=int, default=8)
    r.add_argument("--tag", default="", help="suffix of the result files "
                   "(a trial run that summary does not merge)")
    t = sp.add_parser("table")
    t.add_argument("--gt", default=str(A.BENCH / "ground_truth.jsonl"))
    s = sp.add_parser("summary")
    s.add_argument("--out", default=str(A.BENCH / "ground_truth.jsonl"))
    a = ap.parse_args(argv)
    if a.cmd == "fetch":
        return fetch()
    if a.cmd == "list":
        for app in A.load().values():
            print(f"{app.id} {app.commit[:12]} {app.license}")
            for p in app.programs:
                print(f"  {p.id} {p.lang} {p.model} {len(p.sources)} files "
                      f"{len(p.runs)} runs")
        return 0
    if a.cmd == "run":
        run(a.toolchains, a.modes, a.programs, a.jobs,
            f".{a.tag}" if a.tag else "")
        return 0
    if a.cmd == "table":
        print(table(Path(a.gt)), end="")
        return 0
    if a.cmd == "summary":
        return summary(Path(a.out))
    return 2


if __name__ == "__main__":
    sys.exit(main())
