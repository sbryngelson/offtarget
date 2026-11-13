#!/usr/bin/env python3
"""(F8): compile and run the hand reproducers of
data/reports/fuzz-stress-audit/ (each with its control) on toolchains and memory
modes, with the stress executor's limits (ulimit -v, in-job timeouts,
process-group kills), and print one JSON line per (file, toolchain, mode,
flags): the build outcome and the program's output.

    python3 -I tools/campaigns/stress_audit.py data/reports/fuzz-stress-audit/r1-*.f90 \
        --toolchains afar,cce19 [--modes 1,0] [--flags "-O2 -flto"] \
        [--run-s 120] [--out results/stress/audit/runs.jsonl]

The inputs are committed (data/reports/fuzz-stress-audit/); the output file
is created with its directory (results/ is not in the repository).

Run on a compute node (flux)."""
import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine import harness                      # noqa: E402
from offload.engine import stress_exec as X             # noqa: E402


def model_of(text: str) -> str:
    return "acc" if "!$acc" in text or "#pragma acc" in text else "omp"


def one(path: Path, tc_name: str, mode: int, flags: str | None,
        run_s: int = 120) -> dict:
    text = path.read_text()
    lang = "c" if path.suffix == ".c" else "f90"
    tc = X.tc_for(tc_name, model_of(text), lang)
    rec = {"file": path.name, "toolchain": tc_name, "mode": mode,
           "flags": flags or "-O2", "host": os.uname().nodename}
    try:
        tc = tc.for_mode(mode)
    except ValueError as e:
        rec.update(build="skipped", why=str(e))
        return rec
    tmp = Path(tempfile.mkdtemp(prefix="st_audit_", dir=X.node_local_tmp()))
    rec["build_dir"] = str(tmp)
    try:
        shutil.copy(path, tmp / path.name)
        sc = X.build_script(tc, [path.name], "prog.out", flags or "-O2",
                            str(tmp), 32 * X.GIB, limit_s=900)
        ex = harness._execute(sc, tmp, 920, merge=True)
        steps = X.parse_steps(ex.stdout)
        cls, why = X.classify_compile(tc, ex.rc, ex.stdout, steps)
        rec["build"] = cls or "ok"
        if cls:
            rec["why"] = why[:300]
            return rec
        run = X.in_job_limit(harness.run_script(
            tc, str(tmp / "prog.out"), mode, True, str(tmp)), run_s)
        rx = harness._execute(run, tmp, run_s + 20)
        rec["run_s"] = run_s
        rec["rc"] = rx.rc
        rec["out"] = rx.stdout.strip()[-400:]
        rec["err"] = (rx.stderr or "").strip()[-400:]
        return rec
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--toolchains", required=True)
    ap.add_argument("--modes", default="1,0")
    ap.add_argument("--flags")
    ap.add_argument("--run-s", type=int, default=120)
    ap.add_argument("--out", default=str(ROOT / "results" / "stress" /
                                         "audit" / "runs.jsonl"))
    a = ap.parse_args(argv)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "a") as fh:
        for f in a.files:
            for tc in a.toolchains.split(","):
                for m in [int(x) for x in a.modes.split(",")]:
                    r = one(Path(f), tc, m, a.flags, a.run_s)
                    line = json.dumps(r)
                    fh.write(line + "\n")
                    fh.flush()
                    print(line[:300], flush=True)


if __name__ == "__main__":
    main()
