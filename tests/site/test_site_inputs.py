"""Tests of the site inputs: the optional site block of a finding, the committed inputs, and the scrubbing of user names, paths and internal references."""


# ---- The optional `site:` block of a finding file -----------------------------------------------------

from pathlib import Path

import pytest

from offload.engine.confirm.findings import load_index
from offload.engine.site import header as H

ROOT = Path(__file__).resolve().parent.parent.parent

F90 = """\
! # CCE 21: something reads the wrong element
! Observed (2026-10-25): ...
program p
  print *, 1
end program p
! site:
! title: A private array reads its first element
! summary: Each iteration reads v(s(3)); CCE 21 reads v(1).
! workaround: Copy the subscript to a firstprivate scalar.
! found_in: MFC (vel(dir_idx(1)))
! control: controls/a.f90 subscript is a firstprivate scalar
! control: controls/b.f90 the array is mapped, not private
! report: draft
! same_as: catalog/other-finding
! disposition: mixed legality disputed (5.2 p.275)
! hide: false
! end site
"""

C = """\
/* A C finding with a block comment first. */
#include <stdio.h>
int main(void) { return 0; }
// site:
// title: nvc ignores the present modifier
// control: controls/c.c map(present) on a mapped array
// end site
"""


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    (tmp_path / "controls").mkdir(exist_ok=True)
    for c in ("a.f90", "b.f90", "c.c"):   # the controls F90 and C name
        (tmp_path / "controls" / c).write_text("program c\nend program c\n")
    return p


def test_parse_fortran_block(tmp_path):
    h = H.parse(_write(tmp_path, "x.f90", F90))
    assert h.title == "A private array reads its first element"
    assert h.summary == "Each iteration reads v(s(3)); CCE 21 reads v(1)."
    assert h.workaround == "Copy the subscript to a firstprivate scalar."
    assert h.found_in == "MFC (vel(dir_idx(1)))"
    assert h.controls == (("controls/a.f90", "subscript is a firstprivate scalar"),
                          ("controls/b.f90", "the array is mapped, not private"))
    assert h.report == "draft"
    assert h.same_as == "catalog/other-finding"
    assert h.disposition == ("mixed", "legality disputed (5.2 p.275)")
    assert h.hide is False


def test_parse_c_block(tmp_path):
    h = H.parse(_write(tmp_path, "x.c", C))
    assert h.title == "nvc ignores the present modifier"
    assert h.controls == (("controls/c.c", "map(present) on a mapped array"),)
    assert h.disposition is None


def test_no_block_is_empty_header(tmp_path):
    h = H.parse(_write(tmp_path, "x.f90", "! just a comment\nprogram p\nend program p\n"))
    assert h == H.SiteHeader()
    assert h.hide is False and h.controls == () and h.title is None


def test_unknown_key_raises(tmp_path):
    bad = F90.replace("! title:", "! titel:")
    with pytest.raises(H.SiteHeaderError, match=r"titel.*line 7"):
        H.parse(_write(tmp_path, "x.f90", bad))


def test_devices_names_the_toolchains_that_see_every_device(tmp_path):
    """`devices: all TC...`: the site matrix leaves every device of the node visible to the
    program on those toolchains (a GCC fault on the MI250X shows only with all eight GCDs
    visible); `all` alone means every toolchain. The words must be catalog toolchains."""
    h = H.parse(_write(tmp_path, "x.c", C.replace("// end site", "// devices: all gcc_g90 gcc_sm80\n// end site")))
    assert h.devices == ("gcc_g90", "gcc_sm80")
    assert H.parse(_write(tmp_path, "y.c", C.replace("// end site", "// devices: all\n// end site"))).devices == ("*",)
    assert H.parse(_write(tmp_path, "z.c", C)).devices == ()
    with pytest.raises(H.SiteHeaderError, match="devices"):
        H.parse(_write(tmp_path, "w.c", C.replace("// end site", "// devices: all gcc99\n// end site")))
    with pytest.raises(H.SiteHeaderError, match="devices"):
        H.parse(_write(tmp_path, "v.c", C.replace("// end site", "// devices: some gcc_g90\n// end site")))
    rendered = "\n".join(H.render(h, "c"))
    assert "// devices: all gcc_g90 gcc_sm80" in rendered
    assert H.parse(_write(tmp_path, "r.c", "int main(void){return 0;}\n" + rendered + "\n")).devices == h.devices


def test_bad_disposition_kind_raises(tmp_path):
    bad = F90.replace("disposition: mixed", "disposition: held")
    with pytest.raises(H.SiteHeaderError, match="disposition"):
        H.parse(_write(tmp_path, "x.f90", bad))


def test_unterminated_or_repeated_block_raises(tmp_path):
    with pytest.raises(H.SiteHeaderError, match="end site"):
        H.parse(_write(tmp_path, "x.f90", F90.replace("! end site\n", "")))
    with pytest.raises(H.SiteHeaderError, match="more than one"):
        H.parse(_write(tmp_path, "y.f90", F90 + "! site:\n! title: x\n! end site\n"))


def test_render_parse_round_trip(tmp_path):
    h = H.parse(_write(tmp_path, "x.f90", F90))
    for lang, ext in (("f90", "f90"), ("c", "c")):
        body = "program p\nend program p\n" if lang == "f90" else "int main(void){return 0;}\n"
        p = _write(tmp_path, "r." + ext, body + "\n".join(H.render(h, lang)) + "\n")
        assert H.parse(p) == h


MANUAL = {
    ("a-out.f90", "hpe"): ("not a report", "out of scope (maintainer ruling): the region runs on the host"),
    ("catalog/b-atomic.c", "amd"): ("not a report", "the undefined symbols come from the host object: "
                                    "a missing libatomic link, not a device link failure"),
    ("catalog/c-nohost.f90", "hpe"): ("held, maintainer decision", "legality disputed"),
    ("fuzz/d.f90", "hpe"): ("held: legality not settled", "rests on one reading of 5.2 p.148"),
    ("e-thread-limit.f90", "hpe"): ("fixed in CCE 20.0.2", "CCE 20 and 21 accept it"),
    ("f-spelling.c", "hpe"): ("not a report", "one upstream issue covers both vendors (AMD packet, tier 4)"),
}
REPORTS = [
    {"primary": "p1", "title": "ftn: lastprivate on distribute loses the value, CCE 19.0.0 to 21.0.4",
     "findings": ["stress/p1.f90", "fuzz/m2.f90"]},
    {"primary": "q", "title": "nvc: present is ignored (device write lost), 25.11 and 26.9",
     "findings": ["q.c"]},
]
CASES = [{"finding": "stress/p1.f90", "control": "src/p1-control.f90",
          "control_what": "explicit map(tofrom: l)"},
         {"finding": "q.c", "control": "src/q-control.c", "control_what": "a is mapped first",
          "control_opt": "-O0"}]


def test_seed_dispositions():
    s = H.seed("a-out.f90", MANUAL, [], [])
    assert s.disposition == ("out-of-scope", "out of scope (maintainer ruling): the region runs on the host")
    assert H.seed("catalog/b-atomic.c", MANUAL, [], []).disposition[0] == "not-a-compiler-issue"
    assert H.seed("catalog/c-nohost.f90", MANUAL, [], []).disposition == ("mixed", "legality disputed")
    assert H.seed("fuzz/d.f90", MANUAL, [], []).disposition[0] == "mixed"
    assert H.seed("e-thread-limit.f90", MANUAL, [], []).disposition is None   # fixed: computed
    assert H.seed("f-spelling.c", MANUAL, [], []).disposition is None         # an issue, other packet


def test_seed_titles_same_as_and_controls():
    p = H.seed("stress/p1.f90", {}, REPORTS, CASES)
    assert p.title == "ftn: lastprivate on distribute loses the value"
    assert p.same_as is None
    assert p.controls == (("../vendor/checks/src/p1-control.f90", "explicit map(tofrom: l)"),)
    m = H.seed("fuzz/m2.f90", {}, REPORTS, CASES)
    assert m.same_as == "stress/p1" and m.title == p.title
    q = H.seed("q.c", {}, REPORTS, CASES)
    assert q.title == "nvc: present is ignored (device write lost)"
    assert q.controls == (("../vendor/checks/src/q-control.c", "a is mapped first (-O0)"),)


def test_merge_never_overwrites(tmp_path):
    old = H.SiteHeader(title="hand title", workaround="w")
    new = H.SiteHeader(title="seeded", same_as="x", controls=(("c.f90", "d"),))
    m = H.merge(old, new)
    assert m.title == "hand title" and m.workaround == "w" and m.same_as == "x"
    assert m.controls == (("c.f90", "d"),)
    assert H.merge(H.SiteHeader(controls=(("k.f90", "mine"),)), new).controls == (("k.f90", "mine"),)


def test_write_block_replaces_existing_block(tmp_path):
    p = _write(tmp_path, "x.f90", F90)
    H.write(p, H.SiteHeader(title="new title"), "f90")
    text = p.read_text()
    assert text.count("site:") == 1 and "new title" in text and "program p" in text
    assert H.parse(p).title == "new title"
    q = _write(tmp_path, "y.c", "int main(void){return 0;}\n")
    H.write(q, H.SiteHeader(title="t"), "c")
    assert q.read_text().startswith("int main") and H.parse(q).title == "t"


def test_vendor_dispositions_read_the_headers():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "dispositions", ROOT / "data/vendor/checks/dispositions.py")
    d = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(d)
    nohost = H.parse(ROOT / "data/findings/catalog/cce-nohost-link.f90")
    st, why = d.MANUAL[("catalog/cce-nohost-link.f90", "hpe")]
    assert st.startswith("held") and why == nohost.disposition[1]
    st, why = d.MANUAL[("cce19-acc-if-false-link.f90", "hpe")]
    assert st == "not a report" and "host" in why
    # vendor-only entries (no site disposition) stay in the vendor table
    assert ("clang-c-declare-target-to-omp52.c", "hpe") in d.MANUAL
    assert not hasattr(d, "LEGACY_MANUAL") or d.LEGACY_MANUAL


def test_site_block_does_not_change_batch_inputs_hash(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("regenerate", ROOT / "tools/regenerate.py")
    rg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rg)
    f = tmp_path / "data/findings/fuzz/a.f90"
    f.parent.mkdir(parents=True)
    f.write_text("! toolchain: afar\nprogram p\nend program p\n")
    h0 = rg.batch_inputs_hash(tmp_path, files=(), globs=("data/findings/fuzz/*.f90",))
    H.write(f, H.SiteHeader(title="t", same_as="x"), "f90")
    assert rg.batch_inputs_hash(tmp_path, files=(), globs=("data/findings/fuzz/*.f90",)) == h0
    f.write_text(f.read_text().replace("program p\n", "program q\n"))
    assert rg.batch_inputs_hash(tmp_path, files=(), globs=("data/findings/fuzz/*.f90",)) != h0


def test_every_committed_finding_parses():
    for f in load_index():
        H.parse(ROOT / f.file)


def test_render_wraps_fortran_lines_at_132_and_parse_rejoins(tmp_path):
    # Fortran's 132-character limit covers comment lines
    long = " ".join(["word"] * 60)
    p = tmp_path / "f.f90"
    p.write_text("program p\nend program p\n")
    (tmp_path / "x.f90").write_text("program x\nend program x\n")
    H.write(p, H.SiteHeader(title="t", summary=long, controls=(("x.f90", long),)), "f90")
    assert all(len(x) <= 132 for x in p.read_text().splitlines())
    h = H.parse(p)
    assert h.summary == long and h.controls == (("x.f90", long),)


def test_parse_rejects_a_fortran_line_over_132(tmp_path):
    p = tmp_path / "f.f90"
    p.write_text("program p\nend program p\n! site:\n! summary: " + "x" * 130 + "\n! end site\n")
    with pytest.raises(H.SiteHeaderError, match="132"):
        H.parse(p)


# --- A control that is missing -------------------------------------------------------------------------

def test_missing_control_fails_parse(tmp_path):
    # a control path resolves against the findings directory (findings; the file's own
    # directory when it is in none), as the build reads it
    d = tmp_path / "data/findings/catalog"
    d.mkdir(parents=True)
    p = d / "x.f90"
    p.write_text("program p\nend program p\n! site:\n! control: ../vendor/ctl.f90 the map removed\n! end site\n")
    with pytest.raises(H.SiteHeaderError, match=r"control.*vendor/ctl\.f90.*not found"):
        H.parse(p)
    (tmp_path / "data" / "vendor").mkdir(parents=True)
    (tmp_path / "data/vendor/ctl.f90").write_text("program c\nend program c\n")
    assert H.parse(p).controls == (("../vendor/ctl.f90", "the map removed"),)


def test_one_bad_block_does_not_break_the_vendor_tools(tmp_path, capsys):
    import importlib.util
    from types import SimpleNamespace
    spec = importlib.util.spec_from_file_location(
        "dispositions", ROOT / "data/vendor/checks/dispositions.py")
    d = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(d)
    base = tmp_path / "data" / "findings"
    base.mkdir(parents=True)
    (base / "bad.f90").write_text("program p\nend program p\n! site:\n! titel: x\n! end site\n")
    (base / "ok.f90").write_text("program p\nend program p\n! site:\n! disposition: mixed disputed\n! end site\n")
    entries = [SimpleNamespace(file="data/findings/bad.f90", toolchains=("cce21",)),
               SimpleNamespace(file="data/findings/ok.f90", toolchains=("cce21",))]
    out = d._from_headers(entries, tmp_path)
    assert out == {("ok.f90", "hpe"): ("held (mixed evidence)", "disputed")}
    assert "bad.f90" in capsys.readouterr().err and "data/findings/bad.f90" in d.BAD_HEADERS[0]
    with pytest.raises(H.SiteHeaderError):   # the site build parses every header itself
        H.parse(base / "bad.f90")


# ---- The site's committed inputs (site/inputs/, offload.engine.site.inputs, tools/site/site_inputs.py): ----

import ast
import glob
import gzip
import importlib.util
import json
import re
import subprocess


import where

from offload.engine.site import data as D
from offload.engine.site import inputs as I
from offload.engine.site import scrub as S_scrub
from tests.site.test_site import finding



def _tool(name):
    spec = importlib.util.spec_from_file_location(f"_{name}", where.tool(f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ATOMS = [
    {"scope": "device", "atom": "clause.defaultmap", "id": "omp52-clause-defaultmap", "version": "5.2",
     "lang": "f90", "citation": "OpenMP 5.2 §5.8.7", "cce21_x1": "ok", "note_cce21_x1": "fine",
     "cce21_x0": "suspect", "note_cce21_x0": "wrong value once in /p/lustre5/jdoe1/x",
     "afar_x1": "excluded", "note_afar_x1": "", "nvhpc_x0": "rejected", "unrelated": "dropped",
     "trust": "trusted"},
    {"scope": "host+device", "atom": "clause.private", "id": "omp52-clause-private", "version": "5.2",
     "lang": "f90", "cce21_x1": "ok"},
]
COLS = {"cce21_x1", "cce21_x0", "afar_x1", "nvhpc_x0", "nvhpc_x2"}


def test_projection_keeps_device_rows_and_only_what_the_site_reads():
    rows = I.project_atoms(ATOMS, COLS)
    assert [r["id"] for r in rows] == ["omp52-clause-defaultmap"]
    (r,) = rows
    assert set(r) == {"scope", "atom", "id", "version", "lang", "citation", "cce21_x1", "cce21_x0",
                      "note_cce21_x0", "afar_x1", "nvhpc_x0"}
    # a note is kept only where the site shows it (an unknown or unsupported cell), scrubbed
    assert r["note_cce21_x0"] == "wrong value once in <home>/x"
    assert "note_cce21_x1" not in r and "note_afar_x1" not in r


def test_projection_refuses_a_leak(monkeypatch):
    monkeypatch.setattr(I.S, "scrub", lambda s: s)
    with pytest.raises(I.SiteInputError, match="identifies"):
        I.project_atoms(ATOMS, COLS)


def test_projection_builds_the_same_support_as_the_raw_table():
    cols = {c for cs in D._atom_columns().values() for c, _ in cs}
    recs = D.records([finding("t")])
    assert D.canuse(I.project_atoms(ATOMS, cols), recs) == D.canuse(ATOMS, recs)


def test_atoms_file_round_trips_and_is_byte_stable():
    rows = I.project_atoms(ATOMS, COLS)
    blob = I.dump_atoms(rows)
    assert json.loads(gzip.decompress(blob)) == rows
    assert I.dump_atoms(rows) == blob     # no timestamp in the gzip header


def test_citations_file_is_sorted_text():
    table = {"b/two.c": [{"text": "§2", "version": "OpenMP 5.2", "section": "2", "quote": "q"}],
             "a/one.f90": []}
    text = I.dump_citations(table)
    assert text.index('"a/one.f90"') < text.index('"b/two.c"') and text.endswith("\n")
    assert json.loads(text) == table
    # a citation's fields stay in the order the pages are written with (byte-identical pages)
    assert list(json.loads(text)["b/two.c"][0]) == ["text", "version", "section", "quote"]


def test_canuse_reads_the_committed_atoms(tmp_path, monkeypatch):
    p = tmp_path / "atoms.json.gz"
    p.write_bytes(I.dump_atoms(I.project_atoms(ATOMS, COLS)))
    monkeypatch.setattr(I, "ATOMS", p)
    (cu,) = D.canuse(recs=D.records([finding("t")]))["clause.defaultmap"]
    assert cu["cells"]["cce21|mi300a-u"]["state"] == "correct"
    assert cu["cells"]["cce21|mi300a-c"] == {"state": "unknown", "reason": "wrong value once in <home>/x"}


def test_a_missing_committed_input_names_the_generator(tmp_path, monkeypatch):
    monkeypatch.setattr(I, "ATOMS", tmp_path / "none.json.gz")
    monkeypatch.setattr(I, "CITATIONS", tmp_path / "none.json")
    with pytest.raises(I.SiteInputError, match="tools/site/site_inputs.py"):
        I.load_atoms()
    with pytest.raises(I.SiteInputError, match="tools/site/site_inputs.py"):
        I.load_citations()
    with pytest.raises(I.SiteInputError, match="new/finding.c"):
        I.citations_of("new/finding.c", {"old.f90": []})


def _manifest_files(pat: str) -> list[Path]:
    # a plain path is tested with stat, not glob's lstat: on a Tuolumne compute node
    # lstat of a freshly cloned file can fail where stat succeeds (Lustre)
    if glob.has_magic(pat):     # proposals (data/findings/proposed/) are unindexed: the build never reads them
        return [Path(h) for h in glob.glob(str(ROOT / pat), recursive=True)
                if not Path(h).is_relative_to(ROOT / "data" / "findings" / "proposed")]
    return [ROOT / pat] if (ROOT / pat).is_file() else []


def test_the_committed_inputs_exist_are_tracked_and_not_ignored():
    for pat in I.MANIFEST:
        assert _manifest_files(pat), f"{pat}: nothing in the tree"
    if not (ROOT / ".git").exists():
        pytest.skip("no git history here")
    files = [str(h.relative_to(ROOT)) for pat in I.MANIFEST for h in _manifest_files(pat) if h.is_file()]
    tracked = set(subprocess.run(["git", "ls-files", "-z", "--", *sorted(set(files))], cwd=ROOT,
                                 capture_output=True, text=True).stdout.split("\0"))
    untracked = sorted(set(files) - tracked)
    assert not untracked, f"the site build reads files git does not track: {untracked[:10]}"
    ignored = subprocess.run(["git", "check-ignore", "--", *sorted(set(files))], cwd=ROOT,
                             capture_output=True, text=True).stdout.split()
    assert not ignored, ignored[:10]


def _strings(path: Path):
    tree = ast.parse(path.read_text(), filename=str(path))
    return [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def test_the_site_builder_names_nothing_under_results():
    """The build reads committed data only: no code the build runs names results/ or
    the spec cache (the generator, tools/site/site_inputs.py, is the one that may)."""
    files = sorted((ROOT / "offload" / "engine" / "site").glob("*.py")) + [ROOT / "tools" / "site" / "site_build.py"]
    bad = [f"{p.relative_to(ROOT)}:{ln}: {s!r}" for p in files for ln, s in _strings(p)
           if s.startswith("results/") or "/results/" in s or "spec_cache" in s]
    bad += [f"{p.relative_to(ROOT)}: {m.group(0)!r}" for p in files
            for m in re.finditer(r'/\s*"results"', p.read_text())]
    assert not bad, bad


def test_the_regenerate_driver_checks_and_rebuilds_the_site_inputs(monkeypatch):
    R = _tool("regenerate")
    assert "site-inputs" in [n for n, _ in R.CHECKS]
    steps = [s[0] for s in R.STEPS]
    assert steps.index("dashboard") < steps.index("site-inputs")
    ran = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **k: ran.append(cmd))
    R.run_offline(log=lambda s: None)
    assert any(str(c[2]).endswith("tools/site/site_inputs.py") for c in ran)


def test_stale_committed_inputs_are_reported(tmp_path, monkeypatch):
    si = _tool("site_inputs")
    rows = I.project_atoms(ATOMS, COLS)
    cites = {"x.f90": [{"text": "§1", "version": "OpenMP 5.2", "section": "1", "quote": "q"}]}
    monkeypatch.setattr(si, "derive_atoms", lambda: rows)
    monkeypatch.setattr(si, "derive_citations", lambda: cites)
    atoms, cit = tmp_path / "atoms.json.gz", tmp_path / "citations.json"
    monkeypatch.setattr(I, "ATOMS", atoms)
    monkeypatch.setattr(I, "CITATIONS", cit)
    assert sorted(si.stale()) == ["atoms.json.gz", "citations.json"]
    si.write()
    assert si.stale() == []
    cit.write_text(I.dump_citations({"x.f90": []}))
    assert si.stale() == ["citations.json"]
    atoms.write_bytes(I.dump_atoms([]))
    assert sorted(si.stale()) == ["atoms.json.gz", "citations.json"]


def test_the_wingtip_lane_derives_the_inputs_and_builds_without_results():
    WO = _tool("wingtip_offline")
    step = WO.step("site-inputs")
    assert "results/dash/atoms.json" in step["inputs"] and "results/spec_cache" in step["inputs"]
    assert set(step["outputs"]) == {"site/inputs/atoms.json.gz", "site/inputs/citations.json"}
    assert WO.step("site-build")["inputs"] == []
    assert "results/dash/atoms.json" in WO.step("regen-check")["inputs"]


def test_no_internal_task_reference_reaches_the_built_site_data(built_site_data):
    tmp_path = built_site_data
    """Internal work-item numbers a reader of the public site
    cannot place. The findings' program headers and the committed atom notes still carry
    them (their history); the build rewrites them (offload.engine.site.scrub.unjargon) and stops
    on a phrasing it has no rule for. A new finding header that adds one fails here, naming
    the phrasing, until its rule and its case in tests/site/test_site_inputs.py are written."""
    files = sorted(tmp_path.rglob("*.json"))
    assert len(files) > 300
    hits = {f.name: re.findall(r"\bTask [0-9]+[a-z]?\b", f.read_text()) for f in files}
    assert {k: v for k, v in hits.items() if v} == {}
    # the notes of the unsupported cells that feature support shows, from the committed atoms
    notes = [v for r in I.load_atoms() for k, v in r.items() if k.startswith("note_")]
    blob = " ".join(json.dumps(p) for f in (tmp_path / "data" / "canuse").glob("[a-z].json")
                    for p in json.loads(f.read_text()).get("clause.allocate", []))
    assert "dynamic_allocators" in blob and "Task" not in blob


def test_no_internal_working_vocabulary_reaches_the_built_site_data(built_site_data):
    tmp_path = built_site_data
    """"The maintainer's runs", "fix", "a correction", "the maintainer withdrew": who ran
    what, not what was observed. The findings' headers keep them (their history); the build
    rewrites each known phrasing (offload.engine.site.scrub.unprocess). Any other use of the words
    fails here, naming the phrasing and its file, until a rule and its case in
    tests/site/test_site_inputs.py are written; an OpenMP "owner" of a lock, an AMD "Agent
    handle" or a spec quote is in the allow-list (offload.engine.site.scrub._ALLOWED)."""
    files = sorted(tmp_path.rglob("*.json"))
    assert len(files) > 300
    hits = {}
    for f in files:
        for s in D._strings(json.loads(f.read_text())):
            for w in S_scrub.process_words(s):
                hits.setdefault(f.name, set()).add(w)
    assert hits == {}
    # the committed sources still carry it: the check is not vacuous
    src = " ".join(p.read_text(errors="replace") for p in Path("data", "findings").rglob("*.f90"))
    assert "maintainer" in src.lower() or "fix round" in src.lower()


# ---- The public site never shows a user name, host or private path ---------------------------------------



from offload.engine.site import scrub as S

LEAKY = [
    "/p/lustre5/jdoe1/compliant/x.f90: error",
    "cd /g/g10/jdoe1/work && ftn x.f90",
    "/tmp/jdoe1-t44/harness_1a2b3c4d/x.f90:3: error",
    "/nethome/sjdoe3/compliant-offline/site/x.c",
    "ran on tuolumne1044", "ran on tioga38", "host wingtip-gpu3.cc.gatech.edu",
    "user sjdoe3 here", "jdoe1 there",
    "/fastscratch/sjdoe3/nvhpc/Linux_x86_64/26.9/compilers/bin/nvfortran",
]


@pytest.mark.parametrize("text", LEAKY)
def test_scrub_patterns(text):
    out = S.scrub(text)
    assert S.leaks(out) == [], out
    assert S.leaks(text) != []


def test_scrub_keeps_ordinary_text():
    t = "ftn-1510 ftn: ERROR in x.f90, line 3: v(s(3)) on tuolumne-class GPUs"
    assert S.scrub(t) == t and S.leaks(t) == []


def test_user_tmp_dirs_are_leaks_and_scrubbed():
    # A per-user build directory names its user
    for t in ("/tmp/jdoe_site/harness_1a2b3c4d/x.f90", "/tmp/jdoe-t44/GATEABCDEFGHIJKLMN/x.f90",
              "/tmp/jdoe_site/GATEABCDEFGHIJKLMN/repro.f90"):
        assert S.leaks(t), t
        assert S.leaks(S.scrub(t)) == [], S.scrub(t)
    assert S.leaks("<dir>/repro.f90") == [] and S.leaks("see /tmp for scratch") == []


REPO = "https://github.com/sjdoe/compliant"


def test_the_configured_repo_url_is_not_a_leak_but_the_name_elsewhere_is():
    # the public site links to its own repository, whose owner's handle is in the URL: allowed
    # when it is exactly the configured URL; the same name anywhere else stays a leak
    link = f"{REPO}/blob/master/data/findings/a.f90"
    assert S.leaks(link) == ["sjdoe"]
    assert S.leaks(link, allow=(REPO,)) == []
    assert S.leaks(f"{link} and sjdoe1 at /g/g10/jdoe1", allow=(REPO,)) != []
    assert S.leaks("https://github.com/sjdoe/other-repo", allow=(REPO,)) == ["sjdoe"]


def test_a_scratch_commit_names_no_one():
    # the Tioga copy commits as copy@localhost; "copy" in a page is not a leak
    log = "jdoe@lab.example.edu\n123+sjdoe@users.noreply.github.com\ncopy@localhost\nt@example.com\n"
    assert S.commit_names(log) == {"jdoe", "sjdoe"}


# --- internal task references ("Task 47", "since Task 16 ...") are not shown ---------------------------
# Readers of the public site cannot know what a "Task NN" is. Every phrasing the findings'
# program headers and the committed atom notes use has its own rewrite rule
# (offload.engine.site.scrub.unjargon); each is listed here with the text it must become.
TASK_PHRASINGS = [
    # reference with its connecting words dropped
    ("RUL-COMPILE-TIME (rulings.md, Task 31)", "RUL-COMPILE-TIME (rulings.md)"),
    ("offload.engine.prerun.check accepts it (Task 47 rerun: offload.engine.rules with the",
     "offload.engine.prerun.check accepts it (rerun: offload.engine.rules with the"),
    ("(offload.engine.prerun.check, Task 47 rerun, tools/x.jsonl)", "(offload.engine.prerun.check, rerun, tools/x.jsonl)"),
    ("(OpenMP 5.2, C11; Task 35 catalog widening). Do not edit.", "(OpenMP 5.2, C11; catalog widening). Do not edit."),
    ("re-categorised in Task 15 (was implementation_defined): x", "re-categorised (was implementation_defined): x"),
    ("the run ends (Task 35): the run", "the run ends: the run"),
    ("! Hand-reduced from b2-183-afar.f90 (Task 25).", "! Hand-reduced from b2-183-afar.f90."),
    ("(Task 47, errata item 2): regions", "(errata item 2): regions"),
    ("# Finding (Task 42, from the data/bench/fresh draft fresh-097): CCE rejects",
     "# Finding (from the data/bench/fresh draft fresh-097): CCE rejects"),
    ("# Finding (Task 49a): AFAR amdflang ignores", "# Finding: AFAR amdflang ignores"),
    ("# Finding (Task 39 fix round 2): NVHPC loses", "# Finding (fix round 2): NVHPC loses"),
    ("Host+device pattern (Task 24; minimized and re-verified in Task 25): two",
     "Host+device pattern (minimized and re-verified): two"),
    ("(wingtip/nv.jsonl (Task 42 review)",
     "(wingtip/nv.jsonl (review)"),
    ("(trace.out; Task 46 review, section 5)", "(trace.out; section 5)"),
    ("(CCE 19 and 21, Task 39 re-review 1; fix", "(CCE 19 and 21, re-review 1; fix"),
    ("claims.yaml; coordinator reading, Task 28 fix round 1). A", "claims.yaml; coordinator reading, fix round 1). A"),
    ("(Task 33: the reproduction gate's review queue, entries 86)", "(the reproduction gate's review queue, entries 86)"),
    # "the Task NN X" and "Task NN's X"
    ("the Task 46 pilot saw 104571", "the pilot saw 104571"),
    ("is the Task 46 reviewer's.", "is the reviewer's."),
    ("the Task 39 re-review counts", "the re-review counts"),
    ("a case of the Task 49b known-issues harvest", "a case of the known-issues harvest"),
    ("(the Task 24 program: four quarters)", "(the program: four quarters)"),
    ("(Task 45's four environments on gfx942 X0", "(the four environments on gfx942 X0"),
    ("the gate's reruns and Task 48's repeats", "the gate's reruns and the repeats"),
    ("(MFC's Task 38b CCE 21 objects", "(MFC's CCE 21 objects"),
    ("Before Task 45 the confirmer could not add -flto", "Previously the confirmer could not add -flto"),
    ("compiler witness (Task 27b cited gcc 13.3.1 -fopenmp;", "compiler witness (an earlier review cited gcc 13.3.1 -fopenmp;"),
    ("! Task 27b cited gfortran 13.3.1 -fopenmp as one", "! An earlier review cited gfortran 13.3.1 -fopenmp as one"),
    ("accept, cited in Task 28, is withdrawn", "accept, cited earlier, is withdrawn"),
    ("! - found by: Task 49a while reducing the CCE C", "! - found by: reducing the CCE C"),
    ("the reproducer that Task 39 reduced from the", "the reproducer reduced from the"),
    ("the same values; Task 47,\n! errata item 16). Each", "the same values;\n! errata item 16). Each"),
    ("num_teams(3); Task 39,\n! data/reports/r7.f90)", "num_teams(3);\n! data/reports/r7.f90)"),
    ("reduced by hand. Task 47 (Task 48's\n! errata): that rejection", "reduced by hand. Errata:\n! that rejection"),
    ("rejected because of it; since\n   Task 27b fix round 1 those C ports use enter(f)",
     "rejected because of it; now\n   those C ports use enter(f)"),
    # label at the start of a comment: the label goes, the sentence stays and starts with a capital
    ("// Task 24: an error directive with", "// An error directive with"),
    ("! Task 33: NVHPC 25.11, NVIDIA A100", "! NVHPC 25.11, NVIDIA A100"),
    ("! Task 41 (from the application corpus, Task 38b: PRK Fortran transpose",
     "! (from the application corpus: PRK Fortran transpose"),
    ("! Task 26 (copy mode for the whole catalog): AFAR", "! Copy mode for the whole catalog: AFAR"),
    ("// Task 48 (the reproduction gate's review queue): NVHPC", "// The reproduction gate's review queue: NVHPC"),
    ("! Task 47 (errata item 14): not reproducible", "! Errata item 14: not reproducible"),
    ("! Task 33 (2026-10-24): NVHPC 25.11", "! 2026-10-24: NVHPC 25.11"),
    ("! Task 26 fix round 1: AFAR reports", "! Fix round 1: AFAR reports"),
    ("! Task 48 fix round 1 (the reproduction gate's", "! Fix round 1 (the reproduction gate's"),
    ("/* Task 20 finding (C): dist_schedule(static)", "/* Finding (C): dist_schedule(static)"),
    ("! Task 28 finding: CCE 19, 20, 21 reject", "! Finding: CCE 19, 20, 21 reject"),
    ("! Task 28 finding (fix round 1): AFAR at", "! Finding (fix round 1): AFAR at"),
    ("Task 27b probe (tools/p.c, results/p.jsonl,", "Probe (tools/p.c, results/p.jsonl,"),
    ("! Task 39 audit, candidate 1: a scalar", "! Audit, candidate 1: a scalar"),
    ("/* Task 39 audit: craycc -flto", "/* Audit: craycc -flto"),
    ("! Task 27a. Expected: every thread", "! Expected: every thread"),
    ("! Task 27a. schedule(static, 4) on a parallel do", "! schedule(static, 4) on a parallel do"),
    ("! Task 41 (found while reducing MFC's CCE 20 crash", "! (found while reducing MFC's CCE 20 crash"),
    # the committed feature-support notes (site/inputs/atoms.json.gz)
    ("rejected (not counted: since Task 16 the allocate(t) program has requires dynamic_allocators (an "
     "allocate clause needs it); CCE 19 does not implement that requirement)",
     "rejected (not counted: the allocate(t) program has requires dynamic_allocators (an "
     "allocate clause needs it); CCE 19 does not implement that requirement)"),
    ("internal compiler error 'unhandled construct type'; Task 15 probes), so it measures the task construct",
     "internal compiler error 'unhandled construct type'), so it measures the task construct"),
]
TASK_REF = r"\bTask [0-9]+[a-z]?\b"


@pytest.mark.parametrize("before,after", TASK_PHRASINGS)
def test_task_references_are_rewritten_per_phrasing(before, after):
    out = S.unjargon(before)
    assert out == after
    assert re.search(TASK_REF, out) is None and S.task_refs(out) == []
    # the pages count a program's lines ("Program (47 lines)"): a rewrite never joins or splits lines
    assert out.count("\n") == before.count("\n")


def test_text_without_a_task_reference_is_unchanged():
    t = ("// A task construct, Task scheduling in 5.2 §12.5 p.1; tasks 1 and 2 (task 3)\n"
         "! fix round 1, the owner's ruling; Taskloop 4\n")
    assert S.unjargon(t) == t and S.task_refs(t) == []


def test_a_reference_no_rule_covers_is_reported_not_guessed():
    # a blind removal would break the grammar; the build and the test below name the phrasing
    t = "! mined with Task 61 for the second time"
    assert S.unjargon(t) == t and S.task_refs(t) == ["Task 61"]


def test_the_task_scrub_is_applied_to_every_string_of_the_issue_records():
    from offload.engine.site import data as D
    from tests.site.test_site import finding
    f = finding("t")
    f["source"] = "! Task 33: NVHPC 25.11\nprogram t\nend program t\n"
    (page,) = D.records([f])["pages"].values()
    assert page["source"].startswith("! NVHPC 25.11\n")
    f["source"] = "! mined with Task 61 for the second time\n"
    with pytest.raises(D.SiteDataError, match="Task 61"):
        D.records([f])


# ---- The public site shows what was observed and why, not who ran what -----------------------------------



PROCESS_PHRASINGS = [
    # the coordinator
    ("the failure is in AFAR's OpenMP offload path (the coordinator found its own\n"
     "//   device-malloc initialisation kernel, omp_dm_init_kernel, in the AFAR device image: results/x, no row here)",
     "the failure is in AFAR's OpenMP offload path (its own\n"
     "//   device-malloc initialisation kernel, omp_dm_init_kernel, is in the AFAR device image: results/x, no row here)"),
    ("claims.yaml; coordinator reading, fix round 1). A claimed form", "claims.yaml). A claimed form"),
    ("libc/src/__support/GPU/allocator.cpp; the coordinator's\n//   reading, not checked here): commit",
     "libc/src/__support/GPU/allocator.cpp; a\n//   reading, not checked here): commit"),
    ("that e9350dc is the change that removed them is the coordinator's reading.\n",
     "that e9350dc is the change that removed them is a reading.\n"),
    ("which, by the coordinator's\n//   reading, are the two fences", "which, by that\n//   reading, are the two fences"),
    ("which restores, by the coordinator's reading, half of", "which restores, by that reading, half of"),
    ("libc.a: the coordinator's `llvm-nm`,", "libc.a: the `llvm-nm`,"),
    ("-save-temps`; the coordinator's build, results/x", "-save-temps`; the build, results/x"),
    ("(the coordinator's HIP\n//     image, which uses", "(the HIP\n//     image, which uses"),
    ("(the coordinator's raw md5 792f0fb6446a", "(the raw md5 792f0fb6446a"),
    ("the coordinator's own runs and scripts are copied to", "the separate runs and scripts are copied to"),
    ("the\n//   coordinator's own runs, sources and scripts are in", "the\n//   separate runs, sources and scripts are in"),
    ("rel 0 of 10; the coordinator's runs: ctl 10 of 10 (1007 to 2052 bad)",
     "rel 0 of 10; the separate runs: ctl 10 of 10 (1007 to 2052 bad)"),
    ("(5 of 5 to 0 of 5 in the coordinator's runs).", "(5 of 5 to 0 of 5 in the separate runs)."),
    ("here and in the\n//   coordinator's runs): ctl", "here and in the\n//   separate runs): ctl"),
    ("the coordinator's runs of the Fortran program", "the separate runs of the Fortran program"),
    ("executables built by the coordinator against each   variant)", "executables built against each   variant)"),
    ("The whole-process wall time of the coordinator's C launches", "The whole-process wall time of the C launches"),
    ("the coordinator's rows, libcab/run_b_rows.txt,", "the separate runs' rows, libcab/run_b_rows.txt,"),
    ("rel 0 of 3; the coordinator also found ctl 3 of 3", "rel 0 of 3; the separate runs also found ctl 3 of 3"),
    ("Also from the coordinator (not row-backed: xcc.c,", "Also from the separate runs (not row-backed: xcc.c,"),
    ("launches damaged, coordinator (6 launches per row) and here (4):",
     "launches damaged, other runs (6 launches per row) and here (4):"),
    ("A tag test of the coordinator (xcc2.c:", "A tag test in the separate runs (xcc2.c:"),
    ("XCCs allocating            coordinator (launches per mask in brackets)     here (6 launches per mask)",
     "XCCs allocating            other runs  (launches per mask in brackets)     here (6 launches per mask)"),
    ("differ as expected (coordinator's isa-<v>\n//   directories:",
     "differ as expected (the separate runs' isa-<v>\n//   directories:"),
    ("fences as of 2026-11-02 (the coordinator's check, not repeated here); the path",
     "fences as of 2026-11-02 (checked earlier, not repeated here); the path"),
    ("md5 8e6e223241ab, 3873 lines, 0 differing lines; the\n//     coordinator's raw md5 792f0fb6446a on fixed paths",
     "md5 8e6e223241ab, 3873 lines, 0 differing lines; the\n//     raw md5 792f0fb6446a on fixed paths"),
    # the re-review: a later check
    ("gave needs_human (R22); the re-review counts the A100 results as the other-family witness",
     "gave needs_human (R22); a later check counts the A100 results as the other-family witness"),
    ("the re-review saw the first form fail on CCE 19 and 21)", "a later check saw the first form fail on CCE 19 and 21)"),
    ("is absent (re-review 1, readelf/nm of the executables, CCE 19.0.0", "is absent (a later check, readelf/nm of the executables, CCE 19.0.0"),
    ("read against the spec (audit and re-review); checked by scope", "read against the spec (audit and a later check); checked by scope"),
    ("); the re-review's runs are committed as", "); the later runs are committed as"),
    ("l= 0; the re-review's\n     timeouts are recorded", "l= 0; the later\n     timeouts are recorded"),
    ("runs-fix2-hang.jsonl; re-review: data/reports/fuzz-stress-audit/rereview-1-lp.jsonl",
     "runs-fix2-hang.jsonl; later check: data/reports/fuzz-stress-audit/rereview-1-lp.jsonl"),
    # a task reference that a line break splits
    ("data/reports/rulings.md Task\n! 27b fix round 2, written for the C programs). The C twin",
     "data/reports/rulings.md;\n! written for the C programs). The C twin"),
    # the owner
    ("(owner decision 2026-10-24; held since final review 3, N2):\n! the legality",
     "(held since 2026-10-24):\n! the legality"),
    ("compiler witness since the owner's 2026-10-23 ruling). AFAR", "compiler witness since the 2026-10-23 ruling). AFAR"),
    ("! An earlier review cited gfortran 13.3.1 -fopenmp as one; the owner withdrew\n"
     "! gfortran/gcc -fopenmp as offload legality witnesses on 2026-10-23 (f",
     "! An earlier review cited gfortran 13.3.1 -fopenmp as one;\n"
     "! gfortran/gcc -fopenmp were withdrawn as offload legality witnesses on 2026-10-23 (f"),
    ("as an independent witness; the owner withdrew gfortran/gcc\n! -fopenmp as offload legality witnesses on 2026-10-23",
     "as an independent witness; gfortran/gcc\n! -fopenmp were withdrawn as offload legality witnesses on 2026-10-23"),
    ("(A gfortran -fopenmp accept is no evidence: owner, 2026-10-23.) Expected:",
     "(A gfortran -fopenmp accept is no evidence: rule of 2026-10-23.) Expected:"),
    ("is withdrawn as evidence: owner, 2026-10-23.)", "is withdrawn as evidence: rule of 2026-10-23.)"),
    # the pilot, the reviewer
    ("varies from run to run (-1, 2; the pilot saw 104571, 82972; the review's 12 runs all printed",
     "varies from run to run (-1, 2; an earlier run saw 104571, 82972; the 12 later runs all printed"),
    ("(the generator's form, the pilot's 9 CCE cells, gfx942", "(the generator's form, the 9 CCE cells, gfx942"),
    ("(the pilot's rows); this file", "(the earlier rows); this file"),
    ("! - found by: the data-environment pilot, rule omp-target", "! - found by: the data-environment rule sample, rule omp-target"),
    ("!   This 22-line reproducer is the reviewer's.\n", "!   This is the 22-line reproducer.\n"),
    ("(fix round 2, after the findings\n! reviewer's runs; data/evidence/gate_probe/reduce/): the same",
     "(after further\n! runs; data/evidence/gate_probe/reduce/): the same"),
    ("! - Localization (fix round 2, after the findings reviewer's runs;\n", "! - Localization (after further runs;\n"),
    # the review queue
    ("// The reproduction gate's review queue: NVHPC 25.11 and 26.9 (nvc),", "// NVHPC 25.11 and 26.9 (nvc),"),
    ("! (the reproduction gate's review queue, entries 86 and 75, the", "! (the reproduction gate's flagged cases, entries 86 and 75, the"),
    ("! Fix round 1 (the reproduction gate's review queue, entries 81, 82,\n! 88, 90: the stress program",
     "! (the reproduction gate's flagged cases, entries 81, 82,\n! 88, 90: the stress program"),
    ("// Fix round 1 (the reproduction gate's review queue, entry 72: the\n",
     "// (the reproduction gate's flagged cases, entry 72: the\n"),
    ("! Fix round 1 (reducing the reproduction gate's review queue entry\n! 48, fuzz",
     "! (reducing the reproduction gate's flagged case entry\n! 48, fuzz"),
    ("! lastprivate cells of the reproduction gate's review queue\n! (data/reports/gate-queue.md:",
     "! lastprivate cells of the reproduction gate's flagged cases\n! (data/reports/gate-queue.md:"),
    # fix round N
    ("! Fix round 1: AFAR reports nothing present", "! AFAR reports nothing present"),
    ("// Fix round 2: the C form of x.f90.", "// The C form of x.f90."),
    ("// Fix round 1 (2026-10-24): rerun on 25.11", "// 2026-10-24: rerun on 25.11"),
    ("! Fix round 3 (the optional check): on target parallel for,", "! The optional check: on target parallel for,"),
    ("! Fix round 1 (review minor 1): reduced further by clause", "! Reduced further by clause"),
    ("! Shorter form (fix round 1, review minor 1; written by hand from", "! Shorter form (written by hand from"),
    ("! # Finding (fix round 2): NVHPC loses", "! # Finding: NVHPC loses"),
    ("/* # Finding (fix rounds 2 and 3): NVHPC accepts", "/* # Finding: NVHPC accepts"),
    ("! # Finding (fix round 1, from the data/bench/fresh draft fresh-106): CCE ICE",
     "! # Finding (from the data/bench/fresh draft fresh-106): CCE ICE"),
    ("// TIER finding (fix round 1; the compile fails either way, with", "// TIER finding (the compile fails either way, with"),
    ("! - oracle audit (fix round 1): run on AFAR", "! - oracle audit: run on AFAR"),
    ("is x1_oracle_blind (fix round 1).", "is x1_oracle_blind."),
    ("not run its last block (fix round 2: retitled; the file keeps", "not run its last block (retitled; the file keeps"),
    ("(3 of 3 builds on gfx942, fix round 1 log). Under", "(3 of 3 builds on gfx942, rerun log). Under"),
    ("is right. (Fix round 2.)\n", "is right.\n"),
    ("split in fix round 1: the static local", "split: the static local"),
    ("reproducer replaced in fix round 1: at OpenMP 5.1", "reproducer replaced: at OpenMP 5.1"),
    ("is no witness either (controller ruling R2, fix round 1): nvc also", "is no witness either (ruling R2): nvc also"),
    ("! Basis (fix round 2, N3): g appears", "! Basis: g appears"),
    ("on <host>. Fix round 2 reran it with a 600 s limit", "on <host>. A rerun with a 600 s limit"),
    ("fold). Fix round 1: if (teams: on)\n!   alone fails", "fold). Reduced further: if (teams: on)\n!   alone fails"),
    ("(data/reports/fuzz-stress.md, fix round 1). The installed", "(data/reports/fuzz-stress.md). The installed"),
    ("(CCE 19 and 21, re-review 1; CCE 19/20/21, fix round 2,\n//   runs-fix2.jsonl)",
     "(CCE 19 and 21, a rerun; CCE 19/20/21, a second rerun,\n//   runs-fix2.jsonl)"),
    ("Neither collapse nor simd is needed (fix round 1:\n! this 10-line program replaces",
     "Neither collapse nor simd is needed (\n! this 10-line program replaces"),
    # errata item N
    ("passes only with its long long item (errata item 24).\n", "passes only with its long long item.\n"),
    ("the same values;\n! errata item 16). Each team's mine", "the same values).\n! Each team's mine"),
    ("! - CCE 21.0.3 and 21.0.4 (errata item 2): regions 2 and 4 print", "! - CCE 21.0.3 and 21.0.4: regions 2 and 4 print"),
    ("is not copied back (errata item 1: the header\n! this file did not have).",
     "is not copied back (the header\n! this file did not have)."),
    ("! Errata item 14: not reproducible on the current install", "! Not reproducible on the current install"),
    ("   Errata item 10: three defects in one program", "   Three defects in one program"),
    ("! Errata item 17: hand reductions that drop", "! Hand reductions that drop"),
    ("reduced by hand. Errata:\n! that rejection without the crash was 1 compile in 157",
     "reduced by hand.\n! That rejection without the crash was 1 compile in 157"),
]


@pytest.mark.parametrize("before,after", PROCESS_PHRASINGS)
def test_process_vocabulary_is_rewritten_per_phrasing(before, after):
    out = S.unprocess(before)
    assert out == after
    assert S.unprocess(out) == out                            # a second pass changes nothing
    assert out.count("\n") == before.count("\n")              # the pages count a program's lines
    assert S.process_words(out) == []


def test_the_task_rules_and_the_process_rules_compose():
    raw = "! Task 48 fix round 1 (the reproduction gate's review queue, entries 81, 82,\n! 88, 90: x): CCE 20\n"
    assert S.public_text(raw) == "! (the reproduction gate's flagged cases, entries 81, 82,\n! 88, 90: x): CCE 20\n"
    raw = "claims.yaml; coordinator reading, Task 28 fix round 1). A claimed form"
    assert S.public_text(raw) == "claims.yaml). A claimed form"
    assert S.task_refs(S.public_text(raw)) == []


KEEP = [
    # an OpenMP "owner", a spec "review", an AMD "agent", a file name with "pilot": the rules match
    # the phrasing of the working vocabulary ("the owner withdrew", "owner decision", "the
    # coordinator's"), never the bare word
    "The owner thread of the lock is the thread that last acquired it; fix the round-robin order.\n",
    "\"The thread that owns the lock is the owner of the lock.\" (OpenMP 5.2 section 15.8)\n",
    "// a block's new owner (on another compute die) stores its data and the old owner's dirty\n",
    "// read the previous owner's XCC tag from the chunk before writing it\n",
    "// did not separate a previous\n//   owner on the same XCC from one on another XCC\n",
    "data/vendor/errata-for-findings.md item 23 and tools/notes/review/errata-applied.md\n",
    "Memory access fault by GPU node-4 (Agent handle: 0x794640) on address 0xbed000. Reason: Unknown.\n",
    "OFFLOAD ERROR: memory access fault by GPU 5 (agent 0x55d) at virtual address 0x7f\n",
    "atomicrmw or ... syncscope(\"agent\") monotonic; the agent-scope release emits buffer_wbl2; "
    "the agent release at line 1554\n",
    "the spec says: the implementation may review the clause list at each round of fixing\n",
    "see tools/notes/review/dataenv-pilot.md and results/dataenv/pilot_all/\n",
]


@pytest.mark.parametrize("text", KEEP)
def test_technical_uses_of_the_words_are_untouched(text):
    assert S.unprocess(text) == text
    assert S.public_text(text) == text
    assert S.process_words(text) == [], S.process_words(text)


def test_a_phrasing_without_a_rule_is_listed_by_the_word_list_not_rewritten():
    t = "! the coordinator re-ran it with a larger limit; Fix round 7 changed it\n"
    assert S.unprocess(t) == t
    assert sorted(S.process_words(t), key=str.lower) == ["coordinator", "Fix round"]


def test_the_vocabulary_scrub_is_applied_where_the_task_scrub_is():
    from offload.engine.site import data as D
    from tests.site.test_site import finding
    f = finding("t")
    f["source"] = "! Fix round 1: AFAR reports nothing\nprogram t\nend program t\n"
    (page,) = D.records([f])["pages"].values()
    assert page["source"].startswith("! AFAR reports nothing\n")


def test_canuse_has_a_cell_for_every_twin_of_a_compiler():
    """AFAR's MI250X, MI300X and MI350X cells come from its twins' atom keys (afar_g90,
    afar_mi300x, afar_mi350x) and sit under those GPUs' targets on AFAR's row."""
    cols = D._atom_columns()["afar"]
    assert ("afar_g90", "mi250x") in cols and ("afar_mi300x", "mi300x") in cols
    assert ("afar_mi350x", "mi350x") in cols
    atom = dict(ATOMS[0], afar_mi300x="wrong", afar_mi350x="ok")
    cells = D.canuse([atom])["clause.defaultmap"][0]["cells"]
    assert cells["afar|mi300x"] == {"state": "incorrect"}
    assert cells["afar|mi350x"] == {"state": "correct"}
