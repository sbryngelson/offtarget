"""Vendor claims in one generic format, ingested from vendor documents.

A ``VendorClaim`` is (vendor, product, version, doc source, url, page,
language, construct, clause, claim, quote): what a vendor document says
about one construct or clause for one toolchain. ``claim`` is supported,
unsupported or partial. Vendor, product and the documents (one local
snapshot per toolchain edition) are listed in ``catalog/vendor_claims.yaml``.

The hand mapping from a document's words to catalog atoms is in
catalog/<model>/claims.yaml. ``ingest`` checks every quote against each
edition's snapshot and records the claim only for editions that contain it,
with the section where it was found (``page``). The result is written to
``catalog/vendor_claims_generic.yaml`` (``tools/derive/claims.py ingest``) and
read by offload.engine.report and offload.engine.confirm.rules. ``load`` and
``dump`` read and write that file (a ``claims:`` list)."""
from __future__ import annotations

import csv
import dataclasses
import io
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from offload.engine.root import ROOT  # noqa: E402
PRODUCTS = ROOT / "catalog" / "vendor_claims.yaml"
GENERIC = ROOT / "catalog" / "vendor_claims_generic.yaml"
MAPS = (ROOT / "catalog" / "omp" / "claims.yaml",
        ROOT / "catalog" / "acc" / "claims.yaml")
CLAIMS = ("supported", "unsupported", "partial")
FORMS = ("", "compile_error", "accepted")
REQUIRED = ("vendor", "product", "version", "source", "url", "language",
            "claim", "quote")


@dataclass(frozen=True)
class VendorClaim:
    vendor: str
    product: str
    version: str
    source: str
    url: str
    language: str
    claim: str
    quote: str
    page: str = ""        # where in the document (section; edition)
    construct: str = ""   # a directive or construct name ("target data")
    clause: str = ""      # a clause, with its modifier ("map.to")
    spec_version: str = ""  # the spec version whose feature list the
                            # claim is in ("5.1", "6.0"; "" = not stated)
    toolchain: str = ""   # the project's toolchain the claim is compared to
    atom: str = ""        # the catalog atom (or fnmatch pattern)
    form: str = ""        # compile_error | accepted | "" (report.Claim.form)
    general: bool = False   # release-level: specific claims win
    versions: str = ""    # catalog versions compared ("52,60"; "" = all)
    doc: str = ""         # the local snapshot the quote was checked in
    cross_language: bool = False  # compared with programs of any language
    note: str = ""

    def __post_init__(self):
        for k in REQUIRED:
            if not getattr(self, k):
                raise ValueError(f"vendor claim without {k}: {self}")
        if self.claim not in CLAIMS:
            raise ValueError(f"claim must be one of {CLAIMS}")
        if self.form not in FORMS:
            raise ValueError(f"form must be one of {FORMS}")
        if not (self.construct or self.clause or self.atom):
            raise ValueError("a claim names a construct, a clause or an atom")

    @property
    def version_list(self) -> tuple[int, ...]:
        return tuple(int(v) for v in self.versions.split(",") if v)

    def covers_language(self, lang: str) -> bool:
        """Whether the claim is about programs of ``lang`` (f90 | c)."""
        if self.cross_language:
            return True
        words = self.language.replace("C/C++", "C").replace(",", " ").split()
        return ("C" in words or "C++" in words) if lang == "c" else \
            "Fortran" in words


@lru_cache(maxsize=None)
def _vendor_data() -> dict:
    return yaml.safe_load(PRODUCTS.read_text())


def products() -> dict:
    """toolchain (gfx942 name) -> {vendor, product, version}."""
    return dict(_vendor_data()["products"])


def split_atom(atom: str) -> tuple[str, str]:
    """(construct, clause) of a catalog atom: ``omp.directive.target_data``
    -> ("target data", ""), ``omp.clause.map.to`` -> ("", "map.to")."""
    parts = atom.split(".")
    if len(parts) >= 3 and parts[1] == "directive":
        return parts[2].replace("_", " "), ".".join(parts[3:])
    if len(parts) >= 3 and parts[1] == "clause":
        return "", ".".join(parts[2:])
    return "", ".".join(parts[1:])


# --- document snapshots and the quote check ---------------------------------------

def norm(s: str) -> str:
    """Whitespace, typographic quotes, hyphens and Markdown roles folded."""
    s = (s.replace("‐", "-").replace("‑", "-")
         .replace("‘", "'").replace("’", "'")
         .replace("“", '"').replace("”", '"'))
    s = re.sub(r"\{(good|part|none)\}", "", s).replace("`", "")
    return re.sub(r"\s+", " ", s).strip()


_BULLET = re.compile(r"^(?:·|-|\*)\s+")


class TextDoc:
    """One paragraph or bullet per line. A quote is one sentence (a
    substring of a line; a short fragment must be a whole bullet), or
    ``"<header> ... <bullet> [... <bullet>]"``: each bullet under that
    header (the nearest preceding non-bullet line at the same or a smaller
    indentation, plus the lines between)."""

    def __init__(self, text: str):
        self.lines = []   # (indent, bullet, text, section)
        top = sub = ""
        for raw in text.splitlines():
            if not raw.strip():
                continue
            ind = len(raw) - len(raw.lstrip())
            t = raw.strip()
            m = _BULLET.match(t)
            body = norm(t[m.end():] if m else t)
            if not m and ind == 0 and t.upper() == t and len(t) < 60 and \
                    re.search("[A-Z]", t):
                top, sub = t, ""
            elif not m and ind == 3 and len(t) < 60 and \
                    not t.endswith((".", ":", ",")):
                sub = t
            self.lines.append((ind, bool(m), body,
                               f"{top} > {sub}" if sub else top))

    @staticmethod
    def _whole(frag: str, body: str, bullet: bool) -> bool:
        if not bullet or frag == body:
            return frag in body
        # a bullet is matched whole unless the quote is a sentence of it
        return (frag.endswith((".", ":", ";")) or len(frag) >= 60) and \
            frag in body

    def verify(self, quote: str) -> str | None:
        frags = [norm(f) for f in quote.split(" ... ")]
        if len(frags) == 1:
            for ind, bullet, body, sec in self.lines:
                if self._whole(frags[0], body, bullet):
                    return sec or "(top)"
            return None
        head, items = frags[0], frags[1:]
        where = None
        for item in items:
            hit = None
            for i, (ind, bullet, body, sec) in enumerate(self.lines):
                if not bullet or not self._whole(item, body, True):
                    continue
                ctx = []
                for j in range(i - 1, -1, -1):
                    jind, jb, jbody, _ = self.lines[j]
                    ctx.append(jbody)
                    if not jb and jind <= ind:
                        break
                if any(head in c for c in ctx):
                    hit = sec or "(top)"
                    break
            if hit is None:
                return None
            where = hit
        return where


def _table_rows(path: Path) -> list[tuple[str, str, str, str]]:
    """(section, group, feature, status) rows of a status table: the
    amdflang CSV (omp_version, feature, status), the extracted HTML tables
    (section, c1..c4) or a Markdown file of ``|`` tables. ``group`` is the
    row's category, or the section's version ("OpenMP 6.0") when the table
    has no category column; ``status`` is the C/C++ column of a table that
    has C/C++ and Fortran columns."""
    text = path.read_text(errors="replace")
    rows: list[tuple[str, list[str]]] = []
    if path.suffix == ".md":
        sec = ""
        for line in text.splitlines():
            if line.startswith("#"):
                sec = line.lstrip("#").strip()
            elif line.startswith("|") and not re.match(r"^\|\s*-", line):
                rows.append((sec, [c.strip() for c in
                                   line.strip().strip("|").split("|")]))
    else:
        r = list(csv.reader(io.StringIO(text)))
        if r and r[0][:3] == ["omp_version", "feature", "status"]:
            return [(x[0], x[0], norm(x[1]), norm(x[2])) for x in r[1:]]
        rows = [(x[0], x[1:]) for x in r[1:]]
    out, header = [], {}
    for sec, cells in rows:
        low = [norm(c).lower() for c in cells]
        if "feature" in low or (low and low[0] == ""
                                and "c/c++ status" in low):
            header[sec] = low
            continue
        h = header.get(sec) or ["category", "feature", "status"]
        get = {name: norm(cells[k]) for k, name in enumerate(h)
               if k < len(cells)}
        m = re.search(r"OpenMP (\d\.\d)", sec)
        group = get.get("category") or (f"OpenMP {m.group(1)}" if m
                                        else sec)
        feat = get.get("feature", get.get("", ""))
        if not feat and h and h[0] == "":
            feat = norm(cells[0])
        status = get.get("status") or get.get("c/c++ status") or ""
        out.append((sec, group, feat, status))
    return out


class TableDoc:
    """A quote is ``"group | feature | status; feature | status; ..."``
    (the group carries over to the next row)."""

    def __init__(self, path: Path):
        self.rows = _table_rows(path)

    def verify(self, quote: str) -> str | None:
        group, where = "", None
        for part in quote.split("; "):
            cells = [norm(c) for c in part.split(" | ")]
            if len(cells) == 3:
                group = cells[0]
                cells = cells[1:]
            if len(cells) != 2:
                return None
            feat, status = (c.lower() for c in cells)
            hit = next((r for r in self.rows if r[2].lower() == feat and
                        r[3].lower() == status and
                        (not group or r[1].lower() == group.lower())), None)
            if hit is None:
                return None
            where = hit[0]
        return where


class TodoDoc:
    """``"<test>.f90 [/ <test>.f90]: <message>"``: each test exists and
    expects the message (only the file list when the corpus is absent)."""

    def __init__(self, path: Path):
        self.path = path
        lst = ROOT / "data" / "index" / "claims" / "amdflang_afar_lowering_todo_tests.txt"
        self.names = set(lst.read_text().split()) if lst.is_file() else set()

    def verify(self, quote: str) -> str | None:
        files, _, msg = quote.partition(": ")
        for f in (x.strip() for x in files.split(" / ")):
            p = self.path / f
            if p.is_file():
                if norm(msg) not in norm(p.read_text(errors="replace")):
                    return None
            elif f.removesuffix(".f90") not in self.names:
                return None
        return "Todo test " + files.strip()


@dataclass(frozen=True)
class Edition:
    doc_id: str
    toolchain: str
    path: str
    origin: str
    version: str
    fmt: str

    @property
    def reader(self):
        return _reader(self.fmt, self.path)


@lru_cache(maxsize=None)
def _reader(fmt: str, path: str):
    p = ROOT / path
    if fmt == "text":
        return TextDoc(p.read_text(errors="replace"))
    if fmt == "table":
        return TableDoc(p)
    if fmt == "todo":
        return TodoDoc(p)
    raise ValueError(f"unknown document format {fmt}")


@dataclass(frozen=True)
class Document:
    doc_id: str
    vendor: str
    title: str
    url: str
    fmt: str
    cross_language: bool
    editions: dict

    def verify(self, toolchain: str, quote: str) -> str | None:
        ed = self.editions.get(toolchain)
        return None if ed is None else ed.reader.verify(quote)


def documents() -> dict[str, Document]:
    out = {}
    for k, d in (_vendor_data().get("documents") or {}).items():
        eds = {tc: Edition(k, tc, e["path"], e.get("origin", ""),
                           str(e.get("version", "")), d["format"])
               for tc, e in d["editions"].items()}
        out[k] = Document(k, d["vendor"], d["title"], d["url"], d["format"],
                          bool(d.get("cross_language", False)), eds)
    return out


# --- ingest --------------------------------------------------------------------------

@dataclass
class IngestReport:
    claims: list
    problems: list            # quotes found in no edition, unknown docs
    absent: list              # (map entry, toolchain): edition lacks quote


def _entries(path: Path) -> list[dict]:
    return (yaml.safe_load(Path(path).read_text()) or {}).get("claims") or []


def ingest(maps=MAPS) -> IngestReport:
    """Every mapping entry, checked against each edition of its document."""
    docs = documents()
    prods = products()
    out, problems, absent = [], [], []
    for path in maps:
        for i, e in enumerate(_entries(path)):
            p = Path(path)
            tag = f"{p.relative_to(ROOT) if p.is_relative_to(ROOT) else p}#{i}"
            d = docs.get(e["source"])
            if d is None:
                problems.append(f"{tag}: unknown document {e['source']}")
                continue
            tcs = list(e.get("toolchains") or
                       ([e["toolchain"]] if e.get("toolchain") else
                        d.editions))
            atoms = list(e.get("atoms") or []) + \
                ([e["atom"]] if e.get("atom") else []) + \
                ([e["pattern"]] if e.get("pattern") else [])
            found = False
            for tc in tcs:
                if tc not in d.editions:
                    problems.append(f"{tag}: {e['source']} has no {tc} "
                                    "edition")
                    continue
                where = d.verify(tc, e["quote"])
                if where is None:
                    absent.append((tag, tc))
                    continue
                found = True
                ed = d.editions[tc]
                spec = str(e.get("spec_version", ""))
                m = re.match(r"OpenMP (\d\.\d)", where)
                if not spec and d.fmt == "table" and m:
                    spec = m.group(1)   # the table's spec version
                prod = prods[tc]
                # An edition may name its own url (NVHPC 26.9)
                url = ((_vendor_data().get("documents") or {}).get(
                    e["source"], {}).get("editions", {}).get(tc, {}).get(
                    "url") or d.url)
                for a in atoms:
                    construct, clause = split_atom(a)
                    out.append(VendorClaim(
                        prod["vendor"], prod["product"], str(prod["version"]),
                        e["source"], url, e.get("language", "Fortran"),
                        e["claim"], e["quote"],
                        f"{d.title}: {where} [{ed.version}]", construct,
                        clause, spec, tc, a,
                        e.get("form") or "", bool(e.get("general", False)),
                        ",".join(str(v) for v in e.get("versions") or ()),
                        ed.path, d.cross_language, e.get("note", "")))
            if not found:
                problems.append(f"{tag}: quote not found in "
                                f"{e['source']} ({', '.join(tcs)}): "
                                f"{e['quote'][:80]}")
    return IngestReport(out, problems, absent)


def from_catalog(path: Path) -> list[VendorClaim]:
    """The generic records of one catalog/<model>/claims.yaml file."""
    return ingest((Path(path),)).claims


def load(path: Path = GENERIC) -> list[VendorClaim]:
    data = yaml.safe_load(Path(path).read_text()) or {}
    return [VendorClaim(**d) for d in data.get("claims") or []]


@lru_cache(maxsize=None)
def generic() -> tuple[VendorClaim, ...]:
    """The committed generic claims (empty if not ingested yet)."""
    return tuple(load(GENERIC)) if GENERIC.is_file() else ()


HEADER = ("# Generated by `python3 -I tools/derive/claims.py ingest` from the mapping\n"
          "# files catalog/omp/claims.yaml and catalog/acc/claims.yaml and the\n"
          "# document snapshots of catalog/vendor_claims.yaml. Do\n"
          "# not edit: change the mapping and ingest again.\n")


def dump(claims: list[VendorClaim], path: Path, header: str = "") -> None:
    Path(path).write_text(header + yaml.safe_dump(
        {"claims": [dataclasses.asdict(c) for c in claims]},
        sort_keys=False, allow_unicode=True, width=1000))
