"""The decision rules (catalog/confirm_rules.yaml, versioned data) and the
engine that applies them.

Rules are tried in order; a rule's ``needs`` collectors run (cheapest
first, each once) only when the rule is reached, then its ``when``
conditions (named predicates of ``PREDICATES`` over ``facts.Facts``) are
checked; the first rule whose conditions all hold decides. The decision
records the rule id, its rationale and citations, the reason built from
the facts, every withdrawn witness with its finding, and the evidence."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from offload.engine.confirm import collectors as C
from offload.engine.confirm import registry as REG
from offload.engine.confirm.facts import Facts
from offload.engine.confirm.model import COMPILE_FAILURES, RUN_FAILURES

from offload.engine.root import ROOT  # noqa: E402
RULES_FILE = ROOT / "catalog" / "confirm_rules.yaml"
VERDICTS = ("compiler_bug", "copy_mode_failure", "unified_memory_failure",
            "needs_unified_memory", "requirement_refused", "arch_specific",
            "our_bug", "unspecified", "unsupported", "unsupported_everywhere",
            "noncompliant", "flaky", "environment", "not_a_failure",
            "needs_human")


@dataclass(frozen=True)
class Rule:
    id: str
    verdict: str
    rationale: str
    cite: tuple
    needs: tuple
    when: dict
    # Collectors run only once the rule
    # has matched, for the record it keeps (an expected value), so a rule
    # early in the list does not collect for every case it passes
    needs_after: tuple = ()


def load(path: Path = RULES_FILE, data: dict | None = None) -> list[Rule]:
    if data is None:
        data = yaml.safe_load(Path(path).read_text()) or {}
    if data.get("version") not in (1, 2, 3):
        raise ValueError("confirm rules: unknown version")
    out = []
    reg = REG.entries()
    ids = set()
    for d in data["rules"]:
        if d["id"] in ids:
            raise ValueError(f"duplicate rule id {d['id']}")
        ids.add(d["id"])
        # `ruling`: the verdict a recorded ruling decides (rule R11r)
        if d["verdict"] not in VERDICTS + ("ruling",):
            raise ValueError(f"{d['id']}: unknown verdict {d['verdict']}")
        for c in d.get("cite") or ():
            if c not in reg:
                raise ValueError(f"{d['id']}: cites {c}, not in the "
                                 "registry")
        for n in tuple(d.get("needs") or ()) + tuple(d.get("needs_after")
                                                     or ()):
            if n not in C.COLLECTORS:
                raise ValueError(f"{d['id']}: unknown collector {n}")
        for k in (d.get("when") or {}):
            if k not in PREDICATES:
                raise ValueError(f"{d['id']}: unknown predicate {k}")
        out.append(Rule(d["id"], d["verdict"], d["rationale"],
                        tuple(d.get("cite") or ()),
                        tuple(d.get("needs") or ()), dict(d.get("when")
                                                          or {}),
                        tuple(d.get("needs_after") or ())))
    if not out or out[-1].when:
        raise ValueError("the last rule must be an unconditional default")
    return out


@lru_cache(maxsize=None)
def rules() -> tuple:
    return tuple(load())


# --- predicates ---------------------------------------------------------------

def _env(f: Facts) -> bool:
    if f.case.outcome == "harness_error" and not f.case.reason.startswith(
            ("unclassified_compile_failure", "no_executable")):
        return True
    if f.case.reason.startswith(("remote:", "runner:")):
        return True
    return any(e.kind == "environment" for e in REG.matching(
        "", reason=f.case.reason, kinds=("environment",)))


def _unsupported(f: Facts) -> bool:
    return f.case.outcome == "accepted_ignored" or (
        f.case.outcome == "rejected" and
        f.case.reason.startswith("not_implemented"))


def _needs_um(f: Facts) -> bool:
    if "zero_copy" in f.case.program.needs:
        return True
    return bool(REG._requires(f.case.program.text or "") &
                {"unified_shared_memory", "self_maps"})


def _compile_failure(f: Facts) -> bool:
    return f.compile_time()


def claims_for(toolchain: str, atom: str, version: int,
               lang: str = "f90") -> list:
    """The ingested vendor claims (catalog/vendor_claims_generic
    .yaml) about `atom` for the compiler of `toolchain` (its gfx90a twin
    included) and a program of `lang` at spec `version`: a program of 6.0
    or later is covered only by a claim from a 6.0 feature list (a 6.0
    form is not a 5.x feature's spelling); an earlier one by a claim
    compared at that version."""
    from fnmatch import fnmatchcase
    from offload.engine.confirm import claims as CL
    from offload.engine.toolchains import base_name
    tc = base_name(toolchain)
    out = []
    for c in CL.generic():
        if c.toolchain != tc or not atom or not fnmatchcase(atom, c.atom):
            continue
        if not c.covers_language(lang):
            continue
        if version >= 60:
            if c.spec_version != "6.0":
                continue
        elif c.version_list and version not in c.version_list:
            continue
        out.append(c)
    return out


def claimed(toolchain: str, atom: str, version: int,
            lang: str = "f90") -> bool:
    """A recorded vendor claim that the toolchain supports the atom at the
    spec version: `supported`, or `partial` where the vendor says the
    form is accepted (ruling: a partial claim is no claim of
    support for every form)."""
    return any(c.claim == "supported" or
               (c.claim == "partial" and c.form == "accepted")
               for c in claims_for(toolchain, atom, version, lang))


def claim_status(toolchain: str, atom: str, version: int,
                 lang: str = "f90") -> str:
    """What the vendor's recorded claims say about the
    atom: "claims_support" (``claimed``), "documents_unsupported" (an
    ``unsupported`` claim and no claim of support) or "no_claim" (nothing
    recorded, or only a partial claim that does not say the form is
    accepted)."""
    if claimed(toolchain, atom, version, lang):
        return "claims_support"
    if any(c.claim == "unsupported"
           for c in claims_for(toolchain, atom, version, lang)):
        return "documents_unsupported"
    return "no_claim"


def _documented_unsupported(f: Facts) -> bool:
    """A diagnostic rejection of a feature (the program's primary atom)
    the vendor documents as unsupported (RUL-DOCUMENTED-UNSUPPORTED): the
    documented support gap, not a defect. ICEs, link failures and hangs
    are never covered."""
    if f.case.outcome != "rejected" or not (
            f.case.reason.startswith(("diagnostic", "not_implemented"))):
        return False
    # a diagnostic at a later form of another construct (catalog/
    # later_forms.yaml: e.g. CCE 20 rejecting the enter clause of the
    # indirect programs) is not a rejection of the documented feature
    from offload.engine.confirm import forms as FO
    if FO.match(f.case.program.text or "", f.case.reason):
        return False
    version = f.case.program.version or 0
    if version >= 60 and _shares_52_rejection(f):
        # the 6.0 program's rejection is the 5.2 program's (the same
        # front-end diagnostic): the feature's documented status at 5.2
        # applies (a 6.0 feature list is only needed for a 6.0 form)
        version = 52
    return claim_status(f.case.toolchain, _primary_atom(f), version,
                        f.case.program.lang) == "documents_unsupported"


def _shares_52_rejection(f: Facts) -> bool:
    from offload.engine.confirm.facts import diagnostic_key, frontend_rejection
    r52 = f.extra.get("v52_reason") or ""
    return frontend_rejection(f.extra.get("v52_outcome") or "", r52) and \
        diagnostic_key(r52) == diagnostic_key(f.case.reason)


def _documented_note(f: Facts) -> str:
    v = f.case.program.version or 0
    if v >= 60 and _shares_52_rejection(f):
        v = 52
    cs = [c for c in claims_for(f.case.toolchain, _primary_atom(f), v,
                                f.case.program.lang)
          if c.claim == "unsupported"]
    return "; ".join(f"unsupported claim ({c.source}"
                     + (f", {c.form}" if c.form else "")
                     + f"): {c.quote[:100]}" for c in cs)


def _primary_atom(f: Facts) -> str:
    if f.case.program.kind != "catalog":
        return ""
    from offload.engine.confirm import programs as P
    prog = P.catalog_program(f.case.program.ident)
    return prog.primary_atom if prog is not None else ""


def _newer_form_unclaimed(f: Facts) -> bool:
    """A diagnostic rejection of a program of spec version 6.0 or later
    with no recorded claim of support (RUL-NO-CLAIM-UNSUPPORTED)."""
    if f.case.outcome != "rejected" or \
            not f.case.reason.startswith("diagnostic"):
        return False
    if (f.case.program.version or 0) < 60:
        return False
    # a rejection the 5.2 program of the same atom shares (fix:
    # a front-end rejection with the same diagnostic; a 5.2 link failure,
    # ICE or other diagnostic is not shared) is not one of the 6.0 form:
    # the ordinary rejection rules decide it
    from offload.engine.confirm.facts import diagnostic_key, frontend_rejection
    r52 = f.extra.get("v52_reason") or ""
    if frontend_rejection(f.extra.get("v52_outcome") or "", r52) and \
            diagnostic_key(r52) == diagnostic_key(f.case.reason):
        return False
    return not claimed(f.case.toolchain, _primary_atom(f),
                       f.case.program.version, f.case.program.lang)


def later_forms_unclaimed(f: Facts) -> list:
    """(RUL-LATER-FORM-UNCLAIMED): the later forms
    (catalog/later_forms.yaml) a diagnostic rejection is attributed to
    and that the toolchain's vendor claims nothing for (a general claim of
    the earlier version's construct does not name the form's atom)."""
    if f.case.outcome != "rejected" or \
            not f.case.reason.startswith("diagnostic"):
        return []
    from offload.engine.confirm import forms as FO
    return [fo for fo in FO.match(f.case.program.text or "", f.case.reason)
            if not form_claimed(f.case.toolchain, fo,
                                f.case.program.version or 52,
                                f.case.program.lang)]


def form_claimed(toolchain: str, form, version: int,
                 lang: str = "f90") -> bool:
    """A vendor claim of a later form (RUL-LATER-FORM-UNCLAIMED): a claim
    of the form's atom from a feature list of the version that added the
    form or a later one (spec_version >= since), `supported` or `partial`
    with form `accepted`; a general claim of an earlier version (no spec
    version: "full OpenMP 5.0") does not count."""
    def ver(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return 0.0
    return any((c.claim == "supported" or
                (c.claim == "partial" and c.form == "accepted"))
               and ver(c.spec_version) >= ver(form.since)
               for c in claims_for(toolchain, form.atom, version, lang))


def _later_note(f: Facts) -> str:
    return "; ".join(
        f"later form {fo.id} ({fo.what}, since {fo.since}; {fo.cite()}): "
        f"no claim of {fo.atom} recorded for {f.case.toolchain}"
        for fo in later_forms_unclaimed(f))


def _witness(f: Facts) -> str | None:
    """An independent checker (not under test) accepted the program's
    current source (offload.engine.confirm.witness)."""
    from offload.engine.confirm import witness as W
    if f.case.program.kind not in ("catalog", "file"):
        return None
    from offload.engine.confirm.machines import family_of
    return W.accepted(f.case.program.ident, f.case.program.sha or "",
                      family_of(f.case.toolchain))


def _legal_entries(f: Facts) -> list:
    """Registry entries of kind legality that name the program and quote
    the spec text making it legal."""
    return [e for e in f.registry if e.kind == "legality" and e.citations
            and (e.applies or {}).get("programs")]


def _vendor_claims(f: Facts) -> bool:
    """The vendor claims support for the program's feature (its primary
    atom) on the case's toolchain, language and spec version."""
    return claimed(f.case.toolchain, _primary_atom(f),
                   f.case.program.version or 0, f.case.program.lang)


def _claims_note(f: Facts) -> str:
    """R11a's reason: the claims considered."""
    atom = _primary_atom(f)
    cs = claims_for(f.case.toolchain, atom, f.case.program.version or 0,
                    f.case.program.lang)
    if not cs:
        return f"no claim recorded for {atom or 'the program'} at 6.0"
    return "; ".join(f"{c.claim} claim recorded ({c.source}"
                     + (f", {c.form}" if c.form else "")
                     + f"): {c.quote[:80]}" for c in cs) + \
        " -- a partial claim is no claim of support for every form"


def _runtime_failure(f: Facts) -> bool:
    return f.case.outcome in RUN_FAILURES and not _compile_failure(f)


def _status_in(f: Facts, v) -> bool:
    return f.expected_cached()["status"] in (v if isinstance(v, list)
                                             else [v])


def _eq(value):
    return lambda got: got == value


PREDICATES = {
    "environment": lambda f, v: _env(f) == v,
    "outcome_in": lambda f, v: f.case.outcome in v,
    "legality": lambda f, v: f.legality.status == v,
    "unsupported_message": lambda f, v: _unsupported(f) == v,
    "registry_open": lambda f, v: bool(
        f.registry_kinds() & set(REG.OPEN_KINDS)) == v,
    "mode": lambda f, v: f.case.mode == v,
    "needs_unified_memory": lambda f, v: _needs_um(f) == v,
    "requires_any": lambda f, v: bool(REG._requires(
        f.case.program.text or "") & set(v)) if isinstance(v, list)
        else bool(REG._requires(f.case.program.text or "")) == v,
    "other_mode_passes": lambda f, v: f.other_mode_passes() == v,
    "flaky": lambda f, v: f.flaky() == v,
    "compile_failure": lambda f, v: _compile_failure(f) == v,
    "other_family_compiles": lambda f, v: f.other_family_compiles() == v,
    "elision_and_compilers_against_model":
        lambda f, v: f.elision_and_compilers_against_model() == v,
    "expected_status": _status_in,
    "copy_mode_only_check":
        lambda f, v: (f.case.program.evidence == "copy_mode_only") == v,
    "runtime_failure": lambda f, v: _runtime_failure(f) == v,
    "deterministic": lambda f, v: f.deterministic() == v,
    "witness": lambda f, v: bool(f.witnesses()) == v,
    "other_family_on_device": lambda f, v: f.other_family_on_device() == v,
    "every_family_rejects": lambda f, v: f.every_family_rejects() == v,
    # The amendment of RUL-UNSUPPORTED-EVERYWHERE (RUL-UNSUPPORTED-EVERYWHERE-AMENDED)
    "independent_accepts": lambda f, v: bool(_witness(f)) == v,
    "spec_legal": lambda f, v: bool(_legal_entries(f)) == v,
    "vendor_claims": lambda f, v: _vendor_claims(f) == v,
    "own_link_or_hang": lambda f, v: f.own_link_or_hang() == v,
    "documented_unsupported": lambda f, v: _documented_unsupported(f) == v,
    # A recorded ruling decides the case's support
    "ruling_decides": lambda f, v: (_ruling_decides(f) is not None) == v,
    "newer_form_unclaimed": lambda f, v: _newer_form_unclaimed(f) == v,
    "later_form_unclaimed": lambda f, v: bool(later_forms_unclaimed(f))
    == v,
    "oracle_contested": lambda f, v: f.oracle_contested() == v,
    "task22_noncompliant": lambda f, v: f.noncompliant_by_task22(int(v)),
    "fuzz_noncompliant": lambda f, v: (
        f.extra.get("validity") == "noncompliant") == v,
    "other_arch_passes_same_mode":
        lambda f, v: f.other_arch_passes(f.case.mode) == v,
    # The reproduction gate's verdict on the case's own cell
    "gate_unconfirmed": lambda f, v: _gate_unconfirmed(f) == v,
}


def _ruling_decides(f: Facts) -> tuple[str, str] | None:
    """(verdict, ruling id) a recorded ruling (catalog/rulings.yaml, an
    entry with `decides`) gives the case, or None. The entry applies to
    the program (its `applies`) and its `decides` holds: `verdict` (any
    verdict class), and optionally `families` (the case's compiler
    family), `modes` (the case's memory mode), `reason` (a pattern the
    case's reason matches) and `outcome` (`frontend_rejection`, the
    default: a diagnosed rejection or not-implemented message;
    or a list of outcome classes, for a run-time ruling), and `toolchains`
    (the releases it is about). A ruling
    on legality or support takes precedence over the family witness."""
    from offload.engine.confirm.facts import family, frontend_rejection
    for e in f.registry:
        d = e.decides or {}
        if not d.get("verdict"):
            continue
        fams = d.get("families")
        if fams and family(f.case.toolchain) not in fams:
            continue
        # A ruling about some releases of a family names them
        if d.get("toolchains") and f.case.toolchain not in d["toolchains"]:
            continue
        if d.get("modes") and f.case.mode not in d["modes"]:
            continue
        if d.get("reason") and not re.search(d["reason"],
                                             f.case.reason or ""):
            continue
        out = d.get("outcome", "frontend_rejection")
        if out == "frontend_rejection":
            if not frontend_rejection(f.case.outcome, f.case.reason):
                continue
        # A run-time ruling names the outcome classes it decides
        elif f.case.outcome not in (out if isinstance(out, list)
                                    else [out]):
            continue
        return d["verdict"], e.id
    return None


def _gate_unconfirmed(f: Facts) -> bool:
    """The case's cell does not count as a failure by the reproduction
    gate (offload.engine.gate.counts; results/gate/verdicts.jsonl): its
    verdict is not confirmed, or the decision on it says it does not
    count. A cell the gate has not seen, an ``unchecked`` cell (it keeps
    its outcome, flagged) and a decided cell that counts are False."""
    from offload.engine import gate as G
    v = G.verdict_of_case(f.case)
    return v is not None and not G.counts(v)


# --- the engine -----------------------------------------------------------------

@dataclass
class Decision:
    verdict: str
    rule: str
    rationale: str
    reason: str
    cites: list = field(default_factory=list)
    withdrawn: list = field(default_factory=list)
    expected: dict = field(default_factory=dict)
    witnesses: list = field(default_factory=list)
    fail_rate: str = ""
    collectors_run: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _reason(rule: Rule, f: Facts) -> str:
    parts = []
    if rule.verdict == "flaky":
        parts.append(f"failing runs {f.fail_rate()}")
    if any(k in rule.when for k in ("expected_status", "witness")):
        e = f.expected_cached()
        parts.append(f"expected {e['status']}"
                     + (f" {e['value']}" if e["value"] else "")
                     + (f" ({' + '.join(e['sources'])})" if e["sources"]
                        else "") + f": {e['reason']}")
    if "witness" in rule.when:
        parts.append("witnesses: " + (", ".join(f.witnesses()) or "none"))
    if rule.id.startswith(("R03", "R04")):
        parts.append(f"legality: {f.legality.basis}")
    if rule.id.startswith(("R13-", "R13a")):
        a, b = f.oracle_sides()
        parts.append(f"elision {f.elision_value()}, claim "
                     f"{f.model_value()}; cells with the elision's value: "
                     f"{', '.join(a) or 'none'}; cells with the claim: "
                     f"{', '.join(b) or 'none'}")
    if rule.id.startswith("R13b") or rule.id.startswith("R13c"):
        parts.append(f"host builds of {f.host_families()} families ran; "
                     f"outcome {f.case.outcome}")
    if rule.id.startswith(("R20", "R16", "R17", "R18", "R19-")) and \
            len(f.value_spread()) > 1:
        parts.append("failing on every run with varying values: "
                     + ", ".join(f.value_spread()[:5]))
    if rule.id.startswith("R12b"):
        cells = [f"{e.toolchain}/{e.mode}:{e.outcomes[0]}"
                 for e in f.cells(("other_toolchains",))
                 if e.mode == f.case.mode]
        parts.append("other cells: " + (", ".join(cells) or "none")
                     + "; families without a cell: "
                     + (", ".join(f.missing_families()) or "none")
                     + "; missing evidence: "
                     + (", ".join(f"{m['collector']} {m['toolchain']}"
                                  for m in f.missing_evidence()) or "none"))
    if rule.id.startswith("R12a"):
        src = sorted({c.source for c in claims_for(
            f.case.toolchain, _primary_atom(f), f.case.program.version or 0,
            f.case.program.lang)})
        parts.append(f"independent checker: {_witness(f)}; spec: "
                     + "; ".join(e.cite() for e in _legal_entries(f))
                     + "; vendor claim: " + (", ".join(src) or "recorded"))
    if rule.id.startswith("R11a"):
        parts.append(_claims_note(f))
    if rule.id.startswith("R11d"):
        parts.append(_documented_note(f))
    if rule.id.startswith("R11c"):
        parts.append(_later_note(f))
    if rule.id.startswith("R04b"):
        from offload.engine import gate as G
        v = G.verdict_of_case(f.case) or {}
        parts.append(f"gate verdict {v.get('verdict')}"
                     + (" (inherited from its signature)" if
                        v.get("inherited") else "")
                     + (f"; condition: {v['condition']}" if
                        v.get("condition") else ""))
    if rule.id.startswith("R06"):
        parts.append("registry: " + ", ".join(e.id for e in f.registry
                                              if e.kind in REG.OPEN_KINDS))
    rec = f.record() if rule.verdict == "needs_human" else None
    if rec and rec.get("needs_human"):
        # The triage's stated needs_human reason
        parts.append("stated reason (catalog/expected_triage.yaml): "
                     + rec["needs_human"])
    return "; ".join(parts)


def decide(f: Facts, ctx, rule_list=None, collect=None) -> Decision:
    """Apply the rules to `f` (its evidence is filled in as rules need
    it, through `collect(name)`)."""
    ran: list[str] = []

    def need(names):
        for c in C.ordered(names):
            if c.name in f.evidence:
                continue
            f.evidence[c.name] = (collect or (lambda col: col.collect(
                f.case, ctx)))(c)
            ran.append(c.name)
            f._exp = None
            if collect_hook:
                collect_hook(f)
    collect_hook = getattr(ctx, "after_collect", None)
    for rule in (rule_list or rules()):
        need(rule.needs)
        if all(PREDICATES[k](f, v) for k, v in rule.when.items()):
            if rule.needs_after:
                need(rule.needs_after)
            exp = f.expected_cached() if f.evidence.get("model") is not None \
                or f.evidence.get("expected_record") is not None else {}
            verdict, cites = rule.verdict, list(rule.cite)
            if verdict == "ruling":
                # the ruling that decided names the verdict and is cited
                verdict, rid = _ruling_decides(f)
                cites = [rid] + [c for c in cites if c != rid]
            return Decision(verdict, rule.id, rule.rationale,
                            _reason(rule, f), cites,
                            f.withdrawn(), exp,
                            f.witnesses() if exp else [], f.fail_rate(), ran)
    raise AssertionError("the default rule always applies")


def explain(rule_id: str) -> Rule:
    for r in rules():
        if r.id == rule_id:
            return r
    raise KeyError(rule_id)


def rule_ids() -> list[str]:
    return [r.id for r in rules()]


_ID = re.compile(r"^R\d\d-[a-z0-9-]+$")
