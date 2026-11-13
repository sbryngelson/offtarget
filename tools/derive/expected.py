#!/usr/bin/env python3
"""Independent expected-behaviour sources for fuzz and catalog programs
(method: docs/tooling/expected-behaviour.md; code: offload/engine/expected.py and
offload/engine/transforms.py). Run from anywhere:

    python3 -I tools/derive/expected.py fuzz --run c1 --workers 6
    python3 -I tools/derive/expected.py catalog --workers 6
    python3 -I tools/derive/expected.py report
    python3 -I tools/derive/expected.py xnack0-command

``fuzz`` runs the programs of a campaign whose model value no host run
reproduced on afar, cce19, cce20 and cce21 (-O2, HSA_XNACK=1) and writes
results/expected/<run>.jsonl. ``catalog`` does the same for programs behind
support-table claim mismatches (results/expected/catalog.jsonl). ``report``
writes data/reports/expected-sources.md. ``xnack0-command`` prints the flux
command for copy-mode runs (``--xnack 0``, output ``<out>.xnack0.jsonl``).
"""
import argparse
import dataclasses
import json
import multiprocessing as mp
import re
import sys
import time
from collections import Counter
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine import expected as E  # noqa: E402
from offload.engine import transforms as T  # noqa: E402

OUT = ROOT / "results" / "expected"
REPORT = ROOT / "data" / "reports" / "expected-sources.md"
FUZZ_TCS = ("afar", "cce19", "cce20", "cce21")
CAT_TCS = ("afar", "cce19")
AUDIT_OPEN = ("unaudited_no_passing_original", "weak", "unknown",
              "unverified_oracle_not_written")


# --- selection ----------------------------------------------------------------------

def unresolved_seeds(run: str, base: Path | None = None) -> list[int]:
    """Seeds of a campaign whose host reference run failed or disagreed
    with the model (host_ref_failed or host_mismatch) and where no
    toolchain's host run printed the model value (the campaign's host
    data, overridden by its hostcheck.jsonl rechecks)."""
    from offload.engine.fuzz_exec import load
    progs, _ = load((base or ROOT / "results" / "fuzz") / run)
    return [p.seed for p in progs
            if (p.host_mismatch or p.host_ref_failed) and not any(
                r.host_checksum == p.expected for r in p.results.values())]


def host_validity(run: str, base: Path | None = None) -> dict:
    """seed -> the maintainer's host-path verdict (offload.engine.fuzz_exec.
    host_verdict: validity, witnesses, host_path_failure) of every
    program of the campaign whose host reference failed or disagreed."""
    from offload.engine.fuzz_exec import load
    progs, _ = load((base or ROOT / "results" / "fuzz") / run)
    return {p.seed: {"validity": p.validity, "witnesses": p.host_witnesses,
                     "host_path_failure": p.host_path_failure}
            for p in progs if p.host_mismatch or p.host_ref_failed}


def _validity_cell(v: dict | None) -> str:
    if not v:
        return "—"
    if v["validity"] == "valid":
        parts = []
        hosts = [w for w in v["witnesses"] if w != "elision"]
        if hosts:
            parts.append(f"host witness: {', '.join(hosts)}")
        if v["host_path_failure"]:
            parts.append("host_path_failure: "
                         + ", ".join(v["host_path_failure"]))
        return "valid" + (f" ({'; '.join(parts)})" if parts else "")
    return v["validity"]


def catalog_set(table=None, mism=None, summ=None
                ) -> dict[tuple[int, str], dict]:
    """(version, program id) -> why it is in the set: the support table's
    claim mismatches and the audit's open dispositions (AUDIT_OPEN).
    Device programs only: a host+device program is no claim's
    evidence and has no audit disposition. `table`, `mism`, `summ`
    default to the committed matrix, claims and audit summary."""
    from offload.engine import report
    if table is None:
        table = report.build_table(report.MATRIX, audit=report.AUDIT)
    if mism is None:
        mism = report.compare_claims(table, report.CLAIMS)
    out: dict = {}
    for m in mism:
        rows = [r for r in table if r.atom == m.atom and r.legal and
                r.scope == "device" and
                r.version == m.version and r.toolchain == m.toolchain]
        for pid in sorted({r.program_id for r in rows}):
            out.setdefault((m.version, pid), {"atom": m.atom,
                                              "mismatches": [],
                                              "audit": ""})
            out[(m.version, pid)]["mismatches"].append(
                {"toolchain": m.toolchain, "claimed": m.claimed,
                 "measured": m.measured, "reason": m.reason})
    if summ is None:
        summ = json.loads(report.AUDIT.read_text())
    for v, ents in summ["versions"].items():
        for atom, e in ents.items():
            key = (int(v), e["program"])
            if e.get("disposition") in AUDIT_OPEN or key in out:
                out.setdefault(key, {"atom": atom, "mismatches": [],
                                     "audit": ""})
                out[key]["audit"] = e.get("disposition", "")
    return out


# --- jobs ---------------------------------------------------------------------------

def _legality(job):
    key, name, source, version, kind = job
    return key, name, E.variant_legality(source, version, kind)


def _run(job):
    key, name, source, version, kind, tc, xnack = job
    t0 = time.time()
    r = E.run_on(tc, source, version, kind, name, xnack)
    return key, r.to_dict(), round(time.time() - t0, 1)


def _variants(source: str, version: int, kind: str) -> dict:
    out = {}
    for name, v in T.variants(source, version).items():
        out[name] = v
    try:
        out["probe"] = T.presence_probe(source, version)
    except (T.NotApplicable, Exception) as e:      # noqa: BLE001
        out["probe"] = T.NotApplicable(f"probe: {e}")
    return out


def collect(items: list[dict], tcs, workers: int, xnack: int,
            log=print) -> list[dict]:
    """items: {key, source, version, kind, model} -> records with the
    elision, the variants' legality and every run."""
    pool = mp.Pool(workers)
    variants, legal_jobs = {}, []
    for it in items:
        vs = _variants(it["source"], it["version"], it["kind"])
        variants[it["key"]] = vs
        for name, src in vs.items():
            if isinstance(src, str):
                legal_jobs.append((it["key"], name, src, it["version"],
                                   it["kind"]))
    legality = {}
    for key, name, err in pool.imap_unordered(_legality, legal_jobs):
        legality[(key, name)] = err
    log(f"legality: {len(legal_jobs)} variants, "
        f"{sum(1 for e in legality.values() if e)} illegal")
    run_jobs = []
    for it in items:
        key = it["key"]
        run_jobs += [(key, "original", it["source"], it["version"],
                      it["kind"], tc, xnack) for tc in tcs]
        for name, src in variants[key].items():
            if isinstance(src, str) and legality[(key, name)] is None:
                run_jobs += [(key, name, src, it["version"], it["kind"], tc,
                              xnack) for tc in tcs]
    runs: dict = {}
    t0 = time.time()
    for n, (key, r, secs) in enumerate(pool.imap_unordered(_run, run_jobs),
                                       1):
        runs.setdefault(key, []).append(r)
        if n % 25 == 0 or n == len(run_jobs):
            log(f"runs {n}/{len(run_jobs)} ({time.time() - t0:.0f} s)")
    pool.close()
    pool.join()
    out = []
    for it in items:
        key = it["key"]
        el = E.elision_evidence(it["source"], it["version"]) \
            if xnack == 1 else None
        var_status = {}
        for name, src in variants[key].items():
            if isinstance(src, T.NotApplicable):
                var_status[name] = f"n/a: {src}"
            elif legality[(key, name)]:
                var_status[name] = f"illegal: {legality[(key, name)]}"
            else:
                var_status[name] = "ok"
        rec = {k: v for k, v in it.items() if k != "source"}
        rec.update(elision=el.to_dict() if el else None,
                   variants=var_status,
                   runs=sorted(runs.get(key, []),
                               key=lambda r: (r["variant"], r["toolchain"])),
                   xnack=xnack)
        out.append(rec)
    return out


def model_partners(rec: dict) -> tuple:
    """A catalog program's model is its own oracle: it counts only next to
    elision (offload.engine.expected.CATALOG_MODEL_PARTNERS)."""
    return E.CATALOG_MODEL_PARTNERS if rec.get("kind") == "catalog" \
        else E.MODEL_PARTNERS


TRIAGE = ROOT / "catalog" / "expected_triage.yaml"
# The disposition of a disputed verdict (data/reports/
# triage-2026-10.md)
TRIAGE_DISPOSITIONS = {
    "program_fixed": "the program was nonconforming; fixed, rerun and "
                     "re-audited",
    "oracle_fixed": "the check was wrong; fixed, rerun and re-audited",
    "compiler_wrong": "the toolchains' value is wrong (a finding with a "
                      "minimal reproducer): their runs are withdrawn as "
                      "witnesses",
    "implementation_defined": "the spec leaves the behaviour unspecified "
                              "or implementation defined (quoted): not a "
                              "support verdict",
}


@lru_cache(maxsize=None)
def _triage_cached() -> dict:
    import yaml
    if not TRIAGE.is_file():
        return {}
    out = {}
    for t in yaml.safe_load(TRIAGE.read_text())["entries"]:
        out[(int(t["version"]), t["program"])] = t
    return out


def load_triage() -> dict:
    """(version, program) -> triage entry (catalog/expected_triage.yaml)."""
    return dict(_triage_cached())


def _derivation_of(rec: dict):
    src = source_of(rec) if rec.get("kind") == "catalog" and \
        "version" in rec and "program" in rec else None
    return E.derivation_evidence(src) if src else None


@lru_cache(maxsize=None)
def _matrix_correct() -> frozenset:
    """(version, program id, toolchain, xnack) of every correct_on_device
    row in the matrix files (any compiler, memory mode, GPU)."""
    out = set()
    for f in (ROOT / "results" / "matrix.jsonl",
              ROOT / "results" / "matrix_c.jsonl"):
        if not f.is_file():
            continue
        for ln in f.read_text().splitlines():
            if '"correct_on_device"' in ln:
                r = json.loads(ln)
                if r["outcome"] == "correct_on_device":
                    out.add((r["version"], r["program_id"], r["toolchain"],
                             r["xnack"]))
    return frozenset(out)


def _witnesses(rows) -> frozenset:
    """The rows that can witness: not a support-table cell only (GCC, under test only; the
    MI300X and MI350X twins: the evidence machines are MI300A, MI250X and the A100)."""
    from offload.engine.toolchains import registry
    table_only = registry().table_only()
    return frozenset(h for h in rows if h[2] not in table_only)


@lru_cache(maxsize=None)
def _matrix_witnesses() -> frozenset:
    return _witnesses(_matrix_correct())


def matrix_witness(rec: dict, xnack=None, withdraw=(), have=None) -> bool:
    """The catalog program or its C port ran correct
    on the device (results/matrix*.jsonl). Fix: in memory mode
    `xnack` only (None: any; the gfx90a rows are HSA_XNACK=0), and not on
    a withdrawn compiler (its gfx942 name covers its gfx90a twin). A
    correct_on_device row prints check=pass (or the probe's required
    termination), which is the value a trusted catalog verdict agrees on."""
    from offload.engine.toolchains import base_name
    v, pid = rec.get("version"), rec.get("program", "")
    port = pid.replace(f"omp{v}-", f"omp{v}-c-", 1)
    have = _matrix_witnesses() if have is None else _witnesses(have)
    # the withdrawal is about the catalog (Fortran) program: its findings
    # name the Fortran compilers (amdflang, ftn); the C port is built by
    # another front end (amdclang, craycc) and is not withdrawn
    return any(rv == v and (xnack is None or x == xnack) and (
        p == port or (p == pid and base_name(t) not in withdraw))
        for rv, p, t, x in have)


@lru_cache(maxsize=None)
def _copy_dependent(version: int, program: str) -> bool:
    src = _catalog_sources(version).get(program)
    return src is not None and not E.copy_independent(src, version).ok


def evaluate(rec: dict, mode: dict | None = None, triage: dict | None = None,
             derivation=None, matrix_ok=None,
             copy_dependent=None) -> tuple[list, object]:
    """Evidence and verdict of a stored record: its own (HSA_XNACK=1)
    runs, or with `mode` (a record of the same program in another memory
    mode) that mode's runs and variants with the record's model and
    elision (elision applies only to copy-independent programs, so its
    value holds in both modes). A catalog program's hand
    derivation (its header) is one more source, and its triage entry
    (catalog/expected_triage.yaml, or `triage`) withdraws the runs of the
    toolchains a finding shows wrong, or makes the verdict
    implementation_defined."""
    src = mode if mode is not None else rec
    if triage is None and rec.get("kind") == "catalog":
        triage = load_triage().get((rec.get("version"), rec.get("program")))
    if derivation is None:
        derivation = _derivation_of(rec)
    gone = set((triage or {}).get("withdraw") or ())
    runs = [E.ToolRun(**r) for r in src["runs"]
            if r["toolchain"] not in gone]
    model = E.model_evidence(rec["model"], rec.get("model_detail", ""))
    el = E.Evidence.from_dict(rec["elision"]) if rec.get("elision") else \
        E.Evidence("elision", "no_value", detail="not run")
    probe_na = None
    if not src["variants"].get("probe", "").startswith("ok"):
        probe_na = src["variants"].get("probe", "no probe")
    ev, vd = E.assess(model, el, runs, probe_na, model_partners(rec),
                      derivation)
    if vd.status == "trusted" and rec.get("kind") == "catalog":
        # A positive executed witness is required
        # for a copy-dependent program, from the verdict's
        # memory mode: `mode` is the copy-mode record, else HSA_XNACK=1
        ok = matrix_ok if matrix_ok is not None else matrix_witness
        if copy_dependent is None:
            copy_dependent = "version" in rec and "program" in rec and \
                _copy_dependent(rec["version"], rec["program"])
        want = (0 if mode is not None else 1) if copy_dependent else None
        executed = (el.status == "value" and el.value == vd.value) or any(
            r.value == vd.value and (r.ran_on_host == 0 or
                                     r.value == "error_termination")
            for r in runs if r.variant != "probe" or r.probe) or \
            ok(rec, want, tuple(sorted(gone)))
        if not executed:
            vd = E.Verdict("derived", vd.value, vd.agreeing, vd.values,
                           vd.hints, vd.reason + "; no executed witness (no "
                           "device run, elision or matrix run of the "
                           "program or its C port printed it)")
    if triage and triage.get("disposition") == "implementation_defined":
        vd = E.Verdict("implementation_defined", None, (), vd.values,
                       vd.hints, f"implementation defined: "
                       f"\"{triage['quote']}\" ({triage.get('cite', '')})")
    elif gone and vd.status != "disputed":
        vd = dataclasses.replace(vd, reason=vd.reason + "; runs withdrawn "
                                 f"(finding {triage.get('finding')}): "
                                 + ", ".join(sorted(gone)))
    return ev, vd


def evaluate_copy_mode(rec: dict, x0: dict) -> tuple[list, object]:
    """The copy-mode (HSA_XNACK=0) verdict of a program: its own
    metamorphic family and probe witnesses, separate from HSA_XNACK=1."""
    return evaluate(rec, x0)


def as_compiler(other: dict, tag: str) -> dict:
    """A record of gfx90a runs with every run under its compiler's
    gfx942 name (afar_g90 -> afar), so it joins that compiler's evidence."""
    from offload.engine.toolchains import base_name
    return dict(other, runs=[dict(r, toolchain=base_name(r["toolchain"]))
                             for r in other["runs"]], tag=tag)


def combined_runs(rec: dict, x0: dict | None, g90: dict | None = None,
                  nv: dict | None = None) -> dict:
    """(and the gfx90a runs, ``<variant>@g90``;
    and NVHPC's separate-memory runs, ``<variant>@nvhpc``, under their own
    toolchain: another compiler family, so more independent sources): the
    HSA_XNACK=1 runs with the other runs; see ``_combined``."""
    others = ([("x0", x0)] if x0 is not None else []) + \
        ([("g90", as_compiler(g90, "g90"))] if g90 is not None else []) + \
        ([("nvhpc", nv)] if nv is not None else [])
    return _combined(rec, others)


# The expected-behaviour catalog set run on NVHPC (wingtip,
# separate memory: tools/derive/expected.py catalog --toolchains nvhpc --xnack 0
# --out results/expected/catalog.nvhpc.jsonl)
NV_CATALOG = OUT / "catalog.nvhpc.xnack0.jsonl"
# and NVHPC 26.9 (catalog.nvhpc269.xnack0.jsonl): the same family, so its
# runs join 25.11's record (one witness family, two releases)
NV_CATALOGS = (NV_CATALOG, OUT / "catalog.nvhpc269.xnack0.jsonl",
               # The C 5.0 slice's NVHPC runs (tools/campaigns/c_slices.py)
               OUT / "c50.nvhpc.xnack0.jsonl")


@lru_cache(maxsize=None)
def _nv_records(paths: tuple = tuple(str(p) for p in NV_CATALOGS)) -> dict:
    out: dict = {}
    for path in paths:
        for r in _load(Path(path)):
            have = out.get(r["key"])
            if have is None:
                out[r["key"]] = dict(r, runs=list(r["runs"]),
                                     variants=dict(r["variants"]))
                continue
            have["runs"] += r["runs"]
            for k, v in r["variants"].items():
                if not str(have["variants"].get(k, "")).startswith("ok"):
                    have["variants"][k] = v
    return out


def nv_of(rec: dict) -> dict | None:
    """The NVHPC record of a catalog record (None for fuzz or without)."""
    if rec.get("kind") != "catalog":
        return None
    return _nv_records().get(rec["key"])


def _combined(rec: dict, others: list) -> dict:
    """A record whose runs are the HSA_XNACK=1 runs and the
    copy-mode runs of the same toolchains: a copy-mode original or rewrite
    is one more variant of its toolchain (``<variant>@x0``; only for a
    toolchain with values from two different programs), and a
    toolchain's two probe runs are one probe run that holds only when both
    held and gives a value only when both values are equal."""
    runs = [dict(r) for r in rec["runs"] if r["variant"] != "probe"]
    # a toolchain is a metamorphic witness only through two different
    # programs (the original and a rewrite, or two rewrites): the same
    # program in the two modes (or on two GPUs) is no relation
    bases: dict = {}
    for r in rec["runs"] + [r for _, o in others for r in o["runs"]]:
        if r["variant"] != "probe" and r["value"] is not None:
            bases.setdefault(r["toolchain"], set()).add(r["variant"])
    for tag, o in others:
        runs += [dict(r, variant=f"{r['variant']}@{tag}", xnack=1)
                 for r in o["runs"] if r["variant"] != "probe"
                 and len(bases.get(r["toolchain"], ())) >= 2]
    probes: dict = {}
    for r in rec["runs"] + [r for _, o in others for r in o["runs"]]:
        if r["variant"] == "probe":
            probes.setdefault(r["toolchain"], []).append(r)
    for tc in sorted(probes):
        ps = probes[tc]
        if len(ps) == 1:
            r = dict(ps[0], xnack=1)
        else:
            held = (None if any(p.get("probe") is None for p in ps)
                    else all(p["probe"] for p in ps))
            vals = {p["value"] for p in ps}
            r = dict(ps[0], probe=held, xnack=1,
                     value=ps[0]["value"] if len(vals) == 1 else None,
                     ran_on_host=max(p.get("ran_on_host") or 0 for p in ps))
        runs.append(r)
    probe_ok = rec["variants"].get("probe", "").startswith("ok") or any(
        o["variants"].get("probe", "").startswith("ok") for _, o in others)
    variants = dict(rec["variants"])
    if probe_ok:
        variants["probe"] = "ok"
    return dict(rec, runs=runs, variants=variants)


@lru_cache(maxsize=None)
def _catalog_sources(version: int) -> dict:
    from offload.engine.gen import all_programs
    return {p.id: p.source for p in all_programs(version)}


def source_of(rec: dict) -> str | None:
    """The program text of a stored record: its own `source`, a catalog
    program regenerated by id, a fuzz program regenerated from its seed
    (generator version and base groups of the record); None if it can no
    longer be generated."""
    if rec.get("source"):
        return rec["source"]
    if rec.get("kind") == "catalog":
        return _catalog_sources(rec["version"]).get(rec["program"])
    if rec.get("kind") == "fuzz":
        from offload.engine.fuzz import generate
        g = generate(rec["seed"], rec["gen_version"],
                     tuple(rec.get("base") or ()))
        return g.source if rec.get("model") in (
            None, f"checksum={g.expected}") else None
    return None


def evaluate_both(rec: dict, x0: dict | None, g90: dict | None = None,
                  nv: dict | None | bool = True) -> tuple[list, object]:
    """The verdict of a program with its copy-mode (HSA_XNACK=0)
    runs as additional evidence where allows it: only for a
    copy-independent program (offload.engine.expected.copy_independent: its
    result is the same with separate host and device copies), whose
    copy-mode runs are more runs of the same toolchains (metamorphic and
    probe witnesses; never a new independent source). A copy-dependent
    program, or one without copy-mode runs, keeps its HSA_XNACK=1
    verdict (its copy-mode verdict is evaluate_copy_mode). `g90`,
    the program's gfx90a runs, join the same way (runs of the same
    compilers). `nv`, the program's NVHPC separate-memory runs
    (True: looked up in NV_CATALOG), join a copy-independent program's
    evidence as another compiler family."""
    if nv is True:
        nv = nv_of(rec)
    src = source_of(rec) if x0 is not None or g90 is not None or \
        nv is not None else None
    if src is None:
        return evaluate(rec)
    if not E.copy_independent(src, rec.get("version", 52)).ok:
        return evaluate(rec)
    return evaluate(combined_runs(rec, x0, g90, nv or None))


def merge_records(old: list[dict], new: list[dict], sel: dict
                  ) -> list[dict]:
    """The stored records of a catalog set after a partial rerun
    (``catalog --only``): `new` replaces the records of its keys, records
    of programs no longer in the set `sel` are dropped, and every kept
    record's reasons (atom, mismatches, audit) are those of `sel`."""
    by = {r["key"]: r for r in old}
    by.update({r["key"]: r for r in new})
    out = []
    for (v, pid), why in sorted(sel.items()):
        r = by.get(f"{v}:{pid}")
        if r is None:
            continue
        r = dict(r)
        r.update(atom=why["atom"], mismatches=why["mismatches"],
                 audit=why["audit"])
        out.append(r)
    return out


def write(path: Path, recs: list[dict], meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
    path.with_suffix(".meta.json").write_text(json.dumps(meta, indent=1))


def _out(base: Path, xnack: int) -> Path:
    # NVHPC's managed mode (row key 2) writes <out>.xnack2.jsonl
    return base if xnack == 1 else base.with_suffix(f".xnack{xnack}.jsonl")


# --- commands -----------------------------------------------------------------------

def cmd_fuzz(a) -> int:
    from offload.engine.fuzz import generate
    from offload.engine.fuzz_exec import load
    seeds = a.seeds or unresolved_seeds(a.run)
    progs = {p.seed: p for p in load(ROOT / "results" / "fuzz" / a.run)[0]}
    items = []
    for s in seeds:
        pr = progs[s]
        prog = generate(s, pr.gen_version, tuple(pr.base or ()))
        if prog.expected != pr.expected:
            raise SystemExit(f"seed {s}: the generator no longer replays")
        items.append(dict(
            key=f"{a.run}:{s}", seed=s, gen_version=pr.gen_version,
            source=prog.source, version=52, kind="fuzz",
            model=f"checksum={prog.expected}",
            model_detail="offload.engine.fuzz Python model",
            campaign={tc: {"cls": r.cls, "checksum": r.checksum,
                           "host": r.host_checksum}
                      for tc, r in pr.results.items()},
            kernels=list(prog.kernels)))
    print(f"{len(items)} fuzz programs: {[i['seed'] for i in items]}")
    t0 = time.time()
    recs = collect(items, a.toolchains, a.workers, a.xnack)
    out = _out(a.out or OUT / f"{a.run}.jsonl", a.xnack)
    write(out, recs, {"run": a.run, "seeds": seeds, "toolchains":
                      a.toolchains, "xnack": a.xnack, "opt": "-O2",
                      "seconds": round(time.time() - t0),
                      "started": time.strftime("%Y-%m-%dT%H:%M:%S",
                                               time.localtime(t0))})
    print(f"wrote {out} ({time.time() - t0:.0f} s)")
    return 0


def cmd_catalog(a) -> int:
    from offload.engine.gen import all_programs
    sel = catalog_set()
    progs = {}
    for v in sorted({v for v, _ in sel}):
        progs.update({(v, p.id): p for p in all_programs(v)})
    items = []
    for (v, pid), why in sorted(sel.items()):
        if a.only and pid not in a.only:
            continue
        p = progs.get((v, pid))
        if p is None:
            print(f"skip {pid}: no longer generated")
            continue
        if p.expect == "result":
            model = "check=pass"
        elif p.expect == "error_termination":
            model = "error_termination"
        else:
            model = None
        items.append(dict(
            key=f"{v}:{pid}", version=v, program=pid, atom=why["atom"],
            mismatches=why["mismatches"], audit=why["audit"],
            evidence_level=p.evidence, expect=p.expect, source=p.source,
            kind="catalog", model=model,
            model_detail="the program's own oracle" if model else
            f"compile-time expectation ({p.expect})"))
    print(f"{len(items)} catalog programs")
    t0 = time.time()
    recs = collect(items, a.toolchains, a.workers, a.xnack)
    out = _out(a.out or OUT / "catalog.jsonl", a.xnack)
    meta = {"toolchains": a.toolchains, "xnack": a.xnack, "opt": "-O2",
            "seconds": round(time.time() - t0),
            "started": time.strftime("%Y-%m-%dT%H:%M:%S",
                                     time.localtime(t0))}
    if a.only and out.is_file():
        # a partial rerun: merged into the stored records, the first
        # run's meta kept with the rerun listed
        old_meta = out.with_suffix(".meta.json")
        m0 = json.loads(old_meta.read_text()) if old_meta.is_file() \
            else {}
        rerun = dict(meta, programs=sorted(i["key"] for i in items),
                     why=a.why or "")
        meta = dict(m0 or meta)
        meta["reruns"] = list(meta.get("reruns", [])) + [rerun]
        recs = merge_records(_load(out), recs, sel)
    write(out, recs, meta)
    print(f"wrote {out} ({time.time() - t0:.0f} s)")
    return 0


def cmd_xnack0(a) -> int:
    print('WHY="copy-mode runs" flux alloc --setattr=thp=always -N1 '
          '-q pdebug -t 120 bash -c "ulimit -c 0; '
          'cd "${COMPLIANT_ROOT:-$PWD}" && '
          'python3 -I tools/derive/expected.py fuzz --run c1 --xnack 0 --workers 6 '
          '&& python3 -I tools/derive/expected.py catalog --xnack 0 --workers 6 '
          '&& python3 -I tools/derive/expected.py report" '
          '> results/expected/xnack0.log 2>&1')
    return 0


# --- report -------------------------------------------------------------------------

def _load(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x]


def _x0(path: Path) -> dict:
    """{key: copy-mode record} of the HSA_XNACK=0 runs, if any."""
    return {r["key"]: r for r in _load(path.with_suffix(".xnack0.jsonl"))}


def _g90(path: Path) -> dict:
    """{key: gfx90a record} of the Tioga runs, if any:
    ``<stem>.g90.xnack0.jsonl`` next to ``path``."""
    return {r["key"]: r for r in _load(path.with_name(
        f"{path.stem}.g90.xnack0.jsonl"))}


def _copy_cell(rec: dict, x0s: dict) -> str:
    x0 = x0s.get(rec["key"])
    if x0 is None:
        return ""
    _, v = evaluate_copy_mode(rec, x0)
    return f"; copy mode: {v.status}" + (f" {_short(v.value)}"
                                          if v.value else "")


def _ev(ev, tag):
    return next(e for e in ev if e.tag == tag)


def _cell(e) -> str:
    if e.status == "value":
        return f"{e.value}"
    if e.status == "inapplicable":
        return "n/a"
    return e.status.replace("_", " ")


def _md(t: str) -> str:
    return str(t).replace("|", "\\|").replace("\n", " ")


def _clip(t: str, n: int = 160) -> str:
    t = _md(t)
    return t if len(t) <= n else t[:n - 1] + "…"


def _short(v: str | None) -> str:
    return "—" if v is None else v.replace("checksum=", "")


def wrong_toolchains(rec: dict, verdict) -> list[str]:
    """Toolchains whose original run printed something other than the
    trusted value."""
    if verdict.status != "trusted":
        return []
    return sorted(r["toolchain"] for r in rec["runs"]
                  if r["variant"] == "original" and r["value"] is not None
                  and r["value"] != verdict.value)


def settled_by(verdict) -> str:
    if verdict.status == "trusted":
        return " + ".join(t for t in verdict.agreeing)
    return "open"


def render(fuzz_recs, cat_recs, fuzz_x0, cat_x0, metas,
           validity: dict | None = None,
           current: list | None = None,
           fuzz_g90: dict | None = None, cat_g90: dict | None = None) -> str:
    fuzz_g90, cat_g90 = fuzz_g90 or {}, cat_g90 or {}
    L = ["# Independent expected-behaviour sources", "",
         "Generated by `python3 -I tools/derive/expected.py report` from "
         "`results/expected/c1.jsonl` and `results/expected/catalog.jsonl` "
         "(git-ignored). Method, sources and the agreement rule: "
         "[docs/tooling/expected-behaviour.md](../expected-behaviour.md). A value is "
         "**trusted** only when two independent sources (elision, "
         "metamorphic, model, probe) agree and none disagrees: the fuzz "
         "model counts only together with elision or metamorphic, a "
         "catalog program's own oracle only together with elision; "
         "metamorphic and probe are one source when a compiler family "
         "(CCE 19/20/21 are one) backs both. Consensus between toolchains "
         "is listed as a hint and never counts. Disagreements are "
         "recorded, never resolved by majority. Copy-mode (HSA_XNACK=0) "
         "runs, when present, also get a verdict of their own in the "
         "verdict column ('copy mode: ...'). For a "
         "copy-independent program (its result is the same with separate "
         "host and device copies, offload.engine.expected.copy_independent) "
         "the copy-mode runs are additional runs of the same toolchains in "
         "the main verdict: each is one more metamorphic variant of its "
         "toolchain and a toolchain's two probe runs count as one probe "
         "that must hold in both modes; they never add an independent "
         "source. A copy-dependent program's main verdict uses its "
         "HSA_XNACK=1 runs only."
         + (" The catalog programs also ran on Tioga's MI250X "
            "(gfx90a, HSA_XNACK=0, the gfx90a twins of the same "
            "compilers): for a copy-independent program those runs join "
            "the main verdict the same way, as runs of the same compilers "
            "(afar_g90 is afar), never as an independent source."
            if cat_g90 or fuzz_g90 else ""), ""]
    for name, m in metas.items():
        if m:
            L.append(f"- {name}: toolchains {', '.join(m['toolchains'])}, "
                     f"HSA_XNACK={m['xnack']}, {m['opt']}, started "
                     f"{m['started']}, {m['seconds']} s.")
    L.append("")
    # --- fuzz
    validity = validity or {}
    measured = sorted(r["seed"] for r in fuzz_recs)
    now = measured if current is None else sorted(current)
    L += [f"## The {len(now)} c1 programs no host run reproduced", ""]
    left = [s for s in measured if s not in now]
    entered = [s for s in now if s not in measured]
    if current is not None:
        L += [f"Set derived from results/fuzz/c1 with the host "
              f"rechecks (results/fuzz/c1/hostcheck.jsonl): {len(now)} "
              f"programs; measured {len(measured)}."
              + (f" Seeds that left the set: {', '.join(map(str, left))} "
                 "(a host build now prints the model's checksum; their "
                 "Rows stay below)." if left else "")
              + (" Seeds that entered the set without expected-source "
                 f"runs: {', '.join(map(str, entered))}." if entered
                 else ""), ""]
    L += [
          "Campaign c1 (generator fuzz-1): programs whose host reference "
          "run failed or disagreed with the model and whose model checksum "
          "no toolchain's host run (OMP_TARGET_OFFLOAD=disabled; rebuilt "
          "on every toolchain) printed (data/reports/fuzz-c1.md, "
          "'Host reference checks'). Values are checksums; '—' none "
          "(rejected, ICE, run error); 'n/a' the source does not apply. "
          "'Host-path validity' is the maintainer's rule "
          "(offload.engine.fuzz_exec.host_verdict), separate from the verdict "
          "of this page: valid when a host build or the sequential elision "
          "prints the model's checksum (the toolchains whose host build "
          "did not are host_path_failure findings), noncompliant (a "
          "generator/model defect, excluded from the fuzz findings) when "
          "none does. Metamorphic, probe and model agreement do not make "
          "a program valid under that rule.", "",
          "| seed | model | elision | metamorphic | probe | consensus "
          "(hint) | verdict | settled by | toolchains wrong on the "
          "original | host-path validity |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    counts = Counter()
    details = []
    for rec in sorted(fuzz_recs, key=lambda r: r["seed"]):
        ev, vd = evaluate_both(rec, fuzz_x0.get(rec["key"]),
                               fuzz_g90.get(rec["key"]))
        counts[vd.status] += 1
        wrong = wrong_toolchains(rec, vd)
        L.append(f"| {rec['seed']} | {_short(rec['model'])} | "
                 f"{_short(_cell(_ev(ev, 'elision')))} | "
                 f"{_short(_cell(_ev(ev, 'metamorphic')))} | "
                 f"{_short(_cell(_ev(ev, 'probe')))} | "
                 f"{_short(_cell(_ev(ev, 'consensus_only')))} | "
                 f"{vd.status}{_copy_cell(rec, fuzz_x0)} | "
                 f"{settled_by(vd)} | "
                 f"{', '.join(wrong) or '—'} | "
                 f"{_validity_cell(validity.get(rec['seed']))} |")
        details.append((rec, ev, vd))
    L += ["", f"Verdicts: " + ", ".join(f"{k} {v}" for k, v in
                                         sorted(counts.items())) + ".", ""]
    L += ["### Per program", ""]
    for rec, ev, vd in details:
        L += [f"#### seed {rec['seed']}", "",
              f"Kernels: {'; '.join(rec['kernels'])}. Verdict: "
              f"**{vd.status}** ({_md(vd.reason)}).", ""]
        for e in ev:
            L.append(f"- {e.tag}: {e.status}"
                     + (f" {e.value}" if e.value else "")
                     + (f" — {_clip(e.detail, 300)}" if e.detail else ""))
        L += ["", "| variant | " + " | ".join(FUZZ_TCS) + " |",
              "|---|" + "---|" * len(FUZZ_TCS)]
        L += _variant_rows(rec, FUZZ_TCS,
                           fuzz_x0.get(rec["key"], {}).get("runs", []))
        L.append("")
    # --- catalog
    L += ["## Catalog programs: claim mismatches and open oracles", "",
          "The programs behind the 71 claim mismatches of "
          "results/support_table.md (Fortran, results/matrix.jsonl) and "
          "every program whose audit disposition is open "
          f"({', '.join(AUDIT_OPEN)}; there are no 'weak' atoms left after "
          "). Values: check=pass/fail, error_termination. The audit "
          "disposition is kept as it is; the verdict is about the expected "
          "value only.", ""]
    cc = Counter()
    rows_m, rows_a = [], []
    for rec in sorted(cat_recs, key=lambda r: (r["version"],
                                               r["program"])):
        ev, vd = evaluate_both(rec, cat_x0.get(rec["key"]),
                               cat_g90.get(rec["key"]))
        cc[vd.status] += 1
        tri = load_triage().get((rec["version"], rec["program"])) or {}
        if tri.get("needs_human") and vd.status != "trusted":
            # the stated needs_human reason (in full)
            why = _md(_why(ev, vd)) + "; confirmer needs_human: " + \
                _md(tri["needs_human"])
        else:
            why = _clip(_why(ev, vd), 220)
        row = (f"| {rec['version']} | `{rec['program']}` | "
               f"{rec['audit'] or '—'} | {rec['model'] or 'compile-time'} | "
               f"{_cell(_ev(ev, 'elision'))} | "
               f"{_cell(_ev(ev, 'metamorphic'))} | "
               f"{_cell(_ev(ev, 'probe'))} | "
               f"{_cell(_ev(ev, 'consensus_only'))} | "
               f"{vd.status}{_copy_cell(rec, cat_x0)} | "
               f"{why} |")
        if rec["mismatches"]:
            ms = "; ".join(f"{m['toolchain']}: {m['measured']}"
                           for m in rec["mismatches"])
            rows_m.append(row.replace(f"| {rec['audit'] or '—'} |",
                                      f"| {_clip(ms, 120)} |", 1))
        else:
            rows_a.append(row)
    head = ("| version | program | {} | model | elision | metamorphic | "
            "probe | consensus (hint) | verdict | why |")
    sep = "|---|---|---|---|---|---|---|---|---|---|"
    L += [f"Verdicts: " + ", ".join(f"{k} {v}" for k, v in
                                     sorted(cc.items())) + ".", "",
          "### Programs behind claim mismatches", "",
          head.format("mismatch (toolchain: measured)"), sep] + rows_m
    L += ["", "### Programs with an open audit disposition", "",
          head.format("audit disposition"), sep] + rows_a
    L.append("")
    return "\n".join(L) + "\n"


def _why(ev, vd) -> str:
    if vd.status != "provisional":
        return vd.reason
    parts = []
    for e in ev:
        if e.tag in ("elision", "metamorphic", "probe") and \
                e.status != "value":
            parts.append(f"{e.tag}: {e.detail or e.status}")
    if len(vd.agreeing) > 1:
        # agreeing sources that do not count as two
        parts.insert(0, vd.reason)
    return "; ".join(parts) or vd.reason


def _variant_rows(rec, tcs, x0) -> list[str]:
    by = {}
    for r in rec["runs"]:
        by.setdefault(r["variant"], {})[r["toolchain"]] = r
    for r in x0:
        by.setdefault(f"{r['variant']} (XNACK=0)", {})[r["toolchain"]] = r
    out = []
    for name in ["original"] + [n for n in rec["variants"]] + \
            sorted(k for k in by if k.endswith("(XNACK=0)")):
        st = rec["variants"].get(name, "ok")
        if name not in by:
            if name != "original":
                out.append(f"| {name} | {_clip(st, 150)} |" +
                           " |" * (len(tcs) - 1))
            continue
        cells = []
        for tc in tcs:
            r = by[name].get(tc)
            if r is None:
                cells.append("")
                continue
            c = _short(r["value"]) if r["value"] else \
                f"— ({_clip(r['why'], 50)})"
            if r.get("probe") is not None:
                c += " [probe " + ("held" if r["probe"] else "failed") + "]"
            if r.get("ran_on_host") == 1:
                c += " (host)"
            cells.append(c)
        out.append(f"| {name} | " + " | ".join(cells) + " |")
    return out


def cmd_report(a) -> int:
    fz = OUT / f"{a.run}.jsonl"
    ct = OUT / "catalog.jsonl"
    metas = {}
    for name, p in (("fuzz", fz), ("catalog", ct)):
        m = p.with_suffix(".meta.json")
        metas[name] = json.loads(m.read_text()) if m.is_file() else None
    for name, p in (("catalog_g90", ct),):
        m = p.with_name(f"{p.stem}.g90.xnack0.meta.json")
        metas[name] = json.loads(m.read_text()) if m.is_file() else None
    text = render(_load(fz), _load(ct), _x0(fz), _x0(ct), metas,
                  host_validity(a.run), unresolved_seeds(a.run),
                  _g90(fz), _g90(ct))
    REPORT.write_text(text)
    print(f"wrote {REPORT}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fuzz")
    f.add_argument("--run", default="c1")
    f.add_argument("--seeds", type=int, nargs="*")
    f.add_argument("--toolchains", nargs="+", default=list(FUZZ_TCS))
    f.add_argument("--workers", type=int, default=6)
    f.add_argument("--xnack", type=int, choices=(0, 1, 2), default=1)
    f.add_argument("--out", type=Path)
    c = sub.add_parser("catalog")
    c.add_argument("--only", nargs="*",
                   help="program ids to (re)run; merged into the stored "
                   "records of the set")
    c.add_argument("--why", default="", help="reason of a partial rerun "
                   "(recorded in the meta file)")
    c.add_argument("--toolchains", nargs="+", default=list(CAT_TCS))
    c.add_argument("--workers", type=int, default=6)
    c.add_argument("--xnack", type=int, choices=(0, 1, 2), default=1)
    c.add_argument("--out", type=Path)
    r = sub.add_parser("report")
    r.add_argument("--run", default="c1")
    sub.add_parser("xnack0-command")
    a = ap.parse_args(argv)
    return {"fuzz": cmd_fuzz, "catalog": cmd_catalog, "report": cmd_report,
            "xnack0-command": cmd_xnack0}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
