"""C fuzz programs in the patterns of the profiled code bases (fuzz-capp1: OpenMP, fuzz-cappacc1:
OpenACC): the swarm of offload.engine.fuzz_mfc.AppSwarm (each program draws a code base of
catalog/fuzz_profile.json and that code's weights) in C's own forms of its data: structures whose
pointer members are made device-resident one level at a time and attached (the structure, its
array of field structures, each field's array), an array of structures reached through a pointer,
one heap array through a pointer, and fixed-size global arrays; declare target (declare create)
globals, enter data, or data clauses on the kernel. A C pointer is a scalar to OpenACC (3.4
§2.6.2: firstprivate in a parallel construct), so a pointer shape's kernel always names its
sections in a present or data clause. Updates between kernels move the leaf arrays only (an update
of a level that holds pointers would overwrite the attached device pointers). The expected
checksum is the program's sequential value, computed here from the same expression trees; the
elided C run (offload.engine.fuzz.check_defined_c) must print it."""
from __future__ import annotations

import random
from dataclasses import dataclass

from offload.engine import fuzz as F
from offload.engine import fuzz_mfc as M

GEN = "fuzz-capp1"
GEN_ACC = "fuzz-cappacc1"
VERSIONS = (GEN, GEN_ACC)
SHAPES = ("nested", "flat", "plain", "static")
UPPER = {"m": "M", "n": "N", "p": "P", "nv": "NV"}
CONSTRUCT_OMP = {"tdpd": "target teams distribute parallel for", "ttl": "target teams loop",
                 "tdpds": "target teams distribute parallel for simd"}


def ref_text(shape: str, field: str, e: str, j: str, k: str, l: str) -> str:
    ix = f"IX({j}, {k}, {l})"
    return {"nested": f"{field}.vf[{e}].sf[{ix}]", "flat": f"{field}[{e}].sf[{ix}]",
            "plain": f"{field}[({e}) * SZ + {ix}]", "static": f"{field}[{e}][{l}][{k}][{j}]"}[shape]


@dataclass(frozen=True)
class CRef(F.Ex):
    """A field element in one of the C shapes."""
    shape: str
    field: str
    eqn: F.Ex
    idx: tuple

    def f(self):
        return c(self)

    def ev(self, env, arrs):
        return arrs[(self.field, self.eqn.ev(env, arrs))][tuple(x.ev(env, arrs) for x in self.idx)]


def c(e) -> str:
    """The C text of an expression tree (offload.engine.fuzz): C's / and % truncate like Fortran's
    division and mod, so the model's value is the program's."""
    if isinstance(e, F.Const):
        return str(e.v) if e.v >= 0 else f"({e.v})"
    if isinstance(e, F.Var):
        return UPPER.get(e.name, e.name)
    if isinstance(e, CRef):
        return ref_text(e.shape, e.field, c(e.eqn), *(c(x) for x in e.idx))
    if isinstance(e, M.PRef):
        return f"{e.name}[{c(e.i)}]"
    if isinstance(e, F.Bin):
        return f"({c(e.a)} {e.op} {c(e.b)})"
    if isinstance(e, F.Merge):
        op = "!=" if e.c.op == "/=" else e.c.op
        return f"({c(e.c.a)} {op} {c(e.c.b)} ? {c(e.a)} : {c(e.b)})"
    if isinstance(e, F.Intr):
        a = [c(x) for x in e.args]
        ops = {"iand": "&", "ior": "|", "ieor": "^", "mod": "%"}
        if e.name in ops:
            return f"({a[0]} {ops[e.name]} {a[1]})"
        if e.name in ("min", "max"):
            return f"I{e.name.upper()}({a[0]}, {a[1]})"
    raise ValueError(f"no C form for {e!r}")


class CSwarm(M.AppSwarm):
    def __init__(self, seed: int, model: str = "omp"):
        M.MfcGen.__init__(self, seed, model)
        self.r = r = random.Random(f"capp1-{model}-{seed}")
        self.m, self.n, self.p = (r.randint(2, 5) for _ in range(3))
        self.nv = r.randint(2, 4)
        profs = M._profiles()
        self.code = r.choice(sorted(profs))
        wt = M.weights(profs[self.code], model)
        ch, rt = wt["choices"], wt["rates"]
        shape = dict(ch["shape"], static=ch["shape"]["plain"])
        self.cfg = {"shape": M._pick(r, shape), **{k: M._pick(r, ch[k]) for k in ("residency", "clauses", "routine")}}
        if self.cfg["residency"] == "map" and self.cfg["shape"] in ("nested", "flat"):
            # one clause list cannot name every level of a structure: a structure keeps its shape and
            # is made resident by declare target or enter data
            self.cfg["residency"] = r.choice(("declare", "enter"))
        if self.cfg["residency"] == "map":
            self.cfg["clauses"] = "none"
        self.construct = M._pick(r, ch["construct"])
        self.asyn = r.random() < rt["async_p"]
        self.atomic_p, self.seq_p, self.nb_p = rt["atomic_p"], rt["seq_p"], rt["nb_p"]
        self.c4_p, self.c2_p, self.red_p = rt["c4_p"], rt["c2_p"], rt["red_p"]
        self.mid_update = r.random() < 0.4
        self.features = ({f"model:{model}", "lang:c", f"app:{self.code}", f"mfc2:construct={self.construct}"}
                         | {f"mfc2:{k}={v}" for k, v in self.cfg.items()} | ({"mfc:async"} if self.asyn else set()))

    @property
    def version(self) -> str:
        return GEN if self.model == "omp" else GEN_ACC

    # --- text ------------------------------------------------------------------------------
    def ref(self, fld: str, eqn: F.Ex, idx: tuple) -> CRef:
        return CRef(self.cfg["shape"], fld, eqn, idx)

    def at(self, fld: str, e: str = "i") -> str:
        return ref_text(self.cfg["shape"], fld, e, "j", "k", "l")

    def whole(self, fld: str) -> str:
        """The array section of a field's data in a pointer shape (plain), or the variable."""
        return f"{fld}[0:NV * SZ]" if self.cfg["shape"] == "plain" else fld

    def present_list(self) -> str:
        s = self.cfg["shape"]
        if s == "plain":
            return "qa[0:NV * SZ], qb[0:NV * SZ]"
        if s == "flat":
            return "qa[0:NV], qb[0:NV]"
        return "qa, qb"

    def kernel_head(self, collapse: int, priv: list, src: str, dst: str, atomic: bool, red: str | None) -> list:
        omp, cf = self.model == "omp", self.cfg
        cl = []
        if omp:
            if cf["clauses"] == "mfc":
                cl += ["defaultmap(firstprivate:scalar)", f"collapse({collapse})", "defaultmap(tofrom:aggregate)"]
            elif cf["clauses"] == "one":
                cl += [f"collapse({collapse})", "defaultmap(present:aggregate)"]
            else:
                cl += [f"collapse({collapse})"]
            if cf["residency"] == "map":
                cl += [f"map(to: {self.whole(src)})", f"map(tofrom: {self.whole(dst)})"]
            if atomic and cf["residency"] != "declare":
                cl += ["map(tofrom: tot)"]
            if red:
                cl += [f"reduction({red}: rsum)"]
            if self.asyn:
                cl += ["nowait", "depend(inout: dep)"]
            cl += [f"private({', '.join(priv)})"]
            return [f"#pragma omp {CONSTRUCT_OMP[self.construct]} " + " ".join(cl)]
        cl += [f"collapse({collapse})", "gang", "vector"]
        if cf["residency"] == "map":
            cl += [f"copyin({self.whole(src)})", f"copy({self.whole(dst)})"]
        else:
            if cf["clauses"] == "mfc":
                cl += ["default(present)"]
            # a pointer is a scalar (OpenACC 3.4 §2.6.2): its sections are named, whatever the clause form
            if cf["clauses"] == "one" or cf["shape"] in ("plain", "flat"):
                cl += [f"present({self.present_list()})"]
        if atomic and cf["residency"] != "declare":
            cl += ["copy(tot)"]
        if red:
            cl += [f"reduction({red}: rsum)"]
        if self.asyn:
            cl += ["async(1)"]
        cl += [f"private({', '.join(priv)})"]
        return [f"#pragma acc {self.construct} loop " + " ".join(cl)]

    def sync(self) -> list:
        """Wait for the asynchronous kernels before the host reads what they wrote."""
        if not self.asyn:
            return []
        return ["#pragma omp taskwait"] if self.model == "omp" else ["#pragma acc wait(1)"]

    def motion(self, way: str) -> list:
        """An update of both fields' leaf arrays to (way "to") or from the device."""
        omp, s = self.model == "omp", self.cfg["shape"]
        d = "#pragma omp target update" if omp else "#pragma acc update"
        word = ("to" if way == "to" else "from") if omp else ("device" if way == "to" else "self")
        if s in ("plain", "static"):
            return [f"{d} {word}({self.whole('qa')}, {self.whole('qb')})"]
        leaf = "qa.vf[i].sf[0:SZ], qb.vf[i].sf[0:SZ]" if s == "nested" else "qa[i].sf[0:SZ], qb[i].sf[0:SZ]"
        return ["  for (i = 0; i < NV; i++) {", f"{d} {word}({leaf})", "  }"]

    # --- the program -----------------------------------------------------------------------
    def build(self) -> F.FuzzProgram:
        r, omp, cf = self.r, self.model == "omp", self.cfg
        arrs = {}
        pts = [(j, k, l) for l in range(self.p + 1) for k in range(self.n + 1) for j in range(self.m + 1)]
        for fld in ("qa", "qb"):
            for e in range(self.nv):
                arrs[(fld, e)] = {(j, k, l): (7 * j + 13 * k + 29 * l + 101 * e + 5) % 1009 if fld == "qa" else 0
                                  for (j, k, l) in pts}
        routines = []
        if cf["routine"] != "none":
            self.features.add("mfc:routine")
            for i in range(r.randint(1, 2)):
                routines.append((f"s_mix{i + 1}", M._band(self.expr([F.Var("a"), F.Var("b"), F.Var("c"),
                                                                      F.Const(r.randint(1, 50))], 2))))
        tot, rsums, body = 0, [], []
        src, dst = "qa", "qb"
        for kn in range(r.randint(2, 4)):
            c4, c2 = r.random() < self.c4_p, False
            if not c4:
                c2 = r.random() < self.c2_p
            seq = not c4 and r.random() < self.seq_p
            atomic = r.random() < self.atomic_p and self.construct != "ttl"   # 5.2 §11.7: order(concurrent) nesting
            red = r.choice(("+", "max", "min")) if r.random() < self.red_p else None
            rt = r.choice(routines) if routines else None
            priv = ["i", "j", "k", "l", "t1", "t2"] + (["alpha"] if seq else [])
            jj, kk, ll = self.index("j", "m"), self.index("k", "n"), self.index("l", "p")
            call = (lambda out, a: [f"{rt[0]}({a}, j, k, &{out});"] if cf["routine"] == "sub" else
                    [f"{out} = {rt[0]}({a}, j, k);"]) if rt else (lambda out, a: [f"{out} = ({a} + j + k) & 1023;"])

            def t2_of(t1, j, k):
                return rt[1].ev({"a": t1, "b": j, "c": k}, arrs) if rt else (t1 + j + k) & 1023
            collapse = 4 if c4 else (2 if c2 else 3)
            lines = self.kernel_head(collapse, priv, src, dst, atomic, red)
            self.features.add(f"mfc:collapse{collapse}")
            loops = ([("i", "NV")] if c4 else []) + [("l", "P + 1"), ("k", "N + 1"), ("j", "M + 1")]
            for d, (v, top) in enumerate(loops):
                lines.append(f"  {'  ' * d}for ({v} = 0; {v} < {top}; {v}++)" + (" {" if d == len(loops) - 1 else ""))
            inner = "  " * (len(loops) + 1)
            closes = [f"{'  ' * len(loops)}}}"]
            if c4:
                e1 = M._band(self.expr([self.ref(src, F.Var("i"), (jj, kk, ll)), F.Var("i"), F.Var("j"),
                                        F.Const(r.randint(1, 60))], 2))
                e2 = M._band(self.expr([F.Var("t1"), F.Var("t2"), F.Var("k"), F.Const(r.randint(1, 60))], 2))
                lines += [f"{inner}t1 = {c(e1)};"] + [inner + x for x in call("t2", "t1")] + \
                    [f"{inner}{self.at(dst)} = {c(e2)};"]
                for i in range(self.nv):
                    for (j, k, l) in pts:
                        env = {"i": i, "j": j, "k": k, "l": l, "m": self.m, "n": self.n, "p": self.p}
                        t1 = e1.ev(env, arrs)
                        t2 = t2_of(t1, j, k)
                        arrs[(dst, i)][(j, k, l)] = e2.ev(dict(env, t1=t1, t2=t2), arrs)
                        tot += (t2 & 15) if atomic else 0
                        rsums.append((red, t2)) if red else None
            else:
                e1 = M._band(self.expr([self.ref(src, F.Var("i"), (jj, kk, ll)), F.Var("i"), F.Var("j"), F.Var("l"),
                                        F.Const(r.randint(1, 60))], 2))
                sq = [] if omp else [f"{inner}#pragma acc loop seq"]
                if seq:
                    self.features.update({"mfc:seq-equations", "mfc:private-array"})
                    last = F.Bin("-", F.Var("nv"), F.Const(1))
                    e2 = M._band(self.expr([M.PRef("alpha", F.Const(0)), M.PRef("alpha", last), F.Var("k"),
                                            F.Const(r.randint(1, 60))], 2))
                    e3 = M._band(self.expr([M.PRef("alpha", F.Var("i")), F.Var("t1"), F.Var("t2"),
                                            F.Const(r.randint(1, 60))], 2))
                    lines += sq + [f"{inner}for (i = 0; i < NV; i++)", f"{inner}  alpha[i] = {c(e1)};",
                                   f"{inner}t1 = {c(e2)};"] + [inner + x for x in call("t2", "t1")] + \
                        sq + [f"{inner}for (i = 0; i < NV; i++)", f"{inner}  {self.at(dst)} = {c(e3)};"]
                else:
                    e3 = M._band(self.expr([F.Var("t1"), F.Var("t2"), F.Var("l"), F.Const(r.randint(1, 60))], 2))
                    lines += [f"{inner}for (i = 0; i < NV; i++) {{", f"{inner}  t1 = {c(e1)};"] + \
                        [inner + "  " + x for x in call("t2", "t1")] + \
                        [f"{inner}  {self.at(dst)} = {c(e3)};", f"{inner}}}"]
                for (j, k, l) in pts:
                    env = {"j": j, "k": k, "l": l, "m": self.m, "n": self.n, "p": self.p, "nv": self.nv}
                    if seq:
                        env["alpha"] = {i: e1.ev(dict(env, i=i), arrs) for i in range(self.nv)}
                        t1 = e2.ev(env, arrs)
                        t2 = t2_of(t1, j, k)
                        for i in range(self.nv):
                            arrs[(dst, i)][(j, k, l)] = e3.ev(dict(env, i=i, t1=t1, t2=t2), arrs)
                    else:
                        for i in range(self.nv):
                            t1 = e1.ev(dict(env, i=i), arrs)
                            t2 = t2_of(t1, j, k)
                            arrs[(dst, i)][(j, k, l)] = e3.ev(dict(env, i=i, t1=t1, t2=t2), arrs)
                    # the atomic and the reduction follow the equation loop: once a point, with its last t2
                    tot += (t2 & 15) if atomic else 0
                    rsums.append((red, t2)) if red else None
            if atomic:
                self.features.add("mfc:atomic")
                lines += ["#pragma omp atomic update" if omp else "#pragma acc atomic update",
                          f"{inner}tot += (t2 & 15);"]
            if red:
                self.features.add(f"mfc:reduction:{red}")
                lines += [f"{inner}rsum = " + ("rsum + (t2 & 15);" if red == "+" else f"I{red.upper()}(rsum, t2);")]
            lines += closes
            pre = [f"  rsum = {0 if red == '+' else (-1 if red == 'max' else 100000)};"] if red else []
            post = []
            if red:
                rv = 0 if red == "+" else (-1 if red == "max" else 100000)
                for op, v in rsums:
                    rv = rv + (v & 15) if op == "+" else (max(rv, v) if op == "max" else min(rv, v))
                rsums.clear()
                post = self.sync() + ["  tot2 = tot2 + rsum % 1000;"]
                self.tot2 = getattr(self, "tot2", 0) + rv % 1000
            mid = []
            if self.mid_update and cf["residency"] != "map":
                self.features.add("mfc:mid-update")
                mid = (self.sync() if not red else []) + self.motion("from") + self.motion("to")
            body += [f"  // fuzz: kernel {kn + 1}", *pre, *lines, *post, *mid]
            self.kernels.append(f"capp1: collapse({collapse}) {src}->{dst}" + (" atomic" if atomic else "")
                                + (f" reduction({red})" if red else ""))
            src, dst = dst, src
        cs = 0
        for fld in ("qa", "qb"):
            for e in range(self.nv):
                for pt in pts:
                    cs = (cs * 31 + arrs[(fld, e)][pt]) % M.MOD
        cs = (cs * 31 + tot) % M.MOD
        cs = (cs * 31 + getattr(self, "tot2", 0)) % M.MOD
        return F.FuzzProgram(self.seed, self.source(routines, body, cs), cs, frozenset(self.features),
                             tuple(self.kernels), 0, self.version)

    def source(self, routines, body, cs) -> str:
        omp, cf = self.model == "omp", self.cfg
        s, res = cf["shape"], cf["residency"]
        spec = "OpenMP 5.2" if omp else "OpenACC 3.4"
        out = [f"// Generated by compliance.fuzz ({spec}, C11; patterns of the profiled code bases, swarm). Do not edit.",
               f"// generator: {self.version}", f"// seed: {self.seed}", f"// expected checksum: {cs}",
               "// host-execution flags: none", "// base groups: none", "// base features: none",
               "// swarm: " + ", ".join(f"{k}={v}" for k, v in cf.items()) + f", code={self.code}"]
        out += [f"// kernel {i + 1}: {k}" for i, k in enumerate(self.kernels)]
        out += ["#include <stdio.h>", "#include <stdlib.h>", "",
                f"#define M {self.m}", f"#define N {self.n}", f"#define P {self.p}", f"#define NV {self.nv}",
                "#define SZ ((M + 1) * (N + 1) * (P + 1))",
                "#define IX(j, k, l) ((((l) * (N + 1)) + (k)) * (M + 1) + (j))",
                "#define IMIN(a, b) ((a) < (b) ? (a) : (b))", "#define IMAX(a, b) ((a) > (b) ? (a) : (b))", ""]
        if s in ("nested", "flat"):
            out += ["struct scalar_field {", "  int *sf;", "};"]
        if s == "nested":
            out += ["struct vector_field {", "  struct scalar_field *vf;", "};", "struct vector_field qa, qb;"]
        elif s == "flat":
            out += ["struct scalar_field *qa, *qb;"]
        elif s == "plain":
            out += ["int *qa, *qb;"]
        else:
            out += ["int qa[NV][P + 1][N + 1][M + 1], qb[NV][P + 1][N + 1][M + 1];"]
        out += ["int tot;"]
        if res == "declare":
            out += ["#pragma omp declare target(qa, qb, tot)" if omp else "#pragma acc declare create(qa, qb, tot)"]
        out += [""]
        if routines and omp:
            out += ["#pragma omp declare target"]
        for name, b in routines:
            out += [] if omp else ["#pragma acc routine seq"]
            if cf["routine"] == "sub":
                out += [f"static void {name}(int a, int b, int c, int *r) {{", f"  *r = {c(b)};", "}"]
            else:
                out += [f"static int {name}(int a, int b, int c) {{", f"  return {c(b)};", "}"]
        if routines and omp:
            out += ["#pragma omp end declare target"]
        d = "#pragma omp target enter data map" if omp else "#pragma acc enter data"
        enter_to = (lambda x: f"{d}(to: {x})") if omp else (lambda x: f"{d} copyin({x})")
        enter_alloc = (lambda x: f"{d}(alloc: {x})") if omp else (lambda x: f"{d} create({x})")
        x = "#pragma omp target exit data map" if omp else "#pragma acc exit data"
        leave = (lambda v: f"{x}(delete: {v})") if omp else (lambda v: f"{x} delete({v})")
        out += ["", "int main(void) {", "  int i, j, k, l, t1, t2, rsum, tot2;", "  int alpha[NV];", "  long long cs;",
                *(["  int dep = 0;"] if self.asyn and omp else []), "  // fuzz: setup", "  tot2 = 0;"]
        if s == "nested":
            for f in ("qa", "qb"):
                out += [enter_to(f)] if res == "enter" else []
                out += [f"  {f}.vf = malloc(NV * sizeof *{f}.vf);", enter_alloc(f"{f}.vf[0:NV]")]
            out += ["  for (i = 0; i < NV; i++) {"]
            for f in ("qa", "qb"):
                out += [f"    {f}.vf[i].sf = malloc(SZ * sizeof(int));", enter_alloc(f"{f}.vf[i].sf[0:SZ]")]
            out += ["  }"]
        elif s == "flat":
            for f in ("qa", "qb"):
                out += [f"  {f} = malloc(NV * sizeof *{f});", enter_alloc(f"{f}[0:NV]")]
            out += ["  for (i = 0; i < NV; i++) {"]
            for f in ("qa", "qb"):
                out += [f"    {f}[i].sf = malloc(SZ * sizeof(int));", enter_alloc(f"{f}[i].sf[0:SZ]")]
            out += ["  }"]
        elif s == "plain":
            out += ["  qa = malloc(NV * SZ * sizeof(int));", "  qb = malloc(NV * SZ * sizeof(int));"]
            out += [enter_alloc("qa[0:NV * SZ]"), enter_alloc("qb[0:NV * SZ]")] if res != "map" else []
        elif res == "enter":
            out += [enter_alloc("qa"), enter_alloc("qb")]
        out += ["  for (i = 0; i < NV; i++)", "    for (l = 0; l < P + 1; l++)", "      for (k = 0; k < N + 1; k++)",
                "        for (j = 0; j < M + 1; j++) {",
                f"          {self.at('qa')} = (7 * j + 13 * k + 29 * l + 101 * i + 5) % 1009;",
                f"          {self.at('qb')} = 0;", "        }", "  tot = 0;"]
        if res != "map":
            out += self.motion("to")
            if res == "declare":
                out += ["#pragma omp target update to(tot)" if omp else "#pragma acc update device(tot)"]
        out += body
        out += ["  // fuzz: checksum"] + self.sync()
        if res != "map":
            out += self.motion("from")
            if res == "declare":
                out += ["#pragma omp target update from(tot)" if omp else "#pragma acc update self(tot)"]
        out += ["  cs = 0;"]
        for f in ("qa", "qb"):
            out += ["  for (i = 0; i < NV; i++)", "    for (l = 0; l < P + 1; l++)", "      for (k = 0; k < N + 1; k++)",
                    "        for (j = 0; j < M + 1; j++)", f"          cs = (cs * 31 + {self.at(f)}) % 2147483629LL;"]
        out += ["  cs = (cs * 31 + tot) % 2147483629LL;", "  cs = (cs * 31 + tot2) % 2147483629LL;"]
        if res != "map":
            if s == "nested":
                out += ["  for (i = 0; i < NV; i++) {", leave("qa.vf[i].sf[0:SZ]"), leave("qb.vf[i].sf[0:SZ]"), "  }",
                        leave("qa.vf[0:NV]"), leave("qb.vf[0:NV]")]
                out += [leave("qa"), leave("qb")] if res == "enter" else []
            elif s == "flat":
                out += ["  for (i = 0; i < NV; i++) {", leave("qa[i].sf[0:SZ]"), leave("qb[i].sf[0:SZ]"), "  }",
                        leave("qa[0:NV]"), leave("qb[0:NV]")]
            elif s == "plain":
                out += [leave("qa[0:NV * SZ]"), leave("qb[0:NV * SZ]")]
            elif res == "enter":
                out += [leave("qa"), leave("qb")]
        out += ['  printf("RESULT checksum=%lld ran_on_host=%d\\n", cs, 0);', "  return 0;", "}"]
        return "\n".join(out) + "\n"


def generate(seed: int, gen_version: str = GEN) -> F.FuzzProgram:
    return CSwarm(seed, "acc" if gen_version == GEN_ACC else "omp").build()
