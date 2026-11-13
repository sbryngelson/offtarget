"""A generic reducer for failing device-offload programs (tools/reduce.py).

A failing program (C or Fortran, OpenMP or OpenACC, one file or a
``!@file``/``//@file`` bundle) shrinks by delta debugging. An accepted
candidate must pass the legality witness (``offload.engine.prerun.rules_witness``,
never the compiler under test), fail on every target with the recorded
``Signature`` (outcome class and normalized message) and still compile.
Candidates come from registered steps (``STEPS``, added with ``step``) at four
levels: statements and blocks, clauses, expressions, cleanup. A fuzz-format
Fortran program uses the steps of ``offload.engine.fuzz_min``. ``greedy`` takes
the first candidate that keeps the failure and restarts the level. A
``Judge`` caches by text and logs rows, a ``Budget`` limits the work and a
``checkpoint`` resumes a stopped run. ``controls`` writes one-change edits
of the result that pass on every target. ``FuzzContract`` rewrites a fuzz
checksum line into a ``check=pass|fail`` line."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import random
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from offload.engine import finding_rows as R
from offload.engine import gate as G
from offload.engine.site import matrix as M

from offload.engine.root import ROOT  # noqa: E402


class NoFailure(Exception):
    """The program does not fail (with the wanted signature) on the target."""


class BudgetExhausted(Exception):
    """The candidate or time budget is spent."""


class RunnerUnavailable(Exception):
    """This node cannot run the target (no GPU, another machine)."""


class NoReference(Exception):
    """A wrong-answer reduction of a self-checking program needs an output
    oracle (``--reference elision`` or ``host:TOOLCHAIN``)."""


class CheckpointMismatch(Exception):
    """The checkpoint was written for other targets, levels, witness or
    signature."""


# --- targets and signatures ---------------------------------------------------------

@dataclass(frozen=True)
class Target:
    """A toolchain, its memory-mode row key (HSA_XNACK on AMD; 0 copy and
    2 managed on wingtip, as the campaigns record them) and the
    optimisation level."""
    toolchain: str
    mode: int
    opt: str = "-O2"

    @property
    def label(self) -> str:
        return f"{self.toolchain}/{self.mode}"

    @staticmethod
    def parse(text: str, opt: str = "-O2") -> "Target":
        """``nvhpc/0``; ``nvhpc`` alone takes the toolchain's first mode."""
        name, _, mode = text.partition("/")
        if mode == "":
            from offload.engine.toolchains import TOOLCHAINS
            if name not in TOOLCHAINS:
                raise ValueError(f"unknown toolchain {name!r}")
            mode = str(TOOLCHAINS[name].xnack_modes[0])
        return Target(name, int(mode), opt)


@dataclass(frozen=True)
class Signature:
    cls: str    # the gate's outcome class: ice, rejected, crash, run_error, wrong_answer, timeout, ...
    key: str    # the site matrix's normalized line (or the gate's failure key)

    def __str__(self) -> str:
        return f"{self.cls}: {self.key}" if self.key else self.cls


_IGNORED_RUN = re.compile(r"; run: (\w+): ?(.*)$", re.S)


def run_class(row: dict) -> str:
    """The gate's outcome class of a row, except that an ``accepted_ignored``
    row (the compiler ignored a clause with a note and the program ran) is
    classed by its run (the ``run: <outcome>: <reason>`` tail of the
    reason): the note is not the failure, the run's result is."""
    d = R.normalize_row(dict(row))
    cls = G.outcome_class(d)
    if cls == "accepted_ignored":
        m = _IGNORED_RUN.search(str(d.get("reason") or ""))
        if m:
            from offload.engine.confirm.model import outcome_of_result
            try:
                return outcome_of_result(m.group(1), m.group(2))
            except ValueError:
                return cls
    return cls


def signature(row: dict) -> Signature:
    """The signature of a recorded row of any format (a harness row, a gate
    rerun, a fuzz or stress result): the gate's class (``run_class``) and,
    for a compile failure or a wrong answer, the normalized line
    tools/repo/check_findings.py compares (offload.engine.site.matrix.signature); a
    crash keeps its signal, a run error its exit kind, a timeout its
    stage."""
    d = R.normalize_row(dict(row))
    cls = run_class(d)
    if cls in ("crash", "run_error", "timeout") and G.outcome_class(d) == "accepted_ignored":
        m = _IGNORED_RUN.search(str(d.get("reason") or ""))
        d = dict(d, outcome="wrong_answer", reason=m.group(2) if m else d.get("reason"))
    if cls in ("rejected", "ice", "accepted_ignored", "wrong_answer"):
        return Signature(cls, M.signature(R._stage_text(d, cls))[1])
    if cls in ("crash", "run_error"):
        # finer than the gate's key (the exit kind or signal alone): the normalized first error
        # line of the run, so another run-time failure of the same kind is another failure
        line = _run_line(d)
        return Signature(cls, G.failure_key(d, cls) + (f" | {line}" if line else ""))
    if cls == "timeout":
        return Signature(cls, G.failure_key(d, cls))
    return Signature(cls, "")


_RUN_MARK = re.compile(r"^--- run\b.*$", re.M)
_RUN_DIAG = re.compile(r"error|fatal|fault|abort|illegal|exception|signal|terminat|assert", re.I)


def _run_line(d: dict) -> str:
    """The normalized first error line of a run's output (the text after the
    harness's ``--- run`` marker, else the recorded output), '' when none."""
    text = "\n".join(str(d.get(k) or "") for k in ("stderr", "output", "stdout"))
    m = _RUN_MARK.search(text)
    if m:
        text = text[m.end():]
    lines = [x.strip() for x in text.splitlines() if x.strip() and not x.startswith("---")
             and not x.strip().startswith("RESULT")]
    pick = next((x for x in lines if _RUN_DIAG.search(x)), lines[0] if lines else "")
    return M._norm(pick)


def is_failure(row: dict) -> bool:
    return G.is_failure(run_class(row))


def failures_of_record(rec: dict, mode: int) -> list[tuple[Target, Signature]]:
    """(target, signature) of each failing toolchain of a fuzz campaign
    record (results/fuzz/<run>/programs.jsonl: ``results`` per toolchain).
    A wrong checksum is the ``check=fail`` signature the reduced,
    self-checking program will show (FuzzContract)."""
    out = []
    for tc, r in (rec.get("results") or {}).items():
        d = dict(r, toolchain=tc, program_id=str(rec.get("seed", "")), xnack=mode)
        cls = G.outcome_class(d)
        if not G.is_failure(cls):
            continue
        if cls == "wrong_answer":
            host = r.get("ran_on_host") or 0
            sig = Signature(cls, f"result ran_on_host={host} check=fail")
        else:
            sig = signature(d)
        out.append((Target(tc, mode), sig))
    return out


# --- candidates and the step table ------------------------------------------------------

@dataclass(frozen=True)
class Candidate:
    what: str
    text: str


@dataclass(frozen=True)
class Step:
    name: str
    level: int
    langs: tuple
    fn: Callable
    controls: bool = False
    only: Callable | None = None       # applies(text, lang); None: every program

    def applies(self, text: str, lang: str) -> bool:
        return lang in self.langs and (self.only is None or self.only(text, lang))


STEPS: list[Step] = []
LEVELS = (1, 2, 3, 4)


def step(name: str, level: int, langs=("f90", "c"), controls: bool = False, only=None):
    """Register a candidate generator ``fn(text, lang) -> Iterable[Candidate]``
    at a level (1 blocks and statements, 2 clauses, 3 expressions, 4
    cleanup). ``controls``: its edits are one-change controls too.
    ``only``: a predicate on (text, lang) that selects the programs it
    applies to (the fuzz-format steps)."""
    def deco(fn):
        unregister(name)
        STEPS.append(Step(name, level, tuple(langs), fn, controls, only))
        return fn
    return deco


def unregister(name: str) -> None:
    STEPS[:] = [s for s in STEPS if s.name != name]


def is_fuzz_format(text: str, lang: str = "f90") -> bool:
    return lang == "f90" and "! fuzz: kernels" in text and "! fuzz: checksum" in text


def not_fuzz_format(text: str, lang: str) -> bool:
    return not is_fuzz_format(text, lang)


def steps_for(lang: str, text: str = "", levels=LEVELS) -> list[Step]:
    """The steps that apply to a program, by level then registration order."""
    out = [s for s in STEPS if s.level in levels and s.applies(text, lang)]
    return sorted(out, key=lambda s: (s.level, STEPS.index(s)))


def candidates(text: str, lang: str, levels=LEVELS, steps=None) -> list[Candidate]:
    """Every candidate of the steps at these levels, distinct and different
    from the program, in step order."""
    out, seen = [], {text}
    for s in steps if steps is not None else steps_for(lang, text, levels):
        for c in s.fn(text, lang):
            if c.text not in seen:
                seen.add(c.text)
                out.append(c)
    return out


# --- directives: a small model shared by the steps --------------------------------------

_F_DIR = re.compile(r"^(\s*)!\$(omp|acc)&?\s+(.*?)\s*$", re.I)
_C_DIR = re.compile(r"^(\s*)#\s*pragma\s+(omp|acc)\s+(.*?)\s*$", re.I)
DIRECTIVE_WORDS = {
    "target", "teams", "distribute", "parallel", "do", "for", "simd", "loop", "sections", "section",
    "single", "masked", "master", "task", "taskloop", "taskgroup", "taskwait", "taskyield", "barrier",
    "critical", "atomic", "flush", "ordered", "workshare", "data", "enter", "exit", "update", "declare",
    "mapper", "metadirective", "dispatch", "interop", "scan", "tile", "unroll", "nothing", "error",
    "requires", "assume", "assumes", "allocate", "allocators", "cancel", "cancellation", "point",
    "kernels", "serial", "host_data", "wait", "init", "shutdown", "set", "routine", "cache", "end",
    "variant", "reduction", "simd", "read", "write", "capture", "compare"}
# words that are directive names only when first (atomic update/read/write/capture are clauses of atomic)
_ATOMIC_CLAUSES = {"update", "read", "write", "capture", "compare"}
BLOCK_LAST = {"target", "teams", "parallel", "task", "masked", "master", "single", "critical",
              "taskgroup", "data", "kernels", "serial", "host_data", "ordered", "sections", "workshare"}
LOOP_LAST = {"do", "for", "simd", "loop", "distribute", "taskloop", "tile", "unroll"}
STANDALONE = {("target", "update"), ("target", "enter", "data"), ("target", "exit", "data"),
              ("taskwait",), ("taskyield",), ("barrier",), ("flush",), ("cancel",),
              ("cancellation", "point"), ("update",), ("wait",), ("enter", "data"), ("exit", "data"),
              ("init",), ("shutdown",), ("set",), ("declare", "target"), ("requires",), ("error",),
              ("nothing",), ("interop",), ("scan",), ("depobj",)}


@dataclass
class Directive:
    indent: str
    model: str          # omp | acc
    name: list          # the directive's words
    clauses: list       # the clause tokens, in order
    lang: str

    def render(self) -> str:
        head = f"{self.indent}!${self.model} " if self.lang == "f90" else f"{self.indent}#pragma {self.model} "
        return (head + " ".join(self.name + self.clauses)).rstrip()

    @property
    def is_end(self) -> bool:
        return bool(self.name) and self.name[0] == "end"

    @property
    def last(self) -> str:
        return self.name[-1] if self.name else ""

    @property
    def standalone(self) -> bool:
        return tuple(self.name) in STANDALONE


def _tokens(body: str) -> list[str]:
    """The directive's words and clause tokens: split at depth 0 on blanks
    and commas; a token that opens with "(" joins the word before it."""
    toks, depth, cur = [], 0, ""
    for ch in body:
        if ch in " \t," and depth == 0:
            if cur:
                toks.append(cur)
            cur = ""
            continue
        depth += {"(": 1, ")": -1}.get(ch, 0)
        cur += ch
    if cur:
        toks.append(cur)
    out: list[str] = []
    for t in toks:
        if t.startswith("(") and out and "(" not in out[-1]:
            out[-1] += t
        else:
            out.append(t)
    return out


def parse_directive(line: str, lang: str) -> Directive | None:
    m = (_F_DIR if lang == "f90" else _C_DIR).match(line)
    if not m:
        return None
    toks = _tokens(m.group(3))
    name: list[str] = []
    for i, t in enumerate(toks):
        w = t.lower()
        if "(" in t or w not in DIRECTIVE_WORDS:
            break
        if i > 0 and w in _ATOMIC_CLAUSES and name[0] == "atomic":
            break
        if i > 0 and w == "reduction":
            break
        name.append(w)
    return Directive(m.group(1), m.group(2).lower(), name, toks[len(name):], lang)


def is_directive(line: str, lang: str) -> bool:
    return parse_directive(line, lang) is not None


@dataclass
class Clause:
    word: str
    mods: list          # the modifiers before the last top-level ":" (None: no ":")
    items: list
    raw: str

    def render(self) -> str:
        if not self.items and self.mods is None:
            return self.word
        inner = ", ".join(self.items)
        if self.mods is not None:
            inner = ", ".join(self.mods) + (": " if inner else ":") + inner
        return f"{self.word}({inner})"


def _split_top(s: str, seps=(",",)) -> list[str]:
    parts, depth, cur = [], 0, ""
    for ch in s:
        if ch in seps and depth == 0:
            parts.append(cur.strip())
            cur = ""
            continue
        depth += {"(": 1, "[": 1, ")": -1, "]": -1}.get(ch, 0)
        cur += ch
    parts.append(cur.strip())
    return [p for p in parts if p != ""]


def parse_clause(tok: str) -> Clause:
    m = re.match(r"([A-Za-z_]\w*)\s*\((.*)\)$", tok, re.S)
    if not m:
        return Clause(tok, None, [], tok)
    word, inner = m.group(1).lower(), m.group(2)
    depth, cut = 0, None
    for i, ch in enumerate(inner):
        depth += {"(": 1, "[": 1, ")": -1, "]": -1}.get(ch, 0)
        if ch == ":" and depth == 0 and not (i + 1 < len(inner) and inner[i + 1] == ":"):
            cut = i
    if cut is None:
        return Clause(word, None, _split_top(inner), tok)
    return Clause(word, _split_top(inner[:cut]), _split_top(inner[cut + 1:]), tok)


def _set_clauses(d: Directive, clauses: list) -> str:
    return Directive(d.indent, d.model, list(d.name), list(clauses), d.lang).render()


# --- logical lines ------------------------------------------------------------------------

def logical_lines(text: str, lang: str) -> list[str]:
    """Continued lines joined (Fortran ``&`` and ``!$omp&``; C ``\\``)."""
    if lang == "f90":
        from offload.engine.fuzz_min import join_lines
        return join_lines(text)
    out, raw, k = [], text.splitlines(), 0
    while k < len(raw):
        line = raw[k].rstrip()
        while line.endswith("\\") and k + 1 < len(raw):
            k += 1
            line = line[:-1].rstrip() + " " + raw[k].strip()
        out.append(line)
        k += 1
    return out


def render_lines(lines: list[str], lang: str) -> str:
    if lang == "f90":
        from offload.engine.fuzz_min import render
        return render(list(lines))
    return "\n".join(lines) + "\n"


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


# --- extents of constructs -----------------------------------------------------------------

def _f_end_of_loop(lines, k) -> int | None:
    """``end do`` of the do statement at k (nesting by do/end do)."""
    depth = 0
    for j in range(k, len(lines)):
        s = lines[j].strip().lower()
        s = re.sub(r"^\w+\s*:\s*", "", s)     # a construct name
        if re.match(r"do\b", s) and not re.match(r"do\s*while\b.*\bend\b", s):
            depth += 1
        elif re.match(r"end\s*do\b", s):
            depth -= 1
            if depth == 0:
                return j
    return None


def _f_end_of_if(lines, k) -> int | None:
    depth = 0
    for j in range(k, len(lines)):
        s = lines[j].strip().lower()
        if re.match(r"(\w+\s*:\s*)?if\s*\(.*\)\s*then$", s):
            depth += 1
        elif re.match(r"end\s*if\b", s):
            depth -= 1
            if depth == 0:
                return j
    return None


def _f_end_directive(lines, k, d: Directive) -> int | None:
    """The ``end <name>`` directive matching the block directive at k
    (nesting by the same name)."""
    depth = 0
    for j in range(k + 1, len(lines)):
        e = parse_directive(lines[j], "f90")
        if e is None or e.model != d.model:
            continue
        if not e.is_end and e.name == d.name:
            depth += 1
        elif e.is_end and e.name[1:] == d.name:
            if depth == 0:
                return j
            depth -= 1
    return None


def f_construct_extent(lines, k) -> tuple[int, int | None] | None:
    """(last line of the construct, its end-directive line or None) for the
    directive at k: a block construct to its end directive; a loop
    construct to its loop's end (plus an optional end directive); a
    standalone directive is one line."""
    d = parse_directive(lines[k], "f90")
    if d is None or d.is_end or not d.name:
        return None
    if tuple(d.name) in STANDALONE:
        return k, None
    if d.last == "atomic" or d.name[0] == "atomic":
        e = _f_end_directive(lines, k, d)
        return (e, e) if e is not None else (k + 1, None)
    if d.last in LOOP_LAST or (d.model == "acc" and d.last in ("loop", "kernels") and
                               k + 1 < len(lines) and lines[k + 1].strip().lower().startswith("do")):
        j = k + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j < len(lines) and re.match(r"(\w+\s*:\s*)?do\b", lines[j].strip().lower()):
            e = _f_end_of_loop(lines, j)
            if e is None:
                return None
            if e + 1 < len(lines):
                nxt = parse_directive(lines[e + 1], "f90")
                if nxt is not None and nxt.is_end and nxt.name[1:] == d.name:
                    return e + 1, e + 1
            return e, None
        e = _f_end_directive(lines, k, d)
        return (e, e) if e is not None else None
    e = _f_end_directive(lines, k, d)
    return (e, e) if e is not None else None


def _c_block_end(lines, k) -> int:
    """The last line of the C statement that starts at line k: a ``{``
    block to its matching ``}``; else to the first line ending in ``;``
    or a ``}``; a ``for``/``if`` head followed by a block or statement."""
    depth, opened = 0, False
    for j in range(k, len(lines)):
        s = lines[j]
        depth += s.count("{") - s.count("}")
        if "{" in s:
            opened = True
        if opened and depth <= 0:
            return j
        if not opened and s.rstrip().endswith(";") and not re.match(r"\s*(for|if|while)\s*\(", s):
            return j
        if not opened and re.match(r"\s*(for|if|while)\s*\(.*\)\s*$", s):
            continue
        if not opened and re.match(r"\s*(for|if|while)\s*\(.*\).*;\s*$", s):
            return j
    return len(lines) - 1


def c_construct_extent(lines, k) -> tuple[int, int | None] | None:
    d = parse_directive(lines[k], "c")
    if d is None or not d.name:
        return None
    if tuple(d.name) in STANDALONE or d.name[0] in ("declare", "requires"):
        return k, None
    if k + 1 >= len(lines):
        return k, None
    return _c_block_end(lines, k + 1), None


def construct_extent(lines, k, lang):
    return f_construct_extent(lines, k) if lang == "f90" else c_construct_extent(lines, k)


_F_KEEP = re.compile(r"^\s*(program|end\b|module|contains|implicit|use\s|subroutine|function|"
                     r"interface|type\b|integer function|do\b|else|block|\w+\s*:\s*do\b)", re.I)
_F_DECL = re.compile(r"^\s*(integer|real|complex|logical|character|double precision|type\s*\(|class\s*\()"
                     r".*::", re.I)
_C_DECL = re.compile(r"^\s*(?:static\s+|const\s+|unsigned\s+|signed\s+)*(int|long|short|char|float|double|"
                     r"size_t|_Bool|bool|int\d+_t|uint\d+_t|struct\s+\w+)\b[^(]*;\s*$")
_RESULT = re.compile(r"RESULT|check=", re.I)


def _f_statement_deletable(lines, k) -> bool:
    s = lines[k].strip()
    low = s.lower()
    if not s or s.startswith("!") or _F_KEEP.match(s) or _F_DECL.match(s) or "::" in s:
        return False
    if re.match(r"(\w+\s*:\s*)?if\s*\(.*\)\s*then$", low) or re.match(r"end\s*(do|if|block)\b", low):
        return False
    if _RESULT.search(s) and low.startswith(("print", "write")):
        return False
    if k > 0 and (lines[k - 1].strip().lower().startswith(("!$omp atomic", "!$acc atomic"))):
        return False
    return True


def _c_statement_deletable(lines, k) -> bool:
    s = lines[k].strip()
    if not s or s.startswith(("//", "#", "/*", "*")) or s in ("{", "}") or s.endswith("{"):
        return False
    if re.match(r"(for|if|else|while|do|switch|case|default|return|int\s+main)\b", s) or _C_DECL.match(s):
        return False
    if _RESULT.search(s) and "printf" in s:
        return False
    return s.endswith(";")


# --- level 1: blocks, unwrapping, statements ---------------------------------------------

@step("block", level=1, only=not_fuzz_format)
def block_candidates(text: str, lang: str) -> list[Candidate]:
    """Delete a construct with its body (coarsest first), a loop, an if
    block, a standalone directive."""
    L = logical_lines(text, lang)
    spans = []
    for k in range(len(L)):
        if is_directive(L[k], lang):
            ext = construct_extent(L, k, lang)
            if ext is not None:
                spans.append((k, ext[0], f"delete construct {L[k].strip()[:50]} at line {k + 1}"))
        elif lang == "f90":
            s = L[k].strip().lower()
            if re.match(r"(\w+\s*:\s*)?do\b", s) and not (k > 0 and is_directive(L[k - 1], lang)):
                e = _f_end_of_loop(L, k)
                if e is not None:
                    spans.append((k, e, f"delete loop at line {k + 1}"))
            elif re.match(r"(\w+\s*:\s*)?if\s*\(.*\)\s*then$", s):
                e = _f_end_of_if(L, k)
                if e is not None:
                    spans.append((k, e, f"delete if block at line {k + 1}"))
        else:
            s = L[k].strip()
            if re.match(r"(for|if)\s*\(", s) and not (k > 0 and is_directive(L[k - 1], lang)):
                e = _c_block_end(L, k)
                spans.append((k, e, f"delete {s.split('(')[0].strip()} block at line {k + 1}"))
    out = []
    for k, e, what in sorted(spans, key=lambda t: (t[0] - t[1], t[0])):
        out.append(Candidate(what, render_lines(L[:k] + L[e + 1:], lang)))
    return out


@step("unwrap", level=1, controls=True, only=not_fuzz_format)
def unwrap_candidates(text: str, lang: str) -> list[Candidate]:
    """Remove a directive (and its end directive), keeping its body."""
    L = logical_lines(text, lang)
    out = []
    for k in range(len(L)):
        d = parse_directive(L[k], lang)
        if d is None or d.is_end or not d.name:
            continue
        ext = construct_extent(L, k, lang)
        if ext is None or ext[0] == k:
            continue
        drop = {k} | ({ext[1]} if ext[1] is not None else set())
        if lang == "f90" and (d.last == "atomic" or d.name[0] == "atomic"):
            continue
        new = [ln for i, ln in enumerate(L) if i not in drop]
        out.append(Candidate(f"unwrap {' '.join(d.name)} at line {k + 1}", render_lines(new, lang)))
    return out


_F_LHS = re.compile(r"^\s*(?:if\s*\(.*\)\s*)?([a-z_]\w*)\s*(?:\([^=]*\))?\s*=(?!=)(.*)$", re.I)
_C_LHS = re.compile(r"^\s*(?:([A-Za-z_]\w*)\s*(?:\[[^=]*\])*\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)(.*?);|"
                    r"(?:\+\+|--)\s*([A-Za-z_]\w*)\s*;|([A-Za-z_]\w*)\s*(?:\+\+|--)\s*;)\s*$")
_LOOP_COND = re.compile(r"\b(?:while|for)\s*\((.*)\)|\bdo\s+while\s*\((.*)\)", re.I)


def assigned_name(line: str, lang: str) -> tuple[str | None, str]:
    """(the variable a statement assigns or updates, the right-hand side)."""
    if lang == "f90":
        m = _F_LHS.match(line)
        return (m.group(1), m.group(2)) if m else (None, "")
    m = _C_LHS.match(line)
    if not m:
        return None, ""
    return m.group(1) or m.group(2) or m.group(3), m.group(2) or ""


def _loop_condition_names(L, lang) -> set:
    out = set()
    for ln in L:
        for m in _LOOP_COND.finditer(ln):
            cond = m.group(1) or m.group(2) or ""
            out |= set(re.findall(r"[A-Za-z_]\w*", cond))
    return out


def is_read_elsewhere(L, k: int, name: str, lang: str) -> bool:
    """Some line other than k names `name` otherwise than as the target of a
    whole-variable assignment whose right-hand side does not read it (a
    declaration does not count; an element assignment, a print, a
    condition, any expression does)."""
    flags = re.I if lang == "f90" else 0
    pat = re.compile(rf"(?<![\w%]){re.escape(name)}(?!\w)", flags)
    decl = _F_DECL if lang == "f90" else _C_DECL
    for j, ln in enumerate(L):
        s = ln.strip()
        if j == k or not pat.search(ln) or not s or s.startswith(("!", "//", "#")) or decl.match(ln):
            continue
        if lang == "f90" and re.match(r"\s*(use\s|integer|real|logical|character|double)", ln, re.I):
            continue
        tgt, rhs = assigned_name(ln, lang)
        plain = re.match(rf"\s*{re.escape(name)}\s*=(?!=)", ln, flags) is not None
        if tgt and tgt.lower() == name.lower() and plain and not pat.search(rhs):
            continue
        return True
    return False


@step("statement", level=1, only=not_fuzz_format)
def statement_candidates(text: str, lang: str) -> list[Candidate]:
    """Delete one statement line (not a declaration, a structural line or
    the RESULT line). An assignment stays while another line reads its
    variable (a print, an expression, an element assignment: the read
    would become undefined) or the variable steers a while/for loop."""
    L = logical_lines(text, lang)
    ok = _f_statement_deletable if lang == "f90" else _c_statement_deletable
    loop_vars = _loop_condition_names(L, lang)
    out = []
    for k in range(len(L)):
        if is_directive(L[k], lang) or not ok(L, k):
            continue
        if lang == "f90" and construct_extent(L, k, lang) is not None:
            continue
        name, _ = assigned_name(L[k], lang)
        if name and (name in loop_vars or is_read_elsewhere(L, k, name, lang)):
            continue
        out.append(Candidate(f"delete statement at line {k + 1}: {L[k].strip()[:40]}",
                             render_lines(L[:k] + L[k + 1:], lang)))
    return out


# --- level 2: clauses, items, modifiers, prefixes -----------------------------------------

def _directive_lines(L, lang):
    for k, ln in enumerate(L):
        d = parse_directive(ln, lang)
        if d is not None and d.name and d.clauses:
            yield k, d


@step("clause", level=2, controls=True, only=not_fuzz_format)
def clause_candidates(text: str, lang: str) -> list[Candidate]:
    L = logical_lines(text, lang)
    out = []
    for k, d in _directive_lines(L, lang):
        for i, c in enumerate(d.clauses):
            new = list(L)
            new[k] = _set_clauses(d, d.clauses[:i] + d.clauses[i + 1:])
            out.append(Candidate(f"delete clause {c[:40]} at line {k + 1}", render_lines(new, lang)))
    return out


@step("clause-item", level=2, controls=True, only=not_fuzz_format)
def clause_item_candidates(text: str, lang: str) -> list[Candidate]:
    """Drop one item of a clause's list (two or more items; a schedule's
    chunk only)."""
    L = logical_lines(text, lang)
    out = []
    for k, d in _directive_lines(L, lang):
        for i, tok in enumerate(d.clauses):
            c = parse_clause(tok)
            if len(c.items) < 2:
                continue
            idx = [len(c.items) - 1] if c.word in ("schedule", "dist_schedule") else range(len(c.items))
            for j in idx:
                nc = Clause(c.word, c.mods, c.items[:j] + c.items[j + 1:], tok)
                new = list(L)
                new[k] = _set_clauses(d, d.clauses[:i] + [nc.render()] + d.clauses[i + 1:])
                out.append(Candidate(f"drop {c.items[j][:30]} from {tok[:40]} at line {k + 1}",
                                     render_lines(new, lang)))
    return out


_REDUCTIONS = ("reduction", "in_reduction", "task_reduction")


@step("modifier", level=2, controls=True, only=not_fuzz_format)
def modifier_candidates(text: str, lang: str) -> list[Candidate]:
    """Drop one modifier of a clause: a map-type modifier (always, close,
    present), a directive-name modifier of if, the iterator of depend."""
    L = logical_lines(text, lang)
    out = []
    for k, d in _directive_lines(L, lang):
        for i, tok in enumerate(d.clauses):
            c = parse_clause(tok)
            if c.mods is None or c.word in _REDUCTIONS:
                continue
            drop = list(range(len(c.mods) - 1)) if len(c.mods) > 1 else \
                ([0] if c.word in ("if", "defaultmap") and len(c.mods) == 1 and c.word == "if" else [])
            for j in drop:
                rest = c.mods[:j] + c.mods[j + 1:]
                nc = Clause(c.word, rest or None, c.items, tok)
                new = list(L)
                new[k] = _set_clauses(d, d.clauses[:i] + [nc.render()] + d.clauses[i + 1:])
                out.append(Candidate(f"drop modifier {c.mods[j]} from {tok[:40]} at line {k + 1}",
                                     render_lines(new, lang)))
    return out


@step("prefix", level=2, controls=True, only=not_fuzz_format)
def prefix_candidates(text: str, lang: str) -> list[Candidate]:
    """Shorten a combined construct to a prefix of its name (``target
    teams distribute parallel do`` -> ``target teams distribute``, ...,
    ``target``); Fortran end directives follow, and a loop construct that
    becomes a block construct gets its end directive after the loop."""
    L = logical_lines(text, lang)
    out = []
    for k in range(len(L)):
        d = parse_directive(L[k], lang)
        if d is None or d.is_end or len(d.name) < 2 or tuple(d.name) in STANDALONE:
            continue
        if d.name[0] in ("end", "declare", "atomic", "cancellation", "target") and \
                tuple(d.name[:2]) in (("target", "update"), ("target", "enter"), ("target", "exit")):
            continue
        ext = construct_extent(L, k, lang)
        if ext is None:
            continue
        last, end_line = ext
        for cut in range(len(d.name) - 1, 0, -1):
            prefix = d.name[:cut]
            if prefix[-1] not in BLOCK_LAST | LOOP_LAST:
                continue
            new = list(L)
            new[k] = Directive(d.indent, d.model, prefix, d.clauses, lang).render()
            if lang == "f90":
                if end_line is not None:
                    new[end_line] = f"{d.indent}!${d.model} end {' '.join(prefix)}"
                elif prefix[-1] in BLOCK_LAST:
                    new.insert(last + 1, f"{d.indent}!${d.model} end {' '.join(prefix)}")
            out.append(Candidate(f"shorten {' '.join(d.name)} to {' '.join(prefix)} at line {k + 1}",
                                 render_lines(new, lang)))
    return out


@step("clause-order", level=0, controls=True, only=not_fuzz_format)
def clause_order_candidates(text: str, lang: str) -> list[Candidate]:
    """Swap two adjacent clauses (a control only: level 0 is never a
    reduction level; the order of clauses carries no meaning)."""
    L = logical_lines(text, lang)
    out = []
    for k, d in _directive_lines(L, lang):
        for i in range(len(d.clauses) - 1):
            cl = list(d.clauses)
            cl[i], cl[i + 1] = cl[i + 1], cl[i]
            new = list(L)
            new[k] = _set_clauses(d, cl)
            out.append(Candidate(f"swap clause order: {d.clauses[i][:25]} and {d.clauses[i + 1][:25]} "
                                 f"at line {k + 1}", render_lines(new, lang)))
    return out


# --- level 3: expressions, bounds and extents ----------------------------------------------

_F_BOUND = re.compile(r"parameter\s*::\s*\w+\s*=\s*(\d+)|\bdo\s+\w+\s*=\s*-?\d+\s*,\s*(\d+)", re.I)
_C_BOUND = re.compile(r"#\s*define\s+\w+\s+(\d+)|\b\w+\s*<=?\s*(\d+)\s*;")
_DIGITS_IN_BRACKETS = re.compile(r"[(\[,]\s*(\d+)\s*(?=[)\],])")


def _is_decl(line: str, lang: str) -> bool:
    return bool((_F_DECL if lang == "f90" else _C_DECL).match(line)) or line.lstrip().startswith("#define")


def extent_literals(text: str, lang: str) -> list[int]:
    """The integer extents, bounds and parameters a program can shrink:
    array extents in declarations, parameter and #define values, do and
    for upper bounds (4 and above), largest first."""
    found = set()
    for ln in text.splitlines():
        if _is_decl(ln, lang):
            found |= {int(x) for x in _DIGITS_IN_BRACKETS.findall(ln)}
        for m in (_F_BOUND if lang == "f90" else _C_BOUND).finditer(ln):
            found.add(int(m.group(1) or m.group(2)))
    return sorted((x for x in found if x >= 4), reverse=True)


def index_literals(text: str, lang: str) -> set:
    """The integer literals an executable line reads an element at (a(5),
    a[4]): an extent never shrinks below one of them."""
    out = set()
    for ln in text.splitlines():
        if _is_decl(ln, lang) or is_directive(ln, lang) or ln.strip().startswith(("!", "//")):
            continue
        out |= {int(x) for x in _DIGITS_IN_BRACKETS.findall(ln)}
    return out


def _split_binary(expr: str, lang: str) -> list[str]:
    """Immediate operands of a top-level binary expression; the arguments
    of a one-call expression; the inside of outer parentheses."""
    e = expr.strip()
    while e.startswith("(") and e.endswith(")") and _balanced(e[1:-1]):
        e = e[1:-1].strip()
    seps = (" + ", " - ", " * ", " / ", " .and. ", " .or. ") if lang == "f90" else \
        ("+", "-", "*", "/", "%", "&&", "||", "&", "|", "^")
    parts, depth, cur, k = [], 0, "", 0
    while k < len(e):
        if depth == 0 and k > 0:
            for sep in seps:
                if e.startswith(sep, k) and cur.strip() and not cur.rstrip().endswith(("(", ",", "=")):
                    parts.append(cur.strip())
                    cur = ""
                    k += len(sep)
                    break
            else:
                depth += {"(": 1, "[": 1, ")": -1, "]": -1}.get(e[k], 0)
                cur += e[k]
                k += 1
            continue
        depth += {"(": 1, "[": 1, ")": -1, "]": -1}.get(e[k], 0)
        cur += e[k]
        k += 1
    if cur.strip():
        parts.append(cur.strip())
    if len(parts) >= 2:
        return parts
    m = re.match(r"(\w+)\s*\((.*)\)$", e)
    if m and _balanced(m.group(2)) and m.group(1).lower() not in ("merge",):
        args = _split_top(m.group(2))
        return [a for a in args if a]
    if m and m.group(1).lower() == "merge":
        return _split_top(m.group(2))[:2]
    return []


def _balanced(s: str) -> bool:
    d = 0
    for ch in s:
        d += {"(": 1, ")": -1}.get(ch, 0)
        if d < 0:
            return False
    return d == 0


_F_ASSIGN = re.compile(r"^(\s*(?:if\s*\(.*\)\s*)?[a-z]\w*(?:\s*\([^=]*\))?\s*=\s*)(?!=)(.+?)\s*$", re.I)
_C_ASSIGN = re.compile(r"^(\s*[A-Za-z_]\w*(?:\s*\[[^=]*\])*\s*=\s*)(?![=])(.+?);\s*$")


@step("expression", level=3, only=not_fuzz_format)
def expression_candidates(text: str, lang: str) -> list[Candidate]:
    """Halve every occurrence of one integer extent, bound or parameter
    (all at once, so declarations and loops stay consistent); replace a
    right-hand side by one of its operands."""
    out = []
    # an extent never shrinks below a literal index the program reads at (a(5) with n = 4)
    indices = index_literals(text, lang)
    for lit in extent_literals(text, lang):
        if any(lit // 2 < i <= lit for i in indices):
            continue
        new = re.sub(rf"(?<![\w.]){lit}(?![\w.])", str(lit // 2), text)
        if new != text:
            out.append(Candidate(f"halve {lit} to {lit // 2}", new))
    L = logical_lines(text, lang)
    rx = _F_ASSIGN if lang == "f90" else _C_ASSIGN
    for k, ln in enumerate(L):
        m = rx.match(ln)
        if not m or is_directive(ln, lang) or re.match(r"\s*(do|for|if|while)\b", ln):
            continue
        head, rhs = m.group(1), m.group(2)
        if "omp_is_initial_device" in rhs or "acc_on_device" in rhs or _RESULT.search(ln):
            continue
        for sub in _split_binary(rhs, lang):
            if sub == rhs.strip():
                continue
            new = list(L)
            new[k] = head + sub + (";" if lang == "c" else "")
            out.append(Candidate(f"simplify line {k + 1}: {sub[:40]}", render_lines(new, lang)))
    return out


# --- level 4: cleanup --------------------------------------------------------------------

def _f_entities(decl: str) -> tuple[str, list[str]]:
    head, ents = decl.split("::", 1)
    return head, _split_top(ents)


def _name_of(entity: str) -> str:
    m = re.match(r"\s*([A-Za-z_]\w*)", entity)
    return m.group(1) if m else entity.strip()


@step("cleanup", level=4, only=not_fuzz_format)
def cleanup_candidates(text: str, lang: str) -> list[Candidate]:
    """Remove a declared variable no other line names (its entity, its
    whole-line initialisation, allocate and deallocate)."""
    L = logical_lines(text, lang)
    out = []
    decl_rx = _F_DECL if lang == "f90" else _C_DECL
    for k, ln in enumerate(L):
        if not decl_rx.match(ln) or ("parameter" in ln.lower() and lang == "f90"):
            continue
        if lang == "f90":
            head, ents = _f_entities(ln)
            sep = ", "
        else:
            m = re.match(r"^(\s*(?:[\w\s]+?)\s+)(.*);\s*$", ln)
            if not m:
                continue
            head, ents = m.group(1), _split_top(m.group(2))
        for ent in ents:
            name = _name_of(ent)
            pat = re.compile(rf"(?<![\w%]){re.escape(name)}(?![\w])", re.I if lang == "f90" else 0)
            others = [j for j, x in enumerate(L) if j != k and pat.search(x)]
            init = [j for j in others if re.match(
                rf"\s*(?:{re.escape(name)}\s*(?:\(.*\))?\s*=[^=]|(?:de)?allocate\s*\(\s*{re.escape(name)}\b)",
                L[j], re.I)]
            if [j for j in others if j not in init]:
                continue
            keep = [e for e in ents if e is not ent]
            new = []
            for j, x in enumerate(L):
                if j == k:
                    if keep:
                        new.append((head + "::" + " " + sep.join(keep)) if lang == "f90"
                                   else head + ", ".join(keep) + ";")
                elif j not in init:
                    new.append(x)
            out.append(Candidate(f"remove unused {name}", render_lines(new, lang)))
    return out


# --- the fuzz-format steps (offload.engine.fuzz_min) --------------------------------------------

def _fuzz_steps(kind: str):
    from offload.engine import fuzz_min as FM

    def gen(text: str, lang: str) -> list[Candidate]:
        lines = FM.join_lines(text)
        try:
            if kind == "files":
                cands = FM.file_candidates(lines)
            elif kind == "cleanup":
                cands = FM.cleanup_candidates(lines)
            else:
                cands = FM.candidates(lines)
        except (StopIteration, ValueError, IndexError):
            return []
        if kind in ("blocks", "clauses", "expressions"):
            want = {"blocks": ("delete lines", "unwrap", "rename", "delete statement"),
                    "clauses": ("delete clause", "drop "), "expressions": ("simplify",)}[kind]
            cands = [c for c in cands if c.what.startswith(want)]
        return [Candidate(c.what, FM.render(list(c.lines))) for c in cands]
    return gen


step("fuzz-blocks", level=1, langs=("f90",), only=is_fuzz_format)(_fuzz_steps("blocks"))
step("fuzz-files", level=1, langs=("f90",), only=is_fuzz_format)(_fuzz_steps("files"))
step("fuzz-clauses", level=2, langs=("f90",), only=is_fuzz_format)(_fuzz_steps("clauses"))
step("fuzz-expressions", level=3, langs=("f90",), only=is_fuzz_format)(_fuzz_steps("expressions"))
step("fuzz-cleanup", level=4, langs=("f90",), only=is_fuzz_format)(_fuzz_steps("cleanup"))


_USE_ONLY = re.compile(r"^(\s*use\s+\w+\s*,\s*only\s*:\s*)(.*)$", re.I)


@step("fuzz-tidy", level=4, langs=("f90",), only=is_fuzz_format)
def fuzz_tidy_candidates(text: str, lang: str) -> list[Candidate]:
    """Remove an empty module (``module``, ``implicit none``, ``contains``,
    ``end module`` and nothing else) and a name no line uses from a ``use
    ..., only:`` list (the whole line when none is left)."""
    L = text.splitlines()
    out = []
    for k, ln in enumerate(L):
        m = re.match(r"^\s*module\s+(\w+)\s*$", ln, re.I)
        if m:
            e = next((j for j in range(k + 1, len(L))
                      if re.match(rf"^\s*end\s+module\s+{m.group(1)}\s*$", L[j], re.I)), None)
            if e is not None and all(re.match(r"^\s*(implicit none|contains|private|public)?\s*$", x, re.I)
                                     for x in L[k + 1:e]) and \
                    not any(re.search(rf"\buse\s+{m.group(1)}\b", x, re.I) for x in L):
                out.append(Candidate(f"remove empty module {m.group(1)}", "\n".join(L[:k] + L[e + 1:]) + "\n"))
        u = _USE_ONLY.match(ln)
        if u:
            names = [x.strip() for x in u.group(2).split(",") if x.strip()]
            rest = "\n".join(x for j, x in enumerate(L) if j != k)
            for nm in names:
                if re.search(rf"\b{re.escape(nm)}\b", rest, re.I):
                    continue
                keep = [x for x in names if x != nm]
                new = list(L)
                if keep:
                    new[k] = u.group(1) + ", ".join(keep)
                else:
                    del new[k]
                out.append(Candidate(f"drop unused import {nm}", "\n".join(new) + "\n"))
    return out

# the generic directive edits serve as controls of a reduced fuzz program too
for _n in ("unwrap", "clause", "clause-item", "modifier", "prefix", "clause-order"):
    _s = next(s for s in STEPS if s.name == _n)
    STEPS.append(Step(f"{_n}-fuzz", 0, _s.langs, _s.fn, True, is_fuzz_format))


# --- the output contract ---------------------------------------------------------------------

FUZZ_PRINT = re.compile(r"^(\s*)print\s*'\([^']*\)'\s*,\s*'RESULT checksum='\s*,\s*(\w+)\s*,"
                        r"\s*' ran_on_host='\s*,\s*(.+?)\s*$", re.M)


class PlainContract:
    """A self-checking program (``RESULT ran_on_host=. check=pass|fail``)."""
    why = ""

    def applies(self, text: str) -> bool:
        return True

    def prepare(self, text: str) -> str | None:
        return text


def elision_compilers() -> tuple:
    """The elision's compilers that are installed here (wingtip has gfortran
    only; offload.engine.expected lists gfortran and AFAR's amdflang)."""
    from offload.engine import expected as E
    import shutil
    have = []
    for c in E.ELISION_COMPILERS:
        path = E.GFORTRAN if c == "gfortran" else E.AMDFLANG
        if Path(path).is_file() or shutil.which(path):
            have.append(c)
    return tuple(have)


def elision_reference(text: str):
    """The sequential elision's checksum (int) of a fuzz program by the
    installed elision compilers, or why there is none (str)."""
    from offload.engine import expected as E
    comps = elision_compilers()
    if not comps:
        return "no elision compiler installed here"
    ev = E.elision_evidence(text, compilers=comps)
    if ev.status == "value":
        return int(ev.value.split("=", 1)[1])
    why = ev.detail if isinstance(ev.detail, str) else "; ".join(map(str, ev.detail or []))
    return f"{ev.status}: {why}"[:300]


class FuzzContract:
    """A fuzz program prints ``RESULT checksum=N ran_on_host=H`` and has no
    self-check; the candidate run gets the harness's form, checked
    against the reference value of the same text (default: the
    sequential elision, offload.engine.fuzz_exec.elision_value: an int, or a
    string saying why there is none, which rejects the candidate)."""

    def __init__(self, reference=None):
        self.reference = reference or elision_reference
        self.why = ""

    @staticmethod
    def applies(text: str) -> bool:
        return FUZZ_PRINT.search(text) is not None

    def prepare(self, text: str) -> str | None:
        m = FUZZ_PRINT.search(text)
        if m is None:
            return text
        ref = self.reference(text)
        if not isinstance(ref, int):
            self.why = str(ref)
            return None
        ind, cs, host = m.group(1), m.group(2), m.group(3)
        new = (f"{ind}print '(a,i0)', 'checksum= ', {cs}\n"
               f"{ind}print '(a,i0,a,a)', 'RESULT ran_on_host=', {host}, ' check=', "
               f"merge('pass', 'fail', {cs} == {ref}_8)")
        return text[:m.start()] + new + text[m.end():]


def contract_for(text: str, lang: str):
    return FuzzContract() if lang == "f90" and FuzzContract.applies(text) else PlainContract()


# --- witnesses -------------------------------------------------------------------------------

def rules_witness(text: str, lang: str) -> tuple[bool, list[str]]:
    """The repository's legality rules (offload.engine.prerun.rules_witness) on
    a program text: accepted only on a clear yes (a program the rules
    cannot read is no candidate)."""
    from offload.engine import prerun
    ok, why = prerun.rules_witness((text, lang))
    return bool(ok), list(why)


DEVICE_FLAG = re.compile(r"omp_is_initial_device|acc_on_device|omp_get_device_num", re.I)


def has_device_flag(text: str) -> bool:
    """A call of the host-execution flag (not its import in a ``use`` or
    ``#include`` line)."""
    return any(DEVICE_FLAG.search(ln) for ln in text.splitlines()
               if not re.match(r"\s*(use\s|#\s*include|!|//)", ln))


DEVICE_CONSTRUCT = re.compile(r"^\s*(?:!\$omp\s+target\b(?!\s+(?:update|enter|exit|data)\b)|"
                              r"#\s*pragma\s+omp\s+target\b(?!\s+(?:update|enter|exit|data)\b)|"
                              r"!\$acc\s+(?:parallel|kernels|serial)\b|"
                              r"#\s*pragma\s+acc\s+(?:parallel|kernels|serial)\b)", re.I | re.M)


def has_device_construct(text: str) -> bool:
    """A compute construct that runs on the device (a target region, an
    OpenACC compute construct); a program without one is no device-offload
    failure."""
    return DEVICE_CONSTRUCT.search(text) is not None


def flag_names(text: str) -> set:
    """The variables assigned from the host-execution flag."""
    out = set()
    for ln in text.splitlines():
        if DEVICE_FLAG.search(ln) and not re.match(r"\s*(use\s|#\s*include|!|//)", ln):
            m = re.match(r"\s*(?:if\s*\(.*\)\s*)?([A-Za-z_]\w*)\s*=", ln)
            if m:
                out.add(m.group(1))
    return out


def flagless(text: str) -> str:
    """The program with every use of a host-execution flag variable other
    than its assignment and declaration replaced by 0 (for the elision's
    applicability analysis, which otherwise stops at that use)."""
    names = flag_names(text)
    if not names:
        return text
    out = []
    assign = re.compile(r"\s*(?:if\s*\(.*\)\s*)?(" + "|".join(map(re.escape, names)) + r")\s*=(?!=)", re.I)
    for ln in text.splitlines():
        if DEVICE_FLAG.search(ln) or assign.match(ln) or \
                re.match(r"\s*(integer|logical|real|use\s|!|//|#)", ln, re.I):
            out.append(ln)              # the flag's declaration and assignments stay; its uses become 0
            continue
        for n in names:
            ln = re.sub(rf"(?<![\w%]){re.escape(n)}(?!\w)", "0", ln)
        out.append(ln)
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


_PAIR = re.compile(r"([A-Za-z_]\w*)\s*=\s*(-?\d[\d.eE+-]*)")


def printed_values(stdout: str, exclude=()) -> dict:
    """The ``name= value`` pairs a program printed before (not on) its
    RESULT line, as {name: value}, without the names in `exclude` (the
    host-execution flags)."""
    out = {}
    for ln in (stdout or "").splitlines():
        if ln.strip().startswith("RESULT"):
            continue
        for m in _PAIR.finditer(ln):
            if m.group(1) not in exclude and m.group(1) not in ("ran_on_host", "check"):
                out[m.group(1)] = m.group(2)
    return out


# --- output oracles (references) ------------------------------------------------------------

class FakeReference:
    """A reference for tests: ``fn(text) -> (values or None, why)``."""
    name = "fake"

    def __init__(self, fn):
        self.fn = fn

    def values(self, text: str, lang: str):
        return self.fn(text)


class ElisionReference:
    """The sequential elision (offload.engine.expected: the program built
    without OpenMP by the installed elision compilers, every directive a
    comment, the host as the only device): the values it prints. Fortran
    only; inapplicable programs give no values, with the reason."""
    name = "elision"

    def values(self, text: str, lang: str):
        from offload.engine import expected as E
        if lang != "f90":
            return None, "the sequential elision reads Fortran only"
        # the analysis stops at the flag's use in the RESULT line (a value the elision cannot
        # mirror); the flag-derived values are left out of the comparison, so the analysis sees the
        # program with those uses neutralized and its copy-semantics walk runs on everything else
        ap = E.elision_applicability(flagless(text))
        if not ap.ok:
            return None, "elision inapplicable: " + ap.why[:200]
        comps = elision_compilers()
        if not comps:
            return None, "no elision compiler installed here"
        outs = []
        for c in comps:
            v, note = E.run_elided(flagless(text), c, value=lambda s: s)
            if v is None:
                return None, f"elision ({c}): {note}"
            bad = reference_check_fails(v)
            if bad:
                return None, f"elision ({c}): {bad}"
            outs.append(printed_values(v, flag_names(text)))
        if any(o != outs[0] for o in outs):
            return None, "the elision compilers print different values"
        return outs[0], ""


_CHECK = re.compile(r"^RESULT .*check=(pass|fail)", re.M)


def reference_check_fails(stdout: str) -> str:
    """Why a reference run does not pass: its self-check line says fail (the
    candidate's check is no longer satisfiable by a correct run), or there
    is no single RESULT line. '' when it passes."""
    found = _CHECK.findall(stdout or "")
    if len(found) != 1:
        return "the reference prints no single RESULT line"
    if found[0] != "pass":
        return "the reference's own self-check fails: the candidate is not a correct program any more"
    return ""


class HostReference:
    """A host run (OMP_TARGET_OFFLOAD=disabled) of a toolchain from another
    compiler family than every target, on this node: the values it
    prints."""

    def __init__(self, toolchain: str, targets):
        from offload.engine.toolchains import TOOLCHAINS, family
        if toolchain not in TOOLCHAINS:
            raise ValueError(f"unknown reference toolchain {toolchain!r}")
        same = [t.label for t in targets if family(t.toolchain) == family(toolchain)]
        if same:
            raise ValueError(f"reference {toolchain} is in the compiler family of the target "
                             f"{', '.join(same)}: a reference is never the compiler under test's family")
        self.toolchain = toolchain
        self.name = f"host:{toolchain}"

    def values(self, text: str, lang: str):
        import shutil
        import tempfile
        from offload.engine import harness
        from offload.engine.toolchains import TOOLCHAINS
        tc = TOOLCHAINS[self.toolchain]
        lang_ = "c" if lang == "c" else "f90"
        if tc.lang != lang_:
            tc = dataclasses.replace(tc, lang=lang_)
        tc = dataclasses.replace(tc, model=model_of(text))
        mode = tc.xnack_modes[0]
        tc = tc.for_mode(mode)
        tmp = Path(tempfile.mkdtemp(prefix="reduce_ref_"))
        try:
            src, exe = tmp / f"ref.{lang_}", tmp / "ref.out"
            src.write_text(flagless(text))      # the host run's flag reads 1; its uses become 0
            build = harness._execute(harness.compile_script(tc, str(src), str(exe), "-O0", str(tmp)), tmp, 600,
                                     merge=True)
            if build.rc != 0 or not exe.is_file():
                return None, f"reference {self.toolchain} did not build: {harness._clip(build.stdout)[-200:]}"
            run = harness._execute(harness.run_script(tc, str(exe), mode, False, str(tmp), offload="disabled"),
                                   tmp, 120)
            if run.timed_out or run.rc != 0:
                return None, f"reference {self.toolchain} run failed: rc={run.rc}"
            bad = reference_check_fails(run.stdout)
            if bad:
                return None, f"reference {self.toolchain}: {bad}"
            return printed_values(run.stdout, flag_names(text)), ""
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def reference_for(spec: str | None, lang: str, targets):
    """The output oracle named by ``--reference``: ``elision`` (Fortran),
    ``host:TOOLCHAIN`` (another family than every target), None for none."""
    if spec is None:
        return None
    if spec == "elision":
        if lang != "f90":
            raise ValueError("the sequential elision reads Fortran only; a C program needs --reference host:TC")
        return ElisionReference()
    if spec.startswith("host:"):
        return HostReference(spec[5:], targets)
    raise ValueError(f"unknown reference {spec!r}: elision or host:TOOLCHAIN")


# --- runners ---------------------------------------------------------------------------------

def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def fake_row(cls: str, text: str, target: Target, msg: str = "", program_id: str = "fake") -> dict:
    """A harness-shaped row of class `cls` (correct, wrong_answer, rejected,
    ice, crash, run_error, timeout, fell_back_to_host) for a program
    text, as offload.engine.harness would record it."""
    row = dict(program_id=program_id, primary_atom="reduce", atoms=["reduce"], toolchain=target.toolchain,
               xnack=target.mode, opt=target.opt, flaky=False, flags="", rocm=None, stdout="", stderr="",
               needs=[], evidence="construct", observable=True, legal=True, violates=None, version=52,
               thp="n/a", device="fake", compiler="fake", model="omp", lang="f90", scope="device",
               machine="", arch="", gpu="", build_dir="", node="", toolchain_build="", env_hash="",
               git_rev="", gate="", messages="", sha=sha(text), file="")
    clog = "--- compile (rc=0) ---\n"
    if cls == "correct":
        row.update(outcome="correct_on_device", reason="ran_on_host=0 check=pass",
                   stdout="r= 5\nRESULT ran_on_host=0 check=pass\n", stderr=clog)
    elif cls == "wrong_answer":
        row.update(outcome="wrong_answer", reason="check_fail: ran_on_host=0 check=fail",
                   stdout="r= 0\nRESULT ran_on_host=0 check=fail\n", stderr=clog)
    elif cls == "fell_back_to_host":
        row.update(outcome="fell_back_to_host", reason="ran_on_host=1 check=pass",
                   stdout="RESULT ran_on_host=1 check=pass\n", stderr=clog)
    elif cls in ("rejected", "ice"):
        code = "ice" if cls == "ice" else "diagnostic"
        row.update(outcome="rejected", reason=f"{code}: {msg}", stderr=f"--- compile (rc=2) ---\n{msg}\n",
                   messages=msg)
    elif cls == "crash":
        sig = msg or "SIGSEGV"      # a crash prints nothing: the signal alone is the key
        row.update(outcome="wrong_answer", reason=f"crash: {sig}; without mandatory: crash: {sig}",
                   stderr=clog + "--- run (OMP_TARGET_OFFLOAD=mandatory, rc=-11) ---\n")
    elif cls == "run_error":
        row.update(outcome="wrong_answer", reason="exit_status: 1; without mandatory: exit_status: 1",
                   stderr=clog + f"--- run (OMP_TARGET_OFFLOAD=mandatory, rc=1) ---\n{msg}\n")
    elif cls == "timeout":
        row.update(outcome="wrong_answer", reason="timeout", stderr=clog)
    else:
        raise ValueError(f"fake_row: unknown class {cls!r}")
    return row


class FakeRunner:
    """A runner for tests: ``classify(text, target)`` gives a class name
    (see fake_row), a (class, message) pair or a whole row."""
    machine = "fake"

    def __init__(self, classify: Callable):
        self.classify = classify
        self.calls = 0

    def check(self, targets) -> None:
        pass

    def run(self, text: str, lang: str, target: Target, program_id: str) -> dict:
        self.calls += 1
        res = self.classify(text, target)
        if isinstance(res, dict):
            row = dict(res)
        elif isinstance(res, tuple):
            row = fake_row(res[0], text, target, msg=res[1])
        else:
            row = fake_row(res, text, target)
        row.update(program_id=program_id, lang=lang, sha=sha(text))
        return row


def model_of(text: str) -> str:
    acc = re.search(r"^\s*(?:!\$acc|#\s*pragma\s+acc)\b", text, re.M | re.I)
    omp = re.search(r"^\s*(?:!\$omp|#\s*pragma\s+omp)\b", text, re.M | re.I)
    return "acc" if acc and not omp else "omp"


class HarnessRunner:
    """offload.engine.harness.run_program on this node (a bundle: its files
    compiled as a set with the harness's scripts). ``check`` refuses a
    toolchain this node cannot run (offload.engine.harness.wrong_arch: no GPU
    on a login node, another machine's architecture)."""

    def __init__(self, run_timeout_s: int = 60, repeats: int = 2, compile_timeout_s: int = 600):
        self.run_timeout_s, self.repeats, self.compile_timeout_s = run_timeout_s, repeats, compile_timeout_s

    def check(self, targets) -> None:
        from offload.engine import harness
        from offload.engine.toolchains import TOOLCHAINS
        for t in targets:
            if t.toolchain not in TOOLCHAINS:
                raise RunnerUnavailable(f"unknown toolchain {t.toolchain!r}")
            tc = TOOLCHAINS[t.toolchain]
            try:
                tc.for_mode(t.mode)
            except ValueError as e:
                raise RunnerUnavailable(str(e))
            if t.mode not in tc.xnack_modes:
                raise RunnerUnavailable(f"{t.toolchain} has no mode {t.mode} (its modes: {tc.xnack_modes})")
            why = harness.wrong_arch(tc)
            if why:
                raise RunnerUnavailable(f"{t.label}: {why} (run tools/reduce.py on {tc.machine}, "
                                        "on a compute node or in the wingtip cap)")

    def run(self, text: str, lang: str, target: Target, program_id: str) -> dict:
        from offload.engine import harness
        from offload.engine.confirm.programs import split_files
        from offload.engine.gen import Program
        from offload.engine.toolchains import TOOLCHAINS
        tc = TOOLCHAINS[target.toolchain]
        files = split_files(text)
        if files and len(files) > 1:
            return self._run_set(files, lang, tc, target, program_id, text)
        prog = Program(id=program_id, lang="c" if lang == "c" else "fortran", source=text,
                       atoms=frozenset({"reduce"}), primary_atom="reduce", legal=True, violates=None,
                       observable=True, model=model_of(text))
        res = harness.run_program(prog, tc, target.mode, target.opt, timeout_s=self.run_timeout_s,
                                  repeats=self.repeats, compile_timeout_s=self.compile_timeout_s)
        row = dataclasses.asdict(res)
        row["outcome"] = str(res.outcome)
        row.update(sha=sha(text), file="")
        return row

    def _run_set(self, files, lang, tc, target, program_id, text) -> dict:
        """A bundle through the harness's compile-set script and trial."""
        import shutil
        import tempfile
        from offload.engine import harness
        lang_ = "c" if lang == "c" else "f90"
        if tc.lang != lang_:
            tc = dataclasses.replace(tc, lang=lang_)
        tc = dataclasses.replace(tc, model=model_of(text)).for_mode(target.mode)
        tmp = Path(tempfile.mkdtemp(prefix="harness_"))
        base = dict(program_id=program_id, primary_atom="reduce", atoms=("reduce",), toolchain=tc.name,
                    xnack=target.mode, opt=target.opt, flags=harness._flags(tc, target.opt),
                    rocm=harness._rocm(tc), device=harness.device_of(tc), compiler=harness.compiler_version(tc),
                    needs=(), evidence="construct", observable=True, legal=True, violates=None, version=52,
                    thp=harness.detect_thp(), model=tc.model, lang=lang_, scope="device",
                    machine=tc.machine, arch=tc.arch, gpu=harness.gpu_text())
        try:
            for n, t in files:
                (tmp / n).write_text(t)
            exe = tmp / "prog.out"
            build = harness._execute(harness.compile_set_script(tc, [n for n, _ in files], str(exe),
                                                                target.opt, str(tmp)),
                                     tmp, self.compile_timeout_s, merge=True)
            clog = f"--- compile (rc={build.rc}) ---\n" + harness._clip(build.stdout)

            def result(outcome, reason, stdout="", stderr="", flaky=False):
                res = harness.Result(outcome=outcome, reason=reason, flaky=flaky, stdout=harness._clip(stdout),
                                     stderr=clog + ("\n" + harness._clip(stderr) if stderr else ""), **base,
                                     **harness._provenance(tc, target.mode, str(tmp), base["flags"], outcome))
                row = dataclasses.asdict(res)
                row["outcome"] = str(outcome)
                row.update(sha=sha(text), file="")
                return row
            if build.timed_out:
                return result(harness.Outcome.harness_error, "compile_timeout")
            if build.rc != 0:
                found = harness.classify_message(tc.name, build.stdout, harness.CATEGORY_ORDER[:-1], lang_)
                if found is None:
                    return result(harness.Outcome.harness_error, f"unclassified_compile_failure: rc={build.rc}")
                cat, line = found
                if cat == "environment":
                    return result(harness.Outcome.harness_error, f"environment: {line}")
                return result(harness.Outcome.rejected, f"{harness.CODES[cat]}: {line}")
            if not exe.is_file():
                return result(harness.Outcome.harness_error, "no_executable")
            trials = []
            for _ in range(max(1, self.repeats)):
                t = harness._trial(tc, exe, target.mode, tmp, self.run_timeout_s)
                trials.append(t)
                if "timeout" in t.reason or t.outcome == harness.Outcome.harness_error:
                    break
            worst = min(trials, key=lambda t: harness.WORST_FIRST.index(t.outcome))
            flaky = len({(t.outcome, t.reason) for t in trials}) > 1
            return result(worst.outcome, worst.reason, worst.stdout, worst.stderr, flaky)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# --- the judge -----------------------------------------------------------------------------

@dataclass
class Budget:
    candidates: int | None = None      # runner calls (one per candidate and target)
    seconds: float | None = None       # runner time

    def exhausted(self, used: dict) -> bool:
        return (self.candidates is not None and used["candidates"] >= self.candidates) or \
            (self.seconds is not None and used["seconds"] >= self.seconds)


def not_evidence(row: dict) -> str:
    """Why a row is no evidence of the program's behaviour: a harness error
    or a capacity limit, a compile that hit the harness's time limit, a
    flaky row (its repeats disagree). '' when it is evidence."""
    d = R.normalize_row(dict(row))
    cls = G.outcome_class(d)
    reason = str(d.get("reason") or "")
    if cls in G.NOT_EVIDENCE or cls in G.CAPACITY_CLASSES:
        return f"harness error: {reason[:120]}"
    if cls == "timeout" and "compile" in reason[:40]:
        return f"compile timeout: not evidence ({reason[:80]})"
    if d.get("flaky"):
        return f"flaky: the repeats disagree ({reason[-120:]})"
    return ""


class Judge:
    """Does a candidate keep the failure? In order: the host-execution
    flag must stay (a program that stops calling omp_is_initial_device
    could pass as a host run), the rules witness must accept, the output
    contract must give a reference, then one run per target: the gate's
    class must be evidence (no harness error) and the signature must be
    the wanted one on every target. Cached by text; every run is a row."""

    def __init__(self, runner, targets: list, signature: Signature | None, lang: str,
                 witness: Callable = rules_witness, rows_path: Path | None = None, name: str = "reduce",
                 contract=None, budget: Budget | None = None, verify_targets=(), log=None,
                 require_device_flag: bool = True, reference=None, witness_name: str | None = None):
        import threading
        self.runner, self.targets, self.signature, self.lang = runner, list(targets), signature, lang
        self.witness, self.rows_path, self.name = witness, Path(rows_path) if rows_path else None, name
        self.witness_name = witness_name or ("rules_witness" if witness is rules_witness else witness.__name__)
        self.contract, self.budget = contract, budget or Budget()
        self.verify_targets, self.log = list(verify_targets), log or (lambda *_: None)
        self.require_device_flag = require_device_flag
        self.reference = reference          # the output oracle of a wrong-answer reduction (ElisionReference, ...)
        self.cache: dict[str, tuple[bool, str]] = {}
        self.rows: list[dict] = []
        self.used = {"candidates": 0, "seconds": 0.0}
        self.n = 0
        self.device_flag = True             # the original calls the host-execution flag
        self.device_construct = True        # the original has a device compute construct
        self._lock = threading.Lock()

    def __call__(self, text: str) -> tuple[bool, str]:
        key = sha(text)
        if key not in self.cache:
            verdict = self._judge(text)
            with self._lock:
                self.cache.setdefault(key, verdict)
        return self.cache[key]

    def contract_for(self, text: str):
        if self.contract is None:
            self.contract = contract_for(text, self.lang)
        return self.contract

    def prepared(self, text: str) -> str | None:
        return self.contract_for(text).prepare(text)

    def _check_text(self, text: str) -> tuple[str | None, str]:
        if self.require_device_flag and self.device_flag and not has_device_flag(text):
            return None, "the host-execution flag (omp_is_initial_device) must stay"
        if self.device_construct and not has_device_construct(text):
            return None, "no device construct left (the failure must stay a device-offload failure)"
        ok, why = self.witness(text, self.lang)
        if not ok:
            return None, "illegal: " + "; ".join(why)[:300]
        prepared = self.prepared(text)
        if prepared is None:
            return None, f"no reference: {self.contract.why}"[:300]
        return prepared, ""

    def _judge(self, text: str) -> tuple[bool, str]:
        prepared, why = self._check_text(text)
        if prepared is None:
            return False, why
        with self._lock:
            self.n += 1
            n = self.n
        pid = f"{self.name}~c{n}"
        for t in self.targets:
            row = self.run(prepared, t, pid)
            bad = not_evidence(row)
            if bad:
                return False, f"{t.label}: {bad}"
            cls = run_class(row)
            got = signature(row)
            # the output oracle judges a wrong answer only when a wrong answer is what is reduced: a
            # candidate that turns a compile failure or a crash into a wrong answer is another failure
            if cls == "wrong_answer" and isinstance(self.contract_for(text), PlainContract) and \
                    (self.signature is None or self.signature.cls == "wrong_answer"):
                got, why = self._oracle(text, row, got, t)
                if got is None:
                    return False, why
            if self.signature is None:
                if not G.is_failure(cls):
                    return False, f"{t.label}: {got}: not a failure"
                self.signature = got
            elif got != self.signature:
                # the recorded key of a wrong answer names no values; the first failing run (the
                # original, or on a resume the first candidate that fails) refines it once
                if got.cls == self.signature.cls and "; wrong:" in got.key and \
                        "; wrong:" not in self.signature.key and got.key.startswith(self.signature.key):
                    self.signature = got
                else:
                    return False, f"{t.label}: signature {got} (want {self.signature})"
        return True, str(self.signature)

    def _oracle(self, text: str, row: dict, got: Signature, t: Target):
        """The output oracle of a self-checking program's wrong answer: the
        reference's values must be there and the device's must differ; the
        key names the wrong values."""
        if self.reference is None:
            raise NoReference("a wrong-answer reduction of a self-checking program needs an output oracle "
                              "(--reference elision, or host:TOOLCHAIN of another family): without one every "
                              "candidate that breaks the computation would count as the identical failure")
        ref, why = self.reference.values(text, self.lang)
        if ref is None:
            return None, f"no reference: {why}"
        flags = flag_names(text)
        shown = printed_values(str(row.get("stdout") or ""))
        bad_flag = [f"{k}={v}" for k, v in shown.items() if k in flags and v != "0"]
        if bad_flag:
            return None, (f"{t.label}: the host-execution flag did not reach the host as a device run "
                          f"({' '.join(bad_flag)}): the flag's map is gone or the region ran on the host")
        dev = {k: v for k, v in shown.items() if k not in flags}
        missing = [k for k in ref if k not in dev]
        if missing:
            return None, f"{t.label}: the program no longer prints {', '.join(missing)}"
        wrong = {k: v for k, v in dev.items() if k in ref and ref[k] != v}
        if not wrong:
            return None, (f"{t.label}: the device agrees with the reference ({self.reference.name}: "
                          f"{' '.join(f'{k}={v}' for k, v in sorted(ref.items()))}): not a wrong answer")
        key = got.key + "; wrong: " + " ".join(f"{k}={v}" for k, v in sorted(wrong.items()))
        return Signature(got.cls, key), ""

    def run(self, text: str, target: Target, program_id: str) -> dict:
        with self._lock:
            if self.budget.exhausted(self.used):
                raise BudgetExhausted(f"budget spent: {self.used}")
        t0 = time.time()
        row = self.runner.run(text, self.lang, target, program_id)
        row.setdefault("seconds", round(time.time() - t0, 2))
        with self._lock:
            self.used["candidates"] += 1
            self.used["seconds"] += time.time() - t0
            self.rows.append(row)
            if self.rows_path is not None:
                self.rows_path.parent.mkdir(parents=True, exist_ok=True)
                with self.rows_path.open("a") as f:
                    f.write(json.dumps(row) + "\n")
        return row

    def passes(self, text: str, program_id: str, targets=None) -> tuple[bool, str, list[str], list[dict]]:
        """(passes everywhere, why not, the targets it passed on, the rows):
        legal, with a reference, and correct_on_device on every target."""
        prepared, why = self._check_text(text)
        if prepared is None:
            return False, why, [], []
        passed, rows, bad = [], [], ""
        for t in (targets if targets is not None else self.targets + self.verify_targets):
            row = self.run(prepared, t, program_id)
            rows.append(row)
            cls = run_class(row)
            if not_evidence(row):
                bad = bad or f"{t.label}: {not_evidence(row)}"
            elif cls in G.PASSING and cls != "unobservable":
                passed.append(t.label)
            elif not bad:
                bad = f"{t.label}: {signature(row)}"
        return not bad, bad, passed, rows

    def load_cache(self, tried: dict) -> None:
        for k, v in tried.items():
            self.cache[k] = (bool(v[0]), str(v[1]))


# --- the driver ----------------------------------------------------------------------------

def greedy(state, generators, judge, workers: int = 1, max_rounds: int = 1000, log=None, order=None):
    """Greedy delta debugging over `generators` (each ``state -> [(what,
    state)]``), coarse first: within a generator the first candidate in
    order that `judge` accepts (``state -> (ok, why)``) wins and the
    generator restarts; when none does, the next generator. `order`
    reorders a round's candidates (a seeded shuffle); batches of
    `workers` are judged in parallel. Returns (state, steps, verdict)."""
    steps, verdict = [], ""
    log = log or (lambda *_: None)
    pool = ThreadPoolExecutor(workers) if workers > 1 else None
    try:
        for gen in generators:
            for _ in range(max_rounds):
                cands = list(gen(state))
                if order is not None:
                    cands = order(cands)
                hit = None
                for b in range(0, len(cands), max(1, workers)):
                    batch = cands[b:b + max(1, workers)]
                    if pool is not None:
                        res = list(pool.map(lambda c: judge(c[1]), batch))
                    else:
                        res = [judge(c[1]) for c in batch]
                    for c, (ok, why) in zip(batch, res):
                        if ok:
                            hit = (c, why)
                            break
                    if hit:
                        break
                if not hit:
                    break
                state, verdict = hit[0][1], hit[1]
                steps.append(hit[0][0])
                log(hit[0][0], state)
    finally:
        if pool is not None:
            pool.shutdown(wait=True)
    return state, steps, verdict


@dataclass
class Reduction:
    text: str
    lines_before: int
    lines_after: int
    steps: list = field(default_factory=list)
    verdict: str = ""
    candidates_judged: int = 0
    budget_used: dict = field(default_factory=dict)
    stopped: str = "done"         # done | budget
    signature: Signature | None = None


def _setup(judge: Judge, levels) -> dict:
    """What a resumed run must have in common with the stopped one."""
    return {"targets": [t.label for t in judge.targets], "verify": [t.label for t in judge.verify_targets],
            "opt": sorted({t.opt for t in judge.targets}), "levels": list(levels), "witness": judge.witness_name,
            "reference": getattr(judge.reference, "name", None)}


def _save_checkpoint(path: Path, origin: str, lang: str, text: str, steps: list, judge: Judge,
                     levels, stopped: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"version": 2, "origin": origin, "lang": lang, "text": text, "steps": list(steps),
            "signature": dataclasses.asdict(judge.signature) if judge.signature else None,
            "tried": {k: [ok, why] for k, (ok, why) in judge.cache.items()},
            "used": dict(judge.used), "stopped": stopped, "saved": time.strftime("%Y-%m-%dT%H:%M:%S"),
            **_setup(judge, levels)}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(path)


def load_checkpoint(path: Path, origin: str, judge: Judge | None = None, levels=LEVELS) -> dict | None:
    """The checkpoint of this origin program, or None (no file, or another
    program's). With a judge, the checkpoint must have been written for the
    same targets, verify targets, levels, witness, reference and signature
    (CheckpointMismatch otherwise)."""
    path = Path(path)
    if not path.is_file():
        return None
    data = json.loads(path.read_text())
    if data.get("origin") != origin:
        return None
    if judge is not None:
        want = _setup(judge, levels)
        bad = [f"{k}: {data.get(k)} (now {v})" for k, v in want.items() if data.get(k) != v]
        sig = data.get("signature")
        if sig and judge.signature is not None:
            stored = Signature(**sig)
            if stored.cls != judge.signature.cls or not stored.key.startswith(judge.signature.key):
                bad.append(f"signature: {stored} (now {judge.signature})")
        if bad:
            raise CheckpointMismatch(f"{path} was written for another run: " + "; ".join(bad)
                                     + ". Remove it, or rerun with the same targets, levels and witness.")
    return data


def reduce(text: str, lang: str, judge: Judge, levels=LEVELS, seed: int | None = None,
           checkpoint: Path | None = None, workers: int = 1, log=None, max_rounds: int = 200) -> Reduction:
    """Reduce `text` while `judge` accepts (see the module docstring).
    Raises NoFailure when the original does not fail with the signature.
    A checkpoint of the same original resumes: its text, steps and
    judged candidates are reused."""
    log = log or (lambda *_: None)
    origin = sha(text)
    before = len(text.splitlines())
    judge.device_flag = has_device_flag(text)
    judge.device_construct = has_device_construct(text)
    steps: list[str] = []
    ck = load_checkpoint(checkpoint, origin, judge, levels) if checkpoint else None
    if ck:
        judge.load_cache(ck.get("tried") or {})
        steps = list(ck.get("steps") or [])
        if ck.get("signature"):
            stored = Signature(**ck["signature"])
            # the stored signature is the refined one (load_checkpoint checked it extends the judge's)
            if judge.signature is None or stored.key.startswith(judge.signature.key):
                judge.signature = stored
        current = ck["text"]
        log(f"resumed from {checkpoint}: {len(steps)} steps, {len(judge.cache)} candidates judged")
    else:
        current = text
    ok, why = judge(current)
    if not ok:
        raise NoFailure(why)
    rnd = random.Random(seed) if seed is not None else None

    def order(cands):
        if rnd is None:
            return cands
        cands = list(cands)
        rnd.shuffle(cands)
        return cands

    def accepted(what, state):
        log(f"  {what} -> {len(state.splitlines())} lines")
        if checkpoint:
            _save_checkpoint(Path(checkpoint), origin, lang, state, steps, judge, levels, "running")

    def gens_for(level):
        ss = steps_for(lang, current, (level,))
        if not ss:
            return []
        return [lambda state, ss=ss: [(c.what, c.text) for c in candidates(state, lang, steps=ss)]]

    stopped = "done"
    # after the last level the first is tried again, then the cleanup (what the finer levels freed)
    plan = list(levels) + ([levels[0]] + ([4] if 4 in levels and levels[0] != 4 else []) if len(levels) > 1
                           else [])
    try:
        for level in plan:
            gens = gens_for(level)
            if not gens:
                continue
            new, got, verdict = greedy(current, gens, judge, workers, max_rounds, accepted, order)
            steps += got
            current = new
    except BudgetExhausted as e:
        log(str(e))
        stopped = "budget"
    if checkpoint:
        _save_checkpoint(Path(checkpoint), origin, lang, current, steps, judge, levels, stopped)
    return Reduction(current, before, len(current.splitlines()), steps, str(judge.signature or ""),
                     judge.used["candidates"], dict(judge.used), stopped, judge.signature)


def witness_sentence(witness_name: str) -> str:
    """What the header says about legality, by the judge's witness."""
    if witness_name in ("none", "", None):
        return ("no legality witness: exploration only (every step was judged by the compiler under test "
                "alone; the result is not a candidate finding)")
    return ("Every step passed the legality rules witness (offload.engine.prerun rules); the front-end witness "
            "(offload.engine.prerun.check) is still to run on Tuolumne")


def reduction_header(name: str, origin: str, targets, res: "Reduction", out: Path, lang: str,
                     witness_name: str) -> str:
    """The comment header of a written reduction."""
    lead = "//" if lang == "c" else "!"
    tgt = ", ".join(t.label for t in targets)
    lines = [f"{lead} Reduced by tools/reduce.py from {origin} on {tgt}; failure signature: {res.signature}.",
             f"{lead} {res.lines_before} -> {res.lines_after} lines in {len(res.steps)} steps, "
             f"{res.candidates_judged} candidate runs; rows {out}/rows.jsonl; controls {out}/controls/.",
             f"{lead} {witness_sentence(witness_name)}."]
    return "\n".join(lines) + "\n"


# --- controls --------------------------------------------------------------------------------

@dataclass
class Control:
    what: str
    text: str
    passed: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    slug: str = ""


def _any_directive(line: str) -> bool:
    return is_directive(line, "f90") or is_directive(line, "c")


def one_change(a: str, b: str) -> str | None:
    """What `b` changes in `a` when that is one thing: one line removed or
    changed; a block construct's directive and end directive both removed
    or both changed; a directive changed with an end directive added (a
    loop construct shortened to a block construct). None otherwise (also
    when equal)."""
    import difflib
    lang = "f90" if re.search(r"^\s*!\$", a, re.M) or not re.search(r"^\s*#\s*pragma", a, re.M) else "c"
    la, lb = logical_lines(a, lang), logical_lines(b, lang)     # a continued directive is one line
    gone, changed, added = [], [], []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, la, lb, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if tag == "delete":
            gone += la[i1:i2]
        elif tag == "insert":
            added += lb[j1:j2]
        else:
            n = min(i2 - i1, j2 - j1)
            changed += la[i1:i1 + n]
            gone += la[i1 + n:i2]
            added += lb[j1 + n:j2]
    touched = gone + changed
    if not touched or len(touched) > 2 or len(added) > 1:
        return None
    if len(touched) == 1 and not added:
        i = la.index(touched[0]) + 1
        return f"line {i} removed" if gone else f"line {i} changed"
    if not all(_any_directive(x) for x in touched + added):
        return None

    def is_end(line: str) -> bool:
        d = parse_directive(line, "f90") or parse_directive(line, "c")
        return d is not None and d.is_end
    if len(touched) == 2 and not added and not is_end(touched[0]) and is_end(touched[1]):
        return "directive pair removed" if len(gone) == 2 else "directive pair changed" if len(changed) == 2 \
            else None
    if len(changed) == 1 and not gone and len(added) == 1 and not is_end(changed[0]) and is_end(added[0]):
        return "directive changed and end directive added"
    return None


def control_candidates(text: str, lang: str) -> list[Candidate]:
    """One-change edits of the directives of a program (the steps marked
    ``controls``), distinct and different from it."""
    L = logical_lines(text, lang)
    base = render_lines(L, lang)
    ss = [s for s in STEPS if s.controls and s.applies(text, lang)]
    out, seen = [], {text, base}
    for s in sorted(ss, key=lambda s: (s.level, STEPS.index(s))):
        for c in s.fn(text, lang):
            if c.text in seen or one_change(base, c.text) is None:
                continue
            seen.add(c.text)
            out.append(c)
    return out


def _slug(what: str) -> str:
    w = re.sub(r"\s+at line \d+$", "", what)
    w = re.sub(r"[^A-Za-z0-9]+", "-", w).strip("-").lower()
    return w[:40].rstrip("-")


def controls(text: str, lang: str, judge: Judge, limit: int = 4, name: str = "reduce") -> list[Control]:
    """The one-change controls of a reduced program that are legal and
    pass on every target and verify target of the judge; at most `limit`,
    in step order (a clause, an item or a modifier first)."""
    out, used = [], set()
    for c in control_candidates(text, lang):
        slug = _slug(c.what)
        pid = f"{name}-{slug}-control"
        try:
            ok, why, passed, rows = judge.passes(c.text, pid)
        except BudgetExhausted as e:
            judge.log(str(e))
            break
        if ok:
            while slug in used:
                slug += "x"
            used.add(slug)
            out.append(Control(c.what, c.text, passed, rows, slug))
            judge.log(f"  control kept: {c.what} (passes on {', '.join(passed)})")
            if len(out) >= limit:
                break
        else:
            judge.log(f"  control rejected: {c.what}: {why}")
    return out


# --- rows in: a job from a recorded failure --------------------------------------------------

@dataclass
class Job:
    text: str
    lang: str
    targets: list
    signature: Signature | None
    origin: str
    notes: list = field(default_factory=list)


def lang_of(path: str) -> str:
    return "c" if str(path).endswith((".c", ".h")) else "f90"


def from_rows(paths, ident: str, root: Path = ROOT, program: Path | None = None,
              mode: int | None = None) -> Job:
    """The job of a recorded failing row: `ident` is a harness row's
    program id (or its file's stem), or the seed of a fuzz campaign record
    (results/fuzz/<run>/programs.jsonl). The program text comes from
    `program`, the row's ``file`` (relative to `root`), or the fuzz
    generator; the targets are the failing rows' (toolchain, mode); the
    signature is the most common one among them."""
    rows = R.load_jsonl([str(p) for p in paths])
    recs = [d for d in rows if "seed" in d and "results" in d and str(d["seed"]) == str(ident).split(":")[-1]]
    if recs:
        rec = recs[0]
        from offload.engine.fuzz import generate
        prog = generate(int(rec["seed"]), rec.get("gen_version") or "fuzz-1", tuple(rec.get("base") or ()))
        text = program.read_text() if program else prog.source
        m = mode if mode is not None else _mode_of_run(paths)
        found = failures_of_record(rec, m)
        if not found:
            raise NoFailure(f"seed {rec['seed']}: no failing toolchain in its record")
        sigs = Counter(s for _, s in found)
        top = sigs.most_common(1)[0][0]
        notes = [f"{t.label}: {s}" for t, s in found if s != top]
        return Job(text, "f90", [t for t, s in found if s == top], top,
                   f"fuzz seed {rec['seed']} ({rec.get('gen_version')}) in {Path(paths[0]).name}",
                   [f"another signature on {n}" for n in notes])
    mine = []
    for d in rows:
        d = R.normalize_row(d)
        pid = str(d.get("program_id") or d.get("ident") or "")
        stem = Path(str(d.get("file") or "")).stem
        if ident in (pid, stem) and d.get("toolchain"):
            mine.append(d)
    failing = [d for d in mine if is_failure(d)]
    if not failing:
        raise NoFailure(f"{ident}: no failing row in {', '.join(Path(str(p)).name for p in paths)}"
                        + (f" ({len(mine)} rows of it, none failing)" if mine else ""))
    if program is not None:
        text, lang = Path(program).read_text(), lang_of(program)
    else:
        f = next((d["file"] for d in failing if d.get("file")), None)
        if not f:
            raise NoFailure(f"{ident}: its rows name no file; pass --program")
        p = Path(f) if Path(f).is_absolute() else Path(root) / f
        text, lang = p.read_text(), lang_of(p)
    pairs = [(Target(d["toolchain"], int(d.get("xnack", 0)), str(d.get("opt") or "-O2")), signature(d))
             for d in failing]
    top = Counter(s for _, s in pairs).most_common(1)[0][0]
    targets = list(dict.fromkeys(t for t, s in pairs if s == top))
    notes = [f"{t.label} fails another way: {s}" for t, s in pairs if s != top]
    return Job(text, lang, targets, top, f"row {ident} in {', '.join(Path(str(p)).name for p in paths)}",
               notes)


def _mode_of_run(paths) -> int:
    for p in paths:
        meta = Path(str(p)).parent / "meta.json"
        if meta.is_file():
            try:
                d = json.loads(meta.read_text())
                sess = d.get("sessions") or [d]
                return int(sess[-1].get("xnack", 0))
            except (ValueError, KeyError, TypeError, IndexError):
                pass
    return 0


def from_seed(seed: int, gen_version: str = "fuzz-1", base=()) -> Job:
    """The job of a fuzz seed: the program regenerated; targets and the
    signature are the caller's (the first run on the target decides)."""
    from offload.engine.fuzz import generate
    prog = generate(seed, gen_version, tuple(base))
    return Job(prog.source, "f90", [], None, f"fuzz seed {seed} ({gen_version})",
               [f"model checksum {prog.expected}"])


def from_program(path: Path) -> Job:
    path = Path(path)
    return Job(path.read_text(), lang_of(path), [], None, str(path), [])
