"""Helpers for tests/cluster/test_standing_rules.py: the maintainer's standing rules
(docs/tooling/contributing.md lists them, with which ones a test can hold) as
scans over the repository, and the ratchet that lets a rule start with the
violations that already exist.

The ratchet (catalog/standing_rules_baseline.yaml): one entry per rule and
offender, each with a reason. A rule's test fails

* on an offender that is not in the baseline (a new violation: fix it, do
  not add it to the baseline), and
* on a baseline entry that is no longer an offender (it was fixed: remove
  the entry), so the baseline only shrinks.

An offender is a stable string, usually a repository path.
"""
from __future__ import annotations

import ast
import io
import os
import re
import tokenize
from pathlib import Path
from typing import NamedTuple

import yaml

ROOT = Path(__file__).resolve().parent.parent
BASELINE_FILE = ROOT / "catalog" / "standing_rules_baseline.yaml"

# directories no scan descends into: measurements and clones (git-ignored),
# caches, and the sealed benchmark sets (data/bench/: never read, constraints.md)
PRUNE = {"__pycache__", ".git", "results", "corpus", "spec", "bench",
         ".superpowers", "node_modules", ".pytest_cache", "results-compact",
         "results-site"}


class Rule(NamedTuple):
    id: str
    text: str     # the rule, as docs/tooling/contributing.md states it
    fix: str      # what to do about an offender


RULES: dict[str, Rule] = {r.id: r for r in (
    Rule("no-gcc-witness",
         "never gfortran or gcc -fopenmp/-fopenacc as a legality witness "
         "(GCC is a compiler under test only)",
         "judge legality with the rules (offload.engine.rules) and a front end "
         "of another family; name GCC in a legality line only to say it is "
         "no witness"),
    Rule("no-own-checker",
         "a compiler under test is never its own legality checker",
         "use a checker of another compiler family (catalog/machines.yaml "
         "independent_checkers; AFAR and upstream llvm share a front end)"),
    Rule("no-ompvv-oracle",
         "omp_vv is untrusted: never a legality witness or an oracle",
         "omp_vv failures stay needs_human (rulings.yaml RUL-OMPVV-UNTRUSTED)"),
    Rule("pdebug-batch",
         "batch work goes to pbatch; pdebug is interactive only",
         "show `flux batch -q pbatch` (or a foreground `flux run -q pdebug "
         "--job-name=compile-...` for a short attended run)"),
    Rule("pdebug-job-name",
         "a pdebug job carries a compile-like --job-name",
         "add --job-name=compile-<what> to the flux run/alloc"),
    Rule("pdebug-chained",
         "pdebug jobs are never chained: one foreground job at a time",
         "run one job, read the answer, then start the next by hand"),
    Rule("no-module-pipe",
         "no `module load ... |`: the pipe runs it in a subshell and the "
         "environment is lost",
         "run `module load` on its own line, then pipe the command"),
    Rule("no-shared-tree-git",
         "never git stash/checkout/restore/reset/clean in the shared tree",
         "work in your own worktree and give git an explicit -C <your tree>"),
    Rule("no-external-filing",
         "never file, report or post anything externally",
         "write a draft under docs/ or results/; the maintainer files it"),
    Rule("bounded-waits",
         "every wait is bounded",
         "give the loop a deadline (date +%s, $SECONDS) or run it under "
         "timeout"),
    Rule("wingtip-cap",
         "wingtip scripts go through the cap scripts and the cap is never "
         "softened",
         "source wingtip_cap.sh with `|| exit 1` (tools/jobs/wingtip_cap.sh is "
         "the one copy)"),
    Rule("gate-c-other-node",
         "the gate's environment (c) runs on another node (wingtip: GPU) "
         "than (a)",
         "rerun (c) on a node (GPU) that no (a), (b) or (d) rerun used"),
    Rule("no-first-person",
         "no first person (we, our, us, I, my) in site copy",
         "write it impersonally: \"appears to behave incorrectly\""),
    Rule("site-cell-words",
         "cell words are exactly: behaves incorrectly, not supported, "
         "correct, unknown, n/a, fails another way",
         "use the maintainer's words in tools/site/site_build.py STATE_WORD"),
    Rule("no-tracked-symlink",
         "no tracked symlink at the repository root or with an absolute target "
         "(a worktree's results, spec and corpus links must never be committed: "
         "merging them replaces the shared directories)",
         "remove the link from the index and ignore it in .gitignore as /name "
         "(no trailing slash: that pattern matches directories only)"),
    Rule("no-ai-attribution",
         "no AI attribution lines in git commit messages",
         "amend the message before it leaves your branch"),
)}


# --- the baseline ----------------------------------------------------------

def load_baseline(path: Path = BASELINE_FILE) -> list[dict]:
    if not Path(path).is_file():
        return []
    data = yaml.safe_load(Path(path).read_text()) or {}
    return list(data.get("entries") or [])


def baseline_of(rule: str, path: Path = BASELINE_FILE) -> dict[str, str]:
    return {e["offender"]: e.get("reason", "")
            for e in load_baseline(path) if e.get("rule") == rule}


def ratchet(rule: str, found: dict[str, str],
            path: Path = BASELINE_FILE) -> None:
    """Fail unless the offenders (offender -> evidence) are exactly the
    baseline's entries for `rule`."""
    r = RULES[rule]
    base = baseline_of(rule, path)
    new = sorted(set(found) - set(base))
    gone = sorted(set(base) - set(found))
    msg = []
    if new:
        msg.append(f"standing rule [{rule}] \"{r.text}\" is broken by "
                   f"{len(new)} new offender(s):")
        msg += [f"  {o}  <- {found[o]}" for o in new[:200]]
        if len(new) > 200:
            msg.append(f"  ... and {len(new) - 200} more")
        msg.append(f"  fix: {r.fix}. Do not add it to "
                   "catalog/standing_rules_baseline.yaml.")
    if gone:
        msg.append(f"standing rule [{rule}]: {len(gone)} baseline entr"
                   f"{'y is' if len(gone) == 1 else 'ies are'} fixed; "
                   "remove from catalog/standing_rules_baseline.yaml:")
        msg += [f"  {o}" for o in gone[:40]]
    assert not msg, "\n" + "\n".join(msg)


# --- files -------------------------------------------------------------------

def rel(p: Path | str) -> str:
    """The path relative to the repository (a path outside it is returned
    as it is)."""
    try:
        return Path(p).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return Path(p).as_posix()


def walk(*roots: str, suffixes: tuple[str, ...] = (),
         top_only: bool = False) -> list[Path]:
    """Files below the given repository directories (sorted), with the
    pruned directories skipped (also as a root: data/bench/ is never walked)."""
    out = []
    for root in roots:
        base = ROOT / root
        if not base.is_dir() or PRUNE & set(Path(root).parts):
            continue
        for d, dirs, files in os.walk(base):
            dirs[:] = sorted(x for x in dirs if x not in PRUNE)
            for f in sorted(files):
                if not suffixes or f.endswith(suffixes):
                    out.append(Path(d) / f)
            if top_only:
                break
    return out


def shell_files() -> list[Path]:
    return walk("tools", "data/vendor/checks", suffixes=(".sh",))


def python_files() -> list[Path]:
    return walk("tools", "offload", "data/vendor/checks",
                suffixes=(".py",))


def doc_files() -> list[Path]:
    """The how-to documents: docs/*.md, data/findings/*.md and the vendor
    packet's markdown. The review reports (reports) and the dated plans
    and specs are history, not instructions."""
    return (walk("docs", suffixes=(".md",), top_only=True)
            + walk("data/findings", suffixes=(".md",), top_only=True)
            + walk("data/vendor", suffixes=(".md",)))


class Line(NamedTuple):
    path: str
    no: int
    text: str
    kind: str        # code | comment | string | doc
    block: int       # id of the fenced block (markdown), else 0


def _join(raw: list[tuple[int, str, str, int]]) -> list[Line]:
    """Join backslash continuations of consecutive lines of one kind."""
    out, cur = [], None
    for no, text, kind, block in raw:
        if cur and cur[2] == kind and cur[3] == block and \
                cur[1].endswith("\\"):
            cur = (cur[0], cur[1][:-1].rstrip() + " " + text.strip(), kind,
                   block)
            continue
        if cur:
            out.append(cur)
        cur = (no, text, kind, block)
    if cur:
        out.append(cur)
    return [Line("", no, t, k, b) for no, t, k, b in out]


def lines_of(path: Path) -> list[Line]:
    """The logical lines of a file with their kind: a shell script's code
    and comments (comment markers removed, so a usage example reads like the
    command), a Python file's string constants and comments, a markdown
    file's lines (block = the fenced block they are in)."""
    p = Path(path)
    r = rel(p)
    text = p.read_text(errors="replace")
    raw: list[tuple[int, str, str, int]] = []
    if p.suffix == ".sh":
        for n, ln in enumerate(text.splitlines(), 1):
            s = ln.strip()
            if not s:
                continue
            if s.startswith("#"):
                raw.append((n, s.lstrip("#").strip(), "comment", 0))
            else:
                raw.append((n, s, "code", 0))
    elif p.suffix == ".py":
        try:
            tree = ast.parse(text)
        except SyntaxError:
            tree = None
        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    for k, ln in enumerate(node.value.splitlines()):
                        raw.append((node.lineno + k, ln.strip(), "string", 0))
        try:
            for tok in tokenize.generate_tokens(io.StringIO(text).readline):
                if tok.type == tokenize.COMMENT:
                    raw.append((tok.start[0], tok.string.lstrip("#").strip(),
                                "comment", 0))
        except (tokenize.TokenError, IndentationError):
            pass
        raw.sort(key=lambda x: x[0])
    elif p.suffix == ".md":
        block, fence = 0, False
        for n, ln in enumerate(text.splitlines(), 1):
            if ln.lstrip().startswith("```"):
                fence = not fence
                block = n if fence else 0
                continue
            raw.append((n, ln.strip(), "doc", block))
    return [ln._replace(path=r) for ln in _join(raw)]


# --- the flux queue rules -----------------------------------------------------

FLUX = re.compile(r"\bflux\s+(batch|submit|bulksubmit|run|alloc)\b")
PDEBUG = re.compile(r"(?:-q\s*|--queue[=\s])pdebug\b")
SEGMENT_END = re.compile(r"&&|\|\||;|\||`|\s&(?:\s|$)")


def flux_calls(text: str) -> list[tuple[str, str]]:
    """(subcommand, the call's text up to the next &&, ;, | or backtick) for every `flux <sub>` in a line."""
    out = []
    for m in FLUX.finditer(text):
        rest = text[m.start():]
        end = SEGMENT_END.search(rest, m.end() - m.start())
        out.append((m.group(1), rest[: end.start() if end else None]))
    return out


def pdebug_calls(text: str) -> list[tuple[str, str]]:
    return [(s, c) for s, c in flux_calls(text) if PDEBUG.search(c)]


JOB_NAME = re.compile(r"--job-name[=\s]compile")


# --- Python call lists (subprocess.run(["git", ...])) -------------------------

def const_list(node: ast.AST) -> list[str] | None:
    """A list/tuple literal as strings: constants as they are, anything else
    as its source text; None when the node is not a list or tuple."""
    if not isinstance(node, (ast.List, ast.Tuple)):
        return None
    return [e.value if isinstance(e, ast.Constant) and isinstance(e.value, str)
            else ast.unparse(e) for e in node.elts]


def command_lists(path: Path):
    """(line, argv, cwd) for every list literal in a Python file that starts
    like a command (a first element that is a string), with the cwd= of the
    call it is an argument of (source text, or None)."""
    try:
        tree = ast.parse(Path(path).read_text(errors="replace"))
    except SyntaxError:
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            cwd = next((ast.unparse(k.value) for k in node.keywords
                        if k.arg == "cwd"), None)
            for a in node.args:
                argv = const_list(a)
                if argv:
                    yield a.lineno, argv, cwd
