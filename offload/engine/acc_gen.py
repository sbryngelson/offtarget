"""OpenACC 3.4 programs for the slice: frame, recipes, illegal variants.

``offload.engine.gen`` builds, checks and names the programs (``acc34-...``).
This module gives the source per atom (``recipe``) and, per rule stem, the
base atom and source transform of the illegal variant (``ILLEGAL``).

``AccSrc.render`` writes free-form Fortran (``program gen_prog``) with
``a(i) = i``, ``b(i) = 0`` and a host reference ``ref(i)``. The region of
interest computes ``b`` on the device and sets ``host_flag`` from
``acc_on_device(acc_device_host)``. The program prints
``RESULT ran_on_host=<0|1> check=<pass|fail>``, uses integers and logicals
only, and has n = 64. Checks that need a separate device copy are guarded by
``shared_mem`` and carry ``evidence="copy_mode_only"``. ``OPENACC_STUB`` is a
declaration-only ``openacc`` module for the gfortran -std=f2008 base check.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from offload.engine import gen_templates as T

FLAG = "host_flag = merge(1, 0, acc_on_device(acc_device_host))"
LOOP_FLAG = "if (i == 1) " + FLAG
BODY = ("b(i) = 2*a(i) + 1",)
STD = "copyin(a) copyout(b) copy(host_flag)"
MAX_LINE = 96

NO_VARIANT_WHY = ("Rule: no single-change illegal variant of a "
                  "generated program is written; the rule's legal and "
                  "illegal programs are the unit cases in tests/engine/test_acc.py "
                  "(ACC_CASES)")


def acc(*parts: str) -> str:
    return " ".join(["!$acc", *[p for p in parts if p]])


def loop(directive: str | None, body=BODY, flag=True, var="i",
         upto="n") -> list[str]:
    """A DO loop over 1..n (with its directive, if any): the device report
    in iteration 1, then the body."""
    out = [directive] if directive else []
    out.append(f"do {var} = 1, {upto}")
    if flag:
        out.append(LOOP_FLAG)
    out += list(body)
    out.append("end do")
    return out


# --- the frame ---------------------------------------------------------------

_BLOCK = re.compile(r"!\$acc (parallel|kernels|serial|data|host_data)\b"
                    r"(?! loop)", re.I)


def _indent(lines: list[str], n: int) -> list[str]:
    out, depth = [], 0
    for line in lines:
        low = line.strip().lower()
        if re.match(r"end\s*(do|if|function|subroutine|type)\b", low) \
                or (low.startswith("!$acc end") and not low.endswith("loop")):
            depth -= 1
        out.append(" " * (n + 2 * max(depth, 0)) + line.strip()
                   if line else "")
        if re.match(r"do(\s|$)", low) or re.match(r"if\s*\(.*\)\s*then$",
                                                  low) \
                or low.startswith("contains") or re.match(
                    r"(integer|logical)\s+function\b|subroutine\b", low) \
                or re.match(r"type\s*::", low) or _BLOCK.match(low):
            depth += 1
        if low.startswith("!$acc atomic capture"):
            depth += 1
    return out


def _wrap(line: str) -> str:
    """Split a long directive at clause boundaries (``&`` and ``!$acc&``)."""
    if len(line) <= MAX_LINE or not line.lstrip().lower().startswith("!$acc"):
        return line
    ind = line[:len(line) - len(line.lstrip())]
    parts, depth, cur = [], 0, ""
    for ch in line.strip():
        depth += ch == "("
        depth -= ch == ")"
        if ch == " " and depth == 0:
            parts.append(cur)
            cur = ""
            continue
        cur += ch
    parts.append(cur)
    lines, cur = [], ""
    for p in parts:
        if cur and len(ind) + len(cur) + len(p) + 3 > MAX_LINE:
            lines.append(cur)
            cur = "!$acc& " + p
        else:
            cur = f"{cur} {p}" if cur else p
    lines.append(cur)
    return " &\n".join(ind + x for x in lines)


@dataclass
class AccSrc(T.Src):
    """One OpenACC program before rendering (fields as ``T.Src``, plus
    ``procs``: external procedures placed before the main program)."""
    procs: list = field(default_factory=list)

    def shared_setup(self):
        """``pres`` (checked at the end) and ``shared_mem`` (host and
        device share storage: a serial region's write of a copyin array is
        seen by the host), once per program; evidence copy_mode_only."""
        if "logical :: pres, shared_mem" not in self.decls:
            self.decls += ["logical :: pres, shared_mem", "integer :: zc(1)"]
            self.init += ["pres = .true.", "zc = 0", acc("serial copyin(zc)"),
                          "zc(1) = 1", acc("end serial"),
                          "shared_mem = zc(1) == 1"]
            self.checks.append("pres")
            self.evidence = "copy_mode_only"

    def copy_check(self, cond: str) -> list[str]:
        """Assert `cond` (into ``pres``) in copy mode only."""
        self.shared_setup()
        return [f"if (.not. shared_mem) pres = pres .and. ({cond})"]

    def omp_names(self) -> list[str]:
        """The openacc names the program uses (the ONLY list)."""
        names = {"acc_on_device", "acc_device_host"}
        for line in self.module + self.spec + self.decls + self.init \
                + self.region + self.post:
            low = line.lower()
            if low.lstrip().startswith("!$acc") or \
                    not low.lstrip().startswith("!"):
                names.update(re.findall(r"\b(acc_\w+)", low))
        return sorted(names)

    def render(self, header: list[str]) -> str:
        out = [f"! {h}" for h in header]
        for proc in self.procs:
            out += _indent(proc, 0) + [""]
        if self.module:
            out += ["module gen_mod", "  use openacc", "  implicit none"]
            out += _indent(self.module, 2)
            out += ["end module gen_mod", ""]
        out.append("program gen_prog")
        out.append("  use openacc, only: " + ", ".join(self.omp_names()))
        if self.module:
            out.append("  use gen_mod")
        out += _indent(self.uses, 2)
        out.append("  implicit none")
        body = list(self.spec) + [
            "integer, parameter :: n = 64",
            "integer, allocatable, target :: a(:), b(:)",
            "integer :: ref(n)",
            "integer :: i, host_flag",
            "logical :: ok"] + list(self.decls) + [
            "allocate(a(n), b(n))",
            "do i = 1, n",
            "  a(i) = i",
            "  b(i) = 0",
            f"  ref(i) = {self.ref}",
            "end do",
            "host_flag = 1"] + list(self.init) + list(self.region) + list(
            self.post)
        ok = " .and. ".join(["all(b == ref)"] + list(self.checks))
        body += [f"ok = {ok}",
                 "print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, "
                 "' check=', merge('pass', 'fail', ok)",
                 "deallocate(a, b)"]
        out += _indent(body, 2)
        out.append("end program gen_prog")
        return "\n".join(_wrap(line) for line in out) + "\n"


def src(**kw) -> AccSrc:
    return AccSrc(**kw)


def std_kernel(directive="parallel loop", clauses=STD) -> list[str]:
    """The standard kernel: a combined construct computing b."""
    return loop(acc(directive, clauses))


# --- directive recipes -------------------------------------------------------

def parallel_prog() -> AccSrc:
    """parallel with one gang (a sequential loop in gang-redundant mode):
    a host execution of the region (the construct removed) reports
    ran_on_host=1. (No loop construct: CCE rejects an orphaned loop
    construct in the main program, which the mutant would leave.)"""
    return src(region=[acc("parallel", STD + " num_gangs(1)")]
               + loop(None) + [acc("end parallel")])


def kernels_prog() -> AccSrc:
    return src(region=[acc("kernels", STD)] + loop(None)
               + [acc("end kernels")])


def serial_prog() -> AccSrc:
    return src(region=[acc("serial", STD), FLAG] + loop(None, flag=False)
               + [acc("end serial")])


def loop_redundancy_prog(directive="loop", what="the loop construct") -> AccSrc:
    """Gang-redundant mode (3.4 §1.2, §2.5.1): in a parallel region with
    several gangs, a loop without gang partitioning is executed by every
    gang. Each iteration adds its value to b(i) atomically, so b == ref only
    if each iteration runs once."""
    s = src(header_notes=[
        f"oracle: without {what} every gang of the parallel region "
        "executes every iteration (gang-redundant mode), and the atomic "
        "update adds the value once per gang"])
    s.region = [acc("parallel", "num_gangs(4) copyin(a) copy(b) "
                    "copy(host_flag)"),
                acc(directive), "do i = 1, n", LOOP_FLAG, acc("atomic update"),
                "b(i) = b(i) + 2*a(i) + 1", "end do", acc("end parallel")]
    return s


def scribble_prog(enter: str, exit_: str) -> AccSrc:
    """enter data / exit data (3.4 §2.6.6): the arrays stay on the device
    between the directives, so the kernel (implicit present_or_copy) does
    not copy b back; a host-only write of b(1) after it is overwritten by
    the exit data copyout (copy mode). Without either directive the kernel
    copies b back and the host write remains."""
    s = src()
    s.shared_setup()
    s.region = [acc("enter data", enter)] + std_kernel(
        "parallel loop", "copy(host_flag)") + [
        "if (.not. shared_mem) b(1) = -9", acc("exit data", exit_)]
    return s


def data_prog(clauses="copyin(a) copyout(b)") -> AccSrc:
    """data (3.4 §2.6.5): b stays on the device for the region; a host-only
    write of b(1) inside the region is overwritten by copyout at its end
    (copy mode). Without the construct the kernel copies b back first."""
    s = src()
    s.shared_setup()
    s.region = [acc("data", clauses)] + std_kernel(
        "parallel loop", "copy(host_flag)") + [
        "if (.not. shared_mem) b(1) = -9", acc("end data")]
    return s


def update_prog(clause="self(b)") -> AccSrc:
    """update (3.4 §2.14.4): b is created on the device by a data region
    and computed there; the update copies it to the host (copy mode)."""
    s = src()
    s.shared_setup()
    s.region = [acc("data", "copyin(a) create(b)")] + std_kernel(
        "parallel loop", "copy(host_flag)") + [acc("update", clause),
                                                acc("end data")]
    return s


def update_device_prog() -> AccSrc:
    """update device (3.4 §2.14.4): a changes on the host after it entered
    the device; the update sends the new values before the kernel."""
    s = src(ref="2*(i + 1) + 1")
    s.shared_setup()
    s.region = [acc("data", "copyin(a) copyout(b)"),
                "do i = 1, n", "a(i) = i + 1", "end do",
                acc("update", "device(a)")] + std_kernel(
        "parallel loop", "copy(host_flag)") + [acc("end data")]
    return s


def host_data_prog() -> AccSrc:
    """host_data use_device (3.4 §2.8): the subroutine receives device
    addresses and declares them deviceptr; with host addresses (the
    construct removed) the device would access host memory, which copy
    mode does not allow."""
    s = src()
    s.shared_setup()
    s.module = ["contains", "subroutine dev_twice(x, y, m, hf)",
                "integer, intent(in) :: m",
                "integer :: x(m), y(m), hf",
                "integer :: k",
                acc("parallel loop", "deviceptr(x, y) copy(hf)"),
                "do k = 1, m",
                "if (k == 1) hf = merge(1, 0, acc_on_device(acc_device_host))",
                "y(k) = 2*x(k) + 1", "end do",
                "end subroutine dev_twice"]
    s.region = [acc("data", "copyin(a) copyout(b)"),
                acc("host_data", "use_device(a, b)"),
                "call dev_twice(a, b, n, host_flag)",
                acc("end host_data"), acc("end data")]
    return s


def declare_prog(clause="create(t)") -> AccSrc:
    """declare create (3.4 §2.13): t has a device copy for the program's
    implicit data region, so the kernel (implicit present_or_copy) does not
    copy it back: the host t is unchanged (copy mode). Without the
    directive the kernel copies t back."""
    s = src(decls=["integer :: t(n)"], init=["t = -7"])
    s.spec = [acc("declare", clause)]
    s.region = std_kernel("parallel loop", "copyin(a) copyout(b) "
                          "copy(host_flag)")[:-1] + ["t(i) = i", "end do"]
    s.post = s.copy_check("all(t == -7)")
    return s


def atomic_prog(clause="") -> AccSrc:
    """atomic update (3.4 §2.12): n*100 concurrent increments of one
    counter; without the construct updates are lost."""
    s = src(decls=["integer :: cnt, k"], init=["cnt = 0"],
            checks=["(cnt == 100*n)"])
    s.header_notes.append("oracle: without atomicity concurrent "
                          "increments of cnt are lost")
    s.region = [acc("parallel loop", STD + " copy(cnt)"), "do i = 1, n",
                LOOP_FLAG, *BODY, "do k = 1, 100", acc("atomic", clause),
                "cnt = cnt + 1", "end do", "end do"]
    return s


def capture_prog() -> AccSrc:
    """atomic capture (3.4 §2.12): each iteration takes a ticket from a
    shared counter; the tickets are 0..n-1, each once."""
    s = src(decls=["integer :: cnt, tk(n)"], init=["cnt = 0", "tk = -1"],
            checks=["(cnt == n)", "(sum(tk) == n*(n - 1)/2)",
                    "all(tk >= 0)"])
    s.header_notes.append("oracle: without the atomic capture two "
                          "iterations can take the same ticket")
    s.region = [acc("parallel loop", STD + " copy(cnt) copyout(tk)"),
                "do i = 1, n", LOOP_FLAG, *BODY, acc("atomic capture"),
                "tk(i) = cnt", "cnt = cnt + 1", acc("end atomic"), "end do"]
    return s


def atomic_rw_prog(kind: str) -> AccSrc:
    """atomic read / write in a race-free program."""
    s = src(decls=["integer :: x, v(n)"], init=["x = 5", "v = 0"],
            checks=["all(v == 5)" if kind == "read" else "(x == 7)"])
    stmt = "v(i) = x" if kind == "read" else "x = 7"
    s.region = [acc("parallel loop", STD + " copy(x) copyout(v)"),
                "do i = 1, n", LOOP_FLAG, *BODY, acc("atomic", kind), stmt,
                "end do"]
    return s.unverified(
        "needs_other_infrastructure",
        f"atomic {kind} differs from a plain {kind} only when another "
        "access races with it, which no deterministic single run exercises",
        checked=True)


def routine_prog(level="seq", **kw) -> AccSrc:
    """A module function compiled for the device with routine and called
    in a parallel loop."""
    s = src()
    s.module = ["contains", "integer function twice_plus(x)",
                acc("routine", level), "integer, intent(in) :: x",
                "twice_plus = 2*x + 1", "end function twice_plus"]
    s.region = loop(acc("parallel loop", STD), ["b(i) = twice_plus(a(i))"])
    return s


def bind_prog() -> AccSrc:
    """routine bind (3.4 §2.15.1): on the device, calls of host_val use the
    bound name dev_val, which returns 2*x + 1; the host version returns
    -x. External procedures (CCE 19 stops with an internal error when the
    two are module procedures: data/findings/cce19-acc-routine-bind-module-
    ice.f90)."""
    s = src(decls=["integer, external :: host_val"],
            spec=[acc("routine(host_val) seq bind(dev_val)")])
    s.procs = [["integer function dev_val(x)", acc("routine seq"),
                "integer, intent(in) :: x", "dev_val = 2*x + 1",
                "end function dev_val"],
               ["integer function host_val(x)",
                acc("routine seq bind(dev_val)"),
                "integer, intent(in) :: x", "host_val = -x",
                "end function host_val"]]
    s.region = loop(acc("parallel loop", STD), ["b(i) = host_val(a(i))"])
    s.header_notes.append("oracle: without bind the device calls host_val "
                          "itself, which returns -x")
    return s


def cache_prog() -> AccSrc:
    s = src()
    # the cache directive at the top of the loop body (3.4 §2.10: "When the
    # cache directive appears at the top of (inside of) a loop").
    # It follows the host_flag statement.
    s.region = [acc("parallel loop", STD), "do i = 1, n",
                acc("cache(a(i:i))"), LOOP_FLAG, *BODY, "end do"]
    return s.no_oracle("hint_only", "cache suggests that the elements be "
                       "fetched into the fastest cache level; values are "
                       "the same without it", "cache_hint", checked=True)


def wait_dir_prog() -> AccSrc:
    """wait directive (3.4 §2.16.3): the kernel is asynchronous (async(1))
    and slow; the host reads b only after the wait."""
    s = src(decls=["integer :: k, w"])
    s.header_notes.append("oracle: without the wait the host may read b "
                          "before the asynchronous kernel completes")
    s.region = [acc("parallel loop", STD + " async(1) private(w)"),
                "do i = 1, n", LOOP_FLAG, "w = 0", "do k = 1, 200000",
                "w = w + mod(k, 2)", "end do", "b(i) = 2*a(i) + 1 + w - 100000",
                "end do", acc("wait(1)")]
    return s


def wait_clause_prog(arg="(1)") -> AccSrc:
    """wait clause (3.4 §2.16.2): the second kernel (queue 2) reads what
    the slow first kernel (queue 1) writes; wait(1) orders them."""
    s = src(decls=["integer :: k, w", "integer :: c(n)"])
    s.header_notes.append("oracle: without the wait clause the second "
                          "kernel may run before the first one completes")
    s.region = [acc("data", "copyin(a) create(c) copyout(b)"),
                acc("parallel loop", "async(1) private(w) copy(host_flag)"),
                "do i = 1, n", LOOP_FLAG, "w = 0", "do k = 1, 200000",
                "w = w + mod(k, 2)", "end do", "c(i) = 2*a(i) + w - 100000",
                "end do",
                acc("parallel loop", f"async(2) wait{arg}"),
                "do i = 1, n", "b(i) = c(i) + 1", "end do",
                acc("wait"), acc("end data")]
    return s


def set_prog() -> AccSrc:
    """set default_async (3.4 §2.14.3): async without an argument uses
    queue 2 afterwards, which wait(2) waits for."""
    s = src(decls=["integer :: k, w"])
    s.header_notes.append("oracle: without the set the kernel goes to the "
                          "default queue, which wait(2) does not wait for")
    s.region = [acc("set", "default_async(2)"),
                acc("parallel loop", STD + " async private(w)"),
                "do i = 1, n", LOOP_FLAG, "w = 0", "do k = 1, 200000",
                "w = w + mod(k, 2)", "end do", "b(i) = 2*a(i) + 1 + w - 100000",
                "end do", acc("wait(2)")]
    s.post = [acc("wait")]  # no kernel left running at the end
    return s


def init_prog(clause="") -> AccSrc:
    s = src(region=[acc("init", clause)] + std_kernel())
    return s.unverified("needs_other_infrastructure", "initialisation is "
                        "observable only as timing or through the profiling "
                        "interface (3.4 chapter 5); the runtime initialises "
                        "on first use anyway")


def shutdown_prog() -> AccSrc:
    """shutdown (3.4 §2.14.2) ends every data lifetime: an array entered
    with enter data is no longer present (copy mode: in shared memory
    presence is not tracked)."""
    s = src(decls=["integer :: t(n)"], init=["t = 0"])
    s.region = std_kernel() + [acc("enter data", "copyin(t)"),
                               acc("shutdown")]
    s.post = s.copy_check(".not. acc_is_present(t)")
    return s


def present_probe(clause="present(t)") -> AccSrc:
    """Negative probe (3.4 §2.7.3, p.52): t is not present, so a compute
    construct naming it present must end in runtime error termination
    (acc_error_not_present); a run that goes on prints check=fail."""
    s = src(decls=["integer :: t(n)", "logical :: continued"],
            init=["t = 0", "continued = .false."],
            checks=["(.not. continued)"], evidence="probe",
            expect="error_termination")
    s.header_notes.append(
        f"negative probe: {clause} with t not present requires an "
        "acc_error_not_present error (OpenACC 3.4 §2.7.3, p.52); reaching "
        "the end of the program prints check=fail")
    s.region = std_kernel() + [acc("parallel loop", clause)] + [
        "do i = 1, n", "t(i) = i", "end do", "continued = .true."]
    return s


def if_prog() -> AccSrc:
    """The if clause judged on a data directive (3.4 §2.14.4:
    with the condition false the update moves no data). b is computed on
    the device in a data region (copyout at its end); the host then writes
    b(1) = -9 (copy mode only) and ``update device(b) if(use_dev)`` with
    use_dev false must not send it, so the copyout brings the device b
    back. Without the clause the update sends -9 (copy mode). (The if
    clause on a compute construct with a false condition runs the region
    on the local thread, which is not device offload; the clause is the
    same atom.)"""
    s = src(decls=["logical :: use_dev"], init=["use_dev = .false."])
    s.shared_setup()
    s.region = [acc("data", "copyin(a) copyout(b)")] + std_kernel(
        "parallel loop", "copy(host_flag)") + [
        "if (.not. shared_mem) b(1) = -9",
        acc("update", "device(b) if(use_dev)"), acc("end data")]
    return s


def self_prog() -> AccSrc:
    """The self clause in its update form (3.4 §2.14.4,
    ``self(list)``: copy from device to local memory), the program of
    update_prog: b is created on the device and computed there, and the
    update copies it to the host (copy mode). The compute-construct form
    (self with a condition, acc.clause.self.condition) sends the region to
    the host and is out of scope (catalog/acc/out_of_scope.yaml)."""
    s = update_prog("self(b)")
    s.focus = "self(b)"
    return s


def private_prog(directive="parallel loop") -> AccSrc:
    """private(t) (3.4 §2.5.13, §2.9.10): each thread's t is its own and
    the host t is not written; without the clause t is implicitly copy
    (shared storage, or copied back), so the host t changes."""
    s = src(decls=["integer :: t(2)"], init=["t = -7"],
            checks=["all(t == -7)"])
    s.region = [acc(directive, STD + " private(t)"), "do i = 1, n",
                LOOP_FLAG, "t(1) = a(i)", "t(2) = 1", "b(i) = 2*t(1) + t(2)",
                "end do"]
    return s


def loop_private_prog() -> AccSrc:
    s = private_prog()
    s.region = [acc("parallel", STD), acc("loop", "private(t)"),
                "do i = 1, n", LOOP_FLAG, "t(1) = a(i)", "t(2) = 1",
                "b(i) = 2*t(1) + t(2)", "end do", acc("end parallel")]
    return s


def firstprivate_prog() -> AccSrc:
    """firstprivate(t) (3.4 §2.5.14): the serial region's copy starts with
    the host value and the host t is not written."""
    s = src(decls=["integer :: t(2)"], init=["t = 5"],
            checks=["all(t == 5)"], ref="2*i + 6")
    s.region = [acc("serial", STD + " firstprivate(t)"), FLAG,
                "t(1) = t(1) + 1"] + loop(None, ["b(i) = 2*a(i) + t(1)"],
                                          flag=False) + [acc("end serial")]
    return s


REDUCTIONS = {
    # feature -> (operator, type, initial, value of iteration i, expected)
    "plus": ("+", "integer", "10", "a(i)", "10 + n*(n + 1)/2"),
    "times": ("*", "integer", "3", "merge(2, 1, i <= 10)", "3*1024"),
    "max": ("max", "integer", "-5", "mod(7*a(i), 61)", "60"),
    "min": ("min", "integer", "100", "mod(7*a(i), 61) + 3", "3"),
    "iand": ("iand", "integer", "255", "merge(254, 255, i == 9)", "254"),
    "ior": ("ior", "integer", "0", "merge(4, 0, i == 9)", "4"),
    "ieor": ("ieor", "integer", "1", "merge(6, 0, i == 9)", "7"),
    "and": (".and.", "logical", ".true.", "i /= 9", ".false."),
    "or": (".or.", "logical", ".false.", "i == 9", ".true."),
    "eqv": (".eqv.", "logical", ".true.", "i /= 9", ".false."),
    "neqv": (".neqv.", "logical", ".false.", "i == 9", ".true."),
}


def reduction_prog(feat="plus", combined=True) -> AccSrc:
    """reduction(<op>: s) (3.4 §2.5.15, §2.9.11): the result reaches the
    host (a reduction var is implicitly copy, §2.6.2); without the clause s
    is firstprivate and keeps its initial value on the host."""
    op, typ, init, val, want = REDUCTIONS[feat]
    s = src(decls=[f"{typ} :: s"], init=[f"s = {init}"])
    s.checks.append(f"(s .eqv. {want})" if typ == "logical"
                    else f"(s == {want})")
    if op in ("+", "*", ".and.", ".or.", ".eqv.", ".neqv."):
        upd = f"s = s {op} ({val})"
    else:
        upd = f"s = {op}(s, {val})"
    if combined:
        s.region = loop(acc("parallel loop", f"{STD} reduction({op}: s)"),
                        list(BODY) + [upd])
    else:
        s.region = [acc("parallel", f"{STD} copy(s)"),
                    *loop(acc("loop", f"reduction({op}: s)"),
                          list(BODY) + [upd]), acc("end parallel")]
    return s


def data_clause_prog(clause: str) -> AccSrc:
    """A data clause on a compute construct (3.4 §2.7): copy and copyout
    bring b back, copyin sends a; create(t) gives the kernel a device-only
    t, so the host t is unchanged (copy mode)."""
    s = src()
    s.shared_setup()
    if clause == "create":
        s.decls.append("integer :: t(n)")
        s.init.append("t = -7")
        s.region = loop(acc("parallel loop", "copyin(a) copyout(b) create(t) "
                            "copy(host_flag)"), ["t(i) = a(i)",
                                                 "b(i) = 2*t(i) + 1"])
        s.post = s.copy_check("all(t == -7)")
        return s
    clauses = {"copy": "copyin(a) copy(b) copy(host_flag)",
               "copyin": "copyin(a) copyout(b) copy(host_flag)",
               "copyout": "copyin(a) copyout(b) copy(host_flag)"}[clause]
    s.region = loop(acc("parallel loop", clauses))
    return s


def delete_prog(finalize=False) -> AccSrc:
    """exit data delete (3.4 §2.7.12) ends t's dynamic lifetime; with
    finalize (§2.6.6) also after two enter data copyin (reference count
    2). Presence is checked in copy mode."""
    s = src(decls=["integer :: t(n)"], init=["t = 0"])
    s.region = std_kernel() + [acc("enter data", "copyin(t)")]
    if finalize:
        s.region += [acc("enter data", "copyin(t)"),
                     acc("exit data", "delete(t) finalize")]
    else:
        s.region += [acc("exit data", "delete(t)")]
    s.post = s.copy_check(".not. acc_is_present(t)")
    return s


def if_present_prog() -> AccSrc:
    """update self(t) if_present with t not present (3.4 §2.14.4): no action
    and no error; without if_present the update requires t to be present
    (acc_error_not_present, copy mode)."""
    s = src(decls=["integer :: t(n)"], init=["t = 3"])
    s.shared_setup()
    s.region = std_kernel() + [acc("update", "self(t) if_present")]
    s.checks.append("all(t == 3)")
    return s


def link_prog() -> AccSrc:
    """declare link (3.4 §2.13.3): a module array used in a routine; its
    device copy exists while a data clause allocates it."""
    s = src()
    s.module = ["integer :: lv(64)", acc("declare", "link(lv)"), "contains",
                "integer function get_lv(k)", acc("routine seq"),
                "integer, intent(in) :: k", "get_lv = lv(k)",
                "end function get_lv"]
    s.init = ["do i = 1, n", "lv(i) = 2*i + 1", "end do"]
    s.region = loop(acc("parallel loop", STD + " copyin(lv)"),
                    ["b(i) = get_lv(a(i))"])
    return s


def device_resident_prog() -> AccSrc:
    s = src()
    s.module = ["integer :: dr(64)", acc("declare", "device_resident(dr)")]
    s.region = loop(acc("parallel loop", STD), ["dr(i) = 2*a(i)",
                                                "b(i) = dr(i) + 1"])
    return s.unverified(
        "needs_other_infrastructure", "device_resident places dr in device "
        "memory only; the host may not access it (3.4 §2.13.1), so the only "
        "difference is where the storage lives, which a conforming program "
        "cannot read")


def attach_prog(clause: str) -> AccSrc:
    """attach / detach of an allocatable component (3.4 §2.7.13-14)."""
    s = src(decls=["type :: holder", "integer, allocatable :: v(:)",
                   "end type holder", "type(holder) :: h"],
            init=["allocate(h%v(n))", "h%v = 1"])
    s.region = [acc("enter data", "copyin(h)"), acc("enter data",
                                                    "copyin(h%v)")]
    if clause == "attach":
        s.region += [acc("enter data", "attach(h%v)")]
    s.region += loop(acc("parallel loop", STD + " present(h)"),
                     ["b(i) = 2*a(i) + h%v(i)"])
    s.ref = "2*i + 1"
    if clause == "detach":
        s.region += [acc("exit data", "detach(h%v)")]
    s.region += [acc("exit data", "delete(h%v)"), acc("exit data",
                                                      "delete(h)")]
    return s.unverified(
        "oracle_not_written", f"{clause} of h%v: copyin(h%v) already "
        "attaches the device pointer (3.4 §2.7.8), so the program cannot "
        f"separate an explicit {clause}; a check needs a pointer whose "
        "target enters the device before its parent without an attach "
        "action (create of the target, then attach)")


def no_create_prog() -> AccSrc:
    s = src()
    s.region = [acc("data", "copyin(a) copyout(b)")] + loop(
        acc("parallel loop", "no_create(a, b) copy(host_flag)")) + [
        acc("end data")]
    return s.unverified(
        "oracle_not_written", "no_create on present data behaves as "
        "present; the separating case is an absent var, whose device code "
        "then uses the host address (3.4 §2.7.11), which copy mode faults "
        "on and zero-copy shares, so a check needs a var the kernel does "
        "not dereference")


def deviceptr_prog() -> AccSrc:
    return host_data_prog().unverified(
        "needs_other_infrastructure", "deviceptr tells the compiler the "
        "dummies hold device addresses; without it they are implicitly "
        "copy, and on the MI300A the host can read and write device memory, "
        "so the copies of the device addresses work too (the audit's mutant "
        "survived): a check needs a device whose memory the host cannot "
        "address", checked=True)


def schedule_only(clause_line: str, what: str, directive="parallel loop",
                  nest=1, header=None) -> AccSrc:
    """A loop-scheduling clause in a correct program: the result is the
    same under any schedule."""
    s = src(decls=["integer :: j, k"] if nest == 2 else [])
    if nest == 2:  # a rectangular 8 x 8 nest over the 64 elements
        s.region = [acc(directive, f"{STD} {clause_line}"),
                    "do j = 1, 8", "do k = 1, 8",
                    "if (j == 1 .and. k == 1) " + FLAG,
                    "b((j - 1)*8 + k) = 2*a((j - 1)*8 + k) + 1",
                    "end do", "end do"]
    else:
        s.region = loop(acc(directive, f"{STD} {clause_line}"))
    return s.unverified(
        "needs_other_infrastructure", f"{what} decides which gang, worker "
        "or vector lane runs an iteration; no OpenACC routine reports it "
        "(the result of a correct loop is the same under every schedule)",
        checked=True)


def seq_prog() -> AccSrc:
    """loop seq (3.4 §2.9.5): a running sum in a sequential inner loop of a
    gang loop; executed in parallel the recurrence breaks."""
    s = src(decls=["integer :: c(0:8, 8), j, k"], init=["c = 0"],
            checks=["all(c(8, :) == 36)", "all(c(1:8, 3) == "
                    "[(k*(k + 1)/2, k = 1, 8)])"])
    s.header_notes.append("oracle: without seq the inner loop is "
                          "independent in a parallel construct (3.4 §2.9.6) "
                          "and may run concurrently, breaking the recurrence")
    s.region = loop(acc("parallel loop", f"{STD} copy(c)")) + [
        acc("parallel loop", "gang copy(c)"), "do j = 1, 8",
        acc("loop", "seq"), "do k = 1, 8", "c(k, j) = c(k - 1, j) + k",
        "end do", "end do"]
    return s


def kernels_loop_prog(clause="") -> AccSrc:
    return src(region=[acc("kernels", STD)] + loop(acc("loop", clause))
               + [acc("end kernels")])


def default_none_prog() -> AccSrc:
    s = src(region=loop(acc("parallel loop", "default(none) copyin(a) "
                            "copyout(b) copy(host_flag)")),
            evidence="legality", legality_rule="default-dsa-001",
            observable=False,
            note="legality: the check covers the device kernel, not the atom")
    s.header_notes.append("default(none) only requires every variable to "
                          "appear in a data or data-sharing clause: a "
                          "compile-time restriction")
    return s


def implicit_firstprivate_prog() -> AccSrc:
    """Semantic atom acc.clause.firstprivate.implicit_scalar: a scalar in
    no data clause is firstprivate on a parallel or serial construct (3.4
    §2.6.2), so the region's write does not reach the host (both memory
    modes: a private copy)."""
    s = src(decls=["integer :: x"], init=["x = 5"], checks=["(x == 5)"],
            ref="2*i + 10")
    s.region = [acc("serial", STD), FLAG, "x = x + 4"] + loop(
        None, ["b(i) = 2*a(i) + x + 1"], flag=False) + [acc("end serial")]
    return s


def implicit_kernels_copy_prog() -> AccSrc:
    """Semantic atom acc.clause.copy.implicit_kernels_scalar: a scalar in
    no data clause is copy on a kernels construct (3.4 §2.6.2): the
    device's write reaches the host (copy mode: copied back)."""
    s = src(decls=["integer :: x"], init=["x = 5"], checks=["(x == 9)"])
    s.shared_setup()
    s.region = [acc("kernels", STD), "x = 9"] + loop(None) + [
        acc("end kernels")]
    return s


def device_type_prog() -> AccSrc:
    s = src(region=loop(acc("parallel loop",
                            f"{STD} device_type(*) vector_length(32)")))
    return s.no_oracle("implementation_defined", "the device types and "
                       "their names are implementation-defined; the clauses "
                       "after device_type(*) are hints here (vector_length)",
                       "device_types", checked=True)


# --- atom -> recipe ----------------------------------------------------------

def _no_oracle(s: AccSrc, kind, reason, basis) -> AccSrc:
    return s.no_oracle(kind, reason, basis, checked=True)


def directive_recipe(name: str) -> AccSrc:
    combined = {"parallel_loop": "parallel loop", "kernels_loop":
                "kernels loop", "serial_loop": "serial loop"}
    if name in combined:
        return src(region=std_kernel(combined[name]))
    return {
        "parallel": parallel_prog, "kernels": kernels_prog,
        "serial": serial_prog, "loop": loop_redundancy_prog,
        "data": data_prog, "enter_data": lambda: scribble_prog(
            "copyin(a) create(b)", "copyout(b) delete(a)"),
        "exit_data": lambda: scribble_prog("copyin(a) create(b)",
                                           "copyout(b) delete(a)"),
        "update": update_prog, "host_data": host_data_prog,
        "declare": declare_prog, "atomic": atomic_prog,
        "routine": lambda: _no_oracle(
            routine_prog(), "equivalent_default", "a procedure called in a "
            "compute region without a routine directive gets an implicit "
            "routine seq (3.4 §2.15.1), the directive this program writes",
            "routine_implicit"),
        "cache": cache_prog, "wait": wait_dir_prog,
        "init": init_prog, "shutdown": shutdown_prog, "set": set_prog,
    }[name]()


def clause_recipe(clause: str, feat: str | None) -> AccSrc | None:
    key = clause if feat is None else f"{clause}.{feat}"
    if clause == "reduction":
        return reduction_prog(feat or "plus", combined=feat is not None)
    table = {
        "async": lambda: _no_oracle(
            src(region=std_kernel("parallel loop", STD + " async")
                + [acc("wait")]), "implementation_defined",
            "async lets the operations run asynchronously; they may also "
            "complete before the host goes on, so no run separates it",
            "async_may"),
        "async.async_argument": lambda: _no_oracle(
            src(region=std_kernel("parallel loop", STD + " async(3)")
                + [acc("wait(3)")]), "implementation_defined",
            "the queue number selects an activity queue whose operations "
            "may run asynchronously or not", "async_may"),
        "attach": lambda: attach_prog("attach"),
        "detach": lambda: attach_prog("detach"),
        "auto": lambda: _no_oracle(
            kernels_loop_prog("auto"), "equivalent_default",
            "in a kernels construct a loop without independent or seq is "
            "treated as auto", "auto_kernels"),
        "bind": bind_prog,
        "capture": capture_prog,
        "collapse": lambda: schedule_only("collapse(2)", "collapse",
                                          nest=2),
        "collapse.force": lambda: schedule_only("collapse(force: 2)",
                                                "collapse(force: 2)", nest=2),
        "copy": lambda: data_clause_prog("copy"),
        "copyin": lambda: data_clause_prog("copyin"),
        "copyout": lambda: data_clause_prog("copyout"),
        "create": lambda: data_clause_prog("create"),
        "default": lambda: present_probe("default(present)"),
        "default.present": lambda: present_probe("default(present)"),
        "default.none": default_none_prog,
        "default_async": set_prog,
        "delete": delete_prog,
        "device": update_device_prog,
        "device_num": lambda: init_prog("device_num(0)").unverified(
            "needs_other_infrastructure", "selecting a device by number is "
            "separable only with a second device of the type, which this "
            "slice does not use (brief: nothing needing multiple devices)"),
        "device_resident": device_resident_prog,
        "device_type": device_type_prog,
        "deviceptr": deviceptr_prog,
        "finalize": lambda: delete_prog(finalize=True),
        "firstprivate": firstprivate_prog,
        "gang": lambda: _no_oracle(
            loop_redundancy_prog("loop gang"), "equivalent_default",
            "a data-independent loop in a parallel construct without a gang "
            "clause has an implied gang(dim:1) clause", "gang_implied"),
        "gang.dim": lambda: _no_oracle(
            loop_redundancy_prog("loop gang(dim: 1)"), "equivalent_default",
            "dimension one is the gang clause's dimension without dim",
            "gang_dim_default"),
        "gang.num": lambda: kernels_loop_prog("gang(num: 4)").unverified(
            "needs_other_infrastructure", "the number of gangs a kernels "
            "loop uses is not reported by any OpenACC routine and the result "
            "is the same for every number", checked=True),
        "gang.static": lambda: schedule_only("gang(static: 4)",
                                             "gang(static: 4)"),
        "host": lambda: update_prog("host(b)"),
        "if": if_prog,
        "if_present": if_present_prog,
        "independent": lambda: _no_oracle(
            kernels_loop_prog("independent"), "hint_only",
            "independent asserts that the iterations are data-independent; "
            "the implementation may parallelise the loop with or without it",
            "independent_assertion"),
        "link": link_prog,
        "no_create": no_create_prog,
        "nohost": lambda: routine_prog("seq nohost").unverified(
            "needs_other_infrastructure", "nohost only stops the host "
            "version from being compiled; a conforming program never calls "
            "it on the host, so its absence shows only as a link failure of "
            "a non-conforming one"),
        "num_gangs": lambda: _no_oracle(
            src(region=std_kernel("parallel loop", STD + " num_gangs(4)")),
            "hint_only", "the implementation may use fewer gangs",
            "num_gangs_lower"),
        "num_workers": lambda: _no_oracle(
            src(region=std_kernel("parallel loop", STD + " num_workers(2)")),
            "hint_only", "the implementation may use another number of "
            "workers", "num_workers_value"),
        "present": lambda: present_probe("present(t)"),
        "private": loop_private_prog,
        "read": lambda: atomic_rw_prog("read"),
        "self": lambda: self_prog(),
        "seq": seq_prog,
        "tile": lambda: schedule_only("tile(8, 8)", "tile", nest=2),
        "update": lambda: _no_oracle(
            atomic_prog("update"), "equivalent_default",
            "atomic without a clause has the semantics of atomic update",
            "atomic_update_default"),
        "use_device": host_data_prog,
        "vector": lambda: schedule_only("gang vector", "vector"),
        # an argument of vector has a defined role only under a kernels
        # construct without vector_length (3.4 §2.9.4, p.68); under a
        # parallel construct the vector length is the construct's
        "vector.length": lambda: kernels_loop_prog(
            "gang vector(length: 32)").unverified(
            "needs_other_infrastructure", "vector(length: 32) decides which "
            "gang, worker or vector lane runs an iteration; no OpenACC "
            "routine reports it (the result of a correct loop is the same "
            "under every schedule)", checked=True),
        "vector_length": lambda: _no_oracle(
            src(region=std_kernel("parallel loop", STD + " vector_length(32)")),
            "hint_only", "the implementation may use another vector length",
            "vector_length_value"),
        "wait": lambda: _no_oracle(
            wait_clause_prog(), "implementation_defined",
            "operations on different queues may run in either order or "
            "concurrently, and also in order (CCE runs the second kernel "
            "after the first without the clause: the audit's mutant "
            "survived), so no run separates the clause", "async_queues"),
        "wait.devnum": lambda: _no_oracle(
            wait_clause_prog("(devnum: dn: 1)"), "equivalent_default",
            "devnum names the current device, the associated device "
            "without it", "wait_devnum_current"),
        "wait.queues": lambda: _no_oracle(
            wait_clause_prog("(queues: 1)"), "equivalent_default",
            "the queues modifier is optional, for clarity",
            "wait_queues_optional"),
        "worker": lambda: schedule_only("gang worker", "worker"),
        "worker.num": lambda: kernels_loop_prog("gang worker(num: 2)")
        .unverified("needs_other_infrastructure", "the number of workers a "
                    "kernels loop uses is not reported by any OpenACC "
                    "routine and the result is the same for every number",
                    checked=True),
        "write": lambda: atomic_rw_prog("write"),
        "firstprivate.implicit_scalar": implicit_firstprivate_prog,
        "copy.implicit_kernels_scalar": implicit_kernels_copy_prog,
    }
    fn = table.get(key)
    return fn() if fn else None


def recipe(atom: str, version: int) -> T.Src:
    """The program source of an OpenACC atom (acc.directive.<name>,
    acc.clause.<name>[.<feature>])."""
    from offload.engine.gen import GenError
    parts = atom.split(".")
    if len(parts) < 3 or parts[0] != "acc":
        raise GenError(f"not an OpenACC atom id: {atom!r}")
    if parts[1] == "directive":
        try:
            s = directive_recipe(parts[2])
        except KeyError:
            raise GenError(f"no recipe for {atom!r}") from None
    else:
        s = clause_recipe(parts[2], parts[3] if len(parts) > 3 else None)
    if s is None:
        raise GenError(f"no recipe for {atom!r} at {version}")
    if "wait.devnum" in atom:
        s.decls.append("integer :: dn")
        s.init.append("dn = acc_get_device_num(acc_get_device_type())")
    return s


# --- illegal variants --------------------------------------------------------

def _sub(old: str, new: str, count: int = 1):
    def fn(source: str) -> str:
        from offload.engine.gen import GenError
        n = source.count(old)
        if n != count:
            raise GenError(f"transform: {old!r} occurs {n} times, "
                           f"expected {count}")
        return source.replace(old, new)
    return fn


def _insert_after(pattern: str, line: str):
    def fn(source: str) -> str:
        from offload.engine.gen import GenError
        src_ = source.split("\n")
        hits = [k for k, ln in enumerate(src_)
                if re.fullmatch(pattern, ln.strip())]
        if len(hits) != 1:
            raise GenError(f"transform: {pattern!r} matches {len(hits)} "
                           "lines, expected 1")
        k = hits[0]
        ind = src_[k + 1][:len(src_[k + 1]) - len(src_[k + 1].lstrip())]
        src_.insert(k + 1, ind + line)
        return "\n".join(src_)
    return fn


_STD_LINE = f"!$acc parallel loop {STD}"
# rule stem -> (base atom, transform): one change each, so that the variant
# violates exactly that rule (checked by offload.engine.gen._illegal)
ILLEGAL: dict[str, tuple] = {
    "compute-clause-001": ("acc.directive.parallel_loop", _sub(
        _STD_LINE, _STD_LINE + " device_type(*) default(present)")),
    "data-clause-001": ("acc.directive.data", _sub(
        "!$acc data copyin(a) copyout(b)",
        "!$acc data copyin(a) copyout(b) device_type(*) if(.true.)")),
    "loop-clause-001": ("acc.directive.loop", _sub(
        "!$acc loop\n", "!$acc loop device_type(*) private(host_flag)\n")),
    "update-clause-001": ("acc.directive.update", _sub(
        "!$acc update self(b)", "!$acc update self(b) device_type(*) "
        "if_present")),
    "routine-clause-001": ("acc.clause.bind", _sub(
        "!$acc routine seq bind(dev_val)",
        "!$acc routine seq bind(dev_val) device_type(*) nohost")),
    "compute-clause-002": ("acc.clause.reduction.plus", _sub(
        "reduction(+: s)", "reduction(+: s) num_gangs(2, 2)")),
    "numgangs-clause-001": ("acc.directive.kernels", _sub(
        f"!$acc kernels {STD}", f"!$acc kernels {STD} num_gangs(2, 2)")),
    "numgangs-clause-002": ("acc.directive.parallel", _sub(
        "num_gangs(1)", "num_gangs(2, 2, 2, 2)")),
    "hostonly-placement-001": ("acc.directive.parallel", _insert_after(
        re.escape(f"!$acc parallel {STD} num_gangs(1)"), "!$acc init")),
    "loop-clause-002": ("acc.clause.seq", _sub(
        "!$acc loop seq", "!$acc loop seq vector")),
    "loop-clause-003": ("acc.clause.gang", _sub(
        "!$acc loop gang", "!$acc loop gang gang(dim: 1)")),
    "gang-clause-001": ("acc.clause.gang", _sub(
        "!$acc loop gang", "!$acc loop gang(num: 4)")),
    "gang-clause-002": ("acc.clause.gang.num", _sub(
        "gang(num: 4)", "gang(dim: 1)")),
    "gang-clause-003": ("acc.clause.gang.dim", _sub(
        "gang(dim: 1)", "gang(dim: 4)")),
    "collapse-clause-001": ("acc.clause.collapse", _sub(
        "collapse(2)", "collapse(0)")),
    "collapse-loop-001": ("acc.clause.collapse", _sub(
        "collapse(2)", "collapse(3)")),
    "tile-loop-001": ("acc.clause.tile", _sub("tile(8, 8)",
                                              "tile(8, 8, 8)")),
    "tile-clause-001": ("acc.clause.tile", _sub("tile(8, 8)", "tile(0, 8)")),
    "hostdata-clause-001": ("acc.directive.host_data", _sub(
        "use_device(a, b)", "use_device(a, b(1))")),
    "declare-clause-002": ("acc.directive.declare", _sub(
        "!$acc declare create(t)",
        "!$acc declare create(t)\n  !$acc declare copyin(t)")),
    "declare-placement-001": ("acc.directive.declare", _sub(
        "!$acc declare create(t)", "!$acc declare link(t)")),
    "routine-clause-002": ("acc.clause.bind", _sub(
        "!$acc routine seq bind(dev_val)",
        "!$acc routine seq gang bind(dev_val)")),
    "atomic-clause-001": ("acc.clause.read", _sub(
        "!$acc atomic read", "!$acc atomic read write")),
    "cache-clause-001": ("acc.directive.cache", _sub(
        "!$acc cache(a(i:i))", "!$acc cache(a)")),
    "default-dsa-001": ("acc.clause.default.none", _sub(
        "default(none) copyin(a) copyout(b)", "default(none) copyin(a)")),
    "reduction-dsa-001": ("acc.clause.reduction", _sub(
        f"!$acc parallel {STD} copy(s)", f"!$acc parallel {STD}")),
    "reduction-clause-001": ("acc.clause.reduction", _sub(
        f"!$acc parallel {STD} copy(s)",
        f"!$acc parallel {STD} copy(s) reduction(*: s)")),
}


# --- the openacc stub for the base-language check ----------------------------

OPENACC_STUB = """\
! Declaration-only stub of the openacc module, for the base-language check
! only (gfortran -std=<level> -fsyntax-only, without -fopenacc): it declares
! the OpenACC 3.4 names the generated programs use (3.4 chapter 3), so that
! `use openacc, only:` resolves without any compiler's OpenACC module. Never
! linked, never run.
module openacc
  implicit none
  integer, parameter :: acc_device_kind = 4
  integer, parameter :: acc_handle_kind = 4
  integer(acc_device_kind), parameter :: acc_device_none = 0
  integer(acc_device_kind), parameter :: acc_device_default = 1
  integer(acc_device_kind), parameter :: acc_device_host = 2
  integer(acc_device_kind), parameter :: acc_device_not_host = 3
  integer(acc_handle_kind), parameter :: acc_async_noval = -1
  integer(acc_handle_kind), parameter :: acc_async_sync = -2
  interface
    logical function acc_on_device(dev_type)
      import :: acc_device_kind
      integer(acc_device_kind), value :: dev_type
    end function acc_on_device
    integer function acc_get_device_num(dev_type)
      import :: acc_device_kind
      integer(acc_device_kind) :: dev_type
    end function acc_get_device_num
    integer(acc_device_kind) function acc_get_device_type()
      import :: acc_device_kind
    end function acc_get_device_type
    logical function acc_is_present(a)
      integer, dimension(:) :: a
    end function acc_is_present
  end interface
end module openacc
"""

OPENACC_STUB_NAMES = frozenset({
    "acc_device_kind", "acc_handle_kind", "acc_device_none",
    "acc_device_default", "acc_device_host", "acc_device_not_host",
    "acc_async_noval", "acc_async_sync", "acc_on_device",
    "acc_get_device_num", "acc_get_device_type", "acc_is_present"})
