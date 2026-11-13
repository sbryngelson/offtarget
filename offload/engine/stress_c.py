"""C OpenMP stress programs, the C counterpart of offload.engine.stress.

Generated features: structs with pointer members and deep copy, declare mapper,
VLAs, long lists, long identifiers, device functions with many parameters, and
many translation units sharing a header of declare target prototypes.
Function pointers are not generated.

Conventions match the Fortran generator: a program is a list of kernels
``void kNNNN(int64_t *cs)``, each printing ``K <name> <value>``, then
``RESULT checksum=<sum mod P> ran_on_host=<0|1>``. Values come from a Python
model; arithmetic is int64_t only and bounded. A program that exceeds a C11
5.2.4.1 translation limit (63 initial characters in an internal identifier, 31
in an external one, 127 parameters or arguments, 4095 characters per logical
line) is labelled ``impl_defined``; otherwise it is ``legal``."""
from __future__ import annotations

import random
import re

from offload.engine.stress import (FILE_MARK, P, BOUND, Overflow, StressProgram,
                               cksum, fmod)

GEN = "stress-c-1"
C_IDENT = 63          # C11 5.2.4.1: significant initial characters, internal
C_EXTERN = 31         # external identifiers
C_PARAMS = 127        # parameters in one function definition
C_LINE = 4095         # characters in a logical source line
WIDTH = 100

CITES_C = {
    "ident": "C11 5.2.4.1: 63 significant initial characters in an internal "
             "identifier, 31 in an external one (minimum limits; beyond them "
             "the implementation's documented limit applies)",
    "params": "C11 5.2.4.1: 127 parameters in one function definition and "
              "127 arguments in one call (minimum limits)",
    "line": "C11 5.2.4.1: 4095 characters in a logical source line "
            "(minimum limit)",
    "xtu": "OpenMP 5.2 §13.8 p.284 and §5.8.4 p.158: a function defined in "
           "another translation unit needs its own declare target",
    "begin": "begin declare target is OpenMP 5.1 (5.1 §2.14.7); the program "
             "is a 5.1/5.2 program",
}


def c_pragma(head: str, atoms: list[str], indent: str = "  ",
             width: int = WIDTH) -> list[str]:
    """``#pragma omp <head> atoms...`` with backslash continuations."""
    lines, cur = [], f"{indent}#pragma omp {head}"
    for a in atoms:
        if len(cur) + len(a) + 3 > width and not cur.endswith(head):
            lines.append(cur + " \\")
            cur = f"{indent}    {a}"
        else:
            cur += " " + a
    lines.append(cur)
    return lines


def c_list(name: str, items: list[str], mod: str = "") -> list[str]:
    if not items:
        return []
    head = f"{name}({mod}: " if mod else f"{name}("
    return [(head if k == 0 else "") + it + ("," if k < len(items) - 1
                                             else ")")
            for k, it in enumerate(items)]


def c_stmt(indent: str, head: str, parts: list[str], width: int = WIDTH
           ) -> list[str]:
    lines, cur = [], indent + head
    for p in parts:
        if len(cur) + len(p) + 1 > width and cur.strip() != head.strip():
            lines.append(cur)
            cur = indent + "    " + p
        else:
            cur += ("" if cur.endswith(("(", " ")) else " ") + p
    lines.append(cur)
    return lines


def vname(prefix: str, k: int) -> str:
    return f"{prefix}{k:04d}"


class CKernel:
    kind = "base"
    legality = "legal"
    cite = ""
    elision_valid = True

    def __init__(self, name: str, rng: random.Random | None, **p):
        self.name = name
        self.p = dict(p)
        if rng is not None:
            self.draw(rng)

    def draw(self, rng):
        pass

    def clone(self, **change):
        return type(self)(self.name, None, **{**self.p, **change})

    def globals(self) -> list[str]:
        """File-scope declarations and device functions (the kernel's own
        translation unit, before its function)."""
        return []

    def header(self) -> list[str]:
        """Declarations other translation units need (types, prototypes,
        extern variables)."""
        return []

    def extra_files(self) -> list[tuple[str, str]]:
        return []

    def body(self) -> list[str]:
        raise NotImplementedError

    def value(self) -> int:
        raise NotImplementedError

    def smaller(self):
        return []

    def features(self) -> set:
        return {f"kernel:c_{self.kind}"}

    def describe(self) -> str:
        keys = ",".join(f"{k}={v}" for k, v in sorted(self.p.items())
                        if isinstance(v, (int, str)))
        return f"{self.name}:c_{self.kind}({keys})"

    def function(self) -> list[str]:
        return [f"void {self.name}(int64_t *cs) {{"] + self.body() + ["}"]


def _halve(n, lo=1):
    return [m for m in sorted({lo, n // 2}) if lo <= m < n]


class CLoop(CKernel):
    kind = "loop"
    CHAINS = ("target teams distribute parallel for",
              "target teams distribute parallel for simd",
              "target parallel for", "target teams distribute",
              "target simd", "target teams loop")

    def draw(self, rng):
        self.p.setdefault("chain", rng.randrange(len(self.CHAINS)))
        self.p.setdefault("n", rng.choice((64, 257, 1000)))
        self.p.setdefault("c", [rng.randrange(1, 1000) for _ in range(3)])

    def body(self):
        n, (c1, c2, c3) = self.p["n"], self.p["c"]
        ch = self.CHAINS[self.p["chain"] % len(self.CHAINS)]
        return [f"  static int64_t a[{n}], out[{n}];",
                f"  for (int i = 0; i < {n}; i++) {{ a[i] = (i + 1) * 37 % "
                "1009; out[i] = 0; }"] + c_pragma(
            ch, [f"map(to: a[0:{n}])", f"map(tofrom: out[0:{n}])"]) + [
            f"  for (int i = 0; i < {n}; i++)",
            f"    out[i] = (a[i] * {c1} + (i + 1) * {c2} + {c3}) % 1000003;",
            f"  *cs = st_cksum(out, {n});"]

    def value(self):
        n, (c1, c2, c3) = self.p["n"], self.p["c"]
        return cksum(((i * 37 % 1009) * c1 + i * c2 + c3) % 1000003
                     for i in range(1, n + 1))

    def smaller(self):
        return [self.clone(n=m) for m in _halve(self.p["n"], 8)]


class CList(CKernel):
    """List axes: private, firstprivate, lastprivate, reduction, map,
    depend, capture, is_device_ptr."""

    def __init__(self, name, rng, **p):
        self.kind = p.get("what", "private")
        super().__init__(name, rng, **p)

    def draw(self, rng):
        k = self.p.setdefault("nitems", 8)
        self.p.setdefault("n", max(8, min(256, 200000 // max(1, k))))
        self.p.setdefault("c", [rng.randrange(1, 97) for _ in range(k)])

    def items(self, pre):
        return [vname(pre, j) for j in range(1, self.p["nitems"] + 1)]

    def smaller(self):
        k = self.p["nitems"]
        return [self.clone(nitems=m, c=self.p["c"][:m]) for m in _halve(k)]

    def features(self):
        return super().features() | {f"len:c_{self.kind}:{self.p['nitems']}"}

    def body(self):
        w, n, c = self.p["what"], self.p["n"], self.p["c"]
        k = self.p["nitems"]
        L = ["  int64_t t;", f"  static int64_t out[{n}];",
             f"  for (int i = 0; i < {n}; i++) out[i] = 0;"]
        head = "target teams distribute parallel for"
        if w == "private":
            V = self.items("p")
            L += [f"  int64_t {', '.join(V)};"]
            if self.p.get("contlines"):
                # every list item on its own backslash-continued line
                L += [f"  #pragma omp {head} map(tofrom: out[0:{n}]) "
                      "private( \\"] + [f"      {x}, \\" for x in V] + \
                    ["      t)"]
            else:
                L += c_pragma(head, [f"map(tofrom: out[0:{n}])"] +
                              c_list("private", V + ["t"]))
            L += [f"  for (int i = 1; i <= {n}; i++) {{"]
            L += [f"    {x} = (i * {c[j]} + {j + 1}) % 997;"
                  for j, x in enumerate(V)]
            L += ["    t = 0;"] + [f"    t += {x};" for x in V] + \
                ["    out[i - 1] = t;", "  }", f"  *cs = st_cksum(out, {n});"]
        elif w in ("firstprivate", "capture"):
            V = self.items("f")
            L += [f"  int64_t {x} = {c[j] * 7 + j};" for j, x in enumerate(V)]
            atoms = [f"map(tofrom: out[0:{n}])", "private(t)"]
            if w == "firstprivate":
                atoms += c_list("firstprivate", V)
            L += c_pragma(head, atoms)
            L += [f"  for (int i = 1; i <= {n}; i++) {{", "    t = 0;"]
            L += [f"    t += {x} * ((i + {j}) % 3);" for j, x in enumerate(V)]
            L += ["    out[i - 1] = t;", "  }", f"  *cs = st_cksum(out, {n});"]
            L += ["  t = 0;"] + [f"  t += {x};" for x in V] + \
                [f"  *cs = (*cs + t) % {P};"]
        elif w == "lastprivate":
            V = self.items("l")
            L += [f"  int64_t {x} = 0;" for x in V]
            L += c_pragma(head, c_list("lastprivate", V))
            L += [f"  for (int i = 1; i <= {n}; i++) {{"]
            L += [f"    {x} = i * {c[j]} + {j};" for j, x in enumerate(V)]
            L += ["  }", "  t = 0;"] + [f"  t += {x};" for x in V] + \
                [f"  *cs = t % {P};"]
        elif w == "reduction":
            V = self.items("r")
            L += [f"  int64_t {x} = {j};" for j, x in enumerate(V)]
            L += c_pragma(head, c_list("reduction", V, "+"))
            L += [f"  for (int i = 1; i <= {n}; i++) {{"]
            L += [f"    {x} += (i * {c[j]} + {j}) % 65536;"
                  for j, x in enumerate(V)]
            L += ["  }", "  *cs = 0;"] + [f"  *cs = (*cs * 31 + {x}) % {P};"
                                           for x in V]
        elif w == "map":
            A, B = self.items("a"), self.items("b")
            m = 16
            L += [f"  static int64_t {x}[{m}];" for x in A + B]
            L += [f"  for (int i = 0; i < {m}; i++) {{"]
            L += [f"    {A[j]}[i] = (i + 1) * {j + 3} % 101; {B[j]}[i] = {j};"
                  for j in range(k)] + ["  }"]
            L += c_pragma(head, c_list("map", [f"{x}[0:{m}]" for x in A], "to")
                          + c_list("map", [f"{x}[0:{m}]" for x in B],
                                   "tofrom"))
            L += [f"  for (int i = 0; i < {m}; i++) {{"]
            L += [f"    {B[j]}[i] += {A[j]}[i] * {c[j]};" for j in range(k)]
            L += ["  }", "  *cs = 0;"]
            L += [f"  *cs = (*cs * 31 + st_cksum({x}, {m})) % {P};" for x in B]
        elif w == "depend":
            V = self.items("d")
            L += [f"  int64_t {x} = 0;" for x in V]
            L += ["  int64_t x[4] = {1, 1, 1, 1};",
                  "  for (int t2 = 1; t2 <= 6; t2++) {"]
            L += c_pragma("target", ["map(tofrom: x[0:4])", "nowait"] +
                          c_list("depend", V, "inout"), "    ")
            L += ["    { x[0] = (x[0] * 3 + t2) % 1000003; x[1] = x[0] + t2; }",
                  "  }", "  #pragma omp taskwait", "  *cs = st_cksum(x, 4);"]
        elif w == "is_device_ptr":
            V = self.items("q")
            m = 8
            L += ["  int dev = omp_get_default_device();",
                  "  int hst = omp_get_initial_device();",
                  f"  static int64_t h[{m}];"]
            L += [f"  int64_t *{x} = (int64_t *) omp_target_alloc({m} * "
                  "sizeof(int64_t), dev);" for x in V]
            L += c_pragma("target teams distribute parallel for",
                          c_list("is_device_ptr", V))
            L += [f"  for (int i = 0; i < {m}; i++) {{"]
            L += [f"    {x}[i] = (i + 1) * {j + 2};" for j, x in enumerate(V)]
            L += ["  }", "  *cs = 0;"]
            for x in V:
                L += [f"  omp_target_memcpy(h, {x}, {m} * sizeof(int64_t), 0, 0,"
                      " hst, dev);",
                      f"  *cs = (*cs * 31 + st_cksum(h, {m})) % {P};",
                      f"  omp_target_free({x}, dev);"]
        return L

    def value(self):
        w, n, c = self.p["what"], self.p["n"], self.p["c"]
        k = self.p["nitems"]
        if w == "private":
            return cksum(sum((i * c[j] + j + 1) % 997 for j in range(k))
                         for i in range(1, n + 1))
        if w in ("firstprivate", "capture"):
            f = [c[j] * 7 + j for j in range(k)]
            cs = cksum(sum(f[j] * ((i + j) % 3) for j in range(k))
                       for i in range(1, n + 1))
            return (cs + sum(f)) % P
        if w == "lastprivate":
            return sum(n * c[j] + j for j in range(k)) % P
        if w == "reduction":
            cs = 0
            for j in range(k):
                v = j + sum((i * c[j] + j) % 65536 for i in range(1, n + 1))
                cs = (cs * 31 + v) % P
            return cs
        if w == "map":
            cs = 0
            for j in range(k):
                cs = (cs * 31 + cksum(j + ((i * (j + 3)) % 101) * c[j]
                                      for i in range(1, 17))) % P
            return cs
        if w == "depend":
            x = [1, 1, 1, 1]
            for t in range(1, 7):
                x[0] = (x[0] * 3 + t) % 1000003
                x[1] = x[0] + t
            return cksum(x)
        if w == "is_device_ptr":
            cs = 0
            for j in range(k):
                cs = (cs * 31 + cksum(i * (j + 2) for i in range(1, 9))) % P
            return cs
        raise ValueError(w)


class CNames(CKernel):
    """Identifiers of `length` characters: a struct tag and member, a
    device function (external identifier), and `count` locals in a private
    list. C11 5.2.4.1 guarantees 63 significant characters internal, 31
    external; longer names are within the implementation's documented
    limit (impl_defined, never a bug if rejected)."""
    kind = "names"

    def draw(self, rng):
        self.p.setdefault("length", 63)
        self.p.setdefault("count", 4)
        self.p.setdefault("n", 64)

    def nm(self, tag, k=0):
        base = f"{tag}{self.name[1:]}{k}_"
        L = self.p["length"]
        return (base + "x" * max(0, L - len(base)))[:max(L, len(base))]

    def globals(self):
        t, m, f = self.nm("t"), self.nm("m"), self.nm("f")
        return [f"struct {t} {{ int64_t {m}; }};",
                "#pragma omp declare target",
                f"int64_t {f}(int64_t x) {{ return x * 3 + 1; }}",
                "#pragma omp end declare target"]

    def body(self):
        n, cnt = self.p["n"], self.p["count"]
        V = [self.nm("v", k) for k in range(cnt)]
        t, m, f = self.nm("t"), self.nm("m"), self.nm("f")
        L = [f"  static int64_t out[{n}];", f"  struct {t} obj;",
             f"  obj.{m} = 9;"] + [f"  int64_t {v};" for v in V]
        L += c_pragma("target teams distribute parallel for",
                      [f"map(tofrom: out[0:{n}])", "map(to: obj)"] +
                      c_list("private", V))
        L += [f"  for (int i = 1; i <= {n}; i++) {{"]
        L += [f"    {v} =\n      {f}(i) + {k};" for k, v in enumerate(V)]
        L += [f"    out[i - 1] = obj.{m};"] + \
            [f"    out[i - 1] +=\n      {v};" for v in V] + ["  }"]
        L += [f"  *cs = st_cksum(out, {n});"]
        return L

    def value(self):
        n, cnt = self.p["n"], self.p["count"]
        return cksum(9 + sum(i * 3 + 1 + k for k in range(cnt))
                     for i in range(1, n + 1))

    def features(self):
        return super().features() | {f"len:c_names:{self.p['length']}"}


class CLocals(CKernel):
    kind = "locals"

    def draw(self, rng):
        self.p.setdefault("nlocals", 64)
        self.p.setdefault("n", max(8, min(256, 100000 // max(
            1, self.p["nlocals"]))))

    def globals(self):
        k = self.p["nlocals"]
        L = ["#pragma omp declare target",
             f"static int64_t {self.name}_dr(int64_t x) {{"]
        for j in range(1, k + 1):
            L.append(f"  int64_t {vname('q', j)} = (x * {j + 1} + {j}) % 991;")
        L.append("  int64_t r = 0;")
        L += [f"  r += {vname('q', j)};" for j in range(1, k + 1)]
        L += ["  return r;", "}", "#pragma omp end declare target"]
        return L

    def body(self):
        n = self.p["n"]
        return [f"  static int64_t out[{n}];"] + c_pragma(
            "target teams distribute parallel for",
            [f"map(tofrom: out[0:{n}])"]) + [
            f"  for (int i = 1; i <= {n}; i++) out[i - 1] = "
            f"{self.name}_dr(i);", f"  *cs = st_cksum(out, {n});"]

    def value(self):
        k, n = self.p["nlocals"], self.p["n"]
        return cksum(sum((i * (j + 1) + j) % 991 for j in range(1, k + 1))
                     for i in range(1, n + 1))

    def smaller(self):
        return [self.clone(nlocals=m) for m in _halve(self.p["nlocals"])]


class CArgs(CKernel):
    """A device function with `nargs` parameters: int64_t by value, a
    pointer with a length, a struct by value, a pointer to a struct; past
    127 parameters the C11 minimum limit is exceeded (impl_defined)."""
    kind = "args"

    def draw(self, rng):
        self.p.setdefault("nargs", 16)
        self.p.setdefault("n", max(8, min(256, 60000 // max(
            1, self.p["nargs"]))))

    def kinds(self):
        return [("val", "ptr", "sval", "sptr")[j % 4]
                for j in range(self.p["nargs"])]

    def globals(self):
        ks = self.kinds()
        ps = []
        for j, kd in enumerate(ks, 1):
            x = vname("a", j)
            ps.append({"val": f"int64_t {x}", "ptr": f"const int64_t *{x}",
                       "sval": f"struct st_pair {x}",
                       "sptr": f"const struct st_pair *{x}"}[kd])
        L = ["#pragma omp declare target"]
        L += c_stmt("", f"static int64_t {self.name}_dr(",
                    [p + ("," if j < len(ps) - 1 else ") {")
                     for j, p in enumerate(ps)])
        L.append("  int64_t r = 0;")
        for j, kd in enumerate(ks, 1):
            x = vname("a", j)
            L.append({"val": f"  r += {x} * {j % 13 + 1};",
                      "ptr": f"  r += {x}[0] + {x}[3] * 2;",
                      "sval": f"  r += {x}.u * 3 + {x}.v;",
                      "sptr": f"  r += {x}->u + {x}->v * 2;"}[kd])
        L += ["  return r;", "}", "#pragma omp end declare target"]
        return L

    def body(self):
        n = self.p["n"]
        args = []
        for j, kd in enumerate(self.kinds(), 1):
            args.append({"val": f"i + {j}", "ptr": "arr", "sval": "pr",
                         "sptr": "&pr"}[kd])
        L = [f"  static int64_t out[{n}];",
             "  int64_t arr[4] = {3, 5, 7, 11};",
             "  struct st_pair pr = {4, 9};"]
        L += c_pragma("target teams distribute parallel for",
                      [f"map(tofrom: out[0:{n}])", "map(to: arr[0:4], pr)"])
        L += [f"  for (int64_t i = 1; i <= {n}; i++) {{"]
        L += c_stmt("    ", f"out[i - 1] = {self.name}_dr(",
                    [a + ("," if j < len(args) - 1 else ");")
                     for j, a in enumerate(args)])
        L += ["  }", f"  *cs = st_cksum(out, {n});"]
        return L

    def value(self):
        n = self.p["n"]
        vals = []
        for i in range(1, n + 1):
            r = 0
            for j, kd in enumerate(self.kinds(), 1):
                r += {"val": (i + j) * (j % 13 + 1), "ptr": 3 + 22,
                      "sval": 21, "sptr": 4 + 18}[kd]
            vals.append(r)
        return cksum(vals)

    def smaller(self):
        return [self.clone(nargs=m) for m in _halve(self.p["nargs"])]

    def features(self):
        return super().features() | {f"len:c_args:{self.p['nargs']}"}


class CStruct(CKernel):
    """Structs nested `depth` levels, each with an int64_t s and a pointer
    member p to n elements; an array of `na` of them; deep copy by an
    explicit map list (map(to: x[0:na]) and every x[e].in...in.p[0:n]),
    or ('mapper') by a declare mapper per level (OpenMP 5.0 §2.19.7.4)."""
    kind = "struct"

    def draw(self, rng):
        self.p.setdefault("depth", 3)
        self.p.setdefault("na", 2)
        self.p.setdefault("m", 16)
        self.p.setdefault("mode", rng.choice(("list", "mapper")))

    def t(self, d):
        return f"{self.name}_t{d}"

    def path(self, e, d):
        return f"x[{e}]" + ".in" * (d - 1)

    def globals(self):
        D = self.p["depth"]
        L = []
        for d in range(D, 0, -1):
            L.append(f"struct {self.t(d)} {{ int64_t s; int64_t *p; int64_t "
                     "n;" + (f" struct {self.t(d + 1)} in;" if d < D else "")
                     + " };")
        if self.p["mode"] == "mapper":
            for d in range(D, 0, -1):
                its = ["v", "v.p[0:v.n]"] + (["v.in"] if d < D else [])
                L.append(f"#pragma omp declare mapper(struct {self.t(d)} v) "
                         f"map(tofrom: {', '.join(its)})")
        return L

    def body(self):
        D, na, m = self.p["depth"], self.p["na"], self.p["m"]
        L = [f"  static struct {self.t(1)} x[{na}];",
             f"  static int64_t out[{m}];",
             f"  static int64_t store[{na}][{D}][{m}];"]
        for e in range(na):
            for d in range(1, D + 1):
                pth = self.path(e, d)
                L += [f"  {pth}.s = {d * 10 + e};",
                      f"  {pth}.n = {m};",
                      f"  {pth}.p = store[{e}][{d - 1}];",
                      f"  for (int i = 0; i < {m}; i++) {pth}.p[i] = "
                      f"((i + 1) * {d} + {e}) % 97;"]
        L.append(f"  for (int i = 0; i < {m}; i++) out[i] = 0;")
        if self.p["mode"] == "list":
            items = [f"x[0:{na}]"] + [f"{self.path(e, d)}.p[0:{m}]"
                                      for e in range(na)
                                      for d in range(1, D + 1)]
            atoms = c_list("map", items, "to")
        else:
            atoms = [f"map(tofrom: x[0:{na}])"]
        L += c_pragma("target teams distribute parallel for",
                      [f"map(tofrom: out[0:{m}])"] + atoms)
        L += [f"  for (int i = 0; i < {m}; i++) {{"]
        for e in range(na):
            for d in range(1, D + 1):
                pth = self.path(e, d)
                L.append(f"    out[i] += {pth}.p[i] + {pth}.s;")
        L += ["  }", f"  *cs = st_cksum(out, {m});"]
        return L

    def value(self):
        D, na, m = self.p["depth"], self.p["na"], self.p["m"]
        return cksum(sum(((i * d + e) % 97) + d * 10 + e
                         for e in range(na) for d in range(1, D + 1))
                     for i in range(1, m + 1))

    def smaller(self):
        out = []
        if self.p["depth"] > 1:
            out.append(self.clone(depth=1))
        if self.p["na"] > 1:
            out.append(self.clone(na=1))
        if self.p["mode"] == "mapper":
            out.append(self.clone(mode="list"))
        return out

    def features(self):
        return super().features() | {f"c_struct:depth{self.p['depth']}",
                                     f"c_struct:{self.p['mode']}"}


class CVLA(CKernel):
    """A variable-length array (C99/C11 6.7.6.2) of n x m elements mapped
    as an array section and used in a target region."""
    kind = "vla"

    def draw(self, rng):
        self.p.setdefault("n", 16)
        self.p.setdefault("m", 8)

    def body(self):
        n, m = self.p["n"], self.p["m"]
        return [f"  volatile int nn = {n}, mm = {m};",
                "  int n = nn, m = mm;", "  int64_t a[n][m];",
                "  for (int i = 0; i < n; i++)",
                "    for (int j = 0; j < m; j++) a[i][j] = i * 7 + j;"] + \
            c_pragma("target teams distribute parallel for collapse(2)",
                     ["map(tofrom: a[0:n][0:m])"]) + [
            "  for (int i = 0; i < n; i++)",
            "    for (int j = 0; j < m; j++) a[i][j] = a[i][j] * 3 + n;",
            "  *cs = st_cksum(&a[0][0], n * m);"]

    def value(self):
        n, m = self.p["n"], self.p["m"]
        return cksum((i * 7 + j) * 3 + n for i in range(n)
                     for j in range(m))


class CScalars(CKernel):
    """Default scalar residency in C: one route per kernel (as the Fortran
    ScalarsKernel): implicit firstprivate, map to/from/tofrom,
    defaultmap(tofrom|firstprivate: scalar), firstprivate, private,
    present_implicit (enter data then implicit: firstprivate from the
    host), declare target global with update, struct member (aggregate:
    tofrom), reduction."""
    kind = "scalars"
    elision_valid = False
    ROUTES = {"implicit": (True, "same"), "firstprivate": (True, "same"),
              "private": (False, "same"), "to": (True, None),
              "from": (False, "write"), "tofrom": (True, "write"),
              "dm_tofrom": (True, "write"), "dm_firstprivate": (True, "same"),
              "present_implicit": (True, "same"), "declare": (True, "write"),
              "member": (True, "write"), "reduction": (None, "red")}

    def draw(self, rng):
        self.p.setdefault("nscal", 4)
        self.p.setdefault("route", "implicit")

    def S(self):
        k, r = self.p["nscal"], self.p["route"]
        if r == "declare":
            return [f"{self.name}_g{j}" for j in range(1, k + 1)]
        if r == "member":
            return [f"xs.c{j}" for j in range(1, k + 1)]
        return [f"s{j}" for j in range(1, k + 1)]

    def globals(self):
        k, r = self.p["nscal"], self.p["route"]
        if r == "declare":
            return ["#pragma omp declare target"] + [
                f"int64_t {x};" for x in self.S()] + \
                ["#pragma omp end declare target"]
        if r == "member":
            return [f"struct {self.name}_sc {{ " + " ".join(
                f"int64_t c{j};" for j in range(1, k + 1)) + " };"]
        return []

    def h(self, j):
        return 100 + j

    def body(self):
        k, r = self.p["nscal"], self.p["route"]
        S = self.S()
        L = [f"  int64_t rd[{k}], a[4] = {{0, 0, 0, 0}};",
             f"  for (int j = 0; j < {k}; j++) rd[j] = -1;"]
        if r == "member":
            L.append(f"  struct {self.name}_sc xs;")
        elif r != "declare":
            L.append(f"  int64_t {', '.join(S)};")
        L += [f"  {x} = {self.h(j)};" for j, x in enumerate(S, 1)]
        name, atoms = "target", ["map(tofrom: rd[0:%d], a[0:4])" % k]
        pre, post = [], []
        if r in ("firstprivate", "private"):
            atoms += c_list(r, S)
        elif r in ("to", "from", "tofrom"):
            atoms += c_list("map", S, r)
        elif r.startswith("dm_"):
            atoms.append(f"defaultmap({r[3:]}: scalar)")
        elif r == "present_implicit":
            pre += c_pragma("target enter data", c_list("map", S, "to"))
            pre += [f"  {x} = {self.h(j)} + 1000;" for j, x in enumerate(S, 1)]
            post += c_pragma("target exit data", c_list("map", S, "delete"))
        elif r == "declare":
            pre += c_pragma("target update", c_list("to", S))
            post += c_pragma("target update", c_list("from", S))
        elif r == "reduction":
            name = "target teams distribute parallel for"
            atoms += c_list("reduction", S, "+")
        L += pre + c_pragma(name, atoms)
        if r == "reduction":
            L += ["  for (int ii = 0; ii < 4; ii++) {"]
            L += [f"    {x} += {j};" for j, x in enumerate(S, 1)]
            L += ["  }"]
        else:
            L.append("  {")
            if r == "from":
                L += [f"    {x} = {self.h(j)};" for j, x in enumerate(S, 1)]
            if r == "private":
                L += [f"    {x} = {j} * 5;" for j, x in enumerate(S, 1)]
            L += [f"    rd[{j - 1}] = {x};" for j, x in enumerate(S, 1)]
            L += [f"    {x} = 2 * {x} + 1;" for x in S]
            L += ["    a[0] += 1;", "  }"]
        L += post + ["  *cs = 0;"]
        dr, after = self.ROUTES[r]
        for j, x in enumerate(S, 1):
            if dr is not None:
                L.append(f"  *cs = (*cs * 31 + rd[{j - 1}]) % {P};")
            if after is not None:
                L.append(f"  *cs = (*cs * 31 + {x}) % {P};")
            else:
                L.append(f'  printf("OBS {self.name} {r} host %d %lld\\n", '
                         f'{j}, (long long) {x});')
        return L

    def value(self):
        k, r = self.p["nscal"], self.p["route"]
        dr, after = self.ROUTES[r]
        cs = 0
        for j in range(1, k + 1):
            h = self.h(j) + (1000 if r == "present_implicit" else 0)
            if dr is not None:
                rv = j * 5 if r == "private" else self.h(j) if r == "from" \
                    else h
                cs = (cs * 31 + rv) % P
            if after == "same":
                cs = (cs * 31 + h) % P
            elif after == "write":
                cs = (cs * 31 + 2 * h + 1) % P
            elif after == "red":
                cs = (cs * 31 + h + 4 * j) % P
        return cs

    def features(self):
        return super().features() | {f"route:c_{self.p['route']}"}


class CTU(CKernel):
    """A device call chain across translation units: g1 in the kernel's
    file calls g2 in its own file ... gD; the prototypes in the shared
    header between declare target and end declare target (5.0 form), or
    'begin' (5.1 begin declare target), or 'implicit' (no declare target
    on the definitions: an illegal probe when they are in other files)."""
    kind = "tu"

    def draw(self, rng):
        self.p.setdefault("depth", 5)
        self.p.setdefault("n", 256)
        self.p.setdefault("variant", "plain")
        self.p.setdefault("gv", rng.randrange(1, 100))
        if self.p["variant"] == "implicit":
            self.legality = "illegal_probe"
            self.cite = CITES_C["xtu"]

    def __init__(self, name, rng, **p):
        super().__init__(name, rng, **p)
        if self.p.get("variant") == "implicit":
            self.legality, self.cite = "illegal_probe", CITES_C["xtu"]

    def g(self, j):
        return f"{self.name}_g{j}"

    def header(self):
        D, v = self.p["depth"], self.p["variant"]
        protos = [f"int64_t {self.g(j)}(int64_t x);" for j in
                  range(1, D + 1)]
        if v == "implicit":
            return protos
        if v == "begin":
            return ["#pragma omp begin declare target"] + protos + \
                ["#pragma omp end declare target"]
        return ["#pragma omp declare target"] + protos + \
            ["#pragma omp end declare target"]

    def extra_files(self):
        D, v = self.p["depth"], self.p["variant"]
        files = []
        for j in range(2, D + 1):
            body = (f"  return {self.g(j + 1)}((x * 5) % 1013 + {j}) + {j};"
                    if j < D else f"  return x + {self.p['gv']};")
            dt = v != "implicit"
            text = ['#include "st.h"'] + (
                ["#pragma omp declare target"] if dt else []) + [
                f"int64_t {self.g(j)}(int64_t x) {{", body, "}"] + (
                ["#pragma omp end declare target"] if dt else [])
            files.append((f"{self.g(j)}.c", "\n".join(text) + "\n"))
        return files

    def globals(self):
        D, v = self.p["depth"], self.p["variant"]
        dt = v != "implicit"
        body = (f"  return {self.g(2)}((x * 5) % 1013 + 1) + 1;" if D > 1
                else f"  return x + {self.p['gv']};")
        return (["#pragma omp declare target"] if dt else []) + [
            f"int64_t {self.g(1)}(int64_t x) {{", body, "}"] + (
            ["#pragma omp end declare target"] if dt else [])

    def body(self):
        n = self.p["n"]
        return [f"  static int64_t out[{n}];"] + c_pragma(
            "target teams distribute parallel for",
            [f"map(tofrom: out[0:{n}])"]) + [
            f"  for (int64_t i = 1; i <= {n}; i++) out[i - 1] = "
            f"{self.g(1)}(i);", f"  *cs = st_cksum(out, {n});"]

    def value(self):
        D, n, gv = self.p["depth"], self.p["n"], self.p["gv"]
        vals = []
        for i in range(1, n + 1):
            x, add = i, 0
            for j in range(1, D):
                x = (x * 5) % 1013 + j
                add += j
            vals.append(x + gv + add)
        return cksum(vals)

    def smaller(self):
        return [self.clone(depth=m) for m in _halve(self.p["depth"], 2)]

    def features(self):
        return super().features() | {f"tu:c_{self.p['variant']}",
                                     f"tu:c_depth{self.p['depth']}"}


C_UTIL = f"""#include <stdint.h>
#include <stdio.h>
#ifdef _OPENMP
#include <omp.h>
#else
static inline int omp_is_initial_device(void) {{ return 1; }}
#endif
struct st_pair {{ int64_t u, v; }};
#pragma omp declare target
static inline int64_t st_cksum(const int64_t *a, int64_t n) {{
  int64_t cs = 0;
  for (int64_t i = 1; i <= n; i++)
    cs = (cs + (a[i - 1] % {P}) * (i % 7 + 1)) % {P};
  return cs;
}}
#pragma omp end declare target
"""
C_STUB = """#ifndef _OPENMP
#include <stdlib.h>
#include <string.h>
static inline int omp_get_default_device(void) { return 0; }
static inline int omp_get_initial_device(void) { return 0; }
static inline void *omp_target_alloc(size_t n, int d) { (void) d; return malloc(n); }
static inline void omp_target_free(void *p, int d) { (void) d; free(p); }
static inline int omp_target_memcpy(void *d, const void *s, size_t n, size_t a,
    size_t b, int x, int y) { (void) a; (void) b; (void) x; (void) y;
    memcpy(d, s, n); return 0; }
#endif
"""

C_AXES = ("kernels", "private", "firstprivate", "lastprivate", "reduction",
          "map", "depend", "capture", "is_device_ptr", "contlines", "names",
          "locals", "args", "struct", "vla", "scalars", "tu", "tuimp")
C_SWEEPS = {
    "kernels": (1, 8, 64, 256, 430, 1024),
    "private": (1, 8, 64, 159, 256, 1024, 2048),
    "firstprivate": (1, 8, 64, 256, 1024),
    "lastprivate": (1, 8, 64, 256, 1024),
    "reduction": (1, 8, 64, 256, 1024),
    "map": (1, 8, 31, 64, 256, 1024),
    "depend": (1, 8, 64, 256, 1024),
    "capture": (1, 8, 20, 64, 200, 1024),
    "is_device_ptr": (1, 8, 64, 256),
    "contlines": (1, 8, 64, 256, 1024),
    "names": (31, 63, 255, 1024, 4096),
    "locals": (1, 8, 64, 254, 1024, 2540),
    "args": (1, 8, 78, 127, 128, 256, 780),
    "struct": (1, 2, 3, 6, 12),
    "vla": (16,),
    "scalars": (1, 4, 20, 64),
    "tu": (2, 3, 5, 8, 16, 32),
    "tuimp": (2, 3, 5),
}


def _ckernels(axis: str, size: int, rng: random.Random) -> list:
    ks = []

    def add(cls, **p):
        ks.append(cls(f"k{len(ks) + 1:04d}", random.Random(rng.random()),
                      **p))
    if axis == "kernels":
        for _ in range(size):
            add(CLoop)
    elif axis in ("private", "firstprivate", "lastprivate", "reduction",
                  "map", "depend", "capture", "is_device_ptr"):
        add(CList, what=axis, nitems=size)
    elif axis == "contlines":
        add(CList, what="private", nitems=size, n=8, contlines=1)
    elif axis == "names":
        add(CNames, length=size)
    elif axis == "locals":
        add(CLocals, nlocals=size)
    elif axis == "args":
        add(CArgs, nargs=size)
    elif axis == "struct":
        add(CStruct, depth=size, mode="list")
        add(CStruct, depth=size, mode="mapper")
    elif axis == "vla":
        add(CVLA, n=size)
    elif axis == "scalars":
        for r in CScalars.ROUTES:
            add(CScalars, nscal=size, route=r)
    elif axis == "tu":
        add(CTU, depth=size, variant="plain")
        add(CTU, depth=size, variant="begin")
    elif axis == "tuimp":
        add(CTU, depth=size, variant="implicit")
    else:
        raise ValueError(f"unknown C axis {axis}")
    return ks


def assemble_c(axis: str, size: int, seed: int, ks: list, layout: str
               ) -> StressProgram:
    header = ["#ifndef ST_H", "#define ST_H", C_UTIL, C_STUB]
    for k in ks:
        header += k.header()
    header += [f"void {k.name}(int64_t *cs);" for k in ks]
    header.append("#endif")
    head_text = "\n".join(header) + "\n"
    kfiles = []
    for k in ks:
        body = k.function()
        kfiles.append((k, ['#include "st.h"'] + k.globals() + body))
    main = ['#include "st.h"', "int main(void) {",
            "  int64_t cs, total = 0;", "  int onhost = 1;"]
    for k in ks:
        main += [f"  {k.name}(&cs);",
                 f'  printf("K {k.name} %lld\\n", (long long) cs);',
                 f"  total = (total + cs) % {P};"]
    main += ["  #pragma omp target map(tofrom: onhost)",
             "  { onhost = omp_is_initial_device() ? 1 : 0; }",
             '  printf("RESULT checksum=%lld ran_on_host=%d\\n", '
             "(long long) total, onhost);", "  return 0;", "}"]
    comment = [f"/* stress: axis={axis} size={size} seed={seed} model=omp "
               f"lang=c layout={layout} */", f"/* generator: {GEN} */",
               "/* language: C11; OpenMP 5.2 (5.0 forms where they exist) */"]
    files = [("st.h", "\n".join(comment) + "\n" + head_text)]
    extra = []
    for k in ks:
        extra += k.extra_files()
    if layout == "single":
        text = ["/* single translation unit */"]
        for k, lines in kfiles:
            text += lines[1:]
        files.append(("stress.c", '#include "st.h"\n' + "\n".join(text)
                      + "\n" + "\n".join(main[1:]) + "\n"))
    else:
        for k, lines in kfiles:
            files.append((f"{k.name}.c", "\n".join(lines) + "\n"))
        files.append(("main.c", "\n".join(main) + "\n"))
    files += extra
    per = {k.name: k.value() for k in ks}
    expected = sum(per.values()) % P
    feats = set()
    for k in ks:
        feats |= k.features()
    legality, cite = "legal", ""
    lim = c_limits(files, ks)
    for k in ks:
        if k.legality != "legal" and legality == "legal":
            legality, cite = k.legality, k.cite
    if lim["violations"] and legality == "legal":
        legality = "impl_defined"
        cite = "; ".join(CITES_C[v] for v in lim["violations"])
    if any(isinstance(k, CTU) and k.p["variant"] == "begin" for k in ks):
        feats.add("omp51:begin_declare_target")
    pid = f"{axis}-c-{size}-{seed}" + ("" if layout == "single"
                                       else f"-{layout}")
    feats |= {f"axis:c_{axis}", f"layout:{layout}"}
    # a single-file implicit chain is legal (every g_j in the region's
    # compilation unit): only the chain's other files make it a probe
    if legality == "illegal_probe" and all(
            not (isinstance(k, CTU) and k.extra_files()) for k in ks):
        legality, cite = "legal", ""
    from offload.engine.stress import axis_rev
    prog = StressProgram(pid, axis, size, seed, "omp", layout, ks, files,
                         expected, per, legality, cite, feats, 0, lang="c",
                         gen=GEN, limits=lim, rev=axis_rev(axis, "c"))
    return prog


def c_limits(files, ks) -> dict:
    longest = ident = 0
    for name, text in files:
        for ln in text.splitlines():
            longest = max(longest, len(ln))
        for t in re.findall(r"[A-Za-z_]\w*", re.sub(r'"[^"]*"', "", text)):
            ident = max(ident, len(t))
    params = max([k.p.get("nargs", 0) for k in ks if isinstance(k, CArgs)]
                 or [0])
    v = []
    if ident > C_IDENT:
        v.append("ident")
    if params > C_PARAMS:
        v.append("params")
    if longest > C_LINE:
        v.append("line")
    return {"max_line": longest, "max_ident": ident, "max_params": params,
            "violations": v}


def build_c(axis: str, size: int, seed: int = 0, layout: str = "single"
            ) -> StressProgram:
    rng = random.Random(f"{GEN}:{axis}:{size}:{seed}")
    for _ in range(20):
        ks = _ckernels(axis, size, rng)
        try:
            return assemble_c(axis, size, seed, ks, layout)
        except Overflow:
            continue
    raise RuntimeError("model overflow")


del BOUND, FILE_MARK, fmod
