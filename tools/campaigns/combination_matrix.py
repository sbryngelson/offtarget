#!/usr/bin/env python3
"""Run the directive combination matrix against AFAR amdflang.

Run from the project root: python3 -I tools/campaigns/combination_matrix.py
[--workers N]. For every cell of offload.engine.combos (version x form x
order of leaves) it asks amdflang's frontend (``-fc1 -fopenmp
-fopenmp-version=<v> -fdebug-dump-parse-tree``, i.e. parse plus semantic
checks, offload.engine.flang_oracle) whether the program is accepted, and
writes tests/data/combination_matrix.json: one record per cell with the
spec's and our classification and flang's verdict (stage ok, parse or
semantics, and the first error line). data/reports/rules-coverage.md
(tools/derive/rules_coverage.py) renders it.
"""
import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine.combos import cells, source  # noqa: E402
from offload.engine.flang_oracle import FlangError, _dump  # noqa: E402

OUT = ROOT / "tests" / "data" / "combination_matrix.json"


def flang(src: str, version: int) -> tuple[str, str]:
    """(stage, first error line): stage ok, parse or semantics."""
    try:
        _dump(src, version, sema=True)
    except FlangError as e:
        if e.stage in ("run", "map"):
            raise
        errs = [ln for ln in e.message.splitlines() if "error:" in ln]
        msg = re.sub(r"^.*?error:\s*", "", errs[0]) if errs else \
            e.message.splitlines()[0]
        return e.stage, msg.strip()
    return "ok", ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=32)
    args = ap.parse_args()
    cs = cells()
    t0 = time.time()
    with ThreadPoolExecutor(args.workers) as ex:
        verdicts = list(ex.map(
            lambda c: flang(source(c.order, c.form), c.version), cs))
    rows = [{"version": c.version, "form": c.form, "order": list(c.order),
             "spec": c.spec, "ours": c.ours, "ours_why": c.why,
             "flang": stage, "flang_error": msg}
            for c, (stage, msg) in zip(cs, verdicts)]
    meta = {"tool": "AFAR amdflang -fc1 -fopenmp -fopenmp-version=<v> "
                    "-fdebug-dump-parse-tree (offload.engine.flang_oracle)",
            "date": time.strftime("%Y-%m-%d"), "cells": len(rows),
            "seconds": round(time.time() - t0)}
    OUT.write_text(json.dumps({"meta": meta, "cells": rows}, indent=0)
                   + "\n")
    print(f"{len(rows)} cells in {meta['seconds']} s -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
