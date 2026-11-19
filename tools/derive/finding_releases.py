#!/usr/bin/env python3
"""Write, or check, the generated `releases` line of every finding header
(offload/engine/finding_releases.py): what each release of a compiler family does with the
finding's file in the site matrix (the committed check rows, data/vendor/checks/results-site).

    python3 -I tools/derive/finding_releases.py            # rewrite the lines
    python3 -I tools/derive/finding_releases.py --check    # list the findings whose line is stale

Run it after the site matrix changes (a release added, data/vendor/checks/results-site repacked);
tools/regenerate.py --check (step finding-releases) runs the comparison.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine import finding_releases as FR  # noqa: E402
from offload.engine.confirm.findings import INDEX  # noqa: E402

FINDINGS = ROOT / "data" / "findings"


def files() -> list[Path]:
    """The finding files of the index (data/findings/index.yaml)."""
    import yaml
    return [FINDINGS / e["file"] for e in yaml.safe_load(INDEX.read_text())["findings"]
            if (FINDINGS / e["file"]).is_file()]


def wanted() -> dict[Path, str]:
    """file -> its text with the current line."""
    from offload.engine.site import matrix as M
    rows, cases = M._rows(), M._cases()           # read once, not once per finding
    out = {}
    for f in files():
        text = f.read_text()
        fid = str(f.relative_to(FINDINGS)).rsplit(".", 1)[0]
        out[f] = FR.apply(text, FR.value(fid, M.cells(fid, rows=rows, cases=cases)))
    return out


def stale() -> list[str]:
    return [str(f.relative_to(ROOT)) for f, t in wanted().items() if t != f.read_text()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    if a.check:
        bad = stale()
        for f in bad:
            print(f"{f}: releases line stale (python3 -I tools/derive/finding_releases.py)")
        return 1 if bad else 0
    n = 0
    for f, t in wanted().items():
        if t != f.read_text():
            f.write_text(t)
            n += 1
    print(f"{n} findings rewritten")
    return 0


if __name__ == "__main__":
    sys.exit(main())
