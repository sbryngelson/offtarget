"""The site's committed inputs (site/inputs/): the compact data the public site needs
from the git-ignored measurements, so that a clean clone builds the same site as the
shared tree (docs/tooling/publishing.md).

* ``atoms.json.gz``: feature support per construct, the device-scope rows of the
  dashboard's atom table with only the columns the site reads (``canuse``).
* ``citations.json``: the verified specification citations of every published finding
  (offload.engine.citations against the spec cache), keyed by the finding file.

tools/site/site_inputs.py writes them and ``tools/regenerate.py --check site-inputs`` reports
them stale; the build refuses to run without them (``SiteInputError``) instead of
silently building a smaller site. ``MANIFEST`` lists every committed path the build
reads (tests/site/test_site_inputs.py checks each is tracked and not ignored)."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

from offload.engine.site import scrub as S

ROOT = Path(__file__).resolve().parents[3]
DIR = ROOT / "site" / "inputs"
ATOMS = DIR / "atoms.json.gz"
CITATIONS = DIR / "citations.json"
GENERATOR = "python3 -I tools/site/site_inputs.py"

# every committed path tools/site/site_build.py reads (measured with an audit hook on a
# build in a clean clone, 2026-11-03), besides the code under offload/engine/ and tools/
MANIFEST = (
    "catalog/toolchains.yaml", "catalog/machines.yaml", "catalog/omp/rules.yaml", "catalog/acc/rules.yaml",
    "data/findings/index.yaml", "data/findings/**/*.f90", "data/findings/**/*.c",
    "data/vendor/checks/build.py", "data/vendor/checks/run_checks.py",
    "data/vendor/checks/cases.json", "data/vendor/checks/cases-site.json",
    "data/vendor/checks/src/*/control/*-control.f90", "data/vendor/checks/src/*/control/*-control.c",
    "data/vendor/checks/results-compact/*.jsonl.gz", "data/vendor/checks/results-site/*.jsonl.gz",
    "site/templates/base.html", "site/static/*.js", "site/static/*.css",
    "site/inputs/atoms.json.gz", "site/inputs/citations.json",
)
# the atom fields the site reads besides the support columns
ATOM_FIELDS = ("scope", "atom", "id", "version", "lang", "citation")


class SiteInputError(RuntimeError):
    pass


def project_atoms(atoms: list[dict], cols) -> list[dict]:
    """The device-scope rows with the fields and support columns the site reads
    (offload.engine.site.data.canuse); a note only where the site shows it (an unknown or
    unsupported cell), scrubbed, and refused if it still identifies a person or a path."""
    from offload.engine.site.data import CU_WORD
    out = []
    for a in atoms:
        if a.get("scope") != "device":
            continue
        row = {k: a[k] for k in ATOM_FIELDS if k in a}
        for c in sorted(cols):
            if c not in a:
                continue
            row[c] = a[c]
            note = a.get("note_" + c)
            if note and CU_WORD.get(a[c], "unknown") in ("unknown", "unsupported"):
                row["note_" + c] = S.scrub(str(note))
        line = json.dumps(row, sort_keys=True)
        if S.leaks(line):
            raise SiteInputError(f"{row.get('id')}: still identifies a user, host or path after "
                                 f"scrubbing: {sorted(set(S.leaks(line)))[:5]}")
        out.append(row)
    return out


def dump_atoms(rows: list[dict]) -> bytes:
    """The rows as a gzip member with no timestamp: the same rows give the same bytes."""
    text = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    return gzip.compress(text.encode(), mtime=0)


def dump_citations(table: dict) -> str:
    """The findings in order; each citation keeps its field order (text, version, section,
    quote), so the issue pages are byte-identical to a build that checked the spec itself."""
    return json.dumps(dict(sorted(table.items())), indent=1, ensure_ascii=False) + "\n"


def _missing(path: Path, what: str) -> SiteInputError:
    return SiteInputError(f"{what}: {_rel(path)} is missing; write it with `{GENERATOR}` "
                          "(needs the git-ignored measurements, docs/tooling/regenerate.md)")


def _rel(p: Path) -> str:
    try:
        return str(Path(p).relative_to(ROOT))
    except ValueError:
        return str(p)


def load_atoms() -> list[dict]:
    if not ATOMS.is_file():
        raise _missing(ATOMS, "feature support")
    return json.loads(gzip.decompress(ATOMS.read_bytes()))


def load_citations() -> dict:
    if not CITATIONS.is_file():
        raise _missing(CITATIONS, "the findings' specification citations")
    return json.loads(CITATIONS.read_text())


def citations_of(rel: str, table: dict) -> list[dict]:
    """The committed citations of one finding file; a published finding the table does
    not know is a stale table, not an issue without citations."""
    if rel not in table:
        raise SiteInputError(f"{_rel(CITATIONS)} has no entry for the published finding {rel}; "
                             f"rerun `{GENERATOR}`")
    return table[rel]
