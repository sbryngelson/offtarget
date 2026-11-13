"""What the stress campaigns found (data/reports/fuzz-stress.md).

Inputs are results/stress/<run>/programs.jsonl and rows.jsonl. Runs are merged:
a later row for the same program, toolchain, mode and variant replaces an
earlier one, and wingtip rows take the gate verdict of the Tuolumne run.
* A row counts toward compiler bugs only if its program is ``legal``, passed the
  legality gate, and its model is confirmed by sequential elision where it applies.
* ``unspecified``, ``impl_defined`` and ``illegal_probe`` programs are
  portability data, never bugs.
* A compile timeout or out-of-memory is a finding only if a smaller sibling
  compiled within the limits on the same toolchain and variant.
* A wrong answer names its kernels; other toolchains printing the model's value
  is a second source.
A bug's ``signature`` is toolchain family, class and key (the compiler message
key, the failure kind, or the axis and kernel kind of a wrong answer)."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "results" / "stress"
# the campaigns the doc and the dashboard read (later runs win)
STRESS_RUNS = ("s1-g1", "s1-g2", "s1-g3", "s1-g4", "s1-g5",
               "s1-acc", "s1-c", "s1-var", "nv1-omp", "nv1-acc", "nv1-c",
               "nv1-managed", "s2-fix", "s2-big", "s3-wp", "nv2-var",
               "f1-omp", "f1-acc", "f1-var", "f1-var-acc", "nv3-omp", "f4-wrap",
               "tioga-bp",
               "nv3-acc", "nv3-c", "nv3-var",
               # The CCE ftn heap-abort cells rerun in
               # build directories without "-1"
               "t43-clean", "t43-k-omp", "t43-k-acc")
ARM_RUNS = ("arm1-uniform", "arm1-steered", "arm1-stress")
BUG_CLASSES = ("wrong_code", "ice", "run_error", "run_timeout",
               "host_fallback", "compile_oom", "compile_timeout")
PORT = ("unspecified", "impl_defined", "illegal_probe")


def family(tc: str) -> str:
    return "afar" if tc.startswith("afar") else "nvhpc" if \
        tc.startswith("nvhpc") else "cce"


def _jl(p: Path) -> list:
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


# (F10): records made before programs carried their
# axis revision ("rev") get it once, from the revision the run used
# (``migrate``, which writes it into the run's files). Afterwards the only
# rule is: a record older than its axis's current revision
# (offload.engine.stress.AXIS_REV) is dropped. The history:
#   s1-*, nv1-* (3715681 .. 6973cf1): nest, clauses, random, contlines (C)
#     at revision 1;
#   s2-fix, s1-var (6b78cee), s3-wp, nv2-var (d971f48): nest 2, clauses 2,
#     random 2, contlines (C) 2, tuimp 1, oo.polymap 1.
LEGACY_REV = {
    "s1": {"nest": 1, "clauses": 1, "random": 1, "contlines-c": 1,
           "tuimp": 1, "oo.polymap": 1, "oo": 1},
    "s2": {"nest": 2, "clauses": 2, "random": 2, "contlines-c": 2,
           "tuimp": 1, "oo.polymap": 1, "oo": 2},
}


def _legacy_rev(run: str, axis: str, lang: str) -> int:
    era = "s2" if run.startswith(("s2-", "s3-", "nv2-")) or \
        run == "s1-var" else "s1"
    key = f"{axis}-c" if lang == "c" else axis
    base = axis.split(".")[0]
    t = LEGACY_REV[era]
    return t.get(key, t.get(base, 1) if base in ("nest", "clauses",
                                                 "random", "tuimp") else 1)


def migrate(run: str) -> int:
    """Write "rev" into the records of `run` that lack it; the number of
    records changed. The original files are kept as *.pre-rev."""
    import shutil
    d = OUT / run
    n = 0
    for name in ("programs.jsonl", "rows.jsonl"):
        p = d / name
        if not p.exists():
            continue
        recs = _jl(p)
        if all("rev" in r for r in recs):
            continue
        shutil.copy(p, p.with_suffix(".jsonl.pre-rev"))
        out = []
        for r in recs:
            if "rev" not in r and "axis" in r:
                r["rev"] = _legacy_rev(run, r["axis"], r.get("lang", "f90"))
                n += 1
            out.append(json.dumps(r))
        p.write_text("\n".join(out) + "\n")
    return n


def current(rec: dict) -> bool:
    from offload.engine.stress import axis_rev
    return rec.get("rev", 1) >= axis_rev(rec.get("axis", ""),
                                         rec.get("lang", "f90"))


def load(runs, canaries: bool = True) -> tuple[dict, list]:
    """(programs, rows) of the runs (later runs win). A changed
    canary of a run stops it (offload.engine.canary; `canaries` False: the
    reproduction gate's planning, which reads the rows as data)."""
    progs: dict = {}
    rows: dict = {}
    for run in runs:
        d = OUT / run
        if canaries:
            # a changed canary, or a run recorded
            # with provenance that has none and no exemption, stops it
            from offload.engine import canary
            canary.require_unchanged(
                [d / "canaries.jsonl"], f"stress run {run}",
                campaign_rows=[{"toolchain": r.get("toolchain"),
                                "xnack": r.get("mode"),
                                "git_rev": r.get("git_rev"),
                                "gate": r.get("gate")}
                               for r in _jl(d / "rows.jsonl")
                               if r.get("toolchain")])
        for p in _jl(d / "programs.jsonl"):
            if "id" in p and current(p):
                progs[p["id"]] = p
        for r in _jl(d / "rows.jsonl"):
            if "crash" in r or not current(r):
                continue
            if r["toolchain"].startswith("afar") and r["variant"] == \
                    "noinline" and r.get("lang", "f90") == "f90":
                continue        # flang has no -fno-inline (not a variant)
            r["run"] = run
            if r.get("cls") in ("run_error", "run_timeout"):
                # A stored run whose runtime reported
                # a capacity limit is a break point (stress_exec.judge)
                from offload.engine.harness import capacity_message
                line = capacity_message(r["toolchain"], r.get("output"))
                if line:
                    r["cls"], r["reason"] = "capacity", f"capacity: {line}"
            rows[(r["id"], r["toolchain"], r["mode"], r["variant"])] = r
    return progs, list(rows.values())


def valid(p: dict | None) -> bool:
    if p is None or p.get("gate", {}).get("stage") != "ok":
        return False
    e = p.get("elision")
    return e is None or bool(e.get("ok"))


def base_axis(axis: str) -> str:
    return axis.split(".")[0]


def wrong_kernel_kind(r: dict, prog: dict | None) -> str:
    if prog is None:
        return "?"
    kinds = []
    for k in r.get("bad_kernels") or []:
        desc = next((x for x in prog.get("kernels", [])
                     if x.startswith(k + ":")), "")
        m = re.match(r"\w+:(\w+)\(", desc)
        kinds.append(m.group(1) if m else "?")
    return "+".join(sorted(set(kinds))) or "?"


def signature(r: dict, prog: dict | None) -> str:
    from offload.engine.confirm.decisions import _msg_key
    cls = r["cls"]
    fam = family(r["toolchain"])
    lang = r.get("lang", "f90")
    model = r.get("model", "omp")
    if cls == "wrong_code":
        key = f"{r['axis']}:{wrong_kernel_kind(r, prog)}"
    elif cls in ("run_error", "run_timeout", "host_fallback"):
        key = f"{base_axis(r['axis'])}:" + re.sub(
            r"\d+", "N", (r.get("reason") or "").split(";")[0])[:40]
    else:
        key = _msg_key(r.get("reason") or "")
    return f"{fam}|{lang}/{model}|{cls}|{key}"


def siblings_ok(r: dict, rows_by: dict) -> bool:
    """A smaller program of the same axis compiled within the limits on
    the same toolchain and variant."""
    for o in rows_by.get((r["axis"], r.get("model"), r.get("lang"),
                          r["toolchain"], r["variant"]), []):
        if o["size"] < r["size"] and o["cls"] not in (
                "compile_timeout", "compile_oom", "harness_error",
                "skipped"):
            return True
    return False


def gate_unconfirmed(r: dict, verdicts: dict) -> str | None:
    """The reproduction gate's verdict of a stress row when it is
    not confirmed (offload.engine.gate; results/gate/verdicts.jsonl), else
    None (confirmed, or not gated: a row recorded before the gate keeps
    its outcome)."""
    v = verdicts.get(f"stress|{r['id']}|{r['toolchain']}|{r['mode']}|"
                     f"{r['variant']}")
    from offload.engine import gate as G
    if v is None or v.get("verdict") is None or G.counts(v):
        return None
    return v.get("decision") or v["verdict"]


def findings(progs: dict, rows: list, verdicts: dict | None = None) -> dict:
    """signature -> {rows, toolchains, axes, smallest program, agree}.
    A row the reproduction gate did not confirm is no bug row
    (counted in the signature's ``unconfirmed``)."""
    if verdicts is None:
        from offload.engine import gate as G
        verdicts = G.load_verdicts()
    by_prog = defaultdict(list)
    rows_by = defaultdict(list)
    for r in rows:
        by_prog[r["id"]].append(r)
        rows_by[(r["axis"], r.get("model"), r.get("lang"), r["toolchain"],
                 r["variant"])].append(r)
    out: dict = {}
    for r in rows:
        p = progs.get(r["id"])
        if r["cls"] not in BUG_CLASSES or r["legality"] != "legal" or \
                not valid(p):
            continue
        if r["cls"] in ("compile_timeout", "compile_oom") and \
                not siblings_ok(r, rows_by):
            continue
        if r["variant"] == "nordc":
            continue    # NVHPC documents nordc as no cross-file device calls
        s = norm_key(signature(r, p))
        f = out.setdefault(s, {"rows": 0, "toolchains": set(),
                               "modes": set(), "axes": set(),
                               "smallest": None, "agree_elsewhere": 0,
                               "reason": r["reason"][:200],
                               "unconfirmed": 0})
        if gate_unconfirmed(r, verdicts):
            f["unconfirmed"] += 1
            continue
        f["rows"] += 1
        f["toolchains"].add(r["toolchain"])
        f["modes"].add(r["mode"])
        f["axes"].add(r["axis"])
        lines = (p or {}).get("lines", 10 ** 9)
        if f["smallest"] is None or lines < f["smallest"][1]:
            f["smallest"] = (r["id"], lines, r["toolchain"], r["mode"],
                             r["variant"])
        if r["cls"] == "wrong_code":
            f["agree_elsewhere"] = max(f["agree_elsewhere"], sum(
                1 for o in by_prog[r["id"]] if o["cls"] == "agree"))
    # a signature none of whose rows the gate confirmed is no bug
    out = {k: f for k, f in out.items() if f["rows"]}
    for f in out.values():
        for k in ("toolchains", "modes", "axes"):
            f[k] = sorted(f[k], key=str)
    return out


def class_table(rows: list) -> dict:
    """(toolchain, mode) -> Counter of classes."""
    t = defaultdict(Counter)
    for r in rows:
        t[(r["toolchain"], r["mode"])][r["cls"]] += 1
    return t


def breakpoints(progs: dict, rows: list, maxima: dict | None = None,
                variant: str = "O2") -> list:
    """Per axis (variant), model and toolchain: the sizes run, the first
    size whose class is not agree (and that class), the largest size that
    agreed, compile seconds (steps) and peak RSS at the largest size, the
    real maximum of the axis (profile) and the break point relative to
    it."""
    groups = defaultdict(list)
    for r in rows:
        if r["variant"] != variant or r["legality"] == "illegal_probe":
            continue
        m = 0 if r["toolchain"].startswith("nvhpc") else 1
        if r["mode"] != m:
            continue
        groups[(r["axis"], r.get("lang", "f90"), r.get("model", "omp"),
                r["toolchain"])].append(r)
    out = []
    for (axis, lang, model, tc), rs in sorted(groups.items()):
        rs.sort(key=lambda r: r["size"])
        first_bad = next((r for r in rs if r["cls"] not in (
            "agree", "skipped")), None)
        last_ok = max((r["size"] for r in rs if r["cls"] == "agree"),
                      default=None)
        big = rs[-1]
        real = (maxima or {}).get(base_axis(axis), {}).get("max")
        out.append({
            "axis": axis, "lang": lang, "model": model, "toolchain": tc,
            "sizes": [r["size"] for r in rs],
            "first_fail": first_bad["size"] if first_bad else None,
            "first_fail_class": first_bad["cls"] if first_bad else None,
            "first_fail_reason": (first_bad["reason"][:120]
                                  if first_bad else ""),
            "largest_agree": last_ok,
            "compile_s_at_largest": round(sum(s["s"] for s in big.get(
                "steps", [])), 1),
            "rss_mib_at_largest": round(big.get("peak_rss_kib", 0) / 1024),
            "real_max": real,
            "fail_over_real": (round(first_bad["size"] / real, 2)
                               if first_bad and real else None)})
    return out


def scaling(rows: list, axes=("kernels", "private", "locals", "exprs.expr",
                              "args", "declare", "clauses", "nest",
                              "map", "reduction")) -> dict:
    """axis -> toolchain -> [(size, compile seconds of the steps, peak RSS
    MiB, class)] at -O2 (mode 1 rows on AMD; mode 0 on NVHPC)."""
    out = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r["axis"] not in axes or r["variant"] != "O2":
            continue
        if r["mode"] != (0 if r["toolchain"].startswith("nvhpc") else 1):
            continue
        key = f"{r['axis']}/{r.get('lang', 'f90')}/{r.get('model', 'omp')}"
        out[key][r["toolchain"]].append(
            (r["size"], round(sum(s["s"] for s in r.get("steps", [])), 2),
             round(r.get("peak_rss_kib", 0) / 1024), r["cls"]))
    for a in out.values():
        for tc in a:
            a[tc].sort()
    return {k: dict(v) for k, v in out.items()}


def portability(progs: dict, rows: list) -> list:
    """Outcomes of the programs whose behaviour the specification leaves
    unspecified or implementation-defined, and of the illegal probes."""
    t = defaultdict(Counter)
    for r in rows:
        if r["legality"] in PORT:
            t[(r["legality"], r["axis"], r["toolchain"])][r["cls"]] += 1
    return [{"legality": a, "axis": b, "toolchain": c, "classes": dict(v)}
            for (a, b, c), v in sorted(t.items())]


def observations(rows: list) -> dict:
    """The scalar routes' undefined observations (OBS lines): (route,
    what) -> toolchain/mode -> values seen."""
    out = defaultdict(lambda: defaultdict(Counter))
    for r in rows:
        for k, v in (r.get("obs") or {}).items():
            kern, route, what, j = k.split(":")
            out[f"{route}:{what}"][f"{r['toolchain']}/{r['mode']}"][v] += 1
    return {k: {t: dict(c) for t, c in v.items()} for k, v in out.items()}


def prerun_refusals(rows: list) -> dict:
    """(refusal kind, layout) -> program ids the pre-run check refused
    (offload.engine.prerun.refusal_kind)."""
    from offload.engine.prerun import refusal_kind
    out: dict = defaultdict(list)
    for r in rows:
        if r.get("cls") != "prerun_refused":
            continue
        key = (refusal_kind(r.get("reason") or ""),
               r.get("layout") or "single")
        if r.get("id") not in out[key]:
            out[key].append(r.get("id"))
    return dict(out)


def generator_defects(progs: dict) -> list:
    """Programs the gate rejected although labelled legal, or whose
    sequential elision disagrees with the model."""
    out = []
    for p in progs.values():
        if p.get("legality") == "illegal_probe":
            continue
        g = p.get("gate", {})
        e = p.get("elision")
        if g.get("stage") != "ok" or (e is not None and not e.get("ok")):
            out.append({"id": p["id"], "gate": g, "elision": e})
    return out


def norm_key(sig: str) -> str:
    """A signature without compiler-version strings and positions (one
    defect seen by CCE 19, 20 and 21 is one signature)."""
    sig = re.sub(r"\(<path> line N, version [^)]*\)?", "", sig)
    sig = re.sub(r"version \S+", "", sig)
    return re.sub(r"\s+", " ", sig).strip()


CONFIRM_OUTCOME = {"wrong_code": "wrong_answer", "ice": "ice",
                   "run_error": "crash", "run_timeout": "timeout",
                   "timeout": "timeout", "host_fallback": "fell_back_to_host",
                   "compile_timeout": "timeout", "compile_oom": "compile_oom"}
_IDX = None


def confirm_signature(tc: str, cls: str, reason: str, lang: str,
                      text: str, pid: str = "", output: str = "",
                      build_dir: str = "", opt: str = "") -> str:
    """The confirmer's signature of a failure (offload.engine.confirm:
    decisions.signature without the rule, F6): the
    finding it duplicates (findings.dedupe), else the ICE site, the abort
    signal, the message key; an unlinked wrong answer is one signature per
    toolchain family (the confirmer keeps a wrong answer by its verdict
    alone until it is minimized and linked)."""
    global _IDX
    from offload.engine.confirm import findings as FI
    from offload.engine.confirm.decisions import _msg_key
    if _IDX is None:
        _IDX = FI.index()
    out = CONFIRM_OUTCOME.get(cls, cls)
    rsn = "compile timeout" if cls == "compile_timeout" else (reason or "")
    fam = family(tc)
    g = FI.group(out, rsn)
    try:
        hits = FI.dedupe(tc, lang, out, rsn, text, pid, findings=_IDX,
                         output=output, build_dir=build_dir, opt=opt)
    except Exception:
        hits = []
    if hits:
        return f"{fam}|{g}|finding {Path(hits[0]['file']).name}"
    if g == "ice":
        key = FI.site_of(rsn, output) or FI.strip_site(FI.normalize(rsn))
    elif g == "abort":
        key = FI.signal_of(rsn + " " + output) or _msg_key(rsn)
    elif g == "wrong":
        key = "wrong answer (unlinked)"
    else:
        key = _msg_key(rsn)
    return norm_key(f"{fam}|{g}|{key}")


def _stress_spec(pid: str) -> dict:
    m = re.match(r"^(.*)-(omp|acc|c)-(\d+)-(\d+)(?:-(per_unit|partition))?$",
                 pid)
    return {"axis": m.group(1), "model": m.group(2), "size": int(m.group(3)),
            "seed": int(m.group(4)), "layout": m.group(5) or "single"}


def _stress_text(pid: str) -> str:
    from offload.engine import stress as S
    from offload.engine import stress_c as C
    sp = _stress_spec(pid)
    if sp["model"] == "c":
        p = C.build_c(sp["axis"], sp["size"], sp["seed"], sp["layout"])
    else:
        p = S.build(sp["axis"], sp["size"], sp["seed"], sp["model"],
                    sp["layout"])
    return "\n".join(t for _, t in p.files)


def budget(run: str) -> dict:
    """An arm of the comparison: programs judged, the CPU its tasks used,
    and its distinct failures by confirmer signature (compile timeouts and
    out-of-memory only with a smaller sibling that compiled; stress rows of
    an older axis revision dropped)."""
    from offload.engine.fuzz import generate
    d = OUT / run
    meta = json.loads((d / "meta.json").read_text()) if \
        (d / "meta.json").exists() else {}
    out = {"run": run, "arm": meta.get("arm"), "elapsed_s":
           meta.get("elapsed_s"), "workers": meta.get("workers")}
    sigs = Counter()
    programs = judged = 0
    task_s = 0.0
    for p in _jl(d / "fuzz" / "programs.jsonl"):
        if "results" not in p:
            continue
        programs += 1
        task_s += sum(r.get("compile_s", 0) + r.get("run_s", 0)
                      for r in p["results"].values())
        if p.get("check") != "ok" or p.get("validity", "valid") != "valid":
            continue
        judged += 1
        text = None
        for tc, r in p["results"].items():
            if r["cls"] in ("agree", "compile_reject", "harness_error"):
                continue
            if text is None:
                text = generate(p["seed"], p["gen_version"],
                                tuple(p.get("base") or ())).source
            sigs[confirm_signature(tc, r["cls"], r["reason"], "f90", text,
                                   f"fuzz:{p['seed']}",
                                   r.get("output", ""))] += 1
    sp = {p["id"]: p for p in _jl(d / "stress" / "programs.jsonl")
          if "id" in p}
    srows = [r for r in _jl(d / "stress" / "rows.jsonl") if "crash" not in r]
    rows_by = defaultdict(list)
    for r in srows:
        rows_by[(r["axis"], r.get("model"), r.get("lang"), r["toolchain"],
                 r["variant"])].append(r)
    ids, stale = set(), 0
    from offload.engine.stress import axis_rev
    for r in srows:
        task_s += r.get("compile_s", 0) + r.get("run_s", 0)
        # the arm's rows predate revision records: clauses and random
        # rows are of the racy revision (F1)
        if r["axis"].split(".")[0] in ("clauses", "random") and \
                r.get("rev", 1) < axis_rev(r["axis"]):
            stale += 1
            continue
        ids.add(r["id"])
        p = sp.get(r["id"])
        if r["cls"] not in BUG_CLASSES or r["legality"] != "legal" or \
                not valid(p):
            continue
        if r["cls"] in ("compile_timeout", "compile_oom") and \
                not siblings_ok(r, rows_by):
            continue
        sigs[confirm_signature(r["toolchain"], r["cls"], r["reason"],
                               r.get("lang", "f90"), _stress_text(r["id"]),
                               r["id"], r.get("output", ""),
                               r.get("build_dir", ""), r["variant"])] += 1
    programs += len(ids)
    judged += sum(1 for i in ids if valid(sp.get(i)))
    hours = task_s / 3600
    out.update({"programs": programs, "judged": judged,
                "task_cpu_h": round(hours, 2), "stale_rows": stale,
                "signatures": dict(sigs), "distinct": len(sigs),
                "linked": sum(1 for k in sigs if "|finding " in k),
                "unlinked": sum(1 for k in sigs if "|finding " not in k),
                "per_cpu_h": round(len(sigs) / max(1e-9, hours), 2)})
    return out


def known_signatures() -> set:
    """ICE / rejection message keys and run-failure kinds of every earlier
    fuzz campaign (results/fuzz/*/programs.jsonl), for 'new outside
    existing findings'."""
    from offload.engine.fuzz_steer import signature as fsig
    known = set()
    for f in sorted((ROOT / "results" / "fuzz").glob("*/programs.jsonl")):
        if f.parent.name.startswith(("arm", "t39")):
            continue
        for p in _jl(f):
            for tc, r in (p.get("results") or {}).items():
                if r.get("cls") in ("ice", "run_error", "timeout"):
                    known.add(fsig(r["cls"], r.get("reason", ""), tc))
    return known
