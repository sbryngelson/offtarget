"""The data-environment rule table (catalog/dataenv_rules.yaml).

One row per data-sharing, mapping or residency rule of OpenMP 5.0, 5.2 and
6.0 and OpenACC 3.4. ``load`` reads it for the program generator
(offload.engine.dataenv_gen).

A row has ``id``, ``model``, ``versions``, ``spec`` (citations with version,
section, printed page, margin lines and a verbatim quote, verified by
``check_citation`` against results/spec_cache/), ``subject``, the axes
(``construct``, ``variable_kind``, ``attribute``, ``clauses_present``,
``memory_mode``; see ``AXES``), ``expected`` (``dsa``, ``map_type``,
``copy_back``, ``source``, optional ``residency``), ``observable`` and
``template`` (a key of offload.engine.dataenv_gen.TEMPLATES). No row names a
compiler or a measured result. Memory modes: ``copy``, ``unified``, ``any``.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

from offload.engine.root import ROOT  # noqa: E402
TABLE = ROOT / "catalog" / "dataenv_rules.yaml"

MODELS = ("omp", "acc")
VERSIONS = {"omp": ("5.0", "5.2", "6.0"), "acc": ("3.4",)}
CITE_NAMES = {"5.0": "OpenMP 5.0", "5.2": "OpenMP 5.2", "6.0": "OpenMP 6.0",
              "3.4": "OpenACC 3.4"}

# 40d's Binding vocabularies, plus "n/a" where the rule decides no such attribute
DSA = ("shared", "private", "firstprivate", "lastprivate", "reduction",
       "linear", "n/a")
MAP_TYPE = ("to", "from", "tofrom", "alloc", "none", "present", "n/a")
SOURCE = ("explicit", "implicit", "defaultmap", "declare_target",
          "enclosing_data", "enter_data")
RESIDENCY = ("host_only", "device_copy", "unified", "declare_target")
COPY_BACK = ("yes", "no", "n/a")
MEMORY_MODES = ("copy", "unified")

AXES = {
    "construct": (
        # OpenMP
        "target", "target parallel do", "target teams distribute",
        "target teams distribute parallel do",
        "target teams distribute parallel do simd",
        "target teams distribute simd", "target teams loop",
        "target parallel loop", "target simd", "target parallel",
        "target teams", "target data",
        "target enter data", "target exit data", "target update",
        "declare target",
        # OpenACC
        "parallel", "serial", "kernels", "parallel loop", "data",
        "enter data", "exit data", "declare", "routine", "update"),
    "variable_kind": ("scalar", "array", "derived_type", "c_pointer"),
    # declare_target_link: in a link clause; device_procedure: referenced in
    # a device procedure (declare target or acc routine) called in the
    # region; enclosing_data / enter_data: present from an enclosing data
    # construct / an enter data directive when the construct is reached
    "attribute": ("none", "target", "declare_target", "declare_target_link",
                  "module", "common", "allocatable", "pointer", "component",
                  "value_argument", "declare_create", "declare_copyin",
                  "device_procedure", "enclosing_data", "enter_data",
                  "loop_variable",
                  # Present from two live enter data
                  # (reference count two), so the two exit-data rows do not
                  # share their axes
                  "enter_data_twice"),
    "memory_mode": ("any", "copy", "unified"),
}

# names that must never appear in a rule row: the table states the spec's
# rule, never a compiler's behaviour or a measured result
COMPILER_WORDS = re.compile(
    r"(?i)\b(afar|amdflang|amdclang|flang|clang|cce|cray|craycc|ftn|nvhpc|"
    r"nvfortran|nvc|pgi|gfortran|gcc|ifx|ifort|icx|xlf|llvm|rocm|"
    r"wrong[_ ]answer|compiler[_ ]bug|finding)\b")


def load(path: Path | None = None) -> list[dict]:
    """The rows of the rule table."""
    data = yaml.safe_load((path or TABLE).read_text())
    return list(data["rules"])


def by_id(path: Path | None = None) -> dict:
    return {r["id"]: r for r in load(path)}


def _norm(clause: str) -> str:
    return re.sub(r"\s+", "", clause).lower()


def lookup(rules: list[dict], model: str, version: str, construct: str,
           variable_kind: str, attributes=(), clauses=(),
           memory_mode: str = "copy") -> list[dict]:
    """The rows that decide a variable of `variable_kind` with
    `attributes` (AXES["attribute"] words) referenced in `construct` with
    `clauses` (clause words spelled as the rows spell them; white space and
    case are ignored), most specific first. A row matches when the model,
    version, construct and variable kind are the query's, every attribute
    of the row (``none`` aside) is among `attributes`, every clause of the
    row among `clauses`, and its memory mode is ``any`` or `memory_mode`.
    More matched clauses, then more matched attributes, rank first: the
    first row is the rule that decides (an implicit rule's row also
    matches a query with clauses, below the clause's own row)."""
    attrs = set(attributes) - {"none"}
    cl = {_norm(c) for c in clauses}
    out = []
    for r in rules:
        if r["model"] != model or version not in r["versions"]:
            continue
        if r["construct"] != construct or \
                r["variable_kind"] != variable_kind:
            continue
        if not set(r["attribute"]) - {"none"} <= attrs:
            continue
        if not {_norm(c) for c in r["clauses_present"]} <= cl:
            continue
        if r["memory_mode"] not in ("any", memory_mode):
            continue
        out.append(r)
    out.sort(key=lambda r: (-len(r["clauses_present"]),
                            -len(set(r["attribute"]) - {"none"})))
    return out


# --- the spec text with margin line numbers -----------------------------------------

# a chapter heading: "5 Data Environment" (OpenMP, offload.engine.spec_text's
# form), "6. Glossary" (OpenACC: a short title without punctuation, so a
# numbered list item "3. If the original ..., then the" is not one)
_ACC_CHAPTER = re.compile(r"^(\d)\.\s+((?:[A-Z][A-Za-z]*)(?: [A-Za-z]+){0,5})$")


def _model(version: str) -> str:
    """'OpenMP 5.2' -> '5.2', 'OpenACC 3.4' -> 'acc3.4' (spec_text's
    version strings)."""
    name, num = version.split()
    return ("acc" + num) if name == "OpenACC" else num


@lru_cache(maxsize=None)
def numbered(version: str) -> tuple:
    """(printed page, margin line number, text, section number) of every
    numbered body line of a spec version ("OpenMP 5.2"). The printed page
    is read from the page's footer as offload.engine.spec_text does (the text
    above a footer is on that footer's page)."""
    from offload.engine import spec_text as st
    v = _model(version)
    acc = v.startswith("acc")
    margin = re.compile(r"^\s*(\d{1,4})(?:\s+|$)" if acc else
                        r"^ ?(\d{1,2})(?:\s+|$)")
    out = []
    section = ""
    chapter = 0
    for idx, page in enumerate(st._text(v).split("\f"), start=1):
        raw = page.rstrip().split("\n")
        if acc:
            raw = [ln for ln in raw if not st._ACC_HEADER.match(ln)] or [""]
        foot = len(raw) - 1 if st._FOOT3.match(raw[-1]) else None
        printed = idx
        for j in range(len(raw) - 1, -1, -1):
            m = st._FOOT1.match(raw[j]) or st._FOOT2.match(raw[j]) or (
                st._FOOT3.match(raw[j]) if j == foot else None)
            if m:
                printed = int(m.group(1))
                break
        for j, ln in enumerate(raw):
            if st._FOOT1.match(ln) or st._FOOT2.match(ln) or j == foot:
                continue
            m = margin.match(ln)
            if not m:
                continue
            text = ln[m.end():].strip()
            h = st._HEADING.match(text)
            c = (_ACC_CHAPTER if acc else st._CHAPTER).match(text)
            if h and ". . ." not in text and not text.endswith(","):
                section = h.group(1)
            elif c and int(c.group(1)) == chapter + 1:
                chapter += 1
                section = c.group(1)
            out.append((printed, int(m.group(1)), text, section))
    return tuple(out)


def _squash(s: str) -> str:
    """Text without white space, hyphens, dashes and quote styles (line
    breaks split words with a hyphen; pdftotext keeps typographic
    quotes)."""
    s = s.replace("’", "'").replace("‘", "'")
    s = s.replace("“", '"').replace("”", '"')
    s = s.replace("ﬁ", "fi").replace("ﬂ", "fl")
    return re.sub(r"[\s\-‐-―]+", "", s)


def _span(lines: str) -> tuple[int, int]:
    a, _, b = str(lines).partition("-")
    return int(a), int(b or a)


def text_at(version: str, page: int, lines: str) -> str:
    """The text of margin lines `lines` on printed page `page`."""
    lo, hi = _span(lines)
    return " ".join(t for p, n, t, _ in numbered(version)
                    if p == page and lo <= n <= hi)


def check_citation(c: dict) -> list[str]:
    """Problems with one citation (empty: it checks): the version is
    known, the quote is in the cited lines of the cited printed page, and
    the cited section is the one those lines are in."""
    probs = []
    for k in ("version", "section", "page", "lines", "quote"):
        if not c.get(k):
            probs.append(f"no {k}")
    if probs:
        return probs
    if c["version"] not in CITE_NAMES.values():
        return [f"unknown version {c['version']}"]
    lo, hi = _span(c["lines"])
    rows = [r for r in numbered(c["version"])
            if r[0] == int(c["page"]) and lo <= r[1] <= hi]
    if not rows:
        return [f"{c['version']} p.{c['page']} has no lines {c['lines']}"]
    if len(_squash(c["quote"])) < 20:
        probs.append("quote shorter than 20 characters")
    joined = _squash(" ".join(r[2] for r in rows))
    if _squash(c["quote"]) not in joined:
        probs.append(f"quote not in {c['version']} p.{c['page']} "
                     f"l.{c['lines']}")
    secs = {r[3] for r in rows}
    if str(c["section"]) not in secs:
        probs.append(f"lines are in section(s) {sorted(secs)}, not "
                     f"{c['section']}")
    return probs


def locate(version: str, quote: str) -> list[dict]:
    """Every place a quote occurs (within at most four consecutive lines
    of one page): {version, section, page, lines, quote}."""
    rows = numbered(version)
    want = _squash(quote)
    out = []
    for i in range(len(rows)):
        for k in range(1, 5):
            grp = rows[i:i + k]
            if len({r[0] for r in grp}) > 1:
                break
            if want in _squash(" ".join(r[2] for r in grp)):
                first, last = grp[0], grp[-1]
                # the narrowest span: drop leading lines not needed
                out.append({"version": version, "section": first[3],
                            "page": first[0],
                            "lines": f"{first[1]}-{last[1]}"
                            if last[1] != first[1] else str(first[1]),
                            "quote": quote})
                break
    # a quote found from line i is also found from earlier lines i-1..; keep
    # the narrowest
    best = {}
    for c in out:
        lo, hi = _span(c["lines"])
        key = (c["page"], hi)
        if key not in best or _span(best[key]["lines"])[0] < lo:
            best[key] = c
    return list(best.values())


def cite_string(c: dict) -> str:
    return (f"{c['version']} §{c['section']} p.{c['page']} l.{c['lines']}: "
            f"\"{c['quote']}\"")


def citations_for(rule: dict) -> list[str]:
    """40d's ``version_rule``: the citation strings of a row."""
    return [cite_string(c) for c in rule["spec"]]
