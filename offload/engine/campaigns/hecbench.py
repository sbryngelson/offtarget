"""The ``hecbench`` campaign: ORNL HeCBench OpenMP-offload benchmarks (``src/<name>-omp``)
built and run by every toolchain and memory mode, to find failures in real code
(data/reports/hecbench.md).

Programs are recipes (offload.engine.hecbench) derived from each benchmark's Makefile.
A hash of the directory name splits them into a dev half (data/bench/hecbench/recipes.yaml)
and a holdout half (data/bench/hecbench-holdout/recipes.yaml); the run named ``holdout``
is never reported, clustered or confirmed here. A benchmark excluded for a
non-compiler reason is refused at the pre-run with the reason. Sources stay in
the git-ignored clone corpus/apps/HeCBench-ornl; the run directory's
programs.jsonl carries the recipes. A failure counts as evidence only when the
reproduction gate confirms it and a compiler of another family runs the same
program correctly (offload.engine.hecbench_report)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from offload.engine import campaign as C
from offload.engine import hecbench as H

HOLDOUT_RUN = "holdout"


@dataclass
class Program:
    id: str
    dir: str
    half: str
    recipe: dict
    lang: str = "c"                 # the interface's language slot (the sources are C or C++)
    model: str = "omp"
    version: int = 52
    legality: str = "pending"
    why: str = "real code: legality is not judged; evidence needs the gate and a witness family"
    expected: dict = field(default_factory=dict)
    cites: tuple = ()
    modes: tuple = ("copy", "unified")
    ref: dict | None = field(default=None, compare=False)

    @property
    def source(self) -> str:
        return H.recipe_json(self.recipe)

    @property
    def text(self) -> str:
        return self.source

    def harness(self):
        return self

    def reference_output(self) -> str | None:
        r = self.ref
        return r["out"] if r and r.get("ok") else None


def _full_recipes(half: str) -> dict:
    """dir -> the whole recipe of the half: the tracked file's, and for a gpl-style
    benchmark (tracked as an id only) the private copy under results/."""
    path = H.RECIPES if half == "dev" else H.HOLDOUT_RECIPES
    tracked = H.load_recipes(path)
    priv = H.RESULTS / f"recipes_{half}_full.json"
    full = {}
    if priv.is_file():
        full = {r["dir"]: r for r in json.loads(priv.read_text())}
    return {d: (full.get(d) if r["licence"] in H.WITHHELD and d in full else r)
            for d, r in tracked.items()}


class Hecbench(C.Campaign):
    name = "hecbench"
    labels = ("pending",)
    caps = C.Capabilities(langs=("c",), models=("omp",),
                          families={"tuolumne": ("afar", "cce"), "tioga": None, "wingtip": None},
                          regression=True, draw_options=("half",))
    printed_values = False
    compile_limit_s = H.COMPILE_TIMEOUT_S
    timeout_s = H.RUN_TIMEOUT_S
    doc = "data/reports/hecbench.md"
    stored_programs = True
    sealed_runs = (HOLDOUT_RUN,)

    def programs(self, seed: int = 0, n: int = 0, half: str = "dev", **opts) -> list:
        if half not in ("dev", "holdout"):
            raise ValueError(f"half: dev or holdout, not {half!r}")
        recipes = _full_recipes(half)
        names = sorted(recipes)
        if n:
            names = names[:n]
        return [Program(recipes[d]["id"], d, half, recipes[d]) for d in names]

    def programs_from_records(self, rows: list) -> list:
        return [Program(r["id"], r["recipe"]["dir"], r["recipe"]["half"], r["recipe"])
                for r in sorted(rows, key=lambda r: r["id"])]

    def is_sealed(self, programs: list) -> bool:
        return any(p.half == "holdout" for p in programs)

    def bind_run(self, run_dir, programs: list) -> None:
        """Give each program its serial host reference (the pre-run rows)."""
        refs = {r["id"]: r.get("ref") for r in C.read_jsonl(run_dir / "prerun.jsonl")}
        for p in programs:
            p.ref = refs.get(p.id)

    def record(self, p) -> dict:
        d = super().record(p)
        d["recipe"] = p.recipe
        return d

    def src_name(self, p) -> str:
        return f"{p.id}.recipe.json"

    def ext(self, p) -> str:
        return "c"

    def gated(self, p) -> bool:
        return p.recipe["status"] == "ok"

    def make_runner(self):
        from offload.engine.hecbench_run import HecbenchRunner
        return HecbenchRunner(self)

    def gate_filter(self, items: list, rows: list) -> list:
        """A failure counts as evidence only with a compiler of another family running the
        program correctly in the same memory mode (offload.engine.hecbench_report.witnessed), so a
        cell without such a witness is not worth the gate's four reruns: it stays unconfirmed."""
        from offload.engine import hecbench_report as RP
        by = {}
        for r in rows:
            by.setdefault(r["program_id"], []).append(r)
        return [it for it in items
                if RP.witnessed({"toolchain": it["toolchain"], "xnack": it["xnack"]},
                                by.get(it["ident"], []), C.mode_name)]

    def row_tags(self, p) -> dict:
        return {"lang": p.recipe.get("lang") or "cpp", "model": "omp", "legality": "pending",
                "half": p.half, "licence": p.recipe["licence"]}

    def mark(self, p) -> str:
        return ""

    def facets(self, p) -> set:
        r = p.recipe
        out = {f"lang={r.get('lang')}", f"std={r.get('std') or 'default'}",
               f"files={len(r['compiles'])}"}
        out |= {f"lib={x}" for x in r.get("libs", []) if x != "m"}
        return out

    def parse_observed(self, stdout: str) -> dict:
        return {}


CAMPAIGN = C.register(Hecbench())
