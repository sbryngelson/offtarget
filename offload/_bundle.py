"""The data an installed offload carries (offload/_root), copied from the repository at build time."""
import json
import re
import shutil
import tempfile
from pathlib import Path

from offload.engine.root import ROOT

MANIFEST = ROOT / "tools" / "repo" / "bundle_manifest.txt"
SITE_DATA = ("issues.json", "search.json", "canuse", "compilers")


def manifest() -> list[str]:
    return [l.strip() for l in MANIFEST.read_text().splitlines() if l.strip() and not l.startswith("#")]


def _manifest_files(root: Path) -> set[Path]:
    out = set()
    for pat in manifest():
        hits = root.glob(pat[:-3] + "/**/*") if pat.endswith("/**") else root.glob(pat)
        out |= {p for p in hits if p.is_file() and "__pycache__" not in p.parts
                and not p.is_relative_to(root / "data" / "findings" / "proposed")}   # unreviewed proposals
    return out


_SITE_PATH = re.compile(r"/(?:p/(?:lustre\d|vast\d)|nethome|fastscratch)/[A-Za-z0-9_]+")


def _anonymise(path: Path) -> None:
    """The catalogs name the maintainers' install directories; an installed copy gets a neutral prefix."""
    if path.suffix not in (".yaml", ".yml", ".json", ".txt"):
        return
    try:
        text = path.read_text()
    except UnicodeDecodeError:
        return
    new = _SITE_PATH.sub("/path/to", text)
    if new != text:
        path.write_text(new)


def collect(dest: Path) -> list[Path]:
    """Copy the manifest files and the site data into `dest`."""
    dest = Path(dest)
    written = []
    for src in sorted(_manifest_files(ROOT)):
        target = dest / src.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        _anonymise(target)
        written.append(target)
    return written + collect_data(dest)


def collect_data(dest: Path) -> list[Path]:
    """Write <dest>/data: the site's issue and can-use JSON (not the per-issue pages) and the can-use columns."""
    from offload.engine.site import columns
    from offload.engine.site import data as D
    dest = Path(dest)
    written = []
    with tempfile.TemporaryDirectory() as tmp:
        D.build(Path(tmp))
        for name in SITE_DATA:
            src = Path(tmp) / "data" / name
            for f in ([src] if src.is_file() else sorted(src.rglob("*"))):
                if f.is_file():
                    target = dest / "data" / f.relative_to(Path(tmp) / "data")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, target)
                    written.append(target)
    cols = dest / "data" / "canuse" / "columns.json"
    cols.write_text(json.dumps(columns.canuse_columns(), separators=(",", ":")))
    return written + [cols]
