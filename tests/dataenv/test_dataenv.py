"""Tests of the data-environment rule table (catalog/dataenv_rules.yaml) the data-environment campaign reads."""
from __future__ import annotations

import pytest

from offload.engine import dataenv_rules as R


# ---- The data-environment rule table (catalog/dataenv_rules.yaml) -------------------------------------

import re



RULES_2 = R.load()
FIELDS = ("id", "model", "versions", "languages", "spec", "subject",
          "construct", "variable_kind", "attribute", "clauses_present",
          "memory_mode", "expected", "observable", "template")


def test_rows_have_the_fields_and_vocabularies():
    ids = [r["id"] for r in RULES_2]
    assert len(ids) == len(set(ids))
    for r in RULES_2:
        assert set(FIELDS) <= set(r), (r["id"], set(FIELDS) - set(r))
        assert r["model"] in R.MODELS
        assert r["id"].startswith(r["model"] + "-")
        assert r["versions"] and set(r["versions"]) <= \
            set(R.VERSIONS[r["model"]]), r["id"]
        assert set(r["languages"]) <= {"f90", "c"} and r["languages"]
        assert r["construct"] in R.AXES["construct"], r["id"]
        assert r["variable_kind"] in R.AXES["variable_kind"], r["id"]
        assert r["attribute"] and set(r["attribute"]) <= \
            set(R.AXES["attribute"]), r["id"]
        assert r["memory_mode"] in R.AXES["memory_mode"], r["id"]
        assert isinstance(r["clauses_present"], list)
        e = r["expected"]
        assert e["dsa"] in R.DSA and e["map_type"] in R.MAP_TYPE, r["id"]
        assert e["copy_back"] in R.COPY_BACK, r["id"]
        assert e["source"] in R.SOURCE, r["id"]
        for mode, res in e.get("residency", {}).items():
            assert mode in R.MEMORY_MODES and res in R.RESIDENCY, r["id"]
        assert r["subject"].strip() and r["observable"].strip()


def test_every_version_of_a_rule_has_a_citation():
    for r in RULES_2:
        cited = {c["version"] for c in r["spec"]}
        want = {R.CITE_NAMES[v] for v in r["versions"]}
        assert cited == want, (r["id"], cited ^ want)


@pytest.mark.needs_spec
def test_every_rule_cites_spec_text():
    """Every citation: the quote is in the cited lines of the cited
    printed page, and those lines are in the cited section."""
    bad = []
    for r in RULES_2:
        for c in r["spec"]:
            for p in R.check_citation(c):
                bad.append(f"{r['id']}: {c['version']} §{c['section']} "
                           f"p.{c['page']} l.{c['lines']}: {p}")
    assert not bad, "\n".join(bad)


@pytest.mark.needs_spec
def test_page_is_the_footer_page():
    """The TARGET-scalar sentence of OpenMP 5.2 is on printed p.149 (the
    footer under it), the page after the section heading (p.148): a
    citation one page low is refused."""
    q = "If a scalar variable has the TARGET, ALLOCATABLE or POINTER"
    good = {"version": "OpenMP 5.2", "section": "5.8.1", "page": 149,
            "lines": "6-7", "quote": q}
    assert R.check_citation(good) == []
    assert R.check_citation(dict(good, page=148))
    assert R.check_citation(dict(good, section="5.8.3"))
    assert R.check_citation(dict(good, lines="8-9"))
    acc = {"version": "OpenACC 3.4", "section": "2.6.2", "page": 41,
           "lines": "1394", "quote": "In a firstprivate clause otherwise"}
    assert R.check_citation(acc) == []
    assert R.check_citation(dict(acc, page=40))


@pytest.mark.needs_spec
def test_locate_finds_one_place():
    hits = R.locate("OpenMP 5.2", "If a variable is not a scalar then it "
                    "is treated as if it had appeared in a map clause")
    assert [(h["section"], h["page"], h["lines"]) for h in hits] == \
        [("5.8.1", 149, "4")]


def _strings(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from _strings(v)
    else:
        yield str(x)


def test_no_rule_cites_a_compiler():
    """The table states the spec's rule: no compiler, toolchain, measured
    outcome or finding is named anywhere in a row."""
    bad = [(r["id"], s) for r in RULES_2 for s in _strings(r)
           if R.COMPILER_WORDS.search(s)]
    assert not bad, bad
    # the words are found where they occur
    assert R.COMPILER_WORDS.search("passes on CCE 21")
    assert R.COMPILER_WORDS.search("an NVHPC wrong answer")


def test_lookup_takes_the_most_specific_rule():
    def first(*a, **k):
        return R.lookup(RULES_2, *a, **k)[0]["id"]
    assert first("omp", "5.2", "target", "scalar") == \
        "omp-target-scalar-firstprivate"
    assert first("omp", "5.2", "target", "scalar", ["target"]) == \
        "omp-target-scalar-target-attr"
    assert first("omp", "6.0", "target", "scalar", [],
                 ["defaultmap( tofrom : scalar )"]) == \
        "omp-defaultmap-tofrom-scalar"
    assert first("omp", "5.0", "target", "array") == "omp-target-array-tofrom"
    assert first("acc", "3.4", "kernels", "scalar") == \
        "acc-kernels-scalar-copy"
    assert first("acc", "3.4", "parallel", "scalar", [],
                 ["default(present)"]) == \
        "acc-default-present-scalar-firstprivate"
    # memory mode: a copy-mode rule is not offered for unified memory
    ids = [r["id"] for r in R.lookup(RULES_2, "omp", "5.2", "target", "array",
                                     ["enclosing_data"], [], "unified")]
    assert "omp-target-data-nested-no-transfer" not in ids
    # the present modifier (5.1) is no 5.0 rule
    assert all(r["id"] != "omp-present-modifier" for r in R.lookup(
        RULES_2, "omp", "5.0", "target", "array", ["enclosing_data"],
        ["map(present, tofrom)"]))


def test_the_brief_topics_are_covered():
    """Item 1 of the brief: every topic has at least one row."""
    def has(pred):
        return any(pred(r) for r in RULES_2)
    kinds = {r["variable_kind"] for r in RULES_2 if r["model"] == "omp"}
    assert {"scalar", "array", "derived_type", "c_pointer"} <= kinds
    attrs = {a for r in RULES_2 for a in r["attribute"]}
    for a in ("target", "declare_target", "module", "common", "allocatable",
              "pointer", "component", "value_argument", "declare_create",
              "declare_copyin"):
        assert a in attrs, a
    cl = " ".join(c for r in RULES_2 for c in r["clauses_present"])
    for w in ("defaultmap(tofrom: scalar)", "defaultmap(firstprivate: aggregate)",
              "defaultmap(firstprivate: allocatable)", "lastprivate",
              "firstprivate", "map(always, to)", "map(present, tofrom)",
              "map(close, tofrom)", "default(present)", "finalize",
              "requires unified_shared_memory"):
        assert w in cl, w
    assert has(lambda r: r["construct"] in ("target enter data",
                                            "target exit data"))
    assert has(lambda r: r["construct"] == "target data")
    assert has(lambda r: r["construct"] == "routine")
    assert has(lambda r: "infinity" in " ".join(c["quote"]
                                               for c in r["spec"]))
    assert has(lambda r: r["memory_mode"] == "copy")
    assert has(lambda r: r["memory_mode"] == "unified")
    for v in ("5.0", "5.2", "6.0", "3.4"):
        assert sum(v in r["versions"] for r in RULES_2) >= 15, v


def test_citations_for_names_the_rule():
    r = next(x for x in RULES_2 if x["id"] == "omp-target-scalar-target-attr")
    cites = R.citations_for(r)
    assert any(re.match(r'OpenMP 5\.2 §5\.8\.1 p\.149 l\.6-7: "', c)
               for c in cites), cites
