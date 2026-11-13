"""Wrap a Fortran header comment line at 132 characters (F2018 6.3.2.1).

A break is made only at a space with a non-space on both sides, so the
readers that join continuations with one space (findings.unfold,
expected.derivation_evidence) get the original line back."""
from __future__ import annotations

LIMIT = 132


def wrap_line(line: str, cont: str = "!   ", limit: int = LIMIT) -> list[str]:
    out = []
    cur = line
    while len(cur) > limit:
        k = limit
        while k > len(cont) + 1 and not (
                cur[k] == " " and cur[k - 1] != " " and cur[k + 1:k + 2] not in (" ", "")):
            k -= 1
        if k <= len(cont) + 1:
            break  # one token longer than the limit: leave it
        out.append(cur[:k])
        cur = cont + cur[k + 1:]
    out.append(cur)
    return out


def wrap_comments(text: str, limit: int = LIMIT) -> str:
    """Free-form Fortran source with every comment line over the limit
    wrapped: `! derivation:` and the keyed fuzz header lines use the
    continuations their readers know, other comments continue on `! `."""
    out = []
    for ln in text.split("\n"):
        if len(ln) <= limit or not ln.startswith("!"):
            out.append(ln)
        elif ln.startswith("! derivation"):
            out.extend(wrap_line(ln, "! derivation: ", limit))
        elif ln.startswith(("! - ", "! failure:", "! expected:", "! observed:",
                            "! also fails on:")):
            out.extend(wrap_line(ln, "!   ", limit))
        else:
            out.extend(wrap_line(ln, "! ", limit))
    return "\n".join(out)
