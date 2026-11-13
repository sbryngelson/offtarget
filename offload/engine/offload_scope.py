"""Device-offload scope of a program.

The project measures device offload only (OpenMP target offload and OpenACC
compute offload). A program is a host test when its construct of interest
runs on the host: any OpenMP or OpenACC directive outside a target (OpenACC:
compute) region that is not offload machinery.

``host_constructs(source, version)`` lists the directives that are not inside
a target or compute construct, not in device code (a procedure or C function
under ``declare target`` or ``routine``, unless ``device_type(host)``), and
not offload machinery (``OMP_MACHINERY``, ``ACC_MACHINERY``). A program may
keep a host construct on purpose as a ``host+device`` pattern
(``SCOPE_HOST_DEVICE``, ``scope_of``), judged on the device result.
``check(program)`` raises ``ScopeError`` for any other host construct and for
a clause that sends a device construct to the host (``HOST_EXECUTION_CLAUSES``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from offload.engine.catalog import model_of
from offload.engine.rules import leaves, parse_program

SCOPE_DEVICE = "device"
SCOPE_HOST_DEVICE = "host+device"
SCOPES = (SCOPE_DEVICE, SCOPE_HOST_DEVICE)

# Offload machinery that may stand outside a target region.
OMP_MACHINERY = frozenset({
    "target data", "target enter data", "target exit data", "target update",
    "declare target", "begin declare target", "end declare target",
    "declare mapper", "declare reduction", "requires", "depobj"})
# Allowed outside a target region only where they complete target tasks.
OMP_TASK_SYNC = frozenset({"taskwait", "taskgroup"})
ACC_MACHINERY = frozenset({
    "data", "enter data", "exit data", "update", "declare", "host_data",
    "routine", "wait", "init", "set", "shutdown"})
_DEVICE_DATA = frozenset({"target data", "target enter data",
                          "target exit data", "target update"})
_ACC_COMPUTE = frozenset({"parallel", "kernels", "serial"})

# A device-scope program may not send its device construct to the host at
# run time: a literal false if on a target/compute construct, OpenACC self
# without a condition or with a literal true one.
HOST_EXECUTION_CLAUSES = re.compile(
    r"(?:\$(?:omp|acc)|#pragma\s+(?:omp|acc))\b[^\n]*?"
    r"(?:\bif\s*\(\s*(?:\.false\.|false|0)\s*\)"
    r"|\bself\s*\(\s*(?:\.true\.|true|1)\s*\)"
    r"|device_type\s*\(\s*host\s*\))", re.I)

_SCOPE_LINE = re.compile(r"^(?:!|//) scope: (host\+device): (.+)$", re.M)


class ScopeError(ValueError):
    """A program outside the device-offload scope."""


@dataclass(frozen=True)
class HostConstruct:
    line: int
    directive: str
    why: str


def scope_of(source: str) -> tuple[str, str]:
    """(scope, realistic use) from the program header: ``host+device`` and
    its use for a pattern program, else (``device``, "")."""
    m = _SCOPE_LINE.search(source)
    return (m.group(1), m.group(2)) if m else (SCOPE_DEVICE, "")


def _is_compute(name: str, model: str) -> bool:
    ls = leaves(name, model)
    if model == "acc":
        return ls[0] in _ACC_COMPUTE
    return ls[0] == "target" and name not in _DEVICE_DATA


def _c_device_lines(source: str) -> set[int]:
    """1-based lines of C code between begin declare target (or a
    clause-less declare target) and end declare target, without
    device_type(host)."""
    out, depth, host = set(), 0, []
    for k, line in enumerate(source.splitlines(), 1):
        s = line.strip()
        if re.match(r"#pragma\s+omp\s+(begin\s+declare\s+target|"
                    r"declare\s+target\s*$|declare\s+target\s+"
                    r"device_type)", s):
            depth += 1
            host.append(bool(re.search(r"device_type\s*\(\s*host", s)))
            continue
        if re.match(r"#pragma\s+omp\s+end\s+declare\s+target", s):
            depth = max(0, depth - 1)
            if host:
                host.pop()
            continue
        if depth and not any(host):
            out.add(k)
    return out


def _f_device_units(tree, model: str) -> set:
    """Scoping units (Fortran procedures) whose own specification part has
    a declare target (OpenACC: routine) directive without
    device_type(host)."""
    want = "routine" if model == "acc" else "declare target"
    out = set()
    for i, d in enumerate(tree.directives):
        if d.name != want:
            continue
        if any(c.name == "device_type" and any(
                a.strip().lower() == "host" for a in c.args)
               for c in d.clauses):
            continue
        scope = tree.assoc[i].scope
        if scope and tree.units.get(scope[-1], ("", None))[0] in (
                "subroutine", "function"):
            out.add(scope[-1])
    return out


def _has_target_tasks(tree, model: str) -> bool:
    for i, d in enumerate(tree.directives):
        if _is_compute(d.name, model) or d.name in _DEVICE_DATA:
            if any(c.name in ("nowait", "in_reduction", "depend")
                   for c in d.clauses):
                return True
    return False


def host_constructs(source: str, version: int,
                    lang: str | None = None) -> list[HostConstruct]:
    """The directives of `source` that are host constructs (module
    docstring), in source order."""
    model = model_of(version)
    tree = parse_program(source, version, lang)
    c = tree.lang == "c"
    dev_lines = _c_device_lines(source) if c else set()
    dev_units = set() if c else _f_device_units(tree, model)
    machinery = ACC_MACHINERY if model == "acc" else OMP_MACHINERY
    tasks = _has_target_tasks(tree, model)
    out = []
    for i, d in enumerate(tree.directives):
        anc, p = [], tree.parent(i)
        while p is not None:
            anc.append(p)
            p = tree.parent(p)
        if _is_compute(d.name, model):
            continue
        if any(_is_compute(tree.directives[a].name, model) for a in anc):
            continue
        a = tree.assoc[i]
        if (c and a.line in dev_lines) or any(s in dev_units
                                              for s in a.scope):
            continue
        if d.name in machinery:
            continue
        if model == "omp" and d.name in OMP_TASK_SYNC:
            if tasks:
                continue
            why = "completes no target task"
        else:
            why = "outside a target region" if model == "omp" else \
                "outside a compute region"
        out.append(HostConstruct(a.line, d.name, why))
    return out


def host_execution(source: str) -> list[str]:
    """Directive lines whose clause sends the device construct to the host
    at run time (HOST_EXECUTION_CLAUSES)."""
    return [m.group(0).strip() for m in HOST_EXECUTION_CLAUSES.finditer(
        source)]


def check(prog) -> None:
    """Raise ScopeError when `prog` (a offload.engine.gen.Program) is outside
    the device-offload scope: a host construct in a device-scope program,
    a host+device program without one or without its use, or a construct
    sent to the host by a clause. Illegal variants are checked too: their
    rule must be broken inside the offload code."""
    version = int(re.match(r"(?:omp|acc)(\d\d)-", prog.id).group(1))
    lang = "c" if prog.lang == "c" else "f90"
    scope, use = scope_of(prog.source)
    found = host_constructs(prog.source, version, lang)
    if scope == SCOPE_DEVICE and found:
        raise ScopeError(f"{prog.id}: host constructs " + ", ".join(
            f"{h.directive} (line {h.line}: {h.why})" for h in found))
    if scope == SCOPE_HOST_DEVICE and (not found or not use.strip()):
        raise ScopeError(f"{prog.id}: host+device pattern without "
                         + ("a host construct" if not found else
                            "its realistic use"))
    sent = host_execution(prog.source)
    if sent:
        raise ScopeError(f"{prog.id}: device construct sent to the host: "
                         + "; ".join(sent))
