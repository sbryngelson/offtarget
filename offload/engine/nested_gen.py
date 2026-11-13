"""nested-data: programs that map nested pointer-linked data structures to
the device.

A program is a shape (the structure the host builds), a kernel (what the
device does to every object reachable from the root) and a plan (the
data-mapping constructs that make the structure visible). Every legal plan
of one shape and kernel gives the same result, which `simulate` computes
in Python, so the expected output never comes from a compiler.

Cfg is one point of the axes. build_shape(cfg) builds types, objects and
links. simulate(shape) returns the expected `name= value` lines.
make_plan(shape) returns a strategy's constructs. validate(shape, plan)
replays them against the spec and reports defined, unspecified or illegal;
the last two are generated only as marked negatives or observations.
Rendering is in offload.engine.nested_emit, spec citations in nested_cites."""
from __future__ import annotations

import hashlib
import random
from collections import defaultdict
from dataclasses import dataclass, field, replace

from offload.engine import nested_cites as NC

NM = 8          # elements of every data array
NK = 2          # children of an array-like link
BIG = 10 ** 6   # reference count of a declare target variable

LINKS = {"c": ("embed", "arr", "ptr", "parr", "ptrs", "pp"),
         "f": ("embed", "arr", "ptr", "alloc", "aarr", "parr")}
DATAS = {"c": ("fixed", "ptr"), "f": ("fixed", "ptr", "alloc")}
ROLES = ("in", "inout", "out")
TOPOS = ("chain", "list", "tree", "diamond", "twin", "alias", "aliassub")
STRATEGIES = ("one", "enter", "tdata", "tdata_nested", "present", "always",
              "close", "update", "mapper", "mapper_enter", "acc_data")
SINGLE = ("embed", "ptr", "alloc")           # one child
MANY = ("arr", "parr", "ptrs", "pp", "aarr")  # NK children


@dataclass(frozen=True)
class Cfg:
    lang: str                 # "c" | "f"
    model: str                # "omp" | "acc"
    topo: str = "chain"
    depth: int = 2
    links: tuple = ()         # chain: link kind of each level but the last
    datas: tuple = ("fixed",)  # data member kind per level (cycled)
    roles: tuple = ("inout",)  # role per depth (cycled)
    null_at: int = -1         # depth whose outgoing link is NULL
    kernel: str = "serial"    # serial | par
    strategy: str = "one"
    order: str = "td"         # td | bu | shuf
    mods: str = ""            # "" | always | present | close
    root: str = "var"         # var | heap | global
    mutate: str = ""          # a negative's mutation (see MUTATIONS)

    def key(self) -> str:
        return "|".join(str(v) for v in (
            self.lang, self.model, self.topo, self.depth, self.links,
            self.datas, self.roles, self.null_at, self.kernel,
            self.strategy, self.order, self.mods, self.root, self.mutate))

    @property
    def uid(self) -> str:
        return hashlib.sha256(self.key().encode()).hexdigest()[:8]


@dataclass
class TypeDef:
    name: str
    data: str                       # fixed | ptr | alloc
    links: list = field(default_factory=list)   # (member, kind, target type)


@dataclass
class Node:
    nid: int
    type: str
    depth: int
    group: int                      # nid of the group root (container)
    role: str = "inout"
    owner: int = -1                 # node whose data array this node uses
    off: int = 0
    length: int = NM


@dataclass
class Edge:
    eid: int
    parent: int
    member: str
    kind: str
    children: tuple                  # nid or None per child


@dataclass
class Shape:
    cfg: Cfg
    types: dict
    order: list                     # type names, dependencies first
    nodes: dict
    edges: list
    root: int
    contained: frozenset

    def out_edges(self, nid):
        return [e for e in self.edges if e.parent == nid]

    def separate_data(self, n: Node) -> bool:
        k = self.types[n.type].data
        return k == "ptr" or (k == "alloc" and not (
            self.cfg.lang == "f" and self.cfg.model == "omp"))


# --- the shape --------------------------------------------------------------------------

def _contained(cfg: Cfg) -> frozenset:
    s = {"embed", "arr"}
    if cfg.lang == "f" and cfg.model == "omp":
        s |= {"alloc", "aarr"}
    return frozenset(s)


def _check_cfg(cfg: Cfg):
    if cfg.lang not in LINKS:
        raise ValueError(f"language {cfg.lang}")
    for k in cfg.links:
        if k not in LINKS[cfg.lang]:
            raise ValueError(f"link kind {k} not in {cfg.lang}")
    for k in cfg.datas:
        if k not in DATAS[cfg.lang]:
            raise ValueError(f"data kind {k} not in {cfg.lang}")
    if cfg.topo not in TOPOS:
        raise ValueError(f"topology {cfg.topo}")
    if not 1 <= cfg.depth <= 4:
        raise ValueError("depth 1..4")


def build_shape(cfg: Cfg) -> Shape:
    _check_cfg(cfg)
    contained = _contained(cfg)
    types, order = {}, []
    nodes: dict[int, Node] = {}
    edges: list[Edge] = []

    def datak(level):
        return cfg.datas[level % len(cfg.datas)]

    def addtype(t: TypeDef):
        types[t.name] = t
        order.append(t.name)

    def addnode(tname, depth, group=None) -> int:
        nid = len(nodes)
        nodes[nid] = Node(nid, tname, depth, nid if group is None else group,
                          owner=nid)
        return nid

    def addedge(parent, member, kind, children):
        e = Edge(len(edges), parent, member, kind, tuple(children))
        edges.append(e)
        return e

    def link(parent, member, kind, tname, nullable_edge):
        """A link of `parent` to new objects of type `tname`."""
        p = nodes[parent]
        n = NK if kind in MANY else 1
        null = nullable_edge
        kids = []
        group = None
        for k in range(n):
            if null and (kind in ("ptrs", "pp") and k == n - 1 or
                         kind not in ("ptrs", "pp")):
                kids.append(None)
                continue
            if kind in contained:
                g = p.group
            elif kind in ("parr", "aarr"):
                g = group            # all elements in one block
            else:
                g = None
            c = addnode(tname, p.depth + 1, g)
            if kind in ("parr", "aarr") and group is None:
                group = c
            kids.append(c)
        return addedge(parent, member, kind, kids)

    def expand(nid):
        p = nodes[nid]
        for (m, kind, tname) in types[p.type].links:
            is_null = cfg.null_at == p.depth and kind not in (
                "embed", "arr")
            e = link(nid, m, kind, tname, is_null)
            for c in e.children:
                if c is not None:
                    expand(c)

    if cfg.topo == "chain":
        for lv in range(cfg.depth - 1, -1, -1):
            t = TypeDef(f"n{lv}", datak(lv))
            if lv < cfg.depth - 1:
                t.links.append(("nx", cfg.links[lv], f"n{lv + 1}"))
            addtype(t)
        root = addnode("n0", 0)
        expand(root)
    elif cfg.topo == "list":
        addtype(TypeDef("node", datak(0), [("nx", "ptr", "node")]))
        root = addnode("node", 0)
        cur = root
        for d in range(1, cfg.depth):
            nullcut = cfg.null_at == d - 1
            if nullcut:
                addedge(cur, "nx", "ptr", [None])
                break
            c = addnode("node", d)
            addedge(cur, "nx", "ptr", [c])
            cur = c
        else:
            addedge(cur, "nx", "ptr", [None])
    elif cfg.topo == "tree":
        addtype(TypeDef("node", datak(0), [("l", "ptr", "node"),
                                           ("r", "ptr", "node")]))
        root = addnode("node", 0)

        def grow(nid, d):
            for m in ("l", "r"):
                if d + 1 < cfg.depth and not (
                        cfg.null_at == d and m == "r"):
                    c = addnode("node", d + 1)
                    addedge(nid, m, "ptr", [c])
                    grow(c, d + 1)
                else:
                    addedge(nid, m, "ptr", [None])
        grow(root, 0)
    elif cfg.topo == "diamond":
        addtype(TypeDef("n2", datak(2)))
        addtype(TypeDef("n1", datak(1), [("c", "ptr", "n2")]))
        addtype(TypeDef("n0", datak(0), [("l", "ptr", "n1"),
                                         ("r", "ptr", "n1")]))
        root = addnode("n0", 0)
        x = addnode("n1", 1)
        y = addnode("n1", 1)
        leaf = addnode("n2", 2)
        addedge(root, "l", "ptr", [x])
        addedge(root, "r", "ptr", [y])
        addedge(x, "c", "ptr", [leaf])
        addedge(y, "c", "ptr", [leaf])
    elif cfg.topo == "twin":
        addtype(TypeDef("n1", datak(1)))
        addtype(TypeDef("n0", datak(0), [("l", "ptr", "n1"),
                                         ("r", "ptr", "n1")]))
        root = addnode("n0", 0)
        m = addnode("n1", 1)
        addedge(root, "l", "ptr", [m])
        addedge(root, "r", "ptr", [m])
    else:                              # alias, aliassub
        addtype(TypeDef("n1", "ptr"))
        addtype(TypeDef("n0", "ptr", [("nx", "ptr", "n1")]))
        root = addnode("n0", 0)
        c = addnode("n1", 1)
        addedge(root, "nx", "ptr", [c])
        nodes[c].owner = root
        if cfg.topo == "aliassub":
            nodes[c].off = 2
            nodes[c].length = NM - 2
    shape = Shape(cfg, types, order, nodes, edges, root, contained)
    for n in nodes.values():            # roles by the depth of the group root
        g = nodes[n.group]
        n.role = cfg.roles[g.depth % len(cfg.roles)]
    if cfg.topo in ("alias", "aliassub"):          # one array, one role
        for n in nodes.values():
            n.role = nodes[root].role
    return shape


# --- visits and the model ---------------------------------------------------------------

@dataclass(frozen=True)
class Visit:
    nid: int
    depth: int
    path: tuple            # ((eid, k), ...)
    j: int


def visits(shape: Shape) -> list[Visit]:
    out: list[Visit] = []

    def go(nid, path):
        out.append(Visit(nid, shape.nodes[nid].depth, path, len(out)))
        for e in shape.out_edges(nid):
            for k, c in enumerate(e.children):
                if c is not None:
                    go(c, path + ((e.eid, k),))
    go(shape.root, ())
    return out


def first_path(shape: Shape) -> dict:
    fp = {}
    for v in visits(shape):
        fp.setdefault(v.nid, v.path)
    return fp


def init_values(shape: Shape):
    """(s, a): host initial scalar per node and data array per owner."""
    s, a = {}, {}
    for n in shape.nodes.values():
        out = n.role == "out"
        s[n.nid] = -1 if out else 10 * (n.depth + 1) + n.nid
        if n.owner == n.nid:
            a[n.nid] = [(-1 if out else 100 * (n.nid + 1) + i)
                        for i in range(NM)]
    return s, a


def levels(shape: Shape) -> list[int]:
    return sorted({n.depth for n in shape.nodes.values()})


def simulate(shape: Shape) -> list[tuple[str, int]]:
    """The expected output: ``tot`` (what the device computed) and, per
    depth, ``ha<L>`` (host sum of the data arrays of the objects at that
    depth, per visit) and ``hs<L>`` (host sum of their scalars). A scalar
    is not checked at a depth with an ``out`` object in a parallel kernel
    (the device never writes it, so the copy back is not defined)."""
    cfg = shape.cfg
    s, a = init_values(shape)
    vs = visits(shape)
    tot = 0

    def elem(v, i):
        n = shape.nodes[v.nid]
        return n.owner, n.off + i

    def ops(v, i):
        nonlocal tot
        n = shape.nodes[v.nid]
        L = v.depth + 1
        o, ix = elem(v, i)
        if n.role in ("in", "inout"):
            tot += L * a[o][ix]
        if n.role == "inout":
            a[o][ix] += 7 * L
        elif n.role == "out":
            a[o][ix] = 500 * L + 10 * v.j + i

    def sops(v):
        nonlocal tot
        n = shape.nodes[v.nid]
        if n.role in ("in", "inout"):
            tot += s[v.nid]
        if n.role == "inout":
            s[v.nid] += 3
        elif n.role == "out":
            s[v.nid] = 900 + v.j

    if cfg.kernel == "serial":
        for v in vs:
            for i in range(shape.nodes[v.nid].length):
                ops(v, i)
            sops(v)
    else:
        for i in range(NM):
            for v in vs:
                if i < shape.nodes[v.nid].length:
                    ops(v, i)
    out = [("tot", tot)]
    for L in levels(shape):
        at = [v for v in vs if v.depth == L]
        out.append((f"ha{L}", sum(
            sum(a[shape.nodes[v.nid].owner][shape.nodes[v.nid].off + i]
                for i in range(shape.nodes[v.nid].length)) for v in at)))
        if scalar_checked(shape, L):
            out.append((f"hs{L}", sum(s[v.nid] for v in at)))
    return out


def scalar_checked(shape: Shape, depth: int) -> bool:
    if shape.cfg.kernel == "serial":
        return True
    return all(n.role != "out" for n in shape.nodes.values()
               if n.depth == depth)


# --- blocks, references, plans ------------------------------------------------------------

# A reference names one list item of a plan:
#   ("root",)            the root structure
#   ("e", eid, k)        the objects a pointer-like link points to (k: child
#                        index; None for a whole array of objects)
#   ("pa", eid)          the array of pointers behind a pp link
#   ("d", nid)           the array a pointer/allocatable data member points to

def separate_edges(shape: Shape):
    return [e for e in shape.edges if e.kind not in shape.contained]


def group_of(shape, nid):
    return shape.nodes[nid].group


def refs_of(shape: Shape) -> dict:
    """ref -> (holder block, target block, role of the target)."""
    nodes = shape.nodes
    out = {}
    root = shape.root
    out[("root",)] = (None, ("g", nodes[root].group), nodes[root].role)
    for e in separate_edges(shape):
        hold = ("g", nodes[e.parent].group)
        if e.kind == "pp":
            out[("pa", e.eid)] = (hold, ("pa", e.eid), "in")
            hold = ("pa", e.eid)
        if e.kind in ("parr", "aarr"):
            first = next((c for c in e.children if c is not None), None)
            if first is not None:
                out[("e", e.eid, None)] = (hold, ("g", nodes[first].group),
                                           nodes[first].role)
            continue
        for k, c in enumerate(e.children):
            if c is not None:
                out[("e", e.eid, k)] = (hold, ("g", nodes[c].group),
                                        nodes[c].role)
    for n in nodes.values():
        if shape.separate_data(n):
            o = nodes[n.owner]
            out[("d", n.nid)] = (("g", n.group), ("d", n.owner), n.role)
    return out


def block_role(shape, b):
    if b[0] == "g":
        return shape.nodes[b[1]].role
    if b[0] == "d":
        return shape.nodes[b[1]].role
    return "in"


class Infeasible(Exception):
    """No sequence of map constructs attaches every pointer."""


def _blocks_and_prim(refs):
    prim, order = {}, []
    for r, (h, t, _) in refs.items():
        if t not in prim:
            prim[t] = r
            order.append(t)
    return prim, order


def _toposort(order, deps):
    """Stable topological order of blocks; deps: (a, b) means a before b."""
    level = {b: 0 for b in order}
    for _ in range(len(order) + 1):
        changed = False
        for a, b in deps:
            if level[b] < level[a] + 1:
                level[b] = level[a] + 1
                changed = True
        if not changed:
            break
    else:
        raise Infeasible("cyclic attachment order")
    return level


def td_steps(shape: Shape):
    """Top-down map constructs. Every block is created by the construct of
    its first reference; a pointer needs a construct in which its holder or
    its target is created (OpenMP 5.2 §5.8.3 p.152 l.5-8), so a block's
    other incoming references go in the construct that creates their
    holder, which therefore comes after the target's. Blocks without
    ordering constraint between them share a construct."""
    refs = refs_of(shape)
    prim, order = _blocks_and_prim(refs)
    deps = []
    for r, (h, t, _) in refs.items():
        if h is None:
            continue
        deps.append((h, t) if prim[t] == r else (t, h))
    level = _toposort(order, deps)
    by_level = defaultdict(list)
    for b in order:
        by_level[level[b]].append(b)
    steps = []
    for lv in sorted(by_level):
        items = []
        for b in by_level[lv]:
            items.append(prim[b])
            items += [r for r, (h, t, _) in refs.items()
                      if h == b and prim[t] != r]
        steps.append(items)
    return steps


def bu_steps(shape: Shape, acc: bool):
    """Bottom-up constructs: a block's construct maps it and lists every
    pointer it holds again (OpenMP: the pointer is created now, so it is
    attached; OpenACC: attach clauses). Returns (enter items, exit items)
    per construct, leaves first."""
    refs = refs_of(shape)
    prim, order = _blocks_and_prim(refs)
    deps = [(t, h) for r, (h, t, _) in refs.items() if h is not None]
    level = _toposort(order, deps)
    enter, exits = [], []
    for b in sorted(order, key=lambda b: (level[b], order.index(b))):
        out = [r for r, (h, t, _) in refs.items() if h == b]
        tg = [refs[r][1] for r in out]
        if len(tg) != len(set(tg)):
            raise Infeasible("a block holds two pointers to one block")
        e = [It(prim[b], "to" if b[0] == "pa" else mt_enter(refs[prim[b]][2]))]
        x = [It(prim[b], "release" if b[0] == "pa" else
                mt_exit(refs[prim[b]][2]))]
        for r in out:
            if acc:
                e.append(It(r, "attach"))
                x.append(It(r, "detach"))
            else:
                e.append(It(r, "to" if r[0] == "pa" else mt_enter(refs[r][2])))
                x.append(It(r, "release" if r[0] == "pa" else
                            mt_exit(refs[r][2])))
        enter.append(e)
        exits.append(x)
    return enter, exits


def mt_one(role):
    return {"in": "to", "inout": "tofrom", "out": "from"}[role]


def mt_enter(role):
    return {"in": "to", "inout": "to", "out": "alloc"}[role]


def mt_exit(role):
    return {"in": "release", "inout": "from", "out": "from"}[role]


@dataclass
class It:
    ref: tuple
    mt: str
    mods: tuple = ()


@dataclass
class Cons:
    kind: str       # enter exit tdata_open tdata_close region upd_to upd_from
    items: list = field(default_factory=list)
    mapper: str = ""    # "" | "default" | "named": the root item invokes it
    note: str = ""


@dataclass
class Plan:
    cons: list
    notes: list = field(default_factory=list)
    infeasible: str = ""


def _mt_for(shape, refs, r, fn):
    role = refs[r][2]
    if r[0] == "pa":
        return "to" if fn is mt_enter or fn is mt_one else "release"
    return fn(role)


def make_plan(shape: Shape) -> Plan:
    try:
        return _make_plan(shape)
    except Infeasible as e:
        return Plan([], infeasible=str(e))


def _make_plan(shape: Shape) -> Plan:
    cfg = shape.cfg
    refs = refs_of(shape)
    glob = cfg.root == "global"
    acc = cfg.model == "acc"
    st = cfg.strategy
    steps = td_steps(shape)
    if glob:
        steps = [[r for r in stp if r != ("root",)] for stp in steps]
        steps = [stp for stp in steps if stp]
    flat = [r for stp in steps for r in stp]

    def mt(r, fn):
        return _mt_for(shape, refs, r, fn)

    def items(rs, fn, mods=()):
        return [It(r, mt(r, fn), mods) for r in rs]

    def ordered(rs):
        if cfg.order == "bu":
            return list(reversed(rs))
        if cfg.order == "shuf":
            rr = list(rs)
            random.Random(cfg.uid).shuffle(rr)
            return rr
        return list(rs)

    cons: list[Cons] = []
    root_present = [It(("root",), "present")] if acc else []

    def region(its):
        return Cons("region", its)

    if glob:
        cons.append(Cons("upd_to", [It(("root",), "to")]))

    if st in ("one", "always", "close"):
        mods = ("always",) if st == "always" else (
            ("close",) if st == "close" else ())
        its = items(ordered(flat), mt_one, mods)
        if st == "always":                         # always is for to/from
            its = [i if i.mt in ("to", "from", "tofrom") else
                   replace(i, mods=()) for i in its]
        cons.append(region(its))
    elif st == "mapper":
        cons.append(region(items(flat, mt_one)))
        cons[-1].mapper = "default"
    elif st == "mapper_enter":
        cons.append(Cons("enter", items(flat, mt_enter), mapper="default"))
        cons.append(region([]))
        cons.append(Cons("exit", items(list(reversed(flat)), mt_exit),
                         mapper="default"))
    elif st in ("tdata", "acc_data"):
        cons.append(Cons("tdata_open", items(ordered(flat), mt_one)))
        cons.append(region(list(root_present)))
        cons.append(Cons("tdata_close", items(ordered(flat), mt_one)))
    elif st == "tdata_nested":
        for stp in steps:
            cons.append(Cons("tdata_open", items(stp, mt_one)))
        cons.append(region(list(root_present)))
        for stp in reversed(steps):
            cons.append(Cons("tdata_close", items(stp, mt_one)))
    elif st == "present":
        for stp in steps:
            cons.append(Cons("enter", items(stp, mt_enter)))
        cons.append(region(items(flat, mt_one, ("present",))))
        for stp in reversed(steps):
            cons.append(Cons("exit", items(stp, mt_exit)))
    elif st == "enter":
        if cfg.order == "bu":
            seq, exits = bu_steps(shape, acc)
            if glob:
                seq = [[i for i in e if i.ref != ("root",)] for e in seq]
                exits = [[i for i in e if i.ref != ("root",)] for e in exits]
                seq = [e for e in seq if e]
                exits = [e for e in exits if e]
            for its in seq:
                cons.append(Cons("enter", its))
            cons.append(region(list(root_present)))
            for its in reversed(exits):
                cons.append(Cons("exit", its))
        else:
            for stp in steps:
                cons.append(Cons("enter", items(stp, mt_enter)))
            cons.append(region(list(root_present)))
            for stp in reversed(steps):
                cons.append(Cons("exit", items(stp, mt_exit)))
    elif st == "update":
        for stp in steps:
            cons.append(Cons("enter", [It(r, "alloc") for r in stp]))
        rd = [r for r in flat if refs[r][2] in ("in", "inout")
              and r[0] != "pa"]
        wr = [r for r in flat if refs[r][2] in ("inout", "out")
              and r[0] != "pa"]
        cons.append(Cons("upd_to", [It(r, "to") for r in rd]))
        cons.append(region(list(root_present)))
        cons.append(Cons("upd_from", [It(r, "from") for r in wr]))
        for stp in reversed(steps):
            cons.append(Cons("exit", [It(r, "delete") for r in stp]))
    else:
        raise ValueError(f"strategy {st}")
    if glob and shape.nodes[shape.root].role != "in":
        cons.append(Cons("upd_from", [It(("root",), "from")]))
    return _mutate(shape, Plan(cons), refs)


MUTATIONS = ("drop_edge", "bu_no_relist", "dup_listed", "swap_exit",
             "in_alloc_only", "mapper_cycle")


def _mutate(shape, plan, refs):
    m = shape.cfg.mutate
    if not m:
        return plan
    cons = plan.cons
    if m == "drop_edge":                 # a pointer target no map names
        for c in cons:
            if c.kind in ("region", "enter", "tdata_open", "exit",
                          "tdata_close"):
                c.items = [i for i in c.items if i.ref[0] != "e"
                           or i.ref[1] != 0]
    elif m == "bu_no_relist":            # child-first without re-listing
        for c in cons:
            if c.kind in ("enter", "exit"):
                c.items = c.items[:1]
    elif m == "dup_listed":              # one storage block named twice
        for c in cons:
            if c.kind in ("region", "enter", "tdata_open"):
                dup = [i for i in c.items if i.ref[0] == "e"]
                if dup:
                    other = next((r for r, (h, t, _) in refs.items()
                                  if r[0] == "e" and t == refs[dup[0].ref][1]
                                  and r != dup[0].ref), None)
                    if other is not None:
                        c.items.append(It(other, dup[0].mt))
                break
    elif m == "swap_exit":               # parent leaves before its children
        ex = [c for c in cons if c.kind == "exit"]
        if len(ex) > 1:
            idx = [cons.index(c) for c in ex]
            cons[idx[0]], cons[idx[-1]] = cons[idx[-1]], cons[idx[0]]
    elif m == "in_alloc_only":           # read-roles mapped alloc, no update
        for c in cons:
            for i in c.items:
                if i.mt == "to":
                    i.mt = "alloc"
    plan.cons = [c for c in cons if c.items or c.kind == "region"]
    return plan


# --- the legality model -----------------------------------------------------------------

@dataclass
class Verdict:
    status: str = "defined"             # defined | unspecified | illegal
    reasons: list = field(default_factory=list)   # (tag, message)

    def flag(self, status, tag, msg):
        order = {"defined": 0, "unspecified": 1, "illegal": 2}
        if order[status] > order[self.status]:
            self.status = status
        self.reasons.append((tag, msg))

    @property
    def ok(self):
        return self.status == "defined"


def validate(shape: Shape, plan: Plan, legacy: bool = False) -> Verdict:
    cfg = shape.cfg
    omp = cfg.model == "omp"
    fort_omp = cfg.lang == "f" and omp
    refs = refs_of(shape)
    v = Verdict()
    if plan.infeasible:
        v.flag("illegal", "omp.map.same-storage" if omp else
               "acc.attach.action", plan.infeasible)
        return v
    cnt: dict = defaultdict(int)
    att: dict = defaultdict(int)
    inited: set = set()
    dirty: set = set()
    partial: set = set()
    glob = cfg.root == "global"
    rootb = ("g", shape.nodes[shape.root].group)
    if glob:
        cnt[rootb] = BIG

    def info(ref):
        return refs[ref]

    def do_enter(items, where):
        mapped = []
        for it in items:
            h, t, role = info(it.ref)
            if it.mt != "attach":            # an attach clause counts no block
                mapped.append(t)
        uniq = sorted(set(mapped), key=str)
        # one storage block named by two different list items
        if omp:
            by = defaultdict(set)
            for it in items:
                if it.mt != "attach":
                    by[info(it.ref)[1]].add(it.ref)
            for b, rs in by.items():
                if len(rs) > 1:
                    v.flag("illegal", "omp.map.same-storage",
                           f"{where}: two list items name one storage "
                           f"block {b}")
        new = {b for b in uniq if cnt[b] == 0}
        # Fortran: listing a pointer and a member of its target together
        if fort_omp:
            tgt = {info(i.ref)[1] for i in items
                   if i.ref[0] in ("e", "d") and i.ref != ("root",)}
            for it in items:
                h, t, _ = info(it.ref)
                if h is not None and h in tgt and h[0] == "g":
                    v.flag("unspecified", "omp.map.fortran-pointer-target",
                           f"{where}: {it.ref} is a member of the target "
                           f"of a pointer listed on the same construct")
                    break
        for it in items:
            h, t, _ = info(it.ref)
            if "present" in it.mods and cnt[t] == 0:
                v.flag("illegal", "omp.map.present",
                       f"{where}: present list item {it.ref} is not "
                       f"present")
            if fort_omp and h is not None and cnt[h] == 0 \
                    and h not in new and h[0] == "g":
                partial.add(h)
        for b in new:
            if b in partial:
                # 5.2 §5.8.3 p.156 l.19-22 says "must": a restriction
                # (the first labels, kept for the draw, said unspecified)
                v.flag("unspecified" if legacy else "illegal",
                       "omp.map.partly-present",
                       f"{where}: block {b} is mapped whole after a part "
                       f"of it was mapped alone")
        for b in uniq:
            cnt[b] += 1
        for it in items:
            h, t, role = info(it.ref)
            if it.mt in ("to", "tofrom") and (t in new or (
                    "always" in it.mods)):
                inited.add(t)
            if it.mt in ("attach", "detach"):
                pass
            if h is None or it.mt == "present" and it.ref == ("root",):
                continue
            if cnt[h] > 0 and cnt[t] > 0:
                if omp:
                    if t in new or h in new:
                        att[it.ref] += 1
                else:
                    att[it.ref] += 1
        return new

    def do_exit(items, where):
        for it in items:
            if not omp and it.ref in att and att[it.ref] > 0 \
                    and it.ref != ("root",):
                att[it.ref] -= 1 if it.mt != "delete" else att[it.ref]
        done = set()
        for it in items:
            h, t, role = info(it.ref)
            if it.mt in ("detach", "attach"):
                continue
            if t in done:
                continue
            done.add(t)
            if cnt[t] <= 0 or (t == rootb and glob):
                continue
            cnt[t] -= 1
            if cnt[t] == 0:
                if not omp:
                    for r2, (h2, t2, _) in refs.items():
                        if h2 == t and att[r2] > 0:
                            v.flag("unspecified",
                                   "acc.composite-update-attached",
                                   f"{where}: {t} leaves the device while "
                                   f"its pointer {r2} is still attached")
                for r2, (h2, t2, _) in refs.items():
                    if h2 == t or t2 == t:
                        att[r2] = 0
                if it.mt in ("from", "tofrom"):
                    dirty.discard(t)
            elif "always" in it.mods and it.mt in ("from", "tofrom"):
                dirty.discard(t)
        inited.difference_update({b for b in list(inited) if cnt[b] == 0
                                  and not (glob and b == rootb)})

    if not legacy and any(c.mapper for c in plan.cons) and any(
            tt == tn for tn, t in shape.types.items()
            for (_m, _k, tt) in t.links):
        v.flag("unspecified", "omp.mapper.cycle",
               "the mapper of a self-referential type maps its own type: a "
               "cyclic definition (5.2 §5.8.8 p.164 l.9-10)")
    vs = visits(shape)

    def check_region(where):
        for vi in vs:
            n = shape.nodes[vi.nid]
            blocks = []
            for (eid, k) in vi.path:
                e = shape.edges[eid]
                if e.kind in shape.contained:
                    continue
                ref = ("e", eid, None if e.kind in ("parr", "aarr") else k)
                if e.kind == "pp":
                    if att[("pa", eid)] <= 0:
                        v.flag("illegal", "omp.map.attach" if omp else
                               "acc.attach.action",
                               f"{where}: pointer array of edge {eid} is "
                               f"not attached")
                        return
                if att[ref] <= 0:
                    v.flag("illegal", "omp.map.attach" if omp else
                           "acc.attach.action",
                           f"{where}: pointer {ref} has no attachment: the "
                           f"device would read a host address")
                    return
            for nid in {vi.nid} | {nn for nn in [vi.nid]}:
                pass
            b = ("g", n.group)
            if cnt[b] <= 0:
                v.flag("illegal", "omp.map.attach",
                       f"{where}: block {b} not present")
                return
            if shape.separate_data(n):
                if att[("d", n.nid)] <= 0 or cnt[("d", n.owner)] <= 0:
                    v.flag("illegal", "omp.map.attach" if omp else
                           "acc.attach.action",
                           f"{where}: data pointer of node {n.nid} is not "
                           f"attached")
                    return
                db = ("d", n.owner)
            else:
                db = b
            if n.role in ("in", "inout") and (b not in inited or
                                              db not in inited):
                # indeterminate values, not a restriction violated (the first
                # labels, kept for the draw, said illegal)
                v.flag("illegal" if legacy else "unspecified",
                       "omp.map.refcount",
                       f"{where}: node {n.nid} is read before any map "
                       f"copied the host value")
                return
            if fort_omp and not legacy and any(
                    shape.edges[eid].kind in ("alloc", "aarr") and
                    shape.nodes[shape.edges[eid].parent].role == "out"
                    for (eid, _k) in vi.path):
                v.flag("unspecified", "omp.map.fortran-components",
                       f"{where}: the program tests the allocation status "
                       f"of a component of an object mapped only from; no "
                       f"rule gives the status of a device copy made "
                       f"without a transfer (5.2 §5.8.3 p.151 l.34-37 lets "
                       f"the map treat it as unallocated)")
            if n.role in ("inout", "out"):
                dirty.add(b)
                dirty.add(db)

    for ci, c in enumerate(plan.cons):
        where = f"{c.kind}#{ci}"
        if c.kind in ("enter", "tdata_open"):
            do_enter(c.items, where)
        elif c.kind == "region":
            do_enter(c.items, where)
            check_region(where)
            do_exit(c.items, where)
        elif c.kind in ("exit", "tdata_close"):
            do_exit(c.items, where)
        elif c.kind == "upd_to":
            for it in c.items:
                h, t, _ = info(it.ref)
                if cnt[t] <= 0:
                    v.flag("illegal", "omp.update.attached",
                           f"{where}: update of {it.ref}: not present")
                else:
                    inited.add(t)
        elif c.kind == "upd_from":
            for it in c.items:
                h, t, _ = info(it.ref)
                if cnt[t] <= 0:
                    v.flag("illegal", "omp.update.attached",
                           f"{where}: update of {it.ref}: not present")
                else:
                    dirty.discard(t)
                    if not omp and any(att[r2] > 0 for r2, (h2, _, _)
                                       in refs.items() if h2 == t):
                        v.flag("unspecified",
                               "acc.composite-update-attached",
                               f"{where}: update self of {t} with attached "
                               f"pointers")
        if v.status == "illegal":
            return v
    left = [b for b, n in cnt.items() if n > 0 and not (glob and b == rootb)]
    if left:
        v.flag("illegal", "omp.map.refcount",
               f"blocks still mapped at the end: {left}")
    if dirty - ({rootb} if glob and not any(
            c.kind == "upd_from" for c in plan.cons) else set()):
        v.flag("illegal", "omp.map.refcount",
               "the device wrote blocks the host never got back: "
               f"{sorted(dirty, key=str)}")
    return v


# --- the spec rows of a program ------------------------------------------------------------

def rules_of(shape: Shape, plan: Plan, verdict: Verdict) -> tuple:
    """The tags (offload.engine.nested_cites) of the rules the program stresses."""
    cfg = shape.cfg
    omp = cfg.model == "omp"
    refs = refs_of(shape)
    tags: list[str] = []
    attach = [r for r, (h, t, _) in refs.items() if h is not None]
    kinds = {e.kind for e in shape.edges}
    datas = {t.data for t in shape.types.values()}
    st = cfg.strategy
    implicit_region = any(c.kind == "region" and not [
        i for i in c.items if i.ref != ("root",) or i.mt != "present"]
        for c in plan.cons)
    if omp:
        if attach:
            tags += ["omp.map.attach", "omp.map.attached-unmodified"]
        tags.append("omp.map.struct-elements")
        if len(refs) > 1 and cfg.lang == "c":
            tags.append("omp.map.struct-element-others")
        if any(c.kind in ("enter", "exit", "tdata_open", "tdata_close")
               for c in plan.cons):
            tags.append("omp.map.refcount")
        if implicit_region:
            tags += ["omp.implicit.pointer", "omp.implicit.lookup"]
            if cfg.root == "var":
                tags.append("omp.implicit.nonscalar")
        if cfg.lang == "f":
            tags.append("omp.map.default-mapper")
            if kinds & {"alloc", "aarr"} or "alloc" in datas:
                tags += ["omp.map.fortran-components", "omp.map.alloc-status"]
            if kinds & {"ptr", "parr"} or "ptr" in datas:
                tags += ["omp.map.fortran-pointer-target",
                         "omp.map.pointer-association"]
        if cfg.topo in ("diamond", "twin", "alias", "aliassub"):
            tags += ["omp.map.same-storage", "omp.map.storage-block"]
        if cfg.topo == "aliassub":
            tags.append("omp.map.partly-present")
        if st == "always":
            tags.append("omp.map.always")
        if st == "present":
            tags.append("omp.map.present")
        if st == "close":
            tags.append("omp.map.close")
        if any(c.kind in ("upd_to", "upd_from") for c in plan.cons):
            tags.append("omp.update.attached")
            if cfg.lang == "f":
                tags += ["omp.update.pointer", "omp.update.allocatable"]
        if st in ("mapper", "mapper_enter"):
            tags += ["omp.mapper.decay", "omp.mapper.nested",
                     "omp.map.default-mapper"]
            if kinds & {"parr", "ptrs", "pp"}:
                tags.append("omp.mapper.array")
            if cfg.topo in ("list", "tree"):
                tags.append("omp.mapper.cycle")
    else:
        tags.append("acc.composite.c" if cfg.lang == "c"
                    else "acc.composite.fortran")
        if attach:
            tags += ["acc.host-pointer-copied", "acc.attach.action",
                     "acc.copyin.attach"]
        if cfg.strategy == "enter" and cfg.order == "bu":
            tags += ["acc.attach.clause", "acc.detach"]
        elif attach:
            tags.append("acc.restore-host-pointer")
        if cfg.null_at >= 0 or cfg.topo in ("list", "tree"):
            tags.append("acc.attach.null")
        if kinds & {"ptrs", "pp"}:
            tags.append("acc.pointer-array")
        if cfg.lang == "f" and kinds & {"parr"}:
            tags.append("acc.fortran-array-pointer")
    for t, _ in verdict.reasons:
        if t not in tags:
            tags.append(t)
    seen, out = set(), []
    for t in tags:
        if t in NC.CITES and t not in seen:
            seen.add(t)
            out.append(t)
    return tuple(out)


# --- programs --------------------------------------------------------------------------------

@dataclass(frozen=True)
class Program:
    id: str
    family: str
    title: str
    lang: str                  # "c" | "f90"
    model: str                 # "omp" | "acc"
    version: int               # 52 | 34
    source: str
    expected: dict
    legality: str              # defined | unspecified | illegal
    why: str
    rules: tuple               # tags
    cites: tuple               # rows: dicts as nested_cites
    axes: dict
    cfg: Cfg = None
    modes: tuple = ("copy", "unified")

    @property
    def text(self) -> str:      # offload.engine.prerun reads .text or .source
        return self.source

    def harness(self):
        from offload.engine.gen import Program as HP
        return HP(id=self.id, lang=self.lang, source=self.source,
                  atoms=frozenset({f"nested.{self.family}"}),
                  primary_atom=f"nested.{self.family}",
                  legal=self.legality == "defined", violates=None,
                  observable=True, model=self.model)


def axes_of(shape: Shape, plan: Plan) -> dict:
    cfg = shape.cfg
    kinds = sorted({e.kind for e in shape.edges})
    datas = sorted({t.data for t in shape.types.values()})
    roles = sorted({n.role for n in shape.nodes.values()})
    return {"lang": cfg.lang, "model": cfg.model, "topo": cfg.topo,
            "depth": max(n.depth for n in shape.nodes.values()) + 1,
            "links": kinds, "datas": datas, "roles": roles,
            "null": any(None in e.children for e in shape.edges),
            "kernel": cfg.kernel, "strategy": cfg.strategy,
            "order": cfg.order if cfg.strategy in (
                "one", "enter", "tdata") else "-",
            "root": cfg.root, "constructs": len(plan.cons),
            "objects": len(shape.nodes)}


def _title(shape, plan):
    cfg = shape.cfg
    ax = axes_of(shape, plan)
    lang = {"c": "C", "f": "Fortran"}[cfg.lang]
    model = {"omp": "OpenMP", "acc": "OpenACC"}[cfg.model]
    what = {"chain": "chain", "list": "linked list", "tree": "binary tree",
            "diamond": "shared child (diamond)",
            "twin": "two pointers to one object",
            "alias": "aliasing arrays",
            "aliassub": "array aliasing a part of another"}[cfg.topo]
    order = f" {cfg.order}" if cfg.strategy in (
        "one", "enter", "tdata") and cfg.order != "td" else ""
    return (f"{lang} {model}: {ax['depth']}-level {what} (links "
            f"{', '.join(ax['links']) or 'none'}; data "
            f"{', '.join(ax['datas'])}; roles {', '.join(ax['roles'])}; "
            f"{cfg.kernel} kernel), strategy {cfg.strategy}{order}, "
            f"root {cfg.root}")


# Fortran OpenACC programs that gfortran and ftn both refuse (a derived-type
# variable and its components in one data directive over a tree or an
# aliasing section) and for which the cached OpenACC 3.4 text has no rule
# that makes them defined: neither a defect nor a negative
PENDING = {"a8bf33a0", "4276fdd8", "5eb3a148", "c0f2037d"}
PENDING_WHY = ("pending: gfortran and ftn both refuse it and the cached "
               "OpenACC 3.4 text has no rule that makes it defined")


# OpenACC programs whose overlapping subarrays (an array and a section of it that another level
# points to) sit in one clause set: the cached OpenACC 3.4 text has no rule for a var that overlaps
# another var of the same directive. The draw is made before this label.
ACC_OVERLAP_PENDING = True
OVERLAP_WHY = ("pending: the cached OpenACC 3.4 text has no rule for a var that overlaps another var "
               "of the same directive (an array and the section another level points to)")


def program(cfg: Cfg, legacy: bool = False, review: bool = True) -> Program:
    from offload.engine import nested_emit as E
    shape = build_shape(cfg)
    plan = make_plan(shape)
    verdict = validate(shape, plan, legacy=legacy)
    if not legacy and cfg.uid in PENDING and verdict.status == "defined":
        verdict.status = "pending"
        verdict.reasons.append(("acc.composite.fortran", PENDING_WHY))
    if (review and not legacy and ACC_OVERLAP_PENDING and verdict.status == "defined"
            and cfg.model == "acc" and cfg.topo == "aliassub" and cfg.strategy in ("one", "tdata")):
        verdict.status = "pending"
        verdict.reasons.append(("acc.overlap", OVERLAP_WHY))
    expected = simulate(shape)
    tags = rules_of(shape, plan, verdict)
    rows = NC.rows_for(tags)
    depth = max(n.depth for n in shape.nodes.values()) + 1
    pid = f"nd-{cfg.lang}-{cfg.model}-{cfg.strategy}-{cfg.topo}-d{depth}-" \
          f"{cfg.uid}"
    title = _title(shape, plan)
    acc = cfg.model == "acc"
    mark = "//" if cfg.lang == "c" else "!"
    why = "; ".join(m for _, m in verdict.reasons)
    head = [f"{mark} nested-data {pid} "
            f"({'OpenACC 3.4' if acc else 'OpenMP 5.2'}, "
            f"{'C11' if cfg.lang == 'c' else 'free-form Fortran'}):"]
    head += E.wrap_comment(mark, "", title)
    head += E.wrap_comment(mark, "spec: ", "; ".join(
        NC.cite_text(r) for r in rows))
    head += E.wrap_comment(mark, "rules: ", ", ".join(tags))
    head += E.wrap_comment(mark, "legality: ", verdict.status + (
        f": {why}" if why else ""))
    head += E.wrap_comment(mark, "expected (computed by "
                           "compliance/nested_gen.py): ",
                           ", ".join(f"{k}= {v}" for k, v in expected))
    em = (E.EmitC if cfg.lang == "c" else E.EmitF)(shape, plan, verdict,
                                                   expected, head)
    src = em.emit()
    long = [ln for ln in src.split("\n") if len(ln) > 132]
    if long:
        raise ValueError(f"{pid}: line over 132 characters: {long[0][:60]}")
    return Program(
        id=pid, family=f"{cfg.lang}-{cfg.model}-{cfg.strategy}", title=title,
        lang="c" if cfg.lang == "c" else "f90", model=cfg.model,
        version=34 if acc else 52, source=src, expected=dict(expected),
        legality=verdict.status, why=why, rules=tags,
        cites=tuple(tuple(sorted(r.items())) for r in rows),
        axes=axes_of(shape, plan), cfg=cfg)


def parse_observed(stdout: str) -> dict:
    import re
    return {m.group(1): int(m.group(2)) for m in
            re.finditer(r"^(\w+)= (-?\d+)\s*$", stdout or "", re.M)}


# --- the sample ------------------------------------------------------------------------------

STRATS = {("c", "omp"): {"one": 5, "enter": 5, "tdata": 3, "tdata_nested": 3,
                         "present": 2, "always": 2, "close": 1, "update": 3,
                         "mapper": 3, "mapper_enter": 1},
          ("f", "omp"): {"one": 4, "enter": 6, "tdata": 3, "tdata_nested": 4,
                         "present": 2, "always": 2, "close": 1, "update": 3,
                         "mapper": 2, "mapper_enter": 1},
          ("c", "acc"): {"one": 3, "enter": 7, "tdata": 4},
          ("f", "acc"): {"one": 3, "enter": 7, "tdata": 4}}
TOPO_W = {"chain": 62, "list": 8, "tree": 7, "diamond": 7, "alias": 5,
          "aliassub": 4, "twin": 2}
DEPTHS = {"chain": ((1, 2, 3, 4), (10, 35, 35, 20)),
          "list": ((2, 3, 4), (3, 4, 3)), "tree": ((2, 3), (1, 1)),
          "diamond": ((3,), (1,)), "twin": ((2,), (1,)),
          "alias": ((2,), (1,)), "aliassub": ((2,), (1,))}


def _wchoice(rng, d):
    keys = list(d)
    return rng.choices(keys, [d[k] for k in keys])[0]


def normalize(cfg: Cfg) -> Cfg:
    """Make the combination one the strategy can express."""
    st = cfg.strategy
    kw = {}
    if cfg.topo in ("alias", "aliassub"):
        kw["kernel"] = "serial"
        kw["datas"] = ("ptr",)
        kw["roles"] = (cfg.roles[0],)
    if cfg.topo != "chain":
        kw["links"] = ()
    if st in ("mapper", "mapper_enter"):
        kw["roles"] = (cfg.roles[0],) if st == "mapper" else ("inout",)
        kw["null_at"] = -1
        if cfg.topo == "chain":
            ok = ("ptr", "parr", "ptrs", "pp") if cfg.lang == "c" else (
                "ptr", "parr")
            kw["links"] = tuple(k if k in ok else "ptr" for k in cfg.links)
        kw["root"] = "var" if cfg.root == "global" else cfg.root
    if st in ("always", "present", "close", "update", "mapper",
              "mapper_enter", "tdata_nested") and cfg.model == "acc":
        kw["strategy"] = "enter"
    if st in ("always", "close", "present"):
        kw["order"] = "td"
    if cfg.model == "acc" and cfg.root == "global":
        kw["root"] = "heap"
    if cfg.root == "global" and st not in ("enter", "update"):
        kw["root"] = "var"
    if st == "enter" and cfg.order == "shuf":
        kw["order"] = "td"
    if st in ("tdata_nested", "update", "mapper", "mapper_enter"):
        kw["order"] = "td"
    return replace(cfg, **kw) if kw else cfg


def random_cfg(rng: random.Random, lang: str, model: str, **fixed) -> Cfg:
    topo = fixed.get("topo") or _wchoice(rng, TOPO_W)
    ds, dw = DEPTHS[topo]
    depth = fixed.get("depth") or rng.choices(ds, dw)[0]
    nlev = 3 if topo in ("diamond",) else depth
    kinds = LINKS[lang]
    wk = {k: (4 if k == "ptr" else 1) for k in kinds}
    links = tuple(_wchoice(rng, wk) for _ in range(max(depth - 1, 0)))
    if fixed.get("link") and depth >= 2:
        links = (fixed["link"],) + links[1:]
    datas = tuple(rng.choice(DATAS[lang]) for _ in range(max(nlev, 1)))
    if fixed.get("data"):
        datas = (fixed["data"],) + datas[1:]
    roles = tuple(rng.choice(ROLES) for _ in range(max(nlev, 1)))
    if fixed.get("role"):
        roles = (fixed["role"],) + roles[1:]
    nullable = [i for i, k in enumerate(links) if k not in ("embed", "arr")]
    null_at = -1
    want_null = fixed.get("null")
    if topo == "chain" and nullable and (want_null or (
            want_null is None and rng.random() < 0.15)):
        null_at = rng.choice(nullable)
    elif topo in ("list", "tree") and depth >= 2 and (want_null or (
            want_null is None and rng.random() < 0.15)):
        null_at = rng.randrange(0, depth - 1)
    strat = fixed.get("strategy") or _wchoice(rng, STRATS[(lang, model)])
    order = fixed.get("order") or rng.choices(
        ("td", "bu", "shuf"), (6, 3, 1))[0]
    kernel = fixed.get("kernel") or ("par" if rng.random() < 0.4
                                     else "serial")
    root = fixed.get("root") or ("global" if model == "omp" and
                                 rng.random() < 0.1 else
                                 rng.choice(("var", "heap")))
    return normalize(Cfg(lang, model, topo, depth, links, datas, roles,
                         null_at, kernel, strat, order, "", root))


MIN_COVER = 4


def cov_keys(p: Program) -> list:
    ax = p.axes
    lm = f"{ax['lang']}-{ax['model']}"
    ks = [(lm, "topo", ax["topo"]), (lm, "depth", ax["depth"]),
          (lm, "kernel", ax["kernel"]), (lm, "strategy", ax["strategy"]),
          (lm, "root", ax["root"])]
    if ax["order"] != "-":
        ks.append((lm, "order", ax["order"]))
    ks += [(lm, "link", k) for k in ax["links"]]
    ks += [(lm, "data", k) for k in ax["datas"]]
    ks += [(lm, "role", k) for k in ax["roles"]]
    if ax["null"]:
        ks.append((lm, "null", True))
    return ks


def _force_for(key):
    axis, val = key[1], key[2]
    return {"topo": {"topo": val}, "depth": {"depth": val},
            "kernel": {"kernel": val}, "strategy": {"strategy": val},
            "root": {"root": val}, "order": {"order": val},
            "link": {"link": val}, "data": {"data": val},
            "role": {"role": val}, "null": {"null": True}}[axis]


def pilot(n: int = 400, seed: int = 1, neg_frac: float = 0.12,
          min_cover: int = MIN_COVER, legacy: bool = True,
          max_tries: int = 80) -> list[Program]:
    """About `n` programs sampled over the axes: legal ones (defined), the
    unspecified ones the draw produced (observations) and marked illegal
    negatives (mutations of legal plans, and the shapes with no legal plan).
    Every (language/model, axis, value) the axes can express is covered
    at least `min_cover` times, or the shortfall is reported by
    ``coverage``."""
    rng = random.Random(seed)
    quota = {("c", "omp"): 0.42, ("f", "omp"): 0.30, ("c", "acc"): 0.14,
             ("f", "acc"): 0.14}
    seen: set = set()
    keep: list[Program] = []
    legacy_defined: set = set()
    count: dict = defaultdict(int)

    def add(cfg, allow=("defined",)) -> Program | None:
        if cfg.uid in seen:
            return None
        try:
            lp = program(cfg, legacy=legacy, review=False)   # the draw keeps the labels it was made under
            p = program(cfg)
        except (ValueError, KeyError, IndexError):
            return None
        if lp.legality not in allow:
            return None
        seen.add(cfg.uid)
        keep.append(p)
        if lp.legality == "defined":
            legacy_defined.add(p.id)
            for k in cov_keys(lp):
                count[k] += 1
        return lp

    n_neg = int(n * neg_frac)
    n_unspec = n_neg // 2
    n_def = n - n_neg
    for (lang, model), q in quota.items():
        want = round(n_def * q)
        got = tries = 0
        while got < want and tries < want * 40:
            tries += 1
            if add(random_cfg(rng, lang, model)) is not None:
                got += 1
    # top up the axis values the draw missed (legal programs only)
    for lang, model in quota:
        for key in _feasible_keys(lang, model):
            tries = 0
            while count[key] < min_cover and tries < max_tries:
                tries += 1
                add(random_cfg(rng, lang, model, **_force_for(key)))
    # observations: what the spec leaves open (a Fortran pointer chain
    # listed whole, a parent leaving first in OpenACC, a cyclic mapper)
    got = tries = 0
    while got < n_unspec and tries < n * 200:
        tries += 1
        lang, model = rng.choice(list(quota))
        if add(random_cfg(rng, lang, model), ("unspecified",)) is not None:
            got += 1
    # negatives: mutations of legal programs
    base = [p for p in keep if p.id in legacy_defined]
    rng.shuffle(base)
    mutants = 0
    for p in base:
        if mutants >= n_neg - n_unspec:
            break
        c = p.cfg
        opts = []
        if c.strategy in ("one", "tdata", "enter", "present", "tdata_nested"):
            opts += ["drop_edge", "in_alloc_only"]
        if c.strategy == "enter" and c.order == "bu":
            opts.append("bu_no_relist")
        if c.strategy == "enter" and c.order == "td" and c.model == "acc":
            opts.append("swap_exit")
        if c.strategy == "one":
            opts.append("dup_listed")
        if not opts:
            continue
        q = add(replace(c, mutate=rng.choice(opts)),
                ("illegal", "unspecified"))
        if q is not None:
            mutants += 1
    keep += fnres_programs()
    return sorted(keep, key=lambda p: p.id)


def _feasible_keys(lang, model):
    keys = []
    lm = f"{lang}-{model}"
    keys += [(lm, "topo", t) for t in TOPOS if t != "twin" and not (
        lm == "f-omp" and t in ("diamond", "alias", "aliassub"))]
    keys += [(lm, "depth", d) for d in (1, 2, 3, 4)]
    keys += [(lm, "kernel", k) for k in ("serial", "par")]
    keys += [(lm, "strategy", s) for s in STRATS[(lang, model)]]
    keys += [(lm, "root", r) for r in (("var", "heap", "global")
                                       if model == "omp" else
                                       ("var", "heap"))]
    keys += [(lm, "order", o) for o in ("td", "bu")]
    keys += [(lm, "link", k) for k in LINKS[lang]]
    keys += [(lm, "data", k) for k in DATAS[lang]]
    keys += [(lm, "role", r) for r in ROLES]
    keys += [(lm, "null", True)]
    return keys


def coverage(programs, min_cover: int = MIN_COVER) -> dict:
    """(language-model, axis, value) -> number of legal programs, for every
    key the axes can express."""
    cnt: dict = defaultdict(int)
    for p in programs:
        if p.legality == "defined":
            for k in cov_keys(p):
                cnt[k] += 1
    out = {}
    for lang, model in STRATS:
        for k in _feasible_keys(lang, model):
            out[k] = cnt.get(k, 0)
    return out


# --- derived-type and struct function results -------------------------------------------------

def _fn_header(mark, pid, lang_note, title, tags, expected):
    from offload.engine import nested_emit as E
    rows = NC.rows_for(tags)
    h = [f"{mark} nested-data {pid} (OpenMP 5.2, {lang_note}):"]
    h += E.wrap_comment(mark, "", title)
    h += E.wrap_comment(mark, "spec: ", "; ".join(NC.cite_text(r)
                                                  for r in rows))
    h += E.wrap_comment(mark, "rules: ", ", ".join(tags))
    h += E.wrap_comment(mark, "legality: ", "defined")
    h += E.wrap_comment(mark, "expected (computed by "
                        "compliance/nested_gen.py): ",
                        ", ".join(f"{k}= {v}" for k, v in expected))
    return h, rows


def _fn_program(variant, lang, title, body, expected):
    tags = ("omp.map.attach", "omp.map.struct-elements",
            "omp.implicit.pointer", "omp.declare-target.procs")
    mark = "//" if lang == "c" else "!"
    pid = f"nd-fnres-{lang}-{variant}"
    head, rows = _fn_header(mark, pid, "C11" if lang == "c" else
                            "free-form Fortran", title, tags, expected)
    checks = list(expected)
    if lang == "c":
        tail = [f"  ok = ok && ({k} == {v});" for k, v in checks]
        tail += [f"  printf(\"{k}= %d\\n\", {k});" for k, _ in checks]
        tail += ["  printf(\"RESULT ran_on_host=%d check=%s\\n\", host_flag, "
                 "ok ? \"pass\" : \"fail\");", "  return 0;", "}", ""]
    else:
        tail = [f"  ok = ok .and. ({k} == {v})" for k, v in checks]
        tail += [f"  print '(a,i0)', '{k}= ', {k}" for k, _ in checks]
        tail += ["  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, "
                 "' check=', merge('pass', 'fail', ok)", "end program nd", ""]
    src = "\n".join(head) + "\n" + body.rstrip("\n") + "\n" + "\n".join(tail)
    long = [ln for ln in src.split("\n") if len(ln) > 132]
    if long:
        raise ValueError(f"{pid}: line over 132 characters")
    return Program(
        id=pid, family=f"{lang}-omp-fnres", title=title,
        lang="c" if lang == "c" else "f90", model="omp", version=52,
        source=src, expected=dict(expected), legality="defined", why="",
        rules=tags, cites=tuple(tuple(sorted(r.items())) for r in rows),
        axes={"lang": lang, "model": "omp", "topo": "fnres", "depth": 2,
              "links": ["ptr"], "datas": ["ptr"], "roles": ["inout"],
              "null": False, "kernel": "serial", "strategy": "fnres",
              "order": "-", "root": "heap", "constructs": 2, "objects": 2})


_C_HEAD = """#include <stdio.h>
#include <stdlib.h>
#include <omp.h>
enum { NM = 8 };
struct node { int s; int *a; struct node *nx; };
struct view { int *p; int n; };
struct stat3 { int sum; int mx; int arr[4]; };
#pragma omp declare target
static struct view mkview(int *p, int n) { struct view v; v.p = p; v.n = n; return v; }
static int vsum(struct view v) { int t = 0; for (int i = 0; i < v.n; i++) t += v.p[i]; return t; }
static struct node *child(struct node *r) { return r->nx; }
static struct stat3 summarize(const int *p, int n)
{
  struct stat3 s;
  s.sum = 0; s.mx = p[0];
  for (int i = 0; i < 4; i++) s.arr[i] = 0;
  for (int i = 0; i < n; i++) { s.sum += p[i]; if (p[i] > s.mx) s.mx = p[i]; s.arr[i % 4] += p[i]; }
  return s;
}
#pragma omp end declare target
int main(void)
{
  int host_flag = 1, ok = 1, i;
  int tot = 0, ha1 = 0, out = 0;
  struct node *r = calloc(1, sizeof *r);
  #pragma omp target map(from: host_flag)
  host_flag = omp_is_initial_device() ? 1 : 0;
  r->nx = calloc(1, sizeof *r->nx);
  r->a = malloc(NM * sizeof(int));
  r->nx->a = malloc(NM * sizeof(int));
  for (i = 0; i < NM; i++) { r->a[i] = 100 + i; r->nx->a[i] = 200 + i; }
"""
_C_MAPS = """      map(to: r[0:1]) map(to: r->a[0:NM]) \\
      map(to: r->nx[0:1]) map(to: r->nx->a[0:NM])"""

_F_HEAD = """module nd_m
  implicit none
  integer, parameter :: nm = 8
  type :: node
    integer :: s = 0
    integer, pointer :: a(:) => null()
    type(node), pointer :: nx => null()
  end type node
  type :: view
    integer, pointer :: p(:) => null()
    integer :: n = 0
  end type view
  type :: stat3
    integer :: sum = 0, mx = 0
    integer :: arr(4) = 0
  end type stat3
contains
  function mkview(p) result(v)
    !$omp declare target
    integer, pointer, intent(in) :: p(:)
    type(view) :: v
    v%p => p
    v%n = size(p)
  end function mkview
  integer function vsum(v)
    !$omp declare target
    type(view), intent(in) :: v
    integer :: k
    vsum = 0
    do k = 1, v%n
      vsum = vsum + v%p(k)
    end do
  end function vsum
  function child(r) result(c)
    !$omp declare target
    type(node), pointer, intent(in) :: r
    type(node), pointer :: c
    c => r%nx
  end function child
  function summarize(p, n) result(s)
    !$omp declare target
    integer, intent(in) :: p(:), n
    type(stat3) :: s
    integer :: k
    s%sum = 0
    s%mx = p(1)
    s%arr = 0
    do k = 1, n
      s%sum = s%sum + p(k)
      if (p(k) > s%mx) s%mx = p(k)
      s%arr(mod(k - 1, 4) + 1) = s%arr(mod(k - 1, 4) + 1) + p(k)
    end do
  end function summarize
  subroutine bump(r, t)
    !$omp declare target
    type(node), pointer, intent(in) :: r
    integer, intent(inout) :: t
    type(node), pointer :: c
    integer :: k
    c => child(r)
    do k = 1, nm
      c%a(k) = c%a(k) + 5 * k
      t = t + c%a(k)
    end do
  end subroutine bump
end module nd_m

program nd
  use omp_lib
  use nd_m
  implicit none
  integer :: host_flag, i, tot, ha1, out
  logical :: ok
  type(node), pointer :: r
  type(view) :: v
  type(stat3) :: s
  host_flag = 1
  tot = 0
  ha1 = 0
  out = 0
  !$omp target map(from: host_flag)
  host_flag = merge(1, 0, omp_is_initial_device())
  !$omp end target
  allocate(r)
  allocate(r%nx)
  allocate(r%a(nm))
  allocate(r%nx%a(nm))
  do i = 1, nm
    r%a(i) = 100 + i - 1
    r%nx%a(i) = 200 + i - 1
  end do
  ok = .true.
"""
_F_MAPS = """  !$omp map(to: r) map(to: r%a) map(to: r%nx) map(to: r%nx%a)"""


def fnres_programs() -> list[Program]:
    ar = [100 + i for i in range(8)]
    ac = [200 + i for i in range(8)]
    out = []
    # C: a struct holding a pointer, returned by value and passed on
    body = _C_HEAD + """  #pragma omp target map(tofrom: tot) \\
""" + _C_MAPS + """
  {
    struct view v = mkview(r->nx->a, NM);
    tot = vsum(v);
    v = mkview(r->a, NM);
    tot += vsum(v);
  }
"""
    out.append(_fn_program(
        "view-by-value", "c", "C OpenMP: a device function returns a struct "
        "that holds a pointer into a mapped array (by value, passed to a "
        "second function)", body, [("tot", sum(ar) + sum(ac))]))
    # C: a function returning a pointer to the next struct
    body = _C_HEAD + """  #pragma omp target enter data map(to: r[0:1]) map(to: r->a[0:NM]) \\
      map(to: r->nx[0:1]) map(to: r->nx->a[0:NM])
  #pragma omp target map(tofrom: tot)
  {
    for (int q = 0; q < NM; q++) {
      child(r)->a[q] = child(r)->a[q] + 5 * (q + 1);
      tot += child(r)->a[q];
    }
  }
  #pragma omp target exit data map(from: r->nx->a[0:NM]) map(from: r->nx[0:1]) \\
      map(from: r->a[0:NM]) map(from: r[0:1])
  for (i = 0; i < NM; i++) ha1 += r->nx->a[i];
"""
    new_ac = [v + 5 * (i + 1) for i, v in enumerate(ac)]
    out.append(_fn_program(
        "child-pointer", "c", "C OpenMP: a device function returns the "
        "pointer to the next struct of the chain; the kernel updates the "
        "child's array through it", body,
        [("tot", sum(new_ac)), ("ha1", sum(new_ac))]))
    # C: a struct with a fixed array returned by value
    body = _C_HEAD + """  #pragma omp target map(from: out) \\
""" + _C_MAPS + """
  {
    struct stat3 s = summarize(r->nx->a, NM);
    out = s.sum * 1000 + s.mx * 10 + s.arr[3];
  }
"""
    arr = [0] * 4
    for k, v in enumerate(ac):
        arr[k % 4] += v
    out.append(_fn_program(
        "stats-struct", "c", "C OpenMP: a device function returns a struct "
        "with a fixed-size array computed from a mapped pointer member",
        body, [("out", sum(ac) * 1000 + max(ac) * 10 + arr[3])]))
    # Fortran
    fh = _F_HEAD
    body = fh + """  !$omp target map(tofrom: tot) &
""" + _F_MAPS + """
    v = mkview(r%nx%a)
    tot = vsum(v)
    v = mkview(r%a)
    tot = tot + vsum(v)
  !$omp end target
"""
    out.append(_fn_program(
        "view-by-value", "f", "Fortran OpenMP: a device function result of "
        "derived type holds a pointer component associated with a mapped "
        "array", body, [("tot", sum(ar) + sum(ac))]))
    body = fh + """  !$omp target enter data map(to: r) map(to: r%a) map(to: r%nx) map(to: r%nx%a)
  !$omp target map(tofrom: tot)
    call bump(r, tot)
  !$omp end target
  !$omp target exit data map(from: r%nx%a) map(from: r%nx) map(from: r%a) map(from: r)
  ha1 = sum(r%nx%a)
"""
    out.append(_fn_program(
        "child-pointer", "f", "Fortran OpenMP: a device function returns "
        "a pointer to the next derived-type object of the chain; the kernel "
        "updates the child's array through it", body,
        [("tot", sum(new_ac)), ("ha1", sum(new_ac))]))
    body = fh + """  !$omp target map(from: out) &
""" + _F_MAPS + """
    s = summarize(r%nx%a, nm)
    out = s%sum * 1000 + s%mx * 10 + s%arr(4)
  !$omp end target
"""
    out.append(_fn_program(
        "stats-struct", "f", "Fortran OpenMP: a device function result of "
        "derived type with a fixed-size array component, computed from a "
        "mapped pointer component", body,
        [("out", sum(ac) * 1000 + max(ac) * 10 + arr[3])]))
    return out
