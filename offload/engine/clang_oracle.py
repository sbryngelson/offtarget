"""Cross-check C programs and directives against AFAR amdclang's frontend
(the C analogue of ``offload.engine.flang_oracle``).

amdclang (ROCm/llvm-project, 24.0.0git, the AFAR drop under test) is an
OPINION, never the authority: the spec wins when the two disagree, and
``compare`` reports the disagreement instead of hiding it.

Invocation: ``amdclang -fopenmp -fopenmp-version=<52|60> -fsyntax-only``
on the whole C source (host-side semantic analysis of the OpenMP
directives; no device compilation, no code generation), and with
``-Xclang -ast-dump`` for the clause lists of each OpenMP directive
(``OMP<Name>Directive`` nodes and their ``OMP<Name>Clause`` children).
The OpenMP version flag is explicit for both versions (clang's default is
5.1 in this build's documentation; 5.2 syntax is diagnosed under it), so
a 5.2 program is checked as 5.2.
"""
from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from shlex import quote

from offload.engine.catalog import default_skeleton
from offload.engine.flang_oracle import Agreement, verdict_of  # noqa: F401
from offload.engine.grammar import GrammarError, parse_directive
from offload.engine.toolchains import TOOLCHAINS

_TC = TOOLCHAINS["afar"]
_TIMEOUT = 180


class ClangError(Exception):
    """clang could not be run (`stage` "run"), did not finish ("timeout":
    a frontend hang is a finding, e.g. requires device_safesync), or an AST
    clause node has no known spelling ("map")."""

    def __init__(self, stage: str, message: str):
        super().__init__(f"{stage}: {message}")
        self.stage = stage
        self.message = message


@dataclass(frozen=True)
class Check:
    ok: bool
    errors: tuple[str, ...]   # the "error:" lines (file name masked)
    output: str


def _run(source: str, version: int | None, extra: str = "") -> tuple[int,
                                                                       str,
                                                                       str]:
    from offload.engine.harness import _execute
    vflag = f" -fopenmp-version={version}" if version else ""
    with tempfile.TemporaryDirectory(prefix="clang_oracle_") as d:
        src = Path(d) / "t.c"
        src.write_text(source)
        script = (f"{_TC.prelude}\n" if _TC.prelude else "") + (
            f"{_TC.cc} -fopenmp{vflag} -fsyntax-only {extra} "
            f"{quote(str(src))}")
        # its own process group, killed at the timeout (a hanging clang
        # frontend must not outlive the call: found two hangs)
        res = _execute(script, Path(d), _TIMEOUT)
        if res.timed_out:
            raise ClangError("timeout", f"clang did not finish in "
                                        f"{_TIMEOUT}s")
        err = res.stderr.replace(str(src), "t.c")
    if res.rc != 0 and "error:" not in err:
        raise ClangError("run", f"rc={res.rc}: {err.strip()}")
    return res.rc, res.stdout, err


def syntax_check(source: str, version: int) -> Check:
    """amdclang's frontend verdict on a whole C program."""
    rc, _, err = _run(source, version)
    errors = tuple(ln.strip() for ln in err.splitlines()
                   if re.search(r"\berror:", ln))
    return Check(rc == 0, errors, err)


_DIRECTIVE = re.compile(r"^(?P<ind>[\s|`-]*)OMP(?P<name>\w+)Directive ")
_CLAUSE = re.compile(r"^(?P<ind>[\s|`-]*)OMP(?P<name>\w+)Clause ")
# AST clause node -> clause spelling where snake_casing the node name is not
# the spelling
CLAUSE_NODE_SPELLING = {"DeviceType": "device_type",
                        "Dynamic_allocators": "dynamic_allocators"}


def _spelling(node: str) -> str:
    sp = CLAUSE_NODE_SPELLING.get(node) or re.sub(
        r"(?<=[a-z0-9])(?=[A-Z])", "_", node).lower()
    if sp not in default_skeleton().clauses:
        raise ClangError("map", f"clang clause node {node!r} maps to {sp!r}, "
                                "which is not a catalog clause")
    return sp


def clang_clauses(source: str, version: int) -> list[list[str]]:
    """One clause list per OpenMP executable directive of the AST, in
    source order (declarative directives have other node kinds)."""
    rc, out, err = _run(source, version, "-Xclang -ast-dump")
    if rc != 0:
        raise ClangError("run", f"ast dump failed: {err.strip()[:400]}")
    groups: list[list[str]] = []
    depth = None
    for line in out.splitlines():
        m = _DIRECTIVE.match(line)
        if m:
            groups.append([])
            depth = len(m.group("ind"))
            continue
        m = _CLAUSE.match(line)
        if m and groups and depth is not None and \
                len(m.group("ind")) == depth + 2:
            groups[-1].append(_spelling(m.group("name")))
    return groups


# --- one directive -----------------------------------------------------------------

_STANDALONE = {"target enter data", "target exit data", "target update"}
_FILE_SCOPE = {"declare target", "requires", "begin declare target"}


def wrap_directive(text: str, version: int) -> str | None:
    """A minimal C program around one directive (``#pragma omp ...``): the
    declarations its list items may name (scalars x, y, s; arrays a, b of
    64 ints; pointer p), a structured block or a canonical for loop nest
    as its association needs; None for a directive this wrapper does not
    place."""
    from offload.engine.rules import association
    try:
        d = parse_directive(text, "c", version)
        key = d.name
    except GrammarError:
        m = re.match(r"^\s*#\s*pragma\s+omp\s+((?:\w+\s*)+)", text)
        key = None
        if m:
            words = m.group(1).split()
            for k in range(len(words), 0, -1):
                cand = " ".join(words[:k])
                if cand in default_skeleton().directives:
                    key = cand
                    break
        if key is None:
            return None
    decls = ["int x = 0, y = 0, s = 0, n = 64, i, j;", "int a[64], b[64];",
             "int *p = a;"]
    if key in _FILE_SCOPE:
        if key == "begin declare target":
            return (text + "\nint g;\n#pragma omp end declare target\n"
                    "int main(void) { return g; }\n")
        return ("int x = 0, y = 0;\nint f(int v) { return v; }\n" + text
                + "\nint main(void) { return x; }\n")
    how = association(key)
    body = ["int main(void) {"] + ["  " + x for x in decls]
    if how == "loop":
        n = 1
        m = re.search(r"\bcollapse\s*\(\s*(\d+)", text)
        if m:
            n = int(m.group(1))
        body.append("  " + text)
        for k in range(n):
            v = "ij"[k] if k < 2 else f"k{k}"
            body.append("  " * (k + 1) + f"for ({'int ' if k > 1 else ''}"
                        f"{v} = 0; {v} < 8; {v}++)")
        body.append("  " * (n + 1) + "b[0] = a[0];")
    elif how in ("block", "statement"):
        body += ["  " + text, "  {", "    b[0] = a[0];", "  }"]
    elif key in _STANDALONE or how == "standalone":
        body.append("  " + text)
    else:
        return None
    body += ["  return 0;", "}"]
    return "\n".join(body) + "\n"


def compare(directive_text: str, version: int) -> Agreement:
    """Do the spec grammar and amdclang agree about one ``#pragma omp``
    directive? (``Agreement`` of offload.engine.flang_oracle; flang_* fields
    hold clang's answer.)"""
    try:
        d = parse_directive(directive_text, "c", version)
        grammar_ok, mine, gnote = True, sorted(c.name for c in d.clauses), ""
    except GrammarError as e:
        grammar_ok, mine, gnote = False, None, str(e)
    src = wrap_directive(directive_text, version)
    if src is None:
        return Agreement(grammar_ok, False, None,
                         note=f"no wrapper for this directive; clang not "
                              f"consulted. {gnote}".strip(),
                         consulted=False, flang_stage="skipped")
    chk = syntax_check(src, version)
    theirs = None
    if chk.ok:
        try:
            theirs = clang_clauses(src, version)
        except ClangError as e:
            if e.stage == "map":
                raise
    same = None
    if mine is not None and theirs is not None and theirs:
        same = sorted(c for g in theirs[:1] for c in g) == mine
    return Agreement(grammar_ok, chk.ok, same,
                     "; ".join(chk.errors) if not chk.ok else None, gnote,
                     True, "ok" if chk.ok else "semantics")
