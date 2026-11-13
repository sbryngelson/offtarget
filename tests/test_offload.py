"""Tests of the offload command: can-use, the router, the data cache, the wheel install, issues, the device-offload scope and the usage scanner."""


# ---- offload can-use: which compilers and versions support a construct, from the site's data -------------

import json

import pytest

from offload import canuse, data

FEATURE = "clause.map.present"


@pytest.fixture(autouse=True)
def _data(offload_bundle, monkeypatch):
    monkeypatch.setenv("OFFLOAD_DATA", str(offload_bundle[0] / "data"))
    data.clear_cache()


def test_exact_id_wins_over_longer_names_containing_it():
    assert canuse.lookup("base.device.alloc_component") == ["base.device.alloc_component"]


def test_substring_unique():
    longest = max(data.load("canuse/index.json"), key=len)     # no other id can contain it
    assert canuse.lookup(longest[1:].upper()) == [longest]


def test_ambiguous_lists_candidates_and_exits_1(capsys):
    assert canuse.main(["clause.ma"]) == 1
    out = capsys.readouterr()
    assert "matches" in out.err and FEATURE in out.out


def test_no_match_exits_1_with_a_suggestion(capsys):
    assert canuse.main(["clause.mapp.present"]) == 1
    assert FEATURE in capsys.readouterr().err


def test_list_prints_every_feature(capsys):
    assert canuse.main(["--list"]) == 0
    lines = capsys.readouterr().out.split()
    assert lines == data.load("canuse/index.json") and len(lines) > 400


def test_json_is_the_site_data(capsys):
    assert canuse.main([FEATURE, "--format", "json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got == data.load(f"canuse/{FEATURE[0]}.json")[FEATURE]


def test_grid_maps_every_cell_to_its_compiler_label_and_target_name():
    cols = data.load("canuse/columns.json")
    labels = dict(cols["rows"])
    shorts = {t: n for ts in cols["targets"].values() for t, n in ts}
    row = data.load(f"canuse/{FEATURE[0]}.json")[FEATURE][0]
    grid = canuse.grid(row)
    assert set(grid) == set(labels.values())
    for key, cell in row["cells"].items():
        tc, target = key.split("|")
        assert grid[labels[tc]][shorts[target]] == cell["state"]
    n_a = [v for g in grid.values() for v in g.values() if v == "-"]
    assert n_a                                  # AMD compilers have no A100 column and the reverse
    # a GPU a compiler never ran on is n/a, not unknown: CCE has no MI300X runs, AFAR has
    for tc, label in cols["rows"]:
        for t, n in ((t, n) for ts in cols["targets"].values() for t, n in ts):
            assert (grid[label][n] == "-") == (t not in cols["runs"][tc]), (tc, t)
    assert "mi300x" in cols["runs"]["afar"] and "mi300x" not in cols["runs"]["cce19"]


def test_text_shows_each_compiler_target_and_state_of_the_grid(capsys):
    assert canuse.main([FEATURE]) == 0
    out = capsys.readouterr().out
    row = data.load(f"canuse/{FEATURE[0]}.json")[FEATURE][0]
    for label, cells in canuse.grid(row).items():
        line = next(l for l in out.splitlines() if l.startswith(label))
        for state in cells.values():
            assert state in line
    assert out.splitlines()[0].startswith(FEATURE)


def test_columns_match_what_the_site_generates():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    from offload.engine.site import columns
    cols = data.load("canuse/columns.json")
    assert cols == columns.canuse_columns()
    assert [r[0] for r in cols["rows"]][0] == "afar"


# ---- offload.cli: the router and its three commands ------------------------------------------------------

import subprocess
import sys
from pathlib import Path


from offload import cli

ROOT = Path(__file__).resolve().parent.parent


def test_version(capsys):
    assert cli.main(["--version"]) == 0
    # the version is the git tag at build time (pyproject.toml); a checkout that was not built says 0+unknown
    import re
    from offload import __version__
    assert capsys.readouterr().out.strip() == f"offload {__version__}"
    assert re.fullmatch(r"\d+(\.\d+)*((a|b|rc)\d+)?(\.post\d+)?(\.dev\d+)?(\+[a-z0-9.]+)?", __version__), __version__


def test_unknown_command_exits_2_with_the_list(capsys):
    assert cli.main(["nope"]) == 2
    err = capsys.readouterr().err
    assert "nope" in err and all(c in err for c in ("can-use", "issues"))
    assert "lint" not in cli.COMMANDS     # the linter is not a supported command


@pytest.mark.parametrize("command", ["can-use", "issues"])
def test_each_command_has_help(command, capsys):
    with pytest.raises(SystemExit) as e:
        cli.COMMANDS[command](["--help"])
    assert e.value.code == 0
    assert capsys.readouterr().out.startswith("usage: offload " + command)


def test_no_arguments_prints_usage_and_exits_2(capsys):
    assert cli.main([]) == 2
    assert "usage: offload" in capsys.readouterr().err


def test_module_form_matches_script_form():
    r = subprocess.run([sys.executable, "-m", "offload", "--version"], cwd=ROOT, capture_output=True, text=True,
                       env={"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin"})
    from offload import __version__
    assert r.returncode == 0 and r.stdout.strip() == f"offload {__version__}"


# ---- offload.data: where a checkout's built data is cached, and how the cache is published ---------------

import os
import stat

from offload import data


def test_cache_goes_beside_the_checkout_when_that_is_writable(tmp_path):
    assert data.cache_root(tmp_path) == tmp_path / ".offload-cache"


def test_cache_goes_to_the_user_cache_when_the_checkout_is_read_only(tmp_path, monkeypatch):
    root = tmp_path / "ro"
    root.mkdir()
    root.chmod(stat.S_IRUSR | stat.S_IXUSR)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    try:
        got = data.cache_root(root)
    finally:
        root.chmod(stat.S_IRWXU)
    if os.access(root, os.W_OK):
        return                                  # running as root: every directory is writable
    assert str(got).startswith(str(tmp_path / "xdg" / "offload"))


def test_publishing_over_an_existing_cache_keeps_the_first_and_is_readable_by_others(tmp_path):
    cache = tmp_path / "c" / "stamp"
    for n in (1, 2):
        tmp = tmp_path / f"t{n}"
        (tmp / "data").mkdir(parents=True)
        (tmp / "data" / "issues.json").write_text(str(n))
        data.publish(tmp, cache)
    assert (cache / "data" / "issues.json").read_text() == "1"
    assert stat.S_IMODE(cache.stat().st_mode) & 0o055 == 0o055


def test_publishing_over_a_broken_cache_replaces_it(tmp_path):
    """A cache directory without issues.json (a copy that lost its files) is replaced, not kept."""
    cache = tmp_path / "c" / "stamp"
    (cache / "data" / "canuse").mkdir(parents=True)
    tmp = tmp_path / "t"
    (tmp / "data").mkdir(parents=True)
    (tmp / "data" / "issues.json").write_text("new")
    data.publish(tmp, cache)
    assert (cache / "data" / "issues.json").read_text() == "new"
    assert not (cache / "data" / "canuse").exists()


def test_the_cache_stamp_moves_with_the_code_that_builds_the_data():
    """Every input of the cache stamp exists, and the site-data code is one of them."""
    from pathlib import Path
    root = Path(data.__file__).resolve().parent.parent
    assert all((root / rel).exists() for rel in data.INPUTS), data.INPUTS
    assert "offload/engine/site" in data.INPUTS and "data/findings" in data.INPUTS


# ---- A wheel built from the tracked tree installs into a fresh environment and the three commands work from an empty directory ----

import shutil
import zipfile


import where

SAMPLES = ["data/findings/afar-cce19-character-defaultmap.f90", "data/findings/cce-c-dist-schedule-segv.c",
           "data/findings/hecbench/controls/f16-ctl-float-array.c"]
SIZE_LIMIT = 25_000_000
# the version the test builds carry: the copied tree has no .git for hatch-vcs to read a tag from
VERSION = "0.1.0"


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def _build_install(work):
    work = Path(work)
    src, empty = work / "src", work / "empty"
    names = _run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT).stdout.split("\0")
    for n in filter(None, names):
        if (ROOT / n).is_file():
            (src / n).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / n, src / n)
    for s in SAMPLES:
        (empty / s).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / s, empty / s)
    env = {**os.environ, "SETUPTOOLS_SCM_PRETEND_VERSION": VERSION}
    r = _run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "-w", str(work / "wheels"),
              str(src)], env=env)
    assert r.returncode == 0, r.stderr[-1500:]
    wheel = next((work / "wheels").glob("offtarget-*.whl"))
    # the sdist, and a wheel built from it alone (what a release uploads)
    r = _run([sys.executable, "-c", f"from hatchling.build import build_sdist; build_sdist({str(work / 'sdist')!r})"],
             cwd=src, env=env)
    assert r.returncode == 0, r.stderr[-1500:]
    sdist = next((work / "sdist").glob("offtarget-*.tar.gz"))
    r = _run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "-w",
              str(work / "wheels-from-sdist"), str(sdist)], env=env)
    assert r.returncode == 0, r.stderr[-1500:]
    venv = work / "venv"
    assert _run([sys.executable, "-m", "venv", "--system-site-packages", str(venv)]).returncode == 0
    r = _run([str(venv / "bin" / "python"), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)])
    assert r.returncode == 0, r.stderr[-1500:]
    return None


@pytest.fixture(scope="session")
def installed():
    pytest.importorskip("hatchling")
    if _run([sys.executable, "-m", "pip", "--version"]).returncode:
        pytest.skip("pip is not available in this environment")
    work = where.built_once("offload_install", _build_install)
    wheel = next((work / "wheels").glob("offtarget-*.whl"))
    return {"wheel": wheel, "venv": work / "venv", "empty": work / "empty",
            "sdist": next((work / "sdist").glob("offtarget-*.tar.gz")),
            "sdist_wheel": next((work / "wheels-from-sdist").glob("offtarget-*.whl")),
            "env": {"PATH": "/usr/bin:/bin", "HOME": str(work)}}


def offload(installed, *args):
    return _run([str(installed["venv"] / "bin" / "offload"), *args], cwd=installed["empty"], env=installed["env"])


def test_wheel_is_under_the_size_limit(installed):
    assert installed["wheel"].stat().st_size < SIZE_LIMIT


def test_installed_data_is_under_the_size_limit(installed):
    r = _run([str(installed["venv"] / "bin" / "python"), "-c",
              "from offload.engine.root import ROOT, is_bundle; print(ROOT, is_bundle())"], cwd=installed["empty"],
             env=installed["env"])
    root, flag = r.stdout.split()
    assert flag == "True" and root.endswith("offload/_root")
    assert sum(f.stat().st_size for f in Path(root).rglob("*") if f.is_file()) < SIZE_LIMIT


def test_wheel_has_no_sealed_withheld_or_log_files(installed):
    names = zipfile.ZipFile(installed["wheel"]).namelist()
    bad = [n for n in names if "holdout" in n or n.endswith((".log", ".core", ".jsonl")) or "/results/" in n
           or "/corpus/" in n or "/hecbench" in n.split("_root/")[-1][:9] or "/fresh2/" in n]
    assert not bad, bad[:5]


def test_wheel_carries_the_licence_and_the_notices(installed):
    names = zipfile.ZipFile(installed["wheel"]).namelist()
    # PEP 639: the licence files are under .dist-info/licenses/
    assert any(n.endswith(".dist-info/licenses/LICENSE") for n in names)
    assert any(n.endswith("THIRD_PARTY_NOTICES.md") for n in names)


def _contents(wheel: Path) -> dict:
    z = zipfile.ZipFile(wheel)
    return {n: z.read(n) for n in z.namelist() if ".dist-info/" not in n}


def test_the_sdist_alone_builds_the_same_wheel(installed):
    """The sdist's include list (pyproject.toml) holds every file the build hook reads."""
    a, b = _contents(installed["wheel"]), _contents(installed["sdist_wheel"])
    assert sorted(a) == sorted(b)
    assert [n for n in a if a[n] != b[n]] == []


def test_the_sdist_holds_only_what_the_build_reads(installed):
    import tarfile
    names = [n.split("/", 1)[1] for n in tarfile.open(installed["sdist"]).getnames() if "/" in n]
    tops = {n.split("/")[0] for n in names}
    assert tops <= {"offload", "catalog", "data", "site", "tools", "hatch_build.py", "pyproject.toml", "README.md",
                    "LICENSE", "THIRD_PARTY_NOTICES.md", "PKG-INFO", ".gitignore"}, sorted(tops)
    bad = [n for n in names if n.startswith(("data/reports", "data/findings/proposed", "tests/", ".github"))
           or "holdout" in n or "sealed" in n or "/drafts" in n]
    assert not bad, bad[:5]


def test_version_and_help_work_installed(installed):
    assert offload(installed, "--version").stdout.strip() == f"offload {VERSION}"
    for c in ("can-use", "issues"):
        assert offload(installed, c, "--help").stdout.startswith(f"usage: offload {c}")


def test_installed_can_use_and_issues_match_the_checkout(installed, offload_bundle):
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(ROOT), "OFFLOAD_DATA": str(offload_bundle[0] / "data")}
    for args in (["can-use", "clause.map.present"], ["issues", "--show", "nvhpc-c-map-present-ignored"],
                 ["issues", "map", "present"]):
        here = _run([sys.executable, "-m", "offload", *args], cwd=ROOT, env=env)
        there = offload(installed, *args)
        assert here.returncode == there.returncode == 0, (args, there.stderr[-300:])
        assert here.stdout == there.stdout, args


# ---- offload issues: search the known compiler problems, show one with its reproducer --------------------



from offload.engine.root import ROOT as ROOT_5
from offload import data, issues

SAMPLE = "nvhpc-c-map-present-ignored"




def _all():
    return data.load("issues.json")["issues"]


def test_query_words_all_match_somewhere_in_the_issue():
    hits = issues.search("map present")
    assert SAMPLE in {i["id"] for i in hits}
    for i in hits:
        text = " ".join([i["id"], i["title"], i["search"], " ".join(i["constructs"])]).lower()
        assert "map" in text and "present" in text


def test_empty_query_lists_everything():
    assert len(issues.search("")) == len(_all()) > 300


def test_compiler_filter_takes_a_family_or_a_toolchain():
    nv = issues.search("", compiler="nvhpc")
    assert nv and all(any(t.startswith("nvhpc") for t in i["versions_failing"]) for i in nv)
    assert {i["id"] for i in issues.search("", compiler="nvhpc269")} <= {i["id"] for i in nv}
    with pytest.raises(ValueError):
        issues.search("", compiler="nosuchcompiler")


def test_the_legality_filter_and_the_list_say_the_verdict(capsys):
    contested = issues.search("", legality="contested")
    assert contested and all(i["legality"] == "contested" for i in contested)
    assert {i["legality"] for i in issues.search("")} <= {"confirmed", "supported", "contested", "unconfirmed"}
    assert issues.main(["--legality", "contested"]) == 0
    assert contested[0]["page"] in capsys.readouterr().out


def test_kind_and_status_filters():
    assert all(i["kind"] == "unsupported" for i in issues.search("", kind="unsupported"))
    assert all(i["status"] == "fixed" for i in issues.search("", status="fixed"))
    link = issues.search("", stage="link")
    assert link and all(i["stage"] == "link" for i in link)
    assert {i["stage"] for i in issues.search("")} == {"compile", "link", "run"}
    assert "refused at link time" in issues.show(link[0]["page"]) or "at link time" in issues.show(link[0]["page"])


def test_show_prints_the_reproducer_verbatim_with_the_compilers_and_the_spec():
    out = issues.show(SAMPLE)
    src = next((ROOT_5 / "data" / "findings").glob(SAMPLE + ".*")).read_text()
    assert src in out
    rec = next(i for i in _all() if i["id"] == SAMPLE)
    assert rec["title"] in out and "NVHPC 25.11" in out and rec["specs"][0] in out


def test_show_accepts_a_finding_path_and_a_unique_part_of_an_id():
    full = issues.show("hecbench--gcc-c-swar-popcount-assembler-error")
    assert issues.show("data/findings/hecbench/gcc-c-swar-popcount-assembler-error.c") == full
    assert issues.show("swar-popcount") == full and full.startswith("hecbench--gcc-c-swar-popcount")


def test_unknown_id_exits_1_with_a_suggestion(capsys):
    assert issues.main(["--show", "nvhpc-c-map-present-ignorred"]) == 1
    assert SAMPLE in capsys.readouterr().err


def test_list_ends_with_the_count(capsys):
    assert issues.main(["map", "present"]) == 0
    last = capsys.readouterr().out.strip().splitlines()[-1]
    assert last == f"{len(issues.search('map present'))} of {len(_all())} issues"


def test_no_hits_exits_1(capsys):
    assert issues.main(["zzzznothing"]) == 1


def test_json_list_and_show(capsys):
    assert issues.main(["map", "present", "--format", "json"]) == 0
    assert {i["id"] for i in json.loads(capsys.readouterr().out)} == {i["id"] for i in issues.search("map present")}
    assert issues.main(["--show", SAMPLE, "--format", "json"]) == 0
    rec = json.loads(capsys.readouterr().out)
    assert rec["id"] == SAMPLE and "map(present" in rec["source"]


def test_an_issue_without_a_failing_version_has_no_stray_separator(capsys):
    assert issues.main(["fuzz/698-afar"]) == 0
    out = capsys.readouterr().out
    assert "[;" not in out and "[crashes or aborts at run time]" in out


# ---- Device offload only (offload.engine.offload_scope) -----------------------------------------------

import re
from functools import lru_cache


from offload.engine import gen
from offload.engine.catalog import (out_of_scope, out_of_scope_atoms,
                                slice_atoms)
from offload.engine.offload_scope import (ScopeError, check, host_constructs,
                                      host_execution, scope_of)

F_VERSIONS = (50, 52, 60)
C_VERSIONS = (52, 60)


@lru_cache(maxsize=None)
def f_programs(version):
    return tuple(gen.generate(slice_atoms(version), version))


@lru_cache(maxsize=None)
def c_programs(version):
    from offload.engine.c_gen import all_c_programs
    return tuple(all_c_programs(version))


def _all_6():
    for v in F_VERSIONS + (34,):
        yield from f_programs(v)
    for v in C_VERSIONS:
        yield from c_programs(v)


def test_every_catalog_program_is_device_offload():
    """Fortran 5.0/5.2/6.0, C 5.2/6.0 and OpenACC 3.4, legal and illegal:
    a host construct only in a declared host+device pattern."""
    bad = {}
    for p in _all_6():
        try:
            check(p)
        except ScopeError as err:
            bad[p.id] = str(err)
        found = host_constructs(p.source, int(p.id[3:5]),
                                "c" if p.lang == "c" else "f90")
        if (p.scope == "host+device") != bool(found):
            bad[p.id] = f"scope {p.scope} with host constructs {found}"
    assert bad == {}


def test_host_device_patterns():
    """Each pattern program follows its atom's device-only program, says
    its realistic use, is judged on the device (ran_on_host from the
    target region) and is outside the mutation audit."""
    from offload.engine.mutate import audit_programs
    for v in F_VERSIONS:
        progs = f_programs(v)
        ids = [p.id for p in progs]
        hd = [p for p in progs if p.scope == "host+device"]
        assert {p.primary_atom for p in hd} == (
            set(gen.HOST_DEVICE) & set(slice_atoms(v)))
        for p in hd:
            assert p.id == gen.hostdev_id(p.primary_atom, v)
            assert ids.index(p.id) == ids.index(gen._pid(p.primary_atom,
                                                         v)) + 1
            scope, use = scope_of(p.source)
            assert scope == "host+device" and len(use) > 40
            assert "omp_is_initial_device()" in p.source
        assert not [p for p in audit_programs(v) if p.scope != "device"]
    for v in C_VERSIONS:
        hd = [p for p in c_programs(v) if p.scope == "host+device"]
        assert len(hd) == len([p for p in f_programs(v)
                               if p.scope == "host+device"])
        assert all(p.id.endswith("-hostdev") for p in hd)


@pytest.mark.parametrize("version", F_VERSIONS)
def test_one_device_program_per_atom(version):
    legal = [p for p in f_programs(version) if p.legal
             and p.scope == "device"]
    assert len({p.primary_atom for p in legal}) == len(legal)


H = "program p\n  use omp_lib\n  implicit none\n  integer :: i, a(8)\n"


def _f(body, mod=""):
    return mod + H + body + "end program p\n"


@pytest.mark.parametrize("body, names", [
    ("  !$omp parallel do\n  do i = 1, 8\n    a(i) = i\n  end do\n"
     "  !$omp end parallel do\n", ["parallel do"]),
    ("  !$omp parallel\n  !$omp single\n  !$omp task depend(out: a)\n"
     "  a = 1\n  !$omp end task\n  !$omp end single\n  !$omp end parallel\n",
     ["parallel", "single", "task"]),
    ("  !$omp taskwait\n", ["taskwait"]),
    ("  !$omp target map(tofrom: a)\n  !$omp parallel do\n  do i = 1, 8\n"
     "    a(i) = i\n  end do\n  !$omp end parallel do\n  !$omp end target\n",
     []),
    ("  !$omp target data map(tofrom: a)\n  !$omp target update to(a)\n"
     "  !$omp end target data\n", []),
    ("  !$omp target nowait map(tofrom: a)\n  a(1) = 1\n"
     "  !$omp end target\n  !$omp taskwait\n", []),
])
def test_host_constructs_fortran(body, names):
    assert [h.directive for h in host_constructs(_f(body), 52)] == names


def test_declare_target_procedure_is_device_code():
    mod = ("module m\n  implicit none\ncontains\n  subroutine w(n)\n"
           "    !$omp declare target\n    integer :: n, i\n"
           "    !$omp loop bind(thread)\n    do i = 1, n\n    end do\n"
           "    !$omp end loop\n  end subroutine w\n"
           "  subroutine h(n)\n    integer :: n, i\n"
           "    !$omp parallel do\n    do i = 1, n\n    end do\n"
           "    !$omp end parallel do\n  end subroutine h\n"
           "end module m\n")
    found = host_constructs(_f("  i = 0\n", mod), 52)
    assert [h.directive for h in found] == ["parallel do"]


def test_host_constructs_c():
    src = ("#include <omp.h>\nint a[8];\n#pragma omp begin declare target\n"
           "void w(void) {\n  #pragma omp loop bind(thread)\n"
           "  for (int i = 0; i < 8; i++) a[i] = i;\n}\n"
           "#pragma omp end declare target\nint main(void) {\n"
           "  #pragma omp parallel for\n  for (int i = 0; i < 8; i++) "
           "a[i] = i;\n  #pragma omp target map(tofrom: a)\n  w();\n"
           "  return 0;\n}\n")
    assert [h.directive for h in host_constructs(src, 52, "c")] == \
        ["parallel for"]


def test_host_constructs_openacc():
    src = ("program p\n  use openacc\n  implicit none\n  integer :: i, a(8)\n"
           "  !$acc data copy(a)\n  !$acc update device(a)\n"
           "  !$acc parallel loop\n  do i = 1, 8\n    a(i) = i\n  end do\n"
           "  !$acc end data\n  !$acc atomic update\n  a(1) = a(1) + 1\n"
           "end program p\n")
    assert [h.directive for h in host_constructs(src, 34)] == ["atomic"]


@pytest.mark.parametrize("text", [
    "!$omp target if(.false.) map(tofrom: a)",
    "#pragma omp target if(0)",
    "!$acc serial self(.true.)",
    "!$omp declare target enter(g) device_type(host)"])
def test_host_execution_clauses(text):
    assert host_execution(text)


@pytest.mark.needs_spec
def test_out_of_scope_atoms_quote_the_spec_and_leave_the_slice():
    from offload.engine import spec_text
    vtext = {50: "5.0", 52: "5.2", 60: "6.0", 34: "acc3.4"}
    n = 0
    for model in ("omp", "acc"):
        for atom, e in out_of_scope(model).items():
            assert e["reason"].strip() and e["status"] == "provisional"
            for v in e["versions"]:
                for lang in e["langs"]:
                    whole = slice_atoms(v, lang=lang, in_scope=False)
                    assert atom in whole, (atom, v, lang)
                    assert atom not in slice_atoms(v, lang=lang)
                    assert atom in out_of_scope_atoms(v, lang)
                c = e["spec"][v]
                m = re.fullmatch(r"(?:OpenMP|OpenACC) [\d.]+ §([\d.]+), "
                                 r"p\.(\d+)", c["cite"])
                assert m, c
                secs = [x for x in spec_text.sections(vtext[v]).values()
                        if x.number == m.group(1)]
                assert len(secs) == 1, c
                assert secs[0].first_page <= int(m.group(2)) <= \
                    secs[0].last_page, c
                assert re.sub(r"\s+", "", c["quote"]) in \
                    re.sub(r"\s+", "", secs[0].text), c
                n += 1
    assert n >= 8


def test_no_program_for_an_out_of_scope_atom():
    for v in F_VERSIONS + (34,):
        gone = set(out_of_scope_atoms(v))
        assert gone and not {p.primary_atom for p in f_programs(v)} & gone
    for v in C_VERSIONS:
        gone = set(out_of_scope_atoms(v, "c"))
        assert not {p.primary_atom for p in c_programs(v)} & gone


def test_fuzz_programs_stay_device_offload():
    from offload.engine import fuzz
    for base in ((), ("types",), ("derived",), ("alloc",), ("declare",),
                 ("multitu",)):
        for seed in range(1, 9):
            p = fuzz.generate(seed, "fuzz-3", base)
            assert fuzz.check_scope(p.source) is None, (base, seed)
    for seed in range(1, 9):
        assert fuzz.check_scope(fuzz.generate(seed, "fuzz-1").source) is None
    host = _f("  !$omp parallel do\n  do i = 1, 8\n    a(i) = i\n  end do\n"
              "  !$omp end parallel do\n")
    assert fuzz.check_scope(host).startswith("parallel do")


_DEVICE = re.compile(
    # OpenMP_VV 6.0 tests write "# pragma omp" (a space after #)
    r"#\s*pragma\s+omp\s+(?:target|(?:begin\s+)?declare\s+target)"
    r"|!\$omp\s+(?:target|declare\s+target)"
    r"|\bomp_(?:target_\w+|get_num_devices|get_default_device|"
    r"is_initial_device|get_device_num|set_default_device|"
    r"get_initial_device)\b", re.I)


@pytest.mark.needs_corpus("omp_vv")
@pytest.mark.parametrize("lang", ["f90", "c"])
def test_ompvv_baseline_tests_are_device_tests(lang):
    """Regression: every omp_vv test the baseline selects uses a
    target/device construct or a device API routine; the suite's host-only
    tests stay out (not selected)."""
    from offload.engine.baseline import CORPUS, select_files
    rows = select_files(ROOT / "data" / "index" / "corpus_index.csv", ["omp_vv"],
                        lang)
    assert rows
    bad = [r["path"] for r in rows if not _DEVICE.search(
        (CORPUS / "omp_vv" / r["path"]).read_text(errors="replace"))]
    assert bad == []


@pytest.mark.parametrize("version", F_VERSIONS)
def test_multithreaded_offload_maps_whole_arrays_once(version):
    """Sections of one array mapped by concurrent target
    constructs leave the result unspecified once two sections from
    different constructs are present when a third maps the array (the
    target region references the whole array, an implicit map; 5.2 §5.8.3
    p.155, 6.0 p.286). The multi-threaded programs map a and b whole once,
    before the host parallel region; the threads' target constructs map
    no array section."""
    for atom, nowait in (("omp.directive.target", False),
                         ("omp.clause.nowait", True)):
        (p,) = [q for q in f_programs(version)
                if q.id == gen.hostdev_id(atom, version)]
        lines = [x.strip().lower() for x in p.source.splitlines()]
        par = next(i for i, x in enumerate(lines)
                   if x.startswith("!$omp parallel do"))
        end = next(i for i, x in enumerate(lines)
                   if x.startswith("!$omp end parallel do"))
        assert any(x.startswith("!$omp target enter data") and "map(" in x
                   for x in lines[:par])
        assert any(x.startswith("!$omp target exit data") and "from:" in x
                   for x in lines[end:])
        inside = [x for x in lines[par:end] if x.startswith("!$omp target")
                  and not x.startswith("!$omp target update")]
        assert inside and not any("map(" in x for x in inside), inside
        assert any(x.startswith("!$omp target") and "nowait" in x
                   for x in inside) == nowait
        if not nowait:
            ups = [x for x in lines[par:end]
                   if x.startswith("!$omp target update")]
            assert any("to(a(lo:hi))" in x for x in ups)
            assert any("from(b(lo:hi))" in x for x in ups)


# ---- The usage scanner (offload.engine.usage) and the profile's maxima --------------------------------


from offload.engine import fuzz_profile as FP
from offload.engine import fuzz_steer as FS
from offload.engine import usage as U

F90 = """\
module m_glob
  implicit none
  type :: inner_t
    integer :: a
    real, allocatable :: v(:)
  end type inner_t
  type :: outer_t
    type(inner_t) :: c
    integer, pointer :: p(:)
  contains
    procedure, nopass :: f => outer_f
  end type outer_t
  type, extends(outer_t) :: ext_t
    integer :: z
  end type ext_t
  integer :: gv1, gv2, gv3
  real :: garr(10)
  !$omp declare target(gv1, gv2)
contains
  subroutine dev(x, y, z, w)
    !$omp declare target
    integer, intent(in) :: x
    integer, value :: y
    integer, intent(in), optional :: z
    integer, intent(out) :: w
    integer :: l1, l2
    real :: l3(4)
    l1 = x
    w = l1 + y
  end subroutine dev
  integer function outer_f(i)
    integer, intent(in) :: i
    outer_f = i
  end function outer_f
end module m_glob

program p
  use m_glob, only: gv1, gv2, dev
  implicit none
  integer :: i, j, n, s, t, q(100, 100)
  n = 10
  s = 3
  !$omp target teams distribute parallel do collapse(2) private(t, &
  !$omp& j) map(tofrom: q(1:n, 1:n)) reduction(+: s)
  do i = 1, n
    do j = 1, n
      t = i + n + gv1
      call dev(i, j, w=t)
      q(i, j) = t + s
    end do
  end do
  !$omp end target teams distribute parallel do
end program p
"""

C = """\
#include <stdio.h>
struct inner { int a; double *v; };
struct outer { struct inner in; int *p; };
#pragma omp declare target
int dev(int x, int y, int z) { int l = x + y; return l + z; }
#pragma omp end declare target
int main(void) {
  int n = 10, s = 0;
  int a[100];
  #pragma omp target teams distribute parallel for \\
      map(tofrom: a[0:n]) reduction(+: s) private(n)
  for (int i = 0; i < 10; i++) {
    for (int j = 0; j < 2; j++) { a[i] = dev(i, j, 1); }
  }
  return 0;
}
"""


def test_directive_parser():
    d = U.parse_directive("target teams distribute parallel do collapse(3)"
                          " private(i, j, k) map(always, tofrom: x(1:n), y)",
                          "omp")
    assert d.name == "target teams distribute parallel do"
    assert [(c, n) for c, _, n, _ in d.clauses] == [
        ("collapse", 1), ("private", 3), ("map", 2)]
    assert U.parse_directive("parallel loop gang vector private(a)",
                             "acc").name == "parallel loop"
    assert U.parse_directive("routine(foo) seq", "acc").name == "routine"
    assert U.parse_directive("atomic update", "omp").name == "atomic update"
    assert U.parse_directive("declare target(a, b)", "omp").clauses[0][2] \
        == 2


def test_fortran_scan_hand_counts():
    fs = U.scan_fortran(F90, "x.f90")
    assert len(fs.regions) == 1
    r = fs.regions[0]
    assert r.loop_depth == 2 and r.collapse == 2
    assert {"dir:target", "dir:teams", "dir:distribute", "dir:parallel",
            "dir:do", "clause:private", "clause:reduction", "red:+",
            "map:tofrom", "map:section", "base:call",
            "clause:collapse2"} <= r.features
    # n is referenced without a clause; gv1 is a module variable
    assert r.implicit_scalars == 1
    assert "gv1" in r.idents
    priv = [d for d in fs.directives if d.name.startswith("target")][0]
    assert priv.lines == 2 and dict((c, n) for c, _, n, _ in
                                    priv.clauses)["private"] == 2
    dev = [p for p in fs.procs if p.name == "dev"][0]
    assert dev.device and dev.nargs == 4 and dev.nlocals == 3
    assert dev.optional == 1 and dev.value == 1
    assert fs.modules["m_glob"]["vars"] == 4
    assert fs.modules["m_glob"]["device_vars"] == 2
    assert fs.use_only == [3]
    prof = U.profile_files([fs])
    assert prof["type_nesting_depth"]["max"] == 2
    assert prof["extends_depth"]["max"] == 1
    assert prof["nopass_bindings"] == 1
    assert prof["region_module_scalars"]["max"] == 1
    assert prof["device_call_depth"] == 1


def test_c_scan_hand_counts():
    fs = U.scan_c(C, "x.c")
    assert len(fs.regions) == 1
    r = fs.regions[0]
    assert r.loop_depth == 2
    d = [d for d in fs.directives if d.name.startswith("target")][0]
    assert d.lines == 2
    assert {"clause:reduction", "map:tofrom", "base:call"} <= r.features
    dev = [p for p in fs.procs if p.name == "dev"][0]
    assert dev.device and dev.nargs == 3
    assert fs.types["outer"].children == {"inner"}


def test_preprocessor_keeps_the_live_branch():
    t = "#if defined(A)\nx = 1\n#else\nx = 2\n#endif\n"
    assert U.preprocess(t, ["A"]).split("\n")[1] == "x = 1"
    assert U.preprocess(t, []).split("\n")[3] == "x = 2"


def test_maxima_and_sweeps():
    prof = {"codes": {
        "a": {"list_length": {"private": {"max": 159}}, "regions": 10,
              "offload_files": 2},
        "b": {"list_length": {"private": {"max": 20}}, "regions": 3,
              "offload_files": 1}}}
    mx = FP.maxima(prof)
    assert mx["private"] == {"max": 159, "where": "a"}
    sw = FP.sweeps(mx)["private"]
    assert {1, 8, 64, 159, 318, 636, 1590} <= set(sw)


def test_steer_weights_follow_the_profile():
    prof = {"real_frequencies": {"regions": 100, "features": {
        "dir:teams": 0.9, "clause:nowait": 0.01}},
        "generator_frequencies": {"regions": 100, "features": {
            "dir:teams": 0.3, "clause:nowait": 0.4}},
        "boost_pairs": [{"pair": ["dir:teams", "clause:private"]}]}
    st = FS.Steer(prof)
    assert st.weight([{"dir:teams"}]) > st.weight([{"clause:nowait"}])
    assert st.weight([{"dir:teams", "clause:private"}]) > \
        st.weight([{"dir:teams"}])
    fb = FS.Feedback()
    fb.update("cce", "cce|ice|x", {"dir:teams", "clause:private"})
    assert fb.multiplier("cce", {"dir:teams", "clause:private"}) == 2.0
    assert fb.multiplier("afar", {"dir:teams", "clause:private"}) == 1.0
    for _ in range(FS.SATURATED - 1):
        fb.update("cce", "cce|ice|x", {"dir:teams", "clause:private"})
    assert fb.multiplier("cce", {"dir:teams", "clause:private"}) == \
        pytest.approx(0.6)


def test_steer_choice_replays():
    prof = {"real_frequencies": {"regions": 10, "features": {
        "dir:teams": 0.9}}, "generator_frequencies": {
        "regions": 10, "features": {"dir:teams": 0.3}}}
    st = FS.Steer(prof)
    a = st.choose(5, "afar", k=4)
    b = st.choose(5, "afar", k=4)
    assert a == b
    assert FS.SEED_BASE + 20 <= a["seed"] < FS.SEED_BASE + 24
