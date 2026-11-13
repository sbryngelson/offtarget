#!/usr/bin/env python3
"""The generic campaign runner: any campaign registered in offload.engine.campaign,
run with ``python3 -I`` from the repository root. Steps that compile or run need a compute node (or the wingtip cap).

    tools/campaign.py list
    tools/campaign.py CAMPAIGN gen --name N --n 400 --seed 1 [--opt key=value ...]
    tools/campaign.py CAMPAIGN prerun|witness|legality --name N [--workers 8]
    tools/campaign.py CAMPAIGN run --name N --machine M [--toolchains a,b] [--modes 0,1] [--shard k/m]
    tools/campaign.py CAMPAIGN gate --name N --machine M --envs a,b,d --node same   # then --envs c --node other
    tools/campaign.py CAMPAIGN report|cluster|confirm|findings-plan --name N
    tools/campaign.py CAMPAIGN submit --machine M --steps "run abd" --name N [--go]
    tools/campaign.py CAMPAIGN lane MACHINE   # root of the private copy on a remote machine

``submit`` prints the submission command from the job scripts (tools/
run_campaign.sh, run_wingtip_campaign.sh) and runs it only with ``--go``.
``--results DIR`` (before the campaign name) puts run directories under DIR."""
from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine import campaign as C  # noqa: E402

# the job scripts (reused, never forked per campaign)
FLUX_SCRIPT = "tools/jobs/run_campaign.sh"
WINGTIP_SCRIPT = "tools/jobs/run_wingtip_campaign.sh"


def parse_opt(s: str):
    """``key=value`` with a JSON value (``legacy=false``, ``min_cover=8``),
    else the text."""
    import json
    if "=" not in s:
        raise argparse.ArgumentTypeError(f"--opt {s!r}: key=value")
    k, v = s.split("=", 1)
    try:
        return k, json.loads(v)
    except json.JSONDecodeError:
        return k, v


def run_of(camp: C.Campaign, a) -> C.Run:
    results = Path(a.results) if getattr(a, "results", None) else None
    return C.Run(camp, C.run_dir(camp, a.name, results), C.run_label(camp, a.name))


def cmd_list(a, runner=None) -> int:
    for name in C.names():
        camp = C.get(name)
        tg = camp.caps.targets()
        print(f"{name}: kind {camp.gate_kind} (prefix {camp.gate_prefix}, "
              f"{camp.signature}); languages {', '.join(camp.caps.langs)}; "
              f"models {', '.join(camp.caps.models)}; labels {', '.join(camp.labels)}"
              + (f"; {camp.doc}" if camp.doc else ""))
        for m, (tcs, modes) in tg.items():
            print(f"    {m}: {', '.join(tcs)}; modes {modes}")
        if camp.caps.draw_options:
            print(f"    draw options: {', '.join(camp.caps.draw_options)}")
    return 0


def refuse_sealed(camp: C.Campaign, a) -> None:
    """A sealed run (the campaign's `sealed_runs`) is run and gated but never reported."""
    if run_of(camp, a).sealed:
        raise SystemExit(f"{camp.name}/{a.name} is a sealed run: its results are read by "
                         "its scorer only, never reported, clustered or confirmed here")


def cmd_gen(camp, a, runner=None) -> int:
    run = run_of(camp, a)
    n = run.gen(a.seed, a.n, **dict(a.opt or []))
    print(f"{n} programs -> {run.d}")
    return 0


def cmd_prerun(camp, a, runner=None) -> int:
    run_of(camp, a).prerun(runner, workers=a.workers)
    return 0


def cmd_witness(camp, a, runner=None) -> int:
    run_of(camp, a).witness(runner, workers=a.workers)
    return 0


def cmd_legality(camp, a, runner=None) -> int:
    run_of(camp, a).legality()
    return 0


def cmd_run(camp, a, runner=None) -> int:
    return run_of(camp, a).run(
        a.machine, runner, toolchains=a.toolchains.split(",") if a.toolchains else None,
        modes=[int(m) for m in a.modes.split(",")] if a.modes else None,
        ids=a.ids.split(",") if a.ids else None, legal_only=a.legal_only,
        workers=a.workers, shard=a.shard, timeout_s=a.timeout, limit_s=a.limit_s)


def cmd_gate(camp, a, runner=None) -> int:
    return run_of(camp, a).gate(
        a.machine, runner, envs=a.envs, node=a.node, stored_on=a.stored_on,
        shard=a.shard, root=a.root, workers=a.workers, timeout_s=a.timeout,
        budget_s=a.budget_s)


def cmd_report(camp, a, runner=None) -> int:
    refuse_sealed(camp, a)
    run_of(camp, a).report()
    return 0


def cmd_cluster(camp, a, runner=None) -> int:
    refuse_sealed(camp, a)
    run_of(camp, a).cluster()
    return 0


def cmd_confirm(camp, a, runner=None) -> int:
    refuse_sealed(camp, a)
    run_of(camp, a).confirm()
    return 0


def cmd_findings_plan(camp, a, runner=None) -> int:
    refuse_sealed(camp, a)
    run_of(camp, a).findings_plan()
    return 0


# --- submission: the machines' conventions (docs/tooling/contributing.md) ------------------

# one foreground pdebug job, named like a compile (Tuolumne <= 30 min when
# pbatch is starved, Tioga <= 60 min: this account has no pbatch there); the
# limits come from catalog/toolchains.yaml `pdebug`
PDEBUG = ("flux run -q pdebug -N1 -n1 --exclusive -t {minutes}m --setattr=thp=always "
          "--job-name=compile-test-{camp}-{name}{requires} {script} {camp} {steps} {name} "
          "{limit} {workers}")
PBATCH = ("flux batch -q pbatch -N1 -t {minutes}m --setattr=thp=always "
          "--job-name={camp}-{tag} --output=results/{camp}/logs/run.{{{{id}}}}.log{requires} "
          "{script} {camp} {steps} {name} {limit} {workers}")
SLACK_S = 300          # the job's time beyond the script's limit (startup, the last step's timeout)


def _minutes(limit_s: int) -> int:
    return (limit_s + SLACK_S + 59) // 60


def _capped(limit_s: int, max_minutes: int) -> tuple[int, int]:
    """(script limit, job minutes) under a queue's longest job: the script's
    limit shrinks so the job is never killed mid-step."""
    minutes = _minutes(limit_s)
    if minutes > max_minutes:
        return max_minutes * 60 - SLACK_S, max_minutes
    return limit_s, minutes


def lane_root(camp: C.Campaign, machine: str) -> str:
    """The campaign's private copy of the tree on a remote machine
    (catalog/toolchains.yaml ``campaign_lanes``)."""
    from offload.engine.toolchains import registry
    base = registry().campaign_lanes.get(machine)
    if not base:
        raise SystemExit(f"{machine}: not under campaign_lanes in catalog/toolchains.yaml "
                         "(the machine takes no remote campaign copy)")
    return f"{base}/{camp.name}-lane"


def submission(camp: C.Campaign, machine: str, steps: str, name: str, limit_s: int,
               workers: int, queue: str = "", not_host: str = "") -> str:
    """The command that starts `steps` of the campaign on `machine`; it
    makes the log directory first. A foreground (pdebug) job obeys the
    queue's longest job and nodes (catalog/toolchains.yaml ``pdebug``): the
    script's limit shrinks with the job's minutes. `not_host`: the node to
    keep off (the gate's (c) is another node than (a)'s)."""
    from offload.engine.confirm import machines as M
    from offload.engine.toolchains import registry
    m = M.load()[machine]
    rules = registry().pdebug.get(machine, {})
    requires = f" --requires=-host:{not_host}" if not_host else ""
    logs = f"mkdir -p results/{camp.name}/logs && "
    fields = dict(camp=camp.name, name=name, steps=shlex.quote(steps), workers=workers,
                  script=FLUX_SCRIPT, tag=steps.split()[0])
    if machine == "wingtip":
        cap = (m.access or {}).get("cap") or ""      # every command there runs capped
        lane = lane_root(camp, machine)
        py = m.access.get("python", "python3")
        inner = (f"cd {lane} && {logs}PY={py} setsid nohup {cap} {WINGTIP_SCRIPT} {camp.name} "
                 f"{limit_s} {min(workers, 2)} {name} > results/{camp.name}/logs/wingtip.log "
                 "2>&1 < /dev/null &")
        return f"ssh {m.access['ssh']} {shlex.quote(inner)}"
    if isinstance(m.access, dict) and m.access.get("ssh"):   # Tioga: from its copy
        lane = lane_root(camp, machine)
        py = m.access.get("python", "python3")
        limit, minutes = _capped(limit_s, int(rules.get("max_minutes", 60)))
        if rules.get("hosts"):
            requires = f" --requires=host:{rules['hosts']}" + requires
        cmd = PDEBUG.format(minutes=minutes, limit=limit, requires=requires, **fields)
        inner = f"builtin cd {lane} && {logs}MACHINE={machine} PY={py} {cmd}"
        return f"ssh {m.access['ssh']} {shlex.quote(inner)}"
    if queue == "pdebug":
        limit, minutes = _capped(limit_s, int(rules.get("max_minutes", 30)))
        return logs + PDEBUG.format(minutes=minutes, limit=limit, requires=requires, **fields)
    return logs + PBATCH.format(minutes=_minutes(limit_s), limit=limit_s, requires=requires,
                                **fields)


def cmd_submit(camp, a, runner=None) -> int:
    cmd = submission(camp, a.machine, a.steps, a.name, int(a.limit_s), a.workers, a.queue,
                     a.not_host or "")
    print(cmd)
    if a.go:
        return subprocess.run(["bash", "-c", cmd], cwd=ROOT).returncode
    return 0


def cmd_lane(camp, a, runner=None) -> int:
    print(lane_root(camp, a.machine))
    return 0


# --- the command line -------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results", help="run directories under DIR instead of results/")
    top = ap.add_subparsers(dest="top", required=True)
    top.add_parser("list", help="the registered campaigns and their targets")
    for name in C.names():
        cp = top.add_parser(name)
        sub = cp.add_subparsers(dest="cmd", required=True)
        g0 = sub.add_parser("gen")
        g0.add_argument("--name", default="main")
        g0.add_argument("--n", type=int, default=0)
        g0.add_argument("--seed", type=int, default=0)
        g0.add_argument("--opt", type=parse_opt, action="append",
                        help="a draw option, key=value (the campaign's draw_options)")
        for n in ("prerun", "witness", "legality", "report", "cluster", "confirm",
                  "findings-plan"):
            p = sub.add_parser(n)
            p.add_argument("--name", default="main")
            p.add_argument("--workers", type=int, default=8)
        r = sub.add_parser("run")
        r.add_argument("--name", default="main")
        r.add_argument("--machine", required=True)
        r.add_argument("--toolchains")
        r.add_argument("--modes")
        r.add_argument("--ids")
        r.add_argument("--legal-only", action="store_true")
        r.add_argument("--workers", type=int, default=8)
        r.add_argument("--shard")
        r.add_argument("--timeout", type=int)
        r.add_argument("--limit-s", type=float, default=3000)
        g = sub.add_parser("gate")
        g.add_argument("--name", default="main")
        g.add_argument("--machine", required=True)
        g.add_argument("--envs", default="a,b,c,d")
        g.add_argument("--node", choices=("same", "other", "any"))
        g.add_argument("--stored-on", help="only rows stored on these nodes")
        g.add_argument("--shard")
        g.add_argument("--root")
        g.add_argument("--workers", type=int, default=8)
        g.add_argument("--timeout", type=int)
        g.add_argument("--budget-s", type=float)
        s = sub.add_parser("submit")
        s.add_argument("--machine", required=True)
        s.add_argument("--steps", default="run abd")
        s.add_argument("--name", default="main")
        s.add_argument("--limit-s", type=float, default=3000)
        s.add_argument("--workers", type=int, default=16)
        s.add_argument("--queue", default="", choices=("", "pbatch", "pdebug"))
        s.add_argument("--not-host", help="keep the job off this node (the gate's (c) "
                                          "after (a) ran on it)")
        s.add_argument("--go", action="store_true", help="run it (default: print it)")
        ln = sub.add_parser("lane")
        ln.add_argument("machine")
    return ap


COMMANDS = {"gen": cmd_gen, "prerun": cmd_prerun, "witness": cmd_witness,
            "legality": cmd_legality, "run": cmd_run, "gate": cmd_gate,
            "report": cmd_report, "cluster": cmd_cluster, "confirm": cmd_confirm,
            "findings-plan": cmd_findings_plan, "submit": cmd_submit, "lane": cmd_lane}


def main(argv=None, runner=None) -> int:
    """`runner`: a runner object for the steps that compile or run (the
    tests' FakeRunner); None: offload.engine.campaign.HarnessRunner."""
    a = build_parser().parse_args(argv)
    try:
        if a.top == "list":
            return cmd_list(a)
        camp = C.get(a.top)
    except ValueError as e:          # a campaign the catalog cannot satisfy
        raise SystemExit(f"refused: {e}")
    if getattr(a, "machine", None) and a.cmd in ("run", "gate", "submit") \
            and a.machine not in camp.caps.machines():
        raise SystemExit(f"{camp.name} is not measured on {a.machine} (its machines: "
                         f"{', '.join(camp.caps.machines())})")
    return COMMANDS[a.cmd](camp, a, runner)


if __name__ == "__main__":
    sys.exit(main())
