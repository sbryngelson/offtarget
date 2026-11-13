#!/usr/bin/env python3
"""Reduce a failing program to a minimal reproducer and one-change controls
(offload/engine/reduce.py; docs/tooling/contributing.md "Reduce a failing program").
Input is a recorded failing row (--from-row ROWS --id ID), a fuzz seed
(--seed N) or a program file (--program FILE). --target names where it fails
as toolchain/mode (nvhpc/0, afar/1). The reduction is delta debugging over
statements, clauses and list items, expressions, and cleanup. A candidate is
kept only if the legality witness accepts it, it compiles, and it fails with
the same signature on every --target. It is deterministic (--order-seed),
resumable (checkpoint.json in --out) and bounded (--budget-candidates,
--budget-minutes). Output in --out: <name>.<ext>, controls/, rows.jsonl,
candidates.jsonl, report.md. Run it where the target's compiler and GPU are;
tools/new_finding.py then drafts the finding from the result.

  python3 -I tools/reduce.py --program repro.f90 --target cce21/1 \\
      --name cce-x --out results/reduce/cce-x
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine import reduce as RD  # noqa: E402


def _targets(items, opt) -> list:
    return [RD.Target.parse(x, opt) for x in items or []]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_argument_group("the failing program (one of)")
    src.add_argument("--from-row", nargs="+", metavar="ROWS", help="row files (jsonl: harness rows, gate reruns, "
                     "a fuzz campaign's programs.jsonl); with --id")
    src.add_argument("--id", help="the row's program id (or file stem), or a fuzz record's seed")
    src.add_argument("--seed", type=int, help="a fuzz seed: the program is regenerated (offload.engine.fuzz)")
    src.add_argument("--gen-version", default="fuzz-1")
    src.add_argument("--base", nargs="*", default=[], help="the fuzz base-language groups of the seed")
    src.add_argument("--program", help="a program file (also with --from-row: the text to reduce)")
    tg = ap.add_argument_group("the target")
    tg.add_argument("--target", action="append", metavar="TC/MODE",
                    help="toolchain/mode row key the failure must keep (repeatable; default: the rows')")
    tg.add_argument("--verify-target", action="append", default=[], metavar="TC/MODE",
                    help="checked for the final program and the controls only")
    tg.add_argument("--opt", default="-O2")
    tg.add_argument("--mode", type=int, help="the mode of a fuzz record's failing toolchains (default: the run's)")
    tg.add_argument("--reference", metavar="elision|host:TC",
                    help="the output oracle of a wrong-answer reduction of a self-checking program: the "
                         "sequential elision (Fortran; gfortran without OpenMP) or a host run of a toolchain "
                         "from another compiler family than every target. Required for such a reduction; a "
                         "fuzz program carries its own (the elision, recomputed per candidate)")
    rd = ap.add_argument_group("the reduction")
    rd.add_argument("--name", help="the reduction's name (program id of its rows; default: the id or seed)")
    rd.add_argument("--out", help="output directory (default results/reduce/<name>)")
    rd.add_argument("--levels", default="1,2,3,4", help="the step levels to run, in order")
    rd.add_argument("--order-seed", type=int, help="shuffle the candidate order (deterministic per seed)")
    rd.add_argument("--budget-candidates", type=int, help="stop after this many candidate runs")
    rd.add_argument("--budget-minutes", type=float, help="stop after this much runner time (GPU time)")
    rd.add_argument("--workers", type=int, default=1, help="candidates judged in parallel (one per GPU slot)")
    rd.add_argument("--run-timeout", type=int, default=60, help="seconds per run (a hang costs this much)")
    rd.add_argument("--repeats", type=int, default=2, help="runs per candidate (the worst counts)")
    rd.add_argument("--no-controls", action="store_true")
    rd.add_argument("--max-controls", type=int, default=4)
    rd.add_argument("--no-witness", action="store_true",
                    help="skip the legality rules witness (exploration only; the result is not a candidate finding)")
    a = ap.parse_args(argv)

    if sum(bool(x) for x in (a.from_row, a.seed is not None, a.program and not a.from_row)) != 1:
        ap.error("give one of --from-row ROWS --id ID, --seed N, --program FILE")
    try:
        if a.from_row:
            if not a.id:
                ap.error("--from-row needs --id")
            job = RD.from_rows(a.from_row, a.id, ROOT, Path(a.program) if a.program else None, a.mode)
            name = a.name or a.id.replace(":", "-")
        elif a.seed is not None:
            job = RD.from_seed(a.seed, a.gen_version, a.base)
            name = a.name or f"seed-{a.seed}"
        else:
            job = RD.from_program(Path(a.program))
            name = a.name or Path(a.program).stem
    except RD.NoFailure as e:
        print(f"reduce: {e}", file=sys.stderr)
        return 1
    if a.target:
        job.targets = _targets(a.target, a.opt)
    if not job.targets:
        ap.error("no target: pass --target TC/MODE (the rows name none)")
    verify = [t for t in _targets(a.verify_target, a.opt) if t not in job.targets]
    out = Path(a.out) if a.out else ROOT / "results" / "reduce" / name
    out.mkdir(parents=True, exist_ok=True)
    log_f = (out / "log.txt").open("a")

    def log(msg: str, *_):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        log_f.write(line + "\n")
        log_f.flush()

    runner = RD.HarnessRunner(a.run_timeout, a.repeats)
    try:
        runner.check(job.targets + verify)
    except RD.RunnerUnavailable as e:
        print(f"reduce: {e}", file=sys.stderr)
        return 2
    budget = RD.Budget(a.budget_candidates, a.budget_minutes * 60 if a.budget_minutes else None)
    witness = (lambda t, l: (True, [])) if a.no_witness else RD.rules_witness
    witness_name = "none" if a.no_witness else "rules_witness"
    try:
        reference = RD.reference_for(a.reference, job.lang, job.targets + verify)
    except ValueError as e:
        print(f"reduce: {e}", file=sys.stderr)
        return 2
    judge = RD.Judge(runner, job.targets, job.signature, job.lang, witness=witness,
                     rows_path=out / "candidates.jsonl", name=name, budget=budget, verify_targets=verify, log=log,
                     reference=reference, witness_name=witness_name)
    levels = tuple(int(x) for x in a.levels.split(",") if x.strip())
    log(f"reduce {name}: {job.origin}; targets {', '.join(t.label for t in job.targets)}"
        + (f"; verify {', '.join(t.label for t in verify)}" if verify else "")
        + f"; signature {job.signature or '(from the first run)'}; {len(job.text.splitlines())} lines"
        + f"; witness {witness_name}; reference {getattr(reference, 'name', 'none')}")
    if a.no_witness:
        log("WARNING: --no-witness: no legality witness runs; the result is exploration, not a candidate finding")
    for n in job.notes:
        log(f"note: {n}")
    (out / f"original.{'c' if job.lang == 'c' else 'f90'}").write_text(job.text)
    if job.lang == "f90":        # the candidates are rendered this way (continuations joined, long lines wrapped)
        job.text = RD.render_lines(RD.logical_lines(job.text, "f90"), "f90")
    try:
        res = RD.reduce(job.text, job.lang, judge, levels, a.order_seed, out / "checkpoint.json", a.workers, log)
    except RD.NoFailure as e:
        if str(e).startswith("illegal"):
            log(f"the rules witness refuses the original program: {e}")
        elif str(e).startswith("no reference"):
            log(f"no output oracle for the original program: {e}")
        else:
            log(f"the original does not fail as recorded: {e}")
        return 1
    except RD.NoReference as e:
        log(f"reduce: {e}")
        return 2
    except RD.CheckpointMismatch as e:
        log(f"reduce: {e}")
        return 2
    log(f"reduced: {res.lines_before} -> {res.lines_after} lines, {len(res.steps)} steps, "
        f"{res.candidates_judged} candidate runs, {res.budget_used['seconds'] / 60:.1f} min of runner time"
        + ("; stopped at the budget: rerun the same command to resume" if res.stopped == "budget" else ""))
    ext = ".c" if job.lang == "c" else ".f90"
    final_text = judge.prepared(res.text) or res.text
    if RD.is_fuzz_format(res.text, job.lang):
        from offload.engine.fuzz_min import strip_header
        final_text = strip_header(final_text)       # the generator's header describes the original
    dest = out / f"{name}{ext}"
    dest.write_text(RD.reduction_header(name, job.origin, job.targets, res, out, job.lang, witness_name) + final_text)
    log(f"wrote {dest}")

    # the final rows: the reduced program on every target and verify target, by its own id
    rows_path = out / "rows.jsonl"
    judge.rows_path = rows_path
    final_rows, verdicts = [], []
    for t in job.targets + verify:
        try:
            row = judge.run(final_text, t, name)
        except RD.BudgetExhausted:
            log("budget spent before the final rows; rerun to finish")
            break
        row["file"] = str(dest.relative_to(ROOT)) if ROOT in dest.parents else str(dest)
        final_rows.append(row)
        verdicts.append(f"{t.label}: {RD.signature(row)}")
    for v in verdicts:
        log(f"final: {v}")
    kept = []
    if not a.no_controls and res.stopped == "done":
        log("controls: one-change edits of the reduced program's directives")
        kept = RD.controls(res.text, job.lang, judge, a.max_controls, name)
        cd = out / "controls"
        cd.mkdir(exist_ok=True)
        for c in kept:
            p = cd / f"{name}-{c.slug}-control{ext}"
            lead = "//" if job.lang == "c" else "!"
            p.write_text(f"{lead} Control of {name}{ext}: {c.what}; one change from the reduction; passes on "
                         f"{', '.join(c.passed)}.\n{lead} {RD.witness_sentence(witness_name)}.\n"
                         + (judge.prepared(c.text) or c.text))
            log(f"wrote {p}")
    # rewrite rows.jsonl with the file paths filled in
    rows = final_rows + [r for c in kept for r in c.rows]
    with rows_path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    report = [f"# Reduction {name}", "", f"- origin: {job.origin}",
              f"- targets: {', '.join(t.label for t in job.targets)}"
              + (f"; verify: {', '.join(t.label for t in verify)}" if verify else ""),
              f"- signature: {res.signature}", f"- lines: {res.lines_before} -> {res.lines_after}",
              f"- legality: {RD.witness_sentence(witness_name)}",
              f"- output oracle: {getattr(reference, 'name', 'none')}"
              + (" (the fuzz contract: the sequential elision per candidate)"
                 if isinstance(judge.contract, RD.FuzzContract) else ""),
              f"- candidate runs: {res.candidates_judged}; runner time {res.budget_used['seconds'] / 60:.1f} min; "
              f"stopped: {res.stopped}", f"- final rows: {'; '.join(verdicts)}", "", "## Steps", ""]
    report += [f"{i + 1}. {s}" for i, s in enumerate(res.steps)] or ["(none accepted)"]
    report += ["", "## Controls", ""]
    report += [f"- `controls/{name}-{c.slug}-control{ext}`: {c.what}; passes on {', '.join(c.passed)}"
               for c in kept] or ["(none found)"]
    report += ["", "## Still to do (a person)", "",
               "1. Read the reduced program: is every value it reads defined, and is the failure the one meant?",
               "2. Run the front-end witness on Tuolumne: offload.engine.prerun.check on the reduction and controls.",
               "3. Run the reproduction gate (tools/campaigns/gate.py; environments a-d) for a campaign program.",
               f"4. Draft the finding: `python3 -I tools/new_finding.py {dest} --campaign <name> --rows "
               f"{rows_path} --control {out}/controls/*{ext} --name <slug> --dir <dir>`, then write the "
               "specification citation, the legality sentence and the site text."]
    (out / "report.md").write_text("\n".join(report) + "\n")
    log(f"report {out / 'report.md'}")
    return 0 if res.stopped == "done" else 3


if __name__ == "__main__":
    sys.exit(main())
