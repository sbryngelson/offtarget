"""OpenACC fuzz programs (generator fuzz-acc1): random Fortran OpenACC 3.4
programs with the fuzz generator's model, expressions and checksum frame.

A program is built by offload.engine.fuzz._Gen with every kernel drawn by
``k_acc`` instead of the OpenMP kernel flavors: a loop nest of one or two levels
under a compute construct (parallel loop, kernels loop, serial loop, or parallel
or kernels with nested loop directives), with gang/worker/vector, collapse,
private, reduction (clause or atomic), data clauses or present inside a data
region, and launch sizes. Statements appear only inside the innermost loop, so
no statement runs gang-redundantly. The program frame the OpenMP generator
writes (the data region or enter/exit data around the kernels, the host update,
deferred tasks, device functions) is then rewritten line by line to its OpenACC
counterpart (``acc_frame``); the deferred tasks become operations on one async
queue (async(1)) and each taskwait an ``acc wait(1)``, so their order is the
program order. No base-language groups. The model value is the sequential one,
which every legal schedule prints.

check() of an OpenACC program (``check_acc``): the repository's OpenACC rules
(version 34), gfortran -std=f2008 without OpenACC against the declaration-only
openacc stub, AMD flang's front end with -fopenacc, and the sequential run of
the program built without OpenACC against a sequential openacc module, which
must print the model's checksum."""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from offload.engine import fuzz as F
from offload.engine.fuzz import Kern, wrap_directive

GEN = "fuzz-acc1"
ACC_VERSION = 34
ASYNC = "async(1)"
ACC_SWARM = ("num_gangs", "vector_length", "num_workers", "firstprivate")

# the sequential openacc module of the elided run: the host is the device
OPENACC_SEQ = """\
module openacc
  implicit none
  integer, parameter :: acc_device_kind = 4
  integer(acc_device_kind), parameter :: acc_device_none = 0, acc_device_default = 1, &
    acc_device_host = 2, acc_device_not_host = 3
contains
  logical function acc_on_device(dev_type)
    integer(acc_device_kind), value :: dev_type
    acc_on_device = dev_type == acc_device_host .or. dev_type == acc_device_default
  end function acc_on_device
end module openacc
"""


def acc_frame(source: str) -> str:
    """The OpenACC form of the frame directives the OpenMP generator wrote around
    the kernels; raises ValueError on an OpenMP line it does not cover."""
    text = re.sub(r" &\n\s*!\$omp& ", " ", source)        # join continued directives
    out = []
    for line in text.split("\n"):
        m = re.match(r"(\s*)!\$omp (.*)$", line)
        if not m:
            out.append(line.replace("use omp_lib, only: omp_is_initial_device",
                                    "use openacc, only: acc_on_device, acc_device_host"))
            continue
        ind, d = m.groups()
        out.append(ind + _frame_directive(d.strip()))
    src = "\n".join(out)
    if "!$omp" in src or re.search(r"\bomp_\w+", src):
        raise ValueError("an OpenMP line is left: " + next(
            ln for ln in src.split("\n") if "!$omp" in ln or re.search(r"\bomp_\w+", ln)))
    return src


def _maps(d: str) -> list[tuple[str, str]]:
    return [(k, v.strip()) for k, v in re.findall(r"map\((\w+):\s*([^)]*)\)", d)]


def _deferred(d: str) -> list[str]:
    return [ASYNC] if re.search(r"\bnowait\b", d) else []


def _frame_directive(d: str) -> str:
    acc = {"to": "copyin", "tofrom": "copy", "from": "copyout", "alloc": "create",
           "release": "delete", "delete": "delete"}
    if d == "declare target":
        return "!$acc routine seq"
    if re.fullmatch(r"atomic( update)?", d):
        return "!$acc atomic update"
    if d in ("end atomic",):
        return "!$acc end atomic"
    if d.startswith("taskwait"):
        return "!$acc wait(1)"
    if d == "end target data":
        return "!$acc end data"
    if d.startswith("target data"):
        return "!$acc data " + " ".join(f"{acc[k]}({v})" for k, v in _maps(d))
    if d.startswith("target enter data"):
        return " ".join(["!$acc enter data"] + [f"{acc[k]}({v})" for k, v in _maps(d)] + _deferred(d))
    if d.startswith("target exit data"):
        return " ".join(["!$acc exit data"] + [f"{acc[k]}({v})" for k, v in _maps(d)] + _deferred(d))
    m = re.match(r"target update (to|from)\(([^)]*(?:\([^)]*\))?[^)]*)\)", d)
    if m:
        where = "device" if m.group(1) == "to" else "self"
        return " ".join([f"!$acc update {where}({m.group(2)})"] + _deferred(d))
    raise ValueError(f"no OpenACC form of !$omp {d}")


class AccGen(F._Gen):
    """A fuzz-acc1 program: fuzz-6's decisions with OpenACC kernels."""

    def __init__(self, seed: int):
        super().__init__(seed, "fuzz-6", ())
        self.gen_version = GEN
        # swarm testing of the OpenACC-only features (as fuzz.SWARM for the shared ones)
        self.acc_swarm = {f: self.coin(0.5) for f in ACC_SWARM}
        self.features.update(f"swarm:acc:{f}" for f, on in self.acc_swarm.items() if on)

    def asw(self, name: str, p: float) -> bool:
        return self.acc_swarm[name] and self.coin(p)

    # every flavor is an OpenACC loop kernel
    def k_loop(self, ind):
        return self.k_acc(ind)

    k_guard = k_phase = k_inred = k_loop

    def with_nowait(self, kern: Kern) -> list[str]:
        """The kernel's compute construct on the program's async queue."""
        self.feat("tasking:async")
        last = 0
        while kern.lines[last].rstrip().endswith("&"):
            last += 1
        return kern.lines[:last] + [kern.lines[last] + f" {ASYNC}"] + kern.lines[last + 1:]

    @staticmethod
    def flag_stmt(flag: str) -> str:
        return f"{flag} = merge(1, 0, acc_on_device(acc_device_host))"

    def k_acc(self, ind: str) -> Kern:
        r = self.r
        nlev = 2 if self.sw("two_d", 0.5) else 1
        shape = r.choice(("parallel loop", "parallel loop", "kernels loop", "serial loop",
                          "parallel+loop", "kernels+loop"))
        levels = self.new_levels(nlev)
        out = self.new_array(f"o{self.k}", nlev, "output", "integer")
        full = all(lvl.form != "step2" for lvl in levels)
        ivars = {lvl.var: lvl.extent for lvl in levels}
        readable = self.readable(out.name)
        reds = []
        for idx in range(r.choice((1, 1, 2)) if self.on("reduction") else 0):
            method = "atomic" if self.sw("atomic", 0.4) else "clause"
            reds.append(self.new_red(idx, method))
            self.feat(f"red:{method}", f"red:{method}:{reds[-1].op}")
        temps: list[str] = []
        body, step = self.point(ivars, out, tuple(F.Var(v) for v in ivars), reds, [], temps,
                                nlev == 1 and self.sw("inner_loop", 0.5), readable)
        self.run_points(levels, step)
        text = "\n".join(body)
        reads = {n for n in readable if re.search(rf"\b{n}\(", text)}
        writes = {out.name: "full" if full else "partial"}
        self.full_out[out.name] = full
        scal_reads = {p for p in self.params() if re.search(rf"\b{p}\b", text)}
        flag = self.new_flag() if self.coin(0.5) else None
        if flag:
            cond = " .and. ".join(f"{lvl.var} == {lvl.first()}" for lvl in levels)
            body = [f"if ({cond}) {self.flag_stmt(flag)}"] + body
        # the data clauses of the compute construct
        data = []
        if self.in_data:
            if self.coin(0.4):
                data.append(r.choice(("default(present)", f"present({', '.join(sorted(reads | {out.name}))})")))
        else:
            if reads:
                data.append(f"copyin({', '.join(sorted(reads))})")
            data.append(f"{'copyout' if full and self.coin(0.5) else 'copy'}({out.name})")
        scal = sorted({red.var for red in reds if red.method == "atomic"} | ({flag} if flag else set()))
        if scal:
            data.append(f"copy({', '.join(scal)})")    # a parallel construct's scalars are firstprivate
        if scal_reads and self.asw("firstprivate", 0.4) and not shape.startswith("kernels"):
            data.append(f"firstprivate({', '.join(sorted(scal_reads))})")
            self.feat("acc:firstprivate")
        launch = []
        if not shape.startswith("serial"):
            if self.asw("num_gangs", 0.4):
                launch.append(f"num_gangs({r.choice((1, 2, 4, 7, 64))})")
            if self.asw("vector_length", 0.3):
                launch.append(f"vector_length({r.choice((1, 32, 64, 128))})")
            if self.asw("num_workers", 0.2):
                launch.append(f"num_workers({r.choice((1, 2, 4))})")
        red_cl = [f"reduction({red.op}: {red.var})" for red in reds if red.method == "clause"]
        priv = [f"private({', '.join(temps)})"] if temps else []
        lines: list[str] = []
        par = {"parallel": ("gang", "gang vector", "gang worker vector", ""),
               "kernels": ("gang", "gang vector", "independent", ""),
               "serial": ("", "seq")}
        if "+" not in shape:            # one combined construct over the whole nest
            kind = shape.split()[0]
            cl = [x for x in (r.choice(par[kind]),) if x] + (["collapse(2)"] if nlev == 2 else []) + \
                priv + red_cl + data + launch
            lines += wrap_directive(ind, shape, cl)
            lines[:] = [ln.replace("!$omp", "!$acc") for ln in lines]
            cur = ind
            for lvl in levels:
                lines.append(cur + lvl.header())
                cur += "  "
            lines += [cur + s for s in body]
            for _ in levels:
                cur = cur[:-2]
                lines.append(cur + "end do")
            if self.coin(0.5):
                lines.append(f"{ind}!$acc end {shape}")
        else:                           # the construct, then a loop directive per level
            kind = shape.split("+")[0]
            outer_red = red_cl if kind == "parallel" else []
            head = wrap_directive(ind, kind, data + launch + outer_red)
            lines += [ln.replace("!$omp", "!$acc") for ln in head]
            cur = ind + "  "
            inner = {"parallel": ("vector", "worker", "seq", "worker vector"),
                     "kernels": ("vector", "independent", "seq")}[kind]
            for li, lvl in enumerate(levels):
                last = li == len(levels) - 1
                par_cl = ("gang" if li == 0 and nlev == 2 else
                          r.choice(("gang vector", "gang", "independent" if kind == "kernels" else "gang")))
                if li == 1:
                    par_cl = r.choice(inner)
                cl = [par_cl] + (priv if last else []) + (red_cl if par_cl != "seq" else [])
                lines.append(f"{cur}!$acc loop {' '.join(cl)}")
                lines.append(cur + lvl.header())
                cur += "  "
            lines += [cur + s for s in body]
            for _ in levels:
                cur = cur[:-2]
                lines.append(cur + "end do")
            lines.append(f"{ind}!$acc end {kind}")
        self.kdesc.append(f"acc: {shape} ({nlev}D)")
        self.feat("kernel:acc", f"acc:{shape}")
        self.check_items.append(out.name)
        scal_writes = {red.var for red in reds} | ({flag} if flag else set())
        return Kern(lines, reads | scal_reads, set(writes) | scal_writes)

    def build(self) -> F.FuzzProgram:
        p = super().build()
        src = acc_frame(p.source).replace("! generator: fuzz-6\n", f"! generator: {GEN}\n", 1)
        src = src.replace("(OpenMP 5.2, free-form Fortran)", "(OpenACC 3.4, free-form Fortran)", 1)
        return F.FuzzProgram(p.seed, src, p.expected, p.features, p.kernels, p.flags, GEN, ())


def generate(seed: int) -> F.FuzzProgram:
    return AccGen(seed).build()


# -- the checks --------------------------------------------------------------------

def check_rules_acc(source: str) -> str | None:
    from offload.engine.grammar import GrammarError
    from offload.engine.rules import ProgramError, parse_program, violations
    try:
        found = violations(parse_program(source, ACC_VERSION), ACC_VERSION)
    except (GrammarError, ProgramError) as e:
        return f"{type(e).__name__}: {str(e).splitlines()[0]}"
    return ", ".join(found) or None


def _gfortran(args: list[str], d: str, timeout: int = 300):
    return subprocess.run([F.GFORTRAN] + args, cwd=d, capture_output=True, text=True, timeout=timeout)


def check_gfortran_acc(source: str) -> str | None:
    """gfortran -std=f2008 -fsyntax-only without OpenACC, against the declaration-only openacc stub."""
    from offload.engine.acc_gen import OPENACC_STUB
    with tempfile.TemporaryDirectory(prefix="fuzz_acc_") as d:
        (Path(d) / "openacc.f90").write_text(OPENACC_STUB)
        (Path(d) / "p.f90").write_text(source)
        b = _gfortran(["-std=f2008", "-fsyntax-only", "openacc.f90", "p.f90"], d)
    return None if b.returncode == 0 else (b.stderr or b.stdout).strip()[:500]


def check_flang_acc(source: str) -> str | None:
    """AMD flang's front end with OpenACC (another compiler family than CCE and GCC)."""
    from offload.engine.toolchains import AFAR_BIN
    with tempfile.TemporaryDirectory(prefix="fuzz_acc_") as d:
        (Path(d) / "p.f90").write_text(source)
        b = subprocess.run([f"{AFAR_BIN}/amdflang", "-fopenacc", "-fsyntax-only", "p.f90"], cwd=d,
                           capture_output=True, text=True, timeout=300)
    return None if b.returncode == 0 else (b.stderr or b.stdout).strip()[:500]


def elided_checksum_acc(source: str, init: str = "-finit-integer=-77777") -> int | str:
    """The checksum of the program built without OpenACC (-O0, run-time checks) against the
    sequential openacc module, or why there is none."""
    with tempfile.TemporaryDirectory(prefix="fuzz_acc_") as d:
        (Path(d) / "openacc.f90").write_text(OPENACC_SEQ)
        (Path(d) / "p.f90").write_text(source)
        b = _gfortran(["-std=f2008", "-O0", "-fcheck=all", init, "openacc.f90", "p.f90", "-o", "p"], d)
        if b.returncode:
            return "elided build: " + (b.stderr or b.stdout).strip()[:400]
        run = subprocess.run(["./p"], cwd=d, capture_output=True, text=True, timeout=300)
    m = re.search(r"RESULT checksum=\s*(-?\d+)", run.stdout)
    if run.returncode or not m:
        return f"elided run: rc={run.returncode} {(run.stderr or run.stdout).strip()[:300]}"
    return int(m.group(1))


def check_defined_acc(source: str, expected: int | None) -> str | None:
    """Two elided runs with different initial fills of the integers (an undefined value
    shows as a difference) must both print the model's checksum."""
    for init in ("-finit-integer=-77777", "-finit-integer=31313"):
        v = elided_checksum_acc(source, init)
        if isinstance(v, str):
            return v
        if expected is not None and v != expected:
            return f"elided run ({init}) printed checksum={v}, the model {expected}"
    return None


def check_acc(source: str, expected: int | None = None) -> F.CheckResult:
    stages = [("rules", check_rules_acc), ("gfortran", check_gfortran_acc), ("flang", check_flang_acc),
              ("defined", lambda s: check_defined_acc(s, expected))]
    try:
        for stage, fn in stages:
            why = fn(source)
            if why:
                return F.CheckResult(stage, why)
    except (subprocess.SubprocessError, OSError) as e:
        return F.CheckResult("error", str(e)[:500])
    return F.CheckResult("ok")
