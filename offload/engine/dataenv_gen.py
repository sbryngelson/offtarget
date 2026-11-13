"""Small programs from the data-environment rule table.

``programs(rule) -> list[Program]`` returns, per language of the rule
(``rule["languages"]``), two programs: ``rule``, the rule's own form with
exactly the clauses the row names, and ``control``, the same scenario with the
attribute written out explicitly (a map, data clause, firstprivate or
``present``), expecting the same value.

Each program has one observable, computed on the host after the construct and
compared with the value derived from the rule's ``expected``, never from a
compiler. It prints the observed values and
``RESULT ran_on_host=<0|1> check=<pass|fail>``; ``ran_on_host`` comes from a
probe region at the start. Integers only, n = 64. OpenMP programs target 5.2
(ids ``omp52-de_...``), OpenACC 3.4 (``acc34-de_...``). A row's ``memory_mode``
sets ``Program.modes``. ``TEMPLATES`` maps ``template`` names to builders.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

N = 64
V0 = 101                     # the scalar's host value
OMP_VERSION = 52
ACC_VERSION = 34


@dataclass(frozen=True)
class Program:
    id: str
    rule: str
    lang: str                 # "f90" | "c"
    form: str                 # "rule" | "control"
    model: str                # "omp" | "acc"
    version: int
    source: str
    expected: dict            # observed name -> expected integer
    modes: tuple              # memory modes the expected value holds in
    observable: str

    @property
    def text(self) -> str:    # offload.engine.prerun reads .text or .source
        return self.source

    def harness(self):
        """The offload.engine.gen.Program the harness runs."""
        from offload.engine.gen import Program as HP
        unified_only = self.modes == ("unified",)
        return HP(id=self.id, lang=self.lang, source=self.source,
                  atoms=frozenset({f"dataenv.{self.rule}"}),
                  primary_atom=f"dataenv.{self.rule}", legal=True,
                  violates=None, observable=True,
                  needs=("zero_copy",) if unified_only else (),
                  evidence="copy_mode_only" if self.modes == ("copy",)
                  else "construct", model=self.model)


class GenError(ValueError):
    pass


# --- a program under construction ------------------------------------------------

@dataclass
class Src:
    lang: str
    model: str
    mod_decls: list = field(default_factory=list)   # F module / C globals
    mod_procs: list = field(default_factory=list)   # F contains / C funcs
    decls: list = field(default_factory=list)
    body: list = field(default_factory=list)
    checks: list = field(default_factory=list)      # (name, expected)
    requires: str = ""
    form: str = "rule"

    @property
    def f(self) -> bool:
        return self.lang == "f90"

    def int_(self, *names):
        for nm in names:
            self.decls.append(f"integer :: {nm}" if self.f else f"int {nm};")

    def check(self, name: str, expected: int):
        self.checks.append((name, int(expected)))


def _dir(s: Src, text: str) -> str:
    return (f"!$omp {text}" if s.model == "omp" else f"!$acc {text}") \
        if s.f else (f"#pragma omp {text}" if s.model == "omp"
                     else f"#pragma acc {text}")


def _join(*cl) -> str:
    return " ".join(c for c in cl if c)


C_NAMES = {"target parallel do": "target parallel for",
           "target teams distribute parallel do":
               "target teams distribute parallel for",
           "target teams distribute parallel do simd":
               "target teams distribute parallel for simd"}


def is_loop_construct(construct: str) -> bool:
    """A construct whose directive applies to the loop that follows it."""
    return construct.endswith(("do", "for", "loop", "simd", "distribute"))


# a construct whose region every thread or team runs: one of them, so the
# region's scalar statements run once (a team of one thread, one team)
ONE = {("omp", "target parallel"): "num_threads(1)",
       ("omp", "target teams"): "num_teams(1)",
       ("acc", "parallel"): "num_gangs(1)"}


def head_of(s: Src, construct: str) -> str:
    name = construct if s.f else C_NAMES.get(construct, construct)
    return _join(name, ONE.get((s.model, construct), ""))


def region(s: Src, construct: str, clauses: str, inner: list,
           loop: bool = False) -> list:
    """The lines of a construct around `inner`. A loop construct (OpenMP
    combined, OpenACC parallel loop) or `loop` True puts `inner` in a loop
    over i = 1..n (the directive on the loop for a loop construct)."""
    loop_construct = is_loop_construct(construct)
    head = head_of(s, construct)
    if s.f:
        out = [_dir(s, _join(head, clauses))]
        if loop_construct or loop:
            out += ["do i = 1, n"] + ["  " + x for x in inner] + ["end do"]
        else:
            out += ["  " + x for x in inner]
        out.append(_dir(s, "end " + construct))
        return out
    out = [_dir(s, _join(head, clauses))]
    if loop_construct:
        out += ["for (int i = 1; i <= n; i++) {"] + \
            ["  " + x for x in inner] + ["}"]
    elif loop:
        out += ["{", "  for (int i = 1; i <= n; i++) {"] + \
            ["    " + x for x in inner] + ["  }", "}"]
    else:
        out += ["{"] + ["  " + x for x in inner] + ["}"]
    return out


def _el(s: Src, a: str, idx: str = "i") -> str:
    """Element i (1-based) of array `a`."""
    return f"{a}({idx})" if s.f else f"{a}[{idx} - 1]"


def count_bad(s: Src, a: str, formula: str, into: str) -> list:
    """Lines setting `into` to the number of elements of `a` that differ
    from `formula` (an expression in i)."""
    if s.f:
        return [f"{into} = 0", "do i = 1, n",
                f"  if ({a}(i) /= {formula}) {into} = {into} + 1", "end do"]
    return [f"{into} = 0;", "for (int i = 1; i <= n; i++)",
            f"  if ({a}[i - 1] != {formula}) {into}++;"]


def _f_formula_sum(formula: str) -> int:
    return sum(eval(formula.replace("i", str(i))) for i in range(1, N + 1))


def array_checks(s: Src, a: str, formula: str, tag: str) -> list:
    """count_bad into <tag>_bad (expected 0) and the sum into <tag>_sum."""
    s.int_(f"{tag}_bad", f"{tag}_sum")
    lines = count_bad(s, a, formula, f"{tag}_bad")
    if s.f:
        lines.append(f"{tag}_sum = sum({a})")
    else:
        lines += [f"{tag}_sum = 0;", "for (int i = 1; i <= n; i++)",
                  f"  {tag}_sum += {a}[i - 1];"]
    s.check(f"{tag}_bad", 0)
    s.check(f"{tag}_sum", _f_formula_sum(formula))
    return lines


def init_array(s: Src, a: str, formula: str = "i") -> list:
    if s.f:
        return ["do i = 1, n", f"  {a}(i) = {formula}", "end do"]
    return ["for (int i = 1; i <= n; i++)", f"  {a}[i - 1] = {formula};"]


def stmt(s: Src, text: str) -> str:
    return text if s.f else text + ";"


# --- clauses ------------------------------------------------------------------------

_ACC_MAP = {"tofrom": "copy", "to": "copyin", "from": "copyout",
            "alloc": "create", "present": "present"}


def clause_for(s: Src, rule: dict, var: str) -> str:
    """The explicit clause that states what the rule decides for `var`
    (form "opposite": the clause that decides the other way)."""
    e = rule["expected"]
    if s.form == "opposite":
        return opposite_clause(s, rule, var)
    if e["dsa"] in ("firstprivate", "private"):
        # private: nothing is read, so firstprivate decides the same
        return f"firstprivate({var})"
    mt = e["map_type"]
    if s.model == "acc":
        return f"{_ACC_MAP[mt]}({var})" if mt in _ACC_MAP else ""
    if mt == "present":
        return f"map(present, alloc: {var})"
    if mt in ("to", "from", "tofrom", "alloc"):
        return f"map({mt}: {var})"
    return ""


def opposite_clause(s: Src, rule: dict, var: str) -> str:
    """The oracle mutant's clause: an item the rule makes private or not
    copied back is mapped tofrom (OpenACC copy); an item the rule copies
    back is made firstprivate (a scalar or a structure) or mapped to
    (OpenACC copyin; an array)."""
    e = rule["expected"]
    if e["copy_back"] != "yes":
        return f"map(tofrom: {var})" if s.model == "omp" else f"copy({var})"
    if rule["variable_kind"] in ("scalar", "derived_type"):
        return f"firstprivate({var})"
    return f"map(to: {var})" if s.model == "omp" else f"copyin({var})"


# the templates whose control states the rule's attribute with clause_for,
# so that an oracle mutant ("opposite" form) exists
OPPOSITE = ("scalar_rw", "array_rw", "struct_rw", "usm_scalar")


def map_out(s: Src, var: str) -> str:
    """The clause that returns a result variable (rd, b) to the host."""
    return f"map(from: {var})" if s.model == "omp" else f"copyout({var})"


def map_both(s: Src, var: str) -> str:
    return f"map(tofrom: {var})" if s.model == "omp" else f"copy({var})"


def rule_clauses(rule: dict, var: str, drop=()) -> list:
    """The row's clauses as written on the construct, for `var`:
    "defaultmap(tofrom: scalar)" as is, "lastprivate" -> lastprivate(var),
    "map(always, to)" -> map(always, to: var), "copyin" -> copyin(var).
    Clauses of other directives (requires, data ...) and `drop` are left
    out."""
    out = []
    for c in rule["clauses_present"]:
        if c.startswith(("requires", "data ", "collapse")) or c in drop:
            continue
        if c.startswith(("defaultmap", "default(")):
            out.append(c.replace(" ", ""))
        elif c.startswith("map("):
            inner = c[4:-1]
            out.append(f"map({inner}: {var})")
        elif c == "reduction":
            out.append(f"reduction(+: {var})")
        else:
            out.append(f"{c}({var})")
    return out


# --- variables by attribute ------------------------------------------------------------

def declare_scalar(s: Src, rule: dict, v: str = "v") -> str:
    """Declare the scalar under test and return the name the host reads
    back (a pointer's target)."""
    attrs = set(rule["attribute"])
    if s.f:
        if "module" in attrs or "declare_target" in attrs or \
                "declare_target_link" in attrs or "declare_create" in attrs:
            s.mod_decls.append(f"integer :: {v}")
        elif "target" in attrs:
            s.decls.append(f"integer, target :: {v}")
        elif "allocatable" in attrs:
            s.decls.append(f"integer, allocatable :: {v}")
            s.body.append(f"allocate({v})")
        elif "pointer" in attrs:
            s.decls += [f"integer, target :: {v}t", f"integer, pointer :: {v}"]
            s.body.append(f"{v} => {v}t")
            return f"{v}t"
        elif "common" in attrs:
            s.decls += [f"integer :: {v}", f"common /cbde/ {v}"]
        else:
            s.decls.append(f"integer :: {v}")
        return v
    if attrs & {"module", "declare_target", "declare_target_link",
                "declare_create"}:
        s.mod_decls.append(f"int {v};")
    else:
        s.decls.append(f"int {v};")
    return v


def declare_array(s: Src, rule: dict, a: str = "a") -> str:
    attrs = set(rule["attribute"])
    if s.f:
        if "declare_create" in attrs and "allocatable" in attrs:
            s.mod_decls.append(f"integer, allocatable :: {a}(:)")
            s.body.append(f"allocate({a}(n))")
        elif attrs & {"module", "declare_target", "declare_create"}:
            s.mod_decls.append(f"integer :: {a}(n)")
        elif "allocatable" in attrs:
            s.decls.append(f"integer, allocatable :: {a}(:)")
            s.body.append(f"allocate({a}(n))")
        elif "pointer" in attrs:
            s.decls += [f"integer, target :: {a}t(n)",
                        f"integer, pointer :: {a}(:)"]
            s.body.append(f"{a} => {a}t")
            return f"{a}t"
        elif "common" in attrs:
            s.decls += [f"integer :: {a}(n)", f"common /cbde/ {a}"]
        else:
            s.decls.append(f"integer :: {a}(n)")
        return a
    if attrs & {"module", "declare_target", "declare_create"}:
        s.mod_decls.append(f"int {a}[n];")
    elif "allocatable" in attrs:      # C: a heap array through a pointer
        s.decls.append(f"int *{a} = malloc(n * sizeof(int));")
    else:
        s.decls.append(f"int {a}[n];")
    return a


def _declare_target(s: Src, var: str, link: bool = False) -> None:
    if s.f:
        s.mod_decls.append(f"!$omp declare target link({var})" if link
                           else f"!$omp declare target({var})")
    else:
        s.mod_decls.append(f"#pragma omp declare target link({var})" if link
                           else f"#pragma omp declare target({var})")


def _acc_declare(s: Src, var: str, clause: str = "create") -> None:
    s.mod_decls.append(f"!$acc declare {clause}({var})" if s.f
                       else f"#pragma acc declare {clause}({var})")


# --- templates ------------------------------------------------------------------------
# Each builder fills a Src for (rule, form) and returns the observable text.

def _reads(rule: dict) -> bool:
    """Whether the region may read the item: not when nothing is
    transferred in (map from or alloc) and not when it is private."""
    return rule["expected"]["map_type"] not in ("from", "alloc") and \
        rule["expected"]["dsa"] != "private"


def t_scalar_rw(s: Src, rule: dict, form: str) -> None:
    """rd = v; v = 2*v + 1 in a one-thread region (or v = 77 when the
    rule's map type transfers nothing in or v is private). On an OpenMP
    loop construct, every iteration reads v instead (b(i) = v + i)."""
    if s.model == "omp" and is_loop_construct(rule["construct"]):
        return _scalar_read_in_loop(s, rule, form)
    host = declare_scalar(s, rule)
    s.int_("rd")
    s.body += [stmt(s, f"v = {V0}"), stmt(s, "rd = -1")]
    reads = _reads(rule)
    inner = [stmt(s, "rd = v"), stmt(s, "v = 2*v + 1")] if reads \
        else [stmt(s, "v = 77")]
    usm = any(c.startswith("requires") for c in rule["clauses_present"])
    if usm:
        s.requires = "unified_shared_memory"
    if form == "rule":
        cl = rule_clauses(rule, "v")
    elif form == "control" and _explicit_map(rule) == "tofrom":
        # the row's own map(tofrom: v): the same map through defaultmap
        cl = ["defaultmap(tofrom:scalar)"]
    else:
        cl = [c for c in rule_clauses(rule, "v")
              if not c.startswith("defaultmap") and
              not c.endswith("v)")] + [clause_for(s, rule, "v")]
    s.body += region(s, rule["construct"], _join(*cl, map_out(s, "rd")),
                     inner)
    back = rule["expected"]["copy_back"] == "yes"
    if reads:
        s.check("rd", V0)
        s.check(host, 2 * V0 + 1 if back else V0)
    else:
        s.check(host, 77 if back else V0)


def t_usm_scalar(s, rule, form):
    t_scalar_rw(s, rule, form)


def _scalar_read_in_loop(s: Src, rule: dict, form: str) -> None:
    """A scalar the loop construct's iterations only read: b(i) = v + i
    (b mapped from); the host's v stays 101."""
    host = declare_scalar(s, rule)
    _b(s)
    s.body.append(stmt(s, f"v = {V0}"))
    if form == "rule":
        cl = rule_clauses(rule, "v")
    else:
        cl = [c for c in rule_clauses(rule, "v")
              if not c.startswith("defaultmap") and
              not c.endswith("v)")] + [clause_for(s, rule, "v")]
    s.body += region(s, rule["construct"], _join(*cl, map_out(s, "b")),
                     [stmt(s, f"{_el(s, 'b')} = v + i")])
    s.body += array_checks(s, "b", f"{V0} + i", "b")
    s.check(host, V0)


def _explicit_map(rule: dict) -> str | None:
    """The map type of the row's own plain map clause (map(to) ...), or
    None."""
    for c in rule["clauses_present"]:
        m = re.fullmatch(r"map\((to|from|tofrom|alloc)\)", c.replace(" ", ""))
        if m:
            return m.group(1)
    return None


def t_array_rw(s: Src, rule: dict, form: str) -> None:
    """a(i) = i; the region sets a(i) = 2*a(i) + 1 (b(i) = a(i) first when
    the write is not expected back; a(i) = 7*i, no read, when nothing is
    transferred in or the array is private). Under a defaultmap clause the
    copy-in is observed through a scalar sum (map tofrom: rs), not through
    a second mapped array, so the array the rule decides is the only
    aggregate."""
    host = declare_array(s, rule)
    e = rule["expected"]
    back = e["copy_back"] == "yes"
    reads = _reads(rule)
    dmap = any(c.startswith("defaultmap") for c in rule["clauses_present"])
    s.body += init_array(s, "a")
    a_el = _el(s, "a")
    extra = []
    if not reads:
        inner = [stmt(s, f"{a_el} = 7*i")]
    elif back:
        inner = [stmt(s, f"{a_el} = 2*{a_el} + 1")]
    elif dmap:
        s.int_("rs")
        s.body.append(stmt(s, "rs = 0"))
        inner = [stmt(s, f"rs = rs + {a_el}"),
                 stmt(s, f"{a_el} = 2*{a_el} + 1")]
        extra = ["map(tofrom: rs)"]
    else:
        s.decls.append("integer :: b(n)" if s.f else "int b[n];")
        s.body += init_array(s, "b", "0")
        inner = [stmt(s, f"{_el(s, 'b')} = {a_el}"),
                 stmt(s, f"{a_el} = 2*{a_el} + 1")]
        extra = [map_out(s, "b")]
    sect = "a" if s.f or "allocatable" not in rule["attribute"] else \
        "a[0:n]"
    pre, post = [], []
    mt = _explicit_map(rule)
    if form == "rule":
        cl = rule_clauses(rule, sect)
    else:
        # the row's own clauses for the array (and defaultmap) give way
        # to the explicit clause
        cl = [c for c in rule_clauses(rule, sect)
              if not c.startswith("defaultmap") and
              not c.endswith(f"{sect})")]
        if form == "control" and any(c == "copyin"
                                     for c in rule["clauses_present"]):
            # copyin(a) == enter data copyin, present, exit data delete
            cl = [f"present({sect})"]
            pre = [_dir(s, f"enter data copyin({sect})")]
            post = [_dir(s, f"exit data delete({sect})")]
        elif form == "control" and mt:
            # a plain map(<t>) == target enter data and target exit data
            # with the same transfers around an implicit (present) map
            ent = "to" if mt in ("to", "tofrom") else "alloc"
            ext = "from" if mt in ("from", "tofrom") else "release"
            pre = [_dir(s, f"target enter data map({ent}: {sect})")]
            post = [_dir(s, f"target exit data map({ext}: {sect})")]
        else:
            cl.append(clause_for(s, rule, sect))
    loop = not is_loop_construct(rule["construct"])
    s.body += pre + region(s, rule["construct"], _join(*cl, *extra), inner,
                           loop=loop) + post
    if not reads:
        s.body += array_checks(s, host, "i", "a")
    elif back:
        s.body += array_checks(s, host, "2*i + 1", "a")
    elif dmap:
        s.check("rs", _f_formula_sum("i"))
        s.body += array_checks(s, host, "i", "a")
    else:
        s.body += array_checks(s, "b", "i", "b")
        s.body += array_checks(s, host, "i", "a")


def t_usm_array(s: Src, rule: dict, form: str) -> None:
    """requires unified_shared_memory; a heap array (Fortran allocatable,
    C malloc) with no map clause (control: an explicit map)."""
    s.requires = "unified_shared_memory"
    declare_array(s, rule)
    s.body += init_array(s, "a")
    a_el = _el(s, "a")
    sect = "a" if s.f else "a[0:n]"
    cl = "" if form == "rule" else f"map(tofrom: {sect})"
    s.body += region(s, "target", cl, [stmt(s, f"{a_el} = 2*{a_el} + 1")],
                     loop=True)
    s.body += array_checks(s, "a", "2*i + 1", "a")


def t_struct_rw(s: Src, rule: dict, form: str) -> None:
    if s.f:
        s.mod_decls += ["type t2", "  integer :: c1, c2", "end type t2"]
        s.decls.append("type(t2) :: x")
        c1, c2 = "x%c1", "x%c2"
    else:
        s.mod_decls.append("struct t2 { int c1; int c2; };")
        s.decls.append("struct t2 x;")
        c1, c2 = "x.c1", "x.c2"
    s.int_("rd", "c2v")
    s.body += [stmt(s, f"{c1} = {V0}"), stmt(s, f"{c2} = 0"),
               stmt(s, "rd = -1")]
    inner = [stmt(s, f"rd = {c1}"), stmt(s, f"{c2} = 2*{c1} + 1")]
    cl = "" if form == "rule" else clause_for(s, rule, "x")
    s.body += region(s, rule["construct"], _join(cl, map_out(s, "rd")),
                     inner)
    s.body.append(stmt(s, f"c2v = {c2}"))
    s.check("rd", V0)
    s.check("c2v", 2 * V0 + 1)


def t_c_pointer_rw(s: Src, rule: dict, form: str) -> None:
    s.decls.append("int *p = malloc(n * sizeof(int));")
    s.body += init_array(s, "p")
    s.body.append("#pragma omp target data map(tofrom: p[0:n])")
    s.body.append("{")
    cl = "" if form == "rule" else "map(tofrom: p[0:n])"
    s.body += ["  " + x for x in region(
        s, "target", cl, ["p[i - 1] = 2*p[i - 1] + 1;"], loop=True)]
    s.body.append("}")
    s.body += array_checks(s, "p", "2*i + 1", "p")


def t_value_arg(s: Src, rule: dict, form: str) -> None:
    cl = _join("" if form == "rule" else "firstprivate(v)",
               "map(from: r)")
    reg = region(s, "target", cl, [stmt(s, "r = v"), stmt(s, "v = 2*v + 1")])
    if s.f:
        s.mod_procs += ["subroutine sub(v, rd, vout)",
                        "  integer, value :: v",
                        "  integer, intent(out) :: rd, vout",
                        "  integer :: r", "  r = -1"] + \
            ["  " + x for x in reg] + ["  rd = r", "  vout = v",
                                       "end subroutine sub"]
        s.body.append(f"call sub({V0}, rd, vout)")
    else:
        s.mod_procs += ["static void sub(int v, int *rd, int *vout)", "{",
                        "  int r = -1;"] + ["  " + x for x in reg] + \
            ["  *rd = r;", "  *vout = v;", "}"]
        s.body.append(f"sub({V0}, &rd, &vout);")
    s.int_("rd", "vout")
    s.check("rd", V0)
    s.check("vout", V0)


def t_struct_ptr_member(s: Src, rule: dict, form: str) -> None:
    if s.f:
        s.mod_decls += ["type tp", "  integer, pointer :: p(:) => null()",
                        "end type tp"]
        s.decls += ["type(tp) :: s", "integer, target :: t(n)",
                    "integer, pointer :: q(:)"]
        s.body += init_array(s, "t") + ["s%p => t"]
        if form == "rule":
            s.body += region(s, "target", "map(to: s) map(tofrom: s%p)",
                             ["s%p(i) = 2*s%p(i) + 1"], loop=True)
        else:
            s.body += ["q => s%p"] + region(
                s, "target", "map(tofrom: q)", ["q(i) = 2*q(i) + 1"],
                loop=True)
        s.body += array_checks(s, "t", "2*i + 1", "t")
        return
    s.mod_decls.append("struct tp { int *p; };")
    s.decls += ["struct tp s;", "int *q;"]
    s.body += ["s.p = malloc(n * sizeof(int));"] + init_array(s, "s.p")
    if form == "rule":
        s.body += region(s, "target", "map(to: s) map(tofrom: s.p[0:n])",
                         ["s.p[i - 1] = 2*s.p[i - 1] + 1;"], loop=True)
    else:
        s.body += ["q = s.p;"] + region(s, "target", "map(tofrom: q[0:n])",
                                        ["q[i - 1] = 2*q[i - 1] + 1;"],
                                        loop=True)
    s.body += array_checks(s, "s.p", "2*i + 1", "t")


def _update(s: Src, way: str, var: str) -> str:
    if s.model == "omp":
        return _dir(s, f"target update {'to' if way == 'to' else 'from'}"
                       f"({var})")
    return _dir(s, f"update {'device' if way == 'to' else 'self'}({var})")


def t_declare_target_roundtrip(s: Src, rule: dict, form: str) -> None:
    """g = 101 (g(i) = i), update to; region rd = g, g = 2*g + 1;
    update from."""
    array = rule["variable_kind"] == "array"
    if array:
        declare_array(s, rule, "g")
    else:
        declare_scalar(s, rule, "g")
    _declare_target(s, "g")
    _roundtrip(s, rule, form, array)


def _roundtrip(s: Src, rule: dict, form: str, array: bool) -> None:
    if array:
        s.body += init_array(s, "g") + [_update(s, "to", "g")]
        g_el = _el(s, "g")
        inner = [stmt(s, f"{g_el} = 2*{g_el} + 1")]
        res = []
    else:
        s.int_("rd")
        s.body += [stmt(s, f"g = {V0}"), stmt(s, "rd = -1"),
                   _update(s, "to", "g")]
        inner = [stmt(s, "rd = g"), stmt(s, "g = 2*g + 1")]
        res = [map_out(s, "rd")]
    if form == "rule":
        cl = []
    elif s.model == "omp":
        cl = ["map(tofrom: g)"]
    else:
        cl = ["present(g)"]
    loop = array and rule["construct"] in ("target", "serial")
    s.body += region(s, rule["construct"], _join(*cl, *res), inner,
                     loop=loop)
    s.body.append(_update(s, "from", "g"))
    if array:
        s.body += array_checks(s, "g", "2*i + 1", "g")
    else:
        s.check("rd", V0)
        s.check("g", 2 * V0 + 1)


def t_declare_target_no_transfer(s: Src, rule: dict, form: str) -> None:
    declare_scalar(s, rule, "g")
    _declare_target(s, "g")
    s.int_("rd", "gh")
    s.body += [stmt(s, "g = 5"), _update(s, "to", "g"), stmt(s, f"g = {V0}"),
               stmt(s, "rd = -1")]
    cl = "" if form == "rule" else "map(tofrom: g)"
    s.body += region(s, "target", _join(cl, "map(from: rd)"),
                     [stmt(s, "rd = g"), stmt(s, "g = 77")])
    s.body.append(stmt(s, "gh = g"))
    s.check("rd", 5)
    s.check("gh", V0)


def t_declare_target_link(s: Src, rule: dict, form: str) -> None:
    declare_scalar(s, rule, "g")
    _declare_target(s, "g", link=True)
    s.int_("rd")
    s.body += [stmt(s, f"g = {V0}"), stmt(s, "rd = -1")]
    cl = "" if form == "rule" else "map(tofrom: g)"
    s.body += region(s, "target", _join(cl, "map(from: rd)"),
                     [stmt(s, "rd = g"), stmt(s, "g = 2*g + 1")])
    s.check("rd", V0)
    s.check("g", 2 * V0 + 1)


def t_declare_target_routine(s: Src, rule: dict, form: str) -> None:
    declare_scalar(s, rule, "g")
    _declare_target(s, "g")
    if s.f:
        s.mod_procs += ["subroutine bump(r)", "  !$omp declare target",
                        "  integer, intent(out) :: r", "  r = g",
                        "  g = 2*g + 1", "end subroutine bump"]
        call = "call bump(rd)"
    else:
        s.mod_procs += ["static void bump(int *r)", "{", "  *r = g;",
                        "  g = 2*g + 1;", "}",
                        "#pragma omp declare target(bump)"]
        call = "bump(&rd);"
    s.int_("rd")
    s.body += [stmt(s, f"g = {V0}"), stmt(s, "rd = -1"),
               _update(s, "to", "g")]
    cl = "" if form == "rule" else "map(tofrom: g)"
    s.body += region(s, "target", _join(cl, "map(from: rd)"), [call])
    s.body.append(_update(s, "from", "g"))
    s.check("rd", V0)
    s.check("g", 2 * V0 + 1)


def t_acc_declare_roundtrip(s: Src, rule: dict, form: str) -> None:
    array = rule["variable_kind"] == "array"
    if array:
        declare_array(s, rule, "g")
    else:
        declare_scalar(s, rule, "g")
    _acc_declare(s, "g")
    _roundtrip(s, rule, form, array)


def t_acc_routine_global(s: Src, rule: dict, form: str) -> None:
    declare_scalar(s, rule, "g")
    _acc_declare(s, "g")
    if s.f:
        s.mod_procs += ["subroutine bump(r)", "  !$acc routine seq",
                        "  integer, intent(out) :: r", "  r = g",
                        "  g = 2*g + 1", "end subroutine bump"]
        call = "call bump(rd)"
    else:
        s.mod_procs += ["#pragma acc routine seq",
                        "static void bump(int *r)", "{", "  *r = g;",
                        "  g = 2*g + 1;", "}"]
        call = "bump(&rd);"
    s.int_("rd")
    s.body += [stmt(s, f"g = {V0}"), stmt(s, "rd = -1"),
               _update(s, "to", "g")]
    cl = "" if form == "rule" else "present(g)"
    s.body += region(s, "serial", _join(cl, "copyout(rd)"), [call])
    s.body.append(_update(s, "from", "g"))
    s.check("rd", V0)
    s.check("g", 2 * V0 + 1)


def t_acc_declare_copyin(s: Src, rule: dict, form: str) -> None:
    if not s.f:
        raise GenError("declare copyin of a procedure array: Fortran only")
    cl = _join("" if form == "rule" else "present(a)", "copyout(b)")
    reg = region(s, "parallel loop", cl, ["b(i) = 2*a(i) + 1"])
    s.mod_procs += ["subroutine work(a, b)", "  integer, intent(in) :: a(n)",
                    "  integer, intent(out) :: b(n)", "  integer :: i",
                    "  !$acc declare copyin(a)"] + ["  " + x for x in reg] + \
        ["end subroutine work"]
    s.decls += ["integer :: a(n)", "integer :: b(n)"]
    s.body += init_array(s, "a") + init_array(s, "b", "0") + \
        ["call work(a, b)"]
    s.body += array_checks(s, "b", "2*i + 1", "b")


def _data(s: Src, clause: str, body: list) -> list:
    if s.model == "omp":
        if s.f:
            return [f"!$omp target data {clause}"] + ["  " + x for x in body] \
                + ["!$omp end target data"]
        return [f"#pragma omp target data {clause}", "{"] + \
            ["  " + x for x in body] + ["}"]
    if s.f:
        return [f"!$acc data {clause}"] + ["  " + x for x in body] + \
            ["!$acc end data"]
    return [f"#pragma acc data {clause}", "{"] + ["  " + x for x in body] + \
        ["}"]


def _inner_clauses(s: Src, rule: dict, form: str, var: str) -> str:
    """The inner construct's clauses of a nested-data program: the row's
    (none when the row's construct is the data construct itself); the
    control states the attribute (OpenMP: a map of the rule's map type, or
    map(present, alloc) for present; OpenACC: present)."""
    if rule["construct"] in ("target data", "data"):
        own = []
    else:
        own = rule_clauses(rule, var)
    if form == "rule":
        return _join(*own)
    if s.model == "acc":
        # a present clause's control is a copy (present: no transfer)
        return f"copy({var})" if f"present({var})" in own else \
            f"present({var})"
    if any(c.startswith("map(present") for c in own):
        return f"map(tofrom: {var})"
    if rule["expected"]["map_type"] == "present" or \
            any(c.startswith("defaultmap") for c in own):
        return f"map(present, alloc: {var})"
    return f"map(tofrom: {var})"


def _nested(s: Src, rule: dict, form: str, where: str) -> None:
    declare_array(s, rule)
    s.body += init_array(s, "a")
    a_el = _el(s, "a")
    outer = "map(tofrom: a)" if s.model == "omp" else "copy(a)"
    inner_construct = "target" if s.model == "omp" else "parallel loop"
    reg = region(s, inner_construct, _inner_clauses(s, rule, form, "a"),
                 [stmt(s, f"{a_el} = 2*{a_el} + 1")],
                 loop=s.model == "omp")
    if where == "inside":
        s.body += _data(s, outer, reg + array_checks(s, "a", "i", "a"))
    else:
        s.body += _data(s, outer, reg) + array_checks(s, "a", "2*i + 1",
                                                      "a")


def t_nested_data_inside(s, rule, form):
    _nested(s, rule, form, "inside")


def t_nested_data_after(s, rule, form):
    _nested(s, rule, form, "after")


def t_present_mod(s, rule, form):
    _nested(s, rule, form, "after")


def _enter(s: Src, var: str = "a") -> str:
    return _dir(s, f"target enter data map(to: {var})" if s.model == "omp"
                else f"enter data copyin({var})")


def _exit(s: Src, how: str, var: str = "a") -> str:
    if s.model == "omp":
        return _dir(s, f"target exit data map({how}: {var})")
    acc = {"from": "copyout", "delete": "delete"}[how]
    return _dir(s, f"exit data {acc}({var})")


def _inner_present(s: Src, form: str, var: str = "a") -> str:
    if form == "rule":
        return ""
    return f"map(tofrom: {var})" if s.model == "omp" else f"present({var})"


def _write_region(s: Src, form: str) -> list:
    a_el = _el(s, "a")
    construct = "target" if s.model == "omp" else "parallel loop"
    return region(s, construct, _inner_present(s, form),
                  [stmt(s, f"{a_el} = 2*{a_el} + 1")], loop=s.model == "omp")


def t_enter_exit_refcount(s: Src, rule: dict, form: str) -> None:
    declare_array(s, rule)
    s.body += init_array(s, "a") + [_enter(s), _enter(s)]
    s.body += _write_region(s, form) + [_exit(s, "from")]
    s.body += array_checks(s, "a", "i", "a")
    s.body.append(_dir(s, "target exit data map(delete: a)")
                  if s.model == "omp" else _dir(s, "exit data delete(a) "
                                                   "finalize"))


def t_enter_exit_once(s: Src, rule: dict, form: str) -> None:
    declare_array(s, rule)
    s.body += init_array(s, "a") + [_enter(s)]
    s.body += _write_region(s, form) + [_exit(s, "from")]
    s.body += array_checks(s, "a", "2*i + 1", "a")


def t_enter_exit_finalize(s: Src, rule: dict, form: str) -> None:
    declare_array(s, rule)
    s.body += init_array(s, "a") + [_enter(s), _enter(s)]
    s.body += _write_region(s, form) + [_dir(s, "exit data copyout(a) "
                                               "finalize")]
    s.body += array_checks(s, "a", "2*i + 1", "a")


def _copy_region(s: Src, form: str, extra: str = "") -> list:
    """b(i) = a(i) on the device, b returned."""
    construct = "target" if s.model == "omp" else "parallel loop"
    return region(s, construct,
                  _join(extra or _inner_present(s, form), map_out(s, "b")),
                  [stmt(s, f"{_el(s, 'b')} = {_el(s, 'a')}")],
                  loop=s.model == "omp")


def _b(s: Src) -> None:
    s.decls.append("integer :: b(n)" if s.f else "int b[n];")
    s.body += init_array(s, "b", "0")


def t_enter_data_stale(s: Src, rule: dict, form: str) -> None:
    declare_array(s, rule)
    _b(s)
    s.body += init_array(s, "a") + [_enter(s)] + init_array(s, "a", "100*i")
    s.body += _copy_region(s, form) + [_exit(s, "delete")]
    s.body += array_checks(s, "b", "i", "b")


def t_exit_delete_reenter(s: Src, rule: dict, form: str) -> None:
    declare_array(s, rule)
    _b(s)
    s.body += init_array(s, "a") + [_enter(s), _enter(s),
                                    _exit(s, "delete")]
    s.body += init_array(s, "a", "3*i") + [_enter(s)]
    s.body += _copy_region(s, form) + [_exit(s, "delete")]
    s.body += array_checks(s, "b", "3*i", "b")


def t_always_to(s: Src, rule: dict, form: str) -> None:
    declare_array(s, rule)
    _b(s)
    s.body += init_array(s, "a")
    body = init_array(s, "a", "3*i")
    if form == "rule":
        body += _copy_region(s, form, "map(always, to: a)")
    else:
        body += ["!$omp target update to(a)" if s.f else
                 "#pragma omp target update to(a)"] + \
            _copy_region(s, form, "map(to: a)")
    s.body += _data(s, "map(to: a)", body)
    s.body += array_checks(s, "b", "3*i", "b")


def t_always_from(s: Src, rule: dict, form: str) -> None:
    declare_array(s, rule)
    s.body += init_array(s, "a")
    a_el = _el(s, "a")
    cl = "map(always, from: a)" if form == "rule" else "map(from: a)"
    body = region(s, "target", cl, [stmt(s, f"{a_el} = 2*{a_el} + 1")],
                  loop=True)
    if form == "control":
        body.append("!$omp target update from(a)" if s.f else
                    "#pragma omp target update from(a)")
    body += array_checks(s, "a", "2*i + 1", "a")
    s.body += _data(s, "map(to: a)", body)


def t_combined_lastprivate(s: Src, rule: dict, form: str) -> None:
    s.int_("lp")
    s.body.append(stmt(s, "lp = -1"))
    cl = ["lastprivate(lp)"]
    collapse = "collapse(2)" in rule["clauses_present"]
    if collapse:
        cl.append("collapse(2)")
    if form == "control":
        cl.append("map(tofrom: lp)")
    c = rule["construct"]
    if collapse:
        if s.f:
            s.int_("j")
            s.body += [_dir(s, _join(c, *cl)), "do i = 1, 16", "  do j = 1, 8",
                       "    lp = i*j", "  end do", "end do",
                       _dir(s, "end " + c)]
        else:
            s.body += [_dir(s, _join(C_NAMES.get(c, c), *cl)),
                       "for (int i = 1; i <= 16; i++)",
                       "  for (int j = 1; j <= 8; j++)", "    lp = i*j;"]
        s.check("lp", 128)
    else:
        s.body += region(s, c, _join(*cl), [stmt(s, "lp = 3*i")])
        s.check("lp", 3 * N)


def t_combined_firstprivate(s: Src, rule: dict, form: str) -> None:
    s.int_("f")
    _b(s)
    s.body.append(stmt(s, "f = 7"))
    cl = "firstprivate(f)" if form == "rule" else "map(to: f)"
    s.body += region(s, rule["construct"], _join(cl, map_out(s, "b")),
                     [stmt(s, f"{_el(s, 'b')} = f + i")])
    s.body += array_checks(s, "b", "7 + i", "b")


def t_combined_first_lastprivate(s: Src, rule: dict, form: str) -> None:
    s.int_("lp")
    _b(s)
    s.body.append(stmt(s, "lp = 7"))
    cl = ["firstprivate(lp)", "lastprivate(lp)", map_out(s, "b")]
    if form == "control":
        cl.append("map(tofrom: lp)")
    inner = [stmt(s, f"{_el(s, 'b')} = lp + i"),
             "if (i == n) lp = lp + 100" if s.f else
             "if (i == n) lp = lp + 100;"]
    s.body += region(s, rule["construct"], _join(*cl), inner)
    s.check("lp", 107)
    s.body += array_checks(s, "b", "7 + i", "b")


def t_combined_reduction(s: Src, rule: dict, form: str) -> None:
    s.int_("s", "nn")
    s.body += [stmt(s, "s = 1000"), stmt(s, f"nn = {N}")]
    cl = ["reduction(+: s)"]
    dm = [c.replace(" ", "") for c in rule["clauses_present"]
          if c.startswith("defaultmap")]
    if form == "rule":
        cl += dm
    else:
        cl += [map_both(s, "s")] + (["map(to: nn)"] if dm else [])
    c = rule["construct"]
    if s.f:
        s.body += [_dir(s, _join(head_of(s, c), *cl)), "do i = 1, nn",
                   "  s = s + i", "end do", _dir(s, "end " + c)]
    else:
        s.body += [_dir(s, _join(head_of(s, c), *cl)),
                   "for (int i = 1; i <= nn; i++)", "  s += i;"]
    s.check("s", 1000 + N * (N + 1) // 2)


def t_acc_default_present_data(s: Src, rule: dict, form: str) -> None:
    declare_array(s, rule)
    s.body += init_array(s, "a") + [_enter(s)]
    a_el = _el(s, "a")
    reg = region(s, "parallel loop", "" if form == "rule" else "present(a)",
                 [stmt(s, f"{a_el} = 2*{a_el} + 1")])
    s.body += (_data(s, "default(present)", reg) if form == "rule" else reg)
    s.body += [_exit(s, "from")] + array_checks(s, "a", "2*i + 1", "a")


def t_c_pointer_unmapped(s: Src, rule: dict, form: str) -> None:
    """C: a pointer to host storage that is not mapped, referenced in a
    target region: its value on the device is the host address (5.1 and
    later: the pointer retains its original value) or NULL (5.0); the
    region copies it to pv (map from). Control: firstprivate(p) (retains)
    or map(tofrom: p[0:0]) (5.0's zero-length section, not present)."""
    if s.f:
        raise GenError("a C pointer: C only")
    null = rule["versions"] == ["5.0"]
    s.mod_decls.append("#include <stdint.h>")
    s.decls += ["int x[4] = {1, 2, 3, 4};", "int *p = x;",
                "uintptr_t pv = 1, hv = (uintptr_t)p;", "int same;"]
    if form == "rule":
        cl = ""
    else:
        cl = "map(tofrom: p[0:0])" if null else "firstprivate(p)"
    s.body += region(s, "target", _join(cl, "map(from: pv)"),
                     ["pv = (uintptr_t)p;"])
    s.body.append("same = (pv == 0) ? 0 : (pv == hv) ? 1 : 2;"
                  if not null else "same = (pv == 0) ? 0 : 1;")
    # retains: 1 (the host address); NULL: 0
    s.check("same", 0 if null else 1)


def t_c_is_device_ptr(s: Src, rule: dict, form: str) -> None:
    """C: storage from omp_target_alloc used through is_device_ptr(d); the
    region writes d[i-1] = 2*i + 1 and omp_target_memcpy brings it to h.
    Control: firstprivate(d) (the pointer keeps the device address)."""
    if s.f:
        raise GenError("is_device_ptr of a C pointer: C only")
    s.decls += ["int h[n];", "int dv = omp_get_default_device();",
                "int *d = (int *)omp_target_alloc(n * sizeof(int), dv);"]
    s.body += init_array(s, "h", "0")
    cl = "is_device_ptr(d)" if form == "rule" else "firstprivate(d)"
    s.body += region(s, "target", cl, ["d[i - 1] = 2*i + 1;"], loop=True)
    s.body += ["omp_target_memcpy(h, d, n * sizeof(int), 0, 0, "
               "omp_get_initial_device(), dv);", "omp_target_free(d, dv);"]
    s.body += array_checks(s, "h", "2*i + 1", "h")


def t_acc_update_self(s: Src, rule: dict, form: str) -> None:
    """enter data copyin(a); the loop (present) sets a(i) = 2*a(i) + 1;
    update self(a) brings it to the host while it stays present.
    Control: exit data copyout(a) (the last reference: the same
    transfer out)."""
    declare_array(s, rule)
    s.body += init_array(s, "a") + [_enter(s)]
    a_el = _el(s, "a")
    s.body += region(s, "parallel loop", "present(a)",
                     [stmt(s, f"{a_el} = 2*{a_el} + 1")])
    if form == "rule":
        s.body.append(_dir(s, "update self(a)"))
        s.body += array_checks(s, "a", "2*i + 1", "a")
        s.body.append(_dir(s, "exit data delete(a)"))
    else:
        s.body.append(_dir(s, "exit data copyout(a)"))
        s.body += array_checks(s, "a", "2*i + 1", "a")


def t_acc_update_device(s: Src, rule: dict, form: str) -> None:
    """enter data copyin(a); the host sets a(i) = 3*i; update device(a);
    the loop copies a to b (copyout): b(i) = 3*i. Control: exit data
    delete(a) and enter data copyin(a) (a new device copy from the host
    values)."""
    declare_array(s, rule)
    _b(s)
    s.body += init_array(s, "a") + [_enter(s)] + init_array(s, "a", "3*i")
    if form == "rule":
        s.body.append(_dir(s, "update device(a)"))
    else:
        s.body += [_dir(s, "exit data delete(a)"), _enter(s)]
    s.body += region(s, "parallel loop", "present(a) copyout(b)",
                     [stmt(s, f"{_el(s, 'b')} = {_el(s, 'a')}")])
    s.body.append(_dir(s, "exit data delete(a)"))
    s.body += array_checks(s, "b", "3*i", "b")


def t_loop_var(s: Src, rule: dict, form: str) -> None:
    """The loop variable k (host value 5) of a loop in the construct: an
    associated loop's (combined OpenMP loop construct, OpenACC parallel
    loop: b(k) = k, b returned) or a sequential loop in a target region's
    (the sum of k returned in rs). k is private: the host's k stays 5.
    Control: private(k)."""
    s.int_("k", "kk")
    s.body.append(stmt(s, "k = 5"))
    cl = "" if form == "rule" else "private(k)"
    c = rule["construct"]
    if is_loop_construct(c) or c == "parallel loop":
        _b(s)
        head = _join(head_of(s, c), cl, map_out(s, "b"))
        if s.f:
            s.body += [_dir(s, head), "do k = 1, n", "  b(k) = k", "end do",
                       _dir(s, "end " + c)]
        else:
            s.body += [_dir(s, head), "for (k = 1; k <= n; k++)",
                       "  b[k - 1] = k;"]
        s.body += array_checks(s, "b", "i", "b")
    else:
        s.int_("rs")
        s.body.append(stmt(s, "rs = 0"))
        if not s.f:
            raise GenError("a sequential loop's variable: Fortran rule")
        s.body += [_dir(s, _join("target", cl, "map(tofrom: rs)")),
                   "  do k = 1, n", "    rs = rs + k", "  end do",
                   _dir(s, "end target")]
        s.check("rs", _f_formula_sum("i"))
    s.body.append(stmt(s, "kk = k"))
    s.check("kk", 5)


def t_enter_data_after(s: Src, rule: dict, form: str) -> None:
    """target enter data map(to: a); a region with the row's clauses (the
    control: map(present, alloc: a)) sets a(i) = 2*a(i) + 1; target exit
    data map(from: a): the host sees 2*i + 1."""
    declare_array(s, rule)
    s.body += init_array(s, "a") + [_enter(s)]
    a_el = _el(s, "a")
    cl = _join(*rule_clauses(rule, "a")) if form == "rule" else \
        "map(present, alloc: a)"
    s.body += region(s, "target", cl, [stmt(s, f"{a_el} = 2*{a_el} + 1")],
                     loop=True)
    s.body.append(_exit(s, "from"))
    s.body += array_checks(s, "a", "2*i + 1", "a")


TEMPLATES = {
    "scalar_rw": t_scalar_rw, "array_rw": t_array_rw,
    "struct_rw": t_struct_rw, "c_pointer_rw": t_c_pointer_rw,
    "value_arg": t_value_arg, "struct_ptr_member": t_struct_ptr_member,
    "declare_target_roundtrip": t_declare_target_roundtrip,
    "declare_target_no_transfer": t_declare_target_no_transfer,
    "declare_target_link": t_declare_target_link,
    "declare_target_routine": t_declare_target_routine,
    "nested_data_inside": t_nested_data_inside,
    "nested_data_after": t_nested_data_after, "present_mod": t_present_mod,
    "enter_data_stale": t_enter_data_stale,
    "enter_exit_refcount": t_enter_exit_refcount,
    "enter_exit_once": t_enter_exit_once,
    "enter_exit_finalize": t_enter_exit_finalize,
    "exit_delete_reenter": t_exit_delete_reenter,
    "always_to": t_always_to, "always_from": t_always_from,
    "combined_lastprivate": t_combined_lastprivate,
    "combined_firstprivate": t_combined_firstprivate,
    "combined_first_lastprivate": t_combined_first_lastprivate,
    "combined_reduction": t_combined_reduction,
    "usm_array": t_usm_array, "usm_scalar": t_usm_scalar,
    "acc_declare_roundtrip": t_acc_declare_roundtrip,
    "acc_routine_global": t_acc_routine_global,
    "acc_declare_copyin": t_acc_declare_copyin,
    "acc_default_present_data": t_acc_default_present_data,
    "c_pointer_unmapped": t_c_pointer_unmapped,
    "c_is_device_ptr": t_c_is_device_ptr,
    "acc_update_self": t_acc_update_self,
    "acc_update_device": t_acc_update_device,
    "loop_var": t_loop_var,
    "enter_data_after": t_enter_data_after,
}


# --- rendering ---------------------------------------------------------------------------

def _header(rule: dict, form: str, expected: dict, comment: str) -> list:
    c = rule["spec"][0]
    cites = "; ".join(f"{x['version']} §{x['section']} p.{x['page']} "
                      f"l.{x['lines']}" for x in rule["spec"])
    out = [f"{comment} dataenv rule {rule['id']} ({form} form)",
           f"{comment} {rule['subject']}",
           f"{comment} spec: {cites}",
           f"{comment} \"{c['quote']}\"",
           f"{comment} expected (from the rule: dsa {rule['expected']['dsa']}, "
           f"map {rule['expected']['map_type']}, copy-back "
           f"{rule['expected']['copy_back']}): " +
           ", ".join(f"{k}= {v}" for k, v in expected.items())]
    return [_wrap(x, comment) for x in out]


def _wrap(line: str, comment: str, width: int = 100) -> str:
    if len(line) <= width:
        return line
    words, out, cur = line.split(" "), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            out.append(cur)
            cur = f"{comment}   {w}"
        else:
            cur = f"{cur} {w}" if cur else w
    out.append(cur)
    return "\n".join(out)


def _fortran(s: Src, rule: dict, form: str) -> str:
    exp = dict(s.checks)
    lines = _header(rule, form, exp, "!")
    lines += ["module dem", "  implicit none",
              f"  integer, parameter :: n = {N}"]
    lines += ["  " + x for x in s.mod_decls]
    if s.mod_procs:
        lines += ["contains"] + ["  " + x for x in s.mod_procs]
    lines += ["end module dem", "", "program de",
              "  use omp_lib" if s.model == "omp" else "  use openacc",
              "  use dem", "  implicit none"]
    if s.requires:
        lines.append(f"  !$omp requires {s.requires}")
    lines += ["  integer :: host_flag", "  logical :: ok", "  integer :: i"]
    lines += ["  " + x for x in s.decls]
    lines.append("  host_flag = 1")
    if s.model == "omp":
        lines += ["  !$omp target map(from: host_flag)",
                  "  host_flag = merge(1, 0, omp_is_initial_device())",
                  "  !$omp end target"]
    else:
        lines += ["  !$acc serial copy(host_flag)",
                  "  host_flag = merge(1, 0, acc_on_device(acc_device_host))",
                  "  !$acc end serial"]
    lines += ["  " + x for x in s.body]
    lines.append("  ok = .true.")
    for nm, v in s.checks:
        lines.append(f"  ok = ok .and. ({nm} == {v})")
    for nm, _ in s.checks:
        lines.append(f"  print '(a,i0)', '{nm}= ', {nm}")
    lines += ["  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, "
              "' check=', merge('pass', 'fail', ok)",
              "end program de", ""]
    return "\n".join(lines)


def _c(s: Src, rule: dict, form: str) -> str:
    exp = dict(s.checks)
    lines = _header(rule, form, exp, "//")
    lines += ["#include <stdio.h>", "#include <stdlib.h>",
              "#include <omp.h>" if s.model == "omp" else
              "#include <openacc.h>"]
    if s.requires:
        lines.append(f"#pragma omp requires {s.requires}")
    lines += ["", f"enum {{ n = {N} }};", ""] + s.mod_decls + [""]
    lines += s.mod_procs + ["", "int main(void)", "{",
                            "  int host_flag = 1;", "  int ok;"]
    lines += ["  " + x for x in s.decls]
    if s.model == "omp":
        lines += ["  #pragma omp target map(from: host_flag)",
                  "  host_flag = omp_is_initial_device() ? 1 : 0;"]
    else:
        lines += ["  #pragma acc serial copy(host_flag)",
                  "  host_flag = acc_on_device(acc_device_host) ? 1 : 0;"]
    lines += ["  " + x for x in s.body]
    lines.append("  ok = 1;")
    for nm, v in s.checks:
        lines.append(f"  ok = ok && ({nm} == {v});")
    for nm, _ in s.checks:
        lines.append(f"  printf(\"{nm}= %d\\n\", {nm});")
    lines += ["  printf(\"RESULT ran_on_host=%d check=%s\\n\", host_flag, "
              "ok ? \"pass\" : \"fail\");", "  return 0;", "}", ""]
    return "\n".join(lines)


def version_of(rule: dict) -> int:
    """The version a rule's programs are written for: 5.2 when the rule
    has it, else its newest (a 5.0-only rule: 5.0)."""
    if rule["model"] == "acc":
        return ACC_VERSION
    vs = rule["versions"]
    return 52 if "5.2" in vs else 60 if "6.0" in vs else 50


def _pid(rule: dict, lang: str, form: str) -> str:
    v = version_of(rule)
    stem = re.sub(r"[^A-Za-z0-9]+", "_", rule["id"])
    return f"{rule['model']}{v}-de_{stem}_{lang}_{form}"


def program(rule: dict, lang: str, form: str) -> Program:
    if rule["template"] not in TEMPLATES:
        raise GenError(f"{rule['id']}: no template {rule['template']}")
    if lang not in rule["languages"]:
        raise GenError(f"{rule['id']}: not written in {lang}")
    if form == "opposite" and rule["template"] not in OPPOSITE:
        raise GenError(f"{rule['id']}: no oracle mutant for template "
                       f"{rule['template']}")
    if form == "opposite" and rule["construct"] == "kernels" and \
            rule["expected"]["copy_back"] == "yes" and \
            rule["variable_kind"] == "scalar":
        # firstprivate is not allowed on kernels (OpenACC 3.4 §2.5.3)
        raise GenError(f"{rule['id']}: no oracle mutant on kernels")
    s = Src(lang, rule["model"], form=form)
    TEMPLATES[rule["template"]](s, rule, form)
    if not s.checks:
        raise GenError(f"{rule['id']}: no observable")
    src = _fortran(s, rule, form) if lang == "f90" else _c(s, rule, form)
    modes = {"any": ("copy", "unified"), "copy": ("copy",),
             "unified": ("unified",)}[rule["memory_mode"]]
    return Program(id=_pid(rule, lang, form), rule=rule["id"], lang=lang,
                   form=form, model=rule["model"],
                   version=version_of(rule), source=src, expected=dict(s.checks),
                   modes=modes, observable=rule["observable"])


def oracle_mutant(rule: dict, lang: str) -> Program | None:
    """The control with the opposite attribute (``opposite_clause``),
    keeping the rule's expected values: a correct implementation fails
    its check, so a run that passes shows an observable that does not
    separate the rule's attribute from the other (the oracle audit). None
    for a template without one."""
    try:
        return program(rule, lang, "opposite")
    except GenError:
        return None


def programs(rule: dict) -> list[Program]:
    """One program per (rule, language, form): the rule form and its
    control, in each language of the row."""
    return [program(rule, lang, form) for lang in rule["languages"]
            for form in ("rule", "control")]


def prerun_check(p: Program) -> dict:
    """The offload.engine.prerun.check of a generated program (both
    witnesses; it stubs openacc.h for C OpenACC itself): {id, ok,
    reasons}."""
    from offload.engine import prerun
    ok, why = prerun.check(p)
    return {"id": p.id, "ok": ok, "reasons": why}


def parse_observed(stdout: str) -> dict:
    """name -> integer of the ``name= value`` lines of a run."""
    return {m.group(1): int(m.group(2)) for m in
            re.finditer(r"^(\w+)= (-?\d+)\s*$", stdout or "", re.M)}
