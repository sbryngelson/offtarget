"""tools/repo/private_text.py: no tracked file holds a user name, a private path, the internal host or a work-item label."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools" / "repo"))
import private_text as PT  # noqa: E402


@pytest.fixture
def names(monkeypatch):
    monkeypatch.setenv("OFFLOAD_PRIVATE_NAMES", "jdoe")
    from offload.engine.site import scrub
    scrub.private_names.cache_clear()
    yield
    scrub.private_names.cache_clear()


def _tree(tmp_path, files):
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    return tmp_path


def test_a_user_name_or_label_in_a_tracked_file_is_found(tmp_path, names):
    t = _tree(tmp_path, {"docs/a.md": "run from /g/g10/jdoe1/x\n", "docs/b.md": "as Task 12 said\n",
                         "docs/c.md": "clean text\n"})
    got = PT.leaks(t)
    assert set(got) == {"docs/a.md", "docs/b.md"}


def test_write_scrubs_the_generated_files_only(tmp_path, names):
    t = _tree(tmp_path, {"data/reports/r.md": "under `/tmp/jdoe1/w` on wingtip-gpu3\n",
                         "data/reports/p.sh": "cd /p/lustre5/jdoe1/compliant\n",
                         "docs/a.md": "see /tmp/jdoe1/w\n"})
    PT.scrub_generated(t)
    assert (t / "data/reports/r.md").read_text() == "under `/tmp/<user>/w` on wingtip\n"
    assert (t / "data/reports/p.sh").read_text() == "cd <site>/compliant\n"
    assert (t / "docs/a.md").read_text() == "see /tmp/jdoe1/w\n"      # hand-written: reported, never rewritten
    assert list(PT.leaks(t)) == ["docs/a.md"]


def test_the_public_handle_in_a_repository_link_is_not_a_leak(tmp_path, names):
    t = _tree(tmp_path, {"README.md": "https://github.com/jdoe/offtarget and jdoe.github.io\n"})
    assert PT.leaks(t) == {}


def test_no_tracked_text_file_holds_private_text(monkeypatch):
    """The names are this checkout's committers and login; the made-up names the tests use stay out."""
    from offload.engine.site import scrub
    monkeypatch.delenv("OFFLOAD_PRIVATE_NAMES", raising=False)
    scrub.private_names.cache_clear()
    bad = PT.leaks(ROOT)
    scrub.private_names.cache_clear()
    assert not bad, dict(list(bad.items())[:10])
