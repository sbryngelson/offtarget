"""The rulings registry (catalog/rulings.yaml).

Each entry turns a ruling of data/reports/rulings.md into something a rule
can cite by id: its kind, the rulings.md text it comes from, its spec
citations (version, section, printed page, quoted sentence) and what it
applies to. ``check`` verifies an entry against rulings.md and the spec
text; ``matching`` returns the entries that apply to a program and a
failure reason."""
from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path

import yaml

from offload.engine.root import ROOT  # noqa: E402
REGISTRY = ROOT / "catalog" / "rulings.yaml"
RULINGS_MD = ROOT / "data" / "reports" / "rulings.md"
KINDS = ("legality", "spec_reading", "implementation_defined", "unspecified",
         "no_fixed_value", "oracle", "mode", "environment", "process")
# kinds under which the spec leaves the observed value open (an
# implementation-defined *support* of a feature, e.g. a requirement, does
# not: a supported feature must work)
OPEN_KINDS = ("unspecified", "no_fixed_value")


@dataclass(frozen=True)
class Entry:
    id: str
    kind: str
    task: str
    rulings_md: str
    citations: tuple
    applies: dict = field(default_factory=dict, hash=False, compare=False)
    test: str = ""
    # A ruling that decides the support of the
    # programs it applies to ({verdict, families, outcome}); the confirmer
    # applies it before the family-witness rules (R11, R12b)
    decides: dict = field(default_factory=dict, hash=False, compare=False)

    def cite(self) -> str:
        if not self.citations:
            return f"{self.id} (rulings.md)"
        c = self.citations[0]
        return (f"{self.id} ({c['version']} §{c['section']} p.{c['page']}: "
                f"\"{c['quote']}\")")


def _norm(text: str) -> str:
    return " ".join(text.replace("’", "'").split())


def load(path: Path = REGISTRY) -> dict[str, Entry]:
    data = yaml.safe_load(Path(path).read_text()) or {}
    if data.get("version") != 1:
        raise ValueError("rulings registry: unknown version")
    out: dict[str, Entry] = {}
    for d in data.get("entries") or []:
        if d["id"] in out:
            raise ValueError(f"duplicate registry id {d['id']}")
        if d["kind"] not in KINDS:
            raise ValueError(f"{d['id']}: unknown kind {d['kind']}")
        out[d["id"]] = Entry(d["id"], d["kind"], str(d.get("task", "")),
                             d["rulings_md"],
                             tuple(d.get("citations") or ()),
                             dict(d.get("applies") or {}), d.get("test", ""),
                             dict(d.get("decides") or {}))
    return out


@lru_cache(maxsize=None)
def entries() -> dict:
    return load()


def in_rulings_md(text: str, md: str | None = None) -> bool:
    md = RULINGS_MD.read_text() if md is None else md
    return _norm(text) in _norm(md.replace("\n  ", " "))


@lru_cache(maxsize=None)
def _spec(version: str):
    from offload.engine.spec_text import _lines
    text, starts, pages = "", [], []
    for page, line in _lines(version):
        starts.append(len(text))
        pages.append(page)
        text += line.replace("’", "'") + " "  # as _norm does the quote
    return text, starts, pages


def quote_pages(version: str, quote: str) -> list[tuple[int, int]]:
    """(start page, end page) of every occurrence of `quote` in the spec
    text (whitespace and hyphenation at line ends normalized)."""
    text, starts, pages = _spec(version)
    pat = re.compile(r"\s+".join(re.escape(w) for w in _norm(quote).split()))
    out = []
    for m in pat.finditer(text):
        a = bisect.bisect_right(starts, m.start()) - 1
        b = bisect.bisect_right(starts, m.end() - 1) - 1
        out.append((pages[a], pages[b]))
    return out


def check(entry: Entry, md: str | None = None) -> list[str]:
    """Problems of one entry: its rulings.md text missing, a quote not in
    the spec, a cited page that does not hold it (the quote must start on
    the cited page or the page after: an item is cited where it starts)."""
    errs = []
    if not in_rulings_md(entry.rulings_md, md):
        errs.append(f"{entry.id}: rulings_md text not in rulings.md")
    for c in entry.citations:
        found = quote_pages(str(c["version"]), c["quote"])
        if not found:
            errs.append(f"{entry.id}: quote not in the {c['version']} text")
        elif not any(a - 1 <= int(c["page"]) <= b for a, b in found):
            errs.append(f"{entry.id}: quote is on p.{found} not "
                        f"p.{c['page']}")
    return errs


def _requires(text: str) -> set[str]:
    out = set()
    for m in re.finditer(r"^\s*(?:!\$omp|#\s*pragma\s+omp)\s+requires\s+(.*)$",
                         text, re.I | re.M):
        out |= set(re.findall(r"[a-z_]+", m.group(1).lower()))
    return out


def matching(program_id: str, text: str = "", needs=(), reason: str = "",
             kinds=None) -> list[Entry]:
    """The entries whose `applies` matches: a program id pattern, a
    program marker (needs), a requirement clause in the text, or a reason
    pattern. An entry with an empty `applies` is cited by rules only."""
    out = []
    req = _requires(text) if text else set()
    for e in entries().values():
        if kinds and e.kind not in kinds:
            continue
        a = e.applies
        hit = any(fnmatchcase(program_id, p) for p in a.get("programs", ())) \
            or bool(set(a.get("needs", ())) & set(needs)) \
            or bool(set(a.get("requires", ())) & req) \
            or any(re.search(p, reason or "") for p in a.get("reasons", ()))
        if hit:
            out.append(e)
    return out
