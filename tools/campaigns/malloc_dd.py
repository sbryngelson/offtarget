#!/usr/bin/env python3
"""Delta debugging of the AFAR device-malloc first-use failure (offload/engine/malloc_dd.py).

    python3 -I tools/campaigns/malloc_dd.py reduce [--launches 8] [--out DIR]   # greedy one-ingredient removal
    python3 -I tools/campaigns/malloc_dd.py matrix FILE.c [--tcs afar,cce21,cce21_4] [--modes 1,0] [--launches 8]

Each candidate is built once and launched as separate, fresh processes (the failure is mostly in the first launch of the
device allocator in a process), four at a time, each pinned to one of the node's four APUs
(ROCR_VISIBLE_DEVICES), at HSA_XNACK=1 under OMP_TARGET_OFFLOAD=mandatory. A launch fails when any trial
prints bad records. A removal is kept when at least half of the launches still fail. The result of every
candidate is a row in OUT/rows.jsonl (launches, failing launches, the trial of the first failure). Tuolumne
compute node only (one pbatch node, or a short foreground job).
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine import harness  # noqa: E402
from offload.engine import malloc_dd as D  # noqa: E402
from offload.engine.provenance import node  # noqa: E402
from offload.engine.toolchains import TOOLCHAINS  # noqa: E402

OUT = ROOT / "results" / "malloc-dd"
TRIAL = re.compile(r"trial\s+(\d+): bad (\d+) dup (\d+) missing (\d+)")


def _tc(name: str):
    return harness.dataclasses.replace(TOOLCHAINS[name], model="omp", lang="c")


def build(src: str, tc_name: str, tmp: Path):
    tc = _tc(tc_name)
    f = tmp / "p.c"
    exe = tmp / "p.out"
    f.write_text(src)
    b = harness._execute(harness.compile_script(tc, str(f), str(exe), "-O2", str(tmp)), tmp, 900, merge=True)
    return (exe if b.rc == 0 and exe.is_file() else None), b.stdout[-400:]


def launch(exe: Path, tc_name: str, xnack: int, trials: int, warm: int, gpu: int, tmp: Path) -> dict:
    tc = _tc(tc_name).for_mode(xnack)
    script = harness.run_script(tc, str(exe), xnack, True, str(tmp))
    lines = script.rstrip("\n").split("\n")
    lines[-1] = f"export ROCR_VISIBLE_DEVICES={gpu}\nexec {shlex.quote(str(exe))} {trials} {warm}"
    r = harness._execute("\n".join(lines) + "\n", tmp, 600)
    ts = [tuple(map(int, m.groups())) for m in TRIAL.finditer(r.stdout)]
    return {"rc": r.rc, "trials": len(ts), **D.launch_verdict(ts, trials, r.rc), "timed_out": r.timed_out}


def candidate(name: str, src: str, tc_name: str, xnack: int, launches: int, warm: int = 0,
              trials: int = 2) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="mdd_"))
    try:
        t0 = time.time()
        exe, log = build(src, tc_name, tmp)
        row = {"candidate": name, "toolchain": tc_name, "xnack": xnack, "warm": warm, "launches": launches,
               "trials_per_launch": trials, "node": node(), "src_sha": __import__("hashlib").sha256(
                   src.encode()).hexdigest()[:12]}
        if exe is None:
            return {**row, "result": "compile_failed", "log": log}
        with ThreadPoolExecutor(max_workers=4) as pool:
            res = list(pool.map(lambda i: launch(exe, tc_name, xnack, trials, warm, i % 4, tmp), range(launches)))
        row.update(result="ran", failing=sum(r["fail"] for r in res), per_launch=res,
                   wall_s=round(time.time() - t0, 1), compiler=harness.compiler_version(_tc(tc_name)))
        return row
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def log(out: Path, row: dict):
    with open(out / "rows.jsonl", "a") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
    print(f"{row['candidate']:48s} {row['toolchain']} x{row['xnack']} warm={row['warm']} "
          f"{row.get('failing', '-')}/{row['launches']} {row.get('result')}", flush=True)


def cmd_reduce2(a) -> int:
    """Stage 2: from the stage-1 minimum, which of the remaining ingredients are needed."""
    out = Path(a.out)
    (out / "src").mkdir(parents=True, exist_ok=True)
    need = (a.launches + 1) // 2
    cur = D.minimal()

    def test(name, f, warm=0):
        src = D.source(f)
        (out / "src" / f"{name}.c").write_text(src)
        row = candidate(name, src, "afar", 1, a.launches, warm)
        row["flags"] = asdict(f)
        log(out, row)
        return row
    test("s2-minimal", cur)
    needed, removed = [], []
    for k, v in D.STAGE2:
        r = test(f"s2-drop-{k}-{v}", replace(cur, **{k: v}))
        (removed if r.get("failing", 0) >= need else needed).append(f"{k}={v}")
        if r.get("failing", 0) >= need and k == "marker":
            cur = replace(cur, **{k: v})
    for dim in D.SIZES2:
        r = test(f"s2-size-{dim}", replace(cur, dim=dim))
        (removed if r.get("failing", 0) >= need else needed).append(f"dim={dim}")
    (out / "result2.json").write_text(json.dumps({"removed": removed, "needed": needed}))
    print("stage 2 removed:", removed, "needed:", needed)
    return 0


def cmd_stage3(a) -> int:
    """More fresh launches of the final reproducer: XNACK=0, a warm-up kernel of 1, 1000 and 1e6 mallocs, sizes
    between the smallest that failed and the largest that did not."""
    out = Path(a.out)
    fl = json.loads((out / "final" / "flags.json").read_text())["repro"]
    base = D.Flags(**fl)
    plan = [("s3-repro-x1", base, 1, 0), ("s3-repro-x0", base, 0, 0), ("s3-warm1", base, 1, 1),
            ("s3-warm1000", base, 1, 1000), ("s3-warm1e6", base, 1, 1000000),
            ("s3-size-271", replace(base, dim=271), 1, 0), ("s3-direct", replace(base, store="direct"), 1, 0),
            ("s3-stack", replace(base, store="stack"), 1, 0)]
    for name, f, x, warm in plan:
        src = D.source(f)
        row = candidate(name, src, "afar", x, a.launches, warm)
        row["flags"] = asdict(f)
        log(out, row)
    return 0


FINDING_FILES = {
    "afar-first-use-malloc": "data/findings/malloc/afar-device-malloc-in-kernel-corrupts-records.c",
    "afar-first-use-malloc-direct": "data/findings/malloc/controls/afar-first-use-malloc-direct.c",
    "afar-first-use-malloc-warm": "data/findings/malloc/controls/afar-first-use-malloc-warm.c",
    "afar-first-use-malloc-stack": "data/findings/malloc/controls/afar-first-use-malloc-stack.c",
    "afar-first-use-malloc-fence": "data/findings/malloc/controls/afar-first-use-malloc-fence.c",
    "afar-first-use-malloc-flush": "data/findings/malloc/controls/afar-first-use-malloc-flush.c",
}

# the student's Fortran program: unspecified by the kernel-body model (has_device_addr) and witnessed only by AFAR's
# front end, so its failure is an observation, not a finding (docs/tooling/contributing.md)
OBSERVATION_FILES = {
    "afar-first-use-malloc-student": "data/reports/kbody-observations/afar-device-array-constructor-corrupts-records.f90",
    "afar-first-use-malloc-student-elem": "data/reports/kbody-observations/controls/afar-first-use-malloc-student-elem.f90",
    "afar-first-use-malloc-student-nocons": "data/reports/kbody-observations/controls/afar-first-use-malloc-student-nocons.f90",
}


# --- the maintainer's experiments, through this harness ------------------------------------------------

JOBS = "data/reports/kbody-jobs/malloc"
FINAL = "results/malloc-dd/final"


LIBC_BUILD = str(ROOT / "results/student-repro/libc-build")
STUDENT = str(ROOT / "results/student-repro")


def experiments() -> list[dict]:
    """Every number the finding cites besides the ingredient table: id, source, build, arguments, environment."""
    out = []

    def add(group, id_, src, arch="gfx942", args="", env=None, xnack=1, kind="omp", libc="", launches=0):
        out.append({"group": group, "id": id_, "src": src, "arch": arch, "args": args, "env": env or {},
                    "xnack": xnack, "kind": kind, "libc": libc, "launches": launches})
    for n, f in ((12000000, 100), (16000000, 100), (16700000, 100), (16900000, 100), (20000000, 100),
                 (20000000, 25), (48000000, 25), (48000000, 10), (48000000, 100)):
        add("density", f"density-n{n // 1000000 if n % 1000000 == 0 else n}-share{f}", f"{JOBS}/thresh.c",
            args=f"{n} {f}")
    add("density", "density-n16777216-share100", f"{JOBS}/thresh.c", args="16777216 100")
    add("density", "density-n20123648-share100", f"{JOBS}/thresh.c", args="20123648 100")
    for touch, name in ((0, "calloc-pages"), (1, "host-memset-0"), (3, "host-memset-ff"), (2, "gpu-first-touch")):
        add("first-touch", f"first-touch-{name}", f"{JOBS}/thresh2.c", args=f"20000000 100 {touch}")
    for arch, name in (("gfx942", "default"), ("gfx942:xnack+", "xnack-plus"), ("gfx942:xnack-", "xnack-minus")):
        for x in (1, 0):
            add("target", f"target-{name}-xnack{x}", f"{JOBS}/thresh2.c", arch=arch, args="20000000 100 0", xnack=x)
    for x in (1, 0):
        add("hip", f"hip-gridstride-4096x256-xnack{x}", f"{JOBS}/hipthresh.hip.cpp", args="20000000", xnack=x,
            kind="hip")
        add("hip", f"hip-one-thread-per-element-xnack{x}", f"{JOBS}/hipthresh2.hip.cpp", args="20000000",
            xnack=x, kind="hip")
    for env, name in (({"LIBOMPTARGET_HEAP_SIZE": "33554432"}, "heap-32MiB"),
                      ({"LIBOMPTARGET_HEAP_SIZE": "4294967296"}, "heap-4GiB"),
                      ({"LIBOMPTARGET_STACK_SIZE": "65536"}, "stack-64KiB"), ({}, "none")):
        add("env", f"env-{name}", f"{FINAL}/repro.c", args="2 0", env=env)
    add("trials", "reduction-4-trials", f"{FINAL}/repro.c", args="4 0")
    for fl, name in ((0, "none"), (1, "flush-after-malloc"), (2, "flush-before-free"), (3, "flush-both")):
        add("mechanism", f"flush-{name}", f"{JOBS}/thresh5.c", args=f"20000000 100 {fl}")
    for fl, name in ((0, "none"), (1, "device-release"), (2, "system-release"), (3, "system-seq-cst")):
        add("mechanism", f"fence-{name}", f"{JOBS}/thresh6.c", args=f"20000000 100 {fl}")
    add("mechanism", "readback-in-kernel", f"{JOBS}/thresh3.c", args="20000000")
    add("mechanism", "double-allocation-table", f"{JOBS}/thresh4.c", args="20000000")
    add("mechanism", "omp-alloc-omp-free", f"{JOBS}/thresh_oalloc.c", args="20000000 100")
    add("mechanism", "reduction-device-release-fence-before-free", f"{FINAL}/fence.c", args="2 0")
    add("mechanism", "reduction-omp-flush-before-free", f"{FINAL}/flush.c", args="2 0")
    add("mechanism", "reduction-no-fence", f"{FINAL}/repro.c", args="2 0")
    for rnd in (1, 2):
        for v in ("ctl", "rel", "relacq"):
            add("libc", f"libc-{v}-r{rnd}", f"{JOBS}/thresh.c", args="20000000 100", libc=v)
        add("libc", f"libc-stock-r{rnd}", f"{JOBS}/thresh.c", args="20000000 100")
    for v in ("ctl", "rel", "relacq"):
        add("libc", f"libc-file-{v}", f"{FINAL}/repro.c", args="2 0", libc=v)
    # the mechanism, the patch forms, the sizes (the maintainer's sources, data/reports/kbody-jobs/malloc)
    for v in ("rmw", "rmwrel"):
        add("patchform", f"patchform-{v}-thresh", f"{JOBS}/thresh.c", args="20000000 100", libc=v, launches=10)
    for mask, n in (("0x10", 120000000), ("0x3", 60000000), ("0x7", 40000000), ("0x3f", 20000000)):
        add("xcc", f"xcc-mask{mask}-ctl", f"{JOBS}/xcc3.c", args=f"{n} {mask}", libc="ctl", launches=6)
    for mask, n in (("0x10", 120000000), ("0x3f", 20000000)):
        add("xcc", f"xcc-mask{mask}-rel", f"{JOBS}/xcc3.c", args=f"{n} {mask}", libc="rel", launches=4)
    for m, name in enumerate(("none", "compiler-barrier", "s_waitcnt-vmcnt0", "buffer_wbl2-sc1", "buffer_wbl2-sc1+s_waitcnt",
                              "workgroup-release-fence", "device-release-fence")):
        add("bare", f"bare-{name}", f"{JOBS}/thresh7.c", args=f"20000000 100 {m}", libc="ctl", launches=4)
    for v in ("ctl", "rel", "rmw", "rmwrel", "relacq"):
        add("sizes", f"sizes-4096-{v}", f"{JOBS}/sizes.c", args="4000000 4096 4", libc=v, launches=3)
    for v in ("ctl", "rel"):
        add("sizes", f"sizes-128-{v}", f"{JOBS}/sizes.c", args="20000000 128 4", libc=v, launches=3)
    out_dims = []
    for dim in (255, 271):
        out_dims.append(dim)
    return out


BAD = re.compile(r"\bbad (\d+)")
WRONG = re.compile(r"records wrong (\d+)")
DMG = re.compile(r"(?:allocating iterations \d+ |TOTAL size \d+ )damaged (\d+)")
ALLOCS = re.compile(r"allocating iterations (\d+)")
PRE = re.compile(r"block wrong after (?:own )?stores (\d+)")
DUP = re.compile(r"same block live in two threads (\d+)")


def run_exp(spec: dict, launches: int) -> dict:
    from offload.engine.toolchains import AFAR_BIN
    tmp = Path(tempfile.mkdtemp(prefix="mddx_"))
    try:
        src = ROOT / spec["src"]
        ext = ".cpp" if spec["kind"] == "hip" else ".c"
        f = tmp / ("p" + ext)
        f.write_text(src.read_text())
        exe = tmp / "p.out"
        tc = _tc("afar")
        if spec["kind"] == "hip":
            rocm = sorted(Path("/opt").glob("rocm-*"))[-1]
            cmd = (f"export LD_LIBRARY_PATH={AFAR_BIN}/../lib:{AFAR_BIN}/../lib/llvm/lib:$LD_LIBRARY_PATH\n"
                   f"{AFAR_BIN}/amdclang++ -x hip --offload-arch=gfx942 -O2 --rocm-path={rocm} {f} -o {exe} "
                   f"-L{rocm}/lib -lamdhip64 -Wl,-rpath,{rocm}/lib")
            runenv = f"export LD_LIBRARY_PATH={AFAR_BIN}/../lib:{AFAR_BIN}/../lib/llvm/lib:$LD_LIBRARY_PATH"
        else:
            extra = f"-Xoffload-linker {LIBC_BUILD}/build-{spec['libc']}/libc/lib/libc.a " if spec.get("libc") else ""
            cmd = f"{AFAR_BIN}/amdclang -fopenmp --offload-arch={spec['arch']} -O2 {extra}{f} -o {exe}"
            runenv = ""
        b = harness._execute("\n".join(harness._setup(tc, str(tmp))) + "\n" + cmd + "\n", tmp, 900, merge=True)
        row = D.exp_head(spec, f.read_text(), launches)
        row.update(node=node(), compiler=harness.compiler_version(tc))
        if b.rc != 0 or not exe.is_file():
            return {**row, "result": "compile_failed", "log": b.stdout[-400:]}

        def one(i):
            lines = harness._setup(tc, str(tmp))
            lines += [f"export HSA_XNACK={spec['xnack']}"]
            if spec["kind"] == "omp":
                lines += ["export OMP_TARGET_OFFLOAD=mandatory"]
            lines += [f"export {k}={shlex.quote(str(v))}" for k, v in spec["env"].items()]
            if runenv:
                lines += [runenv]
            lines += [f"export ROCR_VISIBLE_DEVICES={i % 4}", f"exec {shlex.quote(str(exe))} {spec['args']}"]
            r = harness._execute("\n".join(lines) + "\n", tmp, 600)
            bads = ([int(m) for m in BAD.findall(r.stdout)] or [int(m) for m in WRONG.findall(r.stdout)]
                    or [int(m) for m in DMG.findall(r.stdout)])
            ran = bool(bads) and r.rc == 0
            return {"rc": r.rc, "bad_by_trial": bads, "ran": ran, "allocations": sum(int(m) for m in ALLOCS.findall(r.stdout)),
                    "block_wrong_after_stores": [int(m) for m in PRE.findall(r.stdout)],
                    "same_block_live_in_two_threads": [int(m) for m in DUP.findall(r.stdout)],
                    "fail": (not ran) or any(bads), "tail": (r.stdout or "")[-110:].replace("\n", " | "),
                    "err": (r.stderr or "")[-120:] if hasattr(r, "stderr") else ""}
        with ThreadPoolExecutor(max_workers=4) as pool:
            res = list(pool.map(one, range(launches)))
        row.update(result="ran", failing=sum(r["fail"] for r in res),
                   refused=sum(1 for r in res if not r["ran"]), per_launch=res)
        return row
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def cmd_exp(a) -> int:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    done = set()
    p = out / "exp_rows.jsonl"
    if p.exists():
        done = {json.loads(l)["id"] for l in p.read_text().splitlines() if l}
    todo = [s for s in experiments() if s["id"] not in done and (not a.only or s["group"] in a.only.split(","))]
    for s in todo:
        r = run_exp(s, s["launches"] or ((10 if s["id"].startswith("libc-file") else 5) if s["group"] == "libc" else (a.launches if s["group"] != "mechanism" else max(a.launches, 10))))
        with open(p, "a") as fh:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
        print(f"{r['group']:12s} {r['id']:46s} x{r['xnack']} {r.get('failing', '-')}/{r['launches']} "
              f"(did not run: {r.get('refused', '-')}) {r.get('result')}", flush=True)
    return 0


def cmd_isa(a) -> int:
    """Read the free and claim paths of the AFAR OpenMP device image: from the maintainer's saved temporaries
    (results/student-repro/malloc/cmp/omp) and from a fresh -save-temps build of thresh.c (compute node). Keeps the lines of
    the flat atomics (the slab bitfield) and the hashes of every file read."""
    import hashlib
    from offload.engine.toolchains import AFAR_BIN
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rec: dict = {"source": f"{JOBS}/thresh.c", "source_sha256": hashlib.sha256((ROOT / JOBS / "thresh.c").read_bytes()).hexdigest()}

    def one(label: str, asm_path: Path, ll_path: Path | None) -> None:
        r = D.analyze_image(asm_path.read_text(), ll_path.read_text() if ll_path and ll_path.exists() else "")
        r.update({"asm_file": asm_path.name, "asm_sha256": hashlib.sha256(asm_path.read_bytes()).hexdigest()})
        if ll_path and ll_path.exists():
            r.update({"ir_file": ll_path.name, "ir_sha256": hashlib.sha256(ll_path.read_bytes()).hexdigest()})
        rec[label] = r
        print(label, "asm", r["asm_sha256"][:12], "flat atomics",
              [(f["op"], f["line"], f["cache_bits"], f["buffer_wbl2_before_line"], f["buffer_inv_after_line"]) for f in r["flat_atomics"]],
              "rpc global atomics", r["rpc_global_atomics"], "other", r["other_global_atomics"])

    known = ROOT / "results/student-repro/malloc/cmp/omp"
    asm = next(iter(known.glob("t.x.amdgpu*gfx942*.lto.s")), None)
    if asm:
        one("maintainer_build", asm, next(iter(known.glob("t.x.amdgpu*gfx942*.precodegen.ll")), None))
    if not a.no_build:
        tmp = Path(tempfile.mkdtemp(prefix="mddisa_"))
        try:
            (tmp / "t.c").write_text((ROOT / JOBS / "thresh.c").read_text())
            tc = _tc("afar")
            b = harness._execute("\n".join(harness._setup(tc, str(tmp))) + f"\n{AFAR_BIN}/amdclang -fopenmp --offload-arch=gfx942 "
                                 f"-O2 -save-temps t.c -o t.x\n", tmp, 900, merge=True)
            sfile = next(iter(tmp.glob("t.x.amdgpu*gfx942*.lto.s")), None)
            if b.rc != 0 or sfile is None:
                print("compile failed", b.stdout[-300:])
                return 2
            rec["compiler"] = harness.compiler_version(tc)
            one("fresh_build", sfile, next(iter(tmp.glob("t.x.amdgpu*gfx942*.precodegen.ll")), None))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    (out / "isa.json").write_text(json.dumps(rec, indent=1))
    return 0


FBAD = re.compile(r"trial\s+(\d+): bad records (\d+)\s+duplicated cells (\d+)\s+missing cells (\d+)")


def cmd_libc(a) -> int:
    """The upstream fix test: the allocator's libc rebuilt from the commit AFAR 24.3.0 was built from, unmodified (ctl), with a
    release fence before the bit clear (rel) and with that fence and an acquire after the claim (relacq). Writes
    libc_image.json (image hashes and the fence instructions of each variant) and libc_fortran_rows.jsonl (the student's program
    built by the maintainer against each variant, run again here); the C launches are the 'libc' group of exp_rows.jsonl."""
    import hashlib
    from offload.engine.toolchains import AFAR_BIN
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tc = _tc("afar")
    rec: dict = {"libc_source_commit": "ROCm/llvm-project 3ba19712e9fbf709f6c93d33394211ed4eeec8a7", "variants": {}}
    for v in ("stock", "ctl", "rel", "relacq"):
        tmp = Path(tempfile.mkdtemp(prefix="mddlibc_"))
        try:
            (tmp / "t.c").write_text((ROOT / JOBS / "thresh.c").read_text())
            extra = "" if v == "stock" else f"-Xoffload-linker {LIBC_BUILD}/build-{v}/libc/lib/libc.a "
            b = harness._execute("\n".join(harness._setup(tc, str(tmp))) + f"\n{AFAR_BIN}/amdclang -fopenmp --offload-arch=gfx942 "
                                 f"-O2 -save-temps {extra}t.c -o t.x\n", tmp, 900, merge=True)
            s = next(iter(tmp.glob("t.x.amdgpu*gfx942*.lto.s")), None)
            if b.rc != 0 or s is None:
                print(v, "compile failed", b.stdout[-300:])
                return 2
            r = D.analyze_image(s.read_text())
            claim, clear = r["flat_atomics"]
            norm = re.sub(r"anon\.[0-9a-f]{32}", "anon.MODULEHASH",
                          re.sub(r"__omp_offloading_([0-9a-f]+)_[0-9a-f]+_", r"__omp_offloading_\1_FILEHASH_", s.read_text().replace(str(tmp), "TMP")))
            rec.setdefault("_norm", {})[v] = norm.split("\n")
            rec["variants"][v] = {
                "asm_normalized_md5": hashlib.md5(norm.encode()).hexdigest()[:12],
                "asm_lines": r["asm_lines"], "asm_md5": hashlib.md5(s.read_bytes()).hexdigest()[:12],
                "asm_sha256": hashlib.sha256(s.read_bytes()).hexdigest(),
                "archive_sha256": (hashlib.sha256(Path(f"{LIBC_BUILD}/build-{v}/libc/lib/libc.a").read_bytes()).hexdigest()
                                   if v != "stock" else None),
                "flat_atomic_or_line": claim["line"], "flat_atomic_and_line": clear["line"],
                "buffer_wbl2_before_clear_line": clear["buffer_wbl2_before_line"], "buffer_inv_after_claim_line": claim["buffer_inv_after_line"],
                "clear_excerpt": clear["excerpt"], "claim_excerpt": claim["excerpt"], **{k: r[k] for k in r if k.startswith("count_")}}
            print(v, rec["variants"][v]["asm_md5"], r["asm_lines"], "wbl2 before clear", clear["buffer_wbl2_before_line"],
                  "inv after claim", claim["buffer_inv_after_line"], flush=True)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    import difflib
    norm = rec.pop("_norm")
    for v in ("ctl", "rel", "relacq"):
        d = [x for x in difflib.unified_diff(norm["stock"], norm[v], lineterm="", n=0) if x[:1] in "+-" and x[:3] not in ("+++", "---")]
        rec["variants"][v]["diff_lines_vs_stock_image"] = len(d)
        rec["variants"][v]["diff_vs_stock_image"] = d[:40]
    (out / "libc_image.json").write_text(json.dumps(rec, indent=1))
    if a.image_only:
        return 0

    exes = {"stock": f"{STUDENT}/orig.x", "ctl": f"{STUDENT}/libcab/orig-ctl.x", "rel": f"{STUDENT}/libcab/orig-rel.x",
            "relacq": f"{STUDENT}/libcab/orig-relacq.x"}
    rows = []
    for rep in range(a.reps):
        def one(item):
            k, (v, exe) = item
            lines = harness._setup(tc, str(out)) + ["export HSA_XNACK=1", "export OMP_TARGET_OFFLOAD=mandatory",
                                                      f"export ROCR_VISIBLE_DEVICES={(k + rep) % 4}", f"exec {shlex.quote(exe)} 10 50 6"]
            t0 = time.time()
            r = harness._execute("\n".join(lines) + "\n", out, 900)
            tr = [(int(x), int(y), int(z), int(w)) for x, y, z, w in FBAD.findall(r.stdout)]
            return {"variant": v, "rep": rep, "exe": exe, "exe_sha256": hashlib.sha256(Path(exe).read_bytes()).hexdigest(),
                    "args": "10 50 6", "rc": r.rc, "trials": len(tr), "trials_with_damage": sum(1 for x in tr if x[1] or x[2] or x[3]),
                    "bad_records_by_trial": [x[1] for x in tr], "wall_s": round(time.time() - t0, 1), "node": node(),
                    "compiler": harness.compiler_version(tc)}
        with ThreadPoolExecutor(max_workers=4) as pool:
            res = list(pool.map(one, enumerate(exes.items())))
        rows += res
        for r in res:
            print("fortran", r["variant"], r["rep"], f"trials {r['trials']} damaged {r['trials_with_damage']}", flush=True)
    with open(out / "libc_fortran_rows.jsonl", "w") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    return 0


def cmd_exp2(a) -> int:
    """Recheck of the 255^3 / 271^3 result with the generator's decomposition, and the first-trial question."""
    out = Path(a.out)
    p = out / "exp_rows.jsonl"
    for dim in (255, 271):
        f = D.minimal()
        f = replace(f, marker="none", dim=dim)
        name = f"recheck-reduction-dim{dim}"
        row = candidate(name, D.source(f), "afar", 1, a.launches, 0, trials=4)
        row["flags"] = asdict(f)
        row["group"] = "recheck"
        row["id"] = name
        with open(p, "a") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
        print(name, row.get("failing"), "/", a.launches, flush=True)
    return 0


def cmd_annotate(a) -> int:
    """Copy the rows with the path of the finding file (or control) each case became, so that
    tools/repo/check_findings.py can match a row to a file whose name is not the case's id (the rows' results
    are unchanged). -> OUT/finding_rows.jsonl; the rows of the observation (the student's Fortran program)
    -> OUT/observation_rows.jsonl"""
    out = Path(a.out)
    rows = []
    for src in (out / "harness_rows.jsonl", out / "wingtip" / "harness_rows.jsonl", out / "gate_reruns.jsonl"):
        if not src.exists():
            continue
        rows += [json.loads(line) for line in src.read_text().splitlines() if line]
    f, o = D.split_rows(rows, FINDING_FILES, OBSERVATION_FILES)
    (out / "finding_rows.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in f))
    (out / "observation_rows.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in o))
    print(len(f), "rows ->", out / "finding_rows.jsonl", "and", len(o), "->", out / "observation_rows.jsonl")
    return 0


def cmd_final(a) -> int:
    """Write the reduced reproducer and its one-change controls from the stage-2 result."""
    out = Path(a.out)
    res = json.loads((out / "result2.json").read_text())
    cur = D.minimal()
    if "marker=none" in res["removed"]:
        cur = replace(cur, marker="none")
    for item in res["removed"]:
        k, v = item.split("=")
        if k == "alloc":
            pass                                   # an unneeded mapping is not chosen: the mapped form stays the reproducer
    fin = out / "final"
    fin.mkdir(parents=True, exist_ok=True)
    cases = {"repro": cur, "direct": replace(cur, store="direct"), "warm": replace(cur, warm=1000),
             "stack": replace(cur, store="stack"), "fence": replace(cur, fence="device"),
             "flush": replace(cur, fence="flush")}
    for n, f in cases.items():
        (fin / f"{n}.c").write_text(D.source(f))
    (fin / "flags.json").write_text(json.dumps({n: asdict(f) for n, f in cases.items()}))
    print("final:", asdict(cur))
    return 0


def cmd_reduce(a) -> int:
    out = Path(a.out)
    (out / "src").mkdir(parents=True, exist_ok=True)

    def test(name, f, warm=0):
        src = D.source(f)
        (out / "src" / f"{name}.c").write_text(src)
        row = candidate(name, src, "afar", 1, a.launches, warm)
        row["flags"] = asdict(f)
        log(out, row)
        return row

    need = (a.launches + 1) // 2
    cur = D.STUDENT
    base = test("baseline", cur)
    if base.get("failing", 0) < need:
        print("the baseline does not fail often enough; stop")
        return 2
    kept, dropped = [], []
    for k, v, f in D.removals(cur):
        r = test(f"drop-{k}", replace(cur, **{k: v}))
        if r.get("failing", 0) >= need:
            cur = replace(cur, **{k: v})
            kept.append(f"{k}={v}")
        else:
            dropped.append(k)
    for dim in D.SIZES:
        if dim >= cur.dim and cur.dim != 439:
            continue
        r = test(f"size-{dim}", replace(cur, dim=dim))
        if r.get("failing", 0) >= need:
            cur = replace(cur, dim=dim)
            kept.append(f"dim={dim}")
        else:
            dropped.append(f"dim={dim}")
            break
    (out / "src" / "minimal.c").write_text(D.source(cur))
    test("minimal", cur)
    test("minimal-warm1", cur, warm=1)
    test("minimal-warm1000", cur, warm=1000)
    test("minimal-direct", replace(cur, store="direct"))
    test("minimal-stack", replace(cur, store="stack"))
    print("removed (not needed):", kept)
    print("needed (removal stopped the failure):", dropped)
    (out / "result.json").write_text(json.dumps({"minimal": asdict(cur), "removed": kept, "needed": dropped}))
    return 0


def cmd_matrix(a) -> int:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    src = Path(a.file).read_text()
    for tc in a.tcs.split(","):
        for x in [int(m) for m in a.modes.split(",")]:
            for warm in (0, 1):
                row = candidate(f"{Path(a.file).stem}", src, tc, x, a.launches, warm)
                log(out, row)
    return 0


def _cases(a):
    """name=path pairs -> {name: harness Program}"""
    out = {}
    for c in a.cases:
        name, path = c.split("=", 1)
        out[name] = harness.program_from_file(path, id=name, primary_atom="malloc.first_use")
    return out


def cmd_rows(a) -> int:
    """Harness rows (repeats = fresh processes) of the cases on the toolchains -> OUT/harness_rows.jsonl."""
    import dataclasses
    from offload.engine import run_matrix
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    progs = _cases(a)
    for n, p in progs.items():
        for t in a.tcs.split(","):
            for x in [int(v) for v in a.modes.split(",")]:
                tc = run_matrix.for_version(TOOLCHAINS[t], 52, "c" if p.lang == "c" else "f90")
                r = dataclasses.asdict(harness.run_program(p, tc, x, "-O2", timeout_s=600, repeats=a.repeats))
                r.update(campaign="malloc-dd", kind="kbody", case=n, mode={0: "copy", 1: "unified"}.get(x, "unified"))
                r["stdout"] = (r.get("stdout") or "")[-1500:]
                r["stderr"] = (r.get("stderr") or "")[-1500:]
                with open(out / "harness_rows.jsonl", "a") as fh:
                    fh.write(json.dumps(r, sort_keys=True) + "\n")
                print(r["program_id"], r["toolchain"], r["xnack"], r["outcome"], (r["reason"] or "")[:120], flush=True)
    return 0


def cmd_gate(a) -> int:
    """The reproduction gate's reruns (a, b, d here; c on another node) of the failing rows of OUT/harness_rows.jsonl."""
    from offload.engine import gate as GT
    from offload.engine import gate_run as GR
    from offload.engine import run_matrix
    GT.register_kind("kbody", "kbody_", "program")
    out = Path(a.out)
    progs = _cases(a)
    rows = [json.loads(l) for l in (out / "harness_rows.jsonl").read_text().splitlines() if l]
    gp = out / "gate_reruns.jsonl"
    done = set()
    if gp.exists():
        done = {(r["cell"], r["env"]) for r in (json.loads(l) for l in gp.read_text().splitlines() if l)}
    for r in rows:
        if r["outcome"] in GT.PASSING or r["outcome"] == "harness_error":
            continue
        it = {**{k: r.get(k) for k in ("outcome", "reason", "flaky", "build_dir", "node", "toolchain_build",
                                       "toolchain", "xnack", "mode")},
              "campaign": "malloc-dd", "kind": "kbody", "machine": "tuolumne", "ident": r["program_id"],
              "opt": "-O2", "timeout_s": 600, "stdout": r.get("stdout") or "", "compile_log": "",
              "cell": f"kbody|{r['program_id']}|{r['toolchain']}|{r['xnack']}", "family": "malloc"}
        for e in GT.environments(it, a.root or None):
            if e["env"] not in a.envs.split(",") or (it["cell"], e["env"]) in done:
                continue
            if a.node and (e["node"] == "same") != (a.node == "same"):
                continue
            tc = run_matrix.for_version(TOOLCHAINS[r["toolchain"]], 52, "c" if progs[r["program_id"]].lang == "c" else "f90")
            rr = GR.rerun_program(progs[r["program_id"]], tc, int(r["xnack"]), e, "-O2", timeout_s=600)
            with open(gp, "a") as fh:
                fh.write(json.dumps({**rr, "cell": it["cell"]}, sort_keys=True) + "\n")
            print(it["cell"], e["env"], rr["outcome"], flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("reduce")
    r.add_argument("--launches", type=int, default=8)
    r.add_argument("--out", default=str(OUT))
    s3 = sub.add_parser("stage3")
    s3.add_argument("--launches", type=int, default=8)
    s3.add_argument("--out", default=str(OUT))
    bd = sub.add_parser("annotate")
    bd.add_argument("--out", default=str(OUT))
    ex = sub.add_parser("exp")
    ex.add_argument("--launches", type=int, default=8)
    ex.add_argument("--only")
    ex.add_argument("--out", default=str(OUT))
    lc = sub.add_parser("libc")
    lc.add_argument("--out", default=str(OUT))
    lc.add_argument("--reps", type=int, default=5)
    lc.add_argument("--image-only", action="store_true", help="only the image hashes and fence instructions (compile, no GPU)")
    ia = sub.add_parser("isa")
    ia.add_argument("--out", default=str(OUT))
    ia.add_argument("--no-build", action="store_true", help="read only the maintainer's saved temporaries")
    ex2 = sub.add_parser("exp2")
    ex2.add_argument("--launches", type=int, default=8)
    ex2.add_argument("--out", default=str(OUT))
    fn = sub.add_parser("final")
    fn.add_argument("--out", default=str(OUT))
    r2 = sub.add_parser("reduce2")
    r2.add_argument("--launches", type=int, default=8)
    r2.add_argument("--out", default=str(OUT))
    m = sub.add_parser("matrix")
    m.add_argument("file")
    m.add_argument("--tcs", default="afar,cce21,cce21_4")
    m.add_argument("--modes", default="1,0")
    m.add_argument("--launches", type=int, default=8)
    m.add_argument("--out", default=str(OUT))
    for n in ("rows", "gate"):
        q = sub.add_parser(n)
        q.add_argument("cases", nargs="+", help="NAME=FILE.c")
        q.add_argument("--tcs", default="afar")
        q.add_argument("--modes", default="1")
        q.add_argument("--repeats", type=int, default=10)
        q.add_argument("--envs", default="a,b,d")
        q.add_argument("--node", choices=("same", "other"))
        q.add_argument("--root")
        q.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    return {"reduce": cmd_reduce, "reduce2": cmd_reduce2, "final": cmd_final, "annotate": cmd_annotate, "exp": cmd_exp, "exp2": cmd_exp2, "isa": cmd_isa, "libc": cmd_libc, "stage3": cmd_stage3, "matrix": cmd_matrix, "rows": cmd_rows, "gate": cmd_gate}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
