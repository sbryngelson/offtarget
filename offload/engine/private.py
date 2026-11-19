"""The maintainers' private checkout (tools/repo/private.yaml): where it is, and the paths of this tree it supplies.

The benchmark sets, the vendor report drafts and the findings log live in a separate repository that only the
maintainers can read. `link` puts each of its paths into this tree at the same path as a git-ignored link; `files`
lists every file of the tree with the linked ones, for the lanes that copy the tree to another machine.
"""
import fnmatch
import os
import subprocess
from pathlib import Path

import yaml

from offload.engine import localcfg
from offload.engine.root import ROOT

CONFIG = ROOT / "tools" / "repo" / "private.yaml"


class PrivateError(Exception):
    pass


def config() -> dict:
    return localcfg.overlay("private.yaml", yaml.safe_load(CONFIG.read_text()) or {})


def patterns() -> list[str]:
    return list(config().get("paths") or [])


def root() -> Path | None:
    """The private checkout the local settings name (relative to this repository's root), or None."""
    r = config().get("root")
    if not r:
        return None
    p = Path(os.path.expanduser(str(r)))
    return p if p.is_absolute() else (ROOT / p).resolve()


def _ls(tree: Path, *paths: str, new: bool = True) -> list[str]:
    """Tracked files of the git tree at `tree`, and with `new` the new (not ignored) ones."""
    out = subprocess.run(["git", "-C", str(tree), "ls-files", *(["-co", "--exclude-standard"] if new else []), "-z",
                          "--", *paths],
                         capture_output=True, text=True, check=True).stdout
    return [f for f in out.split("\0") if f]


def entries(priv: Path, here: Path, pats: list[str]) -> list[str]:
    """The paths of `priv` to link into `here`: every match of a pattern among its files and their directories,
    except a path `here` tracks."""
    ours = set(_ls(here, new=False))
    found = set()
    for f in _ls(priv):
        parts = f.split("/")
        for n in range(1, len(parts) + 1):
            rel = "/".join(parts[:n])
            if any(fnmatch.fnmatch(rel, p) and rel.count("/") == p.count("/") for p in pats):
                found.add(rel)
                break
    return sorted(r for r in found if r not in ours)


def _stale(here: Path, pats: list[str]) -> list[Path]:
    """Links under a private pattern that point into no existing path."""
    out = []
    for p in pats:
        for cand in here.glob(p):
            if cand.is_symlink() and not cand.exists():
                out.append(cand)
    return out


def link(priv: Path, here: Path, pats: list[str], check: bool = False) -> list[str]:
    """Link each private path into `here`; with `check`, only list what is missing or wrong. A real file or
    directory at a private path is an error, and is never replaced."""
    todo, bad = [], []
    for rel in entries(priv, here, pats):
        dest, src = here / rel, (priv / rel).resolve()
        if dest.is_symlink():
            if dest.resolve() == src:
                continue
            todo.append(rel)
            if not check:
                dest.unlink()
        elif dest.exists():
            bad.append(rel)
            continue
        else:
            todo.append(rel)
        if not check:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.symlink_to(src)
    for s in _stale(here, pats):
        todo.append(str(s.relative_to(here)) + " (stale)")
        if not check:
            s.unlink()
    if bad:
        raise PrivateError("not a link, left alone: " + ", ".join(bad))
    return todo


def linked(here: Path, pats: list[str]) -> list[str]:
    """The private paths `here` has as working links."""
    return sorted(str(c.relative_to(here)) for p in pats for c in here.glob(p) if c.is_symlink() and c.exists())


def files(here: Path = ROOT, pats: list[str] | None = None) -> list[str]:
    """Every file of `here`, with the files behind its links to the private checkout (as their paths here)."""
    pats = patterns() if pats is None else pats
    links = linked(here, pats)
    out = {f for f in _ls(here) if not any(f == r or f.startswith(r + "/") for r in links)}
    for rel in links:
        target = (here / rel).resolve()
        if target.is_dir():
            out |= {f"{rel}/{f}" for f in _ls(target)}
        else:
            out.add(rel)
    return sorted(out)
