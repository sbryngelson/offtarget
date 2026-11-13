"""Markers for tests that need inputs a clone may not have: a fresh clone has no spec PDFs, no corpus/ and no
results/ (docs/tooling/setup.md says how to get them); the public repository has no benchmark sets and one
commit of history. A marked test skips, naming what is missing.

    @pytest.mark.needs_spec                 # the spec PDFs (all of them)
    @pytest.mark.needs_corpus("omp_vv")     # corpus/<name> (default: omp_vv)
    @pytest.mark.needs_results("results/fuzz/s1/meta.json", ...)
    @pytest.mark.needs_bench("wild/cases.yaml", ...)   # files under data/bench
    @pytest.mark.needs_commit("a125ad9")    # a commit of this repository's history
    @pytest.mark.needs_compiler("afar")     # the toolchain's compiler, where the local settings say it is
    @pytest.mark.needs_linux("/proc")       # Linux; the argument says what of it the test uses
    @pytest.mark.needs_gcc                  # GNU gcc as `gcc` (on macOS `gcc` is clang)
"""
import functools
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

# One thread per numeric library: with many test workers on one machine, the default (a thread per
# core in every worker) makes a two-second model fit take minutes.
for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

# The machines and compilers are the catalogs' with a made-up user's settings laid over them
# (offload.engine.localcfg), not the settings of whoever runs the tests.
# OFFLOAD_TEST_LOCAL names your own settings file to lay under them, for the tests that run a real compiler
# (its install paths); the made-up user's machines and lanes still win.
# the tests' made-up user, whose name the scrubbers look for besides the committers' (offload.engine.site.scrub)
os.environ["OFFLOAD_PRIVATE_NAMES"] = "jdoe"
os.environ["OFFLOAD_LOCAL"] = os.pathsep.join(
    [p for p in (os.environ.get("OFFLOAD_TEST_LOCAL"), str(Path(__file__).resolve().parent / "data" / "local_settings.yaml")) if p])

import pytest

import where

ROOT = Path(__file__).resolve().parent.parent
SPEC = ("spec/openmp/openmp-5.0.pdf", "spec/openmp/openmp-5.1.pdf",
        "spec/openmp/openmp-5.2.pdf", "spec/openmp/openmp-6.0.pdf",
        "spec/openacc/openacc-3.4.pdf")


def pytest_configure(config):
    for name, what in (
            ("needs_spec", "the OpenMP/OpenACC spec PDFs under spec/"),
            ("needs_corpus", "a reference suite under corpus/"),
            ("needs_results", "measurements or confirmer output under "
                              "results/")):
        config.addinivalue_line("markers", f"{name}: needs {what} "
                                "(git-ignored; docs/tooling/setup.md)")
    config.addinivalue_line("markers", "needs_bench: needs files of the benchmark sets under data/bench "
                            "(not in the public repository)")
    config.addinivalue_line("markers", "needs_commit: needs a commit of the history (not in the public repository)")
    config.addinivalue_line("markers", "needs_compiler: needs a toolchain's compiler installed "
                            "(catalog/local.example.yaml)")
    config.addinivalue_line("markers", "needs_linux(what): needs Linux (/proc, setsid, GNU time, PR_SET_PDEATHSIG)")
    config.addinivalue_line("markers", "needs_gcc: needs GNU gcc as `gcc` (the base-language checker)")


def missing_inputs(item) -> list[str]:
    want = []
    if item.get_closest_marker("needs_spec"):
        want += SPEC
    m = item.get_closest_marker("needs_corpus")
    if m:
        want += [f"corpus/{n}" for n in (m.args or ("omp_vv",))]
    m = item.get_closest_marker("needs_results")
    if m:
        want += list(m.args or ("results",))
    m = item.get_closest_marker("needs_bench")
    if m:
        want += [f"data/bench/{n}" for n in m.args]
    miss = [p for p in want if not (ROOT / p).exists()]
    m = item.get_closest_marker("needs_commit")
    if m:
        miss += [f"commit {c}" for c in m.args if subprocess.run(
            ["git", "cat-file", "-e", c + "^{commit}"], cwd=ROOT, capture_output=True).returncode]
    m = item.get_closest_marker("needs_compiler")
    if m:
        miss += [lack for tc in m.args if (lack := _no_compiler(tc))]
    return miss + _missing_machine(item)


@functools.lru_cache(maxsize=None)
def _no_gnu_gcc() -> str | None:
    """Why `gcc` is not GNU gcc (absent, or another compiler under that name, as on macOS); None when it is."""
    try:
        r = subprocess.run(["gcc", "-dM", "-E", "-x", "c", os.devnull], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return "gcc not found"
    if "__GNUC__" not in r.stdout or "__clang__" in r.stdout:
        return "`gcc` is not GNU gcc"
    return None


def _platform_lacks(item) -> str | None:
    m = item.get_closest_marker("needs_linux")
    if m and not sys.platform.startswith("linux"):
        return f"needs Linux ({', '.join(m.args) or 'process control'}); this is {sys.platform}"
    if item.get_closest_marker("needs_gcc") and (why := _no_gnu_gcc()):
        return f"needs GNU gcc: {why}"
    return None


def _no_compiler(tc: str) -> str | None:
    from offload.engine.toolchains import TOOLCHAINS
    fc = TOOLCHAINS[tc].fc
    return None if Path(fc).is_file() else f"the {TOOLCHAINS[tc].label} compiler ({fc}; catalog/local.example.yaml)"


@functools.lru_cache(maxsize=None)
def _elsewhere() -> dict:
    """The tests the maintainers' CPU lane leaves for an AMD GPU node, with why
    (tools/lanes/wingtip_offline.yaml, tuolumne_tests)."""
    steps = yaml.safe_load((ROOT / "tools" / "lanes" / "wingtip_offline.yaml").read_text())["steps"]
    return steps["tests"].get("tuolumne_tests") or {}


@functools.lru_cache(maxsize=None)
def _machine_lacks(why: str) -> str | None:
    """What this machine lacks for a test the CPU lane leaves elsewhere for reason `why`; None when it has it."""
    if why == "AFAR front end":
        return _no_compiler("afar")
    if why == "CCE modules":
        return None if os.environ.get("MODULESHOME") else "environment modules with CCE"
    if why.startswith("the application clones"):
        return None if (ROOT / "corpus" / "apps").is_dir() else "corpus/apps"
    if why.startswith("harness node check"):
        from offload.engine.toolchains import detect_gpu
        gpu = detect_gpu()[0]
        return None if gpu in ("", "gfx942") else f"no GPU or an MI300A (gfx942); this node's GPU is {gpu}"
    return None


def _missing_machine(item) -> list[str]:
    why = _elsewhere().get(item.nodeid.split("[")[0])
    lack = why and _machine_lacks(why)
    return [lack] if lack else []


_SLOW_FIXTURES = {"built_site_data", "offload_bundle", "installed"}


def pytest_collection_modifyitems(config, items):
    """Mark the tests that cost seconds each (the shared builds, the installed package, the real measurements)."""
    for item in items:
        if _SLOW_FIXTURES & set(item.fixturenames) or item.get_closest_marker("needs_results"):
            item.add_marker(pytest.mark.slow)


def pytest_runtest_setup(item):
    lack = _platform_lacks(item)
    if lack:
        pytest.skip(lack)
    miss = missing_inputs(item)
    if miss:
        pytest.skip("needs inputs this clone lacks: " + ", ".join(miss) + " (docs/tooling/setup.md)")


_IGNORED_INPUTS = ("spec", "results", "corpus")


def _absent_input(exc) -> str | None:
    """The git-ignored input (under spec/, results/ or corpus/) whose absence raised `exc`, if that is what it is."""
    if not isinstance(exc, FileNotFoundError):
        return None
    name = exc.filename or (exc.args[0] if len(exc.args) == 1 and isinstance(exc.args[0], (str, os.PathLike)) else None)
    if not name:
        return None
    p = Path(name) if Path(name).is_absolute() else ROOT / name     # the tests run from the root
    try:
        rel = p.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return None
    return str(rel) if rel.parts and rel.parts[0] in _IGNORED_INPUTS and not p.exists() else None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """A test with no marker that fails only because a git-ignored input is absent skips, naming it."""
    out = yield
    rep = out.get_result()
    if rep.failed and call.excinfo is not None and rep.when in ("setup", "call"):
        miss = _absent_input(call.excinfo.value)
        if miss:
            rep.outcome = "skipped"
            rep.longrepr = (str(item.path), item.location[1] or 0,
                            f"Skipped: needs inputs this clone lacks: {miss} (docs/tooling/setup.md)")


@pytest.fixture(autouse=True)
def _gate_verdicts_file_is_put_back():
    """Commands that run once per process (tools/campaigns/harvest.py, tools/campaigns/harvest_known.py confirm) point
    offload.engine.gate.VERDICTS_FILE at a run's own file; called in-process by a test they would leave
    every later load_verdicts() reading a deleted temp file ("not_gated" for every cell, so the committed
    artifacts looked stale). Whatever a test does, the module's file is the one it started with."""
    from offload.engine import gate
    saved = gate.VERDICTS_FILE
    yield
    gate.VERDICTS_FILE = saved


@pytest.fixture(scope="session")
def offload_bundle(built_site_data):
    """The data bundle (offload._bundle.collect), built once per test run from the one site-data build:
    (directory, files). The checkout's data cache is filled from it, so `offload` processes find it ready."""
    import shutil
    import tempfile
    from unittest import mock

    from offload import _bundle
    from offload import data as OD
    from offload.engine.site import data as D

    def build(dest):
        def prebuilt(target):
            shutil.copytree(built_site_data, target, dirs_exist_ok=True)
        with mock.patch.object(D, "build", prebuilt):
            _bundle.collect(dest)

    dest = where.built_once("offload_bundle", build)
    cache = OD.cache_root() / OD._stamp()
    if not (cache / "data" / "issues.json").is_file():
        import fcntl
        base = OD.cache_root()
        base.mkdir(parents=True, exist_ok=True)
        with open(base / ".build.lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)       # the lock offload.data.data_dir builds under
            if not (cache / "data" / "issues.json").is_file():
                with tempfile.TemporaryDirectory(dir=base) as tmp:
                    shutil.copytree(dest / "data", Path(tmp) / "data")
                    OD.publish(Path(tmp), cache)
    return dest, sorted(p for p in dest.rglob("*") if p.is_file())


@pytest.fixture(scope="session")
def built_site_data(tmp_path_factory):
    """The site's data JSON (offload.engine.site.data.build), built once per test run; read only."""
    from offload.engine.site import data as D

    def build(dest):
        (dest.parent / "site_data.report.json").write_text(json.dumps(D.build(dest)))
    return where.built_once("site_data", build)
