"""Inventory of the spec's normative restriction sentences for the slice.

``extract(version)`` collects candidate restriction sentences from the page-tagged
spec text (``offload.engine.spec_text``) for the sections in ``SCOPE``. In mode
``restrictions`` it takes each bullet or paragraph of a section's Restrictions
subsections. In mode ``text`` (sections read whole: region nesting, combined
construct names and clauses, canonical loop nest form, data-sharing rules) it
takes every sentence containing one of ``KEYWORDS``. Each candidate is classified
by hand in catalog/omp/rules_coverage.yaml (``CLASSES``);
tools/derive/rules_coverage.py renders data/reports/rules-coverage.md
from it. A test checks that the YAML classifies exactly the extracted sentences.
Scope tags: ``slice`` (a construct, clause or composition rule of the slice) and
``used`` (a construct outside the slice that generated programs use: single,
task, taskwait, taskgroup, ordered, scan, declare simd, declare mapper, depobj,
threadprivate, error)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from offload.engine import spec_text

ROOT = Path(__file__).resolve().parent.parent.parent
COVERAGE_PATH = ROOT / "catalog" / "omp" / "rules_coverage.yaml"

# classification of a sentence
CLASSES = {
    "covered": "already covered: by a rule (rule: <stem>) or by the "
               "grammar layer (rule: grammar)",
    "static": "static-checkable, encoded as a new rule (rule: <stem>)",
    "deferred": "static-checkable, not encoded (why: the reason)",
    "runtime": "not decidable from the source",
    "out_of_slice": "about a construct, clause, form or language outside "
                    "the slice",
    "informative": "not a restriction on programs (semantics, a "
                   "definition, an implementation requirement, an "
                   "unspecified-behaviour statement)",
}

# (section number, mode, scope) per version
SCOPE = {
    "5.2": [
        ("3.1", "restrictions", "slice"), ("3.2", "restrictions", "slice"),
        ("3.2.1", "restrictions", "slice"),
        ("3.2.5", "restrictions", "slice"), ("3.4", "restrictions", "slice"),
        ("4.3", "restrictions", "slice"),
        ("4.4.1", "text", "slice"), ("4.4.3", "restrictions", "slice"),
        ("4.4.4", "restrictions", "slice"),
        ("5.1.1", "text", "slice"),
        ("5.2", "restrictions", "used"),
        ("5.3", "restrictions", "slice"),
        ("5.4", "restrictions", "slice"),
        ("5.4.1", "restrictions", "slice"), ("5.4.2", "restrictions", "slice"),
        ("5.4.3", "restrictions", "slice"), ("5.4.4", "restrictions", "slice"),
        ("5.4.5", "restrictions", "slice"), ("5.4.6", "restrictions", "slice"),
        ("5.4.7", "restrictions", "slice"), ("5.4.8", "restrictions", "slice"),
        ("5.4.9", "restrictions", "slice"),
        ("5.4.10", "restrictions", "slice"),
        ("5.5.5", "restrictions", "slice"),
        ("5.5.8", "restrictions", "slice"),
        ("5.5.10", "restrictions", "slice"),
        ("5.6", "restrictions", "used"),
        ("5.7.1", "restrictions", "slice"),
        ("5.8.3", "restrictions", "slice"), ("5.8.4", "restrictions", "slice"),
        ("5.8.5", "restrictions", "slice"), ("5.8.7", "restrictions", "slice"),
        ("5.8.8", "restrictions", "used"),
        ("5.9", "restrictions", "slice"), ("5.9.1", "restrictions", "slice"),
        ("5.9.2", "restrictions", "slice"),
        ("5.11", "restrictions", "slice"),
        ("6.6", "restrictions", "slice"), ("6.8", "restrictions", "slice"),
        ("7.7", "restrictions", "used"),
        ("7.8", "restrictions", "slice"), ("7.8.1", "restrictions", "slice"),
        ("7.8.3", "restrictions", "slice"),
        ("8.2", "restrictions", "slice"), ("8.2.1", "restrictions", "slice"),
        ("10.1", "restrictions", "slice"),
        ("10.1.2", "restrictions", "slice"),
        ("10.1.4", "restrictions", "slice"),
        ("11", "restrictions", "slice"),
        ("10.2", "restrictions", "slice"),
        ("10.2.1", "restrictions", "slice"),
        ("10.3", "restrictions", "slice"), ("10.4", "restrictions", "slice"),
        ("10.4.1", "restrictions", "slice"),
        ("10.4.2", "restrictions", "slice"),
        ("10.4.3", "restrictions", "slice"),
        ("11.1", "restrictions", "used"),
        ("11.5", "restrictions", "slice"),
        ("11.5.2", "restrictions", "slice"),
        ("11.5.3", "restrictions", "slice"),
        ("11.6", "restrictions", "slice"),
        ("11.6.1", "restrictions", "slice"),
        ("11.7", "restrictions", "slice"),
        ("11.7.1", "restrictions", "slice"),
        ("12.5", "restrictions", "used"),
        ("13.1", "restrictions", "slice"), ("13.2", "restrictions", "slice"),
        ("13.3", "restrictions", "slice"),
        ("13.5", "restrictions", "slice"), ("13.6", "restrictions", "slice"),
        ("13.7", "restrictions", "slice"), ("13.8", "restrictions", "slice"),
        ("13.9", "restrictions", "slice"),
        ("15.4", "restrictions", "used"), ("15.5", "restrictions", "used"),
        ("15.6", "restrictions", "slice"),
        ("15.9.3", "restrictions", "used"),
        ("15.9.4", "restrictions", "used"),
        ("15.9.5", "restrictions", "slice"),
        ("15.10.2", "restrictions", "used"),
        ("17.1", "text", "slice"), ("17.2", "text", "slice"),
        ("17.3", "text", "slice"), ("17.4", "text", "slice"),
        ("17.5", "text", "slice"),
    ],
    "6.0": [
        ("5.1", "restrictions", "slice"), ("5.2", "restrictions", "slice"),
        ("5.2.1", "restrictions", "slice"),
        ("5.2.5", "restrictions", "slice"),
        ("5.4", "restrictions", "slice"), ("5.5", "restrictions", "slice"),
        ("6.3", "restrictions", "slice"),
        ("6.4.1", "text", "slice"), ("6.4.5", "restrictions", "slice"),
        ("6.4.6", "restrictions", "slice"),
        ("7.1.1", "text", "slice"),
        ("7.3", "restrictions", "used"),
        ("7.4", "restrictions", "slice"),
        ("7.5", "restrictions", "slice"),
        ("7.5.1", "restrictions", "slice"), ("7.5.2", "restrictions", "slice"),
        ("7.5.3", "restrictions", "slice"), ("7.5.4", "restrictions", "slice"),
        ("7.5.5", "restrictions", "slice"), ("7.5.6", "restrictions", "slice"),
        ("7.5.7", "restrictions", "slice"), ("7.5.8", "restrictions", "slice"),
        ("7.5.9", "restrictions", "slice"),
        ("7.5.10", "restrictions", "slice"),
        ("7.6.5", "restrictions", "slice"),
        ("7.6.6", "restrictions", "slice"),
        ("7.6.10", "restrictions", "slice"),
        ("7.6.12", "restrictions", "slice"),
        ("7.6.13", "restrictions", "slice"),
        ("7.7", "restrictions", "used"),
        ("7.8.1", "restrictions", "slice"),
        ("7.9.6", "restrictions", "slice"), ("7.9.7", "restrictions", "slice"),
        ("7.9.8", "restrictions", "slice"), ("7.9.9", "restrictions", "slice"),
        ("7.9.10", "restrictions", "used"),
        ("7.10", "restrictions", "slice"), ("7.10.1", "restrictions", "slice"),
        ("7.10.2", "restrictions", "slice"),
        ("7.12", "restrictions", "slice"), ("7.14", "restrictions", "slice"),
        ("8.6", "restrictions", "slice"), ("8.8", "restrictions", "slice"),
        ("9.8", "restrictions", "used"),
        ("9.9", "restrictions", "slice"), ("9.9.1", "restrictions", "slice"),
        ("9.9.3", "restrictions", "slice"),
        ("10.1", "restrictions", "used"),
        ("10.3", "restrictions", "slice"), ("10.4", "restrictions", "slice"),
        ("10.5", "restrictions", "slice"),
        ("10.5.1", "restrictions", "slice"),
        ("10.5.1.1", "restrictions", "slice"),
        ("10.5.1.2", "restrictions", "slice"),
        ("10.5.1.3", "restrictions", "slice"),
        ("10.5.1.4", "restrictions", "slice"),
        ("10.5.1.5", "restrictions", "slice"),
        ("10.5.1.6", "restrictions", "slice"),
        ("10.5.1.7", "restrictions", "slice"),
        ("12.1", "restrictions", "slice"),
        ("12.1.2", "restrictions", "slice"),
        ("12.1.4", "restrictions", "slice"),
        ("12.2", "restrictions", "slice"),
        ("12.2.1", "restrictions", "slice"),
        ("12.3", "restrictions", "slice"), ("12.4", "restrictions", "slice"),
        ("12.4.1", "restrictions", "slice"),
        ("12.4.2", "restrictions", "slice"),
        ("12.4.3", "restrictions", "slice"),
        ("13", "restrictions", "slice"),
        ("13.1", "restrictions", "used"),
        ("13.5", "restrictions", "slice"), ("13.6", "restrictions", "slice"),
        ("13.6.2", "restrictions", "slice"),
        ("13.6.3", "restrictions", "slice"),
        ("13.7", "restrictions", "slice"),
        ("13.7.1", "restrictions", "slice"),
        ("13.8", "restrictions", "slice"),
        ("13.8.1", "restrictions", "slice"),
        ("14.1", "restrictions", "used"),
        ("14.6", "restrictions", "slice"),
        ("15.1", "restrictions", "slice"), ("15.2", "restrictions", "slice"),
        ("15.3", "restrictions", "slice"),
        ("15.5", "restrictions", "slice"), ("15.6", "restrictions", "slice"),
        ("15.7", "restrictions", "slice"), ("15.8", "restrictions", "slice"),
        ("15.9", "restrictions", "slice"),
        ("17.4", "restrictions", "used"), ("17.5", "restrictions", "used"),
        ("17.6", "restrictions", "slice"), ("17.7", "restrictions", "slice"),
        ("17.9.3", "restrictions", "used"),
        ("17.9.4", "restrictions", "used"),
        ("17.9.5", "restrictions", "slice"),
        ("17.9.6", "restrictions", "slice"),
        ("17.10.2", "restrictions", "used"),
        ("19.1", "text", "slice"), ("19.2", "text", "slice"),
        ("19.3", "text", "slice"),
    ],
}

KEYWORDS = re.compile(
    r"\b(?:must|shall|cannot|may not|at most once|at most one|only|"
    r"restricted|not permitted|strictly nested|closely nested|may be|"
    r"required|not allowed)\b", re.I)


# lead-in lines of a Restrictions list ("Restrictions common to ... are as
# follows:", "The following restrictions apply to ...:")
_LEAD_IN = re.compile(r"^(?:Restrictions .*|The (?:following )?restrictions "
                      r".*|Additional restrictions .*)(?:follows|apply to "
                      r".*):$")


@dataclass(frozen=True)
class Item:
    version: str
    section: str
    title: str
    page: int
    language: str
    text: str
    origin: str  # "Restrictions" or "text"
    scope: str

    @property
    def citation(self) -> str:
        return f"OpenMP {self.version} §{self.section}, p.{self.page}"


def _section_lines(version: str, number: str):
    """(title, [(page, line)]) of a numbered section."""
    heads = spec_text._heads(version)
    lines = spec_text._lines(version)
    for k, (i, num, title) in enumerate(heads):
        if num == number:
            end = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
            return title, lines[i + 1:end]
    raise KeyError(f"OpenMP {version}: no section {number}")


_SPLIT = re.compile(r"(?<=[a-z0-9)\]’'\"][.;])\s+(?=[A-Z•(])")


def _units(body, restrictions_only: bool):
    """(pages, language, text, origin) per bullet / paragraph; pages maps
    a character offset of text to the printed page (start offsets)."""
    lang, in_restr, cur, prev_blank = "", False, None, False
    out = []

    def flush():
        nonlocal cur
        if cur:
            lng, parts, origin = cur[1:]
            text, pages = "", []
            for page, part in parts:
                part = re.sub(r"\s+", " ", part).strip()
                if part:
                    pages.append((len(text) + (1 if text else 0), page))
                    text = f"{text} {part}" if text else part
            if text:
                out.append((pages, lng, text, origin))
        cur = None

    for page, ln in body:
        if ln in spec_text._BANNERS:
            flush()
            lang = "" if lang == spec_text._BANNERS[ln] else \
                spec_text._BANNERS[ln]
            continue
        if ln == "Restrictions":
            flush()
            in_restr = True
            continue
        if ln in spec_text._SUBHEADS:
            flush()
            in_restr = False
            continue
        if not ln:
            prev_blank = True
            continue
        if restrictions_only and not in_restr:
            continue
        if re.match(r"^Restrictions to .* are as follows:?$", ln):
            continue
        origin = "Restrictions" if in_restr else "text"
        if ln.startswith("•"):
            flush()
            cur = (page, lang, [(page, ln.lstrip("• ").strip())], origin)
        elif cur is not None and not prev_blank and cur[3] == origin:
            cur[2].append((page, ln))
        else:
            flush()
            cur = (page, lang, [(page, ln)], origin)
        prev_blank = False
    flush()
    return out


def extract(version: str) -> list[Item]:
    items = []
    for number, mode, scope in sorted(
            SCOPE[version], key=lambda e: [int(x) for x in e[0].split(".")]):
        title, body = _section_lines(version, number)
        for pages, lang, text, origin in _units(body,
                                                mode == "restrictions"):
            if _LEAD_IN.match(text):
                continue
            if origin == "Restrictions":
                items.append(Item(version, number, title, pages[0][1], lang,
                                  text, origin, scope))
                continue
            pos = 0
            for sent in _SPLIT.split(text):
                at = text.index(sent, pos)
                pos = at + len(sent)
                if KEYWORDS.search(sent):
                    page = [pg for off, pg in pages if off <= at][-1]
                    items.append(Item(version, number, title, page, lang,
                                      sent.strip(), origin, scope))
    return items


def load_coverage(path: Path = COVERAGE_PATH) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["sentences"]
