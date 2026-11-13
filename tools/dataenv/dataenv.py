#!/usr/bin/env python3
"""The data-environment catalog (catalog/dataenv_rules.yaml).

Subcommands:

* ``cite [--fill]``: check every citation of the rule table against the
  spec text (results/spec_cache/, printed pages from the page footers).
  ``--fill`` completes a citation written as ``{version, section, quote}``
  with its page and lines (the occurrence in that section), rewriting the
  line in place, so comments and layout stay.
* ``gen [--rules ID,...|--pilot] [--out DIR]``: write the programs of the
  rules (offload.engine.dataenv_gen) and their expected values.
* ``run``: compile and run programs through the harness on the targets,
  then the reproduction gate over the failures.
* ``report``: the per-rule x target x mode table and the go/no-go.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine import dataenv_rules as R  # noqa: E402

_ENTRY = re.compile(r"^(\s*-\s*)\{(.*)\}\s*$")


def _fields(body: str) -> dict:
    """The fields of a one-line flow mapping (the table's citation
    lines)."""
    import yaml
    return yaml.safe_load("{" + body + "}")


def _render(d: dict) -> str:
    def q(v):
        return json.dumps(str(v), ensure_ascii=False)
    return (f"{{version: {q(d['version'])}, section: {q(d['section'])}, "
            f"page: {int(d['page'])}, lines: {q(d['lines'])}, "
            f"quote: {q(d['quote'])}}}")


def fill(path: Path = R.TABLE) -> list[str]:
    """Complete citations without page or lines; returns the problems
    (a quote not found in its section, or found more than once)."""
    out, probs = [], []
    for k, line in enumerate(path.read_text().splitlines(), start=1):
        m = _ENTRY.match(line)
        if m and "quote" in m.group(2) and "version" in m.group(2):
            d = _fields(m.group(2))
            if not d.get("page") or not d.get("lines"):
                hits = [h for h in R.locate(d["version"], d["quote"])
                        if not d.get("section") or
                        str(h["section"]) == str(d["section"])]
                if len(hits) != 1:
                    probs.append(f"line {k}: {len(hits)} places for "
                                 f"{d['version']} §{d.get('section')} "
                                 f"\"{d['quote'][:60]}\"")
                else:
                    h = hits[0]
                    d.update(section=h["section"], page=h["page"],
                             lines=h["lines"])
                    line = m.group(1) + _render(d)
        out.append(line)
    path.write_text("\n".join(out) + "\n")
    return probs


def check(rules: list[dict]) -> list[str]:
    probs = []
    for r in rules:
        for c in r["spec"]:
            for p in R.check_citation(c):
                probs.append(f"{r['id']}: {c.get('version')} "
                             f"§{c.get('section')}: {p}")
    return probs


def cmd_cite(a) -> int:
    if a.fill:
        for p in fill():
            print("fill:", p)
    probs = check(R.load())
    for p in probs:
        print(p)
    print(f"{len(R.load())} rules, {len(probs)} citation problems")
    return 1 if probs else 0


# --- programs -------------------------------------------------------------------------

OUT = ROOT / "results" / "dataenv"
PILOT = ROOT / "catalog" / "dataenv_pilot.yaml"
# the targets and their memory modes (row keys, catalog/machines.yaml);
# managed memory (NVHPC row key 2) is this table's "unified" mode for heap
# data only, so copy-only programs never run there
MODE_NAME = {0: "copy", 1: "unified", 2: "unified"}
TARGETS = {"tuolumne": (["afar", "cce19", "cce20", "cce21"], [0, 1]),
           "tioga": (["afar_g90", "cce19_g90", "cce20_g90", "cce21_g90"],
                     [0]),
           "wingtip": (["nvhpc", "nvhpc269"], [0, 2])}


def pilot() -> dict:
    """rule id -> "near" | "away" (catalog/dataenv_pilot.yaml)."""
    import yaml
    d = yaml.safe_load(PILOT.read_text())
    return {**{e["rule"]: "near" for e in d["near"]},
            **{e["rule"]: "away" for e in d["away"]}}


def select(a) -> list[dict]:
    rules = R.load()
    if getattr(a, "rules", None):
        want = a.rules.split(",")
        return [r for r in rules if r["id"] in want]
    if getattr(a, "all", False):
        return rules
    sel = pilot()
    return [r for r in rules if r["id"] in sel]


def all_programs(rules: list[dict], opposite: bool = False) -> list:
    from offload.engine import dataenv_gen as G
    out = []
    for r in rules:
        out += G.programs(r)
        if opposite:
            out += [m for m in (G.oracle_mutant(r, lang)
                                for lang in r["languages"]) if m]
    return out


def _parts(path: Path) -> list[Path]:
    """`path` and its per-writer parts (``<stem>.part.<node>.<pid>.jsonl``)."""
    return ([path] if path.is_file() else []) + sorted(
        path.parent.glob(f"{path.stem}.part.*{path.suffix}"),
        key=lambda p: (p.stat().st_mtime_ns, p.name))   # oldest first: a retry reads after the row it replaces


def _jl(path: Path) -> list[dict]:
    """The rows of a JSONL file and its per-writer parts; a line that does
    not parse (an interrupted write) is skipped, so its work is redone."""
    out = []
    for p in _parts(path):
        for ln in p.read_text().splitlines():
            if ln.strip():
                try:
                    out.append(json.loads(ln))
                except json.JSONDecodeError:
                    pass
    return out


_LOCK = __import__("threading").Lock()


def _append(path: Path, rows: list[dict]) -> None:
    """Append to this process's own part of `path`: appends from two nodes
    to one file interleave on NFS (Tioga's /p/vast1 did)."""
    import os
    part = path.parent / (f"{path.stem}.part.{os.uname().nodename}."
                          f"{os.getpid()}{path.suffix}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, open(part, "a") as fh:
        fh.write("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))


def cmd_gen(a) -> int:
    import hashlib
    rules = select(a)
    progs = all_programs(rules, opposite=True)
    d = OUT / a.name
    (d / "src").mkdir(parents=True, exist_ok=True)
    rows = []
    for p in progs:
        ext = ".c" if p.lang == "c" else ".f90"
        (d / "src" / (p.id + ext)).write_text(p.source)
        rows.append({"id": p.id, "rule": p.rule, "lang": p.lang,
                     "form": p.form, "model": p.model,
                     "version": p.version, "expected": p.expected,
                     "modes": list(p.modes),
                     "sha": hashlib.sha256(p.source.encode()).hexdigest()})
    (d / "programs.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    print(f"{len(rules)} rules, {len(rows)} programs -> {d}")
    return 0


def _prerun_one(p):
    from offload.engine import dataenv_gen as G
    return G.prerun_check(p)


def cmd_prerun(a) -> int:
    """The pre-run check of every program (both witnesses; AFAR's
    front end is needed: a Tuolumne compute node)."""
    from concurrent.futures import ProcessPoolExecutor
    progs = all_programs(select(a), opposite=True)
    out = OUT / a.name / "prerun.jsonl"
    done = {r["id"] for r in _jl(out)}
    todo = [p for p in progs if p.id not in done]
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        for r in pool.map(_prerun_one, todo):
            _append(out, [r])
    rows = {r["id"]: r for r in _jl(out)}
    bad = [r for r in rows.values() if not r["ok"]]
    for r in bad:
        print("refused", r["id"], "; ".join(r["reasons"])[:300])
    print(f"{len(rows)} checked, {len(bad)} refused")
    return 0


# --- runs ---------------------------------------------------------------------------

def _cells(progs, toolchains, modes, prerun_ok):
    """(program, toolchain, row key) of the runs: a program that passed the
    pre-run check, on a toolchain of its model and language, in a mode its
    expected value holds in."""
    from offload.engine.toolchains import TOOLCHAINS
    out = []
    for p in progs:
        if p.id not in prerun_ok:
            continue
        for t in toolchains:
            tc = TOOLCHAINS[t]
            if p.model == "acc" and (tc.kind == "afar" or
                                     (tc.kind == "cce" and p.lang == "c")):
                continue
            for x in modes:
                if x in tc.xnack_modes and MODE_NAME[x] in p.modes:
                    out.append((p, t, x))
    return out


def _run_one(job):
    import dataclasses
    import time
    from offload.engine import harness, run_matrix
    from offload.engine import dataenv_gen as G
    from offload.engine.toolchains import TOOLCHAINS
    p, t, x, timeout_s = job
    hp = p.harness()
    tc = run_matrix.for_version(TOOLCHAINS[t], p.version, p.lang)
    t0 = time.time()
    try:
        r = harness.run_program(hp, tc, x, "-O2", timeout_s=timeout_s,
                                repeats=3)
        d = dataclasses.asdict(r)
    except Exception as e:          # a harness failure, not the program's
        d = {"program_id": p.id, "toolchain": t, "xnack": x,
             "outcome": "harness_error", "reason": f"harness: {e}"[:300]}
    d.update(campaign="dataenv", rule=p.rule, form=p.form, lang=p.lang,
             mode=MODE_NAME[x], expected=p.expected,
             observed=G.parse_observed(d.get("stdout", "")),
             task_s=round(time.time() - t0, 1))
    d["stdout"] = (d.get("stdout") or "")[-2000:]
    d["stderr"] = (d.get("stderr") or "")[-3000:]
    return d


def cmd_run(a) -> int:
    """Compile and run the programs on this machine's toolchains, through
    the harness (limits, whole-group kill, watchdog), resumable."""
    import time
    from concurrent.futures import ThreadPoolExecutor
    d = OUT / a.name
    ok = {r["id"] for r in _jl(d / "prerun.jsonl") if r["ok"]}
    if not ok:
        print("no program passed the pre-run check: run `prerun` first")
        return 2
    progs = all_programs(select(a), opposite=a.opposite)
    if not a.opposite:
        progs = [p for p in progs if p.form != "opposite"]
    tcs = a.toolchains.split(",") if a.toolchains else \
        TARGETS[a.machine][0]
    modes = [int(m) for m in a.modes.split(",")] if a.modes else \
        TARGETS[a.machine][1]
    out = d / "rows.jsonl"
    done = {(r["program_id"], r["toolchain"], r["xnack"]) for r in _jl(out)}
    jobs = [(p, t, x, a.timeout) for p, t, x in _cells(progs, tcs, modes, ok)
            if (p.id, t, x) not in done]
    if a.shard:
        k, m = (int(v) for v in a.shard.split("/"))
        jobs = jobs[k::m]
    print(f"{len(jobs)} runs to do ({len(done)} done)", flush=True)
    end = time.time() + a.limit_s
    from concurrent.futures import as_completed
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futs = [pool.submit(lambda j=j: None if time.time() > end
                            else _run_one(j)) for j in jobs]
        for f in as_completed(futs):
            r = f.result()
            if r is not None:
                _append(out, [r])
    print("done", flush=True)
    return 0


def _rows(name: str) -> list[dict]:
    """The run's rows, one per (program, toolchain, row key): the last
    written (a cell run again after an interrupted write)."""
    last = {}
    for r in _jl(OUT / name / "rows.jsonl"):
        last[(r["program_id"], r["toolchain"], r["xnack"])] = r
    return list(last.values())


# --- the reproduction gate ----------------------------------------------------------
# The gate (offload.engine.gate, kind "dataenv": build-directory prefix
# dataenv_, signatures per program): environments, gate_run.rerun_program,
# judge, plan and inherit. The trial's budget covers every failing row
#; only a row's own `confirmed` verdict counts
# for the go/no-go, never an inherited or unchecked one.

FAILING = ("correct_on_device", "unobservable", "harness_error")


def gate_items(name: str, machine: str | None = None) -> list[dict]:
    """The failing rows of a run as gate items (one machine, or all)."""
    from offload.engine.gate_stored import machine_of
    out = []
    for r in _rows(name):
        if r["outcome"] in FAILING or r.get("form") == "opposite":
            continue
        m = machine_of(r["toolchain"])
        if machine and m != machine:
            continue
        out.append({**{k: r.get(k) for k in (
            "outcome", "reason", "flaky", "build_dir", "node",
            "toolchain_build", "toolchain", "xnack", "mode")},
            "campaign": "dataenv", "kind": "dataenv", "machine": m,
            "ident": r["program_id"], "opt": "-O2", "timeout_s": 120,
            # the whole program output: the gate keys a dataenv wrong
            # answer by the `name= value` lines it printed
            # (offload.engine.gate.printed_values)
            "stdout": r.get("stdout") or "",
            "compile_log": (r.get("stderr") or "")[-3000:],
            "cell": f"dataenv|{r['program_id']}|{r['toolchain']}|"
                    f"{r['xnack']}", "rule": r["rule"], "form": r["form"],
            "lang": r["lang"]})
    return out


def gate_plan(items: list[dict]) -> dict:
    """offload.engine.gate.plan with a budget that covers every row (a row whose
    own stored repeats disagree is `own`: nondeterministic, not rerun)."""
    from offload.engine import gate as GT
    total = sum(len(GT.ENVS) * GT.cost_s(it) for it in items) + 1
    return GT.plan(items, budget_s=total)


def cmd_gate(a) -> int:
    """Rerun this machine's failing rows in the gate's environments
    (`--envs a,b,d` on the row's node; `--envs c` on another node)."""
    from concurrent.futures import ThreadPoolExecutor
    from offload.engine import gate as GT
    from offload.engine import gate_run as GR
    from offload.engine import run_matrix
    from offload.engine import dataenv_gen as G
    from offload.engine.toolchains import TOOLCHAINS
    rules = R.by_id()
    planned = gate_plan(gate_items(a.name, a.machine))
    (OUT / a.name).mkdir(parents=True, exist_ok=True)
    (OUT / a.name / f"gate_plan.{a.machine}.json").write_text(json.dumps(
        {k: v for k, v in planned.items() if k != "rows"} |
        {"samples": {r["cell"]: r["sample"] for r in planned["rows"]}},
        indent=1, sort_keys=True))
    items = [r for r in planned["rows"] if r["sample"] != "own"]
    if a.node:
        # two-node jobs (tools/jobs/run_dataenv.sh): (a), (b), (d) on the row's
        # own node, (c) on the other
        from offload.engine.provenance import node
        here = node()
        items = [it for it in items if (it.get("node") == here) ==
                 (a.node == "same")]
    if a.shard:
        # by failing row, so that (c) of a shard runs where the other
        # shard's (a), (b), (d) do
        k, m = (int(v) for v in a.shard.split("/"))
        items = items[k::m]
    out = OUT / a.name / "gate_reruns.jsonl"
    done = {(r["cell"], r["env"]) for r in _jl(out)}
    envs = a.envs.split(",")
    root = a.root or None
    # one job per failing row, its environments in order: (a) and (d)
    # build in the same path, so they never run at the same time
    jobs = []
    for it in items:
        es = [e for e in GT.environments(it, root)
              if e["env"] in envs and (it["cell"], e["env"]) not in done]
        if es:
            jobs.append((it, es))
    print(f"{len(planned['rows'])} failing rows, {len(items)} here, "
          f"{sum(len(j[1]) for j in jobs)} reruns", flush=True)

    def one(job):
        it, es = job
        p = G.program(rules[it["rule"]], it["lang"], it["form"])
        tc = run_matrix.for_version(TOOLCHAINS[it["toolchain"]], p.version,
                                    p.lang)
        rows = []
        for e in es:
            rr = GR.rerun_program(p.harness(), tc, int(it["xnack"]), e,
                                  "-O2", timeout_s=a.timeout,
                                  compile_timeout_s=900)
            if os.environ.get("COMPLIANT_RUN_SLOTS"):
                # one host (wingtip): (c) is another GPU (tools/campaigns/gate.py)
                rr["node"] = f"{rr.get('node', '')}:gpu" \
                    f"{os.environ.get('CUDA_VISIBLE_DEVICES', 'all')}"
            rows.append({**rr, "cell": it["cell"]})
            _append(out, [rows[-1]])
        return rows
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        list(pool.map(one, jobs))
    return 0


def verdicts(name: str) -> dict:
    """cell -> the gate's verdict record: offload.engine.gate.judge of the
    row's own reruns, then offload.engine.gate.inherit over the plan (fields
    `verdict`, `inherited`, `own` = the verdict is the row's own)."""
    from collections import defaultdict
    from offload.engine import gate as GT
    reruns = defaultdict(list)
    for r in _jl(OUT / name / "gate_reruns.jsonl"):
        reruns[r["cell"]].append(r)
    planned = gate_plan(gate_items(name))["rows"]
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
        rec = {**judged.get(c, {}), **f, "item": it,
               "sample": it["sample"]}
        rec["own"] = c in judged and not f.get("inherited") and \
            f["verdict"] == judged[c]["verdict"]
        out[c] = rec
    return out


# --- the audits -----------------------------------------------------------------------

def mutation_text(original: str, mutant: str) -> str:
    """The lines a mutant changes ("-old | +new", comments aside): what
    the audit record names as the mutation."""
    import difflib
    out = []
    for ln in difflib.unified_diff(original.splitlines(),
                                   mutant.splitlines(), lineterm="", n=0):
        if ln.startswith(("---", "+++", "@@")):
            continue
        body = ln[1:].strip()
        if body.startswith(("!", "//")) and "$" not in body[:3] and \
                "pragma" not in body:
            continue
        out.append(ln[0] + body)
    return " | ".join(out)[:600]


def backfill_mutations(name: str, src: Path) -> int:
    """Add the `mutation` field to audit rows written before it existed:
    each row's mutant made again from the program sources the run used
    (`src`, written by `gen`: the rule forms and the oracle mutants), with
    the deterministic mutation machinery."""
    from offload.engine import mutate
    from offload.engine import dataenv_gen as G
    from offload.engine.gen import Program as HP
    rows = _jl(OUT / name / "audit.jsonl")
    cache = {}
    for r in rows:
        pid = r["program_id"]
        if pid not in cache:
            lang = "c" if pid.endswith("_c_rule") else "f90"
            ext = ".c" if lang == "c" else ".f90"
            orig = (src / (pid + ext)).read_text()
            muts = {}
            opp = src / (pid[:-len("_rule")] + "_opposite" + ext)
            if opp.is_file():
                muts["oracle"] = opp.read_text()
            hp = HP(id=pid, lang=lang, source=orig, atoms=frozenset(),
                    primary_atom=f"dataenv.{r['rule']}", legal=True,
                    violates=None, observable=True,
                    model=pid.split("-")[0][:3])
            try:
                for k, m in mutate.map_mutants(hp).items():
                    muts[f"map:{k}"] = m.source
            except Exception:
                pass
            cache[pid] = (orig, muts)
        o, muts = cache[pid]
        r["mutation"] = mutation_text(o, muts[r["kind"]]) \
            if r["kind"] in muts else "(not regenerated)"
    (OUT / name / "audit.jsonl").write_text("".join(
        json.dumps(r, sort_keys=True) + "\n" for r in rows))
    return len(rows)


def cmd_audit(a) -> int:
    """The oracle audit (each rule form's oracle mutant: the control with
    the opposite attribute, offload.engine.dataenv_gen.oracle_mutant) and the
    map audit (offload.engine.mutate.map_mutants of each rule form), each run
    with its original on the audit toolchains in both modes, one repeat,
    classified by offload.engine.mutate.classify."""
    import dataclasses
    from concurrent.futures import ThreadPoolExecutor
    from offload.engine import harness, mutate, run_matrix
    from offload.engine import dataenv_gen as G
    from offload.engine.toolchains import TOOLCHAINS
    d = OUT / a.name
    ok = {r["id"] for r in _jl(d / "prerun.jsonl") if r["ok"]}
    rules = select(a)
    jobs = []
    for r in rules:
        for lang in r["languages"]:
            orig = G.program(r, lang, "rule")
            if orig.id not in ok:
                continue
            muts = {}
            om = G.oracle_mutant(r, lang)
            if om is not None:
                muts["oracle"] = om.harness()
            try:
                for k, m in mutate.map_mutants(orig.harness()).items():
                    muts[f"map:{k}"] = m
            except Exception as e:          # the mutation machinery's limit
                print("no map mutants:", orig.id, str(e)[:120])
            for t in a.toolchains.split(","):
                tc = TOOLCHAINS[t]
                if orig.model == "acc" and (tc.kind == "afar" or (
                        tc.kind == "cce" and lang == "c")):
                    continue
                for x in [int(m) for m in a.modes.split(",")]:
                    if MODE_NAME[x] not in orig.modes or \
                            x not in tc.xnack_modes:
                        continue
                    for kind, m in muts.items():
                        jobs.append((r["id"], orig, kind, m, t, x))
    out = d / "audit.jsonl"
    done = {(j["program_id"], j["kind"], j["toolchain"], j["xnack"])
            for j in _jl(out)}
    jobs = [j for j in jobs if (j[1].id, j[2], j[4], j[5]) not in done]
    import threading
    cache, locks, guard = {}, {}, threading.Lock()

    def run(prog, t, x, version, lang):
        tc = run_matrix.for_version(TOOLCHAINS[t], version, lang)
        return harness.run_program(prog, tc, x, "-O2", timeout_s=a.timeout,
                                   repeats=1)

    import time
    end = time.time() + a.limit_s

    def one(j):
        rid, orig, kind, m, t, x = j
        if time.time() > end:
            return None
        key = (orig.id, t, x)
        with guard:
            lk = locks.setdefault(key, threading.Lock())
        with lk:
            if key not in cache:
                cache[key] = run(orig.harness(), t, x, orig.version,
                                 orig.lang)
        o = cache[key]
        mr = run(m, t, x, orig.version, orig.lang)
        status, reason, kk = mutate.classify(o, mr)
        return {"rule": rid, "program_id": orig.id, "kind": kind,
                "mutation": mutation_text(orig.source, m.source),
                "toolchain": t, "xnack": x, "mode": MODE_NAME[x],
                "status": status, "reason": reason[:300], "kill_kind": kk,
                "original": str(o.outcome), "mutant": str(mr.outcome)}
    print(f"{len(jobs)} audit runs", flush=True)
    from concurrent.futures import as_completed
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        for f in as_completed([pool.submit(one, j) for j in jobs]):
            if f.result() is not None:
                _append(out, [f.result()])
    return 0


# --- the report ----------------------------------------------------------------------

def family(tc: str) -> str:
    from offload.engine.toolchains import TOOLCHAINS
    return TOOLCHAINS[tc].kind


def summary(name: str) -> dict:
    """Per rule x target x mode outcomes, the gate's verdicts, the new
    wrong-answer signatures (rule, compiler family) and the task CPU-hours
    of the near and away halves."""
    from collections import Counter, defaultdict
    rows = _rows(name)
    ver = verdicts(name)
    sel = pilot()
    cells = defaultdict(dict)
    hours = Counter()
    sigs = defaultdict(set)
    for r in rows:
        if r.get("form") == "opposite":
            continue
        half = sel.get(r["rule"], "rest")
        hours[half] += (r.get("task_s") or 0) / 3600
        cell = f"dataenv|{r['program_id']}|{r['toolchain']}|{r['xnack']}"
        v = ver.get(cell, {}).get("verdict", "" if r["outcome"] in FAILING
                                  else "ungated")
        cells[(r["rule"], r["form"], r["lang"])][
            (r["toolchain"], r["mode"])] = (r["outcome"], v)
        vr = ver.get(cell, {})
        if r["form"] == "rule" and r["outcome"] == "wrong_answer" and \
                str(r.get("reason", "")).startswith("check_fail") and \
                vr.get("verdict") == "confirmed" and vr.get("own"):
            sigs[half].add((r["rule"], family(r["toolchain"])))
    return {"cells": cells, "hours": dict(hours),
            "signatures": {k: sorted(v) for k, v in sigs.items()},
            "verdicts": ver}


def _short(tc: str) -> str:
    return tc.replace("_g90", "g").replace("nvhpc269", "nv269")


def render(name: str) -> str:
    """The results tables (markdown): per rule and form, every target and
    mode as outcome/verdict; the defects by the pre-registered counting;
    the rows that need a legality or determinism review; the audits."""
    from collections import Counter, defaultdict
    s = summary(name)
    rows = [r for r in _rows(name) if r.get("form") != "opposite"]
    ver = s["verdicts"]
    sel = pilot()
    cols = sorted({(r["toolchain"], r["mode"]) for r in rows},
                  key=lambda c: (c[0].startswith("nv"), c[0], c[1]))
    abbrev = {"correct_on_device": "ok", "wrong_answer": "WA",
              "rejected": "rej", "harness_error": "herr",
              "fell_back_to_host": "host", "accepted_ignored": "ign"}
    vab = {"confirmed": "c", "not_reproduced": "nr", "nondeterministic":
           "nd", "environment": "env", "unchecked": "u", "illegal": "ill",
           "not_a_failure": "naf", "ungated": "?"}
    out = ["| rule | form | lang | " + " | ".join(
        f"{_short(t)} {m[0]}" for t, m in cols) + " |",
        "|" + "---|" * (3 + len(cols))]
    by = defaultdict(dict)
    for r in rows:
        cell = f"dataenv|{r['program_id']}|{r['toolchain']}|{r['xnack']}"
        o = abbrev.get(r["outcome"], r["outcome"])
        if r["outcome"] == "wrong_answer" and not str(
                r.get("reason", "")).startswith("check_fail"):
            o = "crash" if "crash" in r.get("reason", "") else "err"
        if r["outcome"] not in FAILING:
            v = ver.get(cell, {})
            o += "/" + vab.get(v.get("verdict", "ungated"), "?") + (
                "*" if v and not v.get("own") else "")
        by[(r["rule"], r["form"], r["lang"])][(r["toolchain"],
                                               r["mode"])] = o
    order = [x for x in pilot()]
    for key in sorted(by, key=lambda k: (order.index(k[0]) if k[0] in
                                         order else 999, k[2], k[1])):
        out.append(f"| {key[0]} | {key[1]} | {key[2]} | " + " | ".join(
            by[key].get(c, "") for c in cols) + " |")
    out.append("")
    out.append(f"Task CPU-hours (rule forms and controls): " + ", ".join(
        f"{k} {v:.2f}" for k, v in sorted(s["hours"].items())))
    for half in ("near", "away"):
        sig = s["signatures"].get(half, [])
        out.append(f"- {half}: {len(sig)} (rule, family) with an own "
                   f"confirmed check_fail: " + ", ".join(
                       f"{r} {f}" for r, f in sig))
    rv = Counter(v["verdict"] for v in ver.values())
    out.append(f"- gate verdicts over {len(ver)} failing rows: " +
               ", ".join(f"{k} {n}" for k, n in rv.most_common()))
    aud = _jl(OUT / name / "audit.jsonl")
    if aud:
        c = Counter((a["kind"].split(":")[0], a["mode"], a["status"])
                    for a in aud)
        out.append("- audits: " + ", ".join(
            f"{k[0]} {k[1]} {k[2]} {n}" for k, n in sorted(c.items())))
    return "\n".join(out) + "\n"


def cmd_report(a) -> int:
    s = summary(a.name)
    for k, v in sorted(s["signatures"].items()):
        print(k, len(v), v)
    print("task CPU-hours:", {k: round(v, 2) for k, v in s["hours"].items()})
    out = OUT / a.name / "summary.json"
    out.write_text(json.dumps({
        "hours": s["hours"], "signatures": s["signatures"],
        "cells": {"|".join(k): {"|".join(c): list(o) for c, o in v.items()}
                  for k, v in s["cells"].items()},
        "verdicts": {c: {k: v for k, v in d.items() if k != "item"}
                     for c, d in s["verdicts"].items()}},
        indent=1, sort_keys=True))
    (OUT / a.name / "report.md").write_text(render(a.name))
    print("->", out, OUT / a.name / "report.md")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cite")
    c.add_argument("--fill", action="store_true")
    c.set_defaults(func=cmd_cite)

    def sel(p):
        p.add_argument("--name", default="pilot")
        g = p.add_mutually_exclusive_group()
        g.add_argument("--rules", help="rule ids, comma separated")
        g.add_argument("--all", action="store_true", help="every rule")
    g = sub.add_parser("gen")
    sel(g)
    g.set_defaults(func=cmd_gen)
    p = sub.add_parser("prerun")
    sel(p)
    p.add_argument("--workers", type=int, default=16)
    p.set_defaults(func=cmd_prerun)
    r = sub.add_parser("run")
    sel(r)
    r.add_argument("--machine", choices=sorted(TARGETS), default="tuolumne")
    r.add_argument("--toolchains")
    r.add_argument("--modes")
    r.add_argument("--workers", type=int, default=16)
    r.add_argument("--timeout", type=int, default=120)
    r.add_argument("--limit-s", type=int, default=3000)
    r.add_argument("--shard")
    r.add_argument("--opposite", action="store_true",
                   help="also the oracle mutants (the audit runs them)")
    r.set_defaults(func=cmd_run)
    q = sub.add_parser("gate")
    sel(q)
    q.add_argument("--machine", choices=sorted(TARGETS), default="tuolumne")
    q.add_argument("--envs", default="a,b,d")
    q.add_argument("--workers", type=int, default=16)
    q.add_argument("--timeout", type=int, default=120)
    q.add_argument("--shard")
    q.add_argument("--root", help="the gate's build root (default: "
                   "offload.engine.gate.gate_tmp)")
    q.add_argument("--node", choices=("same", "other"),
                   help="only the rows run on this node (same) or on "
                        "another (other)")
    q.set_defaults(func=cmd_gate)
    u = sub.add_parser("audit")
    sel(u)
    u.add_argument("--toolchains", default="afar,cce19")
    u.add_argument("--modes", default="0,1")
    u.add_argument("--workers", type=int, default=16)
    u.add_argument("--timeout", type=int, default=120)
    u.add_argument("--limit-s", type=int, default=3000)
    u.set_defaults(func=cmd_audit)
    o = sub.add_parser("report")
    sel(o)
    o.set_defaults(func=cmd_report)
    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
