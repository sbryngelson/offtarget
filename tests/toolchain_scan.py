"""The scan behind tests/cluster/test_reports.py::test_no_hard_coded_toolchain_outside_the_catalog.

A registered toolchain id (``cce21_4``, ``gcc_sm80``) or a toolchain version
(``21.0.4``) in code is a hard-coded list that the catalog should own. Ids
that are also family names (``afar``, ``nvhpc``) are not flagged. Code means
Python string constants that are not docstrings, non-comment lines of shell
scripts, and JavaScript without its comments. Comments, docstrings and
documents may quote versions.

Not scanned: offload/engine/toolchains.py, the generated files
(tools/derive/toolchains_gen.py OUTPUTS), tests/, the ``*_probe`` directories
under tools/, and the files in catalog/toolchain_names_allowlist.yaml.
The test requires every listed file to have a hit."""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST = ROOT / "catalog" / "toolchain_names_allowlist.yaml"
PRUNE = {"__pycache__", ".git", "results", "corpus", "spec", "bench", ".superpowers",
         "node_modules", ".pytest_cache", "results-compact", "results-site"}
SCAN = (("offload/engine", (".py",)), ("tools", (".py", ".sh")), ("site/static", (".js",)),
        ("site/templates", (".html",)), ("data/vendor/checks", (".py", ".sh")))


def names_and_versions(reg=None) -> tuple[list[str], list[str]]:
    """The toolchain ids (those that are not family names) and the distinct
    toolchain versions of the catalog."""
    from offload.engine.toolchains import registry
    reg = reg or registry()
    ids = [n for n in reg.toolchains if n not in reg.families]
    versions = sorted({t.version for t in reg.toolchains.values()}, key=len, reverse=True)
    return ids, versions


def pattern(reg=None) -> re.Pattern:
    """A toolchain id or version as a token; not inside a hyphenated name
    (``cce19-target-parallel-guarded-loop.f90``, ``therock-afar-24.3.0-...``:
    finding files and install directories are data, not lists)."""
    ids, versions = names_and_versions(reg)
    alts = [r"(?<![\w-])" + re.escape(n) + r"(?![\w-])" for n in sorted(ids, key=len, reverse=True)]
    alts += [r"(?<![\w.-])" + re.escape(v) + r"(?![\w.-])" for v in versions]
    return re.compile("|".join(alts))


def not_scanned() -> set[str]:
    """The files the scan leaves out besides the pruned directories."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_tcgen", ROOT / "tools" / "derive" / "toolchains_gen.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return {"offload/engine/toolchains.py", *mod.OUTPUTS}


def files() -> list[Path]:
    out = []
    skip = not_scanned()
    for root, suffixes in SCAN:
        base = ROOT / root
        if not base.is_dir():
            continue
        for d, dirs, fs in os.walk(base):
            dirs[:] = sorted(x for x in dirs if x not in PRUNE and not x.endswith("_probe"))
            for f in sorted(fs):
                p = Path(d) / f
                if f.endswith(suffixes) and rel(p) not in skip:
                    out.append(p)
    return out


def rel(p: Path) -> str:
    return p.resolve().relative_to(ROOT).as_posix()


def code_text(path: Path) -> list[tuple[int, str]]:
    """(line, text) of the code a file holds: Python string constants that
    are not docstrings; a shell script's non-comment lines; JavaScript and
    HTML without comments."""
    text = path.read_text(errors="replace")
    if path.suffix == ".py":
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return [(n, ln) for n, ln in enumerate(text.splitlines(), 1)]
        docs = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                body = node.body
                if body and isinstance(body[0], ast.Expr) and \
                        isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                    docs.add(id(body[0].value))
        return [(node.lineno, node.value) for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docs]
    if path.suffix == ".sh":
        return [(n, ln) for n, ln in enumerate(text.splitlines(), 1)
                if ln.strip() and not ln.strip().startswith("#")]
    if path.suffix == ".js":
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        return [(n, re.sub(r"//.*$", "", ln)) for n, ln in enumerate(text.splitlines(), 1)]
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return [(n, ln) for n, ln in enumerate(text.splitlines(), 1)]


def scan(reg=None) -> dict[str, str]:
    """path -> the first hit ("line N: token in <text>") of every file that
    names a toolchain or version in code."""
    pat = pattern(reg)
    out = {}
    for p in files():
        for no, txt in code_text(p):
            m = pat.search(txt)
            if m:
                out[rel(p)] = f"line {no}: {m.group(0)} in {txt.strip()[:80]!r}"
                break
    return out


def allowlist(path: Path = ALLOWLIST) -> dict[str, str]:
    """path -> reason of the files allowed to name toolchains."""
    if not Path(path).is_file():
        return {}
    data = yaml.safe_load(Path(path).read_text()) or {}
    out = {}
    for e in data.get("entries") or []:
        if not e.get("path") or not e.get("reason"):
            raise ValueError(f"toolchain_names_allowlist: an entry needs a path and a reason: {e}")
        out[e["path"]] = e["reason"]
    return out
