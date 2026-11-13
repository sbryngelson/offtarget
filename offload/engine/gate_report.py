"""Reproduction gate verdicts over the stored campaigns (tools/campaigns/gate.py report).

Reads results/gate/<campaign>/plan.jsonl (offload.engine.gate_stored items) and
results/gate/<campaign>/reruns/*.jsonl (offload.engine.gate_run rows). Writes:

* results/gate/verdicts.jsonl: one record per planned row (``cell``,
  ``campaign``, ``kind``, ``ident``, ``toolchain``, ``xnack``, ``mode``,
  ``signature``, ``verdict``, ``inherited``, ``legality_review``, ``original``,
  ``reclassified``, ``condition``, ``complete``);
* data/reports/gate-changes/<campaign>.tsv: rows whose outcome changed;
* the gate report: counts by verdict per campaign, the cost, and the review
  queue with each entry's checklist and pre-run check.

The original row is first read with the current message tables
(``reclassify``)."""
from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from pathlib import Path

from offload.engine import gate as G

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "results" / "gate"
DOC = ROOT / "data" / "reports" / "gate.md"
CHANGES = ROOT / "data" / "reports" / "gate-changes"
COMPILE = ("rejected", "ice", "accepted_ignored", "harness_error")


def _jl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text().splitlines()
            if x.strip()]


def reclassify(item: dict) -> dict:
    """The item with its compile failure read by the current message
    tables (``outcome``/``cls`` and ``reason`` replaced; ``reclassified``
    holds the old class and reason) when that changes its class
    (offload.engine.gate.reread)."""
    cls = G.outcome_class(item)
    if cls == "accepted_ignored":
        return item
    lang = "c" if "-c-" in str(item.get("ident", "")) or \
        str(item.get("ident", "")).endswith(".c") or \
        (item.get("locator") or {}).get("lang") == "c" else "f90"
    got = G.reread(item["toolchain"], cls, item.get("reason") or "",
                   item.get("compile_log") or "", lang)
    if got is None:
        return item
    new_cls, reason = got
    out = dict(item)
    out["reclassified"] = {"outcome": cls, "reason": item.get("reason")}
    if "cls" in out:
        out["cls"] = {"ice": "ice", "rejected": "compile_reject",
                      "harness_error": "harness_error"}[new_cls]
    else:
        out["outcome"] = "rejected" if new_cls in ("ice", "rejected") else \
            new_cls
    out["reason"] = reason
    return out


def _reruns(camp: str) -> dict:
    """cell -> every rerun of it (every valid run of an
    environment is kept, so a resumed chunk's earlier run that disagreed
    still counts; an invalid run is dropped when its environment has a
    valid one)."""
    by = defaultdict(list)
    for p in sorted((OUT / camp / "reruns").glob("*.jsonl")):
        for r in _jl(p):
            by[r["cell"]].append(r)
    out = {}
    for cell, rs in by.items():
        good = {r["env"] for r in rs if G.outcome_class(r) not in
                G.NOT_EVIDENCE and not G.killed(r)}
        out[cell] = [r for r in rs if r["env"] not in good or (
            G.outcome_class(r) not in G.NOT_EVIDENCE and not G.killed(r))]
    return out


def illegal_cells(camp: str) -> dict:
    """cell -> why: the programs the static rules pass found illegal
    (results/gate/<camp>/illegal.jsonl, ``tools/campaigns/gate.py rules-pass``:
    offload.engine.prerun's rules witness, no front end)."""
    return {d["cell"]: d["why"] for d in _jl(OUT / camp / "illegal.jsonl")
            if d.get("why")}


RUN_TIME = ("wrong_answer", "crash", "run_error", "timeout",
            "fell_back_to_host", "unobservable")


def _rules_one(e):
    key, item = e
    from offload.engine import prerun as PR
    try:
        prog = _program_of(None, item)
        if prog is None:
            return key, None, []
        ok, why = PR.rules_witness(prog)
        return key, ok, why
    except Exception as ex:          # recorded, never dropped
        return key, None, [f"rules pass failed: {ex!r}"[:200]]


def rules_pass(camp: str, workers: int = 16) -> dict:
    """The static rules witness (offload.engine.prerun.rules_witness:
    offload.engine.rules, EXTRA, the race rule; no front end) over the
    programs of a campaign's failing rows. A program that violates a
    restriction rule makes every failure of it ``illegal``; a race makes
    only its run-time failures ``illegal`` (a compile does not depend on
    the race). Writes results/gate/<camp>/illegal.jsonl ({cell, why});
    returns counts."""
    import multiprocessing as mp
    items = _jl(OUT / camp / "plan.jsonl")
    by_prog: dict = {}
    for it in items:
        loc = {k: v for k, v in (it.get("locator") or {}).items()
               if k not in ("toolchain", "mode", "run", "variant",
                            "limits")}
        by_prog.setdefault(json.dumps([it["kind"], loc], sort_keys=True,
                                      default=str), it)
    res = {}
    with mp.get_context("fork").Pool(workers) as pool:
        for key, ok, why in pool.imap_unordered(_rules_one,
                                                list(by_prog.items()), 8):
            res[key] = (ok, why)
    out, n = [], Counter()
    for it in items:
        loc = {k: v for k, v in (it.get("locator") or {}).items()
               if k not in ("toolchain", "mode", "run", "variant",
                            "limits")}
        ok, why = res.get(json.dumps([it["kind"], loc], sort_keys=True,
                                     default=str), (None, []))
        if ok is not False:
            n["legal" if ok else "unread"] += 1
            continue
        rules = [w for w in why if not w.startswith("race:")]
        races = [w for w in why if w.startswith("race:")]
        if rules or (races and G.outcome_class(it) in RUN_TIME):
            out.append({"cell": it["cell"],
                        "why": "; ".join((rules or races)[:3])[:600]})
            n["illegal"] += 1
        else:
            n["race_compile_failure_kept"] += 1
    with (OUT / camp / "illegal.jsonl").open("w") as fh:
        for d in out:
            fh.write(json.dumps(d) + "\n")
    return dict(n)


def judge_campaign(camp: str) -> tuple[list[dict], dict]:
    """(verdict records, stats) of one campaign, under the fix-round-1
    semantics: a row is judged on its own reruns; without one, a row whose
    stored repeats disagree is nondeterministic, an inheritable
    compile-time failure takes its signature's worst verdict, any other
    row is unchecked; a program the rules pass found illegal is illegal."""
    plan = _jl(OUT / camp / "plan.jsonl")
    reruns = _reruns(camp)
    bad = illegal_cells(camp)
    decided = G.load_decisions()
    recs, own = [], {}
    stats = Counter()
    seconds = Counter()
    items = []
    for item in plan:
        item = dict(item)
        item.pop("signature", None)        # recomputed: new signatures
        item["signature"] = G.signature(item)
        items.append(item)
        it = reclassify(item)
        base = {k: it.get(k) for k in ("cell", "campaign", "kind", "ident",
                                       "toolchain", "xnack", "mode",
                                       "machine", "signature", "sample")}
        base["original"] = "|".join(G.observe(item))[:200]
        if "reclassified" in it:
            base["reclassified"] = "|".join(G.observe(it))[:200]
            stats["reclassified"] += 1
        rs = reruns.get(item["cell"], [])
        for r in rs:
            seconds[item["machine"]] += float(r.get("seconds") or 0)
        # the reruns read with the current tables too (a rerun of an
        # earlier round and one of today compare by the same reading)
        rs = [reclassify({**r, "toolchain": item["toolchain"],
                          "kind": item.get("kind"),
                          "ident": item.get("ident"),
                          "locator": item.get("locator")})
              for r in rs]
        if not G.is_failure(G.outcome_class(it)):
            # read today, the stored row is no failure (a capacity limit
            # the runtime reports: offload.engine.harness.CAPACITY)
            base.update({"verdict": "not_a_failure", "inherited": False,
                         "legality_review": False})
            own[item["cell"]] = "not_a_failure"
            recs.append(base)
            continue
        try:
            j = G.judge(it, rs)
        except ValueError:
            recs.append(base)
            continue
        own[item["cell"]] = j["verdict"]
        base.update({"verdict": j["verdict"], "inherited": False,
                     "legality_review": j["legality_review"],
                     "complete": not j["missing"], "missing": j["missing"],
                     "node_distinct": j["node_distinct"],
                     "reruns": j["reruns"]})
        for k in ("condition", "changed_since", "own_repeats"):
            if k in j:
                base[k] = j[k]
        if j.get("own_repeats") and not j["reruns"]:
            stats["own_not_rerun"] += 1
        recs.append(base)
    # rows without a verdict of their own: inherit or unchecked (the
    # gate's own verdicts only: a decision never propagates)
    # (a row nondeterministic on its own repeats without a
    # rerun is "own": its verdict never passes on)
    rerun_cells = {r["cell"] for r in recs if r.get("reruns")}
    for item in items:
        if item["cell"] in rerun_cells:
            item["sample"] = "rerun"
        elif item["cell"] in own:
            item["sample"] = "own"
        else:
            item["sample"] = "inherited" if G.inheritable(item) else \
                "unchecked"
    inh = G.inherit(items, own)
    for r in recs:
        if r.get("verdict") is None:
            v = inh.get(r["cell"]) or {"verdict": "unchecked"}
            r.update({"verdict": v["verdict"],
                      "inherited": bool(v.get("inherited")),
                      "legality_review": v["verdict"] in G.REVIEW})
            if v.get("inherited"):
                r["from"] = v.get("from", 0)
            if v.get("own_repeats"):
                r["own_repeats"] = True
        if r["cell"] in bad:
            r.update({"verdict": "illegal", "illegal": bad[r["cell"]],
                      "legality_review": False})
        d = decided.get(r["cell"])
        if d and not r.get("inherited"):
            # The decision: on the row it names only (never on the
            # rows that inherit from it); the row leaves the queue
            r.update(d)
            r["legality_review"] = False
            stats["decided"] += 1
    # The store's `sample` is how the row got its verdict
    # (rerun, own, inherited, unchecked), not the round-0 plan's
    label = {it["cell"]: it["sample"] for it in items}
    for r in recs:
        r["sample"] = label.get(r["cell"], r.get("sample"))
    stats.update(f"{'inherited ' if r.get('inherited') else ''}"
                 f"{r.get('verdict')}" for r in recs)
    stats["rows"] = len(plan)
    stats["rerun_rows"] = sum(1 for r in recs if r.get("reruns"))
    stats["complete"] = sum(1 for r in recs if r.get("complete"))
    return recs, {"counts": dict(stats), "seconds": dict(seconds)}


def _short(text: str, n: int = 90) -> str:
    return " ".join(str(text or "").split())[:n].replace("\t", " ")


def write_changes(camp: str, recs: list[dict]) -> int:
    """data/reports/gate-changes/<camp>.tsv: every reclassified row."""
    CHANGES.mkdir(parents=True, exist_ok=True)
    head = ["cell", "signature", "old_outcome", "verdict", "inherited",
            "new_outcome", "condition", "decision", "counts"]
    lines = ["\t".join(head)]
    for r in sorted(recs, key=lambda r: r["cell"]):
        # an unchecked row keeps its outcome: not a reclassification (it
        # is counted in the gate report); a decided row is listed
        # with its decision
        changed = (r.get("verdict") not in (None, "confirmed",
                                            "unchecked")) or \
            r.get("reclassified") or r.get("decision")
        if not changed:
            continue
        if r.get("inherited"):
            new = f"inherited from {r.get('from', 0)} rerun row(s) of its " \
                "signature"
        elif r.get("reruns"):
            new = " ".join(f"{x['env']}:{x['outcome'].split('|')[0]}"
                           for x in r["reruns"])
        else:
            new = ""
        if r.get("reclassified"):
            new = f"classifier: {r['reclassified']}" + (f"; {new}" if new
                                                         else "")
        lines.append("\t".join([r["cell"], _short(r.get("signature"), 120),
                                _short(r["original"], 120),
                                str(r.get("verdict")),
                                "yes" if r.get("inherited") else "no",
                                _short(new, 200),
                                _short(r.get("condition", ""), 300),
                                str(r.get("decision") or ""),
                                "yes" if G.counts(r) else "no"]))
    (CHANGES / f"{camp}.tsv").write_text("\n".join(lines) + "\n")
    return len(lines) - 1


def _program_of(rec: dict, item: dict):
    """The program text (and lang) of a queue entry, for prerun.check."""
    from offload.engine import gate_stored as GS
    kind, loc = item["kind"], item["locator"]
    if kind in ("catalog", "widen"):
        p = GS._catalog_prog(loc["pid"])
        if p is None:
            return None
        from offload.engine.confirm.programs import version_of_id
        return (p.source, "c" if p.lang == "c" else "f90", p.model,
                version_of_id(loc["pid"]) or 52)
    if kind == "fuzz":
        from offload.engine.fuzz import generate
        g = generate(loc["seed"], loc["gen_version"],
                     tuple(loc.get("base") or ()))
        return (g.source, "f90", "omp")
    if kind == "stress":
        return GS.stress_program(loc)
    if kind == "evidence":
        text = (OUT / "evidence" / "programs" / f"{loc['sha']}.txt"
                ).read_text()
        return (text, loc["ref"].get("lang", "f90"),
                loc["ref"].get("model", "omp"))
    return None


def _prerun_one(e):
    rec, item = e
    from offload.engine import prerun as PR
    try:
        prog = _program_of(rec, item)
        if prog is None:
            return rec["cell"], (None, ["program not rebuilt"])
        # a front end that takes over two minutes is no witness here
        return rec["cell"], PR.check(prog, timeout_s=120)
    except Exception as ex:      # recorded, never dropped
        return rec["cell"], (None, [f"check failed: {ex!r}"[:200]])


def prerun_of(entries: list[tuple], workers: int = 16,
              limit_s: int = 300) -> dict:
    """cell -> (ok, reasons) of the pre-run check of each queue entry's
    program (both witnesses: a compute node with AFAR), in worker
    processes; a check that takes over `limit_s` (the rules on a very
    large stress program) is not decided."""
    import multiprocessing as mp
    import time
    out = {}
    pool = mp.get_context("fork").Pool(workers)
    try:
        jobs = [(e[0]["cell"], pool.apply_async(_prerun_one, (e,)))
                for e in entries]
        t0 = time.time()
        for cell, j in jobs:
            left = max(1.0, limit_s + t0 - time.time() +
                       limit_s * len(entries) / workers)
            try:
                out[cell] = j.get(timeout=left)[1]
            except mp.TimeoutError:
                out[cell] = (None, [f"the check took over {limit_s} s"])
    finally:
        pool.terminate()
        pool.join()
    return out


BATCHES = ("results/confirm/batch_full.jsonl",
           "results/confirm/batch_s1.final.jsonl",
           "results/confirm/batch_widen.jsonl",
           # the batches before the gate's rule R04b: a cell the gate did
           # not confirm is needs_human now, and the confirmer links a
           # finding only to a bug verdict, so its link is read there
           "results/confirm/batch_full.pre-t45.jsonl",
           "results/confirm/batch_s1.final.pre-t45.jsonl",
           "results/confirm/batch_widen.pre-t45.jsonl")


def _case_id(kind: str, ident: str, tc: str, mode: str) -> str:
    import re
    from offload.engine.toolchains import TOOLCHAINS
    k = "catalog" if kind in ("catalog", "widen") else kind
    i = re.sub(r"[^A-Za-z0-9_.:-]", "_", str(ident))
    return f"{k}:{i}:{tc}:{TOOLCHAINS[tc].arch}:{mode}"


def finding_links() -> dict:
    """case id -> the finding files the confirmer's batches link to the
    cell (an instance of the finding)."""
    out: dict = {}
    for name in BATCHES:
        for d in _jl(ROOT / name):
            fs = [f["file"] for f in d.get("findings") or ()]
            if fs:
                out.setdefault(d["case"]["case_id"], fs)
    return out


def _stress_links(items: list[dict]) -> dict:
    """cell -> finding files of the stress rows (the confirmer's dedupe
    on the stress program's text: the batches do not hold stress rows)."""
    from offload.engine import gate_stored as GS
    from offload.engine.confirm import findings as FI
    from offload.engine.toolchains import TOOLCHAINS
    out, texts = {}, {}
    for it in items:
        loc = it["locator"]
        if loc["id"] not in texts:
            p = GS.stress_program(loc)
            texts[loc["id"]] = "\n".join(t for _, t in p.files) if p \
                else ""
        cls, _ = G.observe(it)
        hits = FI.dedupe(it["toolchain"], loc.get("lang", "f90"), cls,
                         it.get("reason") or "", texts[loc["id"]],
                         it["ident"], it["mode"],
                         arch=TOOLCHAINS[it["toolchain"]].arch,
                         output=it.get("compile_log") or "",
                         build_dir=it.get("build_dir") or "",
                         opt=it.get("variant") or "")
        dups = [h["file"] for h in hits if h["kind"] == "duplicate"]
        if dups:
            out[it["cell"]] = dups[:1]
    return out


def findings_affected(recs: list[dict]) -> dict:
    """finding file -> Counter of the gate verdicts of the cells linked to
    it (``inherited`` verdicts marked so), for every finding with a
    linked cell."""
    links = finding_links()
    stress = [it for it in _jl(OUT / "stress" / "plan.jsonl")]
    slinks = _stress_links(stress) if stress else {}
    out: dict = defaultdict(Counter)
    for r in recs:
        if r.get("kind") in ("evidence",) or not r.get("verdict"):
            continue
        if r.get("kind") == "stress":
            files = slinks.get(r["cell"], [])
        else:
            files = links.get(_case_id(r["kind"], r["ident"], r["toolchain"],
                                       r["mode"]), [])
        for f in files[:1]:
            out[f][("inherited " if r.get("inherited") else "")
                   + r["verdict"]] += 1
            if r.get("decision"):
                out[f]["decided " + str(r.get("counts_as"))] += 1
            if not G.counts(r):
                out[f]["not counting"] += 1
    return dict(out)


def _questioned(c: Counter) -> bool:
    """A finding to review: a linked cell no longer counts, or no linked
    cell was confirmed (own or inherited) or counted by a decision."""
    if c.get("not counting"):
        return True
    return not (c.get("confirmed") or c.get("inherited confirmed") or
                c.get("decided failure"))


CHECKLIST = (
    "- legality: [ ] the spec text of the program's version requires the "
    "expected result; [ ] two witnesses that are not the compiler under "
    "test accept it (pre-run check above); [ ] the construct is not one "
    "another environment may legally treat differently",
    "- determinism: [ ] no read of uninitialised memory; [ ] no clock, "
    "timing or thread-count dependence; [ ] no dependence on device memory "
    "left by an earlier run; [ ] no data race the race rule missed",
    "- environment (environment verdicts): [ ] the condition is named and "
    "reproduced on purpose (as did for the CCE CIF split)")


def report(camps, prerun: bool = True, write: bool = True) -> dict:
    """Judge every campaign, write the verdicts, the change logs and
    the gate report; the summary dict."""
    all_recs, summary = [], {}
    items_by_cell = {}
    for camp in camps:
        if not (OUT / camp / "plan.jsonl").is_file():
            continue
        recs, st = judge_campaign(camp)
        for it in _jl(OUT / camp / "plan.jsonl"):
            items_by_cell[it["cell"]] = it
        plan = json.loads((OUT / camp / "plan.json").read_text())
        st["plan"] = plan
        st["changes"] = write_changes(camp, recs) if write else 0
        summary[camp] = st
        all_recs += recs
    queue = [r for r in all_recs if r.get("legality_review") and
             not r.get("inherited") and not r.get("decision")]
    queue.sort(key=lambda r: (G.WORST_FIRST.index(r["verdict"]),
                              r["campaign"], r["signature"] or "",
                              r["cell"]))
    pr = prerun_of([(r, items_by_cell[r["cell"]]) for r in queue]) \
        if prerun else {}
    affected = findings_affected(all_recs)
    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        with (OUT / "verdicts.jsonl").open("w") as fh:
            for r in all_recs:
                if r.get("verdict") is not None:
                    fh.write(json.dumps({k: v for k, v in r.items()
                                         if k != "reruns"}) + "\n")
        DOC.write_text(render(summary, queue, pr, all_recs, affected))
        (OUT / "findings_affected.json").write_text(json.dumps(
            {f: dict(c) for f, c in sorted(affected.items())}, indent=1)
            + "\n")
    return {"summary": summary, "queue": len(queue),
            "new_queue": [r["cell"] for r in queue],
            "affected": {f: dict(c) for f, c in affected.items()
                         if _questioned(c)}}


# Diagnostic
# candidates the gate's review found, recorded without a finding
LOWER_TIER = (
    "NVHPC diagnostic: NVHPC attributes an `omp_is_initial_device()` call "
    "before a `loop` to the loop (S-1224, \"LOOP construct may not contain "
    "calls to the OpenMP Runtime API\"). Fuzz program n0x0:5 "
    "(generator fuzz-4s50, seed 5; cells fuzz|n0x0:5|nvhpc|0 and "
    "fuzz|n0x0:5|nvhpc269|0): the call `hf4 = merge(1, 0, "
    "omp_is_initial_device())` is line 98, in the target region of line "
    "97, before `!$omp parallel` (line 99) and the `!$omp loop` region of "
    "lines 100-105, which calls no runtime routine; NVHPC 25.11 and 26.9 "
    "report S-1224 at line 98. The static rules pass "
    "(order_concurrent_no_api_calls) finds no runtime call inside a loop "
    "region in any of the 138 stored fuzz programs whose rows carry "
    "S-1224 (184 rows). The rows are kept (rejections). Not reduced; no "
    "finding yet.",
)


# The cost model's estimate (offload.engine.gate.cost_s over
# tools/campaigns/gate.py RERUNS_PER_GPU, uncalibrated) beside the busy GPU-hours the
# ledgers measured, per job and machine; tools/campaigns/gate.py CALIBRATION follows
COST_MEASURED = (
    # (job, campaign, machine, rows, model GPU-h, measured busy GPU-h)
    ("(c) only", "catalog+widen", "tuolumne", 928, 3.9, 1.60),
    ("(c) only", "catalog+widen", "tioga", 804, 3.4, 0.95),
    ("(c) only", "catalog+widen", "wingtip", 529, 3.2, 0.54),
    ("(c) only", "fuzz", "tuolumne", 420, 2.7, 2.97),
    ("(c) only", "fuzz", "wingtip", 213, 1.2, 1.26),
    ("(c) only", "stress", "tuolumne", 202, 2.3, 3.48),
    ("(c) only", "stress", "wingtip", 69, 0.6, 0.53),
    ("(c) only", "evidence", "tuolumne", 417, 4.5, 3.38),
    ("linter KB cells, (a)-(d)", "catalog+widen", "tuolumne", 666, 12.66,
     3.12),
    ("linter KB cells, (a)-(d)", "catalog+widen", "tioga", 239, 4.43, 1.02),
    ("linter KB cells, (a)-(d); 21 widen (c) stopped", "catalog+widen",
     "wingtip", 372, 10.2, 1.45),
)


VERDICT_ORDER = ("confirmed", "environment", "nondeterministic",
                 "not_reproduced")
OWN_ONLY = ("unchecked", "illegal", "not_a_failure")


def render(summary: dict, queue: list[dict], pr: dict,
           recs: list[dict], affected: dict | None = None) -> str:
    decided = [r for r in recs if r.get("decision")]
    L = ["# The reproduction gate over the stored failures", "",
         "Generated by `python3 -I tools/campaigns/gate.py report` (offload/engine/"
         "gate_report.py); do not edit. The method: offload/engine/gate.py; the "
         "change logs: data/reports/gate-changes/<campaign>.tsv; the "
         "verdicts: results/gate/verdicts.jsonl (git-ignored); the "
         "decisions on the review queue: catalog/gate_queue.yaml ("
         "data/reports/gate-queue.md).", "",
         "Every stored failing row of a campaign was planned; within the "
         "campaign's GPU-hour budget the gate reran rows in four "
         "environments: (a) the original build path, (b) another build "
         "directory name with a different character mix, (c) the path of "
         "(a) on another node (wingtip: another GPU, after (a) on the same "
         "host), (d) a second run in (a). The stored row is a run of (a), "
         "unless its provenance shows the toolchain build or the run "
         "environment changed since. Sampling: one row of "
         "every compile-time defect signature, then run-time failures "
         "round-robin over toolchain, class and run, then up to 3 per "
         "compile-time signature. Only a compile-time failure whose "
         "signature names its defect (a diagnostic's message, an ICE's "
         "message or site) inherits its signature's worst verdict; every "
         "other row not rerun is `unchecked`: it keeps its previous outcome "
         "and confirmer verdict, flagged, and is never evidence for a new "
         "finding or the linter's knowledge base. A row whose own stored "
         "repeats disagree is `nondeterministic`. `illegal`: the static "
         "rules pass (offload.engine.rules) finds the program non-conforming. "
         "`not_a_failure`: read today the stored row is a capacity limit "
         "the runtime reports (offload.engine.harness.CAPACITY). A row counts "
         "as a compiler failure when its verdict is `confirmed` or "
         "`unchecked`, or when a decision on it says so "
         "(`counts_as`; a decision applies to its own row only, never to "
         "the rows that inherit from it).", "",
         "## Verdicts by campaign", "",
         "| campaign | failing rows | rerun rows | complete | "
         "confirmed | environment | nondeterministic | not reproduced | "
         "inherited (conf / env / nondet / not repr.) | unchecked | "
         "illegal | not a failure | decided | no verdict | "
         "reclassified | rerun hours |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for camp, st in summary.items():
        c = st["counts"]
        inh = " / ".join(str(c.get(f"inherited {v}", 0))
                         for v in VERDICT_ORDER)
        L.append(f"| {camp} | {c.get('rows', 0)} | "
                 f"{c.get('rerun_rows', 0)} | {c.get('complete', 0)} | "
                 + " | ".join(str(c.get(v, 0)) for v in VERDICT_ORDER)
                 + f" | {inh} | "
                 + " | ".join(str(c.get(v, 0)) for v in OWN_ONLY)
                 + f" | {c.get('decided', 0)} | "
                 f"{c.get('None', 0) + c.get('inherited None', 0)} | "
                 f"{c.get('reclassified', 0)} | "
                 f"{round(sum(st['seconds'].values()) / 3600, 1)} |")
    L += ["", "Nondeterministic includes the rows whose own stored repeats "
          "disagree and that were not rerun: "
          + ", ".join(f"{camp} {st['counts'].get('own_not_rerun', 0)}"
                      for camp, st in summary.items())
          + " (counted, not queued). Rerun hours: the serial seconds of "
          "the reruns (compile and run, every environment), per campaign. "
          "The GPU-hours spent and the budgets are in task-45-report.md.",
          ""]
    L += ["## Decided rows", "",
          f"{len(decided)} rows carry a decision of catalog/gate_queue.yaml "
          "and have left the queue (their reasons: data/reports/"
          "gate-queue.md).", "",
          "| decision | counts as | rows |", "|---|---|---|"]
    for (d, ca), n in sorted(Counter((r["decision"], r.get("counts_as"))
                                     for r in decided).items()):
        L.append(f"| {d} | {ca} | {n} |")
    L += ["", "## The review queue", "",
          f"{len(queue)} rows (rerun rows only, without a decision: each "
          "is new since the last review). Order: nondeterministic, "
          "environment, not reproduced. A failure another environment does "
          "not reproduce, or reproduces differently, may come from a "
          "construct that is not legal (the maintainer, 2026-10-25): each entry "
          "is a legality and determinism question first.", ""]
    inh_by_sig = Counter(r["signature"] for r in recs if r.get("inherited")
                         and r.get("legality_review"))
    for r in queue:
        ok, why = pr.get(r["cell"], (None, ["not checked"]))
        L += [f"### {r['verdict']}: `{r['cell']}`", "",
              f"- signature: `{_short(r['signature'], 160)}`"
              + (f"; {inh_by_sig[r['signature']]} more row(s) inherit this "
                 "verdict" if inh_by_sig.get(r["signature"]) else ""),
              f"- stored: `{_short(r['original'], 160)}`"
              + (f"; read today as `{_short(r['reclassified'], 120)}`"
                 if r.get("reclassified") else ""),
              "- reruns: " + "; ".join(
                  f"{x['env']} `{_short(x['outcome'], 80)}` on "
                  f"{x.get('node', '')}" for x in r.get("reruns", [])),
              ]
        if r.get("condition"):
            L.append(f"- condition (to pin down): {r['condition']}")
        if r.get("missing"):
            L.append(f"- missing environments: {', '.join(r['missing'])}")
        L.append("- pre-run check: " + ("passes (both witnesses accept, no "
                                         "race)" if ok else
                                         "REFUSED: " if ok is False else
                                         "not decided: ")
                 + ("; ".join(_short(w, 200) for w in why[:4])
                    if not ok else ""))
        L += list(CHECKLIST) + [""]
    bad = {f: c for f, c in (affected or {}).items() if _questioned(c)}
    L += ["## Findings to review", "",
          f"{len(bad)} of {len(affected or {})} findings with a linked "
          "failing cell have a linked cell that no longer counts as a "
          "failure, or no linked cell the gate confirmed (the confirmer's "
          "batches link catalog, widened and fuzz cells; stress rows are "
          "linked by the confirmer's dedupe). Their review (kept, or "
          "withdrawn, with the reason) is in task-45-report.md and the "
          "findings' headers.", "",
          "| finding | " + " | ".join(VERDICT_ORDER) + " | inherited "
          "(conf / env / nondet / not repr.) | unchecked | decided "
          "(counts / not) | not counting |",
          "|---|" + "---|" * (len(VERDICT_ORDER) + 4)]
    for f, c in sorted(bad.items()):
        L.append(f"| {f.replace('data/findings/', '')} | "
                 + " | ".join(str(c.get(v, 0)) for v in VERDICT_ORDER)
                 + " | " + " / ".join(str(c.get(f"inherited {v}", 0))
                                      for v in VERDICT_ORDER)
                 + f" | {c.get('unchecked', 0)} | "
                 f"{c.get('decided failure', 0)} / {c.get('decided none', 0)}"
                 f" | {c.get('not counting', 0)} |")
    L += ["", "## Cost model calibration", "",
          "The model's estimate (offload.engine.gate.cost_s over tools/campaigns/gate.py "
          "RERUNS_PER_GPU, uncalibrated) and the busy GPU-hours the ledgers "
          "measured (results/gate/ledger*.jsonl). Calibration per campaign "
          "(measured over model, summed over its jobs): catalog and widened "
          "catalog 0.23, fuzz 1.08, stress 1.38, evidence 0.75 "
          "(tools/campaigns/gate.py CALIBRATION). Allocated GPU-hours add the jobs' "
          "idle tails (the 15% OVERHEAD allowance).", "",
          "| job | campaign | machine | rows | model GPU-h | measured GPU-h "
          "| measured / model |", "|---|---|---|---|---|---|---|"]
    for job, camp, mach, rows, model, meas in COST_MEASURED:
        L.append(f"| {job} | {camp} | {mach} | {rows} | {model} | {meas} | "
                 f"{meas / model:.2f} |")
    L += ["", "## Lower-tier candidates (no finding)", ""]
    L += [f"- {c}" for c in LOWER_TIER]
    L += ["", "## Campaign notes", ""]
    for camp, st in summary.items():
        p = st["plan"]
        L.append(f"- {camp}: plan {p['date']}, sample {p['sample']}, "
                 f"by machine {p['by_machine']}"
                 + (f", {p['stats']}" if p.get("stats") else "")
                 + f"; change log rows: {st['changes']}.")
    L += ["", f"Generated {time.strftime('%Y-%m-%d')}.", ""]
    return "\n".join(L)
