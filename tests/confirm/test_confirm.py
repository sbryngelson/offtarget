"""Tests of the confirmer: vendor claims, evidence collectors, machines and memory modes, the rulings registry, the decision rules and the independent legality witnesses."""


# ---- Vendor claims in one generic format (offload.engine.confirm.claims) --------------------------------

from pathlib import Path

import pytest
import yaml

from offload.engine.confirm import claims as CL

ROOT = Path(__file__).resolve().parent.parent.parent


def test_catalog_claims_convert():
    got = CL.from_catalog(ROOT / "catalog" / "omp" / "claims.yaml")
    assert got
    assert {c.vendor for c in got} <= {"AMD", "HPE", "NVIDIA"}  
    c = next(c for c in got if c.atom == "omp.directive.target_data")
    assert c.construct == "target data" and c.clause == ""
    assert c.url.startswith("http") and c.quote


def test_split_atom():
    assert CL.split_atom("omp.clause.map.to") == ("", "map.to")
    assert CL.split_atom("omp.directive.target_teams") == ("target teams", "")
    assert CL.split_atom("acc.clause.copyin") == ("", "copyin")


def test_round_trip_and_an_nvidia_shaped_claim(tmp_path):
    nv = CL.VendorClaim(vendor="NVIDIA", product="HPC SDK (nvfortran)",
                        version="25.1", source="nvhpc-openmp-guide",
                        url="https://docs.nvidia.com/hpc-sdk/",
                        language="Fortran", claim="unsupported",
                        quote="The requires directive is not supported.",
                        page="12", construct="requires")
    p = tmp_path / "c.yaml"
    CL.dump([nv], p)
    assert CL.load(p) == [nv]


def test_incomplete_claim_is_refused():
    with pytest.raises(ValueError):
        CL.VendorClaim(vendor="X", product="", version="1", source="s",
                       url="u", language="C", claim="supported", quote="q",
                       construct="target")
    with pytest.raises(ValueError):
        CL.VendorClaim(vendor="X", product="p", version="1", source="s",
                       url="u", language="C", claim="maybe", quote="q",
                       construct="target")


# --- The quote check -------------------------------------------------------

MAN = """NAME
       intro_OpenMP - Introduction

DESCRIPTION
       CCE supports full OpenMP 5.0.  The following OpenMP 5.1 features are supported:

       · thread_limit clause on target construct (C/C++ only)

       · indirect clause

       The following OpenMP 6.0 features are supported:

       · support for self mapping via self modifier

   Limitations
       · The device clause is not supported.  The other mechanisms are supported.
"""


def test_text_doc_bullets_under_their_header():
    d = CL.TextDoc(MAN)
    h51 = "The following OpenMP 5.1 features are supported:"
    assert d.verify(f"{h51} ... indirect clause") == "DESCRIPTION"
    # a bullet is matched whole: the C/C++-only bullet is not the claim
    # "thread_limit clause on target construct"
    assert d.verify(f"{h51} ... thread_limit clause on target construct") \
        is None
    assert d.verify(f"{h51} ... thread_limit clause on target construct "
                    "(C/C++ only)")
    # the bullet must be under the header the quote names
    assert d.verify(f"{h51} ... support for self mapping via self modifier") \
        is None
    assert d.verify("The following OpenMP 6.0 features are supported: ... "
                    "support for self mapping via self modifier")
    # a sentence of a bullet, with its section
    assert d.verify("The device clause is not supported.") == \
        "DESCRIPTION > Limitations"
    assert d.verify("The device clause is supported.") is None


def test_text_doc_release_notes_nesting():
    notes = (" - Added or extended support for the following OpenMP "
             "features:\n   [6.0]\n   - groupprivate directive\n"
             "   [5.2]\n   - Fortran: new linear clause syntax\n")
    d = CL.TextDoc(notes)
    assert d.verify("[6.0] ... groupprivate directive")
    assert d.verify("[6.0] ... Fortran: new linear clause syntax") is None
    assert d.verify("[5.2] ... Fortran: new linear clause syntax")


def test_table_doc_rows_and_group_carry_over(tmp_path):
    p = tmp_path / "t.md"
    p.write_text(
        "## OpenMP 5.1 Implementation Details\n\n"
        "| Category | Feature | Status | Reviews |\n| --- | --- | --- | --- |\n"
        "| device | 'present' map type modifier | {good}`done` | D1 |\n"
        "| device | has_device_addr clause | {none}`unclaimed` | |\n\n"
        "## OpenMP 6.0 Implementation Details\n\n"
        "| Feature | C/C++ Status | Fortran Status | Reviews |\n"
        "| --- | --- | --- | --- |\n"
        "| Self maps | {part}`partial` | {none}`unclaimed` | |\n")
    d = CL.TableDoc(p)
    assert d.verify("device | 'present' map type modifier | done; "
                    "has_device_addr clause | unclaimed")
    assert d.verify("device | has_device_addr clause | done") is None
    assert d.verify("OpenMP 6.0 | Self maps | partial") == \
        "OpenMP 6.0 Implementation Details"
    # the C/C++ column is the status
    assert d.verify("OpenMP 6.0 | Self maps | unclaimed") is None


def test_flang_csv_table():
    d = CL.TableDoc(ROOT / "data" / "index" / "claims" /
                    "amdflang_afar_openmp_status.csv")
    assert d.verify("OpenMP 4.0 | target data construct | good")
    assert d.verify("OpenMP 4.0 | target data construct | none") is None


def _fake_docs(tmp_path, monkeypatch):
    for v, extra in (("19", ""), ("21", "· enter clause (Fortran only)\n")):
        (tmp_path / f"cce{v}.txt").write_text(
            "DESCRIPTION\n       The following OpenMP 5.2 features are "
            "supported:\n\n       · masked construct with filter clause\n"
            + "       " + extra)
    data = {"products": {"cce19": {"vendor": "HPE", "product": "CCE",
                                   "version": "19.0.0"},
                         "cce21": {"vendor": "HPE", "product": "CCE",
                                   "version": "21.0.3"}},
            "documents": {"man": {"vendor": "HPE", "title": "intro_openmp(7)",
                                  "url": "https://x", "format": "text",
                                  "editions": {
                "cce19": {"path": str(tmp_path / "cce19.txt"), "version": "19"},
                "cce21": {"path": str(tmp_path / "cce21.txt"),
                          "version": "21"}}}}}
    monkeypatch.setattr(CL, "_vendor_data", lambda: data)
    CL._reader.cache_clear()


def test_ingest_records_a_claim_only_for_editions_with_the_quote(
        tmp_path, monkeypatch):
    _fake_docs(tmp_path, monkeypatch)
    m = tmp_path / "map.yaml"
    m.write_text(yaml.safe_dump({"claims": [
        {"source": "man", "claim": "supported", "language": "Fortran",
         "spec_version": "5.2",
         "quote": "The following OpenMP 5.2 features are supported: ... "
                  "enter clause (Fortran only)",
         "atoms": ["omp.clause.enter"]},
        {"source": "man", "claim": "supported", "language": "Fortran",
         "quote": "not in any edition", "atoms": ["omp.clause.link"]}]}))
    rep = CL.ingest((m,))
    assert [(c.toolchain, c.atom) for c in rep.claims] == \
        [("cce21", "omp.clause.enter")]
    c = rep.claims[0]
    assert c.version == "21.0.3" and c.spec_version == "5.2"
    assert "DESCRIPTION" in c.page and c.doc.endswith("cce21.txt")
    assert any("not in any edition" in p for p in rep.problems)
    assert any(t == "cce19" for _, t in rep.absent)


def test_claim_language():
    c = CL.VendorClaim("HPE", "CCE", "21", "s", "u", "Fortran and C/C++",
                       "supported", "q", atom="omp.clause.map")
    assert c.covers_language("c") and c.covers_language("f90")
    f = CL.VendorClaim("HPE", "CCE", "21", "s", "u", "Fortran",
                       "supported", "q", atom="omp.clause.map")
    assert not f.covers_language("c") and f.covers_language("f90")
    x = CL.VendorClaim("AMD", "AFAR", "24", "s", "u", "C/C++", "supported",
                       "q", atom="omp.clause.map", cross_language=True)
    assert x.covers_language("f90")


def test_committed_mapping_quotes_are_all_found():
    """Every quote of the committed mapping occurs in some edition of its
    document, and the generic file is the ingest of the committed
    mapping."""
    rep = CL.ingest()
    assert rep.problems == []
    assert CL.load(CL.GENERIC) == rep.claims


def test_committed_claims_per_cce_release():
    """The CCE 20/21 man pages claim OpenMP 6.0 self maps; CCE 19's does
    not; the CCE 19 page's release-level sentence is not in CCE 20's."""
    got = CL.generic()
    self_maps = {c.toolchain for c in got if c.atom == "omp.clause.map.self"
                 and c.vendor == "HPE" and c.claim == "supported"}
    assert self_maps == {"cce20", "cce21"}
    assert all(c.spec_version == "6.0" for c in got
               if c.atom == "omp.clause.map.self" and c.vendor == "HPE")
    gen = {c.toolchain for c in got if c.general and c.vendor == "HPE"
           and "and partial OpenMP 5.1 and 5.2." in c.quote}
    assert gen == {"cce19"}
    assert {c.source for c in got} >= {
        "hpe-cce-intro-openmp", "hpe-cce-intro-openacc",
        "olcf-frontier-guide", "rocm-openmp-support",
        "rocm-clang-openmp-status", "amdclang-afar-openmp-support",
        "afar-flang-openmp-status", "afar-flang-lowering-todo",
        "hpe-cce-release-notes"}


def test_table_claims_take_the_spec_version_of_their_table():
    got = [c for c in CL.generic() if c.source == "rocm-clang-openmp-status"
           and c.atom == "omp.clause.map.present"]
    assert got and {c.spec_version for c in got} == {"5.1"}


def test_release_level_claims_of_default_private_are_fortran_only():
    """C/C++ gained default(private/firstprivate) in 5.1, so a
    'full OpenMP 4.5/5.0' sentence covers them for Fortran only."""
    got = [c for c in CL.generic() if c.general and c.atom in (
        "omp.clause.default.private", "omp.clause.default.firstprivate")]
    assert got and all(not c.covers_language("c") for c in got)
    assert all(c.covers_language("f90") for c in got)


def test_nvhpc_claims_quote_the_25_11_user_guide():
    """NVIDIA's claims come from the HPC Compilers User's Guide of
    the installed release (25.11), every quote found in its snapshot."""
    got = [c for c in CL.load(CL.GENERIC) if c.toolchain == "nvhpc"]
    assert got and {c.vendor for c in got} == {"NVIDIA"}
    assert {c.version for c in got} == {"25.11"}
    assert all("/archive/25.11/" in c.url for c in got)
    lin = next(c for c in got if c.atom == "omp.clause.linear")
    assert lin.claim == "unsupported" and \
        lin.quote == "The linear clause is not supported"
    usm = [c for c in got if c.atom == "omp.clause.unified_shared_memory"]
    assert {(c.claim, c.form) for c in usm} == {("partial", "accepted")}
    assert next(c for c in got if c.atom == "acc.clause.link").claim == \
        "unsupported"


# ---- Each evidence collector with a fake runner and a small stored record ---------------------------------------

import where
import json

from offload.engine.confirm import collectors as C
from offload.engine.confirm import execute as X
from offload.engine.confirm import ingest as I
from offload.engine.confirm import machines as M
from offload.engine.confirm import model as MO
from offload.engine.confirm.model import Case, ProgramRef, Provenance, Run
from offload.engine.confirm.store import Store
ROOT_DIR = Path(__file__).resolve().parent.parent.parent

REF = ProgramRef("catalog", "omp52-clause-x", "f90", 52, text="program x\n"
                 "end program x\n", expected="check=pass")


def row(tc, mode, outcome="correct_on_device", value="check=pass",
        ident="omp52-clause-x", flaky=False):
    from offload.engine.toolchains import TOOLCHAINS
    return I.Row("catalog", ident, tc, TOOLCHAINS[tc].arch, mode, outcome,
                 "", value, 0, flaky, 3, True, f"results/x.jsonl:{tc}")


class FakeRunner:
    machine = None

    def __init__(self, outcome="correct_on_device", value="check=pass"):
        self.calls = []
        self.outcome, self.value = outcome, value

    def run(self, ref, toolchain, mode, opt="-O2", offload="mandatory",
            repeats=3):
        self.calls.append((toolchain, mode, opt, offload))
        return ([Run(self.outcome, self.value, 0)] * repeats,
                Provenance(command="fake", host="node1", date="d",
                           modules=("cce/21.0.3",), origin="run"))


def case(tc="cce21", mode="unified", outcome="wrong_answer"):
    from offload.engine.toolchains import TOOLCHAINS
    t = TOOLCHAINS[tc]
    return Case(REF, tc, t.machine, t.arch, mode, outcome, "check_fail",
                "check=fail", 0)


def ctx(rows=(), runner=None, store=None):
    return C.Context(I.Index(rows), store or Store(None), runner=runner,
                     allow_run=runner is not None)


def test_other_toolchains_from_stored_rows_without_running():
    run = FakeRunner()
    c = ctx([row("afar", "unified"), row("cce19", "unified",
                                         "wrong_answer", "check=fail"),
             row("afar", "copy")], run)
    evs = C.COLLECTORS["other_toolchains"].collect(case(), c)
    got = {(e.toolchain, e.mode, e.value) for e in evs}
    assert ("afar", "unified", "check=pass") in got
    assert ("cce19", "unified", "check=fail") in got
    assert all(e.provenance.origin.startswith("results/") for e in evs
               if e.toolchain in ("afar", "cce19"))
    # cce20 has no stored row: it is run (and the regression-only
    # toolchain cce21_4 is never a column)
    assert ("cce20", "unified", "-O2", "mandatory") in run.calls
    assert not any(t == "cce21_4" for t, *_ in run.calls)


def test_offline_context_never_runs():
    c = ctx([row("afar", "unified")])
    evs = C.COLLECTORS["other_toolchains"].collect(case(), c)
    assert {e.toolchain for e in evs} == {"afar"}


def test_other_mode_and_single_mode_machine():
    c = ctx([row("cce21", "copy")])
    evs = C.COLLECTORS["other_mode"].collect(case(), c)
    assert [(e.toolchain, e.mode) for e in evs] == [("cce21", "copy")]
    g = case("cce21_g90", "copy")
    evs = C.COLLECTORS["other_mode"].collect(g, ctx())
    assert evs[0].status == "not_applicable"
    assert "only the copy mode" in evs[0].detail


def test_other_arch_twins():
    c = ctx([row("cce21_g90", "copy")])
    evs = C.COLLECTORS["other_arch"].collect(case(mode="copy"), c)
    assert [(e.toolchain, e.arch) for e in evs] == [("cce21_g90", "gfx90a")]
    # the regression toolchain has no twin: not applicable
    evs = C.COLLECTORS["other_arch"].collect(case("cce21_4"), ctx())
    assert evs[0].status == "not_applicable"


def test_port_rows():
    c = ctx([row("afar", "unified", ident="omp52-c-clause-x")])
    evs = C.COLLECTORS["port"].collect(case(), c)
    assert evs[0].variant == "port:omp52-c-clause-x"


def test_repeats_opt0_host_run_use_the_runner_and_the_store(tmp_path):
    run = FakeRunner("wrong_answer", "check=fail")
    store = Store(tmp_path / "ev.jsonl")
    c = ctx(runner=run, store=store)
    e = C.COLLECTORS["repeats"].collect(case(), c)[0]
    assert len(e.runs) == 3 and e.provenance.host == "node1"
    assert e.provenance.modules == ("cce/21.0.3",)
    C.COLLECTORS["opt0"].collect(case(), c)
    assert ("cce21", "unified", "-O0", "mandatory") in run.calls
    C.COLLECTORS["host_run"].collect(case(), c)
    assert ("cce21", "unified", "-O2", "disabled") in run.calls
    assert ("afar", "unified", "-O2", "disabled") in run.calls
    n = len(run.calls)
    # a second confirmer reuses the stored evidence: no new runs
    c2 = ctx(runner=run, store=Store(tmp_path / "ev.jsonl"))
    C.COLLECTORS["repeats"].collect(case(), c2)
    C.COLLECTORS["opt0"].collect(case(), c2)
    assert len(run.calls) == n


def test_model_and_derivation():
    m = C.COLLECTORS["model"].collect(case(), ctx())[0]
    assert m.value == "check=pass"
    ref = ProgramRef("catalog", "x", text="! derivation (check=pass): 5.2 "
                     "§1 p.1 says so\nprogram x\nend program x\n")
    d = C.COLLECTORS["derivation"].collect(
        Case(ref, "afar", "tuolumne", "gfx942", "unified", "wrong_answer"),
        ctx())[0]
    assert d.value == "check=pass"


def test_metamorphic_runs_rewrites(monkeypatch):
    from offload.engine import transforms as T
    monkeypatch.setattr(T, "variants", lambda src, v: {
        "split_combined": src + "! v1\n", "if_false": T.NotApplicable("x")})
    run = FakeRunner()
    evs = C.COLLECTORS["metamorphic"].collect(case(), ctx(runner=run))
    assert {e.variant for e in evs} == {"split_combined"}
    assert {t for t, *_ in run.calls} == {"cce21", "afar"}


def test_collectors_ordered_cheapest_first():
    names = [c.name for c in C.ordered(["metamorphic", "elision",
                                        "other_toolchains", "repeats"])]
    assert names == ["other_toolchains", "elision", "repeats", "metamorphic"]


def test_outcome_mapping_of_every_format():
    assert MO.outcome_of_result("rejected", "ice: x") == "ice"
    assert MO.outcome_of_result("wrong_answer", "crash: SIGSEGV; without "
                                "mandatory: x") == "crash"
    assert MO.outcome_of_result("wrong_answer", "timeout") == "timeout"
    assert MO.outcome_of_result("wrong_answer", "exit_status: 1") == \
        "run_error"
    assert MO.outcome_of_result("harness_error", "compile_timeout") == \
        "timeout"
    assert MO.outcome_of_baseline({"status": "fail", "stage": "compile",
                                   "reason": "ice: x"}) == "ice"
    assert MO.outcome_of_baseline({"status": "fail", "stage": "run",
                                   "reason": "crash: SIGABRT"}) == "crash"
    assert MO.outcome_of_fuzz("wrong_code") == "wrong_answer"
    assert MO.outcome_of_fuzz("run_error", "crash: SIGABRT") == "crash"


def test_ingest_maps_rows_to_modes(tmp_path):
    p = tmp_path / "matrix.jsonl"
    rows = [dict(program_id="omp52-clause-x", toolchain="cce21", xnack=0,
                 outcome="wrong_answer", reason="check_fail: ran_on_host=0 "
                 "check=fail", stdout="RESULT ran_on_host=0 check=fail\n",
                 flaky=False, legal=True),
            dict(program_id="omp52-clause-x", toolchain="afar_g90",
                 xnack=0, outcome="correct_on_device", reason="",
                 stdout="RESULT ran_on_host=0 check=pass\n", flaky=False,
                 legal=True),
            # an MI300X row is a support-table cell only: the confirmer reads none
            dict(program_id="omp52-clause-x", toolchain="afar_mi300x",
                 xnack=0, outcome="wrong_answer", reason="check_fail: x",
                 stdout="RESULT ran_on_host=0 check=fail\n", flaky=False,
                 legal=True)]
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    got = I.load_rows(p)
    assert [(r.toolchain, r.arch, r.mode, r.value) for r in got] == [
        ("cce21", "gfx942", "copy", "check=fail"),
        ("afar_g90", "gfx90a", "copy", "check=pass")]
    assert got[0].origin.endswith("matrix.jsonl:1")


def test_judge_generic_runs():
    assert X.judge(0, False, "RESULT checksum=7 ran_on_host=0\n",
                   "checksum=7").outcome == "correct_on_device"
    assert X.judge(0, False, "RESULT checksum=8 ran_on_host=0\n",
                   "checksum=7").outcome == "wrong_answer"
    assert X.judge(-11, False, "", "checksum=7").outcome == "crash"
    assert X.judge(None, True, "", "x").outcome == "timeout"
    assert X.judge(0, False, " base_cond bad=           0\n",
                   "base_cond bad= 0").outcome == "correct_on_device"
    assert X.judge(0, False, " base_cond bad=          63\n",
                   "base_cond bad= 0").outcome == "wrong_answer"
    assert X.judge(6, False, "", "error_termination").value == \
        "error_termination"


def test_remote_runner_command_and_parse():
    ti = M.load()["tioga"]
    calls = []

    def fake(argv, **kw):
        calls.append((argv, kw))

        class R:
            returncode = 0
            stdout = "noise\n" + json.dumps({
                "runs": [{"outcome": "correct_on_device", "value":
                          "check=pass", "ran_on_host": 0, "reason": "",
                          "stdout_tail": ""}],
                "provenance": {"command": "c", "host": "tioga39",
                               "date": "d", "modules": ["cce/21.0.3"],
                               "origin": "run"}})
            stderr = ""
        return R()
    rr = X.RemoteRunner(ti, runner=fake)
    runs, prov = rr.run(REF, "cce21_g90", "copy")
    argv, kw = calls[0]
    assert argv[:2] == ["ssh", "tio"]
    assert "cd /srv/vast/user/compliant" in argv[2]
    assert "flux run" in argv[2] and "/usr/tce/bin/python3" in argv[2]
    req = json.loads(kw["input"])
    assert req["toolchain"] == "cce21_g90" and req["mode"] == "copy"
    assert runs[0].outcome == "correct_on_device"
    assert prov.host == "tioga39" and prov.origin == "remote:tioga"


def test_serve_round_trip():
    out = X.serve(X.request_json(REF, "afar", "unified", "-O2", "mandatory",
                                 2), runner=FakeRunner())
    d = json.loads(out)
    assert len(d["runs"]) == 2 and d["provenance"]["host"] == "node1"


def test_elision_of_a_free_form_finding(monkeypatch):
    """A finding prints free text: its elided build's output (whitespace
    collapsed) is the elision value; stored under its own variant."""
    from offload.engine import expected as E
    seen = {}

    def fake(src, version=52, value=None, **kw):
        seen["value"] = value
        out = " base_cond bad=           0\n"
        return E.Evidence("elision", "value", value(out) if value else None)
    monkeypatch.setattr(E, "elision_evidence", fake)
    ref = ProgramRef("file", "f", "f90", 52, text="program f\nend\n",
                     expected="base_cond bad= 0")
    c = Case(ref, "cce21", "tuolumne", "gfx942", "unified", "wrong_answer")
    e = C.COLLECTORS["elision"].collect(c, ctx())[0]
    assert e.value == "base_cond bad= 0"
    assert e.variant == f"free-form@{C.ELISION_ANALYSIS}"
    assert seen["value"] is not None


def test_runner_failure_is_not_evidence(tmp_path):
    """A harness error is retried once, then reported
    as missing evidence, never stored, so a later call runs again."""
    run = FakeRunner("harness_error", None)
    store = Store(tmp_path / "ev.jsonl")
    c = ctx(runner=run, store=store)
    e = C.COLLECTORS["repeats"].collect(case(), c)[0]
    assert e.status == "no_value" and e.runs == ()
    assert "runner failure" in e.detail
    assert len(run.calls) == 2
    assert not (tmp_path / "ev.jsonl").exists()
    C.COLLECTORS["repeats"].collect(case(), c)
    assert len(run.calls) == 4


def test_stored_harness_error_row_is_not_a_cell():
    c = ctx([row("afar", "unified", "harness_error", None)])
    evs = C.COLLECTORS["other_toolchains"].collect(case(), c)
    afar = [e for e in evs if e.toolchain == "afar"][0]
    assert afar.runs == () and afar.status == "no_value"


def test_remote_runner_without_a_result_line():
    ti = M.load()["tioga"]

    def fake(argv, **kw):
        class R:
            returncode = 0
            stdout = "flux-job: something went wrong\n"
            stderr = ""
        return R()
    runs, _ = X.RemoteRunner(ti, runner=fake).run(REF, "cce21_g90", "copy")
    assert runs[0].outcome == "harness_error"


def test_derivation_from_port_and_registry():
    """RUL-PORT-DERIVATION (a recorded port inherits its Fortran program's
    derivation) and RUL-SPEC-READING-DERIVATION (a registry spec reading
    naming the program)."""
    from offload.engine.confirm import ports
    from offload.engine.confirm import programs as P
    cid = next(iter(ports.load()))
    ref = P.catalog_ref(cid)
    d = C.COLLECTORS["derivation"].collect(
        Case(ref, "afar", "tuolumne", "gfx942", "unified", "wrong_answer"),
        ctx())[0]
    assert d.status == "value" and "RUL-PORT-DERIVATION" in d.detail
    ref = P.catalog_ref("omp52-c-clause-map-delete")
    d = C.COLLECTORS["derivation"].collect(
        Case(ref, "cce21", "tuolumne", "gfx942", "copy", "wrong_answer"),
        ctx())[0]
    assert d.status == "value" and d.variant == "registry"
    assert "RUL-DELETE-REFCOUNT" in d.detail


def test_main_program_with_a_bare_end():
    """The elision parser read no main program when the
    file ends with a bare `end`."""
    from offload.engine import expected as E
    src = (ROOT_DIR / "data" / "findings" /
           "cce21-defaultmap-aggregate-flag.f90").read_text()
    ap = E.elision_applicability(src)
    assert "no end program" not in str(ap.why)


def test_triage_reaches_a_program_without_a_stored_record():
    """Omp50-clause-schedule is in the triage but not in
    results/expected/catalog.jsonl; its withdrawals still reach the
    confirmer."""
    import json as _j
    from offload.engine.confirm import programs as P
    from offload.engine.confirm.facts import Facts
    ref = P.catalog_ref("omp50-clause-schedule")
    c = Case(ref, "cce21", "tuolumne", "gfx942", "unified", "wrong_answer")
    e = C.COLLECTORS["expected_record"].collect(c, ctx())[0]
    d = _j.loads(e.detail)
    assert d["withdraw"] == ["afar", "cce19", "cce20", "cce21"] and \
        d["status"] == "triage_only"
    assert "no executed witness" in d["needs_human"]
    f = Facts(c, evidence={"expected_record": [e]})
    assert {w["toolchain"] for w in f.withdrawn()} == {"afar", "cce19",
                                                      "cce20", "cce21"}


def test_missing_evidence_is_listed():
    from offload.engine.confirm.facts import Facts
    run = FakeRunner("harness_error", None)
    c = ctx(runner=run)
    evs = C.COLLECTORS["other_toolchains"].collect(case(), c)
    f = Facts(case(), evidence={"other_toolchains": evs})
    miss = f.missing_evidence()
    assert {m["toolchain"] for m in miss} == {"afar", "cce19", "cce20"}
    assert "afar" in f.missing_families()


def test_an_unrecognised_compile_failure_is_read_from_its_output():
    """Spot check: omp_vv rows the baseline harness stored as
    "compile_failed: rc=1" (no recognised message) are compiler failures,
    not the environment's: a linker's undefined symbol is a rejection, a
    compiler crash or an internal verification failure an ICE; only an
    output with neither stays a harness error."""
    def row(err):
        return {"status": "fail", "stage": "compile",
                "reason": "compile_failed: rc=1", "stderr": err}
    assert MO.outcome_of_baseline(row(
        "ld.lld: error: undefined symbol: it\nclang: error: linker command "
        "failed")) == "rejected"
    assert MO.outcome_of_baseline(row(
        "ld.lld: error: undefined hidden symbol: omp_get_max_teams")) == \
        "rejected"
    assert MO.outcome_of_baseline(row(
        "clang: error: unable to execute command: Segmentation fault")) == \
        "ice"
    assert MO.outcome_of_baseline(row(
        "error: verification of lowering to FIR failed")) == "ice"
    assert MO.outcome_of_baseline(row(
        "error: failed to create the LLVM module")) == "ice"
    assert MO.outcome_of_baseline(row("module: command not found")) == \
        "harness_error"


def test_an_omp_vv_link_failure_carries_a_link_reason():
    """The row read as a rejection from its linker output gets
    the catalog rows' reason prefix (link_undefined_symbol), so tables do
    not call it a front-end rejection."""
    from offload.engine.confirm.ingest import row_of_baseline
    d = {"path": "tests/5.2/x.c", "toolchain": "afar", "xnack": 1,
         "status": "fail", "stage": "compile",
         "reason": "compile_failed: rc=1",
         "stderr": "ld.lld: error: undefined symbol: it\nclang: error: x"}
    r = row_of_baseline(d)
    assert r.outcome == "rejected"
    assert r.reason.startswith("link_undefined_symbol: ")
    assert "undefined symbol: it" in r.reason


# --- Fuzz campaigns split into run ids, stored elision -------------------------

def _fuzz_run(d, seed, xnack, cls="wrong_code", elision=None):
    from offload.engine.fuzz_exec import ProgramResult, TcResult
    d.mkdir(parents=True, exist_ok=True)
    pr = ProgramResult(seed, "fuzz-3", "ok", expected=7, base=["types"],
                       results={"cce21": TcResult("cce21", cls, "",
                                                  checksum=9, runs=[])})
    (d / "programs.jsonl").write_text(pr.to_json() + "\n")
    (d / "meta.json").write_text(json.dumps({"sessions": [
        {"run_id": d.name, "gen_version": "fuzz-3", "base": ["types"],
         "xnack": xnack}]}))
    if elision is not None:
        (d / "elision.jsonl").write_text(json.dumps(elision) + "\n")


def test_runs_of_one_campaign_share_the_program_ident(tmp_path, monkeypatch):
    """S1-NN (unified) and s1x0-NN (copy) are chunks of one
    campaign: the same seed is the same program, so a copy-mode cell finds
    its unified-mode cell (other_mode) under one ident."""
    _fuzz_run(tmp_path / "s1-00", 5, 1)
    _fuzz_run(tmp_path / "s1x0-00", 5, 0)
    _fuzz_run(tmp_path / "zz", 5, 0)
    monkeypatch.setattr(I, "campaigns", lambda: {"s1-00": "s1",
                                                 "s1x0-00": "s1"})
    a = I.load_rows(tmp_path / "s1-00" / "programs.jsonl")
    b = I.load_rows(tmp_path / "s1x0-00" / "programs.jsonl")
    z = I.load_rows(tmp_path / "zz" / "programs.jsonl")
    assert [(r.ident, r.mode) for r in a] == [("s1:5", "unified")]
    assert [(r.ident, r.mode) for r in b] == [("s1:5", "copy")]
    assert z[0].ident == "zz:5"           # not in a campaign: its run id
    assert a[0].extra["run"] == "s1-00" and b[0].extra["run"] == "s1x0-00"
    idx = I.Index(a + b)
    assert idx.get("fuzz", "s1:5", "cce21", "copy").extra["run"] == \
        "s1x0-00"
    assert idx.get("fuzz", "s1:5", "cce21", "unified").extra["run"] == \
        "s1-00"


@pytest.mark.needs_results("results/fuzz/s1/meta.json")
def test_campaign_table_names_runs_of_one_generator_configuration():
    """catalog/fuzz_campaigns.yaml: every run of a campaign exists with the
    same generator version and base groups (the same seed replays the
    same program)."""
    from offload.engine.confirm.ingest import RESULTS, campaign_runs
    for camp, runs in campaign_runs().items():
        confs = set()
        for r in runs:
            meta = json.loads((RESULTS / "fuzz" / r / "meta.json")
                              .read_text())["sessions"][0]
            confs.add((meta["gen_version"], tuple(meta["base"])))
        assert len(confs) == 1, (camp, confs)


def test_stored_elision_of_a_campaign_is_read(tmp_path, monkeypatch):
    """elision.jsonl (tools/campaigns/fuzz.py elide) is stored evidence: a value, or
    inapplicable with the reason; the collector does not run it again."""
    monkeypatch.setattr(I, "campaigns", lambda: {})
    _fuzz_run(tmp_path / "e1", 5, 1, elision={
        "seed": 5, "expected": 7, "applicable": True, "value": 7})
    _fuzz_run(tmp_path / "e2", 5, 1, elision={
        "seed": 5, "expected": 7, "applicable": False, "value": None,
        "why": "declare target variable"})
    r1 = I.load_rows(tmp_path / "e1" / "programs.jsonl")[0]
    r2 = I.load_rows(tmp_path / "e2" / "programs.jsonl")[0]
    assert r1.extra["elision"] == "checksum=7"
    assert r2.extra["elision"] == "inapplicable: declare target variable"
    ref = ProgramRef("fuzz", "e2:5", "f90", 52, text="program x\nend "
                     "program x\n", expected="checksum=7")
    ctx = C.Context(I.Index([r2]), Store(path=tmp_path / "ev.jsonl"))
    c = Case(ref, "cce21", "tuolumne", "gfx942", "unified", "wrong_answer",
             "", "checksum=9")
    ev = C.Elision().collect(c, ctx)[0]
    assert (ev.status, ev.value) == ("inapplicable", None)
    assert "declare target variable" in ev.detail
    ref1 = ProgramRef(**{**ref.__dict__, "ident": "e1:5"})
    ctx1 = C.Context(I.Index([r1]), Store(path=tmp_path / "ev1.jsonl"))
    ev = C.Elision().collect(Case(ref1, "cce21", "tuolumne", "gfx942",
                                  "unified", "wrong_answer", "",
                                  "checksum=9"), ctx1)[0]
    assert (ev.status, ev.value) == ("value", "checksum=7")


def test_shard_store_reads_the_main_store_and_writes_its_own(tmp_path):
    """A batch shard (one process of many on flux) reads the main
    evidence store and appends only to its own file (merged afterwards)."""
    main, shard = tmp_path / "ev.jsonl", tmp_path / "ev.shard1.jsonl"
    run = FakeRunner("wrong_answer", "check=fail")
    C.COLLECTORS["repeats"].collect(case(), ctx(runner=run,
                                                store=Store(main)))
    n = len(run.calls)
    s = Store(shard, also_read=(main,))
    C.COLLECTORS["repeats"].collect(case(), ctx(runner=run, store=s))
    assert len(run.calls) == n            # reused from the main store
    C.COLLECTORS["opt0"].collect(case(), ctx(runner=run, store=s))
    assert len(run.calls) == n + 1
    assert len(main.read_text().splitlines()) == 1
    assert len(shard.read_text().splitlines()) == 1


def test_batch_shards_partition_programs():
    """Every toolchain and mode of one program fall in the same shard."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "confirm_tool", ROOT_DIR / "tools" / "confirm.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    ids = [f"s1:{k}" for k in range(200)]
    got = [[i for i in ids if mod.in_shard(i, k, 7)] for k in range(7)]
    assert sorted(sum(got, [])) == sorted(ids)
    assert all(got)


def test_metamorphic_partner_is_a_family_member_that_ran_the_program(
        monkeypatch):
    """The other family's toolchain for the metamorphic runs is
    one whose stored cell of the program ran correctly in the case's mode
    (CCE 19/20 reject most s1 programs, so the first CCE toolchain is no
    partner); without one, the first of the family."""
    from offload.engine import transforms as T
    monkeypatch.setattr(T, "variants", lambda src, v: {
        "split_combined": src + "! v1\n"})
    run = FakeRunner()
    rows = [row("cce19", "unified", "rejected", None),
            row("cce20", "unified", "wrong_answer", "check=fail"),
            row("cce21", "unified")]
    C.COLLECTORS["metamorphic"].collect(case("afar"), ctx(rows, run))
    assert {t for t, *_ in run.calls} == {"afar", "cce21"}
    run = FakeRunner()
    C.COLLECTORS["metamorphic"].collect(case("afar"), ctx(rows[:1], run))
    assert {t for t, *_ in run.calls} == {"afar", "cce19"}


def test_merged_chunks_are_read_once(tmp_path):
    """A campaign directory merged from chunks (tools/campaigns/fuzz.py merge)
    replaces them in the stored index."""
    for name in ("s1-00", "s1-01", "zz"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "programs.jsonl").write_text("")
    (tmp_path / "s1").mkdir()
    (tmp_path / "s1" / "programs.jsonl").write_text("")
    (tmp_path / "s1" / "meta.json").write_text(json.dumps(
        {"merged_from": ["s1-00", "s1-01"], "sessions": []}))
    assert [p.parent.name for p in I.fuzz_files(tmp_path)] == ["s1", "zz"]


# --- Object names of any suffix; build flags of a reproducer --------

@pytest.mark.parametrize("names,objs", [
    (["modA.F90", "main.F90"], ["modA.o", "main.o"]),
    (["a.f", "b.F"], ["a.o", "b.o"]),
    (["k.cpp", "m.c"], ["k.o", "m.o"]),
    (["st.h", "k.c", "main.c"], ["k.o", "main.o"]),
    (["defs.inc", "a.f90"], ["a.o"]),
    (["x.f90", "x.c"], ["x.o", "x_1.o"]),
    (["noext", "b.f90"], ["noext.o", "b.o"]),
])
def test_object_names_for_any_suffix(names, objs):
    """`-c x.F90 -o x.F90` overwrote the source; every
    suffix gets its own object name, and headers are not compiled."""
    from offload.engine import harness
    pairs = harness.object_names(names)
    assert [o for _, o in pairs] == objs
    assert all(o != f for f, o in pairs)
    script = X._compile_script(MO_TC(), names, "prog.out", "-O2", "/tmp/x")
    for f, o in pairs:
        assert f"-c {f} -o {o}" in script
    for n in names:
        if n.endswith((".h", ".inc")):
            assert f"-c {n}" not in script


def MO_TC():
    from offload.engine.toolchains import Toolchain
    return Toolchain("afar", "", "FC", cc="CC")


@pytest.mark.parametrize("suffix", ["F90", "f", "cpp"])
def test_a_set_of_any_suffix_compiles_without_overwriting(tmp_path, suffix):
    """The set is compiled by a fake compiler that refuses to write over
    an input; the sources survive the build."""
    from offload.engine.toolchains import Toolchain
    fc = tmp_path / "fc.sh"
    fc.write_text("#!/bin/bash\nout=\"\"; src=\"\"\n"
                  "for a in \"$@\"; do [ \"$p\" = -o ] && out=$a; "
                  "[ \"$p\" = -c ] && src=$a; p=$a; done\n"
                  "[ -n \"$src\" ] && [ \"$src\" = \"$out\" ] && exit 9\n"
                  "echo obj > \"$out\"; [ -z \"$src\" ] && chmod +x \"$out\"\n"
                  "exit 0\n")
    fc.chmod(0o755)
    tc = Toolchain("afar", "", str(fc), cc=str(fc))
    text = (f"!@file a.{suffix}\nprogram a\nend\n!@file b.{suffix}\n"
            "subroutine b\nend\n") if suffix != "cpp" else (
        "//@file a.cpp\nint main(){}\n//@file b.cpp\nvoid b(){}\n")
    bad, exe, out = X.compile_files(tc, text, "f90" if suffix != "cpp"
                                    else "c", tmp_path, "-O2")
    assert bad is None, (bad, out)
    assert (tmp_path / f"a.{suffix}").read_text().strip() != "obj"


def test_build_flags_of_a_reproducer_reach_the_build(tmp_path):
    from offload.engine.confirm import programs as P
    f = tmp_path / "r.c"
    f.write_text("// build flags: -O2 -flto\n// expected: sum= 1\n"
                 "int main(void){return 0;}\n")
    ref = P.file_ref([str(f)])
    assert ref.flags == "-O2 -flto" and ref.expected == "sum= 1"
    assert X.build_opt("-O2", ref.flags) == "-O2 -flto"
    assert X.build_opt("-O0", ref.flags) == "-O0 -flto"   # the -O0 control
    assert X.build_opt("-O2", "") == "-O2"
    assert X.build_opt("-O2", "-O3") == "-O3"
    assert "flags" not in P.file_ref([str(tmp_path / "r.c")]).__class__(
        "file", "x").to_dict()
    assert ref.to_dict()["flags"] == "-O2 -flto"


def test_an_nvhpc_cell_is_a_family_witness_for_an_amd_case():
    """Witnesses come from another machine: an AMD case in copy
    mode reads wingtip's stored NVHPC cell of the same program (never in
    unified mode, which wingtip has not)."""
    from offload.engine.confirm.facts import Facts
    from offload.engine.confirm.legality import Legality
    ref = ProgramRef("catalog", "omp52-x", text="program p\nend\n")
    c = Case(ref, "cce21", "tuolumne", "gfx942", "copy", "rejected",
             "diagnostic: ftn-1 ftn: ERROR x")
    assert {"nvhpc", "nvhpc269"} <= set(C.compared_toolchains(c))
    u = Case(ref, "cce21", "tuolumne", "gfx942", "unified", "rejected",
             "diagnostic: ftn-1 ftn: ERROR x")
    assert not {"nvhpc", "nvhpc269"} & set(C.compared_toolchains(u))
    rows = [I.Row("catalog", "omp52-x", t, "gfx942", "copy", "rejected",
                  "diagnostic: ftn-1 ftn: ERROR x") for t in
            ("cce19", "cce20", "afar")] + [
        I.Row("catalog", "omp52-x", "nvhpc", "sm_80", "copy",
              "correct_on_device", "ran_on_host=0 check=pass",
              "check=pass", 0)]
    ctx = C.Context(I.Index(rows), Store(None))
    ev = C.COLLECTORS["other_toolchains"].collect(c, ctx)
    assert any(e.toolchain == "nvhpc" for e in ev)
    f = Facts(c, legality=Legality("legal", "t"))
    f.evidence["other_toolchains"] = ev
    assert f.other_family_compiles()


def test_stored_rows_are_read_with_the_current_message_tables():
    """A stored NVHPC rejection followed by the front end's crash
    (fort2 TERMINATED by signal 11) is read as an ICE, so the atomic
    finding links its cells by the crash."""
    from pathlib import Path as _P
    msg = where.message("nvhpc_acc_fort2_crash").read_text().split(
        "==== verbatim output below ====\n", 1)[1]
    d = {"program_id": "acc34-clause-gang", "toolchain": "nvhpc",
         "xnack": 0, "outcome": "rejected",
         "reason": "diagnostic: NVFORTRAN-S-0155-Invalid atomic update "
                   "expression  (<tmpdir>/acc34-clause-gang.f90: 33)",
         "stderr": "--- compile (rc=2) ---\n" + msg, "stdout": ""}
    r = I.row_of_result(d)
    assert r.outcome == "ice" and "TERMINATED by signal 11" in r.reason
    assert r.extra["reclassified_from"]["outcome"] == "rejected"
    assert r.extra["reclassified_from"]["reason"].startswith("diagnostic")
    from offload.engine.confirm import findings as FI
    hits = FI.dedupe("nvhpc", "f90", r.outcome, r.reason, "",
                     "acc34-clause-gang", "copy", arch="sm_80")
    assert hits and hits[0]["file"].endswith(
        "nvhpc-acc-atomic-update-sum-fort2-crash.f90")


def _family_facts(case_outcome, nv_outcome, nv_reason="compiled and ran"):
    from offload.engine.confirm.facts import Facts
    from offload.engine.confirm.legality import Legality
    ref = ProgramRef("catalog", "omp52-x", text="program p\nend\n")
    c = Case(ref, "cce21", "tuolumne", "gfx942", "copy", case_outcome,
             "diagnostic: x" if case_outcome == "rejected" else "check_fail")
    rows = [I.Row("catalog", "omp52-x", "nvhpc", "sm_80", "copy",
                  nv_outcome, nv_reason, None, 0)]
    ctx = C.Context(I.Index(rows), Store(None))
    f = Facts(c, legality=Legality("legal", "t"))
    f.evidence["other_toolchains"] = C.COLLECTORS[
        "other_toolchains"].collect(c, ctx)
    return f


@pytest.mark.parametrize("nv_outcome,compile_witness,run_witness", [
    ("correct_on_device", True, True),
    ("unobservable", True, False),
    ("wrong_answer", True, False),
    ("crash", True, False),
    ("accepted_ignored", True, False),
    ("rejected", False, False),
    ("ice", False, False)])
def test_the_family_witness_depends_on_the_phase(nv_outcome,
                                                 compile_witness,
                                                 run_witness):
    """For a compile-phase
    outcome the witness is another family whose front end accepts and
    compiles the program, whatever happens when it runs; for a run-time
    outcome it must be an observable correct run."""
    f = _family_facts("rejected", nv_outcome)
    assert f.other_family_compiles() is compile_witness
    (e,) = [x for x in f.cells(("other_toolchains",))]
    assert f.family_witness(e, "compile") is compile_witness
    assert f.family_witness(e, "run") is run_witness
    g = _family_facts("fell_back_to_host", nv_outcome)
    assert g.other_family_on_device() is run_witness
    # an ignored note is no observable run either
    h = _family_facts("fell_back_to_host", "correct_on_device",
                      "ran; note: clause ignored")
    assert not h.other_family_on_device()


# ---- Machines and memory modes (offload.engine.confirm.machines) and job scripts ---------------------------------


from offload.engine.confirm import jobs as J

NVIDIA = {"version": 1, "machines": {"gpubox": {
    "arch": "sm_90", "device": "NVIDIA H100", "access": "local",
    "scheduler": {"kind": "slurm", "queue": "gpu", "max_minutes": 30},
    "headline_mode": "copy",
    "modes": {"copy": {"env": {}, "row_key": 0}}}}}


def test_committed_machines():
    ms = M.load()
    tu, ti = ms["tuolumne"], ms["tioga"]
    assert tu.arch == "gfx942" and ti.arch == "gfx90a"
    assert tu.modes == ("unified", "copy") and ti.modes == ("copy",)
    assert tu.headline_mode == "unified" and ti.headline_mode == "copy"
    assert tu.env("unified") == {"HSA_XNACK": "1"}
    assert tu.row_key("copy") == 0
    assert ti.access["ssh"] == "tio"
    assert ti.access["root"] == "/srv/vast/user/compliant"


def test_mode_from_row_and_not_applicable():
    tu = M.load()["tuolumne"]
    assert tu.mode_of_row_key(1) == "unified"
    assert tu.mode_of_row_key(0) == "copy"
    ti = M.load()["tioga"]
    assert not ti.has("unified")
    with pytest.raises(M.NotApplicable):
        ti.env("unified")


def test_machine_of_toolchain():
    assert M.machine_of("cce21").name == "tuolumne"
    assert M.machine_of("afar_g90").name == "tioga"
    assert M.machine_of("cce21_4").name == "tuolumne"


def test_single_mode_machine_from_data():
    ms = M.load(data=NVIDIA)
    g = ms["gpubox"]
    assert g.modes == ("copy",) and g.other_modes("copy") == ()
    assert g.scheduler["kind"] == "slurm"
    assert g.mode_of_row_key(0) == "copy"


def test_bad_machine_data_is_refused():
    bad = {"version": 1, "machines": {"x": {
        "arch": "a", "access": "local", "scheduler": {"kind": "flux"},
        "headline_mode": "unified", "modes": {"copy": {"env": {},
                                                       "row_key": 0}}}}}
    with pytest.raises(ValueError):
        M.load(data=bad)
    bad["machines"]["x"]["headline_mode"] = "copy"
    bad["machines"]["x"]["modes"]["odd"] = {"env": {}, "row_key": 1}
    with pytest.raises(ValueError):
        M.load(data=bad)


class FakeRunner_3:
    def __init__(self, out="f3fiN7Kxq2Md\n"):
        self.calls, self.out = [], out

    def __call__(self, argv, **kw):
        self.calls.append(argv)

        class R:
            returncode = 0
            stdout = self.out
            stderr = ""
        return R()


def test_flux_submission_command():
    run = FakeRunner_3()
    s = J.FluxScheduler(runner=run)
    spec = J.JobSpec(script="tools/jobs/run_regress.sh", minutes=60,
                     queue="pdebug", env={"JOB": "matrix", "X": "1"},
                     output="results/x.log", attrs={"thp": "always"})
    jid = s.submit(spec)
    assert jid == "f3fiN7Kxq2Md"
    argv = run.calls[0]
    assert argv[:2] == ["flux", "batch"]
    assert "-q" in argv and argv[argv.index("-q") + 1] == "pdebug"
    assert "--setattr=thp=always" in argv
    assert "--env=JOB=matrix" in argv and "--env=X=1" in argv
    assert "--output=results/x.log" in argv
    assert argv[-1] == "tools/jobs/run_regress.sh"
    assert argv[argv.index("-t") + 1] == "60"


def test_slurm_submission_command():
    run = FakeRunner_3(out="Submitted batch job 4242\n")
    s = J.SlurmScheduler(runner=run)
    spec = J.JobSpec(script="tools/jobs/run_regress.sh", minutes=30, queue="gpu",
                     env={"JOB": "matrix"}, output="results/y.log")
    assert s.submit(spec) == "4242"
    argv = run.calls[0]
    assert argv[0] == "sbatch"
    assert "--partition=gpu" in argv and "--time=30" in argv
    assert "--nodes=1" in argv and "--output=results/y.log" in argv
    assert "--export=ALL,JOB=matrix" in argv
    assert argv[-1] == "tools/jobs/run_regress.sh"


def test_slurm_status_and_flux_status():
    run = FakeRunner_3(out="RUNNING\n")
    assert J.SlurmScheduler(runner=run).status("4242") == "running"
    assert run.calls[-1][:2] == ["squeue", "-h"]
    run = FakeRunner_3(out="CD\n")
    assert J.FluxScheduler(runner=run).status("f1") == "done"
    run = FakeRunner_3(out="")
    assert J.SlurmScheduler(runner=run).status("1") == "unknown"

    class Seq:
        def __init__(self, outs):
            self.outs, self.calls = list(outs), []

        def __call__(self, argv, **kw):
            self.calls.append(argv)

            class R:
                returncode = 0
                stdout = self.outs.pop(0)
                stderr = ""
            return R()
    run = Seq(["", "FAILED\n"])
    assert J.SlurmScheduler(runner=run).status("9") == "failed"
    assert run.calls[1][0] == "sacct"
    run = Seq(["", "COMPLETED\n"])
    assert J.SlurmScheduler(runner=run).status("9") == "done"


def test_time_limit_is_enforced():
    s = J.FluxScheduler(runner=FakeRunner_3(), max_minutes=60)
    with pytest.raises(ValueError):
        s.submit(J.JobSpec(script="x.sh", minutes=90, queue="pdebug"))


def test_scheduler_for_machine():
    tu = M.load()["tuolumne"]
    s = J.scheduler_for(tu, runner=FakeRunner_3())
    assert isinstance(s, J.FluxScheduler) and s.max_minutes == 60
    g = M.load(data=NVIDIA)["gpubox"]
    assert isinstance(J.scheduler_for(g, runner=FakeRunner_3()),
                      J.SlurmScheduler)


def test_local_scheduler_runs_the_script():
    run = FakeRunner_3(out="")
    s = J.LocalScheduler(runner=run)
    jid = s.submit(J.JobSpec(script="t.sh", env={"A": "1"}))
    assert jid.startswith("local-") and run.calls[0][-1] == "t.sh"


def test_inside_job():
    tu = M.load()["tuolumne"]
    assert J.inside_job(tu, runner=FakeRunner_3(out="1\n"))
    assert not J.inside_job(tu, runner=FakeRunner_3(out="0\n"))
    g = M.load(data=NVIDIA)["gpubox"]
    import os
    old = os.environ.pop("SLURM_JOB_ID", None)
    try:
        assert not J.inside_job(g)
        os.environ["SLURM_JOB_ID"] = "7"
        assert J.inside_job(g)
    finally:
        os.environ.pop("SLURM_JOB_ID", None)
        if old is not None:
            os.environ["SLURM_JOB_ID"] = old


# ---- RUL-PORT-DERIVATION: the C ports whose Fortran program carries the derivation ------------------------------------------------------

from offload.engine.confirm import ports
from offload.engine.confirm import programs as P


def test_recorded_ports_are_equivalent():
    rows = ports.load()
    assert rows
    for cid, e in rows.items():
        c, f = P.catalog_program(cid), P.catalog_program(e["fortran"])
        assert c is not None and f is not None, cid
        assert P.port_of(cid) == e["fortran"]
        assert ports.problems_of(c, f) == [], cid
        assert ports.derivation_for(cid)[0] == e["value"]


def test_the_file_is_current():
    want = {r["c"] for r in ports.candidates()}
    assert set(ports.load()) == want


def test_an_edited_or_relabelled_port_is_not_recorded():
    from offload.engine import c_gen
    rows = ports.load()
    for cid, e in rows.items():
        assert e["atom"] not in c_gen.C_EDITS
        assert e["atom"] not in c_gen.C_LABELS


# ---- The rulings registry (catalog/rulings.yaml) holds only rulings --------------------------------------

import re


from offload.engine.confirm import registry as R

ENTRIES = list(R.load().values())


@pytest.mark.parametrize("entry", ENTRIES, ids=[e.id for e in ENTRIES])
def test_entry_comes_from_rulings_md(entry):
    assert R.in_rulings_md(entry.rulings_md), entry.id


@pytest.mark.needs_spec
@pytest.mark.parametrize("entry", [e for e in ENTRIES if e.citations],
                         ids=[e.id for e in ENTRIES if e.citations])
def test_quotes_are_in_the_spec(entry):
    assert R.check(entry) == []


@pytest.mark.parametrize("entry", ENTRIES, ids=[e.id for e in ENTRIES])
def test_entry_names_an_existing_test(entry):
    path, _, name = entry.test.partition("::")
    text = (ROOT / path).read_text()
    assert re.search(rf"^def {re.escape(name)}\(", text, re.M), entry.test


def test_spec_reading_entries_cite_the_spec():
    """A reading of the spec carries its text; process, mode and
    environment rulings (and RUL-SCOPE-STRUCTURAL) have none."""
    owner = {"RUL-SCOPE-STRUCTURAL", "RUL-OMPVV-UNTRUSTED",
             "RUL-NO-SELF-CHECK"}
    for e in ENTRIES:
        if e.kind not in ("process", "mode", "environment") and \
                e.id not in owner:
            assert e.citations, e.id


def test_an_invented_ruling_is_refused():
    fake = R.Entry("RUL-X", "unspecified", "31",
                   "the compiler may do anything it likes", ())
    assert R.check(fake) == ["RUL-X: rulings_md text not in rulings.md"]


@pytest.mark.needs_spec
def test_a_wrong_page_is_refused():
    e = R.load()["RUL-PRESENT-TERMINATION"]
    bad = R.Entry(e.id, e.kind, e.task, e.rulings_md,
                  (dict(e.citations[0], page=40),))
    assert any("not p.40" in x for x in R.check(bad))


def test_match_by_program():
    ids = {e.id for e in R.matching("omp52-clause-map-present")}
    assert "RUL-PRESENT-TERMINATION" in ids
    ids = {e.id for e in R.matching("omp52-c-clause-map-delete")}
    assert "RUL-DELETE-REFCOUNT" in ids
    ids = {e.id for e in R.matching("omp52-clause-bind-thread")}
    assert "RUL-BIND-THREAD-SET" in ids
    assert R.matching("omp52-clause-map-to") == []


def test_match_by_needs_requires_and_reason():
    ids = {e.id for e in R.matching("x", needs=("zero_copy",))}
    assert ids == {"RUL-NEEDS-ZERO-COPY"}
    src = "program p\n!$omp requires unified_address\nend program\n"
    ids = {e.id for e in R.matching("x", text=src)}
    assert {"RUL-REQUIRES-IMPLDEF", "RUL-REQUIREMENT-REFUSED"} <= ids
    ids = {e.id for e in R.matching(
        "x", reason="exit_status: 127; error while loading shared libraries")}
    assert ids == {"RUL-PRELUDE-ENVIRONMENT"}


# ---- The decision rules on synthetic evidence (no runs) -------------------------------------



from offload.engine.confirm import registry as REG
from offload.engine.confirm import rules as RU
from offload.engine.confirm.facts import Facts
from offload.engine.confirm.legality import Legality
from offload.engine.confirm.model import Case, Evidence, ProgramRef, Run


SRC = "program p\n!$omp target\n!$omp end target\nend program p\n"


def prog(kind="fuzz", ident="s:1", expected="checksum=7", text=SRC,
         needs=(), evidence="construct", lang="f90"):
    return ProgramRef(kind, ident, lang, 52, "omp", True, tuple(needs),
                      evidence, text, expected)


def case_6(outcome="wrong_answer", value="checksum=9", tc="cce21",
         mode="unified", arch="gfx942", machine="tuolumne", reason="",
         flaky=False, p=None, repeats=3):
    return Case(p or prog(), tc, machine, arch, mode, outcome, reason, value,
                0, flaky, repeats)


def cell(collector, tc, outcome, value, mode="unified", arch="gfx942",
         n=3, variant="original"):
    return Evidence(collector, tc, arch, mode, runs=(Run(outcome, value, 0),)
                    * n, value=value, variant=variant)


def value(collector, v, status="value"):
    return Evidence(collector, value=v, status=status)


class Ctx:
    def __init__(self, evidence):
        self.evidence = evidence


def run(c, evidence, legal="legal", findings=()):
    f = Facts(c, legality=Legality(legal, "test"),
              registry=REG.matching(c.program.ident, c.program.text,
                                    c.program.needs, c.reason),
              findings=list(findings))
    supplied = dict(evidence)
    supplied.setdefault("stored_repeats", [
        cell("stored_repeats", c.toolchain, c.outcome, c.value, c.mode,
             c.arch, 1 if c.flaky else 3)])
    return RU.decide(f, Ctx(supplied),
                     collect=lambda col: list(supplied.get(col.name, [])))


TRUSTED = {"model": [value("model", "checksum=7")],
           "elision": [value("elision", "checksum=7")]}


def test_rules_file_loads_and_cites_only_registry_entries():
    rs = RU.rules()
    assert rs[-1].id == "R99-default" and not rs[-1].when
    reg = REG.entries()
    for r in rs:
        assert all(c in reg for c in r.cite), r.id


def test_every_rule_cites_a_registry_entry():
    """Every rule names the ruling it applies (the
    Rulings are registry entries: presence witness, own-family
    metamorphic source, G1, R12 not for fuzz, R22b)."""
    rs = {r.id: r for r in RU.rules()}
    assert all(r.cite for r in rs.values()), \
        [r.id for r in rs.values() if not r.cite]
    assert "RUL-FUZZ-G1-ILLEGAL" in rs["R03-illegal"].cite
    for rid in ("R12-every-family-rejects",
                "R12a-every-family-rejects-claimed",
                "R12b-compile-undecided"):
        assert "RUL-R12-NOT-FOR-FUZZ" in rs[rid].cite, rid
    for rid in ("R16-copy-check-blind-in-unified", "R17-copy-mode-failure",
                "R18-unified-memory-failure", "R19-arch-specific",
                "R20-runtime-bug"):
        assert "RUL-PRESENCE-WITNESS" in rs[rid].cite, rid
    assert "RUL-METAMORPHIC-OTHER-FAMILY" in rs["R20-runtime-bug"].cite
    assert "RUL-METAMORPHIC-DISPUTE" in \
        rs["R22b-expected-disputed-late"].cite


def test_stored_implementation_defined_disposition_is_unspecified():
    """R15: a stored triage disposition (catalog/expected_triage.yaml)
    saying the spec leaves the behaviour implementation defined makes the
    failure unspecified, not a bug."""
    rec = Evidence("expected_record", value="check=pass", detail=(
        '{"status": "implementation_defined", "reason": "x", "which": '
        '"main verdict", "agreeing": [], "disposition": '
        '"implementation_defined"}'))
    p = prog("catalog", "omp52-clause-x", "check=pass")
    d = run(case_6(p=p, tc="cce21", value="check=fail"),
            {"expected_record": [rec]})
    assert (d.verdict, d.rule) == ("unspecified",
                                   "R15-implementation-defined")
    assert any(c.startswith("RUL-DISPOSITION-PER-PROGRAM")
               for c in d.cites)


def test_stated_needs_human_reason_is_in_the_reason():
    """A triage entry's stated needs_human reason
    (catalog/expected_triage.yaml) is part of a needs_human decision's
    reason."""
    rec = Evidence("expected_record", value="check=pass", detail=(
        '{"status": "derived", "reason": "x", "which": "main verdict", '
        '"agreeing": ["derivation", "model"], "withdraw": ["afar"], '
        '"finding": "data/findings/f.f90", "disposition": '
        '"compiler_wrong", "needs_human": "no 5.0 witness"}'))
    p = prog("catalog", "omp50-clause-schedule", "check=pass")
    d = run(case_6(p=p, tc="cce21", value="check=fail"),
            {"expected_record": [rec]})
    assert d.verdict == "needs_human" and d.rule == "R22-expected-weak"
    assert d.reason.endswith("stated reason (catalog/expected_triage.yaml)"
                             ": no 5.0 witness")


def test_rules_name_no_vendor_or_machine():
    text = (ROOT / "catalog" / "confirm_rules.yaml").read_text().lower()
    body = text.split("rules:", 1)[1]
    for word in ("xnack", "amd", "cray", "cce", "afar", "nvidia", "nvhpc",
                 "gfx", "tuolumne", "tioga", "mi300", "mi250"):
        assert not re.search(rf"\b{word}", body), word


def test_rule_code_names_no_toolchain_or_machine():
    """Rules name no vendor, machine or XNACK:
    the code that decides verdicts holds no toolchain, family, machine or
    arch name as a string; such knowledge is data (catalog/machines.yaml,
    catalog/triage_28.yaml)."""
    from offload.engine.toolchains import TOOLCHAINS, registry
    from offload.engine.confirm import machines as MA
    data = yaml.safe_load((ROOT / "catalog" / "machines.yaml").read_text())
    names = set(TOOLCHAINS) | set(registry().families) | set(data["machines"])
    names |= {m["arch"] for m in data["machines"].values()}
    for f in ("facts.py", "rules.py", "decisions.py", "engine.py"):
        text = (ROOT / "offload" / "engine" / "confirm" / f).read_text()
        quoted = set(re.findall(r"[\"']([A-Za-z0-9_.-]+)[\"']", text))
        assert not quoted & names, (f, sorted(quoted & names))
    assert ("afar", "unified") in MA.no_present_check()


def test_unknown_predicate_or_citation_is_refused():
    data = yaml.safe_load((ROOT / "catalog" / "confirm_rules.yaml")
                          .read_text())
    bad = {"version": 1, "rules": [dict(data["rules"][0],
                                        when={"no_such": True})]
           + data["rules"][-1:]}
    with pytest.raises(ValueError):
        RU.load(data=bad)
    bad = {"version": 1, "rules": [dict(data["rules"][0],
                                        cite=["RUL-INVENTED"])]
           + data["rules"][-1:]}
    with pytest.raises(ValueError):
        RU.load(data=bad)


def test_environment():
    d = run(case_6("harness_error", None, reason="environment: error while "
                 "loading shared libraries: libamdhip64.so.7"), {})
    assert (d.verdict, d.rule) == ("environment", "R01-environment")
    d = run(case_6("run_error", None, reason="exit_status: 127; error while "
                 "loading shared libraries"), {})
    assert d.verdict == "environment"


def test_passing_cell_is_not_a_failure():
    assert run(case_6("correct_on_device", "checksum=7"), {}).verdict == \
        "not_a_failure"


def test_illegal_and_unknown_legality():
    assert run(case_6(), TRUSTED, legal="illegal").verdict == "our_bug"
    d = run(case_6(), TRUSTED, legal="unknown")
    assert (d.verdict, d.rule) == ("needs_human", "R04-legality-unknown")


def test_unsupported():
    d = run(case_6("rejected", None, reason="not_implemented: not yet "
                 "implemented: Unhandled clause allocate"), {})
    assert d.verdict == "unsupported"
    assert run(case_6("accepted_ignored", None, reason="ignored: x"),
               {}).verdict == "unsupported"


def test_unspecified_by_registry():
    p = prog("catalog", "omp60-clause-map-self", "check=pass")
    d = run(case_6(p=p, value="check=fail"), {})
    assert (d.verdict, d.rule) == ("unspecified", "R06-no-fixed-value")
    assert "RUL-NO-FIXED-VALUE-SELF" in d.reason


def test_oracle_entry_does_not_excuse_a_failure():
    """schedule(static) is no-oracle implementation_defined but checked:
    a failure of what the check tests still counts."""
    p = prog("catalog", "omp52-clause-schedule-static", "check=pass")
    ev = {"model": [value("model", "check=pass")],
          "derivation": [value("derivation", "check=pass")],
          "other_toolchains": [cell("other_toolchains", "afar",
                                    "correct_on_device", "check=pass")]}
    d = run(case_6(p=p, value="check=fail"), ev)
    assert d.verdict == "compiler_bug"


def test_needs_unified_memory_in_copy_mode():
    p = prog(needs=("zero_copy",))
    d = run(case_6(p=p, mode="copy"), TRUSTED)
    assert d.verdict == "needs_unified_memory"
    assert "RUL-NEEDS-ZERO-COPY" in d.cites
    req = prog(text="program p\n!$omp requires unified_shared_memory\n"
               "end program p\n")
    assert run(case_6(p=req, mode="copy"), TRUSTED).verdict == \
        "needs_unified_memory"
    # in unified mode the requirement is met: the rules go on
    assert run(case_6(p=p, mode="unified"), TRUSTED).verdict != \
        "needs_unified_memory"


def test_requirement_refused():
    p = prog(text="program p\n!$omp requires unified_address\nend program\n")
    ev = dict(TRUSTED, other_mode=[cell("other_mode", "afar",
                                        "correct_on_device", "checksum=7")])
    d = run(case_6("crash", None, tc="afar", mode="copy", p=p), ev)
    assert d.verdict == "requirement_refused"


def test_flaky_with_rate():
    ev = {"stored_repeats": [Evidence(
        "stored_repeats", "afar", "gfx942", "unified",
        runs=(Run("wrong_answer", "checksum=9"),
              Run("correct_on_device", "checksum=7"),
              Run("wrong_answer", "checksum=9")))]}
    d = run(case_6(flaky=True, tc="afar"), ev)
    assert d.verdict == "flaky" and d.fail_rate == "2/3"


def test_compile_time_bug():
    ice = run(case_6("ice", None, reason="ice: unhandled construct type"), {})
    assert (ice.verdict, ice.rule) == ("compiler_bug", "R10-compile-ice")
    other = {"other_toolchains": [cell("other_toolchains", "afar",
                                       "correct_on_device", "checksum=7")]}
    rej = run(case_6("rejected", None, reason="diagnostic: ftn-1370"), other)
    assert (rej.verdict, rej.rule) == ("compiler_bug",
                                       "R11-compile-rejection")
    alone = {"other_toolchains": [Evidence(
        "other_toolchains", "afar", "gfx942", "unified",
        runs=(Run("rejected", None, None, "diagnostic: error: x"),))]}
    rej = run(case_6("rejected", None, reason="diagnostic: ftn-1370",
                   p=prog("catalog", "omp52-clause-x", "check=pass")), alone)
    # RUL-UNSUPPORTED-EVERYWHERE: every family rejects a legal program (a catalog
    # program; not for a fuzz program)
    assert (rej.verdict, rej.rule) == ("unsupported_everywhere",
                                       "R12-every-family-rejects")
    # the same family accepting is no evidence (CCE releases share bugs),
    # and with no other family measured nothing decides
    same = {"other_toolchains": [cell("other_toolchains", "cce19",
                                      "correct_on_device", "checksum=7")]}
    d = run(case_6("rejected", None, reason="diagnostic: x"), same)
    assert (d.verdict, d.rule) == ("needs_human", "R12b-compile-undecided")
    # legality unknown is escalated before
    assert run(case_6("rejected", None, reason="diagnostic: x"), alone,
               legal="unknown").verdict == "needs_human"


def test_our_bug_when_elision_and_compilers_agree_against_the_model():
    ev = {"model": [value("model", "checksum=7")],
          "elision": [value("elision", "checksum=9")],
          "other_toolchains": [cell("other_toolchains", "afar",
                                    "wrong_answer", "checksum=9")]}
    d = run(case_6(value="checksum=9"), ev)
    assert (d.verdict, d.rule) == ("our_bug", "R13-oracle-wrong")
    # one family only: not enough
    ev["other_toolchains"] = [cell("other_toolchains", "cce20",
                                   "wrong_answer", "checksum=9")]
    assert run(case_6(value="checksum=9"), ev).verdict != "our_bug"


def test_runtime_bug_needs_an_executed_witness():
    witness = {"other_toolchains": [cell("other_toolchains", "afar",
                                         "correct_on_device", "checksum=7")]}
    d = run(case_6(), {**TRUSTED, **witness})
    assert (d.verdict, d.rule) == ("compiler_bug", "R20-runtime-bug")
    assert "afar/gfx942/unified" in d.witnesses
    # model + derivation agree, but nothing executed shows the value
    p = prog("catalog", "omp52-clause-x", "check=pass")
    ev = {"model": [value("model", "check=pass")],
          "derivation": [value("derivation", "check=pass")]}
    d = run(case_6(p=p, value="check=fail"), ev)
    assert d.verdict == "needs_human" and d.expected["status"] == "derived"
    # one source only
    d = run(case_6(), {"model": [value("model", "checksum=7")], **witness})
    assert d.verdict == "needs_human" and \
        d.expected["status"] == "provisional"
    # a gfx90a run of another compiler is a witness; of the same compiler
    # in another mode for a copy-dependent program it is not
    cat = prog("catalog", "omp52-c-clause-x", "check=pass", lang="c",
               text="")
    md = {"model": [value("model", "check=pass")],
          "derivation": [value("derivation", "check=pass")]}
    g = {"other_arch": [cell("other_arch", "cce21_g90", "correct_on_device",
                             "check=pass", mode="copy", arch="gfx90a")]}
    d = run(case_6(p=cat, value="check=fail"), {**md, **g})
    assert d.verdict == "needs_human" and d.expected["status"] == "derived"
    g = {"other_toolchains": [cell("other_toolchains", "afar",
                                   "correct_on_device", "check=pass")]}
    d = run(case_6(p=cat, value="check=fail"), {**md, **g})
    assert d.verdict == "compiler_bug"
    # the elision is a witness of its own (the brief: "... or the elision
    # gives the expected value")
    d = run(case_6(), TRUSTED)
    assert d.verdict == "compiler_bug" and d.witnesses == ["elision"]


def test_disagreeing_toolchain_withdrawn_only_with_a_finding():
    """A stored triage withdrawal names its finding; the decision lists
    it."""
    rec = Evidence("expected_record", value="check=pass", detail=(
        '{"status": "trusted", "reason": "x", "which": "main verdict", '
        '"agreeing": ["derivation", "model"], "withdraw": ["afar", '
        '"cce19"], "finding": "data/findings/f.f90", "disposition": '
        '"compiler_wrong"}'))
    p = prog("catalog", "omp52-clause-schedule", "check=pass")
    ev = {"expected_record": [rec],
          "port": [cell("port", "afar", "correct_on_device", "check=pass",
                        variant="port:omp52-c-clause-schedule")]}
    d = run(case_6(p=p, tc="cce21", value="check=fail"), ev)
    assert d.verdict == "compiler_bug"
    assert {"toolchain": "afar", "finding": "data/findings/f.f90"} in \
        d.withdrawn
    # the withdrawn compiler's own Fortran rows are no witness
    ev2 = {"expected_record": [rec],
           "other_toolchains": [cell("other_toolchains", "afar",
                                     "correct_on_device", "check=pass")]}
    d = run(case_6(p=p, tc="cce21", value="check=fail"), ev2)
    assert d.verdict != "compiler_bug"


def test_copy_mode_failure():
    ev = {**TRUSTED,
          "other_mode": [cell("other_mode", "cce21", "correct_on_device",
                              "checksum=7", mode="unified")],
          "other_toolchains": [cell("other_toolchains", "afar",
                                    "correct_on_device", "checksum=7",
                                    mode="copy")]}
    d = run(case_6(mode="copy"), ev)
    assert (d.verdict, d.rule) == ("copy_mode_failure",
                                   "R17-copy-mode-failure")
    # the check runs in copy mode only: the unified pass is no evidence
    p = prog(evidence="copy_mode_only")
    d = run(case_6(mode="copy", p=p), ev)
    assert (d.verdict, d.rule) == ("compiler_bug",
                                   "R16-copy-check-blind-in-unified")


def test_unified_memory_failure():
    ev = {**TRUSTED,
          "other_mode": [cell("other_mode", "afar", "correct_on_device",
                              "checksum=7", mode="copy")]}
    d = run(case_6(tc="afar"), ev)
    assert d.verdict == "unified_memory_failure"


def test_arch_specific():
    ev = {**TRUSTED,
          "other_arch": [cell("other_arch", "cce21", "correct_on_device",
                              "checksum=7", mode="copy")]}
    d = run(case_6(tc="cce21_g90", mode="copy", arch="gfx90a",
                 machine="tioga"), ev)
    assert (d.verdict, d.rule) == ("arch_specific", "R19-arch-specific")


def test_single_mode_machine_has_no_other_mode_and_still_decides():
    na = Evidence("other_mode", "cce21_g90", status="not_applicable",
                  detail="tioga has only the copy mode")
    ev = {**TRUSTED, "other_mode": [na],
          "other_toolchains": [cell("other_toolchains", "afar_g90",
                                    "correct_on_device", "checksum=7",
                                    mode="copy", arch="gfx90a")]}
    d = run(case_6(tc="cce21_g90", mode="copy", arch="gfx90a",
                 machine="tioga"), ev)
    assert (d.verdict, d.rule) == ("compiler_bug", "R20-runtime-bug")


def test_too_few_repeats_is_needs_human():
    ev = {**TRUSTED, "stored_repeats": [cell("stored_repeats", "cce21",
                                             "wrong_answer", "checksum=9",
                                             n=1)],
          "other_toolchains": [cell("other_toolchains", "afar",
                                    "correct_on_device", "checksum=7")]}
    d = run(case_6(repeats=1), ev)
    assert (d.verdict, d.rule) == ("needs_human", "R21-not-reproduced")


def test_collectors_run_only_when_a_rule_needs_them():
    d = run(case_6("ice", None, reason="ice: x"), {})
    assert "elision" not in d.collectors_run
    assert "metamorphic" not in d.collectors_run


def fuzz_facts(outcome, host_values, value="checksum=9"):
    c = case_6(outcome, value)
    return Facts(c, legality=Legality("legal", "test"),
                 extra={"validity": "noncompliant",
                        "host_values": host_values})


def test_fuzz_noncompliant_needs_host_builds():
    """The rule as written: noncompliant (not
    our_bug), only for a wrong answer with host builds of two families."""
    d = RU.decide(fuzz_facts("wrong_answer", {"afar": 5, "cce19": 5,
                                              "cce20": 5}),
                  Ctx({}), collect=lambda col: [])
    assert (d.verdict, d.rule) == ("noncompliant", "R13b-fuzz-noncompliant")
    # one family's host build only (b4:151): not enough
    d = RU.decide(fuzz_facts("wrong_answer", {"cce21": 5, "afar": None}),
                  Ctx({}), collect=lambda col: [])
    assert (d.verdict, d.rule) == ("needs_human",
                                   "R13c-fuzz-noncompliant-weak")
    # a device crash is never excluded (c1:1759)
    d = RU.decide(fuzz_facts("crash", {"afar": 5, "cce19": 5}, None),
                  Ctx({}), collect=lambda col: [])
    assert d.verdict == "needs_human"


def test_our_bug_blocked_by_a_device_run_printing_the_claim():
    """Probe: model 7, elision 9; cce21 prints 9; AFAR
    prints 7 on the device in unified and 9 in copy: not our_bug; both
    sides listed."""
    ev = {"model": [value("model", "checksum=7")],
          "elision": [value("elision", "checksum=9")],
          "other_toolchains": [
              cell("other_toolchains", "afar", "correct_on_device",
                   "checksum=7"),
              cell("other_toolchains", "afar", "wrong_answer", "checksum=9",
                   mode="copy")]}
    d = run(case_6(value="checksum=9"), ev)
    assert (d.verdict, d.rule) == ("needs_human", "R13a-oracle-contested")
    assert "afar/gfx942/unified=checksum=7" in d.reason
    assert "cce21/gfx942/unified=checksum=9" in d.reason


def test_always_failing_with_varying_values_is_not_flaky():
    """Probe: three wrong answers with three different
    values are a deterministic failure, not flaky."""
    ev = {**TRUSTED, "stored_repeats": [Evidence(
        "stored_repeats", "cce21", "gfx942", "unified",
        runs=(Run("wrong_answer", "checksum=1"),
              Run("wrong_answer", "checksum=2"),
              Run("wrong_answer", "checksum=3")))]}
    d = run(case_6(flaky=True), ev)
    assert (d.verdict, d.rule) == ("compiler_bug", "R20-runtime-bug")
    assert "varying values" in d.reason


def test_runner_failure_never_makes_a_case_flaky():
    """Probe: a harness-error repeat (ssh failure) next
    to deterministic failures is not evidence."""
    ev = {**TRUSTED,
          "repeats": [Evidence("repeats", "cce21", "gfx942", "unified",
                               runs=(Run("harness_error", None, None,
                                         "remote: rc=255"),))],
          "other_toolchains": [cell("other_toolchains", "afar",
                                    "correct_on_device", "checksum=7")]}
    d = run(case_6(), ev)
    assert (d.verdict, d.rule) == ("compiler_bug", "R20-runtime-bug")


def test_value_rules_do_not_swallow_rejections():
    """R06/R07 apply to run-time failures only."""
    p = prog("catalog", "omp60-clause-induction", "check=pass")
    other = {"other_toolchains": [cell("other_toolchains", "afar",
                                       "correct_on_device", "check=pass")]}
    d = run(case_6("rejected", None, reason="diagnostic: x", p=p), other)
    assert d.verdict != "unspecified"
    d = run(case_6("ice", None, reason="ice: x", p=prog(needs=("zero_copy",))),
            {}, )
    assert d.verdict == "compiler_bug"
    # defaultmap(self) reporting a host run under mandatory: R19b
    p = prog("catalog", "omp60-clause-defaultmap-self", "check=pass")
    d = run(case_6("fell_back_to_host", "check=pass", p=p), other)
    assert (d.verdict, d.rule) == ("compiler_bug", "R19b-host-fallback")
    # its wrong answer stays unspecified (the ruling's value)
    d = run(case_6("wrong_answer", "check=fail", p=p), other)
    assert d.verdict == "unspecified"


def test_newer_form_rejection_without_claim():
    """RUL-NO-CLAIM-UNSUPPORTED: a 6.0 diagnostic rejection with no
    recorded claim is unsupported; an ICE stays a bug; 5.2 unchanged."""
    other = {"other_toolchains": [cell("other_toolchains", "afar",
                                       "correct_on_device", "check=pass")]}
    p60 = ProgramRef("file", "x", "f90", 60, "omp", True, (), "construct",
                     SRC, "check=pass")
    d = run(case_6("rejected", None, reason="diagnostic: x", p=p60), other)
    assert (d.verdict, d.rule) == ("unsupported", "R11a-newer-form-unclaimed")
    assert run(case_6("ice", None, reason="ice: x", p=p60), other).verdict \
        == "compiler_bug"
    p52 = ProgramRef("file", "x", "f90", 52, "omp", True, (), "construct",
                     SRC, "check=pass")
    assert run(case_6("rejected", None, reason="diagnostic: x", p=p52),
               other).rule == "R11-compile-rejection"
    assert RU.claimed("cce19", "omp.directive.target", 52)
    assert not RU.claimed("cce19", "omp.directive.target", 60)


def test_host_fallback_under_mandatory():
    """RUL-MANDATORY-DEVICE: a deterministic host report under mandatory
    while another family runs the program on the device is a failure,
    without an expected-value verdict."""
    p = prog("catalog", "omp52-clause-y", "check=pass")
    c = case_6("fell_back_to_host", "check=pass", tc="cce21", p=p)
    on_dev = {"other_toolchains": [cell("other_toolchains", "afar",
                                        "correct_on_device", "check=pass")]}
    d = run(c, on_dev)
    assert (d.verdict, d.rule) == ("compiler_bug", "R19b-host-fallback")
    same = {"other_toolchains": [cell("other_toolchains", "cce19",
                                      "correct_on_device", "check=pass")]}
    assert run(c, same).rule != "R19b-host-fallback"


def test_a_rejection_the_52_program_shares_is_not_a_60_form():
    other = {"other_toolchains": [cell("other_toolchains", "afar",
                                       "correct_on_device", "check=pass")]}
    p = prog("catalog", "omp60-clause-x", "check=pass")
    p = ProgramRef(**{**p.__dict__, "version": 60})
    c = case_6("rejected", None, reason="diagnostic: x", p=p)
    f = Facts(c, legality=Legality("legal", "t"),
              extra={"v52_outcome": "rejected",
                     "v52_reason": "diagnostic: x"})
    supplied = dict(other, stored_repeats=[cell("stored_repeats", "cce21",
                                                "rejected", None, n=1)])
    d = RU.decide(f, Ctx(supplied),
                  collect=lambda col: list(supplied.get(col.name, [])))
    assert d.rule == "R11-compile-rejection"
    f = Facts(c, legality=Legality("legal", "t"),
              extra={"v52_outcome": "correct_on_device"})
    d = RU.decide(f, Ctx(supplied),
                  collect=lambda col: list(supplied.get(col.name, [])))
    assert d.rule == "R11a-newer-form-unclaimed"


def test_every_family_rejects_counts_front_end_rejections_only():
    """An ICE or hang of another family is not
    a rejection; the case's own link failure or hang is compiler_bug."""
    ice = {"other_toolchains": [Evidence("other_toolchains", "afar",
                                         "gfx942", "unified", runs=(
                                             Run("ice", None, None,
                                                 "ice: x"),))]}
    d = run(case_6("rejected", None, reason="diagnostic: ftn-1990 x"), ice)
    assert (d.verdict, d.rule) == ("needs_human", "R12b-compile-undecided")
    assert "afar/unified:ice" in d.reason
    d = run(case_6("rejected", None, reason="link_undefined_symbol: OmpIt$k"),
            {"other_toolchains": [cell("other_toolchains", "afar",
                                       "rejected", None)]})
    assert (d.verdict, d.rule) == ("compiler_bug", "R10b-own-link-or-hang")
    d = run(case_6("timeout", None, reason="compile_timeout"), ice)
    assert (d.verdict, d.rule) == ("compiler_bug", "R10b-own-link-or-hang")
    rej = {"other_toolchains": [Evidence("other_toolchains", "afar",
                                         "gfx942", "unified", runs=(
                                             Run("rejected", None, None,
                                                 "diagnostic: error"),))]}
    d = run(case_6("rejected", None, reason="diagnostic: ftn-1990 x",
                 p=prog("catalog", "omp52-clause-x", "check=pass")), rej)
    assert d.verdict == "unsupported_everywhere"


def test_a_52_link_failure_is_not_a_shared_rejection():
    """Case (omp60-clause-device_type-nohost on
    cce19/cce20): the 5.2 program links badly, the 6.0 one is a syntax
    rejection: a 6.0 form."""
    other = {"other_toolchains": [cell("other_toolchains", "afar",
                                       "correct_on_device", "check=pass")],
             "stored_repeats": [cell("stored_repeats", "cce19", "rejected",
                                     None, n=1)]}
    p = ProgramRef("catalog", "omp60-clause-device_type-nohost", "f90", 60,
                   "omp", True, (), "construct", SRC, "check=pass")
    c = case_6("rejected", None, tc="cce19", p=p,
             reason="diagnostic: ftn-1725 ftn: ERROR Unexpected syntax")

    def go(extra):
        f = Facts(c, legality=Legality("legal", "t"), extra=extra)
        return RU.decide(f, Ctx(other), collect=lambda col: list(
            other.get(col.name, [])))
    d = go({"v52_outcome": "rejected",
            "v52_reason": "link_undefined_symbol: f$gen_mod_"})
    assert d.rule == "R11a-newer-form-unclaimed"
    d = go({"v52_outcome": "rejected",
            "v52_reason": "diagnostic: ftn-297 ftn: ERROR IMPLICIT NONE"})
    assert d.rule == "R11a-newer-form-unclaimed"
    d = go({"v52_outcome": "ice", "v52_reason": "ice: x"})
    assert d.rule == "R11a-newer-form-unclaimed"
    d = go({"v52_outcome": "rejected",
            "v52_reason": "diagnostic: ftn-1725 ftn: ERROR Unexpected syntax"})
    assert d.rule == "R11-compile-rejection"


# --- The vendor claims ingested from the documents --------------------------

def test_claimed_reads_the_ingested_claims_per_release_and_language():
    """A 6.0 form is claimed only by a claim from a 6.0 feature list, of
    the toolchain's own release (or its gfx90a twin), for the program's
    language; a partial claim is no claim of support unless the vendor
    says the form is accepted."""
    assert RU.claimed("cce21", "omp.clause.map.self", 60)
    assert RU.claimed("cce20", "omp.clause.defaultmap.self", 60)
    assert not RU.claimed("cce21", "omp.clause.defaultmap.self", 60)
    assert RU.claimed("cce20", "omp.clause.map.self", 60, "c")
    assert RU.claimed("cce21_g90", "omp.clause.map.self", 60)
    assert not RU.claimed("cce19", "omp.clause.map.self", 60)
    assert RU.claimed("cce21", "omp.clause.enter.automap", 60)
    assert not RU.claimed("cce21", "omp.clause.enter.automap", 60, "c")
    # a 5.1 feature claim does not cover the 6.0 program of the atom
    assert RU.claimed("cce19", "omp.clause.map.iterator", 52)
    assert not RU.claimed("cce19", "omp.clause.map.iterator", 60)
    # amdclang's table: done for C, nothing for Fortran; partial is not
    assert RU.claimed("afar", "omp.clause.num_threads.strict", 60, "c")
    assert not RU.claimed("afar", "omp.clause.num_threads.strict", 60)
    assert not RU.claimed("afar", "omp.clause.map.self", 60, "c")
    assert [c.claim for c in RU.claims_for(
        "afar", "omp.clause.map.self", 60, "c")] == ["partial"]


def test_a_claimed_60_form_goes_to_the_ordinary_rules():
    """The claim makes RUL-NO-CLAIM-UNSUPPORTED's condition live: CCE 21
    claims map(self), so its rejection while another family compiles the
    program is compiler_bug; CCE 19 claims nothing at 6.0."""
    other = {"other_toolchains": [cell("other_toolchains", "afar",
                                       "correct_on_device", "check=pass")]}
    p = ProgramRef("catalog", "omp60-clause-map-self", "f90", 60, "omp",
                   True, (), "construct", SRC, "check=pass")
    d = run(case_6("rejected", None, tc="cce21", reason="diagnostic: x", p=p),
            other)
    assert (d.verdict, d.rule) == ("compiler_bug", "R11-compile-rejection")
    d = run(case_6("rejected", None, tc="cce19", reason="diagnostic: x", p=p),
            other)
    assert (d.verdict, d.rule) == ("unsupported",
                                   "R11a-newer-form-unclaimed")
    assert "no claim recorded" in d.reason


def test_unclaimed_reason_names_a_partial_claim():
    other = {"other_toolchains": [cell("other_toolchains", "cce21",
                                       "correct_on_device", "check=pass")]}
    p = ProgramRef("catalog", "omp60-c-clause-map-self", "c", 60, "omp",
                   True, (), "construct", SRC, "check=pass")
    d = run(case_6("rejected", None, tc="afar", reason="diagnostic: x", p=p),
            other)
    assert d.rule == "R11a-newer-form-unclaimed"
    assert "partial claim recorded" in d.reason
    assert "amdclang-afar-openmp-support" in d.reason


# --- Owner amendment of ruling C ----------------------------------

def _amended(monkeypatch, witness=True, spec=True, claim=True, tc="cce21"):
    """omp52-clause-defaultmap-none rejected by every family; the three
    conditions of the amendment switched on or off."""
    from offload.engine.confirm import witness as W
    from offload.engine.confirm.registry import Entry
    monkeypatch.setattr(W, "accepted",
                        lambda ident, sha="", family=None: ("gfortran 13.3.1" if witness
                                               else None))
    monkeypatch.setattr(RU, "claimed", lambda *a, **k: claim)
    p = ProgramRef("catalog", "omp52-clause-defaultmap-none", "f90", 52,
                   "omp", True, (), "construct", SRC, "check=pass")
    c = case_6("rejected", None, tc=tc, p=p,
             reason="diagnostic: ftn-1964 ftn: ERROR Variable I")
    reg = [Entry("RUL-LEGAL-X", "legality", "27b", "t", (
        {"version": "5.2", "section": "5.8.7", "page": 162, "quote": "q"},),
        {"programs": ["omp52-clause-defaultmap-none"]})] if spec else []
    f = Facts(c, legality=Legality("legal", "t"), registry=reg)
    other = {"other_toolchains": [Evidence(
        "other_toolchains", "afar", "gfx942", "unified", runs=(Run(
            "rejected", None, None, "diagnostic: error: 'i' must be listed"),))],
        "stored_repeats": [cell("stored_repeats", tc, "rejected", None, n=1)]}
    return RU.decide(f, Ctx(other), collect=lambda col: list(
        other.get(col.name, [])))


def test_every_family_rejects_with_all_three_conditions_is_a_bug(monkeypatch):
    d = _amended(monkeypatch)
    assert (d.verdict, d.rule) == ("compiler_bug",
                                   "R12a-every-family-rejects-claimed")
    assert "gfortran 13.3.1" in d.reason and "RUL-LEGAL-X" in d.reason


@pytest.mark.parametrize("missing", ["witness", "spec", "claim"])
def test_every_family_rejects_missing_a_condition_stays_unsupported(
        monkeypatch, missing):
    d = _amended(monkeypatch, **{missing: False})
    assert (d.verdict, d.rule) == ("unsupported_everywhere",
                                   "R12-every-family-rejects")


SRC_SHA = ""


def test_r12a_does_not_fire_without_a_trusted_checker(monkeypatch,
                                                       tmp_path):
    """gfortran/gcc -fopenmp are
    withdrawn as witnesses; with catalog/machines.yaml's checker list
    empty, even a stored gfortran accept is no witness, so every family
    rejecting stays unsupported_everywhere (R12). Gfortran is
    not among the configured checkers (NVHPC is), so its accept counts
    for nothing."""
    import yaml
    from offload.engine.confirm import witness as W
    assert "gfortran" not in W.checkers()
    rows = tmp_path / "w.yaml"
    rows.write_text(yaml.safe_dump({"witnesses": [
        {"program": "omp52-clause-defaultmap-none", "sha256": SRC_SHA,
         "checker": "gfortran", "version": "13.3.1", "result": "accept"}]}))
    monkeypatch.setattr(W, "_rows", lambda p=str(rows): tuple(
        yaml.safe_load(rows.read_text())["witnesses"]))
    assert W.accepted("omp52-clause-defaultmap-none") is None
    from offload.engine.confirm.registry import Entry
    monkeypatch.setattr(RU, "claimed", lambda *a, **k: True)
    p = ProgramRef("catalog", "omp52-clause-defaultmap-none", "f90", 52,
                   "omp", True, (), "construct", SRC, "check=pass")
    c = case_6("rejected", None, tc="cce21", p=p,
             reason="diagnostic: ftn-1964 ftn: ERROR Variable I")
    reg = [Entry("RUL-LEGAL-X", "legality", "27b", "t", (
        {"version": "5.2", "section": "5.8.7", "page": 162, "quote": "q"},),
        {"programs": ["omp52-clause-defaultmap-none"]})]
    f = Facts(c, legality=Legality("legal", "t"), registry=reg)
    other = {"other_toolchains": [Evidence(
        "other_toolchains", "afar", "gfx942", "unified", runs=(Run(
            "rejected", None, None, "diagnostic: error: 'i' must be listed"),))],
        "stored_repeats": [cell("stored_repeats", "cce21", "rejected", None,
                                n=1)]}
    d = RU.decide(f, Ctx(other), collect=lambda col: list(
        other.get(col.name, [])))
    assert (d.verdict, d.rule) == ("unsupported_everywhere",
                                   "R12-every-family-rejects")


# --- Later forms of earlier constructs, unclaimed --------------------------------

FUZZ_SET = ("!@file fuzz_dmod.f90\nmodule fuzz_dmod\n  integer :: gtab(4)\n"
            "  !$omp declare target enter(gtab)\nend module fuzz_dmod\n"
            "!@file fuzz_prog.f90\nprogram p\n  use fuzz_dmod\n"
            "  !$omp target teams num_teams(2: 4) &\n"
            "  !$omp& defaultmap(default: all)\n  gtab(1) = 1\n"
            "  !$omp end target teams\nend program p\n")


@pytest.mark.needs_spec
def test_later_forms_file_quotes_the_spec():
    from offload.engine.confirm import forms as FO
    fs = FO.forms()
    assert {f.id for f in fs} >= {"declare-target-enter",
                                  "target-thread-limit"}
    for f in fs:
        assert f.since in ("5.1", "5.2"), f.id
        assert f.message or f.directive, f.id
        for c in f.citations:
            found = REG.quote_pages(str(c["version"]), c["quote"])
            assert found, (f.id, c["quote"])
            assert any(a - 1 <= int(c["page"]) <= b for a, b in found), \
                (f.id, found)


def test_offending_statement_from_each_diagnostic_format():
    from offload.engine.confirm import forms as FO
    cce = ("diagnostic: ftn-1725 ftn: ERROR FUZZ_DMOD, File = fuzz_dmod.f90,"
           " Line = 3, Column = 24 | Unexpected syntax while parsing the "
           "DIRECTIVE statement : \"INDIRECT, LINK, TO or DEVICE_TYPE\" was"
           " expected but found \"E\".")
    assert FO.statement(FUZZ_SET, cce).strip() == \
        "!$omp declare target enter(gtab)"
    # a continuation line: the whole directive statement
    st = FO.statement(FUZZ_SET, "diagnostic: ftn-1725 ftn: ERROR P, File ="
                      " fuzz_prog.f90, Line = 4, Column = 30 | x")
    assert "num_teams(2: 4)" in st and "defaultmap(default: all)" in st
    clang = "diagnostic: <tmpdir>/p.c:2:30: error: unexpected OpenMP clause"
    assert FO.statement("int x;\n#pragma omp declare target enter(x)\n",
                        clang).startswith("#pragma omp declare target")
    flang = 'not_implemented: loc("fuzz_prog.f90":4:3): error: x'
    assert "num_teams" in FO.statement(FUZZ_SET, flang)
    assert FO.statement(FUZZ_SET, "diagnostic: no position") == ""
    assert [f.id for f in FO.match(FUZZ_SET, cce)] == \
        ["declare-target-enter"]
    msg = ("diagnostic: ftn-1370 ftn: ERROR P, File = p.f90, Line = 9, "
           "Column = 1 | The THREAD_LIMIT clause is not allowed with "
           "directive !$OMP TARGET PARALLEL.")
    assert [f.id for f in FO.match("", msg)] == ["target-thread-limit"]
    assert FO.match("", msg.replace("TARGET PARALLEL", "TARGET TEAMS")) == []


def test_later_form_rejection_without_claim_is_unsupported():
    """RUL-LATER-FORM-UNCLAIMED: CCE 19 rejects declare target enter (5.2)
    and claims only full 5.0: unsupported even though another family
    compiles the program; CCE 21 claims the enter clause (Fortran), so its
    rejection stays compiler_bug; a rejection elsewhere in the program
    (no later form at the diagnostic) stays R11."""
    other = {"other_toolchains": [cell("other_toolchains", "afar",
                                       "correct_on_device", "checksum=7")]}
    p = prog(text=FUZZ_SET)
    cce = ("diagnostic: ftn-1725 ftn: ERROR FUZZ_DMOD, File = fuzz_dmod.f90,"
           " Line = 3, Column = 24 | Unexpected syntax")
    d = run(case_6("rejected", None, tc="cce19", reason=cce, p=p), other)
    assert (d.verdict, d.rule) == ("unsupported",
                                   "R11c-later-form-unclaimed")
    assert "declare-target-enter" in d.reason and "5.2" in d.reason
    d = run(case_6("rejected", None, tc="cce21", reason=cce, p=p), other)
    assert (d.verdict, d.rule) == ("compiler_bug", "R11-compile-rejection")
    other_line = cce.replace("Line = 3", "Line = 2")
    d = run(case_6("rejected", None, tc="cce19", reason=other_line, p=p),
            other)
    assert d.rule == "R11-compile-rejection"
    # an ICE at a later form is still the compiler's defect
    d = run(case_6("ice", None, tc="cce19", reason="ice: " + cce[12:], p=p),
            other)
    assert d.verdict == "compiler_bug"
    from offload.engine.confirm import forms as FO
    F = {f.id: f for f in FO.forms()}
    for tc in ("cce19", "cce20", "cce21"):
        for fid in ("num-teams-lower-bound", "defaultmap-all",
                    "distribute-order"):
            assert not RU.form_claimed(tc, F[fid], 52), (tc, fid)
    assert RU.form_claimed("cce21", F["declare-target-enter"], 52)
    assert not RU.form_claimed("cce19", F["declare-target-enter"], 52)
    # CCE 20.0.0's release notes claim the 5.2
    # declare target syntax ("misc. new syntax ... (e.g. `declare
    # target`...)"), i.e. enter, for Fortran and C
    assert RU.form_claimed("cce20", F["declare-target-enter"], 52)
    assert RU.form_claimed("cce20_g90", F["declare-target-enter"], 52, "c")
    # CCE 19's thread_limit-on-target claim is C/C++ only; CCE's general
    # "full OpenMP 5.0" claim of thread_limit is not one of the 5.1 form
    assert RU.claimed("cce19", "omp.clause.thread_limit", 52)
    assert not RU.form_claimed("cce19", F["target-thread-limit"], 52)


def test_every_family_rejects_is_not_for_fuzz_programs():
    """Spot checks: in a program with many constructs (a fuzz
    program) another family's rejection says nothing about the construct
    this compiler rejects, at another statement (s1: AFAR lastprivate vs
    CCE strided update) or at the same directive (s1 seed 1150: AFAR's
    order clause vs CCE's firstprivate(i)): R12b, an agent decides; a
    catalog program tests one feature, so R12 stays."""
    p = prog(text=FUZZ_SET)
    cce = ("diagnostic: ftn-1747 ftn: ERROR P, File = fuzz_prog.f90, "
           "Line = 5, Column = 9 | The stride specified for array")
    other = lambda r: {"other_toolchains": [Evidence(  # noqa: E731
        "other_toolchains", "afar", "gfx942", "unified",
        runs=(Run("rejected", None, None, r),))]}
    for r in ('not_implemented: loc("fuzz_dmod.f90":3:3): error: x',
              'not_implemented: loc("fuzz_prog.f90":5:3): error: x'):
        d = run(case_6("rejected", None, tc="cce21", reason=cce, p=p),
                other(r))
        assert (d.verdict, d.rule) == ("needs_human",
                                       "R12b-compile-undecided")
    pc = prog("catalog", "omp52-clause-x", "check=pass", text=FUZZ_SET)
    d = run(case_6("rejected", None, tc="cce21", reason=cce, p=pc), other(
        'not_implemented: loc("fuzz_dmod.f90":3:3): error: x'))
    assert d.verdict == "unsupported_everywhere"

def test_a_message_match_names_the_form_before_the_statement():
    """Spot check (s1 seed 8174, CCE 20): the diagnostic is about
    order on target teams distribute, the statement also has
    defaultmap(default: all): the form is the one the message names."""
    from offload.engine.confirm import forms as FO
    src = ("program p\n!$omp target teams distribute defaultmap(default: "
           "all) &\n!$omp& order(reproducible: concurrent)\ndo i = 1, 4\n"
           "end do\nend program p\n")
    reason = ("diagnostic: ftn-1370 ftn: ERROR P, File = p.f90, Line = 3, "
              "Column = 12 | The ORDER clause is not allowed with directive "
              "!$OMP TARGET TEAMS DISTRIBUTE.")
    assert [f.id for f in FO.match(src, reason)] == ["distribute-order"]


def test_a_statement_with_two_later_forms_names_the_one_at_the_column():
    from offload.engine.confirm import forms as FO
    src = ("program p\n!$omp target teams num_teams(1: 4) &\n"
           "!$omp& defaultmap(default: all)\n!$omp end target teams\n"
           "end program p\n")
    r = ("diagnostic: ftn-1725 ftn: ERROR P, File = p.f90, Line = {}, "
         "Column = {} | Unexpected syntax")
    assert [f.id for f in FO.match(src, r.format(2, 34))] == [
        "num-teams-lower-bound"]
    assert [f.id for f in FO.match(src, r.format(3, 33))] == [
        "defaultmap-all"]


def test_metamorphic_dispute_is_named():
    """Spot check: an expected value the metamorphic runs dispute
    is needs_human by R22b (it fell through to R99 before)."""
    meta = [Evidence("metamorphic", "afar", "gfx942", "unified",
                     variant=v, runs=(Run("correct_on_device",
                                          "checksum=5", 0),),
                     value="checksum=5") for v in ("a", "b")]
    ev = {"model": [value("model", "checksum=7")], "metamorphic": meta,
          "other_toolchains": [cell("other_toolchains", "afar",
                                    "correct_on_device", "checksum=5")]}
    d = run(case_6("wrong_answer", "checksum=9"), ev)
    assert (d.verdict, d.rule) == ("needs_human",
                                   "R22b-expected-disputed-late")


def test_the_case_family_is_no_metamorphic_witness_against_itself():
    """Spot check: a compiler that fails deterministically gives
    the same wrong value on the spec-equivalent rewrites too; its own
    family's runs are not evidence against the expected value in its own
    case (as a family is never independent evidence). Another family's
    stable runs that agree with the model make the value trusted."""
    def meta(tc, v):
        return [Evidence("metamorphic", tc, "gfx942", "unified", variant=x,
                         runs=(Run("wrong_answer" if v != "checksum=7"
                                   else "correct_on_device", v, 0),),
                         value=v) for x in ("a", "b")]
    ev = {"model": [value("model", "checksum=7")],
          "metamorphic": meta("cce21", "checksum=9") + meta(
              "cce20", "checksum=9") + meta("afar", "checksum=7"),
          "other_toolchains": [
              cell("other_toolchains", "afar", "correct_on_device",
                   "checksum=7"),
              cell("other_toolchains", "cce20", "wrong_answer",
                   "checksum=9")]}
    d = run(case_6("wrong_answer", "checksum=9", tc="cce21"), ev)
    assert (d.verdict, d.rule) == ("compiler_bug", "R20-runtime-bug")
    assert d.expected["status"] == "trusted"
    # the other family disagreeing with the model is still a dispute
    ev2 = dict(ev, metamorphic=meta("cce21", "checksum=9") + meta(
        "afar", "checksum=5"))
    d = run(case_6("wrong_answer", "checksum=9", tc="cce21"), ev2)
    assert d.verdict == "needs_human"


def test_presence_abort_needs_a_witness_that_checks_presence():
    """(spot check of s1 seed 5153 on CCE 20): a
    presence or overlap abort ("Variable not found in present table",
    "Host region ... overlaps present region") is witnessed only by a run
    that enforces the present check: not by AFAR at HSA_XNACK=1 (unified
    memory, data/findings/afar-xnack1-present-not-enforced.f90), and not
    by the sequential elision (no device data environment)."""
    c = case_6(outcome="run_error", value=None, tc="cce20",
             reason="exit_status: 1; without mandatory: exit_status: 1")
    tail = ("ACC: libcrayacc/acc_present.c:762 CRAY_ACC_ERROR - Host region "
            "(40bbb0 to 40c240) overlaps present region (40bbb0 to 40c1f0 "
            "index 1) but is not contained for 'dr' from fuzz_prog.f90:74")

    def facts(ev):
        f = Facts(c, legality=Legality("legal", "test"), extra={
            "stderr_tail": tail})
        f.evidence = {**{"stored_repeats": [cell(
            "stored_repeats", "cce20", "run_error", None, n=3)]}, **ev}
        return f
    afar_x1 = cell("other_toolchains", "afar", "correct_on_device",
                   "checksum=7")
    afar_x0 = cell("other_mode", "afar", "correct_on_device", "checksum=7",
                   mode="copy")
    cce21 = cell("other_toolchains", "cce21", "correct_on_device",
                 "checksum=7")
    assert facts({**TRUSTED, "other_toolchains": [afar_x1]}).witnesses() \
        == []
    assert facts({**TRUSTED, "other_toolchains": [afar_x1, cce21]}
                 ).witnesses() == ["cce21/gfx942/unified"]
    assert facts({**TRUSTED, "other_mode": [afar_x0]}).witnesses() == \
        ["afar/gfx942/copy"]
    # another abort keeps every witness
    f = facts({**TRUSTED, "other_toolchains": [afar_x1]})
    f.extra = {"stderr_tail": "Memory access fault by GPU node-4"}
    assert f.witnesses() == ["afar/gfx942/unified", "elision"]


@pytest.mark.parametrize("status,verdict,rule", [
    ("claims_support", "compiler_bug", "R11-compile-rejection"),
    ("documents_unsupported", "unsupported", "R11d-documented-unsupported"),
    ("no_claim", "compiler_bug", "R11-compile-rejection"),
])
def test_rejection_by_vendor_claim_status(monkeypatch, status, verdict, rule):
    """A diagnostic rejection of a feature the vendor
    documents as unsupported is unsupported (R11d); with a claim of
    support or no claim it stays compiler_bug (R11); an ICE is a bug
    whatever the claim."""
    monkeypatch.setattr(RU, "claim_status", lambda *a, **k: status)
    other = {"other_toolchains": [cell("other_toolchains", "afar",
                                       "correct_on_device", "check=pass")]}
    p = prog("catalog", "omp52-c-clause-reverse_offload", "check=pass")
    d = run(case_6("rejected", None, tc="cce19", p=p,
                 reason="diagnostic: unexpected OpenMP clause "
                        "'reverse_offload'"), other)
    assert (d.verdict, d.rule) == (verdict, rule)
    d = run(case_6("ice", None, tc="cce19", p=p, reason="ice: x"), other)
    assert d.verdict == "compiler_bug"


def test_claim_status_from_the_claims_data():
    assert RU.claim_status("cce19", "omp.clause.reverse_offload", 52,
                           "c") == "documents_unsupported"
    assert RU.claim_status("cce19", "omp.directive.target", 52) == \
        "claims_support"
    assert RU.claim_status("cce19", "omp.clause.no_such_atom", 52) == \
        "no_claim"


def test_documented_unsupported_carries_to_the_60_program_sharing_the_rejection():
    """A 6.0 program rejected with the same diagnostic as its 5.2 program
    takes the feature's documented status at 5.2 (the CCE C
    reverse_offload programs at 5.2 and 6.0)."""
    other = {"other_toolchains": [cell("other_toolchains", "afar",
                                       "correct_on_device", "check=pass")],
             "stored_repeats": [cell("stored_repeats", "cce19", "rejected",
                                     None, n=1)]}
    why = "diagnostic: x.c:15:22: error: unexpected OpenMP clause 'reverse_offload'"
    p = prog("catalog", "omp60-c-clause-reverse_offload", "check=pass")
    p = ProgramRef(**{**p.__dict__, "version": 60, "lang": "c"})
    c = case_6("rejected", None, tc="cce19", p=p, reason=why)
    for v52, want in ((why, "R11d-documented-unsupported"),
                      ("diagnostic: something else", None)):
        f = Facts(c, legality=Legality("legal", "t"),
                  extra={"v52_outcome": "rejected", "v52_reason": v52})
        d = RU.decide(f, Ctx(other), collect=lambda col: list(
            other.get(col.name, [])))
        if want:
            assert d.rule == want
        else:
            assert d.rule != "R11d-documented-unsupported"


def test_documented_unsupported_not_for_a_rejection_at_a_later_form(
        monkeypatch):
    """CCE 20 rejects the enter clause of the indirect-invoked_by_fptr
    program; that the vendor documents invoked_by_fptr as unsupported does
    not make the enter rejection a documented gap."""
    from offload.engine.confirm import programs as P
    monkeypatch.setattr(RU, "claim_status",
                        lambda *a, **k: "documents_unsupported")
    p = P.catalog_ref("omp52-clause-indirect-invoked_by_fptr")
    why = ('diagnostic: ftn-1725 ftn: ERROR F, File = ../../x.f90, Line = '
           '16, Column = 28 | Unexpected syntax while parsing the DIRECTIVE '
           'statement : "INDIRECT, LINK, TO or DEVICE_TYPE" was expected '
           'but found "E".')
    f = Facts(case_6("rejected", None, tc="cce20", p=p, reason=why),
              legality=Legality("legal", "t"))
    assert not RU._documented_unsupported(f)


def test_gate_unconfirmed_goes_to_review(tmp_path, monkeypatch):
    """A cell whose reproduction-gate verdict is not confirmed is
    needs_human (R04b), a confirmed one goes on to the rules, an ungated
    one keeps its outcome."""
    import json
    from offload.engine import gate as G
    p = prog(kind="catalog", ident="omp52-clause-x")
    vf = tmp_path / "verdicts.jsonl"
    rows = [{"cell": "catalog|omp52-clause-x|cce21|1", "kind": "catalog",
             "ident": "omp52-clause-x", "toolchain": "cce21", "xnack": 1,
             "verdict": "not_reproduced", "inherited": True},
            {"cell": "widen|omp52-clause-x|cce20|1", "kind": "widen",
             "ident": "omp52-clause-x", "toolchain": "cce20", "xnack": 1,
             "verdict": "confirmed"}]
    vf.write_text("".join(json.dumps(r) + "\n" for r in rows))
    monkeypatch.setattr(G, "VERDICTS_FILE", vf)
    G._BY_CASE.clear()
    d = run(case_6(p=p, tc="cce21"), TRUSTED)
    assert d.verdict == "needs_human" and d.rule == "R04b-gate-unconfirmed"
    assert "not_reproduced" in d.reason and "inherited" in d.reason
    assert "RUL-REPRODUCTION-GATE" in d.cites
    d = run(case_6(p=p, tc="cce20"), TRUSTED)
    assert d.rule != "R04b-gate-unconfirmed"
    d = run(case_6(p=p, tc="cce19"), TRUSTED)       # not gated
    assert d.rule != "R04b-gate-unconfirmed"


@pytest.mark.parametrize("tc,program,want", [
    ("afar", "omp50-c-clause-device_type-nohost",
     ("unsupported_everywhere", "R11r-ruling-decides")),
    ("cce19", "omp52-c-clause-device_type-nohost",
     ("unsupported_everywhere", "R11r-ruling-decides")),
    # the Fortran program is not under the ruling: another family's
    # compile witnesses the rejection (R11)
    ("cce19", "omp50-clause-device_type-nohost",
     ("compiler_bug", "R11-compile-rejection"))])
def test_a_ruling_decides_before_the_family_witness(tc, program, want):
    """A recorded ruling about
    legality or support (catalog/rulings.yaml `decides`) takes precedence
    over the family-witness rules: the C nohost twin, which both clang
    front ends reject, is unsupported_everywhere on AFAR and CCE even
    though NVHPC on another machine compiles it."""
    lang = "c" if "-c-" in program else "f90"
    p = ProgramRef("catalog", program, lang, 52, "omp", True, (),
                   "construct", SRC, "check=pass")
    c = case_6("rejected", None, tc=tc, mode="copy", p=p,
             reason="diagnostic: error: function with 'device_type(nohost)'"
             " is not available on host")
    nv = Evidence("other_toolchains", "nvhpc", "sm_80", "copy", runs=(
        Run("unobservable", None, 0, "compiled and ran"),))
    d = run(c, {"other_toolchains": [nv]})
    assert (d.verdict, d.rule) == want
    assert REG.entries()["RUL-NOHOST-C-UNSUPPORTED-EVERYWHERE"].decides[
        "verdict"] == "unsupported_everywhere"


@pytest.mark.parametrize("mode,reason,want", [
    ("copy", "diagnostic: NVFORTRAN-F-1277-OpenMP unified_shared_memory "
     "clause is used in the requires construct but the application is not "
     "compiled with -gpu=unified", ("requirement_refused",
                                    "R11r-ruling-decides")),
    ("managed", "diagnostic: NVC++-S-0155-OpenMP unified_shared_memory "
     "clause is used in the requires construct but the application is not "
     "compiled with -gpu=unified", ("requirement_refused",
                                    "R11r-ruling-decides")),
    # another diagnostic is not the refusal the ruling decides
    ("copy", "diagnostic: NVFORTRAN-S-0034-Syntax error at or near :",
     ("compiler_bug", "R11-compile-rejection"))])
def test_a_ruling_decides_any_verdict_class(mode, reason, want):
    """R11r takes the verdict the ruling names: NVHPC's
    compile-time refusal of `requires unified_shared_memory` without
    -gpu=unified is requirement_refused (RUL-REQUIRES-IMPLDEF), cited by
    the ruling, though another family compiles the program."""
    src = "program p\n  !$omp requires unified_shared_memory\nend program p\n"
    p = ProgramRef("catalog", "omp52-clause-unified_shared_memory", "f90", 52,
                   "omp", True, (), "construct", src, "check=pass")
    c = case_6("rejected", None, tc="nvhpc", mode=mode, arch="sm_80",
             machine="wingtip", p=p, reason=reason)
    afar = Evidence("other_toolchains", "afar", "gfx942", "copy", runs=(
        Run("crash", None, 0, "crash: SIGSEGV"),))
    d = run(c, {"other_toolchains": [afar]})
    assert (d.verdict, d.rule) == want
    if want[0] == "requirement_refused":
        assert d.cites[0] == "RUL-REQUIRES-IMPLDEF"


@pytest.mark.parametrize("tc,program,want", [
    # : CCE 21's defaultmap family reports
    # ran_on_host=1 because the map(tofrom) flag is not copied back; the
    # region ran on the device (cce21-defaultmap-aggregate-flag.f90)
    ("cce21", "omp52-clause-defaultmap-aggregate",
     ("compiler_bug", "R19r-ruling-runtime")),
    ("cce21_g90", "omp60-clause-defaultmap-pointer",
     ("compiler_bug", "R19r-ruling-runtime")),
    ("cce21_4", "omp52-clause-defaultmap-scalar",
     ("compiler_bug", "R19r-ruling-runtime")),
    # The evidence is Fortran's; a C program is not decided
    ("cce21", "omp52-c-clause-defaultmap-scalar",
     ("compiler_bug", "R19b-host-fallback")),
    # another release, or a program outside the family: the host-fallback
    # rule as before
    ("cce19", "omp52-clause-defaultmap-aggregate",
     ("compiler_bug", "R19b-host-fallback")),
    ("cce21", "omp52-clause-target", ("compiler_bug", "R19b-host-fallback"))])
def test_a_ruling_decides_a_runtime_case(tc, program, want):
    p = ProgramRef("catalog", program, "c" if "-c-" in program else "f90",
                   52, "omp", True, (), "construct", SRC, "check=pass")
    c = case_6("fell_back_to_host", "check=pass", tc=tc, mode="copy", p=p,
             reason="ran_on_host=1 check=pass")
    other = cell("other_toolchains", "afar", "correct_on_device",
                 "check=pass", mode="copy")
    d = run(c, {"other_toolchains": [other]})
    assert (d.verdict, d.rule) == want
    if d.rule == "R19r-ruling-runtime":
        assert "RUL-MAPPED-FLAG-NOT-COPIED-BACK" in d.cites


def test_the_runtime_ruling_needs_its_reason():
    """A host fallback whose check failed is not the lost copy-back the
    ruling decides."""
    p = ProgramRef("catalog", "omp52-clause-defaultmap-aggregate", "f90",
                   52, "omp", True, (), "construct", SRC, "check=pass")
    c = case_6("fell_back_to_host", "check=fail", tc="cce21", mode="copy",
             p=p, reason="ran_on_host=1 check=fail")
    d = run(c, {"other_toolchains": [cell(
        "other_toolchains", "afar", "correct_on_device", "check=pass",
        mode="copy")]})
    assert d.rule != "R19r-ruling-runtime"


@pytest.mark.parametrize("program,want", [
    # : the undefined __atomic_load comes from the
    # host object of a double _Complex reduction, which needs -latomic
    # (the build recipe's), not from the compiler's device code
    ("omp52-c-w-reduction-complex", ("our_bug", "R10r-ruling-link")),
    ("omp52-c-w-critical-hint", ("compiler_bug", "R10b-own-link-or-hang"))])
def test_a_ruling_decides_a_link_failure(program, want):
    p = ProgramRef("catalog", program, "c", 52, "omp", True, (), "construct",
                   SRC, "check=pass")
    c = case_6("rejected", None, tc="afar", mode="copy", p=p,
             reason="link_undefined_symbol: ld.lld: error: undefined symbol: "
             "__atomic_load")
    d = run(c, {})
    assert (d.verdict, d.rule) == want


def test_a_runtime_ruling_is_no_derivation():
    """A spec_reading entry whose `applies` names programs
    derives their claimed value (collectors.Derivation); the run-time
    ruling about CCE 21's cells must not (it made 60 other cells of the
    family trusted in a first rebuild)."""
    e = REG.entries()["RUL-MAPPED-FLAG-NOT-COPIED-BACK"]
    assert e.kind != "spec_reading" and e.decides


def test_a_runtime_ruling_collects_the_expected_value_only_when_it_decides():
    """R19r keeps the expected-value record of the cells it
    decides (its `needs_after`), and a case it does not decide collects
    nothing more on its account."""
    other = cell("other_toolchains", "afar", "correct_on_device",
                 "check=pass", mode="copy")
    def go(tc):
        p = ProgramRef("catalog", "omp52-clause-defaultmap-alloc", "f90", 52,
                       "omp", True, (), "construct", SRC, "check=pass")
        c = case_6("fell_back_to_host", "check=pass", tc=tc, mode="copy", p=p,
                 reason="ran_on_host=1 check=pass")
        return run(c, {"other_toolchains": [other]})
    d = go("cce21")
    assert d.rule == "R19r-ruling-runtime" and "model" in d.collectors_run
    d = go("cce19")
    assert d.rule == "R19b-host-fallback" and "model" not in d.collectors_run


def test_a_gcc_host_build_never_counts_for_task22():
    """GCC: GCC is a compiler under test only; its host build of a
    fuzz program is no family for the host check."""
    f = fuzz_facts("wrong_answer", {"afar": 5, "gcc_g90": 5})
    assert f.host_families() == 1
    d = RU.decide(f, Ctx({}), collect=lambda col: [])
    assert d.rule != "R13b-fuzz-noncompliant"
    assert fuzz_facts("wrong_answer", {"afar": 5, "cce19": 5,
                                       "gcc_sm80": 5}).host_families() == 2


# ---- Independent legality witnesses (compilers not under test) -------------------------------------------------

import shutil


from offload.engine.confirm import witness as W
from offload.engine.toolchains import TOOLCHAINS


def test_only_nvhpc_is_trusted_now():
    """gfortran/gcc -fopenmp are
    withdrawn as legality witnesses; NVHPC (another offload
    compiler) is the replacement; every witness row is one of its."""
    assert set(W.checkers()) == {"nvhpc_f90", "nvhpc_acc", "nvhpc_c",
                                 "nvhpc269_f90", "nvhpc269_acc", "nvhpc269_c"}
    assert {r["checker"] for r in W._rows()} <= set(W.checkers())


def test_checkers_are_never_toolchains_under_test():
    """Except a compiler of another machine that names its family (it never witnesses its own family's cases)."""
    cs = {k: v for k, v in W.checkers().items() if not v.get("family")}
    for name, c in cs.items():
        assert name not in TOOLCHAINS
        assert not any(t.fc.split("/")[-1] == c["command"].split()[0] or
                       (t.cc or "").split("/")[-1] == c["command"].split()[0]
                       for t in TOOLCHAINS.values())


@pytest.mark.skipif(not shutil.which("gfortran"), reason="no gfortran")
def test_check_and_lookup_by_source_hash(tmp_path, monkeypatch):
    # the mechanism, with a checker configured for the test only
    # (only offload compilers are allowed as witnesses; gfortran
    # stands in here because it is installed, bypassing validate)
    monkeypatch.setattr(W, "checkers", lambda: {"gfortran": {
        "lang": "f90", "command": "gfortran -ffree-line-length-none "
        "-fsyntax-only", "version": "gfortran --version"}})
    ok = W.check("p-ok", "program p\n  integer :: i\n  i = 1\nend program p\n",
                 "f90", "sha1")
    bad = W.check("p-bad", "program p\n  i = \nend program p\n", "f90", "sha2")
    assert ok["result"] == "accept" and bad["result"] == "reject"
    path = tmp_path / "w.yaml"
    W.write([ok, bad], path)
    monkeypatch.setattr(W, "DATA", path)
    W._rows.cache_clear()
    monkeypatch.setattr(W, "_rows", lambda p=str(path): tuple(
        yaml.safe_load(path.read_text())["witnesses"]))
    assert W.accepted("p-ok", "sha1").startswith("gfortran")
    assert W.accepted("p-ok", "other-sha") is None   # the source changed
    assert W.accepted("p-bad", "sha2") is None


def test_only_witness_only_offload_compilers_not_under_test_are_accepted():
    """Owner's choice 2026-10-23: NVHPC or upstream LLVM clang/flang, flagged
    witness_only: true; never gfortran/gcc, never a toolchain under test."""
    ok = {"upstream_flang": {"kind": "offload_compiler", "witness_only": True,
                             "lang": "f90", "command": "/opt/llvm/bin/flang "
                             "-fopenmp -fsyntax-only"},
          # NVHPC is under test now, so it names its family
          # (never a witness of its own family's cases)
          "nvhpc_c": {"kind": "offload_compiler", "witness_only": True,
                      "family": "nvhpc", "lang": "c",
                      "command": "nvc -mp=gpu -c"}}
    assert set(W.checkers({"independent_checkers": ok})) == set(ok)
    for bad in (
            {"nvhpc_c": {"kind": "offload_compiler", "witness_only": True,
                         "lang": "c", "command": "nvc -mp=gpu -c"}},
            {"x": {"kind": "offload_compiler", "witness_only": True,
                   "family": "cce", "lang": "c", "command": "craycc"}},
            {"g": {"kind": "offload_compiler", "lang": "f90",
                   "command": "/opt/llvm/bin/flang"}},          # no flag
            {"gfortran": {"kind": "offload_compiler", "witness_only": True,
                          "lang": "f90", "command": "gfortran -fopenmp"}},
            {"x": {"kind": "offload_compiler", "witness_only": True,
                   "lang": "c", "command": "craycc -fopenmp"}},  # under test
            {"cce21": {"kind": "offload_compiler", "witness_only": True,
                       "lang": "f90", "command": "/x/flang"}},
            {"y": {"kind": "syntax_checker", "witness_only": True,
                   "lang": "f90", "command": "/x/flang"}}):
        with pytest.raises(ValueError):
            W.checkers({"independent_checkers": bad})


def test_a_compiler_inside_a_toolchain_under_test_is_no_witness():
    """AFAR's internal flang (lib/llvm/bin/flang) and CCE's
    clang (cce-clang) are the compilers under test under another name."""
    from offload.engine.toolchains import AFAR_BIN
    afar_root = AFAR_BIN.rsplit("/bin", 1)[0]
    for cmd in (f"{afar_root}/lib/llvm/bin/flang -fopenmp -fsyntax-only",
                "/opt/cray/pe/cce/19.0.0/cce-clang/x86_64/bin/clang -fopenmp"):
        with pytest.raises(ValueError, match="under test"):
            W.checkers({"independent_checkers": {"x": {
                "kind": "offload_compiler", "witness_only": True,
                "lang": "f90", "command": cmd}}})
    assert W.checkers({"independent_checkers": {"llvm": {
        "kind": "offload_compiler", "witness_only": True, "lang": "f90",
        "command": "/opt/upstream-llvm/bin/flang -fopenmp"}}})


def test_a_witness_never_counts_for_its_own_family(monkeypatch):
    """NVHPC witnesses AMD cases, never NVHPC ones (ruling D)."""
    monkeypatch.setattr(W, "checkers", lambda data=None: {
        "nvhpc_f90": {"kind": "offload_compiler", "witness_only": True,
                      "family": "nvhpc", "lang": "f90", "command": "x"}})
    monkeypatch.setattr(W, "_rows", lambda path=None: (
        {"program": "p", "checker": "nvhpc_f90", "version": "25.11",
         "result": "accept", "sha256": "s"},))
    assert W.accepted("p", "s", "cce") == "nvhpc_f90 25.11"
    assert W.accepted("p", "s", "nvhpc") is None


def test_nvhpc_witnesses_are_configured_for_the_other_families():
    """NVHPC on wingtip is the configured witness (Fortran
    OpenMP, Fortran OpenACC, C OpenMP), family nvhpc, run over ssh."""
    cs = W.checkers()
    assert {"nvhpc_f90", "nvhpc_acc", "nvhpc_c", "nvhpc269_f90"} <= set(cs)
    assert {c["family"] for c in cs.values()} == {"nvhpc"}
    assert {c["machine"] for c in cs.values()} == {"wingtip"}
    assert cs["nvhpc_acc"]["model"] == "acc" and \
        "-acc=gpu" in cs["nvhpc_acc"]["command"]


def test_an_accept_is_no_witness_when_the_family_accepts_illegal_variants(
        monkeypatch):
    """(ruling R2): nvc compiles the illegal C
    defaultmap(none) variants, so NVHPC's accept of a defaultmap(none)
    program (any language of the family) is no witness; an atom whose
    illegal variants the family rejects keeps its witness."""
    cs = {n: {"kind": "offload_compiler", "witness_only": True,
              "family": "nvhpc", "lang": lang, "command": "x"}
          for n, lang in (("nvhpc_f90", "f90"), ("nvhpc_c", "c"))}
    monkeypatch.setattr(W, "checkers", lambda data=None: cs)
    rows = (
        {"program": "p", "atom": "omp.clause.defaultmap.none",
         "checker": "nvhpc_f90", "version": "25.11", "result": "accept",
         "sha256": "s"},
        {"program": "q", "atom": "omp.clause.map.to",
         "checker": "nvhpc_f90", "version": "25.11", "result": "accept",
         "sha256": "t"},
        {"program": "p-c-illegal", "calibrates": "omp.clause.defaultmap.none",
         "checker": "nvhpc_c", "version": "25.11", "result": "accept",
         "sha256": "u"},
        {"program": "q-illegal", "calibrates": "omp.clause.map.to",
         "checker": "nvhpc_f90", "version": "25.11", "result": "reject",
         "sha256": "v"})
    monkeypatch.setattr(W, "_rows", lambda path=None: rows)
    assert W.accepted("p", "s", "cce") is None
    assert W.uncalibrated(rows[0]) == ["p-c-illegal"]
    assert W.accepted("q", "t", "cce") == "nvhpc_f90 25.11"
    # a calibration row is never a witness of its own program
    assert W.accepted("p-c-illegal", "u", "cce") is None


def test_the_recorded_defaultmap_none_witness_is_uncalibrated():
    """The committed data: NVHPC's accepts of omp50/52/60-clause-
    defaultmap-none count for nothing (the illegal C variants compile)."""
    for v in ("50", "52", "60"):
        assert W.accepted(f"omp{v}-clause-defaultmap-none", "", "cce") is None
    assert W.illegal_variants("omp52-clause-defaultmap-none")
