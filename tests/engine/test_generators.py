"""Tests of the OpenACC and OpenMP 5.0 C slices, the grammar, skeleton and rules, the oracle mutation audit, the restriction inventory and the kernel idiom miner."""


# ---- The OpenACC C slice (offload.engine.acc_c_gen): the C ports --------------------------------------

import re
import shutil

import pytest

from offload.engine import acc_c_gen as A
from offload.engine import catalog
from offload.engine import gen as G
from offload.engine.grammar import parse_directive
from offload.engine.rules import parse_program, violations


def test_c_atoms_are_the_fortran_atoms_but_eqv_neqv():
    f = set(catalog.slice_atoms(34))
    c = set(A.c_atoms())
    assert f - c == {"acc.clause.reduction.eqv", "acc.clause.reduction.neqv"}
    assert c <= f


def test_c_pragma_acc_parses():
    d = parse_directive("#pragma acc parallel loop copyin(a[0:n]) "
                        "reduction(&&: s)", "c", 34)
    assert d.name == "parallel loop"
    assert {"acc.clause.reduction.and", "acc.clause.copyin"} <= d.atoms
    with pytest.raises(Exception):
        parse_directive("#pragma omp parallel", "c", 34)


def test_every_c_atom_has_a_program():
    progs = A.all_acc_c_programs()
    legal = {p.primary_atom for p in progs if p.legal}
    assert legal == set(A.c_atoms()) - set(A.UNGENERATABLE)
    assert all(p.id.startswith("acc34-c-") and p.lang == "c"
               and p.model == "acc" for p in progs)
    illegal = [p for p in progs if not p.legal]
    assert len(illegal) == len(A.violation_ids())
    for p in illegal:
        tree = parse_program(p.source, 34, lang="c")
        assert violations(tree, 34) == [p.violates]


def test_ports_keep_the_fortran_oracle():
    """Each C program carries its Fortran program's evidence, needs and
    expectation."""
    for atom in A.c_atoms():
        c, f = A.acc_c_legal(atom), G._legal(atom, 34)
        assert (c.evidence, c.needs, c.expect, c.observable) == \
            (f.evidence, f.needs, f.expect, f.observable), atom
        assert "RESULT ran_on_host=%d check=%s" in c.source


def test_c_forms():
    src = A.acc_c_legal("acc.clause.reduction.ieor").source
    assert "reduction(^: " in src
    assert "#pragma acc routine seq\nint dev_val(int x) {" in \
        A.acc_c_legal("acc.clause.bind").source
    assert re.search(r"acc_is_present\(\w+, sizeof\(\w+\)\)",
                     "".join(A.acc_c_legal(a).source for a in A.c_atoms()))
    att = A.acc_c_legal("acc.clause.attach").source
    assert "attach(h.v)" in att and "copyin(h.v[0:n])" in att
    cap = A.acc_c_legal("acc.clause.capture").source
    assert re.search(r"#pragma acc atomic capture\n\s*\{\n", cap)
    assert "cache(a[i - 1:1])" in A.acc_c_legal("acc.directive.cache").source
    # the atomic update in a C form (x += expr), not x = x + e1 + e2
    gang = A.acc_c_legal("acc.clause.gang").source
    assert "#pragma acc atomic update\n      b[i - 1] += 2 * a[i - 1] + 1;" \
        in gang


def test_binop_form_kept_beside_the_compound_form():
    """x = x + e1 + e2 is a legal 3.4 §2.12 atomic update
    (x binop expr mathematically equivalent to x binop (expr)); the port's
    form is kept as its own program next to the x += expr one."""
    progs = {p.id: p for p in A.all_acc_c_programs()}
    for pid in ("acc34-c-clause-gang", "acc34-c-clause-gang-dim",
                "acc34-c-directive-loop"):
        comp, kept = progs[pid], progs[pid + "-binop"]
        assert kept.legal and kept.primary_atom == comp.primary_atom
        assert (kept.evidence, kept.expect) == (comp.evidence, comp.expect)
        assert "b[i - 1] = b[i - 1] + 2 * a[i - 1] + 1;" in kept.source
        assert "+= " not in kept.source.split("int main")[1]
        assert "mathematically equivalent" in kept.source
        assert "not a C form" not in comp.source
    assert not any(p.id.endswith("-binop") for p in progs.values()
                   if not p.legal)


def test_cache_at_the_top_of_the_loop_body():
    """3.4 §2.10: the cache directive "at the top of
    (inside of) a loop", in the Fortran program and its C port."""
    f = G._legal("acc.directive.cache", 34).source.splitlines()
    k = next(i for i, ln in enumerate(f) if ln.strip() == "do i = 1, n"
             and "parallel loop" in f[i - 1])
    assert f[k + 1].strip() == "!$acc cache(a(i:i))"
    c = A.acc_c_legal("acc.directive.cache").source.splitlines()
    k = next(i for i, ln in enumerate(c) if ln.strip().startswith(
        "for (int i = 1; i <= n; i++) {") and "parallel loop" in c[i - 1])
    assert c[k + 1].strip() == "#pragma acc cache(a[i - 1:1])"


def test_fortran_only_rules_do_not_hold_in_c():
    from offload.engine.rules import acc_rules
    f90 = {r.id for r in acc_rules() if r.lang == "f90"}
    assert {"ACC34-deviceptr-clause-001",
            "ACC34-declare-placement-001"} <= f90
    assert "ACC34-declare-placement-001" in A.NO_VARIANT


@pytest.mark.skipif(not shutil.which("gcc"), reason="needs gcc")
def test_programs_are_c11():
    for p in A.all_acc_c_programs():
        ok, out = A.gcc_check(p.source)
        assert ok, (p.id, out)


def test_mutants_of_c_programs():
    from offload.engine import mutate as M
    progs = M.audit_programs(34, lang="c")
    assert progs and all(p.lang == "c" for p in progs)
    # one program per atom: the -binop companions (same oracle as their
    # compound twin, which the audit covers) are not audited
    assert not any(p.id.endswith("-binop") for p in progs)
    assert len({p.primary_atom for p in progs}) == len(progs)
    for p in progs:
        m = M.neutralise(p)
        assert m is None or m.source != p.source


def test_nvhpc_compiles_openacc_c():
    from offload.engine.run_matrix import for_version
    from offload.engine.toolchains import TOOLCHAINS
    tc = for_version(TOOLCHAINS["nvhpc"], 34, "c").for_mode(0)
    assert re.search(r"/nvc -acc=gpu -gpu=cc80 -gpu=mem:separate",
                     tc.compile_cmd("p.c", "p.out"))
    with pytest.raises(ValueError):
        for_version(TOOLCHAINS["cce19"], 34, "c").flags()


def test_support_table_keeps_companions_out_of_the_atom_rows(tmp_path):
    """The support table has one program per atom; the
    -binop companions get their own section, with each cell."""
    import json
    from offload.engine import report as R
    rows = [json.loads(ln) for ln in
            (R.ROOT / "results" / "acc_matrix_c.jsonl").read_text().splitlines()
            if ln.strip()]
    keep = [r for r in rows if r["program_id"] in (
        "acc34-c-clause-gang", "acc34-c-clause-gang-binop")]
    assert {r["program_id"] for r in keep} == {"acc34-c-clause-gang",
                                               "acc34-c-clause-gang-binop"}
    res = tmp_path / "m.jsonl"
    res.write_text("".join(json.dumps(r) + "\n" for r in keep))
    table = R.build_table(res, audit=None)
    assert {r.program_id for r in table} == {"acc34-c-clause-gang"}
    sec = "\n".join(R.companion_section(res))
    assert "acc34-c-clause-gang-binop" in sec and "invalid ILM" in sec
    assert R.companion_section(tmp_path / "none.jsonl") == []


# ---- The OpenMP 5.0 C slice: the C 5.0 programs ------------------------


import yaml

from offload.engine import c_gen as C
from offload.engine.rules import default_rules

ROOT = C.Path(__file__).resolve().parent.parent.parent


def test_c50_is_a_version():
    assert 50 in C.C_VERSIONS


def test_c50_atoms_are_the_c_applicable_fortran_50_atoms():
    f50 = set(catalog.slice_atoms(50))
    c50 = set(C.c_atoms(50))
    # every C 5.0 atom is a Fortran 5.0 atom (the for compounds are the do
    # compounds); nothing first defined after 5.0 slips in through a form
    assert {C.fortran_atom(a) for a in c50} <= f50
    for a in ("omp.clause.defaultmap.all", "omp.clause.defaultmap.present",
              "omp.clause.linear.step", "omp.directive.begin_declare_target"):
        assert a not in c50, a
    # the Fortran-only atoms are the only Fortran 5.0 atoms without a C one
    ported = {C.fortran_atom(a) for a in c50}
    missing = f50 - ported
    assert missing == set(C.fortran_only_atoms(50)) - ported
    assert "omp.clause.defaultmap.allocatable" in missing


def test_c50_programs_build():
    progs = C.all_c_programs(50)
    legal = {p.primary_atom for p in progs if p.legal and "-hostdev" not in p.id}
    skip = C.C_UNGENERATABLE[50]
    assert legal == set(C.c_atoms(50)) - set(skip)
    assert all(len(r) > 40 for r in skip.values())
    assert all(p.id.startswith("omp50-c-") for p in progs)
    assert all(p.source.startswith("// Generated by compliance.c_gen "
                                   "(OpenMP 5.0, C11)") for p in progs)
    illegal = [p for p in progs if not p.legal]
    assert illegal and all(p.violates.startswith("OMP50-") for p in illegal)


def test_c50_device_type_keeps_to():
    """5.0 has no enter clause (5.2 §B.2: enter is new in 5.2): the 5.0 C
    device_type programs name f in to, as the Fortran ones do."""
    p = C.c_legal("omp.clause.device_type.any", 50)
    assert "#pragma omp declare target to(f)" in p.source
    assert "enter(" not in p.source
    assert "enter(f)" in C.c_legal("omp.clause.device_type.any", 52).source


def test_c50_uses_allocators_traits_is_the_50_form():
    p = C.c_legal("omp.clause.uses_allocators.traits", 50)
    assert re.search(r"uses_allocators\(my_alloc\(my_traits\)\)", p.source)


def test_c_rules_have_their_50_sentence():
    rules = yaml.safe_load((ROOT / "catalog" / "omp" / "rules.yaml")
                           .read_text())["rules"]
    for e in rules:
        if e.get("lang") != "c" or 52 not in e["spec"]:
            continue
        if e["id"] in C.C_RULES_NOT_50:
            assert 50 not in e["spec"]
            continue
        s = e["spec"][50]
        assert s["citation"].startswith("OpenMP 5.0 §"), e["id"]
    r50 = {r.id for r in default_rules() if r.version == 50 and r.lang == "c"}
    assert "OMP50-canonical-loop-001" in r50


@pytest.mark.needs_spec
def test_c_rule_50_sentences_are_in_the_spec():
    from offload.engine import spec_text
    text = re.sub(r"\s+", "", " ".join(l for _, l in spec_text._lines("5.0")))
    rules = yaml.safe_load((ROOT / "catalog" / "omp" / "rules.yaml")
                           .read_text())["rules"]
    for e in rules:
        if e.get("lang") == "c" and 50 in e["spec"]:
            assert re.sub(r"\s+", "", e["spec"][50]["text"]) in text, e["id"]


def test_c50_default_is_shared_or_none():
    """C 5.0 has default(shared | none) only (5.1 §B.2): the 5.0 C slice has
    no default(private)/default(firstprivate) atom, and the ports that use
    default(private) in Fortran use default(none) with a legality oracle."""
    c50 = set(C.c_atoms(50))
    assert "omp.clause.default.private" not in c50
    assert "omp.clause.default.firstprivate" not in c50
    for a in ("omp.clause.default", "omp.clause.shared"):
        p = C.c_legal(a, 50)
        assert p.evidence == "legality"
        assert "default(none)" in p.source
        assert p.source == C.c_legal(a, 50).source
    assert "default(private)" in C.c_legal("omp.clause.shared", 52).source


def test_order_concurrent_cites_the_50_restriction():
    """The 5.0 order(concurrent) programs
    cite the 5.0 restriction, not 5.2 §10.3."""
    from offload.engine import c_gen as C
    from offload.engine import gen as G
    for atom in ("omp.clause.order", "omp.clause.order.concurrent"):
        for src in (G._legal(atom, 50).source, C.c_legal(atom, 50).source):
            head = [ln for ln in src.splitlines() if "no oracle" in ln][0]
            assert "5.2 §" not in head and "5.0 §2.9.5" in head, head
        assert "5.2 §10.3" in G._legal(atom, 52).source


# ---- test_grammar ----------------------------------------------------------------------------------------

from pathlib import Path


from offload.engine import spec_text
from offload.engine.catalog import (grammar_from_dict, load_grammar,
                                load_skeleton, slice_atoms, slice_clauses,
                                slice_directives)
from offload.engine.grammar import GrammarError, parse_directive

ROOT_3 = Path(__file__).resolve().parent.parent.parent
CLAUSES = ROOT_3 / "catalog" / "omp" / "clauses.yaml"
OVERRIDES = ROOT_3 / "catalog" / "omp" / "spec_overrides.yaml"
F = "Fortran"


def code_of(text, version=52, lang=F):
    with pytest.raises(GrammarError) as err:
        parse_directive(text, lang, version)
    return err.value.code


# --- the brief's tests -------------------------------------------------------

@pytest.mark.parametrize("version", [52, 60])
def test_map_with_modifiers(version):
    d = parse_directive("!$omp target data map(always, close, to: a, b)",
                        F, version)
    assert d.name == "target data"
    [m] = d.clauses
    assert (m.name, m.args, m.modifiers) == ("map", ["a", "b"],
                                             ["always", "close", "to"])
    assert {"omp.directive.target_data", "omp.clause.map",
            "omp.clause.map.always", "omp.clause.map.close",
            "omp.clause.map.to"} <= d.atoms


@pytest.mark.parametrize("version", [52, 60])
def test_continuation_and_case(version):
    text = ("!$OMP TARGET TEAMS DISTRIBUTE &\n"
            "!$omp& PARALLEL DO COLLAPSE(2)  ! note\n")
    d = parse_directive(text, F, version)
    assert d.name == "target teams distribute parallel do"
    assert [(c.name, c.args) for c in d.clauses] == [("collapse", ["2"])]
    assert "omp.directive.target_teams_distribute_parallel_do" in d.atoms


@pytest.mark.parametrize("version", [52, 60])
def test_end_directive(version):
    d = parse_directive("!$omp end target data", F, version)
    assert (d.name, d.end, d.clauses) == ("target data", True, [])


def test_rejects_repeated_once_clause():
    assert code_of("!$omp teams num_teams(4) num_teams(8)") == "clause_repeated"


def test_wrong_language():
    assert code_of("!$omp parallel for") == "wrong_language"


def test_version_gate():
    assert code_of("!$omp target_data map(to: a)", 52) == "version"
    assert parse_directive("!$omp target_data map(to: a)", F, 60).name == \
        "target data"


def test_slice_atoms_cover_modifiers():
    atoms = slice_atoms(60)
    assert {"omp.clause.map.always", "omp.clause.map.close",
            "omp.directive.target_teams"} <= set(atoms)
    assert len(atoms) == len(set(atoms))


# --- the other error codes ---------------------------------------------------

@pytest.mark.parametrize("text,code", [
    ("!$omp frobnicate", "unknown_directive"),
    ("x = 1", "unknown_directive"),
    ("!$omp target frobnicate(1)", "unknown_clause"),
    ("!$omp target collapse(2)", "clause_not_allowed"),
    ("!$omp target data device(0)", "missing_required"),
    ("!$omp target enter data nowait", "missing_required"),
    ("!$omp target map(bogus: a)", "bad_argument"),
    ("!$omp target map()", "bad_argument"),
    ("!$omp distribute collapse", "bad_argument"),
    ("!$omp target nowait(1)", "bad_argument"),
    ("!$omp target map(to, from: a)", "bad_argument"),
    ("!$omp target map(always, always, to: a)", "bad_argument"),
    ("!$omp target map(to, always: a)", "bad_argument"),
    ("!$omp target uses_allocators(a; b)", "bad_argument"),
    ("!$omp target data map(to: a) default(none)", "version"),
    ("!$omp end target enter data", "unknown_directive"),
    ("!$omp end target data map(to: a)", "clause_not_allowed"),
    ("!$omp taskloop grainsize(4) num_tasks(2)", "clause_not_allowed"),
])
def test_error_codes(text, code):
    assert code_of(text, 52) == code


def test_required_means_at_least_one_of():
    d = parse_directive("!$omp target data use_device_addr(p)", F, 52)
    assert [c.name for c in d.clauses] == ["use_device_addr"]


def test_error_carries_message():
    with pytest.raises(GrammarError, match="num_teams"):
        parse_directive("!$omp teams num_teams(4) num_teams(8)", F, 52)


# --- Fortran line forms ----------------------------------------------------

@pytest.mark.parametrize("version", [52, 60])
@pytest.mark.parametrize("text", [
    "c$omp target", "C$OMP TARGET", "*$omp target", "c$omp target\nc$omp+ map(a)",
    "!$omp target &\nc$omp& map(a)",
])
def test_fixed_form_sentinel_rejected(text, version):
    with pytest.raises(GrammarError) as e:
        parse_directive(text, F, version)
    assert e.value.code == "fixed_form"


def test_fixed_form_sentinel_needs_column_1():
    # Indented c$omp is not a fixed-form sentinel; it is just not a sentinel.
    assert code_of("  c$omp target") == "unknown_directive"


def test_bang_sentinel_is_free_form():
    assert parse_directive("!$omp target", F, 52).name == "target"


def test_free_form_token_split_across_lines():
    d = parse_directive("!$omp teams num_&\n!$omp&teams(4)", F, 52)
    assert [c.name for c in d.clauses] == ["num_teams"]


def test_free_form_indented_and_comma_separated():
    d = parse_directive("  !$omp target map(to: a), &\n   !$omp&  nowait",
                        F, 52)
    assert [c.name for c in d.clauses] == ["map", "nowait"]


def test_comment_bang_inside_string_kept():
    d = parse_directive('!$omp parallel do message("hi! there") ! c', F, 60)
    assert d.clauses[0].args == ['"hi! there"']


def test_array_sections_and_components():
    d = parse_directive("!$omp target map(to: a(1:n), s%x(:)) map(b)", F, 52)
    assert d.clauses[0].args == ["a(1:n)", "s%x(:)"]
    assert d.clauses[1].args == ["b"] and d.clauses[1].modifiers == []


def test_declare_target_forms():
    d = parse_directive("!$omp declare target (a, b)", F, 52)
    assert (d.name, d.args) == ("declare target", ["a", "b"])
    d = parse_directive("!$omp declare target enter(f) device_type(nohost)",
                        F, 52)
    assert "omp.clause.device_type.nohost" in d.atoms
    assert parse_directive("!$omp declare_target(a)", F, 60).args == ["a"]


def test_duplicate_clause_record_picked_by_directive():
    # metadirective's default is the DefaultVariant record, not the
    # data-sharing default (valid 5.0-5.1), so the data-sharing grammar
    # must not apply.
    d = parse_directive("!$omp metadirective default(parallel do)", F, 51)
    assert d.clauses[0].args == ["parallel do"]
    assert code_of("!$omp teams default(parallel do)") == "bad_argument"


def test_ordered_picked_by_context():
    assert parse_directive("!$omp ordered", F, 52).name == "ordered (Block)"
    d = parse_directive("!$omp ordered doacross(sink: i-1)", F, 52)
    assert d.name == "ordered (None)"


@pytest.mark.parametrize("text,name,end", [
    ("!$omp paralleldo shared(a,b,c)", "parallel do", False),
    ("!$omp enddo", "do", True),
    ("!$omp end paralleldo", "parallel do", True),
    ("!$omp targetteams num_teams(4)", "target teams", False),
    ("!$omp targetteamsdistribute parallel do", "target teams distribute "
     "parallel do", False),
])
def test_optional_blanks_in_fortran_directive_names(text, name, end):
    d = parse_directive(text, F, 52)
    assert (d.name, d.end) == (name, end)


def test_free_form_name_glued_to_clause_rejected():
    # Blanks between a name and its first clause are significant in free form.
    assert code_of("!$omp targetnowait") == "unknown_directive"
    assert code_of("!$omp paralleldoshared(a,b,c)") == "unknown_directive"


def test_unknown_run_together_name_still_rejected():
    assert code_of("!$omp paralleldox") == "unknown_directive"
    assert code_of("!$omp targetfoo map(a)") == "unknown_directive"
    assert code_of("!$omp endfoo") == "unknown_directive"


def test_comment_and_blank_lines_between_continuations():
    d = parse_directive("!$omp target &\n! a comment\n\n   !$omp& map(a)",
                        F, 52)
    assert [c.name for c in d.clauses] == ["map"]


# --- spec overrides of the skeleton --------------------------------------------

def test_override_to_on_declare_target_ends_at_52():
    d = parse_directive("!$omp declare target to(a)", F, 52)
    assert d.clauses[0].name == "to"
    assert code_of("!$omp declare target to(a)", 60) == "version"
    assert "omp.clause.to" in slice_atoms(60)  # still on target update


def test_override_removes_allocator_on_target_parallel_do():
    for version in (52, 60):
        assert code_of("!$omp target parallel do allocator(a)", version) == \
            "clause_not_allowed"
        atoms = slice_atoms(version)
        assert not [a for a in atoms if a.startswith("omp.clause.allocator")]


@pytest.mark.parametrize("version", [52, 60])
def test_override_adds_allocate_and_thread_limit_to_target_parallel_do(
        version):
    d = parse_directive("!$omp target parallel do allocate(a) "
                        "thread_limit(64) private(a)", F, version)
    assert [c.name for c in d.clauses] == ["allocate", "thread_limit",
                                           "private"]
    assert code_of("!$omp target parallel do thread_limit(4) "
                   "thread_limit(8)", version) == "clause_repeated"
    assert code_of("!$omp target parallel do allocator(a)", version) == \
        "clause_not_allowed"
    sk = load_skeleton(ROOT_3 / "catalog" / "omp" / "skeleton.yaml")
    allowed = load_grammar(CLAUSES).allowed(sk, "target parallel do")
    assert "allocator" not in allowed
    assert (allowed["allocate"].min_ver, allowed["allocate"].once) == (50,
                                                                       False)
    assert (allowed["thread_limit"].min_ver,
            allowed["thread_limit"].once) == (51, True)
    atoms = slice_atoms(version)
    assert {"omp.clause.allocate", "omp.clause.allocate.allocator",
            "omp.clause.thread_limit"} <= set(atoms)
    assert len(atoms) == len(set(atoms)) and atoms == sorted(atoms)


@pytest.mark.parametrize("bad", [
    {"clause_rules": [{"directive": "target paralel do", "clause": "allocate",
                       "add": True, "citation": "x", "status": "provisional"}]},
    {"clause_rules": [{"directive": "target", "clause": "alocate",
                       "remove": True, "citation": "x",
                       "status": "provisional"}]},
    {"clause_rules": [{"directive": "target", "clause": "collapse",
                       "remove": True, "citation": "x",
                       "status": "provisional"}]},
    {"clause_rules": [{"directive": "target", "clause": "map", "add": True,
                       "citation": "x", "status": "provisional"}]},
    {"directive_spellings": [{"directive": "target dta", "spelling": "x",
                              "since": 60, "citation": "x",
                              "status": "provisional"}]},
    {"directive_versions": [{"directive": "workdistrbute", "since": 60,
                             "citation": "x", "status": "provisional"}]},
    {"directive_versions": [{"directive": "target loop", "since": 60,
                             "citation": "x", "status": "provisional"}] * 2},
    {"directive_versions": [{"directive": "target", "since": 0,
                             "citation": "x", "status": "provisional"}]},
])
def test_bad_override_is_rejected(bad):
    sk = load_skeleton(ROOT_3 / "catalog" / "omp" / "skeleton.yaml")
    data = yaml.safe_load(CLAUSES.read_text())
    with pytest.raises(ValueError, match="spec override"):
        grammar_from_dict(data, bad, sk)


@pytest.mark.parametrize("version", [52, 60])
def test_override_adds_thread_limit_to_target_parallel_do_simd(version):
    d = parse_directive("!$omp target parallel do simd thread_limit(4)", F,
                        version)
    assert [c.name for c in d.clauses] == ["thread_limit"]


@pytest.mark.parametrize("directive", ["target loop", "target simd"])
def test_override_adds_default_to_target_loop_and_target_simd(directive):
    # The target leaf permits default only from 6.0 (6.0 §7.5.1), so the
    # compound gets it from 60 and raises version (not clause_not_allowed)
    # at 52, exactly like the target leaf itself.
    d = parse_directive(f"!$omp {directive} default(none)", F, 60)
    assert [(c.name, c.args) for c in d.clauses] == [("default", ["none"])]
    assert {"omp.clause.default", "omp.clause.default.none"} <= d.atoms
    assert code_of(f"!$omp {directive} default(none)", 52) == "version"
    assert code_of("!$omp target default(none)", 52) == "version"
    assert code_of(f"!$omp {directive} default(none) default(shared)",
                   60) == "clause_repeated"
    # The data-sharing record, not metadirective's DefaultVariant one, is
    # the one added: its 6.0 grammar applies.
    d = parse_directive(f"!$omp {directive} default(private: scalar)", F, 60)
    assert d.clauses[0].modifiers == ["scalar"]
    assert "omp.clause.default.scalar" in d.atoms
    assert code_of(f"!$omp {directive} default(parallel do)", 60) == \
        "bad_argument"
    sk = load_skeleton(ROOT_3 / "catalog" / "omp" / "skeleton.yaml")
    rule = load_grammar(CLAUSES).allowed(sk, directive)["default"]
    assert (rule.min_ver, rule.max_ver, rule.once) == (60, None, True)


@pytest.mark.parametrize("version", [52, 60])
def test_override_widens_default_on_target_teams_distribute_simd(version):
    # TableGen gives the compound default only from 6.0, but the teams leaf
    # permits it at every version (5.2 §5.4.1) and so does its sibling
    # target teams distribute; the override widens the range.
    for directive in ("target teams distribute simd",
                      "target teams distribute"):
        d = parse_directive(f"!$omp {directive} default(none)", F, version)
        assert [(c.name, c.args) for c in d.clauses] == [("default",
                                                           ["none"])]
        assert "omp.clause.default.none" in d.atoms
        assert code_of(f"!$omp {directive} default(none) default(none)",
                       version) == "clause_repeated"
    # version-specific syntax follows the data-sharing default grammar
    line = "!$omp target teams distribute simd default(firstprivate: scalar)"
    if version == 60:
        assert parse_directive(line, F, 60).clauses[0].modifiers == ["scalar"]
    else:
        assert code_of(line, 52) == "bad_argument"
    sk = load_skeleton(ROOT_3 / "catalog" / "omp" / "skeleton.yaml")
    rule = load_grammar(CLAUSES).allowed(sk, "target teams distribute simd")[
        "default"]
    assert (rule.min_ver, rule.max_ver, rule.once) == (1, None, True)


def test_override_since_until_replace_the_skeleton_bounds():
    sk = load_skeleton(ROOT_3 / "catalog" / "omp" / "skeleton.yaml")
    data = yaml.safe_load(CLAUSES.read_text())
    base = sk.directive("target teams distribute simd").allowed["default"]
    assert base.min_ver == 60
    entry = {"directive": "target teams distribute simd", "clause": "default",
             "citation": "x", "status": "provisional"}
    widened = grammar_from_dict(data, {"clause_rules": [dict(entry, since=52)]},
                                sk).allowed(sk, "target teams distribute simd")
    assert widened["default"].min_ver == 52  # not max(60, 52)
    narrowed = grammar_from_dict(data, {"clause_rules": [dict(entry, until=60)]},
                                 sk).allowed(sk, "target teams distribute simd")
    assert (narrowed["default"].min_ver, narrowed["default"].max_ver) == (60,
                                                                          60)
    with pytest.raises(ValueError, match="version range unchanged"):
        grammar_from_dict(data, {"clause_rules": [dict(entry, since=60)]}, sk)


def test_duplicate_override_is_rejected():
    sk = load_skeleton(ROOT_3 / "catalog" / "omp" / "skeleton.yaml")
    data = yaml.safe_load(CLAUSES.read_text())
    entry = {"directive": "target", "clause": "map", "until": 52,
             "citation": "x", "status": "provisional"}
    with pytest.raises(ValueError, match="spec override: duplicate"):
        grammar_from_dict(data, {"clause_rules": [entry, dict(entry)]}, sk)
    with pytest.raises(ValueError, match="spec override"):
        grammar_from_dict(data, {"clause_rules": [
            {"directive": "target", "clause": "map", "citation": "x",
             "status": "provisional"}]}, sk)


def test_parser_is_cached_but_follows_a_reloaded_catalog():
    from offload.engine import grammar as g
    sk = load_skeleton(ROOT_3 / "catalog" / "omp" / "skeleton.yaml")
    gr = load_grammar(CLAUSES)
    first = g._parser(sk, gr, "Fortran", 52)
    assert g._parser(sk, gr, "Fortran", 52) is first
    gr2 = load_grammar(CLAUSES)
    assert g._parser(sk, gr2, "Fortran", 52) is not first
    d = parse_directive("!$omp target", F, 52, skeleton=sk, grammar=gr2)
    assert d.name == "target"


# --- 5.2 versus 6.0 clause syntax ------------------------------------------

def test_map_type_storage_is_60_only():
    assert code_of("!$omp target map(storage: a)", 52) == "bad_argument"
    d = parse_directive("!$omp target map(storage: a)", F, 60)
    assert "omp.clause.map.storage" in d.atoms
    d = parse_directive("!$omp target map(to, always: a)", F, 60)
    assert d.clauses[0].modifiers == ["to", "always"]


def test_map_modifiers_without_commas_52():
    d = parse_directive("!$omp target map(always to: a)", F, 52)
    assert d.clauses[0].modifiers == ["always", "to"]


def test_uses_allocators_specs_60():
    d = parse_directive("!$omp target uses_allocators(traits(t): a; b)", F, 60)
    assert d.clauses[0].args == ["a", "b"]
    assert "omp.clause.uses_allocators.traits" in d.atoms


def test_num_teams_lower_bound():
    d = parse_directive("!$omp teams num_teams(2: 8)", F, 52)
    assert d.clauses[0].args == ["8"] and d.clauses[0].modifiers == ["2"]
    assert "omp.clause.num_teams.lower_bound" in d.atoms


def test_reduction_identifiers():
    d = parse_directive("!$omp teams reduction(+: s) reduction(max: m)", F, 60)
    assert {"omp.clause.reduction.plus", "omp.clause.reduction.max"} <= d.atoms
    assert parse_directive("!$omp teams reduction(-: s)", F, 52).clauses
    assert code_of("!$omp teams reduction(-: s)", 60) == "bad_argument"
    assert code_of("!$omp teams reduction(s)", 52) == "bad_argument"


def test_schedule_and_dist_schedule():
    d = parse_directive("!$omp target teams distribute parallel do "
                        "dist_schedule(static, 4) "
                        "schedule(nonmonotonic: dynamic, 8)", F, 52)
    assert {"omp.clause.dist_schedule.static",
            "omp.clause.dist_schedule.chunk_size",
            "omp.clause.schedule.nonmonotonic",
            "omp.clause.schedule.dynamic"} <= d.atoms


def test_directive_name_modifier():
    d = parse_directive("!$omp target parallel do if(target: n > 1)", F, 52)
    assert "omp.clause.if.directive_name" in d.atoms
    d = parse_directive("!$omp target teams thread_limit(teams: 64)", F, 60)
    assert "omp.clause.thread_limit.directive_name" in d.atoms
    assert code_of("!$omp target teams thread_limit(teams: 64)", 52) == \
        "bad_argument"


@pytest.mark.parametrize("version", [52, 60])
def test_directive_name_modifier_blanks_optional_in_fortran(version):
    # a directive-name modifier is a directive-name, so in Fortran its
    # blanks are optional too (5.2 §3.1.2, p.55; deprecated in 6.0 §5.1.1).
    # From the corpus: llvm flang/test/Parser/OpenMP/if-clause-unparse.f90:18
    d = parse_directive("!$omp target update if(targetupdate: cond) to(a)",
                        F, version)
    assert "omp.clause.if.directive_name" in d.atoms
    assert code_of("#pragma omp target update if(targetupdate: c) to(a)",
                   version, "C") == "bad_argument"


def test_requires():
    d = parse_directive("!$omp requires unified_shared_memory", F, 52)
    assert "omp.clause.unified_shared_memory" in d.atoms
    d = parse_directive("!$omp requires atomic_default_mem_order(seq_cst)",
                        F, 52)
    assert "omp.clause.atomic_default_mem_order.seq_cst" in d.atoms


# --- the catalog data --------------------------------------------------------

def test_every_clause_entry_is_provisional_and_cited():
    data = yaml.safe_load(CLAUSES.read_text())
    for entry in data["clauses"].values():
        assert entry["status"] == "provisional"
    for name, entry in data["clauses"].items():
        assert entry["forms"], name
        for form in entry["forms"]:
            assert re.match(r"^OpenMP (5\.0|5\.2|6\.0) §[\d.]+, p\.\d+$",
                            form["citation"]), (name, form["citation"])
    assert "reviewed" not in CLAUSES.read_text()


def test_every_slice_clause_has_a_grammar():
    grammar = load_grammar(CLAUSES)
    sk = load_skeleton(ROOT_3 / "catalog" / "omp" / "skeleton.yaml")
    for version in (52, 60):
        missing = set(slice_clauses(sk, version)) - set(grammar.clauses)
        assert not missing, (version, sorted(missing))


def test_every_override_is_provisional_and_cited():
    data = yaml.safe_load(OVERRIDES.read_text())
    entries = (data["directive_spellings"] + data["clause_rules"]
               + data["directive_versions"])
    assert len(data["clause_rules"]) >= 2
    for entry in entries:
        assert entry["status"] == "provisional"
        for cite in [entry["citation"]] + entry.get("also_cited", []):
            assert re.match(r"^OpenMP (5\.[012]|6\.0) §[\d.]+, p\.\d+$",
                            cite)
    assert "reviewed" not in OVERRIDES.read_text()


@pytest.mark.needs_spec
def test_citations_point_into_the_spec():
    data = yaml.safe_load(CLAUSES.read_text())
    over = yaml.safe_load(OVERRIDES.read_text())
    cites = [f["citation"] for e in data["clauses"].values()
             for f in e["forms"]]
    for e in (over["directive_spellings"] + over["clause_rules"]
              + over["directive_versions"]):
        cites += [e["citation"]] + e.get("also_cited", [])
    by_number = {}
    for ver in ("5.0", "5.1", "5.2", "6.0"):
        for s in spec_text.sections(ver).values():
            by_number[(ver, s.number)] = s
    for cite in cites:
        ver, num, page = re.match(r"OpenMP (\S+) §(\S+), p\.(\d+)$",
                                  cite).groups()
        sec = by_number[(ver, num)]
        assert sec.first_page <= int(page) <= sec.last_page, cite


def test_slice_atoms_deterministic_and_versioned():
    a52, a60 = slice_atoms(52), slice_atoms(60)
    assert a52 == sorted(a52) and a60 == slice_atoms(60)
    assert len(a52) == len(set(a52))
    for atom in ("omp.directive.target", "omp.directive.declare_target",
                 "omp.directive.requires", "omp.clause.map.to",
                 "omp.clause.num_teams.lower_bound"):
        assert atom in a52 and atom in a60
    assert "omp.clause.map.storage" in a60
    assert "omp.clause.map.storage" not in a52
    assert "omp.clause.default" in a52  # on parallel do etc. before 6.0
    assert not [a for a in a60 if ".ompx_" in a or "dyn_groupprivate" in a]
    assert all(re.match(r"^omp\.(directive|clause)\.[a-z0-9_.]+$", a)
               for a in a60), [a for a in a60
                               if not re.match(r"^[a-z0-9_.]+$", a)]


# --- gaps found by the corpus check ------------

@pytest.mark.parametrize("version", [52, 60])
@pytest.mark.parametrize("directive", [
    "target parallel", "target parallel do", "target parallel do simd",
    "target parallel loop", "target simd", "target teams",
    "target teams distribute", "target teams distribute parallel do",
    "target teams distribute parallel do simd",
    "target teams distribute simd", "target teams loop"])
def test_in_reduction_on_target_compounds(directive, version):
    # in_reduction applies to the target leaf (5.2 §17.2, 6.0 §19.2);
    # gcc gfortran.dg/gomp/clauses-1.f90 uses it on each of these
    d = parse_directive(f"!$omp {directive} in_reduction(+: r)", F, version)
    assert "omp.clause.in_reduction.plus" in d.atoms


@pytest.mark.parametrize("version", [52, 60])
def test_copyin_on_compounds_with_a_parallel_leaf(version):
    # gcc gfortran.dg/gomp/clauses-1.f90:396
    d = parse_directive("!$omp teams distribute parallel do simd copyin(t)",
                        F, version)
    assert [c.name for c in d.clauses] == ["copyin"]


@pytest.mark.parametrize("directive", [
    "target parallel", "target parallel do", "target parallel do simd",
    "target parallel loop", "target teams distribute parallel do",
    "target teams distribute parallel do simd"])
def test_copyin_on_target_compounds_only_from_60(directive):
    # 5.2 §17.4, p.343: "If directive-name-A is target, the copyin clause
    # must not be specified"; 6.0 §19.3 drops the restriction. The override
    # starts at 60, so 5.2 reports `version`, like any rule outside its range.
    parse_directive(f"!$omp {directive} copyin(t)", F, 60)
    assert code_of(f"!$omp {directive} copyin(t)", 52) == "version"


@pytest.mark.parametrize("directive", ["target teams", "target parallel do",
                                       "target teams loop"])
def test_replayable_on_target_compounds_60(directive):
    # 6.0 §15.8 lists replayable on target; §19.2/§19.3, no exclusion
    d = parse_directive(f"!$omp {directive} replayable(.true.)", F, 60)
    assert "omp.clause.replayable" in d.atoms
    assert code_of(f"!$omp {directive} replayable", 52) == "version"
    assert code_of(f"!$omp {directive} replayable replayable", 60) == \
        "clause_repeated"


@pytest.mark.parametrize("directive", ["target", "target teams",
                                       "target teams distribute parallel do"])
def test_device_type_on_target_constructs_60(directive):
    # 6.0 §15.8 lists device_type on target; gcc target-device-type-1.f90
    d = parse_directive(f"!$omp {directive} device_type(nohost)", F, 60)
    assert "omp.clause.device_type.nohost" in d.atoms
    assert code_of(f"!$omp {directive} device_type(nohost)", 52) == "version"
    assert code_of(f"!$omp {directive} device_type(host) device_type(host)",
                   60) == "clause_repeated"


def test_target_data_task_clauses_60():
    # 6.0 §15.7 (target_data is a composite construct); omp_examples
    # devices/sources/target_data_semantics_new.1.f90
    line = ("!$omp target_data map(a) nogroup nowait "
            "depend(target_exit_data, in: a)")
    d = parse_directive(line, F, 60)
    assert [c.name for c in d.clauses] == ["map", "nogroup", "nowait",
                                           "depend"]
    assert "omp.clause.nogroup" in d.atoms
    parse_directive("!$omp target data map(a) nogroup(.false.)", F, 60)
    assert parse_directive("!$omp end target data nowait", F, 60).end
    for clause in ("nogroup", "nowait", "depend(in: a)"):
        assert code_of(f"!$omp target data map(a) {clause}", 52) == "version"
    assert code_of("!$omp target data map(a) nogroup nogroup", 60) == \
        "clause_repeated"


@pytest.mark.parametrize("directive", ["parallel do", "distribute simd",
                                       "target teams distribute parallel do",
                                       "target simd"])
def test_induction_60(directive):
    # 6.0 §7.6.13; omp_examples data_environment/sources/induction.1.f90:21
    d = parse_directive(f"!$omp {directive} reduction(+: result) "
                        "induction(step(x),*: xi)", F, 60)
    assert {"omp.clause.induction", "omp.clause.induction.step",
            "omp.clause.induction.times"} <= d.atoms
    d = parse_directive(f"!$omp {directive} "
                        "induction(strict, step(s), next : p)", F, 60)
    assert d.clauses[0].args == ["p"]
    assert "omp.clause.induction.strict" in d.atoms
    assert code_of(f"!$omp {directive} induction(step(x),*: xi)", 52) == \
        "version"
    for bad in ("induction(*: xi)", "induction(step(x): xi)",
                "induction(*, step(x): xi)", "induction(step(x), +, *: xi)"):
        assert code_of(f"!$omp {directive} {bad}", 60) == "bad_argument", bad


@pytest.mark.parametrize("name", ["workdistribute", "teams workdistribute",
                                  "target teams workdistribute",
                                  "target loop"])
def test_directive_introduced_in_60(name):
    """TableGen has no directive-level introduction version; the spec
    overrides give it (directive_versions)."""
    assert code_of(f"!$omp {name}", 52) == "version"
    assert parse_directive(f"!$omp {name}", F, 60).name == name


@pytest.mark.parametrize("version", [52, 60])
def test_slice_directives_parse_at_both_versions(version):
    """Regression: every slice directive except those introduced in 6.0
    parses at both versions."""
    sk = load_skeleton(ROOT_3 / "catalog" / "omp" / "skeleton.yaml")
    new_in_60 = {"teams workdistribute", "target teams workdistribute",
                 "target loop"}
    for key in slice_directives(sk):
        if version < 60 and key in new_in_60:
            continue
        spec = sk.directive(key)
        text = f"!$omp {spec.spellings[0].text}"
        if spec.required:  # add one required clause
            c = "map" if "map" in spec.required else sorted(spec.required)[0]
            try:
                d = parse_directive(f"{text} {c}(a)", F, version)
            except GrammarError:
                d = parse_directive(f"{text} {c}", F, version)
        else:
            d = parse_directive(text, F, version)
        assert d.name == key


# --- semantic atoms -------------------------------------------------

def test_semantic_atom_in_slice_at_both_versions():
    from offload.engine.catalog import semantic_atoms
    sem = semantic_atoms()["omp.clause.defaultmap.character"]
    assert sem.clause == "defaultmap" and sem.status == "provisional"
    # 5.0 already excludes character type from scalar variables
    assert sem.since == 50 and set(sem.citations) == {50, 52, 60}
    assert "§1.2.6" in sem.citations[52] and "§7.9.3" in sem.citations[60]
    for v in (52, 60):
        assert "omp.clause.defaultmap.character" in slice_atoms(v)


def test_semantic_atom_follows_its_clause_and_since():
    from offload.engine.catalog import semantic_atoms_from_dict
    with pytest.raises(ValueError, match="must be"):
        semantic_atoms_from_dict({"atoms": {"omp.clause.map.character": {
            "clause": "defaultmap", "since": 52, "citations": {52: "x"},
            "status": "provisional", "behaviour": "x"}}})
    e = semantic_atoms_from_dict({"atoms": {"omp.clause.defaultmap.x": {
        "clause": "defaultmap", "since": 60, "citations": {60: "c"},
        "status": "provisional", "behaviour": "b"}}})
    assert e["omp.clause.defaultmap.x"].citations == {60: "c"}


def test_semantic_atom_is_no_syntax_feature():
    """No clause argument produces the semantic atom: a defaultmap clause
    never parses to it."""
    d = parse_directive("!$omp target defaultmap(tofrom: aggregate)", F, 52)
    assert not any(a.endswith(".character") for a in d.atoms)


# ---- test_skeleton ---------------------------------------------------------------------------------------



from offload.engine.catalog import AmbiguousSpelling
from offload.engine.skeleton import build_skeleton, load_skeleton as load_skeleton_4

ROOT_4 = Path(__file__).resolve().parent.parent.parent
SEED = ROOT_4 / "data" / "index" / "seed" / "omp.json"
SKELETON = ROOT_4 / "catalog" / "omp" / "skeleton.yaml"


@pytest.fixture(scope="module")
def sk():
    return load_skeleton_4(SKELETON)


def test_target_teams_leaves(sk):
    assert sk.directive("target teams").leaves == ["target", "teams"]


def test_target_data_respelled_at_60(sk):
    spellings = {s.text: s for s in sk.directive("target data").spellings}
    assert spellings["target_data"].min_ver == 60


def test_map_allowed_on_target(sk):
    assert "map" in sk.directive("target").allowed


def test_counts(sk):
    assert len(sk.directives) == 119
    assert len(sk.clauses) == 141


def test_lookup_respects_version(sk):
    assert sk.lookup("target_data", 52) is None
    assert sk.lookup("target_data", 60).name == "target data"


def test_committed_yaml_matches_seed(tmp_path):
    import yaml
    assert yaml.safe_load(SKELETON.read_text()) == build_skeleton(SEED)


def test_required_does_not_override_once(sk):
    for d, c, v in (("tile", "sizes", 51), ("split", "counts", 60)):
        spec = sk.directive(d)
        assert spec.allowed[c].once is True
        assert spec.allowed[c].min_ver == v
        assert c in spec.required


def test_ambiguous_spelling(sk):
    both = sk.lookup_all("ordered", 52)
    assert {s.association for s in both} == {"Block", "None"}
    with pytest.raises(AmbiguousSpelling, match="ordered"):
        sk.lookup("ordered", 52)
    assert sk.lookup_all("target_data", 52) == []
    assert [s.name for s in sk.lookup_all("target_data", 60)] == ["target data"]


def _synthetic(tmp_path, allowed, once, excl):
    import json

    def vc(n, clause, lo, hi):
        return {"!superclasses": ["Versioned", "VersionedClause"],
                "clause": {"def": clause}, "minVersion": lo, "maxVersion": hi}

    def ref(n):
        return {"def": n}

    db = {
        "anonymous_1": {"spelling": "x", "minVersion": 0,
                        "maxVersion": 2147483647},
        "anonymous_2": {"spelling": "c1", "minVersion": 0,
                        "maxVersion": 2147483647},
        "anonymous_3": {"spelling": "c2", "minVersion": 0,
                        "maxVersion": 2147483647},
        "OMPC_A": {"!superclasses": ["Clause"],
                   "spellings": [ref("anonymous_2")]},
        "OMPC_B": {"!superclasses": ["Clause"],
                   "spellings": [ref("anonymous_3")]},
        "v_plain_a": vc(0, "OMPC_A", 1, 2147483647),
        "v_once_a": vc(0, "OMPC_A", 51, 2147483647),
        "v_once_b": vc(0, "OMPC_B", 1, 2147483647),
        "v_excl_b": vc(0, "OMPC_B", 1, 60),
        "OMP_X": {"!superclasses": ["Directive"],
                  "spellings": [ref("anonymous_1")],
                  "association": {"def": "AS_Block"}, "languages": [],
                  "leafConstructs": [], "requiredClauses": [],
                  "allowedClauses": [ref(n) for n in allowed],
                  "allowedOnceClauses": [ref(n) for n in once],
                  "allowedExclusiveClauses": [ref(n) for n in excl]},
    }
    path = tmp_path / "seed.json"
    path.write_text(json.dumps(db))
    return build_skeleton(path)["directives"]["x"]["allowed"]


def test_merge_keeps_strong_flags(tmp_path):
    out = _synthetic(tmp_path, ["v_plain_a"], ["v_once_a", "v_once_b"],
                     ["v_excl_b"])
    assert out["c1"]["once"] is True
    assert out["c1"]["min_ver"] == 51
    assert out["c2"]["once"] is True
    assert out["c2"]["exclusive_group"] == "exclusive"
    assert out["c2"]["max_ver"] == 60


def test_merge_rule_is_commutative():
    from offload.engine.skeleton import merge_rule
    weak = {"min_ver": 1, "max_ver": None, "once": False,
            "exclusive_group": None}
    strong = {"min_ver": 51, "max_ver": 60, "once": True,
              "exclusive_group": "exclusive"}
    assert merge_rule(weak, strong) == merge_rule(strong, weak) == strong


# ---- Tests for offload.engine.rules: parse_program and the restriction rules -----------------------------


from offload.engine.grammar import GrammarError
from offload.engine.rules import ProgramError, parse_program


def src(*lines):
    return "\n".join(lines) + "\n"


# --- parse_program -----------------------------------------------------------

def test_parse_program_nesting():
    tree = parse_program(src(
        "program p",
        "  !$omp target",
        "  !$omp teams",
        "  x = 1",
        "  !$omp end teams",
        "  !$omp end target",
        "end program p"), 52)
    assert [d.name for d in tree.directives] == ["target", "teams"]
    assert tree.nesting == [(0, 1)]
    assert tree.ends[0].end and tree.ends[1].end
    assert tree.assoc[0].kind == "block" and tree.assoc[0].line == 2
    assert tree.assoc[0].end_line == 6
    assert tree.assoc[0].stmts == 0 and tree.assoc[1].stmts == 1


def test_parse_program_loop_association():
    tree = parse_program(src(
        "!$omp target teams distribute parallel do collapse(2) &",
        "!$omp&   map(tofrom: a)  ! a comment",
        "do i = 1, n",
        "  ! comment between loops",
        "  do j = 1, m",
        "    a(i, j) = 0",
        "  end do",
        "end do",
        "!$omp end target teams distribute parallel do",
        "!$omp parallel do",
        "do k = 1, n",
        "  b(k) = 1",
        "enddo"), 60)
    a0, a1 = tree.assoc
    assert (a0.kind, a0.loop_depth, a0.loop_vars) == ("loop", 2, ("i", "j"))
    assert a0.end_line == 9 and 0 in tree.ends
    assert (a1.loop_depth, a1.loop_vars, a1.end_line) == (1, ("k",), 13)
    assert 1 not in tree.ends and tree.nesting == []


def test_parse_program_loop_depth_stops_at_two_loops_or_while():
    tree = parse_program(src(
        "!$omp parallel do",
        "do i = 1, n",
        "  do j = 1, m",
        "  end do",
        "  do j = 1, m",
        "  end do",
        "end do",
        "!$omp parallel do",
        "do i = 1, n",
        "  do while (x > 0)",
        "  end do",
        "end do",
        "!$omp parallel do",
        "do while (x > 0)",
        "end do"), 52)
    assert [a.loop_depth for a in tree.assoc] == [1, 1, 0]


def test_parse_program_loop_directive_without_loop():
    tree = parse_program(src("!$omp parallel do", "x = 1"), 52)
    assert tree.assoc[0].loop_depth == 0


def test_parse_program_nested_loop_directive_parent():
    tree = parse_program(src(
        "!$omp target teams",
        "!$omp distribute",
        "do i = 1, n",
        "  !$omp parallel do",
        "  do j = 1, m",
        "  end do",
        "end do",
        "!$omp end target teams",
        "!$omp target update to(a)",
        "!$omp declare target (b)"), 52)
    assert tree.nesting == [(0, 1), (1, 2)]
    assert [a.kind for a in tree.assoc] == ["block", "loop", "loop",
                                            "standalone", "standalone"]


def test_parse_program_one_statement_directives():
    tree = parse_program(src(
        "!$omp parallel",
        "!$omp atomic update",
        "x = x + 1",
        "!$omp atomic",
        "y = y + 1",
        "!$omp end atomic",
        "!$omp end parallel"), 52)
    assert tree.nesting == [(0, 1), (0, 2)] and 2 in tree.ends


def test_parse_program_block_construct_structured_block():
    tree = parse_program(src(
        "!$omp target",
        "block",
        "  integer :: k",
        "  block",
        "  end block",
        "end block",
        "!$omp parallel",
        "block",
        "end block",
        "!$omp end parallel",
        "!$omp atomic capture",
        "v = x",
        "x = x + 1",
        "!$omp end atomic"), 52)
    assert tree.nesting == []
    assert [a.end_line for a in tree.assoc] == [6, 10, 14]
    assert 0 not in tree.ends and 1 in tree.ends and 2 in tree.ends
    with pytest.raises(ProgramError, match="END BLOCK"):
        parse_program(src("!$omp target", "block", "!$omp parallel",
                          "end block", "!$omp end parallel"), 52)


def test_parse_program_unpaired_end_raises():
    with pytest.raises(ProgramError, match="end teams"):
        parse_program(src("!$omp target", "x = 1", "!$omp end teams",
                          "!$omp end target"), 52)
    with pytest.raises(ProgramError, match="end target"):
        parse_program(src("x = 1", "!$omp end target"), 52)


def test_parse_program_missing_end_raises():
    with pytest.raises(ProgramError, match="never closed"):
        parse_program(src("!$omp target", "x = 1"), 52)
    with pytest.raises(ProgramError, match="still open"):
        parse_program(src("subroutine s", "!$omp teams", "x = 1",
                          "end subroutine s"), 52)


def test_parse_program_end_do_crossing_a_directive_raises():
    with pytest.raises(ProgramError, match="END DO"):
        parse_program(src("do i = 1, n", "!$omp target", "end do",
                          "!$omp end target"), 52)


def test_parse_program_unsupported_structure_raises():
    with pytest.raises(ProgramError, match="label"):
        parse_program(src("!$omp parallel do", "do 10 i = 1, n",
                          "10 continue"), 52)
    with pytest.raises(ProgramError, match="loop-transforming"):
        parse_program(src("!$omp parallel do", "!$omp tile sizes(4)",
                          "do i = 1, n", "end do"), 60)


def test_parse_program_grammar_errors_propagate():
    with pytest.raises(GrammarError):
        parse_program(src("!$omp target nosuchclause", "!$omp end target"),
                      52)


# --- the rules file ----------------------------------------------------------

import re  # noqa: E402

import yaml  # noqa: E402

from offload.engine import spec_text  # noqa: E402
from offload.engine.grammar import parse_directive  # noqa: E402
from offload.engine.rules import (RULES_PATH, Assoc, ProgramTree,  # noqa: E402
                              RuleError, association, findings, load_rules,
                              rules_from_list, violations)

RULES = load_rules()
# the C rules (lang: c) have C cases in tests/engine/test_c.py
STATIC = [r for r in RULES if r.check == "static" and r.lang != "c"]
VERSION_TEXT = {50: "5.0", 52: "5.2", 60: "6.0"}


def _section(version, citation):
    m = re.match(r"OpenMP [\d.]+ §([\d.]+), p\.(\d+)$", citation)
    number, page = m.group(1), int(m.group(2))
    secs = [s for s in spec_text.sections(VERSION_TEXT[version]).values()
            if s.number == number]
    assert len(secs) == 1, citation
    return secs[0], page


@pytest.mark.needs_spec
def test_every_rule_has_citation_and_status():
    data = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    assert all(e["status"] == "provisional" for e in data["rules"])
    for r in RULES:
        assert re.fullmatch(r"OMP(50|52|60)-[a-z0-9]+-[a-z]+-\d{3}", r.id), r.id
        assert r.status == "provisional", r.id
        assert r.check in ("static", "runtime"), r.id
        assert (r.predicate is not None) == (r.check == "static"), r.id
        assert re.fullmatch(rf"OpenMP {VERSION_TEXT[r.version]} §[\d.]+, "
                            r"p\.\d+", r.citation), r.id
        sec, page = _section(r.version, r.citation)
        assert sec.first_page <= page <= sec.last_page, (r.id, r.citation)
        flat = re.sub(r"\s+", "", sec.text)
        assert re.sub(r"\s+", "", r.text) in flat, (r.id, r.text)
        for c in r.also:
            sec, page = _section(r.version, c)
            assert sec.first_page <= page <= sec.last_page, (r.id, c)


def test_rule_counts():
    stems = {r.id.split("-", 1)[1] for r in RULES}
    assert 150 <= len(stems) <= 200  # 56 in batch 1, 99 added later
    assert {r.check for r in RULES} == {"static", "runtime"}


def test_missing_predicate_fails_at_load():
    entry = {"id": "x-clause-001", "check": "static", "status": "provisional",
             "predicate": "no_such_predicate",
             "spec": {52: {"citation": "OpenMP 5.2 §3.4, p.72", "text": "t"}}}
    with pytest.raises(RuleError, match="predicate"):
        rules_from_list([entry])
    with pytest.raises(RuleError, match="predicate"):
        rules_from_list([dict(entry, predicate=None)])
    with pytest.raises(RuleError, match="runtime"):
        rules_from_list([dict(entry, check="runtime",
                              predicate="loop_nest_follows", why="w")])
    with pytest.raises(RuleError, match="citation"):
        rules_from_list([dict(entry, predicate="loop_nest_follows", spec={
            60: {"citation": "OpenMP 5.2 §3.4, p.72", "text": "t"}})])


# --- one legal and one illegal program per static rule -----------------------

def wrap(line, version):
    """One directive in a minimal program: a block construct gets a body and
    its end directive, a loop construct a DO loop."""
    d = parse_directive(line, "fortran", version)
    how = association(d.name)
    if how == "block":
        return src(line, "x = 1", f"!$omp end {d.name}")
    if how == "loop":
        return src(line, "do i = 1, n", "  x = 1", "end do")
    return src(line)


REQ = "!$omp requires reverse_offload"


def scan(line, items="x"):
    """A loop directive with reduction(inscan, ...) and its scan directive
    (every inscan item must appear on a scan directive)."""
    return [line, "do i = 1, n", "x = x + 1", f"!$omp scan inclusive({items})",
            "z = x", "end do"]
TEAMS_LOOP = ["!$omp teams", "!$omp distribute", "do i = 1, n", "end do",
              "!$omp end teams"]

# stem -> (legal, illegal), or {version: (legal, illegal)}; a str is one
# directive line for wrap(), a list is a whole program.
CASES = {
    "teams-nesting-001": (
        ["!$omp target", "!$omp teams", "x = 1", "!$omp end teams",
         "!$omp end target"],
        ["!$omp parallel", "!$omp teams", "x = 1", "!$omp end teams",
         "!$omp end parallel"]),
    "teams-nesting-002": (
        ["!$omp target", "!$omp teams", "x = 1", "!$omp end teams",
         "!$omp end target"],
        ["!$omp target", "y = 2", "!$omp teams", "x = 1", "!$omp end teams",
         "!$omp end target"]),
    "teams-nesting-003": (
        TEAMS_LOOP,
        ["!$omp teams", "!$omp task", "x = 1", "!$omp end task",
         "!$omp end teams"]),
    "distribute-nesting-001": (
        TEAMS_LOOP,
        ["!$omp parallel", "!$omp distribute", "do i = 1, n", "end do",
         "!$omp end parallel"]),
    "loop-nesting-001": ("!$omp loop bind(thread)", "!$omp loop"),
    "loop-nesting-002": (
        ["!$omp teams", "!$omp loop bind(teams)", "do i = 1, n", "end do",
         "!$omp end teams"],
        ["!$omp parallel", "!$omp loop bind(teams)", "do i = 1, n", "end do",
         "!$omp end parallel"]),
    "target-nesting-001": (
        ["!$omp target data map(a)", "!$omp target update to(a)",
         "!$omp end target data"],
        ["!$omp target map(a)", "!$omp target update to(a)",
         "!$omp end target"]),
    "order-nesting-001": (
        ["!$omp parallel do order(concurrent)", "do i = 1, n",
         "!$omp parallel", "x = 1", "!$omp end parallel", "end do"],
        ["!$omp parallel do order(concurrent)", "do i = 1, n",
         "!$omp task", "x = 1", "!$omp end task", "end do"]),
    "declaretarget-placement-001": (
        "!$omp declare target (a)",
        ["!$omp target", "!$omp declare target (a)", "x = 1",
         "!$omp end target"]),
    "requires-placement-001": (
        "!$omp requires atomic_default_mem_order(seq_cst)",
        ["!$omp parallel", "!$omp requires atomic_default_mem_order(seq_cst)",
         "x = 1", "!$omp end parallel"]),
    "requires-placement-002": (
        ["!$omp requires unified_shared_memory", "!$omp target", "x = 1",
         "!$omp end target"],
        ["!$omp target", "x = 1", "!$omp end target",
         "!$omp requires unified_shared_memory"]),
    "assoc-loop-001": ("!$omp parallel do", ["!$omp parallel do", "x = 1"]),
    "collapse-loop-001": (
        ["!$omp parallel do collapse(2)", "do i = 1, n", "do j = 1, n",
         "end do", "end do"],
        ["!$omp parallel do collapse(2)", "do i = 1, n", "x = 1", "end do"]),
    "loop-dsa-001": ("!$omp loop bind(thread) lastprivate(i)",
                     "!$omp loop bind(thread) lastprivate(x)"),
    "target-map-001": ("!$omp target map(alloc: a)",
                       "!$omp target map(release: a)"),
    "targetdata-map-001": ("!$omp target data map(alloc: a)",
                           "!$omp target data map(delete: a)"),
    "targetenterdata-map-001": ("!$omp target enter data map(alloc: a)",
                                "!$omp target enter data map(from: a)"),
    "targetexitdata-map-001": ("!$omp target exit data map(release: a)",
                               "!$omp target exit data map(to: a)"),
    "mapitem-map-001": ("!$omp target map(to: a) map(from: a)",
                        "!$omp target map(mapper(m), to: a) map(from: a)"),
    "mapitem-map-002": (
        ["real, allocatable :: a(:), b(:)",
         "!$omp target map(to: a) map(from: b(1:n))", "!$omp end target"],
        ["real, allocatable :: a(:)",
         "!$omp target map(to: a) map(from: a(1:n))", "!$omp end target"]),
    "mapitem-map-003": ("!$omp target map(self: a) map(to: b(1:n))",
                        "!$omp target map(self: a) map(to: a(1:n))"),
    "target-dsa-001": ("!$omp target map(to: a) firstprivate(b)",
                       "!$omp target map(to: a) firstprivate(a)"),
    "usedevice-clause-001": (
        "!$omp target data map(to: s) use_device_addr(s)",
        "!$omp target data map(to: s) use_device_addr(s%a)"),
    "usedevice-clause-002": (
        "!$omp target data map(to: a) use_device_addr(a(1:n))",
        "!$omp target data map(to: s) use_device_addr(s%a(1:n))"),
    "dnm-clause-001": {
        52: ("!$omp target parallel if(parallel: x)",
             "!$omp target simd if(parallel: x)"),
        60: ("!$omp target teams num_teams(teams: 4)",
             "!$omp target teams num_teams(parallel do: 4)")},
    "if-clause-001": ("!$omp target parallel if(target: x) if(parallel: y)",
                      "!$omp target parallel if(target: x) if(y)"),
    "threadlimit-clause-001": ("!$omp teams thread_limit(4)",
                               "!$omp teams thread_limit(-1)"),
    "numteams-clause-001": ("!$omp teams num_teams(2: 4)",
                            "!$omp teams num_teams(0: 4)"),
    "numteams-clause-002": ("!$omp teams num_teams(2: 4)",
                            "!$omp teams num_teams(8: 4)"),
    "distschedule-clause-001": ("!$omp distribute dist_schedule(static, 4)",
                                "!$omp distribute dist_schedule(static, 0)"),
    "reduction-clause-001": ("!$omp parallel reduction(task, +: x)",
                             "!$omp teams reduction(task, +: x)"),
    "reduction-clause-002": (
        scan("!$omp parallel do reduction(inscan, +: x)"),
        scan("!$omp distribute parallel do reduction(inscan, +: x)")),
    "reduction-clause-003": (
        scan("!$omp parallel do reduction(inscan, +: x) "
             "reduction(inscan, +: y)", "x, y"),
        scan("!$omp parallel do reduction(inscan, +: x) reduction(+: y)")),
    "reduction-clause-004": (
        scan("!$omp parallel do reduction(inscan, +: x)"),
        scan("!$omp parallel do reduction(inscan, +: x) schedule(static)")),
    "reduction-clause-005": (
        ["!$omp do reduction(task, +: x)", "do i = 1, n", "end do",
         "!$omp end do"],
        ["!$omp do reduction(task, +: x)", "do i = 1, n", "end do",
         "!$omp end do nowait"]),
    "distribute-dsa-001": (
        "!$omp teams distribute firstprivate(a) lastprivate(b)",
        "!$omp teams distribute firstprivate(a, b) lastprivate(b)"),
    "distribute-clause-001": ("!$omp distribute lastprivate(x)",
                              "!$omp distribute lastprivate(conditional: x)"),
    "datasharing-dsa-001": ("!$omp parallel do private(a) reduction(+: b)",
                            "!$omp parallel do private(a) reduction(+: a)"),
    # A variable declared in the source, referenced in the
    # construct, listed nowhere under default(none) (DO variables are
    # predetermined private, named constants are not variables)
    "default-dsa-001": (
        ["program p", "integer, parameter :: n = 4",
         "integer :: i, a(n), b(n)",
         "!$omp parallel do default(none) shared(a, b)", "do i = 1, n",
         "  b(i) = a(i) + n", "end do", "end program p"],
        ["program p", "integer, parameter :: n = 4",
         "integer :: i, a(n), b(n)",
         "!$omp parallel do default(none) shared(a)", "do i = 1, n",
         "  b(i) = a(i) + n", "end do", "end program p"]),
    "listitem-clause-001": ("!$omp parallel private(a)",
                            "!$omp parallel private(a(1))"),
    "device-clause-001": (
        [REQ, "!$omp target device(ancestor: 1) map(a)", "x = 1",
         "!$omp end target"],
        [REQ, "!$omp target data device(ancestor: 1) map(a)", "x = 1",
         "!$omp end target data"]),
    "device-clause-002": (
        [REQ, "!$omp target device(ancestor: 1) map(a)", "x = 1",
         "!$omp end target"],
        [REQ, "!$omp target device(ancestor: 2) map(a)", "x = 1",
         "!$omp end target"]),
    "device-clause-003": (
        [REQ, "!$omp target device(ancestor: 1) map(a)", "x = 1",
         "!$omp end target"],
        ["!$omp target device(ancestor: 1) map(a)", "x = 1",
         "!$omp end target"]),
    "target-clause-001": (
        [REQ, "!$omp target device(ancestor: 1) map(a) firstprivate(b)",
         "x = 1", "!$omp end target"],
        [REQ, "!$omp target device(ancestor: 1) map(a) if(x)", "x = 1",
         "!$omp end target"]),
    "declaretarget-clause-001": ("!$omp declare target (a)",
                                 "!$omp declare target (a) enter(b)"),
    "declaretarget-clause-002": (
        "!$omp declare target enter(a) device_type(host)",
        "!$omp declare target device_type(host)"),
    "declaretarget-clause-003": (
        "!$omp declare target link(a) device_type(any)",
        "!$omp declare target link(a) device_type(nohost)"),
    "requires-clause-001": (
        ["!$omp requires atomic_default_mem_order(seq_cst)",
         "!$omp requires atomic_default_mem_order(seq_cst)"],
        ["!$omp requires atomic_default_mem_order(seq_cst)",
         "!$omp requires atomic_default_mem_order(relaxed)"]),
    "worksharing-nesting-001": (
        ["!$omp parallel", "!$omp do", "do i = 1, n", "end do",
         "!$omp end parallel"],
        ["!$omp parallel", "!$omp single", "!$omp do", "do i = 1, n",
         "end do", "!$omp end single", "!$omp end parallel"]),
    "simd-nesting-001": (
        ["!$omp simd", "do i = 1, n", "!$omp atomic", "x = x + 1", "end do"],
        ["!$omp simd", "do i = 1, n", "!$omp parallel", "x = 1",
         "!$omp end parallel", "end do"]),
    "order-nesting-002": (
        ["!$omp parallel do order(concurrent)", "do i = 1, n", "x = i",
         "end do"],
        ["!$omp parallel do order(concurrent)", "do i = 1, n",
         "x = omp_get_thread_num()", "end do"]),
    "ordered-nesting-001": (
        ["!$omp parallel do ordered", "do i = 1, n", "!$omp ordered",
         "x = i", "!$omp end ordered", "end do"],
        ["!$omp parallel", "!$omp ordered", "x = 1", "!$omp end ordered",
         "!$omp end parallel"]),
    "ordered-nesting-002": (
        ["!$omp simd", "do i = 1, n", "!$omp ordered simd", "x = i",
         "!$omp end ordered", "end do"],
        ["!$omp parallel do ordered", "do i = 1, n", "!$omp ordered simd",
         "x = i", "!$omp end ordered", "end do"]),
    "ordered-clause-001": (
        ["!$omp parallel do ordered", "do i = 1, n", "!$omp ordered",
         "x = i", "!$omp end ordered", "end do"],
        ["!$omp parallel do", "do i = 1, n", "!$omp ordered", "x = i",
         "!$omp end ordered", "end do"]),
    "workdistribute-nesting-001": (
        ["!$omp teams workdistribute", "b = a",
         "!$omp end teams workdistribute"],
        ["!$omp target", "!$omp workdistribute", "b = a",
         "!$omp end workdistribute", "!$omp end target"]),
    "workdistribute-nesting-002": (
        ["!$omp teams workdistribute", "b = a",
         "!$omp end teams workdistribute"],
        ["!$omp teams workdistribute", "!$omp parallel", "b = a",
         "!$omp end parallel", "!$omp end teams workdistribute"]),
    "workdistribute-body-001": (
        ["!$omp teams workdistribute", "b = a", "call f(b)",
         "!$omp end teams workdistribute"],
        ["!$omp teams workdistribute", "print *, a",
         "!$omp end teams workdistribute"]),
    "distribute-clause-002": ("!$omp distribute simd linear(i)",
                              "!$omp distribute simd linear(x)"),
    "schedule-clause-001": ("!$omp do schedule(static, 4)",
                            "!$omp do schedule(runtime, 4)"),
    "schedule-clause-002": (
        "!$omp do schedule(nonmonotonic: dynamic)",
        "!$omp do schedule(nonmonotonic: dynamic) ordered"),
    "simd-clause-001": ("!$omp simd simdlen(4) safelen(8)",
                        "!$omp simd simdlen(8) safelen(4)"),
    "simd-clause-002": ("!$omp simd order(concurrent)",
                        "!$omp simd order(concurrent) safelen(4)"),
    "positive-clause-001": ("!$omp parallel num_threads(2)",
                            "!$omp parallel num_threads(0)"),
    "constant-clause-001": (
        ["integer, parameter :: k = 4", "!$omp simd safelen(k)",
         "do i = 1, n", "end do"],
        ["integer :: k", "!$omp simd safelen(k)", "do i = 1, n", "end do"]),
    "clauseset-clause-001": ("!$omp target update to(a)",
                             "!$omp target update"),
    "clauseset-clause-002": (
        ["!$omp simd reduction(inscan, +: x)", "do i = 1, n", "x = x + 1",
         "!$omp scan inclusive(x)", "y = x", "end do"],
        ["!$omp simd reduction(inscan, +: x)", "do i = 1, n", "x = x + 1",
         "!$omp scan inclusive(x) exclusive(x)", "y = x", "end do"]),
    "single-clause-001": (
        ["!$omp single", "x = 1", "!$omp end single nowait"],
        ["!$omp single copyprivate(x)", "x = 1", "!$omp end single nowait"]),
    "listitem-clause-002": ("!$omp target update to(a) from(b)",
                            "!$omp target update to(a) from(a)"),
    "linear-clause-001": (
        ["!$omp simd reduction(inscan, +: s) linear(i)", "do i = 1, n",
         "s = s + 1", "!$omp scan inclusive(s)", "y = s", "end do"],
        ["!$omp simd reduction(inscan, +: s) linear(x)", "do i = 1, n",
         "s = s + 1", "!$omp scan inclusive(s)", "y = s", "end do"]),
    "linear-clause-002": {
        52: ("!$omp do linear(x)", "!$omp do linear(ref(x))"),
        60: ("!$omp do linear(x)", "!$omp do linear(x: ref)")},
    "linear-clause-003": (
        ["integer :: p", "!$omp simd linear(p)", "do i = 1, n", "end do"],
        ["integer, pointer :: p", "!$omp simd linear(p)", "do i = 1, n",
         "end do"]),
    "linear-clause-004": (
        ["integer :: x", "!$omp simd linear(x)", "do i = 1, n", "end do"],
        ["real :: x", "!$omp simd linear(x)", "do i = 1, n", "end do"]),
    "loopvar-dsa-001": ("!$omp parallel do lastprivate(i)",
                        "!$omp parallel do firstprivate(i)"),
    "firstprivate-dsa-001": (
        ["!$omp parallel private(x)", "!$omp do firstprivate(y)",
         "do i = 1, n", "end do", "!$omp end parallel"],
        ["!$omp parallel private(x)", "!$omp do firstprivate(x)",
         "do i = 1, n", "end do", "!$omp end parallel"]),
    "firstprivate-dsa-002": (
        ["!$omp teams private(x)", "!$omp distribute firstprivate(y)",
         "do i = 1, n", "end do", "!$omp end teams"],
        ["!$omp teams private(x)", "!$omp distribute firstprivate(x)",
         "do i = 1, n", "end do", "!$omp end teams"]),
    "firstprivate-dsa-003": (
        ["!$omp parallel reduction(+: x)", "!$omp do firstprivate(y)",
         "do i = 1, n", "end do", "!$omp end parallel"],
        ["!$omp parallel reduction(+: x)", "!$omp do firstprivate(x)",
         "do i = 1, n", "end do", "!$omp end parallel"]),
    # a do between keeps reduction-dsa-003 (innermost enclosing
    # worksharing or parallel construct) quiet
    "firstprivate-dsa-004": (
        ["!$omp parallel reduction(+: x)", "!$omp do", "do i = 1, n",
         "!$omp task firstprivate(y)", "z = y", "!$omp end task", "end do",
         "!$omp end parallel"],
        ["!$omp parallel reduction(+: x)", "!$omp do", "do i = 1, n",
         "!$omp task firstprivate(x)", "z = x", "!$omp end task", "end do",
         "!$omp end parallel"]),
    "firstprivate-dsa-005": (
        ["!$omp teams reduction(+: x)", "!$omp distribute firstprivate(y)",
         "do i = 1, n", "end do", "!$omp end teams"],
        ["!$omp teams reduction(+: x)", "!$omp distribute firstprivate(x)",
         "do i = 1, n", "end do", "!$omp end teams"]),
    "lastprivate-dsa-001": (
        ["!$omp parallel private(x)", "!$omp do lastprivate(y)",
         "do i = 1, n", "end do", "!$omp end parallel"],
        ["!$omp parallel private(x)", "!$omp do lastprivate(x)",
         "do i = 1, n", "end do", "!$omp end parallel"]),
    "lastprivate-clause-001": (
        ["real :: x", "!$omp do lastprivate(conditional: x)", "do i = 1, n",
         "end do"],
        ["real :: x(10)", "!$omp do lastprivate(conditional: x)",
         "do i = 1, n", "end do"]),
    "reduction-dsa-001": (
        ["!$omp parallel shared(x)", "!$omp do reduction(+: x)",
         "do i = 1, n", "end do", "!$omp end parallel"],
        ["!$omp parallel private(x)", "!$omp do reduction(+: x)",
         "do i = 1, n", "end do", "!$omp end parallel"]),
    "reduction-dsa-002": (
        ["!$omp teams shared(x)", "!$omp loop reduction(+: x)",
         "do i = 1, n", "end do", "!$omp end teams"],
        ["!$omp teams private(x)", "!$omp loop reduction(+: x)",
         "do i = 1, n", "end do", "!$omp end teams"]),
    "reduction-clause-006": ("!$omp parallel do reduction(+: a(1:n))",
                             "!$omp parallel do reduction(+: s%a(1:n))"),
    "copyin-clause-001": (
        ["real, save :: x", "!$omp threadprivate(x)",
         "!$omp parallel copyin(x)", "y = x", "!$omp end parallel"],
        ["real :: x", "!$omp parallel copyin(x)", "y = x",
         "!$omp end parallel"]),
    "threadprivate-clause-001": (
        ["real, save :: x", "!$omp threadprivate(x)",
         "!$omp parallel copyin(x)", "y = x", "!$omp end parallel"],
        ["real, save :: x", "!$omp threadprivate(x)",
         "!$omp parallel private(x)", "y = x", "!$omp end parallel"]),
    "threadprivate-placement-001": (
        ["real, save :: x", "!$omp threadprivate(x)", "!$omp parallel",
         "y = 1", "!$omp end parallel"],
        ["real, save :: x", "!$omp parallel", "!$omp threadprivate(x)",
         "y = 1", "!$omp end parallel"]),
    "threadprivate-placement-002": (
        ["module m", "real :: x", "!$omp threadprivate(x)", "end module m"],
        ["module m", "real :: x", "contains", "subroutine s()",
         "!$omp threadprivate(x)", "end subroutine s", "end module m"]),
    "threadprivate-storage-001": (
        ["subroutine s()", "real, save :: x", "!$omp threadprivate(x)",
         "end subroutine s"],
        ["subroutine s()", "real :: x", "!$omp threadprivate(x)",
         "end subroutine s"]),
    "declaretarget-storage-001": (
        ["subroutine s()", "real, save :: x", "!$omp declare target enter(x)",
         "end subroutine s"],
        ["subroutine s()", "real :: x", "!$omp declare target enter(x)",
         "end subroutine s"]),
    "declaretarget-storage-002": (
        ["subroutine s()", "real, save :: x", "!$omp declare target link(x)",
         "end subroutine s"],
        ["subroutine s()", "real :: x", "!$omp declare target link(x)",
         "end subroutine s"]),
    "declaretarget-placement-002": (
        ["module m", "real :: x", "!$omp declare target enter(x)",
         "end module m"],
        ["module m", "real :: x", "contains", "subroutine s()",
         "!$omp declare target enter(x)", "end subroutine s",
         "end module m"]),
    "declaretarget-placement-003": (
        ["subroutine s()", "!$omp declare target", "end subroutine s"],
        ["module m", "!$omp declare target", "end module m"]),
    "declaretarget-clause-004": (
        ["!$omp declare target enter(x)", "!$omp declare target link(y)"],
        ["!$omp declare target enter(x)", "!$omp declare target link(x)"]),
    "declaretarget-clause-005": (
        ["!$omp declare target link(x)", "!$omp declare target local(y)"],
        ["!$omp declare target link(x)", "!$omp declare target local(x)"]),
    "indirect-clause-001": (
        "!$omp declare target enter(f) indirect device_type(any)",
        "!$omp declare target enter(f) indirect device_type(host)"),
    "map-clause-002": (
        ["!$omp declare target local(y)", "!$omp target map(x)", "z = 1",
         "!$omp end target"],
        ["!$omp declare target local(x)", "!$omp target map(x)", "z = 1",
         "!$omp end target"]),
    "target-map-002": (
        ["!$omp target map(s%a, s%b)", "s%a = s%b", "!$omp end target"],
        ["!$omp target map(s%a)", "s%a = s%b", "!$omp end target"]),
    "defaultmap-map-003": (
        ["real :: a, b", "!$omp target defaultmap(none) map(a, b)", "b = a",
         "!$omp end target"],
        ["real :: a, b", "!$omp target defaultmap(none) map(a)", "b = a",
         "!$omp end target"]),
    "allocate-clause-001": ("!$omp parallel private(x) allocate(x)",
                            "!$omp parallel allocate(x)"),
    "allocate-clause-002": (
        "!$omp target private(x) allocate(omp_default_mem_alloc: x)",
        "!$omp target private(x) allocate(x)"),
    "usesallocators-clause-001": (
        "!$omp target uses_allocators(a)",
        "!$omp target uses_allocators(a) firstprivate(a)"),
    "usesallocators-clause-002": (
        "!$omp target uses_allocators(omp_default_mem_alloc)",
        "!$omp target uses_allocators(memspace(omp_default_mem_space): "
        "omp_default_mem_alloc)"),
    "usesallocators-clause-003": (
        "!$omp target uses_allocators(memspace(omp_default_mem_space): a)",
        "!$omp target uses_allocators(memspace(my_space): a)"),
    "usesallocators-clause-004": (
        ["type(omp_alloctrait), parameter :: t(1) = [omp_alloctrait(1, 1)]",
         "!$omp target uses_allocators(traits(t): a)", "x = 1",
         "!$omp end target"],
        ["type(omp_alloctrait) :: t(1)",
         "!$omp target uses_allocators(traits(t): a)", "x = 1",
         "!$omp end target"]),
    "requires-placement-003": (
        ["!$omp requires atomic_default_mem_order(seq_cst)", "!$omp atomic",
         "x = x + 1"],
        ["!$omp atomic", "x = x + 1",
         "!$omp requires atomic_default_mem_order(seq_cst)"]),
    "requires-placement-004": (
        ["module m", "!$omp requires unified_shared_memory", "real :: x",
         "!$omp declare target enter(x)", "end module m", "program p",
         "use m", "!$omp target", "x = 1", "!$omp end target",
         "end program p"],
        ["module m", "real :: x", "!$omp declare target enter(x)",
         "end module m", "program p",
         "!$omp requires unified_shared_memory", "!$omp target", "x = 1",
         "!$omp end target", "end program p"]),
    "depend-clause-001": ("!$omp task depend(out: omp_all_memory)",
                          "!$omp task depend(in: omp_all_memory)"),
    "depend-clause-002": ("!$omp task depend(depobj: o)",
                          "!$omp task depend(depobj: o(1:2))"),
    "depend-clause-003": ("!$omp task depend(in: a)",
                          "!$omp task depend(in: /blk/)"),
    "depend-clause-004": ("!$omp task depend(in: a(1:4))",
                          "!$omp task depend(in: a(5:4))"),
    "taskwait-clause-001": ("!$omp taskwait depend(in: x)",
                            "!$omp taskwait depend(mutexinoutset: x)"),
    "taskwait-clause-002": ("!$omp taskwait depend(in: x) nowait",
                            "!$omp taskwait nowait"),
    "taskwait-clause-003": ("!$omp taskwait depend(in: x) replayable",
                            "!$omp taskwait replayable"),
    "depobj-clause-001": ("!$omp depobj(o) depend(in: a)",
                          "!$omp depobj(o) depend(in: a, b)"),
    "update-clause-001": ("!$omp depobj(o) update(inout)",
                          "!$omp depobj(o) update(depobj)"),
    "scan-placement-001": (
        ["!$omp simd reduction(inscan, +: x)", "do i = 1, n", "x = x + 1",
         "!$omp scan inclusive(x)", "y = x", "end do"],
        ["!$omp simd reduction(inscan, +: x)", "do i = 1, n", "x = x + 1",
         "!$omp scan inclusive(x)", "y = x", "!$omp scan inclusive(x)",
         "z = x", "end do"]),
    "scan-placement-002": (
        ["!$omp simd reduction(inscan, +: x)", "do i = 1, n", "x = x + 1",
         "!$omp scan inclusive(x)", "y = x", "end do"],
        ["!$omp scan inclusive(x)"]),
    "scan-clause-001": (
        ["!$omp simd reduction(inscan, +: x)", "do i = 1, n", "x = x + 1",
         "!$omp scan inclusive(x)", "y = x", "end do"],
        ["!$omp simd reduction(inscan, +: x)", "do i = 1, n", "x = x + 1",
         "!$omp scan inclusive(x, t)", "y = x", "end do"]),
    "scan-clause-002": (
        ["!$omp simd reduction(inscan, +: x, t)", "do i = 1, n", "x = x + 1",
         "!$omp scan inclusive(x, t)", "y = x", "end do"],
        ["!$omp simd reduction(inscan, +: x, t)", "do i = 1, n", "x = x + 1",
         "!$omp scan inclusive(x)", "y = x", "end do"]),
    "scan-loop-001": (
        ["!$omp do collapse(2) reduction(inscan, +: x)", "do i = 1, n",
         "do j = 1, n", "x = x + 1", "!$omp scan inclusive(x)", "y = x",
         "end do", "end do"],
        ["!$omp do collapse(2) reduction(inscan, +: x)", "do i = 1, n",
         "w = i", "do j = 1, n", "x = x + 1", "!$omp scan inclusive(x)",
         "y = x", "end do", "end do"]),
    "declaresimd-placement-001": {
        52: (["subroutine f(x)", "!$omp declare simd(f)",
              "end subroutine f"],
             ["program p", "!$omp declare simd(f)", "end program p"]),
        60: (["subroutine f(x)", "!$omp declare_simd(f)",
              "end subroutine f"],
             ["program p", "!$omp declare_simd(f)", "end program p"])},
    "declaremapper-clause-001": (
        "!$omp declare mapper(t :: v) map(tofrom: v)",
        "!$omp declare mapper(t :: v) map(release: v)"),
    "declaremapper-clause-002": {
        52: ("!$omp declare mapper(t :: v) map(mapper(default), tofrom: v)",
             "!$omp declare mapper(t :: v) map(mapper(m), tofrom: v)"),
        60: ("!$omp declare_mapper(t :: v) map(mapper(default), tofrom: v)",
             "!$omp declare_mapper(t :: v) map(mapper(m), tofrom: v)")},
    "declaremapper-clause-003": {
        52: (["!$omp declare mapper(t :: v) map(v)",
              "!$omp declare mapper(m2: t :: v) map(v)"],
             ["!$omp declare mapper(t :: v) map(v)",
              "!$omp declare mapper(t :: w) map(w)"]),
        60: (["!$omp declare_mapper(t :: v) map(v)",
              "!$omp declare_mapper(m2: t :: v) map(v)"],
             ["!$omp declare_mapper(t :: v) map(v)",
              "!$omp declare_mapper(t :: w) map(w)"])},
    "declaremapper-clause-004": {
        52: ("!$omp declare mapper(t :: v) map(v)",
             "!$omp declare mapper(integer :: v) map(v)"),
        60: ("!$omp declare_mapper(t :: v) map(v)",
             "!$omp declare_mapper(integer :: v) map(v)")},
    "declaremapper-clause-005": {
        52: ("!$omp declare mapper(t :: v) map(v%x)",
             "!$omp declare mapper(t :: v) map(w)"),
        60: ("!$omp declare_mapper(t :: v) map(v%x)",
             "!$omp declare_mapper(t :: v) map(w)")},
    "inreduction-clause-001": (
        ["!$omp taskgroup task_reduction(+: x)",
         "!$omp task in_reduction(+: x)", "x = x + 1", "!$omp end task",
         "!$omp end taskgroup"],
        ["!$omp taskgroup task_reduction(+: x)",
         "!$omp task in_reduction(*: x)", "x = x * 2", "!$omp end task",
         "!$omp end taskgroup"]),
    "exit-loop-001": (
        ["!$omp parallel do", "do i = 1, n", "do j = 1, n",
         "if (j > 2) exit", "end do", "end do"],
        ["!$omp parallel do", "do i = 1, n", "if (i > 2) exit", "end do"]),
    "cycle-loop-001": (
        ["!$omp parallel do", "do i = 1, n", "if (i > 2) cycle", "end do"],
        ["!$omp parallel do collapse(2)", "outer: do i = 1, n",
         "do j = 1, n", "if (j > 2) cycle outer", "end do", "end do outer"]),
    "loopvar-loop-001": (
        ["!$omp parallel do", "do i = 1, n", "x = i", "end do"],
        ["!$omp parallel do", "do i = 1, n", "i = i + 1", "end do"]),
    "loopvar-loop-002": (
        ["integer, save :: k", "!$omp threadprivate(k)", "!$omp parallel do",
         "do i = 1, n", "end do"],
        ["integer, save :: i", "!$omp threadprivate(i)", "!$omp parallel do",
         "do i = 1, n", "end do"]),
    "loopvar-loop-003": (
        ["integer :: i", "!$omp parallel do", "do i = 1, n", "end do"],
        ["real :: x", "!$omp parallel do", "do x = 1, 4", "end do"]),
    "nonrect-loop-001": (
        ["!$omp do collapse(3)", "do i = 1, n", "do j = i, n", "do k = j, n",
         "end do", "end do", "end do"],
        ["!$omp do collapse(3)", "do i = 1, n", "do j = i, n", "do k = i, j",
         "end do", "end do", "end do"]),
    "schedule-loop-001": (
        ["!$omp do collapse(2) schedule(static)", "do i = 1, n",
         "do j = 1, n", "end do", "end do"],
        ["!$omp do collapse(2) schedule(static)", "do i = 1, n",
         "do j = i, n", "end do", "end do"]),
    "distschedule-loop-001": (
        ["!$omp distribute collapse(2) dist_schedule(static)", "do i = 1, n",
         "do j = 1, n", "end do", "end do"],
        ["!$omp distribute collapse(2) dist_schedule(static)", "do i = 1, n",
         "do j = i, n", "end do", "end do"]),
    "ordered-loop-001": (
        ["!$omp do ordered(2)", "do i = 1, n", "do j = 1, n", "end do",
         "end do"],
        ["!$omp do ordered(2)", "do i = 1, n", "do j = i, n", "end do",
         "end do"]),
    "linear-loop-001": (
        ["!$omp do collapse(2) linear(x)", "do i = 1, n", "do j = 1, n",
         "end do", "end do"],
        ["!$omp do collapse(2) linear(x)", "do i = 1, n", "do j = i, n",
         "end do", "end do"]),
    "induction-loop-001": (
        ["!$omp parallel do collapse(2) induction(step(1), +: x)",
         "do i = 1, n", "do j = 1, n", "end do", "end do"],
        ["!$omp parallel do collapse(2) induction(step(1), +: x)",
         "do i = 1, n", "do j = i, n", "end do", "end do"]),
    "ordered-loop-002": ("!$omp do ordered(1)", "!$omp do ordered(2)"),
    "ordered-loop-003": (
        ["!$omp do collapse(2) ordered(2)", "do i = 1, n", "do j = 1, n",
         "end do", "end do"],
        ["!$omp do collapse(2) ordered(1)", "do i = 1, n", "do j = 1, n",
         "end do", "end do"]),
    "ordered-loop-004": ("!$omp do ordered(1)",
                         "!$omp do ordered(1) linear(x)"),
    "ordered-loop-005": (
        ["!$omp do ordered(2)", "do i = 1, n", "do j = 1, n", "end do",
         "end do"],
        ["!$omp do ordered(2)", "do i = 1, n", "x = 1", "do j = 1, n",
         "end do", "end do"]),
    "loop-clause-001": (
        ["!$omp loop bind(thread)", "do concurrent (i = 1:n)", "end do"],
        ["!$omp loop bind(thread) private(x)", "do concurrent (i = 1:n)",
         "end do"]),
    "aligned-clause-001": (
        ["real, allocatable :: a(:)", "!$omp simd aligned(a)",
         "do i = 1, n", "end do"],
        ["real :: a(10)", "!$omp simd aligned(a)", "do i = 1, n", "end do"]),
    "aligned-clause-002": (
        ["real :: a(10)", "!$omp simd aligned(a)", "do i = 1, n", "end do"],
        ["real :: x", "!$omp simd aligned(x)", "do i = 1, n", "end do"]),
    "arraysection-clause-001": ("!$omp target update to(a(1:n:2))",
                                "!$omp target update to(a(1:n:0))"),
    "arraysection-clause-002": ("!$omp target update to(s%c(1:n))",
                                "!$omp target update to(s(1:n)%c)"),
    "map-clause-001": ("!$omp target map(a(1:n))",
                       "!$omp target map(a(1:n:2))"),
    # One iterator value (Fortran ranges include the end) versus
    # two instances with the same containing array (5.2 §5.8.3 p.156)
    "map-clause-005": (
        ["!$omp target enter data map(iterator(k = 1:1), to: w(k:n))"],
        ["!$omp target enter data map(iterator(k = 1:2), to: w(k))"]),
    "reduction-dsa-003": (
        ["!$omp parallel reduction(+: x)", "!$omp task in_reduction(+: x)",
         "x = x + 1", "!$omp end task", "!$omp end parallel"],
        ["!$omp parallel reduction(+: x)", "!$omp task", "x = x + 1",
         "!$omp end task", "!$omp end parallel"]),
    "ordered-nesting-003": (
        ["!$omp do simd ordered", "do i = 1, n", "!$omp ordered simd threads",
         "x = i", "!$omp end ordered", "end do"],
        ["!$omp simd", "do i = 1, n", "!$omp ordered simd threads", "x = i",
         "!$omp end ordered", "end do"]),
    "declarative-placement-001": (
        ["subroutine s()", "use m", "!$omp requires reverse_offload",
         "end subroutine s"],
        ["subroutine s()", "!$omp requires reverse_offload", "use m",
         "end subroutine s"]),
    "namedconst-clause-001": (
        ["integer, parameter :: k = 4", "!$omp parallel firstprivate(k)",
         "x = k", "!$omp end parallel"],
        ["integer, parameter :: k = 4", "!$omp parallel private(k)",
         "x = k", "!$omp end parallel"]),
    # fortran-oop (tests/engine/test_generators.py has the other forms)
    "typebound-declaretarget-001": (
        ["module m", "type t", "integer :: v", "contains",
         "procedure :: get => t_get", "end type t", "contains",
         "integer function t_get(s)", "!$omp declare target",
         "class(t), intent(in) :: s", "t_get = s%v", "end function t_get",
         "end module m", "program p", "use m", "type(t) :: x",
         "integer :: r", "!$omp target map(tofrom: x, r)", "r = x%get()",
         "!$omp end target", "end program p"],
        ["module m", "type t", "integer :: v", "contains",
         "procedure :: get => t_get", "end type t", "contains",
         "integer function t_get(s)",
         "class(t), intent(in) :: s", "t_get = s%v", "end function t_get",
         "end module m", "program p", "use m", "type(t) :: x",
         "integer :: r", "!$omp target map(tofrom: x, r)", "r = x%get()",
         "!$omp end target", "end program p"]),
    "typename-clause-001": {
        52: (["subroutine s()",
              "!$omp declare reduction(r: integer: omp_out = omp_in)",
              "end subroutine s"],
             ["subroutine s()",
              "!$omp declare reduction(r: class(*): omp_out = omp_in)",
              "end subroutine s"]),
        60: (["subroutine s()",
              "!$omp declare_reduction(r: integer: omp_out = omp_in)",
              "end subroutine s"],
             ["subroutine s()",
              "!$omp declare_reduction(r: class(*): omp_out = omp_in)",
              "end subroutine s"])},
    "declaretarget-clause-006": {
        50: (["module m", "interface gen", "module procedure f1",
              "end interface gen", "!$omp declare target to(f1)", "contains",
              "integer function f1(x)", "integer :: x", "f1 = x",
              "end function f1", "end module m"],
             ["module m", "interface gen", "module procedure f1",
              "end interface gen", "!$omp declare target to(gen)",
              "contains", "integer function f1(x)", "integer :: x", "f1 = x",
              "end function f1", "end module m"]),
        52: (["module m", "interface gen", "module procedure f1",
              "end interface gen", "!$omp declare target enter(f1)",
              "contains", "integer function f1(x)", "integer :: x", "f1 = x",
              "end function f1", "end module m"],
             ["module m", "interface gen", "module procedure f1",
              "end interface gen", "!$omp declare target enter(gen)",
              "contains", "integer function f1(x)", "integer :: x", "f1 = x",
              "end function f1", "end module m"])},
}
CASES["declaretarget-clause-006"][60] = \
    CASES["declaretarget-clause-006"][52]

# defaultmap is unique in the grammar (a decision of the corpus
# triage), so programs violating these rules do not parse: the trees are
# built from two parsed directives instead.
DEFAULTMAP = {
    "defaultmap-map-001": (["scalar", "aggregate"], ["scalar", "scalar"]),
    "defaultmap-map-002": (["scalar", "aggregate"], ["all", "scalar"]),
}


def program(case, version):
    if isinstance(case, str):
        return parse_program(wrap(case, version), version)
    return parse_program(src(*case), version)


def defaultmap_tree(categories, version):
    clauses = []
    for cat in categories:
        d = parse_directive(f"!$omp target defaultmap(tofrom: {cat})",
                            "fortran", version)
        clauses += d.clauses
    d = parse_directive("!$omp target", "fortran", version)
    d.clauses = clauses
    return ProgramTree([d], [], [Assoc("block", 1, 3, stmts=1)], {})


def test_every_static_rule_has_cases():
    stems = {r.id.split("-", 1)[1] for r in STATIC}
    assert stems == set(CASES) | set(DEFAULTMAP)


# OpenMP 5.0 cases where the shared case uses later syntax (enter,
# 5.1/5.2 modifiers) or the 5.0 rule differs (loop bind only in a procedure,
# a second atomic_default_mem_order requires, any linear modifier); a dict
# case without a 50 key uses its 52 case at 50.
CASES_50 = {
    "loop-nesting-001": (
        "!$omp loop",
        ["subroutine s()", "!$omp loop", "do i = 1, n", "end do",
         "end subroutine s"]),
    "numteams-clause-001": ("!$omp teams num_teams(4)",
                            "!$omp teams num_teams(0)"),
    "requires-clause-001": (
        "!$omp requires atomic_default_mem_order(seq_cst)",
        ["!$omp requires atomic_default_mem_order(seq_cst)",
         "!$omp requires atomic_default_mem_order(seq_cst)"]),
    "linear-clause-002": ("!$omp do linear(x)", "!$omp do linear(val(x))"),
    "declaretarget-storage-001": (
        ["subroutine s()", "real, save :: x", "!$omp declare target to(x)",
         "end subroutine s"],
        ["subroutine s()", "real :: x", "!$omp declare target to(x)",
         "end subroutine s"]),
    "declaretarget-placement-002": (
        ["module m", "real :: x", "!$omp declare target to(x)",
         "end module m"],
        ["module m", "real :: x", "contains", "subroutine s()",
         "!$omp declare target to(x)", "end subroutine s",
         "end module m"]),
    "declaretarget-clause-004": (
        ["!$omp declare target to(x)", "!$omp declare target link(y)"],
        ["!$omp declare target to(x)", "!$omp declare target link(x)"]),
    "usesallocators-clause-002": (
        "!$omp target uses_allocators(omp_default_mem_alloc)",
        "!$omp target uses_allocators(omp_default_mem_alloc(t))"),
    "usesallocators-clause-004": (
        ["type(omp_alloctrait), parameter :: t(1) = [omp_alloctrait(1, 1)]",
         "!$omp target uses_allocators(a(t))", "x = 1",
         "!$omp end target"],
        ["type(omp_alloctrait) :: t(1)",
         "!$omp target uses_allocators(a(t))", "x = 1",
         "!$omp end target"]),
    "requires-placement-004": (
        ["module m", "!$omp requires unified_shared_memory", "real :: x",
         "!$omp declare target to(x)", "end module m", "program p",
         "use m", "!$omp target", "x = 1", "!$omp end target",
         "end program p"],
        ["module m", "real :: x", "!$omp declare target to(x)",
         "end module m", "program p",
         "!$omp requires unified_shared_memory", "!$omp target", "x = 1",
         "!$omp end target", "end program p"]),
}


@pytest.mark.parametrize("rule", STATIC, ids=lambda r: r.id)
def test_rule_legal_and_illegal(rule):
    stem, v = rule.id.split("-", 1)[1], rule.version
    if stem in DEFAULTMAP:
        legal, illegal = (defaultmap_tree(c, v) for c in DEFAULTMAP[stem])
    else:
        case = CASES_50.get(stem) if v == 50 else None
        if case is None:
            case = CASES[stem]
            if isinstance(case, dict):
                case = case[52 if v == 50 and 50 not in case else v]
        legal, illegal = case
        legal, illegal = program(legal, v), program(illegal, v)
    assert violations(legal, v) == []
    assert violations(illegal, v) == [rule.id]


def test_dnm_target_data_constituents_at_60():
    """6.0 target_data is a composite of target_enter_data, task and
    target_exit_data (6.0 §15.7, p.458), so they are constituents."""
    tree = program("!$omp target_data map(a) depend(target_exit_data, in: a)",
                   60)
    assert violations(tree, 60) == []
    tree = program("!$omp target_data map(a) if(target_enter_data: x) if(x)",
                   60)
    assert violations(tree, 60) == ["OMP60-if-clause-001"]


def test_declare_mapper_maps_are_not_construct_maps():
    tree = program("!$omp declare mapper(t :: v) map(v%x, v%x(1))", 52)
    assert violations(tree, 52) == []


def test_findings_report_each_directive():
    tree = parse_program(src("!$omp target map(release: a)",
                             "!$omp end target",
                             "!$omp target map(delete: b)",
                             "!$omp end target"), 52)
    assert findings(tree, 52) == [("OMP52-target-map-001", 0),
                                  ("OMP52-target-map-001", 1)]
    assert violations(tree, 52) == ["OMP52-target-map-001"]


def test_parse_program_skips_preprocessor_and_rejects_fixed_form():
    tree = parse_program(src("#ifdef PDO", "!$omp parallel do", "#endif",
                             "do i = 1, n; x = i; end do"), 52)
    assert tree.assoc[0].loop_depth == 1
    with pytest.raises(GrammarError, match="fixed"):
        parse_program(src("c$omp parallel", "c$omp end parallel"), 52)


def test_parse_program_units():
    tree = parse_program(src(
        "module m",
        "contains",
        "  subroutine s()",
        "  !$omp requires unified_shared_memory",
        "  end subroutine s",
        "end module m",
        "real(8) function f(x) result(y)",
        "!$omp target",
        "!$omp end target",
        "end function",
        "program main",
        "!$omp requires unified_shared_memory",
        "end program main"), 52)
    assert [a.unit for a in tree.assoc] == [1, 2, 3]
    # requires after a device construct of another program unit is fine
    assert violations(tree, 52) == []


def test_parse_program_loop_depth_through_block():
    tree = parse_program(src(
        "!$omp do collapse(2)",
        "do i = 1, n",
        "  block",
        "    block",
        "      call g(i)",
        "    end block",
        "    call f(i)",
        "    do j = 1, n",
        "    end do",
        "  end block",
        "end do"), 52)
    assert tree.assoc[0].loop_vars == ("i", "j")
    assert violations(tree, 52) == []


def test_target_block_construct_around_teams_is_not_a_statement():
    tree = parse_program(src("!$omp target", "block", "!$omp teams",
                             "x = 1", "!$omp end teams", "end block"), 52)
    assert tree.assoc[0].stmts == 0 and violations(tree, 52) == []


def test_loop_transform_in_nest_leaves_depth_unknown():
    tree = parse_program(src(
        "!$omp parallel do collapse(2)",
        "do i = 0, 100",
        "  !$omp unroll partial(2)",
        "  do j = 1, 10",
        "  end do",
        "end do"), 60)
    a = tree.assoc[0]
    assert (a.loop_depth, a.depth_known) == (1, False)
    assert violations(tree, 60) == []


@pytest.mark.parametrize("version", [52, 60])
@pytest.mark.parametrize("clauses", [
    "shared(x) firstprivate(x)", "shared(x) lastprivate(x)",
    "shared(x) reduction(+: x)", "firstprivate(x) lastprivate(x)"])
def test_dsa_split_legal_on_compound(clauses, version):
    """shared goes to parallel, the others to do (5.2 §17.2, 6.0 §19.2)."""
    tree = program(f"!$omp parallel do {clauses}", version)
    assert violations(tree, version) == []


@pytest.mark.parametrize("version", [52, 60])
@pytest.mark.parametrize("line", [
    "!$omp parallel do private(x) firstprivate(x)",
    "!$omp parallel shared(x) private(x)",
    "!$omp target is_device_ptr(p) firstprivate(p)",
    "!$omp target data map(to: a) use_device_ptr(p) use_device_addr(p)"])
def test_dsa_split_same_leaf_illegal(line, version):
    tree = program(line, version)
    assert violations(tree, version) == [f"OMP{version}-datasharing-dsa-001"]


MAP_PART = ["!$omp target map(to: {0}) map(from: {0}(1:n))",
            "!$omp end target"]


@pytest.mark.parametrize("decls, item, fires", [
    (["real, pointer :: p(:)"], "p", False),
    (["real :: p(:)", "pointer :: p"], "p", False),
    ([], "p", False),  # no visible declaration: not checked
    (["use m"], "p", False),
    (["real, allocatable :: a(:)"], "a", True),
    (["real a(100)"], "a", True),
    (["type t", "  real, pointer :: c(:)", "end type", "type(t) :: s"],
     "s%c", False),
    (["type :: t", "  real :: c(10)", "end type t", "type(t) :: s"],
     "s%c", True),
    # the declared type of s is use-associated: its c may be a pointer
    (["use other_mod, only: u", "type t", "  real :: c(10)", "end type",
      "type(u) :: s"], "s%c", False),
    (["type t", "  real :: c(10)", "end type", "type(t) :: s",
      "type(t) :: r"], "r%c", True),
    (["type t", "  real :: c(10)", "end type"], "s%c", False),
    # a USE in the declaring unit may supply the name (a conflict)
    (["use m", "real :: a(10)"], "a", False),
    (["use m, only: b", "real :: a(10)"], "a", True),
])
def test_map_whole_and_part_needs_non_pointer_declaration(decls, item, fires):
    tree = parse_program(src("subroutine sub(n)", *decls,
                             *[ln.format(item) for ln in MAP_PART],
                             "end subroutine"), 52)
    assert violations(tree, 52) == (["OMP52-mapitem-map-002"] if fires
                                    else [])


def test_declarations_follow_scoping_units():
    tree = parse_program(src(
        "module m",
        "  real, allocatable :: a(:)",
        "contains",
        "  subroutine s1()",
        "    real, pointer :: a(:)",
        "    !$omp target map(a) map(a(1:2))",
        "    !$omp end target",
        "  end subroutine",
        "  subroutine s2()",
        "    select type (z)",
        "    type is (integer)",
        "    end select",
        "    !$omp target map(a) map(a(1:2))",
        "    !$omp end target",
        "  end subroutine",
        "end module"), 52)
    assert tree.attribute(0, "a") == "pointer"
    assert tree.attribute(1, "a") == "allocatable"
    assert findings(tree, 52) == [("OMP52-mapitem-map-002", 1)]


USE_HOST = """module m2
  real, pointer :: p(:)
end module m2
program main
  real :: p(10)
contains
  subroutine s
    {use}
    !$omp target map(p) map(p(:))
    !$omp end target
  end subroutine s
end program main
"""


@pytest.mark.parametrize("use, fires", [
    ("use m2", False),              # the module's pointer hides the host p
    ("use m2, only: p", False),
    ("use m2, only: p => q", False),  # rename: local p is the module's q
    ("use, intrinsic :: m2", False),
    ("use m2, only: other", True),  # does not supply p: the host's p
    ("use m2, only: q => p", True),  # local name q, p is still the host's
    ("x = 1", True),
])
def test_use_association_hides_host_declarations(use, fires):
    tree = parse_program(USE_HOST.format(use=use), 52)
    assert violations(tree, 52) == (["OMP52-mapitem-map-002"] if fires
                                    else [])


HOST_TYPE = """program main
  type t
    real, pointer :: c(:)
  end type
  type(t) :: s
contains
  subroutine sub
    type t
      real :: c(10)
    end type
    {decl}
    !$omp target map({x}) map({x}(1:2))
    !$omp end target
  end subroutine
end program
"""


@pytest.mark.parametrize("decl, x, fires", [
    ("", "s%c", False),            # host s has the host t: c is a pointer
    ("type(t) :: s2", "s2%c", True),  # s2 has the inner t: c is plain
    ("class(*), pointer :: u", "u%c", False),
])
def test_component_type_resolved_where_variable_is_declared(decl, x,
                                                             fires):
    tree = parse_program(HOST_TYPE.format(decl=decl, x=x), 52)
    assert violations(tree, 52) == (["OMP52-mapitem-map-002"] if fires
                                    else [])


@pytest.mark.parametrize("inner, fires", [
    ("real, pointer :: c(:)", False), ("real :: c(10)", True)])
def test_nested_component_types(inner, fires):
    """The type of a component is resolved where its type is defined."""
    tree = parse_program(src(
        "module m",
        "  type in",
        f"    {inner}",
        "  end type",
        "  type out",
        "    type(in) :: b",
        "  end type",
        "end module",
        "subroutine sub",
        "  type in",
        "    real, pointer :: c(:)",
        "  end type",
        "  type out",
        "    type(in) :: b",
        "  end type",
        "  type(out) :: a",
        "contains",
        "  subroutine inner_sub",
        "    type in",
        "      real :: c(10)",
        "    end type",
        "    !$omp target map(a%b%c) map(a%b%c(1:2))",
        "    !$omp end target",
        "  end subroutine",
        "end subroutine"), 52)
    # a is sub's: out and in resolve in sub, where c is a pointer
    assert violations(tree, 52) == []
    tree = parse_program(src(
        "module m",
        "  type in",
        f"    {inner}",
        "  end type",
        "  type out",
        "    type(in) :: b",
        "  end type",
        "  type(out) :: a",
        "contains",
        "  subroutine s",
        "    type in",
        "      real, pointer :: c(:)",
        "    end type",
        "    !$omp target map(a%b%c) map(a%b%c(1:2))",
        "    !$omp end target",
        "  end subroutine",
        "end module"), 52)
    assert violations(tree, 52) == (["OMP52-mapitem-map-002"] if fires
                                    else [])


def test_separate_module_procedure_is_a_subprogram_scope():
    """'module integer function f(x)' (interface body or definition of a
    separate module procedure) is a function, so a clause-less declare
    target in it is well placed (stage 5)."""
    from offload.engine.rules import parse_program, violations
    src = """module m
  implicit none
  interface
    module integer function f(x)
      !$omp declare target
      integer, intent(in) :: x
    end function f
  end interface
end module m
submodule (m) s
  implicit none
contains
  module integer function f(x)
    !$omp declare target
    integer, intent(in) :: x
    f = x + 1
  end function f
end submodule s
program p
  use m
  implicit none
  integer :: y
  !$omp target map(from: y)
  y = f(1)
  !$omp end target
  print *, y
end program p
"""
    assert violations(parse_program(src, 52), 52) == []


def test_map_iterator_rule_reads_macros_of_a_preprocessed_fortran_test():
    """Omp_vv test_target_map_iterators.F90 maps
    test_lst(it) for it = 1:N with #define N 1024."""
    src = ("#define N 4\nprogram p\n  integer :: a(N)\n"
           "  !$omp target map(iterator(it = 1:N), tofrom: a(it))\n"
           "  a(1) = 1\n  !$omp end target\nend program p\n")
    assert violations(parse_program(src, 52), 52) == ["OMP52-map-clause-005"]


# ---- Rules-witness false refusals found by the harvest2 -----------------------------------------

from offload.engine import prerun as PR


def rules(text, lang, version=52):
    return PR.rules_witness((text, lang, "omp", version))


C_TWO_DEFAULTMAPS = """int main(void) {
  int s = 1;
  int a[4] = {0, 0, 0, 0};
#pragma omp target defaultmap(tofrom: scalar) defaultmap(firstprivate: aggregate)
  { s = 2; a[0] = 1; }
  return s == 2 ? 0 : 1;
}
"""


def test_defaultmap_once_per_category():
    # 5.2 §5.8.7: "A given variable-category may be specified in at most one
    # defaultmap clause on a construct": two categories are allowed
    ok, why = rules(C_TWO_DEFAULTMAPS, "c")
    assert ok is True, why
    same = C_TWO_DEFAULTMAPS.replace("firstprivate: aggregate",
                                     "firstprivate: scalar")
    ok, why = rules(same, "c")
    assert ok is False and any("defaultmap-map-001" in w for w in why), why
    alone = C_TWO_DEFAULTMAPS.replace("tofrom: scalar", "tofrom: all")
    ok, why = rules(alone, "c")
    assert ok is False and any("defaultmap-map-002" in w for w in why), why


F_DECLARE_VARIANT = """module m
contains
  subroutine base(x)
    integer :: x
    !$omp declare variant(var) match(construct={parallel})
    x = 1
  end subroutine base
  subroutine var(x)
    integer :: x
    x = 2
  end subroutine var
end module m
program p
  use m
  integer :: y
  y = 0
  !$omp target map(tofrom: y)
  y = y + 1
  !$omp end target
  call base(y)
end program p
"""


def test_fortran_declare_variant_is_a_fortran_directive():
    # 5.0 §2.3.5 and 5.2 §7.5 give the Fortran form
    # !$omp declare variant([base-proc-name:]variant-proc-name) clause
    for v in (50, 52):
        ok, why = rules(F_DECLARE_VARIANT, "f90", v)
        assert ok is True, (v, why)


F_BEGIN_METADIRECTIVE = """program p
  implicit none
  integer :: a(10)
  a = 0
  !$omp begin metadirective when(user={condition(.true.)}: parallel) &
  !$omp& otherwise(nothing)
  a(1) = 1
  !$omp end metadirective
  !$omp target map(tofrom: a)
  a(2) = 2
  !$omp end target
end program p
"""


def test_fortran_begin_metadirective_pairs_with_end_metadirective():
    # 5.2 §7.4.4: begin metadirective, a delimited metadirective whose
    # paired end directive is end metadirective
    ok, why = rules(F_BEGIN_METADIRECTIVE, "f90", 52)
    assert ok is True, why


C_BODY_ARRAY = """#include <stdio.h>
int main(void) {
  int n = 100;
  double out[100];
#pragma omp target teams distribute parallel for map(from: out[0:n])
  for (int i = 0; i < n; i++) {
    double v[5] = {0};
    v[i % 5] = i;
    out[i] = v[i % 5];
  }
  return out[3] == 3.0 ? 0 : 1;
}
"""


def test_an_array_declared_in_the_loop_body_is_private():
    # 5.2 §5.1.1: a variable declared in a scope inside the construct is
    # private; its initializer is no write of a shared element
    ok, why = rules(C_BODY_ARRAY, "c")
    assert ok is True, why
    shared = C_BODY_ARRAY.replace("    double v[5] = {0};\n", "").replace(
        "  double out[100];\n", "  double out[100];\n  double v[5];\n").replace(
        "v[i % 5] = i;", "v[0] = i;")
    ok, why = rules(shared, "c")
    assert ok is False and any("race" in w for w in why), why


def test_c_openacc_stub_is_guarded_and_declares_the_api():
    text = ("#include <openacc.h>\nint main(void) { int x = 0;\n"
            "acc_copyin(&x, sizeof x); acc_delete(&x, sizeof x);\n"
            "return acc_get_device_type() == acc_device_host; }\n"
            "#include <openacc.h>\n")
    (name, out), = PR._acc_c_stub([("p.c", text)], "c", "acc")
    assert "#include <openacc.h>" not in out
    assert out.count("#ifndef HV_OPENACC_STUB") == 2
    for f in ("acc_copyin", "acc_delete", "acc_get_device_type",
              "acc_memcpy_from_device", "acc_detach_finalize",
              "acc_present_or_create", "acc_update_self"):
        assert f + "(" in out, f


def test_fortran_openacc_stub_async_test_is_a_function():
    stub = PR.openacc_stub(["if (acc_async_test(1)) x = acc_async_noval"])
    assert "logical, external :: acc_async_test" in stub
    assert "acc_async_noval = " in stub


# --- The refusals the fixes must keep ------------------------------

def test_defaultmap_without_a_category_counts_as_all():
    # 5.2 §5.8.7 p.161 l.17-18: "If no variable-category is specified in the
    # clause then the effect is as if all was specified"
    mixed = C_TWO_DEFAULTMAPS.replace("defaultmap(tofrom: scalar)", "defaultmap(tofrom)")
    for v in (50, 52):
        ok, why = rules(mixed, "c", v)
        assert ok is False and any("defaultmap-map-00" in w for w in why), (v, why)
    two = C_TWO_DEFAULTMAPS.replace("defaultmap(tofrom: scalar)", "defaultmap(tofrom)").replace(
        "defaultmap(firstprivate: aggregate)", "defaultmap(firstprivate)")
    for v in (50, 52):
        ok, why = rules(two, "c", v)
        assert ok is False and any("defaultmap-map-00" in w for w in why), (v, why)
    alone = C_TWO_DEFAULTMAPS.replace(" defaultmap(firstprivate: aggregate)", "").replace(
        "defaultmap(tofrom: scalar)", "defaultmap(tofrom)")
    ok, why = rules(alone, "c", 52)
    assert ok is True, why


def test_begin_metadirective_is_in_5_0():
    # 5.0 §2.3.4 has the begin metadirective / end metadirective form
    # (otherwise and nothing are 5.1/5.2; the 5.0 form has a when clause only)
    v50 = F_BEGIN_METADIRECTIVE.replace(" &\n  !$omp& otherwise(nothing)", "")
    assert "otherwise" not in v50
    ok, why = rules(v50, "f90", 50)
    assert ok is True, why


def test_begin_metadirective_below_its_version_is_refused():
    ok, why = rules(F_BEGIN_METADIRECTIVE, "f90", 45)
    assert ok is not True and any("begin metadirective" in w for w in why), why


def test_end_metadirective_needs_an_open_begin_metadirective():
    alone = F_BEGIN_METADIRECTIVE.replace(
        "  !$omp begin metadirective when(user={condition(.true.)}: parallel) &\n"
        "  !$omp& otherwise(nothing)\n", "")
    ok, why = rules(alone, "f90", 52)
    assert ok is not True and why, why          # unreadable: no legality verdict
    plain = F_BEGIN_METADIRECTIVE.replace("!$omp begin metadirective", "!$omp metadirective")
    ok, why = rules(plain, "f90", 52)
    assert ok is not True and why, why


def test_a_static_array_in_the_loop_body_is_shared():
    # 5.2 §5.1.1 p.98 l.1: "Variables with static storage duration that are
    # declared in a scope inside the construct are shared"
    shared = C_BODY_ARRAY.replace("    double v[5] = {0};\n    v[i % 5] = i;\n    out[i] = v[i % 5];\n",
                                  "    static double v[5];\n    v[0] = i;\n    out[i] = v[0];\n")
    assert "static double v[5]" in shared
    ok, why = rules(shared, "c")
    assert ok is False and any("race" in w for w in why), why


# ---- Fortran derived-type and object-oriented restrictions in offload.engine.rules -----------------------






def module(*procs, types=()):
    return ["module m", "implicit none", *types, "contains", *procs,
            "end module m"]


T_GET = ["type t", "integer :: v", "contains",
         "procedure :: get => t_get", "end type t"]


def get_fn(dt=True):
    return ["integer function t_get(s)"] + \
        (["!$omp declare target"] if dt else []) + \
        ["class(t), intent(in) :: s", "t_get = s%v", "end function t_get"]


def main(*body, decls=("type(t) :: x", "integer :: r")):
    return ["program p", "use m", "implicit none", *decls, *body,
            "end program p"]


def tbp(tree_src, v=52):
    return [x for x in violations(parse_program(tree_src, v), v)
            if "typebound" in x]


TARGET_GET = ["!$omp target map(tofrom: x, r)", "r = x%get()",
              "!$omp end target"]


@pytest.mark.parametrize("v", [50, 52, 60])
def test_type_bound_call_needs_declare_target(v):
    good = src(*module(*get_fn(True), types=T_GET), *main(*TARGET_GET))
    bad = src(*module(*get_fn(False), types=T_GET), *main(*TARGET_GET))
    assert tbp(good, v) == []
    assert tbp(bad, v) == [f"OMP{v}-typebound-declaretarget-001"]


def test_type_bound_call_outside_target_is_not_an_access():
    s = src(*module(*get_fn(False), types=T_GET),
            *main("r = x%get()", "!$omp target map(tofrom: r)", "r = 1",
                  "!$omp end target"))
    assert tbp(s) == []


def test_component_named_like_a_binding_is_not_a_call():
    types = ["type t", "integer :: get(4)", "end type t"]
    s = src(*module("subroutine s0()", "end subroutine s0", types=types),
            *main("!$omp target map(tofrom: x, r)", "r = x%get(2)",
                  "!$omp end target"))
    assert tbp(s) == []


def test_type_bound_call_in_a_device_procedure():
    """An access in a procedure with declare target is an access in a target
    region (the procedure runs there)."""
    caller = ["integer function use_it(s)", "!$omp declare target",
              "type(t), intent(in) :: s", "use_it = s%get()",
              "end function use_it"]
    good = src(*module(*get_fn(True), *caller, types=T_GET))
    bad = src(*module(*get_fn(False), *caller, types=T_GET))
    assert tbp(good) == []
    assert tbp(bad) == ["OMP52-typebound-declaretarget-001"]


def test_type_bound_call_in_a_procedure_called_from_target():
    """A procedure referenced in a target construct is a device procedure
    (5.2 §13.8 p.285), so a binding it calls is accessed in the region."""
    helper = ["integer function helper(s)", "type(t), intent(in) :: s",
              "helper = s%get()", "end function helper"]
    s = src(*module(*get_fn(False), *helper, types=T_GET),
            *main("!$omp target map(tofrom: x, r)", "r = helper(x)",
                  "!$omp end target"))
    assert tbp(s) == ["OMP52-typebound-declaretarget-001"]


SHAPES = ["type, abstract :: shape", "integer :: id = 0", "contains",
          "procedure(area_if), deferred :: area", "end type shape",
          "abstract interface", "integer function area_if(s)",
          "import :: shape", "class(shape), intent(in) :: s",
          "end function area_if", "end interface",
          "type, extends(shape) :: sq", "integer :: side = 0", "contains",
          "procedure :: area => sq_area", "end type sq",
          "type, extends(shape) :: rect", "integer :: w = 0, h = 0",
          "contains", "procedure :: area => rect_area", "end type rect"]


def area(name, body, dt=True):
    return [f"integer function {name}(s)"] + \
        (["!$omp declare target"] if dt else []) + \
        [f"class({name.split('_')[0]}), intent(in) :: s",
         f"{name} = {body}", f"end function {name}"]


def area_of(dt=True):
    return ["integer function area_of(s)"] + \
        (["!$omp declare target"] if dt else []) + \
        ["class(shape), intent(in) :: s", "area_of = s%area()",
         "end function area_of"]


def test_dispatch_on_a_polymorphic_object_needs_every_override():
    """class(shape)%area may call any override of an extension: each one
    accessed in the region must be in a declare target directive."""
    good = src(*module(*area("sq_area", "s%side * s%side"),
                       *area("rect_area", "s%w * s%h"), *area_of(),
                       types=SHAPES))
    bad = src(*module(*area("sq_area", "s%side * s%side"),
                      *area("rect_area", "s%w * s%h", dt=False), *area_of(),
                      types=SHAPES))
    assert tbp(good) == []
    assert tbp(bad) == ["OMP52-typebound-declaretarget-001"]


def test_non_polymorphic_object_needs_only_its_own_binding():
    """type(sq) resolves sq%area statically: rect's override is not
    accessed."""
    s = src(*module(*area("sq_area", "s%side * s%side"),
                    *area("rect_area", "s%w * s%h", dt=False),
                    types=SHAPES),
            *main("!$omp target map(tofrom: q, r)", "r = q%area()",
                  "!$omp end target", decls=("type(sq) :: q",
                                             "integer :: r")))
    assert tbp(s) == []


def test_inherited_binding_resolves_to_the_parent_procedure():
    types = T_GET + ["type, extends(t) :: u", "integer :: w",
                     "end type u"]
    good = src(*module(*get_fn(True), types=types),
               *main("!$omp target map(tofrom: y, r)", "r = y%get()",
                     "!$omp end target", decls=("type(u) :: y",
                                                "integer :: r")))
    bad = src(*module(*get_fn(False), types=types),
              *main("!$omp target map(tofrom: y, r)", "r = y%get()",
                    "!$omp end target", decls=("type(u) :: y",
                                               "integer :: r")))
    assert tbp(good) == []
    assert tbp(bad) == ["OMP52-typebound-declaretarget-001"]


def test_generic_binding_accesses_its_specific_procedures():
    types = ["type t", "integer :: v", "contains",
             "procedure :: scale_i, scale_2",
             "generic :: scale => scale_i, scale_2", "end type t"]
    procs = ["subroutine scale_i(s, k)", "!$omp declare target",
             "class(t), intent(inout) :: s", "integer, intent(in) :: k",
             "s%v = s%v * k", "end subroutine scale_i",
             "subroutine scale_2(s, a, b)",
             "class(t), intent(inout) :: s", "integer, intent(in) :: a, b",
             "s%v = s%v * a * b", "end subroutine scale_2"]
    s = src(*module(*procs, types=types),
            *main("!$omp target map(tofrom: x)", "call x%scale(3)",
                  "!$omp end target"))
    assert tbp(s) == ["OMP52-typebound-declaretarget-001"]


def test_defined_assignment_binding_in_target():
    types = ["type t", "integer :: v", "contains",
             "procedure :: asg", "generic :: assignment(=) => asg",
             "end type t"]

    def asg(dt):
        return ["subroutine asg(a, b)"] + \
            (["!$omp declare target"] if dt else []) + \
            ["class(t), intent(out) :: a", "class(t), intent(in) :: b",
             "a%v = b%v + 1", "end subroutine asg"]
    body = ("!$omp target map(tofrom: x, y)", "x = y", "!$omp end target")
    decls = ("type(t) :: x, y",)
    good = src(*module(*asg(True), types=types), *main(*body, decls=decls))
    bad = src(*module(*asg(False), types=types), *main(*body, decls=decls))
    assert tbp(good) == []
    assert tbp(bad) == ["OMP52-typebound-declaretarget-001"]


def test_final_procedure_of_a_device_local_object():
    types = ["type f_t", "integer :: v = 0", "contains",
             "final :: f_fin", "end type f_t"]

    def fin(dt):
        return ["subroutine f_fin(a)"] + \
            (["!$omp declare target"] if dt else []) + \
            ["type(f_t), intent(inout) :: a", "a%v = 0",
             "end subroutine f_fin"]
    work = ["subroutine work(k)", "!$omp declare target",
            "integer, intent(inout) :: k", "type(f_t) :: o", "o%v = k",
            "k = o%v + 1", "end subroutine work"]
    assert tbp(src(*module(*fin(True), *work, types=types))) == []
    assert tbp(src(*module(*fin(False), *work, types=types))) == \
        ["OMP52-typebound-declaretarget-001"]


def test_binding_procedure_not_in_the_source_is_not_judged():
    s = src("program p", "use other", "type(t) :: x", "integer :: r",
            "!$omp target map(tofrom: x, r)", "r = x%get()",
            "!$omp end target", "end program p")
    assert tbp(s) == []


# --- type-name list items -----------------------------------------------------------

def tn(lines, v=52):
    return [x for x in violations(parse_program(src(*lines), v), v)
            if "typename" in x]


ABSTRACT = ["module m", "type, abstract :: a_t", "integer :: v",
            "end type a_t", "type, extends(a_t) :: c_t", "end type c_t",
            "end module m"]


@pytest.mark.parametrize("v", [50, 52, 60])
def test_declare_reduction_type_not_class_star_or_abstract(v):
    dr = "declare_reduction" if v == 60 else "declare reduction"
    ok = ["subroutine s()", "use m",
          f"!$omp {dr}(r: c_t: omp_out%v = omp_out%v + omp_in%v)",
          "end subroutine s"]
    star = ["subroutine s()",
            f"!$omp {dr}(r: class(*): omp_out = omp_in)",
            "end subroutine s"]
    abst = ["module m", "type, abstract :: a_t", "integer :: v",
            "end type a_t",
            f"!$omp {dr}(r: a_t: omp_out%v = omp_out%v + "
            "omp_in%v)", "end module m"]
    assert tn(ABSTRACT + ok, v) == []
    assert tn(star, v) == [f"OMP{v}-typename-clause-001"]
    assert tn(abst, v) == [f"OMP{v}-typename-clause-001"]


def test_declare_mapper_type_not_abstract():
    lines = ["module m", "type, abstract :: a_t", "integer :: v",
             "end type a_t", "!$omp declare mapper(a_t :: w) map(w%v)",
             "end module m"]
    assert "OMP52-declaremapper-clause-004" in violations(
        parse_program(src(*lines), 52), 52)
    ok = ["module m", "type :: c_t", "integer :: v", "end type c_t",
          "!$omp declare mapper(c_t :: w) map(w%v)", "end module m"]
    assert violations(parse_program(src(*ok), 52), 52) == []


def test_declare_mapper_type_not_pdt_at_60_only():
    def lines(dm):
        return ["module m", "type :: p_t(k)", "integer, kind :: k = 4",
                "integer(k) :: v", "end type p_t",
                f"!$omp {dm}(p_t :: w) map(w%v)", "end module m"]
    assert "OMP60-declaremapper-clause-004" in violations(
        parse_program(src(*lines("declare_mapper")), 60), 60)
    assert violations(parse_program(src(*lines("declare mapper")), 52),
                      52) == []


# --- declare target procedure names -------------------------------------------------

def dtn(lines, v=52):
    return [x for x in violations(parse_program(src(*lines), v), v)
            if x.endswith("declaretarget-clause-006")]


@pytest.mark.parametrize("v", [50, 52, 60])
def test_declare_target_names_no_generic_name(v):
    to = "to" if v == 50 else "enter"
    head = ["module m", "interface gen", "module procedure f1",
            "end interface gen"]
    tail = ["contains", "integer function f1(x)", "integer :: x",
            "f1 = x", "end function f1", "end module m"]
    assert dtn(head + [f"!$omp declare target {to}(f1)"] + tail, v) == []
    assert dtn(head + [f"!$omp declare target {to}(gen)"] + tail, v) == \
        [f"OMP{v}-declaretarget-clause-006"]


def test_declare_target_names_no_procedure_pointer():
    lines = ["module m", "procedure(), pointer :: pp => null()",
             "!$omp declare target enter(pp)", "end module m"]
    assert dtn(lines) == ["OMP52-declaretarget-clause-006"]


def test_declare_mapper_type_not_abstract_at_50():
    """5.0 already forbids an abstract mapper type (5.0
    §2.19.7.3)."""
    lines = ["module m", "type, abstract :: a_t", "integer :: v",
             "end type a_t", "!$omp declare mapper(a_t :: w) map(w%v)",
             "end module m"]
    assert "OMP50-declaremapper-clause-004" in violations(
        parse_program(src(*lines), 50), 50)


# ---- Tests of the oracle mutation audit (offload.engine.mutate) ------------------------------------------

import dataclasses
import difflib
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache


from offload.engine import mutate
from offload.engine.gen import Program, generate
from offload.engine.catalog import slice_atoms
from offload.engine.harness import Outcome, Result
from offload.engine.mutate import (NO_MUTATION, MutantResult, audit,
                               mutation_of, neutralise, summarise)
from offload.engine.rules import parse_program
from test_gen import _syntax, gfortran_only, omp_lib_stub  # noqa: F401

VERSIONS = (52, 60)


@lru_cache(maxsize=None)
def legal(version: int) -> dict:
    return {p.primary_atom: p for p in generate(slice_atoms(version), version)
            if p.legal and p.scope == "device"}


def body(source: str) -> str:
    """The source without its leading header comment block."""
    lines = source.splitlines(keepends=True)
    k = 0
    while k < len(lines) and lines[k].startswith("!"):
        k += 1
    return "".join(lines[k:])


def deletions(old: str, new: str) -> list[str]:
    """The deleted chunks if `new` is `old` with characters deleted, else
    fail."""
    sm = difflib.SequenceMatcher(None, old, new, autojunk=False)
    out = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        assert tag in ("equal", "delete"), (tag, old[i1:i2], new[j1:j2])
        if tag == "delete":
            out.append(old[i1:i2])
    return out


def remove_in_order(text: str, spans: list[str]) -> str:
    pos = 0
    for s in spans:
        i = text.index(s, pos)
        text, pos = text[:i] + text[i + len(s):], i
    return text


# (version, atom, the text removed, in order); each text is exactly one
# deleted span of the program body.
REPRESENTATIVE = [
    (52, "omp.clause.map.always", ["always, "]),
    (52, "omp.clause.map.close", ["close, "]),
    (52, "omp.clause.map.present", ["present, "]),
    (52, "omp.clause.map.mapper", ["mapper(mm), "]),
    (52, "omp.clause.nowait", [" nowait"]),
    (52, "omp.clause.depend", [" depend(out: w)", " depend(in: w)"]),
    (52, "omp.clause.collapse", [" collapse(2)"]),
    (52, "omp.clause.num_teams", [" num_teams(4)"]),
    (52, "omp.clause.num_teams.lower_bound", ["2: "]),
    (52, "omp.clause.device", [" device(dev)"]),
    (52, "omp.clause.defaultmap", [" defaultmap(tofrom: scalar)"]),
    (52, "omp.clause.lastprivate.conditional", ["conditional: "]),
    (60, "omp.clause.depend.in", [" depend(in: w)"]),
    (52, "omp.clause.schedule.static", [" schedule(static)"]),
    # 5.2 linear: the modifier follows the colon; the list item stays
    (52, "omp.clause.linear.ref", [": ref"]),
    (52, "omp.clause.linear.uval", [": uval"]),
    # the reporting variable stays: only the tested list items go
    (52, "omp.clause.shared", [" shared(a, b)"]),
]

@pytest.mark.parametrize("version,atom,removed", REPRESENTATIVE,
                         ids=[a for _, a, _ in REPRESENTATIVE])
def test_neutralise_clause_removes_only_that_clause(version, atom, removed):
    prog = legal(version)[atom]
    mut = neutralise(prog)
    assert mut is not None
    deletions(body(prog.source), body(mut.source))  # deletions only
    assert body(mut.source) == remove_in_order(body(prog.source), removed)
    assert f"! MUTANT of {prog.id}: removed {atom}" in mut.source
    assert mut.primary_atom == atom and mut.id != prog.id
    assert mut.legal and mut.observable == prog.observable
    assert_atom_gone(mut, version)


def assert_atom_gone(mut, version):
    """The atom is gone from every directive, except from clauses whose
    list items are all reporting variables (kept on purpose)."""
    atom = mut.primary_atom
    for d in parse_program(mut.source, version).directives:
        if atom in d.atoms:
            name = atom.split(".")[2]
            for c in d.clauses:
                if c.name == name:
                    assert set(c.args) <= mutate.INFRA_VARS, (atom, d)


def test_neutralise_keeps_continuation_lines_well_formed():
    # nowait is the last clause on the continuation line: the line stays
    prog = legal(52)["omp.clause.nowait"]
    mut = neutralise(prog)
    assert "!$omp& default(none) shared(a, b, host_flag)\n" in mut.source


def test_neutralise_leaves_probe_and_shared_memory_detector_alone():
    # map.to: the shared-memory detector's map(to: zc) is infrastructure
    prog = legal(52)["omp.directive.target_data"]
    assert "!$omp target map(to: zc)" in prog.source
    for atom, p in legal(52).items():
        if "!$omp target map(to: zc)" in p.source and atom.startswith(
                "omp.clause.map"):
            mut = neutralise(p)
            if mut is not None:
                assert "!$omp target map(to: zc)" in mut.source, atom
    probe = legal(52)["omp.directive.target_teams_loop"]
    mut = neutralise(probe)
    assert "!$omp declare target(on_dev)" in mut.source
    assert "  !$omp target map(tofrom: host_flag)\n" in mut.source


@pytest.mark.parametrize("version,atom,directive", [
    (52, "omp.directive.parallel_do", "parallel do"),
    (52, "omp.directive.target_teams_distribute_parallel_do",
     "target teams distribute parallel do"),
    (52, "omp.directive.target_data", "target data"),
])
def test_neutralise_directive_comments_out_pair(version, atom, directive):
    prog = legal(version)[atom]
    mut = neutralise(prog)
    old, new = prog.source.splitlines(), mut.source.splitlines()
    old_body, new_body = body(prog.source).splitlines(), \
        body(mut.source).splitlines()
    assert len(old_body) == len(new_body)
    changed = [(a, b) for a, b in zip(old_body, new_body) if a != b]
    starts = [a for a, _ in changed if a.strip().startswith(
        f"!$omp {directive}")]
    ends = [a for a, _ in changed if a.strip() == f"!$omp end {directive}"]
    assert len(starts) == 1 and len(ends) == 1
    for a, b in changed:
        assert a.strip().startswith("!$omp")
        ind = a[:len(a) - len(a.lstrip())]
        assert b == f"{ind}! MUTANT {a.lstrip()}", (a, b)
    # the associated statements (the DO nest, the block) are kept
    assert sum(1 for x in new if re.match(r"\s*do i = 1, n", x)) == \
        sum(1 for x in old if re.match(r"\s*do i = 1, n", x))
    tree = parse_program(mut.source, version)
    assert all(atom not in d.atoms for d in tree.directives)


def test_neutralise_combined_directive_comments_out_continuation_lines():
    prog = legal(52)["omp.directive.target_teams_distribute_parallel_do"]
    mut = neutralise(prog)
    assert "  ! MUTANT !$omp& default(none) shared(a, b, host_flag)" \
        in mut.source


# map types whose deletion would leave the default (tofrom on target,
# to/from on enter/exit data), which still does the removed thing: the
# type is REPLACED by one without the behaviour (REPLACEMENTS)
@pytest.mark.parametrize("version,atom,old,new", [
    # on target the to-type is deleted (tofrom): the program checks that
    # the region's write of a does not come back
    (52, "omp.clause.map.to", ["map(to: a) map(from: b)"],
     ["map(a) map(from: b)"]),
    (60, "omp.clause.map.to", ["map(to: a) map(from: b)"],
     ["map(a) map(from: b)"]),
    (52, "omp.clause.map.from", ["map(from: b)"], ["map(alloc: b)"]),
    (52, "omp.clause.map.tofrom", ["map(tofrom: b)"], ["map(alloc: b)"]),
    (52, "omp.clause.map.delete", ["map(delete: a)"], ["map(release: a)"]),
    (52, "omp.clause.map.alloc", ["target enter data map(to: a) map(alloc: b)"],
     ["target enter data map(to: a)"]),
    (60, "omp.clause.map.storage", ["map(to: a) map(storage: b)"],
     ["map(to: a)"]),
    (52, "omp.clause.map.release",
     ["!$omp target exit data map(from: b) map(release: a)",
      "  !$omp target exit data map(release: a)"],
     ["!$omp target exit data map(from: b)",
      "  ! MUTANT !$omp target exit data map(release: a)"]),
    (52, "omp.clause.defaultmap.scalar", ["defaultmap(tofrom: scalar)"],
     ["defaultmap(tofrom: aggregate)"]),
    (60, "omp.clause.default.aggregate", ["default(shared: aggregate)"],
     ["default(shared: scalar)"]),
])
def test_neutralise_replaces_forms_whose_default_keeps_the_behaviour(
        version, atom, old, new):
    prog = legal(version)[atom]
    mut = neutralise(prog)
    src = prog.source
    for o, n in zip(old, new):
        assert src.count(o) == 1, o
        src = src.replace(o, n)
    assert body(mut.source) == body(src)
    assert "map(tofrom: host_flag)" in mut.source


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("atom,old,new", [
    ("omp.clause.depend.iterator", "iterator(k = 1:n)", "iterator(k = 1:0)"),
    ("omp.clause.to.iterator", "iterator(k = 1:1)", "iterator(k = 1:0)"),
    ("omp.clause.from.iterator", "iterator(k = 1:1)", "iterator(k = 1:0)"),
    ("omp.clause.map.iterator", "iterator(k = 1:1)", "iterator(k = 1:0)"),
])
def test_iterator_mutant_has_an_empty_range(version, atom, old, new):
    # "If the iterator value set is empty then the effect is as if the list
    # item was not specified" (5.2 and 6.0, iterators): the clause stays,
    # its generated items go, and k is never used unset
    prog = legal(version)[atom]
    mut = neutralise(prog)
    assert body(mut.source) == body(prog.source.replace(old, new))
    assert "empty" in mutation_of(mut)


def test_map_iterator_program_maps_only_the_generated_items():
    # its own program: enter data maps the section the iterator generates
    # (k = 1: w(2:n/2)), the presence checks tell it from the elements
    # around it, an empty range maps nothing. One iterator value,
    # because list items generated from different iterator values must not
    # have the same containing array (5.2 §5.8.3 p.155, 6.0 §7.9.6 p.286);
    # the form w(k) for k = 1, 3, ... was not conforming
    for v in VERSIONS:
        src = legal(v)["omp.clause.map.iterator"].source
        assert "enter data map(iterator(k = 1:1), to: w(k + 1:n/2))" in src
        assert "c_loc(w(1)), omp_get_default_device()) == 0" in src
        assert "c_loc(w(n/2 + 1)), omp_get_default_device()) == 0" in src
        assert "c_loc(w(2)), omp_get_default_device()) /= 0" in src
        assert "omp.clause.map.iterator" not in NO_MUTATION


@pytest.mark.parametrize("version", VERSIONS)
def test_equivalent_default_contexts_hold(version):
    # the bind/default/severity equivalent defaults hold only for the
    # programs as generated: pin their contexts
    progs = legal(version)
    def lines(atom):
        return [x.strip() for x in progs[atom].source.splitlines()
                if x.strip().startswith("!$omp")]
    d = next(x for x in lines("omp.clause.default.none")
             if "default(none)" in x)
    assert d.startswith("!$omp parallel do ") and "shared(a, b)" in d
    # Default(shared) is checked on a task, where it is not the
    # default (the generating thread's private c is firstprivate there)
    assert "!$omp task default(shared)" in lines("omp.clause.default.shared")
    mut = neutralise(progs["omp.clause.default.shared"])
    assert "!$omp task\n" in mut.source and "default(" not in body(
        mut.source)


def test_ref_modifiers_are_swapped():
    # 6.0: without a ref-modifier the map applies to the pointer AND the
    # pointee, a superset of either: ref_ptee <-> ref_ptr instead
    mut = neutralise(legal(60)["omp.clause.map.ref_ptee"])
    assert "ref_ptee" not in body(mut.source)
    assert "enter data map(ref_ptr, to: p)" in mut.source
    assert "exit data map(ref_ptr, release: p)" in mut.source
    mut = neutralise(legal(60)["omp.clause.map.ref_ptr"])
    assert "map(to: a) map(ref_ptee, to: p)" in mut.source


def test_reporting_clause_does_not_switch_off_the_guard():
    # map(tofrom: host_flag) still carries map.tofrom in the mutant; the
    # rest of the program must not
    for v in VERSIONS:
        mut = neutralise(legal(v)["omp.clause.map.tofrom"])
        assert "kept on" not in mutation_of(mut)
        assert "omp.clause.map.tofrom" in mut.atoms
        assert "omp.clause.map.tofrom" not in \
            mutate.atoms_outside_infra(mut.source, v)


def test_map_from_on_exit_data_becomes_release():
    # the map.alloc program, audited for map.from: from on exit data
    prog = legal(52)["omp.clause.map.alloc"]
    assert "exit data map(from: b)" in prog.source
    p = dataclasses.replace(prog, primary_atom="omp.clause.map.from")
    mut = neutralise(p)
    assert "exit data map(release: b) map(release: a)" in mut.source
    assert "map(alloc: b)" in mut.source


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("dtype", ["in", "out", "inout", "inoutset",
                                   "mutexinoutset", "depobj"])
def test_depend_type_mutants_delete_the_dependence(version, dtype):
    atom = f"omp.clause.depend.{dtype}"
    prog = legal(version)[atom]
    mut = neutralise(prog)
    assert re.search(rf"depend\({dtype}:", body(mut.source)) is None
    deletions(body(prog.source), body(mut.source))
    assert "depend(w)" not in mut.source and "depend(obj)" not in mut.source


def test_clause_mutation_keeps_the_reporting_variable():
    for v in VERSIONS:
        mut = neutralise(legal(v)["omp.clause.map"])
        assert "!$omp target map(tofrom: host_flag)\n" in mut.source
        assert "map(to: a)" not in mut.source
        assert "map(from: b)" not in mut.source


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("atom,gone", [
    ("omp.clause.to", "!$omp target update to(a)"),
    ("omp.clause.from", "!$omp target update from(b)"),
    ("omp.clause.enter", "!$omp declare target enter(dv)"),
    ("omp.clause.link", "!$omp declare target link(dv)"),
])
def test_removing_the_required_clause_comments_out_the_directive(
        version, atom, gone):
    prog = legal(version)[atom]
    mut = neutralise(prog)
    assert gone in prog.source
    assert f"! MUTANT {gone}" in mut.source
    assert "required clause" in mutation_of(mut)


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("atom,old,new", [
    ("omp.clause.private", "private(t)", "shared(t)"),
    ("omp.clause.firstprivate", "firstprivate(c)", "shared(c)"),
    ("omp.clause.lastprivate", "lastprivate(t)", "shared(t)"),
    ("omp.clause.reduction.plus", "reduction(+: s)", "shared(s)"),
])
def test_data_sharing_clause_under_default_none_becomes_shared(
        version, atom, old, new):
    prog = legal(version)[atom]
    assert "default(none)" in prog.source and prog.source.count(old) == 1
    mut = neutralise(prog)
    assert body(mut.source) == body(prog.source.replace(old, new))


@pytest.mark.parametrize("version", VERSIONS)
def test_ordered_clause_takes_its_ordered_regions(version):
    prog = legal(version)["omp.clause.ordered"]
    mut = neutralise(prog)
    assert "! MUTANT !$omp ordered" in mut.source
    assert "! MUTANT !$omp end ordered" in mut.source
    assert re.search(r"parallel do .*\bordered\b", mut.source) is None


def test_clause_on_an_end_directive_is_removed():
    prog = legal(52)["omp.clause.reduction.task"]
    src = prog.source.replace("      !$omp end do\n",
                              "      !$omp end do nowait\n")
    assert src != prog.source
    p = dataclasses.replace(prog, source=src, primary_atom="omp.clause.nowait")
    mut = neutralise(p)
    assert "      !$omp end do\n" in mut.source
    assert "nowait" not in body(mut.source)


def test_no_mutant_equals_its_original():
    for v in VERSIONS:
        for atom, prog in legal(v).items():
            mut = neutralise(prog)
            if mut is not None:
                assert body(mut.source) != body(prog.source), atom


@pytest.mark.parametrize("atom", [
    "omp.clause.schedule.nonmonotonic",
    "omp.clause.order.unconstrained", "omp.clause.reduction.default",
    "omp.clause.linear.val", "omp.clause.ordered.n",
    "omp.clause.device.device_num",
    "omp.clause.map.ref_ptr_ptee", "omp.clause.default.none",
])
def test_equivalent_default_forms_are_not_mutated(atom):
    assert NO_MUTATION[atom]
    assert neutralise(legal(52 if atom in legal(52) else 60)[atom]) is None


def test_no_mutation_reasons_and_coverage():
    assert NO_MUTATION
    for atom, why in NO_MUTATION.items():
        assert why.strip(), atom
    for v in VERSIONS:
        for atom, prog in legal(v).items():
            mut = neutralise(prog)
            if atom in NO_MUTATION:
                assert mut is None, atom
            else:
                assert isinstance(mut, Program), atom
                # present only where the table keeps it (no weaker form) or
                # on the reporting variable's own clause
                assert atom not in mut.atoms or "kept on" in \
                    mutation_of(mut) or "made empty" in mutation_of(mut) \
                    or atom not in \
                    mutate.atoms_outside_infra(mut.source, v), atom


@pytest.mark.gfortran
@gfortran_only
@pytest.mark.parametrize("version", VERSIONS)
def test_mutant_stays_free_form_fortran(version, omp_lib_stub):
    muts = [m for m in map(neutralise, legal(version).values())
            if m is not None]
    assert len(muts) > 100
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda p: _syntax(p, omp_lib_stub), muts))
    bad = {pid: err for pid, rc, err in results if rc != 0}
    assert bad == {}


# --- the audit with a fake runner -------------------------------------------------------

def fake_result(prog: Program, tc: str, xnack: int, outcome: Outcome,
                reason: str = "") -> Result:
    return Result(program_id=prog.id, primary_atom=prog.primary_atom,
                  atoms=tuple(sorted(prog.atoms)), toolchain=tc, xnack=xnack,
                  opt="-O2", outcome=outcome, reason=reason or str(outcome),
                  flaky=False, flags="", rocm=None, stdout="", stderr="",
                  needs=tuple(prog.needs), evidence=prog.evidence,
                  observable=prog.observable)


C_8, W, R, F_8, H, A_8 = (Outcome.correct_on_device, Outcome.wrong_answer,
                    Outcome.rejected, Outcome.fell_back_to_host,
                    Outcome.harness_error, Outcome.accepted_ignored)

# atom -> {(toolchain, is_mutant): [outcome, ...]} (one per call, in order)
SCRIPT = {
    "omp.clause.collapse": {("afar", False): [C_8], ("afar", True): [W],
                            ("cce19", False): [C_8], ("cce19", True): [C_8]},
    "omp.clause.depend": {("afar", False): [C_8], ("afar", True): [C_8],
                          ("cce19", False): [C_8], ("cce19", True): [C_8]},
    "omp.clause.num_teams": {("afar", False): [R], ("afar", True): [W],
                             ("cce19", False): [C_8], ("cce19", True): [R]},
    "omp.clause.device": {("afar", False): [C_8], ("afar", True): [F_8],
                          ("cce19", False): [H], ("cce19", True): [C_8]},
    "omp.directive.target": {("afar", False): [W, C_8], ("afar", True): [W, W],
                             ("cce19", False): [C_8], ("cce19", True): [W, C_8]},
    "omp.clause.thread_limit": {("afar", False): [C_8], ("afar", True): [W],
                                ("cce19", False): [C_8], ("cce19", True): [A_8]},
    "omp.clause.private": {("afar", False): [C_8], ("afar", True): [W, W],
                           ("cce19", False): [C_8], ("cce19", True): [H]},
}
TIMEOUT = {("omp.directive.target", "afar", False, 1),
           ("omp.directive.target", "afar", True, 1),
           ("omp.directive.target", "cce19", True, 1),
           ("omp.clause.private", "afar", True, 1),
           ("omp.clause.private", "afar", True, 2)}
CRASH = {("omp.clause.thread_limit", "afar", True)}


class FakeRunner:
    def __init__(self):
        self.calls = []

    def __call__(self, prog, tc, xnack, opt="-O2", timeout_s=300, repeats=3,
                 **kw):
        mutant = "! MUTANT of " in prog.source
        key = (prog.primary_atom, tc.name, mutant)
        self.calls.append((prog.id, tc.name, xnack, opt, repeats))
        n = sum(1 for c in self.calls if c[:2] == (prog.id, tc.name))
        outcome = SCRIPT[prog.primary_atom][(tc.name, mutant)][n - 1]
        reason = ("timeout" if key + (n,) in TIMEOUT else
                  "crash: SIGSEGV; without mandatory: crash: SIGSEGV"
                  if key in CRASH else
                  "ran_on_host=1 check=pass" if outcome == F_8 else
                  "check_fail: ran_on_host=0 check=fail" if outcome == W
                  else "")
        return fake_result(prog, tc.name, xnack, outcome, reason)


def run_fake(monkeypatch, atoms, version=52, no_mutation=None):
    if no_mutation is not None:
        monkeypatch.setattr(mutate, "NO_MUTATION", no_mutation)
    runner = FakeRunner()
    res = audit(version, ["afar", "cce19"], workers=4,
                only=lambda p: p.primary_atom in atoms, runner=runner)
    return res, runner


def test_status_table(monkeypatch):
    res, runner = run_fake(monkeypatch, set(SCRIPT))
    got = {(r.primary_atom, r.toolchain): (r.status, r.original, r.mutant)
           for r in res}
    assert got == {
        ("omp.clause.collapse", "afar"): ("killed", "correct_on_device",
                                          "wrong_answer"),
        ("omp.clause.collapse", "cce19"): ("survived", "correct_on_device",
                                           "correct_on_device"),
        ("omp.clause.depend", "afar"): ("survived", "correct_on_device",
                                        "correct_on_device"),
        ("omp.clause.depend", "cce19"): ("survived", "correct_on_device",
                                         "correct_on_device"),
        ("omp.clause.num_teams", "afar"): ("inconclusive", "rejected",
                                           "wrong_answer"),
        ("omp.clause.num_teams", "cce19"): ("inconclusive",
                                            "correct_on_device", "rejected"),
        ("omp.clause.device", "afar"): ("killed", "correct_on_device",
                                        "fell_back_to_host"),
        ("omp.clause.device", "cce19"): ("inconclusive", "harness_error",
                                         "correct_on_device"),
        # timeouts are re-run once: the second run counts
        ("omp.directive.target", "afar"): ("killed", "correct_on_device",
                                           "wrong_answer"),
        ("omp.directive.target", "cce19"): ("survived", "correct_on_device",
                                            "correct_on_device"),
        # a crashing mutant is killed (kind crash); the compiler saying it
        # ignored something, a harness error or a repeated timeout of the
        # mutant are inconclusive
        ("omp.clause.thread_limit", "afar"): ("killed", "correct_on_device",
                                              "wrong_answer"),
        ("omp.clause.thread_limit", "cce19"): ("inconclusive",
                                               "correct_on_device",
                                               "accepted_ignored"),
        ("omp.clause.private", "afar"): ("inconclusive", "correct_on_device",
                                         "wrong_answer"),
        ("omp.clause.private", "cce19"): ("inconclusive",
                                          "correct_on_device",
                                          "harness_error"),
    }
    kind = {(r.primary_atom, r.toolchain): r.kill_kind for r in res
            if r.status == "killed"}
    assert kind == {("omp.clause.collapse", "afar"): "check_fail",
                    ("omp.clause.device", "afar"): "fell_back_to_host",
                    ("omp.directive.target", "afar"): "check_fail",
                    ("omp.clause.thread_limit", "afar"): "crash"}
    assert all(r.kill_kind == "" for r in res if r.status != "killed")
    why = {(r.primary_atom, r.toolchain): r.reason for r in res}
    assert why[("omp.clause.num_teams", "cce19")].startswith(
        "mutant_compile_failure")
    assert why[("omp.clause.num_teams", "afar")].startswith("original_")
    assert why[("omp.clause.private", "afar")].startswith("mutant_timeout")
    assert why[("omp.clause.private", "cce19")].startswith(
        "mutant_harness_error")
    assert why[("omp.clause.thread_limit", "cce19")].startswith(
        "mutant_accepted_ignored")
    assert all(r.version == 52 and r.xnack == 0 for r in res)
    # copy mode, -O2, one repeat; each original run once per toolchain
    # (timeouts once more)
    assert {c[2:] for c in runner.calls} == {(0, "-O2", 1)}
    orig = [c for c in runner.calls if not c[0].endswith("-mutant")]
    assert len(orig) == 2 * len(SCRIPT) + 1
    # deterministic order
    assert res == sorted(res, key=lambda r: (r.version, r.program_id,
                                             r.toolchain))


def test_status_not_applicable(monkeypatch):
    res, runner = run_fake(monkeypatch, {"omp.clause.depend"},
                           no_mutation={"omp.clause.depend": "a reason"})
    assert {(r.toolchain, r.status, r.reason) for r in res} == {
        ("afar", "not_applicable", "a reason"),
        ("cce19", "not_applicable", "a reason")}
    assert runner.calls == []


def test_audit_skips_unobservable_and_unverified(monkeypatch):
    seen = []

    def only(p):
        seen.append(p)
        return False
    audit(52, ["afar"], only=only, runner=FakeRunner())
    from offload.engine.gen import AUDITED
    assert seen and all(p.legal and p.observable
                        and p.evidence in AUDITED for p in seen)


def test_zero_copy_programs_run_under_xnack1():
    progs = [p for p in mutate.audit_programs(60) if "zero_copy" in p.needs]
    assert progs
    atom = progs[0].primary_atom
    calls = []

    def runner(p, tc, xnack, opt="-O2", timeout_s=300, repeats=3, **kw):
        calls.append(xnack)
        return fake_result(p, tc.name, xnack, C_8)
    res = audit(60, ["afar"], only=lambda p: p.primary_atom == atom,
                runner=runner)
    assert calls == [1, 1]
    assert res[0].xnack == 1 and "needs_zero_copy" in res[0].reason


def mr(atom, tc, status, version=52):
    return MutantResult(program_id=f"p-{atom}", primary_atom=atom,
                        version=version, toolchain=tc, status=status,
                        original="", mutant="", reason="")


def test_summarise():
    res = [mr("a", "afar", "killed"), mr("a", "cce19", "survived"),
           mr("b", "afar", "survived"), mr("b", "cce19", "inconclusive"),
           mr("c", "afar", "inconclusive"), mr("c", "cce19", "inconclusive"),
           mr("d", "afar", "not_applicable"), mr("d", "cce19",
                                                  "not_applicable"),
           mr("e", "afar", "survived"), mr("e", "cce19", "survived")]
    s = summarise(res)
    assert {k: v["status"] for k, v in s.items()} == {
        "a": "valid", "b": "weak", "c": "unknown", "d": "unknown",
        "e": "weak"}
    assert s["a"]["toolchains"] == {"afar": "killed", "cce19": "survived"}
    assert s["d"]["not_applicable"] is True
    assert s["a"]["not_applicable"] is False


def test_partial_audit_report_never_overwrites_the_committed_files(tmp_path):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "tools"))
    import oracle_audit
    out = tmp_path / "r.jsonl"
    out.write_text("")
    before = (oracle_audit.MD.read_text(), oracle_audit.SUMMARY.read_text())
    assert oracle_audit.main(["--report-only", "--out", str(out)]) == 0
    assert (tmp_path / "r.partial.md").is_file()
    assert (tmp_path / "r.partial.summary.json").is_file()
    assert (oracle_audit.MD.read_text(), oracle_audit.SUMMARY.read_text()) \
        == before
    with pytest.raises(SystemExit):
        oracle_audit.main(["--report-only", "--out", str(out), "--summary",
                           str(oracle_audit.SUMMARY)])


@pytest.mark.parametrize("version,flag", [(60, "-fopenmp-version=60"),
                                          (52, "")])
def test_audit_compiles_with_the_matrix_version_flags(version, flag):
    """The audit must build AFAR 6.0 programs as the matrix does
    (run_matrix.for_version), not in AFAR's default 5.2 mode."""
    atom = "omp.directive.target"
    flags = []

    def runner(p, tc, xnack, opt="-O2", timeout_s=300, repeats=3, **kw):
        flags.append((tc.name, tc.flags()))
        return fake_result(p, tc.name, xnack, C_8)
    audit(version, ["afar", "cce19"], only=lambda p: p.primary_atom == atom,
          runner=runner)
    afar = {f for n, f in flags if n == "afar"}
    cce = {f for n, f in flags if n == "cce19"}
    assert afar and cce
    if flag:
        assert all(flag in f for f in afar)
    else:
        assert not any("-fopenmp-version" in f for f in afar)
    assert not any("-fopenmp-version" in f for f in cce)


# --- Present probes -------------------------------------------------------

@pytest.mark.parametrize("version", [52, 60])
@pytest.mark.parametrize("atom,before,after", [
    ("omp.clause.map.present", "map(present, to: a) map(from: b)",
     "map(to: a) map(from: b)"),
    ("omp.clause.to.present", "to(present: a)", "to(a)"),
    ("omp.clause.from.present", "from(present: b)", "from(b)")])
def test_present_probe_mutant_drops_only_the_modifier(atom, before, after,
                                                     version):
    from offload.engine.mutate import neutralise
    (p,) = [q for q in generate([atom], version) if q.legal]
    m = neutralise(p)
    assert m is not None and m.expect == "error_termination"
    probe = [ln for ln in p.source.splitlines()
             if before in ln and ln.lstrip().startswith("!$omp")]
    assert len(probe) == 1
    assert probe[0].replace(before, after) in m.source.splitlines()
    assert "present" not in "".join(
        ln for ln in m.source.splitlines() if ln.lstrip().startswith("!$omp"))


# --- Forms that now have a mutation -----------------------------------

@pytest.mark.parametrize("atom", [
    "omp.clause.bind.parallel", "omp.clause.bind.teams",
    "omp.clause.to.mapper", "omp.clause.from.mapper",
    "omp.clause.defaultmap.all", "omp.clause.severity.fatal",
    "omp.clause.default"])
def test_round1_forms_are_mutated(atom):
    assert atom not in NO_MUTATION
    for v in VERSIONS:
        if atom in legal(v):
            assert neutralise(legal(v)[atom]) is not None


@pytest.mark.parametrize("version", VERSIONS)
def test_defaultmap_all_is_replaced_by_scalar(version):
    m = neutralise(legal(version)["omp.clause.defaultmap.all"])
    assert "defaultmap(to: scalar)" in m.source
    assert "defaultmap(to: all)" not in body(m.source)


def test_severity_fatal_is_replaced_by_warning():
    m = neutralise(legal(60)["omp.clause.severity.fatal"])
    d = [x for x in body(m.source).splitlines() if "!$omp error" in x]
    assert len(d) == 1 and "severity(warning)" in d[0]


@pytest.mark.parametrize("atom,gone", [
    ("omp.clause.message", "message("),
    ("omp.clause.severity", "severity("),
    ("omp.clause.severity.warning", "severity(")])
def test_error_directive_mutants_drop_the_clause(atom, gone):
    m = neutralise(legal(60)[atom])
    (d,) = [x for x in body(m.source).splitlines() if "!$omp error" in x]
    assert gone not in d and "at(compilation)" in d


# --- Mutants must be legal programs --------------------------------------------------------------------

@pytest.mark.parametrize("version", VERSIONS)
def test_every_audited_mutant_is_a_legal_program(version):
    """A mutant that breaks a restriction is no evidence: removing bind
    from an orphaned loop violates loop-nesting-001 (5.2 §11.7 p.257, 6.0
    §13.8 p.424)."""
    from offload.engine.rules import parse_program, violations
    bad = {}
    for p in mutate.audit_programs(version):
        m = neutralise(p)
        if m is not None:
            found = violations(parse_program(m.source, version), version)
            if found:
                bad[p.primary_atom] = found
    assert bad == {}


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("atom", ["omp.clause.bind.parallel",
                                  "omp.clause.bind.teams"])
def test_bind_mutant_binds_to_the_thread(atom, version):
    m = neutralise(legal(version)[atom])
    kind = atom.split(".")[-1]
    assert "!$omp loop bind(thread)" in m.source
    assert f"bind({kind})" not in body(m.source)


def test_illegal_mutant_is_inconclusive_and_not_run(monkeypatch):
    """The audit checks every mutant with the rule checker: a mutant that
    violates a rule is inconclusive ('mutant is illegal'), never a kill."""
    atom = "omp.clause.collapse"
    real = mutate.neutralise

    def illegal(prog):
        m = real(prog)
        return dataclasses.replace(m, source=m.source.replace(
            "collapse(2)", "collapse(3)") if "collapse(2)" in m.source
            else m.source.replace("schedule(static)",
                                  "schedule(static) collapse(3)"))
    monkeypatch.setattr(mutate, "neutralise", illegal)
    runner = FakeRunner()
    res = audit(52, ["afar"], only=lambda p: p.primary_atom == atom,
                runner=runner)
    assert [r.status for r in res] == ["inconclusive"]
    assert res[0].reason.startswith("mutant is illegal: OMP52-")
    assert all("-mutant" not in c[0] for c in runner.calls)


# --- The semantic atom's mutant -----------------------------------------

@pytest.mark.parametrize("version", VERSIONS)
def test_defaultmap_character_mutant_makes_characters_firstprivate(version):
    """The mutant treats the character variables as an integer scalar is
    treated implicitly (firstprivate): a legal program whose check must
    fail on a conforming implementation."""
    from offload.engine.rules import violations
    p = legal(version)["omp.clause.defaultmap.character"]
    m = neutralise(p)
    assert m.id == p.id + "-mutant"
    assert ("!$omp target map(to: a) map(from: b) map(tofrom: host_flag) "
            "firstprivate(ch, s)") in m.source
    assert "omp.clause.firstprivate" in m.atoms
    assert "omp.clause.defaultmap.character" not in m.atoms
    assert violations(parse_program(m.source, version), version) == []
    assert "added firstprivate(ch, s) to target" in mutation_of(m)
    assert p in mutate.audit_programs(version)


# ---- Map mutants (offload.engine.mutate.map_mutants) and the per-mode ------------------------------------



from offload.engine.c_gen import all_c_programs
from offload.engine.gen import generate
from offload.engine.mutate import (MAP_KINDS, illegal, map_audit, map_mutants,
                               map_summary)


@lru_cache(maxsize=None)
def progs(version, lang="f90"):
    ps = all_c_programs(version) if lang == "c" else \
        generate(slice_atoms(version), version)
    return {p.primary_atom: p for p in ps if p.legal and p.scope == "device"}


def test_kinds():
    assert MAP_KINDS == ("weaken_map", "swap_to_from", "drop_map",
                         "drop_update")


def test_weaken_and_swap_on_a_target_region():
    p = progs(52)["omp.clause.collapse"]
    m = map_mutants(p)
    w = m["weaken_map"].source
    assert "map(alloc: a) map(alloc: b) map(alloc: tid, nthr)" in w
    assert "map(tofrom: host_flag)" in w  # infrastructure untouched
    s = m["swap_to_from"].source
    assert "map(from: a) map(to: b) map(to: tid, nthr)" in s
    assert "map(tofrom: host_flag)" in s
    assert "drop_update" not in m  # no target update in the program
    for k, mut in m.items():
        assert mut.id == f"{p.id}-map-{k}"
        assert f"MAP MUTANT of {p.id}: {k}" in mut.source
        parse_program(mut.source, 52)


def test_update_mutants():
    p = progs(52)["omp.clause.to"]
    m = map_mutants(p)
    assert "! MUTANT !$omp target update to(a)" in m["drop_update"].source
    assert "! MUTANT !$omp target update from(b)" in m["drop_update"].source
    s = m["swap_to_from"].source
    assert "!$omp target update from(a)" in s
    assert "!$omp target update to(b)" in s
    # enter/exit data keep legal map types under swap
    assert "target enter data map(to: a)" in s
    # drop_map comments the data directives that need a map clause
    d = m["drop_map"].source
    assert "! MUTANT !$omp target enter data" in d
    assert "!$omp target map(tofrom: host_flag)" in d


def test_c_programs_get_map_mutants():
    p = progs(52, "c")["omp.clause.collapse"]
    m = map_mutants(p)
    assert "weaken_map" in m
    assert "alloc:" in m["weaken_map"].source


def test_acc_mutants_rename_data_clauses():
    ps = {p.primary_atom: p for p in generate(slice_atoms(34), 34)
          if p.legal and p.scope == "device"}
    p = ps["acc.clause.copyin"]
    m = map_mutants(p)
    assert "create(" in m["weaken_map"].source
    assert "!$acc parallel loop create(a) create(b) copy(host_flag)" in \
        m["weaken_map"].source
    assert "!$acc serial copyin(zc)" in m["weaken_map"].source  # detector


@pytest.mark.parametrize("version", (50, 52, 60))
def test_every_fortran_map_mutant_parses_and_is_legal_mostly(version):
    n = bad = 0
    for p in progs(version).values():
        for k, mut in map_mutants(p).items():
            n += 1
            bad += bool(illegal(mut, version))
    assert n > 100
    assert bad < n // 4


def fake(outcomes):
    """runner(prog, tc, xnack, ...) -> Result with outcomes[(suffix, x)]."""
    def run(prog, tc, x, opt, timeout_s=0, repeats=1):
        kind = prog.id.split("-map-")[1] if "-map-" in prog.id else "orig"
        o = outcomes.get((kind, x), Outcome.correct_on_device)
        return Result(program_id=prog.id, primary_atom=prog.primary_atom,
                      atoms=(), toolchain=tc.name, xnack=x, opt=opt,
                      outcome=o, reason="check failed" if o != Outcome
                      .correct_on_device else "", flaky=False, flags="",
                      rocm=None, device="", compiler="", stdout="",
                      stderr="", needs=(), evidence="construct",
                      observable=True, legal=True, violates=None,
                      version=52)
    return run


def test_map_audit_records_the_mode_that_kills():
    out = {("weaken_map", 0): Outcome.wrong_answer,
           ("swap_to_from", 0): Outcome.wrong_answer,
           ("swap_to_from", 1): Outcome.wrong_answer}
    rs = map_audit(52, ["afar"], runner=fake(out), workers=2,
                   only=lambda p: p.primary_atom == "omp.clause.collapse")
    by = {(r.kind, r.xnack): r.status for r in rs}
    assert by[("weaken_map", 0)] == "killed"
    assert by[("weaken_map", 1)] == "survived"
    assert by[("swap_to_from", 1)] == "killed"
    s = map_summary(rs)["omp.clause.collapse"]
    assert s["kinds"]["weaken_map"] == "x0_only"
    assert s["kinds"]["swap_to_from"] == "both"
    assert s["kinds"]["drop_map"] == "neither"
    assert s["caught"] == "both"
    assert s["copy_mode_only"] == ["weaken_map"]


def test_map_summary_x0_only_atom():
    out = {("weaken_map", 0): Outcome.wrong_answer}
    rs = map_audit(52, ["afar", "cce19"], runner=fake(out), workers=2,
                   only=lambda p: p.primary_atom == "omp.clause.collapse")
    s = map_summary(rs)["omp.clause.collapse"]
    assert s["caught"] == "x0_only"


def _tool():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "map_audit_tool",
        Path(__file__).resolve().parent.parent.parent / "tools" / "campaigns" / "map_audit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_tool_run_resumes_and_report_writes_summary(tmp_path, monkeypatch):
    import json
    tool = _tool()
    out = {("weaken_map", 0): Outcome.wrong_answer}
    real = tool.map_audit

    def fake_audit(v, tcs, **kw):
        kw.pop("timeout_s", None)
        return real(v, tcs, runner=fake(out), **kw)
    monkeypatch.setattr(tool, "map_audit", fake_audit)
    res = tmp_path / "res"
    f = res / "f90.52.afar.jsonl"
    only = sorted(p.id for p in progs(52).values()
                  if p.primary_atom in ("omp.clause.collapse",
                                        "omp.clause.to"))
    monkeypatch.setattr(tool, "audit_programs", lambda v, only=None,
                        lang="f90": [p for p in progs(52).values()
                                     if p.id in only_ids])
    only_ids = set(only)
    assert tool.main(["run", "--versions", "52", "--toolchains", "afar",
                      "--out", str(f), "--batch", "1"]) == 0
    n = len(f.read_text().splitlines())
    assert n > 0
    assert tool.main(["run", "--versions", "52", "--toolchains", "afar",
                      "--out", str(f)]) == 0
    assert len(f.read_text().splitlines()) == n  # resumed: nothing new
    md, sm = tmp_path / "m.md", tmp_path / "s.json"
    assert tool.main(["report", "--results", str(res), "--md", str(md),
                      "--summary", str(sm)]) == 0
    doc = json.loads(sm.read_text())
    e = doc["groups"]["f90"]["52"]["omp.clause.collapse"]
    assert e["kinds"]["weaken_map"] == "x0_only"
    assert e["caught"] == "x0_only"
    assert "| f90 | 5.2 | `omp.clause.collapse` |" in md.read_text()


def test_oracle_audit_report_carries_the_map_audit_by_mode():
    """The primary-atom audit report has a section with the
    map-mutant audit's per-mode result for its own group."""
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent.parent
    spec = importlib.util.spec_from_file_location(
        "oracle_audit_t26", root / "tools" / "campaigns" / "oracle_audit.py")
    oa = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oa)
    doc = {"groups": {"f90": {"52": {
        "omp.clause.map.to": {"program": "p", "caught": "x0_only",
                              "kinds": {"weaken_map": "x0_only"},
                              "copy_mode_only": ["weaken_map"]},
        "omp.clause.collapse": {"program": "q", "caught": "both",
                                "kinds": {"weaken_map": "both"},
                                "copy_mode_only": []}}}}}
    lines = "\n".join(oa.map_mode_section(doc, "f90"))
    assert "## Map mutants by memory mode" in lines
    assert "| 5.2 | 1 | 1 | 0 | 0 |" in lines
    assert "`omp.clause.map.to`" in lines
    assert oa.map_mode_section(doc, "acc")[-1] == "No map-audit results."


def test_map_summary_keeps_inconclusive_apart_from_neither():
    """An atom whose map mutants were never conclusive
    (original not correct, illegal or rejected mutants) is `inconclusive`,
    not `neither` (survived)."""
    out = {("orig", 0): Outcome.rejected, ("orig", 1): Outcome.rejected}
    rs = map_audit(52, ["afar"], runner=fake(out), workers=2,
                   only=lambda p: p.primary_atom == "omp.clause.collapse")
    s = map_summary(rs)["omp.clause.collapse"]
    assert set(s["kinds"].values()) == {"inconclusive"}
    assert s["caught"] == "inconclusive"


def test_tool_run_one_mode_for_the_gfx90a_toolchains(tmp_path, monkeypatch):
    """Tioga runs at HSA_XNACK=0 only (--modes 0)."""
    import json
    tool = _tool()
    real = tool.map_audit
    seen = {}

    def fake_audit(v, tcs, **kw):
        kw.pop("timeout_s", None)
        seen["modes"] = kw.get("modes")
        return real(v, tcs, runner=fake({}), **kw)
    monkeypatch.setattr(tool, "map_audit", fake_audit)
    only_ids = {p.id for p in progs(52).values()
                if p.primary_atom == "omp.clause.to"}
    monkeypatch.setattr(tool, "audit_programs", lambda v, only=None,
                        lang="f90": [p for p in progs(52).values()
                                     if p.id in only_ids])
    f = tmp_path / "f90.52.afar_g90.jsonl"
    assert tool.main(["run", "--versions", "52", "--toolchains", "afar",
                      "--modes", "0", "--out", str(f)]) == 0
    assert seen["modes"] == [0]
    rows = [json.loads(ln) for ln in f.read_text().splitlines()]
    assert rows and {r["xnack"] for r in rows} == {0}
    meta = json.loads((tmp_path / "f90.52.afar_g90.jsonl.meta.json")
                      .read_text())
    assert meta["runs"][-1]["modes"] == [0]


def _mm(pid, kind, status, tc="afar_g90", xnack=0, version=52):
    from offload.engine.mutate import MapMutantResult
    return MapMutantResult(program_id=pid, primary_atom="omp.clause.x",
                           version=version, lang="f90", toolchain=tc,
                           kind=kind, xnack=xnack, status=status,
                           original="correct_on_device",
                           mutant="correct_on_device", reason="r")


def test_gfx90a_survivors_are_classified():
    """On the discrete GPU a map mutant that survives is an
    equivalent mutant of a probe, covered (a stronger transfer change of
    the same program is killed), a reviewed compiler behaviour, or an
    oracle weakness to fix."""
    tool = _tool()
    rs = [_mm("probe", "weaken_map", "survived"),
          _mm("cov", "drop_map", "survived"),
          _mm("cov", "swap_to_from", "killed"),
          _mm("omp52-clause-defaultmap-tofrom", "weaken_map", "survived",
              tc="cce19_g90"),
          _mm("weak", "weaken_map", "survived"),
          _mm("weak", "drop_map", "inconclusive")]
    rs.append(_mm("uninit", "drop_map", "survived"))
    rs.append(_mm("uninit", "weaken_map", "killed"))
    expect = {"probe": "error_termination"}
    by = tool.g90_index(rs)
    cls = {r.program_id: tool.survivor_class(
        r, by, lambda v, lang, pid: expect.get(pid, "result"),
        lambda r: ["nthr"] if r.program_id == "uninit" else [])[0]
        for r in rs if r.status == "survived"}
    assert cls == {"probe": "equivalent_probe", "cov": "covered",
                   "omp52-clause-defaultmap-tofrom": "compiler_copies",
                   "weak": "oracle_weakness",
                   "uninit": "oracle_weakness_uninit"}
    assert set(cls.values()) <= set(tool.SURVIVOR_CLASSES)


def test_gfx90a_report_compares_with_mi300a_copy_mode(tmp_path):
    import json
    tool = _tool()
    g = [_mm("p", "weaken_map", "killed"), _mm("q", "drop_map", "survived"),
         _mm("q", "weaken_map", "killed")]
    x0 = [_mm("p", "weaken_map", "survived", tc="afar"),
          _mm("q", "drop_map", "survived", tc="afar"),
          _mm("q", "drop_map", "killed", tc="afar", xnack=1)]
    md, doc = tool.render_g90(g, x0, lambda v, lang, pid: "result",
                              lambda r: [])
    assert "| p | weaken_map | afar | survived | killed |" in md
    assert doc["survivors"]["covered"] == 1
    assert doc["agree_with_x0"] == {"same": 1, "differ": 1}
    assert not doc["oracle_weakness"]
    json.dumps(doc)


def test_committed_gfx90a_audit_classifies_uninit_survivors():
    """Survivors whose check reads a from-mapped item
    the host never set are oracle_weakness_uninit (mechanically detected),
    never `covered`; the hardening list names every such program."""
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent.parent
    doc = json.loads((root / "tests" / "data" /
                      "map_audit_g90_summary.json").read_text())
    n = doc["survivors"]["oracle_weakness_uninit"]
    # Hardened every listed program: no such survivor remains
    assert n == len(doc["oracle_weakness_uninit"]) == 0
    assert doc["hardening_list"] == []
    assert doc["survivors"]["oracle_weakness"] == len(doc["oracle_weakness"])
    listed = (root / "data" / "reports" / "uninit-from-scalars.txt").read_text()
    for e in doc["oracle_weakness_uninit"]:
        assert e.split()[0] in listed
    assert doc["uninit_by_toolchain"]


# --- Checks that read uninitialized from-mapped items --

F_UNINIT = """program p
  integer :: nthr, nref, c
  integer :: b(4)
  c = 7
  b = 0
  !$omp target map(from: nthr) map(tofrom: c, b) map(from: nref)
    nthr = 4
  !$omp end target
  ok = all(b == 0) .and. (nthr >= 1) .and. (c == 7)
  print *, ok
end program p
"""

C_UNINIT = """int main(void) {
  int nthr;
  int b[4];
  for (int i = 0; i < 4; i++) b[i] = 0;
  #pragma omp target map(from: nthr) map(tofrom: b)
  { nthr = 2; }
  ok = (nthr >= 1) && t1_;
  return 0;
}
"""


def test_uninit_from_items_fortran_and_c():
    from offload.engine.mutate import uninit_from_items
    # nref is never read by the check, c and b are set on the host
    assert uninit_from_items(F_UNINIT) == ["nthr"]
    assert uninit_from_items(C_UNINIT) == ["nthr"]
    assert uninit_from_items(F_UNINIT.replace("  c = 7\n",
                                              "  c = 7\n  nthr = -1\n")) == []


def test_uninit_affected_by_a_mutant():
    from offload.engine.mutate import uninit_affected
    dropped = F_UNINIT.replace(" map(from: nthr)", "")
    assert uninit_affected(F_UNINIT, dropped) == ["nthr"]
    weakened = F_UNINIT.replace("map(from: nthr)", "map(alloc: nthr)")
    assert uninit_affected(F_UNINIT, weakened) == ["nthr"]
    commented = F_UNINIT.replace("  !$omp target map(from: nthr)",
                                 "  ! MUTANT !$omp target map(from: nthr)")
    assert uninit_affected(F_UNINIT, commented) == ["nthr"]
    assert uninit_affected(F_UNINIT, F_UNINIT) == []


def test_uninit_from_items_openacc_copyout():
    from offload.engine.mutate import uninit_from_items
    src = ("program p\n  integer :: g\n  !$acc parallel copyout(g)\n"
           "    g = 3\n  !$acc end parallel\n  ok = (g == 3)\nend program p\n")
    assert uninit_from_items(src) == ["g"]
    assert uninit_from_items(src.replace("  !$acc parallel",
                                         "  g = 0\n  !$acc parallel")) == []


# --- The detector's known limits -----------

def _f(decls, init, region_maps="map(from: x)", body="x = 4",
       check="(x == 4)", module=""):
    return (module + "program p\n" + "".join(f"  {d}\n" for d in decls)
            + "".join(f"  {s}\n" for s in init)
            + f"  !$omp target {region_maps}\n    {body}\n  !$omp end target\n"
            + f"  ok = {check}\n  print *, ok\nend program p\n")


def test_uninit_not_flagged_when_initialized_otherwise():
    """Over-listing found by a review: a declaration or DATA initializer, a
    call that receives the item, a memset, a derived-type component or a
    C element of a two-dimensional array assigned on the host."""
    from offload.engine.mutate import uninit_from_items
    assert uninit_from_items(_f(["integer :: x"], [])) == ["x"]
    assert uninit_from_items(_f(["integer :: x = -1"], [])) == []
    assert uninit_from_items(_f(["integer :: y, x = -1"], [])) == []
    assert uninit_from_items(_f(["integer :: x", "data x /-1/"], [])) == []
    assert uninit_from_items(_f(["integer :: x"], ["call setup(x)"])) == []
    dt = ["type(t) :: s"]
    assert uninit_from_items(_f(dt, ["s%x = -1"], "map(from: s)", "s%x = 4",
                                "(s%x == 4)")) == []
    assert uninit_from_items(_f(dt, [], "map(from: s)", "s%x = 4",
                                "(s%x == 4)")) == ["s"]
    c2 = ("int main(void) {\n  int cnt[4][2];\n"
          "  for (int i = 0; i < 4; i++)\n    for (int j = 0; j < 2; j++)\n"
          "      cnt[i][j] = 0;\n"
          "  #pragma omp target map(tofrom: cnt)\n  { cnt[0][0] = 1; }\n"
          "  ok = cnt[0][0] == 1;\n  return 0;\n}\n")
    assert uninit_from_items(c2) == []
    assert uninit_from_items(c2.replace("      cnt[i][j] = 0;\n",
                                        "      ;\n")) == ["cnt"]
    cm = ("int main(void) {\n  struct q s;\n  memset(&s, 0, sizeof s);\n"
          "  #pragma omp target map(from: s)\n  { s.v = 1; }\n"
          "  ok = s.v == 1;\n  return 0;\n}\n")
    assert uninit_from_items(cm) == []
    assert uninit_from_items(cm.replace("  memset(&s, 0, sizeof s);\n",
                                        "")) == ["s"]
    assert uninit_from_items(cm.replace("  memset(&s, 0, sizeof s);\n",
                                        "  s.v = -1;\n")) == []


def test_uninit_ignores_device_and_procedure_assignments():
    """An assignment inside an earlier device region, or in a module or
    internal procedure, does not set the host's item (false negatives the
    review found)."""
    from offload.engine.mutate import uninit_from_items
    src = ("program p\n  integer :: x\n  !$omp target enter data map(alloc: x)\n"
           "  !$omp target\n    x = 1\n  !$omp end target\n"
           "  !$omp target exit data map(from: x)\n  ok = (x == 1)\nend program p\n")
    assert uninit_from_items(src) == ["x"]
    mod = ("module m\ncontains\n  subroutine s(x)\n    integer :: x\n"
           "    x = 2\n  end subroutine s\nend module m\n")
    assert uninit_from_items(_f(["integer :: x"], [], module=mod)) == ["x"]
    acc = ("program p\n  integer :: x\n  !$acc enter data create(x)\n"
           "  !$acc serial\n    x = 1\n  !$acc end serial\n"
           "  !$acc exit data copyout(x)\n  ok = (x == 1)\nend program p\n")
    assert uninit_from_items(acc) == ["x"]
    c = ("int main(void) {\n  int x;\n  #pragma omp target enter data map(alloc: x)\n"
         "  #pragma omp target\n  {\n    x = 1;\n  }\n"
         "  #pragma omp target exit data map(from: x)\n  ok = (x == 1);\n"
         "  return 0;\n}\n")
    assert uninit_from_items(c) == ["x"]


def test_uninit_c_check_after_a_standalone_directive():
    """C: when the last directive is standalone (exit data, update,
    taskwait) the statement after it belongs to the check (the
    defaultmap-pointer programs' pw)."""
    from offload.engine.mutate import uninit_from_items
    src = ("int main(void) {\n  int *pw;\n  int *wp = malloc(8);\n"
           "  #pragma omp target map(from: pw)\n  {\n    pw = wp;\n  }\n"
           "  #pragma omp target exit data map(delete: wp[0:2])\n"
           "  if (!shared_mem) pres = pres && (pw == wp);\n"
           "  ok = pres;\n  return 0;\n}\n")
    assert uninit_from_items(src) == ["pw"]
    assert uninit_from_items(src.replace("  int *pw;\n",
                                         "  int *pw = NULL;\n")) == []


def test_uninit_c_section_needs_element_initialization():
    """A C pointer section (p[0:n]) is initialized by its elements, not by
    assigning the pointer (malloc)."""
    from offload.engine.mutate import uninit_from_items
    src = ("int main(void) {\n  int *p;\n  p = malloc(4 * sizeof *p);\n"
           "  #pragma omp target map(from: p[0:4])\n  { p[0] = 1; }\n"
           "  ok = p[0] == 1;\n  return 0;\n}\n")
    assert uninit_from_items(src) == ["p"]
    assert uninit_from_items(src.replace(
        "  #pragma", "  for (int i = 0; i < 4; i++) p[i] = -1;\n  #pragma",
        1)) == []


def test_no_legal_catalog_program_reads_an_uninitialized_from_item():
    """Every legal catalog program initializes each item it maps
    back (from/tofrom, OpenACC copy/copyout) and reads in its check to a
    value the check rejects before the region, so a lost copy-back fails
    deterministically (data/reports/uninit-from-scalars.txt)."""
    assert _tool().uninit_list() == []


def test_uninit_prior_region_copy_back_is_not_host_initialization():
    """An item first set by a prior
    target region's copy-back is still flagged (the first region that maps
    it back is judged on uninitialized memory if that copy-back is lost);
    a host assignment before the first region clears it."""
    from offload.engine.mutate import uninit_from_items
    src = ("program p\n  integer :: x\n"
           "  !$omp target map(from: x)\n    x = 1\n  !$omp end target\n"
           "  !$omp target map(tofrom: x)\n    x = x + 1\n  !$omp end target\n"
           "  ok = (x == 2)\nend program p\n")
    assert uninit_from_items(src) == ["x"]
    assert uninit_from_items(src.replace("  integer :: x\n",
                                         "  integer :: x\n  x = -1\n")) == []


# ---- Every finding in this batch carries at least one verified spec citation -----------------------------



from offload.engine.site import data as D

ROOT_10 = Path(__file__).resolve().parent.parent.parent
IDS = """stress/cce-teams-reduction-many-teams-wrap stress/cce-c-flto-offload-dropped
oop/cce-class-is-device-link oop/gcc-vtab-not-marked-for-offload
oop/nvhpc-polymorphism-runtime-unsupported fuzz/s1-9914-cce19 fuzz/1505-cce20
fuzz/1540-afar fuzz/1978-cce19 fuzz/2334-cce19 fuzz/591-cce19 fuzz/650-afar
fuzz/916-afar fuzz/98-cce19 fuzz/b1-121-afar fuzz/b2-209-cce19 fuzz/b2-68-afar
fuzz/b3-188-cce19 fuzz/b3-278-cce19 fuzz/b3-54-afar fuzz/b3-61-cce20
fuzz/b4-86-cce19 fuzz/par-s1-2082-gcc_g90""".split()


def _file(fid):
    hits = sorted((ROOT_10 / "data" / "findings").glob(fid + ".*"))
    assert len(hits) == 1, fid
    return hits[0]


@pytest.mark.parametrize("fid", IDS)
def test_finding_has_verified_citation(fid):
    cites = D._citations(_file(fid))
    assert len(cites) >= 1, fid
    assert all(c["quote"] for c in cites), fid


@pytest.mark.parametrize("fid", IDS)
def test_citations_are_trailing_comment_block(fid):
    """The citation block is the file's last lines, comments only."""
    lines = _file(fid).read_text().rstrip("\n").split("\n")
    tail = [i for i, l in enumerate(lines) if "spec (requirement)" in l]
    assert tail, fid
    for l in lines[tail[0]:]:
        assert l.lstrip().startswith(("!", "//")), (fid, l)


# ---- Combined-construct consistency of the skeleton plus the spec overrides ------------------------------



from offload.engine.catalog import (load_grammar, load_skeleton, rule_valid,
                                slice_directives)

ROOT_11 = Path(__file__).resolve().parent.parent.parent
CATALOG = ROOT_11 / "catalog" / "omp"
GAPS = Path(__file__).resolve().parent.parent / "data" / "compound_clause_gaps.yaml"


def compound_gaps() -> dict[tuple[str, str], list[int]]:
    """(compound, clause) -> versions at which a leaf allows the clause and
    the compound does not (ompx_ extensions ignored)."""
    sk = load_skeleton(CATALOG / "skeleton.yaml")
    grammar = load_grammar(CATALOG / "clauses.yaml")
    gaps: dict[tuple[str, str], list[int]] = {}
    for version in VERSIONS:
        for key in slice_directives(sk):
            leaves = sk.directive(key).leaves
            if not leaves:
                continue
            on_compound = {c for c, r in grammar.allowed(sk, key).items()
                           if rule_valid(r, version)}
            on_leaves = {c for leaf in leaves
                         for c, r in grammar.allowed(sk, leaf).items()
                         if rule_valid(r, version)}
            for clause in sorted(on_leaves - on_compound):
                if not clause.startswith("ompx_"):
                    gaps.setdefault((key, clause), []).append(version)
    return gaps


def listed() -> dict[tuple[str, str], dict]:
    entries = yaml.safe_load(GAPS.read_text())["gaps"]
    out = {(e["directive"], e["clause"]): e for e in entries}
    assert len(out) == len(entries), "duplicate allowlist entry"
    return out


def test_every_allowlist_entry_has_a_reason():
    for (d, c), e in listed().items():
        assert e["reason"].strip(), (d, c)


def test_no_unlisted_compound_clause_gaps():
    new = sorted(set(compound_gaps()) - set(listed()))
    assert not new, f"compound directives missing a leaf's clause: {new}"


def test_no_stale_allowlist_entries():
    gaps = compound_gaps()
    stale = sorted(k for k in listed() if k not in gaps)
    assert not stale, f"no longer gaps, remove from the allowlist: {stale}"
    changed = sorted(k for k, e in listed().items()
                     if k in gaps and e["versions"] != gaps[k])
    assert not changed, f"gap versions changed: {changed}"


# ---- Tests of the restriction inventory (catalog/omp/rules_coverage.yaml) --------------------------------

import json
from collections import Counter


from offload.engine import combos, spec_text
from offload.engine.coverage import CLASSES, extract, load_coverage

ROWS = load_coverage()
RULE_IDS = {r.id for r in default_rules()}
VERSIONS_12 = ("5.2", "6.0")


@pytest.mark.needs_spec
def test_every_extracted_sentence_is_classified_once():
    want = [(i.version, i.section, i.text) for v in VERSIONS_12
            for i in extract(v)]
    have = [(r["version"], r["section"], r["text"]) for r in ROWS]
    assert have == want


@pytest.mark.needs_spec
@pytest.mark.parametrize("version", VERSIONS_12)
def test_sentences_are_verbatim_in_their_section(version):
    secs = {s.number: s for s in spec_text.sections(version).values()}
    for r in ROWS:
        if r["version"] != version:
            continue
        sec = secs[r["section"]]
        assert sec.first_page <= r["page"] <= sec.last_page, r["text"]
        assert re.sub(r"\s+", "", r["text"]) in re.sub(r"\s+", "", sec.text)


def test_classes_and_references():
    for r in ROWS:
        assert r["class"] in CLASSES, r
        if r["class"] in ("static", "covered"):
            rule = r["rule"]
            if rule != "grammar":
                v = r["version"].replace(".", "")
                assert f"OMP{v}-{rule}" in RULE_IDS, (r["text"], rule)
        else:
            assert "rule" not in r, r
        if r["class"] == "deferred":
            assert r["why"].strip(), r
        if r["language"] == "C/C++":
            assert r["class"] == "out_of_slice", r


def test_c_triage_of_c_sentences():
    """Every C/C++ sentence has its class for the C slice; a
    static or covered one names a rule that holds in C at that version."""
    from offload.engine.rules import default_rules
    langs = {r.id: r.lang for r in default_rules()}
    n = 0
    for r in ROWS:
        c = r.get("c")
        if r["language"] != "C/C++":
            assert c is None, r
            continue
        n += 1
        assert c["class"] in CLASSES, r
        if c["class"] in ("static", "covered"):
            if c["rule"] != "grammar":
                v = r["version"].replace(".", "")
                rid = f"OMP{v}-{c['rule']}"
                assert langs.get(rid) in ("c", "both"), (r["text"], rid)
        if c["class"] == "deferred":
            assert c["why"].strip(), r
    assert n > 150


def test_static_sentences_name_task16_rules_and_covered_ones_older():
    import yaml
    from offload.engine.rules import RULES_PATH
    stems = [e["id"] for e in yaml.safe_load(
        RULES_PATH.read_text())["rules"]]
    task16 = set(stems[stems.index("worksharing-nesting-001"):]) - {
        e for e in stems if e.endswith("-exec-001")}
    for r in ROWS:
        if r["class"] == "static":
            assert r["rule"] in task16, r
        elif r["class"] == "covered" and r["rule"] != "grammar":
            assert r["rule"] not in task16, r


def test_counts_are_plausible():
    c = Counter(r["class"] for r in ROWS)
    assert len(ROWS) > 800 and c["static"] > 150


# --- the combination matrix ---------------------------------------------------------

CELLS = combos.cells()
# 6.0 Appendix D (via §19.1) derives these compound names, which neither the
# skeleton nor AFAR's parser knows: the grammar is stricter than 6.0
EXTRA_60 = {("teams", "parallel"), ("parallel", "target"), ("parallel", "simd"),
            ("target", "teams", "parallel"), ("target", "parallel", "simd"),
            ("teams", "parallel", "target"), ("teams", "parallel", "do"),
            ("teams", "parallel", "simd"), ("teams", "parallel", "loop"),
            ("parallel", "target", "teams"), ("parallel", "target", "simd"),
            ("parallel", "target", "loop")}


def test_ours_agrees_with_the_spec_tables():
    off = {(c.version, c.form, c.order) for c in CELLS if c.spec != c.ours}
    assert off == {(60, "combined", o) for o in EXTRA_60}
    for c in CELLS:
        if (c.version, c.form, c.order) in off:
            assert c.spec and not c.ours and (
                "unknown" in c.why or "not allowed" in c.why)


def test_matrix_sizes():
    n = Counter((c.version, c.form) for c in CELLS)
    assert n[(52, "nested")] == 7 * 6 + 7 * 6 * 5
    assert n[(60, "combined")] == 8 * 7 + 8 * 7 * 6


def test_committed_flang_results_match_the_cells():
    data = json.loads((Path(__file__).parent.parent / "data"
                       / "combination_matrix.json").read_text())["cells"]
    have = {(r["version"], r["form"], tuple(r["order"])): r for r in data}
    assert set(have) == {(c.version, c.form, c.order) for c in CELLS}
    for c in CELLS:
        r = have[(c.version, c.form, c.order)]
        assert (r["spec"], r["ours"]) == (c.spec, c.ours), c
    # flang never rejects a program we accept
    assert [k for k, r in have.items() if r["ours"] and r["flang"] != "ok"] \
        == []


def test_sources_are_well_formed():
    from offload.engine.rules import parse_program
    for seq in combos.orders(60):
        tree = parse_program(combos.nested_source(seq), 60)
        assert [d.name for d in tree.directives] == list(seq)


# ---- kernel idiom miner (offload/engine/idioms.py): statement shapes inside device -----------------------

from offload.engine import idioms as I


def tags_of(stmt, **kw):
    return I.classify_fortran(stmt, **kw)


# --- Fortran statements -----------------------------------------------------------------

def test_the_students_statement_is_an_array_constructor_into_an_element_component():
    t = tags_of("gps(local_idx)%loc = [i, j, k]")
    assert "ac.elem-comp" in t
    assert "tgt.elem-comp" in t


def test_array_constructor_target_kinds():
    assert "ac.var" in tags_of("v = [1, 2, 3]")
    assert "ac.var" in tags_of("v = (/ 1, 2, 3 /)")
    assert "ac.section" in tags_of("v(1:3) = [1, 2, 3]")
    assert "ac.comp" in tags_of("p%loc = [i, j, k]")
    assert "ac.comp-section" in tags_of("p%loc(1:2) = [i, j]")
    assert "ac.elem-comp-section" not in tags_of("p%loc(1:2) = [i, j]")
    assert "ac.elem-comp" in tags_of("q(n)%loc = [i, j, k]")
    assert "ac.nested-comp" in tags_of("q(n)%a%b = [i, j]")


def test_array_constructor_with_arithmetic_or_inside_a_call():
    assert "ac.expr" in tags_of("v = [1, 2, 3] + k")
    assert "ac.arg" in tags_of("s = sum([a, b, c])")
    assert "ac.var" not in tags_of("s = sum([a, b, c])")


def test_pointer_component_is_known_from_the_declarations():
    t = tags_of("ib%sf(i, j, k) = 3", pointer_comps={"sf"})
    assert "tgt.ptr-comp-elem" in t
    t = tags_of("ib%sf(i, j, k) = 3")
    assert "tgt.ptr-comp-elem" not in t
    assert "tgt.comp-elem" in t


def test_target_kinds():
    assert "tgt.var" in tags_of("a = 1")
    assert "tgt.elem" in tags_of("a(i, j) = 1")
    assert "tgt.section" in tags_of("a(:, j) = 1")
    assert "tgt.comp" in tags_of("a%b = 1")
    assert "tgt.elem-comp" in tags_of("a(i)%b = 1")
    assert "tgt.comp-elem" in tags_of("a%b(2) = 1")
    assert "tgt.elem-comp-elem" in tags_of("a(i)%b(2) = 1")
    assert "tgt.whole-array" in tags_of("a = b + 1", arrays={"a"})


def test_intrinsics_are_grouped():
    t = tags_of("x = merge(a, b, c > 0) + max(p, q) + mod(i, 2) + sqrt(z)")
    assert {"intr.merge", "intr.minmax", "intr.mod", "intr.math"} <= t
    assert "intr.reduce" in tags_of("s = sum(a(:)) + maxval(b)")
    assert "intr.reduce" not in tags_of("s = a(1) + b(2)")


def test_control_and_calls():
    assert "ctl.exit" in tags_of("exit")
    assert "ctl.exit-named" in tags_of("exit search")
    assert "ctl.cycle" in tags_of("cycle")
    assert "ctl.if-single" in tags_of("if (a > 1) b = 2")
    assert "tgt.var" in tags_of("if (a > 1) b = 2")
    assert "call.user" in tags_of("call s_decode(a, b)")
    assert "call.device-routine" in tags_of("call s_decode(a, b)",
                                           routines={"s_decode"})


# --- regions ------------------------------------------------------------------------------

MFC = """
subroutine s_find()
  integer :: i, j, k, count, local_idx
  integer :: tmp(3)
  logical :: is_gp
  count = 0
  $:GPU_PARALLEL_LOOP(private='[i, j, k, is_gp, local_idx, tmp]', &
      & copyin='[count]', collapse=3)
  do i = 0, m
    do j = 0, n
      do k = 0, p
        if (ib%sf(i, j, k) /= 0) then
          is_gp = .false.
          search: do ii = i - 1, i + 1
            do jj = j - 1, j + 1
              if (ib%sf(ii, jj, k) == 0) then
                is_gp = .true.
                exit search
              end if
            end do
          end do search
          if (is_gp) then
            $:GPU_ATOMIC(atomic='capture')
            count = count + 1
            local_idx = count
            $:END_GPU_ATOMIC_CAPTURE()
            gps(local_idx)%loc = [i, j, k]
          end if
        end if
      end do
    end do
  end do
  $:END_GPU_PARALLEL_LOOP()
  host_only = [1, 2, 3]
end subroutine s_find
"""


def test_a_fypp_loop_region_is_found_and_the_host_statement_outside_is_not_counted():
    rs = I.fortran_regions(MFC, "m_ibm.fpp")
    assert len(rs) == 1
    r = rs[0]
    assert r.kind == "loop" and r.collapse == 3
    allt = set().union(*(t for _, t in r.stmts))
    assert "ac.elem-comp" in allt
    assert "ac.var" not in allt                 # host_only is outside
    assert "atomic.capture.update-fetch.var" in allt   # count = count + 1; v = count
    assert "ctl.exit-named" in allt
    assert "loop.search-nested" in allt
    assert "priv.array" in r.flags              # tmp is a private array


def test_omp_target_block_region_and_atomic_forms():
    src = """
subroutine t(a, n)
  integer :: a(n), c, v, i
  !$omp target teams distribute parallel do private(v)
  do i = 1, n
    !$omp atomic update
    c = c + 1
    !$omp atomic capture
    v = c
    c = c + 2
    !$omp end atomic
    !$omp atomic capture
    c = c + 1
    v = c
    !$omp end atomic
    !$omp atomic read
    v = c
    !$omp atomic write
    c = v
    !$omp atomic
    a(i) = a(i) + 1
    !$omp atomic update
    p%cnt = max(p%cnt, v)
  end do
end subroutine
"""
    rs = I.fortran_regions(src, "x.f90")
    assert len(rs) == 1
    allt = set().union(*(t for _, t in rs[0].stmts))
    assert "atomic.update.var" in allt
    assert "atomic.capture.fetch-update.var" in allt
    assert "atomic.capture.update-fetch.var" in allt
    assert "atomic.read.var" in allt
    assert "atomic.write.var" in allt
    assert "atomic.update.elem" in allt
    assert "atomic.update.comp" in allt


def test_device_routine_is_a_region_of_its_own():
    src = """
subroutine s_dev(a, b)
  !$omp declare target
  real :: a(3), b
  a = [b, b, b]
end subroutine s_dev
subroutine s_host(a)
  real :: a(3)
  a = [1., 2., 3.]
end subroutine
"""
    rs = I.fortran_regions(src, "x.f90")
    assert [r.kind for r in rs] == ["routine"]
    assert "ac.var" in set().union(*(t for _, t in rs[0].stmts))
    assert I.device_routines(src) == {"s_dev"}


def test_target_data_and_enter_data_are_not_kernels():
    src = """
subroutine t(a, n)
  !$omp target enter data map(to: a)
  a = [1, 2]
  !$omp target update from(a)
end subroutine
"""
    assert I.fortran_regions(src, "x.f90") == []


def test_call_gpu_parallel_block():
    src = """
subroutine t()
  #:call GPU_PARALLEL(copy='[a]')
    a = [1, 2]
    b(1)%c = [3, 4]
  #:endcall GPU_PARALLEL
end subroutine
"""
    rs = I.fortran_regions(src, "x.fpp")
    assert len(rs) == 1 and rs[0].kind == "block"
    allt = set().union(*(t for _, t in rs[0].stmts))
    assert {"ac.var", "ac.elem-comp"} <= allt


# --- C ---------------------------------------------------------------------------------------

C_SRC = r"""
void f(struct rec *g, int *cnt, int n) {
  #pragma omp target teams distribute parallel for map(tofrom: cnt[0:1])
  for (int i = 0; i < n; i++) {
    int tmp[3];
    int v;
    if (i % 2 == 0) {
      #pragma omp atomic capture
      { v = cnt[0]; cnt[0] += 1; }
      g[v].loc[0] = i;
      g[v].w = (struct vec){i, i, i};
      for (int k = 0; k < 5; k++) { if (k == i) break; }
    }
    #pragma omp atomic update
    cnt[1]++;
    #pragma omp atomic capture
    v = cnt[2]++;
  }
}
"""


def test_c_target_loop_region():
    rs = I.c_regions(C_SRC, "x.c")
    assert len(rs) == 1
    allt = set().union(*(t for _, t in rs[0].stmts))
    assert "atomic.capture.fetch-update.elem" in allt
    assert "atomic.update.elem" in allt
    assert "atomic.capture.stmt.elem" in allt
    assert "tgt.elem-comp-elem" in allt
    assert "c.compound-literal" in allt
    assert "ctl.break" in allt
    assert "local.fixed-array" in allt
    assert "loop.search" in allt


def test_c_host_function_is_not_counted():
    src = "void h(int *a){ a[0] = 1; }\n"
    assert I.c_regions(src, "x.c") == []


# --- the counts --------------------------------------------------------------------------------

def test_idiom_classes_count_a_statement_once():
    rs = I.fortran_regions(MFC, "a.fpp")
    tab = I.tally(rs)
    g = [k for k in I.GROUPS if k.startswith("G02")][0]
    assert tab[g]["stmts"] == 1 and tab[g]["kernels"] == 1
    g12 = [k for k in I.GROUPS if k.startswith("G12")][0]
    assert tab[g12]["kernels"] == 1 and tab[g12]["stmts"] == 0   # tmp is private


def test_tally_counts_statements_files_and_kernels():
    rs = I.fortran_regions(MFC, "a.fpp") + I.fortran_regions(MFC, "b.fpp")
    tab = I.tally(rs)
    row = tab["ac.elem-comp"]
    assert row["stmts"] == 2 and row["files"] == 2 and row["kernels"] == 2
