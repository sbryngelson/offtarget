"""Predicates of the C rules: the C/C++ restriction sentences of
OpenMP 5.2 and 6.0 that the source decides, for ``lang: c`` entries of
catalog/omp/rules.yaml. They read the C facts of ``offload.engine.c_program``
(``tree.extra``: ``ctypes``, ``loops``, ``jumps``, ``iters``,
``substatement``, ``struct_members``) and are registered in the shared
predicate registry of ``offload.engine.rules`` (imported at its end).

Each predicate checks only what the source shows: a type condition when
the list item's declaration is visible in the source, a value condition
when the value is an integer literal.
"""
from __future__ import annotations

import re

from offload.engine.rules import (_DSA, _EXPLICIT_DSA, _base, _c_construct_refs,
                              _c_sections, _clauses, _decl_scope, _each,
                              _int, _items, _norm, _section_base, association,
                              predicate)


def _ctype(tree, i, name) -> str | None:
    s = _decl_scope(tree, i, name)
    if s is None:
        return None
    return tree.extra.get("ctypes", {}).get((s, name))


def _class(tree, i, name) -> str | None:
    s = _decl_scope(tree, i, name)
    return None if s is None else tree.vtypes.get((s, name))


def _is_pointer(tree, i, name) -> bool:
    return tree.attribute(i, name) == "pointer"


def _is_array(tree, i, name) -> bool:
    s = _decl_scope(tree, i, name)
    return s is not None and (s, name) in tree.arrays


def _c(tree) -> bool:
    return getattr(tree, "lang", "f90") == "c"


# --- placement ---------------------------------------------------------------

@predicate
def c_requires_at_file_scope(tree, version):
    """A requires directive not at file scope (in a function body)."""
    return _each(tree, lambda i: _c(tree)
                 and tree.directives[i].name == "requires"
                 and tree.assoc[i].scope != (0,))


@predicate
def c_directive_substatement(tree, version):
    """A stand-alone or declarative directive written as the substatement
    of a selection (if/else, switch) or iteration statement or after a
    label (scanner fact ``substatement``)."""
    return sorted(tree.extra.get("substatement", ())) if _c(tree) else []


@predicate
def c_declare_target_same_scope(tree, version):
    """A declare target directive with an extended list or clauses naming
    a variable declared (visibly) in another scope than the directive's
    (6.0)."""
    def bad(i):
        d = tree.directives[i]
        if d.name != "declare target":
            return False
        xs = [_norm(a) for a in d.args] + _items(_clauses(
            tree, i, "enter", "to", "link", "local"))
        for x in map(_base, xs):
            s = _decl_scope(tree, i, x)
            if s is not None and s != tree.assoc[i].scope[-1]:
                return True
        return False
    return _each(tree, bad) if _c(tree) else []


# --- canonical loop nests ------------------------------------------------------

def _canon(tree, i) -> list[dict]:
    return tree.extra.get("loops", {}).get(i, {}).get("canon", [])


def _n_assoc(tree, i) -> int:
    from offload.engine.rules import _assoc_count
    a = tree.assoc[i]
    n = _assoc_count(tree, i) or 1
    return min(n, a.loop_depth) if a.loop_depth else 0


def _direction(c: dict) -> str | None:
    """"+" or "-": the direction of the increment, None when unknown (a
    non-literal step)."""
    step = c.get("step", "")
    v = _int(step) if step else None
    if v is None:
        return None
    if v == 0:
        return "0"
    sign = c["sign"]
    if v < 0:
        sign = "-" if sign == "+" else "+"
    return sign


def _wrong_direction(c: dict, var_left: bool) -> bool:
    if c.get("var_left") != var_left or c.get("relop") == "!=":
        return False
    d = _direction(c)
    if d is None:
        return False
    up = c["relop"] in ("<", "<=")
    want = "+" if up == var_left else "-"
    return d != want


@predicate
def c_loop_increment_direction_var_left(tree, version):
    """An associated loop with test-expr ``var relop b``: relop < or <=
    with a literal step that decreases var, or > or >= with one that
    increases it."""
    return _each(tree, lambda i: _c(tree) and any(
        _wrong_direction(c, True) for c in _canon(tree, i)[:_n_assoc(
            tree, i)]))


@predicate
def c_loop_increment_direction_ub_left(tree, version):
    """An associated loop with test-expr ``ub relop var``: relop < or <=
    with a literal step that increases var, or > or >= with one that
    decreases it."""
    return _each(tree, lambda i: _c(tree) and any(
        _wrong_direction(c, False) for c in _canon(tree, i)[:_n_assoc(
            tree, i)]))


@predicate
def c_loop_ne_unit_step(tree, version):
    """An associated loop with relop != whose increment is not a literal
    1 or -1 (a constant expression other than +-1, or not an integer
    literal)."""
    def bad(c):
        if c.get("relop") != "!=":
            return False
        v = _int(c.get("step", "") or "x")
        return v is None or abs(v) != 1
    return _each(tree, lambda i: _c(tree) and any(
        bad(c) for c in _canon(tree, i)[:_n_assoc(tree, i)]))


@predicate
def c_loop_var_integer_or_pointer(tree, version):
    """An associated loop whose iteration variable is declared with a type
    that is neither an integer type (``_Bool`` included, an unsigned
    integer type in C11 §6.2.5) nor a pointer type."""
    def bad(i):
        from offload.engine.rules import _assoc_vars
        vs = _assoc_vars(tree, i)
        canon = _canon(tree, i)
        for k, v in enumerate(vs or ()):
            c = canon[k] if k < len(canon) else {}
            if c.get("declared"):
                words = c["type"].replace("*", " * ").split()
                if "*" in words:
                    continue
                if set(words) & {"float", "double", "struct", "union"}:
                    return True
                continue
            cls = _class(tree, i, v)
            if cls in ("real", "type") and not _is_pointer(tree, i, v):
                return True
        return False
    return _each(tree, bad) if _c(tree) else []


def _chain_ids(tree, i) -> list:
    return tree.extra.get("loops", {}).get(i, {}).get("chain", [])


@predicate
def c_intervening_no_iteration_or_jump(tree, version):
    """Intervening code of a collapsed loop nest with an iteration
    statement (for, while, do) other than the next associated loop, or a
    continue or break statement that applies to an associated loop other
    than the innermost one."""
    def bad(i):
        chain = _chain_ids(tree, i)[:_n_assoc(tree, i)]
        if len(chain) < 2:
            return False
        outer = chain[:-1]
        for _, fors, own in tree.extra.get("iters", []):
            # the innermost associated loop around the statement
            inside = [f for f in fors if f in chain]
            if not inside or own in chain:
                continue
            if inside[-1] in outer and fors[-1] == inside[-1]:
                return True
        for kind, _, target, fors in tree.extra.get("jumps", []):
            if target in outer:
                return True
        return False
    return _each(tree, bad) if _c(tree) else []


@predicate
def c_final_body_no_break(tree, version):
    """A break statement that terminates the innermost associated loop."""
    def bad(i):
        chain = _chain_ids(tree, i)[:_n_assoc(tree, i)]
        return bool(chain) and any(
            kind == "break" and target == chain[-1]
            for kind, _, target, _ in tree.extra.get("jumps", []))
    return _each(tree, bad) if _c(tree) else []


# --- list item types --------------------------------------------------------------

def _items_of(tree, i, *names) -> list[str]:
    return [_base(x) for x in _items(_clauses(tree, i, *names))]


def _scalar_non_pointer(tree, i, x) -> bool:
    """x is declared in the source as a scalar that is not a pointer."""
    s = _decl_scope(tree, i, x)
    return s is not None and not _is_array(tree, i, x) and \
        tree.attribute(i, x) == "plain"


@predicate
def c_linear_integral_or_pointer(tree, version):
    """A linear list item declared with a type that is neither integral
    (_Bool included) nor a pointer type."""
    return _each(tree, lambda i: _c(tree) and any(
        _class(tree, i, x) in ("real", "type", "other")
        and not _is_pointer(tree, i, x)
        for x in _items_of(tree, i, "linear")))


@predicate
def c_aligned_array_or_pointer(tree, version):
    """An aligned list item declared as a scalar that is not a pointer."""
    return _each(tree, lambda i: _c(tree) and any(
        _scalar_non_pointer(tree, i, x)
        for x in _items_of(tree, i, "aligned")))


@predicate
def c_is_device_ptr_pointer_or_array(tree, version):
    """An is_device_ptr list item declared as a scalar that is not a
    pointer (5.2)."""
    return _each(tree, lambda i: _c(tree) and any(
        _scalar_non_pointer(tree, i, x)
        for x in _items_of(tree, i, "is_device_ptr")))


def _reduction_ident(c) -> str | None:
    from offload.engine.rules import _modifiers
    return next((_norm(m) for m in _modifiers(c)
                 if _norm(m) not in ("task", "inscan", "default")), None)


@predicate
def c_reduction_minmax_arithmetic(tree, version):
    """A max or min reduction (reduction, in_reduction, task_reduction) of
    a list item declared with a pointer, structure or union type."""
    def bad(i):
        for c in _clauses(tree, i, "reduction", "in_reduction",
                          "task_reduction"):
            if _reduction_ident(c) not in ("max", "min"):
                continue
            for x in map(_base, _items([c])):
                if _is_pointer(tree, i, x) or _class(tree, i, x) in (
                        "type", "other"):
                    return True
        return False
    return _each(tree, bad) if _c(tree) else []


def _const(tree, i, x) -> bool:
    t = _ctype(tree, i, x)
    if t is None:
        return False
    # const qualifying the object: not "const int *p" (pointer to const)
    words = t.replace("*", " * ").split()
    if "*" in words:
        return "const" in words[len(words) - words[::-1].index("*"):]
    return "const" in words


@predicate
def c_reduction_not_const(tree, version):
    """A reduction, in_reduction or task_reduction (6.0: or induction)
    list item declared const-qualified."""
    names = ("reduction", "in_reduction", "task_reduction") + (
        ("induction",) if version >= 60 else ())
    return _each(tree, lambda i: _c(tree) and any(
        _const(tree, i, x) for x in _items_of(tree, i, *names)))


@predicate
def c_privatized_not_const(tree, version):
    """A const-qualified variable in a clause that privatizes it other
    than firstprivate: private, lastprivate, linear (the reduction clauses
    have their own const rule, reduction-clause-008)."""
    return _each(tree, lambda i: _c(tree) and any(
        _const(tree, i, x) for x in _items_of(
            tree, i, "private", "lastprivate", "linear")))


def _member(tree, i, item):
    """(struct kind, member, bit-field?) of a list item s.m / p->m whose
    structure type is defined in the source, else None."""
    m = re.match(r"^([a-z_]\w*)\s*(?:\.|->)\s*([a-z_]\w*)", item)
    if not m:
        return None
    s = _decl_scope(tree, i, m.group(1))
    if s is None:
        return None
    tag = tree.vartypes.get((s, m.group(1)))
    if tag is None:
        return None
    hit = tree._find(tree.assoc[i].scope, tag, tree.types)
    info = None
    for (sid, t), v in tree.extra.get("struct_members", {}).items():
        if t == tag and (hit is None or sid == hit[0][-1]):
            info = v
    if info is None:
        return None
    return info["kind"], m.group(2), m.group(2) in info["bitfields"]


@predicate
def c_map_no_bitfield(tree, version):
    """A map list item that is a bit-field member of a structure defined
    in the source."""
    return _each(tree, lambda i: _c(tree) and any(
        (mm := _member(tree, i, x)) is not None and mm[2]
        for x in _items(_clauses(tree, i, "map"))))


@predicate
def c_map_no_union_member(tree, version):
    """A map list item that is a member of a union defined in the
    source."""
    return _each(tree, lambda i: _c(tree) and any(
        (mm := _member(tree, i, x)) is not None and mm[0] == "union"
        for x in _items(_clauses(tree, i, "map"))))


@predicate
def c_depend_no_bitfield(tree, version):
    """A depend list item that is a bit-field member of a structure
    defined in the source."""
    return _each(tree, lambda i: _c(tree) and any(
        (mm := _member(tree, i, x)) is not None and mm[2]
        for x in _items(_clauses(tree, i, "depend"))))


_C_SCALAR_TYPE = re.compile(r"^(?:const|volatile|signed|unsigned|short|long|"
                            r"int|char|float|double|_bool|bool|void|"
                            r"size_t|int\d+_t|uint\d+_t|_complex)+$")


@predicate
def c_declare_mapper_struct_or_union(tree, version):
    """A declare mapper whose type is not a struct or union type (a
    scalar type keyword, or a pointer type). A typedef name
    defined in the source is resolved (a typedef'd struct is legal: the
    confirmer's legality gate called fresh2 programs illegal for it); a
    typedef name the source does not define (a header's) is not
    flagged. An enum type (named, or through a typedef) is flagged."""
    from offload.engine.rules import _mapper_spec, _norm
    tds = {k.lower(): _norm(v) for k, v in
           tree.extra.get("typedefs", {}).items()}

    def resolve(typ: str) -> str:
        seen = set()
        while typ in tds and typ not in seen:
            seen.add(typ)
            typ = tds[typ]
        return typ

    def bad(i):
        if tree.directives[i].name != "declare mapper":
            return False
        typ = _mapper_spec(tree.directives[i])[1]
        if not typ:
            return False
        raw = tree.directives[i].args[0] if tree.directives[i].args else ""
        named = resolve(typ)
        if "*" in named:
            return True
        # an enum type is a scalar type, not a struct or union:
        # written as "enum tag", or a typedef of one (the types are
        # compared with their blanks removed)
        if re.search(r"(?:^|[:\s])enum\s", raw) or (
                named != typ and re.match(r"^(?:const|volatile)*enum",
                                          named)):
            return True
        typ = named
        if re.match(r"^(struct|union)", typ):
            return False
        return bool(_C_SCALAR_TYPE.match(typ))
    return _each(tree, bad) if _c(tree) else []


# --- array sections -------------------------------------------------------------

_SECTION_CLAUSES = set(_DSA) | {"map", "to", "from", "depend", "reduction",
                                "in_reduction", "task_reduction",
                                "use_device_addr", "has_device_addr",
                                "aligned", "nontemporal", "affinity"}


def _c_section_items(tree, i):
    for c in _clauses(tree, i):
        if c.name in _SECTION_CLAUSES:
            for x in _items([c]):
                if _c_sections(x):
                    yield x


@predicate
def c_section_base_array_or_pointer(tree, version):
    """An array section whose base is a variable declared in the source as
    a scalar that is not a pointer."""
    def bad(i):
        for x in _c_section_items(tree, i):
            base = _section_base(x)
            if base and re.fullmatch(r"[a-z_]\w*", base) and \
                    _scalar_non_pointer(tree, i, base):
                return True
        return False
    return _each(tree, bad) if _c(tree) else []


@predicate
def c_section_stride_positive(tree, version):
    """An array section with an integer literal stride less than one."""
    return _each(tree, lambda i: _c(tree) and any(
        len(t) == 3 and _int(t[2] or "1") is not None and _int(t[2]) < 1
        for x in _c_section_items(tree, i)
        for dims in _c_sections(x) for t in dims))


@predicate
def c_section_length_nonnegative(tree, version):
    """An array section with a negative integer literal length."""
    return _each(tree, lambda i: _c(tree) and any(
        len(t) >= 2 and _int(t[1] or "0") is not None and _int(t[1]) < 0
        for x in _c_section_items(tree, i)
        for dims in _c_sections(x) for t in dims))


# --- data-sharing ----------------------------------------------------------------

@predicate
def c_default_private_static_listed(tree, version):
    """default(firstprivate) or default(private) on a construct whose
    statements reference a file-scope (static storage) variable that no
    data-sharing attribute clause of the directive lists."""
    out = []
    if not _c(tree):
        return out
    for i, d in enumerate(tree.directives):
        cl = [c for c in d.clauses if c.name == "default"]
        if not any(_norm(a).split(":")[0] in ("firstprivate", "private")
                   for c in cl for a in c.args):
            continue
        listed = {_base(x) for x in _items(_clauses(tree, i,
                                                    *_EXPLICIT_DSA))}
        refs = _c_construct_refs(tree, i) - listed
        if any(_decl_scope(tree, i, x) == 0 and (0, x) in tree.saved
               for x in refs):
            out.append(i)
    return out


@predicate
def c_declare_reduction_type(tree, version):
    """A declare reduction type name that is an array, pointer-to-function
    or qualified (const, volatile, restrict) type."""
    def bad(i):
        d = tree.directives[i]
        if d.name != "declare reduction" or not d.args:
            return False
        parts = re.split(r":(?!:)", d.args[0] if len(d.args) == 1
                         else ",".join(d.args))
        if len(parts) < 3:
            return False
        types = parts[1]
        return bool(re.search(r"\b(const|volatile|restrict)\b|\[|\(",
                              types))
    return _each(tree, bad) if _c(tree) else []


__all__ = [n for n in dir() if n.startswith("c_")] + ["association"]
