"""The finding matrix: what each finding's program does on every toolchain,
GPU and memory mode.

Built on the vendor checks (data/vendor/checks): their cases say what
"reproduces" (`symptom`) and what "passes" (`expect`) for each finding, their
result rows hold every run in the four gate environments. A finding the checks
have no case for gets one derived from the findings index (`derive_case`), and
its runs come from the site's own results (results-site/, same format).
"""
from __future__ import annotations

import gzip
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from offload.engine.root import ROOT  # noqa: E402
CHECKS = ROOT / "data" / "vendor" / "checks"
SITE_RESULTS = CHECKS / "results-site"
if str(CHECKS) not in sys.path:
    sys.path.insert(0, str(CHECKS))
import build as B  # noqa: E402  (data/vendor/checks/build.py: classify, verdict)

# The toolchains, their versions and machines come from the catalog
# (catalog/toolchains.yaml, catalog/machines.yaml: offload.engine.toolchains).
from offload.engine.toolchains import REGRESSION_TOOLCHAINS as _REGRESSION  # noqa: E402
from offload.engine.toolchains import registry as _registry  # noqa: E402
from offload.engine.confirm.machines import load as _machines  # noqa: E402
_R = _registry()
# toolchain -> (family, version label, order within the family); the site's toolchains
# are every one that is not an arch twin (cells are keyed by machine)
VERSIONS = _R.versions()
TOOLCHAINS = tuple(VERSIONS)
# (machine, mode) -> target (machines.yaml modes.<mode>.target)
TARGETS = _R.targets()
# machines the site plans no runs on (machines.yaml site_plan_runs: false; Tioga: no batch
# queue for this account, pdebug is interactive only); their cells without runs stay unknown
UNRUN_MACHINES = tuple(m.name for m in _machines().values() if not m.site_plan_runs)
# ... except the toolchains whose runs are planned anyway (catalog site_plan_runs: GCC's MI250X
# cells, run in supervised interactive pdebug jobs: GCC has no other AMD GPU here)
RUN_ANYWAY = {n for n, t in _R.toolchains.items() if t.site_plan_runs}
# toolchains that have only some targets of their kind (catalog site_targets: GCC runs separate
# memory only, no unified or managed cells, and each GCC install targets one GPU)
ONLY_TARGETS = {n: set(t.site_targets) for n, t in _R.toolchains.items() if t.site_targets}
_MACHINE = {n: _R.arches[_R.toolchains[n].arch]["gpu"] for n in TOOLCHAINS}
_KIND = _R.target_kinds()


@dataclass(frozen=True)
class Cell:
    tc: str
    version: str
    target: str
    state: str          # fails-like | fails-differently | correct | unknown | na
    outcome: str = ""   # the observation's stage (RUN_OK, COMPILE_FAIL, ...)
    message: str = ""   # scrubbed first lines of the failing output
    output: str = ""    # scrubbed output of a run
    envs: int = 0       # environments whose runs agree on the state
    reason: str = ""    # why the cell is unknown or n/a


def _rows() -> list[dict]:
    out = []
    for ln in B.result_lines(source="compact"):
        r = json.loads(ln)
        if "obs" in r and "machine" in r:
            out.append(r)
    for f in sorted(SITE_RESULTS.glob("*.jsonl.gz")) if SITE_RESULTS.is_dir() else []:
        with gzip.open(f, "rt") as fh:
            out += [json.loads(x) for x in fh if x.strip()]
    return out


def _cases() -> list[dict]:
    out = json.loads((CHECKS / "cases.json").read_text())
    site = CHECKS / "cases-site.json"
    if site.is_file():
        out += json.loads(site.read_text())
    return out


def derive_case(entry: dict) -> dict:
    """A check case for a findings-index entry the vendor checks do not cover."""
    oc = entry.get("outcome", "")
    symptom = {"wrong_answer": "wrong", "rejected": "compile:.", "ice": "compile:.",
               "crash": "crash:", "run_error": "crash:", "timeout": "runhang"}.get(oc, "wrong")
    exp = entry.get("expected")
    stem = entry["file"].rsplit(".", 1)[0]
    return {"id": "site-" + stem.replace("/", "--"), "finding": entry["file"], "symptom": symptom,
            "expect": f"out:{exp}" if exp else "ok",  # a run that completes counts as correct only
            # when the program's own check passes, whatever the finding's outcome
            "lang": entry.get("lang", "f90"), "model": "acc" if "acc" in Path(stem).name.split("-")
            else "omp", "affected": list(entry.get("toolchains", [])), "repro": entry["file"],
            "derived": True}


def case_for(finding_id: str, cases: list[dict]) -> dict | None:
    stem = finding_id.rsplit("/", 1)[-1]
    mine = [c for c in cases if c["finding"].rsplit(".", 1)[0] == finding_id]
    return next((c for c in mine if c["id"] == stem), mine[0] if mine else None)


def _applicable(case: dict, tc: str, target: str) -> bool:
    """A toolchain of the target's GPU kind, one of the toolchain's targets, whose family
    compiles the case's model (AFAR has no OpenACC)."""
    return _MACHINE[tc] == _KIND[target] \
        and _R.toolchains[tc].family.supports_model(case.get("model") or "omp") \
        and target in ONLY_TARGETS.get(tc, {target})


_MODE_OF = {t: mode for (_, mode), t in TARGETS.items()}


def _affected_modes(case: dict) -> dict:
    """toolchain -> the modes a case was written for (None: every mode). Vendor cases may
    name the mode the finding was seen in ("afar@1"); a regression release goes with its
    headline toolchain (CCE 21.0.4 with 21.0.3), and a twin with the toolchain it is the
    twin of (GCC's MI250X install, gcc_g90, with gcc)."""
    out: dict = {}
    for a in case.get("affected") or []:
        tc, _, mode = a.partition("@")
        if not mode or out.get(tc, set()) is None:
            out[tc] = None
        else:
            out.setdefault(tc, set()).add(mode)
    for reg, head in _REGRESSION.items():
        if head in out:
            out[reg] = out[head]
    for twin, base in _R.twins().items():     # a finding measured on a twin (gcc_g90) is its base's
        if twin in out and base not in out:
            out[base] = out[twin]
    return out


def _affected(case: dict) -> set:
    """The toolchains a case was written for, in any mode."""
    return set(_affected_modes(case))


def _is_affected(case: dict, tc: str, target: str) -> bool:
    modes = _affected_modes(case)
    return tc in modes and (modes[tc] is None or _MODE_OF[target] in modes[tc])


# The failure signature: the vendor checks' symptoms were written for the
# compilers a finding affects, and many are broad ("compile:.", bare "wrong"). On any
# other toolchain a failure counts as this issue only when its signature, outcome class
# plus normalized first diagnostic, or for a run the self-check line with its values, is one the
# affected toolchains show.
_ICE = re.compile(r"internal compiler error|\bINTERNAL\b|Segmentation fault|PLEASE submit|Stack dump|"
                  r"LLVM ERROR|error in backend|Assertion .* failed|signal \d", re.I)
_LINK = re.compile(r"undefined (?:symbol|reference)|\bld(?:\.lld)?:|\blld:|nvlink", re.I)
_DIAG = re.compile(r"error|-[SF]-|fatal|internal|undefined|abort", re.I)
# NVFORTRAN's per-unit count line ("0 inform, 2 warnings, 0 severes, 0 fatal for p") names no diagnostic
_NOT_DIAG = re.compile(r"^\s*\d+ inform,\s*\d+ warnings?,", re.I)
_NUM = re.compile(r"0x[0-9a-fA-F]+|[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?")
# a token holding a source file name without a directory (the check case's copy of the program,
# which the scrub leaves: `site-x--demo.c:3:7:`, NVFORTRAN's `(site-x--demo.f90: 12)`); a token
# holding a path is dropped below, so the two spellings of one diagnostic are one signature
_BARE_FILE = re.compile(r"\S*\b[\w+-]+\.(?:c|h|cc|cpp|f|f90|f95|f03|f08)\b\S*", re.I)


def _norm(line: str) -> str:
    line = re.sub(r"\S*/\S*", "", B.scrub(line))
    line = _BARE_FILE.sub("", line)
    return " ".join(_NUM.sub("", line).lower().split())[:120]


def signature(obs: str) -> tuple[str, str]:
    stage = obs.split(" ", 1)[0].split("\n", 1)[0]
    lines = [x for x in (obs.split("\n", 1)[1] if "\n" in obs else "").splitlines() if x.strip()]
    body = "\n".join(lines)
    if stage == "COMPILE_FAIL":
        cls = "ice" if _ICE.search(body) else "link" if _LINK.search(body) else "reject"
        return cls, _norm(next((x for x in lines if _DIAG.search(x) and not _NOT_DIAG.match(x)),
                               lines[0] if lines else ""))
    if stage == "RUN_FAIL" and re.search(r"^RUN_FAIL rc=-?\d+ signal=", obs):
        return "crash", _norm(lines[0] if lines else "")
    if stage in ("RUN_OK", "RUN_FAIL"):
        # the self-check line with its values: a different wrong value is a different
        # failure (GCC: a wrapped sum and another wrong sum are not one issue)
        checks = [x for x in lines if "=" in x]
        return "wrong", " ".join(B.scrub(checks[-1]).lower().split())[:120] if checks else ""
    return stage.lower(), ""


_INDEXED: list = [None, 0, {}]    # [the rows list last indexed, its length, its rows by case id]


def _of_case(rows: list[dict], case_id: str) -> list[dict]:
    """The rows of one case; the rows list is indexed once, not scanned for every cell."""
    if _INDEXED[0] is not rows or _INDEXED[1] != len(rows):
        index: dict = {}
        for r in rows:
            index.setdefault(r["case"], []).append(r)
        _INDEXED[:] = [rows, len(rows), index]
    return _INDEXED[2].get(case_id, [])


def _references(case: dict, rows: list[dict]) -> set:
    aff = _affected(case)
    return {signature(r["obs"]) for r in _of_case(rows, case["id"]) if r["tc"] in aff
            and r.get("variant", "repro") == "repro" and B.classify(case, r["obs"]) == "R"}


def _cell(case: dict, tc: str, target: str, rows: list[dict], variant: str = "repro",
          refs: set | None = None) -> Cell:
    """`refs`: the affected toolchains' failure signatures; None trusts the symptom."""
    fam, ver, _ = VERSIONS[tc]
    if not _applicable(case, tc, target):
        return Cell(tc, ver, target, "na", reason="not applicable")
    mine = [r for r in _of_case(rows, case["id"]) if r["tc"] == tc and r.get("variant", "repro") == variant
            and TARGETS.get((r["machine"], str(r.get("mode")))) == target]
    if not mine:
        return Cell(tc, ver, target, "unknown", reason="not run")
    per = {}
    for r in mine:
        per.setdefault(r["env"], []).append(B.classify(case, r["obs"], variant))
    classes = {c for v in per.values() for c in v if c not in ("NA", "H")}
    if not classes:
        na = all(c == "NA" for v in per.values() for c in v)
        return Cell(tc, ver, target, "na" if na else "unknown", reason="not applicable" if na else "no result")
    first = next(r for r in mine if B.classify(case, r["obs"], variant) in classes)
    stage, lines = _outline(first["obs"])
    if len(classes) > 1:
        v = B.verdict(per)
        why = "varies between runs" if v == "nondeterministic" else "varies between environments"
        return Cell(tc, ver, target, "unknown", stage, reason=why)
    (c,) = classes
    envs = sum(1 for e, v in per.items() if c in v)
    state = {"R": "fails-like", "P": "correct", "X": "fails-differently"}[c]
    if state == "fails-like" and refs is not None and tc not in _affected(case):
        if not refs:
            return Cell(tc, ver, target, "unknown", stage, "\n".join(lines),
                        reason="fails, but no run of an affected compiler to compare with")
        if signature(first["obs"]) not in refs:
            state = "fails-differently"
    return Cell(tc, ver, target, state, stage, "\n".join(lines) if c != "P" else "",
                "\n".join(lines) if stage.startswith("RUN") else "", envs)


def _outline(obs: str) -> tuple[str, list[str]]:
    stage = obs.split(" ", 1)[0].split("\n", 1)[0]
    body = obs.split("\n", 1)[1] if "\n" in obs else ""
    return stage, [B.scrub(x)[:200] for x in body.splitlines() if x.strip()][:8]


def _case(finding_id: str, cases: list[dict], entry: dict | None) -> dict | None:
    """The finding's check case; one derived from its index entry when no case covers it."""
    case = case_for(finding_id, cases)
    return case if case is not None or entry is None else derive_case(entry)


def cells(finding_id: str, rows: list | None = None, cases: list | None = None,
          entry: dict | None = None) -> list[Cell]:
    cases = _cases() if cases is None else cases
    rows = _rows() if rows is None else rows
    case = _case(finding_id, cases, entry)
    if case is None:
        return []
    refs = _references(case, rows)
    return [_cell(case, tc, t, rows, refs=refs) for tc in TOOLCHAINS for t in TARGETS.values()]


def controls(finding_id: str, rows: list | None = None, cases: list | None = None) -> list[Cell]:
    cases = _cases() if cases is None else cases
    rows = _rows() if rows is None else rows
    case = case_for(finding_id, cases)
    if case is None or not case.get("control"):
        return []
    return [_cell(case, tc, t, rows, "control") for tc in TOOLCHAINS for t in TARGETS.values()]


def status_by_family(finding_id: str, rows: list | None = None, cases: list | None = None,
                     entry: dict | None = None) -> dict:
    """family -> (status, version): open | fixed | changed | not-reproduced | not-run, for the
    families where the finding fails or that its case was written for.
    Fixed in X: correct on X wherever the last failing version failed."""
    cases = _cases() if cases is None else cases
    case = _case(finding_id, cases, entry)
    by_fam: dict = {}
    for c in cells(finding_id, rows, cases, entry):
        fam, _, order = VERSIONS[c.tc]
        by_fam.setdefault(fam, {}).setdefault(order, []).append(c)
    out = {}
    for fam, versions in by_fam.items():
        failing = [o for o, xs in versions.items() if any(x.state == "fails-like" for x in xs)]
        if not failing:
            mine = [x for xs in versions.values() for x in xs if case and _is_affected(case, x.tc, x.target)]
            if mine:
                decided = any(x.state in ("correct", "fails-differently") for x in mine)
                out[fam] = ("not-reproduced" if decided else "not-run", None)
            continue
        last = max(failing)
        bad = {x.target for x in versions[last] if x.state == "fails-like"}
        later = [(versions[o][0].version, {x.target: x.state for x in versions[o]})
                 for o in sorted(o for o in versions if o > last)]
        # changed in X: the first later version that fails another way where the issue
        # failed; else fixed in X: the first later version correct on all those targets
        changed = next((v for v, at in later if any(at.get(t) == "fails-differently" for t in bad)), None)
        fixed = next((v for v, at in later if all(at.get(t) == "correct" for t in bad)), None)
        out[fam] = ("changed", changed) if changed else ("fixed", fixed) if fixed else ("open", None)
    return out


STATUS_ORDER = ("open", "changed", "fixed", "not-reproduced", "not-run")


def status(finding_id: str, rows: list | None = None, cases: list | None = None,
           header=None, entry: dict | None = None) -> tuple[str, str | None]:
    """The finding's status over all families (the most open), or mixed from its header."""
    if header is not None and header.disposition and header.disposition[0] == "mixed":
        return ("mixed", None)
    by = status_by_family(finding_id, rows, cases, entry)
    for s in STATUS_ORDER:
        hit = [v for v in by.values() if v[0] == s]
        if hit:
            return hit[0]
    return ("not-run", None)


# the vendors with a packet (catalog families' vendor; GCC has none)
_VENDOR = {n: _R.toolchains[n].family.vendor for n in TOOLCHAINS
           if _R.toolchains[n].family.vendor}


def site_cases(entries: list[dict], existing: list[dict], headers: dict,
               controls: frozenset | set = frozenset()) -> list[dict]:
    """Derived cases for the index entries no vendor-check case covers, leaving
    out findings the site never publishes (hide, not-a-compiler-issue, out-of-scope).
    Every finding is run everywhere: AMD (gfx942, gfx90a) and NVIDIA (sm_80).
    `controls`: the findings (index paths) whose header control is run as well. A control claimed
    in a header counts as backed only by a recorded row (offload/engine/finding_rows.py), so a finding
    gets its control in the case when those runs are made, not before."""
    covered = {c["finding"] for c in existing}
    out = []
    for e in entries:
        if e["file"] in covered:
            continue
        h = headers.get(e["file"])
        if h is not None and (h.hide or (h.disposition and h.disposition[0] != "mixed")):
            continue
        c = derive_case(e)
        c["repro"] = "../../findings/" + e["file"]
        if e["file"] in controls and h is not None and h.controls:   # the header's first control
            c["control"] = "../../findings/" + h.controls[0][0]
            c["control_what"] = h.controls[0][1]
        if h is not None and h.devices:   # the header's `devices: all TC...`: no GPU pinning there
            c["devices"] = {t: "all" for t in h.devices}
        c["arch"] = ["gfx942", "gfx90a", "sm_80"]
        c["vendor"] = sorted(set(_VENDOR.values()))
        c["modes"] = [1, 0]
        out.append(c)
    return out


def pack(raw_files: list[Path], out: Path) -> None:
    """The site's raw run rows as committed compact rows (results-site/), as the
    vendor checks' pack does: no compile log, host or build directory; text scrubbed
    with the site's scrub (it also covers the /tmp/<user>_site build directories), and a
    row that still identifies a user, host or path is refused."""
    from offload.engine.site import scrub as S
    out.mkdir(parents=True, exist_ok=True)
    for f in raw_files:
        rows = []
        for ln in Path(f).read_text().splitlines():
            if not ln.strip():
                continue
            r = json.loads(ln)
            for k in ("compile_log", "host", "build_dir"):
                r.pop(k, None)
            for k in ("obs", "cmd", "os"):
                if isinstance(r.get(k), str):
                    r[k] = S.scrub(r[k])
            line = json.dumps(r, sort_keys=True)
            if S.leaks(line):
                raise ValueError(f"{f}: still identifies a user, host or path after scrubbing: "
                                 f"{sorted(set(S.leaks(line)))[:5]}")
            rows.append(line)
        dest = out / (Path(f).name + ".gz")
        rows = _kept_rows(dest, rows) + rows
        with open(dest, "wb") as raw_fh, \
                gzip.GzipFile(filename="", mode="wb", fileobj=raw_fh, mtime=0) as fh:
            fh.write(("\n".join(rows) + "\n").encode())


def _run_key(line: str) -> tuple:
    r = json.loads(line)
    return (r.get("case"), r.get("tc"), r.get("machine"), str(r.get("mode")),
            r.get("variant", "repro"), r.get("env"))


def _kept_rows(dest: Path, new_lines: list[str]) -> list[str]:
    """The committed rows a repack must not lose: the raw file may hold only the newest
    runs. A key the raw file has is replaced wholesale (its repeat runs are all in it);
    every other committed row stays."""
    if not dest.is_file():
        return []
    fresh = {_run_key(x) for x in new_lines}
    # a harness error has no mode: any newer run of its case, toolchain, machine, variant and env supersedes it
    real = {_run_key(x)[:3] + _run_key(x)[4:] for x in new_lines
            if not json.loads(x).get("obs", "").startswith("HARNESS_ERROR")}
    with gzip.open(dest, "rt") as fh:
        return [x for x in fh.read().splitlines()
                if x.strip() and _run_key(x) not in fresh
                and not (json.loads(x).get("obs", "").startswith("HARNESS_ERROR")
                         and _run_key(x)[:3] + _run_key(x)[4:] in real)]


def plan(finding_ids: list[str], rows: list | None = None, cases: list | None = None) -> list[dict]:
    """The (case, tc, machine, mode, variant) runs still missing for the findings."""
    cases = _cases() if cases is None else cases
    rows = _rows() if rows is None else rows
    have = {(r["case"], r["tc"], r["machine"], str(r.get("mode")), r.get("variant", "repro")) for r in rows}
    todo = []
    for fid in finding_ids:
        case = case_for(fid, cases)
        if case is None:
            continue
        variants = ["repro"] + (["control"] if case.get("control") else [])
        affected = set(case.get("affected") or [])
        for tc in TOOLCHAINS:
            for (mach, mode), t in TARGETS.items():
                if not _applicable(case, tc, t) or (mach in UNRUN_MACHINES and tc not in RUN_ANYWAY):
                    continue
                for v in variants:
                    if v == "control" and tc not in affected and \
                            _REGRESSION.get(tc) not in affected:
                        continue   # a control is evidence only on a compiler the finding affects
                    if (case["id"], tc, mach, mode, v) not in have:
                        todo.append({"case": case["id"], "tc": tc, "machine": mach, "mode": mode, "variant": v})
    return todo
