#!/usr/bin/env python3
"""The in-the-wild bug benchmark (data/bench/wild/).

Each case is one file data/bench/wild/<id>.<f90|c> (a file set with ``!@file`` /
``//@file`` marks). Its header names the source URL, the edits made, the
expected output (``expected:``) and build options (``wild-opt:``, and
``wild-opt-afar:`` for AFAR only). data/bench/wild/cases.yaml holds the metadata.

    python3 -I tools/wild/wild_bench.py parse       # base-language parse of every case
    python3 -I tools/wild/wild_bench.py legality    # the confirmer's legality gate
    python3 -I tools/wild/wild_bench.py run --toolchains afar cce19 [--modes unified copy] [--jobs N]

``run`` uses the confirmer's runners (local, or ssh) with
OMP_TARGET_OFFLOAD=mandatory, two runs per program. Results go to
results/wild/."""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

BENCH = ROOT / "data" / "bench" / "wild"
OUT = ROOT / "results" / "wild"
F_MARK, C_MARK = "!@file ", "//@file "
# a case's OpenMP version for the version flags: 5.2 unless it needs 6.0
VERSION_60 = {"llvm-180503"}
REPEATS = 2
# compile failures the harness message tables do not classify
# (unclassified_compile_failure), read by hand from the compiler output:
# (case, toolchain) -> (outcome, reason)
HAND_CLASSIFIED = {
    ("llvm-217112", "afar"): ("ice", "hand-read compiler output: 'Operand is "
                              "null / store i32 %11, <null operand!> / error: "
                              "failed to create the LLVM module'"),
    ("llvm-170504", "nvhpc"): ("ice", "hand-read compiler output: 'llvm/bin/opt"
                               ": ... error: use of undefined value "
                               "%.S0000' (invalid IR from the front end)"),
    ("llvm-170504", "nvhpc269"): ("ice", "the same compile as nvhpc 25.11 "
                                  "(unclassified rc=2; output not re-read)"),
}


def _flang() -> str:
    from offload.engine.toolchains import AFAR_BIN
    return f"{AFAR_BIN}/amdflang"


FLANG = _flang()


def case_files() -> list[Path]:
    return sorted([*BENCH.glob("*.f90"), *BENCH.glob("*.c")])


def header(path: Path) -> dict:
    """The header fields of a case file (its leading comment lines)."""
    lead = "//" if path.suffix == ".c" else "!"
    out: dict = {"edits": []}
    in_edits = False
    for line in path.read_text().splitlines():
        if not line.startswith(lead) or line.startswith(F_MARK) or \
                line.startswith(C_MARK):
            break
        body = line[len(lead):].strip()
        m = re.match(r"(wild case|source|also|edits|expected|wild-opt|"
                     r"wild-opt-afar):\s*(.*)$", body)
        if m:
            key, val = m.group(1), m.group(2)
            in_edits = key == "edits"
            if key == "also":
                out.setdefault("also", []).append(val)
            elif key != "edits":
                out[key] = val
            elif val:
                out["edits"].append(val)
        elif in_edits and body:
            out["edits"].append(body)
    return out


def split(path: Path) -> list[tuple[str, str]]:
    """The files of a case: [(name, text)] in compile order."""
    from offload.engine.confirm.programs import split_files
    text = path.read_text()
    return split_files(text) or [(path.name, text)]


def lang_of(path: Path) -> str:
    return "c" if path.suffix == ".c" else "f90"


def model_of(path: Path) -> str:
    text = path.read_text()
    omp = re.search(r"(?im)^\s*(!\$omp|#\s*pragma\s+omp)\b", text)
    acc = re.search(r"(?im)^\s*(!\$acc|#\s*pragma\s+acc)\b", text)
    return "acc" if acc and not omp else "omp"


def load_cases() -> dict:
    import yaml
    d = yaml.safe_load((BENCH / "cases.yaml").read_text())
    return {c["id"]: c for c in d["cases"]}


# --- parse ---------------------------------------------------------------------

def parse_one(path: Path) -> tuple[bool, str]:
    """Whether the case parses as a program of its language: gfortran
    -std=gnu -fsyntax-only (directives are comments) over its file set in
    order, or gcc -std=gnu11 -fsyntax-only (pragmas ignored)."""
    tmp = Path(tempfile.mkdtemp(prefix="wild_parse_"))
    try:
        names = []
        for name, text in split(path):
            (tmp / name).write_text(text)
            names.append(name)
        if lang_of(path) == "c":
            cmd = ["gcc", "-std=gnu11", "-fsyntax-only", *names]
        else:
            cmd = ["gfortran", "-std=gnu", "-ffree-line-length-none",
                   "-fsyntax-only", *names]
        r = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True,
                           timeout=120)
        if r.returncode == 0 or lang_of(path) == "c":
            return r.returncode == 0, (r.stderr or "")[-400:]
        # gfortran 13 lacks some Fortran 2008 forms (a type-spec in DO
        # CONCURRENT): the second base-language parser is flang without
        # OpenMP (directives are comments), when it is installed
        flang = FLANG if Path(FLANG).is_file() else None
        if flang is None:
            return False, (r.stderr or "")[-400:]
        for n in names:
            r2 = subprocess.run([flang, "-fsyntax-only", n], cwd=tmp,
                                capture_output=True, text=True, timeout=120)
            if r2.returncode:
                return False, "gfortran: " + (r.stderr or "")[-200:] + \
                    " flang: " + (r2.stderr or "")[-200:]
        return True, "gfortran rejects it, flang parses it: " + \
            (r.stderr or "")[-200:]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- the program reference of a case -------------------------------------------

def ref_of(path: Path):
    from offload.engine.confirm.model import ProgramRef
    from offload.engine.confirm.programs import join_files
    h = header(path)
    model = model_of(path)
    version = 34 if model == "acc" else \
        (60 if h.get("wild case") in VERSION_60 else 52)
    text = join_files(split(path))
    return ProgramRef("file", f"wild:{path.stem}", lang_of(path), version,
                      model, True, (), "construct", text,
                      expected=h.get("expected", ""))


def opt_of(path: Path, toolchain: str) -> str:
    h = header(path)
    opt = h.get("wild-opt") or "-O2"
    if toolchain.startswith("afar") and h.get("wild-opt-afar"):
        opt = f"{opt} {h['wild-opt-afar']}"
    return opt


# --- legality --------------------------------------------------------------------

def legality(out: Path) -> Path:
    from offload.engine.confirm import legality as LG
    recs = []
    for p in case_files():
        g = LG.gate(ref_of(p))
        d = g.to_dict()
        recs.append({"id": p.stem, **d})
        print(p.stem, d.get("status"), (d.get("reason") or "")[:120],
              flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r) + "\n" for r in recs))
    return out


# --- runs ------------------------------------------------------------------------

def classify(runs: list[dict], expected: str) -> tuple[str, str]:
    """One outcome class for a cell from its runs (the confirmer's Run
    dicts). A program that exits 0 printing nothing is unobservable when it
    has no check (the confirmer's judge calls it a run error). Runs that
    disagree: the worse outcome, reason 'flaky: ...'."""
    outs = []
    for r in runs:
        o, why = r["outcome"], r.get("reason", "")
        if o == "run_error" and why == "no output":
            o = "wrong_answer" if expected else "unobservable"
        if o == "accepted_ignored":
            o = "correct_on_device"
        outs.append((o, why))
    order = ("harness_error", "rejected", "ice", "timeout", "crash",
             "run_error", "wrong_answer", "fell_back_to_host",
             "unobservable", "correct_on_device")
    worst = min(outs, key=lambda x: order.index(x[0]))
    if len({o for o, _ in outs}) > 1:
        return worst[0], "flaky: " + " | ".join(f"{o}: {w}"[:120]
                                                for o, w in outs)
    return worst


def run_cell(path: Path, toolchain: str, mode: str) -> dict:
    from offload.engine.confirm import machines as M
    from offload.engine.confirm.execute import LocalRunner, RemoteRunner
    from offload.engine.toolchains import TOOLCHAINS
    tc = TOOLCHAINS[toolchain]
    machine = M.load()[tc.machine]
    ref = ref_of(path)
    opt = opt_of(path, toolchain)
    rec = {"id": path.stem, "toolchain": toolchain, "mode": mode,
           "opt": opt, "model": ref.model,
           "sha256": hashlib.sha256(ref.text.encode()).hexdigest()[:16]}
    if ref.model == "acc" and toolchain.startswith("afar"):
        rec.update(outcome="not_applicable", reason="AFAR has no OpenACC",
                   runs=[])
        return rec
    runner = RemoteRunner(machine) if isinstance(machine.access, dict) and \
        "ssh" in machine.access else LocalRunner()
    t0 = time.time()
    runs, prov = runner.run(ref, toolchain, mode, opt, "mandatory", REPEATS)
    rd = [dataclasses.asdict(r) for r in runs]
    oc, why = classify(rd, ref.expected)
    if oc == "harness_error" and why.startswith("unclassified_compile") and \
            (path.stem, toolchain) in HAND_CLASSIFIED:
        oc, why = HAND_CLASSIFIED[(path.stem, toolchain)]
    rec.update(outcome=oc, reason=why[:400], runs=rd,
               host=prov.host, modules=list(prov.modules),
               seconds=round(time.time() - t0, 1))
    if tc.kind == "nvhpc":  # The runtime the runs load
        rec["runtime_libs"] = dict(tc.env).get("LD_LIBRARY_PATH", "")
    return rec


def run(toolchains: list[str], modes: list[str] | None, jobs: int,
        only: list[str] | None = None) -> None:
    from offload.engine.confirm import machines as M
    from offload.engine.toolchains import TOOLCHAINS
    OUT.joinpath("runs").mkdir(parents=True, exist_ok=True)
    for tcn in toolchains:
        machine = M.load()[TOOLCHAINS[tcn].machine]
        for mode in modes or list(machine.modes):
            if mode not in machine.modes:
                continue
            out = OUT / "runs" / f"{tcn}.{mode}.jsonl"
            done = set()
            if out.exists():
                done = {json.loads(ln)["id"] for ln in out.read_text()
                        .splitlines() if ln.strip()}
            todo = [p for p in case_files() if p.stem not in done and
                    (not only or p.stem in only)]
            print(f"{tcn} {mode}: {len(todo)} to run", flush=True)
            with ThreadPoolExecutor(max_workers=jobs) as ex, \
                    out.open("a") as fh:
                for rec in ex.map(lambda p: run_cell(p, tcn, mode), todo):
                    fh.write(json.dumps(rec) + "\n")
                    fh.flush()
                    print(f"  {rec['id']}: {rec['outcome']} "
                          f"{rec.get('reason', '')[:100]}", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("parse")
    sp.add_parser("legality")
    r = sp.add_parser("run")
    r.add_argument("--toolchains", nargs="+", required=True)
    r.add_argument("--modes", nargs="+")
    r.add_argument("--jobs", type=int, default=4)
    r.add_argument("--only", nargs="+")
    a = ap.parse_args(argv)
    if a.cmd == "parse":
        bad = 0
        for p in case_files():
            ok, err = parse_one(p)
            if not ok:
                bad += 1
                print(f"{p.name}: {err}")
        print(f"{len(case_files()) - bad} of {len(case_files())} parse")
        return 1 if bad else 0
    if a.cmd == "legality":
        legality(OUT / "legality.jsonl")
    elif a.cmd == "run":
        run(a.toolchains, a.modes, a.jobs, a.only)
    return 0


if __name__ == "__main__":
    sys.exit(main())
