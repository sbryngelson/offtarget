"""Instrument a fuzz program so that it prints the running
checksum after every update of its checksum section (``T <stmt> <cs>``),
and compare two traces: the first statement (variable) and element where
a device run departs from a reference run tells which kernel's output is
wrong. The program is unchanged otherwise (the prints come after the
last kernel)."""
from __future__ import annotations

import re

MARK = "! fuzz: checksum"


def instrument(source: str) -> tuple[str, list[str]]:
    """(instrumented source, the checksum statements in order)."""
    lines = source.split("\n")
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == MARK)
    except StopIteration:
        raise ValueError("no checksum section")
    out, stmts = lines[:start + 1], []
    i = start + 1
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if s.startswith("cs = modulo("):
            block = [ln]
            while block[-1].rstrip().endswith("&"):
                i += 1
                block.append(lines[i])
            out.extend(block)
            ind = ln[:len(ln) - len(ln.lstrip())]
            k = len(stmts)
            text = re.sub(r"\s+", " ", " ".join(
                b.strip().rstrip("&").lstrip("&") for b in block))
            m = re.search(r"int\((.*), ?8\), 2147483629_8\)", text)
            stmts.append(m.group(1).strip() if m else text)
            val = f"int({m.group(1).strip()}, 8)" if m else "cs"
            out.append(f"{ind}print '(a,i0,a,i0)', 'T ', {k}, ' ', {val}")
        else:
            out.append(ln)
        i += 1
    return "\n".join(out), stmts


def parse(stdout: str) -> list[tuple[int, int]]:
    return [(int(a), int(b)) for a, b in
            re.findall(r"^T (\d+) (-?\d+)\s*$", stdout, re.M)]


def differences(dev: list, ref: list, stmts: list[str]) -> dict:
    """statement text -> [(element number, dev value, ref value)] of every
    value that differs ("length" when the traces differ in length)."""
    out: dict = {}
    seen: dict[int, int] = {}
    for a, b in zip(dev, ref):
        seen[b[0]] = seen.get(b[0], 0) + 1
        if a != b:
            name = stmts[b[0]] if b[0] < len(stmts) else str(b[0])
            out.setdefault(name, []).append((seen[b[0]], a[1], b[1]))
    if len(dev) != len(ref):
        out["length"] = [(len(dev), len(ref))]
    return out
