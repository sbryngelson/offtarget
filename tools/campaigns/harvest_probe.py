#!/usr/bin/env python3
"""Run reproducers and their variants (findings, controls) through
the harness on this node's toolchains, every mode, and print what each run
printed. A compute node only (tools/run_harvest_probe.sh).

    python3 -I tools/campaigns/harvest_probe.py --out results/harvest/probe/NAME.jsonl \
        --toolchains afar,cce19,cce20,cce21 --modes 0,1 --version 52 FILE...
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


def prerun_files(files, version: int) -> int:
    """offload.engine.prerun.check of each file. Where /p/lustre5 is not
    mounted (Tioga) the AFAR front end is the copy of the same release on
    /p/vast1 (offload.engine.toolchains.AFAR_VAST)."""
    import os
    from offload.engine import harness, prerun
    from offload.engine import toolchains as T
    if not os.path.exists(f"{T.AFAR_BIN}/amdclang"):
        T.AFAR_BIN = T.AFAR_BIN_G90
    bad = 0
    for f in files:
        p = harness.program_from_file(f)
        p = type("P", (), {"source": p.source, "lang": "c" if f.endswith(
            ".c") else "f90", "model": "omp", "version": version})()
        ok, why = prerun.check(p)
        bad += not ok
        print(f"{Path(f).name}: {'ok' if ok else 'REFUSED'} {'; '.join(why)}")
    return 1 if bad else 0


# --- the reproduction gate of a finding's file --------

def gate_row(path: str, toolchain: str, xnack: int) -> dict:
    """The gate's row of a finding file on one toolchain and mode (kind
    harvest: build directories harvest_<8 hex>, per-program signature)."""
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    import harvest as HV
    HV._register()
    return {"kind": "harvest", "campaign": "harvest", "toolchain": toolchain,
            "xnack": xnack, "ident": Path(path).stem,
            "cell": f"finding|{path}|{toolchain}|{xnack}"}


def gate_envs(row: dict, root: str | None = None) -> list[dict]:
    from offload.engine import gate as GT
    return GT.environments(row, root)


def judge_finding(stored: dict, reruns: list[dict], path: str,
                  toolchain: str, xnack: int) -> dict:
    """offload.engine.gate.judge of a finding file's stored run (a harness
    row) and its reruns, keyed like the harvest's rows (the HV-FAIL line,
    else the RESULT line's check)."""
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    import harvest as HV
    from offload.engine import gate as GT
    row = {**gate_row(path, toolchain, xnack), **stored}
    row["value"] = HV.hv_value(stored.get("stdout"))
    rr = [{**r, "value": HV.hv_value(r.get("stdout"))} for r in reruns]
    return GT.judge(row, rr)


def gate_run(a) -> int:
    """Run the environments `a.gate_envs` of each file here (the stored run
    first with --stored: three repeats in a fresh directory), appending to
    --out."""
    from offload.engine import gate_run as GR
    from offload.engine import harness, run_matrix
    from offload.engine.toolchains import TOOLCHAINS
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    envs = a.gate_envs.split(",")
    with open(out, "a") as fh:
        for f in a.files:
            prog = harness.program_from_file(f)
            lang = "c" if f.endswith(".c") else "f90"
            for t in a.toolchains.split(","):
                for x in (int(m) for m in a.modes.split(",")):
                    tc = run_matrix.for_version(TOOLCHAINS[t], a.version,
                                                lang)
                    row = gate_row(f, t, x)
                    if a.stored:
                        r = harness.run_program(prog, tc, x, a.opt,
                                                timeout_s=a.timeout,
                                                repeats=3,
                                                version=a.version)
                        d = dataclasses.asdict(r)
                        d.update(file=f, role="stored")
                        fh.write(json.dumps(d) + "\n")
                        fh.flush()
                    for e in gate_envs(row, a.root):
                        if e["env"] not in envs:
                            continue
                        rr = GR.rerun_program(prog, tc, x, e, a.opt,
                                              timeout_s=a.timeout)
                        rr.update(file=f, toolchain=t, xnack=x,
                                  role="rerun", cell=row["cell"])
                        fh.write(json.dumps(rr) + "\n")
                        fh.flush()
                        print(f"{Path(f).name} {t} x{x} {e['env']} "
                              f"{rr.get('outcome')} {rr.get('node')}",
                              flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--toolchains", required=True)
    ap.add_argument("--modes", default="0")
    ap.add_argument("--version", type=int, default=52)
    ap.add_argument("--opt", default="-O2")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", required=True)
    ap.add_argument("--prerun", action="store_true",
                    help="only the pre-run check (offload.engine.prerun.check) "
                    "of each file")
    ap.add_argument("--gate-envs", help="run these gate environments "
                    "(a,b,c,d) of each file here instead of plain runs")
    ap.add_argument("--stored", action="store_true",
                    help="with --gate-envs: first the stored run")
    ap.add_argument("--root", help="the gate's build root (node-local)")
    a = ap.parse_args(argv)
    if a.prerun:
        return prerun_files(a.files, a.version)
    if a.gate_envs:
        return gate_run(a)
    from offload.engine import harness, run_matrix
    from offload.engine.toolchains import TOOLCHAINS
    jobs = []
    for f in a.files:
        prog = harness.program_from_file(f)
        lang = "c" if f.endswith(".c") else "f90"
        for t in a.toolchains.split(","):
            for x in (int(m) for m in a.modes.split(",")):
                if x in TOOLCHAINS[t].xnack_modes:
                    jobs.append((f, prog, lang, t, x))

    def one(j):
        f, prog, lang, t, x = j
        tc = run_matrix.for_version(TOOLCHAINS[t], a.version, lang)
        r = harness.run_program(prog, tc, x, a.opt, timeout_s=a.timeout,
                                repeats=a.repeats, version=a.version)
        d = dataclasses.asdict(r)
        d["file"] = f
        return d
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=a.workers) as pool, \
            open(out, "a") as fh:
        for d in pool.map(one, jobs):
            fh.write(json.dumps(d) + "\n")
            fh.flush()
            lines = [ln for ln in (d["stdout"] or "").splitlines()
                     if ln.strip()][-4:]
            print(f"{Path(d['file']).name} {d['toolchain']} x{d['xnack']} "
                  f"{d['outcome']}: {d['reason'][:120]} | "
                  + " / ".join(lines), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
