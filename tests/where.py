"""Find a maintainers script by file name; the scripts live in tools/ and its area folders."""
from pathlib import Path

MAINT = Path(__file__).resolve().parent.parent / "tools"
AREAS = ("", "jobs", "dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")


def tool(name: str) -> Path:
    for area in AREAS:
        p = MAINT / area / name
        if p.is_file():
            return p
    raise FileNotFoundError(name)


MESSAGES = MAINT.parent / "tests" / "data" / "messages"


def message(name: str) -> Path:
    """A captured compiler message by file stem; the files sit in a folder per compiler."""
    hits = list(MESSAGES.rglob(f"{name}.txt"))
    if len(hits) != 1:
        raise FileNotFoundError(name)
    return hits[0]


def built_once(name, build):
    """Build `name` into a directory shared by every test worker (the first to ask builds it, the others wait),
    so an expensive build runs once per test run, not once per worker."""
    import fcntl
    import os
    import tempfile
    uid = os.environ.get("PYTEST_XDIST_TESTRUNUID") or f"solo-{os.getpid()}"
    root = Path(tempfile.gettempdir()) / f"compliant-tests-{uid}"
    root.mkdir(exist_ok=True)
    import shutil
    import time
    for old in root.parent.glob("compliant-tests-*"):          # earlier runs' leftovers
        if old != root and time.time() - old.stat().st_mtime > 6 * 3600:
            shutil.rmtree(old, ignore_errors=True)
    done = root / f"{name}.done"
    with open(root / f"{name}.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not done.exists():
            dest = root / name
            dest.mkdir(exist_ok=True)
            build(dest)
            done.write_text("ok")
    return root / name
