"""Programs from the data-environment rule table
(offload.engine.dataenv_gen)."""
import copy
import re
from pathlib import Path

import pytest

from offload.engine import dataenv_gen as G
from offload.engine import dataenv_rules as R
from offload.engine import prerun

RULES = R.load()
BY_ID = {r["id"]: r for r in RULES}
HAVE_AFAR = Path(__import__("offload.engine.toolchains", fromlist=["x"])
                 .AFAR_BIN, "amdflang").exists()


def test_every_rule_has_a_generator():
    """Every row names a template that makes, per language of the row, a
    rule form and a control with the same expected values
    (the table and its consumers cannot drift apart)."""
    ids = set()
    for r in RULES:
        assert r["template"] in G.TEMPLATES, r["id"]
        progs = G.programs(r)
        assert len(progs) == 2 * len(r["languages"]), r["id"]
        for lang in r["languages"]:
            rule, ctl = [p for p in progs if p.lang == lang]
            assert (rule.form, ctl.form) == ("rule", "control")
            assert rule.expected and rule.expected == ctl.expected, r["id"]
            assert rule.source != ctl.source, r["id"]
            assert r["id"] in rule.source and r["id"] in ctl.source
            assert rule.rule == r["id"]
        ids |= {p.id for p in progs}
    assert len(ids) == sum(2 * len(r["languages"]) for r in RULES)


def test_every_program_prints_its_observables_and_the_result_line():
    for r in RULES:
        for p in G.programs(r):
            for name in p.expected:
                assert f"{name}= " in p.source, (p.id, name)
            assert "RESULT ran_on_host=" in p.source
            assert ("omp_is_initial_device" in p.source) == \
                (p.model == "omp")


def test_expected_values_come_from_the_rule():
    """Changing the row's copy_back changes the expected value: the value
    is the rule's, not a compiler's."""
    r = copy.deepcopy(BY_ID["omp-target-scalar-firstprivate"])
    assert G.program(r, "f90", "rule").expected == {"rd": 101, "v": 101}
    r["expected"]["copy_back"] = "yes"
    assert G.program(r, "f90", "rule").expected == {"rd": 101, "v": 203}
    a = copy.deepcopy(BY_ID["omp-target-array-tofrom"])
    sums = G.program(a, "c", "rule").expected
    assert sums == {"a_bad": 0, "a_sum": sum(2 * i + 1 for i in
                                             range(1, G.N + 1))}
    lp = G.program(BY_ID["omp-combined-lastprivate-ttdpds-collapse"], "c",
                   "rule")
    assert lp.expected == {"lp": 128}


def test_control_states_the_attribute():
    def target_line(p, word):
        return [ln for ln in p.source.splitlines() if word in ln and
                "host_flag" not in ln and "update" not in ln]
    p = G.program(BY_ID["omp-target-scalar-firstprivate"], "f90", "control")
    assert any("firstprivate(v)" in ln for ln in target_line(p, "$omp target"))
    p = G.program(BY_ID["omp-target-scalar-target-attr"], "f90", "control")
    assert any("map(tofrom: v)" in ln for ln in target_line(p, "$omp target"))
    p = G.program(BY_ID["omp-defaultmap-tofrom-scalar"], "c", "control")
    assert not any("defaultmap" in ln for ln in p.source.splitlines()
                   if ln.startswith("  #pragma"))
    p = G.program(BY_ID["acc-declare-create-scalar-serial"], "f90", "control")
    assert any("present(g)" in ln for ln in target_line(p, "$acc serial"))
    p = G.program(BY_ID["omp-combined-lastprivate-tpd"], "c", "control")
    assert any("map(tofrom: lp)" in ln for ln in p.source.splitlines())


def test_rule_form_has_only_the_rows_clauses():
    p = G.program(BY_ID["omp-target-scalar-target-attr"], "f90", "rule")
    region = [ln.strip() for ln in p.source.splitlines()
              if ln.strip().startswith("!$omp target") and "host_flag" not
              in ln]
    assert region == ["!$omp target map(from: rd)"]
    p = G.program(BY_ID["acc-component-aggregate-copy"], "f90", "rule")
    assert "!$acc serial copyout(rd)" in p.source


def test_modes_and_harness_program():
    copy_only = G.program(BY_ID["omp-target-data-nested-no-transfer"],
                          "f90", "rule")
    assert copy_only.modes == ("copy",)
    hp = copy_only.harness()
    assert hp.id.startswith("omp52-de_") and hp.evidence == "copy_mode_only"
    usm = G.program(BY_ID["omp-usm-map-optional"], "c", "rule")
    assert usm.modes == ("unified",) and usm.harness().needs == ("zero_copy",)
    assert "#pragma omp requires unified_shared_memory" in usm.source
    acc = G.program(BY_ID["acc-reduction-copy"], "f90", "rule").harness()
    assert acc.id.startswith("acc34-de_") and acc.model == "acc"
    anym = G.program(BY_ID["omp-target-array-tofrom"], "f90", "rule")
    assert anym.modes == ("copy", "unified")


def test_ids_have_one_dash():
    """Build paths take the program id: one '-' (after the version
    prefix the harness reads), none in what the generator adds."""
    for r in RULES:
        for p in G.programs(r):
            assert re.fullmatch(r"(omp50|omp52|omp60|acc34)-de_\w+",
                                p.id), p.id


def test_oracle_mutant_flips_the_attribute():
    m = G.oracle_mutant(BY_ID["omp-target-scalar-firstprivate"], "f90")
    assert "map(tofrom: v)" in m.source and m.form == "opposite"
    assert m.expected == {"rd": 101, "v": 101}
    m = G.oracle_mutant(BY_ID["omp-target-scalar-target-attr"], "f90")
    assert "firstprivate(v)" in m.source
    m = G.oracle_mutant(BY_ID["acc-copyin-no-copyback"], "c")
    loop = [ln for ln in m.source.splitlines()
            if ln.strip().startswith("#pragma acc parallel loop")]
    assert loop == ["  #pragma acc parallel loop copy(a) copyout(b)"], loop
    assert G.oracle_mutant(BY_ID["acc-kernels-scalar-copy"], "f90") is None
    assert G.oracle_mutant(BY_ID["omp-always-to"], "f90") is None


def test_parse_observed():
    out = "rd= 101\nv= -3\nRESULT ran_on_host=0 check=pass\n"
    assert G.parse_observed(out) == {"rd": 101, "v": -3}


def test_rules_witness_accepts_every_program():
    """The first of the pre-run check's two witnesses (offload.engine.rules,
    the restriction checks, the race rule) accepts every generated program
    and oracle mutant."""
    bad = []
    for r in RULES:
        progs = G.programs(r) + [m for m in (G.oracle_mutant(r, lg) for lg
                                             in r["languages"]) if m]
        for p in progs:
            ok, why = prerun.rules_witness(p)
            if not ok:
                bad.append((p.id, why[:2]))
    assert not bad, bad


def test_racy_variant_is_refused():
    """The race rule sees the shared scalar a generated program would race
    on without its lastprivate clause."""
    p = G.program(BY_ID["omp-combined-lastprivate-ttdpd"], "f90", "rule")
    racy = p.source.replace(" lastprivate(lp)", "")
    ok, why = prerun.rules_witness((racy, "f90", "omp", 52))
    assert not ok and any("race" in w for w in why), why


@pytest.mark.skipif(not HAVE_AFAR, reason="the front-end witness needs AFAR")
def test_prerun_check_accepts_a_sample():
    """Both witnesses (a Tuolumne compute node): one program per template
    and language."""
    seen, bad = set(), []
    for r in RULES:
        for p in G.programs(r):
            key = (r["template"], p.lang, p.model)
            if key in seen or p.form != "rule":
                continue
            seen.add(key)
            res = G.prerun_check(p)
            if not res["ok"]:
                bad.append((p.id, res["reasons"][:3]))
    assert not bad, bad


def _tool():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "dataenv_tool", Path(__file__).resolve().parent.parent.parent / "tools" /
        "dataenv" /
        "dataenv.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_runner_cells_follow_model_language_and_mode():
    """tools/dataenv/dataenv.py runs a program only on a toolchain of its model and
    language, in a memory mode its expected value holds in: no OpenACC on
    AFAR, no OpenACC C on CCE, copy-only programs at row key 0 only,
    unified-only ones at 1 (AMD) or 2 (NVHPC managed) only."""
    D = _tool()
    progs = [G.program(BY_ID[r], lang, "rule") for r, lang in (
        ("acc-reduction-copy", "f90"), ("acc-reduction-copy", "c"),
        ("omp-target-data-nested-no-transfer", "c"),
        ("omp-usm-map-optional", "f90"), ("omp-target-array-tofrom", "f90"))]
    ok = {p.id for p in progs}
    cells = {(p.rule, p.lang, t, x) for p, t, x in D._cells(
        progs, ["afar", "cce19", "nvhpc"], [0, 1, 2], ok)}
    assert ("acc-reduction-copy", "f90", "afar", 0) not in cells
    assert ("acc-reduction-copy", "f90", "cce19", 0) in cells
    assert ("acc-reduction-copy", "c", "cce19", 0) not in cells
    assert ("acc-reduction-copy", "c", "nvhpc", 0) in cells
    nested = {(t, x) for r, _, t, x in cells
              if r == "omp-target-data-nested-no-transfer"}
    assert nested == {("afar", 0), ("cce19", 0), ("nvhpc", 0)}
    usm = {(t, x) for r, _, t, x in cells if r == "omp-usm-map-optional"}
    assert usm == {("afar", 1), ("cce19", 1), ("nvhpc", 2)}
    anym = {(t, x) for r, _, t, x in cells if r == "omp-target-array-tofrom"}
    assert anym == {("afar", 0), ("afar", 1), ("cce19", 0), ("cce19", 1),
                    ("nvhpc", 0), ("nvhpc", 2)}
    # a program without a passing pre-run check is never run
    assert not D._cells(progs, ["afar"], [0, 1], set())


def test_gate_counts_only_a_rows_own_confirmed_check_fail(tmp_path,
                                                         monkeypatch):
    """The trial's gate path (tools/dataenv/dataenv.py): failing rows become
    kind "dataenv" items, the plan reruns every one, and a wrong-answer
    signature (rule, family) counts only for a check_fail row whose own
    verdict is confirmed."""
    import json
    D = _tool()
    monkeypatch.setattr(D, "OUT", tmp_path)
    d = tmp_path / "t"
    d.mkdir()
    rule = "omp-target-scalar-target-attr"
    p = G.program(BY_ID[rule], "f90", "rule")
    base = {"program_id": p.id, "rule": rule, "form": "rule", "lang": "f90",
            "toolchain": "afar", "mode": "copy", "flaky": False,
            "stdout": "rd= 101\nv= 101\nRESULT ran_on_host=0 check=fail",
            "build_dir": "/tmp/x_harness_1", "node": "n1", "task_s": 36.0}
    rows = [dict(base, xnack=0, outcome="wrong_answer",
                 reason="check_fail: ran_on_host=0 check=fail"),
            dict(base, xnack=1, outcome="wrong_answer",
                 reason="crash: SIGSEGV; without mandatory: crash: SIGSEGV"),
            dict(base, toolchain="cce19", xnack=0,
                 outcome="correct_on_device", reason="")]
    (d / "rows.jsonl").write_text("".join(json.dumps(r) + "\n"
                                          for r in rows))
    items = D.gate_items("t")
    assert [it["kind"] for it in items] == ["dataenv", "dataenv"]
    plan = D.gate_plan(items)
    assert {r["sample"] for r in plan["rows"]} == {"all"}
    reruns = []
    for it in items:
        for env, node in (("a", "n1"), ("b", "n1"), ("c", "n2"),
                          ("d", "n1")):
            reruns.append({"cell": it["cell"], "env": env, "node": node,
                           "path": "/tmp/x_harness_1" if env != "b"
                           else "/tmp/GATEX", "outcome": it["outcome"],
                           "reason": it["reason"], "flaky": False,
                           "stdout": it["stdout"]})
    (d / "gate_reruns.jsonl").write_text("".join(json.dumps(r) + "\n"
                                                 for r in reruns))
    v = D.verdicts("t")
    assert all(x["verdict"] == "confirmed" and x["own"] for x in v.values())
    monkeypatch.setattr(D, "pilot", lambda: {rule: "near"})
    s = D.summary("t")
    assert s["signatures"] == {"near": [(rule, "afar")]}
    assert abs(s["hours"]["near"] - 3 * 36 / 3600) < 1e-9


def test_defaultmap_rule_form_observes_the_array_it_decides():
    """Under defaultmap(firstprivate: aggregate) the copy-in is
    read through a scalar sum, not a second mapped array, so a compiler
    that lets defaultmap override an explicit map of another array cannot
    fail the program; the array the rule decides is checked on the host."""
    for rid in ("omp-defaultmap-firstprivate-aggregate",
                "omp-defaultmap-firstprivate-all",
                "omp-defaultmap-firstprivate-allocatable"):
        for lang in BY_ID[rid]["languages"]:
            p = G.program(BY_ID[rid], lang, "rule")
            assert "map(from: b)" not in p.source, (rid, lang)
            assert "map(tofrom: rs)" in p.source
            assert p.expected == {"rs": 2080, "a_bad": 0, "a_sum": 2080}
    # without defaultmap the copy-in channel is still the mapped b
    p = G.program(BY_ID["acc-copyin-no-copyback"], "f90", "rule")
    assert "copyout(b)" in p.source


def test_gate_keys_a_wrong_answer_by_its_printed_values(tmp_path,
                                                        monkeypatch):
    """A failing row's whole output goes to the gate, which keys
    a dataenv wrong answer by the values it printed; reruns that print
    other values make it nondeterministic."""
    import json
    D = _tool()
    monkeypatch.setattr(D, "OUT", tmp_path)
    d = tmp_path / "t"
    d.mkdir()
    rule = "omp-combined-lastprivate-ttdpd"
    p = G.program(BY_ID[rule], "c", "control")
    out = "lp= {}\nRESULT ran_on_host=0 check=fail\n"
    row = {"program_id": p.id, "rule": rule, "form": "control", "lang": "c",
           "toolchain": "afar", "mode": "copy", "xnack": 0, "flaky": False,
           "outcome": "wrong_answer",
           "reason": "check_fail: ran_on_host=0 check=fail",
           "stdout": out.format(104571), "build_dir": "/tmp/x_harness_2",
           "node": "n1", "task_s": 30.0}
    (d / "rows.jsonl").write_text(json.dumps(row) + "\n")
    it = D.gate_items("t")[0]
    assert "lp= 104571" in it["stdout"]
    reruns = [{"cell": it["cell"], "env": e, "node": nd,
               "path": "/tmp/GATEX" if e == "b" else "/tmp/x_harness_2",
               "outcome": "wrong_answer", "reason": row["reason"],
               "flaky": False, "stdout": out.format(v)}
              for e, nd, v in (("a", "n1", 82972), ("b", "n1", 0),
                               ("c", "n2", 17038), ("d", "n1", 151912))]
    (d / "gate_reruns.jsonl").write_text("".join(json.dumps(r) + "\n"
                                                 for r in reruns))
    assert D.verdicts("t")[it["cell"]]["verdict"] == "nondeterministic"


def test_every_construct_of_the_table_has_rows_of_its_own():
    """The combined constructs it meets have rows of their own,
    so it never falls back to the nearest construct."""
    for c in ("target teams loop", "target parallel loop", "target simd",
              "target teams distribute simd", "target parallel",
              "target teams"):
        kinds = {(r["variable_kind"], tuple(r["clauses_present"]))
                 for r in RULES if r["construct"] == c}
        assert ("scalar", ()) in kinds and ("array", ()) in kinds, c
        assert ("scalar", ("reduction",)) in kinds, c


def test_no_row_names_a_program_variable():
    """Clause words are generic (map(to), lastprivate): no row carries a
    variable name of a generated program (the 40d matcher reads them)."""
    for r in RULES:
        for c in r["clauses_present"]:
            assert not re.search(r"\(\s*[\w%.]+\s*:\s*[A-Za-z_]", c) or \
                c.startswith("defaultmap"), (r["id"], c)
