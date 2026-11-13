#!/usr/bin/env python3
"""Summaries of the NVHPC oracle (mutation) audit.

The audit runs per language and memory mode through tools/jobs/run_wingtip.sh
(audit:<lang>:<mode>), writing results/nvhpc/raw/audit.<lang>.x<mode>.*. This
script merges each language's two summaries into the committed file that
offload/engine/report.py reads for the NVIDIA cells (report.NV_AUDIT) and prints
the dispositions:

    python3 -I tools/campaigns/nvhpc_audit.py

``--toolchain nvhpc269 --raw DIR`` reads DIR/audit.<tag>.x<mode>.summary.json and
writes the release's own files (report.nv_audit_path, names suffixed _nvhpc269).
``--compare`` lists dispositions that differ from 25.11's. ``--merge-versions
DIR`` folds the versions of a partial run in DIR (e.g. the C 5.0 audit) into the
release's summaries."""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

RAW = ROOT / "results" / "nvhpc" / "raw"
MODES = (0, 2)


def _nv_settings(settings: str, x: int) -> str:
    """The run settings in NVHPC's terms: the audit tool's AMD wording
    ("HSA_XNACK=<key> (copy mode; ...)") names the memory mode instead."""
    import re
    mode = {0: "separate", 2: "managed"}[x]
    return re.sub(r"^HSA_XNACK=\d \(copy mode; programs that need "
                  r"zero-copy memory under HSA_XNACK=1\)",
                  f"-gpu=mem:{mode} (NVHPC {mode} memory, row key {x})",
                  settings)


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def dispositions(doc: dict) -> dict:
    """(mode, version, atom) -> disposition of a committed NV audit file."""
    return {(x, v, a): e.get("disposition", "")
            for x, m in doc.get("modes", {}).items()
            for v, atoms in m.get("versions", {}).items()
            for a, e in atoms.items()}


def compare(old: dict, new: dict) -> list[tuple]:
    """(mode, version, atom, old, new) for every differing disposition
    (a key in one file only shows "" on the other side)."""
    a, b = dispositions(old), dispositions(new)
    return sorted((*k, a.get(k, ""), b.get(k, "")) for k in set(a) | set(b)
                  if a.get(k, "") != b.get(k, ""))


def merge_versions(doc: dict, part: dict, x: int) -> dict:
    """`doc` (a committed NV audit file) with the versions of `part` (a
    partial run's summary, one mode) in mode `x`."""
    m = doc["modes"][str(x)]
    m["versions"].update(part["versions"])
    m.setdefault("merged_runs", []).append(part.get("run") or {})
    return doc


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--toolchain", default="nvhpc",
                    choices=("nvhpc", "nvhpc269"))
    ap.add_argument("--raw", type=Path, default=None,
                    help="the raw audit directory (default results/<tc>/raw)")
    ap.add_argument("--compare", action="store_true",
                    help="list the dispositions that differ from 25.11")
    ap.add_argument("--merge-versions", type=Path, default=None,
                    help="a directory of partial audit summaries to merge")
    a = ap.parse_args(argv)
    from offload.engine.report import NV_AUDIT, nv_audit_path
    if a.compare:
        n = 0
        for (model, lang), base in NV_AUDIT.items():
            own = base.with_name(base.name.replace("_nvhpc", "_nvhpc269"))
            if not own.is_file():
                print(f"{model} {lang}: no 26.9 audit ({_rel(own)})")
                continue
            diff = compare(json.loads(base.read_text()),
                           json.loads(own.read_text()))
            print(f"{model} {lang}: {len(diff)} dispositions differ")
            for d in diff:
                print("  mode {} {} {}: 25.11 {} / 26.9 {}".format(*d))
            n += len(diff)
        return 0
    if a.merge_versions:
        for (model, lang), base in NV_AUDIT.items():
            tag = ("accc" if lang == "c" else "acc") if model == "acc" else lang
            out = nv_audit_path(a.toolchain, model, lang)
            if (a.toolchain != "nvhpc" and out == base) or \
                    not out.is_file():
                continue
            doc = json.loads(out.read_text())
            hit = False
            for x in MODES:
                p = a.merge_versions / f"audit.{tag}.x{x}.summary.json"
                if p.is_file():
                    part = json.loads(p.read_text())
                    run = dict(part.get("run") or {})
                    if "settings" in run:
                        run["settings"] = _nv_settings(run["settings"], x)
                    part["run"] = dict(run, source=_rel(p))
                    merge_versions(doc, part, x)
                    hit = True
            if hit:
                out.write_text(json.dumps(doc, indent=1, sort_keys=True)
                               + "\n")
                print("merged ->", _rel(out))
        return 0
    raw = a.raw or ROOT / "results" / a.toolchain / "raw"
    name = {"nvhpc": "NVHPC 25.11", "nvhpc269": "NVHPC 26.9"}[a.toolchain]
    missing = False
    for (model, lang), base in NV_AUDIT.items():
        out = base if a.toolchain == "nvhpc" else base.with_name(
            base.name.replace("_nvhpc", f"_{a.toolchain}"))
        tag = ("accc" if lang == "c" else "acc") if model == "acc" else lang
        modes = {}
        paths = [raw / f"audit.{tag}.x{x}.summary.json" for x in MODES]
        if not all(p.is_file() for p in paths):
            print("missing", ", ".join(_rel(p) for p in paths
                                       if not p.is_file()), "(skipped)")
            missing = True
            continue
        for x in MODES:
            p = raw / f"audit.{tag}.x{x}.summary.json"
            doc = json.loads(p.read_text())
            run = dict(doc.get("run") or {})
            if "settings" in run:  # no AMD wording
                run["settings"] = _nv_settings(run["settings"], x)
            if isinstance(run.get("merged_into"), dict) and \
                    "settings" in run["merged_into"]:
                run["merged_into"] = dict(
                    run["merged_into"], settings=_nv_settings(
                        run["merged_into"]["settings"], x))
            modes[str(x)] = {"versions": doc["versions"],
                             "run": run,
                             "source": _rel(p)}
            c = Counter(e["disposition"] for vs in doc["versions"].values()
                        for e in vs.values())
            print(tag, x, dict(sorted(c.items())))
        out.write_text(json.dumps({
            "what": f"The oracle (mutation) audit on {name} "
                    "(wingtip, NVIDIA A100), per memory mode (row key 0 "
                    "separate, 2 managed); dispositions as in "
                    "tests/data/oracle_audit_summary*.json, for the "
                    f"toolchain {a.toolchain} alone",
            "modes": modes}, indent=1, sort_keys=True) + "\n")
        print("->", _rel(out))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
