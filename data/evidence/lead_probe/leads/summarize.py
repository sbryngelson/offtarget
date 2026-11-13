#!/usr/bin/env python3
"""One line per lead job: compile rc, then each run's output
line(s). python3 -I data/evidence/lead_probe/leads/summarize.py RUNS.jsonl"""
import json
import sys
from collections import defaultdict

rows = [json.loads(x) for x in open(sys.argv[1]) if x.strip()]
by = defaultdict(list)
for r in rows:
    by[r["id"]].append(r)
for k in sorted(by):
    rs = by[k]
    comp = [r for r in rs if r["step"] == "compile"]
    runs = [r for r in rs if r["step"] == "run"]
    c = "compile rc=" + ",".join(str(r["rc"]) for r in comp)
    if any(r["rc"] for r in comp):
        c += " [" + comp[0]["out"].strip().splitlines()[-1][:120] + "]" \
            if comp[0]["out"].strip() else ""
    outs = []
    for r in runs:
        o = " | ".join(ln.strip() for ln in r["stdout"].splitlines()
                       if ln.strip())[:160]
        outs.append(f"rc={r['rc']}:{o}" + (" ERR:" + r["stderr"].strip()
                    .splitlines()[-1][:80] if r["rc"] and r["stderr"].strip()
                    else ""))
    node = rs[0].get("node", "")
    print(f"{k} [{node}] {c} :: " + " || ".join(outs))
