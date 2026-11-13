#!/usr/bin/env python3
"""The automated bug confirmer (design: docs/tooling/confirm.md).

Run from anywhere; the script puts the project root on sys.path itself.

    python3 -I tools/confirm.py case prog.f90 --toolchain cce21 \
        [--mode unified|copy] [--expected "bad= 0"] [--run] [--minimize]
    python3 -I tools/confirm.py batch --from results/matrix.jsonl \
        [--filter cce21] [--out results/confirm/batch.jsonl] \
        [--shard K/N] [--outcomes crash wrong_answer] [--store FILE]
    python3 -I tools/confirm.py decide --batch B.jsonl --out B.final.jsonl
    python3 -I tools/confirm.py triage
    python3 -I tools/confirm.py validate
    python3 -I tools/confirm.py regress {plan,fuzz,diff,confirm,report} \
        --toolchain cce21_4 --like cce21
    python3 -I tools/confirm.py promote results/confirm/drafts/<id> NAME
    python3 -I tools/confirm.py index [--scope [--write]]
    python3 -I tools/confirm.py backlog [--write]
    python3 -I tools/confirm.py exec < request.json
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine.confirm import collectors as C  # noqa: E402
from offload.engine.confirm import engine as EN  # noqa: E402
from offload.engine.confirm import ingest as I  # noqa: E402
from offload.engine.confirm import machines as M  # noqa: E402
from offload.engine.confirm import programs as P  # noqa: E402
from offload.engine.confirm.model import Case  # noqa: E402
from offload.engine.confirm.store import Store  # noqa: E402
from offload.engine.toolchains import TOOLCHAINS  # noqa: E402

OUT = ROOT / "results" / "confirm"


def in_shard(ident: str, k: int, n: int) -> bool:
    """Shard k of n of a batch, by program (every toolchain and
    mode of a program in one shard, so its runs are reused)."""
    import zlib
    return zlib.crc32(ident.encode()) % n == k


def _ctx(run: bool, repeats: int = 3, store: str | None = None,
         read: tuple = ()) -> C.Context:
    from offload.engine.confirm.execute import LocalRunner, RemoteRunner
    remote = {}
    if run:
        for m in M.load().values():
            if isinstance(m.access, dict) and "ssh" in m.access:
                rr = RemoteRunner(m)
                if rr.available():
                    remote[m.name] = rr
    here = None
    if run:
        from offload.engine.toolchains import detect_gpu
        from offload.engine.confirm.jobs import inside_job
        m = M.machine_of_arch(detect_gpu()[0])
        if m is not None and inside_job(m):
            here = LocalRunner()
            # this node runs only its own machine's toolchains
            here.machine = m.name
        else:
            print("note: not inside a job allocation of this machine: no "
                  "local runs (submit tools/jobs/run_confirm.sh)",
                  file=sys.stderr)
    st = Store(Path(store), also_read=(OUT / "evidence.jsonl",) + tuple(
        p for g in read for p in sorted(Path(ROOT).glob(g))
        if p.resolve() != Path(store).resolve())) if store else Store()
    return C.Context(I.stored_index(), st, runner=here, remote=remote,
                     allow_run=run, repeats=repeats)


def cmd_case(a) -> int:
    ref = P.file_ref(a.files, a.expected or "", version=a.version)
    tc = TOOLCHAINS[a.toolchain]
    m = M.load()[tc.machine]
    mode = a.mode or m.headline_mode
    if not m.has(mode):
        print(json.dumps({"verdict": "not_applicable", "reason":
                          f"{m.name} has no {mode} mode"}))
        return 0
    ctx = _ctx(a.run, a.repeats)
    # The reproducer's own build flags ("build flags:" header)
    # are the case's optimisation level and flags
    from offload.engine.confirm.execute import build_opt
    opt = build_opt("-O2", ref.flags)
    # the case's own cell: run it (or take --outcome when given)
    if a.outcome:
        case = Case(ref, a.toolchain, tc.machine, tc.arch, mode, a.outcome,
                    a.reason or "", a.value, opt=opt)
    else:
        if not a.run:
            print("give --outcome or --run", file=sys.stderr)
            return 2
        ev = C.run_cell(ctx, "repeats", Case(ref, a.toolchain, tc.machine,
                                             tc.arch, mode, "unknown",
                                             opt=opt),
                        a.toolchain, mode)
        if ev is None or not ev.runs:
            print(json.dumps({"verdict": "environment", "reason":
                              "the case's own cell could not run here: "
                              + (ev.detail if ev else "no runner for "
                                 f"{tc.machine}")}))
            return 1
        r = ev.runs[0]
        case = Case(ref, a.toolchain, tc.machine, tc.arch, mode, r.outcome,
                    r.reason, r.value, r.ran_on_host,
                    len({(x.outcome, x.value) for x in ev.runs}) > 1,
                    len(ev.runs), opt=opt)
    # an explicit --minimize on one case also minimizes an instance of a
    # known finding
    res = EN.confirm(case, ctx, minimize="always" if a.minimize else False,
                     draft=a.draft)
    print(EN.dumps(res))
    return 0


def cmd_batch(a) -> int:
    rows = []
    for p in a.sources:
        rows += I.load_rows(Path(p))
    rows = I.failing_rows(rows)
    if a.toolchains:
        rows = [r for r in rows if r.toolchain in a.toolchains]
    if a.outcomes:
        rows = [r for r in rows if r.outcome in a.outcomes]
    if a.shard:
        k, n = map(int, a.shard.split("/"))
        rows = [r for r in rows if in_shard(r.ident, k, n)]
    ctx = _ctx(a.run, a.repeats, a.store, tuple(a.read or ()))
    out = Path(a.out) if a.out else OUT / "batch.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out.open("w") as f:
        for r in rows:
            case = I.case_of_row(r)
            if a.filter and not re.search(a.filter, case.case_id):
                continue
            res = EN.confirm(case, ctx, minimize=a.minimize, draft=a.draft)
            res.pop("evidence", None) if not a.evidence else None
            f.write(json.dumps(res, default=str) + "\n")
            n += 1
            if n % 100 == 0:
                print(f"{n} cases", flush=True)
    print(f"{n} cases -> {out}")
    return 0


def cmd_validate(a) -> int:
    from offload.engine.confirm import validate as V
    rep = V.run(live=a.live, log=print)
    print(json.dumps(rep["headline"], indent=1))
    if not a.live and V.NV_CASES:
        # The NVIDIA cells with a hand verdict, apart
        nv = V.run(cases=list(V.NV_CASES), log=print,
                   out=OUT / "validation_nvhpc.jsonl")
        print("NVHPC:", json.dumps(nv["headline"], indent=1))
    if not a.live:
        meta = {}
        log = OUT / "validate_live.log"
        if log.is_file():
            m = re.search(r"^host (\S+)", log.read_text(), re.M)
            meta["live_host"] = m.group(1) if m else ""
        print(json.dumps(V.write_report(meta), indent=1))
    return 0


def cmd_regress(a) -> int:
    from offload.engine.confirm import regress as R
    d = R.out_dir(a.toolchain)
    if a.step == "plan":
        for rec in R.plan(a.toolchain, a.like, submit=a.submit):
            print(json.dumps(rec))
        return 0
    if a.step == "fuzz":
        R.run_fuzz(a.toolchain, a.like, a.workers,
                   log=lambda m: print(m, flush=True))
        return 0
    if a.step == "diff":
        cells = R.diff(a.toolchain, a.like)
        (d / "diff.json").write_text(json.dumps(cells, indent=1))
        print(json.dumps(R.summary(cells), indent=1))
        return 0
    if a.step == "confirm":
        from offload.engine.confirm.execute import LocalRunner
        cells = json.loads((d / "diff.json").read_text())
        res = R.confirm_differences(a.toolchain, a.like, cells,
                                    LocalRunner(), workers=a.workers,
                                    log=lambda m: print(m, flush=True))
        (d / "confirmed.json").write_text(json.dumps(res, indent=1,
                                                     default=str))
        return 0
    if a.step == "report":
        from offload.engine.toolchains import compiler_version
        cells = json.loads((d / "diff.json").read_text())
        conf = json.loads((d / "confirmed.json").read_text()) \
            if (d / "confirmed.json").is_file() else []
        meta = {"new_compiler": compiler_version(TOOLCHAINS[a.toolchain]),
                "old_compiler": compiler_version(TOOLCHAINS[a.like])}
        md = ROOT / "data" / "reports" / f"confirm-regress-{a.toolchain}.md"
        md.write_text(R.render(a.toolchain, a.like, cells, conf, meta))
        (d / "report.json").write_text(json.dumps(
            {"summary": R.summary(cells), "confirmed": conf, **meta},
            indent=1, default=str))
        print(md)
        return 0
    return 2


def cmd_promote(a) -> int:
    from offload.engine.confirm import draft as DR
    print(DR.promote(Path(a.draft), a.name))
    return 0


def cmd_index(a) -> int:
    from offload.engine.confirm import findings as FI
    if a.scope:
        # each index finding's mode and arch scope
        # from the cells the confirmer instance-links to it
        import yaml
        names = {"data/findings/" + d["file"] for d in yaml.safe_load(
            FI.INDEX.read_text())["findings"]}
        fs = [f for f in FI.load_index() if f.file in names]
        scope = FI.derive_scope(list(FI.stored_cells(a.batch)), fs)
        stale = {f.file: scope[f.file] for f in fs
                 if (scope[f.file]["modes"], scope[f.file]["arch"]) !=
                 (list(f.modes), list(f.arch))}
        for file, s in stale.items():
            print(f"{file}: modes {s['modes']} arch {s['arch']} (linked "
                  + ", ".join(f"{m}/{x} {n}" for (m, x), n in
                              sorted(s["linked"].items())) + ")")
        if a.write:
            print("rewrote:", FI.write_scope(stale))
        print(f"{len(stale)} of {len(fs)} entries "
              f"{'rewritten' if a.write else 'differ'}")
        return 1 if stale and not a.write else 0
    print(json.dumps([{**f.__dict__, "constructs": sorted(f.constructs),
                       "group": f.group} for f in FI.index()], indent=1))
    return 0


def cmd_backlog(a) -> int:
    """The catalog cells the confirmer calls a bug
    with no finding (offload/engine/confirm/backlog.py), grouped by signature;
    --write renders data/reports/unlinked-bugs.md; exit 1 when a group has
    no recorded reason in catalog/unlinked_bugs.yaml (or changed size)."""
    from offload.engine.confirm import backlog as B
    gs = B.groups(B.unlinked(Path(a.batch)))
    for k, ds in gs.items():
        print(f"{len(ds):4} {k}")
    print(f"{sum(map(len, gs.values()))} cells in {len(gs)} groups")
    data = B.load()
    if a.write:
        B.DOC.write_text(B.render(gs, data))
        print(f"-> {B.DOC.relative_to(ROOT)}")
    problems = B.check(gs, data)
    for p in problems:
        print("PROBLEM", p)
    return 1 if problems else 0


def cmd_exec(a) -> int:
    from offload.engine.confirm.execute import serve
    print(serve(sys.stdin.read()))
    return 0


def cmd_witness(a) -> int:
    """The independent legality checkers (not under
    test, catalog/machines.yaml independent_checkers) on the catalog
    programs every compiler family rejects (verdict R12 or R12a in the
    batch file) or the programs named; catalog/legality_witness.yaml."""
    from offload.engine.confirm import witness as W
    if not W.checkers():
        # no trusted independent checker
        W.DATA.write_text(W.EMPTY)
        print("no independent legality checker (catalog/machines.yaml "
              f"independent_checkers is empty): {W.DATA.relative_to(ROOT)} "
              "has no witness")
        return 0
    ids = set(a.programs or ())
    if not ids:
        for line in Path(a.batch).read_text().splitlines():
            r = json.loads(line)
            if r["rule"].startswith("R12") and \
                    r["rule"] != "R12b-compile-undecided" and \
                    r["case"]["program"]["kind"] == "catalog":
                ids.add(r["case"]["program"]["ident"])
    rows = []
    calibrate = {}
    for pid in sorted(ids):
        ref = P.catalog_ref(pid)
        if not ref.text:
            continue
        for name in W.names_for(ref.lang, ref.model):
            r = W.check(pid, ref.text, ref.lang, ref.sha, ref.model, name)
            r["atom"] = W.atom_of(pid)
            rows.append(r)
            print(pid, r["checker"], r["result"], r["message"][:100])
            if r["result"] == "accept":
                calibrate[pid] = ref.model
    # (ruling R2): every accept is calibrated on the
    # illegal variants of its atom (all languages of the model): a checker
    # family that accepts them is no witness for that atom
    import hashlib
    done = set()
    for pid, model in sorted(calibrate.items()):
        atom = W.atom_of(pid)
        for qid, lang, src in W.illegal_variants(pid):
            for name in W.names_for(lang, model):
                if (qid, name) in done:
                    continue
                done.add((qid, name))
                r = W.check(qid, src, lang,
                            hashlib.sha256(src.encode()).hexdigest(), model,
                            name)
                r["calibrates"] = atom
                rows.append(r)
                print("calibration", atom, qid, r["checker"], r["result"],
                      r["message"][:100])
    W.write(rows)
    print(f"{len(rows)} programs -> {W.DATA.relative_to(ROOT)}")
    return 0


def cmd_decide(a) -> int:
    """The agent decisions of a decisions file applied to the
    needs_human results of a batch (each result gets `final` and
    `decided_by`), the seeded 10% spot sample per verdict class grouped by
    signature, and which sampled groups have no spot check yet."""
    from collections import Counter
    from offload.engine.confirm import decisions as DE
    data = DE.load(Path(a.decisions))
    rows = []
    for p in a.batch:
        rows += [json.loads(ln) for ln in Path(p).read_text().splitlines()
                 if ln.strip()]
    out = DE.apply(rows, data["decisions"])
    Path(a.out).write_text("".join(json.dumps(r, default=str) + "\n"
                                   for r in out))
    used = Counter(r["decided_by"] for r in out)
    print("decided by:", dict(used))
    unused = [d.id for d in data["decisions"] if d.id not in used]
    if unused:
        print("decisions matching nothing:", unused)
    print("final:", dict(Counter(r["final"] for r in out)))
    sample = DE.spot_sample(rows)
    groups = DE.spot_groups(rows, sample)
    done = {s["group"] for s in data["spot_checks"]}
    print(f"spot sample {sum(map(len, sample.values()))} cases in "
          f"{len(groups)} groups; {len(set(groups) - done)} unchecked")
    if a.groups:
        Path(a.groups).write_text(json.dumps(groups, indent=1))
    # the recorded sample (drawn once, its classes as drawn), else a
    # fresh draw from this batch
    checks = data["case_spot_checks"]
    cs = DE.sample_of(checks) if checks else DE.case_sample(
        out, own_class=DE.own_classes(data["decisions"]))
    table = DE.case_agreement(cs, checks)
    print(f"case-level spot sample (10% per class, cap {DE.CAP}, seed "
          f"{DE.CASE_SEED}{', recorded' if checks else ''}):")
    for v, t in table.items():
        print(f"  {v}: sampled {t['sampled']} read {t['read']} "
              f"agree {t['agree']}")
    now = {r["case"]["case_id"]: r for r in out}
    for c in checks:
        if not c["agree"] and c["case"] in now:
            r = now[c["case"]]
            print(f"  disagreed: {c['case']} now {r['final']} "
                  f"({r['decided_by'] if r['decided_by'] != 'rules' else r['rule']})")
    if a.cases:
        Path(a.cases).write_text(json.dumps(cs, indent=1))
    return 0


TRIAGE_DOC = ROOT / "data" / "reports" / "triage-2026-10.md"
UPSTREAM = ROOT / "docs" / "upstream.md"
BEGIN, END = "<!-- t27b:begin (generated) -->", "<!-- t27b:end -->"


def cmd_triage(a) -> int:
    """Every vendor-claim mismatch and omp_vv flag through the
    confirmer (offline), agent decisions applied, the spot-check sample;
    writes results/confirm/triage27b.jsonl, the generated section of
    data/reports/triage-2026-10.md and docs/upstream.md."""
    from offload.engine.confirm import triage as T
    items = T.mismatch_items() + T.flag_items()
    T.run(items, _ctx(False), log=lambda s: print(s, flush=True))
    T.save(items)
    sample = T.spot_sample(items)
    checks = {s["case_id"]: s for s in T.decisions()["spot_checks"]}
    want = {cid for v in sample.values() for cid in v}
    spot = [checks[c] for c in sorted(want) if c in checks]
    missing = sorted(want - set(checks))
    print(f"{len(items)} items; spot sample {len(want)} cases, "
          f"{len(spot)} checked, {len(missing)} not yet")
    for c in missing:
        print("  spot-check needed:", c)
    if not a.no_render:
        md = T.render_tables(items, sample, {"spot": spot})
        text = TRIAGE_DOC.read_text()
        block = f"{BEGIN}\n{md}{END}"
        if BEGIN in text:
            head, rest = text.split(BEGIN, 1)
            text = head + block + rest.split(END, 1)[1]
        else:
            text = text.rstrip("\n") + "\n\n" + block + "\n"
        TRIAGE_DOC.write_text(text)
        UPSTREAM.parent.mkdir(parents=True, exist_ok=True)
        UPSTREAM.write_text(T.render_upstream(items))
    from collections import Counter
    for kind in ("mismatch", "flag"):
        c = Counter(i.disposition for i in items if i.kind == kind)
        print(kind, dict(sorted(c.items())))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("case")
    c.add_argument("files", nargs="+")
    c.add_argument("--toolchain", required=True)
    c.add_argument("--mode", choices=M.MODES)
    c.add_argument("--arch")
    c.add_argument("--version", type=int, default=52)
    c.add_argument("--expected")
    c.add_argument("--outcome")
    c.add_argument("--reason")
    c.add_argument("--value")
    c.add_argument("--run", action="store_true")
    c.add_argument("--repeats", type=int, default=3)
    c.add_argument("--minimize", action="store_true")
    c.add_argument("--draft", action="store_true")
    b = sub.add_parser("batch")
    b.add_argument("--from", dest="sources", nargs="+", required=True)
    b.add_argument("--filter")
    b.add_argument("--toolchains", nargs="*")
    b.add_argument("--out")
    b.add_argument("--run", action="store_true")
    b.add_argument("--repeats", type=int, default=3)
    b.add_argument("--minimize", action="store_true")
    b.add_argument("--draft", action="store_true")
    b.add_argument("--evidence", action="store_true",
                   help="keep the evidence list in each JSON line")
    b.add_argument("--outcomes", nargs="*",
                   help="only cells of these outcome classes")
    b.add_argument("--shard", help="K/N: only the programs of shard K "
                   "of N (tools/jobs/run_confirm_shards.sh)")
    b.add_argument("--store", help="append new evidence to this file "
                   "(reads results/confirm/evidence.jsonl too)")
    b.add_argument("--read", nargs="*", help="more evidence files to read "
                   "(globs under the project root: other shards' stores)")
    v = sub.add_parser("validate")
    v.add_argument("--live", action="store_true",
                   help="also run the live finding reproductions (a "
                   "compute node)")
    r = sub.add_parser("regress")
    r.add_argument("step", choices=("plan", "fuzz", "diff", "confirm",
                                    "report"))
    r.add_argument("--toolchain", required=True)
    r.add_argument("--like", required=True)
    r.add_argument("--submit", action="store_true")
    r.add_argument("--workers", type=int, default=8)
    p = sub.add_parser("promote")
    p.add_argument("draft")
    p.add_argument("name")
    ix = sub.add_parser("index")
    ix.add_argument("--scope", action="store_true", help="derive each "
                    "entry's modes and arch from the batch's linked cells "
                    "(exit 1 when the index differs)")
    ix.add_argument("--write", action="store_true",
                    help="with --scope: rewrite data/findings/index.yaml")
    ix.add_argument("--batch", default=str(OUT / "batch_full.jsonl"))
    sub.add_parser("exec")
    bl = sub.add_parser("backlog")
    bl.add_argument("--batch", default=str(OUT / "batch_full.jsonl"))
    bl.add_argument("--write", action="store_true")
    w = sub.add_parser("witness")
    w.add_argument("--programs", nargs="*")
    w.add_argument("--batch", default=str(OUT / "batch_full.jsonl"))
    de = sub.add_parser("decide")
    de.add_argument("--batch", nargs="+", required=True)
    de.add_argument("--decisions", default=str(ROOT / "catalog" /
                                               "triage_28.yaml"))
    de.add_argument("--out", required=True)
    de.add_argument("--groups", help="write the spot sample's groups "
                    "(JSON) here")
    de.add_argument("--cases", help="write the case-level spot sample "
                    "(JSON, by class) here")
    t = sub.add_parser("triage")
    t.add_argument("--no-render", action="store_true")
    a = ap.parse_args(argv)
    return {"case": cmd_case, "batch": cmd_batch, "validate": cmd_validate,
            "regress": cmd_regress, "promote": cmd_promote,
            "index": cmd_index, "exec": cmd_exec,
            "triage": cmd_triage, "witness": cmd_witness,
            "decide": cmd_decide, "backlog": cmd_backlog}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
