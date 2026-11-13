"""Run the matrix and corpus baseline for one memory mode, or merge results.

Subcommands: run, rerun, merge, prune, replace, copy-subset. Examples:

    python3 -I tools/campaigns/run_matrix.py run --xnack 0 --out results/matrix.xnack0.jsonl --baseline-out results/baseline.xnack0.jsonl
    python3 -I tools/campaigns/run_matrix.py rerun --xnack 0 --out results/matrix.xnack0.jsonl --programs <id> ... --why "<reason>"
    python3 -I tools/campaigns/run_matrix.py merge --inputs results/matrix.xnack1.jsonl results/matrix.xnack0.jsonl --out results/matrix.jsonl --baseline-inputs results/baseline.xnack1.jsonl results/baseline.xnack0.jsonl --baseline-out results/baseline.jsonl
    python3 -I tools/campaigns/run_matrix.py run --lang c --xnack 1 --toolchains afar cce19 --out results/matrix_c.xnack1.jsonl

The headline mode is HSA_XNACK=1 with THP. Copy mode (HSA_XNACK=0) runs the
subset from ``offload.engine.run_matrix.copy_mode_subset``, selected with
``--copy-mode-subset`` (``copy-subset`` prints it). ``prune`` drops rows of
programs no longer generated; ``replace`` puts separate runs into a work copy
of the full file. ``--resume`` continues a cut-short run, ``--lang c`` runs
the C programs, and ``--flags-note thp=unavailable`` notes a run without THP."""
import argparse
import dataclasses
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine.baseline import (copy_semantics_paths,  # noqa: E402
                                 read_baseline, rerun_baseline, run_baseline)
from offload.engine.catalog import slice_atoms  # noqa: E402
from offload.engine.harness import detect_thp  # noqa: E402
from offload.engine.harness import gpu_text, wrong_arch  # noqa: E402
from offload.engine.toolchains import (GFX942_TOOLCHAINS, TOOLCHAINS,  # noqa: E402
                                   compiler_version, device_of,
                                   toolchain_meta)

# --toolchains without a value: the first two gfx942 headline toolchains
_DEFAULT_TOOLCHAINS = list(GFX942_TOOLCHAINS[:2])


def _target_meta(names, lang="f90"):
    """The target device and each toolchain's compiler version (of the C
    compiler for --lang c). The device of every toolchain, the
    node's GPU (rocminfo) and, per toolchain, its machine, arch, loaded
    modules and the code-object target of a compiled smoke program
    (offload.engine.toolchains.toolchain_meta)."""
    import tempfile
    devices = sorted({device_of(TOOLCHAINS[n]) for n in names})
    with tempfile.TemporaryDirectory(prefix="tcmeta_") as d:
        tmeta = {n: toolchain_meta(TOOLCHAINS[n], Path(d)) for n in names}
    return {"device": devices[0] if len(devices) == 1 else devices,
            "gpu": gpu_text(),
            "compilers": {n: compiler_version(dataclasses.replace(
                TOOLCHAINS[n], lang=lang)) for n in names},
            "toolchain_meta": tmeta}


def _arch_refusal(names) -> str | None:
    """A toolchain whose arch is not this node's GPU."""
    for n in names:
        why = wrong_arch(TOOLCHAINS[n])
        if why:
            return why
    return None
from offload.engine.run_matrix import (copy_mode_subset,  # noqa: E402
                                   matrix_programs, mode_differing,
                                   rerun_programs, run_matrix)

INDEX = ROOT / "data" / "index" / "corpus_index.csv"


def _progress(t0):
    def say(msg):
        print(f"[{time.time() - t0:7.0f}s] {msg}", file=sys.stderr,
              flush=True)
    return say


def cmd_run(args) -> int:
    t0 = time.time()
    say = _progress(t0)
    bad = _arch_refusal(args.toolchains)
    if bad:
        print(bad, file=sys.stderr)
        return 2
    meta = {"host": os.uname().nodename, "xnack": args.xnack,
            "thp_seen": detect_thp(), "flags_note": args.flags_note,
            "toolchains": args.toolchains, "versions": args.versions,
            "lang": args.lang,
            **_target_meta(args.toolchains, args.lang),
            "workers": args.workers, "timeout_s": args.timeout,
            "repeats": args.repeats, "flux_job": os.environ.get("FLUX_JOB_ID"),
            "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    only = paths = None
    if args.copy_mode_subset:
        if args.xnack != 0:
            print("--copy-mode-subset runs copy mode: use --xnack 0",
                  file=sys.stderr)
            return 2
        only = copy_mode_subset(args.versions, args.lang)
        paths = copy_semantics_paths(INDEX, args.repos, lang=args.lang)
        meta["copy_mode_subset"] = sorted(only)
        meta["copy_semantics_tests"] = sorted(paths)
    if args.device_count_dependent:
        # Only what depends on the number of visible devices
        only, paths = device_count_selection(args.versions, args.lang,
                                             args.repos)
        meta["device_count_dependent"] = {"programs": sorted(only),
                                          "tests": sorted(paths)}
        meta["rocr_visible_devices"] = os.environ.get(
            "ROCR_VISIBLE_DEVICES")
    # the GPU agents this run sees (record the device count)
    from offload.engine.toolchains import detect_gpu_count
    meta["gpus_visible"] = detect_gpu_count()
    say(f"start {meta}")
    if not args.skip_matrix:
        atoms = sorted(set().union(*(slice_atoms(v, lang=args.lang)
                                     for v in args.versions)))
        n = run_matrix(atoms, args.toolchains, [args.xnack], args.out,
                       versions=args.versions, repeats=args.repeats,
                       timeout_s=args.timeout, workers=args.workers,
                       flags_note=args.flags_note, resume=args.resume,
                       only=only, progress=say, lang=args.lang)
        meta["matrix_rows"] = n
        meta["matrix_seconds"] = round(time.time() - t0)
        say(f"matrix: {n} rows")
    if args.baseline_out:
        t1 = time.time()
        total = 0
        for i, tc in enumerate(args.toolchains):
            total += run_baseline(INDEX, args.repos, tc, args.xnack,
                                  args.baseline_out, timeout_s=args.timeout,
                                  workers=args.workers,
                                  flags_note=args.flags_note,
                                  append=i > 0, only=paths, progress=say,
                                  lang=args.lang)
        meta["baseline_rows"] = total
        meta["baseline_seconds"] = round(time.time() - t1)
        say(f"baseline: {total} rows")
    # The canaries (offload.engine.canary), next to the output; an
    # exemption needs its reason
    from offload.engine import canary
    out = Path(args.out)
    cpath = out.with_name(out.name.replace(".jsonl", "") + ".canaries.jsonl")
    if args.canaries_exempt:
        canary.exempt(cpath, args.canaries_exempt)
        meta["canaries_exempt"] = args.canaries_exempt
    else:
        rows = canary.add_to_campaign(cpath, args.toolchains, [args.xnack],
                                      args.timeout, log=say)
        meta["canaries"] = len(rows)
    meta["seconds"] = round(time.time() - t0)
    Path(str(args.out) + ".meta.json").write_text(
        json.dumps(meta, indent=1) + "\n")
    return 0


def device_count_selection(versions, lang, repos):
    """(program ids, omp_vv test paths) whose result can depend
    on the number of visible devices (offload.engine.run_matrix.
    device_count_dependent)."""
    from offload.engine.baseline import CORPUS, select_files
    from offload.engine.run_matrix import device_count_dependent
    atoms = set().union(*(slice_atoms(v, lang=lang) for v in versions))
    progs = {p.id for _, p in matrix_programs(atoms, versions, lang)
             if device_count_dependent(p.source)}
    paths = {r["path"] for r in select_files(INDEX, repos, lang)
             if device_count_dependent((CORPUS / r["repo"] / r["path"])
                                       .read_text(errors="replace"))}
    return progs, paths


def cmd_rerun(args) -> int:
    """Run some programs again (their source changed) in one memory mode;
    every other row of --out stays; the run is appended to the meta file's
    "reruns" list (the original run's metadata is kept)."""
    t0 = time.time()
    say = _progress(t0)
    bad = _arch_refusal(args.toolchains)
    if bad:
        print(bad, file=sys.stderr)
        return 2
    if bool(args.programs) == bool(args.copy_mode_subset):
        print("give --programs or --copy-mode-subset", file=sys.stderr)
        return 2
    programs = (sorted(copy_mode_subset(args.versions, args.lang))
                if args.copy_mode_subset else sorted(args.programs))
    entry = {"host": os.uname().nodename, "xnack": args.xnack,
             "thp_seen": detect_thp(), "flags_note": args.flags_note,
             "toolchains": args.toolchains, "programs": programs,
             **_target_meta(args.toolchains, args.lang),
             "why": args.why, "workers": args.workers,
             "flux_job": os.environ.get("FLUX_JOB_ID"),
             "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    say(f"rerun {entry}")
    n = rerun_programs(programs, args.toolchains, args.xnack, args.out,
                       versions=args.versions, repeats=args.repeats,
                       timeout_s=args.timeout, workers=args.workers,
                       flags_note=args.flags_note, progress=say,
                       lang=args.lang)
    entry["rows"] = n
    if args.baseline_out:
        paths = copy_semantics_paths(INDEX, args.repos, lang=args.lang)
        t1 = time.time()
        entry["baseline_paths"] = sorted(paths)
        entry["baseline_rows"] = rerun_baseline(
            INDEX, args.repos, paths, args.toolchains, args.xnack,
            args.baseline_out, timeout_s=args.timeout, workers=args.workers,
            flags_note=args.flags_note, progress=say, lang=args.lang)
        entry["baseline_seconds"] = round(time.time() - t1)
        bp = Path(str(args.baseline_out) + ".meta.json")
        bmeta = json.loads(bp.read_text()) if bp.exists() else {}
        bmeta.setdefault("reruns", []).append(
            {k: entry[k] for k in ("host", "xnack", "thp_seen", "why",
                                   "flux_job", "started", "baseline_paths",
                                   "baseline_rows")})
        bp.write_text(json.dumps(bmeta, indent=1) + "\n")
    entry["seconds"] = round(time.time() - t0)
    mp = Path(str(args.out) + ".meta.json")
    meta = json.loads(mp.read_text()) if mp.exists() else {}
    meta.setdefault("reruns", []).append(entry)
    mp.write_text(json.dumps(meta, indent=1) + "\n")
    say(f"rerun: {n} rows")
    return 0


def cmd_merge(args) -> int:
    rows = []
    for p in args.inputs:
        rows += [json.loads(line) for line in Path(p).read_text().splitlines()
                 if line.strip()]
    args.out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    progs = matrix_programs(
        set().union(*(slice_atoms(v, lang=args.lang)
                      for v in args.versions)), args.versions, args.lang)
    configs = sorted({(r["toolchain"], r["xnack"]) for r in rows})
    subset = copy_mode_subset(args.versions, args.lang) \
        if args.copy_mode_subset else None
    if subset is not None:
        # headline mode: every program; copy mode: exactly the subset
        want = {(p.id, t, x) for _, p in progs for t, x in configs
                if x == 1 or p.id in subset}
    else:
        want = {(p.id, t, x) for _, p in progs for t, x in configs}
    have = Counter((r["program_id"], r["toolchain"], r["xnack"])
                   for r in rows)
    missing = want - set(have)
    extra = set(have) - want
    dup = [k for k, c in have.items() if c > 1]
    print(f"matrix: {len(rows)} rows, {len(progs)} programs, configs "
          f"{configs}"
          + (f", copy-mode subset {len(subset)} programs" if subset else "")
          + f"; missing {len(missing)}, unexpected {len(extra)}, "
          f"duplicated {len(dup)}")
    if subset is not None and not any(x == 0 for _, x in configs):
        print("  no copy-mode rows at all")
        missing = missing or {("<copy mode>", "", 0)}
    for k in sorted(missing)[:20]:
        print("  missing", *k)
    for k in sorted(extra)[:20]:
        print("  unexpected", *k)
    c = Counter((r["version"], r["toolchain"], r["xnack"],
                 "legal" if r["legal"] else "illegal", r["outcome"])
                for r in rows)
    for k in sorted(c):
        print(*k, c[k])
    if args.baseline_inputs:
        b = []
        for p in args.baseline_inputs:
            b += read_baseline(p)
        args.baseline_out.write_text("".join(json.dumps(r) + "\n"
                                             for r in b))
        cb = Counter((r["toolchain"], r["xnack"], r["status"]) for r in b)
        bdup = [k for k, c in Counter((r["path"], r["toolchain"], r["xnack"])
                                      for r in b).items() if c > 1]
        print(f"baseline: {len(b)} rows, duplicated {len(bdup)}")
        for k in sorted(cb):
            print(*k, cb[k])
        if subset is not None:
            cs = copy_semantics_paths(INDEX, ["omp_vv"], lang=args.lang)
            x0 = {r["path"] for r in b if r["xnack"] == 0}
            bad = (x0 - cs) | (cs - x0)
            print(f"baseline copy mode: {len(x0)} tests, copy-semantics "
                  f"tests {len(cs)}, mismatched {len(bad)}")
            for k in sorted(bad)[:20]:
                print("  baseline copy mode mismatch", k)
            bdup += sorted(bad)
        dup += bdup
    return 1 if missing or extra or dup else 0


def cmd_prune(args) -> int:
    """Drop the rows of programs the generators no longer make (atoms out of the device-offload scope, catalog/<model>/
    out_of_scope.yaml) from --out; the dropped ids and the reason go to
    the meta file's "pruned" list."""
    progs = {p.id for _, p in matrix_programs(
        set().union(*(slice_atoms(v, lang=args.lang)
                      for v in args.versions)), args.versions, args.lang)}
    lines = [ln for ln in args.out.read_text().splitlines() if ln.strip()]
    keep, gone = [], Counter()
    for ln in lines:
        r = json.loads(ln)
        if r["version"] in args.versions and r["program_id"] not in progs:
            gone[r["program_id"]] += 1
        else:
            keep.append(ln)
    args.out.write_text("".join(f"{ln}\n" for ln in keep))
    mp = Path(str(args.out) + ".meta.json")
    meta = json.loads(mp.read_text()) if mp.exists() else {}
    meta.setdefault("pruned", []).append(
        {"why": args.why, "programs": sorted(gone), "rows": sum(gone.values()),
         "pruned": time.strftime("%Y-%m-%dT%H:%M:%S")})
    mp.write_text(json.dumps(meta, indent=1) + "\n")
    print(f"pruned {sum(gone.values())} rows of {len(gone)} programs: "
          + " ".join(sorted(gone)))
    return 0


def _cell_key(r: dict, baseline: bool) -> tuple:
    return ((r["path"], r["toolchain"], r["xnack"]) if baseline else
            (r["program_id"], r["toolchain"], r["xnack"], r.get("opt", "")))


def cmd_replace(args) -> int:
    """Put the rows of separate runs (--inputs, e.g. a full
    HSA_XNACK=0 run per toolchain) into --out, a work copy of a full result
    file: a row whose cell (program or path, toolchain, xnack) is in --out
    takes that row's place, a new cell is appended, every other row stays.
    Refuses (writes nothing) on a duplicated input cell or when --out would
    lose rows. Each input's run metadata (<input>.meta.json) joins the out
    file's meta "reruns" list with the ids it replaced (a baseline input
    without one takes its run's matrix meta: baseline.X -> matrix.X)."""
    b = args.baseline
    old = [json.loads(ln) for ln in args.out.read_text().splitlines()
           if ln.strip()]
    new, entries, seen = {}, [], Counter()
    for p in args.inputs:
        rows = [json.loads(ln) for ln in p.read_text().splitlines()
                if ln.strip()]
        for r in rows:
            seen[_cell_key(r, b)] += 1
            new[_cell_key(r, b)] = r
        mp = Path(str(p) + ".meta.json")
        if b and not mp.exists():  # `run` writes the meta of its matrix
            mp = p.with_name(p.name.replace("baseline", "matrix", 1)
                             + ".meta.json")
        m = json.loads(mp.read_text()) if mp.exists() else {}
        ids = sorted({r["path" if b else "program_id"] for r in rows})
        e = {k: m.get(k) for k in ("host", "thp_seen", "flags_note",
                                   "toolchains", "device", "compilers", "gpu",
                                   "workers", "flux_job", "started")}
        e.update({"xnack": sorted({r["xnack"] for r in rows}),
                  "why": args.why, "source": str(p),
                  "replaced": time.strftime("%Y-%m-%dT%H:%M:%S")})
        if len(e["xnack"]) == 1:
            e["xnack"] = e["xnack"][0]
        if b:
            e.update(baseline_paths=ids, baseline_rows=len(rows))
        else:
            e.update(programs=ids, rows=len(rows))
        entries.append(e)
    dup = [k for k, c in seen.items() if c > 1]
    if dup:
        print(f"duplicate input cells: {len(dup)}, e.g. {dup[:3]}")
        return 1
    out, done, replaced = [], set(), 0
    for r in old:
        k = _cell_key(r, b)
        if k in new and k not in done:
            out.append(new[k])
            done.add(k)
            replaced += 1
        elif k not in done:
            out.append(r)
    added = [r for k, r in new.items() if k not in done]
    out += added
    if len(out) < len(old):
        print(f"refused: {args.out} would shrink from {len(old)} to "
              f"{len(out)} rows (duplicated cells in it?)")
        return 1
    # written to a temporary file and renamed: an interrupted write never
    # truncates --out
    tmp = args.out.with_name(args.out.name + ".tmp")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in out))
    tmp.replace(args.out)
    mp = Path(str(args.out) + ".meta.json")
    meta = json.loads(mp.read_text()) if mp.exists() else {}
    meta.setdefault("reruns", []).extend(entries)
    mp.write_text(json.dumps(meta, indent=1) + "\n")
    print(f"{args.out}: {len(old)} rows before, replaced {replaced}, added "
          f"{len(added)}, {len(out)} after")
    return 0


def cmd_copy_subset(args) -> int:
    """Print the copy-mode subset; with --check, the programs whose two
    modes differ in a full two-mode matrix but are not in the subset."""
    subset = copy_mode_subset(args.versions, args.lang)
    for p in sorted(subset):
        print(p)
    print(f"{len(subset)} programs", file=sys.stderr)
    if args.check:
        rows = [json.loads(line) for line in args.check.read_text()
                .splitlines() if line.strip()]
        diff = mode_differing(rows)
        miss = sorted(diff - subset)
        print(f"{len(diff)} programs differ between modes in {args.check}; "
              f"{len(miss)} not in the subset: {' '.join(miss)}",
              file=sys.stderr)
        return 1 if miss else 0
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--xnack", type=int, required=True, choices=(0, 1, 2))
    r.add_argument("--toolchains", nargs="+", choices=list(TOOLCHAINS),
                   default=_DEFAULT_TOOLCHAINS, metavar="TC")
    r.add_argument("--versions", type=int, nargs="+", default=[52, 60])
    r.add_argument("--workers", type=int, default=8)
    r.add_argument("--timeout", type=int, default=120,
                   help="run timeout per execution, seconds")
    r.add_argument("--repeats", type=int, default=3)
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--baseline-out", type=Path, default=None)
    r.add_argument("--repos", nargs="+", default=["omp_vv"])
    r.add_argument("--flags-note", default="")
    r.add_argument("--resume", action="store_true")
    r.add_argument("--skip-matrix", action="store_true")
    r.add_argument("--canaries-exempt", metavar="REASON",
                   help="Run no canaries; the reason is recorded "
                   "and the report accepts the campaign without them")
    r.add_argument("--copy-mode-subset", action="store_true",
                   help="copy mode only for the subset (programs and "
                   "copy-semantics omp_vv tests); needs --xnack 0")
    r.add_argument("--lang", choices=("f90", "c"), default="f90",
                   help="c: the C programs and omp_vv C tests")
    r.add_argument("--device-count-dependent", action="store_true",
                   help="Only the programs and omp_vv tests whose "
                   "result can depend on the number of visible devices")
    rr = sub.add_parser("rerun")
    rr.add_argument("--xnack", type=int, required=True, choices=(0, 1, 2))
    rr.add_argument("--programs", nargs="+", default=[])
    rr.add_argument("--copy-mode-subset", action="store_true",
                    help="rerun the copy-mode subset (same node as a "
                    "copy-mode run)")
    rr.add_argument("--baseline-out", type=Path, default=None,
                    help="also rerun the copy-semantics omp_vv tests, "
                    "replacing their rows in this file")
    rr.add_argument("--repos", nargs="+", default=["omp_vv"])
    rr.add_argument("--why", required=True)
    rr.add_argument("--toolchains", nargs="+", choices=list(TOOLCHAINS),
                    default=_DEFAULT_TOOLCHAINS, metavar="TC")
    rr.add_argument("--versions", type=int, nargs="+", default=[52, 60])
    rr.add_argument("--workers", type=int, default=8)
    rr.add_argument("--timeout", type=int, default=120)
    rr.add_argument("--repeats", type=int, default=3)
    rr.add_argument("--out", type=Path, required=True)
    rr.add_argument("--flags-note", default="")
    rr.add_argument("--lang", choices=("f90", "c"), default="f90")
    m = sub.add_parser("merge")
    m.add_argument("--inputs", type=Path, nargs="+", required=True)
    m.add_argument("--out", type=Path, required=True)
    m.add_argument("--versions", type=int, nargs="+", default=[52, 60])
    m.add_argument("--baseline-inputs", type=Path, nargs="*", default=[])
    m.add_argument("--baseline-out", type=Path, default=None)
    m.add_argument("--copy-mode-subset", action="store_true",
                   help="expect HSA_XNACK=1 complete and HSA_XNACK=0 "
                   "exactly the copy-mode subset")
    m.add_argument("--lang", choices=("f90", "c"), default="f90")
    pr = sub.add_parser("prune")
    pr.add_argument("--out", type=Path, required=True)
    pr.add_argument("--versions", type=int, nargs="+", default=[52, 60])
    pr.add_argument("--why", required=True)
    pr.add_argument("--lang", choices=("f90", "c"), default="f90")
    rp = sub.add_parser("replace")
    rp.add_argument("--out", type=Path, required=True)
    rp.add_argument("--inputs", type=Path, nargs="+", required=True)
    rp.add_argument("--why", required=True)
    rp.add_argument("--baseline", action="store_true",
                    help="omp_vv baseline rows (cell = path, toolchain, "
                    "xnack)")
    c = sub.add_parser("copy-subset")
    c.add_argument("--versions", type=int, nargs="+", default=[52, 60])
    c.add_argument("--check", type=Path, default=None)
    c.add_argument("--lang", choices=("f90", "c"), default="f90")
    args = ap.parse_args(argv)
    return {"run": cmd_run, "rerun": cmd_rerun, "merge": cmd_merge,
            "prune": cmd_prune, "replace": cmd_replace,
            "copy-subset": cmd_copy_subset}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
