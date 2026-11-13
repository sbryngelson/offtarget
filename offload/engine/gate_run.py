"""Running a failure again in one of the reproduction gate's
environments (offload.engine.gate.environments).

Each failure is rerun with the runner of the campaign that produced it,
so the rerun classifies the same way: a catalog or widened-catalog row
through offload.engine.harness.run_program, a fuzz row through
offload.engine.fuzz_exec.run_toolchain, a stress row through
offload.engine.stress_exec.execute, a confirmer evidence row through
offload.engine.confirm.execute.LocalRunner. Every runner builds in the
environment's path (it must not exist; it is removed afterwards). A rerun
is one dict: the environment (``env``, ``path``), the node it ran on, the
outcome fields of the campaign's row format, and the toolchain build.

(c), another node, is the same call made by a second job on another
node (tools/campaigns/gate.py run --envs c); this module only runs here."""
from __future__ import annotations

import dataclasses
import os
import shutil
import time
from pathlib import Path

from offload.engine import provenance as PV


def _base(env: dict, t0: float) -> dict:
    return {"env": env["env"], "path": env["path"], "node": PV.node(),
            "repeat": env.get("repeat", 0), "seconds": round(time.time() -
                                                             t0, 1),
            "date": time.strftime("%Y-%m-%dT%H:%M:%S")}


def _clear(path: str) -> None:
    """A leftover of an interrupted rerun of the same environment."""
    if os.path.isdir(path) and os.path.basename(path).startswith(
            ("GATE", "harness_", "fuzz_", "st_", "confirm_", "baseline_")):
        shutil.rmtree(path, ignore_errors=True)


def rerun_program(prog, tc, xnack: int, env: dict, opt: str = "-O2",
                  timeout_s: int = 300, compile_timeout_s: int = 900
                  ) -> dict:
    """A harness program (a catalog, widened-catalog or canary row) in
    environment `env`: one compile and one run (the second run of the
    environment is (d))."""
    from offload.engine import harness
    _clear(env["path"])
    t0 = time.time()
    res = harness.run_program(prog, tc, xnack, opt, timeout_s=timeout_s,
                              repeats=1, compile_timeout_s=compile_timeout_s,
                              build_dir=env["path"])
    d = dataclasses.asdict(res)
    out = {k: d[k] for k in ("outcome", "reason", "flaky", "stdout",
                             "toolchain_build", "build_dir", "git_rev")}
    out["stdout"] = (out["stdout"] or "")[-400:]
    out["compile_log"] = (d.get("stderr") or "")[-1500:]
    return {**_base(env, t0), **out}


def rerun_fuzz(prog, tc, xnack: int, env: dict) -> dict:
    """A fuzz program (offload.engine.fuzz.FuzzProgram) in `env`, with the
    campaign's own compile and run (fuzz_exec.run_toolchain, no
    reruns)."""
    from offload.engine import fuzz_exec as FX
    _clear(env["path"])
    Path(env["path"]).mkdir(parents=True)
    old = FX.XNACK
    FX.XNACK = xnack
    t0 = time.time()
    try:
        res, _ = FX.run_toolchain(prog, tc, Path(env["path"]), reruns=0)
    finally:
        FX.XNACK = old
        shutil.rmtree(env["path"], ignore_errors=True)
    d = dataclasses.asdict(res)
    return {**_base(env, t0), "cls": d["cls"], "reason": d["reason"],
            "checksum": d.get("checksum"), "flaky": d.get("flaky", False),
            "toolchain_build": PV.toolchain_build(tc),
            "build_dir": env["path"], "git_rev": PV.git_rev(),
            "compile_log": (d.get("output") or "")[-1500:]}


def rerun_stress(prog, toolchain: str, mode: int, variant: str, lim,
                 env: dict) -> dict:
    """A stress program in `env` (offload.engine.stress_exec.execute with the
    environment's build directory)."""
    from offload.engine import stress_exec as X
    _clear(env["path"])
    t0 = time.time()
    rows = X.execute(prog, toolchain, (mode,), variant, lim,
                     build_dir=env["path"])
    r = rows[0].as_dict()
    return {**_base(env, t0), "cls": r["cls"], "reason": r["reason"],
            "checksum": r.get("checksum"), "flaky": r.get("flaky", False),
            "bad_kernels": r.get("bad_kernels") or [],
            "toolchain_build": r.get("toolchain_build", ""),
            "build_dir": env["path"], "git_rev": PV.git_rev(),
            "compile_log": (r.get("output") or "")[-1500:]}


def rerun_ref(ref, toolchain: str, mode: str, opt: str, offload: str,
              env: dict) -> dict:
    """A confirmer program (offload.engine.confirm.model.ProgramRef: evidence,
    a finding, a benchmark file) in `env`, one run, with the confirmer's
    LocalRunner."""
    from offload.engine.confirm.execute import LocalRunner
    _clear(env["path"])
    t0 = time.time()
    runs, prov = LocalRunner().run(ref, toolchain, mode, opt, offload,
                                   repeats=1, build_dir=env["path"])
    r = runs[0]
    from offload.engine.toolchains import TOOLCHAINS
    return {**_base(env, t0), "outcome": r.outcome, "reason": r.reason,
            "value": r.value, "flaky": len({(x.outcome, x.value)
                                             for x in runs}) > 1,
            "toolchain_build": PV.toolchain_build(TOOLCHAINS[toolchain]),
            "build_dir": env["path"], "git_rev": PV.git_rev()}
