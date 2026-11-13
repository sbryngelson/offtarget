#!/usr/bin/env python3
"""Write, or check, the site's committed inputs, site/inputs/ (offload.engine.site.inputs):

    python3 -I tools/site/site_inputs.py            # write atoms.json.gz and citations.json
    python3 -I tools/site/site_inputs.py --check    # exit 1 when a committed file is stale

atoms.json.gz is feature support per construct, derived from the dashboard's atom table
(results/dash/atoms.json, written by tools/site/dashboard_data.py on Tuolumne): the device-scope
rows with the columns the site reads. citations.json holds the verified specification
citations of every published finding (offload.engine.citations against the spec cache,
results/spec_cache/, which needs the spec PDFs under spec/). Both inputs are git-ignored,
so the site build reads these committed copies instead (docs/tooling/publishing.md);
``tools/regenerate.py --check site-inputs`` runs the same comparison. On wingtip:
``tools/lanes/wingtip_offline.sh site-inputs``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine import spec_text  # noqa: E402
from offload.engine.site import data as D  # noqa: E402
from offload.engine.site import inputs as I  # noqa: E402

RAW_ATOMS = ROOT / "results" / "dash" / "atoms.json"
SPEC_CACHE = spec_text.CACHE_DIR
SPEC = ROOT / "spec"


def derive_atoms() -> list[dict]:
    cols = {c for cs in D._atom_columns().values() for c, _ in cs}
    return I.project_atoms(json.loads(RAW_ATOMS.read_text()), cols)


def derive_citations() -> dict:
    from offload.engine.confirm.findings import load_index
    from offload.engine.site import header as H
    base = ROOT / "data" / "findings"
    out = {}
    for f in load_index():
        path = ROOT / f.file
        if D.published({"header": H.parse(path)}):
            out[str(path.relative_to(base))] = D._citations(path)   # against the spec text
    return out


def stale() -> list[str]:
    """The committed files that differ from what the measurements give now."""
    out = []
    if not I.ATOMS.is_file() or I.ATOMS.read_bytes() != I.dump_atoms(derive_atoms()):
        out.append(I.ATOMS.name)
    if not I.CITATIONS.is_file() or I.CITATIONS.read_text() != I.dump_citations(derive_citations()):
        out.append(I.CITATIONS.name)
    return out


def write() -> dict:
    I.DIR.mkdir(parents=True, exist_ok=True)
    atoms = derive_atoms()
    cites = derive_citations()
    I.ATOMS.write_bytes(I.dump_atoms(atoms))
    I.CITATIONS.write_text(I.dump_citations(cites))
    return {"atoms": len(atoms), "findings": len(cites),
            "citations": sum(len(v) for v in cites.values())}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    for p in (RAW_ATOMS, SPEC_CACHE, SPEC):
        if not p.exists():
            print(f"site_inputs: {p.relative_to(ROOT)} is missing (git-ignored; docs/tooling/setup.md, "
                  "docs/tooling/regenerate.md)", file=sys.stderr)
            return 2
    if argv == ["--check"]:
        out = stale()
        for name in out:
            print(f"site/inputs/{name}: stale (python3 -I tools/site/site_inputs.py)")
        return 1 if out else 0
    if argv:
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        return 2
    print(json.dumps(write()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
