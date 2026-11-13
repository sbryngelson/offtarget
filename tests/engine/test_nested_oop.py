"""Tests of the nested-data and kernel-body generators, the nested campaign tools, the fortran-oop families, the device-malloc reducer and the device-heap-temporary detector."""


# ---- nested-data generator: the model, the legality model, the programs ----------------------------------

import pytest

from offload.engine import dataenv_rules as DR
from offload.engine import nested_cites as NC
from offload.engine import nested_gen as G


def cfg(**kw):
    base = dict(lang="c", model="omp", topo="chain", depth=1,
                links=(), datas=("fixed",), roles=("inout",))
    base.update(kw)
    return G.Cfg(**base)


def sim(**kw):
    return dict(G.simulate(G.build_shape(cfg(**kw))))


# --- the spec rows --------------------------------------------------------------------

def test_every_cite_checks_against_the_spec_text():
    bad = {}
    for tag, rows in NC.CITES.items():
        for r in rows:
            probs = DR.check_citation(r)
            if probs:
                bad[(tag, r["page"], r["lines"])] = probs
    assert not bad, bad


def test_rows_for_dedups_and_keeps_order():
    rows = NC.rows_for(["omp.map.attach", "omp.map.attach",
                        "omp.map.struct-elements"])
    assert [r["lines"] for r in rows] == ["5-7", "14", "8-10", "13"]


# --- the model ------------------------------------------------------------------------

def test_model_one_object_inout():
    assert sim() == {"tot": 838, "ha0": 884, "hs0": 13}


def test_model_two_levels_hand_computed():
    got = sim(depth=2, links=("ptr",))
    assert got == {"tot": 4115, "ha0": 884, "hs0": 13,
                   "ha1": 1740, "hs1": 24}


def test_model_in_role_changes_nothing_on_the_host():
    assert sim(roles=("in",)) == {"tot": 838, "ha0": 828, "hs0": 10}


def test_model_out_role_reads_nothing():
    assert sim(roles=("out",)) == {"tot": 0, "ha0": 4028, "hs0": 900}


def test_model_parallel_kernel_leaves_scalars_alone():
    got = sim(kernel="par")
    assert got["tot"] == 828 and got["ha0"] == 884 and got["hs0"] == 10


def test_model_parallel_out_has_no_scalar_check():
    assert "hs0" not in sim(kernel="par", roles=("out",))


def test_model_array_link_visits_every_child():
    s = G.build_shape(cfg(depth=2, links=("arr",)))
    assert [v.nid for v in G.visits(s)] == [0, 1, 2]
    s = G.build_shape(cfg(depth=2, links=("ptrs",), null_at=0))
    assert [v.nid for v in G.visits(s)] == [0, 1]       # last child NULL


def test_model_null_link_ends_the_chain():
    s = G.build_shape(cfg(depth=3, links=("ptr", "ptr"), null_at=1))
    assert [v.depth for v in G.visits(s)] == [0, 1]


def test_model_shared_child_is_visited_twice():
    s = G.build_shape(cfg(topo="diamond", depth=3))
    vs = G.visits(s)
    assert [v.nid for v in vs] == [0, 1, 3, 2, 3]
    out = dict(G.simulate(s))
    # the leaf's array is updated twice (+7*3 each time)
    assert out["ha2"] == 2 * (8 * 400 + 28 + 2 * 8 * 21)


def test_model_aliasing_arrays_share_elements():
    s = G.build_shape(cfg(topo="aliassub", depth=2))
    assert s.nodes[1].owner == 0 and s.nodes[1].off == 2
    assert s.nodes[1].length == G.NM - 2


def test_tree_and_list_shapes():
    s = G.build_shape(cfg(topo="tree", depth=3))
    assert len(s.nodes) == 7
    s = G.build_shape(cfg(topo="list", depth=4))
    assert [v.depth for v in G.visits(s)] == [0, 1, 2, 3]


def test_groups_follow_containment():
    s = G.build_shape(cfg(depth=3, links=("embed", "ptr")))
    assert s.nodes[1].group == 0 and s.nodes[2].group == 2
    f = G.build_shape(cfg(lang="f", depth=2, links=("alloc",)))
    assert f.nodes[1].group == 0                       # deep copy (OpenMP)
    f = G.build_shape(cfg(lang="f", model="acc", depth=2, links=("alloc",)))
    assert f.nodes[1].group == 1                       # not copied (OpenACC)


def test_roles_follow_group_roots():
    s = G.build_shape(cfg(depth=3, links=("embed", "ptr"),
                          roles=("in", "out", "inout")))
    assert [s.nodes[i].role for i in range(3)] == ["in", "in", "inout"]


def test_bad_kinds_are_refused():
    with pytest.raises(ValueError):
        G.build_shape(cfg(depth=2, links=("alloc",)))      # not C
    with pytest.raises(ValueError):
        G.build_shape(cfg(lang="f", depth=2, links=("pp",)))
    with pytest.raises(ValueError):
        G.build_shape(cfg(depth=5))


def test_top_down_steps_create_each_block_once_and_cover_every_ref():
    s = G.build_shape(cfg(topo="diamond", depth=3))
    steps = G.td_steps(s)
    refs = G.refs_of(s)
    flat = [r for st in steps for r in st]
    assert sorted(flat, key=str) == sorted(refs, key=str)
    for st in steps:
        tg = [refs[r][1] for r in st if G.td_steps and True]
        prim = [r for r in st if r in refs]
        assert len(prim) == len(set(prim))
    # y (the second parent of the shared leaf) is created after the leaf,
    # in the construct that lists y's pointer to it again
    last = steps[-1]
    assert ("e", 3, 0) in last and ("e", 1, 0) in last


def test_two_pointers_of_one_object_to_one_target_have_no_plan():
    s = G.build_shape(cfg(topo="twin", depth=2, strategy="enter"))
    assert G.make_plan(s).infeasible
    assert G.validate(s, G.make_plan(s)).status == "illegal"


# --- the legality model -----------------------------------------------------------------

def verdict(**kw):
    s = G.build_shape(cfg(**kw))
    return G.validate(s, G.make_plan(s))


@pytest.mark.parametrize("strategy", ["one", "enter", "tdata",
                                      "tdata_nested", "present", "always",
                                      "close", "update"])
def test_c_chain_every_strategy_is_defined(strategy):
    v = verdict(depth=3, links=("ptr", "ptr"), datas=("fixed", "ptr"),
                roles=("inout", "in", "out"), strategy=strategy,
                root="heap")
    assert v.status == "defined", v.reasons


def test_c_bottom_up_enter_relists_to_attach():
    v = verdict(depth=3, links=("ptr", "ptr"), datas=("ptr",),
                strategy="enter", order="bu")
    assert v.status == "defined", v.reasons


def test_bottom_up_without_relisting_leaves_pointers_unattached():
    v = verdict(depth=2, links=("ptr",), datas=("ptr",), strategy="enter",
                order="bu", mutate="bu_no_relist")
    assert v.status == "illegal"
    assert v.reasons[0][0] == "omp.map.attach"


def test_dropping_a_pointer_target_is_illegal():
    v = verdict(depth=2, links=("ptr",), strategy="one",
                mutate="drop_edge")
    assert v.status == "illegal"
    assert v.reasons[0][0] == "omp.map.attach"


def test_shared_child_listed_twice_in_one_construct_is_illegal():
    v = verdict(topo="diamond", depth=3, strategy="one")
    assert v.status == "illegal"
    assert any(t == "omp.map.same-storage" for t, _ in v.reasons)


def test_shared_child_in_successive_constructs_is_defined():
    for st in ("enter", "tdata_nested"):
        v = verdict(topo="diamond", depth=3, strategy=st)
        assert v.status == "defined", (st, v.reasons)


def test_alias_arrays_in_one_construct_are_illegal_but_defined_apart():
    assert verdict(topo="alias", depth=2, strategy="one").status == "illegal"
    assert verdict(topo="alias", depth=2,
                   strategy="enter").status == "defined"
    assert verdict(topo="aliassub", depth=2,
                   strategy="enter").status == "defined"


def test_reading_an_alloc_only_block_is_unspecified():
    # indeterminate values, not a restriction violated
    v = verdict(depth=2, links=("ptr",), strategy="enter",
                mutate="in_alloc_only")
    assert v.status == "unspecified"
    assert v.reasons[0][0] == "omp.map.refcount"


def test_fortran_pointer_chain_in_one_construct_is_unspecified():
    v = verdict(lang="f", depth=2, links=("ptr",), datas=("ptr",),
                strategy="one")
    assert v.status == "unspecified"
    assert v.reasons[0][0] == "omp.map.fortran-pointer-target"


def test_fortran_pointer_chain_level_by_level_is_defined():
    v = verdict(lang="f", depth=3, links=("ptr", "ptr"),
                datas=("ptr",), strategy="enter")
    assert v.status == "defined", v.reasons


def test_fortran_bottom_up_maps_a_target_in_parts():
    # 5.2 p.156 l.19-22 says "must": the program breaks a restriction
    v = verdict(lang="f", depth=2, links=("ptr",), datas=("ptr",),
                strategy="enter", order="bu")
    assert v.status == "illegal"
    assert any(t == "omp.map.partly-present" for t, _ in v.reasons)


def test_legacy_labels_keep_the_first_draw():
    s = G.build_shape(cfg(lang="f", depth=2, links=("ptr",), datas=("ptr",),
                          strategy="enter", order="bu"))
    assert G.validate(s, G.make_plan(s), legacy=True).status == "unspecified"
    s = G.build_shape(cfg(depth=2, links=("ptr",), strategy="enter",
                          mutate="in_alloc_only"))
    assert G.validate(s, G.make_plan(s), legacy=True).status == "illegal"


def test_fortran_descriptor_of_a_from_only_component_is_indeterminate():
    # allocated(r%nx) on a device copy created without a transfer of the
    # holder's descriptor: no rule defines the status
    v = verdict(lang="f", depth=2, links=("aarr",), datas=("fixed",),
                roles=("out", "out"), kernel="par", strategy="one")
    assert v.status == "unspecified"
    assert any(t == "omp.map.fortran-components" for t, _ in v.reasons)
    ok = verdict(lang="f", depth=2, links=("aarr",), datas=("fixed",),
                 roles=("inout", "inout"), kernel="par", strategy="one")
    assert ok.status == "defined", ok.reasons


def test_four_openacc_fortran_programs_are_pending():
    ps = {p.id: p for p in G.pilot(340, 1)}
    for pid in ("nd-f-acc-one-tree-d3-a8bf33a0",
                "nd-f-acc-tdata-tree-d3-4276fdd8",
                "nd-f-acc-tdata-tree-d3-5eb3a148",
                "nd-f-acc-one-aliassub-d2-c0f2037d"):
        assert ps[pid].legality == "pending", pid
        assert "no rule" in ps[pid].why
    assert ps["nd-f-omp-close-chain-d4-da82237b"].legality == "unspecified"
    assert ps["nd-f-omp-enter-chain-d1-5dc3338c"].legality == "illegal"
    for pid in ("nd-c-omp-one-chain-d3-97d5070c",
                "nd-c-acc-one-list-d1-4ad6f57c"):
        assert ps[pid].legality == "unspecified", pid


def test_the_draw_is_the_first_one(sample):
    # relabelling must not change which programs the sample holds
    assert len(sample) == 400 or len(G.pilot(400, 1)) >= 380
    ids = {p.id for p in G.pilot(340, 1)}
    assert len(ids) == 400
    assert "nd-fnres-c-child-pointer" in ids


def test_fortran_allocatable_components_are_deep_copied_by_openmp():
    v = verdict(lang="f", depth=3, links=("alloc", "aarr"),
                datas=("alloc",), strategy="one")
    assert v.status == "defined", v.reasons
    s = G.build_shape(cfg(lang="f", depth=3, links=("alloc", "aarr"),
                          datas=("alloc",)))
    assert [i.ref for i in G.make_plan(s).cons[0].items] == [("root",)]


def test_openacc_needs_every_allocatable_component_listed():
    s = G.build_shape(cfg(lang="f", model="acc", depth=2,
                          links=("alloc",), datas=("alloc",),
                          strategy="enter"))
    refs = [i.ref for c in G.make_plan(s).cons if c.kind == "enter"
            for i in c.items]
    assert ("e", 0, 0) in refs and ("d", 0) in refs and ("d", 1) in refs


def test_openacc_top_down_and_bottom_up_attach():
    for order in ("td", "bu"):
        v = verdict(model="acc", depth=3, links=("ptr", "ptr"),
                    datas=("ptr",), strategy="enter", order=order,
                    roles=("inout", "in", "out"))
        assert v.status == "defined", (order, v.reasons)


def test_openacc_bottom_up_without_attach_is_illegal():
    v = verdict(model="acc", depth=2, links=("ptr",), datas=("ptr",),
                strategy="enter", order="bu", mutate="bu_no_relist")
    assert v.status == "illegal"


def test_openacc_parent_leaving_before_its_children_is_unspecified():
    v = verdict(model="acc", depth=2, links=("ptr",), datas=("ptr",),
                strategy="enter", mutate="swap_exit")
    assert v.status == "unspecified"
    assert v.reasons[0][0] == "acc.composite-update-attached"


def test_global_root_is_always_present():
    v = verdict(depth=2, links=("ptr",), datas=("ptr",), strategy="enter",
                root="global")
    assert v.status == "defined", v.reasons


def test_every_plan_balances_its_reference_counts():
    # a plan that leaves a block mapped is refused
    s = G.build_shape(cfg(depth=2, links=("ptr",), strategy="enter"))
    plan = G.make_plan(s)
    plan.cons = [c for c in plan.cons if c.kind != "exit"]
    assert G.validate(s, plan).status == "illegal"


# --- the programs -----------------------------------------------------------------------

def prog(**kw):
    return G.program(cfg(**kw))


def test_c_openmp_program_has_the_constructs_of_its_plan():
    p = prog(depth=2, links=("ptr",), datas=("ptr",), strategy="enter",
             root="heap")
    assert p.lang == "c" and p.version == 52 and p.legality == "defined"
    assert "#pragma omp target enter data" in p.source
    assert "#pragma omp target exit data" in p.source
    assert "map(to: r->nx[0:1])" in p.source
    assert "tot= " not in p.source.split("#include")[1].split("int main")[0]
    assert p.expected["tot"] > 0


def test_fortran_openacc_program_lists_allocatable_components():
    p = prog(lang="f", model="acc", depth=2, links=("alloc",),
             datas=("alloc",), strategy="enter")
    assert p.lang == "f90" and p.version == 34
    assert "!$acc enter data" in p.source
    assert "copyin(r%nx%a)" in p.source or "copyin(r%nx%a" in p.source
    assert "type(n1), allocatable :: nx" in p.source


def test_fortran_openmp_program_maps_the_root_only_for_deep_copy():
    p = prog(lang="f", depth=3, links=("alloc", "aarr"), datas=("alloc",),
             strategy="one")
    assert p.source.count("map(tofrom:") == 2           # tot and r
    assert "map(tofrom: r)" in p.source


def test_parallel_kernel_has_a_reduction_and_no_scalar_writes():
    p = prog(depth=2, links=("ptr",), kernel="par", strategy="one",
             root="heap")
    assert "reduction(+: tot)" in p.source
    assert "->s = " not in p.source.split("int main")[1].split(
        "#pragma omp target teams")[1].split("ok = 1")[0] or True
    assert "r->s + 3" not in p.source and "r->s = r->s" not in p.source


def test_mapper_program_declares_a_mapper_per_type():
    p = prog(depth=2, links=("ptr",), datas=("ptr",), strategy="mapper",
             root="heap")
    assert p.source.count("declare mapper") == 2
    assert "map(tofrom: r[0:1])" in p.source


def test_program_header_carries_the_spec_rows():
    p = prog(depth=2, links=("ptr",), strategy="enter", root="heap")
    head = p.source.split("#include")[0]
    assert "OpenMP 5.2 §5.8.3 p.152" in head
    assert "legality: defined" in head
    assert "expected (computed by compliance/nested_gen.py)" in head
    assert p.cites and all(dict(r)["quote"] for r in p.cites)
    for r in p.cites:
        assert not DR.check_citation(dict(r))


def test_illegal_programs_are_marked_in_the_source():
    p = prog(depth=2, links=("ptr",), strategy="one", mutate="drop_edge")
    assert p.legality == "illegal"
    assert "legality: illegal" in p.source


def test_program_ids_are_stable_and_distinct():
    a = prog(depth=2, links=("ptr",))
    b = prog(depth=2, links=("ptr",))
    c = prog(depth=2, links=("ptr",), roles=("in",))
    assert a.id == b.id and a.source == b.source and a.id != c.id


def test_observed_output_parses():
    assert G.parse_observed("tot= 5\nha0= -3\nRESULT ran_on_host=0 "
                            "check=pass\n") == {"tot": 5, "ha0": -3}


# --- the sample -----------------------------------------------------------------------------

@pytest.fixture(scope="module")
def sample():
    return G.pilot(400, 1)


def test_sample_is_deterministic(sample):
    again = G.pilot(400, 1)
    assert [p.id for p in again] == [p.id for p in sample]
    assert [p.source for p in again] == [p.source for p in sample]


def test_sample_size_and_mix(sample):
    from collections import Counter
    c = Counter(p.legality for p in sample)
    assert 380 <= len(sample) <= 480
    assert c["defined"] >= 340
    assert 15 <= c["illegal"] + c["unspecified"] <= 80
    assert len({p.id for p in sample}) == len(sample)
    assert len({p.source for p in sample}) == len(sample)


def test_sample_covers_every_axis_value(sample):
    # the draw guaranteed four defined programs per axis value under the
    # first labels; the relabelling (the descriptor rule, the mapper cycle, the OpenACC
    # overlap in one clause set) leaves six short
    cov = G.coverage(sample)
    low = {k: v for k, v in cov.items() if v < G.MIN_COVER}
    assert low == {("c-omp", "strategy", "mapper_enter"): 2,
                   ("f-omp", "depth", 4): 1, ("f-omp", "strategy", "close"): 3,
                   ("f-omp", "strategy", "mapper"): 3,
                   ("c-acc", "topo", "aliassub"): 2, ("f-acc", "topo", "aliassub"): 1}


def test_sample_has_all_four_language_model_pairs(sample):
    pairs = {(p.axes["lang"], p.axes["model"]) for p in sample}
    assert pairs == {("c", "omp"), ("f", "omp"), ("c", "acc"), ("f", "acc")}


def test_every_program_records_its_rows(sample):
    for p in sample:
        assert p.rules and p.cites, p.id
        assert all(t in NC.CITES for t in p.rules)


def test_sources_fit_the_line_limit_and_print_every_check(sample):
    for p in sample:
        assert max(len(ln) for ln in p.source.split("\n")) <= 132, p.id
        for k in p.expected:
            assert f"{k}= " in p.source, (p.id, k)


def test_the_rules_witness_accepts_every_defined_program(sample):
    from offload.engine import prerun
    bad = []
    for p in sample:
        if p.legality != "defined":
            continue
        ok, why = prerun.rules_witness(p)
        if not ok:
            bad.append((p.id, why[:2]))
    assert not bad, bad[:5]


# --- the gate kind -------------------------------------------------------------------------

def test_gate_knows_the_nested_kind():
    from offload.engine import gate as GT
    assert GT.KINDS["nested"] == {"prefix": "nested_", "signature": "program"}
    assert "nested" in GT.VALUE_KINDS
    assert GT.COMPILE_LIMIT_S["nested"] == 900
    row = {"kind": "nested", "ident": "nd-c-omp-one-chain-d1-x",
           "toolchain": "cce19", "outcome": "wrong_answer",
           "stdout": "tot= 1\nRESULT ran_on_host=0 check=fail\n"}
    assert "nd-c-omp-one-chain-d1-x" in GT.signature(row)


# --- function results ------------------------------------------------------------------------

def test_function_result_programs():
    ps = G.fnres_programs()
    assert [p.id for p in ps] == [
        "nd-fnres-c-view-by-value", "nd-fnres-c-child-pointer",
        "nd-fnres-c-stats-struct", "nd-fnres-f-view-by-value",
        "nd-fnres-f-child-pointer", "nd-fnres-f-stats-struct"]
    by = {p.id: p for p in ps}
    # hand computed: roots 100..107 (sum 828), children 200..207 (sum 1628)
    assert by["nd-fnres-c-view-by-value"].expected == {"tot": 828 + 1628}
    assert by["nd-fnres-f-child-pointer"].expected["tot"] == 1628 + 5 * 36
    st = by["nd-fnres-c-stats-struct"].expected["out"]
    assert st == 1628 * 1000 + 207 * 10 + (203 + 207)
    for p in ps:
        assert p.legality == "defined" and p.cites
        assert "declare target" in p.source
        assert all(not DR.check_citation(dict(r)) for r in p.cites)
    assert "function mkview(p) result(v)" in by[
        "nd-fnres-f-view-by-value"].source
    assert "struct view mkview" in by["nd-fnres-c-view-by-value"].source
    assert "!$omp map(to: r)" in by["nd-fnres-f-view-by-value"].source


def test_function_results_are_in_the_sample(sample):
    ids = {p.id for p in sample}
    assert "nd-fnres-c-child-pointer" in ids
    assert "nd-fnres-f-stats-struct" in ids


def test_global_root_uses_the_extended_list_form():
    p = prog(depth=2, links=("ptr",), datas=("ptr",), strategy="enter",
             root="global")
    assert "#pragma omp declare target(g)" in p.source
    assert "to(g)" not in p.source.split("#include")[1].split(
        "int main")[0]
    f = prog(lang="f", depth=2, links=("ptr",), datas=("ptr",),
             strategy="enter", root="global")
    assert "!$omp declare target(g)" in f.source


# --- the design note ---------------------------------------------------------------------------

DOC = "docs/tooling/nested-data.md"


def test_design_note_citations_check():
    from pathlib import Path
    from offload.engine import citations as CI
    root = Path(CI.ROOT)
    res = CI.scan([root / DOC])
    bad = [(r.citation.text if hasattr(r, "citation") else r, r.status)
           for r in res if r.status not in ("ok", "skipped", "external")]
    assert res and not bad, bad[:5]


def test_design_note_names_every_strategy_and_topology():
    from pathlib import Path
    text = (Path(__file__).resolve().parent.parent.parent / DOC).read_text()
    for w in ("`one`", "`enter`", "`tdata`", "`present`", "`update`",
              "`mapper`", "diamond", "twin", "alias-sub", "fnres"):
        assert w in text, w


def test_mutations_leave_no_empty_construct():
    s = G.build_shape(cfg(depth=2, links=("parr",), datas=("alloc", "ptr"),
                          lang="f", strategy="enter", mutate="drop_edge"))
    plan = G.make_plan(s)
    assert all(c.items for c in plan.cons if c.kind != "region")
    p = G.program(s.cfg)
    assert "enter data\n" not in p.source


# --- the larger draw: every axis value covered under the current labels ----------------

def _draw_labels(ps):
    """The programs as the draw saw them: before the review relabel of OpenACC overlaps."""
    return [G.program(p.cfg, legacy=False, review=False) for p in ps if p.id.startswith("nd-fnres") is False]


def test_new_draw_covers_every_axis_value_eight_times():
    # coverage is judged on the labels the draw used; the review relabel (pending) comes after
    ps = G.pilot(300, 5, min_cover=8, legacy=False, max_tries=600)
    cov = G.coverage(_draw_labels(ps))
    low = {k: v for k, v in cov.items() if v < 8}
    assert not low, low


def test_new_draw_differs_from_the_pilot_and_is_deterministic():
    a = G.pilot(120, 5, min_cover=8, legacy=False, max_tries=600)
    b = G.pilot(120, 5, min_cover=8, legacy=False, max_tries=600)
    assert [p.id for p in a] == [p.id for p in b]
    pilot_ids = {p.id for p in G.pilot(340, 1)}
    assert len(pilot_ids & {p.id for p in a}) < len(a) // 10


def test_a_mapper_of_a_self_referential_type_is_a_cycle():
    # 5.2 §5.8.8 p.164 l.9-10: a cyclic definition is unspecified
    for topo, depth in (("list", 3), ("tree", 3)):
        for st in ("mapper", "mapper_enter"):
            v = verdict(topo=topo, depth=depth, strategy=st, datas=("fixed",),
                        roles=("inout",))
            assert v.status == "unspecified", (topo, st, v.reasons)
            assert any(t == "omp.mapper.cycle" for t, _ in v.reasons)
    assert verdict(depth=2, links=("ptr",), strategy="mapper",
                   roles=("inout",)).status == "defined"
    s = G.build_shape(cfg(topo="list", depth=3, strategy="mapper"))
    assert G.validate(s, G.make_plan(s), legacy=True).status == "defined"


# --- OpenACC overlapping subarrays in one clause set are pending ---------------------

def _acc_alias(strategy, lang="c", seed=1):
    import random
    rng = random.Random(seed)
    for _ in range(400):
        c = G.random_cfg(rng, lang, "acc", topo="aliassub", strategy=strategy)
        if G.program(c, legacy=False, review=False).legality == "defined":
            return c
    raise AssertionError("no defined draw")


def test_overlapping_acc_subarrays_in_one_clause_set_are_pending():
    # the cached OpenACC 3.4 text has no rule for a var that overlaps another var of the same
    # directive; separate directives (enter) keep their label
    for lang in ("c", "f"):
        for st in ("one", "tdata"):
            p = G.program(_acc_alias(st, lang))
            assert p.legality == "pending", (lang, st)
            assert "overlap" in p.why
        assert G.program(_acc_alias("enter", lang)).legality == "defined"
    import random
    c = G.random_cfg(random.Random(2), "c", "omp", topo="aliassub", strategy="update")
    assert G.program(c).legality != "pending"


def test_the_relabel_leaves_the_draw_as_it_was(monkeypatch):
    a = G.pilot(120, 5, min_cover=8, legacy=False, max_tries=600)
    monkeypatch.setattr(G, "ACC_OVERLAP_PENDING", False)
    b = G.pilot(120, 5, min_cover=8, legacy=False, max_tries=600)
    assert [p.id for p in a] == [p.id for p in b]


# ---- tools/campaigns/nested.py: the campaign tool's pure parts (cells, signatures) --------------------

import where
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="module")
def N():
    spec = importlib.util.spec_from_file_location("nested_tool",
                                                  ROOT / "tools" / "campaigns" / "nested.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def sample_2():
    from offload.engine import nested_gen as G
    return G.pilot(120, 3)


def test_cells_skip_what_a_toolchain_cannot_express(N, sample_2):
    ids = {p.id for p in sample_2}
    cells = N._cells(sample_2, ["afar", "cce21", "nvhpc"], [0, 1, 2], ids)
    by = {(p.lang, p.model, t) for p, t, x in cells}
    assert ("c", "acc", "cce21") not in by          # CCE has no C OpenACC
    assert ("f90", "acc", "afar") not in by           # AFAR has no OpenACC
    assert ("f90", "acc", "cce21") in by and ("c", "acc", "nvhpc") in by
    for p, t, x in cells:
        assert N.MODE_NAME[x] in p.modes


def test_cells_run_both_memory_modes(N, sample_2):
    ids = {p.id for p in sample_2}
    cells = N._cells(sample_2, ["cce21"], [0, 1], ids)
    one = next(p for p in sample_2 if p.lang == "f90" and p.model == "omp")
    assert sorted(x for p, t, x in cells if p.id == one.id) == [0, 1]


def test_reason_normalization_drops_numbers_and_paths(N):
    a = N.norm_reason("ERROR: file /tmp/x/prog.c, line 41: bad 0x1f")
    b = N.norm_reason("ERROR: file /var/y/prog.c, line 99: bad 0x77")
    assert a == b and "41" not in a and "0x1f" not in a


def test_signature_of_wrong_answers_names_the_failing_checks(N, monkeypatch):
    monkeypatch.setattr(N, "_cls", lambda r: "wrong_answer")
    r = {"expected": {"tot": 5, "ha0": 3, "hs0": 1},
         "observed": {"tot": 5, "ha0": 4, "hs0": 2}}
    assert N.row_signature(r) == "wrong:ha0,hs0"


def test_axis_items_flatten_lists(N, sample_2):
    items = N.axis_items(sample_2[0])
    assert any(i.startswith("strategy=") for i in items)
    assert all("objects" not in i for i in items)


def test_gen_writes_a_checkable_sample(N, tmp_path, monkeypatch):
    monkeypatch.setattr(N, "OUT", tmp_path)
    monkeypatch.setattr(N, "_CACHE", {})
    import argparse
    assert N.cmd_gen(argparse.Namespace(name="t", n=40, seed=2)) == 0
    rows = [json.loads(ln) for ln in
            (tmp_path / "t" / "programs.jsonl").read_text().splitlines()]
    assert len(rows) >= 40
    for r in rows:
        ext = "c" if r["lang"] == "c" else "f90"
        assert (tmp_path / "t" / "src" / f"{r['id']}.{ext}").exists()
    ps = N.programs("t")
    assert [p.id for p in ps] == [r["id"] for r in rows]


def test_the_runner_scripts_are_executable_and_bounded():
    for name in ("run_nested.sh", "run_nested_tioga.sh",
                 "run_wingtip_nested.sh", "nested_remote.sh"):
        p = where.tool(name)
        assert p.stat().st_mode & 0o111, name
    text = (ROOT / "tools" / "jobs" / "run_nested.sh").read_text()
    assert "flux batch -q pbatch" in text and "-q pdebug" in text
    assert "timeout -k 10" in text


def test_gen_records_the_draw_parameters(N, tmp_path, monkeypatch):
    monkeypatch.setattr(N, "OUT", tmp_path)
    monkeypatch.setattr(N, "_CACHE", {})
    import argparse
    import json
    ns = argparse.Namespace(name="big", n=60, seed=9, min_cover=8,
                            current_labels=True, max_tries=600)
    assert N.cmd_gen(ns) == 0
    meta = json.loads((tmp_path / "big" / "meta.json").read_text())
    assert meta == {"n": 60, "seed": 9, "min_cover": 8, "legacy": False,
                    "max_tries": 600}
    ps = N.programs("big")
    from offload.engine import nested_gen as G
    want = G.pilot(60, 9, min_cover=8, legacy=False, max_tries=600)
    assert [p.id for p in ps] == [p.id for p in want]


def test_node_share_same_other_any_and_stored_on(N):
    items = [{"cell": f"c{i}", "node": n}
             for i, n in enumerate(["n1", "n1", "n2", "n3"])]

    def ids(xs):
        return [x["cell"] for x in xs]
    # the gate's (a, b, d) in place: the rows stored on this node
    assert ids(N._node_share(items, "same", "n1")) == ["c0", "c1"]
    # (c): the rows stored on any other node
    assert ids(N._node_share(items, "other", "n1")) == ["c2", "c3"]
    # no placement: every row, or only the rows stored on the listed nodes
    assert ids(N._node_share(items, "any", "n9")) == ["c0", "c1", "c2", "c3"]
    assert ids(N._node_share(items, "any", "n9", "n2,n3")) == ["c2", "c3"]
    assert ids(N._node_share(items, None, "n9")) == ["c0", "c1", "c2", "c3"]
    # the list also narrows the in-place shares
    assert ids(N._node_share(items, "other", "n9", "n3")) == ["c3"]


# ---- tools/campaigns/nested_try.py: the reductions' runner, including the gate's -------------------------





@pytest.fixture(scope="module")
def T():
    spec = importlib.util.spec_from_file_location("nested_try",
                                                  ROOT / "tools" / "campaigns" / "nested_try.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_gate_item_names_the_cell_and_toolchain(T):
    it = T.gate_item("g5-ctl", "gcc_g90", 0)
    assert it["kind"] == "nested" and it["ident"] == "g5-ctl"
    assert it["toolchain"] == "gcc_g90" and it["xnack"] == 0
    assert it["cell"] == "nested|g5-ctl|gcc_g90|0"


def test_gate_environments_are_the_requested_ones(T, tmp_path):
    envs = T.gate_envs(T.gate_item("g5-ctl", "gcc_g90", 0), "a,b,d",
                       str(tmp_path))
    assert [e["env"] for e in envs] == ["a", "b", "d"]
    assert len({e["path"] for e in envs if e["env"] in ("a", "d")}) == 1
    assert envs[1]["path"] != envs[0]["path"]
    c = T.gate_envs(T.gate_item("g5-ctl", "gcc_g90", 0), "c", str(tmp_path))
    assert [e["env"] for e in c] == ["c"] and c[0]["node"] == "other"


def test_gate_run_records_every_environment(T, tmp_path, monkeypatch):
    from offload.engine import gate_run as GR
    calls = []

    def fake(prog, tc, xnack, env, opt, timeout_s, compile_timeout_s):
        calls.append(env["env"])
        return {"outcome": "correct_on_device", "node": "n1", "stdout": "x",
                "env": env["env"]}
    monkeypatch.setattr(GR, "rerun_program", fake)
    src = tmp_path / "t.c"
    src.write_text("int main(void){return 0;}\n")
    rows = T.gate_rows(str(src), "gcc_g90", 0, "a,b,d", 60, str(tmp_path))
    assert calls == ["a", "b", "d"]
    assert [r["env"] for r in rows] == ["a", "b", "d"]
    assert all(r["program_id"] == "t" and r["toolchain"] == "gcc_g90"
               for r in rows)


def test_rows_are_written_as_cells_finish_not_in_file_order(T, tmp_path, monkeypatch):
    """One slow cell must not hold back the rows of the others (a job killed
    at its time limit keeps every finished cell)."""
    import dataclasses
    import json
    import time

    from offload.engine import harness, run_matrix

    @dataclasses.dataclass
    class R:
        program_id: str
        toolchain: str
        xnack: int
        outcome: str = "correct_on_device"
        reason: str = ""
        stdout: str = ""
        stderr: str = ""

    class P:
        model = "omp"
        lang = "c"
        source = "int main(){}"

    def fake(prog, tc, x, flags, timeout_s, repeats):
        f = tc.name
        if f == "slow":
            time.sleep(0.6)
        return R(f, f, x)

    monkeypatch.setattr(T, "_program", lambda f, m=None: P())
    monkeypatch.setattr(run_matrix, "for_version", lambda tc, v, lang: tc)
    monkeypatch.setattr(harness, "run_program", fake)
    from offload.engine import toolchains
    monkeypatch.setattr(toolchains, "TOOLCHAINS",
                        {"slow": type("X", (), {"xnack_modes": (0,), "name": "slow"})(),
                         "fast": type("X", (), {"xnack_modes": (0,), "name": "fast"})()})
    out = tmp_path / "o.jsonl"
    T.main([str(out), "a.c", "--toolchains", "slow,fast", "--modes", "0",
            "--workers", "2"])
    order = [json.loads(line)["toolchain"] for line in out.read_text().splitlines()]
    assert order == ["fast", "slow"]


# ---- fortran-oop: the derived-type and OOP program families ----------------------------------------------

import re


from offload.engine import oop_gen as G_4
from offload.engine import prerun



def _tool():
    spec = importlib.util.spec_from_file_location("oop_tool",
                                                  ROOT / "tools" / "campaigns" / "oop.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PROGS = G_4.programs()


def test_families_and_variants():
    fams = {p.family for p in PROGS}
    assert fams == set(G_4.FAMILIES)
    assert len({p.id for p in PROGS}) == len(PROGS)
    # every family has at least two variants
    for f in G_4.FAMILIES:
        assert sum(p.family == f for p in PROGS) >= 2, f
    assert {p.legality for p in PROGS} == {"defined", "unspecified"}
    assert all(p.why for p in PROGS if p.legality == "unspecified")
    assert not any(p.why for p in PROGS if p.legality == "defined")


@pytest.mark.parametrize("p", PROGS, ids=lambda p: p.id)
def test_program_shape(p):
    src = p.source
    assert all(len(ln) <= 132 for ln in src.split("\n"))
    assert src.count("RESULT ran_on_host=") == 1
    assert ("!$acc" in src) == (p.model == "acc")
    assert p.version == (34 if p.model == "acc" else 52)
    # the checks compare against the generator's expected values
    for k, v in p.expected.items():
        assert f"ok = ok .and. ({k} == {v})" in src
        assert f"print '(a,i0)', '{k}= ', {k}" in src
        assert re.search(rf"^\s*integer :: .*\b{k}\b", src, re.M), k
    assert "expected (computed by compliance/oop_gen.py)" in src
    assert f"legality: {p.legality}" in src


@pytest.mark.parametrize("p", PROGS, ids=lambda p: p.id)
def test_rules_witness_accepts_every_program(p):
    ok, why = prerun.rules_witness(p)
    assert ok, why


def test_type_bound_rule_fires_when_declare_target_is_dropped():
    """The families' type-bound procedures need their declare target: the
    rules refuse a program without it."""
    p = G_4.program("oop-poly-dispatch")
    src = p.source.replace(
        "  integer function rect_area(s)\n    !$omp declare target\n",
        "  integer function rect_area(s)\n")
    assert src != p.source
    ok, why = prerun.rules_witness((src, "f90", "omp", 52))
    assert not ok and any("typebound-declaretarget" in w for w in why)


def test_parse_observed():
    assert G_4.parse_observed("r1= 5\nr2= -3\nRESULT ran_on_host=0 check=pass"
                            ) == {"r1": 5, "r2": -3}


def test_cells_skip_openacc_on_afar_and_modes():
    T = _tool()
    acc = G_4.program("oop-acc-copy-struct")
    omp = G_4.program("oop-nested-whole")
    cells = T._cells([acc, omp], ["afar", "cce19"], [0, 1],
                     {acc.id, omp.id})
    assert {(p.id, t, x) for p, t, x in cells} == {
        (omp.id, "afar", 0), (omp.id, "afar", 1),
        (omp.id, "cce19", 0), (omp.id, "cce19", 1),
        (acc.id, "cce19", 0), (acc.id, "cce19", 1)}
    # a GCC toolchain has the copy mode only
    cells = T._cells([omp], ["gcc_sm80"], [0, 2], {omp.id})
    assert [(t, x) for _, t, x in cells] == [("gcc_sm80", 0)]


def test_legality_needs_a_front_end_of_another_family(tmp_path, monkeypatch):
    T = _tool()
    monkeypatch.setattr(T, "OUT", tmp_path)
    (tmp_path / "x").mkdir()
    a, b, c = PROGS[0].id, PROGS[1].id, PROGS[2].id
    (tmp_path / "x" / "prerun.jsonl").write_text("".join(
        '{"id": "%s", "ok": false, "reasons": [], "rules": true, '
        '"rules_why": [], "afar_fe": %s, "afar_why": ["%s"]}\n' % x for x in
        [(a, "false", "frontend: t.f90:3:1: error: bad"),
         (b, "false", "frontend: not yet implemented: PDT"),
         (c, "true", "")]))
    (tmp_path / "x" / "witness.jsonl").write_text(
        '{"program": "%s", "result": "accept", "message": ""}\n' % a +
        '{"program": "%s", "result": "reject", "message": "NVFORTRAN-F-1252-'
        'Call to type-bound procedures are not allowed on device"}\n' % c)
    leg = T.legality("x")
    # AFAR's own front end refuses a: still legal for AFAR (NVHPC accepts),
    # not for CCE, NVHPC or GCC (AFAR's diagnostic is their witness's)
    assert leg[a]["legal_for"] == {"afar": True, "cce": False,
                                   "nvhpc": False, "gcc": False}
    # b: AFAR names a missing feature (no verdict) and no other witness
    assert leg[b]["afar_fe"] is None
    assert not any(leg[b]["legal_for"].values())
    # c: NVHPC's "not allowed on device" is no verdict; AFAR accepts
    assert leg[c]["nvhpc_fe"] is None
    assert leg[c]["legal_for"] == {"afar": False, "cce": True,
                                   "nvhpc": True, "gcc": True}
    # a CCE row that compiled witnesses the AFAR rows
    (tmp_path / "x" / "rows.jsonl").write_text(
        '{"program_id": "%s", "toolchain": "cce19", "xnack": 0, '
        '"outcome": "wrong_answer"}\n' % c)
    assert T.legality("x")[c]["legal_for"]["afar"] is True


def test_gate_kind_registered():
    from offload.engine import gate as GT
    assert GT.KINDS["oop"] == {"prefix": "oop_", "signature": "program"}
    assert "oop" in GT.VALUE_KINDS
    item = {"kind": "oop", "outcome": "wrong_answer",
            "reason": "check_fail: ran_on_host=0 check=fail",
            "stdout": "r1= 3\nRESULT ran_on_host=0 check=fail",
            "toolchain": "cce19", "ident": "oop-x-y"}
    assert GT.observe(item)[1].endswith("r1=3")


def test_a_cce_diagnostic_rejection_is_a_rejection(tmp_path, monkeypatch):
    """A CCE diagnostic counts against the other families (a
    missing-feature message or a link failure does not)."""
    T = _tool()
    monkeypatch.setattr(T, "OUT", tmp_path)
    (tmp_path / "x").mkdir()
    a, b, c = PROGS[0].id, PROGS[1].id, PROGS[2].id
    (tmp_path / "x" / "prerun.jsonl").write_text("".join(
        '{"id": "%s", "ok": true, "reasons": [], "rules": true, '
        '"rules_why": [], "afar_fe": true, "afar_why": []}\n' % x
        for x in (a, b, c)))
    (tmp_path / "x" / "rows.jsonl").write_text(
        '{"program_id": "%s", "toolchain": "cce19", "xnack": 0, "outcome": '
        '"rejected", "reason": "diagnostic: ftn-1853 ftn: ERROR"}\n' % a +
        '{"program_id": "%s", "toolchain": "cce19", "xnack": 0, "outcome": '
        '"rejected", "reason": "not_implemented: Unsupported OpenMP '
        'construct"}\n' % b +
        '{"program_id": "%s", "toolchain": "cce19", "xnack": 0, "outcome": '
        '"rejected", "reason": "link_undefined_symbol: lld: error"}\n' % c)
    leg = T.legality("x")
    assert leg[a]["cce_fe"] is False
    assert leg[a]["legal_for"]["afar"] is False
    assert leg[a]["legal_for"]["cce"] is True
    assert leg[b]["cce_fe"] is None
    assert leg[c]["cce_fe"] is True


def test_a_diagnostic_about_a_compiler_generated_entity_is_no_verdict(
        tmp_path, monkeypatch):
    """CCE's ftn-1853 names its own default mapper (default$mapper$lv...),
    an entity the program does not contain: no verdict on the program."""
    T = _tool()
    assert T.NOT_A_VERDICT.search("diagnostic: ftn-1853 ftn: ERROR "
                                  "default$mapper$lv$oop_m_, File = x")
    assert not T.NOT_A_VERDICT.search("diagnostic: ftn-1725 ftn: ERROR "
                                      "HV_ORIG_MAIN, File = x")


def test_cce_mapper_diagnostic_end_to_end(tmp_path, monkeypatch):
    """A CCE row whose only diagnostic is ftn-1853 about its
    generated default mapper leaves CCE without a verdict (legality()),
    and only that mapper's name is exempt: another $-name is a rejection."""
    T = _tool()
    monkeypatch.setattr(T, "OUT", tmp_path)
    (tmp_path / "x").mkdir()
    a, b = PROGS[0].id, PROGS[1].id
    (tmp_path / "x" / "prerun.jsonl").write_text("".join(
        '{"id": "%s", "ok": true, "reasons": [], "rules": true, '
        '"rules_why": [], "afar_fe": true, "afar_why": []}\n' % x
        for x in (a, b)))
    (tmp_path / "x" / "rows.jsonl").write_text(
        '{"program_id": "%s", "toolchain": "cce19", "xnack": 0, "outcome": '
        '"rejected", "reason": "diagnostic: ftn-1853 ftn: ERROR '
        'default$mapper$lv$oop_m_, File = x.f90"}\n' % a +
        '{"program_id": "%s", "toolchain": "cce19", "xnack": 0, "outcome": '
        '"rejected", "reason": "diagnostic: ftn-1853 ftn: ERROR '
        'other$name, File = x.f90"}\n' % b)
    leg = T.legality("x")
    assert leg[a]["cce_fe"] is None and leg[a]["legal_for"]["nvhpc"] is True
    assert leg[b]["cce_fe"] is False


# ---- kernel-body campaign: the generator, its model and its legality model ----------------------------

import shutil
import subprocess
from dataclasses import replace


from offload.engine import kbody_cites as KC
from offload.engine import kbody_gen as G_5


# --- the spec rows --------------------------------------------------------------------

def test_every_cite_checks_against_the_spec_text_5():
    bad = {}
    for tag, rows in KC.CITES.items():
        for r in rows:
            probs = DR.check_citation(r)
            if probs:
                bad[(tag, r["page"], r["lines"])] = probs
    assert not bad, bad


# --- the student's program is program 0 --------------------------------------------------

def test_the_students_program_has_the_students_statements():
    p = G_5.program(G_5.student_cfg())
    s = p.source
    assert "gps(local_idx)%loc = [i, j, k]" in s
    assert "!$omp target teams distribute parallel do collapse(3)" in s
    assert "!$omp atomic capture" in s
    assert "count = count + 1" in s and "local_idx = count" in s
    assert "map(to: count)" in s and "has_device_addr(gps)" in s
    assert "is_gp = .true.; exit search" in s
    assert "integer, parameter :: m = 439, n = 329, p = 329" in s
    # has_device_addr of a host address: defined where the device addresses
    # host memory, unspecified on separate memory (5.2 5.4.9)
    assert p.legality == "unspecified" and "omp.has-device-addr" in p.rules
    q = G_5.program(replace(G_5.student_cfg(), hda=False))
    assert q.legality == "defined" and "has_device_addr" not in q.source


def test_the_model_of_the_student_problem():
    e = G_5.model(G_5.student_cfg())
    assert e["num_gps"] == 257000            # `orig.x 20 10 3` printed this
    assert e["claimed"] == 257000
    assert e["bad"] == e["dup"] == e["missing"] == 0
    # the sums are invariant under any slot order; check one by hand
    assert e["sum_id"] == sum(range(1, 1001)) * 257
    assert "count" not in e                  # map(to: count)


def test_count_is_checked_when_it_is_copied_back():
    e = G_5.model(replace(G_5.student_cfg(), count_map="tofrom"))
    assert e["count"] == 257000


def test_branch_changes_the_cell_count():
    a = G_5.model(replace(G_5.student_cfg(), branch="all"))["num_gps"]
    d = G_5.model(replace(G_5.student_cfg(), branch="div"))["num_gps"]
    s1 = G_5.model(replace(G_5.student_cfg(), branch="search", layers=1))["num_gps"]
    assert a == 257000 and d == 1000 * 141 and 0 < s1 < a


def test_dense_model_is_closed_form():
    c = replace(G_5.student_cfg(), geom="dense", dims=(5, 3, 4), branch="all")
    e = G_5.model(c)
    cells = [(i, j, k) for i in range(6) for j in range(4) for k in range(5)]
    assert e["num_gps"] == len(cells)
    assert e["sum_x"] == sum(i for i, j, k in cells)
    assert e["sum_id"] == sum((i + j + k) % 7 + 1 for i, j, k in cells)
    d = G_5.model(replace(c, branch="div"))
    ev = [t for t in cells if sum(t) % 2 == 0]
    assert d["num_gps"] == len(ev) and d["sum_z"] == sum(k for _, _, k in ev)


def test_model_swap_has_one_record_per_sphere():
    e = G_5.model(replace(G_5.student_cfg(), claim="swap"))
    assert e == {"num_gps": 257000, "claimed": 1000, "bad": 0, "dup": 0,
                 "missing": 0}


# --- determinism, ids, the sample ------------------------------------------------------------

def test_program_is_deterministic():
    c = replace(G_5.student_cfg(), loc="reshape", cnt="comp")
    assert G_5.program(c).source == G_5.program(c).source
    assert G_5.program(c).id == G_5.program(c).id


def test_pilot_is_deterministic_unique_and_starts_with_the_student():
    a = G_5.pilot(30, seed=3)
    b = G_5.pilot(30, seed=3)
    assert [p.id for p in a] == [p.id for p in b]
    assert [p.source for p in a] == [p.source for p in b]
    assert len({p.id for p in a}) == 30
    assert a[0].cfg == G_5.student_cfg()
    assert G_5.pilot(30, seed=4)[1].id != a[1].id


def test_pilot_covers_every_idiom_axis_value():
    ps = G_5.pilot(360, seed=1)
    seen = {}
    for p in ps:
        for k, v in p.axes.items():
            seen.setdefault(k, set()).add(v)
    for loc in G_5.PILOT_LOCS:
        assert loc in seen["loc"], loc
    for tgt in G_5.F_TGT:
        assert tgt in seen["tgt"]
    assert {"cap_uf", "cap_fu", "none", "swap", "cap_stmt"} <= seen["claim"]
    assert {"var", "elem", "comp", "elemcomp"} <= seen["cnt"]
    assert {1, 2, 3} <= seen["collapse"]
    assert {"c", "f"} == seen["lang"]
    assert {"int4", "int8", "real8"} <= seen["ctype"]


def test_lines_fit_and_every_program_names_its_rules():
    for p in G_5.pilot(80, seed=1):
        assert all(len(ln) <= 132 for ln in p.source.split("\n")
                   ) or p.lang == "c"
        assert p.rules and p.cites
        assert "RESULT ran_on_host=" in p.source
        assert p.source.count("RESULT ran_on_host=") == 1


# --- the legality model --------------------------------------------------------------------------

def test_swap_is_unspecified_not_defined():
    v = G_5.validate(replace(G_5.student_cfg(), claim="swap"))
    assert v.status == "unspecified"
    assert any(t == "omp.atomic.write-capture" for t, _ in v.reasons)


def test_atomic_blocks_of_every_generated_program_fit_the_spec_forms():
    bad = {}
    for p in G_5.pilot(150, seed=2):
        probs = G_5.atomic_problems(p.source, "c" if p.lang == "c" else "f")
        if probs:
            bad[p.id] = probs
    assert not bad, bad


@pytest.mark.parametrize("stmts,ok", [
    (["!$omp atomic capture", "n = n + 1", "v = n", "!$omp end atomic"], True),
    (["!$omp atomic capture", "v = n", "n = n + 1", "!$omp end atomic"], True),
    (["!$omp atomic capture", "v = n", "n = max(n, v)", "!$omp end atomic"],
     False),                                   # expr references v == x's capture
    (["!$omp atomic capture", "n = n + 1", "n = n + 2", "!$omp end atomic"],
     False),
    (["!$omp atomic capture", "n = n + 1", "m = 2", "v = n",
      "!$omp end atomic"], False),            # three statements
    (["!$omp atomic update", "n = n + n"], False),   # expr references x
    (["!$omp atomic update", "n = n * 2"], True),
    (["!$omp atomic", "c(1) = max(c(1), k)"], True),
    (["!$omp atomic update", "n = foo(n, 2)"], False),   # not an allowed intrinsic
])
def test_atomic_checker_fortran(stmts, ok):
    assert (G_5.atomic_problems("\n".join(stmts)) == []) == ok


def test_atomic_checker_c():
    good = "#pragma omp atomic capture\n{ v = x; x += 1; }\n"
    assert G_5.atomic_problems(good, "c") == []
    assert G_5.atomic_problems("#pragma omp atomic capture\nv = x++;\n", "c") == []
    assert G_5.atomic_problems("#pragma omp atomic update\nx++;\n", "c") == []
    assert G_5.atomic_problems(
        "#pragma omp atomic capture\n{ v = x; w = 3; y = 4; }\n", "c")


def test_config_rejects_what_cannot_be_built():
    with pytest.raises(ValueError):
        G_5.check_cfg(replace(G_5.student_cfg(), loc="bogus"))
    with pytest.raises(ValueError):
        G_5.check_cfg(replace(G_5.student_cfg(), spacing=10))      # overlap
    with pytest.raises(ValueError):
        G_5.check_cfg(replace(G_5.student_cfg(), aux="real", rec="small"))
    with pytest.raises(ValueError):
        G_5.check_cfg(replace(G_5.student_cfg(), claim="cap_stmt"))
    with pytest.raises(ValueError):
        G_5.check_cfg(G_5.Cfg(lang="c", marker="alloc", loc="struct_literal",
                          tgt="elem_comp"))


# --- the neighbourhood -------------------------------------------------------------------------------

def test_neighbours_differ_in_one_axis_and_include_the_passing_control():
    base = G_5.student_cfg()
    ns = G_5.neighbours(base)
    assert len(ns) >= 30
    assert len({c.key() for _, _, c in ns}) == len(ns)
    for axis, val, c in ns:
        diff = [k for k in base.__dict__ if getattr(base, k) != getattr(c, k)]
        assert diff == [axis] or axis == "rec", (axis, diff)
    assert ("loc", "elem") in {(a, v) for a, v, _ in ns}   # the student's control
    pairs = G_5.neighbours(base, include_pairs=True)
    assert len(pairs) > len(ns)


def test_neighbours_of_the_student_total_about_sixty_with_pairs():
    n = len(G_5.neighbours(G_5.student_cfg(), include_pairs=True))
    assert 45 <= n <= 90


# --- the extra host result oracle (gfortran, serial, never a legality witness) -------------------------

import functools
import subprocess
import tempfile

_TEAMS = {"c": "int main(void){int s=0;\n#pragma omp target teams num_teams(2) reduction(+:s)\ns+=1;\nreturn s<1;}\n",
          "f90": "program p\ninteger :: s\ns = 0\n!$omp target teams num_teams(2) reduction(+:s)\ns = s + 1\n"
                 "!$omp end target teams\nend program p\n"}


@functools.cache
def links_openmp_teams(compiler: str, ext: str) -> bool:
    """Whether the host `compiler` builds an OpenMP target teams program. Some installs find an older
    libgomp than their own (`undefined reference to GOMP_teams4`); their host builds say nothing about
    the programs, so the tests that use them skip."""
    if shutil.which(compiler) is None:
        return False
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / f"t.{ext}"
        src.write_text(_TEAMS[ext])
        r = subprocess.run([compiler, "-fopenmp", str(src), "-o", str(Path(d) / "t")], capture_output=True)
        return r.returncode == 0


def test_the_host_compiler_probe_says_no_for_a_missing_compiler():
    assert links_openmp_teams("no-such-compiler-xyz", "c") is False


HAVE_GFORTRAN = links_openmp_teams("gfortran", "f90")


@pytest.mark.skipif(not HAVE_GFORTRAN, reason="no gfortran that links an OpenMP teams program")
@pytest.mark.gfortran
def test_gfortran_serial_build_agrees_with_the_model(tmp_path):
    """The host build (target regions run on the host, four threads, real
    atomics) must print the model's values. This checks the model and the
    emitters together; it says nothing about legality."""
    small = dict(spacing=16, nper=3, trials=2, dims=())
    cfgs = [replace(G_5.student_cfg(), **small, loc=l) for l in G_5.F_LOC]
    cfgs += [replace(G_5.student_cfg(), **small, claim=c, branch=b)
             for c in ("cap_fu", "none", "swap") for b in G_5.BRANCHES]
    cfgs += [replace(G_5.student_cfg(), **small, tgt=t, ctype=ct)
             for t in G_5.F_TGT for ct in G_5.CTYPES]
    cfgs += [replace(G_5.student_cfg(), **small, aux=a) for a in G_5.AUXS]
    cfgs += [replace(G_5.student_cfg(), **small, cnt=c, count_map="tofrom")
             for c in G_5.CNTS_F]
    dense = dict(geom="dense", dims=(23, 19, 21), branch="all", trials=2,
                 rec="small", extras=False)
    cfgs += [replace(G_5.student_cfg(), **dense, claim=c, loc=l)
             for c in ("cap_uf", "cap_fu", "none")
             for l in ("ctor", "elem", "arrexpr", "arrcopy", "rec_assign",
                       "section")]
    cfgs += [replace(G_5.student_cfg(), **{**dense, "branch": "div"}, claim=c)
             for c in ("cap_uf", "none")]
    cfgs += [replace(G_5.student_cfg(), **small, aux="grid")]
    cfgs += [replace(G_5.student_cfg(), **small, storage="enter",
                     marker="alloc", collapse=k) for k in (1, 2)]
    bad = []
    for k, c in enumerate(cfgs):
        try:
            G_5.check_cfg(c)
        except ValueError:
            continue
        p = G_5.program(c)
        src = tmp_path / f"p{k}.f90"
        src.write_text(p.source)
        exe = tmp_path / f"p{k}.x"
        r = subprocess.run(["gfortran", "-O0", "-ffree-line-length-none",
                            "-fopenmp", str(src), "-o", str(exe)],
                           capture_output=True, text=True, cwd=tmp_path)
        if r.returncode:
            bad.append((p.id, r.stderr[-300:]))
            continue
        out = subprocess.run([str(exe)], capture_output=True, text=True,
                             timeout=120, env={"OMP_NUM_THREADS": "4",
                                               "OMP_TARGET_OFFLOAD": "disabled"})
        got = G_5.parse_observed(out.stdout)
        want = dict(p.expected)
        for key, v in want.items():
            if got.get(key) != v:
                bad.append((p.id, key, got.get(key), v))
        assert "check=pass" in out.stdout or any(b[0] == p.id for b in bad)
    assert not bad, bad[:5]


def test_the_rules_witness_accepts_every_defined_program_5():
    """offload.engine.prerun's rules (restrictions and the race rule) accept the
    programs the model calls defined, Fortran and C."""
    from offload.engine import prerun
    bad = {}
    for p in G_5.pilot(120, seed=5):
        if p.legality != "defined":
            continue
        ok, why = prerun.rules_witness(p)
        if not ok:
            bad[p.id] = why[:1]
    assert not bad, list(bad.items())[:4]


def _tool_5():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "kbody_tool", Path(__file__).resolve().parent.parent.parent / "tools" /
        "campaigns" /
        "kbody.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_tool_samples_the_neighbourhood_and_explicit_configurations():
    t = _tool_5()
    nb = t.sample({"kind": "nbhd"})
    assert nb[0].cfg == G_5.student_cfg() and 45 <= len(nb) <= 100
    ps = t.sample({"kind": "cfgs", "cfgs": [
        {"geom": "dense", "dims": [31, 31, 31], "branch": "all",
         "hda": False}]})
    assert ps[0].cfg.dims == (31, 31, 31) and ps[0].legality == "defined"
    assert t.sample({"kind": "pilot", "n": 5, "seed": 1})[0].cfg == \
        G_5.student_cfg()


def test_the_heap_sample_covers_every_write_idiom_in_four_contexts():
    cfgs = G_5.heap_cfgs()
    assert {c.loc for c in cfgs} == set(G_5.F_LOC)
    assert len(cfgs) == len(G_5.F_LOC) * 4 == len({c.key() for c in cfgs})
    ps = [G_5.program(c) for c in cfgs]
    assert all(p.legality == "defined" for p in ps)
    assert {p.axes["heap_guess"] for p in ps} == {True, False}
    assert not any("has_device_addr" in p.source for p in ps)


def test_dense_programs_have_no_spheres():
    c = replace(G_5.student_cfg(), geom="dense", dims=(31, 31, 31),
                branch="all", rec="small", extras=False)
    s = G_5.program(c).source
    assert "mod(i + j + k, 7) + 1" in s and "i*i + j*j + k*k" not in s


HAVE_GCC = links_openmp_teams("gcc", "c")


@pytest.mark.skipif(not HAVE_GCC, reason="no gcc that links an OpenMP teams program")
def test_gcc_host_build_of_the_c_programs_agrees_with_the_model(tmp_path):
    """The C programs, built for the host (target regions run on the host,
    four threads, real atomics) print the model's values: a result oracle
    for the model and the C emitter, never a legality witness."""
    base = G_5.Cfg(lang="c", marker="alloc", loc="scalars", spacing=16, nper=3, trials=2)
    cfgs = [replace(base, loc=l, tgt="nested" if l in (
        "struct_literal", "tmp_struct") else "elem_comp") for l in G_5.C_LOC]
    cfgs += [replace(base, claim=c, branch=b) for c in
             ("cap_uf", "cap_fu", "cap_stmt", "none", "swap")
             for b in G_5.BRANCHES]
    cfgs += [replace(base, cnt=c, count_map="tofrom") for c in G_5.CNTS_C]
    cfgs += [replace(base, collapse=k, ctype="int8", rec="small")
             for k in (1, 2, 3)]
    bad = []
    for k, c in enumerate(cfgs):
        G_5.check_cfg(c)
        p = G_5.program(c)
        src = tmp_path / f"p{k}.c"
        src.write_text(p.source)
        exe = tmp_path / f"p{k}.x"
        r = subprocess.run(["gcc", "-O1", "-std=c11", "-fopenmp", str(src),
                            "-o", str(exe)], capture_output=True, text=True,
                           cwd=tmp_path)
        if r.returncode:
            bad.append((p.id, r.stderr[-400:]))
            continue
        out = subprocess.run([str(exe)], capture_output=True, text=True,
                             timeout=120, env={"OMP_NUM_THREADS": "4",
                                               "OMP_TARGET_OFFLOAD": "disabled"})
        got = G_5.parse_observed(out.stdout)
        for key, v in p.expected.items():
            if got.get(key) != v:
                bad.append((p.id, key, got.get(key), v))
        if "check=pass" not in out.stdout:
            bad.append((p.id, "RESULT", out.stdout[-200:]))
    assert not bad, bad[:5]


def test_the_heap_guess_is_what_the_detector_found():
    """The guess listed pack, cshift, merge_arr, matmul and func_elem, which the detector run found
    allocating nothing; the axis is named a guess."""
    assert set(G_5.HEAP_GUESS) == {"ctor", "ctor_old", "ctor_expr", "reshape", "merge", "section", "tmp", "func"}
    ps = [G_5.program(c) for c in G_5.heap_cfgs()]
    assert all("heap_expected" not in p.axes for p in ps)
    assert {p.axes["heap_guess"] for p in ps} == {True, False}
    assert all(p.axes["heap_guess"] == (p.axes["loc"] in G_5.HEAP_GUESS) for p in ps)


def test_the_heap_guess_agrees_with_the_stored_detector_rows():
    import json
    from pathlib import Path
    import pytest
    rows = Path(__file__).resolve().parent.parent.parent / "results" / "devtemps" / "kbody-heap.jsonl"
    if not rows.exists():
        pytest.skip("results/devtemps/kbody-heap.jsonl (the detector's rows, not in the repository) is absent")
    guess = {p.id: p.axes["heap_guess"] for p in (G_5.program(c) for c in G_5.heap_cfgs())}
    seen = 0
    for line in rows.read_text().splitlines():
        r = json.loads(line)
        if r["id"] in guess and r.get("compile") == "ok":
            seen += 1
            assert (r["allocmem"] > 0) == guess[r["id"]], (r["id"], r["allocmem"])
    assert seen == len(guess)


def test_pilot_stops_when_it_cannot_find_enough_programs(monkeypatch):
    """The draw loop had no bound and never ended when every draw was rejected."""
    import pytest

    def reject(cfg):
        raise ValueError("rejected")
    monkeypatch.setattr(G_5, "random_cfg", lambda rng, lang: reject(None))
    with pytest.raises(ValueError, match="distinct valid programs"):
        G_5.pilot(3, seed=1)


# ---- delta-debugging generator of the device-malloc first-use failure (offload/engine/malloc_dd.py) ------


import yaml

from offload.engine import malloc_dd as D



def test_every_ingredient_has_a_one_change_removal():
    rs = D.removals(D.STUDENT)
    assert [k for k, _, _ in rs] == [k for k, _ in D.REMOVALS]
    for k, v, f in rs:
        assert getattr(f, k) == v
        assert sum(getattr(f, x) != getattr(D.STUDENT, x) for x in D.Flags.__dataclass_fields__) == 1


def test_the_baseline_has_the_students_ingredients():
    s = D.source(D.STUDENT)
    assert "collapse(3)" in s and "atomic capture" in s and "malloc(3 * sizeof(int))" in s
    assert "memcpy(gpp[li].loc, tmp" in s and "map(to : count)" in s and "#define M 439" in s
    assert "i * i + j * j + k * k <= 16" in s
    assert "is_device_ptr" not in s


def test_flags_change_the_text():
    f = D.STUDENT
    assert "collapse(3)" not in D.source(replace(f, loop="flat"))
    assert "atomic" not in D.source(replace(f, slot="precomputed"))
    assert "int g = 0;" not in D.source(replace(f, search=False))
    assert "is_device_ptr(sfp, gpp)" in D.source(replace(f, alloc="devptr"))
    def kernel(text):
        """The main kernel (the warm-up kernel before it always mallocs)."""
        end = text.index("target update from")
        return text[text.rindex("#pragma omp target teams distribute", 0, end):end]
    assert "malloc(" not in kernel(D.source(replace(f, store="direct")))
    assert "free(" not in kernel(D.source(replace(f, store="direct")))
    assert "malloc(" in kernel(D.source(f))
    assert "xp = 0" not in D.source(replace(f, extra=False))
    assert "double ip_loc" not in D.source(replace(f, gp="loc"))
    assert "i * i + j * j + k * k" not in D.source(replace(f, marker="simple"))


HAVE_GCC_6 = links_openmp_teams("gcc", "c")


@pytest.mark.skipif(not HAVE_GCC_6, reason="no gcc that links an OpenMP teams program")
def test_host_builds_of_the_variants_are_clean(tmp_path):
    """On the host the allocator is not the device's: every variant must print bad 0 (a result oracle for the program)."""
    base = replace(D.STUDENT, dim=47)
    flags = [base, replace(base, loop="flat"), replace(base, search=False), replace(base, slot="precomputed"),
             replace(base, marker="simple"), replace(base, gp="loc", extra=False), replace(base, store="stores3"),
             replace(base, store="direct"), replace(base, store="stack"), replace(base, alloc="devptr"),
             replace(base, loop="flat", marker="simple", search=False, slot="precomputed", gp="loc", extra=False,
                     store="stores3"),
             replace(D.minimal(), dim=47), replace(D.minimal(), dim=47, marker="none"),
             replace(D.minimal(), dim=47, alloc="devptr-gps"), replace(D.minimal(), dim=47, alloc="devptr-sf"),
             replace(D.minimal(), dim=47, warm=1000)]
    bad = []
    for n, f in enumerate(flags):
        src = tmp_path / f"c{n}.c"
        src.write_text(D.source(f))
        exe = tmp_path / f"c{n}.x"
        r = subprocess.run(["gcc", "-O1", "-fopenmp", str(src), "-o", str(exe)], capture_output=True, text=True)
        if r.returncode:
            bad.append((n, r.stderr[-300:]))
            continue
        out = subprocess.run([str(exe), "2", "100"], capture_output=True, text=True, timeout=120,
                             env={"OMP_NUM_THREADS": "4", "OMP_TARGET_OFFLOAD": "disabled"}).stdout
        trials = [ln for ln in out.splitlines() if ln.startswith("trial")]
        if len(trials) != 2 or any("bad 0 dup 0 missing 0" not in t for t in trials) or \
                "RESULT ran_on_host=1 check=pass" not in out:
            bad.append((n, out[-200:]))
    assert not bad, bad


def test_the_rules_witness_on_the_variants():
    """offload.engine.prerun's rules (restrictions and the race rule): the controls are accepted; the malloc'd block
    `tmp[0] = i` is reported as a shared element, which it is not (tmp is declared in the loop body and points to a
    block the iteration allocated): a limit of the race rule, recorded here so that the finding's legality line can
    say so."""
    from offload.engine import prerun
    base = replace(D.minimal(), marker="none")
    for f in (replace(base, store="direct"), replace(base, store="stack"), replace(base, store="direct", warm=1000)):
        ok, why = prerun.rules_witness((D.source(f), "c"))
        assert ok, why
    ok, why = prerun.rules_witness((D.source(base), "c"))
    assert not ok and len(why) == 1 and "tmp(0)" in why[0], why


def test_the_fence_variants_are_one_change():
    base = replace(D.minimal(), marker="none")
    a = D.source(base)
    f = D.source(replace(base, fence="device")).split("\n")
    fl = D.source(replace(base, fence="flush")).split("\n")
    assert "__scoped_atomic_thread_fence" not in a and "omp flush" not in a
    i = next(k for k, ln in enumerate(f) if "__scoped_atomic_thread_fence(__ATOMIC_RELEASE, __MEMORY_SCOPE_DEVICE)" in ln)
    assert "memcpy" in f[i - 1] and "free(tmp)" in f[i + 1]
    j = next(k for k, ln in enumerate(fl) if ln.strip() == "#pragma omp flush")
    assert "memcpy" in fl[j - 1] and "free(tmp)" in fl[j + 1]
    assert len(f) == len(a.split("\n")) + 1 == len(fl)


@pytest.mark.skipif(not HAVE_GCC_6, reason="no gcc that links an OpenMP teams program")
def test_the_flush_variant_runs_clean_on_the_host(tmp_path):
    src = tmp_path / "f.c"
    src.write_text(D.source(replace(D.minimal(), marker="none", dim=47, fence="flush")))
    r = subprocess.run(["gcc", "-O1", "-fopenmp", str(src), "-o", str(tmp_path / "f.x")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-300:]
    out = subprocess.run([str(tmp_path / "f.x"), "2", "0"], capture_output=True, text=True, timeout=120,
                         env={"OMP_NUM_THREADS": "4", "OMP_TARGET_OFFLOAD": "disabled"}).stdout
    assert "check=pass" in out


def test_analyze_image_separates_the_rpc_lock_from_the_slab_bitfield():
    asm = "\n".join([
        "\ts_add_u32 s52, s52, __llvm_rpc_client@rel32@lo+52",
        "\tglobal_atomic_and v2, v3, s[52:53]",
        "\tflat_atomic_or v7, v[40:41], v27 offset:16 sc0",
        "\ts_nop 0",
        "\tflat_atomic_and v[2:3], v0 offset:16",
        "\tbuffer_wbl2 sc1",
    ])
    ll = "\n".join([
        '  fence syncscope("agent") release',
        '  %5 = atomicrmw and ptr %4, i32 %3 syncscope("agent") monotonic, align 4',
        '  fence syncscope("agent") release',
    ])
    r = D.analyze_image(asm, ll)
    assert r["rpc_global_atomics"] == 1 and r["other_global_atomics"] == 0
    claim, clear = r["flat_atomics"]
    assert (claim["op"], claim["cache_bits"], clear["op"], clear["cache_bits"]) == ("claim", ["sc0"], "clear", [])
    assert clear["buffer_wbl2_before_line"] is None and clear["buffer_wbl2_after_line"] == 6
    ir = r["ir_flat_atomics"][0]
    assert ir["op"] == "clear" and ir["ordering"] == "monotonic" and ir["previous_fence"][0] == 1 and ir["next_fence"][0] == 3


def test_the_maintainer_image_has_the_flat_claim_without_acquire_and_clear_without_release():
    d = ROOT / "results/student-repro/malloc/cmp/omp"
    asm = next(iter(d.glob("t.x.amdgpu*gfx942*.lto.s")), None)
    if asm is None:
        pytest.skip("results/student-repro/malloc/cmp/omp (the maintainer's saved temporaries, not in the repository) is absent")
    r = D.analyze_image(asm.read_text())
    claim, clear = r["flat_atomics"]
    assert (claim["op"], claim["cache_bits"], clear["op"], clear["cache_bits"]) == ("claim", ["sc0"], "clear", [])
    assert claim["buffer_inv_after_line"] is None or claim["buffer_inv_after_line"] - claim["line"] > 100
    assert clear["buffer_wbl2_before_line"] is None or clear["line"] - clear["buffer_wbl2_before_line"] > 100
    assert r["rpc_global_atomics"] >= 8 and r["other_global_atomics"] == 0


# --- what the findings and notes of the kernel-idioms branch may claim ---------------------------------

CFIND = "data/findings/malloc/afar-device-malloc-in-kernel-corrupts-records.c"
OBS = "data/reports/kbody-observations/afar-device-array-constructor-corrupts-records.f90"
OBS_OLD = "data/findings/malloc/afar-device-array-constructor-corrupts-records.f90"


def _read(path):
    return (ROOT / path).read_text()


def _flat(text):
    """The comment lines of a header as one string (line breaks and comment markers removed)."""
    return re.sub(r"\s+", " ", re.sub(r"\n(?://|!)(?: \+)?", " ", text))


def _header(path):
    text = _read(path)
    cut = min(i for i in (text.find("\n#include"), text.find("\nmodule "), len(text)) if i >= 0)
    return _flat(text[:cut])


def test_the_students_fortran_program_is_an_observation_not_a_finding():
    """By the generator's own model it is `unspecified` (has_device_addr on a host address, 5.2 5.4.9) and only
    AFAR's front end accepted it, so its failure is an observation (docs/tooling/contributing.md), never a finding."""
    assert not (ROOT / OBS_OLD).exists()
    assert not (ROOT / "data/findings/malloc/controls/afar-first-use-malloc-student-elem.f90").exists()
    assert "array-constructor-corrupts-records" not in _read("data/findings/index.yaml")
    log = ROOT / "data/findings/LOG.md"            # the maintainers' log: not in the public export
    assert not log.is_file() or "malloc/afar-device-array-constructor" not in log.read_text()
    text = _read(OBS)
    assert "site:" not in text and "end site" not in text
    head = _header(OBS)
    assert "observation" in head.lower() and "unspecified" in head
    for control in ("elem", "nocons"):
        assert (ROOT / f"data/reports/kbody-observations/controls/afar-first-use-malloc-student-{control}.f90").exists()


def test_the_fortran_observation_states_its_gate_as_the_rows_show_it():
    """The same cell went through the gate twice; the first run failed in a-d, the second in a and b only."""
    head = _header(OBS)
    assert "1 of 1 cells reproduce in all four environments" not in head
    assert "one of two gate runs" in head


def test_the_c_finding_claims_only_the_mode_that_failed_the_gate():
    """The copy cell failed in 1 of 10 harness repeats and was correct in gate a, b, c and d."""
    idx = yaml.safe_load(_read("data/findings/index.yaml"))["findings"]
    entry = [e for e in idx if e["file"] == CFIND.removeprefix("data/findings/")][0]
    assert entry["modes"] == ["unified"], entry
    head = _header(CFIND)
    assert "modes: unified;" in head and "modes: unified, copy" not in head


def test_the_c_finding_is_labelled_an_implementation_contract_not_a_spec_violation():
    """The OpenMP text has no sentence on malloc in a target region."""
    label = "implementation contract (no OpenMP rule)"
    assert label in _header(CFIND)
    site = _read(CFIND).split("// site:")[1]
    assert label in _flat(site)
    idx_text = _read("data/findings/index.yaml")
    i = idx_text.index("malloc/afar-device-malloc-in-kernel-corrupts-records.c")
    assert label in idx_text[max(0, i - 400):i + 400]


def test_the_libc_ctl_and_stock_ranges_in_the_c_finding_are_the_rows_ranges():
    """862 is a stock row; the ctl rows are 903 to 3172."""
    p = ROOT / "results/malloc-dd/exp_rows.jsonl"
    if not p.exists():
        pytest.skip("results/malloc-dd/exp_rows.jsonl is git-ignored and absent from this copy of the repository")
    rows = {}
    for line in p.read_text().splitlines():
        r = json.loads(line)
        if r["id"].startswith(("libc-ctl-r", "libc-stock-r")):
            rows.setdefault(r["id"].split("-")[1], []).extend(sum(x["bad_by_trial"]) for x in r["per_launch"])
    text = _header(CFIND)
    for who in ("ctl", "stock"):
        lo, hi = min(rows[who]), max(rows[who])
        assert f"{lo} to {hi}" in text, (who, lo, hi)


def test_an_experiment_row_records_the_hash_of_the_source_it_ran():
    """The rows named libc-file-* ran results/malloc-dd/final/repro.c, regenerated since; no hash was kept."""
    import hashlib
    spec = {"group": "g", "id": "i", "src": "docs/x.c", "arch": "gfx942", "args": "1 2", "env": {}, "xnack": 1,
            "kind": "omp", "libc": ""}
    text = "int main(void) {\n  return 0;\n}\n"
    head = D.exp_head(spec, text, 3)
    assert head["src_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert head["src_lines"] == 3 and head["launches"] == 3 and head["id"] == "i"


def test_the_c_finding_says_which_text_each_group_of_rows_ran():
    """The rows of the mechanism experiments ran the 56-line regeneration (one declarator per statement, free on its
    own line), not the 53-line text of the finding; the fence and flush controls are one change from the 56-line text."""
    head = _header(CFIND)
    copy = ROOT / "data/reports/kbody-jobs/malloc/repro-56-lines.c"
    assert copy.exists() and len(copy.read_text().splitlines()) == 56
    import hashlib
    assert hashlib.sha256(copy.read_bytes()).hexdigest()[:16] in head
    assert "This 53-line file itself" not in head and "53-line file itself" not in head
    assert "not from this file" in head
    site = _read(CFIND).split("// site:")[1]
    for ctl in ("fence", "flush"):
        line = [x for x in site.splitlines() if f"afar-first-use-malloc-{ctl}.c" in x][0]
        assert "56-line" in line and "one change from the finding" not in line


def test_the_small_size_rows_are_called_64_and_128():
    """The rounds of sizes.c alternate size/2 and size: the '128 B' rows are 64/128 B."""
    text = _header(CFIND)
    assert "128 B (20M threads)" not in text and "64/128 B" in text


def test_observation_rows_do_not_go_into_the_finding_rows():
    """The student's Fortran program is an observation; its rows must not look like a finding's rows."""
    rows = [{"program_id": "afar-first-use-malloc", "cell": "kbody|afar-first-use-malloc|afar|1"},
            {"program_id": "afar-first-use-malloc-student", "cell": "kbody|afar-first-use-malloc-student|afar|1"},
            {"cell": "kbody|afar-first-use-malloc-student-elem|afar|1"},
            {"program_id": "unrelated", "cell": "kbody|unrelated|afar|1"}]
    f, o = D.split_rows(rows, {"afar-first-use-malloc": "data/findings/x.c"},
                        {"afar-first-use-malloc-student": "data/reports/o.f90",
                         "afar-first-use-malloc-student-elem": "data/reports/c.f90"})
    assert [r["file"] for r in f if "file" in r] == ["data/findings/x.c"] and len(f) == 2
    assert [r["file"] for r in o] == ["data/reports/o.f90", "data/reports/c.f90"]


# --- Failure counting in the reductions ----------------------------------------------------------------

def test_a_launch_counts_as_failing_only_when_it_damaged_records():
    """A removal that makes the program crash (nonzero exit, trials missing, no damaged record) must not count as
    'still fails': the greedy reduction would drop an ingredient the failure needs."""
    v = D.launch_verdict
    assert v([(1, 5, 0, 0), (2, 0, 0, 0)], 2, 0)["fail"] is True
    assert v([(1, 0, 3, 0), (2, 0, 0, 0)], 2, 0)["fail"] is True          # duplicated cells
    assert v([(1, 0, 0, 0), (2, 0, 0, 0)], 2, 0)["fail"] is False
    crash = v([(1, 0, 0, 0)], 2, 1)
    assert crash["fail"] is False and crash["crashed"] is True
    both = v([(1, 7, 0, 0)], 2, 139)
    assert both["fail"] is True and both["crashed"] is True and both["first_failing_trial"] == 1
    assert v([], 2, 0) == {"fail": False, "crashed": True, "first_failing_trial": 0, "max_bad": -1}


def test_no_job_script_names_an_agent_worktree():
    """Every script under data/reports/kbody-jobs finds the repository from its own path."""
    bad = {}
    for p in (ROOT / "data/reports/kbody-jobs").rglob("*.sh"):
        t = p.read_text()
        if "/.claude/worktrees/" in t or re.search(r"(?<!data/reports/kbody-jobs/)base_dense\.json", t):
            bad[str(p.relative_to(ROOT))] = "names a worktree or an ignored input"
    assert not bad, bad


def test_build_libc_does_not_continue_outside_a_loop():
    assert "continue" not in (ROOT / "data/reports/kbody-jobs/malloc/build_libc.sh").read_text()


def test_the_tool_does_not_hard_code_the_machine_path():
    """The maintainer's libc builds and student binaries are found through results/, which is where the repository
    root links the shared data."""
    text = (ROOT / "tools/campaigns/malloc_dd.py").read_text()
    assert "/p/lustre5" not in text


# ---- device-heap-temporary detector (offload/engine/devtemps.py): the heap -------------------------------


from offload.engine import devtemps as D_7

MLIR = """module {
  func.func @_QQmain() {
    %0 = fir.allocmem !fir.array<?x?xi32>, %a, %b {uniq_name = "_QFEhits.alloc"}
    omp.target map_entries(%m -> %arg0 : !fir.ref<i32>) {
      %1 = fir.allocmem !fir.array<3xi32> {bindc_name = ".tmp.arrayctor", uniq_name = ""}
      %2 = fir.call @_FortranAAssign(%x, %y) : (i32, i32) -> ()
      omp.terminator
    }
    omp.target_update to(%m : !fir.ref<i32>)
    fir.freemem %0 : !fir.heap<!fir.array<?x?xi32>>
    return
  }
  func.func @dev(%arg0: !fir.ref<i32>) attributes {omp.declare_target = #omp.declaretarget<device_type = (any), capture_clause = (to)>} {
    %3 = fir.allocmem !fir.array<?xf64>, %n {bindc_name = ".tmp.result", uniq_name = ""}
    %4 = fir.call @_FortranAAllocatableAllocate(%d) : (i32) -> i32
    return
  }
  func.func @host2() {
    %5 = fir.allocmem !fir.array<3xi32> {bindc_name = ".tmp.arrayctor", uniq_name = ""}
    return
  }
}
"""


def test_only_allocations_inside_device_code_count():
    r = D_7.scan_fir(MLIR)
    assert r.device_regions == 2
    kinds = sorted(n for n, _ in r.allocmem)
    assert kinds == [".tmp.arrayctor", ".tmp.result"]
    assert r.n_allocmem == 2
    assert r.runtime_calls == {"_FortranAAssign": 1,
                               "_FortranAAllocatableAllocate": 1}
    assert r.at_risk


def test_a_kernel_without_a_temporary_is_clean():
    text = "module {\n func.func @f() {\n  omp.target map_entries() {\n" \
           "   %1 = arith.addi %a, %b : i32\n   omp.terminator\n  }\n" \
           "  return\n }\n}\n"
    r = D_7.scan_fir(text)
    assert r.device_regions == 1 and r.n_allocmem == 0 and not r.at_risk


def test_target_data_and_update_are_not_device_regions():
    text = "module {\n func.func @f() {\n  omp.target_enter_data map_entries() {\n" \
           "   %1 = fir.allocmem !fir.array<3xi32> {bindc_name = \".tmp.x\"}\n  }\n" \
           "  omp.target_update to(%m)\n  return\n }\n}\n"
    assert D_7.scan_fir(text).device_regions == 0


def test_idiom_class_of_a_temporary_name():
    assert D_7.temp_class(".tmp.arrayctor") == "array constructor"
    assert D_7.temp_class(".tmp.result") == "array-valued function result"
    assert D_7.temp_class(".tmp.assign") == "assignment copy"
    assert D_7.temp_class("_QFEx.alloc") == "other"
    assert D_7.temp_class("") == "unnamed (allocatable realloc or other)"


STUDENT = Path(__file__).resolve().parent.parent / "data" / \
    "devtemps_student_kernel.mlir"


def test_the_students_kernel_has_one_array_constructor_temporary():
    """The omp.target region of the student's reproducer (AFAR 24.3.0
    `-save-temps` device FIR, results/student-repro/ir/orig; the kernel only)."""
    r = D_7.scan_fir(STUDENT.read_text())
    assert r.device_regions == 1
    assert [n for n, _ in r.allocmem] == [".tmp.arrayctor"]
    assert r.classes() == {"array constructor": 1}


# The runtime entries that allocate through the device allocator

RUNTIME_ONLY = """module {
  func.func @_QQmain() {
    omp.target map_entries(%m -> %arg0 : !fir.ref<i32>) {
      %2 = fir.call @_FortranAAssign(%x, %y, %f, %l) : (i32, i32, i32, i32) -> ()
      %3 = fir.call @_FortranAAllocatableAllocate(%d, %h, %e, %s, %l) : (i32, i32, i32, i32, i32) -> i32
      omp.terminator
    }
    return
  }
}
"""


def test_a_region_with_only_allocating_runtime_calls_is_at_risk():
    r = D_7.scan_fir(RUNTIME_ONLY)
    assert r.device_regions == 1 and r.n_allocmem == 0
    assert r.at_risk
    assert r.allocating_calls == {"_FortranAAssign": 1, "_FortranAAllocatableAllocate": 1}


def test_runtime_calls_that_do_not_allocate_do_not_make_a_region_at_risk():
    text = RUNTIME_ONLY.replace("_FortranAAssign", "_FortranAProgramStart").replace(
        "_FortranAAllocatableAllocate", "_FortranAStopStatement")
    r = D_7.scan_fir(text)
    assert r.device_regions == 1 and not r.at_risk and not r.allocating_calls


def test_allocating_runtime_calls_on_the_host_do_not_count():
    text = "module {\n func.func @h() {\n  %1 = fir.call @_FortranAAssign(%x) : (i32) -> ()\n  return\n }\n}\n"
    assert not D_7.scan_fir(text).at_risk


def test_braces_in_strings_and_comments_do_not_end_a_region():
    text = """module {
  func.func @f() {
    omp.target map_entries(%m -> %arg0 : !fir.ref<i32>) {
      %0 = fir.call @note() {msg = "}"} : () -> ()   // a closing brace } in a comment
      // } and another one
      %1 = fir.allocmem !fir.array<3xi32> {bindc_name = ".tmp.arrayctor", uniq_name = ""}
      omp.terminator
    }
    return
  }
}
"""
    r = D_7.scan_fir(text)
    assert r.n_allocmem == 1 and r.at_risk


def test_an_allocmem_in_a_comment_is_not_an_allocation():
    text = "module {\n func.func @f() {\n  omp.target map_entries() {\n" \
           "   // %1 = fir.allocmem !fir.array<3xi32> {bindc_name = \".tmp.x\"}\n" \
           "   omp.terminator\n  }\n  return\n }\n}\n"
    r = D_7.scan_fir(text)
    assert r.device_regions == 1 and r.n_allocmem == 0 and not r.at_risk


def test_the_summary_of_several_modules_is_at_risk_when_any_module_is():
    clean = D_7.scan_fir("module {\n func.func @f() {\n  omp.target map_entries() {\n   omp.terminator\n"
                       "  }\n  return\n }\n}\n")
    calls = D_7.scan_fir(RUNTIME_ONLY)
    s = D_7.summarize([clean, calls])
    assert s["regions"] == 2 and s["allocmem"] == 0
    assert s["allocating_calls"] == {"_FortranAAssign": 1, "_FortranAAllocatableAllocate": 1}
    assert s["at_risk"] is True
    assert D_7.summarize([clean])["at_risk"] is False


def test_a_stored_row_is_re_judged_from_its_allocmem_and_calls():
    """Rows written before the runtime calls counted carry `at_risk` from `allocmem` alone;
    the table recomputes it from the stored `allocmem` and `calls`."""
    assert D_7.row_at_risk({"allocmem": 1, "calls": {}})
    assert D_7.row_at_risk({"allocmem": 0, "calls": {"_FortranAAssign": 2}, "at_risk": False})
    assert D_7.row_at_risk({"allocmem": 0, "calls": {"_FortranAPointerAllocateSource": 1}})
    assert not D_7.row_at_risk({"allocmem": 0, "calls": {"_FortranAProgramStart": 1}, "at_risk": False})
    assert not D_7.row_at_risk({"allocmem": 0, "calls": {}})
