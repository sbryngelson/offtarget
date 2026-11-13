#!/usr/bin/env python3
"""Compile-only sweep of the catalog with a GCC toolchain (no run, no GPU):
every program of the requested versions and language is compiled with the
toolchain's flags (harness.compile_script, -O2) and one JSON line per
program records the exit status, the time, the classified messages
(harness.classify_all) and, for a failed compile none of the patterns
knows, the output. It finds the compiler's message forms (ICEs, offload
link failures) for the harness tables and measures compile times for the
run-cost estimate. On wingtip it runs inside the cap (tools/jobs/wingtip_capped.sh
or a capped runner), nice, at most WORKERS compiles.
    python3 -I tools/campaigns/gcc_compile_sweep.py --toolchain gcc_sm80 --lang f90 \
        --versions 50 52 60 --workers 4 --limit-s 2400 --out FILE
"""
import argparse
import dataclasses
import json
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--toolchain", required=True)
    ap.add_argument("--lang", choices=("f90", "c"), default="f90")
    ap.add_argument("--versions", type=int, nargs="+", required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit-s", type=int, default=2400)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    from offload.engine import harness as H
    from offload.engine.catalog import slice_atoms
    from offload.engine.run_matrix import for_version, matrix_programs
    from offload.engine.toolchains import TOOLCHAINS
    base = TOOLCHAINS[a.toolchain]
    atoms = set().union(*(slice_atoms(v, lang=a.lang) for v in a.versions))
    progs = matrix_programs(atoms, a.versions, a.lang)
    done = set()
    if a.out.exists():
        done = {json.loads(ln)["program_id"] for ln in a.out.read_text()
                .splitlines() if ln.strip()}
    end = time.time() + a.limit_s

    def one(vp):
        v, p = vp
        if p.id in done or time.time() > end:
            return None
        tc = dataclasses.replace(base, model=p.model, lang=a.lang)
        tc = for_version(tc.for_mode(tc.xnack_modes[0]), v)
        tc = H.with_libm(tc, p)
        tmp = Path(tempfile.mkdtemp(prefix="gccsweep_"))
        try:
            src = tmp / f"p.{'c' if a.lang == 'c' else 'f90'}"
            src.write_text(p.source)
            t0 = time.time()
            ex = H._execute(H.compile_script(tc, str(src), str(tmp / "p.out"),
                                             "-O2", str(tmp)),
                            tmp, a.timeout, merge=True)
            dt = round(time.time() - t0, 1)
            text = ex.stdout.replace(str(tmp), "<tmpdir>")
            msgs = H.classify_all(tc.name, text, H.CATEGORY_ORDER, a.lang)
            row = {"program_id": p.id, "legal": p.legal, "model": p.model,
                   "rc": ex.rc, "seconds": dt, "messages": msgs}
            if ex.rc != 0 and not [m for m in msgs if m[0] != "ignored"]:
                row["output"] = text[-6000:]
            elif ex.rc == 0 and text.strip():
                row["warnings"] = text[-1500:]
            return row
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    with open(a.out, "a") as fh, ThreadPoolExecutor(a.workers) as ex:
        for row in ex.map(one, progs):
            if row is not None:
                fh.write(json.dumps(row) + "\n")
                fh.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
