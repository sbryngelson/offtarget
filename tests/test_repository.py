"""Tests of the repository itself: READMEs, documented commands and paths, module docstrings, working vocabulary, tools/ references, the top-level layout and the data root."""


# ---- Every directory a visitor can open from the top has a README that says what it is -------------------

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIRS = ["offload", "offload/engine", "tools", "tools/lanes", "tools/campaigns", "tools/derive", "tools/site",
        "tools/repo", "tools/jobs", "tools/dataenv", "tools/wild", "data/evidence", "data", "data/bench",
        "data/findings", "data/index", "data/licenses", "data/reports", "data/vendor", "catalog", "site", "tests", "docs"]


def test_each_listed_directory_has_a_readme_and_is_tracked():
    tracked = set(subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split())
    missing = [d for d in DIRS if f"{d}/README.md" not in tracked]
    assert not missing, missing


def test_the_top_level_names_are_all_described_in_the_docs_index():
    index = (ROOT / "docs" / "README.md").read_text() + (ROOT / "docs" / "maintainers.md").read_text()
    for top in ("offload", "tools", "data", "catalog", "site", "tests", "docs"):
        assert f"`{top}/`" in index, top


# ---- The README and the four pages name only commands, options and paths that exist ----------------------

import os
import re
import sys

import pytest

PAGES = [ROOT / "README.md"] + [ROOT / "docs" / n for n in ("how-it-works.md", "usage.md", "maintainers.md", "scope.md")]
TOOLING = sorted((ROOT / "docs" / "tooling").glob("*.md"))
ENV = {**os.environ, "PYTHONPATH": str(ROOT)}
ROOTS = ("offload/", "offload/engine/", "docs/", "data/findings/", "data/vendor/", "data/reports/", "catalog/", "site/", "tests/", "tools/", "data/bench/", "data/index/", "data/licenses/", ".github/")
TEMPLATE = re.compile(r"[\[\]|]|\.\.\.|\b[A-Z_]{3,}\b")


def _fenced_lines(path):
    inside = False
    for line in path.read_text().splitlines():
        if line.startswith("```"):
            inside = not inside
        elif inside:
            yield line.strip()


def _commands():
    out = []
    for p in PAGES:
        lines = list(_fenced_lines(p))
        for n, l in enumerate(lines):
            if l.startswith("offload "):
                cmd = l
                while n + 1 < len(lines) and lines[n + 1].startswith(("-", "[")) and not lines[n + 1].startswith("offload "):
                    n += 1
                    cmd += " " + lines[n]
                out.append((p.name, cmd))
    return out


@pytest.fixture(scope="module")
def _data_ready(offload_bundle):
    """The commands below read the data cache; the bundle build fills it, so they wait for it, not rebuild it."""


def _run(args):
    return subprocess.run([sys.executable, "-m", "offload", *args], cwd=ROOT, capture_output=True, text=True, env=ENV)


def test_readme_is_one_screen():
    assert len((ROOT / "README.md").read_text().splitlines()) <= 60


def test_every_page_exists():
    assert all(p.is_file() for p in PAGES)


@pytest.mark.parametrize("page,cmd", [c for c in _commands() if not TEMPLATE.search(c[1])])
def test_every_offload_command_in_the_docs_runs(page, cmd, _data_ready):
    r = _run(cmd.split()[1:])
    assert r.returncode in (0, 1), (page, cmd, r.stderr[-300:])


def test_every_usage_line_names_a_real_command_and_real_options():
    seen = 0
    for page, cmd in _commands():
        if not TEMPLATE.search(cmd):
            continue
        words = cmd.split()
        help_text = _run([words[1], "--help"]).stdout
        assert help_text, (page, cmd)
        for flag in re.findall(r"(?<![\w-])--[a-z][\w-]*", cmd):
            assert flag in help_text, (page, flag, words[1])
        seen += 1
    assert seen >= 2


def test_every_path_in_the_docs_exists():
    skip = ("results", "corpus", ".offload-cache", "spec")
    missing = []
    for p in PAGES + TOOLING:
        for tok in re.findall(r"`([^`\s]+)`", p.read_text()):
            tok = tok.split("::")[0]
            if "holdout" in tok or tok == "catalog/local.yaml":
                continue                 # sealed sets are not copied to every checkout; local.yaml is each user's own
            if "<" in tok or "{" in tok:
                continue
            if "/" not in tok or not tok.startswith(ROOTS) or "*" in tok or tok.startswith(skip) or TEMPLATE.search(tok.split("/")[0]) \
                    or re.search(r"[A-Z_]{3,}", tok) or tok.startswith(("http", "-")):
                continue
            if not (ROOT / tok.rstrip("/")).exists() and not (ROOT / "docs" / tok).exists():
                missing.append((p.name, tok))
    assert not missing, missing


# ---- Module docstrings stay short: what it does, how to call it, what it reads and writes ----------------


sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]

import docstring_report as D  # noqa: E402


def test_module_docstrings_are_short():
    too_long = [f"{f} ({n} lines)" for f, n in D.offenders(ROOT) if f not in D.allowed()]
    assert not too_long, too_long[:10]


def test_the_allowlist_names_only_modules_that_still_need_it():
    still = {f for f, _ in D.offenders(ROOT)}
    stale = sorted(D.allowed() - still)
    assert not stale, stale[:10]


# ---- No tracked file outside the frozen data and the historical notes carries the project's working vocabulary ----

import fnmatch


import scrub_vocab as SV  # noqa: E402

# frozen inputs (benchmark programs, sealed sets, pinned models), the notes, and the files that teach the scrubber
EXEMPT = SV.EXEMPT + ("", "docs/superpowers/*", "tests/site/test_site_inputs.py")
# a few files whose strings are written into committed seals keep the original words
KEEP = SV.STRING_EXEMPT
SUFFIXES = SV.SUFFIXES + (".json", ".js", ".mjs", ".toml", ".ini", ".cfg")


def _tracked():
    return subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.splitlines()


def test_no_tracked_file_outside_the_exemptions_carries_the_vocabulary():
    bad = {}
    for p in _tracked():
        if not p.endswith(SUFFIXES) or any(fnmatch.fnmatchcase(p, e) for e in EXEMPT) or p in KEEP:
            continue
        f = ROOT / p
        if not f.is_file() or f.stat().st_size > 5_000_000:
            continue
        try:
            hits = SV.residue(f.read_text())
        except UnicodeDecodeError:
            continue
        if hits:
            bad[p] = sorted(set(hits))[:3]
    assert not bad, f"{len(bad)} files, e.g. {list(bad.items())[:6]}"


# ---- Tracked text files name no tools/ file that does not exist ------------------------------------------




ALLOW = ROOT / "tools" / "repo" / "path_allowlist.txt"
HISTORY = ("data/reports/", "data/findings/")       # run logs and studies name the scripts that produced them
SELF = ("tools/repo/path_allowlist.txt", "tests/site/test_site_inputs.py")   # their text is scrub input
MAX_BYTES = 3_000_000
_REF = re.compile(r"tools/[\w.\-/]+\.(?:py|sh|yaml|yml|md|json|txt|csv|f90|c|mjs)\b")


def _tracked_text():
    for p in subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.splitlines():
        f = ROOT / p
        if p.startswith("data/bench/") and not p.endswith(".md") or "-holdout/" in p or p in SELF or p.startswith(HISTORY):
            continue
        if f.is_file() and f.stat().st_size <= MAX_BYTES:
            try:
                yield p, f.read_text()
            except UnicodeDecodeError:
                continue


def _allowed() -> set[tuple[str, str]]:
    pairs = (l.split("\t") for l in ALLOW.read_text().splitlines() if l.strip() and not l.startswith("#"))
    return {(a, b) for a, b in pairs}


def test_every_maintainers_path_in_a_tracked_text_file_exists_or_is_listed_as_historical():
    bad = []
    for p, t in _tracked_text():
        for ref in sorted({m.group(0) for m in _REF.finditer(t)}):
            if not (ROOT / ref).is_file() and (p, ref) not in _allowed():
                bad.append((p, ref))
    assert not bad, bad[:8]


# ---- What a visitor sees at the top of the repository, and nothing heavy outside the data directories ----


ALLOWED = {"README.md", "CONTRIBUTING.md", "CLAUDE.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "pyproject.toml", "setup.py", "pytest.ini", ".gitignore",
           ".github", "offload", "docs", "catalog", "data", "site", "tests", "tools", "corpus"}
DATA = ("catalog/", "data/")




def test_top_level_entries_are_the_allowed_list():
    top = {p.split("/")[0] for p in _tracked()}
    assert top <= ALLOWED, sorted(top - ALLOWED)


def test_no_large_non_data_files():
    big = [p for p in _tracked() if not p.startswith(DATA) and (ROOT / p).is_file() and (ROOT / p).stat().st_size > 1_000_000]
    assert not big, big


# ---- offload.engine.root: one place decides where the data lives -----------------------------------------

import ast
import json


CLOSURE_CODE = f"""
import contextlib, importlib.util, io, json, sys
import offload.cli, offload.canuse, offload.issues
for args in ((offload.canuse, ["clause.map.present"]), (offload.issues, ["--show", "nvhpc-c-map-present-ignored"])):
    with contextlib.redirect_stdout(io.StringIO()):
        args[0].main(args[1])
print(json.dumps({{n: getattr(m, "__file__", None) for n, m in sys.modules.items()
                  if n == "offload.engine" or n.startswith("offload.engine.")}}))
"""


def _env(**extra):
    return {"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin", **extra}


def _closure() -> dict[str, str]:
    r = subprocess.run([sys.executable, "-c", CLOSURE_CODE], cwd=ROOT, capture_output=True, text=True,
                       env=_env())
    assert r.returncode == 0, r.stderr
    return {n: f for n, f in json.loads(r.stdout.splitlines()[-1]).items() if f}


def _own_root_lines(path: str) -> list[int]:
    tree = ast.parse(Path(path).read_text())
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "ROOT" for t in node.targets):
            lines.append(node.lineno)
        if isinstance(node, ast.Name) and node.id == "__file__":
            lines.append(node.lineno)
    return lines


def test_import_closure_uses_the_shared_root():
    bad = {}
    for name, f in _closure().items():
        if name in ("offload.engine", "offload.engine.root"):
            continue
        lines = _own_root_lines(f)
        if lines:
            bad[name] = lines
    assert not bad, bad


def test_env_root_overrides(tmp_path):
    r = subprocess.run([sys.executable, "-c", "from offload.engine.root import ROOT, is_bundle; print(ROOT, is_bundle())"],
                       cwd=ROOT, capture_output=True, text=True, env=_env(OFFLOAD_ROOT=str(tmp_path)))
    assert r.stdout.split() == [str(tmp_path), "True"], r.stderr


def test_repository_is_the_root_in_a_checkout():
    r = subprocess.run([sys.executable, "-c", "from offload.engine.root import ROOT, is_bundle; print(ROOT, is_bundle())"],
                       cwd=ROOT, capture_output=True, text=True, env=_env())
    assert r.stdout.split() == [str(ROOT), "False"], r.stderr


def test_missing_data_gives_a_one_line_error_not_a_traceback():
    r = subprocess.run([sys.executable, "-m", "offload", "issues", "map"], cwd=ROOT, capture_output=True, text=True,
                       env=_env(OFFLOAD_ROOT="/nonexistent"))
    assert r.returncode == 2
    assert "OFFLOAD_ROOT" in r.stderr and "Traceback" not in r.stderr and len(r.stderr.strip().splitlines()) == 1
