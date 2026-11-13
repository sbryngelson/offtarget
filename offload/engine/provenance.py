"""The provenance every result row carries.

Rows written by the harness (offload.engine.harness.Result) and by the fuzz and
stress runners record:

* ``build_dir``: the absolute path the program was compiled in;
* ``node``, ``flags``: the host name and the compile flags;
* ``toolchain_build``: ``"<version banner> [modules: a b]"``;
* ``env_hash``: first 16 hex digits of the sha256 of the exported run
  environment (sorted ``KEY=value`` lines);
* ``git_rev``: ``git rev-parse --short HEAD``, else the first word of
  ``.wingtip_rev``, else "";
* ``gate``: the gate's verdict (offload.engine.gate.VERDICTS), ``"pending"`` for
  an ungated failing row, ``"n/a"`` for a passing row.
``missing(row)`` lists the fields a row lacks."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
FIELDS = ("build_dir", "node", "toolchain_build", "flags", "env_hash",
          "git_rev", "gate")
PENDING = "pending"     # a failing row the gate has not judged
NOT_GATED = "n/a"       # a passing row: nothing to reproduce


@lru_cache(maxsize=None)
def git_rev() -> str:
    """The short revision of the working tree's HEAD (cached per process)."""
    try:
        res = subprocess.run(["git", "rev-parse", "--show-toplevel",
                              "--short", "HEAD"],
                             cwd=ROOT, capture_output=True, text=True,
                             timeout=30)
        top, _, rev = res.stdout.strip().partition("\n")
        # a copy without .git inside another repository (a home
        # directory under git) must not take that repository's revision
        if not top or Path(top).resolve() != ROOT.resolve():
            rev = ""
    except (subprocess.SubprocessError, OSError):
        rev = ""
    if not rev and (ROOT / ".wingtip_rev").is_file():
        rev = (ROOT / ".wingtip_rev").read_text().split()[0]
    return rev


def node() -> str:
    return os.uname().nodename


def modules_of(prelude: str) -> tuple[str, ...]:
    """The modules a toolchain prelude loads (``module load a b``)."""
    out: list[str] = []
    for m in re.finditer(r"module (?:load|swap) ([^\n;&|]+)", prelude or ""):
        out += m.group(1).split()
    return tuple(out)


def toolchain_build(tc) -> str:
    """The compiler's version banner and the modules its prelude loads."""
    from offload.engine.toolchains import compiler_version
    try:
        version = compiler_version(tc)
    except Exception:          # an ad-hoc test toolchain
        version = ""
    mods = modules_of(getattr(tc, "prelude", "") or "")
    return f"{version or tc.name} [modules: {' '.join(mods) or 'none'}]"


def env_hash(env: dict | None) -> str:
    """A short hash of the exported run environment (order-independent)."""
    text = "\n".join(f"{k}={v}" for k, v in sorted((env or {}).items()))
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def gate_status(failing: bool) -> str:
    return PENDING if failing else NOT_GATED


def fields(tc, build_dir: str, flags: str, env: dict | None,
           failing: bool) -> dict:
    """Every provenance field of one row."""
    return {"build_dir": str(build_dir), "node": node(),
            "toolchain_build": toolchain_build(tc), "flags": flags,
            "env_hash": env_hash(env), "git_rev": git_rev(),
            "gate": gate_status(failing)}


def missing(row: dict) -> list[str]:
    """The provenance fields a row lacks or leaves empty (``git_rev`` may
    be empty only outside a repository)."""
    out = []
    for f in FIELDS:
        if f not in row:
            out.append(f)
        elif f != "git_rev" and row[f] in ("", None):
            out.append(f)
    return out
