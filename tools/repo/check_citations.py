#!/usr/bin/env python3
"""Check every spec citation of the findings, the vendor drafts
and the rulings against the spec text (offload.engine.citations).

    python3 -I tools/repo/check_citations.py            # problems and counts
    python3 -I tools/repo/check_citations.py --all      # every citation
    python3 -I tools/repo/check_citations.py PATH ...   # these files only

Exit 1 when a citation does not check."""
import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from offload.engine import citations as C  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="*", type=Path)
    ap.add_argument("--all", action="store_true", help="list ok ones too")
    a = ap.parse_args(argv)
    paths = [p.resolve() for p in a.paths] or None
    try:
        res = C.scan(paths)
    except FileNotFoundError as e:
        missing = e.filename or (e.args[0] if e.args else "")     # spec_text raises FileNotFoundError(path)
        if "/spec/" not in str(missing):
            raise
        print(f"check_citations: {missing} is missing. The specification PDFs are not in the repository "
              "(spec/ is git-ignored); docs/tooling/setup.md says where to get them.", file=sys.stderr)
        return 2
    for r in res:
        if a.all or r.status not in ("ok", "external", "skipped"):
            print(r.line())
    n = Counter(r.status for r in res)
    print(f"{len(res)} citations: " + ", ".join(
        f"{k} {n[k]}" for k in C.STATUSES if n[k]))
    return 0 if set(n) <= {"ok", "external", "skipped"} else 1


if __name__ == "__main__":
    sys.exit(main())
