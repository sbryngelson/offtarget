"""The stored failing rows of every campaign, as reproduction-gate items
(offload.engine.gate), and how each is run again (offload.engine.gate_run).

Campaigns (CAMPAIGNS) and what counts as a failing row:
catalog: results/matrix.jsonl, matrix_c.jsonl, acc_matrix.jsonl and
acc_matrix_c.jsonl (a later file's row replaces an earlier one); legal
programs with outcome other than correct_on_device.
widen: results/widen/matrix.jsonl, the same rule.
fuzz: every campaign's programs.jsonl; valid programs that passed the
legality check, classes other than agree and harness_error.
stress: runs read by offload.engine.stress_report.STRESS_RUNS; programs that
passed the stress gate, classes other than agree and the skipped ones.
evidence: failed runs in results/confirm/evidence.jsonl whose program can
be rebuilt from the batches' cases; the rest count as `unrecoverable`."""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

from offload.engine.toolchains import TOOLCHAINS

ROOT = Path(__file__).resolve().parent.parent.parent
RESULTS = ROOT / "results"
CAMPAIGNS = ("catalog", "widen", "fuzz", "stress", "evidence")
CATALOG_FILES = ("matrix.jsonl", "matrix_c.jsonl", "acc_matrix.jsonl",
                 "acc_matrix_c.jsonl")
WIDEN_FILES = ("widen/matrix.jsonl",)
CATALOG_TIMEOUT_S = 120          # tools/campaigns/run_matrix.py --timeout default


def _mode(tc: str, xnack: int) -> str:
    from offload.engine.confirm import machines as M
    m = M.load()[TOOLCHAINS[tc].machine]
    return m.mode_of_row_key(int(xnack))


def machine_of(tc: str) -> str:
    return TOOLCHAINS[tc].machine


def _lines(path: Path):
    with path.open() as f:
        for k, ln in enumerate(f, 1):
            if ln.strip():
                try:
                    yield k, json.loads(ln)
                except json.JSONDecodeError:
                    continue


def _compile_log(stderr: str) -> str:
    """The compile section of a harness row's stderr."""
    m = re.search(r"--- compile \(rc=[^)]*\) ---\n(.*?)(?:\n--- run |\Z)",
                  stderr or "", re.S)
    return m.group(1) if m else ""


def harness_items(campaign: str, files) -> list[dict]:
    cells: dict[tuple, dict] = {}
    for name in files:
        p = RESULTS / name
        if not p.is_file():
            continue
        for k, d in _lines(p):
            if d.get("toolchain") not in TOOLCHAINS or "status" in d:
                continue
            cells[(d["program_id"], d["toolchain"], d["xnack"])] = \
                {**d, "_origin": f"{p.relative_to(ROOT)}:{k}"}
    out = []
    for (pid, tc, x), d in sorted(cells.items()):
        if d["outcome"] in ("correct_on_device", "unobservable",
                            "harness_error") or not d.get("legal", True):
            continue
        out.append({
            "campaign": campaign, "kind": campaign,
            "cell": f"{campaign}|{pid}|{tc}|{x}", "ident": pid,
            "toolchain": tc, "machine": machine_of(tc), "xnack": x,
            "mode": _mode(tc, x), "opt": d.get("opt", "-O2"),
            "outcome": d["outcome"], "reason": d.get("reason", ""),
            "flaky": bool(d.get("flaky")), "stdout": (d.get("stdout")
                                                      or "")[-400:],
            "build_dir": d.get("build_dir", ""), "node": d.get("node", ""),
            "toolchain_build": d.get("toolchain_build") or
            d.get("compiler", ""),
            "compile_log": _compile_log(d.get("stderr", ""))[-3000:],
            "timeout_s": CATALOG_TIMEOUT_S, "origin": d["_origin"],
            "locator": {"pid": pid}})
    return out


def fuzz_items() -> list[dict]:
    from offload.engine.confirm import ingest as I
    from offload.engine.fuzz_exec import load
    out = []
    camp = I.campaigns()
    for path in I.fuzz_files():
        run = path.parent.name
        x = I._fuzz_meta(path.parent).get("xnack", 1)
        progs, _ = load(path.parent)
        for pr in progs:
            if pr.check != "ok" or getattr(pr, "validity", "valid") != \
                    "valid":
                continue
            for tc, r in pr.results.items():
                if tc not in TOOLCHAINS or r.cls in ("agree",
                                                     "harness_error"):
                    continue
                ident = f"{camp.get(run) or run}:{pr.seed}"
                out.append({
                    "campaign": "fuzz", "kind": "fuzz",
                    "cell": f"fuzz|{run}:{pr.seed}|{tc}|{x}",
                    "ident": ident, "toolchain": tc,
                    "machine": machine_of(tc), "xnack": x,
                    "mode": _mode(tc, x), "opt": "-O2", "cls": r.cls,
                    "reason": r.reason, "checksum": r.checksum,
                    "flaky": bool(r.flaky), "compile_s": r.compile_s or None,
                    "run_s": r.run_s or None, "timeout_s": 60,
                    "build_dir": getattr(r, "build_dir", "") or "",
                    "node": getattr(r, "node", "") or "",
                    "toolchain_build": getattr(r, "toolchain_build", ""),
                    "compile_log": (r.output or "")[-3000:],
                    "origin": f"{path.relative_to(ROOT)}#seed={pr.seed}",
                    "locator": {"run": run, "seed": pr.seed,
                                "gen_version": pr.gen_version,
                                "base": list(pr.base or ()),
                                "expected": pr.expected}})
    return out


STRESS_FAIL_SKIP = ("agree", "harness_error", "skipped", "probe_rejected")


def stress_items() -> list[dict]:
    from offload.engine import stress_report as SR
    progs, rows = SR.load(SR.STRESS_RUNS, canaries=False)
    out = []
    for r in rows:
        p = progs.get(r["id"])
        if r["toolchain"] not in TOOLCHAINS or r["cls"] in STRESS_FAIL_SKIP \
                or not SR.valid(p) or p.get("legality", "legal") != "legal":
            continue
        tc = r["toolchain"]
        lim = r.get("limits") or {}
        out.append({
            "campaign": "stress", "kind": "stress",
            "cell": f"stress|{r['id']}|{tc}|{r['mode']}|{r['variant']}",
            "ident": r["id"], "toolchain": tc, "machine": machine_of(tc),
            "xnack": r["mode"], "mode": _mode(tc, r["mode"]),
            "variant": r["variant"], "axis": r.get("axis", ""),
            "cls": r["cls"], "reason": r.get("reason", ""),
            "checksum": r.get("checksum"),
            "bad_kernels": r.get("bad_kernels") or [],
            "flaky": bool(r.get("flaky")),
            "compile_s": r.get("compile_s") or None,
            "run_s": r.get("run_s") or None,
            "timeout_s": lim.get("run_s", 120),
            "build_dir": r.get("build_dir", ""), "node": r.get("host", ""),
            "toolchain_build": r.get("toolchain_build", ""),
            "compile_log": (r.get("output") or "")[-3000:],
            "origin": f"results/stress/{r['run']}/rows.jsonl",
            "locator": {"axis": p["axis"], "size": p["size"],
                        "seed": p["seed"], "model": p["model"],
                        "lang": p.get("lang", "f90"),
                        "layout": p.get("layout", "single"),
                        "id": r["id"], "limits": lim}})
    return out


# --- the confirmer's evidence ------------------------------------------------------

BATCHES = ("confirm/batch_full.jsonl", "confirm/batch_s1.final.jsonl",
           "confirm/batch_widen.jsonl")


def _batch_refs() -> dict:
    """(kind, ident) -> ProgramRef of every case in the batches."""
    from offload.engine.confirm import programs as P
    from offload.engine.confirm.model import ProgramRef
    refs = {}
    for name in BATCHES:
        p = RESULTS / name
        if not p.is_file():
            continue
        for _, d in _lines(p):
            pr = (d.get("case") or {}).get("program") or {}
            key = (pr.get("kind"), pr.get("ident"))
            if None in key or key in refs:
                continue
            try:
                if pr["kind"] == "catalog":
                    ref = P.catalog_ref(pr["ident"])
                elif pr["kind"] == "fuzz":
                    from offload.engine.confirm import ingest as I
                    row = I.stored_index().rows_of("fuzz", pr["ident"])
                    if not row:
                        continue
                    ref = I.ref_of_row(row[0])
                elif pr["kind"] == "ompvv":
                    continue      # omp_vv stays untrusted (not gated)
                else:
                    path = ROOT / pr["ident"]
                    if not path.is_file():
                        continue
                    ref = P.file_ref([str(path)], pr.get("expected", ""))
            except Exception:
                continue
            if ref.text:
                refs[key] = ref
    return refs


def _variants_by_sha(refs: dict) -> dict:
    """sha -> (ref, variant name) of every case program and of its
    metamorphic variants (offload.engine.transforms.variants)."""
    from offload.engine import transforms as T
    from offload.engine.confirm.model import ProgramRef
    out = {}
    for ref in refs.values():
        out[ref.sha] = (ref, "original")
        if ref.lang != "f90":
            continue
        try:
            vs = T.variants(ref.text, ref.version or 52)
        except Exception:
            continue
        for name, src in vs.items():
            if isinstance(src, str):
                v = ProgramRef(**{**ref.__dict__, "text": src})
                out[v.sha] = (v, name)
    return out


def evidence_items(stats: dict | None = None) -> list[dict]:
    """The evidence items, cached in results/gate/evidence/items.jsonl
    (rebuilding the batches' programs and variants takes 20 minutes);
    the cache is rebuilt when evidence.jsonl is newer."""
    cache = RESULTS / "gate" / "evidence" / "items.jsonl"
    ev = RESULTS / "confirm" / "evidence.jsonl"
    if cache.is_file() and ev.is_file() and \
            cache.stat().st_mtime > ev.stat().st_mtime:
        lines = cache.read_text().splitlines()
        if stats is not None and lines and lines[0].startswith('{"stats"'):
            stats.update(json.loads(lines[0])["stats"])
        return [json.loads(x) for x in lines[1:] if x.strip()]
    st: dict = {}
    out = _evidence_items(st)
    cache.parent.mkdir(parents=True, exist_ok=True)
    with cache.open("w") as fh:
        fh.write(json.dumps({"stats": st}) + "\n")
        for it in out:
            fh.write(json.dumps(it) + "\n")
    if stats is not None:
        stats.update(st)
    return out


def _evidence_items(stats: dict | None = None) -> list[dict]:
    from offload.engine.confirm.model import Evidence
    path = RESULTS / "confirm" / "evidence.jsonl"
    if not path.is_file():
        return []
    latest = {}
    for _, d in _lines(path):
        e = Evidence.from_dict(d)
        latest[e.key] = e
    fails = [e for e in latest.values() if e.runs and
             e.provenance.origin.startswith(("run", "remote")) and
             e.toolchain in TOOLCHAINS and
             any(r.outcome not in ("correct_on_device", "unobservable",
                                   "harness_error") for r in e.runs)]
    by_sha = _variants_by_sha(_batch_refs())
    out, lost = [], 0
    store = RESULTS / "gate" / "evidence" / "programs"
    for e in fails:
        hit = by_sha.get(e.sha)
        if hit is None:
            lost += 1
            continue
        ref, _ = hit
        worst = next(r for r in e.runs if r.outcome not in (
            "correct_on_device", "unobservable", "harness_error"))
        store.mkdir(parents=True, exist_ok=True)
        (store / f"{e.sha}.txt").write_text(ref.text)
        tc = e.toolchain
        rd = {k: v for k, v in ref.__dict__.items() if k != "text"}
        rd["needs"] = list(rd.get("needs") or ())
        out.append({
            "campaign": "evidence", "kind": "evidence",
            "cell": f"evidence|{e.collector}|{e.sha[:16]}|{tc}|{e.mode}|"
                    f"{e.opt}|{e.offload}|{e.variant}",
            "ident": f"{ref.kind}:{ref.ident}:{e.variant}",
            "toolchain": tc, "machine": machine_of(tc), "mode": e.mode,
            "xnack": _row_key(tc, e.mode), "opt": e.opt,
            "outcome": worst.outcome, "reason": worst.reason,
            "value": worst.value,
            "flaky": len({(r.outcome, r.value) for r in e.runs}) > 1,
            "node": e.provenance.host, "timeout_s": 120,
            "origin": f"results/confirm/evidence.jsonl ({e.collector}, "
                      f"{e.provenance.origin})",
            "locator": {"sha": e.sha, "ref": rd, "offload": e.offload,
                        "collector": e.collector, "variant": e.variant}})
    if stats is not None:
        stats["unrecoverable"] = lost
        stats["failing_entries"] = len(fails)
    return out


def _row_key(tc: str, mode: str) -> int:
    from offload.engine.confirm import machines as M
    return M.load()[TOOLCHAINS[tc].machine].row_key(mode)


def finding_items(files) -> list[dict]:
    """A finding's reproducer as gate items, one per toolchain
    and memory mode its index entry names (data/findings/index.yaml);
    the legality review of a finding whose linked cells the gate did not
    confirm reruns the reproducer itself."""
    from offload.engine.confirm import findings as FI
    from offload.engine.confirm import machines as M
    idx = {f.file: f for f in FI.index()}
    out = []
    for path in files:
        rel = str(path).replace("data/findings/", "")
        f = idx.get(f"data/findings/{rel}") or idx.get(rel)
        if f is None:
            raise KeyError(f"{path}: no index entry")
        for tc in f.toolchains:
            if tc not in TOOLCHAINS:
                continue
            m = M.load()[TOOLCHAINS[tc].machine]
            for mode in f.modes:
                if not m.has(mode):
                    continue
                out.append({
                    "campaign": "findings", "kind": "file",
                    "cell": f"file|{rel}|{tc}|{m.row_key(mode)}",
                    "ident": rel, "toolchain": tc, "machine": m.name,
                    "mode": mode, "xnack": m.row_key(mode), "opt": "-O2",
                    "outcome": f.outcome, "reason": f.message,
                    "signature": f"{tc}|{f.outcome}|{rel}",
                    "sample": "all", "locator": {
                        "path": f"data/findings/{rel}",
                        "expected": f.expected}})
    return out


def items(campaign: str, stats: dict | None = None) -> list[dict]:
    if campaign == "catalog":
        return harness_items("catalog", CATALOG_FILES)
    if campaign == "widen":
        return harness_items("widen", WIDEN_FILES)
    if campaign == "fuzz":
        return fuzz_items()
    if campaign == "stress":
        return stress_items()
    if campaign == "evidence":
        return evidence_items(stats)
    raise KeyError(campaign)


# --- programs and runs ---------------------------------------------------------------

@lru_cache(maxsize=4096)
def _catalog_prog(pid: str):
    from offload.engine.confirm import programs as P
    return P.catalog_program(pid)


def load_factor() -> float:
    """The factor the gate's time limits are scaled by (GATE_LOAD_FACTOR,
    set by tools/campaigns/gate.py run from its workers per node: found 9
    stress run timeouts and 3 compile timeouts that came from 24 reruns
    per node, none at low load)."""
    try:
        return max(1.0, float(os.environ.get("GATE_LOAD_FACTOR", "1")))
    except ValueError:
        return 1.0


def rerun(item: dict, env: dict) -> dict:
    """Run one item again in one environment (its campaign's runner), its
    time limits scaled by ``load_factor``."""
    out = _rerun(item, env)
    f = load_factor()
    if f > 1:
        out["load_factor"] = f
    return out


def _rerun(item: dict, env: dict) -> dict:
    from offload.engine import gate_run as GR
    f = load_factor()
    kind = item["kind"]
    loc = item["locator"]
    tc_name = item["toolchain"]
    if kind in ("catalog", "widen"):
        from offload.engine.confirm import programs as P
        from offload.engine.confirm.execute import toolchain_for
        prog = _catalog_prog(loc["pid"])
        if prog is None:
            return {"env": env["env"], "outcome": "harness_error",
                    "reason": "the program is no longer generated",
                    "path": env["path"]}
        tc = toolchain_for(P.catalog_ref(loc["pid"], prog), tc_name)
        return GR.rerun_program(prog, tc, int(item["xnack"]), env,
                                item.get("opt", "-O2"),
                                timeout_s=int(f * int(item.get("timeout_s")
                                                      or 120)),
                                compile_timeout_s=int(f * 900))
    if kind == "fuzz":
        from offload.engine.fuzz import generate
        prog = generate(loc["seed"], loc["gen_version"],
                        tuple(loc.get("base") or ()))
        if loc.get("expected") is not None and prog.expected != \
                loc["expected"]:
            return {"env": env["env"], "outcome": "harness_error",
                    "reason": "the generator no longer gives this program",
                    "path": env["path"]}
        return GR.rerun_fuzz(prog, TOOLCHAINS[tc_name], int(item["xnack"]),
                             env)
    if kind == "stress":
        from offload.engine import stress_exec as X
        prog = stress_program(loc)
        if prog is None or prog.id != loc["id"]:
            return {"env": env["env"], "outcome": "harness_error",
                    "reason": "the stress generator no longer gives this "
                              "program", "path": env["path"]}
        lim = X.Limits(**{k: (int(v * f) if k != "mem_gib" else v)
                          for k, v in (loc.get("limits") or {}).items()
                          if k in ("compile_s", "mem_gib", "run_s")})
        return GR.rerun_stress(prog, tc_name, int(item["xnack"]),
                               item["variant"], lim, env)
    if kind == "file":
        from offload.engine.confirm import programs as P
        ref = P.file_ref([str(ROOT / loc["path"])],
                         loc.get("expected") or "")
        return GR.rerun_ref(ref, tc_name, item["mode"], item.get("opt",
                                                                 "-O2"),
                            "mandatory", env)
    if kind == "evidence":
        from offload.engine.confirm.model import ProgramRef
        rd = dict(loc["ref"])
        rd["needs"] = tuple(rd.get("needs") or ())
        text = (RESULTS / "gate" / "evidence" / "programs" /
                f"{loc['sha']}.txt").read_text()
        ref = ProgramRef(**rd, text=text)
        return GR.rerun_ref(ref, tc_name, item["mode"], item.get("opt",
                                                                 "-O2"),
                            loc.get("offload", "mandatory"), env)
    raise KeyError(kind)


def stress_program(loc: dict):
    try:
        if loc.get("lang") == "c":
            from offload.engine import stress_c as C
            return C.build_c(loc["axis"], loc["size"], loc["seed"],
                             loc.get("layout", "single"))
        from offload.engine import stress as S
        return S.build(loc["axis"], loc["size"], loc["seed"],
                       loc.get("model", "omp"), loc.get("layout", "single"))
    except Exception:
        return None
