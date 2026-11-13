#!/usr/bin/env python3
"""Split the in-the-wild cases (data/bench/wild/) into a dev half and a
held-out half.

    python3 -I tools/wild/wild_split.py [--salt S]     # writes data/bench/wild/split.yaml

Only dev cases (and their miss analysis) may guide what the catalog and the
linter add; the holdout half is scored before and after, never read while
designing. The split reads only a case's id, project and model.

Method: strata are (project, model); within a stratum the cases are ordered
by sha256("<salt>:<id>"); the strata are concatenated in sorted order and
the cases alternate dev, holdout, dev, ... along that list. So each stratum
of two or more cases has both halves and the halves differ by at most one."""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
BENCH = ROOT / "data" / "bench" / "wild"
SALT = "compliant-task35-wild-split-2026-10-24"
METHOD = ("strata (project, model) in sorted order; within a stratum by "
          "sha256('<salt>:<id>'); alternate dev, holdout along the list")


def _key(salt: str, cid: str) -> str:
    return hashlib.sha256(f"{salt}:{cid}".encode()).hexdigest()


def split(cases: list[dict], salt: str = SALT) -> dict[str, str]:
    strata: dict[tuple, list[str]] = {}
    for c in cases:
        strata.setdefault((c.get("project", ""), c.get("model", "")),
                          []).append(c["id"])
    order = []
    for k in sorted(strata):
        order += sorted(strata[k], key=lambda i: _key(salt, i))
    return {cid: ("dev", "holdout")[i % 2] for i, cid in enumerate(order)}


def load_split(path: Path = BENCH / "split.yaml") -> dict[str, str]:
    import yaml
    return yaml.safe_load(path.read_text())["cases"]


def main(argv=None) -> int:
    import yaml
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--salt", default=SALT)
    a = ap.parse_args(argv)
    cases = yaml.safe_load((BENCH / "cases.yaml").read_text())["cases"]
    s = split(cases, a.salt)
    n = {h: sum(v == h for v in s.values()) for h in ("dev", "holdout")}
    doc = {"salt": a.salt, "method": METHOD,
           "note": "Held-out discipline: only dev cases may guide "
                   "catalog or linter additions (tools/wild/wild_split.py)",
           "counts": n, "cases": dict(sorted(s.items()))}
    (BENCH / "split.yaml").write_text(yaml.safe_dump(doc, sort_keys=False,
                                                     width=100))
    print(n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
