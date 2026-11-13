"""The general minimizer: any case, Fortran or C, one file or a
set. A candidate is kept only when the reduced program (a copy; corpus/
is never touched) passes the legality gate and gets the SAME verdict
under the same rules with the same failure group on the same toolchain
and mode (``Reconfirm``: the candidate's own evidence is collected anew).

Candidates: a fuzz-format Fortran program (``! fuzz: kernels`` marks)
uses offload.engine.fuzz_min's transformations (blocks, nest levels,
statements, clauses, right-hand sides, files of a set, cleanup); any other
program uses the generic ones here: delete a directive with its end
directive (Fortran) or a pragma line (C), delete a clause or one item of a
clause's list, delete a statement line, delete a file of a set. Greedy:
the first candidate in order that keeps the verdict wins, repeated until
none does."""
from __future__ import annotations

import hashlib
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from offload.engine.confirm import programs as P
from offload.engine.confirm.model import Case, ProgramRef

DIRECTIVE = re.compile(r"^\s*(?:!\$(?:omp|acc)|#\s*pragma\s+(?:omp|acc))\s+",
                       re.I)
END_DIRECTIVE = re.compile(r"^\s*!\$(?:omp|acc)\s+end\s+", re.I)
KEEP = re.compile(r"^\s*(program|end\s+program|module|end\s+module|"
                  r"contains|implicit|use\s|subroutine|end\s+subroutine|"
                  r"function|end\s+function|integer function|"
                  r"#include|int\s+main|return\s+0|}\s*$|print|printf|"
                  r"write\s*\()", re.I)


@dataclass
class MinResult:
    source: str
    lines_before: int
    lines_after: int
    steps: list = field(default_factory=list)
    calls: int = 0
    verdict: str = ""

    def summary(self) -> str:
        return (f"minimized: {self.lines_before} -> {self.lines_after} lines "
                f"in {len(self.steps)} steps ({self.calls} candidates "
                f"judged), verdict {self.verdict} kept")


def _clause_spans(text: str) -> list[tuple[int, int]]:
    """(start, end) of each top-level clause of a directive line's tail
    (after the directive name words)."""
    spans, depth, start = [], 0, None
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0 and start is not None:
                spans.append((start, i + 1))
                start = None
        elif depth == 0 and re.match(r"[a-z_]", ch, re.I) and start is None \
                and (i == 0 or text[i - 1] in " ,"):
            m = re.match(r"[a-z_]+", text[i:], re.I)
            j = i + m.end()
            if j < len(text) and text[j] == "(":
                start = i
                i = j
                continue
            spans.append((i, j))
            i = j
            continue
        i += 1
    return spans


def _end_of(lines: list[str], k: int) -> int | None:
    """The matching end directive of a Fortran block directive at k."""
    m = DIRECTIVE.match(lines[k])
    if not m or lines[k].lstrip().startswith("#"):
        return None
    words = lines[k][m.end():].split("(")[0].split()
    if not words:
        return None
    first = words[0].lower()
    depth = 0
    for j in range(k + 1, len(lines)):
        mm = DIRECTIVE.match(lines[j])
        if not mm:
            continue
        w = lines[j][mm.end():].split()
        if not w:
            continue
        if w[0].lower() == first:
            depth += 1
        if w[0].lower() == "end" and len(w) > 1 and w[1].lower() == first:
            if depth == 0:
                return j
            depth -= 1
    return None


def generic_candidates(text: str) -> list[tuple[str, str]]:
    files = P.split_files(text)
    if files and len(files) > 1:
        out = [(f"delete file {n}", P.join_files([f for f in files
                                                   if f[0] != n]))
               for n, _ in files[1:]]
        return out + [(f"in {n}: {w}", P.join_files(
            [(m, t2 if m == n else t) for m, t in files]))
            for n, t in files for w, t2 in generic_candidates(t)]
    lines = text.splitlines()
    out = []

    def without(*ks):
        return "\n".join(ln for i, ln in enumerate(lines)
                         if i not in ks) + "\n"
    for k, ln in enumerate(lines):
        if DIRECTIVE.match(ln) and not END_DIRECTIVE.match(ln):
            end = _end_of(lines, k)
            if end is not None:
                out.append((f"unwrap directive at line {k + 1}",
                            without(k, end)))
            elif ln.lstrip().startswith("#"):
                out.append((f"delete pragma at line {k + 1}", without(k)))
    for k, ln in enumerate(lines):
        m = DIRECTIVE.match(ln)
        if not m or END_DIRECTIVE.match(ln):
            continue
        tail = ln[m.end():]
        for a, b in _clause_spans(tail)[1:]:
            new = (ln[:m.end()] + tail[:a] + tail[b:]).rstrip()
            new = re.sub(r"\s+,|,\s*$", "", new)
            out.append((f"delete clause {tail[a:b][:30]} at line {k + 1}",
                        "\n".join(lines[:k] + [new] + lines[k + 1:]) + "\n"))
    for k, ln in enumerate(lines):
        s = ln.strip()
        if not s or s.startswith(("!", "//")) or DIRECTIVE.match(ln) or \
                KEEP.match(ln) or s.endswith("{") or s.startswith("}") or \
                re.match(r"^(do|end\s*do|if|end\s*if|else|for)\b", s, re.I) \
                or "::" in s:
            continue
        out.append((f"delete statement at line {k + 1}", without(k)))
    return out


class Reconfirm:
    """Does a candidate keep the verdict? (cached by text hash)"""

    def __init__(self, case: Case, ctx, verdict: str, confirm=None,
                 gate=None, rule: str | None = None):
        self.case, self.ctx, self.verdict = case, ctx, verdict
        self.rule = rule
        self.cache: dict[str, tuple[bool, str]] = {}
        self.calls = 0
        from offload.engine.confirm import engine as EN
        from offload.engine.confirm import legality as L
        self.confirm = confirm or EN.confirm
        if gate is None:
            from offload.engine.confirm.machines import family_of
            fam = (family_of(case.toolchain),)
            gate = (lambda ref: L.gate(ref, under_test=fam))
        self.gate = gate

    def ref(self, text: str) -> ProgramRef:
        p = self.case.program
        return ProgramRef("file", f"{p.ident}~min", p.lang, p.version,
                          p.model, True, p.needs, p.evidence, text,
                          p.expected)

    def __call__(self, text: str) -> tuple[bool, str]:
        key = hashlib.sha256(text.encode()).hexdigest()
        if key not in self.cache:
            self.cache[key] = self._judge(text)
        return self.cache[key]

    def _judge(self, text: str) -> tuple[bool, str]:
        from offload.engine.confirm import collectors as C
        from offload.engine.confirm import findings as FI
        self.calls += 1
        ref = self.ref(text)
        lg = self.gate(ref)
        if lg.status != "legal":
            return False, f"legality {lg.status}: {lg.basis[:120]}"
        ev = C.run_cell(self.ctx, "minimize", Case(
            ref, self.case.toolchain, self.case.machine, self.case.arch,
            self.case.mode, "unknown"), self.case.toolchain, self.case.mode)
        if ev is None or not ev.runs:
            return False, "no run"
        r = ev.runs[0]
        if FI.group(r.outcome, r.reason) != FI.group(self.case.outcome,
                                                     self.case.reason):
            return False, f"outcome {r.outcome}"
        # Spot check: the same failure, not only the same group
        # (an ICE at another site, another diagnostic or another signal
        # is another defect)
        if signature_of(r.outcome, r.reason) != signature_of(
                self.case.outcome, self.case.reason):
            return False, (f"signature {signature_of(r.outcome, r.reason)}"
                           " differs")
        cand = Case(ref, self.case.toolchain, self.case.machine,
                    self.case.arch, self.case.mode, r.outcome, r.reason,
                    r.value, r.ran_on_host, ev.detail.startswith("values"),
                    len(ev.runs), self.case.opt)
        res = self.confirm(cand, self.ctx, legality=lg)
        same = res["verdict"] == self.verdict and (
            self.rule is None or res["rule"] == self.rule)
        return same, f"{res['verdict']} {res['rule']}"


def signature_of(outcome: str, reason: str) -> str:
    """What must stay the same while minimizing: an ICE's compiler site
    (or its message without positions), a rejection's diagnostic key, a
    crash's signal; a wrong answer is kept by the verdict alone."""
    from offload.engine.confirm import findings as FI
    from offload.engine.confirm.facts import diagnostic_key
    g = FI.group(outcome, reason)
    if g == "ice":
        return FI.site_of(reason) or FI.strip_site(FI.normalize(reason))
    if g == "rejected":
        return diagnostic_key(reason)
    if g == "abort":
        return FI.signal_of(reason) or g
    return g


def minimize_case(case: Case, ctx, verdict: str, workers: int = 4,
                  max_steps: int = 200, judge=None,
                  rule: str | None = None) -> MinResult:
    judge = judge or Reconfirm(case, ctx, verdict, rule=rule)
    text = case.program.text
    before = len(text.splitlines())
    steps = []
    if "! fuzz: kernels" in text and case.program.lang == "f90":
        from offload.engine import fuzz_min as FM
        try:
            res = FM.minimize(text, judge, workers=workers)
        except ValueError as e:      # the failure does not reproduce
            return MinResult(text, before, before, [str(e)[:300]],
                             judge.calls, verdict)
        return MinResult(res.source, before, res.lines_after, res.steps,
                         judge.calls, verdict)
    ok, why = judge(text)
    if not ok:
        return MinResult(text, before, before, ["the case does not "
                                                "reproduce: " + why],
                         judge.calls, verdict)
    with ThreadPoolExecutor(max(1, workers)) as pool:
        for _ in range(max_steps):
            cands = generic_candidates(text)
            hit = None
            for b in range(0, len(cands), workers):
                batch = cands[b:b + workers]
                res = list(pool.map(lambda c: judge(c[1]), batch))
                for c, (good, _) in zip(batch, res):
                    if good:
                        hit = c
                        break
                if hit:
                    break
            if not hit:
                break
            steps.append(hit[0])
            text = hit[1]
    return MinResult(text, before, len(text.splitlines()), steps,
                     judge.calls, verdict)
