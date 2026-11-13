"""Tests of the static site: its pages and query state, its published data, and the finding matrix."""


# ---- The static site: pages, query state, sizes, no external requests, copy rules ------------------------

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from offload.engine.site import data as D
from offload.engine.site.header import SiteHeader

ROOT = Path(__file__).resolve().parent.parent.parent


def _toolchains_js() -> str:
    """The generated toolchain constants the pages load before the scripts."""
    return (ROOT / "site/static/toolchains.js").read_text()
spec = importlib.util.spec_from_file_location("site_build", ROOT / "tools/site/site_build.py")
SB = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SB)


@pytest.fixture
def site(tmp_path):
    fs = [finding("cce21-a", SiteHeader(title="Hand title", workaround="Map it explicitly.",
                                        found_in="MFC")),
          finding("fuzz/b2", SiteHeader(same_as="cce21-a")),
          finding("plain", outcome="rejected"),
          finding("mixed-one", SiteHeader(disposition=("mixed", "legality disputed")),
                  status=("mixed", None))]
    recs = D.records(fs)
    D.write(tmp_path, recs)
    (tmp_path / "data/compilers").mkdir()
    for tc, page in D.compilers(recs).items():
        (tmp_path / "data/compilers" / f"{tc}.json").write_text(json.dumps(page))
    (tmp_path / "data/canuse").mkdir()
    (tmp_path / "data/canuse/index.json").write_text('["clause.defaultmap"]')
    (tmp_path / "data/canuse/c.json").write_text(json.dumps(
        {"clause.defaultmap": [{"id": "omp52-clause-defaultmap", "version": "5.2", "lang": "f90",
                                "citation": "OpenMP 5.2 §5.8.7", "model": "omp", "issues": [],
                                "cells": {"cce21|mi300a-u": {"state": "correct"}}}]}))
    SB.render(tmp_path)
    return tmp_path


def test_build_writes_every_page(site):
    for p in ("index.html", "canuse.html", "method.html", "static/site.css", "static/issues.js",
              "static/query.js", "static/canuse.js", "static/toolchains.js", "issues/cce21-a.html",
              "issues/fuzz--b2.html",
              "issues/plain.html", "issues/mixed-one.html", "compilers/cce21_4.html", "compilers/afar.html"):
        assert (site / p).is_file(), p


def test_issue_page_shows_present_sections_and_omits_empty_ones(site):
    full = (site / "issues/cce21-a.html").read_text()
    for part in ("Hand title", "Workaround", "Map it explicitly.", "Found in", "Affected variants",
                 "Evidence", "behaves incorrectly", "correct"):
        assert part in full, part
    bare = (site / "issues/plain.html").read_text()
    assert "Workaround" not in bare and "Found in" not in bare and "Mixed evidence" not in bare
    assert "Appears not to support: defaultmap" in bare
    assert "Mixed evidence" in (site / "issues/mixed-one.html").read_text()


def test_reproducers_listed_on_defect_page(site):
    assert "fuzz--b2.html" in (site / "issues/cce21-a.html").read_text()


def test_compiler_page_lists_its_issues(site):
    t = (site / "compilers/cce21.html").read_text()
    # grouped by kind, each issue with its status and, where it regressed, the mark
    assert "issues/cce21-a.html" in t and "Wrong answers" in t and "Open · regression" in t


def test_query_round_trip_and_fallback():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on this machine (run by tools/site/site_check.py)")
    js = _toolchains_js() + (ROOT / "site/static/query.js").read_text() + """
const s = {fams: ['nvhpc'], vers: ['26.9'], kinds: ['incorrect'], q: 'lastprivate', sort: 'construct', regOnly: true};
const back = fromQuery(toQuery(s));
console.log(JSON.stringify([back.fams, back.vers, back.kinds, back.q, back.sort, back.regOnly]));
const bad = fromQuery('?fam=nosuch&sort=zzz&vers=99');
console.log(JSON.stringify([bad.fams, bad.sort, bad.vers]));
const two = fromQuery('?fam=cce,afar&vers=21.0.3,AFAR 24.3.0,26.9');
console.log(JSON.stringify([two.fams, two.vers, toQuery(fromQuery('')), toQuery(two).includes('fam=cce%2Cafar')]));
"""
    out = subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=30).stdout.splitlines()
    assert json.loads(out[0]) == [["nvhpc"], ["26.9"], ["incorrect"], "lastprivate", "construct", True]
    fams, sort, vers = json.loads(out[1])
    assert fams == ["cce", "afar", "nvhpc", "gcc"] and sort == "fixed" and vers == []   # all families by default
    # several families; a version of an unselected family drops; the default view has an empty query
    assert json.loads(out[2]) == [["cce", "afar"], ["21.0.3", "AFAR 24.3.0"], "", True]


def test_csv_columns():
    js = (ROOT / "site/static/issues.js").read_text()
    assert "const CSV_COLUMNS = ['id', 'title', 'kind', 'phase', 'stage', 'symptom', 'legality', 'lang', 'model', 'versions_failing', " \
           "'targets_failing', 'status', 'status_version', 'regression', 'reproducers', 'specs']" in js


def test_static_size_limits(site):
    files = [p for p in site.rglob("*") if p.is_file()]
    assert sum(p.stat().st_size for p in files) < 100 * 2 ** 20
    assert max(p.stat().st_size for p in files) < 25 * 2 ** 20


def test_no_external_requests_except_fonts(site):
    for p in site.rglob("*.html"):
        # what a page loads (src, and a <link>'s href); a link a reader follows (<a href>) is no request
        t = p.read_text()
        for url in re.findall(r'\bsrc="([^"]+)"', t) + re.findall(r'<link\b[^>]*\bhref="([^"]+)"', t):
            assert not url.startswith(("http:", "https:", "//")) or url.startswith(
                ("https://fonts.googleapis.com/", "https://fonts.gstatic.com/")), (p, url)
    for p in (site / "static").glob("*.js"):
        assert not re.search(r"fetch\(\s*['\"]https?:", p.read_text()), p


def test_no_first_person_in_pages(site):
    for p in list(site.rglob("*.html")) + list((site / "static").glob("*.js")):
        text = re.sub(r"<script[^>]*>.*?</script>", "", p.read_text(), flags=re.S)
        assert not re.search(r"\b(we|our|us|I)\b", re.sub(r"<[^>]+>", " ", text)), p


# --- Page script helper --------------------------------------------------------------------------------

def _js(code):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on this machine")
    src = json.dumps(_toolchains_js() + (ROOT / "site/static/query.js").read_text()
                     + (ROOT / "site/static/issues.js").read_text()
                     + code)
    r = subprocess.run([node, "-e", f"require('vm').runInThisContext({src})"], capture_output=True, text=True,
                       timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout.splitlines()


def test_list_matches_the_family_view():
    # A mixed finding with no failing version is listed; a defect is
    # listed under every family its reproducers fail on, with that family's status
    out = _js("""
S = fromQuery('?fam=cce&st=open,mixed,not-reproduced');
const base = {kind: 'incorrect', kinds: ['incorrect'], lang: 'f90', model: 'omp', title: 't', constructs: [],
  regression: false};
const mixed = Object.assign({id: 'm', defect: 'm', fams: {cce: {versions: [], targets: [], status: 'mixed',
  status_version: null}}}, base);
const afarOnly = Object.assign({id: 'a', defect: 'a', fams: {afar: {versions: ['afar'], targets: ['mi300a-u'],
  status: 'open', status_version: null}}}, base);
const fixedCce = Object.assign({id: 'f', defect: 'f', fams: {cce: {versions: ['cce19'], targets: ['mi300a-u'],
  status: 'fixed', status_version: '20.0.2'}, nvhpc: {versions: ['nvhpc'], targets: ['a100-s'], status: 'open',
  status_version: null}}}, base);
console.log(JSON.stringify([matches(mixed), matches(afarOnly), matches(fixedCce)]));
S = fromQuery('?fam=nvhpc');
console.log(JSON.stringify([matches(fixedCce), statusText(fixedCce, 'nvhpc')]));
S = fromQuery('?fam=cce,afar');
console.log(JSON.stringify([matches(afarOnly), shownFams(afarOnly), shownFams(mixed)]));
S = fromQuery('?fam=cce,afar&vers=21.0.3');
console.log(JSON.stringify([matches(afarOnly)]));
S = fromQuery('');
console.log(JSON.stringify([matches(afarOnly), shownFams(fixedCce)]));
""")
    assert json.loads(out[0]) == [True, False, False]
    assert json.loads(out[1]) == [True, "Open"]
    # an issue shows when it matches on any selected family, with a strip for each such family
    assert json.loads(out[2]) == [True, ["afar"], ["cce"]]
    assert json.loads(out[3]) == [False]          # a version filter of another family excludes it
    assert json.loads(out[4]) == [True, ["nvhpc"]]   # all families: fixed on CCE, open on NVHPC


@pytest.fixture
def site2(tmp_path):
    bare = finding("bare", status=("not-run", None), cells=[cell("cce21", "21.0.3", "mi300a-u", "unknown")])
    p = finding("p")
    q = finding("q", SiteHeader(same_as="p"))
    ice = finding("w", outcome="ice", cells=[
        D.Cell("afar", "AFAR 24.3.0", "mi300a-u", "fails-like", "COMPILE_FAIL", "error: crash in MapInfoOp", envs=4),
        D.Cell("nvhpc", "25.11", "a100-s", "fails-differently", "COMPILE_FAIL", "NVFORTRAN-S-0034-Syntax error", envs=4)])
    ctl = finding("c", SiteHeader(controls=(("../vendor/checks/src/other/ctl.f90", "map it explicitly"),)))
    ctl["control_cells"] = [cell("cce21", "21.0.3", "mi300a-u", "correct")]
    ctl["control_sources"] = {"../vendor/checks/src/other/ctl.f90": "program ctl\nend program ctl\n"}
    recs = D.records([bare, p, q, ice, ctl])
    D.write(tmp_path, recs)
    (tmp_path / "data/compilers").mkdir()
    for tc, page in D.compilers(recs).items():
        (tmp_path / "data/compilers" / f"{tc}.json").write_text(json.dumps(page))
    SB.render(tmp_path)
    return tmp_path


def test_bare_finding_page_has_grid_and_says_not_yet_run(site2):
    t = (site2 / "issues/bare.html").read_text()
    assert "Not yet run" in t and "Not reproduced" not in t and "Affected variants" in t and ">unknown<" in t


def test_member_page_links_to_its_issue(site2):
    t = (site2 / "issues/q.html").read_text()
    assert "Same issue as" in t and 'href="p.html"' in t


def test_issue_page_shows_each_failure_message(site2):
    t = (site2 / "issues/w.html").read_text()
    assert "crash in MapInfoOp" in t and "NVFORTRAN-S-0034-Syntax error" in t


def test_control_names_compiler_and_shows_source(site2):
    t = (site2 / "issues/c.html").read_text()
    assert "CCE 21.0.3: correct" in t and "program ctl" in t


# --- Sort order and search -----------------------------------------------------------------------------

def test_fixed_sort_puts_wrong_answers_first():
    out = _js("""
S = fromQuery('?fam=cce');
const v = {versions: ['cce21'], targets: ['mi300a-u'], status: 'open', status_version: null};
const mk = (id, phase, reg) => ({id, defect: id, kind: 'incorrect', kinds: ['incorrect'], phase, lang: 'f90',
  model: 'omp', title: id, constructs: [], regression: reg, fams: {cce: v}});
console.log(JSON.stringify(sorted([mk('ice-reg', 'compile', true), mk('wrong', 'offload', false)]).map((i) => i.id)));
""")
    assert json.loads(out[0]) == ["wrong", "ice-reg"]


def test_search_covers_messages_and_ranks_title_then_constructs():
    out = _js("""
S = fromQuery('?fam=cce&q=mapinfo');
const v = {versions: ['cce21'], targets: ['mi300a-u'], status: 'open', status_version: null};
const mk = (id, title, cons, search) => ({id, defect: id, kind: 'incorrect', kinds: ['incorrect'], phase: 'offload',
  lang: 'f90', model: 'omp', title, constructs: cons, regression: false, fams: {cce: v}, search});
const rows = [mk('z-mapinfo', 'c', ['x'], ''), mk('m', 'b', ['x'], 'crash in MapInfoOp'),
              mk('c', 'a', ['mapinfo'], ''), mk('t', 'MapInfo title', ['x'], '')];
console.log(JSON.stringify(rows.filter(matches).length));
console.log(JSON.stringify(sorted(rows.filter(matches)).map((i) => i.id)));
""")
    assert json.loads(out[0]) == 4
    assert json.loads(out[1])[:2] == ["t", "c"]


def test_version_strip_marks_undecided_versions_unknown():
    out = _js("""
const w = {versions: ['cce21'], states: {cce19: 'unknown', cce20: 'correct', cce21: 'fails-like',
  cce21_4: 'fails-differently'}};
console.log(JSON.stringify(['cce19', 'cce20', 'cce21', 'cce21_4'].map((t) => stripClass(w, t))));
console.log(JSON.stringify(stripClass({versions: []}, 'cce19')));
""")
    assert json.loads(out[0]) == ["s-unknown", "s-correct", "s-fails-like", "s-fails-differently"]
    assert json.loads(out[1]) == "s-unknown"


def test_canuse_unknown_construct_has_a_message():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on this machine")
    js = _toolchains_js() + (ROOT / "site/static/canuse.js").read_text() + """
console.log(JSON.stringify([cuMissing('clause.nosuch', ['clause.defaultmap']), cuMissing('clause.defaultmap',
  ['clause.defaultmap']), cuMissing('', ['clause.defaultmap'])]));
"""
    r = subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    miss, hit, empty = json.loads(r.stdout.splitlines()[-1])
    assert "clause.nosuch" in miss and hit is None and empty is None


def test_compiler_page_links_to_its_version_and_uses_kind_names(site):
    import urllib.parse
    def query(page):
        href = re.search(r'href="\.\./index\.html\?([^"]+)">See them', (site / page).read_text()).group(1)
        return urllib.parse.parse_qs(href.replace("&amp;", "&"))
    q = query("compilers/cce21.html")
    assert q["fam"] == ["cce"] and q["vers"] == ["21.0.3"] and "fixed" in q["st"][0].split(",")
    assert query("compilers/afar.html")["vers"] == ["AFAR 24.3.0"]
    assert "Appears to behave incorrectly" in (site / "issues/cce21-a.html").read_text()
    assert "Appears not to support" in (site / "issues/plain.html").read_text()


def test_gcc_is_a_family_in_the_list():
    # GCC's own issues are reachable from the main list; its two builds are its "versions"
    out = _js("""
S = fromQuery('?fam=gcc&vers=16.2 AMD');
const base = {kind: 'incorrect', kinds: ['incorrect'], lang: 'f90', model: 'omp', title: 't', constructs: [],
  regression: false};
const g = Object.assign({id: 'g', defect: 'g', fams: {gcc: {versions: ['gcc'], targets: ['mi250x'],
  status: 'open', status_version: null}}}, base);
const n = Object.assign({id: 'n', defect: 'n', fams: {gcc: {versions: ['gcc_sm80'], targets: ['a100-s'],
  status: 'open', status_version: null}}}, base);
console.log(JSON.stringify([S.fams, S.vers, matches(g), matches(n), FAMILIES_LIST.includes('gcc')]));
console.log(JSON.stringify([toggledFams(['gcc'], 'gcc'), toggledFams(['gcc'], 'cce'), toggledFams(['gcc', 'cce'], 'gcc')]));
""")
    assert json.loads(out[0]) == [["gcc"], ["16.2 AMD"], True, False, True]
    # the compiler buttons toggle, and the last selected family stays selected
    assert json.loads(out[1]) == [["gcc"], ["cce", "gcc"], ["cce"]]


def test_the_home_page_is_the_issue_list_and_issues_html_forwards_to_it(site):
    home = (site / "index.html").read_text()
    assert 'id="list"' in home and 'static/issues.js' in home and 'class="hero"' not in home
    fwd = (site / "issues.html").read_text()
    assert "location.replace('index.html' + location.search" in fwd and 'href="index.html"' in fwd
    for p in site.rglob("*.html"):
        if p.name != "issues.html":
            assert not re.search(r'href="(?:\.\./)?issues\.html', p.read_text()), p


def test_method_page_carries_the_specification_notices(site):
    """The site quotes the OpenMP and OpenACC specifications; their copyright and permission
    notices appear verbatim under "Sources and credits" (the text is the front matter
    of the specifications themselves)."""
    m = (site / "method.html").read_text()
    assert "Sources and credits" in m
    for part in ("Copyright © 1997-2021 OpenMP Architecture Review Board.",
                 "Permission to copy without fee all or part of this material is granted, provided the OpenMP "
                 "Architecture Review Board copyright notice and the title of this document appear. Notice is "
                 "given that copying is by permission of the OpenMP Architecture Review Board.",
                 "OpenMP Application Programming Interface, Version 5.2 November 2021",
                 "Version 6.0 November 2024",
                 "The OpenACC® Application Programming Interface, Version 3.4",
                 "© 2011-2025 OpenACC-Standard.org. All rights reserved."):
        assert part in m, part


def test_method_page_names_the_behaviour_no_tested_compiler_implements():
    """The three constructs every compiler fails (and the host) are explained on the Method
    page, not listed as compiler issues; the copy has no first person."""
    m = SB.METHOD
    assert "Behaviour no tested compiler implements" in m
    for part in ("type-bound defined assignment", "firstprivate", "lastprivate", "finaliz"):
        assert part in m, part
    sec = m[m.index("Behaviour no tested compiler implements"):]
    sec = sec[:sec.index("</section>")]
    assert not re.search(r"\b(I|we|our|my|us)\b", re.sub(r"<[^>]+>", " ", sec), re.I)


def _spec_site(tmp_path):
    cite = {"text": "5.2 §5.8.3 p.152 l.29-31", "version": "OpenMP 5.2", "section": "5.8.3", "quote": "single mappable storage block"}
    fs = [dict(finding("cce21-a"), citations=[cite]), finding("fuzz/b", SiteHeader(same_as="cce21-a")),
          finding("plain", outcome="rejected")]
    recs = D.records(fs)
    D.write(tmp_path, recs)
    (tmp_path / "data/compilers").mkdir()
    for tc, page in D.compilers(recs).items():
        (tmp_path / "data/compilers" / f"{tc}.json").write_text(json.dumps(page))
    (tmp_path / "data/canuse").mkdir()
    (tmp_path / "data/canuse/index.json").write_text("[]")
    SB.render(tmp_path)
    return tmp_path


def test_issue_page_has_a_what_the_specification_requires_section(tmp_path):
    s = _spec_site(tmp_path)
    page = (s / "issues/cce21-a.html").read_text()
    assert "What the specification requires" in page
    assert "OpenMP 5.2" in page and "5.8.3" in page and "single mappable storage block" in page


def test_member_page_says_the_requirement_is_its_defects(tmp_path):
    s = _spec_site(tmp_path)
    page = (s / "issues/fuzz--b.html").read_text()
    assert "What the specification requires" in page and "5.8.3" in page
    assert 'href="cce21-a.html"' in page   # the requirement is that of the defect page


def test_issue_without_a_citation_says_none_is_attached_yet(tmp_path):
    s = _spec_site(tmp_path)
    page = (s / "issues/plain.html").read_text()
    assert "What the specification requires" not in page


def test_home_page_script_shows_and_searches_the_specification_sections():
    js = (ROOT / "site/static/issues.js").read_text()
    assert "i.specs" in js and "'specs'" in js     # a row line, the search and the CSV column


def test_variants_table_orders_two_gcc_installs_the_same_under_every_hash_seed():
    """gcc and gcc_sm80 are one release ("GCC 16.2.0"), so their rows tied in
    the table's sort and took the set's hash order; the sort now ends with the catalog
    position. Rendered in two interpreters with different PYTHONHASHSEEDs the table is
    identical, with gcc (the catalog's first) first."""
    code = """
import sys
sys.path.insert(0, %r)
import site_build as SB
cells = [{"tc": t, "version": v, "target": tg, "state": "fails-like", "outcome": "RUN_OK",
          "message": "", "output": "", "envs": 2, "reason": ""}
         for t, v, tg in (("gcc_sm80", "GCC 16.2.0", "a100-s"), ("gcc", "GCC 16.2.0", "mi250x"),
                          ("cce21", "CCE 21.0.3", "mi300a-u"))]
print(SB.variants_table(cells, "incorrect"))
""" % str(ROOT / "tools" / "site")
    outs = []
    for seed in ("11", "12345"):
        r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True,
                           env={**os.environ, "PYTHONHASHSEED": seed}, cwd=ROOT, timeout=120)
        assert r.returncode == 0, r.stderr
        outs.append(r.stdout)
    assert outs[0] == outs[1]
    rows = re.findall(r'<tr><th scope="row">([^<]*)</th>(.*?)</tr>', outs[0])
    # the two installs of one release cover different GPUs: one row, each cell from the install
    # that ran there
    assert [r[0] for r in rows] == ["CCE 21.0.3", "GCC 16.2.0"]
    tds = re.findall(r"<td>(.*?)</td>", rows[1][1])
    import sys as _s
    _s.path.insert(0, str(ROOT / "tools" / "site"))
    import site_build as SB
    col = {t: n for n, t in enumerate(SB.TARGETS.values())}
    assert "behaves incorrectly" in tds[col["mi250x"]] and "behaves incorrectly" in tds[col["a100-s"]], tds
    assert "n/a" in tds[col["mi300x"]], tds


def test_variants_table_keeps_installs_apart_where_they_share_a_gpu():
    import sys as _s
    _s.path.insert(0, str(ROOT / "tools" / "site"))
    import site_build as SB
    cell = lambda t, tg, st: {"tc": t, "version": "GCC 16.2.0", "target": tg, "state": st, "outcome": "RUN_OK",
                              "message": "", "output": "", "envs": 4, "reason": ""}
    html = SB.variants_table([cell("gcc", "mi250x", "fails-like"), cell("gcc_sm80", "mi250x", "correct"),
                              cell("gcc_sm80", "a100-s", "correct")], "incorrect")
    names = re.findall(r'<tr><th scope="row">([^<]*)</th>', html)
    assert names == ["GCC 16.2.0 (MI250X)", "GCC 16.2.0 (MI250X, A100)"]


# ---- The site's data: what is published, how issues group, titles, counts --------------------------------



from offload.engine.site.matrix import Cell


def cell(tc, version, target, state, output=""):
    return Cell(tc, version, target, state, output=output, envs=4 if state != "unknown" else 0)


def finding(fid, header=SiteHeader(), outcome="wrong_answer", status=("open", None), cells=None,
            constructs=("clause:defaultmap",), lang="f90"):
    cells = cells if cells is not None else [
        cell("cce20", "20.0.2", "mi300a-u", "correct", "ok=1"),
        cell("cce21", "21.0.3", "mi300a-u", "fails-like", "ok=0"),
        cell("afar", "AFAR 24.3.0", "mi300a-u", "correct", "ok=1")]
    return {"id": fid, "file": fid + "." + lang, "lang": lang, "model": "omp", "outcome": outcome,
            "constructs": list(constructs), "expected": "ok=1", "header": header, "cells": cells,
            "controls": [], "status": status, "case": None, "source": "program p\nend program p\n"}


def test_hidden_and_unpublished_dispositions_absent_everywhere(tmp_path):
    fs = [finding("a"), finding("h", SiteHeader(hide=True)),
          finding("n", SiteHeader(disposition=("not-a-compiler-issue", "host libatomic"))),
          finding("o", SiteHeader(disposition=("out-of-scope", "runs on the host")))]
    D.write(tmp_path, D.records(fs))
    blob = "".join(p.read_text() for p in tmp_path.rglob("*.json"))
    for gone in ('"h"', '"n"', '"o"', "host libatomic", "runs on the host"):
        assert gone not in blob
    assert json.loads((tmp_path / "data/issues.json").read_text())["counts"]["defects"] == 1


def test_mixed_shown_with_reason():
    r = D.records([finding("m", SiteHeader(disposition=("mixed", "legality disputed")),
                           status=("mixed", None))])
    (i,) = r["issues"]
    assert i["status"] == "mixed" and i["mixed_reason"] == "legality disputed"


def test_generated_title_when_no_header_title():
    (i,) = D.records([finding("t")])["issues"]
    assert i["title"] == "Appears to behave incorrectly: defaultmap (CCE 21.0.3)"
    (j,) = D.records([finding("r", outcome="rejected")])["issues"]
    assert j["title"].startswith("Appears not to support: defaultmap")
    (k,) = D.records([finding("k", SiteHeader(title="Hand title"))])["issues"]
    assert k["title"] == "Hand title"


def test_same_as_groups_into_one_defect_with_reproducer_count():
    r = D.records([finding("p"), finding("q", SiteHeader(same_as="p")), finding("z")])
    by = {i["id"]: i for i in r["issues"]}
    assert by["q"]["defect"] == "p" and by["p"]["defect"] == "p"
    assert by["p"]["reproducers"] == 2 and r["counts"] == {"defects": 2, "findings": 3}


@pytest.mark.parametrize("fs", [
    [finding("p", SiteHeader(same_as="missing"))],
    [finding("p", SiteHeader(same_as="q")), finding("q", SiteHeader(same_as="p"))],
    [finding("p", SiteHeader(same_as="h")), finding("h", SiteHeader(hide=True))],
])
def test_same_as_dangling_or_cycle_errors(fs):
    with pytest.raises(D.SiteDataError, match="same_as"):
        D.records(fs)


def test_regression_flag():
    (i,) = D.records([finding("g")])["issues"]
    assert i["regression"] is True
    old = [cell("cce19", "19.0.0", "mi300a-u", "fails-like"), cell("cce20", "20.0.2", "mi300a-u", "fails-like")]
    (j,) = D.records([finding("h2", cells=old)])["issues"]
    assert j["regression"] is False


def test_witnesses_are_other_families_correct():
    (i,) = D.records([finding("w")])["issues"]
    page = D.records([finding("w")])["pages"]["w"]
    assert page["witnesses"] == ["AFAR 24.3.0"]
    assert i["versions_failing"] == ["cce21"] and i["targets_failing"] == ["mi300a-u"]


def test_no_first_person_in_generated_copy(tmp_path):
    D.write(tmp_path, D.records([finding("a"), finding("b", outcome="rejected")]))
    for p in tmp_path.rglob("*.json"):
        assert not re.search(r"\b(we|our|us|I)\b", p.read_text()), p


def test_no_header_no_matrix_renders_minimal_page_data():
    r = D.records([finding("bare", cells=[])])
    page = r["pages"]["bare"]
    assert page["cells"] == [] and page["workaround"] is None and page["controls"] == []
    assert r["issues"][0]["title"].startswith("Appears to behave incorrectly")


def test_build_fails_on_leak(tmp_path):
    f = finding("leak", cells=[cell("cce21", "21.0.3", "mi300a-u", "fails-like",
                                    "/p/lustre5/jdoe1/x.f90 ok=0")])
    r = D.records([f])
    assert "jdoe" not in json.dumps(r)          # scrubbed
    r["pages"]["leak"]["summary"] = "see /g/g10/jdoe1"   # a leak scrubbing missed
    with pytest.raises(D.SiteDataError, match="leak"):
        D.write(tmp_path, r)


def test_a_repo_url_with_the_owner_handle_is_allowed_by_write_and_nothing_else_is(tmp_path):
    url = "https://github.com/sjdoe/compliant"
    r = D.records([finding("a")], repo_url=url)
    assert "jdoe" in json.dumps(r)                       # the source link names the maintainer
    with pytest.raises(D.SiteDataError, match="leak"):
        D.write(tmp_path / "a", r)                             # no allowance: still refused
    D.write(tmp_path / "b", r, allow=(url,))                   # the configured URL is allowed
    r["pages"]["a"]["summary"] = "see /g/g10/jdoe1"
    with pytest.raises(D.SiteDataError, match="leak"):
        D.write(tmp_path / "c", r, allow=(url,))               # the name elsewhere is not


def test_repo_url_off_by_default():
    page = D.records([finding("a")])["pages"]["a"]
    assert page["source_url"] is None
    page2 = D.records([finding("a")], repo_url="https://github.com/x/compliant")["pages"]["a"]
    assert page2["source_url"] == "https://github.com/x/compliant/blob/master/data/findings/a.f90"
    # the links follow the repository's default branch (the workflow passes it)
    page3 = D.records([finding("a")], repo_url="https://github.com/x/compliant/", branch="main")["pages"]["a"]
    assert page3["source_url"] == "https://github.com/x/compliant/blob/main/data/findings/a.f90"


def test_an_issue_page_links_to_prefilled_reports_in_the_repository():
    """With a repository URL each issue gets three links that open a GitHub issue form naming it:
    dispute its legality, report it fixed, report a mistake in it. Without one, none."""
    assert D.records([finding("a")])["pages"]["a"]["report_urls"] == {}
    urls = D.records([finding("a")], repo_url="https://github.com/x/compliant")["pages"]["a"]["report_urls"]
    assert set(urls) == {"dispute", "fixed", "wrong"}
    from urllib.parse import parse_qs, urlsplit
    for kind, form in (("dispute", "dispute-a-finding.yml"), ("fixed", "fixed-in-a-release.yml"),
                       ("wrong", "wrong-result.yml")):
        u = urlsplit(urls[kind])
        assert u.netloc == "github.com" and u.path == "/x/compliant/issues/new"
        q = parse_qs(u.query)
        assert q["template"] == [form] and q["finding"] == ["a"] and "a" in q["title"][0]


def test_every_issue_form_a_page_links_to_exists_with_a_finding_field():
    import yaml
    from offload.engine.root import ROOT
    for form in D.REPORT_FORMS.values():
        doc = yaml.safe_load((ROOT / ".github" / "ISSUE_TEMPLATE" / form).read_text())
        assert any(b.get("id") == "finding" for b in doc["body"]), form


def test_counts_are_per_defect():
    r = D.records([finding("p"), finding("q", SiteHeader(same_as="p"))])
    assert r["counts"]["defects"] == 1 and r["counts"]["findings"] == 2


def test_sealed_sets_excluded_and_build_runs(built_site_data):
    tmp_path = built_site_data
    rep = json.loads((tmp_path.parent / "site_data.report.json").read_text())
    assert rep["issues"] > 100 and rep["counts"]["defects"] <= rep["counts"]["findings"]
    blob = "".join(p.read_text() for p in tmp_path.rglob("*.json"))
    for sealed in ("data/bench/fresh2", "harvest-holdout", "fresh2-"):
        assert sealed not in blob
    assert (tmp_path / "data/compilers/cce21_4.json").is_file()
    page = json.loads((tmp_path / "data/issues/cce21-defaultmap-aggregate-flag.json").read_text())
    assert any(c["state"] == "fails-like" for c in page["cells"])
    assert all("jdoe" not in c["text"] for c in page["commands"])


# --- Family and defect views ---------------------------------------------------------------------------

def test_family_view_includes_affected_families_without_failures():
    # A mixed finding with no failing version still has a place in its family's list
    f = finding("m", SiteHeader(disposition=("mixed", "why")), status=("mixed", None),
                cells=[cell("cce21", "21.0.3", "mi300a-u", "unknown")])
    f["toolchains"] = ["cce21"]
    (i,) = D.records([f])["issues"]
    assert i["fams"]["cce"]["status"] == "mixed" and i["fams"]["cce"]["versions"] == []


def test_defect_view_unions_its_members():
    # A reproducer failing on NVHPC puts the defect in NVHPC's list and page
    p = finding("p")
    q = finding("q", SiteHeader(same_as="p"), cells=[cell("nvhpc", "25.11", "a100-s", "fails-like", "ok=0"),
                                                     cell("cce21", "21.0.3", "mi300a-u", "correct", "ok=1")])
    recs = D.records([p, q])
    by = {i["id"]: i for i in recs["issues"]}
    assert by["p"]["fams"]["nvhpc"]["versions"] == ["nvhpc"] and by["p"]["fams"]["cce"]["versions"] == ["cce21"]
    assert "nvhpc" in by["p"]["versions_failing"] and "a100-s" in by["p"]["targets_failing"]
    assert D.compilers(recs)["nvhpc"]["fails"] == ["p"]
    assert recs["pages"]["q"]["defect"] == "p"


def test_compiler_page_uses_the_family_status():
    # Fixed in CCE 20.0.2 though NVHPC still fails
    f = finding("s", status=("open", None), cells=[cell("cce19", "19.0.0", "mi300a-u", "fails-like"),
                                                   cell("cce20", "20.0.2", "mi300a-u", "correct"),
                                                   cell("nvhpc", "25.11", "a100-s", "fails-like")])
    f["status_by_fam"] = {"cce": ("fixed", "20.0.2"), "nvhpc": ("open", None)}
    recs = D.records([f])
    (i,) = recs["issues"]
    assert i["fams"]["cce"]["status"] == "fixed" and i["fams"]["nvhpc"]["status"] == "open"
    assert D.compilers(recs)["cce20"]["fixed_or_changed"] == ["s"]


def test_commands_list_failing_compilers_first_in_their_failing_mode():
    case = {"id": "c", "lang": "f90", "model": "omp", "opt": "-O2"}
    cells = [cell("afar", "AFAR 24.3.0", "mi300a-u", "correct"),
             cell("cce21", "21.0.3", "mi300a-u", "correct"), cell("cce21", "21.0.3", "mi300a-c", "fails-like"),
             cell("nvhpc", "25.11", "a100-s", "correct"), cell("nvhpc", "25.11", "a100-m", "fails-like")]
    cmds = D._commands(case, cells)
    assert [c["tc"] for c in cmds] == ["cce21", "nvhpc", "afar"]
    assert "HSA_XNACK=0" in cmds[0]["text"] and cmds[0]["target"] == "mi300a-c"
    assert "mem:managed" in cmds[1]["text"] and cmds[1]["target"] == "a100-m"


def test_messages_shown_per_distinct_failure():
    cells = [Cell("afar", "AFAR 24.3.0", "mi300a-u", "fails-like", "COMPILE_FAIL", "error: crash in MapInfoOp", envs=4),
             Cell("nvhpc", "25.11", "a100-s", "fails-differently", "COMPILE_FAIL",
                  "NVFORTRAN-S-0034-Syntax error at or near +", envs=4)]
    p = D.records([finding("w", outcome="ice", cells=cells)])["pages"]["w"]
    assert p["observed"] == "error: crash in MapInfoOp"
    assert {m["state"] for m in p["messages"]} == {"fails-like", "fails-differently"}
    assert any("NVFORTRAN" in m["message"] and m["where"] == ["NVHPC 25.11, A100 separate"] for m in p["messages"])


def test_controls_name_their_compiler_and_carry_source():
    f = finding("c", SiteHeader(controls=(("../vendor/checks/src/other/ctl.f90", "map it explicitly"),)))
    f["control_cells"] = [cell("cce21", "21.0.3", "mi300a-u", "correct"),
                          cell("cce21", "21.0.3", "mi300a-c", "unknown"),
                          cell("afar", "AFAR 24.3.0", "mi300a-u", "unknown")]
    f["control_sources"] = {"../vendor/checks/src/other/ctl.f90": "program ctl\nend program ctl\n"}
    (ctl,) = D.records([f])["pages"]["c"]["controls"]
    assert ctl["results"] == [{"label": "CCE 21.0.3", "state": "correct"}]
    assert "program ctl" in ctl["source"]


def test_canuse_words_model_and_issue_links():
    atoms = [{"scope": "device", "atom": "clause.defaultmap", "id": "omp52-clause-defaultmap", "version": "5.2",
              "lang": "f90", "cce21_x1": "ok", "cce21_x0": "suspect", "note_cce21_x0": "wrong value once",
              "afar_x1": "excluded", "note_afar_x1": "outside the 5.2 subset", "nvhpc_x0": "rejected",
              "nvhpc_x2": "wrong"}]
    recs = D.records([finding("t")])
    (cu,) = D.canuse(atoms, recs)["clause.defaultmap"]
    assert cu["cells"]["cce21|mi300a-u"]["state"] == "correct"
    assert cu["cells"]["cce21|mi300a-c"] == {"state": "unknown", "reason": "wrong value once"}
    assert cu["cells"]["afar|mi300a-u"]["state"] == "unsupported"
    assert cu["cells"]["nvhpc|a100-s"]["state"] == "unsupported"
    assert cu["cells"]["nvhpc|a100-m"]["state"] == "incorrect"
    assert cu["model"] == "omp" and cu["issues"] == [{"page": "t", "title": recs["issues"][0]["title"]}]


# --- Version states and search text --------------------------------------------------------------------

def test_family_view_has_a_state_per_version():
    # the list's version strip: undecided versions are unknown, not correct
    (i,) = D.records([finding("s")])["issues"]
    assert i["fams"]["cce"]["states"] == {"cce19": "unknown", "cce20": "correct", "cce21": "fails-like",
                                          "cce21_4": "unknown"}
    p, q = finding("p", cells=[cell("cce21", "21.0.3", "mi300a-u", "correct")]), \
        finding("q", SiteHeader(same_as="p"), cells=[cell("cce21", "21.0.3", "mi300a-u", "fails-like")])
    p["toolchains"] = ["cce21"]
    by = {x["id"]: x for x in D.records([p, q])["issues"]}
    assert by["p"]["fams"]["cce"]["states"]["cce21"] == "fails-like"   # the defect: most failing state


def test_search_text_holds_compiler_messages():
    cells = [D.Cell("afar", "AFAR 24.3.0", "mi300a-u", "fails-like", "COMPILE_FAIL",
                    "error: crash in MapInfoOp\nStack dump:", envs=4)]
    (i,) = D.records([finding("w", outcome="ice", cells=cells)])["issues"]
    assert "crash in MapInfoOp" in i["search"] and "Stack dump" not in i["search"]


def test_driver_prefix_dropped_when_more_than_one_family_fails():
    two = [cell("cce21", "21.0.3", "mi300a-u", "fails-like"), cell("nvhpc", "25.11", "a100-s", "fails-like")]
    (i,) = D.records([finding("d", SiteHeader(title="ftn: lastprivate loses the value"), cells=two)])["issues"]
    assert i["title"] == "Lastprivate loses the value"
    (j,) = D.records([finding("e", SiteHeader(title="craycc/ftn -fopenmp: map(present) aborts"),
                              cells=two)])["issues"]
    assert j["title"] == "Map(present) aborts"
    (k,) = D.records([finding("k", SiteHeader(title="ftn: lastprivate loses the value"))])["issues"]
    assert k["title"] == "ftn: lastprivate loses the value"     # CCE only: the driver names it
    (m,) = D.records([finding("m", SiteHeader(title="AFAR offload runtime at HSA_XNACK=1: x"),
                              cells=two)])["issues"]
    assert m["title"] == "AFAR offload runtime at HSA_XNACK=1: x"   # not a driver name


def test_messages_and_commands_are_scrubbed_through_records_and_write(tmp_path):
    from offload.engine.site import scrub as S
    cells = [D.Cell("cce21", "21.0.3", "mi300a-u", "fails-like", "COMPILE_FAIL",
                    "/p/lustre5/jdoe1/x/repro.f90:3: error: bad\nat /tmp/jdoe_site/harness_1a2b3c4d/x.f90 "
                    "on tuolumne1044", envs=4)]
    f = finding("leaky", outcome="ice", cells=cells)
    f["commands"] = [{"tc": "cce21", "target": "mi300a-u", "label": "CCE 21.0.3, MI300A unified", "role": "fails",
                      "text": "cd /g/g10/jdoe1/w && ftn -fopenmp /tmp/jdoe_site/a/repro.f90"}]
    r = D.records([f])
    D.write(tmp_path, r)
    for p in tmp_path.rglob("*.json"):
        assert S.leaks(p.read_text()) == [], p
    page = json.loads((tmp_path / "data/issues/leaky.json").read_text())
    assert "ftn -fopenmp" in page["commands"][0]["text"] and "error: bad" in page["messages"][0]["message"]
    r["pages"]["leaky"]["commands"][0]["text"] += " /tmp/jdoe_site/b"   # a leak scrubbing missed
    with pytest.raises(D.SiteDataError, match="leak"):
        D.write(tmp_path, r)


def test_compiler_page_lists_in_the_fixed_order():
    # wrong answers first, then regressions, then reach
    no_reg = [cell("cce20", "20.0.2", "mi300a-u", "fails-like"), cell("cce21", "21.0.3", "mi300a-u", "fails-like")]
    wide = [cell("cce21", "21.0.3", "mi300a-u", "fails-like"), cell("cce21", "21.0.3", "mi300a-c", "fails-like")]
    fs = [finding("r1", outcome="rejected", cells=wide), finding("i1", outcome="ice"),
          finding("w2", cells=no_reg), finding("w1")]
    c = D.compilers(D.records(fs))["cce21"]
    assert c["fails"] == ["w1", "w2", "i1", "r1"]
    assert c["regressions"] == ["w1", "i1"]


def test_compiler_lists_are_per_defect():
    p = finding("p", cells=[cell("cce20", "20.0.2", "mi300a-u", "fails-like"),
                            cell("cce21", "21.0.3", "mi300a-u", "fails-like")])
    q = finding("q", SiteHeader(same_as="p"))      # regresses on CCE 21.0.3
    c = D.compilers(D.records([p, q]))["cce21"]
    assert c["fails"] == ["p"] and c["regressions"] == ["p"]


def test_gcc_commands_and_pages():
    case = {"id": "c", "lang": "c", "model": "omp", "opt": "-O2"}
    cells = [cell("gcc_sm80", "16.2.0", "a100-s", "fails-like"),
             cell("gcc", "16.2.0", "mi250x", "fails-like")]
    cmds = {c["tc"]: c["text"] for c in D._commands(case, cells)}
    a100, mi = cmds["gcc_sm80"], cmds["gcc"]
    assert "$GCC_16_2/bin/gcc -fopenmp -foffload=nvptx-none" in a100 and "-latomic" in a100
    assert "export LD_LIBRARY_PATH=$GCC_16_2/lib64" in a100 and "HSA_XNACK" not in a100
    assert "HSA_XNACK=0 OMP_TARGET_OFFLOAD=mandatory ./repro" in mi
    assert "amdgcn-amdhsa=-march=gfx90a" in mi and "/rocm-7.2.1/lib" in mi
    assert not any(p in a100 + mi for p in ("/fastscratch", "/p/vast1", "sjdoe", "jdoe1"))
    pages = D.compilers(D.records([finding("g", cells=cells)]))
    assert pages["gcc"]["label"] == "GCC 16.2.0 AMD"
    assert pages["gcc_sm80"]["label"] == "GCC 16.2.0 A100"
    assert pages["gcc_sm80"]["fails"] == ["g"]


CITE_MAP = {"text": "5.2 §5.8.3 p.152 l.29-31", "version": "OpenMP 5.2", "section": "5.8.3",
            "quote": "All map clause list items that have the same containing structure"}
CITE_TEAMS = {"text": "5.2 §10.2 p.230", "version": "OpenMP 5.2", "section": "10.2", "quote": "A teams construct creates"}


def test_issue_lists_the_specification_sections_it_cites():
    """The home page shows which specification text an issue rests on (version and section)."""
    f = dict(finding("a"), citations=[CITE_MAP, CITE_TEAMS, dict(CITE_MAP, quote="again")])
    rec = D.records([f])
    issue = rec["issues"][0]
    assert issue["specs"] == ["OpenMP 5.2 §5.8.3", "OpenMP 5.2 §10.2"]   # distinct, in order
    assert rec["pages"]["a"]["citations"][0]["section"] == "5.8.3"


def test_a_member_without_its_own_citation_shows_its_defects():
    root = dict(finding("a"), citations=[CITE_MAP])
    member = finding("fuzz/b", SiteHeader(same_as="a"))
    rec = D.records([root, member])
    by = {i["id"]: i for i in rec["issues"]}
    assert by["fuzz/b"]["specs"] == ["OpenMP 5.2 §5.8.3"]
    page = rec["pages"]["fuzz/b"]
    assert page["citations"] == [CITE_MAP] and page["citations_from"] == "a"
    assert rec["pages"]["a"].get("citations_from") in (None, "")


def test_a_defect_without_a_citation_of_its_own_takes_its_members():
    root = finding("a")
    member = dict(finding("fuzz/b", SiteHeader(same_as="a")), citations=[CITE_TEAMS])
    by = {i["id"]: i for i in D.records([root, member])["issues"]}
    assert by["a"]["specs"] == ["OpenMP 5.2 §10.2"]


def test_an_issue_with_no_citation_has_an_empty_spec_list():
    assert D.records([finding("a")])["issues"][0]["specs"] == []


# ---- The finding matrix: every finding's program on every toolchain and mode -----------------------------

from offload.engine.site import matrix as M

CASE = {"id": "x", "finding": "x.f90", "symptom": "wrong", "expect": "out:ok=1", "lang": "f90",
        "model": "omp", "affected": ["cce19"]}
ICE = {"id": "y", "finding": "catalog/y.f90", "symptom": "compile:internal compiler error",
       "expect": "ok", "lang": "f90", "model": "omp", "affected": ["cce19"]}
ACC = {"id": "z", "finding": "z.f90", "symptom": "wrong", "expect": "out:ok=1", "lang": "f90",
       "model": "acc", "affected": ["cce19"]}


def row(case, tc, machine, mode, env, obs, variant="repro"):
    return {"case": case, "tc": tc, "machine": machine, "mode": mode, "env": env,
            "obs": obs, "variant": variant}


def four(case, tc, machine, mode, obs, variant="repro"):
    return [row(case, tc, machine, mode, e, obs, variant) for e in "abcd"]


WRONG = "RUN_OK rc=0\nok=0"
RIGHT = "RUN_OK rc=0\nok=1"
ICE_OBS = "COMPILE_FAIL rc=1\nftn: internal compiler error"
LINK = "COMPILE_FAIL rc=1\nld.lld: error: undefined symbol: foo"
NA = "NOT_APPLICABLE"


def _cell(cells, tc, target):
    return next(c for c in cells if c.tc == tc and c.target == target)


def test_fails_like_needs_same_class_and_signature():
    rows = four("x", "cce19", "tuolumne", "1", WRONG)
    c = _cell(M.cells("x", rows=rows, cases=[CASE]), "cce19", "mi300a-u")
    assert c.state == "fails-like" and c.envs == 4 and c.version == "19.0.0"


def test_other_failure_is_fails_differently():
    rows = four("y", "cce19", "tuolumne", "1", ICE_OBS) + four("y", "cce20", "tuolumne", "1", LINK)
    cs = M.cells("catalog/y", rows=rows, cases=[ICE])
    assert _cell(cs, "cce19", "mi300a-u").state == "fails-like"
    assert _cell(cs, "cce20", "mi300a-u").state == "fails-differently"


def test_fixed_requires_correct_on_every_later_version():
    rows = (four("x", "cce19", "tuolumne", "1", WRONG) + four("x", "cce20", "tuolumne", "1", RIGHT)
            + four("x", "cce21", "tuolumne", "1", RIGHT) + four("x", "cce21_4", "tuolumne", "1", RIGHT))
    assert M.status("x", rows=rows, cases=[CASE]) == ("fixed", "20.0.2")
    rows2 = rows[:-4] + four("x", "cce21_4", "tuolumne", "1", WRONG)
    assert M.status("x", rows=rows2, cases=[CASE])[0] == "open"


def test_changed_when_later_fails_differently():
    rows = (four("y", "cce19", "tuolumne", "1", ICE_OBS) + four("y", "cce20", "tuolumne", "1", LINK)
            + four("y", "cce21", "tuolumne", "1", LINK))
    assert M.status("catalog/y", rows=rows, cases=[ICE]) == ("changed", "20.0.2")


def test_unknown_when_not_run_or_gate_undecided():
    cs = M.cells("x", rows=[], cases=[CASE])
    c = _cell(cs, "cce19", "mi300a-u")
    assert c.state == "unknown" and c.reason == "not run"
    vary = [row("x", "cce19", "tuolumne", "1", "a", WRONG), row("x", "cce19", "tuolumne", "1", "b", RIGHT),
            row("x", "cce19", "tuolumne", "1", "c", WRONG), row("x", "cce19", "tuolumne", "1", "d", RIGHT)]
    c = _cell(M.cells("x", rows=vary, cases=[CASE]), "cce19", "mi300a-u")
    assert c.state == "unknown" and "varies" in c.reason


def test_na_for_openacc_on_afar():
    cs = M.cells("z", rows=four("z", "afar", "tuolumne", "1", NA), cases=[ACC])
    assert _cell(cs, "afar", "mi300a-u").state == "na"
    # with no rows at all, OpenACC on AFAR is still n/a, not unknown
    assert _cell(M.cells("z", rows=[], cases=[ACC]), "afar", "mi300a-c").state == "na"


def test_envs_counts_agreeing_environments():
    rows = [row("x", "cce19", "tuolumne", "1", e, WRONG) for e in "abd"]
    c = _cell(M.cells("x", rows=rows, cases=[CASE]), "cce19", "mi300a-u")
    assert c.state == "fails-like" and c.envs == 3


def test_mixed_status_from_header():
    rows = four("x", "cce19", "tuolumne", "1", WRONG)
    h = SiteHeader(disposition=("mixed", "legality disputed"))
    assert M.status("x", rows=rows, cases=[CASE], header=h) == ("mixed", None)


def test_not_reproduced_when_nothing_fails_like():
    rows = four("x", "cce19", "tuolumne", "1", RIGHT)
    assert M.status("x", rows=rows, cases=[CASE]) == ("not-reproduced", None)


def test_derived_case_from_index_when_no_vendor_case():
    c = M.derive_case({"file": "dataenv/q.f90", "lang": "f90", "outcome": "wrong_answer",
                       "expected": "vout= 101", "toolchains": ["cce21"]})
    assert c["symptom"] == "wrong" and c["expect"] == "out:vout= 101" and c["finding"] == "dataenv/q.f90"
    i = M.derive_case({"file": "a.f90", "lang": "f90", "outcome": "ice", "toolchains": ["cce19"]})
    assert i["symptom"].startswith("compile:") and i["expect"] == "ok"


def test_plan_runs_only_new_cells():
    rows = []
    for tc in M.TOOLCHAINS:
        for (mach, mode) in M.TARGETS:
            rows += four("x", tc, mach, mode, RIGHT)
    assert M.plan(["x"], rows=rows, cases=[CASE]) == []
    todo = M.plan(["x"], rows=rows[4:], cases=[CASE])
    assert len(todo) == 1 and todo[0]["case"] == "x"


def test_site_cases_cover_uncovered_published_findings():
    from offload.engine.site import header as H
    entries = [{"file": "a.f90", "lang": "f90", "outcome": "wrong_answer", "expected": "x= 1",
                "toolchains": ["cce21"], "arch": ["gfx942", "gfx90a"]},
               {"file": "b.f90", "lang": "f90", "outcome": "ice", "toolchains": ["cce19"]},
               {"file": "hidden.f90", "lang": "f90", "outcome": "ice", "toolchains": ["afar"]},
               {"file": "oos.f90", "lang": "f90", "outcome": "ice", "toolchains": ["afar"]}]
    headers = {"hidden.f90": H.SiteHeader(hide=True),
               "oos.f90": H.SiteHeader(disposition=("out-of-scope", "host only"))}
    out = M.site_cases(entries, existing=[{"id": "b", "finding": "b.f90"}], headers=headers)
    assert [c["finding"] for c in out] == ["a.f90"]
    c = out[0]
    assert c["repro"] == "../../findings/a.f90" and c["arch"] == ["gfx942", "gfx90a", "sm_80"]
    assert c["vendor"] == ["amd", "hpe", "nvidia"]
    assert "control" not in c


def test_site_cases_carry_the_headers_device_visibility():
    from offload.engine.site import header as H
    entries = [{"file": "d/a.c", "lang": "c", "outcome": "crash", "toolchains": ["gcc_g90"]}]
    (plain,) = M.site_cases(entries, existing=[], headers={"d/a.c": H.SiteHeader()})
    assert "devices" not in plain
    (c,) = M.site_cases(entries, existing=[], headers={"d/a.c": H.SiteHeader(devices=("gcc_g90",))})
    assert c["devices"] == {"gcc_g90": "all"}


def test_site_cases_carry_the_headers_control():
    from offload.engine.site import header as H
    entries = [{"file": "d/a.c", "lang": "c", "outcome": "ice", "toolchains": ["gcc_sm80"]}]
    headers = {"d/a.c": H.SiteHeader(controls=(("d/controls/a-control.c", "the list reordered"),
                                                ("d/controls/b.c", "another")))}
    (plain,) = M.site_cases(entries, existing=[], headers=headers)
    assert "control" not in plain   # only the findings asked for get their control run
    (c,) = M.site_cases(entries, existing=[], headers=headers, controls={"d/a.c"})
    assert c["control"] == "../../findings/d/controls/a-control.c"
    assert c["control_what"] == "the list reordered"
    todo = M.plan(["d/a"], rows=[], cases=[c])
    assert {(t["tc"], t["machine"]) for t in todo if t["variant"] == "control"} == {("gcc_sm80", "wingtip")}


def test_pack_scrubs_and_drops_private_fields(tmp_path):
    raw = tmp_path / "site-tuolumne.a.jsonl"
    raw.write_text('{"case": "x", "obs": "COMPILE_FAIL rc=1\\n/p/lustre5/jdoe1/t/x.f90: error", '
                   '"host": "tuolumne1044", "build_dir": "/tmp/jdoe1-t44/h", "tc": "cce21"}\n')
    out = tmp_path / "results-site"
    M.pack([raw], out)
    import gzip
    text = gzip.open(out / "site-tuolumne.a.jsonl.gz", "rt").read()
    assert "jdoe" not in text and "tuolumne1044" not in text and "build_dir" not in text
    assert "COMPILE_FAIL" in text


def test_plan_runs_controls_only_on_affected_toolchains():
    case = dict(CASE, control="src/x-control.f90", affected=["cce21"])
    todo = M.plan(["x"], rows=[], cases=[case])
    ctl = {(t["tc"]) for t in todo if t["variant"] == "control"}
    assert ctl == {"cce21", "cce21_4"}   # "cce21" in affected means CCE 21.x
    # no batch queue on Tioga: only GCC, run in supervised interactive jobs, plans runs there
    assert not any(t["machine"] == "tioga" and t["tc"] != "gcc" for t in todo)


# --- Failures of other families ------------------------------------------------------------------------

AFAR_ICE = {"id": "w", "finding": "catalog/w.f90", "symptom": "compile:.", "expect": "ok", "lang": "f90",
            "model": "omp", "affected": ["afar"]}
WA = {"id": "v", "finding": "v.f90", "symptom": "wrong", "expect": "out:check=pass", "lang": "f90",
      "model": "omp", "affected": ["afar"]}


def test_other_family_failure_never_counts_as_the_issue():
    # AFAR's ICE is the finding; CCE's addrspacecast and link failures and
    # NVHPC's syntax error are other failures, whatever the case's broad symptom says
    rows = (four("w", "afar", "tuolumne", "1", "COMPILE_FAIL rc=1\nerror: Call parameter type does not "
                 "match function signature!\nfatal error: error in backend")
            + four("w", "cce19", "tuolumne", "1", "COMPILE_FAIL rc=1\nerror: invalid addrspacecast")
            + four("w", "cce20", "tuolumne", "1", "COMPILE_FAIL rc=1\nld.lld: error: undefined symbol: "
                   "_cray$mt_taskred_modifier_init")
            + four("w", "nvhpc", "wingtip", "0", "COMPILE_FAIL rc=2\nNVFORTRAN-S-0034-Syntax error at or "
                   "near + (repro.f90: 12)"))
    cs = M.cells("catalog/w", rows=rows, cases=[AFAR_ICE])
    assert _cell(cs, "afar", "mi300a-u").state == "fails-like"
    for tc, t in (("cce19", "mi300a-u"), ("cce20", "mi300a-u"), ("nvhpc", "a100-s")):
        assert _cell(cs, tc, t).state == "fails-differently", tc


def test_wrong_answer_matches_only_the_same_self_check_line():
    rows = (four("v", "afar", "tuolumne", "1", "RUN_OK rc=0\nsum= 12 check=fail")
            + four("v", "nvhpc", "wingtip", "0", "RUN_FAIL rc=1\nFailing in Thread:1\ncall to "
                   "cuStreamSynchronize returned error 700: Illegal address during kernel execution")
            + four("v", "nvhpc269", "wingtip", "0", "RUN_OK rc=0\nsum= 12 check=fail"))
    cs = M.cells("v", rows=rows, cases=[WA])
    assert _cell(cs, "nvhpc", "a100-s").state == "fails-differently"
    assert _cell(cs, "nvhpc269", "a100-s").state == "fails-like"


def test_nvfortrans_per_unit_summary_line_is_not_the_diagnostic():
    # the long check-case file name makes NVFORTRAN warn about truncated identifiers and print
    # its "N inform, N warnings, N severes, N fatal for UNIT" summary before the fatal message;
    # that summary names no diagnostic, so the signature is the F-0155 line (as the campaign row's)
    site = ("COMPILE_FAIL rc=2\nNVFORTRAN-W-0016-Identifier, struct_STATICS1_ab..., truncated to 63 chars (site-fuzz--x.f90: 56)\n"
            "  0 inform,   2 warnings,   0 severes, 0 fatal for p\n"
            "NVFORTRAN-F-0155-Compiler failed to translate OpenMP region  (site-fuzz--x.f90: 47)\n"
            "NVFORTRAN/x86-64 Linux 25.11-0: compilation aborted\n")
    campaign = ("COMPILE_FAIL rc=1\n--- compile (rc=2) ---\nNVFORTRAN-F-0155-Compiler failed to translate OpenMP region  "
                "(<tmpdir>/x.f90: 6)\nNVFORTRAN/x86-64 Linux 25.11-0: compilation aborted\n")
    assert M.signature(site) == M.signature(campaign)
    assert "failed to translate" in M.signature(site)[1]


def test_a_completed_run_whose_own_check_fails_is_not_correct():
    # a derived case without a stated expected output expects "ok": a run that completes
    # counts as correct only when the program's own check passes (RESULT ... check=pass);
    # AFAR's malloc finding prints check=fail with exit status 0
    case = dict(WA, id="m", finding="m.c", affected=["afar"], expect="ok")
    rows = (four("m", "afar", "tuolumne", "1", "RUN_OK rc=0\ntrial 1: bad 4220\nRESULT ran_on_host=0 check=fail")
            + four("m", "afar", "tuolumne", "0", "RUN_OK rc=0\ntrial 1: bad 0\nRESULT ran_on_host=0 check=pass")
            + four("m", "cce21", "tuolumne", "1", "RUN_OK rc=0\ntrial 1: bad 0\nRESULT ran_on_host=0 check=pass"))
    cs = M.cells("m", rows=rows, cases=[case])
    assert _cell(cs, "afar", "mi300a-u").state == "fails-like"
    assert _cell(cs, "afar", "mi300a-c").state == "correct"
    assert _cell(cs, "cce21", "mi300a-u").state == "correct"
    assert M.status("m", rows=rows, cases=[case]) == ("open", None)


def test_a_different_wrong_value_is_a_different_failure():
    # GCC: CCE's wrap prints s= 626787243; another compiler's s= 8721849489850283
    # is a wrong answer too, but not this one
    case = dict(WA, id="t", finding="t.f90", affected=["cce19"], expect="out:check=pass")
    rows = (four("t", "cce19", "tuolumne", "0", "RUN_OK rc=0\ns= 626787243 check=fail")
            + four("t", "cce20", "tuolumne", "0", "RUN_OK rc=0\ns= 626787243 check=fail")
            + four("t", "afar", "tuolumne", "0", "RUN_OK rc=0\ns= 8721849489850283 check=fail"))
    cs = M.cells("t", rows=rows, cases=[case])
    assert _cell(cs, "cce20", "mi300a-c").state == "fails-like"
    assert _cell(cs, "afar", "mi300a-c").state == "fails-differently"


def test_same_diagnostic_on_an_unaffected_version_is_fails_like():
    ice = "COMPILE_FAIL rc=1\nftn-7991 ftn: INTERNAL REPRO, File = repro.f90, Line = {}\nftn: internal compiler error"
    rows = (four("y", "cce19", "tuolumne", "1", ice.format(12))
            + four("y", "cce20", "tuolumne", "1", ice.format(40)))
    assert _cell(M.cells("catalog/y", rows=rows, cases=[ICE]), "cce20", "mi300a-u").state == "fails-like"


def test_unaffected_failure_is_unknown_when_the_affected_compiler_was_not_run():
    rows = four("y", "cce20", "tuolumne", "1", ICE_OBS)
    c = _cell(M.cells("catalog/y", rows=rows, cases=[ICE]), "cce20", "mi300a-u")
    assert c.state == "unknown" and "compare" in c.reason


def test_not_run_when_no_affected_cell_is_decided():
    # Nothing ran where the finding was observed -> not "not reproduced"
    assert M.status("x", rows=[], cases=[CASE]) == ("not-run", None)
    assert M.status("x", rows=four("x", "afar", "tuolumne", "1", RIGHT), cases=[CASE]) == ("not-run", None)


def test_finding_without_a_case_gets_an_all_unknown_grid():
    cs = M.cells("new/thing", rows=[], cases=[],
                 entry={"file": "new/thing.f90", "outcome": "wrong_answer", "lang": "f90", "toolchains": ["cce21"]})
    assert cs and {c.state for c in cs} <= {"unknown", "na"} and any(c.state == "unknown" for c in cs)


def test_status_is_per_compiler_family():
    # CCE fixed it in 20.0.2 while NVHPC still fails
    case = dict(CASE, affected=["cce19", "nvhpc"])
    rows = (four("x", "cce19", "tuolumne", "1", WRONG) + four("x", "cce20", "tuolumne", "1", RIGHT)
            + four("x", "nvhpc", "wingtip", "0", WRONG))
    by = M.status_by_family("x", rows=rows, cases=[case])
    assert by["cce"] == ("fixed", "20.0.2") and by["nvhpc"] == ("open", None)
    assert "afar" not in by


def test_fixed_needs_correct_where_it_failed():
    # 21.0.3 fails in copy mode only; 21.0.4 correct in unified mode is not a fix
    case = dict(CASE, affected=["cce21"])
    rows = (four("x", "cce21", "tuolumne", "0", WRONG) + four("x", "cce21", "tuolumne", "1", RIGHT)
            + four("x", "cce21_4", "tuolumne", "1", RIGHT))
    assert M.status("x", rows=rows, cases=[case]) == ("open", None)
    rows += four("x", "cce21_4", "tuolumne", "0", RIGHT)
    assert M.status("x", rows=rows, cases=[case]) == ("fixed", "21.0.4")


def test_pack_scrubs_user_tmp_dirs(tmp_path):
    # Run_site_matrix.sh builds in /tmp/${USER}_site
    import gzip
    import json as J
    raw = tmp_path / "site-x.a.jsonl"
    obs = ("RUN_FAIL rc=1\nFile: /tmp/sjdoe3_site/harness_1a2b3c4d/x/repro.f90\n"
           "at /tmp/jdoe1_site/GATEABCDEFGHIJKLMN/repro.f90:3")
    raw.write_text(J.dumps(row("x", "nvhpc", "wingtip", "0", "a", obs)) + "\n")
    M.pack([raw], tmp_path / "out")
    text = gzip.open(tmp_path / "out" / "site-x.a.jsonl.gz", "rt").read()
    assert "jdoe" not in text and "<dir>" in text


# --- The first version that fails differently ----------------------------------------------------------

def test_changed_names_the_first_version_that_fails_differently():
    # CCE 19 fails like the issue, 20 is correct, 21 fails another way: changed in 21.0.3,
    # not fixed (and not "changed in 20.0.2", the first later version tested)
    rows = (four("y", "cce19", "tuolumne", "1", ICE_OBS) + four("y", "cce20", "tuolumne", "1", RIGHT)
            + four("y", "cce21", "tuolumne", "1", LINK))
    assert M.status_by_family("catalog/y", rows=rows, cases=[ICE])["cce"] == ("changed", "21.0.3")
    # a different failure on a target where the issue never failed changes nothing
    rows2 = (four("y", "cce19", "tuolumne", "1", ICE_OBS) + four("y", "cce20", "tuolumne", "1", RIGHT)
             + four("y", "cce21", "tuolumne", "0", LINK))
    assert M.status_by_family("catalog/y", rows=rows2, cases=[ICE])["cce"] == ("fixed", "20.0.2")


# --- GCC 16.2: a family on the MI250X (copy) and the A100 (separate) only ---------

def test_gcc_is_a_family_on_the_amd_gpus_and_the_a100():
    assert M.VERSIONS["gcc"][0] == M.VERSIONS["gcc_sm80"][0] == "gcc"
    cs = M.cells("x", rows=[], cases=[CASE])
    # the AMD install runs every AMD GPU (the MI300A in both memory modes, measured); the NVIDIA one
    # the A100 in separate memory
    for tc, mine in (("gcc", {"mi300a-u", "mi300a-c", "mi250x", "mi300x", "mi350x"}),
                     ("gcc_sm80", {"a100-s"})):
        for t in M.TARGETS.values():
            c = _cell(cs, tc, t)
            if t in mine:
                assert c.state == "unknown" and c.reason == "not run", (tc, t)
            else:   # no managed-memory cells, no cells on the other vendor's GPUs
                assert c.state == "na", (tc, t)
    # OpenACC runs on GCC (unlike AFAR)
    assert _cell(M.cells("z", rows=[], cases=[ACC]), "gcc_sm80", "a100-s").state == "unknown"
    c = _cell(M.cells("x", rows=four("x", "gcc", "tioga", "0", RIGHT), cases=[CASE]),
              "gcc", "mi250x")
    assert c.state == "correct"


def test_plan_runs_gcc_on_tioga_but_not_the_other_mi250x_cells():
    todo = M.plan(["x"], rows=[], cases=[CASE])
    keys = {(t["tc"], t["machine"], t["mode"]) for t in todo}
    assert ("gcc", "tioga", "0") in keys and ("gcc_sm80", "wingtip", "0") in keys
    assert ("gcc_sm80", "wingtip", "2") not in keys
    assert not any(m == "tioga" and tc != "gcc" for tc, m, _ in keys)


def test_gcc_rows_keep_the_cce_wrap_finding_fixed():
    """GCC on the committed rows: gcc prints another wrong
    value than CCE's wrap, so the CCE finding stays fixed in 21.0.3 and the
    GCC cell fails differently; the shared declare-create value is a match."""
    rows, cases = M._rows(), M._cases()
    fid = "stress/cce-teams-reduction-many-teams-wrap"
    assert M.status(fid, rows, cases) == ("fixed", "21.0.3")
    g = {(c.tc, c.target): c.state for c in M.cells(fid, rows, cases)}
    assert g[("gcc", "mi250x")] == "fails-differently"
    fid = "stress/cce-acc-declare-create-scalar-serial-firstprivate"
    g = {(c.tc, c.target): c.state for c in M.cells(fid, rows, cases)}
    assert g[("gcc", "mi250x")] == g[("gcc_sm80", "a100-s")] == "fails-like"


def test_rejection_finding_needs_the_programs_check_to_count_as_correct():
    # GCC findings report: a run that completes but prints check=fail is not "correct"
    c = M.derive_case({"file": "gcc/r.f90", "lang": "f90", "outcome": "rejected",
                       "expected": "check=pass", "toolchains": ["gcc_g90"]})
    assert c["expect"] == "out:check=pass"
    i = M.derive_case({"file": "gcc/i.f90", "lang": "f90", "outcome": "ice", "toolchains": ["cce19"]})
    assert i["expect"] == "ok"


def test_affected_with_a_mode_counts_that_toolchains_cells_in_that_mode():
    # vendor cases name the mode a finding was seen in ("afar@1"); the status reads them
    case = dict(CASE, affected=["cce19@1"])
    assert M.status("x", rows=four("x", "cce19", "tuolumne", "1", WRONG), cases=[case]) == ("open", None)
    assert M.status("x", rows=four("x", "cce19", "tuolumne", "1", RIGHT), cases=[case]) == ("not-reproduced", None)


def test_affected_with_a_mode_ignores_the_other_modes_cells():
    # correct in copy mode says nothing about a finding seen in unified mode
    case = dict(CASE, affected=["cce19@1"])
    assert M.status("x", rows=four("x", "cce19", "tuolumne", "0", RIGHT), cases=[case]) == ("not-run", None)


def test_affected_with_a_mode_keeps_cce21_4_with_cce21():
    case = dict(CASE, affected=["cce21@0"])
    rows = four("x", "cce21", "tuolumne", "0", WRONG) + four("x", "cce21_4", "tuolumne", "0", RIGHT)
    assert M.status("x", rows=rows, cases=[case]) == ("fixed", "21.0.4")


def _packed(path):
    import gzip
    import json
    return [json.loads(x) for x in gzip.open(path, "rt").read().splitlines() if x.strip()]


def _row_line(case, env, obs="RUN_OK rc=0\nok=1", tc="cce21", mode="1", variant="repro"):
    import json
    return json.dumps({"case": case, "tc": tc, "machine": "tuolumne", "mode": mode, "env": env,
                       "variant": variant, "obs": obs})


def test_pack_keeps_committed_rows_the_raw_file_does_not_have(tmp_path):
    """The raw file may hold only the newest runs: rows already committed for other
    (case, toolchain, machine, mode, variant, env) keys stay."""
    out = tmp_path / "results-site"
    first = tmp_path / "site-tuolumne.a.jsonl"
    first.write_text(_row_line("old", "a") + "\n" + _row_line("both", "a", "RUN_OK rc=0\nok=0") + "\n")
    M.pack([first], out)
    newest = tmp_path / "newest" / "site-tuolumne.a.jsonl"
    newest.parent.mkdir()
    newest.write_text(_row_line("new", "a") + "\n" + _row_line("both", "a") + "\n")
    M.pack([newest], out)
    rows = _packed(out / "site-tuolumne.a.jsonl.gz")
    by = {(r["case"], r["env"]): r["obs"] for r in rows}
    assert set(by) == {("old", "a"), ("both", "a"), ("new", "a")}
    assert by[("both", "a")].endswith("ok=1")   # the newest run of the same key wins


def test_pack_of_the_full_raw_file_is_unchanged_by_the_merge(tmp_path):
    out = tmp_path / "results-site"
    raw = tmp_path / "site-tuolumne.a.jsonl"
    raw.write_text(_row_line("x", "a") + "\n" + _row_line("x", "a", "RUN_OK rc=0\nok=0") + "\n")
    M.pack([raw], out)
    once = (out / "site-tuolumne.a.jsonl.gz").read_bytes()
    M.pack([raw], out)
    assert (out / "site-tuolumne.a.jsonl.gz").read_bytes() == once
    assert len(_packed(out / "site-tuolumne.a.jsonl.gz")) == 2   # repeat runs of one key are kept


def test_pack_drops_a_harness_error_row_the_newest_run_supersedes(tmp_path):
    """A harness error has no mode; the real run of the same case, toolchain, machine, variant and
    environment replaces it instead of sitting beside it."""
    import json
    out = tmp_path / "results-site"
    bad = {"case": "x", "tc": "gcc", "machine": "tioga", "env": "a", "variant": "repro",
           "obs": "HARNESS_ERROR FileNotFoundError(2, 'No such file or directory')"}
    first = tmp_path / "site-tioga-gcc.a.jsonl"
    first.write_text(json.dumps(bad) + "\n" + _row_line("other", "a", tc="gcc") + "\n")
    M.pack([first], out)
    good = dict(bad, mode="0", obs="COMPILE_FAIL rc=1\ninternal compiler error")
    newest = tmp_path / "newest" / "site-tioga-gcc.a.jsonl"
    newest.parent.mkdir()
    newest.write_text(json.dumps(good) + "\n")
    M.pack([newest], out)
    rows = _packed(out / "site-tioga-gcc.a.jsonl.gz")
    assert sorted(r["case"] for r in rows) == ["other", "x"]
    assert next(r for r in rows if r["case"] == "x")["obs"].startswith("COMPILE_FAIL")


def test_each_issue_says_when_and_how_it_fails():
    """stage: compile, link or run (a link message in a failing cell's output makes a refusal or a
    crash a link-time one); symptom: the finding's outcome; failure: the two in words."""
    from dataclasses import replace

    def fail(outcome, msg=""):
        return replace(cell("cce21", "21.0.3", "mi300a-u", "fails-like"), outcome=outcome, message=msg)
    ok = cell("afar", "AFAR 24.3.0", "mi300a-u", "correct")
    cases = [("wrong_answer", [fail("RUN_OK"), ok], "run", "wrong answer"),
             ("rejected", [fail("COMPILE_FAIL", "x.f90:3:1: error: expected ')'"), ok],
              "compile", "refused at compile time"),
             ("rejected", [fail("COMPILE_FAIL", "ld.lld: error: undefined symbol: __kmpc_x"), ok],
              "link", "refused at link time"),
             ("ice", [fail("COMPILE_FAIL", "lto1: internal compiler error: in expand"), ok],
              "link", "compiler crash at link time"),
             ("ice", [fail("COMPILE_FAIL", "internal compiler error: Segmentation fault"), ok],
              "compile", "compiler crash"),
             ("timeout", [fail("COMPILE_TIMEOUT"), ok], "compile", "compiler hangs"),
             ("timeout", [fail("RUN_TIMEOUT"), ok], "run", "hangs at run time"),
             ("crash", [fail("RUN_FAIL", "Segmentation fault"), ok], "run", "crashes or aborts at run time"),
             ("run_error", [fail("RUN_FAIL", "kernel not found"), ok], "run", "run-time error")]
    for k, (outcome, cells, stage, words) in enumerate(cases):
        (i,) = D.records([finding(f"f{k}", outcome=outcome, cells=cells)])["issues"]
        assert (i["stage"], i["symptom"], i["failure"]) == (stage, outcome, words), (outcome, i)
    # a correct cell's link message is not the issue's
    noisy = [fail("COMPILE_FAIL", "error: expected ')'"), replace(ok, message="ld.lld: error: x")]
    (i,) = D.records([finding("n", outcome="rejected", cells=noisy)])["issues"]
    assert i["stage"] == "compile"


def test_each_issue_carries_its_legality_review(tmp_path, monkeypatch):
    """legality: the verdict of its independent review (offload.engine.legality_review.status),
    in the site's words with the reason; an issue with no review is not independently confirmed."""
    from offload.engine import legality_review as L
    monkeypatch.setattr(L, "status", lambda fid: ("confirmed", "two readings agree") if fid == "c"
                        else ("unconfirmed", "no independent review yet"))
    r = D.records([finding("c"), finding("u")])
    got = {i["id"]: (i["legality"], i["legality_words"], i["legality_why"]) for i in r["issues"]}
    assert got["c"] == ("confirmed", "independently confirmed", "two readings agree")
    assert got["u"] == ("unconfirmed", "not independently confirmed", "no independent review yet")


def test_the_compilers_index_shows_each_release_and_what_changed_between_them():
    """compilers/index.html: a row of releases per family. Each release has its issue count and a
    bar split by when the issues fail, each part a link to those issues in the list; between
    consecutive releases of a family, the regressions and the fixes; GCC's two builds of one
    release have no change between them."""
    sys.path.insert(0, str(ROOT / "tools" / "site"))
    import site_build as B
    issue = lambda i, stage: {"id": i, "defect": i, "stage": stage}  # noqa: E731
    issues = [issue("a", "run"), issue("b", "compile"), issue("c", "link"), issue("d", "run")]
    cs = [{"tc": "cce19", "label": "CCE 19.0.0", "family": "cce", "version": "19.0.0", "fails": ["a", "b"],
           "regressions": [], "fixed_or_changed": []},
          {"tc": "cce20", "label": "CCE 20.0.2", "family": "cce", "version": "20.0.2", "fails": ["a", "b", "c", "d"],
           "regressions": ["c", "d"], "fixed_or_changed": ["x"]},
          {"tc": "gcc", "label": "GCC 16.2.0 AMD", "family": "gcc", "version": "16.2.0", "fails": ["a"],
           "regressions": [], "fixed_or_changed": []},
          {"tc": "gcc_sm80", "label": "GCC 16.2.0 A100", "family": "gcc", "version": "16.2.0", "fails": ["b"],
           "regressions": [], "fixed_or_changed": []}]
    html = B.compilers_index(cs, issues, ran={"cce19": ["mi300a-u"], "cce20": ["mi300a-u"],
                                              "gcc": ["mi250x"], "gcc_sm80": ["a100-s"]})
    assert html.index("Cray CCE") < html.index("GNU GCC")
    assert 'href="cce19.html"' in html and ">2<" in html and ">4<" in html
    assert 'href="../index.html?fam=cce&amp;vers=20.0.2&amp;stages=run&amp;st=' in html
    assert "2 regressions" in html and "1 fixed or changed" in html
    assert html.count('class="delta"') == 1                     # CCE 19 -> 20 only; none between GCC builds
    assert "within each family" in html and "MI300A" in html and "A100" in html
    assert "vers=16.2%20AMD&amp;" in html and "vers=16.2%20A100&amp;" in html   # the list's version buttons
    full = dict(issue("a", "run"), title="t", page="a", phase="offload", kind="incorrect", kinds=["incorrect"],
                constructs=[], fams={"gcc": {"status": "open", "versions": ["gcc"], "targets": ["mi250x"],
                                             "regression": False, "status_version": None}})
    page = B.compiler_page(cs[2], [full], "../")
    assert "vers=16.2%20AMD&amp;" in page


def test_every_page_credits_its_author_and_links_the_repository_when_there_is_one(site):
    """The footer: the author with a link to the author's public profile, the AI-assistance note, and, when
    the site is built with a repository URL, a link to the repository."""
    from offload.engine.site import scrub as SCR
    sys.path.insert(0, str(ROOT / "tools" / "site"))
    import site_build as B
    name, url = SCR.AUTHOR
    for p in ("index.html", "method.html", "canuse.html", "compilers/index.html"):
        t = (site / p).read_text()
        assert f'href="{url}"' in t and name in t and "with assistance from AI tools" in t, p
        assert "Source code" not in t                       # built without a repository URL
    assert 'href="https://github.com/x/offload-issues">Source code' in B.footer("https://github.com/x/offload-issues")
    # the profile URL is public on purpose; the handle alone elsewhere is still a leak
    assert SCR.leaks(f"by {name} ({url})") == []
    assert SCR.leaks("/home/" + url.rsplit("/", 1)[1] + "/x") != []
