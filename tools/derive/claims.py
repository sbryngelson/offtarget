#!/usr/bin/env python3
"""Vendor claims: ingest the vendor documents into the generic
claims format.

    python3 -I tools/derive/claims.py ingest     # write catalog/vendor_claims_generic.yaml
    python3 -I tools/derive/claims.py check      # the committed file is up to date

The mapping (catalog/omp/claims.yaml, catalog/acc/claims.yaml) names, for
each statement of a vendor document, the catalog atoms it is about; the
documents and their per-toolchain snapshots are listed in
catalog/vendor_claims.yaml. A claim is recorded for a toolchain only when
that toolchain's edition of the document contains the quote
(offload.engine.confirm.claims.ingest)."""
import argparse
import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine.confirm import claims as CL  # noqa: E402


def summary(rep) -> str:
    by = collections.Counter((c.vendor, c.toolchain, c.source)
                             for c in rep.claims)
    lines = [f"{len(rep.claims)} claims"]
    for (v, tc, s), n in sorted(by.items()):
        lines.append(f"  {v:5} {tc:6} {s:30} {n}")
    per_vendor = collections.Counter(c.vendor for c in rep.claims)
    lines.append("by vendor: " + ", ".join(f"{v} {n}" for v, n in
                                             sorted(per_vendor.items())))
    if rep.absent:
        lines.append(f"{len(rep.absent)} (entry, toolchain) pairs whose "
                     "edition lacks the quote (no claim for that release)")
    for p in rep.problems:
        lines.append("PROBLEM " + p)
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=("ingest", "check"))
    a = ap.parse_args(argv)
    rep = CL.ingest()
    print(summary(rep))
    if rep.problems:
        return 1
    if a.cmd == "ingest":
        CL.dump(rep.claims, CL.GENERIC, CL.HEADER)
        print(f"-> {CL.GENERIC.relative_to(ROOT)}")
        return 0
    same = CL.GENERIC.is_file() and CL.load(CL.GENERIC) == rep.claims
    print("up to date" if same else "STALE: run tools/derive/claims.py ingest")
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
