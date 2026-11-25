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
VERSIONS = (GEN, GEN_ACC, "fuzz-mfc2", "fuzz-mfcacc2", "fuzz-app1", "fuzz-appacc1")
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




# --- fuzz-mfc2 / fuzz-mfcacc2: swarm over MFC's patterns -------------------------------------------
# Each program switches on its own subset of the patterns (swarm testing), so a compiler bug one
# pattern triggers leaves the programs without it free to reach other bugs; the features name the
# choices (offload.engine.leads splits failure groups by them).
GEN2 = "fuzz-mfc2"
GEN2_ACC = "fuzz-mfcacc2"
OMP_CONSTRUCT = {"tdpd": "target teams distribute parallel do", "ttl": "target teams loop",
                 "tdpds": "target teams distribute parallel do simd"}
SWARM = {
    "shape": ("nested", "flat", "plain"),            # vector_field%vf(e)%sf, scalar_field(e)%sf, a(j,k,l,e)
    "residency": ("declare", "enter", "map"),        # declare target/create + enter data; enter data; data clauses
    "clauses": ("mfc", "one", "none"),               # MFC's clause list, one defaultmap / default, neither
    "routine": ("sub", "func", "none"),
}


@dataclass(frozen=True)
class SRef(F.Ex):
    """A field element in one of the swarm's shapes."""
    shape: str
    field: str
    eqn: F.Ex
    idx: tuple

    def f(self):
        j = ", ".join(x.f() for x in self.idx)
        e = self.eqn.f()
        return {"nested": f"{self.field}%vf({e})%sf({j})", "flat": f"{self.field}({e})%sf({j})",
                "plain": f"{self.field}({j}, {e})"}[self.shape]

    def ev(self, env, arrs):
        return arrs[(self.field, self.eqn.ev(env, arrs))][tuple(x.ev(env, arrs) for x in self.idx)]


class MfcSwarm(MfcGen):
    def __init__(self, seed: int, model: str = "omp"):
        super().__init__(seed, model)
        self.r = random.Random(f"mfc2-{model}-{seed}")
        r = self.r
        self.m, self.n, self.p = (r.randint(2, 5) for _ in range(3))
        self.nv = r.randint(2, 4)
        self.cfg = {k: r.choice(v) for k, v in SWARM.items()}
        if self.cfg["residency"] == "map" and self.cfg["shape"] != "plain":
            # a kernel's data clause on a structure with allocatable components maps them deeply only
            # under rules the swarm does not model: map residency uses plain arrays
            self.cfg["shape"] = "plain"
        if self.cfg["residency"] == "map":
            self.cfg["clauses"] = "none"           # present data clauses need data already present
        self.atomic_p = r.choice((0.0, 0.4, 0.8))
        self.seq_p = r.choice((0.0, 0.5, 1.0))
        self.nb_p = r.choice((0.0, 0.3))
        self.c4_p = r.choice((0.0, 0.35, 0.7))
        self.c2_p = r.choice((0.0, 0.3))
        self.red_p = r.choice((0.0, 0.3))
        self.mid_update = r.random() < 0.4
        self.features = {f"model:{model}"} | {f"mfc2:{k}={v}" for k, v in self.cfg.items()}
        self.construct = "tdpd" if model == "omp" else "parallel"     # fuzz-app1 draws these
        self.asyn = False

    def index(self, v: str, top: str) -> F.Ex:
        x = self.r.random()
        if x < self.nb_p / 2:
            self.features.add("mfc:neighbour")
            return F.Intr("min", (F.Bin("+", F.Var(v), F.Const(1)), F.Var(top)))
        if x < self.nb_p:
            self.features.add("mfc:neighbour")
            return F.Intr("max", (F.Bin("-", F.Var(v), F.Const(1)), F.Const(0)))
        return F.Var(v)

    def ref(self, fld: str, eqn: F.Ex, idx: tuple) -> SRef:
        return SRef(self.cfg["shape"], fld, eqn, idx)

    def text(self, fld: str, e: str, idx: str = "j, k, l") -> str:
        return self.ref(fld, F.Var(e), tuple(F.Var(x.strip()) for x in idx.split(","))).f()

    def kernel_head(self, ind: str, collapse: int, priv: list, src: str, dst: str, atomic: bool, red: str | None) -> list:
        omp, c = self.model == "omp", self.cfg
        cl = []
        if omp:
            if c["clauses"] == "mfc":
                cl += ["defaultmap(firstprivate:scalar)", f"collapse({collapse})", "defaultmap(tofrom:aggregate)",
                       "defaultmap(present:allocatable)", "defaultmap(present:pointer)"]
            elif c["clauses"] == "one":
                cl += [f"collapse({collapse})", "defaultmap(present:allocatable)"]
            else:
                cl += [f"collapse({collapse})"]
            if c["residency"] == "map":
                cl += [f"map(to: {src})", f"map(tofrom: {dst})"]
            if atomic and c["residency"] != "declare":
                cl += ["map(tofrom: tot)"]
            if red:
                cl += [f"reduction({red}: rsum)"]
            if self.asyn:
                cl += ["nowait", "depend(inout: dep)"]
            cl += [f"private({', '.join(priv)})"]
            return _directive(ind, OMP_CONSTRUCT[self.construct], cl, True)
        cl += [f"collapse({collapse})", "gang", "vector"]
        if c["clauses"] == "mfc":
            cl += ["default(present)"]
        elif c["clauses"] == "one":
            cl += [f"present({src}, {dst})"]
        if c["residency"] == "map":
            cl += [f"copyin({src})", f"copy({dst})"]
        if atomic and c["residency"] != "declare":
            cl += ["copy(tot)"]                    # a scalar is firstprivate without a visible data clause
        if red:
            cl += [f"reduction({red}: rsum)"]
        if self.asyn:
            cl += ["async(1)"]
        cl += [f"private({', '.join(priv)})"]
        return _directive(ind, f"{self.construct} loop", cl, False)

    def build(self) -> F.FuzzProgram:
        r, omp, c = self.r, self.model == "omp", self.cfg
        arrs = {}
        pts = [(j, k, l) for l in range(self.p + 1) for k in range(self.n + 1) for j in range(self.m + 1)]
        for fld in ("qa", "qb"):
            for e in range(1, self.nv + 1):
                arrs[(fld, e)] = {(j, k, l): (7 * j + 13 * k + 29 * l + 101 * e + 5) % 1009 if fld == "qa" else 0
                                  for (j, k, l) in pts}
        routines = []
        if c["routine"] != "none":
            self.features.add("mfc:routine")
            for i in range(r.randint(1, 2)):
                routines.append((f"s_mix{i + 1}", _band(self.expr([F.Var("a"), F.Var("b"), F.Var("c"),
                                                                    F.Const(r.randint(1, 50))], 2))))
        tot, rsums, body = 0, [], []
        src, dst = "qa", "qb"
        for kn in range(r.randint(2, 4)):
            ind = "  "
            c4, c2 = r.random() < self.c4_p, False
            if not c4:
                c2 = r.random() < self.c2_p
            seq = not c4 and r.random() < self.seq_p
            atomic = r.random() < self.atomic_p and self.construct != "ttl"   # 5.2 §11.7: order(concurrent) nesting
            red = r.choice(("+", "max", "min")) if r.random() < self.red_p else None
            rt = r.choice(routines) if routines else None
            priv = ["i", "j", "k", "l", "t1", "t2"] + (["alpha"] if seq else [])
            jj, kk, ll = self.index("j", "m"), self.index("k", "n"), self.index("l", "p")
            call = (lambda out, a: [f"call {rt[0]}({a}, j, k, {out})"] if c["routine"] == "sub" else
                    [f"{out} = {rt[0]}({a}, j, k)"]) if rt else (lambda out, a: [f"{out} = iand({a} + j + k, 1023)"])

            def t2_of(t1, j, k):
                return rt[1].ev({"a": t1, "b": j, "c": k}, arrs) if rt else (t1 + j + k) & 1023
            collapse = 4 if c4 else (2 if c2 else 3)
            lines = self.kernel_head(ind, collapse, priv, src, dst, atomic, red)
            self.features.add(f"mfc:collapse{collapse}")
            loops = ([("i", "1", "nv")] if c4 else []) + [("l", "0", "p"), ("k", "0", "n"), ("j", "0", "m")]
            for d, (v, lo, hi) in enumerate(loops):
                lines.append(f"{ind}{'  ' * d}do {v} = {lo}, {hi}")
            inner = f"{ind}{'  ' * len(loops)}"
            if c4:
                e1 = _band(self.expr([self.ref(src, F.Var("i"), (jj, kk, ll)), F.Var("i"), F.Var("j"),
                                      F.Const(r.randint(1, 60))], 2))
                e2 = _band(self.expr([F.Var("t1"), F.Var("t2"), F.Var("k"), F.Const(r.randint(1, 60))], 2))
                lines += _stmt(inner, f"t1 = {e1.f()}") + [inner + x for x in call("t2", "t1")] + \
                    _stmt(inner, f"{self.text(dst, 'i')} = {e2.f()}")
                for i in range(1, self.nv + 1):
                    for (j, k, l) in pts:
                        env = {"i": i, "j": j, "k": k, "l": l, "m": self.m, "n": self.n, "p": self.p}
                        t1 = e1.ev(env, arrs)
                        t2 = t2_of(t1, j, k)
                        arrs[(dst, i)][(j, k, l)] = e2.ev(dict(env, t1=t1, t2=t2), arrs)
                        tot += (t2 & 15) if atomic else 0
                        rsums.append((red, t2)) if red else None
            else:
                e1 = _band(self.expr([self.ref(src, F.Var("i"), (jj, kk, ll)), F.Var("i"), F.Var("j"), F.Var("l"),
                                      F.Const(r.randint(1, 60))], 2))
                if seq:
                    self.features.update({"mfc:seq-equations", "mfc:private-array"})
                    e2 = _band(self.expr([PRef("alpha", F.Const(1)), PRef("alpha", F.Var("nv")), F.Var("k"),
                                          F.Const(r.randint(1, 60))], 2))
                    e3 = _band(self.expr([PRef("alpha", F.Var("i")), F.Var("t1"), F.Var("t2"),
                                          F.Const(r.randint(1, 60))], 2))
                    sq = [] if omp else [f"{inner}!$acc loop seq"]
                    lines += sq + [f"{inner}do i = 1, nv"] + _stmt(inner + "  ", f"alpha(i) = {e1.f()}") + \
                        [f"{inner}end do"] + _stmt(inner, f"t1 = {e2.f()}") + [inner + x for x in call("t2", "t1")] + \
                        sq + [f"{inner}do i = 1, nv"] + _stmt(inner + "  ", f"{self.text(dst, 'i')} = {e3.f()}") + \
                        [f"{inner}end do"]
                else:
                    e3 = _band(self.expr([F.Var("t1"), F.Var("t2"), F.Var("l"), F.Const(r.randint(1, 60))], 2))
                    lines += [f"{inner}do i = 1, nv"] + _stmt(inner + "  ", f"t1 = {e1.f()}") + \
                        [inner + "  " + x for x in call("t2", "t1")] + \
                        _stmt(inner + "  ", f"{self.text(dst, 'i')} = {e3.f()}") + [f"{inner}end do"]
                for (j, k, l) in pts:
                    env = {"j": j, "k": k, "l": l, "m": self.m, "n": self.n, "p": self.p, "nv": self.nv}
                    if seq:
                        alpha = {i: e1.ev(dict(env, i=i), arrs) for i in range(1, self.nv + 1)}
                        env["alpha"] = alpha
                        t1 = e2.ev(env, arrs)
                        t2 = t2_of(t1, j, k)
                        for i in range(1, self.nv + 1):
                            arrs[(dst, i)][(j, k, l)] = e3.ev(dict(env, i=i, t1=t1, t2=t2), arrs)
                        tot += (t2 & 15) if atomic else 0
                        rsums.append((red, t2)) if red else None
                    else:
                        for i in range(1, self.nv + 1):
                            t1 = e1.ev(dict(env, i=i), arrs)
                            t2 = t2_of(t1, j, k)
                            arrs[(dst, i)][(j, k, l)] = e3.ev(dict(env, i=i, t1=t1, t2=t2), arrs)
                        # the atomic and the reduction follow the i loop: once a point, with its last t2
                        tot += (t2 & 15) if atomic else 0
                        rsums.append((red, t2)) if red else None
                if not seq:
                    inner = inner + "  "
            if atomic:
                self.features.add("mfc:atomic")
                lines += [f"{inner}!$omp atomic update" if omp else f"{inner}!$acc atomic update",
                          f"{inner}tot = tot + iand(t2, 15)"]
            if red:
                self.features.add(f"mfc:reduction:{red}")
                lines += [f"{inner}rsum = {'rsum + iand(t2, 15)' if red == '+' else f'{red}(rsum, t2)'}"]
            if not c4 and not seq:
                inner = inner[:-2]
            for d in range(len(loops) - 1, -1, -1):
                lines.append(f"{ind}{'  ' * d}end do")
            lines.append(f"{ind}!$omp end {OMP_CONSTRUCT[self.construct]}" if omp else f"{ind}!$acc end {self.construct} loop")
            pre = [f"  rsum = {0 if red == '+' else (-1 if red == 'max' else 100000)}"] if red else []
            post = []
            if red:
                rv = 0 if red == "+" else (-1 if red == "max" else 100000)
                for op, v in rsums:
                    rv = rv + (v & 15) if op == "+" else (max(rv, v) if op == "max" else min(rv, v))
                rsums.clear()
                post = self.sync() + [f"  tot2 = tot2 + mod(rsum, 1000)"]
                self.tot2 = getattr(self, "tot2", 0) + (rv % 1000 if rv >= 0 else -((-rv) % 1000))
            mid = []
            if self.mid_update and c["residency"] != "map":
                self.features.add("mfc:mid-update")
                mid = (self.sync() if not red else []) + self.motion("from", "  ") + self.motion("to", "  ")
            body += [f"  ! fuzz: kernel {kn + 1}", *pre, *lines, *post, *mid]
            self.kernels.append(f"mfc2: collapse({collapse}) {src}->{dst}" + (" atomic" if atomic else "")
                                + (f" reduction({red})" if red else ""))
            src, dst = dst, src
        cs = 0
        for fld in ("qa", "qb"):
            for e in range(1, self.nv + 1):
                for pt in pts:
                    cs = (cs * 31 + arrs[(fld, e)][pt]) % MOD
        cs = (cs * 31 + tot) % MOD
        cs = (cs * 31 + getattr(self, "tot2", 0)) % MOD
        return F.FuzzProgram(self.seed, self.source(routines, body, cs), cs, frozenset(self.features),
                             tuple(self.kernels), 0, self.version)

    @property
    def version(self) -> str:
        return GEN2 if self.model == "omp" else GEN2_ACC

    def sync(self) -> list:
        """Wait for the asynchronous kernels before the host reads what they wrote."""
        if not self.asyn:
            return []
        return ["  !$omp taskwait"] if self.model == "omp" else ["  !$acc wait(1)"]

    def motion(self, way: str, ind: str) -> list:
        """update of both fields to (way "to") or from the device, in the shape's units."""
        omp, c = self.model == "omp", self.cfg
        d = "!$omp target update" if omp else "!$acc update"
        word = ("to" if way == "to" else "from") if omp else ("device" if way == "to" else "host")
        if c["shape"] == "plain":
            return [f"{ind}{d} {word}(qa, qb)"]
        unit = "qa%vf(i)%sf, qb%vf(i)%sf" if c["shape"] == "nested" else "qa(i)%sf, qb(i)%sf"
        return [f"{ind}do i = 1, nv", f"{ind}  {d} {word}({unit})", f"{ind}end do"]

    def source(self, routines, body, cs) -> str:
        omp, c = self.model == "omp", self.cfg
        d = "!$omp" if omp else "!$acc"
        spec = "OpenMP 5.2" if omp else "OpenACC 3.4"
        enter = (lambda x: f"{d} target enter data map(always,alloc:{x})") if omp else (lambda x: f"{d} enter data create({x})")
        leave = (lambda x: f"{d} target exit data map(delete:{x})") if omp else (lambda x: f"{d} exit data delete({x})")
        out = [f"! Generated by compliance.fuzz ({spec}, free-form Fortran; patterns of MFC, swarm). Do not edit.",
               f"! generator: {self.version}", f"! seed: {self.seed}", f"! expected checksum: {cs}",
               "! host-execution flags: none", "! base groups: none", "! base features: none",
               "! swarm: " + ", ".join(f"{k}={v}" for k, v in c.items())]
        out += [f"! kernel {i + 1}: {k}" for i, k in enumerate(self.kernels)]
        out += ["module m_mfc_fuzz", "  implicit none",
                f"  integer, parameter :: m = {self.m}, n = {self.n}, p = {self.p}, nv = {self.nv}"]
        if c["shape"] in ("nested", "flat"):
            out += ["  type scalar_field", "    integer, allocatable :: sf(:, :, :)", "  end type scalar_field"]
        if c["shape"] == "nested":
            out += ["  type vector_field", "    type(scalar_field), allocatable :: vf(:)", "  end type vector_field",
                    "  type(vector_field) :: qa, qb"]
        elif c["shape"] == "flat":
            out += ["  type(scalar_field), allocatable :: qa(:), qb(:)"]
        else:
            out += ["  integer, allocatable :: qa(:, :, :, :), qb(:, :, :, :)"]
        out += ["  integer :: tot"]
        if c["residency"] == "declare":
            out += [f"  {d} declare target (qa, qb)" if omp else f"  {d} declare create(qa, qb)",
                    f"  {d} declare target (tot)" if omp else f"  {d} declare create(tot)"]
        out += ["contains"] if routines else []
        for name, b in routines:
            mark = f"    {d} declare target" if omp else f"    {d} routine seq"
            if c["routine"] == "sub":
                out += [f"  subroutine {name}(a, b, c, r)", mark, "    integer, intent(in) :: a, b, c",
                        "    integer, intent(out) :: r", *_stmt("    ", f"r = {b.f()}"), f"  end subroutine {name}"]
            else:
                out += [f"  integer function {name}(a, b, c)", mark, "    integer, intent(in) :: a, b, c",
                        *_stmt("    ", f"{name} = {b.f()}"), f"  end function {name}"]
        out += ["end module m_mfc_fuzz", "", "program fuzz_prog", "  use m_mfc_fuzz", "  implicit none",
                "  integer :: i, j, k, l, t1, t2, rsum, tot2", "  integer :: alpha(nv)", "  integer(8) :: cs",
                *(["  integer :: dep"] if self.asyn and omp else []),
                "  ! fuzz: setup", "  tot2 = 0"]
        res = c["residency"]
        if c["shape"] == "plain":
            out += ["  allocate(qa(0:m, 0:n, 0:p, 1:nv), qb(0:m, 0:n, 0:p, 1:nv))"]
            if res != "map":
                out += [f"  {enter('qa')}", f"  {enter('qb')}"]
        else:
            top = (lambda f: f"{f}%vf") if c["shape"] == "nested" else (lambda f: f)
            for fld in ("qa", "qb"):
                out += [f"  allocate({top(fld)}(1:nv))", f"  {enter(top(fld))}"]
            out += ["  do i = 1, nv"]
            for fld in ("qa", "qb"):
                out += [f"    allocate({top(fld)}(i)%sf(0:m, 0:n, 0:p))", f"    {enter(top(fld) + '(i)%sf')}"]
            out += ["  end do"]
        out += ["  do i = 1, nv", "    do l = 0, p", "      do k = 0, n", "        do j = 0, m",
                f"          {self.text('qa', 'i')} = mod(7 * j + 13 * k + 29 * l + 101 * i + 5, 1009)",
                f"          {self.text('qb', 'i')} = 0", "        end do", "      end do", "    end do", "  end do",
                "  tot = 0"]
        if res != "map":
            out += self.motion("to", "  ")
            if res == "declare":
                out += [f"  {d} target update to(tot)" if omp else f"  {d} update device(tot)"]
        out += body
        out += ["  ! fuzz: checksum"] + self.sync()
        if res != "map":
            out += self.motion("from", "  ")
            if res == "declare":
                out += [f"  {d} target update from(tot)" if omp else f"  {d} update host(tot)"]
        out += ["  cs = 0"]
        for fld in ("qa", "qb"):
            out += ["  do i = 1, nv", "    do l = 0, p", "      do k = 0, n", "        do j = 0, m",
                    f"          cs = modulo(cs * 31_8 + int({self.text(fld, 'i')}, 8), 2147483629_8)",
                    "        end do", "      end do", "    end do", "  end do"]
        out += ["  cs = modulo(cs * 31_8 + int(tot, 8), 2147483629_8)",
                "  cs = modulo(cs * 31_8 + int(tot2, 8), 2147483629_8)"]
        if res != "map":
            if c["shape"] == "plain":
                out += [f"  {leave('qa')}", f"  {leave('qb')}"]
            else:
                top = "qa%vf" if c["shape"] == "nested" else "qa"
                topb = "qb%vf" if c["shape"] == "nested" else "qb"
                out += ["  do i = 1, nv", f"    {leave(top + '(i)%sf')}", f"    {leave(topb + '(i)%sf')}", "  end do",
                        f"  {leave(top)}", f"  {leave(topb)}"]
        out += ["  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', 0", "end program fuzz_prog"]
        return "\n".join(out) + "\n"


# --- fuzz-app1 / fuzz-appacc1: the swarm with each code base's weights ------------------------------
# Each program picks a code base of the usage profile (catalog/fuzz_profile.json, measured from the
# application corpus: offload.engine.fuzz_profile) and draws the swarm's choices with that code's
# weights: its collapse depths, type nesting, module device variables and map lists, clause forms,
# construct forms (teams loop, simd, kernels), asynchronous kernels, atomics, reductions and device
# routines. Every choice keeps a floor, so no pattern is ruled out.
GEN_APP = "fuzz-app1"
GEN_APP_ACC = "fuzz-appacc1"
FLOOR = 0.15


def _profiles() -> dict:
    import json
    from pathlib import Path
    p = Path(__file__).resolve().parents[2] / "catalog" / "fuzz_profile.json"
    codes = json.loads(p.read_text())["codes"]
    return {k: v for k, v in sorted(codes.items()) if (v.get("regions") or 0) > 0}


def weights(prof: dict, model: str) -> dict:
    """The swarm's choice weights and rates for one code base's profile."""
    n = max(1, prof.get("regions") or 1)
    feats = prof.get("region_features") or {}
    frac = lambda f: (feats.get(f) or 0) / n           # noqa: E731
    rc = prof.get("region_collapse") or {}
    tn = (prof.get("type_nesting_depth") or {}).get("max") or 0
    mdv = (prof.get("module_device_vars") or {}).get("max") or 0
    maps = frac("clause:map") + (0.5 if "map" in (prof.get("list_length") or {}) else 0)
    w = {"shape": {"nested": 2 if tn >= 2 else FLOOR, "flat": 1.5 if tn >= 1 else FLOOR, "plain": 1 + (2 if tn == 0 else 0)},
         "residency": {"declare": 2 if mdv > 0 else FLOOR, "map": 1 + 2 * min(1, maps), "enter": 1},
         "clauses": {"mfc": (2 if frac("clause:defaultmap" if model == "omp" else "clause:default:present") > 0 else FLOOR),
                     "one": 1, "none": 1},
         "routine": {"sub": 1 if (prof.get("device_routines") or 0) else FLOOR,
                     "func": 1 if (prof.get("device_routines") or 0) else FLOOR, "none": 1}}
    if model == "omp":
        w["construct"] = {"tdpd": frac("dir:distribute") + FLOOR, "ttl": frac("dir:loop") + FLOOR,
                          "tdpds": frac("dir:simd") + FLOOR}
    else:
        w["construct"] = {"parallel": frac("dir:parallel") + FLOOR, "kernels": frac("dir:kernels") + FLOOR}
    rates = {"c4_p": 0.5 if (rc.get("max") or 0) >= 4 else 0.1,
             "c2_p": 0.5 if (rc.get("p50") or 0) <= 2 else 0.15,
             "async_p": min(0.7, frac("clause:nowait") + frac("clause:async") + 0.1),
             "atomic_p": min(0.8, 3 * frac("dir:atomic") + 0.1),
             "red_p": min(0.6, 1.5 * frac("clause:reduction") + 0.1),
             "seq_p": 0.6 if frac("base:loop_nest3") > 0.3 else 0.3, "nb_p": 0.3}
    return {"choices": w, "rates": rates}


def _pick(r: random.Random, w: dict) -> str:
    keys = sorted(w)
    return r.choices(keys, weights=[w[k] for k in keys])[0]


class AppSwarm(MfcSwarm):
    def __init__(self, seed: int, model: str = "omp"):
        MfcGen.__init__(self, seed, model)
        self.r = r = random.Random(f"app1-{model}-{seed}")
        self.m, self.n, self.p = (r.randint(2, 5) for _ in range(3))
        self.nv = r.randint(2, 4)
        profs = _profiles()
        self.code = r.choice(sorted(profs))
        wt = weights(profs[self.code], model)
        ch, rt = wt["choices"], wt["rates"]
        self.cfg = {k: _pick(r, ch[k]) for k in ("shape", "residency", "clauses", "routine")}
        if self.cfg["residency"] == "map":
            self.cfg["shape"], self.cfg["clauses"] = "plain", "none"
        self.construct = _pick(r, ch["construct"])
        self.asyn = r.random() < rt["async_p"]
        self.atomic_p, self.seq_p, self.nb_p = rt["atomic_p"], rt["seq_p"], rt["nb_p"]
        self.c4_p, self.c2_p, self.red_p = rt["c4_p"], rt["c2_p"], rt["red_p"]
        self.mid_update = r.random() < 0.4
        self.features = ({f"model:{model}", f"app:{self.code}", f"mfc2:construct={self.construct}"}
                         | {f"mfc2:{k}={v}" for k, v in self.cfg.items()} | ({"mfc:async"} if self.asyn else set()))

    @property
    def version(self) -> str:
        return GEN_APP if self.model == "omp" else GEN_APP_ACC


def generate(seed: int, gen_version: str = GEN) -> F.FuzzProgram:
    if gen_version in ("fuzz-app1", "fuzz-appacc1"):
        return AppSwarm(seed, "acc" if gen_version == "fuzz-appacc1" else "omp").build()
    if gen_version in (GEN2, GEN2_ACC):
        return MfcSwarm(seed, "acc" if gen_version == GEN2_ACC else "omp").build()
    return MfcGen(seed, "acc" if gen_version == GEN_ACC else "omp").build()
