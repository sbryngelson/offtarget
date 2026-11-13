"""Cases from the stored results, and the index of stored rows the
collectors read before running anything.

Sources: results/matrix*.jsonl, acc_matrix*.jsonl, widen/matrix.jsonl
(harness rows; the last is the widened catalog),
baseline*.jsonl (omp_vv, exit code only), results/fuzz/<run>/programs.jsonl
(one record per program, a result per toolchain; the campaign's memory
mode from its meta.json) and files on the command line
(``offload.engine.confirm.programs.file_ref``). Every case and stored row
carries its origin (file and line)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from offload.engine.confirm import machines as M
from offload.engine.confirm import programs as P
from offload.engine.confirm.model import (Case, ProgramRef, outcome_of_baseline,
                                      outcome_of_fuzz, outcome_of_result,
                                      value_of)
from offload.engine.toolchains import TOOLCHAINS, registry as _registry

from offload.engine.root import ROOT  # noqa: E402
RESULTS = ROOT / "results"
FULL_FILES = ("matrix.jsonl", "matrix_c.jsonl", "acc_matrix.jsonl",
              "baseline.jsonl", "baseline_c.jsonl",
              # The widened catalog (tools/campaigns/widen.py merge)
              "widen/matrix.jsonl",
              # The OpenACC C slice (NVHPC)
              "acc_matrix_c.jsonl")


# Rows that are support-table cells only, which the confirmer reads none of:
# the twins named after their machine (afar_mi300x, afar_mi350x; its machines
# are MI300A, MI250X and the A100) and a family under test only (GCC's
# catalog rows; its findings bring their own rows).
TABLE_ONLY = _registry().table_only()


@dataclass(frozen=True)
class Row:
    """One stored cell: what the rules read of it."""
    kind: str             # catalog | ompvv | fuzz
    ident: str
    toolchain: str
    arch: str
    mode: str
    outcome: str
    reason: str = ""
    value: str | None = None
    ran_on_host: int | None = None
    flaky: bool = False
    repeats: int = 1
    legal: bool = True
    origin: str = ""
    host: str = ""
    compiler: str = ""
    extra: dict = field(default_factory=dict, compare=False, hash=False)

    @property
    def cell(self) -> tuple:
        return (self.kind, self.ident, self.toolchain, self.mode)


def _mode(toolchain: str, xnack) -> tuple[str, str]:
    tc = TOOLCHAINS.get(toolchain)
    if tc is None:
        raise KeyError(f"unknown toolchain {toolchain}")
    m = M.load()[tc.machine]
    return tc.arch, m.mode_of_row_key(int(xnack))


def _check_value(text: str) -> str | None:
    import re
    m = re.search(r"check=(pass|fail)", text)
    if m:
        return f"check={m.group(1)}"
    m = re.search(r"checksum=(-?\d+)", text)
    return f"checksum={m.group(1)}" if m else None


def _reread(d: dict) -> tuple[dict, dict]:
    """A stored compile failure read with the current message
    tables (offload.engine.gate.reread: every message, the worst class; a
    rejection followed by a front end's crash is an ICE); (row, the old
    outcome and reason or {})."""
    from offload.engine import gate as G
    old = outcome_of_result(d["outcome"], d.get("reason", ""))
    lang = "c" if d.get("lang") == "c" else "f90"
    got = G.reread(d["toolchain"], old, d.get("reason", ""),
                   G.compile_section(d.get("stderr", "")), lang)
    if got is None:
        return d, {}
    cls, reason = got
    before = {"outcome": old, "reason": d.get("reason", "")}
    d = dict(d)
    d["outcome"] = "harness_error" if cls == "harness_error" else "rejected"
    d["reason"] = reason
    return d, before


def row_of_result(d: dict, origin: str = "") -> Row:
    arch, mode = _mode(d["toolchain"], d["xnack"])
    d, reread = _reread(d)
    value, host = value_of(d.get("stdout", ""))
    outcome = outcome_of_result(d["outcome"], d.get("reason", ""))
    if d.get("reason", "").startswith("error_termination") or \
            d.get("reason", "").startswith("compile_error_termination"):
        value = "error_termination"
    flaky = bool(d.get("flaky"))
    # a flaky row's reason lists every repeat ("; repeats: o: r | ...")
    reps_text = d.get("reason", "").split("; repeats: ", 1)
    repeat_outcomes = tuple(
        (outcome_of_result(p.split(": ", 1)[0], p.partition(": ")[2]),
         _check_value(p))
        for p in reps_text[1].split(" | ")) if flaky and \
        len(reps_text) == 2 else ()
    reps = 1 if outcome in ("rejected", "ice", "harness_error") or \
        d["outcome"] == "accepted_ignored" or \
        "timeout" in d.get("reason", "") else 3
    return Row("catalog", d["program_id"], d["toolchain"], arch, mode,
               outcome, d.get("reason", ""), value, host, flaky, reps,
               bool(d.get("legal", True)), origin,
               compiler=d.get("compiler", ""),
               extra={"needs": tuple(d.get("needs") or ()),
                      "repeat_outcomes": repeat_outcomes,
                      "evidence": d.get("evidence", "construct"),
                      "version": d.get("version", 0),
                      "observable": d.get("observable", True),
                      "scope": d.get("scope", "device"),
                      "stderr_tail": (d.get("stderr") or "")[-600:],
                      **({"reclassified_from": reread} if reread else {})})


def row_of_baseline(d: dict, origin: str = "") -> Row:
    arch, mode = _mode(d["toolchain"], d["xnack"])
    outcome = outcome_of_baseline(d)
    reason = d.get("reason", "")
    if outcome == "rejected" and reason.startswith("compile_failed"):
        # Read from the linker's output, so it gets
        # the catalog rows' link prefix, not a front-end rejection's
        import re as _re
        m = _re.search(r"[^\n]*undefined (?:hidden )?(?:symbol|reference)"
                       r"[^\n]*", d.get("stderr") or "")
        reason = "link_undefined_symbol: " + (m.group(0).strip() if m
                                              else reason)
    return Row("ompvv", d["path"], d["toolchain"], arch, mode, outcome,
               reason,
               "exit=0" if outcome == "correct_on_device" else
               (f"exit={d.get('run_rc')}" if d.get("stage") == "run"
                else None),
               None, False, 1, True, origin, compiler=d.get("compiler", ""),
               extra={"lang": d.get("lang", "f90"),
                      "stderr_tail": (d.get("stderr") or "")[-600:]})


def _fuzz_meta(run_dir: Path) -> dict:
    meta = run_dir / "meta.json"
    if not meta.is_file():
        return {}
    d = json.loads(meta.read_text())
    s = (d.get("sessions") or [d])[0]
    return s


CAMPAIGNS = ROOT / "catalog" / "fuzz_campaigns.yaml"


@lru_cache(maxsize=None)
def campaign_runs() -> dict[str, list[str]]:
    """Campaign -> its run ids (catalog/fuzz_campaigns.yaml): the
    chunks of one campaign (one generator version and base groups, e.g.
    s1-00 .. s1-19 in unified mode and s1x0-00 .. s1x0-04 in copy mode)
    replay the same program for the same seed."""
    import yaml
    if not CAMPAIGNS.is_file():
        return {}
    d = yaml.safe_load(CAMPAIGNS.read_text()) or {}
    if d.get("version") != 1:
        raise ValueError("fuzz campaigns: unknown version")
    return {c: list(v["runs"]) for c, v in (d.get("campaigns") or {}).items()}


def campaigns() -> dict[str, str]:
    """run id -> campaign."""
    return {r: c for c, runs in campaign_runs().items() for r in runs}


def _stored_elision(run_dir: Path) -> dict:
    """seed -> the elision of tools/campaigns/fuzz.py elide (elision.jsonl):
    "checksum=<n>", or "inapplicable: <why>" / "no value: <why>"."""
    path = run_dir / "elision.jsonl"
    out = {}
    if not path.is_file():
        return out
    for ln in path.read_text().splitlines():
        if not ln.strip():
            continue
        r = json.loads(ln)
        if r.get("value") is not None:
            out[r["seed"]] = f"checksum={r['value']}"
        elif not r.get("applicable"):
            out[r["seed"]] = f"inapplicable: {r.get('why', '')}"
        else:
            out[r["seed"]] = f"no value: {r.get('why', '')}"
    return out


def rows_of_fuzz(rec: dict, run: str, xnack: int, origin: str = "",
                 campaign: str | None = None) -> list[Row]:
    out = []
    for tc, r in (rec.get("results") or {}).items():
        if tc not in TOOLCHAINS:
            continue
        arch, mode = _mode(tc, xnack)
        outcome = outcome_of_fuzz(r["cls"], r.get("reason", ""))
        value = (f"checksum={r['checksum']}" if r.get("checksum") is not None
                 else None)
        reps = tuple(
            (outcome_of_fuzz(s.split(": ", 1)[0], s.partition(": ")[2]),
             _check_value(s.partition(": ")[2]))
            for s in (r.get("runs") or []) if isinstance(s, str))
        out.append(Row("fuzz", f"{campaign or run}:{rec['seed']}", tc,
                       arch, mode,
                       outcome, r.get("reason", ""), value,
                       r.get("ran_on_host"), bool(r.get("flaky")),
                       1 + len(r.get("runs") or []), True, origin,
                       extra={"repeat_outcomes": reps,
                              "run": run,
                              # The run's output (the
                              # runtime's own message) for dedupe
                              "stderr_tail": (r.get("output") or "")[-1500:],
                              "host_checksum": r.get("host_checksum"),
                              "expected": rec.get("expected"),
                              "validity": rec.get("validity", "valid"),
                              "elision": rec.get("elision"),
                              "gen_version": rec.get("gen_version"),
                              "base": tuple(rec.get("base") or ()),
                              "check": rec.get("check"),
                              "host_witnesses": tuple(
                                  rec.get("host_witnesses") or ())}))
    return out


def _lines(path: Path):
    with path.open() as f:
        for k, ln in enumerate(f, 1):
            if ln.strip():
                yield k, json.loads(ln)


def load_rows(path: Path) -> list[Row]:
    """Every row of one stored file (a fuzz programs.jsonl included)."""
    path = Path(path)
    rel = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    out: list[Row] = []
    if path.name == "programs.jsonl":
        # offload.engine.fuzz_exec.load applies the campaign's host rechecks
        # (hostcheck.jsonl: validity, elision, host values)
        import dataclasses
        from offload.engine.fuzz_exec import load
        x = _fuzz_meta(path.parent).get("xnack", 1)
        progs, _ = load(path.parent)
        run = path.parent.name
        # A stored elision (elision.jsonl) where the host check
        # recorded none
        elided = _stored_elision(path.parent)
        for pr in progs:
            if pr.check != "ok":
                continue
            d = dataclasses.asdict(pr)
            if not d.get("elision") and pr.seed in elided:
                d["elision"] = elided[pr.seed]
            out += rows_of_fuzz(d, run, x, f"{rel}#seed={pr.seed}",
                                campaigns().get(run))
        return out
    for k, d in _lines(path):
        if d.get("toolchain") not in TOOLCHAINS or d["toolchain"] in TABLE_ONLY:
            continue
        if "status" in d:
            out.append(row_of_baseline(d, f"{rel}:{k}"))
        else:
            out.append(row_of_result(d, f"{rel}:{k}"))
    return out


class Index:
    """Stored rows by cell (kind, ident, toolchain, mode): the evidence
    the collectors read before running anything. Later files override
    earlier ones for the same cell."""

    def __init__(self, rows=()):
        self.by_cell: dict[tuple, Row] = {}
        self.by_ident: dict[tuple, list[Row]] = {}
        self.add(rows)

    def add(self, rows) -> None:
        for r in rows:
            old = self.by_cell.get(r.cell)
            self.by_cell[r.cell] = r
            lst = self.by_ident.setdefault((r.kind, r.ident), [])
            if old is not None:
                lst.remove(old)
            lst.append(r)

    def get(self, kind: str, ident: str, toolchain: str, mode: str
            ) -> Row | None:
        return self.by_cell.get((kind, ident, toolchain, mode))

    def rows_of(self, kind: str, ident: str) -> list[Row]:
        return list(self.by_ident.get((kind, ident), ()))

    def __len__(self) -> int:
        return len(self.by_cell)


@lru_cache(maxsize=None)
def stored_index(include_fuzz: bool = True) -> Index:
    """The full result files and every fuzz campaign (read-only)."""
    idx = Index()
    for name in FULL_FILES:
        p = RESULTS / name
        if p.is_file():
            idx.add(load_rows(p))
    if include_fuzz:
        for p in fuzz_files():
            idx.add(load_rows(p))
    return idx


def fuzz_files(base: Path | None = None) -> list[Path]:
    """Every campaign's programs.jsonl, except the chunks a merged
    campaign directory names in its meta.json `merged_from` (tools/campaigns/fuzz.py merge), which it replaces."""
    base = Path(base) if base else RESULTS / "fuzz"
    merged = set()
    for m in base.glob("*/meta.json"):
        try:
            merged |= set(json.loads(m.read_text()).get("merged_from") or ())
        except ValueError:
            continue
    return [p for p in sorted(base.glob("*/programs.jsonl"))
            if p.parent.name not in merged]


def ref_of_row(row: Row) -> ProgramRef:
    """The program of a stored row (regenerated)."""
    if row.kind == "catalog":
        return P.catalog_ref(row.ident)
    if row.kind == "ompvv":
        return P.ompvv_ref(row.ident)
    run, seed = row.ident.rsplit(":", 1)
    return P.fuzz_ref(run, int(seed), row.extra["gen_version"],
                      row.extra.get("base") or (), row.extra.get("expected"))


def case_of_row(row: Row, ref: ProgramRef | None = None) -> Case:
    tc = TOOLCHAINS[row.toolchain]
    return Case(ref or ref_of_row(row), row.toolchain, tc.machine, row.arch,
                row.mode, row.outcome, row.reason, row.value,
                row.ran_on_host, row.flaky, row.repeats,
                source={"origin": row.origin})


def failing_rows(rows, legal_only: bool = True) -> list[Row]:
    """The rows that are failures (not passing), legal programs only by
    default (an illegal catalog variant tests rejection, not a device
    result)."""
    return [r for r in rows if r.outcome not in
            ("correct_on_device", "unobservable") and
            (r.legal or not legal_only)]
