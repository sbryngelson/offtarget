"""The citations of a generated finding: a construct's own section of the specification, found by its
heading ("10.2 teams Construct", "5.8.7 defaultmap Clause"), and the first sentence of its Semantics
(OpenMP 5.2) or Summary (OpenACC 3.4), located to its printed page and lines in the cached text
(offload.engine.dataenv_rules.numbered), so every citation checks (dataenv_rules.check_citation).
A combined construct is cited by each construct it combines. No citation is written by hand."""
from __future__ import annotations

import re
from functools import lru_cache

VERSION = {"omp": "OpenMP 5.2", "acc": "OpenACC 3.4"}
OPENING = {"omp": ("Semantics", "Summary"), "acc": ("Summary", "Semantics")}
KINDS = ("construct", "directive", "directives", "clause")
# a sentence that only says what kind of thing its subject is ("The reduction clause is a reduction
# scoping clause ...", "The declare target directive is a declare target directive.")
CLASSIFIES = re.compile(r"^The [\w ]+ (?:clause|directive|construct) is an? [\w -]*(?:clause|directive|construct)\b")


@lru_cache(maxsize=None)
def _rows(version: str) -> tuple:
    from offload.engine.dataenv_rules import numbered
    return tuple(numbered(version))


@lru_cache(maxsize=None)
def headings(version: str) -> dict:
    """{"teams construct": section, ...}: a section's own heading line, lower-cased."""
    out = {}
    for _, _, text, sec in _rows(version):
        m = re.match(r"^(\d+(?:\.\d+)*)\s+(.+?)\s*$", text)
        if m and m.group(1) == sec:
            out.setdefault(m.group(2).lower(), sec)
    return out


def _sections(key: str, model: str) -> list[str]:
    """The sections a construct key names: "dir:target teams" -> target, teams; "clause:if" -> if."""
    heads = headings(VERSION[model])
    kind, _, name = key.partition(":")
    if kind == "clause":
        sec = heads.get(f"{name} clause")
        return [sec] if sec else []
    words, out = name.split(), []
    while words:
        for n in range(len(words), 0, -1):
            title = " ".join(words[:n])
            sec = next((heads[f"{title} {k}"] for k in KINDS if f"{title} {k}" in heads), None)
            if sec:
                out.append(sec)
                words = words[n:]
                break
        else:
            words = words[1:]          # a word with no section of its own
    return out


def _sentence(version: str, section: str, openings: tuple) -> dict | None:
    rows = [r for r in _rows(version) if r[3] == section]
    # the first sentence after the section's Semantics or Summary heading; a section without one
    # (an OpenACC clause) opens with its text right after its own heading line (rows[0])
    starts = [next((k for k, r in enumerate(rows) if r[2].strip() == head), None) for head in openings]
    for i in [k for k in starts if k is not None] + [0]:
        body = rows[i + 1:]
        if not body:
            continue
        page = body[0][0]
        used, text = [], ""
        for r in body:
            if r[0] != page or r[2].strip() in ("Syntax", "Restrictions", "Cross References", "Binding"):
                break
            used.append(r)
            line = r[2].strip()
            # a word broken across lines ("direc-" / "tives") is one word
            text = text[:-1] + line if text.endswith("-") else (text + " " + line).strip()
            m = re.search(r"(?<!e\.g)(?<!i\.e)\.(?:\s|$)", text)
            if m:
                if CLASSIFIES.match(text[:m.start() + 1]):
                    # pass over it: the next sentence starts after it, on this line or the next
                    rest = text[m.end():].strip()
                    used, text = ([r] if rest else []), rest
                    continue
                text = text[:m.start() + 1]
                break
        if len(text) < 20:
            continue
        lo, hi = used[0][1], used[-1][1]
        return {"version": version, "section": section, "page": page,
                "lines": str(lo) if lo == hi else f"{lo}-{hi}", "quote": text}
    return None


def cites(key: str, model: str = "omp") -> list[dict]:
    """The citations of a construct key (offload.engine.confirm.programs constructs: "dir:...",
    "clause:..."), one per section it names; [] when the specification has no section for it."""
    version = VERSION["acc" if model == "acc" else "omp"]
    out = []
    for sec in _sections(key, "acc" if model == "acc" else "omp"):
        c = _sentence(version, sec, OPENING["acc" if model == "acc" else "omp"])
        if c and c not in out:
            out.append(c)
    return out


def cite(key: str, model: str = "omp") -> dict | None:
    cs = cites(key, model)
    return cs[0] if cs else None


def text(c: dict) -> str:
    """A citation as a finding's header writes it: "quote" (OpenMP 5.2 §10.2 p.230 l.12)."""
    return f'"{c["quote"]}" ({c["version"]} §{c["section"]} p.{c["page"]} l.{c["lines"]})'
