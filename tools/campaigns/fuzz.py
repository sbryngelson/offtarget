#!/usr/bin/env python3
"""Csmith-style random differential testing of OpenMP 5.2 offload.

Run from anywhere; the script puts the project root on sys.path itself.

    python3 -I tools/campaigns/fuzz.py gen --seed 17 [--check] [--base-features types ...]
    python3 -I tools/campaigns/fuzz.py run --run-id r1 --start 1 --count 2500 --workers 6
    python3 -I tools/campaigns/fuzz.py minimize --run-id r1 --workers 6
    python3 -I tools/campaigns/fuzz.py report --run-id r1
    python3 -I tools/campaigns/fuzz.py host-check --run-id r1 [--elision-only]
    python3 -I tools/campaigns/fuzz.py elide --run-id r1
    python3 -I tools/campaigns/fuzz.py merge --run-id s1 --runs s1-00 ... s1-19
    python3 -I tools/campaigns/fuzz.py refine --run-id r1
    python3 -I tools/campaigns/fuzz.py minimize-one --seed 17 --toolchain cce19 --kind wrong_code

``run`` is resumable; it writes results/fuzz/<run id>/programs.jsonl.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine import fuzz, fuzz_exec, fuzz_report  # noqa: E402


def _base(args) -> tuple:
    return tuple(args.base_features or ())


def cmd_gen(args) -> int:
    prog = fuzz.generate(args.seed, args.gen_version, _base(args))
    print(prog.source, end="")
    if args.check:
        c = fuzz.check(prog.source)
        print(f"! check: {c.stage} {c.detail}", file=sys.stderr)
    return 0


def cmd_run(args) -> int:
    fuzz_exec.XNACK = args.xnack     # inherited by the forked workers
    out = ROOT / "results" / "fuzz" / args.run_id
    out.mkdir(parents=True, exist_ok=True)
    meta = out / "meta.json"
    seeds = args.seeds or range(args.start, args.start + args.count)
    info = {"run_id": args.run_id, "gen_version": args.gen_version,
            "base": list(_base(args)),
            "seeds": [min(seeds), max(seeds)],
            "seed_list": list(args.seeds or ()),
            "toolchains": args.toolchains, "workers": args.workers,
            "opt": fuzz_exec.OPT, "xnack": fuzz_exec.XNACK,
            "host": os.uname().nodename,
            "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    from offload.engine.harness import detect_thp
    from offload.engine.toolchains import TOOLCHAINS, compiler_version
    info["thp"] = detect_thp()
    info["compilers"] = {t: compiler_version(TOOLCHAINS[t])
                         for t in args.toolchains}
    t0 = time.time()
    fuzz_exec.campaign(out, seeds, args.workers, tuple(args.toolchains),
                       args.reruns, log=lambda m: print(m, flush=True),
                       gen_version=args.gen_version, base=_base(args),
                       xnack=args.xnack)
    # The canaries (offload.engine.canary) in the campaign directory;
    # tools/campaigns/fuzz.py report stops when one changed or is missing (an
    # exemption needs its reason:)
    from offload.engine import canary
    if args.canaries_exempt:
        canary.exempt(out / "canaries.jsonl", args.canaries_exempt)
        info["canaries_exempt"] = args.canaries_exempt
    else:
        info["canaries"] = len(canary.add_to_campaign(
            out / "canaries.jsonl", args.toolchains, [args.xnack],
            log=lambda m: print(m, flush=True)))
    info["seconds"] = round(time.time() - t0)
    info["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    old = json.loads(meta.read_text()) if meta.exists() else {}
    old.setdefault("sessions", []).append(info)
    meta.write_text(json.dumps(old, indent=1) + "\n")
    print(f"done in {info['seconds']} s -> {out}")
    return 0


def cmd_minimize(args) -> int:
    if args.xnack is not None:
        # the memory mode of the runs (a toolchain with separate memory
        # only, gcc_g90 and gcc_sm80: 0); inherited by the workers
        fuzz_exec.XNACK = args.xnack
    only = [(int(x.split(":")[0]), x.split(":")[1], x.split(":")[2])
            for x in args.only or []]
    fuzz_report.minimize_run(ROOT / "results" / "fuzz" / args.run_id,
                             workers=args.workers, limit=args.limit,
                             log=lambda m: print(m, flush=True),
                             only=only or None,
                             also=args.also.split(",") if args.also else None)
    return 0


def cmd_refine(args) -> int:
    fuzz_report.refine_run(ROOT / "results" / "fuzz" / args.run_id,
                           workers=args.workers,
                           log=lambda m: print(m, flush=True),
                           kinds=tuple(args.kinds))
    return 0


def cmd_minimize_one(args) -> int:
    """Minimize one failure; the result carries the finding header
    (fuzz_report.finding_text), not the original program's. For a
    generated program, the references are those whose value of the
    original matched the model (fuzz_min.trusted_refs)."""
    from offload.engine import fuzz_min
    prog = None if args.source else \
        fuzz.generate(args.seed, args.gen_version, _base(args))
    src = Path(args.source).read_text() if args.source else prog.source
    failure = fuzz_min.Failure(args.toolchain, args.kind, args.signature or
                               "", args.host)
    refs = None
    if prog is not None and args.kind != "ice":
        refs = fuzz_min.trusted_refs(src, prog.expected, args.toolchain)
        if not refs:
            raise SystemExit("no reference outside the failing compiler "
                             "family matches the model")
    oracle = fuzz_min.Oracle(failure, refs)
    res = fuzz_min.minimize(src, oracle, workers=args.workers,
                            log=lambda m: print(m, flush=True))
    print(f"{res.lines_before} -> {res.lines_after} lines, "
          f"{res.oracle_calls} oracle calls; {res.verdict}")
    text = fuzz_report.finding_text(args.seed or 0, failure,
                                    args.gen_version, res.source,
                                    res.verdict)
    if args.out:
        Path(args.out).write_text(text)
    else:
        print(text)
    return 0


def _host_check(args):
    seed, gen_version, base = args
    prog = fuzz.generate(seed, gen_version, tuple(base))
    return json.dumps(fuzz_exec.recheck_host(prog))


def cmd_host_check(args) -> int:
    from concurrent.futures import ProcessPoolExecutor
    out = ROOT / "results" / "fuzz" / args.run_id
    progs, _ = fuzz_exec.load(out)
    by_seed = {p.seed: p for p in progs}
    seeds = args.seeds or [p.seed for p in progs
                           if p.host_mismatch or p.host_ref_failed]
    for s in seeds:
        if fuzz_exec.regenerate(by_seed[s]).expected != \
                by_seed[s].expected:
            raise SystemExit(f"seed {s}: the generator no longer replays")
    path = out / fuzz_exec.HOSTCHECK
    if args.elision_only:
        old = [json.loads(ln) for ln in path.read_text().splitlines()
               if ln.strip()] if path.exists() else []
        new = []
        for r in old:
            if args.seeds and r["seed"] not in args.seeds:
                new.append(r)
                continue
            src = fuzz_exec.regenerate(by_seed[r["seed"]]).source
            n = fuzz_exec.reelide(r, src)
            n["reelided"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            if (n["validity"], n["elision"]) != (r["validity"],
                                                 r["elision"]):
                print(f"seed {r['seed']}: {r['validity']} -> "
                      f"{n['validity']}; elision {n['elision'][:100]}")
            new.append(n)
        path.write_text("".join(json.dumps(r) + "\n" for r in new))
        print(f"wrote {path}")
        return 0
    keep = [ln for ln in (path.read_text().splitlines()
                          if path.exists() else [])
            if ln.strip() and json.loads(ln)["seed"] not in seeds]
    print(f"{len(seeds)} programs: {seeds}", flush=True)
    t0 = time.time()
    with ProcessPoolExecutor(args.workers) as ex:
        recs = list(ex.map(_host_check, [(s, by_seed[s].gen_version,
                                          by_seed[s].base) for s in seeds]))
    stamp = {"node": os.uname().nodename,
             "checked": time.strftime("%Y-%m-%dT%H:%M:%S")}
    recs = [json.dumps(dict(json.loads(r), **stamp)) for r in recs]
    path.write_text("\n".join(sorted(keep + recs, key=lambda ln: json.loads(
        ln)["seed"])) + "\n")
    for r in map(json.loads, recs):
        print(f"seed {r['seed']}: {r['validity']} witnesses="
              f"{r['witnesses']} host_path_failure={r['host_path_failure']}")
    print(f"wrote {path} ({time.time() - t0:.0f} s)")
    return 0


def _elide(args):
    seed, gen_version, base = args
    return json.dumps(fuzz_exec.elide_record(
        fuzz.generate(seed, gen_version, tuple(base))))


def cmd_elide(args) -> int:
    """results/fuzz/<run id>/elision.jsonl: the sequential elision of every
    program of the campaign that passed the legality checks."""
    from concurrent.futures import ProcessPoolExecutor
    out = ROOT / "results" / "fuzz" / args.run_id
    progs, _ = fuzz_exec.load(out)
    progs = [p for p in progs if p.check == "ok"]
    t0 = time.time()
    with ProcessPoolExecutor(args.workers) as ex:
        recs = list(ex.map(_elide, [(p.seed, p.gen_version, p.base)
                                    for p in progs], chunksize=4))
    for p, r in zip(progs, map(json.loads, recs)):
        if r["expected"] != p.expected:
            raise SystemExit(f"seed {p.seed}: the generator no longer "
                             "replays")
    (out / fuzz_exec.ELISION_FILE).write_text("".join(r + "\n"
                                                      for r in recs))
    rs = [json.loads(r) for r in recs]
    app = [r for r in rs if r["applicable"]]
    print(f"{len(rs)} programs, elision applies to {len(app)}, "
          f"= model {sum(r['value'] == r['expected'] for r in app)}, "
          f"differs {sum(r['value'] not in (None, r['expected']) for r in app)}"
          f", no value {sum(r['value'] is None for r in app)} "
          f"({time.time() - t0:.0f} s)")
    return 0


def cmd_merge(args) -> int:
    """Results/fuzz/<run id>/ from the chunks a campaign ran as
    (programs, host checks, elisions and sessions; the chunks are kept)."""
    base = ROOT / "results" / "fuzz"
    info = fuzz_exec.merge_runs(base / args.run_id,
                                [base / r for r in args.runs])
    print(json.dumps(info))
    return 0


def cmd_join(args) -> int:
    """Results/fuzz/<run id>/ from runs of the same seeds on other
    toolchains (fuzz_exec.join_toolchains: the AMD run, then the NVHPC
    runs)."""
    base = ROOT / "results" / "fuzz"
    info = fuzz_exec.join_toolchains(base / args.run_id, base / args.base,
                                     [base / r for r in args.runs])
    print(json.dumps(info))
    return 0


def cmd_campaign_review(args) -> int:
    """The generated part of data/reports/fuzz-<campaign>.md (rates,
    confirmer verdicts after the agent decisions, rejection causes, spot
    checks, feature-pair interactions, copy mode) and each run's
    summary.json (the dashboard reads it)."""
    from offload.engine import fuzz_campaign as FC
    from offload.engine.confirm import decisions as DE
    from offload.engine.confirm.ingest import campaign_runs
    runs = campaign_runs()[args.campaign]
    progs = FC.load(runs)
    batch = FC.load_batch(args.batch) if args.batch else []
    data = DE.load()
    spot = None
    if data["spot_checks"]:
        from collections import Counter
        agree = Counter((s["group"].split("|")[0], bool(s["agree"]))
                        for s in data["spot_checks"])
        cases = Counter()
        for s in data["spot_checks"]:
            cases[(s["group"].split("|")[0], bool(s["agree"]))] += s["cases"]
        verdicts = sorted({v for v, _ in agree})
        spot = FC.table(["verdict class", "groups agree", "groups disagree",
                         "sampled cases agree", "sampled cases disagree"],
                        [[v, agree[(v, True)], agree[(v, False)],
                          cases[(v, True)], cases[(v, False)]]
                         for v in verdicts])
        dis = [s for s in data["spot_checks"] if not s["agree"]]
        if dis:
            spot += ["", "Disagreements (each became a rule fix and a "
                     "rerun):", ""] + [f"- `{s['group']}`: {s['note']}"
                                       for s in dis]
    block = FC.render_generated(args.campaign, progs, batch,
                                data["decisions"], spot)
    md = ROOT / "data" / "reports" / f"fuzz-{args.campaign}.md"
    begin, end = "<!-- t28:begin (generated) -->", "<!-- t28:end -->"
    text = md.read_text() if md.exists() else \
        f"# Fuzz campaign {args.campaign}\n\n"
    gen = f"{begin}\n{block}{end}"
    if begin in text:
        head, rest = text.split(begin, 1)
        text = head + gen + rest.split(end, 1)[1]
    else:
        text = text.rstrip("\n") + "\n\n" + gen + "\n"
    md.write_text(text)
    # the campaign's findings (catalog/triage_28.yaml `findings`) as the
    # minimized.json rows the dashboard's findings table reads
    import yaml
    tri = yaml.safe_load((ROOT / "catalog" / "triage_28.yaml").read_text())
    for r in runs:
        d = ROOT / "results" / "fuzz" / r
        mins = [dict(f) for f in tri.get("findings") or ()
                if f.get("run") == r]
        for m in mins:
            m.pop("run", None)
        (d / "minimized.json").write_text(json.dumps(mins, indent=1) + "\n")
        (d / "summary.json").write_text(json.dumps(
            fuzz_report.summarize(d), indent=1) + "\n")
    print(md)
    return 0


def cmd_reclassify(args) -> int:
    for seed, tc, cls, why in fuzz_exec.reclassify_compile(
            ROOT / "results" / "fuzz" / args.run_id):
        print(f"seed {seed} {tc}: {cls}: {why[:120]}")
    return 0


def cmd_base_review(args) -> int:
    fuzz_report.write_base_review(
        [ROOT / "results" / "fuzz" / r for r in args.run_ids],
        ROOT / "data" / "reports" / "fuzz-base-language.md")
    return 0


def cmd_report(args) -> int:
    fuzz_report.write_report(ROOT / "results" / "fuzz" / args.run_id,
                             ROOT / "data" / "reports" /
                             f"fuzz-{args.run_id}.md")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("gen")
    p.add_argument("--gen-version", default=fuzz.GEN_VERSION,
                   choices=fuzz.GEN_VERSIONS)
    p.add_argument("--base-features", nargs="*", choices=fuzz.ALL_GROUPS,
                   help="base-language groups (fuzz-3; offload.engine.fuzz_base)")
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--check", action="store_true")
    p.set_defaults(fn=cmd_gen)
    p = sub.add_parser("run")
    p.add_argument("--gen-version", default=fuzz.GEN_VERSION,
                   choices=fuzz.GEN_VERSIONS)
    p.add_argument("--base-features", nargs="*", choices=fuzz.ALL_GROUPS,
                   help="base-language groups (fuzz-3; offload.engine.fuzz_base)")
    p.add_argument("--run-id", required=True)
    p.add_argument("--start", type=int, default=1)
    p.add_argument("--count", type=int, default=100)
    p.add_argument("--seeds", type=int, nargs="*",
                   help="these seeds instead of --start/--count ("
                   "the seeds a generator fix changes)")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--reruns", type=int, default=fuzz_exec.RERUNS)
    p.add_argument("--xnack", type=int, default=fuzz_exec.XNACK,
                   choices=(0, 1), help="HSA_XNACK of the runs (0: copy "
                   "mode, needs a flux allocation)")
    p.add_argument("--toolchains", nargs="+",
                   default=list(fuzz_exec.TOOLCHAIN_ORDER))
    p.add_argument("--canaries-exempt", metavar="REASON",
                   help="Run no canaries (the reason is recorded)")
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("minimize")
    p.add_argument("--run-id", required=True)
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--limit", type=int, default=4,
                   help="representatives minimized per failure group")
    p.add_argument("--only", nargs="*", metavar="SEED:TOOLCHAIN:KIND",
                   help="minimize these failures instead of the "
                   "representatives")
    p.add_argument("--xnack", type=int, choices=(0, 1), default=None,
                   help="the memory mode of the runs (default the "
                   "campaign default, HSA_XNACK=1)")
    p.add_argument("--also", help="toolchains (comma separated) the "
                   "minimized program is tried on, default every one "
                   "(another machine: its own)")
    p.set_defaults(fn=cmd_minimize)
    p = sub.add_parser("refine")
    p.add_argument("--run-id", required=True)
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--kinds", nargs="+",
                   default=["ice", "wrong_code", "run_error"])
    p.set_defaults(fn=cmd_refine)
    p = sub.add_parser("minimize-one")
    p.add_argument("--gen-version", default=fuzz.GEN_VERSION,
                   choices=fuzz.GEN_VERSIONS)
    p.add_argument("--base-features", nargs="*", choices=fuzz.ALL_GROUPS,
                   help="base-language groups (fuzz-3; offload.engine.fuzz_base)")
    p.add_argument("--seed", type=int)
    p.add_argument("--source")
    p.add_argument("--toolchain", required=True)
    p.add_argument("--kind", default="wrong_code",
                   choices=("wrong_code", "ice", "run_error"))
    p.add_argument("--signature")
    p.add_argument("--host", type=int, default=0)
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--out")
    p.set_defaults(fn=cmd_minimize_one)
    p = sub.add_parser("host-check")
    p.add_argument("--run-id", required=True)
    p.add_argument("--seeds", type=int, nargs="*")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--elision-only", action="store_true",
                   help="recompute the sequential elision and the validity "
                   "of the stored host-check records (no host runs)")
    p.set_defaults(fn=cmd_host_check)
    p = sub.add_parser("merge",
                       help="one campaign directory from the run ids it "
                       "was run as")
    p.add_argument("--run-id", required=True)
    p.add_argument("--runs", nargs="+", required=True)
    p.set_defaults(fn=cmd_merge)
    p = sub.add_parser("join",
                       help="one campaign directory from runs of the same "
                       "seeds on other toolchains")
    p.add_argument("--run-id", required=True)
    p.add_argument("--base", required=True,
                   help="the run with the legality gate and host reference")
    p.add_argument("--runs", nargs="+", required=True)
    p.set_defaults(fn=cmd_join)
    p = sub.add_parser("campaign-review",
                       help="data/reports/fuzz-<campaign>.md, generated part "
                       "")
    p.add_argument("--campaign", required=True)
    p.add_argument("--batch", nargs="*",
                   help="the confirmer's results (after `confirm decide`)")
    p.set_defaults(fn=cmd_campaign_review)
    p = sub.add_parser("reclassify",
                       help="classify again the unclassified compile "
                       "failures of a campaign (current message tables)")
    p.add_argument("--run-id", required=True)
    p.set_defaults(fn=cmd_reclassify)
    p = sub.add_parser("elide",
                       help="results/fuzz/<run id>/elision.jsonl: the "
                       "sequential elision of every program")
    p.add_argument("--run-id", required=True)
    p.add_argument("--workers", type=int, default=16)
    p.set_defaults(fn=cmd_elide)
    p = sub.add_parser("base-review",
                       help="data/reports/fuzz-base-language.md from the "
                       "stage campaigns (run report on each first)")
    p.add_argument("--run-ids", nargs="+", required=True)
    p.set_defaults(fn=cmd_base_review)
    p = sub.add_parser("report")
    p.add_argument("--run-id", required=True)
    p.set_defaults(fn=cmd_report)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
