"""Compile, run and classify stress programs (offload.engine.stress,
offload.engine.stress_c) on a toolchain, a memory mode and a build variant.

``Limits`` are recorded in every row: a compile wall limit (``compile_s``,
900 s), a virtual-memory limit per compiler process (``ulimit -v``, 32 GiB,
16 GiB on wingtip) and a run wall limit (``run_s``, 120 s; 600 s for the
runtime axis). Compile steps run under ``/usr/bin/time`` for compile seconds
and peak RSS (KiB).

Classes are fuzz_exec's plus ``compile_timeout``, ``compile_oom``,
``probe_rejected`` and ``probe_accepted``. Whether a timeout is a finding is
decided by offload.engine.stress_report. ``VARIANTS`` are per-vendor optimisation
and cross-unit inlining settings. Oracles: the Python model (``prog.expected``),
the sequential elision (``elide``) and cross-compiler agreement.
"""
from __future__ import annotations

import dataclasses
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from offload.engine import harness
from offload.engine.toolchains import TOOLCHAINS, Toolchain

GIB = 1024 * 1024        # KiB per GiB (ulimit -v takes KiB)


@dataclass(frozen=True)
class Limits:
    compile_s: int = 900
    mem_gib: int = 32
    run_s: int = 120

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


# build variants: vendor -> flags (the optimisation level included)
VARIANTS = {
    "O2": {"afar": "-O2", "cce": "-O2", "nvhpc": "-O2", "gcc": "-O2"},
    "O0": {"afar": "-O0", "cce": "-O0", "nvhpc": "-O0", "gcc": "-O0"},
    "O3": {"afar": "-O3", "cce": "-O3", "nvhpc": "-O3", "gcc": "-O3"},
    # whole-program / link-time: host LTO for flang/clang (the AMDGPU
    # device code is linked with LTO by the offload driver in every
    # variant), CCE's whole-program mode, NVHPC's link-time inlining
    "lto": {"afar": "-O2 -flto", "cce": "-O2 -h wp -h pl=st.pl",
            "nvhpc": "-O2 -Minline", "gcc": "-O2 -flto"},
    # no inlining: CCE -h ipa0, NVHPC -Mnoinline, flang and GCC -fno-inline
    "noinline": {"afar": "-O2 -fno-inline", "cce": "-O2 -h ipa0",
                 "nvhpc": "-O2 -Mnoinline", "gcc": "-O2 -fno-inline"},
    # relocatable device code off (NVHPC: -gpu=nordc; default rdc)
    "nordc": {"nvhpc": "-O2 -gpu=nordc"},
    # a static library of the device code (all objects but main)
    "staticlib": {"afar": "-O2", "cce": "-O2", "nvhpc": "-O2", "gcc": "-O2"},
}
C_VARIANT = {"cce": {"-h wp -h pl=st.pl": "-flto", "-h ipa0": "-fno-inline"}}

OOM = re.compile(r"out of memory|std::bad_alloc|Cannot allocate memory|"
                 r"memory exhausted|LLVM ERROR: out of memory|"
                 r"virtual memory exhausted|ENOMEM|unable to allocate|"
                 r"Memory allocation failed|insufficient memory",
                 re.I)
TIME_LINE = re.compile(r"^STRESS_TIME (\S+) (\d+) (\S+) rc=(-?\d+)$", re.M)
RESULT = re.compile(r"^\s*RESULT checksum=(-?\d+) ran_on_host=([01])\s*$",
                    re.M)
KLINE = re.compile(r"^\s*K (\S+) (-?\d+)\s*$", re.M)
OBS = re.compile(r"^\s*OBS (\S+) (\S+) (\S+) +(\d+) +(-?\d+)\s*$", re.M)


def vendor(tc: Toolchain) -> str:
    return tc.kind


def variant_flags(tc: Toolchain, variant: str, lang: str = "f90"
                  ) -> str | None:
    v = VARIANTS[variant].get(vendor(tc))
    if v is None:
        return None
    if vendor(tc) == "afar" and variant == "noinline" and lang == "f90":
        return None          # flang has no -fno-inline (it rejects it)
    if lang == "c":
        for a, b in C_VARIANT.get(vendor(tc), {}).items():
            v = v.replace(a, b)
    return v


def tc_for(name: str, model: str, lang: str = "f90") -> Toolchain:
    tc = TOOLCHAINS[name]
    if model == "acc":
        tc = dataclasses.replace(tc, model="acc")
    if lang == "c":
        tc = dataclasses.replace(tc, lang="c")
    return tc


TIMEOUT_RC = (124, 137)   # coreutils timeout: limit hit / killed after it
# --foreground (F5): without it coreutils timeout calls
# setpgid and moves the compiler or program out of the run's process group,
# so the group kill of the harness (at the run's limit and after the script
# ends) missed it and it outlived the build. With it, timeout stays in the
# group, kills its child at the limit (KILL 10 s later), and the group kill
# takes the child's own children.
TIMEOUT = "timeout --foreground --kill-after=10"


def _step(cmd: str, tag: str, mem_kib: int, limit_s: int = 900) -> str:
    """One compiler / linker step under the memory limit, the wall limit
    enforced inside the job and /usr/bin/time (its rc is kept: the script
    stops at the first failing step).

    The step's ``timeout --foreground --kill-after=10`` kills only the
    compiler driver at the limit: with --foreground, "children of COMMAND
    will not be timed out" (coreutils). The driver's children (front end,
    optimizer, clang -cc1, ...) stay in the run's process group and die by
    the harness's group kill; when the Python runner itself dies, that kill
    comes from the harness's outer ``timeout --kill-after`` around the
    script (offload/engine/harness.py ``_command``, commit 2e0124c), which
    signals the whole group. So a hung compiler and its children are
    bounded only together with the harness, not by this timeout alone."""
    return (f"( ulimit -v {mem_kib}; /usr/bin/time -f "
            f"'STRESS_TIME {tag} %M %e rc=%x' {TIMEOUT} "
            f"{limit_s} {cmd} ) || exit 1")


def build_script(tc: Toolchain, files: list[str], exe: str, opt: str,
                 tmpdir: str, mem_kib: int, staticlib: bool = False,
                 limit_s: int = 900) -> str:
    """Compile `files` (compile order; .f90 with the Fortran compiler,
    .c with the C compiler of the toolchain) one at a time with -c, then
    link (all objects, or main.o with a static library of the rest)."""
    bare = dataclasses.replace(tc, prelude="")
    lines = harness._setup(tc, tmpdir)
    objs = []
    files = [f for f in files if f.endswith((".f90", ".c"))]
    fortran = any(f.endswith(".f90") for f in files)
    linker = bare.fc if fortran else dataclasses.replace(
        bare, lang="c", model="omp").compiler()
    lflags = bare.flags() if fortran else dataclasses.replace(
        bare, lang="c", model="omp").flags()
    for f in files:
        o = re.sub(r"\.(f90|c)$", ".o", f)
        if f.endswith(".c"):
            ctc = dataclasses.replace(bare, lang="c", model="omp")
            cmd = f"{ctc.compiler()} {ctc.flags()} {opt} -c {f} -o {o}"
        else:
            cmd = f"{bare.fc} {bare.flags()} {opt} -c {f} -o {o}"
        lines.append(_step(cmd, f, mem_kib, limit_s))
        objs.append(o)
    if staticlib and len(objs) > 1:
        main = [o for o in objs if o.startswith("main")] or objs[-1:]
        rest = [o for o in objs if o not in main]
        lines.append(_step(f"ar rcs libstress.a {' '.join(rest)}", "ar",
                           mem_kib, limit_s))
        link = f"{linker} {lflags} {opt} {' '.join(main)} " \
            f"-L. -lstress -o {exe}"
    else:
        link = f"{linker} {lflags} {opt} {' '.join(objs)} -o {exe}"
    lines.append(_step(link, "link", mem_kib, limit_s))
    return "\n".join(lines) + "\n"


@dataclass
class Row:
    id: str
    toolchain: str
    mode: int
    variant: str
    cls: str
    reason: str = ""
    compile_s: float = 0.0
    peak_rss_kib: int = 0
    steps: list = field(default_factory=list)
    run_s: float = 0.0
    checksum: int | None = None
    ran_on_host: int | None = None
    bad_kernels: list = field(default_factory=list)
    missing_kernels: list = field(default_factory=list)
    obs: dict = field(default_factory=dict)
    flaky: bool = False
    output: str = ""
    limits: dict = field(default_factory=dict)
    legality: str = "legal"
    axis: str = ""
    size: int = 0
    layout: str = ""
    model: str = "omp"
    lang: str = "f90"
    host: str = ""
    gen: str = ""
    rev: int = 1
    build_dir: str = ""
    # The rest of the provenance (offload.engine.provenance)
    node: str = ""
    toolchain_build: str = ""
    flags: str = ""
    env_hash: str = ""
    git_rev: str = ""
    gate: str = ""

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def _scrub(text: str, tmp: Path) -> str:
    return text.replace(str(tmp), "<tmpdir>")


def classify_compile(tc: Toolchain, rc: int | None, out: str,
                     steps: list) -> tuple[str | None, str]:
    """(class or None when it built, reason)."""
    if rc is None:
        return "compile_timeout", "compile_timeout"
    if rc == 0:
        return None, ""
    failed = next((s for s in steps if s["rc"] != 0), None)
    if failed and failed["rc"] in TIMEOUT_RC and not OOM.search(out):
        return "compile_timeout", "compile_timeout (in-job limit)"
    m = OOM.search(out)
    if m or (failed and failed["rc"] in (137, -9) and "Killed" in out):
        return "compile_oom", "compile_oom: " + (m.group(0) if m else
                                                 "killed")
    # The C compiler's own table for a C program (craycc's
    # clang crash was unclassified with the Fortran table)
    found = harness.classify_message(tc.name, out,
                                     harness.CATEGORY_ORDER[:-1],
                                     "c" if tc.lang == "c" else "f90")
    if found is None:
        # a compiler killed by a signal without a message is an ICE
        if failed and failed["rc"] not in (0, 1, 2):
            return "ice", f"ice: {failed['step']} exit {failed['rc']}"
        return "harness_error", f"unclassified_compile_failure: rc={rc}"
    cat, line = found
    if cat == "environment":
        return "harness_error", f"environment: {line}"
    if cat == "ice":
        return "ice", f"ice: {line}"
    code = {"not_implemented": "not_implemented",
            "link_undefined": "link_undefined_symbol",
            "error": "diagnostic"}[cat]
    return "compile_reject", f"{code}: {line}"


def parse_steps(out: str) -> list:
    steps = []
    for m in TIME_LINE.finditer(out):
        steps.append({"step": m.group(1), "rss_kib": int(m.group(2)),
                      "s": float(m.group(3)), "rc": int(m.group(4))})
    return steps


def compile_prog(prog, tc: Toolchain, variant: str, tmp: Path,
                 lim: Limits) -> tuple[str | None, str, list, float, str]:
    """(class or None, reason, steps, seconds, output)."""
    names = []
    for name, text in prog.files:
        (tmp / name).write_text(text)
        names.append(name)
    opt = variant_flags(tc, variant, prog.lang)
    if opt is None:
        return "skipped", f"no {variant} variant for {vendor(tc)}", [], 0, ""
    script = build_script(tc, names, "prog.out", opt, str(tmp),
                          lim.mem_gib * GIB, staticlib=variant == "staticlib",
                          limit_s=lim.compile_s)
    t0 = time.time()
    ex = harness._execute(script, tmp, lim.compile_s, merge=True)
    secs = time.time() - t0
    out = ex.stdout
    steps = parse_steps(out)
    cls, reason = classify_compile(tc, ex.rc, out, steps)
    if cls is None and not (tmp / "prog.out").is_file():
        cls, reason = "harness_error", "no_executable"
    return cls, reason, steps, secs, out


def parse_run(stdout: str) -> dict:
    found = RESULT.findall(stdout)
    ks = {k: int(v) for k, v in KLINE.findall(stdout)}
    obs = {}
    for kern, route, what, j, v in OBS.findall(stdout):
        obs[f"{kern}:{route}:{what}:{j}"] = int(v)
    return {"result": found, "k": ks, "obs": obs}


def run_once(tc: Toolchain, exe: Path, tmp: Path, mode: int, offload: str,
             timeout_s: int):
    t = tc.for_mode(mode)
    script = harness.run_script(
        t, str(exe), mode, offload == "mandatory", str(tmp),
        offload=None if offload in ("mandatory", "unset") else offload)
    script = in_job_limit(script, timeout_s)
    t0 = time.time()
    ex = harness._execute(script, tmp, timeout_s)
    return ex, time.time() - t0


def in_job_limit(script: str, limit_s: int) -> str:
    """The run script with its program under ``timeout --kill-after=10``
    (the limit holds inside the job; the last line still starts with
    ``exec``, so the harness's per-GPU run lock still applies)."""
    lines = script.rstrip("\n").split("\n")
    if lines and lines[-1].startswith("exec "):
        lines[-1] = f"exec {TIMEOUT} {int(limit_s)} " + lines[-1][5:]
    return "\n".join(lines) + "\n"


def judge(prog, ex, toolchain: str = "") -> tuple[str, str, dict]:
    info = parse_run(ex.stdout)
    if (ex.timed_out or ex.rc != 0) and toolchain:
        # The runtime reports a capacity limit (a
        # break point, not a compiler failure; offload.engine.harness.CAPACITY)
        from offload.engine.harness import capacity_message
        line = capacity_message(toolchain, (ex.stdout or "") + "\n" +
                                (ex.stderr or ""))
        if line:
            return "capacity", f"capacity: {line}", info
    if ex.timed_out or ex.rc in TIMEOUT_RC and not info["result"]:
        return "run_timeout", "run_timeout", info
    if ex.rc != 0 or len(info["result"]) != 1:
        if ex.rc is not None and ex.rc < 0:
            import signal
            try:
                why = f"crash: {signal.Signals(-ex.rc).name}"
            except ValueError:
                why = f"crash: signal {-ex.rc}"
        elif ex.rc != 0:
            why = f"exit_status: {ex.rc}"
        else:
            why = "no_result_line" if not info["result"] else \
                "multiple_result_lines"
        return "run_error", why, info
    cs, host = int(info["result"][0][0]), int(info["result"][0][1])
    if cs != prog.expected:
        return "wrong_code", f"checksum={cs} expected={prog.expected}", info
    if host == 1:
        return "host_fallback", "ran_on_host=1", info
    return "agree", "", info


WORST = ("harness_error", "wrong_code", "run_error", "run_timeout",
         "capacity", "host_fallback", "agree")


def run_prog(prog, tc: Toolchain, mode: int, exe: Path, tmp: Path,
             lim: Limits, reruns: int = 2) -> tuple[str, str, dict, float,
                                                     bool, str]:
    timeout = lim.run_s
    trials = []
    t_run = 0.0
    for k in range(1 + reruns):
        ex, secs = run_once(tc, exe, tmp, mode, "mandatory", timeout)
        t_run += secs
        cls, why, info = judge(prog, ex, tc.name)
        trials.append((cls, why, info, ex))
        if cls == "agree" or (cls == "run_timeout" and k >= 1):
            break
    flaky = len({(c, tuple(i["result"])) for c, _, i, _ in trials}) > 1
    cls, why, info, ex = min(trials, key=lambda t: WORST.index(t[0]))
    out = (ex.stdout[-3000:] + "\n" + (ex.stderr or "")[-3000:]) \
        if cls != "agree" else ""
    return cls, why, info, t_run, flaky, out


def execute(prog, toolchain: str, modes=(1, 0), variant: str = "O2",
            lim: Limits | None = None, keep: Path | None = None,
            build_dir: str | None = None) -> list:
    """Rows of `prog` on `toolchain` in `variant`, one per memory mode in
    `modes` (AMD: HSA_XNACK, one build run in each mode; NVHPC: the row
    key, a compile flag: one build per mode). `build_dir` (the
    reproduction gate): build in this path (it must not exist; one mode
    per call when the modes are compile flags)."""
    lim = lim or Limits(run_s=600 if prog.axis == "runtime" else 120)
    base = tc_for(toolchain, prog.model, prog.lang)
    if base.compile_time_modes():
        if build_dir is not None and len(modes) > 1:
            raise ValueError("one mode per build directory")
        rows = []
        for m in modes:
            rows += _execute(prog, base.for_mode(m), toolchain, (m,),
                             variant, lim, keep, build_dir)
        return rows
    return _execute(prog, base, toolchain, tuple(modes), variant, lim, keep,
                    build_dir)


def build_prefix(program_id: str) -> str:
    """The build directory's mkdtemp prefix: no "-" anywhere (a
    "-1" in the source path can cut CCE ftn's message file and abort the
    compile, data/findings/stress/cce-ftn-cif-record-split-abort.f90; the
    ids carry size and seed as "-12-1")."""
    return "st_" + program_id[:40].replace("-", "_") + "_"


def node_local_tmp() -> str | None:
    """STRESS_TMP, the parent of every build and run directory. It must be
    node-local (F12): CCE builds in a lustre directory
    fail (cce_omp_offload_linker "Could not find executable"; a CCE 21
    optcg segfault), and the build path changes CCE ftn's behaviour (the
    free() abort, data/reports/fuzz-stress.md). A path on a network
    filesystem raises."""
    d = os.environ.get("STRESS_TMP")
    if not d:
        return None
    os.makedirs(d, exist_ok=True)
    fs = subprocess.run(["stat", "-f", "-c", "%T", d], capture_output=True,
                        text=True).stdout.strip().lower()
    if fs in ("lustre", "nfs", "gpfs", "nfs4", "fuse.sshfs") or \
            d.startswith(("/p/", "/usr/workspace", "/g/g")):
        raise RuntimeError(f"STRESS_TMP={d} is on {fs or 'a network fs'}: "
                           "use node-local storage (/tmp, /var/tmp)")
    return d


def _row(prog, toolchain, mode, variant, lim) -> Row:
    return Row(prog.id, toolchain, mode, variant, "harness_error",
               limits=lim.as_dict(), legality=prog.legality, axis=prog.axis,
               size=prog.size, layout=prog.layout, model=prog.model,
               lang=prog.lang, host=os.uname().nodename,
               gen=getattr(prog, "gen", ""), rev=getattr(prog, "rev", 1))


def _provenance(row: Row, tc: Toolchain, opt: str | None) -> None:
    """The provenance fields of a stress row (build_dir is set
    where the directory is made)."""
    from offload.engine import provenance as PV
    try:
        env = dict(tc.for_mode(row.mode).run_env(row.mode))
    except ValueError:
        env = {}
    env["OMP_TARGET_OFFLOAD"] = "unset" if tc.model == "acc" else \
        "mandatory"
    f = PV.fields(tc, row.build_dir, f"{tc.flags()} {opt or ''}".strip(),
                  env, row.cls not in ("agree", "harness_error", "skipped",
                                       "probe_rejected"))
    for k, v in f.items():
        setattr(row, k, v)


def _execute(prog, tc: Toolchain, toolchain: str, modes: tuple,
             variant: str, lim: Limits, keep: Path | None,
             build_dir: str | None = None) -> list:
    rows = [_row(prog, toolchain, m, variant, lim) for m in modes]
    if build_dir is None:
        tmp = Path(tempfile.mkdtemp(prefix=build_prefix(prog.id),
                                    dir=node_local_tmp()))
    else:
        tmp = Path(build_dir)
        tmp.mkdir(parents=True)        # FileExistsError if it exists
    for row in rows:
        row.build_dir = str(tmp)      # the build path matters (F2)
    try:
        return _execute_in(prog, tc, rows, variant, lim, tmp)
    finally:
        for row in rows:
            _provenance(row, tc, variant_flags(tc, variant, prog.lang))
        if keep is not None:
            shutil.copytree(tmp, keep / prog.id, dirs_exist_ok=True)
        shutil.rmtree(tmp, ignore_errors=True)


def _execute_in(prog, tc: Toolchain, rows: list, variant: str, lim: Limits,
                tmp: Path) -> list:
    cls, reason, steps, secs, out = compile_prog(prog, tc, variant, tmp,
                                                 lim)
    for row in rows:
        row.steps = steps
        row.compile_s = round(secs, 2)
        row.peak_rss_kib = max((s["rss_kib"] for s in steps), default=0)
    if cls == "skipped":
        for row in rows:
            row.cls, row.reason = "skipped", reason
        return rows
    if cls is not None:
        for row in rows:
            row.cls, row.reason = cls, _scrub(reason, tmp)
            row.output = _scrub(harness._clip(out), tmp)[-6000:]
            if prog.legality == "illegal_probe" and cls == \
                    "compile_reject":
                row.cls = "probe_rejected"
        return rows
    exe = tmp / "prog.out"
    for row in rows:
        cls, why, info, rs, flaky, rout = run_prog(prog, tc, row.mode,
                                                   exe, tmp, lim)
        row.cls, row.reason, row.run_s, row.flaky = cls, why, \
            round(rs, 2), flaky
        if info["result"]:
            row.checksum = int(info["result"][0][0])
            row.ran_on_host = int(info["result"][0][1])
        row.bad_kernels = sorted(k for k, v in info["k"].items()
                                 if prog.per_kernel.get(k) != v)
        row.missing_kernels = sorted(k for k in prog.per_kernel
                                     if k not in info["k"])
        row.obs = info["obs"]
        row.output = _scrub(rout, tmp)
        if prog.legality == "illegal_probe":
            row.reason = f"{row.cls}: {row.reason}"
            row.cls = "probe_accepted"
    return rows


# Fix: run_group's command runs in a session (and
# process group) of its own, and the in-job `timeout --foreground` kills
# only its direct child, never a grandchild (coreutils: "children of
# COMMAND will not be timed out"). The group is bounded by the harness's
# shared watchdog (offload.engine.harness.watch_group): a
# small bash in a session of its own reads a pipe only this runner holds;
# at EOF (the runner died, by any signal) or at the limit plus
# WATCHDOG_GRACE_S it sends the group SIGTERM, then SIGKILL KILL_AFTER_S
# later, so a grandchild that ignores TERM is ended too. The runner stops
# it when the run is over, and kills the group with SIGKILL itself at its
# own limit and after every run. The direct child (`timeout`) gets no death
# signal: if the runner dies before the
# watchdog has started, `timeout` stays as the in-job limit for the
# command. Limits (as the harness's): a descendant that leaves the group
# (setsid or setpgid: a job launcher) is reached neither by the killpg nor
# by the watchdog; the group, not the session, is what is killed.
WATCHDOG_GRACE_S = 2


def run_group(cmd, cwd, timeout: float, env=None) -> subprocess.CompletedProcess:
    """subprocess.run in its own session and process group: on a timeout
    (and after the command ends) the WHOLE group is killed with SIGKILL, so
    no compiler child or GPU program outlives its limit (a fuzz executable
    of another task held two wingtip GPUs for 12.5 hours); if the runner
    dies, the watchdog kills the group (see above). Raises
    subprocess.TimeoutExpired like subprocess.run."""
    # the limit inside the child too
    cmd = TIMEOUT.split() + [str(int(timeout))] + list(cmd)
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, errors="replace",
                         start_new_session=True)
    dog = harness.watch_group(p.pid, timeout + WATCHDOG_GRACE_S)
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        harness._kill_group(p.pid)
        try:
            p.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
        raise
    finally:
        harness._kill_group(p.pid)
        harness.stop_watch(dog)
    return subprocess.CompletedProcess(cmd, p.returncode, out, err)



# --- sequential elision and the legality gate ----------------------------------------------------

STUB_OMP = """module omp_lib
  use, intrinsic :: iso_c_binding
  implicit none
  integer, parameter :: omp_allocator_handle_kind = 8
  integer(omp_allocator_handle_kind), parameter :: omp_default_mem_alloc = 1
  interface
    function st_malloc(n) bind(C, name="malloc") result(p)
      import :: c_ptr, c_size_t
      integer(c_size_t), value :: n
      type(c_ptr) :: p
    end function st_malloc
    subroutine st_free(p) bind(C, name="free")
      import :: c_ptr
      type(c_ptr), value :: p
    end subroutine st_free
    function st_memcpy(d, s, n) bind(C, name="memcpy") result(p)
      import :: c_ptr, c_size_t
      type(c_ptr), value :: d, s
      integer(c_size_t), value :: n
      type(c_ptr) :: p
    end function st_memcpy
  end interface
contains
  logical function omp_is_initial_device()
    omp_is_initial_device = .true.
  end function omp_is_initial_device
  integer function omp_get_default_device()
    omp_get_default_device = 0
  end function omp_get_default_device
  integer function omp_get_initial_device()
    omp_get_initial_device = 0
  end function omp_get_initial_device
  type(c_ptr) function omp_target_alloc(n, dev)
    integer(c_size_t), value :: n
    integer, value :: dev
    omp_target_alloc = st_malloc(n)
  end function omp_target_alloc
  subroutine omp_target_free(p, dev)
    type(c_ptr), value :: p
    integer, value :: dev
    call st_free(p)
  end subroutine omp_target_free
  integer function omp_target_memcpy(d, s, n, do, so, dd, sd)
    type(c_ptr), value :: d, s
    integer(c_size_t), value :: n, do, so
    integer, value :: dd, sd
    type(c_ptr) :: r
    r = st_memcpy(d, s, n)
    omp_target_memcpy = 0
  end function omp_target_memcpy
end module omp_lib
"""
STUB_ACC = """module openacc
  implicit none
  integer, parameter :: acc_device_kind = 4
  integer(acc_device_kind), parameter :: acc_device_none = 0, &
    acc_device_default = 1, acc_device_host = 2, &
    acc_device_not_host = 3, acc_device_nvidia = 4
contains
  logical function acc_on_device(d)
    integer(acc_device_kind), value :: d
    acc_on_device = d == acc_device_host
  end function acc_on_device
end module openacc
"""
GFORTRAN = shutil.which("gfortran") or "/usr/tce/bin/gfortran"
GCC = shutil.which("gcc") or "/usr/tce/bin/gcc"


def _gf_build(prog, d: Path, flags: list[str], syntax_only: bool = False
              ) -> tuple[bool, str]:
    (d / "stub_omp.f90").write_text(STUB_OMP)
    (d / "stub_acc.f90").write_text(STUB_ACC)
    objs = []
    for name in ("stub_omp.f90", "stub_acc.f90"):
        r = run_group([GFORTRAN, "-c", name], cwd=d, timeout=300)
        if r.returncode:
            return False, f"stub: {r.stderr[:300]}"
        objs.append(name.replace(".f90", ".o"))
    for name, text in prog.files:
        (d / name).write_text(text)
    for name, text in prog.files:
        if name.endswith(".h"):
            continue
        if name.endswith(".c"):
            cmd = [GCC, "-std=c11", "-O1", "-c", name]
            if syntax_only:
                cmd = [GCC, "-std=c11", "-Wall", "-Werror=implicit",
                       "-fsyntax-only", name]
        else:
            cmd = [GFORTRAN, *flags, "-c", name]
            if syntax_only:
                cmd = [GFORTRAN, *flags, "-fsyntax-only", name]
        r = run_group(cmd, cwd=d,
                           timeout=1800)
        if r.returncode:
            err = [ln for ln in (r.stderr + r.stdout).splitlines()
                   if "rror" in ln]
            return False, f"{name}: " + (err[0] if err else
                                         r.stderr[:300]).strip()
        if not syntax_only:
            objs.append(re.sub(r"\.(f90|c)$", ".o", name))
        elif name.endswith(".f90"):
            # -fsyntax-only still writes .mod files the next file needs
            pass
    if syntax_only:
        return True, ""
    if any(n.endswith(".f90") for n, _ in prog.files):
        link = [GFORTRAN, *objs]
    else:
        link = [GCC, *[o for o in objs if not o.startswith("stub_")]]
    r = run_group(link + ["-o", "elided.out"], cwd=d, timeout=600)
    if r.returncode:
        return False, f"link: {r.stderr[:300]}"
    return True, ""


def elide(prog, timeout_s: int = 600) -> dict:
    """The program built by gfortran without OpenMP/OpenACC (directives
    are comments) and run on the host: its RESULT and K lines against the
    model (a model or generator defect if they differ)."""
    with tempfile.TemporaryDirectory(prefix="st_elide_",
                                     dir=node_local_tmp()) as d:
        d = Path(d)
        ok, why = _gf_build(prog, d, ["-O1", "-ffree-line-length-none",
                                      "-fcheck=bounds"])
        if not ok:
            return {"ok": False, "why": f"build: {why}"}
        try:
            r = run_group(["bash", "-c", 'ulimit -c 0; exec "$0"',
                                str(d / "elided.out")], cwd=d,
                               timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return {"ok": False, "why": "timeout"}
        info = parse_run(r.stdout)
        if r.returncode or len(info["result"]) != 1:
            return {"ok": False, "why": f"run rc={r.returncode}: "
                    f"{r.stderr[-300:]}"}
        cs = int(info["result"][0][0])
        valid = {k.name for k in prog.kernels if k.elision_valid}
        bad = sorted(k for k, v in info["k"].items()
                     if k in valid and prog.per_kernel.get(k) != v)
        whole = len(valid) == len(prog.kernels)
        ok = not bad and (cs == prog.expected or not whole)
        return {"ok": ok, "checksum": cs, "bad_kernels": bad,
                "checked": len(valid), "of": len(prog.kernels),
                "why": "" if ok else
                f"elision {cs} model {prog.expected}; kernels {bad}"}


def gate(prog, flang: bool = True, rules: bool = True) -> dict:
    """The legality gate of a stress program: gfortran -std=f2018
    -fsyntax-only (no OpenMP/OpenACC: the base language), AFAR flang's
    frontend with -fopenmp -fsyntax-only (OpenMP programs), and
    offload.engine.rules (OpenMP 5.2 / OpenACC 3.4 restrictions) on the
    Fortran text. Returns {"stage": "ok" | first failing stage, ...}."""
    res = {"stage": "ok", "detail": ""}
    with tempfile.TemporaryDirectory(prefix="st_gate_",
                                     dir=node_local_tmp()) as d:
        d = Path(d)
        ok, why = _gf_build(prog, d, ["-std=f2018"], syntax_only=True)
        if not ok:
            return {"stage": "gfortran", "detail": why}
    if rules and prog.lang == "f90":
        try:
            from offload.engine.rules import parse_program, violations
            text = "\n".join(t for n, t in prog.files if n.endswith(".f90"))
            v = 52 if prog.model == "omp" else 34
            found = violations(parse_program(text, v), v)
            if found:
                return {"stage": "rules", "detail": ", ".join(found)[:500]}
        except Exception as e:      # a grammar or parse limitation
            res["rules_note"] = f"{type(e).__name__}: {str(e)[:200]}"
    if rules and prog.lang == "c":
        try:
            from offload.engine.rules import parse_program, violations
            head = "\n".join(t for n, t in prog.files if n.endswith(".h"))
            found = []
            for n, t in prog.files:
                if n.endswith(".c"):
                    text = t.replace('#include "st.h"', head)
                    found += violations(parse_program(text, 52, "c"), 52)
            if found:
                return {"stage": "rules",
                        "detail": ", ".join(sorted(set(found)))[:500]}
        except Exception as e:
            res["rules_note"] = f"{type(e).__name__}: {str(e)[:200]}"
    if flang and prog.model == "omp" and prog.lang == "f90":
        why = flang_syntax(prog)
        if why:
            return {"stage": "flang", "detail": why}
    if flang and prog.lang == "c":
        why = clang_syntax(prog)
        if why:
            return {"stage": "clang", "detail": why}
    return res


def clang_syntax(prog) -> str | None:
    from offload.engine.toolchains import AFAR_BIN
    cl = f"{AFAR_BIN}/amdclang"
    if not Path(cl).exists():
        return None
    with tempfile.TemporaryDirectory(prefix="st_clang_",
                                     dir=node_local_tmp()) as d:
        for name, text in prog.files:
            (Path(d) / name).write_text(text)
        for name, _ in prog.files:
            if not name.endswith(".c"):
                continue
            r = run_group([cl, "-std=c11", "-fopenmp",
                                "-fopenmp-version=52", "-fsyntax-only", name],
                               cwd=d,
                               timeout=1800)
            if r.returncode:
                errs = [ln for ln in r.stderr.splitlines() if "error:" in ln]
                return f"{name}: " + (errs[0] if errs else
                                      r.stderr[:300]).strip()
    return None


def flang_syntax(prog) -> str | None:
    from offload.engine.toolchains import AFAR_BIN
    fl = f"{AFAR_BIN}/amdflang"
    if not Path(fl).exists():
        return None
    with tempfile.TemporaryDirectory(prefix="st_flang_",
                                     dir=node_local_tmp()) as d:
        for name, text in prog.files:
            (Path(d) / name).write_text(text)
            if not name.endswith(".f90"):
                continue
            r = run_group([fl, "-fopenmp", "-fopenmp-version=52",
                                "-fsyntax-only", name], cwd=d, timeout=1800)
            if r.returncode:
                errs = [ln for ln in r.stderr.splitlines()
                        if re.search(r":\d+:\d+: error:", ln)] or \
                    [ln for ln in r.stderr.splitlines() if "error:" in ln]
                return f"{name}: " + (errs[0] if errs else
                                      r.stderr[:300]).strip()
    return None


def write_rows(rows, path: Path) -> None:
    with open(path, "a") as fh:
        for r in rows:
            fh.write(json.dumps(r.as_dict() if hasattr(r, "as_dict") else r)
                     + "\n")
