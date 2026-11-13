#!/usr/bin/env python3
"""The gate's four environments, by hand, for the two findings
promoted from the leads and their one-change controls (probe.py jobs):
(a) harness_<hex>, (b) GATE + 14 letters, (d) a second run in (a) on this
node; (c) the path of (a) on another node (MACHINE ending in "c").
    python3 -I data/evidence/lead_probe/confirm_jobs.py tuolumne|tuolumnec|tioga
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
M = sys.argv[1]
F1 = (ROOT / "data/findings/afar-c-teams-distribute-reduction-first-team.c"
      ).read_text()
F2 = (ROOT / "data/findings/afar-c-lastprivate-distribute-parallel-for-"
      "small-type.c").read_text()
CASES = [
    ("red", F1, "-O2"),
    ("red-ctl-O0", F1, "-O0"),
    ("red-ctl-nt8", F1.replace("target teams distribute reduction(+: l)",
                               "target teams distribute num_teams(8) "
                               "reduction(+: l)"), "-O2"),
    ("lp", F2, "-O2"),
    ("lp-ctl-ll", F2.replace("int lp = -1;", "long long lp = -1;")
     .replace('printf("lp= %d dev', 'printf("lp= %lld dev'), "-O2"),
]
for name, text, _ in [c for c in CASES if "ctl-nt8" in c[0] or "ctl-ll" in c[0]]:
    assert text not in (F1, F2), name
tcs = {"tuolumne": ["afar"], "tuolumnec": ["afar"], "tioga": ["afar_g90"]}[M]
reps = 1 if M == "tuolumnec" else 2


def dirs_of(case: str) -> list:
    """(a) harness_<8 hex> and (b) GATE + 14 upper-case letters, one pair
    per case (concurrent jobs never share a directory); (c) reuses (a)."""
    h = hashlib.sha256(case.encode()).hexdigest()
    a = f"harness_{h[:8]}"
    b = "GATE" + "".join(chr(65 + int(h[i:i + 2], 16) % 26)
                         for i in range(8, 36, 2))
    return [a] if M == "tuolumnec" else [a, b]


for tc in tcs:
    for x in ((0,) if tc.endswith("g90") else (1, 0)):
        for name, text, opt in CASES:
            dirs = dirs_of(f"{name}:{tc}:x{x}")
            print(json.dumps({
                "id": f"{name}:{tc}:x{x}:{M}", "toolchain": tc, "xnack": x,
                "lang": "c", "model": "omp", "opt": opt,
                "cflags": "-fopenmp-version=52",
                "files": [["prog.c", text]], "repeats": reps,
                "offload": "mandatory", "dirs": dirs, "compile_s": 600,
                "run_s": 120}))
if M == "tuolumne":
    for t in ("cce19", "cce20", "cce21", "cce21_4"):
        print(json.dumps({
            "id": f"red:{t}:x0:{M}", "toolchain": t, "xnack": 0,
            "lang": "c", "model": "omp", "opt": "-O2",
            "cflags": "-fopenmp-version=52", "files": [["prog.c", F1]],
            "repeats": 1, "offload": "mandatory", "compile_s": 600,
            "run_s": 120}))
