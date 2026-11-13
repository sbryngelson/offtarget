"""kernel-body campaign: the source text of a program
(offload.engine.kbody_gen.Cfg -> Fortran or C). The program is the student's
reproducer (results/student-repro/orig.f90) with one axis changed at a
time; the oracle is order-independent (see offload.engine.kbody_gen)."""
from __future__ import annotations

from offload.engine import kbody_cites as KC


def wrap_comment(mark, prefix, text, width=100):
    words, out, cur = text.split(), [], mark + " " + prefix
    pad = mark + " " + " " * len(prefix)
    for w in words:
        if len(cur) + 1 + len(w) > width and cur.strip(mark + " "):
            out.append(cur)
            cur = pad
        cur += ("" if cur.endswith(" ") else " ") + w
    out.append(cur)
    return out


def _header(cfg, pid_hint, expected, tags, verdict, mark):
    from offload.engine import kbody_gen as G
    rows = KC.rows_for(tags)
    h = [f"{mark} kbody ({'OpenMP 5.2'}, "
         f"{'C11' if cfg.lang == 'c' else 'free-form Fortran'}):"]
    h += wrap_comment(mark, "", G.title_of(cfg))
    h += wrap_comment(mark, "spec: ", "; ".join(KC.cite_text(r)
                                                for r in rows))
    h += wrap_comment(mark, "rules: ", ", ".join(tags))
    why = "; ".join(m for _, m in verdict.reasons)
    base = ("the base language defines the array constructors, the "
            "intrinsic assignments and the derived-type components "
            "(not in the cached spec texts)")
    h += wrap_comment(mark, "legality: ", verdict.status + ": " +
                      (why or "the atomic structured blocks are the "
                       "update/capture forms of OpenMP 5.2 4.3.1.3; " + base))
    h += wrap_comment(mark, "expected (computed by compliance/kbody_gen.py): ",
                      ", ".join(f"{k}= {v}" for k, v in expected.items()))
    h += wrap_comment(mark, "oracle: ", "order-independent: bad, dup and "
                      "missing records over a large problem, repeated "
                      "trials; the sums are invariant under any slot order")
    return h


def fold_fortran(text: str, width: int = 118) -> str:
    """Continue statement lines longer than `width` at a comma (never a
    directive or a comment)."""
    out = []
    for ln in text.split("\n"):
        while len(ln) > width and not ln.lstrip().startswith("!") and \
                ", " in ln[:width]:
            cut = ln.rfind(", ", 40, width) + 1
            out.append(ln[:cut] + " &")
            ln = " " * (len(ln) - len(ln.lstrip()) + 8) + ln[cut:].lstrip()
        out.append(ln)
    return "\n".join(out)


def emit(cfg, expected, tags, verdict) -> str:
    src = (EmitF if cfg.lang == "f" else EmitC)(
        cfg, expected, tags, verdict).emit()
    return fold_fortran(src) if cfg.lang == "f" else src


# =========================== Fortran ==========================================

class EmitF:
    INT = {"int4": "integer", "int8": "integer(8)", "real8": "real(8)"}
    NEG = {"int4": "-1", "int8": "-1_8", "real8": "-1.0d0"}
    ONE = {"int4": "1", "int8": "1_8", "real8": "1.0d0"}

    def __init__(self, cfg, expected, tags, verdict):
        from offload.engine import kbody_gen as G
        self.c, self.exp, self.tags, self.verdict = cfg, expected, tags, \
            verdict
        g = G.grid_size(cfg)
        self.m = self.n = self.p = g
        if cfg.dims:
            self.m, self.n, self.p = cfg.dims
        self.nsph = cfg.nper ** 3
        self.swap = cfg.claim == "swap"

    # -- small helpers ----------------------------------------------------------
    def cv(self, x):
        t = self.c.ctype
        return x if t == "int4" else f"int({x}, 8)" if t == "int8" \
            else f"real({x}, 8)"

    def ctor(self):
        return "[" + ", ".join(self.cv(v) for v in "ijk") + "]"

    def mk(self, a, b, c):
        return f"markers%sf({a}, {b}, {c})" if self.c.marker == "ptr" \
            else f"mk({a}, {b}, {c})"

    def whole(self, q):
        return {"elem_comp": f"gps({q})%loc", "col": f"locs(:, {q})",
                "row": f"locs({q}, :)",
                "nested": f"gps({q})%pos%loc"}[self.c.tgt]

    def sect(self, q):
        return {"elem_comp": f"gps({q})%loc(1:3)",
                "col": f"locs(1:3, {q})", "row": f"locs({q}, 1:3)",
                "nested": f"gps({q})%pos%loc(1:3)"}[self.c.tgt]

    def el(self, q, d):
        return {"elem_comp": f"gps({q})%loc({d})", "col": f"locs({d}, {q})",
                "row": f"locs({q}, {d})",
                "nested": f"gps({q})%pos%loc({d})"}[self.c.tgt]

    def lx(self, q, d):
        e = self.el(q, d)
        t = self.c.ctype
        return e if t == "int4" else f"int({e})" if t == "int8" \
            else f"nint({e})"

    def counter(self):
        return {"var": "count", "elem": "cnt(1)", "comp": "cs%count",
                "elemcomp": "cs(1)%count"}[self.c.cnt]

    def count_value(self):
        return self.counter()

    # -- the write idiom --------------------------------------------------------
    def loc_lines(self, q):
        c = self.c
        v = [self.cv(x) for x in "ijk"]
        W, S = self.whole(q), self.sect(q)
        k = c.loc
        if k == "ctor":
            return [f"{W} = {self.ctor()}"]
        if k == "ctor_old":
            return [f"{W} = (/ {', '.join(v)} /)"]
        if k == "ctor_expr":
            sh = [self.cv(f"{x} + 1") for x in "ijk"]
            return [f"{W} = [{', '.join(sh)}] - {self.ONE[c.ctype]}"]
        if k == "reshape":
            return [f"{W} = reshape({self.ctor()}, [3])"]
        if k == "merge":
            neg = ", ".join([self.NEG[c.ctype]] * 3)
            return [f"{W} = merge({self.ctor()}, [{neg}], "
                    f"{self.mk('i', 'j', 'k')} /= 0)"]
        if k == "section":
            return [f"{S} = {self.ctor()}"]
        if k == "elem":
            return [f"{self.el(q, d + 1)} = {v[d]}" for d in range(3)]
        if k == "loop":
            return ["do d = 1, 3",
                    f"    {self.el(q, 'd')} = merge({v[0]}, merge({v[1]}, "
                    f"{v[2]}, d == 2), d == 1)", "end do"]
        if k == "tmp":
            return [f"tmp3 = {self.ctor()}", f"{W} = tmp3"]
        if k == "func":
            return [f"{W} = f3(i, j, k)"]
        if k == "pack":
            return [f"tmp3(1) = {v[0]}; tmp3(2) = {v[1]}; tmp3(3) = {v[2]}",
                    f"{W} = pack(tmp3, allt)"]
        if k == "cshift":
            return [f"tmp3(1) = {v[0]}; tmp3(2) = {v[1]}; tmp3(3) = {v[2]}",
                    f"{W} = cshift(tmp3, 0)"]
        if k == "merge_arr":
            return [f"tmp3(1) = {v[0]}; tmp3(2) = {v[1]}; tmp3(3) = {v[2]}",
                    f"tmp4 = {self.NEG[c.ctype]}",
                    f"{W} = merge(tmp3, tmp4, allt)"]
        if k == "matmul":
            return [f"tmp3(1) = {v[0]}; tmp3(2) = {v[1]}; tmp3(3) = {v[2]}",
                    f"{W} = matmul(ident, tmp3)"]
        if k == "func_elem":
            return [f"{W} = f3e(i, j, k)"]
        if k == "arrexpr":
            return [f"tmp3(1) = {v[0]}; tmp3(2) = {v[1]}; tmp3(3) = {v[2]}",
                    f"tmp4 = {self.ONE[c.ctype]}",
                    f"{W} = tmp3 + tmp4 - {self.ONE[c.ctype]}"]
        if k == "arrcopy":
            return [f"tmp3(1) = {v[0]}; tmp3(2) = {v[1]}; tmp3(3) = {v[2]}",
                    f"{W} = tmp3"]
        if k == "rec_assign":
            return [f"gp0%loc(1) = {v[0]}; gp0%loc(2) = {v[1]}; "
                    f"gp0%loc(3) = {v[2]}",
                    f"gp0%ib_patch_id = {self.mk('i', 'j', 'k')}",
                    f"gps({q}) = gp0"]
        raise ValueError(k)

    def aux_lines(self, q):
        a = self.c.aux
        if a == "real":
            return [f"gps({q})%ip_loc = [real(i, 8), real(j, 8), "
                    f"real(k, 8)] * 0.5d0"]
        if a == "logical":
            return [f"gps({q})%flags = [mod(i, 2) == 0, mod(j, 2) == 0, "
                    f"mod(k, 2) == 0]"]
        if a == "grid":
            return [f"gps({q})%ip_grid = [i, j, k]"]
        if a == "db":
            return [f"gps({q})%DB = [0, 0, 0]"]
        if a == "matrix":
            return [f"gps({q})%interp_coeffs = reshape([(real(i + j + k + "
                    f"cc, 8), cc = 1, 8)], [2, 2, 2])"]
        return []

    def extras_lines(self, q):
        if not self.c.extras or self.c.rec != "ghost":
            return []
        return [f"gps({q})%x_periodicity = 0; gps({q})%y_periodicity = 0; "
                f"gps({q})%z_periodicity = 0",
                f"gps({q})%slip = .false.",
                f"gps({q})%DB(1) = 0; gps({q})%DB(2) = 0; "
                f"gps({q})%DB(3) = 0"]

    def claim_lines(self):
        c = self.c
        X = self.counter()
        if c.claim == "cap_uf":
            return ["!$omp atomic capture", f"{X} = {X} + 1",
                    f"local_idx = {X}", "!$omp end atomic"]
        if c.claim == "cap_fu":
            return ["!$omp atomic capture", f"local_idx = {X}",
                    f"{X} = {X} + 1", "!$omp end atomic",
                    "local_idx = local_idx + 1"]
        if c.claim == "none":
            return ["local_idx = rk(i, j, k)"]
        return []

    def body(self):
        """The statements of one qualifying cell."""
        c = self.c
        o = []
        if self.swap:
            o += [f"id = {self.mk('i', 'j', 'k')}",
                  "!$omp atomic capture", "old = first(id)",
                  "first(id) = 1", "!$omp end atomic",
                  "if (old == 0) then"]
            inner = ["local_idx = id"] + self.loc_lines("local_idx") + \
                self.aux_lines("local_idx") + \
                ["gps(local_idx)%ib_patch_id = id"] + \
                self.extras_lines("local_idx") + \
                ["!$omp atomic update", "wc(id) = wc(id) + 1"]
            o += ["    " + s for s in inner] + ["end if"]
            return o
        o += self.claim_lines()
        o += self.loc_lines("local_idx")
        o += self.aux_lines("local_idx")
        o += [f"id = {self.mk('i', 'j', 'k')}",
              "gps(local_idx)%ib_patch_id = id"]
        o += self.extras_lines("local_idx")
        return o

    # -- the program -------------------------------------------------------------
    def private_list(self):
        c = self.c
        v = ["i", "j", "k", "ii", "jj", "kk", "is_gp", "local_idx", "id"]
        if c.loc == "loop":
            v.append("d")
        if c.loc in ("tmp", "arrexpr", "arrcopy", "pack", "cshift",
                     "merge_arr", "matmul"):
            v.append("tmp3")
        if c.loc in ("arrexpr", "merge_arr"):
            v.append("tmp4")
        if c.loc == "rec_assign":
            v.append("gp0")
        if c.aux == "matrix":
            v.append("cc")
        if self.swap:
            v.append("old")
        return v

    def types(self):
        c, o = self.c, []
        it = self.INT[c.ctype]
        if c.marker == "ptr":
            o += ["    type integer_field",
                  "        integer, pointer, dimension(:,:,:) :: sf => null()",
                  "    end type integer_field"]
        if c.cnt in ("comp", "elemcomp"):
            o += ["    type counter_t", "        integer :: count",
                  "    end type counter_t"]
        if c.tgt == "nested":
            o += ["    type pos_t",
                  f"        {it}, dimension(3) :: loc", "    end type pos_t"]
        o += ["    type ghost_point"]
        if c.rec == "ghost":
            o += [f"        {it}, dimension(3) :: loc",
                  "        real(8), dimension(3) :: ip_loc",
                  "        integer, dimension(3) :: ip_grid",
                  "        real(8), dimension(2, 2, 2) :: interp_coeffs",
                  "        logical :: interp_valid",
                  "        integer :: ib_patch_id", "        real(8) :: levelset",
                  "        real(8), dimension(3) :: levelset_norm",
                  "        logical :: slip",
                  "        integer, dimension(3) :: DB",
                  "        integer :: x_periodicity, y_periodicity, "
                  "z_periodicity"]
            if c.aux == "logical":
                o.append("        logical, dimension(3) :: flags")
        else:
            o += [f"        {it}, dimension(3) :: loc",
                  "        integer :: ib_patch_id"]
        if c.tgt == "nested":
            o.append("        type(pos_t) :: pos")
        o += ["    end type ghost_point"]
        return o

    def module(self):
        c = self.c
        it = self.INT[c.ctype]
        o = ["module kb_m", "    implicit none",
             f"    integer, parameter :: m = {self.m}, n = {self.n}, "
             f"p = {self.p}, buff = 10, layers = {c.layers}"]
        if self.swap:
            o.append(f"    integer, parameter :: nsph = {self.nsph}")
        o += self.types()
        decl = []
        if c.marker == "ptr":
            o.append("    type(integer_field) :: markers")
            decl.append("markers")
        else:
            o.append("    integer, allocatable, dimension(:,:,:) :: mk")
            decl.append("mk")
        o.append("    type(ghost_point), allocatable, dimension(:) :: gps")
        decl.append("gps")
        if c.tgt in ("col", "row"):
            o.append(f"    {it}, allocatable, dimension(:,:) :: locs")
            decl.append("locs")
        if c.claim == "none":
            o.append("    integer, allocatable, dimension(:,:,:) :: rk")
        if self.swap:
            o.append("    integer, allocatable, dimension(:) :: first, wc")
        if c.storage == "declare":
            o.append(f"    !$omp declare target({', '.join(decl)})")
        if c.loc in ("pack", "merge_arr"):
            o.append("    logical, parameter :: allt(3) = .true.")
        if c.loc == "matmul":
            z = {"int4": "0", "int8": "0_8", "real8": "0.0d0"}[c.ctype]
            one = self.ONE[c.ctype]
            o.append(f"    {it}, parameter :: ident(3, 3) = reshape([{one}, "
                     f"{z}, {z}, {z}, {one}, {z}, {z}, {z}, {one}], [3, 3])")
        o.append("contains")
        if c.loc == "func_elem":
            o += [f"    pure function f3e(a, b, c) result(r)",
                  "        !$omp declare target",
                  "        integer, intent(in) :: a, b, c",
                  f"        {it}, dimension(3) :: r",
                  f"        r(1) = {self.cv('a')}; r(2) = {self.cv('b')}; "
                  f"r(3) = {self.cv('c')}", "    end function f3e"]
        if c.loc == "func":
            o += [f"    pure function f3(a, b, c) result(r)",
                  "        !$omp declare target",
                  "        integer, intent(in) :: a, b, c",
                  f"        {it}, dimension(3) :: r",
                  f"        r = [{self.cv('a')}, {self.cv('b')}, "
                  f"{self.cv('c')}]", "    end function f3"]
        o += self.kernel()
        o.append("end module kb_m")
        return o

    def kernel(self):
        c = self.c
        o = ["    subroutine find_cells(ncount)",
             "        integer, intent(out) :: ncount",
             "        integer :: i, j, k, ii, jj, kk, local_idx, id, d, cc, old",
             "        logical :: is_gp"]
        it = self.INT[c.ctype]
        if c.loc in ("tmp", "arrexpr", "arrcopy", "pack", "cshift",
                     "merge_arr", "matmul"):
            o.append(f"        {it}, dimension(3) :: tmp3")
        if c.loc in ("arrexpr", "merge_arr"):
            o.append(f"        {it}, dimension(3) :: tmp4")
        if c.loc == "rec_assign":
            o.append("        type(ghost_point) :: gp0")
        X = self.counter()
        if c.claim in ("cap_uf", "cap_fu"):
            if c.cnt == "var":
                o.append("        integer :: count")
                cmap = "count"
                init = "count = 0"
            elif c.cnt == "elem":
                o.append("        integer :: cnt(2)")
                cmap = "cnt"
                init = "cnt = 0"
            elif c.cnt == "comp":
                o += ["        type(counter_t) :: cs"]
                cmap = "cs"
                init = "cs%count = 0"
            else:
                o += ["        type(counter_t) :: cs(2)"]
                cmap = "cs"
                init = "cs%count = 0"
            o.append("        " + init)
        maps = []
        if c.claim in ("cap_uf", "cap_fu"):
            maps.append(f"map({c.count_map}: {cmap})")
        if c.claim == "none":
            maps.append("map(to: rk)")
        if self.swap:
            maps.append("map(tofrom: first, wc)")
        if c.storage == "declare" and c.hda:
            hd = ["gps"] + (["locs"] if c.tgt in ("col", "row") else [])
            maps.append(f"has_device_addr({', '.join(hd)})")
        o.append(f"        !$omp target teams distribute parallel do "
                 f"collapse({c.collapse}) &")
        o.append(f"        !$omp& private({', '.join(self.private_list())}) "
                 f"&" if maps else
                 f"        !$omp& private({', '.join(self.private_list())})")
        for k, mp in enumerate(maps):
            o.append(f"        !$omp& {mp}" + (" &" if k < len(maps) - 1
                                             else ""))
        body = self.body()
        pred = {"all": f"{self.mk('i', 'j', 'k')} /= 0",
                "div": f"{self.mk('i', 'j', 'k')} /= 0 .and. mod(i + j + k, "
                       f"2) == 0"}.get(c.branch)
        ind = "                    "
        loops = [f"        do i = 0, m", "            do j = 0, n",
                 "                do k = 0, p"]
        o += loops
        if c.branch == "search":
            L = "layers"
            o += [f"{ind}if ({self.mk('i', 'j', 'k')} /= 0) then",
                  f"{ind}    is_gp = .false.",
                  f"{ind}    search: do ii = i - {L}, i + {L}",
                  f"{ind}        do jj = j - {L}, j + {L}",
                  f"{ind}            do kk = k - {L}, k + {L}",
                  f"{ind}                if ({self.mk('ii', 'jj', 'kk')} == 0) "
                  f"then",
                  f"{ind}                    is_gp = .true.; exit search",
                  f"{ind}                end if",
                  f"{ind}            end do", f"{ind}        end do",
                  f"{ind}    end do search", f"{ind}    if (is_gp) then"]
            o += [ind + "        " + s for s in body]
            o += [f"{ind}    end if", f"{ind}end if"]
        else:
            o.append(f"{ind}if ({pred}) then")
            o += [ind + "    " + s for s in body]
            o.append(f"{ind}end if")
        o += ["                end do", "            end do", "        end do",
              "        !$omp end target teams distribute parallel do"]
        if c.claim in ("cap_uf", "cap_fu"):
            o.append(f"        ncount = {X}")
        else:
            o.append("        ncount = 0")
        o.append("    end subroutine find_cells")
        return o

    def host_pred(self):
        c = self.c
        if c.branch == "all":
            return f"{self.mk('i', 'j', 'k')} /= 0"
        if c.branch == "div":
            return f"{self.mk('i', 'j', 'k')} /= 0 .and. mod(i + j + k, 2) == 0"
        mk = "markers%sf" if c.marker == "ptr" else "mk"
        return (f"{self.mk('i', 'j', 'k')} /= 0 .and. any({mk}(i - layers:"
                f"i + layers, j - layers:j + layers, &\n"
                f"            k - layers:k + layers) == 0)")

    def main(self):
        c = self.c
        it = self.INT[c.ctype]
        slots = "nsph" if self.swap else "num_gps"
        o = ["program kbody", "    use omp_lib", "    use kb_m",
             "    implicit none",
             "    integer :: spacing, nper, trials, t, q, i, j, k, a, b, cc, "
             "id, num_gps, host_flag, ncount, num_slots",
             "    integer :: l1, l2, l3, bad, dup, missing, claimed, "
             "bad_max, dup_max, missing_max",
             "    integer(8) :: sx, sy, sz, sid, sx_o, sy_o, sz_o, sid_o",
             "    integer :: claimed_o, count_o",
             "    logical :: ok, mism",
             "    integer, allocatable :: hits(:, :, :)"]
        o += [f"    spacing = {c.spacing}; nper = {c.nper}; "
              f"trials = {c.trials}"]
        o += ["    allocate (hits(0:m, 0:n, 0:p))"]
        if c.marker == "ptr":
            o.append("    allocate (markers%sf(-buff:m + buff, -buff:n + buff,"
                     " -buff:p + buff))")
            o.append("    markers%sf = 0")
        else:
            o.append("    allocate (mk(-buff:m + buff, -buff:n + buff, "
                     "-buff:p + buff))")
            o.append("    mk = 0")
        if c.geom == "dense":
            o += ["    id = 0",
                  "    do k = 0, p; do j = 0, n; do i = 0, m",
                  f"        {self.mk('i', 'j', 'k')} = mod(i + j + k, 7) + 1",
                  "    end do; end do; end do",
                  "    num_gps = 0"]
        else:
            o += ["    id = 0",
                  "    do a = 0, nper - 1; do b = 0, nper - 1; do cc = 0, nper - 1",
                  "        id = id + 1",
                  "        do k = -4, 4; do j = -4, 4; do i = -4, 4",
                  "            if (i*i + j*j + k*k <= 16) "
                  f"{self.mk('8 + a*spacing + i', '8 + b*spacing + j', '8 + cc*spacing + k')} = id",
                  "        end do; end do; end do",
                  "    end do; end do; end do",
                  "    num_gps = 0"]
        if c.claim == "none":
            o.append("    allocate (rk(0:m, 0:n, 0:p)); rk = 0")
        o += ["    do k = 0, p; do j = 0, n; do i = 0, m",
              f"        if ({self.host_pred()}) then",
              "            num_gps = num_gps + 1"]
        if c.claim == "none":
            o.append("            rk(i, j, k) = num_gps")
        o += ["        end if", "    end do; end do; end do"]
        o.append(f"    num_slots = {slots}")
        o.append("    allocate (gps(num_slots))")
        if c.tgt in ("col", "row"):
            shape = "3, num_slots" if c.tgt == "col" else "num_slots, 3"
            o.append(f"    allocate (locs({shape}))")
        if self.swap:
            o.append("    allocate (first(nsph), wc(nsph))")
        # device data
        if c.marker == "ptr":
            o += ["    !$omp target enter data map(always, alloc: "
                  "markers%sf)", "    !$omp target update to(markers%sf)"]
        else:
            o += ["    !$omp target enter data map(to: mk)"]
        o += ["    !$omp target enter data map(alloc: gps)"]
        if c.tgt in ("col", "row"):
            o.append("    !$omp target enter data map(alloc: locs)")
        o += ["    host_flag = 1",
              "    !$omp target map(from: host_flag)",
              "    host_flag = merge(1, 0, omp_is_initial_device())",
              "    !$omp end target",
              "    print '(A,I0,A,I0)', 'spheres ', id, '  cells ', num_gps"]
        o += ["    bad_max = 0; dup_max = 0; missing_max = 0",
              "    claimed_o = -1; sx_o = -1; sy_o = -1; sz_o = -1; "
              "sid_o = -1; count_o = -1"]
        o.append("    do t = 1, trials")
        # reset
        o.append("        do q = 1, num_slots")
        o.append(f"            {self.whole('q')} = {self.NEG[c.ctype]}")
        o.append("            gps(q)%ib_patch_id = -1")
        o += ["        end do",
              "        !$omp target update to(gps)"]
        if c.tgt in ("col", "row"):
            o.append("        !$omp target update to(locs)")
        if self.swap:
            o.append("        first = 0; wc = 0")
        o.append("        call find_cells(ncount)")
        o.append("        !$omp target update from(gps)")
        if c.tgt in ("col", "row"):
            o.append("        !$omp target update from(locs)")
        o += ["        hits = 0; bad = 0; claimed = 0; sx = 0; sy = 0; "
              "sz = 0; sid = 0",
              "        do q = 1, num_slots",
              f"            l1 = {self.lx('q', 1)}; l2 = {self.lx('q', 2)}; "
              f"l3 = {self.lx('q', 3)}"]
        if self.swap:
            o += ["            if (l1 < 0) cycle"]
        o += ["            if (l1 < 0 .or. l2 < 0 .or. l3 < 0 .or. l1 > m "
              ".or. l2 > n .or. l3 > p) then",
              "                bad = bad + 1; cycle", "            end if",
              "            hits(l1, l2, l3) = hits(l1, l2, l3) + 1",
              "            claimed = claimed + 1",
              "            sx = sx + l1; sy = sy + l2; sz = sz + l3",
              "            sid = sid + gps(q)%ib_patch_id"]
        want = "q" if self.swap else "gps(q)%ib_patch_id"
        o.append(f"            if ({self.mk('l1', 'l2', 'l3')} /= {want}) "
                 "bad = bad + 1")
        if self.swap:
            o.append("            if (gps(q)%ib_patch_id /= q) bad = bad + 1")
        a = c.aux
        if a == "real":
            o.append("            if (any(gps(q)%ip_loc /= 0.5d0 * real([l1, "
                     "l2, l3], 8))) bad = bad + 1")
        elif a == "logical":
            o.append("            if (any(gps(q)%flags .neqv. [mod(l1, 2) == "
                     "0, mod(l2, 2) == 0, mod(l3, 2) == 0])) bad = bad + 1")
        elif a == "db":
            o.append("            if (any(gps(q)%DB /= 0)) bad = bad + 1")
        elif a == "grid":
            o.append("            if (any(gps(q)%ip_grid /= [l1, l2, l3])) "
                     "bad = bad + 1")
        elif a == "matrix":
            o.append("            if (any(gps(q)%interp_coeffs /= reshape(["
                     "(real(l1 + l2 + l3 + cc, 8), cc = 1, 8)], [2, 2, 2])))"
                     " bad = bad + 1")
        if c.extras and c.rec == "ghost":
            o.append("            if (gps(q)%x_periodicity /= 0 .or. "
                     "gps(q)%y_periodicity /= 0 .or. &")
            o.append("                gps(q)%z_periodicity /= 0 .or. "
                     "gps(q)%slip .or. any(gps(q)%DB /= 0)) bad = bad + 1")
        o.append("        end do")
        if self.swap:
            o += ["        dup = count(wc > 1); missing = count(wc == 0)"]
        else:
            o += ["        dup = count(hits > 1); missing = num_gps - "
                  "count(hits > 0)"]
        o += ["        print '(A,I3,A,I0,A,I0,A,I0,A,I0)', 'trial ', t, ': "
              "bad records ', bad, &",
              "            '  duplicated cells ', dup, '  missing cells ', "
              "missing, '  claimed ', claimed",
              "        bad_max = max(bad_max, bad); dup_max = max(dup_max, "
              "dup)",
              "        missing_max = max(missing_max, missing)"]
        # keep the first trial whose summary differs from the model's
        want = self.exp
        cond = [f"claimed /= {want['claimed']}"]
        if "sum_x" in want:
            cond += [f"sx /= {want['sum_x']}_8", f"sy /= {want['sum_y']}_8",
                     f"sz /= {want['sum_z']}_8",
                     f"sid /= {want['sum_id']}_8"]
        if "count" in want:
            cond += [f"ncount /= {want['count']}"]
        o.append("        mism = .false.")
        for cnd in cond:
            o.append(f"        mism = mism .or. ({cnd})")
        o += ["        if (claimed_o < 0 .or. mism) then",
              "            if (claimed_o < 0 .or. claimed_o == "
              f"{want['claimed']}) then",
              "                claimed_o = claimed; sx_o = sx; sy_o = sy; "
              "sz_o = sz; sid_o = sid; count_o = ncount",
              "            end if", "        end if"]
        o.append("    end do")
        o.append("    ok = .true.")
        o.append(f"    ok = ok .and. (num_gps == {want['num_gps']})")
        o.append(f"    ok = ok .and. (claimed_o == {want['claimed']})")
        if "sum_x" in want:
            for nm, key in (("sx_o", "sum_x"), ("sy_o", "sum_y"),
                            ("sz_o", "sum_z"), ("sid_o", "sum_id")):
                o.append(f"    ok = ok .and. ({nm} == {want[key]}_8)")
        o += ["    ok = ok .and. (bad_max == 0) .and. (dup_max == 0) .and. "
              "(missing_max == 0)"]
        if "count" in want:
            o.append(f"    ok = ok .and. (count_o == {want['count']})")
        o.append("    print '(A,I0)', 'num_gps= ', num_gps")
        o.append("    print '(A,I0)', 'claimed= ', claimed_o")
        if "sum_x" in want:
            for nm, key in (("sx_o", "sum_x"), ("sy_o", "sum_y"),
                            ("sz_o", "sum_z"), ("sid_o", "sum_id")):
                o.append(f"    print '(A,I0)', '{key}= ', {nm}")
        o += ["    print '(A,I0)', 'bad= ', bad_max",
              "    print '(A,I0)', 'dup= ', dup_max",
              "    print '(A,I0)', 'missing= ', missing_max"]
        if "count" in want:
            o.append("    print '(A,I0)', 'count= ', count_o")
        o += ["    print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, "
              "' check=', merge('pass', 'fail', ok)",
              "end program kbody", ""]
        return o

    def emit(self):
        head = _header(self.c, "", self.exp, self.tags, self.verdict, "!")
        return "\n".join(head + self.module() + [""] + self.main())


# =========================== C =================================================

class EmitC:
    def __init__(self, cfg, expected, tags, verdict):
        from offload.engine import kbody_gen as G
        self.c, self.exp, self.tags, self.verdict = cfg, expected, tags, \
            verdict
        g = G.grid_size(cfg)
        self.m = self.n = self.p = g
        if cfg.dims:
            self.m, self.n, self.p = cfg.dims
        self.nsph = cfg.nper ** 3
        self.swap = cfg.claim == "swap"
        self.it = "long" if cfg.ctype == "int8" else "int"

    def counter(self):
        return {"var": "count", "elem": "cnt[0]", "member": "cs.count"}[
            self.c.cnt]

    def loc(self, v, d):
        return f"g[{v}].pos.loc[{d}]" if self.c.tgt == "nested" else \
            f"g[{v}].loc[{d}]"

    def locarr(self, v):
        return f"g[{v}].pos.loc" if self.c.tgt == "nested" else \
            f"g[{v}].loc"

    def loc_lines(self, v):
        c, it = self.c, self.it
        k = c.loc
        if k == "scalars":
            return [f"{self.loc(v, d)} = {x};" for d, x in enumerate("ijk")]
        if k == "memcpy_literal":
            return [f"memcpy({self.locarr(v)}, ({it}[]){{i, j, k}}, "
                    f"3 * sizeof({it}));"]
        if k == "struct_literal":
            return [f"g[{v}].pos = (pos_t){{{{i, j, k}}}};"]
        if k == "loop":
            return ["for (d = 0; d < 3; d++)",
                    f"    {self.loc(v, 'd')} = (d == 0 ? i : (d == 1 ? j : "
                    f"k));"]
        if k == "tmp_struct":
            return ["pos_t tp = {{i, j, k}};", f"g[{v}].pos = tp;"]
        if k == "tmp_array":
            return [f"{it} tmp3[3] = {{i, j, k}};", "for (d = 0; d < 3; d++)",
                    f"    {self.loc(v, 'd')} = tmp3[d];"]
        raise ValueError(k)

    def claim_lines(self):
        c, X = self.c, self.counter()
        if c.claim == "cap_uf":
            return ["#pragma omp atomic capture", f"{{ {X} += 1; v = {X}; }}"]
        if c.claim == "cap_fu":
            return ["#pragma omp atomic capture", f"{{ v = {X}; {X} += 1; }}",
                    "v = v + 1;"]
        if c.claim == "cap_stmt":
            return ["#pragma omp atomic capture", f"v = {X}++;",
                    "v = v + 1;"]
        if c.claim == "none":
            return ["v = rk[IDX(i, j, k)];"]
        return []

    def body(self):
        c = self.c
        o = []
        if self.swap:
            o += [f"id = mk[IDX(i, j, k)];", "#pragma omp atomic capture",
                  "{ old = first[id]; first[id] = 1; }", "if (old == 0) {",
                  "    v = id;"]
            inner = self.loc_lines("v") + ["g[v].ib_patch_id = id;"] + \
                self.extras("v") + ["#pragma omp atomic update",
                                    "wc[id] += 1;"]
            o += ["    " + s for s in inner] + ["}"]
            return o
        o += self.claim_lines()
        o += self.loc_lines("v")
        o += ["id = mk[IDX(i, j, k)];", "g[v].ib_patch_id = id;"]
        o += self.extras("v")
        return o

    def extras(self, v):
        if not self.c.extras or self.c.rec != "ghost":
            return []
        return [f"g[{v}].xp = 0; g[{v}].yp = 0; g[{v}].zp = 0;",
                f"g[{v}].slip = 0;",
                f"g[{v}].DB[0] = 0; g[{v}].DB[1] = 0; g[{v}].DB[2] = 0;"]

    def emit(self):
        c, it = self.c, self.it
        head = _header(c, "", self.exp, self.tags, self.verdict, "//")
        ns = "NSPH" if self.swap else "NS"
        o = head + ["#include <stdio.h>", "#include <stdlib.h>",
                    "#include <string.h>", "#include <omp.h>",
                    f"#define M {self.m}", f"#define N {self.n}",
                    f"#define P {self.p}", "#define BUFF 10",
                    f"#define LAYERS {c.layers}",
                    f"#define NSPH {self.nsph}",
                    "#define NX (M + 2 * BUFF + 1)",
                    "#define NY (N + 2 * BUFF + 1)",
                    "#define NZ (P + 2 * BUFF + 1)",
                    "#define IDX(a, b, cc) ((((a) + BUFF) * NY + ((b) + BUFF))"
                    " * NZ + ((cc) + BUFF))",
                    f"typedef struct {{ {it} loc[3]; }} pos_t;",
                    "typedef struct { int count; } counter_t;"]
        if c.rec == "ghost":
            o += ["typedef struct {"]
            if c.tgt != "nested":
                o.append(f"    {it} loc[3];")
            o += ["    pos_t pos;", "    double ip_loc[3];", "    int ib_patch_id;",
                  "    double levelset;", "    int DB[3];", "    int xp, yp, zp;",
                  "    int slip;", "} ghost_t;"]
        else:
            o += ["typedef struct {"]
            if c.tgt != "nested":
                o.append(f"    {it} loc[3];")
            o += ["    pos_t pos;", "    int ib_patch_id;", "} ghost_t;"]
        o += ["", "int main(void) {",
              "    int spacing = %d, nper = %d, trials = %d;" % (
                  c.spacing, c.nper, c.trials),
              "    long ntot = (long)NX * NY * NZ;",
              "    int *mk = (int *)calloc(ntot, sizeof(int));",
              "    int *hits = (int *)calloc(ntot, sizeof(int));",
              "    int id = 0, num_gps = 0, host_flag = 1, ncount = 0;",
              "    int *rk = NULL, *first = NULL, *wc = NULL;",
              "    int a, b, cc, i, j, k, q, t;"]
        if c.geom == "dense":
            o += ["    for (i = 0; i <= M; i++) for (j = 0; j <= N; j++) for "
                  "(k = 0; k <= P; k++) mk[IDX(i, j, k)] = (i + j + k) % 7 + 1;"]
        else:
            o += ["    for (a = 0; a < nper; a++) for (b = 0; b < nper; b++) for "
                  "(cc = 0; cc < nper; cc++) {",
                  "        id++;",
                  "        for (k = -4; k <= 4; k++) for (j = -4; j <= 4; j++) for "
                  "(i = -4; i <= 4; i++)",
                  "            if (i * i + j * j + k * k <= 16)",
                  "                mk[IDX(8 + a * spacing + i, 8 + b * spacing + j, "
                  "8 + cc * spacing + k)] = id;", "    }"]
        if c.claim == "none":
            o.append("    rk = (int *)calloc(ntot, sizeof(int));")
        host = {"all": "mk[IDX(i, j, k)] != 0",
                "div": "mk[IDX(i, j, k)] != 0 && (i + j + k) % 2 == 0"}.get(
            c.branch)
        o += ["    for (i = 0; i <= M; i++) for (j = 0; j <= N; j++) for "
              "(k = 0; k <= P; k++) {"]
        if c.branch == "search":
            o += ["        int ii, jj, kk, is_gp = 0;",
                  "        if (mk[IDX(i, j, k)] != 0) {",
                  "            for (ii = i - LAYERS; ii <= i + LAYERS && !is_gp;"
                  " ii++) for (jj = j - LAYERS; jj <= j + LAYERS && !is_gp; "
                  "jj++) for (kk = k - LAYERS; kk <= k + LAYERS; kk++)",
                  "                if (mk[IDX(ii, jj, kk)] == 0) { is_gp = 1; "
                  "break; }", "        }", "        if (is_gp) {"]
        else:
            o.append(f"        if ({host}) {{")
        o.append("            num_gps++;")
        if c.claim == "none":
            o.append("            rk[IDX(i, j, k)] = num_gps;")
        o += ["        }", "    }"]
        slots = "NSPH" if self.swap else "num_gps"
        o.append(f"    int num_slots = {slots};")
        o.append("    ghost_t *g = (ghost_t *)calloc(num_slots + 1, "
                 "sizeof(ghost_t));")
        if self.swap:
            o.append("    first = (int *)calloc(NSPH + 1, sizeof(int)); "
                     "wc = (int *)calloc(NSPH + 1, sizeof(int));")
        o += ["    #pragma omp target map(from: host_flag)",
              "    host_flag = omp_is_initial_device();",
              "    printf(\"spheres %d  cells %d\\n\", id, num_gps);",
              "    int bad_max = 0, dup_max = 0, missing_max = 0;",
              "    long claimed_o = -1, sx_o = -1, sy_o = -1, sz_o = -1, "
              "sid_o = -1, count_o = -1;"]
        o.append("    for (t = 1; t <= trials; t++) {")
        o += ["        for (q = 0; q <= num_slots; q++) {",
              f"            {self.locarr('q')}[0] = -1; {self.locarr('q')}[1] = "
              f"-1; {self.locarr('q')}[2] = -1; g[q].ib_patch_id = -1;",
              "        }"]
        if self.swap:
            o.append("        memset(first, 0, (NSPH + 1) * sizeof(int)); "
                     "memset(wc, 0, (NSPH + 1) * sizeof(int));")
        # counter
        X = self.counter()
        maps = ["map(to: mk[0:ntot])", "map(tofrom: g[0:num_slots + 1])"]
        if c.claim in ("cap_uf", "cap_fu", "cap_stmt"):
            if c.cnt == "var":
                o.append("        int count = 0;")
                maps.append(f"map({c.count_map}: count)")
            elif c.cnt == "elem":
                o.append("        int cnt[2] = {0, 0};")
                maps.append(f"map({c.count_map}: cnt[0:2])")
            else:
                o.append("        counter_t cs = {0};")
                maps.append(f"map({c.count_map}: cs)")
        if c.claim == "none":
            maps.append("map(to: rk[0:ntot])")
        if self.swap:
            maps.append("map(tofrom: first[0:NSPH + 1], wc[0:NSPH + 1])")
        priv = "i, j, k, ii, jj, kk, is_gp, v, id, d, old"
        o.append(f"        #pragma omp target teams distribute parallel for "
                 f"collapse({c.collapse}) \\")
        o.append(f"            {' '.join(maps)}")
        jd = "j = 0" if c.collapse >= 2 else "int j = 0"
        kd = "k = 0" if c.collapse >= 3 else "int k = 0"
        o += ["        for (i = 0; i <= M; i++)",
              f"        for ({jd}; j <= N; j++)",
              f"        for ({kd}; k <= P; k++) {{",
              # one declarator per statement: the pre-run's race rule sees
              # only the first name of a declaration list as local
              "            int ii = 0;", "            int jj = 0;",
              "            int kk = 0;", "            int is_gp = 0;",
              "            int v = 0;", "            int d = 0;",
              "            int old = 0;", "            int id = 0;"]
        # the loop variables of a collapsed nest are the construct's; i, j, k
        # are declared outside, ii.. inside
        body = self.body()
        if c.branch == "search":
            o += ["            if (mk[IDX(i, j, k)] != 0) {",
                  "                for (ii = i - LAYERS; ii <= i + LAYERS && "
                  "!is_gp; ii++)",
                  "                    for (jj = j - LAYERS; jj <= j + LAYERS && "
                  "!is_gp; jj++)",
                  "                        for (kk = k - LAYERS; kk <= k + "
                  "LAYERS; kk++)",
                  "                            if (mk[IDX(ii, jj, kk)] == 0) { "
                  "is_gp = 1; break; }", "            }",
                  "            if (is_gp) {"]
        else:
            o.append(f"            if ({host}) {{")
        o += ["                " + s for s in body]
        o += ["            }", "        }"]
        if c.claim in ("cap_uf", "cap_fu", "cap_stmt"):
            o.append(f"        ncount = {X};")
        o += ["        int bad = 0, dup = 0, missing = 0, claimed = 0;",
              "        long sx = 0, sy = 0, sz = 0, sid = 0;",
              "        memset(hits, 0, ntot * sizeof(int));",
              f"        for (q = {'1'}; q <= num_slots; q++) {{",
              f"            long l1 = {self.locarr('q')}[0], l2 = "
              f"{self.locarr('q')}[1], l3 = {self.locarr('q')}[2];"]
        if self.swap:
            o.append("            if (l1 < 0) continue;")
        o += ["            if (l1 < 0 || l2 < 0 || l3 < 0 || l1 > M || l2 > N "
              "|| l3 > P) { bad++; continue; }",
              "            hits[IDX(l1, l2, l3)]++;", "            claimed++;",
              "            sx += l1; sy += l2; sz += l3; sid += "
              "g[q].ib_patch_id;"]
        want = "q" if self.swap else "g[q].ib_patch_id"
        o.append(f"            if (mk[IDX(l1, l2, l3)] != {want}) bad++;")
        if self.swap:
            o.append("            if (g[q].ib_patch_id != q) bad++;")
        if c.extras and c.rec == "ghost":
            o.append("            if (g[q].xp || g[q].yp || g[q].zp || "
                     "g[q].slip || g[q].DB[0] || g[q].DB[1] || g[q].DB[2]) "
                     "bad++;")
        o.append("        }")
        if self.swap:
            o += ["        for (q = 1; q <= NSPH; q++) { if (wc[q] > 1) dup++; "
                  "if (wc[q] == 0) missing++; }"]
        else:
            o += ["        { long nh = 0; for (long z = 0; z < ntot; z++) { if "
                  "(hits[z] > 1) dup++; if (hits[z] > 0) nh++; } "
                  "missing = num_gps - (int)nh; }"]
        o += ["        printf(\"trial %d: bad records %d  duplicated cells %d "
              " missing cells %d  claimed %d\\n\", t, bad, dup, missing, "
              "claimed);",
              "        if (bad > bad_max) bad_max = bad; if (dup > dup_max) "
              "dup_max = dup; if (missing > missing_max) missing_max = "
              "missing;"]
        want = self.exp
        cond = [f"claimed != {want['claimed']}"]
        if "sum_x" in want:
            cond += [f"sx != {want['sum_x']}L", f"sy != {want['sum_y']}L",
                     f"sz != {want['sum_z']}L", f"sid != {want['sum_id']}L"]
        if "count" in want:
            cond += [f"ncount != {want['count']}"]
        o += [f"        if (claimed_o < 0 || ({' || '.join(cond)})) {{",
              f"            if (claimed_o < 0 || claimed_o == "
              f"{want['claimed']}) {{ claimed_o = claimed; sx_o = sx; "
              "sy_o = sy; sz_o = sz; sid_o = sid; count_o = ncount; }",
              "        }", "    }"]
        o.append("    int ok = 1;")
        o.append(f"    ok = ok && num_gps == {want['num_gps']};")
        o.append(f"    ok = ok && claimed_o == {want['claimed']};")
        if "sum_x" in want:
            for nm, key in (("sx_o", "sum_x"), ("sy_o", "sum_y"),
                            ("sz_o", "sum_z"), ("sid_o", "sum_id")):
                o.append(f"    ok = ok && {nm} == {want[key]}L;")
        o.append("    ok = ok && bad_max == 0 && dup_max == 0 && "
                 "missing_max == 0;")
        if "count" in want:
            o.append(f"    ok = ok && count_o == {want['count']};")
        o += ["    printf(\"num_gps= %d\\n\", num_gps);",
              "    printf(\"claimed= %ld\\n\", claimed_o);"]
        if "sum_x" in want:
            for nm, key in (("sx_o", "sum_x"), ("sy_o", "sum_y"),
                            ("sz_o", "sum_z"), ("sid_o", "sum_id")):
                o.append(f"    printf(\"{key}= %ld\\n\", {nm});")
        o += ["    printf(\"bad= %d\\n\", bad_max);",
              "    printf(\"dup= %d\\n\", dup_max);",
              "    printf(\"missing= %d\\n\", missing_max);"]
        if "count" in want:
            o.append("    printf(\"count= %ld\\n\", count_o);")
        o += ["    printf(\"RESULT ran_on_host=%d check=%s\\n\", host_flag, ok ? "
              "\"pass\" : \"fail\");", "    return 0;", "}", ""]
        return "\n".join(o)
