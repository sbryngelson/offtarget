#!/usr/bin/env python3
"""Compile a program once per build directory and run it several
times, keeping each run's exit status, output and error output (the gate's
reruns keep only the class). Jobs: a JSON-lines file, one job per line:

    {"id": "...", "toolchain": "cce19", "xnack": 0, "files": [[name, text]],
     "model": "omp", "lang": "f90", "repeats": 10, "offload": "mandatory", "dirs": ["harness_x", "GATEX"],
     "compile_s": 900, "run_s": 120, "env": {"K": "V"}, "opt": "-O2"}

Run on a compute node (node-local build root: $T48_TMP, else /tmp):
    python3 -I data/evidence/gate_probe/probe.py JOBS OUT.jsonl [--workers 8]
Every compile and run goes through offload.engine.harness._execute (process
group, timeout, watchdog)."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def one(job: dict) -> list[dict]:
    from offload.engine import harness
    from offload.engine.stress_exec import tc_for
    lang = job.get("lang") or ("c" if any(n.endswith(".c") for n, _ in
                                          job["files"]) else "f90")
    tc = tc_for(job["toolchain"], job.get("model", "omp"), lang).for_mode(
        int(job.get("xnack", 0)))
    root = os.environ.get("T48_TMP") or "/tmp"
    out = []
    for d in job.get("dirs") or ["t48_" + job["id"].replace("/", "_")]:
        bd = Path(root) / d
        shutil.rmtree(bd, ignore_errors=True)
        bd.mkdir(parents=True)
        names = []
        for name, text in job["files"]:
            (bd / name).write_text(text)
            names.append(name)
        exe = bd / "prog.out"
        opt = job.get("opt", "-O2")
        script = harness.compile_set_script(tc, names, str(exe), opt,
                                            str(bd)) if len(names) > 1 \
            else harness.compile_script(tc, names[0], str(exe), opt, str(bd))
        if job.get("cflags"):
            script = script.replace(f" {opt} ", f" {opt} {job['cflags']} ")
        t0 = time.time()
        b = harness._execute(script, bd, job.get("compile_s", 900),
                             merge=True)
        base = {"id": job["id"], "toolchain": job["toolchain"],
                "xnack": job.get("xnack", 0), "dir": str(bd),
                "node": socket.gethostname(), "date":
                time.strftime("%Y-%m-%dT%H:%M:%S")}
        rec = {**base, "step": "compile", "rc": b.rc,
               "timed_out": b.timed_out, "seconds": round(time.time() - t0,
                                                          1),
               "out": (b.stdout or "")[-3000:]}
        out.append(rec)
        if b.rc != 0 or not exe.is_file():
            shutil.rmtree(bd, ignore_errors=True)
            continue
        for k in range(job.get("repeats", 1)):
            rs = harness.run_script(tc, str(exe), int(job.get("xnack", 0)),
                                    True, str(bd),
                                    offload=job.get("offload"))
            for key, val in (job.get("env") or {}).items():
                rs = rs.replace("exec ", f"export {key}={val}\nexec ", 1)
            t0 = time.time()
            r = harness._execute(rs, bd, job.get("run_s", 120))
            out.append({**base, "step": "run", "k": k, "rc": r.rc,
                        "timed_out": r.timed_out,
                        "seconds": round(time.time() - t0, 1),
                        "stdout": (r.stdout or "")[-int(job.get("keep", 4000)):],
                        "stderr": (r.stderr or "")[-2000:]})
        shutil.rmtree(bd, ignore_errors=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("jobs")
    ap.add_argument("out")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    jobs = [json.loads(x) for x in Path(a.jobs).read_text().splitlines()
            if x.strip()]
    with ProcessPoolExecutor(a.workers) as ex, open(a.out, "a") as fh:
        for fut in as_completed([ex.submit(one, j) for j in jobs]):
            for r in fut.result():
                fh.write(json.dumps(r) + "\n")
            fh.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
