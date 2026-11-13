"""Compile, run and classify fuzz programs on every toolchain.

``run_program`` compiles one program on each toolchain (afar, cce19, cce20,
cce21; ``-O2``; ``HSA_XNACK=1``) and classifies the compile with
``offload.engine.harness.classify_message``. A program that compiled runs with
``OMP_TARGET_OFFLOAD=mandatory`` and must end with
``RESULT checksum=<int> ran_on_host=<0|1>`` (``FUZZ_RESULT``).
Each toolchain gets one of ``CLASSES`` (``agree``, ``wrong_code``,
``host_fallback``, ``ice``, ``harness_error``, ...). The reference is the
model value (``FuzzProgram.expected``) checked against a host run
(``OMP_TARGET_OFFLOAD=disabled``). If that run fails or disagrees, every host
build and the sequential elision (``offload.engine.expected``) are tried and
``host_verdict`` rules the program ``valid`` or ``noncompliant`` (a generator
or model defect). ``recheck_host`` applies the rule to a finished campaign. A run not classified ``agree`` is
repeated; differing results are ``flaky`` and take the worst class."""
from __future__ import annotations

import dataclasses
import json
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from offload.engine import harness
from offload.engine.fuzz import GEN_VERSION, FuzzProgram, check, generate
from offload.engine.toolchains import (GFX942_TOOLCHAINS, TOOLCHAINS, Toolchain,
                                   family)

# the campaigns' toolchains: the gfx942 headline toolchains (catalog/toolchains.yaml)
TOOLCHAIN_ORDER = GFX942_TOOLCHAINS
OPT = "-O2"
XNACK = 1
CLASSES = ("agree", "compile_reject", "ice", "wrong_code", "host_fallback",
           "timeout", "run_error", "harness_error")
WORST_FIRST = ("harness_error", "wrong_code", "run_error", "timeout",
               "host_fallback", "agree")
FUZZ_RESULT = re.compile(r"^RESULT checksum=(-?\d+) ran_on_host=([01])\s*$",
                         re.M)
RUN_TIMEOUT_S = 60
COMPILE_TIMEOUT_S = 600
RERUNS = 3


@dataclass
class Run:
    """One execution of a binary: `kind` is "ok" (one RESULT line, exit
    0), "timeout", "env" (an environment failure) or "fail"."""
    kind: str
    checksum: int | None = None
    host: int | None = None
    why: str = ""
    stdout: str = ""
    stderr: str = ""

    @property
    def key(self) -> tuple:
        return (self.kind, self.checksum, self.host, self.why)


@dataclass
class TcResult:
    toolchain: str
    cls: str
    reason: str
    checksum: int | None = None
    ran_on_host: int | None = None
    host_checksum: int | None = None
    flaky: bool = False
    runs: list = field(default_factory=list)
    note: str = ""
    output: str = ""
    compile_s: float = 0.0
    run_s: float = 0.0
    host_why: str = ""         # why the host run failed (host_checksum None)
    # Provenance (offload.engine.provenance; "" in older records)
    build_dir: str = ""
    node: str = ""
    toolchain_build: str = ""
    flags: str = ""
    env_hash: str = ""
    git_rev: str = ""
    gate: str = ""


def _parse(ex) -> Run:
    if ex.timed_out:
        return Run("timeout", why="timeout", stdout=ex.stdout,
                   stderr=ex.stderr)
    found = FUZZ_RESULT.findall(ex.stdout)
    if ex.rc == 0 and len(found) == 1:
        return Run("ok", int(found[0][0]), int(found[0][1]),
                   stdout=ex.stdout, stderr=ex.stderr)
    if ex.rc is not None and ex.rc < 0:
        import signal
        try:
            why = f"crash: {signal.Signals(-ex.rc).name}"
        except ValueError:
            why = f"crash: signal {-ex.rc}"
    elif ex.rc != 0:
        why = f"exit_status: {ex.rc}"
    elif len(found) > 1:
        why = "multiple_result_lines"
    else:
        why = "no_result_line"
    return Run("fail", why=why, stdout=ex.stdout, stderr=ex.stderr)


def execute(tc: Toolchain, exe: Path, tmp: Path, offload: str,
            timeout_s: int = RUN_TIMEOUT_S) -> Run:
    """One run of `exe` with OMP_TARGET_OFFLOAD=`offload` ("unset": not
    set) under HSA_XNACK=1."""
    script = harness.run_script(
        tc.for_mode(XNACK), str(exe), XNACK, offload == "mandatory",
        str(tmp),
        offload=None if offload in ("mandatory", "unset") else offload)
    ex = harness._execute(script, tmp, timeout_s)
    run = _parse(ex)
    if run.kind == "fail":
        env = harness._env_failure(tc, ex)
        if env:
            run.kind, run.why = "env", env
    return run


def classify_run(tc: Toolchain, exe: Path, tmp: Path, expected: int,
                 timeout_s: int = RUN_TIMEOUT_S) -> tuple[str, str, Run]:
    """(class, reason, run) of one trial: the mandatory run, and when it
    fails the run without OMP_TARGET_OFFLOAD (as offload.engine.harness)."""
    first = execute(tc, exe, tmp, "mandatory", timeout_s)
    if first.kind == "timeout":
        return "timeout", "timeout", first
    if first.kind == "env":
        return "harness_error", first.why, first
    if first.kind == "ok":
        return judge(first, expected), describe(first, expected), first
    second = execute(tc, exe, tmp, "unset", timeout_s)
    second.stderr = first.stderr + "\n--- without mandatory ---\n" + \
        second.stderr
    if second.kind == "env":
        return "harness_error", f"{second.why}; mandatory run: {first.why}", \
            second
    if second.kind != "ok":
        return "run_error", f"{first.why}; without mandatory: {second.why}", \
            second
    if second.host == 1:
        cls = "host_fallback" if second.checksum == expected else \
            "wrong_code"
        return cls, (f"mandatory_refused: {first.why}; without mandatory: "
                     f"{describe(second, expected)}"), second
    return "run_error", (f"mandatory_failed_device_pass_without: "
                         f"{first.why}; without mandatory: "
                         f"{describe(second, expected)}"), second


def judge(run: Run, expected: int) -> str:
    if run.checksum != expected:
        return "wrong_code"
    return "host_fallback" if run.host == 1 else "agree"


def describe(run: Run, expected: int) -> str:
    text = f"checksum={run.checksum} ran_on_host={run.host}"
    if run.checksum != expected:
        text += f" expected={expected}"
    return text


def compile_program(tc: Toolchain, src: Path, exe: Path, tmp: Path,
                    timeout_s: int = COMPILE_TIMEOUT_S
                    ) -> tuple[str | None, str, str, str]:
    """(class or None if it compiled, reason, note, compiler output). A
    bundle (several files, offload.engine.fuzz_base.split_bundle) is written
    file by file next to `src` and compiled one translation unit at a time,
    then linked."""
    from offload.engine.fuzz_base import split_bundle
    tc = tc.for_mode(XNACK)  # NVHPC builds per memory mode
    files = split_bundle(src.read_text()) if src.is_file() else None
    if files:
        for name, text in files:
            (tmp / name).write_text(text)
        script = harness.compile_set_script(tc, [n for n, _ in files],
                                            str(exe), OPT, str(tmp))
    else:
        script = harness.compile_script(tc, str(src), str(exe), OPT,
                                        str(tmp))
    build = harness._execute(script, tmp, timeout_s, merge=True)
    out = harness._clip(build.stdout)
    if build.timed_out:
        return "timeout", "compile_timeout", "", out
    if build.rc != 0:
        found = harness.classify_message(tc.name, build.stdout,
                                         harness.CATEGORY_ORDER[:-1])
        if found is None:
            return "harness_error", \
                f"unclassified_compile_failure: rc={build.rc}", "", out
        cat, line = found
        if cat == "environment":
            return "harness_error", f"environment: {line}", "", out
        if cat == "ice":
            return "ice", f"ice: {line}", "", out
        code = {"not_implemented": "not_implemented",
                "link_undefined": "link_undefined_symbol",
                "error": "diagnostic"}[cat]
        return "compile_reject", f"{code}: {line}", "", out
    if not exe.is_file():
        return "harness_error", "no_executable", "", out
    notes = []
    ign = harness.classify_message(tc.name, build.stdout, ("ignored",))
    if ign:
        notes.append(f"ignored: {ign[1]}")
    for name, pat in harness.NOTES.get(
            family(tc.name) if tc.kind == "cce" else tc.name, {}).items():
        if re.search(pat, build.stdout, re.M):
            notes.append(f"note: {name}")
    return None, "", "; ".join(notes), out


def _scrub(text: str, tmp: Path) -> str:
    return text.replace(str(tmp), "<tmpdir>").replace(tmp.name, "<tmpdir>")


def run_toolchain(prog: FuzzProgram, tc: Toolchain, tmp: Path,
                  reruns: int = RERUNS, timeout_s: int = RUN_TIMEOUT_S
                  ) -> tuple[TcResult, Path | None]:
    """Compile and run `prog` on `tc` in `tmp` (kept for the host
    reference); the executable is returned when it compiled."""
    src, exe = tmp / f"{prog.id}.f90", tmp / f"{prog.id}.out"
    src.write_text(prog.source)
    t0 = time.time()
    cls, reason, note, out = compile_program(tc, src, exe, tmp)
    ct = time.time() - t0
    if cls is not None:
        return TcResult(tc.name, cls, _scrub(reason, tmp), note=note,
                        output=_scrub(out, tmp), compile_s=ct,
                        **_provenance(tc, tmp, cls)), None
    t1 = time.time()
    cls, reason, run = classify_run(tc, exe, tmp, prog.expected, timeout_s)
    trials = [(cls, reason, run)]
    if cls != "agree":
        for _ in range(reruns if cls != "timeout" else 1):
            trials.append(classify_run(tc, exe, tmp, prog.expected,
                                       timeout_s))
    flaky = len({(c, r.checksum, r.host) for c, _, r in trials}) > 1
    cls, reason, run = min(trials, key=lambda t: WORST_FIRST.index(t[0]))
    if flaky:
        reason += "; repeats: " + " | ".join(f"{c}: {r}"
                                             for c, r, _ in trials)
    res = TcResult(tc.name, cls, _scrub(reason, tmp), run.checksum,
                   run.host, flaky=flaky,
                   runs=[f"{c}: {r}" for c, r, _ in trials], note=note,
                   output=_scrub((out + "\n" + run.stderr)[-6000:], tmp)
                   if cls != "agree" else "",
                   compile_s=ct, run_s=time.time() - t1,
                   **_provenance(tc, tmp, cls))
    return res, exe


def _provenance(tc: Toolchain, tmp: Path, cls: str) -> dict:
    """The provenance fields of a fuzz result."""
    from offload.engine import provenance as PV
    tc = tc.for_mode(XNACK)
    try:
        env = dict(tc.run_env(XNACK))
    except ValueError:
        env = {}
    env["OMP_TARGET_OFFLOAD"] = "mandatory"
    return PV.fields(tc, str(tmp), f"{tc.flags()} {OPT}", env,
                     cls not in ("agree", "harness_error"))


@dataclass
class ProgramResult:
    seed: int
    gen_version: str
    check: str                 # ok | rules | gfortran | flang | error
    check_detail: str = ""
    expected: int | None = None
    features: list = field(default_factory=list)
    kernels: list = field(default_factory=list)
    flags: int = 0
    lines: int = 0
    results: dict = field(default_factory=dict)   # toolchain -> TcResult
    host_ref: int | None = None
    host_ref_tc: str | None = None
    host_mismatch: bool = False     # the reference host run disagreed
    host_ref_failed: bool = False   # the reference host run failed
    validity: str = "valid"         # valid | noncompliant (host_verdict)
    host_witnesses: list = field(default_factory=list)
    host_path_failure: list = field(default_factory=list)
    elision: str | None = None      # "checksum=<n>" or why not
    host_rechecked: bool = False    # host data from hostcheck.jsonl
    seconds: float = 0.0
    base: list = field(default_factory=list)   # base groups (fuzz-3)

    @property
    def all_agree(self) -> bool:
        return bool(self.results) and all(
            r.cls == "agree" for r in self.results.values())

    def to_json(self) -> str:
        d = dataclasses.asdict(self)
        return json.dumps(d)

    @staticmethod
    def from_json(line: str) -> "ProgramResult":
        d = json.loads(line)
        d["results"] = {k: TcResult(**v) for k, v in d["results"].items()}
        if "host_ref_failed" not in d and d.get("host_mismatch") and \
                d.get("host_ref") is None:
            # written earlier: a failed reference run was recorded
            # as a mismatch
            d["host_mismatch"], d["host_ref_failed"] = False, True
        return ProgramResult(**d)


def regenerate(pr) -> FuzzProgram:
    """The program of a campaign record (seed, generator version, base
    groups)."""
    return generate(pr.seed, pr.gen_version, tuple(getattr(pr, "base", ())
                                                   or ()))


# The legality gate's checkers (AFAR flang, gfortran) live on
# Tuolumne; a machine without them (wingtip) reads the gate's verdict of
# each seed from a campaign Tuolumne ran (COMPLIANT_FUZZ_CHECKS: its
# programs.jsonl, the same generator version, base groups and model
# value), never a new verdict
def stored_check(prog: FuzzProgram):
    import os
    path = os.environ.get("COMPLIANT_FUZZ_CHECKS")
    if not path:
        return None
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        if d["seed"] == prog.seed and d.get("gen_version") == \
                prog.gen_version and tuple(d.get("base") or ()) == \
                tuple(prog.base) and d.get("expected") == prog.expected:
            from offload.engine.fuzz import CheckResult
            return CheckResult(d["check"], (d.get("check_detail") or "")
                               + f" [stored gate: {path}]")
    return None


def run_program(seed: int, toolchains=TOOLCHAIN_ORDER,
                reruns: int = RERUNS, gen_version: str = GEN_VERSION,
                base: tuple = ()) -> ProgramResult:
    """Generate, check and (if legal) run the program of `seed`. A fuzz-3
    program also passes the definedness check, whose sequential value
    must be the model's (offload.engine.fuzz.check_defined)."""
    t0 = time.time()
    prog = generate(seed, gen_version, base)
    stored = stored_check(prog)
    chk = stored or check(prog.source, expected=prog.expected)
    if chk.ok and stored is None:
        # The pre-run check (two witnesses and the race rule,
        # offload.engine.prerun); a refused program is never compiled or run
        from offload.engine import prerun
        from offload.engine.fuzz import CheckResult
        ok, why = prerun.check((prog.source, "f90", "omp"))
        if not ok:
            chk = CheckResult("prerun", "; ".join(why)[:600])
    pr = ProgramResult(seed, prog.gen_version, chk.stage, chk.detail,
                       prog.expected, sorted(prog.features),
                       list(prog.kernels), prog.flags,
                       prog.source.count("\n"), base=list(prog.base))
    if not chk.ok:
        pr.seconds = time.time() - t0
        return pr
    base = Path(tempfile.mkdtemp(prefix=f"fuzz_{seed}_"))
    try:
        exes: dict[str, tuple[Path, Path]] = {}
        for name in toolchains:
            tc = TOOLCHAINS[name]
            tmp = base / name
            tmp.mkdir()
            res, exe = run_toolchain(prog, tc, tmp, reruns)
            pr.results[name] = res
            if exe is not None:
                exes[name] = (exe, tmp)
        host_reference(pr, prog, exes)
    finally:
        shutil.rmtree(base, ignore_errors=True)
    pr.seconds = time.time() - t0
    return pr


ELISION = "elision"   # the sequential elision as a host witness
HOST_RUNS = 2         # host runs per build in recheck_host
# a host run uses every core for its OpenMP host threads; on a loaded
# interactive node it took 26 s alone and over 60 s next to other builds
# (c1 seed 1436 on CCE), so host runs (campaign reference and recheck)
# allow far longer than a device run
HOST_TIMEOUT_S = 600
HOSTCHECK = "hostcheck.jsonl"


def host_verdict(expected: int, host: dict, elision: int | None
                 ) -> tuple[str, list, list]:
    """The maintainer's rule for a program whose host reference failed or
    disagreed: (validity, witnesses, host_path_failure). `host` maps each
    toolchain with a host build to its host checksum (None: the run
    failed); `elision` is the sequential elision's checksum (None: no
    value or not applicable). Valid when a host build or the elision
    prints the model's checksum; the toolchains whose host run did not
    are then host-path failures. Otherwise noncompliant."""
    witnesses = [t for t, v in host.items() if v == expected]
    if elision is not None and elision == expected:
        witnesses.append(ELISION)
    if not witnesses:
        return "noncompliant", [], []
    return "valid", witnesses, [t for t, v in host.items() if v != expected]


def elision_value(source: str):
    """The sequential elision's checksum (int), or why there is none
    (str)."""
    from offload.engine import expected as E
    ev = E.elision_evidence(source)
    if ev.status == "value":
        return int(ev.value.split("=", 1)[1])
    why = ev.detail if isinstance(ev.detail, str) else \
        "; ".join(map(str, ev.detail or []))
    return f"{ev.status}: {why}"[:300]


def _elision(prog_source: str, elision) -> tuple[int | None, str]:
    v = (elision or elision_value)(prog_source)
    if isinstance(v, int) and not isinstance(v, bool):
        return v, f"checksum={v}"
    return None, v or "no value"


def _host_value(run: Run) -> tuple[int | None, str]:
    return (run.checksum, "") if run.kind == "ok" else \
        (None, f"{run.why}" if run.why else run.kind)


def host_reference(pr: ProgramResult, prog: FuzzProgram,
                   exes: dict, elision=None) -> None:
    """Run the first compiled binary with OMP_TARGET_OFFLOAD=disabled. If
    the run fails (host_ref_failed) or its checksum is not the model's
    (host_mismatch), run every compiled binary on the host
    (TcResult.host_checksum/host_why) and the sequential elision
    (`elision(source)`: an int checksum, or why not), and set the
    program's validity by ``host_verdict``."""
    for name in TOOLCHAIN_ORDER:
        if name not in exes:
            continue
        exe, tmp = exes[name]
        run = execute(TOOLCHAINS[name], exe, tmp, "disabled", HOST_TIMEOUT_S)
        pr.host_ref_tc = name
        pr.host_ref, why = _host_value(run)
        pr.results[name].host_checksum = pr.host_ref
        pr.results[name].host_why = why
        break
    if pr.host_ref_tc is None or pr.host_ref == prog.expected:
        return
    if pr.host_ref is None:
        pr.host_ref_failed = True
    else:
        pr.host_mismatch = True
    for name, (exe, tmp) in exes.items():
        if name == pr.host_ref_tc:
            continue
        run = execute(TOOLCHAINS[name], exe, tmp, "disabled", HOST_TIMEOUT_S)
        r = pr.results[name]
        r.host_checksum, r.host_why = _host_value(run)
    el, pr.elision = _elision(prog.source, elision)
    pr.validity, pr.host_witnesses, pr.host_path_failure = host_verdict(
        prog.expected, {n: pr.results[n].host_checksum for n in exes}, el)


def recheck_host(prog: FuzzProgram, toolchains=TOOLCHAIN_ORDER,
                 runs: int = HOST_RUNS, elision=None,
                 timeout_s: int = HOST_TIMEOUT_S) -> dict:
    """Rebuild `prog` with every toolchain's campaign recipe (-O2) and run
    each build `runs` times with OMP_TARGET_OFFLOAD=disabled; with the
    sequential elision, decide validity by ``host_verdict``. A host value
    counts only when every repeat printed it; a toolchain whose build
    does not compile has no host build. Returns one hostcheck.jsonl
    record."""
    host, rec_host = {}, {}
    base = Path(tempfile.mkdtemp(prefix=f"fuzzhost_{prog.seed}_"))
    try:
        for name in toolchains:
            tc = TOOLCHAINS[name]
            tmp = base / name
            tmp.mkdir()
            src, exe = tmp / f"{prog.id}.f90", tmp / f"{prog.id}.out"
            src.write_text(prog.source)
            cls, reason, _, _ = compile_program(tc, src, exe, tmp)
            if cls is not None:
                rec_host[name] = {"build": cls, "checksum": None,
                                  "why": _scrub(reason, tmp)[:200],
                                  "runs": []}
                continue
            vals = [_host_value(execute(tc, exe, tmp, "disabled",
                                        timeout_s))
                    for _ in range(runs)]
            shown = [w or f"checksum={v}" for v, w in vals]
            if len({v for v, _ in vals}) == 1 and vals[0][0] is not None:
                value, why = vals[0][0], ""
            elif len(set(shown)) == 1:
                value, why = None, shown[0]
            else:
                value, why = None, "unstable: " + "; ".join(shown)
            host[name] = value
            rec_host[name] = {"build": "ok", "checksum": value,
                              "why": _scrub(why, tmp)[:200],
                              "runs": shown}
    finally:
        shutil.rmtree(base, ignore_errors=True)
    el, el_note = _elision(prog.source, elision)
    validity, witnesses, failures = host_verdict(prog.expected, host, el)
    return {"seed": prog.seed, "gen_version": prog.gen_version,
            "base": list(prog.base),
            "expected": prog.expected, "host": rec_host,
            "elision": el_note, "validity": validity,
            "witnesses": witnesses, "host_path_failure": failures,
            "opt": OPT, "xnack": XNACK}


ELISION_FILE = "elision.jsonl"


def elide_record(prog: FuzzProgram) -> dict:
    """One elision.jsonl record: whether sequential elision applies to the
    program, its value (int) or why there is none."""
    from offload.engine import expected as E
    ap = E.elision_applicability(prog.source)
    rec = {"seed": prog.seed, "expected": prog.expected,
           "applicable": ap.ok, "value": None}
    if not ap.ok:
        rec["why"] = ap.why
        return rec
    v = elision_value(prog.source)
    if isinstance(v, int) and not isinstance(v, bool):
        rec["value"] = v
    else:
        rec["why"] = v
    return rec


def reelide(rec: dict, source: str, elision=None) -> dict:
    """A hostcheck.jsonl record with the sequential elision of `source`
    and the validity it implies (``host_verdict``) computed again; the
    stored host runs are kept (``tools/campaigns/fuzz.py host-check
    --elision-only``, after a change of the elision analysis)."""
    host = {t: h["checksum"] for t, h in rec["host"].items()
            if h["build"] == "ok"}
    el, el_note = _elision(source, elision)
    validity, witnesses, failures = host_verdict(rec["expected"], host, el)
    return dict(rec, elision=el_note, validity=validity,
                witnesses=witnesses, host_path_failure=failures)


def apply_hostcheck(progs: list, records: list[dict]) -> None:
    """Override the campaign's host data of each program with its
    recheck_host record (same seed and expected value)."""
    by_seed = {p.seed: p for p in progs}
    for rec in records:
        p = by_seed.get(rec["seed"])
        if p is None or p.expected != rec["expected"]:
            raise ValueError(f"hostcheck record of seed {rec['seed']} does "
                             "not match the campaign")
        for name, h in rec["host"].items():
            if name in p.results:
                p.results[name].host_checksum = h["checksum"]
                p.results[name].host_why = h["why"] if h["build"] == "ok" \
                    else f"no host build: {h['build']}"
        p.validity = rec["validity"]
        p.host_witnesses = list(rec["witnesses"])
        p.host_path_failure = list(rec["host_path_failure"])
        p.elision = rec["elision"]
        p.host_rechecked = True


# --- a campaign ---------------------------------------------------------------------

def _worker(args) -> str:
    global XNACK
    seed, toolchains, reruns, gen_version, base, xnack = args
    XNACK = xnack
    try:
        return run_program(seed, toolchains, reruns, gen_version,
                           base).to_json()
    except Exception as e:  # recorded, never silently dropped
        import traceback
        return json.dumps({"seed": seed, "crash": repr(e),
                           "traceback": traceback.format_exc()[-3000:]})


def campaign(out_dir: Path, seeds, workers: int = 6,
             toolchains=TOOLCHAIN_ORDER, reruns: int = RERUNS,
             log=print, gen_version: str = GEN_VERSION,
             base: tuple = (), xnack: int | None = None) -> Path:
    """Run every seed (skipping those already in programs.jsonl, so a
    campaign can be resumed) with `workers` processes; one JSON line per
    program, written as each finishes. Resuming with another generator
    version or other base-language groups than the recorded programs'
    raises (a campaign has one generator version and one set of base
    groups)."""
    from concurrent.futures import ProcessPoolExecutor, as_completed
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "programs.jsonl"
    done = set()
    if path.exists():
        other = set()
        for line in path.read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                done.add(rec["seed"])
                if rec.get("gen_version", gen_version) != gen_version:
                    other.add(rec["gen_version"])
                elif tuple(rec.get("base", ())) != tuple(base):
                    other.add(f"{rec['gen_version']} with base groups "
                              f"{rec.get('base', [])}")
        if other:
            raise ValueError(
                f"{path} holds programs of generator "
                f"{', '.join(sorted(other))}, not {gen_version}: use "
                "another output directory")
    todo = [s for s in seeds if s not in done]
    t0 = time.time()
    log(f"{len(todo)} programs to run ({len(done)} done), {workers} "
        f"workers, toolchains {', '.join(toolchains)}")
    with path.open("a") as f, ProcessPoolExecutor(workers) as ex:
        futs = [ex.submit(_worker, (s, tuple(toolchains), reruns,
                                    gen_version, tuple(base),
                                    XNACK if xnack is None else xnack))
                for s in todo]
        for k, fut in enumerate(as_completed(futs), 1):
            line = fut.result()
            f.write(line + "\n")
            f.flush()
            if k % 50 == 0 or k == len(todo):
                log(f"{k}/{len(todo)} in {time.time() - t0:.0f} s")
    return path


def load(out_dir: Path) -> tuple[list[ProgramResult], list[dict]]:
    """(program results, worker crashes) of a campaign directory, with
    the host rechecks of ``HOSTCHECK`` applied."""
    progs, crashes = [], []
    for line in (Path(out_dir) / "programs.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        if "crash" in d:
            crashes.append(d)
        else:
            progs.append(ProgramResult.from_json(line))
    progs.sort(key=lambda p: p.seed)
    hc = Path(out_dir) / HOSTCHECK
    if hc.exists():
        apply_hostcheck(progs, [json.loads(ln) for ln in
                                hc.read_text().splitlines() if ln.strip()])
    return progs, crashes


def reclassify_compile(out_dir: Path) -> list[tuple]:
    """Classify again, with the current message tables, the compile
    failures a campaign recorded as unclassified (harness_error
    "unclassified_compile_failure"), from their stored compiler output;
    programs.jsonl is rewritten (the old reason kept in `note`). Returns
    (seed, toolchain, new class, reason) per change."""
    path = Path(out_dir) / "programs.jsonl"
    lines, changed = [], []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        for name, r in d.get("results", {}).items():
            if r["cls"] != "harness_error" or not r["reason"].startswith(
                    "unclassified_compile_failure"):
                continue
            found = harness.classify_message(name, r["output"],
                                             harness.CATEGORY_ORDER[:-1])
            if found is None or found[0] == "environment":
                continue
            cat, msg = found
            cls = "ice" if cat == "ice" else "compile_reject"
            reason = {"ice": "ice", "not_implemented": "not_implemented",
                      "link_undefined": "link_undefined_symbol",
                      "error": "diagnostic"}[cat] + f": {msg}"
            r["note"] = (r.get("note", "") + "; " if r.get("note") else "") \
                + f"reclassified from: {r['reason']}"
            r["cls"], r["reason"] = cls, reason
            changed.append((d["seed"], name, cls, reason))
        lines.append(json.dumps(d))
    path.write_text("\n".join(lines) + "\n")
    return changed


def merge_runs(out_dir: Path, run_dirs) -> dict:
    """One campaign directory from the run ids it was run as
    (one-hour chunks): programs.jsonl, hostcheck.jsonl and elision.jsonl
    concatenated in seed order, meta.json with every chunk's sessions and
    `merged_from`. The chunks must share the generator version, base
    groups, toolchains and memory mode, and no seed may repeat. The chunk
    directories are only read; the output is rewritten each time."""
    out_dir = Path(out_dir)
    run_dirs = sorted((Path(d) for d in run_dirs), key=lambda d: d.name)
    sessions, conf, seeds = [], set(), set()
    progs, hcs, els = [], [], []
    for d in run_dirs:
        meta = json.loads((d / "meta.json").read_text())
        for s in meta.get("sessions") or [meta]:
            sessions.append(s)
            conf.add((s.get("gen_version"), tuple(s.get("base") or ()),
                      tuple(s.get("toolchains") or ()), s.get("xnack", 1)))
        for line in (d / "programs.jsonl").read_text().splitlines():
            if not line.strip():
                continue
            seed = json.loads(line)["seed"]
            if seed in seeds:
                raise ValueError(f"seed {seed} repeats in {d.name}")
            seeds.add(seed)
            progs.append((seed, line))
        for name, acc in ((HOSTCHECK, hcs), (ELISION_FILE, els)):
            p = d / name
            if p.exists():
                acc += [(json.loads(ln)["seed"], ln) for ln in
                        p.read_text().splitlines() if ln.strip()]
    if len(conf) != 1:
        raise ValueError(f"the runs differ in configuration: {sorted(conf)}")
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, acc in (("programs.jsonl", progs), (HOSTCHECK, hcs),
                      (ELISION_FILE, els)):
        if acc or name == "programs.jsonl":
            (out_dir / name).write_text("".join(
                ln + "\n" for _, ln in sorted(acc, key=lambda x: x[0])))
    meta = {"merged_from": [d.name for d in run_dirs], "sessions": sessions}
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=1) + "\n")
    return {"programs": len(progs), "hostcheck": len(hcs),
            "elision": len(els), "runs": len(run_dirs)}


def join_toolchains(out_dir: Path, base_dir: Path, other_dirs) -> dict:
    """One campaign directory from runs of the SAME seeds on
    different toolchains (the AMD run on Tuolumne, the NVHPC runs on
    wingtip): each program row is the base run's (its legality gate, model,
    host reference, validity and the AMD toolchains' results) with the
    other runs' toolchain results added. Every run must have the same
    generator version, base groups and seeds, and the toolchain sets must
    not overlap; the base run's hostcheck.jsonl and elision.jsonl are
    kept. meta.json: `joined_from` and every run's sessions."""
    out_dir, base_dir = Path(out_dir), Path(base_dir)
    dirs = [base_dir] + [Path(d) for d in other_dirs]
    rows, sessions, conf, tcs = {}, [], set(), {}
    for k, d in enumerate(dirs):
        meta = json.loads((d / "meta.json").read_text())
        for s in meta.get("sessions") or [meta]:
            sessions.append(dict(s, joined_run=d.name))
            conf.add((s.get("gen_version"), tuple(s.get("base") or ())))
        seeds = set()
        for line in (d / "programs.jsonl").read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            seeds.add(r["seed"])
            if k == 0:
                rows[r["seed"]] = r
                continue
            base = rows.get(r["seed"])
            if base is None:
                raise ValueError(f"seed {r['seed']} of {d.name} is not in "
                                 f"{base_dir.name}")
            if r.get("expected") != base.get("expected"):
                raise ValueError(f"seed {r['seed']}: another program")
            for tc, res in (r.get("results") or {}).items():
                if tc in base.setdefault("results", {}):
                    raise ValueError(f"toolchain {tc} in two runs")
                base["results"][tc] = res
                tcs.setdefault(tc, d.name)
        if k and seeds != set(rows):
            raise ValueError(f"{d.name} has other seeds than "
                             f"{base_dir.name}")
    if len(conf) != 1:
        raise ValueError(f"the runs differ in configuration: {sorted(conf)}")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "programs.jsonl").write_text("".join(
        json.dumps(rows[s]) + "\n" for s in sorted(rows)))
    for name in (HOSTCHECK, ELISION_FILE):
        p = base_dir / name
        if p.exists():
            (out_dir / name).write_text(p.read_text())
    (out_dir / "meta.json").write_text(json.dumps(
        {"joined_from": [d.name for d in dirs], "toolchain_runs": tcs,
         "sessions": sessions}, indent=1) + "\n")
    return {"programs": len(rows), "runs": len(dirs),
            "toolchains_added": sorted(tcs)}
