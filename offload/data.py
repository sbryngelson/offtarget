"""Where offload reads the site data (can-use tables, issues) from.

An installed copy has it in the bundle (<root>/data). A checkout builds it on first use into a
cache beside the repository (.offload-cache/, git-ignored; ~/.cache/offload when the checkout is read-only) and rebuilds when an input changed.
OFFLOAD_DATA names a ready directory and skips both.
"""
import fcntl
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from offload.engine.root import ROOT, is_bundle

_cache: dict[str, object] = {}
# what the cache is built from, data and code: a change to any of them is a new cache
INPUTS = ("data/findings", "site/inputs", "catalog/toolchains.yaml", "catalog/machines.yaml", "data/vendor/checks",
          "offload/engine/site", "offload/_bundle.py")


def clear_cache() -> None:
    _cache.clear()


def _stamp() -> str:
    newest = 0.0
    for rel in INPUTS:
        p = ROOT / rel
        for f in ([p] if p.is_file() else p.rglob("*") if p.is_dir() else []):
            if f.is_file() and "__pycache__" not in f.parts:
                newest = max(newest, f.stat().st_mtime)
    return f"{newest:.0f}"


def cache_root(root: Path = ROOT) -> Path:
    """.offload-cache beside the checkout, or the user's cache directory when the checkout is read-only."""
    if os.access(root, os.W_OK):
        return root / ".offload-cache"
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "offload" / hashlib.sha1(str(root).encode()).hexdigest()[:12]


def publish(tmp: Path, cache: Path) -> None:
    """Move a finished build into place; a concurrent first run that got there first wins."""
    os.chmod(tmp, 0o755)
    cache.parent.mkdir(parents=True, exist_ok=True)
    try:
        Path(tmp).rename(cache)
    except OSError:
        if (cache / "data" / "issues.json").is_file():
            return
        shutil.rmtree(cache)                       # a broken cache (no issues.json) is replaced
        Path(tmp).rename(cache)


def data_dir() -> Path:
    env = os.environ.get("OFFLOAD_DATA")
    if env:
        return Path(env)
    if is_bundle() or (ROOT / "data" / "issues.json").is_file():
        return ROOT / "data"
    base = cache_root()
    cache = base / _stamp()
    if not (cache / "data" / "issues.json").is_file():
        base.mkdir(parents=True, exist_ok=True)
        with open(base / ".build.lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)       # one build at a time; a run that waited finds it done
            if not (cache / "data" / "issues.json").is_file():
                from offload import _bundle
                print("offload: building the data from the checkout (first run, about a minute) ...", file=sys.stderr)
                with tempfile.TemporaryDirectory(dir=base) as tmp:
                    _bundle.collect_data(Path(tmp))
                    publish(Path(tmp), cache)
    return cache / "data"


def load(rel: str):
    """The JSON file `rel` under the data directory, read once per process."""
    key = f"{data_dir()}/{rel}"
    if key not in _cache:
        _cache[key] = json.loads((data_dir() / rel).read_text())
    return _cache[key]
