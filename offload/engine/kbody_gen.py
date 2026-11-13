"""Kernel-body campaign: programs that vary the statements inside a kernel
 (idioms from offload/engine/idioms.py).
The base case is a ``target teams distribute parallel do collapse(3)`` that
claims record slots with ``!$omp atomic capture`` and assigns an array
constructor to a component of an element of an array of derived types
(``gps(local_idx)%loc = [i, j, k]``). ``Cfg`` is one point of the axes (slot
claim, counter location, branch, write idiom and target, component type,
storage, collapse depth, size). ``model(cfg)`` computes the qualifying cells
in Python. ``program(cfg)`` returns the source (offload.engine.kbody_emit), spec
rows (offload.engine.kbody_cites), legality model and oracle. ``neighbours(cfg)``
gives single-axis changes and ``pilot(n, seed)`` a sample. The oracle does
not depend on which thread gets which slot: the host counts ``bad``, ``dup``
and ``missing`` records and compares permutation-invariant sums with the
model. The host reference is the same binary with
``OMP_TARGET_OFFLOAD=disabled`` plus a gfortran serial build.
"""
from __future__ import annotations

import hashlib
import random
import re
from dataclasses import dataclass, replace

from offload.engine import kbody_cites as KC

RADIUS = 4                     # of the marker spheres (student's value)

F_LOC = ("ctor", "ctor_old", "ctor_expr", "reshape", "merge", "section",
         "elem", "loop", "tmp", "func", "arrexpr", "arrcopy", "rec_assign",
         "pack", "cshift", "merge_arr", "matmul", "func_elem")
# the statement shapes for which flang makes a heap temporary inside the kernel: the array constructors
# and what is built on them. The first guess also listed pack, cshift, merge_arr, matmul and func_elem; the
# detector run (tools/campaigns/devtemps.py) found those allocate nothing, so the list is
# the detector's result for this sample and only a guess for a new idiom
HEAP_GUESS = ("ctor", "ctor_old", "ctor_expr", "reshape", "merge", "section", "tmp", "func")
C_LOC = ("scalars", "memcpy_literal", "struct_literal", "loop", "tmp_struct",
         "tmp_array")
F_TGT = ("elem_comp", "col", "row", "nested")
C_TGT = ("elem_comp", "nested")
CLAIMS = ("cap_uf", "cap_fu", "cap_stmt", "none", "swap")   # cap_stmt: C only
CNTS_F = ("var", "elem", "comp", "elemcomp")
CNTS_C = ("var", "elem", "member")
BRANCHES = ("all", "div", "search")
CTYPES = ("int4", "int8", "real8")
AUXS = ("none", "real", "logical", "matrix", "grid", "db")


@dataclass(frozen=True)
class Cfg:
    lang: str = "f"              # f | c
    collapse: int = 3
    claim: str = "cap_uf"        # cap_uf | cap_fu | none | swap
    cnt: str = "var"
    count_map: str = "to"        # to | tofrom
    branch: str = "search"
    loc: str = "ctor"
    tgt: str = "elem_comp"
    ctype: str = "int4"
    aux: str = "none"
    extras: bool = True          # the student's other component writes
    rec: str = "ghost"           # ghost | small
    storage: str = "declare"     # declare | enter
    marker: str = "ptr"          # ptr | alloc
    spacing: int = 20
    nper: int = 10
    layers: int = 3
    trials: int = 3
    dims: tuple = ()             # grid (m, n, p); empty: just fits the spheres
    geom: str = "spheres"        # spheres | dense (every cell of the grid; no spheres)
    hda: bool = True             # has_device_addr(gps), the student's clause (declare storage)

    def key(self) -> str:
        return "|".join(str(v) for v in (
            self.lang, self.collapse, self.claim, self.cnt, self.count_map,
            self.branch, self.loc, self.tgt, self.ctype, self.aux,
            self.extras, self.rec, self.storage, self.marker, self.spacing,
            self.nper, self.layers, self.trials, self.dims, self.geom, self.hda))

    @property
    def uid(self) -> str:
        return hashlib.sha256(self.key().encode()).hexdigest()[:8]


def student_cfg() -> Cfg:
    """results/student-repro/orig.f90: the reproducer as a program of the
    campaign (grid and spheres as `orig.x 20 10 3`; the oracle resets the
    records before every trial, which the original does not)."""
    return Cfg(dims=(439, 329, 329))


def check_cfg(cfg: Cfg):
    f = cfg.lang == "f"
    bad = []
    if cfg.collapse not in (1, 2, 3):
        bad.append("collapse")
    if cfg.claim not in CLAIMS:
        bad.append("claim")
    if cfg.loc not in (F_LOC if f else C_LOC):
        bad.append("loc")
    if cfg.tgt not in (F_TGT if f else C_TGT):
        bad.append("tgt")
    if cfg.cnt not in (CNTS_F if f else CNTS_C):
        bad.append("cnt")
    if cfg.branch not in BRANCHES:
        bad.append("branch")
    if cfg.ctype not in CTYPES or (not f and cfg.ctype == "real8"):
        bad.append("ctype")
    if cfg.aux not in AUXS or (not f and cfg.aux != "none"):
        bad.append("aux")
    if cfg.aux != "none" and cfg.rec != "ghost":
        bad.append("aux needs the ghost record")
    if cfg.geom == "spheres" and cfg.spacing < 2 * (RADIUS + cfg.layers) + 1:
        bad.append("spheres overlap")
    if cfg.count_map not in ("to", "tofrom"):
        bad.append("count_map")
    if cfg.storage not in ("declare", "enter") or \
            cfg.marker not in ("ptr", "alloc") or \
            cfg.rec not in ("ghost", "small"):
        bad.append("storage/marker/rec")
    if not f and (cfg.storage != "declare" or cfg.marker != "alloc"):
        bad.append("C has one storage and a plain marker array")
    if cfg.claim == "cap_stmt" and f:
        bad.append("cap_stmt is the C statement form")
    if cfg.loc in ("struct_literal", "tmp_struct") and cfg.tgt != "nested":
        bad.append("a struct literal needs the nested target")
    if cfg.marker == "ptr" and cfg.storage != "declare":
        bad.append("the pointer-component marker array is declared target")
    if cfg.hda and cfg.storage != "declare":
        bad.append("has_device_addr is for the declare target storage")
    if cfg.geom == "dense":
        if not cfg.dims or cfg.branch == "search" or cfg.claim == "swap":
            bad.append("dense needs dims, branch all|div, no swap")
    elif cfg.geom != "spheres":
        bad.append("geom")
    elif cfg.dims and min(cfg.dims) < 16 + (cfg.nper - 1) * cfg.spacing:
        bad.append("dims too small for the spheres")
    if cfg.loc == "rec_assign" and (cfg.tgt != "elem_comp" or cfg.extras
                                    or cfg.aux != "none" or cfg.claim == "swap"):
        bad.append("rec_assign: whole-record copy, elem_comp target, no "
                   "extras or aux")
    if cfg.loc == "rec_assign" and not f:
        bad.append("rec_assign")
    if bad:
        raise ValueError("bad config: " + ", ".join(bad))


# --- the model (Python; never a compiler) --------------------------------------------------

def sphere_offsets(r: int = RADIUS) -> list[tuple]:
    return [(i, j, k) for k in range(-r, r + 1) for j in range(-r, r + 1)
            for i in range(-r, r + 1) if i * i + j * j + k * k <= r * r]


def grid_size(cfg: Cfg) -> int:
    return 16 + (cfg.nper - 1) * cfg.spacing


def centres(cfg: Cfg) -> list[tuple]:
    """(x, y, z, id) of the spheres, in the student's loop order."""
    out, ident = [], 0
    s = cfg.spacing
    for a in range(cfg.nper):
        for b in range(cfg.nper):
            for c in range(cfg.nper):
                ident += 1
                out.append((8 + a * s, 8 + b * s, 8 + c * s, ident))
    return out


def qualifying_offsets(cfg: Cfg) -> list[tuple]:
    """The offsets of a sphere whose cell the kernel claims (the spheres
    are isolated: spacing > 2 (radius + layers))."""
    inside = set(sphere_offsets())
    out = []
    for d in sorted(inside, key=lambda t: (t[2], t[1], t[0])):
        i, j, k = d
        if cfg.branch == "all":
            ok = True
        elif cfg.branch == "div":
            ok = (i + j + k) % 2 == 0          # every centre has even parity
        else:
            L = cfg.layers
            ok = any((i + a, j + b, k + c) not in inside
                     for a in range(-L, L + 1) for b in range(-L, L + 1)
                     for c in range(-L, L + 1))
        if ok:
            out.append(d)
    return out


def _dense_model(cfg: Cfg) -> dict:
    """Every cell of the grid (branch all) or every cell with even i+j+k
    (branch div); the marker id of a cell is mod(i+j+k, 7) + 1."""
    m, n, p = cfg.dims
    even = cfg.branch == "div"
    cnt = sx = sy = sz = sid = 0
    # by residues mod 14 (parity and mod 7 are both functions of them)
    def res(size):
        r = [0] * 14
        s1 = [0] * 14
        for v in range(size + 1):
            r[v % 14] += 1
            s1[v % 14] += v
        return r, s1
    (rx, sxr), (ry, syr), (rz, szr) = res(m), res(n), res(p)
    for a in range(14):
        for b in range(14):
            for c in range(14):
                t = a + b + c
                if even and t % 2:
                    continue
                k = rx[a] * ry[b] * rz[c]
                cnt += k
                sx += sxr[a] * ry[b] * rz[c]
                sy += rx[a] * syr[b] * rz[c]
                sz += rx[a] * ry[b] * szr[c]
                sid += k * (t % 7 + 1)
    e = {"num_gps": cnt, "claimed": cnt, "sum_x": sx, "sum_y": sy,
         "sum_z": sz, "sum_id": sid, "bad": 0, "dup": 0, "missing": 0}
    if cfg.claim in ("cap_uf", "cap_fu", "cap_stmt") and \
            cfg.count_map == "tofrom":
        e["count"] = cnt
    return e


def model(cfg: Cfg) -> dict:
    """The expected observables: ``num_gps`` qualifying cells (the host's
    own count), ``claimed`` records with a valid cell, the sums of the
    location components and of the marker ids over them (``swap``: one
    record per sphere, no sums), zero ``bad``/``dup``/``missing``, and, when
    the counter is copied back, ``count``."""
    if cfg.geom == "dense":
        return _dense_model(cfg)
    offs = qualifying_offsets(cfg)
    cs = centres(cfg)
    n = len(offs) * len(cs)
    if cfg.claim == "swap":
        nsph = len(cs)
        return {"num_gps": n, "claimed": nsph, "bad": 0, "dup": 0,
                "missing": 0}
    sx = sum(x for x, _, _, _ in cs) * len(offs) + len(cs) * sum(
        d[0] for d in offs)
    sy = sum(y for _, y, _, _ in cs) * len(offs) + len(cs) * sum(
        d[1] for d in offs)
    sz = sum(z for _, _, z, _ in cs) * len(offs) + len(cs) * sum(
        d[2] for d in offs)
    sid = sum(i for _, _, _, i in cs) * len(offs)
    e = {"num_gps": n, "claimed": n, "sum_x": sx, "sum_y": sy, "sum_z": sz,
         "sum_id": sid, "bad": 0, "dup": 0, "missing": 0}
    if cfg.claim in ("cap_uf", "cap_fu", "cap_stmt") and \
            cfg.count_map == "tofrom":
        e["count"] = n
    return e


# --- the legality model ----------------------------------------------------------------------

@dataclass
class Verdict:
    status: str                      # defined | unspecified
    reasons: list                    # (tag, text)


def validate(cfg: Cfg) -> Verdict:
    check_cfg(cfg)
    reasons = []
    if cfg.hda:
        reasons.append(("omp.has-device-addr",
                        "has_device_addr(gps) says the host address of the "
                        "declare target variable is a device address of the "
                        "executing device: true where the device addresses "
                        "host memory (MI300A with HSA_XNACK=1), unspecified "
                        "on a device with separate memory"))
    if cfg.claim == "swap":
        reasons.append(("omp.atomic.write-capture",
                        "the write-capture form (v = x; x = e) is a "
                        "write-capture-atomic block in 4.3.1.3, but the "
                        "restriction of 15.8.4 asks for an "
                        "update-capture-atomic block with a plain capture "
                        "clause: the 5.2 text does not settle it (5.0 added "
                        "atomic swap)"))
        return Verdict("unspecified", reasons)
    if cfg.hda:
        return Verdict("unspecified", reasons)
    return Verdict("defined", reasons)


def rules_of(cfg: Cfg, verdict: Verdict) -> tuple:
    tags = ["omp.collapse"]
    tags += ["omp.atomic.scalar-variables"]
    if cfg.claim in ("cap_uf", "cap_fu", "cap_stmt"):
        tags += ["omp.atomic.capture-forms", "omp.atomic.captured-update",
                 "omp.atomic.exclusive-across-teams",
                 "omp.atomic.capture-update-only",
                 "omp.atomic.update-forms", "omp.atomic.no-alias",
                 "omp.atomic.protect-all"]
        if cfg.lang == "f":
            tags += ["omp.atomic.not-allocatable"]
    if cfg.claim == "swap":
        tags += ["omp.atomic.capture-forms", "omp.atomic.write-capture",
                 "omp.atomic.exclusive-across-teams",
                 "omp.atomic.capture-update-only", "omp.atomic.update-forms"]
    for t, _ in verdict.reasons:
        if t not in tags:
            tags.append(t)
    seen, out = set(), []
    for t in tags:
        if t in KC.CITES and t not in seen:
            seen.add(t)
            out.append(t)
    return tuple(out)


# --- atomic structured blocks, checked on the emitted source ------------------------------------
# an independent lexical reading (not the generator's templates) of every
# atomic construct against 4.3.1.3

_F_ATOMIC = re.compile(r"^\s*!\$omp\s+atomic\b(.*)$", re.I)
_F_ENDATOMIC = re.compile(r"^\s*!\$omp\s+end\s+atomic\b", re.I)
_UPDATE_INTR = ("max", "min", "iand", "ior", "ieor")


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s.lower())


def _f_update_ok(stmt: str):
    """(ok, x) for a Fortran update-statement x = x op e | e op x |
    intrinsic(x, e) | intrinsic(e, x)."""
    m = re.match(r"^\s*(.+?)\s*=\s*(.+)$", stmt)
    if not m:
        return False, None
    x, rhs = _norm(m.group(1)), _norm(m.group(2))
    if rhs.startswith(x) and len(rhs) > len(x) and rhs[len(x)] in "+-*/":
        e = rhs[len(x) + 1:]
        return x not in e, x
    if rhs.endswith(x) and len(rhs) > len(x) and rhs[-len(x) - 1] in "+-*/":
        e = rhs[:-len(x) - 1]
        return x not in e, x
    m2 = re.match(r"^(max|min|iand|ior|ieor)\((.*)\)$", rhs)
    if m2:
        args = _split_args(m2.group(2))
        if len(args) >= 2 and (args[0] == x) != (args[-1] == x):
            others = args[1:] if args[0] == x else args[:-1]
            return not any(x in o for o in others), x
    return False, x


def _split_args(s: str) -> list[str]:
    out, buf, depth = [], [], 0
    for ch in s:
        depth += ch in "(["
        depth -= ch in ")]"
        if ch == "," and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf))
    return out


def atomic_problems(source: str, lang: str = "f") -> list[str]:
    """Every OpenMP atomic construct of the source against the atomic
    structured-block forms of OpenMP 5.2 4.3.1.3 (Fortran), as a list of
    problems (empty: all of them fit)."""
    probs = []
    if lang != "f":
        return _c_atomic_problems(source)
    lines = source.split("\n")
    i = 0
    while i < len(lines):
        m = _F_ATOMIC.match(lines[i])
        if not m:
            i += 1
            continue
        ln = i + 1
        clause = [w for w in re.findall(r"[a-z]+", m.group(1).lower())
                  if w in ("read", "write", "update", "capture", "compare")]
        form = clause[0] if clause else "update"
        i += 1
        if form == "capture":
            body = []
            while i < len(lines) and not _F_ENDATOMIC.match(lines[i]):
                if lines[i].strip():
                    body.append(lines[i].strip())
                i += 1
            i += 1
            if len(body) != 2:
                probs.append(f"line {ln}: a capture block has "
                             f"{len(body)} statements, not 2")
                continue
            cap = [b for b in body if re.match(r"^[\w%()]+\s*=\s*[\w%()]+$",
                                               b)]
            a, b = body
            ok1, x1 = _f_update_ok(a)
            ok2, x2 = _f_update_ok(b)
            ma = re.match(r"^\s*(.+?)\s*=\s*(.+)$", a)
            mb = re.match(r"^\s*(.+?)\s*=\s*(.+)$", b)
            if ok1 and mb and _norm(mb.group(2)) == x1 and \
                    _norm(mb.group(1)) != x1 and \
                    _norm(mb.group(1)) not in _norm(a.split("=", 1)[1]):
                pass                                 # update; v = x
            elif ok2 and ma and _norm(ma.group(2)) == x2 and \
                    _norm(ma.group(1)) != x2 and \
                    _norm(ma.group(1)) not in _norm(b.split("=", 1)[1]):
                pass                                 # v = x; update
            elif ma and mb and _norm(ma.group(2)) == _norm(mb.group(1)) \
                    and _norm(mb.group(1)) != _norm(ma.group(1)) and \
                    _norm(ma.group(1)) not in _norm(mb.group(2)):
                pass                                 # v = x; x = e (write)
            else:
                probs.append(f"line {ln}: not a capture block form: "
                             f"{a!r} / {b!r}")
        else:
            while i < len(lines) and not lines[i].strip():
                i += 1
            stmt = lines[i].strip() if i < len(lines) else ""
            i += 1
            if form == "update":
                ok, _ = _f_update_ok(stmt)
                if not ok:
                    probs.append(f"line {ln}: not an update statement: "
                                 f"{stmt!r}")
            elif form == "read":
                if not re.match(r"^[\w%()]+\s*=\s*[\w%()]+$", stmt):
                    probs.append(f"line {ln}: not a read statement: "
                                 f"{stmt!r}")
            elif form == "write":
                if not re.match(r"^[\w%()]+\s*=\s*.+$", stmt):
                    probs.append(f"line {ln}: not a write statement: "
                                 f"{stmt!r}")
    return probs


_LV = r"[\w\[\]\.>-]+"


def _c_stmt(stmt: str):
    """(lhs, rhs, kind): kind is assign (x = e), update (x op= e, x++, ..)."""
    stmt = stmt.strip().rstrip(";").strip()
    m = re.match(r"^(" + _LV + r")\s*([-+*/&|^]|<<|>>)=\s*(.+)$", stmt)
    if m:
        return m.group(1), m.group(3), "update"
    m = re.match(r"^(\+\+|--)\s*(" + _LV + r")$", stmt)
    if m:
        return m.group(2), None, "update"
    m = re.match(r"^(" + _LV + r")\s*(\+\+|--)$", stmt)
    if m:
        return m.group(1), None, "update"
    m = re.match(r"^(" + _LV + r")\s*=\s*(.+)$", stmt)
    if m:
        lhs, rhs = m.group(1), m.group(2)
        m2 = re.match(r"^" + re.escape(lhs) + r"\s*[-+*/&|^]\s*(.+)$", rhs)
        if m2 and lhs not in m2.group(1):
            return lhs, m2.group(1), "update"
        return lhs, rhs, "assign"
    return None


def _c_capture_ok(stmts: list[str]) -> bool:
    if len(stmts) == 1:                      # v = x++ ; v = x op= e ...
        m = re.match(r"^(" + _LV + r")\s*=\s*(.+);?$", stmts[0].strip())
        if not m:
            return False
        v, e = m.group(1), m.group(2).rstrip(";")
        inner = _c_stmt(e)
        return inner is not None and inner[2] == "update" and \
            inner[0] != v
    if len(stmts) != 2:
        return False
    a, b = _c_stmt(stmts[0]), _c_stmt(stmts[1])
    if not a or not b:
        return False
    # v = x; x <update or write>
    if a[2] == "assign" and a[1] is not None and re.fullmatch(_LV, a[1]) \
            and b[0] == a[1] and a[0] != b[0] and (b[1] is None or
                                                    a[0] not in b[1]):
        return True
    # x <update>; v = x
    if a[2] == "update" and b[2] == "assign" and b[1] == a[0] and \
            b[0] != a[0] and (a[1] is None or b[0] not in a[1]):
        return True
    return False


def _c_atomic_problems(source: str) -> list[str]:
    probs = []
    lines = source.split("\n")
    for ln, line in enumerate(lines, 1):
        m = re.match(r"^\s*#\s*pragma\s+omp\s+atomic\b(.*)$", line)
        if not m:
            continue
        form = "update"
        for w in re.findall(r"[a-z]+", m.group(1)):
            if w in ("read", "write", "update", "capture"):
                form = w
        nxt = lines[ln].strip() if ln < len(lines) else ""
        if form == "capture":
            if nxt.startswith("{"):
                inner = nxt
                k = ln
                while "}" not in inner and k + 1 < len(lines):
                    k += 1
                    inner += " " + lines[k].strip()
                stm = [x.strip() for x in inner.strip("{} ").split(";")
                       if x.strip()]
                if not _c_capture_ok(stm):
                    probs.append(f"line {ln}: not a capture block form: "
                                 f"{stm!r}")
            elif not _c_capture_ok([nxt]):
                probs.append(f"line {ln}: not a capture statement: {nxt!r}")
        elif form == "update":
            st = _c_stmt(nxt)
            if not st or st[2] != "update":
                probs.append(f"line {ln}: not an update statement: {nxt!r}")
    return probs


# --- programs ----------------------------------------------------------------------------------

@dataclass(frozen=True)
class Program:
    id: str
    family: str
    title: str
    lang: str                  # "c" | "f90"
    model: str                 # "omp"
    version: int               # 52
    source: str
    expected: dict
    legality: str              # defined | unspecified
    why: str
    rules: tuple
    cites: tuple
    axes: dict
    cfg: Cfg = None
    modes: tuple = ("copy", "unified")

    @property
    def text(self) -> str:
        return self.source

    def harness(self):
        from offload.engine.gen import Program as HP
        return HP(id=self.id, lang=self.lang, source=self.source,
                  atoms=frozenset({f"kbody.{self.family}"}),
                  primary_atom=f"kbody.{self.family}",
                  legal=self.legality == "defined", violates=None,
                  observable=True, model=self.model)


def axes_of(cfg: Cfg) -> dict:
    return {"lang": cfg.lang, "collapse": cfg.collapse, "claim": cfg.claim,
            "cnt": cfg.cnt, "count_map": cfg.count_map,
            "branch": cfg.branch, "loc": cfg.loc, "tgt": cfg.tgt,
            "ctype": cfg.ctype, "aux": cfg.aux, "extras": cfg.extras,
            "rec": cfg.rec, "storage": cfg.storage, "marker": cfg.marker,
            "hda": cfg.hda,
            "geom": cfg.geom,
            "heap_guess": cfg.loc in HEAP_GUESS and cfg.lang == "f",
            "size": (f"dense grid {'x'.join(map(str, cfg.dims))}"
                     if cfg.geom == "dense" else
                     f"{cfg.nper}^3 spheres, spacing {cfg.spacing}")}


def title_of(cfg: Cfg) -> str:
    lang = {"f": "Fortran", "c": "C"}[cfg.lang]
    return (f"{lang} OpenMP: collapse({cfg.collapse}) kernel, slot claim "
            f"{cfg.claim} on counter {cfg.cnt}, branch {cfg.branch}, write "
            f"{cfg.loc} into {cfg.tgt} ({cfg.ctype}), {cfg.rec} record")


def parse_observed(stdout: str) -> dict:
    return {m.group(1): int(m.group(2)) for m in
            re.finditer(r"^(\w+)= (-?\d+)\s*$", stdout or "", re.M)}


def program(cfg: Cfg) -> Program:
    from offload.engine import kbody_emit as E
    verdict = validate(cfg)
    expected = model(cfg)
    tags = rules_of(cfg, verdict)
    rows = KC.rows_for(tags)
    src_obj = E.emit(cfg, expected, tags, verdict)
    src = src_obj
    long = [ln for ln in src.split("\n") if len(ln) > 132 and cfg.lang == "f"]
    if long:
        raise ValueError(f"line over 132 characters: {long[0][:60]}")
    pid = f"kb-{cfg.lang}-{cfg.claim}-c{cfg.collapse}-{cfg.loc}-{cfg.uid}"
    return Program(
        id=pid, family=f"{cfg.lang}-{cfg.claim}", title=title_of(cfg),
        lang="c" if cfg.lang == "c" else "f90", model="omp", version=52,
        source=src, expected=dict(expected), legality=verdict.status,
        why="; ".join(m for _, m in verdict.reasons), rules=tags,
        cites=tuple(tuple(sorted(r.items())) for r in rows),
        axes=axes_of(cfg), cfg=cfg)


# --- neighbourhood mutation --------------------------------------------------------------------

PAIRS = (dict(branch="div", loc="elem"), dict(branch="all", loc="section"),
         dict(cnt="elem", loc="reshape"), dict(collapse=1, loc="merge"),
         dict(claim="cap_fu", loc="tmp"), dict(tgt="col", loc="section"),
         dict(tgt="row", loc="ctor"), dict(tgt="nested", loc="section"),
         dict(ctype="real8", loc="ctor_expr"), dict(ctype="int8", loc="reshape"),
         dict(ctype="real8", loc="merge"), dict(storage="enter", marker="alloc"),
         dict(rec="small", tgt="nested"), dict(claim="none", branch="div"),
         dict(cnt="comp", claim="cap_fu"), dict(cnt="elemcomp", branch="div"),
         dict(count_map="tofrom", cnt="elem"), dict(extras=False, loc="ctor_old"),
         dict(rec="small", loc="elem"), dict(collapse=2, loc="tmp"),
         dict(collapse=1, claim="cap_fu"), dict(branch="all", cnt="comp"),
         dict(branch="div", collapse=1), dict(loc="func", tgt="col"),
         dict(loc="loop", branch="div"), dict(aux="real", loc="elem"),
         dict(aux="logical", loc="merge"), dict(aux="matrix", loc="ctor_old"),
         dict(storage="enter", marker="alloc", claim="none"),
         dict(spacing=16, nper=8), dict(spacing=24, nper=8),
         dict(spacing=20, nper=6), dict(spacing=16, nper=6, branch="all"))


def neighbours(cfg: Cfg, include_pairs: bool = False) -> list[tuple]:
    """[(axis, value, Cfg)]: the programs that differ from `cfg` in one
    idiom. `include_pairs` adds a few two-axis changes (the divergent
    branch with the elementwise write, the section target with a scalar
    counter ...) that are the likeliest places to keep a failure."""
    f = cfg.lang == "f"
    alts = {
        "collapse": (1, 2, 3),
        "claim": CLAIMS,
        "cnt": CNTS_F if f else CNTS_C,
        "count_map": ("to", "tofrom"),
        "branch": BRANCHES,
        "loc": F_LOC if f else C_LOC,
        "tgt": F_TGT if f else C_TGT,
        "ctype": CTYPES if f else ("int4", "int8"),
        "aux": AUXS if f else ("none",),
        "extras": (True, False),
        "rec": ("ghost", "small"),
        "storage": ("declare", "enter") if f else ("declare",),
        "hda": (True, False) if f else (False,),
        "marker": ("ptr", "alloc") if f else ("alloc",),
        "layers": (1, 2, 3),
        "nper": (6, 8, 10),
    }
    if cfg.geom == "dense":
        alts.pop("nper")
        alts.pop("layers")
        alts["dims"] = ((63, 63, 63), (95, 95, 95), (255, 255, 255))
        alts["trials"] = (6, 40)
    out, seen = [], {cfg.key()}
    for axis, vals in alts.items():
        for v in vals:
            if getattr(cfg, axis) == v:
                continue
            try:
                c = replace(cfg, **{axis: v})
                if axis == "rec" and v == "small" and cfg.aux != "none":
                    c = replace(c, aux="none")
                if axis == "aux" and v != "none" and cfg.rec != "ghost":
                    continue
                check_cfg(c)
            except ValueError:
                continue
            if c.key() not in seen:
                seen.add(c.key())
                out.append((axis, v, c))
    if include_pairs:
        for pair in PAIRS:
            if cfg.geom == "dense" and ({"spacing", "nper"} & set(pair)):
                continue
            try:
                c = replace(cfg, **pair)
                check_cfg(c)
            except ValueError:
                continue
            if c.key() not in seen:
                seen.add(c.key())
                out.append(("+".join(pair), "+".join(map(str, pair.values())),
                            c))
    return out


# --- the sample ----------------------------------------------------------------------------------

W_F = {
    "claim": (("cap_uf", 40), ("cap_fu", 25), ("none", 22), ("swap", 13)),
    "cnt": (("var", 55), ("elem", 15), ("comp", 15), ("elemcomp", 15)),
    "branch": (("search", 34), ("div", 33), ("all", 33)),
    "loc": (("ctor", 30), ("ctor_old", 6), ("ctor_expr", 8), ("reshape", 8),
            ("merge", 8), ("section", 8), ("elem", 8), ("loop", 6),
            ("tmp", 10), ("func", 8), ("arrexpr", 6), ("arrcopy", 6),
            ("rec_assign", 6)),
    "tgt": (("elem_comp", 55), ("col", 15), ("row", 15), ("nested", 15)),
    "ctype": (("int4", 60), ("int8", 20), ("real8", 20)),
    "aux": (("none", 50), ("real", 12), ("logical", 12), ("matrix", 12),
            ("grid", 14)),
    "rec": (("ghost", 60), ("small", 40)),
    "storage": (("declare", 65), ("enter", 35)),
    "marker": (("ptr", 65), ("alloc", 35)),
    "collapse": ((3, 55), (2, 20), (1, 25)),
    "count_map": (("to", 70), ("tofrom", 30)),
    "layers": ((3, 60), (2, 20), (1, 20)),
}
W_C = {
    "claim": (("cap_uf", 30), ("cap_fu", 25), ("cap_stmt", 15), ("none", 20),
              ("swap", 10)),
    "cnt": (("var", 50), ("elem", 25), ("member", 25)),
    "branch": (("search", 34), ("div", 33), ("all", 33)),
    "loc": (("scalars", 20), ("memcpy_literal", 20), ("struct_literal", 20),
            ("loop", 10), ("tmp_struct", 15), ("tmp_array", 15)),
    "tgt": (("elem_comp", 60), ("nested", 40)),
    "ctype": (("int4", 75), ("int8", 25)),
    "aux": (("none", 100),),
    "rec": (("ghost", 50), ("small", 50)),
    "storage": (("declare", 100),),
    "marker": (("alloc", 100),),
    "collapse": ((3, 50), (2, 25), (1, 25)),
    "count_map": (("to", 60), ("tofrom", 40)),
    "layers": ((3, 60), (2, 20), (1, 20)),
}
SIZES = ((16, 6), (20, 6), (20, 10), (24, 8), (16, 8))   # (spacing, nper)


PILOT_LOCS = tuple(k for k in F_LOC if k not in (
    "pack", "cshift", "merge_arr", "matmul", "func_elem"))   # the heap sample has them


def heap_cfgs(dims=(159, 159, 159), trials=20) -> list:
    """The device-heap-temporary sample: every write idiom of the Fortran
    generator (the statement shapes that make flang allocate a temporary in
    the kernel, and the stack/element-wise controls), each in four contexts:
    a slot claimed by atomic capture or a precomputed slot, with the
    declare-target storage (no has_device_addr) or the enter-data storage."""
    out = []
    for loc in F_LOC:
        for claim in ("cap_uf", "none"):
            for storage, marker in (("declare", "ptr"), ("enter", "alloc")):
                kw = dict(geom="dense", dims=dims, branch="all", claim=claim,
                          loc=loc, rec="small", extras=False, hda=False,
                          trials=trials, storage=storage, marker=marker)
                if loc == "rec_assign":
                    kw["rec"] = "small"
                out.append(replace(Cfg(), **kw))
    return out


def _pick(rng, table):
    vals, ws = zip(*table)
    return rng.choices(vals, ws)[0]


def random_cfg(rng: random.Random, lang: str) -> Cfg:
    W = W_F if lang == "f" else W_C
    kw = {k: _pick(rng, t) for k, t in W.items()}
    kw["lang"] = lang
    kw["extras"] = rng.random() < 0.5
    kw["hda"] = lang == "f" and kw["storage"] == "declare" and \
        rng.random() < 0.3
    kw["spacing"], kw["nper"] = rng.choice(SIZES)
    kw["trials"] = 3
    if kw["rec"] == "small":
        kw["aux"] = "none"
    if kw["claim"] == "swap":
        kw["count_map"] = "to"
    return replace(Cfg(), **kw)


def pilot(n: int = 360, seed: int = 1, c_frac: float = 0.22) -> list[Program]:
    """The sample: program 0 is the student's; the rest are drawn
    deterministically from (seed, index); duplicates are skipped."""
    out, seen = [], set()

    def add(cfg):
        if cfg.key() in seen:
            return False
        seen.add(cfg.key())
        out.append(program(cfg))
        return True
    add(student_cfg())
    idx = 0
    limit = 400 * n + 1000        # draws: far more than the distinct valid programs that exist ever need
    while len(out) < n:
        if idx >= limit:
            raise ValueError(f"only {len(out)} distinct valid programs of the {n} asked for in {idx} draws "
                             f"(seed {seed}): n is larger than the configurations that exist, or check_cfg rejects them")
        rng = random.Random(f"kbody:{seed}:{idx}")
        idx += 1
        lang = "c" if rng.random() < c_frac else "f"
        try:
            cfg = random_cfg(rng, lang)
            check_cfg(cfg)
        except ValueError:
            continue
        add(cfg)
    return out
