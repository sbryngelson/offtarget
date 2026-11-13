"""Tests of the site checker, the dashboard datasets and the standalone dashboard."""


# ---- tools/site/site_check.py: broken links, leaks, sideways scroll, errors, on a fixture site -----------

import importlib.util
import shutil
from pathlib import Path

import pytest

from tests.site.test_site import site  # noqa: F401  (the fixture)

ROOT = Path(__file__).resolve().parent.parent.parent
spec = importlib.util.spec_from_file_location("site_check", ROOT / "tools/site/site_check.py")
SC = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SC)
HAVE_BROWSER = bool(shutil.which("node") and SC.chrome())


def test_check_flags_broken_link(site):  # noqa: F811
    assert SC.link_problems(site) == []
    p = site / "issues/plain.html"
    p.write_text(p.read_text().replace("</main>", '<a href="nosuch.html">x</a></main>'))
    probs = SC.link_problems(site)
    assert len(probs) == 1 and "nosuch.html" in probs[0]


def test_check_flags_leak(site):  # noqa: F811
    assert SC.file_leaks(site) == []
    p = site / "method.html"
    p.write_text(p.read_text().replace("</main>", "<p>/p/lustre5/jdoe1/x</p></main>"))
    assert any("method.html" in x for x in SC.file_leaks(site))


def test_check_allows_the_configured_repo_url_only(site):  # noqa: F811
    url = "https://github.com/sjdoe/compliant"
    p = site / "method.html"
    p.write_text(p.read_text().replace("</main>", f'<a href="{url}/blob/master/x">source</a></main>'))
    assert any("method.html" in x for x in SC.file_leaks(site))
    assert SC.file_leaks(site, allow=(url,)) == []
    p.write_text(p.read_text().replace("</main>", "<p>/g/g10/jdoe1</p></main>"))
    assert any("method.html" in x for x in SC.file_leaks(site, allow=(url,)))


@pytest.mark.skipif(not HAVE_BROWSER, reason="needs node and Chrome")
def test_check_passes_fixture_site(site):  # noqa: F811
    report = SC.check(site)
    assert report["problems"] == [], report["problems"]
    assert report["pages"] >= 6 and report["controls"] > 5


@pytest.mark.skipif(not HAVE_BROWSER, reason="needs node and Chrome")
def test_check_flags_sideways_scroll(site):  # noqa: F811
    p = site / "method.html"
    p.write_text(p.read_text().replace("</main>", '<div style="width:3000px">wide</div></main>'))
    report = SC.check(site, clicks=False)        # a page-load check: the list's click loop is not needed
    assert any("sideways" in x and "method.html" in x for x in report["problems"])
    assert report["controls"] == 0


@pytest.mark.skipif(not HAVE_BROWSER, reason="needs node and Chrome")
def test_check_reads_a_large_report(site):  # noqa: F811
    p = site / "method.html"
    p.write_text(p.read_text().replace("</main>", "<p>" + "word " * 40000 + "</p></main>"))
    report = SC.check(site, clicks=False)
    assert report["problems"] == [], report["problems"]


@pytest.mark.skipif(not HAVE_BROWSER, reason="needs node and Chrome")
def test_check_flags_stringified_objects(site):  # noqa: F811
    # an array or element appended as text renders "[object HTMLButtonElement]"
    p = site / "method.html"
    p.write_text(p.read_text().replace("</main>", "<p>[object HTMLButtonElement]</p></main>"))
    report = SC.check(site, clicks=False)
    assert any("[object" in x and "method.html" in x for x in report["problems"])


# --- Issue page helpers --------------------------------------------------------------------------------

def _issue(i, fam="cce", status="open", lang="f90", versions=("cce21",)):
    return {"id": i, "page": i, "defect": i, "kind": "incorrect", "kinds": ["incorrect"], "lang": lang,
            "model": "omp", "regression": False,
            "fams": {fam: {"versions": list(versions), "targets": ["mi300a-u"], "status": status}}}


ISSUES = [_issue("a"), _issue("b", lang="c"), _issue("n", status="not-reproduced", versions=())]


def _click(key, value, before, after, fam="cce"):
    return {"fam": fam, "key": key, "value": value, "label": f"{key}={value}",
            "before": [f"issues/{x}.html" for x in before], "after": [f"issues/{x}.html" for x in after]}


def test_click_check_flags_a_dead_filter():
    # The "not reproduced" status box left the list unchanged or empty
    clicks = [_click("st", "not-reproduced", ["a", "b"], ["a", "b"]),
              _click("langs", "c", ["a", "b"], [])]
    probs, unchanged = SC.click_problems(clicks, ISSUES)
    assert len(probs) == 2
    assert any("not-reproduced" in p and "changes nothing" in p for p in probs)
    assert any("langs=c" in p and "empty" in p for p in probs)


def test_click_check_accepts_what_the_data_says():
    clicks = [_click("st", "not-reproduced", ["a", "b"], ["a", "b", "n"]),
              _click("langs", "c", ["a", "b"], ["b"]),
              _click("langs", "f90", ["a", "b"], ["a"]),
              _click("models", "acc", ["a", "b"], []),           # no OpenACC issue: empty is right
              _click("sort", "construct", ["a", "b"], ["b", "a"]),
              _click("fam", "afar", ["a", "b"], ["a", "b", "x"]),   # adds AFAR's issues to CCE's
              _click("fam", "cce", ["a", "b"], ["a", "b"])]          # the only family stays selected
    probs, unchanged = SC.click_problems(clicks, ISSUES + [_issue("x", fam="afar")])
    assert probs == [] and unchanged == ["cce: fam=cce"]
    # recorded, not a problem: a click the data says changes nothing
    probs, unchanged = SC.click_problems([_click("models", "omp", ["a", "b"], ["a", "b"])], ISSUES)
    assert probs == [] and unchanged == ["cce: models=omp"]


def test_spec_check_flags_a_row_that_hides_or_invents_its_specification():
    issues = [{"page": "a", "specs": ["OpenMP 5.2 §5.8.3", "OpenMP 5.2 §10.2"]},
              {"page": "b", "specs": []}]
    ok = [["issues/a.html", "Specification: OpenMP 5.2 §5.8.3 · OpenMP 5.2 §10.2"], ["issues/b.html", ""]]
    assert SC.spec_problems(ok, issues) == []
    bad = [["issues/a.html", ""], ["issues/b.html", "Specification: OpenMP 5.2 §1"]]
    assert len(SC.spec_problems(bad, issues)) == 2


# ---- The dashboard datasets carry every memory mode ---------------------------------------------------

import csv
import re
import subprocess
import sys




def _tool():
    spec = importlib.util.spec_from_file_location(
        "dashboard_data_tool", ROOT / "tools" / "site" / "dashboard_data.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FIELDS = ["version", "program_id", "atom", "legal", "toolchain", "xnack",
          "label", "reason", "evidence", "audit", "citation", "scope",
          "portable", "mode_class", "arch_class"]


def _csv(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})


def _row(tc, x, label, portable="", mode_class="", pid="omp52-clause-x",
         atom="omp.clause.x", version="52"):
    return dict(version=version, program_id=pid, atom=atom, legal="1",
                toolchain=tc, xnack=str(x), label=label, reason="",
                evidence="construct", audit="valid", citation="c",
                scope="device", portable=portable if x == 1 else "",
                mode_class=mode_class if x == 1 else "")


def test_atoms_carry_both_modes_and_the_portable_verdict(tmp_path):
    tool = _tool()
    p = tmp_path / "t.csv"
    _csv(p, [_row("afar", 1, "correct on device", "portable"),
             _row("afar", 0, "correct on device"),
             _row("cce19", 1, "correct on device", "x1_only",
                  "copy_mode_failure"),
             _row("cce19", 0, "wrong answer (confirmed)"),
             _row("cce20", 1, "correct on device", "portable"),
             _row("cce20", 0, "correct on device"),
             _row("cce21", 1, "rejected", "neither"),
             _row("cce21", 0, "rejected")])
    (e,) = tool.atoms(p, "f90", {})
    assert e["cce20_x0"] == "ok" and e["cce21_x0"] == "rejected"
    assert e["afar_portable"] == "portable"
    assert e["cce_portable"] == "x1_only"
    assert e["cce_mode_class"] == "copy_mode_failure"
    assert e["portable"] == "AFAR, CCE 20"


def test_acc_atoms_carry_the_portable_verdict(tmp_path):
    tool = _tool()
    p = tmp_path / "a.csv"
    rows = []
    for tc in ("cce19", "cce20", "cce21"):
        rows += [_row(tc, 1, "correct on device", "portable",
                      pid="acc34-clause-copy", atom="acc.clause.copy",
                      version="34"),
                 _row(tc, 0, "correct on device", pid="acc34-clause-copy",
                      atom="acc.clause.copy", version="34")]
    _csv(p, rows)
    (e,) = tool.acc_atoms(p)
    assert e["cce21_portable"] == "portable"
    assert e["portable"] == "CCE 19, CCE 20, CCE 21"


def _tables(html):
    """{table id: [th data-field of its first header row]} and {table id:
    [column keys of its mount config]}."""
    heads = {}
    for m in re.finditer(r'<table id="(\w+)"[^>]*>\s*<thead><tr>(.*?)</tr>',
                         html, re.S):
        heads[m.group(1)] = re.findall(r'<th data-field="(\w+)"',
                                       m.group(2))
    return heads


def test_page_headers_match_the_column_configs():
    html = (ROOT / "tools" / "site" / "dashboard_page.html").read_text()
    heads = _tables(html)
    # each mounted table declares its columns once, in COLS.<table id>
    cols = {}
    for m in re.finditer(r"COLS\.(\w+)=\[(.*?)\];", html, re.S):
        cols[m.group(1)] = re.findall(r"key:'(\w+)'", m.group(2))
    mounted = re.findall(r"tbl:document.getElementById\('(\w+)'\)", html)
    assert mounted, "no mounted tables"
    for t in mounted:
        assert t in cols, f"{t}: columns not declared in COLS.{t}"
    for t in cols:
        assert heads[t] == cols[t], (t, heads[t], cols[t])
    assert "cce21_x0" in cols["tbl"] and "portable" in cols["tbl"]
    assert "cce20_x0" in cols["vtbl"] and "portable" in cols["atbl"]


def test_atoms_carry_the_map_audit_mode(tmp_path, monkeypatch):
    tool = _tool()
    monkeypatch.setattr(tool, "map_caught", lambda: {
        ("f90", "52", "omp.clause.x"): "x0_only"})
    p = tmp_path / "t.csv"
    _csv(p, [_row("afar", 1, "correct on device", "portable"),
             _row("afar", 0, "correct on device")])
    (e,) = tool.atoms(p, "f90", {})
    assert e["map_caught"] == "x0_only"


def test_runs_are_split_by_memory_mode():
    """With every program in both modes the runs dataset passes
    the 8 MB limit of a dashboard file: runs holds HSA_XNACK=1, runs_x0
    HSA_XNACK=0."""
    tool = _tool()
    rows = [{"id": "a", "x": "1"}, {"id": "a", "x": "0"}]
    x1, x0, g90 = tool.split_runs(rows)
    assert [r["x"] for r in x1] == ["1"] and [r["x"] for r in x0] == ["0"]
    assert g90 == []
    html = (ROOT / "tools" / "site" / "dashboard_page.html").read_text()
    assert "function runsOf(k)" in html


def test_compile_time_probe_pass_is_ok():
    tool = _tool()
    assert tool.status("compile-time error termination as required "
                       "(probe)") == "ok"


def test_every_portable_verdict_has_a_column_in_the_page():
    """Every verdict offload/engine/report.py
    can emit for a device row has its own column in the portable summary
    table (COLS.ptbl, the header row and the calc's initialisation), so no
    verdict hides in "Other"."""
    from offload.engine.report import PORTABLE
    html = (ROOT / "tools" / "site" / "dashboard_page.html").read_text()
    m = re.search(r"COLS\.ptbl=\[(.*?)\];", html, re.S)
    keys = set(re.findall(r"key:'(\w+)'", m.group(1)))
    init = re.search(r"m\[id\]=\{id:id,lang:a\.lang,(.*?)\}\)", html).group(1)
    inits = set(re.findall(r"(\w+):0", init))
    # x0_not_run and gfx90a_not_run cannot occur (every program ran in
    # both modes and on gfx90a); the rest must each have a column
    for v in set(PORTABLE) - {"x0_not_run", "gfx90a_not_run"}:
        assert v in keys, f"{v}: no column in the portable table"
        assert v in inits, f"{v}: not initialised in portable_summary"


# --- The gfx90a (Tioga MI250X) cells ---------------------------------

def test_atoms_carry_the_gfx90a_cell_and_arch_class(tmp_path):
    tool = _tool()
    p = tmp_path / "t.csv"
    rows = [_row("afar", 1, "correct on device", "gfx942_only"),
            _row("afar", 0, "correct on device"),
            _row("afar_g90", 0, "wrong answer (confirmed)"),
            _row("cce19", 1, "correct on device", "portable"),
            _row("cce19", 0, "correct on device"),
            _row("cce19_g90", 0, "correct on device")]
    rows[0]["arch_class"] = "gfx90a_failure"
    _csv(p, rows)
    (e,) = tool.atoms(p, "f90", {})
    assert e["afar_g90"] == "wrong" and e["cce_g90"] == "ok"
    assert e["note_afar_g90"].startswith("wrong answer")
    assert e["afar_arch_class"] == "gfx90a_failure"
    assert e["cce20_g90"] == ""  # every key present
    assert e["portable"] == "CCE 19"


def test_runs_g90_dataset_and_keys():
    tool = _tool()
    rows = [{"id": "a", "x": "1", "tc": "afar"},
            {"id": "a", "x": "0", "tc": "afar"},
            {"id": "a", "x": "0", "tc": "afar_g90"}]
    x1, x0, g90 = tool.split_runs(rows)
    assert [r["tc"] for r in g90] == ["afar_g90"] and len(x0) == 1
    assert tool.TKEY["cce19_g90"] == "cce_g90"


def test_page_has_gfx90a_columns():
    html = (ROOT / "tools" / "site" / "dashboard_page.html").read_text()
    cols = {m.group(1): re.findall(r"key:'(\w+)'", m.group(2))
            for m in re.finditer(r"COLS\.(\w+)=\[(.*?)\];", html, re.S)}
    for k in ("afar_g90", "cce_g90", "cce20_g90", "cce21_g90"):
        assert k in cols["tbl"] and k in cols["vtbl"]
    for k in ("cce19_g90", "cce20_g90", "cce21_g90"):
        assert k in cols["atbl"]
    assert "runs_g90" in html


def test_no_committed_cell_is_gfx90a_not_run():
    """The page has no gfx90a_not_run column because every
    program ran on gfx90a; a partial gfx90a run would put cells there."""
    for p in (ROOT / "data" / "reports" / "c_support_table.csv",
              ROOT / "data" / "reports" / "acc_support_table.csv",
              ROOT / "results" / "support_table.csv"):
        if p.is_file():
            assert not any(r.get("portable") == "gfx90a_not_run"
                           for r in csv.DictReader(p.open())), p


@pytest.mark.skipif(not (shutil.which("node") and shutil.which("google-chrome")),
                    reason="needs node and google-chrome")
def test_page_renders_with_empty_datasets(tmp_path):
    """The page loads, survives a click on every control and fills every headline mark
    (with 0) when each dataset it reads has no rows."""
    page = (ROOT / "tools" / "site" / "dashboard_page.html").read_text()
    ids = set(re.findall(r"dash\.data\('([A-Za-z0-9_]+)'", page))
    calcs = set(re.findall(r"dash\.calc\('([A-Za-z0-9_]+)'", page))
    for i in ids - calcs | {"runs", "runs_x0", "runs_g90"}:
        (tmp_path / f"{i}.json").write_text("[]")
    p = subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "site" / "dashboard_render_check.py"),
                        str(tmp_path), "--widths", "420"],
                       capture_output=True, text=True, timeout=900)
    assert p.returncode == 0, p.stdout + p.stderr


def test_ompvv_outputs_are_clipped(tmp_path):
    """The omp_vv dataset must stay under the 8 MB dataset limit
    (the rerun's CCE and AFAR compile logs took it to 8.9 MB): each cell's
    output keeps its head and tail, with the omitted length said."""
    import json
    D = _tool()
    big = "x" * 50000
    p = tmp_path / "b.jsonl"
    p.write_text(json.dumps({
        "path": "tests/5.0/a/test_a.c", "spec_dir": "5.0",
        "toolchain": "afar", "xnack": 1, "status": "fail", "stage": "run",
        "reason": "r", "stdout": "head" + big + "tail", "stderr": big,
        "device": "d", "compiler": "c"}) + "\n")
    rows = D.ompvv(p, "c")
    out = rows[0]["out_afar_x1"]
    assert len(out) <= D.OMPVV_OUT_MAX + 200
    assert "head" in out and "tail" in out and "omitted" in out


def test_widened_rows_join_the_atom_datasets(tmp_path):
    """The widened catalog's rows (data/reports/
    widen_support_table.csv) join the atoms (Fortran and C OpenMP) and
    acc_atoms (OpenACC) datasets, one row per program, marked `widened`;
    each row's language and model come from its program id."""
    tool = _tool()
    p = tmp_path / "w.csv"
    rows = [_row("afar", 1, "correct on device", "portable",
                 pid="omp52-w-block", atom="base.device.block"),
            _row("cce19", 1, "rejected", "neither",
                 pid="omp52-c-w-union", atom="base.device.union"),
            _row("cce19", 1, "crash: SIGABRT", "neither",
                 pid="acc34-w-stop-unreached", atom="base.device.stop",
                 version="34")]
    _csv(p, rows)
    a, acc = tool.widened(p, {})
    assert {e["id"]: e["lang"] for e in a} == {"omp52-w-block": "f90",
                                               "omp52-c-w-union": "c"}
    assert all(e["widened"] for e in a + acc)
    assert a[0]["atom"] == "base.device.block"
    (e,) = acc
    assert e["id"] == "acc34-w-stop-unreached" and e["cce19_x1"]


def _marks(html, section):
    i = html.index(f'id="{section}"')
    j = html.index("</section>", i)
    return [dict(kv.split("=") for kv in w.replace("&amp;", "&").split("&"))
            for w in re.findall(r'data-where="([^"]+)"', html[i:j])]


def test_headline_tiles_cover_every_platform():
    """The headline names NVHPC on the A100 (separate memory) next to the
    AMD tiles, for every language and version an AMD tile shows."""
    html = (ROOT / "tools" / "site" / "dashboard_page.html").read_text()
    marks = _marks(html, "headline")
    amd = {(m["lang"], m["version"]) for m in marks if m["xnack"] == "1"}
    assert amd
    for tc in ("NVHPC", "NVHPC%2026.9"):
        nv = {(m["lang"], m["version"]) for m in marks
              if m["toolchain"] == tc and m["xnack"] == "sep"}
        assert nv == amd, (tc, amd - nv)
    assert "Correct on the device, zero-copy memory (HSA_XNACK=1)</h2>" not in html


def test_openacc_tiles_cover_cce_and_nvhpc():
    html = (ROOT / "tools" / "site" / "dashboard_page.html").read_text()
    marks = _marks(html, "acc")
    for tc in ("cce19", "cce20", "cce21", "nvhpc", "nvhpc269"):
        assert {m["status"] for m in marks if m["tc"] == tc} == {"ok", "portable"}, tc
    assert "Cray (Fortran only)" not in html
    assert "90 OpenACC features" not in html


def test_page_counts_are_not_hard_coded():
    html = (ROOT / "tools" / "site" / "dashboard_page.html").read_text()
    assert "169 features at 5.0" not in html
    for i in ("barcounts", "introcounts", "acccount"):
        assert f'id="{i}"' in html and f"getElementById('{i}')" in html


def test_fuzz_campaign_picker_offers_every_run():
    """The campaign picker (RUNOPT) lists every run tools/site/dashboard_data.py emits."""
    html = (ROOT / "tools" / "site" / "dashboard_page.html").read_text()
    opts = re.search(r"var RUNOPT=\[(.*?)\];", html).group(1)
    keys = re.findall(r"\['([\w-]+)',", opts)
    assert [r[0] for r in _tool().ALL_RUNS] == keys


def test_widened_rows_are_marked_in_the_page():
    html = (ROOT / "tools" / "site" / "dashboard_page.html").read_text()
    assert html.count("key:'catalog',label:'Catalog'") == 2
    assert "chip wd" in html


def test_compiler_diff_keys_include_nvhpc():
    html = (ROOT / "tools" / "site" / "dashboard_page.html").read_text()
    head = re.search(r"var HEAD=\[(.*?)\];", html).group(1)
    assert "nvhpc_x0" in head and "nvhpc269_x0" in head
    assert "diffKeys:X1" not in html


def test_page_has_the_task37_slices():
    """C 5.0 headline tiles (AMD and NVHPC), OpenACC C tiles and a
    language picker in the OpenACC table, NVHPC columns in the fuzz tables."""
    html = (ROOT / "tools" / "site" / "dashboard_page.html").read_text()
    marks = _marks(html, "headline")
    c50 = {m["toolchain"] for m in marks if m["lang"] == "c"
           and m["version"] == "5.0"}
    assert c50 == {"AFAR", "CCE", "CCE%2020", "CCE%2021", "NVHPC",
                   "NVHPC%2026.9"}
    acc = _marks(html, "acc")
    assert {(m["tc"], m["status"]) for m in acc if m["lang"] == "c"} == {
        ("nvhpc", "ok"), ("nvhpc269", "ok"), ("nvhpc", "portable"),
        ("nvhpc269", "portable")}
    assert "key:'lang',label:'Language'" in html
    for t in ("fgtbl", "fbtbl"):
        cols = re.search(rf"COLS\.{t}=\[(.*?)\];", html).group(1)
        assert "nvhpc_rate" in cols and "nvhpc269_rate" in cols


def test_acc_atoms_carry_their_language(tmp_path):
    tool = _tool()
    p = tmp_path / "a.csv"
    _csv(p, [_row("nvhpc", 0, "correct on device", "portable",
                  pid="acc34-c-clause-copy", atom="acc.clause.copy",
                  version="34")])
    (e,) = tool.acc_atoms(p, "c")
    assert e["lang"] == "c" and e["nvhpc_x0"] == "ok"


# ---- tools/site/dashboard_standalone.py: the dashboard as a page plus data files ----------------------

import json




def _tool_3():
    spec = importlib.util.spec_from_file_location(
        "dashboard_standalone", ROOT / "tools" / "site" / "dashboard_standalone.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _empty_datasets(d: Path) -> None:
    page = (ROOT / "tools" / "site" / "dashboard_page.html").read_text()
    ids = set(re.findall(r"dash\.data\('([A-Za-z0-9_]+)'", page))
    calcs = set(re.findall(r"dash\.calc\('([A-Za-z0-9_]+)'", page))
    for i in ids - calcs | {"runs", "runs_x0", "runs_g90", "runs_nvhpc"}:
        (d / f"{i}.json").write_text("[]")


def test_build_layout(tmp_path):
    data, out = tmp_path / "d", tmp_path / "o"
    data.mkdir()
    _empty_datasets(data)
    r = _tool_3().build(data, out, ROOT / "tools" / "site" / "dashboard_page.html")
    html = (out / "index.html").read_text()
    ids = sorted(p.stem for p in data.glob("*.json"))
    assert json.loads(re.search(r"window\.__DSIDS = (\[.*?\]);", html).group(1)) == ids
    assert html.index("<title>") < 8192
    assert not re.search(r"<!doctype|<html|<body", html[:html.index('<div id="dash-root">')], re.I)
    # every color token gets a light value on :root and a dark one in both dark blocks
    root = re.search(r":root\{(.*?)\}", html, re.S).group(1)
    for tok in re.findall(r"var\((--color-[a-z-]+)", (ROOT / "tools" / "site" / "dashboard_page.html").read_text()):
        assert tok + ":" in root
    assert '@media (prefers-color-scheme: dark){:root:not([data-theme="light"])' in html
    assert ':root[data-theme="dark"]' in html
    # no host outside the artifact allowlist
    hosts = set(re.findall(r'(?:src|href)="https://([^/"]+)', html))
    assert hosts <= {"fonts.googleapis.com"}
    files = json.loads((out / "files.json").read_text())
    assert sorted(files) == [f"data/{i}.json" for i in ids] == sorted(r["files"])
    assert all(Path(v).is_file() for v in files.values())


def test_build_refuses_oversized_file(tmp_path, monkeypatch):
    m = _tool_3()
    data = tmp_path / "d"
    data.mkdir()
    (data / "atoms.json").write_text("[" + "0," * 600 + "0]")
    monkeypatch.setattr(m, "LIMIT", 1000)
    with pytest.raises(SystemExit, match="16 MB"):
        m.build(data, tmp_path / "o", ROOT / "tools" / "site" / "dashboard_page.html")


@pytest.mark.skipif(not shutil.which("node") or not (shutil.which("google-chrome") or shutil.which("chromium")),
                    reason="needs node and Chrome")
def test_standalone_renders_with_empty_datasets(tmp_path):
    """Served over HTTP, the standalone page fetches its data files, survives a click on
    every control and fills every headline mark."""
    data, out = tmp_path / "d", tmp_path / "o"
    data.mkdir()
    _empty_datasets(data)
    _tool_3().build(data, out, ROOT / "tools" / "site" / "dashboard_page.html")
    p = subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "site" / "dashboard_render_check.py"),
                        "--standalone", str(out), "--widths", "420"],
                       capture_output=True, text=True, timeout=900)
    assert p.returncode == 0, p.stdout + p.stderr


@pytest.mark.skipif(not shutil.which("node") or not (shutil.which("google-chrome") or shutil.which("chromium")),
                    reason="needs node and Chrome")
def test_standalone_reports_missing_file(tmp_path):
    """A data file that fails to load is named on the page, and the rest still renders."""
    data, out = tmp_path / "d", tmp_path / "o"
    data.mkdir()
    _empty_datasets(data)
    _tool_3().build(data, out, ROOT / "tools" / "site" / "dashboard_page.html")
    (out / "data" / "fuzz.json").unlink()
    p = subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "site" / "dashboard_render_check.py"),
                        "--standalone", str(out), "--widths", "420"],
                       capture_output=True, text=True, timeout=900)
    assert "fuzz" in p.stdout
