"""Device-heap-temporary detector.

AFAR's flang lowers some statements inside a kernel to a heap allocation per
iteration. An array constructor becomes a ``fir.allocmem`` plus a copy and a
free, and the device code then calls the device allocator.

Compiling with ``-save-temps`` leaves the device module's FIR
(``*-openmp-amdgpu...-gfx942-fir.mlir``). This module reads it and reports
the ``fir.allocmem`` operations and the Fortran runtime calls inside device
code: the bodies of ``omp.target`` and of procedures marked
``omp.declare_target``. Host code in the same file is not counted.

A program whose device module allocates is at risk on AFAR with XNACK=1.
The IR does not show whether the allocator fails, so this is a candidate
for a check, not a verdict."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

_TARGET = re.compile(r"\bomp\.target\b(?!_)")
_DECLARE = re.compile(r"\bfunc\.func\b.*\bomp\.declare_target\b")
_ALLOCMEM = re.compile(r"\bfir\.allocmem\b\s*(![^\s,{]*(?:<[^>]*>)?)?")
_BINDC = re.compile(r'bindc_name\s*=\s*"([^"]*)"')
_CALL = re.compile(r"\bfir\.call\s+@(_Fortran\w+)")
# the runtime entries that allocate through the device allocator: an allocatable or pointer
# allocate, and an assignment (which reallocates an allocatable left-hand side or builds a
# temporary)
_ALLOCATING = re.compile(r"^_FortranA(?:AllocatableAllocate|AllocatableReallocate|PointerAllocate|"
                         r"Assign|CopyInAssign)")

TEMP_CLASSES = {
    ".tmp.arrayctor": "array constructor",
    ".tmp.result": "array-valued function result",
    ".tmp.assign": "assignment copy",
    ".tmp.array": "array expression",
    ".tmp.intrinsic": "array intrinsic result",
    ".tmp.sect": "array section copy",
    ".tmp.char": "character temporary",
}


def temp_class(name: str) -> str:
    if not name:
        return "unnamed (allocatable realloc or other)"
    for k, v in TEMP_CLASSES.items():
        if name.startswith(k):
            return v
    if name.startswith(".tmp"):
        return "other temporary"
    return "other"


@dataclass
class Scan:
    device_regions: int = 0
    allocmem: list = field(default_factory=list)       # (bindc_name, type)
    freemem: int = 0
    runtime_calls: Counter = field(default_factory=Counter)

    @property
    def n_allocmem(self) -> int:
        return len(self.allocmem)

    @property
    def allocating_calls(self) -> Counter:
        """The runtime calls in device code that allocate (AllocatableAllocate*, PointerAllocate*,
        Assign* ...): the same device allocator as `fir.allocmem`, without an allocmem in the FIR."""
        return Counter({k: v for k, v in self.runtime_calls.items() if _ALLOCATING.match(k)})

    @property
    def at_risk(self) -> bool:
        return self.n_allocmem > 0 or bool(self.allocating_calls)

    def classes(self) -> Counter:
        return Counter(temp_class(n) for n, _ in self.allocmem)


def summarize(scans) -> dict:
    """The per-program record of tools/campaigns/devtemps.py from the scans of its device modules."""
    scans = list(scans)
    allocating = sum((s.allocating_calls for s in scans), Counter())
    return {"regions": sum(s.device_regions for s in scans),
            "allocmem": sum(s.n_allocmem for s in scans),
            "classes": dict(sum((s.classes() for s in scans), Counter())),
            "calls": dict(sum((s.runtime_calls for s in scans), Counter())),
            "allocating_calls": dict(allocating),
            "at_risk": any(s.at_risk for s in scans)}


def row_at_risk(row: dict) -> bool:
    """at_risk of a stored record, from its `allocmem` and `calls` (records written before the
    allocating runtime calls counted have `at_risk` from `allocmem` alone)."""
    return bool(row.get("allocmem")) or any(_ALLOCATING.match(k) for k in (row.get("calls") or {}))


_STRING = re.compile(r'"(?:[^"\\]|\\.)*"')


def _comment_free(line: str) -> str:
    """The line without a `//` comment (a `//` inside a quoted string is not a comment)."""
    pos = 0
    for m in _STRING.finditer(line):
        i = line.find("//", pos, m.start())
        if i >= 0:
            return line[:i]
        pos = m.end()
    i = line.find("//", pos)
    return line[:i] if i >= 0 else line


def _braces(line: str) -> int:
    """Opening minus closing braces outside quoted strings (the line has no comment)."""
    code = _STRING.sub('""', line)
    return code.count("{") - code.count("}")


def scan_fir(text: str) -> Scan:
    """The device regions of a FIR module and what they allocate."""
    out = Scan()
    lines = [_comment_free(x) for x in text.split("\n")]
    i = 0
    while i < len(lines):
        ln = lines[i]
        if _TARGET.search(ln) or _DECLARE.search(ln):
            out.device_regions += 1
            depth, j = 0, i
            while j < len(lines):
                body = lines[j]
                for m in _ALLOCMEM.finditer(body):
                    b = _BINDC.search(body)
                    out.allocmem.append((b.group(1) if b else "",
                                         (m.group(1) or "").strip()))
                if "fir.freemem" in body:
                    out.freemem += 1
                for c in _CALL.findall(body):
                    out.runtime_calls[c] += 1
                depth += _braces(body)
                if depth <= 0 and j >= i and ("{" in lines[i] or j > i):
                    break
                j += 1
            i = j + 1
            continue
        i += 1
    return out
