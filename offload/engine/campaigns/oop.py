"""fortran-oop behind the campaign interface: the derived-type and
object-oriented offload families (offload/engine/oop_gen.py). A hand-listed campaign: ``programs``
is ``oop_gen.programs()`` whatever the draw arguments (its run directory
has no meta.json, and none is needed).

Fortran only, OpenMP and OpenACC; measured on every family of Tuolumne and
wingtip (regression releases included) and on GCC on Tioga; the gate kind is
``oop``. Every program is gated (a failure of an ``unspecified`` program is
confirmed against the stored evidence too, with legality ``unknown``: the
confirmer's legality keys on the label, never on ``gated``), as tools/campaigns/oop.py
always did."""
from __future__ import annotations

from offload.engine import campaign as C


class Oop(C.Campaign):
    name = "oop"
    labels = ("defined", "unspecified")
    hand_listed = True
    caps = C.Capabilities(
        langs=("f90",), models=("omp", "acc"),
        families={"tuolumne": ("afar", "cce"), "tioga": ("gcc",), "wingtip": None},
        regression=True)

    def programs(self, seed: int = 0, n: int = 0, **opts) -> list:
        from offload.engine import oop_gen as G
        return G.programs()

    def record(self, p) -> dict:
        return {"id": p.id, "family": p.family, "variant": p.variant,
                "model": p.model, "version": p.version,
                "legality": p.legality, "why": p.why,
                "expected": p.expected, "modes": list(p.modes),
                "cites": list(p.cites), "title": p.title}

    def parse_observed(self, stdout: str) -> dict:
        from offload.engine import oop_gen as G
        return G.parse_observed(stdout)

    def gated(self, p) -> bool:
        return True

    def unknown_why(self, p) -> str:
        return f"unspecified behaviour: {p.why}"[:300]

    def row_tags(self, p) -> dict:
        return {"family": p.family, "variant": p.variant, "model": p.model,
                "legality": p.legality}

    def gate_tags(self, r: dict) -> dict:
        return {"family": r["family"]}

    def short_id(self, p) -> str:
        return p.id[4:]

    def mark(self, p) -> str:
        return "U" if p.legality != "defined" else ""


CAMPAIGN = C.register(Oop())
