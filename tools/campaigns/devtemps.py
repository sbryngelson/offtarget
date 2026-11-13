#!/usr/bin/env python3
"""Which programs put heap allocations inside device code on AFAR
(offload/engine/devtemps.py): compile only, no GPU.

    python3 -I tools/campaigns/devtemps.py scan SET [--workers N] [--limit N]
    python3 -I tools/campaigns/devtemps.py table [SET ...]

SET: findings (findings *.f90), catalog (offload.engine.gen, OpenMP 5.2),
fuzz (seeds 1-200), stress (the first campaign's rows), nested (results/nested/main/src),
oop (offload.engine.oop_gen), kbody (the trial and the neighbourhood: results/kbody/{pilot,nbhd}
programs.jsonl sources are regenerated), or a directory of .f90 files. Each program is compiled
with the harness's AFAR recipe plus ``-O2 -save-temps -c`` in a scratch directory (a
multi-file program file by file, in order); the device FIR (``*-gfx942-fir.mlir``) is read by
``offload.engine.devtemps.scan_fir``. Records -> results/devtemps/SET.jsonl (resumable).
Run on a compute node (``flux run -q pdebug -N1 -n1 -t 30m --job-name=compile-test-devtemps``).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine import devtemps as D  # noqa: E402

OUT = ROOT / "results" / "devtemps"
COMPILE_S = 240


def sources(name: str):
    """Yield (id, [(filename, text)], meta)."""
    if name == "findings":
        for f in sorted((ROOT / "data" / "findings").rglob("*.f90")):
            yield f.name, [(f.name, f.read_text())], {"path": str(f.relative_to(ROOT))}
    elif name == "catalog":
        from offload.engine import gen as G
        from offload.engine.catalog import slice_atoms
        for p in G.generate(slice_atoms(52), 52):
            yield p.id, [("p.f90", p.source)], {}
    elif name == "fuzz":
        from offload.engine import fuzz
        for seed in range(1, 201):
            try:
                p = fuzz.generate(seed)
            except Exception:
                continue
            yield f"fuzz-{seed}", [("p.f90", p.source)], {}
    elif name == "stress":
        from offload.engine import stress
        seen = set()
        sp = ROOT / "results" / "stress" / "arm1-stress" / "stress" / "programs.jsonl"
        for line in sp.read_text().splitlines():
            r = json.loads(line)
            key = (r["axis"], r["size"], r["seed"], r["model"], r["layout"])
            if key in seen or r["model"] != "omp":
                continue
            seen.add(key)
            try:
                p = stress.build(*key)
            except Exception:
                continue
            yield r["id"], list(p.files), {"axis": r["axis"]}
    elif name == "nested":
        for f in sorted((ROOT / "results" / "nested" / "main" / "src").glob("*.f90")):
            if "-omp-" in f.name:
                yield f.stem, [("p.f90", f.read_text())], {}
    elif name == "oop":
        from offload.engine import oop_gen
        for p in oop_gen.programs():
            if p.model == "omp":
                yield p.id, [("p.f90", p.source)], {}
    elif name == "kbody-heap":
        from offload.engine import kbody_gen as G
        for c in G.heap_cfgs():
            p = G.program(c)
            a = p.axes
            yield p.id, [("p.f90", p.source)], {
                "loc": a["loc"], "tgt": a["tgt"], "claim": a["claim"],
                "storage": a["storage"], "heap_guess": a["heap_guess"]}
    elif name in ("kbody-pilot", "kbody-nbhd"):
        from offload.engine import kbody_gen as G
        spec = json.loads((ROOT / "results" / "kbody" / name.split("-")[1] / "meta.json").read_text())
        import importlib.util
        t = importlib.util.spec_from_file_location("kbody_tool", ROOT / "tools" / "campaigns" / "kbody.py")
        m = importlib.util.module_from_spec(t)
        t.loader.exec_module(m)
        for p in m.sample(spec):
            if p.lang == "f90":
                a = p.axes
                yield p.id, [("p.f90", p.source)], {
                    "loc": a["loc"], "tgt": a["tgt"], "claim": a["claim"],
                    "ctype": a["ctype"], "aux": a["aux"], "rec": a["rec"],
                    "legality": p.legality}
    elif Path(name).is_dir():
        for f in sorted(Path(name).glob("*.f90")):
            yield f.stem, [(f.name, f.read_text())], {}
    else:
        raise SystemExit(f"unknown set {name}")


def compile_scan(job) -> dict:
    from offload.engine import harness
    from offload.engine.toolchains import TOOLCHAINS
    pid, files, meta = job
    tc = TOOLCHAINS["afar"]
    tmp = Path(tempfile.mkdtemp(prefix="devtemps_"))
    try:
        for n, t in files:
            (tmp / n).write_text(t)
        rec = {"id": pid, **meta}
        scans = []
        for n, _ in files:
            if not n.endswith((".f90", ".F90")):
                continue
            cmd = f"{tc.compiler()} {tc.flags()} -O2 -save-temps -c {n}"
            if tc.prelude:
                cmd = f"{tc.prelude}\n{cmd}"
            ex = harness._execute(f"ulimit -c 0\n{cmd}\n", tmp, COMPILE_S, merge=True)
            if ex.timed_out:
                rec["compile"] = "timeout"
                return rec
            if ex.rc != 0:
                rec["compile"] = "failed"
                rec["log"] = ex.stdout[-300:]
                return rec
            for f in tmp.glob(f"{Path(n).stem}-openmp-*gfx942-fir.mlir"):
                scans.append(D.scan_fir(f.read_text()))
        rec["compile"] = "ok"
        rec.update(D.summarize(scans))
        return rec
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def cmd_scan(a) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{a.set.replace('/', '_')}.jsonl"
    done = set()
    if out.exists():
        done = {json.loads(l)["id"] for l in out.read_text().splitlines() if l}
    jobs = [j for j in sources(a.set) if j[0] not in done]
    if a.limit:
        jobs = jobs[:a.limit]
    print(f"{a.set}: {len(jobs)} programs to compile", flush=True)
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futs = [pool.submit(compile_scan, j) for j in jobs]
        for f in as_completed(futs):
            with open(out, "a") as fh:
                fh.write(json.dumps(f.result(), sort_keys=True) + "\n")
    return 0


def cmd_table(a) -> int:
    sets = a.sets or sorted(p.stem for p in OUT.glob("*.jsonl"))
    print("| set | programs | compiled | with a device region | allocating in device code | share |")
    print("|---|---|---|---|---|---|")
    cls_all = defaultdict(Counter)
    for s in sets:
        rows = [json.loads(l) for l in (OUT / f"{s}.jsonl").read_text().splitlines() if l]
        ok = [r for r in rows if r.get("compile") == "ok"]
        reg = [r for r in ok if r["regions"]]
        risk = [r for r in reg if D.row_at_risk(r)]
        print(f"| {s} | {len(rows)} | {len(ok)} | {len(reg)} | {len(risk)} | "
              f"{(100 * len(risk) / len(reg)) if reg else 0:.0f}% |")
        for r in risk:
            for c, n in r["classes"].items():
                cls_all[s][c] += 1
            if not r["classes"]:
                cls_all[s]["only allocating runtime calls"] += 1
    print()
    print("| set | temporary class | programs |")
    print("|---|---|---|")
    for s, c in cls_all.items():
        for k, v in c.most_common():
            print(f"| {s} | {k} | {v} |")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("set")
    s.add_argument("--workers", type=int, default=12)
    s.add_argument("--limit", type=int, default=0)
    t = sub.add_parser("table")
    t.add_argument("sets", nargs="*")
    a = ap.parse_args(argv)
    return {"scan": cmd_scan, "table": cmd_table}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
