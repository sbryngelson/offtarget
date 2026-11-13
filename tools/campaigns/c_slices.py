#!/usr/bin/env python3
"""Expected values of the two C slices.

    python3 -I tools/campaigns/c_slices.py expected --slice c50    # OpenMP 5.0 C
    python3 -I tools/campaigns/c_slices.py expected --slice accc   # OpenACC 3.4 C

For every legal device-scope program whose expectation is a result, the record
(catalog format, tools/derive/expected.py) holds the program's own oracle, the
result of sequential elision, and the matrix runs of that memory mode
(results/matrix_c.jsonl, results/acc_matrix_c.jsonl). Elision builds the
program without OpenMP/OpenACC by gcc and AFAR amdclang against a declaration
stub and runs it on the host. For OpenMP C it applies as the Fortran original's
analysis says (offload.engine.expected.elision_applicability); for OpenACC C unless
the program checks copy semantics or is hand written.
Writes results/expected/c50.jsonl or results/expected/accc.jsonl (plus the
.xnack variants that exist), each with a .meta.json, and prints the verdicts."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

OUT = ROOT / "results" / "expected"

SEQ_OMP_C = """\
/* Sequential OpenMP runtime for the elision of the C 5.0 programs
: one initial thread on the host, no devices (OpenMP 5.0
   §3: the initial device is the host; omp_get_num_devices() = 0 and the
   initial device number equals it). Built without -fopenmp. */
#include <stddef.h>
int omp_is_initial_device(void) { return 1; }
int omp_get_thread_num(void) { return 0; }
int omp_get_num_threads(void) { return 1; }
int omp_get_team_num(void) { return 0; }
int omp_get_num_teams(void) { return 1; }
int omp_get_num_devices(void) { return 0; }
int omp_get_default_device(void) { return 0; }
int omp_get_device_num(void) { return 0; }
int omp_get_initial_device(void) { return 0; }
int omp_get_num_places(void) { return 0; }
int omp_target_is_present(const void *p, int d) { (void)p; (void)d; return 1; }
"""

SEQ_ACC_C = """\
/* Sequential OpenACC runtime for the elision of the OpenACC C programs
: the host is the only device (OpenACC 3.4 §3.2), so data is
   present on it. Built without -fopenacc. */
#include <stddef.h>
typedef enum acc_device_t {
  acc_device_none = 0, acc_device_default = 1, acc_device_host = 2,
  acc_device_not_host = 3, acc_device_nvidia = 4
} acc_device_t;
int acc_on_device(acc_device_t t) { return t == acc_device_host; }
int acc_is_present(void *h, size_t n) { (void)h; (void)n; return 1; }
acc_device_t acc_get_device_type(void) { return acc_device_host; }
int acc_get_device_num(acc_device_t t) { (void)t; return 0; }
"""

ELISION_COMPILERS = ("gcc", "amdclang")

# OpenACC C atoms whose program's result depends on what only a device
# execution does (no elision analysis exists for OpenACC; listed by hand,
# as the widened catalog's spec.elision field): the host run differs
ACC_NO_ELISION = {
    "acc.clause.bind": "the device calls the bound procedure (dev_val); "
    "the host calls the procedure itself, which returns -x",
    "acc.clause.private": "the region's writes go to private copies; the "
    "sequential host run writes the variable itself",
    "acc.clause.firstprivate": "the region's writes go to firstprivate "
    "copies; the sequential host run writes the variable itself",
    "acc.clause.firstprivate.implicit_scalar": "the scalar is firstprivate "
    "on the device; the sequential host run writes the variable itself",
}


def _cc(compiler: str) -> str:
    if compiler == "gcc":
        import shutil
        return shutil.which("gcc") or "/usr/bin/gcc"
    from offload.engine.toolchains import AFAR_BIN
    return f"{AFAR_BIN}/amdclang"


def run_elided(source: str, compiler: str, slice_: str,
               timeout: int = 60) -> tuple[str | None, str]:
    """(value, note) of `source` built by `compiler` without OpenMP or
    OpenACC against the slice's header stub and sequential runtime."""
    from offload.engine.acc_c_gen import OPENACC_H_STUB
    from offload.engine.c_gen import OMP_H_STUB
    from offload.engine.expected import value_of
    with tempfile.TemporaryDirectory(prefix="t37_elided_") as d:
        dd = Path(d)
        if slice_ == "accc":
            (dd / "openacc.h").write_text(OPENACC_H_STUB)
            (dd / "rt.c").write_text(SEQ_ACC_C)
        else:
            (dd / "omp.h").write_text(OMP_H_STUB)
            (dd / "rt.c").write_text(SEQ_OMP_C)
        (dd / "p.c").write_text(source)
        exe = str(dd / "p.out")
        cmd = [_cc(compiler), "-O0", "-std=c11", "-Wno-unknown-pragmas",
               "-I" + d, "p.c", "rt.c", "-lm", "-o", exe]
        b = subprocess.run(cmd, cwd=d, capture_output=True, text=True,
                           timeout=300)
        if b.returncode != 0:
            err = [ln for ln in (b.stderr + b.stdout).splitlines()
                   if "rror" in ln]
            return None, f"{compiler} build failed: " + (
                err[0] if err else f"rc={b.returncode}")[:200]
        try:
            r = subprocess.run(["bash", "-c", 'ulimit -c 0; exec "$0"', exe],
                               cwd=d, capture_output=True, text=True,
                               timeout=timeout, env={"PATH": "/usr/bin:/bin"})
        except subprocess.TimeoutExpired:
            return None, f"{compiler} run timed out"
        if r.returncode != 0:
            return None, f"{compiler} run failed: rc={r.returncode}"
        v = value_of(r.stdout)
        if v is None:
            return None, f"{compiler}: no single RESULT line"
        return v, ""


def programs(slice_: str) -> list:
    """The legal device-scope programs of the slice."""
    if slice_ == "accc":
        from offload.engine.acc_c_gen import all_acc_c_programs
        progs = all_acc_c_programs()
    else:
        from offload.engine.c_gen import all_c_programs
        progs = all_c_programs(50)
    return [p for p in progs if p.legal and p.scope == "device"]


def applicability(p, slice_: str) -> tuple[bool, str]:
    """(elision applies, why not)."""
    if p.expect != "result":
        return False, (f"the program expects {p.expect} (a probe), not a "
                       "result")
    if slice_ == "accc":
        from offload.engine import acc_c_gen as A
        if p.evidence == "copy_mode_only":
            return False, ("the check reads copy semantics: elision runs the "
                           "shared-memory branch")
        if p.primary_atom in ACC_NO_ELISION:
            return False, ACC_NO_ELISION[p.primary_atom]
        if p.primary_atom in A.HAND:
            return False, ("a hand-written port (acc_c_gen.HAND): no "
                           "elision analysis")
        return True, ""
    from offload.engine import c_gen as CG
    from offload.engine import expected as E
    if p.primary_atom in CG.C_EDITS or p.primary_atom in CG.C_LABELS:
        return False, ("a C edit or relabel of the port: the Fortran "
                       "program's elision analysis does not cover it")
    from offload.engine import gen as G
    f = G._legal(CG.fortran_atom(p.primary_atom), 50)
    ap = E.elision_applicability(f.source, 50)
    why = ap.why if isinstance(ap.why, str) else "; ".join(ap.why)
    return ap.ok, why[:400] if not ap.ok else ""


def elision(p, slice_: str) -> dict:
    from offload.engine.expected import Evidence
    ok, why = applicability(p, slice_)
    if not ok:
        return Evidence("elision", "inapplicable", detail=why).to_dict()
    obs, notes = [], []
    for c in ELISION_COMPILERS:
        v, note = run_elided(p.source, c, slice_)
        obs.append((c, v))
        if note:
            notes.append(note)
    vals = sorted({v for _, v in obs if v is not None})
    if len(vals) == 1 and all(v is not None for _, v in obs):
        ev = Evidence("elision", "value", vals[0], "; ".join(notes),
                      tuple(obs))
    elif len(vals) > 1:
        ev = Evidence("elision", "conflict", None, "the elided builds "
                      "disagree", tuple(obs))
    else:
        ev = Evidence("elision", "no_value", None,
                      "; ".join(notes) or "no value", tuple(obs))
    return ev.to_dict()


def _toolrun(r: dict) -> dict:
    from offload.engine.expected import value_of
    v = value_of(r.get("stdout", "")) if r["outcome"] in (
        "correct_on_device", "wrong_answer", "fell_back_to_host") else None
    m = re.search(r"ran_on_host=([01])", r.get("stdout", ""))
    return {"toolchain": r["toolchain"], "variant": "original", "value": v,
            "ran_on_host": int(m.group(1)) if m else None, "probe": None,
            "why": "" if v else r.get("reason", "")[:200],
            "xnack": r["xnack"]}


def _audit_disposition(slice_: str) -> dict:
    """atom -> the audit disposition (AMD audit for C 5.0, NVHPC 25.11
    separate memory for OpenACC C)."""
    from offload.engine import report as R
    if slice_ == "accc":
        path = R.NV_AUDIT[("acc", "c")]
        if not path.is_file():
            return {}
        doc = json.loads(path.read_text())
        vs = doc.get("modes", {}).get("0", {}).get("versions", {})
    else:
        if not R.C_AUDIT.is_file():
            return {}
        vs = json.loads(R.C_AUDIT.read_text()).get("versions", {})
    v = "34" if slice_ == "accc" else "50"
    return {a: e.get("disposition", "") for a, e in vs.get(v, {}).items()}


def records(progs, els: dict, matrix: list[dict], slice_: str) -> dict:
    """(file suffix) -> records: "" (the main record), ".xnack0",
    ".g90.xnack0", ".nvhpc.xnack0" ... (the runs of each mode/machine)."""
    v = 34 if slice_ == "accc" else 50
    disp = _audit_disposition(slice_)
    by = {}
    for r in matrix:
        by.setdefault(r["program_id"], []).append(r)

    def group(r):
        tc, x = r["toolchain"], r["xnack"]
        if slice_ == "accc":
            return "" if x == 0 else f".xnack{x}"
        if tc.endswith("_g90"):
            return ".g90.xnack0"
        if tc.startswith("nvhpc"):
            return f".nvhpc.xnack{x}"
        return "" if x == 1 else f".xnack{x}"

    out: dict = {}
    for p in progs:
        rows = by.get(p.id, [])
        groups = sorted({group(r) for r in rows} | {""})
        for g in groups:
            runs = [_toolrun(r) for r in rows if group(r) == g]
            x = 0 if slice_ == "accc" and g == "" else (
                1 if g == "" else int(g[-1]))
            out.setdefault(g, []).append({
                "key": f"{v}:{p.id}", "version": v, "program": p.id,
                "atom": p.primary_atom, "mismatches": [],
                "audit": disp.get(p.primary_atom, ""),
                "evidence_level": p.evidence, "expect": p.expect,
                "kind": "catalog", "model": "check=pass",
                "model_detail": "the program's own oracle",
                "elision": els.get(p.id) if g == "" else None,
                "variants": {"probe": "n/a: no presence-probe variant "
                                      "(C slice)"},
                "runs": sorted(runs, key=lambda r: r["toolchain"]),
                "xnack": x})
    return out


def cmd_expected(a) -> int:
    from offload.engine import report as R
    progs = [p for p in programs(a.slice) if p.expect == "result"]
    mfile = R.ACC_C_MATRIX if a.slice == "accc" else R.C_MATRIX
    want = {p.id for p in progs}
    matrix = [r for r in (json.loads(ln) for ln in
                          mfile.read_text().splitlines() if ln.strip())
              if r["program_id"] in want]
    with ThreadPoolExecutor(a.workers) as ex:
        els = dict(zip([p.id for p in progs],
                       ex.map(lambda p: elision(p, a.slice), progs)))
    recs = records(progs, els, matrix, a.slice)
    OUT.mkdir(parents=True, exist_ok=True)
    meta = {"generated_by": f"python3 -I tools/campaigns/c_slices.py expected --slice "
                            f"{a.slice}",
            "date": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "sources": "the program's own oracle; sequential elision (gcc, "
                       f"amdclang); the matrix runs ({mfile.name})"}
    for g, rs in recs.items():
        path = OUT / f"{a.slice}{g}.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rs))
        path.with_suffix(".meta.json").write_text(json.dumps(
            dict(meta, group=g or "main"), indent=1))
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    import expected as TE
    c = Counter(TE.evaluate(r)[1].status for r in recs[""])
    el = Counter(e["status"] for e in els.values())
    print(f"{len(recs[''])} records -> results/expected/{a.slice}.jsonl: "
          f"{dict(c)}; elision {dict(el)}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("expected")
    e.add_argument("--slice", choices=("c50", "accc"), required=True)
    e.add_argument("--workers", type=int, default=8)
    a = ap.parse_args(argv)
    return {"expected": cmd_expected}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
