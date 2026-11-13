#!/usr/bin/env python3
"""The widened catalog (offload.engine.widen): list, check, run, audit, expected values, support table.

    python3 -I tools/campaigns/widen.py list      # counts by family
    python3 -I tools/campaigns/widen.py check     # legality checkers
    python3 -I tools/campaigns/widen.py run --toolchains afar cce19 cce20 cce21 \\
        --xnack 1 0 --out results/widen/raw/amd.jsonl --workers 16   # GPU node
    python3 -I tools/campaigns/widen.py merge     # raw/*.jsonl -> matrix.jsonl
    python3 -I tools/campaigns/widen.py audit --toolchains afar cce19 \\
        --out results/widen/audit/amd.jsonl   # oracle mutants, copy mode
    python3 -I tools/campaigns/widen.py expected  # results/expected/widen.jsonl
    python3 -I tools/campaigns/widen.py table     # the support table

Results go to results/widen/ (git-ignored). Committed outputs:
data/reports/widen_support_table.csv, data/reports/widen-support-table.md and
tests/data/widen_audit_summary.json."""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine import widen as W  # noqa: E402

OUT = ROOT / "results" / "widen"


def _select(a) -> list:
    ws = list(W.all_wide())
    if getattr(a, "lang", None):
        ws = [w for w in ws if (w.program.lang == "c") == (a.lang == "c")]
    if getattr(a, "model", None):
        ws = [w for w in ws if w.program.model == a.model]
    if getattr(a, "only", None):
        keep = set(a.only)
        ws = [w for w in ws if w.id in keep]
    return ws


def cmd_list(a) -> int:
    c = Counter((w.program.model, "c" if w.program.lang == "c" else "f90",
                 W.kind_of(w.program.primary_atom)) for w in _select(a))
    for k, v in sorted(c.items()):
        print(*k, v)
    print("total", sum(c.values()))
    return 0


def cmd_check(a) -> int:
    ws = _select(a)
    with ThreadPoolExecutor(a.workers) as ex:
        res = list(ex.map(lambda w: (w.id, W.static_problems(w.program)), ws))
    bad = [(i, p) for i, p in res if p]
    for i, p in bad:
        print(i, "; ".join(p))
    print(f"{len(ws) - len(bad)} of {len(ws)} legal by the checkers")
    return 1 if bad else 0


def _done(out: Path) -> set:
    done = set()
    if out.is_file():
        for ln in out.read_text().splitlines():
            if ln.strip():
                try:
                    d = json.loads(ln)
                except ValueError:
                    continue
                done.add((d["program_id"], d["toolchain"], d["xnack"]))
    return done


def cells(ws, toolchains, xnacks) -> list:
    """(program, toolchain, xnack) of the widened programs: OpenACC only on
    a toolchain that compiles it (AFAR has no OpenACC)."""
    from offload.engine.toolchains import TOOLCHAINS
    out = []
    for w in ws:
        for t in toolchains:
            tc = TOOLCHAINS[t]
            if w.program.model == "acc" and tc.kind == "afar":
                continue
            for x in xnacks:
                out.append((w.program, t, x))
    return out


def cmd_run(a) -> int:
    from offload.engine.harness import run_program
    from offload.engine.run_matrix import _error_result, for_version
    from offload.engine.toolchains import TOOLCHAINS
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = _done(out) if a.resume else set()
    if not a.resume:
        out.write_text("")
    todo = [c for c in cells(_select(a), a.toolchains, a.xnack)
            if (c[0].id, c[1], c[2]) not in done]
    lock = threading.Lock()
    n = [0]
    t0 = time.time()

    def job(cell):
        p, t, x = cell
        v = W.VERSION[p.model]
        tc = for_version(TOOLCHAINS[t], v, "c" if p.lang == "c" else "f90"
                         ).for_mode(x)
        try:
            r = run_program(p, tc, x, "-O2", timeout_s=a.timeout,
                            repeats=a.repeats)
        except Exception as err:  # noqa: BLE001 - one cell, keep going
            r = _error_result(p, tc, x, "-O2", v, err)
        line = json.dumps(dataclasses.asdict(r)) + "\n"
        with lock:
            with out.open("a") as f:
                f.write(line)
            n[0] += 1
            print(f"{n[0]}/{len(todo)} {p.id} {t} x{x}: {r.outcome} "
                  f"({time.time() - t0:.0f} s)", flush=True)

    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
        list(ex.map(job, todo))
    # The canaries (offload.engine.canary), next to the output; an
    # exemption needs its reason
    from offload.engine import canary
    cpath = out.with_name(out.name.replace(".jsonl", "") + ".canaries.jsonl")
    if a.canaries_exempt:
        canary.exempt(cpath, a.canaries_exempt)
    else:
        canary.add_to_campaign(cpath, a.toolchains, a.xnack, a.timeout)
    return 0


def read_rows(paths) -> list[dict]:
    rows = []
    for p in paths:
        for ln in Path(p).read_text().splitlines():
            if ln.strip():
                rows.append(json.loads(ln))
    return rows


def cmd_merge(a) -> int:
    """results/widen/raw/*.jsonl -> results/widen/matrix.jsonl: the last
    row of each (program, toolchain, HSA_XNACK) in file-name order, rows of
    programs no longer generated dropped."""
    raw = sorted((OUT / "raw").glob("*.jsonl"))
    ids = {w.id for w in W.all_wide()}
    best = {}
    for r in read_rows(raw):
        if r["program_id"] in ids:
            best[(r["program_id"], r["toolchain"], r["xnack"])] = r
    out = OUT / "matrix.jsonl"
    out.write_text("".join(json.dumps(best[k]) + "\n" for k in sorted(best)))
    c = Counter(r["outcome"] for r in best.values())
    print(f"{len(best)} rows from {len(raw)} files -> {out}: {dict(c)}")
    return 0


def _mutants(w) -> list[tuple[str, object]]:
    """(kind, Program) of a widened program's mutants: the oracle mutant
    (the feature's effect removed: offload.engine.widen) and the map mutants
    of offload.engine.mutate (weaken map types, swap to/from, drop maps or
    target update)."""
    from offload.engine.mutate import map_mutants
    out = []
    if w.mutant_source:
        out.append(("oracle", dataclasses.replace(
            w.program, id=w.id + "-mutant", source=w.mutant_source)))
    for kind, mp in sorted(map_mutants(w.program).items()):
        out.append((f"map-{kind}", mp))
    return out


def cmd_audit(a) -> int:
    """Original and every mutant of each program on each toolchain, one
    repeat, in each mode of --xnack (default copy mode, as the catalog's
    audits); one JSONL row per (program, toolchain, mode, mutant)."""
    from offload.engine.harness import run_program
    from offload.engine.mutate import classify
    from offload.engine.run_matrix import for_version
    from offload.engine.toolchains import TOOLCHAINS
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if a.resume and out.is_file():
        for ln in out.read_text().splitlines():
            if ln.strip():
                d = json.loads(ln)
                done.add((d["program_id"], d["toolchain"], d["xnack"]))
    elif out.is_file():
        out.write_text("")
    todo = [c for c in cells(_select(a), a.toolchains, a.xnack)
            if (c[0].id, c[1], c[2]) not in done]
    by_id = W.by_id()
    lock = threading.Lock()
    n = [0]
    t0 = time.time()

    def job(cell):
        p, t, x = cell
        w = by_id[p.id]
        tc = for_version(TOOLCHAINS[t], W.VERSION[p.model],
                         "c" if p.lang == "c" else "f90").for_mode(x)
        orig = run_program(p, tc, x, "-O2", timeout_s=a.timeout, repeats=1)
        rows = []
        for kind, mp in _mutants(w):
            mut = run_program(mp, tc, x, "-O2", timeout_s=a.timeout,
                              repeats=1)
            st, why, kk = classify(orig, mut)
            rows.append({"program_id": p.id, "primary_atom": p.primary_atom,
                         "version": W.VERSION[p.model], "model": p.model,
                         "lang": "c" if p.lang == "c" else "f90",
                         "toolchain": t, "xnack": x, "mutant": kind,
                         "status": st, "original": str(orig.outcome.value
                                                       if hasattr(orig.outcome, "value")
                                                       else orig.outcome),
                         "mutant_outcome": str(mut.outcome.value
                                               if hasattr(mut.outcome, "value")
                                               else mut.outcome),
                         "reason": why[:300], "kill_kind": kk,
                         "device_only": w.spec.mutant_device})
        with lock:
            with out.open("a") as f:
                for r in rows:
                    f.write(json.dumps(r) + "\n")
            n[0] += 1
            print(f"{n[0]}/{len(todo)} {p.id} {t} x{x}: " + ", ".join(
                f"{r['mutant']}={r['status']}" for r in rows) +
                f" ({time.time() - t0:.0f} s)", flush=True)

    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
        list(ex.map(job, todo))
    return 0


# --- audit summary -----------------------------------------------------------------

AUDIT_SUMMARY = {"f90": ROOT / "tests" / "data" / "widen_audit_summary.json",
                 "c": ROOT / "tests" / "data" / "widen_audit_summary_c.json"}


def audit_summary(rows: list[dict]) -> dict:
    """Per language, version and primary atom: the oracle mutant's status
    per toolchain and mode, the map mutants' statuses, and the program's
    disposition (offload.engine.mutate.DISPOSITIONS: valid = the oracle mutant
    killed on at least one toolchain, weak = it survived wherever the
    result was conclusive, unaudited_no_passing_original = no toolchain
    passed the original, unknown otherwise)."""
    from offload.engine.mutate import DISPOSITIONS
    out = {lang: {"generated_by": "python3 -I tools/campaigns/widen.py audit-summary",
                  "dispositions": {k: DISPOSITIONS[k] for k in (
                      "valid", "weak", "unaudited_no_passing_original")},
                  "versions": {}} for lang in AUDIT_SUMMARY}
    progs = {w.id: w for w in W.all_wide()}
    by: dict = {}
    for r in rows:
        if r["program_id"] in progs:
            by.setdefault(r["program_id"], []).append(r)
    for pid, w in sorted(progs.items()):
        p = w.program
        lang = "c" if p.lang == "c" else "f90"
        rs = by.get(pid, [])
        orc = [r for r in rs if r["mutant"] == "oracle"]
        per = {f"{r['toolchain']}|{r['xnack']}": r["status"] for r in orc}
        sts = [r["status"] for r in orc]
        if "killed" in sts:
            disp = "valid"
        elif "survived" in sts:
            disp = "weak"
        elif orc and not any(r["original"] == "correct_on_device"
                             for r in orc):
            disp = "unaudited_no_passing_original"
        else:
            disp = "unknown" if orc else "missing"
        maps: dict = {}
        for r in rs:
            if r["mutant"].startswith("map-"):
                maps.setdefault(r["mutant"][4:], {})[
                    f"{r['toolchain']}|{r['xnack']}"] = r["status"]
        out[lang]["versions"].setdefault(str(W.VERSION[p.model]), {})[
            p.primary_atom] = {"program": pid, "disposition": disp,
                               "oracle": per, "map": maps,
                               "device_only": w.spec.mutant_device}
    return out


def cmd_audit_summary(a) -> int:
    rows = read_rows(sorted((OUT / "audit").glob("*.jsonl")))
    # a later file (a rerun) replaces a row of the same program,
    # toolchain, mode and mutant
    last = {(r["program_id"], r["toolchain"], r["xnack"], r["mutant"]): r
            for r in rows}
    summ = audit_summary(list(last.values()))
    for lang, path in AUDIT_SUMMARY.items():
        path.write_text(json.dumps(summ[lang], indent=1, sort_keys=True)
                        + "\n")
        c = Counter(e["disposition"] for v in summ[lang]["versions"].values()
                    for e in v.values())
        print(f"{path.relative_to(ROOT)}: {dict(c)}")
    return 0


# --- expected values ----------------------------------------------------------------

EXPECTED = ROOT / "results" / "expected" / "widen.jsonl"


def _toolrun(r: dict) -> dict:
    import re
    from offload.engine.expected import value_of
    v = value_of(r.get("stdout", "")) if r["outcome"] in (
        "correct_on_device", "wrong_answer", "fell_back_to_host") else None
    m = re.search(r"ran_on_host=([01])", r.get("stdout", ""))
    return {"toolchain": r["toolchain"], "variant": "original", "value": v,
            "ran_on_host": int(m.group(1)) if m else None, "probe": None,
            "why": "" if v else r.get("reason", "")[:200],
            "xnack": r["xnack"]}


def expected_records(matrix: list[dict], elisions: dict, audit: dict
                     ) -> dict:
    """xnack -> the stored expected-value records of the widened programs
    (tools/derive/expected.py's catalog record format: the program's own oracle,
    sequential elision, the matrix runs of that memory mode as the
    original's runs)."""
    out: dict = {}
    for w in W.all_wide():
        p = w.program
        v = W.VERSION[p.model]
        lang = "c" if p.lang == "c" else "f90"
        disp = ((audit.get(lang) or {}).get("versions", {}).get(str(v), {})
                .get(p.primary_atom) or {}).get("disposition", "")
        for x in sorted({r["xnack"] for r in matrix}):
            runs = [_toolrun(r) for r in matrix
                    if r["program_id"] == p.id and r["xnack"] == x]
            out.setdefault(x, []).append({
                "key": f"{v}:{p.id}", "version": v, "program": p.id,
                "atom": p.primary_atom, "mismatches": [], "audit": disp,
                "evidence_level": p.evidence, "expect": p.expect,
                "kind": "catalog", "model": "check=pass",
                "model_detail": "the program's own oracle",
                "elision": elisions.get(p.id) if x == 1 else None,
                "variants": {"probe": "n/a: the widened catalog has no "
                             "presence-probe variant"},
                "runs": sorted(runs, key=lambda r: r["toolchain"]),
                "xnack": x})
    return out


def cmd_expected(a) -> int:
    matrix = read_rows([OUT / "matrix.jsonl"])
    ws = list(W.all_wide())
    with ThreadPoolExecutor(a.workers) as ex:
        el = dict(zip([w.id for w in ws], ex.map(W.elision, ws)))
    audit = {lang: json.loads(p.read_text()) for lang, p in
             AUDIT_SUMMARY.items() if p.is_file()}
    recs = expected_records(matrix, el, audit)
    EXPECTED.parent.mkdir(parents=True, exist_ok=True)
    meta = {"generated_by": "python3 -I tools/campaigns/widen.py expected",
            "date": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "sources": "the program's own oracle; sequential elision "
                       "(gfortran/amdflang, gcc/amdclang); the matrix runs "
                       "(results/widen/matrix.jsonl)"}
    for x, rs in recs.items():
        path = EXPECTED if x == 1 else EXPECTED.with_suffix(
            f".xnack{x}.jsonl")
        path.write_text("".join(json.dumps(r) + "\n" for r in rs))
        path.with_suffix(".meta.json").write_text(json.dumps(
            dict(meta, xnack=x), indent=1))
    # the verdicts, as the confirmer reads them
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    import expected as TE
    c = Counter(TE.evaluate(r)[1].status for r in recs[1])
    print(f"{len(recs[1])} records -> {EXPECTED.relative_to(ROOT)}: "
          f"{dict(c)}")
    return 0


# --- the support table ---------------------------------------------------------------

TABLE_CSV = ROOT / "data" / "reports" / "widen_support_table.csv"
TABLE_MD = ROOT / "data" / "reports" / "widen-support-table.md"
GROUPS = (("f90", "omp"), ("c", "omp"), ("f90", "acc"))


def nv_dispositions(summ: dict, toolchain: str, xnack: int) -> dict:
    """(version, atom) -> the disposition of the oracle mutant on one
    NVIDIA toolchain and mode (offload.engine.report reads NVIDIA cells'
    dispositions per toolchain and mode): valid (killed there),
    weak (survived there), unaudited_no_passing_original (the original
    failed there); NVHPC 26.9 without an audit of its own reuses 25.11's
    (the ruling)."""
    out = {}
    for v, atoms in summ.get("versions", {}).items():
        for atom, e in atoms.items():
            per = e.get("oracle") or {}
            st = per.get(f"{toolchain}|{xnack}")
            if st is None and toolchain == "nvhpc269":
                st = per.get(f"nvhpc|{xnack}")
            d = {"killed": "valid", "survived": "weak"}.get(st or "")
            if st == "inconclusive":
                d = "unaudited_no_passing_original"
            if d:
                out[(int(v), atom)] = d
    return out


def table_rows(matrix: list[dict]):
    """offload.engine.report's support-table rows of the widened programs, one
    group (language, model) at a time, with the widened audit summaries;
    -> [(group, rows)]."""
    import tempfile
    from offload.engine import report
    out = []
    progs = {w.id: w for w in W.all_wide()}
    for lang, model in GROUPS:
        rs = [r for r in matrix if r["program_id"] in progs and
              ("c" if progs[r["program_id"]].program.lang == "c" else "f90")
              == lang and progs[r["program_id"]].program.model == model]
        if not rs:
            continue
        apath = AUDIT_SUMMARY["c" if lang == "c" else "f90"]
        summ = json.loads(apath.read_text()) if apath.is_file() else {}
        saved = report._nv_audit
        report._nv_audit = lambda rec: nv_dispositions(
            summ, rec["toolchain"], int(rec["xnack"]))
        try:
            with tempfile.TemporaryDirectory(prefix="widen_table_") as d:
                path = Path(d) / "matrix.jsonl"
                path.write_text("".join(json.dumps(r) + "\n" for r in rs))
                rows = report.build_table(
                    path, apath,
                    source_of=lambda pid, atom, v: progs[pid].program.source
                    if pid in progs else None)
        finally:
            report._nv_audit = saved
        out.append(((lang, model), rows))
    return out


def render_table_csv(groups) -> str:
    import csv
    import io
    from offload.engine import report
    progs = {w.id: w for w in W.all_wide()}
    head, body = None, []
    for _, rows in groups:
        text = report.render_csv(rows)
        lines = list(csv.reader(io.StringIO(text)))
        head = lines[0]
        ci = head.index("citation")
        for ln in lines[1:]:
            w = progs[ln[1]]
            spec = w.spec
            ln[ci] = spec.spec_acc if (w.program.model == "acc" and getattr(
                spec, "spec_acc", "")) else spec.spec
            body.append(ln)
    buf = io.StringIO()
    wr = csv.writer(buf, lineterminator="\n")
    wr.writerow(head)
    wr.writerows(body)
    return buf.getvalue()


def render_table_md(groups) -> str:
    progs = {w.id: w for w in W.all_wide()}
    out = ["# Widened catalog: support table", "",
           "Generated by `python3 -I tools/campaigns/widen.py table` from "
           "results/widen/matrix.jsonl (tools/campaigns/widen.py run; AMD: Tuolumne "
           "MI300A, HSA_XNACK=1 unified and 0 copy) and the oracle audit "
           "summaries tests/data/widen_audit_summary*.json. Programs: "
           "offload/engine/widen_progs.py. The CSV "
           "(widen_support_table.csv) holds the same cells.", "",
           "Cell: the unified-memory label / the copy-mode label "
           "(`.` correct on device). A failing cell whose "
           "reproduction-gate verdict is not confirmed carries "
           "`[gate: <status>]` and does not count as a compiler failure "
           "(the section 'Reproduction gate' at the end; the CSV's `gate` "
           "column).", ""]
    for (lang, model), rows in groups:
        tcs = sorted({r.toolchain for r in rows},
                     key=lambda t: (TC_ORDER.index(t) if t in TC_ORDER
                                    else 99, t))
        name = {"f90": "Fortran", "c": "C"}[lang] + " " + (
            "OpenMP 5.2" if model == "omp" else "OpenACC 3.4")
        out += [f"## {name}", "", "| program | atom | audit | " +
                " | ".join(tcs) + " |", "|---|---|---|" + "---|" * len(tcs)]
        cells: dict = {}
        for r in rows:
            cells.setdefault(r.program_id, {}).setdefault(
                r.toolchain, {})[r.xnack] = r
        for pid in sorted(cells):
            c = cells[pid]
            first = next(iter(next(iter(c.values())).values()))

            def lab(t):
                d = c.get(t) or {}
                xs = sorted(d, reverse=True)
                return " / ".join("." if d[x].label == "correct on device"
                                  else d[x].label.replace("|", "/")[:60]
                                  + (f" [gate: {d[x].gate}]" if d[x].gate
                                     not in ("", "confirmed") else "")
                                  for x in xs) or "-"
            out.append(f"| {pid} | `{progs[pid].program.primary_atom}` | "
                       f"{first.audit or '-'} | "
                       + " | ".join(lab(t) for t in tcs) + " |")
        out.append("")
    from offload.engine import report
    out += report.gate_section([r for _, rows in groups for r in rows])
    return "\n".join(out) + "\n"


def cmd_table(a) -> int:
    # A changed canary of a run merged into the matrix stops it
    from offload.engine import canary
    for raw in sorted((OUT / "raw").glob("*.jsonl")):
        if raw.name.endswith(".canaries.jsonl"):
            continue
        canary.require_unchanged(
            [raw.with_name(raw.name[:-len(".jsonl")] + ".canaries.jsonl")],
            f"the widened catalog run {raw.name}",
            campaign_rows=read_rows([raw]))
    matrix = read_rows([OUT / "matrix.jsonl"])
    groups = table_rows(matrix)
    TABLE_CSV.write_text(render_table_csv(groups))
    TABLE_MD.write_text(render_table_md(groups))
    n = sum(len(rows) for _, rows in groups)
    print(f"{n} cells -> {TABLE_CSV.relative_to(ROOT)}, "
          f"{TABLE_MD.relative_to(ROOT)}")
    return 0


# --- summary ----------------------------------------

# the AMD gfx942 toolchains, their gfx90a twins, then the other toolchains of
# the merged result tables (NVHPC; not GCC, under test only): catalog/toolchains.yaml
from offload.engine.toolchains import GFX90A_TOOLCHAINS, GFX942_TOOLCHAINS, registry as _registry  # noqa: E402
TC_ORDER = GFX942_TOOLCHAINS + GFX90A_TOOLCHAINS + tuple(
    t for t in _registry().merged() if t not in GFX942_TOOLCHAINS
    and _registry().toolchains[t].family_id not in _registry().under_test_only())


def _mode_name(tc: str, x: int) -> str:
    if tc.startswith("nvhpc"):
        return {0: "separate", 2: "managed"}.get(x, str(x))
    if tc.endswith("_g90"):
        return "copy"
    return {1: "unified", 0: "copy"}.get(x, str(x))


def summary_md(matrix: list[dict], batch: list[dict]) -> str:
    """Markdown tables: the programs by family, language and model; the
    outcomes per toolchain and memory mode; the confirmer's verdicts."""
    ws = list(W.all_wide())
    out = ["| family | Fortran OpenMP | C OpenMP | Fortran OpenACC | total |",
           "|---|---|---|---|---|"]
    fams = ("base", "directive", "form", "pair")
    for f in fams + ("total",):
        row = []
        for lang, model in (("f90", "omp"), ("c", "omp"), ("f90", "acc")):
            row.append(sum(1 for w in ws if (f == "total" or W.kind_of(
                w.program.primary_atom) == f) and w.program.model == model
                and ("c" if w.program.lang == "c" else "f90") == lang))
        out.append(f"| {f} | " + " | ".join(map(str, row)) +
                   f" | {sum(row)} |")
    out += ["", "| toolchain | mode | cells | correct | wrong / crash | "
            "rejected / ICE | other | failing programs |",
            "|---|---|---|---|---|---|---|---|"]
    keys = sorted({(r["toolchain"], r["xnack"]) for r in matrix},
                  key=lambda k: (TC_ORDER.index(k[0]) if k[0] in TC_ORDER
                                 else 99, -k[1]))
    for tc, x in keys:
        rs = [r for r in matrix if r["toolchain"] == tc and r["xnack"] == x]
        c = Counter(r["outcome"] for r in rs)
        other = len(rs) - c["correct_on_device"] - c["wrong_answer"] - \
            c["rejected"]
        out.append(f"| {tc} | {_mode_name(tc, x)} | {len(rs)} | "
                   f"{c['correct_on_device']} | {c['wrong_answer']} | "
                   f"{c['rejected']} | {other} | "
                   f"{len({r['program_id'] for r in rs if r['outcome'] != 'correct_on_device'})} |")
    if batch:
        out += ["", "| verdict | rule | cells |", "|---|---|---|"]
        for (v, rule), n in Counter((r["verdict"], r["rule"])
                                    for r in batch).most_common():
            out.append(f"| {v} | {rule} | {n} |")
    return "\n".join(out) + "\n"


def part_cells() -> dict:
    """(lang, model, atom) -> {(toolchain, xnack): passed} of every single
    program a pair's part can be: the widened singles (results/widen/
    matrix.jsonl) and the grammar catalog's headline programs at the
    widened programs' versions (the support tables)."""
    import csv
    out: dict = {}
    for r in read_rows([OUT / "matrix.jsonl"]):
        w = W.by_id().get(r["program_id"])
        if w is None or W.kind_of(w.program.primary_atom) == "pair":
            continue
        lang = "c" if w.program.lang == "c" else "f90"
        out.setdefault((lang, w.program.model, w.program.primary_atom), {})[
            (r["toolchain"], r["xnack"])] = r["outcome"] == "correct_on_device"
    for path, model in ((ROOT / "results" / "support_table.csv", "omp"),
                        (ROOT / "results" / "support_table_c.csv", "omp"),
                        (ROOT / "data" / "reports" / "acc_support_table.csv",
                         "acc")):
        if not path.is_file():
            continue
        for r in csv.DictReader(open(path)):
            if r["legal"] != "1" or r.get("scope", "device") != "device" or \
                    r["version"] not in ("52", "34"):
                continue
            lang = "c" if r.get("lang") == "c" else "f90"
            out.setdefault((lang, model, r["atom"]), {})[
                (r["toolchain"], int(r["xnack"]))] = \
                r["label"].startswith("correct on device")
    return out


def interactions(matrix: list[dict], parts: dict) -> list[dict]:
    """The pair cells that fail where both parts' own programs pass on the
    same toolchain and memory mode (an interaction), and those where a
    part fails too (explained by the part)."""
    out = []
    for r in matrix:
        w = W.by_id().get(r["program_id"])
        if w is None or W.kind_of(w.program.primary_atom) != "pair" or \
                r["outcome"] == "correct_on_device":
            continue
        lang = "c" if w.program.lang == "c" else "f90"
        k = (r["toolchain"], r["xnack"])
        st = [parts.get((lang, w.program.model, p), {}).get(k)
              for p in w.spec.parts]
        out.append({"program": w.id, "toolchain": r["toolchain"],
                    "xnack": r["xnack"], "outcome": r["outcome"],
                    "parts": dict(zip(w.spec.parts, st)),
                    "interaction": all(x is True for x in st)})
    return out


def cmd_summary(a) -> int:
    bpath = ROOT / "results" / "confirm" / "batch_widen.jsonl"
    matrix = read_rows([OUT / "matrix.jsonl"])
    print(summary_md(matrix, read_rows([bpath]) if bpath.is_file() else []))
    inter = interactions(matrix, part_cells())
    by: dict = {}
    for x in inter:
        by.setdefault((x["program"], x["interaction"]), []).append(
            f"{x['toolchain']}/{_mode_name(x['toolchain'], x['xnack'])}")
    print("| pair program | failing cells | both parts pass alone |")
    print("|---|---|---|")
    for (pid, inter_), cs in sorted(by.items()):
        print(f"| {pid} | {', '.join(cs)} | {'yes' if inter_ else 'no'} |")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sp = ap.add_subparsers(dest="cmd", required=True)
    for name in ("list", "check", "run", "audit"):
        p = sp.add_parser(name)
        p.add_argument("--lang", choices=("f90", "c"))
        p.add_argument("--model", choices=("omp", "acc"))
        p.add_argument("--only", nargs="+")
        p.add_argument("--workers", type=int, default=8)
        if name == "audit":
            p.add_argument("--toolchains", nargs="+", required=True)
            p.add_argument("--xnack", type=int, nargs="+", default=[0])
            p.add_argument("--out", required=True)
            p.add_argument("--resume", action="store_true")
            p.add_argument("--timeout", type=int, default=120)
        if name == "run":
            p.add_argument("--toolchains", nargs="+", required=True)
            p.add_argument("--xnack", type=int, nargs="+", required=True)
            p.add_argument("--out", required=True)
            p.add_argument("--resume", action="store_true")
            p.add_argument("--repeats", type=int, default=3)
            p.add_argument("--timeout", type=int, default=120)
            p.add_argument("--canaries-exempt", metavar="REASON",
                           help="Run no canaries (the reason is "
                           "recorded)")
    sp.add_parser("merge")
    sp.add_parser("audit-summary")
    e = sp.add_parser("expected")
    e.add_argument("--workers", type=int, default=16)
    sp.add_parser("table")
    sp.add_parser("summary")
    a = ap.parse_args(argv)
    return {"list": cmd_list, "check": cmd_check, "run": cmd_run,
            "audit": cmd_audit, "merge": cmd_merge,
            "audit-summary": cmd_audit_summary, "expected": cmd_expected,
            "table": cmd_table, "summary": cmd_summary}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
