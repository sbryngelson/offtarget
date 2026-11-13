#!/usr/bin/env python3
"""The confirmer's batch changes of one
rebuild, appended to data/reports/gate-changes/confirm-batches.tsv: one line
per case whose verdict or rule changed (case id, old verdict and rule, new
verdict and rule, the gate's verdict, the reason, and the findings it
links before and after: a link change is listed too).

    python3 -I tools/derive/confirm_batch_changes.py --rebuild t45fr1 \
        --pair results/confirm/batch_full.pre-t45fr1.jsonl \
               results/confirm/batch_full.jsonl [--pair OLD NEW ...]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TSV = ROOT / "data" / "reports" / "gate-changes" / "confirm-batches.tsv"
HEAD = ["rebuild", "batch", "case_id", "old_verdict", "old_rule",
        "new_verdict", "new_rule", "gate", "reason", "old_links",
        "new_links"]


def links(d: dict | None) -> str:
    """The findings a batch row links (duplicates), sorted."""
    return " ".join(sorted(h.get("file", "") for h in
                           (d or {}).get("findings") or []))


def rows(path: Path) -> dict:
    out = {}
    with open(path) as fh:
        for ln in fh:
            if not ln.strip():
                continue
            d = json.loads(ln)
            cid = (d.get("case") or {}).get("case_id")
            if cid:
                out[cid] = d
    return out


def changes(old: Path, new: Path) -> list[list[str]]:
    a, b = rows(old), rows(new)
    out = []
    for cid in sorted(set(a) | set(b)):
        x, y = a.get(cid), b.get(cid)
        ov, orule = (x["verdict"], x["rule"]) if x else ("(absent)", "")
        nv, nrule = (y["verdict"], y["rule"]) if y else ("(absent)", "")
        if (ov, orule) == (nv, nrule) and links(x) == links(y):
            continue
        why = (y or {}).get("reason") or (y or {}).get("rationale") or ""
        out.append([cid, ov, orule, nv, nrule, str((y or {}).get("gate")
                                                   or ""),
                    " ".join(str(why).split())[:200].replace("\t", " "),
                    links(x), links(y)])
    return out


def _name(path) -> str:
    """The batch's name (batch_full, batch_s1.final, batch_widen), also of
    a kept earlier copy (batch_full.pre-TAG.jsonl)."""
    return re.sub(r"\.pre-[^.]+$", "", Path(path).name.replace(".jsonl", ""))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rebuild", required=True)
    ap.add_argument("--pair", nargs=2, action="append", required=True,
                    metavar=("OLD", "NEW"))
    a = ap.parse_args(argv)
    TSV.parent.mkdir(parents=True, exist_ok=True)
    names = {_name(new) for _, new in a.pair}
    kept = []
    if TSV.is_file():
        # a rebuild's earlier lines for these batches are replaced (the
        # widened batch and the full batches of one rebuild are written by
        # two jobs)
        kept = [ln.split("\t") for ln in TSV.read_text().splitlines()[1:]
                if ln and not (ln.split("\t")[0] == a.rebuild and
                               ln.split("\t")[1] in names)]
    n = 0
    for old, new in a.pair:
        name = _name(new)
        for r in changes(Path(old), Path(new)):
            kept.append([a.rebuild, name] + r)
            n += 1
    TSV.write_text("\t".join(HEAD) + "\n" + "".join(
        "\t".join(r) + "\n" for r in kept))
    print(f"{n} changes of rebuild {a.rebuild} -> {TSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
