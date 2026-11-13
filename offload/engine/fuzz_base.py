"""The base-language axis of the fuzz generator.

``offload.engine.fuzz`` varies OpenMP constructs over a trivial Fortran base of
integer arrays and scalars. This module adds base-language groups, each
switchable with ``--base-features`` and each with its own swarm of
sub-features, so a feature one compiler rejects does not hide the others.
Groups: ``types`` (element types and kinds, typed reductions), ``derived``
(derived types, component-level maps), ``alloc`` (allocatable and pointer
arrays, TARGET, internal subroutines), ``declare`` (declare target
variables, mappers, declare reduction and functions) and ``multitu`` (a
bundle of files marked by ``!@file <name>.f90`` lines, compiled with ``-c``
and linked by ``offload.engine.fuzz_exec``). Each program records its features
in ``FuzzProgram.features`` and a header line.
Real values are dyadic rationals bounded statically (``BOUND``, ``DEN``), so
reassociation and contraction stay exact; the model uses ``Fraction``."""
from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction as Q

# --- the groups ---------------------------------------------------------------------

BASE_GROUPS = ("types", "derived", "alloc", "declare", "multitu")
# fortran-oop (generator fuzz-5 only): type extension, type-bound
# procedures, dispatch, SELECT TYPE and CLASS(*) inside device functions
OOP_GROUPS = ("oop",)
ALL_GROUPS = BASE_GROUPS + OOP_GROUPS
# the first generator version of each group added after fuzz-3
GROUP_SINCE = {"oop": "fuzz-5"}
GROUP_SWARM = {
    "types": ("real4", "real8", "dp", "complex4", "complex8", "logical",
              "char", "int1", "int2", "int8", "typed_out", "typed_red",
              "typed_view", "atomic_typed"),
    # stage 2: a structure dr (type rec_t) with fixed-size components, a
    # nested structure component dr%nd (type nd_t), an array of
    # structures ds(n) (type el_t); maps of whole variables, of
    # components, or implicit; default component initialisation
    "derived": ("dt_nested", "dt_aos", "dt_scalar", "dt_typed", "dt_out",
                "dt_whole", "dt_comp", "dt_implicit", "dt_default_init",
                "dt_section"),
    # stage 3: allocatable, pointer and target variables and components,
    # strided array sections in target update and sections in depend,
    # kernels moved into internal procedures with assumed-shape,
    # explicit-shape, allocatable and pointer dummies, intent, value,
    # optional (present, and absent in a map clause), assumed length
    "alloc": ("al_ptr_out", "al_target", "al_alloc_scalar",
              "al_comp_alloc", "al_comp_ptr", "al_stride_update",
              "al_depend_section", "al_proc", "al_explicit_dummy",
              "al_alloc_dummy", "al_ptr_dummy", "al_value", "al_optional",
              "al_optional_absent", "al_intent_out", "al_assumed_len"),
    # stage 4: module fuzz_dmod with declare target variables (an array,
    # an output array, a structure of a module type), a declare mapper
    # (default or named) for a module type, a declare reduction on a
    # module type, and declare target functions in fuzz_dmod and
    # fuzz_dfun (which uses fuzz_dmod) called from kernels
    "declare": ("dc_modvar", "dc_modvar_out", "dc_static_init",
                "dc_modtype", "dc_mapper", "dc_named_mapper", "dc_udr",
                "dc_calls", "dc_chain", "dc_enter"),
    # stage 5: the program as a set of files (translation units), each
    # compiled with -c, then linked: every module in its own file, a
    # module chain fuzz_amod <- fuzz_bmod, a module with a separate module
    # procedure implemented in a submodule (its own file), an external
    # declare target function with an interface block in the main program
    "multitu": ("mt_chain", "mt_submodule", "mt_external", "mt_amod"),
    # fuzz-5 (fortran-oop): module fuzz_omod with a type ob_t (bindings f,
    # g) and its extension ox_t (overriding f, which calls the parent's f
    # through the parent component); declare target functions oo1..oo5
    # called from kernels, each building a local object and calling
    # through a CLASS(ob_t) dummy (dispatch), an inherited binding that
    # dispatches (inherit), SELECT TYPE (select) or a CLASS(*) dummy
    # (unlimited)
    "oop": ("oo_dispatch", "oo_override", "oo_inherit", "oo_select",
            "oo_unlimited"),
}
FILE_MARK = "!@file "        # a bundle: "!@file <name>.f90" starts a file

# What each group leaves out, and why (the model could not predict it, or
# the spec leaves it open); data/reports/fuzz-base-language.md prints this.
EXCLUSIONS = {
    "types": [
        "floating-point values that are not exactly representable, "
        "floating-point division (other than by a power of two inside mod), "
        "transcendental intrinsics, products of two variables: the result "
        "would depend on rounding, contraction or reduction order",
        "product reductions of reals; max/min reductions of complex and any "
        "character reduction (not allowed by 5.2 §5.5.5)",
        "atomic updates of complex and character items",
        "character scalars referenced without an explicit map (5.2 defines "
        "a Fortran scalar variable to exclude character type, so the "
        "implicit rule for one is unclear; "
        "data/findings/afar-cce19-character-defaultmap.f90)",
        "logical values compared with == (not Fortran; .eqv. is used)",
        "lastprivate and in_reduction of typed items (integers only)",
    ],
    "derived": [
        "a structure mapped whole with from or alloc (it would copy back or "
        "leave undefined the components the kernel does not write)",
        "an array of structures mapped by component (ds(:)%u is not "
        "contiguous storage, 5.2 §5.8.3)",
        "structure elements in data-sharing or depend clauses (not variable "
        "or locator list items in Fortran, 5.2 §3.2.1)",
        "reductions, lastprivate or firstprivate of structure components",
        "polymorphic (class), parameterized and extended derived types",
    ],
    "alloc": [
        "a pointer component referenced while its structure is mapped whole "
        "or implicitly (association status undefined through the default "
        "mapper, 5.2 §5.8.3)",
        "pointers or allocatables changing association or allocation inside "
        "a data region, and allocatable or pointer arrays referenced "
        "implicitly through defaultmap (a firstprivate pointer would not "
        "map its target)",
        "non-contiguous array sections in map clauses (5.2 §5.8.3); strided "
        "sections only in target update",
        "dummy procedures (procedure arguments) called in a target region: "
        "an indirect call needs declare target indirect (5.2 §7.8.3), whose "
        "support the model cannot predict",
        "internal procedures holding a kernel of a nowait sequence (the "
        "dummies end before the target task)",
        "intent(in) dummies of arrays a kernel maps other than to (the "
        "copy back would define them)",
    ],
    "declare": [
        "declare target variables in map clauses or in data-sharing clauses "
        "other than shared (infinite reference count, 5.2 §5.8.1)",
        "link clauses and device_type(nohost/host)",
        "mappers that leave out a component a kernel references",
        "declare reduction with a combiner or initializer subroutine; user "
        "reductions in atomic/critical updates or in task reductions",
        "declare variant, metadirective and indirect calls",
    ],
    "oop": [
        "polymorphic objects in map or data-sharing clauses (OpenMP 6.0 "
        "§7.9.6 p.288: unspecified), and mapped objects of the module types: "
        "every object is a local variable of a device function",
        "abstract types, deferred bindings, finalization and defined "
        "assignment (the campaign's hand-written families cover them)",
        "polymorphic allocatable locals (device-side allocation)",
    ],
    "multitu": [
        "a compile order other than the dependency order (modules before "
        "their users)",
        "kernels in procedures of other files (the kernels stay in the main "
        "program file; device functions cross files)",
        "common blocks, block data, and declare target on external variables",
    ],
}

# type key -> (Fortran type, kind)
TYPES = {"real4": ("real", 4), "real8": ("real", 8),
         "complex4": ("complex", 4), "complex8": ("complex", 8),
         "logical": ("logical", 4), "char": ("character", 4),
         "int1": ("integer", 1), "int2": ("integer", 2),
         "int8": ("integer", 8)}
REAL_BITS = {4: 24, 8: 53}
DEN = 64                 # every real value times DEN is an integer
CHAR_LEN = 4
SCALAR_LEN = 8
INT_MAX = {1: 127, 2: 32767, 8: 2 ** 62}
# typed reductions: legal identifiers whose result does not depend on the
# combination order for the values the generator draws (OpenMP 5.2 §5.5.5)
RED_OPS_TYPED = {
    "real": ("+", "max", "min"), "complex": ("+",),
    "logical": (".and.", ".or.", ".eqv.", ".neqv."),
    "integer1": ("max", "min", "iand", "ior", "ieor"),
    "integer2": ("max", "min", "iand", "ior", "ieor"),
    "integer8": ("+", "max", "min", "iand", "ior", "ieor"),
}


class Overflow(Exception):
    """A value of the model left the bounded range (the kernel is
    redrawn)."""


def real_limit(kind: int) -> Q:
    """Largest magnitude a real of `kind` may take: value * DEN must fit
    the significand with a margin."""
    return Q(2 ** (REAL_BITS[kind] - 1), DEN) if kind == 4 else Q(2 ** 40)


def fortran_mod_q(a: Q, p: Q) -> Q:
    """Fortran MOD for reals: a - int(a/p)*p (the sign of a)."""
    return a - int(a / p) * p


def nint_q(a: Q) -> int:
    """Fortran NINT: round half away from zero."""
    s = -1 if a < 0 else 1
    return s * int(abs(a) + Q(1, 2))


def rlit(v: Q, kind: int, dp: bool = False, paren: bool = True) -> str:
    """A real literal of `kind` with the exact value v (a dyadic); a
    negative one in parentheses unless `paren` is false (the parts of a
    complex literal constant are signed literals)."""
    whole = int(v)
    frac = abs(v - whole)
    digits = ""
    if frac:
        # a dyadic fraction has a finite decimal expansion
        x, digits = frac, ""
        while x:
            x *= 10
            digits += str(int(x))
            x -= int(x)
    sign = "-" if v < 0 else ""
    text = f"{abs(whole)}.{digits or '0'}"
    if kind == 8:
        text = text + ("d0" if dp else "_8")
    return f"({sign}{text})" if sign and paren else f"{sign}{text}"


# --- typed expressions (Fortran text, model value, static bound) -------------------

class TEx:
    """A typed expression: ``f()`` Fortran text, ``ev(env, arrs)`` the
    model value (Fraction, (Fraction, Fraction), bool, str or int),
    ``bound()`` a static bound of the magnitude of the value and of any
    partial result of a reassociation (reals, components of complex,
    integers)."""
    def f(self) -> str:
        raise NotImplementedError

    def ev(self, env, arrs):
        raise NotImplementedError

    def bound(self):
        return 0


@dataclass(frozen=True)
class TRef(TEx):
    arr: str
    idx: tuple           # integer Ex subscripts (rank 0: a scalar)
    bnd: object = 0      # static bound of the array's values

    def f(self):
        if not self.idx:
            return self.arr
        sub = ", ".join(x.f() for x in self.idx)
        if "(@)" in self.arr:
            return self.arr.replace("@", sub)
        return f"{self.arr}({sub})"

    def ev(self, env, arrs):
        if not self.idx:
            return arrs[self.arr][()]
        return arrs[self.arr][tuple(x.ev(env, arrs) for x in self.idx)]

    def bound(self):
        return self.bnd


@dataclass(frozen=True)
class RConst(TEx):
    v: Q
    kind: int
    dp: bool = False

    def f(self):
        return rlit(self.v, self.kind, self.dp)

    def ev(self, env, arrs):
        return self.v

    def bound(self):
        return abs(self.v)


@dataclass(frozen=True)
class RConv(TEx):
    """real(e, kind) of an integer expression whose |value| < bnd."""
    e: object
    kind: int
    bnd: int

    def f(self):
        return f"real({self.e.f()}, {self.kind})"

    def ev(self, env, arrs):
        return Q(self.e.ev(env, arrs))

    def bound(self):
        return Q(self.bnd)


@dataclass(frozen=True)
class RCast(TEx):
    """real(x, kind) of a real expression of another kind."""
    x: TEx
    kind: int

    def f(self):
        return f"real({self.x.f()}, {self.kind})"

    def ev(self, env, arrs):
        return self.x.ev(env, arrs)

    def bound(self):
        return self.x.bound()


@dataclass(frozen=True)
class RBin(TEx):
    op: str              # + - *(the right operand a constant)
    a: TEx
    b: TEx

    def f(self):
        return f"({self.a.f()} {self.op} {self.b.f()})"

    def ev(self, env, arrs):
        x, y = self.a.ev(env, arrs), self.b.ev(env, arrs)
        return x + y if self.op == "+" else x - y if self.op == "-" \
            else x * y

    def bound(self):
        if self.op == "*":
            return self.a.bound() * self.b.bound()
        return self.a.bound() + self.b.bound()


@dataclass(frozen=True)
class RFun(TEx):
    name: str            # max | min | abs | mod (b a power-of-two constant)
    a: TEx
    b: TEx | None = None

    def f(self):
        args = self.a.f() + (f", {self.b.f()}" if self.b is not None else "")
        return f"{self.name}({args})"

    def ev(self, env, arrs):
        x = self.a.ev(env, arrs)
        if self.name == "abs":
            return abs(x)
        y = self.b.ev(env, arrs)
        if self.name == "mod":
            return fortran_mod_q(x, y)
        return max(x, y) if self.name == "max" else min(x, y)

    def bound(self):
        if self.name == "mod":
            return min(self.a.bound(), self.b.bound())
        if self.name == "abs":
            return self.a.bound()
        return max(self.a.bound(), self.b.bound())


@dataclass(frozen=True)
class CMake(TEx):
    re: TEx
    im: TEx
    kind: int

    def f(self):
        return f"cmplx({self.re.f()}, {self.im.f()}, {self.kind})"

    def ev(self, env, arrs):
        return (self.re.ev(env, arrs), self.im.ev(env, arrs))

    def bound(self):
        return max(self.re.bound(), self.im.bound())


@dataclass(frozen=True)
class CConst(TEx):
    re: Q
    im: Q
    kind: int

    def f(self):
        return (f"({rlit(self.re, self.kind, paren=False)}, "
                f"{rlit(self.im, self.kind, paren=False)})")

    def ev(self, env, arrs):
        return (self.re, self.im)

    def bound(self):
        return max(abs(self.re), abs(self.im))


@dataclass(frozen=True)
class CBin(TEx):
    op: str              # + - * (the right operand a CConst)
    a: TEx
    b: TEx

    def f(self):
        return f"({self.a.f()} {self.op} {self.b.f()})"

    def ev(self, env, arrs):
        (p, q), (r, s) = self.a.ev(env, arrs), self.b.ev(env, arrs)
        if self.op == "+":
            return (p + r, q + s)
        if self.op == "-":
            return (p - r, q - s)
        return (p * r - q * s, p * s + q * r)

    def bound(self):
        if self.op == "*":
            return self.a.bound() * 2 * self.b.bound()
        return self.a.bound() + self.b.bound()


@dataclass(frozen=True)
class CFun(TEx):
    name: str            # conjg
    a: TEx

    def f(self):
        return f"{self.name}({self.a.f()})"

    def ev(self, env, arrs):
        p, q = self.a.ev(env, arrs)
        return (p, -q)

    def bound(self):
        return self.a.bound()


@dataclass(frozen=True)
class CPart(TEx):
    """real(z) or aimag(z): a real of the complex kind."""
    name: str
    z: TEx

    def f(self):
        return f"{self.name}({self.z.f()})"

    def ev(self, env, arrs):
        v = self.z.ev(env, arrs)
        return v[0] if self.name == "real" else v[1]

    def bound(self):
        return self.z.bound()


@dataclass(frozen=True)
class LCmp(TEx):
    op: str
    a: object            # integer Ex
    b: object

    def f(self):
        return f"({self.a.f()} {self.op} {self.b.f()})"

    def ev(self, env, arrs):
        x, y = self.a.ev(env, arrs), self.b.ev(env, arrs)
        return {"<": x < y, "<=": x <= y, ">": x > y, ">=": x >= y,
                "==": x == y, "/=": x != y}[self.op]


@dataclass(frozen=True)
class LBin(TEx):
    op: str              # .and. .or. .eqv. .neqv.
    a: TEx
    b: TEx

    def f(self):
        return f"({self.a.f()} {self.op} {self.b.f()})"

    def ev(self, env, arrs):
        return lapply(self.op, self.a.ev(env, arrs), self.b.ev(env, arrs))


@dataclass(frozen=True)
class LNot(TEx):
    a: TEx

    def f(self):
        return f"(.not. {self.a.f()})"

    def ev(self, env, arrs):
        return not self.a.ev(env, arrs)


def lapply(op: str, x: bool, y: bool) -> bool:
    return {".and.": x and y, ".or.": x or y, ".eqv.": x == y,
            ".neqv.": x != y}[op]


@dataclass(frozen=True)
class ChMake(TEx):
    """achar(65 + iand(e, 15)) // src(2:4), or src(3:4) // achar(97 +
    iand(e, 15)) // achar(48 + iand(e2, 7)): a character(len=4) value."""
    form: int
    e: object
    src: TEx
    e2: object = None

    def f(self):
        if self.form == 0:
            return (f"achar(65 + iand({self.e.f()}, 15)) // "
                    f"{self.src.f()}(2:4)")
        return (f"{self.src.f()}(3:4) // achar(97 + iand({self.e.f()}, 15))"
                f" // achar(48 + iand({self.e2.f()}, 7))")

    def ev(self, env, arrs):
        s = self.src.ev(env, arrs)
        if self.form == 0:
            return chr(65 + (self.e.ev(env, arrs) & 15)) + s[1:4]
        return s[2:4] + chr(97 + (self.e.ev(env, arrs) & 15)) + \
            chr(48 + (self.e2.ev(env, arrs) & 7))


@dataclass(frozen=True)
class KExpr(TEx):
    """An integer expression of kind 1, 2 or 8 (Fortran text given; the
    model function computes it)."""
    text: str
    fn: object
    bnd: int

    def f(self):
        return self.text

    def ev(self, env, arrs):
        return self.fn(env, arrs)

    def bound(self):
        return self.bnd


# integer views of typed values (integer Ex: f/ev only)

@dataclass(frozen=True)
class IView:
    """An integer of default kind computed from a typed value: `how` is
    int | nint | merge | ichar | intk (int(x) of an integer kind) |
    mod8 (int(mod(x, 1000003_8)))."""
    how: str
    x: TEx
    pos: int = 1          # ichar: the character position

    def f(self):
        x = self.x.f()
        return {"int": f"int({x})", "nint": f"nint({x})",
                "merge": f"merge(1, 0, {x})",
                "ichar": f"ichar({x}({self.pos}:{self.pos}))",
                "intk": f"int({x})",
                "mod8": f"int(mod({x}, 1000003_8))"}[self.how]

    def ev(self, env, arrs):
        v = self.x.ev(env, arrs)
        if self.how == "int":
            return int(v)
        if self.how == "nint":
            return nint_q(v)
        if self.how == "merge":
            return 1 if v else 0
        if self.how == "ichar":
            return ord(v[self.pos - 1])
        if self.how == "intk":
            return v
        r = abs(v) % 1000003
        return r if v >= 0 else -r


# --- model values ---------------------------------------------------------------------

def zero(typ: str):
    if typ == "pair":
        return (0, 0)
    base = TYPES[typ][0] if typ in TYPES else "integer"
    if base == "real":
        return Q(0)
    if base == "complex":
        return (Q(0), Q(0))
    if base == "logical":
        return False
    if base == "character":
        return " " * CHAR_LEN
    return 0


def contributions(typ: str, v) -> list[int]:
    """The checksum contributions of one value (Fortran: ``checksum_terms``)."""
    if typ == "pair":
        return [v[0], v[1]]
    base = TYPES[typ][0] if typ in TYPES else "integer"
    if base == "real":
        x = v * DEN
        if x.denominator != 1:
            raise Overflow(f"real value {v} is not a multiple of 1/{DEN}")
        return [int(x)]
    if base == "complex":
        return contributions("real8", v[0]) + contributions("real8", v[1])
    if base == "logical":
        return [1 if v else 0]
    if base == "character":
        return [ord(c) for c in v]
    return [v]


def checksum_terms(typ: str, ref: str) -> list[str]:
    """Fortran integer(8) expressions of the contributions of `ref`."""
    if typ == "pair":
        return [f"int({ref}%x, 8)", f"int({ref}%y, 8)"]
    base, kind = TYPES[typ] if typ in TYPES else ("integer", 4)
    if base == "real":
        return [f"int({ref} * {DEN}, 8)"]
    if base == "complex":
        return [f"int(real({ref}) * {DEN}, 8)",
                f"int(aimag({ref}) * {DEN}, 8)"]
    if base == "logical":
        return [f"merge(1_8, 0_8, {ref})"]
    if base == "character":
        return [f"int(ichar({ref}({k}:{k})), 8)"
                for k in range(1, CHAR_LEN + 1)]
    return [f"int({ref}, 8)"]


def red_apply_typed(base: str, op: str, acc, v):
    if base == "complex":
        return (acc[0] + v[0], acc[1] + v[1])
    if base == "logical":
        return lapply(op, acc, v)
    if op == "+":
        return acc + v
    if op == "max":
        return max(acc, v)
    if op == "min":
        return min(acc, v)
    if op == "iand":
        return acc & v
    if op == "ior":
        return acc | v
    return acc ^ v


# --- the generator side (mixed into offload.engine.fuzz._Gen) ---------------------------------

class BaseMixin:
    """Base-language decisions of one program. Uses ``self.rb`` (a random
    stream of its own, so a fuzz-3 program without base groups is the
    fuzz-2 program of its seed) and the swarm ``self.bsw``."""

    def base_init(self, base: tuple) -> None:
        import random
        unknown = [g for g in base if g not in ALL_GROUPS]
        if unknown:
            raise ValueError(f"unknown base-feature group(s) {unknown}")
        if base and self.v < 3:
            raise ValueError("base-feature groups need generator fuzz-3")
        # by version order: fuzz-5's self.v is 6, since
        # fuzz-4s50 takes the index after fuzz-4; every check is ">="
        from offload.engine.fuzz import GEN_VERSIONS
        for g in base:
            if g in GROUP_SINCE and GEN_VERSIONS.index(self.gen_version) < \
                    GEN_VERSIONS.index(GROUP_SINCE[g]):
                raise ValueError(f"base-feature group {g} needs generator "
                                 f"{GROUP_SINCE[g]}")
        self.base = tuple(g for g in ALL_GROUPS if g in base)
        self.rb = random.Random(f"fuzz-3-base:{self.seed}")
        self.bsw = {}
        for g in self.base:
            for f in GROUP_SWARM[g]:
                self.bsw[f] = self.rb.random() < 0.6
            self.features.add(f"base:group:{g}")
        self.tscalars: dict[str, str] = {}    # typed scalar -> type key
        self.tbound: dict[str, object] = {}   # typed input -> value bound
        self.spell: dict[str, str] = {}       # array/scalar -> decl type
        self.dvars: dict[str, str] = {}       # structure -> type (stage 2)
        self.dt_defaults: dict[str, str] = {}
        self.ptrs: dict[str, str] = {}        # pointer -> target | alloc
        self.tgt_attr: set = set()            # arrays with TARGET
        self.procs: list[str] = []            # internal procedures
        self.full_out: dict[str, bool] = {}   # output -> written whole
        self.dtv: set = set()                 # declare target (stage 4)
        self.dfuncs: list = []                # device functions (stage 4)
        self.mfuncs: list = []                # functions of fuzz_dmod
        self.xfuncs: list = []                # functions of stage 5
        self.mt_funcs: dict = {}
        self.ofuncs: list = []                # oop device functions (fuzz-5)
        self.oop_consts: dict = {}

    def bon(self, name: str) -> bool:
        return self.bsw.get(name, False)

    # -- names of arrays and components --

    def var_of(self, name: str) -> str:
        a = self.arrays.get(name)
        return a.var if a is not None and a.var else name

    @staticmethod
    def ref_text(name: str, idx: str, rank: int = 1) -> str:
        """The reference of an element (`idx`: the subscript text)."""
        if "(@)" in name:
            return name.replace("@", idx)
        return f"{name}({idx})" if rank else name

    @staticmethod
    def whole_text(name: str) -> str:
        return name.replace("(@)", "")

    @staticmethod
    def ref_re(name: str) -> str:
        """A regular expression matching a reference of `name`."""
        if "(@)" in name:
            head, tail = name.split("(@)", 1)
            return rf"\b{re.escape(head)}\([^%\n]*?\){re.escape(tail)}\b"
        return rf"\b{re.escape(name)}\b"

    def btypes(self) -> list[str]:
        """The type keys enabled in this program."""
        out = []
        for t in TYPES:
            if self.bon(t) or (t == "real8" and self.bon("dp")):
                out.append(t)
        return out

    # -- inputs --

    def setup_types(self) -> None:
        """Typed input arrays (rank 1, extent n) and the character scalar,
        initialised on the host from i (the model computes the same)."""
        rb = self.rb
        for t in self.btypes():
            name = {"real4": "xr4", "real8": "xr8", "complex4": "xz4",
                    "complex8": "xz8", "logical": "xl", "char": "xc",
                    "int1": "xk1", "int2": "xk2", "int8": "xk8"}[t]
            a = self.new_array(name, 1, "input", typ=t)
            dp = t == "real8" and self.bon("dp") and (
                not self.bon("real8") or rb.random() < 0.5)
            self.spell[name] = self.decl_spelling(t, dp)
            c1, c2 = rb.randint(3, 61), rb.randint(0, 50)
            p = rb.choice((97, 101, 211, 1009))
            off = rb.randint(0, p // 2)
            vals = {}
            for (i,) in self.points(a):
                lin = (i * c1 + c2) % p - off
                if t in ("real4", "real8"):
                    vals[(i,)] = Q(lin, 2)
                elif t in ("complex4", "complex8"):
                    vals[(i,)] = (Q(lin), Q((i * c2) % 17 - 8))
                elif t == "logical":
                    vals[(i,)] = (i * c1 + c2) % 3 == 0
                elif t == "char":
                    vals[(i,)] = (chr(65 + (i * c1) % 26) +
                                  chr(97 + (i + c2) % 26) +
                                  chr(48 + i % 10) + "#")
                elif t == "int1":
                    vals[(i,)] = (i * c1 + c2) % 127
                elif t == "int2":
                    vals[(i,)] = (i * c1 + c2) % 16001 - 8000
                else:
                    vals[(i,)] = i * 1000000007 + c2
            self.arrs[name] = vals
            lin = f"mod(i * {c1} + {c2}, {p}) - {off}"
            k = TYPES[t][1]
            half = rlit(Q(1, 2), k, dp)
            self.inits[name] = {
                "real4": f"{name}(i) = real({lin}, 4) * {half}",
                "real8": f"{name}(i) = real({lin}, 8) * {half}",
                "complex4": f"{name}(i) = cmplx({lin}, mod(i * {c2}, 17) "
                            "- 8, 4)",
                "complex8": f"{name}(i) = cmplx({lin}, mod(i * {c2}, 17) "
                            "- 8, 8)",
                "logical": f"{name}(i) = mod(i * {c1} + {c2}, 3) == 0",
                "char": f"{name}(i) = achar(65 + mod(i * {c1}, 26)) // "
                        f"achar(97 + mod(i + {c2}, 26)) // "
                        "achar(48 + mod(i, 10)) // '#'",
                "int1": f"{name}(i) = int(mod(i * {c1} + {c2}, 127), 1)",
                "int2": f"{name}(i) = int(mod(i * {c1} + {c2}, 16001) - "
                        "8000, 2)",
                "int8": f"{name}(i) = int(i, 8) * 1000000007_8 + "
                        f"int({c2}, 8)"}[t]
            self.tbound[name] = self.value_bound(t, vals.values())
            self.features.add(f"base:type:{t}")
            if dp:
                self.features.add("base:spell:double_precision")
        if self.bon("char"):
            # a character scalar: always mapped explicitly (see the module
            # docstring)
            s = "".join(chr(rb.choice((65, 97)) + rb.randint(0, 25))
                        for _ in range(SCALAR_LEN))
            a = self.new_array("xs", 0, "input", typ="char")
            self.arrs["xs"] = {(): s}
            self.spell["xs"] = f"character(len={SCALAR_LEN})"
            self.inits["xs"] = f"xs = '{s}'"
            self.features.add("base:type:char_scalar")

    def decl_spelling(self, t: str, dp: bool = False) -> str:
        if t == "pair":
            return "type(pair_t)"
        base, kind = TYPES[t]
        if dp:
            return "double precision"
        if base == "character":
            return f"character(len={CHAR_LEN})"
        if base == "logical":
            return "logical"
        form = self.rb.choice(("p", "kind", "default"))
        if form == "default" and kind == 4 and base in ("real", "complex"):
            return base
        if form == "kind":
            return f"{base}(kind={kind})"
        return f"{base}({kind})"

    @staticmethod
    def value_bound(t: str, vals) -> object:
        base = TYPES[t][0]
        vals = list(vals)
        if base == "real":
            return max(abs(v) for v in vals)
        if base == "complex":
            return max(max(abs(v[0]), abs(v[1])) for v in vals)
        if base == "integer":
            return max(abs(v) for v in vals)
        return 0

    # -- which typed data a kernel may read --

    def typed_inputs(self, typ: str | None = None) -> list[str]:
        return [a.name for a in self.arrays.values()
                if a.type != "integer" and a.role == "input"
                and (typ is None or a.type == typ)]

    def typed_outputs(self, but: str) -> list[str]:
        return [a.name for a in self.arrays.values()
                if a.type != "integer" and a.role == "output"
                and a.name != but]

    def tref(self, name: str, ivars: dict) -> TRef:
        a = self.arrays[name]
        idx = tuple(self.index(d, ivars) for d in ("n", "m")[:a.rank])
        return TRef(name, idx, self.tbound.get(name, 0))

    def typed_leaves(self, ivars: dict, but: str) -> list:
        """Integer leaves that read typed data (views), for the integer
        expressions of any kernel."""
        if not (self.bon("typed_view") or self.bon("dt_typed")):
            return []
        rb = self.rb
        out = []
        names = self.typed_inputs() + self.typed_outputs(but)
        for name in names:
            if rb.random() < 0.5:
                continue
            a = self.arrays[name]
            ref = self.tref(name, ivars)
            out.append(self.view(a.type, ref, a.role == "output"))
            self.features.add(f"base:view:{a.type}")
        return out

    def view(self, t: str, ref: TRef, output: bool):
        """A bounded integer view of a typed reference."""
        base, kind = TYPES[t]
        rb = self.rb
        if base == "real":
            if output or ref.bound() >= 2 ** 12:
                return IView("int", RFun("mod", ref, RConst(Q(1024), kind)))
            return IView(rb.choice(("int", "nint")), ref)
        if base == "complex":
            part = CPart(rb.choice(("real", "aimag")), ref)
            if output:
                return IView("int", RFun("mod", part, RConst(Q(1024), kind)))
            return IView("int", part)
        if base == "logical":
            return IView("merge", ref)
        if base == "character":
            n = SCALAR_LEN if not ref.idx else CHAR_LEN
            return IView("ichar", ref, rb.randint(1, n))
        if kind == 8:
            return IView("mod8", ref)
        return IView("intk", ref)

    # -- typed outputs --

    def out_type(self, nlev: int) -> str:
        """The element type of a kernel's output array."""
        if not self.bon("typed_out") or self.rb.random() < 0.35:
            return "integer"
        opts = [t for t in self.btypes() if not (t == "char" and nlev > 1)]
        return self.rb.choice(opts) if opts else "integer"

    def typed_store(self, t: str, lv: list, ivars: dict, but: str):
        """A typed expression for an element of an output of type `t`,
        built from the integer leaves `lv` (bounded) and typed data."""
        from offload.engine.fuzz import Const, Intr
        rb = self.rb
        base, kind = TYPES[t]
        self.features.add(f"base:out:{t}")

        def ie(p=(97, 1009)):
            q = rb.choice(p)
            return Intr("mod", (self.expr(1, lv), Const(q))), q

        if base == "real":
            return self.rexpr(kind, 2, lv, ivars, but)
        if base == "complex":
            if rb.random() < 0.6:
                z = CMake(self.rexpr(kind, 1, lv, ivars, but),
                          self.rexpr(kind, 1, lv, ivars, but), kind)
            else:
                src = self.typed_inputs(t)
                z = self.tref(src[0], ivars) if src else CMake(
                    self.rexpr(kind, 1, lv, ivars, but), RConst(Q(1), kind),
                    kind)
            k = rb.random()
            if k < 0.3:
                c = rb.choice(((0, 1), (1, 1), (2, 0), (Q(1, 2), 0)))
                z = CBin("*", z, CConst(Q(c[0]), Q(c[1]), kind))
            elif k < 0.5:
                z = CFun("conjg", z)
            elif k < 0.7:
                z = CBin(rb.choice("+-"), z, CMake(
                    self.rexpr(kind, 1, lv, ivars, but),
                    self.rexpr(kind, 0, lv, ivars, but), kind))
            self.check_real(z, kind)
            return z
        if base == "logical":
            return self.lexpr(2, lv, ivars)
        if base == "character":
            src = self.typed_inputs("char")
            sref = self.tref(src[0], ivars)
            a, _ = ie()
            if rb.random() < 0.5:
                return ChMake(0, a, sref)
            b, _ = ie()
            return ChMake(1, a, sref, b)
        return self.kexpr(kind, lv, ivars)

    def check_real(self, x: TEx, kind: int) -> None:
        if x.bound() >= real_limit(kind):
            raise Overflow(f"real bound {x.bound()} for kind {kind}")

    def rexpr(self, kind: int, depth: int, lv: list, ivars: dict,
              but: str) -> TEx:
        """A real expression of `kind` (bounded, see the module
        docstring)."""
        from offload.engine.fuzz import Const, Intr
        rb = self.rb

        def leaf():
            k = rb.random()
            same = self.typed_inputs(f"real{kind}")
            other = self.typed_inputs(f"real{12 - kind}")
            outs = [n for n in self.typed_outputs(but)
                    if self.arrays[n].type == f"real{kind}"]
            if k < 0.3 and same:
                return self.tref(rb.choice(same), ivars)
            if k < 0.4 and other:
                self.features.add("base:real_kind_conversion")
                return RCast(self.tref(rb.choice(other), ivars), kind)
            if k < 0.5 and outs:
                return RFun("mod", self.tref(rb.choice(outs), ivars),
                            RConst(Q(1024), kind))
            if k < 0.6:
                return RConst(Q(rb.choice((1, 2, 3, 5, -7, 1)), 2) * 2
                              if rb.random() < 0.5 else
                              Q(rb.choice((1, 3, -1)), 2), kind,
                              self.dp_spell(kind))
            q = rb.choice((97, 1009))
            return RConv(Intr("mod", (self.expr(1, lv), Const(q))), kind, q)

        def sub(d):
            if d <= 0 or rb.random() < 0.3:
                return leaf()
            k = rb.choice(("add", "sub", "mulc", "max", "abs", "mod"))
            if k in ("add", "sub"):
                return RBin("+" if k == "add" else "-", sub(d - 1),
                            sub(d - 1))
            if k == "mulc":
                c = Q(rb.choice((2, 3, -1, 1, -3)), rb.choice((1, 2)))
                return RBin("*", sub(d - 1), RConst(c, kind,
                                                    self.dp_spell(kind)))
            if k == "max":
                return RFun(rb.choice(("max", "min")), sub(d - 1), sub(d - 1))
            if k == "abs":
                return RFun("abs", sub(d - 1))
            return RFun("mod", sub(d - 1), RConst(Q(256), kind))
        x = sub(depth)
        self.check_real(x, kind)
        return x

    def dp_spell(self, kind: int) -> bool:
        return kind == 8 and self.bon("dp")

    def lexpr(self, depth: int, lv: list, ivars: dict) -> TEx:
        rb = self.rb

        def leaf():
            src = self.typed_inputs("logical")
            if src and rb.random() < 0.4:
                return self.tref(rb.choice(src), ivars)
            return LCmp(rb.choice(("<", "<=", ">", ">=", "==", "/=")),
                        self.expr(1, lv), self.expr(1, lv))

        def sub(d):
            if d <= 0 or rb.random() < 0.35:
                return leaf()
            if rb.random() < 0.2:
                return LNot(sub(d - 1))
            return LBin(rb.choice((".and.", ".or.", ".eqv.", ".neqv.")),
                        sub(d - 1), sub(d - 1))
        return sub(depth)

    def kexpr(self, kind: int, lv: list, ivars: dict) -> TEx:
        """An integer expression of kind 1, 2 or 8."""
        from offload.engine.fuzz import Const, Intr
        rb = self.rb
        e = self.expr(1, lv)
        src = self.typed_inputs(f"int{kind}")
        ref = self.tref(rb.choice(src), ivars) if src and \
            rb.random() < 0.6 else None
        if kind == 1:
            a = f"int(iand({e.f()}, 127), 1)"

            def av(env, arrs, e=e):
                return e.ev(env, arrs) & 127
            if ref is None:
                return KExpr(a, av, 127)
            op = rb.choice(("ieor", "max", "min", "iand", "ior"))
            fn = {"ieor": lambda x, y: x ^ y, "max": max, "min": min,
                  "iand": lambda x, y: x & y, "ior": lambda x, y: x | y}[op]
            return KExpr(f"{op}({ref.f()}, {a})",
                         lambda env, arrs, ref=ref, av=av, fn=fn:
                         fn(ref.ev(env, arrs), av(env, arrs)), 127)
        if kind == 2:
            a = f"int(mod({e.f()}, 16001), 2)"

            def av(env, arrs, e=e):
                v = e.ev(env, arrs)
                r = abs(v) % 16001
                return r if v >= 0 else -r
            if ref is None:
                return KExpr(a, av, 16000)
            if rb.random() < 0.5 and ref.bound() <= 16000:
                return KExpr(f"({ref.f()} + {a})",
                             lambda env, arrs, ref=ref, av=av:
                             ref.ev(env, arrs) + av(env, arrs), 32000)
            op = rb.choice(("max", "min", "ieor"))
            fn = {"ieor": lambda x, y: x ^ y, "max": max, "min": min}[op]
            return KExpr(f"{op}({ref.f()}, {a})",
                         lambda env, arrs, ref=ref, av=av, fn=fn:
                         fn(ref.ev(env, arrs), av(env, arrs)), 32767)
        e2 = self.expr(1, lv)
        text = f"(int({e.f()}, 8) * int({e2.f()}, 8))"

        def pv(env, arrs, e=e, e2=e2):
            return e.ev(env, arrs) * e2.ev(env, arrs)
        if ref is None:
            return KExpr(text, pv, 2 ** 60)
        return KExpr(f"({ref.f()} + {text})",
                     lambda env, arrs, ref=ref, pv=pv:
                     ref.ev(env, arrs) + pv(env, arrs), 2 ** 61)

    # -- typed reductions --

    def typed_red_type(self) -> str | None:
        if not self.bon("typed_red") or self.rb.random() < 0.4:
            return None
        opts = [t for t in self.btypes() if t != "char"]
        return self.rb.choice(opts) if opts else None

    @staticmethod
    def red_key(t: str) -> str:
        base, kind = TYPES[t]
        return f"integer{kind}" if base == "integer" else base

    def typed_red_init(self, t: str, op: str):
        rb = self.rb
        base, kind = TYPES[t]
        if base == "real":
            return {"+": Q(rb.randint(-50, 50), 2), "max": Q(-1000),
                    "min": Q(1000)}[op]
        if base == "complex":
            return (Q(rb.randint(-9, 9)), Q(rb.randint(-9, 9)))
        if base == "logical":
            return {".and.": True, ".or.": False, ".eqv.": True,
                    ".neqv.": False}[op] if rb.random() < 0.7 else \
                rb.random() < 0.5
        if op in ("max",):
            return -INT_MAX[kind] // 2
        if op == "min":
            return INT_MAX[kind] // 2
        if op == "iand":
            return {1: 127, 2: 32767, 8: 2 ** 40 - 1}[kind]
        if op in ("ior", "ieor"):
            return rb.randint(0, 15)
        return rb.randint(-1000, 1000)

    def typed_red_term(self, t: str, op: str, lv: list, ivars: dict,
                       iters: int, init) -> TEx:
        """The contribution of one iteration; for a sum the static bound
        times the number of iterations must stay exact."""
        from offload.engine.fuzz import Const, Intr
        rb = self.rb
        base, kind = TYPES[t]
        if base == "real":
            q = 97 if op == "+" else 1009
            term = RConv(Intr("mod", (self.expr(1, lv), Const(q))), kind, q)
            if rb.random() < 0.4:
                term = RBin("*", term, RConst(Q(1, 2), kind,
                                              self.dp_spell(kind)))
            if op == "+" and (term.bound() * iters + abs(init)
                              >= real_limit(kind)):
                raise Overflow("real sum reduction bound")
            return term
        if base == "complex":
            return CMake(RConv(Intr("mod", (self.expr(1, lv), Const(97))),
                               kind, 97),
                         RConv(Intr("mod", (self.expr(1, lv), Const(13))),
                               kind, 13), kind)
        if base == "logical":
            return LCmp(rb.choice(("<", ">", "==", "/=")), self.expr(1, lv),
                        self.expr(1, lv))
        if kind == 8:
            e = self.expr(1, lv)
            if op == "+":
                return KExpr(f"(int(mod({e.f()}, 1009), 8) * 1000003_8)",
                             lambda env, arrs, e=e: (lambda v: (
                                 abs(v) % 1009 if v >= 0 else
                                 -(abs(v) % 1009)))(e.ev(env, arrs))
                             * 1000003, 1009 * 1000003)
            return KExpr(f"int({e.f()}, 8)", lambda env, arrs, e=e:
                         e.ev(env, arrs), 2 ** 30)
        return self.kexpr(kind, lv, ivars)

    def typed_red_update(self, var: str, t: str, op: str, term: TEx) -> str:
        base = TYPES[t][0]
        if base == "logical":
            return f"{var} = {var} {op} {term.f()}"
        if op == "+":
            return f"{var} = {var} + {term.f()}"
        return f"{var} = {op}({var}, {term.f()})"

    # -- declarations, initial values and the checksum --

    def typed_decl_lines(self) -> list[str]:
        out = []
        for a in self.arrays.values():
            if a.type == "integer" or a.var:
                continue
            spell = self.spell.get(a.name) or self.decl_spelling(a.type)
            self.spell[a.name] = spell
            if a.rank == 0:
                out.append(f"  {spell} :: {a.name}")
            elif a.name in self.ptrs:
                out.append(f"  {spell}, pointer :: {a.name}"
                           f"({':' if a.rank == 1 else ':, :'})")
            elif a.alloc:
                out.append(f"  {spell}, allocatable :: {a.name}"
                           f"({':' if a.rank == 1 else ':, :'})")
            else:
                out.append(f"  {spell} :: {a.name}"
                           f"({'n' if a.rank == 1 else 'n, m'})")
        for name, (t, _) in self.tscalars.items():
            spell = self.spell.get(name) or self.decl_spelling(
                t, t == "real8" and self.bon("dp") and
                self.rb.random() < 0.5)
            self.spell[name] = spell
            out.append(f"  {spell} :: {name}")
        return out

    def typed_value_text(self, t: str, v) -> str:
        if t == "pair":
            return f"pair_t({v[0]}, {v[1]})"
        base, kind = TYPES[t]
        if base == "real":
            return rlit(v, kind, self.dp_spell(kind))
        if base == "complex":
            return (f"({rlit(v[0], kind, paren=False)}, "
                    f"{rlit(v[1], kind, paren=False)})")
        if base == "logical":
            return ".true." if v else ".false."
        if base == "character":
            return f"'{v}'"
        return f"{v}_{kind}" if v >= 0 else f"({v}_{kind})"

    def typed_zero_text(self, t: str) -> str:
        base = TYPES[t][0]
        return {"logical": ".false.", "character": "' '"}.get(base, "0")

    # -- derived types (stage 2) --

    DT_TYPES = {"dr": "rec_t", "dr%nd": "nd_t", "ds": "el_t"}

    def setup_derived(self) -> None:
        """The structure dr, its nested component dr%nd and the array of
        structures ds, with input components initialised on the host."""
        rb = self.rb
        self.dvars = {"dr": "rec_t"}
        comps = [("dr%a", "integer", 1)]
        if self.bon("dt_typed"):
            comps.append(("dr%b", "real8", 1))
        if self.bon("dt_scalar"):
            comps.append(("dr%s", "integer", 0))
        if self.bon("dt_nested"):
            comps.append(("dr%nd%k", "integer", 1))
            if self.bon("dt_typed"):
                comps.append(("dr%nd%w", "real8", 1))
        if self.bon("dt_aos"):
            self.dvars["ds"] = "el_t"
            comps.append(("ds(@)%u", "integer", 1))
            if self.bon("dt_typed"):
                comps.append(("ds(@)%v", "real8", 1))
        for name, typ, rank in comps:
            var = name.split("%")[0].split("(")[0]
            a = self.new_array(name, rank, "input", typ=typ, var=var)
            c1, c2 = rb.randint(3, 61), rb.randint(0, 50)
            p = rb.choice((97, 101, 211, 1009))
            off = rb.randint(0, p // 2)
            lin = f"mod(i * {c1} + {c2}, {p}) - {off}"
            ref = self.ref_text(name, "i", rank)
            if rank == 0:
                v = rb.randint(-20, 40)
                self.arrs[name] = {(): v}
                if self.bon("dt_default_init"):
                    self.dt_defaults[name] = str(v) if v >= 0 else f"({v})"
                    self.features.add("base:dt:default_init")
                else:
                    self.inits[name] = f"{ref} = {v}"
                self.features.add("base:dt:scalar_component")
                continue
            vals = {}
            for (i,) in self.points(a):
                x = (i * c1 + c2) % p - off
                vals[(i,)] = Q(x, 2) if typ == "real8" else x
            self.arrs[name] = vals
            self.inits[name] = (f"{ref} = real({lin}, 8) * 0.5_8"
                                if typ == "real8" else f"{ref} = {lin}")
            if typ != "integer":
                self.tbound[name] = self.value_bound(typ, vals.values())
            self.features.add("base:dt:component:" +
                              ("aos" if "(@)" in name else "nested"
                               if name.count("%") > 1 else "struct")
                              + f":{typ}")
        self.features.add("base:dt:struct")
        if self.bon("dt_nested"):
            self.features.add("base:dt:nested")
        if self.bon("dt_aos"):
            self.features.add("base:dt:aos")

    def component_output(self, nlev: int, typ: str):
        """A new component of dr, dr%nd or ds as a kernel's output (rank
        1), or None."""
        if not self.bon("dt_out") or nlev != 1 or self.rb.random() < 0.4:
            return None
        homes = ["dr"] + (["dr%nd"] if self.bon("dt_nested") else []) + \
            (["ds"] if self.bon("dt_aos") else [])
        home = self.rb.choice(homes)
        comp = f"o{self.k}"
        name = f"ds(@)%{comp}" if home == "ds" else f"{home}%{comp}"
        if typ == "integer" and self.bon("dt_typed") and \
                self.rb.random() < 0.3:
            typ = "real8"
        if typ == "char" and home == "ds":
            typ = "integer"
        self.features.add(f"base:dt:out:{home}")
        a = self.new_array(name, 1, "output", typ=typ,
                           var=home.split("%")[0])
        if home != "ds" and self.bon("al_comp_alloc") and \
                self.rb.random() < 0.5:
            a.alloc = True
            self.features.add("base:al:allocatable_output_component")
        return a

    def dt_decl_lines(self) -> list[str]:
        """The derived-type definitions (components from the generator's
        pseudo-arrays) and the structure declarations."""
        if not getattr(self, "dvars", None):
            return []
        comps: dict[str, list[str]] = {"rec_t": [], "nd_t": [], "el_t": []}
        for a in self.arrays.values():
            if not a.var or a.var in ("ms", "gs"):   # module types
                continue
            if "(@)" in a.name:
                tname, comp, rank = "el_t", a.name.split("%", 1)[1], 0
            else:
                head, comp = a.name.rsplit("%", 1)
                tname, rank = self.DT_TYPES[head], a.rank
            if a.type == "integer":
                spell = "integer"
            else:
                spell = self.spell.get(a.name) or self.decl_spelling(a.type)
                self.spell[a.name] = spell
            init = self.dt_defaults.get(a.name)
            attr = ", allocatable" if a.alloc else ", pointer" \
                if a.name in self.ptrs else ""
            shape = "(:)" if attr else "(n)"
            comps[tname].append(f"    {spell}{attr} :: {comp}"
                                + (shape if rank else "")
                                + (f" = {init}" if init else ""))
        out = []
        if comps["nd_t"]:
            out += ["  type :: nd_t"] + comps["nd_t"] + ["  end type nd_t"]
            comps["rec_t"].append("    type(nd_t) :: nd")
        if "dr" in self.dvars:
            out += ["  type :: rec_t"] + comps["rec_t"] + \
                ["  end type rec_t"]
        if "ds" in self.dvars:
            out += ["  type :: el_t"] + comps["el_t"] + ["  end type el_t"]
        if "dr" in self.dvars:
            out.append("  type(rec_t) :: dr")
        if "ds" in self.dvars:
            out.append("  type(el_t) :: ds(n)")
        if "ms" in self.dvars:
            out.append("  type(mt_t) :: ms")
        return out

    def struct_maps(self, names: set, reads: set, writes: dict
                    ) -> tuple[list, set, set]:
        """Map clauses of the structures referenced by a target construct:
        ([(map key, item)], implicitly mapped variables, component names
        handled). One mode per variable (module docstring)."""
        rb = self.rb
        groups: dict[str, list[str]] = {}
        for n in sorted(names):
            v = self.var_of(n)
            if v != n:
                groups.setdefault(v, []).append(n)
        pairs, implicit, handled = [], set(), set()
        for v, comps in sorted(groups.items()):
            handled |= set(comps)
            aos = v == "ds"
            written = any(writes.get(c) for c in comps)
            if "derived" in self.base:
                modes = (["whole"] if self.bon("dt_whole") else []) + \
                    (["components"] if self.bon("dt_comp") and not aos
                     else []) + (["implicit"] if self.bon("dt_implicit")
                                 else [])
            else:
                modes = ["whole", "implicit"] + ([] if aos else
                                                 ["components"])
            mode = rb.choice(modes or ["implicit"])
            if any(c in self.ptrs for c in comps):
                # a pointer component: through the default mapper its
                # association status is undefined (5.2 §5.8.3)
                mode = "components"
            self.features.add(f"base:dt:map:{mode}")
            if mode == "implicit":
                implicit.add(v)
                continue
            if mode == "whole":
                t = "tofrom" if written else rb.choice(("to", "tofrom"))
                mods = []
                if v == "ms" and getattr(self, "mapper", ""):
                    mods.append(f"mapper({self.mapper})")
                    self.features.add("base:dc:map_with_named_mapper")
                if not self.in_data and rb.random() < 0.2:
                    mods.append("always")
                if rb.random() < 0.15:
                    mods.append("close")
                if self.in_data and rb.random() < 0.3:
                    mods.append("present")
                for m in mods:
                    self.features.add(f"base:dt:map:mod:{m}")
                pairs.append((", ".join(mods + [t]), v))
                continue
            for c in comps:
                kind = writes.get(c)
                opts = ("from", "tofrom") if kind == "full" and \
                    c not in reads else ("tofrom",) if kind else \
                    ("to", "tofrom")
                t = rb.choice(opts)
                mods = []
                if not self.in_data and rb.random() < 0.2:
                    mods.append("always")
                if self.in_data and rb.random() < 0.3 and \
                        c not in self.ptrs:
                    # the data region maps the structure, not the target
                    # of a pointer component (5.2 §5.8.3)
                    mods.append("present")
                item = c
                if self.arrays[c].rank and self.bon("dt_section") and \
                        rb.random() < 0.3:
                    item = f"{c}(1:n)"
                    self.features.add("base:dt:map:component_section")
                pairs.append((", ".join(mods + [t]), item))
        return pairs, implicit, handled

    def dvar_written(self, v: str, writes: dict) -> bool:
        return any(writes.get(n) for n in writes if self.var_of(n) == v)

    def struct_depend(self, reads: set, writes: set, head: str
                      ) -> tuple[list, list]:
        """depend(in) and depend(out/inout) items of a nowait kernel by
        variable: in only when no component is written and every map item
        of the variable is `to` (or the variable is firstprivate)."""
        from offload.engine.fuzz import map_items
        to_items = set(map_items(head, ("to",)))
        other = set(map_items(head, ("tofrom", "from", "alloc")))
        fp = {x for c in re.findall(r"firstprivate\(([^)]*)\)", head)
              for x in re.split(r"\s*,\s*", c.strip())}
        vs: dict[str, set] = {}
        for n in reads | writes:
            vs.setdefault(self.var_of(n), set()).add(n)
        ins, outs = [], []
        for v, ns in sorted(vs.items()):
            ro = not (ns & writes)
            items = {x for x in to_items | other
                     if x == v or x.startswith(v + "%")}
            if ro and (v in fp or (items and all(
                    x in to_items and x not in other for x in items))):
                ins.append(v)
            else:
                outs.append(v)
        return ins, outs

    # -- allocatable, pointer and target variables (stage 3) --

    def setup_alloc(self) -> None:
        rb = self.rb
        if self.bon("al_alloc_scalar"):
            a = self.new_array("as1", 0, "input")
            a.alloc = True
            v = rb.randint(-30, 60)
            self.arrs["as1"] = {(): v}
            self.inits["as1"] = f"as1 = {v}"
            self.features.add("base:al:allocatable_scalar")
        if (self.bon("al_comp_alloc") or self.bon("al_comp_ptr")) and \
                not self.dvars:
            self.setup_derived()
        for name, kind in (("dr%q", "alloc"), ("dr%pc", "ptr")):
            if not self.bon("al_comp_" + kind):
                continue
            a = self.new_array(name, 1, "input", var="dr")
            if kind == "alloc":
                a.alloc = True
            else:
                self.ptrs[name] = "target"
            c1, c2 = rb.randint(3, 61), rb.randint(0, 50)
            p = rb.choice((97, 211, 1009))
            off = rb.randint(0, p // 2)
            self.arrs[name] = {(i,): (i * c1 + c2) % p - off
                               for i in range(1, self.n + 1)}
            lhs = "tgc(i)" if kind == "ptr" else f"{name}(i)"
            self.inits[name] = f"{lhs} = mod(i * {c1} + {c2}, {p}) - {off}"
            self.features.add("base:al:" + ("allocatable" if kind == "alloc"
                                            else "pointer") + "_component")
        if self.bon("al_target"):
            for name in ("ia", "ib", "ic"):
                if rb.random() < 0.5:
                    self.tgt_attr.add(name)
                    self.features.add("base:al:target_attribute")

    def pointer_output(self, out) -> None:
        """Make a new plain output array a POINTER (associated with a
        TARGET array, or allocated)."""
        if out.var or out.name in self.dtv or not self.bon("al_ptr_out") \
                or self.rb.random() < 0.5:
            return
        how = self.rb.choice(("target", "alloc"))
        self.ptrs[out.name] = how
        out.alloc = False
        self.features.add(f"base:al:pointer_output:{how}")

    def check_ref(self, name: str, idx: str, rank: int = 1) -> str:
        """The host checksum's reference (through the target of a
        pointer associated with one)."""
        if self.ptrs.get(name) == "target" and "%" not in name:
            return self.ref_text(name + "t", idx, rank)
        return self.ref_text(name, idx, rank)

    def alloc_decl_lines(self) -> list[str]:
        out = []
        for name, how in self.ptrs.items():
            a = self.arrays.get(name)
            if a is None or "%" in name or how != "target":
                continue
            spell = self.spell.get(name) or self.decl_spelling(a.type) \
                if a.type != "integer" else "integer"
            self.spell[name] = spell
            dims = "n" if a.rank == 1 else "n, m"
            out.append(f"  {spell}, target :: {name}t({dims})")
        if "dr%pc" in self.ptrs and "dr%pc" in self.arrays:
            out.append("  integer, target :: tgc(n)")
        return out

    def alloc_setup_lines(self) -> list[str]:
        """Allocations and pointer associations before the inputs are
        set."""
        out = []
        if "as1" in self.arrays:
            out.append("  allocate(as1)")
        for a in self.arrays.values():
            if a.var and a.alloc:
                out.append(f"  allocate({a.name}(n))")
        for name, how in self.ptrs.items():
            if name not in self.arrays:
                continue
            a = self.arrays[name]
            dims = "n" if a.rank == 1 else "n, m"
            if name == "dr%pc":
                out.append("  dr%pc => tgc")
            elif how == "target":
                out.append(f"  {name} => {name}t")
            else:
                out.append(f"  allocate({name}({dims}))")
        return out

    def decl_attrs(self, name: str) -> str:
        """Extra attributes of a plain array's declaration."""
        return ", target" if name in getattr(self, "tgt_attr", ()) else ""

    # -- kernels in internal procedures (stage 3) --

    def wrap_in_procedure(self, kern, ind: str):
        """Move a kernel into an internal subroutine kp<k> (module
        docstring); returns the kernel's replacement lines."""
        from offload.engine.fuzz import map_items, add_clauses
        rb = self.rb
        k = len(self.procs) + 1
        pname = f"kp{k}"
        text = "\n".join(kern.lines)
        to_items = set(map_items(text, ("to",)))
        other = set(map_items(text, ("tofrom", "from", "alloc")))
        dummies, decls = [], []
        for a in sorted(self.arrays.values(), key=lambda a: a.name):
            if a.var or a.name in self.dtv or \
                    not re.search(self.ref_re(a.name), text):
                continue
            dummies.append(a.name)
            decls.append(self.dummy_decl(a, kern, to_items, other))
        for v in sorted(self.dvars):
            if v not in self.dtv and re.search(rf"\b{v}\b", text):
                dummies.append(v)
                shape = rb.choice(("(:)", "(n)")) if v == "ds" else ""
                decls.append(f"type({self.dvars[v]}), intent(inout) :: "
                             f"{v}{shape}")
                self.features.add("base:al:structure_dummy")
        params = [p for p in self.params() if re.search(rf"\b{p}\b", text)]
        for p in params:
            dummies.append(p)
            form = rb.choice(["intent(in)"] +
                             (["value"] if self.bon("al_value") else []) +
                             (["intent(in), optional"]
                              if self.bon("al_optional") else []))
            decls.append(f"integer, {form} :: {p}")
            self.features.add("base:al:dummy:" + form.replace(
                "intent(in), ", "").replace("(", "_").replace(")", ""))
        lines = list(kern.lines)
        if self.bon("al_optional_absent") and lines[0].lstrip().startswith(
                "!$omp target") and rb.random() < 0.5:
            dummies.append("zopt")
            decls.append("integer, intent(in), optional :: zopt(:)")
            lines = add_clauses(lines, ["map(to: zopt)"])
            self.features.add("base:al:optional_absent_in_map")
        locs = sorted(set(re.findall(r"\b((?:t|acc)\d+)\b", text)))
        body = [f"  subroutine {pname}("
                f"{', '.join(dummies)})"] + \
            [f"    {d}" for d in decls] + \
            [f"    integer :: {', '.join(['i', 'j', 'jj'] + locs)}"]
        base_ind = len(ind)
        body += ["    " + ln[base_ind:] for ln in lines]
        body.append(f"  end subroutine {pname}")
        self.procs.append("\n".join(body))
        args = [d for d in dummies if d != "zopt"]
        self.features.add("base:al:kernel_in_internal_procedure")
        return [f"{ind}call {pname}({', '.join(args)})"]

    def dummy_decl(self, a, kern, to_items: set, other: set) -> str:
        rb = self.rb
        name = a.name
        spell = "integer" if a.type == "integer" else \
            self.spell.get(name) or self.decl_spelling(a.type)
        if a.rank == 0:
            # intent(in) only when every map of the kernel is `to` (a
            # tofrom map would copy back into it)
            intent = "in" if name in to_items and name not in other \
                else "inout"
            if a.type == "char":
                self.features.add("base:al:dummy:char_len")
                if self.bon("al_assumed_len"):
                    self.features.add("base:al:dummy:assumed_length")
                    return f"character(len=*), intent({intent}) :: {name}"
                return f"{spell}, intent({intent}) :: {name}"
            alloc = ", allocatable" if a.alloc and self.bon(
                "al_alloc_dummy") else ""
            return f"{spell}{alloc}, intent({intent}) :: {name}"
        written = name in kern.writes
        if written:
            intent = "inout"
            if self.bon("al_intent_out") and rb.random() < 0.5 and \
                    not a.alloc and name not in self.ptrs and \
                    self.full_out.get(name) and name not in kern.reads:
                intent = "out"
        else:
            intent = "in" if name in to_items and name not in other \
                else "inout"
        deferred = "(:)" if a.rank == 1 else "(:, :)"
        explicit = "(n)" if a.rank == 1 else "(n, m)"
        k = rb.random()
        if a.alloc and self.bon("al_alloc_dummy") and k < 0.5:
            form, shape = "allocatable", deferred
        elif name in self.ptrs and self.bon("al_ptr_dummy") and k < 0.5:
            form, shape = "pointer", deferred
            intent = "in"     # the association, not the target
        elif self.bon("al_explicit_dummy") and k < 0.7:
            form, shape = "explicit", explicit
        else:
            form, shape = "assumed_shape", deferred
        self.features.add(f"base:al:dummy:{form}")
        self.features.add(f"base:al:dummy:intent_{intent}")
        attr = f", {form}" if form in ("allocatable", "pointer") else ""
        return f"{spell}{attr}, intent({intent}) :: {name}{shape}"

    # -- declare target, mappers, user reductions (stage 4) --

    def setup_declare(self) -> None:
        from offload.engine.fuzz import (ARef, Bin, Call, Const, Func, Intr,
                                     Var)
        rb = self.rb
        self.dc_static = {}
        if self.bon("dc_modvar") or self.bon("dc_calls"):
            a = self.new_array("gtab", 1, "input")
            a.alloc = False
            self.dtv.add("gtab")
            c1, c2 = rb.randint(3, 61), rb.randint(0, 50)
            p = rb.choice((97, 211, 1009))
            off = rb.randint(0, p // 2)
            self.arrs["gtab"] = {(i,): (i * c1 + c2) % p - off
                                 for i in range(1, self.n + 1)}
            if self.bon("dc_static_init"):
                self.dc_static["gtab"] = (f"[(mod(kk * {c1} + {c2}, {p}) - "
                                          f"{off}, kk = 1, nm)]")
                self.features.add("base:dc:static_init")
            else:
                self.inits["gtab"] = (f"gtab(i) = mod(i * {c1} + {c2}, {p})"
                                      f" - {off}")
            self.features.add("base:dc:declare_target_array")
        if self.bon("dc_modtype"):
            self.dvars["gs"] = "gp_t"
            self.new_array("gs%k", 1, "input", var="gs")
            self.dtv |= {"gs", "gs%k"}
            c1, c2 = rb.randint(3, 61), rb.randint(0, 50)
            self.arrs["gs%k"] = {(i,): (i * c1 + c2) % 211 - 100
                                 for i in range(1, self.n + 1)}
            self.inits["gs%k"] = f"gs%k(i) = mod(i * {c1} + {c2}, 211) - 100"
            self.features.add("base:dc:declare_target_structure")
        if self.bon("dc_mapper"):
            self.dvars["ms"] = "mt_t"
            self.new_array("ms%a", 1, "input", var="ms")
            c1, c2 = rb.randint(3, 61), rb.randint(0, 50)
            self.arrs["ms%a"] = {(i,): (i * c1 + c2) % 101 - 50
                                 for i in range(1, self.n + 1)}
            self.inits["ms%a"] = f"ms%a(i) = mod(i * {c1} + {c2}, 101) - 50"
            self.mapper = "mmap" if self.bon("dc_named_mapper") else ""
            self.features.add("base:dc:declare_mapper:" +
                              ("named" if self.mapper else "default"))
        if self.bon("dc_chain") or self.bon("dc_calls"):
            gm0 = Func("gm0", ("x",), Bin("+", Intr("iand", (Var("x"),
                                                             Const(255))),
                                          Const(rb.randint(1, 9))))
            self.mfuncs.append(gm0)
            if self.bon("dc_calls") and "gtab" in self.arrs:
                idx = Bin("+", Intr("mod", (Intr("abs", (Var("x"),)),
                                            NConst("nm", self.n))), Const(1))
                self.dfuncs.append(Func("gd1", ("x",), Intr("mod", (
                    Bin("+", Var("x"), ARef("gtab", (idx,))),
                    Const(1009)))))
                self.features.add("base:dc:device_function_reads_module_var")
            if self.bon("dc_chain"):
                self.dfuncs.append(Func("gd2", ("x",), Intr("mod", (
                    Bin("+", Call(gm0, (Var("x"),)), Bin("*", Var("x"),
                                                          Const(3))),
                    Const(1009)))))
                self.features.add("base:dc:call_across_modules")
        if self.bon("dc_udr"):
            self.features.add("base:dc:declare_reduction_available")
        if self.dtv:
            self.features.add("base:dc:declare_target_" + (
                "enter" if self.bon("dc_enter") else "to"))

    def modvar_output(self, nlev: int):
        """A declare target module array as a kernel's output, or None."""
        if not self.bon("dc_modvar_out") or nlev != 1 or \
                self.rb.random() < 0.5:
            return None
        a = self.new_array(f"go{self.k}", 1, "output")
        a.alloc = False
        self.dtv.add(a.name)
        self.features.add("base:dc:declare_target_output")
        return a

    def udr_red(self, idx: int):
        """A reduction with the user-defined identifier padd on pair_t, or
        None."""
        if not self.bon("dc_udr") or self.rb.random() < 0.6:
            return None
        from offload.engine.fuzz import Red
        init = (self.rb.randint(-20, 20), self.rb.randint(-20, 20))
        name = f"rp{self.k}{'ab'[idx]}"
        self.tscalars[name] = ("pair", init)
        self.env[name] = init
        self.check_items.append(name)
        self.features.add("base:dc:declare_reduction")
        return Red(name, "padd", "clause", init, "pair")

    def udr_term(self, lv: list):
        from offload.engine.fuzz import Const, Intr
        return (Intr("mod", (self.expr(1, lv), Const(97))),
                Intr("mod", (self.expr(1, lv), Const(13))))

    def dc_module_lines(self) -> list[str]:
        """Modules fuzz_dmod and fuzz_dfun (stage 4)."""
        from offload.engine.fuzz import wrap_stmt
        if not (self.dtv or self.mfuncs or "ms" in self.dvars or
                self.bon("dc_udr")):
            return []
        L = ["module fuzz_dmod", "  implicit none",
             f"  integer, parameter :: nm = {self.n}"]
        if self.dc_static:
            L.append("  integer, private :: kk")
        if "gs" in self.dvars:
            L += ["  type :: gp_t", "    integer :: k(nm)", "  end type gp_t"]
        if "ms" in self.dvars:
            comps = [a.name.split("%", 1)[1] for a in self.arrays.values()
                     if a.var == "ms"]
            L += ["  type :: mt_t"] + [f"    integer :: {c}(nm)"
                                        for c in comps] + ["  end type mt_t"]
        if self.bon("dc_udr"):
            L += ["  type :: pair_t", "    integer :: x, y",
                  "  end type pair_t"]
        arrs = [a.name for a in self.arrays.values()
                if a.name in self.dtv and not a.var]
        for name in arrs:
            init = self.dc_static.get(name)
            L.append(f"  integer :: {name}(nm)" + (f" = {init}" if init
                                                     else ""))
        if "gs" in self.dvars:
            L.append("  type(gp_t) :: gs")
        dt = arrs + (["gs"] if "gs" in self.dvars else [])
        if dt:
            # 5.2 spells the clause enter; to is its deprecated synonym
            # (5.2 §7.8.2), which CCE 19/20 still require
            cl = "enter" if self.bon("dc_enter") else "to"
            L.append(f"  !$omp declare target {cl}({', '.join(dt)})")
        if "ms" in self.dvars:
            comps = [a.name.split("%", 1)[1] for a in self.arrays.values()
                     if a.var == "ms"]
            head = f"{self.mapper}: " if self.mapper else ""
            L.append(f"  !$omp declare mapper({head}mt_t :: v) map(tofrom: "
                     + ", ".join(f"v%{c}" for c in comps) + ")")
        if self.bon("dc_udr"):
            L += ["  !$omp declare reduction(padd: pair_t: omp_out = &",
                  "  !$omp& pair_t(omp_out%x + omp_in%x, omp_out%y + "
                  "omp_in%y)) &",
                  "  !$omp& initializer(omp_priv = pair_t(0, 0))"]
        if self.mfuncs:
            L.append("contains")
            for fn in self.mfuncs:
                L += self.func_lines(fn)
        L.append("end module fuzz_dmod")
        if self.dfuncs:
            L += ["module fuzz_dfun", "  use fuzz_dmod", "  implicit none",
                  "contains"]
            for fn in self.dfuncs:
                L += self.func_lines(fn)
            L.append("end module fuzz_dfun")
        return L

    @staticmethod
    def func_lines(fn) -> list[str]:
        from offload.engine.fuzz import wrap_stmt
        args = ", ".join(fn.params)
        return ([f"  integer function {fn.name}({args})",
                 "    !$omp declare target",
                 f"    integer, intent(in) :: {args}"]
                + wrap_stmt("    ", f"{fn.name} = {fn.body.f()}")
                + [f"  end function {fn.name}"])

    def dc_setup_lines(self) -> list[str]:
        """Host statements after the inputs: zero the declare target
        outputs and copy the module variables set on the host to the
        device."""
        out = [f"  {a.name} = 0" for a in self.arrays.values()
               if a.name in self.dtv and a.role == "output"]
        out = []
        upd = [a.name for a in self.arrays.values()
               if a.name in self.dtv and not a.var and
               (a.role == "output" or a.name in self.inits)]
        if "gs" in self.dvars:
            upd.append("gs")
        if upd:
            out.append(f"  !$omp target update to({', '.join(upd)})")
        return out

    def dc_final_lines(self) -> list[str]:
        outs = [a.name for a in self.arrays.values()
                if a.name in self.dtv and a.role == "output"]
        return [f"  !$omp target update from({', '.join(outs)})"] \
            if outs else []

    # -- type extension, type-bound procedures, polymorphism (fuzz-5) --

    def setup_oop(self) -> None:
        """The device functions oo1..oo5 (module fuzz_omod) and their
        models. Every object is a local variable of a device function, so
        no polymorphic object is ever mapped (OpenMP 6.0 §7.9.6 p.288)."""
        from offload.engine.fuzz import Bin, Const, Func, Intr, Var
        rb = self.rb
        c = {"a1": rb.randint(2, 7), "p1": rb.choice((97, 211, 1009)),
             "a2": rb.randint(2, 5), "p2": rb.choice((89, 101, 997)),
             "k": {}, "j": {}, "k2": {}}
        x = Var("x")
        on = [f for f in GROUP_SWARM["oop"] if self.bon(f)] or \
            ["oo_dispatch"]

        def ob(k):
            return Intr("mod", (Bin("+", Bin("*", x, Const(c["a1"])),
                                    Const(k)), Const(c["p1"])))

        def ox(k, j):
            return Intr("mod", (Bin("+", ob(k), Const(j * c["a2"])),
                                Const(c["p2"])))
        for n, feat in enumerate(GROUP_SWARM["oop"], start=1):
            if feat not in on:
                continue
            name = f"oo{n}"
            k, j, k2 = rb.randint(0, 50), rb.randint(1, 40), \
                rb.randint(0, 30)
            c["k"][name], c["j"][name], c["k2"][name] = k, j, k2
            body = {
                "oo_dispatch": lambda: ob(k),
                "oo_override": lambda: ox(k, j),
                "oo_inherit": lambda: Bin("+", ox(k, j), Const(k)),
                "oo_select": lambda: Bin("+", Bin("+", x, Const(j)),
                                         Bin("-", x, Const(k2))),
                "oo_unlimited": lambda: Bin("+", Intr("mod", (Bin(
                    "+", Bin("*", x, Const(3)), Const(j)), Const(1009))),
                    Intr("mod", (Bin("+", x, Const(k2)), Const(1009)))),
            }[feat]()
            self.ofuncs.append(Func(name, ("x",), body))
            self.features.add(f"base:oop:{feat[3:]}")
        self.oop_consts = c

    def oop_module_lines(self) -> list[str]:
        """Module fuzz_omod (fuzz-5)."""
        c = self.oop_consts
        dt = "    !$omp declare target"

        def fn(name, args, decls, body):
            return ([f"  integer function {name}({args})", dt] +
                    [f"    {d}" for d in decls] +
                    [f"    {b}" for b in body] +
                    [f"  end function {name}"])
        L = ["module fuzz_omod", "  implicit none",
             "  type :: ob_t", "    integer :: k = 0", "  contains",
             "    procedure :: f => ob_f", "    procedure :: g => ob_g",
             "  end type ob_t", "  type, extends(ob_t) :: ox_t",
             "    integer :: j = 0", "  contains",
             "    procedure :: f => ox_f", "  end type ox_t", "contains"]
        sx = ["class(ob_t), intent(in) :: s", "integer, intent(in) :: x"]
        L += fn("ob_f", "s, x", sx,
                [f"ob_f = mod(x * {c['a1']} + s%k, {c['p1']})"])
        L += fn("ob_g", "s, x", sx, ["ob_g = s%f(x) + s%k"])
        L += fn("ox_f", "s, x", ["class(ox_t), intent(in) :: s",
                                 "integer, intent(in) :: x"],
                [f"ox_f = mod(s%ob_t%f(x) + s%j * {c['a2']}, {c['p2']})"])
        L += fn("od", "s, x", sx, ["od = s%f(x)"])
        L += fn("osel", "s, x", sx,
                ["select type (s)", "type is (ox_t)", "  osel = x + s%j",
                 "class default", "  osel = x - s%k", "end select"])
        L += fn("cany", "s, x", ["class(*), intent(in) :: s",
                                 "integer, intent(in) :: x"],
                ["select type (s)", "type is (ox_t)",
                 "  cany = mod(x * 3 + s%j, 1009)", "type is (integer)",
                 "  cany = mod(x + s, 1009)", "class default",
                 "  cany = 0", "end select"])
        xd = ["integer, intent(in) :: x"]
        for f in self.ofuncs:
            k, j, k2 = c["k"][f.name], c["j"][f.name], c["k2"][f.name]
            if f.name == "oo1":
                L += fn("oo1", "x", xd + ["type(ob_t) :: o"],
                        [f"o%k = {k}", "oo1 = od(o, x)"])
            elif f.name == "oo2":
                L += fn("oo2", "x", xd + ["type(ox_t) :: o"],
                        [f"o%k = {k}", f"o%j = {j}", "oo2 = od(o, x)"])
            elif f.name == "oo3":
                L += fn("oo3", "x", xd + ["type(ox_t) :: o"],
                        [f"o%k = {k}", f"o%j = {j}", "oo3 = o%g(x)"])
            elif f.name == "oo4":
                L += fn("oo4", "x", xd + ["type(ox_t) :: o",
                                          "type(ob_t) :: b"],
                        [f"o%k = {k}", f"o%j = {j}", f"b%k = {k2}",
                         "oo4 = osel(o, x) + osel(b, x)"])
            else:
                L += fn("oo5", "x", xd + ["type(ox_t) :: o",
                                          "integer :: kk"],
                        [f"o%k = {k}", f"o%j = {j}", f"kk = {k2}",
                         "oo5 = cany(o, x) + cany(kk, x)"])
        L.append("end module fuzz_omod")
        return L

    # -- translation units (stage 5) --

    def setup_multitu(self) -> None:
        from offload.engine.fuzz import Bin, Call, Const, Func, Intr, Var
        rb = self.rb
        self.mt_funcs: dict[str, list] = {}
        x = Var("x")
        if self.bon("mt_amod") or self.bon("mt_chain") or not any(
                self.bon(f) for f in ("mt_submodule", "mt_external")):
            ga1 = Func("ga1", ("x",), Intr("mod", (Bin("+", Bin(
                "*", Intr("iand", (x, Const(1023))), Const(rb.randint(2, 7))),
                Const(rb.randint(0, 50))), Const(1013))))
            self.mt_funcs["fuzz_amod"] = [ga1]
            self.xfuncs.append(ga1)
            self.features.add("base:mt:module_file")
            if self.bon("mt_chain"):
                gb1 = Func("gb1", ("x",), Intr("mod", (Bin("+", Call(
                    ga1, (x,)), Bin("*", x, Const(rb.choice((3, 5))))),
                    Const(2003))))
                self.mt_funcs["fuzz_bmod"] = [gb1]
                self.xfuncs.append(gb1)
                self.features.add("base:mt:module_chain")
        if self.bon("mt_submodule"):
            gs1 = Func("gs1", ("x",), Intr("mod", (Intr("ieor", (x, Const(
                rb.randint(1, 255)))), Const(4093))))
            self.mt_funcs["fuzz_smod"] = [gs1]
            self.xfuncs.append(gs1)
            self.features.add("base:mt:submodule")
        if self.bon("mt_external"):
            ge1 = Func("ge1", ("x",), Intr("mod", (Bin("-", Intr("max", (
                x, Const(rb.randint(-30, 30)))), Const(rb.randint(0, 9))),
                Const(997))))
            self.mt_funcs["external"] = [ge1]
            self.xfuncs.append(ge1)
            self.features.add("base:mt:external_function")
        self.features.add("base:mt:file_set")

    def mt_unit_lines(self) -> list[tuple[str, list[str]]]:
        """(file name, lines) of the stage-5 units, in compile order."""
        out = []
        for mod in ("fuzz_amod", "fuzz_bmod"):
            if mod not in self.mt_funcs:
                continue
            L = [f"module {mod}"]
            if mod == "fuzz_bmod":
                L.append("  use fuzz_amod, only: ga1")
            L += ["  implicit none", "contains"]
            for fn in self.mt_funcs[mod]:
                L += self.func_lines(fn)
            L.append(f"end module {mod}")
            out.append((f"{mod}.f90", L))
        if "fuzz_smod" in self.mt_funcs:
            fn = self.mt_funcs["fuzz_smod"][0]
            out.append(("fuzz_smod.f90", [
                "module fuzz_smod", "  implicit none", "  interface",
                f"    module integer function {fn.name}(x)",
                "      !$omp declare target",
                "      integer, intent(in) :: x",
                f"    end function {fn.name}", "  end interface",
                "end module fuzz_smod"]))
            body = self.func_lines(fn)
            body[0] = body[0].replace("  integer function",
                                      "  module integer function")
            out.append(("fuzz_ssub.f90", [
                "submodule (fuzz_smod) fuzz_ssub", "  implicit none",
                "contains"] + body + ["end submodule fuzz_ssub"]))
        if "external" in self.mt_funcs:
            fn = self.mt_funcs["external"][0]
            from offload.engine.fuzz import wrap_stmt
            out.append(("fuzz_ext.f90", [
                f"integer function {fn.name}(x)", "  implicit none",
                "  integer, intent(in) :: x", "  !$omp declare target"]
                + wrap_stmt("  ", f"{fn.name} = {fn.body.f()}")
                + [f"end function {fn.name}"]))
        return out

    def mt_use_lines(self) -> list[str]:
        out = []
        for mod in ("fuzz_amod", "fuzz_bmod", "fuzz_smod"):
            if mod in self.mt_funcs:
                out.append(f"  use {mod}, only: "
                           + ", ".join(f.name for f in self.mt_funcs[mod]))
        return out

    def mt_interface_lines(self) -> list[str]:
        if "external" not in self.mt_funcs:
            return []
        fn = self.mt_funcs["external"][0]
        return ["  interface", f"    integer function {fn.name}(x)",
                "      !$omp declare target",
                "      integer, intent(in) :: x",
                f"    end function {fn.name}", "  end interface"]


def split_bundle(source: str) -> list[tuple[str, str]] | None:
    """The files of a bundle (stage 5) in compile order: [(name, text)];
    None if `source` is a single file. Lines before the first marker (the
    generator's comment header) go to the first file."""
    if FILE_MARK not in source:
        return None
    files: list[list] = []
    head: list[str] = []
    for line in source.splitlines():
        if line.startswith(FILE_MARK):
            files.append([line[len(FILE_MARK):].strip(), []])
        elif files:
            files[-1][1].append(line)
        else:
            head.append(line)
    if files:
        files[0][1] = head + files[0][1]
    return [(n, "\n".join(ls) + "\n") for n, ls in files]


@dataclass(frozen=True)
class NConst:
    """A named integer constant (Fortran text `name`, value `v`)."""
    name: str
    v: int

    def f(self):
        return self.name

    def ev(self, env, arrs):
        return self.v
