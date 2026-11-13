#!/usr/bin/env python3
"""Compile and run the vendor-packet reproducers and controls.

Reads cases.json (made by build.py from cases.yaml)
and the sources in src/, and appends one JSON line per (case, variant,
toolchain, mode, environment) to --out.

    python3 -I run_checks.py run --machine tuolumne --env a \\
        --toolchains afar,cce19,cce20,cce21 --modes 1,0 --workers 24 \\
        --out results/tuolumne.a.jsonl [--cases id,id] [--variants repro,control]
    python3 -I run_checks.py versions --machine tuolumne --toolchains ...

Environments are the reproduction gate's (offload/engine/gate.py): a and b differ
in the build directory name, c is a on another node or GPU, d is a second
compile and run. AFAR_ROOT names where AFAR is installed. Compile has a 32 GiB ulimit and a timeout (compile_s,
default 300 s); run has a timeout (run_s, default 120 s)."""
import argparse
import concurrent.futures as cf
import datetime
import fcntl
import hashlib
import json
import os
import random
import shlex
import shutil
import signal
import string
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

AFAR_942 = "/opt/afar/therock-afar-24.3.0-multiarch-10.1.0-592954c"
AFAR_90A = "/opt/afar/therock-afar-24.3.0-multiarch-10.1.0-592954c"
NV = {"nvhpc": "/opt/nvidia/hpc_sdk/Linux_x86_64/25.11/compilers",
      "nvhpc269": "/opt/nvidia/hpc_sdk/Linux_x86_64/26.9/compilers"}
CCE = {"cce19": ("19.0.0", "6.4.3"), "cce20": ("20.0.2", "6.4.3"),
       "cce21": ("21.0.3", "7.2.0"), "cce21_4": ("21.0.4", "7.2.0")}
# GCC 16.2 with offloading (offload/engine/toolchains.py gcc_g90, gcc_sm80): its
# install (GCC_ROOT overrides it), the ROCm whose HSA runtime libgomp opens on AMD
# (GCC_ROCM overrides it), and the offload target: amdgcn on every AMD machine (one
# install holds the device libraries of several arches), nvptx on wingtip
GCC_DEFAULT = "/opt/gcc-16.2"
GCC_ROCM = "/opt/rocm-7.2.1"
GCC_TARGET = {"tuolumne": "amdgcn-amdhsa", "tioga": "amdgcn-amdhsa", "mi300x": "amdgcn-amdhsa",
              "mi350x": "amdgcn-amdhsa", "wingtip": "nvptx-none"}
ARCH = {"tuolumne": "gfx942", "tioga": "gfx90a", "mi300x": "gfx942", "mi350x": "gfx950", "wingtip": "sm_80"}
# machines whose GPUs run separate memory only (no XNACK modes)
COPY_ONLY = ("tioga", "mi300x", "mi350x")
NV_MODE = {0: "separate", 2: "managed"}
GIB_KIB = 1024 * 1024


def family(tc):
    if tc.startswith("gcc"):
        return "gcc"
    return "afar" if tc == "afar" else "nvhpc" if tc.startswith("nvhpc") else "cce"


def modes_of(fam, machine):
    """The memory modes (row keys) a family runs on a machine: NVHPC
    separate and managed; copy only on the copy-only machines and for GCC on
    NVIDIA; AMD otherwise both (GCC on the MI300A too: measured, every smoke
    program runs on the device at HSA_XNACK 0 and 1)."""
    if fam == "nvhpc":
        return (0, 2)
    if machine in COPY_ONLY or (fam == "gcc" and machine == "wingtip"):
        return (0,)
    return (0, 1)


def recipe(tc, machine, lang, model, extra, opt, mode, src, exe):
    """(prelude lines, compile command, run env) of one build."""
    arch = ARCH[machine]
    fam = family(tc)
    env = {}
    pre = []
    if fam == "afar":
        if model == "acc":
            return None
        root = os.environ.get("AFAR_ROOT") or (AFAR_90A if machine == "tioga" else AFAR_942)
        if machine != "tuolumne":
            env["LD_LIBRARY_PATH"] = f"{root}/lib:{root}/lib/llvm/lib"
        if lang == "c":
            cmd = f"{root}/bin/amdclang -fopenmp --offload-arch={arch}"
        else:
            cmd = (f"{root}/bin/amdflang -fopenmp --offload-arch={arch} "
                   "-L/usr/lib/gcc/x86_64-redhat-linux/8")
    elif fam == "cce":
        if lang == "c" and model == "acc":
            return None
        v, r = CCE[tc]
        pre = [". /etc/profile >/dev/null 2>&1",
               f"module load cce/{v} craype-accel-amd-{arch} rocm/{r} >/dev/null 2>&1",
               "module unload cray-mpich >/dev/null 2>&1"]
        if lang == "c":
            cmd = ("craycc -fopenmp -fopenmp-targets=amdgcn-amd-amdhsa "
                   f"-Xopenmp-target=amdgcn-amd-amdhsa -march={arch}")
        else:
            cmd = "ftn -h acc" if model == "acc" else "ftn -fopenmp"
    elif fam == "gcc":
        root = os.environ.get("GCC_ROOT") or GCC_DEFAULT
        tgt = GCC_TARGET[machine]
        rocm = os.environ.get("GCC_ROCM") or GCC_ROCM
        env["LD_LIBRARY_PATH"] = f"{root}/lib64" + (f":{rocm}/lib" if tgt == "amdgcn-amdhsa" else "")
        if machine == "wingtip":   # nvptx-as verifies with CUDA's ptxas
            pre = ["export PATH=/usr/local/cuda/bin:$PATH"]
        comp = "gcc" if lang == "c" else "gfortran"
        par = "-fopenacc" if model == "acc" else "-fopenmp"
        cmd = (f"{root}/bin/{comp} {par} -foffload={tgt} "
               f"-foffload-options={tgt}=-march={arch}")
        if tgt == "nvptx-none":   # GCC's manual: nvptx offload needs libatomic
            cmd += f" -foffload-options={tgt}=-latomic"
    else:
        root = NV[tc]
        env["LD_LIBRARY_PATH"] = f"{root}/lib"
        comp = "nvc" if lang == "c" else "nvfortran"
        par = "-acc=gpu" if model == "acc" else "-mp=gpu"
        cmd = f"{root}/bin/{comp} {par} -gpu=cc80 -gpu=mem:{NV_MODE[mode]}"
    if extra:
        cmd += " " + extra
    cmd += f" {opt} {src} -o {exe}"
    return pre, cmd, env


def base_env(renv):
    """The caller's environment without GCC's libgomp settings (GOMP_*,
    GCN_*: GOMP_DEBUG, GCN_STACK_SIZE would change a GCC run; the harness
    drops them too), then the recipe's own variables."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GOMP_", "GCN_"))}
    env.update(renv)
    return env


def run_env(case, variant, tc, machine, g, mode, env):
    """The environment of one run: the memory mode (HSA_XNACK on AMD), mandatory offload, the
    case's own `run_env`, and the GPU the run was given (ROCR_VISIBLE_DEVICES; CUDA_VISIBLE_DEVICES
    on wingtip), unless the case's `devices` says `all` for this toolchain (or "*"): then every
    device of the node stays visible, as a campaign harness run (a GCC fault on the MI250X shows
    only then)."""
    out = dict(env)
    if family(tc) != "nvhpc":
        out["HSA_XNACK"] = str(mode)
    out["OMP_TARGET_OFFLOAD"] = "mandatory"
    out.update(ov(case, variant, "run_env") or {})
    var = "CUDA_VISIBLE_DEVICES" if machine == "wingtip" else "ROCR_VISIBLE_DEVICES"
    dev = case.get("devices") or {}
    if (dev.get(tc) or dev.get("*")) == "all":
        out.pop(var, None)
    else:
        out[var] = str(g)
    return out


def ov(case, variant, key, default=None):
    """A case key, overridden for the control by control_<key>."""
    if variant == "control" and f"control_{key}" in case:
        return case[f"control_{key}"]
    return case.get(key, default)


def extra_for(case, tc, variant="repro"):
    fl = ov(case, variant, "flags") or {}
    parts = [fl.get("all", ""), fl.get(family(tc), ""), fl.get(tc, "")]
    return " ".join(p for p in parts if p)


def dirname_for(env, rnd):
    if env == "b":
        return "GATE" + "".join(rnd.choice(string.ascii_uppercase) for _ in range(14))
    return "harness_" + "".join(rnd.choice("0123456789abcdef") for _ in range(8))


def _exec(script, cwd, limit, env):
    """Run a bash script in its own process group; kill the group at
    limit + 30 s (the script's own timeouts come first)."""
    p = subprocess.Popen(["bash", "-c", script], cwd=cwd, env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         start_new_session=True)
    try:
        out, _ = p.communicate(timeout=limit + 30)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        out, _ = p.communicate()
        return 124, out.decode("utf-8", "replace"), True
    return p.returncode, out.decode("utf-8", "replace"), False


def tail(s, n=6000):
    return s if len(s) <= n else s[:1500] + "\n[...]\n" + s[-(n - 1500):]


class Gpus:
    """Round-robin GPU choice with at most `per` concurrent runs per GPU
    (Tuolumne/Tioga), or one per GPU under the shared flock (wingtip)."""

    def __init__(self, ids, per, lock):
        self.ids = ids
        self.sem = {g: threading.Semaphore(per) for g in ids}
        self.lock = lock
        self.n = 0
        self.mu = threading.Lock()

    def acquire(self):
        with self.mu:
            g = self.ids[self.n % len(self.ids)]
            self.n += 1
        self.sem[g].acquire()
        fh = None
        if self.lock:
            fh = open(f"/tmp/compliant-run-{os.getuid()}-gpu{g}.lock", "a")
            fcntl.flock(fh, fcntl.LOCK_EX)
        return g, fh

    def release(self, g, fh):
        if fh is not None:
            fcntl.flock(fh, fcntl.LOCK_UN)
            fh.close()
        self.sem[g].release()


def one(job, a, gpus, csem, rnd_seed):
    case, variant, tc = job["case"], job["variant"], job["tc"]
    rnd = random.Random(rnd_seed)
    lang, model = case["lang"], case.get("model", "omp")
    srcpath = HERE / case[variant]
    fam = family(tc)
    machine = a.machine
    modes = [m for m in a.modes if m in modes_of(fam, a.machine)]
    if a.machine in COPY_ONLY:
        modes = [0]
    if not modes:
        return []
    base = Path(a.tmp) / dirname_for(a.env, rnd)
    sub = case.get("build_dir")
    recs = []
    # NVHPC: the memory mode is a compile flag (one build per mode)
    builds = [(m, [m]) for m in modes] if fam == "nvhpc" else [(modes[0], modes)]
    for bmode, rmodes in builds:
        if sub:   # an absolute build path of the case (path-dependent defects)
            d = Path(sub[variant].get(a.env, sub[variant]["a"]) + f"_{tc}_{bmode}"
                     if sub[variant].get("suffix") else sub[variant].get(a.env, sub[variant]["a"]))
        else:
            d = base / f"{case['id']}_{variant}_{tc}_{bmode}"
        d.mkdir(parents=True, exist_ok=True)
        name = case.get("filename") or (case["id"] + (".c" if lang == "c" else ".f90"))
        shutil.copy(srcpath, d / name)
        opt = ov(case, variant, "opt", "-O2")
        r = recipe(tc, machine, lang, model, extra_for(case, tc, variant), opt, bmode, name, "repro")
        rec0 = {"case": case["id"], "variant": variant, "tc": tc, "machine": machine,
                "env": a.env, "host": os.uname().nodename, "build_dir": str(d),
                "sha": hashlib.sha256(srcpath.read_bytes()).hexdigest()[:12],
                "date": datetime.datetime.now().isoformat(timespec="seconds")}
        if r is None:
            for m in rmodes:
                recs.append(dict(rec0, mode=m, obs="NOT_APPLICABLE"))
            continue
        pre, cmd, renv = r
        climit = int(case.get("compile_s", 300))
        script = "\n".join(["ulimit -c 0"] + pre + [
            "ulimit -c 0", f"export TMPDIR={shlex.quote(str(d))}",
            f"ulimit -v {32 * GIB_KIB}",
            ("nice -n 10 " if machine == "wingtip" else "") +
            f"timeout --kill-after=10 {climit} {cmd}"])
        env = base_env(renv)
        with csem:
            t0 = time.time()
            rc, log, killed = _exec(script, d, climit + 15, env)
            ct = round(time.time() - t0, 1)
        rec0.update(cmd=cmd, compile_rc=rc, compile_s=ct, compile_log=tail(log, 4000))
        if rc != 0 or not (d / "repro").exists():
            stage = "COMPILE_TIMEOUT" if (rc in (124, 137) or killed) else "COMPILE_FAIL"
            for m in rmodes:
                recs.append(dict(rec0, mode=m, obs=f"{stage} rc={rc}\n{log}"))
            shutil.rmtree(d, ignore_errors=True)
            continue
        rlimit = int(case.get("run_s", 120))
        for m in rmodes:
            g, fh = gpus.acquire()
            try:
                renv2 = run_env(case, variant, tc, machine, g, m, env)
                # the compile's module environment (CCE's runtime libraries)
                rs = "\n".join(["ulimit -c 0"] + pre + [
                    "ulimit -c 0",
                    ("exec nice -n 10 " if machine == "wingtip" else "exec ")
                    + f"timeout --kill-after=10 {rlimit} ./repro"])
                t0 = time.time()
                rrc, out, killed = _exec(rs, d, rlimit + 15, renv2)
                rt = round(time.time() - t0, 1)
            finally:
                gpus.release(g, fh)
            if killed or rrc in (124, 137) and rt >= rlimit:
                stage = "RUN_TIMEOUT"
            elif rrc == 0:
                stage = "RUN_OK"
            else:
                stage = "RUN_FAIL"
            sig = (f" signal={-rrc}" if rrc < 0 else
                   f" signal={rrc - 128}" if 128 < rrc < 160 else "")
            recs.append(dict(rec0, mode=m, gpu=g, run_s=rt, run_rc=rrc,
                             obs=f"{stage} rc={rrc}{sig}\n{tail(out)}"))
        shutil.rmtree(d, ignore_errors=True)
    try:
        base.rmdir()
    except OSError:
        pass
    return recs


def load_cases(sel, cases_file="cases.json"):
    cases = json.loads((HERE / cases_file).read_text())
    if sel:
        want = set(sel.split(","))
        cases = [c for c in cases if c["id"] in want]
    return cases


def select_jobs(cases, tcs, variants, machine, vendor=None, all_arches=False):
    """The (case, variant, toolchain) jobs of a run. A vendor case runs on
    the machines its vendor named (Tioga: the gfx90a cases; `vendor_machine`);
    `all_arches` runs every case (a compiler under test that the cases were
    not written for: the site's GCC column)."""
    jobs = []
    for c in cases:
        if not all_arches and machine == "tioga" and "gfx90a" not in c.get("arch", []):
            continue
        if vendor and vendor not in (c["vendor"] if isinstance(c["vendor"], list) else [c["vendor"]]):
            continue
        only = c.get("only")   # restrict a case to some toolchains
        for v in variants:
            if not c.get(v):
                continue
            for tc in tcs:
                if only and tc not in only and family(tc) not in only:
                    continue
                if not all_arches and c.get("vendor_machine") and machine not in c["vendor_machine"]:
                    continue
                jobs.append({"case": c, "variant": v, "tc": tc})
    return jobs


def cmd_run(a):
    a.modes = [int(m) for m in a.modes.split(",")]
    cases = load_cases(a.cases, a.cases_file)
    tcs = a.toolchains.split(",")
    variants = a.variants.split(",")
    jobs = select_jobs(cases, tcs, variants, a.machine, a.vendor, a.all_arches)
    if a.resume and Path(a.out).is_file():
        done_keys = set()
        for ln in Path(a.out).read_text().splitlines():
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if r.get("env") == a.env and not r.get("obs", "").startswith("HARNESS_ERROR"):
                done_keys.add((r["case"], r["variant"], r["tc"]))
        jobs = [j for j in jobs if (j["case"]["id"], j["variant"], j["tc"]) not in done_keys]
    if a.shard:
        k, n = (int(x) for x in a.shard.split("/"))
        jobs = [j for i, j in enumerate(jobs) if i % n == k]
    random.Random(7).shuffle(jobs)   # mix slow CCE builds with fast ones
    gpu_ids = [int(g) for g in a.gpus.split(",")]
    gpus = Gpus(gpu_ids, 1 if a.machine == "wingtip" else a.per_gpu,
                a.machine == "wingtip")
    csem = threading.Semaphore(a.compiles)
    Path(a.tmp).mkdir(parents=True, exist_ok=True)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    print(f"{len(jobs)} jobs on {os.uname().nodename} env {a.env}", flush=True)
    seed = int(hashlib.sha256(f"{a.env}{os.getpid()}{time.time()}".encode()).hexdigest()[:8], 16)
    done = 0
    t_end = time.time() + a.limit_s
    with open(a.out, "a") as fh, cf.ThreadPoolExecutor(a.workers) as ex:
        futs = {}
        for i, j in enumerate(jobs):
            futs[ex.submit(lambda j=j, s=seed + i: one(j, a, gpus, csem, s)
                           if time.time() < t_end else [])] = j
        for f in cf.as_completed(futs):
            try:
                recs = f.result()
            except Exception as e:  # noqa: BLE001 - record and go on
                j = futs[f]
                recs = [{"case": j["case"]["id"], "variant": j["variant"], "tc": j["tc"],
                         "env": a.env, "machine": a.machine, "obs": f"HARNESS_ERROR {e!r}"}]
            for r in recs:
                fh.write(json.dumps(r) + "\n")
            fh.flush()
            done += 1
            if done % 50 == 0:
                print(f"{done}/{len(jobs)} {datetime.datetime.now():%H:%M:%S}", flush=True)
    print("done", flush=True)


def cmd_versions(a):
    out = {"host": os.uname().nodename, "machine": a.machine,
           "date": datetime.datetime.now().isoformat(timespec="seconds"), "tc": {}}
    for tc in a.toolchains.split(","):
        r = recipe(tc, a.machine, "f90", "omp", "", "", 0, "", "")
        pre, cmd, env = r
        comp = cmd.split()[0]
        e = dict(os.environ)
        e.update(env)
        script = "\n".join(pre + [f"{comp} --version 2>&1 | head -4",
                                  "module list 2>&1 | tr -s ' ' | head -20" if pre else "true"])
        rc, log, _ = _exec(script, "/tmp", 120, e)
        out["tc"][tc] = log.strip()
        rc_ = recipe(tc, a.machine, "c", "omp", "", "", 0, "", "")
        if rc_:
            pre, cmd, env = rc_
            e = dict(os.environ)
            e.update(env)
            rc, log, _ = _exec("\n".join(pre + [f"{cmd.split()[0]} --version 2>&1 | head -4"]), "/tmp", 120, e)
            out["tc"][tc + ":c"] = log.strip()
    for f in ("/etc/os-release",):
        try:
            out["os"] = [l for l in open(f) if l.startswith("PRETTY_NAME")][0].strip()
        except OSError:
            pass
    out["kernel"] = os.uname().release
    for exe in ("/opt/rocm/bin/rocm-smi", "nvidia-smi"):
        rc, log, _ = _exec(f"{exe} --showproductname 2>/dev/null | head -12 || true"
                           if "rocm" in exe else
                           f"{exe} --query-gpu=name,driver_version --format=csv 2>/dev/null | head -3 || true",
                           "/tmp", 60, dict(os.environ))
        out[Path(exe).name] = log.strip()
    print(json.dumps(out))
    if a.out:
        with open(a.out, "a") as fh:
            fh.write(json.dumps(out) + "\n")


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("run")
    r.add_argument("--machine", required=True, choices=sorted(ARCH))
    r.add_argument("--env", required=True, choices=["a", "b", "c", "d"])
    r.add_argument("--toolchains", required=True)
    r.add_argument("--modes", default="1,0")
    r.add_argument("--cases")
    r.add_argument("--all-arches", action="store_true",
                   help="run every case, not only those of the machine's vendor arch")
    r.add_argument("--cases-file", default="cases.json",
                   help="the cases to run (the public site's derived cases: cases-site.json)")
    r.add_argument("--variants", default="repro,control")
    r.add_argument("--workers", type=int, default=16)
    r.add_argument("--compiles", type=int, default=16)
    r.add_argument("--per-gpu", type=int, default=4)
    r.add_argument("--gpus", default="0,1,2,3")
    r.add_argument("--shard")
    r.add_argument("--resume", action="store_true")
    r.add_argument("--vendor")
    r.add_argument("--limit-s", type=int, default=10 ** 9)
    r.add_argument("--tmp", default=f"/tmp/{os.environ.get('USER', 'u')}-t44")
    r.add_argument("--out", required=True)
    v = sp.add_parser("versions")
    v.add_argument("--machine", required=True, choices=sorted(ARCH))
    v.add_argument("--toolchains", required=True)
    v.add_argument("--out")
    a = ap.parse_args()
    {"run": cmd_run, "versions": cmd_versions}[a.cmd](a)


if __name__ == "__main__":
    main()
