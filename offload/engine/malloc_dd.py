"""Delta debugging of the first-use device-malloc failure of AFAR at HSA_XNACK=1 on MI300A
 (results/student-repro/malloc/ghost3.c).

``source(flags)`` writes a C program of the ghost-point kernel with one ingredient per flag, so that each
can be removed on its own: the search loop, the sphere lattice, ``collapse(3)``, the atomic capture, the
other field stores, the size of the record, the ``memcpy``, the mapped arrays, the problem size. The
program takes ``trials`` and ``warm`` (a kernel of ``warm`` mallocs before the real kernel; 0: none) and
prints, per trial, ``trial T: bad B dup D missing M``; a launch fails when any trial has bad records.
``removals(flags)`` lists the one-ingredient changes, in the order the greedy reduction tries them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Flags:
    loop: str = "collapse3"        # collapse3 | flat
    marker: str = "lattice"        # lattice (the student's spheres) | simple (checker blocks) | none (every cell, sf unread)
    search: bool = True            # the neighbour search with an exit
    slot: str = "atomic"           # atomic (capture on a mapped host counter) | precomputed
    extra: bool = True             # the other field stores (ib_patch_id, DB, periodicity)
    gp: str = "full"               # full (the student's 20 fields) | loc (just int loc[3])
    store: str = "memcpy"          # memcpy | stores3 (three stores from the malloc'd block) | direct | stack
    alloc: str = "map"             # map (enter data) | devptr | devptr-gps (sf mapped) | devptr-sf (gps mapped)
    dim: int = 439                 # cells per side (the student's 439 x 329 x 329 when 439)
    warm: int = 0                  # a kernel of this many mallocs before the real one (the default of argv[2])
    fence: str = ""                # "" | device (a device-scope release fence before free) | flush (omp flush before free)

    def dims(self):
        return (439, 329, 329) if self.dim == 439 else (self.dim,) * 3


STUDENT = Flags()

FENCE = {"": [], "device": ["  __scoped_atomic_thread_fence(__ATOMIC_RELEASE, __MEMORY_SCOPE_DEVICE);"],
         "flush": ["#pragma omp flush"]}

REMOVALS = (("search", False), ("marker", "simple"), ("loop", "flat"), ("slot", "precomputed"),
            ("extra", False), ("gp", "loc"), ("store", "stores3"), ("alloc", "devptr"))
SIZES = (255, 191, 127, 95, 63)
STAGE2 = (("marker", "none"), ("alloc", "devptr-gps"), ("alloc", "devptr-sf"))
SIZES2 = (359, 319, 287)


def minimal() -> Flags:
    """The reduction of stage 1 (results/malloc-dd/result.json)."""
    return Flags(loop="flat", marker="simple", search=False, slot="precomputed", extra=False, gp="loc",
                 store="memcpy", alloc="map", dim=439)


def removals(f: Flags):
    out = [(k, v, replace(f, **{k: v})) for k, v in REMOVALS if getattr(f, k) != v]
    return out


def source(f: Flags) -> str:
    M, N, P = f.dims()
    o = ["#include <stdio.h>", "#include <stdlib.h>", "#include <string.h>", "#include <omp.h>",
         f"#define M {M}", f"#define N {N}", f"#define P {P}", "#define B 10", "#define L 3",
         "#define NJ (N + 1 + 2 * B)", "#define NK (P + 1 + 2 * B)",
         "#define IX(i, j, k) ((((long)((i) + B)) * NJ + ((j) + B)) * NK + ((k) + B))"]
    if f.gp == "full":
        o += ["typedef struct { int loc[3]; double ip_loc[3]; int ip_grid[3]; double ic[8]; int iv, ib;",
              "  double ls, ln[3]; int slip; int DB[3]; int xp, yp, zp; } gp_t;"]
    else:
        o += ["typedef struct { int loc[3]; int ib; } gp_t;"]
    search = ("int g = 0;", "for (int a = i - L; a <= i + L && !g; a++) for (int b = j - L; b <= j + L && !g; b++)",
              "  for (int c = k - L; c <= k + L; c++) if (!sf[IX(a, b, c)]) { g = 1; break; }")
    pred = "(sf[IX(i, j, k)] != 0 && g)" if f.search else "(sf[IX(i, j, k)] != 0)"
    o += ["int main(int argc, char **argv) {",
          f"  int trials = argc > 1 ? atoi(argv[1]) : 2; long warm = argc > 2 ? atol(argv[2]) : {f.warm}L; int dev = omp_get_default_device();",
          "  size_t tot = (size_t)(M + 1 + 2 * B) * NJ * NK; int *sf = calloc(tot, sizeof(int)); long nc = (long)(M + 1) * (N + 1) * (P + 1);"]
    if f.marker == "lattice":
        o += ["  int id = 0;  /* the student's lattice: spheres of radius 4, spacing 10, 50 per side */",
              "  for (int a = 0; a < 50; a++) for (int b = 0; b < 50; b++) for (int c = 0; c < 50; c++) {",
              "    if (8 + a * 10 > M - 8 || 8 + b * 10 > N - 8 || 8 + c * 10 > P - 8) continue;",
              "    id++;",
              "    for (int k = -4; k <= 4; k++) for (int j = -4; j <= 4; j++) for (int i = -4; i <= 4; i++)",
              "      if (i * i + j * j + k * k <= 16) sf[IX(8 + a * 10 + i, 8 + b * 10 + j, 8 + c * 10 + k)] = id;",
              "  }"]
    elif f.marker == "simple":
        o += ["  for (int i = 0; i <= M; i++) for (int j = 0; j <= N; j++) for (int k = 0; k <= P; k++)",
              "    sf[IX(i, j, k)] = ((i / 8 + j / 8 + k / 8) % 2 == 0) ? 1 + (i / 8) % 7 : 0;"]
    nomark = f.marker == "none"
    host = ["  long ng = nc;"] if nomark else [
        "  long ng = 0;", "  for (int i = 0; i <= M; i++) for (int j = 0; j <= N; j++) for (int k = 0; k <= P; k++) {",
        "    if (!sf[IX(i, j, k)]) continue;"]
    if f.search and not nomark:
        host += ["    " + search[0], "    " + search[1], "    " + search[2]]
    if not nomark:
        host += [f"    ng += {'g' if f.search else '1'};", "  }"]
    o += host
    nrec = "nc" if f.slot == "precomputed" else "ng"
    o += [f"  long nrec = {nrec}; gp_t *gps = calloc(nrec, sizeof(gp_t));"]
    sfmap = f.alloc in ("map", "devptr-gps")
    gpmap = f.alloc in ("map", "devptr-sf")
    maps, dps = [], []
    if sfmap:
        o += ["  int *sfp = sf;"]
        maps.append("map(to : sf[0 : tot])")
    else:
        o += ["  int *sfp = omp_target_alloc(tot * sizeof(int), dev);",
              "  omp_target_memcpy(sfp, sf, tot * sizeof(int), 0, 0, dev, omp_get_initial_device());"]
        dps.append("sfp")
    if gpmap:
        o += ["  gp_t *gpp = gps;"]
        maps.append("map(alloc : gps[0 : nrec])")
    else:
        o += ["  gp_t *gpp = omp_target_alloc(nrec * sizeof(gp_t), dev);"]
        dps.append("gpp")
    if maps:
        o += ["#pragma omp target enter data " + " ".join(maps)]
    isdp = f" is_device_ptr({', '.join(dps)})" if dps else ""
    o += ["  int host = 1; long tbad = 0;",
          "#pragma omp target map(from : host)",
          "  host = omp_is_initial_device();",
          "  printf(\"cells %ld ghost %ld\\n\", nc, ng);",
          "  if (warm > 0) { long wb = 0;",
          "#pragma omp target teams distribute parallel for reduction(+ : wb)",
          "    for (long w = 0; w < warm; w++) { int *p = (int *)malloc(3 * sizeof(int)); if (!p) { wb++; continue; }",
          "      p[0] = (int)w; if (p[0] != (int)w) wb++; free(p); }",
          "    printf(\"warm-up: bad %ld\\n\", wb); }",
          "  for (int t = 1; t <= trials; t++) {",
          "    int count = 0;"]
    clause = "collapse(3) " if f.loop == "collapse3" else ""
    o += [f"#pragma omp target teams distribute parallel for {clause}map(to : count){isdp}"]
    if f.loop == "collapse3":
        o += ["    for (int i = 0; i <= M; i++) for (int j = 0; j <= N; j++) for (int k = 0; k <= P; k++) {"]
    else:
        o += ["    for (long cc = 0; cc < nc; cc++) {",
              "      int i = (int)(cc / ((long)(N + 1) * (P + 1)));  /* one declarator per statement: the pre-run race rule */",
              "      int j = (int)((cc / (P + 1)) % (N + 1));", "      int k = (int)(cc % (P + 1));"]
    sfx = lambda s: s.replace("sf[", "sfp[")
    body = ["{" if nomark else "if (sfp[IX(i, j, k)] != 0) {"]
    if f.search:
        body += [sfx(search[0]), sfx(search[1]), sfx(search[2]), "if (g) {"]
    if f.slot == "atomic":
        body += ["  int li;", "#pragma omp atomic capture", "  li = count++;"]
    else:
        body += ["  long li = ((long)i * (N + 1) + j) * (P + 1) + k;"]
    st = f.store
    if st == "direct":
        body += ["  gpp[li].loc[0] = i; gpp[li].loc[1] = j; gpp[li].loc[2] = k;"]
    elif st == "stack":
        body += ["  int tmp[3]; tmp[0] = i; tmp[1] = j; tmp[2] = k; memcpy(gpp[li].loc, tmp, 3 * sizeof(int));"]
    elif st == "memcpy":
        body += ["  int *tmp = (int *)malloc(3 * sizeof(int)); tmp[0] = i; tmp[1] = j; tmp[2] = k;",
                 "  memcpy(gpp[li].loc, tmp, 3 * sizeof(int));"] + FENCE[f.fence] + ["  free(tmp);"]
    else:
        body += ["  int *tmp = (int *)malloc(3 * sizeof(int)); tmp[0] = i; tmp[1] = j; tmp[2] = k;",
                 "  gpp[li].loc[0] = tmp[0]; gpp[li].loc[1] = tmp[1]; gpp[li].loc[2] = tmp[2];"] + FENCE[f.fence] + [
                     "  free(tmp);"]
    body += ["  gpp[li].ib = " + ("1" if nomark else "sfp[IX(i, j, k)]") + ";"]
    if f.extra and f.gp == "full":
        body += ["  gpp[li].xp = 0; gpp[li].yp = 0; gpp[li].zp = 0; gpp[li].slip = 0;",
                 "  gpp[li].DB[0] = 0; gpp[li].DB[1] = 0; gpp[li].DB[2] = 0;"]
    body += ["}}" if f.search else "}"]
    o += ["      " + b for b in body]
    o += ["    }"]
    if not gpmap:
        o += ["    omp_target_memcpy(gps, gpp, nrec * sizeof(gp_t), 0, 0, omp_get_initial_device(), dev);"]
    else:
        o += ["#pragma omp target update from(gps[0 : nrec])"]
    o += ["    long bad = 0, dup = 0, miss = 0; int *hits = calloc(nc, sizeof(int));"]
    if f.slot == "atomic":
        o += ["    for (long q = 0; q < nrec; q++) { int *l = gps[q].loc;",
              "      if (l[0] < 0 || l[1] < 0 || l[2] < 0 || l[0] > M || l[1] > N || l[2] > P) { bad++; continue; }",
              "      hits[((long)l[0] * (N + 1) + l[1]) * (P + 1) + l[2]]++; if (sf[IX(l[0], l[1], l[2])] != gps[q].ib) bad++; }",
              "    long cov = 0; for (long q = 0; q < nc; q++) { if (hits[q] > 1) dup++; if (hits[q] > 0) cov++; } miss = nrec - cov;"]
    else:
        host_pred = "sf[IX(i, j, k)] != 0" + (" && g" if f.search else "")
        o += ["    for (int i = 0; i <= M; i++) for (int j = 0; j <= N; j++) for (int k = 0; k <= P; k++) {"]
        if not nomark:
            o += ["      if (!sf[IX(i, j, k)]) continue;"]
        if f.search:
            o += ["      " + search[0], "      " + search[1], "      " + search[2], "      if (!g) continue;"]
        o += ["      gp_t *r = &gps[((long)i * (N + 1) + j) * (P + 1) + k];",
              "      if (r->loc[0] != i || r->loc[1] != j || r->loc[2] != k) bad++; }"]
    o += ["    printf(\"trial %d: bad %ld dup %ld missing %ld\\n\", t, bad, dup, miss); free(hits);",
          "    tbad += bad + dup + miss;", "  }",
          "  printf(\"RESULT ran_on_host=%d check=%s\\n\", host, tbad == 0 ? \"pass\" : \"fail\");", "  return 0;", "}"]
    return "\n".join(o) + "\n"


def analyze_image(asm: str, ll: str = "") -> dict:
    """Facts about the AFAR OpenMP device image of thresh.c, read from the assembly (.lto.s) and the IR before code generation
    (.precodegen.ll): the slab-bitfield operations are the FLAT atomic or (claim a chunk) and and (free a chunk); the global
    atomics on __llvm_rpc_client are the RPC port lock and are not the allocator's bitfield. For each flat atomic: the lines
    around it, its cache-control bits, the nearest buffer_wbl2 before it and buffer_inv after it (None when there is none
    within the window); for the IR: the flat atomicrmw or/and with the nearest fence before and after it."""
    lines = asm.split("\n")
    out: dict = {"asm_lines": len(lines), "flat_atomics": [], "rpc_global_atomics": 0, "other_global_atomics": 0}
    for key in ("buffer_wbl2", "buffer_inv", "global_atomic", "flat_atomic", "s_sleep"):
        out[f"count_{key}"] = sum(1 for ln in lines if re.match(rf"\s+{key}", ln))
    for k, ln in enumerate(lines):
        if re.match(r"\s+global_atomic_(and|or)\b", ln):
            base = re.search(r"s\[(\d+):(\d+)\]", ln)
            rpc = bool(base) and any("__llvm_rpc_client" in w and re.search(rf"\bs{base.group(1)}\b", w)
                                      for w in lines[max(0, k - 14):k])
            out["rpc_global_atomics" if rpc else "other_global_atomics"] += 1
        m = re.match(r"\s+flat_atomic_(or|and)\b", ln)
        if m:
            before = next((j + 1 for j in range(k - 1, max(0, k - 400), -1) if re.match(r"\s+buffer_wbl2", lines[j])), None)
            after = next((j + 1 for j in range(k + 1, min(len(lines), k + 400)) if re.match(r"\s+buffer_inv", lines[j])), None)
            after_wbl2 = next((j + 1 for j in range(k + 1, min(len(lines), k + 400)) if re.match(r"\s+buffer_wbl2", lines[j])), None)
            out["flat_atomics"].append({
                "line": k + 1, "op": "claim" if m.group(1) == "or" else "clear", "text": ln.strip(),
                "cache_bits": sorted(set(re.findall(r"\b(sc0|sc1|nt)\b", ln))),
                "excerpt": [x.rstrip() for x in lines[max(0, k - 10):k + 3]],
                "buffer_wbl2_before_line": before, "buffer_inv_after_line": after, "buffer_wbl2_after_line": after_wbl2})
    if ll:
        il = ll.split("\n")
        fences = [(k + 1, re.search(r"fence.*?(?:,|$)", ln).group(0).rstrip(",").strip()) for k, ln in enumerate(il)
                  if re.match(r"\s+fence ", ln)]
        out["ir_flat_atomics"] = []
        for k, ln in enumerate(il):
            m = re.match(r"\s+%\S+ = atomicrmw (or|and) ptr %\S+, i32 \S+ (syncscope\(\"\w+\"\) )?(\w+)", ln)
            if m:
                prev = [f for f in fences if f[0] < k + 1]
                nxt = [f for f in fences if f[0] > k + 1]
                out["ir_flat_atomics"].append({
                    "line": k + 1, "op": "claim" if m.group(1) == "or" else "clear", "ordering": m.group(3),
                    "scope": (m.group(2) or "system").strip(), "previous_fence": prev[-1] if prev else None,
                    "next_fence": nxt[0] if nxt else None})
    return out


def exp_head(spec: dict, text: str, launches: int) -> dict:
    """The head of an experiment row: the spec's fields and the hash and length of the source text that is
    compiled. Rows written before this carry the source path only; `results/malloc-dd/final/` is regenerated by
    `tools/campaigns/malloc_dd.py final`, so a path alone does not say which text ran."""
    import hashlib
    keys = ("group", "id", "src", "arch", "args", "env", "xnack", "kind", "libc")
    row = {k: spec[k] for k in keys}
    row.update(launches=launches, src_sha256=hashlib.sha256(text.encode()).hexdigest(),
               src_lines=len(text.splitlines()))
    return row


def split_rows(rows: list, finding_files: dict, observation_files: dict) -> tuple[list, list]:
    """(finding rows, observation rows): each row gets the path of the file its case became; the rows of an
    observation (an unspecified program, docs/tooling/contributing.md) are kept apart so that they never look
    like the evidence of a finding."""
    f, o = [], []
    for r in rows:
        r = dict(r)
        pid = r.get("program_id") or r["cell"].split("|")[1]
        if pid in observation_files:
            r["file"] = observation_files[pid]
            o.append(r)
            continue
        if pid in finding_files:
            r["file"] = finding_files[pid]
        f.append(r)
    return f, o


def launch_verdict(trials: list, expected: int, rc: int) -> dict:
    """What one launch says, from its parsed trial lines (trial, bad, dup, missing) and exit code. A launch fails
    (the failure is reproduced) only when some trial damaged records; a crash (nonzero exit, trials missing)
    without damage is `crashed`, not `fail`, so that removing an ingredient which makes the program crash is not
    taken for 'still fails'."""
    first = next((t[0] for t in trials if t[1] or t[2] or t[3]), 0)
    return {"fail": bool(first), "crashed": rc != 0 or len(trials) != expected, "first_failing_trial": first,
            "max_bad": max((t[1] for t in trials), default=-1)}
