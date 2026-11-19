"""offload/engine/private.py and tools/repo/link_private.py: the maintainers' private checkout linked into the tree."""
import subprocess
import sys
from pathlib import Path

import pytest

from offload.engine import private as P

ROOT = Path(__file__).resolve().parent.parent
PATTERNS = ["data/bench/*", "data/findings/LOG.md", "data/vendor/amd", "data/vendor/checks/reports-*.yaml"]


def _repo(path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        (path / rel).parent.mkdir(parents=True, exist_ok=True)
        (path / rel).write_text(text)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    return path


@pytest.fixture
def trees(tmp_path):
    priv = _repo(tmp_path / "private", {
        "README.md": "the private repository\n",
        "data/bench/README.md": "the maintainers' description of the sets\n",
        "data/bench/fresh/fresh-001.c": "int main(){}\n",
        "data/bench/wild/cases.yaml": "{}\n",
        "data/findings/LOG.md": "# log\n",
        "data/vendor/amd/case.md": "draft\n",
        "data/vendor/checks/reports-amd.yaml": "{}\n",
    })
    here = _repo(tmp_path / "public", {
        "data/bench/README.md": "not published\n",
        "data/vendor/checks/run_checks.py": "\n",
        "data/findings/index.yaml": "{}\n",
    })
    return priv, here


def test_each_private_path_is_linked_at_the_same_path(trees):
    priv, here = trees
    P.link(priv, here, PATTERNS)
    for rel in ("data/bench/fresh", "data/bench/wild", "data/findings/LOG.md", "data/vendor/amd",
                "data/vendor/checks/reports-amd.yaml"):
        assert (here / rel).is_symlink() and (here / rel).resolve() == (priv / rel).resolve(), rel
    assert (here / "data/bench/fresh/fresh-001.c").read_text() == "int main(){}\n"


def test_a_path_this_tree_tracks_is_never_linked(trees):
    priv, here = trees
    P.link(priv, here, PATTERNS)
    assert not (here / "data/bench/README.md").is_symlink()
    assert (here / "data/bench/README.md").read_text() == "not published\n"


def test_linking_again_changes_nothing_and_a_stale_link_goes(trees):
    priv, here = trees
    P.link(priv, here, PATTERNS)
    (here / "data/bench/gone").symlink_to(priv / "data/bench/gone")      # a set the private repo no longer has
    P.link(priv, here, PATTERNS)
    assert not (here / "data/bench/gone").is_symlink()
    assert (here / "data/bench/fresh").is_symlink()


def test_a_real_file_at_a_private_path_is_an_error_and_is_left_alone(trees):
    priv, here = trees
    (here / "data/findings/LOG.md").write_text("a copy\n")
    with pytest.raises(P.PrivateError, match="data/findings/LOG.md"):
        P.link(priv, here, PATTERNS)
    assert (here / "data/findings/LOG.md").read_text() == "a copy\n"


def test_the_file_list_holds_both_trees(trees):
    priv, here = trees
    P.link(priv, here, PATTERNS)
    got = P.files(here, PATTERNS)
    assert "data/findings/index.yaml" in got and "data/bench/README.md" in got
    assert "data/bench/fresh/fresh-001.c" in got and "data/vendor/amd/case.md" in got
    assert "data/findings/LOG.md" in got
    assert "README.md" not in got                     # the private repository's own files stay out
    assert "data/bench/fresh" not in got              # files, not the links


def test_without_links_the_file_list_is_this_tree(trees):
    _, here = trees
    assert P.files(here, PATTERNS) == sorted(["data/bench/README.md", "data/findings/index.yaml",
                                                    "data/vendor/checks/run_checks.py"])


def test_the_root_comes_from_the_local_settings(tmp_path, monkeypatch):
    local = tmp_path / "local.yaml"
    local.write_text("private.yaml:\n  root: ../offtarget-private\n")
    monkeypatch.setenv("OFFLOAD_LOCAL", str(local))
    assert P.root() == (P.ROOT / "../offtarget-private").resolve()
    monkeypatch.setenv("OFFLOAD_LOCAL", "")
    assert P.root() is None


def test_every_private_path_is_git_ignored_here():
    probes = [p.replace("*", "some-set") for p in P.patterns()]
    out = subprocess.run(["git", "check-ignore", "--no-index", *probes], cwd=ROOT, capture_output=True,
                         text=True).stdout.split()
    assert sorted(out) == sorted(probes)
    tracked = subprocess.run(["git", "ls-files", "data/bench"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    assert tracked == ["data/bench/README.md"]


def test_the_command_says_when_no_private_checkout_is_set(tmp_path):
    env = {"OFFLOAD_LOCAL": "", "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-I", "tools/repo/link_private.py", "--check"], cwd=ROOT, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0 and "no private checkout" in r.stdout
