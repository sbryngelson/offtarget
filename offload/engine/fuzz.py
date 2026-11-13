"""Csmith-style random OpenMP 5.2 Fortran target-offload programs.

``generate(seed)`` returns a ``FuzzProgram``: a legal-by-construction
deterministic free-form Fortran program whose output ends with
``RESULT checksum=<int> ran_on_host=<0|1>``. The seed and ``GEN_VERSION``
(both in the header) determine the program.
A program holds 1 to 4 kernels (target regions) of kind ``loop``, ``guard``,
``phase`` or ``inred``. A loop kernel's construct nest is a chain taken from
a compound directive in ``catalog/omp/skeleton.yaml``, with clauses from
``FILLABLE``. Bodies use bounded
integer arithmetic without races. ``FuzzProgram.expected`` comes from a
Python model of sequential execution.
``check(program)`` runs ``check_scope``, ``offload.engine.rules``, the AFAR flang
frontend and gfortran ``-std=f2008``; a failing program is a
``generator_reject`` and is never run."""
from __future__ import annotations

import random
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable

from offload.engine.catalog import (default_grammar, default_skeleton,
                                rule_valid, slice_directives, spelling_valid)
from offload.engine.fuzz_base import (ALL_GROUPS, BASE_GROUPS, TYPES, BaseMixin,
                                  Overflow,
                                  checksum_terms, contributions,
                                  red_apply_typed, zero)

# Generator versions. A seed replays only with its version (in the
# program header and every campaign result row).
# fuzz-1: the first campaign (results/fuzz/c1).
# fuzz-2: defaultmap on the scalar and all categories draws only default,
#   tofrom, to or firstprivate (Ruling below: a loop iteration variable
#   referenced only inside a loop construct nested in the target region;
#   CCE applies defaultmap(present: all) to it).
# fuzz-3: the base-language axis (offload.engine.fuzz_base): base
#   groups chosen per campaign; without any group a fuzz-3 program is the
#   fuzz-2 program of its seed (only the header differs).
# fuzz-4: fuzz-3 with generator defect G1 fixed: default(none)
#   on a combined construct also lists the variables of its if(<leaf>:)
#   clauses whose leaf is nested inside the default's leaf (those
#   expressions are evaluated inside that region, 5.2 §17.2 p.340,
#   §5.4.1 p.109); every other line, and the model, is fuzz-3's.
# fuzz-4s50: the fuzz-4 program of the seed with the OpenMP
#   5.0/5.1 spelling of each construct whose 5.2 spelling has an exact
#   5.0/5.1 equivalent (``spell50``); the model, every random decision and
#   every other line are fuzz-4's, and the program is still a legal 5.2
#   program (each 5.0 spelling is valid, if deprecated, at 5.2), checked by
#   the same checkers. For compilers that reject the 5.2 spellings (NVHPC).
# fuzz-5 (fortran-oop): fuzz-4 plus the base group ``oop`` (type extension,
#   type-bound procedures, dispatch, SELECT TYPE, CLASS(*) in declare target
#   functions, offload.engine.fuzz_base.setup_oop); without that group a fuzz-5
#   program is the fuzz-4 program of its seed (only the header differs), and
#   no older version's program changes.
GEN_VERSIONS = ("fuzz-1", "fuzz-2", "fuzz-3", "fuzz-4", "fuzz-4s50",
                "fuzz-5")
GEN_VERSION = "fuzz-4"
# the generator behaviour (self.v) of a spelling variant
_SPELL_OF = {"fuzz-4s50": "fuzz-4"}


def spell50(source: str) -> str:
    """The OpenMP 5.0/5.1 spellings of a fuzz program's directives. The
    first two have the same meaning at 5.2; the third does not:

    * ``declare target enter(list)`` -> ``to(list)``: 5.2 §5.8.4, p.157
      ("to ... is a deprecated synonym of enter"; enter is new in 5.2,
      5.2 §B.2 p.627);
    * ``defaultmap(behavior: all)`` -> ``defaultmap(behavior)``: without a
      variable-category the clause applies to all variables (5.2 §5.8.7,
      p.162; 5.0 §2.19.7.2, p.325), and 5.0 has no all category;
    * ``order(unconstrained: concurrent)`` -> ``order(concurrent)``: NOT
      the same meaning. 5.0 has only ``order(concurrent)``: the iterations
      may run in any order, including concurrently (5.0 §2.9.2 p.104,
      §2.9.5 p.130). At 5.2 the iterations may still run in any order
      (§10.3 p.234), but the modifier decides reproducibility: with
      unconstrained "the loop schedule is not reproducible"; without a
      modifier the clause does not affect it (5.2 §B.2 p.628: order with
      concurrent "only affects whether a loop schedule is reproducible if a
      modifier is explicitly specified"), so a schedule(static) worksharing
      loop, a dist_schedule(static) distribute or a loop construct stays
      reproducible (§11.5 p.248, §11.6 p.254, §11.7 p.257). The 5.0 spelling
      therefore asks more of the compiler than fuzz-4's program (a reproducible
      schedule); every fuzz-4 program stays legal and its checksum, which
      no schedule decides, is unchanged.

    ``order(reproducible: ...)``, ``thread_limit`` on target and the other
    5.1/5.2 features have no 5.0 equivalent and are kept."""
    out = []
    for line in source.split("\n"):
        if line.lstrip().lower().startswith("!$omp"):
            line = re.sub(r"\benter\s*\(", "to(", line)
            line = re.sub(r"\bdefaultmap\(\s*(\w+)\s*:\s*all\s*\)",
                          r"defaultmap(\1)", line)
            line = re.sub(r"\border\(\s*unconstrained\s*:\s*concurrent\s*\)",
                          "order(concurrent)", line)
        out.append(line)
    return "\n".join(out)
VERSION = 52
LIMIT = 2 ** 30          # |every intermediate value| stays below this
CHECK_MOD = 2147483629   # checksum modulus (a prime below 2**31)

LOOP_LEAVES = ("distribute", "do", "simd", "loop")
BLOCK_LEAVES = ("target", "teams", "parallel")

# Clauses the generator fills without changing the result.
FILLABLE = frozenset({
    "map", "firstprivate", "private", "shared", "default", "reduction",
    "lastprivate", "collapse", "schedule", "dist_schedule", "order",
    "num_teams", "thread_limit", "num_threads", "proc_bind", "if", "device",
    "defaultmap", "nowait", "depend", "in_reduction", "simdlen", "safelen",
    "bind", "nontemporal"})

RED_OPS = ("+", "*", "max", "min", "iand", "ior", "ieor")

# Legal 5.2 forms AFAR flang's frontend rejects (its semantic check is one
# of the three legality checks, so a program using one would only be a
# generator reject). The generator avoids them; each has a reproducer in
# data/findings/ (afar-flang-*.f90) and the spec text that allows it.
FLANG_FALSE_REJECTS = {
    "task_reduction_intrinsic_identifier":
        "task_reduction/in_reduction with max, min, iand, ior or ieor "
        "(5.2 §5.5.1: intrinsic procedure names are reduction identifiers; "
        "flang: 'Internal: no symbol found for max')",
    "loop_bind_teams_reduction":
        "reduction on a loop construct bound to an enclosing teams "
        "construct (5.2 §11.7.1 only makes it unspecified when the loop is "
        "not nested in a teams construct; flang: 'REDUCTION clause not "
        "allowed with !$OMP LOOP BIND(TEAMS)')",
    "thread_limit_target_parallel_do":
        "thread_limit on target parallel do [simd] (5.2 §13.8: target "
        "takes thread_limit; §17.2 applies it to every leaf that takes it; "
        "flang: 'THREAD_LIMIT clause is not allowed on TARGET PARALLEL DO')",
    "firstprivate_and_map_on_different_targets":
        "a variable firstprivate on one target construct and mapped on "
        "another (5.2 §13.8 forbids both only on the same construct; "
        "flang: 'may not appear on both MAP and FIRSTPRIVATE clauses on a "
        "TARGET construct')",
}

# Optional features, each enabled for a random half of the programs.
SWARM = ("device", "if_target", "thread_limit", "split", "order", "atomic",
         "critical", "lastprivate", "conditional", "inner_loop", "num_teams",
         "num_threads", "proc_bind", "if_parallel", "if_simd", "schedule",
         "dist_schedule", "simdlen", "safelen", "bind", "default", "shared",
         "firstprivate", "nontemporal", "defaultmap", "nowait", "temp",
         "map_always", "map_close", "map_present", "map_section", "guard",
         "phase", "inred", "wrapper", "functions", "two_d", "reduction")


# --- the catalog view ---------------------------------------------------------

@lru_cache(maxsize=None)
def _cat():
    return default_skeleton(), default_grammar()


def directive_valid(key: str) -> bool:
    sk, g = _cat()
    return key in sk.directives and spelling_valid(sk, g, key, key, VERSION)


@lru_cache(maxsize=None)
def allowed_clauses(key: str) -> frozenset:
    """Clauses of directive `key` valid at 5.2 (after the spec overrides)."""
    sk, g = _cat()
    return frozenset(c for c, r in g.allowed(sk, key).items()
                     if rule_valid(r, VERSION) and not c.startswith("ompx_"))


def leaves_of(key: str) -> tuple:
    sk, _ = _cat()
    return tuple(sk.directive(key).leaves or [key])


@lru_cache(maxsize=None)
def target_chains() -> tuple:
    """Leaf chains of the slice's compound directives that start with
    target and are valid at 5.2, except the data-motion directives (and
    6.0's workdistribute)."""
    sk, _ = _cat()
    out = set()
    for key in slice_directives(sk):
        lv = leaves_of(key)
        if lv[0] != "target" or not directive_valid(key):
            continue
        if all(x in LOOP_LEAVES + BLOCK_LEAVES for x in lv):
            out.add(lv)
    return tuple(sorted(out))


@lru_cache(maxsize=None)
def partitions(chain: tuple) -> tuple:
    """Every split of `chain` into consecutive groups that are directives
    valid at 5.2 (each group a tuple of leaves)."""
    if not chain:
        return ((),)
    out = []
    for k in range(1, len(chain) + 1):
        head = chain[:k]
        if directive_valid(" ".join(head)):
            out += [(head,) + rest for rest in partitions(chain[k:])]
    return tuple(out)


def catalog_coverage() -> dict:
    """Per target chain: its allowed 5.2 clauses the generator fills and
    those it does not."""
    out = {}
    for chain in target_chains():
        key = " ".join(chain)
        al = allowed_clauses(key)
        out[key] = {"filled": sorted(al & FILLABLE),
                    "not_filled": sorted(al - FILLABLE)}
    return out


# --- expressions --------------------------------------------------------------

def _chk(v: int) -> int:
    if abs(v) >= LIMIT:
        raise Overflow(v)
    return v


def fmod(a: int, p: int) -> int:
    """Fortran MOD (the sign of the first argument)."""
    r = abs(a) % abs(p)
    return r if a >= 0 else -r


def fdiv(a: int, b: int) -> int:
    """Fortran integer division (truncates toward zero)."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


class Ex:
    def f(self) -> str:
        """Fortran text."""
        raise NotImplementedError

    def ev(self, env: dict, arrs: dict) -> int:
        raise NotImplementedError


@dataclass(frozen=True)
class Const(Ex):
    v: int

    def f(self):
        return str(self.v) if self.v >= 0 else f"({self.v})"

    def ev(self, env, arrs):
        return self.v


@dataclass(frozen=True)
class Var(Ex):
    name: str

    def f(self):
        return self.name

    def ev(self, env, arrs):
        return env[self.name]


@dataclass(frozen=True)
class ARef(Ex):
    arr: str
    idx: tuple

    def f(self):
        if not self.idx:            # a scalar component (fuzz-3)
            return self.arr
        sub = ", ".join(x.f() for x in self.idx)
        if "(@)" in self.arr:       # a component of an array of structures
            return self.arr.replace("@", sub)
        return f"{self.arr}({sub})"

    def ev(self, env, arrs):
        return arrs[self.arr][tuple(x.ev(env, arrs) for x in self.idx)]


@dataclass(frozen=True)
class Bin(Ex):
    op: str
    a: Ex
    b: Ex

    def f(self):
        return f"({self.a.f()} {self.op} {self.b.f()})"

    def ev(self, env, arrs):
        x, y = self.a.ev(env, arrs), self.b.ev(env, arrs)
        if self.op == "+":
            return _chk(x + y)
        if self.op == "-":
            return _chk(x - y)
        if self.op == "*":
            return _chk(x * y)
        return fdiv(x, y)  # "/" by a positive constant


@dataclass(frozen=True)
class Intr(Ex):
    name: str
    args: tuple

    def f(self):
        return f"{self.name}({', '.join(a.f() for a in self.args)})"

    def ev(self, env, arrs):
        v = [a.ev(env, arrs) for a in self.args]
        n = self.name
        if n == "mod":
            return fmod(v[0], v[1])
        if n == "max":
            return max(v)
        if n == "min":
            return min(v)
        if n == "iand":
            return v[0] & v[1]
        if n == "ior":
            return v[0] | v[1]
        if n == "ieor":
            return v[0] ^ v[1]
        if n == "abs":
            return abs(v[0])
        if n == "ishft":  # applied to iand(x, 1023) only: never negative
            return _chk(v[0] << v[1] if v[1] >= 0 else v[0] >> -v[1])
        raise ValueError(n)


@dataclass(frozen=True)
class Cond:
    op: str
    a: Ex
    b: Ex

    def f(self):
        return f"{self.a.f()} {self.op} {self.b.f()}"

    def ev(self, env, arrs) -> bool:
        x, y = self.a.ev(env, arrs), self.b.ev(env, arrs)
        return {"<": x < y, "<=": x <= y, ">": x > y, ">=": x >= y,
                "==": x == y, "/=": x != y}[self.op]


@dataclass(frozen=True)
class Merge(Ex):
    a: Ex
    b: Ex
    c: Cond

    def f(self):
        return f"merge({self.a.f()}, {self.b.f()}, {self.c.f()})"

    def ev(self, env, arrs):
        # Fortran evaluates both; both are in range by construction
        x, y = self.a.ev(env, arrs), self.b.ev(env, arrs)
        return x if self.c.ev(env, arrs) else y


@dataclass(frozen=True)
class Func:
    name: str
    params: tuple
    body: Ex


@dataclass(frozen=True)
class Call(Ex):
    """A call of a declare-target module function."""
    fn: Func
    args: tuple

    def f(self):
        return f"{self.fn.name}({', '.join(a.f() for a in self.args)})"

    def ev(self, env, arrs):
        vals = [a.ev(env, arrs) for a in self.args]
        return self.fn.body.ev(dict(zip(self.fn.params, vals)), arrs)


def red_apply(op: str, acc: int, v: int) -> int:
    if op == "+":
        return _chk(acc + v)
    if op == "*":
        return _chk(acc * v)
    if op == "max":
        return max(acc, v)
    if op == "min":
        return min(acc, v)
    if op == "iand":
        return acc & v
    if op == "ior":
        return acc | v
    return acc ^ v


# --- text helpers ---------------------------------------------------------------

def wrap_directive(indent: str, name: str, clauses: list,
                   width: int = 96) -> list[str]:
    """`!$omp name clauses...` with free-form continuation lines."""
    lines, cur = [], f"{indent}!$omp {name}"
    first = True
    for c in clauses:
        if len(cur) + 1 + len(c) > width and not first:
            lines.append(cur + " &")
            cur = f"{indent}!$omp& {c}"
        else:
            cur += " " + c
        first = False
    lines.append(cur)
    return lines


def wrap_stmt(indent: str, text: str, width: int = 100) -> list[str]:
    """A statement split with `&` continuations at spaces (generated
    statements have spaces only between tokens, never in strings)."""
    out = []
    line = indent + text
    while len(line) > width:
        k = line.rfind(" ", len(indent) + 12, width)
        if k < 0:
            break
        out.append(line[:k] + " &")
        line = indent + "    & " + line[k + 1:]
    out.append(line)
    return out


def add_clauses(lines: list[str], extra: list[str]) -> list[str]:
    """`lines` (a directive, maybe continued, then more lines) with
    `extra` clauses appended to the directive as continuation lines."""
    if not extra:
        return list(lines)
    last = 0
    while lines[last].rstrip().endswith("&"):
        last += 1
    ind = re.match(r"\s*", lines[0]).group()
    cont = [f"{ind}!$omp& {x} &" for x in extra[:-1]] + \
        [f"{ind}!$omp& {extra[-1]}"]
    return lines[:last] + [lines[last] + " &"] + cont + lines[last + 1:]


# --- the program model ------------------------------------------------------------

@dataclass
class Arr:
    name: str
    rank: int         # 1: (n), 2: (n, m)
    alloc: bool       # allocatable, else explicit shape
    role: str         # input | output | scratch
    type: str = "integer"   # a key of fuzz_base.TYPES (fuzz-3)
    var: str = ""           # the structure of a component (fuzz-3)


@dataclass
class Group:
    leaves: tuple
    levels: int = 0
    clauses: list = field(default_factory=list)
    vars: tuple = ()     # loop variables of the associated levels

    @property
    def key(self) -> str:
        return " ".join(self.leaves)

    @property
    def is_loop(self) -> bool:
        return self.leaves[-1] in LOOP_LEAVES

    def has(self, leaf: str) -> bool:
        return leaf in self.leaves

    def allows(self, clause: str) -> bool:
        return clause in allowed_clauses(self.key)


@dataclass
class Level:
    var: str
    extent: str      # "n" or "m"
    form: str        # up | down | step2

    def header(self) -> str:
        return {"up": f"do {self.var} = 1, {self.extent}",
                "down": f"do {self.var} = {self.extent}, 1, -1",
                "step2": f"do {self.var} = 1, {self.extent}, 2"}[self.form]

    def values(self, size: int) -> range:
        return {"up": range(1, size + 1), "down": range(size, 0, -1),
                "step2": range(1, size + 1, 2)}[self.form]

    def first(self) -> str:
        return self.extent if self.form == "down" else "1"


@dataclass
class Red:
    var: str
    op: str
    method: str     # clause | atomic | critical | plain
    init: object
    type: str = "integer"   # a key of fuzz_base.TYPES (fuzz-3)


@dataclass
class Kern:
    lines: list
    reads: set
    writes: set
    target_line: int = 0     # index of the target directive's first line
    host: bool = False       # host statements (not a kernel)


@dataclass(frozen=True)
class FuzzProgram:
    seed: int
    source: str
    expected: int
    features: frozenset
    kernels: tuple          # one description per kernel
    flags: int              # kernels with a host-execution flag
    gen_version: str = GEN_VERSION
    base: tuple = ()        # base-language groups (fuzz-3)

    @property
    def id(self) -> str:
        return f"fuzz-{self.seed}"

    @property
    def base_features(self) -> tuple:
        """The program's base-language feature set (sorted)."""
        return tuple(sorted(f for f in self.features
                            if f.startswith("base:")))


class _Gen(BaseMixin):
    """One program. Every random decision goes through self.r in a fixed
    order (base-language decisions through self.rb), so the program is a
    function of the seed, the generator version and the base groups."""

    def __init__(self, seed: int, gen_version: str = GEN_VERSION,
                 base: tuple = ()):
        if gen_version not in GEN_VERSIONS:
            raise ValueError(f"unknown generator version {gen_version!r}")
        self.gen_version = gen_version
        self.v = GEN_VERSIONS.index(_SPELL_OF.get(gen_version,
                                                  gen_version)) + 1
        self.seed = seed
        self.r = random.Random(seed)
        self.n = self.r.choice((16, 24, 32, 48, 64, 100, 128, 200))
        self.m = self.r.choice((2, 3, 4, 5, 8))
        self.arrays: dict[str, Arr] = {}
        self.scalars: dict[str, int] = {}     # integer scalars: initial value
        self.logicals: dict[str, bool] = {}
        self.inits: dict[str, str] = {}
        self.funcs: list[Func] = []
        self.api: set[str] = set()
        self.features: set[str] = set()
        self.kdesc: list[str] = []
        self.flags: list[str] = []
        self.temps: set[str] = set()
        self.check_items: list[str] = []
        self.arrs: dict[str, dict] = {}       # model: array values
        self.env: dict[str, int] = {"n": self.n, "m": self.m}  # scalars
        self.k = 0
        self.uses_dev = False
        self.in_data = False
        self.pmode: dict[str, str] = {}   # param -> "fp" | "map" (targets)
        # swarm testing (Groce et al., ISSTA 2012): each program enables a
        # random half of the optional features, so many programs avoid any
        # one feature a compiler rejects
        self.swarm = {f: self.coin(0.5) for f in SWARM}
        self.features.update(f"swarm:{f}" for f, on in self.swarm.items()
                             if on)
        self.cur_out = ""
        self.race_redraws = 0
        self.base_init(tuple(base))

    # -- helpers --

    def feat(self, *names: str) -> None:
        self.features.update(names)

    def coin(self, p: float) -> bool:
        return self.r.random() < p

    def on(self, name: str) -> bool:
        return self.swarm[name]

    def sw(self, name: str, p: float) -> bool:
        """An optional feature: enabled in this program's swarm, then
        drawn with probability p at this site."""
        return self.swarm[name] and self.coin(p)

    def size(self, extent: str) -> int:
        return self.n if extent == "n" else self.m

    def points(self, a: Arr) -> list[tuple]:
        if a.rank == 0:
            return [()]
        if a.rank == 1:
            return [(i,) for i in range(1, self.n + 1)]
        return [(i, j) for j in range(1, self.m + 1)
                for i in range(1, self.n + 1)]

    def new_array(self, name: str, rank: int, role: str,
                  typ: str = "integer", var: str = "") -> Arr:
        if var:
            a = Arr(name, rank, False, role, typ, var)
        elif typ == "integer":
            a = Arr(name, rank, self.coin(0.6), role)
        else:
            # typed arrays (fuzz-3) draw from the base stream
            a = Arr(name, rank, rank > 0 and self.rb.random() < 0.4, role,
                    typ)
        if typ != "integer" and role == "output":
            base, kind = TYPES[typ]
            from offload.engine.fuzz_base import INT_MAX, real_limit
            self.tbound[name] = real_limit(kind) if base in (
                "real", "complex") else INT_MAX.get(kind, 0) \
                if base == "integer" else 0
        self.arrays[name] = a
        self.arrs[name] = {t: zero(typ) for t in self.points(a)}
        if role == "output":
            self.cur_out = name
        if var:
            pass
        elif typ == "integer":
            self.feat(f"decl:{'allocatable' if a.alloc else 'explicit'}"
                      f"_rank{rank}")
        elif rank:
            self.feat(f"base:decl:{'allocatable' if a.alloc else 'explicit'}"
                      f"_{typ}")
        return a

    def new_scalar(self, name: str, value: int) -> str:
        self.scalars[name] = value
        self.env[name] = value
        return name

    def params(self) -> list[str]:
        return [p for p in self.scalars if re.fullmatch(r"p\d", p)]

    # -- inputs and functions --

    def setup(self) -> None:
        r = self.r
        for name, rank in (("ia", 1), ("ib", 1), ("ic", 2)):
            a = self.new_array(name, rank, "input")
            c1, c2 = r.randint(3, 61), r.randint(0, 50)
            p = r.choice((97, 101, 211, 1009, 30011))
            off = r.randint(0, p // 2)
            cj = r.randint(1, 9)
            for t in self.points(a):
                lin = t[0] if rank == 1 else t[0] + cj * t[1]
                self.arrs[name][t] = fmod(lin * c1 + c2, p) - off
            lin = "i" if rank == 1 else f"(i + {cj} * j)"
            idx = "i" if rank == 1 else "i, j"
            self.inits[name] = (f"{name}({idx}) = mod({lin} * {c1} + {c2}, "
                                f"{p}) - {off}")
        for k in range(r.choice((1, 1, 2))):
            self.new_scalar(f"p{k + 1}", r.randint(-9, 9))
        for k in range(r.choice((1, 2)) if self.on("functions") else 0):
            params = ("x",) if self.coin(0.5) else ("x", "y")
            leaves = [Var(p) for p in params] + [Const(r.randint(1, 13))]
            body = Intr("mod", (self.expr(2, leaves, calls=False),
                                Const(r.choice((97, 1009, 9973)))))
            self.funcs.append(Func(f"g{k + 1}", params, body))
        if "types" in self.base:
            self.setup_types()
        if "derived" in self.base:
            self.setup_derived()
        if "alloc" in self.base:
            self.setup_alloc()
        if "declare" in self.base:
            self.setup_declare()
        if "multitu" in self.base:
            self.setup_multitu()
        if "oop" in self.base:
            self.setup_oop()

    # -- expressions --

    def expr(self, depth: int, leaves: list, calls: bool = True) -> Ex:
        r = self.r
        if depth <= 0 or self.coin(0.25):
            return r.choice(leaves)
        kind = r.choices(
            ("add", "sub", "mul", "mod", "mm", "bit", "merge", "div", "call",
             "ishft"),
            (5, 3, 3, 3, 2, 2, 2, 1,
             (6 if self.ofuncs else 2) if (calls and (
                 self.funcs or self.dfuncs or self.mfuncs or self.xfuncs or
                 self.ofuncs)) else 0, 1))[0]

        def sub():
            return self.expr(depth - 1, leaves, calls)
        if kind == "add":
            return Bin("+", sub(), sub())
        if kind == "sub":
            return Bin("-", sub(), sub())
        if kind == "mul":
            small = Const(r.choice((-3, -2, 2, 3, 5, 7))) if self.coin(0.6) \
                else Intr("mod", (sub(), Const(r.randint(3, 15))))
            return Bin("*", sub(), small)
        if kind == "mod":
            return Intr("mod", (sub(), Const(r.choice((7, 13, 97, 1000)))))
        if kind == "mm":
            return Intr(r.choice(("max", "min")), (sub(), sub()))
        if kind == "bit":
            return Intr(r.choice(("iand", "ior", "ieor")), (sub(), sub()))
        if kind == "merge":
            c = Cond(r.choice(("<", "<=", ">", ">=", "==", "/=")), sub(),
                     sub())
            return Merge(sub(), sub(), c)
        if kind == "div":
            return Bin("/", sub(), Const(r.randint(2, 9)))
        if kind == "ishft":
            return Intr("ishft", (Intr("iand", (sub(), Const(1023))),
                                  Const(r.randint(-4, 4))))
        fn = r.choice(self.funcs + self.dfuncs + self.mfuncs + self.xfuncs
                      + self.ofuncs)
        self.feat("body:call_declare_target")
        if fn in self.ofuncs:
            self.feat(f"base:oop:call:{fn.name}")
        elif fn not in self.funcs:
            self.feat(f"base:dc:call:{fn.name}")
        return Call(fn, tuple(sub() for _ in fn.params))

    def index(self, extent: str, ivars: dict) -> Ex:
        """A subscript in 1..extent built from the loop variables."""
        r = self.r
        same = [v for v, e in ivars.items() if e == extent]
        if same and self.coin(0.6):
            v = r.choice(same)
            if self.coin(0.75):
                return Var(v)
            return Bin("-", Const(self.size(extent) + 1), Var(v))
        if ivars and self.coin(0.8):
            v = r.choice(sorted(ivars))
            return Bin("+", Intr("mod", (Bin("+", Bin("*", Var(v), Const(
                r.randint(1, 7))), Const(r.randint(0, 9))), Var(extent))),
                Const(1))
        return Const(r.randint(1, self.size(extent)))

    def leaves(self, ivars: dict, readable: list[str]) -> list[Ex]:
        out: list[Ex] = [Var(v) for v in ivars]
        out += [Var(p) for p in self.params()]
        out += [Const(self.r.randint(-20, 40)) for _ in range(2)]
        for name in readable:
            if self.arrays[name].rank == 0:     # a scalar component
                out.append(ARef(name, ()))
                continue
            dims = ("n",) if self.arrays[name].rank == 1 else ("n", "m")
            for _ in range(2):
                out.append(ARef(name, tuple(self.index(d, ivars)
                                            for d in dims)))
        if self.bsw:
            out += self.typed_leaves(ivars, self.cur_out)
        return out

    def bounded(self, e: Ex) -> Ex:
        """A kernel result wrapped so later kernels read small values."""
        r = self.r
        kind = r.choice(("mod", "mod", "iand", "none"))
        if kind == "mod":
            return Intr("mod", (e, Const(r.choice((97, 1009, 9973, 30011)))))
        if kind == "iand":
            return Intr("iand", (e, Const(r.choice((255, 4095, 65535)))))
        return e

    def readable(self, but: str) -> list[str]:
        """Integer arrays an integer expression may read."""
        return [a.name for a in self.arrays.values()
                if a.role in ("input", "output") and a.name != but
                and a.type == "integer"]

    def read_in(self, text: str, but: str = "") -> set:
        """Arrays (any type) the kernel text reads."""
        return {a.name for a in self.arrays.values()
                if a.role in ("input", "output") and a.name != but
                and re.search(self.ref_re(a.name), text)}

    # -- reductions, lastprivate, flags --

    def new_red(self, idx: int, method: str, ops=RED_OPS,
                typed: bool = False) -> Red:
        r = self.r
        t = self.typed_red_type() if typed else None
        if t is not None:
            from offload.engine.fuzz_base import RED_OPS_TYPED
            base = TYPES[t][0]
            if method == "atomic" and base == "complex":
                method = "clause"   # no atomic update of complex items
            op = self.rb.choice(RED_OPS_TYPED[self.red_key(t)])
            init = self.typed_red_init(t, op)
            name = f"r{self.k}{'ab'[idx]}"
            self.tscalars[name] = (t, init)
            self.env[name] = init
            self.check_items.append(name)
            self.feat(f"base:red:{t}:{op}", f"base:red:{t}:{method}")
            return Red(name, op, method, init, t)
        op = r.choice(ops)
        init = {"+": r.randint(-50, 50), "*": r.choice((1, 2, -1)),
                "max": r.randint(-100, 0), "min": r.randint(0, 100),
                "iand": r.choice((-1, 65535, 1048575)),
                "ior": r.randint(0, 8), "ieor": r.randint(0, 255)}[op]
        red = Red(self.new_scalar(f"r{self.k}{'ab'[idx]}", init), op, method,
                  init)
        self.check_items.append(red.var)
        return red

    def red_term(self, op: str, lv: list) -> Ex:
        r = self.r
        if op == "*":
            c = Cond("==", Intr("mod", (r.choice(lv), Const(r.choice(
                (11, 13, 17))))), Const(0))
            return Merge(Const(r.choice((2, -1, 3))), Const(1), c)
        e = self.expr(2, lv)
        if op in ("iand", "ior", "ieor"):
            return Intr("iand", (e, Const(r.choice((255, 65535, 1048575)))))
        return e

    def red_lines(self, red: Red, ce: Ex) -> list[str]:
        v = red.var
        if red.type != "integer":
            upd = self.typed_red_update(v, red.type, red.op, ce)
        else:
            upd = (f"{v} = {v} {red.op} {ce.f()}" if red.op in ("+", "*")
                   else f"{v} = {red.op}({v}, {ce.f()})")
        if red.method == "atomic":
            return [f"!$omp atomic{self.r.choice(('', ' update'))}"] + \
                wrap_stmt("", upd)
        if red.method == "critical":
            return ["!$omp critical"] + wrap_stmt("", upd) + \
                ["!$omp end critical"]
        return wrap_stmt("", upd)

    def new_flag(self) -> str:
        self.api.add("omp_is_initial_device")
        name = self.new_scalar(f"hf{self.k}", 0)
        self.flags.append(name)
        return name

    @staticmethod
    def flag_stmt(flag: str) -> str:
        return f"{flag} = merge(1, 0, omp_is_initial_device())"

    # -- the body of one iteration point --

    def point(self, ivars: dict, out: Arr, outidx: tuple, reds: list,
              lps: list, temps: list, seq_inner: bool, readable: list
              ) -> tuple[list[str], Callable]:
        """(lines, model step) of one iteration point: a temporary, an
        optional sequential inner loop, the output element, reduction
        updates and lastprivate assignments."""
        lines: list[str] = []
        steps: list[Callable] = []
        lv = self.leaves(ivars, readable)
        if self.sw("temp", 0.5):
            t = f"t{self.k}"
            temps.append(t)
            te = self.expr(2, lv)
            lines += wrap_stmt("", f"{t} = {te.f()}")
            steps.append(lambda env, a, te=te, t=t:
                         env.__setitem__(t, te.ev(env, a)))
            lv = lv + [Var(t)]
            self.feat("body:temp")
        if seq_inner:
            acc = f"acc{self.k}"
            temps += [acc, "jj"]
            ie = self.expr(2, self.leaves(dict(ivars, jj="m"), readable)
                           + [x for x in lv if isinstance(x, Var)
                              and x.name.startswith("t")])
            lines += [f"{acc} = 0", "do jj = 1, m"] + \
                wrap_stmt("  ", f"{acc} = {acc} + {ie.f()}") + ["end do"]

            def inner(env, a, ie=ie, acc=acc):
                s = 0
                for v in range(1, self.m + 1):
                    env["jj"] = v
                    s = _chk(s + ie.ev(env, a))
                env[acc] = s
            steps.append(inner)
            lv = lv + [Var(acc)]
            self.feat("body:inner_seq_loop")
        if out.type != "integer":
            oe = self.typed_store(out.type, lv, ivars, out.name)
        else:
            oe = self.bounded(self.expr(3, lv))
        tgt = ARef(out.name, outidx)
        lines += wrap_stmt("", f"{tgt.f()} = {oe.f()}")
        steps.append(lambda env, a, oe=oe, tgt=tgt: a[tgt.arr].__setitem__(
            tuple(x.ev(env, a) for x in tgt.idx), oe.ev(env, a)))
        for red in reds:
            if red.type == "pair":
                ex, ey = self.udr_term(lv)
                lines += wrap_stmt("", f"{red.var} = pair_t({red.var}%x + "
                                   f"{ex.f()}, {red.var}%y + {ey.f()})")

                def pupd(env, a, ex=ex, ey=ey, red=red):
                    x, y = env[red.var]
                    env[red.var] = (_chk(x + ex.ev(env, a)),
                                    _chk(y + ey.ev(env, a)))
                steps.append(pupd)
                continue
            if red.type != "integer":
                ce = self.typed_red_term(red.type, red.op, lv, ivars,
                                         self.n * self.m, red.init)
                lines += self.red_lines(red, ce)

                def tupd(env, a, ce=ce, red=red):
                    env[red.var] = red_apply_typed(
                        TYPES[red.type][0], red.op, env[red.var],
                        ce.ev(env, a))
                steps.append(tupd)
                continue
            ce = self.red_term(red.op, lv)
            lines += self.red_lines(red, ce)

            def upd(env, a, ce=ce, red=red):
                v = ce.ev(env, a)
                env[red.var] = red_apply(red.op, env[red.var], v)
                # any combination order stays in range
                key = "_abs_" + red.var
                env[key] = _chk(env.get(key, abs(red.init)) + abs(v)) \
                    if red.op == "+" else _chk(env.get(key, max(1, abs(
                        red.init))) * max(1, abs(v))) if red.op == "*" else 0
            steps.append(upd)
        for name, cond in lps:
            le = self.expr(2, lv)
            if cond is None:
                lines += wrap_stmt("", f"{name} = {le.f()}")
                steps.append(lambda env, a, le=le, name=name:
                             env.__setitem__(name, le.ev(env, a)))
            else:
                lines += wrap_stmt("", f"if ({cond.f()}) {name} = {le.f()}")

                def cl(env, a, le=le, name=name, cond=cond):
                    if cond.ev(env, a):
                        env[name] = le.ev(env, a)
                        env["_set_" + name] = 1
                steps.append(cl)

        def run(env, a):
            for s in steps:
                s(env, a)
        return lines, run

    def run_points(self, levels: list[Level], step: Callable,
                   parallel: bool = True) -> None:
        """Run `step` at every iteration point. From fuzz-3 the points of
        a parallel loop are checked for races (``_Tracked``): an array
        element one point writes is neither written nor read by another
        point (the reductions live in the scalars, not here)."""
        env = self.env
        arrs = _Tracked(self.arrs) if self.v >= 3 and parallel \
            else self.arrs
        if len(levels) == 1:
            for i in levels[0].values(self.size(levels[0].extent)):
                env[levels[0].var] = i
                if arrs is not self.arrs:
                    arrs.point = (i,)
                step(env, arrs)
        else:
            for i in levels[0].values(self.size(levels[0].extent)):
                for j in levels[1].values(self.size(levels[1].extent)):
                    env[levels[0].var], env[levels[1].var] = i, j
                    if arrs is not self.arrs:
                        arrs.point = (i, j)
                    step(env, arrs)
        if arrs is not self.arrs:
            race = arrs.race()
            if race:
                self.race_redraws += 1
                raise Overflow(f"race: {race}")

    def new_levels(self, count: int) -> list[Level]:
        out = []
        for d in range(count):
            form = self.r.choices(("up", "down", "step2"), (6, 2, 1))[0]
            out.append(Level("ij"[d], "nm"[d], form))
            self.feat(f"loop:{form}")
        return out

    # -- clauses of the target group --

    def map_clauses(self, reads: set, writes: dict, scal_reads: set,
                    scal_writes: set, implied: set) -> tuple[list, set]:
        """Map/firstprivate clauses of a target group and the variables
        left implicit. `writes`: array -> full | partial | scratch;
        `implied`: scalars a clause on the combined target already maps
        tofrom (5.2 §17.2)."""
        r = self.r
        by_type: dict[str, list[str]] = {}
        implicit: set = set()
        fp: list[str] = []
        handled: set = set()
        if self.dvars:
            pairs, implicit, handled = self.struct_maps(
                reads | set(writes), reads, writes)
            for key, item in pairs:
                by_type.setdefault(key, []).append(item)
        for name in sorted((reads | set(writes)) - handled):
            kind = writes.get(name)
            if self.arrays[name].rank == 0:
                # a character or allocatable scalar: always mapped
                # explicitly (offload.engine.fuzz_base)
                opts = ("to", "tofrom")
            elif name in self.ptrs and kind == "full" and name not in reads:
                opts = ("from", "tofrom")   # a pointer: always explicit
            elif name in self.ptrs:
                opts = ("tofrom",) if kind else ("to", "tofrom")
            elif kind == "scratch":
                opts = ("alloc", "tofrom", "implicit")
            elif kind == "full" and name not in reads:
                opts = ("from", "tofrom", "implicit")
            elif kind:
                opts = ("tofrom", "implicit")
            else:
                opts = ("to", "tofrom", "implicit")
            t = r.choice(opts)
            self.feat(f"map:{t}")
            if t == "implicit":
                implicit.add(name)
                continue
            mods = [m for m, p in (("always", 0.25), ("close", 0.2))
                    if self.sw("map_" + m, p)]
            # in a data region the host copy of an earlier kernel's output
            # is stale: always would copy it over the device copy
            if self.in_data and "always" in mods and kind is None and \
                    self.arrays[name].role == "output":
                mods.remove("always")
            if self.in_data and self.sw("map_present", 0.3) and \
                    self.arrays[name].role in ("input", "output"):
                mods.append("present")
            for mm in mods:
                self.feat(f"map:mod:{mm}")
            item = name
            if self.sw("map_section", 0.3) and self.arrays[name].rank:
                self.feat("map:section")
                item = f"{name}(1:n)" if self.arrays[name].rank == 1 else \
                    r.choice((f"{name}(:, 1:m)", f"{name}(:, :)"))
            by_type.setdefault(", ".join(mods + [t]), []).append(item)
        for name in sorted(scal_reads):
            # FLANG_FALSE_REJECTS: one program never both firstprivates
            # and maps the same variable on target constructs
            opts = [x for x in ("implicit", "implicit", "firstprivate", "to",
                                "tofrom")
                    if self.pmode.get(name) is None or x == "implicit"
                    or (x == "firstprivate") == (self.pmode[name] == "fp")]
            t = r.choice(opts)
            if t != "implicit":
                self.pmode[name] = "fp" if t == "firstprivate" else "map"
            self.feat(f"scalar:{t}")
            if t == "implicit":
                implicit.add(name)
            elif t == "firstprivate":
                fp.append(name)
            else:
                by_type.setdefault(t, []).append(name)
        for name in sorted(scal_writes):
            if name in implied:
                # 5.2 §17.2: the reduction/lastprivate clause on the
                # combined target maps it tofrom (flang rejects an
                # explicit map of it as well)
                self.feat("scalar:implied_tofrom")
                continue
            by_type.setdefault("always, tofrom" if self.sw("map_always", 0.2)
                               else "tofrom", []).append(name)
        out = []
        groups = sorted(by_type.items())
        if self.coin(0.4):
            out += [f"map({key}: {x})" for key, items in groups
                    for x in items]
        else:
            out += [f"map({key}: {', '.join(items)})"
                    for key, items in groups]
        if fp:
            out.append(f"firstprivate({', '.join(fp)})")
        return out, implicit

    def defaultmap(self, implicit: set, writes: dict, cl: list = ()
                   ) -> str | None:
        """A defaultmap clause that keeps the result for every implicitly
        mapped variable of its category (see the Ruling), or None."""
        r = self.r
        if not self.sw("defaultmap", 0.5):
            return None
        cat = r.choice(("scalar", "aggregate", "allocatable", "all"))
        members = []
        for name in sorted(implicit):
            if name in self.dvars:          # a structure (fuzz-3)
                if cat in ("aggregate", "all"):
                    members.append(name)
            elif name in self.arrays:
                cats = {"aggregate", "all"} | (
                    {"allocatable"} if self.arrays[name].alloc else set())
                if cat in cats:
                    members.append(name)
            elif cat in ("scalar", "all"):
                members.append(name)
        safe = {"default", "tofrom"}
        for name in members:
            if name in self.dvars:
                # from/alloc of a whole structure would clobber the
                # components the kernel does not write
                safe &= {"default", "tofrom"} if self.dvar_written(
                    name, writes) else {"default", "tofrom", "to",
                                        "firstprivate"}
            elif name not in self.arrays:
                safe &= {"default", "tofrom", "to", "firstprivate"}
            elif writes.get(name) == "full":
                safe &= {"default", "tofrom", "from"}
            elif writes.get(name) == "scratch":
                safe &= {"default", "tofrom", "alloc"}
            elif writes.get(name):
                safe &= {"default", "tofrom"}
            else:
                safe &= {"default", "tofrom", "to", "firstprivate"}
        if not members:
            safe = {"default", "tofrom", "to", "from", "firstprivate",
                    "alloc"}
            # none only for arrays: scalars such as the logical of an if
            # clause on an inner construct may be referenced implicitly
            if cat in ("aggregate", "allocatable"):
                safe.add("none")
        if any("(" in c.split(":", 1)[-1] for c in cl if c.startswith("map(")):
            safe.discard("none")  # flang: a section does not list the array
        if self.in_data and members and all(
                x in self.dvars or (x in self.arrays and
                                    self.arrays[x].role != "scratch")
                for x in members):
            safe.add("present")
        if self.v >= 2 and cat in ("scalar", "all"):
            safe &= {"default", "tofrom", "to", "firstprivate"}
        beh = r.choice(sorted(safe))
        self.feat(f"defaultmap:{beh}:{cat}")
        return f"defaultmap({beh}: {cat})"

    def target_extras(self, g: Group) -> list[str]:
        r = self.r
        out = []
        if g.allows("device") and self.sw("device", 0.25):
            self.uses_dev = True
            self.api.add("omp_get_default_device")
            out.append("device(dev)" if self.coin(0.5)
                       else "device(device_num: dev)")
            self.feat("clause:device")
        if g.allows("if") and self.sw("if_target", 0.25):
            self.logicals["lt"] = True
            out.append("if(target: lt)" if self.coin(0.6) else "if(lt)")
            self.feat("clause:if:target")
        if g.allows("thread_limit") and not (g.has("parallel") and
                                             g.has("do")) and \
                self.sw("thread_limit", 0.3):  # FLANG_FALSE_REJECTS
            out.append(f"thread_limit({r.choice((1, 8, 32, 64, 256))})")
            self.feat("clause:thread_limit")
        return out

    def target_clauses(self, g: Group, reads, writes, scal_reads,
                       scal_writes, implied, temps=()) -> list[str]:
        if self.bsw and self.dtv:
            # declare target variables: never in a map clause (fuzz_base)
            reads = {x for x in reads if self.var_of(x) not in self.dtv}
            writes = {x: v for x, v in writes.items()
                      if self.var_of(x) not in self.dtv}
        cl, implicit = self.map_clauses(reads, writes, scal_reads,
                                        scal_writes, implied)
        # temporaries are implicitly firstprivate scalars of the region
        implicit |= set(temps)
        dm = self.defaultmap(implicit, writes, cl) if \
            g.allows("defaultmap") else None
        return cl + ([dm] if dm else []) + self.target_extras(g)

    # -- the loop kernel --

    def k_loop(self, ind: str) -> Kern:
        r = self.r
        chain = r.choice([c for c in target_chains()
                          if c[-1] in LOOP_LEAVES])
        parts = [p for p in partitions(chain)
                 if sum(g[-1] in LOOP_LEAVES for g in p) <= 2]
        part = parts[0] if len(parts) == 1 or not self.sw("split", 0.8) else \
            r.choice(parts[1:])
        groups = [Group(g) for g in part]
        loops = [g for g in groups if g.is_loop]
        nlev = 2 if len(loops) == 2 else (2 if self.sw("two_d", 0.5) else 1)
        for g in loops:
            g.levels = 1
        if nlev == 2 and len(loops) == 1:
            loops[0].levels = 2
        levels = self.new_levels(nlev)
        li = 0
        for g in loops:
            g.vars = tuple(lvl.var for lvl in levels[li:li + g.levels])
            li += g.levels
        otyp = self.out_type(nlev) if self.bsw else "integer"
        out = (self.modvar_output(nlev) if self.bsw else None) or (
            self.component_output(nlev, otyp) if self.dvars else None) \
            or self.new_array(f"o{self.k}", nlev, "output", otyp)
        if "alloc" in self.base:
            self.pointer_output(out)
        full = all(lvl.form != "step2" for lvl in levels)
        ivars = {lvl.var: lvl.extent for lvl in levels}
        readable = self.readable(out.name)
        teams = any(g.has("teams") for g in groups)
        concurrent = any(g.has("simd") or g.has("loop") for g in groups)
        if not concurrent and self.sw("order", 0.4):
            # innermost only: an order(concurrent) region may hold only
            # loop, parallel and simd constructs (5.2 §10.3)
            cands = [g for g in loops[-1:] if g.allows("order")]
            if cands:
                g = r.choice(cands)
                g.clauses.append(r.choice((
                    "order(concurrent)", "order(reproducible: concurrent)",
                    "order(unconstrained: concurrent)")))
                self.feat("clause:order")
                concurrent = True
        reds = []
        # FLANG_FALSE_REJECTS: no reduction when a loop group is closely
        # nested in a teams group
        loop_in_teams = any(g.leaves[0] == "loop" and gi and
                            groups[gi - 1].leaves[-1] == "teams"
                            for gi, g in enumerate(groups))
        for idx in range(r.choice((1, 1, 2)) if self.on("reduction")
                         and not loop_in_teams else 0):
            method = "clause"
            if not concurrent and (self.sw("atomic", 0.5) or self.sw(
                    "critical", 0.4)):
                method = "atomic" if teams or not self.on("critical") or \
                    (self.on("atomic") and self.coin(0.5)) else "critical"
            udr = self.udr_red(idx) if self.bsw and method == "clause" \
                else None
            reds.append(udr or self.new_red(idx, method,
                                            typed=bool(self.bsw)))
            self.feat(f"red:{method}", f"red:{method}:{reds[-1].op}")
        lps = []
        # lastprivate on a loop construct takes only its iteration variable
        # (5.2 §11.7.1 loop-dsa-001); conditional is not allowed on
        # distribute (§11.6 distribute-clause-001)
        if self.sw("lastprivate", 0.5) and all(g.allows("lastprivate") and
                                   not g.has("loop") for g in loops):
            name = self.new_scalar(f"lp{self.k}", 0)
            self.check_items.append(name)
            cond = None
            if self.sw("conditional", 0.5) and not any(g.has("distribute")
                                          for g in loops):
                cond = Cond("==", Intr("mod", (Var(levels[0].var), Const(
                    r.randint(2, 5)))), Const(r.randint(0, 1)))
                self.feat("clause:lastprivate:conditional")
            lps.append((name, cond))
            self.feat("clause:lastprivate")
        temps: list[str] = []
        body, step = self.point(ivars, out, tuple(Var(v) for v in ivars),
                                reds, lps, temps, nlev == 1 and
                                self.sw("inner_loop", 0.5), readable)
        self.run_points(levels, step)
        for name, cond in lps:
            if cond is not None and not self.env.pop("_set_" + name, 0):
                raise Overflow("conditional lastprivate never assigned")
        text = "\n".join(body)
        reads = {n for n in readable if re.search(rf"\b{n}\(", text)}
        if self.bsw:
            reads |= self.read_in(text, out.name)
        writes = {out.name: "full" if full else "partial"}
        self.full_out[out.name] = full
        scal_reads = {p for p in self.params()
                      if re.search(rf"\b{p}\b", text)}
        # clauses that do not depend on the target's maps
        for gi, g in enumerate(groups):
            if g.levels == 2:
                g.clauses.append("collapse(2)")
                self.feat("clause:collapse")
            nxt = groups[gi + 1] if gi + 1 < len(groups) else None
            # a worksharing (or loop) construct's reduction needs the item
            # shared in the binding parallel/teams region (5.2 §5.5.8
            # reduction-dsa-001): the enclosing block group has none
            binds = (not g.is_loop and nxt is not None
                     and nxt.leaves[0] in ("do", "loop"))
            for red in reds:
                if red.method == "clause" and g.allows("reduction") and (
                        set(g.leaves) - {"target", "distribute"}) and \
                        not binds:
                    g.clauses.append(f"reduction({red.op}: {red.var})")
            for name, cond in lps:
                if g.is_loop and g.allows("lastprivate"):
                    mod = "conditional: " if cond is not None else ""
                    g.clauses.append(f"lastprivate({mod}{name})")
        if temps:
            groups[-1].clauses.append(f"private({', '.join(temps)})")
        flag_at = self.flag_position(groups)
        flag = self.new_flag() if flag_at else None
        scal_writes = {red.var for red in reds} | {n for n, _ in lps} | (
            {flag} if flag else set())
        tgt = groups[0]
        implied = {v for v in scal_writes if any(
            re.search(rf"\b(reduction|lastprivate)\([^)]*\b{v}\b", c)
            for c in tgt.clauses)} if len(tgt.leaves) > 1 else set()
        # innermost first: default(none) lists what the inner groups use
        for gi in range(len(groups) - 1, 0, -1):
            self.group_extras(groups[gi], gi, groups, text, temps, reds, lps,
                              flag)
        tgt.clauses = self.target_clauses(
            tgt, reads, writes, scal_reads, scal_writes, implied,
            temps) + tgt.clauses
        self.group_extras(tgt, 0, groups, text, temps, reds, lps, flag)
        lines = self.nest(ind, groups, 0, levels, 0, body, flag, flag_at, [])
        self.kdesc.append("loop: " + " / ".join(g.key for g in groups)
                          + f" ({nlev}D)")
        self.feat("kernel:loop", "chain:" + " ".join(chain),
                  "split:" + " | ".join(g.key for g in groups))
        for g in groups:
            self.feat(f"dir:{g.key}")
        self.check_items.append(out.name)
        return Kern(lines, reads | scal_reads, set(writes) | scal_writes)

    def flag_position(self, groups: list[Group]):
        """(group index, "loop"|"block") of the outermost place where a
        statement may call omp_is_initial_device: outside every simd, loop
        and order(concurrent) region (5.2 §10.3, §10.4, §11.7.1), not in
        a target that contains teams (§10.2), not in a teams body outside
        a nested construct (Ruling); None if there is no such place."""
        for gi, g in enumerate(groups):
            if g.has("simd") or g.has("loop") or any(
                    c.startswith("order(") for c in g.clauses):
                return None
            if g.is_loop:
                return gi, "loop"
            nxt = groups[gi + 1] if gi + 1 < len(groups) else None
            if nxt is None:
                return None
            if g.leaves[-1] == "teams" or (g.leaves[-1] == "target"
                                           and nxt.leaves[0] == "teams"):
                continue
            return gi, "block"
        return None

    def group_extras(self, g: Group, gi: int, groups: list[Group], text: str,
                     temps: list, reds: list, lps: list, flag) -> None:
        r = self.r
        if g.has("teams") and g.allows("num_teams") and self.sw("num_teams", 0.5):
            if self.coin(0.2):
                g.clauses.append(f"num_teams({r.randint(1, 2)}: "
                                 f"{r.randint(2, 16)})")
                self.feat("clause:num_teams:lower_bound")
            else:
                g.clauses.append(f"num_teams({r.choice((1, 2, 4, 7, 64))})")
            self.feat("clause:num_teams")
        if g.has("teams") and not g.has("target") and \
                g.allows("thread_limit") and self.sw("thread_limit", 0.3):
            g.clauses.append(f"thread_limit({r.choice((1, 16, 64))})")
            self.feat("clause:thread_limit")
        if g.has("parallel") and g.allows("num_threads") and \
                self.sw("num_threads", 0.5):
            g.clauses.append(f"num_threads({r.choice((1, 2, 3, 8, 64))})")
            self.feat("clause:num_threads")
        if g.has("parallel") and g.allows("proc_bind") and \
                self.sw("proc_bind", 0.3):
            g.clauses.append("proc_bind("
                             f"{r.choice(('spread', 'close', 'primary'))})")
            self.feat("clause:proc_bind")
        # one if clause without a directive-name modifier applies to every
        # leaf: no second if clause then (5.2 §3.4 if-clause-001)
        bare_if = any(re.match(r"if\([^:]*\)$", c) for c in g.clauses)
        if g.has("parallel") and g.allows("if") and not bare_if and \
                self.sw("if_parallel", 0.3):
            self.logicals.setdefault("lpar", self.coin(0.5))
            g.clauses.append("if(parallel: lpar)")
            self.feat("clause:if:parallel")
        if g.has("simd") and g.allows("if") and not bare_if and \
                self.sw("if_simd", 0.3):
            self.logicals.setdefault("lsimd", self.coin(0.5))
            g.clauses.append("if(simd: lsimd)")
            self.feat("clause:if:simd")
        if g.has("do") and g.allows("schedule") and \
                self.sw("schedule", 0.6):
            kind = r.choice(("static", "dynamic", "guided", "auto",
                             "runtime"))
            text_ = kind
            if kind in ("static", "dynamic", "guided") and self.coin(0.5):
                text_ += f", {r.choice((1, 2, 3, 7, 16))}"
            mods = []
            if self.coin(0.3):
                mods.append("monotonic" if kind not in ("dynamic", "guided")
                            or self.coin(0.5) else "nonmonotonic")
            if g.has("simd") and self.coin(0.3):
                mods.append("simd")
            g.clauses.append(f"schedule({', '.join(mods) + ': ' if mods else ''}"
                             f"{text_})")
            self.feat("clause:schedule", f"clause:schedule:{kind}")
        if g.has("distribute") and g.allows("dist_schedule") and \
                self.sw("dist_schedule", 0.5):
            g.clauses.append("dist_schedule(static" + (
                f", {r.choice((1, 2, 5, 16))})" if self.coin(0.6) else ")"))
            self.feat("clause:dist_schedule")
        if g.has("simd") and g.allows("simdlen") and \
                self.sw("simdlen", 0.5):
            sl = r.choice((1, 2, 4, 8, 16))
            g.clauses.append(f"simdlen({sl})")
            self.feat("clause:simdlen")
            if g.allows("safelen") and self.coin(0.5):
                g.clauses.append(f"safelen({sl * r.choice((1, 2))})")
                self.feat("clause:safelen")
        elif g.has("simd") and g.allows("safelen") and \
                self.sw("safelen", 0.4):
            g.clauses.append(f"safelen({r.choice((1, 4, 16))})")
            self.feat("clause:safelen")
        if g.leaves[-1] == "loop" and g.allows("bind") and \
                self.sw("bind", 0.6):
            prev = groups[gi - 1] if gi else None
            if len(g.leaves) > 1:
                outer = g.leaves[-2]
            elif prev is not None and not prev.is_loop:
                outer = prev.leaves[-1]
            else:
                outer = None
            bind = {"teams": "teams", "parallel": "parallel"}.get(outer,
                                                                  "thread")
            g.clauses.append(f"bind({bind})")
            self.feat(f"clause:bind:{bind}")
        inner = text + "\n" + "\n".join(c for h in groups[gi + 1:]
                                        for c in h.clauses)
        if (g.has("teams") or g.has("parallel")) and not g.has("target") \
                and g.allows("default") and self.sw("default", 0.5):
            if self.coin(0.5):
                g.clauses.append("default(shared)")
                self.feat("clause:default:shared")
            else:
                outer = {v for h in groups[:gi] for v in h.vars}
                if self.v >= 4:
                    # G1: the group's if clauses of leaves
                    # nested inside the default's leaf are evaluated
                    # inside its region
                    inner += "\n" + "\n".join(nested_if_clauses(
                        g.leaves, g.clauses))
                self.default_none(g, inner, temps, reds, lps, flag, outer)
        elif (g.has("teams") or g.has("parallel")) and g.allows("shared") \
                and self.sw("shared", 0.3):
            arrs = sorted(a for a in self.arrays
                          if re.search(rf"\b{a}\(", inner)) if not \
                self.dvars else sorted({self.var_of(a) for a in self.arrays
                                        if re.search(self.ref_re(a), inner)})
            if arrs:
                g.clauses.append(f"shared({', '.join(arrs)})")
                self.feat("clause:shared")
        # firstprivate only on teams/parallel: on a worksharing or
        # distribute construct it would name an item private in the
        # binding region (5.2 §5.4.4 firstprivate-dsa-001/002)
        if g.allows("firstprivate") and self.sw("firstprivate", 0.3) and \
                not g.is_loop and "default(none)" not in g.clauses:
            ps = [p for p in self.params() if re.search(rf"\b{p}\b", inner)
                  and not any(re.search(rf"\b{p}\b", c) for c in g.clauses)
                  and self.pmode.get(p, "fp") == "fp"]
            for p in ps:
                self.pmode[p] = "fp"
            if ps:
                g.clauses.append(f"firstprivate({', '.join(ps)})")
                self.feat("clause:firstprivate")
        if g.has("simd") and g.allows("nontemporal") and \
                self.sw("nontemporal", 0.3):
            m = re.search(r"(?<![%\w])(o\d+)\(", text)
            if m:
                g.clauses.append(f"nontemporal({m.group(1)})")
                self.feat("clause:nontemporal")

    def default_none(self, g: Group, inner: str, temps, reds, lps,
                     flag, outer: set = frozenset()) -> None:
        """default(none) with every variable referenced in the construct
        listed (5.2 §5.4.1); the group's own associated loop variables are
        predetermined and not listed; the loop variables of enclosing loop
        groups (`outer`) keep their values: firstprivate."""
        names = set(re.findall(r"\b([a-z]\w*)\b", inner))
        own = set(g.vars)
        listed = {x for c in g.clauses for x in re.findall(r"\b\w+\b", c)}
        private = sorted((set(temps) | ({"i", "j", "jj"} & names)) - own
                         - listed - set(outer))
        shared = {self.var_of(a) for a in self.arrays
                  if self.var_of(a) in names}
        shared |= {red.var for red in reds if red.var not in listed}
        shared |= {n for n, _ in lps if n not in listed}
        if flag:
            shared.add(flag)
        fp = sorted(v for v in self.params() + list(self.logicals)
                    if v in names) + sorted(set(outer) & names)
        g.clauses.append("default(none)")
        if shared:
            g.clauses.append(f"shared({', '.join(sorted(shared))})")
        if private:
            g.clauses.append(f"private({', '.join(private)})")
        if fp:
            g.clauses.append(f"firstprivate({', '.join(fp)})")
        self.feat("clause:default:none")

    def nest(self, ind, groups, gi, levels, li, body, flag, flag_at,
             outer: list) -> list[str]:
        g = groups[gi]
        lines = wrap_directive(ind, g.key, g.clauses)
        if g.is_loop:
            used = levels[li:li + g.levels]
            cur = ind
            for lvl in used:
                lines.append(cur + lvl.header())
                cur += "  "
            seen = outer + used
            if flag_at == (gi, "loop"):
                cond = " .and. ".join(f"{lvl.var} == {lvl.first()}"
                                      for lvl in seen)
                lines.append(f"{cur}if ({cond}) {self.flag_stmt(flag)}")
            if gi + 1 < len(groups):
                lines += self.nest(cur, groups, gi + 1, levels,
                                   li + g.levels, body, flag, flag_at, seen)
            else:
                lines += [cur + s for s in body]
            for _ in used:
                cur = cur[:-2]
                lines.append(cur + "end do")
            if self.coin(0.5):
                lines.append(f"{ind}!$omp end {g.key}")
            return lines
        inner = ind + "  "
        if flag_at == (gi, "block"):
            conds = [f"{lvl.var} == {lvl.first()}" for lvl in outer]
            if g.has("parallel"):
                conds.append("omp_get_thread_num() == 0")
                self.api.add("omp_get_thread_num")
            stmt = self.flag_stmt(flag)
            lines.append(f"{inner}if ({' .and. '.join(conds)}) {stmt}"
                         if conds else inner + stmt)
        lines += self.nest(inner, groups, gi + 1, levels, li, body, flag,
                           flag_at, outer)
        lines.append(f"{ind}!$omp end {g.key}")
        return lines

    # -- the guard kernel --

    def k_guard(self, ind: str) -> Kern:
        r = self.r
        shape = r.choice(("par_thread0", "par_thread0", "single", "masked",
                          "teams_team0", "target_seq", "split_par_thread0",
                          "teams_team0_pardo"))
        otyp = self.out_type(1) if self.bsw else "integer"
        out = (self.modvar_output(1) if self.bsw else None) or (
            self.component_output(1, otyp) if self.dvars else None) \
            or self.new_array(f"o{self.k}", 1, "output", otyp)
        if "alloc" in self.base:
            self.pointer_output(out)
        lvl = self.new_levels(1)[0]
        readable = self.readable(out.name)
        pardo = shape == "teams_team0_pardo"
        reds = [self.new_red(idx, "clause" if pardo else "plain",
                             typed=bool(self.bsw))
                for idx in range(r.choice((0, 1, 1)))]
        temps: list[str] = []
        body, step = self.point({"i": "n"}, out, (Var("i"),), reds, [],
                                temps, self.coin(0.2), readable)
        self.run_points([lvl], step, parallel=pardo)
        flag = self.new_flag()
        text = "\n".join(body)
        reads = {n for n in readable if re.search(rf"\b{n}\(", text)}
        if self.bsw:
            reads |= self.read_in(text, out.name)
        writes = {out.name: "partial" if lvl.form == "step2" else "full"}
        self.full_out[out.name] = lvl.form != "step2"
        scal_reads = {p for p in self.params()
                      if re.search(rf"\b{p}\b", text)}
        scal_writes = {red.var for red in reds} | {flag}
        head = Group({"par_thread0": ("target", "parallel"),
                      "single": ("target", "parallel"),
                      "masked": ("target", "parallel"),
                      "teams_team0": ("target", "teams"),
                      "teams_team0_pardo": ("target", "teams")}.get(
                          shape, ("target",)))
        tcl = self.target_clauses(head, reads, writes, scal_reads,
                                  scal_writes, set(), temps)
        if head.has("parallel") and self.coin(0.3):
            tcl.append(f"num_threads({r.choice((1, 4, 64, 256))})")
            self.feat("clause:num_threads")
        if head.has("teams") and self.coin(0.3):
            tcl.append(f"num_teams({r.choice((1, 3, 8))})")
            self.feat("clause:num_teams")
        if head.has("parallel") and temps and self.coin(0.5):
            tcl.append(f"private({', '.join(temps)})")
            temps = []
        if head.has("parallel") and self.coin(0.2):
            tcl.append("private(i)")
            self.feat("clause:private:loop_variable")
        b, c = ind + "  ", ind + "    "
        seq = [lvl.header()] + ["  " + s for s in body] + ["end do"]
        fl = self.flag_stmt(flag)
        lines = wrap_directive(ind, head.key, tcl)
        if shape == "par_thread0":
            self.api.add("omp_get_thread_num")
            lines += [f"{b}if (omp_get_thread_num() == 0) then", c + fl]
            lines += [c + s for s in seq] + [f"{b}end if"]
        elif shape == "single":
            lines += [f"{b}!$omp single", c + fl] + [c + s for s in seq]
            lines.append(f"{b}!$omp end single"
                         + (" nowait" if self.coin(0.3) else ""))
        elif shape == "masked":
            lines.append(f"{b}!$omp masked"
                         + (" filter(0)" if self.coin(0.4) else ""))
            lines += [c + fl] + [c + s for s in seq] + [f"{b}!$omp end masked"]
        elif shape == "split_par_thread0":
            self.api.add("omp_get_thread_num")
            pcl = []
            if self.coin(0.3):
                pcl.append(f"num_threads({r.choice((2, 8, 64))})")
            if temps and self.coin(0.5):
                pcl.append(f"private({', '.join(temps)})")
            lines += wrap_directive(b, "parallel", pcl)
            lines += [f"{c}if (omp_get_thread_num() == 0) then",
                      c + "  " + fl] + [c + "  " + s for s in seq]
            lines += [f"{c}end if", f"{b}!$omp end parallel"]
        elif shape == "teams_team0":
            self.api |= {"omp_get_team_num", "omp_get_thread_num"}
            lines += [f"{b}if (omp_get_team_num() == 0) then",
                      f"{c}!$omp parallel",
                      f"{c}  if (omp_get_thread_num() == 0) {fl}",
                      f"{c}!$omp end parallel"]
            lines += [c + s for s in seq] + [f"{b}end if"]
        elif shape == "teams_team0_pardo":
            self.api.add("omp_get_team_num")
            lines.append(f"{b}if (omp_get_team_num() == 0) then")
            pcl = [f"reduction({red.op}: {red.var})" for red in reds]
            if temps:
                pcl.append(f"private({', '.join(temps)})")
            lines += wrap_directive(c, "parallel do", pcl)
            first = lvl.first()
            lines += [c + seq[0], f"{c}  if (i == {first}) {fl}"]
            lines += [c + s for s in seq[1:]] + [f"{b}end if"]
            self.feat("dir:parallel do")
        else:  # target_seq
            lines += [b + fl] + [b + s for s in seq]
        lines.append(f"{ind}!$omp end {head.key}")
        self.kdesc.append(f"guard: {shape}")
        self.feat("kernel:guard", f"guard:{shape}", f"dir:{head.key}")
        self.check_items.append(out.name)
        return Kern(lines, reads | scal_reads, set(writes) | scal_writes)

    # -- the phase kernel --

    def k_phase(self, ind: str) -> Kern:
        r = self.r
        out = self.new_array(f"o{self.k}", 1, "output")
        scr = self.new_array(f"s{self.k}", 1, "scratch")
        readable = self.readable(out.name)
        iv = {"i": "n"}
        e1 = self.bounded(self.expr(3, self.leaves(iv, readable)))
        for i in range(1, self.n + 1):
            self.env["i"] = i
            self.arrs[scr.name][(i,)] = e1.ev(self.env, self.arrs)
        lv2 = self.leaves(iv, readable) + [
            ARef(scr.name, (self.index("n", iv),)) for _ in range(3)]
        e2 = self.bounded(self.expr(3, lv2))
        if scr.name not in e2.f():
            e2 = Bin("+", e2, ARef(scr.name, (self.index("n", iv),)))
        reds = [self.new_red(0, "clause")] if self.coin(0.4) else []
        terms = [self.red_term(red.op, lv2) for red in reds]
        for i in range(1, self.n + 1):
            self.env["i"] = i
            self.arrs[out.name][(i,)] = e2.ev(self.env, self.arrs)
            for red, ce in zip(reds, terms):
                self.env[red.var] = red_apply(red.op, self.env[red.var],
                                              ce.ev(self.env, self.arrs))
        flag = self.new_flag()
        text = "\n".join([e1.f(), e2.f()] + [t.f() for t in terms])
        reads = {n for n in readable if re.search(rf"\b{n}\(", text)}
        if self.bsw:
            reads |= self.read_in(text, out.name)
        writes = {out.name: "full", scr.name: "scratch"}
        scal_reads = {p for p in self.params()
                      if re.search(rf"\b{p}\b", text)}
        scal_writes = {red.var for red in reds} | {flag}
        split = self.coin(0.3)
        head = Group(("target",) if split else ("target", "parallel"))
        tcl = self.target_clauses(head, reads, writes, scal_reads,
                                  scal_writes, set())
        pcl = []
        if self.coin(0.3):
            pcl.append(f"num_threads({r.choice((1, 2, 4, 64))})")
            self.feat("clause:num_threads")
        if split:
            lines = wrap_directive(ind, "target", tcl)
            lines += wrap_directive(ind + "  ", "parallel", pcl)
            b = ind + "    "
        else:
            lines = wrap_directive(ind, "target parallel", tcl + pcl)
            b = ind + "  "
        nowait = self.coin(0.4)
        d1 = r.choice(("do", "do", "do simd"))
        c1 = ([f"schedule(static, {r.choice((1, 4))})"]
              if self.coin(0.4) else [])
        lines += wrap_directive(b, d1, c1)
        lines += [f"{b}do i = 1, n"] + wrap_stmt(b + "  ",
                                                 f"{scr.name}(i) = {e1.f()}")
        lines += [f"{b}end do", f"{b}!$omp end {d1}"
                  + (" nowait" if nowait else "")]
        if nowait:
            lines.append(f"{b}!$omp barrier")
            self.feat("phase:nowait_barrier")
        d2 = r.choice(("do", "do", "loop", "do simd"))
        c2 = [f"reduction({red.op}: {red.var})" for red in reds]
        if d2 == "loop" and self.coin(0.5):
            c2.append("bind(parallel)")
        elif d2 != "loop" and self.coin(0.3):
            c2.append(f"schedule({r.choice(('dynamic', 'guided', 'static'))}"
                      ", 3)")
        lines += wrap_directive(b, d2, c2) + [f"{b}do i = 1, n"]
        lines += wrap_stmt(b + "  ", f"{out.name}(i) = {e2.f()}")
        for red, ce in zip(reds, terms):
            lines += [b + "  " + s for s in self.red_lines(red, ce)]
        lines += [f"{b}end do", f"{b}!$omp end {d2}"]
        mark = r.choice(("masked", "single"))
        lines += [f"{b}!$omp {mark}", f"{b}  {self.flag_stmt(flag)}",
                  f"{b}!$omp end {mark}"]
        if split:
            lines += [f"{ind}  !$omp end parallel", f"{ind}!$omp end target"]
        else:
            lines.append(f"{ind}!$omp end target parallel")
        self.kdesc.append(f"phase: {head.key}{' / parallel' if split else ''}"
                          f" {d1} / {d2}")
        self.feat("kernel:phase", f"dir:{head.key}", f"phase:{d1}",
                  f"phase:{d2}", f"phase:{mark}")
        self.check_items.append(out.name)
        return Kern(lines, reads | scal_reads, set(writes) | scal_writes)

    # -- the in_reduction kernel --

    def k_inred(self, ind: str) -> Kern:
        out = self.new_array(f"o{self.k}", 1, "output")
        readable = self.readable(out.name)
        inner_par = self.coin(0.4)
        red = self.new_red(0, "clause" if inner_par else "plain",
                           ops=("+", "*"))  # FLANG_FALSE_REJECTS
        temps: list[str] = []
        body, step = self.point({"i": "n"}, out, (Var("i"),), [red], [],
                                temps, False, readable)
        self.run_points([Level("i", "n", "up")], step, parallel=inner_par)
        flag = self.new_flag()
        text = "\n".join(body)
        reads = {n for n in readable if re.search(rf"\b{n}\(", text)}
        if self.bsw:
            reads |= self.read_in(text, out.name)
        scal_reads = {p for p in self.params()
                      if re.search(rf"\b{p}\b", text)}
        g = Group(("target",))
        tcl = self.target_clauses(g, reads, {out.name: "full"}, scal_reads,
                                  {flag}, set(), temps)
        tcl.append(f"in_reduction({red.op}: {red.var})")
        b = ind + "  "
        lines = [f"{ind}!$omp taskgroup task_reduction({red.op}: {red.var})"]
        lines += wrap_directive(b, "target", tcl)
        lines.append(f"{b}  {self.flag_stmt(flag)}")
        if inner_par:
            pcl = [f"reduction({red.op}: {red.var})"]
            if temps:
                pcl.append(f"private({', '.join(temps)})")
            lines += wrap_directive(b + "  ", "parallel do", pcl)
            self.feat("dir:parallel do")
        lines += [f"{b}  do i = 1, n"] + [f"{b}    {s}" for s in body]
        lines += [f"{b}  end do", f"{b}!$omp end target",
                  f"{ind}!$omp end taskgroup"]
        self.kdesc.append("inred: taskgroup task_reduction / target "
                          "in_reduction" + (" / parallel do" if inner_par
                                            else ""))
        self.feat("kernel:inred", "clause:in_reduction",
                  f"red:in_reduction:{red.op}", "dir:target",
                  "dir:taskgroup")
        self.check_items.append(out.name)
        return Kern(lines, reads | scal_reads, {out.name, red.var, flag})

    # -- the whole program --

    def kernel(self, flavor: str, ind: str) -> Kern:
        """One kernel, redrawn (from the same stream) until its model stays
        in range."""
        snap = self.snapshot()
        for _ in range(60):
            try:
                kern = getattr(self, f"k_{flavor}")(ind)
                for name in kern.writes:
                    if self.env.get("_abs_" + name, 0) >= LIMIT:
                        raise Overflow(name)
                    a = self.arrays.get(name)
                    if a is not None and a.type != "integer":
                        for v in self.arrs[name].values():
                            contributions(a.type, v)
                    elif name in self.tscalars:
                        contributions(self.tscalars[name][0],
                                      self.env[name])
                return kern
            except Overflow:
                self.restore(snap)
        raise RuntimeError(f"seed {self.seed}: no in-range kernel")

    def snapshot(self):
        return ({k: dict(v) for k, v in self.arrs.items()}, dict(self.env),
                dict(self.arrays), set(self.features), list(self.flags),
                list(self.check_items), set(self.api), dict(self.scalars),
                dict(self.logicals), self.uses_dev, list(self.kdesc),
                dict(self.pmode), dict(self.tscalars), dict(self.tbound),
                dict(self.spell), self.cur_out, dict(self.ptrs),
                dict(self.full_out))

    def restore(self, snap) -> None:
        (arrs, env, arrays, feats, flags, items, api, scal, logi, dev,
         kd, pm, tsc, tb, sp, co, pt, fo) = snap
        self.ptrs, self.full_out = dict(pt), dict(fo)
        self.tscalars, self.tbound, self.spell = dict(tsc), dict(tb), dict(sp)
        self.cur_out = co
        self.pmode = dict(pm)
        self.arrs = {k: dict(v) for k, v in arrs.items()}
        self.env, self.arrays = dict(env), dict(arrays)
        self.features, self.flags = set(feats), list(flags)
        self.check_items, self.api = list(items), set(api)
        self.scalars, self.logicals = dict(scal), dict(logi)
        self.uses_dev, self.kdesc = dev, list(kd)

    def build(self) -> FuzzProgram:
        r = self.r
        self.setup()
        nk = r.choice((1, 1, 2, 2, 3, 4))
        flavors = r.choices(("loop", "guard", "phase", "inred"),
                            (10, 4 * self.on("guard"), 2 * self.on("phase"),
                             2 * self.on("inred")), k=nk)
        wrapper = r.choice(("data", "enter")) if self.sw("wrapper", 0.7) \
            else "none"
        nowait = nk >= 2 and self.sw("nowait", 0.5)
        self.in_data = wrapper != "none"
        ind = "    " if wrapper == "data" else "  "
        kerns: list[Kern] = []
        updated = False
        for flavor in flavors:
            self.k += 1
            if wrapper != "none" and not updated and self.k > 1 and \
                    self.coin(0.4):
                kerns.append(self.host_update(ind))
                updated = True
            kerns.append(self.kernel(flavor, ind))
        if self.bon("al_proc") and not nowait:
            for kern in kerns:
                if not kern.host and self.rb.random() < 0.6:
                    kern.lines = self.wrap_in_procedure(kern, ind)
        body: list[str] = []
        pending = False
        for kern in kerns:
            plain = kern.host or kern.lines[0].lstrip().startswith(
                "!$omp taskgroup")
            if nowait and not plain:
                body += self.with_nowait(kern)
                pending = True
                continue
            if pending:
                body.append(f"{ind}!$omp taskwait")
                pending = False
            body += kern.lines
        if pending:
            body.append(f"{ind}!$omp taskwait")
        arrs = sorted(a.name for a in self.arrays.values()
                      if a.role in ("input", "output"))
        ins = [a for a in arrs if self.arrays[a].role == "input"]
        outs = [a for a in arrs if a not in ins]
        if self.dvars:      # structures are mapped whole by the wrapper
            outs = sorted({self.var_of(a) for a in outs})
            ins = sorted({self.var_of(a) for a in ins} - set(outs))
        if self.bsw and self.dtv:
            outs = [a for a in outs if a not in self.dtv]
            ins = [a for a in ins if a not in self.dtv]
        if wrapper == "data":
            cl = [f"map(to: {', '.join(ins)})"] + (
                [f"map(tofrom: {', '.join(outs)})"] if outs else [])
            body = wrap_directive("  ", "target data", cl) + body + \
                ["  !$omp end target data"]
            self.feat("wrap:target_data")
        elif wrapper == "enter":
            enter = [f"map(to: {', '.join(ins + outs)})"]
            ex = ([f"map(from: {', '.join(outs)})"] if outs else []) + [
                f"map({r.choice(('release', 'delete'))}: {', '.join(ins)})"]
            body = wrap_directive("  ", "target enter data", enter) + body \
                + wrap_directive("  ", "target exit data", ex)
            self.feat("wrap:enter_exit_data")
        expected = self.checksum()
        src = self.source(body, expected)
        if self.gen_version == "fuzz-4s50":
            src = spell50(src)
        return FuzzProgram(self.seed, src, expected,
                           frozenset(self.features), tuple(self.kdesc),
                           len(self.flags), self.gen_version, self.base)

    def host_update(self, ind: str) -> Kern:
        """The host changes an input inside the data region and updates
        the device copy (5.2 §13.9)."""
        name = self.r.choice(("ia", "ib"))
        if self.dvars:
            name = self.rb.choice([name] + [
                a.name for a in self.arrays.values() if a.var and
                a.role == "input" and a.rank and a.type == "integer"
                and "(@)" not in a.name])
            if name != "ia" and name != "ib":
                self.feat("base:dt:target_update_component")
        c = self.r.randint(1, 9)
        if self.bon("al_stride_update") and self.rb.random() < 0.6:
            # only the odd elements change: a strided section is enough
            for t in self.arrs[name]:
                if t[0] % 2 == 1:
                    self.arrs[name][t] += c
            self.feat("wrap:host_update_to", "base:al:strided_update")
            return Kern([f"{ind}do i = 1, n, 2",
                         f"{ind}  {name}(i) = {name}(i) + {c}",
                         f"{ind}end do",
                         f"{ind}!$omp target update to({name}(1:n:2))"],
                        set(), set(), host=True)
        for t in self.arrs[name]:
            self.arrs[name][t] += c
        self.feat("wrap:host_update_to")
        return Kern([f"{ind}do i = 1, n", f"{ind}  {name}(i) = {name}(i) + {c}",
                     f"{ind}end do", f"{ind}!$omp target update to({name})"],
                    set(), set(), host=True)

    def with_nowait(self, kern: Kern) -> list[str]:
        """The kernel's target directive with nowait and depend clauses
        (5.2 §13.8, §15.9.5); a taskwait follows the sequence. A variable
        the kernel only reads is depend(in) when the target maps it to or
        firstprivate; else (an implicit or tofrom map copies it back) it is
        depend(inout), so no two tasks touch it concurrently."""
        text = []
        for line in kern.lines:
            text.append(line)
            if not line.rstrip().endswith("&"):
                break
        head = " ".join(text)
        only_in = set(map_items(head, ("to",))) | set(
            x for c in re.findall(r"firstprivate\(([^)]*)\)", head)
            for x in re.split(r"\s*,\s*", c.strip()))
        ro = kern.reads - kern.writes
        ins = sorted(ro & only_in)
        outs = sorted(kern.writes | (ro - only_in))
        if self.dvars:
            ins, outs = self.struct_depend(set(kern.reads), set(kern.writes),
                                           head)
        extra = ["nowait"]
        if self.bon("al_depend_section"):
            def sec(x):
                a = self.arrays.get(x)
                if a is not None and not a.var and a.rank == 1 and \
                        self.rb.random() < 0.5:
                    self.feat("base:al:depend_section")
                    return f"{x}(1:n)" if self.rb.random() < 0.5 else \
                        f"{x}(:)"
                return x
            ins, outs = [sec(x) for x in ins], [sec(x) for x in outs]
        if ins:
            extra.append(f"depend(in: {', '.join(ins)})")
        if outs:
            extra.append(f"depend({self.r.choice(('out', 'inout'))}: "
                         f"{', '.join(outs)})")
        self.feat("tasking:nowait_depend")
        return add_clauses(kern.lines, extra)

    def checksum(self) -> int:
        cs = 0
        for item in self.check_items:
            if item in self.arrays:
                typ = self.arrays[item].type
                for t in self.points(self.arrays[item]):
                    for c in contributions(typ, self.arrs[item][t]):
                        cs = (cs * 31 + c) % CHECK_MOD
            elif item in self.tscalars:
                for c in contributions(self.tscalars[item][0],
                                       self.env[item]):
                    cs = (cs * 31 + c) % CHECK_MOD
            else:
                cs = (cs * 31 + self.env[item]) % CHECK_MOD
        return cs

    def source(self, body: list[str], expected: int) -> str:
        L = ["! Generated by compliance.fuzz (OpenMP 5.2, free-form "
             "Fortran). Do not edit.",
             f"! generator: {self.gen_version}",
             f"! seed: {self.seed}",
             f"! expected checksum: {expected}",
             f"! host-execution flags: {', '.join(self.flags) or 'none'}"]
        if self.v >= 3:
            bf = sorted(f[5:] for f in self.features
                        if f.startswith("base:") and
                        not f.startswith("base:group:"))
            L.append(f"! base groups: {', '.join(self.base) or 'none'}")
            L += [f"! base features: {x}" for x in _chunks(bf, 90)] or \
                ["! base features: none"]
        L += [f"! kernel {k + 1}: {d}" for k, d in enumerate(self.kdesc)]
        if self.bsw:
            L += self.dc_module_lines()
        if self.ofuncs:
            L += self.oop_module_lines()
        if self.funcs:
            L += ["module fuzz_mod", "  implicit none", "contains"]
            for fn in self.funcs:
                args = ", ".join(fn.params)
                L += [f"  integer function {fn.name}({args})",
                      "    !$omp declare target",
                      f"    integer, intent(in) :: {args}"]
                L += wrap_stmt("    ", f"{fn.name} = {fn.body.f()}")
                L.append(f"  end function {fn.name}")
            L.append("end module fuzz_mod")
            self.feat("declare_target_function")
        L.append("program fuzz_prog")
        if self.api:
            L.append(f"  use omp_lib, only: {', '.join(sorted(self.api))}")
        if self.funcs:
            L.append("  use fuzz_mod, only: "
                     + ", ".join(f.name for f in self.funcs))
        if self.bsw and any(ln == "module fuzz_dmod" for ln in L):
            L.append("  use fuzz_dmod")
        if self.bsw and self.dfuncs:
            L.append("  use fuzz_dfun, only: "
                     + ", ".join(f.name for f in self.dfuncs))
        if self.ofuncs:
            L.append("  use fuzz_omod, only: "
                     + ", ".join(f.name for f in self.ofuncs))
        if self.bsw and self.mt_funcs:
            L += self.mt_use_lines()
        L += ["  implicit none"]
        if self.bsw and self.mt_funcs:
            L += self.mt_interface_lines()
        L += [f"  integer, parameter :: n = {self.n}, m = {self.m}"]
        L += self.dt_decl_lines()
        for a in self.arrays.values():
            if a.type != "integer" or a.var or (self.bsw and
                                                 a.name in self.dtv):
                continue
            tgt = self.decl_attrs(a.name) if self.bsw else ""
            if a.rank == 0:         # an allocatable scalar (fuzz-3)
                L.append(f"  integer{', allocatable' if a.alloc else ''}"
                         f" :: {a.name}")
            elif self.bsw and a.name in self.ptrs:
                L.append(f"  integer, pointer :: {a.name}"
                         f"({':' if a.rank == 1 else ':, :'})")
            elif a.alloc:
                L.append(f"  integer, allocatable{tgt} :: {a.name}"
                         f"({':' if a.rank == 1 else ':, :'})")
            else:
                L.append(f"  integer{tgt} :: {a.name}"
                         f"({'n' if a.rank == 1 else 'n, m'})")
        L += self.typed_decl_lines()
        if self.bsw:
            L += self.alloc_decl_lines()
        text = "\n".join(body)
        temps = sorted(set(re.findall(r"\b((?:t|acc)\d+)\b", text)))
        names = ["i", "j", "jj"] + list(self.scalars) + temps + (
            ["dev"] if self.uses_dev else [])
        L.append(f"  integer :: {', '.join(names)}")
        if self.logicals:
            L.append(f"  logical :: {', '.join(self.logicals)}")
        L.append("  integer(8) :: cs")
        for a in self.arrays.values():
            if a.alloc and not a.var and a.rank:
                L.append(f"  allocate({a.name}"
                         f"({'n' if a.rank == 1 else 'n, m'}))")
        if self.bsw:
            L += self.alloc_setup_lines()
        for name in ("ia", "ib"):
            L += ["  do i = 1, n", f"    {self.inits[name]}", "  end do"]
        L += ["  do j = 1, m", "    do i = 1, n", f"      {self.inits['ic']}",
              "    end do", "  end do"]
        typed_in = [a.name for a in self.arrays.values()
                    if a.name not in ("ia", "ib", "ic") and a.role == "input"
                    and a.name in self.inits]
        if typed_in:
            arr = [x for x in typed_in if self.arrays[x].rank]
            if arr:
                L.append("  do i = 1, n")
                for name in arr:
                    L += wrap_stmt("    ", self.inits[name])
                L.append("  end do")
            L += [f"  {self.inits[x]}" for x in typed_in
                  if not self.arrays[x].rank]
        L += [f"  {self.whole_text(a.name)} = "
              f"{self.typed_zero_text(a.type) if a.type != 'integer' else 0}"
              for a in self.arrays.values() if a.role != "input"]
        L += [f"  {k} = {v}" for k, v in self.scalars.items()]
        L += [f"  {k} = {self.typed_value_text(t, v)}"
              for k, (t, v) in self.tscalars.items()]
        L += [f"  {k} = {'.true.' if v else '.false.'}"
              for k, v in self.logicals.items()]
        if self.uses_dev:
            L.append("  dev = omp_get_default_device()")
        if self.bsw:
            L += self.dc_setup_lines()
            body = body + self.dc_final_lines()
        L += ["  ! fuzz: kernels"] + body + ["  ! fuzz: checksum", "  cs = 0"]
        for item in self.check_items:
            add = (f"cs = modulo(cs * 31_8 + int({{}}, 8), {CHECK_MOD}_8)")
            typ = self.arrays[item].type if item in self.arrays else \
                self.tscalars[item][0] if item in self.tscalars else \
                "integer"
            if typ != "integer":
                addt = f"cs = modulo(cs * 31_8 + {{}}, {CHECK_MOD}_8)"
                if item not in self.arrays:
                    L += ["  " + addt.format(x)
                          for x in checksum_terms(typ, item)]
                elif self.arrays[item].rank == 1:
                    L += ["  do i = 1, n"] + [
                        "    " + addt.format(x)
                        for x in checksum_terms(typ, self.check_ref(item, "i"))
                    ] + ["  end do"]
                else:
                    L += ["  do j = 1, m", "    do i = 1, n"] + [
                        "      " + addt.format(x)
                        for x in checksum_terms(
                            typ, self.check_ref(item, "i, j"))] + \
                        ["    end do", "  end do"]
            elif item not in self.arrays:
                L.append("  " + add.format(item))
            elif self.arrays[item].rank == 1:
                L += ["  do i = 1, n",
                      "    " + add.format(self.check_ref(item, "i")),
                      "  end do"]
            else:
                L += ["  do j = 1, m", "    do i = 1, n",
                      "      " + add.format(self.check_ref(item, "i, j")),
                      "    end do", "  end do"]
        host = f"max({', '.join(self.flags)}, 0)" if self.flags else "0"
        L += [f"  print '(a,i0,a,i0)', 'RESULT checksum=', cs, "
              f"' ran_on_host=', {host}"]
        if self.bsw and self.procs:
            L.append("contains")
            for proc in self.procs:
                L += proc.split("\n")
        L.append("end program fuzz_prog")
        if self.bsw and "multitu" in self.base:
            L = self.as_bundle(L)
        return "\n".join(L) + "\n"

    def as_bundle(self, L: list[str]) -> list[str]:
        """The single-file program L as a bundle of files (stage 5): the
        stage-5 units before the main program, a FILE_MARK line before
        every program unit."""
        from offload.engine.fuzz_base import FILE_MARK
        k = L.index("program fuzz_prog")
        units = []
        for name, lines in self.mt_unit_lines():
            units += [FILE_MARK + name] + lines
        out = []
        for i, ln in enumerate(L[:k]):
            m = re.match(r"(?:module|submodule \(\w+\)) (\w+)$", ln)
            if m and not ln.startswith("module procedure"):
                out.append(f"{FILE_MARK}{m.group(1)}.f90")
            out.append(ln)
        return out + units + [FILE_MARK + "fuzz_prog.f90"] + L[k:]


def map_items(text: str, types: tuple) -> list[str]:
    """Base names of the list items of map clauses in `text` whose map
    type is one of `types`."""
    out = []
    for m in re.finditer(r"\bmap\(", text):
        depth, k = 1, m.end()
        while depth and k < len(text):
            depth += {"(": 1, ")": -1}.get(text[k], 0)
            k += 1
        inner = text[m.end():k - 1]
        top = re.sub(r"\([^()]*\)", "", inner)
        if ":" not in top:
            continue
        mods, items = top.rsplit(":", 1)
        mtype = mods.split(",")[-1].strip()
        if mtype in types:
            out += [x.strip() for x in items.split(",") if x.strip()]
    return out


def generate(seed: int, gen_version: str = GEN_VERSION,
             base: tuple = ()) -> FuzzProgram:
    """The program of `seed` (deterministic for one generator version and
    set of base-language groups, offload.engine.fuzz_base; groups need
    fuzz-3)."""
    return _Gen(seed, gen_version, tuple(base)).build()


def _chunks(words: list[str], width: int) -> list[str]:
    out, cur = [], ""
    for w in words:
        if cur and len(cur) + 2 + len(w) > width:
            out.append(cur)
            cur = w
        else:
            cur = f"{cur}, {w}" if cur else w
    if cur:
        out.append(cur)
    return out


class _TrackedArr:
    def __init__(self, owner, name, data):
        self.owner, self.name, self.data = owner, name, data

    def __getitem__(self, idx):
        self.owner.log.setdefault((self.name, idx), set()).add(
            ("r", self.owner.point))
        return self.data[idx]

    def __setitem__(self, idx, v):
        self.owner.log.setdefault((self.name, idx), set()).add(
            ("w", self.owner.point))
        self.data[idx] = v


class _Tracked:
    """The model's arrays with every element access logged by iteration
    point (fuzz-3 race check of a parallel loop)."""

    def __init__(self, arrs: dict):
        self.arrs, self.point, self.log = arrs, None, {}

    def __getitem__(self, name):
        return _TrackedArr(self, name, self.arrs[name])

    def race(self) -> str | None:
        for (name, idx), acc in sorted(self.log.items(), key=str):
            writers = {p for k, p in acc if k == "w"}
            if not writers:
                continue
            others = {p for _, p in acc} - writers
            if len(writers) > 1 or others:
                return f"{name}{list(idx)} written by {sorted(writers)[:2]}"
        return None


# --- legality checks ----------------------------------------------------------------

GFORTRAN = shutil.which("gfortran") or "/usr/tce/bin/gfortran"


@dataclass(frozen=True)
class CheckResult:
    """`stage`: "ok", or the first checker that said no ("scope",
    "rules", "gfortran", "flang", "defined"), or "error" (a checker could not be run: neither
    a pass nor a reject)."""
    stage: str
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.stage == "ok"


def check_scope(source: str) -> str | None:
    """None, or why the program is outside the device-offload scope (Task
    24, offload.engine.offload_scope): an OpenMP construct outside a target
    region that is not offload machinery, or a target region sent to the
    host by a clause. Every generated program is device offload by
    construction; this keeps it so."""
    from offload.engine.grammar import GrammarError
    from offload.engine.offload_scope import host_constructs, host_execution
    from offload.engine.rules import ProgramError
    try:
        found = host_constructs(source, VERSION, "f90")
    except (GrammarError, ProgramError):
        return None  # check_rules reports the parse error
    sent = host_execution(source)
    if not found and not sent:
        return None
    return "; ".join(
        [f"{h.directive} at line {h.line} ({h.why})" for h in found] + sent)


def check_rules(source: str) -> str | None:
    """None, or why offload.engine.rules rejects the program at 5.2 (a parse
    error of the grammar or the scanner, or the violated rule ids)."""
    from offload.engine.grammar import GrammarError
    from offload.engine.rules import ProgramError, parse_program, violations
    try:
        found = violations(parse_program(source, VERSION), VERSION)
    except (GrammarError, ProgramError) as e:
        return f"{type(e).__name__}: {str(e).splitlines()[0]}"
    # The known generator defects are rule violations too
    found = list(found) + generator_defects(source)
    return ", ".join(found) or None


@lru_cache(maxsize=None)
def _stub_dir() -> str:
    """A per-process directory with omp_lib.mod built from
    gen.OMP_LIB_STUB (declarations only; base-language checking)."""
    from offload.engine.gen import OMP_LIB_STUB
    d = tempfile.mkdtemp(prefix="fuzz_stub_")
    (Path(d) / "omp_lib_stub.f90").write_text(OMP_LIB_STUB)
    subprocess.run([GFORTRAN, "-std=f2008", "-fsyntax-only",
                    "omp_lib_stub.f90"], cwd=d, check=True,
                   capture_output=True, timeout=120)
    return d


def check_gfortran(source: str) -> str | None:
    """None, or gfortran's first error for `-std=f2008 -fsyntax-only`
    without -fopenmp (OpenMP directives are comments)."""
    with tempfile.TemporaryDirectory(prefix="fuzz_gf_") as d:
        (Path(d) / "t.f90").write_text(source)
        res = subprocess.run([GFORTRAN, "-std=f2008", "-fsyntax-only",
                              f"-I{_stub_dir()}", "-J", d, "t.f90"],
                             cwd=d, capture_output=True, text=True,
                             timeout=120)
    if res.returncode == 0:
        return None
    lines = [ln for ln in res.stderr.splitlines() if "Error" in ln]
    return (lines[0] if lines else res.stderr.strip()[:300]) or \
        f"rc={res.returncode}"


class CheckerError(Exception):
    """A checker could not be run (not a verdict on the program)."""


def check_flang(source: str) -> str | None:
    """None, or AFAR flang's frontend diagnostic (parse + semantic checks
    at -fopenmp-version=52, the offload.engine.flang_oracle invocation)."""
    from offload.engine.flang_oracle import MODULE_FLAGS, FlangError, _dump
    try:
        _dump(source, VERSION, sema=True, extra_flags=MODULE_FLAGS)
    except FlangError as e:
        if e.stage in ("run", "map"):
            raise CheckerError(str(e))
        errs = [ln for ln in e.message.splitlines()
                if re.search(r":\d+:\d+: error:", ln)] or \
            [ln for ln in e.message.splitlines() if "error:" in ln]
        return f"{e.stage}: " + (errs[0] if errs else
                                 e.message.splitlines()[0])
    return None


# The definedness check (fuzz-3): the program without OpenMP (sequential
# elision's build, offload.engine.expected.run_elided) built by gfortran with
# run-time checks, twice with different fills of uninitialised storage
# (-finit-* for variables, MALLOC_PERTURB_ for allocated memory). Both
# builds must run to a RESULT line (no bounds, pointer, allocation,
# floating-point or signed-overflow trap) and print the same value: a
# read of undefined storage would differ. With `expected` given, the value
# must also be the model's (a self-check of the model).
DEFINED_RUNS = (
    (("-fcheck=all", "-ftrapv", "-ffpe-trap=invalid,zero,overflow",
      "-finit-integer=-31415", "-finit-real=snan", "-finit-logical=true",
      "-finit-character=35", "-finit-derived"), {"MALLOC_PERTURB_": "165"}),
    (("-fcheck=all", "-finit-integer=27182", "-finit-real=zero",
      "-finit-logical=false", "-finit-character=64", "-finit-derived"),
     {"MALLOC_PERTURB_": "90"}),
)


def check_defined(source: str, expected: int | None = None) -> str | None:
    """None, or why the definedness check fails (see DEFINED_RUNS)."""
    from offload.engine import expected as E
    vals = []
    for extra, env in DEFINED_RUNS:
        v, note = E.run_elided(source, "gfortran", extra, env)
        if v is None:
            if "build failed" in note:
                raise CheckerError(note)
            return f"definedness: {note}"
        vals.append(v)
    if len(set(vals)) > 1:
        return f"definedness: undefined value read ({' vs '.join(vals)})"
    if expected is not None and vals[0] != f"checksum={expected}":
        return (f"definedness: the sequential program prints {vals[0]}, "
                f"the model {expected}")
    return None


DEFAULT_LEAVES = ("parallel", "teams")


def nested_if_clauses(leaves, clauses) -> list[str]:
    """The if(<leaf>: x) clauses of a combined construct whose leaf comes
    after (is nested inside) a leaf that takes a default clause."""
    leaves = list(leaves)
    out = []
    for c in clauses:
        m = re.match(r"if\((\w+):", c)
        if not m or m.group(1) not in leaves:
            continue
        k = leaves.index(m.group(1))
        if any(x in DEFAULT_LEAVES for x in leaves[:k]):
            out.append(c)
    return out


def generator_defects(source: str) -> list[str]:
    """Known generator defects of a program, found statically:
    G1, a default(none) combined construct whose if(<leaf>: x) clause
    names a leaf nested inside the leaf with default, without x in a
    data-sharing clause (fuzz-3; fixed in fuzz-4)."""
    out = []
    for st in re.findall(r"^[ \t]*!\$omp (?!end\b)[^\n]*(?:\n[ \t]*"
                         r"!\$omp&[^\n]*)*", source, re.M | re.I):
        st = re.sub(r"&?[ \t]*\n[ \t]*!\$omp&", " ", st).strip()
        if "default(none)" not in st.lower():
            continue
        head = st[6:].lower()
        leaves = []
        for w in head.split():
            if "(" in w:
                break
            leaves.append(w)
        clauses = re.findall(r"\w+\([^()]*(?:\([^()]*\)[^()]*)*\)", head)
        for c in nested_if_clauses(leaves, clauses):
            x = re.match(r"if\(\w+:\s*(\w+)\)", c)
            if x and not re.search(rf"\b(shared|firstprivate|private)\("
                                   rf"[^)]*\b{x.group(1)}\b", head):
                out.append(f"G1: {x.group(1)} in {c} under default(none) of "
                           f"'{' '.join(leaves)}' is not in a data-sharing "
                           "clause (5.2 §17.2 p.340, §5.4.1 p.109)")
    return out


def is_fuzz3(source: str) -> bool:
    return re.search(r"^! generator: fuzz-(\d+)", source, re.M) is not None \
        and int(re.search(r"^! generator: fuzz-(\d+)", source,
                          re.M).group(1)) >= 3


def check(source: str, defined: bool | None = None,
          expected: int | None = None, scope: bool = True) -> CheckResult:
    """The scope check (unless `scope` is False: a host-execution rewrite
    that serves as a reference, offload.engine.expected), the three legality
    checks, cheapest first, then (fuzz-3: `defined` None means "the header
    says fuzz-3") the definedness check; the first "no" wins."""
    if defined is None:
        defined = is_fuzz3(source)
    stages = ([("scope", check_scope)] if scope else []) + [
        ("rules", check_rules), ("gfortran", check_gfortran),
        ("flang", check_flang)]
    if defined:
        stages.append(("defined",
                       lambda src: check_defined(src, expected)))
    try:
        for stage, fn in stages:
            why = fn(source)
            if why:
                return CheckResult(stage, why)
    except (CheckerError, subprocess.SubprocessError, OSError) as e:
        return CheckResult("error", str(e)[:500])
    return CheckResult("ok")
