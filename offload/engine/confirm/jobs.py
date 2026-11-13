"""Job submission behind one interface.

``JobSpec`` says what to run (a script, its environment, nodes, minutes,
queue, output file, scheduler attributes); a ``Scheduler`` submits it and
reports its state (``pending``, ``running``, ``done``, ``failed``).
``FluxScheduler`` (Tuolumne, Tioga) and ``SlurmScheduler`` (the NVIDIA
machine later) only build their command lines and call ``runner`` (by
default ``subprocess.run``), so both are unit-tested with a fake runner;
``LocalScheduler`` runs the script on this node and waits for it;
``DirectScheduler`` (wingtip, a shared node with no scheduler)
starts it detached under nohup and nice and reads its state from the
process table and the exit-status file it leaves. A machine names its
scheduler in catalog/machines.yaml (``scheduler_for``)."""
from __future__ import annotations

import itertools
import re
import subprocess
from dataclasses import dataclass, field


@dataclass(frozen=True)
class JobSpec:
    script: str
    minutes: int = 60
    queue: str = ""
    nodes: int = 1
    env: dict = field(default_factory=dict)
    output: str = ""
    attrs: dict = field(default_factory=dict)


def _run(argv, **kw):
    return subprocess.run(argv, capture_output=True, text=True, **kw)


class Scheduler:
    kind = "abstract"

    def __init__(self, runner=None, max_minutes: int | None = None):
        self.runner = runner or _run
        self.max_minutes = max_minutes

    def _limit(self, spec: JobSpec) -> None:
        if self.max_minutes is not None and spec.minutes > self.max_minutes:
            raise ValueError(f"{spec.minutes} min exceeds this queue's "
                             f"{self.max_minutes} min")

    def command(self, spec: JobSpec) -> list[str]:
        raise NotImplementedError

    def submit(self, spec: JobSpec) -> str:
        self._limit(spec)
        res = self.runner(self.command(spec))
        if res.returncode != 0:
            raise RuntimeError(f"{self.kind} submit failed: "
                               f"{(res.stderr or res.stdout).strip()}")
        return self.job_id(res.stdout)

    def job_id(self, out: str) -> str:
        return out.strip().split()[-1]

    def status(self, job: str) -> str:
        raise NotImplementedError


class FluxScheduler(Scheduler):
    kind = "flux"
    STATES = {"S": "pending", "D": "pending", "P": "pending",
              "R": "running", "C": "running", "CD": "done", "F": "failed",
              "CA": "failed", "TO": "failed", "I": "done"}

    def command(self, spec: JobSpec) -> list[str]:
        argv = ["flux", "batch", "-N", str(spec.nodes), "-t",
                str(spec.minutes)]
        if spec.queue:
            argv += ["-q", spec.queue]
        argv += [f"--setattr={k}={v}" for k, v in spec.attrs.items()]
        argv += [f"--env={k}={v}" for k, v in spec.env.items()]
        if spec.output:
            argv.append(f"--output={spec.output}")
        return argv + [spec.script]

    def status(self, job: str) -> str:
        res = self.runner(["flux", "jobs", "-n", "-a", "-o", "{status_abbrev}",
                           job])
        return self.STATES.get(res.stdout.strip(), "unknown")


class SlurmScheduler(Scheduler):
    kind = "slurm"
    STATES = {"PENDING": "pending", "CONFIGURING": "pending",
              "RUNNING": "running", "COMPLETING": "running",
              "COMPLETED": "done", "FAILED": "failed", "CANCELLED": "failed",
              "TIMEOUT": "failed", "NODE_FAIL": "failed"}

    def command(self, spec: JobSpec) -> list[str]:
        argv = ["sbatch", f"--nodes={spec.nodes}", f"--time={spec.minutes}"]
        if spec.queue:
            argv.append(f"--partition={spec.queue}")
        if spec.output:
            argv.append(f"--output={spec.output}")
        if spec.env:
            argv.append("--export=ALL," + ",".join(
                f"{k}={v}" for k, v in spec.env.items()))
        argv += [f"--{k}={v}" for k, v in spec.attrs.items()]
        return argv + [spec.script]

    def job_id(self, out: str) -> str:
        m = re.search(r"Submitted batch job (\d+)", out)
        if not m:
            raise RuntimeError(f"no job id in sbatch output: {out!r}")
        return m.group(1)

    def status(self, job: str) -> str:
        res = self.runner(["squeue", "-h", "-j", job, "-o", "%T"])
        state = res.stdout.strip()
        if state:
            return self.STATES.get(state, "unknown")
        # a job squeue no longer lists has left the queue: its final state
        # is in the accounting database
        res = self.runner(["sacct", "-n", "-X", "-j", job, "-o", "State"])
        final = (res.stdout.split() or [""])[0].rstrip("+")
        return self.STATES.get(final, "unknown")


class LocalScheduler(Scheduler):
    """Runs the script on this node (tests, a workstation)."""
    kind = "local"
    _ids = itertools.count(1)

    def command(self, spec: JobSpec) -> list[str]:
        return ["env"] + [f"{k}={v}" for k, v in spec.env.items()] + \
            ["bash", spec.script]

    def job_id(self, out: str) -> str:
        return f"local-{next(self._ids)}"

    def status(self, job: str) -> str:
        return "done"


class DirectScheduler(Scheduler):
    """No scheduler (wingtip, a shared login node). The script runs
    detached on this host (setsid nohup), at ``nice`` priority, under
    ``timeout`` of the job's minutes, with its output in ``spec.output``;
    the job id is the wrapper's process id, and the wrapper writes the
    script's exit status to ``<state_dir>/<id>.rc``. ``status``: that file
    -> done (0) or failed; the process alive -> running. GPU choice (free
    GPUs only, one program per GPU) is the script's (tools/jobs/run_wingtip.sh)."""
    kind = "direct"

    def __init__(self, runner=None, max_minutes: int | None = None,
                 nice: int = 10, state_dir: str = ""):
        super().__init__(runner, max_minutes)
        import os
        import tempfile
        self.nice = nice
        self.state_dir = state_dir or os.path.join(
            tempfile.gettempdir(), f"direct-jobs-{os.getuid()}")

    def command(self, spec: JobSpec) -> list[str]:
        import shlex
        env = " ".join(f"{k}={shlex.quote(str(v))}"
                       for k, v in spec.env.items())
        out = shlex.quote(spec.output or "/dev/null")
        state = shlex.quote(self.state_dir)
        inner = (f"mkdir -p {state}; env {env} nice -n {self.nice} timeout "
                 f"{spec.minutes}m bash {shlex.quote(spec.script)} > {out} "
                 f"2>&1; echo $? > {state}/$$.rc")
        return ["bash", "-c", f"setsid nohup bash -c {shlex.quote(inner)} "
                ">/dev/null 2>&1 < /dev/null & echo $!"]

    def status(self, job: str) -> str:
        import os
        rc = os.path.join(self.state_dir, f"{job}.rc")
        if os.path.isfile(rc):
            text = open(rc).read().strip()
            return "done" if text == "0" else "failed"
        return "running" if os.path.exists(f"/proc/{job}") else "unknown"


def scheduler_for(machine, runner=None) -> Scheduler:
    """The scheduler a machine declares (catalog/machines.yaml)."""
    s = machine.scheduler
    cls = {"flux": FluxScheduler, "slurm": SlurmScheduler,
           "local": LocalScheduler, "direct": DirectScheduler}[s["kind"]]
    if cls is DirectScheduler:
        return cls(runner=runner, max_minutes=s.get("max_minutes"),
                   nice=int(s.get("nice", 10)))
    return cls(runner=runner, max_minutes=s.get("max_minutes"))


def spec_for(machine, script: str, env: dict, output: str,
             minutes: int | None = None) -> JobSpec:
    """A JobSpec on the machine's queue with its attributes."""
    s = machine.scheduler
    return JobSpec(script=script, minutes=minutes or s.get("max_minutes", 60),
                   queue=s.get("queue", ""), env=dict(env), output=output,
                   attrs=dict(s.get("attrs") or {}))


def inside_job(machine, runner=None) -> bool:
    """Whether this process runs inside a job allocation of the machine's
    scheduler (local runs of a confirmer belong on compute nodes, not on a
    login node): flux, an instance level above 0; Slurm, SLURM_JOB_ID;
    local, always."""
    import os
    kind = machine.scheduler["kind"]
    if kind in ("local", "direct"):  # no allocation to be inside of
        return True
    if kind == "slurm":
        return bool(os.environ.get("SLURM_JOB_ID"))
    res = (runner or _run)(["flux", "getattr", "instance-level"])
    return res.returncode == 0 and res.stdout.strip() not in ("", "0")
