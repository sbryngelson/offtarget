#!/usr/bin/env python3
"""HeCBench ingestion, split, references, seal and the dev-half report
(the ``hecbench`` campaign's companion: data/reports/hecbench.md).

    tools/campaigns/hecbench.py split                 # write data/bench/hecbench/split.yaml and the SEAL (names only)
    tools/campaigns/hecbench.py derive [--only DIR]   # make -n each benchmark -> recipes (compute node)
    tools/campaigns/hecbench.py ref --name N          # serial host reference output of each buildable benchmark
    tools/campaigns/hecbench.py seal --name N         # outcomes.csv and the SEAL of the holdout (prints nothing about it)
    tools/campaigns/hecbench.py report --name N       # the dev half's tables (never reads the holdout)
    tools/campaigns/hecbench.py check                 # the clone is at the pinned commit; the split file is current

Run with ``python3 -I`` from the repository root. ``derive`` runs ``make -n``
(no compiler runs) and ``ref`` compiles and runs: both on a compute node."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from offload.engine import hecbench as H  # noqa: E402

RULE = ("a benchmark is in the dev half iff the SHA-256 of its directory name "
        "(src/<name>, the whole name with -omp), read as a number, is even; "
        "otherwise it is in the sealed holdout half")


def benchmark_dirs(clone: Path = H.CLONE) -> list[str]:
    return sorted(p.name for p in (clone / "src").iterdir()
                  if p.is_dir() and p.name.endswith("-omp"))


def cmd_split(a) -> int:
    clone = Path(a.clone)
    names = benchmark_dirs(clone)
    commit = H.clone_commit(clone)
    dev = [n for n in names if H.half_of(n) == "dev"]
    hold = [n for n in names if H.half_of(n) == "holdout"]
    readme = (clone / "README.md").read_text(errors="replace")
    gpl = H.parse_gpl_listed(readme)
    d = {
        "source": "https://github.com/ORNL/HeCBench",
        "commit": commit,
        "rule": RULE,
        "benchmarks": len(names),
        "dev_count": len(dev),
        "holdout_count": len(hold),
        "gpl_style_listed_in_readme": gpl,
        "dev": dev,
        # the sealed half is named by hash only; the names are derivable from the
        # public repository and the rule, and their outcomes are sealed
        "holdout_sha256": sorted(H.name_hash(n) for n in hold),
    }
    H.SPLIT.parent.mkdir(parents=True, exist_ok=True)
    H.SPLIT.write_text("# The HeCBench split, written before the first measurement "
                       "(tools/campaigns/hecbench.py split).\n" +
                       yaml.safe_dump(d, sort_keys=False, width=100))
    ids = hashlib.sha256("\n".join(d["holdout_sha256"]).encode()).hexdigest()
    H.HOLDOUT.mkdir(parents=True, exist_ok=True)
    (H.HOLDOUT / "SEAL").write_text(
        "# seal of bench/hecbench-holdout (the sealed half of the HeCBench benchmarks)\n"
        f"commit: {commit}\ncases: {len(hold)}\n"
        "method: sha256 over the holdout's sorted directory-name hashes joined by newlines "
        "(data/bench/hecbench/split.yaml holdout_sha256)\n"
        f"sha256: {ids}\n"
        "outcomes_sha256: pending\n")
    print(f"{len(names)} benchmarks: {len(dev)} dev, {len(hold)} holdout; commit {commit}")
    return 0


def dry_run(name: str, clone: Path, timeout_s: int = 60) -> str:
    """``make -n -B`` of the benchmark's Makefile.aomp (else Makefile) with the
    compiler variables replaced by markers; the run target is included. No
    command is run (``-n``)."""
    d = clone / "src" / name
    mk = "Makefile.aomp" if (d / "Makefile.aomp").is_file() else "Makefile"
    cmd = ["make", "-n", "-B", "-f", mk, *H.MAKE_VARS, "run"]
    r = subprocess.run(cmd, cwd=d, capture_output=True, text=True, timeout=timeout_s,
                       env={**os.environ, "LAUNCHER": ""})
    return r.stdout


def cmd_derive(a) -> int:
    clone = Path(a.clone)
    readme = (clone / "README.md").read_text(errors="replace")
    gpl = H.parse_gpl_listed(readme)
    names = [a.only] if a.only else benchmark_dirs(clone)
    recipes = {"dev": [], "holdout": []}
    for n in names:
        d = clone / "src" / n
        lic_text = H.read_licence_file(d)
        try:
            text = dry_run(n, clone)
        except (subprocess.TimeoutExpired, OSError) as e:
            text = ""
            print(n, "make -n failed:", e, file=sys.stderr)
        mk = d / ("Makefile.aomp" if (d / "Makefile.aomp").is_file() else "Makefile")
        r = H.recipe_from(n, d, text, gpl, lic_text, mk.read_text(errors="replace"))
        recipes[r["half"]].append(r)
    for half, path in (("dev", H.RECIPES), ("holdout", H.HOLDOUT_RECIPES)):
        rs = recipes[half]
        if a.only:
            print(json.dumps(rs, indent=1))
            continue
        header = {"commit": H.clone_commit(clone), "procedure": "data/reports/hecbench.md; "
                  "offload/engine/hecbench.py (make -n, a fixed whitelist of flags, the Makefile's "
                  "run arguments with a repeat-like argument set to 2)",
                  "benchmarks": [H.recipe_for_tracking(r) for r in rs]}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(header, sort_keys=False, width=110))
        # the whole recipes (the gpl-style ones too) stay out of the tree
        priv = H.RESULTS / f"recipes_{half}_full.json"
        priv.parent.mkdir(parents=True, exist_ok=True)
        priv.write_text(json.dumps(rs, indent=0, sort_keys=True))
        from collections import Counter
        print(half, len(rs), dict(Counter(r["status"] for r in rs)))
    return 0


def _run(name: str):
    from offload.engine import campaign as C
    camp = C.get("hecbench")
    return camp, C.Run(camp, C.run_dir(camp, name), C.run_label(camp, name))


def cmd_report(a) -> int:
    """The dev half's tables (data/reports/hecbench.md). The sealed run is refused."""
    from collections import Counter

    from offload.engine import campaign as C
    from offload.engine import hecbench_report as RP
    camp, run = _run(a.name)
    if run.sealed:
        raise SystemExit("hecbench report reads the dev half only; the holdout is sealed")
    progs = {p.id: p for p in run.programs()}
    if any(p.half != "dev" for p in progs.values()):
        raise SystemExit(f"{a.name} holds programs of the sealed half: not reported")
    rows = run.rows()
    verdicts = run.verdicts()
    excluded = RP.non_compiler_programs(rows)
    envs: dict = {}
    for g in C.read_jsonl(run.d / "gate_reruns.jsonl"):
        if g.get("outcome") != "harness_error":
            envs.setdefault(g["cell"], set()).add(g["env"])
    cells = RP.split_cells(rows, verdicts, C.mode_name, camp.cell, set(excluded), envs)
    sigs = RP.merge_same_programs(RP.signatures(cells["evidence"]))
    index = yaml.safe_load((ROOT / "data" / "findings" / "index.yaml").read_text())["findings"]
    for s in sigs:
        s["existing"] = RP.existing_findings(s, index)
        s["related"] = [f for f in RP.existing_findings(s, index, related=True) if f not in s["existing"]]
    table = RP.outcome_table(rows, C.mode_name, set(excluded))
    out = {"programs": len(progs), "status": dict(Counter(p.recipe["status"] for p in progs.values())),
           "licence": dict(Counter(p.recipe["licence"] for p in progs.values())),
           "non_compiler_after_the_fact": excluded, "outcome_table": table,
           "evidence_cells": len(cells["evidence"]),
           "evidence_cells_without_timeouts": sum(1 for c in cells["evidence"] if c["class"] != "timeout"), "unconfirmed_cells": len(cells["unconfirmed"]),
           "unconfirmed_reasons": dict(Counter(c["why_not"] for c in cells["unconfirmed"])),
           "signatures": sigs, "gate": dict(Counter(v["verdict"] for v in verdicts.values()))}
    (run.d / "report.json").write_text(json.dumps(out, indent=1, sort_keys=True))
    print(json.dumps({k: out[k] for k in ("programs", "status", "licence", "evidence_cells",
                                          "unconfirmed_cells", "unconfirmed_reasons", "gate")}, indent=1))
    print(RP.markdown_table(table))
    print(len(sigs), "distinct failure signatures;", sum(1 for s in sigs if not s["existing"]),
          "with no finding of a matching message")
    for s in sigs:
        print(f"- {s['family']} {s['class']} {s['key'][:90]}: {len(s['programs'])} programs "
              f"({', '.join(s['toolchains'])}); existing: {', '.join(s['existing']) or 'none'}; "
              f"related: {', '.join(s['related']) or 'none'}")
    if a.write_doc:
        write_doc(out, sigs, a.write_doc)
    return 0


def write_doc(out: dict, sigs: list, path: str) -> None:
    """Splice the dev half's results into the write-up between its result markers."""
    from offload.engine import hecbench_report as RP
    L = ["## Results (dev half only)", "",
         f"Dev programs: {out['programs']}. Recipe status: " +
         ", ".join(f"{k} {v}" for k, v in sorted(out["status"].items())) + ". Licence class: " +
         ", ".join(f"{k} {v}" for k, v in sorted(out["licence"].items())) + ".", ""]
    nc = out["non_compiler_after_the_fact"]
    L += [f"Moved to the excluded programs after the runs (a header or library is missing on every "
          f"toolchain): {len(nc)}.", "",
          "### Outcome classes per toolchain and memory mode (cells of the programs that stay)", "",
          RP.markdown_table(out["outcome_table"]), "",
          "`built` is the cells whose compile and link succeeded. A compile that exceeds its limit is a "
          "`timeout`.", "",
          "### Evidence", "",
          f"Gate verdicts of the failing cells (one per cell, compile failures inheriting by signature): "
          + ", ".join(f"{k} {v}" for k, v in sorted(out["gate"].items())) + ".", "",
          f"Evidence cells (gate confirmed and a witness of another family in the same mode): "
          f"{out['evidence_cells']} ({out['evidence_cells_without_timeouts']} without the 30 s time-outs). "
          f"Unconfirmed failing cells: {out['unconfirmed_cells']} ("
          + "; ".join(f"{k}: {v}" for k, v in sorted(out["unconfirmed_reasons"].items())) + ").", "",
          f"### Failure signatures: {len(sigs)} distinct, "
          f"{sum(1 for s in sigs if not s['existing'])} with no finding of a matching message", "",
          "| family | class | signature | programs | toolchains | existing finding (same message) | related (same family and class) |",
          "|---|---|---|---|---|---|---|"]
    for s in sigs:
        L.append(f"| {s['family']} | {s['class']} | {s['key'][:100].replace('|', '/')} | "
                 f"{', '.join(p[len('hecbench-'):] for p in s['programs'])} | {', '.join(s['toolchains'])} | "
                 f"{', '.join(s['existing']) or 'none'} | {', '.join(s['related'][:4]) or 'none'} |")
    p = Path(path)
    text = p.read_text()
    a, b = text.index("<!-- results:begin -->"), text.index("<!-- results:end -->")
    p.write_text(text[:a] + "<!-- results:begin -->\n" + "\n".join(L) + "\n" + text[b:])


def cmd_seal(a) -> int:
    """outcomes.csv and the SEAL of the holdout from its run. Writes the files and prints
    nothing about their content: only the runner reads the outcomes."""
    import csv

    from offload.engine import campaign as C
    from offload.engine import gate as GT
    camp, run = _run(a.name)
    if a.name not in camp.sealed_runs:
        raise SystemExit("seal is for the holdout run")
    ver = run.verdicts()
    out = H.HOLDOUT / "outcomes.csv"
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["case", "toolchain", "mode", "outcome", "gate"])
        for r in sorted(run.rows(), key=lambda r: (r["program_id"], r["toolchain"], r["xnack"])):
            v = (ver.get(camp.cell(r["program_id"], r["toolchain"], r["xnack"])) or {}).get("verdict", "")
            w.writerow([r["program_id"], r["toolchain"], C.mode_name(r["xnack"]),
                        GT.outcome_class({**r, "kind": "hecbench"}), v])
    seal = H.HOLDOUT / "SEAL"
    lines = [ln for ln in seal.read_text().splitlines()
             if not ln.startswith(("outcomes_sha256", "recipes_sha256"))]
    lines.append("recipes_sha256: " + hashlib.sha256(H.HOLDOUT_RECIPES.read_bytes()).hexdigest())
    lines.append("outcomes_sha256: " + hashlib.sha256(out.read_bytes()).hexdigest())
    seal.write_text("\n".join(lines) + "\n")
    print("sealed")
    return 0


def cmd_t120(a) -> int:
    """Rerun the dev half's run-time time-outs of one machine's toolchains with a longer limit
    (default 120 s), through the runner, into a run of its own (rows beside the originals, never over
    them); resumable. ``--plan`` prints the cell count only. The sealed half is refused."""
    import random
    import time
    from offload.engine import campaign as C
    from offload.engine import hecbench_report as RP
    camp = C.get("hecbench")
    orig = C.Run(camp, C.run_dir(camp, "dev"), "dev")
    run = C.Run(camp, C.run_dir(camp, a.name), a.name)
    if run.sealed or orig.sealed:
        raise SystemExit("the sealed half is not rerun here")
    withheld = {p.id for p in orig.programs() if p.recipe["licence"] in H.WITHHELD}
    rows = orig.rows()
    cells = RP.timeout_cells(rows, withheld)
    mine = set(camp.caps.toolchains(a.machine))
    cells = [c for c in cells if c[1] in mine]
    done = {(r["program_id"], r["toolchain"], r["xnack"]) for r in C.read_jsonl(run.d / "rows.jsonl")}
    todo = [c for c in cells if c not in done]
    random.Random(7).shuffle(todo)      # a run cut short covers every signature
    if a.shard:
        k, m = (int(v) for v in a.shard.split("/"))
        todo = todo[k::m]               # two GPUs of one host take one half each
    print(f"{a.machine}: {len(cells)} timed-out cells, {len(todo)} to do")
    if a.plan:
        return 0
    from concurrent.futures import ThreadPoolExecutor, as_completed
    runner = camp.make_runner()
    progs = {p.id: p for p in run.programs()}
    end = time.time() + a.limit_s
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futs = [pool.submit(lambda c=c: None if time.time() > end else
                            run.run_one(runner, progs[c[0]], c[1], c[2], a.timeout)) for c in todo]
        for f in as_completed(futs):
            r = f.result()
            if r is not None:
                C.append_jsonl(run.d / "rows.jsonl", [r])
    print("done")
    return 0


def cmd_t120_gate_list(a) -> int:
    """Write t120/gate_only.json: the cells that now fail differently at the longer limit (not the ones
    still timing out) for which a compiler of another family ran the program correctly in the same
    memory mode (the original 30 s rows and the new rows are both looked at); the campaign gate of the
    t120 run then reruns exactly these (Run.gate_items)."""
    from offload.engine import campaign as C
    from offload.engine import hecbench_report as RP
    camp = C.get("hecbench")
    orig = C.Run(camp, C.run_dir(camp, "dev"), "dev")
    run = C.Run(camp, C.run_dir(camp, "t120"), "t120")
    if run.sealed or orig.sealed:
        raise SystemExit("the sealed half is not gated here")
    new = run.rows()
    by: dict = {}
    for r in orig.rows():
        by.setdefault(r["program_id"], {})[(r["toolchain"], r["xnack"])] = r
    for r in new:
        by.setdefault(r["program_id"], {})[(r["toolchain"], r["xnack"])] = r      # the 120 s row replaces
    cells = []
    for r in new:
        if RP.timeout_verdict(r) != "finished failing":
            continue
        if RP.witnessed(r, list(by[r["program_id"]].values()), C.mode_name):
            cells.append(camp.cell(r["program_id"], r["toolchain"], r["xnack"]))
    (run.d / "gate_only.json").write_text(json.dumps(sorted(cells)))
    print(len(cells), "cells to gate")
    return 0


def cmd_check(a) -> int:
    d = H.load_split()
    clone = Path(a.clone)
    ok = True
    if H.clone_commit(clone) != d["commit"]:
        print("the clone is not at the pinned commit", H.clone_commit(clone), d["commit"])
        ok = False
    names = benchmark_dirs(clone)
    if len(names) != d["benchmarks"]:
        print("the clone has", len(names), "benchmarks, the split", d["benchmarks"])
        ok = False
    print("ok" if ok else "BROKEN")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--clone", default=str(H.CLONE))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("split")
    d = sub.add_parser("derive")
    d.add_argument("--only")
    sub.add_parser("check")
    sub.add_parser("t120-gate-list")
    t = sub.add_parser("t120")
    t.add_argument("--machine", required=True)
    t.add_argument("--name", default="t120")
    t.add_argument("--timeout", type=int, default=120)
    t.add_argument("--workers", type=int, default=8)
    t.add_argument("--limit-s", type=float, default=1500)
    t.add_argument("--plan", action="store_true")
    t.add_argument("--shard", help="k/m: every m-th remaining cell, from the k-th")
    for n in ("report", "seal"):
        sp = sub.add_parser(n)
        sp.add_argument("--name", default="dev" if n == "report" else "holdout")
        if n == "report":
            sp.add_argument("--write-doc", help="splice the tables into this write-up (data/reports/hecbench.md)")
    a = ap.parse_args(argv)
    return {"split": cmd_split, "derive": cmd_derive, "check": cmd_check, "report": cmd_report,
            "t120": cmd_t120, "t120-gate-list": cmd_t120_gate_list, "seal": cmd_seal}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
