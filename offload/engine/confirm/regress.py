"""Regression mode: ``confirm regress --toolchain NEW --like OLD``.

Four steps, all writing under results/confirm/regress/NEW/:
  plan     the jobs that run the catalog on NEW and the fixed fuzz sample
           (tools/jobs/run_regress.sh), through the scheduler
  fuzz     the sample (``FUZZ_SAMPLE``) on OLD and NEW in one job
  diff     NEW's rows against OLD's stored rows per (program, mode): same,
           regression (OLD passed, NEW fails), fix (OLD failed, NEW passes),
           changed (both fail, differently)
  confirm  each differing cell is rerun on OLD and NEW (k repeats, one node);
           one that does not reproduce is ``not_reproduced``, otherwise the
           rules decide the failing cell. Output: report.json
``report`` writes data/reports/confirm-regress-NEW.md."""
from __future__ import annotations

import json
import re
import time
from collections import Counter
from pathlib import Path

from offload.engine.confirm import ingest as I
from offload.engine.confirm import machines as M
from offload.engine.confirm.model import PASSING
from offload.engine.toolchains import TOOLCHAINS

ROOT = Path(__file__).resolve().parent.parent.parent.parent
BASE = ROOT / "results" / "confirm" / "regress"
# the fixed fuzz sample: the first 200 seeds of campaign s1-00's
# configuration (generator fuzz-3, every base-language group)
FUZZ_SAMPLE = {"gen_version": "fuzz-3",
               "base": ("types", "derived", "alloc", "declare", "multitu"),
               "seeds": (1, 200), "mode": "unified"}
LANGS = ("f90", "c", "acc")


def out_dir(new: str) -> Path:
    return BASE / new


def plan(new: str, like: str, submit: bool = False, scheduler=None
         ) -> list[dict]:
    """The run jobs of a regression (printed, or submitted through the
    machine's scheduler)."""
    from offload.engine.confirm import jobs as J
    tc = TOOLCHAINS[new]
    if TOOLCHAINS[like].machine != tc.machine:
        raise ValueError("NEW and OLD must run on the same machine")
    m = M.load()[tc.machine]
    d = out_dir(new).relative_to(ROOT)
    specs = []
    for lang in LANGS:
        for mode in m.modes:
            x = m.row_key(mode)
            specs.append(J.spec_for(m, "tools/jobs/run_regress.sh",
                                    {"JOB": "matrix", "LANG_": lang,
                                     "X": str(x), "NEW": new},
                                    f"{d}/matrix.{lang}.x{x}.log"))
    specs.append(J.spec_for(m, "tools/jobs/run_regress.sh",
                            {"JOB": "fuzz", "NEW": new, "LIKE": like},
                            f"{d}/fuzz.log"))
    out = []
    sched = scheduler or J.scheduler_for(m)
    for s in specs:
        rec = {"command": " ".join(sched.command(s)), "env": s.env}
        if submit:
            rec["job"] = sched.submit(s)
        out.append(rec)
    return out


def run_fuzz(new: str, like: str, workers: int = 16, log=print) -> Path:
    from offload.engine import fuzz_exec as fe
    m = M.load()[TOOLCHAINS[new].machine]
    fe.XNACK = m.row_key(FUZZ_SAMPLE["mode"])
    d = out_dir(new) / "fuzz"
    a, b = FUZZ_SAMPLE["seeds"]
    meta = {"run_id": "fuzz", "gen_version": FUZZ_SAMPLE["gen_version"],
            "base": list(FUZZ_SAMPLE["base"]), "seeds": [a, b],
            "toolchains": [like, new], "xnack": fe.XNACK,
            "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(json.dumps({"sessions": [meta]}, indent=1))
    fe.campaign(d, range(a, b + 1), workers, (like, new),
                log=log, gen_version=FUZZ_SAMPLE["gen_version"],
                base=FUZZ_SAMPLE["base"], xnack=fe.XNACK)
    return d / "programs.jsonl"


def new_rows(new: str) -> list[I.Row]:
    out = []
    d = out_dir(new)
    for p in sorted(d.glob("matrix.*.jsonl")) + sorted(
            d.glob("baseline.*.jsonl")):
        if ".meta" in p.name:
            continue
        out += I.load_rows(p)
    f = d / "fuzz" / "programs.jsonl"
    if f.is_file():
        out += I.load_rows(f)
    return out


def _reason_class(r: I.Row) -> str:
    """The comparable part of a reason (no addresses, paths, numbers of
    lines; a check value)."""
    from offload.engine.confirm.findings import normalize
    text = normalize(r.reason.split(";")[0])
    text = re.sub(r"0x[0-9a-f]+|<tmpdir>\S*|:\d+:\d+|line \d+|"
                  r"version \S+", "", text)
    return " ".join(text.split())[:120]


def classify(old: I.Row | None, new: I.Row) -> str:
    if old is None:
        return "new_cell"
    po, pn = old.outcome in PASSING, new.outcome in PASSING
    if po and pn:
        return "same"
    if po and not pn:
        return "regression"
    if pn and not po:
        return "fix"
    if old.outcome != new.outcome or old.value != new.value:
        return "changed"
    return "same"


def diff(new: str, like: str, rows=None, index=None) -> list[dict]:
    """Each cell of NEW with OLD's row for the same program and mode
    (fuzz: OLD's row of the same side-by-side run)."""
    rows = rows if rows is not None else new_rows(new)
    idx = index or I.stored_index()
    side = I.Index(rows)
    out = []
    for r in rows:
        if r.toolchain != new:
            continue
        if r.kind == "fuzz":
            old = side.get("fuzz", r.ident, like, r.mode)
        else:
            old = idx.get(r.kind, r.ident, like, r.mode)
        cls = classify(old, r)
        if cls == "same" and old is not None and old.outcome == r.outcome \
                and r.outcome not in PASSING and \
                _reason_class(old) != _reason_class(r):
            cls = "changed"
        out.append({"kind": r.kind, "ident": r.ident, "mode": r.mode,
                    "class": cls, "legal": r.legal,
                    "old": None if old is None else
                    {"outcome": old.outcome, "value": old.value,
                     "reason": old.reason[:200], "origin": old.origin},
                    "new": {"outcome": r.outcome, "value": r.value,
                            "reason": r.reason[:200], "origin": r.origin}})
    return out


def summary(cells: list[dict]) -> dict:
    c = Counter((d["kind"], d["mode"], d["class"]) for d in cells)
    return {f"{k}|{m}|{cl}": n for (k, m, cl), n in sorted(c.items())}


def rerun_class(old: dict, new: dict) -> str:
    """The class of a cell run again on OLD and NEW (each: outcomes and
    values of k repeats). Both failing in the same outcome class with a
    value that changes from run to run on both is "same" (one
    nondeterministic failure, not a change between the versions)."""
    po = all(o in PASSING for o in old["outcomes"])
    pn = all(o in PASSING for o in new["outcomes"])
    again = {(True, False): "regression", (False, True): "fix"}.get((po, pn))
    if again is not None:
        return again
    if po:
        return "same"
    if set(old["outcomes"]) != set(new["outcomes"]):
        return "changed"
    if set(old["values"]) == set(new["values"]):
        return "same"
    if len(set(old["values"])) > 1 and len(set(new["values"])) > 1:
        return "same"
    return "changed"


def confirm_differences(new: str, like: str, cells: list[dict], runner,
                        repeats: int = 3, workers: int = 8, store=None,
                        log=print) -> list[dict]:
    """Run each differing cell again on OLD and NEW (this node), then the
    rules on the cell that still differs."""
    from concurrent.futures import ThreadPoolExecutor

    from offload.engine.confirm import collectors as C
    from offload.engine.confirm import engine as EN
    from offload.engine.confirm.store import Store
    todo = [d for d in cells if d["class"] in ("regression", "fix",
                                               "changed") and d["legal"]]
    rows = new_rows(new)
    idx = I.Index(list(I.stored_index().by_cell.values()) + rows)
    ctx = C.Context(idx, store or Store(), runner=runner, allow_run=True,
                    repeats=repeats)
    nidx = I.Index(rows)

    def one(d):
        row = nidx.get(d["kind"], d["ident"], new, d["mode"])
        case = I.case_of_row(row)
        ref = case.program
        res = {}
        for t in (like, new):
            runs, prov = runner.run(ref, t, d["mode"], "-O2", "mandatory",
                                    repeats)
            res[t] = {"outcomes": [r.outcome for r in runs],
                      "values": [r.value for r in runs],
                      "reason": runs[0].reason[:200], "host": prov.host}
        again = rerun_class(res[like], res[new])
        out = dict(d, rerun=res, rerun_class=again)
        if again == "same":
            out["status"] = "not_reproduced"
            return out
        target = new if again in ("regression", "changed") else like
        trow = idx.get(d["kind"], d["ident"], target, d["mode"])
        tcase = I.case_of_row(trow, ref)
        verdict = EN.confirm(tcase, ctx)
        out["status"] = "confirmed"
        out["confirm"] = {k: verdict[k] for k in (
            "verdict", "rule", "reason", "citations", "findings",
            "witnesses", "withdrawn")}
        out["confirm"]["toolchain"] = target
        return out

    results = []
    with ThreadPoolExecutor(max(1, workers)) as pool:
        for k, r in enumerate(pool.map(one, todo), 1):
            results.append(r)
            log(f"{k}/{len(todo)} {r['kind']} {r['ident']} {r['mode']}: "
                f"{r['class']} -> {r.get('rerun_class')} "
                f"{r.get('confirm', {}).get('verdict', '')}")
    return results


def render(new: str, like: str, cells: list[dict], confirmed: list[dict],
           meta: dict) -> str:
    from offload.engine.toolchains import compiler_version
    s = Counter((d["kind"], d["class"]) for d in cells)
    kinds = sorted({k for k, _ in s})
    classes = ["same", "regression", "fix", "changed", "new_cell"]
    lines = [f"# Regression: {new} against {like}", "",
             f"NEW `{new}`: {meta.get('new_compiler', '')}; OLD `{like}`: "
             f"{meta.get('old_compiler', '')}. Rows of NEW: "
             "results/confirm/regress/" + new + "/ (git-ignored; not in the "
             "headline tables). OLD: the stored full result files; the fuzz "
             "sample ran both side by side.", "",
             "| set | " + " | ".join(classes) + " |",
             "|---|" + "---|" * len(classes)]
    for k in kinds:
        lines.append(f"| {k} | " + " | ".join(str(s[(k, c)]) for c in
                                               classes) + " |")
    st = Counter(d.get("status", "") for d in confirmed)
    diffs = sum(s[(k, c)] for k in kinds for c in ("regression", "fix",
                                                    "changed"))
    lines += ["", f"Result: {diffs} differing cells; run again on one node "
              f"(3 repeats of each version): {st['confirmed']} reproduced, "
              f"{st['not_reproduced']} not reproduced (the versions behave "
              "the same; a stored difference was run-to-run variation)."]
    lines += ["", "## Differences, run again on one node and confirmed", "",
              "| set | program | mode | stored | rerun | verdict (rule) on "
              "| finding |", "|---|---|---|---|---|---|---|"]
    for d in sorted(confirmed, key=lambda d: (d["kind"], d["ident"],
                                               d["mode"])):
        c = d.get("confirm") or {}
        f = (c.get("findings") or [{}])[0].get("file", "") if c else ""
        lines.append(
            f"| {d['kind']} | {d['ident']} | {d['mode']} | {d['class']}: "
            f"{(d['old'] or {}).get('outcome')} -> {d['new']['outcome']} | "
            f"{d.get('rerun_class')} | "
            + (f"{c['verdict']} ({c['rule']}) on {c['toolchain']}"
               if c else d.get("status", "") + (f": {d['note']}" if
                                                d.get("note") else ""))
            + f" | {f} |")
    return "\n".join(lines) + "\n"
