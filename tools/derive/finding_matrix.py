#!/usr/bin/env python3
"""The public site's finding matrix (offload/engine/site/matrix.py).

    python3 -I tools/derive/finding_matrix.py cases [--control harvest/x.c ...]
                                               # data/vendor/checks/cases-site.json: derived cases
                                               # for the findings no vendor-check case covers; a
                                               # finding's header control joins its case with --control
    python3 -I tools/derive/finding_matrix.py plan    # the runs still missing, per machine and toolchain
    python3 -I tools/derive/finding_matrix.py pack    # data/vendor/checks/results/site-*.jsonl ->
                                               # results-site/*.jsonl.gz (committed, scrubbed)

The runs: tools/jobs/run_site_matrix.sh MACHINE ENV (data/vendor/checks/run_checks.py with
--cases-file cases-site.json, results/site-<machine>.<env>.jsonl). Tuolumne in pbatch,
wingtip through the cap; Tioga is not run (no batch queue for this account there), so its
cells for new findings stay unknown.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine.site import header as H  # noqa: E402
from offload.engine.site import matrix as M  # noqa: E402


def cmd_cases(a):
    entries = (yaml.safe_load((ROOT / "data/findings/index.yaml").read_text()) or {}).get("findings", [])
    from offload.engine.confirm.findings import load_index
    known = {e["file"] for e in entries}
    base = ROOT / "data" / "findings"
    for f in load_index():   # fuzz findings come from their headers, not the index
        rel = str((ROOT / f.file).relative_to(base))
        if rel not in known:
            entries.append({"file": rel, "lang": f.lang, "outcome": f.outcome,
                            "expected": f.expected or None, "toolchains": list(f.toolchains)})
    headers = {e["file"]: H.parse(base / e["file"]) for e in entries if (base / e["file"]).is_file()}
    existing = json.loads((M.CHECKS / "cases.json").read_text())
    path = M.CHECKS / "cases-site.json"
    # controls already in the cases stay; --control FINDING adds the header's control of a finding
    have = {c["finding"] for c in (json.loads(path.read_text()) if path.is_file() else []) if c.get("control")}
    out = M.site_cases(entries, existing, headers, controls=have | set(a.control or ()))
    path.write_text(json.dumps(out, indent=1) + "\n")
    print(f"{len(out)} derived cases -> data/vendor/checks/cases-site.json")


def cmd_plan(_a):
    from offload.engine.confirm.findings import load_index
    base = ROOT / "data" / "findings"
    ids = []
    for f in load_index():
        h = H.parse(ROOT / f.file)
        if h.hide or (h.disposition and h.disposition[0] != "mixed"):
            continue
        ids.append(str((ROOT / f.file).relative_to(base)).rsplit(".", 1)[0])
    todo = M.plan(ids)
    c = Counter((t["machine"], t["tc"], t["variant"]) for t in todo)
    for k, n in sorted(c.items()):
        print(*k, n)
    print(f"{len(todo)} runs missing (per environment)")


def cmd_pack(_a):
    raw = sorted((M.CHECKS / "results").glob("site-*.jsonl"))
    M.pack(raw, M.SITE_RESULTS)
    print(f"{len(raw)} files -> {M.SITE_RESULTS.relative_to(ROOT)}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("cases", "plan", "pack"):
        p = sub.add_parser(name)
        if name == "cases":
            p.add_argument("--control", action="append", metavar="FINDING",
                           help="a finding (path under findings) whose header control is run too")
    a = ap.parse_args(argv)
    {"cases": cmd_cases, "plan": cmd_plan, "pack": cmd_pack}[a.cmd](a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
