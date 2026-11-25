"""Leads: every failure of a run checked against the catalog's findings and grouped by signature.

A failure is known (a finding's signature: offload.engine.confirm.findings.dedupe, duplicate),
related (dedupe, related) or new. Failures of one compiler family with one signature form a group:
a wrong answer by the kernels it runs, a compile-time or run-time failure by its normalized
message. A group is new only when none of its failures is known or related; its representative
is the smallest program, the one to reduce. Sources: a fuzz run (``fuzz_failures``)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

_RUN_ERROR = re.compile(r"assert|error|fault|abort|illegal|exception|out of bounds|out of memory|failed", re.I)
# a compiler's warnings and summaries in a run's output
_NOISE = re.compile(r"\bwarning\b|^Cray Fortran :|^\s*\d+ (?:errors?|warnings?) generated", re.I)
MODES = {0: "copy", 1: "unified"}            # a fuzz run's HSA_XNACK
# outcomes decided before the program runs: the memory mode (a run-time setting) cannot change them
COMPILE_TIME = ("ice", "rejected", "compile_timeout", "compile_oom")
NOT_LEADS = ("harness_error", "capacity", "correct_on_device", "skipped")


@dataclass(frozen=True)
class Failure:
    campaign: str
    program_id: str
    toolchain: str
    lang: str
    model: str
    mode: str
    outcome: str                # a gate outcome class (offload.engine.gate.outcome_class)
    reason: str
    text: str
    lines: int
    kernels: tuple = ()
    failing: tuple = ()         # every toolchain that fails the program
    output: str = ""            # the failing run's output (a run-time failure's message is there)
    agree: tuple = ()           # the toolchains that ran the program correctly

    @property
    def program_ref(self) -> str:
        """``<run>:<seed>``: how an index entry's ``programs:`` names a fuzz program."""
        return f"{self.campaign.split(':', 1)[-1]}:{self.program_id}"


@dataclass(frozen=True)
class Lead:
    failure: Failure
    status: str                 # known | related | unsupported (the compiler says so) | new
    findings: tuple             # the matching findings' files, best first


@dataclass(frozen=True)
class Group:
    family: str
    signature: str
    leads: tuple

    @property
    def status(self) -> str:
        """known or related when every failure is explained, new or unsupported when none is, else mixed."""
        got = {lead.status for lead in self.leads}
        explained = got & {"known", "related"}
        if explained and got - explained:
            return "mixed"
        return next((s for s in ("known", "related", "unsupported") if s in got), "new")

    @property
    def findings(self) -> tuple:
        return tuple(dict.fromkeys(f for lead in self.leads for f in lead.findings))

    @property
    def unexplained(self) -> tuple:
        """The failures no finding's signature covers (in a known group: what it may still hide)."""
        return tuple(lead for lead in self.leads if lead.status in ("new", "unsupported"))

    @property
    def representative(self) -> Lead:
        pool = self.unexplained or self.leads
        return min(pool, key=lambda lead: (lead.failure.lines, lead.failure.program_id))


def _family(tc: str) -> str:
    from offload.engine.toolchains import TOOLCHAINS
    t = TOOLCHAINS.get(tc)
    return t.family.id if t is not None else tc.rstrip("0123456789_")


def _dedupe(f: Failure) -> list[dict]:
    """The findings whose signature the failure has (dedupe); with none, those it would have on a
    GPU of the finding's scope (related: a finding's arch is where it was seen, not a limit)."""
    from offload.engine.confirm import findings as F
    mode = "" if f.outcome in COMPILE_TIME else f.mode
    hits = F.dedupe(f.toolchain, f.lang, f.outcome, f.reason, f.text, program_id=f.program_ref,
                    mode=mode, output=f.output, related=True)
    if hits:
        return hits
    out = []
    for fi in F.index():
        for arch in fi.arch or ():
            m = F.match(fi, f.toolchain, f.lang, f.outcome, f.reason, f.text, f.program_ref, mode,
                        arch=arch, output=f.output)
            if m:
                out.append({"file": fi.file, "kind": "related", "why": f"{m[1]} (on {arch})"})
                break
    return out


def classify(failures) -> list[Lead]:
    out = []
    for f in failures:
        hits = _dedupe(f)
        dup = tuple(h["file"] for h in hits if h["kind"] == "duplicate")
        rel = tuple(h["file"] for h in hits if h["kind"] == "related")
        # a refusal the compiler itself calls a missing feature (harness category not_implemented)
        missing = f.outcome == "rejected" and (f.reason or "").startswith("not_implemented")
        out.append(Lead(f, "known" if dup else "related" if rel else "unsupported" if missing else "new", dup or rel))
    return out


def signature(f: Failure) -> str:
    """The group key of a failure within its family: a wrong answer by the family's toolchains that
    fail the program (its kernels are its own; a reduction finds its key), any other failure by its
    outcome class and normalized message."""
    if f.outcome in ("wrong_answer", "fell_back_to_host"):
        fam = _family(f.toolchain)
        return f"{f.outcome}|" + ",".join(sorted(t for t in f.failing if _family(t) == fam))
    from offload.engine.confirm.decisions import _msg_key     # paths, names and numbers masked
    first = next((ln for ln in (f.reason or "").splitlines() if ln.strip()), "")
    if f.outcome in ("crash", "run_error", "timeout"):
        # the run's own message (an assertion, a runtime error) says more than the signal
        err = next((ln for ln in (f.output or "").splitlines() if _RUN_ERROR.search(ln) and not _NOISE.search(ln)), "")
        if err:
            first = err.split(": ", 1)[-1] if err.split(": ", 1)[0].endswith(".out") else err
        from offload.engine.reduce import _FAULT_REASON     # the runtime's reason differs between runs
        first = _FAULT_REASON.sub(r"\1", first)
    return f"{f.outcome}|{_msg_key(first)}"


def group(leads) -> list[Group]:
    by: dict = {}
    for lead in leads:
        by.setdefault((_family(lead.failure.toolchain), signature(lead.failure)), []).append(lead)
    return [Group(fam, sig, tuple(ls)) for (fam, sig), ls in sorted(by.items())]


def fuzz_failures(run_dir: Path):
    """The failures of a fuzz run (results/fuzz/<run>/programs.jsonl): one per failing toolchain of
    a program the run's checks found legal (``check`` ok); the program regenerated from its seed."""
    from offload.engine import fuzz
    from offload.engine import gate as G
    run_dir = Path(run_dir)
    meta = json.loads((run_dir / "meta.json").read_text()) if (run_dir / "meta.json").is_file() else {}
    session = (meta.get("sessions") or [{}])[0]
    mode = MODES.get(int(session.get("xnack") or 0), "copy")
    for line in (run_dir / "programs.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("check") != "ok" or rec.get("validity", "valid") != "valid":
            continue
        failing = []
        for tc, r in (rec.get("results") or {}).items():
            cls = G.outcome_class(dict(r, toolchain=tc))
            if G.is_failure(cls) and cls not in NOT_LEADS:
                failing.append((tc, cls, r.get("reason") or "", r.get("output") or ""))
        if not failing:
            continue
        p = fuzz.generate(int(rec["seed"]), rec.get("gen_version") or session.get("gen_version"),
                          tuple(rec.get("base") or session.get("base") or ()))
        n = sum(1 for ln in p.source.splitlines() if ln.strip())
        every = tuple(sorted(tc for tc, _, _, _ in failing))
        agree = tuple(sorted(tc for tc, r in (rec.get("results") or {}).items()
                             if G.outcome_class(dict(r, toolchain=tc)) == "correct_on_device"))
        for tc, cls, reason, output in failing:
            yield Failure(f"fuzz:{run_dir.name}", str(rec["seed"]), tc, p.lang, p.model, mode, cls, reason,
                          p.source, n, tuple(rec.get("kernels") or ()), every, output, agree)


REDUCE_OUT = "results/leads/reduce"
# wrong answers first (silent), then run-time failures, compiler crashes, refusals
_ORDER = {"wrong_answer": 0, "fell_back_to_host": 0, "crash": 1, "run_error": 1, "timeout": 1, "ice": 2}


def priority(signature: str, failures: int) -> tuple:
    return (_ORDER.get(signature.split("|", 1)[0], 3), -failures)


def _elision_blind(f: Failure) -> bool:
    """The sequential elision (a fuzz program's own oracle) cannot read the program: hand-written C, OpenACC, or
    Fortran module variables (declare target visibility)."""
    from offload.engine.fuzz import is_c, is_mfc
    if f.lang == "c" and is_c(f.text):
        return False            # a generated C program: its sequential C run (offload.engine.fuzz.elided_checksum_c)
    if is_mfc(f.text):          # a generated MFC or application program: the elision reads it
        return f.lang == "c"
    return f.lang == "c" or f.model == "acc" or re.search(r"^\s*module\s+\w+", f.text, re.M | re.I) is not None


def reduce_queue(groups, run_dir: str, opt: str = "-O2", xnack: int = 0, budget_minutes: int = 8) -> list[dict]:
    """One tools/reduce.py command per new or mixed group of a fuzz run: its representative (the
    smallest unexplained program) on the toolchain it fails, in the run's mode and at its level.
    A known or related group needs none; a declared missing feature is not a lead."""
    out = []
    run = Path(run_dir).name
    for g in groups:
        if g.status not in ("new", "mixed"):
            continue
        f = g.representative.failure
        name = f"lead-{run}-{f.program_id}-{f.toolchain}"
        ref = []
        if f.outcome in ("wrong_answer", "fell_back_to_host") and _elision_blind(f):
            # a host run of a toolchain of another family that ran it correctly (GCC first: a value,
            # never legality evidence); with none, no oracle and no reduction
            fam = _family(f.toolchain)
            others = sorted((t for t in f.agree if _family(t) != fam), key=lambda t: (_family(t) != "gcc", t))
            if not others:
                continue
            ref = ["--reference", f"host:{others[0]}"]
        verify = []
        if f.outcome in _ORDER and _ORDER[f.outcome] < 2:
            # a run-time failure: every candidate must still run correctly on a compiler of another family
            # that ran the original correctly, so the reduction cannot drift into a broken program
            fam = _family(f.toolchain)
            others = sorted(t for t in f.agree if _family(t) != fam)
            verify = ["--verify-target", f"{others[0]}/{xnack}"] if others else []
        out.append({"name": name, "target": f"{f.toolchain}/{xnack}", "group": g.signature, "family": g.family,
                    "failures": len(g.unexplained), "priority": priority(g.signature, len(g.unexplained)),
                    "toolchains": sorted({lead.failure.toolchain for lead in g.leads}), "lang": f.lang,
                    "mode": f.mode, "outcome": f.outcome, "reason": f.reason, "output": f.output[-4000:],
                    "text": f.text, "program_ref": f.program_ref,
                    "argv": ["--from-row", f"{run_dir}/programs.jsonl", "--id", f.program_id,
                             "--target", f"{f.toolchain}/{xnack}", f"--opt={opt}", *ref, *verify,
                             "--budget-minutes", str(budget_minutes), "--name", name,
                             "--out", f"{REDUCE_OUT}/{name}"]})
    return out


def provisional(e: dict, reduced: str, row: dict):
    """A finished reduction as a finding (offload.engine.confirm.findings.Finding) the remaining
    leads are matched against: the group's toolchains, the reduced program's key constructs, its
    message (a compile-time failure) or compiler-source site (an ICE)."""
    from offload.engine.confirm import findings as F
    from offload.engine.toolchains import TOOLCHAINS
    outcome, reason = e["outcome"], row.get("reason") or e.get("reason") or ""
    tcs = tuple(e.get("toolchains") or (e["target"].split("/")[0],))
    first = next((ln for ln in reason.splitlines() if ln.strip()), "")
    sites = {}
    if outcome == "ice":
        s = F.site_of(first)
        if s:
            sites = {F.base_name(t): s for t in tcs}
    msg = "" if outcome in ("wrong_answer", "fell_back_to_host") else F.normalize(first)
    arch = tuple(sorted({TOOLCHAINS[t].arch for t in tcs if t in TOOLCHAINS})) or ("gfx942",)
    return F.Finding(f"{REDUCE_OUT}/{e['name']}", tcs, e.get("lang", "f90"), outcome, msg,
                     modes=(e.get("mode") or "copy",), arch=arch, constructs=F._key_constructs(reduced), sites=sites)


def covered(e: dict, provisionals) -> str | None:
    """The provisional finding (a finished reduction) whose signature the lead's representative has."""
    from offload.engine.confirm import findings as F
    tc = e["target"].split("/")[0]
    for p in provisionals:
        m = F.match(p, tc, e.get("lang", "f90"), e["outcome"], e.get("reason") or "", e.get("text") or "",
                    e.get("program_ref") or "", e.get("mode") or "", output=e.get("output") or "")
        if m and m[0] == "duplicate":
            return p.file
    return None


def _tail(N: int, K: int, n: int, k: int) -> float:
    """P(X >= k), X hypergeometric: n draws from N programs of which K have the feature."""
    from math import comb
    total = comb(N, n)
    return sum(comb(K, i) * comb(N - K, n - i) for i in range(k, min(K, n) + 1)) / total if total else 1.0


def split_by_features(groups, features: dict, min_support: int = 3, alpha: float = 1e-4,
                      min_lift: float = 2.0) -> list[Group]:
    """Wrong-answer groups split by the generator features their failing programs share far more
    often than the family's other programs (features: {program id: (features, failing)}): the
    feature with the smallest one-sided hypergeometric tail, at least min_support failing programs
    and min_lift times the base rate, takes the failures that have it; the rest are split again."""
    out = []
    for g in groups:
        if not g.signature.startswith(("wrong_answer|", "fell_back_to_host|")):
            out.append(g)
            continue
        rest, pool = list(g.leads), dict(features)
        while True:
            pids = {lead.failure.program_id for lead in rest}
            n, N = len(pids), len(pool)
            best = None
            for f in set().union(*(pool[p][0] for p in pids if p in pool)) if pids else ():
                k = sum(1 for p in pids if p in pool and f in pool[p][0])
                K = sum(1 for v in pool.values() if f in v[0])
                # a feature no program without it fails is a split at any base rate (where twice
                # the base rate cannot be reached)
                sole = k == n and not any(pool[p][1] for p in pool if f not in pool[p][0])
                if k < min_support or K == N or ((k / n) < min_lift * (K / N) and not sole):
                    continue
                p = _tail(N, K, n, k)
                if p < alpha and (best is None or (p, -k) < best[0]):
                    best = ((p, -k), f)
            if best is None:
                break
            f = best[1]
            hit = [lead for lead in rest if f in pool.get(lead.failure.program_id, ((), 0))[0]]
            out.append(Group(g.family, f"{g.signature}|feature:{f}", tuple(hit)))
            rest = [lead for lead in rest if lead not in hit]
            for p in {lead.failure.program_id for lead in hit}:
                pool.pop(p, None)
        if rest:
            out.append(Group(g.family, g.signature, tuple(rest)))
    return out


def fuzz_features(run_dir: Path, family: str) -> dict:
    """{seed: (generator features, a toolchain of the family answered wrong)} of the legal programs of
    a fuzz run the family ran."""
    from offload.engine import gate as G
    out = {}
    for line in (Path(run_dir) / "programs.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("check") != "ok":
            continue
        mine = {tc: r for tc, r in (rec.get("results") or {}).items() if _family(tc) == family}
        if not mine:
            continue
        wrong = any(G.outcome_class(dict(r, toolchain=tc)) in ("wrong_answer", "fell_back_to_host")
                    for tc, r in mine.items())
        out[str(rec["seed"])] = (set(rec.get("features") or ()), wrong)
    return out


def fuzz_groups(run_dir: Path) -> list[Group]:
    """The groups of a fuzz run, wrong-answer groups split by their programs' features."""
    groups = group(classify(fuzz_failures(run_dir)))
    out = []
    for fam in sorted({g.family for g in groups}):
        mine = [g for g in groups if g.family == fam]
        out += split_by_features(mine, fuzz_features(run_dir, fam)) \
            if any(g.signature.startswith("wrong_answer|") for g in mine) else mine
    return out


def _family_toolchains(tc: str) -> tuple:
    from offload.engine.toolchains import TOOLCHAINS
    fam = _family(tc)
    return tuple(sorted(t for t in TOOLCHAINS if _family(t) == fam)) or (tc,)


def clusters(drafts: list[dict]) -> list[list[dict]]:
    """Drafts (queue entries with ``reduced``, the reduced program, and ``row``, its failing row) of
    one candidate bug: two are linked when either's reduced program has the other's signature
    (``provisional`` with every toolchain of the family: a signature in two releases is one bug that
    persisted); the connected sets, largest first."""
    from offload.engine.confirm import findings as F
    provs = []
    for d in drafts:
        p = provisional(dict(d, toolchains=list(_family_toolchains(d["target"].split("/")[0]))), d["reduced"], d["row"])
        provs.append(p)
    parent = list(range(len(drafts)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, d in enumerate(drafts):
        tc = d["target"].split("/")[0]
        for j, p in enumerate(provs):
            if i == j or find(i) == find(j):
                continue
            m = F.match(p, tc, d.get("lang", "f90"), d["outcome"], d["row"].get("reason") or d.get("reason") or "",
                        d["reduced"], "", d.get("mode") or "", output=d["row"].get("output") or d.get("output") or "")
            if m and m[0] == "duplicate":
                parent[find(i)] = find(j)
    groups: dict = {}
    for i, d in enumerate(drafts):
        groups.setdefault(find(i), []).append(d)
    return sorted(groups.values(), key=lambda g: (-len(g), g[0]["name"]))
