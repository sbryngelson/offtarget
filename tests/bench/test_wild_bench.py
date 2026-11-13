"""The in-the-wild bug benchmark (data/bench/wild/): every case file
names its source URL and parses as a program of its language, the runner's
outcome classes, and the dev / holdout split."""
import re
import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]

import wild_bench as WB  # noqa: E402

CASES = WB.case_files()


@pytest.mark.needs_bench("wild/cases.yaml", "wild/split.yaml")
def test_cases_exist_and_match_metadata():
    meta = yaml.safe_load((WB.BENCH / "cases.yaml").read_text())
    ids = {c["id"] for c in meta["cases"]}
    files = {p.stem for p in CASES}
    assert len(files) >= 80
    assert ids == files
    for c in meta["cases"]:
        for k in ("url", "project", "date", "compiler", "family", "failure",
                  "reported", "status", "lang", "model", "license", "file"):
            assert c.get(k), (c["id"], k)
        assert c["lang"] in ("f90", "c") and c["model"] in ("omp", "acc")
        assert (WB.BENCH / c["file"]).suffix == (".c" if c["lang"] == "c"
                                                 else ".f90")
    assert all(e["reason"] for e in meta["excluded"])


@pytest.mark.parametrize("path", CASES, ids=[p.stem for p in CASES])
def test_case_header(path):
    h = WB.header(path)
    assert h["wild case"] == path.stem
    assert re.match(r"https?://", h["source"])
    assert h["edits"], "every case lists its edits (or 'none')"
    # a device-offload directive is in the program
    assert re.search(r"(?im)^\s*(!\$(omp|acc)|#\s*pragma\s+(omp|acc))\s+"
                     r"(\w+\s+)*?(target|declare|parallel|kernels|serial|"
                     r"data|enter|update|routine|teams|metadirective)", path.read_text())


# legal Fortran the syntax checker (gfortran 13) does not parse
GFORTRAN_GAP = re.compile(r"(?im)^\s*do\s+concurrent\s*\(\s*integer\s*(\([^)]*\))?\s*::")


@pytest.mark.gfortran
@pytest.mark.parametrize("path", CASES, ids=[p.stem for p in CASES])
def test_case_parses(path):
    tool = "gcc" if path.suffix == ".c" else "gfortran"
    if shutil.which(tool) is None:
        pytest.skip(f"{tool} not found")
    ok, err = WB.parse_one(path)
    if not ok and GFORTRAN_GAP.search(path.read_text()) and "Syntax error in DO statement" in err:
        pytest.skip("this gfortran rejects a type-spec in a DO CONCURRENT header "
                    "(do concurrent (integer :: k = ...), Fortran 2008 R818)")
    assert ok, err


def test_classify():
    run = lambda o, r="": {"outcome": o, "reason": r}  # noqa: E731
    assert WB.classify([run("run_error", "no output")] * 2, "") == \
        ("unobservable", "no output")
    assert WB.classify([run("run_error", "no output")], "x")[0] == \
        "wrong_answer"
    oc, why = WB.classify([run("correct_on_device"), run("crash", "SIGSEGV")],
                          "x")
    assert oc == "crash" and why.startswith("flaky:")
    assert WB.classify([run("rejected", "diagnostic: e")], "")[0] == \
        "rejected"


# --- The dev / holdout split --------------------------------------------

import wild_split as WSP  # noqa: E402


def test_split_is_deterministic_stratified_and_balanced():
    cases = [{"id": f"c{i}", "project": "p" if i < 7 else "q",
              "model": "omp" if i % 3 else "acc"} for i in range(20)]
    a = WSP.split(cases, "salt-x")
    assert a == WSP.split(list(reversed(cases)), "salt-x")
    assert set(a) == {c["id"] for c in cases}
    assert set(a.values()) == {"dev", "holdout"}
    n_dev = sum(v == "dev" for v in a.values())
    assert abs(n_dev - (20 - n_dev)) <= 1
    # every stratum of two or more cases has both halves
    strata = {}
    for c in cases:
        strata.setdefault((c["project"], c["model"]), []).append(a[c["id"]])
    for v in strata.values():
        if len(v) >= 2:
            assert {"dev", "holdout"} <= set(v)
    assert WSP.split(cases, "other-salt") != a


@pytest.mark.needs_bench("wild/cases.yaml", "wild/split.yaml")
def test_split_file_matches_cases():
    sp = yaml.safe_load((WB.BENCH / "split.yaml").read_text())
    meta = yaml.safe_load((WB.BENCH / "cases.yaml").read_text())
    assert sp["salt"] and sp["method"]
    assert WSP.split(meta["cases"], sp["salt"]) == sp["cases"]
