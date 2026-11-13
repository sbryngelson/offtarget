"""nested-data behind the campaign interface: pointer-linked data structures
mapped to the device, in C and Fortran, OpenMP 5.2 and OpenACC 3.4
(offload/engine/nested_gen.py; docs/tooling/nested-data.md). The draw
is ``nested_gen.pilot``; its options (``min_cover``, ``legacy``,
``max_tries``) are the draw's and are recorded in meta.json, so the second
draw (seed 11, n 1000, min_cover 8, legacy False, max_tries 600: the 1055
programs of results/nested/big) regenerates unchanged.

Measured on every family of Tuolumne and wingtip (regression releases
included) and on GCC on Tioga; the gate kind is ``nested``; a program whose
legality is ``unspecified``, ``illegal`` or ``pending`` runs, but its
failures are observations, never findings."""
from __future__ import annotations

import re

from offload.engine import campaign as C

# what NVHPC says about the map modifiers, declare mapper and the
# allocatable runtime it lacks, on top of the shared list
NOT_A_VERDICT = re.compile(
    C.NOT_A_VERDICT.pattern +
    r"|invalid text in pragma|syntax error at or near|openmp gpu - 'target'"
    r" is used with map-type|call to nvhpc runtime function|openacc data "
    r"clause expected|no acc routine information", re.I)


class Nested(C.Campaign):
    name = "nested"
    caps = C.Capabilities(
        langs=("c", "f90"), models=("omp", "acc"),
        families={"tuolumne": ("afar", "cce"), "tioga": ("gcc",), "wingtip": None},
        regression=True, draw_options=("min_cover", "legacy", "max_tries"))
    not_a_verdict = NOT_A_VERDICT
    fe_timeout_s = 90           # one front-end check; a hang is no verdict
    doc = "docs/tooling/nested-data.md"

    def programs(self, seed: int = 1, n: int = 400, **opts) -> list:
        from offload.engine import nested_gen as G
        return G.pilot(n, seed, min_cover=opts.get("min_cover", G.MIN_COVER),
                       legacy=opts.get("legacy", True),
                       max_tries=opts.get("max_tries", 80))

    def record(self, p) -> dict:
        return {"id": p.id, "family": p.family, "lang": p.lang,
                "model": p.model, "version": p.version,
                "legality": p.legality, "why": p.why,
                "expected": p.expected, "rules": list(p.rules),
                "cites": [dict(r) for r in p.cites], "axes": p.axes,
                "title": p.title}

    def parse_observed(self, stdout: str) -> dict:
        from offload.engine import nested_gen as G
        return G.parse_observed(stdout)

    def row_tags(self, p) -> dict:
        return {"family": p.family, "lang": p.lang, "model": p.model,
                "legality": p.legality}

    def gate_tags(self, r: dict) -> dict:
        return {"family": r["family"]}

    def short_id(self, p) -> str:
        return p.id[3:]

    def facets(self, p) -> set:
        out = set()
        for k, v in p.axes.items():
            if k in ("constructs", "objects"):
                continue
            for x in (v if isinstance(v, list) else [v]):
                out.add(f"{k}={x}")
        return out


CAMPAIGN = C.register(Nested())
