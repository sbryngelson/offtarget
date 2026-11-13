"""The catalog widened toward real codes.

The grammar catalog (offload.engine.gen, c_gen, acc_gen) has one program per atom
of the offload slice. This module adds hand-written, self-checking programs,
built from the specs of ``offload.engine.widen_progs``, for what real codes use
and the catalog does not test: ``base.device.<feature>`` (a base-language
feature in device code), directives outside the slice, ``form.<model>.<name>``
and ``pair.<atom A>+<atom B>`` (an interaction; each part needs a program of
its own so a failing pair is attributable).
Ids are ``omp52-w-<slug>``, ``omp52-c-w-<slug>`` and ``acc34-w-<slug>``. The
output line is the catalog's and the header adds ``atoms:``, ``feature:`` and
``spec:``. ``static_problems`` checks legality without an offload compiler.
``elision`` builds the program without OpenMP/OpenACC and runs it on the host
for the expected value. Each spec's ``mutant`` names the edit that removes the
feature's effect; the mutant must fail the check (tools/campaigns/widen.py audit)."""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path

from offload.engine.gen import Program

from offload.engine.root import ROOT  # noqa: E402
GENERATOR = "offload.engine.widen"

# --- specs ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FSpec:
    """A Fortran program, rendered for OpenMP and/or OpenACC through the
    macros of ``expand``."""
    slug: str
    atom: str
    feature: str
    spec: str
    kernel: str
    ref: str = "2*i + 1"
    check: str = "all(b == ref)"
    decls: str = ""
    init: str = ""
    modules: str = ""
    contains: str = ""
    uses: str = ""
    models: tuple = ("omp", "acc")
    acc: dict = field(default_factory=dict)  # field overrides for OpenACC
    parts: tuple = ()
    mutant: tuple = ()          # ((old, new), ...) on the rendered program
    std: str = "f2008"
    elision: str = ""           # why elision does not apply ("" = applies)
    spec_acc: str = ""
    # why the oracle mutant fails only on a device ("" = it fails the
    # check in sequential elision too): a race, or copy semantics
    mutant_device: str = ""

    def for_model(self, model: str) -> "FSpec":
        if model == "acc" and self.acc:
            return replace(self, **self.acc)
        return self


@dataclass(frozen=True)
class CSpec:
    """A C OpenMP program: the full body after the header (includes,
    helpers and main)."""
    slug: str
    atom: str
    feature: str
    spec: str
    body: str
    parts: tuple = ()
    mutant: tuple = ()
    elision: str = ""
    mutant_device: str = ""


# --- the Fortran macros --------------------------------------------------------------

_ACC_DATA = {"to": "copyin", "from": "copyout", "tofrom": "copy",
             "alloc": "create", "present": "present", "delete": "delete"}
_CLAUSE = re.compile(r"(\w+)\(((?:[^()]|\([^()]*\))*)\)|(\w+)")


def _clauses(text: str) -> list[tuple[str, str]]:
    out = []
    for m in _CLAUSE.finditer(text):
        if m.group(1):
            out.append((m.group(1), m.group(2).strip()))
        else:
            out.append((m.group(3), ""))
    return out


def _fmt_clause(name: str, arg: str) -> str:
    if not arg:
        return name
    if name in ("reduction",) and ":" in arg:
        op, items = arg.split(":", 1)
        return f"{name}({op.strip()}: {items.strip()})"
    return f"{name}({arg})"


def _data_clauses(clauses, model: str) -> list[str]:
    out = []
    for name, arg in clauses:
        if name in _ACC_DATA:
            if model == "omp":
                if name == "present":
                    continue
                out.append(f"map({name}: {arg})")
            else:
                out.append(f"{_ACC_DATA[name]}({arg})")
        else:
            out.append(_fmt_clause(name, arg))
    return out


def _directive(indent: str, sentinel: str, head: str, clauses) -> list[str]:
    """One directive line, continued (`&` / `!$omp&`) past 96 columns."""
    lines, cur = [], f"{indent}{sentinel} {head}"
    for c in clauses:
        if len(cur) + 1 + len(c) > 96:
            lines.append(cur + " &")
            cur = f"{indent}{sentinel}& {c}"
        else:
            cur += " " + c
    lines.append(cur)
    return lines


def expand(text: str, model: str) -> str:
    """The Fortran macros of a spec, for `model` (omp | acc):

    ``@PLOOP <clauses>`` / ``@END_PLOOP``: omp ``target teams distribute
    parallel do`` (to/from/tofrom/alloc -> map, present dropped) / acc
    ``parallel loop`` (copyin/copyout/copy/create/present); ``@REGION`` /
    ``@END_REGION``: omp ``target`` / acc ``serial``; ``@ROUTINE``:
    ``declare target`` / ``routine seq``; ``@DECLVAR(x)``: ``declare
    target(x)`` / ``declare create(x)``; ``@UPD_TO(x)``, ``@UPD_FROM(x)``:
    ``target update to/from`` / ``update device/self``; ``@ENTER``,
    ``@EXIT``: ``target enter/exit data`` / ``enter/exit data``; ``@USE``:
    the runtime module; ``@ATOMIC``: ``atomic`` / ``atomic update``;
    ``@DATA`` / ``@END_DATA``: ``target data`` / ``data``; inline
    ``@HOSTFLAG[var]``: ``var = merge(1, 0,
    omp_is_initial_device())`` / ``acc_on_device(acc_device_host)``."""
    sent = "!$omp" if model == "omp" else "!$acc"
    out = []
    for line in text.splitlines():
        s = line.strip()
        ind = line[:len(line) - len(line.lstrip())]
        if s.startswith("@") and not s.startswith("@HOSTFLAG"):
            m = re.match(r"@(\w+)(?:\((.*)\))?\s*(.*)$", s)
            mac, arg, rest = m.group(1), m.group(2), m.group(3)
            cl = _clauses(rest)
            if mac == "PLOOP":
                head = "target teams distribute parallel do" \
                    if model == "omp" else "parallel loop"
                out += _directive(ind, sent, head, _data_clauses(cl, model))
            elif mac == "END_PLOOP":
                if model == "omp":
                    out.append(f"{ind}!$omp end target teams distribute "
                               "parallel do")
            elif mac == "REGION":
                head = "target" if model == "omp" else "serial"
                out += _directive(ind, sent, head, _data_clauses(cl, model))
            elif mac == "END_REGION":
                out.append(f"{ind}{sent} end " + ("target" if model == "omp"
                                                  else "serial"))
            elif mac == "ROUTINE":
                out.append(f"{ind}{sent} " + ("declare target"
                                              if model == "omp"
                                              else "routine seq"))
            elif mac == "DECLVAR":
                out.append(f"{ind}{sent} " + (f"declare target({arg})"
                                              if model == "omp" else
                                              f"declare create({arg})"))
            elif mac == "UPD_TO":
                out.append(f"{ind}{sent} " + (f"target update to({arg})"
                                              if model == "omp" else
                                              f"update device({arg})"))
            elif mac == "UPD_FROM":
                out.append(f"{ind}{sent} " + (f"target update from({arg})"
                                              if model == "omp" else
                                              f"update self({arg})"))
            elif mac in ("ENTER", "EXIT"):
                if model == "omp":
                    head = "target enter data" if mac == "ENTER" else \
                        "target exit data"
                    cls = [f"map({n}: {a})" for n, a in cl]
                else:
                    head = "enter data" if mac == "ENTER" else "exit data"
                    cls = [f"{_ACC_DATA[n]}({a})" for n, a in cl]
                out += _directive(ind, sent, head, cls)
            elif mac == "ATOMIC":
                out.append(f"{ind}{sent} " + ("atomic" if model == "omp"
                                              else "atomic update"))
            elif mac == "DATA":
                if model == "omp":
                    out += _directive(ind, sent, "target data",
                                      [f"map({n}: {a})" for n, a in cl])
                else:
                    out += _directive(ind, sent, "data",
                                      [f"{_ACC_DATA[n]}({a})" for n, a in cl])
            elif mac == "END_DATA":
                out.append(f"{ind}{sent} end " + ("target data"
                                                  if model == "omp"
                                                  else "data"))
            elif mac == "USE":
                out.append(ind + ("use omp_lib, only: omp_is_initial_device"
                                  if model == "omp" else
                                  "use openacc, only: acc_device_host, "
                                  "acc_on_device"))
            else:
                raise ValueError(f"unknown macro {s!r}")
            continue
        out.append(line)
    text = "\n".join(out)
    probe = "omp_is_initial_device()" if model == "omp" else \
        "acc_on_device(acc_device_host)"
    return re.sub(r"@HOSTFLAG(?:\[(\w+)\])?",
                  lambda m: f"{m.group(1) or 'host_flag'} = merge(1, 0, "
                  f"{probe})", text)


F_FRAME = """\
{modules}program wide_prog
  @USE
{uses}  implicit none
  integer, parameter :: n = 64
  integer :: a(n), b(n), ref(n)
{decls}  integer :: i, host_flag
  logical :: ok
  do i = 1, n
    a(i) = i
    b(i) = 0
    ref(i) = {ref}
  end do
{init}  host_flag = 1
{kernel}  ok = {check}
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
{contains}end program wide_prog
"""


def _block(text: str) -> str:
    text = text.strip("\n")
    return text + "\n" if text else ""


def render_f(spec: FSpec, model: str) -> str:
    s = spec.for_model(model)
    body = F_FRAME.format(
        modules=_block(s.modules) + ("\n" if s.modules.strip() else ""),
        uses=_block(s.uses), decls=_block(s.decls), ref=s.ref,
        init=_block(s.init), kernel=_block(s.kernel), check=s.check,
        contains=("contains\n" + _block(s.contains)) if s.contains.strip()
        else "")
    return expand(body, model)


# --- ids, headers, programs ---------------------------------------------------------

VERSION = {"omp": 52, "acc": 34}


def pid_of(slug: str, lang: str, model: str) -> str:
    v = VERSION[model]
    return f"{model}{v}-" + ("c-" if lang == "c" else "") + f"w-{slug}"


def _header(pid: str, spec, model: str, lang: str, std: str) -> list[str]:
    name = ("OpenMP 5.2" if model == "omp" else "OpenACC 3.4") + (
        ", C11" if lang == "c" else ", free-form Fortran")
    where = ("inside the target region of interest" if model == "omp"
             else "inside the compute region of interest (acc_on_device)")
    atoms = [spec.atom] + list(spec.parts)
    lines = [f"Generated by {GENERATOR} ({name}; catalog widening)."
             " Do not edit.",
             f"id: {pid}", f"primary atom: {spec.atom}",
             "atoms: " + ", ".join(atoms),
             "legal: yes", "observable: yes", f"ran_on_host: {where}",
             "evidence: construct", "needs: none", f"std: {std}",
             f"feature: {spec.feature}"]
    cite = spec.spec_acc if (model == "acc" and getattr(spec, "spec_acc", ""))\
        else spec.spec
    lines.append(f"spec: {cite}")
    if spec.parts:
        lines.append("pair of: " + " + ".join(spec.parts) +
                     " (each has a program of its own)")
    if spec.elision:
        lines.append(f"elision: not applicable ({spec.elision})")
    return lines


def _apply(source: str, edits) -> str:
    for old, new in edits:
        if source.count(old) < 1:
            raise ValueError(f"mutant edit not found: {old!r}")
        source = source.replace(old, new)
    return source


@dataclass(frozen=True)
class Wide:
    """A widened program and what tools/campaigns/widen.py needs besides the
    Program: its spec, the oracle mutant's source, the elision note."""
    program: Program
    spec: object
    mutant_source: str | None
    elision: str = ""

    @property
    def id(self) -> str:
        return self.program.id


def _parsed_atoms(source: str, lang: str, model: str) -> frozenset:
    from offload.engine import program_source as S
    name = "p.c" if lang == "c" else "p.f90"
    prog = S.from_texts([(name, source)], VERSION[model])
    return frozenset(a for o in prog.occurrences for a in o.atoms)


def _make(spec, lang: str, model: str) -> Wide:
    pid = pid_of(spec.slug, lang, model)
    std = "c11" if lang == "c" else spec.for_model(model).std
    head = _header(pid, spec, model, lang, std)
    if lang == "c":
        body = spec.body.strip("\n") + "\n"
        source = "".join(f"// {h}\n" for h in head) + body
        edits = spec.mutant
    else:
        s = spec.for_model(model)
        body = render_f(spec, model)
        source = "".join(f"! {h}\n" for h in head) + body
        edits = s.mutant
    mutant = None
    if edits:
        mutant = _apply(source, edits)
        mark = "// " if lang == "c" else "! "
        mutant = mutant.replace(f"{mark}id: {pid}\n",
                                f"{mark}id: {pid}-mutant\n{mark}MUTANT of "
                                f"{pid}: the feature's effect removed\n", 1)
    atoms = _parsed_atoms(source, lang, model) | {spec.atom} | set(
        spec.parts)
    prog = Program(pid, "c" if lang == "c" else "fortran", source,
                   frozenset(atoms), spec.atom, True, None, True, std, (),
                   "construct", "result", "", model, "device")
    return Wide(prog, spec, mutant, spec.elision)


@lru_cache(maxsize=None)
def all_wide() -> tuple:
    from offload.engine import widen_progs as WP
    out = []
    for s in WP.F_SPECS:
        for m in s.models:
            out.append(_make(s, "f90", m))
    for s in WP.C_SPECS:
        out.append(_make(s, "c", "omp"))
    ids = [w.id for w in out]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise ValueError(f"duplicate widened program ids: {sorted(dup)}")
    return tuple(out)


def programs(lang: str | None = None, model: str | None = None
             ) -> list[Program]:
    return [w.program for w in all_wide()
            if (lang is None or (w.program.lang == "c") == (lang == "c"))
            and (model is None or w.program.model == model)]


@lru_cache(maxsize=None)
def by_id() -> dict:
    return {w.id: w for w in all_wide()}


def program(pid: str) -> Program | None:
    w = by_id().get(pid)
    return w.program if w else None


def is_wide(pid: str) -> bool:
    return bool(re.match(r"(?:omp|acc)\d\d-(?:c-)?w-", pid or ""))


def kind_of(atom: str) -> str:
    """base | directive | form | pair"""
    if atom.startswith("pair."):
        return "pair"
    if atom.startswith("base."):
        return "base"
    if atom.startswith("form."):
        return "form"
    return "directive"


def pair_parts(atom: str) -> tuple[str, str]:
    a, b = atom.removeprefix("pair.").split("+", 1)
    return a, b


# --- static checks (legality, as the catalog generators check theirs) -------------

STD_FLAGS = {"f2008": "-std=f2008", "f2018": "-std=f2018"}


@lru_cache(maxsize=None)
def _stub_dir() -> str:
    from offload.engine.acc_gen import OPENACC_STUB
    d = tempfile.mkdtemp(prefix="widen_stub_")
    (Path(d) / "omp_lib_stub.f90").write_text(OMP_STUB)
    (Path(d) / "openacc_stub.f90").write_text(OPENACC_STUB)
    for f in ("omp_lib_stub.f90", "openacc_stub.f90"):
        subprocess.run([_gfortran(), "-std=f2008", "-fsyntax-only", f],
                       cwd=d, check=True, capture_output=True, timeout=120)
    return d


def _gfortran() -> str:
    return shutil.which("gfortran") or "/usr/tce/bin/gfortran"


def _gcc() -> str:
    return shutil.which("gcc") or "/usr/bin/gcc"


def gfortran_check(source: str, std: str = "f2008") -> str | None:
    with tempfile.TemporaryDirectory(prefix="widen_gf_") as d:
        (Path(d) / "t.f90").write_text(source)
        r = subprocess.run([_gfortran(), STD_FLAGS.get(std, f"-std={std}"),
                            "-fsyntax-only", f"-I{_stub_dir()}", "-J", d,
                            "t.f90"], cwd=d, capture_output=True, text=True,
                           timeout=120)
    if r.returncode == 0:
        return None
    errs = [ln for ln in r.stderr.splitlines() if "Error" in ln]
    return (errs[0] if errs else r.stderr.strip()[:300]) or \
        f"rc={r.returncode}"


def gcc_check(source: str) -> str | None:
    with tempfile.TemporaryDirectory(prefix="widen_gcc_") as d:
        (Path(d) / "t.c").write_text(source)
        r = subprocess.run([_gcc(), "-std=c11", "-fsyntax-only",
                            "-Wno-unknown-pragmas", "t.c"], cwd=d,
                           capture_output=True, text=True, timeout=120)
    if r.returncode == 0:
        return None
    errs = [ln for ln in r.stderr.splitlines() if "error" in ln]
    return (errs[0] if errs else r.stderr[:300]).strip()


def rule_problems(prog: Program) -> list[str]:
    """The catalog's restriction rules (offload.engine.rules) and the offload
    scope (offload.engine.offload_scope.check)."""
    from offload.engine.grammar import GrammarError
    from offload.engine.offload_scope import ScopeError, check
    from offload.engine.rules import ProgramError, parse_program, violations
    out = []
    lang = "c" if prog.lang == "c" else "f90"
    v = VERSION[prog.model]
    try:
        check(prog)
    except ScopeError as e:
        out.append(f"scope: {e}")
    except (GrammarError, ProgramError) as e:
        out.append(f"scope: cannot read: {e}")
    try:
        found = violations(parse_program(prog.source, v, lang), v)
        if found:
            out.append("rules: " + ", ".join(found))
    except (GrammarError, ProgramError) as e:
        out.append(f"rules: cannot read: {str(e).splitlines()[0]}")
    return out


def static_problems(prog: Program) -> list[str]:
    """Everything that makes a widened program not legal by the checkers
    ([] = legal): the scope, the rules, the base language."""
    out = rule_problems(prog)
    base = gcc_check(prog.source) if prog.lang == "c" else \
        gfortran_check(prog.source, prog.std)
    if base:
        out.append(f"base language: {base}")
    return out


# --- sequential elision (the expected value's second source) -------------------------

OMP_STUB = """\
! Declaration-only omp_lib stub for the base-language check of the
! widened programs (offload.engine.widen); never linked.
module omp_lib
  implicit none
  integer, parameter :: omp_allocator_handle_kind = 8
  integer(omp_allocator_handle_kind), parameter :: omp_default_mem_alloc = 1
  integer(omp_allocator_handle_kind), parameter :: omp_const_mem_alloc = 3
  integer, parameter :: omp_sync_hint_kind = 4
  integer(omp_sync_hint_kind), parameter :: omp_sync_hint_none = 0
  integer(omp_sync_hint_kind), parameter :: omp_sync_hint_contended = 2
  interface
    logical function omp_is_initial_device()
    end function omp_is_initial_device
    integer function omp_get_thread_num()
    end function omp_get_thread_num
    integer function omp_get_num_threads()
    end function omp_get_num_threads
    integer function omp_get_team_num()
    end function omp_get_team_num
  end interface
end module omp_lib
"""

OMP_ELISION = """\
! Sequential omp_lib for the elision of the widened programs: one initial
! thread on the host, no devices (OpenMP 5.2 §18). Built without -fopenmp.
module omp_lib
  implicit none
  integer, parameter :: omp_allocator_handle_kind = 8
  integer(omp_allocator_handle_kind), parameter :: omp_default_mem_alloc = 1
  integer(omp_allocator_handle_kind), parameter :: omp_const_mem_alloc = 3
  integer, parameter :: omp_sync_hint_kind = 4
  integer(omp_sync_hint_kind), parameter :: omp_sync_hint_none = 0
  integer(omp_sync_hint_kind), parameter :: omp_sync_hint_contended = 2
contains
  logical function omp_is_initial_device()
    omp_is_initial_device = .true.
  end function omp_is_initial_device
  integer function omp_get_thread_num()
    omp_get_thread_num = 0
  end function omp_get_thread_num
  integer function omp_get_num_threads()
    omp_get_num_threads = 1
  end function omp_get_num_threads
  integer function omp_get_team_num()
    omp_get_team_num = 0
  end function omp_get_team_num
end module omp_lib
"""

ACC_ELISION = """\
! Sequential openacc module for the elision of the widened programs: the
! host is the only device (OpenACC 3.4 §3.2.17). Built without -fopenacc.
module openacc
  implicit none
  integer, parameter :: acc_device_kind = 4
  integer(acc_device_kind), parameter :: acc_device_host = 2
contains
  logical function acc_on_device(dev_type)
    integer(acc_device_kind), value :: dev_type
    acc_on_device = dev_type == acc_device_host
  end function acc_on_device
end module openacc
"""

C_ELISION = """\
/* Sequential OpenMP runtime for the elision of the widened C programs:
   one initial thread on the host, no devices. Built without -fopenmp. */
int omp_is_initial_device(void) { return 1; }
int omp_get_thread_num(void) { return 0; }
int omp_get_num_threads(void) { return 1; }
int omp_get_team_num(void) { return 0; }
"""

ELISION_COMPILERS = {"f90": ("gfortran", "amdflang"),
                     "c": ("gcc", "amdclang")}


def _amd_bin() -> str:
    from offload.engine.toolchains import AFAR_BIN
    return AFAR_BIN


def _value(stdout: str) -> str | None:
    from offload.engine.expected import value_of
    return value_of(stdout)


def run_elided(prog: Program, compiler: str, timeout: int = 60
               ) -> tuple[str | None, str]:
    """(value, note): `prog` built by `compiler` without OpenMP/OpenACC
    against the sequential stubs, run on the host."""
    lang = "c" if prog.lang == "c" else "f90"
    with tempfile.TemporaryDirectory(prefix="widen_elided_") as d:
        dd = Path(d)
        exe = str(dd / "p.out")
        if lang == "c":
            (dd / "p.c").write_text(prog.source)
            (dd / "rt.c").write_text(C_ELISION)
            cc = _gcc() if compiler == "gcc" else f"{_amd_bin()}/amdclang"
            cmd = [cc, "-O0", "-std=c11", "-Wno-unknown-pragmas",
                   "-I" + str(_omp_h_dir()), "p.c", "rt.c", "-lm", "-o",
                   exe]
        else:
            (dd / "p.f90").write_text(prog.source)
            (dd / "rt.f90").write_text(OMP_ELISION if prog.model == "omp"
                                       else ACC_ELISION)
            if compiler == "gfortran":
                cmd = [_gfortran(), "-O0", "-J", d, "rt.f90", "p.f90", "-o",
                       exe]
            else:
                cmd = [f"{_amd_bin()}/amdflang", "-O0", "-module-dir", d,
                       "rt.f90", "p.f90",
                       "-L/usr/lib/gcc/x86_64-redhat-linux/8", "-o", exe]
        b = subprocess.run(cmd, cwd=d, capture_output=True, text=True,
                           timeout=300)
        if b.returncode != 0:
            err = [ln for ln in (b.stderr + b.stdout).splitlines()
                   if "rror" in ln]
            return None, f"{compiler} build failed: " + (
                err[0] if err else f"rc={b.returncode}")[:200]
        try:
            r = subprocess.run(["bash", "-c", 'ulimit -c 0; exec "$0"', exe],
                               cwd=d, capture_output=True, text=True,
                               timeout=timeout,
                               env={"PATH": "/usr/bin:/bin"})
        except subprocess.TimeoutExpired:
            return None, f"{compiler} run timed out"
        if r.returncode != 0:
            return None, f"{compiler} run failed: rc={r.returncode}"
        v = _value(r.stdout)
        return (v, "") if v else (None, f"{compiler}: no single RESULT line")


@lru_cache(maxsize=None)
def _omp_h_dir() -> Path:
    """A directory with a declaration-only omp.h (the elided C build must
    not depend on any OpenMP implementation's header)."""
    d = Path(tempfile.mkdtemp(prefix="widen_omph_"))
    (d / "omp.h").write_text(
        "#ifndef WIDEN_OMP_H\n#define WIDEN_OMP_H\n"
        "typedef unsigned long omp_allocator_handle_t;\n"
        "#define omp_default_mem_alloc ((omp_allocator_handle_t)1)\n"
        "#define omp_const_mem_alloc ((omp_allocator_handle_t)3)\n"
        "int omp_is_initial_device(void);\nint omp_get_thread_num(void);\n"
        "int omp_get_num_threads(void);\nint omp_get_team_num(void);\n"
        "#endif\n")
    return d


def elision(w: Wide) -> dict:
    """The elision Evidence of a widened program (as a dict, the stored
    record's ``elision`` field: offload.engine.expected.Evidence.to_dict)."""
    from offload.engine.expected import Evidence
    if w.elision:
        return Evidence("elision", "inapplicable",
                        detail=w.elision).to_dict()
    lang = "c" if w.program.lang == "c" else "f90"
    obs, notes = [], []
    for c in ELISION_COMPILERS[lang]:
        v, note = run_elided(w.program, c)
        obs.append((c, v))
        if note:
            notes.append(note)
    vals = sorted({v for _, v in obs if v is not None})
    if len(vals) == 1 and all(v is not None for _, v in obs):
        ev = Evidence("elision", "value", vals[0], "; ".join(notes),
                      tuple(obs))
    elif len(vals) > 1:
        ev = Evidence("elision", "conflict", None, "the elided builds "
                      "disagree", tuple(obs))
    else:
        ev = Evidence("elision", "no_value", None, "; ".join(notes) or
                      "no value", tuple(obs))
    return ev.to_dict()
