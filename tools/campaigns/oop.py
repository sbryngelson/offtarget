#!/usr/bin/env python3
"""fortran-oop: the derived-type and object-oriented offload campaign
(offload/engine/oop_gen.py).

The campaign is behind offload/engine/campaigns/oop.py. This is its original
command line, kept for tools/run_oop*.sh and run_wingtip_oop*.sh. All subcommands but ``fuzz-gate`` are the
generic runner's (``python3 -I tools/campaign.py oop ...``):

* ``gen``: programs -> results/oop/<name>/programs.jsonl and src/;
* ``prerun``: the rules and AFAR's front end (a Tuolumne compute node);
* ``witness``: NVHPC 26.9 nvfortran, compile only, on wingtip over ssh;
* ``legality``: the per-program, per-family table of the witnesses;
* ``run``: compile and run (resumable); ``gate``: the reproduction gate;
  ``report``: the tables; ``confirm``: the confirmer;
* ``fuzz-gate``: the fuzz-5 sample's failing rows (results/fuzz/<run>)
  through the gate. Only this tool has it."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine import campaign as C  # noqa: E402
from offload.engine.campaigns.oop import CAMPAIGN  # noqa: E402

OUT = ROOT / "results" / "oop"
# the targets and their memory modes (row keys, catalog/machines.yaml), from
# the catalog through the campaign's capabilities; managed memory (NVHPC row
# key 2) is this campaign's "unified" mode
MODE_NAME = {x: C.mode_name(x) for x in (0, 1, 2)}
TARGETS = CAMPAIGN.caps.targets()
FAILING_OK = C.FAILING_OK
NOT_A_VERDICT = CAMPAIGN.not_a_verdict
_jl, _append = C.read_jsonl, C.append_jsonl
_CACHE: dict = {}


def _run(name: str = "main") -> C.Run:
    return C.Run(CAMPAIGN, OUT / name, C.run_label(CAMPAIGN, name), _CACHE)


def family_of(tc: str) -> str:
    from offload.engine.toolchains import TOOLCHAINS
    return TOOLCHAINS[tc].kind


def _register() -> None:
    """The gate kind is declared when offload.engine.campaigns.oop is imported."""
    C.get("oop")


def _fe(ok, why: str):
    return C._fe(ok, why, NOT_A_VERDICT)


def programs(ids=None) -> list:
    return _run().programs(ids)


def rows(name: str) -> list[dict]:
    return _run(name).rows()


def legality(name: str) -> dict:
    """program id -> {rules, afar_fe, nvhpc_fe, cce_fe, legality, legal_for}
    (offload.engine.campaign.Run.legality_table)."""
    return _run(name).legality_table()


def _cells(progs, toolchains, modes, ok: set):
    return _run().cells(progs, toolchains, modes, ok)


def gate_items(name: str, machine: str | None = None) -> list[dict]:
    return _run(name).gate_items(machine)


def verdicts(name: str) -> dict:
    return _run(name).verdicts()


def _cls(r: dict) -> str:
    return _run().cls(r)


def summary(name: str) -> dict:
    return _run(name).summary()


def matrix(name: str) -> str:
    return _run(name).matrix()


# --- the fuzz-5 sample (results/fuzz/<run>) through the gate --------------------------
# The sample is a fuzz campaign of its own (tools/campaigns/fuzz.py run --gen-version
# fuzz-5 --base-features oop ...); its failing rows are gated here, in this
# campaign's directory (results/oop/fuzz-<run>/), so no shared gate plan of
# the fuzz campaigns is rewritten.

def fuzz_items(run: str) -> list[dict]:
    """offload.engine.gate_stored.fuzz_items for one fuzz campaign directory:
    the failing rows of the programs that passed the legality check."""
    from offload.engine.fuzz_exec import load
    from offload.engine.gate_stored import _mode, machine_of
    from offload.engine.toolchains import TOOLCHAINS
    d = ROOT / "results" / "fuzz" / run
    # meta.json is written after the canaries: a session cut short there
    # has none (tools/jobs/run_oop_pdebug.sh runs the sample at HSA_XNACK=1)
    meta = json.loads((d / "meta.json").read_text()) \
        if (d / "meta.json").is_file() else {"sessions": [{"xnack": 1}]}
    x = meta["sessions"][-1].get("xnack", 1)
    progs, _ = load(d)
    out = []
    for pr in progs:
        if pr.check != "ok" or getattr(pr, "validity", "valid") != "valid":
            continue
        for tc, r in pr.results.items():
            if tc not in TOOLCHAINS or r.cls in ("agree", "harness_error"):
                continue
            out.append({
                "campaign": "fuzz", "kind": "fuzz",
                "cell": f"fuzz|{run}:{pr.seed}|{tc}|{x}",
                "ident": f"{run}:{pr.seed}", "toolchain": tc,
                "machine": machine_of(tc), "xnack": x,
                "mode": _mode(tc, x), "opt": "-O2", "cls": r.cls,
                "reason": r.reason, "checksum": r.checksum,
                "flaky": bool(r.flaky), "compile_s": r.compile_s or None,
                "run_s": r.run_s or None, "timeout_s": 60,
                "build_dir": getattr(r, "build_dir", "") or "",
                "node": getattr(r, "node", "") or "",
                "toolchain_build": getattr(r, "toolchain_build", ""),
                "compile_log": (r.output or "")[-3000:],
                "locator": {"run": run, "seed": pr.seed,
                            "gen_version": pr.gen_version,
                            "base": list(pr.base or ()),
                            "expected": pr.expected}})
    return out


# the gate's budget per sample campaign, serial seconds over its four
# environments: offload.engine.gate.plan samples under it (every new
# compile-time signature first, then run-time failures round-robin; a
# compile-time row not rerun inherits its signature's verdict)
FUZZ_BUDGET_S = 8000


def _fuzz_plan(run: str) -> list[dict]:
    from offload.engine import gate as GT
    return GT.plan(fuzz_items(run), budget_s=FUZZ_BUDGET_S)["rows"]


def cmd_fuzz_gate(a) -> int:
    """Rerun a fuzz-5 sample's failing rows: (a), (b), (d) of the rows of
    this node (`--node same`) or (c) of the other node's (`--node
    other`)."""
    from concurrent.futures import ThreadPoolExecutor
    from offload.engine import gate as GT
    from offload.engine import gate_stored as GS
    from offload.engine.provenance import node
    planned = [r for r in _fuzz_plan(a.run)
               if r["sample"] not in ("own", "inherited")]
    here = node()
    if a.node:
        planned = [it for it in planned if (it.get("node") == here) ==
                   (a.node == "same")]
    out = OUT / f"fuzz-{a.run}" / "gate_reruns.jsonl"
    done = {(r["cell"], r["env"]) for r in _jl(out)}
    envs = a.envs.split(",")
    jobs = []
    for it in planned:
        es = [e for e in GT.environments(it, a.root or None)
              if e["env"] in envs and (it["cell"], e["env"]) not in done]
        if es:
            jobs.append((it, es))
    print(f"{len(planned)} rows here, {sum(len(j[1]) for j in jobs)} "
          "reruns", flush=True)

    def one(job):
        it, es = job
        for e in es:
            rr = GS.rerun(it, e)
            _append(out, [{**rr, "cell": it["cell"]}])
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        list(pool.map(one, jobs))
    return 0


def fuzz_verdicts(run: str) -> dict:
    from collections import defaultdict
    from offload.engine import gate as GT
    reruns = defaultdict(list)
    for r in _jl(OUT / f"fuzz-{run}" / "gate_reruns.jsonl"):
        reruns[r["cell"]].append(r)
    planned = _fuzz_plan(run)
    judged = {}
    for it in planned:
        try:
            judged[it["cell"]] = GT.judge(it, reruns[it["cell"]])
        except ValueError:
            pass
    final = GT.inherit(planned, {c: j["verdict"] for c, j in judged.items()})
    return {it["cell"]: {**judged.get(it["cell"], {}),
                         **final.get(it["cell"], {"verdict": "unchecked"}),
                         "item": it} for it in planned}


def _campaign_tool():
    spec = importlib.util.spec_from_file_location("campaign_tool",
                                                  ROOT / "tools" / "campaign.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["fuzz-gate"]:
        ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
        ap.add_argument("--run", required=True)
        ap.add_argument("--envs", default="a,b,c,d")
        ap.add_argument("--node", choices=("same", "other"))
        ap.add_argument("--root")
        ap.add_argument("--workers", type=int, default=8)
        return cmd_fuzz_gate(ap.parse_args(argv[1:]))
    return _campaign_tool().main(["oop", *argv])


if __name__ == "__main__":
    sys.exit(main())
