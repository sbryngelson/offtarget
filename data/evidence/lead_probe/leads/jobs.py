#!/usr/bin/env python3
"""The jobs (data/evidence/gate_probe/probe.py's format) for the three
leads. python3 -I data/evidence/lead_probe/leads/jobs.py MACHINE > JOBS.jsonl
(MACHINE: tuolumne or tioga)."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
M = sys.argv[1] if len(sys.argv) > 1 else "tuolumne"
RED = ["red_assign.c", "red_maxform.c", "red_nomap.c", "red_int.c",
       "red_tdpf.c", "red_teams1.c", "red_tpfor.c", "red_diag.c",
       "red_assign.f90"]
LP = ["lp_int_map.c", "lp_ll_map.c", "lp_int_nomap.c", "lp_ll_nomap.c",
      "lp_float_map.c", "lp_double_map.c", "lp_short_map.c",
      "lp_int_tdist_map.c", "lp_int_tpfor_map.c", "lp_int_tpfor_nomap.c",
      "lp_int_split.c"]
TM = ["tm_host.f90", "tm_target.f90"]


def job(name, tc, xnack, opt="-O2", repeats=3):
    lang = "c" if name.endswith(".c") else "f90"
    return {"id": f"{name}:{tc}:x{xnack}:{opt}", "toolchain": tc,
            "xnack": xnack, "lang": lang, "model": "omp", "opt": opt,
            "files": [["prog.c" if lang == "c" else "prog.f90",
                       (HERE / name).read_text()]],
            "repeats": repeats, "offload": "mandatory",
            "compile_s": 600, "run_s": 120,
            "cflags": "-fopenmp-version=52" if lang == "c" else ""}


RED2 = ["red_sum.c", "red_min.c", "red_min_rev.c", "red_max_double.c",
        "red_max_nt4.c", "red_max_fmax.c", "red_sum_int.c", "red_maxform.f90"]
jobs = []
RED3 = ["red3_n1000.c", "red3_nt64.c", "red3_nt8.c", "red3_split.c",
        "red3_teams.c", "red_sum.c"]
if M == "tuolumne3":
    for x in (0, 1):
        for n in RED3:
            jobs.append(job(n, "afar", x))
    for n in RED3:
        jobs.append(job(n, "cce21_4", 0, repeats=1))
elif M in ("tuolumne2", "tioga2"):
    tc = "afar" if M == "tuolumne2" else "afar_g90"
    for x in ((0, 1) if M == "tuolumne2" else (0,)):
        for n in RED2 + ["lp_int_map.f90"]:
            jobs.append(job(n, tc, x))
        for n in ("red_maxform.c", "red_assign.c", "red_sum.c"):
            for opt in ("-O0", "-O1", "-O3"):
                jobs.append(job(n, tc, x, opt))
    if M == "tuolumne2":
        for t in ("cce19", "cce20", "cce21", "cce21_4"):
            for n in ("red_maxform.f90", "red_assign.f90", "red_maxform.c",
                      "red_sum.c"):
                jobs.append(job(n, t, 0, repeats=3))
elif M == "tuolumne":
    for x in (0, 1):
        for n in RED + LP:
            jobs.append(job(n, "afar", x))
        for n in ("red_assign.c", "lp_int_map.c", "lp_ll_map.c"):
            jobs.append(job(n, "afar", x, "-O0"))
    for tc in ("cce19", "cce20", "cce21", "cce21_4"):
        for n in ("red_assign.c", "red_assign.f90", "red_diag.c",
                  "lp_int_map.c", "lp_ll_map.c"):
            jobs.append(job(n, tc, 0, repeats=2))
        for n in TM:
            for opt in ("-O2", "-O0"):
                jobs.append(job(n, tc, 0, opt, repeats=1))
    for n in TM:
        jobs.append(job(n, "afar", 0, repeats=1))
else:
    for n in RED + LP:
        jobs.append(job(n, "afar_g90", 0))
    for tc in ("cce21_g90",):
        for n in ("red_assign.c", "lp_int_map.c"):
            jobs.append(job(n, tc, 0, repeats=2))
for j in jobs:
    if not j["cflags"]:
        j.pop("cflags")
    print(json.dumps(j))
