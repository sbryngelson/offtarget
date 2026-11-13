"""A toy campaign: the whole of what a new campaign is, in one module (plus
its registry entry, which tests/cluster/test_campaigns.py adds as
``offload.engine.campaign.MODULES["toy"] = "tests.toy_campaign"``). Its
programs are synthetic (a Fortran and a C program per draw index) and its
expected values are computed here; the generic runner takes it through
gen, prerun, run, gate, confirm and report with a fake runner and no GPU.
"""
from __future__ import annotations

from dataclasses import dataclass

from offload.engine import campaign as C

F90 = """program toy{k}
  use omp_lib
  implicit none
  integer :: r, host
  r = 0
  !$omp target map(tofrom: r) map(from: host)
  host = merge(1, 0, omp_is_initial_device())
  r = {k} + 5
  !$omp end target
  print '(a,i0)', 'r= ', r
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host, ' check=', merge('pass', 'fail', r == {expect})
end program toy{k}
"""

C_SRC = """#include <stdio.h>
#include <omp.h>
int main(void) {{
  int r = 0, host = 1;
  #pragma omp target map(tofrom: r) map(from: host)
  {{ host = omp_is_initial_device(); r = {k} + 5; }}
  printf("r= %d\\n", r);
  printf("RESULT ran_on_host=%d check=%s\\n", host, r == {expect} ? "pass" : "fail");
  return 0;
}}
"""


@dataclass(frozen=True)
class Program:
    id: str
    lang: str
    model: str
    version: int
    source: str
    expected: dict
    legality: str
    why: str
    cites: tuple
    modes: tuple = ("copy", "unified")

    @property
    def text(self) -> str:
        return self.source

    def harness(self):
        from offload.engine.gen import Program as HP
        return HP(id=self.id, lang=self.lang, source=self.source,
                  atoms=frozenset({"toy.scalar"}), primary_atom="toy.scalar",
                  legal=self.legality == "defined", violates=None,
                  observable=True, model=self.model)


class Toy(C.Campaign):
    name = "toy"
    labels = ("defined", "unspecified")
    caps = C.Capabilities(langs=("c", "f90"), models=("omp",),
                          families={"tuolumne": None, "wingtip": None},
                          regression=False, draw_options=("step",))
    printed_values = True

    def programs(self, seed: int = 0, n: int = 2, step: int = 1, **opts) -> list:
        out = []
        for i in range(n):
            k = seed + i * step
            for lang, tpl in (("f90", F90), ("c", C_SRC)):
                legality = "defined" if i % 3 != 2 else "unspecified"
                out.append(Program(
                    id=f"toy-{lang}-{k}", lang=lang, model="omp", version=52,
                    source=tpl.format(k=k, expect=k + 5), expected={"r": k + 5},
                    legality=legality,
                    why="" if legality == "defined" else "a made-up open question",
                    cites=({"version": "5.2", "section": "13.8", "quote": "target"},)))
        return out


CAMPAIGN = C.register(Toy())
