"""Independent legality reviews (offload.engine.legality_review): the verdict rule, the readers
that count, the staleness of a record, what a reader sees of a finding, and the committed
records."""
import json

import pytest

from offload.engine import legality_review as L


def reader(legal="yes", required="yes", decoy="caught", not_found=0, lines_missing=0, contradicted=0,
           instructions=None):
    return {"model": "m", "batch_decoy": decoy, "legal": legal, "result_required": required,
            "quotes": {"ok": 2, "wrong_section": 0, "not_found": not_found},
            "program": {"ok": 2, "not_found": lines_missing, "contradicted": contradicted},
            "instructions": instructions or L.INSTRUCTIONS}


def test_two_counted_readers_that_agree_confirm():
    assert L.verdict({"readers": [reader(), reader()]}) == "confirmed"
    assert L.verdict({"readers": [reader()]}) == "unconfirmed"          # one reading is not enough


def test_a_reader_that_missed_its_decoy_or_cited_missing_text_does_not_count():
    assert L.verdict({"readers": [reader(), reader(decoy="missed")]}) == "unconfirmed"
    assert L.verdict({"readers": [reader(), reader(not_found=1)]}) == "unconfirmed"
    assert L.verdict({"readers": [reader(legal="no", decoy="missed"), reader(), reader()]}) == "confirmed"


def test_a_counted_no_is_contested_unless_outside_evidence_settles_it():
    rs = [reader(), reader(legal="uncertain", required="no")]
    assert L.verdict({"readers": rs}) == "contested"
    assert L.verdict({"readers": rs, "prior_art": [{"strength": "strong"}]}) == "supported"
    assert L.verdict({"readers": rs, "prior_art": [{"strength": "partial"}]}) == "contested"
    assert L.verdict({"readers": rs, "external": [{"kind": "fixed_in", "what": "CCE 22"}]}) == "supported"


def test_uncertain_readers_are_unconfirmed_until_outside_evidence():
    rs = [reader(required="uncertain"), reader()]
    assert L.verdict({"readers": rs}) == "unconfirmed"
    assert L.verdict({"readers": rs, "prior_art": [{"strength": "strong"}]}) == "supported"


def test_a_reader_sees_the_program_without_the_header(tmp_path):
    f = tmp_path / "x.f90"
    f.write_text("! # Finding: the argument\n! spec: \"quoted\"\nprogram p\n  !$omp target\n"
                 "  x = 1\n  !$omp end target\nend program p\n! site:\n! title: t\n! end site\n")
    assert L.program_text(f) == "program p\n  !$omp target\n  x = 1\n  !$omp end target\nend program p\n"
    c = tmp_path / "y.c"
    c.write_text("// header\nint main(void) {\n#pragma omp target\n  {}\n  return 0; // tail\n}\n")
    assert L.program_text(c).startswith("int main(void)") and "// tail" in L.program_text(c)


def test_a_changed_program_makes_its_record_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "FINDINGS", tmp_path)
    monkeypatch.setattr(L, "REVIEWS", tmp_path / "reviews")
    (tmp_path / "reviews").mkdir()
    f = tmp_path / "x.f90"
    f.write_text("program p\nend program p\n")
    rec = {"finding": "x.f90", "program_sha": L.program_sha(f), "readers": [reader(), reader()],
           "verdict": "confirmed", "why": "w"}
    L.record_path("x").write_text(json.dumps(rec))
    assert L.status("x") == ("confirmed", "w")
    f.write_text("! a header edit keeps the review\nprogram p\nend program p\n")
    assert L.status("x")[0] == "confirmed"
    f.write_text("program p\n  print *, 1\nend program p\n")
    assert L.status("x") == ("unconfirmed", "the program changed since its review")
    assert L.status("nothing") == ("unconfirmed", "no independent review yet")


@pytest.mark.needs_spec
def test_quotes_are_checked_against_the_specification_text():
    q = ("the effect of the lastprivate clause is as if the same list item appears in a map clause "
         "with a map-type of tofrom")
    assert L.check_quotes([{"spec": "openmp-5.2.txt", "section": "17.2", "quote": q}]) == \
        {"ok": 1, "wrong_section": 0, "not_found": 0}
    assert L.check_quotes([{"spec": "openmp-5.2.txt", "section": "5.8.1", "quote": q}])["wrong_section"] == 1
    assert L.check_quotes([{"spec": "openmp-5.2.txt", "section": "17.2",
                            "quote": "a sentence the specification never says"}])["not_found"] == 1
    # a table row as the reader's plain text lays it out (the PDF rows order its columns differently)
    row = "iand               omp_priv = All bits on            omp_out = iand(omp_in, omp_out)"
    assert L.check_quotes([{"file": "openmp-5.2.txt", "section": "5.5.3", "quote": row}])["not_found"] == 0


def test_every_committed_record_follows_the_rule_and_names_a_finding():
    bad = []
    for p in sorted(L.REVIEWS.glob("*.json")):
        rec = json.loads(p.read_text())
        fid = p.stem.replace("--", "/")
        if L.finding_file(fid) is None:
            bad.append(f"{p.name}: no finding {fid}")
            continue
        bad += L.problems(fid, rec)
    assert not bad, bad


def test_two_adjudicators_that_weigh_a_dispute_settle_it():
    rs = [reader(), reader(legal="yes", required="no")]
    assert L.verdict({"readers": rs, "adjudicators": [reader(), reader()]}) == "confirmed"
    assert L.verdict({"readers": rs, "adjudicators": [reader(), reader(decoy="missed")]}) == "contested"
    assert L.verdict({"readers": rs, "adjudicators": [reader(), reader(required="no")]}) == "contested"
    unsure = [reader(), reader(required="uncertain")]
    assert L.verdict({"readers": unsure, "adjudicators": [reader(), reader()]}) == "confirmed"
    assert L.verdict({"readers": unsure, "adjudicators": [reader(), reader(legal="uncertain")]}) == "unconfirmed"


def test_a_case_says_whether_the_failing_runs_kept_host_and_device_storage_apart():
    assert "separate" in L.memory_line(["mi300a-u", "mi300x"])
    assert "may share storage" in L.memory_line(["mi300a-u", "a100-m"])


def test_ingest_records_readers_then_adjudicators(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("review", L.ROOT / "tools" / "review" / "review.py")
    R = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(R)
    monkeypatch.setattr(L, "FINDINGS", tmp_path / "f")
    monkeypatch.setattr(L, "REVIEWS", tmp_path / "f" / "reviews")
    (tmp_path / "f").mkdir()
    (tmp_path / "f" / "x.f90").write_text("program p\nend program p\n")
    sha = L.program_sha(tmp_path / "f" / "x.f90")

    def batch(run, name, key, answers):
        d = tmp_path / run / name
        d.mkdir(parents=True)
        (d / "key.json").write_text(json.dumps(key))
        (d / "out.jsonl").write_text("".join(json.dumps(a) + "\n" for a in answers))

    case = lambda n, kind, answer=None: {"case": n, "kind": kind, "id": "x" if kind == "finding" else "d.f90",  # noqa: E731
                                         "sha": sha if kind == "finding" else None, "answer": answer}
    ans = lambda n, legal, req: {"case": n, "legal": legal, "result_required": req, "reasoning": "r. s.",  # noqa: E731
                                 "program_lines": ["program p"]}
    for b, req in (("batch-01", "yes"), ("batch-02", "no")):
        batch("run", b, {"round": "read", "instructions": L.INSTRUCTIONS,
                         "cases": [case(1, "finding"), case(2, "decoy", "illegal")]}, [ans(1, "yes", req), ans(2, "no", "no")])
    R.ingest(tmp_path / "run")
    assert L.load("x")["verdict"] == "contested" and len(L.load("x")["readers"]) == 2
    for b in ("batch-01", "batch-02"):
        batch("adj", b, {"round": "adjudicate", "instructions": L.INSTRUCTIONS,
                         "cases": [case(1, "finding"), case(2, "decoy", "result_not_required")]},
              [ans(1, "yes", "yes"), ans(2, "yes", "no")])
    R.ingest(tmp_path / "adj")
    rec = L.load("x")
    assert rec["verdict"] == "confirmed" and len(rec["adjudicators"]) == 2 and len(rec["readers"]) == 2
    assert rec["why"].startswith("One independent reading disputed it")
    assert "Reading" not in R._clip("Reading B fails. The rule holds. Reading A is right; it cites 5.8.1.")
    assert not L.problems("x", rec)


def test_a_passage_given_as_bare_text_names_no_specification_and_is_not_found():
    assert L.check_quotes(["a quoted sentence with no specification named"]) == \
        {"ok": 0, "wrong_section": 0, "not_found": 1}


def test_an_outside_dispute_is_read_against_a_counted_reading(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("review", L.ROOT / "tools" / "review" / "review.py")
    R = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(R)
    rec = {"readers": [dict(reader(decoy="missed"), reasoning="uncounted."),
                       dict(reader(), reasoning="It is legal.")]}
    a, b = R.dispute_readings(rec, "It breaks 5.8.3.")
    assert {a, b} == {"legal: yes, result_required: yes. It is legal.", "It breaks 5.8.3."}
    a, b = R.dispute_readings({"readers": [dict(reader(), reasoning="x."), dict(reader(), reasoning="y.")]}, None)
    assert {a, b} == {"legal: yes, result_required: yes. x.", "legal: yes, result_required: yes. y."}



def test_a_reader_counts_only_if_its_program_quotes_hold():
    """A quoted program line must be in the program; a text the reader says the program lacks
    must not be (the reading that called `x` undeclared, with `integer, intent(in) :: x` there)."""
    prog = "module integer function gs1(x)\n  integer, intent(in) :: x\nend function gs1\n"
    assert L.check_program({"program_lines": ["module integer function gs1(x)"], "absent": [":: y"]}, prog) == \
        {"ok": 1, "not_found": 0, "contradicted": 0}
    assert L.check_program({"program_lines": ["INTEGER,  INTENT(IN) :: X"]}, prog)["ok"] == 1   # case, spacing
    assert L.check_program({"program_lines": ["integer :: x = 3"]}, prog)["not_found"] == 1
    assert L.check_program({"program_lines": ["gs1"], "absent": [":: x"]}, prog)["contradicted"] == 1
    assert L.check_program({"program_lines": ["gs1"], "absent": ["x"]}, prog)["contradicted"] == 0   # too short to test
    assert L.check_program({}, prog) == {"ok": 0, "not_found": 0, "contradicted": 0}
    # an absent text matches as a whole word: a device clause is not the device( of omp_is_initial_device()
    calls = "if (omp_is_initial_device()) x = 1;\n#pragma omp target map(tofrom: x)\n"
    assert L.check_program({"program_lines": ["omp_is_initial_device"], "absent": ["device("]}, calls)["contradicted"] == 0
    assert L.check_program({"program_lines": ["omp_is_initial_device"], "absent": ["map(tofrom: x)"]}, calls)["contradicted"] == 1
    assert L.verdict({"readers": [reader(), reader(legal="no", contradicted=1), reader()]}) == "confirmed"
    assert L.verdict({"readers": [reader(), reader(lines_missing=1)]}) == "unconfirmed"


def test_a_reader_that_quotes_no_program_line_does_not_count():
    r = reader()
    r["program"] = {"ok": 0, "not_found": 0, "contradicted": 0}
    assert not L.counted(r)


def test_the_verdict_counts_only_readings_under_the_current_instructions():
    old = [reader(legal="no", instructions="v1"), reader(instructions="v1")]
    assert L.verdict({"readers": old}) == "unconfirmed"
    assert L.verdict({"readers": old + [reader(), reader()]}) == "confirmed"


def test_a_dispute_adjudicated_only_under_older_instructions_is_still_open(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("review", L.ROOT / "tools" / "review" / "review.py")
    R = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(R)
    monkeypatch.setattr(L, "REVIEWS", tmp_path)
    rs = [reader(), reader(legal="no")]
    (tmp_path / "a.json").write_text(json.dumps({"verdict": "contested", "readers": rs,
                                                 "adjudicators": [reader(instructions="v1")]}))
    (tmp_path / "b.json").write_text(json.dumps({"verdict": "contested", "readers": rs,
                                                 "adjudicators": [reader(), reader()]}))
    assert R.disputed() == ["a"]


def verification(refuted=True, decoys="caught", spec_missing=0, program_missing=0):
    return {"run": "v", "batch_decoys": decoys, "refuted": refuted,
            "quotes": {"ok": 1, "wrong_section": 0, "not_found": spec_missing},
            "program": {"ok": 1, "not_found": program_missing, "contradicted": 0}}


def test_a_reading_two_counted_verifiers_refute_does_not_count():
    """A verifier lists the premises a reading rests on and checks each against the specification
    and the program. A reading stops counting when two verifiers that passed both their decoys
    refute one of its premises with quotes that check out; one refutation is not enough."""
    r = reader(legal="no")
    assert L.counted(r)
    r["verifications"] = [verification()]
    assert L.counted(r)                                         # one refutation: the reading stands
    r["verifications"] = [verification(), verification()]
    assert not L.counted(r) and L.refuted(r)
    for bad in (verification(decoys="missed"), verification(spec_missing=1), verification(program_missing=1),
                verification(refuted=False)):
        r["verifications"] = [verification(), bad]
        assert L.counted(r), bad                                # an uncounted or upholding verifier: no refutation
    rs = [reader(), reader(legal="no"), reader()]
    rs[1]["verifications"] = [verification(), verification()]
    assert L.verdict({"readers": rs}) == "confirmed"           # the refuted dissent no longer contests it


def test_a_verifier_counts_only_if_it_gets_both_decoys_right():
    assert L.verification_counted(verification())
    assert not L.verification_counted(verification(decoys="missed"))
    assert not L.verification_counted(verification(decoys="half"))


def test_verification_attaches_to_the_reading_and_two_refutations_drop_it(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("review", L.ROOT / "tools" / "review" / "review.py")
    R = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(R)
    monkeypatch.setattr(L, "FINDINGS", tmp_path / "f")
    monkeypatch.setattr(L, "REVIEWS", tmp_path / "f" / "reviews")
    (tmp_path / "f" / "reviews").mkdir(parents=True)
    (tmp_path / "f" / "x.f90").write_text("program p\n  character :: c\nend program p\n")
    sha = L.program_sha(tmp_path / "f" / "x.f90")
    no = dict(reader(legal="no"), run="r/batch-01", reasoning="c is a scalar.")
    rec = {"finding": "x.f90", "program_sha": sha, "readers": [dict(reader(), run="r/batch-02"), no,
                                                              dict(reader(), run="r/batch-03")]}
    rec["verdict"] = L.verdict(rec)
    L.record_path("x").write_text(json.dumps(rec))
    assert rec["verdict"] == "contested"
    assert [(t["id"], t["run"]) for t in R.verify_targets()] == [("x", "r/batch-01"), ("x", "r/batch-02"),
                                                                ("x", "r/batch-03")]
    cases = [{"case": 1, "kind": "reading", "id": "x", "role": "readers", "run": "r/batch-01", "sha": sha},
             {"case": 2, "kind": "decoy-false", "id": "d.f90"}, {"case": 3, "kind": "decoy-true", "id": "d.f90"}]
    refute = {"case": 1, "refuted": True, "claims": [{"claim": "a character variable is a scalar variable",
              "verdict": "false", "program_lines": ["character :: c"], "passages": []}]}
    for b in ("batch-01", "batch-02"):
        d = tmp_path / "ver" / b
        d.mkdir(parents=True)
        (d / "key.json").write_text(json.dumps({"round": "verify", "cases": cases}))
        (d / "out.jsonl").write_text("".join(json.dumps(a) + "\n" for a in
                                             (refute, {"case": 2, "refuted": True}, {"case": 3, "refuted": False})))
        R.ingest(d.parent) if b == "batch-02" else None
    rec = L.load("x")
    dropped = rec["readers"][1]
    assert len(dropped["verifications"]) == 2 and L.refuted(dropped)
    assert rec["verdict"] == "confirmed" and not L.problems("x", rec)
