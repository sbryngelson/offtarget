"""Cross-check the grammar against AFAR amdflang's OpenMP parse tree.

amdflang (ROCm/llvm-project, 24.0.0git) is an OPINION, never the authority:
the spec wins when the two disagree, and `compare` reports the disagreement
instead of hiding it.

Invocation.  The driver form `amdflang -fopenmp -Xflang -fdebug-dump-parse-tree`
fails on this build ("only one action option is allowed. Got '-emit-obj',
'-fdebug-dump-parse-tree'") and `-fsyntax-only` clashes the same way, so the
dump is requested from the frontend directly: `amdflang -fc1 -fopenmp
-fdebug-dump-parse-tree` (the dump is itself the action).  `-fopenmp-version=NN`
is accepted and honoured by semantic checking (e.g. WORKDISTRIBUTE is rejected
at 52 and accepted at 60); parsing itself is version independent.
"""
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from shlex import quote

from offload.engine.catalog import (base_name, default_skeleton,
                                slice_directives)
from offload.engine.grammar import GrammarError, parse_directive
from offload.engine.toolchains import TOOLCHAINS

_TC = TOOLCHAINS["afar"]
_TIMEOUT = 180


class FlangError(Exception):
    """flang did not produce a usable parse tree. `stage` is "parse" (the
    prescanner or the parser rejected the source), "semantics", "run" (the
    tool itself could not be run) or "map" (a dump clause node with no known
    spelling)."""

    def __init__(self, stage: str, message: str):
        super().__init__(f"{stage}: {message}")
        self.stage = stage
        self.message = message


def verdict_of(grammar_ok: bool, consulted: bool, flang_ok: bool,
               same_clauses: bool | None) -> str:
    """The one-word triage label for a comparison (pure, flang-free)."""
    if not consulted:
        return "not_consulted"
    if grammar_ok and flang_ok:
        return "agree" if same_clauses else "clauses_differ"
    if grammar_ok:
        return "grammar_only"   # spec grammar accepts, flang rejects
    return "flang_only" if flang_ok else "both_reject"


@dataclass(frozen=True)
class Agreement:
    """`flang_ok` is meaningful only when `consulted`; read `verdict`.

    flang_stage: "ok" | "parse" | "semantics" | "skipped" (not consulted).
    same_clauses is None when either side produced no clause list."""
    grammar_ok: bool
    flang_ok: bool
    same_clauses: bool | None
    flang_error: str | None = None  # flang's diagnostic when it said no
    note: str = ""                  # e.g. "no wrapper" or a grammar error
    consulted: bool = True
    flang_stage: str = "skipped"

    @property
    def verdict(self) -> str:
        return verdict_of(self.grammar_ok, self.consulted, self.flang_ok,
                          self.same_clauses)


# --- parse-tree node name -> spec clause spelling -----------------------------

# amdflang names a clause node `OmpClause -> CamelCase`; snake_casing it gives
# the spec spelling (UseDeviceAddr -> use_device_addr). Nodes for which that
# is not true go here (none found so far). A node whose spelling is not a
# known catalog clause raises instead of being passed through.
CLAUSE_NODE_SPELLING: dict[str, str] = {}


def _known_clauses() -> frozenset[str]:
    return frozenset(default_skeleton().clauses)


def _spelling(node: str) -> str:
    spelling = CLAUSE_NODE_SPELLING.get(node) or re.sub(
        r"(?<=[a-z0-9])(?=[A-Z])", "_", node).lower()
    if spelling not in _known_clauses():
        raise FlangError("map", f"flang clause node {node!r} maps to "
                                f"{spelling!r}, which is not a catalog clause")
    return spelling


# --- running flang --------------------------------------------------------------

# The host module directory of the AFAR install: `-fc1` does not add it, so
# a program that uses omp_lib needs `-fintrinsic-modules-path` (the driver
# passes the same directory; checks whole programs).
MODULE_FLAGS = ("-fintrinsic-modules-path " + quote(
    str(Path(_TC.fc).parent.parent / "lib/llvm/lib/clang/24/finclude/flang"
        / "x86_64-unknown-linux-gnu")))


def _dump(source: str, version: int | None, sema: bool,
          extra_flags: str = "") -> str:
    flag = "-fdebug-dump-parse-tree" + ("" if sema else "-no-sema")
    vflag = f" -fopenmp-version={version}" if version else ""
    if extra_flags:
        vflag += " " + extra_flags
    with tempfile.TemporaryDirectory(prefix="flang_oracle_") as d:
        src = Path(d) / "t.f90"  # free-form only
        src.write_text(source)
        script = (f"{_TC.prelude}\n" if _TC.prelude else "") + (
            f"{_TC.fc} -fc1 -fopenmp{vflag} {flag} {quote(str(src))}")
        # its own process group, killed whole on a timeout: the prelude's
        # subshell leaves flang a grandchild that a plain kill of bash
        # would orphan (hung sample checks); through
        # harness._execute, whose watchdog also ends
        # the group when this process dies or stops
        from offload.engine.harness import _execute
        ex = _execute(f"( {script}\n)", Path(d), _TIMEOUT)
        if ex.timed_out:
            raise FlangError("run", f"flang timed out after {_TIMEOUT}s")
        res = subprocess.CompletedProcess(script, ex.rc, ex.stdout,
                                          ex.stderr)
    if res.returncode == 0:
        return res.stdout
    err = res.stderr.replace(str(src), src.name).strip()
    if "Could not parse" in err or "Could not scan" in err:
        raise FlangError("parse", err)  # scanning is the parser's first step
    if "Semantic errors" in err:
        raise FlangError("semantics", err)
    raise FlangError("run", f"rc={res.returncode}: {err}")


_DIRECTIVE_NAME = re.compile(r"OmpDirectiveName -> ")
_CLAUSE = re.compile(r"OmpClause -> (\w+)")


def _clauses_from_dump(dump: str) -> list[list[str]]:
    """One clause list per directive, in source order. Each directive starts
    at an `OmpDirectiveName` line; an end directive without clauses (the
    usual case) adds nothing."""
    groups: list[tuple[bool, list[str]]] = []  # (is_end_directive, clauses)
    in_end = False
    for raw in dump.splitlines():
        line = raw.lstrip("| ")
        if line == "OmpEndDirective":
            in_end = True
        elif line == "OmpBeginDirective" or line.endswith("OmpDirectiveSpecification"):
            in_end = False
        if _DIRECTIVE_NAME.match(line):
            groups.append((in_end, []))
        m = _CLAUSE.search(line)
        if m and groups:
            groups[-1][1].append(_spelling(m.group(1)))
    return [cl for is_end, cl in groups if cl or not is_end]


def flang_clauses(source: str, version: int | None = None,
                  sema: bool = True) -> list[list[str]]:
    """Clause spellings per OpenMP directive in `source`, in source order.

    `sema=False` uses the dump taken before semantic checking, which still
    works when semantic checks reject the program."""
    return _clauses_from_dump(_dump(source, version, sema))


# --- wrapping a bare directive in a minimal valid program -------------------------

# NB: `use omp_lib` would need an include path under -fc1 if a wrapper
# ever needs it.
_DECLS = ("  integer :: i, j, k, l, m, n, dev\n"
          "  real :: a(10,10), b(10,10), c(10,10), x(10,10), y(10,10), "
          "z(10,10), s\n")
_LOOP_VARS = "ijklm"
_STANDALONE = {"target enter data", "target exit data", "target update"}
_SPECIFICATION = {"declare target", "requires"}
_LOOP_LAST = {"do", "simd", "loop", "distribute"}


def _spec_for(text: str, version: int):
    """(key, DirectiveSpec) for the longest directive name leading `text`."""
    sk = default_skeleton()
    body = re.sub(r"^\s*!\$omp\s+", "", text, flags=re.I)
    words = re.match(r"[a-z_ ]*", body.lower()).group().split()
    for n in range(len(words), 0, -1):
        # a spelling may use spaces or underscores ("target data" up to 5.2,
        # "target_data" from 6.0); the Fortran grammar accepts both
        found = {sk.key_of(spec) for sep in (" ", "_")
                 for spec in sk.lookup_all(sep.join(words[:n]), version)}
        if len(found) > 1:
            break  # ambiguous: do not fall back to a shorter name
        if found:
            key = found.pop()
            return key, sk.directive(key)
    return None, None


def _declaration_associated(text: str) -> bool:
    """A declare target with no extended list and no enter, link, local or
    to clause (bare, or with only device_type / indirect)."""
    rest = re.sub(r"(?i)^\s*!\$omp\s+declare[ _]target", "", text)
    return not rest.lstrip().startswith("(") and not re.search(
        r"(?i)\b(?:enter|link|local|to)\s*\(", rest)


def _nest_depth(text: str) -> int:
    nums = [int(n) for n in re.findall(r"\b(?:collapse|ordered)\s*\(\s*(\d+)",
                                       text, flags=re.I)]
    return max(nums or [1])


def wrap_directive(text: str, version: int) -> str | None:
    """A minimal free-form program around one bare directive, or None when
    no wrapper is known (the caller must say so, not guess)."""
    key, spec = _spec_for(text, version)
    if key is None or key not in slice_directives(default_skeleton()):
        return None
    name = base_name(key)
    last = name.split()[-1]
    directive = text.strip()
    depth = _nest_depth(text)
    if depth > len(_LOOP_VARS):
        return None
    body = ""
    end = ""
    if name in _STANDALONE:
        body = f"  {directive}\n"
    elif name == "declare target" and _declaration_associated(directive):
        # with neither an extended list nor a list clause the directive is
        # declaration-associated (6.0 §9.9.1) and must sit in a subprogram's
        # specification part (5.2 §7.8.1, 6.0 §9.9.1, Fortran); in the main
        # program flang rejects it (a wrapper artifact otherwise)
        return (f"subroutine wrap_sub()\n{_DECLS}  {directive}\nend subroutine\n")
    elif name in _SPECIFICATION:
        return (f"program p\n{_DECLS}  {directive}\nend program\n")
    elif last == "workdistribute":
        body = f"  {directive}\n  a = b + c\n"
        end = f"  !$omp end {name}\n"
    elif spec.association == "LoopNest" or (
            spec.association == "FromLeaves" and last in _LOOP_LAST):
        loops = "".join(
            f"{'  ' * (d + 1)}do {_LOOP_VARS[d]} = 1, 10\n"
            for d in range(depth))
        inner = f"{'  ' * (depth + 1)}a(1,1) = b(1,1) + s\n"
        closes = "".join(f"{'  ' * d}end do\n" for d in range(depth, 0, -1))
        body = f"  {directive}\n{loops}{inner}{closes}"
        # the end directive of a loop construct is optional; omitted
    elif spec.association in ("Block", "FromLeaves"):
        body = f"  {directive}\n  a(1,1) = b(1,1)\n"
        end = f"  !$omp end {name}\n"
    else:
        return None
    return f"program p\n{_DECLS}{body}{end}end program\n"


# --- comparing the grammar with flang -----------------------------------------------

def compare(directive_text: str, version: int) -> Agreement:
    """Do the spec grammar and amdflang agree about one bare directive?

    flang_ok means flang parsed AND semantically accepted the wrapped program.
    A semantic rejection of a program the spec grammar accepts is a
    disagreement to report (the wrapper keeps everything else valid)."""
    try:
        d = parse_directive(directive_text, "fortran", version)
        grammar_ok, mine, gnote = True, sorted(c.name for c in d.clauses), ""
    except GrammarError as e:
        grammar_ok, mine, gnote = False, None, str(e)
    src = wrap_directive(directive_text, version)
    if src is None:
        return Agreement(grammar_ok, False, None,
                         note=f"no wrapper for this directive; flang not "
                              f"consulted. {gnote}".strip(),
                         consulted=False, flang_stage="skipped")
    stage, ferr = "ok", None
    try:
        theirs = flang_clauses(src, version)
    except FlangError as e:
        if e.stage in ("run", "map"):
            raise
        stage, ferr, theirs = e.stage, e.message, None
        if e.stage == "semantics":
            try:
                theirs = flang_clauses(src, version, sema=False)
            except FlangError as e2:
                if e2.stage == "map":
                    raise
    same = None
    if mine is not None and theirs is not None:
        # the wrapped program has exactly one OpenMP directive group with
        # clauses; compare as sorted multisets (order is not semantics)
        same = sorted(c for g in theirs for c in g) == mine
    return Agreement(grammar_ok, stage == "ok", same, ferr, gnote,
                     True, stage)
