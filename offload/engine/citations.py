"""Check every spec citation in the findings, vendor drafts and rulings against
the spec text (results/spec_cache/). A citation is a section sign with an
optional version before it and optional printed page and margin lines after::

    5.2 §17.2 p.340 l.21-30      OpenACC 3.4 §2.12 p.77      p.205-206

A citation without a version takes the last version named before it in the
same file. It has a quote when a quoted string ends just before it or follows
it after a colon (in Markdown, a ``>`` block quote below it). ``check`` reads
the printed page from the page footers (offload.engine.dataenv_rules.numbered) and
gives a status: ``ok``, ``wrong_page``, ``wrong_lines``, ``wrong_section``,
``quote_not_found``, ``unparseable``, ``skipped`` or ``external`` (an entry of
catalog/citation_allowlist.yaml). Quotes are compared ignoring white space,
hyphens, quote styles, Markdown marks and case.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
ALLOWLIST = ROOT / "catalog" / "citation_allowlist.yaml"

OMP_VERSIONS = ("4.5", "5.0", "5.1", "5.2", "6.0")
ACC_VERSIONS = ("3.4",)

_VERS = r"(?<![§\d.])(?:(?P<name>OpenMP|OpenACC)\s+)?(?P<ver>\d+\.\d+)"
_NUM = r"\d+(?:\s?[-–]\s?\d+)?"
CITE = re.compile(
    r"(?:" + _VERS + r"\s*,?\s*)?§\s?(?P<sec>(?:[A-Z]|\d+)(?:\.\d+)*)"
    r"(?P<tail>(?:\s*,?\s*(?:pp?\.\s?" + _NUM + r"|l\.\s?" + _NUM + r"))*)")
_TAIL = re.compile(r"(pp?|l)\.\s?(\d+)(?:\s?[-–]\s?(\d+))?")
_MENTION = re.compile(r"\b(OpenMP|OpenACC)\s+(\d+\.\d+)\b")
_LEADERS = {
    ".f90": re.compile(r"^\s*!+\s?"), ".F90": re.compile(r"^\s*!+\s?"),
    ".f": re.compile(r"^(?:[cC!*]|\s*!)\s?"),
    ".c": re.compile(r"^\s*(?:/\*+|\*+(?!/)|//+)\s?"),
    ".h": re.compile(r"^\s*(?:/\*+|\*+(?!/)|//+)\s?"),
    ".cpp": re.compile(r"^\s*(?:/\*+|\*+(?!/)|//+)\s?"),
    ".yaml": re.compile(r"^\s*#+\s?"), ".yml": re.compile(r"^\s*#+\s?"),
}
STATUSES = ("ok", "wrong_page", "wrong_lines", "wrong_section",
            "quote_not_found", "unparseable", "external", "skipped")


@dataclass
class Citation:
    path: str
    line: int
    text: str
    version: str | None          # "OpenMP 5.2", "OpenACC 3.4"
    section: str
    pages: list = field(default_factory=list)   # [(lo, hi)]
    lines: str | None = None     # "21-30"
    quote: str | None = None
    external: str | None = None  # the allowlist reason
    raw_version: str | None = None
    skipped: str | None = None   # why it is listed but not checked


@dataclass
class Result:
    cite: Citation
    status: str
    detail: str = ""

    def line(self) -> str:
        c = self.cite
        q = f' "{c.quote[:60]}..."' if c.quote else ""
        return (f"{c.path}:{c.line}: {self.status}: {c.text}"
                f" [{c.version or c.raw_version or '?'}]{q}"
                + (f" -- {self.detail}" if self.detail else ""))


# --- the allowlist -------------------------------------------------------------------

def load_allowlist(path: Path | None = None) -> list[dict]:
    p = path or ALLOWLIST
    if not p.is_file():
        return []
    return list(yaml.safe_load(p.read_text())["external"])


# --- parsing -------------------------------------------------------------------------

def _flatten(text: str, path: str) -> tuple[str, list[int]]:
    """The text with comment leaders removed from every line (lines joined
    by newlines) and the offset where each line starts."""
    lead = _LEADERS.get(Path(path).suffix)
    out, starts, pos = [], [], 0
    for ln in text.split("\n"):
        if lead:
            ln = lead.sub("", ln, count=1)
            ln = re.sub(r"\*/\s*$", "", ln)
        ln = ln.strip()
        starts.append(pos)
        out.append(ln)
        pos += len(ln) + 1
    return "\n".join(out), starts


def _version_of(name: str | None, ver: str | None) -> str | None:
    if ver is None:
        return None
    if name == "OpenACC" or (name is None and ver in ACC_VERSIONS):
        return f"OpenACC {ver}" if ver in ACC_VERSIONS else None
    if ver in OMP_VERSIONS:
        return f"OpenMP {ver}"
    return None


def _quote_before(flat: str, start: int) -> str | None:
    """A quoted string that ends just before a citation group:
    ``"..." (5.2 §``, ``"...", 5.2 §``."""
    m = re.search(r"([\"”])\\?\s*,?\s*\(?\s*$", flat[:start])
    if not m:
        return None
    end = m.start(1)
    opener = "“" if m.group(1) == "”" else '"'
    i = flat.rfind(opener, 0, end)
    if i < 0:
        return None
    q = flat[i + 1:end].rstrip("\\")
    return q if q.strip() else None


def _quote_after(flat: str, end: int, md: bool) -> str | None:
    """A quoted string right after a citation (``p.248 "If ..."``,
    ``p.230 l.12-13: "When ..."``) or, in Markdown, a block quote after a
    colon."""
    m = re.match(r"\s*(:?)\s*", flat[end:])
    i = end + m.end()
    if i < len(flat) and flat[i] in "\"“":
        close = "”" if flat[i] == "“" else '"'
        j = flat.find(close, i + 1)
        while j > 0 and flat[j - 1] == "\\" and close == '"':
            j = flat.find(close, j + 1)
        if j > i:
            return flat[i + 1:j]
    if md and m.group(1) and flat.startswith(">", i):
        body = []
        for ln in flat[i:].split("\n"):
            if not ln.startswith(">"):
                break
            body.append(ln[1:].strip())
        return " ".join(body).strip() or None
    return None


def _groups(tail: str) -> list[tuple[tuple[int, int] | None, str | None]]:
    """(page span, lines) groups of a citation's tail: "p.152, p.156" is
    two groups, "p.340 l.21-30" one, "l.1374" one without a page."""
    out: list = []
    for kind, a, b in _TAIL.findall(tail):
        if kind.startswith("p"):
            out.append([(int(a), int(b or a)), None])
        elif out and out[-1][1] is None:
            out[-1][1] = f"{a}-{b}" if b else a
        else:
            out.append([None, f"{a}-{b}" if b else a])
    return [tuple(g) for g in out] or [(None, None)]


NAMED = re.compile(r"(?i)\b(?:appendix|glossary)(?:\s+[A-Z](?:\.\d+)*)?"
                   r"\s*,?\s*pp?\.\s?\d+(?:\s?[-–]\s?\d+)?"
                   r"(?:\s*,?\s*l\.\s?\d+(?:\s?[-–]\s?\d+)?"
                   r"(?:\s*,\s*\d+(?:[-–]\d+)?)*)?")
BARE = re.compile(r"(?<![\w.§])p\.\s?\d+(?:\s?[-–]\s?\d+)?"
                  r"(?:\s*,?\s*l\.\s?" + _NUM + r")?")


def extract(text: str, path: str, allow: list | None = None,
            base_line: int = 0, version: str | None = None) -> list[Citation]:
    """The citations of one file's text. Besides the section citations, a
    bare page citation with a quote (``p.153: "If a single ..."``, ``"..."
    (p.155 l.19-21)``) is checked for the quote (it names no section)."""
    allow = load_allowlist() if allow is None else allow
    flat, starts = _flatten(text, path)
    md = path.endswith(".md")
    mentions = [(m.start(), _version_of(m.group(1), m.group(2)))
                for m in _MENTION.finditer(flat)]
    ext_mentions = sorted((m.start(), a["reason"]) for a in allow
                          for m in re.finditer(a["match"], flat))
    cites = list(CITE.finditer(flat))
    spans = [(m.start(), m.end()) for m in cites]
    # An appendix or glossary reference by
    # page ("Appendix B.1 p.625", "glossary p.159 l.5792") names no section
    # number the checker reads: listed as skipped, never silently dropped
    named = list(NAMED.finditer(flat))
    spans += [(m.start(), m.end()) for m in named]
    # a bare page inside quotes ("p.153" as a word) is not a citation
    bare = [m for m in BARE.finditer(flat)
            if not any(a <= m.start() < b for a, b in spans)
            and flat[m.start() - 1:m.start()] not in ('"', "“")
            and flat[m.end():m.end() + 1] not in ('"', "”")]
    found = sorted([(m.start(), "cite", m) for m in cites] +
                   [(m.start(), "bare", m) for m in bare] +
                   [(m.start(), "named", m) for m in named],
                   key=lambda t: t[0])
    out = []
    last_group_end = -1
    current, spec_pos = version, -1
    mi = 0
    for _, kind, m in found:
        while mi < len(mentions) and mentions[mi][0] < m.start():
            if mentions[mi][1]:
                current, spec_pos = mentions[mi][1], mentions[mi][0]
            mi += 1
        if kind == "cite":
            raw = (f"{m.group('name') + ' ' if m.group('name') else ''}"
                   f"{m.group('ver')}") if m.group("ver") else None
            v = _version_of(m.group("name"), m.group("ver")) if raw else None
        else:
            raw = v = None
        ext = None
        if v:
            current, spec_pos = v, m.start()
        else:
            # an external text named more recently than any spec version
            # (and not long before) is what an unversioned citation cites
            near = [(p, r) for p, r in ext_mentions
                    if spec_pos < p < m.start() and m.start() - p <= 400]
            if near:
                ext = near[-1][1]
            elif not raw:
                v = current
        lineno = _lineno(starts, m.start()) + base_line
        # the first citation of a parenthesis takes a quote before it
        between = flat[last_group_end:m.start()] if last_group_end >= 0 \
            else "x"
        first_in_group = not re.fullmatch(r"\s*[;,]\s*(?:and\s+)?", between)
        q = _quote_after(flat, m.end(), md)
        if q is None and first_in_group:
            q = _quote_before(flat, m.start())
        last_group_end = m.end()
        text_ = flat[m.start():m.end()].replace("\n", " ").strip()
        if kind == "named":
            # with a quote, the quote is checked on the page and lines, as
            # for a bare page; without one it is listed as skipped
            (pages, lines), = _groups(text_)[:1]
            out.append(Citation(
                path=path, line=lineno, text=text_, version=v, section="",
                pages=[pages] if pages else [], lines=lines,
                quote=_clean(q) if q else None, external=ext,
                skipped=None if q else "an appendix or glossary reference "
                "by page (no section number): not checked"))
            continue
        if kind == "bare":
            (pages, lines), = _groups(text_)
            out.append(Citation(
                path=path, line=lineno, text=text_, version=v,
                section="", pages=[pages], lines=lines,
                quote=_clean(q) if q else None, external=ext,
                skipped=None if q else "a bare page without a quote "
                "names no section: not checked"))
            continue
        for k, (pages, lines) in enumerate(_groups(m.group("tail"))):
            out.append(Citation(
                path=path, line=lineno, text=text_, version=v,
                section=m.group("sec"), pages=[pages] if pages else [],
                lines=lines, quote=_clean(q) if (q and k == 0) else None,
                external=ext, raw_version=raw))
    return out


def _clean(q: str) -> str:
    q = q.replace("\\", "")
    q = re.sub(r"\s+", " ", q).strip()
    return q


def _lineno(starts: list[int], pos: int) -> int:
    lo, hi = 0, len(starts) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if starts[mid] <= pos:
            lo = mid
        else:
            hi = mid - 1
    return lo + 1


def extract_rulings_yaml(text: str, path: str,
                         allow: list | None = None) -> list[Citation]:
    """catalog/rulings.yaml: each ruling's rulings_md sentence and its
    structured ``citations`` ({version, section, page, lines?, quote})."""
    allow = load_allowlist() if allow is None else allow
    data = yaml.safe_load(text) or {}
    raw_lines = text.split("\n")
    out = []
    for r in data.get("rulings", []):
        rid = str(r.get("id", ""))
        ln = next((i + 1 for i, s in enumerate(raw_lines)
                   if re.search(r"\bid:\s*" + re.escape(rid) + r"\s*$", s)), 0)
        if r.get("rulings_md"):
            out += extract(str(r["rulings_md"]), path + ".md", allow,
                           base_line=ln - 1)
        for c in r.get("citations") or []:
            ver = str(c.get("version", ""))
            name = "OpenACC" if ver.startswith("acc") else None
            v = _version_of(name, ver.removeprefix("acc"))
            page = c.get("page")
            out.append(Citation(
                path=path, line=ln, text=f"{ver} §{c.get('section')} "
                f"p.{page}" + (f" l.{c['lines']}" if c.get("lines") else ""),
                version=v, section=str(c.get("section")),
                pages=[(int(page), int(page))] if page else [],
                lines=str(c["lines"]) if c.get("lines") else None,
                quote=_clean(c["quote"]) if c.get("quote") else None,
                raw_version=ver))
    for c in out:
        c.path = path
    return out


# --- checking ------------------------------------------------------------------------

def _squash(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"') \
        .replace("”", '"').replace("ﬁ", "fi").replace("ﬂ", "fl")
    s = re.sub(r"[`*_\"']", "", s)
    return re.sub(r"[\s\-‐-―]+", "", s).lower()


_APPENDIX = re.compile(r"^([A-Z](?:\.\d+)+)\s+[A-Z]")


@lru_cache(maxsize=None)
def _rows(version: str) -> tuple:
    """offload.engine.dataenv_rules.numbered, with the appendix sections
    ("B.4 Version 4.5 to 5.0 Differences") that its numeric headings do
    not track: an appendix heading names the section of the rows after it
    until the next numbered heading."""
    from offload.engine.dataenv_rules import numbered
    out, over, prev = [], None, None
    for p, n, t, s in numbered(version):
        if s != prev:
            over = None
        prev = s
        m = _APPENDIX.match(t)
        if m and ". . ." not in t:
            over = m.group(1)
        out.append((p, n, t, over or s))
    return tuple(out)


@lru_cache(maxsize=None)
def _big(version: str) -> tuple[str, tuple]:
    """The version's squashed text and the start offset of each row."""
    parts, starts, pos = [], [], 0
    for r in _rows(version):
        s = _squash(r[2])
        starts.append(pos)
        parts.append(s)
        pos += len(s)
    return "".join(parts), tuple(starts)


def _row_at(starts: tuple, pos: int) -> int:
    return _lineno(list(starts), pos) - 1


def _pieces(quote: str) -> list[str]:
    parts = re.split(r"\.\s?\.\s?\.|…|\[[^\]]*\]", quote)
    return [p for p in (_squash(x) for x in parts) if p]


def _matches(version: str, quote: str) -> list[tuple[int, int]]:
    """(first row, last row) of every place the quote's pieces occur in
    order (each next piece within 4000 characters)."""
    big, starts = _big(version)
    ps = _pieces(quote)
    if not ps:
        return []
    out = []
    i = big.find(ps[0])
    while i >= 0:
        end, ok = i + len(ps[0]), True
        for p in ps[1:]:
            j = big.find(p, end, end + 4000)
            if j < 0:
                ok = False
                break
            end = j + len(p)
        if ok:
            out.append((_row_at(starts, i), _row_at(starts, end - 1)))
        i = big.find(ps[0], i + 1)
    return out


def _in_sec(row_sec: str, sec: str) -> bool:
    return not sec or row_sec == sec or row_sec.startswith(sec + ".")


def _span(lines: str) -> tuple[int, int]:
    a, _, b = lines.partition("-")
    return int(a), int(b or a)


def _where(rows, a: int, b: int) -> str:
    ra, rb = rows[a], rows[b]
    if ra[0] == rb[0]:
        ln = f"{ra[1]}" if ra[1] == rb[1] else f"{ra[1]}-{rb[1]}"
        return f"p.{ra[0]} l.{ln}"
    return f"p.{ra[0]} l.{ra[1]}-p.{rb[0]} l.{rb[1]}"


def _sec_pages(rows, sec: str) -> str:
    ps = sorted({r[0] for r in rows if _in_sec(r[3], sec)})
    if not ps:
        return "nowhere"
    return f"p.{ps[0]}" if len(ps) == 1 else f"p.{ps[0]}-{ps[-1]}"


def _cited_rows(rows, c: Citation, acc: bool) -> list[int]:
    """Indices of the rows the citation's page(s) and lines name."""
    lo = hi = None
    if c.lines:
        lo, hi = _span(c.lines)
    idx = []
    for i, r in enumerate(rows):
        if c.pages and not any(a <= r[0] <= b for a, b in c.pages):
            continue
        if lo is not None and not lo <= r[1] <= hi:
            continue
        idx.append(i)
    return idx


def check(c: Citation) -> Result:
    if c.external:
        return Result(c, "external", c.external)
    if c.skipped:
        return Result(c, "skipped", c.skipped)
    if not c.version:
        why = f"unknown version {c.raw_version}" if c.raw_version else \
            "no version named before it"
        return Result(c, "unparseable", why)
    acc = c.version.startswith("OpenACC")
    if c.lines and not c.pages and not acc:
        return Result(c, "unparseable", "OpenMP lines without a page")
    rows = _rows(c.version)
    if c.section and not any(_in_sec(r[3], c.section) for r in rows):
        return Result(c, "wrong_section", f"{c.version} has no §{c.section}")
    cited = _cited_rows(rows, c, acc) if (c.pages or c.lines) else []
    if (c.pages or c.lines) and not cited:
        return Result(c, "wrong_page", f"no such page/lines; §{c.section} is "
                      f"at {_sec_pages(rows, c.section)}")
    if c.quote:
        ms = _matches(c.version, c.quote)
        if not ms:
            return Result(c, "quote_not_found",
                          f"not in {c.version}")
        cset = set(cited)
        for a, b in ms:
            if not cited:
                inside = all(_in_sec(rows[k][3], c.section)
                             for k in (a, b))
                if inside:
                    return Result(c, "ok")
                continue
            # with a page only (no lines), the quote must start on it
            if (a in cset and b in cset) or (not c.lines and a in cset):
                secs = {rows[k][3] for k in range(a, b + 1)}
                if any(_in_sec(s, c.section) for s in secs):
                    return Result(c, "ok")
                return Result(c, "wrong_section",
                              f"the quote is in §{sorted(secs)[0]}")
        # not at the cited place: say where it is
        best = sorted(ms, key=lambda ab: (
            not _in_sec(rows[ab[0]][3], c.section),
            not (c.pages and any(p0 <= rows[ab[0]][0] <= p1
                                 for p0, p1 in c.pages))))[0]
        a, b = best
        where = _where(rows, a, b)
        if not _in_sec(rows[a][3], c.section):
            return Result(c, "wrong_section",
                          f"the quote is in §{rows[a][3]} {where}")
        if c.pages and any(p0 <= rows[a][0] <= p1 for p0, p1 in c.pages):
            return Result(c, "wrong_lines", f"the quote is at {where}")
        return Result(c, "wrong_page", f"the quote is at {where}")
    if not cited:
        return Result(c, "ok")
    secs = {rows[k][3] for k in cited}
    if any(_in_sec(s, c.section) for s in secs):
        return Result(c, "ok")
    pages = {rows[k][0] for k in cited}
    on_page = [r for r in rows if r[0] in pages and _in_sec(r[3], c.section)]
    if on_page and c.lines:
        return Result(c, "wrong_lines", f"the cited lines are in "
                      f"§{sorted(secs)[0]}; §{c.section} on this page: "
                      f"l.{on_page[0][1]}-{on_page[-1][1]}")
    return Result(c, "wrong_page", f"the cited page is in "
                  f"§{', §'.join(sorted(secs))}; §{c.section} is at "
                  f"{_sec_pages(rows, c.section)}")


# --- the tree ------------------------------------------------------------------------

TEXT_SUFFIXES = {".f90", ".F90", ".f", ".c", ".h", ".cpp", ".md", ".yaml",
                 ".yml", ".txt"}


def default_paths(root: Path = ROOT) -> list[Path]:
    paths = [p for p in sorted((root / "data" / "findings").rglob("*"))
             if p.is_file() and p.suffix in TEXT_SUFFIXES]
    paths += sorted((root / "data" / "vendor").rglob("*.md"))
    paths += [root / "catalog" / "rulings.yaml",
              root / "data" / "reports" / "rulings.md"]
    return paths


def extract_file(p: Path, root: Path = ROOT,
                 allow: list | None = None) -> list[Citation]:
    rel = str(p.relative_to(root)) if p.is_absolute() else str(p)
    text = p.read_text(encoding="utf-8", errors="replace")
    if p.name == "rulings.yaml":
        return extract_rulings_yaml(text, rel, allow)
    return extract(text, rel, allow)


def scan(paths: list[Path] | None = None, root: Path = ROOT) -> list[Result]:
    allow = load_allowlist()
    out = []
    for p in paths or default_paths(root):
        for c in extract_file(p, root, allow):
            out.append(check(c))
    return out
