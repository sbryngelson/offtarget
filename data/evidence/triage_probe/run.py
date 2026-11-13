#!/usr/bin/env python3
"""Probes (compute node): the probe programs of this directory on
the toolchains named below, both memory modes, -O2, 3 runs each
(offload.engine.harness.run_program); one JSONL row per cell to
results/t27b/probes.jsonl. Submit with data/evidence/triage_probe/run.sh."""
import dataclasses
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))
from offload.engine.harness import program_from_file, run_program  # noqa: E402
from offload.engine.toolchains import TOOLCHAINS  # noqa: E402

HERE = Path(__file__).resolve().parent
ALL = ("afar", "cce19", "cce20", "cce21")
PLAN = [  # (file, toolchains, xnack modes, extra flags (C version))
    ("pfor_dyn_dn.c", ALL, (1, 0), ("-fopenmp-version=52",)),
    ("pfor_dyn.c", ALL, (1, 0), ("-fopenmp-version=52",)),
    ("pfor_dyn_sh.c", ALL, (1, 0), ("-fopenmp-version=52",)),
    ("pfor_dn.c", ALL, (1, 0), ("-fopenmp-version=52",)),
    ("pfor_plain.c", ALL, (1, 0), ("-fopenmp-version=52",)),
    ("dt_to.c", ALL, (1,), ("-fopenmp-version=52", "")),
    ("map_iter.c", ALL, (1, 0),
     ("", "-fopenmp-version=51", "-fopenmp-version=52")),
    ("dmap_none.f90", ALL, (1, 0), ("",)),
    ("dmap_none_noi.f90", ALL, (1, 0), ("",)),
    ("linear_mod.f90", ALL, (1, 0), ("",)),
    ("linear_mod_nodn.f90", ALL, (1, 0), ("",)),
]


def main() -> int:
    import os
    out = ROOT / "results" / "t27b" / os.environ.get("PROBES_OUT",
                                                     "probes.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[1:])
    with out.open("a") as f:
        for name, tcs, modes, extras in PLAN:
            if only and name not in only:
                continue
            prog = program_from_file(HERE / name)
            for extra in extras:
                for tcn in tcs:
                    tc = dataclasses.replace(TOOLCHAINS[tcn], extra=extra)
                    for x in modes:
                        r = run_program(prog, tc, x, repeats=3)
                        d = dataclasses.asdict(r)
                        d.update(probe=name, extra=extra)
                        f.write(json.dumps(d, default=str) + "\n")
                        f.flush()
                        print(name, extra or "-", tcn, x, d["outcome"],
                              d["reason"][:120], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
