"""The confirmer's data types and the mapping of every stored result format
to one set of outcome classes (docs/tooling/confirm.md, "Case" and "Evidence")."""
from __future__ import annotations

import dataclasses
import hashlib
import re
from dataclasses import dataclass, field

OUTCOMES = ("rejected", "ice", "crash", "run_error", "timeout",
            "wrong_answer", "fell_back_to_host", "accepted_ignored",
            "harness_error", "correct_on_device", "unobservable")
PASSING = ("correct_on_device", "unobservable")
COMPILE_FAILURES = ("rejected", "ice")
RUN_FAILURES = ("crash", "run_error", "timeout", "wrong_answer",
                "fell_back_to_host")


def outcome_of_result(outcome: str, reason: str) -> str:
    """The class of a harness row (offload.engine.harness.Result: matrix and
    acc_matrix files)."""
    reason = reason or ""
    if outcome == "rejected":
        return "ice" if reason.startswith("ice:") else "rejected"
    if outcome == "wrong_answer":
        head = reason.split(";")[0]
        if head.startswith("timeout") or head.startswith("compile_timeout"):
            return "timeout"
        if head.startswith("crash:"):
            return "crash"
        if head.startswith(("exit_status", "no_result_line",
                            "multiple_result_lines", "mandatory_failed")):
            return "run_error"
        return "wrong_answer"
    if outcome == "harness_error" and reason.startswith("compile_timeout"):
        return "timeout"
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown outcome {outcome!r}")
    return outcome


def outcome_of_baseline(row: dict) -> str:
    """The class of an omp_vv baseline row (offload.engine.baseline: exit code
    only)."""
    st, stage, reason = row["status"], row.get("stage"), row.get("reason", "")
    if st == "pass":
        return "correct_on_device"
    if st == "harness_error":
        return "harness_error"
    if stage == "compile":
        if reason.startswith("ice"):
            return "ice"
        if reason.startswith("compile_failed"):
            # The harness found no known message; the output
            # still tells a compiler failure from the environment's
            err = row.get("stderr") or ""
            if re.search(r"Segmentation fault|PLEASE submit a bug report|"
                         r"INTERNAL COMPILER ERROR|verification of lowering"
                         r"|failed to create the LLVM module", err):
                return "ice"
            if re.search(r"undefined (hidden )?symbol|undefined reference",
                         err):
                return "rejected"
            return "harness_error"
        if "timeout" in reason:
            return "timeout"
        return "rejected"
    if reason.startswith("crash"):
        return "crash"
    if reason.startswith("timeout"):
        return "timeout"
    return "run_error"


FUZZ_CLASS = {"agree": "correct_on_device", "compile_reject": "rejected",
              "ice": "ice", "wrong_code": "wrong_answer",
              "host_fallback": "fell_back_to_host", "run_error": "run_error",
              "harness_error": "harness_error"}


def outcome_of_fuzz(cls: str, reason: str = "") -> str:
    """The class of a fuzz campaign's per-toolchain result."""
    if cls == "timeout":
        return "timeout"
    if cls == "run_error" and (reason or "").startswith("crash"):
        return "crash"
    return FUZZ_CLASS[cls]


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@dataclass(frozen=True)
class ProgramRef:
    """A program: ``kind`` catalog (``ident`` = program id), ompvv
    (``ident`` = corpus path), fuzz (``ident`` = "<run>:<seed>"), file
    (``ident`` = path or label; ``text`` holds the files)."""
    kind: str
    ident: str
    lang: str = "f90"
    version: int = 0
    model: str = "omp"
    legal_claim: bool = True
    needs: tuple = ()
    evidence: str = "construct"
    text: str = ""          # the program text (a set: FILE marks)
    expected: str = ""      # a stated expected value (fuzz model, finding)
    # Build flags the reproducer needs (its "build flags:" header
    # line, e.g. "-O2 -flto"); the runners add them to every build
    flags: str = ""

    @property
    def sha(self) -> str:
        return sha256(self.text) if self.text else ""

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["needs"] = list(self.needs)
        d["sha256"] = self.sha
        d.pop("text")
        if not self.flags:
            d.pop("flags")      # older rows had none
        return d


@dataclass(frozen=True)
class Case:
    program: ProgramRef
    toolchain: str
    machine: str
    arch: str
    mode: str
    outcome: str
    reason: str = ""
    value: str | None = None
    ran_on_host: int | None = None
    flaky: bool = False
    repeats: int = 1
    opt: str = "-O2"
    source: dict = field(default_factory=dict)

    @property
    def case_id(self) -> str:
        ident = re.sub(r"[^A-Za-z0-9_.:-]", "_", self.program.ident)
        return (f"{self.program.kind}:{ident}:{self.toolchain}:"
                f"{self.arch}:{self.mode}")

    @property
    def failing(self) -> bool:
        return self.outcome not in PASSING

    def to_dict(self) -> dict:
        d = {k: v for k, v in dataclasses.asdict(self).items()
             if k != "program"}
        d["program"] = self.program.to_dict()
        d["case_id"] = self.case_id
        return d


@dataclass(frozen=True)
class Provenance:
    command: str = ""
    host: str = ""
    date: str = ""
    modules: tuple = ()
    origin: str = ""   # "run", or "<file>:<line>" of a stored row

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["modules"] = list(self.modules)
        return d


@dataclass(frozen=True)
class Run:
    """One execution (or one stored row) of a program on a toolchain."""
    outcome: str
    value: str | None = None
    ran_on_host: int | None = None
    reason: str = ""
    stdout_tail: str = ""


@dataclass(frozen=True)
class Evidence:
    """What one collector found for one cell (docs/tooling/confirm.md). `status`:
    value | no_value | inapplicable | not_applicable."""
    collector: str
    toolchain: str = ""
    arch: str = ""
    mode: str = ""
    opt: str = "-O2"
    offload: str = "mandatory"
    variant: str = "original"
    sha: str = ""
    runs: tuple = ()
    value: str | None = None
    status: str = "value"
    detail: str = ""
    provenance: Provenance = Provenance()

    def __post_init__(self):
        if self.status not in ("value", "no_value", "inapplicable",
                               "not_applicable"):
            raise ValueError(f"unknown evidence status {self.status!r}")

    @property
    def key(self) -> tuple:
        return (self.collector, self.sha, self.toolchain, self.arch,
                self.mode, self.opt, self.offload, self.variant)

    @property
    def outcomes(self) -> tuple:
        return tuple(r.outcome for r in self.runs)

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["runs"] = [dataclasses.asdict(r) for r in self.runs]
        d["provenance"] = self.provenance.to_dict()
        return d

    @staticmethod
    def from_dict(d: dict) -> "Evidence":
        d = dict(d)
        d["runs"] = tuple(Run(**r) for r in d.get("runs", ()))
        p = dict(d.get("provenance") or {})
        p["modules"] = tuple(p.get("modules", ()))
        d["provenance"] = Provenance(**p)
        return Evidence(**d)


VALUE_LINE = re.compile(r"^RESULT (?:ran_on_host=([01]) check=(pass|fail)|"
                        r"checksum=(-?\d+) ran_on_host=([01]))\s*$", re.M)


def value_of(stdout: str) -> tuple[str | None, int | None]:
    """(value, ran_on_host) of a program's output: ``check=pass|fail`` or
    ``checksum=<n>`` from its single RESULT line; else the output with
    whitespace collapsed (a finding's free-form output); (None, None) for
    no output."""
    found = VALUE_LINE.findall(stdout or "")
    if len(found) == 1:
        h, chk, cs, h2 = found[0]
        if chk:
            return f"check={chk}", int(h)
        return f"checksum={cs}", int(h2)
    text = " ".join((stdout or "").split())
    return (text or None), None
