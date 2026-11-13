"""The legality gate (offload.engine.confirm.legality)."""
import os

import pytest

from offload.engine.confirm import legality as L
from offload.engine.confirm import programs as P
from offload.engine.confirm.model import ProgramRef
from offload.engine.expected import AMDFLANG

LEGAL_F = """program t
  implicit none
  integer :: a(8), i
  a = 0
  !$omp target teams distribute parallel do map(tofrom: a)
  do i = 1, 8
    a(i) = i
  end do
  print *, sum(a)
end program t
"""

HOST_ONLY = """program t
  implicit none
  integer :: a(8), i
  !$omp parallel do
  do i = 1, 8
    a(i) = i
  end do
  print *, sum(a)
end program t
"""

LEGAL_C = """#include <stdio.h>
int main(void) {
  int a[8];
  #pragma omp target teams distribute parallel for map(from: a)
  for (int i = 0; i < 8; i++) a[i] = i;
  printf("%d\\n", a[7]);
  return 0;
}
"""


def ref(text, lang="f90", kind="file"):
    return ProgramRef(kind, "t", lang, 52, text=text)


def test_catalog_programs_are_legal_or_illegal_by_construction():
    assert L.gate(ProgramRef("catalog", "omp52-clause-map-to")).status == \
        "legal"
    g = L.gate(ProgramRef("catalog", "omp52-illegal-x", legal_claim=False))
    assert g.status == "illegal" and "illegal catalog variant" in g.basis


def test_fuzz_programs_by_their_stored_check():
    r = ProgramRef("fuzz", "s1-00:8", text="x")
    assert L.gate(r, "ok").status == "legal"
    assert L.gate(r, "gfortran").status == "illegal"
    # AFAR flang's front end has known false rejections
    assert L.gate(r, "flang").status == "unknown"


@pytest.mark.gfortran
@pytest.mark.skipif(not os.path.exists(AMDFLANG), reason="no AFAR")
def test_legal_fortran_file_by_the_checkers():
    g = L.gate(ref(LEGAL_F))
    assert g.status == "legal", g


@pytest.mark.gfortran
@pytest.mark.skipif(not os.path.exists(AMDFLANG), reason="no AFAR")
def test_out_of_scope_file_is_not_legal_for_the_catalog():
    g = L.gate(ref(HOST_ONLY))
    assert g.status == "unknown"
    assert g.rulings == ("RUL-SCOPE-STRUCTURAL",)


@pytest.mark.gfortran
@pytest.mark.skipif(not os.path.exists(AMDFLANG), reason="no AFAR")
def test_a_rule_violation_is_illegal():
    """Illegal only when both witnesses reject it; when the front
    end accepts it the witnesses disagree (legality review)."""
    prog = next(p for p in P._catalog(52, "f90").values() if not p.legal)
    g = L.gate(ref(prog.source))
    assert g.status in ("illegal", "unknown") and prog.violates in g.basis
    if g.status == "unknown":
        assert "witnesses disagree" in g.basis


@pytest.mark.skipif(not os.path.exists(AMDFLANG), reason="no AFAR")
def test_legal_c_file_by_the_checkers():
    g = L.gate(ref(LEGAL_C, "c"))
    assert g.status == "legal", g
    # a user file is not generator output: a strict base-language
    # rejection makes it unknown, not illegal (review Minor 1)
    g = L.gate(ref(LEGAL_C.replace("int a[8];", "int a[8]"), "c"))
    assert g.status == "unknown"


def test_corpus_fortran_is_unknown():
    """RUL-OMPVV-UNTRUSTED: omp_vv stays untrusted (C and Fortran)."""
    g = L.gate(ProgramRef("ompvv", "tests/4.5/x.F90", text="program x\nend"))
    assert g.status == "unknown" and g.rulings == ("RUL-OMPVV-UNTRUSTED",)
    g = L.gate(ProgramRef("ompvv", "tests/5.0/x.c", "c", text=LEGAL_C))
    assert g.status == "unknown"


@pytest.mark.gfortran
def test_frontend_rejection_alone_does_not_count(monkeypatch):
    """The flang checker is not run for an AFAR case, and
    for another compiler's case its rejection alone does not count. Legality needs two witnesses, so an AFAR case without a witness
    from another machine, and a case the witnesses disagree on, are
    unknown (the legality review), never legal or illegal."""
    from offload.engine import fuzz
    from offload.engine.confirm import witness as W
    calls = []

    def flang(src):
        calls.append(1)
        return "semantics: error: not allowed"
    monkeypatch.setattr(fuzz, "check_flang", flang)
    monkeypatch.setattr(W, "verdict_of", lambda *a, **k: None)
    g = L.gate(ref(LEGAL_F), under_test=("afar",))
    assert g.status == "unknown" and not calls and "one witness" in g.basis
    g = L.gate(ref(LEGAL_F), under_test=("cce",))
    assert g.status == "unknown" and calls
    assert "witnesses disagree" in g.basis
    assert g.rulings == ("RUL-NO-SELF-CHECK",)


@pytest.mark.gfortran
def test_a_witness_from_another_machine_for_an_afar_case(monkeypatch):
    """NVHPC's stored verdict (catalog/legality_witness.yaml) is
    the second witness of an AFAR case."""
    from offload.engine.confirm import witness as W
    monkeypatch.setattr(W, "verdict_of",
                        lambda *a, **k: ("nvhpc269_f90 26.9-0", "accept"))
    g = L.gate(ref(LEGAL_F), under_test=("afar",))
    assert g.status == "legal" and "nvhpc269_f90" in g.basis
    monkeypatch.setattr(W, "verdict_of",
                        lambda *a, **k: ("nvhpc269_f90 26.9-0", "reject"))
    g = L.gate(ref(LEGAL_F), under_test=("afar",))
    assert g.status == "unknown" and "witnesses disagree" in g.basis


@pytest.mark.gfortran
@pytest.mark.skipif(not os.path.exists(AMDFLANG), reason="no AFAR")
@pytest.mark.parametrize("name,lang,family,rule,status", [
    # the rules and clang (not the compiler under test) both reject it
    ("fresh-042.c", "c", "cce", "alloc-in-target-predefined", "illegal"),
    ("fresh-042.c", "c", "nvhpc", "alloc-in-target-predefined", "illegal"),
    # clang is AFAR's own front end: one witness
    ("fresh-042.c", "c", "afar", "alloc-in-target-predefined", "unknown"),
    # the rules reject it, flang accepts it: the witnesses disagree
    ("fresh-070.f90", "f90", "cce", "declare-target-module-variable",
     "unknown"),
    ("fresh-070.f90", "f90", "nvhpc", "declare-target-module-variable",
     "unknown"),
    ("fresh-070.f90", "f90", "afar", "declare-target-module-variable",
     "unknown"),
    ("fresh-076.f90", "f90", "cce", "acc-loop-reduction-data-clause",
     "unknown"),
    ("fresh-076.f90", "f90", "nvhpc", "acc-loop-reduction-data-clause",
     "unknown")])
def test_the_three_non_conforming_programs_are_not_legal(name, lang, family,
                                                         rule, status):
    """The gate called fresh-042, fresh-070
    and fresh-076 (the drafts' originals) legal. The exact
    status per family: illegal where both witnesses ran and reject;
    unknown where one witness is the compiler under test's own front end
    or the witnesses disagree."""
    from pathlib import Path
    path = Path(__file__).resolve().parent.parent.parent / "data" / "bench" / "fresh" / name
    r = P.file_ref([str(path)])
    g = L.gate(r, under_test=(family,))
    assert g.status == status, g
    assert rule in g.basis or rule in str(g.checks.get("rules")), g
    if status == "unknown":
        assert ("witnesses disagree" in g.basis) == (family != "afar") \
            or name == "fresh-042.c", g


def test_declare_mapper_on_a_typedef_struct_is_legal():
    """The gate's declare mapper rule called
    a typedef'd struct illegal."""
    from offload.engine.rules import parse_program, violations
    good = """typedef struct { int n; double *d; } vec_t;
#pragma omp declare mapper(vm: vec_t v) map(v.n, v.d[0:v.n])
int main(void) { vec_t x; x.n = 0; return 0; }
"""
    assert "OMP52-declaremapper-clause-006" not in violations(
        parse_program(good, 52, "c"), 52)
    chain = good.replace("int main", "typedef vec_t vec2_t;\n"
                         "#pragma omp declare mapper(v2: vec2_t w) map(w.n)\n"
                         "int main")
    assert "OMP52-declaremapper-clause-006" not in violations(
        parse_program(chain, 52, "c"), 52)
    bad = """typedef int myint;
#pragma omp declare mapper(mi: myint v) map(v)
int main(void) { return 0; }
"""
    assert "OMP52-declaremapper-clause-006" in violations(
        parse_program(bad, 52, "c"), 52)
    ptr = """typedef struct { int n; } s_t;
typedef s_t *sp_t;
#pragma omp declare mapper(sp: sp_t v) map(v[0:1])
int main(void) { return 0; }
"""
    assert "OMP52-declaremapper-clause-006" in violations(
        parse_program(ptr, 52, "c"), 52)
    # An enum type, named or through a typedef
    for en in ("""typedef enum { RED, BLUE } color_t;
#pragma omp declare mapper(cm: color_t v) map(v)
int main(void) { return 0; }
""", """enum color { RED, BLUE };
#pragma omp declare mapper(cm: enum color v) map(v)
int main(void) { return 0; }
"""):
        assert "OMP52-declaremapper-clause-006" in violations(
            parse_program(en, 52, "c"), 52), en


@pytest.mark.gfortran
@pytest.mark.skipif(not os.path.exists(AMDFLANG), reason="no AFAR")
def test_declared_host_device_pattern_is_in_scope():
    """A host construct feeding target regions is in scope when
    the program declares the pattern."""
    src = HOST_ONLY.replace("  !$omp parallel do\n",
                            "  !$omp parallel do\n").replace(
        "    a(i) = i\n", "    !$omp target map(tofrom: a)\n"
        "    a(i) = i\n    !$omp end target\n")
    assert L.gate(ref(src)).status == "unknown"
    src = "! scope: host+device: one target region per host thread\n" + src
    assert L.gate(ref(src)).status == "legal"


def test_fuzz_program_with_a_known_generator_defect_is_illegal():
    """A stored check "ok" does not make a program with a known
    generator defect (G1, offload.engine.fuzz.generator_defects) legal."""
    from offload.engine import fuzz
    src = fuzz.generate(10, "fuzz-3", ("types", "derived", "alloc",
                                       "declare", "multitu")).source
    ref = ProgramRef("fuzz", "s1:10", "f90", 52, text=src,
                     expected="checksum=1")
    lg = L.gate(ref, "ok")
    assert lg.status == "illegal" and "G1" in lg.basis
    assert lg.rulings == ("RUL-FUZZ-G1-ILLEGAL",)
    src4 = fuzz.generate(10, "fuzz-4", ("types", "derived", "alloc",
                                        "declare", "multitu")).source
    assert L.gate(ProgramRef(**{**ref.__dict__, "text": src4}),
                  "ok").status == "legal"
