#!/usr/bin/env python3
"""Probe and contention runs for candidate GCC defects: hand-made
reproducers with their one-change controls (tests/data/gcc_probes) and
catalog programs. Each is compiled once with the toolchain's own recipe and
run many times. One JSON line per run goes to results/gcc/<tc>/probes.jsonl.

    # each file RUNS times, with OMP_TARGET_OFFLOAD=mandatory and unset
    python3 -I tools/campaigns/gcc_probe.py files --toolchain gcc_sm80 --runs 5 \
        tests/data/gcc_probes/inred_base.c ...
    # catalog programs, alone (COPIES 1) or COPIES at once on one GPU,
    # ROUNDS times, under mandatory
    python3 -I tools/campaigns/gcc_probe.py contend --toolchain gcc_g90 --copies 8 \
        --rounds 4 --timeout 60 omp52-clause-depend-out ...

The caller selects the GPU (CUDA_VISIBLE_DEVICES / ROCR_VISIBLE_DEVICES)
and, on wingtip, the cap. On Tioga it runs inside one interactive job."""
from __future__ import annotations

import argparse
import dataclasses
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

_RESULT = re.compile(r"^RESULT ran_on_host=([01]) check=(pass|fail)\s*$", re.M)
_BAD = re.compile(r"\bbad=\s*(\d+)")


def run_class(rc, stdout: str, stderr: str) -> str:
    """One run's class: pass / host / wrong (the program's own check),
    timeout (rc None), device_not_found / host_only (libgomp refusing
    under mandatory), crash (a signal), exit (another failure)."""
    if rc is None:
        return "timeout"
    if "MANDATORY, but device not found" in stderr:
        return "device_not_found"
    if "MANDATORY, but only the host device is available" in stderr:
        return "host_only"
    if rc < 0:
        return "crash"
    m = _RESULT.search(stdout)
    if rc == 0 and m:
        if m.group(2) == "fail":
            return "wrong"
        return "host" if m.group(1) == "1" else "pass"
    b = _BAD.search(stdout)
    if rc == 0 and b:
        return "pass" if b.group(1) == "0" else "wrong"
    return "exit"


def summary(rows: list[dict]) -> dict:
    """'<program> <offload>' -> counts of each run class."""
    out: dict = {}
    for r in rows:
        out.setdefault(f"{r['program']} {r['offload']}", Counter())[
            r["class"]] += 1
    return {k: dict(v) for k, v in out.items()}


_DIRECTIVE = re.compile(r"^\s*(?:!\$(omp|acc)|#\s*pragma\s+(omp|acc))\b", re.M | re.I)


def model_of(path) -> str:
    """acc for a file of OpenACC directives only (built with -fopenacc), else omp."""
    kinds = {(m.group(1) or m.group(2)).lower()
             for m in _DIRECTIVE.finditer(Path(path).read_text())}
    return "acc" if kinds == {"acc"} else "omp"


def _tc(name: str, lang: str, model: str = "omp"):
    from offload.engine.toolchains import TOOLCHAINS
    t = TOOLCHAINS[name]
    return dataclasses.replace(t.for_mode(t.xnack_modes[0]), lang=lang,
                               model=model)


def _build(tc, src: Path, d: Path) -> tuple[Path | None, str]:
    from offload.engine import harness as H
    exe = d / "p.out"
    ex = H._execute(H.compile_script(tc, str(src), str(exe), "-O2", str(d)),
                    d, 600, merge=True)
    return (exe if ex.rc == 0 and exe.is_file() else None), ex.stdout[-2000:]


def _run(tc, exe: Path, d: Path, offload: str, timeout: int):
    from offload.engine import harness as H
    script = H.run_script(tc, str(exe), tc.xnack_modes[0], offload ==
                          "mandatory", str(d))
    ex = H._execute(script, d, timeout)
    return ex.rc, ex.stdout, ex.stderr


def cmd_files(a) -> int:
    out = ROOT / "results" / "gcc" / a.toolchain / "probes.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with out.open("a") as fh:
        for f in a.files:
            src = Path(f)
            lang = "c" if src.suffix == ".c" else "f90"
            tc = _tc(a.toolchain, lang, model_of(src))
            d = Path(tempfile.mkdtemp(prefix="gccprobe_"))
            try:
                exe, log = _build(tc, src.resolve(), d)
                if exe is None:
                    r = {"program": src.name, "offload": "-", "class":
                         "compile_fail", "log": log}
                    fh.write(json.dumps(r) + "\n")
                    rows.append(r)
                    continue
                for off in ("mandatory", "unset"):
                    for k in range(a.runs):
                        rc, so, se = _run(tc, exe, d, off, a.timeout)
                        r = {"program": src.name, "toolchain": a.toolchain,
                             "offload": off, "run": k, "rc": rc,
                             "class": run_class(rc, so, se),
                             "stdout": so[-300:], "stderr": se[-300:],
                             "date": time.strftime("%Y-%m-%dT%H:%M:%S")}
                        fh.write(json.dumps(r) + "\n")
                        fh.flush()
                        rows.append(r)
            finally:
                shutil.rmtree(d, ignore_errors=True)
    print(json.dumps(summary(rows), indent=1))
    return 0


def cmd_contend(a) -> int:
    """Each catalog program built once, then ROUNDS rounds of COPIES
    concurrent runs (mandatory) on the caller's GPU."""
    from concurrent.futures import ThreadPoolExecutor
    from offload.engine.confirm.programs import catalog_program
    out = ROOT / "results" / "gcc" / a.toolchain / "contend.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with out.open("a") as fh:
        for pid in a.programs:
            prog = catalog_program(pid)
            lang = "c" if prog.lang == "c" else "f90"
            tc = _tc(a.toolchain, lang, prog.model)
            d = Path(tempfile.mkdtemp(prefix="gcccontend_"))
            try:
                src = d / f"p.{'c' if lang == 'c' else 'f90'}"
                src.write_text(prog.source)
                exe, log = _build(tc, src, d)
                if exe is None:
                    print(pid, "compile failed", log[-300:])
                    continue
                for rnd in range(a.rounds):
                    dirs = []
                    for k in range(a.copies):
                        dk = d / f"r{rnd}c{k}"
                        dk.mkdir()
                        dirs.append(dk)
                    with ThreadPoolExecutor(a.copies) as ex:
                        res = list(ex.map(lambda dk: _run(
                            tc, exe, dk, "mandatory", a.timeout), dirs))
                    for k, (rc, so, se) in enumerate(res):
                        r = {"program": pid, "toolchain": a.toolchain,
                             "offload": f"mandatory x{a.copies}",
                             "round": rnd, "copy": k, "rc": rc,
                             "class": run_class(rc, so, se),
                             "stderr": se[-200:],
                             "date": time.strftime("%Y-%m-%dT%H:%M:%S")}
                        fh.write(json.dumps(r) + "\n")
                        rows.append(r)
                    fh.flush()
            finally:
                shutil.rmtree(d, ignore_errors=True)
    print(json.dumps(summary(rows), indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("files")
    f.add_argument("--toolchain", required=True)
    f.add_argument("--runs", type=int, default=5)
    f.add_argument("--timeout", type=int, default=60)
    f.add_argument("files", nargs="+")
    c = sub.add_parser("contend")
    c.add_argument("--toolchain", required=True)
    c.add_argument("--copies", type=int, default=8)
    c.add_argument("--rounds", type=int, default=4)
    c.add_argument("--timeout", type=int, default=60)
    c.add_argument("programs", nargs="+")
    a = ap.parse_args(argv)
    return {"files": cmd_files, "contend": cmd_contend}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
