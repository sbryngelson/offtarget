"""Predicates of the OpenACC 3.4 restriction rules (catalog/acc/rules.yaml).

Each function is registered with ``offload.engine.rules.predicate`` and reads a
``ProgramTree`` built by ``offload.engine.rules.parse_program(source, 34)``. The
rules file names them, and ``offload.engine.rules.acc_rules`` imports this module
before it loads the file. As for the OpenMP predicates, each returns the
indices of the offending directives and checks only what the source shows
(a value only when it is an integer literal, nesting only when the enclosing
construct is in the same source).

Predicate names start with ``acc_`` because the registry is shared with the
OpenMP predicates and rejects duplicates. Clause names are the skeleton key
whatever the spelling (``pcopy`` is ``copy``, ``dtype`` is ``device_type``).
Clauses after a ``device_type`` clause are device-specific (3.4 section 2.4);
``_sections`` splits a directive's clauses at each ``device_type``."""
from __future__ import annotations

import re
from functools import lru_cache

from offload.engine.catalog import base_name, default_skeleton
from offload.engine.rules import (_DO, _END_DO, ProgramTree, _base, _each,
                              _int, _is_do, _norm, leaves, predicate)

MODEL = "acc"
COMPUTE = ("parallel", "serial", "kernels")
LEVEL_CLAUSES = ("gang", "worker", "vector")
DATA_CLAUSES = ("copy", "copyin", "copyout", "create", "no_create", "present",
                "deviceptr", "attach")
# clauses that may follow a device_type clause (3.4 §2.5.4 p.36, §2.6.5
# p.44, §2.9 p.65, §2.14.4 p.90, §2.15.1 p.93)
AFTER_DTYPE = {
    "compute": {"async", "wait", "num_gangs", "num_workers",
                "vector_length"},
    "data": {"async", "wait"},
    "loop": {"collapse", "gang", "worker", "vector", "seq", "independent",
             "auto", "tile"},
    "update": {"async", "wait"},
    "routine": {"gang", "worker", "vector", "seq", "bind"},
}


@lru_cache(maxsize=1)
def _alias() -> dict:
    """Clause spelling -> clause name (pcopy -> copy, dtype ->
    device_type)."""
    return {s["text"]: base_name(k)
            for k, c in default_skeleton(MODEL).clauses.items()
            for s in c["spellings"]}


def cname(clause) -> str:
    return _alias().get(clause.name, clause.name)


def _lv(tree: ProgramTree, i: int) -> list[str]:
    return leaves(tree.directives[i].name, MODEL)


def _cl(tree: ProgramTree, i: int, *names: str) -> list:
    return [c for c in tree.directives[i].clauses
            if not names or cname(c) in names]


def _sections(tree: ProgramTree, i: int) -> list[list]:
    """The directive's clauses split at each device_type clause: the
    default clauses first, then one list per device_type clause (without
    it)."""
    out = [[]]
    for c in tree.directives[i].clauses:
        if cname(c) == "device_type":
            out.append([])
        else:
            out[-1].append(c)
    return out


def _after_dtype(tree: ProgramTree, i: int) -> set[str]:
    return {cname(c) for sec in _sections(tree, i)[1:] for c in sec}


def _ancestors(tree: ProgramTree, i: int) -> list[int]:
    out, p = [], tree.parent(i)
    while p is not None:
        out.append(p)
        p = tree.parent(p)
    return out


def _is_compute(tree: ProgramTree, i: int) -> bool:
    return _lv(tree, i)[0] in COMPUTE


def parent_compute(tree: ProgramTree, i: int) -> int | None:
    """The directive's own compute construct (a combined construct) or
    the nearest enclosing one, None if none is in the source."""
    if _is_compute(tree, i):
        return i
    return next((a for a in _ancestors(tree, i) if _is_compute(tree, a)),
                None)


def _items(clauses) -> list[str]:
    return [_norm(a) for c in clauses for a in c.args]


# --- device_type -------------------------------------------------------------

def _is_compute_d(tree, i) -> bool:
    return _lv(tree, i)[0] in COMPUTE


def _named(name: str):
    return lambda tree, i: tree.directives[i].name == name


def _dtype_rule(kind: str, test):
    def check(tree, version):
        def bad(i):
            if not test(tree, i):
                return False
            allowed = set(AFTER_DTYPE[kind])
            if kind == "compute" and "loop" in _lv(tree, i):
                allowed |= AFTER_DTYPE["loop"]  # combined: either set
            return bool(_after_dtype(tree, i) - allowed)
        return _each(tree, bad)
    return check


def _register(name: str, fn) -> None:
    fn.__name__ = name
    predicate(fn)


for _name, _kind, _test in (
        ("acc_compute_after_device_type", "compute", _is_compute_d),
        ("acc_data_after_device_type", "data", _named("data")),
        ("acc_loop_after_device_type", "loop", _named("loop")),
        ("acc_update_after_device_type", "update", _named("update")),
        ("acc_routine_after_device_type", "routine", _named("routine"))):
    _register(_name, _dtype_rule(_kind, _test))


# --- compute constructs ------------------------------------------------------

def _num_gangs_args(tree, i) -> int:
    return max((len(c.args) for c in _cl(tree, i, "num_gangs")), default=0)


@predicate
def acc_reduction_with_multi_num_gangs(tree, version):
    """A reduction clause on a parallel construct whose num_gangs clause has
    more than one argument (3.4 §2.5.4)."""
    return _each(tree, lambda i: _lv(tree, i)[0] == "parallel"
                 and bool(_cl(tree, i, "reduction"))
                 and _num_gangs_args(tree, i) > 1)


@predicate
def acc_kernels_num_gangs_single(tree, version):
    """num_gangs with more than one argument on a kernels construct."""
    return _each(tree, lambda i: _lv(tree, i)[0] == "kernels"
                 and _num_gangs_args(tree, i) > 1)


@predicate
def acc_parallel_num_gangs_three(tree, version):
    """num_gangs with more than three arguments on a parallel construct."""
    return _each(tree, lambda i: _lv(tree, i)[0] == "parallel"
                 and _num_gangs_args(tree, i) > 3)


@predicate
def acc_host_only_directive_in_compute(tree, version):
    """init, shutdown or set inside a compute construct (code executed on
    the device)."""
    return _each(tree, lambda i: tree.directives[i].name in (
        "init", "shutdown", "set") and parent_compute(tree, i) is not None)


# --- loop --------------------------------------------------------------------

def _is_loop(tree, i) -> bool:
    return "loop" in _lv(tree, i)


@predicate
def acc_loop_seq_with_level(tree, version):
    """seq with gang, worker or vector in the same device-type section of a
    loop construct."""
    def bad(i):
        if not _is_loop(tree, i):
            return False
        secs = _sections(tree, i)
        default = {cname(c) for c in secs[0]}
        for k, sec in enumerate(secs):
            names = {cname(c) for c in sec} | (default if k else set())
            if "seq" in names and names & set(LEVEL_CLAUSES):
                return True
        return False
    return _each(tree, bad)


@predicate
def acc_loop_one_gang(tree, version):
    """More than one gang clause on a loop construct."""
    return _each(tree, lambda i: _is_loop(tree, i)
                 and len(_cl(tree, i, "gang")) > 1)


def _gang_dim(clause) -> int | None:
    args = [_norm(a) for a in clause.args]
    if "dim" in args and args.index("dim") + 1 < len(args):
        return _int(args[args.index("dim") + 1])
    return None


def _levels(tree, i) -> list[int]:
    """Parallelism levels the loop's gang, worker, vector clauses specify:
    vector 1, worker 2, gang(dim:d) 2 + d (gang without dim: d = 1)."""
    out = []
    for c in _cl(tree, i, *LEVEL_CLAUSES):
        n = cname(c)
        if n == "vector":
            out.append(1)
        elif n == "worker":
            out.append(2)
        else:
            out.append(2 + (_gang_dim(c) or 1))
    return out


@predicate
def acc_loop_level_nesting(tree, version):
    """A loop construct with gang, worker or vector lexically inside one
    whose lowest level is at most the inner one's highest, with the same
    parent compute scope (no compute construct between them)."""
    def bad(j):
        if not _is_loop(tree, j) or not _levels(tree, j):
            return False
        inner = max(_levels(tree, j))
        for a in _ancestors(tree, j):
            if _is_compute(tree, a) and not _is_loop(tree, a):
                return False  # a compute construct: another scope
            if _is_loop(tree, a) and _levels(tree, a) \
                    and inner >= min(_levels(tree, a)):
                return True
            if _is_compute(tree, a):
                return False  # a combined construct ends the scope
        return False
    return _each(tree, bad)


def _gang_has(tree, i, feature) -> bool:
    return f"acc.clause.gang.{feature}" in tree.directives[i].atoms


@predicate
def acc_gang_num_outside_kernels(tree, version):
    """A gang num argument on a loop whose parent compute construct is not
    a kernels construct (parallel, serial, or an orphaned loop)."""
    def bad(i):
        if not _is_loop(tree, i) or not _gang_has(tree, i, "num"):
            return False
        p = parent_compute(tree, i)
        return p is None or _lv(tree, p)[0] != "kernels"
    return _each(tree, bad)


@predicate
def acc_gang_dim_in_kernels(tree, version):
    """A gang dim argument on a loop whose parent compute construct is a
    kernels construct."""
    def bad(i):
        p = parent_compute(tree, i)
        return _is_loop(tree, i) and _gang_has(tree, i, "dim") and \
            p is not None and _lv(tree, p)[0] == "kernels"
    return _each(tree, bad)


@predicate
def acc_gang_dim_range(tree, version):
    """A gang dim argument that is an integer literal other than 1, 2, 3
    (loop and routine)."""
    return _each(tree, lambda i: any(
        (d := _gang_dim(c)) is not None and d not in (1, 2, 3)
        for c in _cl(tree, i, "gang")))


def _collapse(tree, i) -> tuple[int | None, bool]:
    for c in _cl(tree, i, "collapse"):
        args = [_norm(a) for a in c.args]
        return _int(args[-1]), "force" in args[:-1]
    return None, False


@predicate
def acc_collapse_positive(tree, version):
    """A collapse argument that is an integer literal below 1."""
    return _each(tree, lambda i: (n := _collapse(tree, i)[0]) is not None
                 and n < 1)


@predicate
def acc_collapse_within_depth(tree, version):
    """collapse(n) on a loop construct followed by fewer than n nested DO
    loops each containing exactly one loop."""
    def bad(i):
        n = _collapse(tree, i)[0]
        a = tree.assoc[i]
        return n is not None and n > 1 and a.depth_known \
            and a.loop_depth < n
    return _each(tree, bad)


@predicate
def acc_collapse_tightly_nested(tree, version):
    """collapse(n) without force whose associated loops are not tightly
    nested (statements in a loop body besides the next associated loop)."""
    def bad(i):
        n, force = _collapse(tree, i)
        a = tree.assoc[i]
        if n is None or n < 2 or force or a.loop_depth < n:
            return False
        return any(a.intervening[k] for k in range(n - 1)
                   if k < len(a.intervening))
    return _each(tree, bad)


def _tile_sizes(tree, i) -> list[str]:
    return [_norm(a) for c in _cl(tree, i, "tile") for a in c.args]


@predicate
def acc_tile_within_depth(tree, version):
    """tile with n sizes on a loop construct followed by fewer than n
    tightly nested loops."""
    def bad(i):
        sizes = _tile_sizes(tree, i)
        a = tree.assoc[i]
        return bool(sizes) and a.depth_known and a.loop_depth < len(sizes)
    return _each(tree, bad)


@predicate
def acc_tile_size_positive(tree, version):
    """A tile size that is an integer literal below 1."""
    return _each(tree, lambda i: any(
        (v := _int(s)) is not None and v < 1 for s in _tile_sizes(tree, i)))


# --- data --------------------------------------------------------------------

@predicate
def acc_use_device_variable_name(tree, version):
    """A use_device list item that is not a variable or array name (an
    array element, section or component)."""
    # In C an element, section or member has [ . or ->
    marks = ("[", ".", "->") if tree.lang == "c" else ("(", "%")
    return _each(tree, lambda i: any(
        m in x for x in _items(_cl(tree, i, "use_device")) for m in marks))


def _unit_kind(tree, i) -> str | None:
    scope = tree.assoc[i].scope
    return tree.units.get(scope[-1], (None,))[0] if scope else None


@predicate
def acc_declare_module_clauses(tree, version):
    """A declare directive in a module's specification part with a clause
    other than create, copyin, device_resident or link."""
    ok = {"create", "copyin", "device_resident", "link"}
    return _each(tree, lambda i: tree.directives[i].name == "declare"
                 and _unit_kind(tree, i) == "module"
                 and any(cname(c) not in ok for c in _cl(tree, i)))


@predicate
def acc_declare_var_once(tree, version):
    """A var in more than one clause of the declare directives of one
    program unit or subprogram."""
    seen: dict = {}
    out = []
    for i, d in enumerate(tree.directives):
        if d.name != "declare":
            continue
        scope = tree.assoc[i].scope[-1] if tree.assoc[i].scope else 0
        for x in map(_base, _items(_cl(tree, i))):
            if (scope, x) in seen:
                out.append(i)
            seen[(scope, x)] = i
    return sorted(set(out))


@predicate
def acc_declare_link_placement(tree, version):
    """A declare link clause outside a module specification part whose
    arguments are not all common block names (/name/)."""
    return _each(tree, lambda i: tree.directives[i].name == "declare"
                 and _unit_kind(tree, i) != "module"
                 and any(not x.startswith("/")
                         for x in _items(_cl(tree, i, "link"))))


@predicate
def acc_declare_same_scope(tree, version):
    """A declare directive naming a variable declared in another scoping
    unit (a host or the module of the program), when the declaration is in
    the source."""
    def bad(i):
        if tree.directives[i].name != "declare":
            return False
        scope = tree.assoc[i].scope
        for x in map(_base, _items(_cl(tree, i))):
            if x.startswith("/"):
                continue
            hit = tree._find(scope, x, tree.decls)
            if hit is not None and hit[0][-1] != scope[-1]:
                return True
        return False
    return _each(tree, bad)


@predicate
def acc_attach_pointer_or_allocatable(tree, version):
    """An attach or detach list item declared without the pointer or
    allocatable attribute (when its declaration is in the source)."""
    return _each(tree, lambda i: any(
        tree.designator_attribute(i, x) == "plain"
        for x in _items(_cl(tree, i, "attach", "detach"))))


@predicate
def acc_deviceptr_attribute(tree, version):
    """A deviceptr list item declared with the pointer or allocatable
    attribute."""
    return _each(tree, lambda i: any(
        tree.designator_attribute(i, x) in ("pointer", "allocatable")
        for x in _items(_cl(tree, i, "deviceptr"))))


# --- routine, atomic, cache --------------------------------------------------

@predicate
def acc_routine_one_level(tree, version):
    """A routine directive without device_type clauses that has not exactly
    one of gang, worker, vector, seq."""
    def bad(i):
        if tree.directives[i].name != "routine" or len(
                _sections(tree, i)) > 1:
            return False
        return len(_cl(tree, i, *LEVEL_CLAUSES, "seq")) != 1
    return _each(tree, bad)


@predicate
def acc_routine_placement(tree, version):
    """A routine directive without a name outside the specification part
    of a subroutine or function (in a main program or a module)."""
    return _each(tree, lambda i: tree.directives[i].name == "routine"
                 and not tree.directives[i].args
                 and _unit_kind(tree, i) in ("program", "module"))


@predicate
def acc_atomic_one_clause(tree, version):
    """More than one atomic-clause (read, write, update, capture)."""
    return _each(tree, lambda i: tree.directives[i].name == "atomic"
                 and len(_cl(tree, i, "read", "write", "update",
                             "capture")) > 1)


def _do_ranges(tree) -> list[tuple[int, int]]:
    """(DO line, END DO line) of the block DO loops of the source."""
    out, stack = [], []
    for line, stmt, _ in tree.statements:
        if _is_do(stmt):
            stack.append(line)
        elif _END_DO.match(stmt) and stack:
            out.append((stack.pop(), line))
    return out


@predicate
def acc_cache_in_loop(tree, version):
    """A cache directive that is not inside a DO loop."""
    def bad(i):
        if tree.directives[i].name != "cache":
            return False
        ln = tree.assoc[i].line
        if tree.lang == "c":
            # C reading: inside the loop of an enclosing
            # loop-associated directive (a cache in a for loop without one
            # is flagged too: stricter, never more lenient)
            return not any(
                p == i and tree.assoc[q].kind == "loop"
                and tree.assoc[q].line < ln <= tree.assoc[q].end_line
                for q, p in tree.nesting)
        return not any(a < ln < b for a, b in _do_ranges(tree))
    return _each(tree, bad)


@predicate
def acc_cache_element_or_subarray(tree, version):
    """A cache var that is a whole variable name, not an array element or
    subarray."""
    mark = "[" if tree.lang == "c" else "("  # C subscripts
    return _each(tree, lambda i: tree.directives[i].name == "cache" and any(
        mark not in a for a in (re.sub(r"^\s*readonly\s*:\s*", "", x)
                                for x in tree.directives[i].args)))


# --- data-sharing ------------------------------------------------------------

def _reductions(tree, i) -> dict[str, str]:
    """var -> reduction operator of the directive's reduction clauses."""
    out = {}
    for c in _cl(tree, i, "reduction"):
        op = _norm(c.modifiers[0]) if c.modifiers else ""
        for x in c.args:
            out[_base(_norm(x))] = op
    return out


@predicate
def acc_reduction_same_operator(tree, version):
    """A reduction var of a construct nested in another construct that
    reduces the same var with another operator."""
    def bad(j):
        mine = _reductions(tree, j)
        return any(op != _reductions(tree, a).get(x, op)
                   for a in _ancestors(tree, j) for x, op in mine.items())
    return _each(tree, bad)


@predicate
def acc_reduction_not_member(tree, version):
    """A reduction var that is a member of a composite variable."""
    return _each(tree, lambda i: any(
        "%" in x for x in _items(_cl(tree, i, "reduction"))))


_DATA_OR_DSA = DATA_CLAUSES + ("copy", "firstprivate", "private",
                               "reduction")


def _visible_listed(tree, p: int, x: str) -> bool:
    """x appears in a data clause or a private/firstprivate/reduction
    clause on compute construct p, or in a data clause of a data
    construct around p, or of a declare directive of its scoping unit."""
    if x in map(_base, _items(_cl(tree, p, *_DATA_OR_DSA))):
        return True
    for a in _ancestors(tree, p):
        if tree.directives[a].name == "data" and x in map(
                _base, _items(_cl(tree, a, *DATA_CLAUSES))):
            return True
    scope = tree.assoc[p].scope
    for k, d in enumerate(tree.directives):
        if d.name == "declare" and tree.assoc[k].scope and \
                tree.assoc[k].scope[-1] in scope and \
                x in map(_base, _items(_cl(tree, k))):
            return True
    return False


@predicate
def acc_loop_reduction_scalar_listed(tree, version):
    """A scalar reduction var of a loop construct (not combined) whose
    parent compute construct is parallel or serial, where the var is not
    in a visible data clause or a private, firstprivate or reduction
    clause of the compute construct (3.4 §2.6.2)."""
    def bad(i):
        if tree.directives[i].name != "loop":
            return False
        p = parent_compute(tree, i)
        if p is None or _lv(tree, p)[0] not in ("parallel", "serial"):
            return False
        for x in _reductions(tree, i):
            if tree.attribute(i, x) is None or _is_array(tree, i, x):
                continue  # not a scalar declared in the source
            between = [a for a in _ancestors(tree, i) if a != p and
                       p in _ancestors(tree, a)]
            if any(x in map(_base, _items(_cl(tree, a, "private",
                                                "reduction")))
                   for a in between):
                continue  # privatized or reduced in between: not exposed
            if not _visible_listed(tree, p, x):
                return True
        return False
    return _each(tree, bad)


def _is_array(tree, i, x) -> bool:
    hit = tree._find(tree.assoc[i].scope, x, tree.decls)
    return hit is not None and (hit[0][-1], x) in tree.arrays


_KEYWORDS = frozenset("""
do end if then else elseif endif enddo while call print write read merge all
any size allocate deallocate return stop continue exit cycle program module
contains subroutine function result implicit none integer logical real
character type class intent in out inout value optional target pointer
allocatable dimension parameter save use only true false and or not eqv neqv
max min mod abs sum product iand ior ieor associated present kind len huge
""".split())
_NAME = re.compile(r"(?<![%\w.])([a-z_]\w*)(?!\s*=[^=])?")


def _referenced(tree, i) -> set[str]:
    """Declared variables referenced in the base-language statements of
    construct i (strings removed), except the DO variables of loops inside
    it (predetermined private)."""
    a = tree.assoc[i]
    lo, hi = a.line, a.end_line if a.end_line is not None else a.line
    scope = a.scope
    names, dovars = set(), set()
    for ln, stmt, _ in tree.statements:
        if not lo < ln <= hi:
            continue
        text = re.sub(r"'[^']*'|\"[^\"]*\"", " ", stmt)
        m = _DO.match(text)
        if _is_do(text) and m and "=" in m.group(1):
            dovars.add(m.group(1).split("=")[0].strip())
        for x in re.findall(r"(?<![%\w])([a-z_]\w*)", text):
            if x in _KEYWORDS:
                continue
            hit = tree._find(scope, x, tree.decls)
            if hit is not None and (hit[0][-1], x) not in tree.params:
                names.add(x)
    return names - dovars


@predicate
def acc_default_none_listed(tree, version):
    """A compute construct with a visible default(none) clause (its own or
    a data construct's around it) referencing a declared variable that is
    in no visible data clause and in no private, firstprivate or reduction
    clause of the construct (DO variables of loops inside are
    predetermined private)."""
    def none_visible(i):
        for k in [i] + [a for a in _ancestors(tree, i)
                        if tree.directives[a].name == "data"]:
            for c in _cl(tree, k, "default"):
                return [_norm(x) for x in c.args] == ["none"]
        return False

    def bad(i):
        if not _is_compute(tree, i) or not none_visible(i):
            return False
        reductions_inside = {x for d in tree.descendants(i)
                             for x in _reductions(tree, d)}
        return any(not _visible_listed(tree, i, x)
                   and x not in reductions_inside
                   for x in _referenced(tree, i))
    return _each(tree, bad)
