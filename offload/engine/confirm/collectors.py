"""Evidence collectors: one class each, with a cost; the engine
runs the ones a rule needs, cheapest first.

A collector reads stored rows first (``Context.index``: the full result
files and the fuzz campaigns, cost 0), then the evidence store (a cell it
ran before: same program hash, toolchain, arch, mode, opt, offload,
variant) and runs the program only when ``Context.allow_run`` and a runner
for the machine exists. A mode or arch a machine does not have is
``not_applicable`` evidence. Every Evidence names its origin
(``provenance``)."""
from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from offload.engine.confirm import machines as M
from offload.engine.confirm import programs as P
from offload.engine.confirm.ingest import Index, Row
from offload.engine.confirm.model import (PASSING, Case, Evidence, Provenance,
                                      Run)
from offload.engine.confirm.store import Store
from offload.engine.toolchains import TOOLCHAINS, base_name

family = M.family_of

from offload.engine.root import ROOT  # noqa: E402


@dataclass
class Context:
    index: Index
    store: Store
    runner: object = None                 # LocalRunner (this machine)
    remote: dict = field(default_factory=dict)   # machine -> runner
    allow_run: bool = False
    repeats: int = 3
    findings: object = None               # findings.FindingsIndex
    log: object = None

    def runner_for(self, machine: str):
        if not self.allow_run:
            return None
        here = self.runner
        if here is not None and getattr(here, "machine", None) in (None,
                                                                   machine):
            return here
        return self.remote.get(machine)


def headline_toolchains(arch: str) -> list[str]:
    """The measured toolchains of the machine of an arch
    (catalog/machines.yaml ``toolchains``; a regression-only toolchain is
    not one), without those of a family under test only (GCC: never
    evidence for another family's case)."""
    m = M.machine_of_arch(arch)
    return _witnessing(m.toolchains) if m is not None else []


def _witnessing(toolchains) -> list[str]:
    """`toolchains` without those of an ``under_test_only`` family."""
    skip = M.under_test_only()
    return [t for t in toolchains if M.family_of(t) not in skip]


def compared_toolchains(case) -> list[str]:
    """The toolchains of other machines a case is compared with
    (catalog/machines.yaml ``compare_with`` of the case's machine: a
    machine whose only family is its own, e.g. wingtip, is compared with
    the AMD families of tuolumne), in the case's mode only and only when
    that machine has it (stored rows; never run). The AMD
    machines are compared with wingtip too (an NVHPC cell is a family
    witness for an AMD-side defect; copy mode only, wingtip has no
    unified mode)."""
    m = M.load().get(case.machine)
    if m is None:
        return []
    out = []
    for other in M.compare_with(m.name):
        om = M.load()[other]
        if om.has(case.mode):
            out += [t for t in _witnessing(om.toolchains) if t not in out]
    return out


def twins(toolchain: str) -> list[str]:
    """The same compiler on the other arches (twins)."""
    b = base_name(toolchain)
    me = TOOLCHAINS[toolchain]
    return [t.name for t in TOOLCHAINS.values()
            if t.base == b and t.arch != me.arch]


def _row_evidence(collector: str, row: Row, case: Case,
                  variant: str = "original") -> Evidence:
    if row.outcome == "harness_error":
        # a stored harness error says nothing about the program
        return Evidence(collector, row.toolchain, row.arch, row.mode,
                        case.opt, "mandatory", variant, case.program.sha,
                        (), None, "no_value",
                        f"stored harness error (not evidence): "
                        f"{row.reason[:200]}",
                        Provenance(origin=row.origin, command="stored row"))
    runs = (Run(row.outcome, row.value, row.ran_on_host, row.reason[:300]),)
    if row.extra.get("repeat_outcomes") and (row.flaky or
                                             row.kind == "fuzz"):
        # the repeats of the row, each with its outcome and value (a
        # harness row lists them when they differed; a fuzz row always)
        runs = tuple(Run(o, v) for o, v in row.extra["repeat_outcomes"]
                     if o != "harness_error") or runs
        return Evidence(collector, row.toolchain, row.arch, row.mode,
                        case.opt, "mandatory", variant, case.program.sha,
                        runs, row.value, "value" if row.value is not None
                        else "no_value", f"flaky={row.flaky}",
                        Provenance(origin=row.origin, host=row.host,
                                   command="stored row"))
    return Evidence(collector, row.toolchain, row.arch, row.mode,
                    case.opt, "mandatory", variant, case.program.sha,
                    runs * max(1, row.repeats) if not row.flaky else runs,
                    row.value, "value" if row.value is not None else
                    "no_value", f"flaky={row.flaky}" if row.flaky else "",
                    Provenance(origin=row.origin, host=row.host,
                               command="stored row"))


def _na(collector: str, case: Case, toolchain: str, why: str, arch="",
        mode="") -> Evidence:
    return Evidence(collector, toolchain, arch, mode, case.opt, "mandatory",
                    "original", case.program.sha, (), None,
                    "not_applicable", why)


def failed_runs(runs) -> bool:
    """Runs that say nothing about the program: a harness error (the
    environment, the runner, ssh, a node of the wrong arch)."""
    return any(r.outcome == "harness_error" for r in runs)


def run_cell(ctx: Context, collector: str, case: Case, toolchain: str,
             mode: str, opt: str | None = None, offload: str = "mandatory",
             variant: str = "original", ref=None, repeats=None
             ) -> Evidence | None:
    """Evidence of one cell from the store, else by a run (None when
    neither is possible)."""
    ref = ref or case.program
    tc = TOOLCHAINS[toolchain]
    opt = opt or case.opt
    key = (collector, ref.sha, toolchain, tc.arch, mode, opt, offload,
           variant)
    hit = ctx.store.get(key)
    if hit is not None:
        return hit
    runner = ctx.runner_for(tc.machine)
    if runner is None or not ref.text:
        return None
    # a runner failure (harness error: environment, ssh, wrong node, no
    # result) is never evidence: tried twice, then reported as missing
    # evidence (no runs, not stored, so a later call runs it again)
    for _ in range(2):
        try:
            runs, prov = runner.run(ref, toolchain, mode, opt, offload,
                                    repeats or ctx.repeats)
        except Exception as e:     # an ssh or runner exception
            runs, prov = [Run("harness_error", None, None,
                              f"runner: {e!r}"[:300])], Provenance()
        if not failed_runs(runs):
            break
    if failed_runs(runs):
        return Evidence(collector, toolchain, tc.arch, mode, opt, offload,
                        variant, ref.sha, (), None, "no_value",
                        "runner failure (not evidence): " + "; ".join(
                            r.reason for r in runs
                            if r.outcome == "harness_error")[:300], prov)
    values = {r.value for r in runs}
    ev = Evidence(collector, toolchain, tc.arch, mode, opt, offload,
                  variant, ref.sha, tuple(runs),
                  runs[0].value if len(values) == 1 else None,
                  "value" if len(values) == 1 and runs[0].value is not None
                  else "no_value", "" if len(values) == 1 else
                  f"values differ: {sorted(map(str, values))}", prov)
    return ctx.store.put(ev)


class Collector:
    name = "abstract"
    cost = 0

    def collect(self, case: Case, ctx: Context) -> list[Evidence]:
        raise NotImplementedError


class StoredRepeats(Collector):
    """The case's own cell: its stored row (the harness ran it 3 times;
    `flaky` when they differed)."""
    name, cost = "stored_repeats", 0

    def collect(self, case, ctx):
        row = ctx.index.get(case.program.kind, case.program.ident,
                            case.toolchain, case.mode)
        if row is not None:
            return [_row_evidence(self.name, row, case)]
        runs = (Run(case.outcome, case.value, case.ran_on_host,
                    case.reason[:300]),)
        return [Evidence(self.name, case.toolchain, case.arch, case.mode,
                         case.opt, "mandatory", "original", case.program.sha,
                         runs * max(1, case.repeats) if not case.flaky
                         else runs, case.value, "value" if case.value
                         else "no_value", f"flaky={case.flaky}",
                         Provenance(origin=str(case.source.get("origin",
                                                               "case"))))]


class Model(Collector):
    """The program's own claim: a catalog program's oracle (check=pass, or
    the probe's error termination), the fuzz model's checksum, a
    finding's stated output, an omp_vv test's exit code 0."""
    name, cost = "model", 0

    def collect(self, case, ctx):
        v = case.program.expected
        return [Evidence(self.name, value=v or None,
                         status="value" if v else "no_value",
                         sha=case.program.sha,
                         detail={"catalog": "the program's own oracle",
                                 "fuzz": "the fuzz model",
                                 "file": "the stated expected output",
                                 "ompvv": "the test's self-check (exit 0)"
                                 }.get(case.program.kind, ""))]


class Derivation(Collector):
    """A hand derivation: the program header's; for a C port
    recorded in catalog/omp/port_equivalence.yaml, its Fortran program's
    (RUL-PORT-DERIVATION); else a registry spec reading
    whose `applies` names the program (ruling: the
    quoted sentence fixes what the check tests, so it derives the
    program's claimed value)."""
    name, cost = "derivation", 0

    def collect(self, case, ctx):
        from offload.engine import expected as E
        sha = case.program.sha
        ev = E.derivation_evidence(case.program.text or "")
        if ev.status == "value":
            return [Evidence(self.name, value=ev.value, sha=sha,
                             detail=str(ev.detail)[:300])]
        if case.program.kind == "catalog":
            from offload.engine.confirm import ports
            got = ports.derivation_for(case.program.ident)
            if got is not None:
                return [Evidence(self.name, value=got[0], sha=sha,
                                 detail=f"the derivation of {got[1]} "
                                        "(port equivalence, "
                                        "RUL-PORT-DERIVATION)")]
            from offload.engine.confirm import registry as REG
            from fnmatch import fnmatchcase
            claim = case.program.expected
            for e in REG.entries().values():
                if e.kind == "spec_reading" and claim and any(
                        fnmatchcase(case.program.ident, p)
                        for p in e.applies.get("programs", ())):
                    return [Evidence(self.name, value=claim, sha=sha,
                                     variant="registry",
                                     detail=f"spec reading {e.cite()}")]
        return [Evidence(self.name, status="no_value", sha=sha,
                         detail=str(ev.detail)[:300])]


TOOLS_EXPECTED = ROOT / "tools" / "derive" / "expected.py"


@lru_cache(maxsize=None)
def _tools_expected():
    spec = importlib.util.spec_from_file_location("tools_expected",
                                                  TOOLS_EXPECTED)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@lru_cache(maxsize=None)
def _expected_records() -> dict:
    """(kind, ident) -> (record, copy-mode record, gfx90a record) of
    results/expected (catalog and fuzz sets)."""
    out = {}
    base = ROOT / "results" / "expected"
    for path in sorted(base.glob("*.jsonl")):
        if ".xnack0" in path.name or ".g90" in path.name:
            continue
        # The NVHPC runs of the catalog set (catalog.nvhpc*.xnack
        # {0,2}.jsonl) are no record of their own: tools/derive/expected.py joins
        # them to the catalog record (nv_of)
        if ".nvhpc" in path.name or ".xnack" in path.name:
            continue
        x0 = {}
        g90 = {}
        p0 = path.with_suffix(".xnack0.jsonl")
        pg = path.with_name(f"{path.stem}.g90.xnack0.jsonl")
        for p, d in ((p0, x0), (pg, g90)):
            if p.is_file():
                for ln in p.read_text().splitlines():
                    if ln.strip():
                        r = json.loads(ln)
                        d[r["key"]] = r
        for ln in path.read_text().splitlines():
            if not ln.strip():
                continue
            r = json.loads(ln)
            if r.get("kind") == "catalog":
                ident = r["program"]
            else:
                ident = f"{r.get('campaign', path.stem)}:{r['seed']}"
            out[(r.get("kind"), ident)] = (r, x0.get(r["key"]),
                                           g90.get(r["key"]), str(path))
    return out


class ExpectedRecord(Collector):
    """The stored expected-behaviour verdict (results/expected,
    tools/derive/expected.py evaluate; triage and withdrawals included):
    the verdict of the case's memory mode."""
    name, cost = "expected_record", 0

    def collect(self, case, ctx):
        found = _expected_records().get((case.program.kind,
                                         case.program.ident))
        if found is None:
            # A program in catalog/expected_triage.yaml whose
            # record is not in results/expected (the 5.0/6.0 schedule
            # programs left the expected set when they were relabelled
            # no-oracle) still carries its triage: withdrawals, finding
            tri = None
            if case.program.kind == "catalog":
                tri = _tools_expected().load_triage().get(
                    (case.program.version, case.program.ident))
            if tri is None:
                return [Evidence(self.name, status="no_value",
                                 detail="no stored expected verdict")]
            st = "implementation_defined" if tri.get("disposition") == \
                "implementation_defined" else "triage_only"
            d = {"status": st, "which": "triage only (no stored record)",
                 "reason": f"triage {tri.get('disposition')}: "
                           f"{tri.get('cite', '')}", "agreeing": [],
                 "withdraw": tri.get("withdraw") or [],
                 "finding": tri.get("finding"),
                 "disposition": tri.get("disposition")}
            if tri.get("needs_human"):
                d["needs_human"] = tri["needs_human"]
            detail = json.dumps(d)
            return [Evidence(self.name, status="no_value", detail=detail,
                             sha=case.program.sha, provenance=Provenance(
                                 origin="catalog/expected_triage.yaml"))]
        rec, x0, g90, path = found
        T = _tools_expected()
        if case.mode == "copy" and x0 is not None and \
                rec.get("kind") == "catalog" and \
                T._copy_dependent(rec["version"], rec["program"]):
            _, vd = T.evaluate_copy_mode(rec, x0)
            which = "copy-mode verdict"
        else:
            _, vd = T.evaluate_both(rec, x0, g90)
            which = "main verdict"
        triage = T.load_triage().get((rec.get("version"),
                                      rec.get("program"))) or {}
        d = {"status": vd.status, "reason": vd.reason, "which": which,
             "agreeing": list(vd.agreeing),
             "withdraw": triage.get("withdraw") or [],
             "finding": triage.get("finding"),
             "disposition": triage.get("disposition")}
        if triage.get("needs_human"):
            # Why the triage's program stays needs_human
            d["needs_human"] = triage["needs_human"]
        detail = json.dumps(d)
        return [Evidence(self.name, value=vd.value, status=(
            "value" if vd.value else "no_value"), sha=case.program.sha,
            detail=detail, provenance=Provenance(origin=path))]


def _cell(ctx, collector, case, toolchain, mode, kind=None, ident=None):
    row = ctx.index.get(kind or case.program.kind,
                        ident or case.program.ident, toolchain, mode)
    if row is not None:
        return _row_evidence(collector, row, case)
    return run_cell(ctx, collector, case, toolchain, mode)


class OtherToolchains(Collector):
    """The same program on the machine's other toolchains: the case's
    mode (stored, else run) and the machine's other modes (stored rows
    only; the facts use them only for a copy-independent program)."""
    name, cost = "other_toolchains", 0

    def collect(self, case, ctx):
        out = []
        modes = M.load()[case.machine].modes
        for t in headline_toolchains(case.arch):
            if t == case.toolchain:
                continue
            ev = _cell(ctx, self.name, case, t, case.mode)
            if ev is not None:
                out.append(ev)
            for mode in modes:
                if mode == case.mode:
                    continue
                row = ctx.index.get(case.program.kind, case.program.ident,
                                    t, mode)
                if row is not None:
                    out.append(_row_evidence(self.name, row, case))
        for t in compared_toolchains(case):  # Stored rows only
            row = ctx.index.get(case.program.kind, case.program.ident, t,
                                case.mode)
            if row is not None:
                out.append(_row_evidence(self.name, row, case))
        return out


class OtherMode(Collector):
    """The same toolchain in the machine's other memory mode(s);
    not_applicable on a single-mode machine."""
    name, cost = "other_mode", 0

    def collect(self, case, ctx):
        m = M.load()[case.machine]
        others = m.other_modes(case.mode)
        if not others:
            return [_na(self.name, case, case.toolchain,
                        f"{m.name} has only the {case.mode} mode")]
        out = []
        for mode in others:
            ev = _cell(ctx, self.name, case, case.toolchain, mode)
            if ev is not None:
                out.append(ev)
            elif not ctx.allow_run:
                pass
        return out


class OtherArch(Collector):
    """The same compiler on the other arches (twin toolchains), in every
    mode their machine has; not_applicable without a twin."""
    name, cost = "other_arch", 0

    def collect(self, case, ctx):
        tw = twins(case.toolchain)
        if not tw:
            return [_na(self.name, case, case.toolchain,
                        "no twin toolchain on another arch")]
        out = []
        for t in tw:
            tc = TOOLCHAINS[t]
            for mode in M.load()[tc.machine].modes:
                ev = _cell(ctx, self.name, case, t, mode)
                if ev is not None:
                    out.append(ev)
        return out


class Port(Collector):
    """The catalog program's C <-> Fortran port on every toolchain of the
    arch, every mode of the machine (stored rows; witnesses of a
    copy-dependent program are filtered to the case's mode by the
    facts)."""
    name, cost = "port", 0

    def collect(self, case, ctx):
        if case.program.kind != "catalog":
            return [_na(self.name, case, "", "not a catalog program")]
        port = P.port_of(case.program.ident)
        if port is None or not ctx.index.rows_of("catalog", port):
            return [_na(self.name, case, "", "no port")]
        out = []
        modes = M.load()[case.machine].modes
        for t in headline_toolchains(case.arch):
            for mode in modes:
                row = ctx.index.get("catalog", port, t, mode)
                if row is None:
                    continue
                out.append(_row_evidence(self.name, row, case,
                                         variant=f"port:{port}"))
        return out


ELISION_ANALYSIS = 2


class Elision(Collector):
    """Sequential elision (offload.engine.expected.elision_evidence; Fortran,
    where ELISION_RULE applies). A fuzz campaign's stored elision value is
    reused."""
    name, cost = "elision", 1

    def collect(self, case, ctx):
        exp = case.program.expected or ""
        free_form = bool(exp) and not exp.startswith(
            ("check=", "checksum=", "error_termination"))
        # the analysis version is part of the key: a stored result of an
        # older elision analysis is not reused (the parser reads a bare `end`)
        variant = ("free-form" if free_form else "original") + \
            f"@{ELISION_ANALYSIS}"
        key = (self.name, case.program.sha, "", "", "", "-O2", "mandatory",
               variant)
        hit = ctx.store.get(key)
        if hit is not None:
            return [hit]
        from offload.engine import widen
        if case.program.kind == "catalog" and widen.is_wide(
                case.program.ident):
            # A widened program's elision is its stored record's
            # (tools/campaigns/widen.py expected: gfortran/amdflang, gcc/amdclang)
            rec = _expected_records().get(("catalog", case.program.ident))
            el = (rec[0].get("elision") or {}) if rec else {}
            if el:
                return [Evidence(self.name, sha=case.program.sha,
                                 value=el.get("value"),
                                 status="value" if el.get("status") ==
                                 "value" else "inapplicable",
                                 detail=el.get("detail", "")[:300],
                                 provenance=Provenance(origin=rec[3]))]
        if case.program.lang != "f90" or P.split_files(case.program.text):
            return [Evidence(self.name, sha=case.program.sha,
                             status="inapplicable",
                             detail="Fortran single-file programs only")]
        row = ctx.index.get(case.program.kind, case.program.ident,
                            case.toolchain, case.mode)
        stored = row.extra.get("elision") if row is not None else None
        if stored and str(stored).startswith("checksum="):
            return [Evidence(self.name, sha=case.program.sha, value=stored,
                             provenance=Provenance(origin=row.origin))]
        if stored and str(stored).startswith(("inapplicable: ",
                                              "no value: ")):
            # The campaign's elision.jsonl (same analysis)
            st = "inapplicable" if stored.startswith("inapplicable") \
                else "no_value"
            return [Evidence(self.name, sha=case.program.sha, status=st,
                             detail=stored.split(": ", 1)[1][:300],
                             provenance=Provenance(origin=row.origin))]
        rec = _expected_records().get((case.program.kind,
                                       case.program.ident))
        if rec is not None and rec[0].get("elision"):
            el = rec[0]["elision"]
            return [Evidence(self.name, sha=case.program.sha,
                             value=el.get("value"),
                             status="value" if el.get("status") == "value"
                             else "inapplicable",
                             detail=str(el.get("detail"))[:300],
                             provenance=Provenance(origin=rec[3]))]
        from offload.engine import expected as E
        from offload.engine.confirm.model import value_of
        # a finding's free-form output: the elided build's output with
        # whitespace collapsed (value_of), else the RESULT line
        free = (lambda out: value_of(out)[0]) if free_form else None
        try:
            ev = E.elision_evidence(case.program.text,
                                    case.program.version or 52, value=free)
        except Exception as e:   # a checker failure is no verdict
            return [Evidence(self.name, sha=case.program.sha,
                             status="no_value", detail=f"error: {e}")]
        status = {"value": "value", "inapplicable": "inapplicable"}.get(
            ev.status, "no_value")
        return [ctx.store.put(Evidence(
            self.name, variant=variant, sha=case.program.sha,
            value=ev.value, status=status,
            detail=str(ev.detail)[:300],
            provenance=Provenance(command="offload.engine.expected."
                                  "elision_evidence", origin="run")))]


class Repeats(Collector):
    """k more runs of the failing cell."""
    name, cost = "repeats", 2

    def collect(self, case, ctx):
        ev = run_cell(ctx, self.name, case, case.toolchain, case.mode)
        return [ev] if ev is not None else []


class HostRun(Collector):
    """OMP_TARGET_OFFLOAD=disabled on the failing toolchain and on one
    toolchain of another family."""
    name, cost = "host_run", 2

    def collect(self, case, ctx):
        out = []
        tcs = [case.toolchain] + [t for t in headline_toolchains(case.arch)
                                  if family(t) != family(case.toolchain)][:1]
        for t in tcs:
            ev = run_cell(ctx, self.name, case, t, case.mode,
                          offload="disabled", repeats=1)
            if ev is not None:
                out.append(ev)
        return out


class Opt0(Collector):
    """The failing cell at -O0."""
    name, cost = "opt0", 3

    def collect(self, case, ctx):
        ev = run_cell(ctx, self.name, case, case.toolchain, case.mode,
                      opt="-O0")
        return [ev] if ev is not None else []


def partner(ctx, case: Case) -> str:
    """The other family's toolchain for the metamorphic runs:
    the first whose stored cell of the program ran correctly on the device
    in the case's mode, else the first of another family."""
    others = [t for t in headline_toolchains(case.arch)
              if family(t) != family(case.toolchain)]
    # A machine with one family takes its partner from the
    # machine it is compared with (a stored cell only: never run there)
    remote = [t for t in compared_toolchains(case)
              if family(t) != family(case.toolchain)]
    for t in others + remote:
        row = ctx.index.get(case.program.kind, case.program.ident, t,
                            case.mode)
        if row is not None and row.outcome in PASSING:
            return t
    if not others:
        return None
    return others[0]


class Metamorphic(Collector):
    """Spec-equivalent rewrites (offload.engine.transforms.variants) on the
    failing toolchain and on one toolchain of another family."""
    name, cost = "metamorphic", 4

    def collect(self, case, ctx):
        if case.program.lang != "f90" or not case.program.text:
            return [Evidence(self.name, sha=case.program.sha,
                             status="inapplicable", detail="Fortran only")]
        from offload.engine import transforms as T
        from offload.engine.confirm.model import ProgramRef
        out = []
        try:
            vs = T.variants(case.program.text, case.program.version or 52)
        except Exception as e:
            return [Evidence(self.name, sha=case.program.sha,
                             status="inapplicable", detail=str(e)[:200])]
        tcs = [case.toolchain] + [t for t in [partner(ctx, case)] if t]
        for name, src in vs.items():
            if not isinstance(src, str):
                continue
            ref = ProgramRef(**{**case.program.__dict__, "text": src})
            for t in tcs:
                ev = run_cell(ctx, self.name, case, t, case.mode,
                              variant=name, ref=ref, repeats=1)
                if ev is not None:
                    out.append(ev)
        return out


COLLECTORS = {c.name: c for c in (
    StoredRepeats(), Model(), Derivation(), ExpectedRecord(),
    OtherToolchains(), OtherMode(), OtherArch(), Port(), Elision(),
    Repeats(), HostRun(), Opt0(), Metamorphic())}


def ordered(names) -> list[Collector]:
    """The named collectors, cheapest first."""
    return sorted((COLLECTORS[n] for n in names),
                  key=lambda c: (c.cost, list(COLLECTORS).index(c.name)))
