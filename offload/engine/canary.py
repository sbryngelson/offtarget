"""Canaries. Every campaign runs five programs per toolchain with a known
outcome (catalog/canaries.yaml). Its report is not written if one changed.
* ``pass``: runs correctly on the device on every toolchain;
* ``ice``: a known internal compiler error or rejection;
* ``wrong``: a known wrong answer;
* ``racy``: a racy program the pre-run check (offload.engine.prerun) must refuse
  (outcome ``refused``, never compiled);
* ``hang``: never ends; the run timeout must end it (outcome
  ``wrong_answer``, reason ``timeout``).

``check`` names the changed canaries and ``require_unchanged`` stops the
report. Canary rows are harness rows (offload.engine.harness.Result as a dict)
plus ``canary`` (the kind) and ``canary_program``. A campaign writes them to
``<campaign output>.canaries.jsonl`` (matrix file) or
``<run dir>/canaries.jsonl`` (fuzz, stress); ``run_for`` makes them."""
from __future__ import annotations

import dataclasses
import json
from functools import lru_cache
from pathlib import Path

import yaml

from offload.engine import localcfg

ROOT = Path(__file__).resolve().parent.parent.parent
CANARIES = ROOT / "catalog" / "canaries.yaml"
KINDS = ("pass", "ice", "wrong", "racy", "hang")


class CanaryChanged(RuntimeError):
    """A canary's outcome differs from catalog/canaries.yaml."""


@lru_cache(maxsize=None)
def _load(path: str) -> dict:
    d = yaml.safe_load(Path(path).read_text()) or {}
    if Path(path) == CANARIES:
        d = localcfg.overlay("canaries.yaml", d)       # a user's own toolchains
    if d.get("version") != 1:
        raise ValueError("canaries: unknown version")
    for tc, kinds in (d.get("toolchains") or {}).items():
        if set(kinds) != set(KINDS):
            raise ValueError(f"canaries: {tc} must name {KINDS}")
        for k, v in kinds.items():
            if v["program"] not in d["programs"]:
                raise ValueError(f"canaries: {tc} {k}: unknown program")
            if "outcome" not in v:
                raise ValueError(f"canaries: {tc} {k}: no outcome")
    return d


def load(path: Path | None = None) -> dict:
    return _load(str(path or CANARIES))


def program(name: str, spec: dict | None = None):
    """The Program of a canary program entry (a catalog id or a file)."""
    spec = spec or load()
    p = spec["programs"][name]
    if "catalog" in p:
        from offload.engine.confirm.programs import catalog_program
        prog = catalog_program(p["catalog"])
        if prog is None:
            raise KeyError(f"canary program {p['catalog']} is no longer "
                           "generated")
        return prog
    from offload.engine.harness import program_from_file
    return program_from_file(ROOT / p["file"], id=f"canary-{name}")


def _toolchain(prog, name: str):
    from offload.engine.confirm.execute import toolchain_for
    from offload.engine.confirm.programs import catalog_ref
    from offload.engine.toolchains import TOOLCHAINS
    if prog.id.startswith(("omp", "acc")) and not prog.id.startswith(
            "canary-"):
        return toolchain_for(catalog_ref(prog.id, prog), name)
    return TOOLCHAINS[name]


def run_for(toolchain: str, xnack: int, timeout_s: int = 120,
            spec: dict | None = None, tc=None, runner=None,
            prerun=None) -> list[dict]:
    """The canary rows of one toolchain and memory mode: the racy canary
    through the pre-run check only (never compiled), the others through
    the harness with the campaign's run timeout. `tc`, `runner` and
    `prerun` replace the toolchain, harness.run_program and
    offload.engine.prerun.check (tests)."""
    from offload.engine import harness
    spec = spec or load()
    kinds = spec["toolchains"][toolchain]
    run = runner or harness.run_program
    out = []
    for kind in KINDS:
        name = kinds[kind]["program"]
        prog = program(name, spec)
        if kind == "racy":
            from offload.engine import prerun as PR
            ok, why = (prerun or PR.check)(prog)
            row = {"program_id": prog.id, "toolchain": toolchain,
                   "xnack": xnack, "outcome": "accepted" if ok else
                   "refused", "reason": "; ".join(why)[:600]}
        else:
            t = tc or _toolchain(prog, toolchain)
            res = run(prog, t, xnack, "-O2", timeout_s=timeout_s, repeats=1)
            row = dataclasses.asdict(res)
            row["outcome"] = str(row["outcome"])
            row["toolchain"] = toolchain
        row["canary"] = kind
        row["canary_program"] = name
        out.append(row)
    return out


def _matches(row: dict, want: dict) -> bool:
    if str(row.get("outcome")) != want["outcome"]:
        return False
    reason = row.get("reason") or ""
    pre = want.get("reason")
    return pre is None or reason.startswith(pre) or pre in reason


def check(campaign_rows, spec: dict | None = None) -> list[str]:
    """The canaries whose outcome differs from catalog/canaries.yaml, one
    message each (rows without a ``canary`` field are the campaign's own
    and are skipped; a canary of a toolchain the file does not list is
    reported)."""
    spec = spec or load()
    out = []
    for r in campaign_rows:
        kind = r.get("canary")
        if not kind:
            continue
        tc = r.get("toolchain")
        want = (spec.get("toolchains") or {}).get(tc, {}).get(kind)
        if want is None:
            out.append(f"canary {kind} on {tc}: no expected outcome in "
                       "catalog/canaries.yaml")
            continue
        if not _matches(r, want):
            out.append(
                f"canary {kind} ({want['program']}) on {tc} at mode key "
                f"{r.get('xnack')}: expected {want['outcome']}"
                + (f" ({want['reason']})" if want.get("reason") else "")
                + f", got {r.get('outcome')}: {(r.get('reason') or '')[:160]}")
    return out


def rows_of(paths) -> list[dict]:
    out = []
    for p in paths:
        p = Path(p)
        if not p.is_file():
            continue
        for ln in p.read_text().splitlines():
            if ln.strip():
                out.append(json.loads(ln))
    return out


def files_for(results: Path) -> list[Path]:
    """The canary files of a campaign output: ``<file>.canaries.jsonl``
    next to a matrix file (and those of the per-mode runs merged into it:
    ``<stem>.*.canaries.jsonl``), ``canaries.jsonl`` in a run directory."""
    results = Path(results)
    if results.is_dir():
        return sorted(results.glob("canaries.jsonl"))
    stem = results.name[:-len(".jsonl")] if results.name.endswith(
        ".jsonl") else results.name
    return sorted(set(results.parent.glob(f"{stem}.canaries.jsonl")) |
                  set(results.parent.glob(f"{stem}.*.canaries.jsonl")))


def _post_task45(campaign_rows) -> bool:
    """A campaign recorded with provenance: its rows carry git_rev
    or gate."""
    return any(r.get("git_rev") or r.get("gate") for r in campaign_rows)


def missing(campaign_rows, canary_rows, spec: dict | None = None
            ) -> list[str]:
    """The (toolchain, mode, kind) canaries
    a campaign recorded with provenance lacks: the toolchains and modes
    whose rows carry provenance (a file merged from older runs and newer
    ones needs them for the newer only); a toolchain absent from
    catalog/canaries.yaml is one message. An explicit exemption row
    (``canary_exempt``: the reason) exempts the campaign."""
    spec = spec or load()
    if not _post_task45(campaign_rows):
        return []
    if any(r.get("canary_exempt") for r in canary_rows):
        return []
    have = {(r.get("toolchain"), int(r.get("xnack", -1)), r.get("canary"))
            for r in canary_rows if r.get("canary")}
    cells = {(r.get("toolchain"), int(r.get("xnack", r.get("mode", -1))))
             for r in campaign_rows if r.get("toolchain") and _post_task45([r])}
    out = []
    for tc, x in sorted(cells, key=str):
        if tc not in (spec.get("toolchains") or {}):
            out.append(f"toolchain {tc} has no canaries in "
                       "catalog/canaries.yaml")
            continue
        for k in KINDS:
            if (tc, x, k) not in have:
                out.append(f"canary {k} missing on {tc} at mode key {x}")
    return out


def require_unchanged(rows_or_paths, what: str = "the campaign",
                      campaign_rows=None) -> int:
    """Stop the report (CanaryChanged) when a canary changed, or (with
    `campaign_rows`) when a campaign recorded with provenance lacks a
    canary of one of its toolchains and modes and is not marked exempt
    (CanaryMissing); the number of canary rows checked (0: a campaign
    recorded without provenance, which has none)."""
    rows = list(rows_or_paths)
    if rows and not isinstance(rows[0], dict):
        rows = rows_of(rows)
    bad = check(rows)
    if bad:
        raise CanaryChanged(f"{what}: {len(bad)} canar"
                            f"{'y' if len(bad) == 1 else 'ies'} changed; the "
                            "report is not written until they are explained "
                            "(catalog/canaries.yaml):\n  " + "\n  ".join(bad))
    if campaign_rows is not None:
        gone = missing(list(campaign_rows), rows)
        if gone:
            raise CanaryMissing(
                f"{what}: {len(gone)} canaries missing; the report is not "
                "written until the campaign runs them or is marked exempt "
                "with a reason (--canaries-exempt):\n  "
                + "\n  ".join(gone[:20]))
    return sum(1 for r in rows if r.get("canary"))


class CanaryMissing(CanaryChanged):
    """A campaign recorded with provenance has no canary of a toolchain,
    mode and kind it ran, and no exemption."""


def exempt(path: Path, reason: str) -> None:
    """Mark a campaign exempt from canaries, with the reason (one row in
    its canaries file)."""
    if not reason.strip():
        raise ValueError("an exemption needs a reason")
    write([{"canary_exempt": reason.strip()}], Path(path))


def write(rows: list[dict], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def add_to_campaign(path: Path, toolchains, modes, timeout_s: int = 120,
                    log=print) -> list[dict]:
    """Run the canaries of every toolchain and mode of a campaign and
    append them to `path` (a campaign runner's last step)."""
    spec = load()
    rows = []
    for t in toolchains:
        if t not in (spec.get("toolchains") or {}):
            raise KeyError(f"canaries: toolchain {t} has none in "
                           "catalog/canaries.yaml (an error)")
        for x in modes:
            rows += run_for(t, x, timeout_s, spec)
    write(rows, path)
    bad = check(rows, spec)
    log(f"canaries: {len(rows)} rows -> {path}"
        + (f"; CHANGED: {'; '.join(bad)}" if bad else "; unchanged"))
    return rows
