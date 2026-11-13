"""OpenMP in C (catalog lang axis, C grammar forms, the C program
scanner, the C rules, the Fortran-to-C translator, the C programs, the
clang oracle, the C toolchain recipes, C mutation, the C report column,
the omp_vv C reading)."""
import re
from pathlib import Path

import pytest

from offload.engine import c_gen, f2c
from offload.engine.c_program import is_c_source, parse_c_program
from offload.engine.catalog import (atom_langs, default_grammar, default_skeleton,
                                feature, for_twin, slice_atoms,
                                slice_directives)
from offload.engine.grammar import GrammarError, parse_directive
from offload.engine.rules import default_rules, parse_program, violations
from offload.engine.toolchains import C_FLAGS, TOOLCHAINS

ROOT = Path(__file__).resolve().parent.parent.parent


# --- the catalog's language axis -------------------------------------------------

@pytest.mark.parametrize("version", [52, 60])
def test_c_slice_shares_atoms_with_fortran(version):
    f = set(slice_atoms(version))
    c = set(slice_atoms(version, lang="c"))
    f_only = {a for a in f - c if not a.startswith("omp.directive.")}
    assert {"omp.clause.defaultmap.allocatable",
            "omp.clause.defaultmap.character", "omp.clause.linear.ref",
            "omp.clause.linear.uval", "omp.clause.reduction.eqv",
            "omp.clause.reduction.neqv"} <= f_only
    assert c - f == {a.replace("_do", "_for") for a in f - c
                     if a.startswith("omp.directive.") and "_do" in a} | {
        "omp.directive.begin_declare_target"}
    if version == 60:
        assert {"omp.clause.map.ref_ptee", "omp.clause.enter.automap",
                "omp.clause.default.allocatable"} <= f_only
    # the shared atoms of the C reduction identifiers
    for op in ("and", "or", "iand", "ior", "ieor", "max", "min", "plus"):
        assert f"omp.clause.reduction.{op}" in c


def test_atom_langs():
    langs = atom_langs(52)
    assert langs["omp.directive.target"] == {"f90", "c"}
    assert langs["omp.directive.parallel_do"] == {"f90"}
    assert langs["omp.directive.parallel_for"] == {"c"}
    assert langs["omp.directive.begin_declare_target"] == {"c"}


def test_c_operator_features():
    assert [feature(o) for o in ("&&", "||", "&", "|", "^")] == [
        "and", "or", "iand", "ior", "ieor"]


def test_do_overrides_are_mirrored_on_for_twins():
    g = default_grammar()
    assert for_twin("target parallel do simd") == "target parallel for simd"
    assert for_twin("target teams") is None
    assert ("parallel for", "induction") in g.mirrored
    sk = default_skeleton()
    assert "induction" in g.allowed(sk, "parallel for")
    assert "begin declare target" in slice_directives(sk, lang="c")
    assert set(g.allowed(sk, "begin declare target")) == {"device_type",
                                                          "indirect"}


# --- the C grammar -------------------------------------------------------------------

def C(text, version=52):
    return parse_directive(text, "c", version)


def code(text, version=52):
    try:
        C(text, version)
    except GrammarError as err:
        return err.code
    return None


def test_c_pragma_and_continuation():
    d = C("#pragma omp target teams distribute parallel for map(to: a[0:n]) "
          "\\\n    reduction(&&: x) reduction(^: y)")
    assert d.name == "target teams distribute parallel for"
    assert {"omp.clause.reduction.and", "omp.clause.reduction.ieor",
            "omp.clause.map.to"} <= d.atoms
    assert d.clauses[0].args == ["a[0:n]"]


@pytest.mark.parametrize("text,err", [
    ("#pragma omp parallel do", "wrong_language"),
    ("#pragma omp parallel for reduction(.and.: x)", "bad_argument"),
    ("#pragma omp parallel for reduction(.eqv.: x)", "bad_argument"),
    ("#pragma omp target defaultmap(to: allocatable)", "bad_argument"),
    ("#pragma omp parallel for linear(x: ref)", None),  # a step named ref
    ("#pragma omp parallel for linear(x: ref, step(1))", "bad_argument"),
    ("#pragma omp begin declare target to(f)", "clause_not_allowed"),
])
def test_c_grammar_rejections(text, err):
    assert code(text) == err


def test_c_6_0_forms():
    assert code("#pragma omp target map(ref_ptee, to: p[0:4])", 60) == \
        "bad_argument"
    assert code("#pragma omp declare target enter(automap: g)", 60) == \
        "bad_argument"
    assert code("#pragma omp begin declare target", 60) is None
    assert code("#pragma omp end declare target", 60) is None
    assert code("#pragma omp target map(self: a)", 60) is None


def test_fortran_grammar_unchanged_by_c_forms():
    F = "fortran"
    assert "omp.clause.reduction.eqv" in parse_directive(
        "!$omp parallel do reduction(.eqv.: x)", F, 52).atoms
    assert "omp.clause.map.ref_ptee" in parse_directive(
        "!$omp target map(ref_ptee, to: p)", F, 60).atoms
    with pytest.raises(GrammarError):
        parse_directive("!$omp parallel do reduction(&&: x)", F, 52)


# --- the C scanner -------------------------------------------------------------------

SRC = """\
#include <omp.h>
enum { n = 64 };
int dv = 1;
#pragma omp declare target(dv)
struct dt { int v; int f : 3; };
union uu { int i; float x; };
static int g(int x) { return x; }
#pragma omp begin declare target
int h(int x) { return x; }
#pragma omp end declare target
int main(void) {
  int a[n], b[n];
  int *p = a;
  const int k = 2;
  #pragma omp target teams distribute parallel for collapse(2) \\
      map(to: a) map(from: b)
  for (int i = 1; i <= 8; i++) {
    for (int j = 1; j <= 8; j++) {
      b[(i - 1) * 8 + j - 1] = a[(i - 1) * 8 + j - 1];
    }
  }
  #pragma omp target
  {
    #pragma omp teams
    {
      b[0] = 1;
    }
  }
  if (k)
    #pragma omp target update to(a)
  ;
  return 0;
}
"""


def test_scanner_tree():
    t = parse_c_program(SRC, 52)
    names = [d.name for d in t.directives]
    assert names == ["declare target", "begin declare target",
                     "target teams distribute parallel for", "target",
                     "teams", "target update"]
    a = t.assoc[2]
    assert (a.kind, a.loop_depth, a.loop_vars) == ("loop", 2, ("i", "j"))
    assert a.loop_bounds[0] == ("1", "8", "1") and a.intervening == (0, 1)
    assert a.line == 15 and a.end_line == 21
    assert t.nesting == [(3, 4)]
    assert t.assoc[3].stmts == 0 and t.assoc[4].stmts == 1
    assert t.ends[1].name == "end declare target"
    assert t.assoc[1].kind == "standalone" and t.assoc[1].end_line == 10
    assert t.extra["substatement"] == {5}
    assert t.lang == "c" and is_c_source(SRC)
    main = next(s for s, (k, nm) in t.units.items() if nm == "main")
    assert t.units[main][0] == "program"
    assert (0, "dv") in t.saved and (0, "n") in t.params
    assert any(k[1] == "p" and v == "pointer" for k, v in t.decls.items())
    assert any(k[1] == "a" for k in t.arrays)
    assert t.extra["struct_members"][(0, "dt")]["bitfields"] == {"f"}


def test_scanner_unclosed_delimited_region_raises():
    from offload.engine.rules import ProgramError
    with pytest.raises(ProgramError, match="never closed"):
        parse_c_program("#pragma omp begin declare target\nint g;\n", 52)
    with pytest.raises(ProgramError, match="without begin"):
        parse_c_program("#pragma omp end declare target\n", 52)


def test_parse_program_dispatches_on_the_language():
    assert parse_program(SRC, 52).lang == "c"
    f = "program p\n!$omp target\nx = 1\n!$omp end target\nend program p\n"
    assert parse_program(f, 52).lang == "f90"


@pytest.mark.parametrize("header,canon", [
    ("for (int i = 0; i < n; i++)", True),
    ("for (i = n; i >= 0; i -= 2)", True),
    ("for (int i = 0; n > i; i = i + 1)", True),
    ("for (int i = 0; i < n; i *= 2)", False),
    ("for (int i = 0; i + 1 < n; i++)", False),
    ("for (;;)", False),
])
def test_canonical_shape(header, canon):
    src = ("int main(void) { int i, n = 8, a[8];\n#pragma omp parallel for\n"
           f"{header} a[0] = 1;\nreturn 0; }}\n")
    t = parse_c_program(src, 52)
    assert (t.assoc[0].loop_depth == 1) == canon


# --- the C rules: one legal and one illegal program per C rule ---------------------

def cprog(*body, top=()):
    return "\n".join(
        ["#include <omp.h>", "enum { n = 64 };"] + list(top)
        + ["int main(void) {", "  int a[64], b[64], c[64];",
           "  int x = 0, s = 0, t = 0;", "  int *p = a;"]
        + ["  " + ln for ln in body] + ["  return 0;", "}"]) + "\n"


BF = ["struct bf { int f : 4; int g; };", "union uv { int i; float y; };"]
LOOP = ["#pragma omp parallel for", "for (int i = 0; i < 8; i++) {",
        "  a[i] = i;", "}"]


def loop(header, body="a[0] = 1;", directive="#pragma omp parallel for"):
    return [directive, header + " {", "  " + body, "}"]


C_CASES = {
    "requires-placement-005": (
        cprog("#pragma omp target", "{ x = 1; }",
              top=["#pragma omp requires unified_shared_memory"]),
        cprog("#pragma omp requires unified_shared_memory", "x = 1;")),
    "directive-placement-001": (
        cprog("if (x) {", "  #pragma omp target update to(a)", "}"),
        cprog("if (x)", "  #pragma omp target update to(a)", ";")),
    "canonical-loop-001": (
        cprog(*loop("for (int i = 0; i < 8; i++)")),
        cprog(*loop("for (int i = 9; i < 8; i--)"))),
    "canonical-loop-002": (
        cprog(*loop("for (int i = 0; 8 > i; i++)")),
        cprog(*loop("for (int i = 9; 8 > i; i--)"))),
    "canonical-loop-003": (
        cprog(*loop("for (int i = 0; i != 8; i++)")),
        cprog(*loop("for (int i = 0; i != 8; i += 2)"))),
    "loopvar-loop-004": (
        cprog(*loop("for (int *q = a; q < a + 8; q++)", "*q = 1;")),
        cprog(*loop("for (double d = 0; d < 8; d++)"))),
    "intervening-loop-001": (
        cprog("#pragma omp parallel for collapse(2)",
              "for (int i = 0; i < 8; i++) {", "  x = i;",
              "  for (int j = 0; j < 8; j++) {", "    while (0) { }",
              "    a[j] = i;", "  }", "}"),
        cprog("#pragma omp parallel for collapse(2)",
              "for (int i = 0; i < 8; i++) {", "  while (0) { }",
              "  for (int j = 0; j < 8; j++) {", "    a[j] = i;", "  }",
              "}")),
    "finalbody-loop-001": (
        cprog(*loop("for (int i = 0; i < 8; i++)",
                    "switch (i) { case 1: break; }")),
        cprog(*loop("for (int i = 0; i < 8; i++)", "if (i == 3) break;"))),
    "linear-clause-005": (
        cprog("#pragma omp parallel for linear(x: 1)",
              "for (int i = 0; i < 8; i++) {", "  x = x + 1;", "}"),
        cprog("double dx = 0;", "#pragma omp parallel for linear(dx: 1)",
              "for (int i = 0; i < 8; i++) {", "  dx = dx + 1;", "}")),
    "aligned-clause-003": (
        cprog(*loop("for (int i = 0; i < 8; i++)", "p[i] = i;",
                    "#pragma omp simd aligned(p: 8)")),
        cprog(*loop("for (int i = 0; i < 8; i++)", "a[i] = i;",
                    "#pragma omp simd aligned(x: 8)"))),
    "isdeviceptr-clause-001": {
        v: (cprog("#pragma omp target is_device_ptr(p)", "{ p[0] = 1; }"),
            cprog("#pragma omp target is_device_ptr(x)", "{ t = 1; }"))
        for v in (50, 52)},  # 5.0
    "reduction-clause-007": (
        cprog(*loop("for (int i = 0; i < 8; i++)", "s = s > i ? s : i;",
                    "#pragma omp parallel for reduction(max: s)")),
        cprog(*loop("for (int i = 0; i < 8; i++)", "x = i;",
                    "#pragma omp parallel for reduction(max: p)"))),
    "reduction-clause-008": (
        cprog(*loop("for (int i = 0; i < 8; i++)", "s += i;",
                    "#pragma omp parallel for reduction(+: s)")),
        cprog("const int cs = 0;",
              *loop("for (int i = 0; i < 8; i++)", "x = i;",
                    "#pragma omp parallel for reduction(+: cs)"))),
    "privatization-dsa-001": (
        cprog("const int ct = 1;",
              *loop("for (int i = 0; i < 8; i++)", "a[i] = ct;",
                    "#pragma omp parallel for firstprivate(ct)")),
        cprog("const int ct = 1;",
              *loop("for (int i = 0; i < 8; i++)", "a[i] = i;",
                    "#pragma omp parallel for private(ct)"))),
    "map-clause-003": (
        cprog("struct bf v;", "#pragma omp target map(tofrom: v.g)",
              "{ v.g = 1; }", top=BF),
        cprog("struct bf v;", "#pragma omp target map(tofrom: v.f)",
              "{ x = 1; }", top=BF)),
    "map-clause-004": (
        cprog("union uv u;", "#pragma omp target map(tofrom: u)",
              "{ u.i = 1; }", top=BF),
        cprog("union uv u;", "#pragma omp target map(tofrom: u.i)",
              "{ x = 1; }", top=BF)),
    "depend-clause-005": (
        cprog("struct bf v;", "#pragma omp task depend(out: v.g)",
              "{ v.g = 1; }", top=BF),
        cprog("struct bf v;", "#pragma omp task depend(out: v.f)",
              "{ x = 1; }", top=BF)),
    "declaremapper-clause-006": {
        50: (cprog("x = 1;", top=BF + [
            "#pragma omp declare mapper(m1: struct bf v) map(v.g)"]),
            cprog("x = 1;", top=["#pragma omp declare mapper(m1: int v) "
                                 "map(v)"])),
        52: (cprog("x = 1;", top=BF + [
            "#pragma omp declare mapper(m1: struct bf v) map(v.g)"]),
            cprog("x = 1;", top=["#pragma omp declare mapper(m1: int v) "
                                 "map(v)"])),
        60: (cprog("x = 1;", top=BF + [
            "#pragma omp declare_mapper(m1: struct bf v) map(v.g)"]),
            cprog("x = 1;", top=["#pragma omp declare_mapper(m1: int v) "
                                 "map(v)"]))},
    "arraysection-clause-003": (
        cprog("#pragma omp target update to(a[0:4])"),
        cprog("#pragma omp target update to(x[0:4])")),
    "arraysection-clause-004": (
        cprog("#pragma omp target update to(a[0:4:2])"),
        cprog("#pragma omp target update to(a[0:4:0])")),
    "arraysection-clause-005": (
        cprog("#pragma omp target update to(a[0:0])"),
        cprog("#pragma omp target update to(a[0:-1])")),
    "default-dsa-002": (
        cprog("#pragma omp parallel default(firstprivate) shared(gz)",
              "{ x = gz; }", top=["int gz = 0;"]),
        cprog("#pragma omp parallel default(firstprivate)", "{ x = gz; }",
              top=["int gz = 0;"])),
    "declaretarget-placement-004": {
        60: (cprog("x = 1;", top=["int gz = 0;",
                                  "#pragma omp declare target(gz)"]),
             cprog("#pragma omp declare target(gz)", "x = 1;",
                   top=["int gz = 0;"]))},
    "declarereduction-clause-001": {
        50: (cprog("x = 1;", top=["#pragma omp declare reduction(r: int: "
                                  "omp_out += omp_in)"]),
             cprog("x = 1;", top=["#pragma omp declare reduction(r: const "
                                  "int: omp_out += omp_in)"])),
        52: (cprog("x = 1;", top=["#pragma omp declare reduction(r: int: "
                                  "omp_out += omp_in)"]),
             cprog("x = 1;", top=["#pragma omp declare reduction(r: const "
                                  "int: omp_out += omp_in)"])),
        60: (cprog("x = 1;", top=["#pragma omp declare_reduction(r: int: "
                                  "omp_out += omp_in)"]),
             cprog("x = 1;", top=["#pragma omp declare_reduction(r: "
                                  "const int: omp_out += omp_in)"]))},
}

# rules of both languages, with C cases (the C reading of their predicates)
C_CASES_BOTH = {
    # C ranges exclude the end: 0:1 is the one value 0; 0:8 gives
    # a[0], ..., a[7], instances with the same containing array
    "map-clause-005": (
        cprog("#pragma omp target map(iterator(it = 0:1), tofrom: a[it:8])",
              "{ a[0] = 1; }"),
        cprog("#pragma omp target map(iterator(it = 0:8), tofrom: a[it])",
              "{ a[0] = 1; }")),
    "default-dsa-001": (
        cprog("#pragma omp parallel for default(none) shared(a)",
              "for (int i = 0; i < 8; i++) {", "  int y = i;",
              "  a[i] = y;", "}"),
        cprog("#pragma omp parallel default(none) shared(a)",
              "{ a[0] = x; }")),
    "listitem-clause-001": (
        cprog("#pragma omp parallel private(t)", "{ t = 1; }"),
        cprog("#pragma omp parallel private(a[1])", "{ t = 1; }")),
    "mapitem-map-002": (
        cprog("#pragma omp target map(to: a) map(to: b[0:4])",
              "{ x = a[0]; }"),
        cprog("#pragma omp target map(to: a) map(to: a[0:4])",
              "{ x = a[0]; }")),
    "loopvar-loop-001": (
        cprog(*loop("for (int i = 0; i < 8; i++)", "a[i] = i;")),
        cprog(*loop("for (int i = 0; i < 8; i++)", "i = i + 1;"))),
    "collapse-loop-001": (
        cprog("#pragma omp parallel for collapse(2)",
              "for (int i = 0; i < 8; i++)", "  for (int j = 0; j < 8; j++)",
              "    a[j] = i;"),
        cprog("#pragma omp parallel for collapse(3)",
              "for (int i = 0; i < 8; i++)", "  for (int j = 0; j < 8; j++)",
              "    a[j] = i;")),
    "teams-nesting-002": (
        cprog("#pragma omp target", "{", "  #pragma omp teams",
              "  { x = 1; }", "}"),
        cprog("#pragma omp target", "{", "  t = 1;", "  #pragma omp teams",
              "  { x = 1; }", "}")),
    "reduction-clause-006": (
        cprog(*loop("for (int i = 0; i < 8; i++)", "a[0] += i;",
                    "#pragma omp parallel for reduction(+: a[0:2])")),
        cprog(*loop("for (int i = 0; i < 8; i++)", "a[0] += i;",
                    "#pragma omp parallel for reduction(+: a[0:0])"))),
    "target-map-002": (
        cprog("struct bf v;", "#pragma omp target map(tofrom: v.g)",
              "{ v.g = 1; }", top=BF),
        cprog("struct bf v;", "#pragma omp target map(tofrom: v.g)",
              "{ v.g = v.f; }", top=BF)),
    "requires-placement-002": (
        cprog("#pragma omp target", "{ x = 1; }",
              top=["#pragma omp requires unified_shared_memory"]),
        cprog("#pragma omp target", "{ x = 1; }") +
        "#pragma omp requires unified_shared_memory\n"),
}

C_RULES = [r for r in default_rules() if r.lang == "c"]
BOTH_RULES = [r for r in default_rules() if r.check == "static"
              and r.id.split("-", 1)[1] in C_CASES_BOTH and r.version > 50]


def test_every_c_rule_has_cases():
    assert {r.id.split("-", 1)[1] for r in C_RULES} == set(C_CASES)
    assert all(r.check == "static" for r in C_RULES)


def _case(table, rule):
    case = table[rule.id.split("-", 1)[1]]
    return case[rule.version] if isinstance(case, dict) else case


@pytest.mark.parametrize("rule", C_RULES + BOTH_RULES, ids=lambda r: r.id)
def test_c_rule_legal_and_illegal(rule):
    table = C_CASES if rule.lang == "c" else C_CASES_BOTH
    legal, illegal = _case(table, rule)
    v = rule.version
    assert violations(parse_program(legal, v), v) == []
    assert violations(parse_program(illegal, v), v) == [rule.id]


def test_c_rules_never_fire_on_fortran():
    f = ("program p\n  integer :: x\n  !$omp requires unified_shared_memory"
         "\n  x = 1\nend program p\n")
    assert not [r for r in violations(parse_program(f, 52), 52)
                if r.endswith("placement-005")]


def test_fortran_only_rules_do_not_fire_on_c():
    langs = {r.id: r.lang for r in default_rules()}
    for v in (52, 60):
        for p in c_gen.all_c_programs(v):
            for rid in violations(parse_program(p.source, v), v):
                assert langs[rid] in ("both", "c"), (p.id, rid)


@pytest.mark.needs_spec
@pytest.mark.parametrize("version", [52, 60])
def test_c_rule_texts_are_in_the_spec(version):
    # the citation checks of tests/engine/test_generators.py cover every rule; here the
    # C rules' sentences are C/C++ text of their sections
    from offload.engine import spec_text
    for r in C_RULES:
        if r.version != version:
            continue
        num = re.search(r"§([\d.]+)", r.citation).group(1)
        sec = next(s for s in spec_text.sections(f"{version // 10}."
                                                 f"{version % 10}").values()
                   if s.number == num)
        assert re.sub(r"\s+", "", r.text) in re.sub(r"\s+", "", sec.text)


# --- the translator --------------------------------------------------------------------

FHEAD = "! Generated by compliance.gen (OpenMP 5.2, free-form Fortran). " \
    "Do not edit.\n! id: x\n! primary atom: omp.directive.target\n" \
    "! legal: yes\n! observable: yes\n! ran_on_host: x\n" \
    "! evidence: construct\n! needs: none\n! std: f2008\n"


def tr(body, decls="", module=""):
    src = FHEAD + module + (
        "program gen_prog\n  use omp_lib, only: omp_is_initial_device\n"
        "  implicit none\n  integer, parameter :: n = 64\n"
        "  integer, allocatable, target :: a(:), b(:)\n  integer :: i\n"
        f"{decls}  allocate(a(n), b(n))\n{body}\nend program gen_prog\n")
    return f2c.translate(src, 52)


def test_translate_indices_sections_and_loops():
    c = tr("  do i = 1, n\n    b(i) = 2*a(i) + 1\n  end do\n"
           "  !$omp target update to(a(2:n - 1))")
    assert "for (int i = 1; i <= n; i++) {" in c
    assert "b[i - 1] = 2 * a[i - 1] + 1;" in c
    assert "#pragma omp target update to(a[1:n - 2])" in c
    assert "int a[n];" in c and "enum { n = 64 };" in c


def test_translate_iterator_range_is_exclusive_in_c():
    c = tr("  !$omp target enter data map(iterator(k = 1:n:2), to: a(k))",
           "  integer :: k\n")
    assert "map(iterator(k = 1:n + 1:2), to: a[k - 1])" in c


def test_translate_reductions_and_whole_arrays():
    c = tr("  b = 0\n  if (all(b == 0) .and. any(a == 1)) b(1) = count(a > 2)",
           "  logical :: ok\n")
    assert re.search(r"for \(int k\d+_ = 0; k\d+_ < n; k\d+_\+\+\)\n\s+"
                     r"b\[k\d+_\] = 0;", c)
    assert "bool t" in c and "if (t" in c and "++;" in c


def test_translate_do_becomes_for_and_end_clauses_move():
    c = tr("  !$omp parallel do\n  do i = 1, n\n    b(i) = a(i)\n  end do\n"
           "  !$omp end parallel do\n  !$omp parallel\n  !$omp do\n"
           "  do i = 1, n\n    b(i) = a(i)\n  end do\n  !$omp end do nowait\n"
           "  !$omp end parallel")
    assert "#pragma omp parallel for\n" in c
    assert "#pragma omp for nowait" in c


def test_translate_rejects_fortran_only_data():
    with pytest.raises(f2c.TranslateError):
        tr("  ch = 'a'", "  character :: ch\n")


def test_translate_declare_target_procedure():
    mod = ("module gen_mod\n  implicit none\n  contains\n"
           "    integer function f(x)\n      !$omp declare target\n"
           "      integer, intent(in) :: x\n      f = 2*x + 1\n"
           "    end function f\nend module gen_mod\n\n")
    c = tr("  b(1) = f(a(1))", module=mod)
    assert "#pragma omp begin declare target\nint f(int x) {" in c
    assert "return r_;\n}\n#pragma omp end declare target" in c


# --- the C programs ---------------------------------------------------------------------

@pytest.fixture(scope="module")
def programs():
    return {v: c_gen.all_c_programs(v) for v in (52, 60)}


def test_c_program_counts_and_ids(programs):
    for v, ps in programs.items():
        legal = [p for p in ps if p.legal]
        assert {p.primary_atom for p in legal} == set(c_gen.c_atoms(v))
        assert all(re.match(rf"omp{v}-c-", p.id) and p.lang == "c"
                   and p.std == "c11" for p in ps)
        assert not c_gen.C_UNGENERATABLE[v]
        assert len({p.id for p in ps}) == len(ps)


def test_c_programs_follow_the_output_contract(programs):
    for ps in programs.values():
        for p in ps:
            assert 'printf("RESULT ran_on_host=%d check=%s\\n", host_flag, ' \
                'ok ? "pass" : "fail");' in p.source
            assert "omp_is_initial_device()" in p.source
            assert "device_c_f_pointer" not in p.needs


def test_c_programs_carry_the_fortran_evidence(programs):
    from offload.engine import gen as G
    for p in programs[52]:
        if not p.legal or p.primary_atom in c_gen.C_LABELS:
            continue
        if p.primary_atom in c_gen.C_EDITS and p.evidence == "legality":
            # an edit that hands the oracle to an illegal variant
            # (defaultmap none): that variant must exist
            assert any(not q.legal and q.violates and
                       q.primary_atom == p.primary_atom
                       for q in programs[52]), p.id
            continue
        fa = (c_gen.fortran_atom(p.primary_atom)
              if p.primary_atom != "omp.directive.begin_declare_target"
              else "omp.directive.declare_target")
        # A host+device pattern is the port of the Fortran pattern
        f = G._hostdev(fa, 52) if p.scope == "host+device" else \
            G._legal(fa, 52)
        assert (p.evidence, p.observable, p.expect) == (
            f.evidence, f.observable, f.expect), p.id


def test_illegal_c_programs_violate_exactly_their_rule(programs):
    for v, ps in programs.items():
        for p in ps:
            if not p.legal:
                assert violations(parse_program(p.source, v), v) == \
                    [p.violates]


@pytest.mark.gfortran
def test_c_programs_are_c11(programs):
    # the base-language checker: gcc -std=c11 -pedantic-errors
    # -fsyntax-only, no -fopenmp (pragmas ignored), against OMP_H_STUB
    for ps in programs.values():
        for p in ps:
            ok, out = c_gen.gcc_check(p.source)
            assert ok, (p.id, out)


def test_omp_h_stub_declares_every_name_used(programs):
    for ps in programs.values():
        for p in ps:
            code = "\n".join(ln for ln in p.source.splitlines()
                             if not ln.startswith("//"))
            for name in set(re.findall(r"\bomp_\w+", code)):
                if name in ("omp_out", "omp_in", "omp_priv", "omp_orig",
                            "omp_impex"):
                    continue
                assert name in c_gen.OMP_H_STUB_NAMES, (p.id, name)


# --- the clang oracle -------------------------------------------------------------------

def test_clang_oracle_accepts_a_legal_program(programs):
    from offload.engine import clang_oracle
    p = c_gen.c_legal("omp.directive.target_teams_distribute_parallel_for",
                      52)
    chk = clang_oracle.syntax_check(p.source, 52)
    assert chk.ok, chk.errors
    groups = clang_oracle.clang_clauses(p.source, 52)
    assert ["map", "map", "map", "default", "shared"] == groups[0]


def test_clang_oracle_compare():
    from offload.engine import clang_oracle
    a = clang_oracle.compare("#pragma omp target map(to: a) map(from: b)", 52)
    assert a.verdict == "agree"
    a = clang_oracle.compare("#pragma omp teams distribute dist_schedule("
                             "static, 4)", 52)
    assert a.consulted and a.grammar_ok
    a = clang_oracle.compare("#pragma omp target nosuchclause", 52)
    assert not a.grammar_ok


# --- toolchains, harness, mutation ---------------------------------------------------

def test_c_toolchain_recipes():
    import dataclasses
    afar = dataclasses.replace(TOOLCHAINS["afar"], lang="c")
    assert afar.compile_cmd("p.c", "p.out").startswith(
        f"{TOOLCHAINS['afar'].cc} {C_FLAGS['afar']} -O2")
    for name in ("cce19", "cce20", "cce21"):
        tc = dataclasses.replace(TOOLCHAINS[name], lang="c")
        assert f"craycc {C_FLAGS['cce']} -O2 p.c" in tc.compile_cmd(
            "p.c", "p.out")
        assert "-march=gfx942" in tc.flags()
    from offload.engine.run_matrix import for_version
    assert "-fopenmp-version=52" in for_version(TOOLCHAINS["cce19"], 52,
                                                "c").flags()
    assert "-fopenmp-version" not in for_version(TOOLCHAINS["afar"], 52
                                                 ).flags()


def test_c_mutants():
    from offload.engine import mutate
    p = c_gen.c_legal("omp.directive.target_teams_distribute_parallel_for",
                      52)
    m = mutate.neutralise(p)
    assert "// MUTANT #pragma omp target teams distribute parallel for" \
        in m.source
    assert "\\\n" not in m.source.split("// MUTANT #pragma")[1].split(
        "\n")[0] + "\n"
    assert mutate.mutation_of(m).startswith("removed omp.directive.")
    p = c_gen.c_legal("omp.clause.map.to", 52)
    m = mutate.neutralise(p)
    assert "#pragma omp target map(a) map(from: b)" in m.source
    p = c_gen.c_legal("omp.clause.reduction.and", 52)
    m = mutate.neutralise(p)
    assert "shared(ls)" in m.source and "&&: ls" not in m.source
    assert mutate.illegal(m, 52) == []
    assert mutate.body_sha(p.source) == mutate.body_sha(
        "// another header\n" + p.source.split("\n", 9)[-1])


def test_every_c_program_has_a_conforming_mutant(programs):
    from offload.engine import mutate
    for v, ps in programs.items():
        for p in ps:
            if not p.legal:
                continue
            m = mutate.neutralise(p)
            if m is None:
                continue
            bad = mutate.illegal(m, v)
            assert not bad or p.primary_atom == "omp.clause.device.ancestor",\
                (p.id, bad)


# --- report, baseline, omp_vv --------------------------------------------------------------

def test_csv_lang_column_is_last():
    # Appended `scope` after it, then `portable` and
    # `mode_class`, then `arch` and `arch_class`, then `gate`; the
    # earlier columns keep their positions
    from offload.engine import report
    assert report.CSV_FIELDS[-8:] == ("lang", "scope", "portable",
                                      "mode_class", "presence_x1", "arch",
                                      "arch_class", "gate")
    assert report.Row("a", "afar", 1, "x", False).lang == "f90"
    assert report.Row("a", "afar", 1, "x", False).scope == "device"


def test_c_rows_match_claims_about_c():
    from offload.engine import report
    c = report.Claim(source="s", url="u", toolchain="afar",
                     claim="supported", version_note="",
                     atoms=("omp.directive.parallel_do",), language="C/C++")
    f = report.Claim(source="s", url="u", toolchain="afar",
                     claim="supported", version_note="",
                     atoms=("omp.directive.parallel_do",),
                     language="Fortran")
    row = report.Row("omp.directive.parallel_for", "afar", 1,
                     "correct_on_device", False, version=52, lang="c")
    assert report._matches(c, row) and not report._matches(f, row)


def test_baseline_selects_the_omp_vv_c_tests():
    from offload.engine.baseline import c_version_flag, select_files
    rows = select_files(ROOT / "data" / "index" / "corpus_index.csv", ["omp_vv"], "c")
    # OpenMP_VV f7d95b34 (was 315 on sollve_vv d978684)
    assert len(rows) == 340 and all(r["path"].endswith(".c") for r in rows)
    assert c_version_flag({"spec_dir": "4.5"}) == ""
    assert c_version_flag({"spec_dir": "5.1"}) == ""
    assert c_version_flag({"spec_dir": "5.2"}) == "-fopenmp-version=52"
    assert c_version_flag({"spec_dir": "6.0"}) == "-fopenmp-version=60"
    assert len(select_files(ROOT / "data" / "index" / "corpus_index.csv",
                            ["omp_vv"])) == 218  # OpenMP_VV f7d95b34 (216 on sollve_vv)


def test_ompvv_reads_c():
    from offload.engine.ompvv import copy_semantics, directive_lines
    src = ("int main(void) {\n  int a[8];\n"
           "#pragma omp target map(to: a[0:8]) \\\n   map(tofrom: x)\n"
           "  {\n    a[0] = 5;\n  }\n  return a[0];\n}\n")
    assert directive_lines(src) == ["target map(to: a[0:8]) map(tofrom: x)"]
    assert copy_semantics(src)
    ok = src.replace("map(to:", "map(tofrom:")
    assert copy_semantics(ok) == []


def test_c_coverage_atom_split():
    # tools/campaigns/c_coverage.py: the atom table counts the language split
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "c_coverage", ROOT / "tools" / "campaigns" / "c_coverage.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    text = "\n".join(mod._atoms_section())
    for v in c_gen.C_VERSIONS:
        # Begin declare target is new in 5.1
        assert ("omp.directive.begin_declare_target" in
                c_gen.c_only_atoms(v)) == (v > 50)
        assert "omp.clause.linear.uval" in c_gen.fortran_only_atoms(v)
    assert "| 5.2 |" in text and "| 6.0 |" in text


def test_map_iterator_rule_reads_integer_macros():
    """Omp_vv test_target_map_iterators.c maps
    test_lst[it] for it = 0:N with #define N 1024; the macro is read, so
    the instances with one containing array are seen."""
    src = ("#define N 4\nint main(void) {\n  int a[N];\n"
           "  #pragma omp target map(iterator(it = 0:N), tofrom: a[it])\n"
           "  { a[0] = 1; }\n  return 0;\n}\n")
    assert violations(parse_program(src, 52), 52) == ["OMP52-map-clause-005"]
    one = src.replace("0:N", "0:1").replace("a[it]", "a[it:N]")
    assert violations(parse_program(one, 52), 52) == []


def test_c_52_device_type_ports_use_enter():
    """The C 5.2 device_type programs name f in an enter
    clause (the deprecated to, which every clang C front end rejects at
    5.2, would make them measure that rejection instead of device_type)."""
    from offload.engine.c_gen import c_legal
    for atom in ("omp.clause.device_type", "omp.clause.device_type.any",
                 "omp.clause.device_type.nohost"):
        src = c_legal(atom, 52).source
        assert "declare target enter(f)" in src, atom
        assert "declare target to(" not in src, atom


def test_c_scanner_keeps_every_loop_frame_alive():
    """The C scanner records loop frames by id(); every frame is
    kept for the whole parse, so a freed frame's id is never given to a
    later loop (that made omp52-c-illegal-collapse-loop-001 read as
    violating a second rule on another host)."""
    from offload.engine.c_program import _For, _Scanner
    src = ("int main(void) {\n  int s = 0;\n"
           "  for (int i = 0; i < 4; i++) s += i;\n"
           "  for (int j = 0; j < 4; j++) { for (int k = 0; k < 2; k++) "
           "s += k; }\n  return s;\n}\n")
    sc = _Scanner(src, 52)
    sc.run()
    fors = [x for x in sc._alive if isinstance(x, _For)]
    assert len(fors) == 3
    assert len({id(f) for f in fors}) == 3
