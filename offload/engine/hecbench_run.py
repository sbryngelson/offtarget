"""Build and run a HeCBench recipe (offload.engine.hecbench) with a catalog
toolchain; also the runner behind the ``hecbench`` campaign.

A build is one bash script: the toolchain's prelude, one ``-c`` compile per
source (toolchain flags, ``-O2``, the recipe's ``-std``, defines and include
directories) and a link with the recipe's libraries. Each step prints a
marker, so the first failing step classifies the build as ``rejected``
(diagnostic, unresolved symbol, ICE) or ``harness_error`` (environment,
compile at the time limit).

A run executes the program with its recipe arguments and
``OMP_TARGET_OFFLOAD=mandatory``. ``offload.engine.hecbench.judge_output``
judges the output against a serial host reference built without OpenMP
(stubs in data/bench/hecbench/stubs/omp.h), an output oracle only. Rows have the
harness's shape."""
from __future__ import annotations

import contextlib
import dataclasses
import os
import re
import shlex
import shutil
import signal
import time
from pathlib import Path

from offload.engine import hecbench as H

STUBS = H.BENCH / "stubs"
MARK = "@@STEP"
RUN_MARK = "@@HECBENCH-RUN"       # printed just before the program: the prelude's noise stays before it
LINK_STEP = "link"
RUN_TAIL = 400


# --- the commands -----------------------------------------------------------------------


def source_lang(src: str) -> str:
    return "c" if Path(src).suffix in H.C_EXT else "cpp"


def _std_ok(lang: str, std: str) -> bool:
    """A C++ standard is no flag for a C source and the reverse."""
    if not std:
        return False
    is_cxx = std.startswith(("c++", "gnu++"))
    return is_cxx == (lang == "cpp")


def compile_flags(recipe: dict, comp: dict, bench_dir: Path) -> str:
    lang = source_lang(comp["src"])
    parts = []
    std = comp.get("std") or recipe.get("std") or ""
    if _std_ok(lang, std):
        parts.append(f"-std={std}")
    parts += [f"-D{shlex.quote(d)}" for d in comp.get("defines", [])]
    parts += [f"-U{shlex.quote(u)}" for u in comp.get("undefs", [])]
    parts += [f"-I{shlex.quote(str((bench_dir / i).resolve()))}" for i in comp.get("includes", [])]
    parts += [f"-include {shlex.quote(str((bench_dir / f).resolve()))}"
              for f in comp.get("include_files", [])]
    return " ".join(parts)


def toolchain_for(name: str, lang: str, xnack: int | None):
    """The catalog toolchain compiled for OpenMP in ``lang`` (c | cpp), for the
    memory mode ``xnack`` where the machine selects modes by a compile flag."""
    from offload.engine.toolchains import TOOLCHAINS
    tc = dataclasses.replace(TOOLCHAINS[name], lang=lang, model="omp")
    return tc.for_mode(xnack) if xnack is not None else tc


def build_steps(recipe: dict, toolchain: str, xnack: int, clone: Path, opt: str = "-O2"):
    """[(step name, command)] of a build in the build directory: the compiles,
    then the link (the C++ driver when any source is C++)."""
    from offload.engine.toolchains import TOOLCHAINS
    bench_dir = clone / "src" / recipe["dir"]
    steps, objs = [], []
    for k, comp in enumerate(recipe["compiles"]):
        lang = source_lang(comp["src"])
        tc = toolchain_for(toolchain, lang, xnack)
        obj = f"o{k:02d}_{Path(comp['src']).stem}.o"
        cmd = (f"{tc.compiler()} {tc.flags()} {opt} {compile_flags(recipe, comp, bench_dir)} "
               f"-c {shlex.quote(str(bench_dir / comp['src']))} -o {obj}")
        steps.append((f"compile {comp['src']}", " ".join(cmd.split())))
        objs.append(obj)
    link_lang = "cpp" if any(source_lang(c["src"]) == "cpp" for c in recipe["compiles"]) else "c"
    tc = toolchain_for(toolchain, link_lang, xnack)
    libs = list(recipe.get("libs", []))
    if "m" not in libs:
        libs.append("m")
    libdirs = [f"-L{shlex.quote(d)}" for d in recipe.get("libdirs", [])]
    cmd = (f"{tc.compiler()} {tc.flags()} {opt} {' '.join(objs)} -o app.exe "
           f"{' '.join(libdirs)} {' '.join('-l' + shlex.quote(x) for x in libs)}")
    steps.append((LINK_STEP, " ".join(cmd.split())))
    return steps, link_lang


def build_script(tc, steps, tmpdir: str) -> str:
    """The bash script: prelude, then each step with a marker and its status;
    it stops at the first failing step."""
    from offload.engine import harness
    lines = harness._setup(tc, tmpdir)
    for name, cmd in steps:
        lines += [f"echo '{MARK} {name}'", cmd, "rc=$?", f"echo '{MARK}-rc '$rc",
                  "[ $rc -eq 0 ] || exit $rc"]
    return "\n".join(lines) + "\n"


_STEP_RX = re.compile(rf"^{re.escape(MARK)} (?!-rc)(.*)$", re.M)
_RC_RX = re.compile(rf"^{re.escape(MARK)}-rc (\d+)$", re.M)


def failing_step(text: str) -> tuple[str, int, str]:
    """(step, rc, that step's output) of the last step that printed a marker."""
    steps = list(_STEP_RX.finditer(text))
    if not steps:
        return "", 0, text
    last = steps[-1]
    body = text[last.end():].lstrip("\n")
    m = _RC_RX.search(body)
    rc = int(m.group(1)) if m else -1
    return last.group(1), rc, body[:m.start()] if m else body


# a link failure on an undefined symbol: the symbol is a compiler or offload-runtime one, or any other
_UNDEFINED = re.compile(r"undefined (?:reference to|symbol:?)\s*[`'\"]?([^'`\"\s)]+)")
_RUNTIME_SYMBOL = re.compile(r"__?(?:kmpc|tgt|omp|cray|nv|pgi|hip|gomp|builtin)|GOMP_|omp_|_cray|llvm\.|"
                             r"__(?:cxa|gxx|gnu)_|__acc|acc_")


def classify_build(toolchain: str, step: str, rc: int, text: str, timed_out: bool) -> tuple[str, str]:
    """(outcome, reason) of a failed build step in the harness's vocabulary."""
    from offload.engine import harness
    if timed_out:
        return "harness_error", "compile_timeout"
    if step == LINK_STEP:
        m = _UNDEFINED.search(text)
        if m:
            sym = m.group(1)
            kind = "runtime" if _RUNTIME_SYMBOL.match(sym) else "other"
            return "rejected", f"link_undefined_symbol: {kind} symbol {sym}"[:300]
    found = harness.classify_message(toolchain, text, harness.CATEGORY_ORDER[:-1], "c")
    if found is None:
        lines = [ln for ln in text.splitlines() if ln.strip()]
        err = next((ln for ln in lines if re.search(r"error|Error|ERROR", ln)), lines[-1] if lines else "")
        if rc >= 128 or re.search(r"(?i)internal compiler error|stack dump|PLEASE submit a bug|"
                                  r"Segmentation fault|core dumped", text):
            return "rejected", f"ice: {err.strip()[:300]}"
        return "rejected", f"diagnostic: {err.strip()[:300]}"
    cat, line = found
    if cat == "environment":
        return "harness_error", f"environment: {line[:300]}"
    return "rejected", f"{harness.CODES[cat]}: {line[:300]}"


# --- running -----------------------------------------------------------------------------


def run_args(recipe: dict, bench_dir: Path) -> list[str]:
    """The recipe's arguments; one that names a file of the repository is made
    absolute (the run directory is not the benchmark's)."""
    out = []
    for a in recipe.get("run_args", []):
        p = bench_dir / a
        out.append(str(p.resolve()) if H._file_like(a) and p.exists() else a)
    return out


def prepare_run_dir(rdir: Path, bench_dir: Path) -> None:
    """A directory that links every file of the benchmark's own, so a program
    that reads a file next to it finds it, and writes its output here."""
    rdir.mkdir(parents=True, exist_ok=True)
    for p in bench_dir.iterdir():
        dst = rdir / p.name
        if not dst.exists():
            try:
                dst.symlink_to(p.resolve())
            except OSError:
                pass


def run_script(tc, exe: str, args: list[str], xnack: int, tmpdir: str, gpu: int | None = None) -> str:
    from offload.engine import harness
    from offload.engine.toolchains import registry
    lines = harness._setup(tc, tmpdir)
    lines += [f"export {k}={shlex.quote(v)}" for k, v in tc.run_env(xnack).items()]
    if gpu is not None and registry().arches[tc.arch]["gpu"] == "amd":
        lines.append(f"export ROCR_VISIBLE_DEVICES={gpu}")
    lines.append("export OMP_TARGET_OFFLOAD=mandatory")
    lines.append(f"echo {RUN_MARK}")
    lines.append(f"exec {shlex.quote(exe)} " + " ".join(shlex.quote(a) for a in args))
    return "\n".join(lines) + "\n"


def judge_run(rc: int | None, out: str, ref_out: str | None, timeout_s: int) -> tuple[str, str]:
    """(outcome, reason) of one run in the harness's vocabulary: ``wrong_answer``
    with a ``timeout``, ``crash:`` or ``exit_status`` head is a time-out, a crash
    or a run error (offload.engine.confirm.model.outcome_of_result)."""
    tail = " ".join(out.split()[-30:])[-RUN_TAIL:]
    if rc is None:
        return "wrong_answer", f"timeout: the run did not end in {timeout_s} s"
    if rc < 0 or rc in (134, 136, 139):
        sig = -rc if rc < 0 else rc - 128
        try:
            name = signal.Signals(sig).name
        except ValueError:
            name = f"signal {sig}"
        return "wrong_answer", f"crash: {name}: {tail}"
    if rc != 0:
        return "wrong_answer", f"exit_status={rc}: {tail}"
    ok, why = H.judge_output(out, ref_out)
    if ok:
        return "correct_on_device", why
    return "wrong_answer", why


@contextlib.contextmanager
def gpu_slot(gpu: int | None):
    """At most ``HECBENCH_SLOTS`` (default 2) programs run on one AMD GPU at a time on this
    node, across every worker and process (file locks under the temporary directory), so
    that a run's time is not the contention of thirty compiles' neighbours. NVIDIA runs take
    the harness's run lock (COMPLIANT_RUN_SLOTS) instead; ``gpu`` None takes no slot."""
    if gpu is None:
        yield
        return
    import fcntl
    import tempfile
    n = int(os.environ.get("HECBENCH_SLOTS") or 2)
    base = os.path.join(tempfile.gettempdir(), f"hecbench-{os.getuid()}-gpu{gpu}")
    fds = [os.open(f"{base}.{k}.lock", os.O_CREAT | os.O_RDWR, 0o600) for k in range(n)]
    held = None
    try:
        while held is None:
            for fd in fds:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    held = fd
                    break
                except OSError:
                    continue
            else:
                time.sleep(0.2)
        yield
    finally:
        if held is not None:
            fcntl.flock(held, fcntl.LOCK_UN)
        for fd in fds:
            os.close(fd)


def row_base(program_id: str, toolchain: str, xnack: int, opt: str, flags: str) -> dict:
    from offload.engine import harness
    from offload.engine.toolchains import TOOLCHAINS, device_of
    tc = TOOLCHAINS[toolchain]
    return dict(program_id=program_id, toolchain=toolchain, xnack=xnack, opt=opt, flags=flags,
                device=device_of(tc), machine=tc.machine, arch=tc.arch, model="omp",
                lang="cpp", compiler=harness.compiler_version(tc), rocm=harness._rocm(tc))


def build_and_run(recipe: dict, toolchain: str, xnack: int, clone: Path, ref_out: str | None,
                  build_dir=None, opt: str = "-O2", timeout_s: int | None = None,
                  compile_timeout_s: int = H.COMPILE_TIMEOUT_S, repeats: int = 1,
                  gpu: int | None = None, keep: bool = False, prebuilt: dict | None = None) -> dict:
    """One cell: compile, link and run ``recipe`` with ``toolchain`` in memory mode
    ``xnack`` -> a result row (the harness's fields; ``oracle`` names how the output
    was judged). ``repeats`` runs: a failing first run is repeated once to mark a
    flaky one. On a machine whose memory modes are chosen at run time one build serves
    every mode: ``keep`` leaves a successful build's directory (row key ``_kept``) and
    ``prebuilt`` ({tmp, clog}) runs in such a directory and removes it."""
    from offload.engine import harness
    timeout_s = timeout_s or H.RUN_TIMEOUT_S
    bench_dir = clone / "src" / recipe["dir"]
    steps, link_lang = build_steps(recipe, toolchain, xnack, clone, opt)
    tc = toolchain_for(toolchain, link_lang, xnack)
    base = row_base(recipe["id"], toolchain, xnack, opt, steps[0][1].split(" -c ")[0][:300])
    tmp = Path(prebuilt["tmp"]) if prebuilt else harness._build_dir(build_dir)
    keep_dir = False
    t0 = time.time()

    def provenance(outcome):
        return harness._provenance(tc, xnack, str(tmp), base["flags"], harness.Outcome(outcome))

    def scrub(text):
        return text.replace(str(tmp), "<tmpdir>").replace(tmp.name, "<tmpdir>")
    try:
        if prebuilt:
            clog = prebuilt["clog"]
            build = harness._Exec(0, "", "")
        else:
            build = harness._execute(build_script(tc, steps, str(tmp)), tmp, compile_timeout_s, merge=True)
            clog = f"--- build (rc={build.rc}) ---\n" + harness._clip(build.stdout)

        def row(outcome, reason, stdout="", flaky=False, **extra):
            return {**base, "outcome": outcome, "reason": scrub(reason), "flaky": flaky,
                    "stdout": scrub(harness._clip(stdout)), "stderr": scrub(clog),
                    "oracle": H.oracle_kind(ref_out), "task_s": round(time.time() - t0, 1),
                    **provenance(outcome), **extra}
        if build.timed_out or build.rc != 0:
            step, rc, body = failing_step(build.stdout)
            out, why = classify_build(toolchain, step, rc, body, build.timed_out)
            return row(out, why, stage="link" if step == LINK_STEP else "compile")
        exe = tmp / "app.exe"
        if not exe.is_file():
            return row("harness_error", "no_executable: the build exited 0 but wrote no executable")
        rdir = tmp / "run"
        prepare_run_dir(rdir, bench_dir)
        args = run_args(recipe, bench_dir)
        keep_dir = keep
        trials = []
        for k in range(max(1, repeats)):
            with gpu_slot(gpu):
                ex = harness._execute(run_script(tc, str(exe), args, xnack, str(rdir), gpu), rdir, timeout_s,
                                      merge=True)
            out = ex.stdout.split(RUN_MARK, 1)[-1].lstrip("\n")
            trials.append((judge_run(ex.rc if not ex.timed_out else None, out, ref_out, timeout_s), out))
            if trials[-1][0][0] == "correct_on_device" and repeats == 1:
                break
            if "timeout" in trials[-1][0][1]:
                break
        (outcome, reason), stdout = trials[0]
        flaky = len({t[0] for t in trials}) > 1
        if flaky:
            reason += "; repeats: " + " | ".join(f"{t[0][0]}: {t[0][1]}"[:150] for t in trials)
        extra = {"_kept": str(tmp)} if keep_dir else {}
        return row(outcome, reason, stdout, flaky, stage="run", **extra)
    finally:
        if not keep_dir:
            shutil.rmtree(tmp, ignore_errors=True)


# --- the serial host reference -----------------------------------------------------------


def reference_commands(recipe: dict, clone: Path):
    """[(name, command)] of the serial host build: the node's C and C++
    compilers, no OpenMP, the serial runtime stubs first on the include path."""
    bench_dir = clone / "src" / recipe["dir"]
    steps, objs = [], []
    for k, comp in enumerate(recipe["compiles"]):
        lang = source_lang(comp["src"])
        cc = "gcc" if lang == "c" else "g++"
        obj = f"r{k:02d}.o"
        steps.append((f"compile {comp['src']}",
                      f"{cc} -O1 -w -I{shlex.quote(str(STUBS))} {compile_flags(recipe, comp, bench_dir)} "
                      f"-c {shlex.quote(str(bench_dir / comp['src']))} -o {obj}"))
        objs.append(obj)
    drv = "g++" if any(source_lang(c["src"]) == "cpp" for c in recipe["compiles"]) else "gcc"
    libs = list(recipe.get("libs", []))
    if "m" not in libs:
        libs.append("m")
    steps.append((LINK_STEP, f"{drv} {' '.join(objs)} -o ref.exe " +
                  " ".join(f"-L{shlex.quote(d)}" for d in recipe.get("libdirs", [])) + " " +
                  " ".join("-l" + x for x in libs)))
    return steps


def serial_reference(recipe: dict, clone: Path, timeout_s: int = H.REF_TIMEOUT_S) -> dict:
    """{ok, out, why}: the serial host build's output for the recipe's arguments
    (``ok`` false when it does not build or run: the oracle is then none)."""
    from offload.engine import harness
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="hecref_"))
    try:
        steps = reference_commands(recipe, clone)
        script = "\n".join(["ulimit -c 0"] + [
            ln for name, cmd in steps for ln in (f"echo '{MARK} {name}'", cmd, "rc=$?",
                                                 f"echo '{MARK}-rc '$rc", "[ $rc -eq 0 ] || exit $rc")]) + "\n"
        b = harness._execute(script, tmp, 600, merge=True)
        if b.timed_out or b.rc != 0:
            step, rc, body = failing_step(b.stdout)
            return {"ok": False, "out": "", "why": f"host build failed at {step}"}
        bench_dir = clone / "src" / recipe["dir"]
        rdir = tmp / "run"
        prepare_run_dir(rdir, bench_dir)
        args = " ".join(shlex.quote(a) for a in run_args(recipe, bench_dir))
        r = harness._execute(f"ulimit -c 0\nexec {shlex.quote(str(tmp / 'ref.exe'))} {args}\n", rdir,
                             timeout_s, merge=True)
        if r.timed_out or r.rc != 0:
            return {"ok": False, "out": "", "why": "host run failed" if not r.timed_out else "host run timeout"}
        return {"ok": True, "out": r.stdout[-20000:], "why": ""}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- the runner of the campaign -----------------------------------------------------------


class HecbenchRunner:
    """The campaign's runner (offload.engine.campaign.Run calls ``prerun``, ``run`` and
    ``rerun``). ``prerun`` stands for the legality pre-run of the generated
    campaigns: a benchmark that the recipe procedure excluded for a non-compiler
    reason is refused with that reason, and for the others the serial host
    reference is built and run (an output oracle, stored with the row). ``witness``
    has no meaning for real code: evidence is the gate plus a compiler of
    another family running the same program correctly (offload.engine.hecbench_report)."""
    parallel = "process"

    def __init__(self, camp, clone: Path | None = None):
        import itertools
        self.camp = camp
        self.clone = Path(clone) if clone else H.CLONE
        self._turn = itertools.count()
        import atexit
        import threading
        self._guard, self._locks, self._built, self._kept = threading.Lock(), {}, {}, []
        atexit.register(lambda: [shutil.rmtree(d, ignore_errors=True) for d in self._kept])

    def _gpu(self) -> int | None:
        """The AMD GPU of the next run: the workers take the node's GPUs in turn
        (HECBENCH_GPUS overrides the detected count); NVIDIA runs are placed by
        CUDA_VISIBLE_DEVICES and the run lock of the wingtip scripts."""
        from offload.engine.toolchains import detect_gpu_count
        if getattr(self, "_ngpu", None) is None:
            self._ngpu = int(os.environ.get("HECBENCH_GPUS") or detect_gpu_count() or 1)
        return next(self._turn) % self._ngpu if self._ngpu > 1 else None

    def prerun(self, p) -> dict:
        r = p.recipe
        if r["status"] != "ok":
            return {"id": p.id, "ok": False, "rules": False,
                    "reasons": [f"{r['status']}: {r['reason']}"], "ref": None, "afar_fe": None}
        ref = serial_reference(r, self.clone)
        return {"id": p.id, "ok": True, "rules": True, "reasons": [], "afar_fe": None,
                "ref": ref, "oracle": H.oracle_kind(ref["out"] if ref["ok"] else None)}

    def witness(self, p) -> dict:
        return {"program": p.id, "result": "error",
                "message": "no independent front end for real code: the cross-family rule is "
                           "applied to the run rows"}

    def run(self, prog, toolchain: str, xnack: int, *, version: int, timeout_s: int,
            opt: str = "-O2") -> dict:
        """One cell. Where the memory mode is chosen at run time (AMD) the program is built
        once per toolchain and run in each mode; the second mode's row repeats a failed
        build's row."""
        from offload.engine.toolchains import TOOLCHAINS
        args = (prog.recipe, toolchain, xnack, self.clone, prog.reference_output())
        kw = dict(opt=opt, timeout_s=timeout_s, gpu=self._gpu())
        if TOOLCHAINS[toolchain].compile_time_modes():
            return build_and_run(*args, **kw)
        key = (prog.id, toolchain, opt)
        with self._lock(key):
            st = self._built.get(key)
            if st is None:
                r = build_and_run(*args, keep=True, **kw)
                kept = r.pop("_kept", None)
                self._built[key] = {"tmp": kept, "clog": r["stderr"], "row": dict(r)}
                if kept:
                    self._kept.append(kept)
                return r
            del self._built[key]
            if st["tmp"] is None:                  # the build failed: the same failure in this mode
                return {**st["row"], "xnack": xnack}
            self._kept.remove(st["tmp"])
            return build_and_run(*args, prebuilt=st, **kw)

    def _lock(self, key):
        import threading
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())

    def rerun(self, prog, toolchain: str, xnack: int, env: dict, *, version: int, timeout_s: int,
              opt: str = "-O2") -> dict:
        from offload.engine import gate_run as GR
        # one build serves both AMD modes, so both cells record the same build directory: each mode
        # reruns in its own (the path's characters, which environment (b) varies, are kept)
        env = {**env, "path": f"{env['path']}_m{xnack}"}
        if os.path.isdir(env["path"]) and os.path.basename(env["path"]).startswith(
                ("GATE", "hecbench_", "harness_")):
            shutil.rmtree(env["path"], ignore_errors=True)    # a leftover of an interrupted rerun
        t0 = time.time()
        d = build_and_run(prog.recipe, toolchain, xnack, self.clone, prog.reference_output(),
                          build_dir=env["path"], opt=opt, timeout_s=timeout_s, gpu=self._gpu())
        out = {k: d.get(k) for k in ("outcome", "reason", "flaky", "stdout", "toolchain_build",
                                     "build_dir", "git_rev")}
        out["stdout"] = (out["stdout"] or "")[-400:]
        out["compile_log"] = (d.get("stderr") or "")[-1500:]
        rr = {**GR._base(env, t0), **out}
        if os.environ.get("COMPLIANT_RUN_SLOTS"):     # wingtip: (c) is another GPU
            rr["node"] = f"{rr.get('node', '')}:gpu{os.environ.get('CUDA_VISIBLE_DEVICES', 'all')}"
        return rr
