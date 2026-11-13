#!/usr/bin/env python3
"""Reduce a fuzz program whose compile does not finish on one
toolchain (CCE 19 on s1 seed 9914: the campaign's 600 s compile timeout,
while CCE 20/21 compile it in 5 s). A candidate keeps the failure when it
passes the fuzz legality checks (offload.engine.fuzz.check_rules and
check_gfortran) and its compile on the toolchain is still running after
LIMIT seconds; candidates are judged in parallel (offload.engine.fuzz_min's
reductions). On a compute node:
    python3 -I data/evidence/dataenv_probe/min_hang.py SEED TOOLCHAIN OUT [LIMIT]"""
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine import fuzz, fuzz_exec, fuzz_min  # noqa: E402
from offload.engine.toolchains import TOOLCHAINS  # noqa: E402

BASE = ("types", "derived", "alloc", "declare", "multitu")


def main() -> int:
    seed, tc, out = int(sys.argv[1]), TOOLCHAINS[sys.argv[2]], sys.argv[3]
    limit = int(sys.argv[4]) if len(sys.argv) > 4 else 90
    src = fuzz.generate(seed, "fuzz-3", BASE).source

    def oracle(text: str):
        why = fuzz.check_rules(text) or fuzz.check_gfortran(text)
        if why:
            return False, f"illegal: {why[:80]}"
        with tempfile.TemporaryDirectory(prefix="hang_") as d:
            d = Path(d)
            (d / "p.f90").write_text(text)
            t0 = time.time()
            cls, reason, _, _ = fuzz_exec.compile_program(
                tc, d / "p.f90", d / "p.out", d, timeout_s=limit)
            good = cls == "timeout"
            if good:
                # every kept candidate is a reproducer: the latest one is
                # saved (the job may end at its time limit)
                Path(out).write_text(text)
            return good, f"{cls or 'compiled'} {time.time() - t0:.0f} s"
    res = fuzz_min.minimize(src, oracle, workers=12,
                            log=lambda m: print(m, flush=True))
    Path(out).write_text(res.source)
    print(f"{res.lines_before} -> {res.lines_after} lines; {res.verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
