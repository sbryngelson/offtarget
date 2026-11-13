#!/usr/bin/env python3
"""Regenerate, or check, every committed generated artifact (order: docs/tooling/regenerate.md).

    python3 -I tools/regenerate.py --list      # the ordered steps
    python3 -I tools/regenerate.py --check     # are the artifacts current?
    python3 -I tools/regenerate.py --offline   # rerun every offline step

``--check`` rebuilds each offline artifact in memory or a temporary directory
from results/ and the committed inputs, and compares it with the stored copy. It
writes nothing. A check with missing inputs (a fresh clone has no results/) is
skipped and says what is missing. Exit 1 when any artifact is stale. Steps that
need a GPU or compute node (measurements, audits, the confirmer batch in
tools/jobs/run_regen_confirm.sh) are listed, not run.
``--offline`` reruns the offline steps in order and does not publish the dashboard."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

R = ROOT / "results"
C = R / "confirm"

# (step, where it runs, command, artifacts) in dependency order
STEPS = [
    ("measure", "GPU node (flux)",
     "tools/jobs/run_matrix_xnack1.sh, run_x0_full.sh, run_copy_subset*.sh; "
     "Tioga run_tioga*.sh; baselines (tools/campaigns/run_matrix.py)",
     "results/matrix*.jsonl, acc_matrix*.jsonl, baseline*.jsonl"),
    ("audits", "GPU node",
     "tools/campaigns/oracle_audit.py, tools/campaigns/map_audit.py (both machines), "
     "tools/campaigns/presence_x1.py",
     "tests/data/*_summary.json"),
    ("expected-runs", "GPU node",
     "tools/derive/expected.py fuzz|catalog (and xnack0-command)",
     "results/expected/*.jsonl"),
    ("expected-report", "offline", "tools/derive/expected.py report",
     "data/reports/expected-sources.md"),
    ("claims", "offline", "tools/derive/claims.py ingest",
     "catalog/vendor_claims_generic.yaml"),
    ("toolchains-gen", "offline", "tools/derive/toolchains_gen.py (from "
     "catalog/toolchains.yaml and machines.yaml)",
     "site/static/toolchains.js, tools/jobs/toolchains.sh, docs/tooling/toolchains.md"),
    ("support-tables", "offline",
     "tools/derive/support_table.py; --lang c; --model acc; --model acc --lang c",
     "results/support_table{,_c}.{md,csv}, results/acc_support_table.*, "
     "data/reports/{c,acc}-support-table.md, data/reports/{c,acc}_support_"
     "table.csv"),
    ("widen-table", "offline (after the widened catalog's GPU runs)",
     "tools/campaigns/widen.py merge; audit-summary; expected; table",
     "results/widen/matrix.jsonl, tests/data/widen_audit_summary*.json, "
     "results/expected/widen*.jsonl, data/reports/widen_support_table.csv, "
     "data/reports/widen-support-table.md"),
    ("fuzz", "GPU node, then offline",
     "tools/campaigns/fuzz.py campaigns, then tools/campaigns/fuzz.py report",
     "results/fuzz/*, data/reports/fuzz-*.md"),
    ("confirm-evidence", "GPU node (and Tioga over ssh)",
     "tools/jobs/run_confirm_shards.sh (confirm batch --run)",
     "results/confirm/shards/*.ev.*.jsonl, results/confirm/evidence.jsonl"),
    ("confirm-batch", "compute node (offline, ~5 min)",
     "tools/jobs/run_regen_confirm.sh (INSTALL=1): confirm batch (full, s1), "
     "confirm decide",
     "results/confirm/batch_full.jsonl, batch_s1.jsonl, "
     "batch_s1.final.jsonl"),
    ("widen-batch", "compute node (offline, a few minutes)",
     "tools/jobs/run_widen_confirm.sh: confirm batch on the widened catalog's "
     "failing cells, stamped",
     "results/confirm/batch_widen.jsonl, batch_widen.stamp.json"),
    ("witness", "offline (the witness_only offload compilers of machines.yaml; none configured)",
     "tools/confirm.py witness  (then confirm-batch again if the witnessed "
     "set changed: the cycle, docs/tooling/regenerate.md)",
     "catalog/legality_witness.yaml"),
    ("index-scope", "offline", "tools/confirm.py index --scope --write",
     "data/findings/index.yaml (modes, arch)"),
    ("backlog", "offline", "tools/confirm.py backlog --write",
     "data/reports/unlinked-bugs.md"),
    ("ompvv-compare", "offline",
     "tools/derive/ompvv_compare.py; --lang c (the corpus pin and the omp_vv index "
     "rows: tools/campaigns/index_corpus.py, checked as ompvv-corpus)",
     "results/ompvv_compare{,_c}.csv, data/index/corpus_index.csv"),
    ("triage", "offline", "tools/confirm.py triage",
     "results/confirm/triage27b.jsonl, data/reports/triage-2026-10.md "
     "(generated block), docs/upstream.md"),
    ("validate", "offline", "tools/confirm.py validate",
     "data/reports/confirm-validation.md"),
    ("dashboard", "offline, then publish",
     "tools/site/dashboard_data.py OUT_DIR; Artifact publish + ArtifactData "
     "update (docs/tooling/dashboard-publish.md)", "the published datasets"),
    ("site-inputs", "offline",
     "tools/site/site_inputs.py (feature support from results/dash/atoms.json, "
     "the published findings' verified citations from the spec cache)",
     "site/inputs/atoms.json.gz, site/inputs/citations.json"),
]


def _tool(name: str):
    path = next(p for a in ("", "dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes") if (p := ROOT / "tools" / a / f"{name}.py").is_file())
    spec = importlib.util.spec_from_file_location(f"_regen_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _missing(*paths: Path) -> list[str]:
    return [str(Path(p).relative_to(ROOT)) for p in paths
            if not Path(p).exists()]


class Skip(Exception):
    pass


def _rel(p) -> str:
    try:
        return str(Path(p).relative_to(ROOT))
    except ValueError:
        return str(p)


def _need(*paths):
    m = _missing(*paths)
    if m:
        raise Skip("missing " + ", ".join(m))


# --- checks: each returns a list of stale things (empty: current) --------

def check_claims() -> list[str]:
    from offload.engine.confirm import claims as CL
    _need(ROOT / "data" / "index" / "claims")
    rep = CL.ingest()
    if rep.problems:
        return [f"claims ingest problems: {rep.problems[:3]}"]
    same = CL.GENERIC.is_file() and CL.load(CL.GENERIC) == rep.claims
    return [] if same else [str(CL.GENERIC.relative_to(ROOT))]


def check_support_tables() -> list[str]:
    from offload.engine import report
    _need(report.MATRIX, report.C_MATRIX, report.ACC_MATRIX)
    out = []
    sets = [
        (report.MATRIX, report.CLAIMS, report.AUDIT, report.BASELINE,
         [R / "support_table.md", R / "support_table.csv"], []),
        (report.C_MATRIX, report.CLAIMS, report.C_AUDIT, report.C_BASELINE,
         [R / "support_table_c.md", R / "support_table_c.csv"],
         [ROOT / "data" / "reports" / "c-support-table.md",
          ROOT / "data" / "reports" / "c_support_table.csv"]),
        (report.ACC_MATRIX, report.ACC_CLAIMS, report.ACC_AUDIT,
         R / "no_acc_baseline.jsonl",
         [R / "acc_support_table.md", R / "acc_support_table.csv"],
         [ROOT / "data" / "reports" / "acc-support-table.md",
          ROOT / "data" / "reports" / "acc_support_table.csv"])]
    if report.ACC_C_MATRIX.is_file():  # The OpenACC C slice
        sets.append((report.ACC_C_MATRIX, report.ACC_CLAIMS,
                     report.ACC_C_AUDIT, R / "no_acc_baseline.jsonl",
                     [R / "acc_support_table_c.md",
                      R / "acc_support_table_c.csv"],
                     [ROOT / "data" / "reports" / "acc-c-support-table.md",
                      ROOT / "data" / "reports" / "acc_c_support_table.csv"]))
    with tempfile.TemporaryDirectory() as d:
        for res, claims, audit, base, stored, committed in sets:
            md, csv = Path(d) / "t.md", Path(d) / "t.csv"
            report.write_report(res, claims, audit, base, md, csv)
            for new, old in zip((md, csv), stored):
                if not old.is_file() or old.read_text() != new.read_text():
                    out.append(str(old.relative_to(ROOT)))
            for new, old in zip((md, csv), committed):
                # the committed Markdown copy's links are one level deeper
                # (tools/derive/support_table.py)
                text = new.read_text()
                if old.suffix == ".md":
                    text = text.replace("](../", "](../../")
                if not old.is_file() or old.read_text() != text:
                    out.append(str(old.relative_to(ROOT)))
    return out


def check_expected_report() -> list[str]:
    ex = _tool("expected")
    _need(ex.OUT / "catalog.jsonl", ex.OUT / "c1.jsonl")
    with tempfile.TemporaryDirectory() as d:
        stored = ex.REPORT
        ex.REPORT = Path(d) / "e.md"
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            ex.cmd_report(argparse.Namespace(run="c1"))
        new = ex.REPORT.read_text()
    return [] if stored.read_text() == new else \
        [str(stored.relative_to(ROOT))]


def _batch(path: Path) -> list[dict]:
    return [json.loads(x) for x in Path(path).read_text().splitlines()
            if x.strip()]


def check_witness() -> list[str]:
    """Every catalog program the batch decides by R12/R12a has a witness
    row for its current source (a stale sha silently turned R12a into R12),
    and no witness row is for an old source."""
    from offload.engine.confirm import programs as P
    from offload.engine.confirm import witness as W
    _need(C / "batch_full.jsonl")
    rows = W._rows()
    out = []
    if not W.checkers():
        # no trusted checker, so no witness
        return [f"legality_witness.yaml: {len(rows)} witness rows but no "
                "independent checker"] if rows else []
    want = {d["case"]["program"]["ident"] for d in _batch(C / "batch_full.jsonl")
            if d["rule"].startswith("R12") and d["rule"] !=
            "R12b-compile-undecided" and
            d["case"]["program"]["kind"] == "catalog"}
    have = {}
    for r in rows:
        have.setdefault(r["program"], set()).add(r["sha256"])
    for pid in sorted(set(want) | set(have)):
        sha = P.catalog_ref(pid).sha
        if pid in want and sha not in have.get(pid, ()):
            out.append(f"legality_witness.yaml: no row for {pid} at its "
                       "current source")
        elif pid in have and sha not in have[pid]:
            out.append(f"legality_witness.yaml: {pid} witnessed at an old "
                       "source")
    return out


def check_index_scope() -> list[str]:
    import yaml
    from offload.engine.confirm import findings as FI
    _need(C / "batch_full.jsonl")
    names = {"data/findings/" + d["file"] for d in yaml.safe_load(
        FI.INDEX.read_text())["findings"]}
    fs = [f for f in FI.load_index() if f.file in names]
    s = FI.derive_scope(list(FI.stored_cells()), fs)
    return [f"data/findings/index.yaml scope of {f.file}" for f in fs
            if (s[f.file]["modes"], s[f.file]["arch"]) !=
            (list(f.modes), list(f.arch))]


def check_backlog() -> list[str]:
    from offload.engine.confirm import backlog as B
    _need(B.BATCH)
    gs = B.groups(B.unlinked())
    data = B.load()
    out = B.check(gs, data)
    if not B.DOC.is_file() or B.DOC.read_text() != B.render(gs, data):
        out.append(str(B.DOC.relative_to(ROOT)))
    return out


def check_decide() -> list[str]:
    from offload.engine.confirm import decisions as DE
    _need(C / "batch_s1.jsonl", C / "batch_s1.final.jsonl")
    out = DE.apply(_batch(C / "batch_s1.jsonl"),
                   DE.load()["decisions"])
    old = _batch(C / "batch_s1.final.jsonl")
    key = [(r["case"]["case_id"], r["final"], r["decided_by"]) for r in out]
    return [] if key == [(r["case"]["case_id"], r["final"], r["decided_by"])
                         for r in old] else \
        ["results/confirm/batch_s1.final.jsonl"]


def check_triage() -> list[str]:
    from offload.engine.confirm import triage as T
    cf = _tool("confirm")
    _need(C / "batch_full.jsonl", R / "support_table.csv")
    items = T.mismatch_items() + T.flag_items()
    T.run(items, cf._ctx(False))
    sample = T.spot_sample(items)
    checks = {s["case_id"]: s for s in T.decisions()["spot_checks"]}
    want = {cid for v in sample.values() for cid in v}
    spot = [checks[c] for c in sorted(want) if c in checks]
    md = T.render_tables(items, sample, {"spot": spot})
    text = cf.TRIAGE_DOC.read_text()
    block = text.split(cf.BEGIN, 1)[-1].split(cf.END, 1)[0]
    out = []
    if block != "\n" + md:
        out.append(str(cf.TRIAGE_DOC.relative_to(ROOT)))
    if cf.UPSTREAM.read_text() != T.render_upstream(items):
        out.append(str(cf.UPSTREAM.relative_to(ROOT)))
    return out


# what the confirmer batch is a function of (besides the stored results and
# evidence, which only GPU runs change): its rules, registry, claims,
# forms, machines, witnesses, expected-value triage, the findings (dedupe)
# and its code; and the omp_vv baselines
BATCH_INPUTS = ("catalog/confirm_rules.yaml", "catalog/rulings.yaml",
                "catalog/vendor_claims_generic.yaml", "catalog/later_forms.yaml",
                "catalog/machines.yaml", "catalog/legality_witness.yaml",
                "catalog/expected_triage.yaml", "catalog/omp/derivations.yaml",
                "data/findings/index.yaml",
                # The omp_vv baselines the batch ingests
                "results/baseline.jsonl", "results/baseline_c.jsonl",
                # The reproduction gate's verdicts (rule R04b)
                # and the legality checks the gate reads
                "results/gate/verdicts.jsonl", "offload/engine/gate.py",
                "offload/engine/prerun.py")
BATCH_GLOBS = ("offload/engine/confirm/*.py", "data/findings/fuzz/*.f90")
STAMP = C / "batch_full.stamp.json"


def batch_inputs_hash(root: Path | None = None, files=None,
                      globs=None) -> str:
    import hashlib
    root = root or ROOT
    files = BATCH_INPUTS if files is None else files
    globs = BATCH_GLOBS if globs is None else globs
    h = hashlib.sha256()
    paths = [root / f for f in files] + sorted(
        p for g in globs for p in root.glob(g))
    for p in paths:
        rel = p.relative_to(root)
        h.update(str(rel).encode() + b"\0")
        if not p.is_file():
            h.update(b"<missing>")
        elif rel.parts[:2] == ("data", "findings") and p.suffix in (".f90", ".c"):
            # the public site's optional block is not an input of the confirmer
            from offload.engine.site.header import strip
            h.update(strip(p.read_text(errors="replace")).encode())
        else:
            h.update(p.read_bytes())
    return h.hexdigest()


def stamp_batch(path: Path | None = None) -> None:
    """Record the inputs hash the installed batch was made with
    (tools/jobs/run_regen_confirm.sh calls this after INSTALL)."""
    path = path or STAMP
    Path(path).write_text(json.dumps({"inputs_sha256": batch_inputs_hash(),
                                      "files": list(BATCH_INPUTS),
                                      "globs": list(BATCH_GLOBS)}) + "\n")


def check_batch(path: Path | None = None) -> list[str]:
    """The confirmer batch was made with the current rules, claims,
    findings and code (its stamp's inputs hash); else rerun
    tools/jobs/run_regen_confirm.sh (a compute node)."""
    _need(C / "batch_full.jsonl")
    path = path or STAMP
    if not Path(path).is_file():
        return ["results/confirm/batch_full.jsonl: no inputs stamp (rerun "
                "tools/jobs/run_regen_confirm.sh with INSTALL=1)"]
    want = json.loads(Path(path).read_text()).get("inputs_sha256")
    return [] if want == batch_inputs_hash() else [
        "results/confirm/batch_full.jsonl: made with other rules, claims, "
        "findings or confirmer code than the current ones (rerun "
        "tools/jobs/run_regen_confirm.sh with INSTALL=1)"]


# The widened catalog's batch (tools/jobs/run_widen_confirm.sh) is a
# function of the full batch's inputs and of the widened matrix and its
# expected values
WIDEN_BATCH_INPUTS = (R / "widen" / "matrix.jsonl",
                      R / "expected" / "widen.jsonl",
                      R / "expected" / "widen.xnack0.jsonl")
WIDEN_STAMP = C / "batch_widen.stamp.json"


def _widen_hash() -> str:
    import hashlib
    h = hashlib.sha256(batch_inputs_hash().encode())
    for p in WIDEN_BATCH_INPUTS:
        h.update(Path(p).read_bytes() if Path(p).is_file() else b"<missing>")
    return h.hexdigest()


def stamp_widen_batch(path: Path | None = None) -> None:
    path = path or WIDEN_STAMP
    Path(path).write_text(json.dumps({"inputs_sha256": _widen_hash()}) +
                          "\n")


def check_widen_batch(path: Path | None = None) -> list[str]:
    """The widened catalog's confirmer batch was made from the current
    matrix, expected values, rules and confirmer code (its stamp)."""
    _need(C / "batch_widen.jsonl")
    path = path or WIDEN_STAMP
    if not Path(path).is_file():
        return ["results/confirm/batch_widen.jsonl: no inputs stamp (rerun "
                "tools/jobs/run_widen_confirm.sh)"]
    want = json.loads(Path(path).read_text()).get("inputs_sha256")
    return [] if want == _widen_hash() else [
        "results/confirm/batch_widen.jsonl: made from another widened "
        "matrix, expected values, rules or confirmer code (rerun "
        "tools/jobs/run_widen_confirm.sh)"]


def check_widen_table() -> list[str]:
    """The widened catalog's audit summaries, support table (CSV
    and Markdown) are those of results/widen/ (tools/campaigns/widen.py
    audit-summary, table)."""
    w = _tool("widen")
    _need(R / "widen" / "matrix.jsonl", R / "widen" / "audit")
    out = []
    rows = w.read_rows(sorted((R / "widen" / "audit").glob("*.jsonl")))
    last = {(r["program_id"], r["toolchain"], r["xnack"], r["mutant"]): r
            for r in rows}
    summ = w.audit_summary(list(last.values()))
    for lang, path in w.AUDIT_SUMMARY.items():
        if not path.is_file() or json.loads(path.read_text()) != summ[lang]:
            out.append(_rel(path))
    if out:
        return out  # the table reads the summaries
    groups = w.table_rows(w.read_rows([R / "widen" / "matrix.jsonl"]))
    for path, text in ((w.TABLE_CSV, w.render_table_csv(groups)),
                       (w.TABLE_MD, w.render_table_md(groups))):
        if not path.is_file() or path.read_text() != text:
            out.append(_rel(path))
    return out


CORPUS_INDEX = ROOT / "data" / "index" / "corpus_index.csv"


def _corpus_head(repo: str) -> str:
    import subprocess
    return subprocess.run(["git", "-C", str(ROOT / "corpus" / repo),
                           "rev-parse", "HEAD"], capture_output=True,
                          text=True, check=True).stdout.strip()


def check_ompvv_corpus() -> list[str]:
    """Corpus/omp_vv is checked out at the pinned upstream commit
    (offload.engine.ompvv.UPSTREAM, docs/tooling/setup.md) and the committed omp_vv rows
    of data/index/corpus_index.csv are those of that checkout (order aside)."""
    import csv
    from offload.engine.ompvv import UPSTREAM
    _need(ROOT / "corpus" / "omp_vv" / ".git")
    out = []
    head = _corpus_head("omp_vv")
    if head != UPSTREAM["commit"]:
        out.append(f"corpus/omp_vv at {head[:12]}, not the pinned "
                   f"{UPSTREAM['commit'][:12]} (docs/tooling/setup.md)")
    ic = _tool("index_corpus")

    def key(r):
        return tuple(str(r[k]) for k in ("repo", "path", "lang", "model",
                                         "kind", "spec_dir", "n_directives",
                                         "directives"))
    new = sorted(key(r) for r in ic.index_repo("omp_vv"))
    with open(CORPUS_INDEX, newline="") as fh:
        old = sorted(key(r) for r in csv.DictReader(fh)
                     if r["repo"] == "omp_vv")
    if new != old:
        out.append(f"{_rel(CORPUS_INDEX)} (omp_vv rows)")
    return out


def check_ompvv_compare() -> list[str]:
    """Results/ompvv_compare{,_c}.csv (tools/derive/ompvv_compare.py) are
    those of the current baselines and support tables."""
    oc = _tool("ompvv_compare")
    out = []
    for lang in ("f90", "c"):
        base, table, stored = oc.PATHS[lang]
        _need(*(p for p in (base, table) if p is not None))
        rows = oc.compare(lang)[0]
        if not Path(stored).is_file() or open(
                stored, newline="").read() != oc.render_csv(rows):
            out.append(_rel(stored))
    return out


def check_toolchains_gen() -> list[str]:
    """The files generated from catalog/toolchains.yaml are current."""
    return [f"{p}: stale (python3 -I tools/derive/toolchains_gen.py)"
            for p in _tool("toolchains_gen").stale()]


def check_site_inputs() -> list[str]:
    """The site's committed inputs (site/inputs/) are those of the current
    atom table and spec cache (tools/site/site_inputs.py); a clean clone builds
    the site from them alone (docs/tooling/publishing.md)."""
    si = _tool("site_inputs")
    _need(si.RAW_ATOMS, si.SPEC_CACHE, si.SPEC)
    return [f"site/inputs/{n}: stale (python3 -I tools/site/site_inputs.py)"
            for n in si.stale()]


CHECKS = [("confirm-batch", check_batch),
          ("claims", check_claims),
          ("toolchains-gen", check_toolchains_gen),
          ("expected-report", check_expected_report),
          ("support-tables", check_support_tables),
          ("decide", check_decide),
          ("witness", check_witness),
          ("index-scope", check_index_scope),
          ("backlog", check_backlog),
          ("ompvv-corpus", check_ompvv_corpus),
          ("ompvv-compare", check_ompvv_compare),
          ("triage", check_triage),
          ("widen-table", check_widen_table),
          ("widen-batch", check_widen_batch),
          ("site-inputs", check_site_inputs)]
NOT_CHECKED = {
    "measure, audits, expected-runs, fuzz, confirm-evidence":
        "GPU runs (the measurements themselves)",
    "confirm-batch (content)": "only its inputs hash is checked; the "
                               "batch itself needs a compute node "
                               "(tools/jobs/run_regen_confirm.sh)",
    "validate": "tests/confirm/test_confirm_outputs.py (no unexplained rows)",
    "dashboard": "not committed; the published datasets "
                 "(docs/tooling/dashboard-publish.md)",
    "site (the pages)": "not committed; built from committed data by "
                        "tools/site_publish.sh (docs/tooling/publishing.md)"}


def run_checks(names=None, log=print) -> dict:
    res = {}
    for name, fn in CHECKS:
        if names and name not in names:
            continue
        try:
            stale = fn()
            res[name] = ("stale", stale) if stale else ("current", [])
        except Skip as e:
            res[name] = ("skipped", [str(e)])
        log(f"{name:16} {res[name][0]:8} {'; '.join(res[name][1])[:400]}")
    for k, why in NOT_CHECKED.items():
        log(f"{k:16} not checked here: {why}")
    return res


def run_offline(log=print) -> None:
    import subprocess
    py = [sys.executable, "-I"]
    cmds = [["tools/derive/expected.py", "report"], ["tools/derive/claims.py", "ingest"],
            ["tools/derive/support_table.py"],
            ["tools/derive/support_table.py", "--lang", "c"],
            ["tools/derive/support_table.py", "--model", "acc"],
            ["tools/derive/support_table.py", "--model", "acc", "--lang", "c"],
            ["tools/campaigns/widen.py", "audit-summary"],
            ["tools/campaigns/widen.py", "table"],
            ["tools/confirm.py", "index", "--scope", "--write"],
            ["tools/confirm.py", "backlog", "--write"],
            ["tools/derive/ompvv_compare.py"],
            ["tools/derive/ompvv_compare.py", "--lang", "c"],
            ["tools/confirm.py", "triage"],
            ["tools/site/site_inputs.py"]]
    for c in cmds:
        log("$ python3 -I " + " ".join(c))
        subprocess.run(py + [str(ROOT / c[0])] + c[1:], cwd=ROOT, check=True)


def main(argv=None) -> int:
    os.environ["OFFLOAD_LOCAL"] = ""      # what is committed comes from the committed catalogs, never from one user's settings
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true")
    g.add_argument("--check", nargs="*", metavar="STEP",
                   help="all checks, or the named ones")
    g.add_argument("--offline", action="store_true")
    g.add_argument("--stamp-batch", action="store_true",
                   help="record the inputs hash of the installed batch")
    g.add_argument("--stamp-widen-batch", action="store_true",
                   help="record the inputs hash of batch_widen.jsonl")
    a = ap.parse_args(argv)
    if a.list:
        for i, (name, where, cmd, arts) in enumerate(STEPS, 1):
            print(f"{i:2}. {name} [{where}]\n    {cmd}\n    -> {arts}")
        return 0
    if a.stamp_batch:
        stamp_batch()
        print(f"{STAMP.relative_to(ROOT)}: {batch_inputs_hash()}")
        return 0
    if a.stamp_widen_batch:
        stamp_widen_batch()
        print(f"{WIDEN_STAMP.relative_to(ROOT)}: {_widen_hash()}")
        return 0
    if a.offline:
        run_offline()
        return 0
    res = run_checks(a.check or None)
    return 1 if any(v[0] == "stale" for v in res.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
