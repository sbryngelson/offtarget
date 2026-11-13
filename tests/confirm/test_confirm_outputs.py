"""Tests of the confirmer's outputs: confirmed bugs without a finding, agent decisions, the findings index, the minimizer, regression mode, claim mismatches and the validation rules."""


# ---- Confirmed catalog bugs without a finding ----------------------------------------

import json

import pytest

from offload.engine.confirm import backlog as B


def _res(pid, tc, mode, outcome, reason, verdict="compiler_bug",
         findings=(), related=(), kind="catalog", lang="f90"):
    arch = "gfx90a" if tc.endswith("_g90") else "gfx942"
    return {"case": {"case_id": f"{kind}:{pid}:{tc}:{arch}:{mode}",
                     "toolchain": tc, "arch": arch, "mode": mode,
                     "outcome": outcome, "reason": reason,
                     "program": {"kind": kind, "ident": pid,
                                 "lang": lang}},
            "verdict": verdict, "rule": "R20-runtime-bug",
            "findings": [{"file": f} for f in findings],
            "related": [{"file": f} for f in related]}


@pytest.fixture
def batch(tmp_path):
    rows = [
        # one run-time group across versions and compilers of a family
        _res("omp52-clause-x", "cce19", "unified", "wrong_answer",
             "check_fail"),
        _res("omp60-clause-x", "cce21_g90", "copy", "wrong_answer",
             "check_fail"),
        # a link failure groups by its symbol, across programs
        _res("omp52-clause-y", "cce20", "unified", "rejected",
             "link_undefined_symbol: lld: error: undefined symbol: _F"),
        _res("omp52-clause-z", "cce21", "copy", "rejected",
             "link_undefined_symbol: lld: error: undefined symbol: _F"),
        # linked (instance or related), not a bug, or not catalog: out
        _res("omp52-clause-w", "afar", "unified", "wrong_answer", "c",
             findings=["data/findings/w.f90"]),
        _res("omp52-clause-v", "afar", "unified", "wrong_answer", "c",
             related=["data/findings/v.f90"]),
        _res("omp52-clause-u", "afar", "unified", "wrong_answer", "c",
             verdict="needs_human"),
        _res("s1:3", "afar", "unified", "wrong_answer", "c", kind="fuzz"),
    ]
    p = tmp_path / "batch.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return p


def test_groups_by_signature(batch):
    gs = B.groups(B.unlinked(batch))
    assert {k: len(v) for k, v in gs.items()} == {
        "cce|f90|rejected|link _F": 2, "cce|f90|wrong|omp*-clause-x": 2}


def test_check_needs_a_reason_for_every_group(batch):
    gs = B.groups(B.unlinked(batch))
    data = {"version": 1, "groups": [
        {"key": "cce|f90|wrong|omp*-clause-x", "cells": 2, "why": "w"},
        {"key": "afar|f90|ice|gone", "cells": 3, "why": "x"}]}
    problems = B.check(gs, data)
    assert any("new backlog group" in p and "link _F" in p
               for p in problems)
    assert any("no longer in the backlog" in p for p in problems)
    data["groups"][0]["cells"] = 1
    assert any("2 cells, recorded 1" in p for p in B.check(gs, data))


def test_the_committed_backlog_has_a_reason_for_every_group():
    if not B.BATCH.is_file():
        pytest.skip("needs results/confirm/batch_full.jsonl (git-ignored: "
                    "docs/tooling/setup.md, docs/tooling/regenerate.md)")
    gs = B.groups(B.unlinked())
    data = B.load()
    assert B.check(gs, data) == []
    assert B.DOC.read_text() == B.render(gs, data)


# ---- Agent decisions of needs_human results and the spot-check -------------------------------------------

from offload.engine.confirm import decisions as D


def R(cid, verdict, rule, tc="cce21", outcome="wrong_answer", reason="",
      why="", findings=()):
    return {"case": {"case_id": cid, "toolchain": tc, "outcome": outcome,
                     "reason": reason, "mode": "unified",
                     "program": {"ident": cid.split(":", 1)[1]}},
            "verdict": verdict, "rule": rule, "reason": why,
            "findings": list(findings)}


def test_signature_names_the_cause():
    r = R("fuzz:s1:1:cce19", "unsupported", "R11c-later-form-unclaimed",
          tc="cce19", outcome="rejected",
          why="later form declare-target-enter (the enter clause ...)")
    assert D.signature(r).endswith("form declare-target-enter")
    r = R("fuzz:s1:2:cce21", "compiler_bug", "R10-compile-ice",
          outcome="ice", findings=[{"file": "data/findings/x.f90"}])
    assert D.signature(r).endswith("finding x.f90")
    a = R("fuzz:s1:3:afar", "needs_human", "R22-expected-weak",
          tc="afar", outcome="crash", reason="crash: SIGSEGV at 0x7f12")
    b = R("fuzz:s1:4:afar", "needs_human", "R22-expected-weak",
          tc="afar", outcome="crash", reason="crash: SIGSEGV at 0x7f99")
    assert D.signature(a) == D.signature(b)


def test_decisions_apply_to_needs_human_only():
    decs = [D.Decision("d1", "compiler_bug", "probe", rule="R22-*",
                       toolchains=("afar",), outcomes=("crash",),
                       reason="SIGSEGV")]
    rs = [R("fuzz:s1:3:afar", "needs_human", "R22-expected-weak",
            tc="afar", outcome="crash", reason="crash: SIGSEGV"),
          R("fuzz:s1:4:afar", "needs_human", "R22-expected-weak",
            tc="afar", outcome="crash", reason="crash: SIGABRT"),
          R("fuzz:s1:5:afar", "flaky", "R09-flaky", tc="afar",
            outcome="crash", reason="crash: SIGSEGV")]
    got = D.apply(rs, decs)
    assert [(g["final"], g["decided_by"]) for g in got] == [
        ("compiler_bug", "d1"), ("needs_human", "rules"),
        ("flaky", "rules")]


def test_spot_sample_is_seeded_and_covers_every_class():
    rs = [R(f"fuzz:s1:{k}:cce21", "compiler_bug", "R10") for k in range(95)]
    rs += [R("fuzz:s1:999:cce21", "unsupported", "R05"),
           R("fuzz:s1:998:cce21", "needs_human", "R22")]
    s = D.spot_sample(rs)
    assert set(s) == {"compiler_bug", "unsupported"}
    assert len(s["compiler_bug"]) == 10 and len(s["unsupported"]) == 1
    assert s == D.spot_sample(rs)
    g = D.spot_groups(rs, s)
    assert sum(len(v) for v in g.values()) == 11


def test_decision_data_loads():
    d = D.load()
    ids = [x.id for x in d["decisions"]]
    assert len(ids) == len(set(ids))
    for x in d["decisions"]:
        assert x.basis and x.verdict


def test_case_sample_caps_each_class_and_keeps_agent_decisions_apart():
    """The case-level spot sample is a seeded 10% of
    each final verdict class decided by the rules (needs_human too), at
    least one and at most CAP cases, and the agent-decided cells as their
    own class; the agreement table counts per class."""
    rs = [R(f"fuzz:s1:{k}:cce21", "compiler_bug", "R10") for k in range(900)]
    rs += [R(f"fuzz:s1:{k}:cce20", "unsupported", "R05") for k in range(30)]
    rs += [R(f"fuzz:s1:{k}:afar", "needs_human", "R22", tc="afar")
           for k in range(40)]
    fin = D.apply(rs, [D.Decision("d1", "compiler_bug", "b", rule="R22",
                                  cases=tuple(f"fuzz:s1:{k}:afar"
                                              for k in range(20)))])
    s = D.case_sample(fin, cap=60)
    assert len(s["compiler_bug"]) == 60          # 10% of 900, capped
    assert len(s["unsupported"]) == 3
    assert len(s["needs_human"]) == 2            # the 20 left undecided
    assert len(s["agent-decided"]) == 2          # the 20 d1 cells
    assert all(c.startswith("fuzz:s1:") and c.endswith(":afar")
               for c in s["agent-decided"])
    assert s == D.case_sample(fin, cap=60)
    own = D.case_sample(fin, cap=60, own_class=("d1",))
    assert len(own["agent-decided d1"]) == 2 and "agent-decided" not in own
    checks = [{"case": s["unsupported"][0], "agree": True, "note": "x"},
              {"case": s["unsupported"][1], "agree": False, "note": "y"}]
    t = D.case_agreement(s, checks)
    assert t["unsupported"] == {"sampled": 3, "read": 2, "agree": 1}
    assert t["compiler_bug"]["read"] == 0
    rec = [{"case": c, "class": k, "agree": True, "note": "n"}
           for k, v in s.items() for c in v]
    assert D.sample_of(rec) == s


def test_own_sample_class_is_data():
    """The decisions sampled as a class of their own
    are named in the decisions file (own_sample_class), not in code."""
    d = D.load()
    assert D.own_classes(d["decisions"]) == (
        "D9-cce20-declare-target-enter",)
    assert D.own_classes([D.Decision("x", "compiler_bug", "b")]) == ()


# ---- The findings index (data/findings/index.yaml and the fuzz findings) -------------------------------------------

from pathlib import Path

from offload.engine.confirm import findings as FI

ROOT = Path(__file__).resolve().parent.parent.parent

GUARDED = """program t
  !$omp target parallel map(tofrom: a)
  if (omp_get_thread_num() == 0) then
  end if
  !$omp end target parallel
end program t
"""


def test_every_finding_file_is_indexed():
    idx = FI.load_index()
    files = {f.file for f in idx}
    for p in sorted((ROOT / "data" / "findings").glob("*.*")):
        if p.suffix in (".f90", ".c"):
            assert str(p.relative_to(ROOT)) in files, p.name
    fuzz = [p for p in (ROOT / "data" / "findings" / "fuzz").glob("*.f90")]
    assert all(str(p.relative_to(ROOT)) in files for p in fuzz)


def test_fuzz_header_parsed():
    f = next(f for f in FI.load_index() if f.file.endswith("b3-188-cce19.f90"))
    assert f.toolchains == ("cce19", "cce20", "cce21")
    assert f.outcome == "ice" and "Unexpected schedule" in f.message
    f = next(f for f in FI.load_index() if f.file.endswith("1131-afar.f90"))
    assert f.outcome == "crash" and f.toolchains == ("afar",)
    assert f.constructs


GUARDED2 = GUARDED.replace("!$omp target parallel map(tofrom: a)",
                           "!$omp target parallel map(tofrom: a) "
                           "num_threads(4)")

SMALL = [
    FI.Finding("data/findings/a.f90", ("cce19", "cce20", "cce21"), "f90",
               "ice", "unhandled construct type",
               sites={"cce19": "v_openmp.c:7617"}),
    FI.Finding("data/findings/b.f90", ("cce19", "cce20", "cce21"), "f90",
               "wrong_answer", constructs=frozenset({"dir:target parallel",
                                                     "clause:num_threads"})),
    FI.Finding("data/findings/c.c", ("cce19",), "c", "wrong_answer",
               programs=("omp52-c-clause-map-delete",),
               constructs=frozenset({"clause:delete"})),
    FI.Finding("data/findings/d.f90", ("cce21",), "f90", "wrong_answer",
               modes=("copy",), constructs=frozenset({"dir:target parallel",
                                                       "clause:num_threads"})),
    FI.Finding("data/findings/e.f90", ("afar",), "f90", "crash", "SIGSEGV",
               constructs=frozenset({"dir:target parallel",
                                     "clause:num_threads"})),
    FI.Finding("data/findings/f.f90", ("cce20",), "f90", "wrong_answer",
               constructs=frozenset({"dir:target parallel"})),
]

ICE = ("ice: INTERNAL COMPILER ERROR:  \"unhandled construct type\" "
       "(/workspace/crayftn/pdgcs/v_openmp.c, line {}, version 0abc)")


def test_same_ice_site_is_one_finding():
    got = FI.dedupe("cce19", "f90", "ice", ICE.format(7617), GUARDED,
                    findings=SMALL)
    assert [d["file"] for d in got] == ["data/findings/a.f90"]
    # another front end is another finding
    assert FI.dedupe("cce19", "c", "ice", ICE.format(7617), GUARDED,
                     findings=SMALL) == []


def test_different_ice_site_or_mode_is_not_a_duplicate():
    """Probes: another site of the same release, a
    release whose site the finding does not record (related only), a mode
    the finding does not list."""
    assert FI.dedupe("cce19", "f90", "ice", ICE.format(7814), GUARDED,
                     findings=SMALL) == []
    rel = FI.dedupe("cce21", "f90", "ice", ICE.format(8197), GUARDED,
                    findings=SMALL, related=True)
    assert [(d["file"], d["kind"]) for d in rel] == [("data/findings/a.f90",
                                                      "related")]
    assert FI.dedupe("cce21", "f90", "ice", ICE.format(8197), GUARDED,
                     findings=SMALL) == []
    got = FI.dedupe("cce21", "f90", "wrong_answer", "check_fail", GUARDED2,
                    mode="unified", findings=SMALL)
    assert "data/findings/d.f90" not in [d["file"] for d in got]
    got = FI.dedupe("cce21", "f90", "wrong_answer", "check_fail", GUARDED2,
                    mode="copy", findings=SMALL)
    assert "data/findings/d.f90" in [d["file"] for d in got]


def test_runtime_signature_needs_two_key_constructs():
    got = FI.dedupe("cce20", "f90", "wrong_answer", "check_fail", GUARDED2,
                    findings=SMALL)
    assert [d["file"] for d in got] == ["data/findings/b.f90"]
    # one construct alone (f.f90) never matches; the program without
    # num_threads matches neither
    assert FI.dedupe("cce20", "f90", "wrong_answer", "check_fail", GUARDED,
                     findings=SMALL) == []
    # a crash is another group than a wrong answer
    assert FI.dedupe("cce20", "f90", "crash", "crash: SIGSEGV", GUARDED2,
                     findings=SMALL) == []


def test_crash_needs_the_same_signal():
    assert [d["file"] for d in FI.dedupe(
        "afar", "f90", "crash", "crash: SIGSEGV", GUARDED2,
        findings=SMALL)] == ["data/findings/e.f90"]
    assert FI.dedupe("afar", "f90", "crash", "crash: SIGABRT", GUARDED2,
                     findings=SMALL) == []


def test_named_catalog_program_matches():
    got = FI.dedupe("cce19", "c", "wrong_answer", "check_fail", "",
                    "omp52-c-clause-map-delete", findings=SMALL)
    assert got and got[0]["why"].startswith("program")
    assert FI.dedupe("afar", "c", "wrong_answer", "check_fail", "",
                     "omp52-c-clause-map-delete", findings=SMALL) == []


def test_fuzz_ice_site_parsed():
    f = next(f for f in FI.load_index()
             if f.file.endswith("1391-cce20.f90"))
    assert f.sites == {"cce20": "v_mt_translate.c:5607"}


def test_related_link_ignores_the_site_in_a_fuzz_header_message():
    """1391-cce20's message embeds its own site; a
    same-message ICE of another release is related."""
    f = next(f for f in FI.load_index()
             if f.file.endswith("1391-cce20.f90"))
    r = ('ice: INTERNAL COMPILER ERROR:  "ACC - barrier/reset/protected last '
         'private not supported" (/workspace/crayftn/pdgcs/v_mt_translate.c,'
         ' line 5798, version 03f45ce)')
    assert FI.match(f, "cce21", "f90", "ice", r, "")[0] == "related"
    r2 = r.replace("5798", "5607")
    assert FI.match(f, "cce20", "f90", "ice", r2, "")[0] == "duplicate"


def test_named_program_needs_the_same_group():
    """A wrong answer is no instance of a crash
    finding even when the finding names the program."""
    f = FI.Finding("data/findings/s.c", ("cce19",), "c", "crash", "SIGSEGV",
                   programs=("omp52-c-clause-dist_schedule*",))
    assert FI.match(f, "cce19", "c", "wrong_answer", "check_fail", "",
                    "omp52-c-clause-dist_schedule-chunk_size") is None
    assert FI.match(f, "cce19", "c", "crash", "crash: SIGSEGV", "",
                    "omp52-c-clause-dist_schedule-chunk_size")[0] == \
        "duplicate"


def test_diagnostic_dedupe_needs_the_findings_constructs():
    """Spot check: CCE 21's ftn-1510 for a teams distribute loop
    variable under default(none) has the message of the linear-modifier
    finding but none of its constructs: related, not an instance. A link
    failure keeps the message match (its symbol names the defect)."""
    lin = FI.Finding("data/findings/lin.f90", ("cce21",), "f90", "rejected",
                     "must have its data scope explicitly declared",
                     constructs=frozenset({"clause:linear",
                                           "dir:parallel do"}))
    reason = ('diagnostic: ftn-1510 ftn: ERROR P | Variable "I" must have '
              'its data scope explicitly declared because DEFAULT(NONE)')
    prog = ("program p\n!$omp target teams distribute default(none)\n"
            "do i = 1, 4\nend do\nend program p\n")
    got = FI.dedupe("cce21", "f90", "rejected", reason, prog,
                    findings=[lin], related=True)
    assert [(d["file"], d["kind"]) for d in got] == [
        ("data/findings/lin.f90", "related")]
    with_lin = prog.replace("default(none)", "default(none)\n"
                            "!$omp parallel do linear(x: val)")
    got = FI.dedupe("cce21", "f90", "rejected", reason, with_lin,
                    findings=[lin])
    assert got and got[0]["kind"] == "duplicate"
    link = FI.Finding("data/findings/udr.f90", ("afar",), "f90", "rejected",
                      "flang_rt_verbose_abort",
                      constructs=frozenset({"clause:pair_t"}))
    got = FI.dedupe("afar", "f90", "rejected", "link_undefined_symbol: "
                    "undefined symbol: flang_rt_verbose_abort", prog,
                    findings=[link])
    assert got and got[0]["kind"] == "duplicate"


def test_fuzz_runtime_instance_needs_a_distinctive_signature():
    """In a fuzz program a run-time failure is an
    instance only through a key construct that is not common in fuzz
    programs, or the finding's own run-time message; else related."""
    common = FI.Finding("data/findings/fuzz/x.f90", ("afar",), "f90",
                        "crash", "SIGSEGV",
                        constructs=frozenset({"dir:do", "dir:parallel"}))
    prog = ("program p\n!$omp target\n!$omp parallel\n!$omp do\n"
            "do i = 1, 4\nend do\n!$omp end parallel\n!$omp end target\n"
            "end program p\n")
    got = FI.dedupe("afar", "f90", "crash", "crash: SIGSEGV", prog,
                    "s1:8131", findings=[common], related=True)
    assert [d["kind"] for d in got] == ["related"]
    # a catalog-like id keeps the old two-construct rule
    got = FI.dedupe("afar", "f90", "crash", "crash: SIGSEGV", prog,
                    "omp52-x", findings=[common])
    assert got and got[0]["kind"] == "duplicate"
    msg = FI.Finding("data/findings/fuzz/y.f90", ("afar",), "f90", "crash",
                     "Failed to process data before launching",
                     constructs=frozenset({"dir:do", "dir:parallel"}))
    got = FI.dedupe("afar", "f90", "crash", "crash: SIGABRT", prog,
                    "s1:8411", findings=[msg],
                    output="omptarget error: Failed to process data before "
                    "launching the kernel.")
    assert got and got[0]["kind"] == "duplicate"


def test_fuzz_runtime_message_the_finding_does_not_name_is_related():
    """(spot check of s1 seed 1439 on CCE 20): a
    fuzz program's wrong answer that prints a runtime error ("Unhandled
    Reduction!!!") is not an instance of a finding without that message,
    even with the finding's distinctive key constructs; related."""
    f = FI.Finding("data/findings/x-bind.f90", ("cce20",), "f90",
                   "wrong_answer", "",
                   constructs=frozenset({"clause:bind", "dir:loop"}))
    prog = ("program p\n!$omp target\n!$omp loop bind(thread)\n"
            "do i = 1, 4\nend do\n!$omp end target\nend program p\n")
    got = FI.dedupe("cce20", "f90", "wrong_answer", "checksum=1 expected=2",
                    prog, "s1:1439", findings=[f], related=True,
                    output="Cray Fortran : 0 errors\nUnhandled Reduction!!! ")
    assert [d["kind"] for d in got] == ["related"]
    assert "Unhandled Reduction" in got[0]["why"]
    got = FI.dedupe("cce20", "f90", "wrong_answer", "checksum=1 expected=2",
                    prog, "s1:1439", findings=[f], output="Cray Fortran")
    assert got and got[0]["kind"] == "duplicate"


def test_fuzz_finding_names_its_runtime_message(tmp_path, monkeypatch):
    """A minimized fuzz finding may name the runtime
    message of its failure ("! message: <regex>"); a fuzz failure printing
    it is then an instance (by the key constructs), one printing another
    runtime error is not."""
    monkeypatch.setattr(FI, "ROOT", tmp_path)
    (tmp_path / "index.yaml").write_text("findings: []\n")
    fz = tmp_path / "fuzz"
    fz.mkdir()
    (fz / "s1-1-cce20.f90").write_text(
        "! Minimized by compliance.fuzz_min from fuzz seed 1 (fuzz-3).\n"
        "! toolchain: cce20 (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)"
        "\n! failure: run_error (exit_status)\n"
        "! message: Variable not found in present table\n"
        "program p\n!$omp target data map(to: xc)\n"
        "!$omp target map(present, tofrom: xc)\n!$omp end target\n"
        "!$omp end target data\nend program p\n")
    fs = FI.load_index(tmp_path / "index.yaml", fz)
    assert fs[0].message == "Variable not found in present table"
    prog = ("program p\n!$omp target data map(to: xc, ia)\n"
            "!$omp target map(present, tofrom: xc)\n!$omp end target\n"
            "!$omp end target data\nend program p\n")
    out = "ACC: libcrayacc/acc_runtime.c:890 CRAY_ACC_ERROR - Variable " \
        "not found in present table"
    got = FI.dedupe("cce20", "f90", "run_error", "exit_status: 1", prog,
                    "s1:7", findings=fs, output=out, related=True)
    assert got and got[0]["kind"] == "duplicate"
    got = FI.dedupe("cce20", "f90", "run_error", "exit_status: 1", prog,
                    "s1:7", findings=fs, related=True,
                    output="CRAY_ACC_ERROR - Host region overlaps present "
                    "region")
    assert not any(d["kind"] == "duplicate" for d in got)


# --- The index's mode and arch scope from the data ---

def _cell(ident, tc, mode, arch, outcome="wrong_answer", verdict=
          "compiler_bug", text=GUARDED2, lang="f90", reason="check_fail"):
    return {"toolchain": tc, "lang": lang, "outcome": outcome,
            "reason": reason, "text": text, "ident": ident, "mode": mode,
            "arch": arch, "output": "", "verdict": verdict}


SCOPED = [
    FI.Finding("data/findings/p.c", ("cce19", "cce20", "cce21"), "c",
               "wrong_answer", modes=("copy",), arch=("gfx942",),
               programs=("omp52-c-clause-p",),
               constructs=frozenset({"clause:p"})),
    FI.Finding("data/findings/q.c", ("cce19",), "c", "wrong_answer",
               modes=("unified",), arch=("gfx942",),
               programs=("omp52-c-clause-p",),
               constructs=frozenset({"clause:q"})),
    FI.Finding("data/findings/r.f90", ("afar",), "f90", "wrong_answer",
               modes=("unified",), arch=("gfx942",),
               constructs=frozenset({"dir:target parallel",
                                     "clause:num_threads"})),
]


def test_derive_scope_adds_the_arch_of_linked_twin_cells():
    cells = [_cell("omp52-c-clause-p", "cce19", "copy", "gfx942", lang="c"),
             _cell("omp52-c-clause-p", "cce19_g90", "copy", "gfx90a",
                   lang="c"),
             # unified: q's recorded scope covers it; p is not extended
             _cell("omp52-c-clause-p", "cce19", "unified", "gfx942",
                   lang="c"),
             # not evidence about the compiler: never extends a scope
             _cell("omp52-c-clause-p", "cce20_g90", "unified", "gfx90a",
                   lang="c", verdict="our_bug")]
    s = FI.derive_scope(cells, SCOPED, arches=("gfx942", "gfx90a"),
                        modes=("unified", "copy"))
    p = s["data/findings/p.c"]
    assert p["arch"] == ["gfx942", "gfx90a"] and p["modes"] == ["copy"]
    assert p["linked"] == {("copy", "gfx942"): 1, ("copy", "gfx90a"): 1}
    q = s["data/findings/q.c"]
    assert q["modes"] == ["unified"] and q["arch"] == ["gfx942"]
    # no linked cell: the recorded scope stays
    r = s["data/findings/r.f90"]
    assert r["linked"] == {} and r["modes"] == ["unified"]


# Follow-up: the split-CIF-record finding links a row only when the
# row's build path can cut the CIF ("-1" not followed by a digit), or, when
# the path is not recorded, when the row is CCE ftn at -O2/-O3
SPLIT = FI.Finding("data/findings/stress/split.f90", ("cce19", "cce20",
                                                      "cce21"), "f90", "ice",
                   r"free\(\): invalid pointer|double free or corruption",
                   arch=("gfx942", "gfx90a"), path_rule="cif_split")
HEAP = "ice: free(): invalid pointer"


def _split(**kw):
    return [(d["file"], d["kind"]) for d in FI.dedupe(
        kw.pop("tc", "cce19"), kw.pop("lang", "f90"), "ice",
        kw.pop("reason", HEAP), GUARDED, findings=[SPLIT], related=True,
        **kw)]


def test_split_finding_needs_the_drivers_own_abort():
    # a stress row: the reason is the exit, the heap message is the output
    cut = "/tmp/u/st-tu.plain-omp-12-1-abcd1234"
    assert FI.dedupe("cce19", "f90", "ice", "ice: stress.f90 exit 6",
                     GUARDED, findings=[SPLIT], build_dir=cut,
                     output="free(): invalid pointer") != []
    # optcg's abort prints a heap message too: another defect
    optcg = ('ice: ftn-2116 ftn: INTERNAL | "/opt/cray/pe/cce/20.0.2/cce/'
             'x86_64/bin/optcg" was terminated due to receipt of signal 06:'
             '  Aborted.')
    assert FI.dedupe("cce20", "f90", "ice", optcg, GUARDED, findings=[SPLIT],
                     build_dir=cut, output="double free or corruption (out)",
                     related=True) == []
    site = ('ice: INTERNAL COMPILER ERROR:  "Too few arguments on the stack" '
            '(/workspace/crayftn/pdgcs/v_fei.c, line 11730, version cc4d)')
    assert FI.dedupe("cce19", "f90", "ice", site, GUARDED, findings=[SPLIT],
                     build_dir=cut, output="free(): invalid pointer",
                     related=True) == []


def test_split_finding_links_a_recorded_path_that_cuts():
    got = _split(build_dir="/tmp/u/st-tu.plain-omp-12-1-abcd1234")
    assert got == [("data/findings/stress/split.f90", "duplicate")]
    # the source file name is part of the path
    assert _split(build_dir="/tmp/harness_x", source="t-1a.f90") == [
        ("data/findings/stress/split.f90", "duplicate")]


def test_split_finding_skips_a_recorded_path_that_cannot_cut():
    for d in ("/tmp/harness_1abc", "/tmp/u/st-tu.plain-omp-12-10-x",
              "/tmp/cce-cif/a-2aa", "/dev/shm/x-12"):
        assert _split(build_dir=d) == [], d
    # the rule is the finding's: an unrelated ICE finding is unaffected
    assert FI.dedupe("cce19", "f90", "ice", ICE.format(7617), GUARDED,
                     findings=SMALL, build_dir="/tmp/clean") != []


def test_split_finding_without_a_path_needs_cce_ftn_at_o2_or_o3():
    for opt in ("-O2", "-O3", "O2", "lto", "noinline"):
        assert _split(opt=opt) == [("data/findings/stress/split.f90",
                                    "related")], opt
    for opt in ("-O0", "O0", ""):
        assert _split(opt=opt) == [], opt
    assert _split(opt="-O2", lang="c") == []
    assert _split(opt="-O2", tc="afar") == []
    # another heap message is not this finding's
    assert _split(opt="-O2", reason="ice: malloc(): corrupted top size") == []


def test_committed_split_finding_has_the_path_rule():
    f = next(f for f in FI.load_index()
             if f.file.endswith("cce-ftn-cif-record-split-abort.f90"))
    assert f.path_rule == "cif_split"
    assert FI.path_cuts("/tmp/cce-cif/" + "a" * 202 + "-1aa/stress.f90")
    assert not FI.path_cuts("/tmp/cce-cif/" + "a" * 202 + "-2aa/stress.f90")


def test_the_construct_reader_joins_continuation_lines():
    """A clause on a continuation line belongs to
    its directive (Fortran `&` and `!$omp&`, C `\\`)."""
    from offload.engine.confirm.programs import constructs
    f = ("  !$omp target teams distribute &\n"
         "  !$omp& parallel do map(tofrom: a) &\n"
         "  !$omp   reduction(+: s)\n  do i = 1, n\n")
    got = constructs(f)
    # (the reader keeps at most four directive words)
    assert "dir:target teams distribute parallel" in got
    assert {"clause:map", "clause:reduction"} <= got
    c = ("#pragma omp target teams \\\n    distribute parallel for \\\n"
         "    map(tofrom: a[0:n])\nfor (i = 0; i < n; i++) ;\n")
    got = constructs(c)
    assert "dir:target teams distribute parallel" in got
    assert "clause:map" in got


# --- fortran-oop post-merge: keys that match only their own defect -----------------

def _oop(name):
    return next(f for f in FI.load_index()
                if f.file == f"data/findings/oop/{name}.f90")


UDR_LINK = ("link_undefined_symbol: ld.lld: error: undefined symbol: "
            "flang_rt_verbose_abort(char const*, ...)")


def test_udr_link_failure_is_not_the_dealloc_finding():
    """A declare-reduction program's flang_rt_verbose_abort link failure
    (afar-udr-derived-type-link's rows) shares only the undefined symbol
    with the DEALLOCATE finding: no duplicate of it, still of the udr
    finding."""
    udr_text = (ROOT / "data/findings/afar-udr-derived-type-link.f90"
                ).read_text()
    dealloc = _oop("afar-final-dealloc-device-link")
    assert FI.matches(dealloc, "afar", "f90", "rejected", UDR_LINK,
                      udr_text, "fuzz:s1:4242", "copy") is None
    udr = next(f for f in FI.load_index()
               if f.file.endswith("afar-udr-derived-type-link.f90"))
    assert FI.matches(udr, "afar", "f90", "rejected", UDR_LINK, udr_text,
                      "fuzz:s1:4242", "copy")


def test_dealloc_finding_keeps_its_own_cells():
    dealloc = _oop("afar-final-dealloc-device-link")
    text = (ROOT / "data/findings/oop/afar-final-dealloc-device-link.f90"
            ).read_text()
    assert FI.matches(dealloc, "afar", "f90", "rejected", UDR_LINK, text,
                      "oop-assignfinal-final-dealloc", "copy")
    # its key is a construct the confirmer never sees (as the strided
    # findings'): only its named programs link, never another program's
    # failure on the shared symbol, related or not
    udr_text = (ROOT / "data/findings/afar-udr-derived-type-link.f90"
                ).read_text()
    assert FI.match(dealloc, "afar", "f90", "rejected", UDR_LINK,
                    udr_text, "", "copy") is None


def test_oop_runtime_findings_do_not_link_generic_programs():
    """fuzz:n0:393 (CCE wrong answer) shares only `do` and `target teams
    distribute parallel` with the component-map reproducer: no link."""
    text = (ROOT / "data/findings/oop/controls/alloccomp-whole.f90"
            ).read_text()
    f = _oop("cce-copy-parent-to-component-tofrom-lost")
    assert FI.matches(f, "cce20", "f90", "wrong_answer",
                      "check_fail: checksum=1 ran_on_host=0 expected=2",
                      text, "fuzz:n0:393", "copy") is None


def test_every_oop_finding_links_its_own_programs():
    import yaml
    for d in yaml.safe_load((ROOT / "data/findings/index.yaml").read_text()
                            )["findings"]:
        if not d["file"].startswith("oop/"):
            continue
        f = _oop(d["file"][4:-4])
        reason = {"rejected": "diagnostic: x", "ice": "ice: x",
                  "crash": "crash: SIGABRT", "run_error":
                  "exit_status: 1"}.get(d["outcome"], "check_fail: x")
        text = (ROOT / "data" / "findings" / d["file"]).read_text()
        for pid in d["programs"]:
            assert FI.matches(f, d["toolchains"][0], d["lang"],
                              d["outcome"], reason, text, pid,
                              d["modes"][0]), (d["file"], pid)


def test_no_oop_runtime_finding_links_a_generic_fuzz_program():
    import yaml
    text = (ROOT / "data/findings/oop/controls/alloccomp-whole.f90"
            ).read_text()
    reason = {"crash": "crash: SIGABRT", "run_error": "exit_status: 1",
              "wrong_answer": "check_fail: checksum=1 ran_on_host=0"}
    for d in yaml.safe_load((ROOT / "data/findings/index.yaml").read_text()
                            )["findings"]:
        if not d["file"].startswith("oop/") or d["outcome"] not in reason:
            continue
        f = _oop(d["file"][4:-4])
        assert FI.match(f, d["toolchains"][0], "f90", d["outcome"],
                        reason[d["outcome"]], text, "fuzz:n0:393",
                        d["modes"][0]) is None, d["file"]


# ---- The general minimizer keeps the verdict (fake runner, no runs) --------------------------------------------


from offload.engine.confirm import collectors as C
from offload.engine.confirm import draft as DR
from offload.engine.confirm import minimize as MZ
from offload.engine.confirm import programs as P
from offload.engine.confirm.ingest import Index
from offload.engine.confirm.legality import Legality
from offload.engine.confirm.model import Case, ProgramRef, Provenance, Run
from offload.engine.confirm.store import Store

F = """program t
  implicit none
  integer :: a(8), i, s, bad
  a = 0
  s = 0
  bad = 1
  !$omp target teams distribute parallel do map(tofrom: a) num_teams(2)
  do i = 1, 8
    a(i) = i
  end do
  !$omp end target teams distribute parallel do
  s = sum(a)
  print *, s
end program t
"""

C_SRC = """#include <stdio.h>
int main(void) {
  int a[8], s = 0;
  int bad = 1;
  #pragma omp target teams distribute parallel for map(tofrom: a) num_teams(2)
  for (int i = 0; i < 8; i++) a[i] = i;
  s = a[7];
  printf("%d\\n", s);
  return 0;
}
"""


class FakeRunner:
    """Fails (wrong answer) while the program keeps its `bad = 1` line and
    a target directive."""
    machine = None

    def __init__(self):
        self.calls = 0

    def run(self, ref, toolchain, mode, opt="-O2", offload="mandatory",
            repeats=3):
        self.calls += 1
        bad = "bad = 1" in ref.text and ("target" in ref.text)
        r = Run("wrong_answer", "checksum=9", 0, "check_fail") if bad else \
            Run("correct_on_device", "checksum=7", 0)
        return [r] * repeats, Provenance(origin="run", host="fake")


def legal(ref):
    return Legality("legal", "test")


def confirm_stub(case, ctx, legality=None):
    v = "compiler_bug" if case.outcome == "wrong_answer" else "not_a_failure"
    return {"verdict": v, "rule": "stub"}


def make(text, lang):
    ref = ProgramRef("file", "t", lang, 52, text=text, expected="checksum=7")
    case = Case(ref, "cce21", "tuolumne", "gfx942", "unified",
                "wrong_answer", "check_fail", "checksum=9", 0)
    ctx = C.Context(Index(), Store(None), runner=FakeRunner(),
                    allow_run=True)
    return case, ctx


def test_minimizer_keeps_the_verdict_fortran():
    case, ctx = make(F, "f90")
    judge = MZ.Reconfirm(case, ctx, "compiler_bug", confirm=confirm_stub,
                         gate=legal)
    res = MZ.minimize_case(case, ctx, "compiler_bug", workers=1, judge=judge)
    assert res.lines_after < res.lines_before
    assert "bad = 1" in res.source and "target" in res.source
    assert judge(res.source)[0]
    assert "num_teams" not in res.source     # a clause went
    assert "s = sum(a)" not in res.source    # a statement went


def test_minimizer_keeps_the_verdict_c():
    case, ctx = make(C_SRC, "c")
    judge = MZ.Reconfirm(case, ctx, "compiler_bug", confirm=confirm_stub,
                         gate=legal)
    res = MZ.minimize_case(case, ctx, "compiler_bug", workers=2, judge=judge)
    assert res.lines_after < res.lines_before
    assert "bad = 1" in res.source and "#pragma omp target" in res.source


def test_minimizer_refuses_illegal_candidates():
    case, ctx = make(F, "f90")

    def gate(ref):
        # any candidate that drops `implicit none` is "illegal" here
        return Legality("legal" if "implicit none" in ref.text
                        else "illegal", "test")
    judge = MZ.Reconfirm(case, ctx, "compiler_bug", confirm=confirm_stub,
                         gate=gate)
    res = MZ.minimize_case(case, ctx, "compiler_bug", workers=1, judge=judge)
    assert "implicit none" in res.source


def test_program_set_candidates_delete_files():
    text = P.join_files([("m.f90", "module m\nend module m\n"),
                         ("u.f90", "module u\nend module u\n"),
                         ("main.f90", F)])
    names = [w for w, _ in MZ.generic_candidates(text)]
    assert "delete file u.f90" in names and "delete file main.f90" in names
    assert "delete file m.f90" not in names


def test_minimizer_never_edits_the_input():
    case, ctx = make(F, "f90")
    judge = MZ.Reconfirm(case, ctx, "compiler_bug", confirm=confirm_stub,
                         gate=legal)
    MZ.minimize_case(case, ctx, "compiler_bug", workers=1, judge=judge)
    assert case.program.text == F


def test_draft_and_promote(tmp_path):
    case, _ = make(F, "f90")
    result = {"case": case.to_dict(), "verdict": "compiler_bug",
              "rule": "R20-runtime-bug", "rationale": "r", "reason": "x",
              "citations": [], "legality": {"status": "legal",
                                            "basis": "test"},
              "expected": {"status": "trusted", "value": "checksum=7",
                           "sources": ["elision", "model"]},
              "witnesses": ["afar/gfx942/unified"], "withdrawn": [],
              "evidence": [], "actions": ["dedupe: new failure signature"],
              "minimized": F}
    d = DR.write_draft(result, tmp_path / "drafts")
    md = (d / "finding.md").read_text()
    assert "citation needed" in md and "R20-runtime-bug" in md
    assert "expected: checksum=7" in md
    fdir = tmp_path / "data" / "findings"
    fdir.mkdir(parents=True)
    (fdir / "index.yaml").write_text("findings:\n")
    out = DR.promote(d, "cce21-new-bug", fdir)
    assert out.name == "cce21-new-bug.f90"
    assert out.read_text().startswith("! # Draft finding")
    assert "cce21-new-bug.f90" in (fdir / "index.yaml").read_text()
    json.loads((d / "result.json").read_text())


def test_drafts_never_cite_gfortran_or_gcc_for_legality(tmp_path):
    """gfortran and gcc are never a legality
    witness (standing rule), so the draft's legality line names neither,
    whatever the gate's basis says."""
    case, _ = make(F, "f90")
    for basis in ("legal by the checkers (scope, offload.engine.rules, "
                  "gfortran -std=f2008, flang)",
                  "legal by the checkers (scope, offload.engine.rules, "
                  "gfortran -std=f2008)",
                  "legal by the checkers (scope, offload.engine.rules, "
                  "gcc -std=c11, clang); clang rejects it (x), which "
                  "alone does not count (RUL-NO-SELF-CHECK)",
                  "gfortran -std=f2008 rejects it: Error: x",
                  "gcc -std=c11 rejects it: t.c:1: error: y"):
        result = {"case": case.to_dict(), "verdict": "compiler_bug",
                  "rule": "R20-runtime-bug", "rationale": "r",
                  "reason": "x", "citations": [],
                  "legality": {"status": "legal", "basis": basis},
                  "expected": {"status": "trusted", "value": "c=7",
                               "sources": ["model"]},
                  "witnesses": [], "withdrawn": [], "evidence": [],
                  "actions": []}
        md = DR.render(result, "x")
        line = next(ln for ln in md.splitlines()
                    if ln.startswith("- legality:"))
        assert "gfortran" not in line and "gcc" not in line, line
        if "checkers" in basis:
            assert "offload.engine.rules" in line and "spec reading" in line


def test_draft_legality_handles_parentheses_in_a_checker_name():
    """The checker list splits at top-level
    commas, so a checker name with parentheses keeps its whole text, and a
    gfortran or gcc mention inside it or after the list is still dropped."""
    for basis, keep in (
            ("legal by the checkers (scope, offload.engine.rules (C tree, v52), "
             "gfortran -std=f2008 (no OpenMP), flang)", "offload.engine.rules (C tree, v52)"),
            ("legal by the checkers (scope (gcc -E first), offload.engine.rules)",
             "offload.engine.rules"),
            ("legal by the checkers (scope, offload.engine.rules); gcc rejects "
             "(x), which alone does not count", "offload.engine.rules")):
        line = DR.legality_text({"status": "legal", "basis": basis})
        assert "gfortran" not in line and "gcc" not in line, line
        assert keep in line and "spec reading" in line, line


class IceRunner:
    """An ICE whose message depends on the program: "site A" while the
    program keeps `bad = 1`, "site B" after any other deletion keeps a
    target directive."""
    machine = None

    def run(self, ref, toolchain, mode, opt="-O2", offload="mandatory",
            repeats=3):
        if "target" not in ref.text:
            r = Run("correct_on_device", "checksum=7", 0)
        elif "bad = 1" in ref.text:
            r = Run("ice", None, None, 'ice: INTERNAL COMPILER ERROR: "A" '
                    '(/w/v_a.c, line 10, version x)')
        else:
            r = Run("ice", None, None, 'ice: INTERNAL COMPILER ERROR: "B" '
                    '(/w/v_b.c, line 99, version x)')
        return [r] * repeats, Provenance(origin="run", host="fake")


def test_minimizer_keeps_the_ice_signature():
    """Spot check: an ICE of another site is not the same failure
    (the s1 seed 8634 reduction drifted to another CCE ICE)."""
    ref = ProgramRef("file", "t", "f90", 52, text=F, expected="checksum=7")
    case = Case(ref, "cce21", "tuolumne", "gfx942", "unified", "ice",
                'ice: INTERNAL COMPILER ERROR: "A" (/w/v_a.c, line 10, '
                'version x)')
    ctx = C.Context(Index(), Store(None), runner=IceRunner(),
                    allow_run=True)

    def stub(c, ctx, legality=None):
        return {"verdict": "compiler_bug", "rule": "R10-compile-ice"}
    judge = MZ.Reconfirm(case, ctx, "compiler_bug", confirm=stub, gate=legal)
    res = MZ.minimize_case(case, ctx, "compiler_bug", workers=1, judge=judge)
    assert "bad = 1" in res.source
    ok, why = judge(F.replace("  bad = 1\n", ""))
    assert not ok and "signature" in why


def test_a_fuzz_case_that_does_not_reproduce_is_reported():
    """A fuzz-format program whose first run gives another
    failure is left as it is (the minimizer said so), not an exception."""
    src = "! fuzz: kernels\n" + F
    ref = ProgramRef("file", "t", "f90", 52, text=src, expected="checksum=7")
    case = Case(ref, "cce21", "tuolumne", "gfx942", "unified", "ice",
                'ice: INTERNAL COMPILER ERROR: "Z" (/w/v_z.c, line 1, '
                'version x)')
    ctx = C.Context(Index(), Store(None), runner=IceRunner(),
                    allow_run=True)

    def stub(c, ctx, legality=None):
        return {"verdict": "compiler_bug", "rule": "R10-compile-ice"}
    judge = MZ.Reconfirm(case, ctx, "compiler_bug", confirm=stub, gate=legal)
    res = MZ.minimize_case(case, ctx, "compiler_bug", workers=1, judge=judge)
    assert res.source == src and "does not reproduce" in res.steps[0]


# ---- Regression mode (diff, rerun classes, plan) without runs --------------------------------------------

from offload.engine.confirm import ingest as I
from offload.engine.confirm import regress as R_5


def row(tc, outcome, value, ident="omp52-clause-x", mode="unified",
        reason=""):
    from offload.engine.toolchains import TOOLCHAINS
    return I.Row("catalog", ident, tc, TOOLCHAINS[tc].arch, mode, outcome,
                 reason, value)


def test_diff_classes():
    old = I.Index([row("cce21", "correct_on_device", "check=pass"),
                   row("cce21", "wrong_answer", "check=fail", "b"),
                   row("cce21", "wrong_answer", "check=fail", "c"),
                   row("cce21", "ice", None, "d", reason="ice: x (v.c, "
                       "line 7, version 03f45ce)")])
    new = [row("cce21_4", "wrong_answer", "check=fail"),
           row("cce21_4", "correct_on_device", "check=pass", "b"),
           row("cce21_4", "crash", None, "c"),
           row("cce21_4", "ice", None, "d", reason="ice: x (v.c, line 7, "
               "version f6a00ff)"),
           row("cce21_4", "rejected", None, "e")]
    got = {d["ident"]: d["class"] for d in R_5.diff("cce21_4", "cce21", new,
                                                  old)}
    assert got == {"omp52-clause-x": "regression", "b": "fix",
                   "c": "changed", "d": "same", "e": "new_cell"}


def test_rerun_class():
    f = {"outcomes": ["wrong_answer"] * 3}
    assert R_5.rerun_class({**f, "values": ["a", "b", "c"]},
                         {**f, "values": ["d", "e", "f"]}) == "same"
    assert R_5.rerun_class({**f, "values": ["a"] * 3},
                         {**f, "values": ["b"] * 3}) == "changed"
    ok = {"outcomes": ["correct_on_device"] * 3, "values": ["v"] * 3}
    assert R_5.rerun_class(ok, {**f, "values": ["a"] * 3}) == "regression"
    assert R_5.rerun_class({**f, "values": ["a"] * 3}, ok) == "fix"


def test_plan_names_every_language_and_mode():
    from tests.confirm.test_confirm import FakeRunner_3 as FakeRunner
    from offload.engine.confirm import jobs as J
    recs = R_5.plan("cce21_4", "cce21", submit=True,
                  scheduler=J.FluxScheduler(runner=FakeRunner()))
    envs = [r["env"] for r in recs]
    assert {(e.get("LANG_"), e.get("X")) for e in envs
            if e["JOB"] == "matrix"} == {(l, x) for l in ("f90", "c", "acc")
                                         for x in ("1", "0")}
    assert any(e["JOB"] == "fuzz" for e in envs)
    assert all(r["job"] for r in recs)


# ---- Claim mismatches and omp_vv flags through the confirmer ---------------------------------------------

import yaml

from offload.engine.confirm import triage as T


def mism(claim="supported", **kw):
    d = {"claim": claim, "cross_language": False, "older_doc": False,
         "confound": "", "general": False}
    d.update(kw)
    return d


def v(verdict, rule="R", outcome="rejected", cid="c"):
    return {"verdict": verdict, "rule": rule, "outcome": outcome,
            "case_id": cid}


@pytest.mark.parametrize("verdicts,want", [
    ([v("compiler_bug", "R10-compile-ice")], "compiler_bug"),
    ([v("copy_mode_failure")], "compiler_bug"),
    ([v("our_bug", "R13-oracle-wrong")], "our_error"),
    ([v("unsupported", "R05-unsupported")], "doc_overclaims"),
    ([v("unspecified", "R06-no-fixed-value")], "implementation_defined"),
    ([v("environment", "R01-environment")], "harness_issue"),
    ([v("needs_human", "R22-expected-weak")], "needs_human"),
    # one bug cell decides; an undecided other mode does not block it
    ([v("needs_human"), v("compiler_bug", "R20-runtime-bug")],
     "compiler_bug"),
    # our program wrong beats a compiler verdict in another cell
    ([v("compiler_bug"), v("our_bug")], "our_error"),
    ([], "needs_human"),
])
def test_supported_claim_dispositions(verdicts, want):
    assert T.mismatch_disposition(mism(), verdicts)[0] == want


def test_scope_and_partial_dispositions():
    un = [v("unsupported", "R05-unsupported")]
    assert T.mismatch_disposition(mism(cross_language=True), un)[0] == \
        "version_scope"
    assert T.mismatch_disposition(mism(confound="construct-specific: x"),
                                  un)[0] == "partial_support"
    ok = [v("not_a_failure", "R02-not-a-failure", "correct_on_device")]
    assert T.mismatch_disposition(mism("unsupported"), ok)[0] == \
        "doc_understates"
    assert T.mismatch_disposition(mism("unsupported", older_doc=True),
                                  ok)[0] == "version_scope"
    # a compile-error claim contradicted by an ignored clause
    assert T.mismatch_disposition(mism("unsupported"), un)[0] == \
        "doc_overclaims"


def test_flag_dispositions():
    bad = {"flag": "ours_bad_suite_passes"}
    assert T.flag_disposition(bad, [v("compiler_bug", "R11")])[0] == \
        "compiler_bug"
    assert T.flag_disposition(bad, [v("unsupported", "R05")])[0] == \
        "unsupported_form"
    assert T.flag_disposition(bad, [v("our_bug")])[0] == "our_error"
    ok = {"flag": "ours_ok_suite_fails"}
    # omp_vv is untrusted: the suite's failures go to an agent
    assert T.flag_disposition(ok, [v("needs_human", "R04-legality-unknown",
                                     "run_error")])[0] == "needs_human"
    assert T.flag_disposition(ok, [v("environment", "R01")])[0] == \
        "harness_issue"


def test_item_cases():
    m = T.Item("mismatch", "k", {"cells": [["omp52-x", "cce19", 1, "rejected"],
                                           ["omp52-x", "cce19_g90", 0,
                                            "rejected"]]})
    assert T.item_cases(m) == [("catalog", "omp52-x", "cce19", 1),
                               ("catalog", "omp52-x", "cce19_g90", 0)]
    f = T.Item("flag", "k", {"flag": "ours_ok_suite_fails", "toolchain":
                             "afar", "xnack": "1", "our_programs": ["p"],
                             "suite_tests": [["a.F90", "pass"],
                                             ["b.F90", "fail"]]})
    assert T.item_cases(f) == [("ompvv", "b.F90", "afar", 1)]
    f.info["flag"] = "ours_bad_suite_passes"
    assert T.item_cases(f) == [("catalog", "p", "afar", 1)]


def test_agent_decisions_apply_to_needs_human_only(tmp_path, monkeypatch):
    p = tmp_path / "d.yaml"
    p.write_text(yaml.safe_dump({"decisions": [
        {"key": "flag:f90:*", "disposition": "test_bug", "reason": "r"},
        {"key": "mismatch:x", "disposition": "compiler_bug",
         "reason": "s", "finding": "data/findings/f.f90"}]}))
    monkeypatch.setattr(T, "DECISIONS", p)
    a = T.Item("flag", "flag:f90:52:a", {}, disposition="needs_human")
    b = T.Item("mismatch", "mismatch:x", {}, disposition="needs_human")
    c = T.Item("mismatch", "mismatch:x", {}, disposition="our_error")
    T.apply_decisions([a, b, c])
    assert (a.disposition, a.decided_by) == ("test_bug", "agent")
    assert (b.disposition, b.info["finding"]) == ("compiler_bug",
                                                  "data/findings/f.f90")
    assert (c.disposition, c.decided_by) == ("our_error", "confirmer")


def test_spot_sample_is_a_seeded_tenth_per_class():
    items = [T.Item("mismatch", "k", {}, cases=[
        v("compiler_bug", cid=f"b{i}") for i in range(30)] + [
        v("unsupported", cid="u1"), v("needs_human", cid="h")])]
    s = T.spot_sample(items)
    assert len(s["compiler_bug"]) == 3 and s["unsupported"] == ["u1"]
    assert "needs_human" not in s
    assert s == T.spot_sample(items)


def test_decision_by_program_and_toolchain(tmp_path, monkeypatch):
    p = tmp_path / "d.yaml"
    p.write_text(yaml.safe_dump({"decisions": [
        {"programs": ["omp52-x"], "toolchains": ["cce21"],
         "disposition": "compiler_bug", "reason": "r21"},
        {"programs": ["omp52-x"], "disposition": "version_scope",
         "reason": "r"}]}))
    monkeypatch.setattr(T, "DECISIONS", p)
    a = T.Item("mismatch", "k1", {"toolchain": "cce21"},
               cases=[v("needs_human", cid="catalog:omp52-x:cce21:gfx942:"
                        "unified")], disposition="needs_human")
    b = T.Item("mismatch", "k2", {"toolchain": "cce19"},
               cases=[v("needs_human", cid="catalog:omp52-x:cce19:gfx942:"
                        "unified")], disposition="needs_human")
    T.apply_decisions([a, b])
    assert (a.disposition, b.disposition) == ("compiler_bug", "version_scope")


def test_render_tables(tmp_path):
    m = T.Item("mismatch", "k", {"model": "omp", "lang": "f90", "toolchain":
                                 "cce21", "atom": "omp.clause.map.to",
                                 "version": 52, "claimed": "supported [s]",
                                 "measured": "rejected", "source": "s",
                                 "page": "intro_openmp(7): DESCRIPTION "
                                 "[CCE 21.0.3]", "url": "u", "quote": "q",
                                 "claim": "supported"},
               cases=[v("unsupported", "R05-unsupported", cid="c1")],
               disposition="doc_overclaims", basis="R05")
    f = T.Item("flag", "f", {"lang": "c", "version": "52", "atom":
                             "omp.clause.map.always", "toolchain": "cce19",
                             "mode": "headline", "flag":
                             "ours_ok_suite_fails", "ours":
                             "correct_on_device", "suite_tests":
                             [["tests/5.2/x.c", "fail"]],
                             "upstream": "the test maps s.len only"},
               cases=[v("needs_human", "R04",
                        cid="ompvv:tests_5.2_x.c:cce19:gfx942:unified")],
               disposition="test_bug", basis="b", decided_by="agent")
    md = T.render_tables([m, f], {"compiler_bug": ["c1"]},
                         {"spot": [{"case_id": "c1", "agree": True}]})
    assert "| `clause.map.to` |" in md and "doc_overclaims" in md
    assert "Documentation overclaims" in md and "CCE 21.0.3" in md
    st = {"version": 1, "decision": "Maintainer decision: file upstream.",
          "corpus": {"path": "corpus/omp_vv", "repo": "a/b", "note": "n"},
          "active": {"repo": "c/d", "url": "u", "checked": "today"},
          "defects": [{"id": "d1", "title": "the mapper defect", "tests": [
              {"path": "tests/5.2/x.c", "defect": "s.len only",
               "status": "filed", "refs": [{"text": "c/d#1", "url": "v"}],
               "date": "2026-10-24"}]}]}
    up = T.render_upstream([m, f], st)
    assert "tests/5.2/x.c" in up and "s.len only" in up
    assert "| Filed: [c/d#1](v) (2026-10-24) |" in up
    with pytest.raises(ValueError, match="without a filing status"):
        T.render_upstream([m, f], dict(st, defects=[]))


def test_upstream_doc_names_the_corpus_commit():
    """Once corpus/omp_vv is a clone of the active repository,
    the doc says so with the commit (not "the archived ...")."""
    st = {"version": 1, "decision": "D.",
          "corpus": {"path": "corpus/omp_vv", "repo": "c/d",
                     "commit": "f7d95b34", "date": "2026-09-17",
                     "note": "the archived a/b d978684"},
          "active": {"repo": "c/d", "url": "u", "checked": "today"},
          "defects": []}
    up = T.render_upstream([], st)
    assert "is a clone of the active repository u at f7d95b34 " \
        "(2026-09-17; the archived a/b d978684)" in up
    assert "is the archived" not in up


def test_a_defect_without_a_flag_case_says_what_was_observed():
    """A drafted defect no flag case covers (the suite header's
    exit status) shows its own `observed` text instead of "No failing
    case here"."""
    st = {"version": 1, "decision": "D.",
          "corpus": {"path": "corpus/omp_vv", "repo": "c/d", "commit": "x",
                     "date": "d", "note": "n"},
          "active": {"repo": "c/d", "url": "u", "checked": "today"},
          "defects": [{"id": "h", "title": "exit status", "observed":
                       "51 runs exit 0 but report failed.", "tests": [
                           {"path": "ompvv/ompvv.h", "defect": "return err",
                            "status": "not_filed", "note": "draft"}]}]}
    up = T.render_upstream([], st)
    assert "51 runs exit 0 but report failed." in up
    assert "No failing case here." not in up
    assert "| ompvv/ompvv.h | return err | Not filed: draft |" in up


def test_upstream_doc_carries_the_filing_status(tmp_path):
    """docs/upstream/docs/upstream.md says, per test file, what upstream did (from
    catalog/upstream_status.yaml), and a defect covering several test
    files has one section."""
    st = T.upstream_status()
    paths = {t["path"]: t for d in st["defects"] for t in d["tests"]}
    assert paths["tests/5.2/declare_mapper/test_declare_mapper_iterator.c"][
        "status"] == "filed"
    assert {paths[p]["status"] for p in (
        "tests/5.1/target/test_target_map_iterators.c",
        "tests/5.1/target/test_target_map_iterators.F90")} == \
        {"already_fixed"}
    doc = (T.ROOT / "docs" / "upstream.md").read_text()
    assert "Filed: [OpenMP_VV#921]" in doc and "not filed" not in \
        doc.split("\n", 1)[0]
    assert doc.count("instantiates the list items v.data[0]") == 1
    # The drafts, filed as OpenMP_VV#922 and #923
    assert {paths[p]["status"] for p in (
        "tests/5.1/target/test_target_is_accessible.c",
        "tests/5.1/target/test_target_is_accessible.F90",
        "ompvv/ompvv.h")} == {"filed"}
    assert "## omp_target_is_accessible returning false fails the test" \
        in doc
    # The two files' notes differ since the rerun (one row each)
    assert "| tests/5.1/target/test_target_map_iterators.c |" in doc
    assert "| tests/5.1/target/test_target_map_iterators.F90 |" in doc
    bad = dict(st, defects=[{"id": "x", "title": "x", "tests": [
        {"path": "p.c", "defect": "d", "status": "filed"}]}])
    p = tmp_path / "s.yaml"
    p.write_text(yaml.safe_dump(bad))
    with pytest.raises(ValueError, match="without an issue or PR"):
        T.upstream_status(p)


def test_decision_key_is_a_pattern(tmp_path, monkeypatch):
    p = tmp_path / "d.yaml"
    p.write_text(yaml.safe_dump({"decisions": [
        {"key": "flag:f90:*:omp.clause.defaultmap*:cce19:*",
         "disposition": "compiler_bug", "reason": "r"}]}))
    monkeypatch.setattr(T, "DECISIONS", p)
    a = T.Item("flag", "flag:f90:52:omp.clause.defaultmap.scalar:cce19:"
               "headline:ours_ok_suite_fails", {}, disposition="needs_human")
    b = T.Item("flag", "flag:f90:52:omp.clause.defaultmap.scalar:afar:"
               "headline:ours_ok_suite_fails", {}, disposition="needs_human")
    T.apply_decisions([a, b])
    assert (a.disposition, b.disposition) == ("compiler_bug", "needs_human")


F90 = """program p
  !$omp taskgroup task_reduction(+: s)
  !$omp target map(tofrom: a) in_reduction(+: s)
    !$omp parallel
      !$omp task
      a = 1
      !$omp end task
      !$omp taskwait
    !$omp end parallel
  !$omp end target
  !$omp end taskgroup
  !$omp target teams distribute parallel do
  do i = 1, n
  end do
  !$omp single
  !$omp end single
end program p
"""

C_6 = """int main(void) {
  #pragma omp taskgroup
  {
  #pragma omp target map(tofrom: a)
  {
    #pragma omp parallel for ordered
    for (int i = 0; i < n; i++) {
      #pragma omp ordered
      a[i] = i;
    }
  }
  }
  #pragma omp target teams distribute parallel for
  for (int i = 0; i < n; i++) a[i] = 1;
  #pragma omp single
  x = 1;
  return 0;
}
"""


def test_device_directives_are_those_inside_target_regions():
    assert T.device_directives(F90, "f90") == {"parallel", "task",
                                               "taskwait"}
    assert T.device_directives(C_6, "c") == {"parallel for", "ordered"}


def test_documented_device_limitation_makes_a_bug_cell_partial_support():
    m = mism(device_unsupported={"omp52-x": ["task"]},
             device_unsupported_doc="intro_openmp(7): Limitations")
    bug = [v("compiler_bug", "R10b-own-link-or-hang",
             cid="catalog:omp52-x:cce20:gfx942:unified")]
    d, why = T.mismatch_disposition(m, bug)
    assert d == "partial_support" and "task" in why
    ice = [v("compiler_bug", "R10-compile-ice", "ice",
             cid="catalog:omp52-x:cce20:gfx942:unified")]
    assert T.mismatch_disposition(m, ice)[0] == "compiler_bug"


def test_an_unclaimed_60_form_is_a_version_scope_difference():
    r11a = [v("unsupported", "R11a-newer-form-unclaimed",
              cid="catalog:omp60-x:cce19:gfx942:unified")]
    assert T.mismatch_disposition(mism(), r11a)[0] == "version_scope"


def test_a_documented_clause_limitation_is_partial_support():
    """The allocate program needs requires dynamic_allocators, which the
    vendor documents as a compile-time error: its rejection is the
    documented limitation, not an overclaim of allocate."""
    m = mism(device_unsupported={"omp52-x": ["clause dynamic_allocators"]},
             device_unsupported_doc="intro_openmp(7)")
    un = [v("unsupported", "R05-unsupported",
            cid="catalog:omp52-x:cce19:gfx942:unified")]
    d, why = T.mismatch_disposition(m, un)
    assert d == "partial_support" and "dynamic_allocators" in why


def test_documented_limits_of_a_program():
    src = ("program p\n  !$omp requires dynamic_allocators\n"
           "  !$omp target\n  !$omp end target\nend program p\n")
    hit, page = T.device_limits("cce19", "f90", src, own_atom="omp.clause.allocate")
    assert "clause dynamic_allocators" in hit and page
    hit, _ = T.device_limits("cce19", "f90", src,
                             own_atom="omp.clause.dynamic_allocators")
    assert hit == []


def test_lastprivate_on_distribute_is_a_documented_nvhpc_limitation():
    """NVIDIA's guide (7.4, 2.9.4) says "The
    lastprivate clause is not supported" for distribute, and a combined
    construct takes a clause only as far as its leaves do (2.14): a
    program with lastprivate on a construct with a distribute leaf is the
    documented limitation on NVHPC, the program's own clause included;
    lastprivate on a worksharing loop is not, and other compilers have no
    such claim."""
    c = ("int main(void) {\n  long long l = 0;\n"
         "  #pragma omp target teams distribute parallel for "
         "lastprivate(l) map(tofrom: l)\n"
         "  for (int i = 1; i <= 64; i++) l = i;\n  return 0;\n}\n")
    f = ("program p\n  integer :: i, l\n"
         "  !$omp target teams distribute lastprivate(l)\n"
         "  do i = 1, 4\n    l = i\n  end do\nend program p\n")
    for tc in ("nvhpc", "nvhpc269"):
        hit, page = T.device_limits(tc, "c", c,
                                    own_atom="omp.clause.lastprivate")
        assert hit == ["clause lastprivate on distribute"] and page
        assert T.device_limits(tc, "f90", f)[0] == \
            ["clause lastprivate on distribute"]
        pfor = c.replace("teams distribute parallel for", "parallel for")
        assert T.device_limits(tc, "c", pfor)[0] == []
    assert T.device_limits("cce19", "c", c)[0] == []
    assert T.device_limits("afar", "f90", f)[0] == []


def test_an_override_decision_corrects_a_computed_disposition(tmp_path,
                                                             monkeypatch):
    """An agent may correct a computed mismatch
    disposition (not a cell verdict) with `override: true` and a reason;
    without it a decided item is left alone."""
    p = tmp_path / "d.yaml"
    p.write_text(yaml.safe_dump({"decisions": [
        {"key": "mismatch:a", "override": True,
         "disposition": "compiler_bug", "reason": "r"},
        {"key": "mismatch:b", "disposition": "compiler_bug",
         "reason": "r"}]}))
    monkeypatch.setattr(T, "DECISIONS", p)
    a = T.Item("mismatch", "mismatch:a", {}, disposition="doc_overclaims",
               basis="R05")
    b = T.Item("mismatch", "mismatch:b", {}, disposition="doc_overclaims")
    T.apply_decisions([a, b])
    assert (a.disposition, a.decided_by) == ("compiler_bug", "agent")
    assert "computed: doc_overclaims" in a.basis
    assert b.disposition == "doc_overclaims"


def test_every_family_rejects_keeps_its_class_in_a_mismatch():
    """Under RUL-UNSUPPORTED-EVERYWHERE-AMENDED, an unsupported_everywhere
    cell gives the mismatch that class; the amended rule's compiler_bug
    cells give compiler_bug."""
    r12 = [v("unsupported_everywhere", "R12-every-family-rejects")]
    assert T.mismatch_disposition(mism(), r12)[0] == "unsupported_everywhere"
    r12a = [v("compiler_bug", "R12a-every-family-rejects-claimed")]
    assert T.mismatch_disposition(mism(), r12a)[0] == "compiler_bug"


# ---- The validation's agreement and explanation rules -------------------------------------------

import re

from offload.engine.confirm import validate as V



def test_bug_verdicts_agree_as_a_group():
    assert V.agrees("copy_mode_failure", "compiler_bug")
    assert V.agrees("compiler_bug", "arch_specific")
    assert not V.agrees("compiler_bug", "needs_human")
    assert not V.agrees("needs_unified_memory", "compiler_bug")


def res_of(rule, verdict, **kw):
    return {"rule": rule, "verdict": verdict, "case_id": "x",
            "rationale": "r", "reason": "", "case": {"program": {
                "lang": kw.pop("lang", "f90")}}, **kw}


def test_explanations_come_from_the_evidence():
    r = res_of("R22-expected-weak", "needs_human",
               expected={"status": "provisional", "sources": ["model"]},
               evidence=[{"collector": "elision", "status": "inapplicable",
                          "detail": "present modifier", "value": None}])
    ex = V.explain(r, "compiler_bug")
    assert ex.startswith("explained: stricter") and "present modifier" in ex
    r["evidence"][0]["detail"] = "source not understood: no end program"
    assert V.explain(r, "compiler_bug").startswith(
        "investigate: tool limitation")
    r = res_of("R22-expected-weak", "needs_human",
               expected={"status": "derived", "sources": ["derivation",
                                                          "model"],
                         "value": "check=pass"},
               other_cells=[{"toolchain": "cce20", "mode": "unified",
                             "outcome": "wrong_answer"}],
               withdrawn=[{"toolchain": "afar"}])
    ex = V.explain(r, "compiler_bug")
    assert "cce20/unified" in ex and "withdrawn: afar" in ex
    assert V.explain(res_of("R20-runtime-bug", "compiler_bug"),
                     "compiler_bug") == ""
    assert V.explain(res_of("R13-oracle-wrong", "our_bug"),
                     "compiler_bug").startswith("investigate")


def _c_bug(pid, detail, variant=""):
    r = res_of("R20-runtime-bug", "compiler_bug", lang="c",
               expected={"status": "trusted",
                         "sources": ["derivation", "model"]},
               evidence=[{"collector": "derivation", "status": "value",
                          "value": "check=pass", "variant": variant,
                          "detail": detail}])
    r["case"]["program"].update(ident=pid, version=int(pid[3:5]))
    return r


def test_port_derivation_is_explained_only_for_its_port():
    """The explanation applies when the C program's port
    entry names the Fortran program whose derivation is the label's
    source, at the same version; else it falls through."""
    ok = _c_bug("omp50-c-clause-schedule", "the derivation of "
                "omp50-clause-schedule (port equivalence, RUL-PORT-DERIVATION)")
    ex = V.explain(ok, "needs_human")
    assert ex.startswith("explained: looser (port derivation)")
    assert "omp50-clause-schedule" in ex
    # a derivation naming another Fortran program than the port entry's
    bad = _c_bug("omp50-c-clause-schedule", "the derivation of "
                 "omp52-clause-schedule (port equivalence, RUL-PORT-DERIVATION)")
    assert V.explain(bad, "needs_human").startswith("investigate")
    # a program with no port entry (the evidence claims one)
    none = _c_bug("omp50-c-clause-map-delete", "the derivation of "
                  "omp50-clause-map-delete (port equivalence, "
                  "RUL-PORT-DERIVATION)")
    assert V.explain(none, "needs_human").startswith("investigate")
    # no derivation evidence at all, or a Fortran cell
    bare = _c_bug("omp50-c-clause-schedule", "")
    bare["evidence"] = []
    assert V.explain(bare, "needs_human").startswith("investigate")
    ok["case"]["program"]["lang"] = "f90"
    assert V.explain(ok, "needs_human").startswith("investigate")


def test_registry_derivation_is_explained_with_its_version_citation():
    """The map-delete rows' source is the spec reading
    RUL-DELETE-REFCOUNT, which cites the program's version (5.0); a reading
    without a citation at the program's version falls through."""
    r = _c_bug("omp50-c-clause-map-delete", "spec reading RUL-DELETE-REFCOUNT "
               "(5.2 §5.8.3 p.153: ...)", variant="registry")
    ex = V.explain(r, "needs_human")
    assert ex.startswith("explained: looser (spec reading RUL-DELETE-REFCOUNT")
    assert "5.0 §2.19.7.1" in ex and "Fortran" not in ex
    other = _c_bug("omp50-c-clause-map-delete", "spec reading "
                   "RUL-IS-PRESENT-X1 (5.2 §18.8.3 p.389: ...)",
                   variant="registry")
    assert V.explain(other, "needs_human").startswith("investigate")


def test_requirement_refused_is_a_finer_class():
    assert V.explain(res_of("R08-requirement-refused",
                            "requirement_refused"),
                     "needs_human").startswith("explained: finer class")


def test_committed_report_has_no_unexplained_disagreement():
    text = (ROOT / "data" / "reports" / "confirm-validation.md").read_text()
    m = re.search(r"of which (\d+) unexplained", text)
    assert m and m.group(1) == "0"
    assert "investigate:" not in text
