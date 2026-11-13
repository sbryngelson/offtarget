"""GCC's libgomp testsuite (libgomp.c, libgomp.fortran, libgomp.oacc-*) as
harvest programs.

A libgomp test checks itself: it aborts (or ``stop N``) on a wrong result and
exits 0 otherwise, so DejaGnu requires exit status 0. That is the oracle here
(``exit_status``); a test whose ``dg-output`` is plain text also gets CHECK
lines (``filecheck``, offload.engine.harvest.checks). ``record`` reads the
DejaGnu directives (``parse_dg``). ``classify`` records every reason a test
is dropped (``reasons``: language, scope, DejaGnu usage, source content) and
what a kept one needs (``modes``, ``defines``, ``checks``, ``flags``).
``convert`` writes the program: local includes inlined, GNU builtins
rewritten to ISO C names, the -D options of the test and its suite as
#define lines, then the self-check of offload.engine.harvest.convert. OpenACC
programs get an OpenACC host probe instead of the OpenMP one.
"""
from __future__ import annotations

import re
from pathlib import Path

from offload.engine.harvest import convert as HC
from offload.engine.harvest import filters as HF

LICENSE = ("GPL-3.0-or-later (the GCC testsuite; "
           "https://gcc.gnu.org/onlinedocs/libstdc++/manual/license.html); "
           "kept in its own directory with COPYING3")
URL = "https://github.com/gcc-mirror/gcc/blob/{commit}/libgomp/testsuite/{path}"

SUITES = {
    "libgomp.c": "c",
    "libgomp.c-c++-common": "ccc",
    "libgomp.fortran": "f",
    "libgomp.oacc-c": "acc-c",
    "libgomp.oacc-c-c++-common": "acc-ccc",
    "libgomp.oacc-fortran": "acc-f",
}

# --- DejaGnu directives -------------------------------------------------------------------

_DG = re.compile(r"\{\s*(dg-[\w-]+)\b(.*)")


def _braced(s: str, i: int) -> tuple[str, int]:
    """The text of the brace group or quoted string at s[i] (after
    blanks), and the offset after it; ('', i) when there is none."""
    while i < len(s) and s[i] in " \t":
        i += 1
    if i >= len(s):
        return "", i
    if s[i] == '"':
        j = i + 1
        while j < len(s) and s[j] != '"':
            j += 2 if s[j] == "\\" else 1
        return s[i + 1:j], j + 1
    if s[i] == "{":
        depth, j = 0, i
        while j < len(s):
            if s[j] == "{":
                depth += 1
            elif s[j] == "}":
                depth -= 1
                if depth == 0:
                    return s[i + 1:j], j + 1
            j += 1
        return s[i + 1:], len(s)
    m = re.match(r"[^\s{}]+", s[i:])
    if m:
        return m.group(0), i + m.end()
    return "", i


def _args(rest: str) -> list[str]:
    out, i = [], 0
    while True:
        a, j = _braced(rest, i)
        if j == i or (not a and j >= len(rest)):
            break
        if rest[i:j].strip() in ("}", "*/", ""):
            break
        out.append(a.strip())
        i = j
        if len(out) > 6:
            break
    return out


def _selector(args: list[str]) -> str:
    """The target selector of a directive's trailing ``{ target X }``."""
    for a in args:
        m = re.match(r"(target|xfail)\s+(.*)$", a, re.S)
        if m and m.group(1) == "target":
            return " ".join(m.group(2).split()).strip("{} ").strip()
    return ""


def parse_dg(text: str) -> dict:
    d = {"do": ("run", ""), "options": [], "target_options": [], "env": {},
         "effective": [], "output": [], "shouldfail": False, "sources": [],
         "skip": [], "xfail": [], "outputs_selected": []}
    for line in text.splitlines():
        for m in re.finditer(r"\{\s*(dg-[\w-]+)", line):
            name = m.group(1)
            rest = line[m.end():]
            args = _args(rest)
            if name == "dg-do":
                kind = args[0] if args else "run"
                d["do"] = (kind, _selector(args[1:]))
            elif name in ("dg-options", "dg-additional-options"):
                opts = (args[0] if args else "").split()
                sel = _selector(args[1:])
                if sel:
                    d["target_options"] += [(o, sel) for o in opts]
                else:
                    d["options"] += opts
            elif name == "dg-set-target-env-var":
                if len(args) >= 2:
                    d["env"][args[0].strip('"')] = args[1]
            elif name == "dg-require-effective-target":
                if args:
                    d["effective"].append(args[0])
            elif name == "dg-output":
                sel = _selector(args[1:])
                if sel:
                    d["outputs_selected"].append((args[0] if args else "", sel))
                else:
                    d["output"].append(args[0] if args else "")
            elif name == "dg-shouldfail":
                d["shouldfail"] = True
            elif name == "dg-additional-sources":
                d["sources"] += (args[0] if args else "").split()
            elif name == "dg-skip-if":
                d["skip"].append(args[1:])
            elif name in ("dg-xfail-run-if", "dg-xfail-if"):
                d["xfail"].append(args)
    return d


# --- the record ------------------------------------------------------------------------

def lang_of(path: str) -> str:
    p = path.lower()
    if path.endswith((".C", ".cc", ".cpp", ".cxx")):
        return "cpp"
    if p.endswith(".c"):
        return "c"
    if p.endswith((".f90", ".f95", ".f03", ".f08")):
        return "f90"
    if p.endswith((".f", ".for", ".f77")):
        return "fixed"
    if p.endswith((".h", ".inc", ".fh")):
        return "header"
    return "other"


def model_of(text: str) -> str:
    omp = re.search(r"^\s*(?:#\s*pragma\s+omp|!\$omp)\b", text, re.M | re.I)
    acc = re.search(r"^\s*(?:#\s*pragma\s+acc|!\$acc)\b", text, re.M | re.I)
    if omp and acc:
        return "mixed"
    return "acc" if acc else ("omp" if omp else "none")


def record(path: str, text: str, commit: str, root: str = "") -> dict:
    """``path`` relative to libgomp/testsuite (``suite/name``)."""
    suite = path.split("/")[0]
    return {"id": f"gomp/{path}", "source": "gomp", "suite": suite,
            "path": f"libgomp/testsuite/{path}", "rel": path,
            "commit": commit, "license": LICENSE,
            "url": URL.format(commit=commit[:12], path=path),
            "project": "gcc-mirror/gcc (libgomp testsuite)",
            "lang": lang_of(path), "model": model_of(text),
            "dg": parse_dg(text), "prs": prs(path, text)}


def prs(path: str, text: str) -> list[str]:
    """The GCC bugzilla PRs a test names (its file name, its PR lines)."""
    out = []
    m = re.search(r"\bpr(\d{5,6})", Path(path).name)
    if m:
        out.append(m.group(1))
    for m in re.finditer(r"\bPR\s+(?:[\w+-]+/)?(\d{5,6})\b", text):
        out.append(m.group(1))
    return sorted(set(out), key=out.index)


# --- includes and rewrites ---------------------------------------------------------------

_C_INC = re.compile(r'^[ \t]*#[ \t]*include[ \t]*"([^"]+)"[^\n]*$', re.M)
_F_INC = re.compile(r"^[ \t]*include[ \t]*['\"]([^'\"]+)['\"][^\n]*$",
                    re.M | re.I)


def _rel(p: Path) -> str:
    parts = p.resolve().parts
    for k in range(len(parts) - 1, -1, -1):
        if parts[k].startswith("libgomp.") or parts[k] == "gcc":
            return "/".join(parts[k:])
    return p.name


def inline_includes(text: str, path: Path, depth: int = 0,
                    skip: tuple = ()) -> tuple[str, list]:
    """(text with each local include replaced by the file's text, the
    included files relative to the testsuite, None for a missing one);
    an include named in ``skip`` (one under an #ifdef that is not taken,
    such as an optional profiling header) is left as it is."""
    incs: list = []
    rx = _F_INC if lang_of(str(path)) in ("f90", "fixed") else _C_INC

    def sub(m):
        if m.group(1) in skip:
            return m.group(0)
        f = (path.parent / m.group(1))
        if depth > 6 or not f.is_file():
            incs.append(None)
            return m.group(0)
        incs.append(_rel(f))
        body, more = inline_includes(f.read_text(errors="replace"), f,
                                     depth + 1, skip)
        incs.extend(more)
        return f"/* inlined {m.group(1)} */\n{body}" if rx is _C_INC else \
            f"! inlined {m.group(1)}\n{body}"
    out = rx.sub(sub, text)
    return out, incs


_BUILTIN_C = {
    "abort": "stdlib.h", "exit": "stdlib.h", "malloc": "stdlib.h",
    "calloc": "stdlib.h", "free": "stdlib.h", "abs": "stdlib.h",
    "printf": "stdio.h", "memcmp": "string.h", "memset": "string.h",
    "memcpy": "string.h", "strcmp": "string.h", "strlen": "string.h",
    "fabs": "math.h", "sin": "math.h", "cos": "math.h", "acos": "math.h",
    "sqrt": "math.h", "copysign": "math.h", "fabsf": "math.h",
}


_ATTR_WORD = r"(?:noinline|__noinline__|noipa|noclone|always_inline|used|unused)"
_ATTR = re.compile(r"__attribute__\s*\(\(\s*" + _ATTR_WORD +
                   r"(?:\s*,\s*" + _ATTR_WORD + r")*\s*\)\)[ \t]*")


def rewrite_builtins(text: str, lang: str) -> tuple[str, list[str]]:
    """GNU builtins with an ISO C name as that name (its header included),
    GNU attributes that only steer optimisation removed; Fortran: the GNU
    ABORT subroutine as ERROR STOP."""
    edits = []
    if lang != "c":
        out, n = re.subn(r"(?im)^([ \t]*(?:\d+[ \t]+)?(?:if[ \t]*\(.*\)[ \t]*)?)"
                         r"call[ \t]+abort\b[ \t]*(\([ \t]*\))?",
                         r"\1error stop", text)
        if n:
            edits.append(f"the GNU ABORT subroutine as ERROR STOP ({n})")
        return out, edits
    heads = []
    text, n = _ATTR.subn("", text)
    if n:
        edits.append(f"GNU optimisation attributes removed ({n}: noinline, "
                     "noipa, noclone, always_inline, used, unused)")

    def sub(m):
        name = m.group(1)
        if name in _BUILTIN_C:
            heads.append(_BUILTIN_C[name])
            return name
        if name == "inff":
            heads.append("math.h")
            return "INFINITY"
        return m.group(0)
    out = re.sub(r"\b__builtin_(\w+)\b", sub, text)
    if heads:
        names = sorted(set(re.findall(r"\b__builtin_(\w+)\b", text)) &
                       (set(_BUILTIN_C) | {"inff"}))
        edits.append("GNU builtins as their ISO C names: " +
                     ", ".join(f"__builtin_{n}" for n in names))
        add = [h for h in sorted(set(heads))
               if not re.search(rf"#\s*include\s*<{re.escape(h)}>", out)]
        if add:
            out = "".join(f"#include <{h}>\n" for h in add) + out
            edits.append("#include " + ", ".join(f"<{h}>" for h in add))
    return out, edits


# --- classification ---------------------------------------------------------------------

_DROP_FLAG = re.compile(
    r"^(-O\w*|-W\S*|-w|-g\S*|-std=\S+|-fopenmp|-fopenacc|-cpp|"
    r"-foffload=\S*|-foffload-options=\S*|--param\S*|-fopt-info\S*|"
    r"-fdump-\S+|-fno-inline\S*|-finline\S*|-f(?:no-)?ipa\S*|"
    r"-f(?:no-)?tree-\S+|-ffast-math|-fno-math-errno|-fno-trapping-math|"
    r"-m(?:sse|avx|no-|arch|tune|cx16)\S*|-march=\S+|-fvect-cost-model\S*|"
    r"-flto\S*|-fno-builtin\S*|-ffree-line-length-\S+|-frecursive|"
    r"-fno-stack-protector|-fPIC|-pthread|-l(?:m|dl|pthread)|"
    r"-fexceptions|-fno-exceptions|-fdiagnostics\S*|-fno-diagnostics\S*|"
    r"-fstack-arrays|-fno-unroll\S*|-funroll\S*|-fno-strict\S*|"
    r"-fwrapv|-fsanitize=\S*|-fcheck=\S*|-fno-openacc-kernels-annotate-loops|"
    r"-fopenacc-kernels=\S+|-fno-schedule-insns\S*|-fbounds-check|"
    r"parloops\S*|-ftree-parallelize-loops=\S+|-ffree-form|-fno-ipa-sra)$")
_DEFINE = re.compile(r"^-[DU]\S+$")
_INTEROP_LIB = re.compile(r"^-l(?:cuda|cudart|cublas|amdhip64|hipblas)\S*$")
_FIXED_FLAG = re.compile(r"^-ffixed-form$")

_OK_TARGET = {"offload_device", "offload_device_nonshared_as",
              "! openacc_host_selected", "lto", "tls_runtime",
              "vect_simd_clones", "*-*-linux* *-*-gnu* *-*-freebsd*",
              "c99_runtime", "fopenmp", "size32plus", "sync_int_long",
              "{ ! offload_device_nvptx }", "! offload_device_nvptx",
              "! offload_target_nvptx", "! offload_device_gcn"}
_INTEROP_EFF = re.compile(r"cuda|cublas|cudart|amdhip|hipblas|gomp_lib")
_SPECIFIC_EFF = re.compile(r"nvptx|gcn|amdgcn|nvidia|radeon|aarch64|avx|"
                           r"x86|i\?86|float16|lp64|skip-all")
_COPY_EFF = {"offload_device_nonshared_as"}
_USM_EFF = {"omp_usm", "omp_managedmem"}
_STD_ENV = re.compile(r"^OMP_\w+$")


def _code(text: str, lang: str) -> str:
    return HF._strip_comments(text, "c" if lang == "c" else "f90")


_GNU_C = re.compile(r"\basm\b|\b__asm__\b|__attribute__|\btypeof\b|"
                    r"\b__typeof__\b|\(\{|\b__int128\b|#\s*pragma\s+GCC\b|"
                    r"\b__builtin_\w+|\b_Pragma\s*\(\s*\"GCC|__extension__|"
                    r"\b__label__\b|\b__auto_type\b|\b__seg_\w+|"
                    r"\b__restrict__\b|\b__inline__\b|\b__alignof__\b|"
                    r"\b__real__\b|\b__imag__\b|\b__complex__\b|"
                    r"\bcase\s+[^:;]+\.\.\.")
_GNU_F = re.compile(r"\bcall\s+(?:sleep|flush|exit|system|getenv|"
                    r"getarg|srand|fdate|ctime|chdir|perror|signal)\b|"
                    r"\b(?:loc|malloc|lshift|rshift|etime|dtime|secnds|"
                    r"time8|irand|rand|ran|getpid|hostnm|lnblnk|isnan|"
                    r"dfloat|dreal|dcmplx|zabs|cdabs)\s*\(|"
                    r"%val\s*\(|%ref\s*\(|\bstructure\s*/|\bunion\b|"
                    r"\bpointer\s*\(\s*\w+\s*,|"
                    r"!GCC\$|\bdouble\s+complex\b|\breal\s*\*\s*16\b",
                    re.I)
_INTERNAL = re.compile(r"\bGOMP_\w+|\bGOACC_\w+|\b__builtin_goacc_\w+|"
                       r"\b__builtin_omp_\w+|gomp-constants\.h|"
                       r"libgomp_g\.h|\bgomp_\w+|\bgoacc_\w+|"
                       r"\b__gomp_\w+|\bacc_prof_\w+|\bacc_register_library\b|"
                       r"\bacc_prof\b|\bacc_event_info\b|\bacc_api_info\b|"
                       r"\bacc_callback\w*\b|\bacc_ev_\w+")
_ARCH = re.compile(r"\bACC_DEVICE_TYPE_(?!host\b)\w+|__nvptx__|__NVPTX__|"
                   r"__AMDGCN__|__amdgcn__|__gcn__|__GCN__|"
                   r"\bacc_device_(?:nvidia|radeon|gcn|nvptx)\b|"
                   r"arch\s*\(\s*(?:nvptx|gcn|amdgcn|x86_64)|"
                   r"isa\s*\(\s*(?:sm_|gfx)")
_INTEROP_SRC = re.compile(r"\bcu[A-Z]\w+\s*\(|\bcublas\w*|\bhip[A-Z]\w*|"
                          r"<cuda[\w.]*\.h>|<hip/|\bacc_get_cuda_stream\b|"
                          r"\bacc_set_cuda_stream\b|\bacc_get_current_cuda_\w+|"
                          r"\bomp_interop_\w+|\bomp_get_interop_\w+|"
                          r"\binterop\b|\bCUDA\b|\bHIP\b")
_ACC_SPEC = None


def acc_spec_names() -> frozenset:
    """The OpenACC 3.4 runtime routine and type names (§3.2, §3.1)."""
    return frozenset("""
acc_get_num_devices acc_set_device_type acc_get_device_type
acc_set_device_num acc_get_device_num acc_get_property
acc_get_property_string acc_init acc_init_device acc_shutdown
acc_shutdown_device acc_async_test acc_async_test_device
acc_async_test_all acc_async_test_all_device acc_wait acc_wait_device
acc_wait_async acc_wait_device_async acc_wait_all acc_wait_all_device
acc_wait_all_async acc_wait_all_device_async acc_get_default_async
acc_set_default_async acc_on_device acc_malloc acc_free acc_copyin
acc_copyin_async acc_create acc_create_async acc_copyout acc_copyout_async
acc_copyout_finalize acc_copyout_finalize_async acc_delete
acc_delete_async acc_delete_finalize acc_delete_finalize_async
acc_update_device acc_update_device_async acc_update_self
acc_update_self_async acc_map_data acc_unmap_data acc_deviceptr
acc_hostptr acc_is_present acc_memcpy_to_device
acc_memcpy_to_device_async acc_memcpy_from_device
acc_memcpy_from_device_async acc_memcpy_device acc_memcpy_device_async
acc_attach acc_attach_async acc_detach acc_detach_async
acc_detach_finalize acc_detach_finalize_async acc_memcpy_d2d
acc_memcpy_d2d_async acc_present_or_copyin acc_pcopyin
acc_present_or_create acc_pcreate acc_async_wait acc_async_wait_all
acc_device_t acc_device_none acc_device_default acc_device_host
acc_device_not_host acc_device_property_t acc_property_memory
acc_property_free_memory acc_property_shared_memory_support
acc_property_name acc_property_vendor acc_property_driver
acc_async_noval acc_async_sync acc_async_default acc_handle_kind
acc_device_kind acc_device_property openacc_version
acc_get_num_devices_f acc_set_device_num_f acc_copyin_async_f
acc_is_present_f acc_device_property_kind
""".split())


_ACC_NAME = re.compile(r"\b(acc_[a-z0-9_]+)\b", re.I)
_OMP_NAME = re.compile(r"\b(omp_[a-z0-9_]+)\b", re.I)


def nonspec_names(code: str) -> list[str]:
    spec = HF.spec_names()
    acc = acc_spec_names()
    bad = {m.group(1).lower() for m in _OMP_NAME.finditer(code)
           if m.group(1).lower() not in spec}
    bad |= {m.group(1).lower() for m in _ACC_NAME.finditer(code)
            if m.group(1).lower() not in acc and
            not m.group(1).isupper() and
            not re.match(r"acc_(?:device|prof|ev|api|event|register|"
                         r"get_cuda|set_cuda|get_current_cuda)", m.group(1),
                         re.I)}
    return sorted(bad)


_LITERAL_OUT = re.compile(r"^(?:[^\\\[\](){}.*+?^$|]|\\[\\\"\[\]$.])*$")
_NEWLINE_RX = re.compile(r"\((?:\\n\|\\r\\n\|\\r|\\r\\n\|\\n\|\\r)\)\+?|"
                         r"\[\\r\\n\]\+?|\\r\\n|\\n")


def output_checks(outputs: list[str]) -> list[str] | None:
    """CHECK lines of plain-text dg-output patterns (one per line of
    expected output); None when one is a regular expression."""
    out = []
    for o in outputs:
        parts = _NEWLINE_RX.split(o)
        for p in parts:
            if not p:
                continue
            if not _LITERAL_OUT.match(p):
                return None
            lit = re.sub(r"\\(.)", r"\1", p).strip()
            if lit:
                out.append(f"CHECK: {lit}")
    return out


_RUNTIME_MSG = re.compile(r"libgomp|GOMP_|GOACC|nvptx|gcn|cuda|plugin|"
                          r"OMP_DISPLAY_ENV|OPENMP DISPLAY|_omp_fn|"
                          r"Refusing|kernel ", re.I)


def classify(r: dict, text: str) -> dict:
    """{reasons, modes, defines, checks, flags} of a test (its text with
    the includes inlined)."""
    lang, d = r["lang"], r["dg"]
    reasons: list[str] = []
    flags: list[str] = []
    defines: list[str] = []
    modes = ["copy", "unified"]
    if lang == "cpp":
        reasons.append("cpp")
    elif lang == "fixed":
        reasons.append("fixed_form")
    elif lang not in ("c", "f90"):
        reasons.append("no_source")
    model = model_of(text) if lang in ("c", "f90") else r["model"]
    if model == "mixed":
        reasons.append("mixed_models")
    code = _code(text, lang) if lang in ("c", "f90") else text
    m = "acc" if model == "acc" else "omp"
    if lang in ("c", "f90") and not HF._offload(code, lang, m):
        reasons.append("host_only")
    kind, sel = d["do"]
    if kind != "run":
        reasons.append("compile_only")
    elif sel:
        if sel in _COPY_EFF:
            modes = ["copy"]
        elif sel not in _OK_TARGET:
            reasons.append("target_specific")
    if d["shouldfail"]:
        reasons.append("expects_failure")
    if d["sources"]:
        reasons.append("multi_file")
    for args in d["skip"]:
        sel = " ".join(args[0].split()) if args else ""
        incl = args[1] if len(args) > 1 else ""
        excl = args[2] if len(args) > 2 else ""
        if sel == "*-*-*" and "ACC_MEM_SHARED=0" in excl:
            modes = ["copy"]
        elif sel == "*-*-*" and "ACC_MEM_SHARED=1" in incl:
            modes = ["copy"]
        elif sel == "*-*-*" and not incl and not excl:
            reasons.append("skipped_upstream")
        elif sel == "*-*-*" and re.fullmatch(r'"?-O\d"?', incl.strip()):
            flags.append(f"upstream skips it at {incl.strip()}")
        elif _SPECIFIC_EFF.search(sel) or "selected" in sel:
            reasons.append("target_specific")
        elif sel:
            flags.append(f"skip-if {sel}")
    if d["xfail"]:
        flags.append("upstream xfail: " + "; ".join(
            " ".join(a) for a in d["xfail"])[:160])
    for o in d["options"]:
        if _DEFINE.match(o):
            defines.append(o)
        elif _INTEROP_LIB.match(o):
            reasons.append("interop")
        elif _FIXED_FLAG.match(o):
            reasons.append("fixed_form")
        elif o == "-fno-openmp" or o == "-fno-openacc":
            reasons.append("gcc_flag")
        elif not _DROP_FLAG.match(o):
            reasons.append("gcc_flag")
    for eff in d["effective"]:
        if eff in _USM_EFF:
            modes = ["unified"]
        elif eff in _COPY_EFF:
            modes = ["copy"]
        elif _INTEROP_EFF.search(eff):
            reasons.append("interop")
        elif _SPECIFIC_EFF.search(eff) or eff == "exceptions":
            reasons.append("target_specific")
    for k, v in d["env"].items():
        if k == "OMP_TARGET_OFFLOAD":
            if v.strip('"').lower() == "disabled":
                reasons.append("host_fallback_test")
        elif _STD_ENV.match(k):
            reasons.append("needs_omp_env")
        else:
            reasons.append("vendor_env")
    checks: list[str] = []
    if d["output"]:
        if any(_RUNTIME_MSG.search(o) for o in d["output"]):
            reasons.append("checks_runtime_message")
        else:
            cs = output_checks(d["output"])
            if cs is None:
                reasons.append("dg_output_regex")
            else:
                checks = cs
    if d["outputs_selected"]:
        flags.append("dg-output for some targets only (not checked)")
    if model == "acc":
        defines.append("-DACC_MEM_SHARED=0")
        if re.search(r"\bACC_MEM_SHARED\b", code):
            modes = ["copy"] if modes != ["unified"] else modes
    if lang == "c":
        rw, _ = rewrite_builtins(code, "c")
        if _GNU_C.search(rw):
            reasons.append("gnu_extension")
        if re.search(r"#\s*include\s*<(?!stdio|stdlib|string|math|omp|openacc|"
                     r"assert|stdint|stdbool|stddef|limits|float|complex|"
                     r"unistd|time|errno|inttypes|stdarg|signal|setjmp|"
                     r"ctype|wchar|uchar|stdalign|stdatomic|tgmath|iso646|"
                     r"fenv|locale|sys/time|pthread)[\w/.]+>", code):
            reasons.append("gnu_extension")
    elif lang == "f90":
        rw, _ = rewrite_builtins(code, "f90")
        if _GNU_F.search(rw):
            reasons.append("gnu_extension")
    if lang in ("c", "f90"):
        if _INTERNAL.search(code):
            reasons.append("runtime_internals")
        if _ARCH.search(code) or any(re.search(r"ACC_DEVICE_TYPE_(?!host)",
                                               o) for o in d["options"]):
            reasons.append("arch_specific")
        if _INTEROP_SRC.search(code):
            reasons.append("interop")
        if nonspec_names(code):
            reasons.append("nonspec_routine")
        if (lang == "c" and HF._FOPEN_READ.search(code)) or \
                (lang == "f90" and HF._F_OPEN_OLD.search(code)):
            reasons.append("needs_files")
        if lang == "c" and not re.search(r"\bmain\s*\(", code):
            reasons.append("no_main")
        if lang == "f90" and not re.search(r"^\s*program\s+\w+", code,
                                           re.I | re.M):
            reasons.append("no_main")
    seen = []
    for x in reasons:
        if x not in seen:
            seen.append(x)
    return {"reasons": seen, "modes": modes, "defines": defines,
            "checks": checks, "flags": flags, "model": model}


# --- conversion -------------------------------------------------------------------------

def program_id(r: dict) -> str:
    rel = r["rel"]
    suite, name = rel.split("/", 1)
    slug = re.sub(r"\.(c|f90|F90|f95|f03|f08)$", "", name)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", slug).strip("-").lower()
    return f"h2-gomp-{SUITES.get(suite, 'x')}-{slug}"


_C_PROBE_OMP = ("#pragma omp target map(from: h)\n"
                "  h = omp_is_initial_device();")
_C_PROBE_ACC = ("#pragma acc serial copyout(h)\n"
                "  h = acc_on_device(acc_device_host);")
_F_PROBE_OMP = ("!$omp target\n    if (omp_is_initial_device()) then\n"
                "      h(1) = 1\n    else\n      h(1) = 0\n    end if\n"
                "!$omp end target")
_F_PROBE_ACC = ("!$acc serial copyout(h)\n"
                "    if (acc_on_device(acc_device_host)) then\n"
                "      h(1) = 1\n    else\n      h(1) = 0\n    end if\n"
                "!$acc end serial")


def acc_runtime(src: str, lang: str) -> str:
    """The 49a self-check with an OpenACC host probe: no OpenMP left."""
    if lang == "c":
        assert _C_PROBE_OMP in src and "#include <omp.h>\n" in src
        src = src.replace(_C_PROBE_OMP, _C_PROBE_ACC)
        k = src.rfind("#include <omp.h>\n")
        return src[:k] + "#include <openacc.h>\n" + \
            src[k + len("#include <omp.h>\n"):]
    assert _F_PROBE_OMP in src
    src = src.replace(_F_PROBE_OMP, _F_PROBE_ACC)
    k = src.rfind("  use omp_lib\n")
    return src[:k] + "  use openacc\n" + src[k + len("  use omp_lib\n"):]


def header(r: dict, c: dict, version: int, oracle: str, edits: list,
           incs: list, lang: str, original_sha: str) -> list[str]:
    lines = [
        "Harvested test (tools/campaigns/harvest2.py convert; do not edit)",
        f"source: {r['url']}",
        f"license: {r['license']}",
        f"original sha256: {original_sha}",
    ]
    if incs:
        lines.append("inlined: " + ", ".join(i for i in incs if i))
    if r.get("prs"):
        lines.append("GCC PRs named: " + ", ".join(f"PR{p}" for p in r["prs"]))
    if c["flags"]:
        lines.append("upstream: " + "; ".join(c["flags"])[:200])
    ver = (f"OpenACC 3.4" if c["model"] == "acc" else
           f"OpenMP {version // 10}.{version % 10}")
    lines += [
        f"modes: {', '.join(c['modes'])}; defines: "
        f"{' '.join(c['defines']) or '(none)'}",
        f"spec version: {ver} (the grammar reads every directive at it)",
        "expected: exit status 0 (the test's own checks: abort or STOP on a "
        "wrong result)" + (f"; the output matches {len(c['checks'])} CHECK "
                           "lines from its dg-output" if oracle == "filecheck"
                           else ""),
        "self-check: RESULT ran_on_host=<0|1> check=<pass|fail>",
        "edits: " + "; ".join(edits + ["self-check appended"]),
    ]
    if lang == "c":
        return ["/*"] + [" * " + ln.replace("*/", "* /") for ln in lines] + \
            [" */"]
    return ["! " + ln for ln in lines]


def convert(r: dict, text: str, incs: list | None = None) -> dict:
    """The harvest program of a kept test (its text with includes
    inlined); HC.ConvertError when it cannot be converted."""
    import hashlib
    from offload.engine.harvest import checks as K
    c = classify(r, text)
    lang, model = r["lang"], c["model"]
    if model not in ("omp", "acc"):
        raise HC.ConvertError(f"model {model}")
    orig_sha = hashlib.sha256(text.encode()).hexdigest()
    body, edits = rewrite_builtins(text, lang)
    cs = K.parse_checks("\n".join("// " + x for x in c["checks"]),
                        ("CHECK",)) if c["checks"] else []
    v = {"flags": c["defines"], "prefixes": ["CHECK"] if cs else []}
    if lang == "c":
        src, e2 = HC.convert_c(body, cs, v)
    else:
        src, e2 = HC.convert_f(body, cs, v)
    edits += e2
    if model == "acc":
        src = acc_runtime(src, lang)
        edits.append("the self-check's host probe is OpenACC (acc serial, "
                     "acc_on_device)")
    version, gerr = HC.spec_version(body, lang, [], model)
    oracle = "filecheck" if cs else "exit_status"
    head = header(r, c, version, oracle, edits, incs or [], lang, orig_sha)
    if lang == "c":
        pre = HC.CR.PRELUDE
        src = pre + "\n".join(head) + "\n" + src[len(pre):]
    else:
        src = "\n".join(head) + "\n" + src
    return {"id": program_id(r), "record": r["id"], "lang": lang,
            "model": model, "version": version, "source": src,
            "oracle": oracle, "checks": len(cs),
            "prefixes": ["CHECK"] if cs else [], "modes": c["modes"],
            "edits": edits, "grammar_errors": gerr, "url": r["url"],
            "license": r["license"], "project": r["project"],
            "suite": r["suite"], "commit": r["commit"], "prs": r["prs"],
            "flags": c["flags"], "gpl": True, "copyleft": True,
            "original_sha256": orig_sha}
