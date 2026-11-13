"""The citation checker (offload.engine.citations,
tools/repo/check_citations.py). Every spec citation in the findings, the vendor
drafts and the rulings is checked against the spec text: the section
exists, the printed page (read from the page footers, as
offload.engine.dataenv_rules does) holds it, and the cited lines hold the
quoted text."""
import pytest

from offload.engine import citations as C

pytestmark = pytest.mark.needs_spec

Q1730 = ("the effect of the lastprivate clause is as if the same list item "
         "appears in a map clause with a map-type of tofrom")


def one(text, path="x.f90"):
    cs = C.extract(text, path)
    assert len(cs) == 1, cs
    return cs[0]


def status(text, path="x.f90"):
    return C.check(one(text, path)).status


# --- parsing -------------------------------------------------------------------------

def test_parse_full_form():
    c = one('! "x" (OpenMP 5.2 §17.2 p.340 l.21-30)\n')
    assert (c.version, c.section, c.pages, c.lines) == \
        ("OpenMP 5.2", "17.2", [(340, 340)], "21-30")
    assert c.line == 1


def test_parse_short_and_acc_forms():
    assert one("see 5.0 §2.19.7 p.314").version == "OpenMP 5.0"
    c = one("(OpenACC 3.4 §2.12 p.77)")
    assert (c.version, c.section, c.pages) == ("OpenACC 3.4", "2.12",
                                                [(77, 77)])
    c = one("spec: OpenMP 5.2 §15.2, p.316 (critical construct)")
    assert c.pages == [(316, 316)]
    assert one("(5.2 §7.8.1 p.205-206)").pages == [(205, 206)]


def test_version_is_inherited_from_the_file_context():
    cs = C.extract("Each file is legal OpenMP 5.2.\n! - §5.4.3 p.111\n"
                   "! OpenACC 3.4 §2.6.2 l.1374 and §2.13 p.81\n", "x.f90")
    assert [(c.version, c.section) for c in cs] == [
        ("OpenMP 5.2", "5.4.3"), ("OpenACC 3.4", "2.6.2"),
        ("OpenACC 3.4", "2.13")]
    assert cs[1].lines == "1374" and cs[1].pages == []


def test_quote_before_parenthesis_belongs_to_the_first_citation():
    cs = C.extract(f'!   "{Q1730}"\n!   (5.2 §17.2 p.340 l.27-30;'
                   ' 5.0 §2.14 p.219 l.18-20)\n', "x.f90")
    assert cs[0].quote == Q1730 and cs[1].quote is None


def test_quote_after_colon_and_markdown_blockquote():
    c = one('// - §17.2 p.340 l.27-30: "If the target construct is among '
            'the"\n', "x.c")
    assert c.quote.startswith("If the target") and c.version is None
    c = one("OpenMP 5.2 §17.2 p.340 l.27-30:\n\n> If the target construct "
            "is among the\n> constituent constructs\n\nnext\n", "x.md")
    assert c.quote == "If the target construct is among the constituent " \
                      "constructs"


def test_no_version_anywhere_is_unparseable():
    assert status("see §5.4.3 p.111") == "unparseable"
    assert status("Manual 25.11 §7.4") == "unparseable"


# --- checking ------------------------------------------------------------------------

def test_ok_forms():
    assert status(f'"{Q1730}" (5.2 §17.2 p.340 l.27-30)') == "ok"
    assert status("(5.2 §17.2 p.340)") == "ok"
    assert status("(5.2 §17.2 p.339-340)") == "ok"
    assert status("(5.2 §17.2)") == "ok"
    # a parent section on a page of one of its subsections
    assert status("(5.2 §5.8 p.149)") == "ok"
    assert status("(OpenACC 3.4 §2.6.2 l.1372-1373)") == "ok"
    # a quote with an ellipsis
    assert status('"If the target construct is among the ... with a '
                  'map-type of tofrom" (5.2 §17.2 p.340 l.27-30)') == "ok"


def test_wrong_page_names_the_right_one():
    r = C.check(one(f'"{Q1730}" (5.2 §17.2 p.339 l.27-30)'))
    assert r.status == "wrong_page" and "p.340 l.29-30" in r.detail
    r = C.check(one("(5.2 §17.2 p.300)"))
    assert r.status == "wrong_page" and "p.339" in r.detail


def test_wrong_lines_on_the_right_page():
    r = C.check(one(f'"{Q1730}" (5.2 §17.2 p.340 l.21-22)'))
    assert r.status == "wrong_lines" and "l.29-30" in r.detail


def test_wrong_section():
    r = C.check(one(f'"{Q1730}" (5.2 §17.3 p.340 l.27-30)'))
    assert r.status == "wrong_section" and "17.2" in r.detail
    assert status("(5.2 §99.1 p.340)") == "wrong_section"


def test_quote_not_found():
    assert status('"no spec says this sentence at all, ever" '
                  '(5.2 §17.2 p.340 l.27-30)') == "quote_not_found"


def test_allowlist_marks_external_texts():
    allow = [{"match": r"User's Guide", "reason": "vendor guide"}]
    cs = C.extract("User's Guide 25.11 §7.4 and its §2.20; 5.2 §17.2 p.340,"
                   " then §17.2", "x.md", allow=allow)
    assert [c.external for c in cs] == ["vendor guide", "vendor guide",
                                        None, None]
    assert C.check(cs[0]).status == "external"
    assert [C.check(c).status for c in cs[2:]] == ["ok", "ok"]


def test_structured_rulings_citations():
    cs = C.extract_rulings_yaml(
        "rulings:\n  - id: X\n    rulings_md: \"(5.2 §17.2 p.340)\"\n"
        "    citations:\n      - {version: \"5.2\", section: \"17.2\", "
        f"page: 340, quote: \"{Q1730}\"}}\n", "r.yaml")
    assert len(cs) == 2 and cs[1].quote == Q1730
    assert all(C.check(c).status == "ok" for c in cs)


# --- the committed tree --------------------------------------------------------------

def test_every_citation_in_the_tree_checks():
    """Every citation of the findings, the vendor drafts and the rulings
    checks (the allowlist names only texts not in results/spec_cache)."""
    results = C.scan()
    assert len(results) > 500
    bad = [r for r in results
           if r.status not in ("ok", "external", "skipped")]
    assert not bad, "\n".join(r.line() for r in bad[:40])


def test_allowlist_entries_are_used_and_reasoned():
    allow = C.load_allowlist()
    assert allow and all(a["reason"].strip() for a in allow)
    used = {r.cite.external for r in C.scan() if r.status == "external"}
    assert {a["reason"] for a in allow} <= used


def test_unchecked_forms_are_reported_as_skipped():
    """An appendix or glossary reference by page and a bare page
    without a quote are listed as skipped, not dropped."""
    cs = C.extract("Appendix B.1 p.625 says so; glossary p.159 l.5792-5796; "
                   "OpenMP 5.2 exit steps (p.154 l.1-11)", "x.md")
    assert [C.check(c).status for c in cs] == ["skipped"] * 3
    assert "appendix" in C.check(cs[0]).detail


def test_check_citations_without_the_specification_pdfs_says_where_to_get_them(monkeypatch, capsys):
    import importlib.util
    from offload.engine import citations as Cit
    from offload.engine.root import ROOT
    spec = importlib.util.spec_from_file_location("check_citations", ROOT / "tools" / "repo" / "check_citations.py")
    CC = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(CC)

    def absent(_paths):
        raise FileNotFoundError(ROOT / "spec" / "openmp" / "openmp-6.0.pdf")     # as spec_text raises it
    monkeypatch.setattr(Cit, "scan", absent)
    assert CC.main([]) == 2
    err = capsys.readouterr().err
    assert "spec/" in err and "docs/tooling/setup.md" in err and "Traceback" not in err
