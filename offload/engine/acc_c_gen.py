"""The OpenACC 3.4 C programs: the C slice of OpenACC for NVHPC nvc.

Every program is the C port of the Fortran OpenACC program of the same atom
(``offload.engine.acc_gen`` through ``offload.engine.gen``), made by
``offload.engine.f2c.translate`` at version 34, with the same data, oracle, output
line and evidence level. Ids are ``acc34-c-...``, with ``Program.lang == "c"``
and ``Program.model == "acc"``.
The atoms are ``catalog.slice_atoms(34, lang="c")``: the Fortran OpenACC atoms
without ``.eqv.`` and ``.neqv.``. A program ``f2c`` cannot port is written by
hand in ``HAND``; atoms with no C program are in ``UNGENERATABLE``. Each
program must parse, carry its atom, violate no OpenACC rule that holds in C,
and pass ``gcc -std=c11 -fsyntax-only`` against ``OPENACC_H_STUB``. Illegal
variants are ports of the Fortran ones whose rule holds in C (``NO_VARIANT``).
CCE's C compiler and amdclang run OpenACC regions on the host, so the C slice
runs on NVHPC only."""
from __future__ import annotations

import re
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Iterator

from offload.engine import c_gen as CG
from offload.engine import f2c
from offload.engine import gen as G
from offload.engine.catalog import semantic_atoms, slice_atoms
from offload.engine.grammar import GrammarError
from offload.engine.rules import (ProgramError, acc_rules, parse_program,
                              violations)

VERSION = 34
CSTD = "c11"


class AccCGenError(G.GenError):
    """An OpenACC C program that fails its own checks."""


OPENACC_H_STUB = """\
/* Declaration-only stub of openacc.h, for the base-language check only
   (gcc -std=c11 -pedantic-errors -fsyntax-only, without -fopenacc): the
   OpenACC 3.4 names the generated C programs use (3.4 chapter 3), so that
   the programs compile as C11 without any compiler's OpenACC header. Never
   linked, never run. */
#ifndef OPENACC_H_STUB
#define OPENACC_H_STUB
#include <stddef.h>
typedef enum acc_device_t {
  acc_device_none = 0, acc_device_default = 1, acc_device_host = 2,
  acc_device_not_host = 3, acc_device_nvidia = 4
} acc_device_t;
#define acc_async_noval (-1)
#define acc_async_sync (-2)
int acc_on_device(acc_device_t dev_type);
int acc_is_present(void *data_arg, size_t bytes);
acc_device_t acc_get_device_type(void);
int acc_get_device_num(acc_device_t dev_type);
void acc_set_device_num(int dev_num, acc_device_t dev_type);
int acc_get_num_devices(acc_device_t dev_type);
void acc_wait(int wait_arg);
int acc_async_test(int wait_arg);
#endif
"""


def gcc_check(source: str) -> tuple[bool, str]:
    """(ok, output) of ``gcc -std=c11 -pedantic-errors -fsyntax-only`` (no
    -fopenacc) on `source` with OPENACC_H_STUB as openacc.h."""
    with tempfile.TemporaryDirectory(prefix="accgen_") as d:
        Path(d, "openacc.h").write_text(OPENACC_H_STUB)
        src = Path(d, "prog.c")
        src.write_text(source)
        res = subprocess.run(
            ["gcc", f"-std={CSTD}", "-pedantic-errors", "-fsyntax-only",
             "-Wno-unknown-pragmas", "-I", d, str(src)],
            capture_output=True, text=True)
        return res.returncode == 0, (res.stdout + res.stderr).replace(
            d, "<tmp>")


def c_atoms() -> list[str]:
    return slice_atoms(VERSION, lang="c")


def c_pid(atom: str) -> str:
    return "acc34-c-" + atom.removeprefix("acc.").replace(".", "-")


# atom -> reason: no C program
UNGENERATABLE: dict[str, str] = {}
# rule id -> reason: a Fortran variant with no C variant
NO_VARIANT: dict[str, str] = {
    "ACC34-declare-placement-001": "a Fortran sentence ('In Fortran, the "
    "link clause must appear in a module declaration section, or the "
    "arguments must be common block names', 3.4 §2.13 p.82): the rule does "
    "not hold in C (rules.yaml lang f90)",
}


# --- hand ports -----------------------------------------------------------------------

_FRAME_HEAD = """\
#include <stdio.h>
#include <stdbool.h>
#include <stdlib.h>
#include <openacc.h>

enum { n = 64 };
"""

_DATA = """\
  for (int i = 1; i <= n; i++) {
    a[i - 1] = i;
    b[i - 1] = 0;
    ref[i - 1] = 2 * i + 1;
  }
  host_flag = 1;
"""

_RESULT = """\
  printf("RESULT ran_on_host=%d check=%s\\n", host_flag, ok ? "pass" : "fail");
"""


def _holder(detach: bool) -> str:
    """attach / detach of a pointer member: the Fortran program's
    allocatable component h%v is the C pointer member h.v (its target
    malloc'd); copyin(h.v[0:n]) is the subarray of the pointee (and, as
    copyin(h%v), attaches the device copy of h.v, 3.4 §2.7.2)."""
    mid = ("  #pragma acc enter data attach(h.v)\n" if not detach else "")
    post = ("  #pragma acc exit data detach(h.v)\n" if detach else "")
    return _FRAME_HEAD + """struct holder {
  int *v;
};

int main(void) {
  int a[n];
  int b[n];
  int ref[n];
  int host_flag;
  bool ok;
  struct holder h;
""" + _DATA + """  h.v = malloc(n * sizeof(int));
  for (int k = 0; k < n; k++)
    h.v[k] = 1;
  #pragma acc enter data copyin(h)
  #pragma acc enter data copyin(h.v[0:n])
""" + mid + """  #pragma acc parallel loop copyin(a) copyout(b) copy(host_flag) present(h)
  for (int i = 1; i <= n; i++) {
    if (i == 1) host_flag = (acc_on_device(acc_device_host) ? 1 : 0);
    b[i - 1] = 2 * a[i - 1] + h.v[i - 1];
  }
""" + post + """  #pragma acc exit data delete(h.v[0:n])
  #pragma acc exit data delete(h)
  ok = true;
  for (int k = 0; k < n; k++)
    ok = ok && (b[k] == ref[k]);
  free(h.v);
""" + _RESULT + """  return 0;
}
"""


def _seq(level: str = "") -> str:
    """seq: the recurrence c(k, j) = c(k - 1, j) + k over k in each column j
    (Fortran c(0:8, 8); C c[9][8], c[k][j - 1])."""
    return _FRAME_HEAD + """
int main(void) {
  int a[n];
  int b[n];
  int ref[n];
  int host_flag;
  bool ok;
  int c[9][8];
""" + _DATA + """  for (int k = 0; k < 9; k++)
    for (int j = 0; j < 8; j++)
      c[k][j] = 0;
  #pragma acc parallel loop copyin(a) copyout(b) copy(host_flag) copy(c)
  for (int i = 1; i <= n; i++) {
    if (i == 1) host_flag = (acc_on_device(acc_device_host) ? 1 : 0);
    b[i - 1] = 2 * a[i - 1] + 1;
  }
  #pragma acc parallel loop gang copy(c)
  for (int j = 1; j <= 8; j++) {
    #pragma acc loop seq""" + (f" {level}" if level else "") + """
    for (int k = 1; k <= 8; k++) {
      c[k][j - 1] = c[k - 1][j - 1] + k;
    }
  }
  ok = true;
  for (int k = 0; k < n; k++)
    ok = ok && (b[k] == ref[k]);
  for (int j = 0; j < 8; j++)
    ok = ok && (c[8][j] == 36);
  for (int k = 1; k <= 8; k++)
    ok = ok && (c[k][2] == k * (k + 1) / 2);
""" + _RESULT + """  return 0;
}
"""


# atom (or illegal rule id) -> (reason, C body: everything after the header)
HAND: dict[str, tuple[str, str]] = {
    "acc.clause.attach": (
        "an allocatable component (h%v) is a C pointer member; compliance."
        "f2c ports no allocatable component", _holder(False)),
    "acc.clause.detach": (
        "an allocatable component (h%v) is a C pointer member; compliance."
        "f2c ports no allocatable component", _holder(True)),
    "acc.clause.seq": (
        "the Fortran array c(0:8, 8) has a lower bound of 0 and the check "
        "an implied-do array constructor, which compliance.f2c does not "
        "port", _seq()),
    "ACC34-loop-clause-002": (
        "the hand port of the seq program with the Fortran variant's change "
        "(loop seq vector)", _seq("vector")),
}


# --- building -------------------------------------------------------------------------

def _c_header(f_source: str, pid: str, f_pid: str, note: str = "") -> str:
    """The Fortran program's header lines as C comments, with the C id,
    std and the first line naming the port."""
    lines = []
    for ln in f_source.splitlines():
        if not ln.startswith("! "):
            break
        lines.append("// " + ln[2:])
    src = "\n".join(lines) + "\n"
    first = ("// Generated by compliance.acc_c_gen (OpenACC 3.4, C11): the "
             f"C port (compliance.f2c) of {f_pid}. Do not edit.")
    if note:
        first = ("// Generated by compliance.acc_c_gen (OpenACC 3.4, C11): "
                 f"the hand-written C port of {f_pid}. Do not edit.")
    src = first + "\n" + src.split("\n", 1)[1]
    src = CG._set_header(src, "id", pid)
    src = CG._set_header(src, "std", CSTD)
    if note:
        src = CG._add_header(src, f"C: {note}")
    return src


_ATOMIC_SUM = re.compile(r"^(\s*)([A-Za-z_][\w\[\] +\-*]*?) = \2 \+ (.+);$")


def _atomic_compound(body: list[str]) -> tuple[list[str], bool]:
    """The statement after ``#pragma acc atomic [update]`` written
    ``x += expr`` where the port has ``x = x + e1 + e2``. Both are legal C
    forms of 3.4 §2.12: C parses the port's statement as ``(x + e1) + e2``,
    and "x binop expr must be mathematically equivalent to x binop (expr)",
    which it is for int ``+`` (the precedence and parentheses forms are
    sufficient, not necessary). The compound form is the slice's program;
    the port's form is kept as its own program (``BINOP``, id
    ``<pid>-binop``): nvc 25.11 failed on it with "invalid ILM atomic
    region"."""
    out, hit = list(body), False
    for k, line in enumerate(out[:-1]):
        if re.match(r"^\s*#pragma acc atomic(\s+update)?\s*$", line):
            m = _ATOMIC_SUM.match(out[k + 1])
            if m and re.search(r" [+-] ", m.group(3)):
                out[k + 1] = f"{m.group(1)}{m.group(2)} += {m.group(3)};"
                hit = True
    return out, hit


BINOP_SUFFIX = "-binop"


def _port(fprog: G.Program, pid: str, key: str, binop: bool = False) -> str:
    """The C source of `fprog`; `binop`: the port's atomic update as
    written (x = x + e1 + e2), without the compound rewrite."""
    if key in HAND:
        reason, body = HAND[key]
        return _c_header(fprog.source, pid, fprog.id, reason) + body
    try:
        src = f2c.translate(fprog.source, VERSION)
    except (f2c.TranslateError, GrammarError) as err:
        raise AccCGenError(f"{pid}: not ported: {err}") from err
    head = _c_header(fprog.source, pid, fprog.id)
    body = src.split("\n")
    k = 0
    while k < len(body) and body[k].startswith("// "):
        k += 1
    rest, hit = _atomic_compound(body[k:])
    if binop:
        if not hit:
            raise AccCGenError(f"{pid}: no atomic update x = x + e1 + e2")
        return CG._add_header(
            head, "C: the atomic update as the port writes it, x = x + e1 + "
            "e2 (C: (x + e1) + e2), legal by 3.4 §2.12: x binop expr is "
            "mathematically equivalent to x binop (expr) for int +; the "
            "companion of " + pid.removesuffix(BINOP_SUFFIX) + ", which "
            "writes x += expr") + "\n".join(body[k:])
    if hit:
        head = CG._add_header(head, "C: the atomic update is written x += "
                              "expr; the port's x = x + e1 + e2 is also a "
                              "legal 3.4 §2.12 form (mathematically "
                              "equivalent to x + (e1 + e2)) and is kept as "
                              f"{pid}{BINOP_SUFFIX}")
    return head + "\n".join(rest)


def has_binop(atom: str) -> bool:
    """Whether the legal program of `atom` has an atomic update the port
    writes x = x + e1 + e2 (so a ``-binop`` companion exists)."""
    if atom in HAND:
        return False
    src = f2c.translate(G._legal(atom, VERSION).source, VERSION)
    return _atomic_compound(src.split("\n"))[1]


def _parsed_atoms(source: str) -> frozenset:
    tree = parse_program(source, VERSION, lang="c")
    return frozenset().union(*(d.atoms for d in tree.directives),
                             *(d.atoms for d in tree.ends.values()))


def _finish(pid: str, atom: str, src: str, legal: bool = True,
            violates: str | None = None) -> G.Program:
    try:
        atoms = _parsed_atoms(src)
        found = violations(parse_program(src, VERSION, lang="c"), VERSION)
    except (GrammarError, ProgramError) as err:
        raise AccCGenError(f"{pid}: {err}\n{src}") from err
    if atom in semantic_atoms("acc"):
        atoms = atoms | {atom}
    if legal and atom not in atoms:
        raise AccCGenError(f"{pid}: the program does not exercise {atom}\n"
                           f"{src}")
    if legal and found:
        raise AccCGenError(f"{pid}: legal program violates {found}\n{src}")
    if not legal and found != [violates]:
        raise AccCGenError(f"{pid}: violates {found}, expected "
                           f"[{violates}]\n{src}")
    head = CG._meta(src)
    evidence = head["evidence"]
    unv = G._UNVERIFIED_LINE.findall(src)
    noo = G._NO_ORACLE_LINE.findall(src)
    if (evidence == "unverified") != bool(unv) or (
            evidence in G.NO_ORACLE) != bool(noo) or (
            evidence == "legality") != bool(G.legality_of(src)):
        raise AccCGenError(f"{pid}: evidence {evidence!r} and its header "
                           "lines disagree")
    needs = () if head["needs"] == "none" else tuple(
        x.strip() for x in head["needs"].split(","))
    expect = head.get("expect", "result").split()[0]
    prog = G.Program(pid, "c", src, atoms, atom, legal, violates,
                     not head["observable"].startswith("no"), CSTD, needs,
                     evidence, expect, head.get("token", ""), "acc",
                     G.scope_of(src)[0])
    G._check_scope(prog)
    return prog


@lru_cache(maxsize=None)
def acc_c_legal(atom: str) -> G.Program:
    """The C program of the OpenACC atom `atom`."""
    if atom in UNGENERATABLE:
        raise AccCGenError(f"{atom}: {UNGENERATABLE[atom]}")
    pid = c_pid(atom)
    fprog = G._legal(atom, VERSION)
    return _finish(pid, atom, _port(fprog, pid, atom))


@lru_cache(maxsize=None)
def acc_c_binop(atom: str) -> G.Program:
    """The companion of `atom`'s program with the port's atomic update
    form (x = x + e1 + e2), id ``<pid>-binop``."""
    pid = c_pid(atom) + BINOP_SUFFIX
    return _finish(pid, atom, _port(G._legal(atom, VERSION), pid, atom,
                                    binop=True))


def violation_ids() -> list[str]:
    """Rule ids with a C variant: the Fortran OpenACC variants whose rule
    holds in C."""
    langs = {r.id: r.lang for r in acc_rules()}
    return sorted(rid for rid in G.VIOLATION_BASE
                  if rid.startswith("ACC34-") and rid not in NO_VARIANT
                  and langs.get(rid) in ("both", "c"))


def base_atom(rid: str) -> str:
    stem = rid.split("-", 1)[1]
    return G.VARIANT_PRIMARY.get(stem, G.VIOLATION_BASE[rid][0])


@lru_cache(maxsize=None)
def acc_c_illegal(rid: str) -> G.Program:
    stem = rid.split("-", 1)[1]
    pid = f"acc34-c-illegal-{stem}"
    fprog = G._illegal(rid)
    src = _port(fprog, pid, rid)
    src = CG._set_header(src, "primary atom", base_atom(rid))
    return _finish(pid, base_atom(rid), src, legal=False, violates=rid)


def generate_acc_c(atoms: Iterable[str]) -> Iterator[G.Program]:
    """One legal C program per atom (sorted; UNGENERATABLE skipped; with its
    ``-binop`` companion where it has one), then the illegal variants whose base atom is among `atoms` (sorted by rule)."""
    wanted = sorted(set(atoms) - set(UNGENERATABLE))
    for atom in wanted:
        yield acc_c_legal(atom)
        if has_binop(atom):
            yield acc_c_binop(atom)
    for rid in violation_ids():
        if base_atom(rid) in wanted:
            yield acc_c_illegal(rid)


def all_acc_c_programs() -> list[G.Program]:
    return list(generate_acc_c(c_atoms()))
