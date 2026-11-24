"""The citations of a generated finding (offload.engine.fuzz_cites): each construct's section of the
specification, found by its heading, and the first sentence of its Semantics (OpenMP) or Summary
(OpenACC), located to the printed page and lines and checked like any citation."""
import pytest

from offload.engine import fuzz_cites as FC

pytestmark = pytest.mark.needs_spec


def test_a_construct_is_cited_by_the_first_sentence_of_its_semantics():
    c = FC.cite("dir:teams", "omp")
    assert c["version"] == "OpenMP 5.2" and c["section"] == "10.2" and c["page"] == 230
    assert c["quote"].startswith("When a thread encounters a teams construct, a league of teams is created.")
    from offload.engine.dataenv_rules import check_citation
    assert check_citation(c) == []


def test_a_clause_and_an_openacc_construct_are_cited_the_same_way():
    from offload.engine.dataenv_rules import check_citation
    for key, model, sec in (("clause:thread_limit", "omp", "13.3"), ("dir:kernels loop", "acc", "2.5.3"),
                            ("clause:copyin", "acc", "2.7.8")):
        cs = FC.cites(key, model)
        assert cs and cs[0]["section"] == sec, (key, cs)
        assert all(check_citation(c) == [] for c in cs), cs


def test_a_combined_construct_is_cited_by_each_construct_it_combines():
    secs = [c["section"] for c in FC.cites("dir:target teams", "omp")]
    assert secs == ["13.8", "10.2"]


def test_every_key_construct_of_the_catalog_vocabulary_is_cited_or_named_uncited():
    from offload.engine.dataenv_rules import check_citation
    keys = ["dir:declare target", "clause:defaultmap", "clause:reduction", "dir:distribute", "clause:if",
            "dir:parallel", "dir:target exit data", "dir:target teams", "dir:loop", "clause:device",
            "clause:collapse", "dir:do", "dir:simd", "clause:task_reduction", "clause:in_reduction",
            "dir:taskgroup", "clause:lastprivate", "dir:parallel do", "clause:num_threads", "dir:masked",
            "dir:teams distribute parallel do", "clause:simdlen", "clause:bind", "clause:dist_schedule",
            "clause:nowait", "clause:depend", "dir:taskwait", "dir:target data", "clause:schedule"]
    for k in keys:
        cs = FC.cites(k, "omp")
        assert cs, k
        assert all(check_citation(c) == [] for c in cs), (k, cs)


def test_a_sentence_that_only_classifies_its_subject_is_passed_over():
    from offload.engine.dataenv_rules import check_citation
    for key in ("dir:declare target", "clause:reduction"):
        c = FC.cite(key, "omp")
        assert not FC.CLASSIFIES.match(c["quote"]), c["quote"]
        assert check_citation(c) == [], c
