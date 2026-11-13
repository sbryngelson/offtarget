#!/usr/bin/env python3
"""kernel-body campaign: programs that vary the statements inside a kernel
(offload/engine/kbody_gen.py). The driver is tools/campaigns/nested.py's.

Subcommands (run with ``python3 -I`` from the repository root):

* ``gen``: ``--kind pilot --n N --seed S``, ``--kind nbhd`` (single-axis and
  two-axis neighbours) or ``--kind cfgs --cfgs FILE`` (a JSON list of
  configurations) -> results/kbody/<name>/;
* ``prerun``: the rules and AFAR's front end; ``witness``: NVHPC 26.9
  compile only; ``legality``: the table of the witnesses;
* ``run``: compile and run on this machine's toolchains (resumable);
* ``hostref``: run with OMP_TARGET_OFFLOAD=disabled; it must print the
  model's values;
* ``gate``, ``report``, ``cluster``: as tools/campaigns/nested.py (kind ``kbody``)."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

OUT = ROOT / "results" / "kbody"
MODE_NAME = {0: "copy", 1: "unified", 2: "unified"}
TARGETS = {"tuolumne": (["afar", "cce19", "cce20", "cce21", "cce21_4"],
                        [0, 1]),
           "tioga": (["gcc_g90"], [0]),
           "wingtip": (["nvhpc", "nvhpc269", "gcc_sm80"], [0, 2])}
FAILING_OK = ("correct_on_device", "unobservable")
FE_TIMEOUT_S = 90           # one front-end check; a hang is no verdict


def _oop():
    """tools/campaigns/oop.py's file helpers and front-end verdict logic."""
    spec = importlib.util.spec_from_file_location("campaign_oop",
                                                  ROOT / "tools" / "campaigns" / "oop.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_O = _oop()
_jl, _append = _O._jl, _O._append
# a front end's rejection that names a feature it lacks is no legality
# verdict (tools/campaigns/oop.py's list, plus what NVHPC says about the map
# modifiers, declare mapper and the allocatable runtime it lacks)
NOT_A_VERDICT = re.compile(
    _O.NOT_A_VERDICT.pattern +
    r"|invalid text in pragma|syntax error at or near|openmp gpu - 'target'"
    r" is used with map-type|call to nvhpc runtime function|openacc data "
    r"clause expected|no acc routine information", re.I)


def _fe(ok, why: str):
    if ok is None:
        return None
    if ok:
        return True
    return None if NOT_A_VERDICT.search(why or "") else False


def family_of(tc: str) -> str:
    from offload.engine.toolchains import TOOLCHAINS
    return TOOLCHAINS[tc].kind


def _register():
    from offload.engine import gate as GT
    GT.register_kind("kbody", "kbody_", "program")


_CACHE: dict = {}


def sample(meta: dict) -> list:
    from dataclasses import replace
    from offload.engine import kbody_gen as G
    kind = meta.get("kind", "pilot")
    if kind == "pilot":
        return G.pilot(meta["n"], meta["seed"])
    if kind == "nbhd":
        base = G.student_cfg() if not meta.get("base") else replace(
            G.Cfg(), **{k: (tuple(v) if k == "dims" else v)
                        for k, v in meta["base"].items()})
        cfgs = [base] + [c for _, _, c in G.neighbours(base, True)]
        return [G.program(c) for c in cfgs]
    if kind == "heap":
        return [G.program(c) for c in G.heap_cfgs()]
    if kind == "cfgs":
        return [G.program(replace(G.Cfg(), **{
            k: (tuple(v) if k == "dims" else v) for k, v in d.items()}))
            for d in meta["cfgs"]]
    raise SystemExit(f"unknown kind {kind}")


def programs(name: str = "main", ids=None) -> list:
    """The campaign's programs: the sample regenerated from meta.json and
    checked against programs.jsonl's hashes."""
    import hashlib
    if name not in _CACHE:
        meta = json.loads((OUT / name / "meta.json").read_text())
        ps = sample(meta)
        stored = {r["id"]: r["sha"] for r in _jl(OUT / name /
                                                 "programs.jsonl")}
        for p in ps:
            sha = hashlib.sha256(p.source.encode()).hexdigest()
            if stored.get(p.id, sha) != sha:
                raise SystemExit(f"{p.id}: the generator changed since "
                                 f"`gen` (sha differs)")
        _CACHE[name] = ps
    return [p for p in _CACHE[name] if not ids or p.id in ids]


def ext(p) -> str:
    return "c" if p.lang == "c" else "f90"


def cmd_gen(a) -> int:
    import hashlib
    d = OUT / a.name
    (d / "src").mkdir(parents=True, exist_ok=True)
    meta = {"kind": a.kind, "n": a.n, "seed": a.seed}
    if a.base:
        meta["base"] = json.loads(Path(a.base).read_text())
    if a.kind == "cfgs":
        meta["cfgs"] = json.loads(Path(a.cfgs).read_text())
    (d / "meta.json").write_text(json.dumps(meta))
    ps = sample(meta)
    rows = []
    for p in ps:
        (d / "src" / f"{p.id}.{ext(p)}").write_text(p.source)
        rows.append({"id": p.id, "family": p.family, "lang": p.lang,
                     "model": p.model, "version": p.version,
                     "legality": p.legality, "why": p.why,
                     "expected": p.expected, "rules": list(p.rules),
                     "cites": [dict(r) for r in p.cites], "axes": p.axes,
                     "title": p.title,
                     "sha": hashlib.sha256(p.source.encode()).hexdigest()})
    (d / "programs.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    print(f"{len(rows)} programs -> {d}")
    return 0


def _prerun_one(args):
    name, pid = args
    from offload.engine import prerun
    p = programs(name, {pid})[0]
    r_ok, r_why = prerun.rules_witness(p)
    f_ok, f_why = prerun.frontend_witness(p, timeout_s=FE_TIMEOUT_S)
    why = list(r_why) + [w for w in f_why if f_ok is not True]
    if r_ok is not None and f_ok is not None and r_ok != f_ok:
        why.append("witnesses disagree: legality review")
    return {"id": p.id, "ok": bool(r_ok and f_ok), "reasons": why,
            "rules": r_ok, "rules_why": r_why, "afar_fe": f_ok,
            "afar_why": f_why}


def cmd_prerun(a) -> int:
    from concurrent.futures import ProcessPoolExecutor
    out = OUT / a.name / "prerun.jsonl"
    done = {r["id"] for r in _jl(out)}
    todo = [(a.name, p.id) for p in programs(a.name) if p.id not in done]
    from concurrent.futures import as_completed
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        futs = [pool.submit(_prerun_one, t) for t in todo]
        for f in as_completed(futs):
            _append(out, [f.result()])
    rows = {r["id"]: r for r in _jl(out)}
    bad = [r for r in rows.values() if not r["ok"]]
    for r in bad:
        print("refused", r["id"], "; ".join(r["reasons"])[:300])
    print(f"{len(rows)} checked, {len(bad)} refused")
    return 0


def _witness_one(args):
    name, pid = args
    import hashlib
    from offload.engine.confirm import witness as W
    p = programs(name, {pid})[0]
    sha = hashlib.sha256(p.source.encode()).hexdigest()
    try:
        return W.check(p.id, p.source, p.lang, sha, model=p.model)
    except Exception as e:
        return {"program": p.id, "sha256": sha, "result": "error",
                "message": f"{type(e).__name__}: {e}"[:300]}


def cmd_witness(a) -> int:
    from concurrent.futures import ThreadPoolExecutor
    out = OUT / a.name / "witness.jsonl"
    done = {r["program"] for r in _jl(out) if r.get("result") != "error"}
    todo = [(a.name, p.id) for p in programs(a.name) if p.id not in done]
    with ThreadPoolExecutor(max_workers=min(a.workers, 4)) as pool:
        for r in pool.map(_witness_one, todo):
            _append(out, [r])
            print(r["program"], r["result"], r.get("message", "")[:120],
                  flush=True)
    return 0


def rows(name: str) -> list[dict]:
    last = {}
    for r in _jl(OUT / name / "rows.jsonl"):
        last[(r["program_id"], r["toolchain"], r["xnack"])] = r
    return list(last.values())


def legality(name: str) -> dict:
    """program id -> {rules, afar_fe, nvhpc_fe, cce_fe, legality, legal_for}
    as tools/campaigns/oop.py: a program is legal for a compiler family when the
    rules accept it, a front end of another family accepts it and none of
    another family rejects it with a diagnostic (a rejection that names a
    missing feature is no verdict). GCC never witnesses."""
    pre = {r["id"]: r for r in _jl(OUT / name / "prerun.jsonl")}
    wit = {r["program"]: r for r in _jl(OUT / name / "witness.jsonl")}
    cce = {}
    for r in rows(name):
        if r["toolchain"].startswith("cce"):
            reason = str(r.get("reason", ""))
            pid = r["program_id"]
            if r["outcome"] not in ("rejected", "harness_error") or \
                    reason.startswith("link_undefined"):
                cce[pid] = True
            elif r["outcome"] == "rejected" and \
                    reason.startswith("diagnostic") and \
                    not NOT_A_VERDICT.search(reason) and \
                    cce.get(pid) is not True:
                cce[pid] = False
            else:
                cce.setdefault(pid, None)
    out = {}
    for p in programs(name):
        r = pre.get(p.id) or {}
        rules = r.get("rules")
        afar = _fe(r.get("afar_fe"), "; ".join(r.get("afar_why") or []))
        w = wit.get(p.id, {})
        nv = _fe({"accept": True, "reject": False}.get(w.get("result")),
                 w.get("message", ""))
        fe = {"afar": afar, "nvhpc": nv, "cce": cce.get(p.id)}
        legal_for = {}
        for fam in ("afar", "cce", "nvhpc", "gcc"):
            others = [v for f, v in fe.items() if f != fam and v is not None]
            legal_for[fam] = bool(rules) and any(others) and all(others)
        out[p.id] = {"rules": rules, "afar_fe": afar, "nvhpc_fe": nv,
                     "cce_fe": cce.get(p.id), "legality": p.legality,
                     "legal_for": legal_for,
                     "prerun": (r.get("rules_why", []) +
                                r.get("afar_why", []))[:4],
                     "nvhpc_message": w.get("message", "")}
    return out


def cmd_legality(a) -> int:
    leg = legality(a.name)
    (OUT / a.name / "legality.json").write_text(json.dumps(leg, indent=1,
                                                           sort_keys=True))
    n_all = sum(1 for r in leg.values() if all(r["legal_for"].values()))
    for pid, r in leg.items():
        if not all(r["legal_for"].values()) or r["legality"] != "defined":
            print(pid, r["legality"], "rules", r["rules"], "afar_fe",
                  r["afar_fe"], "nvhpc_fe", r["nvhpc_fe"], "|",
                  r["nvhpc_message"][:100], "|",
                  "; ".join(r["prerun"])[:160])
    print(f"{len(leg)} programs; {n_all} legal for every family")
    return 0


# --- runs ---------------------------------------------------------------------------

def _cells(progs, toolchains, modes, ok: set):
    from offload.engine.toolchains import TOOLCHAINS
    out = []
    for p in progs:
        if p.id not in ok:
            continue
        for t in toolchains:
            tc = TOOLCHAINS[t]
            if p.model == "acc" and (tc.kind == "afar" or (
                    tc.kind == "cce" and p.lang == "c")):
                continue                   # no OpenACC (AFAR), no C (CCE)
            for x in modes:
                if x in tc.xnack_modes and MODE_NAME[x] in p.modes:
                    out.append((p, t, x))
    return out


def _run_one(job):
    import dataclasses
    import time
    from offload.engine import harness, run_matrix
    from offload.engine import kbody_gen as G
    from offload.engine.toolchains import TOOLCHAINS
    p, t, x, timeout_s, a_repeats = job
    tc = run_matrix.for_version(TOOLCHAINS[t], p.version, p.lang)
    t0 = time.time()
    try:
        r = harness.run_program(p.harness(), tc, x, "-O2",
                                timeout_s=timeout_s, repeats=a_repeats)
        d = dataclasses.asdict(r)
    except Exception as e:
        d = {"program_id": p.id, "toolchain": t, "xnack": x,
             "outcome": "harness_error", "reason": f"harness: {e}"[:300]}
    d.update(campaign="kbody", family=p.family, lang=p.lang, model=p.model,
             legality=p.legality, mode=MODE_NAME[x], expected=p.expected,
             observed=G.parse_observed(d.get("stdout", "")),
             task_s=round(time.time() - t0, 1))
    d["stdout"] = (d.get("stdout") or "")[-2000:]
    d["stderr"] = (d.get("stderr") or "")[-3000:]
    return d


def prerun_ok(name: str) -> set:
    stored = {r["id"]: r.get("rules") for r in
              _jl(OUT / name / "prerun.jsonl")}
    from offload.engine import prerun
    ok = set()
    for p in programs(name):
        v = stored.get(p.id)
        if v is None:
            v = prerun.rules_witness(p)[0]
        if v:
            ok.add(p.id)
    return ok


def cmd_run(a) -> int:
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed
    d = OUT / a.name
    ok = prerun_ok(a.name)
    if not ok:
        print("no program has a rules verdict")
        return 2
    tcs = a.toolchains.split(",") if a.toolchains else TARGETS[a.machine][0]
    modes = [int(m) for m in a.modes.split(",")] if a.modes else \
        TARGETS[a.machine][1]
    out = d / "rows.jsonl"
    done = {(r["program_id"], r["toolchain"], r["xnack"]) for r in _jl(out)}
    ids = set(a.ids.split(",")) if a.ids else None
    progs = programs(a.name, ids)
    if a.legal_only:
        progs = [p for p in progs if p.legality == "defined"]
    jobs = [(p, t, x, a.timeout, a.repeats) for p, t, x in _cells(progs, tcs, modes, ok)
            if (p.id, t, x) not in done]
    import random
    random.Random(7).shuffle(jobs)         # a run cut short covers every axis
    if a.shard:
        k, m = (int(v) for v in a.shard.split("/"))
        jobs = jobs[k::m]
    print(f"{len(jobs)} runs to do ({len(done)} done)", flush=True)
    end = time.time() + a.limit_s
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futs = [pool.submit(lambda j=j: None if time.time() > end
                            else _run_one(j)) for j in jobs]
        for f in as_completed(futs):
            r = f.result()
            if r is not None:
                _append(out, [r])
    print("done", flush=True)
    return 0


# --- the reproduction gate ----------------------------------------------------------

def gate_items(name: str, machine: str | None = None) -> list[dict]:
    from offload.engine.gate_stored import machine_of
    legal = {p.id: p.legality for p in programs(name)}
    out = []
    for r in rows(name):
        if r["outcome"] in FAILING_OK or r["outcome"] == "harness_error":
            continue
        if legal.get(r["program_id"]) != "defined":
            continue                       # observations are not gated
        m = machine_of(r["toolchain"])
        if machine and m != machine:
            continue
        out.append({**{k: r.get(k) for k in (
            "outcome", "reason", "flaky", "build_dir", "node",
            "toolchain_build", "toolchain", "xnack", "mode")},
            "campaign": "kbody", "kind": "kbody", "machine": m,
            "ident": r["program_id"], "opt": "-O2", "timeout_s": 120,
            "stdout": r.get("stdout") or "",
            "compile_log": (r.get("stderr") or "")[-3000:],
            "cell": f"kbody|{r['program_id']}|{r['toolchain']}|"
                    f"{r['xnack']}", "family": r["family"]})
    return out


def gate_budget(name: str) -> float | None:
    """The gate's budget (summed rerun seconds, tools/campaigns/nested.py gate
    --budget-s), kept in meta.json so every later command plans the same
    sample; None: gate every failing row."""
    try:
        return json.loads((OUT / name / "meta.json").read_text()).get(
            "gate_budget_s")
    except FileNotFoundError:
        return None


def gate_plan(items: list[dict], budget_s: float | None = None) -> dict:
    from offload.engine import gate as GT
    _register()
    total = sum(len(GT.ENVS) * GT.cost_s(it) for it in items) + 1
    return GT.plan(items, budget_s=budget_s or total)


def cmd_gate(a) -> int:
    from concurrent.futures import ThreadPoolExecutor
    from offload.engine import gate as GT
    from offload.engine import gate_run as GR
    from offload.engine import run_matrix
    from offload.engine.toolchains import TOOLCHAINS
    _register()
    byid = {p.id: p for p in programs(a.name)}
    if a.budget_s:
        mp = OUT / a.name / "meta.json"
        meta = json.loads(mp.read_text())
        meta["gate_budget_s"] = a.budget_s
        mp.write_text(json.dumps(meta))
    # the plan covers every machine's rows (as `verdicts` plans them); this
    # run takes its machine's share
    planned = gate_plan(gate_items(a.name), gate_budget(a.name))
    items = [r for r in planned["rows"] if r["machine"] == a.machine
             and r["sample"] in ("all", "new", "runtime", "sampled")]
    if a.node:
        from offload.engine.provenance import node
        here = node()
        items = [it for it in items if (it.get("node") == here) ==
                 (a.node == "same")]
    if a.shard:
        k, m = (int(v) for v in a.shard.split("/"))
        items = items[k::m]
    out = OUT / a.name / "gate_reruns.jsonl"
    done = {(r["cell"], r["env"]) for r in _jl(out)}
    envs = a.envs.split(",")
    jobs = []
    for it in items:
        es = [e for e in GT.environments(it, a.root or None)
              if e["env"] in envs and (it["cell"], e["env"]) not in done]
        if es:
            jobs.append((it, es))
    print(f"{len(planned['rows'])} failing rows, {len(items)} here, "
          f"{sum(len(j[1]) for j in jobs)} reruns", flush=True)

    def one(job):
        it, es = job
        p = byid[it["ident"]]
        tc = run_matrix.for_version(TOOLCHAINS[it["toolchain"]], p.version,
                                    p.lang)
        res = []
        for e in es:
            rr = GR.rerun_program(p.harness(), tc, int(it["xnack"]), e,
                                  "-O2", timeout_s=a.timeout,
                                  compile_timeout_s=900)
            if os.environ.get("COMPLIANT_RUN_SLOTS"):
                rr["node"] = f"{rr.get('node', '')}:gpu" \
                    f"{os.environ.get('CUDA_VISIBLE_DEVICES', 'all')}"
            res.append({**rr, "cell": it["cell"]})
            _append(out, [res[-1]])
        return res
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        list(pool.map(one, jobs))
    return 0


def verdicts(name: str) -> dict:
    from collections import defaultdict
    from offload.engine import gate as GT
    _register()
    reruns = defaultdict(list)
    for r in _jl(OUT / name / "gate_reruns.jsonl"):
        reruns[r["cell"]].append(r)
    planned = gate_plan(gate_items(name), gate_budget(name))["rows"]
    judged = {}
    for it in planned:
        try:
            judged[it["cell"]] = GT.judge(it, reruns[it["cell"]])
        except ValueError:
            pass
    final = GT.inherit(planned, {c: j["verdict"] for c, j in judged.items()})
    out = {}
    for it in planned:
        c = it["cell"]
        f = final.get(c, {"verdict": "unchecked", "inherited": False})
        rec = {**judged.get(c, {}), **f, "item": it}
        rec["own"] = c in judged and not f.get("inherited") and \
            f["verdict"] == judged[c]["verdict"]
        out[c] = rec
    return out


# --- report -------------------------------------------------------------------------

def _cls(r: dict) -> str:
    from offload.engine import gate as GT
    _register()
    return GT.observe({**r, "kind": "kbody"})[0]


TC_ORDER = ("afar", "cce19", "cce20", "cce21", "cce21_4", "nvhpc",
            "nvhpc269", "gcc_g90", "gcc_sm80")
SHORT = {"correct_on_device": "ok", "wrong_answer": "WA", "rejected": "rej",
         "ice": "ICE", "crash": "crash", "run_error": "run", "timeout": "TO",
         "fell_back_to_host": "host", "accepted_ignored": "ign",
         "harness_error": "harn", "unobservable": "ok"}


def summary(name: str) -> dict:
    from collections import Counter, defaultdict
    ps = {p.id: p for p in programs(name)}
    rs = rows(name)
    by_tc = defaultdict(Counter)
    for r in rs:
        if ps[r["program_id"]].legality != "defined":
            continue
        by_tc[(r["toolchain"], MODE_NAME[r["xnack"]])][_cls(r)] += 1
    v = verdicts(name)
    return {"rows": len(rs), "by_toolchain": {f"{t}|{m}": dict(c) for
                                              (t, m), c in by_tc.items()},
            "gate": dict(Counter(x["verdict"] for x in v.values()))}


def matrix(name: str) -> str:
    v = verdicts(name)
    rs = rows(name)
    cols = sorted({(r["toolchain"], MODE_NAME[r["xnack"]]) for r in rs},
                  key=lambda c: (TC_ORDER.index(c[0]) if c[0] in TC_ORDER
                                 else 99, c[1] != "copy"))
    cell = {}
    for r in rs:
        c = SHORT.get(_cls(r), _cls(r))
        if c != "ok":
            g = v.get(f"kbody|{r['program_id']}|{r['toolchain']}|"
                      f"{r['xnack']}", {}).get("verdict")
            c += "*" if g == "confirmed" else "?" if g else ""
        cell[(r["program_id"], r["toolchain"], MODE_NAME[r["xnack"]])] = c
    head = ["program", "spec"] + [f"{t} {m[0]}" for t, m in cols]
    L = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for p in programs(name):
        L.append("| " + " | ".join(
            [p.id[3:], {"defined": "", "pending": "P", "unspecified": "U",
                        "illegal": "N"}[p.legality]] +
            [cell.get((p.id, t, m), "") for t, m in cols]) + " |")
    return "\n".join(L)


def cmd_report(a) -> int:
    print(json.dumps(summary(a.name), indent=1, sort_keys=True))
    (OUT / a.name / "matrix.md").write_text(matrix(a.name) + "\n")
    print("matrix ->", OUT / a.name / "matrix.md")
    return 0


# --- triage: clusters of failures ------------------------------------------------------

def norm_reason(text: str) -> str:
    import re
    t = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    t = re.sub(r"<tmpdir>|/\S+", "<path>", t)
    t = re.sub(r"\b0x[0-9a-f]+\b", "<addr>", t)
    t = re.sub(r"\d+", "N", t)
    return t[:140]


def row_signature(r: dict) -> str:
    cls = _cls(r)
    if cls == "wrong_answer":
        exp, obs = r.get("expected") or {}, r.get("observed") or {}
        bad = sorted(k for k in exp if obs.get(k) != exp[k])
        return "wrong:" + ",".join(bad) if bad else "wrong:?"
    return f"{cls}:{norm_reason(r.get('reason', ''))}"


def axis_items(p) -> set:
    out = set()
    for k, v in p.axes.items():
        if k in ("constructs", "objects"):
            continue
        for x in (v if isinstance(v, list) else [v]):
            out.add(f"{k}={x}")
    return out


def clusters(name: str) -> list[dict]:
    """Confirmed failures of defined programs grouped by (toolchain, mode,
    signature), with the axis values the members share and the passing
    programs of the same toolchain and mode mostly lack."""
    from collections import Counter, defaultdict
    ps = {p.id: p for p in programs(name)}
    ver = verdicts(name)
    rs = [r for r in rows(name) if ps[r["program_id"]].legality == "defined"]
    ok = defaultdict(list)
    bad = defaultdict(list)
    for r in rs:
        key = (r["toolchain"], MODE_NAME[r["xnack"]])
        cls = _cls(r)
        if cls in ("correct_on_device", "unobservable"):
            ok[key].append(r["program_id"])
        elif cls != "harness_error":
            v = ver.get(f"kbody|{r['program_id']}|{r['toolchain']}|"
                        f"{r['xnack']}", {}).get("verdict")
            bad[key + (row_signature(r),)].append((r["program_id"], v))
    out = []
    for key, members in bad.items():
        tc, mode, sig = key
        ids = [m[0] for m in members]
        mem = [axis_items(ps[i]) for i in ids]
        pas = [axis_items(ps[i]) for i in ok[(tc, mode)]]
        share = []
        for item in sorted(set().union(*mem)):
            f_in = sum(item in m for m in mem) / len(mem)
            f_out = (sum(item in m for m in pas) / len(pas)) if pas else 0
            if f_in >= 0.8 and f_out <= f_in - 0.4:
                share.append((item, round(f_in, 2), round(f_out, 2)))
        out.append({"toolchain": tc, "mode": mode, "signature": sig,
                    "n": len(ids), "confirmed": sum(
                        1 for m in members if m[1] == "confirmed"),
                    "programs": sorted(ids), "discriminators": share})
    return sorted(out, key=lambda c: (-c["n"], c["toolchain"]))


def cmd_cluster(a) -> int:
    cs = clusters(a.name)
    (OUT / a.name / "clusters.json").write_text(json.dumps(cs, indent=1))
    for c in cs:
        print(f"{c['n']:4d} ({c['confirmed']:3d} conf)  {c['toolchain']:9s} "
              f"{c['mode']:8s} {c['signature']}")
        print("        ", "; ".join(f"{i} {f}/{g}" for i, f, g in
                                    c["discriminators"][:8]))
    return 0


# --- the host reference ------------------------------------------------------------

def _host_one(job):
    """Compile with the toolchain, run with OMP_TARGET_OFFLOAD=disabled."""
    import re
    import shutil
    import tempfile
    from pathlib import Path as P
    from offload.engine import harness, run_matrix
    from offload.engine import kbody_gen as G
    from offload.engine.toolchains import TOOLCHAINS
    p, t, timeout_s = job
    tc = run_matrix.for_version(TOOLCHAINS[t], p.version, p.lang)
    tc = harness.dataclasses.replace(tc, model=p.model,
                                     lang="c" if p.lang == "c" else "f90")
    tmp = P(tempfile.mkdtemp(prefix="kbhost_"))
    try:
        src = tmp / f"p.{ext(p)}"
        exe = tmp / "p.out"
        src.write_text(p.source)
        b = harness._execute(harness.compile_script(tc, str(src), str(exe),
                                                    "-O2", str(tmp)),
                             tmp, 900, merge=True)
        if b.rc != 0 or not exe.is_file():
            return {"program_id": p.id, "toolchain": t, "host": "compile_failed",
                    "log": b.stdout[-600:]}
        r = harness._execute(harness.run_script(tc, str(exe), 1, False,
                                                str(tmp), "disabled"),
                             tmp, timeout_s)
        obs = G.parse_observed(r.stdout)
        bad = sorted(k for k in p.expected if obs.get(k) != p.expected[k])
        return {"program_id": p.id, "toolchain": t, "rc": r.rc,
                "host": "agree" if not bad and r.rc == 0 else "differ",
                "bad_keys": bad, "observed": obs,
                "tail": r.stdout[-300:]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def cmd_hostref(a) -> int:
    from concurrent.futures import ThreadPoolExecutor
    out = OUT / a.name / "hostref.jsonl"
    done = {(r["program_id"], r["toolchain"]) for r in _jl(out)}
    tcs = a.toolchains.split(",") if a.toolchains else TARGETS[a.machine][0]
    jobs = [(p, t, a.timeout) for p in programs(a.name) if p.legality ==
            "defined" for t in tcs if (p.id, t) not in done]
    print(len(jobs), "host runs", flush=True)
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        for r in pool.map(_host_one, jobs):
            _append(out, [r])
    return 0


# --- failure rates: one build, many runs ---------------------------------------------

def _rate_one(job):
    """Compile once and run the executable `runs` times in each memory mode;
    a run fails when it prints check=fail (or no RESULT line); the number of
    bad records per run is kept."""
    import re
    import shutil
    import tempfile
    import time
    from pathlib import Path as P
    from offload.engine import harness, run_matrix
    from offload.engine import kbody_gen as G
    from offload.engine.provenance import node
    from offload.engine.toolchains import TOOLCHAINS
    p, t, xs, runs, timeout_s = job
    tc = run_matrix.for_version(TOOLCHAINS[t], p.version, p.lang)
    tc = harness.dataclasses.replace(tc, model=p.model,
                                     lang="c" if p.lang == "c" else "f90")
    tmp = P(tempfile.mkdtemp(prefix="kbrate_"))
    out = []
    try:
        src = tmp / f"p.{ext(p)}"
        exe = tmp / "p.out"
        src.write_text(p.source)
        t0 = time.time()
        b = harness._execute(harness.compile_script(tc, str(src), str(exe),
                                                    "-O2", str(tmp)),
                             tmp, 900, merge=True)
        comp_s = round(time.time() - t0, 1)
        if b.rc != 0 or not exe.is_file():
            return [{"program_id": p.id, "toolchain": t, "xnack": x,
                     "result": "compile_failed", "log": b.stdout[-500:]}
                    for x in xs]
        for x in xs:
            tcx = tc.for_mode(x)
            per, fails = [], 0
            for _ in range(runs):
                r = harness._execute(harness.run_script(tcx, str(exe), x,
                                                        True, str(tmp)),
                                     tmp, timeout_s)
                obs = G.parse_observed(r.stdout)
                fail = not re.search(r"RESULT ran_on_host=0 check=pass",
                                     r.stdout)
                fails += fail
                per.append({"fail": fail, "rc": r.rc, "bad": obs.get("bad"),
                            "dup": obs.get("dup"),
                            "missing": obs.get("missing"),
                            "claimed": obs.get("claimed")})
            out.append({"program_id": p.id, "toolchain": t, "xnack": x,
                        "mode": MODE_NAME[x], "runs": runs, "failing": fails,
                        "per_run": per, "node": node(), "compile_s": comp_s,
                        "compiler": harness.compiler_version(tc),
                        "trials_per_run": p.cfg.trials,
                        "expected": p.expected})
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def cmd_rate(a) -> int:
    from concurrent.futures import ThreadPoolExecutor
    out = OUT / a.name / "rate.jsonl"
    done = {(r["program_id"], r["toolchain"], r["xnack"]) for r in _jl(out)}
    tcs = a.toolchains.split(",") if a.toolchains else TARGETS[a.machine][0]
    xs = [int(m) for m in a.modes.split(",")] if a.modes else \
        TARGETS[a.machine][1]
    ids = set(a.ids.split(",")) if a.ids else None
    jobs = [(p, t, xs, a.runs, a.timeout) for p in programs(a.name, ids)
            if p.legality == "defined" or not a.legal_only for t in tcs
            if any((p.id, t, x) not in done for x in xs)]
    print(len(jobs), "builds,", a.runs, "runs per mode each", flush=True)
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        for rows in pool.map(_rate_one, jobs):
            _append(out, rows)
            for r in rows:
                print(r["program_id"][-8:], r["toolchain"], r.get("xnack"),
                      f"{r.get('failing')}/{r.get('runs')}", flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    g0 = sub.add_parser("gen")
    g0.add_argument("--name", default="main")
    g0.add_argument("--n", type=int, default=360)
    g0.add_argument("--seed", type=int, default=1)
    g0.add_argument("--kind", default="pilot",
                    choices=("pilot", "nbhd", "cfgs", "heap"))
    g0.add_argument("--cfgs")
    g0.add_argument("--base", help="JSON of the base configuration of nbhd")
    for n in ("prerun", "witness", "legality", "report", "cluster"):
        p = sub.add_parser(n)
        p.add_argument("--name", default="main")
        p.add_argument("--workers", type=int, default=8)
    r = sub.add_parser("run")
    r.add_argument("--name", default="main")
    r.add_argument("--machine", required=True, choices=sorted(TARGETS))
    r.add_argument("--toolchains")
    r.add_argument("--modes")
    r.add_argument("--ids")
    r.add_argument("--legal-only", action="store_true")
    r.add_argument("--workers", type=int, default=8)
    r.add_argument("--shard")
    r.add_argument("--timeout", type=int, default=300)
    r.add_argument("--repeats", type=int, default=3)
    r.add_argument("--limit-s", type=float, default=3000)
    g = sub.add_parser("gate")
    g.add_argument("--name", default="main")
    g.add_argument("--machine", required=True, choices=sorted(TARGETS))
    g.add_argument("--envs", default="a,b,c,d")
    g.add_argument("--node", choices=("same", "other"))
    g.add_argument("--shard")
    g.add_argument("--root")
    g.add_argument("--workers", type=int, default=8)
    g.add_argument("--timeout", type=int, default=120)
    g.add_argument("--budget-s", type=float)
    rt = sub.add_parser("rate")
    rt.add_argument("--name", default="main")
    rt.add_argument("--machine", required=True, choices=sorted(TARGETS))
    rt.add_argument("--toolchains")
    rt.add_argument("--modes")
    rt.add_argument("--ids")
    rt.add_argument("--runs", type=int, default=10)
    rt.add_argument("--legal-only", action="store_true")
    rt.add_argument("--workers", type=int, default=4)
    rt.add_argument("--timeout", type=int, default=600)
    h = sub.add_parser("hostref")
    h.add_argument("--name", default="main")
    h.add_argument("--machine", required=True, choices=sorted(TARGETS))
    h.add_argument("--toolchains")
    h.add_argument("--workers", type=int, default=4)
    h.add_argument("--timeout", type=int, default=300)
    a = ap.parse_args(argv)
    return {"rate": cmd_rate, "hostref": cmd_hostref, "gen": cmd_gen, "prerun": cmd_prerun, "witness": cmd_witness,
            "legality": cmd_legality, "run": cmd_run, "gate": cmd_gate,
            "report": cmd_report, "cluster": cmd_cluster}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
