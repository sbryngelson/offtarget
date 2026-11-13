"""Where the data lives: the repository in a checkout, a bundle inside an installed package, or OFFLOAD_ROOT.

Modules that read catalog/, findings or the generated site data import ROOT from here
instead of working it out from their own file name.
"""
import os
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent.parent


def resolve_root() -> Path:
    env = os.environ.get("OFFLOAD_ROOT")
    if env:
        return Path(env)
    if (_REPO / "catalog").is_dir():
        return _REPO
    return _REPO / "offload" / "_root"


ROOT = resolve_root()


def is_bundle() -> bool:
    return ROOT != _REPO


def problem() -> str | None:
    """A one-line reason the data is missing, or None."""
    if (ROOT / "catalog").is_dir():
        return None
    where = "OFFLOAD_ROOT" if os.environ.get("OFFLOAD_ROOT") else "the installed package"
    return f"offload: no data under {ROOT} (from {where}); set OFFLOAD_ROOT to a checkout or reinstall"
