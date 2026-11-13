"""Stress programs: very large and very complex device-offload programs that
are still legal and still checked.

A stress program is a list of kernels. Each is its own subroutine in a kernel
module with its own data and prints its own value, so a wrong answer names the
kernel. Values come from a Python model (``Kernel.value``). The program prints
``K <name> <value>`` per kernel and ends with the fuzz line
``RESULT checksum=<sum mod P> ran_on_host=<0|1>`` (``offload.engine.fuzz_exec``).
``AXES`` lists the axes and ``build(axis, size, seed, ...)`` makes a program:
many kernels, deep nests and call chains, long clause lists, continuation
lines and names, derived types, many translation units, async sequences and
kernel shapes taken from real failing codes (``template``).
Each program is labelled ``legal``, ``illegal_probe`` (beyond a base-language
limit, so a rejection is right), ``unspecified`` or ``impl_defined``;
``limits`` relabels a program that exceeds a base-language limit."""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

P = 2147483629                    # checksum modulus (offload.engine.fuzz)
LINE_MAX = 132                    # F2008 3.3.2.1 / F2018 6.3.2.1
CONT_MAX = 255                    # F2008 3.3.2.4 / F2018 6.3.2.4
NAME_MAX = 63                     # F2008 3.2.2 / F2018 6.2.2
BOUND = 2 ** 62
FILE_MARK = "!@file "             # offload.engine.fuzz_base bundle marker
WIDTH = 100                       # default packing width of long lines

CITES = {
    "line": "Fortran 2018 6.3.2.1: a free-form line shall contain at most "
            "132 characters",
    "cont": "Fortran 2018 6.3.2.4: a free-form statement shall not have "
            "more than 255 continuation lines",
    "name": "Fortran 2018 6.2.2: a name shall have at most 63 characters",
    "xtu": "OpenMP 5.2 §13.8 p.284 (a procedure referenced in a target "
           "construct is treated as if named in an enter clause) and §5.8.4 "
           "p.158 (a device version is created when the enter clause is in "
           "the compilation unit of the definition), §1.2.2 p.3 (for "
           "Fortran a compilation unit is a program unit; OpenACC 3.4 "
           "§2.15.1 p.91 likewise): a procedure of another module needs its "
           "own declare target / routine directive, even in the same file",
    "tbp": "OpenMP 5.0 §1.2.6 p.15 / 5.2 §1.2.6 p.18 (mappable type): all "
           "type-bound procedures accessed in a target region must appear "
           "in a declare target directive",
    "poly": "an OpenMP 6.0 program: 6.0 §7.9.6 p.287, if a map list item "
            "has polymorphic type, the behavior is unspecified (5.2 restricts "
            "polymorphic allocatables only in firstprivate, lastprivate and "
            "copyprivate, §5.4.4, §5.4.5, §5.7.2 p.146; it does not make "
            "this map unspecified, so the program declares 6.0)",
    "contig": "OpenMP 5.2 §5.8.3 p.155: a map list item that is an array "
              "section must specify contiguous storage",
    "stride": "OpenMP 5.2 §5.9 p.164: data-motion clause list items may "
              "include array sections with stride expressions",
    "share": "OpenMP 5.2 §5.8.3 p.155: two map list items on one construct "
             "must not share original storage unless one contains the other",
}


class Overflow(Exception):
    """A model value left the bound: the kernel is redrawn smaller."""


def chk(v: int) -> int:
    if abs(v) >= BOUND:
        raise Overflow(v)
    return v


def fmod(a: int, p: int) -> int:
    """Fortran MOD (sign of the dividend)."""
    r = abs(a) % abs(p)
    return r if a >= 0 else -r


def cksum(vals) -> int:
    """The Fortran helper ``st_cksum``: sum of mod(v_i, P)*(mod(i,7)+1),
    i from 1, mod P (every v_i >= 0)."""
    cs = 0
    for i, v in enumerate(vals, 1):
        cs = (cs + fmod(v, P) * (i % 7 + 1)) % P
    return cs


# --- text helpers -----------------------------------------------------------------------------

def pack(head: str, atoms: list[str], indent: str, sentinel: str | None,
         width: int = WIDTH) -> list[str]:
    """Lines of a statement (sentinel None) or directive (``!$omp``)
    made of `head` and `atoms`, wrapped with ``&`` continuations at
    `width` columns (an atom is never split; an atom wider than the line
    gets a line of its own)."""
    lead = f"{indent}{sentinel} " if sentinel else indent
    cont = f"{indent}{sentinel}& " if sentinel else f"{indent}   & "
    lines, cur = [], lead + head
    for a in atoms:
        if len(cur) + len(a) + 1 + 2 > width and cur.strip() not in (
                lead.strip(), cont.strip()):
            lines.append(cur + " &")
            cur = cont + a
        else:
            cur = cur + ("" if cur.endswith(("(", " ")) or a.startswith(
                (")", ",")) else " ") + a
    lines.append(cur)
    return lines


def list_atoms(name: str, items: list[str], mod: str = "") -> list[str]:
    """Atoms of a clause with a list: ``name(mod: a,`` ``b,`` ... ``z)``."""
    if not items:
        return []
    head = f"{name}({mod}: " if mod else f"{name}("
    out = []
    for k, it in enumerate(items):
        piece = it + ("," if k < len(items) - 1 else ")")
        out.append(head + piece if k == 0 else piece)
    return out


def call_lines(indent: str, name: str, args: list[str],
               width: int = WIDTH) -> list[str]:
    if not args:
        return [f"{indent}call {name}()"]
    return pack(f"call {name}(", [a + ("," if k < len(args) - 1 else ")")
                                  for k, a in enumerate(args)],
                indent, None, width)


def sum_lines(indent: str, target: str, terms: list[str],
              width: int = WIDTH, chunk: int = 40) -> list[str]:
    """``target = target + t1 + t2 ...`` in statements of at most `chunk`
    terms (a long expression is the exprs axis' business)."""
    out = []
    for k in range(0, len(terms), chunk):
        part = terms[k:k + chunk]
        out += pack(f"{target} = {target} +",
                    [t + (" +" if j < len(part) - 1 else "")
                     for j, t in enumerate(part)], indent, None, width)
    return out


def vname(prefix: str, k: int, width: int = 4) -> str:
    return f"{prefix}{k:0{width}d}"


# --- directives for both models ------------------------------------------------------------------

@dataclass
class Opts:
    model: str = "omp"            # omp | acc
    spell: int = 50               # OpenMP spelling: 50 (5.0 forms) or 52
    level: str = "f2018"
    width: int = WIDTH

    @property
    def sent(self) -> str:
        return "!$omp" if self.model == "omp" else "!$acc"


# OpenMP chains (5.0 spellings; each a combined or split nest whose last
# leaf is a loop construct) and their OpenACC counterparts
OMP_CHAINS = (
    ("target teams distribute parallel do",),
    ("target teams distribute parallel do simd",),
    ("target parallel do",),
    ("target teams distribute",),
    ("target teams distribute simd",),
    ("target parallel do simd",),
    ("target simd",),
    ("target teams loop",),
    ("target", "teams distribute parallel do"),
    ("target teams", "distribute parallel do"),
    ("target", "parallel do"),
    ("target", "teams", "distribute parallel do"),
)
ACC_CHAINS = (
    ("parallel loop gang vector",),
    ("parallel loop",),
    ("kernels loop",),
    ("serial loop",),
    ("parallel", "loop gang vector"),
    ("kernels", "loop independent"),
)


def data_clauses(o: Opts, data: list[tuple[str, str]]) -> list[str]:
    """Atoms of the data clauses: [(item, to|from|tofrom|alloc)]."""
    groups: dict[str, list[str]] = {}
    for item, kind in data:
        groups.setdefault(kind, []).append(item)
    out = []
    for kind in ("to", "from", "tofrom", "alloc"):
        if kind not in groups:
            continue
        if o.model == "omp":
            out += list_atoms("map", groups[kind], kind)
        else:
            name = {"to": "copyin", "from": "copyout", "tofrom": "copy",
                    "alloc": "create"}[kind]
            out += list_atoms(name, groups[kind])
    return out


def region(o: Opts, chain: tuple, indent: str, data=(), private=(),
           firstprivate=(), reduction=(), collapse: int = 0,
           extra=(), loop_extra=()) -> tuple[list[str], list[str], str]:
    """(opening lines, closing lines, inner indent) of a loop region of
    `chain` (a tuple of directive texts, outermost first): data clauses on
    the first directive, privatization / reduction / collapse on the last
    (the loop directive), `extra` atoms on the first, `loop_extra` on the
    last. Fortran OpenMP: every directive gets its end directive (a
    combined loop construct's is optional; written for symmetry)."""
    opens, closes = [], []
    ind = indent
    n = len(chain)
    if n > 1 and reduction:
        # OpenACC 3.4 §2.6.2 p.41: a reduction variable of a loop in a
        # parallel construct must be in a data clause of the construct;
        # OpenMP: a reduction on a construct nested in target (not a
        # combined target construct) needs the variable mapped tofrom
        # (otherwise it is firstprivate on target: 5.2 §5.8.1 p.148)
        data = list(data) + [(v, "tofrom") for _, items in reduction
                             for v in items]
    if n > 1 and o.model == "omp":
        lp = [a for a in loop_extra if a.startswith("lastprivate(")]
        for v in [x.strip(",)") for a in lp for x in
                  a[len("lastprivate("):].split()]:
            data = list(data) + [(v, "tofrom")]
    fp_first = o.model == "acc" and n > 1
    for k, d in enumerate(chain):
        atoms = []
        if k == 0:
            atoms += data_clauses(o, list(data)) + list(extra)
            if fp_first:
                # OpenACC: firstprivate is a compute-construct clause
                # (3.4 §2.5.14), not a loop clause
                atoms += list_atoms("firstprivate", list(firstprivate))
        if k < n - 1 and "teams" in d.split() and reduction:
            # the teams of a split nest would race on the shared variable:
            # the reduction is on the teams construct too
            for op, items in reduction:
                atoms += list_atoms("reduction", list(items), op)
        if k == n - 1:
            if collapse > 1:
                atoms.append(f"collapse({collapse})")
            atoms += list_atoms("private", list(private))
            if not fp_first:
                atoms += list_atoms("firstprivate", list(firstprivate))
            for op, items in reduction:
                atoms += list_atoms("reduction", list(items), op)
            atoms += list(loop_extra)
        opens += pack(d, atoms, ind, o.sent, o.width)
        dname = d if o.model == "omp" else " ".join(
            w for w in d.split() if w in ("parallel", "kernels", "serial",
                                          "loop"))
        closes.insert(0, f"{ind}{o.sent} end {dname}")
        if k < n - 1:
            ind += "  "
    if o.model == "acc":
        # an OpenACC loop construct has no end directive; a combined
        # construct's is optional (written), a compute construct's required
        closes = [c for c, d in zip(closes, reversed(chain))
                  if " loop" not in " " + d or d.split()[0] in
                  ("parallel", "kernels", "serial")]
    return opens, closes, ind


# --- kernels -----------------------------------------------------------------------------------

@dataclass
class Module:
    name: str
    spec: list[str] = field(default_factory=list)
    contains: list[str] = field(default_factory=list)
    uses: list[str] = field(default_factory=list)


class Kernel:
    """One kernel: a subroutine ``<name>(cs)`` of a kernel module. Every
    random decision is made in the constructor (``self.p``), so the text
    and the value are functions of ``p``; ``smaller`` returns variants for
    the shrinker."""
    kind = "base"
    legality = "legal"
    cite = ""
    version = 50                  # the OpenMP version whose text it needs
    # whether the sequential elision computes the kernel's value (False
    # where the value depends on data-sharing: a firstprivate copy's write
    # is not seen by the host, the elided program writes the variable)
    elision_valid = True

    def __init__(self, name: str, o: Opts, rng: random.Random | None,
                 **p):
        self.name, self.o = name, o
        self.p = dict(p)
        if rng is not None:
            self.draw(rng)

    def draw(self, rng: random.Random) -> None:
        pass

    def clone(self, **change) -> "Kernel":
        k = type(self)(self.name, self.o, None, **{**self.p, **change})
        return k

    # text
    def modules(self) -> list[Module]:
        return []

    def uses(self) -> list[str]:
        return []

    def decls(self) -> list[str]:
        return []

    def body(self) -> list[str]:
        return []

    def value(self) -> int:
        raise NotImplementedError

    def smaller(self) -> list["Kernel"]:
        return []

    def features(self) -> set:
        return {f"kernel:{self.kind}"}

    def describe(self) -> str:
        def show(v):
            if isinstance(v, list) and len(v) <= 6 and all(
                    isinstance(x, int) for x in v):
                return "x".join(map(str, v))
            if isinstance(v, list) and all(isinstance(x, str) for x in v):
                return "+".join(v) if len(v) <= 4 else f"{len(v)}items"
            return v
        keys = ",".join(f"{k}={show(v)}" for k, v in sorted(self.p.items())
                        if (isinstance(v, (int, str)) or k in ("ext",
                                                                 "routes"))
                        and k != "seed")
        return f"{self.name}:{self.kind}({keys})"

    def routine(self) -> list[str]:
        ind = "    "
        lines = [f"  subroutine {self.name}(cs)"]
        for u in self.uses():
            lines.append(f"{ind}use {u}")
        lines += [f"{ind}implicit none", f"{ind}integer(8), intent(out) :: cs"]
        lines += [ind + d if not d.startswith(" ") else d
                  for d in self.decls()]
        lines += self.body()
        lines.append(f"  end subroutine {self.name}")
        return lines


def _halve(n: int, lo: int = 1) -> list[int]:
    out = []
    for m in (lo, n // 2):
        if lo <= m < n and m not in out:
            out.append(m)
    return out


class LoopKernel(Kernel):
    """out(i) = mod(a(i)*c1 + i*c2 + c3, 1000003) over a random chain."""
    kind = "loop"

    def draw(self, rng):
        chains = OMP_CHAINS if self.o.model == "omp" else ACC_CHAINS
        self.p.setdefault("chain", rng.randrange(len(chains)))
        self.p.setdefault("n", rng.choice((64, 100, 257, 1000, 4096)))
        self.p.setdefault("c", [rng.randrange(1, 1000) for _ in range(3)])

    def chain(self):
        chains = OMP_CHAINS if self.o.model == "omp" else ACC_CHAINS
        return chains[self.p["chain"] % len(chains)]

    def decls(self):
        n = self.p["n"]
        return [f"integer(8) :: a({n}), out({n})", "integer :: i"]

    def body(self):
        n, (c1, c2, c3) = self.p["n"], self.p["c"]
        ind = "    "
        lines = [f"{ind}do i = 1, {n}", f"{ind}  a(i) = mod(i * 37, 1009)",
                 f"{ind}end do", f"{ind}out = 0"]
        op, cl, ii = region(self.o, self.chain(), ind,
                            data=[("a", "to"), ("out", "tofrom")])
        lines += op + [f"{ii}do i = 1, {n}",
                       f"{ii}  out(i) = mod(a(i) * {c1} + i * {c2} + {c3}, "
                       "1000003_8)", f"{ii}end do"] + cl
        lines.append(f"{ind}call st_cksum(out, {n}, cs)")
        return lines

    def value(self):
        n, (c1, c2, c3) = self.p["n"], self.p["c"]
        return cksum(fmod((i * 37 % 1009) * c1 + i * c2 + c3, 1000003)
                     for i in range(1, n + 1))

    def smaller(self):
        return [self.clone(n=m) for m in _halve(self.p["n"], 8)] + (
            [self.clone(chain=0)] if self.p["chain"] else [])

    def features(self):
        return super().features() | {"chain:" + " | ".join(self.chain())}


class NestKernel(Kernel):
    """A loop nest `depth` deep; collapse(c) on the loop directive (c up
    to the depth); out(lin) = sum_k idx_k * w_k + c0 where lin is the
    linear index of the full nest; optional split: teams distribute over
    the outermost loop, a nested parallel do (collapse) over the next, simd
    on the innermost."""
    kind = "nest"

    def draw(self, rng):
        d = self.p.setdefault("depth", 3)
        # past 16 levels the extra levels run once (2**16 iterations at
        # most from extents of 2): the nest depth is the stress, not the
        # iteration count
        ext = self.p.setdefault("ext", [rng.choice((2, 3, 4, 5)) if k < 16
                                        else 1 for k in range(d)])
        tot = 1
        for e in ext:
            tot *= e
        while tot > 200000:
            k = max(range(d), key=lambda j: ext[j])
            ext[k] = max(min(2, ext[k]), ext[k] - 1)
            tot = 1
            for e in ext:
                tot *= e
            if all(e <= 2 for e in ext):
                break
        self.p.setdefault("collapse", rng.choice(
            (d, d, max(1, d - 1), 1)) if d > 1 else 1)
        self.p.setdefault("split", rng.random() < 0.4 and d >= 3)
        self.p.setdefault("w", [rng.randrange(1, 50) for _ in range(d)])
        self.p.setdefault("c0", rng.randrange(1000))

    def total(self):
        t = 1
        for e in self.p["ext"]:
            t *= e
        return t

    def decls(self):
        d = self.p["depth"]
        return [f"integer(8) :: out({self.total()})",
                *decl_lines("integer", [f"i{k}" for k in range(1, d + 1)],
                            self.o.width), "integer :: lin"]

    def _lin(self):
        ext = self.p["ext"]
        terms, stride = [], 1
        for k in range(len(ext), 0, -1):
            terms.append(f"(i{k} - 1) * {stride}" if stride > 1
                         else f"(i{k} - 1)")
            stride *= ext[k - 1]
        return " + ".join(reversed(terms)) + " + 1"

    def _lin_lines(self, ind, expr):
        lin = self._lin().split(" + ")
        terms = expr.split(" + ")
        return pack("lin =", [t + (" +" if k < len(lin) - 1 else "")
                              for k, t in enumerate(lin)], ind, None,
                    self.o.width) + \
            pack("out(lin) =", [t + (" +" if k < len(terms) - 1 else "")
                                for k, t in enumerate(terms)], ind, None,
                 self.o.width)

    def body(self):
        d, ext, w, c0 = (self.p["depth"], self.p["ext"], self.p["w"],
                         self.p["c0"])
        col = self.p["collapse"]
        ind = "    "
        lines = [f"{ind}out = 0"]
        priv = [f"i{k}" for k in range(col + 1, d + 1)] + ["lin"]
        expr = " + ".join(f"i{k} * {w[k - 1]}" for k in range(1, d + 1)) + \
            f" + {c0}"
        if self.p["split"] and self.o.model == "omp":
            # teams distribute over i1; parallel do collapse over the rest
            # (up to the collapse depth); simd on nothing (bodies index out)
            inner_col = max(1, min(col, d - 1))
            op1, cl1, i1 = region(self.o, ("target teams distribute",), ind,
                                  data=[("out", "tofrom")])
            lines += op1 + [f"{i1}do i1 = 1, {ext[0]}"]
            inner_priv = [f"i{k}" for k in range(2 + inner_col, d + 1)] + \
                ["lin"]
            op2, cl2, i2 = region(self.o, ("parallel do",), i1 + "  ",
                                  private=inner_priv, collapse=inner_col)
            lines += op2
            def at(k):     # indentation, capped (deep nests stay < 132)
                return i2 + "  " * min(k - 2, 16)
            for k in range(2, d + 1):
                lines.append(f"{at(k)}do i{k} = 1, {ext[k - 1]}")
            lines += self._lin_lines(at(d + 1), expr)
            for k in range(d, 1, -1):
                lines.append(f"{at(k)}end do")
            lines += cl2 + [f"{i1}end do"] + cl1
        else:
            chain = ("target teams distribute parallel do",) if \
                self.o.model == "omp" else ("parallel loop gang vector",)
            op, cl, ii = region(self.o, chain, ind, data=[("out", "tofrom")],
                                private=priv, collapse=col)
            lines += op

            def at(k):
                return ii + "  " * min(k - 1, 16)
            for k in range(1, d + 1):
                lines.append(f"{at(k)}do i{k} = 1, {ext[k - 1]}")
            lines += self._lin_lines(at(d + 1), expr)
            for k in range(d, 0, -1):
                lines.append(f"{at(k)}end do")
            lines += cl
        lines.append(f"{ind}call st_cksum(out, {self.total()}, cs)")
        return lines

    def value(self):
        import itertools
        ext, w, c0 = self.p["ext"], self.p["w"], self.p["c0"]
        out = [0] * self.total()
        for idx in itertools.product(*[range(1, e + 1) for e in ext]):
            lin, stride = 0, 1
            for k in range(len(ext) - 1, -1, -1):
                lin += (idx[k] - 1) * stride
                stride *= ext[k]
            out[lin] = sum(i * wk for i, wk in zip(idx, w)) + c0
        return cksum(out)

    def smaller(self):
        d = self.p["depth"]
        out = []
        if d > 1:
            out.append(self.clone(depth=d - 1, ext=self.p["ext"][:-1],
                                  w=self.p["w"][:-1],
                                  collapse=min(self.p["collapse"], d - 1),
                                  split=self.p["split"] and d - 1 >= 3))
        if self.p["collapse"] > 1:
            out.append(self.clone(collapse=1))
        if self.p["split"]:
            out.append(self.clone(split=False))
        if any(e > 2 for e in self.p["ext"]):
            out.append(self.clone(ext=[min(2, e) for e in self.p["ext"]]))
        return out

    def features(self):
        f = super().features() | {f"nest:depth{self.p['depth']}",
                                  f"nest:collapse{self.p['collapse']}"}
        if self.p["collapse"] == self.p["depth"]:
            f.add("nest:collapse_full")
        if self.p["split"]:
            f.add("nest:split")
        return f


def _item_count(size: int) -> int:
    return max(1, int(size))


class ListKernel(Kernel):
    """Base of the list axes: `nitems` items, `n` iterations (n * items is
    kept below 2e5 so the model stays fast)."""
    kind = "list"

    def draw(self, rng):
        k = self.p.setdefault("nitems", 8)
        self.p.setdefault("n", max(8, min(256, 200000 // max(1, k))))
        self.p.setdefault("chain", rng.randrange(3))
        self.p.setdefault("c", [rng.randrange(1, 97) for _ in range(k)])

    def items(self, prefix):
        return [vname(prefix, k) for k in range(1, self.p["nitems"] + 1)]

    def smaller(self):
        k = self.p["nitems"]
        out = []
        for m in _halve(k):
            out.append(self.clone(nitems=m, c=self.p["c"][:m]))
        if self.p["n"] > 8:
            out.append(self.clone(n=8))
        return out

    def chain(self):
        if self.o.model == "omp":
            return (("target teams distribute parallel do",),
                    ("target parallel do",),
                    ("target", "teams distribute parallel do"))[
                self.p["chain"] % 3]
        return (("parallel loop gang vector",), ("parallel loop",),
                ("parallel", "loop gang vector"))[self.p["chain"] % 3]

    def features(self):
        return super().features() | {
            f"list:{self.kind}", f"len:{self.kind}:{self.p['nitems']}"}


class PrivateKernel(ListKernel):
    """private(p0001, ..., pN): each iteration sets every p_j and sums
    them (a shared p_j would race)."""
    kind = "private"

    def decls(self):
        n = self.p["n"]
        its = self.items("p")
        return [f"integer(8) :: out({n})", "integer :: i", "integer(8) :: t"] \
            + [ln.strip() for ln in pack("integer(8) ::",
                                         [x + ("," if k < len(its) - 1 else "")
                                          for k, x in enumerate(its)], "",
                                         None, self.o.width)]

    def body(self):
        n, c = self.p["n"], self.p["c"]
        its = self.items("p")
        ind = "    "
        lines = [f"{ind}out = 0"]
        op, cl, ii = region(self.o, self.chain(), ind,
                            data=[("out", "tofrom")], private=its + ["t"])
        lines += op + [f"{ii}do i = 1, {n}"]
        for k, x in enumerate(its):
            lines.append(f"{ii}  {x} = mod(i * {c[k]} + {k + 1}, 997)")
        lines.append(f"{ii}  t = 0")
        lines += sum_lines(ii + "  ", "t", its, self.o.width)
        lines += [f"{ii}  out(i) = t", f"{ii}end do"] + cl
        lines.append(f"{ind}call st_cksum(out, {n}, cs)")
        return lines

    def value(self):
        n, c = self.p["n"], self.p["c"]
        k = self.p["nitems"]
        return cksum(sum((i * c[j] + j + 1) % 997 for j in range(k))
                     for i in range(1, n + 1))


class FirstprivateKernel(ListKernel):
    """firstprivate(f0001, ..., fN) of host-initialised scalars; the device
    reads each; the host values must be unchanged afterwards."""
    kind = "firstprivate"

    def decls(self):
        n = self.p["n"]
        its = self.items("f")
        return [f"integer(8) :: out({n})", "integer :: i", "integer(8) :: t"] \
            + [ln.strip() for ln in pack("integer(8) ::",
                                         [x + ("," if k < len(its) - 1 else "")
                                          for k, x in enumerate(its)], "",
                                         None, self.o.width)]

    def body(self):
        n, c = self.p["n"], self.p["c"]
        its = self.items("f")
        ind = "    "
        lines = [f"{ind}{x} = {c[k] * 7 + k}" for k, x in enumerate(its)]
        lines.append(f"{ind}out = 0")
        op, cl, ii = region(self.o, self.chain(), ind,
                            data=[("out", "tofrom")], private=["t"],
                            firstprivate=its)
        lines += op + [f"{ii}do i = 1, {n}", f"{ii}  t = 0"]
        terms = [f"{x} * mod(i + {k}, 3)" for k, x in enumerate(its)]
        lines += sum_lines(ii + "  ", "t", terms, self.o.width)
        lines += [f"{ii}  out(i) = t", f"{ii}end do"] + cl
        lines.append(f"{ind}call st_cksum(out, {n}, cs)")
        lines.append(f"{ind}t = 0")
        lines += sum_lines(ind, "t", its, self.o.width)
        lines.append(f"{ind}cs = mod(cs + t, {P}_8)")
        return lines

    def value(self):
        n, c = self.p["n"], self.p["c"]
        k = self.p["nitems"]
        f = [c[j] * 7 + j for j in range(k)]
        cs = cksum(sum(f[j] * ((i + j) % 3) for j in range(k))
                   for i in range(1, n + 1))
        return (cs + sum(f)) % P


class LastprivateKernel(ListKernel):
    """lastprivate(l0001, ..., lN): after the loop l_j holds the value of
    the sequentially last iteration, n * c_j + j."""
    kind = "lastprivate"

    def decls(self):
        its = self.items("l")
        return ["integer :: i", "integer(8) :: t"] + \
            [ln.strip() for ln in pack("integer(8) ::",
                                       [x + ("," if k < len(its) - 1 else "")
                                        for k, x in enumerate(its)], "",
                                       None, self.o.width)]

    def chain(self):
        if self.o.model == "omp":
            # lastprivate on a combined target construct: the list item is
            # treated as if it also appeared in map(tofrom) (5.0 §2.19.7.1)
            return (("target teams distribute parallel do",),
                    ("target parallel do",),
                    ("target parallel do",))[self.p["chain"] % 3]
        raise ValueError("OpenACC has no lastprivate clause")

    def body(self):
        n, c = self.p["n"], self.p["c"]
        its = self.items("l")
        ind = "    "
        lines = [f"{ind}{x} = 0" for x in its]
        op, cl, ii = region(self.o, self.chain()[:1], ind,
                            loop_extra=list_atoms("lastprivate", its))
        lines += op + [f"{ii}do i = 1, {n}"]
        for k, x in enumerate(its):
            lines.append(f"{ii}  {x} = i * {c[k]} + {k}")
        lines += [f"{ii}end do"] + cl
        lines.append(f"{ind}t = 0")
        lines += sum_lines(ind, "t", its, self.o.width)
        lines.append(f"{ind}cs = mod(t, {P}_8)")
        return lines

    def value(self):
        n, c = self.p["n"], self.p["c"]
        return sum(n * c[j] + j for j in range(self.p["nitems"])) % P


class SharedKernel(ListKernel):
    """target data region; inside, ``parallel do shared(s0001..sN, out)``
    nested in a target region (shared is a parallel / teams clause): the
    shared scalars are read by every thread."""
    kind = "shared"

    def decls(self):
        n = self.p["n"]
        its = self.items("s")
        return [f"integer(8) :: out({n})", "integer :: i", "integer(8) :: t"] \
            + [ln.strip() for ln in pack("integer(8) ::",
                                         [x + ("," if k < len(its) - 1 else "")
                                          for k, x in enumerate(its)], "",
                                         None, self.o.width)]

    def body(self):
        n, c = self.p["n"], self.p["c"]
        its = self.items("s")
        ind = "    "
        lines = [f"{ind}{x} = {c[k] + k}" for k, x in enumerate(its)]
        lines.append(f"{ind}out = 0")
        if self.o.model == "omp":
            op1 = pack("target", data_clauses(self.o, [(x, "to") for x in
                                                       its] +
                                              [("out", "tofrom")]),
                       ind, self.o.sent, self.o.width)
            op2 = pack("parallel do", list_atoms("shared", its + ["out"]) +
                       list_atoms("private", ["t"]), ind + "  ",
                       self.o.sent, self.o.width)
            ii = ind + "    "
            lines += op1 + op2 + [f"{ii}do i = 1, {n}", f"{ii}  t = 0"]
            terms = [f"{x} * mod(i, {k + 2})" for k, x in enumerate(its)]
            lines += sum_lines(ii + "  ", "t", terms, self.o.width)
            lines += [f"{ii}  out(i) = t", f"{ii}end do",
                      f"{ind}  {self.o.sent} end parallel do",
                      f"{ind}{self.o.sent} end target"]
        else:
            op, cl, ii = region(self.o, ("parallel loop",), ind,
                                data=[(x, "to") for x in its] +
                                [("out", "tofrom")], private=["t"])
            lines += op + [f"{ii}do i = 1, {n}", f"{ii}  t = 0"]
            terms = [f"{x} * mod(i, {k + 2})" for k, x in enumerate(its)]
            lines += sum_lines(ii + "  ", "t", terms, self.o.width)
            lines += [f"{ii}  out(i) = t", f"{ii}end do"] + cl
        lines.append(f"{ind}call st_cksum(out, {n}, cs)")
        return lines

    def value(self):
        n, c = self.p["n"], self.p["c"]
        k = self.p["nitems"]
        s = [c[j] + j for j in range(k)]
        return cksum(sum(s[j] * (i % (j + 2)) for j in range(k))
                     for i in range(1, n + 1))


class MapKernel(ListKernel):
    """map(to: a0001..aN) map(tofrom: b0001..bN): N arrays of m elements;
    b_j(i) = b_j(i) + a_j(i) * c_j."""
    kind = "map"

    def draw(self, rng):
        k = self.p.setdefault("nitems", 8)
        self.p.setdefault("m", max(4, min(64, 100000 // max(1, k))))
        self.p.setdefault("n", self.p["m"])
        self.p.setdefault("chain", rng.randrange(3))
        self.p.setdefault("c", [rng.randrange(1, 97) for _ in range(k)])

    def decls(self):
        m = self.p["m"]
        its_a, its_b = self.items("a"), self.items("b")
        ents = [f"{x}({m})" for x in its_a + its_b]
        return ["integer :: i", "integer(8) :: t"] + \
            [ln.strip() for ln in pack("integer(8) ::",
                                       [x + ("," if k < len(ents) - 1 else "")
                                        for k, x in enumerate(ents)], "",
                                       None, self.o.width)]

    def body(self):
        m, c = self.p["m"], self.p["c"]
        A, B = self.items("a"), self.items("b")
        ind = "    "
        lines = [f"{ind}do i = 1, {m}"]
        for k in range(len(A)):
            lines.append(f"{ind}  {A[k]}(i) = mod(i * {k + 3}, 101)")
            lines.append(f"{ind}  {B[k]}(i) = {k}")
        lines.append(f"{ind}end do")
        op, cl, ii = region(self.o, self.chain(), ind,
                            data=[(x, "to") for x in A] +
                            [(x, "tofrom") for x in B])
        lines += op + [f"{ii}do i = 1, {m}"]
        for k in range(len(A)):
            lines.append(f"{ii}  {B[k]}(i) = {B[k]}(i) + {A[k]}(i) * {c[k]}")
        lines += [f"{ii}end do"] + cl
        lines.append(f"{ind}cs = 0")
        for k in range(len(B)):
            lines.append(f"{ind}call st_cksum({B[k]}, {m}, t)")
            lines.append(f"{ind}cs = mod(cs * 31 + t, {P}_8)")
        return lines

    def value(self):
        m, c = self.p["m"], self.p["c"]
        cs = 0
        for k in range(self.p["nitems"]):
            t = cksum(k + ((i * (k + 3)) % 101) * c[k]
                      for i in range(1, m + 1))
            cs = (cs * 31 + t) % P
        return cs

    def smaller(self):
        k = self.p["nitems"]
        return [self.clone(nitems=m, c=self.p["c"][:m]) for m in _halve(k)] \
            + ([self.clone(m=4, n=4)] if self.p["m"] > 4 else [])


RED_OPS = ("+", "*", "max", "min", "iand", "ior", "ieor")


class ReductionKernel(ListKernel):
    """reduction clauses over r0001..rN with operators cycling through
    + * max min iand ior ieor (one clause per operator); * multiplies by 2
    on 3 iterations only (bounded)."""
    kind = "reduction"

    def draw(self, rng):
        super().draw(rng)
        self.p.setdefault("ops", [RED_OPS[(j + rng.randrange(7)) % 7]
                                  for j in range(self.p["nitems"])])

    def decls(self):
        its = self.items("r")
        return ["integer :: i", "integer(8) :: t"] + \
            [ln.strip() for ln in pack("integer(8) ::",
                                       [x + ("," if k < len(its) - 1 else "")
                                        for k, x in enumerate(its)], "",
                                       None, self.o.width)]

    def init(self, op, k):
        return {"+": k, "*": 1, "max": 0, "min": 1000000, "iand": 1048575,
                "ior": 0, "ieor": k}[op]

    def contrib(self, op, i, k, c):
        if op == "*":
            return f"merge(2_8, 1_8, mod(i, {max(1, self.p['n'] // 3)}) == 0" \
                f" .and. i <= {3 * max(1, self.p['n'] // 3)})"
        return f"int(mod(i * {c} + {k}, 65536), 8)"

    def body(self):
        n, c, ops = self.p["n"], self.p["c"], self.p["ops"]
        its = self.items("r")
        ind = "    "
        lines = [f"{ind}{x} = {self.init(ops[k], k)}"
                 for k, x in enumerate(its)]
        groups: dict[str, list[str]] = {}
        for k, x in enumerate(its):
            groups.setdefault(ops[k], []).append(x)
        red = [(op, groups[op]) for op in RED_OPS if op in groups]
        op_, cl, ii = region(self.o, self.chain(), ind, reduction=red)
        lines += op_ + [f"{ii}do i = 1, {n}"]
        for k, x in enumerate(its):
            e = self.contrib(ops[k], None, k, c[k])
            stmt = {"+": f"{x} = {x} + {e}", "*": f"{x} = {x} * {e}",
                    "max": f"{x} = max({x}, {e})",
                    "min": f"{x} = min({x}, {e})",
                    "iand": f"{x} = iand({x}, {e} + 1048576_8 - 65536_8)",
                    "ior": f"{x} = ior({x}, {e})",
                    "ieor": f"{x} = ieor({x}, {e})"}[ops[k]]
            lines.append(f"{ii}  {stmt}")
        lines += [f"{ii}end do"] + cl
        lines.append(f"{ind}cs = 0")
        for x in its:
            lines.append(f"{ind}cs = mod(cs * 31 + mod({x}, {P}_8), {P}_8)")
        return lines

    def value(self):
        n, c, ops = self.p["n"], self.p["c"], self.p["ops"]
        cs = 0
        step = max(1, n // 3)
        for k in range(self.p["nitems"]):
            op = ops[k]
            v = self.init(op, k)
            for i in range(1, n + 1):
                e = (i * c[k] + k) % 65536
                if op == "+":
                    v += e
                elif op == "*":
                    v *= 2 if (i % step == 0 and i <= 3 * step) else 1
                elif op == "max":
                    v = max(v, e)
                elif op == "min":
                    v = min(v, e)
                elif op == "iand":
                    v &= e + 1048576 - 65536
                elif op == "ior":
                    v |= e
                else:
                    v ^= e
                chk(v)
            cs = (cs * 31 + v % P) % P
        return cs

    def smaller(self):
        out = super().smaller()
        for k in out:
            if "ops" in k.p:
                k.p["ops"] = self.p["ops"][:k.p["nitems"]]
        return out

    def features(self):
        return super().features() | {f"red:{op}" for op in self.p["ops"]}


class DependKernel(ListKernel):
    """T target tasks (nowait) each with depend(inout: d0001..dN) on N
    scalars and map(tofrom: x); the dependences serialize them; taskwait.
    OpenACC: the async queue chain (async(q) wait(q-1)) over N queues."""
    kind = "depend"

    def draw(self, rng):
        super().draw(rng)
        self.p.setdefault("tasks", 6)

    def decls(self):
        its = self.items("d")
        return ["integer(8) :: x(4)", "integer :: t"] + \
            [ln.strip() for ln in pack("integer(8) ::",
                                       [x + ("," if k < len(its) - 1 else "")
                                        for k, x in enumerate(its)], "",
                                       None, self.o.width)]

    def body(self):
        its = self.items("d")
        T = self.p["tasks"]
        ind = "    "
        lines = [f"{ind}{x} = 0" for x in its] + [f"{ind}x = 1"]
        if self.o.model == "omp":
            lines.append(f"{ind}do t = 1, {T}")
            lines += pack("target", ["map(tofrom: x)", "nowait"] +
                          list_atoms("depend", its, "inout"),
                          ind + "  ", self.o.sent, self.o.width)
            lines += [f"{ind}    x(1) = mod(x(1) * 3 + t, 1000003_8)",
                      f"{ind}    x(2) = x(1) + t",
                      f"{ind}  {self.o.sent} end target", f"{ind}end do",
                      f"{ind}{self.o.sent} taskwait"]
        else:
            q = len(its)
            lines += [f"{ind}{self.o.sent} enter data copyin(x)",
                      f"{ind}do t = 1, {T}"]
            lines += [f"{ind}  {self.o.sent} serial present(x) "
                      f"async(mod(t - 1, {q}) + 1) "
                      f"wait(mod(t + {q} - 2, {q}) + 1)",
                      f"{ind}    x(1) = mod(x(1) * 3 + t, 1000003_8)",
                      f"{ind}    x(2) = x(1) + t",
                      f"{ind}  {self.o.sent} end serial", f"{ind}end do",
                      f"{ind}{self.o.sent} wait",
                      f"{ind}{self.o.sent} exit data copyout(x)"]
        lines.append(f"{ind}call st_cksum(x, 4, cs)")
        return lines

    def value(self):
        x = [1, 1, 1, 1]
        for t in range(1, self.p["tasks"] + 1):
            x[0] = (x[0] * 3 + t) % 1000003
            x[1] = x[0] + t
        return cksum(x)


class UDRKernel(ListKernel):
    """A reduction list mixing intrinsic operators with user-defined
    reductions (declare reduction, OpenMP 5.2 §5.5.11): variables cycle
    through +, max, ieor and two user-defined identifiers (a sum and a
    max with an initializer)."""
    kind = "udr"
    OPS = ("+", "max", "ieor", "st_add", "st_max")

    def decls(self):
        its = self.items("u")
        return ["integer :: i", "integer(8) :: t",
                "!$omp declare reduction(st_add: integer(8): omp_out = "
                "omp_out + omp_in) initializer(omp_priv = 0_8)",
                "!$omp declare reduction(st_max: integer(8): omp_out = "
                "max(omp_out, omp_in)) initializer(omp_priv = -1_8)"] + \
            decl_lines("integer(8)", its, self.o.width)

    def body(self):
        n, c = self.p["n"], self.p["c"]
        its = self.items("u")
        ops = [self.OPS[j % 5] for j in range(len(its))]
        ind = "    "
        lines = [f"{ind}{x} = {j}" for j, x in enumerate(its)]
        groups: dict[str, list[str]] = {}
        for x, op in zip(its, ops):
            groups.setdefault(op, []).append(x)
        red = [(op, groups[op]) for op in self.OPS if op in groups]
        op_, cl, ii = region(self.o, self.chain(), ind, reduction=red)
        lines += op_ + [f"{ii}do i = 1, {n}"]
        for j, (x, op) in enumerate(zip(its, ops)):
            e = f"int(mod(i * {c[j]} + {j}, 65536), 8)"
            lines.append(f"{ii}  {x} = " + {
                "+": f"{x} + {e}", "st_add": f"{x} + {e}",
                "max": f"max({x}, {e})", "st_max": f"max({x}, {e})",
                "ieor": f"ieor({x}, {e})"}[op])
        lines += [f"{ii}end do"] + cl
        lines.append(f"{ind}cs = 0")
        for x in its:
            lines.append(f"{ind}cs = mod(cs * 31 + mod({x}, {P}_8), {P}_8)")
        return lines

    def value(self):
        n, c = self.p["n"], self.p["c"]
        cs = 0
        for j in range(self.p["nitems"]):
            op = self.OPS[j % 5]
            v = j
            for i in range(1, n + 1):
                e = (i * c[j] + j) % 65536
                v = v + e if op in ("+", "st_add") else max(v, e) \
                    if op in ("max", "st_max") else v ^ e
            cs = (cs * 31 + v % P) % P
        return cs

    def chain(self):
        return (("target teams distribute parallel do",),
                ("target parallel do",),
                ("target teams distribute parallel do",))[
            self.p["chain"] % 3]


class DeclareKernel(ListKernel):
    """N module variables made device resident (declare target / acc
    declare create) in the kernel's own module; host sets them, target
    update to, the region reads them all and writes w; update from."""
    kind = "declare"

    def mod(self):
        return f"{self.name}_m"

    def modules(self):
        its = self.items("v")
        spec = [ln.strip() for ln in pack(
            "integer(8) ::", [x + ("," if k < len(its) - 1 else "")
                              for k, x in enumerate(its)], "", None,
            self.o.width)]
        spec.append(f"integer(8) :: w({self.p['n']})")
        if self.o.model == "omp":
            dl = pack("declare target(", [x + ("," if k < len(its) else ")")
                                          for k, x in enumerate(its + ["w"])],
                      "", self.o.sent, self.o.width)
        else:
            dl = pack("declare", list_atoms("create", its + ["w"]), "",
                      self.o.sent, self.o.width)
        return [Module(self.mod(), spec + dl)]

    def uses(self):
        return [self.mod()]

    def decls(self):
        return ["integer :: i", "integer(8) :: t"]

    def body(self):
        n, c = self.p["n"], self.p["c"]
        its = self.items("v")
        ind = "    "
        lines = [f"{ind}{x} = {c[k] * 3 + k}" for k, x in enumerate(its)]
        lines.append(f"{ind}w = 0")
        if self.o.model == "omp":
            lines += pack("target update", list_atoms("to", its + ["w"]),
                          ind, self.o.sent, self.o.width)
            op, cl, ii = region(self.o, ("target teams distribute parallel "
                                         "do",), ind, private=["t"])
        else:
            lines += pack("update", list_atoms("device", its + ["w"]), ind,
                          self.o.sent, self.o.width)
            op, cl, ii = region(self.o, ("parallel loop",), ind,
                                private=["t"], extra=["default(present)"])
        lines += op + [f"{ii}do i = 1, {n}", f"{ii}  t = 0"]
        terms = [f"{x} * mod(i, {k % 5 + 2})" for k, x in enumerate(its)]
        lines += sum_lines(ii + "  ", "t", terms, self.o.width)
        lines += [f"{ii}  w(i) = t", f"{ii}end do"] + cl
        if self.o.model == "omp":
            lines.append(f"{ind}{self.o.sent} target update from(w)")
        else:
            lines.append(f"{ind}{self.o.sent} update self(w)")
        lines.append(f"{ind}call st_cksum(w, {n}, cs)")
        return lines

    def value(self):
        n, c = self.p["n"], self.p["c"]
        v = [c[k] * 3 + k for k in range(self.p["nitems"])]
        return cksum(sum(v[k] * (i % (k % 5 + 2)) for k in range(len(v)))
                     for i in range(1, n + 1))


class SectionsKernel(ListKernel):
    """Many array sections of one array: x is entered whole (enter data),
    then a target region maps N disjoint sections x(lo:hi) (present, so
    they refer to the same storage: 5.2 §5.8.3 p.155) and a target update
    to of a strided section x(1:m:2) (5.2 §5.9 p.164)."""
    kind = "sections"

    def draw(self, rng):
        k = self.p.setdefault("nitems", 8)
        self.p.setdefault("w", 4)          # elements per section
        self.p.setdefault("n", k * self.p["w"])
        self.p.setdefault("chain", 0)
        self.p.setdefault("c", [rng.randrange(1, 97) for _ in range(k)])

    def decls(self):
        return [f"integer(8) :: x({self.p['n']})", "integer :: i"]

    def body(self):
        n, w = self.p["n"], self.p["w"]
        k = self.p["nitems"]
        ind = "    "
        secs = [f"x({j * w + 1}:{(j + 1) * w})" for j in range(k)]
        lines = [f"{ind}do i = 1, {n}", f"{ind}  x(i) = i", f"{ind}end do"]
        if self.o.model == "omp":
            lines.append(f"{ind}{self.o.sent} target enter data map(to: x)")
            lines.append(f"{ind}do i = 1, {n}, 2")
            lines.append(f"{ind}  x(i) = x(i) + 1000")
            lines.append(f"{ind}end do")
            lines.append(f"{ind}{self.o.sent} target update to(x(1:{n}:2))")
            op, cl, ii = region(self.o, ("target teams distribute parallel "
                                         "do",), ind,
                                data=[(s, "tofrom") for s in secs])
            lines += op + [f"{ii}do i = 1, {n}",
                           f"{ii}  x(i) = x(i) * 3 + mod(i, 7)",
                           f"{ii}end do"] + cl
            lines.append(f"{ind}{self.o.sent} target exit data map(from: x)")
        else:
            lines.append(f"{ind}{self.o.sent} enter data copyin(x)")
            lines.append(f"{ind}do i = 1, {n}, 2")
            lines.append(f"{ind}  x(i) = x(i) + 1000")
            lines.append(f"{ind}end do")
            lines.append(f"{ind}{self.o.sent} update device(x(1:{n}:2))")
            op, cl, ii = region(self.o, ("parallel loop",), ind,
                                extra=list_atoms("present", secs))
            lines += op + [f"{ii}do i = 1, {n}",
                           f"{ii}  x(i) = x(i) * 3 + mod(i, 7)",
                           f"{ii}end do"] + cl
            lines.append(f"{ind}{self.o.sent} exit data copyout(x)")
        lines.append(f"{ind}call st_cksum(x, {n}, cs)")
        return lines

    def value(self):
        n = self.p["n"]
        x = [i + (1000 if i % 2 == 1 else 0) for i in range(1, n + 1)]
        return cksum(v * 3 + (i % 7) for i, v in enumerate(x, 1))

    def smaller(self):
        k = self.p["nitems"]
        return [self.clone(nitems=m, n=m * self.p["w"], c=self.p["c"][:m])
                for m in _halve(k)]


# --- calls, clauses, continuation lines, names --------------------------------------------------

def _dt_line(o: Opts, ind: str = "    ") -> str:
    """The device-routine marker in a procedure's specification part."""
    return f"{ind}{o.sent} declare target" if o.model == "omp" else \
        f"{ind}{o.sent} routine seq"


class CallsKernel(Kernel):
    """A device call chain `depth` levels deep in the kernel's module:
    f_1(x) = f_2(mod(x*3, 1009) + 1) + 1, ..., f_D(x) = x + D; out(i) =
    f_1(i); optionally a RECURSIVE device function rsum(m) = m + rsum(m-1)
    (no specification forbids recursion in a device routine; 5.2 §7.8,
    OpenACC 3.4 §2.15.1)."""
    kind = "calls"

    def draw(self, rng):
        self.p.setdefault("depth", 5)
        self.p.setdefault("n", 512)
        self.p.setdefault("recursive", rng.random() < 0.3)
        self.p.setdefault("rdepth", 12)

    def fname(self, k):
        return f"{self.name}_f{k}"

    def modules(self):
        d = self.p["depth"]
        cont = []
        for k in range(1, d + 1):
            cont += [f"  function {self.fname(k)}(x) result(r)",
                     _dt_line(self.o), "    integer(8), intent(in) :: x",
                     "    integer(8) :: r"]
            if k < d:
                cont.append(f"    r = {self.fname(k + 1)}(mod(x * 3, 1009_8) "
                            "+ 1) + 1")
            else:
                cont.append(f"    r = x + {d}")
            cont.append(f"  end function {self.fname(k)}")
        if self.p["recursive"]:
            cont += [f"  recursive function {self.name}_rs(m) result(r)",
                     _dt_line(self.o), "    integer(8), intent(in) :: m",
                     "    integer(8) :: r", "    if (m <= 0) then",
                     "      r = 0", "    else",
                     f"      r = m + {self.name}_rs(m - 1)", "    end if",
                     f"  end function {self.name}_rs"]
        return [Module(f"{self.name}_m", [], cont)]

    def uses(self):
        return [f"{self.name}_m"]

    def decls(self):
        return [f"integer(8) :: out({self.p['n']})", "integer :: i"]

    def body(self):
        n = self.p["n"]
        ind = "    "
        chain = ("target teams distribute parallel do",) if \
            self.o.model == "omp" else ("parallel loop gang vector",)
        op, cl, ii = region(self.o, chain, ind, data=[("out", "tofrom")])
        e = f"{self.fname(1)}(int(i, 8))"
        if self.p["recursive"]:
            e += f" + {self.name}_rs(int(mod(i, {self.p['rdepth']}), 8))"
        lines = [f"{ind}out = 0"] + op + [f"{ii}do i = 1, {n}",
                                          f"{ii}  out(i) = {e}",
                                          f"{ii}end do"] + cl
        lines.append(f"{ind}call st_cksum(out, {n}, cs)")
        return lines

    def f(self, x):
        d = self.p["depth"]
        add = 0
        for k in range(1, d):
            x = (x * 3) % 1009 + 1
            add += 1
        return x + d + add

    def value(self):
        n, rd = self.p["n"], self.p["rdepth"]
        vals = []
        for i in range(1, n + 1):
            v = self.f(i)
            if self.p["recursive"]:
                m = i % rd
                v += m * (m + 1) // 2
            vals.append(v)
        return cksum(vals)

    def smaller(self):
        out = [self.clone(depth=m) for m in _halve(self.p["depth"])]
        if self.p["recursive"]:
            out.append(self.clone(recursive=False))
        if self.p["n"] > 8:
            out.append(self.clone(n=8))
        return out

    def features(self):
        f = super().features() | {f"calls:depth{self.p['depth']}"}
        if self.p["recursive"]:
            f.add("calls:recursive")
        return f


# fillable clauses of target teams distribute parallel do simd (5.0
# spellings), in the order the clauses axis adds them; each: atoms,
# declarations, setup (host, before), teardown (host, after)
CLAUSE_ORDER = ("map", "private", "firstprivate", "reduction", "collapse",
                "lastprivate", "shared", "default", "defaultmap", "if",
                "device", "num_teams", "thread_limit", "num_threads",
                "dist_schedule", "schedule", "proc_bind", "safelen",
                "simdlen", "nontemporal", "nowait", "depend",
                "allocate", "uses_allocators", "in_reduction",
                "is_device_ptr")
REPEATABLE = ("map", "private", "firstprivate", "reduction", "shared")
NOT_FILLED = {
    "aligned": "an alignment the program cannot guarantee portably "
               "(a false aligned clause is unspecified behaviour)",
    "has_device_addr": "5.1; the program keeps 5.0 spellings for NVHPC",
    "linear": "on a compound with a distribute leaf only loop iteration "
              "variables may be linear (5.0 §2.9.4.2 p.124), and with "
              "collapse(2) they are lastprivate",
    "order": "order(concurrent) excludes safelen on the simd leaf (5.2 "
             "§10.4 p.235); safelen is kept",
}


class ClausesKernel(Kernel):
    """`size` clauses on one target teams distribute parallel do simd
    directive: the catalog's allowed clauses in CLAUSE_ORDER, then repeats
    of the repeatable ones (each repeat with its own variables). The loop
    is a 2-deep nest (collapse(2)); out(lin) = i*j + fp + sh."""
    kind = "clauses"

    def draw(self, rng):
        self.p.setdefault("nclauses", 8)
        self.p.setdefault("ni", 16)
        self.p.setdefault("nj", 8)

    def plan(self) -> list[tuple[str, int]]:
        from offload.engine.fuzz import allowed_clauses
        allowed = allowed_clauses("target teams distribute parallel do simd")
        base = [c for c in CLAUSE_ORDER if c in allowed]
        k = self.p["nclauses"]
        out = [(c, 0) for c in base[:k]]
        r = 1
        while len(out) < k:
            for c in REPEATABLE:
                if len(out) >= k:
                    break
                out.append((c, r))
            r += 1
        return out

    def decls(self):
        ni, nj = self.p["ni"], self.p["nj"]
        n = ni * nj
        d = [f"integer(8) :: out({n}), a({n})", "integer :: i, j, lin",
             "integer(8) :: tp, fp, rs, lp, sh, lk, ir, dd",
             "logical :: lt", "integer(8) :: tq"]
        reps = [r for c, r in self.plan() if r]
        for c, r in self.plan():
            if r:
                d.append(f"integer(8) :: {c[:2]}{r:04d}")
        if any(c == "is_device_ptr" for c, _ in self.plan()):
            d += ["type(c_ptr) :: cp", "integer(8), pointer :: fpp(:)",
                  "integer(8), target :: hcopy(4)", "integer :: rc"]
        del reps
        return d

    def uses(self):
        u = []
        if self.o.model == "omp":
            u.append("omp_lib")
        if any(c == "is_device_ptr" for c, _ in self.plan()):
            u.append("iso_c_binding")
        return u

    def body(self):
        ni, nj = self.p["ni"], self.p["nj"]
        n = ni * nj
        plan = self.plan()
        names = [c for c, _ in plan]
        ind = "    "
        lines = [f"{ind}out = 0", f"{ind}do i = 1, {n}",
                 f"{ind}  a(i) = mod(i * 13, 101)", f"{ind}end do",
                 f"{ind}fp = 7", f"{ind}sh = 5", f"{ind}rs = 0",
                 f"{ind}lp = 0", f"{ind}lk = 0", f"{ind}ir = 0",
                 f"{ind}dd = 0", f"{ind}lt = .true.", f"{ind}tq = 0"]
        for c, r in plan:
            if r:
                v = f"{c[:2]}{r:04d}"
                lines.append(f"{ind}{v} = {r}")
        atoms = []
        body_extra = []
        after = []
        for c, r in plan:
            v = f"{c[:2]}{r:04d}" if r else ""
            if c == "map":
                atoms += (["map(to: a)", "map(tofrom: out)"] if not r
                          else [f"map(tofrom: {v})"])
            elif c == "private":
                # lin (the linear index each iteration computes) is private
                # with the first private clause (fix, F1:
                # it was shared, a data race in every clauses program)
                atoms.append(f"private({v})" if r else "private(tp, lin)")
                body_extra.append(f"{v or 'tp'} = i")
            elif c == "firstprivate":
                atoms.append(f"firstprivate({v or 'fp'})")
            elif c == "reduction":
                atoms.append(f"reduction(+: {v or 'rs'})")
                body_extra.append(f"{v or 'rs'} = {v or 'rs'} + 1")
                if r:
                    after.append(v)
            elif c == "collapse":
                atoms.append("collapse(2)")
            elif c == "lastprivate":
                atoms.append("lastprivate(lp)")
                body_extra.append("lp = lin")
            elif c == "shared":
                atoms.append(f"shared({v or 'sh'})")
            elif c == "default":
                atoms.append("default(shared)")
            elif c == "defaultmap":
                atoms.append("defaultmap(tofrom: scalar)")
            elif c == "if":
                atoms += ["if(target: lt)", "if(parallel: lt)"]
            elif c == "device":
                atoms.append("device(omp_get_default_device())")
            elif c == "num_teams":
                atoms.append("num_teams(4)")
            elif c == "thread_limit":
                atoms.append("thread_limit(64)")
            elif c == "num_threads":
                atoms.append("num_threads(32)")
            elif c == "dist_schedule":
                atoms.append("dist_schedule(static, 4)")
            elif c == "schedule":
                atoms.append("schedule(static, 2)")
            elif c == "proc_bind":
                atoms.append("proc_bind(close)")
            elif c == "safelen":
                atoms.append("safelen(8)")
            elif c == "simdlen":
                atoms.append("simdlen(4)")
            elif c == "nontemporal":
                atoms.append("nontemporal(a)")
            elif c == "order":
                atoms.append("order(concurrent)")
            elif c == "nowait":
                atoms.append("nowait")
            elif c == "depend":
                atoms.append("depend(inout: dd)")
            elif c == "linear":
                atoms.append("linear(lk: 1)")
            elif c == "allocate":
                atoms.append("allocate(omp_default_mem_alloc: tp)")
            elif c == "uses_allocators":
                atoms.append("uses_allocators(omp_default_mem_alloc)")
            elif c == "in_reduction":
                atoms.append("in_reduction(+: ir)")
                body_extra.append("if (lin == 1) ir = ir + 5")
            elif c == "is_device_ptr":
                atoms.append("is_device_ptr(cp)")
        if "private" not in names:
            # lin must be private even when the private clause is not one of
            # the clauses drawn (an extra clause, not counted)
            atoms.append("private(lin)")
        if "allocate" in names and not any(x.startswith("private(tp")
                                           for x in atoms):
            atoms.append("private(tp)")
            body_extra.append("tp = i")
        pre, post = [], []
        if "is_device_ptr" in names:
            pre += [f"{ind}cp = omp_target_alloc(int(4 * 8, c_size_t), "
                    "omp_get_default_device())"]
            body_extra.append("if (lin == 1) then")
            body_extra.append("  call c_f_pointer(cp, fpp, [4])")
            body_extra.append("  fpp(1) = 11")
            body_extra.append("  fpp(2) = 22")
            body_extra.append("  fpp(3) = 33")
            body_extra.append("  fpp(4) = 44")
            body_extra.append("end if")
            post += pack("rc = omp_target_memcpy(", [
                "c_loc(hcopy),", "cp,", "int(4 * 8, c_size_t),",
                "0_c_size_t,", "0_c_size_t,", "omp_get_initial_device(),",
                "omp_get_default_device())"], ind, None, self.o.width) + [
                     f"{ind}call omp_target_free(cp, "
                     "omp_get_default_device())"]
        if "in_reduction" in names:
            pre.append(f"{ind}{self.o.sent} taskgroup task_reduction(+: ir)")
            post.insert(0, f"{ind}{self.o.sent} end taskgroup")
        lines += pre
        dname = "target teams distribute parallel do simd"
        lines += pack(dname, atoms, ind, self.o.sent, self.o.width)
        lines += [f"{ind}do i = 1, {ni}", f"{ind}  do j = 1, {nj}",
                  f"{ind}    lin = (i - 1) * {nj} + j"]
        lines += [f"{ind}    {s}" for s in body_extra]
        lines += [f"{ind}    out(lin) = i * j + fp + sh + a(lin)",
                  f"{ind}  end do", f"{ind}end do",
                  f"{ind}{self.o.sent} end {dname}"]
        if "nowait" in names or "depend" in names:
            lines.append(f"{ind}{self.o.sent} taskwait")
        lines += post
        lines.append(f"{ind}call st_cksum(out, {n}, cs)")
        if "reduction" in names:
            lines.append(f"{ind}cs = mod(cs + rs, {P}_8)")
        for v in after:
            lines.append(f"{ind}cs = mod(cs + {v}, {P}_8)")
        if "lastprivate" in names:
            lines.append(f"{ind}cs = mod(cs + lp, {P}_8)")
        if "in_reduction" in names:
            lines.append(f"{ind}cs = mod(cs + ir, {P}_8)")
        if "is_device_ptr" in names:
            lines.append(f"{ind}cs = mod(cs + hcopy(1) + hcopy(2) + "
                         f"hcopy(3) + hcopy(4), {P}_8)")
        return lines

    def value(self):
        ni, nj = self.p["ni"], self.p["nj"]
        n = ni * nj
        plan = self.plan()
        names = [c for c, _ in plan]
        out = []
        for i in range(1, ni + 1):
            for j in range(1, nj + 1):
                lin = (i - 1) * nj + j
                out.append(i * j + 7 + 5 + (lin * 13) % 101)
        cs = cksum(out)
        if "reduction" in names:
            cs = (cs + n) % P
        for c, r in plan:
            if r and c == "reduction":
                cs = (cs + r + n) % P
        if "lastprivate" in names:
            cs = (cs + n) % P
        if "in_reduction" in names:
            cs = (cs + 5) % P
        if "is_device_ptr" in names:
            cs = (cs + 110) % P
        return cs

    def smaller(self):
        k = self.p["nclauses"]
        return [self.clone(nclauses=m) for m in _halve(k)] + \
            ([self.clone(nclauses=k - 1)] if k > 2 else [])

    def features(self):
        return super().features() | {f"clause:{c}" for c, _ in self.plan()} \
            | {f"len:clauses:{self.p['nclauses']}"}


class ContKernel(PrivateKernel):
    """One directive spanning `nitems` continuation lines: the private list
    one item per line (PrivateKernel's program with width 1 for the
    directive)."""
    kind = "contlines"

    def body(self):
        o = self.o
        saved = o.width
        try:
            self.o = Opts(o.model, o.spell, o.level, width=1)
            lines = super().body()
        finally:
            self.o = Opts(o.model, o.spell, o.level, width=saved)
        return lines


def long_name(prefix: str, k: int, length: int) -> str:
    base = f"{prefix}{k}_"
    return (base + "x" * max(0, length - len(base)))[:max(length, len(base))]


class NamesKernel(Kernel):
    """Names of exactly `length` characters: the kernel's module, a device
    function, a derived type and its component, and `count` variables in a
    private list (63 is the Fortran limit; longer: an illegal probe)."""
    kind = "names"

    def draw(self, rng):
        self.p.setdefault("length", 63)
        self.p.setdefault("count", 4)
        self.p.setdefault("n", 64)

    def nm(self, tag, k=0):
        return long_name(f"{tag}{self.name[1:]}", k, self.p["length"])

    def modules(self):
        L = self.p["length"]
        t, c, f = self.nm("t"), self.nm("c"), self.nm("f")
        spec = [f"type :: {t}", f"  integer(8) :: {c}", f"end type {t}"]
        cont = [f"  function {f}(x) result(r)", _dt_line(self.o),
                "    integer(8), intent(in) :: x", "    integer(8) :: r",
                "    r = x * 3 + 1", f"  end function {f}"]
        del L
        return [Module(self.nm("m"), spec, cont)]

    def uses(self):
        return [self.nm("m")]

    def decls(self):
        n = self.p["n"]
        vs = [self.nm("v", k) for k in range(self.p["count"])]
        return [f"integer(8) :: out({n})", "integer :: i",
                f"type({self.nm('t')}) :: obj"] + \
            [f"integer(8) :: {v}" for v in vs]

    def body(self):
        n = self.p["n"]
        vs = [self.nm("v", k) for k in range(self.p["count"])]
        ind = "    "
        f, c = self.nm("f"), self.nm("c")
        lines = [f"{ind}out = 0", f"{ind}obj%{c} = 9"]
        chain = ("target teams distribute parallel do",) if \
            self.o.model == "omp" else ("parallel loop",)
        op, cl, ii = region(self.o, chain, ind,
                            data=[("out", "tofrom"), ("obj", "to")],
                            private=vs)
        lines += op + [f"{ii}do i = 1, {n}"]
        for k, v in enumerate(vs):
            lines += pack(f"{v} =", [f"{f}(int(i, 8))", f"+ {k}"],
                          ii + "  ", None, self.o.width)
        lines += sum_lines(ii + "  ", "out(i)", vs + [f"obj%{c}"],
                           self.o.width)
        lines += [f"{ii}end do"] + cl
        lines.append(f"{ind}call st_cksum(out, {n}, cs)")
        return lines

    def value(self):
        n, cnt = self.p["n"], self.p["count"]
        return cksum(sum(i * 3 + 1 + k for k in range(cnt)) + 9
                     for i in range(1, n + 1))

    def smaller(self):
        out = []
        if self.p["count"] > 1:
            out.append(self.clone(count=1))
        if self.p["length"] > 63:
            out.append(self.clone(length=64))
        return out

    def features(self):
        return super().features() | {f"len:names:{self.p['length']}"}


# --- long variable lists ---------------------------------------------------------------------------

def decl_lines(typ: str, names: list[str], width: int) -> list[str]:
    return [ln.strip() for ln in pack(f"{typ} ::", [
        x + ("," if k < len(names) - 1 else "")
        for k, x in enumerate(names)], "", None, width)]


class LocalsKernel(Kernel):
    """A device routine with `nlocals` local variables (scalars and, every
    eighth, a 4-element array): res = sum of q_j = mod(x*(j+1)+j, 991)."""
    kind = "locals"

    def draw(self, rng):
        self.p.setdefault("nlocals", 64)
        self.p.setdefault("n", max(8, min(256, 100000 // max(
            1, self.p["nlocals"]))))

    def modules(self):
        k = self.p["nlocals"]
        sc = [vname("q", j) for j in range(1, k + 1) if j % 8]
        ar = [vname("q", j) for j in range(1, k + 1) if not j % 8]
        cont = [f"  subroutine {self.name}_dr(x, res)", _dt_line(self.o),
                "    integer(8), intent(in) :: x",
                "    integer(8), intent(out) :: res"]
        cont += ["    " + d for d in decl_lines("integer(8)", sc,
                                                 self.o.width)]
        if ar:
            cont += ["    " + d for d in decl_lines(
                "integer(8)", [f"{a}(4)" for a in ar], self.o.width)]
        for j in range(1, k + 1):
            v = vname("q", j)
            rhs = f"mod(x * {j + 1} + {j}, 991_8)"
            cont.append(f"    {v} = {rhs}" if j % 8 else f"    {v} = {rhs}")
        cont.append("    res = 0")
        terms = [vname("q", j) if j % 8 else f"{vname('q', j)}(3)"
                 for j in range(1, k + 1)]
        cont += sum_lines("    ", "res", terms, self.o.width)
        cont.append(f"  end subroutine {self.name}_dr")
        return [Module(f"{self.name}_m", [], cont)]

    def uses(self):
        return [f"{self.name}_m"]

    def decls(self):
        return [f"integer(8) :: out({self.p['n']})", "integer :: i",
                "integer(8) :: r"]

    def body(self):
        n = self.p["n"]
        ind = "    "
        chain = ("target teams distribute parallel do",) if \
            self.o.model == "omp" else ("parallel loop gang vector",)
        op, cl, ii = region(self.o, chain, ind, data=[("out", "tofrom")],
                            private=["r"])
        return [f"{ind}out = 0"] + op + [
            f"{ii}do i = 1, {n}",
            f"{ii}  call {self.name}_dr(int(i, 8), r)",
            f"{ii}  out(i) = r", f"{ii}end do"] + cl + [
            f"{ind}call st_cksum(out, {n}, cs)"]

    def value(self):
        k, n = self.p["nlocals"], self.p["n"]
        return cksum(sum((i * (j + 1) + j) % 991 for j in range(1, k + 1))
                     for i in range(1, n + 1))

    def smaller(self):
        return [self.clone(nlocals=m) for m in _halve(self.p["nlocals"])] \
            + ([self.clone(n=8)] if self.p["n"] > 8 else [])

    def features(self):
        return super().features() | {f"len:locals:{self.p['nlocals']}"}


ARG_KINDS = ("value", "ref", "array", "derived", "optional")


class ArgsKernel(Kernel):
    """A device routine with `nargs` dummy arguments, kinds cycling through
    VALUE scalar, by-reference scalar, explicit-shape array(4), a derived
    type, and (last) OPTIONAL scalars of which every other one is passed
    (by keyword after the first omitted one)."""
    kind = "args"

    def draw(self, rng):
        self.p.setdefault("nargs", 16)
        self.p.setdefault("n", max(8, min(256, 60000 // max(
            1, self.p["nargs"]))))

    def kinds(self):
        k = self.p["nargs"]
        nopt = max(0, k // 5)
        req = [ARG_KINDS[j % 4] for j in range(k - nopt)]
        return req + ["optional"] * nopt

    def modules(self):
        ks = self.kinds()
        names = [vname("a", j) for j in range(1, len(ks) + 1)]
        spec = ["type :: st_pairT", "  integer(8) :: u, v", "end type"] \
            if False else []
        cont = []
        cont += pack(f"subroutine {self.name}_dr(", [
            x + ("," if j < len(names) else ")") for j, x in
            enumerate(names + ["res"])], "  ", None, self.o.width)
        cont.append(_dt_line(self.o))
        # declarations grouped by kind
        groups: dict[str, list[str]] = {}
        for x, kd in zip(names, ks):
            groups.setdefault(kd, []).append(x)
        typ = {"value": "integer(8), value", "ref": "integer(8), intent(in)",
               "array": "integer(8), intent(in)",
               "derived": "type(st_pair), intent(in)",
               "optional": "integer(8), intent(in), optional"}
        for kd in ARG_KINDS:
            if kd in groups:
                ents = [f"{x}(4)" if kd == "array" else x
                        for x in groups[kd]]
                cont += ["    " + d for d in decl_lines(typ[kd], ents,
                                                         self.o.width)]
        cont.append("    integer(8), intent(out) :: res")
        cont.append("    res = 0")
        for j, (x, kd) in enumerate(zip(names, ks), 1):
            if kd in ("value", "ref"):
                cont.append(f"    res = res + {x} * {j % 13 + 1}")
            elif kd == "array":
                cont.append(f"    res = res + {x}(1) + {x}(4) * 2")
            elif kd == "derived":
                cont.append(f"    res = res + {x}%u * 3 + {x}%v")
            else:
                cont.append(f"    if (present({x})) res = res + {x} * 5")
        cont.append(f"  end subroutine {self.name}_dr")
        return [Module(f"{self.name}_m", spec, cont, ["st_util"])]

    def uses(self):
        return [f"{self.name}_m", "st_util"]

    def decls(self):
        return [f"integer(8) :: out({self.p['n']})", "integer :: i",
                "integer(8) :: r, s", "integer(8) :: arr(4)",
                "type(st_pair) :: pr"]

    def actuals(self):
        ks = self.kinds()
        acts, keyword = [], False
        for j, kd in enumerate(ks, 1):
            x = vname("a", j)
            if kd in ("value", "ref"):
                acts.append(f"s + {j}" if kd == "value" else "s")
            elif kd == "array":
                acts.append("arr")
            elif kd == "derived":
                acts.append("pr")
            else:
                if j % 2:
                    acts.append(f"{x}=s" if keyword else "s")
                else:
                    keyword = True
        acts.append("res=r" if keyword else "r")
        return acts

    def body(self):
        n = self.p["n"]
        ind = "    "
        chain = ("target teams distribute parallel do",) if \
            self.o.model == "omp" else ("parallel loop gang vector",)
        op, cl, ii = region(self.o, chain, ind,
                            data=[("out", "tofrom"), ("arr", "to"),
                                  ("pr", "to")], private=["r", "s"])
        lines = [f"{ind}out = 0", f"{ind}arr = [3, 5, 7, 11]",
                 f"{ind}pr%u = 4", f"{ind}pr%v = 9"]
        lines += op + [f"{ii}do i = 1, {n}", f"{ii}  s = i"]
        lines += call_lines(ii + "  ", f"{self.name}_dr", self.actuals(),
                            self.o.width)
        lines += [f"{ii}  out(i) = r", f"{ii}end do"] + cl
        lines.append(f"{ind}call st_cksum(out, {n}, cs)")
        return lines

    def value(self):
        ks, n = self.kinds(), self.p["n"]
        vals = []
        for i in range(1, n + 1):
            res = 0
            for j, kd in enumerate(ks, 1):
                if kd == "value":
                    res += (i + j) * (j % 13 + 1)
                elif kd == "ref":
                    res += i * (j % 13 + 1)
                elif kd == "array":
                    res += 3 + 11 * 2
                elif kd == "derived":
                    res += 4 * 3 + 9
                elif j % 2:
                    res += i * 5
            vals.append(res)
        return cksum(vals)

    def smaller(self):
        return [self.clone(nargs=m) for m in _halve(self.p["nargs"])] + \
            ([self.clone(n=8)] if self.p["n"] > 8 else [])

    def features(self):
        return super().features() | {f"len:args:{self.p['nargs']}"} | {
            f"args:{k}" for k in set(self.kinds())}


class UseOnlyKernel(Kernel):
    """`use <module>, only: ...` with `nitems` names: half named constants
    (parameters), half device-resident module variables."""
    kind = "useonly"

    def draw(self, rng):
        self.p.setdefault("nitems", 16)
        self.p.setdefault("n", max(8, min(256, 100000 // max(
            1, self.p["nitems"]))))

    def names(self):
        k = self.p["nitems"]
        return [vname("u", j) for j in range(1, k + 1)]

    def modules(self):
        nm = self.names()
        spec = []
        pv = [x for j, x in enumerate(nm) if j % 2 == 0]
        dv = [x for j, x in enumerate(nm) if j % 2 == 1]
        for j, x in enumerate(nm):
            if j % 2 == 0:
                spec.append(f"integer(8), parameter :: {x} = {j * 3 + 1}")
        if dv:
            spec += decl_lines("integer(8)", dv, self.o.width)
            if self.o.model == "omp":
                spec += pack("declare target(", [
                    x + ("," if k < len(dv) - 1 else ")")
                    for k, x in enumerate(dv)], "", self.o.sent,
                    self.o.width)
            else:
                spec += pack("declare", list_atoms("create", dv), "",
                             self.o.sent, self.o.width)
        del pv
        # a decoy name the kernel does not import
        spec.append(f"integer(8) :: {self.name}_unused")
        return [Module(f"{self.name}_m", spec)]

    def routine(self):
        lines = super().routine()
        nm = self.names()
        use = pack(f"use {self.name}_m, only:", [
            x + ("," if k < len(nm) - 1 else "")
            for k, x in enumerate(nm)], "    ", None, self.o.width)
        return [lines[0]] + use + lines[1:]

    def decls(self):
        return [f"integer(8) :: out({self.p['n']})", "integer :: i",
                "integer(8) :: t"]

    def body(self):
        n = self.p["n"]
        nm = self.names()
        dv = [x for j, x in enumerate(nm) if j % 2 == 1]
        ind = "    "
        lines = [f"{ind}{x} = {j * 3 + 1}" for j, x in enumerate(nm)
                 if j % 2 == 1]
        if dv:
            if self.o.model == "omp":
                lines += pack("target update", list_atoms("to", dv), ind,
                              self.o.sent, self.o.width)
            else:
                lines += pack("update", list_atoms("device", dv), ind,
                              self.o.sent, self.o.width)
        chain = ("target teams distribute parallel do",) if \
            self.o.model == "omp" else ("parallel loop gang vector",)
        op, cl, ii = region(self.o, chain, ind, data=[("out", "tofrom")],
                            private=["t"])
        lines += [f"{ind}out = 0"] + op + [f"{ii}do i = 1, {n}",
                                           f"{ii}  t = i"]
        lines += sum_lines(ii + "  ", "t", nm, self.o.width)
        lines += [f"{ii}  out(i) = t", f"{ii}end do"] + cl
        lines.append(f"{ind}call st_cksum(out, {n}, cs)")
        return lines

    def value(self):
        k, n = self.p["nitems"], self.p["n"]
        s = sum(j * 3 + 1 for j in range(k))
        return cksum(i + s for i in range(1, n + 1))

    def smaller(self):
        return [self.clone(nitems=m) for m in _halve(self.p["nitems"])]

    def features(self):
        return super().features() | {f"len:useonly:{self.p['nitems']}"}


class CaptureKernel(ListKernel):
    """`nitems` host scalars referenced in the region with no clause
    (implicitly firstprivate: OpenMP 5.2 §5.8.1 p.148; OpenACC 3.4 §2.6.2
    p.41 for parallel)."""
    kind = "capture"

    def decls(self):
        n = self.p["n"]
        its = self.items("s")
        return [f"integer(8) :: out({n})", "integer :: i", "integer(8) :: t"] \
            + decl_lines("integer(8)", its, self.o.width)

    def body(self):
        n, c = self.p["n"], self.p["c"]
        its = self.items("s")
        ind = "    "
        lines = [f"{ind}{x} = {c[k] + 2 * k}" for k, x in enumerate(its)]
        lines.append(f"{ind}out = 0")
        chain = ("target teams distribute parallel do",) if \
            self.o.model == "omp" else ("parallel loop gang vector",)
        op, cl, ii = region(self.o, chain, ind, data=[("out", "tofrom")],
                            private=["t"])
        lines += op + [f"{ii}do i = 1, {n}", f"{ii}  t = i"]
        terms = [f"{x} * mod(i, {k % 3 + 2})" for k, x in enumerate(its)]
        lines += sum_lines(ii + "  ", "t", terms, self.o.width)
        lines += [f"{ii}  out(i) = t", f"{ii}end do"] + cl
        lines.append(f"{ind}call st_cksum(out, {n}, cs)")
        return lines

    def value(self):
        n, c = self.p["n"], self.p["c"]
        k = self.p["nitems"]
        s = [c[j] + 2 * j for j in range(k)]
        return cksum(i + sum(s[j] * (i % (j % 3 + 2)) for j in range(k))
                     for i in range(1, n + 1))


# --- nested derived types and classes ------------------------------------------------------------

class DTNestKernel(Kernel):
    """Derived types nested `depth` levels (t1 contains t2 ... contains tD),
    each level with a scalar s and an allocatable component v(:) (and, with
    ptr, a pointer component at the deepest level); an array x(na) of t1;
    deep copy by enter data of x then of every x(e)%c...%v (OpenMP 5.2
    §5.8.3: a list item and its containing structure may both be mapped),
    or one region mapping them all (mode 'region'); out(i) = sum over
    elements and levels of v(i) + s."""
    kind = "dtnest"

    def draw(self, rng):
        self.p.setdefault("depth", 3)
        self.p.setdefault("na", 2)
        self.p.setdefault("m", 16)
        self.p.setdefault("mode", rng.choice(("enter", "region")))
        self.p.setdefault("ptr", rng.random() < 0.3)

    def tname(self, d):
        return f"{self.name}_t{d}"

    def path(self, e, d):
        return f"x({e})" + "%c" * (d - 1)

    def modules(self):
        D = self.p["depth"]
        spec = []
        for d in range(D, 0, -1):
            spec.append(f"type :: {self.tname(d)}")
            spec.append("  integer(8) :: s")
            spec.append("  integer(8), allocatable :: v(:)")
            if d == D and self.p["ptr"]:
                spec.append("  integer(8), pointer :: pv(:) => null()")
            if d < D:
                spec.append(f"  type({self.tname(d + 1)}) :: c")
            spec.append(f"end type {self.tname(d)}")
        if self.p["ptr"]:
            spec.append(f"integer(8), target :: {self.name}_tgt"
                        f"({self.p['m']}, {self.p['na']})")
        return [Module(f"{self.name}_m", spec)]

    def uses(self):
        return [f"{self.name}_m"]

    def decls(self):
        return [f"type({self.tname(1)}) :: x({self.p['na']})",
                f"integer(8) :: out({self.p['m']})", "integer :: i, e"]

    def items(self):
        D, na = self.p["depth"], self.p["na"]
        its = []
        for e in range(1, na + 1):
            for d in range(1, D + 1):
                its.append(self.path(e, d) + "%v")
            if self.p["ptr"]:
                its.append(self.path(e, D) + "%pv")
        return its

    def body(self):
        D, na, m = self.p["depth"], self.p["na"], self.p["m"]
        ind = "    "
        lines = []
        for e in range(1, na + 1):
            for d in range(1, D + 1):
                pth = self.path(e, d)
                lines += [f"{ind}allocate({pth}%v({m}))",
                          f"{ind}{pth}%s = {d * 10 + e}",
                          f"{ind}do i = 1, {m}",
                          f"{ind}  {pth}%v(i) = mod(i * {d} + {e}, 97)",
                          f"{ind}end do"]
            if self.p["ptr"]:
                pth = self.path(e, D)
                lines += [f"{ind}do i = 1, {m}",
                          f"{ind}  {self.name}_tgt(i, {e}) = i + {e}",
                          f"{ind}end do",
                          f"{ind}{pth}%pv => {self.name}_tgt(:, {e})"]
        lines.append(f"{ind}out = 0")
        its = self.items()
        o = self.o
        terms = []
        for e in range(1, na + 1):
            for d in range(1, D + 1):
                terms.append(f"{self.path(e, d)}%v(i)")
                terms.append(f"{self.path(e, d)}%s")
            if self.p["ptr"]:
                terms.append(f"{self.path(e, D)}%pv(i)")
        if self.p["mode"] == "enter":
            if o.model == "omp":
                lines.append(f"{ind}{o.sent} target enter data map(to: x)")
                lines += pack("target enter data", list_atoms("map", its,
                                                              "to"),
                              ind, o.sent, o.width)
            else:
                lines.append(f"{ind}{o.sent} enter data copyin(x)")
                lines += pack("enter data", list_atoms("copyin", its), ind,
                              o.sent, o.width)
            chain = ("target teams distribute parallel do",) if \
                o.model == "omp" else ("parallel loop",)
            op, cl, ii = region(o, chain, ind, data=[("out", "tofrom")],
                                extra=["present(x)"] if o.model == "acc"
                                else [])
        else:
            chain = ("target teams distribute parallel do",) if \
                o.model == "omp" else ("parallel loop",)
            op, cl, ii = region(o, chain, ind,
                                data=[("x", "to")] + [(t, "to") for t in its]
                                + [("out", "tofrom")])
        lines += op + [f"{ii}do i = 1, {m}"]
        lines += sum_lines(ii + "  ", "out(i)", terms, o.width)
        lines += [f"{ii}end do"] + cl
        if self.p["mode"] == "enter":
            if o.model == "omp":
                lines += pack("target exit data",
                              list_atoms("map", list(reversed(its)),
                                         "delete"), ind, o.sent, o.width)
                lines.append(f"{ind}{o.sent} target exit data "
                             "map(delete: x)")
            else:
                lines += pack("exit data", list_atoms(
                    "delete", list(reversed(its))), ind, o.sent, o.width)
                lines.append(f"{ind}{o.sent} exit data delete(x)")
        lines.append(f"{ind}call st_cksum(out, {m}, cs)")
        return lines

    def value(self):
        D, na, m = self.p["depth"], self.p["na"], self.p["m"]
        vals = []
        for i in range(1, m + 1):
            t = 0
            for e in range(1, na + 1):
                for d in range(1, D + 1):
                    t += (i * d + e) % 97 + d * 10 + e
                if self.p["ptr"]:
                    t += i + e
            vals.append(t)
        return cksum(vals)

    def smaller(self):
        out = []
        if self.p["depth"] > 1:
            out.append(self.clone(depth=self.p["depth"] - 1))
            out.append(self.clone(depth=1))
        if self.p["na"] > 1:
            out.append(self.clone(na=1))
        if self.p["ptr"]:
            out.append(self.clone(ptr=False))
        if self.p["mode"] == "region":
            out.append(self.clone(mode="enter"))
        return out

    def features(self):
        f = super().features() | {f"dt:depth{self.p['depth']}",
                                  f"dt:mode:{self.p['mode']}",
                                  "base:derived", "base:allocatable"}
        if self.p["na"] > 1:
            f.add("dt:array_of_dt")
        if self.p["ptr"]:
            f.add("base:pointer")
        return f


OO_VARIANTS = ("tbp", "nopass", "generic", "extends", "abstract", "class",
               "polymap", "pdt")
OO_LEGAL = ("tbp", "nopass", "generic", "extends", "abstract", "class")


class OOKernel(Kernel):
    """Object-oriented code used in a target / compute region: type-bound
    procedures (passed-object, NOPASS), generic and operator bindings, an
    EXTENDS chain `depth` deep with overriding bindings, an abstract type
    with a deferred binding, a CLASS dummy with SELECT TYPE in a device
    routine; every procedure the region reaches is a device routine
    (OpenMP 5.0/5.2 §1.2.6: type-bound procedures accessed in a target
    region must appear in a declare target directive). 'polymap' maps a
    polymorphic allocatable: unspecified (OpenMP 6.0 §7.9.6 p.287; 5.0 and
    5.2 do not define it): portability data, never a compiler bug."""
    kind = "oo"

    def draw(self, rng):
        self.p.setdefault("variant", rng.choice(OO_VARIANTS))
        self.p.setdefault("depth", 3)
        self.p.setdefault("n", 128)
        if self.p["variant"] == "polymap":
            self.legality = "unspecified"
            self.cite = CITES["poly"]

    def __init__(self, name, o, rng, **p):
        super().__init__(name, o, rng, **p)
        if self.p.get("variant") == "polymap":
            self.legality = "unspecified"
            self.cite = CITES["poly"]

    def t(self, d=0):
        return f"{self.name}_t{d}"

    def modules(self):
        v, D = self.p["variant"], self.p["depth"]
        dt = _dt_line(self.o)
        spec, cont = [], []
        if v in ("tbp", "class", "polymap"):
            spec = [f"type :: {self.t()}", "  integer(8) :: k = 3",
                    "contains",
                    f"  procedure :: get => {self.name}_get",
                    f"end type {self.t()}"]
            cont = [f"  function {self.name}_get(self, i) result(r)", dt,
                    f"    class({self.t()}), intent(in) :: self",
                    "    integer(8), intent(in) :: i", "    integer(8) :: r",
                    "    r = self%k * i + 1", f"  end function {self.name}_get"]
            if v in ("class", "polymap"):
                spec += [f"type, extends({self.t()}) :: {self.t(1)}",
                         "  integer(8) :: extra = 5",
                         "contains", f"  procedure :: get => {self.name}_get1",
                         f"end type {self.t(1)}"]
                cont += [f"  function {self.name}_get1(self, i) result(r)",
                         dt, f"    class({self.t(1)}), intent(in) :: self",
                         "    integer(8), intent(in) :: i",
                         "    integer(8) :: r",
                         "    r = self%k * i + self%extra",
                         f"  end function {self.name}_get1",
                         f"  function {self.name}_sel(o, i) result(r)", dt,
                         f"    class({self.t()}), intent(in) :: o",
                         "    integer(8), intent(in) :: i",
                         "    integer(8) :: r",
                         "    select type (o)",
                         f"    type is ({self.t(1)})",
                         "      r = o%extra * 100 + o%get(i)",
                         "    class default",
                         "      r = o%get(i)",
                         "    end select",
                         f"  end function {self.name}_sel"]
        elif v == "nopass":
            spec = [f"type :: {self.t()}", "  integer(8) :: k = 3",
                    "contains",
                    f"  procedure, nopass :: f => {self.name}_f",
                    f"end type {self.t()}"]
            cont = [f"  function {self.name}_f(i) result(r)", dt,
                    "    integer(8), intent(in) :: i", "    integer(8) :: r",
                    "    r = i * 7 + 2", f"  end function {self.name}_f"]
        elif v == "generic":
            spec = [f"type :: {self.t()}", "  integer(8) :: k = 3",
                    "contains",
                    f"  procedure :: addi => {self.name}_addi",
                    "  generic :: add => addi",
                    f"  procedure :: plus => {self.name}_plus",
                    "  generic :: operator(+) => plus",
                    f"end type {self.t()}"]
            cont = [f"  function {self.name}_addi(self, i) result(r)", dt,
                    f"    class({self.t()}), intent(in) :: self",
                    "    integer(8), intent(in) :: i", "    integer(8) :: r",
                    "    r = self%k + i", f"  end function {self.name}_addi",
                    f"  function {self.name}_plus(a, b) result(r)", dt,
                    f"    class({self.t()}), intent(in) :: a",
                    f"    type({self.t()}), intent(in) :: b",
                    f"    type({self.t()}) :: r",
                    "    r%k = a%k + b%k", f"  end function {self.name}_plus"]
        elif v == "extends":
            for d in range(D + 1):
                head = f"type :: {self.t(0)}" if d == 0 else \
                    f"type, extends({self.t(d - 1)}) :: {self.t(d)}"
                spec += [head, f"  integer(8) :: c{d} = {d + 2}", "contains",
                         f"  procedure :: get => {self.name}_g{d}",
                         f"end type {self.t(d)}"]
                cont += [f"  function {self.name}_g{d}(self, i) result(r)",
                         dt, f"    class({self.t(d)}), intent(in) :: self",
                         "    integer(8), intent(in) :: i",
                         "    integer(8) :: r",
                         f"    r = self%c{d} * i + {d}",
                         f"  end function {self.name}_g{d}"]
        elif v == "pdt":
            # a parameterized derived type (kind and length parameters;
            # OpenMP 5.2 §5.8.3: a corresponding list item has the type
            # parameters of the original)
            spec = [f"type :: {self.t()}(kk, nn)",
                    "  integer, kind :: kk = 8", "  integer, len :: nn",
                    "  integer(kk) :: v(nn)", "  integer(kk) :: s",
                    f"end type {self.t()}"]
            cont = []
        elif v == "abstract":
            spec = [f"type, abstract :: {self.t(0)}", "  integer(8) :: k = 4",
                    "contains",
                    f"  procedure({self.name}_iface), deferred :: get",
                    f"end type {self.t(0)}",
                    "abstract interface",
                    f"  function {self.name}_iface(self, i) result(r)",
                    f"    import :: {self.t(0)}",
                    f"    class({self.t(0)}), intent(in) :: self",
                    "    integer(8), intent(in) :: i", "    integer(8) :: r",
                    f"  end function {self.name}_iface", "end interface",
                    f"type, extends({self.t(0)}) :: {self.t(1)}", "contains",
                    f"  procedure :: get => {self.name}_g1",
                    f"end type {self.t(1)}"]
            cont = [f"  function {self.name}_g1(self, i) result(r)", dt,
                    f"    class({self.t(1)}), intent(in) :: self",
                    "    integer(8), intent(in) :: i", "    integer(8) :: r",
                    "    r = self%k * i * 2", f"  end function {self.name}_g1"]
        return [Module(f"{self.name}_m", spec, cont)]

    def uses(self):
        return [f"{self.name}_m"]

    def decls(self):
        v = self.p["variant"]
        d = [f"integer(8) :: out({self.p['n']})", "integer :: i"]
        if v in ("tbp", "nopass", "generic"):
            d.append(f"type({self.t()}) :: obj")
        if v == "generic":
            d.append(f"type({self.t()}) :: o2")
        if v == "extends":
            d.append(f"type({self.t(self.p['depth'])}) :: obj")
        if v == "abstract":
            d.append(f"type({self.t(1)}) :: obj")
        if v == "class":
            d.append(f"type({self.t(1)}) :: obj")
        if v == "polymap":
            d.append(f"class({self.t()}), allocatable :: obj")
        if v == "pdt":
            d.append(f"type({self.t()}(8, 7)) :: obj")
        return d

    def expr(self):
        v = self.p["variant"]
        return {"tbp": "obj%get(int(i, 8))",
                "nopass": "obj%f(int(i, 8))",
                "generic": "obj%add(int(i, 8)) + o2%k",
                "extends": "obj%get(int(i, 8)) + obj%c0",
                "abstract": "obj%get(int(i, 8))",
                "class": f"{self.name}_sel(obj, int(i, 8))",
                "polymap": "obj%get(int(i, 8))",
                "pdt": "obj%v(mod(i, obj%nn) + 1) + obj%s + obj%nn"}[v]

    def body(self):
        v = self.p["variant"]
        n = self.p["n"]
        ind = "    "
        lines = [f"{ind}out = 0"]
        if v == "generic":
            lines.append(f"{ind}o2 = obj + obj")
        if v == "polymap":
            lines.append(f"{ind}allocate({self.t(1)} :: obj)")
        if v == "pdt":
            lines += [f"{ind}do i = 1, 7", f"{ind}  obj%v(i) = i * 11",
                      f"{ind}end do", f"{ind}obj%s = 5"]
        chain = ("target teams distribute parallel do",) if \
            self.o.model == "omp" else ("parallel loop",)
        data = [("out", "tofrom"), ("obj", "to")]
        if v == "generic":
            data.append(("o2", "to"))
        op, cl, ii = region(self.o, chain, ind, data=data)
        lines += op + [f"{ii}do i = 1, {n}",
                       f"{ii}  out(i) = {self.expr()}", f"{ii}end do"] + cl
        lines.append(f"{ind}call st_cksum(out, {n}, cs)")
        return lines

    def value(self):
        v, n, D = self.p["variant"], self.p["n"], self.p["depth"]
        f = {"tbp": lambda i: 3 * i + 1,
             "nopass": lambda i: i * 7 + 2,
             "generic": lambda i: 3 + i + 6,
             "extends": lambda i: (D + 2) * i + D + 2,
             "abstract": lambda i: 4 * i * 2,
             "class": lambda i: 5 * 100 + 3 * i + 5,
             "polymap": lambda i: 3 * i + 5,
             "pdt": lambda i: (i % 7 + 1) * 11 + 5 + 7}[v]
        return cksum(f(i) for i in range(1, n + 1))

    def smaller(self):
        out = []
        if self.p["variant"] == "extends" and self.p["depth"] > 1:
            out.append(self.clone(depth=1))
        if self.p["n"] > 8:
            out.append(self.clone(n=8))
        return out

    def features(self):
        return super().features() | {f"oo:{self.p['variant']}",
                                     "base:derived"}


# --- translation units ---------------------------------------------------------------------------

class ChainTUKernel(Kernel):
    """A device call chain across modules: module <k>_c1 uses <k>_c2 ...
    uses <k>_cD, each with function g_j(x) = g_{j+1}(mod(x*5, 1013) + j)
    + j; every module also uses <k>_glob, whose declare target variable gv
    the deepest function adds (a module DAG with a shared root). Variants:
    'plain'; 'submodule' (the deepest function's interface in the module,
    its body in a submodule); 'bindc' (the deepest function in C, bound
    with bind(C), OpenMP only); 'implicit' (no declare target on g_2..g_D:
    legal when every g_j is in the compilation unit of the region,
    otherwise an illegal probe, OpenMP 5.2 §13.8 p.284 and §5.8.4 p.158).
    The program's layout decides the files (one per module, or
    partitions)."""
    kind = "tu"

    def draw(self, rng):
        self.p.setdefault("depth", 5)
        self.p.setdefault("n", 256)
        self.p.setdefault("variant", "plain")
        self.p.setdefault("gv", rng.randrange(1, 100))

    def m(self, j):
        return f"{self.name}_c{j}"

    def g(self, j):
        return f"{self.name}_g{j}"

    def modules(self):
        D, var = self.p["depth"], self.p["variant"]
        o = self.o
        mods = []
        glob_spec = ["integer(8) :: gv = 0"]
        glob_spec.append(f"{o.sent} declare target(gv)" if o.model == "omp"
                         else f"{o.sent} declare create(gv)")
        mods.append(Module(f"{self.name}_glob", glob_spec))
        for j in range(D, 0, -1):
            uses = [f"{self.name}_glob"] + ([self.m(j + 1)] if j < D else [])
            need_dt = not (var == "implicit" and j > 1)
            dl = [_dt_line(o)] if need_dt else []
            if j == D and var == "submodule":
                spec = ["interface",
                        f"  module function {self.g(j)}(x) result(r)",
                        f"  {o.sent} declare target" if o.model == "omp"
                        else f"  {o.sent} routine seq",
                        "    integer(8), intent(in) :: x",
                        "    integer(8) :: r",
                        f"  end function {self.g(j)}", "end interface"]
                mods.append(Module(self.m(j), spec, [], uses))
                continue
            if j == D and var == "bindc":
                spec = ["interface",
                        f"  function {self.g(j)}(x) result(r) "
                        f"bind(C, name=\"{self.g(j)}_c\")",
                        "    import :: c_int64_t",
                        f"  {o.sent} declare target",
                        "    integer(c_int64_t), value :: x",
                        "    integer(c_int64_t) :: r",
                        f"  end function {self.g(j)}", "end interface"]
                mods.append(Module(self.m(j), spec, [],
                                   uses + ["iso_c_binding"]))
                continue
            cont = [f"  function {self.g(j)}(x) result(r)"] + dl + [
                "    integer(8), intent(in) :: x", "    integer(8) :: r"]
            if j < D:
                cont.append(f"    r = {self.g(j + 1)}(mod(x * 5, 1013_8) + "
                            f"{j}) + {j}")
            else:
                cont.append("    r = x + gv")
            cont.append(f"  end function {self.g(j)}")
            mods.append(Module(self.m(j), [], cont, uses))
        return mods

    def extra_files(self) -> list[tuple[str, str]]:
        """Files that are not modules of the program text: the submodule
        and the C function, each its own translation unit."""
        D, var = self.p["depth"], self.p["variant"]
        o = self.o
        if var == "submodule":
            text = [f"submodule ({self.m(D)}) {self.m(D)}_s",
                    "  implicit none", "contains",
                    f"  module function {self.g(D)}(x) result(r)",
                    "    use " + f"{self.name}_glob, only: gv",
                    f"  {o.sent} declare target" if o.model == "omp"
                    else f"  {o.sent} routine seq",
                    "    integer(8), intent(in) :: x",
                    "    integer(8) :: r",
                    "    r = x + gv", f"  end function {self.g(D)}",
                    f"end submodule {self.m(D)}_s"]
            return [(f"{self.m(D)}_s.f90", "\n".join(text) + "\n")]
        if var == "bindc":
            text = ["#include <stdint.h>",
                    "#pragma omp declare target",
                    f"int64_t {self.g(D)}_c(int64_t x) {{ return x + "
                    f"{self.p['gv']}; }}",
                    "#pragma omp end declare target"]
            return [(f"{self.g(D)}_c.c", "\n".join(text) + "\n")]
        return []

    def uses(self):
        return [self.m(1), f"{self.name}_glob"]

    def decls(self):
        return [f"integer(8) :: out({self.p['n']})", "integer :: i"]

    def body(self):
        n = self.p["n"]
        o = self.o
        ind = "    "
        lines = [f"{ind}gv = {self.p['gv']}"]
        lines.append(f"{ind}{o.sent} target update to(gv)" if o.model ==
                     "omp" else f"{ind}{o.sent} update device(gv)")
        chain = ("target teams distribute parallel do",) if \
            o.model == "omp" else ("parallel loop gang vector",)
        op, cl, ii = region(o, chain, ind, data=[("out", "tofrom")])
        lines += [f"{ind}out = 0"] + op + [
            f"{ii}do i = 1, {n}", f"{ii}  out(i) = {self.g(1)}(int(i, 8))",
            f"{ii}end do"] + cl
        lines.append(f"{ind}call st_cksum(out, {n}, cs)")
        return lines

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
        out = [self.clone(depth=m) for m in _halve(self.p["depth"], 2)]
        if self.p["variant"] != "plain":
            out.append(self.clone(variant="plain"))
        return out

    def features(self):
        return super().features() | {f"tu:depth{self.p['depth']}",
                                     f"tu:{self.p['variant']}"}


# --- default scalar residency ------------------------------------------------------------------

# route -> (defined: device read of the host value, defined: host value
# after the region, what the host sees after: "same" | "write")
OMP_ROUTES = {
    "implicit": (True, True, "same"),
    "firstprivate": (True, True, "same"),
    "private": (False, True, "same"),
    "to": (True, False, None),
    "from": (False, True, "write"),
    "tofrom": (True, True, "write"),
    "dm_tofrom": (True, True, "write"),
    "dm_firstprivate": (True, True, "same"),
    "dm_to": (True, False, None),
    "target_attr": (True, True, "write"),
    "present_implicit": (True, True, "same"),
    "present_update": (True, True, "write"),
    "declare": (True, True, "write"),
    "component": (True, True, "write"),
    "byref": (True, True, "same"),
    "value": (True, True, "same"),
    "reduction": (True, True, "red"),
}
ACC_ROUTES = {
    "implicit_parallel": (True, True, "same"),
    "implicit_serial": (True, True, "same"),
    "implicit_kernels": (True, True, "write"),
    "copy": (True, True, "write"),
    "copyin": (True, False, None),
    "copyout": (False, True, "write"),
    "firstprivate": (True, True, "same"),
    "private": (False, True, "same"),
    "data_copy": (True, True, "write"),
    "enter_implicit": (True, True, "same"),
    "declare": (True, True, "write"),
    "component": (True, True, "write"),
    "byref": (True, True, "same"),
    "reduction": (True, True, "red"),
}
ROUTE_CITES = (
    "OpenMP 5.2 §5.8.1 p.147-148 (implicit data-mapping: a non-scalar or a "
    "TARGET/ALLOCATABLE/POINTER scalar is tofrom, another scalar "
    "firstprivate; the same rules in 5.0 §2.19.7 p.314 and 6.0 §7.9.3 "
    "p.276), §1.4.2 p.27 (a write to a variable whose corresponding "
    "variable does not share storage makes the other undefined); OpenACC "
    "3.4 §2.6.2 p.41 (a scalar is copy in kernels, firstprivate otherwise; "
    "a visible data clause of an enclosing data construct applies)")


class ScalarsKernel(Kernel):
    """Default scalar residency against every explicit route: for each
    route, `nscal` scalars s_j (host value h_j) and an array a mixed in the
    same region; one thread on the device (target / serial) reads each s_j
    into rd(j) and writes s_j = 2*s_j + 1. The value combines only the
    observations the specification defines (a device read of the host
    value; the host value afterwards: unchanged for private copies, the
    device write for tofrom); the others print an ``OBS`` line
    (portability data)."""
    kind = "scalars"
    elision_valid = False

    def draw(self, rng):
        self.p.setdefault("nscal", 4)
        routes = OMP_ROUTES if self.o.model == "omp" else ACC_ROUTES
        self.p.setdefault("routes", list(routes))

    def table(self):
        return OMP_ROUTES if self.o.model == "omp" else ACC_ROUTES

    def mod(self):
        return f"{self.name}_m"

    def svars(self, r):
        return [f"s{r}_{j}" for j in range(1, self.p["nscal"] + 1)]

    def modules(self):
        spec, cont = [], []
        o = self.o
        if "declare" in self.p["routes"]:
            dv = [f"g_{j}" for j in range(1, self.p["nscal"] + 1)]
            spec += decl_lines("integer(8)", dv, o.width)
            if o.model == "omp":
                spec += pack("declare target(", [
                    x + ("," if k < len(dv) - 1 else ")")
                    for k, x in enumerate(dv)], "", o.sent, o.width)
            else:
                spec += pack("declare", list_atoms("create", dv), "",
                             o.sent, o.width)
        if "component" in self.p["routes"]:
            spec += [f"type :: {self.name}_sc",
                     *[f"  integer(8) :: c{j}" for j in
                       range(1, self.p["nscal"] + 1)],
                     f"end type {self.name}_sc"]
        cont += [f"  subroutine {self.name}_upd(x)", _dt_line(o),
                 "    integer(8), intent(inout) :: x",
                 "    x = 2 * x + 1", f"  end subroutine {self.name}_upd",
                 f"  function {self.name}_val(x) result(r)", _dt_line(o),
                 "    integer(8), value :: x", "    integer(8) :: r",
                 "    x = 2 * x + 1", "    r = x",
                 f"  end function {self.name}_val"]
        return [Module(self.mod(), spec, cont)]

    def uses(self):
        return [self.mod()]

    def decls(self):
        k = self.p["nscal"]
        d = [f"integer(8) :: rd({k}), a(4), hv", "integer :: j, ii"]
        for r, route in enumerate(self.p["routes"]):
            if route in ("declare", "component"):
                continue
            attr = ", target" if route == "target_attr" else ""
            d += decl_lines(f"integer(8){attr}", self.svars(r), self.o.width)
        if "component" in self.p["routes"]:
            d.append(f"type({self.name}_sc) :: xc")
        return d

    def h(self, r, j):
        return 100 * (r + 1) + j

    def names(self, r, route):
        k = self.p["nscal"]
        if route == "declare":
            return [f"g_{j}" for j in range(1, k + 1)]
        if route == "component":
            return [f"xc%c{j}" for j in range(1, k + 1)]
        return self.svars(r)

    def route_lines(self, r, route) -> list[str]:
        o = self.o
        ind = "    "
        S = self.names(r, route)
        k = len(S)
        lines = [f"{ind}! route {route}", f"{ind}rd = -1", f"{ind}a = 0"]
        lines += [f"{ind}{s} = {self.h(r, j)}" for j, s in enumerate(S, 1)]
        read_first = OMP_ROUTES.get(route, ACC_ROUTES.get(route))[0]
        dev = []
        if route in ("from", "copyout"):
            dev += [f"{s} = {self.h(r, j)} + 0" for j, s in enumerate(S, 1)]
        if route == "private":
            dev += [f"{s} = {j} * 5" for j, s in enumerate(S, 1)]
        if route == "byref":
            dev += [f"rd({j}) = {s}" for j, s in enumerate(S, 1)]
            dev += [f"call {self.name}_upd({s})" for s in S]
            dev += [f"a({min(4, j)}) = a({min(4, j)}) + {s}"
                    for j, s in enumerate(S, 1)]
        elif route == "value":
            dev += [f"rd({j}) = {self.name}_val({s}) - {s}"
                    for j, s in enumerate(S, 1)]
            dev += [f"a(1) = a(1) + {s}" for s in S]
        elif route == "reduction":
            pass
        else:
            dev += [f"rd({j}) = {s}" for j, s in enumerate(S, 1)]
            dev += [f"{s} = 2 * {s} + 1" for s in S]
            dev += ["a(1) = a(1) + 1"]
        pre, post = [], []
        atoms = []
        name = "target" if o.model == "omp" else "serial"
        data = [("rd", "tofrom"), ("a", "tofrom")]
        if o.model == "omp":
            if route in ("firstprivate", "private"):
                atoms = list_atoms(route, S)
            elif route in ("to", "from", "tofrom"):
                data = [(s, route) for s in S] + data
            elif route.startswith("dm_"):
                atoms = [f"defaultmap({route[3:]}: scalar)"]
            elif route == "present_implicit":
                pre += pack("target enter data", list_atoms("map", S, "to"),
                            ind, o.sent, o.width)
                pre += [f"{ind}{s} = {self.h(r, j)} + 1000"
                        for j, s in enumerate(S, 1)]
                post += pack("target exit data", list_atoms("map", S,
                                                            "delete"),
                             ind, o.sent, o.width)
            elif route == "present_update":
                pre += pack("target enter data", list_atoms("map", S, "to"),
                            ind, o.sent, o.width)
                pre += [f"{ind}{s} = {self.h(r, j)} + 1000"
                        for j, s in enumerate(S, 1)]
                pre += pack("target update", list_atoms("to", S), ind,
                            o.sent, o.width)
                data = [(s, "tofrom") for s in S] + data
                post += pack("target update", list_atoms("from", S), ind,
                             o.sent, o.width)
                post += pack("target exit data", list_atoms("map", S,
                                                            "delete"),
                             ind, o.sent, o.width)
            elif route == "declare":
                pre += pack("target update", list_atoms("to", S), ind,
                            o.sent, o.width)
                post += pack("target update", list_atoms("from", S), ind,
                             o.sent, o.width)
            elif route == "reduction":
                name = "target teams distribute parallel do"
                atoms = list_atoms("reduction", S, "+")
        else:
            if route == "implicit_parallel":
                name = "parallel"
                atoms = ["num_gangs(1)"]
            elif route == "implicit_kernels":
                name = "kernels"
            elif route in ("copy", "copyin", "copyout", "firstprivate",
                           "private"):
                atoms = list_atoms(route, S)
            elif route == "data_copy":
                pre += pack("data", list_atoms("copy", S), ind, o.sent,
                            o.width)
                post += [f"{ind}{o.sent} end data"]
            elif route == "enter_implicit":
                pre += pack("enter data", list_atoms("copyin", S), ind,
                            o.sent, o.width)
                pre += [f"{ind}{s} = {self.h(r, j)} + 1000"
                        for j, s in enumerate(S, 1)]
                post += pack("exit data", list_atoms("delete", S), ind,
                             o.sent, o.width)
            elif route == "declare":
                pre += pack("update", list_atoms("device", S), ind, o.sent,
                            o.width)
                post += pack("update", list_atoms("self", S), ind, o.sent,
                             o.width)
            elif route == "reduction":
                name = "parallel loop"
                atoms = list_atoms("reduction", S, "+")
        lines += pre
        lines += pack(name, data_clauses(o, data) + atoms, ind, o.sent,
                      o.width)
        if route == "reduction":
            lines += [f"{ind}do ii = 1, 4"]
            lines += [f"{ind}  {s} = {s} + {j}" for j, s in enumerate(S, 1)]
            lines += [f"{ind}end do"]
        else:
            lines += [f"{ind}  {x}" for x in dev]
        if not (o.model == "acc" and name == "parallel loop"):
            lines.append(f"{ind}{o.sent} end {name}")
        lines += post
        del read_first, k
        return lines

    def expect(self, r, route):
        """(rd values or None per j, host-after values or None per j)."""
        dr, da, after = self.table()[route]
        k = self.p["nscal"]
        hs = [self.h(r, j) + (1000 if route in ("present_implicit",
                                                "present_update",
                                                "enter_implicit") else 0)
              for j in range(1, k + 1)]
        rd = [None] * k
        aft = [None] * k
        for j in range(k):
            if route == "private":
                rd[j] = (j + 1) * 5
            elif route == "from" or route == "copyout":
                rd[j] = self.h(r, j + 1)
            elif route == "value":
                rd[j] = hs[j] + 1          # 2h+1 - h
            elif route == "reduction":
                rd[j] = None
            elif dr:
                rd[j] = hs[j]
            if da:
                if after == "same":
                    aft[j] = hs[j]
                elif after == "write":
                    base = self.h(r, j + 1) if route in ("from", "copyout") \
                        else hs[j]
                    aft[j] = 2 * base + 1
                elif after == "red":
                    aft[j] = hs[j] + 4 * (j + 1)
        return rd, aft

    def body(self):
        ind = "    "
        lines = [f"{ind}cs = 0"]
        for r, route in enumerate(self.p["routes"]):
            lines += self.route_lines(r, route)
            rd, aft = self.expect(r, route)
            S = self.names(r, route)
            for j, s in enumerate(S, 1):
                if rd[j - 1] is not None:
                    lines.append(f"{ind}cs = mod(cs * 31 + rd({j}), {P}_8)")
                else:
                    lines.append(f"{ind}print '(a,i0,a,i0)', 'OBS "
                                 f"{self.name} {route} rd ', {j}, ' ', "
                                 f"rd({j})")
                if aft[j - 1] is not None:
                    lines.append(f"{ind}cs = mod(cs * 31 + {s}, {P}_8)")
                else:
                    lines.append(f"{ind}hv = {s}")
                    lines.append(f"{ind}print '(a,i0,a,i0)', 'OBS "
                                 f"{self.name} {route} host ', {j}, ' ', hv")
        return lines

    def value(self):
        cs = 0
        for r, route in enumerate(self.p["routes"]):
            rd, aft = self.expect(r, route)
            for j in range(self.p["nscal"]):
                if rd[j] is not None:
                    cs = (cs * 31 + rd[j]) % P
                if aft[j] is not None:
                    cs = (cs * 31 + aft[j]) % P
        return cs

    def smaller(self):
        rs = self.p["routes"]
        out = []
        if len(rs) > 1:
            h = len(rs) // 2
            out += [self.clone(routes=rs[:h]), self.clone(routes=rs[h:])]
        if self.p["nscal"] > 1:
            out.append(self.clone(nscal=1))
        return out

    def features(self):
        return super().features() | {f"route:{r}" for r in self.p["routes"]}


# --- reductions + atomics + criticals, expressions, async, runtime -----------------------------

class MixedKernel(Kernel):
    """`nred` reduction variables (cycling operators), `natom` counters
    updated by atomic update, a histogram updated in `ncrit` named critical
    sections (OpenMP: in a target parallel do, no teams: Ruling of
    offload.engine.fuzz on critical and teams), all in one loop. OpenACC: the
    reductions and atomics (OpenACC has no critical)."""
    kind = "mixed"

    def draw(self, rng):
        self.p.setdefault("nred", 4)
        self.p.setdefault("natom", 2)
        self.p.setdefault("ncrit", 2 if self.o.model == "omp" else 0)
        self.p.setdefault("n", 512)

    def decls(self):
        nr, na, nc = self.p["nred"], self.p["natom"], self.p["ncrit"]
        d = ["integer :: i", f"integer(8) :: hist({max(1, nc)}, 8)"]
        if nr:
            d += decl_lines("integer(8)", [vname("r", j) for j in
                                           range(1, nr + 1)], self.o.width)
        if na:
            d += decl_lines("integer(8)", [vname("q", j) for j in
                                           range(1, na + 1)], self.o.width)
        return d

    def body(self):
        nr, na, nc, n = (self.p["nred"], self.p["natom"], self.p["ncrit"],
                         self.p["n"])
        o = self.o
        ind = "    "
        R = [vname("r", j) for j in range(1, nr + 1)]
        Q = [vname("q", j) for j in range(1, na + 1)]
        ops = [("+", "max", "ieor", "ior")[j % 4] for j in range(nr)]
        lines = [f"{ind}{x} = 0" for x in R + Q] + [f"{ind}hist = 0"]
        groups: dict[str, list[str]] = {}
        for x, op in zip(R, ops):
            groups.setdefault(op, []).append(x)
        red = [(op, groups[op]) for op in ("+", "max", "ieor", "ior")
               if op in groups]
        chain = ("target parallel do",) if o.model == "omp" else \
            ("parallel loop gang vector",)
        op_, cl, ii = region(o, chain, ind, reduction=red,
                             data=[(x, "tofrom") for x in Q] +
                             [("hist", "tofrom")])
        lines += op_ + [f"{ii}do i = 1, {n}"]
        for j, (x, op) in enumerate(zip(R, ops)):
            e = f"int(mod(i * {j + 3}, 4099), 8)"
            lines.append(f"{ii}  {x} = " + {
                "+": f"{x} + {e}", "max": f"max({x}, {e})",
                "ieor": f"ieor({x}, {e})",
                "ior": f"ior({x}, {e})"}[op])
        for j, x in enumerate(Q):
            lines += [f"{ii}  {o.sent} atomic update",
                      f"{ii}  {x} = {x} + mod(i, {j + 2})"]
        for c in range(1, nc + 1):
            lines += [f"{ii}  {o.sent} critical (c{self.name}_{c})",
                      f"{ii}  hist({c}, mod(i, 8) + 1) = "
                      f"hist({c}, mod(i, 8) + 1) + {c}",
                      f"{ii}  {o.sent} end critical (c{self.name}_{c})"]
        lines += [f"{ii}end do"] + cl
        lines.append(f"{ind}call st_cksum(hist, {max(1, nc) * 8}, cs)")
        for x in R + Q:
            lines.append(f"{ind}cs = mod(cs * 31 + {x}, {P}_8)")
        return lines

    def value(self):
        nr, na, nc, n = (self.p["nred"], self.p["natom"], self.p["ncrit"],
                         self.p["n"])
        hist = [[0] * 8 for _ in range(max(1, nc))]
        for c in range(1, nc + 1):
            for i in range(1, n + 1):
                hist[c - 1][i % 8] += c
        flat = [hist[c][b] for b in range(8) for c in range(max(1, nc))]
        cs = cksum(flat)
        ops = [("+", "max", "ieor", "ior")[j % 4] for j in range(nr)]
        for j, op in enumerate(ops):
            v = 0
            for i in range(1, n + 1):
                e = (i * (j + 3)) % 4099
                v = {"+": v + e, "max": max(v, e), "ieor": v ^ e,
                     "ior": v | e}[op]
            cs = (cs * 31 + v) % P
        for j in range(na):
            cs = (cs * 31 + sum(i % (j + 2) for i in range(1, n + 1))) % P
        return cs

    def smaller(self):
        out = []
        for key in ("nred", "natom", "ncrit"):
            if self.p[key] > 0:
                out.append(self.clone(**{key: self.p[key] // 2}))
        return out

    def features(self):
        f = super().features() | {f"len:mixed:{self.p['nred']}"}
        if self.p["natom"]:
            f.add("dir:atomic")
        if self.p["ncrit"]:
            f.add("dir:critical")
        return f


class ExprsKernel(Kernel):
    """Compile-time stress in device code: 'expr', one assignment of
    `size` terms (continuation lines: past 255 an illegal probe); 'select',
    a SELECT CASE of `size` cases in a device function; 'spec', `size`
    device functions (specializations) dispatched by a SELECT CASE."""
    kind = "exprs"

    def draw(self, rng):
        self.p.setdefault("variant", rng.choice(("expr", "select", "spec")))
        self.p.setdefault("size", 64)
        self.p.setdefault("n", 256)

    def modules(self):
        v, k = self.p["variant"], self.p["size"]
        dt = _dt_line(self.o)
        cont = []
        if v == "select":
            cont += [f"  function {self.name}_sel(x) result(r)", dt,
                     "    integer(8), intent(in) :: x", "    integer(8) :: r",
                     f"    select case (mod(x, {k}_8))"]
            for c in range(k):
                cont += [f"    case ({c})", f"      r = x * {c % 17 + 1} + "
                         f"{c}"]
            cont += ["    case default", "      r = -1", "    end select",
                     f"  end function {self.name}_sel"]
        if v == "spec":
            for c in range(k):
                cont += [f"  function {self.name}_s{c}(x) result(r)", dt,
                         "    integer(8), intent(in) :: x",
                         "    integer(8) :: r",
                         f"    r = x * {c % 17 + 1} + {c}",
                         f"  end function {self.name}_s{c}"]
            cont += [f"  function {self.name}_sel(x) result(r)", dt,
                     "    integer(8), intent(in) :: x", "    integer(8) :: r",
                     f"    select case (mod(x, {k}_8))"]
            for c in range(k):
                cont += [f"    case ({c})", f"      r = {self.name}_s{c}(x)"]
            cont += ["    case default", "      r = -1", "    end select",
                     f"  end function {self.name}_sel"]
        return [Module(f"{self.name}_m", [], cont)] if cont else []

    def uses(self):
        return [f"{self.name}_m"] if self.p["variant"] != "expr" else []

    def decls(self):
        return [f"integer(8) :: out({self.p['n']})", "integer :: i"]

    def body(self):
        v, k, n = self.p["variant"], self.p["size"], self.p["n"]
        ind = "    "
        chain = ("target teams distribute parallel do",) if \
            self.o.model == "omp" else ("parallel loop gang vector",)
        op, cl, ii = region(self.o, chain, ind, data=[("out", "tofrom")])
        lines = [f"{ind}out = 0"] + op + [f"{ii}do i = 1, {n}"]
        if v == "expr":
            terms = [f"mod(i * {c % 97 + 1}, {c % 13 + 2})"
                     for c in range(k)]
            lines += pack("out(i) =", [t + (" +" if c < k - 1 else "")
                                       for c, t in enumerate(terms)],
                          ii + "  ", None, self.o.width)
        else:
            lines.append(f"{ii}  out(i) = {self.name}_sel(int(i, 8))")
        lines += [f"{ii}end do"] + cl
        lines.append(f"{ind}call st_cksum(out, {n}, cs)")
        return lines

    def value(self):
        v, k, n = self.p["variant"], self.p["size"], self.p["n"]
        if v == "expr":
            return cksum(sum((i * (c % 97 + 1)) % (c % 13 + 2)
                             for c in range(k)) for i in range(1, n + 1))
        return cksum(i * ((i % k) % 17 + 1) + (i % k)
                     for i in range(1, n + 1))

    def smaller(self):
        return [self.clone(size=m) for m in _halve(self.p["size"])]

    def features(self):
        return super().features() | {f"exprs:{self.p['variant']}",
                                     f"len:exprs:{self.p['size']}"}


class AsyncKernel(Kernel):
    """`ntasks` concurrent target tasks: each enters its own array (target
    enter data nowait depend(out:)), a target nowait depend(inout:)
    computes, the host updates another array, target update from nowait
    depend(in:) brings it back; one taskwait. OpenACC: the same over
    `ntasks` async queues (enter data async, parallel loop async, update
    self async) and one wait."""
    kind = "async"

    def draw(self, rng):
        self.p.setdefault("ntasks", 8)
        self.p.setdefault("m", 64)

    def decls(self):
        k, m = self.p["ntasks"], self.p["m"]
        return [f"integer(8) :: x({m}, {k}), h({m}, {k})",
                "integer :: i, t", "integer(8) :: tcs"]

    def body(self):
        k, m = self.p["ntasks"], self.p["m"]
        o = self.o
        ind = "    "
        lines = [f"{ind}do t = 1, {k}", f"{ind}  do i = 1, {m}",
                 f"{ind}    x(i, t) = i + t", f"{ind}    h(i, t) = 0",
                 f"{ind}  end do", f"{ind}end do"]
        if o.model == "omp":
            lines += [f"{ind}do t = 1, {k}",
                      f"{ind}  {o.sent} target enter data map(to: x(:, t)) "
                      "nowait depend(out: x(:, t))",
                      f"{ind}  {o.sent} target teams distribute parallel do "
                      "nowait depend(inout: x(:, t))",
                      f"{ind}  do i = 1, {m}",
                      f"{ind}    x(i, t) = x(i, t) * 3 + t",
                      f"{ind}  end do",
                      f"{ind}  {o.sent} end target teams distribute parallel "
                      "do",
                      f"{ind}  {o.sent} target exit data map(from: x(:, t)) "
                      "nowait depend(inout: x(:, t))",
                      f"{ind}  do i = 1, {m}", f"{ind}    h(i, t) = i * t",
                      f"{ind}  end do",
                      f"{ind}end do", f"{ind}{o.sent} taskwait"]
        else:
            lines += [f"{ind}do t = 1, {k}",
                      f"{ind}  {o.sent} enter data copyin(x(:, t)) async(t)",
                      f"{ind}  {o.sent} parallel loop present(x(:, t)) "
                      "async(t)",
                      f"{ind}  do i = 1, {m}",
                      f"{ind}    x(i, t) = x(i, t) * 3 + t",
                      f"{ind}  end do",
                      f"{ind}  {o.sent} exit data copyout(x(:, t)) async(t)",
                      f"{ind}  do i = 1, {m}", f"{ind}    h(i, t) = i * t",
                      f"{ind}  end do",
                      f"{ind}end do", f"{ind}{o.sent} wait"]
        lines += [f"{ind}cs = 0", f"{ind}do t = 1, {k}",
                  f"{ind}  call st_cksum(x(:, t), {m}, tcs)",
                  f"{ind}  cs = mod(cs * 31 + tcs, {P}_8)",
                  f"{ind}  call st_cksum(h(:, t), {m}, tcs)",
                  f"{ind}  cs = mod(cs * 31 + tcs, {P}_8)", f"{ind}end do"]
        return lines

    def value(self):
        k, m = self.p["ntasks"], self.p["m"]
        cs = 0
        for t in range(1, k + 1):
            cs = (cs * 31 + cksum((i + t) * 3 + t for i in range(1, m + 1))) \
                % P
            cs = (cs * 31 + cksum(i * t for i in range(1, m + 1))) % P
        return cs

    def smaller(self):
        return [self.clone(ntasks=x) for x in _halve(self.p["ntasks"])]

    def features(self):
        return super().features() | {f"len:async:{self.p['ntasks']}"}


class RuntimeKernel(Kernel):
    """Runtime stress: 'iters', a reduction over `size` iterations of
    mod(i*c, 1009) (the model uses its period); 'teams', num_teams(size)
    thread_limit(t) over `size`*t iterations; 'alloc', an allocatable of
    `size` 8-byte elements (bounded: the size is in the header) filled and
    reduced on the device."""
    kind = "runtime"

    def draw(self, rng):
        self.p.setdefault("variant", "iters")
        self.p.setdefault("size", 1 << 20)
        self.p.setdefault("c", rng.randrange(1, 1009))

    def decls(self):
        d = ["integer(8) :: i, nn, s"]
        if self.p["variant"] == "alloc":
            d.append("integer(8), allocatable :: big(:)")
        return d

    def iters(self):
        if self.p["variant"] == "teams":
            return self.p["size"] * 256
        return self.p["size"]

    def body(self):
        v, c = self.p["variant"], self.p["c"]
        o = self.o
        ind = "    "
        nn = self.iters()
        lines = [f"{ind}nn = {nn}_8", f"{ind}s = 0"]
        if v == "alloc":
            lines.append(f"{ind}allocate(big(nn))")
            if o.model == "omp":
                lines += [f"{ind}{o.sent} target enter data map(alloc: big)"]
                op, cl, ii = region(o, ("target teams distribute parallel "
                                        "do",), ind)
            else:
                lines += [f"{ind}{o.sent} enter data create(big)"]
                op, cl, ii = region(o, ("parallel loop gang vector",), ind,
                                    extra=["present(big)"])
            lines += op + [f"{ii}do i = 1, nn",
                           f"{ii}  big(i) = mod(i * {c}, 1009_8)",
                           f"{ii}end do"] + cl
            op, cl, ii = region(o, ("target teams distribute parallel do",)
                                if o.model == "omp" else
                                ("parallel loop gang vector",), ind,
                                reduction=[("+", ["s"])],
                                extra=["present(big)"] if o.model == "acc"
                                else [])
            lines += op + [f"{ii}do i = 1, nn", f"{ii}  s = s + big(i)",
                           f"{ii}end do"] + cl
            lines.append(f"{ind}{o.sent} target exit data map(delete: big)"
                         if o.model == "omp" else
                         f"{ind}{o.sent} exit data delete(big)")
            lines.append(f"{ind}deallocate(big)")
        else:
            extra = []
            if v == "teams" and o.model == "omp":
                extra = [f"num_teams({self.p['size']})",
                         "thread_limit(256)"]
            if v == "teams" and o.model == "acc":
                extra = [f"num_gangs({self.p['size']})", "vector_length(256)"]
            chain = ("target teams distribute parallel do",) if \
                o.model == "omp" else ("parallel loop gang vector",)
            op, cl, ii = region(o, chain, ind, reduction=[("+", ["s"])],
                                extra=extra)
            lines += op + [f"{ii}do i = 1, nn",
                           f"{ii}  s = s + mod(i * {c}, 1009_8)",
                           f"{ii}end do"] + cl
        lines.append(f"{ind}cs = mod(s, {P}_8)")
        return lines

    def value(self):
        c, nn = self.p["c"], self.iters()
        per = sum((i * c) % 1009 for i in range(1009))
        q, r = divmod(nn, 1009)
        s = q * per + sum((i * c) % 1009 for i in range(1, r + 1))
        # i runs 1..nn: the block 1..1009 has the same sum as 0..1008
        return s % P

    def smaller(self):
        return [self.clone(size=max(1, self.p["size"] // 16))] if \
            self.p["size"] > 16 else []

    def features(self):
        return super().features() | {f"runtime:{self.p['variant']}"}

    def bytes(self) -> int:
        return 8 * self.iters() if self.p["variant"] == "alloc" else 0


# --- templates: shapes of failing real kernels ----------------------------------------------------

TEMPLATES = ("team_private", "declared_alloc", "mfc_cbc", "mfc_bubbles")


class TemplateKernel(Kernel):
    """Kernel shapes of failing real kernels (structure only), varied:

    * team_private: an array private to each team (teams distribute
      private(t)) written and read by nested parallel loops (the
      widened program teams-private-array-parallel: AFAR and every CCE
      wrong; PRK transpose tile32 has the same shape with collapse(2) and
      simd); `w` tile width, `nloops` nested loops, collapse / simd;
    * declared_alloc: a declare target module variable of a derived type
      with `ncomp` allocatable components entered by enter data (MFC under CCE at unified memory);
    * mfc_cbc: MFC's s_cbc kernel (m_cbc.fpp:597, CCE 20 device-link
      crash): collapse(2), a long private list of scalars and private
      arrays (`npriv` extra scalars), loop bounds from components of a
      device-resident module derived type, inner sequential loops, device
      routines with array arguments, a module logical branch;
    * mfc_bubbles: MFC's s_compute_bubble_EE_source (m_bubbles_EE.fpp:186,
      CCE 21 device-link crash): an array of derived type with a pointer (or
      allocatable) 3-D component indexed through integer index arrays,
      collapse(3), private arrays, a device function with an OPTIONAL
      argument passed by keyword, a counter updated atomically."""
    kind = "template"

    def draw(self, rng):
        v = self.p.setdefault("variant", rng.choice(TEMPLATES))
        if v == "team_private":
            self.p.setdefault("w", rng.choice((4, 8, 32)))
            self.p.setdefault("nt", 16)
            self.p.setdefault("nloops", 2)
            self.p.setdefault("col2", rng.random() < 0.5)
            self.p.setdefault("simd", rng.random() < 0.5)
        elif v == "declared_alloc":
            self.p.setdefault("ncomp", 2)
            self.p.setdefault("n", 64)
        elif v == "mfc_cbc":
            self.p.setdefault("npriv", 40)
            self.p.setdefault("nf", 3)
            self.p.setdefault("nk", 6)
            self.p.setdefault("nr", 5)
        else:
            self.p.setdefault("nb", 3)
            self.p.setdefault("ext", [4, 3, 2])
            self.p.setdefault("ptr", rng.random() < 0.5)

    # team_private ------------------------------------------------------------
    def _tp_body(self):
        w, nt, nl = self.p["w"], self.p["nt"], self.p["nloops"]
        col2, simd = self.p["col2"], self.p["simd"]
        o = self.o
        ind = "    "
        n = w * nt
        lines = [f"{ind}do i = 1, {n}", f"{ind}  a(i) = mod(i * 7, 61)",
                 f"{ind}end do", f"{ind}b = 0"]
        inner = "parallel do simd" if simd else "parallel do"
        if o.model == "acc":
            return self._tp_body_acc(lines, n)
        if col2:
            # 2-D tiles: n = (w*nt) elements as (w, nt) blocks of a 2-D view
            head = pack("target teams distribute collapse(2)",
                        ["private(t, j, jj)", "map(to: a)", "map(tofrom: b)"],
                        ind, o.sent, o.width)
            lines += head + [f"{ind}do jt = 1, {nt}, 2", f"{ind}  do kt = 0, 1"]
            ii = ind + "    "
            lines += [f"{ii}{o.sent} {inner} collapse(2)",
                      f"{ii}do j = 0, {w - 1}", f"{ii}  do jj = 0, 0",
                      f"{ii}    t(j) = a((jt + kt - 1) * {w} + j + 1)",
                      f"{ii}  end do", f"{ii}end do",
                      f"{ii}{o.sent} end {inner}"]
            for L in range(1, nl):
                lines += [f"{ii}{o.sent} {inner} collapse(2)",
                          f"{ii}do j = 0, {w - 1}", f"{ii}  do jj = 0, 0",
                          f"{ii}    b((jt + kt - 1) * {w} + j + 1) = "
                          f"b((jt + kt - 1) * {w} + j + 1) + "
                          f"{L + 1} * t({w - 1} - j) + {L}",
                          f"{ii}  end do", f"{ii}end do",
                          f"{ii}{o.sent} end {inner}"]
            lines += [f"{ind}  end do", f"{ind}end do",
                      f"{ind}{o.sent} end target teams distribute"]
        else:
            head = pack("target teams distribute",
                        ["private(t, j)", "map(to: a)", "map(tofrom: b)"],
                        ind, o.sent, o.width)
            lines += head + [f"{ind}do jt = 1, {n}, {w}"]
            ii = ind + "  "
            lines += [f"{ii}{o.sent} {inner}", f"{ii}do j = 0, {w - 1}",
                      f"{ii}  t(j) = a(jt + j)", f"{ii}end do",
                      f"{ii}{o.sent} end {inner}"]
            for L in range(1, nl):
                lines += [f"{ii}{o.sent} {inner}", f"{ii}do j = 0, {w - 1}",
                          f"{ii}  b(jt + j) = b(jt + j) + {L + 1} * "
                          f"t({w - 1} - j) + {L}", f"{ii}end do",
                          f"{ii}{o.sent} end {inner}"]
            lines += [f"{ind}end do", f"{ind}{o.sent} end target teams "
                      "distribute"]
        lines.append(f"{ind}call st_cksum(b, {n}, cs)")
        return lines

    def _tp_body_acc(self, lines, n):
        w, nt, nl = self.p["w"], self.p["nt"], self.p["nloops"]
        o = self.o
        ind = "    "
        lines += pack("parallel loop gang", ["private(t)", "copyin(a)",
                                             "copy(b)"], ind, o.sent, o.width)
        lines += [f"{ind}do jt = 1, {n}, {w}"]
        ii = ind + "  "
        lines += [f"{ii}{o.sent} loop vector", f"{ii}do j = 0, {w - 1}",
                  f"{ii}  t(j) = a(jt + j)", f"{ii}end do"]
        for L in range(1, nl):
            lines += [f"{ii}{o.sent} loop vector", f"{ii}do j = 0, {w - 1}",
                      f"{ii}  b(jt + j) = b(jt + j) + {L + 1} * "
                      f"t({w - 1} - j) + {L}", f"{ii}end do"]
        lines += [f"{ind}end do", f"{ind}{o.sent} end parallel loop"]
        lines.append(f"{ind}call st_cksum(b, {n}, cs)")
        return lines

    def _tp_value(self):
        w, nt, nl = self.p["w"], self.p["nt"], self.p["nloops"]
        n = w * nt
        a = [0] + [(i * 7) % 61 for i in range(1, n + 1)]
        b = [0] * (n + 1)
        for blk in range(nt):
            base = blk * w
            t = [a[base + j + 1] for j in range(w)]
            for L in range(1, nl):
                for j in range(w):
                    b[base + j + 1] += (L + 1) * t[w - 1 - j] + L
        return cksum(b[1:])

    # declared_alloc -----------------------------------------------------------
    def _da_modules(self):
        k = self.p["ncomp"]
        o = self.o
        spec = [f"type :: {self.name}_rec"] + [
            f"  integer(8), allocatable :: v{c}(:)" for c in range(1, k + 1)
        ] + [f"end type {self.name}_rec", f"type({self.name}_rec) :: gq"]
        spec.append(f"{o.sent} declare target(gq)" if o.model == "omp" else
                    f"{o.sent} declare create(gq)")
        return [Module(f"{self.name}_m", spec)]

    def _da_body(self):
        k, n = self.p["ncomp"], self.p["n"]
        o = self.o
        ind = "    "
        lines = []
        comps = [f"gq%v{c}" for c in range(1, k + 1)]
        for c, x in enumerate(comps, 1):
            lines += [f"{ind}allocate({x}({n}))", f"{ind}do i = 1, {n}",
                      f"{ind}  {x}(i) = i * {c + 2}", f"{ind}end do"]
        if o.model == "omp":
            lines += pack("target enter data", list_atoms("map", comps, "to"),
                          ind, o.sent, o.width)
        else:
            lines += pack("enter data", list_atoms("copyin", comps), ind,
                          o.sent, o.width)
        chain = ("target teams distribute parallel do",) if \
            o.model == "omp" else ("parallel loop",)
        op, cl, ii = region(o, chain, ind, data=[("out", "tofrom")])
        lines += [f"{ind}out = 0"] + op + [f"{ii}do i = 1, {n}"]
        lines += sum_lines(ii + "  ", "out(i)", [f"{x}(i)" for x in comps],
                           o.width)
        lines += [f"{ii}  out(i) = out(i) + 1", f"{ii}end do"] + cl
        if o.model == "omp":
            lines += pack("target exit data", list_atoms("map", comps,
                                                         "delete"),
                          ind, o.sent, o.width)
        else:
            lines += pack("exit data", list_atoms("delete", comps), ind,
                          o.sent, o.width)
        lines += [f"{ind}deallocate({x})" for x in comps]
        lines.append(f"{ind}call st_cksum(out, {n}, cs)")
        return lines

    def _da_value(self):
        k, n = self.p["ncomp"], self.p["n"]
        return cksum(sum(i * (c + 2) for c in range(1, k + 1)) + 1
                     for i in range(1, n + 1))

    # mfc_cbc -------------------------------------------------------------------
    def _cbc_dims(self):
        nf = self.p["nf"]
        e = nf + 3 + 1
        return nf, e, e + nf          # nf, eqn%e, nv

    def _cbc_modules(self):
        o = self.o
        nm = self.name
        spec = [f"type :: {nm}_bnd", "  integer :: beg, end",
                f"end type {nm}_bnd", f"type :: {nm}_eqn",
                f"  type({nm}_bnd) :: cont, adv", "  integer :: e",
                f"end type {nm}_eqn", f"type({nm}_eqn) :: eqn",
                "integer :: ndims", "logical :: chem"]
        spec.append(f"{o.sent} declare target(eqn, ndims, chem)"
                    if o.model == "omp" else
                    f"{o.sent} declare create(eqn, ndims, chem)")
        dt = _dt_line(o)
        cont = [f"  subroutine {nm}_mix(rho, gam, ar, al, nf)", dt,
                "    integer, intent(in) :: nf",
                "    integer(8), intent(in) :: ar(nf), al(nf)",
                "    integer(8), intent(out) :: rho, gam", "    integer :: i",
                "    rho = 0", "    gam = 0", "    do i = 1, nf",
                "      rho = rho + ar(i)",
                "      gam = mod(gam + al(i) * ar(i), 1009_8)", "    end do",
                f"  end subroutine {nm}_mix",
                f"  subroutine {nm}_snd(pres, rho, gam, c)", dt,
                "    integer(8), intent(in) :: pres, rho, gam",
                "    integer(8), intent(out) :: c",
                "    c = mod(pres * 3 + rho + gam, 10007_8)",
                f"  end subroutine {nm}_snd"]
        return [Module(f"{nm}_m", spec, cont)]

    def _cbc_privs(self):
        return [vname("x", j) for j in range(1, self.p["npriv"] + 1)]

    def _cbc_body(self):
        nf, e, nv = self._cbc_dims()
        nk, nr = self.p["nk"], self.p["nr"]
        o = self.o
        nm = self.name
        ind = "    "
        X = self._cbc_privs()
        lines = [f"{ind}eqn%cont%beg = 1", f"{ind}eqn%cont%end = {nf}",
                 f"{ind}eqn%e = {e}", f"{ind}eqn%adv%beg = {e + 1}",
                 f"{ind}eqn%adv%end = {e + nf}", f"{ind}ndims = 3",
                 f"{ind}chem = .true."]
        lines.append(f"{ind}{o.sent} target update to(eqn, ndims, chem)"
                     if o.model == "omp" else
                     f"{ind}{o.sent} update device(eqn, ndims, chem)")
        lines += [f"{ind}allocate(q(0:2, {nk}, {nr}, {nv}))",
                  f"{ind}do v = 1, {nv}", f"{ind}  do r = 1, {nr}",
                  f"{ind}    do k = 1, {nk}", f"{ind}      do b = 0, 2",
                  f"{ind}        q(b, k, r, v) = mod(b * 7 + k * 3 + r * 5 "
                  "+ v, 101)",
                  f"{ind}      end do", f"{ind}    end do", f"{ind}  end do",
                  f"{ind}end do", f"{ind}flux = 0", f"{ind}dir_idx = 2"]
        priv = ["r", "k", "i", "alpha_rho", "vel", "adv", "rho", "gam",
                "pres", "c", "accum"] + X
        if o.model == "omp":
            chain = ("target teams distribute parallel do",)
            data = [("q", "to"), ("flux", "tofrom"), ("dir_idx", "to")]
        else:
            chain = ("parallel loop gang vector",)
            data = [("q", "to"), ("flux", "tofrom"), ("dir_idx", "to")]
        op, cl, ii = region(o, chain, ind, data=data, private=priv,
                            collapse=2)
        seq = [f"{o.sent} loop seq"] if o.model == "acc" else []
        lines += op + [f"{ii}do r = 1, {nr}", f"{ii}  do k = 1, {nk}"]
        jj = ii + "    "
        lines += [jj + s for s in seq] + [
            f"{jj}do i = 1, eqn%cont%end",
            f"{jj}  alpha_rho(i) = q(0, k, r, i)", f"{jj}end do"]
        lines += [jj + s for s in seq] + [
            f"{jj}do i = 1, ndims",
            f"{jj}  vel(i) = q(0, k, r, eqn%cont%end + i)", f"{jj}end do",
            f"{jj}pres = q(dir_idx - 2, k, r, eqn%e)"]
        lines += [jj + s for s in seq] + [
            f"{jj}do i = 1, eqn%adv%end - eqn%e",
            f"{jj}  adv(i) = q(0, k, r, eqn%e + i)", f"{jj}end do",
            f"{jj}call {nm}_mix(rho, gam, alpha_rho, adv, eqn%cont%end)",
            f"{jj}if (chem) then", f"{jj}  pres = pres + 7", f"{jj}end if",
            f"{jj}call {nm}_snd(pres, rho, gam, c)", f"{jj}accum = 0"]
        for j, x in enumerate(X, 1):
            lines.append(f"{jj}{x} = mod(c + {j} * k, 97_8)")
        lines += sum_lines(jj, "accum", X, o.width)
        lines += [f"{jj}flux(k, r) = c + vel(1) + vel(2) + vel(3) + accum",
                  f"{ii}  end do", f"{ii}end do"] + cl
        lines += [f"{ind}call st_cksum(flux, {nk * nr}, cs)",
                  f"{ind}deallocate(q)"]
        return lines

    def _cbc_value(self):
        nf, e, nv = self._cbc_dims()
        nk, nr = self.p["nk"], self.p["nr"]

        def q(b, k, r, v):
            return (b * 7 + k * 3 + r * 5 + v) % 101
        flux = {}
        for r in range(1, nr + 1):
            for k in range(1, nk + 1):
                ar = [q(0, k, r, i) for i in range(1, nf + 1)]
                vel = [q(0, k, r, nf + i) for i in range(1, 4)]
                pres = q(0, k, r, e) + 7
                adv = [q(0, k, r, e + i) for i in range(1, nf + 1)]
                rho = sum(ar)
                gam = 0
                for i in range(nf):
                    gam = (gam + adv[i] * ar[i]) % 1009
                c = (pres * 3 + rho + gam) % 10007
                acc = sum((c + j * k) % 97 for j in
                          range(1, self.p["npriv"] + 1))
                flux[(k, r)] = c + sum(vel) + acc
        return cksum(flux[(k, r)] for r in range(1, nr + 1)
                     for k in range(1, nk + 1))

    # mfc_bubbles ---------------------------------------------------------------
    def _bub_modules(self):
        o = self.o
        nm = self.name
        attr = "pointer" if self.p["ptr"] else "allocatable"
        init = " => null()" if self.p["ptr"] else ""
        spec = [f"type :: {nm}_sf",
                f"  integer(8), {attr} :: sf(:, :, :){init}",
                f"end type {nm}_sf"]
        dt = _dt_line(o)
        cont = [f"  function {nm}_f(a, b, scale) result(r)", dt,
                "    integer(8), intent(in) :: a, b",
                "    integer(8), intent(in), optional :: scale",
                "    integer(8) :: r", "    if (present(scale)) then",
                "      r = a + b * scale", "    else", "      r = a + b",
                "    end if", f"  end function {nm}_f"]
        return [Module(f"{nm}_m", spec, cont)]

    def _bub_body(self):
        nb = self.p["nb"]
        m, n, p_ = self.p["ext"]
        nv = 2 * nb + 1
        o = self.o
        nm = self.name
        ind = "    "
        lines = []
        for v in range(1, nv + 1):
            lines += [f"{ind}allocate(qp({v})%sf(0:{m - 1}, 0:{n - 1}, "
                      f"0:{p_ - 1}))",
                      f"{ind}do l = 0, {p_ - 1}", f"{ind}  do k = 0, {n - 1}",
                      f"{ind}    do j = 0, {m - 1}",
                      f"{ind}      qp({v})%sf(j, k, l) = mod(j * 3 + k * 5 + "
                      f"l * 7 + {v}, 37)",
                      f"{ind}    end do", f"{ind}  end do", f"{ind}end do"]
        lines += [f"{ind}do q = 1, {nb}", f"{ind}  rs(q) = q + 1",
                  f"{ind}  vs(q) = q + 1 + {nb}", f"{ind}  w(q) = q",
                  f"{ind}end do", f"{ind}cnt = 0", f"{ind}src = 0"]
        comps = [f"qp({v})%sf" for v in range(1, nv + 1)]
        if o.model == "omp":
            lines.append(f"{ind}{o.sent} target enter data map(to: qp)")
            lines += pack("target enter data", list_atoms("map", comps,
                                                          "to"),
                          ind, o.sent, o.width)
            chain = ("target teams distribute parallel do",)
            extra = []
        else:
            lines.append(f"{ind}{o.sent} enter data copyin(qp)")
            lines += pack("enter data", list_atoms("copyin", comps), ind,
                          o.sent, o.width)
            chain = ("parallel loop gang vector",)
            extra = ["present(qp)"]
        op, cl, ii = region(o, chain, ind,
                            data=[("rs", "to"), ("vs", "to"), ("w", "to"),
                                  ("src", "tofrom"), ("cnt", "tofrom")],
                            private=["j", "k", "l", "q", "rtmp", "vtmp",
                                     "r3", "nbub"], collapse=3, extra=extra)
        seq = [f"{o.sent} loop seq"] if o.model == "acc" else []
        lines += op + [f"{ii}do l = 0, {p_ - 1}", f"{ii}  do k = 0, {n - 1}",
                       f"{ii}    do j = 0, {m - 1}"]
        jj = ii + "      "
        lines += [jj + s for s in seq] + [
            f"{jj}do q = 1, {nb}",
            f"{jj}  rtmp(q) = qp(rs(q))%sf(j, k, l)",
            f"{jj}  vtmp(q) = qp(vs(q))%sf(j, k, l)", f"{jj}end do",
            f"{jj}r3 = 0"]
        lines += [jj + s for s in seq] + [
            f"{jj}do q = 1, {nb}", f"{jj}  r3 = r3 + w(q) * rtmp(q)",
            f"{jj}end do",
            f"{jj}if (mod(j + k + l, 2) == 0) then",
            f"{jj}  nbub = {nm}_f(r3, vtmp(1), scale=3_8)",
            f"{jj}else", f"{jj}  nbub = {nm}_f(r3, vtmp(1))", f"{jj}end if",
            f"{jj}src(j, k, l) = nbub + qp(1)%sf(j, k, l)",
            f"{jj}if (mod(j + k + l, 5) == 0) then",
            f"{jj}  {o.sent} atomic update", f"{jj}  cnt = cnt + 1",
            f"{jj}end if",
            f"{ii}    end do", f"{ii}  end do", f"{ii}end do"] + cl
        if o.model == "omp":
            lines += pack("target exit data", list_atoms(
                "map", comps, "delete"), ind, o.sent, o.width)
            lines.append(f"{ind}{o.sent} target exit data map(delete: qp)")
        else:
            lines += pack("exit data", list_atoms("delete", comps), ind,
                          o.sent, o.width)
            lines.append(f"{ind}{o.sent} exit data delete(qp)")
        lines += [f"{ind}call st_cksum(src, {m * n * p_}, cs)",
                  f"{ind}cs = mod(cs * 31 + cnt, {P}_8)"]
        lines += [f"{ind}deallocate(qp({v})%sf)" for v in range(1, nv + 1)]
        return lines

    def _bub_value(self):
        nb = self.p["nb"]
        m, n, p_ = self.p["ext"]

        def sf(v, j, k, l):
            return (j * 3 + k * 5 + l * 7 + v) % 37
        src, cnt = [], 0
        for l in range(p_):
            for k in range(n):
                for j in range(m):
                    rt = [sf(q + 1, j, k, l) for q in range(1, nb + 1)]
                    vt = [sf(q + 1 + nb, j, k, l) for q in range(1, nb + 1)]
                    r3 = sum(q * rt[q - 1] for q in range(1, nb + 1))
                    nbub = r3 + vt[0] * (3 if (j + k + l) % 2 == 0 else 1)
                    src.append(nbub + sf(1, j, k, l))
                    if (j + k + l) % 5 == 0:
                        cnt += 1
        return (cksum(src) * 31 + cnt) % P

    # dispatch ------------------------------------------------------------------
    def modules(self):
        v = self.p["variant"]
        if v == "declared_alloc":
            return self._da_modules()
        if v == "mfc_cbc":
            return self._cbc_modules()
        if v == "mfc_bubbles":
            return self._bub_modules()
        return []

    def uses(self):
        return [] if self.p["variant"] == "team_private" else \
            [f"{self.name}_m"]

    def decls(self):
        v = self.p["variant"]
        if v == "team_private":
            n = self.p["w"] * self.p["nt"]
            return [f"integer(8) :: a({n}), b({n}), t(0:{self.p['w'] - 1})",
                    "integer :: i, j, jj, jt, kt"]
        if v == "declared_alloc":
            return [f"integer(8) :: out({self.p['n']})", "integer :: i"]
        if v == "mfc_cbc":
            nf = self.p["nf"]
            return ["integer(8), allocatable :: q(:, :, :, :)",
                    f"integer(8) :: flux({self.p['nk']}, {self.p['nr']})",
                    "integer :: r, k, i, v, b, dir_idx",
                    f"integer(8) :: alpha_rho({nf}), vel(3), adv({nf})",
                    "integer(8) :: rho, gam, pres, c, accum"] + decl_lines(
                        "integer(8)", self._cbc_privs(), self.o.width)
        nb = self.p["nb"]
        m, n, p_ = self.p["ext"]
        return [f"type({self.name}_sf) :: qp({2 * nb + 1})",
                f"integer :: rs({nb}), vs({nb})", f"integer(8) :: w({nb})",
                f"integer(8) :: src(0:{m - 1}, 0:{n - 1}, 0:{p_ - 1})",
                f"integer(8) :: rtmp({nb}), vtmp({nb}), r3, nbub, cnt",
                "integer :: j, k, l, q"]

    def body(self):
        return {"team_private": self._tp_body,
                "declared_alloc": self._da_body,
                "mfc_cbc": self._cbc_body,
                "mfc_bubbles": self._bub_body}[self.p["variant"]]()

    def value(self):
        return {"team_private": self._tp_value,
                "declared_alloc": self._da_value,
                "mfc_cbc": self._cbc_value,
                "mfc_bubbles": self._bub_value}[self.p["variant"]]()

    def smaller(self):
        v = self.p["variant"]
        out = []
        if v == "team_private":
            if self.p["nloops"] > 2:
                out.append(self.clone(nloops=2))
            if self.p["simd"]:
                out.append(self.clone(simd=False))
            if self.p["col2"]:
                out.append(self.clone(col2=False))
            if self.p["w"] > 4:
                out.append(self.clone(w=4))
        elif v == "declared_alloc" and self.p["ncomp"] > 1:
            out.append(self.clone(ncomp=1))
        elif v == "mfc_cbc" and self.p["npriv"] > 1:
            out += [self.clone(npriv=m) for m in _halve(self.p["npriv"])]
        elif v == "mfc_bubbles" and self.p["nb"] > 1:
            out.append(self.clone(nb=1))
        return out

    def features(self):
        return super().features() | {f"template:{self.p['variant']}"}


# --- programs ------------------------------------------------------------------------------------

GEN = "stress-1"
# The revision of each axis's programs. A
# program record and a result row carry the revision they were made at
# ("rev"); offload.engine.stress_report drops anything older than the current
# revision (the generator changed the axis's text or its label since).
#   nest 2: deep nests wrapped and indented under 132 columns (ac364f0)
#   clauses 2: no linear / order(concurrent) (ac364f0); 3: lin private
#   random 2: the clauses change; 3: lin private
#   contlines (C) 2: one list item per continuation line (ac364f0)
#   tuimp 2: Fortran cross-module calls are cross-unit (an illegal
#     probe in every layout)
#   oo.polymap 2: an OpenMP 6.0 program
#   oo 3: the mixed axis has a polymap kernel, so its text changed too
AXIS_REV = {"nest": 2, "clauses": 3, "random": 3, "contlines-c": 2,
            "tuimp": 2, "oo.polymap": 2, "oo": 3}


def axis_rev(axis: str, lang: str = "f90") -> int:
    if lang == "c":
        return AXIS_REV.get(f"{axis}-c", 1)
    return AXIS_REV.get(axis, AXIS_REV.get(axis.split(".")[0], 1)
                        if axis.split(".")[0] in ("nest", "clauses",
                                                  "random", "tuimp")
                        else 1)
LAYOUTS = ("single", "per_unit", "partition")

UTIL = f"""module st_util
  implicit none
  integer(8), parameter :: st_p = {P}_8
  type :: st_pair
    integer(8) :: u, v
  end type st_pair
contains
  subroutine st_cksum(a, n, cs)
    integer, intent(in) :: n
    integer(8), intent(in) :: a(n)
    integer(8), intent(out) :: cs
    integer :: i
    cs = 0
    do i = 1, n
      cs = mod(cs + mod(a(i), st_p) * (mod(i, 7) + 1), st_p)
    end do
  end subroutine st_cksum
end module st_util
"""


def module_text(m: Module) -> str:
    uses = []
    for u in ["st_util"] + list(m.uses):
        if u not in uses:
            uses.append(u)
    lines = [f"module {m.name}"] + [f"  use {u}" for u in uses] + \
        ["  implicit none"]
    lines += ["  " + s if s and not s.startswith(" ") else s for s in m.spec]
    if m.contains:
        lines.append("contains")
        lines += m.contains
    lines.append(f"end module {m.name}")
    return "\n".join(lines) + "\n"


@dataclass
class StressProgram:
    id: str
    axis: str
    size: int
    seed: int
    model: str
    layout: str
    kernels: list
    files: list                      # [(name, text)] in compile order
    expected: int
    per_kernel: dict
    legality: str = "legal"
    cite: str = ""
    features: set = field(default_factory=set)
    alloc_bytes: int = 0
    lang: str = "f90"
    gen: str = GEN
    limits: dict = field(default_factory=dict)
    rev: int = 1

    @property
    def source(self) -> str:
        if len(self.files) == 1:
            return self.files[0][1]
        return "".join(f"{FILE_MARK}{n}\n{t}" for n, t in self.files)

    @property
    def lines(self) -> int:
        return sum(t.count("\n") for _, t in self.files)

    def meta(self) -> dict:
        return {"id": self.id, "gen": self.gen, "rev": self.rev,
                "axis": self.axis,
                "size": self.size, "seed": self.seed, "model": self.model,
                "lang": self.lang, "layout": self.layout,
                "legality": self.legality, "cite": self.cite,
                "expected": self.expected, "lines": self.lines,
                "files": len(self.files), "kernels": [
                    k.describe() for k in self.kernels],
                "per_kernel": self.per_kernel,
                "features": sorted(self.features),
                "alloc_bytes": self.alloc_bytes, "limits": self.limits}


def main_text(kernels: list, o: Opts, kmods: list[str]) -> str:
    lines = ["program stress_main", "  use st_util"]
    lines += [f"  use {m}" for m in kmods]
    lines.append("  use omp_lib" if o.model == "omp" else "  use openacc")
    lines += ["  implicit none", "  integer(8) :: cs, total",
              "  integer :: onhost", "  total = 0"]
    for k in kernels:
        lines += [f"  call {k.name}(cs)",
                  f"  print '(a,i0)', 'K {k.name} ', cs",
                  "  total = mod(total + cs, st_p)"]
    lines.append("  onhost = 1")
    if o.model == "omp":
        lines += ["  !$omp target map(tofrom: onhost)",
                  "  if (.not. omp_is_initial_device()) onhost = 0",
                  "  !$omp end target"]
    else:
        lines += ["  !$acc serial copy(onhost)",
                  "  if (acc_on_device(acc_device_not_host)) onhost = 0",
                  "  !$acc end serial"]
    lines += ["  print '(a,i0,a,i0)', 'RESULT checksum=', total, "
              "' ran_on_host=', onhost", "end program stress_main"]
    return "\n".join(lines) + "\n"


_ID = re.compile(r"[A-Za-z][A-Za-z0-9_]*")


def check_limits(files: list) -> dict:
    """Base-language limits of the rendered text (Fortran files): the
    longest line, the most continuation lines of one statement or
    directive, the longest name; with ``violations`` (keys of CITES)."""
    longest = cont_max = name_max = 0
    for name, text in files:
        if not name.endswith(".f90"):
            continue
        run = 0
        for ln in text.splitlines():
            longest = max(longest, len(ln))
            body = ln.split("!", 1)[0] if not ln.lstrip().startswith(
                "!$") else ln.lstrip()[5:]
            if ln.lstrip().startswith("!") and not ln.lstrip().startswith(
                    "!$"):
                continue
            if ln.rstrip().endswith("&"):
                run += 1
                cont_max = max(cont_max, run)
            else:
                run = 0
            for t in _ID.findall(re.sub(r"'[^']*'|\"[^\"]*\"", "", body)):
                name_max = max(name_max, len(t))
    v = []
    if longest > LINE_MAX:
        v.append("line")
    if cont_max > CONT_MAX:
        v.append("cont")
    if name_max > NAME_MAX:
        v.append("name")
    return {"max_line": longest, "max_continuations": cont_max,
            "max_name": name_max, "violations": v}


def assemble(axis: str, size: int, seed: int, kernels: list, o: Opts,
             layout: str = "single", rng: random.Random | None = None
             ) -> StressProgram:
    """Render `kernels` into files per `layout`; compute the value, the
    limits and the legality label."""
    rng = rng or random.Random(f"layout:{seed}")
    units: list[tuple[str, str, str]] = [("st_util", "mod", UTIL)]
    extra_after: dict[str, list] = {}
    kmods = []
    for k in kernels:
        for m in k.modules():
            units.append((m.name, "mod", module_text(m)))
        if hasattr(k, "extra_files"):
            for fname, text in k.extra_files():
                units.append((fname, "file", text))
    # the kernel subroutines: one module per kernel (per_unit / partition)
    # or one module for all (single)
    if layout == "single":
        body = ["module st_kern", "  use st_util", "  implicit none",
                "contains"]
        for k in kernels:
            body += k.routine()
        body.append("end module st_kern")
        units.append(("st_kern", "mod", "\n".join(body) + "\n"))
        kmods = ["st_kern"]
    else:
        for k in kernels:
            mname = f"st_k_{k.name}"
            body = [f"module {mname}", "  use st_util", "  implicit none",
                    "contains"] + k.routine() + [f"end module {mname}"]
            units.append((mname, "mod", "\n".join(body) + "\n"))
            kmods.append(mname)
    main = main_text(kernels, o, kmods)
    omp_level = "6.0" if any(isinstance(k, OOKernel) and
                             k.p.get("variant") == "polymap"
                             for k in kernels) else "5.2 in 5.0 spellings"
    head = [f"! stress: axis={axis} size={size} seed={seed} model={o.model}"
            f" layout={layout}",
            f"! generator: {GEN} rev {axis_rev(axis)}",
            f"! language: Fortran 2018 free form; OpenMP {omp_level}"
            if o.model == "omp" else
            "! language: Fortran 2018 free form; OpenACC 3.4"]
    for k in kernels:
        head.append(("! kernel " + k.describe())[:120])
    header = "\n".join(head) + "\n"
    # files
    fort = [u for u in units if u[1] == "mod"]
    others = [u for u in units if u[1] == "file"]
    files: list[tuple[str, str]] = []
    if layout == "single":
        text = header + "".join(t for _, _, t in fort) + main
        files.append(("stress.f90", text))
        # a submodule must follow its ancestor module: its own file after
        files += [(n, t) for n, _, t in others]
    elif layout == "per_unit":
        files.append(("st_util.f90", header + UTIL))
        for n, kind, t in fort[1:]:
            files.append((f"{n}.f90", t))
        files += [(n, t) for n, _, t in others]
        files.append(("main.f90", main))
    else:
        # random partition into contiguous groups (module order is kept)
        nf = max(2, min(len(fort), rng.randint(2, max(2, len(fort) // 2))))
        cuts = sorted(rng.sample(range(1, len(fort)), min(nf - 1,
                                                          len(fort) - 1)))
        groups, prev = [], 0
        for c in cuts + [len(fort)]:
            groups.append(fort[prev:c])
            prev = c
        for g_i, g in enumerate(groups):
            text = (header if g_i == 0 else "") + "".join(t for _, _, t in g)
            files.append((f"part{g_i:03d}.f90", text))
        files += [(n, t) for n, _, t in others]
        files.append(("main.f90", main))
    per = {k.name: k.value() for k in kernels}
    expected = sum(per.values()) % P
    feats = set()
    for k in kernels:
        feats |= k.features()
    lim = check_limits(files)
    legality, cite = "legal", ""
    for k in kernels:
        if k.legality == "unspecified" and legality == "legal":
            legality, cite = "unspecified", k.cite
    # implicit device procedures across compilation units (OpenMP 5.2
    # §13.8 p.284, §5.8.4 p.158). For Fortran a compilation unit is a
    # program unit (5.2 §1.2.2 p.3; OpenACC 3.4 §2.15.1 p.91: "program unit
    # being compiled"), so a chain of procedures in other modules is
    # cross-unit even in one file (F7): an illegal
    # probe in every layout
    for k in kernels:
        if isinstance(k, ChainTUKernel) and k.p["variant"] == "implicit":
            legality, cite = "illegal_probe", CITES["xtu"]
    if lim["violations"]:
        legality = "illegal_probe"
        cite = "; ".join(CITES[v] for v in lim["violations"])
    alloc = sum(k.bytes() for k in kernels if hasattr(k, "bytes"))
    pid = f"{axis}-{o.model}-{size}-{seed}" + ("" if layout == "single"
                                               else f"-{layout}")
    feats |= {f"axis:{axis}", f"layout:{layout}"}
    return StressProgram(pid, axis, size, seed, o.model, layout, kernels,
                         files, expected, per, legality, cite, feats, alloc,
                         limits=lim, rev=axis_rev(axis))


# --- axes ----------------------------------------------------------------------------------------

def _k(i: int) -> str:
    return f"k{i:04d}"


def kernel_variant(k: Kernel) -> str | None:
    """The variant (route, template, ...) a kernel instantiates."""
    if "routes" in k.p and len(k.p["routes"]) == 1:
        return k.p["routes"][0]
    return k.p.get("variant")


def _kernels_for(axis: str, size: int, rng: random.Random, o: Opts) -> list:
    """The kernels of one axis at one size; ``<axis>.<variant>`` keeps the
    kernels of one variant (a scalar route, an OO feature, a template, a
    translation-unit variant, ...), so a rejection of one variant does not
    hide the others."""
    if "." in axis:
        base, var = axis.split(".", 1)
        ks = [k for k in _kernels_for(base, size, rng, o)
              if kernel_variant(k) == var]
        if not ks:
            raise ValueError(f"axis {base} has no variant {var}")
        for j, k in enumerate(ks, 1):
            k.name = _k(j)
        return ks
    ks: list[Kernel] = []
    if o.model == "acc" and axis in ACC_EXCLUDED:
        raise ValueError(f"the {axis} axis is OpenMP only")

    def add(cls, **p):
        ks.append(cls(_k(len(ks) + 1), o, random.Random(rng.random()), **p))
    if axis == "kernels":
        for _ in range(size):
            r = rng.random()
            if r < 0.8:
                add(LoopKernel)
            elif r < 0.9:
                add(PrivateKernel, nitems=4)
            else:
                add(CallsKernel, depth=2, recursive=False, n=64)
    elif axis == "nest":
        add(NestKernel, depth=size, collapse=size)
        if size >= 3 and o.model == "omp":
            add(NestKernel, depth=size, split=True)
        add(NestKernel, depth=size, collapse=1)
    elif axis == "calls":
        add(CallsKernel, depth=size, recursive=False)
        add(CallsKernel, depth=size, recursive=True)
    elif axis in LIST_AXES:
        if axis == "lastprivate" and o.model == "acc":
            raise ValueError("OpenACC has no lastprivate")
        add(LIST_AXES[axis], nitems=size)
    elif axis == "clauses":
        if o.model == "acc":
            raise ValueError("the clauses axis is OpenMP")
        add(ClausesKernel, nclauses=size)
    elif axis == "contlines":
        add(ContKernel, nitems=size, n=8)
    elif axis == "names":
        add(NamesKernel, length=size, count=4)
    elif axis == "locals":
        add(LocalsKernel, nlocals=size)
    elif axis == "args":
        add(ArgsKernel, nargs=size)
    elif axis == "useonly":
        add(UseOnlyKernel, nitems=size)
    elif axis == "capture":
        add(CaptureKernel, nitems=size)
    elif axis == "dtnest":
        add(DTNestKernel, depth=size, mode="enter", ptr=False)
        add(DTNestKernel, depth=size, mode="region", ptr=False)
        add(DTNestKernel, depth=size, mode="enter", ptr=True)
    elif axis == "oo":
        for v in OO_LEGAL:
            add(OOKernel, variant=v, depth=size)
        add(OOKernel, variant="polymap", depth=size)
        add(OOKernel, variant="pdt", depth=size)
    elif axis == "tu":
        for v in ("plain", "submodule") + (
                ("bindc",) if o.model == "omp" else ()):
            add(ChainTUKernel, depth=size, variant=v)
    elif axis == "tuimp":
        add(ChainTUKernel, depth=size, variant="implicit")
    elif axis == "scalars":
        routes = OMP_ROUTES if o.model == "omp" else ACC_ROUTES
        for r in routes:
            add(ScalarsKernel, nscal=size, routes=[r])
    elif axis == "mixed":
        add(MixedKernel, nred=size, natom=max(1, size // 2),
            ncrit=max(1, min(size, 64) // 2) if o.model == "omp" else 0)
    elif axis == "exprs":
        for v in ("expr", "select", "spec"):
            add(ExprsKernel, variant=v, size=size)
    elif axis == "async":
        add(AsyncKernel, ntasks=size)
    elif axis == "runtime":
        for v in ("iters", "teams", "alloc"):
            sz = {"iters": size, "teams": max(1, size // 256),
                  "alloc": size}[v]
            add(RuntimeKernel, variant=v, size=sz)
    elif axis == "template":
        add(TemplateKernel, variant="team_private", nloops=max(2, min(size,
                                                                      16)))
        add(TemplateKernel, variant="declared_alloc", ncomp=max(1, min(
            size, 64)))
        add(TemplateKernel, variant="mfc_cbc", npriv=size)
        add(TemplateKernel, variant="mfc_bubbles", nb=max(1, min(size, 32)))
    elif axis == "random":
        # every axis together: `size` kernels drawn from the axes at
        # moderate sizes
        pool = [a for a in AXES if a not in ("random", "runtime", "names",
                                             "contlines", "tuimp",
                                             "oo", "scalars", "udr")]
        if o.model == "acc":
            pool = [a for a in pool if a not in ACC_EXCLUDED]
        for _ in range(size):
            a = rng.choice(pool)
            sub = _kernels_for(a, rng.choice(SMALL_SIZES.get(a, (4, 8, 16))),
                               random.Random(rng.random()), o)
            for k in sub[:1]:
                k.name = _k(len(ks) + 1)
                ks.append(k)
    else:
        raise ValueError(f"unknown axis {axis}")
    return ks


LIST_AXES = {"private": PrivateKernel, "firstprivate": FirstprivateKernel,
             "udr": UDRKernel,
             "lastprivate": LastprivateKernel, "shared": SharedKernel,
             "map": MapKernel, "reduction": ReductionKernel,
             "depend": DependKernel, "declare": DeclareKernel,
             "sections": SectionsKernel}
AXES = ("kernels", "nest", "calls", *LIST_AXES, "clauses", "contlines",
        "names", "locals", "args", "useonly", "capture", "dtnest", "oo",
        "tu", "tuimp", "scalars", "mixed", "exprs", "async", "runtime", "template",
        "random")
ACC_EXCLUDED = ("lastprivate", "clauses", "udr")
SMALL_SIZES = {"kernels": (2, 4), "nest": (3, 4, 5), "calls": (3, 5),
               "dtnest": (2, 3), "oo": (2,), "tu": (2, 3), "scalars": (1, 2),
               "template": (4, 8), "names": (40, 63), "exprs": (16, 64),
               "async": (4, 8), "mixed": (2, 4), "clauses": (8, 16, 28)}
# the size sweep of each axis (1, 8, 64, 256, 1024 ... and the
# real maximum x2 to x10, set from catalog/fuzz_profile.json by
# offload.engine.fuzz_profile.sweeps; these are the defaults)
SWEEPS = {
    "kernels": (1, 8, 64, 256, 512),
    "nest": (1, 2, 3, 4, 5, 6, 7, 8, 10, 12),
    "calls": (1, 2, 5, 10, 20, 50),
    "private": (1, 8, 64, 159, 256, 512, 1024, 2048),
    "firstprivate": (1, 8, 64, 256, 1024),
    "lastprivate": (1, 8, 64, 256, 1024),
    "shared": (1, 8, 64, 256, 1024),
    "map": (1, 8, 64, 256, 1024),
    "reduction": (1, 8, 64, 256, 1024),
    "udr": (1, 8, 64, 256, 1024),
    "depend": (1, 8, 64, 256, 1024),
    "declare": (1, 8, 64, 113, 256, 1024),
    "sections": (1, 8, 64, 256, 1024),
    "clauses": (1, 8, 16, 28, 64, 256),
    "contlines": (1, 8, 64, 200, 255, 256, 300),
    "names": (31, 63, 64, 128),
    "locals": (1, 8, 64, 190, 512, 1024, 2048),
    "args": (1, 8, 25, 64, 128, 250),
    "useonly": (1, 16, 64, 160, 1024),
    "capture": (1, 8, 20, 64, 200, 1024),
    "dtnest": (1, 2, 3, 4, 6, 8, 12),
    "oo": (1, 3, 6),
    "tu": (2, 3, 5, 8, 16, 32),
    "tuimp": (2, 3, 5, 8),
    "scalars": (1, 4, 20, 64, 200),
    "mixed": (1, 8, 64, 256),
    "exprs": (8, 64, 256, 1024, 2048),
    "async": (1, 8, 64, 256),
    "runtime": (1 << 20, 1 << 24, 1 << 28, 1 << 30),
    "template": (8, 40, 159, 400),
    "random": (8, 32, 128),
}


def variants_of(axis: str, model: str = "omp") -> tuple:
    """The variants ``<axis>.<variant>`` of an axis (empty: no split)."""
    return {
        "oo": OO_VARIANTS,
        "scalars": tuple(OMP_ROUTES if model == "omp" else ACC_ROUTES),
        "tu": ("plain", "submodule") + (("bindc",) if model == "omp"
                                        else ()),
        "template": TEMPLATES,
        "exprs": ("expr", "select", "spec"),
        "runtime": ("iters", "teams", "alloc"),
    }.get(axis, ())


def axis_names(model: str = "omp", split: bool = True) -> list[str]:
    """Every axis of a model, split into its variants where it has
    them."""
    out = []
    for a in AXES:
        if model == "acc" and a in ACC_EXCLUDED:
            continue
        vs = variants_of(a, model) if split else ()
        out += [f"{a}.{v}" for v in vs] if vs else [a]
    return out


def build(axis: str, size: int, seed: int = 0, model: str = "omp",
          layout: str = "single", width: int = WIDTH) -> StressProgram:
    """The stress program of one axis at one size (deterministic in
    axis, size, seed, model, layout)."""
    o = Opts(model=model, width=width)
    rng = random.Random(f"{GEN}:{axis}:{size}:{seed}:{model}")
    for attempt in range(20):
        ks = _kernels_for(axis, size, rng, o)
        try:
            return assemble(axis, size, seed, ks, o, layout,
                            random.Random(f"layout:{seed}:{attempt}"))
        except Overflow:
            continue
    raise RuntimeError(f"{axis} {size} {seed}: model overflow 20 times")


def rebuild(prog_meta: dict, kernels: list) -> StressProgram:
    """A program of `kernels` (a subset or shrunk variants) with the
    original's axis, seed, model and layout (offload.engine.stress_min)."""
    o = Opts(model=prog_meta["model"])
    for j, k in enumerate(kernels, 1):
        k.o = o
    return assemble(prog_meta["axis"], prog_meta["size"], prog_meta["seed"],
                    kernels, o, prog_meta["layout"])
