"""Corpus baseline: compile and run existing corpus tests, judged by exit code.

``run_baseline(index_csv, repos, toolchain, xnack, out)`` takes the files of
``repos`` chosen by ``select_files`` from ``data/index/corpus_index.csv``: Fortran
run tests under the repository's test directory, free-form, with at least one
``target`` directive of the slice. Each file is copied to a temporary
directory with its repository's include directory (``INCLUDES``), compiled
with the toolchain's fixed flags (-O2) and run once under ``HSA_XNACK=<xnack>``
and ``OMP_TARGET_OFFLOAD=mandatory``. Rows are ``pass`` (both exit 0),
``fail``, or ``harness_error`` (an environment pattern matched, or the test
skipped itself). For OpenMP_VV the test's own result line (``suite_result``)
overrides the exit code. ``lang="c"`` selects the omp_vv C tests. Copy mode
(HSA_XNACK=0) runs only ``copy_semantics_paths``. One JSONL row per file is
appended as it finishes; ``rerun_baseline`` replaces some files' rows.
"""
from __future__ import annotations

import csv
import dataclasses
import json
import re
import shutil
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from offload.engine import harness
from offload.engine.catalog import default_skeleton, slice_directives
from offload.engine.toolchains import (TOOLCHAINS, Toolchain,
                                   compiler_version, device_of)

ROOT = Path(__file__).resolve().parent.parent.parent
CORPUS = ROOT / "corpus"
# include directories copied next to the source, per repository
INCLUDES: dict[str, tuple[str, ...]] = {"omp_vv": ("ompvv",)}
# Include files copied next to the source (OpenACCV&V's Fortran
# tests INCLUDE "acc_testsuite.Fh", which lives in Tests/)
INCLUDE_FILES: dict[str, tuple[str, ...]] = {
    "acc_vv": ("Tests/acc_testsuite.Fh",)}
# where a repository keeps its tests (omp_vv's template/ is not a test: its
# template prints "Test failed on the device" and exits 0)
TEST_DIRS: dict[str, str] = {"omp_vv": "tests/", "acc_vv": "Tests/"}
# OpenACC suites (every Fortran test of Tests/, compiled as
# OpenACC; the pass criterion is the exit code: the suite's main program
# exits with the bit mask of its failed tests)
ACC_REPOS = ("acc_vv",)
FREE_FORM = (".f90", ".F90")
C_SUFFIXES = (".c",)
# The suite's C link flag (corpus/omp_vv/sys/make/make.def: CFLAGS
# += -lm for the clang and cray compilers)
C_EXTRA = "-lm"


@dataclass(frozen=True)
class BaselineResult:
    repo: str
    path: str
    spec_dir: str
    toolchain: str
    xnack: int
    opt: str
    flags: str
    rocm: str | None
    thp: str
    offload: str
    status: str            # pass | fail | harness_error
    stage: str             # compile | run
    compile_rc: int | None
    run_rc: int | None
    reason: str
    stdout: str
    stderr: str
    device: str = ""
    compiler: str = ""
    lang: str = "f90"
    # The toolchain's machine and arch and the node's GPU
    machine: str = ""
    arch: str = ""
    gpu: str = ""


def select_files(index_csv: Path, repos: list[str],
                 lang: str = "f90") -> list[dict]:
    """The index rows of the baseline (see the module docstring), sorted by
    repository and path; `lang` "c": the C tests."""
    c = lang == "c"
    slice_names = {d for d in slice_directives(default_skeleton(),
                                               lang="c" if c else "f90")
                   if "target" in d.split()}
    rows = []
    with Path(index_csv).open(newline="") as fh:
        for r in csv.DictReader(fh):
            if r["repo"] in ACC_REPOS:  # OpenACC, Fortran only
                if (r["repo"] in repos and not c and r["lang"] == "fortran"
                        and r["kind"] == "run" and r["path"].endswith(
                            FREE_FORM) and r["path"].startswith(
                                TEST_DIRS[r["repo"]])):
                    rows.append(r)
                continue
            if (r["repo"] in repos and r["lang"] == ("c" if c else "fortran")
                    and r["kind"] == "run"
                    and r["path"].endswith(C_SUFFIXES if c else FREE_FORM)
                    and r["path"].startswith(TEST_DIRS.get(r["repo"], ""))
                    and any(d in slice_names
                            for d in r["directives"].split(";"))):
                rows.append(r)
    return sorted(rows, key=lambda r: (r["repo"], r["path"]))


def copy_semantics_paths(index_csv: Path, repos: list[str],
                         corpus_root: Path = CORPUS,
                         lang: str = "f90") -> set[str]:
    """Paths of the selected files whose result depends on copy semantics
    (read as text; the corpus is untrusted)."""
    from offload.engine.ompvv import copy_semantics
    out = set()
    for r in select_files(index_csv, repos, lang):
        f = Path(corpus_root) / r["repo"] / r["path"]
        if copy_semantics(f.read_text(errors="replace")):
            out.add(r["path"])
    return out


def _include_flags(repo: str) -> str:
    return " ".join(f"-I./{d}" for d in INCLUDES.get(repo, ()))


def run_file(row: dict, tc: Toolchain, xnack: int, corpus_root: Path,
             opt: str = "-O2", timeout_s: int = 120,
             compile_timeout_s: int = 900, thp: str | None = None
             ) -> BaselineResult:
    """Compile and run one corpus file (a copy) by exit code."""
    repo = row["repo"]
    tc = tc.for_mode(xnack)  # NVHPC builds per memory mode
    if repo in ACC_REPOS and tc.model != "acc":
        tc = dataclasses.replace(tc, model="acc")
    src_in = Path(corpus_root) / repo / row["path"]
    inc = _include_flags(repo)
    lang = "c" if row["path"].endswith(C_SUFFIXES) else "f90"
    if lang == "c":
        # NVHPC has no OpenMP version option
        vflag = "" if tc.kind == "nvhpc" else c_version_flag(row)
        inc = f"{inc} {C_EXTRA} {vflag}".strip()
        tc = dataclasses.replace(tc, lang="c")
    tc = dataclasses.replace(tc, extra=f"{tc.extra} {inc}".strip()) \
        if inc else tc
    base = dict(repo=repo, path=row["path"], spec_dir=row.get("spec_dir", ""),
                toolchain=tc.name, xnack=xnack, opt=opt,
                flags=f"{tc.flags()} {opt}", rocm=harness._rocm(tc),
                device=device_of(tc), compiler=compiler_version(tc),
                thp=harness.detect_thp() if thp is None else thp,
                offload="mandatory", lang=lang, machine=tc.machine,
                arch=tc.arch, gpu=harness.gpu_text())
    bad_arch = harness.wrong_arch(tc)
    if bad_arch:
        return BaselineResult(status="harness_error", stage="compile",
                              compile_rc=None, run_rc=None, reason=bad_arch,
                              stdout="", stderr="", **base)
    tmp = Path(tempfile.mkdtemp(prefix="baseline_"))
    try:
        src = tmp / src_in.name
        shutil.copyfile(src_in, src)
        for d in INCLUDES.get(repo, ()):
            shutil.copytree(Path(corpus_root) / repo / d, tmp / d)
        for f in INCLUDE_FILES.get(repo, ()):
            shutil.copyfile(Path(corpus_root) / repo / f, tmp / Path(f).name)
        exe = tmp / "test.out"

        def scrub(text: str) -> str:
            return harness._clip(text).replace(str(tmp), "<tmpdir>") \
                .replace(tmp.name, "<tmpdir>")

        build = harness._execute(
            harness.compile_script(tc, str(src), str(exe), opt, str(tmp)),
            tmp, compile_timeout_s, merge=True)
        clog = f"--- compile (rc={build.rc}) ---\n" + build.stdout

        def result(status, stage, reason, run_rc=None, stdout="", log=""):
            return BaselineResult(status=status, stage=stage,
                                  compile_rc=build.rc, run_rc=run_rc,
                                  reason=scrub(reason), stdout=scrub(stdout),
                                  stderr=scrub(clog + log), **base)

        if build.timed_out:
            return result("fail", "compile", "compile_timeout")
        if build.rc != 0 or not exe.is_file():
            found = harness.classify_message(tc.name, build.stdout,
                                             harness.CATEGORY_ORDER[:-1],
                                             lang)
            if found and found[0] == "environment":
                return result("harness_error", "compile",
                              f"environment: {found[1]}")
            why = f"{found[0]}: {found[1]}" if found else \
                f"compile_failed: rc={build.rc}"
            return result("fail", "compile", why)
        ex = harness._execute(
            harness.run_script(tc, str(exe), xnack, True, str(tmp)), tmp,
            timeout_s)
        log = f"\n--- run (OMP_TARGET_OFFLOAD=mandatory, rc={ex.rc}) ---\n" \
            + ex.stderr
        said = suite_result(ex.stdout)
        if said == "skipped":
            return result("harness_error", "run",
                          f"suite_skipped: the test reports 'Test skipped' "
                          f"(rc={ex.rc})", ex.rc, ex.stdout, log)
        if ex.rc == 0 and said == "failed":
            return result("fail", "run", "suite_reported_failure: exit 0 "
                          "but the test reports 'Test failed' (an error "
                          "count returned as the exit status wraps at "
                          "256)", 0, ex.stdout, log)
        if ex.rc == 0:
            return result("pass", "run", "exit 0", 0, ex.stdout, log)
        env = harness._env_failure(tc, ex)
        if env:
            return result("harness_error", "run", env, ex.rc, ex.stdout, log)
        return result("fail", "run", harness._failure(ex), ex.rc, ex.stdout,
                      log)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


_RESULT = re.compile(r"^\[OMPVV_RESULT:?\s[^\]]*\]\s+Test\s+"
                     r"(passed|failed|skipped)\b", re.M)


def suite_result(stdout: str) -> str | None:
    """What the test's own result line says ("passed", "failed",
    "skipped"; the last one printed), or None without one. The
    current OpenMP_VV C header returns the error count itself as the exit
    status (``OMPVV_RETURN(err)``: ``return err;``), so a count that is a
    multiple of 256 exits 0, and a skipped test (``OMPVV_CHECK_TO_SKIP``)
    exits with -667 & 255; the line decides those two cases."""
    found = _RESULT.findall(stdout or "")
    return found[-1] if found else None


def c_version_flag(row: dict) -> str:
    """-fopenmp-version for a C test: none (the compiler's default, OpenMP
    5.1 for both C front ends, as the Fortran baseline uses the defaults)
    for a test of a 4.5, 5.0 or 5.1 spec directory; the directory's
    version for 5.2 and later (5.2 -> 52, 6.0 -> 60), which the default
    does not accept. Not -fopenmp-version=45/50: CCE craycc at 45 fails to
    link omp_is_initial_device in device code (first C baseline:
    115 of 315 tests; data/findings/cce-c-openmp45-device-link.c)."""
    m = re.match(r"(\d)\.(\d)", row.get("spec_dir", "") or "")
    if not m or (int(m.group(1)), int(m.group(2))) <= (5, 1):
        return ""
    return f"-fopenmp-version={m.group(1)}{m.group(2)}"


def run_baseline(index_csv: Path, repos: list[str], toolchain: str | Toolchain,
                 xnack: int, out: Path, *, corpus_root: Path = CORPUS,
                 opt: str = "-O2", timeout_s: int = 120, workers: int = 8,
                 flags_note: str = "", append: bool = False,
                 only: set[str] | None = None,
                 progress: Callable[[str], None] | None = None,
                 lang: str = "f90") -> int:
    """Run the selected files of `repos` with `toolchain` under
    HSA_XNACK=`xnack`; one row per file in `out` (truncated first unless
    `append`). `only`: just these paths. Returns the number of rows
    written. `lang` "c": the C tests."""
    tc = TOOLCHAINS[toolchain] if isinstance(toolchain, str) else toolchain
    tc = tc.for_mode(xnack)  
    rows = select_files(index_csv, repos, lang)
    if only is not None:
        rows = [r for r in rows if r["path"] in only]
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not append:
        out.write_text("")
    lock = threading.Lock()
    count = [0]

    def job(row) -> None:
        try:
            r = run_file(row, tc, xnack, corpus_root, opt, timeout_s)
        except Exception as err:  # noqa: BLE001 - one file, keep going
            r = BaselineResult(row["repo"], row["path"],
                               row.get("spec_dir", ""), tc.name, xnack, opt,
                               f"{tc.flags()} {opt}", None, "n/a",
                               "mandatory", "harness_error", "compile", None,
                               None, f"runner_exception: "
                               f"{type(err).__name__}: {err}", "", "",
                               lang=lang)
        if flags_note:
            r = dataclasses.replace(r, flags=f"{r.flags} {flags_note}")
        line = json.dumps(dataclasses.asdict(r)) + "\n"
        with lock:
            with out.open("a") as f:
                f.write(line)
            count[0] += 1
            if progress:
                progress(f"{count[0]}/{len(rows)} {r.repo}/{r.path} "
                         f"{tc.name} xnack={xnack}: {r.status}")

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(job, rows))
    return count[0]


def rerun_baseline(index_csv: Path, repos: list[str], paths: set[str],
                   toolchains: list[str | Toolchain], xnack: int, out: Path,
                   **kw) -> int:  # kw may carry lang
    """Run `paths` again on `toolchains` under one HSA_XNACK value: their
    rows in `out` (those toolchains, that mode) are dropped, every other
    row is kept, and the new rows are appended. Returns the rows written."""
    names = {t if isinstance(t, str) else t.name for t in toolchains}
    out = Path(out)
    kept = [line for line in (out.read_text().splitlines()
                              if out.exists() else [])
            if line.strip() and not (
                (d := json.loads(line))["path"] in paths
                and d["toolchain"] in names and d["xnack"] == xnack)]
    out.write_text("".join(f"{line}\n" for line in kept))
    return sum(run_baseline(index_csv, repos, tc, xnack, out, append=True,
                            only=set(paths), **kw) for tc in toolchains)


def read_baseline(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines()
            if line.strip()]
