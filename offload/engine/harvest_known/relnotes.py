"""PGI/NVHPC release notes as the dating source for TPR fixes.

The archived PGI pages (pgroup.com/support/release_tprs_<year>.htm, 2010 to
2019, via web.archive.org) are tables of TPR number, release, category,
problem and fix. Current NVHPC release notes list no TPRs; later fixes are
dated by the vendor's forum posts ("fixed in X.Y")."""
from __future__ import annotations

import html as _html
import re

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
_ACC = re.compile(r"accelerator|openacc|openmp|offload|gpu|cuda|\btarget\b",
                  re.I)


def _txt(s: str) -> str:
    return " ".join(_html.unescape(re.sub(r"<[^>]+>", " ", s)).split())


def pgi_tpr_rows(page: str) -> list[dict]:
    """Rows of TPR, release, category, problem, fix: five cells, or four
    with problem and fix in one cell separated by <br>."""
    out = []
    for r in _ROW.findall(page):
        raw = _CELL.findall(r)
        if len(raw) == 4:
            prob, _, fix = re.split(r"(<br\s*/?>)", raw[3], maxsplit=1) \
                if re.search(r"<br\s*/?>", raw[3]) else (raw[3], "", "")
            raw = raw[:3] + [prob, fix]
        cells = [_txt(c) for c in raw]
        if len(cells) >= 5 and re.fullmatch(r"\d{4,6}", cells[0]) and \
                re.fullmatch(r"\d+\.\d+(-\d+)?", cells[1]):
            out.append({"tpr": cells[0], "release": cells[1],
                        "category": cells[2], "problem": cells[3],
                        "fix": cells[4]})
    return out


def is_accelerator(row: dict) -> bool:
    return bool(_ACC.search(row["category"] + " " + row["problem"]))
