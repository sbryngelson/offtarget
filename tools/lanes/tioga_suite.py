#!/usr/bin/env python3
"""The tests the wingtip lane leaves for Tuolumne (its tuolumne.txt), run
on Tioga where they can (docs/tooling/wingtip.md, "Tests left for Tuolumne, on
Tioga"; tools/lanes/run_tioga_suite.sh does the copy, the job and the pull).

    python3 -I tools/lanes/tioga_suite.py split TUOLUMNE_TXT OUTDIR
    python3 -I tools/lanes/tioga_suite.py copy-files < NUL-separated paths
    python3 -I tools/lanes/tioga_suite.py inputs           # the corpus/ inputs
    python3 -I tools/lanes/tioga_suite.py after TUOLUMNE_TXT OUTDIR JUNIT...

`split` writes OUTDIR/<class>.txt per class (CLASSES; a node id's class is
that of the longest RULES prefix, `tuolumne` without one). `after` reads
the Tioga run's junit files and writes OUTDIR/tioga.txt (passed there),
OUTDIR/failed.tsv and OUTDIR/tuolumne.txt: every id that did not pass on
Tioga (failed, skipped, not run or not classed for Tioga), for the next
Tuolumne job."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tools"), str(ROOT / "tools" / "lanes")]

CLASSES = {
    "tioga": "runs on Tioga as is",
    "tioga-afar": "runs on Tioga with AFAR's run-time libraries on "
                  "LD_LIBRARY_PATH (as afar_g90 runs)",
    "tioga-nogpu": "runs on Tioga with the GPU hidden (ROCR_VISIBLE_DEVICES)",
    "tioga-inputs": "runs on Tioga with git-ignored inputs copied there",
    "mi300a": "a gfx942 device run or HSA_XNACK=1: Tuolumne",
    "sealed": "an unscored sealed set or holdout-derived rows: Tuolumne",
    "skips": "skips on every machine by design",
    "tuolumne": "not classed: stays on Tuolumne",
}
ON_TIOGA = ("tioga", "tioga-afar", "tioga-nogpu", "tioga-inputs")

_NODE = ("the fake toolchains target gfx942: on gfx90a the harness's node "
         "check refuses them; with no GPU visible it does not apply")
_AFAR = "AFAR's front end (the /p/vast1 copy, offload.engine.toolchains)"
_GF = "gfortran 13.3.1 (/usr/tce/bin, as on Tuolumne)"
_WEB = "node and Chrome (both on Tioga)"
_AGF = _AFAR + "; " + _GF
_G942 = "builds for gfx942 and runs on the device"
# node-id prefix -> (class, why); the longest prefix of an id decides.
# Measured on tioga35, 2026-11-03 (docs/tooling/wingtip.md).
RULES = {
    "tests/engine/test_findings_nogpu.py": ("tioga-nogpu", _NODE),
    "tests/engine/test_findings_nogpu.py::test_hang_control_times_out_at_baseline_opt":
        ("mi300a", _G942 + " at HSA_XNACK=1"),
    "tests/engine/test_acc.py": ("tioga-nogpu", _NODE),
    "tests/cluster/test_campaigns_nogpu.py": ("tioga-nogpu", _NODE),
    "tests/engine/test_fuzz_afar.py": ("tioga-afar", _AFAR),
    "tests/engine/test_c.py": ("tioga-afar", _AFAR),
    "tests/engine/test_findings_afar.py": ("tioga-afar", _AGF),
    "tests/confirm/test_confirm_legality.py": ("tioga-afar", _AGF),
    "tests/cluster/test_widen.py": ("tioga-afar", _AGF),
    "tests/dataenv/test_dataenv_gen.py": ("tioga-afar", _AFAR),
    "tests/engine/test_fuzz_afar.py::test_minimizer_on_the_cce19_guarded_loop":
        ("mi300a", "CCE 19 " + _G942),
    "tests/cluster/test_toolchains.py": ("mi300a", _G942),
    "tests/cluster/test_toolchains.py::test_rocm_version_recorded":
        ("tioga", "the CCE 19 modules (on Tioga too)"),
    "tests/bench/test_wild_bench.py": ("tioga", _GF),
    "tests/site/test_site_web.py": ("tioga", _WEB),
    "tests/engine/test_spec_text.py": ("tioga", "results/ is a directory of a git "
                                "copy there, not a link"),
    "tests/bench/test_apps.py": ("tioga-inputs", "the application sources "
                           "(`inputs`)"),
    "tests/engine/test_canary.py": ("mi300a", "skips unless the GPU is gfx942"),
    "tests/bench/test_harvest_runtime.py": ("mi300a", _G942),
    "tests/bench/test_holdout_exposure.py": ("sealed", "the unscored sealed sets"),
    "tests/bench/test_harvest_known.py": ("sealed", "the unscored sealed set"),
    "tests/engine/test_check_findings.py": ("sealed", "full mode reads results/ "
                                     "row files and their src/, holdout "
                                     "programs among them"),
    "tests/engine/test_gen.py": ("skips", "5.1 and 5.2 features at version 50"),
    "tests/cluster/test_standing_rules.py": ("skips", "no shared_frontends in "
                                     "catalog/machines.yaml yet"),
}


def _under(nid: str, prefix: str) -> bool:
    return nid == prefix or nid.startswith((prefix + "::", prefix + "["))


def classify(nid: str) -> tuple[str, str]:
    """(class, why) of a node id (or node-id prefix)."""
    best = max((p for p in RULES if _under(nid, p)), key=len, default="")
    return RULES[best] if best else ("tuolumne", CLASSES["tuolumne"])


def split(ids) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for i in ids:
        out.setdefault(classify(i)[0], []).append(i)
    return out


def copy_files(paths) -> list[str]:
    """The paths that may go to Tioga: no sealed unscored set
    (tools/lanes/wingtip_offline.py) and no holdout set, scored or not."""
    import wingtip_offline as WO
    keep, _ = WO.code_files(paths)
    return [p for p in keep if not re.match(r"data/bench/[^/]*holdout(/|$)", p)]


def inputs(root: Path = ROOT) -> list[str]:
    """The corpus/ files the `tioga-inputs` tests read: each application's
    sources (offload.engine.apps); an application built by its own build
    system has none, so its top-level CMakeLists.txt (the clone exists)."""
    from offload.engine import apps as A
    out = []
    for a in A.load().values():
        files = [p for prog in a.programs for _, p in A.source_paths(prog, a)]
        files = files or [a.path / "CMakeLists.txt"]
        for p in files:
            rel = Path(p).relative_to(root)
            if rel.parts[0] == "corpus":
                out.append(str(rel))
    return sorted(set(out))


def after_tioga(ids, junits) -> dict:
    """{"passed": test ids passed on Tioga, "failed": [(id, reason)],
    "left": ids for Tuolumne}: a node id (or prefix) is done when every
    test of it that ran passed, and at least one ran; else its tests that
    did not pass stay (the id itself when none ran)."""
    import wingtip_suite as WS
    rows = WS.read_junit(junits)
    res = {"passed": [], "failed": [], "left": []}
    for i in ids:
        mine = [r for r in rows if _under(r["id"], i)]
        res["passed"] += [r["id"] for r in mine if r["outcome"] == "passed"]
        res["failed"] += [(r["id"], r["reason"]) for r in mine
                          if r["outcome"] in ("failed", "error")]
        res["left"] += [r["id"] for r in mine if r["outcome"] != "passed"] \
            if mine else [i]
    return res


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else ""
    if cmd == "split" and len(argv) == 3:
        ids = Path(argv[1]).read_text().split()
        out = Path(argv[2])
        out.mkdir(parents=True, exist_ok=True)
        for cls, mine in split(ids).items():
            (out / f"{cls}.txt").write_text("".join(i + "\n" for i in mine))
            print(f"{cls:13} {len(mine):4}  {CLASSES[cls]}")
        return 0
    if cmd == "copy-files" and len(argv) == 1:
        paths = [p for p in sys.stdin.buffer.read().decode().split("\0") if p]
        sys.stdout.write("".join(p + "\0" for p in copy_files(paths)))
        return 0
    if cmd == "inputs" and len(argv) == 1:
        print("\n".join(inputs()))
        return 0
    if cmd == "after" and len(argv) >= 4:
        ids = Path(argv[1]).read_text().split()
        out = Path(argv[2])
        res = after_tioga(ids, [Path(j) for j in argv[3:]])
        (out / "tioga.txt").write_text("".join(i + "\n" for i in
                                               res["passed"]))
        (out / "failed.tsv").write_text("".join(f"{i}\t{w}\n" for i, w in
                                                res["failed"]))
        (out / "tuolumne.txt").write_text("".join(i + "\n" for i in
                                                  res["left"]))
        summary = {k: len(v) for k, v in res.items()}
        (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
        print(json.dumps(summary))
        for i, w in res["failed"]:
            print("FAILED", i, w[:200])
        return 1 if res["failed"] else 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
