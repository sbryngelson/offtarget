# Follow-up: the effective stress rows (stress_report.load) without and with the t43 reruns; prints every changed (id, toolchain, mode, variant)
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[5]))
from offload.engine import stress_report as R
old = tuple(r for r in R.STRESS_RUNS if not r.startswith("t43"))
_, a = R.load(old); _, b = R.load(R.STRESS_RUNS)
ka = {(r["id"], r["toolchain"], r["mode"], r["variant"]): r for r in a}
kb = {(r["id"], r["toolchain"], r["mode"], r["variant"]): r for r in b}
print("rows", len(ka), len(kb), "new keys", len(set(kb) - set(ka)))
ch = [(k, ka[k]["cls"], kb[k]["cls"], ka[k]["reason"][:50], kb[k]["reason"][:50]) for k in kb if k in ka and (ka[k]["cls"], ka[k]["reason"][:40]) != (kb[k]["cls"], kb[k]["reason"][:40])]
for c in sorted(ch): print(*c, sep=" | ")
print("changed", len(ch))
