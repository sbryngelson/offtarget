"""Program generator for the slice: legal and illegal free-form Fortran.

``generate(atoms, version)`` yields, for each atom, one small deterministic
self-checking legal program with that atom as ``primary_atom`` (built from
``offload.engine.gen_templates``), then one illegal variant for each rule in
``VIOLATIONS`` whose base atom is in ``atoms``. Each program must parse,
contain its primary atom, and have ``violations`` equal to ``[]`` (legal) or
``[violates]`` (illegal), else ``GenError``. ``UNGENERATABLE`` lists atoms
without a program.
Each program prints one line ``RESULT ran_on_host=<0|1> check=<pass|fail>``
and exits 0. ``ran_on_host`` comes from ``omp_is_initial_device()`` in the
target region, or from a probe region that sets ``on_dev``. ``NEEDS``,
``EVIDENCE``, ``NO_ORACLE`` and ``UNVERIFIED`` define the header markers.
Version 34 uses ``offload.engine.acc_gen``; version 50 uses the 5.2 recipes
(exceptions in ``NO_VARIANT_50``)."""
from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterable, Iterator

import yaml

from offload.engine import gen_templates as T
from offload.engine.catalog import (MODEL_NAME, catalog_dir, default_skeleton,
                                directive_atom, model_of, semantic_atoms,
                                slice_atoms, slice_directives)
from offload.engine.grammar import GrammarError, parse_directive
from offload.engine.offload_scope import ScopeError, scope_of
from offload.engine.offload_scope import check as check_scope
from offload.engine.rules import (RULE_PREFIX, ProgramError, default_rules,
                              leaves, parse_program, rules_for, violations)

STD_LEVELS = ("f95", "f2003", "f2008", "f2018")


class GenError(Exception):
    """An atom without a recipe, or a program that fails its own checks."""


@dataclass(frozen=True)
class Program:
    id: str
    lang: str
    source: str
    atoms: frozenset
    primary_atom: str
    legal: bool
    violates: str | None
    observable: bool
    std: str = "f2008"
    needs: tuple = ()
    evidence: str = "construct"
    expect: str = "result"
    token: str = ""
    model: str = "omp"  # "acc": an OpenACC program
    # "device" (the atom's headline program) or "host+device" (a
    # host construct feeding a target region the way people use it,
    # reported apart and judged on the device result;
    # offload.engine.offload_scope)
    scope: str = "device"


# The message text of the compile-output probes (the error directive's
# message clause); the harness looks for it in the
# compiler's output.
PROBE_TOKEN = "COMPLIANCE_PROBE_MESSAGE"


# Program.expect: how a correct run ends. "result": exit 0 with
# the RESULT line (the output contract above). "error_termination": a
# negative probe; the program uses the atom where the spec requires runtime
# error termination, so a correct run ends there with the runtime's error
# message (offload.engine.harness.ERROR_TERMINATION); reaching the end prints
# RESULT ... check=fail.
EXPECT = {
    "result": "exit status 0 with one RESULT line",
    "error_termination": "runtime error termination with the toolchain's "
                         "error message before the RESULT line (a negative "
                         "probe; continuing prints check=fail)",
    # compile-output probes: an error directive with
    # at(compilation) and message(PROBE_TOKEN)
    "compile_message": "the compile succeeds and its output shows the "
                       "token as a warning; then the program runs as for "
                       "result",
    "compile_error": "the compile stops with the token as an error "
                     "(compile-time error termination); nothing runs",
}


# Program.evidence: how the program shows that the construct of interest
# worked on the device.
EVIDENCE = {
    "construct": "the check depends on the construct and on its own device "
                 "execution (a no-op or host fallback of the construct fails "
                 "it or reports ran_on_host=1)",
    "probe": "a negative probe: the program uses the atom where "
             "the spec requires runtime error termination (expect="
             "\"error_termination\"), so the run must end there with the "
             "runtime's error message; without the atom it continues and "
             "prints check=fail; or a compile-output probe (expect "
             "compile_message/compile_error): the compiler output must show "
             "the error directive's message, or the compile must stop",
    "copy_mode_only": "the check tells a working construct from a no-op only "
                      "in copy mode (HSA_XNACK=0): under unified memory host "
                      "and device addresses coincide",
    # (owner agreement): "unverified" only where a deterministic
    # oracle is possible and missing; the forms no run can separate carry
    # their NO_ORACLE category instead
    "hint_only": "no oracle can exist: the spec lets an implementation "
                 "ignore the form (a hint, an assertion the program makes, "
                 "or a bound that one-at-a-time execution meets), so a "
                 "conforming run without it can coincide; reported as "
                 "'accepted; conforms vacuously'",
    "implementation_defined": "no oracle can exist: the spec leaves the "
                              "behaviour to the implementation (or permits "
                              "but does not require it), so a conforming "
                              "run without the form can coincide; reported "
                              "as 'implementation-defined'",
    "equivalent_default": "no oracle can exist: by the spec the form is the "
                          "behaviour without it (a default modifier, "
                          "argument, category or binding); reported as "
                          "'equivalent to the default (no separable "
                          "effect)'",
    "legality": "the atom's only effect is a compile-time restriction: its "
                "oracle is the illegal variant the header names (a compiler "
                "must reject it); the legal program's run is no evidence",
    "unverified": "a deterministic oracle for behaviour the spec fixes is "
                  "possible but the program has none (the header says what "
                  "is missing)",
}
# The evidence categories with no separating oracle, each with
# its spec basis (catalog/omp/no_oracle.yaml): header lines
# ``! no oracle (<kind>): <reason>`` and ``! basis: <cite>: "<quote>"``.
NO_ORACLE = ("hint_only", "implementation_defined", "equivalent_default")
# Evidence levels the oracle mutation audit covers (offload.engine.mutate).
AUDITED = ("construct", "copy_mode_only", "probe")
# Why a program is evidence="unverified": the header line
# ``! unverified (<kind>): <reason>`` (exactly one, only on such programs;
# offload.engine.mutate.audit_summary reports it as unverified_<kind>).
UNVERIFIED = {
    "needs_other_infrastructure": "the effect is observable only by means "
                                  "outside the program's own result (a tool "
                                  "interface such as OMPT, or a feature "
                                  "neither toolchain provides)",
    # The spec fixes the behaviour and a single-run check of it is
    # possible, but this program does not have it (the reason says which)
    "oracle_not_written": "the spec fixes the behaviour and a deterministic "
                          "check of it is possible, but the program does "
                          "not have it yet (the reason names the check)",
}
# header lines: ``! `` in Fortran, ``// `` in C
_UNVERIFIED_LINE = re.compile(r"^(?:!|//) unverified \((\w+)\): (.+)$",
                              re.M)
_NO_ORACLE_LINE = re.compile(r"^(?:!|//) no oracle \((\w+)\): (.+)$", re.M)
_BASIS_LINE = re.compile(r"^(?:!|//) basis: (.+)$", re.M)
_LEGALITY_LINE = re.compile(r"^(?:!|//) legality oracle: (\S+)$", re.M)
from offload.engine.root import ROOT  # noqa: E402

NO_ORACLE_YAML = ROOT / "catalog" / "omp" / "no_oracle.yaml"


# Hand derivations of expected results (the `derivation` source
# of offload.engine.expected), written into the legal program's header
DERIVATIONS = ROOT / "catalog" / "omp" / "derivations.yaml"


@lru_cache(maxsize=None)
def derivations() -> dict:
    """(atom, version) -> (value, text with the version's citations)."""
    import yaml
    if not DERIVATIONS.is_file():
        return {}
    doc = yaml.safe_load(DERIVATIONS.read_text())
    cites = doc.get("cites", {})
    out = {}
    for e in doc["entries"]:
        for v in e["versions"]:
            text = re.sub(r"\{cite:(\w+)\}",
                          lambda m: cites[m.group(1)][v], e["text"])
            if (e["atom"], v) in out:
                raise ValueError(f"two derivations of {e['atom']} at {v}")
            out[(e["atom"], v)] = (e["value"], text)
    return out


def with_derivation(prog: Program, atom: str, version: int) -> Program:
    """The legal program with its hand derivation (catalog/omp/
    derivations.yaml) as the last header line ``! derivation (<value>):
    <text>``. Added only to the programs `generate` returns: the illegal
    variants, the host+device patterns and the C ports are derived from
    ``_legal`` (no derivation), so their text transforms never see it."""
    d = derivations().get((atom, version))
    if d is None or not prog.legal:
        return prog
    lines = prog.source.split("\n")
    k = 0
    while k < len(lines) and lines[k].startswith("!"):
        k += 1
    lines.insert(k, f"! derivation ({d[0]}): {d[1]}")
    return dataclasses.replace(prog, source="\n".join(lines))


@lru_cache(maxsize=None)
def no_oracle_bases(model: str = "omp") -> dict:
    """catalog/<model>/no_oracle.yaml: basis id -> {version: [{cite,
    quote}]}."""
    path = NO_ORACLE_YAML if model == "omp" else \
        catalog_dir(model) / "no_oracle.yaml"
    data = yaml.safe_load(path.read_text()) or {}
    out = {}
    for bid, e in (data.get("bases") or {}).items():
        out[bid] = {int(v): list(c) for v, c in e.items() if v != "status"}
    return out


def basis_text(basis: str, version: int) -> str:
    """The ``! basis:`` text of a basis id at a version: the first
    citation and its quoted sentence."""
    model = model_of(version)
    cites = no_oracle_bases(model).get(basis, {}).get(version)
    if not cites:
        raise GenError(f"no spec basis {basis!r} at {version} in "
                       f"catalog/{model}/no_oracle.yaml")
    return f'{cites[0]["cite"]}: "{cites[0]["quote"]}"'


def unverified_of(source: str) -> tuple[str, str] | None:
    """(kind, reason) of the program's ``! unverified (<kind>): <reason>``
    header line, or None."""
    m = _UNVERIFIED_LINE.search(source)
    return (m.group(1), m.group(2)) if m else None


def no_oracle_of(source: str) -> tuple[str, str, str] | None:
    """(kind, reason, basis) of a program with no separating oracle (its
    ``! no oracle (<kind>): <reason>`` and ``! basis: ...`` header lines),
    or None."""
    m = _NO_ORACLE_LINE.search(source)
    if m is None:
        return None
    b = _BASIS_LINE.search(source)
    return m.group(1), m.group(2), b.group(1) if b else ""


def legality_of(source: str) -> str | None:
    """The rule id of a legality program's ``! legality oracle:`` line."""
    m = _LEGALITY_LINE.search(source)
    return m.group(1) if m else None


# Program.needs: run-time requirements beyond a plain offload device.
NEEDS = {
    "zero_copy": "memory the device can access (unified shared memory, "
                 "HSA_XNACK=1); in copy mode the runtime aborts or reports "
                 "an unsupported requirement",
    "device_c_f_pointer": "c_f_pointer callable in device code (CCE 19 "
                          "fails to link _C_F_POINTER for the GPU)",
}


# --- atoms without a program -------------------------------------------------------

UNGENERATABLE: dict[int, dict[str, str]] = {50: {}, 52: {}, 60: {}, 34: {}}

# --- the omp_lib stub for the base-language check ----------------------------------

OMP_LIB_STUB = """\
! Declaration-only stub of omp_lib, for the base-language check only
! (gfortran -std=<level> -fsyntax-only, without -fopenmp): it declares the
! OpenMP names the generated programs use, with the kinds, types and
! interfaces of the OpenMP 5.2/6.0 Fortran API, so that `use omp_lib, only:`
! resolves without any compiler's OpenMP module. Never linked, never run.
module omp_lib
  use, intrinsic :: iso_c_binding, only: c_ptr, c_int
  implicit none
  integer, parameter :: omp_allocator_handle_kind = 8
  integer, parameter :: omp_memspace_handle_kind = 8
  integer, parameter :: omp_alloctrait_key_kind = 8
  integer, parameter :: omp_alloctrait_val_kind = 8
  integer, parameter :: omp_depend_kind = 16
  integer, parameter :: omp_impex_kind = 4
  type omp_alloctrait
    integer(omp_alloctrait_key_kind) :: key
    integer(omp_alloctrait_val_kind) :: value
  end type omp_alloctrait
  integer(omp_alloctrait_key_kind), parameter :: omp_atk_alignment = 3
  integer(omp_allocator_handle_kind), parameter :: omp_default_mem_alloc = 1
  integer(omp_memspace_handle_kind), parameter :: omp_default_mem_space = 0
  integer(omp_impex_kind), parameter :: omp_not_impex = 0, omp_import = 1, &
    omp_export = 2, omp_impex = 3
  interface
    logical function omp_is_initial_device()
    end function omp_is_initial_device
    integer function omp_get_team_num()
    end function omp_get_team_num
    integer function omp_get_thread_num()
    end function omp_get_thread_num
    integer function omp_get_default_device()
    end function omp_get_default_device
    double precision function omp_get_wtime()
    end function omp_get_wtime
    integer function omp_get_num_threads()
    end function omp_get_num_threads
    integer function omp_get_num_teams()
    end function omp_get_num_teams
    integer function omp_get_num_devices()
    end function omp_get_num_devices
    integer function omp_get_device_num()
    end function omp_get_device_num
    integer(c_int) function omp_target_is_present(ptr, device_num) bind(c)
      import :: c_ptr, c_int
      type(c_ptr), value :: ptr
      integer(c_int), value :: device_num
    end function omp_target_is_present
  end interface
end module omp_lib
"""

# The names OMP_LIB_STUB declares for the programs (test-checked against
# every program's ONLY list).
OMP_LIB_STUB_NAMES = frozenset({
    "omp_allocator_handle_kind", "omp_memspace_handle_kind",
    "omp_alloctrait_key_kind", "omp_alloctrait_val_kind", "omp_depend_kind",
    "omp_impex_kind", "omp_alloctrait", "omp_atk_alignment",
    "omp_default_mem_alloc", "omp_default_mem_space", "omp_not_impex",
    "omp_import", "omp_export", "omp_impex", "omp_is_initial_device",
    "omp_get_team_num", "omp_get_thread_num", "omp_get_default_device",
    "omp_get_wtime", "omp_get_num_threads", "omp_get_num_teams",
    "omp_get_num_devices", "omp_get_device_num",
    "omp_target_is_present"})


# --- building ---------------------------------------------------------------------------

@lru_cache(maxsize=None)
def _directive_keys() -> dict[str, str]:
    return {directive_atom(k): k for k in slice_directives(default_skeleton())}


def _recipe(atom: str, version: int) -> T.Src:
    if model_of(version) == "acc":
        from offload.engine import acc_gen
        return acc_gen.recipe(atom, version)
    parts = atom.split(".")
    if len(parts) < 3 or parts[0] != "omp":
        raise GenError(f"not an atom id: {atom!r}")
    if parts[1] == "directive":
        key = _directive_keys().get(atom)
        if key is None:
            raise GenError(f"no slice directive for {atom!r}")
        return T.directive_recipe(key, version)
    clause, feat = parts[2], (parts[3] if len(parts) > 3 else None)
    if feat == "directive_name":
        if clause == "if":
            return T.if_dnm_prog(version)
        return _dnm(clause, version)
    src = T.clause_recipe(clause, feat, version)
    if src is None:
        raise GenError(f"no recipe for {atom!r} at {version}")
    return src


def _parsed_atoms(source: str, version: int) -> frozenset:
    tree = parse_program(source, version)
    return frozenset().union(*(d.atoms for d in tree.directives),
                             *(d.atoms for d in tree.ends.values()))


def _header(pid, atom, version, src: T.Src, violates=None) -> list[str]:
    obs = "yes" if src.observable else "no"
    if src.note:
        obs += f" ({src.note})"
    model = model_of(version)
    where = ("probe (a target region just before the region of interest,"
             " which may not call the OpenMP API)"
             if src.probe else "inside the target region of interest")
    if model == "acc":
        where = "inside the compute region of interest (acc_on_device)"
    return [f"Generated by compliance.gen ({MODEL_NAME[model]} "
            f"{version // 10}.{version % 10}, free-form Fortran). Do not "
            "edit.",
            f"id: {pid}", f"primary atom: {atom}",
            "legal: " + ("yes" if violates is None
                         else f"no (violates {violates})"),
            f"observable: {obs}", f"ran_on_host: {where}",
            f"evidence: {src.evidence}",
            "needs: " + (", ".join(src.needs) if src.needs else "none"),
            f"std: {src.std}"] + (
                [f"expect: {src.expect}"]
                if src.expect != "result" else []) + (
                [f"token: {src.token}"] if src.token else []) + list(
                src.header_notes) + (
                [f"basis: {basis_text(src.basis, version)}"]
                if src.basis else []) + (
                [f"legality oracle: {RULE_PREFIX[model]}{version}-"
                 f"{src.legality_rule}"]
                if src.legality_rule else [])


def _pid(atom: str, version: int) -> str:
    m = model_of(version)
    return f"{m}{version}-" + atom.removeprefix(f"{m}.").replace(".", "-")


def _program(atom: str, version: int, src: T.Src) -> Program:
    pid = _pid(atom, version)
    source = src.render(_header(pid, atom, version, src))
    try:
        atoms = _parsed_atoms(source, version)
        found = violations(parse_program(source, version), version)
    except (GrammarError, ProgramError) as err:
        raise GenError(f"{pid}: {err}\n{source}") from err
    # a semantic atom (catalog/omp/semantic_atoms.yaml) is exercised through
    # the program's data; no directive carries it, so it is added to the
    # parsed atoms
    if atom in semantic_atoms():
        atoms = atoms | {atom}
    if atom not in atoms:
        raise GenError(f"{pid}: the program does not exercise {atom}\n"
                       f"{source}")
    if found:
        raise GenError(f"{pid}: legal program violates {found}\n{source}")
    if src.evidence not in EVIDENCE or not set(src.needs) <= set(NEEDS) \
            or src.expect not in EXPECT \
            or (src.evidence == "probe") != (src.expect != "result") \
            or bool(src.token) != src.expect.startswith("compile_"):
        raise GenError(f"{pid}: bad evidence {src.evidence!r}, needs "
                       f"{src.needs!r} or expect {src.expect!r}")
    unv = _UNVERIFIED_LINE.findall(source)
    if (src.evidence == "unverified") != bool(unv) or len(unv) > 1 or any(
            k not in UNVERIFIED for k, _ in unv):
        raise GenError(f"{pid}: evidence {src.evidence!r} with unverified "
                       f"lines {unv!r}")
    noo = _NO_ORACLE_LINE.findall(source)
    if (src.evidence in NO_ORACLE) != bool(noo) or len(noo) > 1 or any(
            k != src.evidence for k, _ in noo) or (
            bool(noo) != bool(_BASIS_LINE.search(source))):
        raise GenError(f"{pid}: evidence {src.evidence!r} with no-oracle "
                       f"lines {noo!r} (a no-oracle program needs exactly "
                       "one, of its own kind, and a basis)")
    if (src.evidence == "legality") != bool(legality_of(source)):
        raise GenError(f"{pid}: evidence {src.evidence!r} without its "
                       "legality oracle line (or the line without it)")
    prog = Program(pid, "fortran", source, atoms, atom, True, None,
                   src.observable, src.std, tuple(src.needs), src.evidence,
                   src.expect, src.token, model_of(version),
                   scope_of(source)[0])
    _check_scope(prog)
    return prog


def _check_scope(prog: Program) -> None:
    """The program is device offload (or a declared host+device
    pattern); offload.engine.offload_scope.check."""
    try:
        check_scope(prog)
    except ScopeError as err:
        raise GenError(str(err)) from err


@lru_cache(maxsize=None)
def _legal(atom: str, version: int) -> Program:
    return _program(atom, version, _recipe(atom, version))


# --- host+device patterns -------------------------------------------------
#
# The maintainer's exception to the device-offload scope: host constructs that
# feed a target region in a way people actually use are kept as patterns,
# each with its own program (id ``<atom program id>-hostdev``,
# Program.scope "host+device", header line ``! scope: host+device: <the
# realistic use>``). They are reported apart from the atom's device-only
# headline program, judged on the device result, and not mutation-audited
# (the headline program is the atom's oracle).
_DEPEND_FIRST = {"omp.clause.depend": "out", "omp.clause.depend.out": "out",
                 "omp.clause.depend.in": "out",
                 "omp.clause.depend.inout": "inout",
                 "omp.clause.depend.inoutset": "inoutset",
                 "omp.clause.depend.mutexinoutset": "mutexinoutset",
                 "omp.clause.depend.iterator": "iterator",
                 "omp.clause.depend.depobj": "depobj"}


def _depend_host(atom: str):
    def build(version: int) -> T.Src:
        s = T.depend_host_prog(version, _DEPEND_FIRST[atom], "in")
        if atom == "omp.clause.depend.in":
            s.focus = "depend(in: w)"
        return s
    return build


HOST_DEVICE: dict[str, Callable[[int], T.Src]] = {
    **{a: _depend_host(a) for a in _DEPEND_FIRST},
    "omp.directive.target": lambda v: T.threads_offload_prog(v),
    "omp.clause.nowait": lambda v: T.threads_offload_prog(v, nowait=True),
}


def hostdev_id(atom: str, version: int) -> str:
    return _pid(atom, version) + "-hostdev"


@lru_cache(maxsize=None)
def _hostdev(atom: str, version: int) -> Program:
    """The host+device pattern program of `atom` (HOST_DEVICE)."""
    src = HOST_DEVICE[atom](version)
    pid = hostdev_id(atom, version)
    prog = _program(atom, version, src)
    source = re.sub(r"^! id: .*$", f"! id: {pid}", prog.source, count=1,
                    flags=re.M)
    if prog.scope != "host+device":
        raise GenError(f"{pid}: a host+device pattern without its scope "
                       "line")
    return dataclasses.replace(prog, id=pid, source=source)


# --- the directive-name modifier family (6.0) --------------------------------------

# Argument for a clause whose base form has none (``nowait`` ->
# ``nowait(target: .true.)``).
_DNM_ARG = {"transparent": "omp_impex"}


# Base atom of the family member when it is not omp.clause.<clause>
# (ordered: the block-ordered base program repeats the word "ordered";
# linear: the simple step modifier takes no other modifier).
_DNM_BASE = {"ordered": "omp.clause.ordered.n",
             "linear": "omp.clause.linear.step"}

# Base programs of family members built from another recipe: reduction on
# parallel do in a target region without default(none). The base
# program of omp.clause.reduction is target teams distribute parallel do,
# where reduction(do, ...) leaves the teams sharing the item, so the teams'
# do reductions race for it, and default(none) leaves the item without a
# data-sharing attribute on teams and parallel.
_DNM_RECIPE = {"reduction": lambda v: T.reduction_prog(v, key="parallel do",
                                                       hyg=False),
               # message/severity: the parallel do form (the base atoms'
               # programs use the error directive)
               "message": lambda v: T.pdo(v, 'message("generated")').unverified(
                   "needs_other_infrastructure", T.ERROR_CLAUSE_WHY),
               "severity": lambda v: T.pdo(v, "severity(warning)").unverified(
                   "needs_other_infrastructure", T.ERROR_CLAUSE_WHY)}


def _dnm_variants(focus: str, clause: str, name: str) -> list[str]:
    m = re.fullmatch(rf"{clause}(?:\((.*)\))?", focus)
    if m is None:
        return []
    args = m.group(1)
    if args is None:
        return [f"{clause}({name}: {_DNM_ARG.get(clause, '.true.')})"]
    out = [f"{clause}({name}: {args})"]
    if ":" in args:
        head, tail = args.split(":", 1)
        out += [f"{clause}({name}, {args})",
                f"{clause}({head.strip()}, {name}:{tail})",
                f"{clause}({head.strip()}: {name},{tail})",
                f"{clause}({args}, {name})"]
    else:
        out.append(f"{clause}({args}: {name})")
    return out


def _dnm(clause: str, version: int) -> T.Src:
    """The base program of omp.clause.<clause> with a directive-name
    modifier on the focus clause, naming the innermost leaf (or the
    directive) that takes the clause."""
    base = _DNM_RECIPE[clause](version) if clause in _DNM_RECIPE else \
        _recipe(_DNM_BASE.get(clause, f"omp.clause.{clause}"), version)
    focus = next((c for c in _split_clauses(base.focus)
                  if re.match(rf"{clause}\b", c)), None)
    if focus is None:
        raise GenError(f"no focus clause for {clause} directive_name")
    rendered = base.render([])
    hits = [ln for ln in rendered.splitlines() if focus in ln]
    if len(hits) != 1:
        raise GenError(f"focus {focus!r} not unique in the {clause} program")
    key = parse_directive(_directive_text(rendered, hits[0]), "fortran",
                          version).name
    names = [leaf for leaf in reversed(leaves(key))
             if T.permits(leaf, clause, version)] + [key]
    atom = f"omp.clause.{clause}.directive_name"
    for name in names:
        spelled = T.spell(name, version)
        for variant in _dnm_variants(focus, clause, spelled):
            src = dataclasses.replace(base, focus=variant)
            src.module = [x.replace(focus, variant) for x in base.module]
            for f in ("spec", "region", "init", "post"):
                setattr(src, f, [x.replace(focus, variant)
                                 for x in getattr(base, f)])
            source = src.render([])
            try:
                ok = atom in _parsed_atoms(source, version) and not \
                    violations(parse_program(source, version), version)
            except (GrammarError, ProgramError):
                ok = False
            if ok:
                return _dnm_evidence(src, clause, key, name, version)
    raise GenError(f"no directive-name form of {focus!r} parses at "
                   f"{version}")


# Directive-name forms on a compound construct whose clause, without the
# modifier, already applies only to the named constituent by the rules of
# 6.0 §19.2 p.528 ("Clauses on Compound Constructs"): (clause, compound,
# named constituent) -> the rule.
_DNM_SAME = {
    ("private", "parallel do", "do"):
        "private has the innermost-leaf property, so without the modifier "
        "it applies only to the innermost leaf that permits it, do",
    ("firstprivate", "parallel do", "do"):
        "firstprivate on a compound construct with a worksharing-loop "
        "applies to the do, and the parallel then shares the item, which is "
        "also the effect of firstprivate(do: ...)",
    ("allocate", "parallel do", "do"):
        "allocate has the all-privatizing property: it applies to the leaves "
        "on which a clause privatizes the item, here only the do (private "
        "has the innermost-leaf property)",
    ("reduction", "parallel do", "do"):
        "reduction on parallel combined with a worksharing-loop applies to "
        "the do, and the parallel then shares the item, which is also the "
        "effect of reduction(do, ...)",
    ("thread_limit", "target teams distribute parallel do", "teams"):
        "without the modifier thread_limit applies to target and teams, and "
        "a teams construct closely nested in a target construct with "
        "thread_limit behaves as if the clause were on the teams too (6.0 "
        "§12.2 p.394), so every legal form (no modifier, teams, target) "
        "gives each team the same limit",
}
# Directive-name forms whose constituents differ in effect, but in ways
# no single run of a conforming program can tell apart.
_DNM_IMPL = {
    "nowait": "with the modifier nowait drops the do's barrier, which the "
              "parallel region's end barrier follows at once; without it "
              "nowait applies to the outermost leaf, target (outermost-leaf "
              "property, 6.0 §19.2 p.528), whose target task an "
              "implementation may run synchronously: no conforming run "
              "separates the two",
}
_DNM_NO_RENAME = ("; no other constituent accepts the clause, so no "
                  "directive-name mutation is legal")
# The spec basis (catalog/omp/no_oracle.yaml) of each _DNM_SAME rule.
_DNM_SAME_BASIS = {"private": "dnm_innermost_leaf",
                   "firstprivate": "dnm_firstprivate",
                   "allocate": "dnm_all_privatizing",
                   "reduction": "dnm_reduction",
                   "thread_limit": "dnm_thread_limit"}
_DNM_IMPL_BASIS = {"nowait": "target_nowait"}


def _dnm_evidence(src: T.Src, clause: str, key: str, name: str,
                  version: int) -> T.Src:
    """An observable member of the family has no separating oracle (triage, categories): where only the named constituent accepts
    the clause, or where the rules of 6.0 §19.2 already apply the
    unmodified clause to the named constituent alone, the forms are the
    same (equivalent_default); the others differ only in ways no single run
    can show (implementation_defined). Each carries its spec basis."""
    if not src.observable and src.evidence not in ("unverified",) + NO_ORACLE:
        return src
    # the base program's check tests the clause's effect (it stays
    # observable) only when the base has an audited oracle
    checked = src.evidence in AUDITED and src.observable
    takers = [leaf for leaf in leaves(key) if T.permits(leaf, clause, version)]
    if len(takers) <= 1:
        basis = "dnm_own_directive" if len(leaves(key)) == 1 \
            else "dnm_single_leaf"
        return src.no_oracle(
            "equivalent_default", f"{clause} applies only to the {name} "
            f"constituent of {key}, the one the modifier names, so the form "
            "without the modifier is the same" + _DNM_NO_RENAME, basis,
            checked=checked)
    same = _DNM_SAME.get((clause, key, name))
    if same is not None:
        return src.no_oracle(
            "equivalent_default", f"{same} (6.0 §19.2 p.528), so the form "
            "without the modifier is the same", _DNM_SAME_BASIS[clause],
            checked=checked)
    why = _DNM_IMPL.get(clause)
    if why is None or key != "target teams distribute parallel do":
        raise GenError(f"no triage for the directive-name form of {clause} "
                       f"on {key} (constituents {takers})")
    return src.no_oracle("implementation_defined", why,
                         _DNM_IMPL_BASIS[clause], checked=checked)


def _split_clauses(text: str) -> list[str]:
    out, depth, cur = [], 0, ""
    for ch in text:
        depth += ch == "("
        depth -= ch == ")"
        if ch == " " and depth == 0:
            if cur:
                out.append(cur)
            cur = ""
            continue
        cur += ch
    if cur:
        out.append(cur)
    return out


def _directive_text(source: str, line: str) -> str:
    """The whole (possibly continued) directive containing `line`."""
    lines = source.splitlines()
    k = lines.index(line)
    while k and lines[k - 1].rstrip().endswith("&"):
        k -= 1
    out = [lines[k]]
    while out[-1].rstrip().endswith("&"):
        k += 1
        out.append(lines[k])
    return "\n".join(out)


# --- illegal variants -----------------------------------------------------------------

def _sub(old: str, new: str, count: int = 1):
    """A source transform replacing `old` (which must occur `count` times)."""
    def fn(source: str) -> str:
        n = source.count(old)
        if n != count:
            raise GenError(f"transform: {old!r} occurs {n} times, "
                           f"expected {count}")
        return source.replace(old, new)
    return fn


def _chain(*fns):
    def fn(source: str) -> str:
        for f in fns:
            source = f(source)
        return source
    return fn


def _regex(pattern: str, repl: str):
    def fn(source: str) -> str:
        new, n = re.subn(pattern, repl, source, count=1, flags=re.M | re.S)
        if n != 1:
            raise GenError(f"transform: no match for {pattern!r}")
        return new
    return fn


def _insert(pattern: str, lines: list[str], after: bool = True):
    """Insert `lines` after (or before) the one source line whose stripped
    text matches `pattern` (re.fullmatch), at that line's indentation."""
    def fn(source: str) -> str:
        src = source.split("\n")
        hits = [k for k, ln in enumerate(src)
                if re.fullmatch(pattern, ln.strip())]
        if len(hits) != 1:
            raise GenError(f"transform: {pattern!r} matches {len(hits)} "
                           "lines, expected 1")
        k = hits[0]
        ind = src[k][:len(src[k]) - len(src[k].lstrip())]
        new = [ind + x for x in lines]
        src[k + 1 if after else k:k + 1 if after else k] = new
        return "\n".join(src)
    return fn


def _drop(pattern: str):
    """Remove the one line whose stripped text matches `pattern`."""
    def fn(source: str) -> str:
        src = source.split("\n")
        hits = [k for k, ln in enumerate(src)
                if re.fullmatch(pattern, ln.strip())]
        if len(hits) != 1:
            raise GenError(f"transform: {pattern!r} matches {len(hits)} "
                           "lines, expected 1")
        del src[hits[0]]
        return "\n".join(src)
    return fn


# rule stem -> {version: (base atom, transform)}; one change each (see the
# isolation notes in catalog/omp/rules.yaml).
_T: dict[str, dict[int, tuple[str, Callable[[str], str]]]] = {}


def _rule(stem, versions, base, fn):
    for v in versions:
        _T.setdefault(stem, {})[v] = (base, fn)


BOTH = (52, 60)
_TARGET_MAPS = ("!$omp target map(to: a) map(from: b) map(from: nt) "
                "map(tofrom: host_flag)")

# The teams construct is nested in a parallel construct inside
# the target region (before: a host parallel region with no target), so the
# illegal nesting is in offload code
_rule("teams-nesting-001", BOTH, "omp.directive.teams", _chain(
    _insert(re.escape(_TARGET_MAPS), ["!$omp parallel num_threads(1)"]),
    _insert(r"!\$omp end target$", ["!$omp end parallel"], after=False)))
_rule("teams-nesting-002", BOTH, "omp.directive.teams",
      _insert(re.escape(_TARGET_MAPS), ["host_flag = 1"]))
_rule("teams-nesting-003", BOTH, "omp.directive.teams", _chain(
    _insert(r"if \(omp_get_team_num\(\) == 0\) then", ["!$omp single"],
            after=False),
    _insert(r"!\$omp end teams", ["!$omp end single"], after=False)))
_rule("distribute-nesting-001", BOTH, "omp.directive.distribute", _chain(
    _sub("!$omp target teams map", "!$omp target parallel map"),
    _sub(" num_teams(4)", ""),
    _sub("!$omp end target teams", "!$omp end target parallel")))
# The orphaned loop construct without bind is in a declare target
# subroutine called in a target region (the bind(parallel) program without
# its bind clause); before, the main program's loop construct with its
# target teams wrapper removed, which ran on the host. The loop is in a
# procedure, so the 5.0 rule (bind required on an orphaned loop in a
# procedure, 5.0 §2.9.5 p.131) holds too.
_rule("loop-nesting-001", (50,) + BOTH, "omp.clause.bind.parallel",
      _sub("!$omp loop bind(parallel)", "!$omp loop"))
# The primary atom of a variant whose transform removes its base atom: the
# directive the rule restricts (the base program supplies the context).
VARIANT_PRIMARY = {"loop-nesting-001": "omp.directive.loop"}
# the bind programs use an orphaned loop, which the rule
# never flags: the variant is the loop program with bind(teams) added and
# its target teams wrapper made target parallel (as distribute-nesting-001)
_rule("loop-nesting-002", BOTH, "omp.directive.loop", _chain(
    _sub("!$omp loop", "!$omp loop bind(teams)"),
    _sub("!$omp target teams map", "!$omp target parallel map"),
    _sub(" num_teams(4)", ""),
    _sub("!$omp end target teams", "!$omp end target parallel")))
_rule("target-nesting-001", BOTH, "omp.directive.target", _insert(
    r"!\$omp end target", ["!$omp target update from(b)"], after=False))
_rule("order-nesting-001", BOTH, "omp.clause.order.concurrent", _chain(
    _insert(r"b\(i\) = 2\*a\(i\) \+ 1", ["!$omp task"], after=False),
    _insert(r"b\(i\) = 2\*a\(i\) \+ 1", ["!$omp end task"])))
_rule("declaretarget-placement-001", BOTH, "omp.directive.target", _insert(
    r"!\$omp end target", ["!$omp declare target (a)"], after=False))
_rule("requires-placement-001", BOTH, "omp.directive.target_parallel",
      _insert(r"host_flag = merge.*", [
          "!$omp requires atomic_default_mem_order(seq_cst)"], after=False))
_rule("requires-placement-002", (52,), "omp.directive.target", _insert(
    r"!\$omp end target", ["!$omp requires unified_shared_memory"]))
_rule("assoc-loop-001", BOTH, "omp.directive.parallel_do", _regex(
    r"(!\$omp parallel do [^\n]*\n)\s*do i = 1, n\n.*?end do\n"
    r"\s*!\$omp end parallel do\n", r"\1    b = 2*a + 1\n"))
_rule("collapse-loop-001", BOTH, "omp.clause.collapse",
      _sub("collapse(2)", "collapse(3)"))
_rule("target-map-001", (52,), "omp.directive.target",
      _sub("map(from: b)", "map(release: b)"))
_rule("targetdata-map-001", (52,), "omp.directive.target_data",
      _sub("!$omp target data map(to: a) map(from: b)",
           "!$omp target data map(to: a) map(release: b)"))
_rule("targetenterdata-map-001", BOTH, "omp.directive.target_enter_data",
      _sub("map(alloc: b)", "map(from: b)"))
_rule("targetexitdata-map-001", BOTH, "omp.directive.target_exit_data",
      _sub("map(from: b) map(release: a)", "map(to: b) map(release: a)"))
_rule("mapitem-map-001", BOTH, "omp.clause.map.mapper",
      _sub("map(mapper(mm), tofrom: s)",
           "map(mapper(mm), tofrom: s) map(to: s)"))
_rule("mapitem-map-002", (52,), "omp.directive.target",
      _sub("map(to: a) map(from: b) map(tofrom: host_flag)\n",
           "map(to: a) map(to: a(1:n)) map(from: b) "
           "map(tofrom: host_flag)\n"))
_rule("mapitem-map-003", (60,), "omp.clause.map.self",
      _sub("map(self: a)", "map(self: a) map(to: a(1:n))"))
_rule("loop-dsa-001", BOTH, "omp.directive.loop",
      _sub("!$omp loop", "!$omp loop lastprivate(host_flag)"))
_rule("target-dsa-001", BOTH, "omp.directive.target",
      _sub("map(to: a) map(from: b) map(tofrom: host_flag)\n",
           "map(to: a) map(from: b) map(tofrom: host_flag) "
           "firstprivate(a)\n"))
_rule("distribute-dsa-001", BOTH, "omp.directive.distribute",
      _sub("!$omp distribute", "!$omp distribute firstprivate(host_flag) "
           "lastprivate(host_flag)"))
_rule("datasharing-dsa-001", BOTH, "omp.clause.private",
      _sub("private(t)", "private(t) firstprivate(t)"))
_USE_DEV = _sub("  implicit none\n", "  implicit none\n  type :: ud_t\n"
                "    integer :: v(4)\n  end type ud_t\n  type(ud_t) :: su\n")
_rule("usedevice-clause-001", (52,), "omp.clause.use_device_addr", _chain(
    _USE_DEV, _sub("use_device_addr(a, b)", "use_device_addr(a, b, su%v)")))
_rule("usedevice-clause-002", (60,), "omp.clause.use_device_addr", _chain(
    _USE_DEV,
    _sub("use_device_addr(a, b)", "use_device_addr(a, b, su%v(1:2))")))
_rule("dnm-clause-001", BOTH, "omp.clause.if.directive_name",
      _sub("if(parallel: use_dev)", "if(simd: use_dev)"))
_rule("if-clause-001", BOTH, "omp.clause.if.directive_name",
      _sub("if(parallel: use_dev)", "if(parallel: use_dev) if(use_dev)"))
_rule("threadlimit-clause-001", BOTH, "omp.clause.thread_limit",
      _sub("thread_limit(16)", "thread_limit(0)"))
_rule("numteams-clause-001", BOTH, "omp.clause.num_teams",
      _sub("num_teams(4)", "num_teams(0)"))
_rule("numteams-clause-002", BOTH, "omp.clause.num_teams.lower_bound",
      _sub("num_teams(2: 4)", "num_teams(8: 4)"))
_rule("distschedule-clause-001", BOTH, "omp.clause.dist_schedule.chunk_size",
      _sub("dist_schedule(static, 4)", "dist_schedule(static, 0)"))
_rule("reduction-clause-001", BOTH, "omp.directive.teams", _chain(
    _insert(r"logical :: ok", ["integer :: t"]),
    _regex(r"(!\$omp teams [^\n]*)\n", r"\1 reduction(task, +: t)\n")))
# The device report moves into a one-thread parallel region,
# since a teams region may not call omp_is_initial_device (teams-nesting-003)
_rule("reduction-clause-002", BOTH, "omp.clause.reduction.inscan", _chain(
    _regex(r"^( *)(host_flag = merge\(1, 0, omp_is_initial_device\(\)\))\n",
           r"\1!$omp parallel num_threads(1)\n\1  \2\n"
           r"\1!$omp end parallel\n"),
    _sub("!$omp target map", "!$omp target teams map"),
    _sub("!$omp end target\n", "!$omp end target teams\n"),
    _sub("!$omp parallel do", "!$omp distribute parallel do"),
    _sub("!$omp end parallel do", "!$omp end distribute parallel do")))
_rule("reduction-clause-003", BOTH, "omp.clause.reduction.inscan",
      _sub("reduction(inscan, +: s)", "reduction(inscan, +: s) "
           "reduction(+: host_flag)"))
_rule("reduction-clause-004", BOTH, "omp.clause.reduction.inscan",
      _sub("reduction(inscan, +: s)", "reduction(inscan, +: s) "
           "schedule(static)"))
_rule("reduction-clause-005", BOTH, "omp.clause.reduction.task",
      _sub("!$omp end do\n", "!$omp end do nowait\n"))
_rule("distribute-clause-001", BOTH, "omp.directive.distribute",
      _sub("!$omp distribute", "!$omp distribute "
           "lastprivate(conditional: host_flag)"))
# The legality oracle of default(none): b is no longer listed
_rule("default-dsa-001", BOTH, "omp.clause.default.none",
      _sub("default(none) shared(a, b)", "default(none) shared(a)"))
_rule("listitem-clause-001", BOTH, "omp.clause.private",
      _sub("private(t)", "private(t, b(1))"))
_rule("device-clause-001", BOTH, "omp.clause.device.ancestor", _sub(
    "  !$omp target map(to: a)",
    "  !$omp target enter data device(ancestor: 1) map(to: a)\n"
    "  !$omp target map(to: a)"))
_rule("device-clause-002", BOTH, "omp.clause.device.ancestor",
      _sub("device(ancestor: 1)", "device(ancestor: 2)"))
_rule("device-clause-003", BOTH, "omp.clause.device.ancestor",
      _sub("  !$omp requires reverse_offload\n", ""))
_rule("target-clause-001", BOTH, "omp.clause.device.ancestor",
      _sub("device(ancestor: 1)", "device(ancestor: 1) if(.true.)"))
_rule("declaretarget-clause-001", BOTH, "omp.clause.enter",
      _sub("!$omp declare target enter(dv)",
           "!$omp declare target (dv) enter(dw)"))
_rule("declaretarget-clause-002", (52,), "omp.clause.device_type.any",
      _sub("to(f) device_type(any)", "device_type(any)"))
_rule("declaretarget-clause-003", BOTH, "omp.clause.link",
      _sub("link(dv)", "link(dv) device_type(nohost)"))
_rule("requires-clause-001", (52,),
      "omp.clause.atomic_default_mem_order.seq_cst",
      _sub("  !$omp requires atomic_default_mem_order(seq_cst)\n",
           "  !$omp requires atomic_default_mem_order(seq_cst)\n"
           "  !$omp requires atomic_default_mem_order(relaxed)\n"))

# The OpenMP 5.0 variant of a rule that has a 5.0 entry is the 5.2
# transform applied to the 5.0 program of the same atom (each one checked:
# it must violate exactly the 5.0 rule), except where the 5.0 rule differs
# so that the 5.2 change is legal 5.0.
NO_VARIANT_50: dict[str, str] = {}
# 5.0 transforms of their own: the 5.0 num_teams program asks for one team
_T50 = {"numteams-clause-001": ("omp.clause.num_teams",
                                _sub("num_teams(1)", "num_teams(0)"))}
_RULES50 = {r.id for r in default_rules() if r.version == 50}
for _stem, _by in list(_T.items()):
    if 52 in _by and f"OMP50-{_stem}" in _RULES50 \
            and _stem not in NO_VARIANT_50:
        _by[50] = _T50.get(_stem, _by[52])

NOT_GENERATABLE_WHY: dict[str, str] = {
    f"OMP50-{_stem}": _why for _stem, _why in NO_VARIANT_50.items()}
for _v in (50,) + BOTH:
    for _stem in ("defaultmap-map-001", "defaultmap-map-002"):
        if _v == 50 and _stem == "defaultmap-map-002":
            continue  # the all category is 5.2
        NOT_GENERATABLE_WHY[f"OMP{_v}-{_stem}"] = (
            "no violation template: the generator writes one defaultmap "
            "clause per construct (the grammar lets defaultmap repeat since "
            "; the rule checks parsed source)")

# rule id -> (base atom, source transform); the OpenACC transforms are
# offload.engine.acc_gen's
VIOLATION_BASE: dict[str, tuple[str, Callable[[str], str]]] = {
    f"OMP{v}-{stem}": entry for stem, by in _T.items()
    for v, entry in by.items()}


def _acc_violations():
    from offload.engine import acc_gen
    for stem, entry in acc_gen.ILLEGAL.items():
        VIOLATION_BASE[f"ACC34-{stem}"] = entry
    from offload.engine.rules import acc_rules
    for r in acc_rules():
        if r.check == "static" and r.id not in VIOLATION_BASE:
            NOT_GENERATABLE_WHY[r.id] = acc_gen.NO_VARIANT_WHY

# Added the remaining static restrictions (data/reports/
# rules-coverage.md); their illegal programs are the unit cases of
# tests/engine/test_generators.py (CASES), not generated variants.
TASK16_NO_VARIANT = ("Rule: no single-change illegal variant of a "
                     "generated program is written; the rule's legal and "
                     "illegal programs are the unit cases in "
                     "tests/engine/test_generators.py (CASES)")
for _r in default_rules():
    if _r.check == "static" and _r.id not in NOT_GENERATABLE_WHY and \
            _r.id not in VIOLATION_BASE:
        NOT_GENERATABLE_WHY[_r.id] = TASK16_NO_VARIANT
_acc_violations()
# The iterator restriction of map clauses is checked to judge
# corpus tests (omp_vv); a catalog variant would add a program whose
# behaviour is unspecified and need not be diagnosed, and no measurement
for _v in BOTH:
    NOT_GENERATABLE_WHY[f"OMP{_v}-map-clause-005"] = (
        "added to judge corpus tests: a variant with two "
        "iterator instances of one containing array has unspecified "
        "behaviour that need not be diagnosed, so it measures nothing")

NOT_GENERATABLE: set[str] = set(NOT_GENERATABLE_WHY)


_ZERO_COPY_SOURCE = re.compile(
    r"^\s*!\$omp\s+requires\b[^\n]*\b(unified_shared_memory|self_maps)\b"
    r"|\bmap\s*\(\s*self\b|\bdefaultmap\s*\(\s*self\b", re.M | re.I)


def needs_zero_copy(source: str) -> bool:
    """Whether a source uses a feature that needs memory the device can
    access (requires unified_shared_memory / self_maps, self maps)."""
    return bool(_ZERO_COPY_SOURCE.search(source))


def _make_violation(rid: str) -> Callable[[Program], Program]:
    version = int(rid[3:5])
    fn = VIOLATION_BASE[rid][1]

    def apply(prog: Program) -> Program:
        pid = f"{model_of(version)}{version}-illegal-{rid.split('-', 1)[1]}"
        source = fn(prog.source)
        primary = variant_primary(rid)
        if primary != prog.primary_atom:
            source = re.sub(r"^! primary atom: .*$",
                            f"! primary atom: {primary}", source, count=1,
                            flags=re.M)
        source = re.sub(r"^! id: .*$", f"! id: {pid}", source, count=1,
                        flags=re.M)
        source = re.sub(r"^! legal: .*$", f"! legal: no (violates {rid})",
                        source, count=1, flags=re.M)
        try:
            atoms = _parsed_atoms(source, version)
        except (GrammarError, ProgramError) as err:
            raise GenError(f"{pid}: {err}\n{source}") from err
        needs = tuple(prog.needs)
        if "zero_copy" not in needs and needs_zero_copy(source):
            needs += ("zero_copy",)
            source = re.sub(r"^! needs: .*$", "! needs: " + ", ".join(needs),
                            source, count=1, flags=re.M)
        return dataclasses.replace(prog, id=pid, source=source, atoms=atoms,
                                   legal=False, violates=rid, needs=needs,
                                   primary_atom=primary)
    return apply


def variant_primary(rid: str) -> str:
    """The primary atom of the illegal variant of `rid`: its base atom, or
    the VARIANT_PRIMARY override."""
    return VARIANT_PRIMARY.get(rid.split("-", 1)[1],
                               VIOLATION_BASE[rid][0])


VIOLATIONS: dict[str, Callable[[Program], Program]] = {
    rid: _make_violation(rid) for rid in VIOLATION_BASE}


def _check_rule_sets():
    rules = {r.id: r for v in (52, 34) for r in rules_for(v)}
    for rid in VIOLATIONS:
        if rid not in rules or rules[rid].check != "static":
            raise GenError(f"VIOLATIONS names {rid}, not a static rule")


_check_rule_sets()


@lru_cache(maxsize=None)
def _illegal(rid: str) -> Program:
    version = int(rid[3:5])
    base_atom, _ = VIOLATION_BASE[rid]
    prog = VIOLATIONS[rid](_legal(base_atom, version))
    found = violations(parse_program(prog.source, version), version)
    if found != [rid]:
        raise GenError(f"{prog.id}: violates {found}, expected [{rid}]\n"
                       f"{prog.source}")
    _check_scope(prog)
    return prog


# --- the entry point ------------------------------------------------------------------

def generate(atoms: Iterable[str], version: int) -> Iterator[Program]:
    """One legal program per atom (sorted), then the illegal variants whose
    base atom is among `atoms` (sorted by rule id). An atom listed in
    UNGENERATABLE[version] is skipped (with its stated reason); any other
    atom without a program raises GenError."""
    wanted = sorted(set(atoms))
    skip = UNGENERATABLE.get(version, {})
    for atom in wanted:
        if atom in skip:
            continue
        yield with_derivation(_legal(atom, version), atom, version)
        if atom in HOST_DEVICE and model_of(version) == "omp":
            yield _hostdev(atom, version)
    chosen = set(wanted) - set(skip)
    for rid in sorted(VIOLATION_BASE):
        if rid.startswith(f"{RULE_PREFIX[model_of(version)]}{version}-") \
                and VIOLATION_BASE[rid][0] in chosen:
            yield _illegal(rid)


def all_programs(version: int) -> list[Program]:
    """Every program of the slice at `version`."""
    return list(generate(slice_atoms(version), version))
