"""Tests of the support tables and the vendor-claims check, their gate column, the toolchain list in catalog/toolchains.yaml, and tools/regenerate.py --check on the committed data."""
from __future__ import annotations


# ---- Tests of offload.engine.report: the support table and the vendor-claims check -----------------------

import where
import json
from pathlib import Path

import pytest
import yaml

from offload.engine.catalog import slice_atoms
from offload.engine.report import (CLAIMS, LEGALITY_TEXT, NO_ORACLE_TEXT,
                               UNVERIFIED_TEXT, Mismatch, Row, build_table,
                               compare_claims, family, load_claims,
                               render_csv, render_markdown)


def mrow(program_id, atom, toolchain, xnack, outcome="correct_on_device",
         reason="ran_on_host=0 check=pass", version=52, legal=True,
         violates=None, evidence="construct", needs=(), flaky=False):
    return {"program_id": program_id, "primary_atom": atom, "atoms": [atom],
            "toolchain": toolchain, "xnack": xnack, "opt": "-O2",
            "outcome": outcome, "reason": reason, "flaky": flaky,
            "flags": "-O2", "rocm": None, "stdout": "", "stderr": "",
            "needs": list(needs), "evidence": evidence, "observable": True,
            "legal": legal, "violates": violates, "version": version,
            "thp": "always" if xnack else "never"}


def write_matrix(path: Path, rows) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


def write_audit(path: Path, entries: dict) -> Path:
    """entries: {(version, atom): disposition}."""
    versions: dict = {}
    for (v, atom), disp in entries.items():
        versions.setdefault(str(v), {})[atom] = {"disposition": disp}
    path.write_text(json.dumps({"versions": versions}))
    return path


def write_claims(path: Path, claims: list) -> Path:
    path.write_text(yaml.safe_dump({"claims": claims}))
    return path


HPE_URL = "https://cpe.ext.hpe.com/docs/latest/cce/man7/intro_openmp.7.html"
REVERSE_OFFLOAD = {
    "source": "hpe-cce-intro-openmp", "url": HPE_URL, "toolchain": "cce19",
    "atom": "omp.clause.reverse_offload", "claim": "unsupported",
    "form": "compile_error", "status": "provisional",
    "quote": "The requires directive clauses dynamic_allocators and "
             "reverse_offload currently result in compile time errors.",
    "version_note": "intro_openmp(7) shipped with CCE 19.0.0",
}


def table(tmp_path, rows, audit=None):
    m = write_matrix(tmp_path / "matrix.jsonl", rows)
    a = write_audit(tmp_path / "audit.json", audit or {})
    return build_table(m, audit=a)


def by(rows, **kw):
    out = [r for r in rows if all(getattr(r, k) == v for k, v in kw.items())]
    assert len(out) == 1, out
    return out[0]


# --- the table -----------------------------------------------------------------------

def test_table_one_row_per_cell(tmp_path):
    rows = [mrow(p, a, tc, x)
            for p, a in (("omp52-directive-target", "omp.directive.target"),
                         ("omp52-clause-map-to", "omp.clause.map.to"))
            for tc in ("afar", "cce19") for x in (1, 0)]
    t = table(tmp_path, rows)
    assert len(t) == 8
    assert all(isinstance(r, Row) for r in t)
    cells = {(r.program_id, r.toolchain, r.xnack) for r in t}
    assert len(cells) == 8
    r = by(t, atom="omp.clause.map.to", toolchain="cce19", xnack=0)
    assert (r.outcome, r.flaky) == ("correct_on_device", False)


def test_duplicate_cell_is_an_error(tmp_path):
    rows = [mrow("p", "omp.directive.target", "afar", 1)] * 2
    with pytest.raises(ValueError, match="duplicate"):
        table(tmp_path, rows)


def test_illegal_rows_reduce_to_rejected_or_not(tmp_path):
    rows = [
        mrow("i1", "omp.directive.teams", "afar", 1, outcome="rejected",
             legal=False, violates="OMP52-teams-nesting-001"),
        mrow("i1", "omp.directive.teams", "cce19", 1, outcome="wrong_answer",
             reason="check_fail", legal=False,
             violates="OMP52-teams-nesting-001"),
        mrow("i1", "omp.directive.teams", "afar", 0,
             outcome="correct_on_device", legal=False,
             violates="OMP52-teams-nesting-001"),
    ]
    t = table(tmp_path, rows)
    assert by(t, toolchain="afar", xnack=1).outcome == "rejected"
    assert by(t, toolchain="cce19", xnack=1).outcome == "not_rejected"
    assert by(t, toolchain="afar", xnack=0).outcome == "not_rejected"
    assert all("wrong" not in r.label for r in t)


def test_unverified_atom_reads_accepted_unverified(tmp_path):
    rows = [mrow("p", "omp.clause.has_device_addr", "afar", 1,
                 outcome="unobservable", evidence="unverified"),
            mrow("p", "omp.clause.has_device_addr", "afar", 0,
                 outcome="correct_on_device", evidence="unverified")]
    t = table(tmp_path, rows, {(52, "omp.clause.has_device_addr"):
                               "unverified_oracle_not_written"})
    assert {r.label for r in t} == {UNVERIFIED_TEXT}
    assert UNVERIFIED_TEXT == ("accepted; unverified (an oracle is possible "
                               "but missing)")
    assert {r.evidence for r in t} == {"unverified"}


@pytest.mark.parametrize("ev,text", [
    ("hint_only", "accepted; conforms vacuously"),
    ("implementation_defined", "implementation-defined"),
    ("equivalent_default", "equivalent to the default (no separable effect)"),
    ("legality", "accepted (its oracle is the illegal variant)")])
def test_no_oracle_categories_read_as_their_category(tmp_path, ev, text):
    """A no-oracle (or legality) cell that ran reads as its
    category, never as correct on the device, and is not support; a
    rejection, a wrong answer and a crash keep their outcome."""
    atom = "omp.clause.map.close"
    rows = [mrow("p", atom, "afar", 1, evidence=ev),
            mrow("p", atom, "afar", 0, outcome="unobservable", evidence=ev),
            mrow("p", atom, "cce19", 1, outcome="rejected", evidence=ev,
                 reason="diagnostic: no"),
            mrow("p", atom, "cce19", 0, outcome="wrong_answer", evidence=ev,
                 reason="check_fail: ran_on_host=0 check=fail")]
    t = table(tmp_path, rows, {(52, atom): ev})
    assert by(t, toolchain="afar", xnack=1).label == text
    assert by(t, toolchain="afar", xnack=0).label == text
    assert ({**NO_ORACLE_TEXT, "legality": LEGALITY_TEXT}[ev]) == text
    assert by(t, toolchain="cce19", xnack=1).label == "rejected"
    assert by(t, toolchain="cce19", xnack=0).label.startswith("wrong answer")
    assert all("correct on device" not in family(r.label) for r in t)
    claim = dict(REVERSE_OFFLOAD, toolchain="afar", atom=atom,
                 claim="unsupported", form=None)
    claims = write_claims(tmp_path / "claims.yaml", [claim])
    # an unsupported claim is contradicted only by a credited pass
    assert compare_claims(t, claims) == []
    md = render_markdown(t, compare_claims(t, claims), claims=claims, meta={})
    assert "## Atoms without a separating oracle" in md


def test_unaudited_atom_is_marked_not_confirmed(tmp_path):
    rows = [mrow("p", "omp.clause.schedule", "afar", 1, outcome="wrong_answer",
                 reason="check_fail: ran_on_host=0 check=fail")]
    t = table(tmp_path, rows,
              {(52, "omp.clause.schedule"): "unaudited_no_passing_original"})
    assert "oracle unaudited" in t[0].label
    assert "confirmed" not in t[0].label


def test_audited_wrong_answer_is_confirmed(tmp_path):
    rows = [mrow("p", "omp.clause.dist_schedule", "afar", 1,
                 outcome="wrong_answer", reason="check_fail")]
    t = table(tmp_path, rows, {(52, "omp.clause.dist_schedule"): "valid"})
    assert t[0].label == "wrong answer (confirmed)"


def test_crash_in_one_mode_names_the_mode(tmp_path):
    rows = [mrow("p", "omp.clause.to.present", "afar", 1,
                 outcome="wrong_answer", evidence="unverified",
                 reason="crash: SIGABRT; without mandatory: crash: SIGABRT"),
            mrow("p", "omp.clause.to.present", "afar", 0,
                 outcome="unobservable", evidence="unverified")]
    t = table(tmp_path, rows)
    assert by(t, xnack=1).label == "crash: SIGABRT, HSA_XNACK=1 only"
    assert by(t, xnack=0).label == UNVERIFIED_TEXT


def test_zero_copy_program_in_copy_mode_is_not_a_wrong_answer(tmp_path):
    rows = [mrow("p", "omp.clause.unified_shared_memory", "cce19", 0,
                 outcome="wrong_answer", reason="exit_status: 255",
                 needs=("zero_copy",)),
            mrow("p", "omp.clause.unified_shared_memory", "cce19", 1,
                 outcome="unobservable")]
    t = table(tmp_path, rows)
    assert "needs zero-copy" in by(t, xnack=0).label
    assert "wrong answer" not in by(t, xnack=0).label


# --- claims --------------------------------------------------------------------------

def test_claim_mismatch_reported(tmp_path):
    claims = write_claims(tmp_path / "claims.yaml", [REVERSE_OFFLOAD])
    t = table(tmp_path, [mrow("p", "omp.clause.reverse_offload", "cce19", 1)])
    ms = compare_claims(t, claims)
    assert len(ms) == 1
    m = ms[0]
    assert type(m).__name__ == Mismatch.__name__   # the module may be loaded twice by other tests
    assert (m.atom, m.toolchain) == ("omp.clause.reverse_offload", "cce19")
    assert "unsupported" in m.claimed
    assert "correct on device" in m.measured


def test_claim_agreement_not_reported(tmp_path):
    claims = write_claims(tmp_path / "claims.yaml", [REVERSE_OFFLOAD])
    t = table(tmp_path, [
        mrow("p", "omp.clause.reverse_offload", "cce19", x, outcome="rejected",
             reason="not_implemented: ... deferred.") for x in (1, 0)]
        # another toolchain's success is not compared with a CCE claim
        + [mrow("p", "omp.clause.reverse_offload", "afar", 1)])
    assert compare_claims(t, claims) == []


def test_illegal_rows_are_not_compared(tmp_path):
    claims = write_claims(tmp_path / "claims.yaml", [REVERSE_OFFLOAD])
    t = table(tmp_path, [mrow("i", "omp.clause.reverse_offload", "cce19", 1,
                              legal=False, violates="OMP52-x-clause-001")])
    assert compare_claims(t, claims) == []


def test_supported_claim_against_unaudited_failure_is_flagged(tmp_path):
    claim = dict(REVERSE_OFFLOAD, atom="omp.clause.schedule",
                 claim="supported", form=None)
    claims = write_claims(tmp_path / "claims.yaml", [claim])
    t = table(tmp_path, [mrow("p", "omp.clause.schedule", "cce19", 1,
                              outcome="wrong_answer", reason="check_fail")],
              {(52, "omp.clause.schedule"): "unaudited_no_passing_original"})
    (m,) = compare_claims(t, claims)
    assert m.oracle_unaudited
    assert "oracle unaudited" in m.measured


def test_rejection_of_unaudited_atom_is_not_oracle_dependent(tmp_path):
    claim = dict(REVERSE_OFFLOAD, atom="omp.clause.allocate",
                 claim="supported", form=None)
    claims = write_claims(tmp_path / "claims.yaml", [claim])
    t = table(tmp_path, [mrow("p", "omp.clause.allocate", "cce19", 1,
                              outcome="rejected", reason="ice: x")],
              {(52, "omp.clause.allocate"): "unaudited_no_passing_original"})
    (m,) = compare_claims(t, claims)
    assert not m.oracle_unaudited
    assert (m.measured, m.reason) == ("rejected", "ice: x")


def test_specific_claim_overrides_general_claim(tmp_path):
    general = dict(REVERSE_OFFLOAD, atom=None,
                   atoms=["omp.clause.device", "omp.directive.target"],
                   claim="supported", form=None, general=True)
    specific = dict(REVERSE_OFFLOAD, atom="omp.clause.device",
                    claim="unsupported", form=None)
    claims = write_claims(tmp_path / "claims.yaml", [general, specific])
    t = table(tmp_path, [
        mrow("d", "omp.clause.device", "cce19", 1, outcome="accepted_ignored",
             reason="ignored: device clause"),
        mrow("t", "omp.directive.target", "cce19", 1, outcome="rejected")])
    ms = compare_claims(t, claims)
    assert [m.atom for m in ms] == ["omp.directive.target"]


def test_pattern_claim_and_modes_in_one_mismatch(tmp_path):
    claim = dict(REVERSE_OFFLOAD, atom=None, pattern="omp.clause.to.*",
                 claim="supported", form=None)
    claims = write_claims(tmp_path / "claims.yaml", [claim])
    t = table(tmp_path, [
        mrow("p", "omp.clause.to.present", "cce19", 1, outcome="wrong_answer",
             reason="crash: SIGABRT"),
        mrow("p", "omp.clause.to.present", "cce19", 0),
        mrow("q", "omp.clause.map.to", "cce19", 1, outcome="rejected")])
    (m,) = compare_claims(t, claims)
    assert m.atom == "omp.clause.to.present"
    assert m.measured == "crash: SIGABRT, HSA_XNACK=1 only"
    assert m.xnack == (1,)


# --- rendering -----------------------------------------------------------------------

def test_markdown_carries_citations_evidence_and_caveats(tmp_path):
    rows = [mrow("omp52-clause-map-to", "omp.clause.map.to", tc, x)
            for tc in ("afar", "cce19") for x in (1, 0)]
    rows += [mrow("omp52-illegal-teams-nesting-001", "omp.directive.teams",
                  tc, x, outcome="rejected", legal=False,
                  violates="OMP52-teams-nesting-001")
             for tc in ("afar", "cce19") for x in (1, 0)]
    t = table(tmp_path, rows, {(52, "omp.clause.map.to"): "valid"})
    claims = write_claims(tmp_path / "claims.yaml", [REVERSE_OFFLOAD])
    baseline = [{"repo": "omp_vv", "path": "tests/4.5/a.F90", "toolchain": tc,
                 "xnack": x, "status": "pass", "stage": "run", "reason": "",
                 "stdout": "[OMPVV_RESULT a.F90] Test passed on the host.\n"}
                for tc in ("afar", "cce19") for x in (1, 0)]
    md = render_markdown(t, compare_claims(t, claims), claims=claims,
                         baseline=baseline, meta={})
    assert "OpenMP 5.2" in md                      # clause citation
    assert "../catalog/omp/clauses.yaml" in md     # linked
    assert "../catalog/omp/rules.yaml" in md       # illegal row -> its rule
    assert "OMP52-teams-nesting-001" in md
    assert "different nodes" in md
    assert "provisional" in md
    assert "Test passed on the host" in md         # baseline footnote
    assert "| construct |" in md                   # evidence level column
    csv_text = render_csv(t)
    assert csv_text.splitlines()[0].startswith("version,program_id,atom")
    assert len(csv_text.splitlines()) == 1 + len(t)


# --- the committed claims file -------------------------------------------------------

def test_committed_claims_are_well_formed():
    """The support tables read the generic claims ingested from
    the vendor documents (catalog/vendor_claims_generic.yaml)."""
    from offload.engine.confirm.claims import products
    claims = load_claims(CLAIMS)
    assert claims
    # A claim may name an atom outside the device-offload scope
    # (a vendor statement about copyin); it is kept, but never measured
    known = set(slice_atoms(52, in_scope=False)) | set(
        slice_atoms(60, in_scope=False)) | set(slice_atoms(34, in_scope=False))
    for c in claims:
        assert c.source and c.url.startswith(("https://", "file://")), c
        assert c.toolchain in products(), c
        assert c.claim in ("supported", "unsupported", "partial"), c
        assert c.status == "provisional", c
        assert c.version_note, c
        assert c.quote, c
        assert c.atoms or c.pattern, c
        # Device.directive.<name> pseudo-atoms (documented device
        # limitations, read by the triage, never compared)
        # Onleaf.<leaf>.<clause> pseudo-atoms (a clause
        # documented as unsupported on a construct leaf), likewise
        assert not {a for a in c.atoms
                    if not a.startswith(("device.", "onleaf."))} \
            - known, (c, set(c.atoms) - known)


def test_committed_claims_cover_the_design_sources():
    sources = {c.source for c in load_claims(CLAIMS)}
    assert {"hpe-cce-intro-openmp", "rocm-openmp-support",
            "rocm-clang-openmp-status", "afar-flang-openmp-status"} <= sources
    reverse = [c for c in load_claims(CLAIMS)
               if c.toolchain == "cce19"
               and "omp.clause.reverse_offload" in c.atoms]
    assert reverse and reverse[0].claim == "unsupported"
    assert reverse[0].form == "compile_error"


# --- Generic claims, every release, both GPUs ---------------------------------

def _generic(tmp_path, **kw):
    from offload.engine.confirm.claims import VendorClaim, dump
    d = dict(vendor="HPE", product="CCE", version="19.0.0",
             source="hpe-cce-intro-openmp", url=HPE_URL,
             language="Fortran and C/C++", claim="supported",
             quote="CCE supports full OpenMP 5.0", toolchain="cce19",
             atom="omp.clause.map.to", page="intro_openmp(7): DESCRIPTION "
             "[CCE 19.0.0]")
    d.update(kw)
    p = tmp_path / "generic.yaml"
    dump([VendorClaim(**d)], p)
    return p


def test_generic_claims_load(tmp_path):
    (c,) = load_claims(_generic(tmp_path, versions="52,60", form="accepted",
                                claim="partial"))
    assert (c.toolchain, c.atoms, c.versions, c.form) == \
        ("cce19", ("omp.clause.map.to",), (52, 60), "accepted")
    assert c.version_note == "CCE 19.0.0"


def test_claim_covers_the_gfx90a_twin_in_one_mismatch(tmp_path):
    claims = _generic(tmp_path)
    t = table(tmp_path, [
        mrow("p", "omp.clause.map.to", "cce19", 1, outcome="rejected",
             reason="ice: x"),
        mrow("p", "omp.clause.map.to", "cce19_g90", 0, outcome="rejected",
             reason="ice: x")])
    (m,) = compare_claims(t, claims)
    assert m.toolchain == "cce19"
    assert sorted(c[1] for c in m.cells) == ["cce19", "cce19_g90"]


def test_language_of_a_generic_claim(tmp_path):
    t = table(tmp_path, [mrow("p", "omp.clause.map.to", "afar", 1,
                              outcome="rejected", reason="ice: x")])
    only_c = _generic(tmp_path, language="C/C++", toolchain="afar",
                      vendor="AMD")
    assert compare_claims(t, only_c) == []
    cross = _generic(tmp_path, language="C/C++", toolchain="afar",
                     vendor="AMD", cross_language=True)
    (m,) = compare_claims(t, cross)
    assert m.lang == "f90"


# --- review ----------------------------------------------------------------------

def test_dagger_marks_outcome_differences_only(tmp_path):
    rows = [  # copy_mode_only: labels differ by design, outcomes do not
        mrow("c", "omp.clause.defaultmap.aggregate", tc, x,
             evidence="copy_mode_only") for tc in ("afar", "cce19")
        for x in (1, 0)]
    rows += [mrow("p", "omp.clause.to.present", "afar", 1,
                  outcome="wrong_answer", reason="crash: SIGABRT"),
             mrow("p", "omp.clause.to.present", "afar", 0,
                  outcome="wrong_answer", reason="check_fail")]
    t = table(tmp_path, rows)
    md = render_markdown(t, [], meta={})
    agg = next(ln for ln in md.splitlines()
               if ln.startswith("| `clause.defaultmap.aggregate`"))
    assert "†" not in agg
    pres = next(ln for ln in md.splitlines()
                if ln.startswith("| `clause.to.present`"))
    assert pres.count("†") == 2   # crash in one mode, check failure in other


def test_summary_order_is_deterministic(tmp_path):
    rows = [mrow("a", "omp.clause.map.to", "afar", 1, outcome="rejected"),
            mrow("b", "omp.clause.map.from", "afar", 1,
                 outcome="fell_back_to_host", reason="ran_on_host=1")]
    md = render_markdown(table(tmp_path, rows), [], meta={})
    i_f = md.index("| fell back to host |")
    i_r = md.index("| rejected |")
    assert i_f < i_r    # equal totals: alphabetical


def test_crash_counts_in_wording_and_clang_rows_are_tagged(tmp_path):
    claim = dict(REVERSE_OFFLOAD, source="rocm-clang-openmp-status",
                 toolchain="afar", atom="omp.clause.to.present",
                 claim="supported", form=None, language="C/C++")
    claims = write_claims(tmp_path / "claims.yaml", [claim])
    t = table(tmp_path, [
        mrow("p", "omp.clause.to.present", "afar", 1, outcome="wrong_answer",
             evidence="unverified", reason="crash: SIGABRT"),
        mrow("p", "omp.clause.to.present", "afar", 0, outcome="unobservable",
             evidence="unverified")])
    ms = compare_claims(t, claims)
    md = render_markdown(t, ms, claims=claims, meta={})
    assert "a compile result, a crash, or an audited oracle" in md
    assert "(C/C++ table)" in md


def test_confounded_atoms_carry_a_caveat(tmp_path):
    claim = dict(REVERSE_OFFLOAD, toolchain="afar", atom=None,
                 atoms=["omp.clause.linear.ref", "omp.clause.allocate"],
                 claim="supported", form=None)
    claims = write_claims(tmp_path / "claims.yaml", [claim])
    t = table(tmp_path, [
        mrow("l", "omp.clause.linear.ref", "afar", 1, outcome="rejected",
             reason="not yet implemented: omp.declare_simd"),
        mrow("a", "omp.clause.allocate", "afar", 1, outcome="rejected",
             reason="USES_ALLOCATORS clause is not implemented yet")])
    ms = compare_claims(t, claims)
    assert ms == []   # a listed confound is not counted (final-fix review R1)
    md = render_markdown(t, ms, claims=claims, meta={})
    assert "declare simd" in md and "uses_allocators" in md
    assert all("not counted" in r.label for r in t)


def test_stale_audit_note_names_atoms_a_toolchain_passes(tmp_path):
    rows = [mrow("s", "omp.clause.severity", "afar", 1, version=60),
            mrow("s", "omp.clause.severity", "cce19", 1, version=60,
                 outcome="rejected")]
    t = table(tmp_path, rows,
              {(60, "omp.clause.severity"): "unaudited_no_passing_original"})
    md = render_markdown(t, [], meta={})
    note = next(ln for ln in md.splitlines() if "-fopenmp-version=60" in ln
                and "predate" in ln)
    assert "`clause.severity` (6.0)" in note


# --- toolchain and uses_allocators sources --------------------------------------------------------------------

SRC = """program p
  !$omp target uses_allocators(omp_default_mem_alloc) map(to: a) &
  !$omp& map(from: b)
  !$omp parallel do private(t) allocate(omp_default_mem_alloc: t)
  do i = 1, n
  end do
end program p
"""


def test_rejection_at_a_line_without_the_atom_is_not_counted(tmp_path):
    rows = [mrow("p", "omp.clause.allocate", "afar", 1, outcome="rejected",
                 reason='not_implemented: error: loc("<tmpdir>/p.f90":2:10): '
                        "not yet implemented: X"),
            mrow("p", "omp.clause.allocate", "cce19", 1, outcome="rejected",
                 reason="diagnostic: ftn-1510 ftn: ERROR P, File = p.f90, "
                        "Line = 4, Column = 9 | bad allocate")]
    m = write_matrix(tmp_path / "m.jsonl", rows)
    t = build_table(m, audit=None, source_of=lambda pid, atom, v: SRC)
    afar = by(t, toolchain="afar")
    cce = by(t, toolchain="cce19")
    assert "line 2" in afar.label and "does not carry the atom" in afar.label
    assert afar.confound
    assert cce.label == "rejected" and not cce.confound   # line 4 has it
    claim = dict(REVERSE_OFFLOAD, toolchain="afar", atom="omp.clause.allocate",
                 claim="supported", form=None)
    claims = write_claims(tmp_path / "claims.yaml", [claim])
    assert compare_claims(t, claims) == []


def test_continuation_lines_belong_to_the_diagnosed_directive(tmp_path):
    rows = [mrow("p", "omp.clause.map.from", "afar", 1, outcome="rejected",
                 reason="diagnostic: <tmpdir>/p.f90:2:5: error: x")]
    t = build_table(write_matrix(tmp_path / "m.jsonl", rows), audit=None,
                    source_of=lambda pid, atom, v: SRC)
    assert t[0].label == "rejected" and not t[0].confound


def test_listed_confound_applies_only_when_its_message_matches(tmp_path):
    msg = ('diagnostic: ftn-1725 ftn: ERROR F, File = p.f90, Line = 16 | '
           'Unexpected syntax while parsing the DIRECTIVE statement : '
           '"INDIRECT, LINK, TO or DEVICE_TYPE" was expected but found "E".')
    rows = [mrow("p", "omp.clause.device_type", "cce19", 1,
                 outcome="rejected", reason=msg, version=60),
            mrow("q", "omp.clause.device_type", "cce19", 1, version=52)]
    t = table(tmp_path, rows)
    assert "enter" in by(t, version=60).confound
    assert by(t, version=52).confound == ""


def test_cce_module_summary_reason_is_replaced_by_the_root(tmp_path):
    stderr = where.message("cce_module_summary").read_text()
    r = mrow("p", "omp.clause.device_type", "cce19", 1, outcome="rejected",
             version=60, reason="diagnostic: ftn-855 ftn: ERROR GEN_MOD, "
             "File = x.f90, Line = 10 | The compiler has detected errors in "
             'module "GEN_MOD".')
    r["stderr"] = stderr
    t = table(tmp_path, [r])
    assert "ftn-1725" in t[0].reason and "ftn-855" not in t[0].reason


def test_provenance_names_rerun_rows(tmp_path):
    t = table(tmp_path, [mrow("p", "omp.directive.target", "afar", 1)])
    meta = {1: {"host": "n1", "thp_seen": "always", "started": "s1",
                "reruns": [{"host": "n9", "thp_seen": "always",
                            "started": "s9", "programs": ["p"],
                            "why": "generator fix"}]},
            0: {"host": "n0", "thp_seen": "never", "started": "s0"}}
    md = render_markdown(t, [], meta=meta)
    assert "n9" in md and "generator fix" in md


# --- final-fix review --------------------------------------------------------------------

DM_AFAR = ("diagnostic: <tmpdir>/omp52-clause-defaultmap-none.f90:31:8: error: "
           "The DEFAULTMAP(NONE) clause requires that 'i' must be listed in a "
           "data-sharing attribute, data-mapping attribute, or is_device_ptr "
           "clause")
DM_CCE = ('diagnostic: ftn-1964 ftn: ERROR GEN_PROG, File = '
          '../../omp52-clause-defaultmap-none.f90, Line = 32, Column = 7 | '
          'Variable "B" must have its data mapping attribute explicitly '
          'declared because default map(none) was specified.')


def test_defaultmap_none_real_messages_are_counted_with_a_caveat(tmp_path):
    """The real messages point at statements that use a variable
    (lines 31 and 32 of the generated program), not at the clause: the
    rejection is the atom's own check, so it is counted, with a caveat."""
    rows = [mrow("omp52-clause-defaultmap-none", "omp.clause.defaultmap.none",
                 tc, x, outcome="rejected", reason=msg)
            for tc, msg in (("afar", DM_AFAR), ("cce19", DM_CCE))
            for x in (1, 0)]
    t = build_table(write_matrix(tmp_path / "m.jsonl", rows), audit=None)
    for r in t:
        assert r.label == "rejected ‡", r.label
        assert ("the compiler points at a statement that uses a variable, "
                "not at the clause") in r.confound
    claims = write_claims(tmp_path / "claims.yaml", [
        dict(REVERSE_OFFLOAD, toolchain=tc, atom="omp.clause.defaultmap.none",
             claim="supported", form=None) for tc in ("afar", "cce19")])
    ms = compare_claims(t, claims)
    assert sorted(m.toolchain for m in ms) == ["afar", "cce19"]
    assert all(m.confound for m in ms)


SRC_TR = """program p
  use omp_lib, only: omp_impex
  !$omp taskgroup task_reduction(iand: s)
  !$omp target in_reduction(iand: s)
  !$omp end target
  !$omp end taskgroup
end program p
"""


@pytest.mark.parametrize("atom,tc,reason,words", [
    ("omp.clause.in_reduction.iand", "afar",
     "diagnostic: <tmpdir>/p.f90:3:34: error: Internal: no symbol found for "
     "'iand'", "task_reduction"),
    ("omp.clause.in_reduction.minus", "afar",
     "diagnostic: <tmpdir>/p.f90:3:19: error: The minus reduction operator "
     "is deprecated since OpenMP 5.2 and is not supported in the REDUCTION "
     "clause.", "task_reduction"),
    ("omp.clause.transparent.impex_type", "cce19",
     'diagnostic: ftn-732 ftn: ERROR P, File = p.f90, Line = 2, Column = 46 '
     '| "OMP_IMPEX" is not in module "OMP_LIB".', "omp_impex"),
    ("omp.clause.transparent.directive_name", "afar",
     "diagnostic: <tmpdir>/p.f90:2:46: error: 'omp_impex' not found in "
     "module 'omp_lib'", "omp_impex"),
    ("omp.clause.device_type.nohost", "cce19",
     "link_undefined_symbol: The Cpu Module:(.text+0x873): undefined "
     "reference to `f$gen_mod_'", "host build"),
])
def test_counted_caveats(tmp_path, atom, tc, reason, words):
    rows = [mrow("p", atom, tc, 1, outcome="rejected", reason=reason)]
    t = build_table(write_matrix(tmp_path / "m.jsonl", rows), audit=None,
                    source_of=lambda pid, a, v: SRC_TR)
    assert t[0].label == "rejected ‡" and words in t[0].confound
    claims = write_claims(tmp_path / "claims.yaml", [dict(
        REVERSE_OFFLOAD, toolchain=tc, atom=atom, claim="supported",
        form=None)])
    assert len(compare_claims(t, claims)) == 1


def test_rerun_provenance_names_the_final_rows_and_notes(tmp_path):
    t = table(tmp_path, [mrow("p", "omp.directive.target", "afar", 1)])
    meta = {1: {"host": "n1", "reruns": [
        {"host": "nA", "started": "s1", "programs": ["p", "q"], "why": "w1",
         "note": "edited by hand"},
        {"host": "nB", "started": "s2", "programs": ["p"], "why": "w2"}]}}
    md = render_markdown(t, [], meta=meta)
    assert "edited by hand" in md
    line = next(ln for ln in md.splitlines() if "come from the last" in ln)
    assert "`p`: nB" in line


def test_negative_probe_labels(tmp_path):
    # Present modifiers are negative probes (evidence probe): the
    # required error termination reads as such, a run that went on as a
    # missing error termination
    rows = [mrow("p", "omp.clause.map.present", "afar", 0,
                 reason="error_termination: device mapping required by "
                 "'present' map type modifier does not exist",
                 evidence="probe"),
            mrow("p", "omp.clause.map.present", "afar", 1,
                 outcome="wrong_answer",
                 reason="no_error_termination: ran_on_host=0 check=fail",
                 evidence="probe")]
    t = table(tmp_path, rows, {(52, "omp.clause.map.present"): "valid"})
    assert by(t, xnack=0).label == ("error termination as required "
                                    "(negative probe)")
    assert by(t, xnack=1).label == ("no error termination (negative probe, "
                                    "confirmed)")



def test_compile_probe_labels(tmp_path):
    rows = [mrow("p", "omp.clause.severity.fatal", "afar", 0, version=60,
                 reason="compile_error_termination: x.f90:3:7: error: T",
                 evidence="probe"),
            mrow("q", "omp.clause.message", "afar", 0, version=60,
                 reason="ran_on_host=0 check=pass; compile message: warning: T",
                 evidence="probe")]
    t = table(tmp_path, rows, {(60, "omp.clause.severity.fatal"): "valid",
                               (60, "omp.clause.message"): "valid"})
    assert by(t, atom="omp.clause.severity.fatal").label == \
        "compile-time error termination as required (probe)"
    assert by(t, atom="omp.clause.message").label == \
        "correct on device; compile-time message as required (probe)"


def test_semantic_atom_cites_the_spec_definitions():
    from offload.engine.report import atom_citation
    c52, link = atom_citation("omp.clause.defaultmap.character", 52)
    assert "OpenMP 5.2 §1.2.6, p.14" in c52 and "§5.8.1, p.148" in c52
    assert link.endswith("semantic_atoms.yaml")
    c60, _ = atom_citation("omp.clause.defaultmap.character", 60)
    assert c60.startswith("OpenMP 6.0") and "§7.9.3, p.277" in c60
    # the syntax atoms of the clause keep the clause's citation
    assert atom_citation("omp.clause.defaultmap.to", 52)[0] == \
        "OpenMP 5.2 §5.8.7, p.161"


# --- Headline mode, copy-mode column, omp_vv second source ------------------

def _atom_line(md, atom):
    return next(ln for ln in md.splitlines()
                if ln.startswith(f"| `{atom.removeprefix('omp.')}`"))


def test_copy_column_reads_not_run_for_headline_only_programs(tmp_path):
    rows = [mrow("p", "omp.clause.map.to", tc, 1) for tc in ("afar", "cce19")]
    t = table(tmp_path, rows)
    line = _atom_line(render_markdown(t, [], meta={}), "omp.clause.map.to")
    assert line.count("not run") == 2 and "†" not in line
    assert all(r.copy_label == "not run" for r in t)


def test_copy_mode_only_headline_is_never_a_plain_pass(tmp_path):
    a = "omp.clause.defaultmap.aggregate"
    rows = [mrow("c", a, "afar", x, evidence="copy_mode_only")
            for x in (1, 0)]
    rows += [mrow("d", "omp.clause.defaultmap.alloc", "afar", 1,
                  evidence="copy_mode_only")]
    t = table(tmp_path, rows)
    with_copy = by(t, program_id="c", xnack=1)
    assert with_copy.label.startswith("correct on device (copy-mode")
    assert with_copy.copy_label == "correct on device"
    md = render_markdown(t, [], meta={})
    assert "◊" in _atom_line(md, a).split("|")[4]
    alone = by(t, program_id="d")
    assert alone.label.endswith("copy-mode check not run")
    assert "not run" in _atom_line(md, "omp.clause.defaultmap.alloc")
    csv_rows = list(__import__("csv").DictReader(
        __import__("io").StringIO(render_csv(t))))
    head = [r for r in csv_rows if r["program_id"] == "c"
            and r["mode"] == "headline"]
    assert head[0]["copy_label"] == "correct on device"


def test_dagger_only_when_the_modes_ran_on_different_nodes(tmp_path):
    rows = [mrow("p", "omp.clause.to.present", "afar", 1,
                 outcome="wrong_answer", reason="check_fail"),
            mrow("p", "omp.clause.to.present", "afar", 0)]
    t = table(tmp_path, rows)
    same = {1: {"host": "n1", "reruns": [{"host": "n5", "programs": ["p"]}]},
            0: {"host": "n5"}}
    diff = {1: {"host": "n1"}, 0: {"host": "n5"}}
    a = "omp.clause.to.present"
    assert "†" not in _atom_line(render_markdown(t, [], meta=same), a)
    assert _atom_line(render_markdown(t, [], meta=diff), a).count("†") == 2
    md = render_markdown(t, [], meta=same)
    assert "1 have both rows from one node, 0 from different nodes" in md


def test_suite_second_source_column(tmp_path):
    rows = [mrow("p", "omp.clause.map.to", tc, 1) for tc in ("afar", "cce19")]
    t = table(tmp_path, rows)
    suite = {("omp.clause.map.to", "afar"): [3, 1]}
    md = render_markdown(t, [], meta={}, suite=suite)
    cells = [c.strip() for c in _atom_line(md, "omp.clause.map.to")
             .split("|")]
    assert "3 pass / 1 fail" in cells
    i = cells.index("3 pass / 1 fail")
    assert cells[i + 1] == ""          # CCE: no narrow test -> blank
    csv_text = render_csv(t, suite=suite)
    assert "3 pass / 1 fail" in csv_text


def test_full_two_mode_matrix_still_renders(tmp_path):
    rows = [mrow("p", "omp.clause.map.to", tc, x)
            for tc in ("afar", "cce19") for x in (1, 0)]
    t = table(tmp_path, rows)
    md = render_markdown(t, [], meta={1: {"host": "a"}, 0: {"host": "b"}})
    assert "every program (a full two-mode matrix)" in md
    assert "not run" not in _atom_line(md, "omp.clause.map.to")


def test_copy_mark_is_not_put_on_a_rejection(tmp_path):
    a = "omp.clause.map.iterator"
    rows = [mrow("i", a, "afar", x, outcome="rejected", reason="not_impl",
                 evidence="copy_mode_only") for x in (1, 0)]
    rows += [mrow("j", "omp.clause.to.iterator", "afar", 1,
                  outcome="rejected", reason="x", evidence="copy_mode_only")]
    t = table(tmp_path, rows)
    md = render_markdown(t, [], meta={})
    assert "◊" not in _atom_line(md, a)
    assert by(t, program_id="j").label == "rejected"


# --- Semantic atoms ---------------------------------------------

SRC_CHAR = """program p
  character(len=4) :: c
  c = 'abcd'
  !$omp target map(from: b)
  c(1:1) = 'x'
  !$omp end target
end program p
"""


def test_semantic_atom_rejection_at_a_directive_is_its_own(tmp_path):
    """omp.clause.defaultmap.character has no clause in its program (a
    semantic atom): a rejection diagnosed at a directive line is the
    atom's own failure, not a confound."""
    rows = [mrow("p", "omp.clause.defaultmap.character", "afar", 1,
                 outcome="rejected",
                 reason="diagnostic: <tmpdir>/p.f90:4:9: error: character "
                        "item in a target region")]
    t = build_table(write_matrix(tmp_path / "m.jsonl", rows), audit=None,
                    source_of=lambda pid, a, v: SRC_CHAR)
    assert t[0].label == "rejected" and not t[0].confound
    assert not t[0].excluded
    claims = write_claims(tmp_path / "claims.yaml", [dict(
        REVERSE_OFFLOAD, toolchain="afar",
        atom="omp.clause.defaultmap.character", claim="supported",
        form=None)])
    assert [m.toolchain for m in compare_claims(t, claims)] == ["afar"]


def test_clause_atom_rejection_at_another_directive_stays_a_confound(
        tmp_path):
    rows = [mrow("p", "omp.clause.defaultmap.none", "afar", 1,
                 outcome="rejected",
                 reason="diagnostic: <tmpdir>/p.f90:4:9: error: x")]
    t = build_table(write_matrix(tmp_path / "m.jsonl", rows), audit=None,
                    source_of=lambda pid, a, v: SRC_CHAR)
    assert "does not carry the atom" in t[0].confound


def test_reruns_into_the_merged_matrix_reach_the_provenance(tmp_path):
    """`run_matrix.py rerun --out results/matrix.jsonl` records
    its rerun in the merged matrix's meta file; read_meta adds it to its
    mode's reruns (once, by start time), so the table names those rows."""
    from offload.engine.report import read_meta
    res = write_matrix(tmp_path / "matrix.jsonl",
                       [mrow("p", "omp.directive.target", "afar", 1)])
    one = {"host": "n1", "started": "2026-01-01T00:00:00", "programs": ["q"],
           "xnack": 1, "why": "in both files"}
    (tmp_path / "matrix.xnack1.jsonl.meta.json").write_text(json.dumps(
        {"host": "n0", "started": "s0", "reruns": [one]}))
    two = {"host": "n9", "started": "2026-02-01T00:00:00", "programs": ["p"],
           "xnack": 1, "why": "merged only"}
    (tmp_path / "matrix.jsonl.meta.json").write_text(json.dumps(
        {"reruns": [one, two]}))
    meta = read_meta(res)
    assert [r["why"] for r in meta[1]["reruns"]] == ["in both files",
                                                     "merged only"]
    md = render_markdown(build_table(res, audit=None), [], meta=meta)
    assert "n9" in md and "merged only" in md


# --- Portable verdict (correct in both memory modes) ------------------------

def test_portable_verdict_per_headline_row(tmp_path):
    from offload.engine.report import portable_of
    a = "omp.clause.map.to"
    rows = [mrow("p", a, "afar", 1), mrow("p", a, "afar", 0),
            mrow("p", a, "cce19", 1),
            mrow("p", a, "cce19", 0, outcome="wrong_answer",
                 reason="check_fail"),
            mrow("p", a, "cce20", 1, outcome="wrong_answer",
                 reason="check_fail"),
            mrow("p", a, "cce20", 0),
            mrow("p", a, "cce21", 1)]
    t = table(tmp_path, rows)
    assert by(t, toolchain="afar", xnack=1).portable == "portable"
    assert by(t, toolchain="cce19", xnack=1).portable == "x1_only"
    assert by(t, toolchain="cce20", xnack=1).portable == "x0_only"
    assert by(t, toolchain="cce21", xnack=1).portable == "x0_not_run"
    assert by(t, toolchain="afar", xnack=0).portable == ""  # copy rows
    assert portable_of("correct on device", "rejected") == "x1_only"
    assert portable_of("rejected", "rejected") == "neither"
    csv_rows = list(__import__("csv").DictReader(
        __import__("io").StringIO(render_csv(t))))
    assert csv_rows[0].keys() >= {"portable"}
    head = {r["toolchain"]: r["portable"] for r in csv_rows
            if r["mode"] == "headline"}
    assert head == {"afar": "portable", "cce19": "x1_only",
                    "cce20": "x0_only", "cce21": "x0_not_run"}


def test_zero_copy_program_is_not_portable_by_design(tmp_path):
    a = "omp.clause.map.to"
    rows = [mrow("p", a, "afar", 1, needs=("zero_copy",)),
            mrow("p", a, "afar", 0, outcome="wrong_answer",
                 reason="check_fail", needs=("zero_copy",))]
    t = table(tmp_path, rows)
    assert by(t, xnack=1).portable == "needs_zero_copy"


def test_markdown_portable_column_and_summary(tmp_path):
    a = "omp.clause.map.to"
    rows = [mrow("p", a, "afar", 1), mrow("p", a, "afar", 0),
            mrow("p", a, "cce19", 1),
            mrow("p", a, "cce19", 0, outcome="wrong_answer",
                 reason="check_fail")]
    t = table(tmp_path, rows)
    md = render_markdown(t, [], meta={})
    line = _atom_line(md, a)
    assert "AFAR" in line.split("|")[-3] and "X1 only: CCE 19" in line
    assert "## Portable verdict (correct at HSA_XNACK=0 and 1)" in md
    head = next(ln for ln in md.splitlines()
                if ln.startswith("| atom | evidence | audit |"))
    sep = md.splitlines()[md.splitlines().index(head) + 1]
    # one separator cell per header cell (the dashboard crash)
    assert head.count("|") == sep.count("|")


def test_mode_differences_are_classified(tmp_path, monkeypatch):
    from offload.engine import report
    monkeypatch.setattr(report, "MODE_DIFFERENCES", {"entries": [
        {"programs": ["p*"], "toolchains": ["cce19"],
         "class": "copy_mode_failure", "why": "w",
         "finding": "target-update-sections-in-parallel.f90"}]})
    a = "omp.clause.map.to"
    rows = [mrow("p1", a, "cce19", 1),
            mrow("p1", a, "cce19", 0, outcome="wrong_answer",
                 reason="check_fail"),
            mrow("p1", a, "afar", 1),
            mrow("p1", a, "afar", 0, outcome="wrong_answer",
                 reason="check_fail"),
            mrow("p1", a, "cce20", 1), mrow("p1", a, "cce20", 0)]
    t = table(tmp_path, rows)
    assert by(t, toolchain="cce19", xnack=1).mode_class == \
        "copy_mode_failure"
    assert by(t, toolchain="afar", xnack=1).mode_class == "unclassified"
    assert by(t, toolchain="cce20", xnack=1).mode_class == ""
    md = render_markdown(t, [], meta={})
    assert "## Memory-mode differences" in md
    assert "X1 only: AFAR (unclassified), CCE 19 (copy_mode_failure)" \
        in _atom_line(md, a)
    assert "target-update-sections-in-parallel.f90" in md
    csv_rows = list(__import__("csv").DictReader(
        __import__("io").StringIO(render_csv(t))))
    assert {r["mode_class"] for r in csv_rows} >= {"copy_mode_failure"}


def test_committed_mode_differences_are_well_formed():
    from offload.engine.report import MODE_CLASSES, load_mode_differences
    doc = load_mode_differences()
    assert doc["entries"]
    for e in doc["entries"]:
        assert e["class"] in MODE_CLASSES, e
        assert e["programs"] and e["toolchains"] and e["why"].strip()
        if e["class"] in ("copy_mode_failure", "x1_oracle_blind"):
            assert e.get("finding"), e
        if e.get("finding"):
            assert (Path(__file__).resolve().parent.parent.parent / "data" / "findings" / e["finding"]).is_file(), e


def test_ompvv_mode_differences_are_flagged():
    from offload.engine.report import _baseline_mode_flags

    def b(path, tc, x, status, stage="run", reason="exit 0"):
        return {"path": path, "toolchain": tc, "xnack": x, "status": status,
                "stage": stage, "reason": reason, "repo": "omp_vv"}
    base = [b("tests/5.0/t.F90", "afar", 1, "pass"),
            b("tests/5.0/t.F90", "afar", 0, "fail", reason="exit 1"),
            b("tests/5.0/u.F90", "afar", 1, "pass"),
            b("tests/5.0/u.F90", "afar", 0, "pass")]
    lines = "\n".join(_baseline_mode_flags(base))
    assert "t.F90" in lines and "u.F90" not in lines
    assert "untrusted" in lines
    assert "| AFAR | 1 | 0 |" in lines  # x1-only passes, x0-only passes


def test_merged_baseline_meta_reruns_reach_the_modes(tmp_path):
    from offload.engine.report import read_meta
    m = tmp_path / "matrix.jsonl"
    m.write_text("")
    (tmp_path / "baseline.jsonl.meta.json").write_text(json.dumps(
        {"reruns": [{"xnack": 0, "host": "n9", "started": "s",
                     "baseline_paths": ["a"]}]}))
    meta = read_meta(m)
    assert meta["baseline0"]["reruns"][0]["host"] == "n9"



@pytest.mark.parametrize("x1,x0,want", [
    ("correct on device", "correct on device", "portable"),
    ("compiled and ran; nothing checked (unobservable)",
     "compiled and ran; nothing checked (unobservable)", "not_verifiable"),
    ("accepted, ignored (warning)", "accepted, ignored (warning)",
     "not_verifiable"),
    (NO_ORACLE_TEXT["hint_only"], NO_ORACLE_TEXT["hint_only"],
     "not_verifiable"),
    (UNVERIFIED_TEXT, UNVERIFIED_TEXT, "not_verifiable"),
    ("harness error", "harness error", "not_verifiable"),
    ("rejected", "rejected", "neither"),
    ("wrong answer (confirmed)", "compiled and ran; nothing checked "
     "(unobservable)", "x1_fail_x0_unverified"),
    ("crash: SIGSEGV, HSA_XNACK=1 only", "wrong answer (confirmed)",
     "neither"),
    ("rejected (not counted: x)", "rejected (not counted: x)",
     "not_verifiable"),
    # a copy_mode_only cell's HSA_XNACK=1 check is skipped: no evidence
    ("correct on device (copy-mode evidence; not separable at "
     "HSA_XNACK=1)", "wrong answer (confirmed)", "x0_fail_x1_unverified"),
    ("correct on device (copy-mode evidence; not separable at "
     "HSA_XNACK=1)", "correct on device", "portable"),
])
def test_portable_neither_needs_an_observed_failure(x1, x0, want):
    from offload.engine.report import portable_of
    assert portable_of(x1, x0) == want


def test_not_verifiable_is_a_portable_verdict():
    from offload.engine.report import PORTABLE
    assert "not_verifiable" in PORTABLE
    assert "both modes" in PORTABLE["neither"]


def test_x1_oracle_blind_is_a_mode_class():
    from offload.engine.report import MODE_CLASSES
    assert "x1_oracle_blind" in MODE_CLASSES


def _committed_tables():
    root = Path(__file__).resolve().parent.parent.parent
    return [p for p in (root / "data" / "reports" / "c_support_table.csv",
                        root / "data" / "reports" / "acc_support_table.csv",
                        root / "results" / "support_table.csv")
            if p.is_file()]


def test_no_unclassified_mode_difference_in_the_tables():
    """(review Minor 1): every memory-mode difference
    of a committed (or present) support table has a class."""
    import csv
    for p in _committed_tables():
        bad = [(r["program_id"], r["toolchain"])
               for r in csv.DictReader(p.open())
               if r.get("mode_class") == "unclassified"]
        assert not bad, f"{p.name}: unclassified {bad}"


def test_write_report_refuses_unclassified(tmp_path, monkeypatch):
    from offload.engine import report
    monkeypatch.setattr(report, "MODE_DIFFERENCES", {"entries": []})
    a = "omp.clause.map.to"
    m = write_matrix(tmp_path / "matrix.jsonl", [
        mrow("p1", a, "afar", 1),
        mrow("p1", a, "afar", 0, outcome="wrong_answer",
             reason="check_fail")])
    au = write_audit(tmp_path / "audit.json", {})
    cl = write_claims(tmp_path / "claims.yaml", [])
    with pytest.raises(ValueError, match="unclassified"):
        report.write_report(m, cl, au, tmp_path / "none.jsonl",
                            tmp_path / "o.md", tmp_path / "o.csv")


def test_hidden_x1_presence_failure_is_not_portable(tmp_path, monkeypatch):
    """A copy_mode_only program whose presence check, run at
    HSA_XNACK=1 (tools/campaigns/presence_x1.py), fails is not portable even if its
    copy-mode cell is correct: the HSA_XNACK=1 'correct' was no evidence."""
    from offload.engine import report
    monkeypatch.setattr(report, "PRESENCE_X1", {
        "p": {"afar": "wrong_answer", "cce19": "correct_on_device"}})
    a = "omp.clause.map.alloc"
    rows = [mrow("p", a, tc, x, evidence="copy_mode_only")
            for tc in ("afar", "cce19") for x in (1, 0)]
    t = table(tmp_path, rows)
    assert by(t, toolchain="afar", xnack=1).portable == "x0_only"
    assert by(t, toolchain="afar", xnack=1).presence_x1 == "wrong_answer"
    assert by(t, toolchain="cce19", xnack=1).portable == "portable"
    md = render_markdown(t, [], meta={})
    assert "## Presence checks at HSA_XNACK=1" in md
    csv_rows = list(__import__("csv").DictReader(
        __import__("io").StringIO(render_csv(t))))
    assert {r["presence_x1"] for r in csv_rows} >= {"wrong_answer"}



def test_copy_mode_only_rule_keys_on_evidence_not_label(tmp_path, monkeypatch):
    """An unaudited copy_mode_only program's X1 label is "correct on
    device (oracle unaudited)"; its X1 cell is still no evidence next to a
    copy-mode failure, and a failing presence check at X1 still counts."""
    from offload.engine import report
    monkeypatch.setattr(report, "PRESENCE_X1", {"p": {"afar": "wrong_answer"}})
    a = "omp.clause.map.iterator"
    rows = [mrow("p", a, "afar", 1, evidence="copy_mode_only"),
            mrow("p", a, "afar", 0, outcome="wrong_answer",
                 reason="check_fail", evidence="copy_mode_only"),
            mrow("q", "omp.clause.to.iterator", "afar", 1,
                 evidence="copy_mode_only"),
            mrow("q", "omp.clause.to.iterator", "afar", 0,
                 outcome="wrong_answer", reason="check_fail",
                 evidence="copy_mode_only")]
    t = table(tmp_path, rows, audit={
        (52, a): "unaudited_no_passing_original",
        (52, "omp.clause.to.iterator"): "unaudited_no_passing_original"})
    p = by(t, program_id="p", xnack=1)
    assert p.label.startswith("correct on device (oracle unaudited)")
    assert p.portable == "neither"          # X1 presence failure + X0 failure
    q = by(t, program_id="q", xnack=1)
    assert q.portable == "x0_fail_x1_unverified"
    md = render_markdown(t, [], meta={})
    assert "p (AFAR)" in md.split("## Presence checks at HSA_XNACK=1")[1]


@pytest.mark.parametrize("x1,x0,kw,want", [
    ("rejected", "wrong answer (confirmed)", {}, "neither"),
    ("compiled and ran; nothing checked (unobservable)",
     "wrong answer (confirmed)", {}, "x0_fail_x1_unverified"),
    ("correct on device (copy-mode evidence; not separable at "
     "HSA_XNACK=1)", "wrong answer (confirmed)", {"x1_copy_only": True},
     "x0_fail_x1_unverified"),
    ("compiled and ran; nothing checked (unobservable)",
     "compiled and ran; nothing checked (unobservable)",
     {"x1_hidden_failure": True}, "x1_fail_x0_unverified"),
    ("compile-time error termination as required (probe)",
     "compile-time error termination as required (probe)", {}, "portable"),
])
def test_portable_round2_verdicts(x1, x0, kw, want):
    from offload.engine.report import portable_of
    assert portable_of(x1, x0, **kw) == want


def test_requirement_refused_has_its_own_verdict(tmp_path, monkeypatch):
    from offload.engine import report
    monkeypatch.setattr(report, "MODE_DIFFERENCES", {"entries": [
        {"programs": ["u"], "toolchains": ["afar"],
         "class": "requirement_refused", "why": "w"}]})
    a = "omp.clause.unified_address"
    rows = [mrow("u", a, "afar", 1, outcome="unobservable", reason="r"),
            mrow("u", a, "afar", 0, outcome="wrong_answer",
                 reason="crash: SIGABRT")]
    t = table(tmp_path, rows)
    assert by(t, xnack=1).portable == "requirement_refused"
    assert {"requirement_refused", "x0_fail_x1_unverified",
            "x1_fail_x0_unverified"} <= set(report.PORTABLE)


# --- The gfx90a (Tioga MI250X) column -------------------------------------

def _g90_rows(a="omp.clause.map.to"):
    bad = dict(outcome="wrong_answer", reason="check_fail: x")
    return [mrow("p", a, "afar", 1), mrow("p", a, "afar", 0),
            mrow("p", a, "afar_g90", 0),
            mrow("p", a, "cce19", 1), mrow("p", a, "cce19", 0),
            mrow("p", a, "cce19_g90", 0, **bad),
            mrow("p", a, "cce20", 1), mrow("p", a, "cce20", 0),
            mrow("p", a, "cce20_g90", 0, outcome="unobservable",
                 reason="r"),
            mrow("p", a, "cce21", 1), mrow("p", a, "cce21", 0)]


def test_portable_needs_gfx942_x0_x1_and_gfx90a(tmp_path, monkeypatch):
    from offload.engine import report
    monkeypatch.setattr(report, "MODE_DIFFERENCES", {"entries": [],
                                                     "arch_entries": []})
    t = table(tmp_path, _g90_rows())
    assert by(t, toolchain="afar", xnack=1).portable == "portable"
    assert by(t, toolchain="cce19", xnack=1).portable == "gfx942_only"
    assert by(t, toolchain="cce20", xnack=1).portable == "gfx90a_unverified"
    assert by(t, toolchain="cce21", xnack=1).portable == "gfx90a_not_run"
    # the gfx90a rows are cells of their own, not headline rows
    g = by(t, toolchain="cce19_g90", xnack=0)
    assert g.portable == "" and g.label == "wrong answer"
    assert {"gfx942_only", "gfx90a_unverified", "gfx90a_not_run"} <= \
        set(report.PORTABLE)
    # a difference between gfx942 X0 and gfx90a needs a class
    assert by(t, toolchain="cce19", xnack=1).arch_class == "unclassified"
    assert by(t, toolchain="afar", xnack=1).arch_class == ""


def test_three_cell_rule_keeps_the_two_mode_verdict_when_not_portable():
    from offload.engine.report import portable3
    assert portable3("x1_only", "correct on device") == "x1_only"
    assert portable3("portable", "correct on device") == "portable"
    assert portable3("portable", "wrong answer (confirmed)") == "gfx942_only"
    assert portable3("portable", "harness error") == "gfx90a_unverified"
    assert portable3("portable", None) == "gfx90a_not_run"
    assert portable3("needs_zero_copy", "wrong answer") == "needs_zero_copy"


def test_tables_without_gfx90a_rows_keep_the_two_mode_verdict(tmp_path):
    a = "omp.clause.map.to"
    t = table(tmp_path, [mrow("p", a, "afar", 1), mrow("p", a, "afar", 0)])
    assert by(t, xnack=1).portable == "portable"


def test_gfx90a_columns_in_the_markdown(tmp_path, monkeypatch):
    from offload.engine import report
    monkeypatch.setattr(report, "MODE_DIFFERENCES", {"entries": [],
                                                     "arch_entries": []})
    t = table(tmp_path, _g90_rows())
    md = render_markdown(t, [], meta={})
    head = next(ln for ln in md.splitlines()
                if ln.startswith("| atom | evidence | audit |"))
    assert "AFAR gfx90a (X=0)" in head and "CCE 21 gfx90a" not in head
    sep = md.splitlines()[md.splitlines().index(head) + 1]
    assert head.count("|") == sep.count("|")
    line = _atom_line(md, "omp.clause.map.to")
    assert line.count("|") == head.count("|")
    assert "wrong answer" in line
    assert "## gfx90a (MI250X) versus gfx942 (MI300A) copy mode" in md
    assert "gfx942_only" in md
    for ln in md.splitlines():  # every table: header and separator agree
        if ln.startswith("|---"):
            prev = md.splitlines()[md.splitlines().index(ln) - 1]
            assert prev.count("|") == ln.count("|"), prev
    rows = list(__import__("csv").DictReader(
        __import__("io").StringIO(render_csv(t))))
    g = [r for r in rows if r["toolchain"] == "cce19_g90"]
    assert g and g[0]["mode"] == "gfx90a" and g[0]["arch"] == "gfx90a"
    assert {r["arch"] for r in rows if r["toolchain"] == "afar"} == \
        {"gfx942"}
    head_rows = {r["toolchain"]: r["arch_class"] for r in rows
                 if r["mode"] == "headline"}
    assert head_rows["cce19"] == "unclassified"


def test_mi300x_and_mi350x_columns_follow_the_gfx90a_one(tmp_path, monkeypatch):
    """A compiler's twins on other machines (afar_mi300x, afar_mi350x) are cells of their
    own after its gfx90a cell. They do not change the portable verdict, which is MI300A's two
    modes and gfx90a's; their CSV mode is the machine."""
    from offload.engine import report
    monkeypatch.setattr(report, "MODE_DIFFERENCES", {"entries": [],
                                                     "arch_entries": []})
    a = "omp.clause.map.to"
    rows = _g90_rows() + [mrow("p", a, "afar_mi300x", 0),
                          mrow("p", a, "afar_mi350x", 0, outcome="wrong_answer",
                               reason="check_fail: x")]
    t = table(tmp_path, rows)
    assert by(t, toolchain="afar", xnack=1).portable == "portable"
    assert by(t, toolchain="afar_mi350x", xnack=0).label == "wrong answer"
    assert report.columns()[:5] == [("afar", 1), ("afar", 0), ("afar_g90", 0),
                                    ("afar_mi300x", 0), ("afar_mi350x", 0)]
    md = render_markdown(t, [], meta={})
    head = next(ln for ln in md.splitlines()
                if ln.startswith("| atom | evidence | audit |"))
    assert "AFAR gfx90a (X=0) | AFAR MI300X (X=0) | AFAR MI350X (X=0)" in head
    assert "CCE 19 MI300X" not in head
    line = _atom_line(md, a)
    assert line.count("|") == head.count("|")
    csv_rows = list(__import__("csv").DictReader(
        __import__("io").StringIO(render_csv(t))))
    m = [r for r in csv_rows if r["toolchain"] == "afar_mi300x"]
    assert m and m[0]["mode"] == "mi300x" and m[0]["arch"] == "gfx942"
    assert m[0]["host"] == "" and m[0]["portable"] == ""
    # their recorded runs are kept apart from the MI300A modes' and Tioga's
    assert report._twin_machine({"toolchains": ["afar_mi300x"], "xnack": 0}) == "mi300x"
    assert report._twin_machine({"toolchains": ["afar_g90"], "xnack": 0}) is None
    assert report._twin_machine({"toolchains": ["afar_mi300x", "afar"]}) is None
    prov = report._twins_provenance(t, {"twins": {"mi350x": [{"host": "mi350x-12"}]}})
    assert len(prov) == 2 and "nodes mi350x-12" in prov[1] and "AFAR MI350X" in prov[1]


def test_a_compiler_with_twin_rows_only_has_no_mi300a_columns(tmp_path):
    """GCC's MI300A rows are left out of the tables (not gated): its twins' columns stay, its
    MI300A modes are no columns, and the row cells line up with the header."""
    from offload.engine import report
    a = "omp.clause.map.to"
    rows = [mrow("p", a, "afar", 1), mrow("p", a, "afar", 0),
            mrow("p", a, "gcc_g90", 0), mrow("p", a, "gcc_mi300x", 0)]
    t = table(tmp_path, rows)
    cols = report.columns()
    assert ("gcc", 1) not in cols and ("gcc", 0) not in cols
    assert ("gcc_g90", 0) in cols and ("gcc_mi300x", 0) in cols
    md = render_markdown(t, [], meta={})
    head = next(ln for ln in md.splitlines() if ln.startswith("| atom | evidence | audit |"))
    assert "GCC 16.2 (X=1)" not in head and "GCC 16.2 gfx90a (X=0)" in head
    assert _atom_line(md, a).count("|") == head.count("|")


def test_arch_differences_are_classified(tmp_path, monkeypatch):
    from offload.engine import report
    monkeypatch.setattr(report, "MODE_DIFFERENCES", {
        "entries": [], "arch_entries": [
            {"programs": ["p"], "toolchains": ["cce19"],
             "class": "gfx90a_failure", "why": "w",
             "finding": "target-update-sections-in-parallel.f90"}]})
    t = table(tmp_path, _g90_rows())
    assert by(t, toolchain="cce19", xnack=1).arch_class == "gfx90a_failure"
    md = render_markdown(t, [], meta={})
    sec = md.split("## gfx90a (MI250X) versus gfx942 (MI300A) copy mode")[1]
    assert "gfx90a_failure" in sec and "target-update-sections" in sec


def test_write_report_refuses_unclassified_arch_differences(tmp_path,
                                                            monkeypatch):
    from offload.engine import report
    monkeypatch.setattr(report, "MODE_DIFFERENCES", {"entries": [],
                                                     "arch_entries": []})
    m = write_matrix(tmp_path / "matrix.jsonl", _g90_rows())
    au = write_audit(tmp_path / "audit.json", {})
    cl = write_claims(tmp_path / "claims.yaml", [])
    with pytest.raises(ValueError, match="gfx90a"):
        report.write_report(m, cl, au, tmp_path / "none.jsonl",
                            tmp_path / "o.md", tmp_path / "o.csv")


def test_gfx90a_reruns_stay_out_of_the_copy_mode_provenance(tmp_path):
    from offload.engine.report import program_hosts, read_meta
    m = tmp_path / "matrix.jsonl"
    m.write_text("")
    (tmp_path / "matrix.xnack0.jsonl.meta.json").write_text(json.dumps(
        {"host": "tuolumne1", "reruns": []}))
    (tmp_path / "matrix.jsonl.meta.json").write_text(json.dumps(
        {"reruns": [{"xnack": 0, "host": "tioga37", "started": "s",
                     "toolchains": ["afar_g90", "cce19_g90"],
                     "programs": ["p"]}]}))
    meta = read_meta(m)
    assert not meta[0]["reruns"]
    assert meta["g90"]["reruns"][0]["host"] == "tioga37"
    assert program_hosts(meta)("p", 0) == "tuolumne1"


def test_ompvv_gfx90a_differences_are_flagged():
    from offload.engine.report import _baseline_mode_flags

    def b(path, tc, x, status):
        return {"path": path, "toolchain": tc, "xnack": x, "status": status,
                "stage": "run", "reason": "r", "repo": "omp_vv"}
    base = [b("tests/5.0/t.F90", "afar", 1, "pass"),
            b("tests/5.0/t.F90", "afar", 0, "pass"),
            b("tests/5.0/t.F90", "afar_g90", 0, "fail"),
            b("tests/5.0/u.F90", "afar", 0, "pass"),
            b("tests/5.0/u.F90", "afar_g90", 0, "pass")]
    text = "\n".join(_baseline_mode_flags(base))
    sec = text.split("gfx90a")[1]
    assert "t.F90" in text and "u.F90" not in text


def test_committed_arch_differences_are_well_formed():
    from offload.engine.report import ARCH_CLASSES, load_mode_differences
    doc = load_mode_differences()
    for e in doc.get("arch_entries") or []:
        assert e["class"] in ARCH_CLASSES, e
        assert e["programs"] and e["toolchains"] and e["why"].strip()
        if e["class"] in ("gfx90a_failure", "x0_emulation_gap",
                          "gfx942_failure"):
            assert e.get("finding"), e
        if e.get("finding"):
            assert (Path(__file__).resolve().parent.parent.parent / "data" / "findings" / e["finding"]).is_file(), e


def test_a_5x_feature_claim_is_not_compared_with_60_programs(tmp_path):
    """A claim from a 5.x feature list covers the 5.x spelling;
    a 6.0 program is compared only with claims from a 6.0 list or claims
    that name no spec version (or list 60 explicitly)."""
    rows = [mrow(f"omp{v}-p", "omp.clause.map.to", "cce19", 1,
                 outcome="rejected", reason="ice: x", version=v)
            for v in (52, 60)]
    t = table(tmp_path, rows)
    ms = compare_claims(t, _generic(tmp_path, spec_version="5.1"))
    assert [m.version for m in ms] == [52]
    ms = compare_claims(t, _generic(tmp_path, spec_version=""))
    assert sorted(m.version for m in ms) == [52, 60]
    ms = compare_claims(t, _generic(tmp_path, spec_version="5.1",
                                    versions="52,60"))
    assert sorted(m.version for m in ms) == [52, 60]


def test_confounds_apply_to_every_release_and_the_gfx90a_twins():
    """A listed confound (another feature rejected) holds for the
    compiler, so for its gfx90a twin and, for CCE, every release (the
    message tables are CCE 19's); report.family (label categories) once
    shadowed the toolchain family, so only afar and cce19 matched."""
    from offload.engine.report import confound
    r = "not_implemented: x: not yet implemented: omp.declare_simd"
    assert confound("omp.clause.linear.uval", "afar", r)
    assert confound("omp.clause.linear.uval", "afar_g90", r)
    d = "not_implemented: Implementation for the DYNAMIC_ALLOCATORS clause"
    assert confound("omp.clause.allocate", "cce19", d)
    assert confound("omp.clause.allocate", "cce21", d)
    assert confound("omp.clause.allocate", "cce20_g90", d)


def test_rows_of_an_unknown_toolchain_fail_loudly(tmp_path):
    """A toolchain with rows in the results but no
    support-table column (for example an NVHPC run before the report knew it, or
    another unknown compiler) is an error, never silently dropped."""
    rows = [mrow("omp52-clause-x", "omp.clause.x", "afar", 1),
            mrow("omp52-clause-x", "omp.clause.x", "xlf", 0)]
    with pytest.raises(ValueError, match="xlf"):
        build_table(write_matrix(tmp_path / "m.jsonl", rows), audit=None)


@pytest.mark.parametrize("cls,x1,x0,ok", [
    ("both_wrong", "crash: SIGSEGV, HSA_XNACK=1 only",
     "implementation-defined", False),
    ("both_wrong", "crash: SIGSEGV", "wrong answer (confirmed)", True),
    ("unified_memory_failure", "crash: SIGSEGV, HSA_XNACK=1 only",
     "implementation-defined", True),
    ("unified_memory_failure", "crash: SIGSEGV", "wrong answer", False),
    ("copy_mode_failure", "correct on device", "wrong answer", True),
    ("copy_mode_failure", "wrong answer", "correct on device", False),
    ("x1_oracle_blind", "correct on device (copy-mode evidence)",
     "wrong answer (confirmed)", True),
    ("needs_unified_memory", "compiled and ran; nothing checked",
     "fails in copy mode: needs zero-copy memory", True),
    ("requirement_refused", "compiled and ran; nothing checked",
     "crash: SIGABRT, HSA_XNACK=0 only", True),
    ("requirement_refused", "compiled and ran; nothing checked",
     "correct on device", False),
])
def test_mode_class_must_fit_the_cells(cls, x1, x0, ok):
    """A mode class names which mode fails; a class
    the two cells contradict (both_wrong next to a correct copy-mode
    cell) is reported."""
    from offload.engine.report import mode_class_problem
    assert (mode_class_problem(cls, x1, x0) is None) == ok


def _support_rows():
    import csv
    root = Path(__file__).resolve().parent.parent.parent
    paths = [root / "results" / "support_table.csv",
             root / "data" / "reports" / "c_support_table.csv",
             root / "data" / "reports" / "acc_support_table.csv",
             root / "data" / "reports" / "acc_c_support_table.csv"]
    missing = [str(p.relative_to(root)) for p in paths if not p.is_file()]
    if missing:
        pytest.skip(f"needs the support tables {missing} (git-ignored "
                    "results/: docs/tooling/setup.md, docs/tooling/regenerate.md)")
    rows = []
    for p in paths:
        with p.open(newline="") as fh:
            rows += list(csv.DictReader(fh))
    return rows


def test_every_mode_difference_entry_matches_the_current_data():
    """Every catalog/mode_differences.yaml entry (and
    arch entry) classifies at least one current difference of the support
    tables, and its class fits every cell it classifies, so an entry
    cannot go stale silently (CCE C dist_schedule kept both_wrong after
    Made its copy-mode cells correct)."""
    from fnmatch import fnmatchcase
    from offload.engine.report import (MODE_DIFFERENCES, mode_class_problem,
                                   arch_entry, mode_entry, nv_mode_entry)
    from offload.engine.toolchains import NVIDIA_TOOLCHAINS
    rows = _support_rows()
    used, problems = set(), []
    for r in rows:
        if r["mode_class"] and r["toolchain"] in NVIDIA_TOOLCHAINS:
            # NVIDIA separate/managed differences are classified by
            # nvhpc_entries (their classes name managed memory, not XNACK)
            e = nv_mode_entry(r["program_id"], r["toolchain"])
            assert e is not None and e["class"] == r["mode_class"], r
            used.add(("nv", id(e)))
            continue
        if r["mode_class"] and r["mode_class"] != "unclassified":
            e = mode_entry(r["program_id"], r["toolchain"])
            assert e is not None and e["class"] == r["mode_class"], r
            used.add(("mode", id(e)))
            why = mode_class_problem(r["mode_class"], r["label"],
                                     r["copy_label"])
            if why:
                problems.append(f"{r['program_id']} {r['toolchain']}: {why}")
        if r["arch_class"] and r["arch_class"] != "unclassified":
            used.add(("arch", id(arch_entry(r["program_id"],
                                            r["toolchain"]))))
    dead = [e["programs"] for e in MODE_DIFFERENCES.get("entries") or []
            if ("mode", id(e)) not in used]
    dead += [e["programs"] for e in MODE_DIFFERENCES.get("arch_entries")
             or [] if ("arch", id(e)) not in used]
    dead += [e["programs"] for e in MODE_DIFFERENCES.get("nvhpc_entries")
             or [] if ("nv", id(e)) not in used]
    assert not problems, problems
    assert not dead, f"entries that classify no current difference: {dead}"


# --- NVHPC (wingtip, A100) columns ----------------------------------------

def _nv_rows(a="omp.clause.map.to"):
    bad = dict(outcome="wrong_answer", reason="check_fail: x")
    return [mrow("p", a, "afar", 1), mrow("p", a, "afar", 0),
            mrow("p", a, "cce19", 1), mrow("p", a, "cce19", 0, **bad),
            mrow("p", a, "nvhpc", 0, **bad), mrow("p", a, "nvhpc", 2),
            mrow("q", "omp.clause.map.from", "afar", 1),
            mrow("q", "omp.clause.map.from", "afar", 0),
            mrow("q", "omp.clause.map.from", "nvhpc", 0),
            mrow("q", "omp.clause.map.from", "nvhpc", 2)]


def test_nvhpc_has_its_own_columns_and_verdict(tmp_path, monkeypatch):
    from offload.engine import report
    monkeypatch.setattr(report, "NV_AUDIT", {})  # no real NVHPC audit
    monkeypatch.setattr(report, "MODE_DIFFERENCES", {"entries": [
        {"programs": ["p"], "toolchains": ["cce19"],
         "class": "copy_mode_failure", "why": "w"}], "arch_entries": []})
    t = table(tmp_path, _nv_rows())
    assert report.NV == ["nvhpc"] and report.TOOLCHAINS == ["afar", "cce19"]
    head = by(t, program_id="p", toolchain="nvhpc", xnack=0)
    assert head.copy_label == "correct on device"
    assert head.portable == "x1_only"  # correct in managed memory only
    assert head.mode_class == "unclassified"
    assert by(t, program_id="p", toolchain="nvhpc", xnack=2).portable == ""
    assert by(t, program_id="q", toolchain="nvhpc", xnack=0).portable == \
        "portable"
    # the AMD verdicts never read an NVIDIA row
    assert by(t, program_id="p", toolchain="afar", xnack=1).portable == \
        "portable"
    assert report.columns()[-2:] == [("nvhpc", 0), ("nvhpc", 2)]


def test_nvhpc_markdown_and_csv(tmp_path, monkeypatch):
    from offload.engine import report
    monkeypatch.setattr(report, "NV_AUDIT", {})  # no real NVHPC audit
    monkeypatch.setattr(report, "MODE_DIFFERENCES", {
        "entries": [{"programs": ["p"], "toolchains": ["cce19"],
                     "class": "copy_mode_failure", "why": "w"}],
        "arch_entries": [],
        "nvhpc_entries": [{"programs": ["p"], "toolchains": ["nvhpc"],
                           "class": "separate_failure", "why": "nv w"}]})
    t = table(tmp_path, _nv_rows())
    assert by(t, program_id="p", toolchain="nvhpc", xnack=0).mode_class \
        == "separate_failure"
    md = render_markdown(t, [], meta={})
    head = next(ln for ln in md.splitlines()
                if ln.startswith("| atom | evidence | audit |"))
    assert "NVHPC 25.11 separate (A100) | NVHPC 25.11 managed (A100)" in head
    assert "NVHPC 25.11 portable (separate and managed)" in head
    for ln in md.splitlines():  # every table: header and separator agree
        if ln.startswith("|---"):
            prev = md.splitlines()[md.splitlines().index(ln) - 1]
            assert prev.count("|") == ln.count("|"), prev
    line = _atom_line(md, "omp.clause.map.to")
    assert line.count("|") == head.count("|")
    assert "x1_only (separate_failure)" in line
    assert "## Portable verdict, NVIDIA (separate and managed memory)" in md
    sec = md.split("## Memory-mode differences, NVIDIA")[1]
    assert "separate_failure" in sec and "nv w" in sec
    amd = md.split("## Memory-mode differences\n")[1].split("## ")[0]
    assert "NVHPC" not in amd  # the AMD mode table has AMD rows only
    rows = list(__import__("csv").DictReader(
        __import__("io").StringIO(render_csv(t))))
    nv = {r["mode"]: r for r in rows if r["toolchain"] == "nvhpc"
          and r["program_id"] == "p"}
    assert set(nv) == {"sm_80 separate", "sm_80 managed"}
    assert nv["sm_80 separate"]["copy_label"] == "correct on device"
    assert nv["sm_80 separate"]["arch"] == "sm_80"


def test_amd_rendering_ignores_nvhpc_rows(tmp_path, monkeypatch):
    """Adding NVIDIA rows changes no AMD cell, verdict or count:
    the AMD columns of the per-atom rows are the same with and without
    them."""
    from offload.engine import report
    monkeypatch.setattr(report, "MODE_DIFFERENCES", {"entries": [
        {"programs": ["p"], "toolchains": ["cce19"],
         "class": "copy_mode_failure", "why": "w"}], "arch_entries": [],
        "nvhpc_entries": [{"programs": ["p"], "toolchains": ["nvhpc"],
                           "class": "separate_failure", "why": "x"}]})
    amd_rows = [r for r in _nv_rows() if r["toolchain"] != "nvhpc"]
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    t0 = table(tmp_path / "a", amd_rows)
    md0 = render_markdown(t0, [], meta={})
    t1 = table(tmp_path / "b", _nv_rows())
    md1 = render_markdown(t1, [], meta={})
    key = ["portable", "label", "copy_label", "mode_class", "arch_class"]
    amd1 = [r for r in t1 if r.toolchain != "nvhpc"]
    assert [[getattr(r, k) for k in key] for r in t0] == \
        [[getattr(r, k) for k in key] for r in amd1]
    n = len(report.columns()) - 2
    for atom in ("omp.clause.map.to", "omp.clause.map.from"):
        c0 = _atom_line(md0, atom).split(" | ")
        c1 = _atom_line(md1, atom).split(" | ")
        # the NVHPC mode cells after the AMD ones, its portable verdict
        # before the citation; every AMD cell as it was
        assert c1 == c0[:3 + n] + c1[3 + n:5 + n] + c0[3 + n:-1] + \
            [c1[-2]] + c0[-1:]
    portable0 = md0.split("## Portable verdict")[1].split("## ")[0]
    assert portable0 in md1


def test_nvhpc_mode_class_problem():
    from offload.engine.report import nv_mode_class_problem
    assert nv_mode_class_problem("separate_failure", "wrong answer",
                                 "correct on device") is None
    assert nv_mode_class_problem("managed_failure", "wrong answer",
                                 "correct on device")
    assert nv_mode_class_problem("both_wrong", "crash: SIGSEGV",
                                 "wrong answer") is None


def test_nvhpc_reruns_stay_out_of_the_amd_provenance(tmp_path):
    from offload.engine.report import read_meta
    m = tmp_path / "matrix.jsonl"
    m.write_text("")
    (tmp_path / "matrix.jsonl.meta.json").write_text(json.dumps(
        {"reruns": [{"xnack": 0, "host": "wingtip3", "started": "s",
                     "toolchains": ["nvhpc"], "programs": ["p"]},
                    {"xnack": 2, "host": "wingtip3", "started": "t",
                     "toolchains": ["nvhpc"], "programs": ["p"]}]}))
    meta = read_meta(m)
    assert 0 not in meta and "g90" not in meta
    assert len(meta["nvhpc"]["reruns"]) == 2


def test_nvhpc_crash_and_zero_copy_labels_name_the_mode(tmp_path):
    a = "omp.clause.map.to"
    crash = dict(outcome="wrong_answer", reason="crash: SIGSEGV; x")
    t = table(tmp_path, [
        mrow("p", a, "nvhpc", 0, **crash), mrow("p", a, "nvhpc", 2),
        mrow("z", "omp.clause.unified_shared_memory", "nvhpc", 2,
             outcome="wrong_answer", reason="check_fail: x",
             needs=("zero_copy",))])
    assert by(t, program_id="p", xnack=0).label == \
        "crash: SIGSEGV, separate only"
    z = by(t, program_id="z", xnack=2)
    assert z.label.startswith("fails in copy mode: needs zero-copy memory "
                              "(managed memory, no unified memory")


def test_nvhpc_managed_shares_storage_is_not_a_failure(tmp_path, monkeypatch):
    """A copy_mode_only program correct in separate memory whose
    managed cell fails only because managed memory shares the checked
    storage reads 'not verifiable' there, verdict managed_unverified."""
    from offload.engine import report
    monkeypatch.setattr(report, "MODE_DIFFERENCES", {
        "entries": [], "arch_entries": [], "nvhpc_entries": [
            {"programs": ["p"], "toolchains": ["nvhpc"],
             "class": "managed_shares_storage", "why": "w"}]})
    a = "omp.clause.map.to"
    t = table(tmp_path, [
        mrow("p", a, "nvhpc", 0, evidence="copy_mode_only"),
        mrow("p", a, "nvhpc", 2, outcome="wrong_answer",
             reason="check_fail: x", evidence="copy_mode_only")])
    h = by(t, xnack=0)
    assert h.mode_class == "managed_shares_storage"
    assert h.portable == "managed_unverified"
    assert by(t, xnack=2).label == report.NV_SHARED_TEXT
    assert h.copy_label == report.NV_SHARED_TEXT
    assert report.nv_mode_class_problem("managed_shares_storage",
                                        h.label, h.copy_label) is None


def test_nvhpc_cells_read_their_own_audit(tmp_path, monkeypatch):
    """Dispositions are per toolchain: an AMD 'valid' oracle does
    not make an NVHPC wrong answer confirmed."""
    from offload.engine import report
    monkeypatch.setattr(report, "MODE_DIFFERENCES", {"entries": [],
                                                     "arch_entries": []})
    a = "omp.clause.map.to"
    bad = dict(outcome="wrong_answer", reason="check_fail: x")
    rows = [mrow("p", a, "afar", 1, **bad), mrow("p", a, "afar", 0, **bad),
            mrow("p", a, "nvhpc", 0, **bad), mrow("p", a, "nvhpc", 2, **bad)]
    nv = tmp_path / "nv.json"
    nv.write_text(json.dumps({"modes": {"2": {"versions": {"52": {
        a: {"disposition": "valid"}}}}}}))
    monkeypatch.setitem(report.NV_AUDIT, ("omp", "f90"), nv)
    report._nv_audit_file.cache_clear()
    t = table(tmp_path, rows, audit={(52, a): "valid"})
    assert by(t, toolchain="afar", xnack=1).label == "wrong answer (confirmed)"
    assert by(t, toolchain="nvhpc", xnack=0).label == "wrong answer"
    assert by(t, toolchain="nvhpc", xnack=2).label == \
        "wrong answer (confirmed)"
    report._nv_audit_file.cache_clear()


def test_gcc_rows_build_a_table(tmp_path):
    """GCC: merged GCC rows build a table: gcc is an AMD column with its twins (gcc_g90 on the
    MI250X), gcc_sm80 an NVIDIA column."""
    from offload.engine import report
    rows = [mrow("omp52-clause-x", "omp.clause.x", "afar", 1),
            mrow("omp52-clause-x", "omp.clause.x", "gcc", 1),
            mrow("omp52-clause-x", "omp.clause.x", "gcc", 0),
            mrow("omp52-clause-x", "omp.clause.x", "gcc_g90", 0),
            mrow("omp52-clause-x", "omp.clause.x", "gcc_sm80", 0)]
    t = build_table(write_matrix(tmp_path / "m.jsonl", rows), audit=None)
    tcs = {r.toolchain for r in t}
    assert {"afar", "gcc", "gcc_g90", "gcc_sm80"} <= tcs
    assert ("gcc", 1) in report.columns() and ("gcc_g90", 0) in report.columns()
    assert by(t, toolchain="gcc", xnack=1).portable == "portable"
    # GCC on the A100 runs separate memory only: its verdict is over that one mode
    assert by(t, toolchain="gcc_sm80", xnack=0).portable == "one_mode_correct"


# ---- The support tables' gate column -----------------------------------------


from offload.engine import report
from offload.engine.report import (Row, annotate_gate, confirmed_failure,
                               gate_status)


def vrec(ident, tc, x, verdict, inherited=False, cls="wrong_answer",
         kind="catalog"):
    return {"cell": f"{kind}|{ident}|{tc}|{x}", "campaign": kind,
            "kind": kind, "ident": ident, "toolchain": tc, "xnack": x,
            "signature": f"{tc}|{cls}|key", "verdict": verdict,
            "inherited": inherited,
            "sample": "inherited" if inherited else "rerun"}


def test_gate_status_reading():
    assert gate_status(None, None) == "ungated"
    assert gate_status(vrec("p", "afar", 1, "confirmed"), None) == \
        "confirmed"
    # inherited: only from a compile-time signature
    assert gate_status(vrec("p", "afar", 1, "confirmed", True, "rejected"),
                       None) == "confirmed"
    assert gate_status(vrec("p", "afar", 1, "confirmed", True,
                            "wrong_answer"), None) == "unchecked"
    assert gate_status(vrec("p", "afar", 1, "unchecked"), None) == \
        "unchecked"
    assert gate_status(vrec("p", "afar", 1, "nondeterministic"), None) == \
        "nondeterministic"
    assert gate_status(vrec("p", "afar", 1, "environment"), None) == \
        "environment"
    assert gate_status(vrec("p", "afar", 1, "nondeterministic"),
                       {"decision": "ours", "counts_as": "failure"}) == \
        "decided"
    assert gate_status(vrec("p", "afar", 1, "nondeterministic"),
                       {"decision": "x", "counts_as": "none"}) == \
        "decided_not_counted"


def rows():
    return [
        Row("omp.a", "afar", 1, "wrong_answer", False, program_id="p1",
            label="wrong answer (confirmed)"),
        Row("omp.a", "cce19", 1, "rejected", False, program_id="p1",
            label="rejected: x"),
        Row("omp.b", "afar", 1, "wrong_answer", False, program_id="p2",
            label="wrong answer (oracle unaudited)"),
        Row("omp.b", "cce19", 1, "correct_on_device", False,
            program_id="p2", label="correct on device"),
        Row("omp.c", "afar", 0, "wrong_answer", False, program_id="p3",
            label="wrong answer (confirmed)"),
        Row("omp.c", "cce20", 0, "wrong_answer", False, program_id="p3",
            label="wrong answer (confirmed)"),
    ]


def test_annotate_and_count(tmp_path):
    vf = tmp_path / "verdicts.jsonl"
    recs = [vrec("p1", "afar", 1, "confirmed"),
            vrec("p1", "cce19", 1, "confirmed", True, "rejected"),
            vrec("p2", "afar", 1, "unchecked"),
            vrec("p3", "afar", 0, "nondeterministic", kind="widen")]
    vf.write_text("".join(json.dumps(r) + "\n" for r in recs))
    df = tmp_path / "queue.yaml"
    df.write_text("entries:\n  - cell: widen|p3|afar|0\n    verdict: ours\n"
                  "    counts_as: failure\n")
    t = annotate_gate(rows(), vf, df)
    g = {(r.program_id, r.toolchain): r.gate for r in t}
    assert g == {("p1", "afar"): "confirmed", ("p1", "cce19"): "confirmed",
                 ("p2", "afar"): "unchecked", ("p2", "cce19"): "",
                 ("p3", "afar"): "decided", ("p3", "cce20"): "ungated"}
    counted = {(r.program_id, r.toolchain) for r in t
               if confirmed_failure(r)}
    # the ruling: confirmed, compile-inherited
    # confirmed and decided-as-counting cells; an unchecked or ungated cell
    # is not a confirmed failure (gate.counts keeps it for campaign counts)
    assert counted == {("p1", "afar"), ("p1", "cce19"), ("p3", "afar")}


def test_the_gate_column_reads_the_gcc_lanes_verdicts(tmp_path):
    """The GCC lane gates its own rows (tools/campaigns/gcc_lane.py) into verdict files of its
    own, keyed by cell only; the gate column reads them, and the gate's store wins a cell both
    hold."""
    lane = tmp_path / "lane.jsonl"
    lane.write_text(json.dumps({"cell": "catalog|p9|gcc_g90|0", "toolchain": "gcc_g90",
                                "ident": "p9", "verdict": "confirmed", "envs": list("abcd")}) + "\n"
                    + json.dumps({"cell": "catalog|p1|afar|1", "verdict": "nondeterministic"}) + "\n")
    vf = tmp_path / "verdicts.jsonl"
    vf.write_text(json.dumps(vrec("p1", "afar", 1, "confirmed")) + "\n")
    r = Row("omp.x", "gcc_g90", 0, "wrong_answer", False, program_id="p9", label="wrong answer")
    t = annotate_gate(rows() + [r], vf, tmp_path / "none.yaml", lanes=[lane])
    g = {(x.program_id, x.toolchain): x.gate for x in t}
    assert g[("p9", "gcc_g90")] == "confirmed" and g[("p1", "afar")] == "confirmed"


def test_csv_ends_with_the_gate_column(tmp_path):
    t = annotate_gate(rows(), tmp_path / "none.jsonl", tmp_path / "none.yaml")
    text = report.render_csv(t)
    head = text.splitlines()[0].split(",")
    assert head[-1] == "gate" and report.CSV_FIELDS[-1] == "gate"
    assert text.splitlines()[1].split(",")[-1] == "ungated"


def test_gate_section_counts_only_confirmed(tmp_path):
    vf = tmp_path / "verdicts.jsonl"
    vf.write_text(json.dumps(vrec("p1", "afar", 1, "confirmed")) + "\n" +
                  json.dumps(vrec("p2", "afar", 1, "unchecked")) + "\n")
    t = annotate_gate(rows(), vf, tmp_path / "none.yaml")
    lines = report.gate_section(t)
    text = "\n".join(lines)
    assert "## Reproduction gate" in text
    assert "counted" in text and "confirmed (own" in text
    # the unchecked cell is listed apart
    assert "| p2 |" in text.split("Not counted")[1]


def test_a_support_claim_is_contradicted_only_by_a_counted_failure():
    """Only confirmed or decided-as-counting cells (and ungated ones, Task
    45's rule for rows the gate has not seen) contradict a claim."""
    from offload.engine.report import Claim, _disagrees
    c = Claim("s", "u", "afar", "supported", "")
    r = Row("omp.a", "afar", 1, "wrong_answer", False, program_id="p1",
            label="wrong answer (confirmed)", gate="confirmed")
    assert _disagrees(c, r)
    from dataclasses import replace
    assert not _disagrees(c, replace(r, gate="unchecked"))
    assert not _disagrees(c, replace(r, gate="nondeterministic"))
    assert _disagrees(c, replace(r, gate="decided"))
    assert not _disagrees(c, replace(r, gate="decided_not_counted"))
    assert _disagrees(c, replace(r, gate="ungated"))


def test_confirmed_failure_differs_from_gate_counts_as_documented():
    """Gate.counts keeps an unchecked row at its previous outcome
    (campaign counts); the support tables' confirmed_failure does not."""
    from offload.engine import gate as G
    assert G.counts({"verdict": "unchecked"}) is True
    r = Row("omp.a", "afar", 1, "wrong_answer", False, program_id="p",
            label="wrong answer (confirmed)", gate="unchecked")
    assert not confirmed_failure(r)
    assert G.counts({"verdict": "x", "counts_as": "failure"}) is True
    assert confirmed_failure(Row("omp.a", "afar", 1, "wrong_answer", False,
                                 program_id="p", label="wrong answer",
                                 gate="decided"))
    assert "gate.counts" in confirmed_failure.__doc__


def test_a_recorded_our_bug_ruling_marks_the_cell_ours(tmp_path):
    """The withdrawn complex-reduction link (RUL-HOST-LIBATOMIC)
    reads `ours`, not counted, although its gate verdict is confirmed."""
    vf = tmp_path / "v.jsonl"
    vf.write_text(json.dumps(vrec("omp52-c-w-reduction-complex", "afar", 1,
                                  "confirmed", cls="rejected")) + "\n")
    r = Row("omp.x", "afar", 1, "rejected", False,
            program_id="omp52-c-w-reduction-complex", label="rejected",
            reason="link_undefined_symbol: ld.lld: error: undefined symbol: "
            "__atomic_load")
    (g,) = annotate_gate([r], vf, tmp_path / "none.yaml")
    assert g.gate == "ours" and not confirmed_failure(g)


def test_a_runtime_ruling_is_named_in_the_gate_section(tmp_path):
    """A CCE 21 Fortran defaultmap cell read as fell back to
    host carries its ruling (it ran on the device; the flag was lost)."""
    from offload.engine.report import runtime_ruling
    r = Row("omp.clause.defaultmap", "cce21", 0, "fell_back_to_host", False,
            program_id="omp52-clause-defaultmap-alloc",
            label="fell back to host", reason="ran_on_host=1 check=pass")
    assert runtime_ruling(r).id == "RUL-MAPPED-FLAG-NOT-COPIED-BACK"
    (g,) = annotate_gate([r], tmp_path / "v.jsonl", tmp_path / "none.yaml")
    text = "\n".join(report.gate_section([g]))
    assert "RUL-MAPPED-FLAG-NOT-COPIED-BACK" in text


# ---- catalog/toolchains.yaml is the one source of the toolchain list --------------------------------

import importlib
import importlib.util
import subprocess


from offload.engine import toolchains as T
from tests import toolchain_scan as SCAN

ROOT = Path(__file__).resolve().parent.parent.parent


def _gen():
    spec = importlib.util.spec_from_file_location("_tcgen", ROOT / "tools" / "derive" / "toolchains_gen.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- the generated files -------------------------------------------------------------

def test_generated_files_are_current():
    """site/static/toolchains.js, tools/jobs/toolchains.sh and docs/tooling/toolchains.md are what
    tools/derive/toolchains_gen.py writes from the catalog (rerun it after editing the catalog)."""
    assert _gen().stale() == []


def test_generated_files_carry_the_header_and_the_scripts_source_the_table():
    G = _gen()
    for path in G.OUTPUTS:
        assert G.HEADER in (ROOT / path).read_text(), path
    for script in ("run_wingtip.sh", "run_gcc_lane.sh", "run_gcc_full.sh", "run_gcc_sweep.sh",
                   "run_tioga.sh", "run_x0_full.sh", "run_site_matrix.sh"):
        text = where.tool(script).read_text()
        assert "toolchains.sh" in text and "tc_" in text, script


def test_the_shell_table_checks_a_toolchain_against_its_lane(tmp_path):
    table = _gen().shell_table(T.registry())
    script = tmp_path / "t.sh"
    script.write_text(table + '\ntc_check "$1" "$2"\n')
    assert subprocess.run(["bash", str(script), "nvhpc269", "wingtip"]).returncode == 0
    r = subprocess.run(["bash", str(script), "gcc_sm80", "wingtip"], capture_output=True, text=True)
    assert r.returncode == 1 and "its lane: gcc" in r.stderr
    r = subprocess.run(["bash", str(script), "xlf", "gcc"], capture_output=True, text=True)
    assert r.returncode == 1 and "unknown toolchain xlf" in r.stderr


def test_the_site_scripts_read_the_generated_constants():
    """query.js, issues.js and canuse.js define no toolchain table of their own; the pages
    load static/toolchains.js before them."""
    for js in ("query.js", "issues.js", "canuse.js"):
        text = (ROOT / "site" / "static" / js).read_text()
        for const in ("const FAMILIES =", "const VERSIONS =", "const TC =", "const CU_TC =",
                      "const FAM_NAME =", "const TG_NAME ="):
            assert const not in text, (js, const)
    build = (ROOT / "tools" / "site" / "site_build.py").read_text()
    assert build.count('static/toolchains.js"></script>') == 2


# --- no hard-coded toolchain outside the catalog ------------------------------------------

def test_no_hard_coded_toolchain_outside_the_catalog():
    """A registered toolchain id or version in code (a Python string, a shell
    command, JavaScript) is a list the catalog owns. Offenders are exactly the
    allow-list (catalog/toolchain_names_allowlist.yaml): a new one fails here, a
    listed file with no hit must be removed from the list."""
    found = SCAN.scan()
    allowed = SCAN.allowlist()
    new = sorted(set(found) - set(allowed))
    gone = sorted(set(allowed) - set(found))
    msg = []
    if new:
        msg.append("code outside catalog/toolchains.yaml names a toolchain or version:")
        msg += [f"  {p}: {found[p]}" for p in new]
        msg.append("  read it from offload.engine.toolchains (registry(), the lists) or the generated "
                   "tools/jobs/toolchains.sh; a reason in the allow-list is the last resort")
    if gone:
        msg.append("allow-listed files with no hit any more (remove them from "
                   "catalog/toolchain_names_allowlist.yaml): " + ", ".join(gone))
    assert not msg, "\n".join(msg)


def test_the_scan_sees_code_not_prose(tmp_path):
    p = tmp_path / "x.py"
    p.write_text('"""cce21_4 in a docstring is fine."""\n# cce19 in a comment too\n'
                 'X = "cce21_4"  # a string is code\n')
    hits = [t for _, t in SCAN.code_text(p)]
    assert hits == ["cce21_4"]
    sh = tmp_path / "x.sh"
    sh.write_text("# TC=cce21_4 in a comment\nTC=cce21_4\n")
    assert [t for _, t in SCAN.code_text(sh)] == ["TC=cce21_4"]
    pat = SCAN.pattern()
    assert pat.search("--toolchains afar cce19") and pat.search("cce/21.0.4 ")
    assert not pat.search("cce19-target-parallel-guarded-loop.f90")   # a finding file name
    assert not pat.search("therock-afar-24.3.0-multiarch")           # an install directory
    assert not pat.search("afar nvhpc")                              # family names


def test_the_vendor_packet_tables_agree_with_the_catalog(monkeypatch, request):
    """data/vendor/checks keeps its own copy of the recipes (allow-listed); its tables
    must agree with the catalog."""
    import sys
    sys.path.insert(0, str(ROOT / "data" / "vendor" / "checks"))
    import render as RD
    import run_checks as RC
    monkeypatch.setenv("OFFLOAD_LOCAL", "")        # the catalog's own install paths
    request.addfinalizer(T.reset)
    T.reset()
    reg = T.registry()
    for tc, (ver, rocm) in RC.CCE.items():
        t = reg.toolchains[tc]
        assert t.version == ver and f"rocm/{rocm}" in t.prelude, tc
    for tc, root in RC.NV.items():
        assert reg.toolchains[tc].install_roots[0].startswith(root), tc
    gcc = [t for t in reg.toolchains.values() if t.family_id == "gcc"]
    assert gcc and all(t.install_roots == (RC.GCC_DEFAULT,) for t in gcc)
    for t in gcc:
        assert RC.GCC_TARGET[t.machine] == ("nvptx-none" if t.arch.startswith("sm_") else "amdgcn-amdhsa"), t.name
    assert set(RD.ALLTC) == {n for n in reg.site_toolchains() if reg.toolchains[n].family.vendor}
    for tc, name in RD.TCNAME.items():
        t = reg.toolchains[tc]
        assert name == (t.site_version if t.site_version.startswith(t.family.name)
                        else f"{t.family.name} {t.site_version}"), tc


# --- adding a compiler is a config edit ---------------------------------------------------

FAKE = {
    # a CCE release on Tuolumne (the AMD lane) ...
    "cce99": {"family": "cce", "version": "99.0.0", "machine": "tuolumne", "arch": "gfx942",
              "modes": ["unified", "copy"], "label": "CCE 99", "merged_key": "cce99",
              "lane": "tuolumne", "modules": {"cce": "99.0.0", "rocm": "7.2.0"}},
    # ... and an NVHPC release on wingtip (the wingtip lane)
    "nvhpc99": {"family": "nvhpc", "version": "99.1", "machine": "wingtip", "arch": "sm_80",
                "modes": ["copy", "managed"], "label": "NVHPC 99.1", "merged_key": "nvhpc99",
                "site_root_var": "NVHPC_99_1", "lane": "wingtip",
                "install": {"default": "/opt/nvidia/hpc_sdk/Linux_x86_64/99.1/compilers/bin",
                            "env": "NVHPC99_BIN"},
                "fc": "{root}/nvfortran", "cc": "{root}/nvc",
                "env": {"LD_LIBRARY_PATH": "{root_dir}/lib"}},
}
# the modules whose constants are built from the registry at import
CONSUMERS = ("offload.engine.report", "offload.engine.site.matrix", "offload.engine.site.data",
             "offload.engine.finding_header", "offload.engine.fuzz_exec", "offload.engine.fuzz_report",
             "offload.engine.fuzz_campaign", "offload.engine.run_matrix")


def _reload_consumers():
    for name in CONSUMERS:
        importlib.reload(importlib.import_module(name))


@pytest.fixture
def fake_catalog(tmp_path, monkeypatch):
    """The committed catalog plus the fake releases, in force for the registry and the
    consumer modules; the real catalog is restored afterwards."""
    data = yaml.safe_load(T.CATALOG.read_text())
    data["toolchains"].update(FAKE)
    p = tmp_path / "toolchains.yaml"
    p.write_text(yaml.safe_dump(data, sort_keys=False))
    # the canaries: the five kinds of the release the fake is like (the real ones are measured)
    canaries = yaml.safe_load((ROOT / "catalog" / "canaries.yaml").read_text())
    canaries["toolchains"]["cce99"] = canaries["toolchains"]["cce21"]
    canaries["toolchains"]["nvhpc99"] = canaries["toolchains"]["nvhpc269"]
    cp = tmp_path / "canaries.yaml"
    cp.write_text(yaml.safe_dump(canaries))
    from offload.engine import canary
    monkeypatch.setenv(T.CATALOG_ENV, str(p))
    monkeypatch.setattr(canary, "CANARIES", cp)
    T.reset()
    importlib.reload(T)
    try:
        _reload_consumers()
        yield T.registry()
    finally:
        monkeypatch.delenv(T.CATALOG_ENV)
        T.reset()
        importlib.reload(T)
        _reload_consumers()


def test_adding_a_compiler_is_a_config_edit(fake_catalog):
    """With cce99 and nvhpc99 added to a copy of the catalog (no code edit) the recipe,
    the registry checks, the canary requirement, the matrix cases and the site matrix,
    the support-table columns, the site columns and pills, the shell table and lane
    lists, the header mention parser and the fuzz orders all include them. What needs a
    real compiler is left to the plan: measuring the canaries (tools/campaigns/gate.py canaries),
    the compiler version and code-object metadata, the smoke run, the matrix and the gate
    (docs/tooling/contributing.md, "Add a compiler or a compiler release")."""
    reg = fake_catalog
    from offload.engine import report as R
    from offload.engine.site import matrix as M
    from offload.engine.site import data as D
    from offload.engine import finding_header as H
    from offload.engine import fuzz_exec as FE
    from offload.engine import fuzz_report as FR
    from offload.engine import run_matrix as RM
    from offload.engine.confirm import machines as MA
    from offload.engine import gate as G
    # the recipe
    cce99, nv27 = T.TOOLCHAINS["cce99"], T.TOOLCHAINS["nvhpc99"]
    cmd = cce99.compile_cmd("a.f90", "a.out")
    assert "module load cce/99.0.0 craype-accel-amd-gfx942 rocm/7.2.0" in cmd and "ftn -fopenmp -O2" in cmd
    assert cce99.run_env(1) == {"HSA_XNACK": "1"} and T.family("cce99") == "cce19"
    assert nv27.for_mode(2).compile_cmd("a.f90", "a.out").endswith(
        "nvfortran -mp=gpu -gpu=cc80 -gpu=mem:managed -O2 a.f90 -o a.out")
    assert RM.version_flags("cce99", 52, "c") == "-fopenmp-version=52"
    # the registry checks pass, the canary requirement includes them (with the canaries
    # removed again it names them)
    assert T.check_registry(reg) == []
    assert MA.family_of("cce99") == "cce" and "cce99" in MA.load()["tuolumne"].toolchains
    assert G.COMPILE_S[MA.family_of("cce99")] == 30.0
    # the matrix: the gfx942 toolchains and the campaign orders
    assert T.GFX942_TOOLCHAINS[-1] == "cce99" and FE.TOOLCHAIN_ORDER[-1] == "cce99"
    assert "nvhpc99" in FR.REPORT_ORDER and "cce99" in R.ALL_TOOLCHAINS
    assert R.TC_NAME["cce99"] == "CCE 99" and R.TC_NAME["nvhpc99"] == "NVHPC 99.1"
    assert "nvhpc99" in T.NVIDIA_TOOLCHAINS
    # the site: cells, plans, versions, columns
    case = {"id": "x", "finding": "x.f90", "symptom": "wrong", "expect": "ok", "lang": "f90",
            "model": "omp", "affected": ["cce21"]}
    cells = M.cells("x", rows=[], cases=[case])
    assert {c.tc for c in cells} >= {"cce99", "nvhpc99"}
    assert any(c.tc == "cce99" and c.target == "mi300a-u" and c.state == "unknown" for c in cells)
    planned = {(p["tc"], p["machine"], p["mode"]) for p in M.plan(["x"], rows=[], cases=[case])}
    assert {("cce99", "tuolumne", "1"), ("cce99", "tuolumne", "0"), ("nvhpc99", "wingtip", "2")} <= planned
    # the fakes are the last release of their family: order = the family's other versions
    for fake, fam, ver in (("cce99", "cce", "99.0.0"), ("nvhpc99", "nvhpc", "99.1")):
        others = {v for f, v, _ in M.VERSIONS.values() if f == fam} - {ver}
        assert M.VERSIONS[fake] == (fam, ver, len(others))
    assert D.compilers({"pages": {}, "issues": []})["cce99"]["label"] == "CCE 99.0.0"
    gen = _gen()
    js = gen.site_js(reg)
    assert "'99.0.0': 'cce99'" in js and "'99.1': 'nvhpc99'" in js and "['nvhpc99', 'NVHPC 99.1']" in js
    # the lanes and the job scripts' table
    assert reg.of_lane("tuolumne")[-1] == "cce99" and reg.of_lane("wingtip")[-1] == "nvhpc99"
    sh = gen.shell_table(reg)
    assert 'TC_LANE_wingtip="nvhpc nvhpc269 nvhpc99"' in sh and "cce99" in sh
    assert "| `cce99` | cce | 99.0.0 | tuolumne |" in gen.docs_table(reg)
    # the header parser
    ms = H.mentions("CCE 99 runs it; NVHPC 99.1 rejects it; cce99 too")
    assert ("cce", ("cce99",)) in {(m.family, m.tcs) for m in ms}
    assert ("nvhpc", ("nvhpc99",)) in {(m.family, m.tcs) for m in ms}


def test_a_release_without_canaries_is_refused_by_the_registry_check(fake_catalog):
    from offload.engine import canary
    canary.CANARIES = ROOT / "catalog" / "canaries.yaml"   # the committed ones: no fake entries
    problems = "\n".join(T.check_registry(fake_catalog))
    assert "cce99: no canaries" in problems and "nvhpc99: no canaries" in problems


def test_the_real_catalog_is_back_after_the_fake(tmp_path):
    assert "cce99" not in T.registry().toolchains and "cce99" not in T.TOOLCHAINS
    from offload.engine.site import matrix as M
    assert "cce99" not in M.VERSIONS


# ---- tools/regenerate.py --check on the committed data ------------------------------





def _tool():
    spec = importlib.util.spec_from_file_location(
        "_regen", ROOT / "tools" / "regenerate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_steps_are_listed_in_order(capsys):
    R = _tool()
    assert R.main(["--list"]) == 0
    names = [s[0] for s in R.STEPS]
    assert names.index("support-tables") < names.index("confirm-batch") \
        < names.index("witness")
    assert "confirm-batch" in capsys.readouterr().out


def test_a_missing_input_is_a_named_skip(tmp_path):
    R = _tool()
    with pytest.raises(R.Skip, match="missing"):
        R._need(ROOT / "results" / "no-such-file.jsonl")


@pytest.mark.needs_results("results/support_table.csv",
                           "results/confirm/batch_full.jsonl")
@pytest.mark.parametrize("name", [n for n, _ in _tool().CHECKS])
def test_committed_artifacts_are_current(name):
    R = _tool()
    res = R.run_checks([name], log=lambda s: None)
    stale = {k: v[1] for k, v in res.items() if v[0] == "stale"}
    assert not stale, stale


def test_a_stale_batch_is_reported(tmp_path, monkeypatch):
    """The batch's inputs stamp catches a rules change made
    without a batch rerun."""
    R = _tool()
    rules = tmp_path / "rules.yaml"
    rules.write_text("version: 1\n")
    monkeypatch.setattr(R, "BATCH_INPUTS", ("rules.yaml",))
    monkeypatch.setattr(R, "BATCH_GLOBS", ())
    monkeypatch.setattr(R, "ROOT", tmp_path)
    monkeypatch.setattr(R, "_need", lambda *p: None)
    stamp = tmp_path / "stamp.json"
    R.stamp_batch(stamp)
    assert R.check_batch(stamp) == []
    rules.write_text("version: 2\n")
    assert R.check_batch(stamp) and "made with other" in R.check_batch(stamp)[0]
    assert "no inputs stamp" in R.check_batch(tmp_path / "none.json")[0]


def test_the_ompvv_outputs_are_checked():
    """The omp_vv outputs have their own checks (the corpus pin
    and its index rows, the cross-check CSVs) and the batch's inputs hash
    covers the omp_vv baselines it ingests."""
    R = _tool()
    names = [n for n, _ in R.CHECKS]
    assert {"ompvv-corpus", "ompvv-compare"} <= set(names)
    assert names.index("ompvv-corpus") < names.index("ompvv-compare") \
        < names.index("triage")
    assert {"results/baseline.jsonl", "results/baseline_c.jsonl"} <= \
        set(R.BATCH_INPUTS)


def test_a_stale_ompvv_compare_csv_is_reported(tmp_path, monkeypatch):
    R = _tool()
    oc = R._tool("ompvv_compare")
    rows = [{"version": "52", "atom": "omp.directive.target",
             "toolchain": "afar", "mode": "headline", "xnack": 1,
             "ours": "correct_on_device", "suite_pass": 1, "suite_fail": 0,
             "narrow_pass": 1, "narrow_fail": 0, "flag": ""}]
    monkeypatch.setattr(R, "_need", lambda *p: None)
    monkeypatch.setattr(R, "_tool", lambda name: oc)
    monkeypatch.setattr(oc, "compare", lambda lang: (rows, [], {}, {}, []))
    paths = {}
    for lang in ("f90", "c"):
        p = tmp_path / f"{lang}.csv"
        p.write_text(oc.render_csv(rows), newline="")
        paths[lang] = (None, None, p)
    monkeypatch.setattr(oc, "PATHS", paths)
    assert R.check_ompvv_compare() == []
    paths["c"][2].write_text("version\n")
    assert R.check_ompvv_compare() == [str(paths["c"][2])]


def test_the_ompvv_corpus_pin_and_index_rows(tmp_path, monkeypatch):
    """The checked-out omp_vv commit is the pinned one and the committed
    index rows of omp_vv are those of that checkout."""
    from offload.engine import ompvv
    R = _tool()
    ic = R._tool("index_corpus")
    monkeypatch.setattr(R, "_need", lambda *p: None)
    monkeypatch.setattr(R, "_tool", lambda name: ic)
    rows = [{"repo": "omp_vv", "path": "tests/a.c", "lang": "c",
             "model": "omp", "kind": "run", "spec_dir": "",
             "n_directives": 1, "directives": "target"}]
    monkeypatch.setattr(ic, "index_repo", lambda repo: list(rows))
    index = tmp_path / "corpus_index.csv"
    index.write_text("repo,path,lang,model,kind,spec_dir,n_directives,"
                     "directives\nacc_vv,x.F90,fortran,acc,run,,1,data\n"
                     "omp_vv,tests/a.c,c,omp,run,,1,target\n")
    monkeypatch.setattr(R, "CORPUS_INDEX", index)
    monkeypatch.setattr(R, "_corpus_head", lambda repo: ompvv.UPSTREAM[
        "commit"])
    assert R.check_ompvv_corpus() == []
    monkeypatch.setattr(R, "_corpus_head", lambda repo: "d978684")
    assert any("not the pinned" in s for s in R.check_ompvv_corpus())
    monkeypatch.setattr(R, "_corpus_head", lambda repo: ompvv.UPSTREAM[
        "commit"])
    rows[0]["directives"] = "target;teams"
    assert [s.endswith("corpus_index.csv (omp_vv rows)")
            for s in R.check_ompvv_corpus()] == [True]


def test_the_pin_is_in_the_setup_document():
    from offload.engine import ompvv
    text = (ROOT / "docs" / "tooling" / "setup.md").read_text()
    row = next(ln for ln in text.splitlines()
               if ln.startswith("| corpus/omp_vv |"))
    assert ompvv.UPSTREAM["url"] in row
    assert ompvv.UPSTREAM["commit"][:8] in row
    assert f"checkout {ompvv.UPSTREAM['commit']}" in text


def test_the_widened_catalog_is_checked(tmp_path, monkeypatch):
    """The widened catalog's table (and its audit summaries) and
    its confirmer batch have their own checks;
    the widened batch's stamp covers the matrix and the expected values it
    reads besides the full batch's inputs."""
    R = _tool()
    names = [n for n, _ in R.CHECKS]
    assert names.index("widen-table") < names.index("widen-batch")
    steps = [s[0] for s in R.STEPS]
    assert steps.index("support-tables") < steps.index("widen-table") \
        < steps.index("confirm-batch") < steps.index("widen-batch")
    m = tmp_path / "matrix.jsonl"
    m.write_text("{}\n")
    monkeypatch.setattr(R, "WIDEN_BATCH_INPUTS", (m,))
    monkeypatch.setattr(R, "_need", lambda *p: None)
    stamp = tmp_path / "stamp.json"
    R.stamp_widen_batch(stamp)
    assert R.check_widen_batch(stamp) == []
    m.write_text("{\"x\": 1}\n")
    assert R.check_widen_batch(stamp)


def test_a_difference_no_finding_explains_yet_has_a_class_of_its_own():
    """A memory-mode or GPU difference that is measured but not yet reduced to a finding is
    `no_finding_yet` (shown, not counted); the classes that name a finding stay for those that
    have one, and every catalog entry of that class says why without naming a finding."""
    from offload.engine import report
    assert "no_finding_yet" in report.MODE_CLASSES and "no_finding_yet" in report.ARCH_CLASSES
    md = report.load_mode_differences()
    for e in (md.get("entries") or []) + (md.get("arch_entries") or []):
        if e["class"] == "no_finding_yet":
            assert not e.get("finding") and "No finding yet" in e["why"] or "none" in e["why"], e
