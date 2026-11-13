"""Supercomputing centres' known-issues pages as a bug source.

Pages come as HTML (the live page and its web.archive.org snapshots, e.g.
OLCF, whose known issues are injected from JIRA at build time) or as the
Markdown/RST sources of a docs repository whose history is the archive
(NERSC, ALCF, LUMI, CSC). Each parser splits a page into sections
(heading, text, code blocks); relevant() keeps the sections about an
offload compiler defect; entry_key() names an entry across snapshots
(the ticket id when it has one)."""
from __future__ import annotations

import html as _html
import re

from offload.engine.harvest_known import textscan

_H = re.compile(r"<h([1-6])[^>]*>(.*?)</h\1>", re.S | re.I)
_PRE = re.compile(r"<pre[^>]*>(.*?)</pre>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")


def _clean(s: str) -> str:
    return _html.unescape(_TAG.sub("", s))


def _ws(s: str) -> str:
    return " ".join(s.split())


def html_sections(page: str) -> list[dict]:
    out = []
    hs = list(_H.finditer(page))
    for k, m in enumerate(hs):
        end = hs[k + 1].start() if k + 1 < len(hs) else len(page)
        body = page[m.end():end]
        codes = [_clean(c).strip("\n") for c in _PRE.findall(body)]
        text = _ws(_clean(_PRE.sub(" ", body)))
        out.append({"heading": _ws(_clean(m.group(2))).rstrip("¶ ").strip(),
                    "level": int(m.group(1)), "text": text, "codes": codes})
    return out


_MD_H = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


def md_sections(md: str) -> list[dict]:
    out: list[dict] = []
    cur = None
    code: list[str] | None = None
    for line in md.splitlines():
        if code is not None:
            if _FENCE.match(line):
                if cur is not None:
                    cur["codes"].append("\n".join(code))
                code = None
            else:
                code.append(line)
            continue
        if _FENCE.match(line):
            code = []
            continue
        m = _MD_H.match(line)
        if m:
            cur = {"heading": m.group(2).strip(), "level": len(m.group(1)),
                   "text": "", "codes": []}
            out.append(cur)
        elif cur is not None:
            cur["text"] += " " + line
    for s in out:
        s["text"] = _ws(s["text"])
    return out


_RST_UL = re.compile(r"^([=\-~^\"'`#*+])\1{2,}\s*$")


def _dedent_block(lines: list[str]) -> str:
    ind = min((len(x) - len(x.lstrip()) for x in lines if x.strip()),
              default=0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(x[ind:] for x in lines)


def rst_sections(rst: str) -> list[dict]:
    lines = rst.splitlines()
    out: list[dict] = []
    cur = None
    levels: list[str] = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if ln.strip() and _RST_UL.match(nxt) and len(nxt.strip()) >= \
                len(ln.strip()) and not _RST_UL.match(ln):
            ch = nxt.strip()[0]
            if ch not in levels:
                levels.append(ch)
            cur = {"heading": ln.strip(), "level": levels.index(ch) + 1,
                   "text": "", "codes": []}
            out.append(cur)
            i += 2
            continue
        lit = ln.rstrip().endswith("::") or \
            re.match(r"^\s*\.\.\s+(code-block|code|sourcecode)::", ln)
        if lit and cur is not None:
            if not ln.strip().startswith(".."):
                cur["text"] += " " + ln.rstrip()[:-1]
            base = len(ln) - len(ln.lstrip())
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or
                                      lines[j].strip().startswith(":")):
                j += 1
            blk: list[str] = []
            while j < len(lines) and (not lines[j].strip() or
                                      len(lines[j]) - len(lines[j].lstrip())
                                      > base):
                blk.append(lines[j])
                j += 1
            if any(x.strip() for x in blk):
                cur["codes"].append(_dedent_block(blk))
            i = j
            continue
        if cur is not None:
            cur["text"] += " " + ln
        i += 1
    for s in out:
        s["text"] = _ws(s["text"])
    return out


_DEVICE_WORDS = re.compile(
    r"\bOpenMP\b.{0,80}\b(offload|target|GPU|device)\b|\b(offload|target)"
    r"\b.{0,80}\bOpenMP\b|\bOpenACC\b|!\$acc|!\$omp\s+target|#pragma\s+"
    r"(acc|omp\s+target)|\bomp\s+target\b|\bdeclare\s+target\b|"
    r"-fopenmp-targets|-mp=gpu|-acc\b|-hacc\b|-fopenmp\b.{0,40}--offload|"
    r"--offload-arch|\bomp_target_\w+|\bacc_\w+\(|\bdo\s+concurrent\b.{0,80}"
    r"\b(GPU|offload|stdpar)\b|-stdpar", re.I | re.S)


def relevant(sec: dict) -> bool:
    """A section about a defect of an offload compiler: it carries offload
    code (on a centre's page that code is for the centre's compilers), or
    its text names both a compiler and a device model."""
    blob = " ".join([sec["heading"], sec["text"]])
    code = "\n".join(sec["codes"])
    if {"acc", "omp-target"} & textscan.models(code):
        return True
    return bool(_DEVICE_WORDS.search(blob)) and \
        bool(textscan.compilers(blob + "\n" + code))


_TICKET = re.compile(r"\b([A-Z][A-Z0-9]{2,}[-_]\d{1,7})\b")


def entry_key(heading: str) -> str:
    m = _TICKET.search(heading)
    if m:
        return m.group(1).replace("_", "-")
    return _ws(heading).lower()


def union(rows: list[dict]) -> list[dict]:
    """One entry per (source, key) over every snapshot that shows it: the
    first and last snapshot dates, and the richest text and code seen."""
    by: dict[tuple, dict] = {}
    for r in sorted(rows, key=lambda r: r["snapshot"]):
        k = (r["source"], entry_key(r["heading"]))
        e = by.get(k)
        if e is None:
            e = by[k] = {**r, "key": k[1], "first_seen": r["snapshot"],
                         "last_seen": r["snapshot"], "snapshots": 0,
                         "pages": []}
            e.pop("snapshot", None)
        e["snapshots"] += 1
        e["last_seen"] = r["snapshot"]
        if r.get("page") not in e["pages"]:
            e["pages"].append(r.get("page"))
        if len(r["text"]) > len(e["text"]):
            e["text"] = r["text"]
        if sum(map(len, r["codes"])) > sum(map(len, e["codes"])):
            e["codes"] = r["codes"]
    return sorted(by.values(), key=lambda e: (e["source"], e["key"]))
