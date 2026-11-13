"""fortran-oop: program families of Fortran derived types and object-oriented
features in device code.

Each family is a set of small, self-checking, free-form Fortran programs
(OpenMP 5.2, or OpenACC 3.4 for the ``acc-`` families). A program prints
``name= value`` lines and the harness's ``RESULT ran_on_host=<0|1>
check=<pass|fail>`` line. Expected values are computed here in Python from
the program's arithmetic and written into its checks and header.
``legality`` is ``defined`` (the program must pass both legality witnesses,
offload.engine.prerun) or ``unspecified`` (the spec leaves the behaviour
unspecified or OpenACC 3.4 does not address it; a failure is an
observation, not a finding; ``why`` cites the text). Expected values hold in
both memory modes unless ``modes`` says otherwise.
``programs()`` lists every program, ``program(id)`` returns one, and
``Program.harness()`` is the offload.engine.gen.Program the harness runs."""
from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass, field

N = 64
S1 = N * (N + 1) // 2            # sum 1..n
S2 = N * (N + 1) * (2 * N + 1) // 6  # sum of squares 1..n


@dataclass(frozen=True)
class Program:
    id: str
    family: str
    variant: str
    title: str
    model: str                 # "omp" | "acc"
    version: int               # 52 | 34
    source: str
    expected: dict
    legality: str              # "defined" | "unspecified"
    cites: tuple
    why: str = ""
    modes: tuple = ("copy", "unified")
    lang: str = "f90"

    @property
    def text(self) -> str:     # offload.engine.prerun reads .text or .source
        return self.source

    def harness(self):
        """The offload.engine.gen.Program the harness runs."""
        from offload.engine.gen import Program as HP
        return HP(id=self.id, lang="f90", source=self.source,
                  atoms=frozenset({f"oop.{self.family}"}),
                  primary_atom=f"oop.{self.family}", legal=True,
                  violates=None, observable=True, model=self.model)


@dataclass
class V:
    """One variant under construction."""
    family: str
    variant: str
    title: str
    cites: list
    types: str = ""
    mod_decls: str = ""
    procs: str = ""
    decls: str = ""
    body: str = ""
    checks: list = field(default_factory=list)   # (name, expected int)
    legality: str = "defined"
    why: str = ""
    model: str = "omp"
    modes: tuple = ("copy", "unified")


_OPEN = re.compile(r"^(?:do\b|if\s*\(.*\)\s*then$|select\s+type\b|"
                   r"(?:abstract\s+)?interface\b|module\s+(?!procedure)\w+$|"
                   r"type\s*(?:,[^:]*)?::|type\s+(?!is\b)\w+$|"
                   r"(?:[\w(),=*]+\s+)*?(?:subroutine|function)\s+\w+)",
                   re.I)
_MIDDLE = re.compile(r"^(?:else\b|type\s+is\b|class\s+is\b|"
                     r"class\s+default\b|contains$)", re.I)
_CLOSE = re.compile(r"^end\b", re.I)


def _block(text: str, indent: int) -> list[str]:
    """The statements of `text`, re-indented by nesting (two blanks per
    level, directives at the level of the code around them)."""
    out, level, in_select = [], 0, []
    for raw in text.split("\n"):
        ln = raw.strip()
        if not ln:
            continue
        if _CLOSE.match(ln):
            if re.match(r"^end\s*select", ln, re.I) and in_select:
                level -= 1
                in_select.pop()
            level -= 1
            out.append(" " * (indent + 2 * max(level, 0)) + ln)
            continue
        if _MIDDLE.match(ln):
            if re.match(r"^(?:type|class)\s+(?:is|default)", ln, re.I):
                if in_select and in_select[-1]:
                    level -= 1
                elif in_select:
                    in_select[-1] = True
                out.append(" " * (indent + 2 * level) + ln)
                level += 1
                continue
            out.append(" " * (indent + 2 * max(level - 1, 0)) + ln)
            continue
        out.append(" " * (indent + 2 * level) + ln)
        if _OPEN.match(ln) and not ln.lower().startswith("!"):
            level += 1
            if re.match(r"^select\s+type", ln, re.I):
                in_select.append(False)
    return out


def _wrap(prefix: str, text: str) -> list[str]:
    lines = textwrap.wrap(text, 96, break_long_words=False,
                          break_on_hyphens=False)
    return [f"! {prefix}{lines[0]}"] + [f"!   {ln}" for ln in lines[1:]]


def render(v: V) -> Program:
    acc = v.model == "acc"
    pid = f"oop-{v.family}-{v.variant}"
    head = [f"! fortran-oop {v.family}/{v.variant} "
            f"({'OpenACC 3.4' if acc else 'OpenMP 5.2'}, free-form Fortran):"]
    head += _wrap("", v.title)
    head += _wrap("spec: ", "; ".join(v.cites))
    head += _wrap("legality: ", v.legality + (f": {v.why}" if v.why else ""))
    head += _wrap("expected (computed by compliance/oop_gen.py): ",
                  ", ".join(f"{k}= {x}" for k, x in v.checks))
    mod = ["module oop_m", "  implicit none", f"  integer, parameter :: n = {N}"]
    mod += _block(v.types, 2) + _block(v.mod_decls, 2)
    procs = _block(v.procs, 2)
    if procs:
        mod += ["contains"] + procs
    mod += ["end module oop_m"]
    main = ["program oop", f"  use {'openacc' if acc else 'omp_lib'}",
            "  use oop_m", "  implicit none", "  integer :: host_flag",
            "  logical :: ok"]
    names = {k for k, _ in v.checks}
    declared = "\n".join(ln for ln in v.decls.split("\n")
                         if "::" in ln).lower()
    missing = [k for k in sorted(names)
               if not re.search(rf"\b{k}\b", declared)]
    if missing:
        main += [f"  integer :: {', '.join(missing)}"]
    main += _block(v.decls, 2)
    main += ["  host_flag = 1"]
    if acc:
        main += ["  !$acc serial copy(host_flag)",
                 "  host_flag = merge(1, 0, acc_on_device(acc_device_host))",
                 "  !$acc end serial"]
    else:
        main += ["  !$omp target map(from: host_flag)",
                 "  host_flag = merge(1, 0, omp_is_initial_device())",
                 "  !$omp end target"]
    main += _block(v.body, 2)
    main += ["  ok = .true."]
    main += [f"  ok = ok .and. ({k} == {x})" for k, x in v.checks]
    main += [f"  print '(a,i0)', '{k}= ', {k}" for k, _ in v.checks]
    main += ["  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, "
             "' check=', merge('pass', 'fail', ok)", "end program oop"]
    src = "\n".join(head + mod + [""] + main) + "\n"
    too_long = [ln for ln in src.split("\n") if len(ln) > 132]
    if too_long:
        raise ValueError(f"{pid}: line over 132 characters: {too_long[0]}")
    return Program(id=pid, family=v.family, variant=v.variant,
                   title=v.title, model=v.model,
                   version=34 if acc else 52, source=src,
                   expected=dict(v.checks), legality=v.legality,
                   cites=tuple(v.cites), why=v.why, modes=v.modes)


# --- shared pieces --------------------------------------------------------------------

VEC = """
type vec
  integer :: n = 0
  integer, allocatable :: a(:)
end type vec
"""

VEC_SETUP = """
allocate(x%a(n))
x%n = n
do i = 1, n
  x%a(i) = i
end do
"""

C_MAPPABLE = "OpenMP 5.2 §1.2.6 p.18-19 (mappable type)"
C_MAP = "OpenMP 5.2 §5.8.3 p.151-155 (map clause)"
C_DEFMAPPER = "OpenMP 5.2 §5.8.2 p.150 (predefined default mapper)"
C_ALLOCCOMP = ("OpenMP 5.2 §5.8.3 p.151 l.29-37 (components from the "
               "predefined default mapper); OpenMP 6.0 §B.5 p.909 l.35-37 "
               "(5.0: mapping of allocatable and pointer components)")
C_ARRAYELTS = ("OpenMP 6.0 §7.9.6 p.281 l.25-26 (array elements become "
               "implicit list items)")
C_IMPLICIT = ("OpenMP 5.2 §5.8.1 p.148 (implicit data-mapping: a "
              "non-scalar is tofrom); §1.2.6 (scalar: intrinsic type)")
C_STRUCTELT = ("OpenMP 5.2 §13.8 p.286 l.27-28 (other referenced elements "
               "of a mapped structure element are mapped too)")
C_TBP = ("OpenMP 5.2 §1.2.6 p.19 l.1-3 (type-bound procedures accessed in "
         "a target region appear in a declare target directive)")
C_DT = "OpenMP 5.2 §7.8.1 p.205-207 (declare target, procedures)"
C_PROCREF = "OpenMP 5.2 §13.8 p.285 l.1-3 (procedures referenced in target)"
C_UPDATE = "OpenMP 5.2 §13.9 (target update)"
C_ENTER = "OpenMP 5.2 §13.6, §13.7 (target enter data, target exit data)"
C_MAPPER = "OpenMP 5.2 §5.8.8 p.162-164 (declare mapper)"
C_SECTION = ("OpenMP 5.2 §5.8.3 p.151 l.13 (structure elements and array "
             "sections are list items); §5.8.3 p.157 l.21-22")
C_POLY60 = ("OpenMP 6.0 §7.9.6 p.288 l.10 (Fortran: a map list item of "
            "polymorphic type: the behavior is unspecified)")
C_FINAL = ("OpenMP 5.2 §5.3 p.107 l.20-22 (finalization of a privatized "
           "list item at the end of the region)")


# --- F01 nested types and arrays of types ---------------------------------------------

def _nested() -> list[V]:
    out = []
    types = """
    type inner
      integer :: a = 0, b = 0
    end type inner
    type outer
      type(inner) :: in
      integer :: c = 0
      integer :: arr(4) = 0
    end type outer
    """
    setup = """
    o%in%a = 3
    o%in%b = 5
    o%c = 7
    o%arr = [1, 2, 3, 4]
    """
    region = """
    o%c = o%in%a * 10 + o%in%b + o%arr(1) + o%arr(2) + o%arr(3) + o%arr(4)
    o%in%a = o%in%a + o%arr(4)
    """
    tail = "r1 = o%c\nr2 = o%in%a\n"
    r1 = 3 * 10 + 5 + 1 + 2 + 3 + 4
    out.append(V("nested", "whole", "a structure with a nested structure and "
                 "a fixed-size array component, map(tofrom:) whole",
                 [C_MAP, C_DEFMAPPER], types=types,
                 decls="type(outer) :: o",
                 body=setup + "!$omp target map(tofrom: o)\n" + region +
                 "!$omp end target\n" + tail,
                 checks=[("r1", r1), ("r2", 3 + 4)]))
    out.append(V("nested", "implicit", "the same structure referenced in a "
                 "target region without a map clause (implicitly tofrom)",
                 [C_IMPLICIT, C_DEFMAPPER], types=types,
                 decls="type(outer) :: o",
                 body=setup + "!$omp target\n" + region + "!$omp end target\n"
                 + tail, checks=[("r1", r1), ("r2", 7)]))
    out.append(V("nested", "aos", "an array of structures in a target teams "
                 "distribute parallel do",
                 [C_MAP, C_ARRAYELTS],
                 types="type pt\n  integer :: x = 0, y = 0\nend type pt",
                 decls="type(pt) :: p(n)\ninteger :: i",
                 body="""
                 do i = 1, n
                   p(i)%x = i
                   p(i)%y = 2 * i
                 end do
                 !$omp target teams distribute parallel do map(tofrom: p)
                 do i = 1, n
                   p(i)%x = p(i)%x + 3 * p(i)%y
                 end do
                 r1 = sum(p%x)
                 r2 = p(n)%x
                 """, checks=[("r1", 7 * S1), ("r2", 7 * N)]))
    out.append(V("nested", "cells", "a structure whose component is an array "
                 "of structures with array components, with a reduction",
                 [C_MAP, "OpenMP 5.2 §17.2 p.341 l.11-13 (a reduction on a "
                  "combined target construct maps tofrom)"],
                 types="""
                 type cell
                   integer :: v(3) = 0
                 end type cell
                 type grid
                   type(cell) :: c(n)
                   integer :: total = 0
                 end type grid
                 """, decls="type(grid) :: g\ninteger :: i, tot",
                 body="""
                 do i = 1, n
                   g%c(i)%v = [i, 2 * i, 3 * i]
                 end do
                 tot = 0
                 !$omp target teams distribute parallel do map(tofrom: g) reduction(+: tot)
                 do i = 1, n
                   g%c(i)%v(2) = g%c(i)%v(1) + g%c(i)%v(3)
                   tot = tot + g%c(i)%v(2)
                 end do
                 r1 = tot
                 r2 = g%c(5)%v(2)
                 """, checks=[("r1", 4 * S1), ("r2", 20)]))
    out.append(V("nested", "enterexit", "an array of structures by target "
                 "enter data, updated on the device, target update from, "
                 "exit data", [C_ENTER, C_UPDATE, C_MAP],
                 types="type pt\n  integer :: x = 0, y = 0\nend type pt",
                 decls="type(pt) :: p(n)\ninteger :: i",
                 body="""
                 do i = 1, n
                   p(i)%x = i
                   p(i)%y = 0
                 end do
                 !$omp target enter data map(to: p)
                 !$omp target teams distribute parallel do
                 do i = 1, n
                   p(i)%x = 2 * p(i)%x
                   p(i)%y = i
                 end do
                 !$omp target update from(p)
                 r1 = sum(p%x)
                 r2 = sum(p%y)
                 !$omp target exit data map(release: p)
                 """, checks=[("r1", 2 * S1), ("r2", S1)]))
    return out


# --- F02 allocatable components (deep copy) -------------------------------------------

def _alloccomp() -> list[V]:
    out = []
    d = "type(vec) :: x\ninteger :: i"
    out.append(V("alloccomp", "whole", "map(tofrom:) of a structure with an "
                 "allocatable array component: the component's data is mapped "
                 "with it (deep copy)", [C_ALLOCCOMP, C_DEFMAPPER],
                 types=VEC, decls=d, body=VEC_SETUP + """
                 !$omp target teams distribute parallel do map(tofrom: x)
                 do i = 1, n
                   x%a(i) = 3 * x%a(i) + x%n
                 end do
                 r1 = sum(x%a)
                 r2 = x%a(n)
                 """, checks=[("r1", 3 * S1 + N * N), ("r2", 3 * N + N)]))
    out.append(V("alloccomp", "parent-and-comp", "map(to:) of the structure "
                 "and map(tofrom:) of its allocatable component on one "
                 "construct", [C_MAP, C_ALLOCCOMP,
                               "OpenMP 5.2 §5.8.3 p.156 l.6-7"],
                 types=VEC, decls=d, body=VEC_SETUP + """
                 !$omp target teams distribute parallel do map(to: x) map(tofrom: x%a)
                 do i = 1, n
                   x%a(i) = x%a(i) + 7
                 end do
                 r1 = sum(x%a)
                 """, checks=[("r1", S1 + 7 * N)]))
    out.append(V("alloccomp", "comp-only", "map(tofrom:) of the allocatable "
                 "component alone", [C_MAP, C_STRUCTELT],
                 types=VEC, decls=d, body=VEC_SETUP + """
                 !$omp target teams distribute parallel do map(tofrom: x%a)
                 do i = 1, n
                   x%a(i) = 2 * x%a(i)
                 end do
                 r1 = sum(x%a)
                 """, checks=[("r1", 2 * S1)]))
    out.append(V("alloccomp", "enterexit", "target enter data of the "
                 "structure (deep copy), a target region with an implicit map, "
                 "target exit data map(from:)", [C_ENTER, C_ALLOCCOMP],
                 types=VEC, decls=d, body=VEC_SETUP + """
                 !$omp target enter data map(to: x)
                 !$omp target teams distribute parallel do
                 do i = 1, n
                   x%a(i) = 5 * x%a(i)
                 end do
                 !$omp target exit data map(from: x)
                 r1 = sum(x%a)
                 """, checks=[("r1", 5 * S1)]))
    out.append(V("alloccomp", "array", "an array of structures, each with an "
                 "allocatable component, mapped whole",
                 [C_ALLOCCOMP, C_ARRAYELTS], types=VEC,
                 decls="type(vec) :: v(4)\ninteger :: i, k",
                 body="""
                 do k = 1, 4
                   allocate(v(k)%a(n))
                   v(k)%n = n
                   do i = 1, n
                     v(k)%a(i) = k * i
                   end do
                 end do
                 !$omp target teams distribute parallel do collapse(2) map(tofrom: v)
                 do k = 1, 4
                   do i = 1, n
                     v(k)%a(i) = v(k)%a(i) + k
                   end do
                 end do
                 r1 = 0
                 do k = 1, 4
                   r1 = r1 + sum(v(k)%a)
                 end do
                 """, checks=[("r1", 10 * (S1 + N))]))
    out.append(V("alloccomp", "twolevel", "an allocatable array of structures "
                 "with allocatable components inside a structure (two levels "
                 "of deep copy)", [C_ALLOCCOMP, C_ARRAYELTS],
                 types="""
                 type inner
                   integer, allocatable :: b(:)
                 end type inner
                 type outer
                   type(inner), allocatable :: c(:)
                   integer :: m = 0
                 end type outer
                 """, decls="type(outer) :: o\ninteger :: i, j",
                 body="""
                 allocate(o%c(3))
                 o%m = 3
                 do j = 1, 3
                   allocate(o%c(j)%b(n))
                   do i = 1, n
                     o%c(j)%b(i) = 100 * j + i
                   end do
                 end do
                 !$omp target teams distribute parallel do collapse(2) map(tofrom: o)
                 do j = 1, 3
                   do i = 1, n
                     o%c(j)%b(i) = 2 * o%c(j)%b(i)
                   end do
                 end do
                 r1 = 0
                 do j = 1, 3
                   r1 = r1 + sum(o%c(j)%b)
                 end do
                 """, checks=[("r1", 2 * (600 * N + 3 * S1))]))
    out.append(V("alloccomp", "scalar", "an allocatable scalar component",
                 [C_ALLOCCOMP],
                 types="""
                 type sc
                   integer, allocatable :: s
                   integer :: k = 0
                 end type sc
                 """, decls="type(sc) :: x",
                 body="""
                 allocate(x%s)
                 x%s = 5
                 x%k = 3
                 !$omp target map(tofrom: x)
                 x%s = x%s * 10 + x%k
                 !$omp end target
                 r1 = x%s
                 """, checks=[("r1", 53)]))
    out.append(V("alloccomp", "update", "target update from(x%a) of an "
                 "allocatable component of a structure entered by target "
                 "enter data", [C_UPDATE, C_ALLOCCOMP, C_ENTER],
                 types=VEC, decls=d, body=VEC_SETUP + """
                 !$omp target enter data map(to: x)
                 !$omp target teams distribute parallel do
                 do i = 1, n
                   x%a(i) = -x%a(i)
                 end do
                 !$omp target update from(x%a)
                 r1 = sum(x%a)
                 !$omp target exit data map(release: x)
                 """, checks=[("r1", -S1)]))
    return out


# --- F03 pointer components -----------------------------------------------------------

PV = """
type pv
  integer :: n = 0
  integer, pointer :: p(:) => null()
end type pv
"""


def _ptrcomp() -> list[V]:
    out = []
    d = "type(pv) :: x\ninteger, target :: buf(n)\ninteger :: i"
    setup = "do i = 1, n\n  buf(i) = i\nend do\nx%n = n\nx%p => buf\n"
    out.append(V("ptrcomp", "parent-and-comp", "map(to:) of a structure and "
                 "map(tofrom:) of its pointer component: the target is mapped "
                 "and the device pointer attached",
                 [C_MAP, "OpenMP 5.2 §5.8.3 p.152 l.1-16 (pointer list items, "
                  "attached pointers)"], types=PV, decls=d,
                 body=setup + """
                 !$omp target teams distribute parallel do map(to: x) map(tofrom: x%p)
                 do i = 1, n
                   x%p(i) = x%p(i) + 100
                 end do
                 r1 = sum(buf)
                 r2 = buf(n)
                 """, checks=[("r1", S1 + 100 * N), ("r2", N + 100)]))
    out.append(V("ptrcomp", "comp-only", "map(tofrom:) of a pointer "
                 "component alone", [C_MAP, C_STRUCTELT], types=PV, decls=d,
                 body=setup + """
                 !$omp target teams distribute parallel do map(tofrom: x%p)
                 do i = 1, n
                   x%p(i) = 2 * x%p(i)
                 end do
                 r1 = sum(buf)
                 """, checks=[("r1", 2 * S1)]))
    out.append(V("ptrcomp", "enterexit", "target enter data of the structure, "
                 "then of its pointer component (attach), a target region, exit "
                 "data from the component, release of the structure",
                 [C_ENTER, "OpenMP 5.2 §5.8.3 p.152 l.5-16",
                  "OpenMP 5.2 §5.8.3 p.156 l.27-30"], types=PV, decls=d,
                 body=setup + """
                 !$omp target enter data map(to: x)
                 !$omp target enter data map(to: x%p)
                 !$omp target teams distribute parallel do
                 do i = 1, n
                   x%p(i) = 3 * x%p(i)
                 end do
                 !$omp target exit data map(from: x%p)
                 !$omp target exit data map(release: x)
                 r1 = sum(buf)
                 """, checks=[("r1", 3 * S1)]))
    out.append(V("ptrcomp", "section-target", "a pointer component associated "
                 "with an array section buf(9:24), map(tofrom: x%p)",
                 [C_MAP, "OpenMP 5.2 §5.8.3 p.152 l.1-4"], types=PV, decls=d,
                 body="""
                 do i = 1, n
                   buf(i) = i
                 end do
                 x%n = 16
                 x%p => buf(9:24)
                 !$omp target teams distribute parallel do map(tofrom: x%p)
                 do i = 1, 16
                   x%p(i) = x%p(i) + 1000
                 end do
                 r1 = sum(buf)
                 r2 = buf(9)
                 """, checks=[("r1", S1 + 16000), ("r2", 1009)]))
    return out


# --- F04 sections of components -------------------------------------------------------

def _section() -> list[V]:
    out = []
    d = "type(vec) :: x\ninteger :: i"
    out.append(V("section", "alloc", "map(tofrom: x%a(9:40)): a section of an "
                 "allocatable component", [C_SECTION, C_STRUCTELT],
                 types=VEC, decls=d, body=VEC_SETUP + """
                 !$omp target teams distribute parallel do map(tofrom: x%a(9:40))
                 do i = 9, 40
                   x%a(i) = x%a(i) + 1000
                 end do
                 r1 = sum(x%a)
                 r2 = x%a(8)
                 """, checks=[("r1", S1 + 32000), ("r2", 8)]))
    out.append(V("section", "fixed", "map(tofrom: s%b(17:48)): a section of a "
                 "fixed-size array component", [C_SECTION, C_STRUCTELT],
                 types="type fs\n  integer :: b(n) = 0\n  integer :: k = 0\n"
                 "end type fs", decls="type(fs) :: s\ninteger :: i",
                 body="""
                 do i = 1, n
                   s%b(i) = i
                 end do
                 !$omp target teams distribute parallel do map(tofrom: s%b(17:48))
                 do i = 17, 48
                   s%b(i) = 2 * s%b(i)
                 end do
                 r1 = sum(s%b)
                 """, checks=[("r1", S1 + sum(range(17, 49)))]))
    out.append(V("section", "update", "target update from(x%a(1:16)) after "
                 "the device changed every element, then exit data from",
                 [C_UPDATE, C_SECTION, C_ENTER], types=VEC, decls=d,
                 body=VEC_SETUP + """
                 !$omp target enter data map(to: x)
                 !$omp target teams distribute parallel do
                 do i = 1, n
                   x%a(i) = 2 * x%a(i)
                 end do
                 !$omp target update from(x%a(1:16))
                 r1 = sum(x%a(1:16))
                 !$omp target exit data map(from: x)
                 r2 = sum(x%a)
                 """, checks=[("r1", 2 * 136), ("r2", 2 * S1)]))
    out.append(V("section", "element", "map(tofrom: v(2)%a(5:20)): a section "
                 "of the allocatable component of an array element",
                 [C_SECTION], types=VEC,
                 decls="type(vec) :: v(3)\ninteger :: i, k",
                 body="""
                 do k = 1, 3
                   allocate(v(k)%a(n))
                   v(k)%n = n
                   do i = 1, n
                     v(k)%a(i) = i
                   end do
                 end do
                 !$omp target teams distribute parallel do map(tofrom: v(2)%a(5:20))
                 do i = 5, 20
                   v(2)%a(i) = v(2)%a(i) + 50
                 end do
                 r1 = sum(v(2)%a)
                 r2 = sum(v(1)%a)
                 """, checks=[("r1", S1 + 16 * 50), ("r2", S1)]))
    out.append(V("section", "nested", "map(tofrom: o%in%v(3:30)): a section of "
                 "an allocatable component of a nested structure", [C_SECTION],
                 types="""
                 type in_t
                   integer, allocatable :: v(:)
                 end type in_t
                 type out_t
                   type(in_t) :: in
                   integer :: tag = 0
                 end type out_t
                 """, decls="type(out_t) :: o\ninteger :: i",
                 body="""
                 allocate(o%in%v(n))
                 do i = 1, n
                   o%in%v(i) = i
                 end do
                 !$omp target teams distribute parallel do map(tofrom: o%in%v(3:30))
                 do i = 3, 30
                   o%in%v(i) = 3 * o%in%v(i)
                 end do
                 r1 = sum(o%in%v)
                 """, checks=[("r1", S1 + 2 * sum(range(3, 31)))]))
    return out


# --- F05 declare mapper ----------------------------------------------------------------

MAPPER = "!$omp declare mapper(vec :: v) map(tofrom: v, v%a(1:v%n))"


def _mapper() -> list[V]:
    out = []
    d = "type(vec) :: x\ninteger :: i"
    out.append(V("mapper", "default", "a default user-defined mapper for a "
                 "type with an allocatable component", [C_MAPPER, C_MAP],
                 types=VEC + MAPPER, decls=d, body=VEC_SETUP + """
                 !$omp target teams distribute parallel do map(tofrom: x)
                 do i = 1, n
                   x%a(i) = x%a(i) + i
                 end do
                 r1 = sum(x%a)
                 """, checks=[("r1", 2 * S1)]))
    out.append(V("mapper", "named", "a named mapper used by "
                 "map(mapper(deep), tofrom: x)", [C_MAPPER,
                                                  "OpenMP 5.2 §5.8.2"],
                 types=VEC + "!$omp declare mapper(deep: vec :: v) "
                 "map(tofrom: v, v%a(1:v%n))", decls=d,
                 body=VEC_SETUP + """
                 !$omp target teams distribute parallel do map(mapper(deep), tofrom: x)
                 do i = 1, n
                   x%a(i) = x%a(i) * x%n
                 end do
                 r1 = sum(x%a)
                 """, checks=[("r1", N * S1)]))
    out.append(V("mapper", "array", "an array of structures mapped through "
                 "the default user-defined mapper (each element by the mapper)",
                 [C_MAPPER, "OpenMP 5.2 §5.8.3 p.151 l.26-28"],
                 types=VEC + MAPPER, decls="type(vec) :: v(3)\ninteger :: i, k",
                 body="""
                 do k = 1, 3
                   allocate(v(k)%a(n))
                   v(k)%n = n
                   do i = 1, n
                     v(k)%a(i) = i
                   end do
                 end do
                 !$omp target teams distribute parallel do collapse(2) map(tofrom: v)
                 do k = 1, 3
                   do i = 1, n
                     v(k)%a(i) = v(k)%a(i) + k
                   end do
                 end do
                 r1 = sum(v(1)%a) + sum(v(2)%a) + sum(v(3)%a)
                 """, checks=[("r1", 3 * S1 + 6 * N)]))
    out.append(V("mapper", "update", "target update from(x) through the "
                 "default user-defined mapper (the component's data comes "
                 "back)", [C_MAPPER, C_UPDATE,
                           "OpenMP 5.2 §5.9 p.165-166 (motion clauses use "
                           "mappers)"],
                 types=VEC + MAPPER, decls=d, body=VEC_SETUP + """
                 !$omp target enter data map(to: x)
                 !$omp target teams distribute parallel do
                 do i = 1, n
                   x%a(i) = x%a(i) + 5
                 end do
                 !$omp target update from(x)
                 r1 = sum(x%a)
                 !$omp target exit data map(release: x)
                 """, checks=[("r1", S1 + 5 * N)]))
    out.append(V("mapper", "implicit", "a structure referenced in a target "
                 "region without a map clause: the implicit map uses the "
                 "default user-defined mapper", [C_MAPPER, C_IMPLICIT,
                                                 C_MAP],
                 types=VEC + MAPPER, decls=d, body=VEC_SETUP + """
                 !$omp target teams distribute parallel do
                 do i = 1, n
                   x%a(i) = 3 * x%a(i)
                 end do
                 r1 = sum(x%a)
                 """, checks=[("r1", 3 * S1)]))
    out.append(V("mapper", "chained", "a mapper of an outer type whose map of "
                 "an inner component uses the inner type's mapper",
                 [C_MAPPER, "OpenMP 5.2 §5.8.8 p.164 l.1-2 (mapper map "
                  "clauses are subject to mappers in scope)"],
                 types="""
                 type inner_t
                   integer :: m = 0
                   integer, allocatable :: b(:)
                 end type inner_t
                 type outer_t
                   type(inner_t) :: in
                   integer :: k = 0
                 end type outer_t
                 !$omp declare mapper(inner_t :: w) map(tofrom: w, w%b(1:w%m))
                 !$omp declare mapper(outer_t :: o) map(tofrom: o, o%in)
                 """, decls="type(outer_t) :: o\ninteger :: i",
                 body="""
                 allocate(o%in%b(n))
                 o%in%m = n
                 o%k = 10
                 do i = 1, n
                   o%in%b(i) = i
                 end do
                 !$omp target teams distribute parallel do map(tofrom: o)
                 do i = 1, n
                   o%in%b(i) = o%in%b(i) + o%k
                 end do
                 r1 = sum(o%in%b)
                 """, checks=[("r1", S1 + 10 * N)]))
    return out


# --- F06 parameterized derived types ---------------------------------------------------

LV = """
type lv(m)
  integer, len :: m
  integer :: a(m)
end type lv
"""


def _pdt() -> list[V]:
    out = []
    out.append(V("pdt", "kind", "a derived type with a kind type parameter "
                 "(integer(8) components), map(tofrom:)",
                 [C_MAP, "OpenMP 5.2 §5.8.3 p.155 l.5-7 (same type, type "
                  "parameters and rank)"],
                 types="""
                 type kv(k)
                   integer, kind :: k = 4
                   integer(k) :: v(8)
                 end type kv
                 """, decls="type(kv(8)) :: x\ninteger :: i",
                 body="""
                 do i = 1, 8
                   x%v(i) = int(i, 8) * 1000000000_8
                 end do
                 !$omp target map(tofrom: x)
                 do i = 1, 8
                   x%v(i) = x%v(i) + i
                 end do
                 !$omp end target
                 r1 = int(x%v(8) - 8000000000_8)
                 r2 = int(mod(sum(x%v), 1000000_8))
                 """, checks=[("r1", 8), ("r2", 36)]))
    out.append(V("pdt", "len", "a derived type with a length type parameter "
                 "(constant), its value read on the device",
                 [C_MAP, "OpenMP 5.2 §5.8.3 p.155 l.5-7"], types=LV,
                 decls="type(lv(16)) :: x\ninteger :: i",
                 body="""
                 do i = 1, 16
                   x%a(i) = i
                 end do
                 !$omp target map(tofrom: x) map(from: r1)
                 r1 = x%m
                 do i = 1, x%m
                   x%a(i) = x%a(i) * x%a(i)
                 end do
                 !$omp end target
                 r2 = sum(x%a)
                 """, checks=[("r1", 16),
                              ("r2", sum(i * i for i in range(1, 17)))]))
    out.append(V("pdt", "deferred", "an allocatable scalar of a derived type "
                 "with a deferred length type parameter (allocate(lv(32) :: y))",
                 [C_MAP, "OpenMP 5.2 §5.8.3 p.155 l.5-7"], types=LV,
                 decls="type(lv(:)), allocatable :: y\ninteger :: i",
                 body="""
                 allocate(lv(32) :: y)
                 do i = 1, 32
                   y%a(i) = i
                 end do
                 !$omp target map(tofrom: y)
                 do i = 1, 32
                   y%a(i) = y%a(i) + y%m
                 end do
                 !$omp end target
                 r1 = sum(y%a)
                 """, checks=[("r1", 528 + 32 * 32)]))
    out.append(V("pdt", "array", "an array of a parameterized derived type in "
                 "a target teams distribute parallel do", [C_MAP, C_ARRAYELTS],
                 types=LV, decls="type(lv(4)) :: arr(n)\ninteger :: i, j",
                 body="""
                 do j = 1, n
                   arr(j)%a = j
                 end do
                 !$omp target teams distribute parallel do collapse(2) map(tofrom: arr)
                 do j = 1, n
                   do i = 1, 4
                     arr(j)%a(i) = arr(j)%a(i) + i
                   end do
                 end do
                 r1 = 0
                 do j = 1, n
                   r1 = r1 + sum(arr(j)%a)
                 end do
                 """, checks=[("r1", 4 * S1 + 10 * N)]))
    out.append(V("pdt", "kindlen", "a derived type with a kind and a length "
                 "type parameter", [C_MAP, "OpenMP 5.2 §5.8.3 p.155 l.5-7"],
                 types="""
                 type kl(k, m)
                   integer, kind :: k = 4
                   integer, len :: m
                   integer(k) :: a(m)
                 end type kl
                 """, decls="type(kl(8, 10)) :: x\ninteger :: i",
                 body="""
                 do i = 1, 10
                   x%a(i) = i
                 end do
                 !$omp target map(tofrom: x)
                 do i = 1, x%m
                   x%a(i) = 2 * x%a(i) + 1
                 end do
                 !$omp end target
                 r1 = int(sum(x%a))
                 """, checks=[("r1", 2 * 55 + 10)]))
    return out


# --- F07 type extension ----------------------------------------------------------------

BASE_EXT = """
type base
  integer :: a = 0
end type base
type, extends(base) :: ext
  integer :: b = 0
end type ext
"""


def _extends() -> list[V]:
    out = []
    out.append(V("extends", "whole", "an extended type mapped whole: "
                 "inherited and own components, and the parent component",
                 [C_MAP, C_DEFMAPPER], types=BASE_EXT, decls="type(ext) :: e",
                 body="""
                 e%a = 5
                 e%b = 7
                 !$omp target map(tofrom: e)
                 e%b = e%a * 2 + e%b
                 e%a = e%a + 1
                 e%base%a = e%base%a + 10
                 !$omp end target
                 r1 = e%a
                 r2 = e%b
                 """, checks=[("r1", 16), ("r2", 17)]))
    out.append(V("extends", "parent-comp", "map(tofrom: e%base): the parent "
                 "component as a structure element", [C_MAP, C_STRUCTELT],
                 types=BASE_EXT, decls="type(ext) :: e",
                 body="""
                 e%a = 5
                 e%b = 7
                 !$omp target map(tofrom: e%base)
                 e%base%a = e%base%a * 3
                 !$omp end target
                 r1 = e%a
                 r2 = e%b
                 """, checks=[("r1", 15), ("r2", 7)]))
    out.append(V("extends", "alloc-parent", "an array of an extended type "
                 "whose parent has an allocatable component",
                 [C_ALLOCCOMP, C_ARRAYELTS],
                 types="""
                 type base2
                   integer, allocatable :: w(:)
                 end type base2
                 type, extends(base2) :: ext2
                   integer :: s = 0
                 end type ext2
                 """, decls="type(ext2) :: arr(4)\ninteger :: i, k",
                 body="""
                 do k = 1, 4
                   allocate(arr(k)%w(n))
                   arr(k)%w = k
                   arr(k)%s = 0
                 end do
                 !$omp target teams distribute parallel do map(tofrom: arr)
                 do k = 1, 4
                   do i = 1, n
                     arr(k)%w(i) = arr(k)%w(i) + i
                     arr(k)%s = arr(k)%s + arr(k)%w(i)
                   end do
                 end do
                 r1 = sum(arr%s)
                 r2 = arr(4)%w(n)
                 """, checks=[("r1", N * 10 + 4 * S1), ("r2", 4 + N)]))
    out.append(V("extends", "chain", "a three-level extension chain: "
                 "components by inherited names and by parent components",
                 [C_MAP], types="""
                 type lvl1
                   integer :: a = 0
                 end type lvl1
                 type, extends(lvl1) :: lvl2
                   integer :: b = 0
                 end type lvl2
                 type, extends(lvl2) :: lvl3
                   integer :: c = 0
                 end type lvl3
                 """, decls="type(lvl3) :: t",
                 body="""
                 t%a = 1
                 t%b = 2
                 t%c = 3
                 !$omp target map(tofrom: t)
                 t%c = t%a + t%b + t%c
                 t%lvl2%lvl1%a = 10
                 t%lvl2%b = t%b * 4
                 !$omp end target
                 r1 = t%a
                 r2 = t%b
                 r3 = t%c
                 """, checks=[("r1", 10), ("r2", 8), ("r3", 6)]))
    out.append(V("extends", "aos", "an array of an extended type in a target "
                 "teams distribute parallel do", [C_MAP, C_ARRAYELTS],
                 types=BASE_EXT, decls="type(ext) :: q(n)\ninteger :: i",
                 body="""
                 do i = 1, n
                   q(i)%a = i
                   q(i)%b = 0
                 end do
                 !$omp target teams distribute parallel do map(tofrom: q)
                 do i = 1, n
                   q(i)%b = q(i)%a * q(i)%a
                   q(i)%a = -q(i)%a
                 end do
                 r1 = sum(q%b)
                 r2 = sum(q%a)
                 """, checks=[("r1", S2), ("r2", -S1)]))
    return out


# --- F08 type-bound procedures as device routines --------------------------------------

def _tbp() -> list[V]:
    out = []
    dt = "!$omp declare target"
    vec3 = f"""
    type vec3
      integer :: x = 0, y = 0, z = 0
    contains
      procedure :: norm2 => v_norm2
      procedure, nopass :: twice => v_twice
      procedure :: scale_i, scale_ij
      generic :: scale => scale_i, scale_ij
    end type vec3
    """
    vprocs = f"""
    integer function v_norm2(s)
      {dt}
      class(vec3), intent(in) :: s
      v_norm2 = s%x * s%x + s%y * s%y + s%z * s%z
    end function v_norm2
    integer function v_twice(k)
      {dt}
      integer, intent(in) :: k
      v_twice = 2 * k
    end function v_twice
    subroutine scale_i(s, k)
      {dt}
      class(vec3), intent(inout) :: s
      integer, intent(in) :: k
      s%x = s%x * k
      s%y = s%y * k
      s%z = s%z * k
    end subroutine scale_i
    subroutine scale_ij(s, a, b)
      {dt}
      class(vec3), intent(inout) :: s
      integer, intent(in) :: a, b
      s%x = s%x * a * b
      s%y = s%y * a * b
      s%z = s%z * a * b
    end subroutine scale_ij
    """
    vset = "v%x = 1\nv%y = 2\nv%z = 3\n"
    out.append(V("tbp", "function", "a type-bound function called on the "
                 "device (declare target)", [C_TBP, C_DT], types=vec3,
                 procs=vprocs, decls="type(vec3) :: v",
                 body=vset + "!$omp target map(tofrom: v) map(from: r1)\n"
                 "r1 = v%norm2()\n!$omp end target\n",
                 checks=[("r1", 14)]))
    out.append(V("tbp", "nopass", "a NOPASS type-bound function called on the "
                 "device", [C_TBP, C_DT], types=vec3, procs=vprocs,
                 decls="type(vec3) :: v",
                 body=vset + "!$omp target map(tofrom: v) map(from: r1)\n"
                 "r1 = v%twice(21)\n!$omp end target\n",
                 checks=[("r1", 42)]))
    out.append(V("tbp", "generic", "a generic type-bound binding with two "
                 "specific subroutines, both called on the device",
                 [C_TBP, C_DT], types=vec3, procs=vprocs,
                 decls="type(vec3) :: v",
                 body=vset + """
                 !$omp target map(tofrom: v)
                 call v%scale(3)
                 call v%scale(2, 5)
                 !$omp end target
                 r1 = v%x + v%y + v%z
                 """, checks=[("r1", (1 + 2 + 3) * 30)]))
    ov_types = """
    type base_t
      integer :: a = 0
    contains
      procedure :: val => base_val
    end type base_t
    type, extends(base_t) :: ext_t
      integer :: b = 0
    contains
      procedure :: val => ext_val
    end type ext_t
    """
    ov_procs = f"""
    integer function base_val(s)
      {dt}
      class(base_t), intent(in) :: s
      base_val = s%a
    end function base_val
    integer function ext_val(s)
      {dt}
      class(ext_t), intent(in) :: s
      ext_val = s%a * 100 + s%b
    end function ext_val
    """
    out.append(V("tbp", "override", "an overridden binding called on objects "
                 "of the base and the extended type, and through the parent "
                 "component", [C_TBP, C_DT], types=ov_types, procs=ov_procs,
                 decls="type(base_t) :: b0\ntype(ext_t) :: e",
                 body="""
                 b0%a = 3
                 e%a = 4
                 e%b = 5
                 !$omp target map(tofrom: b0, e) map(from: r1, r2, r3)
                 r1 = b0%val()
                 r2 = e%val()
                 r3 = e%base_t%val()
                 !$omp end target
                 """, checks=[("r1", 3), ("r2", 405), ("r3", 4)]))
    out.append(V("tbp", "loop", "a type-bound subroutine called on each "
                 "element of an array in a target teams distribute parallel do",
                 [C_TBP, C_DT],
                 types="""
                 type cnt
                   integer :: c = 0
                 contains
                   procedure :: step => cnt_step
                 end type cnt
                 """, procs=f"""
                 subroutine cnt_step(s, k)
                   {dt}
                   class(cnt), intent(inout) :: s
                   integer, intent(in) :: k
                   s%c = s%c + k
                 end subroutine cnt_step
                 """, decls="type(cnt) :: p(n)\ninteger :: i",
                 body="""
                 !$omp target teams distribute parallel do map(tofrom: p)
                 do i = 1, n
                   call p(i)%step(i)
                   call p(i)%step(1)
                 end do
                 r1 = sum(p%c)
                 """, checks=[("r1", S1 + N)]))
    out.append(V("tbp", "argument", "a type-bound function with a second "
                 "derived-type argument", [C_TBP, C_DT],
                 types="""
                 type acc_t
                   integer :: v(8) = 0
                 contains
                   procedure :: dot => a_dot
                 end type acc_t
                 """, procs=f"""
                 integer function a_dot(s, o)
                   {dt}
                   class(acc_t), intent(in) :: s
                   type(acc_t), intent(in) :: o
                   integer :: i
                   a_dot = 0
                   do i = 1, 8
                     a_dot = a_dot + s%v(i) * o%v(i)
                   end do
                 end function a_dot
                 """, decls="type(acc_t) :: u, w\ninteger :: i",
                 body="""
                 do i = 1, 8
                   u%v(i) = i
                   w%v(i) = 2
                 end do
                 !$omp target map(tofrom: u, w) map(from: r1)
                 r1 = u%dot(w)
                 !$omp end target
                 """, checks=[("r1", 72)]))
    out.append(V("tbp", "operator", "a type-bound generic operator(+) used in "
                 "device code", [C_TBP, C_DT],
                 types="""
                 type v2
                   integer :: x = 0, y = 0
                 contains
                   procedure :: add => v2_add
                   generic :: operator(+) => add
                 end type v2
                 """, procs=f"""
                 function v2_add(a, b) result(c)
                   {dt}
                   class(v2), intent(in) :: a
                   type(v2), intent(in) :: b
                   type(v2) :: c
                   c%x = a%x + b%x
                   c%y = a%y + b%y
                 end function v2_add
                 """, decls="type(v2) :: a, b, c",
                 body="""
                 a%x = 1
                 a%y = 2
                 b%x = 10
                 b%y = 20
                 !$omp target map(tofrom: a, b, c)
                 c = a + b
                 !$omp end target
                 r1 = c%x * 100 + c%y
                 """, checks=[("r1", 1122)]))
    out.append(V("tbp", "nested-call", "a type-bound function that calls "
                 "another binding of the same object", [C_TBP, C_DT],
                 types="""
                 type pair
                   integer :: v(2) = 0
                 contains
                   procedure :: part => p_part
                   procedure :: total => p_total
                 end type pair
                 """, procs=f"""
                 integer function p_part(s, k)
                   {dt}
                   class(pair), intent(in) :: s
                   integer, intent(in) :: k
                   p_part = s%v(k) * k
                 end function p_part
                 integer function p_total(s)
                   {dt}
                   class(pair), intent(in) :: s
                   p_total = s%part(1) + s%part(2)
                 end function p_total
                 """, decls="type(pair) :: q",
                 body="""
                 q%v = [5, 7]
                 !$omp target map(tofrom: q) map(from: r1)
                 r1 = q%total()
                 !$omp end target
                 """, checks=[("r1", 19)]))
    return out


# --- F09 polymorphic dummy arguments, SELECT TYPE, dispatch ----------------------------

POLY_TYPES = """
type base_t
  integer :: a = 0
end type base_t
type, extends(base_t) :: ext1
  integer :: u = 0
end type ext1
type, extends(base_t) :: ext2
  integer :: v = 0
end type ext2
"""

BUMP = """
subroutine bump(s)
  !$omp declare target
  class(base_t), intent(inout) :: s
  select type (s)
  type is (ext1)
    s%u = s%u + 10
  type is (ext2)
    s%v = s%v + 100
  class default
    s%a = -1
  end select
end subroutine bump
"""

SHAPES = """
type, abstract :: shape
  integer :: id = 0
contains
  procedure(area_if), deferred :: area
end type shape
abstract interface
  integer function area_if(s)
    import :: shape
    class(shape), intent(in) :: s
  end function area_if
end interface
type, extends(shape) :: sq
  integer :: side = 0
contains
  procedure :: area => sq_area
end type sq
type, extends(shape) :: rect
  integer :: w = 0, h = 0
contains
  procedure :: area => rect_area
end type rect
"""


def _shape_procs(dt: str = "!$omp declare target") -> str:
    return f"""
    integer function sq_area(s)
      {dt}
      class(sq), intent(in) :: s
      sq_area = s%side * s%side
    end function sq_area
    integer function rect_area(s)
      {dt}
      class(rect), intent(in) :: s
      rect_area = s%w * s%h
    end function rect_area
    integer function area_of(s)
      {dt}
      class(shape), intent(in) :: s
      area_of = s%area()
    end function area_of
    """


C_SELECT = ("OpenMP 5.2 §5.3 p.107 l.17-19 (SELECT TYPE in OpenMP regions); "
            "Fortran 2018 11.1.11 (SELECT TYPE)")


def _poly() -> list[V]:
    out = []
    out.append(V("poly", "select-type", "a declare target subroutine with a "
                 "CLASS(base_t) dummy and SELECT TYPE, called on the device "
                 "with mapped non-polymorphic objects of three types",
                 [C_TBP, C_DT, C_SELECT], types=POLY_TYPES, procs=BUMP,
                 decls="type(ext1) :: e1\ntype(ext2) :: e2\ntype(base_t) :: b0",
                 body="""
                 !$omp target map(tofrom: e1, e2, b0)
                 call bump(e1)
                 call bump(e2)
                 call bump(b0)
                 !$omp end target
                 r1 = e1%u
                 r2 = e2%v
                 r3 = b0%a
                 """, checks=[("r1", 10), ("r2", 100), ("r3", -1)]))
    out.append(V("poly", "dispatch", "dynamic dispatch of a deferred binding "
                 "(abstract type) through a CLASS(shape) dummy on the device",
                 [C_TBP, C_DT], types=SHAPES, procs=_shape_procs(),
                 decls="type(sq) :: q\ntype(rect) :: rr",
                 body="""
                 q%side = 3
                 rr%w = 4
                 rr%h = 5
                 !$omp target map(tofrom: q, rr) map(from: r1)
                 r1 = area_of(q) + area_of(rr)
                 !$omp end target
                 """, checks=[("r1", 29)]))
    out.append(V("poly", "dispatch-loop", "dynamic dispatch on every element "
                 "of an array in a target teams distribute parallel do with a "
                 "reduction", [C_TBP, C_DT], types=SHAPES,
                 procs=_shape_procs(),
                 decls="type(sq) :: qs(n)\ninteger :: i, tot",
                 body="""
                 do i = 1, n
                   qs(i)%side = i
                 end do
                 tot = 0
                 !$omp target teams distribute parallel do map(to: qs) reduction(+: tot)
                 do i = 1, n
                   tot = tot + area_of(qs(i))
                 end do
                 r1 = tot
                 """, checks=[("r1", S2)]))
    out.append(V("poly", "class-is", "SELECT TYPE with TYPE IS and CLASS IS "
                 "guards on the device", [C_DT, C_SELECT], types=POLY_TYPES,
                 procs="""
                 subroutine tag(s, t)
                   !$omp declare target
                   class(base_t), intent(in) :: s
                   integer, intent(out) :: t
                   t = 0
                   select type (s)
                   class is (base_t)
                     t = 1
                   type is (ext2)
                     t = 2
                   end select
                 end subroutine tag
                 """,
                 decls="type(ext1) :: e1\ntype(ext2) :: e2\ntype(base_t) :: b0\n"
                       "integer :: t1, t2, t3",
                 body="""
                 !$omp target map(tofrom: e1, e2, b0) map(from: t1, t2, t3)
                 call tag(e1, t1)
                 call tag(e2, t2)
                 call tag(b0, t3)
                 !$omp end target
                 r1 = 100 * t1 + 10 * t2 + t3
                 """, checks=[("r1", 121)]))
    out.append(V("poly", "parent-call", "an overriding binding that calls the "
                 "parent's binding through the parent component, dispatched "
                 "through a CLASS(base_t) dummy", [C_TBP, C_DT],
                 types="""
                 type base_t
                   integer :: a = 0
                 contains
                   procedure :: val => base_val
                 end type base_t
                 type, extends(base_t) :: ext1
                   integer :: u = 0
                 contains
                   procedure :: val => ext1_val
                 end type ext1
                 """, procs="""
                 integer function base_val(s)
                   !$omp declare target
                   class(base_t), intent(in) :: s
                   base_val = s%a
                 end function base_val
                 integer function ext1_val(s)
                   !$omp declare target
                   class(ext1), intent(in) :: s
                   ext1_val = s%base_t%val() + s%u * 10
                 end function ext1_val
                 integer function get_val(s)
                   !$omp declare target
                   class(base_t), intent(in) :: s
                   get_val = s%val()
                 end function get_val
                 """, decls="type(ext1) :: e1\ntype(base_t) :: b0",
                 body="""
                 e1%a = 3
                 e1%u = 4
                 b0%a = 7
                 !$omp target map(tofrom: e1, b0) map(from: r1)
                 r1 = get_val(e1) * 100 + get_val(b0)
                 !$omp end target
                 """, checks=[("r1", 4307)]))
    out.append(V("poly", "pointer", "a polymorphic pointer associated on the "
                 "device with a TARGET dummy, then a dispatched call",
                 [C_TBP, C_DT], types=SHAPES, procs=_shape_procs() + """
                 integer function area_ptr(q)
                   !$omp declare target
                   type(sq), target, intent(in) :: q
                   class(shape), pointer :: sp
                   sp => q
                   area_ptr = sp%area()
                 end function area_ptr
                 """, decls="type(sq) :: q",
                 body="""
                 q%side = 6
                 !$omp target map(tofrom: q) map(from: r1)
                 r1 = area_ptr(q)
                 !$omp end target
                 """, checks=[("r1", 36)]))
    out.append(V("poly", "mapped-class", "a CLASS(base_t), ALLOCATABLE object "
                 "with dynamic type ext1 mapped by map(tofrom:)",
                 [C_POLY60, C_DT], types=POLY_TYPES, procs=BUMP,
                 decls="class(base_t), allocatable :: pa",
                 body="""
                 allocate(ext1 :: pa)
                 pa%a = 1
                 !$omp target map(tofrom: pa)
                 call bump(pa)
                 !$omp end target
                 r1 = -1
                 select type (pa)
                 type is (ext1)
                   r1 = pa%u
                 end select
                 """, checks=[("r1", 10)], legality="unspecified",
                 why="OpenMP 6.0 §7.9.6 p.288 l.10: a map list item of "
                     "polymorphic type (Fortran): the behavior is unspecified; "
                     "OpenMP 6.0 §B.2 p.898 l.18-19 (5.2 to 6.0: restrictions "
                     "changed and behavior clarified for polymorphic types)"))
    out.append(V("poly", "firstprivate-class", "firstprivate of a "
                 "CLASS(base_t) dummy argument on a target construct",
                 ["OpenMP 6.0 §7.5.4 p.228 l.8-9 (firstprivate on target of "
                  "a polymorphic variable: unspecified)"], types=POLY_TYPES,
                 procs="""
                 subroutine probe(s, r)
                   class(base_t), intent(in) :: s
                   integer, intent(out) :: r
                   r = 0
                   !$omp target firstprivate(s) map(from: r)
                   r = s%a + 1
                   !$omp end target
                 end subroutine probe
                 """, decls="type(ext1) :: e1",
                 body="""
                 e1%a = 41
                 call probe(e1, r1)
                 """, checks=[("r1", 42)], legality="unspecified",
                 why="OpenMP 6.0 §7.5.4 p.228 l.8-9: firstprivate on a target "
                     "construct of a variable of polymorphic type: the "
                     "behavior is unspecified"))
    return out


# --- F10 CLASS(*) ----------------------------------------------------------------------

def _unlimited() -> list[V]:
    out = []
    pt = "type pt\n  integer :: a = 0\nend type pt\n"
    incr = """
    subroutine incr_any(x)
      !$omp declare target
      class(*), intent(inout) :: x
      select type (x)
      type is (integer)
        x = x + 1
      type is (real(8))
        x = x + 0.5d0
      type is (pt)
        x%a = x%a + 2
      end select
    end subroutine incr_any
    """
    out.append(V("unlimited", "select-type", "a declare target subroutine with "
                 "a CLASS(*) dummy and SELECT TYPE over intrinsic and derived "
                 "types, called on the device", [C_DT, C_SELECT], types=pt,
                 procs=incr, decls="integer :: k\nreal(8) :: d\ntype(pt) :: q",
                 body="""
                 k = 41
                 d = 1.5d0
                 q%a = 5
                 !$omp target map(tofrom: k, d, q)
                 call incr_any(k)
                 call incr_any(d)
                 call incr_any(q)
                 !$omp end target
                 r1 = k
                 r2 = nint(d * 10)
                 r3 = q%a
                 """, checks=[("r1", 42), ("r2", 20), ("r3", 7)]))
    out.append(V("unlimited", "classify", "a CLASS(*) function classifying "
                 "array elements of two derived types in a target teams "
                 "distribute parallel do", [C_DT, C_SELECT],
                 types=pt + "type qt\n  integer :: b = 0\nend type qt\n",
                 procs="""
                 integer function code_of(x)
                   !$omp declare target
                   class(*), intent(in) :: x
                   select type (x)
                   type is (integer)
                     code_of = 1
                   type is (pt)
                     code_of = 2
                   type is (qt)
                     code_of = 3
                   class default
                     code_of = 0
                   end select
                 end function code_of
                 """, decls="type(pt) :: ps(n)\ntype(qt) :: qs(n)\n"
                            "integer :: i, tot",
                 body="""
                 tot = 0
                 !$omp target teams distribute parallel do map(to: ps, qs) reduction(+: tot)
                 do i = 1, n
                   tot = tot + code_of(ps(i)) + code_of(qs(i))
                 end do
                 r1 = tot
                 """, checks=[("r1", 5 * N)]))
    out.append(V("unlimited", "mapped", "a CLASS(*), ALLOCATABLE object "
                 "(dynamic type pt) mapped by map(tofrom:)", [C_POLY60, C_DT],
                 types=pt, procs=incr, decls="class(*), allocatable :: u",
                 body="""
                 allocate(u, source=pt(5))
                 !$omp target map(tofrom: u)
                 call incr_any(u)
                 !$omp end target
                 r1 = -1
                 select type (u)
                 type is (pt)
                   r1 = u%a
                 end select
                 """, checks=[("r1", 7)], legality="unspecified",
                 why="OpenMP 6.0 §7.9.6 p.288 l.10: a map list item of "
                     "polymorphic type (Fortran): the behavior is unspecified"))
    return out


# --- F11 defined assignment and finalization -------------------------------------------

CT = """
type ct
  integer :: v = 0
  integer :: copies = 0
contains
  procedure :: asg => ct_asg
  generic :: assignment(=) => asg
end type ct
"""

CT_ASG = """
subroutine ct_asg(a, b)
  !$omp declare target
  class(ct), intent(inout) :: a
  class(ct), intent(in) :: b
  a%v = b%v
  a%copies = b%copies + 1
end subroutine ct_asg
"""

FT = """
type ft
  integer :: v = 0
contains
  final :: ft_fin
end type ft
"""

# `to`, 5.2's deprecated synonym of enter (5.2 §7.8.2), which CCE 19/20 and
# NVHPC still require: the family measures finalization, not the spelling
FT_DECLS = """
integer :: fin_count = 0
!$omp declare target to(fin_count)
"""

FT_FIN = """
subroutine ft_fin(o)
  !$omp declare target
  type(ft), intent(inout) :: o
  !$omp atomic update
  fin_count = fin_count + 1
end subroutine ft_fin
"""

C_FIN = ("Fortran 2018 7.5.6.3 (when finalization occurs); "
         "OpenMP 5.2 §1.2.6 p.19 (type-bound procedures in declare target)")


def _assignfinal() -> list[V]:
    out = []
    out.append(V("assignfinal", "tbp-assign", "an intrinsic-looking assignment "
                 "y = x in a target region invokes the type-bound defined "
                 "assignment", [C_TBP, C_DT,
                                "Fortran 2018 10.2.1.4 (defined assignment)"],
                 types=CT, procs=CT_ASG, decls="type(ct) :: x, y",
                 body="""
                 x%v = 5
                 x%copies = 0
                 !$omp target map(tofrom: x, y)
                 y = x
                 !$omp end target
                 r1 = y%v
                 r2 = y%copies
                 """, checks=[("r1", 5), ("r2", 1)]))
    out.append(V("assignfinal", "iface-assign", "a defined assignment by a "
                 "generic interface (not type-bound) in a target region",
                 [C_DT, C_PROCREF, "Fortran 2018 10.2.1.4"],
                 types="""
                 type nt
                   integer :: v = 0
                   integer :: n = 0
                 end type nt
                 interface assignment(=)
                   module procedure nt_asg
                 end interface
                 """, procs="""
                 subroutine nt_asg(a, b)
                   !$omp declare target
                   type(nt), intent(out) :: a
                   type(nt), intent(in) :: b
                   a%v = b%v * 2
                   a%n = b%n + 1
                 end subroutine nt_asg
                 """, decls="type(nt) :: x, y",
                 body="""
                 x%v = 5
                 x%n = 0
                 !$omp target map(tofrom: x, y)
                 y = x
                 !$omp end target
                 r1 = y%v
                 r2 = y%n
                 """, checks=[("r1", 10), ("r2", 1)]))
    out.append(V("assignfinal", "firstprivate", "firstprivate(x) on a target "
                 "construct initializes the new list item as if by the "
                 "type-bound defined assignment", [
                     "OpenMP 5.2 §5.4.4 p.113 l.3-6 (firstprivate "
                     "initialization by a compatible type-bound defined "
                     "assignment)", C_TBP],
                 types=CT, procs=CT_ASG, decls="type(ct) :: x",
                 body="""
                 x%v = 5
                 x%copies = 0
                 !$omp target firstprivate(x) map(from: r1, r2)
                 r1 = x%copies
                 r2 = x%v
                 !$omp end target
                 """, checks=[("r1", 1), ("r2", 5)]))
    out.append(V("assignfinal", "lastprivate", "lastprivate(w) of a parallel "
                 "do in a target region: the original is updated as if by the "
                 "type-bound defined assignment", [
                     "OpenMP 5.2 §5.4.5 p.115 l.24-25 (lastprivate update by a "
                     "type-bound defined assignment)", C_TBP],
                 types=CT, procs=CT_ASG, decls="type(ct) :: w\ninteger :: i",
                 body="""
                 w%v = -1
                 w%copies = 0
                 !$omp target map(tofrom: w)
                 !$omp parallel do lastprivate(w)
                 do i = 1, n
                   w%v = i
                   w%copies = 0
                 end do
                 !$omp end target
                 r1 = w%v
                 r2 = w%copies
                 """, checks=[("r1", N), ("r2", 1)]))
    fin_setup = "fin_count = 0\n!$omp target update to(fin_count)\n"
    out.append(V("assignfinal", "final-local", "a local object of a "
                 "finalizable type in a declare target subroutine is finalized "
                 "on return (the final subroutine counts on the device)",
                 [C_FIN, C_DT], types=FT, mod_decls=FT_DECLS,
                 procs=FT_FIN + """
                 subroutine work(k, r)
                   !$omp declare target
                   integer, intent(in) :: k
                   integer, intent(out) :: r
                   type(ft) :: o
                   o%v = k
                   r = 2 * o%v
                 end subroutine work
                 """, decls="integer :: res(n), i",
                 body=fin_setup + """
                 !$omp target teams distribute parallel do map(tofrom: res)
                 do i = 1, n
                   call work(i, res(i))
                 end do
                 !$omp target update from(fin_count)
                 r1 = fin_count
                 r2 = sum(res)
                 """, checks=[("r1", N), ("r2", 2 * S1)]))
    out.append(V("assignfinal", "final-private", "private(x) of a finalizable "
                 "type on a target construct: the private copy is finalized at "
                 "the end of the region", [C_FINAL, C_FIN], types=FT,
                 mod_decls=FT_DECLS, procs=FT_FIN, decls="type(ft) :: x",
                 body=fin_setup + """
                 !$omp target private(x)
                 x%v = 3
                 !$omp end target
                 !$omp target update from(fin_count)
                 r1 = fin_count
                 """, checks=[("r1", 1)]))
    out.append(V("assignfinal", "final-assign", "intrinsic assignment to a "
                 "local finalizable object in device code finalizes the "
                 "left-hand side, and the object is finalized on return",
                 ["Fortran 2018 7.5.6.3 para 1 and 3 (intrinsic assignment, "
                  "RETURN/END)", C_DT], types=FT, mod_decls=FT_DECLS,
                 procs=FT_FIN + """
                 subroutine copy_work(s, r)
                   !$omp declare target
                   type(ft), intent(in) :: s
                   integer, intent(out) :: r
                   type(ft) :: o
                   o = s
                   r = o%v
                 end subroutine copy_work
                 """, decls="type(ft) :: src\ninteger :: res(n), i",
                 body=fin_setup + """
                 src%v = 4
                 !$omp target teams distribute parallel do map(to: src) map(tofrom: res)
                 do i = 1, n
                   call copy_work(src, res(i))
                 end do
                 !$omp target update from(fin_count)
                 r1 = fin_count
                 r2 = sum(res)
                 """, checks=[("r1", 2 * N), ("r2", 4 * N)]))
    out.append(V("assignfinal", "final-dealloc", "DEALLOCATE of an allocatable "
                 "finalizable object in device code finalizes it once",
                 ["Fortran 2018 7.5.6.3 para 2 (deallocation)", C_DT],
                 types=FT, mod_decls=FT_DECLS, procs=FT_FIN + """
                 subroutine alloc_work(k, r)
                   !$omp declare target
                   integer, intent(in) :: k
                   integer, intent(out) :: r
                   type(ft), allocatable :: o
                   allocate(o)
                   o%v = k
                   r = o%v + 1
                   deallocate(o)
                 end subroutine alloc_work
                 """, decls="integer :: res(n), i",
                 body=fin_setup + """
                 !$omp target teams distribute parallel do map(tofrom: res)
                 do i = 1, n
                   call alloc_work(i, res(i))
                 end do
                 !$omp target update from(fin_count)
                 r1 = fin_count
                 r2 = sum(res)
                 """, checks=[("r1", N), ("r2", S1 + N)]))
    return out


# --- F12 declare reduction on derived types --------------------------------------------

V2 = "type v2\n  integer :: x = 0, y = 0\nend type v2\n"
C_DR = ("OpenMP 5.2 §5.5.11 p.139-140 (declare reduction); §5.5.2 p.125 "
        "l.25-27 (procedures of a reduction used in a target region are "
        "declare target)")


def _dreduce() -> list[V]:
    out = []
    vadd = """
    function vadd(a, b) result(c)
      !$omp declare target
      type(v2), intent(in) :: a, b
      type(v2) :: c
      c%x = a%x + b%x
      c%y = a%y + b%y
    end function vadd
    """
    loop = """
    !$omp target teams distribute parallel do reduction({rid}: acc)
    do i = 1, n
    {stmt}
    end do
    r1 = acc%x
    r2 = acc%y
    """
    out.append(V("dreduce", "function", "a declare reduction on a derived "
                 "type whose combiner calls a function, used on target teams "
                 "distribute parallel do", [C_DR,
                                            "OpenMP 5.2 §17.2 p.341 l.11-13"],
                 types=V2, procs=vadd,
                 decls="type(v2) :: acc\ninteger :: i\n"
                       "!$omp declare reduction(vsum: v2: omp_out = "
                       "vadd(omp_out, omp_in)) initializer(omp_priv = v2(0, 0))",
                 body="acc = v2(0, 0)\n" + loop.format(
                     rid="vsum", stmt="  acc = vadd(acc, v2(i, 2 * i))"),
                 checks=[("r1", S1), ("r2", 2 * S1)]))
    vcomb = """
    subroutine vcomb(o, i)
      !$omp declare target
      type(v2), intent(inout) :: o
      type(v2), intent(in) :: i
      o%x = o%x + i%x
      o%y = o%y + i%y
    end subroutine vcomb
    subroutine vinit(p)
      !$omp declare target
      type(v2), intent(out) :: p
      p%x = 0
      p%y = 0
    end subroutine vinit
    """
    out.append(V("dreduce", "subroutine", "a declare reduction whose combiner "
                 "and initializer are subroutine references",
                 [C_DR, "OpenMP 5.2 §5.5.2.1, §5.5.2.2 p.126-128"],
                 types=V2, procs=vcomb,
                 decls="type(v2) :: acc\ninteger :: i\n"
                       "!$omp declare reduction(vsum2: v2: vcomb(omp_out, "
                       "omp_in)) initializer(vinit(omp_priv))",
                 body="acc = v2(0, 0)\n" + loop.format(
                     rid="vsum2", stmt="  acc%x = acc%x + i\n  acc%y = acc%y + 1"),
                 checks=[("r1", S1), ("r2", N)]))
    out.append(V("dreduce", "operator", "a declare reduction(+) for a derived "
                 "type whose combiner uses a type-bound operator(+)",
                 [C_DR, C_TBP],
                 types="""
                 type w2
                   integer :: x = 0, y = 0
                 contains
                   procedure :: add => w2_add
                   generic :: operator(+) => add
                 end type w2
                 """, procs="""
                 function w2_add(a, b) result(c)
                   !$omp declare target
                   class(w2), intent(in) :: a
                   type(w2), intent(in) :: b
                   type(w2) :: c
                   c%x = a%x + b%x
                   c%y = a%y + b%y
                 end function w2_add
                 """,
                 decls="type(w2) :: acc\ninteger :: i\n"
                       "!$omp declare reduction(+: w2: omp_out = omp_out + "
                       "omp_in) initializer(omp_priv = w2(0, 0))",
                 body="acc%x = 0\nacc%y = 0\n" + loop.format(
                     rid="+", stmt="  acc = acc + w2(i, 1)"),
                 checks=[("r1", S1), ("r2", N)]))
    out.append(V("dreduce", "default-init", "a declare reduction without an "
                 "initializer clause: the private copies get the type's default "
                 "initialization", [C_DR, "OpenMP 5.2 §5.5.2.2 p.128 l.6"],
                 types="type d2\n  integer :: x = 0, y = 0\nend type d2\n",
                 procs="""
                 subroutine dcomb(o, i)
                   !$omp declare target
                   type(d2), intent(inout) :: o
                   type(d2), intent(in) :: i
                   o%x = o%x + i%x
                   o%y = o%y + i%y
                 end subroutine dcomb
                 """,
                 decls="type(d2) :: acc\ninteger :: i\n"
                       "!$omp declare reduction(dsum: d2: dcomb(omp_out, "
                       "omp_in))",
                 body=loop.format(rid="dsum",
                                  stmt="  acc%x = acc%x + i\n  acc%y = acc%y + 2"),
                 checks=[("r1", S1), ("r2", 2 * N)]))
    out.append(V("dreduce", "argmax", "a declare reduction keeping the element "
                 "with the largest key", [C_DR,
                                          "OpenMP 5.2 §5.5.2.2 p.128 l.6"],
                 types="type kv\n  integer :: key = -1, val = 0\nend type kv\n",
                 procs="""
                 subroutine kmax(o, i)
                   !$omp declare target
                   type(kv), intent(inout) :: o
                   type(kv), intent(in) :: i
                   if (i%key > o%key) then
                     o%key = i%key
                     o%val = i%val
                   end if
                 end subroutine kmax
                 """,
                 decls="type(kv) :: acc\ninteger :: i\n"
                       "!$omp declare reduction(kmx: kv: kmax(omp_out, omp_in))",
                 body="""
                 !$omp target teams distribute parallel do reduction(kmx: acc)
                 do i = 1, n
                   if (i > acc%key) then
                     acc%key = i
                     acc%val = 3 * i
                   end if
                 end do
                 r1 = acc%key
                 r2 = acc%val
                 """, checks=[("r1", N), ("r2", 3 * N)]))
    out.append(V("dreduce", "nested", "a declare reduction on a parallel do "
                 "inside a target region (the structure mapped tofrom)",
                 [C_DR], types=V2, procs=vadd,
                 decls="type(v2) :: acc\ninteger :: i\n"
                       "!$omp declare reduction(vsum: v2: omp_out = "
                       "vadd(omp_out, omp_in)) initializer(omp_priv = v2(0, 0))",
                 body="""
                 acc = v2(0, 0)
                 !$omp target map(tofrom: acc)
                 !$omp parallel do reduction(vsum: acc)
                 do i = 1, n
                   acc = vadd(acc, v2(1, i))
                 end do
                 !$omp end target
                 r1 = acc%x
                 r2 = acc%y
                 """, checks=[("r1", N), ("r2", S1)]))
    return out


# --- F13 elements and sections of arrays of structures (the AOMP map-test forms) ------

DC = """
type dc
  integer :: g(20) = 0
  integer :: i = 0
end type dc
"""


def _elemsec() -> list[V]:
    """Forms of ROCm/aomp's fortran-map-tests (harvest 2's CCE leads)
    written as family variants: an element or a
    section of an array of structures, a component of an element, sections
    of two members, an allocatable parent."""
    out = []
    d = "type(dc) :: vk(5)\ninteger :: l"
    out.append(V("elemsec", "element", "map(tofrom: vk(5)): one element of an "
                 "array of structures", [C_SECTION, C_MAP], types=DC,
                 decls=d, body="""
                 !$omp target map(tofrom: vk(5))
                 do l = 1, 20
                   vk(5)%g(l) = 20 + l
                 end do
                 vk(5)%i = 40
                 !$omp end target
                 r1 = sum(vk(5)%g)
                 r2 = vk(5)%i
                 r3 = sum(vk(4)%g)
                 """, checks=[("r1", 400 + 210), ("r2", 40), ("r3", 0)]))
    out.append(V("elemsec", "comp-element", "map(tofrom: vk(4)%g(3)): an "
                 "element of a component of an array element",
                 [C_SECTION, C_MAP], types=DC, decls=d, body="""
                 !$omp target map(tofrom: vk(4)%g(3))
                 vk(4)%g(3) = 74
                 !$omp end target
                 r1 = vk(4)%g(3)
                 r2 = sum(vk(4)%g)
                 """, checks=[("r1", 74), ("r2", 74)]))
    out.append(V("elemsec", "comp-section", "map(tofrom: vk(5)%g(3:5)): a "
                 "section of a component of an array element",
                 [C_SECTION, C_MAP], types=DC, decls=d, body="""
                 do l = 1, 20
                   vk(5)%g(l) = 100 + l
                 end do
                 !$omp target map(tofrom: vk(5)%g(3:5))
                 do l = 3, 5
                   vk(5)%g(l) = l
                 end do
                 !$omp end target
                 r1 = sum(vk(5)%g)
                 """, checks=[("r1", sum(100 + x for x in range(1, 21)) -
                                       sum(100 + x for x in range(3, 6)) +
                                       12)]))
    out.append(V("elemsec", "struct-section", "map(tofrom: vk(3:5)): a section "
                 "of an array of structures", [C_SECTION, C_MAP], types=DC,
                 decls=d, body="""
                 !$omp target map(tofrom: vk(3:5))
                 do l = 3, 5
                   vk(l)%i = 10 * l
                 end do
                 !$omp end target
                 r1 = sum(vk%i)
                 """, checks=[("r1", 120)]))
    da = "type da\n  integer :: b(10) = 0\n  integer :: d(10) = 0\nend type da"
    out.append(V("elemsec", "two-members", "map(tofrom: f%b(3:6), f%d(3:6)): "
                 "sections of two members of one structure",
                 [C_SECTION, C_STRUCTELT], types=da,
                 decls="type(da) :: f\ninteger :: l", body="""
                 !$omp target map(tofrom: f%b(3:6), f%d(3:6))
                 do l = 3, 6
                   f%b(l) = l
                   f%d(l) = 2 * l
                 end do
                 !$omp end target
                 r1 = sum(f%b)
                 r2 = sum(f%d)
                 """, checks=[("r1", 18), ("r2", 36)]))
    out.append(V("elemsec", "two-structs", "sections of two members of each "
                 "of two structures on one construct",
                 [C_SECTION, C_STRUCTELT], types=da,
                 decls="type(da) :: f, h\ninteger :: l", body="""
                 !$omp target map(tofrom: f%b(3:6), f%d(3:6), h%b(3:6), h%d(3:6))
                 do l = 3, 6
                   f%b(l) = l
                   f%d(l) = 2 * l
                   h%b(l) = 3 * l
                   h%d(l) = 4 * l
                 end do
                 !$omp end target
                 r1 = sum(f%b) + sum(f%d)
                 r2 = sum(h%b) + sum(h%d)
                 """, checks=[("r1", 54), ("r2", 126)]))
    out.append(V("elemsec", "nested-element", "map(tofrom: vk(4)%h%c(8)): an "
                 "element of a nested member of an array element",
                 [C_SECTION, C_MAP], types="""
                 type dn
                   integer :: c(10) = 0
                 end type dn
                 type dm
                   type(dn) :: h
                   integer :: i = 0
                 end type dm
                 """, decls="type(dm) :: vk(5)", body="""
                 !$omp target map(tofrom: vk(4)%h%c(8))
                 vk(4)%h%c(8) = 42
                 !$omp end target
                 r1 = vk(4)%h%c(8)
                 r2 = sum(vk(4)%h%c)
                 """, checks=[("r1", 42), ("r2", 42)]))
    out.append(V("elemsec", "alloc-parent", "map(tofrom: vj%h(4:8)): a section "
                 "of an allocatable array-of-structures component of an "
                 "allocatable scalar structure", [C_SECTION, C_ALLOCCOMP],
                 types="""
                 type da2
                   integer :: a = 0
                 end type da2
                 type db
                   type(da2), allocatable :: h(:)
                 end type db
                 """, decls="type(db), allocatable :: vj\ninteger :: l",
                 body="""
                 allocate(vj)
                 allocate(vj%h(10))
                 !$omp target map(tofrom: vj%h(4:8))
                 do l = 4, 8
                   vj%h(l)%a = 3 * l
                 end do
                 !$omp end target
                 r1 = sum(vj%h%a)
                 """, checks=[("r1", 90)]))
    out.append(V("elemsec", "alloc-chain", "a structure whose allocatable "
                 "scalar components hold allocatable scalar and array "
                 "components, mapped whole (recursive deep copy)",
                 [C_ALLOCCOMP, C_DEFMAPPER], types="""
                 type t1
                   integer, allocatable :: a
                   integer, allocatable :: c(:)
                 end type t1
                 type t2
                   type(t1), allocatable :: f
                 end type t2
                 type t3
                   type(t2), allocatable :: h
                   integer, allocatable :: g(:)
                 end type t3
                 """, decls="type(t3) :: x\ninteger :: l", body="""
                 allocate(x%h)
                 allocate(x%h%f)
                 allocate(x%h%f%a)
                 allocate(x%h%f%c(10))
                 allocate(x%g(10))
                 x%h%f%a = 0
                 x%h%f%c = 0
                 x%g = 0
                 !$omp target map(tofrom: x)
                 x%h%f%a = 7
                 do l = 1, 10
                   x%h%f%c(l) = l
                   x%g(l) = 2 * l
                 end do
                 !$omp end target
                 r1 = x%h%f%a
                 r2 = sum(x%h%f%c)
                 r3 = sum(x%g)
                 """, checks=[("r1", 7), ("r2", 55), ("r3", 110)]))
    return out


# --- OpenACC 3.4 -----------------------------------------------------------------------

A_DATA = ("OpenACC 3.4 §2.7.1 p.49-50 l.1711-1713 (a derived-type variable: "
          "its members are copied; allocatable or pointer members' data are "
          "not)")
A_ATTACH = ("OpenACC 3.4 §2.6.8 p.47-48 (attachment), §2.7.2 (data clause "
            "actions: attach)")
A_UPDATE = ("OpenACC 3.4 §2.14.4 p.90 l.3296-3299 (members of derived types, "
            "subarrays of members)")
A_ROUTINE = "OpenACC 3.4 §2.15.1 (routine directive)"


def _acc() -> list[V]:
    out = []
    acc = dict(model="acc")
    out.append(V("acc-copy", "struct", "copy(s) of a structure with a "
                 "fixed-size array member in a parallel loop", [A_DATA],
                 types="type sa\n  integer :: b(n) = 0\n  integer :: c = 0\n"
                 "end type sa", decls="type(sa) :: s\ninteger :: i",
                 body="""
                 do i = 1, n
                   s%b(i) = i
                 end do
                 s%c = 5
                 !$acc parallel loop copy(s)
                 do i = 1, n
                   s%b(i) = s%b(i) + s%c
                 end do
                 r1 = sum(s%b)
                 """, checks=[("r1", S1 + 5 * N)], **acc))
    out.append(V("acc-copy", "aos", "copy(p) of an array of structures",
                 [A_DATA], types="type pt\n  integer :: x = 0, y = 0\n"
                 "end type pt", decls="type(pt) :: p(n)\ninteger :: i",
                 body="""
                 do i = 1, n
                   p(i)%x = i
                 end do
                 !$acc parallel loop copy(p)
                 do i = 1, n
                   p(i)%y = 2 * p(i)%x + 1
                 end do
                 r1 = sum(p%y)
                 """, checks=[("r1", 2 * S1 + N)], **acc))
    d = "type(vec) :: x\ninteger :: i"
    out.append(V("acc-deep", "enterexit", "manual deep copy: enter data "
                 "copyin(x), then copyin(x%a) (attach); a parallel loop; "
                 "copyout(x%a); delete(x)", [A_DATA, A_ATTACH],
                 types=VEC, decls=d, body=VEC_SETUP + """
                 !$acc enter data copyin(x)
                 !$acc enter data copyin(x%a)
                 !$acc parallel loop present(x)
                 do i = 1, n
                   x%a(i) = x%a(i) + x%n
                 end do
                 !$acc exit data copyout(x%a)
                 !$acc exit data delete(x)
                 r1 = sum(x%a)
                 """, checks=[("r1", S1 + N * N)], **acc))
    out.append(V("acc-deep", "data", "a data construct with copyin(x) "
                 "copy(x%a) around a parallel loop", [A_DATA, A_ATTACH],
                 types=VEC, decls=d, body=VEC_SETUP + """
                 !$acc data copyin(x) copy(x%a)
                 !$acc parallel loop
                 do i = 1, n
                   x%a(i) = 2 * x%a(i)
                 end do
                 !$acc end data
                 r1 = sum(x%a)
                 """, checks=[("r1", 2 * S1)], **acc))
    out.append(V("acc-deep", "attach", "explicit attach and detach clauses for "
                 "a pointer member whose target is copied in separately",
                 [A_ATTACH, "OpenACC 3.4 §2.7.13 (attach clause), §2.7.14 "
                  "(detach clause)"], types=PV,
                 decls="type(pv) :: x\ninteger, target :: buf(n)\ninteger :: i",
                 body="""
                 do i = 1, n
                   buf(i) = i
                 end do
                 x%n = n
                 x%p => buf
                 !$acc enter data copyin(x)
                 !$acc enter data copyin(buf)
                 !$acc enter data attach(x%p)
                 !$acc parallel loop present(x)
                 do i = 1, n
                   x%p(i) = 3 * x%p(i)
                 end do
                 !$acc exit data detach(x%p)
                 !$acc exit data copyout(buf)
                 !$acc exit data delete(x)
                 r1 = sum(buf)
                 """, checks=[("r1", 3 * S1)], **acc))
    out.append(V("acc-deep", "update", "update self(x%a(1:16)): a subarray "
                 "of an allocatable member, after a device change",
                 [A_UPDATE, A_ATTACH], types=VEC, decls=d,
                 body=VEC_SETUP + """
                 !$acc enter data copyin(x)
                 !$acc enter data copyin(x%a)
                 !$acc parallel loop present(x)
                 do i = 1, n
                   x%a(i) = -x%a(i)
                 end do
                 !$acc update self(x%a(1:16))
                 r1 = sum(x%a(1:16))
                 !$acc exit data copyout(x%a)
                 !$acc exit data delete(x)
                 r2 = sum(x%a)
                 """, checks=[("r1", -136), ("r2", -S1)], **acc))
    out.append(V("acc-deep", "twolevel", "deep copy of an allocatable member "
                 "of a nested structure member: copyin(o), copyin(o%in%b)",
                 [A_DATA, A_ATTACH], types="""
                 type in_t
                   integer, allocatable :: b(:)
                 end type in_t
                 type out_t
                   type(in_t) :: in
                   integer :: k = 0
                 end type out_t
                 """, decls="type(out_t) :: o\ninteger :: i",
                 body="""
                 allocate(o%in%b(n))
                 do i = 1, n
                   o%in%b(i) = i
                 end do
                 o%k = 3
                 !$acc enter data copyin(o)
                 !$acc enter data copyin(o%in%b)
                 !$acc parallel loop present(o)
                 do i = 1, n
                   o%in%b(i) = o%in%b(i) * o%k
                 end do
                 !$acc exit data copyout(o%in%b)
                 !$acc exit data delete(o)
                 r1 = sum(o%in%b)
                 """, checks=[("r1", 3 * S1)], **acc))
    out.append(V("acc-routine", "tbp", "a type-bound function with a routine "
                 "seq directive called on each element (non-polymorphic "
                 "objects: the binding resolves statically)",
                 [A_ROUTINE, "Fortran 2018 15.5.6 (resolving type-bound "
                  "procedure references)"],
                 types="""
                 type tg
                   integer :: v = 0
                 contains
                   procedure :: get => tg_get
                 end type tg
                 """, procs="""
                 integer function tg_get(s)
                   !$acc routine seq
                   class(tg), intent(in) :: s
                   tg_get = s%v
                 end function tg_get
                 """, decls="type(tg) :: p(n)\ninteger :: r(n), i",
                 body="""
                 do i = 1, n
                   p(i)%v = i
                 end do
                 !$acc parallel loop copyin(p) copyout(r)
                 do i = 1, n
                   r(i) = 2 * p(i)%get()
                 end do
                 r1 = sum(r)
                 """, checks=[("r1", 2 * S1)], **acc))
    out.append(V("acc-routine", "dispatch", "dynamic dispatch through a "
                 "CLASS(shape) dummy in a routine seq function",
                 [A_ROUTINE], types=SHAPES,
                 procs=_shape_procs("!$acc routine seq"),
                 decls="type(sq) :: q\ntype(rect) :: rr",
                 body="""
                 q%side = 3
                 rr%w = 4
                 rr%h = 5
                 !$acc serial copyin(q, rr) copyout(r1)
                 r1 = area_of(q) + area_of(rr)
                 !$acc end serial
                 """, checks=[("r1", 29)], legality="unspecified",
                 why="OpenACC 3.4 does not address polymorphic objects or "
                     "type-bound procedure dispatch in compute regions (§1.8 "
                     "p.16 l.496-500 lists polymorphic assignment among the "
                     "Fortran 2008 features whose use may result in "
                     "unspecified behavior); observation only", **acc))
    return out


FAMILIES = ("nested", "alloccomp", "ptrcomp", "section", "mapper", "pdt",
            "extends", "tbp", "poly", "unlimited", "assignfinal", "dreduce",
            "elemsec", "acc-copy", "acc-deep", "acc-routine")


def programs() -> list[Program]:
    vs = (_nested() + _alloccomp() + _ptrcomp() + _section() + _mapper() +
          _pdt() + _extends() + _tbp() + _poly() + _unlimited() +
          _assignfinal() + _dreduce() + _elemsec() + _acc())
    return [render(v) for v in vs]


def program(pid: str) -> Program:
    for p in programs():
        if p.id == pid:
            return p
    raise KeyError(pid)


def parse_observed(stdout: str) -> dict:
    """name -> integer of the ``name= value`` lines of a run."""
    import re
    return {m.group(1): int(m.group(2)) for m in
            re.finditer(r"^(\w+)= (-?\d+)\s*$", stdout or "", re.M)}
