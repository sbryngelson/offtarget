"""A fuzz campaign of several run ids, with the confirmer's verdicts
(s1 = s1-00 .. s1-19 at HSA_XNACK=1 and s1x0-00 .. s1x0-04 at
HSA_XNACK=0; catalog/fuzz_campaigns.yaml).

``load`` reads every run of a campaign (each run's memory mode from its
meta.json, its host check applied); ``rates`` counts the per-toolchain
classes per memory mode; ``verdict_counts`` and ``reject_drivers`` read
the confirmer's batch results; ``interactions`` finds base-language x
OpenMP feature pairs whose programs fail on a toolchain more often than
programs with either feature without the other, and compares them with
the single-group campaigns (b1-b5: one base group each; b0 and c1: no
base-language features); ``copy_mode`` compares the copy-mode runs with
the unified-mode runs of the same seeds. ``render`` writes
data/reports/fuzz-<campaign>.md."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from offload.engine import fuzz_exec as fe

ROOT = Path(__file__).resolve().parent.parent.parent
FUZZ = ROOT / "results" / "fuzz"
from offload.engine.toolchains import GFX942_TOOLCHAINS as TOOLCHAINS  # noqa: E402
MODES = {1: "unified", 0: "copy"}
# OpenMP-side feature prefixes of the generator's feature lists (base:*
# are base-language features, swarm:* generator knobs)
OMP_PREFIXES = ("dir:", "clause:", "map:", "red:", "kernel:", "scalar:",
                "defaultmap:")
# run-time failure classes (among programs the toolchain compiled)
RUN_FAIL = ("wrong_code", "run_error", "host_fallback")
SINGLE_GROUP = {"types": "b1", "derived": "b2", "alloc": "b3",
                "declare": "b4", "multitu": "b5"}
NO_BASE = ("b0", "c1")


@dataclass
class Prog:
    run: str
    mode: str
    seed: int
    features: frozenset
    classes: dict                   # toolchain -> fuzz class
    reasons: dict = field(default_factory=dict)
    validity: str = "valid"
    check: str = "ok"


def _mode_of(run_dir: Path) -> str:
    meta = run_dir / "meta.json"
    x = 1
    if meta.is_file():
        s = json.loads(meta.read_text()).get("sessions") or [{}]
        x = s[0].get("xnack", 1)
    return MODES[int(x)]


def load_run(run_dir: Path) -> list[Prog]:
    run_dir = Path(run_dir)
    progs, _ = fe.load(run_dir)
    mode = _mode_of(run_dir)
    out = []
    for p in progs:
        out.append(Prog(run_dir.name, mode, p.seed,
                        frozenset(f for f in p.features
                                  if not f.startswith("swarm:")),
                        {t: r.cls for t, r in p.results.items()},
                        {t: r.reason for t, r in p.results.items()},
                        p.validity, p.check))
    return out


def load(runs) -> list[Prog]:
    out = []
    for r in runs:
        out += load_run(FUZZ / r if isinstance(r, str) else r)
    return out


def judged(progs) -> list[Prog]:
    """Programs that passed the legality checks and are not excluded by
    the host check (noncompliant)."""
    return [p for p in progs if p.check == "ok" and
            p.validity != "noncompliant"]


def outcome(cls: str, reason: str) -> str:
    """The report's outcome class: a run_error that is a signal is a
    crash; a compile timeout is its own class."""
    if cls == "run_error" and reason.startswith("crash"):
        return "crash"
    if cls == "timeout" and "compile" in reason:
        return "compile_timeout"
    return cls


def rates(progs) -> dict:
    """{mode: {toolchain: Counter(outcome)}} over the judged programs."""
    out: dict = defaultdict(lambda: defaultdict(Counter))
    for p in judged(progs):
        for t, c in p.classes.items():
            out[p.mode][t][outcome(c, p.reasons.get(t, ""))] += 1
    return {m: {t: dict(c) for t, c in v.items()} for m, v in out.items()}


# --- the confirmer's verdicts -------------------------------------------------------------

def load_batch(paths) -> list[dict]:
    out = []
    for p in paths:
        for ln in Path(p).read_text().splitlines():
            if ln.strip():
                out.append(json.loads(ln))
    return out


def verdict_counts(batch: list[dict]) -> dict:
    """{mode: {toolchain: Counter(verdict)}}."""
    out: dict = defaultdict(lambda: defaultdict(Counter))
    for r in batch:
        c = r["case"]
        out[c["mode"]][c["toolchain"]][r["verdict"]] += 1
    return {m: {t: dict(c) for t, c in v.items()} for m, v in out.items()}


def rule_counts(batch: list[dict]) -> dict:
    out: dict = defaultdict(Counter)
    for r in batch:
        out[r["case"]["toolchain"]][(r["verdict"], r["rule"])] += 1
    return out


def _key(reason: str) -> str:
    """A rejection's message without positions, names and numbers."""
    t = re.sub(r"File = [^|]*\|", "", reason)
    t = re.sub(r"ftn: ERROR \S+", "ftn: ERROR", t)
    t = re.sub(r'loc\("[^"]*":\d+:\d+\)', "loc", t)
    t = re.sub(r"<tmpdir>\S*|/\S+", "<path>", t)
    t = re.sub(r'"[A-Za-z0-9_$%]+"', '"X"', t)
    t = re.sub(r"\d+", "N", t)
    return " ".join(t.split())[:150]


def reject_drivers(batch: list[dict], top: int = 12) -> dict:
    """{toolchain: [(cells, verdict, rule, cause)]} of the compile
    rejections: the cause is the later form R11c attributes it to, else
    the message key."""
    out: dict = defaultdict(Counter)
    for r in batch:
        c = r["case"]
        if c["outcome"] != "rejected":
            continue
        m = re.search(r"later form (\S+) \(", r.get("reason") or "")
        cause = f"later form {m.group(1)}" if m else _key(c["reason"])
        out[c["toolchain"]][(r["verdict"], r["rule"], cause)] += 1
    return {t: [(n, *k) for k, n in c.most_common(top)]
            for t, c in out.items()}


# --- feature pairs ----------------------------------------------------------------------------

def _is_base(f: str) -> bool:
    return f.startswith("base:") and not f.startswith("base:group:")


def _is_omp(f: str) -> bool:
    return f.startswith(OMP_PREFIXES)


def fail_rows(progs, tc: str, mode: str | None = None,
              fail=RUN_FAIL, excluded=frozenset()) -> list[tuple]:
    """(features, failed) of the judged programs `tc` compiled (not a
    compile rejection, compile timeout or harness error) in `mode`;
    `excluded`: (run, seed, toolchain) cells the confirmer did not call a
    failure of the compiler (our_bug, noncompliant, flaky, environment)."""
    out = []
    for p in judged(progs):
        if mode and p.mode != mode:
            continue
        c = p.classes.get(tc)
        if c is None or c in ("compile_reject", "harness_error"):
            continue
        if c == "timeout" and "compile" in p.reasons.get(tc, ""):
            continue
        if (p.run, p.seed, tc) in excluded:
            continue
        out.append((p.features, c in fail))
    return out


def _fisher_greater(k: int, n: int, k0: int, n0: int) -> float:
    """One-sided Fisher exact p-value that the rate k/n exceeds k0/n0."""
    from scipy.stats import fisher_exact
    return float(fisher_exact([[k, n - k], [k0, n0 - k0]],
                              alternative="greater")[1])


def _rate(k: int, n: int) -> float:
    return k / n if n else 0.0


def interactions(rows, min_n: int = 30, min_fail: int = 5,
                 factor: float = 2.0, p_max: float = 0.01,
                 alone: dict | None = None) -> list[dict]:
    """Base-language x OpenMP feature pairs whose programs fail at least
    `factor` times as often as the programs with either feature without
    the other (each side at least `min_n` programs; the pair at least
    `min_n` programs and `min_fail` failures; one-sided Fisher p below
    `p_max` against the programs with exactly one of the two). `alone`:
    {feature: (failures, programs)} of the same toolchain in the
    single-group campaigns, shown and required not to explain the pair."""
    n1, k1 = Counter(), Counter()
    n2, k2 = Counter(), Counter()
    for feats, hit in rows:
        base = [f for f in feats if _is_base(f)]
        omp = [f for f in feats if _is_omp(f)]
        for f in base + omp:
            n1[f] += 1
            k1[f] += hit
        for a in base:
            for b in omp:
                n2[(a, b)] += 1
                k2[(a, b)] += hit
    out = []
    for (a, b), n in n2.items():
        k = k2[(a, b)]
        if n < min_n or k < min_fail:
            continue
        na, ka = n1[a] - n, k1[a] - k          # a without b
        nb, kb = n1[b] - n, k1[b] - k          # b without a
        if na < min_n or nb < min_n:
            continue
        r, ra, rb = _rate(k, n), _rate(ka, na), _rate(kb, nb)
        if r < factor * max(ra, rb, 1e-9):
            continue
        p = _fisher_greater(k, n, ka + kb, na + nb)
        if p > p_max:
            continue
        row = {"base": a, "omp": b, "programs": n, "failures": k,
               "rate": round(r, 3), "base_without": [ka, na],
               "omp_without": [kb, nb], "p": p}
        if alone is not None:
            for f, key in ((a, "base_alone"), (b, "omp_alone")):
                kk, nn = alone.get(f, (0, 0))
                row[key] = [kk, nn]
            # the single-group campaigns: a feature that fails as often
            # alone explains the pair
            row["explained_alone"] = any(
                nn >= 10 and _rate(kk, nn) * factor > r
                for kk, nn in (row["base_alone"], row["omp_alone"]))
        out.append(row)
    out.sort(key=lambda r: (r["p"], -r["rate"]))
    return _merge_aliases(out)


def _merge_aliases(rows: list[dict]) -> list[dict]:
    """Features that always occur together (kernel:inred, clause:
    in_reduction and dir:taskgroup) give rows with the same counts: one
    row, the names joined with " / " (first the OpenMP side, then the
    base side)."""
    for side, other in (("omp", "base"), ("base", "omp")):
        merged: dict = {}
        order = []
        for r in rows:
            key = (r[other], r["programs"], r["failures"],
                   tuple(r["base_without"] if side == "omp"
                         else r["omp_without"]))
            if key in merged:
                m = merged[key]
                if r[side] not in m[side].split(" / "):
                    m[side] += " / " + r[side]
            else:
                merged[key] = dict(r)
                order.append(key)
        rows = [merged[k] for k in order]
    return rows


def alone_rates(tc: str, fail=RUN_FAIL) -> dict:
    """{feature: (failures, programs)} on `tc` in the single-group
    campaigns: a base feature in its group's campaign (b1-b5), an OpenMP
    feature in the campaigns without base-language features (b0, c1)."""
    out: dict = {}
    for grp, run in SINGLE_GROUP.items():
        if not (FUZZ / run).is_dir():
            continue
        rows = fail_rows(load_run(FUZZ / run), tc, fail=fail)
        for feats, hit in rows:
            for f in feats:
                if _is_base(f):
                    k, n = out.get(f, (0, 0))
                    out[f] = (k + hit, n + 1)
    for run in NO_BASE:
        if not (FUZZ / run).is_dir():
            continue
        for feats, hit in fail_rows(load_run(FUZZ / run), tc, fail=fail):
            for f in feats:
                if _is_omp(f):
                    k, n = out.get(f, (0, 0))
                    out[f] = (k + hit, n + 1)
    return out


# --- copy mode ---------------------------------------------------------------------------------

def copy_mode(progs) -> dict:
    """The copy-mode runs against the unified-mode runs of the same seeds:
    {toolchain: {"pairs": n, "only_copy": [(seed, x1 class, x0 class)],
    "only_unified": [...], "transitions": Counter((x1, x0))}}; a cell
    fails when its class is not agree; compile rejections on both sides
    are not compared (they do not depend on the mode)."""
    x1 = {p.seed: p for p in judged(progs) if p.mode == "unified"}
    x0 = {p.seed: p for p in judged(progs) if p.mode == "copy"}
    out = {}
    for tc in TOOLCHAINS:
        only0, only1, trans, n = [], [], Counter(), 0
        for s in sorted(set(x1) & set(x0)):
            a = x1[s].classes.get(tc)
            b = x0[s].classes.get(tc)
            if a is None or b is None:
                continue
            a = outcome(a, x1[s].reasons.get(tc, ""))
            b = outcome(b, x0[s].reasons.get(tc, ""))
            n += 1
            trans[(a, b)] += 1
            if a == "agree" and b != "agree":
                only0.append((s, a, b))
            elif b == "agree" and a != "agree":
                only1.append((s, a, b))
        out[tc] = {"pairs": n, "only_copy": only0, "only_unified": only1,
                   "transitions": trans}
    return out


def pct(k: int, n: int) -> str:
    return f"{100 * k / n:.1f}%" if n else "-"


# --- rendering ------------------------------------------------------------------------------

OUTCOMES = ("agree", "compile_reject", "ice", "compile_timeout",
            "wrong_code", "crash", "run_error", "timeout", "host_fallback",
            "harness_error")
VERDICTS = ("compiler_bug", "copy_mode_failure", "unified_memory_failure",
            "arch_specific", "unsupported", "unsupported_everywhere",
            "needs_unified_memory", "requirement_refused", "unspecified",
            "noncompliant", "our_bug", "flaky", "environment",
            "needs_human")


def table(head, rows) -> list[str]:
    out = ["| " + " | ".join(map(str, head)) + " |",
           "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(c).replace("|", "\\|") for c in r) + " |"
            for r in rows]
    return out


def rate_table(r: dict) -> list[str]:
    rows = []
    for mode in ("unified", "copy"):
        for tc in TOOLCHAINS:
            c = r.get(mode, {}).get(tc)
            if not c:
                continue
            n = sum(c.values())
            rows.append([mode, tc, n] + [f"{c.get(o, 0)} ({pct(c.get(o, 0), n)})"
                                         if c.get(o) else "" for o in
                                         OUTCOMES])
    return table(["mode", "toolchain", "programs"] + list(OUTCOMES), rows)


def verdict_table(v: dict) -> list[str]:
    used = [x for x in VERDICTS if any(x in c for m in v.values()
                                       for c in m.values())]
    rows = []
    for mode in ("unified", "copy"):
        for tc in TOOLCHAINS:
            c = v.get(mode, {}).get(tc)
            if not c:
                continue
            rows.append([mode, tc, sum(c.values())] + [c.get(x, "")
                                                       for x in used])
    return table(["mode", "toolchain", "failing cells"] + used, rows)


MIN_PAIR = 30   # programs with both features (and with each feature
#                 without the other) for a pair to be judged


def excluded_cells(batch: list[dict], runs_by_mode: dict) -> frozenset:
    """(run, seed, toolchain) of failing cells the confirmer did not call
    a failure of the compiler (our_bug, noncompliant, environment,
    flaky): left out of the pair rates. `runs_by_mode`: the campaign's
    run directory of each memory mode."""
    out = set()
    for r in batch:
        if r["verdict"] in ("our_bug", "noncompliant", "environment",
                            "flaky"):
            _, seed = r["case"]["program"]["ident"].rsplit(":", 1)
            run = runs_by_mode[r["case"]["mode"]]
            out.add((run, int(seed), r["case"]["toolchain"]))
    return frozenset(out)


def interaction_section(progs, batch, mode="unified", fail=RUN_FAIL,
                        label="run-time failure", top=12) -> tuple:
    """(markdown lines, rows per toolchain) of the base x OpenMP feature
    pairs of `mode` (see ``interactions``)."""
    ex = excluded_cells(batch, {p.mode: p.run for p in progs})
    L, data = [], {}
    for tc in TOOLCHAINS:
        rows = fail_rows(progs, tc, mode, fail, ex)
        got = interactions(rows, min_n=MIN_PAIR,
                           alone=alone_rates(tc, fail))
        new = [g for g in got if not g["explained_alone"]]
        data[tc] = got
        n = len(rows)
        k = sum(h for _, h in rows)
        L += ["", f"#### {tc}: {label} ({k} of {n} programs it did not reject, "
              f"{pct(k, n)}); {len(got)} pairs, {len(new)} not explained "
              "by a feature alone"]
        if not got:
            continue
        L += table(["base feature", "OpenMP feature", "both: fail/programs",
                    "base without the OpenMP feature",
                    "OpenMP feature without the base feature",
                    "base alone (b1-b5)", "OpenMP alone (b0, c1)", "p",
                    "interaction"],
                   [[g["base"], g["omp"],
                     f"{g['failures']}/{g['programs']} ({pct(g['failures'], g['programs'])})",
                     f"{g['base_without'][0]}/{g['base_without'][1]}",
                     f"{g['omp_without'][0]}/{g['omp_without'][1]}",
                     f"{g['base_alone'][0]}/{g['base_alone'][1]}",
                     f"{g['omp_alone'][0]}/{g['omp_alone'][1]}",
                     f"{g['p']:.1e}",
                     "no (explained alone)" if g["explained_alone"]
                     else "yes"] for g in got[:top]])
    return L, data


def copy_section(progs, batch, camp: str) -> tuple:
    cm = copy_mode(progs)
    vb = {}
    for r in batch:
        c = r["case"]
        vb[(c["program"]["ident"], c["toolchain"], c["mode"])] = r
    L = []
    rows = []
    for tc in TOOLCHAINS:
        e = cm[tc]
        v0 = Counter(vb[(f"{camp}:{s}", tc, "copy")]["verdict"]
                     for s, _, _ in e["only_copy"]
                     if (f"{camp}:{s}", tc, "copy") in vb)
        v1 = Counter(vb[(f"{camp}:{s}", tc, "unified")]["verdict"]
                     for s, _, _ in e["only_unified"]
                     if (f"{camp}:{s}", tc, "unified") in vb)
        rows.append([tc, e["pairs"], len(e["only_copy"]),
                     ", ".join(f"{k} {n}" for k, n in v0.most_common()),
                     len(e["only_unified"]),
                     ", ".join(f"{k} {n}" for k, n in v1.most_common())])
    L += table(["toolchain", "seeds in both modes",
                "fail only in copy mode", "their verdicts (copy cell)",
                "fail only in unified mode", "their verdicts (unified cell)"],
               rows)
    return L, cm


def _verdicts_final(batch) -> dict:
    out: dict = defaultdict(lambda: defaultdict(Counter))
    for r in batch:
        c = r["case"]
        out[c["mode"]][c["toolchain"]][r.get("final", r["verdict"])] += 1
    return {m: {t: dict(c) for t, c in v.items()} for m, v in out.items()}


def instances(batch) -> list:
    """(finding, toolchain, cells) of the bug verdicts that are instances
    of an indexed finding."""
    c = Counter()
    for r in batch:
        if r.get("final", r["verdict"]) in ("compiler_bug",
                                            "copy_mode_failure",
                                            "unified_memory_failure") and \
                r.get("findings"):
            c[(Path(r["findings"][0]["file"]).name,
               r["case"]["toolchain"])] += 1
    return sorted(((f, t, n) for (f, t), n in c.items()),
                  key=lambda x: (-x[2], x[0], x[1]))


def render_generated(camp: str, progs, batch, decisions=None,
                     spot=None) -> str:
    """The generated block of data/reports/fuzz-<camp>.md: rates, verdicts,
    rejection drivers, decisions, spot checks, interactions, copy mode,
    finding instances."""
    L = []
    runs = sorted({(p.run, p.mode) for p in progs})
    allp = len(progs)
    ok = sum(p.check == "ok" for p in progs)
    nc = sum(p.check == "ok" and p.validity == "noncompliant" for p in progs)
    L += ["### Programs", ""]
    L += table(["run", "memory mode", "programs", "passed the legality "
                "checks", "noncompliant (host check)"],
               [[r, m, sum(p.run == r for p in progs),
                 sum(p.run == r and p.check == "ok" for p in progs),
                 sum(p.run == r and p.check == "ok" and
                     p.validity == "noncompliant" for p in progs)]
                for r, m in runs])
    L += ["", f"Total {allp} programs, {ok} legal by the checks, {nc} "
          "noncompliant (left out of the rates below).", ""]
    L += ["### Outcome per compiler and memory mode", "",
          "Outcome classes of the stored runs (a run_error with a signal is "
          "a crash; host_fallback is a region that reported a host run "
          "under OMP_TARGET_OFFLOAD=mandatory).", ""]
    L += rate_table(rates(progs))
    if batch:
        L += ["", "### Confirmer verdicts per compiler and memory mode", "",
              "Every failing cell (`tools/confirm.py batch`), after the "
              "agent decisions of catalog/triage_28.yaml for the cases the "
              "rules leave needs_human.", ""]
        L += verdict_table(_verdicts_final(batch))
        L += ["", "#### By rule", ""]
        rc = Counter((r["case"]["toolchain"], r["rule"],
                      r.get("decided_by", "rules")) for r in batch)
        L += table(["toolchain", "rule", "decided by", "cells"],
                   [[t, ru, d, n] for (t, ru, d), n in sorted(rc.items())])
        L += ["", "### What the compile rejections are", "",
              "Each rejected cell by the verdict, the rule and its cause "
              "(the later form R11c names, else the diagnostic without "
              "positions and names); the twelve most frequent per "
              "toolchain.", ""]
        for tc, rows in sorted(reject_drivers(batch).items()):
            n = sum(r["case"]["toolchain"] == tc and
                    r["case"]["outcome"] == "rejected" for r in batch)
            L += ["", f"#### {tc} ({n} rejected cells)", ""]
            L += table(["cells", "verdict", "rule", "cause"],
                       [list(x) for x in rows])
        if decisions:
            L += ["", "### Agent decisions (needs_human)", ""]
            used = Counter(r.get("decided_by") for r in batch)
            L += table(["decision", "verdict", "cells", "basis"],
                       [[d.id, d.verdict, used.get(d.id, 0),
                         " ".join(d.basis.split())[:400]]
                        for d in decisions])
            left = Counter(r["rule"] for r in batch
                           if r.get("final") == "needs_human")
            L += ["", "Left needs_human: " + (", ".join(
                f"{k} {v}" for k, v in sorted(left.items())) or "none"), ""]
        if spot is not None:
            L += ["", "### Spot checks", ""] + spot
        L += ["", "### Instances of known findings", "",
              "Bug verdicts whose failure signature is an indexed finding's "
              "(offload/engine/confirm/findings.py).", ""]
        L += table(["finding", "toolchain", "cells"],
                   [list(x) for x in instances(batch)[:40]])
    L += ["", "### Feature pairs (base language x OpenMP)", "",
          f"Unified mode (s1). A pair is judged with at least {MIN_PAIR} "
          f"programs with both features and {MIN_PAIR} with each feature "
          "without the other, among the programs the toolchain compiled; "
          "it is listed when its programs fail at least twice as often as "
          "either side alone and a one-sided Fisher test against the "
          "programs with exactly one of the two gives p < 0.01. "
          "\"alone\" columns: the same toolchain in the single-group "
          "campaigns (b1-b5 for the base feature, b0 and c1 for the "
          "OpenMP feature); \"interaction yes\" means neither feature "
          "fails that often there either. Features that always occur "
          "together are one row (joined with /).", ""]
    for label, fail in (("run-time failure (wrong code, crash, run "
                         "error)", RUN_FAIL), ("ICE", ("ice",))):
        L += ["", f"#### {label}"]
        sec, _ = interaction_section(progs, batch or [], "unified", fail,
                                     label)
        L += sec
    L += ["", "### Copy mode (s1x0 against the same seeds of s1)", "",
          "A cell fails when its class is not agree; compile rejections "
          "are the same in both modes and are compared like any class.",
          ""]
    sec, cm = copy_section(progs, batch or [], camp)
    L += sec
    L += ["", "#### Class transitions (unified -> copy) of the cells that "
          "differ", ""]
    rows = []
    for tc in TOOLCHAINS:
        for (a, b), n in cm[tc]["transitions"].most_common():
            if a != b:
                rows.append([tc, a, b, n])
    L += table(["toolchain", "unified", "copy", "cells"], rows)
    return "\n".join(L) + "\n"
