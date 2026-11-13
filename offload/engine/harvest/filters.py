"""Which harvested tests become catalog programs, each drop with a
recorded reason (``classify``).

``TEST_REASONS`` apply to a whole test, in order; all that apply are
recorded and the first is primary. They cover language (C++, CUDA/HIP, fixed
form, mixed or multiple files), host-only tests, vendor and LLVM extensions,
runtime internals, and environment needs (MPI, input files, arguments, extra
tools, sanitizers, compile-only or no-run tests).

``VARIANT_REASONS`` apply to one RUN variant: a nonstandard flag or runtime
variable, host fallback, an expected failure, a target-specific triple, or
FileCheck lines the harness cannot use. Tests that the AOMP ``smoke-fails``
suite or an upstream XFAIL marks as failing are kept and flagged (``flags``).
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from offload.engine.harvest import checks as K

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SPEC_NAMES = ROOT / "catalog" / "harvest_spec_names.txt"

TEST_REASONS = ("cpp", "cuda_hip", "fixed_form", "mixed_language",
                "no_source", "multi_file", "mixed_models", "host_only",
                "llvm_extension", "arch_specific", "runtime_internals",
                "nonspec_routine", "ompt", "hip_cuda_interop", "mpi",
                "needs_files", "needs_args", "needs_other_tools",
                "llvm_libc", "llvm_debug", "llvm_pgo", "sanitizer",
                "llvm_machine", "compile_only", "no_run")
VARIANT_REASONS = ("llvm_flag", "llvm_env", "needs_omp_env",
                   "host_fallback_test", "expects_failure",
                   "target_specific", "filecheck_unsupported",
                   "checks_llvm_message", "no_check_lines")


@lru_cache(maxsize=1)
def spec_names() -> frozenset:
    return frozenset(ln.strip() for ln in SPEC_NAMES.read_text().splitlines()
                     if ln.strip() and not ln.startswith("#"))


# --- flags --------------------------------------------------------------------------

_ALLOWED = re.compile(r"^(-fopenmp-version=\d+|-O[0-3s]?|-g\S*|-D\S+|-U\S+|"
                      r"-I\S*|-lm|-std=\S+|-fopenmp|-fopenmp-targets=\S+|"
                      r"--offload-arch=\S+|-Xopenmp-target=\S+|-march=\S+|"
                      r"-w|-Wall|-Wextra|-cpp|-Mstandard|-ffree-form|"
                      r"-ffree-line-length-none|-fiopenmp|"
                      r"-fopenmp-targets)$")


def allowed_flag(f: str) -> bool:
    """A compile flag the conversion can keep (as #define, the version) or
    drop (optimisation, debug info, warnings, target selection, which the
    harness's toolchains set)."""
    return bool(_ALLOWED.match(f))


# --- environment --------------------------------------------------------------------

_LLVM_ENV = re.compile(r"^(LIBOMPTARGET_\w+|OFFLOAD_\w+|LLVM_\w+|OMPX_\w+|"
                       r"ROCR_VISIBLE_DEVICES|CUDA_VISIBLE_DEVICES|"
                       r"HIP_VISIBLE_DEVICES|GPU_\w+|AMD_\w+|KMP_\w+|"
                       r"LD_LIBRARY_PATH|PATH|LIBRARY_PATH|ATMI_\w+|"
                       r"HSA_(?!XNACK)\w+)$")


def env_reasons(env: dict) -> list[str]:
    out = []
    for k, v in env.items():
        if k == "HSA_XNACK":
            continue                # a memory mode (the program's modes)
        if k == "OMP_TARGET_OFFLOAD":
            if v.lower() == "disabled":
                out.append("host_fallback_test")
            continue                # mandatory: the harness runs with it
        if _LLVM_ENV.match(k):
            out.append("llvm_env")
        elif k.startswith("OMP_"):
            out.append("needs_omp_env")
        else:
            out.append("llvm_env")
    return sorted(set(out))


# --- the source -----------------------------------------------------------------------

_EXT = re.compile(r"\bompx_\w+|__builtin_amdgcn\w*|__builtin_nvvm\w*|"
                  r"\b__nvvm_\w+|__builtin_ptx\w*|\b__gpu_\w+|gpuintrin\.h|"
                  r"__attribute__\s*\(\(\s*(?:amdgpu_\w+|address_space|"
                  r"launch_bounds|nvptx\w*)|\[\[clang::|"
                  r"-fopenmp-extensions|\b__scoped_atomic\w*|"
                  r"\b__builtin_amdgpu\w*", re.I)
_ARCH = re.compile(r"__AMDGCN__|__NVPTX__|__AMDGPU__|__gfx\d+\w*__|"
                   r"__OFFLOAD_ARCH_\w+|__CUDA_ARCH__|__HIP_DEVICE_COMPILE__")
_INTERNAL = re.compile(r"\b__tgt_\w+|\b__kmpc_\w+|\b__llvm_omp\w*|"
                       r"omptarget\.h|\bTargetAsyncInfo\b")
_OMPT = re.compile(r"\bompt_\w+|omp-tools\.h|\bompTest\b", re.I)
_HIP = re.compile(r"hip/hip_runtime|cuda_runtime|<cuda\.h>|\bhipMalloc\w*|"
                  r"\bcudaMalloc\w*|hip_runtime_api", re.I)
_MPI = re.compile(r"<mpi\.h>|^\s*use\s+mpi\b|mpif\.h|\bMPI_Init\b", re.I | re.M)
_FOPEN_READ = re.compile(r"\bfopen\s*\([^;]*,\s*\"r", re.S)
_F_OPEN_OLD = re.compile(r"^\s*open\s*\(.*(status\s*=\s*['\"]old|action\s*="
                         r"\s*['\"]read)", re.I | re.M)
_OMP_NAME = re.compile(r"\b((?:llvm_)?omp_[a-z0-9_]+)\b", re.I)

# device routines that make a test offload without a target construct
_DEVICE_API = re.compile(r"\bomp_(?:target_\w+|get_num_devices|"
                         r"get_default_device|set_default_device|"
                         r"is_initial_device|get_device_num|"
                         r"get_initial_device|get_mapped_ptr|"
                         r"get_device_from_uid|get_uid_from_device|"
                         r"get_interop_\w+)\b", re.I)


def _strip_comments(text: str, lang: str) -> str:
    if lang == "c":
        text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
        return re.sub(r"//[^\n]*", "", text)
    out = []
    for ln in text.splitlines():
        s = ln.lstrip()
        if s.startswith("!") and not re.match(r"!\$(omp|acc)", s, re.I):
            continue
        out.append(ln)
    return "\n".join(out)


def _offload(code: str, lang: str, model: str) -> bool:
    if model == "acc":
        return bool(re.search(r"^\s*(#\s*pragma\s+acc|!\$acc)\s+"
                              r"(parallel|kernels|serial|data|enter|exit|"
                              r"update|host_data|declare|routine)", code,
                              re.I | re.M))
    if re.search(r"^\s*(?:#\s*pragma\s+omp|!\$omp)\b[^\n]*\btarget\b", code,
                 re.I | re.M):
        return True
    if re.search(r"^\s*(?:#\s*pragma\s+omp|!\$omp)\s+(?:begin\s+)?declare\s+"
                 r"(?:target|variant)", code, re.I | re.M):
        return True
    return bool(_DEVICE_API.search(code))


def source_reasons(text: str, lang: str, model: str) -> list[str]:
    code = _strip_comments(text, lang)
    out = []
    if not _offload(code, lang, model):
        out.append("host_only")
    if _EXT.search(code):
        out.append("llvm_extension")
    if _ARCH.search(code):
        out.append("arch_specific")
    if _INTERNAL.search(code):
        out.append("runtime_internals")
    names = spec_names()
    bad = {m.group(1).lower() for m in _OMP_NAME.finditer(code)
           if m.group(1).lower() not in names}
    if bad:
        out.append("nonspec_routine")
    if _OMPT.search(code):
        out.append("ompt")
    if _HIP.search(code):
        out.append("hip_cuda_interop")
    if _MPI.search(code):
        out.append("mpi")
    if (lang == "c" and _FOPEN_READ.search(code)) or \
            (lang != "c" and _F_OPEN_OLD.search(code)):
        out.append("needs_files")
    return out


def nonspec_names(text: str, lang: str) -> list[str]:
    code = _strip_comments(text, lang)
    names = spec_names()
    return sorted({m.group(1).lower() for m in _OMP_NAME.finditer(code)
                   if m.group(1).lower() not in names})


# --- checks -------------------------------------------------------------------------

_LLVM_MSG = re.compile(r"omptarget|libomptarget|PluginInterface|OFFLOAD "
                       r"ERROR|Launching kernel|__omp_offloading|"
                       r"\bAMDGPU\b|\bCUDA\b|nvptx|amdgcn|Libomptarget|"
                       r"\bPluginAdaptor\b|\bhsa_\w+|kernel trace|"
                       r"DEVID:|SGN:|ConstWGSize|\bkernel_launch\b|"
                       r"\b(?:SPMD|Generic)(?:-SPMD)? mode", re.I)


def check_reasons(text: str, prefixes: list[str], lang: str) -> list[str]:
    if not prefixes:
        return []
    cs = K.parse_checks(text, tuple(prefixes))
    if not cs:
        return ["no_check_lines"]
    out = []
    for c in cs:
        if c.kind == "EMPTY":
            continue
        try:
            K.compile_pattern(c.pattern, "c" if lang == "c" else "f90")
        except K.Unsupported:
            out.append("filecheck_unsupported")
        if _LLVM_MSG.search(c.pattern):
            out.append("checks_llvm_message")
    return sorted(set(out))


# --- a test ---------------------------------------------------------------------------

def _lang_reasons(r: dict) -> list[str]:
    lang = r["lang"]
    out = {"cpp": ["cpp"], "cuda": ["cuda_hip"], "hip": ["cuda_hip"],
           "fixed": ["fixed_form"], "mixed": ["mixed_language"],
           "none": ["no_source"], "other": ["no_source"],
           "header": ["no_source"]}.get(lang, [])
    srcs = [f for f in r["files"] if not re.search(r"\.(h|hpp|inc)$", f)]
    if len(srcs) > 1:
        out.append("multi_file")
    if r["model"] == "both":
        out.append("mixed_models")
    return out


_OK_TOOLS = {"echo", "true", ":", "cd"}


def bugfix(r: dict) -> dict | None:
    """Whether the test came with a bug fix, and its references: LLVM, the
    commit that added it (an issue it fixes, an issue it names, or a fix
    subject); AOMP, a ticket in its name, an AOMP issue that names it, or
    an adding commit that reads as a fix."""
    h = r.get("history") or {}
    add = h.get("added") or {}
    refs: list[str] = []
    kind = None
    if add.get("fixes"):
        kind, refs = "fixes_issue", list(add["fixes"])
    elif add.get("issues"):
        kind, refs = "names_issue", list(add["issues"])
    elif add.get("fix"):
        kind = "fix_commit"
    if r["source"] == "aomp":
        if r.get("tickets"):
            kind = kind or "ticket_in_name"
            refs += r["tickets"]
        iss = [f"aomp#{i['number']}" for i in r.get("aomp_issues") or []]
        if iss:
            kind = kind or "aomp_issue"
            refs += iss
    if kind is None:
        return None
    return {"kind": kind, "refs": sorted(set(refs)),
            "commit": add.get("commit"), "date": add.get("date"),
            "subject": add.get("subject"), "pr": add.get("pr", [])}


def classify(r: dict, texts: dict[str, str]) -> dict:
    """{keep, reasons, flags, variants: [{keep, reasons}], bugfix} of an
    inventory record; `texts`: its files' texts by the record's paths."""
    srcs = [texts.get(f, "") for f in r["files"]]
    text = "\n".join(srcs)
    lang = r["lang"]
    reasons = _lang_reasons(r)
    if not reasons:
        reasons += source_reasons(text, lang, r["model"])
        if lang == "f90" and any(v.get("args") for v in r["variants"]):
            reasons.append("needs_args")
        tools = [t for t in r.get("tools", []) if t not in _OK_TOOLS]
        if tools:
            reasons.append("needs_other_tools")
        req = {x.lower() for x in r.get("requires", [])}
        if "libc" in req:
            reasons.append("llvm_libc")
        if req & {"libomptarget-debug", "debug"}:
            reasons.append("llvm_debug")
        if "pgo" in req:
            reasons.append("llvm_pgo")
        if "ompt" in req:
            reasons.append("ompt")
        # a test of LLVM's GPU libc (offload/test/libc) or of its offload
        # sanitizer (deliberately erroneous programs: use after free, out of
        # bounds), and a test of an LLVM machine feature
        rel = r["path"].split("offload/test/", 1)[-1]
        if r["source"] == "llvm" and rel.startswith("libc/"):
            reasons.append("llvm_libc")
        if r["source"] == "llvm" and rel.startswith("sanitizer/"):
            reasons.append("sanitizer")
        if "large_allocation_memory_pool" in req:
            reasons.append("llvm_machine")
        if r.get("compile_only"):
            reasons.append("compile_only")
        elif not r["variants"]:
            reasons.append("no_run")
    reasons = [x for x in TEST_REASONS if x in reasons]
    variants = []
    for v in r["variants"]:
        vr = []
        if any(not allowed_flag(f) for f in v.get("flags", [])):
            vr.append("llvm_flag")
        vr += env_reasons(v.get("env", {}))
        if v.get("fail"):
            vr.append("expects_failure")
        if v.get("triple", "generic") != "generic" or \
                v.get("run_triple", "generic") != "generic":
            vr.append("target_specific")
        if lang in ("c", "f90"):
            vr += check_reasons(text, v.get("prefixes", []), lang)
        vr = [x for x in VARIANT_REASONS if x in vr]
        variants.append({"keep": not vr, "reasons": vr})
    keep = not reasons and any(v["keep"] for v in variants)
    flags = []
    for x in r.get("xfail", []):
        if re.search(r"amdgcn|amdgpu", x):
            flags.append("upstream_xfail_amd")
        if re.search(r"nvptx|nvidia", x):
            flags.append("upstream_xfail_nvidia")
        if x.strip() == "*":
            flags.append("upstream_xfail_all")
    for x in r.get("unsupported", []):
        if re.fullmatch(r"(amdgcn|amdgpu)[\w-]*", x) and "LTO" not in x:
            flags.append("upstream_unsupported_amd")
        if re.fullmatch(r"(nvptx|nvidia)[\w-]*", x) and "LTO" not in x:
            flags.append("upstream_unsupported_nvidia")
    if r.get("suite") == "smoke-fails":
        flags.append("aomp_smoke_fails")
    if "unified_shared_memory" in [x.lower() for x in r.get("requires", [])]:
        flags.append("requires_usm")
    if not keep and not reasons:
        reasons = sorted({x for v in variants for x in v["reasons"]},
                         key=VARIANT_REASONS.index)
    return {"id": r["id"], "keep": keep, "reasons": reasons,
            "flags": sorted(set(flags)), "variants": variants,
            "bugfix": bugfix(r),
            "nonspec": nonspec_names(text, lang) if lang in ("c", "f90")
            else []}
