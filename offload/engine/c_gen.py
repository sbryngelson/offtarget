"""The C programs of the slice: OpenMP 5.0, 5.2 and 6.0 in C11.

Each C program is the port of the Fortran program of the same atom
(``offload.engine.gen``), made by ``offload.engine.f2c.translate``. It keeps the
data, oracle, output line (``RESULT ran_on_host=<0|1> check=<pass|fail>``)
and evidence header lines. Ids are ``omp52-c-...`` and ``omp60-c-...``.

Atoms come from ``catalog.slice_atoms(version, lang="c")``. A program must
parse (offload.engine.c_program), carry its atom, violate no rule that holds in C,
and have header lines that match its evidence. ``C_EDITS`` fixes unfaithful
ports, ``C_LABELS`` relabels evidence that does not carry over, and
``C_UNGENERATABLE`` lists atoms with no C program. Illegal variants are the
translated Fortran variants (exceptions in ``C_NO_VARIANT``) plus ``C_ILLEGAL``.
The base check is ``gcc -std=c11 -pedantic-errors -fsyntax-only`` without
``-fopenmp``, against ``OMP_H_STUB``, a declaration-only ``omp.h``.
"""
from __future__ import annotations

import dataclasses
import re
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterable, Iterator

from offload.engine import f2c
from offload.engine import gen as G
from offload.engine.catalog import atom_langs, slice_atoms
from offload.engine.grammar import GrammarError
from offload.engine.rules import (ProgramError, default_rules, parse_program,
                              violations)

C_VERSIONS = (50, 52, 60)
CSTD = "c11"


class CGenError(G.GenError):
    """A C program that fails its own checks (never a silent skip)."""


# --- the omp.h stub for the base-language check ----------------------------------

OMP_H_STUB = """\
/* Declaration-only stub of omp.h, for the base-language check only
   (gcc -std=c11 -pedantic-errors -fsyntax-only, without -fopenmp): it
   declares the OpenMP names the generated C programs use, with the types of
   the OpenMP 5.2/6.0 C API, so that the programs compile as C11 without any
   compiler's OpenMP header. Never linked, never run. */
#ifndef OMP_H_STUB
#define OMP_H_STUB
#include <stdint.h>
typedef uintptr_t omp_uintptr_t;
typedef enum omp_allocator_handle_t {
  omp_null_allocator = 0, omp_default_mem_alloc = 1,
  omp_large_cap_mem_alloc = 2, omp_const_mem_alloc = 3,
  omp_high_bw_mem_alloc = 4, omp_low_lat_mem_alloc = 5,
  omp_cgroup_mem_alloc = 6, omp_pteam_mem_alloc = 7,
  omp_thread_mem_alloc = 8, omp_allocator_handle_t_max = UINTPTR_MAX
} omp_allocator_handle_t;
typedef enum omp_memspace_handle_t {
  omp_default_mem_space = 0, omp_large_cap_mem_space = 1,
  omp_const_mem_space = 2, omp_high_bw_mem_space = 3,
  omp_low_lat_mem_space = 4, omp_memspace_handle_t_max = UINTPTR_MAX
} omp_memspace_handle_t;
typedef enum omp_alloctrait_key_t {
  omp_atk_sync_hint = 1, omp_atk_alignment = 2, omp_atk_access = 3,
  omp_atk_pool_size = 4, omp_atk_fallback = 5, omp_atk_fb_data = 6,
  omp_atk_pinned = 7, omp_atk_partition = 8
} omp_alloctrait_key_t;
typedef struct omp_alloctrait_t {
  omp_alloctrait_key_t key;
  omp_uintptr_t value;
} omp_alloctrait_t;
typedef struct omp_depend_t { char opaque[16]; } omp_depend_t;
typedef enum omp_impex_t {
  omp_not_impex = 0, omp_import = 1, omp_export = 2, omp_impex = 3
} omp_impex_t;
int omp_is_initial_device(void);
int omp_get_team_num(void);
int omp_get_thread_num(void);
int omp_get_default_device(void);
double omp_get_wtime(void);
int omp_get_num_threads(void);
int omp_get_num_teams(void);
int omp_get_num_devices(void);
int omp_get_device_num(void);
int omp_target_is_present(const void *ptr, int device_num);
#endif
"""

OMP_H_STUB_NAMES = frozenset({
    "omp_allocator_handle_t", "omp_memspace_handle_t", "omp_alloctrait_t",
    "omp_alloctrait_key_t", "omp_depend_t", "omp_impex_t",
    "omp_default_mem_alloc", "omp_default_mem_space", "omp_atk_alignment",
    "omp_not_impex", "omp_import", "omp_export", "omp_impex",
    "omp_is_initial_device", "omp_get_team_num", "omp_get_thread_num",
    "omp_get_default_device", "omp_get_wtime", "omp_get_num_threads",
    "omp_get_num_teams", "omp_get_num_devices", "omp_get_device_num",
    "omp_target_is_present", "omp_null_allocator", "omp_large_cap_mem_alloc",
    "omp_const_mem_alloc", "omp_high_bw_mem_alloc", "omp_low_lat_mem_alloc",
    "omp_cgroup_mem_alloc", "omp_pteam_mem_alloc", "omp_thread_mem_alloc",
    "omp_large_cap_mem_space", "omp_const_mem_space",
    "omp_high_bw_mem_space", "omp_low_lat_mem_space"})


def gcc_check(source: str, std: str = CSTD) -> tuple[bool, str]:
    """(ok, output) of ``gcc -std=<std> -pedantic-errors -fsyntax-only``
    (no -fopenmp) on `source` with OMP_H_STUB as omp.h."""
    with tempfile.TemporaryDirectory(prefix="cgen_") as d:
        Path(d, "omp.h").write_text(OMP_H_STUB)
        src = Path(d, "prog.c")
        src.write_text(source)
        res = subprocess.run(
            ["gcc", f"-std={std}", "-pedantic-errors", "-fsyntax-only",
             "-Wno-unknown-pragmas", "-I", d, str(src)],
            capture_output=True, text=True)
        return res.returncode == 0, (res.stdout + res.stderr).replace(
            d, "<tmp>")


# --- atoms --------------------------------------------------------------------------

def fortran_atom(atom: str) -> str:
    """The Fortran atom whose program a C atom's program is ported from:
    a ``for`` compound from the ``do`` compound, others itself."""
    if atom.startswith("omp.directive."):
        words = atom[len("omp.directive."):].split("_")
        return "omp.directive." + "_".join("do" if w == "for" else w
                                           for w in words)
    return atom


def c_pid(atom: str, version: int) -> str:
    return f"omp{version}-c-" + atom.removeprefix("omp.").replace(".", "-")


def c_atoms(version: int) -> list[str]:
    return slice_atoms(version, lang="c")


# --- header ------------------------------------------------------------------------

def _set_header(src: str, key: str, value: str) -> str:
    new, n = re.subn(rf"^// {re.escape(key)}: .*$", f"// {key}: {value}",
                     src, count=1, flags=re.M)
    if n != 1:
        raise CGenError(f"no header line {key!r}")
    return new


def _header_lines(src: str) -> list[str]:
    out = []
    for line in src.splitlines():
        if not line.startswith("// "):
            break
        out.append(line)
    return out


def _add_header(src: str, line: str) -> str:
    """Append a header line (after the existing ones)."""
    lines = src.split("\n")
    k = 0
    while k < len(lines) and lines[k].startswith("// "):
        k += 1
    lines.insert(k, f"// {line}")
    return "\n".join(lines)


def relabel(src: str, evidence: str, kind: str, reason: str,
            basis: str | None, version: int, checked: bool = False) -> str:
    """Give a ported program the evidence level `evidence` (``unverified``
    or a no-oracle category) with its header lines, as
    gen_templates.Src.unverified / no_oracle do for Fortran: the old
    unverified/no-oracle/basis lines are replaced; unless `checked`, the
    program becomes observable=no."""
    lines = [ln for ln in src.split("\n")
             if not re.match(r"^// (unverified \(|no oracle \(|basis: |"
                             r"legality oracle: )", ln)]
    src = "\n".join(lines)
    src = _set_header(src, "evidence", evidence)
    if not checked:
        note = ("unverified: the check covers the device kernel, not the "
                "atom" if evidence == "unverified" else
                f"{evidence}: the check covers the device kernel, not the "
                "atom")
        src = _set_header(src, "observable", f"no ({note})")
    if evidence == "unverified":
        src = _add_header(src, f"unverified ({kind}): {reason}")
    else:
        src = _add_header(src, f"no oracle ({evidence}): {reason}")
        src = _add_header(src, f"basis: {G.basis_text(basis, version)}")
    return src


# --- C-specific edits and labels -------------------------------------------------------

def _sub(old: str, new: str, count: int = 1):
    def fn(src: str) -> str:
        n = src.count(old)
        if n != count:
            raise CGenError(f"edit: {old!r} occurs {n} times, expected "
                            f"{count}")
        return src.replace(old, new)
    return fn


def _chain(*fns):
    def fn(src: str) -> str:
        for f in fns:
            src = f(src)
        return src
    return fn


def _note(text: str):
    return lambda src: _add_header(src, text)


# atom -> (reason, transform of the translated source), applied to the C
# program at every version where the atom has one (filled below)
C_EDITS: dict[str, tuple[str, Callable[[str], str]]] = {}
# atom -> (evidence, kind, reason, basis id) relabelling of a port whose
# Fortran oracle does not carry over to C
C_LABELS: dict[str, tuple[str, str, str, str | None]] = {}
# version -> atom -> reason: no C program
C_UNGENERATABLE: dict[int, dict[str, str]] = {50: {
    # The 5.0 Fortran program of linear(val(x)) puts the clause on
    # a declare simd directive (the 5.0 worksharing-loop and simd constructs
    # forbid a linear modifier: 5.0 §2.9.2, p.107; §2.9.3.1, p.113), whose
    # procedure offload.engine.f2c does not port; declare simd is outside the
    # device-offload slice
    "omp.clause.linear.val": "the 5.0 program needs linear(val(x)) on a "
    "declare simd directive (5.0 forbids the modifier on the loop "
    "constructs), and compliance.f2c does not port a declare simd "
    "procedure; declare simd is outside the slice",
}, 52: {}, 60: {}}
# The C rules (lang c) without a 5.0 sentence, with the reason
C_RULES_NOT_50 = {
    "intervening-loop-001": "5.0 states no restriction on the statements "
    "of intervening code (5.0 §2.9.2, p.103 says only how often it runs)",
    "finalbody-loop-001": "5.0 has no final-loop-body restriction (the "
    "canonical loop form of 5.0 §2.9.1 has no such term)",
    "default-dsa-002": "the 5.0 C default clause has no firstprivate or "
    "private argument (5.0 §2.19.4.1: default(shared | none))",
}


def _edit(atoms, reason, fn):
    for a in ([atoms] if isinstance(atoms, str) else atoms):
        C_EDITS[a] = (reason, fn)


# begin declare target (C only): the declare target program's module
# variable in a delimited region instead of the extended-list form; the
# same oracle (the device copy of dv is written by one target region and
# read by the next)
_edit("omp.directive.begin_declare_target",
      "the delimited form (5.2 §7.8.2, 6.0 §9.9.2) of the declare target "
      "program: dv is declared between begin declare target and end "
      "declare target instead of being named by declare target(dv)",
      _chain(_sub("int dv = 1;\nint dw = 1;\n#pragma omp declare target(dv)",
                  "#pragma omp begin declare target\nint dv = 1;\n"
                  "#pragma omp end declare target\nint dw = 1;"),
             _note("C: dv is declared in a begin declare target ... end "
                   "declare target region (its implicit extended list)")))


# The Fortran device_type programs name f in the
# deprecated `to` at 5.2 (CCE 19 ftn rejects `enter`); every clang C front
# end rejects `to` at -fopenmp-version=52 (finding
# clang-c-declare-target-to-omp52.c), so the C ports would measure that
# rejection, not device_type. The C 5.2 ports use `enter` (5.2 §5.8.4
# p.157: to is a deprecated synonym of enter); at 6.0 they already do.
def _dt_enter(src: str) -> str:
    old = "#pragma omp declare target to(f)"
    if old not in src or "// id: omp50-" in src:
        # 5.0 has no enter clause (5.2 §B.2, p.627: enter was
        # added as a synonym of to), so the 5.0 C port keeps to(f)
        return src
    return _add_header(src.replace(old, "#pragma omp declare target enter(f)"),
                       "C: f is named in an enter clause (the deprecated "
                       "synonym to, which the Fortran program keeps for CCE "
                       "19, is rejected by the clang C front ends at 5.2)")


_edit(("omp.clause.device_type", "omp.clause.device_type.any",
       "omp.clause.device_type.nohost"),
      "declare target enter(f) instead of the deprecated to(f)",
      _dt_enter)


# defaultmap(...: pointer): in C the pointer category is the pointer
# variable itself (5.2 §5.8.7, 6.0 §7.9.9), not a Fortran POINTER's target,
# and the port's device writes through wp would dereference a host address
# in copy mode. The C oracle: wp's pointee is mapped by target enter data;
# without the clause a referenced pointer is treated as the base pointer of
# a zero-length array section (5.2 §5.8.1, p.148; 6.0 §7.9.3, p.277), so
# the device sees the address of the device copy; with defaultmap(to:
# pointer) the pointer is mapped as a variable and keeps the host address.
# The device's value of wp comes back in pw; in copy mode it must equal the
# host address (under unified memory the two coincide: copy_mode_only).
def _defaultmap_pointer(src: str) -> str:
    start = src.index("  #pragma omp target map(to: a) map(from: b) "
                      "map(tofrom: host_flag) defaultmap(to: pointer)")
    end = src.index("  free(wp);")
    # Pw starts at NULL (never the host address the check wants),
    # so a lost copy-back fails deterministically
    new = """\
  pw = NULL;
  #pragma omp target enter data map(to: wp[0:n])
  #pragma omp target map(to: a) map(from: b) map(from: pw) map(tofrom: host_flag) \\
      defaultmap(to: pointer)
  {
    host_flag = (omp_is_initial_device() ? 1 : 0);
    pw = wp;
    for (int i = 1; i <= n; i++) {
      b[i - 1] = 2 * a[i - 1] + 1;
    }
  }
  #pragma omp target exit data map(delete: wp[0:n])
  if (!shared_mem) pres = pres && (pw == wp);
"""
    src = src[:start] + new + src[end:]
    src = src.replace("  int *wp;\n", "  int *wp;\n  int *pw;\n", 1)
    return _add_header(src, "C: the pointer category is the pointer variable "
                       "itself; the check compares the device's value of wp "
                       "(mapped to by defaultmap) with the host address, "
                       "while the pointee is present (without the clause the "
                       "pointer is attached to the device copy)")


_edit("omp.clause.defaultmap.pointer",
      "C pointer category: the pointer's own value is mapped (see "
      "_defaultmap_pointer)", _defaultmap_pointer)


# The C audit is the first audit that could run these programs:
# no Fortran toolchain passes their originals (Fortran disposition
# unaudited_no_passing_original), so the weakness of their checks showed
# only in C (the mutant survived). The C programs get a check that
# separates where one exists (C_EDITS below), or the label the spec gives
# (C_LABELS); the Fortran programs are unchanged (their check is the same
# and stays unaudited there).
def _w_unchanged(src: str, copy_only: bool = False) -> str:
    """Check that the region's writes to w do not reach the host's w (the
    category's behaviour keeps w private or unmapped); `copy_only`: only
    in copy mode (storage map-type: under unified memory the storage is
    the host's)."""
    check = ("  bool wz = true;\n  for (int k_ = 0; k_ < n; k_++)\n"
             "    wz = wz && (w[k_] == 0);\n")
    if copy_only:
        src = src.replace("  bool ok;\n", "  bool ok;\n  bool pres;\n"
                          "  bool shared_mem;\n  int zc[1];\n", 1)
        detector = ("  pres = true;\n  zc[0] = 0;\n  #pragma omp target "
                    "map(to: zc)\n  {\n    zc[0] = 1;\n  }\n  shared_mem "
                    "= zc[0] == 1;\n")
        src = src.replace("  c = 0;\n", detector + "  c = 0;\n", 1)
        check += "  if (!shared_mem) pres = pres && wz;\n"
        src = src.replace("  ok = t2_;", "  ok = t2_ && pres;", 1)
        src = _set_header(src, "evidence", "copy_mode_only")
    else:
        src = src.replace("  ok = t2_;", "  ok = t2_ && wz;", 1)
    marker = "  bool t2_ = true;\n"
    if src.count(marker) != 1 or "ok = t2_ &&" not in src:
        raise CGenError("w check: the program shape changed")
    src = src.replace(marker, check + marker, 1)
    return _add_header(src, "C: the check also reads w after the region: "
                       "the defaultmap category keeps the region's writes "
                       "to the aggregate w " + ("unmapped (copy mode)" if
                                                copy_only else "private")
                       + "; without the clause w is mapped tofrom and they "
                       "come back (the Fortran program checks b only)")


_edit(["omp.clause.defaultmap.firstprivate", "omp.clause.defaultmap.private"],
      "the check also reads w (the port of the Fortran check, b only, "
      "survived the C mutant)", _w_unchanged)
_edit("omp.clause.defaultmap.storage",
      "the check also reads w in copy mode (storage: allocated, not "
      "transferred)", lambda s: _w_unchanged(s, copy_only=True))


def _legality(rid_stem: str):
    def fn(src: str) -> str:
        v = re.search(r"^// id: omp(\d\d)-", src, re.M).group(1)
        lines = [ln for ln in src.split("\n")
                 if not re.match(r"^// (unverified \(|no oracle \(|basis: )",
                                 ln)]
        src = "\n".join(lines)
        src = _set_header(src, "evidence", "legality")
        src = _set_header(src, "observable", "no (legality: the check covers "
                          "the device kernel, not the atom)")
        return _add_header(src, f"legality oracle: OMP{v}-{rid_stem}")
    return fn


# C 5.0 has default(shared | none) only (private and firstprivate
# came in 5.1, 5.1 §B.2 p.669), so the 5.0 ports of the programs that use
# default(private) use default(none) with every variable listed; the
# clause's effect is then the compile-time restriction of default(none),
# whose oracle is the illegal variant of default-dsa-001 (as default(none)
# at 5.2); the 5.2 and 6.0 ports are unchanged
def _default_none_50(listed: str):
    def fn(src: str) -> str:
        if "// id: omp50-" not in src:
            return src
        old = "default(private) shared(a, b)"
        if src.count(old) != 1:
            raise CGenError("default(private): the program shape changed")
        src = src.replace(old, f"default(none) {listed}")
        src = _add_header(src, "C 5.0: default(none) with every referenced "
                          "variable listed (default(private) is not C 5.0)")
        return _legality("default-dsa-001")(src)
    return fn


_edit("omp.clause.default", "C 5.0: default(none) (no default(private) "
      "in C 5.0)", _default_none_50("shared(a, b) private(c)"))
_edit("omp.clause.shared", "C 5.0: default(none) (no default(private) "
      "in C 5.0)", _default_none_50("shared(a, b)"))

_edit("omp.clause.defaultmap.none",
      "defaultmap(none) only requires every referenced variable to have an "
      "explicit data-sharing or mapping attribute: a compile-time "
      "restriction (5.2 §5.8.7 p.162, 6.0 §7.9.9), so its oracle is the "
      "illegal variant of defaultmap-map-003 (as default(none) and "
      "default-dsa-001); the C mutant survived", _legality(
          "defaultmap-map-003"))

C_LABELS.update({
    # (evidence, kind, reason, basis id)
    "omp.clause.default.aggregate": (
        "equivalent_default", "", "default(shared: aggregate) on the "
        "parallel construct shares the aggregates it does not list, which "
        "is what a parallel construct does without a default clause (C "
        "mutant survived)", "default_parallel_shared"),
    "omp.clause.default.pointer": (
        "equivalent_default", "", "default(shared: pointer) on the "
        "parallel construct shares the pointers it does not list, which is "
        "what a parallel construct does without a default clause (C mutant "
        "survived)", "default_parallel_shared"),
    "omp.clause.default.scalar": (
        "equivalent_default", "", "default(shared: scalar) on the parallel "
        "construct shares the scalars it does not list, which is what a "
        "parallel construct does without a default clause (C mutant "
        "survived)", "default_parallel_shared"),
    "omp.clause.reduction.original": (
        "equivalent_default", "", "original(shared) on an item that is "
        "shared in the enclosing context (s, mapped tofrom on the target "
        "leaf) assumes what the default sharing argument assumes there (C "
        "mutant survived)", "reduction_original_default"),
    "omp.clause.num_threads.strict": (
        "unverified", "oracle_not_written", "the program asks for 4 "
        "threads, which both toolchains give with or without strict (C "
        "mutant survived); the oracle is a negative probe: a strict "
        "request the implementation cannot meet must end in runtime error "
        "termination (6.0 §12.1.2), without strict the region runs with "
        "fewer threads", None),
    "omp.clause.replayable": (
        "unverified", "oracle_not_written", "outside a taskgraph region a "
        "replayable construct runs as any other (C mutant survived); the "
        "oracle needs a taskgraph region (6.0 §14.3) recorded and "
        "replayed, where only a replayable construct is executed again", None),
    "omp.clause.allocate": (
        "unverified", "needs_other_infrastructure", "the program cannot "
        "observe which allocator provides the private copy of t: no OpenMP "
        "routine reports a variable's allocator and the default allocator "
        "returns ordinary memory (C mutant survived on AFAR)", None),
    "omp.clause.allocate.allocator": (
        "unverified", "needs_other_infrastructure", "the program cannot "
        "observe which allocator provides the private copy of t (no OpenMP "
        "routine reports a variable's allocator; omp_default_mem_alloc and "
        "the default allocator both return ordinary memory; C mutant "
        "survived on AFAR)", None),
    "omp.clause.allocate.allocator_simple_modifier": (
        "unverified", "needs_other_infrastructure", "the program cannot "
        "observe which allocator provides the private copy of t (no OpenMP "
        "routine reports a variable's allocator; C mutant survived on "
        "AFAR)", None),
    "omp.clause.allocate.align": (
        "unverified", "oracle_not_written", "the program does not check the "
        "private copy's address: a check of its address modulo an "
        "alignment larger than any default (e.g. align(4096)) would fail "
        "without the modifier (C mutant survived on AFAR)", None),
    "omp.clause.uses_allocators": (
        "unverified", "needs_other_infrastructure", "uses_allocators("
        "omp_default_mem_alloc) makes a predefined allocator available in "
        "the region (5.2 §6.8, 6.0 §8.8); which allocator provides the "
        "private copy is not observable by the program (C mutant survived "
        "on both toolchains)", None),
})


# --- building -----------------------------------------------------------------------

def _c_rules_violations(source: str, version: int) -> list[str]:
    return violations(parse_program(source, version, lang="c"), version)


def _parsed_atoms(source: str, version: int) -> frozenset:
    tree = parse_program(source, version, lang="c")
    return frozenset().union(*(d.atoms for d in tree.directives),
                             *(d.atoms for d in tree.ends.values()))


def _port(f_source: str, version: int, pid: str, atom: str,
          f_pid: str) -> str:
    try:
        src = f2c.translate(f_source, version)
    except (f2c.TranslateError, GrammarError) as err:
        raise CGenError(f"{pid}: not ported: {err}") from err
    lines = src.split("\n")
    lines[0] = (f"// Generated by compliance.c_gen (OpenMP {version // 10}."
                f"{version % 10}, C11): the C port (compliance.f2c) of "
                f"{f_pid}. Do not edit.")
    src = "\n".join(lines)
    src = _set_header(src, "id", pid)
    src = _set_header(src, "primary atom", atom)
    src = _set_header(src, "std", CSTD)
    # Fortran needs a device-callable c_f_pointer; the C port assigns the
    # pointer instead (no such need)
    m = re.search(r"^// needs: (.*)$", src, re.M)
    if m and "device_c_f_pointer" in m.group(1):
        needs = [x.strip() for x in m.group(1).split(",")
                 if x.strip() != "device_c_f_pointer"]
        src = _set_header(src, "needs", ", ".join(needs) or "none")
    return src


def _meta(src: str) -> dict:
    head = {}
    for line in _header_lines(src):
        m = re.match(r"^// ([a-z_ ]+): (.*)$", line)
        if m:
            head.setdefault(m.group(1), m.group(2))
    return head


def _finish(pid: str, atom: str, version: int, src: str,
            legal: bool = True, violates: str | None = None,
            fprog: G.Program | None = None) -> G.Program:
    try:
        atoms = _parsed_atoms(src, version)
        found = _c_rules_violations(src, version)
    except (GrammarError, ProgramError) as err:
        raise CGenError(f"{pid}: {err}\n{src}") from err
    if legal and atom not in atoms:
        raise CGenError(f"{pid}: the program does not exercise {atom}\n"
                        f"{src}")
    if legal and found:
        raise CGenError(f"{pid}: legal program violates {found}\n{src}")
    head = _meta(src)
    evidence = head["evidence"]
    unv = G._UNVERIFIED_LINE.findall(src)
    noo = G._NO_ORACLE_LINE.findall(src)
    if (evidence == "unverified") != bool(unv) or (
            evidence in G.NO_ORACLE) != bool(noo) or (
            evidence == "legality") != bool(G.legality_of(src)):
        raise CGenError(f"{pid}: evidence {evidence!r} and its header "
                        "lines disagree")
    needs = () if head["needs"] == "none" else tuple(
        x.strip() for x in head["needs"].split(","))
    expect = head.get("expect", "result").split()[0]
    prog = G.Program(pid, "c", src, atoms, atom, legal, violates,
                     not head["observable"].startswith("no"), CSTD, needs,
                     evidence, expect, head.get("token", ""), "omp",
                     G.scope_of(src)[0])
    G._check_scope(prog)
    return prog


@lru_cache(maxsize=None)
def c_legal(atom: str, version: int) -> G.Program:
    """The C program of `atom` at `version`."""
    if version not in C_VERSIONS:
        raise CGenError(f"no C programs at {version}")
    if atom in C_UNGENERATABLE.get(version, {}):
        raise CGenError(f"{atom}: {C_UNGENERATABLE[version][atom]}")
    pid = c_pid(atom, version)
    fa = fortran_atom(atom)
    if fa == "omp.directive.begin_declare_target":
        fa = "omp.directive.declare_target"
    fprog = G._legal(fa, version)
    src = _port(fprog.source, version, pid, atom, fprog.id)
    if atom in C_EDITS:
        src = C_EDITS[atom][1](src)
    if atom in C_LABELS and fprog.evidence in G.AUDITED:
        ev, kind, reason, basis = C_LABELS[atom]
        src = relabel(src, ev, kind, reason, basis, version)
    return _finish(pid, atom, version, src, fprog=fprog)


@lru_cache(maxsize=None)
def c_hostdev(atom: str, version: int) -> G.Program:
    """The C port of the host+device pattern program of `atom` (offload.engine.gen.HOST_DEVICE)."""
    fprog = G._hostdev(fortran_atom(atom), version)
    pid = c_pid(atom, version) + "-hostdev"
    src = _port(fprog.source, version, pid, atom, fprog.id)
    return _finish(pid, atom, version, src, fprog=fprog)


# --- illegal variants ---------------------------------------------------------------

# rule id -> reason: a generated Fortran variant with no C variant
C_NO_VARIANT: dict[str, str] = {}
# (C_ILLEGAL entries for a rule with a Fortran variant replace its port)
# C-only variants: rule id -> (base C atom, transform of its C source)
C_ILLEGAL: dict[str, tuple[str, Callable[[str], str]]] = {}


def _ins_after(pattern: str, lines: list[str]):
    """Insert `lines` after the one line matching `pattern` (re.search),
    at its indentation."""
    def fn(src: str) -> str:
        out = src.split("\n")
        hits = [k for k, ln in enumerate(out) if re.search(pattern, ln)]
        if len(hits) != 1:
            raise CGenError(f"edit: {pattern!r} matches {len(hits)} lines")
        k = hits[0]
        ind = out[k][:len(out[k]) - len(out[k].lstrip())]
        out[k + 1:k + 1] = [ind + x for x in lines]
        return "\n".join(out)
    return fn


def _move_to_main(line: str):
    """Move a file-scope line into main (its first statement)."""
    return _chain(_sub(line + "\n", ""),
                  _sub("int main(void) {\n", f"int main(void) {{\n  {line}\n"))


def _wrap_loop_in_block(pragma_re: str):
    """The loop after the matching pragma made the statement of a compound
    statement: the directive is then followed by a block, not a loop."""
    def fn(src: str) -> str:
        out = src.split("\n")
        hits = [k for k, ln in enumerate(out) if re.search(pragma_re, ln)]
        if len(hits) != 1:
            raise CGenError(f"edit: {pragma_re!r} matches {len(hits)} lines")
        k = hits[0]
        while out[k].rstrip().endswith("\\"):
            k += 1
        ind = out[k + 1][:len(out[k + 1]) - len(out[k + 1].lstrip())]
        depth, j = 0, k + 1
        while True:
            depth += out[j].count("{") - out[j].count("}")
            if depth == 0 and j > k + 1 or (depth == 0 and "{" not in
                                             out[j] and j == k + 1):
                break
            j += 1
        out[k + 1:j + 1] = [ind + "{"] + ["  " + x for x in out[k + 1:j + 1]] \
            + [ind + "}"]
        return "\n".join(out)
    return fn


_FOR_I = "for (int i = 1; i <= n; i++) {"
_PFOR_LOOP = r"#pragma omp parallel for default\(none\) shared\(a, b, nref, nthr\)$"


def _c_illegal(stem, versions, base, fn):
    for v in versions:
        C_ILLEGAL[f"OMP{v}-{stem}"] = (base, fn)


BOTH = (52, 60)
# The C-only variants also at 5.0 where the rule has its 5.0 sentence
ALL = (50, 52, 60)
# the Fortran assoc-loop-001 variant replaces the DO loop by an array
# assignment, whose C port is a canonical for loop again; the C variant
# puts the loop in a compound statement, which is not a loop nest
_c_illegal("assoc-loop-001", ALL, "omp.directive.parallel_for",
           _wrap_loop_in_block(r"#pragma omp parallel for"))
# the Fortran declaretarget-clause-002 variant (device_type alone in the
# procedure) ports to the legal delimited form; in C the directive with
# clauses and no enter or link is a file-scope declare target
_c_illegal("declaretarget-clause-002", (52,), "omp.clause.device_type.any",
           _chain(_sub("#pragma omp declare target enter(f) device_type(any)",
                       "#pragma omp declare target device_type(any)"),
                  # the legal port's note does not apply
                  _sub("// C: f is named in an enter clause (the deprecated "
                       "synonym to, which the Fortran program keeps for CCE "
                       "19, is rejected by the clang C front ends at 5.2)\n",
                       "")))
# requires after a device construct: in C at file scope after main (the
# Fortran variant's requires in the program body is also not at file scope)
_c_illegal("requires-placement-002", (50, 52), "omp.directive.target",
           lambda src: src.rstrip("\n") +
           "\n#pragma omp requires unified_shared_memory\n")
# --- C-only rules --------------------------------------------------------------
_c_illegal("requires-placement-005", ALL, "omp.directive.requires",
           _move_to_main("#pragma omp requires "
                         "atomic_default_mem_order(seq_cst)"))
_c_illegal("directive-placement-001", ALL, "omp.directive.target_update",
           _sub("  #pragma omp target update to(a)\n",
                "  if (host_flag == 1)\n    #pragma omp target update to(a)\n"
                "  ;\n"))
_c_illegal("canonical-loop-001", ALL, "omp.directive.parallel_for",
           _sub("    for (int i = 1; i <= n; i++) {\n      b[i - 1] = 2 * a",
                "    for (int i = n + 1; i <= n; i--) {\n      b[i - 1] = 2 * a"))
_c_illegal("canonical-loop-002", ALL, "omp.directive.parallel_for",
           _sub("    for (int i = 1; i <= n; i++) {\n      b[i - 1] = 2 * a",
                "    for (int i = n + 1; n >= i; i--) {\n      b[i - 1] = 2 * a"))
_c_illegal("canonical-loop-003", ALL, "omp.directive.parallel_for",
           _sub("    for (int i = 1; i <= n; i++) {\n      b[i - 1] = 2 * a",
                "    for (int i = 1; i != n + 1; i += 2) {\n"
                "      b[i - 1] = 2 * a"))
_c_illegal("loopvar-loop-004", ALL, "omp.directive.parallel_for",
           _sub("    for (int i = 1; i <= n; i++) {\n      b[i - 1] = 2 * a",
                "    for (float f = 1; f <= n; f++) {\n      int i = f;\n"
                "      b[i - 1] = 2 * a"))
_c_illegal("intervening-loop-001", BOTH, "omp.clause.collapse",
           _ins_after(r"for \(int j = 1; j <= 2; j\+\+\) \{$",
                      ["  while (0) { }"]))
_c_illegal("finalbody-loop-001", BOTH, "omp.directive.parallel_for",
           _ins_after(r"b\[i - 1\] = 2 \* a\[i - 1\] \+ 1;$",
                      ["if (i > n) break;"]))
_c_illegal("linear-clause-005", ALL, "omp.clause.linear",
           _sub("  int x;\n", "  double x;\n"))
_c_illegal("aligned-clause-003", ALL, "omp.clause.aligned",
           _chain(_sub("  bool ok;\n", "  bool ok;\n  int al;\n"),
                  _sub("aligned(a: 8)", "aligned(a: 8) aligned(al)")))
_c_illegal("isdeviceptr-clause-001", (52,), "omp.clause.is_device_ptr",
           _chain(_sub("  bool ok;\n", "  bool ok;\n  int dq = 0;\n"),
                  _sub("is_device_ptr(pa, pb)", "is_device_ptr(pa, pb, dq)")))
# The 5.0 program's target region is in dev_kernel
_c_illegal("isdeviceptr-clause-001", (50,), "omp.clause.is_device_ptr",
           _chain(_sub("  int *qq;\n", "  int *qq;\n  int dq = 0;\n"),
                  _sub("is_device_ptr(pa, pb)", "is_device_ptr(pa, pb, dq)")))
_c_illegal("reduction-clause-007", ALL, "omp.clause.reduction.max",
           _chain(_sub("  int sref;\n", "  int sref;\n  int *mp = 0;\n"),
                  _sub("reduction(max: s)", "reduction(max: s, mp)")))
_c_illegal("reduction-clause-008", ALL, "omp.clause.reduction.max",
           _chain(_sub("  int sref;\n", "  int sref;\n  const int cs = 0;\n"),
                  _sub("reduction(max: s)", "reduction(max: s, cs)")))
_c_illegal("privatization-dsa-001", ALL, "omp.clause.private",
           _chain(_sub("  bool ok;\n", "  bool ok;\n  const int ct = 1;\n"),
                  _sub("private(t)", "private(t, ct)")))
_BITS = _sub("enum { n = 64 };\n", "enum { n = 64 };\nstruct bf {\n  int f : 4;"
             "\n  int g;\n};\nunion uv {\n  int i;\n  float x;\n};\n")
_c_illegal("map-clause-003", ALL, "omp.directive.target", _chain(
    _BITS, _sub("  bool ok;\n", "  bool ok;\n  struct bf bv;\n"),
    _sub("#pragma omp target map(to: a) map(from: b) map(tofrom: host_flag)",
         "#pragma omp target map(to: a) map(from: b) map(tofrom: host_flag) "
         "map(tofrom: bv.f)")))
_c_illegal("map-clause-004", ALL, "omp.directive.target", _chain(
    _BITS, _sub("  bool ok;\n", "  bool ok;\n  union uv uw;\n"),
    _sub("#pragma omp target map(to: a) map(from: b) map(tofrom: host_flag)",
         "#pragma omp target map(to: a) map(from: b) map(tofrom: host_flag) "
         "map(tofrom: uw.i)")))
_c_illegal("depend-clause-005", ALL, "omp.clause.depend.out", _chain(
    _BITS, _sub("  bool ok;\n", "  bool ok;\n  struct bf bv;\n"),
    _sub("depend(inout: tk)", "depend(inout: tk) depend(out: bv.f)")))
for _v, _sp in ((50, "declare mapper"), (52, "declare mapper"),
                 (60, "declare_mapper")):
    _c_illegal("declaremapper-clause-006", (_v,), "omp.clause.map.mapper",
               _ins_after(r"^#pragma omp declare.mapper\(mm",
                          [f"#pragma omp {_sp}(im: int v) map(v)"]))
_c_illegal("arraysection-clause-003", ALL, "omp.directive.target_update",
           _chain(_sub("  bool ok;\n", "  bool ok;\n  int sx = 0;\n"),
                  _sub("#pragma omp target update to(a)",
                       "#pragma omp target update to(a) to(sx[0:1])")))
_c_illegal("arraysection-clause-004", ALL, "omp.directive.target_update",
           _sub("#pragma omp target update to(a)",
                "#pragma omp target update to(a[0:n:0])"))
_c_illegal("arraysection-clause-005", ALL, "omp.directive.target_update",
           _sub("#pragma omp target update to(a)",
                "#pragma omp target update to(a) to(b[0:-1])"))
_c_illegal("default-dsa-002", BOTH, "omp.clause.default.firstprivate", _chain(
    _sub("enum { n = 64 };\n", "enum { n = 64 };\nint gz = 0;\n"),
    _sub("      c = 2 * a[i - 1];\n", "      c = 2 * a[i - 1] + gz;\n")))
# the oracle of the defaultmap(none) programs (relabelled legality above)
_c_illegal("defaultmap-map-003", BOTH, "omp.clause.defaultmap.none",
           _sub("defaultmap(none) private(i)", "defaultmap(none)"))
_c_illegal("declaretarget-placement-004", (60,), "omp.directive.declare_target",
           _move_to_main("#pragma omp declare target(dv)"))
for _v, _sp in ((50, "declare reduction"), (52, "declare reduction"),
                 (60, "declare_reduction")):
    _c_illegal("declarereduction-clause-001", (_v,), "omp.clause.reduction.max",
               _sub("enum { n = 64 };\n", f"enum {{ n = 64 }};\n#pragma omp "
                    f"{_sp}(cr: const int: omp_out += omp_in)\n"))


@lru_cache(maxsize=1)
def _rule_langs() -> dict[str, str]:
    return {r.id: r.lang for r in default_rules()}


def c_violation_ids(version: int) -> list[str]:
    """Rule ids with a C illegal variant at `version`: the ported Fortran
    variants of rules that hold in C, and the C-only variants."""
    langs = _rule_langs()
    out = [rid for rid in G.VIOLATION_BASE
           if rid.startswith(f"OMP{version}-")
           and langs.get(rid) in ("both", "c") and rid not in C_NO_VARIANT
           and rid not in C_ILLEGAL]
    out += [rid for rid in C_ILLEGAL if rid.startswith(f"OMP{version}-")]
    return sorted(set(out))


def c_base_atom(rid: str) -> str:
    """The C atom whose program an illegal variant is built on."""
    if rid in C_ILLEGAL:
        return C_ILLEGAL[rid][0]
    fa = G.VIOLATION_BASE[rid][0]
    if fa.startswith("omp.directive."):
        words = fa[len("omp.directive."):].split("_")
        return "omp.directive." + "_".join("for" if w == "do" else w
                                           for w in words)
    return fa


@lru_cache(maxsize=None)
def c_illegal(rid: str) -> G.Program:
    version = int(rid[3:5])
    stem = rid.split("-", 1)[1]
    pid = f"omp{version}-c-illegal-{stem}"
    if rid in C_ILLEGAL:
        base_atom, fn = C_ILLEGAL[rid]
        base = c_legal(base_atom, version)
        src = fn(base.source)
    else:
        fprog = G._illegal(rid)
        src = _port(fprog.source, version, pid,
                    _meta_f(fprog.source, "primary atom"), fprog.id)
        base_atom = c_base_atom(rid)
        if stem in G.VARIANT_PRIMARY:  # The Fortran override
            base_atom = G.VARIANT_PRIMARY[stem]
        src = _set_header(src, "primary atom", base_atom)
    src = _set_header(src, "id", pid)
    src = _set_header(src, "legal", f"no (violates {rid})")
    try:
        found = _c_rules_violations(src, version)
    except (GrammarError, ProgramError) as err:
        raise CGenError(f"{pid}: {err}\n{src}") from err
    if found != [rid]:
        raise CGenError(f"{pid}: violates {found}, expected [{rid}]\n{src}")
    prog = _finish(pid, base_atom, version, src, legal=False, violates=rid)
    if G.needs_zero_copy(src) and "zero_copy" not in prog.needs:
        needs = tuple(prog.needs) + ("zero_copy",)
        src = _set_header(src, "needs", ", ".join(needs))
        prog = dataclasses.replace(prog, source=src, needs=needs)
    return prog


def _meta_f(source: str, key: str) -> str:
    m = re.search(rf"^! {re.escape(key)}: (.*)$", source, re.M)
    return m.group(1) if m else ""


# --- the entry point ---------------------------------------------------------------

def generate_c(atoms: Iterable[str], version: int) -> Iterator[G.Program]:
    """One legal C program per atom (sorted; atoms in C_UNGENERATABLE are
    skipped), then the illegal variants whose base atom is among `atoms`
    (sorted by rule id)."""
    wanted = sorted(set(atoms))
    skip = C_UNGENERATABLE.get(version, {})
    for atom in wanted:
        if atom not in skip:
            yield c_legal(atom, version)
            if fortran_atom(atom) in G.HOST_DEVICE:
                yield c_hostdev(atom, version)
    chosen = set(wanted) - set(skip)
    for rid in c_violation_ids(version):
        if c_base_atom(rid) in chosen:
            yield c_illegal(rid)


def all_c_programs(version: int) -> list[G.Program]:
    return list(generate_c(c_atoms(version), version))


def fortran_only_atoms(version: int) -> list[str]:
    return sorted(a for a, ls in atom_langs(version).items()
                  if ls == frozenset({"f90"}))


def c_only_atoms(version: int) -> list[str]:
    return sorted(a for a, ls in atom_langs(version).items()
                  if ls == frozenset({"c"}))
