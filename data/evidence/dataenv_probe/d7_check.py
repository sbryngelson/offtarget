#!/usr/bin/env python3
"""Per-case check of decision D7 (CCE wrong answer
of a program with target simd lastprivate(conditional: x), x in no map
clause; the known finding fuzz/b2-209-cce19.f90). For each case the
program is regenerated, rewritten with an explicit map(tofrom: x) on
every such directive (what 5.2 §17.2 p.340 makes implicit for a
lastprivate item of a combined target construct), and run on the case's
toolchain in the case's memory mode, next to the original. The case is
confirmed when the original gives the stored wrong value and the
rewrite gives the model's value. JSON lines to OUT. On a compute node:
    python3 -I data/evidence/dataenv_probe/d7_check.py OUT CASE_ID..."""
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))
from offload.engine import fuzz, fuzz_exec  # noqa: E402
from offload.engine.toolchains import TOOLCHAINS  # noqa: E402

BASE = ("types", "derived", "alloc", "declare", "multitu")
DIRECTIVE = re.compile(r"!\$omp target simd[^\n]*(?:&\s*\n\s*!\$omp&[^\n]*)*",
                       re.I)


def with_map(src: str) -> tuple[str, list[str]]:
    """`src` with map(tofrom: x) added to each target simd directive with
    lastprivate(conditional: x) and no map of x; the items added."""
    added = []

    def fix(m):
        text = m.group(0)
        flat = re.sub(r"&\s*\n\s*!\$omp&", " ", text)
        lp = re.search(r"lastprivate\(conditional:\s*(\w+)\)", flat, re.I)
        if not lp or re.search(rf"map\([^)]*\b{lp.group(1)}\b", flat, re.I):
            return text
        added.append(lp.group(1))
        first, nl, rest = text.partition("\n")
        if first.rstrip().endswith("&"):
            first = first.rstrip()[:-1].rstrip() + \
                f" map(tofrom: {lp.group(1)}) &"
        else:
            first = first.rstrip() + f" map(tofrom: {lp.group(1)})"
        return first + nl + rest
    return DIRECTIVE.sub(fix, src), added


def run(tc, text, xnack):
    fuzz_exec.XNACK = xnack
    with tempfile.TemporaryDirectory(prefix="d7_") as d:
        d = Path(d)
        (d / "p.f90").write_text(text)
        cls, reason, _, _ = fuzz_exec.compile_program(
            tc, d / "p.f90", d / "p.out", d)
        if cls:
            return {"compile": cls, "reason": reason[:200]}
        r = fuzz_exec.execute(tc, d / "p.out", d, "mandatory")
        return {"kind": r.kind, "checksum": r.checksum, "host": r.host,
                "why": r.why}


def main() -> int:
    out = Path(sys.argv[1])
    rows = []
    for cid in sys.argv[2:]:
        _, _, seed, tcn, _, mode = cid.split(":")
        prog = fuzz.generate(int(seed), "fuzz-3", BASE)
        new, added = with_map(prog.source)
        xnack = 1 if mode == "unified" else 0
        tc = TOOLCHAINS[tcn]
        row = {"case": cid, "expected": prog.expected, "added": added,
               "original": run(tc, prog.source, xnack),
               "explicit_map": run(tc, new, xnack)}
        row["confirmed"] = bool(
            added and row["original"].get("checksum") not in
            (None, prog.expected) and
            row["explicit_map"].get("checksum") == prog.expected)
        rows.append(row)
        print(json.dumps(row), flush=True)
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
