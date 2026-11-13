#!/usr/bin/env python3
"""nested-data: run hand-written reductions and controls through the harness.

    python3 -I tools/campaigns/nested_try.py OUT.jsonl FILE... --toolchains gcc_g90 \
        [--modes 0,1] [--model omp|acc] [--repeats 3] [--workers N] \
        [--gate a,b,d | c]

The language comes from the extension (.c, .f90), the model from the file's
directives (``acc`` in one) unless --model is given. Each result row
(program, toolchain, mode, outcome, reason, stdout, stderr) is appended to
OUT; the harness's own classification is used (offload.engine.harness).
--gate runs each file in the gate's environments instead (offload.engine.gate:
``a,b,d`` in one job, ``c`` in a job on another node), one row per
environment with its node. Run it on a compute node of the machine that
has the toolchain."""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


def _program(path: str, model: str | None = None):
    from offload.engine.gen import Program
    src = Path(path).read_text()
    lang = "c" if path.endswith(".c") else "f90"
    model = model or ("acc" if re.search(r"(#pragma|!\$)\s*acc\b", src, re.I)
                      else "omp")
    pid = Path(path).stem
    return Program(id=pid, lang=lang, source=src,
                   atoms=frozenset({"nested.reduce"}),
                   primary_atom="nested.reduce", legal=True, violates=None,
                   observable=True, model=model)


def gate_item(pid: str, toolchain: str, xnack: int) -> dict:
    """A gate row for a hand-written file (offload.engine.gate kind nested)."""
    return {"kind": "nested", "ident": pid, "toolchain": toolchain,
            "xnack": xnack, "node": None, "build_dir": "-",
            "cell": f"nested|{pid}|{toolchain}|{xnack}"}


def gate_envs(item: dict, envs: str, root: str | None = None) -> list[dict]:
    """The gate's environments of `item` named in `envs` ("a,b,d" or "c")."""
    from offload.engine import gate as GT
    want = envs.split(",")
    return [e for e in GT.environments(item, root) if e["env"] in want]


def gate_rows(path: str, toolchain: str, xnack: int, envs: str,
              timeout_s: int, root: str | None = None) -> list[dict]:
    """Run the file in the gate's environments (offload.engine.gate_run); one
    row per environment."""
    from offload.engine import gate_run as GR
    from offload.engine import run_matrix
    from offload.engine.toolchains import TOOLCHAINS
    prog = _program(path)
    version = 34 if prog.model == "acc" else 52
    tc = run_matrix.for_version(TOOLCHAINS[toolchain], version, prog.lang)
    out = []
    for e in gate_envs(gate_item(prog.id, toolchain, xnack), envs, root):
        rr = GR.rerun_program(prog, tc, xnack, e, "-O2", timeout_s=timeout_s,
                              compile_timeout_s=900)
        out.append({**rr, "program_id": prog.id, "toolchain": toolchain,
                    "xnack": xnack, "env": e["env"], "file": path})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--toolchains", required=True)
    ap.add_argument("--modes", default="0")
    ap.add_argument("--model")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--gate")
    ap.add_argument("--workers", type=int, default=1)
    a = ap.parse_args(argv)
    from concurrent.futures import ThreadPoolExecutor
    from offload.engine import harness, run_matrix
    from offload.engine.toolchains import TOOLCHAINS
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    def one(job):
        f, t, x = job
        if a.gate:
            return gate_rows(f, t, x, a.gate, a.timeout)
        prog = _program(f, a.model)
        version = 34 if prog.model == "acc" else 52
        tc = run_matrix.for_version(TOOLCHAINS[t], version, prog.lang)
        r = harness.run_program(prog, tc, x, "-O2", timeout_s=a.timeout,
                                repeats=a.repeats)
        d = dataclasses.asdict(r)
        d["sha"] = hashlib.sha256(prog.source.encode()).hexdigest()
        d["file"] = f
        return [d]

    jobs = [(f, t, int(m)) for f in a.files for t in a.toolchains.split(",")
            for m in a.modes.split(",")
            if int(m) in TOOLCHAINS[t].xnack_modes]
    from concurrent.futures import as_completed
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        # rows are written as they finish: one slow cell holds back no other
        for rows in (f.result() for f in as_completed(
                [pool.submit(one, j) for j in jobs])):
            for d in rows:
                d["stdout"] = (d.get("stdout") or "")[-1500:]
                d["stderr"] = (d.get("stderr") or "")[-2500:]
                with open(out, "a") as fh:
                    fh.write(json.dumps(d, sort_keys=True) + "\n")
                print(f"{d['program_id']} {d['toolchain']} {d['xnack']} "
                      f"{d.get('env', '')}: {d['outcome']} "
                      f"{(d.get('reason') or '')[:90]}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
