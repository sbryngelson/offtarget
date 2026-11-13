"""offload._bundle: the data an installed copy carries, and proof it is enough."""
import re
import subprocess
import sys
from pathlib import Path

from offload.engine.site import scrub as S

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]

from offload import _bundle  # noqa: E402
import trace_reads  # noqa: E402,F401  (imported to fail early if it moves)

# the commands an installed copy answers, each with arguments that read the catalogs, the findings and the site data
QUERIES = (("can-use", "clause.map.present"), ("can-use", "--list"), ("issues", "defaultmap"),
           ("issues", "--show", "cce-c-dist-schedule-segv"))


@pytest.fixture
def bundle(offload_bundle):
    return offload_bundle


def _tracked() -> set[str]:
    return set(subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.splitlines())


def test_manifest_patterns_each_match_a_tracked_file():
    tracked = _tracked()
    for pat in _bundle.manifest():
        hits = [p for p in tracked if Path(p).match(pat) or (pat.endswith("/**") and p.startswith(pat[:-2]))]
        assert hits, pat


def test_collect_is_under_25_mb(bundle):
    dest, files = bundle
    assert sum(f.stat().st_size for f in files) < 25_000_000


def test_collect_has_no_sealed_withheld_or_log_files(bundle):
    dest, files = bundle
    rel = [str(f.relative_to(dest)) for f in files]
    assert not [p for p in rel if "holdout" in p or p.endswith((".log", ".jsonl", ".core"))
                or p.startswith(("results/", "corpus/", "data/bench/hecbench"))], rel[:5]
    assert not [p for p in rel if "/fresh2/" in p]


def test_collect_writes_the_site_data_but_not_the_per_issue_pages(bundle):
    dest, _ = bundle
    assert (dest / "data" / "issues.json").is_file() and (dest / "data" / "canuse" / "index.json").is_file()
    assert not (dest / "data" / "issues").exists()


@pytest.mark.parametrize("query", QUERIES)
def test_each_command_answers_the_same_from_the_bundle_as_from_the_checkout(bundle, query, tmp_path):
    dest, _ = bundle
    def run(root):
        r = subprocess.run([sys.executable, "-m", "offload", *query], cwd=tmp_path, capture_output=True, text=True,
                           env={"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin", "OFFLOAD_ROOT": str(root)})
        assert r.returncode in (0, 1), r.stderr[-400:]
        return r.stdout
    assert run(dest) == run(ROOT)


def test_manifest_covers_every_file_the_commands_open(bundle):
    dest, files = bundle
    have = {str(f.relative_to(dest)) for f in files}
    for query in QUERIES:
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "repo" / "trace_reads.py"), "offload/__main__.py", *query],
                           cwd=ROOT, capture_output=True, text=True, env={"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin"})
        reads = r.stdout.split("=== reads ===\n", 1)[1].split()
        data = [p for p in reads if p.startswith(("catalog/", "docs/", "data/"))
                and p != "catalog/local.yaml"]       # the user's own settings (git-ignored), never bundled
        assert not [p for p in data if p not in have], [p for p in data if p not in have][:5]


def test_collect_carries_no_user_name_or_machine_path(bundle):
    dest, files = bundle
    leaks = []
    for f in files:
        if f.suffix == ".py":
            continue                             # code may hold the patterns that scrub these names
        try:
            text = f.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        if re.search(r"/p/(?:lustre\d|vast\d)/|/nethome/|/fastscratch/", text) or S._names_rx().search(text):
            leaks.append(str(f.relative_to(dest)))
    assert not leaks, leaks[:5]
