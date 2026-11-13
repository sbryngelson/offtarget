"""Triage of a fuzz campaign.

``summarize(run_dir)`` reads ``results/fuzz/<run id>/programs.jsonl`` (and
``minimized.json`` after ``minimize_run``) and returns the summary written
to ``summary.json``: counts per class per toolchain, generator rejects with
causes, distinct failures (ICEs by compiler message, wrong code by the
minimized source's hash), compile rejections by message, the feature pairs
most associated with failures, known findings rediscovered, and timing.
``write_report`` also renders ``data/reports/fuzz-<run id>.md``.

A program whose host reference run failed (``host_ref_failed``) or
disagreed with the model (``host_mismatch``) is ``valid`` when another host
build or the sequential elision prints the model's checksum
(offload.engine.fuzz_exec.host_verdict). Otherwise it is ``noncompliant`` and is
left out of all tallies, failure lists and minimization."""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

from offload.engine import fuzz_exec as fe

# The toolchains a report reads (the campaigns run fe.TOOLCHAIN_ORDER;
# the n0x0/n1x0 samples also the other toolchains of the merged result tables,
# NVHPC 25.11 and 26.9, joined in: catalog/toolchains.yaml merged_key; GCC, under
# test only, is no fuzz target)
from offload.engine.toolchains import registry as _registry  # noqa: E402
REPORT_ORDER = fe.TOOLCHAIN_ORDER + tuple(
    t for t in _registry().merged() if t not in fe.TOOLCHAIN_ORDER
    and _registry().toolchains[t].family_id not in _registry().under_test_only())
from offload.engine.fuzz import generate

ROOT = Path(__file__).resolve().parent.parent.parent
FINDINGS = ROOT / "data" / "findings" / "fuzz"
FAILS = ("wrong_code", "ice", "run_error", "timeout", "host_fallback")


def _norm(text: str) -> str:
    """A message key: no paths, numbers of lines/columns, hashes or
    addresses."""
    t = re.sub(r"version [0-9a-f]{8,}", "version <v>", text)
    t = re.sub(r"<tmpdir>\S*|\.\./\S+|(?<![\w])/\S+", "<path>", t)
    t = re.sub(r"(File|Line|Column) = [^,|]+,?", "", t)
    t = re.sub(r":\d+:\d+", ":L:C", t)
    t = re.sub(r"0x[0-9a-fA-F]+", "0x", t)
    t = re.sub(r"\bline \d+", "line N", t)
    t = re.sub(r"\b(FUZZ_PROG|fuzz_prog)\b", "", t)
    return " ".join(t.split())[:200]


def reject_cause(stage: str, detail: str) -> str:
    """The generator-reject cause: rule ids, or the checker's message
    without positions and names."""
    if stage == "rules":
        return "rules: " + detail
    if stage == "prerun":
        # The kind of a pre-run refusal;
        # a front-end-only refusal is a candidate AFAR front-end defect
        from offload.engine.prerun import refusal_kind
        k = refusal_kind(detail)
        if k == "frontend_only":
            return ("prerun: front end alone refuses (candidate AFAR "
                    "front-end defect)")
        return f"prerun: {k}"
    d = re.sub(r"t\.f90:\d+:\d+: ", "", detail)
    d = re.sub(r"'(p\d|lp\d|r\d[ab]|o\d|hf\d|t\d)'", "'<var>'", d)
    d = re.sub(r"\b(r\d[ab]|lp\d|o\d|hf\d)\b", "<var>", d)
    return f"{stage}: {_norm(d)}"


def load(run_dir: Path):
    return fe.load(run_dir)


def _minimized(run_dir: Path) -> list[dict]:
    p = Path(run_dir) / "minimized.json"
    return json.loads(p.read_text()) if p.exists() else []


def feature_pairs(progs, tc: str, cls: tuple = FAILS, top: int = 12,
                  min_n: int = 15) -> list:
    """Feature pairs whose programs end in `cls` on `tc` most often,
    relative to the toolchain's rate among programs it did not reject
    (lift), with at least `min_n` programs and 3 hits per pair. A pair is
    listed only if it beats both of its features alone by 25% (otherwise
    one feature explains it; those are in ``single_features``)."""
    rows = [(set(f for f in p.features if not f.startswith("swarm:")),
             p.results[tc].cls in cls)
            for p in progs if tc in p.results
            and p.results[tc].cls not in ("compile_reject", "harness_error")]
    if not rows:
        return []
    base = sum(f for _, f in rows) / len(rows)
    if base == 0:
        return []
    n1, k1, n, k = Counter(), Counter(), Counter(), Counter()
    for feats, hit in rows:
        for f in feats:
            n1[f] += 1
            k1[f] += hit
        for pair in combinations(sorted(feats), 2):
            n[pair] += 1
            k[pair] += hit
    out = []
    for pair, cnt in n.items():
        if cnt < min_n or k[pair] < 3:
            continue
        rate = k[pair] / cnt
        alone = max(k1[f] / n1[f] for f in pair)
        if rate < 1.25 * alone:
            continue
        out.append({"pair": list(pair), "programs": cnt,
                    "failures": k[pair], "rate": round(rate, 3),
                    "lift": round(rate / base, 2),
                    "best_single_rate": round(alone, 3)})
    out.sort(key=lambda r: (-r["lift"], -r["failures"], r["pair"]))
    return out[:top]


def single_features(progs, tc: str, cls, top: int = 12,
                    min_n: int = 15, among_compiled: bool = False) -> list:
    """Features whose programs end in class `cls` (a name or a tuple) on
    `tc` most often relative to the toolchain's rate (lift)."""
    cls = (cls,) if isinstance(cls, str) else tuple(cls)
    skip = ("harness_error",) + (("compile_reject",) if among_compiled
                                 else ())
    rows = [(set(f for f in p.features if not f.startswith("swarm:")),
             p.results[tc].cls in cls) for p in progs if tc in p.results
            and p.results[tc].cls not in skip]
    if not rows:
        return []
    base = sum(f for _, f in rows) / len(rows)
    n, k = Counter(), Counter()
    for feats, hit in rows:
        for f in feats:
            n[f] += 1
            k[f] += hit
    out = [{"feature": f, "programs": n[f], "hits": k[f],
            "rate": round(k[f] / n[f], 3),
            "lift": round((k[f] / n[f]) / base, 2) if base else 0}
           for f in n if n[f] >= min_n and k[f] >= 3]
    out.sort(key=lambda r: (-r["lift"], -r["hits"], r["feature"]))
    return out[:top]


def base_feature_rates(progs) -> dict:
    """Base-language features (fuzz-3, offload.engine.fuzz_base) of the
    judged programs: for each feature and toolchain the programs that have
    it and their classes (counts)."""
    out: dict = {}
    for p in progs:
        for f in p.features:
            if not f.startswith("base:") or f.startswith("base:group:"):
                continue
            row = out.setdefault(f, {"programs": 0, "classes": {}})
            row["programs"] += 1
            for t, r in p.results.items():
                c = row["classes"].setdefault(t, {})
                c[r.cls] = c.get(r.cls, 0) + 1
    return dict(sorted(out.items()))


def known_findings(progs) -> dict:
    """The campaign's evidence for the known findings of data/findings/."""
    def count(pred):
        seeds = [p.seed for p in progs if pred(p)]
        return {"programs": len(seeds), "seeds": seeds[:12]}
    feats = lambda p: set(p.features)  # noqa: E731
    return {
        "cce19-target-parallel-guarded-loop (wrong code on cce19 in a "
        "program with a thread-0-guarded sequential loop in target "
        "parallel)": count(lambda p: "cce19" in p.results
                           and p.results["cce19"].cls == "wrong_code"
                           and feats(p) & {"guard:par_thread0",
                                           "guard:split_par_thread0"}),
        "cce21-defaultmap-aggregate-flag (wrong code or host fallback on "
        "cce21 where cce20 agrees, in a program with a defaultmap clause; "
        "the finding's symptom: a map(tofrom) scalar is not copied back)": count(
            lambda p: "cce21" in p.results and "cce20" in p.results
            and p.results["cce21"].cls in ("wrong_code", "host_fallback")
            and p.results["cce20"].cls == "agree"
            and any(f.startswith("defaultmap:") for f in feats(p))),
        "(control for the line above: the same without a defaultmap "
        "clause)": count(
            lambda p: "cce21" in p.results and "cce20" in p.results
            and p.results["cce21"].cls in ("wrong_code", "host_fallback")
            and p.results["cce20"].cls == "agree"
            and not any(f.startswith("defaultmap:") for f in feats(p))),
        "cce21-in-reduction-taskwait-link (cce21 link failure on "
        "_cray$mt_taskwait)": count(
            lambda p: "cce21" in p.results
            and "_cray$mt_taskwait" in p.results["cce21"].reason),
        "cce19-target-parallel-single-ice / task ICE (CCE 'unhandled "
        "construct type')": count(
            lambda p: any(r.cls == "ice" and "unhandled" in r.reason
                          for r in p.results.values())),
    }


def summarize(run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    progs, crashes = load(run_dir)
    meta = json.loads((run_dir / "meta.json").read_text()) \
        if (run_dir / "meta.json").exists() else {}
    legal = [p for p in progs if p.check == "ok"]
    noncompliant = [p for p in legal if p.validity == "noncompliant"]
    ran = [p for p in legal if p.validity != "noncompliant"]
    # a checker that could not run (stage "error") is an environment
    # failure, not a generator reject
    rejects = [p for p in progs if p.check not in ("ok", "error")]
    checker_errors = [p.seed for p in progs if p.check == "error"]
    tcs = [t for t in REPORT_ORDER if any(t in p.results for p in ran)]
    counts = {t: Counter() for t in tcs}
    flaky = {t: Counter() for t in tcs}
    for p in ran:
        for t, r in p.results.items():
            counts[t][r.cls] += 1
            if r.flaky:
                flaky[t][r.cls] += 1
    causes = Counter(reject_cause(p.check, p.check_detail) for p in rejects)
    by_cause = defaultdict(list)
    for p in rejects:
        by_cause[reject_cause(p.check, p.check_detail)].append(p.seed)
    # distinct failures
    from offload.engine.fuzz_min import ice_signature
    ices = defaultdict(list)
    others = defaultdict(list)
    rejected_msgs = {t: Counter() for t in tcs}
    for p in ran:
        for t, r in p.results.items():
            if r.cls == "ice":
                ices[(t, ice_signature(r.reason, r.output))].append(p.seed)
            elif r.cls in ("run_error", "timeout", "host_fallback"):
                key = re.sub(r"checksum=-?\d+|expected=-?\d+", "", r.reason)
                others[(t, r.cls, _norm(key.split("; repeats")[0]))].append(
                    p.seed)
            elif r.cls == "compile_reject":
                rejected_msgs[t][_norm(r.reason)] += 1
    wrong = {t: [p.seed for p in ran if t in p.results
                 and p.results[t].cls == "wrong_code"] for t in tcs}
    all_mins = _minimized(run_dir)
    nc_seeds = {p.seed for p in noncompliant}
    mins = [m for m in all_mins if m["seed"] not in nc_seeds]
    sessions = meta.get("sessions", [])
    seconds = sum(s.get("seconds", 0) for s in sessions)
    per_prog = [p.seconds for p in progs]
    summary = {
        "run_id": run_dir.name,
        "generated": len(progs) + len(crashes),
        "worker_crashes": [{"seed": c["seed"], "crash": c["crash"]}
                           for c in crashes],
        "legal_and_run": len(legal),
        "judged": len(ran),
        "generator_rejects": {"total": len(rejects),
                              "by_stage": dict(Counter(p.check
                                                       for p in rejects)),
                              "by_cause": {c: {"count": n,
                                               "seeds": by_cause[c][:8]}
                                           for c, n in causes.most_common()}},
        "checker_errors": {"total": len(checker_errors),
                           "seeds": checker_errors},
        "classes": {t: dict(counts[t]) for t in tcs},
        "flaky": {t: dict(flaky[t]) for t in tcs},
        "flaky_programs": [{"seed": p.seed, "toolchain": t,
                            "runs": r.runs} for p in ran
                           for t, r in p.results.items() if r.flaky],
        "all_agree": sum(p.all_agree for p in ran),
        "host_mismatch": [_host_row(p) for p in legal if p.host_mismatch],
        "host_ref_failed": [_host_row(p) for p in legal
                            if p.host_ref_failed],
        "host_path_failure": {t: {"programs": len(s), "seeds": s}
                              for t, s in _host_path_failures(ran).items()},
        "noncompliant": [dict(_host_row(p), classes={
            t: r.cls for t, r in p.results.items()},
            minimized=[m["file"] for m in all_mins if m["seed"] == p.seed
                       and m.get("status") == "minimized"])
            for p in noncompliant],
        "ice": [{"toolchain": t, "signature": sig, "programs": len(s),
                 "seeds": s[:10]} for (t, sig), s in
                sorted(ices.items(), key=lambda kv: (-len(kv[1]), kv[0]))],
        "wrong_code": {t: {"programs": len(s), "seeds": s[:40]}
                       for t, s in wrong.items()},
        "other_failures": [{"toolchain": t, "class": c, "reason": why,
                            "programs": len(s), "seeds": s[:10]}
                           for (t, c, why), s in sorted(
                               others.items(), key=lambda kv: -len(kv[1]))],
        "compile_reject_messages": {t: [{"message": m, "programs": n}
                                        for m, n in c.most_common(25)]
                                    for t, c in rejected_msgs.items()},
        "minimized": mins,
        "distinct_failures": _distinct(mins),
        "feature_pairs": {t: {c: feature_pairs(ran, t, (c,))
                              for c in ("wrong_code", "ice", "run_error")}
                          for t in tcs},
        "failure_features": {t: {c: single_features(ran, t, c, top=8,
                                                    among_compiled=True)
                                 for c in ("wrong_code", "ice",
                                           "run_error")}
                             for t in tcs},
        "compile_reject_features": {t: single_features(ran, t,
                                                       "compile_reject")
                                    for t in tcs},
        "known_findings": known_findings(ran),
        "base": sorted({g for p in progs for g in (p.base or [])}),
        "base_features": base_feature_rates(ran),
        "timing": {"campaign_seconds": seconds,
                   "programs_per_hour": round(len(progs) / seconds * 3600)
                   if seconds else None,
                   "mean_program_seconds": round(sum(per_prog) /
                                                 len(per_prog), 1)
                   if per_prog else None,
                   "workers": sessions[-1]["workers"] if sessions else None,
                   "sessions": sessions},
    }
    return summary


def base_table(rates: dict, tcs: list) -> list[str]:
    rows = []
    for f, v in rates.items():
        cells = []
        for t in tcs:
            c = v["classes"].get(t, {})
            main = [c.get(k, 0) for k in ("agree", "compile_reject", "ice",
                                          "wrong_code", "run_error")]
            rest = sum(c.values()) - sum(main)
            cells.append("/".join(map(str, main))
                         + (f" ({rest})" if rest else ""))
        rows.append([f[5:], v["programs"]] + cells)
    return _table(["feature", "programs"] + tcs, rows)


def _host_row(p) -> dict:
    """A program's host reference check: the reference toolchain and
    value, every host build's checksum (or why it has none), the
    elision, and the validity verdict."""
    return {"seed": p.seed, "expected": p.expected, "tc": p.host_ref_tc,
            "host_ref": p.host_ref,
            "reference": "host_ref_failed" if p.host_ref_failed else
            "host_mismatch" if p.host_mismatch else "agree",
            "host": {t: r.host_checksum if r.host_checksum is not None
                     else (r.host_why or "-")
                     for t, r in p.results.items()},
            "elision": p.elision, "validity": p.validity,
            "witnesses": p.host_witnesses,
            "host_path_failure": p.host_path_failure,
            "rechecked": p.host_rechecked}


def _host_path_failures(progs) -> dict:
    """toolchain -> seeds of valid programs whose host build on it failed
    or printed another checksum than the model (finding class
    host_path_failure)."""
    out = {t: [] for t in REPORT_ORDER}
    for p in progs:
        for t in p.host_path_failure:
            out.setdefault(t, []).append(p.seed)
    return {t: s for t, s in out.items() if s}


def _distinct(mins: list[dict]) -> list[dict]:
    """Minimized failures deduplicated: ICEs by (toolchain family,
    signature), wrong code and run errors by minimized-source hash."""
    seen, out = set(), []
    for m in mins:
        if m.get("status") != "minimized":
            continue
        key = (m["kind"], m["signature"]) if m["kind"] == "ice" else \
            (m["kind"], m["sha"])
        if key in seen:
            continue
        seen.add(key)
        out.append({k: m[k] for k in ("seed", "toolchain", "kind",
                                      "signature", "file", "lines_before",
                                      "lines_after", "also_fails_on",
                                      "expected", "observed") if k in m})
    return out


# --- minimization of a campaign ------------------------------------------------------------

def _ice_key(sig: str) -> str:
    """An ICE message without its source location (CCE releases report the
    same message at different lines of v_openmp.c)."""
    return re.sub(r"\s*\([^()]*line \d+[^()]*\)", "", sig).strip()


# fuzz-1 programs whose result rests on the defaultmap Ruling of
# offload.engine.fuzz (fixed in fuzz-2): not minimized, reported apart
AMBIGUOUS_FUZZ1 = re.compile(r"defaultmap:(present|alloc|from|none):"
                             r"(scalar|all)$")


def ambiguous(p) -> bool:
    return p.gen_version == "fuzz-1" and any(
        AMBIGUOUS_FUZZ1.match(f) for f in p.features)


def representatives(progs, limit: int) -> list[tuple]:
    """(seed, toolchain, kind, signature, host) to minimize: for each ICE
    message (without its location) the smallest program, on the first
    toolchain that shows it; for wrong code and run errors on each
    toolchain up to `limit` non-flaky programs with different kernel
    lists, fewest kernels and shortest first (so one bug that dominates
    the counts does not take every slot). Duplicates are removed after
    minimization, by source hash."""
    from offload.engine.fuzz_min import ice_signature
    ran = sorted((p for p in progs if p.check == "ok"
                  and p.validity != "noncompliant"),
                 key=lambda p: (len(p.kernels), p.lines))
    out, seen = [], set()
    for p in ran:
        for t in REPORT_ORDER:
            r = p.results.get(t)
            if r is None or r.cls != "ice":
                continue
            sig = ice_signature(r.reason, r.output)
            if _ice_key(sig) not in seen:
                seen.add(_ice_key(sig))
                out.append((p.seed, t, "ice", sig, 0))
    for kind in ("wrong_code", "run_error"):
        for t in REPORT_ORDER:
            keys = set()
            for p in ran:
                r = p.results.get(t)
                if r is None or r.cls != kind or r.flaky or ambiguous(p):
                    continue
                key = tuple(re.sub(r" \(\dD\)", "", k) for k in p.kernels)
                if key in keys or len(keys) >= limit:
                    continue
                keys.add(key)
                sig = r.reason.split(";")[0] if kind == "run_error" else ""
                out.append((p.seed, t, kind, sig, r.ran_on_host or 0))
    return out


def also_candidates(tc: str, also=None) -> list[str]:
    """The toolchains a minimized failure is tried on ("also fails on"):
    REPORT_ORDER, or (another machine: coverage parity on Tioga) the given
    ones, never the failing toolchain itself."""
    return [t for t in (also or REPORT_ORDER) if t != tc]


def minimize_run(run_dir: Path, workers: int = 6, limit: int = 4,
                 log=print, only=None, also=None) -> list[dict]:
    """Minimize the representatives of a campaign; results go to
    minimized.json (incremental: entries already there are kept) and
    data/findings/fuzz/<seed>-<toolchain>.f90."""
    from offload.engine import fuzz_min as fm
    run_dir = Path(run_dir)
    progs, _ = load(run_dir)
    by_seed = {p.seed: p for p in progs}
    state_path = run_dir / "minimized.json"
    state = _minimized(run_dir)
    done = {(m["seed"], m["toolchain"], m["kind"]) for m in state}
    FINDINGS.mkdir(parents=True, exist_ok=True)
    if only:
        # given (seed, toolchain, kind) triples instead of the
        # representatives (a triage of a small campaign)
        reps = []
        for seed, tc, kind in only:
            r = by_seed[seed].results[tc]
            sig = ""
            if kind == "ice":
                from offload.engine.fuzz_min import ice_signature
                sig = ice_signature(r.reason, r.output)
            elif kind == "run_error":
                sig = r.reason.split(";")[0]
            reps.append((seed, tc, kind, sig, r.ran_on_host or 0))
    else:
        reps = representatives(progs, limit)
    log(f"{len(reps)} representatives ({len(done)} done)")
    for seed, tc, kind, sig, host in reps:
        if (seed, tc, kind) in done:
            continue
        prog = fe.regenerate(by_seed[seed])
        entry = {"seed": seed, "toolchain": tc, "kind": kind,
                 "signature": sig, "expected": "", "observed": ""}
        r = by_seed[seed].results[tc]
        # the same program minimized for another toolchain already fails
        # on this one: nothing new to minimize
        same = next((m for m in state if m["seed"] == seed and m["kind"]
                     == kind and tc in m.get("also_fails_on", [])), None)
        if same:
            entry.update(status="covered_by", covered_by=same["file"])
            state.append(entry)
            state_path.write_text(json.dumps(state, indent=1) + "\n")
            log(f"seed {seed} on {tc}: covered by {same['file']}")
            continue
        t0 = time.time()
        failure = fm.Failure(tc, kind, sig, host)
        log(f"minimize seed {seed} on {tc} ({kind}) ...")
        try:
            refs = fm.trusted_refs(prog.source, prog.expected, tc) \
                if kind != "ice" else None
            if kind != "ice" and not refs:
                raise ValueError("no reference outside the failing "
                                 "compiler family (another family's host "
                                 "run, or sequential elision) matches the "
                                 "model")
            entry["references"] = refs
            res = fm.minimize(prog.source, fm.Oracle(failure, refs),
                              workers=workers, log=log)
        except ValueError as e:
            entry.update(status="not_reproduced", why=str(e)[:300])
            state.append(entry)
            state_path.write_text(json.dumps(state, indent=1) + "\n")
            log(f"  not reproduced: {e}")
            continue
        body = fm.strip_header(res.source)
        sha = hashlib.sha256(body.encode()).hexdigest()[:16]
        exp, obs = expected_observed(kind, res.verdict, r.reason)
        also = []
        for other in also_candidates(tc, also):
            # another toolchain: any ICE counts (messages differ by release);
            # its references must come from outside its own family
            orefs = fm.refs_for(other, entry.get("references"))
            if kind != "ice" and orefs is None:
                continue
            ok, why = fm.Oracle(fm.Failure(
                other, kind, "" if kind == "ice" else sig, host),
                orefs)(body)
            if ok:
                also.append(other)
        # c1 files keep their names; later campaigns prefix the
        # run id (seeds repeat across campaigns)
        name = f"{seed}-{tc}.f90" if run_dir.name == "c1" else \
            f"{run_dir.name}-{seed}-{tc}.f90"
        (FINDINGS / name).write_text(finding_text(
            seed, failure, prog.gen_version, res.source, res.verdict,
            r.reason, also))
        entry.update(status="minimized", file=f"data/findings/fuzz/{name}",
                     sha=sha, lines_before=res.lines_before,
                     lines_after=len(body.splitlines()),
                     oracle_calls=res.oracle_calls, steps=len(res.steps),
                     seconds=round(time.time() - t0), also_fails_on=also,
                     expected=exp, observed=obs, verdict=res.verdict)
        state.append(entry)
        state_path.write_text(json.dumps(state, indent=1) + "\n")
        log(f"  {res.lines_before} -> {entry['lines_after']} lines in "
            f"{entry['seconds']} s; also fails on {also}")
    return state


# --- the review document --------------------------------------------------------------------

def _table(head: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(head) + " |",
           "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(str(c).replace("|", "\\|") for c in r) + " |"
            for r in rows]
    return out


CAMPAIGNS = Path(__file__).resolve().parent.parent.parent / "catalog" / \
    "fuzz_campaigns.yaml"


def _run_notes(run_id: str) -> list[str]:
    """The notes catalog/fuzz_campaigns.yaml keeps for a run (a campaign's
    run_notes: {run id: text or [texts]})."""
    import yaml
    if not CAMPAIGNS.is_file():
        return []
    d = yaml.safe_load(CAMPAIGNS.read_text()) or {}
    for c in (d.get("campaigns") or {}).values():
        got = (c.get("run_notes") or {}).get(run_id)
        if got:
            return [got] if isinstance(got, str) else list(got)
    return []


def _mode_text(s: dict) -> str:
    """The memory mode of a campaign's runs: its sessions' HSA_XNACK
    (1 when not recorded), and NVHPC's separate memory when a session ran
    an NVHPC toolchain (the x0 campaigns said
    HSA_XNACK=1)."""
    ses = s["timing"]["sessions"] or [{}]
    xs = sorted({x.get("xnack", 1) for x in ses
                 if not any(t.startswith("nvhpc")
                            for t in x.get("toolchains", ()))} or {1})
    text = "HSA_XNACK=" + "/".join(map(str, xs))
    if any(t.startswith("nvhpc") for x in ses
           for t in x.get("toolchains", ())):
        text += " (AMD) and separate memory (NVHPC)"
    return text


def _timing_text(t: dict) -> str:
    """The campaign's time: one session as before; several (concurrent
    chunks, joined toolchain runs) each with its own time and workers
    (their sum read as one session with the last
    session's workers)."""
    ses = t["sessions"] or []
    if len(ses) <= 1:
        return (f"- campaign wall time: {t['campaign_seconds']} s with "
                f"{t['workers']} workers ({t['programs_per_hour']} "
                f"programs/hour; {t['mean_program_seconds']} s per program "
                "and worker, all toolchains and repeats included)")
    parts = ", ".join(
        f"{x.get('run_id', '?')}: {x.get('seconds', 0)} s with "
        f"{x.get('workers', '?')} worker"
        + ("s" if x.get("workers") != 1 else "") for x in ses)
    return (f"- sessions ({len(ses)}, some concurrent; the times are not a "
            f"wall time): {parts}; {t['mean_program_seconds']} s per program "
            "and worker, all toolchains and repeats included")


def _campaign_rows(run_dir: Path) -> list[dict]:
    """(toolchain, mode key, provenance) of a campaign's results, for the
    canary coverage check."""
    if not (run_dir / "programs.jsonl").is_file():
        return []
    meta = run_dir / "meta.json"
    x = 1
    if meta.is_file():
        d = json.loads(meta.read_text())
        x = (d.get("sessions") or [d])[0].get("xnack", 1)
    out = []
    for ln in (run_dir / "programs.jsonl").read_text().splitlines():
        if not ln.strip():
            continue
        rec = json.loads(ln)
        for tc, r in (rec.get("results") or {}).items():
            out.append({"toolchain": tc, "xnack": x,
                        "git_rev": r.get("git_rev"), "gate": r.get("gate")})
    return out


def write_report(run_dir: Path, md_path: Path) -> dict:
    # A changed canary of the campaign stops the report
    from offload.engine import canary
    canary.require_unchanged(canary.files_for(Path(run_dir)),
                             f"fuzz campaign {Path(run_dir).name}",
                             campaign_rows=_campaign_rows(Path(run_dir)))
    s = summarize(run_dir)
    Path(run_dir, "summary.json").write_text(json.dumps(s, indent=1) + "\n")
    gv = (s['timing']['sessions'] or [{}])[-1].get('gen_version', '?')
    L = [f"# Fuzz campaign `{s['run_id']}`"
         + ("" if gv in ("fuzz-1", "fuzz-2") else
            ""), "",
         "Csmith-style random OpenMP 5.2 Fortran offload programs "
         f"(offload.engine.fuzz, generator `{gv}`"
         + (f", base-language groups: {', '.join(s['base'])} "
            "(offload.engine.fuzz_base)" if s.get("base") else "") + ")"
         ", run on every toolchain at -O2, " + _mode_text(s) + ", "
         "OMP_TARGET_OFFLOAD=mandatory; reference: the Python model of "
         "each program, checked against a host run "
         "(OMP_TARGET_OFFLOAD=disabled, a reference only; see the "
         "appendix 'Host reference checks' for the programs whose host run "
         "failed or disagreed). "
         "Machine-readable: "
         f"results/fuzz/{s['run_id']}/summary.json.", ""]
    t = s["timing"]
    L += ["## Size and timing", "",
          f"- programs generated: {s['generated']}; legal and run: "
          f"{s['legal_and_run']} (judged: {s['judged']}; noncompliant, "
          f"excluded from every count below: {len(s['noncompliant'])}); "
          "generator rejects: "
          f"{s['generator_rejects']['total']}; worker crashes: "
          f"{len(s['worker_crashes'])}"
          + (f"; checker errors (a checker could not run): "
             f"{s['checker_errors']['total']} (seeds "
             f"{', '.join(map(str, s['checker_errors']['seeds'][:8]))}; "
             "not run, not generator rejects)"
             if s.get("checker_errors", {}).get("total") else ""),
          _timing_text(t),
          f"- programs whose device results agree with the model on every "
          f"toolchain: {s['all_agree']}", ""]
    notes = _run_notes(s["run_id"])
    if notes:
        L += ["## Notes", ""] + [f"- {n}" for n in notes] + [""]
    L += ["## Classes per toolchain", "",
          "Rejections (compile_reject) are features a toolchain does not "
          "support, not failures. Flaky = the repeats differed (counted "
          "in the worst class).", ""]
    tcs = list(s["classes"])
    L += _table(["class"] + tcs,
                [[c] + [f"{s['classes'][tc].get(c, 0)}"
                        + (f" ({s['flaky'][tc][c]} flaky)"
                           if s["flaky"][tc].get(c) else "")
                        for tc in tcs] for c in fe.CLASSES])
    if s.get("base_features"):
        L += ["", "## Base-language features", "",
              "Per base-language feature (offload.engine.fuzz_base): the "
              "programs that have it, and per toolchain agree / "
              "compile_reject / ice / wrong_code / run_error (other classes "
              "in parentheses when present).", ""]
        L += base_table(s["base_features"], tcs)
    L += ["", "## Known findings rediscovered", ""]
    for k, v in s["known_findings"].items():
        L.append(f"- {k}: {v['programs']} programs "
                 f"(seeds {', '.join(map(str, v['seeds']))})")
    L += ["", "## Distinct minimized failures", ""]
    if s["distinct_failures"]:
        L += _table(["file", "toolchain", "kind", "also fails on",
                     "lines", "expected", "observed"],
                    [[f"`{d['file']}`", d["toolchain"], d["kind"],
                      ", ".join(d.get("also_fails_on") or []) or "-",
                      f"{d['lines_before']} -> {d['lines_after']}",
                      d.get("expected", ""), d.get("observed", "")[:160]]
                     for d in s["distinct_failures"]])
    else:
        L.append("(none minimized yet)")
    others = [m for m in s["minimized"] if m.get("status") != "minimized"]
    if others:
        L += ["", "Not minimized:", ""]
        L += [f"- seed {m['seed']} {m['toolchain']} {m['kind']}: "
              f"{m['status']} {m.get('why', m.get('covered_by', ''))}"
              for m in others]
    L += ["", "## Wrong code (all programs)", ""]
    for tc, w in s["wrong_code"].items():
        L.append(f"- {tc}: {w['programs']} programs"
                 + (f" (seeds {', '.join(map(str, w['seeds'][:20]))})"
                    if w["seeds"] else ""))
    L += ["", "## Internal compiler errors (deduplicated by message)", ""]
    L += _table(["toolchain", "programs", "message", "seeds"],
                [[i["toolchain"], i["programs"], i["signature"][:150],
                  ", ".join(map(str, i["seeds"][:5]))] for i in s["ice"]])
    L += ["", "## Run errors, timeouts, host fallbacks", ""]
    L += _table(["toolchain", "class", "programs", "reason", "seeds"],
                [[o["toolchain"], o["class"], o["programs"],
                  o["reason"][:150], ", ".join(map(str, o["seeds"][:5]))]
                 for o in s["other_failures"]])
    L += ["", "## Features and feature pairs most associated with failures",
          "", "Among programs the toolchain compiled (or crashed on). Lift = "
          "the rate of the class among programs with the feature (pair) "
          "over the toolchain's overall rate; a pair is listed only when it "
          "beats both of its features alone by 25%.", ""]
    for tc in tcs:
        for c in ("wrong_code", "ice", "run_error"):
            singles = s["failure_features"][tc][c]
            pairs = s["feature_pairs"][tc][c]
            if not singles and not pairs:
                continue
            L += [f"### {tc}: {c}", ""]
            if singles:
                L.append("Single features: " + "; ".join(
                    f"{f['feature']} ({f['hits']}/{f['programs']}, lift "
                    f"{f['lift']})" for f in singles))
                L.append("")
            if pairs:
                L += _table(["feature pair", "programs", c, "rate",
                             "best single rate", "lift"],
                            [[" + ".join(r["pair"]), r["programs"],
                              r["failures"], r["rate"],
                              r["best_single_rate"], r["lift"]]
                             for r in pairs[:8]])
                L.append("")
    L += ["## Compile rejections (features not supported)", ""]
    for tc in tcs:
        msgs = s["compile_reject_messages"][tc][:12]
        if not msgs:
            continue
        L += [f"### {tc}", ""]
        L += _table(["programs", "message"],
                    [[m["programs"], m["message"][:170]] for m in msgs])
        feats = s["compile_reject_features"][tc][:8]
        if feats:
            L += ["", "Features most associated with rejection: " + "; ".join(
                f"{f['feature']} ({f['hits']}/{f['programs']})"
                for f in feats)]
        L.append("")
    g = s["generator_rejects"]
    L += ["## Generator rejects", "",
          "Programs failing a legality check are never run. Causes "
          "(`rules`: a 5.2 rule of offload.engine.rules fired, a generator or "
          "rule bug; `flang`: AFAR flang's frontend refused a program the "
          "rules and gfortran accept; see the report for which of these "
          "are flang's errors):", ""]
    L += _table(["count", "cause", "seeds"],
                [[v["count"], c[:170], ", ".join(map(str, v["seeds"][:5]))]
                 for c, v in g["by_cause"].items()])
    if s["flaky_programs"]:
        L += ["", "## Flaky results", ""]
        L += [f"- seed {f['seed']} {f['toolchain']}: "
              + " | ".join(f["runs"])[:300] for f in s["flaky_programs"]]
    L += _host_section(s)
    Path(md_path).parent.mkdir(parents=True, exist_ok=True)
    Path(md_path).write_text("\n".join(L) + "\n")
    return s


def _host_section(s: dict) -> list[str]:
    checks = sorted(s["host_ref_failed"] + s["host_mismatch"],
                    key=lambda h: h["seed"])
    if not checks:
        return []
    tcs = list(s["classes"]) or list(REPORT_ORDER)
    nf = len(s["host_ref_failed"])
    L = ["", "## Appendix: host reference checks (not offload findings)",
         "",
         "Device offload only: host runs (OMP_TARGET_OFFLOAD="
         "disabled) and the sequential elision are references for the "
         "expected value, never measurements of a toolchain. A "
         "host_path_failure below is recorded data (results/fuzz/<run>/"
         "summary.json), not an offload finding, and it counts nowhere "
         "in the tables above.", "",
         f"The reference host run (OMP_TARGET_OFFLOAD=disabled, the first "
         f"toolchain that compiled) failed for {nf} programs "
         f"(host_ref_failed) and printed another checksum than the model "
         f"for {len(s['host_mismatch'])} (host_mismatch). For each, every "
         "toolchain whose build compiled ran it on the host"
         + (" (rebuilt and run twice: results/fuzz/"
            f"{s['run_id']}/{fe.HOSTCHECK})"
            if any(h["rechecked"] for h in checks) else "")
         + ", and the sequential elision (offload.engine.expected) ran where "
         "it applies. Rule: **valid** when at least one of them "
         "prints the model's checksum; the host builds that ran and did "
         "not are `host_path_failure` records (a host-path compiler or "
         "runtime bug: out of scope, not an offload finding). "
         "**noncompliant** when none does (a generator or "
         "model defect): excluded from the findings and the tallies above. "
         "A toolchain whose build does not compile has no host build "
         "('no host build'). Values are host checksums. Scope: only these "
         "programs had every toolchain's host build run; for the others "
         "only the reference toolchain's host run exists, so "
         "host_path_failure counts are a lower bound.", ""]
    rows = []
    for h in checks:
        cells = []
        for t in tcs:
            v = h["host"].get(t, "-")
            if isinstance(v, int):
                cells.append(f"**{v}**" if v == h["expected"] else str(v))
            else:
                cells.append(re.sub(r"^no host build: ", "no build: ",
                                    str(v))[:40])
        el = h["elision"] or "-"
        if el == f"checksum={h['expected']}":
            el = f"**{el}**"
        rows.append([h["seed"], h["reference"], h["tc"] or "-",
                     h["expected"]] + cells +
                    [el[:60], h["validity"],
                     ", ".join(h["host_path_failure"]) or "-"])
    L += _table(["seed", "reference", "ref tc", "model"] +
                [f"{t} host" for t in tcs] +
                ["elision", "validity", "host_path_failure"], rows)
    L += ["", "### host_path_failure (valid programs; host-path "
          "failures, out of scope)", ""]
    hp = s["host_path_failure"]
    if hp:
        L += [f"- {t}: {v['programs']} programs (seeds "
              f"{', '.join(map(str, v['seeds']))})" for t, v in hp.items()]
    else:
        L.append("(none)")
    L += ["", "### Noncompliant programs (generator/model investigation)",
          ""]
    if s["noncompliant"]:
        L += ["No available host build prints the model's checksum. "
              "Their device classes (not counted anywhere above):", ""]
        L += [f"- seed {n['seed']}: model {n['expected']}; host "
              + ", ".join(f"{t} {v}" for t, v in n["host"].items())
              + f"; elision {n['elision'] or '-'}; device "
              + ", ".join(f"{t} {c}" for t, c in n["classes"].items())
              + (f"; minimized (withdrawn): {', '.join(n['minimized'])}"
                 if n["minimized"] else "")
              for n in s["noncompliant"]]
    else:
        L.append("(none)")
    return L


def finding_text(seed: int, failure, gen_version: str, source: str,
                 verdict: str, reason: str = "", also=()) -> str:
    """A minimized reproducer's file: the finding header (the failure, and
    the expected and observed values of the minimized program from the
    oracle's verdict) and the minimized source without the generator's
    header, which describes the original program."""
    from offload.engine import fuzz_min as fm
    from offload.engine.hdrwrap import wrap_line
    exp, obs = expected_observed(failure.kind, verdict, reason)
    return (fm.finding_header(seed, failure, exp, obs, gen_version) +
            ("\n".join(wrap_line(f"! also fails on: {', '.join(also)}")) +
             "\n" if also else "") +
            fm.strip_header(source))


def expected_observed(kind: str, verdict: str, reason: str = ""
                      ) -> tuple[str, str]:
    """The finding header's expected and observed lines from the
    oracle's verdict."""
    if kind == "wrong_code":
        return (f"the host reference checksum "
                f"({verdict.split(';')[-1].strip()})",
                verdict.split(";")[0])
    if kind == "ice":
        return "compiles", f"internal compiler error: {reason[:160]}"
    return "runs to completion (the host run does)", verdict


_KEYED = ("! failure:", "! expected:", "! observed:", "! also fails on:")


def _unfold_keys(lines: list) -> list:
    """Header lines with the `!   ` continuations of the keyed lines
    joined back (the caller wraps again); other lines stay as they are."""
    out = []
    for ln in lines:
        if ln.startswith("!   ") and ln[4:5] != " " and out and \
                out[-1].startswith(_KEYED):
            out[-1] += " " + ln[4:]
        else:
            out.append(ln)
    return out


def refine_run(run_dir: Path, workers: int = 6, log=print,
               kinds=("ice", "wrong_code", "run_error")) -> list[dict]:
    """Minimize every minimized finding once more (a later fix of the
    minimizer, or a second pass, may shrink it further); the file, its
    hash and line count are updated in place, with the header's expected
    and observed lines; an "also fails on" line was measured on the old
    body and is kept only as "before refinement". A stored reference in
    the failing compiler's family is dropped (sequential elision when
    none is left)."""
    from offload.engine import fuzz_min as fm
    run_dir = Path(run_dir)
    state = _minimized(run_dir)
    for m in state:
        if m.get("status") != "minimized" or m["kind"] not in kinds:
            continue
        path = ROOT / m["file"]
        text = path.read_text()
        k = 0
        lines = text.splitlines()
        while k < len(lines) and lines[k].startswith("!") and \
                not lines[k].startswith("!$"):
            k += 1
        body = "\n".join(lines[k:]) + "\n"
        failure = fm.Failure(m["toolchain"], m["kind"], m["signature"],
                             0 if "ran_on_host=1" not in m.get("verdict", "")
                             else 1)
        refs = None
        if m["kind"] != "ice":
            refs = fm.refs_for(m["toolchain"], m.get("references")) or \
                [fm.ELISION_REF]
            m["references"] = refs
        try:
            res = fm.minimize(body, fm.Oracle(failure, refs),
                              workers=workers)
        except ValueError as e:
            log(f"{m['file']}: no longer reproduces: {e}")
            m["refine"] = f"not reproduced: {str(e)[:200]}"
            continue
        new = fm.strip_header(res.source)
        if len(new.splitlines()) < len(body.splitlines()):
            exp, obs = expected_observed(m["kind"], res.verdict,
                                         m.get("observed", ""))
            from offload.engine.hdrwrap import wrap_line
            head = []
            for ln in _unfold_keys(lines[:k]):
                if ln.startswith("! expected:") and m["kind"] != "ice":
                    ln = f"! expected: {exp}"
                elif ln.startswith("! observed:") and m["kind"] != "ice":
                    ln = f"! observed: {obs}"
                elif ln.startswith("! also fails on:"):
                    ln = ln.replace("! also fails on:", "! also failed on "
                                    "(before refinement):", 1)
                head.extend(wrap_line(ln))
            path.write_text("\n".join(head) + "\n" + new)
            if m["kind"] != "ice":
                m.update(expected=exp, observed=obs, verdict=res.verdict)
            if m.get("also_fails_on"):
                m["also_failed_before_refinement"] = m.pop("also_fails_on")
            m["lines_after"] = len(new.splitlines())
            m["sha"] = hashlib.sha256(new.encode()).hexdigest()[:16]
            log(f"{m['file']}: {len(body.splitlines())} -> "
                f"{m['lines_after']} lines")
    (run_dir / "minimized.json").write_text(json.dumps(state, indent=1)
                                            + "\n")
    return state


# --- the base-language review --------------------------------------------------

STAGES = {"types": "1: element types and kinds",
          "derived": "2: derived types",
          "alloc": "3: allocatable, pointer, target, sections, procedures",
          "declare": "4: declare target, mapper, user reduction, modules",
          "multitu": "5: multiple translation units"}


def _pct(k: int, n: int) -> str:
    return f"{100 * k / n:.0f}%" if n else "-"


def _copy_mode_section(run_dirs: list, sums: list, tcs: list) -> list:
    """The copy-mode comparison of the base-language review: for each stage
    run with a sibling ``x0-<group>`` campaign (the same seeds at
    HSA_XNACK=0, in a flux allocation with THP on), the per-toolchain class
    changes among the seeds judged in both; and, from ``thp_split.json``
    next to the runs, the verdicts of the reruns that separate THP from the
    memory mode. Empty when no stage has an x0 run."""
    rows, changes = [], []
    for d, s in zip(run_dirs, sums):
        g = ", ".join(s.get("base") or [])
        x0 = Path(d).parent / f"x0-{g}"
        if not g or not (x0 / "summary.json").exists():
            continue
        xs = json.loads((x0 / "summary.json").read_text())
        ok = {p.seed: p for p in fe.load(d)[0]
              if p.check == "ok" and p.validity != "noncompliant"}
        okx = {p.seed: p for p in fe.load(x0)[0]
               if p.check == "ok" and p.validity != "noncompliant"}
        both = sorted(set(ok) & set(okx))
        moved = Counter()
        for seed in both:
            for t in tcs:
                a, b = ok[seed].results.get(t), okx[seed].results.get(t)
                if a and b and a.cls != b.cls:
                    moved[(t, a.cls, b.cls)] += 1
        rows.append([f"`{s['run_id']}`", f"`{xs['run_id']}`", len(both),
                     len(xs["noncompliant"]),
                     f"{xs['all_agree']} ({s['all_agree']})",
                     sum(moved.values())])
        if moved:
            changes.append(f"`{s['run_id']}`: " + "; ".join(
                f"{t}: {a} -> {b} {n}"
                for (t, a, b), n in sorted(moved.items())))
    if not rows:
        return []
    L = ["## Copy mode (HSA_XNACK=0)", "",
         "Each stage campaign run again on the same seeds at HSA_XNACK=0 "
         "(copy mode) in a flux allocation with THP on. The stage runs above "
         "used HSA_XNACK=1 on the interactive node with THP off, so a change "
         "here mixes the memory mode with THP (see the split below when "
         "present). Per run: seeds judged in both, noncompliant at "
         "HSA_XNACK=0, programs that agree on every toolchain at "
         "HSA_XNACK=0 (at HSA_XNACK=1 in parentheses), and the toolchain "
         "cells whose class changed.", ""]
    L += _table(["run", "copy-mode run", "seeds in both",
                 "noncompliant", "agree on all", "cells changed"], rows)
    L += [""] + [f"- {c}" for c in changes] + [""]
    split = Path(run_dirs[0]).parent / "thp_split.json"
    if split.exists():
        sp = json.loads(split.read_text())
        n = Counter(e["verdict"] for e in sp["seeds"])
        L += ["### THP or memory mode", "",
              sp.get("note", "Seeds that crashed at HSA_XNACK=1 and agree at "
                     "HSA_XNACK=0, run again at HSA_XNACK=1 in two flux "
                     "allocations, THP on and THP off."), ""]
        L += _table(["verdict", "seeds"], [[v, c] for v, c in
                                           sorted(n.items())])
        L += [""] + [f"- {v}: " + ", ".join(
            f"{e['group']} {e['seed']}" for e in sp["seeds"]
            if e["verdict"] == v) for v in sorted(n)] + [""]
        sigs = defaultdict(list)
        for e in sp["seeds"]:
            if e["verdict"] == "xnack1" and e.get("signature"):
                sigs[e["signature"]].append(f"{e['group']} {e['seed']}")
        if sigs:
            fam = sp.get("families", {})
            L += ["Runtime failure of the xnack1 seeds:", ""]
            L += _table(["failure", "seeds", "which", "family"],
                        [[f"`{s}`", len(v), ", ".join(v), fam.get(s, "")]
                         for s, v in sorted(sigs.items(),
                                            key=lambda x: -len(x[1]))])
            L += [""]
    return L


def _elision_section(run_dirs: list, sums: list) -> list:
    """The sequential elision of each run's programs (``elision.jsonl``,
    written by ``tools/campaigns/fuzz.py elide``): programs, how many it applies to
    (offload.engine.expected.elision_applicability), how many of those print
    the model's checksum, differ from it, or gave no value, and the most
    frequent reasons it does not apply. Empty when no run has the file."""
    rows, odd = [], []
    for d, s in zip(run_dirs, sums):
        path = Path(d) / fe.ELISION_FILE
        if not path.exists():
            continue
        recs = [json.loads(ln) for ln in path.read_text().splitlines()
                if ln.strip()]
        app = [r for r in recs if r["applicable"]]
        same = [r for r in app if r.get("value") == r["expected"]]
        diff = [r for r in app if r.get("value") is not None and
                r["value"] != r["expected"]]
        none = [r for r in app if r.get("value") is None]
        why = Counter()
        for r in recs:
            if not r["applicable"]:
                for x in r.get("why", "").split("; "):
                    why[re.sub(r"\s*\[.*?\]", "",
                               re.sub(r"line \d+", "line N", x))[:120]] += 1
        rows.append([f"`{s['run_id']}`", len(recs), len(app), len(same),
                     len(diff), len(none),
                     "; ".join(f"{k} ({n})" for k, n in why.most_common(4))
                     or "-"])
        odd += [f"`{s['run_id']}` seed {r['seed']}: elision "
                f"{r['value']}, model {r['expected']}" for r in diff]
        odd += [f"`{s['run_id']}` seed {r['seed']}: {r.get('why', '')[:120]}"
                for r in none]
    if not rows:
        return []
    L = ["## Sequential elision", "",
         "The programs built without OpenMP (gfortran and amdflang) against "
         "a sequential omp_lib and run on the host, where "
         "offload.engine.expected.elision_applicability proves that sequential "
         "execution gives the OpenMP result (ELISION_RULE; structures are "
         "tracked component by component, pointers as aliases of their "
         "targets, internal subroutines inlined). Elision is the model's "
         "independent partner: a value different from the model's is a "
         "model bug or an analysis bug until shown otherwise.", ""]
    L += _table(["run", "programs", "elision applies", "= model",
                 "differs", "no value", "most frequent reasons it does not "
                 "apply"], rows)
    L += [""] + ([f"- {x}" for x in odd] + [""] if odd else [])
    return L


def write_base_review(run_dirs: list, md_path: Path) -> dict:
    """data/reports/fuzz-base-language.md from the stage campaigns
    (summary.json of each, written by write_report)."""
    from offload.engine.fuzz_base import EXCLUSIONS, GROUP_SWARM
    sums = []
    for d in run_dirs:
        d = Path(d)
        sums.append(json.loads((d / "summary.json").read_text()))
    tcs = list(fe.TOOLCHAIN_ORDER)  # the stage campaigns ran these
    L = ["# Base-language axis of the fuzz generator", "",
         "Generator `fuzz-3` (offload.engine.fuzz, offload.engine.fuzz_base) adds "
         "base-language groups to the Csmith-style OpenMP 5.2 offload "
         "generator, one group per stage, switchable per campaign "
         "(`tools/campaigns/fuzz.py run --base-features <group>`); without a group a "
         "fuzz-3 program is the fuzz-2 program of its seed, and fuzz-1/fuzz-2 "
         "seeds replay unchanged. Every program passes offload.engine.rules, "
         "gfortran -std=f2008 -fsyntax-only, AFAR flang's frontend, and the "
         "definedness check (the program without OpenMP built by gfortran "
         "with -fcheck=all, twice with different fills of uninitialised "
         "storage, must print the model's checksum both times); each "
         "parallel loop of the model is checked for races. The maintainer's "
         "host-run rule applies (a program that no host build or sequential "
         "elision prints the model's value for is noncompliant and left out). "
         "Campaigns: 300 programs each, toolchains afar, cce19, cce20, cce21, "
         "-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory; per-campaign "
         "reports data/reports/fuzz-<run>.md, minimized reproducers "
         "data/findings/fuzz/<run>-<seed>-<toolchain>.f90 (triage: "
         "data/findings/fuzz/README.md).", ""]
    L += ["## Campaigns", ""]
    rows = []
    for s in sums:
        g = ", ".join(s.get("base") or [])
        t = s["timing"]
        rows.append([f"`{s['run_id']}`", STAGES.get(g, g) if g else
                     "control: no base group (the fuzz-2 programs)",
                     s["generated"],
                     s["judged"], len(s["noncompliant"]),
                     s["generator_rejects"]["total"], s["all_agree"],
                     t["campaign_seconds"]])
    L += _table(["run", "stage", "programs", "judged", "noncompliant",
                 "generator rejects", "agree on all", "wall s"], rows)
    L += ["", "## Classes per stage and toolchain", "",
          "Counts among the judged programs (rate of the judged in "
          "parentheses).", ""]
    for c in ("agree", "compile_reject", "ice", "wrong_code", "run_error",
              "timeout", "host_fallback", "harness_error"):
        rows = []
        for s in sums:
            n = s["judged"]
            rows.append([f"`{s['run_id']}`"] + [
                f"{s['classes'].get(t, {}).get(c, 0)} "
                f"({_pct(s['classes'].get(t, {}).get(c, 0), n)})"
                for t in tcs])
        if any(any(not x.startswith("0 ") for x in r[1:]) for r in rows):
            L += [f"### {c}", ""] + _table(["run"] + tcs, rows) + [""]
    ctrl = next((x for x in sums if not x.get("base")), None)
    if ctrl is not None:
        L += ["## Against the control", "",
              f"The control `{ctrl['run_id']}` runs the same seeds without a "
              "base-language group (the fuzz-2 programs), so a stage's "
              "excess over it is what its group adds. Per toolchain: the "
              "stage's failure rate (wrong_code + run_error + timeout + "
              "host_fallback, among the judged programs the toolchain "
              "compiled) and, in parentheses, the control's.", ""]

        def frate(x, t):
            c = x["classes"].get(t, {})
            comp = sum(c.values()) - c.get("compile_reject", 0) - \
                c.get("harness_error", 0) - c.get("ice", 0)
            bad = sum(c.get(k, 0) for k in ("wrong_code", "run_error",
                                            "timeout", "host_fallback"))
            return bad, comp
        rows = []
        for x in sums:
            if x is ctrl:
                continue
            cells = []
            for t in tcs:
                b, c = frate(x, t)
                b0, c0 = frate(ctrl, t)
                cells.append(f"{b}/{c} = {_pct(b, c)} ({_pct(b0, c0)})")
            rows.append([f"`{x['run_id']}`"] + cells)
        L += _table(["run"] + tcs, rows) + [""]
    L += _copy_mode_section(run_dirs, sums, tcs)
    L += _elision_section(run_dirs, sums)
    L += ["## Coverage and rates by base-language feature", "",
          "Per feature: programs with it; per toolchain the agree rate among "
          "those it compiled, then wrong_code / ice / run_error counts "
          "(compile rejections are features not supported, not failures). "
          "Features in fewer than 10 programs are listed by name only.", ""]
    for s in sums:
        rates = s.get("base_features", {})
        g = ", ".join(s["base"])
        L += [f"### `{s['run_id']}` ({STAGES.get(g, g) if g else 'control'})",
              ""]
        rows, few = [], []
        for f, v in rates.items():
            if v["programs"] < 10:
                few.append(f"{f[5:]} ({v['programs']})")
                continue
            cells = []
            for t in tcs:
                c = v["classes"].get(t, {})
                compiled = sum(c.values()) - c.get("compile_reject", 0) - \
                    c.get("harness_error", 0)
                cells.append(f"{_pct(c.get('agree', 0), compiled)} "
                             f"{c.get('wrong_code', 0)}/{c.get('ice', 0)}/"
                             f"{c.get('run_error', 0)}")
            rows.append([f[5:], v["programs"]] + cells)
        L += _table(["feature", "programs"] + [f"{t} agree w/i/r"
                                               for t in tcs], rows)
        if few:
            L += ["", "Fewer than 10 programs: " + "; ".join(few)]
        lifts = []
        for t in tcs:
            for c in ("wrong_code", "ice", "run_error"):
                for f in s.get("failure_features", {}).get(t, {}).get(c, []):
                    if f["feature"].startswith("base:"):
                        lifts.append(f"{t} {c}: {f['feature'][5:]} "
                                     f"({f['hits']}/{f['programs']}, lift "
                                     f"{f['lift']})")
        if lifts:
            L += ["", "Base-language features among the most associated "
                  "with a failure class (lift over the toolchain's rate): "
                  + "; ".join(lifts)]
        L.append("")
    L += ["## Minimized reproducers", ""]
    rows = []
    for s in sums:
        for d in s.get("distinct_failures", []):
            rows.append([f"`{s['run_id']}`", f"`{d['file']}`",
                         d["toolchain"], d["kind"],
                         ", ".join(d.get("also_fails_on") or []) or "-",
                         f"{d['lines_before']} -> {d['lines_after']}"])
        for m in s.get("minimized", []):
            if m.get("status") != "minimized":
                rows.append([f"`{s['run_id']}`", f"seed {m['seed']}",
                             m["toolchain"], m["kind"], "-",
                             f"{m['status']}: "
                             f"{(m.get('why') or m.get('covered_by') or '')[:80]}"])
    L += _table(["run", "file", "toolchain", "kind", "also fails on",
                 "lines"], rows) if rows else ["(none)"]
    L += ["", "## Exclusions", "",
          "What each group does not generate, because the model could not "
          "predict it or the spec leaves it open (offload.engine.fuzz_base "
          "EXCLUSIONS):", ""]
    for g, items in EXCLUSIONS.items():
        if g not in STAGES:     # a later group (fuzz-5 oop): not in this review
            continue
        L += [f"### {g} (stage {STAGES[g]})", ""] + [f"- {x}" for x in items]
        L += ["", "Sub-features (swarm): " + ", ".join(GROUP_SWARM[g]), ""]
    Path(md_path).write_text("\n".join(L) + "\n")
    return {"runs": [s["run_id"] for s in sums]}
