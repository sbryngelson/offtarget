#!/usr/bin/env python3
"""The leads of runs (offload.engine.leads): each failure checked against the catalog's findings,
grouped by signature; known, related and new groups, each new one with the program to reduce.

    python3 -I tools/campaigns/leads.py scan RUN_DIR [RUN_DIR ...]   # results/fuzz/<run>
    python3 -I tools/campaigns/leads.py plan RUN_DIR [RUN_DIR ...]   # the reduction queue
    python3 -I tools/campaigns/leads.py reduce [--minutes M]          # a compute node: run the queue
    python3 -I tools/campaigns/leads.py recheck                       # the reduced programs vs the catalog
    python3 -I tools/campaigns/leads.py advance [--minutes M]         # a compute node: the confirmer on new ones
    python3 -I tools/campaigns/leads.py clusters                      # the confirmed drafts as candidate bugs
    python3 -I tools/campaigns/leads.py deepen [--minutes M]          # a compute node: reduce stopped drafts further
    python3 -I tools/campaigns/leads.py write | cases | finish        # the drafts as findings (compute node)

Outputs are under results/leads/ (docs/tooling/contributing.md, "Leads of a run"): the groups of a
scan, queue.jsonl of plan, rechecked.jsonl of recheck, clusters.json of clusters."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from offload.engine import leads as LD  # noqa: E402

OUT = ROOT / "results" / "leads"


def scan(run_dir: Path) -> list:
    groups = LD.fuzz_groups(run_dir)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"fuzz-{Path(run_dir).name}.jsonl"
    with path.open("w") as fh:
        for g in groups:
            rep = g.representative.failure
            fh.write(json.dumps({"family": g.family, "signature": g.signature, "status": g.status,
                                 "findings": list(g.findings), "failures": len(g.leads),
                                 "unexplained": sorted({lead.failure.program_id for lead in g.unexplained}, key=int),
                                 "programs": sorted({lead.failure.program_id for lead in g.leads}, key=int),
                                 "toolchains": sorted({lead.failure.toolchain for lead in g.leads}),
                                 "representative": {"program_id": rep.program_id, "toolchain": rep.toolchain,
                                                    "mode": rep.mode, "lines": rep.lines}}) + "\n")
    c = Counter(g.status for g in groups)
    print(f"{run_dir}: {sum(len(g.leads) for g in groups)} failures in {len(groups)} groups: "
          f"{c['known']} known, {c['related']} related, {c['mixed']} mixed, {c['unsupported']} declared unsupported, "
          f"{c['new']} new "
          f"-> {path.relative_to(ROOT)}")
    for g in groups:
        if g.status in ("new", "mixed"):
            rep = g.representative.failure
            print(f"  {g.status:5} {g.family:6} {len(g.unexplained):4}/{len(g.leads):<4} unexplained  seed "
                  f"{rep.program_id} on {rep.toolchain}/{rep.mode} ({rep.lines} lines)  {g.signature[:80]}")
    return groups


QUEUE = OUT / "queue.jsonl"


def _meta(run_dir: Path) -> dict:
    p = Path(run_dir) / "meta.json"
    return ((json.loads(p.read_text()).get("sessions") or [{}])[0]) if p.is_file() else {}


def plan(run_dir: Path) -> int:
    groups = LD.fuzz_groups(run_dir)
    meta = _meta(run_dir)
    q = LD.reduce_queue(groups, str(Path(run_dir).relative_to(ROOT) if Path(run_dir).is_absolute() else run_dir),
                        meta.get("opt") or "-O2", int(meta.get("xnack") or 0))
    old = [json.loads(x) for x in QUEUE.read_text().splitlines() if x.strip()] if QUEUE.is_file() else []
    OUT.mkdir(parents=True, exist_ok=True)
    now = {e["name"]: e for e in q}
    # an unfinished reduction takes the command computed now; a finished one keeps the one it ran with
    kept = [now[e["name"]] if e["name"] in now and not _done(e) else e for e in old]
    have = {e["name"] for e in old}
    new = [e for e in q if e["name"] not in have]
    QUEUE.write_text("".join(json.dumps(e) + "\n" for e in kept + new))
    print(f"{run_dir}: {len(new)} reductions queued ({len(q) - len(new)} already) -> {QUEUE.relative_to(ROOT)}")
    return 0


def _done(e: dict) -> bool:
    d = ROOT / e["argv"][-1]
    return any((d / f).is_file() for f in ("report.md", "covered.json", "failed.json"))


def _result(e: dict):
    """(reduced program path, its failing row on the target) of a finished reduction, or None."""
    d = ROOT / e["argv"][-1]
    prog = next((p for p in sorted(d.glob(e["name"] + ".*")) if p.suffix in (".f90", ".c", ".F90")), None)
    rows = d / "rows.jsonl"
    if prog is None or not rows.is_file() or not (d / "report.md").is_file():
        return None
    tc = e["target"].split("/")[0]
    row = next((json.loads(x) for x in rows.read_text().splitlines()
                if x.strip() and json.loads(x).get("toolchain") == tc), {})
    return prog, row


def reduce(minutes: float) -> int:
    """The unfinished reductions of the queue, in order, until `minutes` pass (a compute node)."""
    end = time.time() + minutes * 60
    todo = [json.loads(x) for x in QUEUE.read_text().splitlines() if x.strip()] if QUEUE.is_file() else []
    todo = sorted((e for e in todo if not _done(e)), key=lambda e: tuple(e.get("priority") or (9, 0)))
    print(f"{len(todo)} reductions left")
    every = [json.loads(x) for x in QUEUE.read_text().splitlines() if x.strip()] if QUEUE.is_file() else []
    for e in todo:
        left = (end - time.time()) / 60
        if left < 3:
            break
        # a lead a finished reduction already explains is not reduced again
        provs = [LD.provisional(d, r[0].read_text(), r[1]) for d in every if "text" in d and (r := _result(d))]
        by = LD.covered(e, provs) if "text" in e else None
        if by:
            out = ROOT / e["argv"][-1]
            out.mkdir(parents=True, exist_ok=True)
            (out / "covered.json").write_text(json.dumps({"by": by}) + "\n")
            print(f"covered {e['name']} by {by}", flush=True)
            continue
        argv = list(e["argv"])
        i = argv.index("--budget-minutes")
        argv[i + 1] = str(int(min(float(argv[i + 1]), left - 1)))
        print(f"reduce {e['name']} ({argv[i + 1]} min)", flush=True)
        p = subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "reduce.py"), *argv], cwd=ROOT)
        out = ROOT / e["argv"][-1]
        if p.returncode == 1 and not (out / "report.md").is_file():
            # the original does not fail as recorded, the witness refuses it, or no oracle: finished,
            # with the reason (exit 2, a runner or checkpoint problem, is tried again)
            log = (out / "log.txt").read_text().splitlines() if (out / "log.txt").is_file() else []
            out.mkdir(parents=True, exist_ok=True)
            (out / "failed.json").write_text(json.dumps({"reason": (log[-1] if log else "exit 1")[:400]}) + "\n")
    print(f"{sum(1 for e in todo if not _done(e))} reductions left")
    return 0


def recheck() -> int:
    """Each finished reduction's program asked of the catalog with its failure (the reduction keeps
    the failure's signature on its target): known, related or new."""
    from offload.engine.confirm import findings as F
    entries = [json.loads(x) for x in QUEUE.read_text().splitlines() if x.strip()] if QUEUE.is_file() else []
    out = []
    for e in entries:
        got = _result(e)
        if got is None:
            continue
        prog, row = got
        tc = e["target"].split("/")[0]
        lang = "c" if prog.suffix == ".c" else "f90"
        outcome = __import__("offload.engine.gate", fromlist=["outcome_class"]).outcome_class(dict(row, toolchain=tc))
        hits = F.dedupe(tc, lang, outcome, row.get("reason") or "", prog.read_text(), related=True,
                        output=row.get("output") or "")
        kind = "known" if any(h["kind"] == "duplicate" for h in hits) else ("related" if hits else "new")
        out.append({"name": e["name"], "family": e["family"], "group": e["group"], "status": kind, "target": e["target"],
                    "findings": [h["file"] for h in hits], "program": str(prog.relative_to(ROOT)),
                    "lines": sum(1 for x in prog.read_text().splitlines() if x.strip())})
        print(f"  {kind:7} {e['name']:40} {out[-1]['lines']:4} lines  {', '.join(out[-1]['findings'][:2])}")
    (OUT / "rechecked.jsonl").write_text("".join(json.dumps(r) + "\n" for r in out))
    return 0


def _result_json(stdout: str) -> dict | None:
    """The confirmer's result: the JSON object it prints (indented) after any notes."""
    lines = stdout.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("{"):
            try:
                return json.loads("\n".join(lines[i:]))
            except ValueError:
                continue
    return None


def _witness(prog: Path) -> None:
    """The independent checkers' verdicts on a reduction (Intel here, NVHPC over ssh;
    offload.engine.confirm.witness), stored where the confirmer's legality step reads them
    (witness.add_file_rows), keyed as the confirmer keys the program; a checker that cannot run or
    be reached adds nothing, and a stored program is not checked again."""
    from offload.engine import autodraft as AD
    from offload.engine.confirm import programs as P
    from offload.engine.confirm import witness as W
    if not prog.is_file():
        return
    ref = P.file_ref([str(prog)])
    have = {(r["program"], r["sha256"], r["checker"]) for r in W._all_rows()}
    lang = "c" if prog.suffix == ".c" else "f90"
    rows = []
    for name in W.names_for(lang, AD.model_of(ref.text)):
        if (ref.ident, ref.sha, name) in have:
            continue
        try:
            rows.append(W.check(ref.ident, ref.text, lang, ref.sha, AD.model_of(ref.text), name))
        except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as e:
            print(f"  {name}: no verdict ({str(e)[:80]})", flush=True)
    if rows:
        W.add_file_rows(rows)


def advance(minutes: float) -> int:
    """The confirmer (tools/confirm.py case --run --draft) on each reduction recheck found new, once:
    it runs the case and the evidence cells, applies the legality witnesses, decides the verdict and
    writes a draft (results/confirm/drafts/; promoting one is a person's step). Its result is the
    reduction's confirm.json."""
    end = time.time() + minutes * 60
    path = OUT / "rechecked.jsonl"
    rows = [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.is_file() else []
    for r in rows:
        if r["status"] != "new":
            continue
        prog = ROOT / r["program"]
        done = prog.parent / "confirm.json"
        if done.is_file():
            continue
        if (end - time.time()) / 60 < 3:
            break
        _witness(prog)
        tc, xn = r["target"].split("/")
        mode = LD.MODES.get(int(xn), "copy")
        # a reduction that checks itself (RESULT ... check=) against the value its reference gave (the
        # elision or a host run of another family, never the failing compiler) claims check=pass
        claim = ["--expected", "check=pass"] if prog.is_file() and re.search(
            r"RESULT[^\n]*check=", prog.read_text(errors="replace")) else []
        argv = [sys.executable, "-I", str(ROOT / "tools" / "confirm.py"), "case", str(prog), *claim,
                "--toolchain", tc, "--mode", mode, "--run", "--draft"]
        print(f"confirm {r['name']}", flush=True)
        try:
            p = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=max(60, int(end - time.time())))
        except subprocess.TimeoutExpired:
            print("  not finished in this job: a later job tries again", flush=True)
            break
        res = _result_json(p.stdout) or {"verdict": "error", "reason": (p.stderr or p.stdout)[-400:]}
        if res.get("verdict") == "environment" and "could not run here" in str(res.get("reason")):
            print(f"  not run: {res.get('reason')}", flush=True)     # no result: a later job tries again
            continue
        done.write_text(json.dumps(res) + "\n")
        print(f"  {res.get('verdict')}  {(res.get('drafts') or [''])[0][-60:] or str(res.get('reason', ''))[:100]}", flush=True)
    return 0


def _stopped(e: dict) -> bool:
    """The reduction's last run stopped at its budget (its log's last "reduced:" line says so)."""
    log = ROOT / e["argv"][-1] / "log.txt"
    last = [x for x in log.read_text().splitlines() if "reduced:" in x][-1:] if log.is_file() else []
    return bool(last) and "stopped at the budget" in last[0]


def deepen(minutes: float, budget: int = 25, workers: int = 4, rows_only: bool = False) -> int:
    """The confirmed drafts (confirm.json compiler_bug) whose reduction stopped at its budget,
    resumed from their checkpoints with a larger budget and `workers` candidates at once (a compute
    node: one per GPU), until `minutes` pass. A program that changed loses its confirm.json, so
    advance confirms the smaller one."""
    end = time.time() + minutes * 60
    entries = [json.loads(x) for x in QUEUE.read_text().splitlines() if x.strip()] if QUEUE.is_file() else []
    if rows_only:
        # a finished or stopped reduction with no final rows: resumed briefly, its final rows are recorded
        todo = [e for e in entries if not (_result(e) or (None, {}))[1]
                and (ROOT / e["argv"][-1] / "report.md").is_file()]
    else:
        todo = [e for e in entries if _stopped(e) and (ROOT / e["argv"][-1] / "confirm.json").is_file()
                and json.loads((ROOT / e["argv"][-1] / "confirm.json").read_text()).get("verdict") == "compiler_bug"]
    print(f"{len(todo)} drafts to reduce further")
    for e in todo:
        left = (end - time.time()) / 60
        if left < 5:
            break
        d = ROOT / e["argv"][-1]
        prog = next((p for p in sorted(d.glob(e["name"] + ".*")) if p.suffix in (".f90", ".c", ".F90")), None)
        before = prog.read_text() if prog else ""
        argv = list(e["argv"])
        i = argv.index("--budget-minutes")
        argv[i + 1] = str(int(min(budget, left - 2)))
        argv = argv[:-2] + ["--workers", str(workers)] + argv[-2:]
        print(f"deepen {e['name']} ({argv[i + 1]} min, {workers} workers)", flush=True)
        subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "reduce.py"), *argv], cwd=ROOT)
        if prog and prog.is_file() and prog.read_text() != before:
            (d / "confirm.json").unlink(missing_ok=True)
    return 0


def clusters() -> int:
    """The confirmed drafts (confirm.json verdict compiler_bug) grouped into candidate bugs
    (offload.engine.leads.clusters): results/leads/clusters.json, one cluster per entry."""
    entries = [json.loads(x) for x in QUEUE.read_text().splitlines() if x.strip()] if QUEUE.is_file() else []
    drafts = []
    for e in entries:
        got = _result(e)
        conf = ROOT / e["argv"][-1] / "confirm.json"
        if got is None or not conf.is_file() or "text" not in e:
            continue
        res = json.loads(conf.read_text())
        if res.get("verdict") != "compiler_bug":
            continue
        prog, row = got
        drafts.append(dict(e, reduced=prog.read_text(), row=row, program=str(prog.relative_to(ROOT)),
                           drafts=res.get("drafts") or []))
    out = []
    for c in LD.clusters(drafts):
        rep = min(c, key=lambda d: (len(d["reduced"].splitlines()), d["name"]))
        out.append({"family": c[0]["family"], "outcome": c[0]["outcome"],
                    "toolchains": sorted({d["target"].split("/")[0] for d in c}),
                    "representative": rep["name"], "program": rep["program"], "draft": (rep["drafts"] or [""])[0],
                    "members": [d["name"] for d in c]})
        print(f"{len(c):3}  {out[-1]['family']:5} {out[-1]['outcome']:12} {','.join(out[-1]['toolchains']):18} "
              f"{rep['name']}  {(rep['row'].get('reason') or '')[:60]}")
    (OUT / "clusters.json").write_text(json.dumps(out, indent=1) + "\n")
    print(f"{len(drafts)} drafts in {len(out)} clusters -> {(OUT / 'clusters.json').relative_to(ROOT)}")
    return 0


LEDGER = OUT / "published.json"


def _ledger() -> dict:
    return json.loads(LEDGER.read_text()) if LEDGER.is_file() else {}


def _words(rep: dict, link: bool) -> dict:
    """The generated words of a cluster's representative (offload.engine.autodraft)."""
    from offload.engine import autodraft as AD
    from offload.engine.confirm import findings as F
    from offload.engine.toolchains import TOOLCHAINS
    d = ROOT / rep["argv"][-1]
    tc = rep["target"].split("/")[0]
    t = TOOLCHAINS[tc]
    report = (d / "report.md").read_text() if (d / "report.md").is_file() else ""
    keys = AD.control_constructs(report)
    if not keys:
        prog = next(p for p in sorted(d.glob(rep["name"] + ".*")) if p.suffix in (".f90", ".c"))
        keys = sorted(F._key_constructs(prog.read_text()))[:3]
    prog_text = next(p for p in sorted(d.glob(rep["name"] + ".*")) if p.suffix in (".f90", ".c")).read_text()
    lang, model, outcome = rep.get("lang", "f90"), AD.model_of(prog_text), rep["outcome"]
    res = json.loads((d / "confirm.json").read_text())
    return {"keys": keys, "name": AD.name(t.family.id if t.family.id != "cce" else tc, outcome, keys),
            "title": AD.title(t.label, outcome, lang, model, keys, link), "expected": AD.expected_text(res),
            "rule": AD.rule(keys, model, outcome), "legality": AD.legality_text(res),
            "site_title": AD.site_title(t.family.name, outcome, keys),
            "site_summary": AD.site_summary(t.label, outcome, keys, lang, model, link)}


def _new_finding(rep: dict, name: str, case: str | None, programs: list | None = None) -> int:
    d = ROOT / rep["argv"][-1]
    prog = next(p for p in sorted(d.glob(rep["name"] + ".*")) if p.suffix in (".f90", ".c"))
    argv = [sys.executable, "-I", str(ROOT / "tools" / "new_finding.py"), str(prog), "--campaign", "leads",
            "--rows", str(d / "rows.jsonl"), "--name", name, "--dir", "fuzz", "--write"]
    ctl = sorted((d / "controls").glob("*")) if (d / "controls").is_dir() else []
    if ctl:
        argv += ["--control", *map(str, ctl)]
    if case:
        argv += ["--case", case]
    if programs:
        argv += ["--programs", *programs]       # the campaign programs it stands for (run:seed)
    return subprocess.run(argv, cwd=ROOT).returncode


def _fill(entry: dict, rep: dict, keep_expected: bool) -> None:
    from offload.engine import autodraft as AD
    w = _words(rep, entry.get("link", False))
    AD.fill(ROOT / "data" / "findings" / entry["file"], title=w["title"],
            expected=None if keep_expected else w["expected"], rule=w["rule"], legality=w["legality"],
            site_title=w["site_title"], site_summary=w["site_summary"])


def write(limit: int = 0) -> int:
    """Each cluster's representative not yet written becomes a finding (tools/new_finding.py --write
    from its reduction's rows and controls) with its generated words, and a site check case
    (tools/derive/finding_matrix.py cases); the ledger is results/leads/published.json."""
    led = _ledger()
    queue = {json.loads(x)["name"]: json.loads(x) for x in QUEUE.read_text().splitlines() if x.strip()}
    done = 0
    for c in json.loads((OUT / "clusters.json").read_text()):
        rep = queue.get(c["representative"])
        if rep is None or rep["name"] in led or (limit and done >= limit):
            continue
        if not (ROOT / rep["argv"][-1] / "confirm.json").is_file() or not (_result(rep) or (None, {}))[1]:
            print(f"{rep['name']}: no confirmation or no final rows yet")
            continue
        row = (_result(rep) or (None, {}))[1]
        link = "undefined symbol" in (row.get("reason") or "")
        w = _words(rep, link)
        name, n = w["name"], 2
        while (ROOT / "data" / "findings" / "fuzz" / f"{name}.{'c' if rep.get('lang') == 'c' else 'f90'}").exists():
            name, n = f"{w['name']}-{n}", n + 1
        programs = [queue[m]["program_ref"] for m in c["members"] if m in queue and queue[m].get("program_ref")]
        if _new_finding(rep, name, None, programs) != 0:
            print(f"{rep['name']}: new_finding failed"); continue
        ext = "c" if rep.get("lang") == "c" else "f90"
        entry = {"file": f"fuzz/{name}.{ext}", "case": f"site-fuzz--{name}", "link": link, "members": c["members"],
                 "programs": programs}
        _fill(entry, rep, keep_expected=False)
        led[rep["name"]] = entry
        LEDGER.write_text(json.dumps(led, indent=1) + "\n")
        print(f"wrote {entry['file']}: {w['title']}")
        done += 1
    for entry in led.values():
        subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "derive" / "finding_matrix.py"), "cases",
                        "--control", entry["file"]], cwd=ROOT, capture_output=True)
    return 0


def cases() -> int:
    """The check cases of the written findings that are not finished (for run_leads_gate.sh)."""
    print(",".join(e["case"] for e in _ledger().values() if not e.get("finished")))
    return 0


def _gated(case: str) -> bool:
    import glob
    envs = set()
    for f in glob.glob(str(ROOT / "data" / "vendor" / "checks" / "results" / "site-tuolumne*.jsonl")):
        for ln in open(f):
            if f'"{case}"' in ln:
                envs.add(json.loads(ln).get("env"))
    return {"a", "b", "c", "d"} <= envs


def _reproduced(case: str, rel: str, tc: str) -> bool:
    """The gate's rows of the case show the program failing on its compiler (a repro row not
    classified as passing; offload.engine.finding_rows.site_obs)."""
    import glob
    from offload.engine import finding_rows as R
    from offload.engine.site import matrix as M
    rows = []
    for f in glob.glob(str(ROOT / "data" / "vendor" / "checks" / "results" / "site-tuolumne*.jsonl")):
        rows += [json.loads(ln) for ln in open(f) if f'"{case}"' in ln]
    c = next((x for x in M._cases() if x["id"] == case), None)
    if c is None:
        return False
    return any(o.tc == tc and o.variant == "repro" and o.failed for o in R.site_obs(c, rows))


def _pack(case: str) -> None:
    import glob
    import tempfile
    from offload.engine.site import matrix as M
    tmp = Path(tempfile.mkdtemp())
    files = []
    for f in sorted(glob.glob(str(ROOT / "data" / "vendor" / "checks" / "results" / "site-tuolumne*.jsonl"))):
        rows = [ln for ln in open(f) if ln.strip() and json.loads(ln).get("case") == case]
        if rows:
            (tmp / Path(f).name).write_text("".join(rows))
            files.append(tmp / Path(f).name)
    M.pack(files, ROOT / "data" / "vendor" / "checks" / "results-site")


def _unwrite(rel: str) -> None:
    """Remove a written finding, its controls and its index entry (new_finding does not overwrite)."""
    idx = ROOT / "data" / "findings" / "index.yaml"
    s = idx.read_text()
    a = s.find(f"  - file: {rel}\n")
    if a != -1:
        b = s.find("\n  - file:", a + 10)
        idx.write_text(s[:a] + s[b + 1:] if b != -1 else s[:a])
    f = ROOT / "data" / "findings" / rel
    for ln in (f.read_text().splitlines() if f.is_file() else []):
        m = re.match(r"^\S+ control: (fuzz/controls/\S+)", ln)
        if m:
            (ROOT / "data" / "findings" / m.group(1)).unlink(missing_ok=True)
    f.unlink(missing_ok=True)
    # its legality record (tools/review/review.py mechanical) goes with it
    (ROOT / "data" / "findings" / "reviews" / (rel.rsplit(".", 1)[0].replace("/", "--") + ".json")).unlink(missing_ok=True)


def finish() -> int:
    """Each written finding whose case has rows in all four gate environments: its rows packed into
    the committed site rows, the finding drafted again from them (--case), its words filled again
    (the expected line from a passing row) and its legality record computed; then the site inputs."""
    led = _ledger()
    queue = {json.loads(x)["name"]: json.loads(x) for x in QUEUE.read_text().splitlines() if x.strip()}
    for name, e in led.items():
        if e.get("finished") or not _gated(e["case"]):
            continue
        rep = queue[name]
        tc = rep["target"].split("/")[0]
        if not _reproduced(e["case"], e["file"], tc):
            # the gate does not show the failure on its compiler: no finding
            _unwrite(e["file"])
            e["finished"], e["not_reproduced"] = True, True
            LEDGER.write_text(json.dumps(led, indent=1) + "\n")
            print(f"not reproduced in the gate: {e['file']} on {tc}")
            continue
        _pack(e["case"])
        _unwrite(e["file"])
        if _new_finding(rep, Path(e["file"]).stem, e["case"], e.get("programs")) != 0:
            print(f"{e['file']}: new_finding --case failed"); continue
        text = (ROOT / "data" / "findings" / e["file"]).read_text()
        _fill(e, rep, keep_expected="- expected: TODO(human)" not in text)
        fid = e["file"].rsplit(".", 1)[0]
        subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "review" / "review.py"), "mechanical", fid], cwd=ROOT)
        e["finished"] = True
        LEDGER.write_text(json.dumps(led, indent=1) + "\n")
        print(f"finished {e['file']}")
    subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "site" / "site_inputs.py")], cwd=ROOT)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("runs", nargs="+", type=Path)
    pl = sub.add_parser("plan")
    pl.add_argument("runs", nargs="+", type=Path)
    rd = sub.add_parser("reduce")
    rd.add_argument("--minutes", type=float, default=25)
    sub.add_parser("recheck")
    sub.add_parser("clusters")
    wr = sub.add_parser("write")
    wr.add_argument("--limit", type=int, default=0)
    sub.add_parser("cases")
    sub.add_parser("finish")
    dp = sub.add_parser("deepen")
    dp.add_argument("--minutes", type=float, default=20)
    dp.add_argument("--budget", type=int, default=25)
    dp.add_argument("--workers", type=int, default=4)
    dp.add_argument("--rows-only", action="store_true", help="record the final rows of stopped reductions")
    ad = sub.add_parser("advance")
    ad.add_argument("--minutes", type=float, default=10)
    a = ap.parse_args(argv)
    if a.cmd == "advance":
        return advance(a.minutes)
    if a.cmd == "clusters":
        return clusters()
    if a.cmd == "write":
        return write(a.limit)
    if a.cmd == "cases":
        return cases()
    if a.cmd == "finish":
        return finish()
    if a.cmd == "deepen":
        return deepen(a.minutes, a.budget, a.workers, a.rows_only)
    if a.cmd == "reduce":
        return reduce(a.minutes)
    if a.cmd == "recheck":
        return recheck()
    for r in a.runs:
        scan(r) if a.cmd == "scan" else plan(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
