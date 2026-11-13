"""Running one program on one toolchain, memory mode, optimisation level and
offload policy, k times.

``LocalRunner`` runs on this node: a catalog program under the mandatory
policy goes through offload.engine.harness.run_program (the matrix's own
classification: probes, ignored clauses, the second run without
mandatory); an omp_vv test through offload.engine.baseline.run_file; anything
else (fuzz programs, files, program sets, the host runs of any program) is
compiled once with the toolchain's recipe (a set one translation unit at a
time, then linked), the compile classified with the harness's message
tables, and run k times with the machine's mode environment
(catalog/machines.yaml) and the offload policy. ``RemoteRunner`` sends the
same request to another machine (catalog/machines.yaml ``access``: ssh,
the clone, a compute-node prefix) as JSON to ``tools/confirm.py exec``.
Every result carries its provenance (command, host, date, modules)."""
from __future__ import annotations

import dataclasses
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from offload.engine import harness
from offload.engine.confirm import machines as M
from offload.engine.confirm import programs as P
from offload.engine.confirm.model import (ProgramRef, Provenance, Run,
                                      outcome_of_baseline, outcome_of_result,
                                      value_of)
from offload.engine.toolchains import TOOLCHAINS, Toolchain

# CONFIRM_COMPILE_TIMEOUT_S shortens it for a batch (a
# metamorphic variant that hangs a compiler says nothing)
COMPILE_TIMEOUT_S = int(os.environ.get("CONFIRM_COMPILE_TIMEOUT_S", "900"))
RUN_TIMEOUT_S = 120


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def toolchain_for(ref: ProgramRef, name: str) -> Toolchain:
    """The toolchain with the program's language, model and version flags
    (offload.engine.run_matrix.for_version, as the matrix compiles it)."""
    from offload.engine.run_matrix import for_version
    tc = TOOLCHAINS[name]
    if ref.version:
        tc = for_version(tc, ref.version, ref.lang)
    elif tc.lang != ref.lang:
        tc = dataclasses.replace(tc, lang=ref.lang)
    if tc.model != ref.model:
        tc = dataclasses.replace(tc, model=ref.model)
    return tc


_OLEVEL = re.compile(r"^-O(?:\d|s|fast|g)?$")


def build_opt(opt: str, flags: str) -> str:
    """The optimisation level and flags of a build: the
    reproducer's own flags (``ProgramRef.flags``) added to `opt`; its
    optimisation level replaces the default -O2 (an explicit other level,
    e.g. the -O0 control, stays)."""
    if not flags:
        return opt
    words = flags.split()
    levels = [w for w in words if _OLEVEL.match(w)]
    extra = [w for w in words if not _OLEVEL.match(w)]
    base = levels[-1] if levels and opt == "-O2" else opt
    return " ".join([base] + [w for w in extra if w not in opt.split()])


def judge(ex_rc, timed_out: bool, stdout: str, expected: str,
          env_failure: str | None = None) -> Run:
    """The outcome of one generic run."""
    tail = (stdout or "")[-400:]
    if timed_out:
        return Run("timeout", None, None, "timeout", tail)
    if env_failure:
        return Run("harness_error", None, None, env_failure, tail)
    if ex_rc is not None and ex_rc < 0:
        try:
            why = f"crash: {signal.Signals(-ex_rc).name}"
        except ValueError:
            why = f"crash: signal {-ex_rc}"
        if expected == "error_termination":
            return Run("correct_on_device", "error_termination", None, why,
                       tail)
        return Run("crash", None, None, why, tail)
    if ex_rc:
        if expected == "error_termination":
            return Run("correct_on_device", "error_termination", None,
                       f"exit_status: {ex_rc}", tail)
        return Run("run_error", None, None, f"exit_status: {ex_rc}", tail)
    value, host = value_of(stdout)
    if value is None:
        return Run("run_error", None, None, "no output", tail)
    if expected == "error_termination":
        return Run("wrong_answer", value, host, "no_error_termination", tail)
    if value.startswith("check="):
        if value == "check=fail":
            return Run("wrong_answer", value, host, "check_fail", tail)
        return Run("fell_back_to_host" if host else "correct_on_device",
                   value, host, "", tail)
    if not expected:
        return Run("unobservable", value, host, "no expected value", tail)
    want = " ".join(expected.split())
    if value == want or (not value.startswith("checksum=") and want in value):
        return Run("fell_back_to_host" if host else "correct_on_device",
                   value, host, "", tail)
    return Run("wrong_answer", value, host, f"expected {want}", tail)


def _compile_script(tc: Toolchain, files: list[str], exe: str, opt: str,
                    tmp: str) -> str:
    bare = dataclasses.replace(tc, prelude="")
    if len(files) == 1:
        return harness.compile_script(tc, files[0], exe, opt, tmp)
    # Any suffix (.F90, .f, .cpp, ...), headers not compiled
    pairs = harness.object_names(files)
    steps = [bare.compile_cmd(f"-c {f}", o, opt) for f, o in pairs]
    steps.append(bare.compile_cmd(" ".join(o for _, o in pairs), exe, opt))
    return "\n".join(harness._setup(tc, tmp) + [" && \\\n".join(steps)]) \
        + "\n"


def compile_files(tc: Toolchain, text: str, lang: str, tmp: Path, opt: str
                  ) -> tuple[Run | None, Path, str]:
    """Compile a program (or set) in `tmp`: (None, exe, output) when it
    built, else (the classified Run, exe, output)."""
    files = P.split_files(text) or [("prog.c" if lang == "c" else
                                     "prog.f90", text)]
    for name, body in files:
        (tmp / name).write_text(body)
    exe = tmp / "prog.out"
    build = harness._execute(_compile_script(tc, [n for n, _ in files],
                                             str(exe), opt, str(tmp)),
                             tmp, COMPILE_TIMEOUT_S, merge=True)
    out = harness._clip(build.stdout).replace(str(tmp), "<tmpdir>")
    if build.timed_out:
        return Run("timeout", None, None, "compile_timeout"), exe, out
    if build.rc != 0:
        found = harness.classify_message(tc.name, build.stdout,
                                         harness.CATEGORY_ORDER[:-1], lang)
        if found is None:
            return Run("harness_error", None, None,
                       f"unclassified_compile_failure: rc={build.rc}"), \
                exe, out
        cat, line = found
        line = line.replace(str(tmp), "<tmpdir>")
        if cat == "environment":
            return Run("harness_error", None, None,
                       f"environment: {line}"), exe, out
        code = {"ice": "ice", "not_implemented": "not_implemented",
                "link_undefined": "link_undefined_symbol",
                "error": "diagnostic"}[cat]
        return Run("ice" if cat == "ice" else "rejected", None, None,
                   f"{code}: {line}"), exe, out
    if not exe.is_file():
        return Run("harness_error", None, None, "no_executable"), exe, out
    return None, exe, out


def run_script(tc: Toolchain, exe: Path, env: dict, offload: str,
               tmp: Path) -> str:
    lines = harness._setup(tc, str(tmp))
    lines += [f"export {k}={shlex.quote(v)}" for k, v in
              {**env, **dict(tc.env)}.items()]
    if tc.model == "acc":
        lines.append("unset OMP_TARGET_OFFLOAD")
    elif offload:
        lines.append(f"export OMP_TARGET_OFFLOAD={shlex.quote(offload)}")
    lines.append(f"exec {shlex.quote(str(exe))}")
    return "\n".join(lines) + "\n"


def _runs_of_result(res, k: int) -> list[Run]:
    """The runs behind one harness Result (its reason lists the repeats
    when they disagreed)."""
    value, host = value_of(res.stdout)
    if res.reason.startswith(("error_termination",
                              "compile_error_termination")):
        value = "error_termination"
    main = Run(outcome_of_result(res.outcome, res.reason), value, host,
               res.reason[:300], (res.stdout or "")[-400:])
    if not res.flaky:
        n = 1 if main.outcome in ("rejected", "ice", "harness_error") or \
            res.outcome == "accepted_ignored" or "timeout" in res.reason \
            else k
        return [main] * n
    parts = res.reason.split("; repeats: ", 1)[1].split(" | ")
    out = []
    for p in parts:
        o, _, why = p.partition(": ")
        v = None
        m = re.search(r"ran_on_host=([01]) check=(pass|fail)", why)
        if m:
            v = f"check={m.group(2)}"
        out.append(Run(outcome_of_result(o, why), v,
                       int(m.group(1)) if m else None, why[:300]))
    return out


class LocalRunner:
    """Runs on this node (it must have the toolchain's arch)."""

    def __init__(self, timeout_s: int = RUN_TIMEOUT_S):
        self.timeout_s = timeout_s

    def provenance(self, tc: Toolchain, command: str) -> Provenance:
        mods = ()
        if tc.prelude:
            m = re.search(r"module load ([^\n]+)", tc.prelude)
            mods = tuple(m.group(1).split()) if m else ()
        return Provenance(command=command, host=os.uname().nodename,
                          date=_now(), modules=mods, origin="run")

    def run(self, ref: ProgramRef, toolchain: str, mode: str,
            opt: str = "-O2", offload: str = "mandatory", repeats: int = 3,
            build_dir: str | None = None) -> tuple[list[Run], Provenance]:
        """`build_dir` (the reproduction gate): build in this
        path (it must not exist). The program's own build flags
        (``ProgramRef.flags``) are added to `opt` (``build_opt``)."""
        opt = build_opt(opt, ref.flags)
        tc = toolchain_for(ref, toolchain)
        machine = M.load()[tc.machine]
        env = machine.env(mode)
        tc = tc.for_mode(machine.row_key(mode))  # NVHPC
        bad = harness.wrong_arch(tc)
        prov = self.provenance(tc, f"{tc.compiler()} {tc.flags()} {opt}; "
                               f"{' '.join(f'{k}={v}' for k, v in env.items())}"
                               f" OMP_TARGET_OFFLOAD={offload}")
        if bad:
            return [Run("harness_error", None, None, bad)], prov
        if ref.kind == "catalog" and offload == "mandatory":
            prog = P.catalog_program(ref.ident)
            if prog is not None and prog.source == ref.text:
                res = harness.run_program(prog, tc, machine.row_key(mode),
                                          opt, timeout_s=self.timeout_s,
                                          repeats=repeats,
                                          build_dir=build_dir)
                return _runs_of_result(res, repeats), prov
        if ref.kind == "ompvv" and offload == "mandatory":
            from offload.engine import baseline as B
            row = {"repo": "omp_vv", "path": ref.ident,
                   "spec_dir": ref.ident.split("/")[1]
                   if ref.ident.count("/") > 1 else ""}
            out = []
            for _ in range(max(1, repeats)):
                r = B.run_file(row, TOOLCHAINS[toolchain],
                               machine.row_key(mode), B.CORPUS, opt,
                               self.timeout_s)
                d = dataclasses.asdict(r)
                oc = outcome_of_baseline(d)
                out.append(Run(oc, "exit=0" if oc == "correct_on_device"
                               else None, None, d["reason"][:300],
                               (d["stdout"] or "")[-400:]))
                if oc in ("rejected", "ice", "harness_error"):
                    break
            return out, prov
        return self._generic(ref, tc, env, opt, offload, repeats,
                             build_dir), prov

    def _generic(self, ref, tc, env, opt, offload, repeats,
                 build_dir: str | None = None) -> list[Run]:
        if build_dir is None:
            tmp = Path(tempfile.mkdtemp(prefix="confirm_"))
        else:
            tmp = Path(build_dir)
            tmp.mkdir(parents=True)     # FileExistsError if it exists
        try:
            failed, exe, out = compile_files(tc, ref.text, ref.lang, tmp, opt)
            if failed is not None:
                return [failed]
            runs = []
            expected = ref.expected if offload != "disabled" or \
                ref.expected != "error_termination" else ""
            for _ in range(max(1, repeats)):
                ex = harness._execute(run_script(tc, exe, env, offload, tmp),
                                      tmp, self.timeout_s)
                envf = harness._env_failure(tc, ex)
                r = judge(ex.rc, ex.timed_out, ex.stdout, expected, envf)
                runs.append(r)
                if r.outcome in ("timeout", "harness_error"):
                    break
            return runs
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def request_json(ref: ProgramRef, toolchain: str, mode: str, opt: str,
                 offload: str, repeats: int) -> str:
    d = dataclasses.asdict(ref)
    d["needs"] = list(ref.needs)
    return json.dumps({"program": d, "toolchain": toolchain, "mode": mode,
                       "opt": opt, "offload": offload, "repeats": repeats})


def serve(request: str, runner=None) -> str:
    """``tools/confirm.py exec``: one JSON request in, the runs out."""
    d = json.loads(request)
    p = dict(d["program"])
    p["needs"] = tuple(p.get("needs") or ())
    ref = ProgramRef(**p)
    runs, prov = (runner or LocalRunner()).run(
        ref, d["toolchain"], d["mode"], d["opt"], d["offload"], d["repeats"])
    return json.dumps({"runs": [dataclasses.asdict(r) for r in runs],
                       "provenance": prov.to_dict()})


class RemoteRunner:
    """Runs on another machine through its ``access`` entry: ``ssh <alias>
    'cd <root> && <run_prefix> <python> -I tools/confirm.py exec'`` with the
    request on stdin. `runner` replaces subprocess.run (tests)."""

    def __init__(self, machine, runner=None, timeout_s: int = 3600):
        if not isinstance(machine.access, dict) or "ssh" not in machine.access:
            raise ValueError(f"{machine.name} is not reached over ssh")
        self.machine = machine
        self.runner = runner or (lambda argv, **kw: subprocess.run(
            argv, capture_output=True, text=True, **kw))
        self.timeout_s = timeout_s

    def _ssh(self) -> list[str]:
        a = self.machine.access
        return ["ssh", *(a.get("ssh_options") or ()), a["ssh"]]

    def available(self) -> bool:
        """An ssh master is up (`ssh -O check`); a machine reached
        without one (``master: false``, wingtip) answers a trivial
        command."""
        a = self.machine.access
        if a.get("master", True):
            res = self.runner(["ssh", "-O", "check", a["ssh"]])
        else:
            res = self.runner(self._ssh() + ["true"], timeout=120)
        return res.returncode == 0

    def command(self) -> list[str]:
        a = self.machine.access
        # `env` (e.g. the GPU and the run lock) for the exec
        env = ("env " + " ".join(f"{k}={shlex.quote(str(v))}"
                                 for k, v in a["env"].items())
               if a.get("env") else "")
        # A machine with a cap (wingtip) runs the exec inside it
        cap = a.get("cap") or ""
        remote = (f"cd {shlex.quote(a['root'])} && {env} "
                  f"{a.get('run_prefix', '')} {cap} "
                  f"{a.get('python', 'python3')} "
                  "-I tools/confirm.py exec").replace("  ", " ")
        return self._ssh() + [remote]

    def run(self, ref, toolchain, mode, opt="-O2", offload="mandatory",
            repeats=3):
        res = self.runner(self.command(), input=request_json(
            ref, toolchain, mode, opt, offload, repeats),
            timeout=self.timeout_s)
        if res.returncode != 0:
            return ([Run("harness_error", None, None,
                         f"remote: rc={res.returncode}: "
                         f"{(res.stderr or '')[-300:]}")],
                    Provenance(command=" ".join(self.command()),
                               date=_now(), origin="remote"))
        lines = [ln for ln in res.stdout.splitlines() if ln.startswith("{")]
        try:
            d = json.loads(lines[-1])
        except (IndexError, ValueError):
            return ([Run("harness_error", None, None,
                         "remote: no result line: "
                         f"{(res.stdout or res.stderr or '')[-200:]}")],
                    Provenance(command=" ".join(self.command()),
                               date=_now(), origin="remote"))
        p = dict(d["provenance"])
        p["modules"] = tuple(p.get("modules", ()))
        p["origin"] = f"remote:{self.machine.name}"
        return [Run(**r) for r in d["runs"]], Provenance(**p)
