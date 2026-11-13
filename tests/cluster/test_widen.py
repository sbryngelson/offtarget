"""The widened catalog (offload.engine.widen, offload.engine.widen_progs):
ids and headers, legality by the catalog's checkers, attributable pairs,
expected values by sequential elision, oracle mutants."""
import dataclasses
import re
import shutil
from concurrent.futures import ThreadPoolExecutor

import pytest

from offload.engine import widen as W
from offload.engine import widen_progs as WP

WIDE = W.all_wide()
IDS = [w.id for w in WIDE]


def test_counts_and_ids():
    assert 150 <= len(WIDE) <= 300
    assert len(set(IDS)) == len(IDS)
    for w in WIDE:
        p = w.program
        assert W.is_wide(p.id)
        assert re.match(r"^(omp52-(c-)?|acc34-)w-[a-z0-9-]+$", p.id), p.id
        assert (p.lang == "c") == ("-c-w-" in p.id)
        assert p.model == ("acc" if p.id.startswith("acc") else "omp")
    pairs = [w for w in WIDE if W.kind_of(w.program.primary_atom) == "pair"]
    assert 50 <= len(pairs) <= 100


def test_one_program_per_atom_language_and_model():
    seen = {}
    for w in WIDE:
        k = (w.program.lang, w.program.model, w.program.primary_atom)
        assert k not in seen, (w.id, seen.get(k))
        seen[k] = w.id


def test_headers():
    for w in WIDE:
        p = w.program
        mark = "//" if p.lang == "c" else "!"
        head = {m.group(1): m.group(2) for m in re.finditer(
            rf"^{mark} ([a-z_ ]+): (.*)$", p.source, re.M)}
        assert head["id"] == p.id
        assert head["primary atom"] == p.primary_atom
        assert head["legal"] == "yes" and head["feature"] and head["spec"]
        atoms = [a.strip() for a in head["atoms"].split(",")]
        assert atoms[0] == p.primary_atom
        assert set(atoms) <= p.atoms
        assert p.source.count("RESULT ran_on_host=") == 1


def test_atom_families():
    for w in WIDE:
        a = w.program.primary_atom
        k = W.kind_of(a)
        if k == "base":
            assert re.match(r"^base\.device\.[a-z0-9_]+$", a), a
        elif k == "form":
            assert re.match(r"^form\.(omp|acc)\.[a-z0-9_]+$", a), a
        elif k == "directive":
            # a grammar atom, carried by a directive of the program
            assert a.startswith(w.program.model + ".")
            assert a in W._parsed_atoms(w.program.source,
                                        "c" if w.program.lang == "c"
                                        else "f90", w.program.model), w.id


def _single_atoms(lang: str, model: str) -> set:
    from offload.engine.catalog import slice_atoms
    v = W.VERSION[model]
    have = set(slice_atoms(v, lang=lang)) if model == "omp" else \
        set(slice_atoms(v))
    have |= {w.program.primary_atom for w in WIDE
             if (w.program.lang == "c") == (lang == "c") and
             w.program.model == model and
             W.kind_of(w.program.primary_atom) != "pair"}
    return have


def test_pairs_are_attributable():
    """Each part of a pair has a program of its own in the same language
    and model: a widened single, or a grammar catalog program."""
    for w in WIDE:
        p = w.program
        if W.kind_of(p.primary_atom) != "pair":
            assert not w.spec.parts
            continue
        a, b = W.pair_parts(p.primary_atom)
        assert (a, b) == tuple(w.spec.parts)
        have = _single_atoms("c" if p.lang == "c" else "f90", p.model)
        assert a in have and b in have, (w.id, a in have, b in have)
        for part in (a, b):
            assert part.split(".")[0] in ("base", "form", p.model), (w.id,
                                                                     part)


def test_render_macros():
    s = W.expand("  @PLOOP to(a) from(b) tofrom(host_flag) private(t)\n"
                 "  @END_PLOOP\n  @HOSTFLAG", "acc")
    assert "!$acc parallel loop copyin(a) copyout(b) copy(host_flag) " \
        "private(t)" in s
    assert "acc_on_device(acc_device_host)" in s
    s = W.expand("  @REGION to(a)\n  @END_REGION\n  @ATOMIC", "omp")
    assert "!$omp target map(to: a)" in s and "!$omp end target" in s
    assert "!$omp atomic" in s
    long = W.expand("  @PLOOP " + " ".join(f"to(v{k})" for k in range(30)),
                    "omp")
    assert all(len(ln) <= 132 for ln in long.splitlines())
    assert "!$omp& " in long


def test_mutants_change_the_program():
    for w in WIDE:
        assert w.mutant_source, w.id
        assert w.mutant_source != w.program.source
        assert f"MUTANT of {w.id}" in w.mutant_source


def test_scope_and_rules():
    """The offload scope and the catalog's restriction rules (no
    compiler)."""
    bad = [(w.id, W.rule_problems(w.program)) for w in WIDE]
    assert [b for b in bad if b[1]] == []


@pytest.mark.gfortran
def test_base_language():
    if shutil.which("gfortran") is None or shutil.which("gcc") is None:
        pytest.skip("gfortran or gcc not found")
    with ThreadPoolExecutor(16) as ex:
        bad = list(ex.map(lambda w: (w.id, W.static_problems(w.program)),
                          WIDE))
    assert [b for b in bad if b[1]] == []


def _amd_ok() -> bool:
    from pathlib import Path
    return Path(W._amd_bin(), "amdflang").exists()


@pytest.mark.gfortran
def test_elision_gives_pass_and_mutants_fail():
    """Sequential elision (the expected value's second source) prints
    check=pass for every program, and the oracle mutant fails it, except
    for a mutant whose failure needs a device (a race, copy semantics)."""
    if shutil.which("gfortran") is None or not _amd_ok():
        pytest.skip("gfortran or AFAR not found")
    with ThreadPoolExecutor(16) as ex:
        ev = list(ex.map(W.elision, WIDE))
    assert [(w.id, e) for w, e in zip(WIDE, ev)
            if e.get("value") != "check=pass"] == []

    def mut(w):
        p = dataclasses.replace(w.program, source=w.mutant_source)
        return W.run_elided(p, "gcc" if p.lang == "c" else "gfortran")[0]
    with ThreadPoolExecutor(16) as ex:
        mv = list(ex.map(mut, WIDE))
    for w, v in zip(WIDE, mv):
        if w.spec.mutant_device:
            assert v == "check=pass", w.id
        else:
            assert v == "check=fail", (w.id, v)


def test_dev_misses_are_covered():
    """The dev half's misses (dev cases only)
    that name a catalog program have one."""
    atoms = {(w.program.lang, w.program.model, w.program.primary_atom)
             for w in WIDE}
    want = [("fortran", "omp", "base.device.stop"),
            ("fortran", "omp", "base.device.optional_absent"),
            ("fortran", "omp", "omp.directive.critical"),
            ("fortran", "omp", "omp.directive.parallel_sections"),
            ("fortran", "omp", "base.device.allocate_derived"),
            ("fortran", "omp", "base.device.intrinsic_modulo_int8"),
            ("fortran", "omp", "base.device.private_array_dynamic"),
            ("c", "omp", "base.device.private_array_dynamic"),
            ("fortran", "omp", "form.omp.declare_mapper_extended_type"),
            ("fortran", "omp", "pair.omp.clause.lastprivate+"
             "base.device.parallel_in_seq_loop"),
            ("fortran", "omp", "pair.omp.clause.defaultmap.present+"
             "base.device.private_array"),
            ("c", "omp", "pair.omp.clause.allocate+omp.clause.firstprivate"),
            ("fortran", "acc", "pair.base.device.loop_in_routine+"
             "base.device.sequence_association")]
    assert [x for x in want if x not in atoms] == []


def test_specs_cite_text():
    for s in WP.F_SPECS + WP.C_SPECS:
        assert s.spec and s.feature


def test_confirmer_regenerates_widened_programs():
    """The confirmer (and the knowledge base's shape check) get a widened
    program by id, as a catalog program; its C port pairs with it."""
    from offload.engine.confirm import ingest
    from offload.engine.confirm import programs as P
    p = P.catalog_program("omp52-w-block")
    assert p is not None and p.source == W.program("omp52-w-block").source
    ref = P.catalog_ref("omp52-c-w-private-array")
    assert ref.lang == "c" and ref.version == 52 and ref.text
    assert P.catalog_ref("acc34-w-block").model == "acc"
    assert P.port_of("omp52-w-private-array") == "omp52-c-w-private-array"
    assert "widen/matrix.jsonl" in ingest.FULL_FILES


def _tools_widen():
    import importlib.util
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent.parent / "tools" / "campaigns" / "widen.py"
    spec = importlib.util.spec_from_file_location("tools_widen", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _row(pid, tc, x, outcome="correct_on_device", out="RESULT ran_on_host=0 "
         "check=pass"):
    w = W.by_id()[pid]
    return {"program_id": pid, "primary_atom": w.program.primary_atom,
            "toolchain": tc, "xnack": x, "outcome": outcome,
            "stdout": out, "reason": "" if outcome == "correct_on_device"
            else "check_fail: ran_on_host=0 check=fail"}


def test_audit_summary_dispositions():
    T = _tools_widen()
    mk = lambda pid, tc, st, orig="correct_on_device", m="oracle": {  # noqa
        "program_id": pid, "toolchain": tc, "xnack": 0, "mutant": m,
        "status": st, "original": orig}
    rows = [mk("omp52-w-block", "afar", "killed"),
            mk("omp52-w-block", "cce19", "survived"),
            mk("omp52-w-stop-unreached", "afar", "survived"),
            mk("omp52-w-task", "afar", "inconclusive", "rejected"),
            mk("omp52-w-block", "afar", "survived", m="map-drop_map")]
    s = T.audit_summary(rows)["f90"]["versions"]["52"]
    assert s["base.device.block"]["disposition"] == "valid"
    assert s["base.device.block"]["map"] == {"drop_map": {"afar|0":
                                                          "survived"}}
    assert s["base.device.stop"]["disposition"] == "weak"
    assert s["omp.directive.task"]["disposition"] == \
        "unaudited_no_passing_original"


def test_expected_records_trusted_by_oracle_and_elision():
    import sys
    from pathlib import Path
    T = _tools_widen()
    sys.path.insert(0, str(Path(T.__file__).parent))
    import expected as TE
    pid = "omp52-w-block"
    matrix = [_row(pid, "afar", 1), _row(pid, "cce19", 1, "wrong_answer",
                                         "RESULT ran_on_host=0 check=fail"),
              _row(pid, "afar", 0)]
    el = {pid: {"tag": "elision", "status": "value", "value": "check=pass",
                "detail": "", "observations": [["gfortran", "check=pass"]],
                "witnesses": []}}
    recs = T.expected_records(matrix, el, {})
    r1 = next(r for r in recs[1] if r["program"] == pid)
    assert r1["key"] == f"52:{pid}" and r1["kind"] == "catalog"
    assert {r["toolchain"]: r["value"] for r in r1["runs"]} == {
        "afar": "check=pass", "cce19": "check=fail"}
    assert TE.evaluate(r1)[1].status == "trusted"
    r0 = next(r for r in recs[0] if r["program"] == pid)
    assert r0["elision"] is None and len(r0["runs"]) == 1


def test_confirmer_elision_of_a_widened_c_program(monkeypatch):
    """A widened program's elision is its stored record's (tools/campaigns/widen.py
    expected), also for C (gcc and amdclang without OpenMP), which the
    Fortran-only elision analysis does not cover."""
    from offload.engine.confirm import collectors as C
    from offload.engine.confirm import ingest as I
    from offload.engine.confirm import programs as P
    from offload.engine.confirm.model import Case
    from offload.engine.confirm.store import Store
    pid = "omp52-c-w-allocate-const-firstprivate"
    rec = {"kind": "catalog", "program": pid, "elision": {
        "tag": "elision", "status": "value", "value": "check=pass",
        "detail": "", "observations": [["gcc", "check=pass"],
                                       ["amdclang", "check=pass"]],
        "witnesses": []}}
    monkeypatch.setattr(C, "_expected_records",
                        lambda: {("catalog", pid): (rec, None, None, "x")})
    case = Case(P.catalog_ref(pid), "afar", "tuolumne", "gfx942", "copy",
                "wrong_answer", "check_fail", "check=fail")
    ctx = C.Context(I.Index(), Store(None))
    ev = C.Elision().collect(case, ctx)[0]
    assert ev.status == "value" and ev.value == "check=pass"


def test_nvidia_dispositions_per_toolchain_and_mode():
    T = _tools_widen()
    summ = {"versions": {"52": {"base.device.block": {"oracle": {
        "nvhpc|0": "killed", "afar|0": "survived"}},
        "base.device.stop": {"oracle": {"nvhpc|0": "inconclusive"}}}}}
    assert T.nv_dispositions(summ, "nvhpc", 0) == {
        (52, "base.device.block"): "valid",
        (52, "base.device.stop"): "unaudited_no_passing_original"}
    # 26.9 reuses 25.11's audit; another mode has none
    assert T.nv_dispositions(summ, "nvhpc269", 0)[
        (52, "base.device.block")] == "valid"
    assert T.nv_dispositions(summ, "nvhpc", 2) == {}


def test_interactions_need_both_parts_passing():
    T = _tools_widen()
    pid = "omp52-w-collapse-private-array"
    m = [{"program_id": pid, "toolchain": "afar", "xnack": 1,
          "outcome": "wrong_answer"},
         {"program_id": pid, "toolchain": "cce19", "xnack": 1,
          "outcome": "wrong_answer"},
         {"program_id": pid, "toolchain": "cce20", "xnack": 1,
          "outcome": "correct_on_device"}]
    parts = {("f90", "omp", "omp.clause.collapse"): {("afar", 1): True,
                                                      ("cce19", 1): True},
             ("f90", "omp", "base.device.private_array"): {
                 ("afar", 1): True, ("cce19", 1): False}}
    got = {x["toolchain"]: x["interaction"] for x in T.interactions(m, parts)}
    assert got == {"afar": True, "cce19": False}


def test_gate_names_the_widened_generator():
    from offload.engine.confirm import legality as L
    from offload.engine.confirm import programs as P
    assert "offload.engine.widen" in L.gate(P.catalog_ref("omp52-w-block")).basis
    assert "offload.engine.gen" in L.gate(
        P.catalog_ref("omp52-clause-collapse")).basis
