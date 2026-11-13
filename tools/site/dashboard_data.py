#!/usr/bin/env python3
"""Build the datasets of the dashboard artifact from the results.

    python3 -I tools/site/dashboard_data.py OUT_DIR

Writes into OUT_DIR: atoms.json, programs.json, runs.json, runs_x0.json (HSA_XNACK=1
and =0 runs), ompvv.json (Fortran and C rows, field `lang` "f90" | "c"), fuzz.json
(campaign class counts, minimized findings, feature rates against the control,
host-path failures, noncompliant programs, verdicts of c1 programs no host run
reproduced), fuzz_sources.json (generated, elided and minimized sources of the
fuzz programs those tables show), stress.json (offload.engine.stress_report), and the
OpenACC sets acc_atoms.json, acc_programs.json, acc_runs.json (rebuilt from
results/acc_support_table.csv, results/acc_matrix.jsonl and the generator).
It reads the git-ignored results/ files. The only thing it runs is the sequential
elision (gfortran, amdflang) of fuzz programs the host check did not already elide."""
import csv
import importlib.util
import json
import sys
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine.toolchains import GFX942_TOOLCHAINS, NVIDIA_TOOLCHAINS  # noqa: E402
from offload.engine.toolchains import TOOLCHAINS as _TC, registry as _registry  # noqa: E402
_R = _registry()
# the dataset column key of each toolchain in the merged result tables
# (catalog/toolchains.yaml merged_key: afar, cce, cce20, cce21, nvhpc, ...)
TKEY = {t: _TC[t].merged_key for t in _R.merged()}
# The twins (HSA_XNACK=0 only): one cell per compiler and GPU, key <key>
# and the twin's suffix (afar_g90, cce_g90, ..., afar_mi300x); the gfx90a
# ones also give the headline row's <key>_arch_class (a gfx90a versus MI300A
# copy-mode difference) and their runs go to the runs_g90 dataset (the
# dashboard page has no columns for the others' runs)
TWIN_KEYS = {t: [f"{k}{_R.twin_key(w)}" for w in _R.twins_of(t)] for t, k in TKEY.items()}
TKEY.update({w: f"{k}{_R.twin_key(w)}" for t, k in list(TKEY.items()) for w in _R.twins_of(t)})
# NVHPC 25.11 on wingtip (NVIDIA A100): cells nvhpc_x0 (separate
# memory, the headline) and nvhpc_x2 (managed memory), nvhpc_portable and
# nvhpc_mode_class (its own verdict: correct in both of its modes); its
# runs and omp_vv rows go to datasets of their own (runs_nvhpc,
# ompvv_nvhpc: the 8 MB dataset limit); `portable` stays the AMD list
NV_TCS = tuple(t for t in NVIDIA_TOOLCHAINS if t in TKEY)
NV_KEYS = tuple(f"{t}_x{x}" for t in NV_TCS for x in _TC[t].xnack_modes)
# Atoms and acc_atoms rows carry, per toolchain key, <key>_x1 and
# <key>_x0 (every program ran in both memory modes), <key>_portable (the
# support table's portable verdict: correct at HSA_XNACK=0 and 1) and
# <key>_mode_class (the class of a mode difference), and `portable` (the
# toolchains whose verdict is portable)
VERSION = {"50": "5.0", "52": "5.2", "60": "6.0"}
CLS_ORDER = ["agree", "wrong_code", "compile_reject", "ice", "run_error",
             "timeout"]
TC_NAME = {t: _R.label(t) for t in _R.merged()}


def status(label):
    """The dashboard status of a support-table label."""
    if label.startswith(("correct on device", "error termination",
                         "compile-time error termination as required")):
        return "ok"
    if label.startswith("rejected (not counted"):
        return "excluded"
    if label.startswith("rejected"):
        return "rejected"
    if label == "wrong answer (confirmed)":
        return "wrong"
    if label.startswith("wrong answer"):
        return "suspect"
    return "unverified"


def _portable(e, r, key):
    """The headline row's portable verdict and mode-difference
    class as <key>_portable and <key>_mode_class (the copy-mode row has
    none); its gfx90a difference class as <key>_arch_class."""
    if r["toolchain"] in NV_TCS:  # Its headline is separate
        if r["xnack"] == "0":
            e[f"{r['toolchain']}_portable"] = r.get("portable", "")
            e[f"{r['toolchain']}_mode_class"] = r.get("mode_class", "")
        return
    if r["xnack"] != "1":
        return
    e[f"{key}_portable"] = r.get("portable", "")
    e[f"{key}_mode_class"] = r.get("mode_class", "")
    e[f"{key}_arch_class"] = r.get("arch_class", "")


def cell_key(tc, x, tkey=TKEY):
    """The dataset key of a (toolchain, xnack) cell: <key>_x<x>, or the
    twin's key for a twin (HSA_XNACK=0 only: <key>_g90, <key>_mi300x)."""
    k = tkey.get(tc, tc)
    return k if tc in _R.twins() or tc.endswith("_g90") else f"{k}_x{x}"


def _portable_text(e, order):
    """The names of the toolchains ((key, name) in `order`) whose verdict
    is portable."""
    return ", ".join(name for k, name in order
                     if e.get(f"{k}_portable") == "portable")


def target_block(device, compiler):
    return f"--- target ---\ndevice: {device}\ncompiler: {compiler}\n"


def output(r):
    return (target_block(r.get("device", ""), r.get("compiler", ""))
            + f"--- stdout ---\n{r.get('stdout', '')}\n"
              f"--- stderr ---\n{r.get('stderr', '')}")


def load_jsonl(p):
    return [json.loads(l) for l in open(p) if l.strip()]


def load_expected():
    spec = importlib.util.spec_from_file_location(
        "expected_tool", ROOT / "tools" / "derive" / "expected.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def trust_for(mod):
    """program id -> (verdict, settled_by, why) for the catalog records."""
    out = {}
    exp = ROOT / "results" / "expected"
    # The C 5.0 slice's records (tools/campaigns/c_slices.py), when built
    for path in [exp / "catalog.jsonl"] + [p for p in [exp / "c50.jsonl"]
                                           if p.is_file()]:
        x0 = mod._x0(path)  # Copy-mode runs as additional evidence
        g90 = mod._g90(path)  # Gfx90a runs of the same compilers
        for rec in load_jsonl(path):
            ev, vd = mod.evaluate_both(rec, x0.get(rec["key"]),
                                       g90.get(rec["key"]))
            why = "; ".join(f"{e.tag}: {mod._cell(e)}" for e in ev)
            out[rec["program"]] = (vd.status, mod.settled_by(vd), why)
    return out


def map_caught():
    """(group, version, atom) -> the map-mutant audit's mode (both, x0_only, x1_only, neither; tests/data/map_audit_summary.json)."""
    p = ROOT / "tests" / "data" / "map_audit_summary.json"
    if not p.exists():
        return {}
    doc = json.load(open(p))
    return {(g, v, atom): e["caught"]
            for g, vs in doc["groups"].items() for v, atoms_ in vs.items()
            for atom, e in atoms_.items()}


def atoms(csv_path, lang, trust):
    mc = map_caught()
    by = OrderedDict()
    for r in csv.DictReader(open(csv_path)):
        if r["legal"] != "1":
            continue
        e = by.setdefault(r["program_id"], {
            "id": r["program_id"], "version": VERSION[r["version"]],
            "atom": r["atom"].removeprefix("omp."),
            "evidence": r["evidence"], "audit": r["audit"],
            "citation": r["citation"], "lang": lang,
            # Device | host+device (a pattern program, reported
            # apart from the atom's headline)
            "scope": r.get("scope") or "device"})
        k = cell_key(r["toolchain"], r["xnack"])
        e[k] = status(r["label"])
        e["note_" + k] = r["label"] + (" | " + r["reason"]
                                       if r["reason"] else "")
        _portable(e, r, TKEY[r["toolchain"]])
    out = []
    order = [(TKEY[t], TC_NAME[t]) for t in TCS]
    for e in by.values():
        for t in TCS:
            tc = TKEY[t]
            for k in (f"{tc}_x1", f"{tc}_x0", f"{tc}_g90", *TWIN_KEYS[t]):
                e.setdefault(k, "")
                e.setdefault(f"note_{k}", "")
            e.setdefault(f"{tc}_portable", "")
            e.setdefault(f"{tc}_mode_class", "")
            e.setdefault(f"{tc}_arch_class", "")
        _nv_defaults(e)
        e["portable"] = _portable_text(e, order)
        t = trust.get(e["id"])
        e["trust"], e["trust_by"], e["trust_why"] = t if t else ("", "", "")
        v = {"5.0": "50", "5.2": "52", "6.0": "60"}[e["version"]]
        e["map_caught"] = mc.get((lang, v, "omp." + e["atom"]), "")
        out.append(e)
    return out


def _nv_defaults(e):
    """The NVHPC fields of an atom row ("" when not run)."""
    for k in NV_KEYS:
        e.setdefault(k, "")
        e.setdefault(f"note_{k}", "")
    for t in NV_TCS:
        e.setdefault(f"{t}_portable", "")
        e.setdefault(f"{t}_mode_class", "")


def programs():
    """id -> source for every program of the matrices (both languages)."""
    from offload.engine.catalog import slice_atoms
    from offload.engine.run_matrix import matrix_programs
    out = {}
    for lang, versions in (("f90", (50, 52, 60)), ("c", (50, 52, 60))):
        atoms_ = set()
        for v in versions:
            atoms_ |= set(slice_atoms(v, lang=lang))
        for _v, p in matrix_programs(atoms_, versions, lang):
            out[p.id] = (lang, p.source)
    return out


def runs(path, lang):
    out = []
    for r in load_jsonl(path):
        out.append({"id": r["program_id"], "tc": TKEY[r["toolchain"]],
                    "x": str(r["xnack"]), "outcome": r["outcome"],
                    "flags": r.get("flags", ""), "output": output(r),
                    "lang": lang})
    return out


def split_runs(rows):
    """(HSA_XNACK=1 rows, HSA_XNACK=0 rows): the datasets runs
    and runs_x0 (one file of both modes passes the 8 MB dataset limit);
    And the gfx90a rows (tc <key>_g90), the dataset runs_g90."""
    g90 = [r for r in rows if str(r.get("tc", "")).endswith("_g90")]
    twin = set(TKEY[w] for w in _R.twins())
    rest = [r for r in rows if r.get("tc") not in twin
            and r.get("tc") not in NV_TCS]
    return ([r for r in rest if r["x"] == "1"],
            [r for r in rest if r["x"] == "0"], g90)


def nv_runs(rows):
    """The NVHPC rows (dataset runs_nvhpc)."""
    return [r for r in rows if r.get("tc") in NV_TCS]


# The omp_vv dataset stays under the 8 MB dataset limit: each
# stream of a cell's output keeps OMPVV_OUT_MAX // 2 characters (head and
# tail; the stored rows have it all)
OMPVV_OUT_MAX = 1600


def _clip(text: str, n: int) -> str:
    if len(text) <= n:
        return text
    h = n // 2
    return (text[:h] + f"\n[... {len(text) - n} characters omitted ...]\n"
            + text[-h:])


def ompvv(path, lang, nvhpc=False):
    """omp_vv rows of the AMD toolchains (`nvhpc`: of NVHPC only:
    the dataset ompvv_nvhpc)."""
    by = OrderedDict()
    for r in load_jsonl(path):
        if (r["toolchain"] in NV_TCS) != nvhpc:
            continue
        pid = r["path"].removeprefix("tests/")
        e = by.setdefault(pid, {"id": pid, "spec_dir": r["spec_dir"],
                                "lang": lang})
        k = cell_key(r["toolchain"], r["xnack"])
        e[k] = r["status"]
        e["note_" + k] = f"{r['stage']}: {r['reason']}"
        e["out_" + k] = output(dict(
            r, stdout=_clip(r.get("stdout", ""), OMPVV_OUT_MAX // 2),
            stderr=_clip(r.get("stderr", ""), OMPVV_OUT_MAX // 2)))
    out = []
    for e in by.values():
        src = ROOT / "corpus" / "omp_vv" / "tests" / e["id"]
        e["source"] = src.read_text(errors="replace") if src.exists() else ""
        keys = NV_KEYS if nvhpc else [
            f"{tc}_{m}" for tc in ("afar", "cce", "cce20", "cce21")
            for m in ("x1", "x0", "g90")]
        for k in keys:
            for p in ("", "note_", "out_"):
                e.setdefault(f"{p}{k}", "")
        out.append(e)
    return out


RUNS = [("c1", "none", "c1: 2400 programs, no base-language group (generator fuzz-1)"),
        ("b0", "none", "b0: control, 300 programs, no base-language group"),
        ("b1", "types", "b1: element types and kinds"),
        ("b2", "derived", "b2: derived types"),
        ("b3", "alloc", "b3: allocatable, pointer, sections, procedures"),
        ("b4", "declare", "b4: declare target, mapper, user reduction"),
        ("b5", "multitu", "b5: multiple translation units"),
        ("x0-types", "types", "x0-types: b1 seeds at HSA_XNACK=0 (THP on)"),
        ("x0-derived", "derived", "x0-derived: b2 seeds at HSA_XNACK=0 (THP on)"),
        ("x0-alloc", "alloc", "x0-alloc: b3 seeds at HSA_XNACK=0 (THP on)"),
        ("x0-declare", "declare", "x0-declare: b4 seeds at HSA_XNACK=0 (THP on)"),
        ("x0-multitu", "multitu", "x0-multitu: b5 seeds at HSA_XNACK=0 (THP on)"),
        # Every base group combined (merged from s1-00 .. s1-19
        # and s1x0-00 .. s1x0-04)
        ("s1", "all", "s1: 10000 programs, all five base groups combined "
         "(HSA_XNACK=1)"),
        ("s1x0", "all", "s1x0: s1 seeds 1-2500 at HSA_XNACK=0"),
        # Generator fuzz-4s50 (the 5.0/5.1 spellings NVHPC
        # accepts), the AMD toolchains at HSA_XNACK=0 and NVHPC 25.11 and
        # 26.9 in separate memory, the same seeds
        ("n0x0", "none", "n0x0: 1000 programs in 5.0/5.1 spellings, no "
         "base-language group (AMD at HSA_XNACK=0, NVHPC separate memory)"),
        ("n1x0", "all", "n1x0: 1000 programs in 5.0/5.1 spellings, all five "
         "base groups (AMD at HSA_XNACK=0, NVHPC separate memory)")]
# the campaigns that exist (a clone without the runs has none of
# n0x0 / n1x0)
ALL_RUNS = list(RUNS)
RUNS = [r for r in RUNS if r[0] not in ("n0x0", "n1x0") or (
    ROOT / "results" / "fuzz" / r[0] / "summary.json").is_file()]
TCS = GFX942_TOOLCHAINS
FAIL = ("wrong_code", "run_error", "timeout")


def _rates(cl):
    """fail % among the programs a toolchain compiled (judged minus
    compile_reject and ice), as in data/reports/fuzz-base-language.md."""
    judged = sum(cl.values())
    compiled = judged - cl.get("compile_reject", 0) - cl.get("ice", 0)
    fails = sum(cl.get(c, 0) for c in FAIL)
    return compiled, fails, (round(100.0 * fails / compiled, 1)
                             if compiled >= 10 else "")


def _control():
    ctl = json.load(open(ROOT / "results" / "fuzz" / "b0" / "summary.json"))
    return {tc: _rates(ctl["classes"].get(tc, {}))[2] for tc in TCS}


def fuzz(mod):
    rows = []
    ctl = _control()
    for run, group, label in RUNS:
        d = ROOT / "results" / "fuzz" / run
        summ = json.load(open(d / "summary.json"))
        for tc, cl in summ["classes"].items():
            for c in CLS_ORDER:
                if cl.get(c):
                    rows.append({"kind": "class", "id": f"{run}-{tc}-{c}",
                                 "run": run, "group": group, "tc": tc,
                                 "tc_name": TC_NAME[tc], "cls": c,
                                 "n": cl[c]})
        rows.append({"kind": "run", "id": run, "run": run, "group": group,
                     "label": label, "judged": summ["judged"],
                     "generated": summ["generated"],
                     "noncompliant": len(summ.get("noncompliant", []))})
        # Host runs are references only; a host-path failure is
        # kept as data but is not an offload finding (appendix)
        for tc, e in summ.get("host_path_failure", {}).items():
            rows.append({"kind": "host_path_failure", "id": f"{run}-{tc}",
                         "run": run, "group": group, "tc": tc,
                         "tc_name": TC_NAME[tc], "programs": e["programs"],
                         "seeds": ", ".join(map(str, e["seeds"])),
                         "appendix": "host reference run, not an offload "
                                     "finding (out of scope)"})
        for nc in summ.get("noncompliant", []):
            host = ", ".join(f"{TC_NAME[t]}: {v}"
                             for t, v in nc["host"].items())
            rows.append({"kind": "noncompliant", "id": f"{run}-{nc['seed']}",
                         "run": run, "group": group, "seed": nc["seed"],
                         "model": nc["expected"], "host": host,
                         "elision": nc["elision"],
                         "classes": ", ".join(
                             f"{TC_NAME[t]}: {c}"
                             for t, c in nc["classes"].items())})
        # NVHPC's rates where the run has it (no b0 control)
        tcs = TCS + tuple(t for t in NV_TCS if t in summ["classes"])
        if run != "c1":
            cmp_ = {"kind": "stage", "id": f"{run} {group}", "run": run,
                    "group": group, "feature": "(all programs of the run)",
                    "programs": summ["judged"]}
            for tc in tcs:
                n, f, rate = _rates(summ["classes"].get(tc, {}))
                cmp_[tc + "_n"], cmp_[tc + "_fail"] = n, f
                cmp_[tc + "_rate"], cmp_[tc + "_ctl"] = rate, ctl.get(tc, "")
            rows.append(cmp_)
        for feat, e in sorted(summ.get("base_features", {}).items()):
            r = {"kind": "base_feature",
                 "id": f"{run} {feat.removeprefix('base:')}", "run": run,
                 "group": group, "feature": feat.removeprefix("base:"),
                 "programs": e["programs"]}
            for tc in tcs:
                cl = e["classes"].get(tc, {})
                n, f, rate = _rates(cl)
                r[tc + "_n"], r[tc + "_fail"] = n, f
                r[tc + "_rate"], r[tc + "_ctl"] = rate, ctl.get(tc, "")
                r[tc + "_counts"] = ", ".join(
                    f"{c} {cl[c]}" for c in CLS_ORDER if cl.get(c))
            rows.append(r)
        mf = d / "minimized.json"
        for m in json.load(open(mf)) if mf.exists() else []:
            f = ROOT / m["file"] if m.get("file") else None
            rows.append({
                "kind": "finding", "run": run, "group": group,
                "id": f"{run}-{m['seed']}-{m['toolchain']}",
                "seed": m["seed"], "tc": m["toolchain"],
                "tc_name": TC_NAME[m["toolchain"]], "fkind": m["kind"],
                "status": m["status"], "why": m.get("why", ""),
                "signature": m["signature"][:240],
                "expected": m["expected"], "observed": m["observed"][:400],
                "also": ", ".join(TC_NAME.get(t, t)
                                  for t in m.get("also_fails_on", [])),
                "lines_before": m.get("lines_before", ""),
                "lines_after": m.get("lines_after", ""),
                "file": m.get("file", ""),
                "source": f.read_text() if f and f.exists() else ""})
    # c1 programs no host run reproduced (sources, rule)
    now = set(mod.unresolved_seeds("c1"))
    valid = mod.host_validity("c1")
    c1_x0 = mod._x0(ROOT / "results" / "expected" / "c1.jsonl")
    for rec in load_jsonl(ROOT / "results" / "expected" / "c1.jsonl"):
        if int(rec["seed"]) not in now:
            continue
        ev, vd = mod.evaluate_both(rec, c1_x0.get(rec["key"]))
        cells = {e.tag: mod._cell(e) for e in ev}
        v = valid.get(int(rec["seed"]))
        rows.append({
            "kind": "trust", "id": f"seed {rec['seed']}",
            "seed": int(rec["seed"]), "verdict": vd.status,
            "validity": v["validity"] if v else "",
            "host_path": mod._validity_cell(v),
            "settled_by": mod.settled_by(vd),
            "wrong_on": ", ".join(TC_NAME.get(t, t) for t in
                                  mod.wrong_toolchains(rec, vd)),
            "model": cells["model"], "elision": cells["elision"],
            "metamorphic": cells["metamorphic"], "probe": cells["probe"],
            "consensus": cells["consensus_only"]})
    return rows


def _program_pairs(rows, mod):
    """(run, seed) of every fuzz program a fuzz table shows: findings,
    host-path failures, noncompliant programs, the c1 verdicts."""
    pairs = set()
    for r in rows:
        if r["kind"] in ("finding", "noncompliant"):
            pairs.add((r["run"], int(r["seed"])))
        elif r["kind"] == "host_path_failure":
            pairs |= {(r["run"], int(s)) for s in r["seeds"].split(", ") if s}
        elif r["kind"] == "trust":
            pairs.add(("c1", int(r["seed"])))
    return pairs


def _elision_cells(source, rec, cache):
    """(checksum or None, text): the host check's stored elision result,
    else the one fuzz_sources ran (`cache`: source -> elision_value)."""
    v = (rec or {}).get("elision")
    if v is None:
        v = cache[source]
        v = f"checksum={v}" if isinstance(v, int) else v
    if v.startswith("checksum="):
        return int(v.split("=", 1)[1]), v
    return None, v


def fuzz_sources(rows, mod):
    """One row per fuzz program the fuzz tables show (id "<run>-<seed>"):
    the generated source (regenerated from the campaign's generator
    version, base groups and seed, checked against the stored model value
    and line count), the program sequential elision builds
    (offload.engine.expected.elided_source) with its result or why it does
    not apply, the per-toolchain outcomes, the host check and the
    minimized reproducers; plus one row "omp_lib", the sequential omp_lib
    the elided build links."""
    from concurrent.futures import ThreadPoolExecutor
    from offload.engine import expected as E
    from offload.engine import fuzz as FZ
    from offload.engine import fuzz_exec
    pairs = sorted(_program_pairs(rows, mod))
    progs, hosts, mins, base = {}, {}, {}, {}
    for run in {r for r, _ in pairs}:
        d = ROOT / "results" / "fuzz" / run
        for p in load_jsonl(d / "programs.jsonl"):
            progs[(run, p["seed"])] = p
        if (d / "hostcheck.jsonl").exists():
            for h in load_jsonl(d / "hostcheck.jsonl"):
                hosts[(run, h["seed"])] = h
        if (d / "minimized.json").exists():
            for m in json.load(open(d / "minimized.json")):
                f = ROOT / m["file"] if m.get("file") else None
                mins.setdefault((run, m["seed"]), []).append({
                    "tc": TC_NAME[m["toolchain"]], "status": m["status"],
                    "file": m.get("file", ""),
                    "source": f.read_text() if f and f.exists() else ""})
        sessions = json.load(open(d / "meta.json"))["sessions"]
        base[run] = tuple(sessions[-1].get("base") or ())
    gen = {}
    for run, seed in pairs:
        p = progs[(run, seed)]
        g = FZ.generate(seed, p["gen_version"], base[run])
        if g.expected != p["expected"] or g.source.count("\n") != p["lines"]:
            raise SystemExit(f"{run} seed {seed}: the generator no longer "
                             "gives the campaign's program")
        gen[(run, seed)] = g
    todo = [g.source for k, g in gen.items()
            if (hosts.get(k) or {}).get("elision") is None]
    with ThreadPoolExecutor(8) as ex:
        cache = dict(zip(todo, ex.map(fuzz_exec.elision_value, todo)))
    out = [{"id": "omp_lib", "kind": "omp_lib",
            "source": E.ELISION_OMP_LIB}]
    for run, seed in pairs:
        p, g, h = progs[(run, seed)], gen[(run, seed)], hosts.get((run, seed))
        el_v, el_txt = _elision_cells(g.source, h, cache)
        res = []
        for tc in TCS + NV_TCS:  # NVHPC in the n campaigns
            t = p["results"].get(tc)
            if not t:
                continue
            res.append({"tc": TC_NAME[tc], "cls": t["cls"],
                        "checksum": t.get("checksum"),
                        "host": t.get("host_checksum"),
                        "reason": (t.get("reason") or "")[:300]})
        host = ""
        if h:
            host = "; ".join(
                f"{TC_NAME[t]}: " + (f"checksum={v['checksum']}"
                                     if v.get("checksum") is not None
                                     else (v.get("build") or "no value"))
                for t, v in h["host"].items())
        out.append({
            "id": f"{run}-{seed}", "kind": "program", "run": run,
            "seed": seed, "gen_version": p["gen_version"],
            "base": ", ".join(base[run]) or "none", "model": p["expected"],
            "lines": p["lines"], "source": g.source,
            "elided": E.elided_source(g.source),
            "elision_value": el_v, "elision": el_txt,
            "elision_agrees": el_v == p["expected"] if el_v is not None
            else None,
            "validity": (h or {}).get("validity", ""),
            "host": host, "results": res,
            "minimized": mins.get((run, seed), [])})
    return out


def acc_atoms(csv_path, lang="f90"):
    """The OpenACC atom rows (CCE 19/20/21 per memory mode);
    `lang` "c" for the OpenACC C slice (NVHPC cells only)."""
    mc = map_caught()
    by = OrderedDict()
    for r in csv.DictReader(open(csv_path)):
        if r["legal"] != "1":
            continue
        e = by.setdefault(r["program_id"], {
            "id": r["program_id"], "atom": r["atom"].removeprefix("acc."),
            "evidence": r["evidence"], "audit": r["audit"],
            "citation": r["citation"], "lang": lang})
        k = cell_key(r["toolchain"], r["xnack"], {})
        e[k] = status(r["label"])
        e["note_" + k] = r["label"] + (" | " + r["reason"]
                                       if r["reason"] else "")
        _portable(e, r, r["toolchain"])
    # the gfx942 toolchains whose family compiles OpenACC (CCE)
    acc_tcs = [t for t in TCS if _TC[t].family.supports_model("acc")]
    order = [(t, TC_NAME[t]) for t in acc_tcs]
    for e in by.values():
        for tc in acc_tcs:
            for k in (f"{tc}_x1", f"{tc}_x0", *_R.twins_of(tc)):
                e.setdefault(k, "")
                e.setdefault(f"note_{k}", "")
            e.setdefault(f"{tc}_portable", "")
            e.setdefault(f"{tc}_mode_class", "")
            e.setdefault(f"{tc}_arch_class", "")
        _nv_defaults(e)
        e["portable"] = _portable_text(e, order)
        e["map_caught"] = mc.get(("acc", "34", "acc." + e["atom"]), "")
    return list(by.values())


def widened(csv_path, trust):
    """(atoms rows, acc_atoms rows) of the widened catalog
    (data/reports/widen_support_table.csv): the same row builders, one
    language and model at a time (from the program id: omp52-w-,
    omp52-c-w-, acc34-w-), each row marked `widened`."""
    import tempfile
    rows = list(csv.DictReader(open(csv_path)))
    head = list(rows[0].keys()) if rows else []
    out_a, out_acc = [], []
    with tempfile.TemporaryDirectory(prefix="dash_widen_") as d:
        for key, pred in (("f90", lambda i: i.startswith("omp52-w-")),
                          ("c", lambda i: i.startswith("omp52-c-w-")),
                          ("acc", lambda i: i.startswith("acc34-w-"))):
            sel = [r for r in rows if pred(r["program_id"])]
            if not sel:
                continue
            path = Path(d) / f"{key}.csv"
            with open(path, "w", newline="") as fh:
                w = csv.DictWriter(fh, head)
                w.writeheader()
                w.writerows(sel)
            got = acc_atoms(path) if key == "acc" else atoms(path, key,
                                                             trust)
            for e in got:
                e["widened"] = True
            (out_acc if key == "acc" else out_a).extend(got)
    return out_a, out_acc


def acc_programs():
    from offload.engine.acc_c_gen import all_acc_c_programs
    from offload.engine.catalog import slice_atoms
    from offload.engine.gen import generate
    return [{"id": p.id, "source": p.source, "lang": "f90"}
            for p in generate(slice_atoms(34), 34)] + [
        {"id": p.id, "source": p.source, "lang": "c"}  
        for p in all_acc_c_programs()]


def acc_runs(path):
    return [{"id": r["program_id"], "tc": r["toolchain"],
             "x": str(r["xnack"]), "outcome": r["outcome"],
             "flags": r.get("flags", ""), "output": output(r)}
            for r in load_jsonl(path)]


def stress():
    """The stress campaigns (offload.engine.stress_report over
    STRESS_RUNS): class counts per toolchain and mode, the distinct
    findings, the size break points against the real maxima of the usage
    profile, compile-time and memory scaling, portability outcomes, the
    scalar routes' undefined observations and the equal-budget arms."""
    from offload.engine import stress_report as SR
    runs = [r for r in SR.STRESS_RUNS if (SR.OUT / r).is_dir()]
    if not runs:
        return {}
    progs, rows = SR.load(runs)
    prof = ROOT / "catalog" / "fuzz_profile.json"
    maxima = json.load(open(prof))["maxima"] if prof.is_file() else {}
    classes = []
    for r in rows:
        classes.append((r["toolchain"], r["mode"], r.get("lang", "f90"),
                        r.get("model", "omp"), r["variant"], r["cls"]))
    from collections import Counter
    cc = Counter(classes)
    fnd = SR.findings(progs, rows)
    return {
        "runs": runs, "programs": len(progs), "rows": len(rows),
        "classes": [{"tc": a, "mode": b, "lang": c, "model": d,
                     "variant": e, "cls": f, "n": n}
                    for (a, b, c, d, e, f), n in sorted(cc.items(),
                                                         key=str)],
        "findings": [dict(signature=k, **{x: (list(y) if isinstance(
            y, tuple) else y) for x, y in v.items()})
            for k, v in sorted(fnd.items())],
        "breakpoints": SR.breakpoints(progs, rows, maxima),
        "scaling": SR.scaling(rows),
        "portability": SR.portability(progs, rows),
        "observations": SR.observations(rows),
        "arms": [SR.budget(a) for a in SR.ARM_RUNS
                 if (SR.OUT / a).is_dir()],
        "maxima": maxima}


def main(argv):
    out = Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    mod = load_expected()
    trust = trust_for(mod)
    res = ROOT / "results"
    a = (atoms(res / "support_table.csv", "f90", trust)
         + atoms(res / "support_table_c.csv", "c", trust))
    src = programs()
    p = [{"id": i, "lang": l, "source": s} for i, (l, s) in src.items()]
    r = runs(res / "matrix.jsonl", "f90") + runs(res / "matrix_c.jsonl", "c")
    wm0 = res / "widen" / "matrix.jsonl"
    if wm0.is_file():  # The widened catalog's OpenMP runs
        r += [dict(x, lang="c" if x["id"].startswith("omp52-c-") else "f90")
              for x in runs(wm0, "f90") if x["id"].startswith("omp52-")]
    v = ompvv(res / "baseline.jsonl", "f90") + ompvv(res / "baseline_c.jsonl",
                                                     "c")
    vn = (ompvv(res / "baseline.jsonl", "f90", nvhpc=True)
          + ompvv(res / "baseline_c.jsonl", "c", nvhpc=True))
    f = fuzz(mod)
    fs = fuzz_sources(f, mod)
    # The widened catalog's rows, programs and runs
    wa, wacc = ([], [])
    wcsv = ROOT / "data" / "reports" / "widen_support_table.csv"
    if wcsv.is_file():
        wa, wacc = widened(wcsv, trust)
        a += wa
    from offload.engine import widen as W
    p += [{"id": w.id, "lang": "c" if w.program.lang == "c" else "f90",
           "source": w.program.source} for w in W.all_wide()
          if w.program.model == "omp"]
    wm = res / "widen" / "matrix.jsonl"
    wrows = load_jsonl(wm) if wm.is_file() else []
    # The OpenACC C slice (NVHPC), when its table exists
    acsv = res / "acc_support_table_c.csv"
    accc = acc_atoms(acsv, "c") if acsv.is_file() else []
    acm = res / "acc_matrix_c.jsonl"
    acc = (("acc_atoms", acc_atoms(res / "acc_support_table.csv") + wacc
            + accc),
           ("acc_programs", acc_programs() + [
               {"id": w.id, "source": w.program.source, "lang": "f90"}
               for w in W.all_wide() if w.program.model == "acc"]),
           ("acc_runs", acc_runs(res / "acc_matrix.jsonl")
            + (acc_runs(acm) if acm.is_file() else []) + [
               {"id": x["program_id"], "tc": x["toolchain"],
                "x": str(x["xnack"]), "outcome": x["outcome"],
                "flags": x.get("flags", ""), "output": output(x)}
               for x in wrows if x["program_id"].startswith("acc34-")]))
    rn = nv_runs(r)
    r, r0, rg = split_runs(r)
    for name, rows in (("atoms", a), ("programs", p), ("runs", r),
                       ("runs_x0", r0), ("runs_g90", rg),
                       ("runs_nvhpc", rn), ("ompvv", v),
                       ("ompvv_nvhpc", vn), ("fuzz", f),
                       ("fuzz_sources", fs), ("stress", stress())) + acc:
        (out / f"{name}.json").write_text(json.dumps(rows))
        print(name, len(rows))


if __name__ == "__main__":
    main(sys.argv)
