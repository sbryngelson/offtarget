"""``confirm(case)``: the legality gate, the rules, then the actions
(dedupe, minimize, draft) for a failure the rules call a bug.

The JSON result per case: the case, its legality, the verdict with its
rule id, rationale, reason and citations (registry entries as
"<id> (<version> §<section> p.<page>: "<quote>")"), every withdrawn
witness with its finding, the findings whose signature the failure has,
the evidence (with provenance), the actions taken and the drafts
written."""
from __future__ import annotations

import json
from pathlib import Path

from offload.engine.confirm import collectors as C
from offload.engine.confirm import findings as FI
from offload.engine.confirm import legality as L
from offload.engine.confirm import registry as REG
from offload.engine.confirm import rules as RU
from offload.engine.confirm.facts import Facts
from offload.engine.confirm.model import Case

BUG_VERDICTS = ("compiler_bug", "copy_mode_failure", "unified_memory_failure",
                "arch_specific")
# An instance of a known finding is still minimized and
# drafted when no finding it matches has a reproducer of its shape


def _fuzz_check(case: Case, ctx) -> str | None:
    if case.program.kind != "fuzz":
        return None
    row = ctx.index.get("fuzz", case.program.ident, case.toolchain,
                        case.mode)
    return row.extra.get("check") if row is not None else None


def facts_of(case: Case, ctx, legality=None) -> Facts:
    from offload.engine.confirm.machines import family_of
    lg = legality or L.gate(case.program, _fuzz_check(case, ctx),
                            under_test=(family_of(case.toolchain),))
    reg = REG.matching(case.program.ident, case.program.text,
                       case.program.needs, case.reason)
    row = ctx.index.get(case.program.kind, case.program.ident,
                        case.toolchain, case.mode)
    extra = dict(row.extra) if row is not None else {}
    # the host builds of the same program (host check)
    extra["host_values"] = {
        r.toolchain: r.extra.get("host_checksum")
        for r in ctx.index.rows_of(case.program.kind, case.program.ident)
        if r.mode == case.mode and "host_checksum" in r.extra}
    # the same atom's 5.2 program on this toolchain and mode (is a 6.0
    # rejection one of the 6.0 form only?)
    import re as _re
    m = _re.match(r"omp60-(.*)$", case.program.ident)
    if case.program.kind == "catalog" and m:
        r52 = ctx.index.get("catalog", f"omp52-{m.group(1)}",
                            case.toolchain, case.mode)
        extra["v52_outcome"] = r52.outcome if r52 is not None else None
        extra["v52_reason"] = r52.reason if r52 is not None else ""
    return Facts(case, legality=lg, registry=reg, extra=extra)


def other_cells(f: Facts) -> list[dict]:
    """Every device cell of another toolchain, mode or arch, passing or
    failing, with the finding a failure has the signature of (no
    disagreeing evidence is dropped silently)."""
    out = []
    for e in f.cells():
        if e.toolchain == f.case.toolchain and e.mode == f.case.mode and \
                e.variant == "original":
            continue
        failed = not all(o in ("correct_on_device", "unobservable")
                         for o in e.outcomes)
        hits = FI.dedupe(e.toolchain, f.case.program.lang, e.outcomes[0],
                         e.runs[0].reason, f.case.program.text,
                         f.case.program.ident, e.mode,
                         arch=e.arch, opt=f.case.opt) if failed else []
        out.append({"collector": e.collector, "toolchain": e.toolchain,
                    "arch": e.arch, "mode": e.mode, "variant": e.variant,
                    "outcome": e.outcomes[0], "value": e.value,
                    "finding": hits[0]["file"] if hits else None})
    return out


def confirm(case: Case, ctx, legality=None, minimize: bool = False,
            draft: bool = False, draft_dir: Path | None = None) -> dict:
    f = facts_of(case, ctx, legality)
    d = RU.decide(f, ctx)
    reg = REG.entries()
    out = {"case": case.to_dict(), "legality": f.legality.to_dict(),
           "verdict": d.verdict, "rule": d.rule, "rationale": d.rationale,
           "reason": d.reason,
           "citations": [reg[c].cite() for c in d.cites if c in reg] or
           (["citation needed"] if d.verdict in BUG_VERDICTS else []),
           "withdrawn": d.withdrawn, "expected": d.expected,
           "witnesses": d.witnesses, "fail_rate": d.fail_rate,
           "collectors_run": d.collectors_run,
           "registry": [e.id for e in f.registry],
           "evidence": [e.to_dict() for es in f.evidence.values()
                        for e in es],
           "actions": [], "drafts": [], "findings": []}
    if case.failing:
        # The reproduction gate's flag on the case's
        # cell. "unchecked": not rerun, the verdict above is the confirmer's
        # on stored data only; such a row is never evidence for a new
        # finding
        from offload.engine import gate as G
        gv = G.verdict_of_case(case)
        if gv is not None:
            out["gate"] = gv.get("verdict")
            if gv.get("decision"):
                out["gate_decision"] = gv["decision"]
        out["other_cells"] = other_cells(f)
        out["missing"] = f.missing_evidence()
        out["families_without_cell"] = f.missing_families() \
            if case.failing else []
    if d.verdict in BUG_VERDICTS:
        output = f.extra.get("stderr_tail", "")
        hits = FI.dedupe(case.toolchain, case.program.lang, case.outcome,
                         case.reason, case.program.text, case.program.ident,
                         case.mode, arch=case.arch, output=output,
                         related=True, opt=case.opt)
        dups = [h for h in hits if h["kind"] == "duplicate"]
        out["findings"] = dups
        out["related"] = [h for h in hits if h["kind"] == "related"]
        if dups:
            out["actions"].append(f"dedupe: instance of {dups[0]['file']} "
                                  f"({dups[0]['why']})")
        else:
            out["actions"].append("dedupe: new failure signature"
                                  + (f" (related: {out['related'][0]['file']})"
                                     if out["related"] else ""))
        # a new signature, or an instance whose findings have no
        # reproducer of its shape, is minimized and drafted; any case when
        # asked explicitly (minimize="always")
        shaped = any(h["same_shape"] for h in dups)
        if not shaped or minimize == "always":
            if dups:
                out["actions"].append("no finding has a reproducer of this "
                                      "shape" if not shaped else
                                      "minimized on request")
            if minimize:
                from offload.engine.confirm import minimize as MZ
                res = MZ.minimize_case(case, ctx, d.verdict, workers=8,
                                       rule=d.rule)
                out["actions"].append(res.summary())
                out["minimized"] = res.source
            if draft:
                from offload.engine.confirm import draft as DR
                out["source"] = case.program.text
                path = DR.write_draft(out, draft_dir)
                out["drafts"].append(str(path))
    return out


def dumps(result: dict) -> str:
    return json.dumps(result, indent=1, default=str)
