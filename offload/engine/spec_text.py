"""Sectioned OpenMP and OpenACC spec text with citations.

A version string names an OpenMP spec ("5.2") or, with the prefix ``acc``, an
OpenACC spec ("acc3.4": spec/openacc/openacc-3.4.pdf). Citations read
"OpenMP 5.2 §..." or "OpenACC 3.4 §...".

Text is extracted once per version with ``pdftotext -layout`` into
``results/spec_cache/`` (git-ignored). Numbered headings (``7.9.6 map Clause``)
split it into sections keyed by title; a repeated title gets ``" [<number>]"``
appended. Page numbers are the printed ones, with the PDF page index as fallback.

``restrictions`` returns each bullet of a section's "Restrictions" subsection.
The name may be a construct, directive or clause, with spaces or underscores.
An unknown name raises KeyError; a section without Restrictions gives [].
``language`` is "C/C++", "Fortran" or "" from the surrounding banners."""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = ROOT / "results" / "spec_cache"
PDFTOTEXT = "/usr/bin/pdftotext"


@dataclass
class Section:
    title: str
    first_page: int
    last_page: int
    text: str
    number: str = ""


@dataclass
class RestrictionItem:
    text: str
    citation: str
    language: str = ""


_MARGIN = re.compile(r"^ ?\d{1,2}(?:\s+|$)")
_HEADING = re.compile(r"^(\d+(?:\.\d+)+)\s+([A-Za-z_\[][^.\n]*?)\s*$")
_FOOT1 = re.compile(r"^\s*(\d+)\s+OpenMP API")
_FOOT2 = re.compile(r"^\s*(?:CHAPTER|ANNEX|APPENDIX|Index)\b.*?\s(\d+)\s*$")
_CHAPTER = re.compile(r"^(\d{1,2})\s+([A-Z][A-Za-z ,\-]*[A-Za-z])$")
_FOOT3 = re.compile(r"^\s{3,}(\d+)\s*$")  # bare number as last line of a page
_BANNERS = {"C / C++": "C/C++", "C++": "C/C++", "C": "C/C++", "Fortran": "Fortran"}
_SUBHEADS = {
    "Summary", "Syntax", "Arguments", "Description", "Binding", "Semantics",
    "Restrictions", "Cross References", "Clauses", "Properties", "Modifiers",
    "Execution Model Events", "Tool Callbacks", "Format", "Additional Definitions",
}


def _model(version: str) -> tuple[str, str, str]:
    """(spec directory/file stem, number, citation name) of a version
    string: "5.2" -> ("openmp", "5.2", "OpenMP"), "acc3.4" -> ("openacc",
    "3.4", "OpenACC")."""
    if version.startswith("acc"):
        return "openacc", version[3:], "OpenACC"
    return "openmp", version, "OpenMP"


def cite_name(version: str) -> str:
    """'OpenMP 5.2' / 'OpenACC 3.4' for a version string."""
    _, num, name = _model(version)
    return f"{name} {num}"


# OpenACC pages: margin line numbers run to four digits, and each page
# opens with a running header "The OpenACC® API Version 3.4 <section>"
_ACC_MARGIN = re.compile(r"^\s*\d{1,4}(?:\s+|$)")
_ACC_HEADER = re.compile(r"^\s*The OpenACC\S* API Version")


def _text(version: str) -> str:
    stem, num, _ = _model(version)
    pdf = ROOT / "spec" / stem / f"{stem}-{num}.pdf"
    if not pdf.is_file():
        raise FileNotFoundError(pdf)
    cache = CACHE_DIR / f"{stem}-{num}.txt"
    if not cache.is_file() or cache.stat().st_mtime < pdf.stat().st_mtime:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run([PDFTOTEXT, "-layout", str(pdf), str(cache)], check=True,
                       cwd=str(ROOT))
    return cache.read_text(encoding="utf-8", errors="replace")


@lru_cache(maxsize=None)
def _lines(version: str) -> tuple:
    """(printed_page, line) for every body line, margin numbers stripped."""
    out = []
    acc = version.startswith("acc")
    margin = _ACC_MARGIN if acc else _MARGIN
    for idx, page in enumerate(_text(version).split("\f"), start=1):
        raw = page.rstrip().split("\n")
        if acc:
            raw = [ln for ln in raw if not _ACC_HEADER.match(ln)] or [""]
        foot = len(raw) - 1 if _FOOT3.match(raw[-1]) else None
        printed = idx
        for j in range(len(raw) - 1, -1, -1):
            m = _FOOT1.match(raw[j]) or _FOOT2.match(raw[j]) or (
                _FOOT3.match(raw[j]) if j == foot else None)
            if m:
                printed = int(m.group(1))
                break
        body = [margin.sub("", ln, count=1).strip() for j, ln in enumerate(raw)
                if not (_FOOT1.match(ln) or _FOOT2.match(ln) or j == foot)]
        # Blank lines at page edges come from headers/footers, not from the
        # text, so they must not look like paragraph breaks.
        while body and not body[0]:
            body.pop(0)
        while body and not body[-1]:
            body.pop()
        out.extend((printed, ln) for ln in body)
    return tuple(out)


@lru_cache(maxsize=None)
def _heads(version: str) -> tuple:
    """(line index, number, title) of numbered headings, chapters included.

    Chapter headings ("14 Interoperability") have a single number, so they are
    accepted only when they are the next chapter in sequence.
    """
    heads = []
    chapter = 0
    for i, (_, ln) in enumerate(_lines(version)):
        if ". . ." in ln:
            continue
        m = _HEADING.match(ln)
        if m and not ln.endswith(","):
            heads.append((i, m.group(1), m.group(2)))
            continue
        m = _CHAPTER.match(ln)
        if m and int(m.group(1)) == chapter + 1:
            chapter += 1
            heads.append((i, m.group(1), m.group(2)))
    return tuple(heads)


@lru_cache(maxsize=None)
def _sections(version: str) -> tuple:
    lines = _lines(version)
    heads = _heads(version)
    result = []
    for k, (i, num, title) in enumerate(heads):
        end = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
        body = lines[i + 1:end]
        text = "\n".join(l for _, l in body).strip()
        if not text:
            continue
        result.append(Section(title, lines[i][0], body[-1][0], text, num))
    return tuple(result)


def sections(version: str) -> dict[str, Section]:
    out: dict[str, Section] = {}
    for s in _sections(version):
        key = s.title if s.title not in out else f"{s.title} [{s.number}]"
        out[key] = s
    return out


_SUFFIXES = ("", " Construct", " Directive", " Clause")


def _candidates(name: str) -> list[str]:
    forms = [name, name.replace(" ", "_")]
    return [f + s for f in dict.fromkeys(forms) for s in _SUFFIXES]


def _find_construct(version: str, name: str) -> Section:
    secs = _sections(version)
    tried = _candidates(name)
    for title in tried:
        for s in secs:
            if s.title == title:
                return s
    raise KeyError(f"no {cite_name(version)} section titled any of {tried}")


def restrictions(version: str, construct: str) -> list[RestrictionItem]:
    sec = _find_construct(version, construct)  # KeyError if unknown name
    lines = _lines(version)
    heads = _heads(version)
    k = next(k for k, h in enumerate(heads) if h[1] == sec.number and h[2] == sec.title)
    start = heads[k][0]
    stop = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
    items: list[RestrictionItem] = []
    cur: list[str] | None = None
    cur_page = 0
    cur_lang = ""
    in_restr = False
    lang = ""
    prev_blank = False

    def flush():
        nonlocal cur
        if cur:
            text = re.sub(r"\s+", " ", " ".join(cur)).strip()
            items.append(RestrictionItem(
                text, f"{cite_name(version)} §{sec.number}, p.{cur_page}",
                cur_lang))
        cur = None

    for page, ln in lines[start + 1:stop]:
        if ln in _BANNERS:
            if in_restr:
                flush()
            lang = "" if lang == _BANNERS[ln] else _BANNERS[ln]
            continue
        if ln == "Restrictions":
            flush()
            in_restr = True
            continue
        if ln in _SUBHEADS:
            flush()
            in_restr = False
            continue
        if not in_restr:
            continue
        if not ln:
            prev_blank = True
            continue
        if re.match(r"^Restrictions to .* are as follows:?$", ln):
            continue
        if ln.startswith("•"):
            flush()
            cur, cur_page, cur_lang = [ln.lstrip("• ").strip()], page, lang
        elif cur is not None and not prev_blank:
            cur.append(ln)
        else:
            flush()
            cur, cur_page, cur_lang = [ln], page, lang
        prev_blank = False
    flush()
    return items
