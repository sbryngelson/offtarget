"""Predict CCE ftn's split-CIF-record defect for a build directory.

CCE copies the CIF record file with fgets into a 1024-byte buffer and stops at
the first chunk whose leading integer is -1. A record over 1023 characters
is split at offsets 1023, 2046, ...; if a continuation chunk starts with "-1"
not followed by a digit, the CIF is truncated mid-record and the driver
prints fewer messages or aborts in Cif_Cifconv ("free(): invalid pointer").

The long records name the absolute source path once per inlined call site,
so the trigger depends on the path. Given the record file (stress_1.cif.Ttmp)
for directory BASE, directory p has the same lines with BASE replaced by p.

  ftn_cif_split.py hits <ttmp> <base> <dir>...
  ftn_cif_split.py design <ttmp> <base> <root> <lo:hi>   # pairs: '-1' dir, '-2' control
  ftn_cif_split.py eval <ttmp> <base> <sweep.log>...     # run_ftn_cif_split.sh sweep rows"""
from __future__ import annotations

import sys
from pathlib import Path

BUF = 1024          # fgets(buf, 1024, f): at most 1023 characters per chunk


def load(ttmp) -> list[str]:
    return Path(ttmp).read_text(errors="replace").split("\n")


def hits(lines, base: str, p: str, buf: int = BUF) -> list[tuple[int, int]]:
    """(record number, offset) of every continuation chunk, with base
    replaced by p, that starts with -1 not followed by a digit."""
    out = []
    for n, line in enumerate(lines, 1):
        line = line.replace(base, p)
        k = buf - 1
        while k < len(line):
            if line[k:k + 2] == "-1" and not line[k + 2:k + 3].isdigit():
                out.append((n, k))
            k += buf - 1
    return out


def design(lines, base: str, root: str, length: int, rec: int):
    """A directory root/a...a-1a...a of the given length whose only hit is
    record rec (None when there is none)."""
    for j in range(len(root) + 1, length - 2):
        p = root + "/" + "a" * (j - len(root) - 1) + "-1" + "a" * (length - j - 2)
        if len(p) != length:
            continue
        h = hits(lines, base, p)
        if h and all(r == rec for r, _ in h):
            return p
    return None


def eval_rows(lines, base: str, logs) -> list[dict]:
    """Rows '<rc> <heap 0|1> <message> <dir> ...' with the prediction."""
    rows = []
    for log in logs:
        for raw in Path(log).read_text().splitlines():
            r = raw.split()
            if len(r) < 4 or not r[0].isdigit():
                continue
            h = hits(lines, base, r[3])
            rows.append({"dir": r[3], "rc": int(r[0]), "aborted": r[1] == "1",
                         "predicted": bool(h), "hits": h, "rest": r[4:]})
    return rows


def main(argv) -> int:
    cmd, lines, base = argv[0], load(argv[1]), argv[2]
    if cmd == "hits":
        for p in argv[3:]:
            print(p, hits(lines, base, p))
    elif cmd == "design":
        root = argv[3]
        lo, hi = map(int, argv[4].split(":"))
        for length in range(lo, hi + 1):
            for rec in range(1, len(lines) + 1):
                p = design(lines, base, root, length, rec)
                if p:
                    print(p)
                    print(p.replace("-1", "-2"))
    elif cmd == "eval":
        for r in eval_rows(lines, base, argv[3:]):
            print(int(r["predicted"]), int(r["aborted"]), r["rc"],
                  " ".join(r["rest"]), r["dir"], r["hits"])
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
