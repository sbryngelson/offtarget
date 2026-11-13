"""Extraction side of the known-issues harvest
(offload/engine/harvest_known/, tools/campaigns/harvest_known.py).

Sources: centre known-issues pages, the NVIDIA HPC compilers forum and
NVHPC release notes, and the workaround history of open offload codes.
Everything here runs on synthetic fixtures; no test reads the downloaded
(untrusted) sources."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine.harvest_known import forum, textscan  # noqa: E402


# --- text scanning shared by every source ---------------------------------------

def test_offload_model_of_code():
    assert textscan.models("!$omp target teams distribute\n") == {"omp-target"}
    assert textscan.models("#pragma omp target map(to: a)\n") == {"omp-target"}
    assert textscan.models("!$acc parallel loop\n") == {"acc"}
    assert textscan.models("  #pragma acc kernels\n") == {"acc"}
    assert textscan.models("!$omp declare target\n") == {"omp-target"}
    # host OpenMP only is not device offload
    assert textscan.models("!$omp parallel do\n") == {"omp-host"}
    assert textscan.models("int main(){}") == set()
    # a sentinel inside a comment line of C is still C text; not a directive
    assert textscan.models("// #pragma omp target\n") == set()


def test_language_of_code():
    assert textscan.language("program p\n  integer :: i\nend program\n") == "fortran"
    assert textscan.language("subroutine s(a)\nend subroutine s\n") == "fortran"
    assert textscan.language("#include <stdio.h>\nint main(void){return 0;}\n") == "c"
    assert textscan.language("#include <iostream>\nint main(){std::cout<<1;}\n") == "c++"
    assert textscan.language("template <typename T> T f(T x){return x;}\n") == "c++"
    assert textscan.language("$ nvfortran -acc x.f90\n") == "shell"


def test_tpr_and_fixed_in():
    t = "I added a problem report, TPR #33317, and engineering will look."
    assert textscan.tprs(t) == {"33317"}
    assert textscan.tprs("TPR 28123 and TPR#28124") == {"28123", "28124"}
    assert textscan.tprs("tpr is not a number") == set()
    assert textscan.fixed_in("This was fixed in the 23.5 release.") == {"23.5"}
    assert textscan.fixed_in("TPR #1234 has been fixed in NVHPC 24.1") == {"24.1"}
    assert textscan.fixed_in("fixed in our 22.11 release") == {"22.11"}
    assert textscan.fixed_in("it is not fixed yet") == set()


def test_compiler_mentions():
    t = "CCE 15.0.1 crashes; works with nvfortran 22.5 and amdflang; AOMP 17"
    got = textscan.compilers(t)
    assert {"cce", "nvhpc", "amd-flang", "aomp"} <= got
    assert textscan.compilers("rocm 6.0 and hipcc") == {"rocm"}
    assert textscan.compilers("plain text") == set()


# --- the forum (Discourse JSON) ----------------------------------------------------

def _topic(posts, title="Wrong answer with acc", tid=101, cat=313):
    return {"id": tid, "title": title, "slug": "wrong-answer", "category_id": cat,
            "created_at": "2024-01-02T00:00:00Z", "posts_count": len(posts),
            "post_stream": {"posts": posts, "stream": [p["id"] for p in posts]}}


def _post(n, cooked, staff=False, user="u"):
    return {"id": 1000 + n, "post_number": n, "cooked": cooked, "staff": staff,
            "username": user, "created_at": "2024-01-0%dT00:00:00Z" % n}


def test_code_blocks_unescaped():
    html = ("<p>see</p><pre><code class=\"lang-auto\">program p\n"
            "  if (a &lt; b) x = 1\n!$acc kernels\nend</code></pre>"
            "<p>and</p><pre><code>int x;</code></pre>")
    blocks = forum.code_blocks(html)
    assert blocks[0].startswith("program p\n  if (a < b) x = 1")
    assert blocks[1] == "int x;"


def test_topic_record_evidence():
    code = ("<pre><code>program p\n!$acc parallel loop\ndo i=1,n\nend do\n"
            "end program</code></pre>")
    t = _topic([_post(1, "<p>wrong results</p>" + code),
                _post(2, "<p>Thanks, I filed TPR #34567. It is a compiler "
                         "bug.</p>", staff=True, user="MatColgrove"),
                _post(3, "<p>FYI, TPR #34567 was fixed in our 24.3 release."
                         "</p>", staff=True, user="MatColgrove")])
    r = forum.topic_record(t)
    assert r["id"] == 101
    assert r["url"] == "https://forums.developer.nvidia.com/t/101"
    assert r["models"] == ["acc"]
    assert r["languages"] == ["fortran"]
    assert r["tprs"] == ["34567"]
    assert r["fixed_in"] == ["24.3"]
    assert r["staff_confirmed"] is True
    assert r["evidence"] == "tpr"
    assert r["n_code"] == 1


def test_topic_record_no_evidence_and_host_only():
    t = _topic([_post(1, "<pre><code>!$omp parallel do\ndo i=1,n\nend do"
                         "</code></pre>")])
    r = forum.topic_record(t)
    assert r["models"] == ["omp-host"]
    assert r["evidence"] is None
    assert r["staff_confirmed"] is False


def test_staff_confirmation_needs_bug_words():
    t = _topic([_post(1, "<p>q</p>"),
                _post(2, "<p>Use the -gpu=managed flag instead.</p>",
                      staff=True)])
    assert forum.topic_record(t)["staff_confirmed"] is False
    t = _topic([_post(1, "<p>q</p>"),
                _post(2, "<p>I was able to reproduce the error and have "
                         "reported it to engineering.</p>", staff=True)])
    assert forum.topic_record(t)["staff_confirmed"] is True
    assert forum.topic_record(t)["evidence"] == "staff"


def test_funnel_stage():
    base = {"models": ["acc"], "languages": ["fortran"], "evidence": "tpr",
            "n_code": 1}
    assert forum.stage(base) == "candidate"
    assert forum.stage({**base, "n_code": 0}) == "no_code"
    assert forum.stage({**base, "models": ["omp-host"]}) == "not_offload"
    assert forum.stage({**base, "models": []}) == "not_offload"
    assert forum.stage({**base, "languages": ["c++"]}) == "cxx_only"
    assert forum.stage({**base, "evidence": None}) == "no_bug_evidence"


def test_listing_topics(tmp_path):
    d = {"topic_list": {"topics": [{"id": 5, "title": "a", "posts_count": 2,
                                    "created_at": "x"}],
                        "more_topics_url": "/c/313?page=2"}}
    assert forum.listing_ids(d) == [5]
    assert forum.listing_has_more(d) is True
    d["topic_list"].pop("more_topics_url")
    assert forum.listing_has_more(d) is False


# --- centre pages (HTML snapshots, Markdown and RST sources) -----------------------

from offload.engine.harvest_known import centres  # noqa: E402


def test_html_sections():
    h = ("<h2>Known Issues</h2><p>intro</p>"
         "<h3>OLCFDEV-1803: CCE/17.0.0 Fortran Issues</h3>"
         "<p>An <code>!$omp target</code> region with crayftn 17 crashes.</p>"
         "<div class=\"highlight\"><pre><span>!$omp target map(tofrom: a)</span>"
         "\nend</pre></div>"
         "<h3>OLCFDEV-1: Slurm thing</h3><p>srun hangs</p>")
    s = centres.html_sections(h)
    assert [x["heading"] for x in s] == ["Known Issues",
                                        "OLCFDEV-1803: CCE/17.0.0 Fortran Issues",
                                        "OLCFDEV-1: Slurm thing"]
    assert s[1]["codes"] == ["!$omp target map(tofrom: a)\nend"]
    assert "crayftn 17 crashes" in s[1]["text"]
    assert s[2]["codes"] == []


def test_markdown_sections():
    md = ("# Title\n\n## Known issues\n\n### nvfortran 22.5: wrong reduction\n\n"
          "Using `!$acc parallel loop reduction` gives 0.\n\n```fortran\n"
          "!$acc parallel loop reduction(+:s)\ndo i=1,n\nend do\n```\n\n"
          "### Other\n\ntext\n")
    s = centres.md_sections(md)
    assert [x["heading"] for x in s] == ["Title", "Known issues",
                                        "nvfortran 22.5: wrong reduction",
                                        "Other"]
    assert s[2]["codes"][0].startswith("!$acc parallel loop reduction")
    assert "gives 0" in s[2]["text"]


def test_rst_sections():
    rst = ("Known Issues\n============\n\nintro\n\n"
           "CCE OpenMP offload crash\n------------------------\n\n"
           "With ``crayftn`` 15 a target region crashes::\n\n"
           "    !$omp target\n    x = 1\n    !$omp end target\n\nafter\n\n"
           ".. code-block:: c\n\n   #pragma omp target\n   {}\n\n"
           "Next\n----\n\nnone\n")
    s = centres.rst_sections(rst)
    assert [x["heading"] for x in s] == ["Known Issues",
                                        "CCE OpenMP offload crash", "Next"]
    assert s[1]["codes"] == ["!$omp target\nx = 1\n!$omp end target",
                             "#pragma omp target\n{}"]


def test_relevance_filter():
    def sec(heading, text, codes=()):
        return {"heading": heading, "text": text, "codes": list(codes)}
    assert centres.relevant(sec("OLCFDEV-1803: CCE/17.0.0 Fortran Issues",
                                "OpenMP offload of derived types fails"))
    assert centres.relevant(sec("x", "nvfortran gives wrong answers with "
                                     "OpenACC kernels"))
    assert centres.relevant(sec("x", "see", ["!$acc parallel loop"]))
    assert not centres.relevant(sec("Slurm srun hang", "srun hangs with "
                                                       "--gpus"))
    # a compiler without a device model: not an offload issue
    assert not centres.relevant(sec("CCE 15 C++20", "std::format missing"))
    # a library issue that mentions OpenMP threads but no compiler
    assert not centres.relevant(sec("rocFFT", "OpenMP threads and rocFFT"))


def test_entry_key_prefers_ticket_id():
    assert centres.entry_key("OLCFDEV-1803: CCE/17.0.0 Fortran Issues") == \
        "OLCFDEV-1803"
    assert centres.entry_key("  Wrong answer with nvfortran 22.5 ") == \
        "wrong answer with nvfortran 22.5"


def test_union_of_entries_across_snapshots():
    a = {"source": "olcf", "page": "p", "snapshot": "2023-01-01",
         "heading": "OLCFDEV-9: CCE OpenMP offload crash", "text": "short",
         "codes": []}
    b = {**a, "snapshot": "2024-05-01", "text": "longer text now",
         "codes": ["!$omp target"]}
    c = {**a, "heading": "OLCFDEV-10: other", "snapshot": "2024-05-01"}
    got = centres.union([b, a, c])
    assert [g["key"] for g in got] == ["OLCFDEV-10", "OLCFDEV-9"]
    e9 = got[1]
    assert e9["first_seen"] == "2023-01-01" and e9["last_seen"] == "2024-05-01"
    assert e9["text"] == "longer text now" and e9["codes"] == ["!$omp target"]
    assert e9["snapshots"] == 2


# --- application workaround history ---------------------------------------------------

from offload.engine.harvest_known import apps  # noqa: E402


def test_commit_mentions_compiler_workaround():
    assert apps.workaround_hit("Avoid NVHPC 25.5 fort2 ICE by expanding f (#1718)")
    assert apps.workaround_hit("Cray CCE: drop `simd` from the GPU directive")
    assert apps.workaround_hit("reversed-stride (amdflang 23.2.x false-nuw)")
    assert apps.workaround_hit("work around a compiler bug in the reduction")
    assert apps.workaround_hit("HSA_XNACK=1 needed for this case")
    assert not apps.workaround_hit("Fix typo in README")
    assert not apps.workaround_hit("Frontier CI walltime bump")
    # the commit names a compiler only as a CI/runner change: still a hit,
    # the triage reads it
    assert apps.workaround_hit("rmeove nvhpc runners (most of them)")


def test_pr_numbers():
    assert apps.pr_numbers("Fix x (#1718)") == [1718]
    assert apps.pr_numbers("Merge pull request #125 from a/b") == [125]
    assert apps.pr_numbers("See #12 and #13") == [12, 13]
    assert apps.pr_numbers("no number") == []


def test_parse_git_log():
    log = ("\x1eabc123 2026-01-02\nAvoid NVHPC ICE (#5)\n\nbody @@ -1,2 line\n"
           "\x1edef456 2025-12-01\nDocs\n")
    got = apps.parse_log(log)
    assert got == [{"commit": "abc123", "date": "2026-01-02",
                    "subject": "Avoid NVHPC ICE (#5)",
                    "body": "body @@ -1,2 line"},
                   {"commit": "def456", "date": "2025-12-01",
                    "subject": "Docs", "body": ""}]


def test_issue_record():
    issue = {"number": 1815, "title": "CCE acc routine element bug",
             "html_url": "https://github.com/MFlowCode/MFC/issues/1815",
             "created_at": "2026-08-01T00:00:00Z", "state": "closed",
             "body": "With CCE 19 at -O2:\n```fortran\n!$acc routine seq\n"
                     "subroutine s(x)\nend subroutine\n```\n",
             "pull_request": None}
    r = apps.issue_record(issue, "MFlowCode/MFC")
    assert r["number"] == 1815 and r["kind"] == "issue"
    assert r["compilers"] == ["cce"]
    assert r["models"] == ["acc"]
    assert r["n_code"] == 1
    assert r["hit"] is True
    issue["pull_request"] = {"url": "x"}
    assert apps.issue_record(issue, "MFlowCode/MFC")["kind"] == "pr"


def test_forum_title_priority():
    hi = forum.title_priority("OpenACC reduction gives wrong results with nvfortran")
    mid = forum.title_priority("OpenMP target offload question")
    lo = forum.title_priority("License server setup on Windows")
    assert hi > mid > lo == 0
    assert forum.title_priority("ICE: internal compiler error with !$acc") > mid


def test_listing_titles():
    d = {"topic_list": {"topics": [{"id": 5, "title": "acc bug"},
                                   {"id": 6, "title": "install"}]}}
    assert forum.listing_titles(d) == {5: "acc bug", 6: "install"}


# --- the set's cases: legality rows ------------------------------------------------

from offload.engine.harvest_known import cases as HC  # noqa: E402


def test_legality_rows_use_prerun_rules_and_race(tmp_path):
    ok = ("! fresh case: hk-901\n! expected: RESULT: pass\nprogram p\n"
          "  integer :: i, a(10)\n  !$omp target teams distribute parallel do "
          "map(from: a)\n  do i = 1, 10\n    a(i) = i\n  end do\n"
          "  print '(a)', 'RESULT: pass'\nend program p\n")
    racy = ("! fresh case: hk-902\n! expected: RESULT: pass\nprogram p\n"
            "  integer :: i, s\n  s = 0\n  !$omp target teams distribute "
            "parallel do map(tofrom: s)\n  do i = 1, 10\n    s = s + i\n"
            "  end do\n  print '(a)', 'RESULT: pass'\nend program p\n")
    (tmp_path / "hk-901.f90").write_text(ok)
    (tmp_path / "hk-902.f90").write_text(racy)
    rows = HC.legality_rows(sorted(tmp_path.glob("hk-*.f90")), frontend=False)
    by = {r["id"]: r for r in rows}
    assert set(by) == {"hk-901", "hk-902"}
    # one witness only: never ok, but the race is named
    assert by["hk-901"]["ok"] is False and by["hk-902"]["ok"] is False
    assert any("race" in w for w in by["hk-902"]["reasons"])
    assert not any("race" in w for w in by["hk-901"]["reasons"])


def test_url_keys_normalize_sources():
    k = HC.url_key
    assert k("https://forums.developer.nvidia.com/t/wrong-output/331339") == "nvforum:331339"
    assert k("https://forums.developer.nvidia.com/t/331339") == "nvforum:331339"
    assert k("https://forums.developer.nvidia.com/t/x/331339/4") == "nvforum:331339"
    assert k("https://github.com/MFlowCode/MFC/issues/1815") == "gh:mflowcode/mfc#1815"
    assert k("https://github.com/MFlowCode/MFC/pull/1286") == "gh:mflowcode/mfc#1286"
    assert k("https://github.com/MFlowCode/MFC/commit/f95b2c4b2") == "commit:f95b2c4"
    assert k("https://gitlab.com/QEF/q-e/-/commit/741957c8e374c0") == "commit:741957c"
    assert k("https://docs.olcf.ornl.gov/x.html#a") == "https://docs.olcf.ornl.gov/x.html#a"


def test_known_keys_from_sets(tmp_path):
    (tmp_path / "cases.yaml").write_text(
        "cases:\n- id: a-1\n  url: https://github.com/o/r/issues/5\n"
        "  also: [https://forums.developer.nvidia.com/t/s/77]\n"
        "excluded:\n- source: https://github.com/o/r/pull/9\n  class: cxx\n")
    keys = HC.known_keys([tmp_path])
    assert keys == {"gh:o/r#5": "a-1", "nvforum:77": "a-1",
                    "gh:o/r#9": "excluded"}


# --- NVHPC/PGI release notes: fixed-TPR tables -----------------------------------------

from offload.engine.harvest_known import relnotes  # noqa: E402


def test_pgi_tpr_rows():
    html = ("<tr><td>20128</td><td>14.6</td><td>Fortran</td><td>pgfortran "
            "code containing allocatable class types fails</td><td>Corrected"
            "</td></tr><tr><td>19997</td><td>14.6</td><td>PGI Accelerator</td>"
            "<td>Using kernels region over sequential code fails</td><td>"
            "Corrected the processing</td></tr><tr><td>x</td></tr>"
            "<tr><td> 18947 </td><td> 14.4 </td><td> OpenACC </td>"
            "<td class=\"left\"> Reduction fails above 256 threads \n<br/>\n"
            " Corrected the launch </td></tr>")
    rows = relnotes.pgi_tpr_rows(html)
    assert rows == [
        {"tpr": "20128", "release": "14.6", "category": "Fortran",
         "problem": "pgfortran code containing allocatable class types fails",
         "fix": "Corrected"},
        {"tpr": "19997", "release": "14.6", "category": "PGI Accelerator",
         "problem": "Using kernels region over sequential code fails",
         "fix": "Corrected the processing"},
        {"tpr": "18947", "release": "14.4", "category": "OpenACC",
         "problem": "Reduction fails above 256 threads",
         "fix": "Corrected the launch"}]
    assert relnotes.is_accelerator(rows[1]) and not relnotes.is_accelerator(rows[0])


def test_holdout_rule_matches_49a():
    import hashlib
    # the rule: sha256 of the program text in the lowest 30% of the space
    for t in ("a", "b", "program p\nend\n", "x" * 100):
        h = int(hashlib.sha256(t.encode()).hexdigest(), 16)
        assert HC.holdout(t) == (h < int(0.30 * (1 << 256)))
    share = sum(HC.holdout(f"case {k}") for k in range(2000)) / 2000
    assert 0.25 < share < 0.35


def test_export_rows(tmp_path):
    (tmp_path / "hk-901.f90").write_text("! fresh case: hk-901\nprogram p\n!$acc parallel\n!$acc end parallel\nend\n")
    (tmp_path / "hk-902.c").write_text("// fresh case: hk-902\nint main(void){\n#pragma acc parallel\n{}\nreturn 0;}\n")
    (tmp_path / "hk-903.f90").write_text("! fresh case: hk-903\nprogram p\n!$omp target\n!$omp end target\nend\n")
    (tmp_path / "cases.yaml").write_text(
        "cases:\n- {id: hk-901, file: hk-901.f90, lang: f90, model: acc}\n"
        "- {id: hk-902, file: hk-902.c, lang: c, model: acc}\n"
        "- {id: hk-903, file: hk-903.f90, lang: f90, model: omp, omp_version: 60}\n")
    rows = {r["id"]: r for r in HC.export_rows(tmp_path)}
    assert rows["hk-901"]["version"] == 34 and rows["hk-901"]["model"] == "acc"
    assert rows["hk-903"]["version"] == 60
    assert rows["hk-901"]["modes"] == ["copy", "unified"]
    assert rows["hk-901"]["toolchains"] == ["cce19", "cce20", "cce21", "cce19_g90",
                                            "cce20_g90", "cce21_g90", "nvhpc", "nvhpc269"]
    assert rows["hk-902"]["toolchains"] == ["nvhpc", "nvhpc269"]
    assert "afar" in rows["hk-903"]["toolchains"]
    assert rows["hk-903"]["holdout"] == HC.holdout((tmp_path / "hk-903.f90").read_text())
    assert rows["hk-901"]["record"] == "hk-901" and rows["hk-901"]["oracle"] == "selfcheck"


def test_run_groups_split_by_toolchain():
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    import harvest_known as HK
    rows = [{"id": "a", "toolchains": HC.toolchains_for("f90", "omp")},
            {"id": "b", "toolchains": HC.toolchains_for("f90", "acc")},
            {"id": "c", "toolchains": HC.toolchains_for("c", "acc")}]
    got = HK.run_groups(rows, ["afar", "cce19", "cce20", "cce21"])
    assert sorted((tuple(t), tuple(i)) for t, i in got) == [
        (("afar",), ("a",)), (("cce19", "cce20", "cce21"), ("a", "b"))]
    got = HK.run_groups(rows, ["nvhpc", "nvhpc269"])
    assert got == [(["nvhpc", "nvhpc269"], ["a", "b", "c"])]


def test_overlap_hides_sealed_ids(tmp_path):
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    import harvest_known as HK
    prog = "program p\n  integer :: i, a(10)\n  !$omp target teams distribute parallel do map(from: a)\n  do i = 1, 10\n    a(i) = i*2 + 3\n  end do\n  print *, a\nend program p\n"
    mine = tmp_path / "mine"; mine.mkdir()
    sealed = tmp_path / "fresh2"; sealed.mkdir()
    (mine / "hk-901.f90").write_text("! fresh case: hk-901\n" + prog)
    (sealed / "fresh2-007.f90").write_text("! fresh case: fresh2-007\n" + prog.replace("a(", "b(").replace(" a", " b"))
    (mine / "cases.yaml").write_text("cases:\n- {id: hk-901, file: hk-901.f90, url: 'https://x/1', family: cce, failure: wrong, blame: target, reported: r}\n")
    (sealed / "cases.yaml").write_text("cases:\n- {id: fresh2-007, file: fresh2-007.f90, url: 'https://x/1', family: cce, failure: wrong, blame: target, reported: r}\n")
    hits = HK.overlap_hits(mine, [("fresh2", sealed, True)])
    assert hits and all(h["other"] == "fresh2" and h["other_id"] is None for h in hits)
    kinds = {h["kind"] for h in hits}
    assert "url" in kinds and "copy" in kinds


def test_summary_tables():
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    import harvest_known as HK
    rows = [{"program_id": "hk-901", "toolchain": "cce19", "xnack": 0, "outcome": "correct_on_device"},
            {"program_id": "hk-901", "toolchain": "cce19", "xnack": 1, "outcome": "wrong_answer", "reason": "check_fail: x"},
            {"program_id": "hk-902", "toolchain": "nvhpc", "xnack": 2, "outcome": "rejected", "reason": "compile: y"},
            {"program_id": "hk-009", "toolchain": "nvhpc", "xnack": 0, "outcome": "rejected"}]
    t = HK.outcome_table(rows, drop={"hk-009"})
    assert t[("cce19", 0)]["correct_on_device"] == 1
    assert t[("cce19", 1)]["wrong_answer"] == 1
    assert t[("nvhpc", 2)]["rejected"] == 1
    assert ("nvhpc", 0) not in t
    fails = HK.failing(rows, drop={"hk-009"})
    assert [(f["program_id"], f["toolchain"], f["xnack"]) for f in fails] == [
        ("hk-901", "cce19", 1), ("hk-902", "nvhpc", 2)]


def test_shard_rows_partition_by_id():
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    import harvest_known as HK
    rows = [{"id": "hk-9%02d" % k} for k in range(1, 82)]
    a, b = HK.shard_rows(rows, "0/2"), HK.shard_rows(rows, "1/2")
    assert {r["id"] for r in a} | {r["id"] for r in b} == {r["id"] for r in rows}
    assert not ({r["id"] for r in a} & {r["id"] for r in b})
    assert HK.shard_rows(rows, "0/2") == a


def test_holdout_split_moves_and_seals(tmp_path):
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    import harvest_known as HK
    import yaml
    bench, hold = tmp_path / "data" / "bench", tmp_path / "hold"
    bench.mkdir(parents=True)
    cases = []
    for k in range(1, 9):
        name = "hk-9%02d.f90" % k
        (bench / name).write_text("! fresh case: hk-9%02d\n! source: https://x/%d\nprogram p%d\nend\n" % (k, k, k))
        cases.append({"id": "hk-9%02d" % k, "file": name, "url": "https://x/%d" % k,
                      "lang": "f90", "model": "omp", "source_kind": "forum"})
    (bench / "cases.yaml").write_text(yaml.safe_dump({"cases": cases, "excluded": []}))
    rows = HC.export_rows(bench)
    want = sorted(r["id"] for r in rows if r["holdout"])
    runs = [{"program_id": r["id"], "toolchain": "afar", "xnack": 0, "outcome": "correct_on_device",
             "reason": ""} for r in rows]
    progs = {r["id"]: r for r in rows}
    n = HK.split_holdout(bench, hold, rows, runs, commit="abc1234", progs=progs, verdicts={})
    meta = yaml.safe_load((hold / "cases.yaml").read_text())["cases"]
    assert n == len(want) == len(meta)
    assert [c["program"] for c in meta] == want
    for c in meta:
        assert (hold / c["file"]).is_file() and not (bench / (c["program"] + ".f90")).exists()
        assert (hold / c["file"]).read_text().startswith("! fresh case: " + c["id"])
    left = yaml.safe_load((bench / "cases.yaml").read_text())
    assert sorted(c["id"] for c in left["cases"]) == sorted(set("hk-9%02d" % k for k in range(1, 9)) - set(want))
    assert left["holdout"]["cases"] == len(want)
    seal = (hold / "SEAL").read_text()
    assert "commit: abc1234" in seal and "outcomes_sha256:" in seal
    assert "hk-9" not in seal
    import fresh_bench as FB
    paths = sorted(p for p in hold.iterdir() if p.suffix in (".f90", ".c"))
    assert FB.check_seal(hold / "SEAL", paths, hold / "cases.yaml", hold / "outcomes.csv") == []
    # The columns; the hk ids are not in outcomes.csv
    lines = (hold / "outcomes.csv").read_text().splitlines()
    assert lines[0] == "case,toolchain,mode,outcome,gate"
    assert not any("hk-9" in ln for ln in lines)


def test_applicable_drops_rows_outside_the_modes():
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    import harvest_known as HK
    progs = {"a": {"modes": ["copy"]}, "b": {"modes": ["copy", "unified"]}}
    rows = [{"program_id": p, "xnack": x} for p in ("a", "b", "c") for x in (0, 1, 2)]
    got = {(r["program_id"], r["xnack"]) for r in HK.applicable(rows, progs)}
    assert got == {("a", 0), ("b", 0), ("b", 1), ("b", 2), ("c", 0), ("c", 1), ("c", 2)}


def test_export_keeps_moved_holdout_programs():
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    import harvest_known as HK
    old = {"hk-901": {"id": "hk-901", "file": "hk-901.f90", "holdout": False},
           "hk-902": {"id": "hk-902", "file": "hk-902.f90", "holdout": True},
           "hk-904": {"id": "hk-904", "file": "hk-904.f90", "holdout": False}}
    new = [{"id": "hk-901", "file": "hk-901.f90", "holdout": False}]
    # hk-902: moved to the holdout, its metadata kept (no copy needed);
    # hk-904: not a holdout program, so dropped from the bench on purpose
    assert [r["id"] for r in HK.keep_moved(old, new)] == ["hk-901", "hk-902"]
    assert [r["id"] for r in HK.keep_moved(old, new + [old["hk-902"]])] == ["hk-901", "hk-902"]

def test_holdout_is_a_top_level_sealed_set():
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    import harvest_known as HK
    assert HK.HOLDOUT == ROOT / "data" / "bench" / "harvest-known-holdout"


def test_holdout_outcomes_have_49a_semantics():
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    import harvest_known as HK
    progs = {"hk-901": {"id": "hk-901", "holdout": True, "toolchains": ["cce19", "nvhpc"],
                        "modes": ["copy"]},
             "hk-902": {"id": "hk-902", "holdout": False, "toolchains": ["cce19"],
                        "modes": ["copy", "unified"]},
             "hk-903": {"id": "hk-903", "holdout": True, "toolchains": ["afar"],
                        "modes": ["copy", "unified"]}}
    runs = [{"program_id": "hk-901", "toolchain": "cce19", "xnack": 0, "outcome": "rejected",
             "reason": "ice: ftn-7991 INTERNAL COMPILER ERROR"},
            {"program_id": "hk-901", "toolchain": "nvhpc", "xnack": 0, "outcome": "wrong_answer",
             "reason": "crash: SIGSEGV"},
            {"program_id": "hk-902", "toolchain": "cce19", "xnack": 0, "outcome": "rejected",
             "reason": "diagnostic: x"},
            {"program_id": "hk-903", "toolchain": "afar", "xnack": 0,
             "outcome": "correct_on_device", "reason": ""}]
    ver = {"harvest|hk-901|cce19|0": "confirmed", "harvest|hk-901|nvhpc|0": "environment"}
    got = HK.holdout_outcomes(progs, runs, ver)
    assert got == [
        ["harvest-known-holdout-001", "cce19", "copy", "ice", "confirmed"],
        ["harvest-known-holdout-001", "cce19", "unified", "not_applicable", ""],
        ["harvest-known-holdout-001", "nvhpc", "copy", "crash", "environment"],
        ["harvest-known-holdout-001", "nvhpc", "managed", "not_applicable", ""],
        ["harvest-known-holdout-002", "afar", "copy", "correct_on_device", ""],
        ["harvest-known-holdout-002", "afar", "unified", "not_run", ""]]


def test_confirm_rows_carry_outcome_classes():
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    import harvest_known as HK
    rows = [{"program_id": "hk-008", "toolchain": "cce19", "xnack": 1, "outcome": "wrong_answer",
             "reason": "crash: SIGABRT", "stdout": "", "lang": "f90"},
            {"program_id": "hk-030", "toolchain": "nvhpc", "xnack": 0, "outcome": "rejected",
             "reason": "ice: NVC++-F-0000-Internal compiler error. targetinfo symbol not found",
             "stdout": "", "lang": "c"},
            {"program_id": "hk-040", "toolchain": "nvhpc", "xnack": 2, "outcome": "wrong_answer",
             "reason": "exit_status: 1", "stdout": "", "lang": "f90"}]
    got = {r.ident: r.outcome for r in HK.confirm_rows(rows)}
    assert got == {"hk-008": "crash", "hk-030": "ice", "hk-040": "run_error"}
    assert all(r.kind == "file" for r in HK.confirm_rows(rows))


def test_gate_verdicts_as_the_confirmer_reads_them():
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    import harvest_known as HK
    ver = [{"cell": "harvest|hk-008|cce19|1", "program": "hk-008", "toolchain": "cce19",
            "xnack": 1, "verdict": "confirmed"},
           {"cell": "harvest|hk-030|cce19|0", "program": "hk-030", "toolchain": "cce19",
            "xnack": 0, "verdict": None}]
    assert HK.gate_verdict_records(ver) == [
        {"cell": "harvest|hk-008|cce19|1", "kind": "file", "ident": "hk-008",
         "toolchain": "cce19", "xnack": 1, "verdict": "confirmed"}]


def test_tables_name_no_holdout_cell(tmp_path, monkeypatch):
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    import harvest_known as HK
    monkeypatch.setattr(HK, "OUT", tmp_path)
    progs = [{"id": "hk-901", "holdout": False, "modes": ["copy", "unified"], "source": "forum",
              "file": "hk-901.c"},
             {"id": "hk-902", "holdout": True, "modes": ["copy", "unified"], "source": "app",
              "file": "hk-902.c"}]
    (tmp_path / "programs.jsonl").write_text("".join(json.dumps(p) + "\n" for p in progs))
    (tmp_path / "main").mkdir()
    rows = [{"program_id": p, "toolchain": "cce19", "xnack": 0, "outcome": "rejected",
             "reason": "diagnostic: secret-%s" % p} for p in ("hk-901", "hk-902")]
    (tmp_path / "main" / "rows.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    text = HK.render_tables(["main"])
    assert "hk-901" in text and "secret-hk-901" in text
    assert "hk-902" not in text and "secret-hk-902" not in text and "holdout" not in text.lower()
    # the counts include the holdout
    assert "| cce19 | copy (HSA_XNACK=0 / separate) | 2 | 2 |" in text


def test_the_holdout_is_an_unspent_sealed_set_the_lanes_leave_out():
    """At the top level, master's sealed-set guard sees it
    (data/bench/<set>/SEAL); a subdirectory of another set escaped it. Tuolumne
    only: the wingtip lanes do not copy the set this test looks for."""
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    import wingtip_offline as W
    if not (ROOT / "data" / "bench" / "harvest-known-holdout" / "SEAL").is_file():
        pytest.skip("the sealed set is not here (a wingtip lane)")
    assert "data/bench/harvest-known-holdout" in W.sealed_unspent(ROOT)
    assert W.under_sealed("data/bench/harvest-known-holdout/cases.yaml", W.sealed_unspent(ROOT))


@pytest.mark.needs_bench("harvest-known/cases.yaml")
def test_holdout_membership_is_the_original_split():
    """The holdout is the 22 cases of the original split; the
    development set keeps every other case (membership never changes after
    the split)."""
    import yaml
    dev = yaml.safe_load((ROOT / "data" / "bench" / "harvest-known" / "cases.yaml").read_text())
    assert dev["holdout"]["cases"] == 22
    assert len(dev["cases"]) == 66
