#!/usr/bin/env python3
"""Coverage parity runs: GCC 16.2 (gcc_g90 on Tioga, gcc_sm80 on wingtip) on
the corpora the other families ran beyond the catalog (harvest dev sets,
stress sweeps, application corpus, a fuzz sample), and NVHPC 25.11/26.9 on
the fuzz sample. Results go to results/parity/.

    # seeded fuzz sample; writes catalog/parity_fuzz_sample.json
    python3 -I tools/campaigns/parity.py fuzz-sample [--n 5000]

    # pre-run check of the stress sweeps (Tuolumne compute node, AFAR front
    # end); writes results/parity/stress-checked/programs.jsonl, which the
    # wingtip and Tioga sweeps read (COMPLIANT_PRERUN_STORED)
    python3 -I tools/campaigns/parity.py stress-check [--workers 32]

Also: gate-plan, gate-run, gate-verdicts, c-cells, confirm-fuzz,
harvest-combine, summary."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

OUT = ROOT / "results" / "parity"
FUZZ = ROOT / "results" / "fuzz"
SAMPLE = ROOT / "catalog" / "parity_fuzz_sample.json"
ALL = ["types", "derived", "alloc", "declare", "multitu"]

# One stratum per program set: a fuzz program is its seed, generator
# version and base-language groups, so campaigns of one set in two memory
# modes (s1/s1x0, b<k>/x0-<group>) are one stratum. `runs`: the stored
# records whose legality verdicts the runs read (wingtip and Tioga have no
# AFAR flang or gfortran gate: COMPLIANT_FUZZ_CHECKS).
STRATA = {
    "c1": {"gen_version": "fuzz-1", "base": [], "runs": ["c1"]},
    "b0": {"gen_version": "fuzz-3", "base": [], "runs": ["b0"]},
    "b1": {"gen_version": "fuzz-3", "base": ["types"], "runs": ["b1"]},
    "b2": {"gen_version": "fuzz-3", "base": ["derived"], "runs": ["b2"]},
    "b3": {"gen_version": "fuzz-3", "base": ["alloc"], "runs": ["b3"]},
    "b4": {"gen_version": "fuzz-3", "base": ["declare"], "runs": ["b4"]},
    "b5": {"gen_version": "fuzz-3", "base": ["multitu"], "runs": ["b5"]},
    "s1": {"gen_version": "fuzz-3", "base": ALL, "runs": ["s1"]},
    # NVHPC 25.11 and 26.9 ran every program of these two
    "n0": {"gen_version": "fuzz-4s50", "base": [], "runs": ["n0x0-amd"],
           "nvhpc_ran": True},
    "n1": {"gen_version": "fuzz-4s50", "base": ALL, "runs": ["n1x0-amd"],
           "nvhpc_ran": True},
}
# the campaign a stratum's programs are known by in the stored results, its
# copy-mode run where one exists (the confirmer's evidence is per memory
# mode): b<k> ran at HSA_XNACK=1 only, x0-<group> the same programs at 0
FUZZ_IDENT = {"c1": "c1", "b0": "b0", "b1": "x0-types", "b2": "x0-derived",
              "b3": "x0-alloc", "b4": "x0-declare", "b5": "x0-multitu",
              "s1": "s1", "n0": "n0", "n1": "n1"}
CHECK_KEYS = ("seed", "gen_version", "base", "expected", "check",
              "check_detail")


def _jl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines()
            if ln.strip()]


def eligible(rec: dict) -> bool:
    """A program the campaign's legality gate passed and its host check did
    not find noncompliant (records before the host check have no
    validity)."""
    return rec.get("check") == "ok" and \
        rec.get("validity") in (None, "valid")


def _rank(stratum: str, seed: int) -> str:
    return hashlib.sha256(f"parity:{stratum}:{seed}".encode()).hexdigest()


def sample(strata: dict[str, list[dict]], n: int) -> dict[str, list[int]]:
    """stratum -> sorted seeds: n programs in all, each stratum's share
    proportional to its eligible programs (largest remainder), the seeds of
    a stratum the first by a fixed hash of (stratum, seed)."""
    elig = {k: sorted({r["seed"] for r in v if eligible(r)})
            for k, v in strata.items()}
    tot = sum(len(v) for v in elig.values())
    n = min(n, tot)
    quota = {k: n * len(v) / tot for k, v in elig.items()}
    take = {k: int(q) for k, q in quota.items()}
    left = n - sum(take.values())
    for k in sorted(quota, key=lambda k: (-(quota[k] - take[k]), k))[:left]:
        take[k] += 1
    return {k: sorted(sorted(v, key=lambda s: _rank(k, s))[:take[k]])
            for k, v in elig.items()}


def check_lines(recs: list[dict], seeds: set) -> list[str]:
    """The stored-check lines (offload.engine.fuzz_exec.stored_check) of the
    sampled seeds."""
    return [json.dumps({k: r.get(k) for k in CHECK_KEYS})
            for r in recs if r["seed"] in seeds]


def stratum_records(name: str) -> list[dict]:
    st = STRATA[name]
    out = {}
    for run in st["runs"]:
        for r in _jl(FUZZ / run / "programs.jsonl"):
            if r.get("gen_version") == st["gen_version"] and \
                    list(r.get("base") or []) == st["base"]:
                out[r["seed"]] = r
    return [out[s] for s in sorted(out)]


def cmd_fuzz_sample(a) -> int:
    recs = {k: stratum_records(k) for k in STRATA}
    picks = sample(recs, a.n)
    SAMPLE.write_text(json.dumps(
        {"n": sum(len(v) for v in picks.values()),
         "rule": "per stratum (generator version, base groups): its share "
                 "of the legal, valid programs (largest remainder); seeds "
                 "ranked by sha256('parity:<stratum>:<seed>')",
         "strata": {k: {**{x: STRATA[k][x] for x in ("gen_version", "base",
                                                      "runs")},
                        "nvhpc_ran": bool(STRATA[k].get("nvhpc_ran")),
                        "eligible": sum(eligible(r) for r in recs[k]),
                        "seeds": v} for k, v in picks.items()}},
        indent=1) + "\n")
    d = OUT / "fuzz" / "checks"
    d.mkdir(parents=True, exist_ok=True)
    for k, v in picks.items():
        (d / f"{k}.jsonl").write_text("".join(
            ln + "\n" for ln in check_lines(recs[k], set(v))))
        print(k, len(v), "of", sum(eligible(r) for r in recs[k]))
    return 0


def stratum_of_run(run: str) -> str:
    """par-<stratum>-<toolchains>"""
    return run.split("-")[1]


def fuzz_items_of(recs: list[dict], run: str, xnack: int) -> list[dict]:
    """The gate items of a parity fuzz run's failing rows (as
    offload.engine.gate_stored.fuzz_items, the ident by FUZZ_IDENT)."""
    from offload.engine.gate_stored import _mode, machine_of
    from offload.engine.toolchains import TOOLCHAINS
    camp = FUZZ_IDENT[stratum_of_run(run)]
    out = []
    for pr in recs:
        if pr.get("check") != "ok" or \
                pr.get("validity") not in (None, "valid"):
            continue
        for tc, r in (pr.get("results") or {}).items():
            if tc not in TOOLCHAINS or r["cls"] in ("agree",
                                                    "harness_error"):
                continue
            out.append({
                "campaign": "fuzz", "kind": "fuzz",
                "cell": f"fuzz|{run}:{pr['seed']}|{tc}|{xnack}",
                "ident": f"{camp}:{pr['seed']}", "toolchain": tc,
                "machine": machine_of(tc), "xnack": xnack,
                "mode": _mode(tc, xnack), "opt": "-O2", "cls": r["cls"],
                "reason": r.get("reason", ""), "checksum": r.get("checksum"),
                "flaky": bool(r.get("flaky")),
                "compile_s": r.get("compile_s") or None,
                "run_s": r.get("run_s") or None, "timeout_s": 60,
                "build_dir": r.get("build_dir") or "",
                "node": r.get("node") or "",
                "toolchain_build": r.get("toolchain_build") or "",
                "compile_log": (r.get("output") or "")[-3000:],
                "origin": f"{run}#seed={pr['seed']}",
                "locator": {"run": run, "seed": pr["seed"],
                            "gen_version": pr["gen_version"],
                            "base": list(pr.get("base") or ()),
                            "expected": pr.get("expected")}})
    return out


# --- stress ---------------------------------------------------------------------------
# GCC's sweeps: NVHPC's (nv1-omp, nv1-acc, nv1-c: every axis at the key
# sizes; nv2-var/nv3-var: the build variants and layouts of the multi-unit
# axes), separate memory only. nordc is NVHPC's own flag.
STRESS_SWEEPS = {
    "pg-omp": "--axes all --sizes key --models omp",
    "pg-acc": "--axes all --sizes key --models acc",
    "pg-c": "--axes all --sizes key --models c",
    "pg-var": "--axes tu.plain,tu.submodule,tuimp,calls --sizes 3,12 "
              "--models omp,acc --variants O0,O2,O3,lto,noinline,staticlib "
              "--layouts single,per_unit,partition",
}
STRESS_CHECKED = OUT / "stress-checked" / "programs.jsonl"


def stress_step(run: str, tc: str) -> str:
    return f"stress:{run}:{tc}:" + STRESS_SWEEPS[run].replace(" ", "+")


def _stress_ns(args: str):
    ns = argparse.Namespace(models="omp", axes="all", sizes="key",
                            layouts="single", seeds="1", variants="O2")
    words = args.split()
    for k in range(0, len(words), 2):
        setattr(ns, words[k][2:].replace("-", "_"), words[k + 1])
    return ns


def stress_specs() -> list[dict]:
    """Every program of the sweeps, once."""
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    import stress as ST
    out = {}
    for args in STRESS_SWEEPS.values():
        for s in ST.program_specs(_stress_ns(args)):
            out.setdefault(stress_pid(s), s)
    return list(out.values())


def stress_pid(spec: dict) -> str:
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    import stress as ST
    return ST.pid(spec)


def cmd_stress_check(a) -> int:
    """tools/campaigns/stress.py's check task (the gate, the pre-run check, the
    elision) of every sweep program not checked yet."""
    from concurrent.futures import ProcessPoolExecutor, as_completed
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    import stress as ST
    STRESS_CHECKED.parent.mkdir(parents=True, exist_ok=True)
    done = {stress_pid(d) for d in _jl(STRESS_CHECKED) if "axis" in d}
    todo = [s for s in stress_specs() if stress_pid(s) not in done]
    print(f"{len(todo)} programs to check ({len(done)} done)", flush=True)
    with ProcessPoolExecutor(a.workers) as ex, STRESS_CHECKED.open("a") as f:
        futs = [ex.submit(ST.check_task, s) for s in todo]
        for k, fu in enumerate(as_completed(futs), 1):
            f.write(fu.result() + "\n")
            f.flush()
            if k % 50 == 0:
                print(f"{k}/{len(todo)}", flush=True)
    return 0


# --- the reproduction gate over the lane's fuzz and stress rows ---------------------
# The gate (offload.engine.gate: four environments, judge) on the lane's
# own plan, reruns and verdicts under results/parity/gate/<campaign>/ (as
# tools/campaigns/gcc_lane.py does for GCC's catalog rows): every failing row is
# planned, the shared results/gate/ is never touched.

GATE = OUT / "gate"
GATE_CAMPAIGNS = ("fuzz", "stress")


def lane_fuzz_runs(base: Path = FUZZ) -> list[Path]:
    return sorted(p for p in base.glob("par-*") if (p / "programs.jsonl")
                  .is_file())


def fuzz_items(base: Path = FUZZ) -> list[dict]:
    out = []
    for d in lane_fuzz_runs(base):
        meta = json.loads((d / "meta.json").read_text()) if \
            (d / "meta.json").is_file() else {}
        x = int(((meta.get("sessions") or [{}])[0]).get("xnack", 0))
        out += fuzz_items_of(_jl(d / "programs.jsonl"), d.name, x)
    return out


STRESS_SKIP = ("agree", "harness_error", "skipped", "probe_rejected",
               "probe_accepted", "prerun_refused")


def stress_items(base: Path = ROOT / "results" / "stress",
                 checked: Path = STRESS_CHECKED) -> list[dict]:
    """offload.engine.gate_stored.stress_items over the lane's pg-* sweeps,
    their programs from the pre-run check's records."""
    from offload.engine import stress_report as SR
    from offload.engine.gate_stored import _mode, machine_of
    from offload.engine.toolchains import TOOLCHAINS
    progs = {p["id"]: p for p in _jl(checked) if "id" in p}
    out = []
    for d in sorted(base.glob("pg-*")):
        for r in _jl(d / "rows.jsonl"):
            p = progs.get(r.get("id"))
            if "crash" in r or r.get("toolchain") not in TOOLCHAINS or \
                    r.get("cls") in STRESS_SKIP or not SR.valid(p) or \
                    p.get("legality", "legal") != "legal":
                continue
            tc, lim = r["toolchain"], r.get("limits") or {}
            out.append({
                "campaign": "stress", "kind": "stress",
                "cell": f"stress|{r['id']}|{tc}|{r['mode']}|{r['variant']}",
                "ident": r["id"], "toolchain": tc,
                "machine": machine_of(tc), "xnack": r["mode"],
                "mode": _mode(tc, r["mode"]), "variant": r["variant"],
                "axis": r.get("axis", ""), "cls": r["cls"],
                "reason": r.get("reason", ""),
                "checksum": r.get("checksum"),
                "bad_kernels": r.get("bad_kernels") or [],
                "flaky": bool(r.get("flaky")),
                "compile_s": r.get("compile_s") or None,
                "run_s": r.get("run_s") or None,
                "timeout_s": lim.get("run_s", 120),
                "build_dir": r.get("build_dir", ""),
                "node": r.get("host", ""),
                "toolchain_build": r.get("toolchain_build", ""),
                "compile_log": (r.get("output") or "")[-3000:],
                "origin": f"{d.name}/rows.jsonl",
                "locator": {"axis": p["axis"], "size": p["size"],
                            "seed": p["seed"], "model": p["model"],
                            "lang": p.get("lang", "f90"),
                            "layout": p.get("layout", "single"),
                            "id": r["id"], "limits": lim}})
    return out


def only_toolchains(items: list[dict], toolchains) -> list[dict]:
    return [it for it in items if not toolchains or
            it["toolchain"] in toolchains]


def cmd_gate_plan(a) -> int:
    from collections import Counter
    from offload.engine import gate as G
    for camp in a.campaigns:
        its = only_toolchains(fuzz_items() if camp == "fuzz" else
                              stress_items(), a.toolchains)
        if a.only_cells:    # a top-up: only the cells a file lists
            keep = set(Path(a.only_cells).read_text().split())
            its = [it for it in its if it["cell"] in keep]
        # every row, or (a budget in serial rerun hours) a sample per
        # signature with the compile-time rest inheriting
        p = G.plan(its, budget_s=a.budget_h * 3600 if a.budget_h
                   else float("inf"))
        d = GATE / camp
        d.mkdir(parents=True, exist_ok=True)
        (d / "plan.jsonl").write_text("".join(json.dumps(r) + "\n"
                                              for r in p["rows"]))
        print(camp, len(p["rows"]), "rows,",
              Counter((r["machine"], r["toolchain"]) for r in p["rows"]),
              f"{p['total_s'] / 3600:.2f} serial rerun hours")
    return 0


def c_cells(plan: list[dict], toolchain: str | None = None) -> list[str]:
    """The rows whose (c) must run on another node (parity, the
    ruling of 2026-10-29): every row that is no inheritable
    compile-time failure (run-time failures, generic compile failures) and
    one row of each inheritable signature (the first cell), which the
    signature's other rows inherit (``c_status``)."""
    from offload.engine import gate as G
    out, seen = [], set()
    for it in sorted(plan, key=lambda r: r["cell"]):
        if toolchain and it["toolchain"] != toolchain:
            continue
        if not G.inheritable(it):
            out.append(it["cell"])
        elif it["signature"] not in seen:
            seen.add(it["signature"])
            out.append(it["cell"])
    return out


def c_status(plan: list[dict], judged: dict) -> dict[str, str]:
    """cell -> how its (c) stands: ``own`` (a valid (c) on another node,
    ``node_distinct``), ``inherited`` (an inheritable compile-time row
    whose signature has a row with its own (c) and the verdict
    ``confirmed``) or ``missing``."""
    from offload.engine import gate as G
    good = {it["signature"] for it in plan
            if (judged.get(it["cell"]) or {}).get("node_distinct") and
            (judged.get(it["cell"]) or {}).get("verdict") == "confirmed"}
    out = {}
    for it in plan:
        j = judged.get(it["cell"]) or {}
        out[it["cell"]] = "own" if j.get("node_distinct") else (
            "inherited" if G.inheritable(it) and it["signature"] in good
            else "missing")
    return out


def cmd_c_cells(a) -> int:
    plan = _jl(GATE / a.campaign / "plan.jsonl")
    cells = c_cells(plan, a.toolchain)
    path = GATE / a.campaign / f"c_cells.{a.toolchain}.txt"
    path.write_text("".join(c + "\n" for c in cells))
    print(a.campaign, a.toolchain, len(cells), "cells ->", path)
    return 0


def cmd_gate_run(a) -> int:
    """tools/campaigns/gate.py run on the lane's plan (its output paths patched to
    results/parity/gate; no budget: the plan is the budget); ``--cells``
    limits it to the cells a file lists (``c_cells``)."""
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    import gate as GT
    GT.OUT = GATE
    GT.LEDGER = GATE / "ledger.jsonl"
    if getattr(a, "cells", None):
        keep = set(Path(a.cells).read_text().split())
        read = GT._jl

        def _jl(path):
            rows = read(path)
            return [r for r in rows if r.get("cell") in keep] \
                if Path(path).name == "plan.jsonl" else rows
        GT._jl = _jl
    ns = argparse.Namespace(campaign=a.campaign, machine=a.machine,
                            envs=a.envs, shard=a.shard, workers=a.workers,
                            limit_s=a.limit_s, budget_gpu_h=1e9, gpus=1,
                            concurrent=a.workers)
    return GT.cmd_run(ns)


def gate_verdicts(camp: str) -> dict[str, dict]:
    from collections import defaultdict
    from offload.engine import gate as G
    rr: dict = defaultdict(list)
    for p in sorted((GATE / camp / "reruns").glob("*.jsonl")):
        for r in _jl(p):
            rr[r["cell"]].append(r)
    out = {}
    plan = _jl(GATE / camp / "plan.jsonl")
    judged = {}
    for it in plan:
        try:
            judged[it["cell"]] = G.judge(it, rr.get(it["cell"], []))
        except ValueError:
            pass
    # a sampled plan (a budget): an inheritable row not rerun takes its
    # signature's verdict (offload.engine.gate.inherit)
    final = G.inherit(plan, {c: j["verdict"] for c, j in judged.items()
                             if j.get("verdict")})
    cs = c_status(plan, judged)
    for it in plan:
        v = dict(judged.get(it["cell"]) or {"verdict": None,
                                             "missing": list(G.ENVS)})
        v["c"] = cs[it["cell"]]
        f = final.get(it["cell"]) or {}
        if f.get("verdict") and (v.get("verdict") is None or
                                 f.get("inherited")):
            v.update(verdict=f["verdict"], inherited=bool(f.get("inherited")))
        out[it["cell"]] = {"cell": it["cell"], "campaign": camp,
                           "kind": it["kind"], "ident": it["ident"],
                           "toolchain": it["toolchain"],
                           "xnack": it["xnack"], "cls": it.get("cls"),
                           "reason": (it.get("reason") or "")[:300],
                           "signature": it.get("signature"), **v}
    return out


def cmd_gate_verdicts(a) -> int:
    from collections import Counter
    rows = []
    for camp in GATE_CAMPAIGNS:
        rows += list(gate_verdicts(camp).values())
    GATE.mkdir(parents=True, exist_ok=True)
    (GATE / "verdicts.jsonl").write_text("".join(json.dumps(r) + "\n"
                                                 for r in rows))
    print(Counter((r["campaign"], r["toolchain"], r["verdict"], r["c"])
                  for r in rows))
    return 0


# --- the confirmer over the lane's fuzz rows ---------------------------------------------
# Stored evidence only (no runs): the stored results (offload.engine.confirm.
# ingest.stored_index: the full result files and every fuzz campaign) plus
# the lane's rows (GCC and NVHPC), each under its program set's campaign
# ident (FUZZ_IDENT), the lane's gate verdicts. GCC is never evidence for
# another family (catalog/machines.yaml under_test_only).

def lane_fuzz_rows(roots) -> list:
    from offload.engine.confirm import ingest as I
    out = []
    for root in roots:
        for d in lane_fuzz_runs(Path(root)):
            meta = json.loads((d / "meta.json").read_text()) if \
                (d / "meta.json").is_file() else {}
            x = int(((meta.get("sessions") or [{}])[0]).get("xnack", 0))
            camp = FUZZ_IDENT[stratum_of_run(d.name)]
            for rec in _jl(d / "programs.jsonl"):
                if rec.get("check") != "ok":
                    continue
                out += I.rows_of_fuzz(rec, d.name, x,
                                      f"{d.name}#seed={rec['seed']}", camp)
    return out


def cmd_confirm_fuzz(a) -> int:
    from collections import Counter
    from offload.engine import gate as G
    from offload.engine.confirm import engine as EN
    from offload.engine.confirm import ingest as I
    from offload.engine.confirm.collectors import Context
    from offload.engine.confirm.store import Store
    G.VERDICTS_FILE = Path(a.verdicts)
    rows = lane_fuzz_rows(a.roots)
    idx = I.stored_index()
    idx.add(rows)
    out_dir = OUT / "confirm"
    out_dir.mkdir(parents=True, exist_ok=True)
    ctx = Context(idx, Store(out_dir / "fuzz_evidence.jsonl"),
                  allow_run=False)
    todo = [r for r in I.failing_rows(rows)
            if not a.toolchains or r.toolchain in a.toolchains]
    print(len(rows), "rows,", len(todo), "failing", flush=True)
    n = Counter()
    with (out_dir / "fuzz.jsonl").open("w") as fh:
        for r in todo:
            case = I.case_of_row(r)
            try:
                res = EN.confirm(case, ctx, minimize=False, draft=False)
            except Exception as e:
                res = {"verdict": "error", "rule": "",
                       "reason": f"{type(e).__name__}: {e}"[:300]}
            res.pop("evidence", None)
            res.update(ident=r.ident, toolchain=r.toolchain, mode=r.mode,
                       outcome=r.outcome, run=r.extra.get("run"))
            fh.write(json.dumps(res, default=str) + "\n")
            n[(r.toolchain, res.get("verdict"), res.get("rule"))] += 1
    for k, v in sorted(n.items(), key=str):
        print(k, v)
    return 0


# --- what ran, per source and toolchain --------------------------------------------------

HARVEST_SETS = ("harvest", "harvest-known", "harvest2")
PASS_ROW = ("correct_on_device", "unobservable")
PASS_FUZZ = ("agree",)
PASS_STRESS = ("agree", "probe_rejected", "probe_accepted")


def _last(rows: list[dict], key) -> list[dict]:
    out = {}
    for r in rows:
        out[key(r)] = r
    return list(out.values())


def summary(machines) -> dict:
    """(source, toolchain) -> {run, failing}: the cells each pulled lane
    ran (results/parity/<machine>/results/...; a harvest set's last row per
    cell)."""
    from collections import defaultdict
    s: dict = defaultdict(lambda: {"run": 0, "failing": 0})

    def add(src, tc, ok):
        s[(src, tc)]["run"] += 1
        s[(src, tc)]["failing"] += 0 if ok else 1
    for m in machines:
        r = Path(m) / "results"
        for hs in HARVEST_SETS:
            rows = []
            for f in sorted((r / hs / "parity").glob("rows*.jsonl")):
                rows += _jl(f)
            for x in _last(rows, lambda x: (x["program_id"], x["toolchain"],
                                            x["xnack"])):
                add("harvest", x["toolchain"], x["outcome"] in PASS_ROW)
        for d in lane_fuzz_runs(r / "fuzz"):
            for p in _jl(d / "programs.jsonl"):
                if p.get("check") != "ok":
                    continue
                for tc, x in (p.get("results") or {}).items():
                    add("fuzz", tc, x["cls"] in PASS_FUZZ)
        for d in sorted((r / "stress").glob("pg-*")):
            for x in _last(_jl(d / "rows.jsonl"),
                           lambda x: (x.get("id"), x.get("toolchain"),
                                      x.get("mode"), x.get("variant"))):
                if "toolchain" in x and x.get("cls") != "prerun_refused":
                    add("stress", x["toolchain"], x.get("cls") in PASS_STRESS)
        for f in sorted((r / "apps" / "runs").glob("*.jsonl")):
            for x in _jl(f):
                if x.get("outcome") != "not_applicable":
                    add("apps", x["toolchain"],
                        x.get("outcome") == "correct_on_device")
    return dict(s)


def harvest_combine(set_dir: Path, mains, lanes, set_name: str,
                    name: str = "parity") -> Path:
    """<set>/<name>/: the main runs' rows of the dev programs (the other
    families: the confirmer's evidence) and each pulled lane's rows and gate
    reruns of the set's parity run, one part per source (tools/campaigns/harvest.py
    reads every part)."""
    set_dir = Path(set_dir)
    dev = {p["id"] for p in _jl(set_dir / "programs.jsonl")
           if not p.get("holdout")}
    out = set_dir / name
    out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("*.part.*.jsonl"):
        f.unlink()
    for m in mains:
        rows = []
        for f in sorted((set_dir / m).glob("rows*.jsonl")):
            rows += [r for r in _jl(f) if r.get("program_id") in dev]
        (out / f"rows.part.{m}.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows))
    for lane in lanes:
        lane = Path(lane)
        src = lane / "results" / set_name / "parity"
        for kind in ("rows", "gate_reruns"):
            rows = []
            for f in sorted(src.glob(f"{kind}*.jsonl")):
                rows += _jl(f)
            # dev programs only (a gate rerun's cell names its program:
            # "harvest|<id>|<toolchain>|<mode>")
            rows = [r for r in rows if (
                r.get("program_id") if kind == "rows" else
                (str(r.get("cell", "")).split("|") + [""])[1]) in dev]
            (out / f"{kind}.part.{lane.name}.jsonl").write_text(
                "".join(json.dumps(r) + "\n" for r in rows))
    return out


def cmd_harvest_combine(a) -> int:
    for s, mains in (("harvest", ["main"]),
                     ("harvest-known", ["main", "main.wingtip",
                                        "main.tioga"]),
                     ("harvest2", ["main"])):
        out = harvest_combine(ROOT / "results" / s, mains, a.lanes, s)
        print(s, "->", out)
    return 0


def cmd_summary(a) -> int:
    s = summary(a.machines)
    for (src, tc), v in sorted(s.items()):
        print(f"{src:8} {tc:10} run {v['run']:5} failing {v['failing']:5}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("fuzz-sample")
    p.add_argument("--n", type=int, default=5000)
    p = sub.add_parser("stress-check")
    p.add_argument("--workers", type=int, default=32)
    p = sub.add_parser("gate-plan")
    p.add_argument("--campaigns", nargs="+", default=list(GATE_CAMPAIGNS))
    p.add_argument("--toolchains", nargs="*")
    p.add_argument("--budget-h", type=float, default=None,
                   help="serial rerun hours (default: every row)")
    p.add_argument("--only-cells", help="a file of cell ids: plan only these")
    p = sub.add_parser("gate-run")
    p.add_argument("--campaign", required=True, choices=GATE_CAMPAIGNS)
    p.add_argument("--machine", required=True, choices=("tioga", "wingtip"))
    p.add_argument("--envs", default="a,b,d")
    p.add_argument("--shard")
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--limit-s", type=float, default=3600)
    p.add_argument("--cells", help="a file of cells (c-cells): only these")
    p = sub.add_parser("c-cells")
    p.add_argument("--campaign", required=True, choices=GATE_CAMPAIGNS)
    p.add_argument("--toolchain", required=True)
    sub.add_parser("gate-verdicts")
    p = sub.add_parser("confirm-fuzz")
    p.add_argument("--roots", nargs="+", required=True,
                   help="directories holding the lane's par-* fuzz runs")
    p.add_argument("--verdicts", required=True)
    p.add_argument("--toolchains", nargs="*")
    p = sub.add_parser("harvest-combine")
    p.add_argument("lanes", nargs="+", help="pulled lanes")
    p = sub.add_parser("summary")
    p.add_argument("machines", nargs="+",
                   help="pulled lanes (results/parity/<machine>)")
    a = ap.parse_args(argv)
    return {"summary": cmd_summary, "harvest-combine": cmd_harvest_combine, "fuzz-sample": cmd_fuzz_sample,
            "stress-check": cmd_stress_check,
            "gate-plan": cmd_gate_plan, "gate-run": cmd_gate_run,
            "gate-verdicts": cmd_gate_verdicts, "c-cells": cmd_c_cells,
            "confirm-fuzz": cmd_confirm_fuzz}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
