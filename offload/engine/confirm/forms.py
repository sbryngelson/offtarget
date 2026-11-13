"""Later forms of earlier constructs (catalog/later_forms.yaml).

A compile rejection is attributed to a form a later OpenMP version added
(the enter clause of 5.2, thread_limit on target of 5.1, ...) when the
diagnostic's message names it, or when the directive statement the
diagnostic points at (file and line from the stored reason, continuation
lines joined) uses it. The rules then read the vendor claims for the
form's own atom (RUL-LATER-FORM-UNCLAIMED): a general claim of an earlier
version ("full OpenMP 5.0") covers the earlier forms only."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from offload.engine.root import ROOT  # noqa: E402
FORMS = ROOT / "catalog" / "later_forms.yaml"


@dataclass(frozen=True)
class Form:
    id: str
    atom: str
    since: str
    what: str
    message: str = ""
    directive: str = ""
    citations: tuple = ()

    def cite(self) -> str:
        c = self.citations[0]
        return (f"{c['version']} §{c['section']} p.{c['page']}: "
                f"\"{c['quote']}\"")


@lru_cache(maxsize=None)
def forms() -> tuple:
    d = yaml.safe_load(FORMS.read_text()) or {}
    if d.get("version") != 1:
        raise ValueError("later forms: unknown version")
    out = []
    for f in d.get("forms") or ():
        out.append(Form(f["id"], f["atom"], str(f["since"]), f["what"],
                        f.get("message", ""), f.get("directive", ""),
                        tuple(f.get("citations") or ())))
    return tuple(out)


# where a diagnostic points: CCE Fortran "File = <path>, Line = N", a
# clang-style "<path>:N:C:" (AFAR clang, CCE C), flang's loc("<path>":N:C)
_POS = (re.compile(r"File = ([^,\s]+), Line = (\d+)"),
        re.compile(r"loc\(\"([^\"]+)\":(\d+):\d+\)"),
        re.compile(r"(?:^|[\s(])([^\s:()]+\.(?:f90|F90|c|cpp|h)):(\d+):\d+"))


def position(reason: str) -> tuple[str, int] | None:
    for pat in _POS:
        m = pat.search(reason or "")
        if m:
            return Path(m.group(1)).name, int(m.group(2))
    return None


def _file_text(text: str, name: str) -> str:
    from offload.engine.confirm.programs import split_files
    files = split_files(text)
    if not files:
        return text
    for n, t in files:
        if Path(n).name == name:
            return t
    return ""


def statement(text: str, reason: str) -> str:
    """The directive statement at the diagnostic's position (Fortran: the
    line with its continuation lines; C: with backslash continuations),
    "" when the reason has no position or the file is not found."""
    pos = position(reason)
    if pos is None or not text:
        return ""
    lines = _file_text(text, pos[0]).splitlines()
    k = pos[1] - 1
    if not 0 <= k < len(lines):
        return ""
    a = b = k

    def cont_before(i):        # line i-1 continues into line i
        prev = lines[i - 1].rstrip()
        return prev.endswith("&") or prev.endswith("\\")
    while a > 0 and cont_before(a):
        a -= 1
    while b + 1 < len(lines) and (lines[b].rstrip().endswith("&") or
                                  lines[b].rstrip().endswith("\\")):
        b += 1
    return "\n".join(lines[a:b + 1])


def match(text: str, reason: str) -> list[Form]:
    """The later forms a rejection is attributed to: the forms its message
    names, else (spot check) the forms of the directive statement
    it points at."""
    named = [f for f in forms()
             if f.message and re.search(f.message, reason or "")]
    if named:
        return named
    st = None
    out = []
    for f in forms():
        if f.directive:
            if st is None:
                st = re.sub(r"&\s*\n\s*!\$omp&?", " ", statement(text,
                                                                 reason),
                            flags=re.I)
            if st and re.search(f.directive, st):
                out.append(f)
    if len(out) > 1:
        out = _at_column(text, reason, out) or out
    return out


def _at_column(text: str, reason: str, found: list) -> list:
    """Of several forms of one statement, the one whose text on the
    reported line starts closest before the reported column."""
    m = re.search(r"Line = (\d+), Column = (\d+)", reason or "") or \
        re.search(r":(\d+):(\d+)", reason or "")
    pos = position(reason)
    if not m or pos is None:
        return []
    lines = _file_text(text, pos[0]).splitlines()
    k, col = int(m.group(1)) - 1, int(m.group(2))
    if not 0 <= k < len(lines):
        return []
    line = lines[k]
    best, where = [], -1
    for f in found:
        starts = [x.start() for x in re.finditer(
            f.directive.replace("(?i)", ""), line, re.I)
            if x.start() < col]
        if starts and max(starts) > where:
            best, where = [f], max(starts)
    return best
