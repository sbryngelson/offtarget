"""Facts the rules read, derived from a case and its evidence.

The expected value follows offload.engine.expected. Independent sources are the
program's own claim (``model``), ``elision``, ``derivation`` and
``metamorphic``; toolchain consensus is a hint, never a source. A stored
expected verdict (results/expected) is used for its program and memory mode.

``trusted`` needs two agreeing sources and an executed witness: the
elision, or a device run printing the value, in the case's memory mode for a
copy-dependent program. A toolchain is withdrawn as a witness only by a
stored triage entry that names its finding.

Runner failures are not runs here; collectors return them as missing
evidence. Flaky means some repeats pass and some fail. A failure on every
run whose value varies is deterministic, and its value spread is reported."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from offload.engine.confirm.model import (COMPILE_FAILURES, PASSING,
                                      RUN_FAILURES, Case, Evidence)
from offload.engine.confirm.machines import family_of as family
from offload.engine.confirm.machines import no_present_check
from offload.engine.toolchains import TOOLCHAINS, base_name

DEVICE_COLLECTORS = ("stored_repeats", "repeats", "other_toolchains",
                     "other_mode", "other_arch", "port")


def frontend_rejection(outcome: str, reason: str) -> bool:
    """A diagnosed compile error or a not-implemented message (not an
    ICE, a hang or a link failure)."""
    return outcome == "rejected" and (reason or "").startswith(
        ("diagnostic", "not_implemented"))


def diagnostic_key(reason: str) -> str:
    """The comparable part of a diagnostic: a CCE message number
    (ftn-NNN), else the message without positions and quoted names."""
    import re
    m = re.search(r"\bftn-(\d+)\b", reason or "")
    if m:
        return f"ftn-{m.group(1)}"
    text = (reason or "").split("error:", 1)[-1]
    text = re.sub(r"'[^']*'|`[^`]*'|\"[^\"]*\"|\S+:\d+:\d+:?", "", text)
    return " ".join(text.split())[:120]


# (RUL-PRESENCE-WITNESS): a presence or overlap abort
# of the failing run (the runtimes' present-table, region-overlap and
# present-modifier errors) is witnessed only by a run that enforces the
# present check: the (family, mode) pairs that do not are data
# (catalog/machines.yaml no_present_check), and the sequential elision has
# no device data environment
PRESENCE_ABORT = re.compile(
    r"not found in present table|overlaps present region|"
    r"'present' map type modifier|is not present on the device|"
    r"present clause.*not (?:present|mapped)|"
    # NVHPC's runtime (tests/data/messages/nvhpc_acc_run_present)
    r"data in PRESENT clause was not found on device", re.I)


@dataclass
class Facts:
    case: Case
    evidence: dict = field(default_factory=dict)   # collector -> [Evidence]
    legality: object = None
    registry: list = field(default_factory=list)
    findings: list = field(default_factory=list)   # signature matches
    extra: dict = field(default_factory=dict)      # the stored row's extra

    def ev(self, name: str) -> list[Evidence]:
        return self.evidence.get(name, [])

    # --- repeats -----------------------------------------------------------------
    def repeat_runs(self) -> list:
        runs = []
        for e in self.ev("stored_repeats") + self.ev("repeats"):
            runs += [r for r in e.runs if r.outcome != "harness_error"]
        return runs

    def flaky(self) -> bool:
        """Some repeats pass and some fail (a failure on
        every run is never flaky, whatever its values)."""
        runs = self.repeat_runs()
        passed = {r.outcome in PASSING for r in runs}
        return len(passed) > 1

    def fail_rate(self) -> str:
        runs = self.repeat_runs()
        bad = sum(1 for r in runs if r.outcome not in PASSING)
        return f"{bad}/{len(runs)}"

    def value_spread(self) -> list:
        return sorted({str(r.value) for r in self.repeat_runs()
                       if r.outcome not in PASSING})

    def compile_time(self) -> bool:
        from offload.engine.confirm.findings import group
        return group(self.case.outcome, self.case.reason) in (
            "ice", "rejected", "compile_timeout")

    def deterministic(self) -> bool:
        runs = self.repeat_runs()
        if self.flaky() or not runs:
            return False
        if self.compile_time():
            return True       # one compile; a compile is deterministic
        return len(runs) >= 2

    # --- cells --------------------------------------------------------------------
    def cells(self, names=DEVICE_COLLECTORS) -> list[Evidence]:
        out = []
        for n in names:
            out += [e for e in self.ev(n) if e.status in (
                "value", "no_value") and e.runs]
        return out

    def _passes(self, e: Evidence, value: str | None) -> bool:
        outs = e.outcomes
        if not outs or any(o not in PASSING for o in outs):
            return False
        if value is None:
            return True
        return e.value == value

    def _fails(self, e: Evidence) -> bool:
        return bool(e.outcomes) and all(o not in PASSING for o in
                                        e.outcomes)

    # --- the expected value -------------------------------------------------------
    def model_value(self) -> str | None:
        es = self.ev("model")
        return es[0].value if es else None

    def elision_value(self) -> str | None:
        es = [e for e in self.ev("elision") if e.status == "value"]
        return es[0].value if es else None

    def record(self) -> dict | None:
        es = [e for e in self.ev("expected_record") if e.detail.startswith(
            "{")]
        if not es:
            return None
        d = json.loads(es[0].detail)
        d["value"] = es[0].value
        return d

    def withdrawn(self) -> list[dict]:
        """Toolchains withdrawn as witnesses, each with its finding: the
        stored triage's withdrawals (catalog/expected_triage.yaml)."""
        rec = self.record()
        if not rec or not rec.get("withdraw"):
            return []
        return [{"toolchain": t, "finding": rec.get("finding")}
                for t in rec["withdraw"]]

    def expected(self) -> dict:
        """{"status", "value", "sources", "reason"} of the case's memory
        mode."""
        from offload.engine import expected as E
        rec = self.record()
        if rec is not None and rec["status"] in (
                "trusted", "derived", "disputed", "implementation_defined"):
            st = rec["status"]
            if st == "trusted" and not self._executed(rec["value"]):
                st = "derived"
            return {"status": st, "value": rec["value"],
                    "sources": rec.get("agreeing", []),
                    "reason": f"stored {rec['which']}: {rec['reason']}"}
        evs = []
        mv = self.model_value()
        if mv:
            evs.append(E.model_evidence(mv))
        el = [e for e in self.ev("elision") if e.status == "value"]
        if el:
            evs.append(E.Evidence("elision", "value", el[0].value))
        dv = [e for e in self.ev("derivation") if e.status == "value"]
        if dv:
            evs.append(E.Evidence("derivation", "value", dv[0].value))
        meta = self._metamorphic()
        if meta is not None:
            evs.append(meta)
        partners = E.CATALOG_MODEL_PARTNERS if \
            self.case.program.kind == "catalog" else E.MODEL_PARTNERS
        vd = E.decide(evs, partners)
        st = vd.status
        if st == "trusted" and not self._executed(vd.value):
            st = "derived"
        return {"status": st, "value": vd.value,
                "sources": list(vd.agreeing), "reason": vd.reason}

    def _metamorphic(self):
        from offload.engine import expected as E
        runs = [(e.toolchain, e.variant, e.value)
                for e in self.ev("metamorphic") if e.status == "value"]
        if not runs:
            return None
        gone = {w["toolchain"] for w in self.withdrawn()}
        orig = [(e.toolchain, "original", e.value)
                for e in self.cells(("stored_repeats", "other_toolchains"))
                if e.value is not None and e.mode == self.case.mode]
        # The case's own compiler family is no witness against
        # the expected value in its own case (a deterministic defect gives
        # the same wrong value on the rewrites; a family is never
        # independent evidence)
        me = family(self.case.toolchain)
        runs = [r for r in runs + orig if base_name(r[0]) not in gone
                and family(r[0]) != me]
        return E.metamorphic_evidence(runs)

    def copy_dependent(self) -> bool:
        if self.case.program.lang != "f90" or not self.case.program.text:
            return True
        from offload.engine import expected as E
        try:
            return not E.copy_independent(self.case.program.text,
                                          self.case.program.version or 52).ok
        except Exception:
            return True

    def _executed(self, value: str | None) -> bool:
        if value is None:
            return False
        return bool(self.witnesses(value))

    def witnesses(self, value: str | None = None) -> list[str]:
        """Device cells that printed the expected value (not withdrawn;
        the case's mode for a copy-dependent program)."""
        if value is None:
            value = self.expected_value_cached()
        if value is None:
            return []
        gone = {w["toolchain"] for w in self.withdrawn()}
        dep = self.copy_dependent()
        presence = self.presence_abort()
        # the brief: "at least one other toolchain/mode/arch or the
        # elision gives the expected value"
        out = ["elision"] if self.elision_value() == value and \
            not presence else []
        for e in self.cells():
            if e.toolchain == self.case.toolchain and e.mode == \
                    self.case.mode and e.arch == self.case.arch and \
                    e.variant == "original":
                continue      # the case's own cell (a port is another
                #               program and may be a witness)
            if base_name(e.toolchain) in gone and not e.variant.startswith(
                    "port:"):
                continue
            if dep and e.mode != self.case.mode:
                continue
            if presence and (family(e.toolchain), e.mode) in \
                    no_present_check():
                continue
            if self._passes(e, value):
                out.append(f"{e.toolchain}/{e.arch}/{e.mode}"
                           + (f" ({e.variant})" if e.variant != "original"
                              else ""))
        return sorted(set(out))

    def presence_abort(self) -> bool:
        """The failing run ended in a presence or overlap abort."""
        return bool(PRESENCE_ABORT.search(
            (self.case.reason or "") + "\n" +
            str(self.extra.get("stderr_tail") or "")))

    _exp = None

    def expected_cached(self) -> dict:
        if self._exp is None:
            self._exp = self.expected()
        return self._exp

    def expected_value_cached(self):
        return self.expected_cached()["value"]

    # --- comparisons ----------------------------------------------------------------
    def same_toolchain(self, collector: str) -> list[Evidence]:
        return [e for e in self.cells((collector,))
                if base_name(e.toolchain) == base_name(self.case.toolchain)]

    def other_mode_passes(self) -> bool:
        v = self.expected_value_cached()
        return any(self._passes(e, v) for e in self.cells(("other_mode",)))

    def other_mode_fails(self) -> bool:
        return any(self._fails(e) for e in self.cells(("other_mode",)))

    def other_arch_passes(self, mode: str | None = None) -> bool:
        v = self.expected_value_cached()
        return any(self._passes(e, v) for e in self.cells(("other_arch",))
                   if mode is None or e.mode == mode)

    def other_arch_fails(self, mode: str | None = None) -> bool:
        return any(self._fails(e) for e in self.cells(("other_arch",))
                   if mode is None or e.mode == mode)

    def family_witness(self, e, phase: str) -> bool:
        """Whether another family's cell `e` witnesses the case, by the
        phase of the case's outcome. ``compile``: its front end accepts and
        compiles the same program, whatever happens when it runs (a
        rejection, ICE, compile timeout or environment failure is no
        witness). ``run``: an observable correct run: every run
        correct_on_device on the device, with no ignored / not implemented
        / not supported note. The same family is
        never a witness, nor is a family under test only (GCC,
        catalog/machines.yaml ``under_test_only``)."""
        from offload.engine.confirm.findings import group
        from offload.engine.confirm.machines import under_test_only
        if family(e.toolchain) == family(self.case.toolchain) or not e.runs:
            return False
        if family(e.toolchain) in under_test_only():
            return False  # GCC: a compiler under test only, no witness
        if phase == "compile":
            return group(e.runs[0].outcome, e.runs[0].reason) not in (
                "ice", "rejected", "compile_timeout", "env")
        return all(r.outcome == "correct_on_device" and
                   r.ran_on_host in (0, None) and not re.search(
                       r"ignored|not implemented|not supported",
                       r.reason or "", re.I) for r in e.runs)

    def other_family_compiles(self) -> bool:
        """Another compiler family compiles the program (the compile-phase
        witness of rule R11: ``family_witness(e, "compile")``), on this
        machine or another (catalog/machines.yaml compare_with)."""
        return any(self.family_witness(e, "compile") for e in
                   self.cells(("other_toolchains", "other_mode")))

    def other_family_on_device(self) -> bool:
        """Another compiler family's cell of the same program and mode is
        an observable correct run on the device (the run-phase witness:
        ``family_witness(e, "run")``), original variant."""
        return any(e.mode == self.case.mode and e.variant == "original"
                   and self.family_witness(e, "run")
                   for e in self.cells(("other_toolchains",)))

    def every_family_rejects(self) -> bool:
        """Whether (RUL-UNSUPPORTED-EVERYWHERE) the case is a front-end rejection
        (a diagnosed compile error or not-implemented message), every
        other measured compiler family of the machine has a cell in the
        case's mode, and every other cell is a front-end rejection too
        (an ICE, a compile hang or a link failure is not a rejection)."""
        from offload.engine.confirm.collectors import headline_toolchains
        if not frontend_rejection(self.case.outcome, self.case.reason):
            return False
        me = family(self.case.toolchain)
        cells = [e for e in self.cells(("other_toolchains",))
                 if e.mode == self.case.mode]
        need = {family(t) for t in headline_toolchains(self.case.arch)} - \
            {me}
        have = {family(e.toolchain) for e in cells}
        if not need or not need <= have:
            return False
        if not all(frontend_rejection(e.runs[0].outcome, e.runs[0].reason)
                   for e in cells):
            return False
        # A fuzz program has many unrelated constructs, so another
        # family's rejection, even at the same directive (another clause),
        # is no evidence about the construct this compiler rejects; those
        # cases go to R12b (agent decision). A catalog program tests one
        # feature.
        return self.case.program.kind != "fuzz"

    def missing_families(self) -> list[str]:
        """Measured compiler families with no cell of the program in the
        case's mode (no stored row, no runner, or a runner failure)."""
        from offload.engine.confirm.collectors import headline_toolchains
        me = family(self.case.toolchain)
        need = {family(t) for t in headline_toolchains(self.case.arch)} - \
            {me}
        have = {family(e.toolchain) for e in self.cells(
            ("other_toolchains",)) if e.mode == self.case.mode}
        return sorted(need - have)

    def missing_evidence(self) -> list[dict]:
        """Evidence a collector could not get (runner failures, stored
        harness errors), listed so it is never silently absent."""
        out = []
        for es in self.evidence.values():
            for e in es:
                if not e.runs and e.status == "no_value" and \
                        e.detail.startswith(("runner failure",
                                             "stored harness error")):
                    out.append({"collector": e.collector,
                                "toolchain": e.toolchain, "mode": e.mode,
                                "detail": e.detail[:200]})
        return out

    def own_link_or_hang(self) -> bool:
        """A link failure on symbols the compiler's own generated code
        needs, or a compile that does not finish (RUL-COMPILE-TIME)."""
        r = self.case.reason
        return (self.case.outcome == "rejected" and
                r.startswith("link_undefined_symbol")) or (
            self.case.outcome == "timeout" and "compile" in r)

    def _like_cells(self) -> list[Evidence]:
        """Non-withdrawn device cells comparable with the case: its mode
        for a copy-dependent program, every mode otherwise."""
        gone = {w["toolchain"] for w in self.withdrawn()}
        dep = self.copy_dependent()
        return [e for e in self.cells(("stored_repeats", "repeats",
                                       "other_toolchains", "other_mode",
                                       "other_arch"))
                if e.value is not None and (not dep or e.mode ==
                                            self.case.mode)
                and base_name(e.toolchain) not in gone]

    def oracle_sides(self) -> tuple[list, list]:
        """(cells printing the elision's value, cells printing the
        program's claim), as "toolchain/arch/mode=value"."""
        el, mv = self.elision_value(), self.model_value()
        a = [f"{e.toolchain}/{e.arch}/{e.mode}={e.value}"
             for e in self._like_cells() if e.value == el]
        b = [f"{e.toolchain}/{e.arch}/{e.mode}={e.value}"
             for e in self._like_cells() if e.value == mv]
        return sorted(set(a)), sorted(set(b))

    def elision_and_compilers_against_model(self) -> bool:
        """The sequential elision and the device runs of at least two
        compiler families agree on a value the program's own claim does
        not give, and every comparable device cell with a value prints
        the elision's value (no cell prints the claim)."""
        el, mv = self.elision_value(), self.model_value()
        if el is None or mv is None or el == mv:
            return False
        cells = self._like_cells()
        if not cells or any(e.value != el for e in cells):
            return False
        return len({family(e.toolchain) for e in cells}) >= 2

    def oracle_contested(self) -> bool:
        """The elision and some device runs disagree with the program's
        claim, but some comparable device run prints the claim."""
        el, mv = self.elision_value(), self.model_value()
        if el is None or mv is None or el == mv:
            return False
        a, b = self.oracle_sides()
        return bool(a) and bool(b)

    def host_families(self) -> int:
        """Compiler families whose host build of the fuzz program ran to a
        value (the host check)."""
        from offload.engine.confirm.machines import under_test_only
        hv = self.extra.get("host_values") or {}
        # GCC: a family under test only (GCC) is never evidence
        skip = under_test_only()
        return len({family(t) for t, v in hv.items()
                    if v is not None and family(t) not in skip})

    def noncompliant_by_task22(self, min_families: int) -> bool:
        """The rule as written: no host build and not the elision
        prints the model's value, host builds of at least `min_families`
        families ran, and the case is a value outcome (never a crash)."""
        if self.extra.get("validity") != "noncompliant":
            return False
        if self.case.outcome != "wrong_answer":
            return False
        return self.host_families() >= min_families

    def runtime_failure(self) -> bool:
        return self.case.outcome in RUN_FAILURES

    def registry_kinds(self) -> set[str]:
        return {e.kind for e in self.registry}
