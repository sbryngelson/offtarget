"""Fuzz programs in the patterns of MFC's offload code (fuzz-mfc1: OpenMP, fuzz-mfcacc1: OpenACC).

The patterns are MFC's generated builds' (results/apps/mfc/*/fypp): module variables of nested
derived types (vector_field%vf(:) of scalar_field%sf(:, :, :)) made device-resident by declare
target (declare create) and an enter data of each allocatable component as it is allocated;
kernels over collapse(3) or collapse(4) nests with MFC's clause list (OpenMP: defaultmap
firstprivate:scalar, tofrom:aggregate, present:allocatable, present:pointer; OpenACC: gang vector
default(present)) and the loop indices and temporaries private; sequential inner loops over the
equations; device subroutines with an intent(out) result; clamped neighbour reads; atomic
updates of a device scalar; update to and from the device between kernels. A kernel reads one
field and writes the other, so no iteration reads what another writes; the expected checksum is
the program's sequential value, computed here (offload.engine.fuzz expressions)."""
from __future__ import annotations

import random
from dataclasses import dataclass

from offload.engine import fuzz as F

GEN = "fuzz-mfc1"
GEN_ACC = "fuzz-mfcacc1"
VERSIONS = (GEN, GEN_ACC)
MOD = 2147483629
# MFC's clause lists, in its order (the generated m_rhs and m_riemann_solvers kernels)
CLAUSES_OMP = ("defaultmap(firstprivate:scalar)", "collapse({c})", "defaultmap(tofrom:aggregate)",
               "defaultmap(present:allocatable)", "defaultmap(present:pointer)", "private({p})")
CLAUSES_ACC = ("collapse({c})", "gang", "vector", "default(present)", "private({p})")


def _directive(indent: str, name: str, clauses: list, omp: bool) -> list[str]:
    """A directive with free-form continuation lines (offload.engine.fuzz.wrap_directive)."""
    lines = F.wrap_directive(indent, name, clauses)
    return lines if omp else [ln.replace("!$omp", "!$acc", 1) for ln in lines]


def _stmt(indent: str, text: str) -> list[str]:
    return F.wrap_stmt(indent, text)


@dataclass(frozen=True)
class FRef(F.Ex):
    """field%vf(eqn)%sf(j, k, l)."""
    field: str
    eqn: F.Ex
    idx: tuple

    def f(self):
        return f"{self.field}%vf({self.eqn.f()})%sf({', '.join(x.f() for x in self.idx)})"

    def ev(self, env, arrs):
        return arrs[(self.field, self.eqn.ev(env, arrs))][tuple(x.ev(env, arrs) for x in self.idx)]


@dataclass(frozen=True)
class PRef(F.Ex):
    """A private array's element: alpha(i)."""
    name: str
    i: F.Ex

    def f(self):
        return f"{self.name}({self.i.f()})"

    def ev(self, env, arrs):
        return env[self.name][self.i.ev(env, arrs)]


def _band(e: F.Ex) -> F.Ex:
    return F.Intr("iand", (e, F.Const(1023)))


class MfcGen:
    def __init__(self, seed: int, model: str = "omp"):
        self.seed, self.model = seed, model
        self.r = random.Random(f"mfc-{model}-{seed}")
        self.m, self.n, self.p = (self.r.randint(2, 5) for _ in range(3))
        self.nv = self.r.randint(2, 4)
        self.features: set = {f"model:{model}"}
        self.kernels: list = []

    # --- expressions ---------------------------------------------------------------------
    def expr(self, leaves: list, depth: int = 2) -> F.Ex:
        if depth == 0 or self.r.random() < 0.3:
            return self.r.choice(leaves)
        kind = self.r.choice(("+", "-", "*", "iand", "ieor", "max", "min", "merge", "mod"))
        a, b = self.expr(leaves, depth - 1), self.expr(leaves, depth - 1)
        if kind == "*":
            return F.Bin("*", _band(a), F.Intr("iand", (b, F.Const(31))))
        if kind in ("+", "-"):
            return F.Bin(kind, a, b)
        if kind == "merge":
            c = F.Cond(self.r.choice(("<", ">=", "/=")), a, b)
            return F.Merge(b, a, c)
        if kind == "mod":
            return F.Intr("mod", (a, F.Const(self.r.randint(3, 97))))
        return F.Intr(kind, (a, b))

    def index(self, v: str, top: str) -> F.Ex:
        """j, or a clamped neighbour min(j + 1, m) / max(j - 1, 0) (MFC's stencil reads)."""
        x = self.r.random()
        if x < 0.2:
            self.features.add("mfc:neighbour")
            return F.Intr("min", (F.Bin("+", F.Var(v), F.Const(1)), F.Var(top)))
        if x < 0.4:
            self.features.add("mfc:neighbour")
            return F.Intr("max", (F.Bin("-", F.Var(v), F.Const(1)), F.Const(0)))
        return F.Var(v)

    # --- the program ---------------------------------------------------------------------
    def build(self) -> F.FuzzProgram:
        r = self.r
        omp = self.model == "omp"
        arrs = {}
        for fld in ("qa", "qb"):
            for e in range(1, self.nv + 1):
                arrs[(fld, e)] = {(j, k, l): ((7 * j + 13 * k + 29 * l + 101 * e + (5 if fld == "qa" else 0)) % 1009)
                                  if fld == "qa" else 0
                                  for j in range(self.m + 1) for k in range(self.n + 1) for l in range(self.p + 1)}
        # device routines: subroutine s_mixN(a, b, c, r) with r intent(out)
        routines = []
        for i in range(r.randint(1, 2)):
            body = _band(self.expr([F.Var("a"), F.Var("b"), F.Var("c"), F.Const(r.randint(1, 50))], 2))
            routines.append((f"s_mix{i + 1}", body))
        self.features.add("mfc:routine")
        tot = 0
        body: list = []
        env_points = [(j, k, l) for l in range(self.p + 1) for k in range(self.n + 1) for j in range(self.m + 1)]
        src, dst = "qa", "qb"
        for kn in range(r.randint(2, 4)):
            c4 = r.random() < 0.35
            atomic = r.random() < 0.4
            rname, rbody = r.choice(routines)
            ind = "  "
            priv = ["i", "j", "k", "l", "t1", "t2"] + ([] if c4 else ["alpha"])
            clauses = [c.format(c=4 if c4 else 3, p=", ".join(priv)) for c in (CLAUSES_OMP if omp else CLAUSES_ACC)]
            lines = _directive(ind, "target teams distribute parallel do" if omp else "parallel loop", clauses, omp)
            self.features.add("mfc:collapse4" if c4 else "mfc:collapse3")
            jj, kk, ll = self.index("j", "m"), self.index("k", "n"), self.index("l", "p")
            if c4:
                # do i = 1, nv outermost (the equation index collapsed with the grid)
                rd = FRef(src, F.Var("i"), (jj, kk, ll))
                e1 = _band(self.expr([rd, F.Var("i"), F.Var("j"), F.Const(r.randint(1, 60))], 2))
                e2 = _band(self.expr([F.Var("t1"), F.Var("t2"), F.Var("k"), F.Const(r.randint(1, 60))], 2))
                lines += [f"{ind}do i = 1, nv", f"{ind}  do l = 0, p", f"{ind}    do k = 0, n", f"{ind}      do j = 0, m",
                          *_stmt(f"{ind}        ", f"t1 = {e1.f()}"), f"{ind}        call {rname}(t1, j, k, t2)",
                          *_stmt(f"{ind}        ", f"{dst}%vf(i)%sf(j, k, l) = {e2.f()}")]
                inner = f"{ind}        "
                ends = [f"{ind}      end do", f"{ind}    end do", f"{ind}  end do", f"{ind}end do"]
                for i in range(1, self.nv + 1):
                    for (j, k, l) in env_points:
                        env = {"i": i, "j": j, "k": k, "l": l, "m": self.m, "n": self.n, "p": self.p}
                        t1 = e1.ev(env, arrs)
                        t2 = rbody.ev({"a": t1, "b": j, "c": k}, arrs)
                        env.update(t1=t1, t2=t2)
                        arrs[(dst, i)][(j, k, l)] = e2.ev(env, arrs)
                        if atomic:
                            tot += t2 & 15
            else:
                self.features.update({"mfc:seq-equations", "mfc:private-array"})
                rd = FRef(src, F.Var("i"), (jj, kk, ll))
                e1 = _band(self.expr([rd, F.Var("i"), F.Var("j"), F.Var("l"), F.Const(r.randint(1, 60))], 2))
                e2 = _band(self.expr([PRef("alpha", F.Const(1)), PRef("alpha", F.Var("nv")), F.Var("k"),
                                      F.Const(r.randint(1, 60))], 2))
                e3 = _band(self.expr([PRef("alpha", F.Var("i")), F.Var("t1"), F.Var("t2"), F.Const(r.randint(1, 60))], 2))
                seq = [] if omp else [f"{ind}        !$acc loop seq"]
                lines += [f"{ind}do l = 0, p", f"{ind}  do k = 0, n", f"{ind}    do j = 0, m", *seq,
                          f"{ind}      do i = 1, nv", *_stmt(f"{ind}        ", f"alpha(i) = {e1.f()}"),
                          f"{ind}      end do", *_stmt(f"{ind}      ", f"t1 = {e2.f()}"),
                          f"{ind}      call {rname}(t1, j, k, t2)", *seq,
                          f"{ind}      do i = 1, nv", *_stmt(f"{ind}        ", f"{dst}%vf(i)%sf(j, k, l) = {e3.f()}"),
                          f"{ind}      end do"]
                inner = f"{ind}      "
                ends = [f"{ind}    end do", f"{ind}  end do", f"{ind}end do"]
                for (j, k, l) in env_points:
                    env = {"j": j, "k": k, "l": l, "m": self.m, "n": self.n, "p": self.p, "nv": self.nv}
                    alpha = {}
                    for i in range(1, self.nv + 1):
                        alpha[i] = e1.ev(dict(env, i=i), arrs)
                    env["alpha"] = alpha
                    t1 = e2.ev(env, arrs)
                    t2 = rbody.ev({"a": t1, "b": j, "c": k}, arrs)
                    for i in range(1, self.nv + 1):
                        arrs[(dst, i)][(j, k, l)] = e3.ev(dict(env, i=i, t1=t1, t2=t2), arrs)
                    if atomic:
                        tot += t2 & 15
            if atomic:
                self.features.add("mfc:atomic")
                lines += [f"{inner}!$omp atomic update" if omp else f"{inner}!$acc atomic update",
                          f"{inner}tot = tot + iand(t2, 15)"]
            lines += ends
            lines.append(f"{ind}!$omp end target teams distribute parallel do" if omp else f"{ind}!$acc end parallel loop")
            body += [f"  ! fuzz: kernel {kn + 1}", *lines]
            self.kernels.append(f"mfc: collapse({4 if c4 else 3}) {src}->{dst}" + (" atomic" if atomic else ""))
            src, dst = dst, src
        cs = 0
        for fld in ("qa", "qb"):
            for e in range(1, self.nv + 1):
                for (j, k, l) in env_points:
                    cs = (cs * 31 + arrs[(fld, e)][(j, k, l)]) % MOD
        cs = (cs * 31 + tot) % MOD
        return F.FuzzProgram(self.seed, self.source(routines, body, cs), cs, frozenset(self.features),
                             tuple(self.kernels), 0, GEN if omp else GEN_ACC)

    def source(self, routines, body, cs) -> str:
        omp = self.model == "omp"
        d = "!$omp" if omp else "!$acc"
        upd_to = (lambda x: f"  !$omp target update to({x})") if omp else (lambda x: f"  !$acc update device({x})")
        upd_from = (lambda x: f"  !$omp target update from({x})") if omp else (lambda x: f"  !$acc update host({x})")
        alloc = (lambda x: f"{d} target enter data map(always,alloc:{x})") if omp else \
            (lambda x: f"{d} enter data create({x})")
        delete = (lambda x: f"{d} target exit data map(delete:{x})") if omp else (lambda x: f"{d} exit data delete({x})")
        declare = (lambda x: f"  {d} declare target ({x})") if omp else (lambda x: f"  {d} declare create({x})")
        spec = "OpenMP 5.2" if omp else "OpenACC 3.4"
        out = [f"! Generated by compliance.fuzz ({spec}, free-form Fortran; patterns of MFC). Do not edit.",
               f"! generator: {GEN if omp else GEN_ACC}", f"! seed: {self.seed}", f"! expected checksum: {cs}",
               "! host-execution flags: none", "! base groups: none", "! base features: none"]
        out += [f"! kernel {i + 1}: {k}" for i, k in enumerate(self.kernels)]
        out += ["module m_mfc_fuzz", "  implicit none",
                f"  integer, parameter :: m = {self.m}, n = {self.n}, p = {self.p}, nv = {self.nv}",
                "  type scalar_field", "    integer, allocatable :: sf(:, :, :)", "  end type scalar_field",
                "  type vector_field", "    type(scalar_field), allocatable :: vf(:)", "  end type vector_field",
                "  type(vector_field) :: qa, qb", "  integer :: tot", declare("qa, qb"), declare("tot"), "contains"]
        for name, b in routines:
            out += [f"  subroutine {name}(a, b, c, r)", f"    {d} declare target" if omp else f"    {d} routine seq",
                    "    integer, intent(in) :: a, b, c", "    integer, intent(out) :: r", *_stmt("    ", f"r = {b.f()}"),
                    f"  end subroutine {name}"]
        out += ["end module m_mfc_fuzz", "", "program fuzz_prog", "  use m_mfc_fuzz", "  implicit none",
                "  integer :: i, j, k, l, t1, t2", "  integer :: alpha(nv)", "  integer(8) :: cs", "  ! fuzz: setup"]
        for fld in ("qa", "qb"):
            out += [f"  allocate({fld}%vf(1:nv))", f"  {alloc(fld + '%vf')}"]
        out += ["  do i = 1, nv"]
        for fld in ("qa", "qb"):
            out += [f"    allocate({fld}%vf(i)%sf(0:m, 0:n, 0:p))", f"    {alloc(fld + '%vf(i)%sf')}"]
        out += ["    do l = 0, p", "      do k = 0, n", "        do j = 0, m",
                "          qa%vf(i)%sf(j, k, l) = mod(7 * j + 13 * k + 29 * l + 101 * i + 5, 1009)",
                "          qb%vf(i)%sf(j, k, l) = 0", "        end do", "      end do", "    end do",
                f"  {upd_to('qa%vf(i)%sf, qb%vf(i)%sf').strip()}", "  end do", "  tot = 0", upd_to("tot")]
        out += body
        out += ["  ! fuzz: checksum", "  do i = 1, nv", f"  {upd_from('qa%vf(i)%sf, qb%vf(i)%sf').strip()}", "  end do",
                upd_from("tot"), "  cs = 0"]
        for fld in ("qa", "qb"):
            out += ["  do i = 1, nv", "    do l = 0, p", "      do k = 0, n", "        do j = 0, m",
                    f"          cs = modulo(cs * 31_8 + int({fld}%vf(i)%sf(j, k, l), 8), 2147483629_8)",
                    "        end do", "      end do", "    end do", "  end do"]
        out += ["  cs = modulo(cs * 31_8 + int(tot, 8), 2147483629_8)", "  do i = 1, nv",
                f"    {delete('qa%vf(i)%sf')}", f"    {delete('qb%vf(i)%sf')}", "  end do",
                f"  {delete('qa%vf')}", f"  {delete('qb%vf')}",
                "  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', 0", "end program fuzz_prog"]
        return "\n".join(out) + "\n"


def generate(seed: int, gen_version: str = GEN) -> F.FuzzProgram:
    return MfcGen(seed, "acc" if gen_version == GEN_ACC else "omp").build()
