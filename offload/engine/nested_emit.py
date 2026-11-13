"""nested-data: the source text of a program (C or Fortran; OpenMP 5.2 or
OpenACC 3.4) from a shape, a plan and the model's expected values
(offload.engine.nested_gen). Nothing here decides legality or the expected
result."""
from __future__ import annotations

import textwrap

from offload.engine import nested_gen as G


def wrap_comment(mark, prefix, text, width=96):
    lines = textwrap.wrap(text, width, break_long_words=False,
                          break_on_hyphens=False)
    if not lines:
        return [f"{mark} {prefix}".rstrip()]
    return [f"{mark} {prefix}{lines[0]}"] + [f"{mark}   {ln}"
                                             for ln in lines[1:]]


OMP_MT = {"to": "to", "from": "from", "tofrom": "tofrom", "alloc": "alloc",
          "release": "release", "delete": "delete"}
ACC_ENTER = {"to": "copyin", "alloc": "create", "attach": "attach"}
ACC_EXIT = {"from": "copyout", "release": "delete", "delete": "delete",
            "detach": "detach", "tofrom": "copyout", "to": "delete",
            "alloc": "delete"}
ACC_REGION = {"to": "copyin", "tofrom": "copy", "from": "copyout",
              "alloc": "create", "present": "present"}


class Emitter:
    """Common walk; the language classes give the syntax."""
    mark = "//"

    def __init__(self, shape: G.Shape, plan: G.Plan, verdict, expected,
                 header_lines):
        self.s = shape
        self.cfg = shape.cfg
        self.plan = plan
        self.expected = expected
        self.header = header_lines
        self.fp = G.first_path(shape)
        self.refs = G.refs_of(shape)
        self.acc = self.cfg.model == "acc"
        self.par = self.cfg.kernel == "par"
        self.out: list[str] = []

    # --- helpers shared by both languages -------------------------------------------
    def put(self, text, indent=2):
        for ln in text.split("\n"):
            self.out.append(" " * indent + ln if ln else "")

    def visit_ops(self, v, ELEM, IDX, S, tot_add, assign, serial_scalar):
        """The statements of one visit: (element statements, scalar
        statements)."""
        n = self.s.nodes[v.nid]
        L = v.depth + 1
        el, sc = [], []
        if n.role in ("in", "inout"):
            el.append(tot_add(f"{L} * {ELEM}"))
        if n.role == "inout":
            el.append(assign(ELEM, f"{ELEM} + {7 * L}"))
        elif n.role == "out":
            el.append(assign(ELEM, f"{500 * L + 10 * v.j} + {IDX}"))
        if serial_scalar:
            if n.role in ("in", "inout"):
                sc.append(tot_add(S))
            if n.role == "inout":
                sc.append(assign(S, f"{S} + 3"))
            elif n.role == "out":
                sc.append(assign(S, f"{900 + v.j}"))
        return el, sc


# =============================== C =======================================================

class EmitC(Emitter):
    mark = "//"

    # expressions: (text, is_pointer)
    def root_expr(self):
        return {"var": ("r", False), "heap": ("r", True),
                "global": ("g", False)}[self.cfg.root]

    @staticmethod
    def acc_(e):
        return e[0] + ("->" if e[1] else ".")

    def node_expr(self, path):
        e = self.root_expr()
        for (eid, k) in path:
            ed = self.s.edges[eid]
            m = self.acc_(e) + ed.member
            kd = ed.kind
            if kd == "embed":
                e = (m, False)
            elif kd == "arr":
                e = (f"{m}[{k}]", False)
            elif kd == "ptr":
                e = (m, True)
            elif kd == "parr":
                e = (f"{m}[{k}]", False)
            else:                                # ptrs, pp
                e = (f"{m}[{k}]", True)
        return e

    def member(self, ed):
        p = self.node_expr(self.fp[ed.parent])
        return self.acc_(p) + ed.member

    def guards(self, path):
        conds = []
        e = self.root_expr()
        for i, (eid, k) in enumerate(path):
            ed = self.s.edges[eid]
            m = self.acc_(e) + ed.member
            if ed.kind in ("ptr", "parr"):
                conds.append(f"{m} != NULL")
            elif ed.kind == "ptrs":
                conds.append(f"{m}[{k}] != NULL")
            elif ed.kind == "pp":
                conds += [f"{m} != NULL", f"{m}[{k}] != NULL"]
            e = self.node_expr(path[:i + 1])
        return conds

    def item(self, ref):
        if ref == ("root",):
            return {"var": "r", "heap": "r[0:1]", "global": "g"}[
                self.cfg.root]
        if ref[0] == "d":
            n = self.s.nodes[ref[1]]
            return f"{self.acc_(self.node_expr(self.fp[n.nid]))}a" \
                   f"[0:{n.length}]"
        ed = self.s.edges[ref[1]]
        m = self.member(ed)
        if ref[0] == "pa":
            return f"{m}[0:NK]"
        k = ref[2]
        if ed.kind == "ptr":
            return f"{m}[0:1]"
        if ed.kind == "parr":
            return f"{m}[0:NK]"
        return f"{m}[{k}][0:1]"

    def ptr_lvalue(self, ref):
        if ref[0] == "d":
            n = self.s.nodes[ref[1]]
            return f"{self.acc_(self.node_expr(self.fp[n.nid]))}a"
        ed = self.s.edges[ref[1]]
        m = self.member(ed)
        if ref[0] == "pa" or ed.kind in ("ptr", "parr"):
            return m
        return f"{m}[{ref[2]}]"

    # --- directives -----------------------------------------------------------------
    def clauses_omp(self, items, root_only_mapper=False):
        out = []
        for it in items:
            mods = ", ".join(it.mods)
            out.append(f"map({mods + ', ' if mods else ''}{it.mt}: "
                       f"{self.item(it.ref)})")
        return out

    def clauses_acc(self, items, kind):
        groups: dict[str, list] = {}
        for it in items:
            tbl = {"enter": ACC_ENTER, "exit": ACC_EXIT,
                   "region": ACC_REGION}[kind]
            name = tbl[it.mt]
            if it.mt in ("attach", "detach"):
                groups.setdefault(name, []).append(self.ptr_lvalue(it.ref))
            else:
                groups.setdefault(name, []).append(self.item(it.ref))
        return [f"{n}({', '.join(v)})" for n, v in groups.items()]

    def pragma(self, head, clauses):
        sentinel = "acc" if self.acc else "omp"
        if not clauses:
            return f"#pragma {sentinel} {head}"
        lines = [f"#pragma {sentinel} {head} \\"]
        for i, c in enumerate(clauses):
            lines.append(f"    {c}" + (" \\" if i < len(clauses) - 1 else ""))
        return "\n".join(lines)

    # --- the program ---------------------------------------------------------------
    def emit(self) -> str:
        s, cfg = self.s, self.cfg
        o = self.out
        o += self.header
        o += ["#include <stdio.h>", "#include <stdlib.h>",
              "#include <openacc.h>" if self.acc else "#include <omp.h>", "",
              f"enum {{ NM = {G.NM}, NK = {G.NK} }};", ""]
        for tn in s.order:
            t = s.types[tn]
            o.append(f"struct {tn} {{")
            o.append("  int s;")
            o.append("  int a[NM];" if t.data == "fixed" else "  int *a;")
            for (m, kd, tt) in t.links:
                o.append("  " + {
                    "embed": f"struct {tt} {m};",
                    "arr": f"struct {tt} {m}[NK];",
                    "ptr": f"struct {tt} *{m};",
                    "parr": f"struct {tt} *{m};",
                    "ptrs": f"struct {tt} *{m}[NK];",
                    "pp": f"struct {tt} **{m};"}[kd])
            o.append("};")
        o.append("")
        if any(c.mapper for c in self.plan.cons):
            o += self.mappers()
        if cfg.root == "global":
            o += [f"struct {s.nodes[s.root].type} g;",
                  "#pragma omp declare target(g)", ""]
        o += ["int main(void)", "{", "  int host_flag = 1;", "  int ok = 1;",
              "  int i;", "  int tot = 0;"]
        lv = G.levels(s)
        o.append("  int " + ", ".join(
            [f"ha{L} = 0" for L in lv] + [f"hs{L} = 0" for L in lv
                                          if G.scalar_checked(s, L)]) + ";")
        rt = s.nodes[s.root].type
        if cfg.root == "var":
            o.append(f"  struct {rt} r = {{0}};")
        elif cfg.root == "heap":
            o.append(f"  struct {rt} *r = calloc(1, sizeof *r);")
        if self.acc:
            o += ["  #pragma acc serial copy(host_flag)",
                  "  host_flag = acc_on_device(acc_device_host) ? 1 : 0;"]
        else:
            o += ["  #pragma omp target map(from: host_flag)",
                  "  host_flag = omp_is_initial_device() ? 1 : 0;"]
        self.build_host()
        self.constructs()
        self.host_sums()
        o.append("  ok = 1;")
        for nm, val in self.expected:
            o.append(f"  ok = ok && ({nm} == {val});")
        for nm, _ in self.expected:
            o.append(f"  printf(\"{nm}= %d\\n\", {nm});")
        o += ["  printf(\"RESULT ran_on_host=%d check=%s\\n\", host_flag, "
              "ok ? \"pass\" : \"fail\");", "  return 0;", "}", ""]
        return "\n".join(o)

    def mappers(self):
        """One declare mapper per type: the type's own storage, its data
        array and everything its links point to (acyclic: the types of a
        chain are distinct)."""
        s, o = self.s, []
        role = s.nodes[s.root].role
        mt = G.mt_one(role)
        for tn in s.order:
            t = s.types[tn]
            cl = [f"map({mt}: v)"]
            if t.data == "ptr":
                cl.append(f"map({mt}: v.a[0:NM])")
            for (m, kd, tt) in t.links:
                if kd == "ptr":
                    cl.append(f"map({mt}: v.{m}[0:1])")
                elif kd == "parr":
                    cl.append(f"map({mt}: v.{m}[0:NK])")
                elif kd == "ptrs":
                    cl += [f"map({mt}: v.{m}[{k}][0:1])" for k in range(G.NK)]
                elif kd == "pp":
                    cl.append(f"map(to: v.{m}[0:NK])")
                    cl += [f"map({mt}: v.{m}[{k}][0:1])" for k in range(G.NK)]
            o.append(f"#pragma omp declare mapper(struct {tn} v) "
                     + " ".join(cl))
        o.append("")
        return o

    # --- the host side ---------------------------------------------------------------
    def build_host(self):
        s, o = self.s, self.out
        made = set()
        allocated = {s.root}
        for ed in s.edges:
            m = self.member(ed)
            tt = s.nodes[next((c for c in ed.children if c is not None),
                              ed.parent)].type
            tgt_t = None
            for (mm, kd, t2) in s.types[s.nodes[ed.parent].type].links:
                if mm == ed.member:
                    tgt_t = t2
            kd = ed.kind
            if kd in ("embed", "arr"):
                continue
            if kd == "ptr":
                c = ed.children[0]
                if c is None:
                    o.append(f"  {m} = NULL;")
                elif c in allocated:
                    o.append(f"  {m} = {self.node_expr(self.fp[c])[0]};")
                else:
                    o.append(f"  {m} = calloc(1, sizeof *{m});")
                    allocated.add(c)
            elif kd == "parr":
                if ed.children[0] is None:
                    o.append(f"  {m} = NULL;")
                else:
                    o.append(f"  {m} = calloc(NK, sizeof *{m});")
                    allocated.update(ed.children)
            else:
                if kd == "pp":
                    o.append(f"  {m} = calloc(NK, sizeof *{m});")
                for k, c in enumerate(ed.children):
                    if c is None:
                        o.append(f"  {m}[{k}] = NULL;")
                    elif c in allocated:
                        o.append(f"  {m}[{k}] = "
                                 f"{self.node_expr(self.fp[c])[0]};")
                    else:
                        o.append(f"  {m}[{k}] = calloc(1, sizeof *{m}[{k}]);")
                        allocated.add(c)
        for n in s.nodes.values():
            N = self.acc_(self.node_expr(self.fp[n.nid]))
            if s.types[n.type].data == "ptr":
                if n.owner == n.nid:
                    o.append(f"  {N}a = malloc(NM * sizeof(int));")
                else:
                    O = self.acc_(self.node_expr(self.fp[n.owner]))
                    off = f" + {n.off}" if n.off else ""
                    o.append(f"  {N}a = {O}a{off};")
        for n in s.nodes.values():
            N = self.acc_(self.node_expr(self.fp[n.nid]))
            s0 = -1 if n.role == "out" else 10 * (n.depth + 1) + n.nid
            o.append(f"  {N}s = {s0};")
            if n.owner == n.nid:
                base = "-1" if n.role == "out" else f"{100 * (n.nid + 1)} + i"
                o.append(f"  for (i = 0; i < NM; i++) {N}a[i] = {base};")

    # --- the constructs and the kernel ---------------------------------------------
    def constructs(self):
        o = self.out
        depth = 0
        for c in self.plan.cons:
            k = c.kind
            items = c.items
            if c.mapper:
                items = [i for i in items if i.ref == ("root",)] or items[:1]
                if k == "region":
                    items = [G.It(("root",), "tofrom")]
                elif k == "enter":
                    items = [G.It(("root",), "to")]
                else:
                    items = [G.It(("root",), "from")]
            if self.acc:
                self.acc_construct(c, items)
            else:
                self.omp_construct(c, items)

    def omp_construct(self, c, items):
        o = self.out
        k = c.kind
        if k == "enter":
            self.put(self.pragma("target enter data",
                                 self.clauses_omp(items)))
        elif k == "exit":
            self.put(self.pragma("target exit data",
                                 self.clauses_omp(items)))
        elif k == "tdata_open":
            self.put(self.pragma("target data", self.clauses_omp(items)))
            self.put("{")
        elif k == "tdata_close":
            self.put("}")
        elif k in ("upd_to", "upd_from"):
            w = "to" if k == "upd_to" else "from"
            cl = [f"{w}({self.item(i.ref)})" for i in items]
            if cl:
                self.put(self.pragma("target update", cl))
        else:
            self.region(items)

    def acc_construct(self, c, items):
        k = c.kind
        if k == "enter":
            self.put(self.pragma("enter data",
                                 self.clauses_acc(items, "enter")))
        elif k == "exit":
            self.put(self.pragma("exit data", self.clauses_acc(items, "exit")))
        elif k == "tdata_open":
            self.put(self.pragma("data", self.clauses_acc(items, "region")))
            self.put("{")
        elif k == "tdata_close":
            self.put("}")
        elif k in ("upd_to", "upd_from"):
            w = "device" if k == "upd_to" else "self"
            cl = [f"{w}({self.item(i.ref)})" for i in items]
            if cl:
                self.put(self.pragma("update", cl))
        else:
            self.region(items)

    def region(self, items):
        """The kernel."""
        s, o = self.s, self.out
        vs = G.visits(s)
        if self.acc:
            cl = self.clauses_acc(items, "region")
        else:
            cl = self.clauses_omp(items)
        if self.par:
            if self.acc:
                head = "parallel loop reduction(+: tot)"
            else:
                head = "target teams distribute parallel for reduction(+: tot)"
            self.put(self.pragma(head, cl))
            self.put("for (int q = 0; q < NM; q++) {")
            for v in vs:
                n = s.nodes[v.nid]
                N = self.acc_(self.node_expr(v.path))
                el, _ = self.visit_ops(
                    v, f"{N}a[q]", "q", f"{N}s",
                    lambda e: f"tot += {e};",
                    lambda lhs, rhs: f"{lhs} = {rhs};", False)
                if not el:
                    continue
                g = self.guards(v.path)
                if n.length < G.NM:
                    g = g + [f"q < {n.length}"]
                if g:
                    self.put(f"  if ({' && '.join(g)}) {{")
                    self.put("    " + "\n    ".join(el), 0)
                    self.put("  }")
                else:
                    self.put("  " + "\n  ".join(el))
            self.put("}")
            return
        if self.acc:
            self.put(self.pragma("serial", ["copy(tot)"] + cl))
        else:
            self.put(self.pragma("target", ["map(tofrom: tot)"] + cl))
        self.put("{")
        for v in vs:
            n = s.nodes[v.nid]
            N = self.acc_(self.node_expr(v.path))
            el, sc = self.visit_ops(
                v, f"{N}a[q]", "q", f"{N}s",
                lambda e: f"tot += {e};",
                lambda lhs, rhs: f"{lhs} = {rhs};", True)
            g = self.guards(v.path)
            ind = "  "
            if g:
                self.put(f"  if ({' && '.join(g)}) {{")
                ind = "    "
            if el:
                self.put(f"{ind}for (int q = 0; q < {n.length}; q++) {{")
                self.put(f"{ind}  " + f"\n{ind}  ".join(el), 0)
                self.put(f"{ind}}}")
            for x in sc:
                self.put(f"{ind}{x}")
            if g:
                self.put("  }")
        self.put("}")

    def host_sums(self):
        s = self.s
        for v in G.visits(s):
            n = s.nodes[v.nid]
            N = self.acc_(self.node_expr(v.path))
            g = self.guards(v.path)
            body = [f"for (i = 0; i < {n.length}; i++) ha{v.depth} += "
                    f"{N}a[i];"]
            if G.scalar_checked(s, v.depth):
                body.append(f"hs{v.depth} += {N}s;")
            if g:
                self.put(f"  if ({' && '.join(g)}) {{", 0)
                for b in body:
                    self.put("    " + b, 0)
                self.put("  }", 0)
            else:
                for b in body:
                    self.put("  " + b, 0)


# =============================== Fortran =================================================

class EmitF(Emitter):
    mark = "!"

    def node_expr(self, path):
        e = "r" if self.cfg.root != "global" else "g"
        for (eid, k) in path:
            ed = self.s.edges[eid]
            e = f"{e}%{ed.member}"
            if ed.kind in ("arr", "aarr", "parr"):
                e += f"({k + 1})"
        return e

    def guards(self, path):
        conds = []
        e = "r" if self.cfg.root != "global" else "g"
        for (eid, k) in path:
            ed = self.s.edges[eid]
            m = f"{e}%{ed.member}"
            if ed.kind in ("ptr", "parr"):
                conds.append(f"associated({m})")
            elif ed.kind in ("alloc", "aarr"):
                conds.append(f"allocated({m})")
            e = m + (f"({k + 1})" if ed.kind in ("arr", "aarr", "parr")
                     else "")
        return conds

    def item(self, ref):
        if ref == ("root",):
            return "r" if self.cfg.root != "global" else "g"
        if ref[0] == "d":
            return f"{self.node_expr(self.fp[ref[1]])}%a"
        ed = self.s.edges[ref[1]]
        return f"{self.node_expr(self.fp[ed.parent])}%{ed.member}"

    ptr_lvalue = item

    def directive(self, head, clauses, cont_ok=True):
        sentinel = "acc" if self.acc else "omp"
        if not clauses:
            return f"!${sentinel} {head}"
        lines = [f"!${sentinel} {head} &"]
        for i, c in enumerate(clauses):
            lines.append(f"!${sentinel} {c}" + (" &" if i < len(clauses) - 1
                                                else ""))
        return "\n".join(lines)

    def clauses_omp(self, items):
        out = []
        for it in items:
            mods = ", ".join(it.mods)
            out.append(f"map({mods + ', ' if mods else ''}{it.mt}: "
                       f"{self.item(it.ref)})")
        return out

    def clauses_acc(self, items, kind):
        tbl = {"enter": ACC_ENTER, "exit": ACC_EXIT, "region": ACC_REGION}[
            kind]
        groups: dict[str, list] = {}
        for it in items:
            groups.setdefault(tbl[it.mt], []).append(self.item(it.ref))
        return [f"{n}({', '.join(v)})" for n, v in groups.items()]

    def emit(self) -> str:
        s, cfg = self.s, self.cfg
        o = self.out
        o += self.header
        o += ["module nd_m", "  implicit none",
              f"  integer, parameter :: nm = {G.NM}, nk = {G.NK}"]
        for tn in s.order:
            t = s.types[tn]
            o.append(f"  type :: {tn}")
            o.append("    integer :: s = 0")
            o.append({"fixed": "    integer :: a(nm) = 0",
                      "ptr": "    integer, pointer :: a(:) => null()",
                      "alloc": "    integer, allocatable :: a(:)"}[t.data])
            for (m, kd, tt) in t.links:
                o.append("    " + {
                    "embed": f"type({tt}) :: {m}",
                    "arr": f"type({tt}) :: {m}(nk)",
                    "ptr": f"type({tt}), pointer :: {m} => null()",
                    "alloc": f"type({tt}), allocatable :: {m}",
                    "aarr": f"type({tt}), allocatable :: {m}(:)",
                    "parr": f"type({tt}), pointer :: {m}(:) => null()"}[kd])
            o.append(f"  end type {tn}")
        rt = s.nodes[s.root].type
        if cfg.root == "global":
            o += [f"  type({rt}) :: g", "  !$omp declare target(g)"]
        if any(c.mapper for c in self.plan.cons):
            o += self.mappers()
        o += ["end module nd_m", "", "program nd",
              "  use openacc" if self.acc else "  use omp_lib", "  use nd_m",
              "  implicit none", "  integer :: host_flag", "  logical :: ok",
              "  integer :: i, q", "  integer :: tot"]
        lv = G.levels(s)
        o.append("  integer :: " + ", ".join(
            [f"ha{L}" for L in lv] + [f"hs{L}" for L in lv
                                      if G.scalar_checked(s, L)]))
        if cfg.root == "var":
            o.append(f"  type({rt}) :: r")
        elif cfg.root == "heap":
            o.append(f"  type({rt}), pointer :: r")
        o += ["  host_flag = 1", "  tot = 0"]
        for L in lv:
            o.append(f"  ha{L} = 0")
            if G.scalar_checked(s, L):
                o.append(f"  hs{L} = 0")
        if self.acc:
            o += ["  !$acc serial copy(host_flag)",
                  "  host_flag = merge(1, 0, acc_on_device(acc_device_host))",
                  "  !$acc end serial"]
        else:
            o += ["  !$omp target map(from: host_flag)",
                  "  host_flag = merge(1, 0, omp_is_initial_device())",
                  "  !$omp end target"]
        if cfg.root == "heap":
            o.append("  allocate(r)")
        self.build_host()
        self.constructs()
        self.host_sums()
        o.append("  ok = .true.")
        for nm, val in self.expected:
            o.append(f"  ok = ok .and. ({nm} == {val})")
        for nm, _ in self.expected:
            o.append(f"  print '(a,i0)', '{nm}= ', {nm}")
        o += ["  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, "
              "' check=', merge('pass', 'fail', ok)", "end program nd", ""]
        return "\n".join(o)

    def mappers(self):
        s, o = self.s, []
        role = s.nodes[s.root].role
        mt = G.mt_one(role)
        for tn in s.order:
            t = s.types[tn]
            cl = [f"map({mt}: v)"]
            if t.data == "ptr":
                cl.append(f"map({mt}: v%a)")
            for (m, kd, tt) in t.links:
                if kd in ("ptr", "parr"):
                    cl.append(f"map({mt}: v%{m})")
            o.append(f"  !$omp declare mapper({tn} :: v) " + " ".join(cl))
        return o

    def build_host(self):
        s, o = self.s, self.out
        allocated = {s.root}
        for ed in s.edges:
            kd = ed.kind
            if kd in ("embed", "arr"):
                continue
            m = f"{self.node_expr(self.fp[ed.parent])}%{ed.member}"
            c = ed.children[0]
            if c is None:
                continue
            if kd in ("ptr", "alloc"):
                if c in allocated:
                    o.append(f"  {m} => {self.node_expr(self.fp[c])}")
                else:
                    o.append(f"  allocate({m})")
                    allocated.add(c)
            else:                              # parr, aarr
                o.append(f"  allocate({m}(nk))")
                allocated.update(ed.children)
        for n in s.nodes.values():
            N = self.node_expr(self.fp[n.nid])
            kind = s.types[n.type].data
            if kind in ("ptr", "alloc"):
                if n.owner == n.nid:
                    o.append(f"  allocate({N}%a(nm))")
                else:
                    O = self.node_expr(self.fp[n.owner])
                    o.append(f"  {N}%a => {O}%a({1 + n.off}:nm)")
        for n in s.nodes.values():
            N = self.node_expr(self.fp[n.nid])
            s0 = -1 if n.role == "out" else 10 * (n.depth + 1) + n.nid
            o.append(f"  {N}%s = {s0}")
            if n.owner == n.nid:
                base = "-1" if n.role == "out" else f"{100 * (n.nid + 1)} + q - 1"
                o.append(f"  do q = 1, nm")
                o.append(f"    {N}%a(q) = {base}")
                o.append("  end do")

    def constructs(self):
        for c in self.plan.cons:
            items = c.items
            if c.mapper:
                if c.kind == "region":
                    items = [G.It(("root",), "tofrom")]
                elif c.kind == "enter":
                    items = [G.It(("root",), "to")]
                else:
                    items = [G.It(("root",), "from")]
            if self.acc:
                self.acc_construct(c, items)
            else:
                self.omp_construct(c, items)

    def omp_construct(self, c, items):
        k = c.kind
        if k == "enter":
            self.put(self.directive("target enter data",
                                    self.clauses_omp(items)))
        elif k == "exit":
            self.put(self.directive("target exit data",
                                    self.clauses_omp(items)))
        elif k == "tdata_open":
            self.put(self.directive("target data", self.clauses_omp(items)))
        elif k == "tdata_close":
            self.put("!$omp end target data")
        elif k in ("upd_to", "upd_from"):
            w = "to" if k == "upd_to" else "from"
            cl = [f"{w}({self.item(i.ref)})" for i in items]
            if cl:
                self.put(self.directive("target update", cl))
        else:
            self.region(items)

    def acc_construct(self, c, items):
        k = c.kind
        if k == "enter":
            self.put(self.directive("enter data",
                                    self.clauses_acc(items, "enter")))
        elif k == "exit":
            self.put(self.directive("exit data",
                                    self.clauses_acc(items, "exit")))
        elif k == "tdata_open":
            self.put(self.directive("data", self.clauses_acc(items,
                                                              "region")))
        elif k == "tdata_close":
            self.put("!$acc end data")
        elif k in ("upd_to", "upd_from"):
            w = "device" if k == "upd_to" else "self"
            cl = [f"{w}({self.item(i.ref)})" for i in items]
            if cl:
                self.put(self.directive("update", cl))
        else:
            self.region(items)

    def region(self, items):
        s = self.s
        vs = G.visits(s)
        cl = self.clauses_acc(items, "region") if self.acc else \
            self.clauses_omp(items)
        asg = lambda lhs, rhs: f"{lhs} = {rhs}"
        add = lambda e: f"tot = tot + {e}"
        if self.par:
            if self.acc:
                head, tail = "parallel loop reduction(+: tot)", \
                    "!$acc end parallel loop"
            else:
                head = "target teams distribute parallel do reduction(+: tot)"
                tail = "!$omp end target teams distribute parallel do"
            self.put(self.directive(head, cl))
            self.put("do q = 1, nm")
            for v in vs:
                n = s.nodes[v.nid]
                N = self.node_expr(v.path)
                el, _ = self.visit_ops(v, f"{N}%a(q)", "(q - 1)", f"{N}%s",
                                       add, asg, False)
                if not el:
                    continue
                g = self.guards(v.path)
                if n.length < G.NM:
                    g = g + [f"q <= {n.length}"]
                if g:
                    self.put(f"  if ({' .and. '.join(g)}) then")
                    self.put("    " + "\n    ".join(el), 0)
                    self.put("  end if")
                else:
                    self.put("  " + "\n  ".join(el))
            self.put("end do")
            self.put(tail)
            return
        if self.acc:
            self.put(self.directive("serial", ["copy(tot)"] + cl))
        else:
            self.put(self.directive("target", ["map(tofrom: tot)"] + cl))
        for v in vs:
            n = s.nodes[v.nid]
            N = self.node_expr(v.path)
            el, sc = self.visit_ops(v, f"{N}%a(q)", "(q - 1)", f"{N}%s",
                                    add, asg, True)
            g = self.guards(v.path)
            ind = "  "
            if g:
                # nested single-condition ifs: associated()/allocated() may
                # not be evaluated when an earlier one is false
                for j, cnd in enumerate(g):
                    self.put("  " * (j + 1) + f"if ({cnd}) then")
                ind = "  " * (len(g) + 1)
            if el:
                self.put(f"{ind}do q = 1, {n.length}")
                self.put(f"{ind}  " + f"\n{ind}  ".join(el), 0)
                self.put(f"{ind}end do")
            for x in sc:
                self.put(f"{ind}{x}")
            for j in range(len(g), 0, -1):
                self.put("  " * j + "end if")
        self.put("!$acc end serial" if self.acc else "!$omp end target")

    def host_sums(self):
        s = self.s
        for v in G.visits(s):
            n = s.nodes[v.nid]
            N = self.node_expr(v.path)
            g = self.guards(v.path)
            body = [f"ha{v.depth} = ha{v.depth} + sum({N}%a(1:{n.length}))"]
            if G.scalar_checked(s, v.depth):
                body.append(f"hs{v.depth} = hs{v.depth} + {N}%s")
            for j, cnd in enumerate(g):
                self.put("  " * (j + 1) + f"if ({cnd}) then", 0)
            for b in body:
                self.put("  " * (len(g) + 1) + b, 0)
            for j in range(len(g), 0, -1):
                self.put("  " * j + "end if", 0)
