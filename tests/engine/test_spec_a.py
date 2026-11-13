"""The public site's "What the specification requires" section reads the
verified spec citations of a finding (offload.engine.site.data._citations).
These 27 findings each carry at least one citation that checks against the
spec text, and every citation they carry checks."""
from pathlib import Path

import pytest

from offload.engine import citations as C
from offload.engine.site import data as D

pytestmark = pytest.mark.needs_spec

BASE = Path(__file__).resolve().parent.parent.parent / "data" / "findings"
IDS = """afar-cce19-character-defaultmap cce19-target-parallel-guarded-loop
cce19-target-parallel-single-ice afar-loop-bind-thread-in-teams cce21-in-reduction-taskwait-link
afar-flang-task-reduction-max afar-flang-loop-bind-teams-reduction
afar-flang-thread-limit-target-parallel-do afar-flang-firstprivate-map-two-targets
afar-nontemporal-assumed-shape-ice afar-xnack1-atomic-min-nested-parallel afar-udr-derived-type-link
catalog/afar-c-reduction-task-link catalog/afar-flang-reduction-minus-rejected
catalog/afar-flang-ordered-wrong catalog/cce-c-map-iterator-ice catalog/cce21-c-target-loop-ice
catalog/cce20-c-defaultmap-private-storage-rejected catalog/cce-c-allocate-align-link
catalog/cce-c-allocate-allocator-modifier-rejected catalog/cce-c-dist-schedule-chunk
catalog/cce-allocators-stack-ice catalog/cce19-reduction-task-addrspacecast-ice
catalog/cce-reduction-task-link catalog/c-allocate-const-mem-firstprivate-wrong
catalog/cce-flang-lastprivate-parallel-in-seq-loop-wrong
catalog/cce-acc-character-dummy-routine-ice""".split()


def finding(fid):
    hits = sorted(p for p in (BASE / fid).parent.glob(Path(fid).name + ".*")
                  if p.suffix in (".f90", ".c"))
    assert len(hits) == 1, (fid, hits)
    return hits[0]


def test_there_are_27():
    assert len(IDS) == len(set(IDS)) == 27


@pytest.mark.parametrize("fid", IDS)
def test_has_a_verified_citation(fid):
    assert len(D._citations(finding(fid))) >= 1


@pytest.mark.parametrize("fid", IDS)
def test_every_citation_checks(fid):
    p = finding(fid)
    res = C.scan([p.resolve()])
    assert res, f"{fid}: no citation"
    bad = [r.line() for r in res if r.status != "ok"]
    assert not bad, bad


@pytest.mark.parametrize("fid", IDS)
def test_comments_only_and_last(fid):
    """The citations are comment lines at the very end of the file, after
    any site block (no code line moves) and within the Fortran line limit."""
    p = finding(fid)
    lines = p.read_text().split("\n")
    assert lines[-1] == ""
    lead = "!" if p.suffix == ".f90" else "//"
    i = next(k for k, ln in enumerate(lines) if ln.startswith(lead + " spec (requirement):"))
    tail = [ln for ln in lines[i:-1]]
    assert all(ln.startswith(lead) for ln in tail)
    assert any(ln.startswith(lead + " spec (this program):") for ln in tail)
    if p.suffix == ".f90":
        assert all(len(ln) <= 132 for ln in tail)
