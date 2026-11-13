"""Build, run and classify one program on one toolchain and memory mode.

``run_program(prog, tc, xnack, opt)`` compiles ``prog`` with
``tc.compile_cmd``, runs it on the MI300A and returns a ``Result`` whose
``outcome`` is an ``Outcome``, with the evidence for the verdict.
Compile output is matched against ``PATTERNS`` (messages from real compiler
output): environment, ice, not_implemented, link_undefined, diagnostic.
Environment problems and unmatched failures are ``harness_error``, never a
rejection; ``ignored`` messages give ``accepted_ignored``.
Each run happens in its own temporary directory and process group. The
primary run sets ``OMP_TARGET_OFFLOAD=mandatory`` and prints one
``RESULT ran_on_host=<0|1> check=<pass|fail>`` line; a failed one gets a
second run without it. Runs repeat ``repeats`` times and disagreeing runs
give the worst outcome with ``flaky=True``. Negative and compile-output
probes use ``ERROR_TERMINATION`` and ``COMPILE_DIAGNOSTIC``. OpenACC runs once."""
from __future__ import annotations

import dataclasses
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from offload.engine.gen import Program
from offload.engine.toolchains import (Toolchain, compiler_version, detect_gpu,
                                   device_of, family, install_roots,
                                   loaded_rocm_version)


class Outcome(StrEnum):
    rejected = "rejected"
    accepted_ignored = "accepted_ignored"
    fell_back_to_host = "fell_back_to_host"
    wrong_answer = "wrong_answer"
    correct_on_device = "correct_on_device"
    unobservable = "unobservable"
    harness_error = "harness_error"


# Most pessimistic first; used to report the worst of disagreeing repeats.
WORST_FIRST = (Outcome.harness_error, Outcome.wrong_answer,
               Outcome.fell_back_to_host, Outcome.accepted_ignored,
               Outcome.rejected, Outcome.unobservable,
               Outcome.correct_on_device)


@dataclass(frozen=True)
class Result:
    program_id: str
    primary_atom: str
    atoms: tuple[str, ...]
    toolchain: str
    xnack: int
    opt: str
    outcome: Outcome
    reason: str
    flaky: bool
    flags: str
    rocm: str | None
    stdout: str
    stderr: str
    needs: tuple[str, ...] = ()
    evidence: str = "construct"
    observable: bool = True
    legal: bool = True
    violates: str | None = None
    version: int = 0
    thp: str = "n/a"
    device: str = ""
    compiler: str = ""
    model: str = "omp"
    lang: str = "f90"  # "c" for a C program
    scope: str = "device"  # "host+device" for a pattern program
    # Where the row ran: the toolchain's machine and arch, and the
    # node's GPU per rocminfo ("<gfx> <marketing name>"); "" in rows
    # written before these fields existed (all of them Tuolumne, gfx942)
    machine: str = ""
    arch: str = ""
    gpu: str = ""
    # Provenance (offload.engine.provenance; "" in rows written
    # before provenance was recorded): the build directory, the node, the compiler's
    # version and modules, a hash of the run environment, the code's git
    # revision, and the reproduction gate's status ("pending" for a
    # failing row the gate has not judged, "n/a" for a passing row, else a
    # offload.engine.gate verdict)
    build_dir: str = ""
    node: str = ""
    toolchain_build: str = ""
    env_hash: str = ""
    git_rev: str = ""
    gate: str = ""
    # Every classified message of a failed compile, worst first
    # (classify_all); the outcome and reason are the worst one's
    messages: str = ""


# --- the message table ---------------------------------------------------------------
#
# Regular expressions (re.MULTILINE), per toolchain and category, each taken
# from real output captured on Tuolumne (tests/data/messages/<file>.txt says
# which program and command produced it). COMMON applies to every toolchain.

COMMON_ENVIRONMENT = (
    # cce_run_no_rocm: CCE binary run without the module prelude
    r"error while loading shared libraries: .*cannot open shared object file",
    # shell_no_module: Lmod not initialised
    r"module: command not found",
    # shell_no_module: the compiler is not on PATH
    r"^bash: .*: command not found",
    # lmod_unknown_module
    r"Lmod has detected the following error",
    # shell_missing_compiler: compiler path does not exist
    r"^bash: .*: No such file or directory",
)

PATTERNS: dict[str, dict[str, tuple[str, ...]]] = {
    "afar": {
        "environment": COMMON_ENVIRONMENT + (
            r"unable to find library -l\S+",            # afar_link_quadmath
            # afar_frontend_killed: SIGKILL (OOM killer, external kill)
            r"error: unable to execute command: Killed",
        ),
        "ice": (                                         # afar_ice_segfault
            r"PLEASE submit a bug report to https://github\.com/llvm/llvm-project",
            r"error: unable to execute command: Segmentation fault",
            # afar_ice_llvm_verifier: LLVM IR the compiler generated fails
            # the verifier (reduction(task, ...) in a target region); NOT
            # "failed to create the LLVM module", which also follows a
            # not-yet-implemented or MLIR diagnostic
            r"^Call parameter type does not match function signature!",
            # afar_ice_fir_verification: the FIR the compiler lowered fails
            # its own verifier (fuzz campaign)
            r"^error: verification of lowering to FIR failed",
        ),
        "not_implemented": (
            r"not yet implemented",                     # afar_not_implemented
        ),
        # afar_link_device_runtime: the device image of a
        # program with module derived types references flang runtime
        # routines the device runtime lacks; _undefined_symbols decides
        # program vs system by the referrer (the program's .img.lto.o)
        "link_undefined": (
            r"lld: error: undefined symbol: ",
        ),
        "error": (
            r"^\S.*:\d+:\d+: error: ",                  # afar_syntax_error, ...
            r"^error: Semantic errors in ",             # afar_clause_not_allowed
            r"^error: Could not parse ",                # afar_syntax_error
            r"^loc\(.*\): error: ",                     # afar_mlir_op_not_allowed
        ),
        "ignored": (
            r"is not supported and will be ignored",    # afar_ignored_reverse_offload
        ),
    },
    "cce19": {
        "environment": COMMON_ENVIRONMENT + (
            r"lib\S+\.so[\d.]*, needed by \S+, not found",  # cce_link_no_rocm
        ),
        "ice": (
            r"INTERNAL COMPILER ERROR",                 # cce_ice_ordered
            r"^ftn-\d+ ftn: INTERNAL",
            # cce_ice_addrspacecast: the LLVM back end rejects code the
            # compiler generated ("in function <generated>: ...")
            r"^error: \S+:\d+:\d+: in function \S+ .*: invalid addrspacecast",
        ),
        "not_implemented": (
            r"Implementation for the .* is deferred",   # cce_deferred
            r"Unsupported OpenMP construct",            # cce_unsupported_construct
            # Cce_acc_unsupported_construct
            r"Unsupported OpenACC construct",
        ),
        # detectors only: _undefined_symbols decides program vs system
        "link_undefined": (
            r"lld: error: undefined symbol: ",          # cce_link_c_f_pointer
            r"undefined reference to `",                # cce_link_ompit
        ),
        "error": (
            r"^ftn-\d+ ftn: ERROR",                     # cce_syntax_error, ...
        ),
        "ignored": (
            r'OpenMP [\d.]+ "\w+" clause is being ignored',  # cce_ignored_device
        ),
    },
}

# C: AFAR amdclang and CCE craycc are both clang front ends and
# print clang's diagnostics (captured: afar_c_syntax_error,
# cce_c_syntax_error, afar_c_error_warning, cce_c_error_fatal, ...); the
# environment patterns are the toolchain's own. Keys "<family>:c". Unlike
# the Fortran compilers, clang drops an OpenMP clause, modifier or
# directive-name word it does not know with a warning and compiles the
# rest ("extra tokens at the end of '#pragma omp target' are ignored": a
# 6.0 replayable clause, the "loop" of 6.0 "target loop"), so that warning
# is "ignored" (captured: afar_c_extra_tokens_ignored,
# cce_c_extra_tokens_ignored, afar_c_modifier_ignored).
_CLANG_C = {
    "error": (
        r"^\S.*:\d+:\d+: (?:fatal )?error: ",        # afar/cce_c_syntax_error
    ),
    "ignored": (
        r"warning: extra tokens at the end of '#pragma omp [^']*' are "
        r"ignored",                                     # *_c_extra_tokens_ignored
    ),
}
PATTERNS["afar:c"] = {
    "environment": PATTERNS["afar"]["environment"],
    # afar_c_link_device_error: the device image of a target
    # region with an error directive at(compilation) calls __kmpc_error,
    # which the device runtime lacks; _undefined_symbols decides program
    # vs system by the referrer (the program's .img.lto.o)
    "link_undefined": PATTERNS["afar"]["link_undefined"],
    **_CLANG_C,
    "ignored": _CLANG_C["ignored"] + (
        r"; modifier ignored \[-Wopenmp-clauses\]",    # afar_c_modifier_ignored
    ),
    # Afar_c_link_no_libcall: the AMDGPU back end cannot lower
    # an operation of the program (long double arithmetic)
    "not_implemented": (
        r"^ld\.lld: error: no libcall available for ",
    ),
}
PATTERNS["cce19:c"] = {
    "environment": PATTERNS["cce19"]["environment"],
    "link_undefined": PATTERNS["cce19"]["link_undefined"],
    "ice": (
        r"PLEASE submit a bug report to ",              # cce_c_ice
        r"^clang\S*: error: clang frontend command failed",  # cce_c_ice
    ),
    "not_implemented": (
        r"error: .* is not yet supported",              # cce_c_not_yet_supported
        # Cce_c_unsupported_dynamic_alloca: a variable-length
        # array in a target region
        r"^error: \S+:\d+:\d+: in function .*: unsupported ",
    ),
    **_CLANG_C}


# NVIDIA HPC SDK 25.11 (nvfortran, nvc) on wingtip, captured from
# the catalog's own compiles (tests/data/messages/nvhpc_*.txt). NVFORTRAN
# messages read "NVFORTRAN-<severity>-<number>-<text> (<file>: <line>)",
# severity I(nform), W(arning), S(evere), F(atal); a compile fails on S or
# F. nvc prints EDG front-end diagnostics ('"<file>", line N: error: ...':
# it rejects every OpenMP clause or modifier it does not know, e.g.
# "invalid text in pragma", 'identifier "ancestor" is undefined') and
# "NVC++-<severity>-<number>-..." messages of the OpenMP lowering.
# * ice: the device compiler (NVVM) rejecting code the compiler generated
#   ("nvvmCompileProgram: failed", "nvnvvmd: error:", "Compiler failed to
#   translate accelerator region"), "Compiler failed to translate OpenMP
#   region", LLVM opt rejecting the generated IR, "Internal compiler
#   error".
# * not_implemented: NVHPC's own "not (yet) implemented", "not supported"
#   ("... is not supported in GPU region", "... not supported in NVIDIA
#   subset", "Only static schedule kind is supported for GPU", "GPU
#   targets do not support ...") and "Unrecognized OpenMP directive" (a
#   warning: the directive is dropped) in a compile that failed.
# * ignored (a compile that succeeded): "OpenMP feature, <X>, not yet
#   implemented in this version of the compiler" and "Unrecognized OpenMP
#   directive - <name>": the compiler says it dropped the feature.
# (only captured patterns: a failure no pattern knows is a harness error,
# never a rejection)
_NV_ICE = (
    r"^nvvmCompileProgram: failed with error",           # nvhpc_ice_nvvm
    r"^nvnvvmd: error: ",                                # nvhpc_ice_nvvm
    r"Compiler failed to translate accelerator region",  # nvhpc_ice_nvvm
    # A front end (fort2, nvcpfe) killed by a signal, also after
    # a diagnostic: the worst message decides (nvhpc_acc_fort2_crash,
    # nvhpc_c_acc_nvcpfe_crash)
    # (signal 9, an OOM or external kill, is the environment:)
    r"^nv\w+-Fatal-\S+ TERMINATED by signal (?!9\b)\d+",
)
# A front end killed by signal 9
_NV_KILLED = (r"^nv\w+-Fatal-\S+ TERMINATED by signal 9\b",)
PATTERNS["nvhpc"] = {
    "environment": COMMON_ENVIRONMENT + _NV_KILLED,   # nvhpc_frontend_killed
    "ice": _NV_ICE,
    "not_implemented": (
        r"^NVFORTRAN-[WSF]-\d+-.*not (?:yet )?implemented",  # nvhpc_not_implemented_linear
        r"^NVFORTRAN-[SF]-\d+-.*not supported",           # nvhpc_not_supported_gpu_region
        r"^NVFORTRAN-[SF]-\d+-.*Only static schedule kind is supported",
        r"^NVFORTRAN-W-\d+-Unrecognized OpenMP directive",  # nvhpc_unrecognized_failed
    ),
    "error": (
        r"^NVFORTRAN-[SF]-\d+-",                          # nvhpc_syntax_error
    ),
    "ignored": (
        r"^NVFORTRAN-W-\d+-OpenMP feature, .* not yet implemented",  # nvhpc_ignored_aligned
        r"^NVFORTRAN-W-\d+-Unrecognized OpenMP directive",  # nvhpc_ignored_unrecognized
    ),
}
PATTERNS["nvhpc:c"] = {
    "environment": COMMON_ENVIRONMENT + _NV_KILLED,
    "ice": _NV_ICE + (
        r"Compiler failed to translate OpenMP region",   # nvhpc_c_ice_translate
        r"Internal compiler error",                      # nvhpc_c_ice_internal
        r"/llvm/bin/opt: \S+: error: ",                  # nvhpc_c_ice_llvm_opt
    ),
    "not_implemented": (
        # nvhpc_c_not_implemented_bind ("is not implemented yet"),
        # nvhpc_c_not_supported_requires ('... "reverse_offload" is not
        # supported')
        r"^NVC\+\+-[WSF]-\d+-.*not (?:yet )?(?:implemented|supported)",
        r"^NVC\+\+-[SF]-\d+-.*Only static schedule kind is supported",
        r"^NVC\+\+-[SF]-\d+-GPU targets do not support",
        r"error: this OpenMP construct is not supported in NVIDIA subset",
    ),
    "error": (
        r'^"\S+", line \d+: (?:catastrophic )?error: ',     # nvhpc_c_invalid_pragma
        r"^NVC\+\+-[SF]-\d+-",                            # nvhpc_c_severe
    ),
    "ignored": (),
}



# GCC 16.2 (gfortran, gcc with -foffload; tools/jobs/gcc_offload_build.sh),
# captured on Tioga (amdgcn) and wingtip (nvptx) from the catalog's own
# compiles (tests/data/messages/gcc_*.txt; the smoke subset and the
# compile-only sweep, tools/campaigns/gcc_compile_sweep.py). gfortran prints the
# location on its own line and the message as "Error: ..." / "Fatal Error:
# ..." (or "<file>:L:C: Error: ..." for a repeat, "f951: Error: ..." for the
# end of the file); gcc prints "<file>:L:C: error: ...". "sorry,
# unimplemented: ..." is GCC's own not-implemented message in both. A
# gfortran warning that a directive is ignored ("... is ignored
# [-Wopenmp]") in a successful compile is "ignored". Only captured
# patterns: an offload link failure no pattern knows stays a harness error
# (unclassified_compile_failure), never a rejection. Coverage parity
# captured GCC's ICEs (gcc_ice_*, gcc_c_ice_*): "internal
# compiler error: ..." from the front end, the middle end and the offload
# compiler's lto1, always the compiler's own failure wherever it is located.
# at the start of a line or after a location or program name ("x.c:20:9: ",
# "lto1: "): never echoed source text
_GCC_ICE = (r"(?:^|: )internal compiler error: ",)
# the offload compiler's own generated assembly that its assembler refuses (mkoffload's .s
# file; a reduced HeCBench program, gcc_c_ice_offload_assembler): the compiler's own failure
_GCC_ASM = (r"^\S*\.mkoffload\.\d+\.s:\d+:\d+: error: ",)
_GCC_SORRY = (r"sorry, unimplemented: ",)  # gcc_sorry_unimplemented
# the program's own sources and headers (a located diagnostic of GCC counts
# only there)
_GCC_SRC = r"^\S+\.(?:c|h|f90|F90|f|F|f95|f03|f08|inc|fh)"
# the offload link (mkoffload): detectors only, _undefined_symbols decides
# program vs system (gcc_link_unresolved_atomic, gcc_link_undefined_probe)
_GCC_LINK = (r"^unresolved symbol \S+", r"^ld: error: undefined symbol: ")
PATTERNS["gcc"] = {
    "environment": COMMON_ENVIRONMENT,
    "ice": _GCC_ICE,
    "not_implemented": _GCC_SORRY,
    "link_undefined": _GCC_LINK,
    "error": (
        # gcc_syntax_error, gcc_unclassifiable_directive, gcc_fatal_module,
        # gcc_error_fatal; gcc_acc_located_error; gcc_f951_error
        r"^(?:Fatal )?Error: ",
        r"^\S+:\d+:\d+: Error: ",
        r"^f951: Error: ",
        # gcc_acc_located_lower_error: the middle end's form ("seq overrides
        # other OpenACC loop specifiers"), at a line of the program's own
        # source (GCC: never a generated .s file the offload
        # assembler, llvm-mc, refuses: that is the compiler's own failure)
        _GCC_SRC + r":\d+:\d+: error: ",
    ),
    "ignored": (
        r"^Warning: .* is ignored \[-Wopenmp\]",  # gcc_ignored_declare_target
    ),
}
PATTERNS["gcc:c"] = {
    "environment": COMMON_ENVIRONMENT,
    "ice": _GCC_ICE + _GCC_ASM,
    "not_implemented": (
        r"^\S+:\d+:\d+: sorry, unimplemented: ",  # gcc_c_sorry_unimplemented
    ),
    # gcc_c_link_unresolved_atomic, gcc_c_link_undefined_probe
    "link_undefined": _GCC_LINK,
    # gcc_c_syntax_error, gcc_c_error_fatal: at a line of the program's
    # own source (GCC: not an assembler's .s line)
    "error": (_GCC_SRC + r":\d+:\d+: (?:fatal )?error: ",),
    "ignored": (),
}

def table_key(toolchain: str, lang: str = "f90") -> str:
    """The message-table key of a toolchain and source language: the
    family (every CCE release shares CCE 19's tables), with ``:c`` for C
."""
    fam = family(toolchain)
    return f"{fam}:c" if lang == "c" else fam


# Recognised notes: warnings that are neither errors nor "ignored", appended
# to the reason as "; note: <name>" so reports can flag the result (also
# from real output: cce_single_thread_warning, afar_version_warning_not_ignored).
NOTES: dict[str, dict[str, str]] = {
    "afar": {
        "version_warning":
            r"is not supported in OpenMP v[\d.]+ on \w+ clause, "
            r"try -fopenmp-version=",
    },
    "cce19": {
        # "An OpenMP parallel construct in a target region is limited to a
        # single thread." (num_threads / if / ordered(n) programs)
        "ftn-7256": r"^ftn-7256 ftn: WARNING",
    },
}

NOTES["afar:c"] = {}
NOTES["cce19:c"] = {}
# NVHPC's deprecation warning for use_device_ptr (5.1 deprecated
# it in favour of use_device_addr), and nvc's internal OpenACC note on a
# loop bind(parallel) in a declare target routine (its lowering)
NOTES["nvhpc"] = {
    "deprecated": r"^NVFORTRAN-W-\d+-Use of the \w+ clause is deprecated",
}
NOTES["gcc"] = {}
NOTES["gcc:c"] = {}
NOTES["nvhpc:c"] = {
    "deprecated": r"warning: The use of \w+ is deprecated",
    "acc_clause_ignored": r"^NVC\+\+-W-\d+-acc loop \w+ clause ignored",
}

CATEGORY_ORDER = ("environment", "ice", "not_implemented", "link_undefined",
                  "error", "ignored")

# Runtime error termination a negative probe (Program.expect ==
# "error_termination") must end with: the runtime's message for an
# absent list item named with the present modifier (captured:
# afar_run_present_map, afar_run_present_motion, cce_run_present).
ERROR_TERMINATION: dict[str, tuple[str, ...]] = {
    "afar": (
        r"device mapping required by 'present' (?:map type|motion) modifier "
        r"does not exist",
    ),
    "cce19": (
        r"CRAY_ACC_ERROR - Variable not found in present table",
    ),
}
# C: AFAR's C programs end with libomptarget's message
# (captured: afar_c_run_present). CCE's C programs never reach a present
# table message: every map with the present modifier aborts in an assertion
# of CCE's offload runtime, also when the item is present (captured:
# cce_c_run_present_assert; data/findings/cce-c-map-present-assert.c), so
# there is no message to accept and the probe reads as a crash
ERROR_TERMINATION["afar:c"] = ERROR_TERMINATION["afar"]
ERROR_TERMINATION["cce19:c"] = ()
# NVHPC's OpenACC runtime (captured: nvhpc_acc_run_present); its
# OpenMP Fortran rejects the present modifier at compile time and its C
# programs run on without a message (no pattern to accept)
ERROR_TERMINATION["nvhpc"] = (
    r"FATAL ERROR: data in PRESENT clause was not found on device",
)
# The OpenACC C programs (nvc -acc) print the same OpenACC runtime
# message (captured: nvhpc_c_acc_run_present); the OpenMP C programs never
# print it (they run on without a message)
ERROR_TERMINATION["nvhpc:c"] = ERROR_TERMINATION["nvhpc"]
# GCC: libgomp's message, the same for OpenMP and OpenACC, Fortran and C
# (captured: gcc_run_present, gcc_acc_run_present, gcc_c_run_present)
ERROR_TERMINATION["gcc"] = (
    r"libgomp: present clause: not present on the device",
)
ERROR_TERMINATION["gcc:c"] = ERROR_TERMINATION["gcc"]
# CCE's present-table miss names the source line of the construct
# (captured: cce_run_present); it counts only at a directive line of the
# program that carries the present modifier
_CCE_MISS_LINE = re.compile(r"find_in_present_table failed for .* from "
                            r"\S+?:(\d+)\s*$", re.M)
_ADDRESS = re.compile(r"0x[0-9a-fA-F]+")

# Compile-output probes (Program.expect "compile_message" /
# "compile_error"): the line of the compiler output that
# shows the error directive's message as a warning or as an error ({token}
# is the program's Program.token). Captured: afar_error_warning,
# afar_error_fatal, cce_error_warning, cce_error_fatal.
COMPILE_DIAGNOSTIC: dict[str, dict[str, str]] = {
    "afar": {"warning": r"warning: {token}", "error": r"error: {token}"},
    "cce19": {"warning": r"OpenMP Compilation Warning : {token}",
              "error": r"OpenMP Compilation Error : {token}"},
    # C (captured afar_c_error_*, cce_c_error_*): clang's
    # "<file>:L:C: warning: <message> [-Wuser-defined-warnings]"
    "afar:c": {"warning": r"warning: {token}", "error": r"error: {token}"},
    "cce19:c": {"warning": r"warning: {token}", "error": r"error: {token}"},
    # Neither NVHPC compiler prints the error directive's message
    # (nvfortran: "Unrecognized OpenMP directive - error"; nvc rejects
    # at(compilation) as "invalid text in pragma"), so no pattern
    "nvhpc": {}, "nvhpc:c": {},
    # GCC (captured gcc_error_warning, gcc_error_fatal: gfortran's
    # "Warning|Error: $OMP ERROR encountered at (1): <message>";
    # gcc_c_error_warning, gcc_c_error_fatal: gcc's "warning|error: 'pragma
    # omp error' encountered: <message>")
    "gcc": {"warning": r"^Warning: \$OMP ERROR encountered at \(1\): {token}",
            "error": r"^Error: \$OMP ERROR encountered at \(1\): {token}"},
    "gcc:c": {"warning": r"warning: .pragma omp error. encountered: {token}",
              "error": r"error: .pragma omp error. encountered: {token}"},
}


def _diagnostic(tc: Toolchain, kind: str, token: str, text: str) -> str | None:
    pat = COMPILE_DIAGNOSTIC.get(table_key(tc.name, tc.lang), {}).get(kind)
    if not pat or not token:
        return None
    m = re.search(pat.format(token=re.escape(token)), text, re.M)
    if m is None:
        return None
    return text[text.rfind("\n", 0, m.start()) + 1:].split("\n", 1)[0].strip()


_SUMMARY = re.compile(r"\s*ftn-(855|894) ftn: ")


def classify_message(toolchain: str, text: str,
                     categories: Iterable[str] = CATEGORY_ORDER,
                     lang: str = "f90") -> tuple[str, str] | None:
    """The first category (in `categories` order) with a pattern matching
    `text`, and the full line it matched; None if nothing matches. An
    unknown toolchain name uses the common environment patterns only.
    `lang` "c" selects the C compiler's table."""
    table = PATTERNS.get(table_key(toolchain, lang),
                         {"environment": COMMON_ENVIRONMENT})
    for cat in categories:
        if cat == "link_undefined":
            if any(re.search(p, text, re.M) for p in table.get(cat, ())):
                found = _undefined_symbols(text)
                if found:
                    return found
            continue
        for pat in table.get(cat, ()):
            ms = list(re.finditer(pat, text, re.M))
            # CCE: prefer the root error to the module summaries (ftn-855
            # "errors in module", ftn-894 "module has compile errors")
            m = next((x for x in ms if not _SUMMARY.match(
                text[text.rfind("\n", 0, x.start()) + 1:])), ms[0] if ms
                else None)
            if m:
                start = text.rfind("\n", 0, m.start()) + 1
                lines = text[start:].split("\n")
                line = lines[0].strip()
                # CCE puts the message text on the line after "ftn-N ftn:"
                if re.match(r"ftn-\d+ ftn: ", line) and len(lines) > 1:
                    line += " | " + lines[1].strip()
                return cat, line
    return None


# (decisions, groups capacity-large-args and
# capacity-microtask-args): a run-time message by which the offload runtime
# says the program exceeds one of its capacities (hundreds of mapped
# arrays or reduction scalars in one kernel). The program is conforming;
# capacity is the processor's (Fortran 2008 §1.1, C18 §1 p.2): a capacity
# break point, never a compiler failure. Captured: cce_run_large_args,
# afar_run_microtask_args.
CAPACITY: dict[str, tuple[str, ...]] = {
    "cce": (r"CRAY_ACC_ERROR - Large args not supported",),
    "afar": (r"Too many arguments in kmp_invoke_microtask",),
}


def capacity_message(toolchain: str, text: str) -> str | None:
    """The line of a run's output by which the runtime of `toolchain`
    reports a capacity limit (``CAPACITY``), or None."""
    fam = "cce" if toolchain.startswith("cce") else \
        "afar" if toolchain.startswith("afar") else toolchain
    for pat in CAPACITY.get(fam, ()):
        m = re.search(pat, text or "")
        if m:
            start = (text or "").rfind("\n", 0, m.start()) + 1
            return text[start:].split("\n", 1)[0].strip()
    return None


CODES = {"environment": "environment", "ice": "ice",
         "not_implemented": "not_implemented",
         "link_undefined": "link_undefined_symbol", "error": "diagnostic"}


def classify_all(toolchain: str, text: str,
                 categories: Iterable[str] = CATEGORY_ORDER,
                 lang: str = "f90") -> list[tuple[str, str]]:
    """Every category (in `categories` order, worst first) with
    a pattern matching some message of `text`, with the line it matched
    (``classify_message`` per category). The first entry is the worst
    class, which classifies the failure; a failure is never classified
    by its first message alone (a rejection followed by a front end's
    crash is an ICE)."""
    out = []
    for cat in categories:
        found = classify_message(toolchain, text, (cat,), lang)
        if found:
            out.append(found)
    return out


def messages_of(toolchain: str, text: str, lang: str = "f90") -> str:
    """The classified messages of a failed compile, worst first, as
    ``"<code>: <line> | <code>: <line>"`` (Result.messages)."""
    return " || ".join(f"{CODES[c]}: {line}" for c, line in classify_all(
        toolchain, text, CATEGORY_ORDER[:-1], lang))


_LD_REF = re.compile(r"^\S*ld: (\S+?): undefined reference to `")
_LD_FUNC = re.compile(r"^\S*ld: (\S+?): in function ")
_LLD_BY = re.compile(r"^>>> referenced by (\S+?)(?::\(|\s|$)")
# the system directories and every compiler install of the catalog (an
# AFAR release directory sits in the vendor directory with its siblings:
# that directory)
_SYSTEM_PREFIXES = ("/opt/", "/usr/", "/lib", "/collab/") + tuple(
    (str(Path(r).parent) if Path(r).name.startswith("therock-afar") else r.rstrip("/")) + "/"
    for r in install_roots())


def _is_system(path: str) -> bool:
    """A file of the installed toolchain or system, not of the program."""
    return (re.search(r"\.so(\.\d+)*$", path) is not None
            or path.startswith(_SYSTEM_PREFIXES) or "/rocm" in path)


def _undefined_symbols(text: str) -> tuple[str, str] | None:
    """Classify a link failure on undefined symbols by WHO references them:
    any system library or toolchain file -> ("environment", line); only the
    program's own objects (in the per-run directory: <tmp>/pe_*/<prog>_1.o,
    CCE's generated a.out-cce-openmp__llc.amdgpu) -> ("link_undefined",
    line); no referrer found -> None (an unclassified failure)."""
    lines = text.split("\n")
    program: str | None = None
    for i, line in enumerate(lines):
        refs: list[str] = []
        if "undefined reference to `" in line:
            m = _LD_REF.match(line)
            if m:
                refs.append(m.group(1))
            else:  # "<obj>:(.text+0x..): ..." after "ld: <file>: in function"
                for back in reversed(lines[:i]):
                    f = _LD_FUNC.match(back)
                    if f:
                        refs.append(f.group(1))
                        break
        elif line.startswith("unresolved symbol "):
            # GCC's nvptx-ld (the offload link in mkoffload) names no
            # referrer: it links the program's device image with the
            # toolchain's archives, so the reference is the program's
            if program is None:
                program = line.strip()
            continue
        elif "ld: error: undefined symbol: " in line:
            # lld as "ld.lld:", "lld:" or (GCC's amdgcn offload link) "ld:"
            for nxt in lines[i + 1:]:
                m = _LLD_BY.match(nxt)
                if not nxt.startswith(">>>"):
                    break
                if m:
                    refs.append(m.group(1))
        for ref in refs:
            if _is_system(ref):
                return "environment", line.strip()
            if program is None:
                program = line.strip()
    return ("link_undefined", program) if program else None


# --- running commands ------------------------------------------------------------------

@dataclass(frozen=True)
class _Exec:
    rc: int | None          # None after a timeout
    stdout: str
    stderr: str

    @property
    def timed_out(self) -> bool:
        return self.rc is None


def _kill_group(pgid: int) -> None:
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


# On a shared node without a scheduler (wingtip) at most one
# program runs on a GPU at a time while compiles stay parallel:
# COMPLIANT_RUN_SLOTS=1 makes every program run take an exclusive lock on
# a file per visible GPU (CUDA_VISIBLE_DEVICES; flock, so threads and the
# worker processes of a multiprocessing pool alike wait for it;
# tools/jobs/run_wingtip.sh). A run script is one that ends by exec-ing the
# program (harness.run_script, offload.engine.confirm.execute.run_script); the
# timeout starts once the lock is held. Unset (Tuolumne, Tioga): no lock,
# nothing changes.
def _run_lock_path() -> str | None:
    if not os.environ.get("COMPLIANT_RUN_SLOTS"):
        return None
    if os.environ["COMPLIANT_RUN_SLOTS"] != "1":
        raise ValueError("COMPLIANT_RUN_SLOTS supports 1 (one program per "
                         "GPU) only")
    gpu = os.environ.get("CUDA_VISIBLE_DEVICES", "all").replace(",", "_")
    return os.path.join(tempfile.gettempdir(),
                        f"compliant-run-{os.getuid()}-gpu{gpu}.lock")


def _is_run_script(script: str) -> bool:
    lines = script.rstrip().split("\n")
    return bool(lines) and lines[-1].startswith("exec ")


def _execute(script: str, cwd: Path, timeout_s: float,
             merge: bool = False) -> _Exec:
    """Run `script` with bash in its own process group; kill the whole group
    at the timeout and after the script ends (no stray children), and end
    the group when the runner dies or stops (``_die_with_parent``, the
    watchdog). A
    program run waits for the GPU's run lock first when
    COMPLIANT_RUN_SLOTS is set."""
    lock = _run_lock_path()
    if lock is not None and _is_run_script(script):
        import fcntl
        with open(lock, "a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                return _execute_now(script, cwd, timeout_s, merge)
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)
    return _execute_now(script, cwd, timeout_s, merge)


@lru_cache(maxsize=None)
def _prctl():
    """libc's prctl, loaded in the parent (a preexec_fn must not import:
    another thread may hold the import lock at the fork); None where there
    is none."""
    try:
        import ctypes
        return ctypes.CDLL(None, use_errno=True).prctl
    except (OSError, AttributeError):
        return None


def _die_with_parent(parent: int, sig: int = signal.SIGKILL):
    """A preexec_fn: the child gets `sig` when the thread that started it
    exits (Linux PR_SET_PDEATHSIG, kept across exec).
    The run is in its own session, so killing the runner (a campaign
    stopped by hand, a pool worker that dies) did not reach it: n1x0 seed
    72 ran on two A100s for 12.5 hours after its first campaign was
    stopped. Without prctl: nothing."""
    prctl = _prctl()

    def setup() -> None:
        if prctl is None:
            return
        prctl(1, int(sig), 0, 0, 0)  # PR_SET_PDEATHSIG
        if os.getppid() != parent:  # the runner died before the prctl
            os._exit(1)
    return setup


# The death signal reaches the direct
# child only, so a compiler or program the script starts survived its
# runner (seed 72; the six-day AFAR clangs ran outside the
# harness). Every run therefore has a watchdog: a small bash process in its
# own session (outside the run's process group) whose stdin is the read end
# of a pipe only the runner holds the write end of. It wakes when that pipe
# reaches EOF (the runner died, by any signal: the kernel closes its fds) or
# at the limit plus GRACE_S (the runner's own timer normally fires first;
# this covers a stopped or hung runner). Either way it sends the run's whole
# process group SIGTERM, then SIGKILL after KILL_AFTER_S, so a grandchild
# that ignores TERM is ended too. The runner stops the watchdog when the run
# is over. A pipe, not a death signal, tells the watchdog: there is no
# window before a trap is installed, and it does not depend
# on the forking thread (PR_SET_PDEATHSIG fires when the *thread* that
# forked exits). The direct child keeps PR_SET_PDEATHSIG (SIGKILL): every
# caller (thread pools in run_matrix, mutate, minimize, the tests' bounded
# map, ...) blocks in _execute until the run is over, and a Python thread
# cannot exit inside a call, so its thread outlives its run. Limits: a
# descendant that leaves the run's process group (setsid, setpgid: a job
# launcher such as srun, mpirun or flux) is reached neither by the runner's
# killpg nor by the watchdog; and a process forked (without exec) while a
# runner holds its pipe keeps the pipe open, so the watchdog then waits for
# its deadline. (Fix used coreutils timeout, which exits as soon as
# its child does and so never sent the KILL to a TERM-ignoring grandchild;
# The watchdog took SIGTERM by PR_SET_PDEATHSIG.)
KILL_AFTER_S = 10
GRACE_S = 2
_WATCHDOG = r"""
g=$1; k=$2
read -r -t "$3" _
kill -TERM -- "-$g" 2>/dev/null || exit 0
sleep "$k"
kill -KILL -- "-$g" 2>/dev/null
exit 0
"""


@dataclass
class Watchdog:
    proc: subprocess.Popen
    runner_end: int | None   # the pipe's write end, held by the runner

    def close_runner_end(self) -> None:
        if self.runner_end is not None:
            os.close(self.runner_end)
            self.runner_end = None


def watch_group(pgid: int, limit_s: float,
                kill_after_s: float = KILL_AFTER_S) -> Watchdog | None:
    """Start the watchdog (above) of a process group the caller started
    (Popen(..., start_new_session=True): pgid is its pid): at EOF of the
    caller's pipe (the caller died) or `limit_s` seconds from now it sends
    the group SIGTERM, then SIGKILL `kill_after_s` seconds later. The caller
    must call ``stop_watch`` when the group is done (or killed). None if the
    watchdog cannot start. Shared with offload.engine.stress_exec.run_group
."""
    r, w = os.pipe()  # not inheritable: only the watchdog gets r (stdin)
    try:
        proc = subprocess.Popen(
            ["bash", "-c", _WATCHDOG, "watchdog", str(pgid),
             f"{kill_after_s:g}", f"{limit_s:g}"],
            stdin=r, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
    except OSError:
        os.close(w)
        return None
    finally:
        os.close(r)
    return Watchdog(proc, w)


def stop_watch(dog: Watchdog | None) -> None:
    """Stop a watchdog of ``watch_group`` (its whole group, then the
    caller's pipe); None: nothing."""
    if dog is not None:
        _kill_group(dog.proc.pid)
        dog.proc.wait()
        dog.close_runner_end()


def _watchdog(pgid: int, timeout_s: float) -> Watchdog | None:
    """The watchdog of a harness run: the limit plus GRACE_S."""
    return watch_group(pgid, timeout_s + GRACE_S)


_stop_watchdog = stop_watch


def _execute_now(script: str, cwd: Path, timeout_s: float,
                 merge: bool = False) -> _Exec:
    # the caller's OpenMP/offload settings must not leak into a run (the
    # scripts set what they need); ROCR_*/other HSA_* stay, since a batch
    # allocation may use them to assign the GPU;
    # GCC's libgomp reads GOMP_* and GCN_* (GOMP_DEBUG, GCN_STACK_SIZE)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("OMP_", "LIBOMPTARGET_", "CRAY_ACC_",
                                "NVCOMPILER_", "ACC_", "GOMP_",
                                "GCN_"))}
    env.pop("HSA_XNACK", None)
    env["TMPDIR"] = str(cwd)
    p = subprocess.Popen(["bash", "-c", script], cwd=cwd, env=env,
                         stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT if merge else subprocess.PIPE,
                         text=True, errors="replace", start_new_session=True,
                         preexec_fn=_die_with_parent(os.getpid()))
    dog = _watchdog(p.pid, timeout_s)
    try:
        try:
            out, err = p.communicate(timeout=timeout_s)
            rc: int | None = p.returncode
        except subprocess.TimeoutExpired:
            _kill_group(p.pid)
            try:
                out, err = p.communicate(timeout=10)
            except subprocess.TimeoutExpired:  # a process left the group
                p.kill()
                out, err = "", ""
            rc = None
        _kill_group(p.pid)
    finally:
        _stop_watchdog(dog)
    return _Exec(rc, out or "", err or "")


def _setup(tc: Toolchain, tmpdir: str | None) -> list[str]:
    # TMPDIR is exported AFTER the prelude: /etc/profile (sourced by the
    # CCE prelude) resets it to the user's /var/tmp directory
    lines = ["ulimit -c 0"]
    if tc.prelude:
        lines += [tc.prelude, "ulimit -c 0"]
    if tmpdir is not None:
        lines.append(f"export TMPDIR={shlex.quote(tmpdir)}")
    return lines


def compile_script(tc: Toolchain, src: str, exe: str, opt: str,
                   tmpdir: str | None = None) -> str:
    """The bash script that compiles `src` (non-strict, no pipes, no core
    dumps, the prelude, TMPDIR, then the prelude-free compile_cmd)."""
    bare = dataclasses.replace(tc, prelude="")
    return "\n".join(_setup(tc, tmpdir)
                     + [bare.compile_cmd(src, exe, opt)]) + "\n"


# Files of a set that are included, not compiled (headers)
HEADER_SUFFIXES = (".h", ".hh", ".hpp", ".hxx", ".inc", ".fh", ".fi")


def object_names(files: list[str]) -> list[tuple[str, str]]:
    """[(source, object)] of the translation units of a file set, in
    order: every suffix is replaced (.f90, .F90, .f, .F, .c, .cpp, ...;
    task-40a-review: a ``.F90`` name kept its suffix and ``-o x.F90``
    overwrote the source), a name without a suffix gets ``.o`` appended,
    two sources with one stem get distinct objects, and headers
    (``HEADER_SUFFIXES``) are not compiled."""
    out, used = [], set()
    for k, f in enumerate(files):
        p = Path(f)
        if p.suffix.lower() in HEADER_SUFFIXES:
            continue
        obj = str(p.with_suffix(".o")) if p.suffix else f + ".o"
        if obj in used or obj == f:
            obj = str(p.with_name(f"{p.stem}_{k}.o"))
        used.add(obj)
        out.append((f, obj))
    return out


def compile_set_script(tc: Toolchain, files: list[str], exe: str, opt: str,
                       tmpdir: str | None = None) -> str:
    """The bash script that compiles a set of files (a fuzz
    bundle) one translation unit at a time with -c, in the given order
    (modules before their users), then links the objects; each step runs
    only if the previous one succeeded (&&, no strict mode)."""
    bare = dataclasses.replace(tc, prelude="")
    pairs = object_names(files)
    steps = [bare.compile_cmd(f"-c {f}", o, opt) for f, o in pairs]
    objs = " ".join(o for _, o in pairs)
    steps.append(bare.compile_cmd(objs, exe, opt))
    return "\n".join(_setup(tc, tmpdir) + [" && \\\n".join(steps)]) + "\n"


def run_script(tc: Toolchain, exe: str, xnack: int, mandatory: bool,
               tmpdir: str | None = None, offload: str | None = None) -> str:
    """The bash script that runs `exe` (non-strict, no pipes, no core
    dumps, the toolchain prelude, TMPDIR, memory mode, offload policy; an
    OpenACC toolchain has no offload policy). `offload`, when given, is the
    OMP_TARGET_OFFLOAD value and overrides `mandatory` (the host
    reference runs use "disabled")."""
    lines = _setup(tc, tmpdir)
    lines += [f"export {k}={shlex.quote(v)}"
              for k, v in tc.run_env(xnack).items()]
    if tc.model == "acc":
        lines.append("unset OMP_TARGET_OFFLOAD")
    elif offload is not None:
        lines.append(f"export OMP_TARGET_OFFLOAD={shlex.quote(offload)}")
    else:
        lines.append("export OMP_TARGET_OFFLOAD=mandatory" if mandatory
                     else "unset OMP_TARGET_OFFLOAD")
    lines.append(f"exec {shlex.quote(exe)}")
    return "\n".join(lines) + "\n"


# --- one run (primary, then without mandatory if needed) ----------------------------

RESULT_RE = re.compile(r"^RESULT ran_on_host=([01]) check=(pass|fail)\s*$",
                       re.M)


@dataclass(frozen=True)
class _Trial:
    outcome: Outcome
    reason: str
    stdout: str
    stderr: str


def _observation(ex: _Exec) -> tuple[int, str] | None:
    found = RESULT_RE.findall(ex.stdout)
    if ex.rc == 0 and len(found) == 1:
        return int(found[0][0]), found[0][1]
    return None


def _failure(ex: _Exec) -> str:
    if ex.timed_out:
        return "timeout"
    if ex.rc is not None and ex.rc < 0:
        try:
            return f"crash: {signal.Signals(-ex.rc).name}"
        except ValueError:
            return f"crash: signal {-ex.rc}"
    if ex.rc != 0:
        return f"exit_status: {ex.rc}"
    if len(RESULT_RE.findall(ex.stdout)) > 1:
        return "multiple_result_lines"
    return "no_result_line"


def _from_observation(obs: tuple[int, str]) -> tuple[Outcome, str]:
    host, check = obs
    text = f"ran_on_host={host} check={check}"
    if check == "fail":
        return Outcome.wrong_answer, f"check_fail: {text}"
    return (Outcome.fell_back_to_host if host else Outcome.correct_on_device,
            text)


def _env_failure(tc: Toolchain, ex: _Exec) -> str | None:
    found = classify_message(tc.name, ex.stdout + "\n" + ex.stderr,
                             ("environment",), tc.lang)
    return f"environment: {found[1]}" if found else None


def _trial(tc: Toolchain, exe: Path, xnack: int, cwd: Path,
           timeout_s: float) -> _Trial:
    first = _execute(run_script(tc, str(exe), xnack, True, str(cwd)), cwd,
                     timeout_s)
    log = f"--- run (OMP_TARGET_OFFLOAD=mandatory, rc={first.rc}) ---\n" \
        + first.stderr
    if first.timed_out:
        return _Trial(Outcome.wrong_answer, "timeout", first.stdout, log)
    obs = _observation(first)
    if obs:
        return _Trial(*_from_observation(obs), first.stdout, log)
    env = _env_failure(tc, first)
    if env:
        return _Trial(Outcome.harness_error, env, first.stdout, log)
    why = _failure(first)
    if tc.model == "acc":  # one run: no offload policy to relax
        return _Trial(Outcome.wrong_answer, why, first.stdout, log)
    second = _execute(run_script(tc, str(exe), xnack, False, str(cwd)), cwd,
                      timeout_s)
    log += f"\n--- run (OMP_TARGET_OFFLOAD unset, rc={second.rc}) ---\n" \
        + second.stderr
    out = first.stdout + second.stdout
    env = _env_failure(tc, second)
    if env:
        return _Trial(Outcome.harness_error, f"{env}; mandatory run: {why}",
                      out, log)
    obs = _observation(second)
    if obs is None:
        return _Trial(Outcome.wrong_answer,
                      f"{why}; without mandatory: {_failure(second)}", out, log)
    outcome, text = _from_observation(obs)
    if outcome == Outcome.correct_on_device:
        return _Trial(Outcome.wrong_answer,
                      f"mandatory_failed_device_pass_without: {why}; "
                      f"without mandatory: {text}", out, log)
    if outcome == Outcome.fell_back_to_host:
        return _Trial(outcome, f"mandatory_refused: {why}; without "
                      f"mandatory: {text}", out, log)
    return _Trial(outcome, f"{text}; mandatory run: {why}; without "
                  "mandatory", out, log)


_DIRECTIVE_START = re.compile(r"^\s*(?:!\$omp|!\$acc|#\s*pragma\s+(?:omp|acc))",
                              re.I)


def _directive_at(lines: list[str], k: int) -> str | None:
    """The whole directive that physical line k (1-based) belongs to: its
    first line with every continuation line (Fortran ``&`` / ``!$omp&``,
    C backslash), lowercased; None when line k is not in a directive."""
    if not 1 <= k <= len(lines):
        return None
    cont = ("&", "\\")
    i = j = k - 1
    while i > 0 and lines[i - 1].rstrip().endswith(cont):
        i -= 1
    while j < len(lines) - 1 and lines[j].rstrip().endswith(cont):
        j += 1
    if not _DIRECTIVE_START.match(lines[i]):
        return None
    return " ".join(lines[i:j + 1]).lower()


def _probe_line_ok(tc: Toolchain, source: str, text: str) -> bool:
    """For CCE, the present-table miss must be at a directive carrying the
    present modifier, on the named line or on one of the directive's
    continuation lines; AFAR's message is
    specific to the modifier."""
    if family(tc.name) != "cce19":
        return True
    lines = source.splitlines()
    for m in _CCE_MISS_LINE.finditer(text):
        d = _directive_at(lines, int(m.group(1)))
        if d is not None and "present" in d:
            return True
    return False


def probe_termination(toolchain: str, lang: str, source: str,
                      text: str) -> str | None:
    """The line of a run's output (`text`: stdout and stderr) that shows
    the negative probe's error termination on `toolchain`
    (ERROR_TERMINATION of its family and language, with the line check of
    ``_probe_line_ok``), or None. Shared by the harness and
    offload.engine.expected.run_on."""
    tc = Toolchain(toolchain, "", "", lang=lang) \
        if not isinstance(toolchain, Toolchain) else toolchain
    for pat in ERROR_TERMINATION.get(table_key(tc.name, tc.lang), ()):
        m = re.search(pat, text, re.M)
        if m and _probe_line_ok(tc, source, text):
            return text[text.rfind("\n", 0, m.start()) + 1:].split(
                "\n", 1)[0]
    return None


def _error_trial(tc: Toolchain, exe: Path, xnack: int, cwd: Path,
                 timeout_s: float, source: str = "") -> _Trial:
    """One run of a negative probe (Program.expect == "error_termination"),
    with OMP_TARGET_OFFLOAD=mandatory only (a host fallback cannot pass
    silently: the runtime aborts with another message). Abnormal end (or no
    RESULT line) with a message of ERROR_TERMINATION[toolchain] ->
    correct_on_device (``error_termination: <line>``); a completed run
    (it prints check=fail) -> wrong_answer (``no_error_termination:
    ...``); any other failure -> wrong_answer (``...; no expected error
    message``); an environment failure -> harness_error."""
    first = _execute(run_script(tc, str(exe), xnack, True, str(cwd)), cwd,
                     timeout_s)
    log = f"--- run (OMP_TARGET_OFFLOAD=mandatory, rc={first.rc}) ---\n" \
        + first.stderr
    if first.timed_out:
        return _Trial(Outcome.wrong_answer, "timeout", first.stdout, log)
    obs = _observation(first)
    if obs:
        host, check = obs
        return _Trial(Outcome.wrong_answer, f"no_error_termination: "
                      f"ran_on_host={host} check={check}", first.stdout, log)
    env = _env_failure(tc, first)
    if env:
        return _Trial(Outcome.harness_error, env, first.stdout, log)
    text = first.stdout + "\n" + first.stderr
    line = probe_termination(tc, tc.lang, source, text)
    if line is not None:
        # no host address in the reason: repeats compare reasons
        line = _ADDRESS.sub("0x...", line.strip())
        return _Trial(Outcome.correct_on_device,
                      f"error_termination: {line}", first.stdout, log)
    return _Trial(Outcome.wrong_answer, f"{_failure(first)}; no expected "
                  "error message", first.stdout, log)


# --- the whole program ------------------------------------------------------------------

_SECTION_MAX = 16000


def _clip(text: str) -> str:
    if len(text) <= _SECTION_MAX:
        return text
    half = _SECTION_MAX // 2
    return (text[:half] + f"\n[... {len(text) - _SECTION_MAX} characters "
            "omitted ...]\n" + text[-half:])


@lru_cache(maxsize=None)
def _rocm(tc: Toolchain) -> str | None:
    try:
        return loaded_rocm_version(tc)
    except (subprocess.CalledProcessError, OSError):
        return None


def detect_thp() -> str:
    """The kernel's transparent huge page mode ("always", "madvise",
    "never"), or "unknown"."""
    try:
        text = Path("/sys/kernel/mm/transparent_hugepage/enabled").read_text()
    except OSError:
        return "unknown"
    m = re.search(r"\[(\w+)\]", text)
    return m.group(1) if m else "unknown"


def gpu_text() -> str:
    """This node's GPU as recorded in a row: "<gfx> <name>"."""
    return " ".join(x for x in detect_gpu() if x)


def wrong_arch(tc: Toolchain) -> str | None:
    """The reason a toolchain cannot run on this node: its arch
    differs from the node's GPU; None when they match or the node's GPU is
    unknown (no rocminfo)."""
    gfx = detect_gpu()[0]
    if not gfx and tc.arch.startswith("sm_"):
        # Under OMP_TARGET_OFFLOAD=mandatory an NVHPC program on a
        # node with no visible GPU aborts with no message, and without it
        # runs on the host: that would read as a host fallback (GCC's
        # libgomp likewise: no device, so host fallback)
        return ("environment: no_gpu: toolchain {} needs an NVIDIA GPU "
                "and none is visible (nvidia-smi, CUDA_VISIBLE_DEVICES)"
                .format(tc.name))
    if gfx and gfx != tc.arch:
        return (f"environment: wrong_arch: toolchain {tc.name} targets "
                f"{tc.arch}, this node's GPU is {gfx}")
    return None


def _spec_version(prog: Program) -> int:
    m = re.match(r"(?:omp|acc)(\d\d)-", prog.id)
    return int(m.group(1)) if m else 0


# A C program that includes the math headers links the C math
# library, as omp_vv's make.def does for every C test (offload.engine.baseline
# C_EXTRA); on AMD GPUs -lm also selects the device math library.
_LIBM = re.compile(r"^\s*#\s*include\s*<(?:math|complex|tgmath)\.h>", re.M)


def with_libm(tc: Toolchain, prog: Program) -> Toolchain:
    """`tc` with ``-lm`` for a C program that includes <math.h>,
    <complex.h> or <tgmath.h>; otherwise `tc` unchanged."""
    if prog.lang == "c" and _LIBM.search(prog.source) and \
            "-lm" not in tc.extra.split():
        return dataclasses.replace(tc, extra=f"{tc.extra} -lm".strip())
    return tc


def _flags(tc: Toolchain, opt: str) -> str:
    return f"{tc.flags()} {opt}"


def _provenance(tc: Toolchain, xnack: int, build_dir: str,
                flags: str, outcome: Outcome) -> dict:
    """The provenance fields of a row (offload.engine.provenance)."""
    from offload.engine import provenance as PV
    try:
        env = dict(tc.run_env(xnack))
    except ValueError:          # a mode the toolchain has not: no run
        env = dict(tc.env)
    env["OMP_TARGET_OFFLOAD"] = "unset" if tc.model == "acc" else \
        "mandatory"
    # a harness error says nothing about the program: never gated
    f = PV.fields(tc, build_dir, flags, env,
                  outcome not in (Outcome.correct_on_device,
                                  Outcome.unobservable,
                                  Outcome.harness_error))
    f.pop("flags")              # Result.flags is the row's own field
    return f

# Functions called with every failing Result (the reproduction
# gate's hook, offload.engine.gate.hook: a campaign runner registers one to
# queue its failures; nothing is registered by default)
GATE_HOOKS: list = []


def _gated(res: Result) -> Result:
    if res.gate == "pending":
        for hook in list(GATE_HOOKS):
            hook(res)
    return res


def _build_dir(build_dir: str | Path | None) -> Path:
    """The per-call build directory: a fresh mkdtemp ("harness_"), or
    (the reproduction gate's environments) the given path, which
    must not exist yet (it is created, with its parents, and removed after
    the call)."""
    if build_dir is None:
        return Path(tempfile.mkdtemp(prefix="harness_"))
    path = Path(build_dir)
    if path.exists():
        raise FileExistsError(f"build directory {path} exists")
    path.mkdir(parents=True)
    return path


def run_program(prog: Program, tc: Toolchain, xnack: int, opt: str = "-O2",
                timeout_s: int = 300, repeats: int = 3, *,
                version: int | None = None, thp: str | None = None,
                compile_timeout_s: int = 900,
                build_dir: str | Path | None = None) -> Result:
    """Compile `prog` with `tc`, run it under HSA_XNACK=`xnack` and classify
    the outcome (see the module docstring for the rules and policies).
    `build_dir`: build in this path instead of a fresh
    temporary directory (it must not exist; it is removed afterwards)."""
    return _gated(_run_program(prog, tc, xnack, opt, timeout_s, repeats,
                               version, thp, compile_timeout_s, build_dir))


def _run_program(prog: Program, tc: Toolchain, xnack: int, opt: str,
                 timeout_s: int, repeats: int, version: int | None,
                 thp: str | None, compile_timeout_s: int,
                 build_dir: str | Path | None) -> Result:
    if tc.model != prog.model:  # the program's model decides the flags
        tc = dataclasses.replace(tc, model=prog.model)
    lang = "c" if prog.lang == "c" else "f90"
    if tc.lang != lang:  # and its language the compiler
        tc = dataclasses.replace(tc, lang=lang)
    tc = tc.for_mode(xnack)  # NVHPC builds per memory mode
    tc = with_libm(tc, prog)  
    base = dict(program_id=prog.id, primary_atom=prog.primary_atom,
                atoms=tuple(sorted(prog.atoms)), toolchain=tc.name,
                xnack=xnack, opt=opt, flags=_flags(tc, opt), rocm=_rocm(tc),
                device=device_of(tc), compiler=compiler_version(tc),
                needs=tuple(prog.needs), evidence=prog.evidence,
                observable=prog.observable, legal=prog.legal,
                violates=prog.violates,
                version=_spec_version(prog) if version is None else version,
                thp=detect_thp() if thp is None else thp, model=prog.model,
                lang=lang, scope=getattr(prog, "scope", "device"),
                machine=tc.machine, arch=tc.arch, gpu=gpu_text())
    bad_arch = wrong_arch(tc)
    if bad_arch:
        # not built: "-" as the build directory (provenance stays complete)
        return Result(outcome=Outcome.harness_error, reason=bad_arch,
                      flaky=False, stdout="", stderr="", **base,
                      **_provenance(tc, xnack, "-", base["flags"],
                                    Outcome.harness_error))
    tmp = _build_dir(build_dir)
    try:
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", prog.id) or "prog"
        src = tmp / f"{name}.{'c' if lang == 'c' else 'f90'}"
        exe = tmp / f"{name}.out"
        src.write_text(prog.source)
        build = _execute(compile_script(tc, str(src), str(exe), opt,
                                        str(tmp)),
                         tmp, compile_timeout_s, merge=True)
        clog = f"--- compile (rc={build.rc}) ---\n" + _clip(build.stdout)

        def scrub(text: str) -> str:
            # the per-call directory name differs on every call; replace it
            # (absolute, and relative as CCE prints it) so results compare
            return text.replace(str(tmp), "<tmpdir>").replace(tmp.name,
                                                              "<tmpdir>")

        def result(outcome, reason, stdout="", stderr="", flaky=False):
            return Result(outcome=outcome, reason=scrub(reason), flaky=flaky,
                          stdout=scrub(_clip(stdout)),
                          stderr=scrub(clog + ("\n" + _clip(stderr) if stderr
                                               else "")), **base,
                          **_provenance(tc, xnack, str(tmp), base["flags"],
                                        outcome))

        if build.timed_out:
            return result(Outcome.harness_error, "compile_timeout")
        # compile-output probes
        if prog.expect in ("compile_message", "compile_error"):
            fatal = _diagnostic(tc, "error", prog.token, build.stdout)
            if build.rc != 0 and fatal:
                if prog.expect == "compile_error":
                    return result(Outcome.correct_on_device,
                                  f"compile_error_termination: {fatal}")
                return result(Outcome.wrong_answer, "check_fail: compile-time "
                              "error termination where severity(warning) "
                              f"requires a warning: {fatal}")
            if build.rc == 0 and prog.expect == "compile_error":
                return result(Outcome.wrong_answer, "check_fail: no "
                              "compile-time error termination (the "
                              "compilation went on)")
            shown = _diagnostic(tc, "warning", prog.token, build.stdout)
            if build.rc == 0 and not shown:
                return result(Outcome.wrong_answer, "check_fail: no "
                              "compile-time message with the token in the "
                              "compiler output")
        if build.rc != 0:
            found = classify_message(tc.name, build.stdout,
                                     CATEGORY_ORDER[:-1], lang)
            if found is None:
                return result(Outcome.harness_error,
                              f"unclassified_compile_failure: rc={build.rc}")
            cat, line = found
            msgs = scrub(messages_of(tc.name, build.stdout, lang))
            if cat == "environment":
                return dataclasses.replace(result(
                    Outcome.harness_error, f"environment: {line}"),
                    messages=msgs)
            return dataclasses.replace(result(
                Outcome.rejected, f"{CODES[cat]}: {line}"), messages=msgs)
        if not exe.is_file():
            return result(Outcome.harness_error,
                          "no_executable: the compiler exited 0 but wrote "
                          "no executable")
        notes = "".join(f"; note: {name}" for name, pat in
                        NOTES.get(table_key(tc.name, lang), {}).items()
                        if re.search(pat, build.stdout, re.M))
        if prog.expect == "error_termination":
            def trial(*a):
                return _error_trial(*a, source=prog.source)
        else:
            trial = _trial
        ignored = classify_message(tc.name, build.stdout, ("ignored",), lang)
        if ignored:
            t = trial(tc, exe, xnack, tmp, timeout_s)
            return result(Outcome.accepted_ignored,
                          f"ignored: {ignored[1]}; run: {t.outcome}: "
                          f"{t.reason}{notes}", t.stdout, t.stderr)
        trials: list[_Trial] = []
        for _ in range(max(1, repeats)):
            t = trial(tc, exe, xnack, tmp, timeout_s)
            trials.append(t)
            if "timeout" in t.reason or t.outcome == Outcome.harness_error:
                break
        worst = min(trials, key=lambda t: WORST_FIRST.index(t.outcome))
        flaky = len({(t.outcome, t.reason) for t in trials}) > 1
        outcome, reason = worst.outcome, worst.reason
        if outcome == Outcome.correct_on_device and not prog.observable:
            outcome = Outcome.unobservable
            reason += " (device kernel ran; the atom has no checked effect)"
        if flaky:
            reason += "; repeats: " + " | ".join(
                f"{t.outcome}: {t.reason}" for t in trials)
        if prog.expect == "compile_message":
            reason += "; compile message: " + _diagnostic(
                tc, "warning", prog.token, build.stdout)
        return result(outcome, reason + notes, worst.stdout, worst.stderr,
                      flaky)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- programs from files, JSONL ----------------------------------------------------------

def program_from_file(path: str | Path, **overrides) -> Program:
    """A Program for a hand-written source (e.g. a control) or a saved
    generated program. Fields come from the offload.engine.gen header comment
    when present (id, primary atom, legal, observable, evidence, needs,
    std), else defaults: id = file stem, primary_atom = "control.<stem>",
    legal and observable True, no needs, evidence "construct". `atoms` is
    {primary_atom}. Keyword arguments override any field."""
    path = Path(path)
    source = path.read_text()
    head: dict[str, str] = {}
    c_source = path.suffix == ".c"
    lead = "//" if c_source else "!"
    for line in source.splitlines():
        if not line.startswith(lead):
            break
        m = re.match(rf"{lead}\s*([a-z_ ]+):\s*(.*)$", line)
        if m:
            head.setdefault(m.group(1).strip(), m.group(2).strip())
    pid = head.get("id", path.stem)
    primary = head.get("primary atom", f"control.{path.stem}")
    legal_text = head.get("legal", "yes")
    vm = re.search(r"violates (\S+?)\)?$", legal_text)
    needs_text = head.get("needs", "none")
    fields = dict(
        id=pid, lang="c" if c_source else "fortran", source=source,
        atoms=frozenset({primary}),
        primary_atom=primary, legal=legal_text.startswith("yes"),
        violates=vm.group(1) if vm else None,
        observable=not head.get("observable", "yes").startswith("no"),
        std=head.get("std", "c11" if c_source else "f2008"),
        needs=() if needs_text == "none" else tuple(
            n.strip() for n in needs_text.split(",")),
        evidence=head.get("evidence", "construct"),
        expect=head.get("expect", "result").split()[0],
        token=head.get("token", ""),
        model="acc" if re.match(r"acc\d\d-", pid) else "omp")
    fields.update(overrides)
    return Program(**fields)


def write_jsonl(results: Iterable[Result], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in results:
            f.write(json.dumps(dataclasses.asdict(r)) + "\n")


def read_jsonl(path: Path) -> list[Result]:
    out = []
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        d["outcome"] = Outcome(d["outcome"])
        d["atoms"] = tuple(d["atoms"])
        d["needs"] = tuple(d["needs"])
        out.append(Result(**d))
    return out
