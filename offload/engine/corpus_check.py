"""Validate the grammar against the Fortran OpenMP lines of the corpus.

``check_corpus(index_csv, out_csv)`` reads every Fortran OpenMP file in the
corpus index (``data/index/corpus_index.csv``), finds the free-form ``!$omp``
directive lines (joined across ``&`` continuations), parses each slice
directive with ``parse_directive`` at OpenMP 5.2 and 6.0, and writes one CSV
row per line that parses at neither. Corpus files are untrusted and only read
as text. The exception is ``compare_with_flang``, which passes a selection of
deduplicated directives, wrapped in a generated program, to the flang frontend
(``-fc1``) in a temporary directory, in a process pool.

Fixed-form sources and ``c$omp`` / ``*$omp`` lines are counted under
``failed["fixed_form"]`` and not parsed. Directives outside ``slice_directives``
are counted in ``Summary.out_of_slice``. Lines from ``lit-diagnostic`` rows get
``diagnostic=true``; lines a GCC ``dg-error`` targets get ``expected_error=true``.
"""
from __future__ import annotations

import csv
import random
import re
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from offload.engine.catalog import (default_grammar, default_skeleton,
                                slice_directives)
from offload.engine.grammar import (GrammarError, _fortran_line, _is_comment,
                                _outside_strings, _parser, _strip_bang_comment,
                                _tokenize, parse_directive)

VERSIONS = (52, 60)
FIXED_FORM_EXTS = {".f", ".for", ".f77", ".ftn"}
DIAGNOSTIC_KINDS = {"lit-diagnostic"}
CSV_FIELDS = ["repo", "path", "line", "text", "error_code", "diagnostic",
              "expected_error", "kind", "directive", "error_52", "error_60"]

_FREE = re.compile(r"^\s*!\$omp(?=[\sxX&]|$)", re.I)
_FIXED_FREE_FILE = re.compile(r"^[cC*]\$omp", re.I)    # column 1 only
_FIXED_ANY = re.compile(r"^[cC*!]\$omp", re.I)


@dataclass
class Summary:
    """total = parsed + sum(failed.values()); failed includes "fixed_form".
    out_of_slice lines are not in total; diagnostic counts the failures
    (fixed form excluded) in diagnostic-test files."""
    total: int
    parsed: int
    failed: dict[str, int]
    out_of_slice: int = 0
    diagnostic: int = 0


@dataclass(frozen=True)
class DirectiveText:
    line: int          # 1-based line of the first physical line
    text: str          # the physical lines, joined with "\n"
    fixed_form: bool


# --- finding directive lines ---------------------------------------------------

def _fixed_start(raw: str) -> bool:
    return len(raw) < 6 or raw[5] in " \t0"


def _continues(raw: str) -> bool:
    m = _FREE.match(raw)
    return bool(m) and _strip_bang_comment(raw[m.end():]).rstrip() \
        .endswith("&")


def extract_directives(source: str, fixed_form: bool = False
                       ) -> list[DirectiveText]:
    """The OpenMP directives of one Fortran source, continuations joined."""
    lines = source.splitlines()
    out: list[DirectiveText] = []
    i = 0
    while i < len(lines):
        raw = lines[i]
        fixed_rx = _FIXED_ANY if fixed_form else _FIXED_FREE_FILE
        if fixed_rx.match(raw):
            if _fixed_start(raw):
                out.append(DirectiveText(i + 1, raw.rstrip(), True))
            i += 1
            continue
        m = _FREE.match(raw)
        if fixed_form or not m or raw[m.end():].lstrip().startswith("&"):
            i += 1
            continue
        group, j = [raw.rstrip()], i
        while _continues(lines[j]):
            k = j + 1
            while k < len(lines) and _is_comment(lines[k]):
                k += 1
            if k < len(lines) and _FREE.match(lines[k]):
                group.append(lines[k].rstrip())
                j = k
            else:
                break
        out.append(DirectiveText(i + 1, "\n".join(group), False))
        i = j + 1
    return out


def normalise(text: str) -> str:
    """One logical line: sentinel, lower case and single blanks outside
    strings, comments and continuations removed. Used to deduplicate."""
    try:
        line = _fortran_line(text)
    except GrammarError:
        line = re.sub(r"^\s*\S+", "", text.strip().lower(), count=1)
    line = _outside_strings(line, lambda s: re.sub(r"\s+", " ", s))
    return f"!$omp {line.strip()}"


# --- the slice ---------------------------------------------------------------------

def _keys_for(text: str) -> list[str]:
    """Skeleton keys of the directive name leading a free-form directive;
    [] for unknown names and unparsable sentinels."""
    try:
        line = _fortran_line(text)
    except GrammarError:
        return []
    p = _parser(default_skeleton(), default_grammar(), "Fortran", 60)
    spelling, _end, _rest = p.fortran_name(_tokenize(line))
    return list(p.index[spelling]) if spelling else []


def _free_form_view(d: DirectiveText) -> str:
    """A fixed-form directive's first line with a free-form sentinel, for
    name matching only."""
    first = d.text.split("\n")[0]
    return "!$omp " + first[5:].split("&")[0] if len(first) > 5 else first


def in_slice(d: DirectiveText) -> tuple[bool, str]:
    keys = _keys_for(_free_form_view(d) if d.fixed_form else d.text)
    slice_keys = set(slice_directives(default_skeleton()))
    return any(k in slice_keys for k in keys), ";".join(keys)


# --- checking ------------------------------------------------------------------------

@dataclass
class Record:
    repo: str
    path: str
    kind: str
    d: DirectiveText
    directive: str
    in_slice: bool
    errors: dict  # version -> GrammarError | None (empty for fixed form)
    expected_error: bool = False  # a GCC dg-error annotation targets it

    @property
    def diagnostic(self) -> bool:
        return self.kind in DIAGNOSTIC_KINDS

    @property
    def parsed(self) -> bool:
        return any(e is None for e in self.errors.values())

    @property
    def code(self) -> str | None:
        if self.d.fixed_form:
            return "fixed_form"
        if not self.errors or self.parsed:  # parsed, or not checked
            return None
        e52, e60 = self.errors[52], self.errors[60]
        return e60.code if e52.code == "version" else e52.code


_DG_ERROR = re.compile(
    r'\{\s*dg-error\s+"(?:[^"\\]|\\.)*"(?:\s+"(?:[^"\\]|\\.)*")?'
    r'(?:\s+\{[^}]*\})?\s*([.][-+]\d+|\d+)?\s*\}')


def dg_error_lines(source: str) -> set[int]:
    """1-based lines that a GCC testsuite `{ dg-error ... }` annotation
    expects an error on: its own line, a relative `.-N` / `.+N`, or an
    absolute line (0, "anywhere", is ignored)."""
    out = set()
    for n, raw in enumerate(source.splitlines(), 1):
        for m in _DG_ERROR.finditer(raw):
            where = m.group(1)
            if where is None:
                out.add(n)
            elif where.startswith("."):
                out.add(n + int(where[1:]))
            elif int(where):
                out.add(int(where))
    return out


_PARSE_CACHE: dict[str, dict] = {}


def _parse_both(text: str) -> dict:
    hit = _PARSE_CACHE.get(text)
    if hit is None:
        hit = {}
        for v in VERSIONS:
            try:
                parse_directive(text, "fortran", v)
                hit[v] = None
            except GrammarError as e:
                hit[v] = e
        _PARSE_CACHE[text] = hit
    return hit


def _index_rows(index_csv: Path):
    with open(index_csv, newline="") as fh:
        for row in csv.DictReader(fh):
            if row["lang"] == "fortran" and row["model"] == "omp":
                yield row


def scan_corpus(index_csv: Path, corpus_root: Path | None = None,
                slice_only: bool = True) -> list[Record]:
    """Every directive of the indexed Fortran OpenMP files, as Records."""
    index_csv = Path(index_csv)
    root = Path(corpus_root or index_csv.resolve().parent.parent.parent / "corpus")
    root = root.resolve()
    records = []
    for row in _index_rows(index_csv):
        path = (root / row["repo"] / row["path"]).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise FileNotFoundError(f"indexed file missing or outside the "
                                    f"corpus: {row['repo']}/{row['path']}")
        source = path.read_text(errors="replace")
        fixed = path.suffix.lower() in FIXED_FORM_EXTS
        targets = dg_error_lines(source)
        for d in extract_directives(source, fixed_form=fixed):
            ok, keys = in_slice(d)
            errors = {} if d.fixed_form or (slice_only and not ok) \
                else _parse_both(d.text)
            span = range(d.line, d.line + d.text.count("\n") + 1)
            records.append(Record(row["repo"], row["path"], row["kind"], d,
                                  keys, ok, errors,
                                  any(n in targets for n in span)))
    return records


def _row(r: Record) -> dict:
    return {"repo": r.repo, "path": r.path, "line": r.d.line,
            "text": r.d.text, "error_code": r.code,
            "diagnostic": "true" if r.diagnostic else "false",
            "expected_error": "true" if r.expected_error else "false",
            "kind": r.kind, "directive": r.directive,
            "error_52": str(r.errors.get(52) or ""),
            "error_60": str(r.errors.get(60) or "")}


def summarise(records: list[Record], slice_only: bool = True) -> Summary:
    counted = [r for r in records if r.in_slice or not slice_only]
    failed = Counter(r.code for r in counted if r.code)
    return Summary(
        total=len(counted),
        parsed=sum(1 for r in counted if r.code is None),
        failed=dict(failed),
        out_of_slice=len(records) - len(counted),
        diagnostic=sum(1 for r in counted if r.code and r.code != "fixed_form"
                       and r.diagnostic))


def check_corpus(index_csv: Path, out_csv: Path, slice_only: bool = True,
                 corpus_root: Path | None = None) -> Summary:
    """Parse the corpus's slice directives; one CSV row per failing line."""
    records = scan_corpus(index_csv, corpus_root, slice_only)
    return write_failures(records, out_csv, slice_only)


def write_failures(records: list[Record], out_csv: Path,
                   slice_only: bool = True) -> Summary:
    """Write the failing lines of `records` to `out_csv`; their Summary."""
    out_csv = Path(out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(_row(r) for r in records
                    if (r.in_slice or not slice_only) and r.code)
    return summarise(records, slice_only)


# --- the flang cross-check ----------------------------------------------------------

FLANG_SEED = 20261017
FLANG_SAMPLE = 300
FLANG_FIELDS = ["sample", "version", "text", "n_lines", "example",
                "grammar_code", "verdict", "flang_stage", "flang_error",
                "same_clauses", "note"]


def flang_text(norm: str, width: int = 100) -> str:
    """A normalised directive split into `!$omp&` continuation lines at
    blanks (outside strings) so no line exceeds the free-form limit."""
    words = re.findall(r"""(?:'[^']*'|"[^"]*"|\S)+""", norm)
    lines, cur = [], ""
    for w in words:
        if cur and len(cur) + len(w) + 3 > width:
            lines.append(cur + " &")
            cur = "!$omp& " + w
        else:
            cur = f"{cur} {w}" if cur else w
    return "\n".join(lines + [cur])


def _compare_job(job: tuple[str, int]) -> dict:
    from offload.engine.flang_oracle import FlangError, compare
    text, version = job
    try:
        a = compare(flang_text(text), version)
    except FlangError as e:  # the tool itself failed: record, do not hide
        return {"verdict": "error", "flang_stage": e.stage,
                "flang_error": e.message, "same_clauses": "", "note": ""}
    err = a.flang_error or ""
    first = next((l for l in err.splitlines() if "error:" in l
                  and "Semantic errors" not in l
                  and "Could not parse" not in l), err.split("\n")[0])
    return {"verdict": a.verdict, "flang_stage": a.flang_stage,
            "flang_error": first.strip(), "same_clauses": a.same_clauses,
            "note": a.note}


def flang_jobs(records: list[Record], sample: int = FLANG_SAMPLE,
               seed: int = FLANG_SEED) -> list[dict]:
    """The comparisons to run, deduplicated by normalised text: every grammar
    failure in a non-diagnostic file (at 5.2 and 6.0) and a seeded random
    sample of `sample` distinct grammar successes (at the first version
    they parse at)."""
    groups: dict[tuple[str, str], list[Record]] = {}
    for r in records:
        if not r.in_slice or r.d.fixed_form:
            continue
        if r.code is None:
            groups.setdefault(("success", normalise(r.d.text)), []).append(r)
        elif not r.diagnostic:
            groups.setdefault(("failure", normalise(r.d.text)), []).append(r)
    jobs = []
    for (kind, text), rs in sorted(groups.items()):
        if kind == "failure":
            for v in VERSIONS:
                jobs.append((kind, v, text, rs))
    ok = sorted(t for k, t in groups if k == "success")
    for text in random.Random(seed).sample(ok, min(sample, len(ok))):
        rs = groups[("success", text)]
        v = next(v for v in VERSIONS if rs[0].errors[v] is None)
        jobs.append(("success", v, text, rs))
    return [{"sample": k, "version": v, "text": t, "n_lines": len(rs),
             "example": f"{rs[0].repo}/{rs[0].path}:{rs[0].d.line}",
             "grammar_code": rs[0].code or ""} for k, v, t, rs in jobs]


def compare_with_flang(records: list[Record], out_csv: Path,
                       workers: int = 16, sample: int = FLANG_SAMPLE,
                       seed: int = FLANG_SEED) -> dict:
    """Run `flang_jobs` through `flang_oracle.compare` in a process pool
    (each comparison writes its program in its own temporary directory) and
    write one CSV row per comparison. Returns counts and the runtime."""
    jobs = flang_jobs(records, sample, seed)
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(_compare_job,
                                [(j["text"], j["version"]) for j in jobs],
                                chunksize=4))
    seconds = time.time() - t0
    rows = [{**j, **r} for j, r in zip(jobs, results)]
    out_csv = Path(out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FLANG_FIELDS)
        w.writeheader()
        w.writerows(rows)
    per_text = {k: {j["text"]: j["n_lines"] for j in jobs
                    if j["sample"] == k} for k in ("failure", "success")}
    texts = {k: len(v) for k, v in per_text.items()}
    lines = {k: sum(v.values()) for k, v in per_text.items()}
    return {"comparisons": len(rows), "seconds": round(seconds, 1),
            "workers": workers, "texts": texts, "lines": lines,
            "verdicts": dict(Counter((r["sample"], r["version"], r["verdict"])
                                     for r in rows))}
