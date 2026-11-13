#!/usr/bin/env python3
"""Why a copy_mode_only program fails in NVHPC managed memory.

Such a program tests whether host and device share memory with a probe on a
small local array (``zc``): map it, write it on the device, read it on the
host. In managed mode (-gpu=mem:managed) only dynamically allocated data is
managed, so the probe says "separate" while the heap arrays the program
checks are shared. This tool reruns each such program with the
probe changed: ``zc`` becomes heap data (Fortran allocatable, C malloc'd,
mapped as ``zc[0:1]``). A pass shows the probe caused it (class managed_shares_storage
in catalog/mode_differences.yaml); a failure goes to the confirmer.

    python3 -I tools/campaigns/nvhpc_managed_probe.py run --matrix A.jsonl B.jsonl \\
        --out results/nvhpc/managed_probe.jsonl      # on wingtip
    python3 -I tools/campaigns/nvhpc_managed_probe.py summary \\
        --out results/nvhpc/managed_probe.jsonl      # tests/data summary"""
import argparse
import dataclasses
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

SUMMARY = ROOT / "tests" / "data" / "nvhpc_managed_probe.json"
MANAGED = 2  # catalog/machines.yaml wingtip managed row key


def heap_probe(source: str, lang: str) -> str:
    """`source` with its shared-memory probe array on the heap; ValueError
    when the program has no such probe."""
    if lang == "c":
        if "int zc[1];" not in source or "map(to: zc)" not in source:
            raise ValueError("no zc probe")
        out = source.replace("int zc[1];", "int *zc = malloc(sizeof(int));",
                             1).replace("map(to: zc)", "map(to: zc[0:1])")
        if "#include <stdlib.h>" not in out:
            out = re.sub(r"^(#include [^\n]*\n)", r"\1#include <stdlib.h>\n",
                         out, count=1, flags=re.M)
        return out
    m = re.search(r"^(\s*)integer :: zc\(1\)\s*$", source, re.M)
    first = re.search(r"^(\s*)zc = 0\s*$", source, re.M)
    if m is None or first is None:
        raise ValueError("no zc probe")
    out = source[:m.start()] + f"{m.group(1)}integer, allocatable :: zc(:)" \
        + source[m.end():]
    first = re.search(r"^(\s*)zc = 0\s*$", out, re.M)
    return out[:first.start()] + f"{first.group(1)}allocate(zc(1))\n" + \
        out[first.start():]


def candidates(paths) -> list[dict]:
    """Rows of copy_mode_only legal programs that pass in separate memory
    (row key 0) and fail in managed memory (row key 2)."""
    rows = {}
    for p in paths:
        for ln in Path(p).read_text().splitlines():
            if ln.strip():
                r = json.loads(ln)
                if r["toolchain"] == "nvhpc":
                    rows[(r["program_id"], r["xnack"])] = r
    out = []
    for (pid, x), r in sorted(rows.items()):
        sep = rows.get((pid, 0))
        if x != MANAGED or sep is None or not r["legal"] or \
                r["evidence"] != "copy_mode_only":
            continue
        if sep["outcome"] == "correct_on_device" and \
                r["outcome"] == "wrong_answer":
            out.append(r)
    return out


def cmd_run(a) -> int:
    from offload.engine.gen import all_programs
    from offload.engine.harness import run_program
    from offload.engine.toolchains import TOOLCHAINS
    from offload.engine.run_matrix import for_version
    rows = candidates(a.matrix)
    progs = {}
    out = []
    for r in rows:
        v, lang = r["version"], r.get("lang", "f90")
        key = (v, lang)
        if key not in progs:
            if lang == "c":
                from offload.engine.c_gen import all_c_programs
                progs[key] = {p.id: p for p in all_c_programs(v)}
            else:
                progs[key] = {p.id: p for p in all_programs(v)}
        p = progs[key].get(r["program_id"])
        if p is None:
            continue
        try:
            src = heap_probe(p.source, lang)
        except ValueError as e:
            out.append({"program_id": p.id, "version": v, "lang": lang,
                        "status": "inapplicable", "why": str(e)})
            continue
        q = dataclasses.replace(p, source=src)
        tc = for_version(TOOLCHAINS["nvhpc"], v, lang)
        res = run_program(q, tc, MANAGED, timeout_s=120, repeats=3)
        out.append({"program_id": p.id, "version": v, "lang": lang,
                    "model": p.model, "original": r["outcome"],
                    "original_reason": r["reason"][:200],
                    "heap_probe": str(res.outcome),
                    "heap_probe_reason": res.reason[:200],
                    "flags": res.flags, "compiler": res.compiler,
                    "status": "explained" if str(res.outcome) ==
                    "correct_on_device" else "not_explained"})
        print(p.id, out[-1]["status"], res.reason[:80], flush=True)
    Path(a.out).write_text("".join(json.dumps(x) + "\n" for x in out))
    return 0


def cmd_summary(a) -> int:
    rows = [json.loads(ln) for ln in Path(a.out).read_text().splitlines()
            if ln.strip()]
    SUMMARY.write_text(json.dumps({
        "what": "Copy_mode_only programs correct in NVHPC separate "
                "memory and wrong in managed memory, rerun in managed "
                "memory with the shared-memory probe on the heap "
                "(tools/campaigns/nvhpc_managed_probe.py)",
        "programs": {r["program_id"]: {k: r.get(k) for k in (
            "status", "heap_probe", "heap_probe_reason", "compiler")}
            for r in rows}}, indent=1, sort_keys=True) + "\n")
    from collections import Counter
    print(Counter(r["status"] for r in rows))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--matrix", nargs="+", required=True)
    r.add_argument("--out", required=True)
    s = sub.add_parser("summary")
    s.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    return {"run": cmd_run, "summary": cmd_summary}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
