"""The usage profile of real offload code and what the fuzzer takes from it.

Sources: the application corpus (data/bench/apps/manifest.yaml, with MFC's
generated OpenMP and OpenACC builds); the other offload codes cloned under
corpus/apps, measured the same way and reported in their own column; and
the dev half of data/bench/wild (data/bench/wild/split.yaml) with its run records in
results/wild/runs. data/bench/fresh and results/fresh are never read.

build returns the profile (catalog/fuzz_profile.json): per code base and
combined, the distributions measured by offload.engine.usage.profile_files
(clause list lengths, loop depth, collapse, module and derived-type
structure, cross-file device call depth and so on), the region feature
frequencies, the features of failing real regions and their enrichment
(the boost list of offload.engine.fuzz_steer), and the sweep ranges (`sweeps`:
the real maximum and 2-10x past it)."""
from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

import yaml

from offload.engine import usage as U

ROOT = Path(__file__).resolve().parent.parent.parent
PROFILE = ROOT / "catalog" / "fuzz_profile.json"
APPS = ROOT / "corpus" / "apps"
WILD = ROOT / "data" / "bench" / "wild"
WILD_RUNS = ROOT / "results" / "wild" / "runs"
EXTRA_APPS = ("HipFT", "POT3D", "dwarf-p-cloudsc", "miniBUDE", "minisweep",
              "nwchem-tce-triples-kernels", "HPCTrainingExamples")
SRC_EXT = (".f90", ".F90", ".f", ".F", ".c", ".h", ".cpp", ".cc", ".hpp",
           ".cxx", ".fpp")
FAIL = ("wrong_answer", "crash", "run_error", "ice")
# application kernels a compiler names in a crash (data/bench/apps
# ground_truth.jsonl link locations)
APP_FAILING_PROCS = {
    "mfc": {"s_cbc": "CCE 20 device link (Infer address spaces) at "
                     "m_cbc.fpp:597",
            "s_compute_bubble_ee_source": "CCE 21 device link (AGPR-copy "
                                          "assertion) at m_bubbles_EE.fpp:186"},
}


def _read(p: Path) -> str:
    return p.read_text(errors="replace")


def manifest_files() -> dict:
    """app -> [(path, defines, model)] of the manifest programs (MFC from
    its generated sources)."""
    from offload.engine import apps as A
    out: dict = {}
    data = A.load()
    for app_id, app in data.items():
        files = out.setdefault(app_id, [])
        seen = set()
        for prog in app.programs:
            if prog.sources == ["@mfc"]:
                gpu = "mp" if prog.model == "omp" else "acc"
                # OpenMP: AFAR's build; OpenACC: the first gfx942 toolchain
                # whose family compiles it (CCE)
                from offload.engine.toolchains import GFX942_TOOLCHAINS, TOOLCHAINS
                tc = "afar" if gpu == "mp" else next(
                    t for t in GFX942_TOOLCHAINS
                    if TOOLCHAINS[t].family.supports_model("acc"))
                for d in A.mfc_dirs(tc, gpu):
                    st = A.mfc_staging(d)
                    if st is None:
                        continue
                    defs = list(prog.defines) + [
                        f"MFC_{A.MFC_COMPILER_ID['afar' if tc == 'afar' else 'cce']}",
                        "_OPENACC=201711" if gpu == "acc"
                        else "_OPENMP=201811"]
                    for f in sorted((st / "fypp" / "simulation").glob(
                            "*.f90")):
                        key = (str(f), prog.model)
                        if key not in seen:
                            seen.add(key)
                            files.append((f, defs, prog.model))
                    break
                continue
            base = APPS / app.dir
            for s in prog.sources:
                f = base / s
                key = (str(f), prog.model)
                if f.exists() and key not in seen:
                    seen.add(key)
                    defs = list(prog.defines) + (
                        ["_OPENACC=201711"] if prog.model == "acc"
                        else ["_OPENMP=201811"])
                    files.append((f, defs, prog.model))
    return out


def extra_files() -> dict:
    out = {}
    for name in EXTRA_APPS:
        base = APPS / name
        if not base.is_dir():
            continue
        files = []
        for f in sorted(base.rglob("*")):
            if not f.is_file() or f.suffix not in SRC_EXT:
                continue
            try:
                t = _read(f)
            except OSError:
                continue
            low = t.lower()
            if "$omp target" in low or "omp target" in low or \
                    "$acc" in low or "pragma acc" in low:
                files.append((f, ["_OPENMP=201811"], "omp"))
        out[name] = files
    return out


def wild_dev() -> list:
    split = yaml.safe_load(open(WILD / "split.yaml"))["cases"]
    cases = yaml.safe_load(open(WILD / "cases.yaml"))["cases"]
    return [c for c in cases if split.get(c["id"]) == "dev"]


def wild_dev_failing(dev: list) -> dict:
    """case id -> the failing outcomes (dev rows of results/wild/runs)."""
    ids = {c["id"] for c in dev}
    out: dict = {}
    for f in sorted(WILD_RUNS.glob("*.jsonl")):
        for line in open(f):
            r = json.loads(line)
            if r["id"] not in ids:
                continue
            if r["outcome"] in FAIL:
                out.setdefault(r["id"], set()).add(
                    f"{r['toolchain']}:{r['outcome']}")
    return {k: sorted(v) for k, v in out.items()}


def scan_set(files) -> list:
    scans = []
    for f, defs, model in files:
        try:
            s = U.scan(_read(f), str(f), defs)
        except Exception:      # an unreadable layout: skipped, counted
            continue
        if s is not None:
            scans.append(s)
    return scans


def generator_frequencies(n: int = 400) -> dict:
    """Region feature frequencies of fuzz-4s50 programs (no base groups),
    by the same extractor (the denominator of the steering weights)."""
    from offload.engine.fuzz import generate
    c, regions = Counter(), 0
    for seed in range(n):
        p = generate(seed, "fuzz-4s50")
        for fs in U.region_features(p.source):
            regions += 1
            c.update(fs)
    return {"programs": n, "regions": regions,
            "features": {k: round(v / max(1, regions), 4)
                         for k, v in sorted(c.items())}}


def enrichment(all_regs: list, fail_regs: list, top: int = 60) -> list:
    """Feature pairs more frequent in failing regions than in all regions
    (add-one smoothed ratio), with their counts: the boost list."""
    def pairs(rs):
        c = Counter()
        for r in rs:
            fs = sorted(f for f in r.features if not f.startswith(
                ("clause:map", "dir:end")))
            for i in range(len(fs)):
                for j in range(i + 1, len(fs)):
                    c[(fs[i], fs[j])] += 1
        return c
    a, f = pairs(all_regs), pairs(fail_regs)
    na, nf = max(1, len(all_regs)), max(1, len(fail_regs))
    rows = []
    for k, v in f.items():
        ratio = ((v + 1) / (nf + 2)) / ((a.get(k, 0) + 1) / (na + 2))
        if v >= 2 and ratio > 1.5:
            rows.append({"pair": list(k), "failing": v, "all": a.get(k, 0),
                         "ratio": round(ratio, 2)})
    rows.sort(key=lambda r: (-r["ratio"] * math.log(1 + r["failing"]),
                             r["pair"]))
    return rows[:top]


def build(gen_n: int = 400) -> dict:
    prof: dict = {"note": "Usage profile (offload.engine.fuzz_profile; "
                          "sources: data/bench/apps manifest, corpus/apps, "
                          "data/bench/wild dev half)", "codes": {}}
    all_regs, fail_regs = [], []
    combined = []
    for app, files in sorted(manifest_files().items()):
        scans = scan_set(files)
        combined += scans
        prof["codes"][app] = U.profile_files(scans)
        prof["codes"][app]["source"] = "data/bench/apps manifest"
        per_model = {}
        for m in ("omp", "acc"):
            per_model[m] = sum(len(sc.regions) for sc in scan_set(
                [f for f in files if f[2] == m]))
        # the most offload regions of one program (one build of a code)
        prof["codes"][app]["regions_per_program"] = max(per_model.values())
        regs = [r for s in scans for r in s.regions]
        all_regs += regs
        bad = APP_FAILING_PROCS.get(app, {})
        hits = [r for r in regs if r.proc.lower() in bad]
        fail_regs += hits
        if bad:
            prof["codes"][app]["failing_regions"] = {
                p: {"why": why, "regions": sum(1 for r in hits
                                               if r.proc.lower() == p)}
                for p, why in bad.items()}
    extra_scans = []
    for app, files in sorted(extra_files().items()):
        scans = scan_set(files)
        extra_scans += scans
        prof["codes"][app] = U.profile_files(scans)
        prof["codes"][app]["source"] = "corpus/apps (not in the manifest)"
        all_regs += [r for s in scans for r in s.regions]
    dev = wild_dev()
    failing = wild_dev_failing(dev)
    wild_scans = []
    for c in dev:
        if c.get("legality", {}).get("status") == "illegal" if isinstance(
                c.get("legality"), dict) else c.get("legality") == "illegal":
            continue
        f = WILD / c["file"]
        if not f.exists():
            continue
        s = U.scan(_read(f), str(f), ["_OPENMP=201811"])
        if s is None:
            continue
        wild_scans.append(s)
        all_regs += s.regions
        if c["id"] in failing:
            fail_regs += s.regions
    prof["codes"]["wild-dev"] = U.profile_files(wild_scans)
    prof["codes"]["wild-dev"]["source"] = "data/bench/wild dev half"
    prof["codes"]["wild-dev"]["failing_cases"] = len(failing)
    prof["combined"] = U.profile_files(combined + extra_scans + wild_scans)
    prof["manifest_combined"] = U.profile_files(combined)
    feats = Counter()
    for r in all_regs:
        feats.update(r.features)
    prof["real_frequencies"] = {
        "regions": len(all_regs),
        "features": {k: round(v / max(1, len(all_regs)), 4)
                     for k, v in sorted(feats.items())}}
    ff = Counter()
    for r in fail_regs:
        ff.update(r.features)
    prof["failing_frequencies"] = {
        "regions": len(fail_regs),
        "features": {k: round(v / max(1, len(fail_regs)), 4)
                     for k, v in sorted(ff.items())}}
    prof["boost_pairs"] = enrichment(all_regs, fail_regs)
    prof["generator_frequencies"] = generator_frequencies(gen_n)
    prof["maxima"] = maxima(prof)
    prof["sweeps"] = sweeps(prof["maxima"])
    return prof


MAX_KEYS = {
    # profile key -> (stress axis, how to read it)
    "private": ("list_length", "private"),
    "firstprivate": ("list_length", "firstprivate"),
    "lastprivate": ("list_length", "lastprivate"),
    "shared": ("list_length", "shared"),
    "map": ("list_length", "map"),
    "reduction": ("list_length", "reduction"),
    "depend": ("list_length", "depend"),
    "declare": ("module_device_vars", None),
    "clauses": ("clauses_per_directive", None),
    "contlines": ("directive_lines", None),
    "locals": ("device_routine_locals", None),
    "args": ("device_routine_args", None),
    "useonly": ("use_only_length", None),
    "capture": ("region_scalars_total", None),
    "dtnest": ("type_nesting_depth", None),
    "nest": ("region_loop_depth", None),
    "calls": ("device_call_depth", None),
    "tu": ("device_call_file_crossings", None),
    "kernels": ("regions_per_program", None),
}


def _max_of(p: dict, key: str, sub) -> int:
    v = p.get(key)
    if sub is not None:
        v = (v or {}).get(sub)
    if isinstance(v, dict):
        return int(v.get("max", 0))
    return int(v or 0)


def maxima(prof: dict) -> dict:
    """axis -> {"max": real maximum over all codes, "where": the code}."""
    out = {}
    for axis, (key, sub) in MAX_KEYS.items():
        best, where = 0, ""
        for code, p in prof["codes"].items():
            v = _max_of(p, key, sub)
            if v > best:
                best, where = v, code
        out[axis] = {"max": best, "where": where}
    out["kernels"]["note"] = ("offload regions of one program (one build "
                              "of a manifest code)")
    return out


BASE_SWEEP = (1, 8, 64, 256, 1024)


def sweeps(mx: dict) -> dict:
    """Size sweep per axis: 1, 8, 64, 256, 1024 within reach, plus the
    real maximum and 2x, 4x and 10x of it (cover the real maximum
    and go 2-10x beyond)."""
    out = {}
    for axis, m in mx.items():
        r = m["max"]
        pts = {x for x in BASE_SWEEP if x <= max(10 * r, 8)}
        if r:
            pts |= {r, 2 * r, 4 * r, 10 * r}
        out[axis] = sorted(pts)
    return out


def write(prof: dict, path: Path = PROFILE) -> None:
    path.write_text(json.dumps(prof, indent=1, sort_keys=True) + "\n")


def load(path: Path = PROFILE) -> dict:
    return json.loads(path.read_text())
