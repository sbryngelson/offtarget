#!/usr/bin/env python3
"""The bounded catalog subset of GCC's smoke run: N legal programs of one
language and model, evenly spaced over the sorted program ids of the
requested spec versions (deterministic, so both GPUs run the same set).
Prints one id per line.
    python3 -I tools/campaigns/gcc_subset.py --lang f90 --versions 50 52 60 -n 50
    python3 -I tools/campaigns/gcc_subset.py --lang f90 --versions 34 -n 20  (OpenACC)
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def pick(ids, n: int) -> list:
    """n ids evenly spaced over the sorted `ids` (all of them when fewer)."""
    ids = sorted(ids)
    if len(ids) <= n:
        return ids
    return [ids[i * len(ids) // n] for i in range(n)]


def subset(progs, n: int) -> list:
    """`pick` over the legal programs of (version, Program) pairs."""
    return pick({p.id for _, p in progs if p.legal}, n)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=("f90", "c"), default="f90")
    ap.add_argument("--versions", type=int, nargs="+", required=True)
    ap.add_argument("-n", type=int, required=True)
    a = ap.parse_args()
    from offload.engine.catalog import slice_atoms
    from offload.engine.run_matrix import matrix_programs
    atoms = set().union(*(slice_atoms(v, lang=a.lang) for v in a.versions))
    for i in subset(matrix_programs(atoms, a.versions, a.lang), a.n):
        print(i)
    return 0


if __name__ == "__main__":
    sys.exit(main())
