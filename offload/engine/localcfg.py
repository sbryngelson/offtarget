"""Settings of the machine the tools run on, laid over the shared catalogs.

catalog/machines.yaml and catalog/toolchains.yaml say nothing about where anything is installed or how to reach it.
A user's file does (catalog/local.example.yaml): one mapping per catalog file, named like it, laid over its contents.
The files named by OFFLOAD_LOCAL are read if the variable is set (a list separated by the path separator, later files
over earlier; set empty, none). Otherwise the first that exists of catalog/local.yaml (git-ignored) and
~/.config/offload/local.yaml. Mappings merge key by key, a null removes a key, anything else replaces; an entry the
catalog lacks (a new machine or compiler) is added and checked like a catalog entry.
"""
import os
from functools import lru_cache
from pathlib import Path

import yaml

from offload.engine.root import ROOT

ENV = "OFFLOAD_LOCAL"


def paths() -> list[Path]:
    named = os.environ.get(ENV)
    if named is not None:                  # set, even to nothing: those files only
        return [Path(p) for p in named.split(os.pathsep) if p and Path(p).is_file()]
    for p in (ROOT / "catalog" / "local.yaml", Path.home() / ".config" / "offload" / "local.yaml"):
        if p.is_file():
            return [p]
    return []


@lru_cache(maxsize=None)
def _read(p: str, mtime: float) -> dict:
    return yaml.safe_load(Path(p).read_text()) or {}


def merge(base, over):
    """`over` laid over `base`: mappings merge, None deletes, anything else replaces."""
    if not isinstance(base, dict) or not isinstance(over, dict):
        return over
    out = dict(base)
    for k, v in over.items():
        if v is None:
            out.pop(k, None)
        else:
            out[k] = merge(base.get(k), v)
    return out


def overlay(name: str, data: dict) -> dict:
    """`data`, the contents of catalog/`name`, with the user's settings for it laid over."""
    for p in paths():
        mine = _read(str(p), p.stat().st_mtime).get(name)
        if mine is None:
            continue
        if not isinstance(mine, dict):
            raise ValueError(f"{p}: {name} must be a mapping")
        data = merge(data, mine)
    return data
