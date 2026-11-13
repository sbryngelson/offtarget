"""Validation of the confirmer against hand verdicts.

Each hand verdict becomes the cases (stored cells) it judges:
* ``mode_differences``, ``arch_entries``: catalog/mode_differences.yaml; the
  failing cells of the class's mode, or of the named compiler's gfx90a twin.
* ``triage``: catalog/expected_triage.yaml; compiler_wrong gives compiler_bug,
  implementation_defined gives unspecified.
* ``expected``: results/expected; a failing cell with a trusted verdict is a bug.
* ``fuzz_findings``: data/findings/fuzz/<run>-<seed>-<toolchain>.f90 and its
  "also fails on" toolchains: compiler_bug.
* ``live``: hand-written findings run end to end (``LIVE_FINDINGS``): compiler_bug.
The agreement matrix compares the rule verdict with the hand verdict; the bug
verdicts (compiler_bug, copy_mode_failure, unified_memory_failure,
arch_specific) agree as a group. Each disagreement is listed with the deciding rule."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from fnmatch import fnmatchcase
from pathlib import Path

import yaml

from offload.engine.confirm import collectors as C
from offload.engine.confirm import engine as EN
from offload.engine.confirm import findings as FI
from offload.engine.confirm import ingest as I
from offload.engine.confirm.model import PASSING, RUN_FAILURES
from offload.engine.confirm.store import Store
from offload.engine.toolchains import TOOLCHAINS, base_name

ROOT = Path(__file__).resolve().parent.parent.parent.parent
OUT = ROOT / "results" / "confirm" / "validation.jsonl"
DOC = ROOT / "data" / "reports" / "confirm-validation.md"
BUG = ("compiler_bug", "copy_mode_failure", "unified_memory_failure",
       "arch_specific")
MODE_CLASS = {"copy_mode_failure": ("copy_mode_failure", ("copy",)),
              "unified_memory_failure": ("unified_memory_failure",
                                         ("unified",)),
              "needs_unified_memory": ("needs_unified_memory", ("copy",)),
              "requirement_refused": ("requirement_refused", ("copy",)),
              "both_wrong": ("compiler_bug", ("unified", "copy")),
              "x1_oracle_blind": ("compiler_bug", ("copy",))}
ARCH_CLASS = {"intermittent": "flaky", "gfx90a_failure": "arch_specific",
              "x0_emulation_gap": "arch_specific",
              "gfx942_failure": "arch_specific",
              "both_wrong": "compiler_bug",
              "needs_unified_memory": "needs_unified_memory",
              "requirement_refused": "requirement_refused",
              "not_verifiable": "needs_human"}
# hand-written findings reproduced end to end on a compute node
LIVE_FINDINGS = (
    ("cce19-target-parallel-guarded-loop.f90", "cce21", "unified"),
    ("afar-cce19-character-defaultmap.f90", "afar", "unified"),
    ("cce-mapper-next-map-copy-back.f90", "cce19", "copy"),
    ("cce21-in-reduction-taskwait-link.f90", "cce21", "unified"),
    ("cce19-target-parallel-single-ice.f90", "cce20", "unified"),
    ("afar-nontemporal-assumed-shape-ice.f90", "afar", "unified"),
    ("cce-c-map-delete-refcount.c", "cce21", "copy"),
    ("multithread-allocatable-section-maps.f90", "cce19", "unified"),
    ("afar-flang-firstprivate-map-two-targets.f90", "afar", "unified"),
    ("cce21-defaultmap-aggregate-flag.f90", "cce21", "unified"),
)


def agrees(hand: str, rule: str) -> bool:
    return hand == rule or (hand in BUG and rule in BUG)


def _rows(idx: I.Index, kind="catalog"):
    return [r for r in idx.by_cell.values() if r.kind == kind]


def hand_cases(idx: I.Index) -> list[dict]:
    out = []
    md = yaml.safe_load((ROOT / "catalog" / "mode_differences.yaml")
                        .read_text())
    cat = [r for r in _rows(idx) if r.legal and r.outcome not in PASSING]
    for k, e in enumerate(md.get("entries") or []):
        hand, modes = MODE_CLASS[e["class"]]
        for r in cat:
            # a mode class describes run results; a pattern's rejected
            # cells (e.g. the 6.0 directive-name forms) are not its cases
            if TOOLCHAINS[r.toolchain].arch != "gfx942" or \
                    r.mode not in modes or r.outcome not in RUN_FAILURES:
                continue
            if any(fnmatchcase(r.ident, p) for p in e["programs"]) and \
                    any(fnmatchcase(r.toolchain, t) for t in e["toolchains"]):
                out.append({"source": "mode_differences", "row": r,
                            "hand": hand, "hand_detail": e["class"],
                            "ref": f"catalog/mode_differences.yaml entries"
                                   f"[{k}] ({e.get('finding', '')})"})
    for k, e in enumerate(md.get("arch_entries") or []):
        hand = ARCH_CLASS[e["class"]]
        for r in cat:
            if TOOLCHAINS[r.toolchain].arch == "gfx942":
                continue
            if any(fnmatchcase(r.ident, p) for p in e["programs"]) and \
                    any(fnmatchcase(base_name(r.toolchain), t)
                        for t in e["toolchains"]):
                out.append({"source": "arch_entries", "row": r,
                            "hand": hand, "hand_detail": e["class"],
                            "ref": f"catalog/mode_differences.yaml "
                                   f"arch_entries[{k}]"})
    tri = yaml.safe_load((ROOT / "catalog" / "expected_triage.yaml")
                         .read_text())
    for e in tri.get("entries") or []:
        for r in cat:
            if r.ident != e["program"]:
                continue
            if e["disposition"] == "compiler_wrong" and \
                    base_name(r.toolchain) in e.get("withdraw", ()):
                out.append({"source": "triage", "row": r,
                            "hand": "compiler_bug",
                            "hand_detail": "compiler_wrong",
                            "ref": f"catalog/expected_triage.yaml "
                                   f"{e['program']} ({e.get('finding')})"})
            elif e["disposition"] == "implementation_defined":
                out.append({"source": "triage", "row": r,
                            "hand": "unspecified",
                            "hand_detail": "implementation_defined",
                            "ref": f"catalog/expected_triage.yaml "
                                   f"{e['program']}"})
    out += _expected_cases(cat)
    out += _fuzz_cases(idx)
    out += _finding_program_cases(cat)
    return out


def _finding_program_cases(cat) -> list[dict]:
    """The catalog cells a hand-written finding names (data/findings/
    index.yaml ``programs``) on its toolchains, modes and arches, where
    the cell's run failed in the finding's way (its outcome group)."""
    out = []
    for f in FI.index():
        if not f.programs or f.scope == "out_of_scope":
            continue
        for r in cat:
            if base_name(r.toolchain) not in f.toolchains or \
                    r.mode not in f.modes or \
                    TOOLCHAINS[r.toolchain].arch not in f.arch or \
                    r.outcome not in RUN_FAILURES:
                continue
            if any(fnmatchcase(r.ident, p) for p in f.programs):
                out.append({"source": "finding_programs", "row": r,
                            "hand": "compiler_bug",
                            "hand_detail": "named by the finding",
                            "ref": f.file})
    return out


def _expected_cases(cat) -> list[dict]:
    T = C._tools_expected()
    recs = C._expected_records()
    by = defaultdict(list)
    for r in cat:
        by[r.ident].append(r)
    out = []
    for (kind, ident), (rec, x0, g90, path) in sorted(recs.items()):
        if kind != "catalog":
            continue
        _, main = T.evaluate_both(rec, x0, g90)
        copy = main
        if x0 is not None and T._copy_dependent(rec["version"],
                                                rec["program"]):
            _, copy = T.evaluate_copy_mode(rec, x0)
        for r in by.get(ident, ()):
            if r.outcome not in RUN_FAILURES or "compile" in r.reason:
                continue      # the expected value judges runs only
            vd = copy if r.mode == "copy" else main
            hand = {"trusted": "compiler_bug", "derived": "needs_human",
                    "provisional": "needs_human", "disputed": "needs_human",
                    "implementation_defined": "unspecified"}[vd.status]
            out.append({"source": "expected", "row": r, "hand": hand,
                        "hand_detail": f"expected {vd.status}",
                        "ref": f"{Path(path).name} {ident}"})
    return out


FUZZ_NAME = re.compile(r"^(?:(b\d)-)?(\d+)-(\w+)\.f90$")


def _fuzz_cases(idx: I.Index) -> list[dict]:
    out = []
    for p in sorted((ROOT / "data" / "findings" / "fuzz").glob("*.f90")):
        m = FUZZ_NAME.match(p.name)
        if not m:
            continue
        run = m.group(1) or "c1"
        seed, tc = m.group(2), m.group(3)
        text = FI.unfold(p.read_text())
        also = re.search(r"^! also fails on: (.*)$", text, re.M)
        tcs = [tc] + ([t.strip() for t in also.group(1).split(",")]
                      if also else [])
        mode = "copy" if "HSA_XNACK=0" in text else "unified"
        f = FI._fuzz_finding(p)
        for t in tcs:
            r = idx.get("fuzz", f"{run}:{seed}", t, mode)
            # "also fails on" is about the minimized program: a toolchain
            # whose cell of the original failed otherwise (e.g. a
            # not-implemented rejection) is not this finding's case
            if r is None or FI.group(r.outcome, r.reason) != f.group:
                continue
            out.append({"source": "fuzz_findings", "row": r,
                        "hand": "compiler_bug",
                        "hand_detail": "minimized fuzz finding",
                        "ref": str(p.relative_to(ROOT))})
    return out


# Fix: the resolution of a disagreement is computed from the
# case's own evidence (elision status and reason, derivation, sources,
# witnesses, the other cells, legality, registry hits), never from a
# template; a limitation of a tool (an elision that cannot read the
# program, a checker that could not run) is "investigate: tool
# limitation", so it is counted, not hidden.
TOOL_LIMIT = re.compile(r"not understood|could not run|cannot read|"
                        r"build failed|timed out|no single RESULT", re.I)


def tool_limited(res: dict) -> bool:
    """A needs_human that a tool limitation causes (an elision that cannot
    read the program, a checker that could not run), not rule
    strictness."""
    if res.get("verdict") != "needs_human":
        return False
    texts = [e.get("detail", "") for e in _ev(res, "elision")] + \
        [res.get("legality", {}).get("basis", "")]
    return any(TOOL_LIMIT.search(x or "") for x in texts)


def _ev(res: dict, name: str) -> list[dict]:
    return [e for e in res.get("evidence", []) if e["collector"] == name]


def _failing_others(res: dict) -> list[str]:
    return sorted({f"{c['toolchain']}/{c['mode']}"
                   + (" (port)" if c.get("variant", "").startswith("port")
                      else "") for c in
                   res.get("other_cells", []) if c["outcome"] not in
                   ("correct_on_device", "unobservable")})


_PORT_DER = re.compile(r"^the derivation of (\S+) \(port equivalence")
_REG_DER = re.compile(r"^spec reading (RUL-[A-Z0-9-]+)")


def _c_derivation_source(res: dict, der: dict) -> str:
    """The explanation of a C cell whose trusted
    expected value has a derivation the C slice's expected record
    (tools/campaigns/c_slices.py: own oracle and sequential elision) does not read,
    named by its actual source: the port entry's Fortran program at the
    same version (RUL-PORT-DERIVATION), or a registry spec reading that
    cites the program's version. "" when neither holds (the caller falls
    through to "investigate")."""
    prog = res["case"]["program"]
    pid, ver = prog.get("ident", ""), prog.get("version")
    detail = der.get("detail") or ""
    m = _PORT_DER.match(detail)
    if m:
        from offload.engine.confirm import ports
        got = ports.derivation_for(pid)
        fpid = m.group(1)
        if (got and got[1] == fpid and fpid.split("-")[0] ==
                pid.split("-")[0] == f"omp{ver}"):
            return ("explained: looser (port derivation): the rules' "
                    f"expected value has two sources ({', '.join(res['expected']['sources'])}); "
                    f"the derivation is that of {fpid}, the Fortran program "
                    f"{pid} ports (catalog/omp/port_equivalence.yaml, "
                    "RUL-PORT-DERIVATION); the C slice's results/expected "
                    "record reads the program's oracle and sequential "
                    "elision only")
        return ""
    m = _REG_DER.match(detail)
    if m and der.get("variant") == "registry":
        from offload.engine.confirm import registry as REG
        e = REG.entries().get(m.group(1))
        want = f"{ver // 10}.{ver % 10}" if isinstance(ver, int) else ""
        cites = [c for c in (e.citations if e else ())
                 if str(c["version"]) == want]
        if cites:
            c = cites[0]
            return (f"explained: looser (spec reading {e.id}, {c['version']} "
                    f"§{c['section']} p.{c['page']}): the rules derive the "
                    "value from the registry reading that names this program; "
                    "the C slice's results/expected record reads the "
                    "program's oracle and sequential elision only")
    return ""


def explain(res: dict, hand: str) -> str:
    """The resolution of a disagreement ("" when the verdicts agree),
    from the case's evidence."""
    rule, v = res["rule"], res["verdict"]
    if agrees(hand, v):
        return ""
    exp = res.get("expected") or {}
    el = (_ev(res, "elision") or [{}])[0]
    der = (_ev(res, "derivation") or [{}])[0]
    if rule.startswith("R22"):
        el_text = el.get("status", "not collected")
        if el.get("status") != "value" and el.get("detail"):
            el_text += f" ({el['detail'][:90]})"
        if el.get("detail") and TOOL_LIMIT.search(el["detail"]):
            return ("investigate: tool limitation: the elision could not "
                    f"read the program ({el['detail'][:120]})")
        lang = res["case"]["program"]["lang"]
        src = ", ".join(exp.get("sources") or []) or "none"
        if exp.get("status") == "derived":
            return ("explained: stricter (RUL-DERIVED-NEEDS-EXECUTION): "
                    f"sources {src} agree on {exp.get('value')} but no run "
                    "shows it in this memory mode; failing elsewhere: "
                    f"{', '.join(_failing_others(res)) or 'none'}; "
                    f"withdrawn: {', '.join(w['toolchain'] for w in res.get('withdrawn', [])) or 'none'}")
        meta = _ev(res, "metamorphic")
        return (f"explained: stricter (rule): one independent "
                f"source ({src}); missing a second: elision {el_text}; "
                f"derivation {der.get('value') or 'none'} ("
                f"{(der.get('detail') or 'no header derivation, port entry '
                    'or registry reading')[:80]}); metamorphic "
                f"{'not run (offline)' if not meta else meta[0]['status']}"
                + (" (a C program: no elision)" if lang == "c" else ""))
    if rule.startswith("R04"):
        basis = res.get("legality", {}).get("basis", "")
        if TOOL_LIMIT.search(basis):
            return f"investigate: tool limitation: {basis[:150]}"
        return f"explained: the legality gate cannot decide: {basis[:150]}"
    if rule.startswith("R21"):
        return (f"explained: too few repeats ({res.get('fail_rate')}) to "
                "call it deterministic")
    if rule.startswith(("R12b", "R13a", "R13c", "R14")):
        return f"explained: {res['rationale']}: {res['reason'][:160]}"
    if rule.startswith(("R06", "R07")) and hand == "needs_human":
        return ("explained: finer class: the hand label says only 'no "
                "expected value'; "
                "the registry entries "
                f"{', '.join(res.get('registry', [])) or '(none)'} name the "
                f"class ({v})")
    if rule.startswith("R19r") and hand == "needs_human":
        # A run-time ruling (RUL-MAPPED-FLAG-NOT-COPIED-BACK)
        return ("explained: run-time ruling: the cell's ran_on_host=1 is a "
                "map(tofrom) flag the compiler did not copy back, a "
                "finding's wrong answer, not a host fallback (the value is "
                "not in question); the hand label was about the value")
    if rule.startswith("R19b") and hand == "needs_human":
        return ("explained: host fallback: a host report under mandatory "
                "(RUL-MANDATORY-DEVICE): the value is not in question; the "
                "hand label was about the value")
    if (hand == "needs_human" and v in BUG
            and res["case"]["program"]["lang"] == "c"
            and exp.get("status") == "trusted"
            and "derivation" in (exp.get("sources") or [])):
        why = _c_derivation_source(res, der)
        if why:
            return why
    if rule.startswith("R08") and hand == "needs_human":
        return ("explained: finer class: the compiler refused the program's "
                "requires directive in this memory mode (requirement_refused); "
                "the hand label says only that no trusted value exists")
    if v == "flaky":
        return (f"explained: intermittent: some repeats pass and some fail "
                f"({res.get('fail_rate')}); the hand verdict calls the "
                "failure a bug, the rules call it intermittent")
    return f"investigate: {rule}"


LIVE_OUT = ROOT / "results" / "confirm" / "validation_live.jsonl"
NV_CASES: list = []  # The NVIDIA hand-verdict cases of the run


def run(live: bool = False, log=print, cases=None, ctx=None,
        out: Path | None = None) -> dict:
    if live:
        res = live_results(log)
        LIVE_OUT.parent.mkdir(parents=True, exist_ok=True)
        LIVE_OUT.write_text("".join(json.dumps(r) + "\n" for r in res))
        return {"headline": headline(res), "results": res}
    idx = I.stored_index()
    ctx = ctx or C.Context(idx, Store())
    if cases is None:
        # The validation is of the AMD/Cray cases (its hand
        # verdicts are theirs); the NVIDIA cells a finding or triage entry
        # now names are reported by nvhpc_results (data/reports/
        # nvhpc-a100.md), so this report stays as it was
        from offload.engine.toolchains import NVIDIA_TOOLCHAINS
        all_cases = hand_cases(idx)
        cases = [hc for hc in all_cases
                 if hc["row"].toolchain not in NVIDIA_TOOLCHAINS]
        NV_CASES[:] = [hc for hc in all_cases
                       if hc["row"].toolchain in NVIDIA_TOOLCHAINS]
    results = []
    cache = {}
    for k, hc in enumerate(cases, 1):
        r = hc["row"]
        key = r.cell
        if key not in cache:
            case = I.case_of_row(r)
            res = EN.confirm(case, ctx)
            cache[key] = res
        res = cache[key]
        res = dict(res, source=hc["source"])
        results.append({"source": hc["source"], "case_id": res["case"]
                        ["case_id"], "hand": hc["hand"],
                        "hand_detail": hc["hand_detail"], "ref": hc["ref"],
                        "verdict": res["verdict"], "rule": res["rule"],
                        "reason": res["reason"][:400],
                        "findings": [f["file"] for f in res["findings"]],
                        "agree": agrees(hc["hand"], res["verdict"]),
                        "explanation": explain(res, hc["hand"]),
                        "elision": [(e["status"], e["detail"][:120], e["value"])
                                    for e in _ev(res, "elision")],
                        "other_cells": [f"{c['toolchain']}/{c['mode']}:"
                                        f"{c['outcome']}" for c in
                                        res.get("other_cells", [])][:12],
                        "expected": res.get("expected"),
                        "tool_limit": tool_limited(res)})
        if k % 200 == 0:
            log(f"{k}/{len(cases)}")
    out = out or OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r) + "\n" for r in results))
    head = headline(results)
    return {"headline": head, "results": results}


def headline(results: list[dict]) -> dict:
    by = Counter(r["source"] for r in results)
    ok = Counter(r["source"] for r in results if r["agree"])
    nh = Counter(r["source"] for r in results if r["verdict"] ==
                 "needs_human")
    inv = sum(1 for r in results if r["explanation"].startswith(
        "investigate"))
    return {"cases": len(results), "agree": sum(ok.values()),
            "unexplained": inv,
            "by_source": {s: {"cases": n, "agree": ok[s],
                              "needs_human": nh[s]}
                          for s, n in sorted(by.items())}}


def live_results(log=print, findings=LIVE_FINDINGS, runner=None) -> list:
    """The hand-written findings of LIVE_FINDINGS confirmed end to end on
    this node: the finding's own cell is run (3 repeats), then the rules
    with every collector allowed to run (other toolchains, the other
    mode, elision, repeats)."""
    from offload.engine.confirm import findings as FI
    from offload.engine.confirm import programs as P
    from offload.engine.confirm.execute import LocalRunner
    from offload.engine.confirm.model import Case
    idx = {f.file.split("/")[-1]: f for f in FI.index()}
    runner = runner or LocalRunner()
    from offload.engine.confirm import machines as M
    from offload.engine.toolchains import detect_gpu
    here = M.machine_of_arch(detect_gpu()[0])
    runner.machine = here.name if here else "no-gpu"
    ctx = C.Context(I.Index(), Store(), runner=runner, allow_run=True)
    out = []
    for name, tc, mode in findings:
        f = idx[name]
        ref = P.file_ref([str(ROOT / "data" / "findings" / name)],
                         f.expected)
        t = TOOLCHAINS[tc]
        ev = C.run_cell(ctx, "repeats", Case(ref, tc, t.machine, t.arch,
                                             mode, "unknown"), tc, mode)
        if ev is None or not ev.runs:
            log(f"live {name} {tc} {mode}: could not run here "
                f"({ev.detail if ev else 'no runner'})")
            continue
        r = ev.runs[0]
        case = Case(ref, tc, t.machine, t.arch, mode, r.outcome, r.reason,
                    r.value, r.ran_on_host,
                    len({(x.outcome, x.value) for x in ev.runs}) > 1,
                    len(ev.runs))
        res = EN.confirm(case, ctx)
        log(f"live {name} {tc} {mode}: {r.outcome} -> {res['verdict']} "
            f"({res['rule']})")
        out.append({"source": "live", "case_id": case.case_id,
                    "hand": "compiler_bug", "hand_detail": "finding",
                    "ref": f"data/findings/{name}", "verdict": res["verdict"],
                    "rule": res["rule"], "reason": res["reason"][:400],
                    "outcome": r.outcome,
                    "findings": [x["file"] for x in res["findings"]],
                    "agree": agrees("compiler_bug", res["verdict"]),
                    "explanation": explain(res, "compiler_bug")})
    return out


SOURCES = {
    "mode_differences": "catalog/mode_differences.yaml entries (mode "
                        "classes)",
    "arch_entries": "catalog/mode_differences.yaml arch_entries",
    "triage": "catalog/expected_triage.yaml dispositions",
    "expected": "results/expected verdicts (Tasks 21, 27a; run failures "
                "of the programs in the expected set)",
    "fuzz_findings": "data/findings/fuzz (minimized fuzz findings: the "
                     "campaign cell of each failing toolchain)",
    "finding_programs": "catalog cells a hand-written finding names "
                        "(data/findings/index.yaml programs), failing at "
                        "run time on the finding's compilers and modes",
    "live": "hand-written findings run end to end on a compute node",
}


def render(results: list[dict], live: list[dict], meta: dict) -> str:
    allr = results + live
    hands = sorted({r["hand"] for r in allr})
    verdicts = sorted({r["verdict"] for r in allr})
    m = Counter((r["hand"], r["verdict"]) for r in allr)
    head = headline(allr)
    nh = sum(1 for r in allr if r["verdict"] == "needs_human")
    lines = [
        "# Confirmer validation", "",
        "The confirmer (tools/confirm.py, rules catalog/confirm_rules.yaml "
        f"version 2) run over every AMD/Cray case with a hand verdict: "
        f"{head['cases']} cases, {head['agree']} agree "
        f"({100 * head['agree'] // max(1, head['cases'])}%), "
        f"{head['cases'] - head['agree']} disagree, of which "
        f"{head['unexplained']} unexplained. needs_human: {nh} "
        f"({100 * nh // max(1, head['cases'])}%). The bug verdicts "
        "(compiler_bug, copy_mode_failure, unified_memory_failure, "
        "arch_specific) agree with each other as a group. Offline cases use "
        "the stored evidence (result files, results/expected, the fuzz "
        "campaigns, sequential elision run where it applies); live cases "
        f"ran on {meta.get('live_host', 'a compute node')}.", "",
        "Circularity note: the `triage` and `expected` hand verdicts were "
        "made with the same expected-value machinery (tools/derive/expected.py) "
        "the rules read through the expected_record collector, so their "
        "agreement shows consistency, not independent confirmation. The "
        "rules never read catalog/mode_differences.yaml (the mode and arch "
        "classes are derived from the cells).", "",
        "## Sources", "",
        "| source | what | cases | agree | needs_human |", "|---|---|---|---|---|"]
    for s, d in head["by_source"].items():
        lines.append(f"| {s} | {SOURCES.get(s, '')} | {d['cases']} | "
                     f"{d['agree']} | {d['needs_human']} "
                     f"({100 * d['needs_human'] // max(1, d['cases'])}%) |")
    lines += ["", "## Agreement matrix (rows: hand verdict; columns: rule "
              "verdict)", "",
              "| hand \\ rule | " + " | ".join(verdicts) + " |",
              "|---|" + "---|" * len(verdicts)]
    for h in hands:
        lines.append(f"| {h} | " + " | ".join(
            str(m[(h, v)]) if m[(h, v)] else "" for v in verdicts) + " |")
    lines += ["", "## Disagreements and their resolution", "",
              "| source | hand | rule verdict (rule) | cases | resolution | "
              "examples |", "|---|---|---|---|---|---|"]
    groups = defaultdict(list)
    for r in allr:
        if not r["agree"]:
            groups[(r["source"], r["hand"], r["verdict"], r["rule"],
                    r["explanation"])].append(r["case_id"])
    for (s, h, v, rule, ex), ids in sorted(groups.items()):
        lines.append(f"| {s} | {h} | {v} ({rule}) | {len(ids)} | "
                     f"{ex.replace('|', '/')} | "
                     f"{', '.join(i.replace('catalog:', '') for i in ids[:3])}"
                     + (" ..." if len(ids) > 3 else "") + " |")
    dis = [r for r in allr if not r["agree"]]
    nhs = [r for r in allr if r["verdict"] == "needs_human"]
    tl_d = sum(1 for r in dis if r["explanation"].startswith(
        "investigate: tool limitation"))
    st_d = sum(1 for r in dis if r["explanation"].startswith(
        "explained: stricter"))
    tl_n = sum(1 for r in nhs if r.get("tool_limit"))
    lines += ["", "## Tool limitations vs rule strictness", "",
              "| set | tool limitation | rule strictness | other |",
              "|---|---|---|---|",
              f"| disagreements ({len(dis)}) | {tl_d} | {st_d} | "
              f"{len(dis) - tl_d - st_d} |",
              f"| needs_human ({len(nhs)}) | {tl_n} | "
              f"{sum(1 for r in nhs if r['rule'].startswith(('R22', 'R04', 'R12b', 'R13', 'R14', 'R21')) and not r.get('tool_limit'))} | "
              f"{sum(1 for r in nhs if not r.get('tool_limit') and not r['rule'].startswith(('R22', 'R04', 'R12b', 'R13', 'R14', 'R21')))} |"]
    cat = Counter(": ".join(x.strip() for x in
                            r["explanation"].split(":")[:2])[:110]
                  for r in allr if not r["agree"])
    lines += ["", "## Disagreements by category", "",
              "| category | cases |", "|---|---|"]
    lines += [f"| {k} | {n} |" for k, n in cat.most_common()]
    sc = ROOT / "data" / "reports" / "confirm-selfcheck.yaml"
    if sc.is_file():
        rows = (yaml.safe_load(sc.read_text()) or {}).get("checked") or []
        lines += ["", f"## Self-check ({len(rows)} disagreements checked by "
                  "hand: data/reports/confirm-selfcheck.yaml)", "",
                  "| case | hand -> rule | explanation (computed) | check |",
                  "|---|---|---|---|"]
        for r in rows:
            lines.append(f"| {r['case_id']} | {r['hand']} -> "
                         f"{r['rule_verdict']} ({r['rule']}) | "
                         f"{r['explanation'][:150].replace('|', '/')} | "
                         f"{r['check'].replace('|', '/')} |")
    if live:
        lines += ["", "## Live reproductions (end to end on flux)", "",
                  "| finding | case | outcome | verdict (rule) | reason |",
                  "|---|---|---|---|---|"]
        for r in live:
            lines.append(f"| {r['ref']} | {r['case_id']} | "
                         f"{r.get('outcome', '')} | {r['verdict']} "
                         f"({r['rule']}) | "
                         f"{r['reason'][:160].replace('|', '/')} |")
    return "\n".join(lines) + "\n"


def write_report(meta: dict | None = None) -> dict:
    res = [json.loads(x) for x in OUT.read_text().splitlines() if x]
    live = [json.loads(x) for x in LIVE_OUT.read_text().splitlines()
            if x] if LIVE_OUT.is_file() else []
    DOC.write_text(render(res, live, meta or {}))
    return headline(res + live)
