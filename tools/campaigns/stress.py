#!/usr/bin/env python3
"""The stress campaigns and the usage profile.
    python3 -I tools/campaigns/stress.py profile                # catalog/fuzz_profile.json
    python3 -I tools/campaigns/stress.py gen --axis private --size 256 [--model acc]
        [--layout per_unit] [--seed 1] [--out DIR]    # write one program
    python3 -I tools/campaigns/stress.py sweep --run NAME --axes private,map
        [--sizes profile|default|1,8,64] [--models omp,acc]
        [--toolchains afar,cce19,cce20,cce21] [--modes 1,0]
        [--variants O2] [--layouts single] [--seeds 1] [--workers 8]
        [--mem-gib 32] [--compile-s 900]
    python3 -I tools/campaigns/stress.py steer --run NAME --family cce --seeds 0-99
        # the steered fuzz-4s50 seeds of a campaign (seeds.json)
    python3 -I tools/campaigns/stress.py summary --run NAME     # class counts
A sweep writes results/stress/<run>/programs.jsonl and rows.jsonl and can be
resumed. Run it on compute nodes."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine import stress as S            # noqa: E402
from offload.engine import stress_exec as X       # noqa: E402

OUT = ROOT / "results" / "stress"


def _ints(text: str) -> list[int]:
    out = []
    for part in text.split(","):
        if "-" in part:
            a, b = part.split("-")
            out += list(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return out


def sizes_for(axis: str, how: str, model: str = "omp") -> list[int]:
    if model == "c":
        from offload.engine import stress_c as C
        sw = list(C.C_SWEEPS[axis])
        if how.startswith("first"):
            return sw[:int(how[5:] or 1)]
        if how == "key":
            return sorted({sw[0], sw[len(sw) // 2], sw[-1]})
        return sw if how in ("default", "profile") else _ints(how)
    if how == "default":
        return list(S.SWEEPS[axis])
    if how == "key":
        # the smallest size, the real maximum and 2x / 10x of it (profile),
        # else the first, middle and last of the default sweep
        from offload.engine import fuzz_profile as FP
        sw = list(S.SWEEPS[axis])
        if axis in ("names", "contlines"):
            return sw            # the base-language limits themselves
        try:
            mx = FP.load()["maxima"].get(axis, {}).get("max", 0)
        except FileNotFoundError:
            mx = 0
        if mx:
            return sorted({sw[0], mx, 2 * mx, 10 * mx})
        return sorted({sw[0], sw[len(sw) // 2], sw[-1]})
    if how.startswith("first"):
        return list(S.SWEEPS[axis])[:int(how[5:] or 1)]
    if how == "profile":
        from offload.engine import fuzz_profile as FP
        try:
            prof = FP.load()
        except FileNotFoundError:
            return list(S.SWEEPS[axis])
        extra = prof.get("sweeps", {}).get(axis, [])
        pts = sorted(set(S.SWEEPS[axis]) | set(extra))
        return pts
    return _ints(how)


def program_specs(args) -> list[dict]:
    specs = []
    for model in args.models.split(","):
        if model == "c":
            from offload.engine import stress_c as C
            axes = list(C.C_AXES) if args.axes == "all" else [
                a for a in args.axes.split(",") if a in C.C_AXES]
        else:
            axes = S.axis_names(model) if args.axes == "all" else \
                args.axes.split(",")
        for axis in axes:
            if model == "acc" and axis.split(".")[0] in S.ACC_EXCLUDED:
                continue
            for size in sizes_for(axis.split(".")[0], args.sizes, model):
                for layout in args.layouts.split(","):
                    for seed in _ints(args.seeds):
                        specs.append({"axis": axis, "size": size,
                                      "model": model, "layout": layout,
                                      "seed": seed})
    return specs


def _build(spec):
    if spec["model"] == "c":
        from offload.engine import stress_c as C
        return C.build_c(spec["axis"], spec["size"], spec["seed"],
                         spec["layout"])
    return S.build(spec["axis"], spec["size"], spec["seed"], spec["model"],
                   spec["layout"])


def check_task(spec: dict) -> str:
    t0 = time.time()
    try:
        p = _build(spec)
    except Exception as e:
        return json.dumps({**spec, "build_error": repr(e)[:500]})
    rec = {**spec, **p.meta(), "per_kernel": p.per_kernel}
    rec["gate"] = X.gate(p)
    rec["prerun"] = _prerun(p)
    rec["elision"] = X.elide(p) if p.legality != "illegal_probe" else None
    rec["check_s"] = round(time.time() - t0, 1)
    return json.dumps(rec)


_PRERUN: dict = {}


def _prerun(p) -> dict:
    """The pre-run check of a program (offload.engine.prerun: two
    witnesses and the race rule), once per process; on a machine without
    the front end (wingtip) the verdict a Tuolumne run stored
    (COMPLIANT_PRERUN_STORED: its programs.jsonl), else refused."""
    if p.id in _PRERUN:
        return _PRERUN[p.id]
    stored = os.environ.get("COMPLIANT_PRERUN_STORED")
    res = None
    if stored and Path(stored).is_file():
        for line in Path(stored).read_text().splitlines():
            if line.strip():
                d = json.loads(line)
                if d.get("id") == p.id and "prerun" in d and \
                        d.get("rev") == getattr(p, "rev", 1):
                    res = dict(d["prerun"], stored=stored)
                    break
    if res is None:
        from offload.engine import prerun
        ok, why = prerun.check(p)
        res = {"ok": ok, "reasons": why}
    _PRERUN[p.id] = res
    return res


def run_task(args_t) -> str:
    spec, tc, modes, variant, lim = args_t
    if spec["axis"] == "runtime":
        lim = {**lim, "run_s": max(lim["run_s"], 600)}
    t0 = time.time()
    try:
        p = _build(spec)
        pre = _prerun(p)
        if not pre["ok"] and p.legality != "illegal_probe":
            # never compiled or run
            return "\n".join(json.dumps({
                "id": p.id, "toolchain": tc, "mode": m, "variant": variant,
                "cls": "prerun_refused",
                "reason": "; ".join(pre["reasons"])[:600],
                "legality": p.legality, "axis": p.axis, "size": p.size,
                "layout": p.layout, "model": p.model, "lang": p.lang,
                "rev": getattr(p, "rev", 1), "seed": spec["seed"],
                "host": os.uname().nodename}) for m in modes)
        rows = X.execute(p, tc, modes, variant, X.Limits(**lim))
    except Exception as e:
        import traceback
        return json.dumps({**spec, "toolchain": tc, "variant": variant,
                           "crash": repr(e)[:300],
                           "traceback": traceback.format_exc()[-2000:]})
    out = []
    for r in rows:
        d = r.as_dict()
        d.update({"seed": spec["seed"], "task_s": round(time.time() - t0,
                                                        2)})
        out.append(json.dumps(d))
    return "\n".join(out)


def _done(path: Path, key) -> set:
    done = set()
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                try:
                    done.add(key(json.loads(line)))
                except (KeyError, json.JSONDecodeError):
                    pass
    return done


def pid(spec):
    model = spec["model"]
    return f"{spec['axis']}-{model}-{spec['size']}-{spec['seed']}" \
        + ("" if spec["layout"] == "single" else f"-{spec['layout']}")


def cmd_sweep(args) -> None:
    from concurrent.futures import ProcessPoolExecutor, as_completed
    out = OUT / args.run
    out.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("STRESS_TMP", str(Path(
        os.environ.get("TMPDIR", "/tmp"))))
    specs = program_specs(args)
    lim = {"compile_s": args.compile_s, "mem_gib": args.mem_gib,
           "run_s": args.run_s}
    import subprocess
    rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                         capture_output=True, text=True).stdout.strip()
    if not rev and (ROOT / ".wingtip_rev").exists():
        rev = (ROOT / ".wingtip_rev").read_text().split()[0]
    (out / "meta.json").write_text(json.dumps({
        "argv": sys.argv, "limits": lim, "host": os.uname().nodename,
        "rev": rev, "started": time.strftime("%Y-%m-%d %H:%M:%S")},
        indent=1))
    progs = out / "programs.jsonl"
    rows = out / "rows.jsonl"
    done_p = _done(progs, lambda d: d["id"])
    done_r = _done(rows, lambda d: (d["id"], d["toolchain"], d["variant"]))
    tasks = []
    if not args.no_check:
        for s in specs:
            if pid(s) not in done_p:
                tasks.append(("check", s))
    modes = tuple(_ints(args.modes))
    for s in specs:
        for tc in args.toolchains.split(","):
            if s["model"] == "acc" and tc.startswith("afar"):
                continue
            for v in args.variants.split(","):
                if (pid(s), tc, v) not in done_r:
                    tasks.append(("run", (s, tc, modes, v, lim)))
    print(f"{len(specs)} programs, {len(tasks)} tasks, {args.workers} "
          f"workers", flush=True)
    t0 = time.time()
    with ProcessPoolExecutor(args.workers) as ex, \
            progs.open("a") as fp, rows.open("a") as fr:
        futs = {}
        for kind, a in tasks:
            f = ex.submit(check_task if kind == "check" else run_task, a)
            futs[f] = kind
        for k, f in enumerate(as_completed(futs), 1):
            line = f.result()
            (fp if futs[f] == "check" else fr).write(line + "\n")
            (fp if futs[f] == "check" else fr).flush()
            if k % 20 == 0 or k == len(futs):
                print(f"{k}/{len(futs)} in {time.time() - t0:.0f} s",
                      flush=True)
    # The canaries (offload.engine.canary) in the run directory (an
    # exemption needs its reason:)
    from offload.engine import canary
    if args.canaries_exempt:
        canary.exempt(out / "canaries.jsonl", args.canaries_exempt)
    else:
        canary.add_to_campaign(out / "canaries.jsonl",
                               args.toolchains.split(","), modes,
                               log=lambda m: print(m, flush=True))
    print("all done", flush=True)


def cmd_gen(args) -> None:
    p = S.build(args.axis, args.size, args.seed, args.model, args.layout)
    out = Path(args.out or ".")
    out.mkdir(parents=True, exist_ok=True)
    for name, text in p.files:
        (out / name).write_text(text)
    (out / "meta.json").write_text(json.dumps(p.meta(), indent=1))
    print(f"{p.id}: {len(p.files)} files, {p.lines} lines, legality "
          f"{p.legality}, expected {p.expected}")


def cmd_profile(args) -> None:
    from offload.engine import fuzz_profile as FP
    prof = FP.build(gen_n=args.gen_n)
    FP.write(prof)
    print(json.dumps(prof["maxima"], indent=1))


def cmd_steer(args) -> None:
    from offload.engine import fuzz_profile as FP
    from offload.engine import fuzz_steer as FS
    prof = FP.load()
    fb = None
    if args.feedback:
        fb = FS.Feedback()
        for p in args.feedback.split(","):
            FS.feedback_from_campaign(Path(p) / "programs.jsonl", fb)
    st = FS.Steer(prof, feedback=fb)
    out = OUT / args.run
    out.mkdir(parents=True, exist_ok=True)
    picks = [dict(campaign_seed=s, **st.choose(s, args.family))
             for s in _ints(args.seeds)]
    path = out / "seeds.json"
    old = json.loads(path.read_text()) if path.exists() else []
    path.write_text(json.dumps(old + picks, indent=0))
    print(f"{len(picks)} steered seeds -> {path}")


def _spec_of_row(d: dict) -> dict:
    m = re.match(r"^(.*)-(omp|acc|c)-(\d+)-(\d+)(?:-(per_unit|partition))?$",
                 d["id"])
    return {"axis": m.group(1), "model": m.group(2), "size": int(m.group(3)),
            "seed": int(m.group(4)), "layout": m.group(5) or "single"}


FAIL_CLASSES = ("wrong_code", "ice", "run_error", "run_timeout",
                "compile_oom", "compile_timeout", "host_fallback")


def shrink_task(a) -> str:
    from offload.engine import stress_min as M
    d, out = a
    log = []
    try:
        prog = _build(_spec_of_row(d))
        res = M.minimize(prog, d, log=log.append)
        path = M.save(res, d, Path(out))
        (path / "log.txt").write_text("\n".join(log) + "\n")
        return json.dumps({"id": d["id"], "toolchain": d["toolchain"],
                           "mode": d["mode"], "variant": d["variant"],
                           "cls": d["cls"], "dir": str(path),
                           "reproduced": res.reproduced,
                           "lines_before": prog.lines,
                           "lines_after": res.prog.lines,
                           "kernels_after": [k.describe() for k in
                                             getattr(res.prog, "kernels",
                                                     [])],
                           "calls": res.calls})
    except Exception as e:
        import traceback
        return json.dumps({"id": d["id"], "toolchain": d["toolchain"],
                           "error": repr(e)[:300],
                           "traceback": traceback.format_exc()[-1500:]})


def cmd_shrink(args) -> None:
    """Minimize one failing row per (toolchain family, class, failure key,
    axis): the smallest program of each group."""
    from concurrent.futures import ProcessPoolExecutor
    from offload.engine import stress_min as M
    os.environ.setdefault("STRESS_TMP", "/tmp")
    out = OUT / args.run
    rows = [json.loads(x) for x in (out / "rows.jsonl").read_text()
            .splitlines() if x.strip()]
    groups = {}
    for d in rows:
        if "crash" in d or d["cls"] not in FAIL_CLASSES:
            continue
        if d["legality"] not in ("legal",) and not args.all_legality:
            continue
        if args.classes and d["cls"] not in args.classes.split(","):
            continue
        fam = d["toolchain"].rstrip("0123456789")
        key = (fam, d["cls"], M.failure_key(d["cls"], d["reason"]),
               d["axis"].split(".")[0])
        if key not in groups or d["size"] < groups[key]["size"]:
            groups[key] = d
    done = set()
    res_path = out / "shrink.jsonl"
    if res_path.exists():
        for x in res_path.read_text().splitlines():
            if x.strip():
                r = json.loads(x)
                done.add((r["id"], r["toolchain"]))
    todo = [d for d in groups.values() if (d["id"], d["toolchain"])
            not in done][:args.max]
    print(f"{len(groups)} groups, {len(todo)} to shrink", flush=True)
    with ProcessPoolExecutor(args.workers) as ex, res_path.open("a") as fh:
        for line in ex.map(shrink_task, [(d, out / "min") for d in todo]):
            fh.write(line + "\n")
            fh.flush()
            print(line[:200], flush=True)


# --- the equal-budget comparison (§3) ---------------------------------------------------

from offload.engine.toolchains import GFX942_TOOLCHAINS as ARM_TOOLCHAINS  # noqa: E402


def _fuzz_batch(out: Path, seeds: list, workers: int) -> None:
    from offload.engine import fuzz_exec as FE
    FE.campaign(out, seeds, workers=workers, toolchains=ARM_TOOLCHAINS,
                gen_version="fuzz-4s50", xnack=0, log=lambda m: None)


def _stress_batch(out: Path, specs: list, workers: int) -> None:
    """Run stress specs (gate, elision and rows on the arm's toolchains,
    mode 0) into out/programs.jsonl and out/rows.jsonl."""
    from concurrent.futures import ProcessPoolExecutor
    lim = {"compile_s": 900, "mem_gib": 32, "run_s": 120}
    tasks = [("check", s) for s in specs] + [
        ("run", (s, tc, (0,), "O2", lim)) for s in specs
        for tc in ARM_TOOLCHAINS
        if not (s["model"] == "acc" and tc == "afar")]
    with ProcessPoolExecutor(workers) as ex, \
            (out / "programs.jsonl").open("a") as fp, \
            (out / "rows.jsonl").open("a") as fr:
        futs = [(k, ex.submit(check_task if k == "check" else run_task, a))
                for k, a in tasks]
        for k, f in futs:
            (fp if k == "check" else fr).write(f.result() + "\n")


def _sample_specs(rng, n: int, start_seed: int, axes=None) -> list:
    out = []
    pool = axes or [a for a in S.axis_names("omp")
                    if not a.startswith("runtime")]
    for j in range(n):
        a = rng.choice(pool)
        sizes = sizes_for(a.split(".")[0], "profile")
        out.append({"axis": a, "size": rng.choice(sizes), "model": "omp",
                    "layout": "single", "seed": start_seed + j})
    return out


def cmd_arm(args) -> None:
    """One arm of the comparison, run for --budget-s seconds of wall time
    with --workers processes on one node: uniform (fuzz-4s50 seeds),
    steered (profile-weighted fuzz-4s50 seeds with feedback, plus template
    programs, --template-share of the programs), stress (sampled stress
    specs)."""
    import random as R
    out = OUT / args.run
    out.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("STRESS_TMP", "/tmp")
    t0 = time.time()
    meta = {"arm": args.arm, "budget_s": args.budget_s, "workers":
            args.workers, "host": os.uname().nodename,
            "toolchains": ARM_TOOLCHAINS, "mode": 0,
            "started": time.strftime("%Y-%m-%d %H:%M:%S"), "batches": []}
    rng = R.Random(f"arm:{args.arm}:{args.seed}")
    b = 0
    fz = out / "fuzz"
    st = out / "stress"
    fz.mkdir(exist_ok=True)
    st.mkdir(exist_ok=True)
    steer = None
    while time.time() - t0 < args.budget_s:
        tb = time.time()
        if args.arm == "uniform":
            seeds = list(range(2_000_000 + args.seed * 100_000 + b *
                               args.batch, 2_000_000 + args.seed * 100_000
                               + (b + 1) * args.batch))
            _fuzz_batch(fz, seeds, args.workers)
            meta["batches"].append({"b": b, "fuzz": len(seeds),
                                    "s": round(time.time() - tb)})
        elif args.arm == "steered":
            from offload.engine import fuzz_profile as FP
            from offload.engine import fuzz_steer as FS
            fb = FS.Feedback()
            if (fz / "programs.jsonl").exists():
                FS.feedback_from_campaign(fz / "programs.jsonl", fb)
            steer = FS.Steer(FP.load(), feedback=fb)
            nt = int(round(args.batch * args.template_share))
            picks = [steer.choose(args.seed * 100_000 + b * args.batch + j)
                     for j in range(args.batch - nt)]
            with (out / "steer.jsonl").open("a") as fh:
                for p in picks:
                    fh.write(json.dumps({"batch": b, **p}) + "\n")
            _fuzz_batch(fz, [p["seed"] for p in picks], args.workers)
            if nt:
                tpl = [a for a in S.axis_names("omp")
                       if a.startswith("template.")]
                specs = _sample_specs(rng, nt, 1000 + b * args.batch, tpl)
                _stress_batch(st, specs, args.workers)
            meta["batches"].append({"b": b, "fuzz": len(picks),
                                    "templates": nt,
                                    "s": round(time.time() - tb)})
        else:
            specs = _sample_specs(rng, args.batch, 5000 + b * args.batch)
            _stress_batch(st, specs, args.workers)
            meta["batches"].append({"b": b, "stress": len(specs),
                                    "s": round(time.time() - tb)})
        b += 1
        meta["elapsed_s"] = round(time.time() - t0)
        (out / "meta.json").write_text(json.dumps(meta, indent=1))
        print(f"batch {b} done at {meta['elapsed_s']} s", flush=True)
    print("all done", flush=True)


def cmd_summary(args) -> None:
    from collections import Counter
    out = OUT / args.run
    c = Counter()
    for line in (out / "rows.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        if "crash" in d:
            c[("CRASH", d.get("toolchain"), "")] += 1
            continue
        c[(d["toolchain"], d["mode"], d["cls"])] += 1
    for k, v in sorted(c.items(), key=str):
        print(k, v)
    # Pre-run refusals by kind and
    # layout; a front-end-only refusal is a candidate AFAR front-end
    # defect, an unreadable program a coverage loss
    from offload.engine.stress_report import prerun_refusals
    rows = [json.loads(x) for x in (out / "rows.jsonl").read_text()
            .splitlines() if x.strip()]
    for (kind, layout), ids in sorted(prerun_refusals(rows).items()):
        print(f"prerun refused: {kind} layout={layout}: {len(ids)} "
              f"programs ({', '.join(ids[:4])})")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("profile")
    p.add_argument("--gen-n", type=int, default=400)
    p = sub.add_parser("gen")
    p.add_argument("--axis", required=True)
    p.add_argument("--size", type=int, required=True)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--model", default="omp")
    p.add_argument("--layout", default="single")
    p.add_argument("--out")
    p = sub.add_parser("sweep")
    p.add_argument("--run", required=True)
    p.add_argument("--axes", default="all",
                   help="all (every axis, split into variants) or a list")
    p.add_argument("--sizes", default="profile")
    p.add_argument("--models", default="omp")
    p.add_argument("--toolchains", default=",".join(ARM_TOOLCHAINS))
    p.add_argument("--modes", default="1,0")
    p.add_argument("--variants", default="O2")
    p.add_argument("--layouts", default="single")
    p.add_argument("--seeds", default="1")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--mem-gib", type=int, default=32)
    p.add_argument("--compile-s", type=int, default=900)
    p.add_argument("--run-s", type=int, default=120)
    p.add_argument("--no-check", action="store_true")
    p.add_argument("--canaries-exempt", metavar="REASON",
                   help="Run no canaries (the reason is recorded)")
    p = sub.add_parser("steer")
    p.add_argument("--run", required=True)
    p.add_argument("--family", default=None)
    p.add_argument("--seeds", required=True)
    p.add_argument("--feedback", default="")
    p = sub.add_parser("summary")
    p.add_argument("--run", required=True)
    p = sub.add_parser("arm")
    p.add_argument("--run", required=True)
    p.add_argument("--arm", choices=("uniform", "steered", "stress"),
                   required=True)
    p.add_argument("--budget-s", type=int, default=3000)
    p.add_argument("--workers", type=int, default=24)
    p.add_argument("--batch", type=int, default=48)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--template-share", type=float, default=0.2)
    p = sub.add_parser("shrink")
    p.add_argument("--run", required=True)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--max", type=int, default=200)
    p.add_argument("--classes", default="")
    p.add_argument("--all-legality", action="store_true")
    args = ap.parse_args(argv)
    {"sweep": cmd_sweep, "gen": cmd_gen, "profile": cmd_profile,
     "steer": cmd_steer, "summary": cmd_summary,
     "shrink": cmd_shrink, "arm": cmd_arm}[args.cmd](args)


if __name__ == "__main__":
    main()
