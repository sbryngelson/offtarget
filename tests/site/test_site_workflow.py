"""The human/CI publishing path: tools/site_publish.sh (the one command), the GitHub
Actions workflow .github/workflows/site.yml and docs/tooling/publishing.md. The workflow is CPU
only (no compiler, no module load, no scheduler), reads nothing under results/ or a
sealed set, pins every action to a commit, holds no secret and asks for the least
permissions GitHub Pages needs."""
import glob
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

from offload.engine.site import scrub as S

ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "site.yml"
PUBLISH = ROOT / "tools" / "site_publish.sh"
DOC = ROOT / "docs" / "tooling" / "publishing.md"

# a compiler, a module system, a scheduler or a remote machine: none of them in CI
FORBIDDEN = re.compile(r"\b(module\s+load|ftn|craycc|crayftn|amdflang|amdclang|nvfortran|nvc|nvcc|"
                       r"gfortran|gcc|g\+\+|clang|flang|flux|srun|sbatch|ssh|rsync|rocm|cuda|hipcc)\b")
# git-ignored measurements and the sealed sets: never an input of the public build
PRIVATE = re.compile(r"\b(results|bench|corpus|spec)/|fresh2|holdout|SEAL\b|spec_cache")
SHA = re.compile(r"^[0-9a-f]{40}$")
PATHISH = re.compile(r"(?<![\w./-])((?:tools|tests|docs|site|offload|catalog|data)/[\w./*-]+)")


def _wf() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _jobs() -> dict:
    return _wf()["jobs"]


def _runs() -> list[str]:
    return [s["run"] for j in _jobs().values() for s in j["steps"] if "run" in s]


def test_the_workflow_runs_on_the_default_branch_and_by_hand():
    wf = _wf()
    on = wf.get("on", wf.get(True))     # PyYAML reads a bare `on` as the boolean True
    assert set(on) == {"push", "workflow_dispatch"}
    assert on["push"] == {"branches": ["master"]}
    assert wf["concurrency"]["cancel-in-progress"] is False


def test_every_action_is_pinned_to_a_commit_with_its_version_named():
    uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)(.*)$", WORKFLOW.read_text(), re.M)
    assert len(uses) >= 5
    for ref, rest in uses:
        owner, sha = ref.rsplit("@", 1)
        assert owner.startswith("actions/"), ref        # GitHub's own actions only
        assert SHA.match(sha), f"{ref}: not a full commit sha"
        assert re.search(r"#\s*v\d+\.\d+\.\d+", rest), f"{ref}: the version it pins is not named"


def test_permissions_are_the_least_pages_needs():
    wf = _wf()
    assert wf["permissions"] == {}
    jobs = _jobs()
    assert set(jobs) == {"build", "deploy"}
    assert jobs["build"]["permissions"] == {"contents": "read"}
    assert jobs["deploy"]["permissions"] == {"pages": "write", "id-token": "write"}
    assert jobs["deploy"]["needs"] == "build"
    assert jobs["deploy"]["environment"]["name"] == "github-pages"
    text = WORKFLOW.read_text()
    assert "secrets." not in text and "GITHUB_TOKEN" not in text
    checkout = next(s for s in jobs["build"]["steps"] if s.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["persist-credentials"] is False


def test_the_deploy_job_runs_only_when_the_owner_sets_the_switch():
    """A push to master builds and checks; it publishes only while the repository variable
    SITE_PUBLISH is 'true' (the maintainer sets it on go-live, docs/tooling/publishing.md)."""
    jobs = _jobs()
    assert "if" not in jobs["build"]
    assert "vars.SITE_PUBLISH == 'true'" in str(jobs["deploy"]["if"])
    text = DOC.read_text()
    on = text.split("## Turning it on", 1)[1].split("\n## ", 1)[0]
    assert "SITE_PUBLISH" in on and "gh variable set SITE_PUBLISH" in on
    assert "SITE_PUBLISH" in on.split("### Rollback", 1)[1]


def test_every_job_has_a_time_limit():
    for name, job in _jobs().items():
        assert 0 < job.get("timeout-minutes", 0) <= 60, name


def test_the_source_links_follow_the_default_branch():
    build = next(s for s in _jobs()["build"]["steps"] if "site_publish.sh" in s.get("run", ""))
    assert "--source-branch" in build["run"]
    assert "github.event.repository.default_branch" in str(build["env"])


def test_the_build_directory_is_ignored():
    assert "/_site/" in (ROOT / ".gitignore").read_text().split()


def test_the_browser_check_ends_its_chrome():
    """tools/site/site_check.mjs kills the whole Chrome process group after a grace period, so a
    surviving Chrome cannot hold a compute-node job open (docs/tooling/site.md)."""
    text = (ROOT / "tools" / "site" / "site_check.mjs").read_text()
    assert "detached: true" in text and "SIGKILL" in text and "-chrome.pid" in text
    assert "outlive" in (ROOT / "docs" / "tooling" / "site.md").read_text() or "process group" in (ROOT / "docs" / "tooling" / "site.md").read_text()


def test_the_workflow_uses_only_cpu_commands_and_no_private_input():
    for run in _runs():
        assert not FORBIDDEN.search(run), run
    text = WORKFLOW.read_text()
    assert not PRIVATE.search(text), PRIVATE.search(text).group(0)
    runners = {j["runs-on"] for j in _jobs().values()}
    assert runners and all(r.startswith("ubuntu-") and r != "ubuntu-latest" for r in runners), runners


def test_every_path_the_workflow_names_exists():
    text = WORKFLOW.read_text()
    paths = sorted(set(PATHISH.findall(text)))
    assert "tools/site_publish.sh" in paths
    for p in paths:
        hits = glob.glob(str(ROOT / p), recursive=True)
        assert hits, f"{p}: named in the workflow, not in the tree"


def test_the_workflow_builds_checks_tests_and_deploys():
    runs = "\n".join(_runs())
    assert "tools/site_publish.sh _site" in runs
    assert re.search(r"pytest .*tests/site", runs)
    steps = [s.get("uses", "") for j in _jobs().values() for s in j["steps"]]
    assert any(s.startswith("actions/upload-pages-artifact@") for s in steps)
    assert any(s.startswith("actions/deploy-pages@") for s in steps)
    upload = next(s for j in _jobs().values() for s in j["steps"]
                  if s.get("uses", "").startswith("actions/upload-pages-artifact@"))
    assert upload["with"]["path"] == "_site"
    # the test subset the workflow runs is the one that guards the site, and it includes this file
    files = sorted(glob.glob(str(ROOT / "tests" / "site" / "test_*.py")))
    assert str(Path(__file__)) in files and len(files) >= 4


def test_the_requirements_are_pinned_and_small():
    req = next(p for p in PATHISH.findall(WORKFLOW.read_text()) if p.endswith("requirements.txt"))
    lines = [l.strip() for l in (ROOT / req).read_text().splitlines() if l.strip() and not l.startswith("#")]
    assert lines and all(re.match(r"^[A-Za-z0-9_.-]+==\d", l) for l in lines), lines
    assert {l.split("==")[0].lower() for l in lines} == {"pyyaml", "pytest"}


def test_the_publish_script_is_the_one_command():
    assert PUBLISH.is_file() and PUBLISH.stat().st_mode & stat.S_IXUSR
    text = PUBLISH.read_text()
    assert text.startswith("#!/bin/bash")
    assert "set -euo pipefail" in text
    assert "tools/site/site_build.py" in text and "tools/site/site_check.py" in text
    for word in ("Chrome", "Chromium", "node", "docs/tooling/publishing.md"):
        assert word in text, word
    assert "results/" not in text.replace("under results/", "")
    subprocess.run(["bash", "-n", str(PUBLISH)], check=True)


def test_the_publish_script_refuses_without_a_browser(tmp_path):
    bare = tmp_path / "bin"
    bare.mkdir()
    for tool in ("bash", "dirname", "ls", "find", "wc", "node"):
        src = Path("/usr/bin" if Path(f"/usr/bin/{tool}").exists() else "/bin") / tool
        if src.exists():
            os.symlink(src, bare / tool)
    env = {"PATH": str(bare), "HOME": str(tmp_path)}
    r = subprocess.run(["bash", str(PUBLISH), str(tmp_path / "out")], env=env, capture_output=True,
                       text=True, timeout=60)
    assert r.returncode == 1 and ("Chrome" in r.stderr or "node" in r.stderr), r.stderr
    assert not (tmp_path / "out").exists()


def test_the_publish_script_refuses_a_non_empty_output_directory(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "stale.html").write_text("x")
    r = subprocess.run(["bash", str(PUBLISH), str(out)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 1 and "not empty" in r.stderr


def test_the_publishing_document_covers_the_hand_offs():
    text = DOC.read_text()
    for frag in (".github/workflows/site.yml", "tools/site_publish.sh", "tools/site/site_inputs.py",
                 "GitHub Pages", "Settings", "GitHub Actions", "rollback", "private", "licen",
                 "history", "dry run", "Chrome", "claude.ai",
                 # The repository goes public (an export without data/bench/), not only the site;
                 # the specification notices, the OpenACC one reserving all rights
                 "THIRD_PARTY_NOTICES.md", "data/bench/", "OpenMP Architecture Review Board",
                 "OpenACC-Standard.org", "All rights reserved",
                 # The pinned tags are lightweight
                 "lightweight"):
        assert frag.lower() in text.lower(), frag
    assert not re.search(r"(?<![-\w])(we|our|ours|I|me|my)\b", text)   # `python3 -I` is a flag
    assert "/p/lustre" not in text and "/g/g" not in text and not S.leaks(text)


@pytest.mark.parametrize("doc", ["docs/tooling/site.md", "docs/tooling/contributing.md", "docs/tooling/regenerate.md"])
def test_the_other_documents_point_at_the_publish_path(doc):
    text = (ROOT / doc).read_text()
    assert "site_publish.sh" in text or "site_inputs" in text, doc
