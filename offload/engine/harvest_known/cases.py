"""The harvested cases (data/bench/harvest-known/hk-NNN.<f90|c>, the
data/bench/fresh case format: a header with ``fresh case:``, ``source:``,
``edits:``, ``expected: RESULT: pass``).

legality_rows runs the pre-run legality check (offload.engine.prerun.check:
the rules witness and the front-end witness, never a compiler under test
judging itself, plus the race rule) on each case. Refused cases are
recorded with the reasons and never run."""
from __future__ import annotations

from pathlib import Path


def lang_of(path: Path) -> str:
    return "c" if path.suffix == ".c" else "f90"


def legality_rows(paths, frontend: bool = True,
                  timeout_s: int = 600) -> list[dict]:
    from offload.engine import prerun
    rows = []
    for p in paths:
        text = Path(p).read_text()
        ok, why = prerun.check((text, lang_of(Path(p))), frontend=frontend,
                               timeout_s=timeout_s)
        rows.append({"id": Path(p).stem, "ok": bool(ok), "reasons": why,
                     "kind": None if ok else prerun.refusal_kind(why)})
    return rows


import re as _re

_NV = _re.compile(r"forums\.developer\.nvidia\.com/t/(?:[^/]+/)?(\d+)")
_GH = _re.compile(r"github\.com/([^/]+)/([^/]+)/(?:issues|pull)/(\d+)")
_COMMIT = _re.compile(r"/commit/([0-9a-f]{7,40})")


def url_key(url: str) -> str:
    """A source URL in a form two sets can compare: the forum topic id, the
    GitHub issue or pull-request number, the first 7 hex digits of a
    commit; any other URL as written (trailing slash dropped)."""
    u = str(url).strip()
    m = _NV.search(u)
    if m:
        return f"nvforum:{m.group(1)}"
    m = _GH.search(u)
    if m:
        return f"gh:{m.group(1).lower()}/{m.group(2).lower()}#{m.group(3)}"
    m = _COMMIT.search(u)
    if m:
        return f"commit:{m.group(1)[:7]}"
    return u.rstrip("/")


def known_keys(dirs) -> dict[str, str]:
    """url_key -> the case id (or 'excluded') of every source URL another
    set holds (cases.yaml: each case's url and also; excluded sources).
    For a sealed set the caller only tests membership; nothing here is
    printed."""
    import yaml
    out: dict[str, str] = {}
    for d in dirs:
        meta = Path(d) / "cases.yaml"
        if not meta.is_file():
            continue
        y = yaml.safe_load(meta.read_text()) or {}
        for c in y.get("cases") or []:
            for u in [c.get("url"), *(c.get("also") or [])]:
                if u:
                    out.setdefault(url_key(u), c["id"])
        for e in y.get("excluded") or []:
            if e.get("source"):
                out.setdefault(url_key(e["source"]), "excluded")
    return out


# --- the 30% holdout and the export to the runner --------------------------------

import hashlib as _hashlib

HOLDOUT_FRACTION = 0.30
# toolchains (offload.engine.toolchains names) by what they compile: the AMD
# gfx942 toolchains, their gfx90a twins and the other toolchains of the
# merged result tables (NVHPC; GCC, under test only, is no target); OpenACC is CCE Fortran and NVHPC only (AFAR
# has none; CCE has no OpenACC C): catalog/toolchains.yaml families
from offload.engine.toolchains import GFX90A_TOOLCHAINS as _G90  # noqa: E402
from offload.engine.toolchains import GFX942_TOOLCHAINS as _G942  # noqa: E402
from offload.engine.toolchains import TOOLCHAINS as _TC, registry as _registry  # noqa: E402
ALL_TC = list(_G942 + _G90 + tuple(t for t in _registry().merged() if t not in _G942
                                    and _TC[t].family_id not in _registry().under_test_only()))
ACC_F_TC = [t for t in ALL_TC if _TC[t].family.why_unsupported("acc", "f90") is None]
ACC_C_TC = [t for t in ALL_TC if _TC[t].family.why_unsupported("acc", "c") is None]


def holdout(text: str) -> bool:
    """The rule (offload.engine.harvest.convert.holdout): the program
    whose sha256 lies in the lowest 30% of the hash space."""
    h = int(_hashlib.sha256(text.encode()).hexdigest(), 16)
    return h < int(HOLDOUT_FRACTION * (1 << 256))


def toolchains_for(lang: str, model: str) -> list[str]:
    if model == "acc":
        return list(ACC_C_TC if lang == "c" else ACC_F_TC)
    return list(ALL_TC)


def export_rows(bench) -> list[dict]:
    """The cases of ``bench`` as rows of the runner's programs.jsonl (id,
    record, variant, version, oracle, file, lang, model, modes, holdout),
    plus the toolchains that compile the model and the text's sha256."""
    import yaml
    bench = Path(bench)
    meta = yaml.safe_load((bench / "cases.yaml").read_text())
    out = []
    for c in meta["cases"]:
        text = (bench / c["file"]).read_text()
        model = c["model"]
        version = 34 if model == "acc" else int(c.get("omp_version", 52))
        out.append({"id": c["id"], "record": c["id"], "variant": 0,
                    "version": version, "oracle": "selfcheck",
                    "file": c["file"], "lang": c["lang"], "model": model,
                    "modes": list(c.get("modes", ["copy", "unified"])),
                    "holdout": holdout(text),
                    "sha256": _hashlib.sha256(text.encode()).hexdigest(),
                    "toolchains": toolchains_for(c["lang"], model),
                    "source": c.get("source_kind", "")})
    return out
