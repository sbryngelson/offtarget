"""Run the presence checks of the copy-mode programs at HSA_XNACK=1.

The catalog's copy_mode_only programs skip their checks under unified
memory, so their HSA_XNACK=1 cell reads "correct on device (copy-mode
evidence; not separable)". A presence check (omp_target_is_present) asks
about the device data environment, which the spec defines in both memory
modes. This tool builds each such program with only its presence checks
unguarded and runs it at HSA_XNACK=1 on every toolchain. Results go to
results/task26/presence_x1.jsonl (harness.Result rows, id <id>-presx1).

    python3 -I tools/campaigns/presence_x1.py --workers 16
    python3 -I tools/campaigns/presence_x1.py --only c:50 --workers 16

``--only c:50`` runs only the candidates of that language and version and
replaces their earlier rows in --out."""
import argparse
import dataclasses
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine.catalog import slice_atoms  # noqa: E402
from offload.engine.harness import run_program  # noqa: E402
from offload.engine.run_matrix import for_version, matrix_programs  # noqa: E402
from offload.engine.toolchains import TOOLCHAINS  # noqa: E402

OUT = ROOT / "results" / "task26" / "presence_x1.jsonl"
# the committed summary the support tables read (offload.engine.report)
SUMMARY = ROOT / "tests" / "data" / "presence_x1_summary.json"
_GUARD = re.compile(r"^(\s*)(?:if \(\.not\. shared_mem\)|if \(!shared_mem\)) "
                    r"(pres = .*omp_target_is_present.*)$", re.M)


def unguard(source: str) -> str:
    """`source` with the shared-memory guard removed from the presence
    checks only."""
    return _GUARD.sub(r"\1\2", source)


def candidates():
    """(version, Program) of the legal device programs with a guarded
    presence check (Fortran 5.0/5.2/6.0, C 5.2/6.0)."""
    out = []
    for lang, vs in (("f90", (50, 52, 60)), ("c", (50, 52, 60))):
        atoms = set().union(*(slice_atoms(v, lang=lang) for v in vs))
        for v, p in matrix_programs(atoms, vs, lang):
            if p.legal and p.scope == "device" and _GUARD.search(p.source):
                out.append((v, p))
    return out


def summary(rows, run: dict) -> dict:
    """{original program id: {toolchain: outcome}} of the runs."""
    progs: dict = {}
    for r in rows:
        pid = r["program_id"].removesuffix("-presx1")
        progs.setdefault(pid, {})[r["toolchain"]] = r["outcome"]
    return {"generated_by": "tools/campaigns/presence_x1.py",
            "run": run, "programs": dict(sorted(progs.items()))}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--toolchains", nargs="+",
                    default=["afar", "cce19", "cce20", "cce21"])
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--summary", type=Path, default=SUMMARY)
    ap.add_argument("--only", default=None,
                    help="LANG:VERSION: only these candidates, "
                    "merged into --out")
    ap.add_argument("--summary-only", action="store_true",
                    help="write the summary from an existing --out")
    ap.add_argument("--run-host", default=os.uname().nodename,
                    help="the node of the run (summary provenance)")
    ap.add_argument("--run-started",
                    default=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    help="the start time of the run")
    a = ap.parse_args(argv)
    if a.summary_only:
        rows = [json.loads(ln) for ln in a.out.read_text().splitlines()
                if ln.strip()]
        try:
            src = str(a.out.resolve().relative_to(ROOT))
        except ValueError:
            src = str(a.out)
        run = {"host": a.run_host, "started": a.run_started, "xnack": 1,
               "thp": sorted({r.get("thp", "") for r in rows}),
               "toolchains": sorted({r["toolchain"] for r in rows}),
               "repeats": 3, "source": src}
        a.summary.write_text(json.dumps(summary(rows, run), indent=1,
                                        sort_keys=True) + "\n")
        return 0
    started = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    jobs = []
    pick = None
    if a.only:
        lang_, ver = a.only.split(":")
        pick = (lang_, int(ver))
    for v, p in candidates():
        if pick and (("c" if p.lang == "c" else "f90"), v) != pick:
            continue
        q = dataclasses.replace(p, id=f"{p.id}-presx1",
                                source=unguard(p.source))
        lang = "c" if p.lang == "c" else "f90"
        for t in a.toolchains:
            jobs.append((q, for_version(TOOLCHAINS[t], v, lang)))

    def run(job):
        q, tc = job
        return run_program(q, tc, 1, "-O2", timeout_s=120, repeats=3)
    with ThreadPoolExecutor(a.workers) as ex:
        rs = list(ex.map(run, jobs))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    new = [json.dumps(dataclasses.asdict(r)) for r in rs]
    if pick and a.out.exists():
        ids = {r.program_id for r in rs}
        keep = [ln for ln in a.out.read_text().splitlines() if ln.strip()
                and json.loads(ln)["program_id"] not in ids]
        new = keep + new
    a.out.write_text("".join(x + "\n" for x in new))
    for r in rs:
        print(r.program_id, r.toolchain, r.outcome, r.reason[:80])
    return main(["--out", str(a.out), "--summary", str(a.summary),
                 "--summary-only", "--run-host", os.uname().nodename,
                 "--run-started", started])


if __name__ == "__main__":
    sys.exit(main())
