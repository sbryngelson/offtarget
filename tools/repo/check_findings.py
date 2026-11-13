#!/usr/bin/env python3
"""Check each finding's header claims against the recorded rows (data/findings/AUTHORING.md).

    python3 -I tools/repo/check_findings.py [--mode committed|full] [--summary] [--list] [FINDING...]
    python3 -I tools/repo/check_findings.py --write-baseline      # needs results/ (full mode)

The claims (listed in offload/engine/finding_claims.py): a control is correct on each
compiler it is claimed for, other compilers run the file correctly, the gate ran
in four environments with (c) on another node, and "the same way" means one
signature. ``committed`` mode uses the rows in data/vendor/checks/results-compact
and results-site; ``full`` mode also uses the git-ignored campaign rows a header
names. Without rows a check is skipped with a message.
Claims that existing findings fail are listed in catalog/findings_claims_baseline.yaml.
A violation outside it fails, and so does an entry that no longer holds, so the
file only shrinks. A TODO(human) in the findings, their README or the index
also fails. Exit 1 on any problem."""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
if __name__ == "__main__":      # committed findings are checked against the committed catalogs, not one user's settings
    os.environ["OFFLOAD_LOCAL"] = ""

from offload.engine import finding_claims as C  # noqa: E402
from offload.engine import finding_header as H  # noqa: E402
from offload.engine import finding_rows as R  # noqa: E402
from offload.engine.site import matrix as M  # noqa: E402

FINDINGS = ROOT / "data" / "findings"
BASELINE = ROOT / "catalog" / "findings_claims_baseline.yaml"
EXTRA = (FINDINGS / "LOG.md", FINDINGS / "index.yaml")
SUFFIXES = (".c", ".f90", ".F90")
_HEAD = """# The claims the findings made before tools/repo/check_findings.py existed that no recorded row backs.
# A ratchet: tools/repo/check_findings.py fails on a violation not listed here (a new or edited finding must
# be backed by rows) and on an entry that no longer holds (remove it), so this file only shrinks.
# Do not add entries for new findings: record the rows (tools/new_finding.py writes the lines from them).
# One entry per finding and claim. mode: committed = decided from the committed rows
# (data/vendor/checks/results-compact, results-site); full = needs the git-ignored results/ too.
"""


def detect_mode() -> str:
    """`full` where the git-ignored campaign rows exist (results/ with its Tuolumne-only
    directories; a wingtip lane's results/ holds only a step's inputs), `committed` where only
    the committed rows do, else `none`. COMPLIANT_FINDINGS_MODE overrides."""
    forced = os.environ.get("COMPLIANT_FINDINGS_MODE")
    if forced:
        return forced
    res = ROOT / "results"
    if (res / "archive").is_dir() and (res / "controller").is_dir():
        return "full"
    return "committed" if M.SITE_RESULTS.is_dir() or (M.CHECKS / "results-compact").is_dir() else "none"


mode = detect_mode


def finding_files(findings_dir: Path = FINDINGS) -> list[str]:
    out = []
    for p in sorted(findings_dir.rglob("*")):
        rel = p.relative_to(findings_dir).as_posix()
        if p.suffix in SUFFIXES and p.is_file() and "controls" not in rel.split("/")[:-1]:
            out.append(rel)
    return out


def _index_entries() -> dict:
    data = yaml.safe_load((FINDINGS / "index.yaml").read_text()) or {}
    return {d["file"]: d for d in data.get("findings") or []}


def _toolchains(rel: str, entries: dict, header_text: str) -> tuple:
    if rel in entries:
        return tuple(entries[rel].get("toolchains") or ())
    from offload.engine.confirm import findings as F
    for f in F.index():
        if f.file == f"data/findings/{rel}":
            return tuple(f.toolchains)
    h = H.parse(header_text)
    return tuple(dict.fromkeys(t for m in H.mentions(h.get("fail")) for t in m.tcs))


def collect(rels=None, mode: str | None = None, findings_dir: Path = FINDINGS) -> list[C.Violation]:
    mode = mode or detect_mode()
    if mode == "none":
        return []
    full = mode == "full"
    rows, cases = M._rows(), M._cases()
    entries = _index_entries()
    out = []
    for rel in rels or finding_files(findings_dir):
        text = (findings_dir / rel).read_text(errors="replace")
        ev = R.evidence_for(rel, text, entry=entries.get(rel), rows=rows, cases=cases, full=full,
                            findings_dir=findings_dir)
        out += C.check(rel, text, _toolchains(rel, entries, text), ev)
    return out


def todo_problems(findings_dir: Path = FINDINGS, extra=EXTRA) -> list[str]:
    out = []
    files = [p for p in sorted(Path(findings_dir).rglob("*")) if p.is_file() and p.suffix in SUFFIXES]
    for p in files + [Path(x) for x in extra if Path(x).is_file()]:
        base = findings_dir if findings_dir in p.parents else p.parent
        for n, ln in H.todos(p.read_text(errors="replace")):
            out.append(f"{p.relative_to(base).as_posix()}:{n}: {ln[:120]}")
    return out


# --- the ratchet ---------------------------------------------------------------------

def load_baseline(path: Path = BASELINE) -> list[dict]:
    if not Path(path).is_file():
        return []
    return list((yaml.safe_load(Path(path).read_text()) or {}).get("violations") or [])


def compare(found: list, baseline: list[dict], mode: str) -> tuple[list, list]:
    """(violations not in the baseline, baseline entries that no longer hold). The committed
    mode judges only the entries it can decide."""
    have = {v.key for v in found}
    known = {(e["finding"], e["claim"]) for e in baseline}
    new = [v for v in found if v.key not in known]
    decidable = [e for e in baseline if mode == "full" or e["mode"] == "committed"]
    stale = [e for e in decidable if (e["finding"], e["claim"]) not in have]
    return new, stale


def baseline_entries(full: list, committed: list) -> list[dict]:
    cm = {v.key for v in committed}
    return [{"finding": v.finding, "claim": v.claim, "reason": " ".join(v.reason.split())[:300],
             "mode": "committed" if v.key in cm else "full"}
            for v in sorted(full, key=lambda x: x.key)]


def write_baseline_entries(full: list, committed: list, path: Path = BASELINE) -> list[dict]:
    if any(v.claim.startswith("todo") for v in full):
        raise SystemExit("check_findings: a TODO(human) cannot be baselined: finish the draft")
    es = baseline_entries(full, committed)
    Path(path).write_text(_HEAD + yaml.safe_dump({"violations": es}, sort_keys=False, width=100,
                                                  allow_unicode=True))
    return es


def kind(claim: str) -> str:
    return claim.split(" ", 1)[0]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("findings", nargs="*", help="finding paths under findings (default: all)")
    ap.add_argument("--mode", choices=("committed", "full"))
    ap.add_argument("--summary", action="store_true", help="count the violations by kind")
    ap.add_argument("--list", action="store_true", help="print every violation")
    ap.add_argument("--write-baseline", action="store_true")
    a = ap.parse_args(argv)
    md = a.mode or detect_mode()
    if md == "none":
        print("check_findings: no recorded rows here (no results/ and no committed check rows): skipped")
        return 0
    rels = [Path(x).as_posix().replace("data/findings/", "") for x in a.findings] or None
    found = collect(rels, md)
    todo = todo_problems()
    how = "committed rows and results/" if md == "full" else \
        "committed rows only; claims that need results/ are not decided"
    print(f"check_findings: {md} mode ({how}), {len(rels or finding_files())} findings, "
          f"{len(found)} violations")
    if a.write_baseline:
        if md != "full":
            print("check_findings: --write-baseline needs the full mode (results/)")
            return 1
        es = write_baseline_entries(found, collect(rels, "committed"))
        print(f"wrote {len(es)} entries to {BASELINE.relative_to(ROOT)}: "
              + ", ".join(f"{k} {n}" for k, n in sorted(Counter(kind(e['claim']) for e in es).items())))
        return 0
    base = load_baseline()
    new, stale = compare(found, base, md)
    if rels:
        stale = [e for e in stale if e["finding"] in rels]
    if a.summary:
        for k, n in sorted(Counter(kind(v.claim) for v in found).items()):
            print(f"  {k}: {n}")
    if a.list:
        for v in found:
            print(f"  {v.finding}: {v.claim}: {v.reason}")
    bad = 0
    for v in new:
        print(f"NEW  {v.finding}: {v.claim}: {v.reason}")
        bad += 1
    for e in stale:
        print(f"STALE baseline entry (fixed: remove it) {e['finding']}: {e['claim']}")
        bad += 1
    for t in todo:
        print(f"TODO {t}")
        bad += 1
    print(f"check_findings: {len(found) - len(new)} baselined, {len(new)} new, {len(stale)} stale, "
          f"{len(todo)} unfinished")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
