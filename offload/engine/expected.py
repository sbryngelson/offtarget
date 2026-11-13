"""Independent sources of expected behaviour, and the rule for trusting one.

A program's expected result (a fuzz checksum, a catalog ``check=pass``, a
negative probe's error termination) is trusted only when two independent
sources agree. Each source yields an ``Evidence`` tagged with one of ``TAGS``:
``elision`` (run with the directives ignored, on the host), ``metamorphic``
(spec-equivalent rewrites), ``model`` (the fuzzer's Python model or the
program's own oracle), ``probe`` (a variant asserting spec-mandated device
state) and ``consensus_only`` (toolchains agreeing; a hint, never counted).
``decide`` returns ``trusted`` when two distinct sources in ``INDEPENDENT``
give the same value and none differs, ``disputed`` when they differ, else
``provisional``. Witnesses from one compiler family count as one source. All
runs behind a verdict share one memory mode; ``assess`` refuses a mix.
``disposition_note`` fits a verdict next to a mutation-audit disposition.
"""
from __future__ import annotations

import atexit
import dataclasses
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from offload.engine import fsource as F
from offload.engine.toolchains import AFAR_BIN

TAGS = {
    "elision": "sequential elision: the program built without OpenMP "
               "(gfortran and amdflang, no -fopenmp) against a sequential "
               "omp_lib and run on the host, where ELISION_RULE applies",
    "metamorphic": "spec-equivalent rewrites (offload.engine.transforms) run on "
                   "the toolchains; the value of the toolchains whose "
                   "outputs coincide on the original and its rewrites",
    "model": "the fuzzer's Python model (counted only with elision or "
             "metamorphic), or a catalog program's own oracle (counted only "
             "with elision)",
    "probe": "a self-checking variant asserting spec-mandated device state "
             "(presence by reference count, device execution); the value "
             "printed by toolchains on which every assertion holds",
    "consensus_only": "the toolchains' own results agreeing: a hint, never "
                      "validation (CCE 19/20/21 share bugs)",
    "derivation": "The expected value derived by hand from the "
                  "spec text, written in the catalog program's header "
                  "(`derivation (<value>):` lines citing section and page): "
                  "computed by no toolchain and not by the generator's "
                  "check code",
}
INDEPENDENT = ("elision", "metamorphic", "model", "probe", "derivation")
# model counts only next to one of these (the brief: the model is trusted
# only where it agrees with elision or a metamorphic variant)
MODEL_PARTNERS = ("elision", "metamorphic")
# a catalog program's oracle is the claim under question: only elision, a
# value computed without any OpenMP toolchain, makes it a second source
# Or a hand derivation from the spec (the brief's "independent
# hand-derived expected value with the derivation written in the program
# header")
CATALOG_MODEL_PARTNERS = ("elision", "derivation")
# sources whose value is printed by OpenMP toolchains: one source when a
# compiler family backs both
TOOLCHAIN_SOURCES = ("metamorphic", "probe")
VERDICTS = {
    "trusted": "two independent sources agree and none disagrees",
    "provisional": "fewer than two independent sources give a value",
    "disputed": "independent sources give different values (recorded, not "
                "resolved by majority)",
    "derived": "Two sources agree (the program's own "
               "oracle and a hand derivation) but no execution shows the "
               "value: no device run, elision or matrix run (program or C "
               "port) printed it",
    "implementation_defined": "Triage: the spec leaves the "
                              "observed behaviour unspecified or "
                              "implementation defined (quoted); not a "
                              "support verdict",
}

ELISION_RULE = """\
Sequential elision applies to a program only if all of these hold
(offload.engine.expected.elision_applicability checks each one; the program
is assumed race-free with deterministic reductions, the precondition of
the method, which the fuzzer guarantees by construction and the catalog
programs are written to meet):

1. No floating-point list item in a reduction, in_reduction or
   task_reduction clause or updated in an atomic construct (reduction
   order), unless the program is a fuzz-3 program, whose values are
   exact in every order by construction (offload.engine.fuzz_base).
2. No OpenMP runtime routine whose value can reach the result. Allowed:
   the ran_on_host flag idiom `x = merge(1, 0, omp_is_initial_device())`
   when x only feeds the ran_on_host field; `x = omp_get_default_device()`
   when x is only used in device clauses; and the guards
   `if (omp_get_thread_num() == 0)` / `if (omp_get_team_num() == 0)` where
   the guarded code runs exactly once in OpenMP execution (a thread guard
   with no loop construct between it and its binding parallel region and a
   team guard inside every enclosing teams region; a team guard directly
   in a teams region). single and masked (filter 0) obey the same
   once-only condition. No write to shared or reduction storage runs once
   per team or thread (redundant_execution: directly in a teams or
   parallel region, with no worksharing construct, single, masked,
   sections or once-only guard between the write and the region, and no
   private copy of the variable there; sequential execution runs it once).
3. No device-only semantics: no present modifier or defaultmap(present),
   no declare target variable or module variable, no device pointers or
   addresses (is_device_ptr, has_device_addr, use_device_ptr,
   use_device_addr), no device(ancestor), no mapper or iterator, no
   requires directive. And the result does not depend on the device data
   environment: a version analysis that runs the program with separate
   host and device copies (map entry/exit, reference counts, always,
   target update, firstprivate/private/lastprivate/reduction copies,
   implicit data-sharing and mapping rules of OpenMP 5.2 §5.8.1, §5.1.1 and
   the combined-construct rules of §17.2) must find that every read sees
   the copy sequential execution would see, both with the reference-count
   rules and with every map copying unconditionally (so the result depends
   neither on copies nor on reference counts).
4. No construct whose sequential execution is not one of its conforming
   executions or whose effect is not on values: linear, scan/inscan,
   ordered depend/doacross, user-defined reductions, declare mapper,
   declare variant, metadirective, dispatch, interop, threadprivate,
   copyin, cancel, error, detach, default(private|firstprivate), masked
   with a nonzero filter, conditional compilation (!$) lines.
5. Base language (the version analysis of rule 3 tracks storage, not
   names): a structure is tracked component by component; the parts of a
   structure mapped on one construct are one storage block whose
   reference count is the structure's, and a part that is not on the
   device may not be mapped while other parts are present (5.2 §5.8.3);
   a referenced element of a structure with mapped elements must itself
   be mapped (5.2 §13.8); a structure referenced without any clause is
   mapped whole (aggregate category), its pointer components excluded
   (their association status is undefined, §5.8.3); a pointer referenced
   in a target region must be a map list item of that construct whose
   pointer or target is created there (attachment), and `p => t` makes p
   an alias of t; an allocatable scalar or a pointer referenced in a
   target region needs an explicit clause; a call of an internal
   subroutine runs its body on the actual arguments (whole variables;
   argument association shares storage except for a pointer actual of a
   non-pointer dummy, 5.2 §5.1.1, which may then not be present on the
   device at the call nor be referenced by another name in the body),
   VALUE dummies are copies, explicit-shape dummies match the actual's
   extents, and an absent optional dummy is ignored in a clause and may
   not be referenced (5.2 §3.2.1); an array section in a map or target
   update clause copies only its part (a later read of the rest counts as
   a dependence), except `:` or `1:extent` in every dimension and an
   update of the section a host loop wrote since the copies agreed.
The ran_on_host field is never compared (sequential elision runs on the
host by definition).
"""

# The result line of a run: a fuzz program prints a checksum, a catalog
# program check=pass/fail. The value compared is "checksum=<n>" or
# "check=<pass|fail>"; "error_termination" for a run that ends in error.
FUZZ_LINE = re.compile(r"^RESULT checksum=(-?\d+) ran_on_host=([01])\s*$",
                       re.M)
CAT_LINE = re.compile(r"^RESULT ran_on_host=([01]) check=(pass|fail)\s*$",
                      re.M)


def value_of(stdout: str) -> str | None:
    """The compared value of one run's output, or None (no or several
    result lines)."""
    f = FUZZ_LINE.findall(stdout)
    c = CAT_LINE.findall(stdout)
    if len(f) + len(c) != 1:
        return None
    return f"checksum={f[0][0]}" if f else f"check={c[0][1]}"


# --- evidence and the agreement rule ------------------------------------------

@dataclass(frozen=True)
class Evidence:
    tag: str
    status: str          # value | inapplicable | no_value | conflict
    value: str | None = None
    detail: str = ""
    observations: tuple = ()   # ((who, value), ...)
    witnesses: tuple = ()      # toolchains behind the value (metamorphic,
    #                            probe)

    def __post_init__(self):
        if self.tag not in TAGS:
            raise ValueError(f"unknown evidence tag {self.tag!r}")
        if self.status not in ("value", "inapplicable", "no_value",
                               "conflict"):
            raise ValueError(f"unknown evidence status {self.status!r}")
        if (self.status == "value") != (self.value is not None):
            raise ValueError("a value exactly when status is 'value'")

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["observations"] = [list(o) for o in self.observations]
        d["witnesses"] = list(self.witnesses)
        return d

    @staticmethod
    def from_dict(d: dict) -> "Evidence":
        d = dict(d)
        d["observations"] = tuple(tuple(o) for o in d.get("observations",
                                                           ()))
        d["witnesses"] = tuple(d.get("witnesses", ()))
        return Evidence(**d)


@dataclass(frozen=True)
class Verdict:
    status: str                  # trusted | provisional | disputed
    value: str | None            # the agreed value (trusted only)
    agreeing: tuple = ()         # tags behind the value
    values: tuple = ()           # ((tag, value), ...) of independent sources
    hints: tuple = ()            # consensus_only values
    reason: str = ""


def _families(e: Evidence) -> set[str]:
    from offload.engine.toolchains import family
    return {family(w) for w in e.witnesses}


def decide(evidence: list[Evidence],
           model_partners: tuple = MODEL_PARTNERS) -> Verdict:
    """The agreement rule (module docstring). `model_partners`: the tags
    next to which `model` counts (CATALOG_MODEL_PARTNERS for a catalog
    program)."""
    vals = [(e.tag, e.value) for e in evidence
            if e.tag in INDEPENDENT and e.status == "value"]
    hints = tuple((e.tag, e.value) for e in evidence
                  if e.tag == "consensus_only" and e.status == "value")
    tags = [t for t, _ in vals]
    if len(tags) != len(set(tags)):
        raise ValueError("one evidence per independent tag")
    distinct = sorted({v for _, v in vals})
    if len(distinct) > 1:
        by = {v: sorted(t for t, w in vals if w == v) for v in distinct}
        parts = "; ".join(f"{'+'.join(ts)}: {v}" for v, ts in by.items())
        why = f"sources disagree ({parts})"
        el = dict(vals).get("elision")
        mo = dict(vals).get("model")
        if el is not None and mo is not None and el != mo:
            why += "; model disagrees with elision: suspected model bug"
        return Verdict("disputed", None, (), tuple(sorted(vals)), hints, why)
    if not distinct:
        return Verdict("provisional", None, (), (), hints,
                       "no independent source gives a value")
    v = distinct[0]
    agreeing = tuple(sorted(tags))
    counted = set(agreeing)
    notes = []
    if set(TOOLCHAIN_SOURCES) <= counted:
        by = {e.tag: e for e in evidence if e.tag in TOOLCHAIN_SOURCES}
        shared = _families(by["metamorphic"]) & _families(by["probe"])
        if shared:
            counted.discard("probe")
            notes.append("metamorphic and probe are one source: both on "
                         f"{', '.join(sorted(shared))}")
    if "model" in counted and not counted & set(model_partners):
        counted.discard("model")
        if len(agreeing) > 1:
            notes.append(f"the model counts only with "
                         f"{' or '.join(model_partners)}")
    tail = "".join(f"; {n}" for n in notes)
    if len(counted) >= 2:
        return Verdict("trusted", v, agreeing, tuple(sorted(vals)), hints,
                       f"{' + '.join(agreeing)} agree{tail}")
    return Verdict("provisional", None, agreeing, tuple(sorted(vals)), hints,
                   f"only {' + '.join(agreeing)}{tail}")


def disposition_note(disposition: str, verdict: Verdict) -> str:
    """The audit disposition with the expected-value verdict next to it.
    The disposition itself is never changed (a trusted expected value does
    not make a weak or unaudited oracle valid: the audit asks whether the
    check depends on the atom, this asks whether the expected value is
    right)."""
    tail = verdict.status
    if verdict.status == "trusted":
        tail += f" ({'+'.join(verdict.agreeing)})"
    return f"{disposition}; expected value {tail}"


# --- evidence from recorded runs ------------------------------------------------

_DERIVATION = re.compile(r"^(?:!|//) derivation(?: \(([^)]*)\))?: (.*)$")


def derivation_evidence(source: str) -> Evidence:
    """The hand derivation in a catalog program's header comment
    block: a first line ``! derivation (<value>): <text>`` (C ``//``) and
    continuation lines ``! derivation: <text>``. No value when the header
    has none."""
    value, text = None, []
    for ln in source.splitlines():
        if not ln.startswith(("!", "//")):
            break
        m = _DERIVATION.match(ln)
        if m:
            if m.group(1):
                value = m.group(1)
            text.append(m.group(2).strip())
    if value is None:
        return Evidence("derivation", "no_value",
                        detail="no derivation in the program header")
    return Evidence("derivation", "value", value, " ".join(text))


def model_evidence(value: str | None, detail: str = "") -> Evidence:
    if value is None:
        return Evidence("model", "no_value", detail=detail)
    return Evidence("model", "value", value, detail)


def consensus_evidence(observations: list[tuple[str, str | None]]
                       ) -> Evidence:
    """The toolchains' results of the original program: the value two or
    more toolchains print (a hint)."""
    obs = tuple((w, v) for w, v in observations if v is not None)
    count: dict[str, list[str]] = {}
    for w, v in obs:
        count.setdefault(v, []).append(w)
    shared = {v: ws for v, ws in count.items() if len(ws) >= 2}
    if len(shared) == 1:
        v, ws = next(iter(shared.items()))
        return Evidence("consensus_only", "value", v,
                        f"{', '.join(ws)} agree", obs)
    if len(shared) > 1:
        return Evidence("consensus_only", "conflict", None,
                        "groups of toolchains agree on different values", obs)
    return Evidence("consensus_only", "no_value", None,
                    "no two toolchains agree", obs)


def metamorphic_evidence(runs: list[tuple[str, str, str | None]]
                         ) -> Evidence:
    """Runs (toolchain, variant, value or None); variant "original" is the
    program itself. A toolchain with at least two values that all coincide
    is a stable witness; the source's value is the stable witnesses'
    common value."""
    by: dict[str, list[tuple[str, str]]] = {}
    for tc, var, v in runs:
        if v is not None:
            by.setdefault(tc, []).append((var, v))
    stable, violations = {}, []
    for tc, vs in sorted(by.items()):
        if len({v for _, v in vs}) == 1 and len(vs) >= 2:
            stable[tc] = vs[0][1]
        elif len({v for _, v in vs}) > 1:
            violations.append(f"{tc}: " + ", ".join(f"{var}={v}"
                                                    for var, v in vs))
    obs = tuple((f"{tc}/{var}", v) for tc, var, v in runs)
    detail = ""
    if violations:
        detail = "relation violated on " + "; ".join(violations)
    vals = sorted(set(stable.values()))
    if len(vals) == 1:
        return Evidence("metamorphic", "value", vals[0],
                        (f"stable on {', '.join(sorted(stable))}" +
                         (f"; {detail}" if detail else "")), obs,
                        tuple(sorted(stable)))
    if len(vals) > 1:
        return Evidence("metamorphic", "conflict", None,
                        "stable witnesses disagree: " + ", ".join(
                            f"{tc}={v}" for tc, v in sorted(stable.items()))
                        + (f"; {detail}" if detail else ""), obs)
    return Evidence("metamorphic", "no_value", None,
                    detail or "no toolchain ran the original and a variant",
                    obs)


def probe_evidence(runs: list[tuple[str, bool | None, str | None]],
                   applicable: str | None = None) -> Evidence:
    """Probe runs (toolchain, all assertions held?, value). `applicable`:
    None, or why no probe could be built."""
    if applicable is not None:
        return Evidence("probe", "inapplicable", detail=applicable)
    tcs = [tc for tc, _, _ in runs]
    if len(tcs) != len(set(tcs)):
        raise ValueError("one probe run per toolchain (a copy-mode probe "
                         "run belongs to its own verdict)")
    ok = {tc: v for tc, held, v in runs if held and v is not None}
    obs = tuple((tc, f"{'held' if held else 'failed' if held is False else 'no result'}"
                 f": {v}") for tc, held, v in runs)
    vals = sorted(set(ok.values()))
    if len(vals) == 1:
        return Evidence("probe", "value", vals[0],
                        f"state verified on {', '.join(sorted(ok))}", obs,
                        tuple(sorted(ok)))
    if len(vals) > 1:
        return Evidence("probe", "conflict", None,
                        "state-verified toolchains disagree: " +
                        ", ".join(f"{t}={v}" for t, v in sorted(ok.items())),
                        obs)
    return Evidence("probe", "no_value", None,
                    "no toolchain held every assertion", obs)


# --- elision applicability -------------------------------------------------------

EXCLUDED_DIRECTIVES = {
    "declare mapper": "declare mapper", "declare reduction":
    "user-defined reduction", "declare variant": "declare variant",
    "metadirective": "metadirective", "dispatch": "dispatch",
    "interop": "interop", "threadprivate": "threadprivate",
    "cancel": "cancel", "cancellation point": "cancel",
    "error": "error directive", "requires": "requires directive",
    "scan": "scan", "declare induction": "induction",
    "begin declare variant": "declare variant",
}
EXCLUDED_CLAUSES = {
    "is_device_ptr": "device pointers", "has_device_addr": "device addresses",
    "use_device_ptr": "device pointers", "use_device_addr":
    "device addresses", "linear": "linear", "detach": "detach",
    "copyin": "threadprivate", "induction": "induction",
    "doacross": "doacross", "uses_allocators": None, "allocate": None,
}
INTRINSIC_RED = {"+", "*", "-", "max", "min", "iand", "ior", "ieor",
                 ".and.", ".or.", ".eqv.", ".neqv."}
LOOP_LEAVES = {"do", "simd", "distribute", "loop", "taskloop"}
STANDALONE = {"target enter data", "target exit data", "target update",
              "barrier", "taskwait", "taskyield", "flush", "depobj",
              "nothing", "section", "declare target", "declare simd",
              "allocate", "assumes", "requires", "error", "scan",
              "cancel", "cancellation point", "interop", "threadprivate",
              "declare reduction", "declare mapper", "declare variant",
              "allocators"}
FLAG_IDIOM = re.compile(r"^(\w+)\s*=\s*merge\(\s*1\s*,\s*0\s*,\s*"
                        r"omp_is_initial_device\(\s*\)\s*\)$", re.I)
DEV_IDIOM = re.compile(r"^(\w+)\s*=\s*omp_get_default_device\(\s*\)$", re.I)
THREAD_GUARD = re.compile(r"^if\s*\(\s*omp_get_thread_num\(\s*\)\s*==\s*0"
                          r"\s*\)\s*(.*)$", re.I)
TEAM_GUARD = re.compile(r"^if\s*\(\s*omp_get_team_num\(\s*\)\s*==\s*0"
                        r"\s*\)\s*(.*)$", re.I)


@dataclass
class Applicability:
    ok: bool
    reasons: list = field(default_factory=list)
    flags: frozenset = frozenset()

    @property
    def why(self) -> str:
        return "; ".join(self.reasons)


@dataclass
class Node:
    kind: str                 # code | do | if | ifstmt | dir | loopdir |
    #                           standalone | atomic
    stmt: F.Stmt | None = None
    dir: F.Dir | None = None
    children: list = field(default_factory=list)
    inner: "Node | None" = None   # ifstmt: the statement
    cond: str = ""                # if / ifstmt condition
    guard: str = ""               # "thread" | "team" | ""
    once: bool = False            # if (i == <first or last i>) in a loop
    loop_var: str = ""
    end_stmt: F.Stmt | None = None   # dir/loopdir/do: the closing stmt
    lo: str = ""
    hi: str = ""
    step: str = ""


_DO = re.compile(r"^(?:\w+\s*:\s*)?do\s+(\w+)\s*=\s*(.+)$", re.I)
_DO_OTHER = re.compile(r"^(?:\w+\s*:\s*)?do(\s+while\b.*|\s*)$", re.I)
_END_DO = re.compile(r"^end\s*do\b", re.I)
_IF_THEN = re.compile(r"^(?:else\s*)?if\s*\((.*)\)\s*then$", re.I)
_ELSE = re.compile(r"^else$", re.I)
_END_IF = re.compile(r"^end\s*if\b", re.I)


def _paren_split(text: str) -> tuple[str, str] | None:
    """`(cond) rest` -> (cond, rest)."""
    if not text.startswith("("):
        return None
    depth = 0
    for k, ch in enumerate(text):
        depth += ch == "("
        depth -= ch == ")"
        if depth == 0:
            return text[1:k], text[k + 1:].strip()
    return None


def _code_node(s: F.Stmt) -> Node:
    low = s.lower
    if low.startswith("if") and re.match(r"if\s*\(", low) and \
            not _IF_THEN.match(s.text):
        ps = _paren_split(s.text[2:].strip())
        if ps:
            cond, rest = ps
            inner = _code_node(F.Stmt(s.first, s.last, rest, "code",
                                      s.indent))
            guard = "thread" if THREAD_GUARD.match(s.text) else \
                "team" if TEAM_GUARD.match(s.text) else ""
            return Node("ifstmt", s, inner=inner, cond=cond, guard=guard)
    return Node("code", s)


def build_tree(stmts: list[F.Stmt], start: int, stop: int,
               version: int = 52) -> list[Node]:
    """The construct tree of statements [start, stop)."""
    root = Node("root")
    stack = [root]
    i = start

    def close_loopdirs():
        # a loop directive closes after its loop; its end directive is
        # optional (consumed by the caller's look-ahead)
        nonlocal i
        while stack[-1].kind == "loopdir" and stack[-1].children and \
                stack[-1].children[-1].kind == "do" and \
                getattr(stack[-1].children[-1], "_closed", False):
            ld = stack.pop()
            ld.end_stmt = ld.children[-1].end_stmt
            nxt = stmts[i + 1] if i + 1 < stop else None
            if nxt is not None and nxt.kind == "dir":
                d = F.parse_dir(nxt, version)
                if d.end and d.base == ld.dir.base:
                    i += 1
                    ld.end_stmt = nxt
            stack[-1].children.append(ld)

    while i < stop:
        s = stmts[i]
        if s.kind == "condcomp":
            raise F.SourceError("conditional compilation line")
        if s.kind == "acc":
            raise F.SourceError("OpenACC directive")
        if s.kind == "dir":
            d = F.parse_dir(s, version)
            if d.end:
                top = stack[-1]
                if top.kind != "dir" or top.dir.base != d.base:
                    raise F.SourceError(f"line {s.first + 1}: unexpected "
                                        f"{d.name}")
                stack.pop()
                top.end_stmt = s
                stack[-1].children.append(top)
            elif d.base in STANDALONE or d.base.startswith("declare"):
                stack[-1].children.append(Node("standalone", s, d))
            elif d.base == "atomic":
                n = Node("atomic", s, d)
                i += 1
                if i >= stop or stmts[i].kind != "code":
                    raise F.SourceError("atomic without a statement")
                n.children.append(_code_node(stmts[i]))
                if i + 1 < stop and stmts[i + 1].kind == "dir":
                    e = F.parse_dir(stmts[i + 1], version)
                    if e.end and e.base == "atomic":
                        i += 1
                stack[-1].children.append(n)
            elif set(d.leaves) & LOOP_LEAVES or d.base in ("tile", "unroll"):
                stack.append(Node("loopdir", s, d))
            else:
                stack.append(Node("dir", s, d))
            i += 1
            continue
        m = _DO.match(s.text)
        if m and not _DO_OTHER.match(s.text):
            var = m.group(1).lower()
            bounds = F.split_top(m.group(2), ",")
            stack.append(Node("do", s, loop_var=var, lo=bounds[0].lower(),
                              hi=bounds[1].lower() if len(bounds) > 1
                              else "",
                              step=bounds[2].lower() if len(bounds) > 2
                              else "1"))
        elif _DO_OTHER.match(s.text):
            stack.append(Node("do", s))
        elif _END_DO.match(s.text):
            top = stack.pop()
            if top.kind != "do":
                raise F.SourceError(f"line {s.first + 1}: end do mismatch")
            top._closed = True
            top.end_stmt = s
            stack[-1].children.append(top)
            close_loopdirs()
        elif _IF_THEN.match(s.text) and not s.lower.startswith("else"):
            cond = _IF_THEN.match(s.text).group(1)
            guard = "thread" if THREAD_GUARD.match(s.text) else \
                "team" if TEAM_GUARD.match(s.text) else ""
            stack.append(Node("if", s, cond=cond, guard=guard))
        elif s.lower.startswith("else"):
            top = stack[-1]
            if top.kind != "if":
                raise F.SourceError(f"line {s.first + 1}: else outside if")
            top.guard = ""      # a guard with an else branch is no guard
            m2 = _IF_THEN.match(s.text)
            top.children.append(Node("code", F.Stmt(
                s.first, s.last, f"!else ({m2.group(1) if m2 else ''})",
                "code")))
        elif _END_IF.match(s.text):
            top = stack.pop()
            if top.kind != "if":
                raise F.SourceError(f"line {s.first + 1}: end if mismatch")
            stack[-1].children.append(top)
        else:
            stack[-1].children.append(_code_node(s))
        i += 1
    if len(stack) != 1:
        raise F.SourceError(f"unclosed construct: {stack[-1].kind}")
    return root.children


# The sequential copy model: versions are ints; a partial or conditional
# write makes an interned (previous, event) version, so two copies agree
# after it only if they agreed before.

class _Versions:
    def __init__(self):
        self.n = 0
        self.table: dict = {}

    def new(self) -> int:
        self.n += 1
        return self.n

    def upd(self, prev: int | None, event: int) -> int:
        key = (prev, event)
        if key not in self.table:
            self.table[key] = self.new()
        return self.table[key]


class _Violation(Exception):
    pass


@dataclass
class _Frame:
    copies: dict                    # leaf -> version (private copies)
    kind: str = ""                  # target | construct
    reductions: frozenset = frozenset()
    attached: frozenset = frozenset()   # target: pointers attached on entry


# --- storage: variables, structure components, pointers ---------------------------

@dataclass
class Leaf:
    """A unit of storage the version analysis tracks: a variable, or a
    component of a structure (``dr%a``, ``dr%nd%k``; ``ds%u`` for the
    component of an array of structures). ``levels`` has one entry per
    part of the path: (rank, extents), extents None when deferred (an
    allocatable or pointer array before its ALLOCATE)."""
    path: str
    root: str
    levels: tuple
    allocatable: bool = False
    pointer: bool = False
    target: bool = False


def _parse_ref(text: str):
    """(path, subscripts per part (None where a part has none), rest) of
    the data reference at the start of `text` (``ds(i)%u`` gives
    ``("ds%u", ["i", None], rest)``), or None."""
    m = re.match(r"\s*([A-Za-z_]\w*)\s*", text)
    if not m:
        return None
    parts, subs = [m.group(1).lower()], [None]
    rest = text[m.end():]
    while True:
        if rest.startswith("("):
            ps = _paren_split(rest)
            if ps is None or subs[-1] is not None:
                return None
            subs[-1], rest = ps[0], ps[1]
            continue
        mm = re.match(r"%\s*([A-Za-z_]\w*)\s*", rest)
        if mm:
            parts.append(mm.group(1).lower())
            subs.append(None)
            rest = rest[mm.end():]
            continue
        return "%".join(parts), subs, rest.strip()


def _assignment(t: str):
    """(path, subscripts per part, rhs) of `ref = rhs`, or None."""
    r = _parse_ref(t)
    if r is None:
        return None
    path, subs, rest = r
    if not rest.startswith("=") or rest.startswith("=="):
        return None
    if path.split("%")[0] in F.KEYWORDS:
        return None
    return path, subs, rest[1:].strip()


def _item_name(item: str) -> str | None:
    m = re.match(r"\s*([A-Za-z_]\w*)", item)
    return m.group(1).lower() if m else None


def _item_ref(item: str):
    """(path, subscripts per part) of a clause list item, or None."""
    r = _parse_ref(item)
    if r is None or r[2]:
        return None
    return r[0], r[1]


def _map_parts(c: F.RawClause) -> tuple[str, list[str], list[str]]:
    """(map type, modifiers, item texts) of a map clause."""
    mods = c.modifiers()
    typ = "tofrom"
    for t in ("tofrom", "to", "from", "alloc", "release", "delete",
              "storage"):
        if t in mods:
            typ = t
    typ = "alloc" if typ == "storage" else typ
    return typ, [m for m in mods if m != typ], list(c.items())


def _red_items(c: F.RawClause) -> tuple[str, list[str]]:
    mods = c.modifiers()
    op = mods[-1] if mods else ""
    return op, [n for n in (_item_name(x) for x in c.items()) if n]


class _Walk:
    """One run of the version analysis (refcounts: the spec's reference
    count rules, or every map copying unconditionally). Values live in
    leaves (``_Analysis.leaf``); a reference to a structure or a structure
    component that is itself a structure is a reference to each leaf under
    it (``_Analysis.under``: pointer components are not part of it). A
    pointer associated with a target (``p => t``) is an alias of the
    target's leaf. Reference counts belong to the root variable: map list
    items with the same containing structure are one storage block (5.2
    §5.8.3)."""

    def __init__(self, an: "_Analysis", flags: set, devvars: set,
                 refcounts: bool, check_reads: bool = True):
        self.check_reads = check_reads
        self.an = an
        self.decls = an.decls
        self.leaf = an.leaf
        self.under = an.under
        self.absent = an.absent
        self.vars = set(an.leaf)
        self.flags, self.devvars = flags, devvars
        self.refcounts = refcounts
        self.V = _Versions()
        self.host: dict = {}
        self.dev: dict = {}
        self.ref: dict = {}             # root -> reference count
        self.devleaves: dict = {}       # root -> leaves of its device block
        self.ptr_ref: dict = {}         # pointer variable -> map count
        self.elis: dict = {}
        self.alias: dict = {}           # pointer path -> target leaf
        self.frames: list[_Frame] = []
        self.ctx: list[Node] = []       # enclosing nodes (dirs, dos, ifs)
        self.levels = {p: list(lf.levels) for p, lf in an.leaf.items()}
        # leaf -> (device version, (lo, hi, step)): host writes since the
        # copies agreed, all in that section (``write``)
        self.sections: dict = {}
        # (names, leaves) of the actual arguments the inlined calls being
        # executed may pass by copy
        self.copied: list[tuple] = []
        for v in self.vars:
            x = self.V.new()            # undefined initial value, shared
            self.host[v] = self.elis[v] = x

    # -- names --

    @staticmethod
    def root(path: str) -> str:
        return path.split("%")[0]

    def skip(self, path: str) -> bool:
        r = self.root(path)
        return r in self.flags or r in self.devvars

    def canon(self, path: str) -> str:
        parts = path.split("%")
        for k in range(len(parts), 0, -1):
            pre = "%".join(parts[:k])
            if pre in self.alias:
                return "%".join([self.alias[pre]] + parts[k:])
        return path

    def is_ptr(self, path: str) -> bool:
        lf = self.leaf.get(path)
        return lf is not None and lf.pointer

    def expand(self, path: str) -> list[str]:
        """The leaves a reference to `path` reads or writes."""
        if self.root(path) in self.absent:
            raise _Violation(f"absent optional dummy argument "
                             f"{self.root(path)} is referenced")
        c = self.canon(path)
        if c != path and any(c in leaves and self.root(path) not in names
                             for names, leaves in self.copied):
            raise _Violation(f"{path} refers to {c}, an actual argument of "
                             "the procedure being executed that may be a "
                             "copy")
        if c in self.leaf:
            return [c]
        if c in self.under:
            return list(self.under[c])
        if "%" in c and self.root(c) in self.leaf:
            raise _Violation(f"component {c} of a structure whose type the "
                             "analysis does not see")
        return []

    def levels_of(self, path: str) -> list:
        """(rank, extents) per part of `path` (its own parts: for a pointer
        alias, the target's)."""
        c = self.canon(path)
        if c in self.levels:
            return self.levels[c]
        leaves = self.under.get(c)
        if leaves:
            return self.levels[leaves[0]][:len(c.split("%"))]
        return []

    def whole(self, path: str, subs: list) -> bool:
        """The reference covers all of `path`'s storage: no subscripts, or
        sections `:` or `1:extent` in every dimension."""
        if all(s is None for s in subs):
            return True
        if path != self.canon(path):
            if any(s is not None for s in subs[:-1]):
                return False
            subs = subs[-1:]
        lv = self.levels_of(path)
        if len(lv) != len(subs):
            return False
        for (rank, ext), s in zip(lv, subs):
            if s is None:
                continue
            dims = [x.strip().lower() for x in F.split_top(s, ",")]
            if ext is None or len(dims) != rank or len(ext) != rank:
                return False
            for d, e in zip(dims, ext):
                if d == ":":
                    continue
                p = [x.strip() for x in F.split_top(d, ":")]
                if len(p) != 2 or p[0] not in ("", "1") or \
                        p[1] not in ("", e):
                    return False
        return True

    # -- copies --

    @property
    def on_device(self) -> bool:
        return any(f.kind == "target" for f in self.frames)

    def _where(self, v: str):
        for f in reversed(self.frames):
            if v in f.copies:
                return ("frame", f)
            if f.kind == "target":
                break
        if self.on_device:
            if v in self.dev:
                return ("dev", None)
            return ("none", None)
        return ("host", None)

    def seen(self, v: str):
        w, f = self._where(v)
        if w == "frame":
            return f.copies[v]
        if w == "dev":
            return self.dev[v]
        if w == "host":
            return self.host[v]
        return None

    def _set(self, v: str, ver: int):
        if not self.check_reads:
            return
        w, f = self._where(v)
        if w == "frame":
            f.copies[v] = ver
        elif w == "dev":
            self.dev[v] = ver
        elif w == "host":
            self.host[v] = ver
        else:
            raise _Violation(f"{v} is written in a target region without a "
                             "device copy")

    def _red_var(self, v: str) -> bool:
        for f in reversed(self.frames):
            if v in f.copies:
                return v in f.reductions
        return False

    def _device_pointer(self, path: str, line: int):
        """A pointer referenced in a target region must have been attached
        on entry to it (5.2 §5.8.3: mapped explicitly on the construct, with
        its pointer or its target newly created)."""
        if not (self.on_device and self.is_ptr(path)):
            return
        for f in reversed(self.frames):
            if f.kind == "target":
                if path not in f.attached:
                    raise _Violation(f"line {line}: pointer {path} is "
                                     "referenced in a target region without "
                                     "being attached on entry")
                return

    def read(self, v: str, line: int, in_update_of: str | None = None):
        if not self.check_reads or self.skip(v):
            return
        self._device_pointer(v, line)
        mine = set(self.expand(in_update_of)) if in_update_of else set()
        for leaf in self.expand(v):
            if self._red_var(leaf):
                if leaf in mine:
                    continue
                raise _Violation(f"line {line}: {leaf} is read inside its "
                                 "reduction region outside its own update")
            if self.seen(leaf) != self.elis[leaf]:
                raise _Violation(
                    f"line {line}: {leaf} is read "
                    f"{'on the device' if self.on_device else 'on the host'} "
                    "from a copy that differs from sequential execution")

    def write(self, v: str, full: bool, line: int, section=None):
        """`section`: the (lo, hi, step) of the loop whose variable is the
        only subscript of a partial write of a rank-1 array on the host
        (``loop_section``)."""
        if not self.check_reads or self.skip(v):
            return
        self._device_pointer(v, line)
        for leaf in self.expand(v):
            e = self.V.new()
            if self._red_var(leaf):
                self.elis[leaf] = self.V.upd(self.elis[leaf], e)
                continue
            where = self._where(leaf)[0]
            if full:
                self._set(leaf, e)
                self.elis[leaf] = e
            else:
                cur = self.seen(leaf)
                self._set(leaf, self.V.upd(cur, e))
                self.elis[leaf] = self.V.upd(self.elis[leaf], e)
            if where == "host":
                # host writes since the copies last agreed, all inside one
                # section: a target update of that section makes them
                # agree again
                old = self.sections.get(leaf)
                if not full and section is not None and (
                        old is None and self.dev.get(leaf) == cur or
                        old is not None and old[1] == section):
                    self.sections[leaf] = (old[0] if old else cur, section)
                else:
                    self.sections.pop(leaf, None)

    def loop_section(self, path: str, subs: list):
        """(lo, hi, step) when the only subscript of `path` (a rank-1
        array) is the variable of the innermost enclosing loop with that
        variable, else None."""
        if any(x is not None for x in subs[:-1]) or subs[-1] is None:
            return None
        idx = subs[-1].strip().lower()
        for n in reversed(self.ctx):
            if n.kind == "do" and n.loop_var == idx:
                return (n.lo, n.hi, n.step)
        return None

    # -- maps --

    def _groups(self, items) -> dict:
        """root -> [(leaves, map type, modifiers, whole)] of map list items
        (path, map type, modifiers, subscripts per part)."""
        groups: dict = {}
        for path, typ, mods, subs in items:
            if self.root(path) in self.absent:
                continue        # an absent optional dummy: no effect
            if self.skip(path):
                continue
            leaves = self.expand(path)
            if not leaves:
                continue
            groups.setdefault(self.root(self.canon(path)), []).append(
                (leaves, typ, mods, self.whole(path, subs)))
        return groups

    def _copy(self, dst: dict, src: dict, leaf: str, whole: bool):
        if whole or dst.get(leaf) == src[leaf]:
            dst[leaf] = src[leaf]
        else:
            # a section: the copies agree only where it was copied
            dst[leaf] = self.V.upd(dst.get(leaf), self.V.new())

    def map_enter(self, items) -> dict:
        """Map entry of a construct's list items; returns the reference
        counts before it."""
        groups = self._groups(items)
        before = {r: self.ref.get(r, 0) for r in groups}
        for r, its in groups.items():
            cnt = before[r]
            block = set().union(*(set(lv) for lv, _, _, _ in its))
            if cnt == 0 or not self.refcounts:
                for leaves, typ, mods, whole in its:
                    for leaf in leaves:
                        if cnt == 0:
                            self.dev.pop(leaf, None)    # new storage
                        if typ in ("to", "tofrom"):
                            self._copy(self.dev, self.host, leaf, whole)
                        elif leaf not in self.dev:
                            self.dev[leaf] = self.V.new()   # uninitialised
                self.devleaves[r] = block if cnt == 0 else \
                    self.devleaves.get(r, set()) | block
            else:
                if not block <= self.devleaves.get(r, set()):
                    raise _Violation(
                        f"{r}: a part of the structure that is not on the device "
                        "is mapped while other parts are present (5.2 §5.8.3: "
                        "one storage block)")
                for leaves, typ, mods, whole in its:
                    if "always" in mods and typ in ("to", "tofrom"):
                        for leaf in leaves:
                            self._copy(self.dev, self.host, leaf, whole)
            self.ref[r] = cnt + 1
        return before

    def map_exit(self, items):
        for r, its in self._groups(items).items():
            cnt = self.ref.get(r, 0)
            if cnt == 0:
                continue                # not present: no effect
            cnt = 0 if any(t == "delete" for _, t, _, _ in its) else cnt - 1
            for leaves, typ, mods, whole in its:
                if typ in ("from", "tofrom") and (
                        cnt == 0 or "always" in mods or not self.refcounts):
                    for leaf in leaves:
                        if leaf in self.dev:
                            self._copy(self.host, self.dev, leaf, whole)
            self.ref[r] = cnt
            if cnt == 0:
                for leaf in self.devleaves.pop(r, ()):
                    self.dev.pop(leaf, None)

    def update(self, path: str, subs: list, to: bool):
        """target update to/from of one list item."""
        if self.skip(path):
            return
        whole = self.whole(path, subs)
        sec = None
        if not whole and all(x is None for x in subs[:-1]):
            p = [x.strip().lower() for x in F.split_top(subs[-1], ":")]
            if len(p) in (2, 3) and "," not in subs[-1]:
                sec = (p[0], p[1], p[2] if len(p) == 3 else "1")
        for leaf in self.expand(path):
            if leaf not in self.dev:
                continue
            pend = self.sections.get(leaf)
            if to and sec is not None and pend is not None and \
                    pend[1] == sec and self.dev[leaf] == pend[0]:
                self.dev[leaf] = self.host[leaf]
                self.sections.pop(leaf)
            elif to:
                self._copy(self.dev, self.host, leaf, whole)
            else:
                self._copy(self.host, self.dev, leaf, whole)

    # -- statements --

    def full_write(self, path: str, subs: list) -> bool:
        """A write `ref = ...` covers all of `path`: no subscripts, or
        subscripts that are the variables of enclosing unconditional loops
        over the declared extents (or `:`), each loop variable once."""
        if self._conditional():
            return False
        if all(s is None for s in subs):
            return True
        if path != self.canon(path):
            if any(s is not None for s in subs[:-1]):
                return False
            subs = subs[-1:]
        lv = self.levels_of(path)
        if len(lv) != len(subs):
            return False
        loops = {n.loop_var: n for n in self.ctx if n.kind == "do"}
        used = []
        for (rank, ext), s in zip(lv, subs):
            if s is None:
                continue
            idx = [x.strip().lower() for x in F.split_top(s, ",")]
            if ext is None or len(ext) != len(idx):
                return False
            for x, e in zip(idx, ext):
                if x == ":":
                    continue
                n = loops.get(x)
                if n is None:
                    return False
                if not ((n.lo == "1" and n.hi == e and n.step == "1") or
                        (n.lo == e and n.hi == "1" and n.step == "-1")):
                    return False
                used.append(x)
        return len(set(used)) == len(used)

    def _conditional(self) -> bool:
        return any(n.kind in ("if", "ifstmt") and not n.guard and
                   not n.once for n in self.ctx)

    def once_in_loop(self, cond: str) -> bool:
        """`i == c` where i is the variable of an enclosing unconditional
        loop that takes the value c exactly once (c its first value, or
        its last with step 1 or -1)."""
        m = re.match(r"^\s*(\w+)\s*==\s*(\w+)\s*$", cond)
        if not m:
            return False
        var, c = m.group(1).lower(), m.group(2).lower()
        for k in range(len(self.ctx) - 1, -1, -1):
            n = self.ctx[k]
            if n.kind == "do" and n.loop_var == var:
                if any(x.kind in ("if", "ifstmt") and not x.guard and
                       not x.once for x in self.ctx[k:]):
                    return False
                return c == n.lo or (c == n.hi and n.step in ("1", "-1"))
        return False

    def code(self, s: F.Stmt):
        t, line = s.text, s.first + 1
        low = s.lower
        if low.startswith(CALL_MARK):
            parts = t.split()
            name = parts[1]
            if self.on_device:
                raise _Violation(f"line {line}: internal procedure {name} "
                                 "called in a target region")
            copied = [] if parts[2] == "-" else parts[2].split(",")
            for a in copied:
                if self.ref.get(self.root(self.canon(a)), 0) > 0:
                    raise _Violation(
                        f"line {line}: actual argument {a} of {name} is "
                        "present on the device at the call (a copy-in/"
                        "copy-out argument would not be)")
            for req in parts[3:]:
                a, ext = req.split("=")
                lv = self.levels_of(a)
                if not lv or lv[-1][1] != tuple(ext.split("|")):
                    raise _Violation(
                        f"line {line}: explicit-shape dummy of {name}: the "
                        f"extents of actual {a} are not known to be "
                        f"({', '.join(ext.split('|'))})")
            self.copied.append((set(copied), {leaf for a in copied
                                              for leaf in self.expand(a)}))
            return
        if low.startswith(END_CALL_MARK):
            self.copied.pop()
            return
        if low.startswith("!else"):
            for v in F.designators(t[5:]):
                self.read(v, line)
            return
        if re.match(r"(print|write)\b", low):
            for v in F.designators(t):
                if v not in F.KEYWORDS:
                    self.read(v, line)
            return
        m = re.match(r"allocate\s*\((.*)\)$", t, re.I)
        if m:
            if self.on_device:
                raise _Violation(f"line {line}: allocate in a target region")
            for item in F.split_top(m.group(1), ","):
                r = _item_ref(item)
                if r is None:
                    raise _Violation(f"line {line}: allocate item {item!r}")
                path, subs = r
                self.alias.pop(path, None)  # a pointer gets its own target
                for v in F.designators(subs[-1] or ""):
                    self.read(v, line)
                for leaf in self.expand(path):
                    lv = self.levels[leaf]
                    dims = [x.strip().lower() for x in
                            F.split_top(subs[-1], ",")] if subs[-1] else []
                    lv[-1] = (len(dims), tuple(dims) if all(
                        ":" not in d for d in dims) else None)
                self.write(path, True, line)
            return
        if re.match(r"deallocate\b", low) or low in (
                "continue", "exit", "cycle", "stop") or \
                re.match(r"(stop|return)\b", low):
            return
        m = re.match(r"(.+?)\s*=>\s*(.+)$", t)
        if m and not m.group(1).strip().startswith("("):
            if self.on_device:
                raise _Violation(f"line {line}: pointer assignment in a "
                                 "target region")
            lhs, rhs = _item_ref(m.group(1)), _item_ref(m.group(2))
            if lhs is None or not self.is_ptr(lhs[0]) or \
                    any(x is not None for x in lhs[1]):
                raise _Violation(f"line {line}: pointer assignment not "
                                 f"understood: {t!r}")
            if rhs is None or any(x is not None for x in rhs[1]):
                raise _Violation(f"line {line}: pointer target is not a "
                                 f"whole variable: {t!r}")
            tgt = self.canon(rhs[0])
            if tgt not in self.leaf or not (self.leaf[tgt].target or
                                            self.leaf[tgt].pointer):
                raise _Violation(f"line {line}: pointer target {rhs[0]} is "
                                 "not a TARGET variable")
            self.alias[lhs[0]] = tgt
            return
        m = re.match(r"call\s+(\w+)\s*(\((.*)\))?$", t, re.I)
        if m:
            for v in F.designators(m.group(3) or ""):
                self.read(v, line)
            for a in F.split_top(m.group(3) or "", ","):
                r = _parse_ref(a.strip())
                if r is not None and not r[2]:
                    self.write(r[0], False, line)
            return
        m = _assignment(t)
        if m is None:
            raise _Violation(f"line {line}: statement not understood: {t!r}")
        path, subs, rhs = m
        if self.skip(path):
            return
        for v in F.designators(rhs) + [d for x in subs if x
                                       for d in F.designators(x)]:
            self.read(v, line, in_update_of=path)
        self.write(path, self.full_write(path, subs), line,
                   self.loop_section(path, subs))


CALL_MARK = "!call "
END_CALL_MARK = "!endcall "


class _Analysis:
    """A source split for the analysis: the main program's declarations and
    the derived types it defines, its storage leaves, and its execution
    part with every call of an internal subroutine replaced by the
    subroutine's body (``inline``)."""

    def __init__(self, source: str, version: int):
        self.source, self.version = source, version
        self.stmts = F.statements(source)
        start, stop = F.main_program(self.stmts)
        prog = next(i for i, s in enumerate(self.stmts)
                    if s.kind == "code" and
                    re.match(r"program\s+\w+", s.lower))
        self.decls = F.declarations(self.stmts, prog + 1, start)
        self.all_decls = F.declarations(self.stmts)
        self.types = F.type_defs(self.stmts)
        self.absent: set = set()
        self.procs = F.internal_procedures(self.stmts) \
            if stop < len(self.stmts) and self.stmts[stop].lower == \
            "contains" else {}
        self.has_procs = bool(self.procs)
        self.body = self.inline(self.stmts[start:stop], 0)
        self.leaf: dict[str, Leaf] = {}
        self.under: dict[str, list[str]] = {}
        for name, v in self.decls.items():
            if not v.parameter:
                self._add_leaf(name, name, v, ())

    # -- leaves --

    def _add_leaf(self, path: str, root: str, v: F.Var, levels: tuple,
                  depth: int = 0):
        lv = levels + ((v.rank, v.extents if (v.extents or v.rank == 0)
                        else None),)
        m = re.match(r"type\s*\(\s*(\w+)\s*\)", v.type)
        t = self.types.get(m.group(1).lower()) if m else None
        if t is None:
            self.leaf[path] = Leaf(path, root, lv, v.allocatable, v.pointer,
                                   v.target)
            return
        if v.pointer or v.allocatable or depth > 8:
            raise F.SourceError(f"{path}: pointer or allocatable structure")
        for cn, cv in t.items():
            self._add_leaf(f"{path}%{cn}", root, cv, lv, depth + 1)
        self.under[path] = [p for p, lf in self.leaf.items()
                            if p.startswith(path + "%") and not lf.pointer]

    # -- internal procedures --

    def inline(self, stmts: list, depth: int) -> list:
        """`stmts` with each `call p(...)` of an internal subroutine p
        replaced by: a marker statement (CALL_MARK, naming the actual
        arguments that may be passed by copy-in/copy-out), an assignment of
        each VALUE dummy's copy, and p's body with its dummies renamed to
        the actual arguments and its locals to names of their own. The
        call executes p's body on the caller's variables (argument
        association by reference) in OpenMP and in sequential execution
        alike; ``_Walk.code`` checks that no actual argument that could be
        copied is present on the device at the call, so the presence the
        body's maps find is the caller's."""
        out = []
        for s in stmts:
            m = re.match(r"call\s+(\w+)\s*(?:\((.*)\))?\s*$", s.text, re.I) \
                if s.kind == "code" else None
            if m and m.group(1).lower() in self.procs:
                out += self._expand_call(s, m.group(1).lower(),
                                         m.group(2) or "", depth)
                continue
            names = F.designators(s.text if s.kind == "code" else
                                  " ".join(c.arg or "" for c in
                                           F.parse_dir(s, self.version)
                                           .clauses)
                                  if s.kind == "dir" else "")
            if set(names) & set(self.procs):
                raise F.SourceError(f"line {s.first + 1}: internal procedure "
                                    "referenced other than by a CALL "
                                    "statement")
            out.append(s)
        return out

    def _expand_call(self, s: F.Stmt, name: str, args: str,
                     depth: int) -> list:
        if depth > 4:
            raise F.SourceError(f"internal procedure {name}: calls nested too "
                                "deeply")
        p = self.procs[name]
        actuals = [a.strip() for a in F.split_top(args, ",") if a.strip()]
        if len(actuals) > len(p.dummies) or \
                any(re.match(r"\w+\s*=[^=]", a) for a in actuals):
            raise F.SourceError(f"line {s.first + 1}: call of {name} not "
                                "understood (keyword or extra arguments)")
        mapping, pre, copied, shapes = {}, [], [], []
        for k, d in enumerate(p.dummies):
            dv = p.decls.get(d)
            if dv is None:
                raise F.SourceError(f"{name}: dummy {d} not declared")
            if k >= len(actuals):
                if not dv.optional:
                    raise F.SourceError(f"line {s.first + 1}: {name}: "
                                        f"missing actual for {d}")
                new = f"{name}__absent__{d}"
                mapping[d] = new
                self.absent.add(new)
                continue
            a = actuals[k]
            if dv.value:
                new = f"{name}__{d}"
                mapping[d] = new
                self.decls[new] = dataclasses.replace(dv, name=new,
                                                      value=False,
                                                      intent="")
                pre.append(F.Stmt(s.first, s.last, f"{new} = {a}", "code",
                                  s.indent))
                continue
            if not re.fullmatch(r"[A-Za-z_]\w*", a):
                raise F.SourceError(f"line {s.first + 1}: {name}: actual "
                                    f"argument {a!r} is not a variable")
            av = self.decls.get(a.lower())
            if av is None or av.parameter:
                raise F.SourceError(f"line {s.first + 1}: {name}: actual "
                                    f"argument {a} is not a variable")
            if (dv.allocatable and not av.allocatable) or \
                    (dv.pointer and not av.pointer) or \
                    (dv.type.startswith("type") and dv.type != av.type) or \
                    dv.rank != av.rank or \
                    (dv.extents and av.extents and
                     dv.extents != av.extents) or \
                    (dv.rank and not dv.extents and
                     not (dv.allocatable or dv.pointer) and
                     re.search(r"\(\s*\*", dv.type)) or \
                    (dv.intent == "out" and dv.allocatable):
                raise F.SourceError(f"line {s.first + 1}: {name}: dummy {d} "
                                    f"and actual {a} are not associated "
                                    "element by element")
            if dv.extents and not av.extents:
                # explicit shape against a deferred-shape actual: checked
                # against the actual's allocated extents at the call
                shapes.append((a.lower(), dv.extents))
            mapping[d] = a.lower()
            if av.pointer and not dv.pointer:
                # a pointer's target may be discontiguous: the dummy may be
                # a copy (5.2 §5.1.1 calls a dummy argument's storage the
                # actual's only for a scalar, a structure or an array that
                # is not a pointer or assumed-shape array)
                copied.append(a.lower())
        for local, lv in p.decls.items():
            if local in p.dummies:
                continue
            new = f"{name}__{local}"
            mapping[local] = new
            self.decls[new] = dataclasses.replace(lv, name=new)
        body = [F.Stmt(t.first, t.last, F.rename(t.text, mapping), t.kind,
                       t.indent) for t in p.body]
        mark = F.Stmt(s.first, s.last,
                      f"{CALL_MARK}{name} {','.join(copied) or '-'} " +
                      " ".join(f"{a}={'|'.join(e)}" for a, e in shapes),
                      "code", s.indent)
        end = F.Stmt(s.last, s.last, f"{END_CALL_MARK}{name}", "code",
                     s.indent)
        return [mark] + pre + self.inline(body, depth + 1) + [end]

    def static_exclusions(self) -> tuple[list[str], set, set]:
        """Reasons the program is out of scope before any walk, the
        ran_on_host flag variables, and device-number variables."""
        why: list[str] = []
        st = self.stmts
        if any(s.kind == "condcomp" for s in st):
            why.append("conditional compilation (!$) line")
        # module variables
        in_mod, in_type, mod_vars = False, False, []
        for s in st:
            low = s.lower if s.kind == "code" else ""
            if in_type:
                in_type = not F._END_TYPE.match(low)
            elif re.match(r"module\s+\w+$", low):
                in_mod = True
            elif low.startswith("contains") and in_mod:
                in_mod = False
            elif in_mod and F._TYPEDEF.match(low):
                in_type = True
            elif in_mod and F._TYPE.match(s.text) and \
                    "parameter" not in low:
                mod_vars.append(s.text)
        if mod_vars:
            why.append("module variables (declare target visibility)")
        fp = {n for n, v in self.decls.items()
              if v.type.startswith(("real", "double", "complex"))}
        flags, devvars = set(), set()
        body = self.body
        for s in body:
            if s.kind != "code":
                continue
            m = FLAG_IDIOM.match(_strip_if(s.text))
            if m:
                flags.add(m.group(1).lower())
            m = DEV_IDIOM.match(s.text)
            if m:
                devvars.add(m.group(1).lower())
        # flags may only be initialised, set by the idiom, listed in
        # clauses and printed in the ran_on_host field
        for s in body:
            if s.kind != "code":
                continue
            ids = set(F.identifiers(s.text))
            bad = ids & (flags | devvars)
            if not bad:
                continue
            txt = _strip_if(s.text)
            if FLAG_IDIOM.match(txt) or DEV_IDIOM.match(txt):
                continue
            if re.match(r"(\w+)\s*=\s*-?\d+$", txt):
                continue
            if re.match(r"print\b", s.lower) and "ran_on_host" in s.lower:
                continue      # the ran_on_host field (never compared)
            why.append(f"ran_on_host flag or device number "
                       f"{', '.join(sorted(bad))} used in a value "
                       f"(line {s.first + 1})")
        for s in body:
            if s.kind != "code":
                continue
            for name in re.findall(r"\b(omp_\w+)\s*\(", s.text, re.I):
                txt = _strip_if(s.text)
                if name.lower() == "omp_is_initial_device" and \
                        FLAG_IDIOM.match(txt):
                    continue
                if name.lower() == "omp_get_default_device" and \
                        DEV_IDIOM.match(txt):
                    continue
                if THREAD_GUARD.match(s.text) or TEAM_GUARD.match(s.text):
                    continue
                why.append(f"runtime routine {name.lower()} "
                           f"(line {s.first + 1})")
        for s in st:
            if s.kind != "dir":
                continue
            d = F.parse_dir(s, self.version)
            if d.end:
                continue
            if d.base in EXCLUDED_DIRECTIVES:
                why.append(EXCLUDED_DIRECTIVES[d.base])
            if d.base == "declare target":
                items = [_item_name(x) for x in
                         F.split_top(d.args or "", ",") if x]
                for c in d.clauses:
                    items += [_item_name(x) for x in c.items()]
                if any(n in self.all_decls for n in items if n):
                    why.append("declare target variable")
            if d.base == "ordered" and (d.clause("depend") or
                                        d.clause("doacross")):
                why.append("ordered depend/doacross")
            if d.base == "masked":
                for c in d.clause("filter"):
                    if (c.arg or "").strip() != "0":
                        why.append("masked with a nonzero filter")
            for c in d.clauses:
                if c.name in EXCLUDED_CLAUSES and EXCLUDED_CLAUSES[c.name]:
                    why.append(EXCLUDED_CLAUSES[c.name])
                mods = c.modifiers()
                if c.name in ("map", "to", "from", "defaultmap") and (
                        "present" in mods or (c.name == "defaultmap" and
                                              (c.arg or "").lower()
                                              .startswith("present"))):
                    why.append("present modifier")
                if c.name in ("map", "to", "from", "depend") and any(
                        m.startswith(("iterator", "mapper")) for m in mods):
                    why.append("iterator or mapper modifier")
                if c.name == "map" and any(m in ("self", "ref_ptr",
                                                 "ref_ptee", "ref_ptr_ptee")
                                           for m in mods):
                    why.append("6.0 map modifier")
                if c.name == "defaultmap" and (c.arg or "").lower().split(
                        ":")[0].strip() in ("self", "private", "present"):
                    why.append(f"defaultmap({c.arg})")
                if c.name == "device" and "ancestor" in mods:
                    why.append("device(ancestor)")
                if c.name == "default" and (c.arg or "").lower().strip() in (
                        "private", "firstprivate"):
                    why.append(f"default({c.arg})")
                if c.name in ("reduction", "in_reduction",
                              "task_reduction"):
                    op, items = _red_items(c)
                    if "inscan" in mods:
                        why.append("inscan reduction")
                    if op and op not in INTRINSIC_RED:
                        why.append(f"reduction identifier {op}")
                    if set(items) & fp and not exact_fp(self.source):
                        why.append("floating-point reduction")
        return sorted(set(why)), flags, devvars


_GEN = re.compile(r"^! generator: fuzz-(\d+)\s*$", re.M)


def exact_fp(source: str) -> bool:
    """A fuzz-3 program (offload.engine.fuzz_base): every floating-point
    value, and every partial result of any reduction order, is exactly
    representable by construction, so rule 1 (reduction order) does not
    exclude its floating-point reductions."""
    m = _GEN.search(source)
    return m is not None and int(m.group(1)) >= 3


def _strip_if(text: str) -> str:
    """The statement of a one-line if (or the text itself)."""
    if re.match(r"if\s*\(", text, re.I) and not _IF_THEN.match(text):
        ps = _paren_split(text[2:].strip())
        if ps:
            return ps[1]
    return text


# clauses whose list items name variables without accessing them
SHARING_CLAUSES = ("shared", "private", "firstprivate", "lastprivate",
                   "reduction", "in_reduction", "task_reduction", "depend",
                   "default", "allocate")


def _refs(nodes: list[Node], sharing: bool = True) -> set[str]:
    """Data references (``F.designators``) in a list of nodes (statements
    and the clause arguments of nested directives; without the list items
    of data-sharing and depend clauses unless `sharing`)."""
    out: set[str] = set()
    for n in nodes:
        if n.stmt is not None:
            if n.kind in ("dir", "loopdir", "standalone", "atomic"):
                for c in (n.dir.clauses if n.dir else []):
                    if sharing or c.name not in SHARING_CLAUSES:
                        out |= set(F.designators(c.arg or ""))
            else:
                out |= set(F.designators(n.stmt.text))
        if n.inner is not None:
            out |= _refs([n.inner], sharing)
        out |= _refs(n.children, sharing)
    return out


def _assoc_loop_vars(node: Node) -> list[str]:
    """Iteration variables of the loops associated with a loop directive
    (collapse(k) takes k levels; a nested loop directive is not one)."""
    k = 1
    for c in node.dir.clauses:
        if c.name == "collapse":
            try:
                k = int((c.arg or "1").strip())
            except ValueError:
                k = 1
    out, cur = [], node
    for _ in range(k):
        loops = [c for c in cur.children if c.kind == "do"]
        if not loops:
            break
        out.append(loops[0].loop_var)
        cur = loops[0]
    return [v for v in out if v]


# --- multiplicity: code executed once per team or thread ---------

# leaves that share out the work of the innermost enclosing region of a
# kind among its teams or threads (a loop construct: the iterations; the
# others: their block runs once)
_SHARES = {"do": "parallel", "for": "parallel", "workshare": "parallel",
           "sections": "parallel", "single": "parallel",
           "masked": "parallel", "master": "parallel",
           "distribute": "teams", "workdistribute": "teams"}
_PRIVATE_CLAUSES = ("private", "firstprivate", "lastprivate", "linear")


def _redundant_region(ctx: list[Node]) -> tuple[int, str] | None:
    """(index in ctx, "teams" | "parallel") of the innermost enclosing
    teams or parallel region whose body the innermost statement runs once
    per team or thread: no worksharing construct (do, distribute, loop with
    its binding), single, masked, sections or once-only guard
    (``if (omp_get_team_num() == 0)`` / ``omp_get_thread_num()``) between
    the statement and the region; None when it runs once. Detection only:
    num_teams(1), num_threads(1) or if(.false.) on the region are not
    read."""
    pending: set[str] = set()
    for k in range(len(ctx) - 1, -1, -1):
        x = ctx[k]
        if x.kind in ("if", "ifstmt"):
            if x.guard == "thread":
                pending.add("parallel")
            elif x.guard == "team":
                pending.add("teams")
            continue
        if x.kind not in ("dir", "loopdir"):
            continue
        leaves = list(x.dir.leaves)
        for leaf in reversed(leaves):
            if leaf in ("teams", "parallel"):
                if leaf in pending or "nearest" in pending:
                    pending -= {leaf, "nearest"}
                else:
                    return k, leaf
            elif leaf in _SHARES and (x.kind == "loopdir" or
                                      leaf not in ("do", "for",
                                                   "distribute")):
                pending.add(_SHARES[leaf])
            elif leaf == "loop" and x.kind == "loopdir":
                bind = [c.arg.strip().lower() for c in x.dir.clause("bind")
                        if c.arg]
                if bind:
                    if bind[0] in ("teams", "parallel"):
                        pending.add(bind[0])
                elif "parallel" in leaves:
                    pending.add("parallel")
                elif "teams" in leaves:
                    pending.add("teams")
                else:
                    pending.add("nearest")
    return None


def _written(s: F.Stmt) -> str | None:
    """The variable an assignment statement writes (its root name)."""
    low = s.lower
    if low.startswith((CALL_MARK, END_CALL_MARK, "!else")):
        return None
    m = _assignment(s.text)
    if m is None:
        return None
    return re.split(r"[%(]", m[0], maxsplit=1)[0].strip().lower()


def _private_at(ctx: list[Node], start: int, var: str) -> bool:
    """Whether `var` has a copy per team or thread at or inside ctx[start]:
    the innermost data-sharing clause naming it there is private-like (a
    reduction copy is combined back, so it is not), or it is the iteration
    variable of a loop there."""
    for x in reversed(ctx[start:]):
        if x.kind == "do" and x.loop_var == var:
            return True
        if x.kind not in ("dir", "loopdir"):
            continue
        if x.kind == "loopdir" and var in _assoc_loop_vars(x):
            return True
        for c in x.dir.clauses:
            names = {(_item_name(i) or "").lower() for i in c.items()}
            if var not in names:
                continue
            if c.name in _PRIVATE_CLAUSES:
                return True
            if c.name in ("reduction", "in_reduction", "task_reduction"):
                return False
    return False


def _redundant_writes(nodes: list[Node], flags: set,
                      ctx: list[Node] | None = None,
                      out: list | None = None) -> list[str]:
    ctx = [] if ctx is None else ctx
    out = [] if out is None else out
    for n in nodes:
        if n.kind == "code":
            var = _written(n.stmt)
            if var is None or var in flags:
                continue
            r = _redundant_region(ctx)
            if r is None or _private_at(ctx, r[0], var):
                continue
            k, kind = r
            out.append(f"line {n.stmt.first + 1}: {var} is written once per "
                       f"{'team' if kind == 'teams' else 'thread'} (the "
                       f"{ctx[k].dir.base} region at line "
                       f"{ctx[k].stmt.first + 1}: no worksharing construct "
                       "or once-only guard around the write)")
        elif n.kind == "ifstmt":
            ctx.append(n)
            _redundant_writes([n.inner], flags, ctx, out)
            ctx.pop()
        elif n.kind in ("if", "do", "dir", "loopdir"):
            ctx.append(n)
            _redundant_writes(n.children, flags, ctx, out)
            ctx.pop()
        elif n.kind == "atomic":
            _redundant_writes(n.children, flags, ctx, out)
    return out


def redundant_execution(source: str, version: int = 52) -> list[str]:
    """Writes to shared or reduction storage that OpenMP execution runs
    once per team or thread and sequential elision runs once: elision does not apply and the rewrites that change the
    number of teams or threads (num_teams_*, thread_limit_32, if_false)
    change the result. The ran_on_host flag variables are left out (every
    instance writes the same value, and the flag is never compared).
    Raises F.SourceError when the source is not understood."""
    an, _, flags, _, tree = _analysed(source, version)
    return _redundant_writes(tree, set(flags))


class _Runner:
    """Walks the tree with one _Walk."""

    def __init__(self, an: _Analysis, w: _Walk, check_guards: bool = True,
                 snapshots: list | None = None):
        self.an, self.w = an, w
        self.check_guards = check_guards
        # presence snapshots for the probe: (where, physical line,
        # {variable: present}) with where "before" or "after"
        self.snapshots = snapshots

    def snap(self, where: str, line: int, extra: tuple = ()):
        if self.snapshots is None:
            return
        state = {v: c > 0 for v, c in self.w.ref.items()
                 if v not in self.w.flags}
        for v in extra:
            if v in self.w.decls and v not in self.w.flags:
                state.setdefault(v, self.w.ref.get(v, 0) > 0)
        self.snapshots.append((where, line, state))

    def nodes(self, nodes: list[Node]):
        for n in nodes:
            self.node(n)

    def node(self, n: Node):
        w = self.w
        if n.kind == "code":
            w.code(n.stmt)
        elif n.kind == "ifstmt":
            for v in F.designators(n.cond):
                if not v.startswith("omp_"):
                    w.read(v, n.stmt.first + 1)
            if n.guard and self.check_guards:
                self.check_guard(n)
            n.once = w.once_in_loop(n.cond)
            w.ctx.append(n)
            self.node(n.inner)
            w.ctx.pop()
        elif n.kind == "if":
            for v in F.designators(n.cond):
                if not v.startswith("omp_"):
                    w.read(v, n.stmt.first + 1)
            if n.guard and self.check_guards:
                self.check_guard(n)
            w.ctx.append(n)
            self.nodes(n.children)
            w.ctx.pop()
        elif n.kind == "do":
            line = n.stmt.first + 1
            for part in (n.lo, n.hi, n.step):
                for v in F.designators(part):
                    w.read(v, line)
            if n.loop_var:
                w.write(n.loop_var, True, line)
            w.ctx.append(n)
            self.nodes(n.children)
            w.ctx.pop()
        elif n.kind == "atomic":
            self.nodes(n.children)
        elif n.kind == "standalone":
            self.standalone(n)
        elif n.kind in ("dir", "loopdir"):
            self.construct(n)

    def check_guard(self, n: Node):
        """The guarded code must run exactly once (ELISION_RULE 2)."""
        dirs = [x for x in self.w.ctx if x.kind in ("dir", "loopdir") or
                (x.kind in ("if", "ifstmt") and x.guard)]
        line = n.stmt.first + 1
        if n.guard == "thread":
            for x in reversed(dirs):
                if x.kind in ("if", "ifstmt"):
                    continue
                lv = set(x.dir.leaves)
                if lv & LOOP_LEAVES:
                    raise _Violation(f"line {line}: thread guard inside a "
                                     "loop construct")
                if "parallel" in lv or "target" in lv:
                    break
            self._teams_guarded(dirs, line, "thread guard")
        else:
            inner = None
            for x in reversed(dirs):
                if x.kind in ("if", "ifstmt"):
                    continue
                lv = set(x.dir.leaves)
                if "teams" in lv:
                    inner = x
                    break
                if lv & (LOOP_LEAVES | {"parallel"}):
                    raise _Violation(f"line {line}: team guard inside a "
                                     "parallel or loop construct")
            if inner is None:
                raise _Violation(f"line {line}: team guard outside teams")

    def _teams_guarded(self, dirs, line, what):
        """Every enclosing teams region has a team guard inside it."""
        seen_guard = False
        for x in reversed(dirs):
            if x.kind in ("if", "ifstmt") and x.guard == "team":
                seen_guard = True
            elif x.kind in ("dir", "loopdir") and "teams" in x.dir.leaves:
                if not seen_guard:
                    raise _Violation(f"line {line}: {what} runs once per "
                                     "team")
                seen_guard = False

    def _map_items(self, d: F.Dir) -> list:
        """(path, map type, modifiers, subscripts per part) of the map
        clauses of `d`."""
        out = []
        for c in d.clause("map"):
            typ, mods, items = _map_parts(c)
            for it in items:
                r = _item_ref(it)
                if r is None:
                    raise _Violation(f"line {d.stmt.first + 1}: map list item "
                                     f"{it!r} not understood")
                out.append((r[0], typ, mods, r[1]))
        return out

    def _names(self, items: list) -> set:
        """Leaves of data-sharing list items (variables)."""
        out = set()
        for v in items:
            if self.w.skip(v):
                continue
            out |= set(self.w.expand(v))
        return out

    def standalone(self, n: Node):
        d, w = n.dir, self.w
        if d.base == "target enter data":
            w.map_enter(self._map_items(d))
            self.snap("after", n.stmt.last)
        elif d.base == "target exit data":
            w.map_exit(self._map_items(d))
            self.snap("after", n.stmt.last)
        elif d.base == "target update":
            for c in d.clauses:
                if c.name in ("to", "from"):
                    for it in c.items():
                        r = _item_ref(it)
                        if r is None:
                            raise _Violation(f"line {n.stmt.first + 1}: "
                                             f"update item {it!r}")
                        w.update(r[0], r[1], c.name == "to")

    def construct(self, n: Node):
        d, w = n.dir, self.w
        line = n.stmt.first + 1
        leaves = d.leaves
        own = tuple(w.root(p) for p, _, _, _ in self._map_items(d))
        if d.base == "target data":
            maps = self._map_items(d)
            self.snap("before", n.stmt.first, own)
            w.map_enter(maps)
            self.snap("after", n.stmt.last)
            w.ctx.append(n)
            self.nodes(n.children)
            w.ctx.pop()
            w.map_exit(maps)
            self.snap("after", n.end_stmt.last)
            return
        if d.base in ("single", "masked", "master") and self.check_guards:
            dirs = [x for x in w.ctx if x.kind in ("dir", "loopdir") or
                    (x.kind in ("if", "ifstmt") and x.guard)]
            self._teams_guarded(dirs, line, d.base)
        exits = None
        if "target" in leaves:
            self.snap("before", n.stmt.first, own)
            exits = self.target_entry(n)
        # data-sharing of the other leaves
        inner = _Frame({}, "construct")
        priv, fpriv, lpriv, reds = set(), set(), {}, set()
        is_target = "target" in leaves
        for c in d.clauses:
            items = [x for x in (_item_name(i) for i in c.items()) if x]
            if c.name == "private":
                priv |= set(items)
            elif c.name == "firstprivate" and (not is_target or len(leaves)
                                               > 1):
                fpriv |= set(items)
            elif c.name == "lastprivate":
                cond = "conditional" in c.modifiers()
                for v in items:
                    lpriv[v] = cond
            elif c.name in ("reduction", "in_reduction"):
                if c.name == "in_reduction" and is_target and \
                        len(leaves) == 1:
                    reds |= set(items)
                    continue
                reds |= set(items)
        if n.kind == "loopdir":
            priv |= set(_assoc_loop_vars(n))
        # implicit: variables private in an enclosing frame become
        # firstprivate in a task
        if "task" in leaves or "taskloop" in leaves:
            for v in _refs(n.children):
                if w.skip(v) or w.root(v) in w.absent:
                    continue
                for leaf in w.expand(v):
                    for f in reversed(w.frames):
                        if leaf in f.copies:
                            fpriv.add(leaf)
                            break
        priv, fpriv, reds = (self._names(priv), self._names(fpriv),
                             self._names(reds))
        lpriv = {leaf: cond for v, cond in lpriv.items()
                 for leaf in self._names([v])}
        for v in sorted(reds):
            # nested in a reduction region of the same item, the original
            # is the enclosing region's private copy (combined there)
            if not w._red_var(v) and w.check_reads:
                if w.seen(v) != w.elis[v]:
                    raise _Violation(f"line {line}: the original value of "
                                     f"reduction item {v} differs from "
                                     "sequential execution")
        for v in priv | set(lpriv) | fpriv | reds:
            if v in reds:
                inner.copies[v] = w.V.new()
            elif v in fpriv or lpriv.get(v):
                inner.copies[v] = w.seen(v)
            else:
                inner.copies[v] = w.V.new()        # undefined
        inner.reductions = frozenset(v for v in reds if v in inner.copies)
        w.frames.append(inner)
        w.ctx.append(n)
        self.nodes(n.children)
        w.ctx.pop()
        w.frames.pop()
        for v in lpriv:
            if v in inner.copies:
                w._set(v, inner.copies[v])
        for v in inner.reductions:
            w._set(v, w.elis[v])
        if exits is not None:
            self.target_exit(exits)
            self.snap("after", n.end_stmt.last)

    def target_entry(self, n: Node) -> tuple:
        """Maps and the firstprivate/private copies of a target construct
        (explicit, implied by the combined-construct rules, implicit);
        returns the map exits. A structure is mapped implicitly as a whole
        when no part of it appears in a clause (5.2 §5.8.1: a reference
        to a structure element is a reference to the structure; aggregate
        category); when parts of it are mapped, every referenced part must
        be (5.2 §13.8, a restriction on the program). A pointer referenced
        in the region must be a list item of a map clause of the construct
        (``_Walk._device_pointer``); an allocatable scalar must have an
        explicit clause (whether 5.2's scalar category holds it is not
        settled)."""
        d, w = n.dir, self.w
        line = n.stmt.first + 1
        maps = self._map_items(d)
        mapped_paths = [p for p, _, _, _ in maps]
        mapped = {p for p in mapped_paths if "%" not in p}
        fp, pv, inred = set(), set(), set()
        multi = len(d.leaves) > 1
        lp_items = set()
        shared_names = set()
        for c in d.clauses:
            items = [x for x in (_item_name(i) for i in c.items()) if x]
            if c.name == "firstprivate":
                fp |= set(items) - mapped
            elif c.name == "private" and not multi:
                pv |= set(items)
            elif c.name == "in_reduction":
                inred |= set(items)
            elif c.name in ("lastprivate", "reduction") and multi:
                lp_items |= set(items)
            elif c.name == "shared":
                shared_names |= set(items)
        for v in sorted(lp_items - mapped):
            maps.append((v, "tofrom", [], [None]))       # 5.2 §17.2
            mapped_paths.append(v)
        named = fp | pv | inred | lp_items
        if multi:
            # private on a combined construct goes to the innermost leaf;
            # the target region still references the variable
            for c in d.clause("private"):
                named |= {x for x in (_item_name(i) for i in c.items())
                          if x}
        explicit_roots = named | {w.root(p) for p in mapped_paths}
        dm: dict[str, str] = {}
        for c in d.clause("defaultmap"):
            beh = (c.arg or "").split(":")[0].strip().lower()
            cat = (c.arg or "").split(":")[1].strip().lower() if ":" in (
                c.arg or "") else "all"
            dm[cat] = beh
        refs = set(_refs(n.children, sharing=False))
        # variables named only in data-sharing clauses of nested
        # constructs: referenced (implicitly mapped) unless a part of them
        # is in a clause of this construct
        named_inside = {w.root(p) for p in _refs(n.children)} - \
            {w.root(p) for p in refs}
        for c in d.clauses:
            if c.name == "shared":
                named_inside |= {w.root(p) for p in
                                 F.designators(c.arg or "")}
            elif c.name not in SHARING_CLAUSES + ("map", "defaultmap",
                                                  "nowait"):
                refs |= set(F.designators(c.arg or ""))
        named_inside -= {w.root(p) for p in refs}
        implicit = {r for r in named_inside if r in w.decls and
                    not w.decls[r].parameter and not w.skip(r) and
                    r not in explicit_roots and r not in w.absent and
                    not w.decls[r].pointer}
        for p in sorted(refs):
            r = w.root(p)
            if r not in w.decls or w.decls[r].parameter or w.skip(p):
                continue
            if r in w.absent:
                raise _Violation(f"line {line}: absent optional dummy "
                                 f"argument {r} referenced in a target "
                                 "region")
            if w.is_ptr(p):
                continue            # checked where it is referenced
            if r in explicit_roots:
                if r in named or r in mapped or any(
                        p == q or p.startswith(q + "%")
                        for q in mapped_paths):
                    continue
                raise _Violation(f"line {line}: {p} is referenced but only "
                                 f"other parts of {r} are mapped (5.2 §13.8)")
            implicit.add(r)
        for v in sorted(implicit):
            var = w.decls[v]
            if var.pointer:
                raise _Violation(f"line {line}: pointer {v} is referenced "
                                 "without a map clause")
            struct = v in w.under
            if var.rank == 0 and var.allocatable:
                raise _Violation(f"line {line}: allocatable scalar {v} "
                                 "without an explicit data-sharing or map "
                                 "clause")
            if var.rank == 0 and not struct:
                cats = ["scalar", "all"]
            else:
                cats = ["aggregate", "all"] + (["allocatable"]
                                               if var.allocatable else [])
            behs = {dm[c] for c in cats if c in dm and dm[c] != "default"}
            if len(behs) > 1:
                raise _Violation(f"line {line}: defaultmap categories give "
                                 f"{v} different behaviours")
            beh = behs.pop() if behs else "default"
            if beh == "default":
                beh = "firstprivate" if cats[0] == "scalar" else "tofrom"
            if beh == "firstprivate":
                fp.add(v)
            elif beh == "none":
                raise _Violation(f"line {line}: defaultmap(none) and "
                                 f"{v} has no explicit data-sharing")
            else:
                maps.append((v, "alloc" if beh == "storage" else beh, [],
                             [None]))
        ptrs = {p for p in mapped_paths if w.is_ptr(p)}
        holders = {p: (p if "%" not in p else w.root(p)) for p in ptrs}
        ptr_before = {p: w.ptr_ref.get(p, 0) for p in ptrs}
        before = w.map_enter(maps)
        attached = set()
        for p in ptrs:
            tgt = w.root(w.canon(p))
            h = holders[p]
            new_ptr = ptr_before[p] == 0 if h == p else \
                before.get(h, w.ref.get(h, 0)) == 0
            if before.get(tgt, 0) == 0 or new_ptr:
                attached.add(p)
            w.ptr_ref[p] = w.ptr_ref.get(p, 0) + 1
        frame = _Frame({}, "target", attached=frozenset(attached))
        for v in self._names(fp):
            if v in w.dev and w.dev[v] != w.host[v] and w.check_reads:
                raise _Violation(f"line {line}: firstprivate {v} has "
                                 "host and device copies that differ")
            frame.copies[v] = w.host[v]
        for v in self._names(pv):
            frame.copies[v] = w.V.new()
        for v in self._names(inred):
            if w.host[v] != w.elis[v] and w.check_reads:
                raise _Violation(f"line {line}: in_reduction item {v}: "
                                 "the original differs from sequential")
            frame.copies[v] = w.V.new()
        frame.reductions = frozenset(self._names(inred) & set(frame.copies))
        w.frames.append(frame)
        return maps, frame, ptrs

    def target_exit(self, exits):
        w = self.w
        maps, frame, ptrs = exits
        # the target frame is below the construct frame, already popped
        w.frames.pop()
        for v in frame.reductions:
            w.host[v] = w.elis[v]
        w.map_exit(maps)
        for p in ptrs:
            w.ptr_ref[p] -= 1


def _analysed(source: str, version: int):
    """(analysis, exclusions, flags, devvars, tree), or SourceError."""
    an = _Analysis(source, version)
    why, flags, devvars = an.static_exclusions()
    tree = build_tree(an.body, 0, len(an.body), version)
    return an, why, flags, devvars, tree


def elision_applicability(source: str, version: int = 52) -> Applicability:
    """Whether sequential elision gives the OpenMP result of `source`
    (ELISION_RULE), with the reasons when it does not."""
    try:
        an, why, flags, devvars, tree = _analysed(source, version)
    except F.SourceError as e:
        return Applicability(False, [f"source not understood: {e}"])
    if why:
        return Applicability(False, why, frozenset(flags))
    red = _redundant_writes(tree, set(flags))
    if red:
        return Applicability(False, red, frozenset(flags))
    reasons = []
    for refcounts in (True, False):
        w = _Walk(an, flags, devvars, refcounts)
        try:
            _Runner(an, w).nodes(tree)
        except _Violation as e:
            label = "copy semantics" if refcounts else \
                "copies ignoring reference counts"
            reasons.append(f"{e} [{label}]")
        except F.SourceError as e:
            reasons.append(f"source not understood: {e}")
    return Applicability(not reasons, reasons, frozenset(flags))


# Exclusions that concern the device data environment (the precondition
# of the host-execution rewrite, offload.engine.transforms if_false, as well as
# of elision)
DATA_REASONS = ("module variables", "declare target variable",
                "present modifier", "iterator or mapper", "6.0 map modifier",
                "defaultmap(", "device(ancestor)", "device pointers",
                "device addresses", "requires directive", "declare mapper",
                "runtime routine omp_target", "runtime routine "
                "omp_get_mapped", "conditional compilation",
                "source not understood")


def copy_independent(source: str, version: int = 52) -> Applicability:
    """Whether the result of `source` is the same with separate host and
    device copies (reference counts or unconditional copies) as with one
    shared copy: the data-environment half of ELISION_RULE (rule 3), without
    the rules about runtime routines, guards and reduction order. The
    precondition of rewrites that move execution or data motion
    (offload.engine.transforms)."""
    try:
        an, why, flags, devvars, tree = _analysed(source, version)
    except F.SourceError as e:
        return Applicability(False, [f"source not understood: {e}"])
    why = [r for r in why if r.startswith(DATA_REASONS)]
    if why:
        return Applicability(False, why, frozenset(flags))
    reasons = []
    for refcounts in (True, False):
        w = _Walk(an, flags, devvars, refcounts)
        try:
            _Runner(an, w, check_guards=False).nodes(tree)
        except _Violation as e:
            reasons.append(f"{e} [{'copy semantics' if refcounts else 'copies ignoring reference counts'}]")
        except F.SourceError as e:
            reasons.append(f"source not understood: {e}")
    return Applicability(not reasons, reasons, frozenset(flags))


def presence_snapshots(source: str, version: int = 52) -> list[tuple]:
    """The presence of every mapped variable the reference-count rules fix
    (OpenMP 5.2 §5.8.3, §13.6-13.8) at the host points around each data
    construct and target construct: (where, physical line, {var: present})
    with where "before" (insert before that line) or "after". Raises
    SourceError for a source the model does not handle."""
    an, _, flags, devvars, tree = _analysed(source, version)
    snaps: list = []
    w = _Walk(an, flags, devvars, True, check_reads=False)
    _Runner(an, w, check_guards=False, snapshots=snaps).nodes(tree)
    return snaps


# --- running the elided program ---------------------------------------------------

GFORTRAN = shutil.which("gfortran") or "/usr/tce/bin/gfortran"
AMDFLANG = f"{AFAR_BIN}/amdflang"
# amdflang's runtime links libquadmath from the system GCC (the AFAR
# Fortran recipe passes the same -L)
AMDFLANG_LINK = "-L/usr/lib/gcc/x86_64-redhat-linux/8"
ELISION_COMPILERS = ("gfortran", "amdflang")
ELISION_TIMEOUT_S = 60

ELISION_OMP_LIB = """\
! Sequential omp_lib for sequential elision (offload.engine.expected): the
! values of the runtime routines for one initial thread on the host with
! no devices (OpenMP 5.2 §18: the initial device is the host; a team of
! one thread, one team; omp_get_num_devices() = 0 and the initial device
! number equals it). Built without -fopenmp; the programs' directives are
! comments.
module omp_lib
  use, intrinsic :: iso_c_binding, only: c_ptr, c_int
  implicit none
  integer, parameter :: omp_allocator_handle_kind = 8
  integer, parameter :: omp_memspace_handle_kind = 8
  integer, parameter :: omp_alloctrait_key_kind = 8
  integer, parameter :: omp_alloctrait_val_kind = 8
  integer, parameter :: omp_depend_kind = 16
  integer, parameter :: omp_impex_kind = 4
  type omp_alloctrait
    integer(omp_alloctrait_key_kind) :: key
    integer(omp_alloctrait_val_kind) :: value
  end type omp_alloctrait
  integer(omp_alloctrait_key_kind), parameter :: omp_atk_alignment = 3
  integer(omp_allocator_handle_kind), parameter :: omp_default_mem_alloc = 1
  integer(omp_memspace_handle_kind), parameter :: omp_default_mem_space = 0
  integer(omp_impex_kind), parameter :: omp_not_impex = 0, omp_import = 1, &
    omp_export = 2, omp_impex = 3
contains
  logical function omp_is_initial_device()
    omp_is_initial_device = .true.
  end function omp_is_initial_device
  integer function omp_get_team_num()
    omp_get_team_num = 0
  end function omp_get_team_num
  integer function omp_get_thread_num()
    omp_get_thread_num = 0
  end function omp_get_thread_num
  integer function omp_get_num_threads()
    omp_get_num_threads = 1
  end function omp_get_num_threads
  integer function omp_get_num_teams()
    omp_get_num_teams = 1
  end function omp_get_num_teams
  integer function omp_get_num_devices()
    omp_get_num_devices = 0
  end function omp_get_num_devices
  integer function omp_get_default_device()
    omp_get_default_device = 0
  end function omp_get_default_device
  integer function omp_get_device_num()
    omp_get_device_num = 0
  end function omp_get_device_num
end module omp_lib
"""


_ELISION_LIBS: dict = {}


def _elision_lib(compiler: str) -> tuple[str, str]:
    """(module dir, object) of ELISION_OMP_LIB built by `compiler`; rebuilt if its directory was removed."""
    have = _ELISION_LIBS.get(compiler)
    if have and Path(have[1]).is_file():
        return have
    _ELISION_LIBS[compiler] = _build_elision_lib(compiler)
    return _ELISION_LIBS[compiler]


def _build_elision_lib(compiler: str) -> tuple[str, str]:
    d = tempfile.mkdtemp(prefix=f"elision_{compiler}_")
    atexit.register(shutil.rmtree, d, True)
    src = Path(d) / "omp_lib_elision.f90"
    src.write_text(ELISION_OMP_LIB)
    obj = str(Path(d) / "omp_lib_elision.o")
    if compiler == "gfortran":
        cmd = [GFORTRAN, "-c", str(src), "-o", obj, f"-J{d}"]
    else:
        cmd = [AMDFLANG, "-c", str(src), "-o", obj, "-module-dir", d]
    subprocess.run(cmd, cwd=d, check=True, capture_output=True, timeout=120)
    return d, obj


def run_elided(source: str, compiler: str, extra: tuple = (),
               env: dict | None = None, value=None
               ) -> tuple[str | None, str]:
    """(value or None, note) of the source built by `compiler` without
    OpenMP against ELISION_OMP_LIB, run on the host. `extra`: more
    compiler flags (fuzz_min's range guard: -ftrapv); `env`: more
    environment variables of the run (the fuzz definedness check:
    MALLOC_PERTURB_); `value`: how the output gives the value (default
    ``value_of``: one RESULT line; passes its own for a finding's
    free-form output)."""
    mdir, obj = _elision_lib(compiler)
    with tempfile.TemporaryDirectory(prefix="elided_") as d:
        src = Path(d) / "p.f90"
        src.write_text(source)
        exe = str(Path(d) / "p.out")
        if compiler == "gfortran":
            cmd = [GFORTRAN, "-O0", *extra, f"-I{mdir}", "-J", d, str(src),
                   obj, "-o", exe]
        else:
            cmd = [AMDFLANG, "-O0", *extra, "-I", mdir, "-module-dir", d,
                   str(src), obj, AMDFLANG_LINK, "-o", exe]
        b = subprocess.run(cmd, cwd=d, capture_output=True, text=True,
                           timeout=300)
        if b.returncode != 0:
            err = [ln for ln in (b.stderr + b.stdout).splitlines()
                   if "rror" in ln]
            return None, f"{compiler} build failed: " + (
                err[0] if err else f"rc={b.returncode}")[:200]
        try:
            # no core dumps, set by the shell: a preexec_fn runs Python in
            # the forked child, which can deadlock in a threaded parent
            # (it hung the test suite)
            r = subprocess.run(["bash", "-c", 'ulimit -c 0; exec "$0"', exe],
                               cwd=d, capture_output=True, text=True,
                               timeout=ELISION_TIMEOUT_S,
                               env={"PATH": "/usr/bin:/bin", **(env or {})})
        except subprocess.TimeoutExpired:
            return None, f"{compiler} run timed out"
        if r.returncode != 0:
            return None, f"{compiler} run failed: rc={r.returncode}"
        v = (value or value_of)(r.stdout)
        if v is None:
            return None, f"{compiler}: no single RESULT line"
        return v, ""


def elided_source(source: str) -> str:
    """The program sequential elision builds, as a reader sees it.
    run_elided compiles `source` unchanged without OpenMP, where every
    line whose first non-blank characters are the sentinel ``!$``
    (directives, their continuations, conditional compilation) is a
    comment; this leaves those lines out and keeps every other line as
    it is. The build also links ELISION_OMP_LIB."""
    return "".join(ln for ln in source.splitlines(keepends=True)
                   if not ln.lstrip().startswith("!$"))


def elision_evidence(source: str, version: int = 52,
                     compilers=ELISION_COMPILERS,
                     applicability: Applicability | None = None,
                     value=None) -> Evidence:
    """Sequential elision of `source`: inapplicable with the reasons, or
    the value every compiler prints (conflict if they differ; no value
    unless every build printed one)."""
    ap = applicability or elision_applicability(source, version)
    if not ap.ok:
        return Evidence("elision", "inapplicable", detail=ap.why)
    obs, notes = [], []
    for c in compilers:
        v, note = run_elided(source, c) if value is None else \
            run_elided(source, c, value=value)
        obs.append((c, v))
        if note:
            notes.append(note)
    vals = sorted({v for _, v in obs if v is not None})
    detail = "; ".join(notes)
    if len(vals) == 1 and all(v is not None for _, v in obs):
        return Evidence("elision", "value", vals[0], detail, tuple(obs))
    if len(vals) > 1:
        return Evidence("elision", "conflict", None,
                        "the elided builds disagree" +
                        (f"; {detail}" if detail else ""), tuple(obs))
    return Evidence("elision", "no_value", None, detail or "no value",
                    tuple(obs))


# --- legality of rewritten programs ----------------------------------------------

def variant_legality(source: str, version: int, kind: str) -> str | None:
    """None if a rewritten program is legal, else the first failure. A
    fuzz program (kind "fuzz") gets the fuzzer's three checks
    (offload.engine.fuzz.check: rules, gfortran, AFAR flang's frontend); a
    catalog program the rules at its version and gfortran at its std
    level (the generator's own checks of its programs)."""
    from offload.engine import fuzz
    if kind == "fuzz":
        # a rewrite may run on the host (if(.false.)): it is a reference,
        # not an offload test, so the device-offload scope check
        # does not apply
        res = fuzz.check(source, scope=False)
        return None if res.ok else f"{res.stage}: {res.detail}"[:300]
    from offload.engine.rules import ProgramError, parse_program, violations
    try:
        bad = violations(parse_program(source, version), version)
    except ProgramError as e:
        return f"rules: {e}"[:300]
    if bad:
        return f"rules: {', '.join(bad)}"
    std = re.search(r"^! std: (\S+)$", source, re.M)
    err = _gfortran_check(source, std.group(1) if std else "f2008")
    return f"gfortran: {err}"[:300] if err else None


def _gfortran_check(source: str, std: str) -> str | None:
    from offload.engine.fuzz import _stub_dir
    with tempfile.TemporaryDirectory(prefix="expected_gf_") as d:
        (Path(d) / "t.f90").write_text(source)
        r = subprocess.run([GFORTRAN, f"-std={std}", "-fsyntax-only",
                            f"-I{_stub_dir()}", "-J", d, "t.f90"], cwd=d,
                           capture_output=True, text=True, timeout=120)
    if r.returncode == 0:
        return None
    lines = [ln for ln in r.stderr.splitlines() if "Error" in ln]
    return lines[0] if lines else r.stderr.strip()[:200]


# --- running a program or variant on a toolchain ------------------------------------

RUN_TIMEOUT_S = 120
COMPILE_TIMEOUT_S = 600


@dataclass
class ToolRun:
    """One compile and run of a (rewritten) program on a toolchain under
    HSA_XNACK=`xnack` and OMP_TARGET_OFFLOAD=mandatory. `value`: the
    compared value, "error_termination" (the toolchain's runtime error
    message, offload.engine.harness.ERROR_TERMINATION), or None (`why`).
    `probe`: whether every PROBE line said pass (None: no PROBE line)."""
    toolchain: str
    variant: str
    value: str | None
    ran_on_host: int | None = None
    probe: bool | None = None
    why: str = ""
    xnack: int = 1

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


def terminated(toolchain: str, source: str, text: str) -> bool:
    """Whether a run's output (`text`) shows the negative probe's error
    termination on `toolchain`: the harness's check
    (``harness.probe_termination``: the toolchain family's message and, for
    CCE, a present-table miss at a directive of `source` that carries the
    present modifier), so the matrix and this module read a probe run
    alike."""
    from offload.engine import harness
    return harness.probe_termination(toolchain, "f90", source,
                                     text) is not None


def run_on(toolchain: str, source: str, version: int, kind: str,
           variant: str = "original", xnack: int = 1,
           timeout_s: int = RUN_TIMEOUT_S) -> ToolRun:
    """Compile `source` with the toolchain's recipe (a catalog program
    with the matrix's version flags, a fuzz program as the campaign) and
    run it once."""
    from offload.engine import harness
    from offload.engine.run_matrix import for_version
    from offload.engine.toolchains import TOOLCHAINS
    from offload.engine.transforms import PROBE_LINE
    tc = TOOLCHAINS[toolchain]
    if kind != "fuzz":
        tc = for_version(tc, version)
    tc = tc.for_mode(xnack)  # NVHPC builds per memory mode
    with tempfile.TemporaryDirectory(prefix="expected_run_") as d:
        tmp = Path(d)
        src, exe = tmp / "p.f90", tmp / "p.out"
        src.write_text(source)
        b = harness._execute(harness.compile_script(tc, str(src), str(exe),
                                                    "-O2", str(tmp)),
                             tmp, COMPILE_TIMEOUT_S, merge=True)
        if b.timed_out:
            return ToolRun(toolchain, variant, None, why="compile timeout",
                           xnack=xnack)
        if b.rc != 0 or not exe.is_file():
            found = harness.classify_message(tc.name, b.stdout,
                                             harness.CATEGORY_ORDER[:-1],
                                             "c" if tc.lang == "c" else
                                             "f90")
            why = f"{found[0]}: {found[1]}" if found else \
                f"compile failed: rc={b.rc}"
            return ToolRun(toolchain, variant, None,
                           why=why.replace(str(tmp), "<tmpdir>")[:300],
                           xnack=xnack)
        ex = harness._execute(harness.run_script(tc, str(exe), xnack, True,
                                                 str(tmp)), tmp, timeout_s)
    out = ex.stdout + "\n" + ex.stderr
    probes = PROBE_LINE.findall(ex.stdout)
    probe = None if not probes else all(p == "pass" for p in probes)
    if ex.timed_out:
        return ToolRun(toolchain, variant, None, probe=probe, why="timeout",
                       xnack=xnack)
    v = value_of(ex.stdout) if ex.rc == 0 else None
    host = None
    m = re.search(r"ran_on_host=([01])", ex.stdout)
    if m:
        host = int(m.group(1))
    if v is not None:
        return ToolRun(toolchain, variant, v, host, probe, xnack=xnack)
    line = harness.probe_termination(toolchain, "f90", source, out)
    if line is not None:
        return ToolRun(toolchain, variant, "error_termination", host,
                       probe, why=f"error termination ({line.strip()[:60]})",
                       xnack=xnack)
    return ToolRun(toolchain, variant, None, host, probe,
                   why=f"run failed: rc={ex.rc}", xnack=xnack)


# --- one program's evidence ---------------------------------------------------------

def assess(model: Evidence, elision: Evidence, runs: list[ToolRun],
           probe_na: str | None = None,
           model_partners: tuple = MODEL_PARTNERS,
           derivation: Evidence | None = None
           ) -> tuple[list[Evidence], Verdict]:
    """The evidence of a program from its model value, its elision and
    its runs (variant "original", the rewrites, "probe"), and the
    verdict. Metamorphic uses the original and the rewrites; consensus
    the original; probe the probe runs (state verified: every PROBE line
    passed, and the run reached the device or ended in error
    termination, by a toolchain that does not violate the metamorphic
    relation). Every run must be in one memory mode (HSA_XNACK): a
    copy-mode run is no rewrite of a zero-copy run."""
    modes = {r.xnack for r in runs}
    if len(modes) > 1:
        raise ValueError(f"runs of more than one memory mode (HSA_XNACK "
                         f"{sorted(modes)}): assess each mode separately")
    meta = [(r.toolchain, r.variant, r.value) for r in runs
            if r.variant != "probe"]
    has_variant = any(r.variant not in ("original", "probe") for r in runs)
    ev = [model, elision]
    ev.append(metamorphic_evidence(meta) if has_variant else
              Evidence("metamorphic", "inapplicable",
                       detail="no rewrite applies"))
    # a toolchain the rewrites show inconsistent (it is wrong on at least
    # one of them) is no probe witness, however its state checks went
    unstable = {tc for tc in {r.toolchain for r in runs}
                if len({r.value for r in runs if r.toolchain == tc and
                        r.variant != "probe" and r.value is not None}) > 1}
    pr = [(r.toolchain,
           bool(r.probe) and r.toolchain not in unstable and
           (r.ran_on_host == 0 or r.value == "error_termination"),
           r.value) for r in runs if r.variant == "probe"]
    ev.append(probe_evidence(pr, probe_na if not pr else None))
    ev.append(consensus_evidence([(r.toolchain, r.value) for r in runs
                                  if r.variant == "original"]))
    if derivation is not None:
        ev.append(derivation)
    return ev, decide(ev, model_partners)
