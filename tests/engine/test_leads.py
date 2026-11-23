"""Leads (offload.engine.leads): every failure of a run checked against the catalog's findings
(offload.engine.confirm.findings.dedupe) and grouped by its signature, so no person reads a
reproducer to tell a known bug from a new one."""
import json
from types import SimpleNamespace

from offload.engine import leads as LD


def failure(seed, tc="cce21", outcome="wrong_answer", reason="", lines=40, kernels=("loop: target",), failing=None):
    return LD.Failure("fuzz:run", str(seed), tc, "f90", "omp", "copy", outcome, reason, "program p\nend program p\n",
                      lines, tuple(kernels), tuple(failing or (tc,)))


def test_the_catalog_is_asked_with_the_program_id_its_entries_name(monkeypatch):
    from offload.engine.confirm import findings as F
    seen = {}
    monkeypatch.setattr(F, "dedupe", lambda *a, **k: seen.update(k) or [])
    LD._dedupe(failure(9))
    assert seen["program_id"] == "run:9" and seen["related"] is True


def test_a_failure_is_known_related_or_new_by_the_catalog(monkeypatch):
    hits = {"1": [{"file": "data/findings/a.f90", "kind": "duplicate", "why": "w"}],
            "2": [{"file": "data/findings/b.f90", "kind": "related", "why": "w"}], "3": []}
    monkeypatch.setattr(LD, "_dedupe", lambda f: hits[f.program_id])
    got = {lead.failure.program_id: (lead.status, lead.findings) for lead in LD.classify([failure(1), failure(2), failure(3)])}
    assert got == {"1": ("known", ("data/findings/a.f90",)), "2": ("related", ("data/findings/b.f90",)), "3": ("new", ())}


def test_failures_of_one_signature_are_one_group_with_the_smallest_program_as_its_representative(monkeypatch):
    monkeypatch.setattr(LD, "_dedupe", lambda f: [])
    fs = [failure(1, lines=80), failure(2, lines=30), failure(3, failing=("cce20", "cce21")),
          failure(4, tc="cce20", lines=10, failing=("cce20",)),
          failure(5, outcome="rejected", reason='ftn-1234: ERROR: line 12: bad thing "x"'),
          failure(6, outcome="rejected", reason='ftn-1234: ERROR: line 99: bad thing "y"')]
    groups = LD.group(LD.classify(fs))
    by = {tuple(sorted(lead.failure.program_id for lead in g.leads)): g for g in groups}
    # a wrong answer: by the family's compilers that fail the program (its kernels are its own)
    assert set(by) == {("1", "2"), ("3",), ("4",), ("5", "6")}
    assert by[("1", "2")].representative.failure.program_id == "2"
    assert by[("5", "6")].status == "new" and by[("1", "2")].family == "cce"


def test_a_group_is_new_only_when_none_of_its_failures_is_known(monkeypatch):
    monkeypatch.setattr(LD, "_dedupe", lambda f: [{"file": "k.f90", "kind": "duplicate", "why": ""}]
                        if f.program_id == "1" else [])
    g = LD.group(LD.classify([failure(1)]))
    assert len(g) == 1 and g[0].status == "known" and g[0].findings == ("k.f90",)
    # one explained failure does not explain the rest: a mixed group, represented by an unexplained one
    g = LD.group(LD.classify([failure(1, lines=5), failure(2, lines=50)]))[0]
    assert g.status == "mixed" and g.representative.failure.program_id == "2"


def test_a_fuzz_run_gives_one_failure_per_failing_toolchain_of_a_legal_program(tmp_path, monkeypatch):
    run = tmp_path / "r1"
    run.mkdir()
    (run / "meta.json").write_text(json.dumps({"sessions": [{"run_id": "r1", "gen_version": "fuzz-6", "base": [],
                                                             "xnack": 1, "opt": "-O2"}]}))
    recs = [{"seed": 7, "gen_version": "fuzz-6", "check": "ok", "validity": "valid", "base": [], "kernels": ["k"],
             "results": {"cce21": {"cls": "wrong_code", "reason": "checksum=1"}, "afar": {"cls": "agree", "reason": ""},
                         "gcc": {"cls": "harness_error", "reason": "x"}}},
            {"seed": 8, "gen_version": "fuzz-6", "check": "prerun", "validity": "valid", "base": [],
             "results": {"cce21": {"cls": "ice", "reason": "boom"}}}]
    (run / "programs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))
    from offload.engine import fuzz
    monkeypatch.setattr(fuzz, "generate", lambda seed, gv, base=(): SimpleNamespace(
        source="program p\n  x = 1\nend program p\n", lang="f90", model="omp"))
    fs = list(LD.fuzz_failures(run))
    assert [(f.program_id, f.toolchain, f.outcome, f.mode, f.lines) for f in fs] == [("7", "cce21", "wrong_answer", "unified", 3)]
    assert fs[0].campaign == "fuzz:r1" and fs[0].kernels == ("k",) and fs[0].failing == ("cce21",)
    assert fs[0].program_ref == "r1:7"          # the form of an index entry's `programs:`


def test_a_compile_time_failure_matches_a_finding_of_any_memory_mode(monkeypatch):
    """The memory mode (HSA_XNACK) is a run-time setting: a compile-time failure is the same bug in
    every mode, so the catalog is asked without one; a run-time failure keeps its mode."""
    from offload.engine.confirm import findings as F
    seen = []
    monkeypatch.setattr(F, "dedupe", lambda *a, **k: seen.append(k["mode"]) or [])
    for outcome in ("ice", "rejected", "wrong_answer", "crash"):
        LD._dedupe(failure(1, outcome=outcome))
    assert seen == ["", "", "copy", "copy"]


def test_a_group_counts_the_failures_no_finding_explains(monkeypatch):
    monkeypatch.setattr(LD, "_dedupe", lambda f: [{"file": "k.f90", "kind": "duplicate", "why": ""}]
                        if f.program_id == "1" else [])
    g = LD.group(LD.classify([failure(1), failure(2), failure(3)]))[0]
    assert g.status == "mixed" and [lead.failure.program_id for lead in g.unexplained] == ["2", "3"]


def test_a_run_failure_is_grouped_by_the_first_error_line_of_its_output():
    out = ("\nThe following have been reloaded with a version change:\n  1) cce/20.0.0 => cce/20.0.2\n\n"
           "fuzz-21.out: libcrayacc/acc_clang_wrapper.c:1009: void TransferList::validate_clang_flags(int64_t): "
           "Assertion `clang_flags == 0' failed.\n")
    a = LD.Failure("fuzz:r", "1", "cce20", "c", "omp", "copy", "crash", "crash: SIGABRT", "", 9, (), ("cce20",), out)
    b = LD.Failure("fuzz:r", "2", "cce20", "c", "omp", "copy", "crash", "crash: SIGABRT", "", 9, (), ("cce20",),
                   "fuzz-3.out: something else entirely: Segmentation fault\n")
    assert "validate_clang_flags" in LD.signature(a) and LD.signature(a) != LD.signature(b)
    noise = LD.Failure("fuzz:r", "3", "afar", "c", "omp", "copy", "run_error", "exit_status: 1", "", 9, (), ("afar",),
                       "t.c:9: warning: loop not vectorized [-Wpass-failed=transform-warning]\n"
                       "Cray Fortran : 0 errors, 1 warnings\nfuzz-3.out: device error: out of memory\n")
    assert "out of memory" in LD.signature(noise)


def test_a_refusal_the_compiler_says_is_a_missing_feature_is_its_own_status(monkeypatch):
    monkeypatch.setattr(LD, "_dedupe", lambda f: [])
    f = failure(1, outcome="rejected", reason="not_implemented: error: not yet implemented: lastprivate clause")
    assert LD.classify([f])[0].status == "unsupported"
    assert LD.group(LD.classify([f]))[0].status == "unsupported"


def test_a_finding_of_another_gpu_makes_a_failure_related(monkeypatch):
    """A finding's arch scope is where it was seen; the same signature on another GPU is related,
    not new."""
    from offload.engine.confirm import findings as F
    fi = SimpleNamespace(file="data/findings/gcc/x.f90", arch=("gfx90a",))
    monkeypatch.setattr(F, "dedupe", lambda *a, **k: [])
    monkeypatch.setattr(F, "index", lambda: [fi])
    monkeypatch.setattr(F, "match", lambda f, *a, **k: ("duplicate", "message") if k.get("arch") == "gfx90a" else None)
    hits = LD._dedupe(failure(1, tc="gcc", outcome="run_error"))
    assert hits == [{"file": "data/findings/gcc/x.f90", "kind": "related", "why": "message (on gfx90a)"}]


def test_the_reduction_queue_holds_one_command_per_unexplained_group(monkeypatch):
    monkeypatch.setattr(LD, "_dedupe", lambda f: [{"file": "k.f90", "kind": "duplicate", "why": ""}]
                        if f.program_id == "1" else [])
    groups = LD.group(LD.classify([failure(1), failure(2, lines=20), failure(3, lines=10),
                                   failure(4, outcome="rejected", reason="not_implemented: x"),
                                   failure(5, tc="cce20", outcome="ice", reason="ice: boom")]))
    q = LD.reduce_queue(groups, run_dir="results/fuzz/run", opt="-O3", xnack=0)
    # the known failure 1 is not reduced; the mixed group's smallest unexplained program (3) is;
    # the compiler's declared missing feature (4) is not a lead
    assert [(e["name"], e["target"]) for e in q] == [("lead-run-5-cce20", "cce20/0"), ("lead-run-3-cce21", "cce21/0")]
    assert q[1]["argv"][:4] == ["--from-row", "results/fuzz/run/programs.jsonl", "--id", "3"]
    assert "--opt=-O3" in q[1]["argv"] and q[1]["argv"][-2:] == ["--out", "results/leads/reduce/lead-run-3-cce21"]


def test_silent_wrong_answers_are_reduced_first_then_the_largest_groups():
    order = sorted([("rejected|x", 900), ("ice|y", 3), ("wrong_answer|cce21", 2), ("crash|z", 40), ("crash|w", 7)],
                   key=lambda s: LD.priority(*s))
    assert order == [("wrong_answer|cce21", 2), ("crash|z", 40), ("crash|w", 7), ("ice|y", 3), ("rejected|x", 900)]


ICE = "ice: INTERNAL COMPILER ERROR: \"Couldn't find an atomic update statement\" (/workspace/crayftn/pdgcs/v_mt_translate_atomic.c, line 1703, version abc)"
SIMD_IF = """program p
  implicit none
  integer :: a(8), i
  logical :: c
  c = .true.
  !$omp target simd if(c) map(from: a)
  do i = 1, 8
    a(i) = i
  end do
  print *, a(1)
end program p
"""


def entry(seed, outcome, reason, text, tcs=("cce19", "cce20")):
    return {"name": f"lead-r-{seed}-{tcs[0]}", "target": f"{tcs[0]}/0", "toolchains": list(tcs), "lang": "f90",
            "mode": "copy", "outcome": outcome, "reason": reason, "output": "", "text": text,
            "program_ref": f"r:{seed}"}


def test_a_finished_reduction_covers_a_waiting_lead_of_its_signature():
    done = entry(1, "ice", ICE, SIMD_IF)
    prov = LD.provisional(done, SIMD_IF, {"toolchain": "cce19", "reason": ICE})
    # another program with the same compiler-source site of the same family: covered
    other = entry(2, "ice", ICE.replace("abc", "def"), SIMD_IF.replace("8", "16"), tcs=("cce20",))
    assert LD.covered(other, [prov]) == prov.file
    # another signature: not covered
    assert LD.covered(entry(3, "ice", "ice: INTERNAL COMPILER ERROR: \"something else\" (/x/y.c, line 9, version a)",
                            SIMD_IF), [prov]) is None


def test_a_reduced_wrong_answer_covers_a_lead_whose_program_has_its_key_constructs():
    prov = LD.provisional(entry(1, "wrong_answer", "", SIMD_IF), SIMD_IF, {"toolchain": "cce19", "reason": ""})
    assert "clause:if" in " ".join(prov.constructs) or prov.constructs
    assert LD.covered(entry(2, "wrong_answer", "", SIMD_IF.replace("a(i) = i", "a(i) = 2 * i")), [prov]) == prov.file
    plain = SIMD_IF.replace("!$omp target simd if(c) map(from: a)", "!$omp target teams distribute parallel do map(from: a)")
    assert LD.covered(entry(3, "wrong_answer", "", plain), [prov]) is None


def test_the_job_skips_a_lead_a_finished_reduction_covers(tmp_path, monkeypatch):
    import importlib.util
    import subprocess
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("leads_tool", Path(__file__).parents[2] / "tools/campaigns/leads.py")
    T = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(T)
    monkeypatch.setattr(T, "ROOT", tmp_path)
    monkeypatch.setattr(T, "QUEUE", tmp_path / "queue.jsonl")
    done = dict(entry(1, "ice", ICE, SIMD_IF), argv=["--budget-minutes", "8", "--out", "red/a"], priority=[2, -5])
    wait = dict(entry(2, "ice", ICE, SIMD_IF.replace("8", "16"), tcs=("cce20",)), argv=["--budget-minutes", "8", "--out", "red/b"],
                priority=[2, -1])
    (tmp_path / "queue.jsonl").write_text(json.dumps(done) + "\n" + json.dumps(wait) + "\n")
    d = tmp_path / "red" / "a"
    d.mkdir(parents=True)
    (d / f"{done['name']}.f90").write_text(SIMD_IF)
    (d / "rows.jsonl").write_text(json.dumps({"toolchain": "cce19", "reason": ICE}) + "\n")
    (d / "report.md").write_text("done\n")
    ran = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **k: ran.append(argv))
    T.reduce(25)
    assert ran == [] and json.loads((tmp_path / "red" / "b" / "covered.json").read_text())["by"].endswith(done["name"])


def test_a_wrong_answer_group_splits_by_the_features_its_failing_programs_share():
    """features: {program id: (generator features, failing?)} of every program the family ran."""
    feats = {}
    for i in range(200):
        fs = {"common"} | ({"x"} if i < 12 else set()) | ({"y"} if 100 <= i < 108 else set())
        fails = (i < 11) or (100 <= i < 107) or i in (150, 151)
        feats[str(i)] = (fs, fails)
    fails = [failure(i) for i in range(200) if feats[str(i)][1]]
    groups = LD.split_by_features(LD.group([LD.Lead(f, "new", ()) for f in fails]), feats)
    by = {g.signature: sorted(int(lead.failure.program_id) for lead in g.leads) for g in groups}
    assert by == {"wrong_answer|cce21|feature:x": list(range(11)),
                  "wrong_answer|cce21|feature:y": list(range(100, 107)),
                  "wrong_answer|cce21": [150, 151]}


def test_a_feature_common_to_every_program_does_not_split_a_group():
    feats = {str(i): ({"common"}, i < 20) for i in range(100)}
    groups = LD.group([LD.Lead(failure(i), "new", ()) for i in range(20)])
    assert [g.signature for g in LD.split_by_features(groups, feats)] == ["wrong_answer|cce21"]


def test_a_fuzz_run_gives_each_programs_features_and_whether_the_family_answered_wrong(tmp_path):
    run = tmp_path / "r"
    run.mkdir()
    recs = [{"seed": 1, "check": "ok", "features": ["a", "b"], "results": {"cce21": {"cls": "wrong_code"}, "afar": {"cls": "agree"}}},
            {"seed": 2, "check": "ok", "features": ["a"], "results": {"cce21": {"cls": "agree"}}},
            {"seed": 3, "check": "prerun", "features": ["a"], "results": {"cce21": {"cls": "wrong_code"}}}]
    (run / "programs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))
    assert LD.fuzz_features(run, "cce") == {"1": ({"a", "b"}, True), "2": ({"a"}, False)}
    assert LD.fuzz_features(run, "afar") == {"1": ({"a", "b"}, False)}


def test_a_wrong_answer_lead_the_elision_cannot_read_gets_a_host_run_of_a_correct_other_family():
    def lead(model, lang, text, agree):
        f = LD.Failure("fuzz:run", "7", "cce19", lang, model, "copy", "wrong_answer", "", text, 9, (), ("cce19",),
                       "", tuple(agree))
        return LD.group([LD.Lead(f, "new", ())])
    acc = LD.reduce_queue(lead("acc", "f90", "program p\nend program p\n", ("cce20", "afar", "gcc")), "results/fuzz/run")
    assert acc[0]["argv"][acc[0]["argv"].index("--reference") + 1] == "host:gcc"
    mod = LD.reduce_queue(lead("omp", "f90", "module m\nend module m\n", ("afar",)), "results/fuzz/run")
    assert mod[0]["argv"][mod[0]["argv"].index("--reference") + 1] == "host:afar"
    plain = LD.reduce_queue(lead("omp", "f90", "program p\nend program p\n", ("gcc",)), "results/fuzz/run")
    assert "--reference" not in plain[0]["argv"]       # a Fortran fuzz program carries its own (the elision)
    none = LD.reduce_queue(lead("acc", "f90", "program p\nend program p\n", ("cce20",)), "results/fuzz/run")
    assert none == []                                   # no correct run of another family: no oracle
