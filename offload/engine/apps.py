"""The application corpus (data/bench/apps/): real open-source Fortran and C offload
codes, built and run per toolchain and memory mode. The outcome of every source
file, the link and every run (the code's own validation) is recorded, so a
failure traces to a file and, through the compiler's message, a line.

data/bench/apps/manifest.yaml names each application (repository, pinned commit,
licence, clone directory corpus/apps/<dir>, git-ignored) and its programs:
sources in compile order, defines, includes, per-vendor flags, libraries, runs
and the check (a regular expression a correct run prints, or ``check_fn``).
Stubs are in data/bench/apps/stubs/. Compiling follows offload.engine.toolchains plus
the program's settings; runs use offload.engine.harness._execute.

Per file: ``ok``, ``rejected``, ``ice``, ``timeout``, ``blocked``. Link: ``ok``
or ``rejected``. Per run: ``correct_on_device``, ``wrong_answer``, ``run_error``,
``crash``, ``timeout``. The program's outcome is that of its first failing stage."""
from __future__ import annotations

import dataclasses
import json
import os
import re
import shlex
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
BENCH = ROOT / "data" / "bench" / "apps"
MANIFEST = BENCH / "manifest.yaml"
CLONES = ROOT / "corpus" / "apps"
OUT = ROOT / "results" / "apps"

COMPILE_TIMEOUT_S = 1800
RUN_TIMEOUT_S = 600

# Fortran preprocessing of a lower-case .f90 (an .F90 is preprocessed by
# every compiler without it): the flag CMake's Fortran_PREPROCESS uses
PREPROCESS = {"afar": "-cpp", "cce": "-eZ", "nvhpc": "-Mpreprocess",
              "gcc": "-cpp"}
FAILING_RUN = ("wrong_answer", "run_error", "crash", "timeout")
INTRINSIC_MODULES = {"iso_fortran_env", "iso_c_binding", "omp_lib",
                     "omp_lib_kinds", "openacc", "ieee_arithmetic",
                     "ieee_exceptions", "ieee_features", "mpi", "mpi_f08"}


# --- the manifest ------------------------------------------------------------------

@dataclass
class Run:
    name: str
    args: str = ""
    check: str = ""             # regex a correct run prints
    check_fn: str = ""          # or offload.engine.apps.CHECKS[<name>]
    fail: str = ""              # a regex no correct run prints
    inputs: tuple = ()          # files copied into the run directory
    timeout_s: int = RUN_TIMEOUT_S


@dataclass
class AppProgram:
    id: str
    app: str
    lang: str                   # f90 | c
    model: str                  # omp | acc
    sources: list               # paths relative to the app clone
    defines: list = field(default_factory=list)
    includes: list = field(default_factory=list)
    flags: dict = field(default_factory=dict)   # vendor -> extra flags
    libs: str = ""
    stubs: list = field(default_factory=list)   # data/bench/apps/stubs/<file>
    runs: list = field(default_factory=list)
    order: str = "given"        # given | auto
    toolchains: list | None = None              # None: every applicable
    note: str = ""
    # what a correct run needs beyond the language: "unified_memory" (a
    # host allocation used on the device without requires: the copy mode
    # makes no promise for it, so copy-mode cells are not scored)
    needs: list = field(default_factory=list)
    # {status: legal | illegal | unknown, basis: text} (default legal: the
    # code as its project ships it, unless a decision says otherwise)
    legality: dict = field(default_factory=dict)


@dataclass
class App:
    id: str
    repo: str
    commit: str
    license: str
    dir: str
    programs: list
    note: str = ""

    @property
    def path(self) -> Path:
        return CLONES / self.dir


def load(path: Path = MANIFEST) -> dict:
    """app id -> App."""
    d = yaml.safe_load(path.read_text())
    apps = {}
    for a in d["apps"]:
        progs = []
        for p in a.get("programs") or ():
            runs = [Run(r["name"], str(r.get("args", "")), r.get("check", ""),
                        r.get("check_fn", ""), r.get("fail", ""),
                        tuple(r.get("inputs") or ()),
                        int(r.get("timeout_s", RUN_TIMEOUT_S)))
                    for r in p.get("runs") or ()]
            progs.append(AppProgram(
                p["id"], a["id"], p["lang"], p["model"], list(p["sources"]),
                list(p.get("defines") or ()), list(p.get("includes") or ()),
                dict(p.get("flags") or {}), p.get("libs", ""),
                list(p.get("stubs") or ()), runs, p.get("order", "given"),
                p.get("toolchains"), p.get("note", ""),
                list(p.get("needs") or ()), dict(p.get("legality") or {})))
        apps[a["id"]] = App(a["id"], a["repo"], a["commit"], a["license"],
                            a["dir"], progs, a.get("note", ""))
    return apps


def programs(apps: dict | None = None) -> dict:
    """program id -> AppProgram over every app."""
    apps = apps if apps is not None else load()
    return {p.id: p for a in apps.values() for p in a.programs}


def applicable(prog: AppProgram, toolchain: str) -> str | None:
    """None when `prog` can be built by `toolchain`, else why not: AFAR has
    no OpenACC; CCE's OpenACC is Fortran only."""
    from offload.engine.toolchains import TOOLCHAINS
    tc = TOOLCHAINS[toolchain]
    if prog.toolchains is not None and tc.base not in prog.toolchains:
        return "not in the program's toolchain list"
    if prog.model == "acc" and tc.kind == "afar":
        return "AFAR has no OpenACC"
    if prog.model == "acc" and tc.kind == "cce" and prog.lang == "c":
        return "CCE supports OpenACC for Fortran only"
    if prog.sources == ["@mfc"] and tc.kind == "gcc":
        # corpus/apps/MFC CMakeLists.txt: "MFC with GPU processing is not
        # currently compatible with GNU compilers"
        return "MFC's build refuses GPU offload with GNU compilers"
    return None


# --- Fortran module order ----------------------------------------------------------

_MOD_DEF = re.compile(r"^\s*module\s+(?!procedure\b)(\w+)\s*$", re.I | re.M)
_MOD_USE = re.compile(r"^\s*use\b(?:\s*,\s*(?:non_)?intrinsic\s*::|\s*::)?"
                      r"\s*(\w+)", re.I | re.M)


def module_order(files: dict) -> list:
    """The files (name -> text) in an order where every module is compiled
    before its users (stable: ties keep the given order); a cycle or an
    unknown module keeps the rest in the given order."""
    defines = {}
    for name, text in files.items():
        for m in _MOD_DEF.finditer(text):
            defines[m.group(1).lower()] = name
    deps = {name: {defines[u.group(1).lower()] for u in
                   _MOD_USE.finditer(text)
                   if u.group(1).lower() in defines and
                   defines[u.group(1).lower()] != name}
            for name, text in files.items()}
    out, done = [], set()
    pending = list(files)
    while pending:
        ready = [n for n in pending if deps[n] <= done]
        if not ready:
            ready = pending[:1]
        for n in ready:
            out.append(n)
            done.add(n)
        pending = [n for n in pending if n not in done]
    return out


def module_deps(files: dict) -> dict:
    """file -> the files defining the modules it uses (program files)."""
    defines = {}
    for name, text in files.items():
        for m in _MOD_DEF.finditer(text):
            defines[m.group(1).lower()] = name
    return {name: sorted({defines[u.group(1).lower()] for u in
                          _MOD_USE.finditer(text)
                          if u.group(1).lower() in defines and
                          defines[u.group(1).lower()] != name})
            for name, text in files.items()}


# --- compiler messages ---------------------------------------------------------------

_LOCS = [
    # clang / flang / craycc: path:line:col: error: msg
    re.compile(r"^(?P<file>[^\s:][^:]*):(?P<line>\d+):(?:\d+:)?\s*"
               r"(?:fatal )?error:\s*(?P<msg>.*)$", re.M),
    # CCE ftn: ftn-N ftn: ERROR UNIT, File = path, Line = L, Column = C
    re.compile(r"^ftn-\d+ (?:ftn|crayftn): (?:ERROR|INTERNAL)[^\n]*?File = "
               r"(?P<file>\S+?), Line = (?P<line>\d+)[^\n]*\n\s*(?P<msg>.*)$",
               re.M),
    # flang's MLIR lowering: loc("path":line:col): error: msg
    re.compile(r'loc\("(?P<file>[^"]+)":(?P<line>\d+):\d+\)(?: at [^:]*)?: '
               r'error: (?P<msg>.*)$', re.M),
    # nvfortran / nvc: NVFORTRAN-S-0155-msg (path: line)
    re.compile(r"^NV(?:FORTRAN|C|C\+\+)-[SF]-\d+-(?P<msg>.*?)\s*\("
               r"(?P<file>[^:()]+): (?P<line>\d+)\)\s*$", re.M),
    # nvc / EDG: "path", line N: error: msg
    re.compile(r'^"(?P<file>[^"]+)", line (?P<line>\d+): (?:catastrophic )?'
               r'error:\s*(?P<msg>.*)$', re.M),
]


def error_locations(text: str, src_name: str) -> list:
    """[{line, msg}] of the error messages about `src_name` (by base name)
    in a compiler's output, in order, without duplicates."""
    base = Path(src_name).name
    out, seen = [], set()
    hits = []
    for rx in _LOCS:
        for m in rx.finditer(text):
            if Path(m.group("file")).name != base:
                continue
            hits.append((m.start(), int(m.group("line")),
                         m.group("msg").strip()[:200]))
    for _, line, msg in sorted(hits):
        if (line, msg) not in seen:
            seen.add((line, msg))
            out.append({"line": line, "msg": msg})
    return out


def compile_outcome(toolchain: str, lang: str, rc: int | None,
                    text: str) -> tuple[str, str]:
    """(outcome, reason) of one compile: ok, timeout, ice (the harness's
    ICE patterns or a compiler killed by a signal), rejected."""
    from offload.engine import harness
    if rc is None:
        return "timeout", "compile timeout"
    if rc == 0:
        return "ok", ""
    found = harness.classify_message(toolchain, text, ("environment", "ice",
                                                       "not_implemented",
                                                       "error"), lang)
    if found and found[0] == "environment":
        return "harness_error", found[1][:300]
    if found and found[0] == "ice":
        return "ice", found[1][:300]
    if rc >= 128 or re.search(r"(?i)internal compiler error|stack dump|"
                              r"PLEASE submit a bug report|Segmentation "
                              r"fault|core dumped|signal \d+", text):
        line = next((ln for ln in text.splitlines() if re.search(
            r"(?i)internal|stack dump|bug report|segmentation|signal",
            ln)), "")
        return "ice", (line or f"rc={rc}")[:300]
    if found:
        return "rejected", (f"{found[0]}: {found[1]}")[:300]
    tail = [ln for ln in text.splitlines() if ln.strip()]
    return "rejected", (f"rc={rc}: " + (tail[-1] if tail else ""))[:300]


# --- toolchains ----------------------------------------------------------------------

def toolchain(name: str, prog: AppProgram, row_key: int | None = None):
    """The catalog toolchain with the program's language and model, for a
    memory mode when the machine selects modes by a compile flag."""
    from offload.engine.toolchains import TOOLCHAINS
    tc = dataclasses.replace(TOOLCHAINS[name], lang=prog.lang,
                             model=prog.model)
    if row_key is not None:
        tc = tc.for_mode(row_key)
    return tc


def compile_flags(tc, prog: AppProgram, src: str, opt: str) -> str:
    parts = [tc.flags(), opt]
    if prog.lang == "f90" and Path(src).suffix in (".f90", ".f95", ".f03",
                                                   ".f08") and \
            (prog.defines or prog.flags.get("cpp")):
        parts.append(PREPROCESS[tc.kind])
    parts += [prog.flags.get(tc.kind, ""), prog.flags.get("all", "")]
    parts += [f"-D{d}" for d in prog.defines]
    parts += [f"-I{shlex.quote(str(i))}" for i in prog.includes]
    return " ".join(p for p in parts if p)


@dataclass
class FileResult:
    file: str
    outcome: str
    reason: str = ""
    locs: list = field(default_factory=list)
    seconds: float = 0.0


def _script(tc, cmd: str, tmpdir: str) -> str:
    from offload.engine import harness
    return "\n".join(harness._setup(tc, tmpdir) + [cmd]) + "\n"


def source_paths(prog: AppProgram, app: App) -> list:
    """(source name as the program knows it, absolute path) in compile
    order: stubs first, then the program's sources."""
    if prog.sources == ["@mfc"]:     # built by tools/jobs/run_mfc.sh
        return []
    out = [(f"stubs/{s}", BENCH / "stubs" / s) for s in prog.stubs]
    out += [(s, (app.path / s) if not Path(s).is_absolute() else Path(s))
            for s in prog.sources]
    if prog.order == "auto":
        texts = {n: p.read_text(errors="replace") for n, p in out}
        order = module_order(texts)
        out = sorted(out, key=lambda x: order.index(x[0]))
    return out


def build(prog: AppProgram, app: App, toolchain_name: str, bdir: Path,
          row_key: int | None = None, opt: str = "-O2",
          timeout_s: int = COMPILE_TIMEOUT_S) -> dict:
    """Compile every source file of `prog` on its own (-c) in order, then
    link. A file whose module dependency failed is ``blocked`` (not
    compiled). Returns {files: [...], link: {...}, exe: path or None}."""
    from offload.engine import harness
    tc = toolchain(toolchain_name, prog, row_key)
    prog = dataclasses.replace(prog, includes=[
        str(i) if Path(i).is_absolute() else str(app.path / i)
        for i in prog.includes])
    if bdir.exists():
        shutil.rmtree(bdir)
    bdir.mkdir(parents=True)
    srcs = source_paths(prog, app)
    texts = {n: p.read_text(errors="replace") for n, p in srcs}
    deps = module_deps(texts) if prog.lang == "f90" else {}
    failed: set = set()
    files, objs = [], []
    for k, (name, path) in enumerate(srcs):
        bad = [d for d in deps.get(name, ()) if d in failed]
        if bad:
            files.append(FileResult(name, "blocked",
                                    "uses a module of " + ", ".join(bad)))
            failed.add(name)
            continue
        is_c = path.suffix in (".c",)
        ftc = dataclasses.replace(tc, lang="c") if is_c else tc
        obj = f"o{k:03d}_{path.stem}.o"
        flags = compile_flags(ftc, prog, str(path), opt)
        cmd = f"{ftc.compiler()} {flags} -c {shlex.quote(str(path))} -o {obj}"
        t0 = time.time()
        ex = harness._execute(_script(ftc, cmd, str(bdir)), bdir, timeout_s,
                              merge=True)
        secs = round(time.time() - t0, 1)
        (bdir / f"{obj}.log").write_text(cmd + "\n" + ex.stdout)
        oc, why = compile_outcome(toolchain_name, "c" if is_c else
                                  prog.lang, ex.rc, ex.stdout)
        locs = error_locations(ex.stdout, path.name) if oc != "ok" else []
        files.append(FileResult(name, oc, why, locs, secs))
        if oc == "ok":
            objs.append(obj)
        else:
            failed.add(name)
    res = {"files": [dataclasses.asdict(f) for f in files], "link": None,
           "exe": None, "flags": compile_flags(tc, prog, "x.F90", opt)}
    if failed:
        return res
    exe = "app.exe"
    libs = prog.libs
    if prog.lang == "c" and "-lm" not in libs:
        libs = (libs + " -lm").strip()
    cmd = f"{tc.compiler()} {tc.flags()} {opt} " + " ".join(objs) + \
        f" -o {exe} {libs}"
    t0 = time.time()
    ex = harness._execute(_script(tc, cmd, str(bdir)), bdir, timeout_s,
                          merge=True)
    (bdir / "link.log").write_text(cmd + "\n" + ex.stdout)
    if ex.rc == 0 and (bdir / exe).exists():
        res["link"] = {"outcome": "ok", "reason": "",
                       "seconds": round(time.time() - t0, 1)}
        res["exe"] = str(bdir / exe)
    else:
        oc, why = compile_outcome(toolchain_name, prog.lang, ex.rc,
                                  ex.stdout)
        if oc == "ok":
            oc, why = "rejected", "link: no executable"
        if oc == "rejected":
            found = harness.classify_message(toolchain_name, ex.stdout,
                                             ("link_undefined",), prog.lang)
            why = f"link: {found[1]}" if found else f"link: {why}"
        res["link"] = {"outcome": oc, "reason": why[:300],
                       "seconds": round(time.time() - t0, 1)}
    return res


# --- runs -------------------------------------------------------------------------------

def run_script(tc, exe: str, args: str, row_key: int, tmpdir: str,
               gpu: int | None = None) -> str:
    from offload.engine import harness
    lines = harness._setup(tc, tmpdir)
    lines += [f"export {k}={shlex.quote(v)}"
              for k, v in tc.run_env(row_key).items()]
    if gpu is not None and tc.kind != "nvhpc":
        lines.append(f"export ROCR_VISIBLE_DEVICES={gpu}")
    if tc.model == "acc":
        lines.append("unset OMP_TARGET_OFFLOAD")
    else:
        lines.append("export OMP_TARGET_OFFLOAD=mandatory")
    lines.append(f"exec {shlex.quote(exe)} {args}".rstrip())
    return "\n".join(lines) + "\n"


def judge_run(rc: int | None, out: str, run: Run) -> tuple[str, str]:
    """(outcome, reason) of one run of an application."""
    import signal
    tail = " ".join(out.split()[-30:])[-300:]
    if rc is None:
        return "timeout", "run timeout"
    if rc < 0 or rc in (134, 136, 139):
        sig = -rc if rc < 0 else rc - 128
        try:
            name = signal.Signals(sig).name
        except ValueError:
            name = f"signal {sig}"
        return "crash", f"crash: {name}: {tail}"
    if run.fail:
        m = re.search(run.fail, out, re.M)
        if m:
            line = out[out.rfind("\n", 0, m.start()) + 1:].split("\n")[0]
            return ("wrong_answer" if rc == 0 else "run_error"), \
                f"failure printed: {line.strip()[:200]}"
    if run.check_fn:
        ok, why = CHECKS[run.check_fn](out)
        if ok and rc == 0:
            return "correct_on_device", why
        if rc != 0:
            return "run_error", f"exit {rc}: {tail}"
        return "wrong_answer", why
    if run.check and re.search(run.check, out, re.M):
        if rc == 0:
            return "correct_on_device", f"check matched (exit 0)"
        return "run_error", f"check matched but exit {rc}: {tail}"
    if rc != 0:
        return "run_error", f"exit {rc}: {tail}"
    return "wrong_answer", f"check {run.check!r} not printed: {tail}"


def run_program(prog: AppProgram, app: App, toolchain_name: str, exe: str,
                mode: str, rdir: Path, gpu: int | None = None,
                repeats: int = 2) -> list:
    """Each run of the program twice (a disagreement keeps the worse
    outcome, reason 'flaky: ...'): [{name, outcome, reason, seconds}]."""
    from offload.engine import harness
    from offload.engine.confirm import machines as M
    from offload.engine.toolchains import TOOLCHAINS
    machine = M.load()[TOOLCHAINS[toolchain_name].machine]
    row_key = machine.row_key(mode)
    tc = toolchain(toolchain_name, prog,
                   row_key if machine.compile_time_modes else None)
    out = []
    for run in prog.runs:
        d = rdir / run.name
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        for inp in run.inputs:
            src = app.path / inp
            shutil.copy(src, d / Path(inp).name)
        trials = []
        t0 = time.time()
        for _ in range(repeats):
            ex = harness._execute(run_script(tc, exe, run.args, row_key,
                                             str(d), gpu), d, run.timeout_s,
                                  merge=True)
            (d / "run.log").write_text(ex.stdout[-200000:])
            trials.append(judge_run(ex.rc, ex.stdout, run))
            if trials[-1][0] == "timeout":
                break
        order = ("timeout", "crash", "run_error", "wrong_answer",
                 "correct_on_device")
        worst = min(trials, key=lambda t: order.index(t[0]))
        if len({t[0] for t in trials}) > 1:
            worst = (worst[0], "flaky: " + " | ".join(
                f"{o}: {w}"[:150] for o, w in trials))
        out.append({"name": run.name, "outcome": worst[0],
                    "reason": worst[1][:400],
                    "seconds": round(time.time() - t0, 1)})
    return out


def overall(rec: dict) -> tuple[str, str]:
    """(stage, outcome) of a program record: the first failing stage."""
    for f in rec.get("files") or ():
        if f["outcome"] not in ("ok", "blocked"):
            return "compile", f["outcome"]
    link = rec.get("link")
    if link is None:
        return "compile", "rejected"
    if link["outcome"] != "ok":
        return "link", link["outcome"]
    runs = rec.get("runs") or ()
    bad = [r for r in runs if r["outcome"] != "correct_on_device"]
    if bad:
        order = ("timeout", "crash", "run_error", "wrong_answer")
        return "run", min((r["outcome"] for r in bad), key=order.index)
    return ("run" if runs else "link"), "correct_on_device"


# --- run checks (check_fn) ---------------------------------------------------------------

def _num(rx: str, out: str):
    m = re.search(rx, out, re.M)
    try:
        return float(m.group(1).replace("D", "E").replace("d", "e")) if m \
            else None
    except ValueError:
        return None


def check_miniweather(out: str) -> tuple[bool, str]:
    """miniWeather's check_output.sh with its CMake tolerances: |d_mass| <
    1e-13 (double precision), d_te negative and |d_te| < 4.5e-5."""
    dm = _num(r"d_mass:\s*(\S+)", out)
    dte = _num(r"d_te:\s*(\S+)", out)
    if dm is None or dte is None:
        return False, "no d_mass / d_te line"
    if dm != dm or dte != dte:
        return False, f"NaN: d_mass {dm} d_te {dte}"
    if abs(dm) >= 1e-13:
        return False, f"mass change {dm} too large"
    if not dte < 0:
        return False, f"energy change {dte} not negative"
    if abs(dte) >= 4.5e-5:
        return False, f"energy change {dte} too large"
    return True, f"d_mass {dm} d_te {dte}"


CHECKS = {"miniweather": check_miniweather}


# --- records ----------------------------------------------------------------------------

def record(prog: AppProgram, toolchain_name: str, mode: str, built: dict,
           runs: list | None) -> dict:
    rec = {"program": prog.id, "app": prog.app, "lang": prog.lang,
           "model": prog.model, "toolchain": toolchain_name, "mode": mode,
           "files": built["files"], "link": built["link"],
           "runs": runs or [], "flags": built.get("flags", ""),
           "needs": list(prog.needs),
           "legality": prog.legality.get("status", "legal"),
           "host": os.uname().nodename,
           "date": time.strftime("%Y-%m-%dT%H:%M:%S")}
    from offload.engine.toolchains import TOOLCHAINS
    tc = TOOLCHAINS[toolchain_name]
    if tc.kind == "nvhpc":
        rec["runtime_libs"] = dict(tc.env).get("LD_LIBRARY_PATH", "")
    rec["stage"], rec["outcome"] = overall(rec)
    return rec


def read_records(path: Path) -> list:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines()
            if ln.strip()]


# --- MFC (its own build and test suite: tools/jobs/run_mfc.sh) ---------------------------------

MFC_COMPILER_ID = {"afar": "LLVMFlang", "cce": "Cray", "nvhpc": "NVHPC"}
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def mfc_dirs(toolchain: str, gpu: str) -> list:
    """The working directories of MFC runs of a toolchain and GPU model:
    results/apps/mfc/<tc>-<gpu> (Tuolumne) and results/apps/wingtip/mfc/
    <tc>-<gpu> (pulled from wingtip)."""
    out = []
    for base in (OUT / "mfc", OUT / "wingtip" / "mfc"):
        d = base / f"{toolchain}-{gpu}"
        if d.exists():
            out.append(d)
    return out


def mfc_staging(d: Path) -> Path | None:
    """The simulation build's staging directory of an MFC working copy."""
    f = d / "simulation_staging.txt"
    if f.exists():
        p = Path(f.read_text().strip())
        if not p.is_absolute():
            p = d / "MFC" / p
        if p.exists():
            return p
    for p in sorted((d / "MFC" / "build" / "staging").glob("*")):
        if (p / "fypp" / "simulation").is_dir() and any(
                (p / "fypp" / "simulation").glob("*.f90")):
            return p
    return None


def _mfc_make_k(text: str) -> list:
    """Per object file of `make -k -j1` output: (source name, ok?, error
    text): the file being built is the last "Building Fortran object"
    line; an error line after it belongs to it."""
    out, cur, errs = [], None, []
    for line in text.splitlines():
        m = re.search(r"Building Fortran object .*?/([^/\s]+?)\.o\b", line)
        if m:
            if cur is not None:
                out.append((cur, not errs, "\n".join(errs[:5])))
            cur, errs = m.group(1), []
            continue
        if cur is not None and re.search(
                r"(?i)\berror\b|internal compiler|ftn-\d+ ftn: (ERROR|"
                r"INTERNAL)|NVFORTRAN-[SF]|Segmentation|signal", line) \
                and "Error 1" not in line and "Error 2" not in line:
            errs.append(line.strip()[:300])
    if cur is not None:
        out.append((cur, not errs, "\n".join(errs[:5])))
    return out


_KERNEL_FN = re.compile(r"on function\s+'@\"?(\w+)\$(m_\w+?)_\$ck_L(\d+)_"
                        r"(\d+)")


def mfc_link_failure(btext: str) -> dict:
    """The link stage of a failed MFC build whose objects all compiled:
    ``ice`` when the (device) link crashed (an assertion, a signal, a
    "PLEASE submit a bug report"), else ``rejected``; ``locs``: the
    kernels the crash names (CCE: ``s_x$m_cbc_$ck_L597_13`` is the
    compute construct at line 597 of m_cbc.fpp)."""
    flat = re.sub(r"[\u2502\s]+", " ", btext)
    locs = []
    for m in _KERNEL_FN.finditer(flat.replace("\" ", "\"")):
        loc = {"file": f"{m.group(2)}.fpp", "line": int(m.group(3)),
               "msg": f"{m.group(1)} in {m.group(2)}"}
        if loc not in locs:
            locs.append(loc)
    ice = re.search(r"PLEASE submit a bug report|Assertion .* failed|"
                    r"Stack dump|Segmentation fault|signal \d+|"
                    r"malloc_consolidate|internal compiler error", flat, re.I)
    if ice:
        why = ice.group(0)
        p = re.search(r"Running pass '([^']+)'(?! on module)", flat)
        if p:
            why += f" (pass {p.group(1)})"
        return {"outcome": "ice", "reason": f"link: {why}"[:300],
                "seconds": 0, "locs": locs}
    reason = re.findall(r"(?m)^.*(?:Error|error).*$", btext)
    return {"outcome": "rejected", "reason": ("link: " + (
        reason[-1].strip() if reason else "failed"))[:300], "seconds": 0,
        "locs": locs}


def _mfc_tests(text: str) -> tuple:
    """(ran uuids, {failed uuid: error}) of an MFC test log."""
    text = _ANSI.sub("", text)
    ran = set(re.findall(r"^\s*\(\s*\d+/\s*\d+\)\s.*?\s([0-9A-F]{8})\s*$",
                         text, re.M))
    failed = {}
    for m in re.finditer(r"FAILED: .*?\n\s*UUID: ([0-9A-F]{8})(.*?)(?=\n\s*"
                         r"\n|\n\s*\(|\Z)", text, re.S):
        err = re.search(r"Error: (.*)", m.group(2))
        failed[m.group(1)] = (err.group(1).strip() if err else "")[:300]
    return ran | set(failed), failed


def mfc_outcome(err: str) -> str:
    """The outcome of a failed MFC test from its error line: ``crash`` when
    MFC failed to execute, ``timeout`` when the test suite's per-test limit
    ended it ("exceeded 1 hour timeout": the message names MFC's default
    limit, tools/jobs/run_mfc.sh sets 300 s), else ``wrong_answer`` (a golden
    file mismatch or NaN)."""
    if "Failed to execute" in err:
        return "crash"
    if re.search(r"exceeded .*timeout", err):
        return "timeout"
    return "wrong_answer"


def _mfc_finished(text: str) -> bool:
    return "mfc test rc=" in text or "Test Summary" in text


def mfc_dir_key(name: str):
    """(toolchain, gpu model) of an MFC working-copy directory named
    ``<toolchain>-<mp|acc>``; None for anything else, among them the
    ``<toolchain>-<gpu>-<variant>`` copies of tools/jobs/run_mfc.sh MFC_VARIANT
    (a workaround build: not a corpus record)."""
    from offload.engine.toolchains import TOOLCHAINS
    m = re.fullmatch(r"(.+)-(mp|acc)", name)
    if m is None or m.group(1) not in TOOLCHAINS:
        return None
    return m.group(1), m.group(2)


def mfc_records() -> list:
    """Program records (as ``record``) of every MFC working copy: the
    build (per file when it failed: make -k), the link, and each test of
    the subset as a run (pass, or the test suite's failure: wrong_answer
    for a golden-file mismatch or NaN, crash / run_error when MFC failed
    to execute)."""
    from offload.engine.confirm import machines as M
    from offload.engine.toolchains import TOOLCHAINS
    progs = programs()
    out = []
    for base in (OUT / "mfc", OUT / "wingtip" / "mfc"):
        if not base.exists():
            continue
        for d in sorted(base.iterdir()):
            key = mfc_dir_key(d.name) if d.is_dir() else None
            if key is None:
                continue
            tc, gpu = key
            prog = progs[f"mfc-sim-{'omp' if gpu == 'mp' else 'acc'}"]
            blog = d / "build.log"
            if not blog.exists():
                continue
            btext = _ANSI.sub("", blog.read_text(errors="replace"))
            rc = re.search(r"mfc build rc=(\d+)", btext)
            if rc is None:
                continue
            files, link = [], None
            if rc.group(1) == "0":
                link = {"outcome": "ok", "reason": "", "seconds": 0}
            else:
                mk = d / "make_k.log"
                for name, ok, err in _mfc_make_k(mk.read_text(
                        errors="replace")) if mk.exists() else []:
                    oc = "ok"
                    if not ok:
                        oc = "ice" if re.search(
                            r"(?i)internal|segmentation|signal|"
                            r"stack dump|bug report", err) else "rejected"
                    files.append({"file": name, "outcome": oc,
                                  "reason": err[:300], "locs": [],
                                  "seconds": 0})
                if not any(f["outcome"] != "ok" for f in files):
                    link = mfc_link_failure(btext)
            machine = M.load()[TOOLCHAINS[tc].machine]
            # NVHPC: MFC's build takes no memory-mode flag: its default,
            # separate memory (copy), only
            modes = ["copy"] if machine.compile_time_modes else \
                list(machine.modes)
            for mode in modes:
                tl = d / f"test.{mode}.log"
                runs = None
                if link and link["outcome"] == "ok":
                    ttext = tl.read_text(errors="replace") if tl.exists() \
                        else ""
                    # finished: the script's rc line, or MFC's summary
                    if not _mfc_finished(ttext):
                        continue
                    ran, failed = _mfc_tests(tl.read_text(errors="replace"))
                    # Test.<mode>.rerun.log, tests rerun alone
                    # (one at a time on an idle GPU: tools/jobs/run_mfc.sh
                    # rerun). Fix: the rerun replaces only a
                    # first-run timeout (the host's load: other builds on
                    # the same host); any other first-run failure stays the
                    # outcome (a failure that passes alone is still a
                    # failure), the rerun noted in its reason
                    rl = d / f"test.{mode}.rerun.log"
                    rtext = rl.read_text(errors="replace") if rl.exists() \
                        else ""
                    rran, rfailed = _mfc_tests(rtext) \
                        if _mfc_finished(rtext) else (set(), {})
                    runs = []
                    for u in sorted(ran):
                        first = failed.get(u)
                        if u in rran:
                            err = rfailed.get(u)
                            rer = mfc_outcome(err) if err is not None \
                                else "correct_on_device"
                            first_oc = mfc_outcome(first) if first \
                                is not None else "correct_on_device"
                            oc = rer if first_oc == "timeout" else first_oc
                            why = f"rerun alone: {err or 'passed'}; " \
                                f"first run: {first or 'passed'}"
                            if first_oc != "timeout":
                                why = f"rerun alone: {err or 'passed'} " \
                                    f"(not counted: only a first-run timeout" \
                                    f" is replaced); first run: " \
                                    f"{first or 'passed'}"
                            runs.append({"name": u, "outcome": oc,
                                         "reason": why[:300], "seconds": 0})
                        elif first is not None:
                            runs.append({"name": u, "outcome":
                                         mfc_outcome(first), "reason": first,
                                         "seconds": 0})
                        else:
                            runs.append({"name": u, "outcome":
                                         "correct_on_device", "reason": "",
                                         "seconds": 0})
                    if not runs:
                        continue
                built = {"files": files, "link": link, "flags": "mfc.sh"}
                rec = record(prog, tc, mode, built, runs)
                rec["host"] = "wingtip" if "wingtip" in str(base) else \
                    "tuolumne"
                out.append(rec)
    return out
