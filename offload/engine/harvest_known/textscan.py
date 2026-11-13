"""Text scanning shared by the known-issues sources.

Pure functions over text (forum posts, centre pages, commit messages and
diffs): which offload model a piece of code uses, its language, the
NVIDIA problem-report numbers (TPRs) and "fixed in X.Y" versions a text
names, and the compilers it mentions. Nothing here reads files or runs
anything; the callers hand it text from the untrusted download area."""
from __future__ import annotations

import re

_F_DIR = re.compile(r"^\s*!\$(omp|acc)\b(.*)$", re.I | re.M)
_C_DIR = re.compile(r"^\s*#\s*pragma\s+(omp|acc)\b(.*)$", re.M)
# the OpenMP directives that put code on a device (or describe device code)
_DEVICE = re.compile(r"\b(target|declare\s+target|begin\s+declare\s+target|"
                     r"declare\s+variant|requires|declare\s+mapper|"
                     r"end\s+declare\s+target)\b", re.I)


def models(code: str) -> set[str]:
    """{'omp-target', 'omp-host', 'acc'}: the models the directives of
    ``code`` use. 'omp-host' only when no OpenMP directive is a device one."""
    out: set[str] = set()
    omp_dev = omp_host = False
    for m in (*_F_DIR.finditer(code), *_C_DIR.finditer(code)):
        kind, rest = m.group(1).lower(), m.group(2)
        if kind == "acc":
            out.add("acc")
        elif _DEVICE.search(rest):
            omp_dev = True
        else:
            omp_host = True
    if omp_dev:
        out.add("omp-target")
    elif omp_host:
        out.add("omp-host")
    return out


_CXX = re.compile(r"#include\s*<(iostream|vector|string|cstdio|cstdlib|cmath|"
                  r"array|memory|algorithm|complex|chrono|map|thread|numeric|"
                  r"cassert|iomanip|sstream|fstream|functional)>|\bstd::|"
                  r"\btemplate\s*<|\bclass\s+\w+\s*[{:]|\bnamespace\b|"
                  r"\bnew\s+\w+\s*\[|\bdelete\s*\[\]|\bcout\b|\bnullptr\b|"
                  r"\bauto\s+\w+\s*=|::\w+\(")
_C = re.compile(r"#include\s*[<\"]|\bint\s+main\s*\(|\bvoid\s+\w+\s*\(|"
                r"\b(double|float|int)\s*\*\s*\w+|\bprintf\s*\(|;\s*$", re.M)
_F = re.compile(r"^\s*(program|subroutine|module|function|end\s+(program|"
                r"subroutine|module|do|if)|implicit\s+none|use\s+\w+|"
                r"(integer|real|double\s+precision|logical|character|"
                r"complex)\b.*::|do\s+\w+\s*=|!\$(acc|omp))\b",
                re.I | re.M)
_SHELL = re.compile(r"^\s*(\$|%|>)\s+\S+|^\s*(nvfortran|nvc|nvc\+\+|ftn|cc|"
                    r"amdflang|flang|clang|make|cmake|module)\s", re.M)


def language(code: str) -> str:
    """'fortran', 'c', 'c++', 'shell' or 'other': a guess from the text."""
    f, c, x = len(_F.findall(code)), len(_C.findall(code)), \
        len(_CXX.findall(code))
    if x and x >= 1 and (c or not f):
        return "c++"
    if f and f >= c:
        return "fortran"
    if c:
        return "c"
    if _SHELL.search(code):
        return "shell"
    return "other"


_TPR = re.compile(r"\bTPR\s*#?\s*:?\s*(\d{4,6})\b", re.I)
_FIXED = re.compile(r"\b(?:is|was|been|be|are|were|got|now)?\s*(?:fixed|"
                    r"resolved|corrected)\s+(?:in|as\s+of|with|since|for)\s+"
                    r"(?:the\s+|our\s+|an?\s+)?(?:NVHPC|NV\s*HPC|HPC\s*SDK|PGI|"
                    r"nvfortran|nvc|release|version|compiler|upcoming|next)?"
                    r"\s*(?:SDK\s+|release\s+|version\s+)?v?(\d{2}\.\d{1,2})"
                    r"\b", re.I)


def tprs(text: str) -> set[str]:
    return set(_TPR.findall(text))


def fixed_in(text: str) -> set[str]:
    return set(_FIXED.findall(text))


_COMPILERS = {
    "cce": r"\bCCE\b|\bcrayftn\b|\bcraycc\b|\bcray\s+(fortran|compiler|"
           r"ftn|cc)\b|\bftn-\d{3,4}\b|\bPrgEnv-cray\b",
    "nvhpc": r"\bnvfortran\b|\bnvc\b|\bnvc\+\+|\bNVHPC\b|\bNV\s?HPC\b|"
             r"\bHPC\s?SDK\b|\bpgfortran\b|\bpgcc\b|\bpgf90\b|\bPGI\b",
    "amd-flang": r"\bamdflang\b|\bamd-flang\b|\bflang-new\b|\bAFAR\b|"
                 r"\bLLVMFlang\b",
    "amd-clang": r"\bamdclang\b",
    "aomp": r"\bAOMP\b",
    "rocm": r"\bROCm\b|\bhipcc\b",
    "gcc": r"\bgfortran\b|\bGCC\b",
    "intel": r"\bifx\b|\bicx\b|\boneAPI\b",
    "xl": r"\bxlf\b|\bIBM\s+XL\b",
}
_COMPILER_RE = {k: re.compile(v, re.I) for k, v in _COMPILERS.items()}


def compilers(text: str) -> set[str]:
    return {k for k, r in _COMPILER_RE.items() if r.search(text)}
