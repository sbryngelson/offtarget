"""Tests of the fresh bug benchmarks (the tool and the sealed sets), the findings promoted from their drafts, and the omp_vv copy-semantics classification and comparison."""


# ---- The sealed fresh bug benchmark (data/bench/fresh/, tools/campaigns/fresh_bench.py) ------------------

import csv
import json
import re
import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]

import fresh_bench as FB  # noqa: E402


# --- the tool on fixtures -------------------------------------------------------

def _case(tmp, name, text):
    p = tmp / name
    p.write_text(text)
    return p


def test_digest_is_order_independent_and_content_sensitive(tmp_path):
    a = _case(tmp_path, "fresh-001.f90", "program a\nend\n")
    b = _case(tmp_path, "fresh-002.c", "int main(){return 0;}\n")
    d1 = FB.digest([a, b])
    assert d1 == FB.digest([b, a])
    assert re.fullmatch(r"[0-9a-f]{64}", d1)
    b.write_text("int main(){return 1;}\n")
    assert FB.digest([a, b]) != d1
    # a rename changes the digest too (the name is hashed with the text)
    b.write_text("int main(){return 0;}\n")
    c = tmp_path / "fresh-003.c"
    b.rename(c)
    assert FB.digest([a, c]) != d1


def test_header_reads_fresh_case_key(tmp_path):
    p = _case(tmp_path, "fresh-007.f90",
              "! fresh case: fresh-007\n! source: https://example.org/1\n"
              "! edits:\n!   1) added a main program\n"
              "! expected: wild-check: pass\n! wild-opt: -O0\n"
              "program p\nend program\n")
    h = FB.header(p)
    assert h["fresh case"] == "fresh-007"
    assert h["wild case"] == "fresh-007"     # wild_bench's ref_of reads it
    assert h["source"] == "https://example.org/1"
    assert h["edits"] == ["1) added a main program"]
    assert h["expected"] == "wild-check: pass" and h["wild-opt"] == "-O0"


def test_outcomes_table(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "afar.copy.jsonl").write_text(
        json.dumps({"id": "fresh-002", "toolchain": "afar", "mode": "copy",
                    "outcome": "ice"}) + "\n" +
        json.dumps({"id": "fresh-001", "toolchain": "afar", "mode": "copy",
                    "outcome": "correct_on_device"}) + "\n")
    (runs / "nvhpc.managed.jsonl").write_text(
        json.dumps({"id": "fresh-001", "toolchain": "nvhpc",
                    "mode": "managed", "outcome": "not_applicable"}) + "\n")
    rows = FB.outcome_rows(runs)
    assert rows == [("fresh-001", "afar", "copy", "correct_on_device"),
                    ("fresh-001", "nvhpc", "managed", "not_applicable"),
                    ("fresh-002", "afar", "copy", "ice")]
    out = tmp_path / "outcomes.csv"
    FB.write_outcomes(rows, out)
    got = list(csv.reader(out.open()))
    assert got[0] == ["case", "toolchain", "mode", "outcome"]
    assert len(got) == 4
    # a rerun line of the same cell replaces the earlier one
    with (runs / "afar.copy.jsonl").open("a") as fh:
        fh.write(json.dumps({"id": "fresh-002", "toolchain": "afar",
                             "mode": "copy", "outcome": "rejected"}) + "\n")
    assert ("fresh-002", "afar", "copy", "rejected") in FB.outcome_rows(runs)
    assert len(FB.outcome_rows(runs)) == 3


def test_hand_classified_compile_failures(monkeypatch):
    monkeypatch.setitem(FB.HAND_CLASSIFIED, ("fresh-900", "nvhpc"),
                        ("ice", "hand-read"))
    rec = {"id": "fresh-900", "toolchain": "nvhpc", "mode": "copy",
           "outcome": "harness_error",
           "reason": "unclassified_compile_failure: rc=2"}
    assert FB.reclassify(rec) == ("ice", "hand-read")
    other = dict(rec, toolchain="nvhpc269")
    assert FB.reclassify(other)[0] == "harness_error"
    ok = dict(rec, outcome="rejected", reason="diagnostic: x")
    assert FB.reclassify(ok) == ("rejected", "diagnostic: x")


def test_unsupported_combination_is_not_applicable(tmp_path):
    p = _case(tmp_path, "fresh-005.c", "// fresh case: fresh-005\n"
              "#pragma acc parallel\nint main(){return 0;}\n")

    def boom(path, tc, mode):
        raise ValueError("CCE supports OpenACC for Fortran only")
    rec = FB.guarded_run_cell(boom)(p, "cce19", "copy")
    assert rec["outcome"] == "not_applicable" and rec["id"] == "fresh-005"

    def other(path, tc, mode):
        raise ValueError("something else")
    with pytest.raises(ValueError):
        FB.guarded_run_cell(other)(p, "cce19", "copy")
    remote = {"id": "fresh-005", "toolchain": "cce19_g90", "mode": "copy",
              "outcome": "harness_error", "reason": "remote: rc=1: ... "
              "ValueError: CCE supports OpenACC for Fortran only"}
    assert FB.reclassify(remote)[0] == "not_applicable"


def test_confirm_candidates():
    rows = [("fresh-001", "afar", "copy", "ice"),
            ("fresh-001", "afar", "unified", "ice"),      # same family
            ("fresh-001", "cce19", "copy", "crash"),
            ("fresh-002", "cce20", "copy", "rejected"),   # not implemented
            ("fresh-003", "nvhpc", "copy", "wrong_answer"),  # not legal
            ("fresh-004", "nvhpc269", "managed", "correct_on_device")]
    leg = {"fresh-001": "legal", "fresh-002": "legal", "fresh-003": "unknown",
           "fresh-004": "legal"}
    reasons = {("fresh-002", "cce20", "copy"): "not_implemented: x"}
    c = FB.confirm_candidates(rows, leg, reasons)
    assert [(x["id"], x["toolchain"], x["mode"]) for x in c] == [
        ("fresh-001", "afar", "copy"), ("fresh-001", "cce19", "copy")]
    assert {x["family"] for x in c} == {"afar", "cce"}


def test_seal_text_and_check(tmp_path):
    a = _case(tmp_path, "fresh-001.f90", "program a\nend\n")
    meta = _case(tmp_path, "cases.yaml", "cases: []\n")
    text = FB.seal_text("abc1234", [a], meta)
    seal = tmp_path / "SEAL"
    seal.write_text(text)
    s = FB.read_seal(seal)
    assert s["commit"] == "abc1234" and s["cases"] == 1
    assert s["sha256"] == FB.digest([a])
    assert FB.check_seal(seal, [a], meta) == []
    a.write_text("program b\nend\n")
    assert FB.check_seal(seal, [a], meta)        # a broken seal is reported
    a.write_text("program a\nend\n")
    oc = _case(tmp_path, "outcomes.csv", "case,toolchain,mode,outcome\n")
    seal.write_text(FB.seal_text("abc1234", [a], meta, oc))
    assert FB.read_seal(seal)["outcomes_sha256"]
    assert FB.check_seal(seal, [a], meta, oc) == []
    oc.write_text("case,toolchain,mode,outcome\nx,y,z,ice\n")
    assert FB.check_seal(seal, [a], meta, oc)


def test_version_60_from_metadata(tmp_path):
    meta = tmp_path / "cases.yaml"
    meta.write_text("cases:\n- {id: fresh-001}\n- {id: fresh-002, omp_version: 60}\n"
                    "excluded: []\n")
    assert FB.version_60(meta) == {"fresh-002"}
    assert FB.version_60(tmp_path / "missing.yaml") == set()


def test_remote_roots_replaces_only_the_root():
    from offload.engine.confirm import machines as M
    before = M.load()["wingtip"]
    with FB.remote_roots({"wingtip": "/elsewhere/clone"}):
        m = M.load()["wingtip"]
        assert m.access["root"] == "/elsewhere/clone"
        assert m.access["ssh"] == before.access["ssh"]
        assert M.load()["tuolumne"] == M.load()["tuolumne"]
    assert M.load()["wingtip"].access["root"] == before.access["root"]
    with FB.remote_roots({}, ("tioga",)):
        assert M.load()["tioga"].access == "local"
    assert isinstance(M.load()["tioga"].access, dict)


def test_run_uses_fresh_paths():
    with FB.fresh():
        import wild_bench as WB
        assert WB.BENCH == FB.FRESH and WB.OUT == FB.OUT
        assert WB.header is FB.header
    import wild_bench as WB
    assert WB.BENCH == ROOT / "data" / "bench" / "wild"   # restored


# --- the set itself -----------------------------------------------------------------

HAVE_SET = (FB.FRESH / "cases.yaml").is_file()
needs_set = pytest.mark.skipif(not HAVE_SET, reason="data/bench/fresh not built")


def _meta():
    return yaml.safe_load((FB.FRESH / "cases.yaml").read_text())


@needs_set
def test_cases_match_metadata():
    meta = _meta()
    ids = [c["id"] for c in meta["cases"]]
    files = {p.stem for p in FB.case_files()}
    assert len(ids) == len(set(ids)) and set(ids) == files
    assert 100 <= len(ids) <= 150
    bad = []
    for c in meta["cases"]:
        for k in ("url", "project", "date", "compiler", "family", "failure",
                  "reported", "status", "lang", "model", "license", "file",
                  "source_kind"):
            if not c.get(k):
                bad.append((c["id"], k))
        if c["lang"] not in ("f90", "c") or c["model"] not in ("omp", "acc"):
            bad.append((c["id"], "lang/model"))
        if (FB.FRESH / c["file"]).suffix != (".c" if c["lang"] == "c"
                                             else ".f90"):
            bad.append((c["id"], "suffix"))
        if not re.fullmatch(r"fresh-\d{3}", c["id"]):
            bad.append((c["id"], "opaque id"))
    assert not bad, bad
    assert all(e.get("reason") and e.get("class") for e in meta["excluded"])


@needs_set
def test_no_overlap_with_bench_wild():
    """Dedupe by URL: no source or related URL of a fresh case or exclusion
    is a URL of data/bench/wild/cases.yaml (kept or excluded)."""
    def urls(obj):
        out = set()
        if isinstance(obj, dict):
            for v in obj.values():
                out |= urls(v)
        elif isinstance(obj, list):
            for v in obj:
                out |= urls(v)
        elif isinstance(obj, str):
            out |= {u.rstrip(".,;)") for u in
                    re.findall(r"https?://[^\s'\"]+", obj)}
        return out
    wild = urls(yaml.safe_load((ROOT / "data" / "bench" / "wild" / "cases.yaml")
                               .read_text()))
    fresh = set()
    for c in _meta()["cases"]:
        fresh |= urls({k: v for k, v in c.items()
                       if k in ("url", "also")})
    clash = sorted(fresh & wild)
    assert not clash, f"{len(clash)} URL(s) also in data/bench/wild"


@needs_set
def test_case_headers():
    bad = []
    for p in FB.case_files():
        h = FB.header(p)
        if h.get("fresh case") != p.stem:
            bad.append((p.stem, "id"))
        if not re.match(r"https?://", h.get("source", "")):
            bad.append((p.stem, "source"))
        if not h["edits"]:
            bad.append((p.stem, "edits"))
        if not re.search(r"(?im)^\s*(!\$(omp|acc)|#\s*pragma\s+(omp|acc))\s+"
                         r"(\w+\s+)*?(target|declare|parallel|kernels|serial|"
                         r"data|enter|update|routine|teams|metadirective)",
                         p.read_text()):
            bad.append((p.stem, "no offload directive"))
    assert not bad, bad


@needs_set
@pytest.mark.gfortran
def test_cases_parse():
    if shutil.which("gfortran") is None or shutil.which("gcc") is None:
        pytest.skip("gfortran/gcc not found")
    with FB.fresh():
        bad = [p.stem for p in FB.case_files() if not FB.parse_ok(p)]
    assert not bad, bad


@needs_set
def test_seal_matches_the_set():
    seal = FB.FRESH / "SEAL"
    if not seal.is_file():
        pytest.skip("not sealed yet")
    assert FB.check_seal(seal, FB.case_files(),
                         FB.FRESH / "cases.yaml") == []


@needs_set
def test_outcomes_csv_shape():
    p = FB.FRESH / "outcomes.csv"
    if not p.is_file():
        pytest.skip("no outcome table yet")
    rows = list(csv.reader(p.open()))
    assert rows[0] == ["case", "toolchain", "mode", "outcome"]
    ids = {c["id"] for c in _meta()["cases"]}
    assert {r[0] for r in rows[1:]} <= ids
    assert not any("lint" in h for h in rows[0])


# --- --bench / --out, and the second sealed set (data/bench/fresh2) ----------

FRESH2 = ROOT / "data" / "bench" / "fresh2"


def _fixture_bench(tmp, name="fresh2"):
    b = tmp / name
    b.mkdir()
    _case(b, f"{name}-001.f90", f"! fresh case: {name}-001\n"
          "! source: https://example.org/1\n! edits: none\nprogram a\nend\n")
    _case(b, f"{name}-002.c", f"// fresh case: {name}-002\n"
          "// source: https://example.org/2\n// edits: none\n"
          "int main(){return 0;}\n")
    _case(b, "cases.yaml", "cases: []\nexcluded: []\n")
    return b


def test_case_files_follow_the_bench_name(tmp_path):
    b = _fixture_bench(tmp_path)
    _case(b, "fresh-009.c", "int main(){return 0;}\n")   # not this bench's
    assert [p.name for p in FB.case_files(b)] == ["fresh2-001.f90",
                                                  "fresh2-002.c"]
    assert all(p.name.startswith("fresh-") for p in FB.case_files())


def test_seal_and_check_seal_with_bench_arg(tmp_path, capsys):
    b = _fixture_bench(tmp_path)
    assert FB.main(["seal", "--commit", "abc1234", "--bench", str(b)]) == 0
    text = (b / "SEAL").read_text()
    assert "bench/fresh2" in text and "fresh2-*.f90" in text
    assert FB.read_seal(b / "SEAL")["cases"] == 2
    assert FB.main(["check-seal", "--bench", str(b)]) == 0
    (b / "fresh2-002.c").write_text("int main(){return 1;}\n")
    assert FB.main(["check-seal", "--bench", str(b)]) == 1
    assert FB.FRESH == ROOT / "data" / "bench" / "fresh"      # restored after main
    assert FB.OUT == ROOT / "results" / "fresh"


def test_outcomes_with_bench_and_out(tmp_path):
    b = _fixture_bench(tmp_path)
    out = tmp_path / "res"
    (out / "runs").mkdir(parents=True)
    (out / "runs" / "afar.copy.jsonl").write_text(json.dumps(
        {"id": "fresh2-001", "toolchain": "afar", "mode": "copy",
         "outcome": "ice"}) + "\n")
    assert FB.main(["outcomes", "--bench", str(b), "--out", str(out)]) == 0
    rows = list(csv.reader((b / "outcomes.csv").open()))
    assert rows == [["case", "toolchain", "mode", "outcome"],
                    ["fresh2-001", "afar", "copy", "ice"]]
    # --out defaults to results/<bench name>
    with FB.use_bench(b):
        assert FB.OUT == ROOT / "results" / "fresh2"
        with FB.fresh() as WB:
            assert WB.BENCH == b and WB.OUT == ROOT / "results" / "fresh2"
            assert [p.name for p in WB.case_files()] == ["fresh2-001.f90",
                                                         "fresh2-002.c"]
    assert FB.FRESH == ROOT / "data" / "bench" / "fresh"


def test_fresh_seal_is_unchanged():
    """No change to how the tool builds data/bench/fresh: its seal text, written
    again from the sealed commit, is byte-identical to the committed SEAL."""
    seal = FB.FRESH / "SEAL"
    if not seal.is_file():
        pytest.skip("data/bench/fresh not sealed")
    commit = FB.read_seal(seal)["commit"]
    assert FB.seal_text(commit, FB.case_files(),
                        FB.FRESH / "cases.yaml") == seal.read_text()


def test_body_digest_ignores_header_and_spacing(tmp_path):
    a = _case(tmp_path, "fresh-001.f90", "! fresh case: fresh-001\n"
              "! source: https://a\nprogram a\n  x = 1\nend\n")
    b = _case(tmp_path, "llvm-1.f90", "! wild case: llvm-1\n"
              "! source: https://b\n! edits: none\nprogram a\n x  =  1\n\nend\n")
    assert FB.body_digest(a) == FB.body_digest(b)
    b.write_text("! wild case: llvm-1\nprogram a\n x = 2\nend\n")
    assert FB.body_digest(a) != FB.body_digest(b)


def _urls(obj):
    out = set()
    if isinstance(obj, dict):
        for v in obj.values():
            out |= _urls(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= _urls(v)
    elif isinstance(obj, str):
        out |= {u.rstrip(".,;)") for u in
                re.findall(r"https?://[^\s'\"]+", obj)}
    return out


@pytest.mark.needs_bench("fresh2/cases.yaml", "fresh2/SEAL")
def test_fresh2_excludes_known_urls():
    """data/bench/fresh2 holds no URL (a case's url or also) and no reproducer
    (FB.body_digest) of data/bench/wild or data/bench/fresh, kept or excluded. Reports
    only counts: the set is sealed."""
    assert (FRESH2 / "cases.yaml").is_file(), "data/bench/fresh2 not built"
    known = set()
    for b in ("wild", "fresh"):
        known |= _urls(yaml.safe_load((ROOT / "data" / "bench" / b / "cases.yaml")
                                      .read_text()))
    meta = yaml.safe_load((FRESH2 / "cases.yaml").read_text())
    mine = set()
    for c in meta["cases"]:
        mine |= _urls({k: v for k, v in c.items() if k in ("url", "also")})
    for p in FB.case_files(FRESH2):
        h = FB.header(p)
        mine |= _urls([h.get("source", ""), *h.get("also", [])])
    assert not (mine & known), f"{len(mine & known)} known URL(s)"
    old = {FB.body_digest(p) for p in
           [*(ROOT / "data" / "bench" / "wild").glob("*.f90"),
            *(ROOT / "data" / "bench" / "wild").glob("*.c"),
            *FB.case_files(FB.FRESH)]}
    new = [FB.body_digest(p) for p in FB.case_files(FRESH2)]
    assert new and not (set(new) & old), \
        f"{len(set(new) & old)} known reproducer(s)"
    assert len(set(new)) == len(new), "a reproducer appears twice"


@pytest.mark.needs_bench("fresh2/cases.yaml", "fresh2/SEAL")
def test_check_seal_bench_arg(tmp_path):
    """check-seal --bench data/bench/fresh2 passes on the set and fails on a
    tampered copy."""
    assert (FRESH2 / "SEAL").is_file(), "data/bench/fresh2 not sealed"
    assert FB.main(["check-seal", "--bench", str(FRESH2)]) == 0
    copy = tmp_path / "fresh2"
    shutil.copytree(FRESH2, copy)
    assert FB.main(["check-seal", "--bench", str(copy)]) == 0
    victim = FB.case_files(copy)[0]
    victim.write_text(victim.read_text() + "\n")
    assert FB.main(["check-seal", "--bench", str(copy)]) == 1
    # the seal covers outcomes.csv and cases.yaml too
    s = FB.read_seal(FRESH2 / "SEAL")
    assert s.get("outcomes_sha256") and s.get("cases_yaml_sha256")
    for name in ("outcomes.csv", "cases.yaml"):
        c2 = tmp_path / ("t-" + name.split(".")[0]) / "fresh2"
        shutil.copytree(FRESH2, c2)
        assert FB.main(["check-seal", "--bench", str(c2)]) == 0
        f = c2 / name
        f.write_text(f.read_text() + "\n")
        assert FB.main(["check-seal", "--bench", str(c2)]) == 1
    # a copy in a directory of another name still finds its case files
    other = tmp_path / "elsewhere"
    shutil.copytree(FRESH2, other)
    assert len(FB.case_files(other)) == len(FB.case_files(FRESH2))
    assert FB.main(["check-seal", "--bench", str(other)]) == 0


REMOVED_FR1 = ("fresh2-039", "fresh2-067", "fresh2-079")  


@pytest.mark.needs_bench("fresh2/cases.yaml", "fresh2/SEAL")
def test_fresh2_metadata():
    """The second set's metadata, as test_cases_match_metadata, plus its
    phase field (and where it comes from), its provenance and resampling
    clusters, and the ids removed (kept unused, each listed
    under excluded with its reason). 119 cases: the ruling for
    (three removed; every per-phase, family, model and language
    quota still holds)."""
    assert (FRESH2 / "cases.yaml").is_file(), "data/bench/fresh2 not built"
    meta = yaml.safe_load((FRESH2 / "cases.yaml").read_text())
    ids = [c["id"] for c in meta["cases"]]
    assert len(ids) == len(set(ids))
    assert set(ids) == {p.stem for p in FB.case_files(FRESH2)}
    assert 119 <= len(ids) <= 160
    assert not set(REMOVED_FR1) & set(ids)
    gone = {e.get("former_id"): e for e in meta["excluded"]}
    assert all(gone.get(i, {}).get("reason") for i in REMOVED_FR1)
    bad = []
    for c in meta["cases"]:
        for k in ("url", "project", "date", "compiler", "family", "failure",
                  "reported", "status", "lang", "model", "license", "file",
                  "source_kind", "phase", "phase_source", "cluster"):
            if not c.get(k):
                bad.append((c["id"], k))
        if c.get("phase") not in ("compile", "offload"):
            bad.append((c["id"], "phase"))
        if c.get("phase_source") not in ("reported", "inferred"):
            bad.append((c["id"], "phase_source"))
        if c.get("reconstructed", False) not in (False, True,
                                                 "completed_fragment"):
            bad.append((c["id"], "reconstructed"))
        if c.get("weak_reconstruction") and not c.get("reconstructed"):
            bad.append((c["id"], "weak_reconstruction"))
        if not re.fullmatch(r"fresh2-\d{3}", c["id"]):
            bad.append((c["id"], "opaque id"))
        if c["lang"] not in ("f90", "c") or c["model"] not in ("omp", "acc"):
            bad.append((c["id"], "lang/model"))
    assert not bad, bad
    assert all(e.get("reason") and e.get("class") for e in meta["excluded"])
    # a cluster is a case's own id unless it names another case of the set;
    # a shared cluster holds programs that are near copies (next test)
    clusters = {c["cluster"] for c in meta["cases"]}
    assert clusters <= set(ids)
    members: dict = {}
    for c in meta["cases"]:
        members.setdefault(c["cluster"], []).append(c["id"])
    for cl, ms in members.items():
        if len(ms) > 1:
            assert cl in ms
            ps = [FRESH2 / next(c["file"] for c in meta["cases"]
                                if c["id"] == i) for i in ms]
            best = max(FB.program_similarity(FB.program_tokens(a),
                                             FB.program_tokens(b))[0]
                       for a in ps for b in ps if a != b)
            assert best >= FB.COPY_JACCARD, cl


@pytest.mark.needs_bench("fresh2/cases.yaml", "fresh2/SEAL")
def test_fresh2_near_copies_share_a_cluster():
    """Two cases of the set whose programs are near copies (FB.program_
    similarity over identifier-canonical token streams) are resampled
    together: they carry the same cluster."""
    meta = yaml.safe_load((FRESH2 / "cases.yaml").read_text())
    cl = {c["id"]: c["cluster"] for c in meta["cases"]}
    files = FB.case_files(FRESH2)
    toks = {p.stem: FB.program_tokens(p) for p in files}
    bad = []
    for i, a in enumerate(files):
        for b in files[i + 1:]:
            if a.suffix != b.suffix:
                continue
            jac, _ = FB.program_similarity(toks[a.stem], toks[b.stem])
            if jac >= FB.COPY_JACCARD and cl[a.stem] != cl[b.stem]:
                bad.append((a.stem, b.stem))
    assert not bad, f"{len(bad)} near-copy pair(s) in different clusters"


def _known_sets():
    """(cases, directory) of data/bench/wild and data/bench/fresh, as committed."""
    out = []
    for b in ("wild", "fresh"):
        d = ROOT / "data" / "bench" / b
        meta = yaml.safe_load((d / "cases.yaml").read_text())
        out.append((meta["cases"] if isinstance(meta, dict) else meta, d))
    return out


def test_overlap_catches_renamed_copies_and_same_defect(tmp_path):
    """FB.overlaps on fixtures: a program with its identifiers renamed is a
    copy; a different program of the same family, phase, blamed construct
    and reported diagnostic is the same defect; an unrelated program of the
    same family is neither."""
    prog = ("program p\n  implicit none\n  integer :: i, n\n"
            "  real :: a(100), s\n  n = 100\n  s = 0.0\n"
            "  !$omp target teams distribute parallel do reduction(+:s) "
            "map(tofrom: a)\n  do i = 1, n\n    a(i) = a(i) * 2.0 + i\n"
            "    s = s + a(i)\n  end do\n  print *, s\nend program p\n")
    ren = ("program p\n  implicit none\n  integer :: k, cnt\n"
           "  real :: buf(100), tot\n  cnt = 100\n  tot = 0.0\n"
           "  !$omp target teams distribute parallel do reduction(+:tot) "
           "map(tofrom: buf)\n  do k = 1, cnt\n"
           "    buf(k) = buf(k) * 2.0 + k\n    tot = tot + buf(k)\n"
           "  end do\n  print *, tot\nend program p\n")
    other = ("program q\n  integer :: m(4)\n  m = 1\n"
             "  !$omp target update to(m)\n  print *, sum(m)\nend\n")
    mine = tmp_path / "mine"
    known = tmp_path / "known"
    mine.mkdir()
    known.mkdir()
    _case(mine, "fresh2-001.f90", "! fresh case: fresh2-001\n" + ren)
    _case(mine, "fresh2-002.f90", "! fresh case: fresh2-002\n" + other)
    _case(known, "k-1.f90", "! wild case: k-1\n" + prog)
    _case(known, "k-2.c", "// wild case: k-2\nint main(){return 0;}\n")
    m = [{"id": "fresh2-001", "file": "fresh2-001.f90", "family": "cce",
          "failure": "wrong", "reported": "wrong sum", "blame": "reduction"},
         {"id": "fresh2-002", "file": "fresh2-002.f90", "family": "nvhpc",
          "failure": "reject", "blame": "target update",
          "reported": 'rejected with "NVFORTRAN-S-0155-Invalid update '
                      'clause for array m"'}]
    k = [{"id": "k-1", "file": "k-1.f90", "family": "nvhpc",
          "failure": "ice", "reported": "an ICE", "blame": "teams"},
         {"id": "k-2", "file": "k-2.c", "family": "nvhpc",
          "failure": "reject", "blame": "target update|map",
          "reported": 'nvc says "NVFORTRAN-S-0155-Invalid update clause '
                      'for array m" too'}]
    hits = {(a, b, kind) for a, b, kind, _ in
            FB.overlaps(m, mine, [(k, known)])}
    assert ("fresh2-001", "k-1", "copy") in hits      # any family
    assert ("fresh2-002", "k-2", "same_defect") in hits
    assert not any(h[0] == "fresh2-002" and h[1] == "k-1" for h in hits)


def _committed_case(tmp, rev, cid):
    import subprocess
    meta = yaml.safe_load(subprocess.run(
        ["git", "show", f"{rev}:bench/fresh2/cases.yaml"], cwd=ROOT,
        capture_output=True, text=True, check=True).stdout)["cases"]
    c = next(x for x in meta if x["id"] == cid)
    (tmp / c["file"]).write_text(subprocess.run(
        ["git", "show", f"{rev}:bench/fresh2/{c['file']}"], cwd=ROOT,
        capture_output=True, text=True, check=True).stdout)
    return c


@pytest.mark.needs_bench("wild/cases.yaml", "wild/split.yaml", "fresh/cases.yaml")
@pytest.mark.needs_commit("a125ad9")
def test_overlap_flags_the_removed_duplicates(tmp_path):
    """FB.overlaps, against the committed data/bench/wild and data/bench/fresh, flags
    the two cases removed as duplicates (as committed in
    a125ad9): one a renamed copy of a data/bench/wild program of the same family
    and phase, one the same defect as a data/bench/fresh case."""
    ms = [_committed_case(tmp_path, "a125ad9", i)
          for i in ("fresh2-067", "fresh2-079")]
    hits = FB.overlaps(ms, tmp_path, _known_sets())
    assert {h[0] for h in hits} == {"fresh2-067", "fresh2-079"}


@pytest.mark.needs_bench("fresh2/cases.yaml", "fresh2/SEAL")
def test_fresh2_has_no_overlap():
    """No case of data/bench/fresh2 is a copy (identifier-canonical token
    streams), a same-family similar program or the same defect (family,
    phase, blamed construct, reported diagnostic) of a data/bench/wild or
    data/bench/fresh case. Reports only a count: the set is sealed."""
    meta = yaml.safe_load((FRESH2 / "cases.yaml").read_text())["cases"]
    hits = FB.overlaps(meta, FRESH2, _known_sets())
    assert not hits, f"{len(hits)} overlap(s)"


@pytest.mark.needs_bench("fresh2/cases.yaml", "fresh2/SEAL")
def test_fresh2_headers():
    assert (FRESH2 / "cases.yaml").is_file(), "data/bench/fresh2 not built"
    bad = []
    for p in FB.case_files(FRESH2):
        h = FB.header(p)
        if h.get("fresh case") != p.stem:
            bad.append((p.stem, "id"))
        if not re.match(r"https?://", h.get("source", "")):
            bad.append((p.stem, "source"))
        if not h["edits"]:
            bad.append((p.stem, "edits"))
    assert not bad, bad


@pytest.mark.needs_bench("fresh2/cases.yaml", "fresh2/SEAL", "fresh2/outcomes.csv")
def test_fresh2_outcomes_csv_shape():
    p = FRESH2 / "outcomes.csv"
    assert p.is_file(), "no data/bench/fresh2/outcomes.csv"
    rows = list(csv.reader(p.open()))
    assert rows[0] == ["case", "toolchain", "mode", "outcome"]
    ids = {c["id"] for c in yaml.safe_load(
        (FRESH2 / "cases.yaml").read_text())["cases"]}
    assert {r[0] for r in rows[1:]} <= ids


def test_every_subcommand_takes_bench_and_out():
    ap = FB.build_parser()
    for cmd in ("parse", "legality", "outcomes", "summary", "check-seal"):
        a = ap.parse_args([cmd, "--bench", "x", "--out", "y"])
        assert (a.bench, a.out) == ("x", "y")
    a = ap.parse_args(["seal", "--commit", "c", "--bench", "x"])
    assert a.bench == "x"


def test_outcome_rows_keep_only_cases_of_the_set(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "afar.copy.jsonl").write_text("".join(json.dumps(
        {"id": i, "toolchain": "afar", "mode": "copy", "outcome": "ice"})
        + "\n" for i in ("fresh2-001", "fresh2-009")))
    assert [r[0] for r in FB.outcome_rows(runs, {"fresh2-001"})] == \
        ["fresh2-001"]
    assert len(FB.outcome_rows(runs)) == 2


def test_remote_roots_access_overrides():
    """--prefix / --env: the wingtip runs go through the capped
    slice on a chosen GPU; the other access keys stay."""
    from offload.engine.confirm import machines as M
    before = M.load()["wingtip"]
    with FB.remote_roots({"wingtip": "/clone"},
                         prefixes={"wingtip": "tools/jobs/wingtip_capped.sh nice"},
                         envs={"wingtip": {"CUDA_VISIBLE_DEVICES": "1"}}):
        a = M.load()["wingtip"].access
        assert a["root"] == "/clone"
        assert a["run_prefix"] == "tools/jobs/wingtip_capped.sh nice"
        assert a["env"]["CUDA_VISIBLE_DEVICES"] == "1"
        assert a["env"]["COMPLIANT_RUN_SLOTS"] == \
            before.access["env"]["COMPLIANT_RUN_SLOTS"]
        assert a["ssh"] == before.access["ssh"]
    assert M.load()["wingtip"].access == before.access
    assert FB._kv(["wingtip:CUDA_VISIBLE_DEVICES=2", "wingtip:X=y"]) == \
        {"wingtip": {"CUDA_VISIBLE_DEVICES": "2", "X": "y"}}


# ---- The findings promoted from the data/bench/fresh drafts ----------------------------------------------



from offload.engine.confirm import findings as FI
from offload.engine.confirm import forms as FO
from offload.engine.confirm import registry as REG
from offload.engine.confirm import rules as RU
from offload.engine.confirm.facts import Facts
from offload.engine.confirm.legality import Legality
from offload.engine.confirm.model import Case, Evidence, ProgramRef, Run

FRESH = ROOT / "data" / "findings" / "fresh"
TWO = "data/findings/fresh/cce-if-stop-in-target-ice.f90"
ONE = "data/findings/fresh/cce-if-stop-in-target-ice-one-condition.f90"
ICE = ('ice: INTERNAL COMPILER ERROR:  "{msg}" (/workspace/crayftn/pdgcs/'
       '{site}, version {ver})')
VER = {"cce19": "cc4d36e4ff3377d45f0e6e892b5dacd82009a0ca",
       "cce20": "668d73f9607c0349bd23641a3a25a1acfac374de",
       "cce21": "03f45ce3d0ede393b9c256b04948894287765405"}
# the sites of the runs (results/fresh-drafts: d106-e1/e4, d106-e2/e3/e7)
TWO_SITES = {"cce19": "v_region.c, line 636", "cce20": "v_region.c, line 636",
             "cce21": "v_region.c, line 646"}
ONE_SITES = {"cce19": "v_fs.c, line 2323", "cce20": "v_fs.c, line 2325",
             "cce21": "v_fs.c, line 2325"}


def _best(tc, reason, path, ident=""):
    text = (ROOT / path).read_text()
    hits = FI.dedupe(tc, "f90", "ice", reason, text, ident or path,
                     "copy", arch="gfx942", related=True)
    return hits[0] if hits else None


@pytest.mark.parametrize("tc", ["cce19", "cce20", "cce21"])
def test_both_if_stop_ice_forms_link(tc):
    """A recorded site per release must not keep the
    one-condition form (v_fs.c) from linking; each form is a duplicate of
    the finding whose reproducer has it."""
    two = ICE.format(msg="Condition statement not found in condition node",
                     site=TWO_SITES[tc], ver=VER[tc])
    one = ICE.format(msg="COND PDG 20 with no stmts.", site=ONE_SITES[tc],
                     ver=VER[tc])
    h = _best(tc, two, TWO)
    assert h and (h["kind"], h["file"]) == ("duplicate", TWO), h
    h = _best(tc, one, ONE)
    assert h and (h["kind"], h["file"]) == ("duplicate", ONE), h
    # the draft's own program (data/bench/fresh/fresh-106.f90 gives the
    # two-operand ICE)
    h = _best(tc, two, TWO, "/x/bench/fresh/fresh-106.f90")
    assert h and (h["kind"], h["file"]) == ("duplicate", TWO), h


def test_catalog_stop_entry_names_the_related_ice():
    """The catalog STOP entry and the fresh ICE entries
    point at each other."""
    text = (ROOT / "data" / "findings" / "index.yaml").read_text()
    i = text.index("  - file: catalog/cce-flang-stop-in-target-crash.f90\n")
    entry = text[i:text.index("\n  - file:", i + 1)]
    assert "fresh/cce-if-stop-in-target-ice.f90" in entry
    assert "catalog/cce-flang-stop-in-target-crash.f90" in \
        (FRESH / "cce-if-stop-in-target-ice.f90").read_text()


FRESH032 = """program main
    use omp_lib
    implicit none
    integer :: teams
    !$omp target teams if(teams: .false.) map(tofrom: teams)
      teams = omp_get_num_teams()
    !$omp end target teams
end program main
"""
CCE_IF = ('diagnostic: ftn-1028 ftn: ERROR MAIN, File = prog.f90, Line = 5,'
          ' Column = 27 | The IF clause on the !$OMP TARGET TEAMS directive '
          'may only have "TARGET" specified as the directive-name-modifier.'
          '  The compiler found "TEAMS".')
NV_IF = ("diagnostic: NVFORTRAN-S-0155-Unknown directive modifier teams "
         "(prog.f90: 5)")


def test_if_on_teams_is_a_later_form():
    F = {f.id: f for f in FO.forms()}
    fo = F["teams-if"]
    assert fo.since == "5.2"
    assert [f.id for f in FO.match(FRESH032, CCE_IF)] == ["teams-if"]
    assert [f.id for f in FO.match(FRESH032, NV_IF)] == ["teams-if"]
    # on target teams distribute parallel do CCE names two modifiers
    both = CCE_IF.replace('"TARGET"', '"TARGET or PARALLEL"')
    assert [f.id for f in FO.match(FRESH032, both)] == ["teams-if"]
    for tc in ("cce19", "cce20", "cce21", "nvhpc", "nvhpc269"):
        assert not RU.form_claimed(tc, fo, 52), tc
    # another if form at the diagnostic is not this form
    other = CCE_IF.replace('"TEAMS"', '"PARALLEL"')
    assert "teams-if" not in [f.id for f in FO.match(
        FRESH032.replace("if(teams:", "if(parallel:"), other)]


def test_cce19_rejection_of_if_on_teams_is_unsupported():
    """fresh-032: CCE 19 does not claim the 5.2 form,
    so its rejection is R11c, not compiler_bug, though AFAR compiles it."""
    p = ProgramRef("file", "/x/bench/fresh/fresh-032.f90", "f90", 52, "omp",
                   True, (), "construct", FRESH032, "")
    c = Case(p, "cce19", "tuolumne", "gfx942", "copy", "rejected", CCE_IF,
             None, 0, False, 3)
    ev = {"stored_repeats": [Evidence("stored_repeats", "cce19", "gfx942",
                                      "copy", runs=(Run("rejected", None, 0,
                                                        CCE_IF),) * 3)],
          "other_toolchains": [Evidence(
              "other_toolchains", "afar", "gfx942", "copy",
              runs=(Run("correct_on_device", "1", 0),) * 3, value="1")]}

    class Ctx:
        evidence = ev
    f = Facts(c, legality=Legality("legal", "test"),
              registry=REG.matching(p.ident, p.text, p.needs, c.reason),
              findings=[])
    d = RU.decide(f, Ctx(), collect=lambda col: list(ev.get(col.name, [])))
    assert (d.verdict, d.rule) == ("unsupported",
                                   "R11c-later-form-unclaimed"), d
    assert "teams-if" in d.reason


# ---- Tests of offload.engine.ompvv: copy-semantics classification of omp_vv tests ------------------------

from offload.engine.ompvv import (COPY_XNACK, HEADLINE_XNACK, copy_semantics,
                              suite_verdicts, verdict_mode)

HEAD = "program t\n  integer :: a(10), b(10), i\n"


def src(body: str) -> str:
    return HEAD + body + "end program t\n"


def test_device_write_to_a_to_mapped_array_read_by_host():
    s = src("  a = 1\n"
            "  !$omp target map(to: a) map(from: b)\n"
            "    b = a\n"
            "    a(:) = 0\n"
            "  !$omp end target\n"
            "  if (any(a /= 1)) stop 1\n")
    why = copy_semantics(s)
    assert why and "device writes a" in why[0]
    assert verdict_mode(s) == COPY_XNACK


def test_tofrom_or_copy_back_is_not_copy_semantics():
    tofrom = src("  !$omp target map(tofrom: a)\n    a = 0\n"
                 "  !$omp end target\n  if (any(a /= 0)) stop 1\n")
    updated = src("  !$omp target data map(to: a)\n"
                  "  !$omp target\n    a = 0\n  !$omp end target\n"
                  "  !$omp target update from(a)\n"
                  "  !$omp end target data\n  if (any(a /= 0)) stop 1\n")
    assert copy_semantics(tofrom) == [] and copy_semantics(updated) == []
    assert verdict_mode(tofrom) == HEADLINE_XNACK


def test_inner_alloc_of_an_outer_tofrom_mapping_comes_back():
    s = src("  !$omp target data map(to: b) map(tofrom: a)\n"
            "  !$omp target teams distribute map(alloc: a, b)\n"
            "  do i = 1, 10\n    a(i) = b(i)\n  end do\n"
            "  !$omp end target data\n"
            "  if (any(a /= 0)) stop 1\n")
    assert copy_semantics(s) == []


def test_device_write_never_read_on_the_host_is_not_flagged():
    s = src("  !$omp target map(to: a) map(from: b)\n"
            "    a(:) = 0\n    b = 1\n  !$omp end target\n"
            "  if (any(b /= 1)) stop 1\n")
    assert copy_semantics(s) == []


def test_continuations_and_sections_in_map_lists():
    s = src("  !$omp target map(to: a(1:5), &\n  !$omp& b(1:5))\n"
            "    a(1:5) = -1\n  !$omp end target\n"
            "  if (a(1) /= 1) stop 1\n")
    assert copy_semantics(s)


def test_defaultmap_to_covers_unmapped_variables():
    s = src("  !$omp target defaultmap(to: aggregate) map(from: b)\n"
            "    a = 3\n    b = 1\n  !$omp end target\n"
            "  if (any(a /= 0)) stop 1\n")
    why = copy_semantics(s)
    assert len(why) == 1 and "device writes a" in why[0]


def test_host_write_after_enter_data_read_by_a_target_region():
    s = src("  a = 1\n"
            "  !$omp target enter data map(to: a)\n"
            "  a = 0\n"
            "  !$omp target map(from: b)\n    b = a\n  !$omp end target\n"
            "  !$omp target exit data map(delete: a)\n"
            "  if (any(b /= 1)) stop 1\n")
    why = copy_semantics(s)
    assert why and "host writes a" in why[0]
    with_update = s.replace("  a = 0\n",
                            "  a = 0\n  !$omp target update to(a)\n")
    assert copy_semantics(with_update) == []


def test_one_copy_per_device():
    s = src("  integer :: d\n"
            "  do d = 0, 3\n    a = d\n"
            "    !$omp target enter data map(to: a) device(d)\n  end do\n"
            "  do d = 0, 3\n"
            "    !$omp target map(alloc: a) device(d)\n    a = a + 1\n"
            "    !$omp end target\n  end do\n")
    assert any("device-selecting loop" in w for w in copy_semantics(s))


def test_write_in_a_subroutine_read_in_the_caller():
    s = ("module m\n  integer :: arr(10)\ncontains\n"
         "  subroutine sub()\n    !$omp target map(to: arr)\n"
         "    arr = 0\n    !$omp end target\n  end subroutine\n"
         "end module\nprogram p\n  use m\n  arr = 1\n  call sub()\n"
         "  if (any(arr /= 1)) stop 1\nend program\n")
    assert copy_semantics(s)


def test_suite_verdicts_read_each_test_in_its_mode(tmp_path):
    root = tmp_path / "corpus"
    d = root / "omp_vv" / "tests"
    d.mkdir(parents=True)
    (d / "copy.F90").write_text(src(
        "  !$omp target map(to: a)\n    a = 0\n  !$omp end target\n"
        "  if (any(a /= 1)) stop 1\n"))
    (d / "plain.F90").write_text(src(
        "  !$omp target map(tofrom: a)\n    a = 0\n  !$omp end target\n"))
    (d / "wide.F90").write_text(src(
        "  !$omp target map(tofrom: a) defaultmap(tofrom: scalar)\n"
        "    a = 0\n  !$omp end target\n"))
    base = []
    for path, x, st in (("copy", 1, "fail"), ("copy", 0, "pass"),
                        ("plain", 1, "pass"), ("plain", 0, "fail"),
                        ("wide", 1, "pass"), ("wide", 0, "pass")):
        base.append({"repo": "omp_vv", "path": f"tests/{path}.F90",
                     "toolchain": "afar", "xnack": x, "status": st})
    atoms = {"omp.directive.target", "omp.clause.map", "omp.clause.defaultmap"}
    v = suite_verdicts(base, atoms, corpus_root=root)
    # copy.F90 read at 0 (pass), plain.F90 at 1 (pass); wide.F90 has two
    # base clauses, so it is not narrow
    assert v[("omp.clause.map", "afar")] == [2, 0]
    assert v[("omp.directive.target", "afar")] == [2, 0]
    assert ("omp.clause.defaultmap", "afar") not in v


# ---- The omp_vv comparison ----------------------------------------------------------------------------------

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "ompvv_compare", Path(__file__).resolve().parent.parent.parent / "tools" / "derive" / "ompvv_compare.py")
oc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oc)

DIRS = {"target", "target_teams", "target_teams_distribute"}
CLAUSES = {"map", "defaultmap", "order"}
ATOMS = {"omp.clause.defaultmap.scalar", "omp.clause.map.present"}


def test_directive_lines_join_continuations():
    src = "x = 1\n!$omp target &\n!$omp& map(to: a)\n!$omp end target\n"
    assert oc.directive_lines(src) == ["target map(to: a)", "end target"]


def test_atoms_include_modifiers_and_longest_directive():
    src = "!$omp target teams defaultmap(tofrom:scalar) map(present, to: a)\n"
    dirs, cls = oc.atoms_of(src, DIRS | {"target_teams"}, CLAUSES, ATOMS)
    assert dirs == {"target_teams"}
    assert cls == {"omp.clause.defaultmap", "omp.clause.defaultmap.scalar",
                   "omp.clause.map", "omp.clause.map.present"}


def test_end_directives_and_unknown_clauses_are_ignored():
    dirs, cls = oc.atoms_of("!$omp end target\n!$omp target nowait\n",
                            DIRS, CLAUSES, ATOMS)
    assert dirs == {"target"} and cls == set()


def test_ours_reads_device_programs_only():
    """A host+device pattern program (scope host+device) is not
    its atom's result; with full copy-mode runs it overwrote the device
    program's cell of omp.directive.target."""
    rows = [{"legal": "1", "version": "52", "atom": "omp.directive.target",
             "toolchain": "afar", "xnack": "0", "outcome": "correct_on_device",
             "scope": "device"},
            {"legal": "1", "version": "52", "atom": "omp.directive.target",
             "toolchain": "afar", "xnack": "0", "outcome": "wrong_answer",
             "scope": "host+device"}]
    ours = oc.ours_from(rows)
    assert ours[("52", "omp.directive.target", "afar", "0")] == \
        "correct_on_device"


def test_gfx90a_toolchains_read_every_test_at_xnack0():
    """Tioga runs at HSA_XNACK=0 only, so every omp_vv test of a
    gfx90a toolchain is read there and set against our gfx90a cell."""
    assert oc.read_mode("afar_g90", oc.HEADLINE_XNACK) == oc.COPY_XNACK
    assert oc.read_mode("afar", oc.HEADLINE_XNACK) == oc.HEADLINE_XNACK
    assert oc.read_mode("cce19", oc.COPY_XNACK) == oc.COPY_XNACK
    assert oc.mode_name("cce21_g90", 0) == "gfx90a"
    assert oc.mode_name("cce21", 0) == "copy"
    assert oc.mode_name("cce21", 1) == "headline"
