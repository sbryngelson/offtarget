#!/usr/bin/env python3
"""nested-data: pointer-linked data structures mapped to the device, in C and
Fortran, OpenMP 5.2 and OpenACC 3.4 (offload/engine/nested_gen.py).

The campaign is registered in offload/engine/campaigns/nested.py. This tool is its
command line for tools/run_nested*.sh and tools/campaigns/nested_findings.py;
each subcommand is the generic runner's (``tools/campaign.py nested ...``):
* ``gen``: sample programs (``--n``, ``--seed``, ``--current-labels``,
  ``--min-cover``, ``--max-tries``) into results/nested/<name>/;
* ``prerun``, ``witness``, ``legality``: the rule and AFAR witnesses, the NVHPC
  26.9 compile-only witness (wingtip, over ssh) and the per-family table;
* ``run``, ``gate``, ``report``, ``cluster``, ``confirm``: compile and run
  (resumable), reproduction gate, tables, failure clusters, confirmer.

Failures of a program whose legality is ``unspecified``, ``illegal`` or
``pending`` are observations, never findings."""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine import campaign as C  # noqa: E402
from offload.engine.campaigns.nested import CAMPAIGN, NOT_A_VERDICT  # noqa: E402,F401

OUT = ROOT / "results" / "nested"
MODE_NAME = {x: C.mode_name(x) for x in (0, 1, 2)}
# machine -> (toolchains, row keys), from the catalog through the campaign's
# capabilities (no toolchain is named here)
TARGETS = CAMPAIGN.caps.targets()
FAILING_OK = C.FAILING_OK
FE_TIMEOUT_S = CAMPAIGN.fe_timeout_s
_jl, _append = C.read_jsonl, C.append_jsonl
_CACHE: dict = {}


def _run(name: str = "main") -> C.Run:
    return C.Run(CAMPAIGN, OUT / name, C.run_label(CAMPAIGN, name), _CACHE)


def _fe(ok, why: str):
    return C._fe(ok, why, NOT_A_VERDICT)


def family_of(tc: str) -> str:
    from offload.engine.toolchains import TOOLCHAINS
    return TOOLCHAINS[tc].kind


def _register() -> None:
    """The gate kind is declared when offload.engine.campaigns.nested is imported
    (kept for tools/campaigns/nested_findings.py)."""
    C.get("nested")


def programs(name: str = "main", ids=None) -> list:
    """The campaign's programs: the sample regenerated from meta.json and
    checked against programs.jsonl's hashes."""
    return _run(name).programs(ids)


def ext(p) -> str:
    return CAMPAIGN.ext(p)


def cmd_gen(a) -> int:
    opts = {}
    if getattr(a, "current_labels", False):
        opts = dict(min_cover=a.min_cover, legacy=False, max_tries=a.max_tries)
    run = _run(a.name)
    n = run.gen(a.seed, a.n, **opts)
    print(f"{n} programs -> {run.d}")
    return 0


def rows(name: str) -> list[dict]:
    return _run(name).rows()


def legality(name: str) -> dict:
    """program id -> {rules, afar_fe, nvhpc_fe, cce_fe, legality, legal_for}
    (offload.engine.campaign.Run.legality_table)."""
    return _run(name).legality_table()


def _cells(progs, toolchains, modes, ok: set):
    return _run().cells(progs, toolchains, modes, ok)


def prerun_ok(name: str) -> set:
    return _run(name).prerun_ok()


def gate_items(name: str, machine: str | None = None) -> list[dict]:
    return _run(name).gate_items(machine)


def gate_budget(name: str) -> float | None:
    return _run(name).gate_budget()


def gate_plan(items: list[dict], budget_s: float | None = None) -> dict:
    from offload.engine import gate as GT
    total = sum(len(GT.ENVS) * GT.cost_s(it) for it in items) + 1
    return GT.plan(items, budget_s=budget_s or total)


_node_share = C.Run.node_share


def verdicts(name: str) -> dict:
    return _run(name).verdicts()


def _cls(r: dict) -> str:
    return _run().cls(r)


SHORT = C.SHORT


def summary(name: str) -> dict:
    return _run(name).summary()


def matrix(name: str) -> str:
    return _run(name).matrix()


norm_reason = C.norm_reason


def row_signature(r: dict) -> str:
    return C.row_signature(r, _cls(r))


def axis_items(p) -> set:
    return CAMPAIGN.facets(p)


def clusters(name: str) -> list[dict]:
    return _run(name).clusters()


def _legality(p, toolchain: str, leg: dict):
    return _run().cell_legality(p, toolchain, leg)


def _campaign_tool():
    spec = importlib.util.spec_from_file_location("campaign_tool",
                                                  ROOT / "tools" / "campaign.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["gen"]:
        ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
        ap.add_argument("--name", default="main")
        ap.add_argument("--n", type=int, default=400)
        ap.add_argument("--seed", type=int, default=1)
        ap.add_argument("--current-labels", action="store_true",
                        help="draw under the current labels with --min-cover")
        ap.add_argument("--min-cover", type=int, default=8)
        ap.add_argument("--max-tries", type=int, default=600)
        return cmd_gen(ap.parse_args(argv[1:]))
    return _campaign_tool().main(["nested", *argv])


if __name__ == "__main__":
    sys.exit(main())
