"""The dev/holdout split of the harvest2 programs.

The holdout is the lowest 30% of the sha256 space of a program's code
(offload.engine.harvest.convert.holdout_by_code: comments, the header among
them, and blank runs ignored), so programs that differ
only in comments fall on one side:
data/bench/harvest2-holdout, opaque case files harvest2-holdout-NNN.<c|f90>
numbered in program-id order, cases.yaml (provenance) and SEAL (the digest
of tools/campaigns/fresh_bench.py over the case files, and the sha256 of cases.yaml;
outcomes are added by phase 2's runs). Everything else is the dev set,
data/bench/harvest2, one file per program named by its id.

A copyleft program (GPL: the GCC testsuite; CC-BY-SA) goes to a
``copyleft/`` subdirectory of either set, beside its license texts; the
maintainers decide on publishing it."""
from __future__ import annotations

import hashlib
from pathlib import Path

from offload.engine.harvest import convert as HC

HOLDOUT_NAME = "harvest2-holdout"


def _ext(lang: str) -> str:
    return ".c" if lang == "c" else ".f90"


def plan(progs: list[dict]) -> list[dict]:
    """Each program with ``set`` (dev or holdout), ``path`` (relative to
    the set's directory) and, for the holdout, ``case``."""
    out = []
    k = 0
    for p in sorted(progs, key=lambda q: q["id"]):
        sub = "copyleft/" if p.get("copyleft") else ""
        if HC.holdout_by_code(p["source"], p["lang"]):
            k += 1
            case = f"{HOLDOUT_NAME}-{k:03d}"
            out.append({**p, "set": "holdout", "case": case,
                        "path": sub + case + _ext(p["lang"])})
        else:
            out.append({**p, "set": "dev",
                        "path": sub + p["id"] + _ext(p["lang"])})
    return out


def dev_similar(plan_rows: list[dict]) -> dict:
    """Each dev program's `similar` list without holdout programs (no
    holdout id in the dev set's cases)."""
    hold = {p["id"] for p in plan_rows if p["set"] == "holdout"}
    return {p["id"]: [x for x in p.get("similar") or []
                      if not (x.get("set") == "harvest2" and x["id"] in hold)]
            for p in plan_rows if p["set"] == "dev"}


def digest(paths) -> str:
    """tools/campaigns/fresh_bench.py's digest: sha256 over the case files sorted by
    name, each as name, NUL, bytes, NUL."""
    h = hashlib.sha256()
    for p in sorted(paths, key=lambda q: q.name):
        h.update(p.name.encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def seal_text(commit: str, paths, meta: Path) -> str:
    paths = list(paths)
    return (
        f"# Seal of bench/{HOLDOUT_NAME} (the harvest2 holdout: "
        "30% of the programs by sha256)\n"
        f"commit: {commit}\n"
        f"cases: {len(paths)}\n"
        f"method: sha256 over the case files ({HOLDOUT_NAME}-*.f90, "
        # the sealed text names the tool by its original path (tools/): the committed SEAL files say so
        f"{HOLDOUT_NAME}-*.c, copyleft/ included) sorted by name, each as "
        "name, NUL, bytes, NUL (tools/fresh_bench.py digest)\n"
        f"sha256: {digest(paths)}\n"
        f"cases_yaml_sha256: {hashlib.sha256(meta.read_bytes()).hexdigest()}\n")
