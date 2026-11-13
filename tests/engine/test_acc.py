"""Tests of the OpenACC 3.4 slice: catalog, grammar, rules,
generator, mutation, harness flags and the support table.

The base-language check runs gfortran (a checker only) as
``gfortran -std=<level> -fsyntax-only`` without -fopenacc, against
``offload.engine.acc_gen.OPENACC_STUB``; marked ``gfortran``.
"""
import where
import json
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import yaml

from offload.engine import acc_gen, gen, spec_text
from offload.engine.catalog import (catalog_dir, default_grammar,
                                default_skeleton, model_of, semantic_atoms,
                                slice_atoms)
from offload.engine.grammar import GrammarError, parse_directive
from offload.engine.harness import (Outcome, program_from_file, run_program,
                                run_script)
from offload.engine.mutate import (ACC_RENAMES, audit_programs, illegal,
                               mutation_of, neutralise)
from offload.engine.rules import (Assoc, ProgramTree, acc_rules, association,
                              default_rules, parse_program, rules_for,
                              violations)
from offload.engine.run_matrix import for_version
from offload.engine.toolchains import TOOLCHAINS, Toolchain

V = 34
ROOT = Path(__file__).resolve().parent.parent.parent
DATA = Path(__file__).parent.parent / "data"
ACC = catalog_dir("acc")


def programs():
    return gen.all_programs(V)


def legal():
    return [p for p in programs() if p.legal]


def _section(citation):
    m = re.match(r"OpenACC 3\.4 §([\d.]+), p\.(\d+)$", citation)
    assert m, citation
    secs = [s for s in spec_text.sections("acc3.4").values()
            if s.number == m.group(1)]
    assert len(secs) == 1, citation
    return secs[0], int(m.group(2))


def _verbatim(text, sec):
    return re.sub(r"\s+", "", text) in re.sub(r"\s+", "", sec.text)


# --- catalog -----------------------------------------------------------------------

def test_model_of_version():
    assert model_of(34) == "acc"
    assert model_of(52) == model_of(60) == "omp"


def test_skeleton_is_the_tablegen_dump():
    from offload.engine.skeleton import build_skeleton
    built = build_skeleton(ROOT / "data" / "index" / "seed" / "acc.json")
    on_disk = yaml.safe_load((ACC / "skeleton.yaml").read_text())
    assert built == on_disk


def test_slice_atoms():
    atoms = slice_atoms(V)
    # Acc.clause.self.condition is out of the device-offload scope
    assert len(atoms) == len(set(atoms)) == 89
    assert len(slice_atoms(V, in_scope=False)) == 90
    assert all(a.startswith("acc.") for a in atoms)
    for a in ("acc.directive.parallel_loop", "acc.directive.enter_data",
              "acc.clause.reduction.neqv", "acc.clause.default.present",
              "acc.clause.gang.static", "acc.clause.wait.devnum",
              "acc.clause.update", "acc.clause.firstprivate.implicit_scalar"):
        assert a in atoms, a
    # data-clause modifiers parse but are out of the slice;
    # shortloop is not an OpenACC 3.4 clause; unknown is TableGen's
    assert not any(a.split(".")[-1] in ("always", "readonly", "zero",
                                        "capture", "alwaysin")
                   for a in atoms if a.count(".") == 3)
    assert "acc.clause.shortloop" not in atoms
    assert "acc.directive.unknown" not in atoms
    # the OpenMP slice is unchanged by the model flag
    assert all(a.startswith("omp.") for a in slice_atoms(52) + slice_atoms(60))


@pytest.mark.needs_spec
def test_clause_citations_are_sections_of_the_spec():
    data = yaml.safe_load((ACC / "clauses.yaml").read_text())
    for name, e in data["clauses"].items():
        assert e["status"] == "provisional", name
        for f in e["forms"]:
            assert f["since"] == 34, name
            sec, page = _section(f["citation"])
            assert sec.first_page <= page <= sec.last_page, (name, f)


def test_spec_overrides():
    sk, g = default_skeleton("acc"), default_grammar("acc")
    assert "update" in sk.clauses
    atomic = g.allowed(sk, "atomic")
    assert {"read", "write", "update", "capture", "if"} <= set(atomic)
    for d in ("loop", "parallel loop", "kernels loop", "serial loop"):
        assert "shortloop" not in g.allowed(sk, d)


@pytest.mark.needs_spec
def test_semantic_atoms_cite_the_spec():
    sem = semantic_atoms("acc")
    assert set(sem) == {"acc.clause.firstprivate.implicit_scalar",
                        "acc.clause.copy.implicit_kernels_scalar"}
    for e in sem.values():
        sec, page = _section(e.citations[34].split(" (")[0])
        assert sec.first_page <= page <= sec.last_page


@pytest.mark.needs_spec
def test_spec_text_reads_openacc():
    secs = {s.number: s for s in spec_text.sections("acc3.4").values()}
    assert secs["2.5.1"].title == "Parallel Construct"
    assert secs["2.5.1"].first_page == 33
    items = spec_text.restrictions("acc3.4", "Data Construct")
    assert items[0].citation == "OpenACC 3.4 §2.6.5, p.44"
    assert spec_text.cite_name("acc3.4") == "OpenACC 3.4"
    assert spec_text.cite_name("5.2") == "OpenMP 5.2"


# --- grammar -----------------------------------------------------------------------

def test_parse_acc_directives():
    d = parse_directive("!$acc parallel loop gang copyin(a) reduction(+: s)",
                        "fortran", V)
    assert d.name == "parallel loop"
    assert {"acc.directive.parallel_loop", "acc.clause.gang",
            "acc.clause.copyin", "acc.clause.reduction",
            "acc.clause.reduction.plus"} <= d.atoms
    d = parse_directive("!$acc atomic capture", "fortran", V)
    assert d.atoms == {"acc.directive.atomic", "acc.clause.capture"}
    d = parse_directive("!$acc wait(devnum: 0: queues: 1) async(2)",
                        "fortran", V)
    assert d.name == "wait" and "acc.clause.async.async_argument" in d.atoms
    d = parse_directive("!$acc loop gang(static: *) worker(num: 4) "
                        "vector(length: 32)", "fortran", V)
    assert {"acc.clause.gang.static", "acc.clause.worker.num",
            "acc.clause.vector.length"} <= d.atoms


def test_alias_spellings_name_their_clause():
    d = parse_directive("!$acc data pcopy(a) present_or_copyin(b) "
                        "pcreate(c) dtype(*) wait(1)", "fortran", V)
    assert {"acc.clause.copy", "acc.clause.copyin", "acc.clause.create",
            "acc.clause.device_type"} <= d.atoms
    assert not any("pcopy" in a or "dtype" in a for a in d.atoms)


def test_self_forms_per_directive():
    d = parse_directive("!$acc update self(b)", "fortran", V)
    assert "acc.clause.self" in d.atoms
    d = parse_directive("!$acc serial self(c)", "fortran", V)
    assert "acc.clause.self.condition" in d.atoms
    assert "acc.clause.self.condition" not in parse_directive(
        "!$acc serial self", "fortran", V).atoms


def test_routine_gang_takes_only_dim():
    parse_directive("!$acc routine gang(dim: 1)", "fortran", V)
    with pytest.raises(GrammarError):
        parse_directive("!$acc routine gang(static: 2)", "fortran", V)


@pytest.mark.parametrize("text,code", [
    ("!$acc kernels loop shortloop", "clause_not_allowed"),
    ("!$acc parallel default(shared)", "bad_argument"),
    ("!$acc enter data", "missing_required"),
    ("!$acc update if_present", "missing_required"),
    ("!$acc loop seq independent", "clause_not_allowed"),
    ("c$acc parallel", "fixed_form"),
    ("!$omp target", "unknown_directive"),
])
def test_grammar_errors(text, code):
    with pytest.raises(GrammarError) as e:
        parse_directive(text, "fortran", V)
    assert e.value.code == code


def test_sentinels_do_not_mix():
    src = "\n".join(["program p", "integer :: i", "!$omp parallel",
                     "!$acc parallel", "i = 1", "!$acc end parallel",
                     "!$omp end parallel", "end program p"])
    acc_tree = parse_program(src, V)
    omp_tree = parse_program(src, 52)
    assert [d.name for d in acc_tree.directives] == ["parallel"]
    assert next(iter(acc_tree.directives[0].atoms)).startswith("acc.")
    assert next(iter(omp_tree.directives[0].atoms)).startswith("omp.")


def test_associations():
    assert association("parallel loop", "acc") == "loop"
    assert association("data", "acc") == "block"
    assert association("atomic", "acc") == "statement"
    assert association("enter data", "acc") == "standalone"


# --- rules -------------------------------------------------------------------------

RULES = acc_rules()
STATIC = [r for r in RULES if r.check == "static"]


@pytest.mark.needs_spec
def test_rules_cite_the_spec_verbatim():
    data = yaml.safe_load((ACC / "rules.yaml").read_text(encoding="utf-8"))
    assert all(e["status"] == "provisional" for e in data["rules"])
    for r in RULES:
        assert re.fullmatch(r"ACC34-[a-z0-9]+-[a-z]+-\d{3}", r.id), r.id
        assert (r.predicate is not None) == (r.check == "static"), r.id
        sec, page = _section(r.citation)
        assert sec.first_page <= page <= sec.last_page, r.id
        assert _verbatim(r.text, sec), (r.id, r.text)
        for c in r.also:
            sec, page = _section(c)
            assert sec.first_page <= page <= sec.last_page, (r.id, c)


def test_rule_counts_and_model_split():
    assert len(STATIC) == 36 and len(RULES) == 39
    assert rules_for(V) == RULES and rules_for(52) == default_rules()
    assert all(r.predicate.startswith("acc_") for r in STATIC)


def P(*lines):
    return "\n".join(["program p", "  use openacc, only: acc_on_device",
                      "  implicit none",
                      "  integer, parameter :: n = 8",
                      "  integer :: a(n), b(n), t(2), x, s, i, j",
                      *lines, "end program p"])


def LOOP2(directive, inter=()):
    return [directive, "do j = 1, n", *inter, "do i = 1, n", "b(i) = j",
            "end do", "end do"]


MOD = ["end program p", "module m", "  implicit none", "  integer :: x, y(4)"]
# stem -> (legal source, illegal source)
ACC_CASES = {
    "compute-clause-001": (
        P("!$acc parallel device_type(*) num_gangs(4)", "x = 1",
          "!$acc end parallel"),
        P("!$acc parallel device_type(*) private(x)", "x = 1",
          "!$acc end parallel")),
    "data-clause-001": (
        P("!$acc data copy(a) device_type(*) async(1)", "x = 1",
          "!$acc end data"),
        P("!$acc data copy(a) device_type(*) if(.true.)", "x = 1",
          "!$acc end data")),
    "loop-clause-001": (
        P("!$acc parallel", "!$acc loop device_type(*) vector", "do i = 1, n",
          "b(i) = i", "end do", "!$acc end parallel"),
        P("!$acc parallel", "!$acc loop device_type(*) private(x)",
          "do i = 1, n", "b(i) = i", "end do", "!$acc end parallel")),
    "update-clause-001": (
        P("!$acc update self(b) device_type(*) async(1)"),
        P("!$acc update self(b) device_type(*) if_present")),
    "routine-clause-001": (
        P("contains", "subroutine f()", "!$acc routine seq device_type(*) "
          "bind(g)", "end subroutine f"),
        P("contains", "subroutine f()", "!$acc routine seq device_type(*) "
          "nohost", "end subroutine f")),
    "compute-clause-002": (
        P("!$acc parallel num_gangs(4) reduction(+: s)", "s = s + 1",
          "!$acc end parallel"),
        P("!$acc parallel num_gangs(2, 2) reduction(+: s)", "s = s + 1",
          "!$acc end parallel")),
    "numgangs-clause-001": (
        P("!$acc kernels num_gangs(2)", "x = 1", "!$acc end kernels"),
        P("!$acc kernels num_gangs(2, 2)", "x = 1", "!$acc end kernels")),
    "numgangs-clause-002": (
        P("!$acc parallel num_gangs(2, 2, 2)", "x = 1", "!$acc end parallel"),
        P("!$acc parallel num_gangs(2, 2, 2, 2)", "x = 1",
          "!$acc end parallel")),
    "hostonly-placement-001": (
        P("!$acc init", "!$acc parallel", "x = 1", "!$acc end parallel"),
        P("!$acc parallel", "!$acc set device_num(0)", "x = 1",
          "!$acc end parallel")),
    "loop-clause-002": (
        P("!$acc parallel loop seq device_type(*) collapse(1)",
          "do i = 1, n", "b(i) = i", "end do"),
        P("!$acc parallel loop seq vector", "do i = 1, n", "b(i) = i",
          "end do")),
    "loop-nesting-001": (
        P(*LOOP2("!$acc parallel loop gang", ["!$acc loop vector"])),
        P(*LOOP2("!$acc parallel loop vector", ["!$acc loop worker"]))),
    "loop-clause-003": (
        P("!$acc parallel loop gang", "do i = 1, n", "b(i) = i", "end do"),
        P("!$acc parallel loop gang gang(dim: 1)", "do i = 1, n", "b(i) = i",
          "end do")),
    "gang-clause-001": (
        P("!$acc kernels loop gang(num: 4)", "do i = 1, n", "b(i) = i",
          "end do"),
        P("!$acc parallel loop gang(num: 4)", "do i = 1, n", "b(i) = i",
          "end do")),
    "gang-clause-002": (
        P("!$acc parallel loop gang(dim: 1)", "do i = 1, n", "b(i) = i",
          "end do"),
        P("!$acc kernels", "!$acc loop gang(dim: 1)", "do i = 1, n",
          "b(i) = i", "end do", "!$acc end kernels")),
    "gang-clause-003": (
        P("!$acc parallel loop gang(dim: 3)", "do i = 1, n", "b(i) = i",
          "end do"),
        P("!$acc parallel loop gang(dim: 4)", "do i = 1, n", "b(i) = i",
          "end do")),
    "collapse-clause-001": (
        P(*LOOP2("!$acc parallel loop collapse(1)")),
        P(*LOOP2("!$acc parallel loop collapse(0)"))),
    "collapse-loop-001": (
        P(*LOOP2("!$acc parallel loop collapse(2)")),
        P("!$acc parallel loop collapse(2)", "do i = 1, n", "b(i) = i",
          "end do")),
    "collapse-loop-002": (
        P(*LOOP2("!$acc parallel loop collapse(force: 2)", ["x = j"])),
        P(*LOOP2("!$acc parallel loop collapse(2)", ["x = j"]))),
    "tile-loop-001": (
        P(*LOOP2("!$acc parallel loop tile(4, 4)")),
        P(*LOOP2("!$acc parallel loop tile(4, 4, 4)"))),
    "tile-clause-001": (
        P(*LOOP2("!$acc parallel loop tile(*, 4)")),
        P(*LOOP2("!$acc parallel loop tile(0, 4)"))),
    "hostdata-clause-001": (
        P("!$acc host_data use_device(a)", "x = 1", "!$acc end host_data"),
        P("!$acc host_data use_device(a(1))", "x = 1",
          "!$acc end host_data")),
    "declare-clause-001": (
        P(*MOD, "  !$acc declare create(x)", "end module m"),
        P(*MOD, "  !$acc declare copy(x)", "end module m")),
    "declare-clause-002": (
        P("!$acc declare create(x)", "!$acc declare copyin(t)"),
        P("!$acc declare create(x)", "!$acc declare copyin(x)")),
    "declare-placement-001": (
        P(*MOD, "  !$acc declare link(y)", "end module m"),
        P("!$acc declare link(t)")),
    "declare-placement-002": (
        P("x = 1", "contains", "subroutine s()", "integer :: z",
          "!$acc declare create(z)", "end subroutine s"),
        P("x = 1", "contains", "subroutine s()", "!$acc declare create(x)",
          "end subroutine s")),
    "attach-clause-001": (
        ["program p", "integer, allocatable :: v(:)",
         "!$acc enter data attach(v)", "end program p"],
        P("!$acc enter data attach(t)")),
    "deviceptr-clause-001": (
        ["subroutine s(v)", "integer :: v(8)", "!$acc parallel deviceptr(v)",
         "v(1) = 1", "!$acc end parallel", "end subroutine s"],
        ["subroutine s()", "integer, allocatable :: v(:)",
         "!$acc parallel deviceptr(v)", "v(1) = 1", "!$acc end parallel",
         "end subroutine s"]),
    "routine-clause-002": (
        P("contains", "subroutine f()", "!$acc routine vector",
          "end subroutine f"),
        P("contains", "subroutine f()", "!$acc routine gang seq",
          "end subroutine f")),
    "routine-placement-001": (
        P("contains", "subroutine f()", "!$acc routine seq",
          "end subroutine f"),
        P("!$acc routine seq")),
    "atomic-clause-001": (
        P("!$acc parallel", "!$acc atomic read", "x = s",
          "!$acc end parallel"),
        P("!$acc parallel", "!$acc atomic read write", "x = s",
          "!$acc end parallel")),
    "cache-placement-001": (
        P("!$acc parallel loop", "do i = 1, n", "!$acc cache(a(i:i))",
          "b(i) = a(i)", "end do"),
        P("!$acc parallel", "!$acc cache(a(1:2))", "x = a(1)",
          "!$acc end parallel")),
    "cache-clause-001": (
        P("!$acc parallel loop", "do i = 1, n", "!$acc cache(a(i))",
          "b(i) = a(i)", "end do"),
        P("!$acc parallel loop", "do i = 1, n", "!$acc cache(a)",
          "b(i) = a(i)", "end do")),
    "default-dsa-001": (
        P("!$acc parallel loop default(none) copyin(a) copyout(b)",
          "do i = 1, n", "b(i) = a(i)", "end do"),
        P("!$acc parallel loop default(none) copyin(a)", "do i = 1, n",
          "b(i) = a(i)", "end do")),
    "reduction-dsa-001": (
        P("!$acc parallel copy(s)", "!$acc loop reduction(+: s)",
          "do i = 1, n", "s = s + i", "end do", "!$acc end parallel"),
        P("!$acc parallel", "!$acc loop reduction(+: s)", "do i = 1, n",
          "s = s + i", "end do", "!$acc end parallel")),
    "reduction-clause-001": (
        P("!$acc parallel reduction(+: s)", "!$acc loop reduction(+: s)",
          "do i = 1, n", "s = s + i", "end do", "!$acc end parallel"),
        P("!$acc parallel reduction(+: s)", "!$acc loop reduction(*: s)",
          "do i = 1, n", "s = s * i", "end do", "!$acc end parallel")),
    "reduction-clause-002": (
        ["program p", "type :: q", "integer :: c", "end type q",
         "type(q) :: r", "integer :: s, i", "!$acc parallel loop "
         "reduction(+: s)", "do i = 1, 8", "s = s + i", "end do",
         "end program p"],
        ["program p", "type :: q", "integer :: c", "end type q",
         "type(q) :: r", "integer :: i", "!$acc parallel loop "
         "reduction(+: r%c)", "do i = 1, 8", "r%c = r%c + i", "end do",
         "end program p"]),
}


def test_every_static_rule_has_cases():
    assert {r.id.split("-", 1)[1] for r in STATIC} == set(ACC_CASES)


@pytest.mark.parametrize("rule", STATIC, ids=lambda r: r.id)
def test_rule_legal_and_illegal(rule):
    good, bad = ACC_CASES[rule.id.split("-", 1)[1]]
    good = good if isinstance(good, str) else "\n".join(good)
    bad = bad if isinstance(bad, str) else "\n".join(bad)
    assert violations(parse_program(good, V), V) == []
    assert violations(parse_program(bad, V), V) == [rule.id]


def test_omp_and_acc_predicates_do_not_collide():
    from offload.engine.rules import PREDICATES
    names = {r.predicate for r in default_rules() if r.predicate}
    assert not names & {r.predicate for r in STATIC}
    assert all(PREDICATES[r.predicate] for r in default_rules()
               if r.predicate)


@pytest.mark.needs_spec
def test_no_oracle_bases_quote_the_spec_verbatim():
    data = yaml.safe_load((ACC / "no_oracle.yaml").read_text())
    for bid, e in data["bases"].items():
        assert e["status"] == "provisional"
        for c in e[34]:
            sec, page = _section(c["cite"])
            assert sec.first_page <= page <= sec.last_page, bid
            assert _verbatim(c["quote"], sec), bid


# --- generator ---------------------------------------------------------------------

def test_every_slice_atom_has_a_program():
    got = {p.primary_atom for p in legal()}
    assert got == set(slice_atoms(V))
    assert not gen.UNGENERATABLE[V]


def test_program_ids_and_model():
    for p in programs():
        assert p.model == "acc" and p.id.startswith("acc34-"), p.id
        assert "OpenACC 3.4" in p.source.splitlines()[0]
        assert "!$omp" not in p.source.lower()


def test_legal_programs_have_no_violations():
    for p in legal():
        assert violations(parse_program(p.source, V), V) == [], p.id


def test_illegal_violates_exactly_one():
    ill = [p for p in programs() if not p.legal]
    assert {p.violates for p in ill} == {
        r for r in gen.VIOLATIONS if r.startswith("ACC34-")}
    assert len(ill) == len(acc_gen.ILLEGAL)
    for p in ill:
        assert p.id == "acc34-illegal-" + p.violates.split("-", 1)[1]
        assert violations(parse_program(p.source, V), V) == [p.violates]


def test_static_rules_have_a_variant_or_a_reason():
    static = {r.id for r in STATIC}
    variants = {r for r in gen.VIOLATIONS if r.startswith("ACC34-")}
    reasons = {r for r in gen.NOT_GENERATABLE if r.startswith("ACC34-")}
    assert variants | reasons == static and not variants & reasons


def test_vector_length_argument_only_where_the_text_defines_it():
    """acc34-clause-vector-length and its C twin use vector(length:) under a
    kernels construct without vector_length (OpenACC 3.4 §2.9.4, p.68: "An
    argument is allowed only when the vector_length does not appear on the
    kernels construct"). Under a parallel construct the text gives the
    argument no role ("vectors of the length specified or chosen for the
    parallel region"), unlike gang(num:) and worker(num:), which it names
    as not allowed there; the program was a parallel loop before."""
    p = next(q for q in legal() if q.id == "acc34-clause-vector-length")
    lines = [ln.strip().lower() for ln in p.source.splitlines()
             if ln.strip().startswith("!$acc")]
    use = [i for i, ln in enumerate(lines) if "vector(length:" in ln]
    assert len(use) == 1
    assert lines[use[0]].startswith("!$acc loop")
    kernels = [ln for ln in lines[:use[0]] if ln.startswith("!$acc kernels")]
    assert len(kernels) == 1 and "vector_length" not in kernels[0]
    assert not any(ln.startswith("!$acc parallel") for ln in lines)


def test_programs_self_report():
    rx = re.compile(r"print '\(a,i0,a,a\)', 'RESULT ran_on_host=', "
                    r"host_flag, ' check='")
    for p in programs():
        assert len(rx.findall(p.source)) == 1, p.id
        assert "acc_on_device(acc_device_host)" in p.source, p.id


def test_evidence_markers():
    from collections import Counter
    c = Counter(p.evidence for p in legal())
    assert set(c) <= set(gen.EVIDENCE)
    for p in legal():
        if p.evidence == "copy_mode_only":
            assert "shared_mem = zc(1) == 1" in p.source, p.id
        if p.evidence == "probe":
            assert p.expect == "error_termination", p.id
            assert re.search(r"!\$acc parallel loop (present|default"
                             r"\(present\))", p.source), p.id
        if p.evidence == "legality":
            assert gen.legality_of(p.source) == "ACC34-default-dsa-001"


def test_openacc_stub_declares_every_name_used():
    for p in programs():
        only = re.search(r"use openacc, only: (.*)", p.source).group(1)
        names = {x.strip() for x in only.split(",")}
        assert names <= acc_gen.OPENACC_STUB_NAMES, (p.id, names)
    for name in acc_gen.OPENACC_STUB_NAMES:
        assert re.search(rf"\b{name}\b", acc_gen.OPENACC_STUB), name


GFORTRAN = shutil.which("gfortran") or "/usr/tce/bin/gfortran"
gfortran_only = pytest.mark.skipif(not Path(GFORTRAN).is_file(),
                                   reason="gfortran is not installed")


@pytest.fixture(scope="module")
def openacc_stub(tmp_path_factory):
    d = tmp_path_factory.mktemp("openacc_stub")
    src = d / "openacc_stub.f90"
    src.write_text(acc_gen.OPENACC_STUB)
    subprocess.run([GFORTRAN, "-std=f2008", "-fsyntax-only", "-J", str(d),
                    str(src)], check=True, capture_output=True, text=True,
                   cwd=d)
    return str(d)


def _syntax(p, stub):
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "p.f90"
        f.write_text(p.source)
        res = subprocess.run([GFORTRAN, f"-std={p.std}", "-fsyntax-only",
                              f"-I{stub}", "-J", d, str(f)],
                             capture_output=True, text=True, cwd=d)
    return p.id, res.returncode, res.stderr


@pytest.mark.gfortran
@gfortran_only
def test_programs_legal_in_base_language(openacc_stub):
    with ThreadPoolExecutor(max_workers=16) as pool:
        res = list(pool.map(lambda p: _syntax(p, openacc_stub), programs()))
    assert {pid: err for pid, rc, err in res if rc} == {}


def test_reduction_programs_change_the_value():
    for feat, (_, typ, init, _, want) in acc_gen.REDUCTIONS.items():
        assert init != want, feat


# --- mutation audit ----------------------------------------------------------------

def test_every_audited_program_has_a_conforming_mutant():
    progs = audit_programs(V)
    assert progs
    for p in progs:
        m = neutralise(p)
        assert m is not None and m.source != p.source, p.id
        assert illegal(m, V) == [], (p.id, illegal(m, V))
        assert mutation_of(m).startswith(f"removed {p.primary_atom}")


def test_data_clauses_are_renamed_to_create():
    (p,) = [q for q in audit_programs(V)
            if q.primary_atom == "acc.clause.copyout"]
    m = neutralise(p)
    assert "create(b)" in m.source and "copyout(b)" not in m.source
    assert "copy(host_flag)" in m.source  # infrastructure is kept
    assert set(ACC_RENAMES) == {"acc.clause.copy", "acc.clause.copyin",
                                "acc.clause.copyout", "acc.clause.link"}


def test_audit_summary_matches_generator():
    """tests/data/acc_audit_summary.json (tools/campaigns/oracle_audit.py --model
    acc, a full run) covers every legal program as generated now."""
    from offload.engine.mutate import body_sha
    data = json.loads((DATA / "acc_audit_summary.json").read_text())
    assert data["run"]["full"] and data["run"]["model"] == "acc"
    summ = data["versions"]["34"]
    assert set(summ) == {p.primary_atom for p in legal()}
    for p in legal():
        e = summ[p.primary_atom]
        assert e["program"] == p.id
        assert e["body_sha"] == body_sha(p.source), p.id
        assert e["evidence"] == p.evidence, p.id


def test_audited_atoms_are_valid_or_unaudited():
    data = json.loads((DATA / "acc_audit_summary.json").read_text())
    for atom, e in data["versions"]["34"].items():
        if e["observable"] and e["evidence"] in gen.AUDITED:
            assert e["disposition"] in (
                "valid", "unaudited_no_passing_original"), (atom, e)


# --- harness, matrix, report -------------------------------------------------------

def test_toolchain_flags_by_model():
    cce = TOOLCHAINS["cce19"]
    assert cce.flags() == "-fopenmp"
    acc_tc = for_version(cce, 34)
    assert acc_tc.model == "acc" and acc_tc.flags() == "-h acc"
    assert for_version(cce, 52).flags() == "-fopenmp"
    with pytest.raises(ValueError):
        for_version(TOOLCHAINS["afar"], 34).flags()
    assert "unset OMP_TARGET_OFFLOAD" in run_script(acc_tc, "x", 1, True)
    assert "OMP_TARGET_OFFLOAD=mandatory" in run_script(cce, "x", 1, True)


def _fake(exe):
    fakes = DATA / "fakes"
    return Toolchain("cce19", "", f"{fakes}/fake_fc.sh - 0 {fakes}/{exe}")


def test_acc_run_is_a_single_trial():
    (p,) = [q for q in legal() if q.primary_atom == "acc.directive.serial"]
    r = run_program(p, _fake("exe_abort.sh"), 1, repeats=1, timeout_s=20)
    assert r.model == "acc" and r.version == 34
    assert r.outcome == Outcome.wrong_answer
    assert "without mandatory" not in r.reason
    assert r.flags.startswith("-h acc")
    r = run_program(p, _fake("exe_device_pass.sh"), 1, repeats=1,
                    timeout_s=20)
    assert r.outcome == Outcome.correct_on_device


def test_acc_present_probe_reads_the_runtime_message(tmp_path):
    (p,) = [q for q in legal() if q.primary_atom == "acc.clause.present"]
    text = where.message("cce_acc_run_present").read_text() \
        .split("==== verbatim output below ====\n", 1)[1]
    # the captured miss names the program's present directive line
    line = int(re.search(r"\.f90:(\d+)", text).group(1))
    assert p.source.splitlines()[line - 1].lstrip().startswith(
        "!$acc parallel loop present(t)")
    msg = tmp_path / "m.txt"
    msg.write_text(text)
    exe = tmp_path / "probe.sh"
    exe.write_text(f"#!/bin/bash\ncat {msg} >&2\nexit 1\n")
    exe.chmod(0o755)
    tc = Toolchain("cce19", "", f"{DATA}/fakes/fake_fc.sh - 0 {exe}")
    r = run_program(p, tc, 0, repeats=1, timeout_s=20)
    assert r.outcome == Outcome.correct_on_device, r.reason
    assert r.reason.startswith("error_termination: ")


def test_program_from_file_reads_the_model(tmp_path):
    (p,) = [q for q in legal() if q.primary_atom == "acc.clause.copy"]
    f = tmp_path / "x.f90"
    f.write_text(p.source)
    assert program_from_file(f).model == "acc"


@pytest.mark.needs_spec
def test_support_table_for_acc_rows(tmp_path):
    from offload.engine import report
    progs = {p.id: p for p in programs()}
    rows = []
    for pid in ("acc34-directive-serial", "acc34-clause-num_gangs",
                "acc34-illegal-default-dsa-001"):
        p = progs[pid]
        for tc in ("cce19", "cce20"):
            rows.append(dict(
                program_id=pid, primary_atom=p.primary_atom, atoms=[],
                toolchain=tc, xnack=1, opt="-O2",
                outcome="rejected" if not p.legal else "correct_on_device",
                reason="ran_on_host=0 check=pass", flaky=False, flags="-h acc",
                needs=[], evidence=p.evidence, observable=p.observable,
                legal=p.legal, violates=p.violates, version=34, model="acc"))
    res = tmp_path / "acc_matrix.jsonl"
    res.write_text("".join(json.dumps(r) + "\n" for r in rows))
    saved = list(report.TOOLCHAINS)
    try:
        _check_acc_table(report, res)
    finally:
        report.TOOLCHAINS[:] = saved


def _check_acc_table(report, res):
    table = report.build_table(res, audit=None)
    assert report.table_model(table) == "acc"
    assert report.TOOLCHAINS == ["cce19", "cce20"]
    labels = {(r.program_id, r.toolchain): r.label for r in table}
    assert labels[("acc34-clause-num_gangs", "cce19")] == \
        report.NO_ORACLE_TEXT["hint_only"]
    csv_text = report.render_csv(table)
    assert csv_text.splitlines()[0].split(",") == list(report.CSV_FIELDS)
    assert ",34,acc34-" not in csv_text and csv_text.splitlines()[1] \
        .startswith("34,acc34-")
    md = report.render_markdown(table, [], claims=[], baseline=[], meta={})
    assert md.startswith("# Support table: OpenACC 3.4")
    assert "omp_vv" not in md
    assert "OpenACC 3.4 §2.5.2, p.34" in md  # serial's section
    cite = report.rule_citation("ACC34-default-dsa-001")
    assert cite[0] == "OpenACC 3.4 §2.6.2, p.42"
    assert report.atom_citation("acc.clause.copy", 34)[0] == \
        "OpenACC 3.4 §2.7.7, p.54"
