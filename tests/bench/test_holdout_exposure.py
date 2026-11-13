"""Sealed holdout exposure: a sealed set that is not scored yet (data/bench/<set>/SEAL, not listed in
catalog/sealed_spent.yaml) must keep its unexcluded cases unexposed. The catalog's exclusion file
(sealed ids only) lists every case whose code or outcome can be read outside the seal; these tests
fail when another case becomes readable, e.g. a dev program that is a copy of it, or a tracked file
that names it.

They read only case ids and hashes of the sealed files (never print or compare a program's text),
and skip where the set is absent (wingtip lanes do not receive unscored sealed sets)."""
import re
import subprocess
from pathlib import Path

import pytest
import yaml

import hashlib


def program_sha(files) -> str:
    """The hash the exclusion files hold: of the program's text (its file, or its files joined with the
    confirmer's file marks), lines right-stripped and blank lines dropped."""
    files = list(files)
    if len(files) == 1:
        text = files[0][1]
    else:
        from offload.engine.confirm.programs import join_files
        text = join_files(files)
    norm = "\n".join(ln.rstrip() for ln in text.splitlines() if ln.strip()) + "\n"
    return hashlib.sha256(norm.encode()).hexdigest()


ROOT = Path(__file__).resolve().parent.parent.parent
# unscored sealed set -> (case-id prefix, the exclusion file beside the seal)
EXCLUSION = {"harvest2-holdout": ("harvest2-holdout-", "catalog/harvest2_holdout_excluded.yaml")}
SOURCE_EXT = (".c", ".h", ".f90", ".F90", ".f", ".F", ".cpp", ".cc")


def _git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True,
                          check=True).stdout


def _unspent_sealed():
    spent = set(yaml.safe_load((ROOT / "catalog/sealed_spent.yaml").read_text())["spent"] or ())
    return [s for s in EXCLUSION if (ROOT / "data" / "bench" / s / "SEAL").is_file() and s not in spent]


def _cases(sset, prefix):
    """case id -> [tracked paths of the sealed set that belong to it]."""
    out: dict = {}
    for path in _git("ls-files", f"data/bench/{sset}").splitlines():
        m = re.search(re.escape(prefix) + r"\d+", path)
        if m and path.endswith(SOURCE_EXT):
            out.setdefault(m.group(0), []).append(path)
    return out


def _excluded(path):
    d = yaml.safe_load((ROOT / path).read_text())
    return set(d["excluded"]), d


SETS = _unspent_sealed()


@pytest.mark.skipif(not SETS, reason="no unscored sealed set on this machine")
@pytest.mark.parametrize("sset", SETS)
def test_the_exclusion_file_accounts_for_every_sealed_case(sset):
    prefix, xfile = EXCLUSION[sset]
    cases = _cases(sset, prefix)
    excluded, d = _excluded(xfile)
    assert excluded <= set(cases), sorted(excluded - set(cases))[:5]
    assert d["sealed_cases"] == len(cases) == len(excluded) + d["unexposed_cases"]


@pytest.mark.skipif(not SETS, reason="no unscored sealed set on this machine")
@pytest.mark.parametrize("sset", SETS)
def test_no_tracked_source_outside_the_set_is_a_copy_of_an_unexcluded_case(sset):
    """A dev program with the same normalized text as a sealed case shows its labels."""
    prefix, xfile = EXCLUSION[sset]
    cases = _cases(sset, prefix)
    excluded, _ = _excluded(xfile)
    sha = {}
    for cid in sorted(set(cases) - excluded):
        files = [(p, (ROOT / p).read_text(errors="replace")) for p in sorted(cases[cid])]
        sha[program_sha(files)] = cid
    exposed = {}
    for path in _git("ls-files").splitlines():
        if path.startswith("data/bench/") and re.search(r"-holdout", path.split("/")[2]):
            continue    # the sealed sets themselves
        if not path.endswith(SOURCE_EXT):
            continue
        try:
            text = (ROOT / path).read_text(errors="replace")
        except OSError:
            continue
        cid = sha.get(program_sha([(path, text)]))
        if cid:
            exposed.setdefault(cid, []).append(path)
    assert not exposed, {cid: ps[:2] for cid, ps in sorted(exposed.items())[:5]}


@pytest.mark.skipif(not SETS, reason="no unscored sealed set on this machine")
@pytest.mark.parametrize("sset", SETS)
def test_no_tracked_file_names_an_unexcluded_case(sset):
    """Case ids of unexposed cases appear in the seal only (the exclusion files list the others).
    Read in Python: `git grep` takes minutes on a compute node."""
    prefix, xfile = EXCLUSION[sset]
    cases = _cases(sset, prefix)
    excluded, _ = _excluded(xfile)
    names = sorted(set(cases) - excluded)
    assert names
    pat = re.compile("|".join(re.escape(n) for n in names) + r"(?!\d)")
    hits = []
    for path in _git("ls-files", "-z").split("\0"):
        if not path or path.startswith(f"data/bench/{sset}/"):
            continue
        try:
            data = (ROOT / path).read_bytes()
        except OSError:
            continue
        if b"\0" in data[:4096]:
            continue    # binary
        if pat.search(data.decode(errors="replace")):
            hits.append(path)
    assert not hits, hits[:5]


# --- data/bench/hecbench-holdout: the sealed half of the HeCBench benchmarks ---------------------------
# The set holds no program text (the benchmarks are in the git-ignored clone corpus/apps/HeCBench-ornl):
# its cases are directory names, kept in the tree as SHA-256 hashes (data/bench/hecbench/split.yaml) and
# in the recipes and outcomes under data/bench/hecbench-holdout/. These tests read hashes only.
HEC_SET = "hecbench-holdout"
HEC_EXCLUDED = "catalog/hecbench_holdout_excluded.yaml"
HEC_SPENT = set(yaml.safe_load((ROOT / "catalog/sealed_spent.yaml").read_text())["spent"] or ())
HEC_SKIP = pytest.mark.skipif(
    not (ROOT / "data" / "bench" / HEC_SET / "SEAL").is_file() or HEC_SET in HEC_SPENT,
    reason="the hecbench holdout is absent or scored on this machine")
_HEC_NAME = re.compile(r"hecbench-[A-Za-z0-9_.+-]+-omp\b|src/[A-Za-z0-9_.+]+-omp\b")


def _hec_hashes():
    import hashlib
    d = yaml.safe_load((ROOT / "data/bench/hecbench/split.yaml").read_text())
    return d, set(d["holdout_sha256"]), hashlib


@HEC_SKIP
def test_the_hecbench_exclusion_file_accounts_for_the_sealed_cases():
    d, hashes, _ = _hec_hashes()
    excluded, x = _excluded(HEC_EXCLUDED)
    seal = (ROOT / "data" / "bench" / HEC_SET / "SEAL").read_text()
    assert f"cases: {d['holdout_count']}" in seal
    assert x["sealed_cases"] == len(hashes) == len(excluded) + x["unexposed_cases"]
    assert excluded <= hashes


@HEC_SKIP
def test_no_hecbench_program_text_is_tracked():
    """The benchmarks stay in the git-ignored clone: a tracked source file of either half, or a path
    into the clone, would show the sealed half's code."""
    for path in _git("ls-files").splitlines():
        assert "HeCBench-ornl" not in path, path
        if path.startswith(("data/bench/hecbench/", f"data/bench/{HEC_SET}/")) and \
                not path.startswith("data/bench/hecbench/stubs/"):       # stubs/: this corpus's own files
            assert not path.endswith(SOURCE_EXT), path


@HEC_SKIP
def test_no_tracked_file_names_an_unexcluded_hecbench_holdout_benchmark():
    """A benchmark's id (hecbench-<x>-omp) or path (src/<x>-omp) is hashed and looked up; the
    sealed set's own directory and the split file (hashes) are the only places holding the names."""
    d, hashes, hashlib = _hec_hashes()
    excluded, _ = _excluded(HEC_EXCLUDED)
    hits = []
    for path in _git("ls-files", "-z").split("\0"):
        if not path or path.startswith(f"data/bench/{HEC_SET}/"):
            continue
        try:
            data = (ROOT / path).read_bytes()
        except OSError:
            continue
        if b"\0" in data[:4096]:
            continue
        for tok in set(_HEC_NAME.findall(data.decode(errors="replace"))):
            for cand in (tok[len("hecbench-"):] if tok.startswith("hecbench-") else tok[len("src/"):],):
                h = hashlib.sha256(cand.encode()).hexdigest()
                if h in hashes and h not in excluded:
                    hits.append(path)
    assert not hits, sorted(set(hits))[:5]
