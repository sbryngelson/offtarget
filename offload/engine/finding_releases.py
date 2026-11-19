"""The `releases` line of a finding header: what each release of a compiler family does with the
finding's file in the site matrix (the committed check rows, offload.engine.site.matrix), for the
families with more than one release run on it.

The rest of a header states what the rows showed when the finding was written; a release added
later is named only here. The line is generated (tools/derive/finding_releases.py) and kept current
by tools/regenerate.py (step finding-releases), never written by hand. Example:

    ! - releases: AFAR 24.3.0 and 24.4.0 fail it the same way; CCE 19.0.0 runs it correctly
"""
from __future__ import annotations

import re

from offload.engine import finding_header as H
from offload.engine.site import data as D
from offload.engine.site import matrix as M
from offload.engine.toolchains import registry

KEY = "releases"
_R = registry()
# the states of a cell, in the words of the line (plural verb: one or more releases)
_WORDS = {"fails-like": ("fails it the same way", "fail it the same way"),
          "fails-differently": ("fails it another way", "fail it another way"),
          "correct": ("runs it correctly", "run it correctly")}
_KNOWN = tuple(_WORDS)


def release_name(tc: str) -> str:
    """A release as headers name it ("AFAR 24.4.0", "CCE 21.0.3"): the family name and version."""
    fam, label, _ = M.VERSIONS[tc]
    name = _R.families[fam].name
    return label if label.startswith(name) else f"{name} {label}"


def _state(cells: list) -> str | None:
    """One release's state over its targets: one word when every measured target agrees, else
    per target ("fails it the same way on MI300A copy; runs it correctly on MI250X")."""
    by = {}
    for c in cells:
        if c.state in _KNOWN:
            by.setdefault(c.state, []).append(D.TG_SHORT.get(c.target, c.target))
    if not by:
        return None
    if len(by) == 1:
        return next(iter(by))
    return " and ".join(f"{_WORDS[s][0]} on {', '.join(ts)}" for s, ts in
                        sorted(by.items(), key=lambda x: _KNOWN.index(x[0])))


def _names(tcs: list) -> str:
    """"AFAR 24.3.0 and 24.4.0", "CCE 19.0.0, 20.0.2 and 21.0.3": the family name once."""
    first, rest = release_name(tcs[0]), [M.VERSIONS[t][1].split()[-1] for t in tcs[1:]]
    parts = [first] + rest
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def value(finding_id: str, cells: list | None = None) -> str | None:
    """The line's text for a finding (its id: the path under data/findings without the suffix),
    or None. It covers the families the file fails the same way on in some release and that have
    more than one release run on it (GCC is one release built for two GPUs: never)."""
    cells = M.cells(finding_id) if cells is None else cells
    out = []
    for fam in _R.family_order():
        tcs = [t for t in M.TOOLCHAINS if M.VERSIONS[t][0] == fam]
        states = [(t, _state([c for c in cells if c.tc == t])) for t in tcs]
        states = [(t, s) for t, s in states if s]
        if len({_R.toolchains[t].version for t, _ in states}) < 2:
            continue
        if not any(c.state == "fails-like" for c in cells if c.tc in tcs):
            continue
        groups = []                      # consecutive releases with one state
        for t, s in states:
            if groups and groups[-1][1] == s:
                groups[-1][0].append(t)
            else:
                groups.append(([t], s))
        for ts, s in groups:
            words = _WORDS[s][len(ts) > 1] if s in _WORDS else s
            out.append(f"{_names(ts)} {words}")
    return "; ".join(out) or None


def _lead(text: str) -> str:
    return "//" if text.lstrip().startswith("//") else "!"


def apply(text: str, val: str | None) -> str:
    """The file with its `releases` bullet set to `val` (None: removed). An existing bullet is
    replaced in place; a new one goes after the header's first run of bullets (a bullet's
    continuation lines, a quoted block among them, are part of it), or at the end of a header
    written as prose. A file that does not start with a comment is returned unchanged."""
    lead = _lead(text)
    lines = text.split("\n")
    bullet = re.compile(rf"^{re.escape(lead)} - ")
    cont = re.compile(rf"^{re.escape(lead)}   ")
    mine = re.compile(rf"^{re.escape(lead)} - {KEY}:")
    new = H.bullet(KEY, val, lead) if val else []
    for k, ln in enumerate(lines):
        if mine.match(ln):
            j = k + 1
            while j < len(lines) and cont.match(lines[j]):
                j += 1
            return "\n".join(lines[:k] + new + lines[j:])
    if not val:
        return text
    head = next((k for k, ln in enumerate(lines) if not ln.startswith(lead)), len(lines))
    if head == 0:
        return text
    start = next((k for k in range(head) if bullet.match(lines[k])), None)
    if start is None:
        j = head
    else:
        j = start
        while j < head and (bullet.match(lines[j]) or cont.match(lines[j])):
            j += 1
    return "\n".join(lines[:j] + new + lines[j:])


def strip(text: str) -> str:
    """The file without its `releases` bullet (what the header said before the line existed)."""
    return apply(text, None)
