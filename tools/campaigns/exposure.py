#!/usr/bin/env python3
"""Exposure of the findings in public code (offload.engine.exposure), over a snapshot of The Stack
(bigcode/the-stack-dedup, its per-language parquet shards under results/exposure/stack/<lang>).

    python3 -I tools/campaigns/exposure.py fetch LANG [LANG ...]           # the shards (HF_TOKEN)
    python3 -I tools/campaigns/exposure.py scan LANG [LANG ...] [--jobs N]   # a compute node
    python3 -I tools/campaigns/exposure.py queue                       # findings to make controls for
    python3 -I tools/campaigns/exposure.py controls [--minutes M]      # a compute node: make them
    python3 -I tools/campaigns/exposure.py links                       # the example commits still exist
    python3 -I tools/campaigns/exposure.py count

scan keeps the files with an OpenMP or OpenACC directive: their regions and words, in
results/exposure/scan/<lang>/. controls runs tools/reduce.py without reduction steps on each
queued finding: the one-change controls that pass where it fails, in results/exposure/controls/.
count writes site/inputs/exposure.json: per finding its signature and the distinct repositories
and files that have every ingredient."""
from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from offload.engine import exposure as E  # noqa: E402

OUT = ROOT / "results" / "exposure"
STACK = OUT / "stack"
SCAN = OUT / "scan"
CONTROLS = OUT / "controls"
QUEUE = CONTROLS / "queue.jsonl"
FINDINGS = ROOT / "data" / "findings"
TABLE = ROOT / "site" / "inputs" / "exposure.json"
LINKS = OUT / "links.json"
EXAMPLES = 5
DIRECTIVE = re.compile(r"(!\$|#\s*pragma\s+)(omp|acc)\b", re.I)
EXT = {"fortran": ".f90", "c": ".c", "cpp": ".cpp"}


API = "https://huggingface.co/api/datasets/bigcode/the-stack-dedup/tree/main/data/"
URL = "https://huggingface.co/datasets/bigcode/the-stack-dedup/resolve/main/data/"


def _token() -> str:
    import os
    tok = os.environ.get("HF_TOKEN") or ""
    f = Path.home() / ".cache" / "huggingface" / "token"
    if not tok and f.is_file():
        tok = f.read_text().strip()
    if not tok:
        raise SystemExit("fetch: The Stack is gated: accept its terms on Hugging Face and put a read token in "
                         "HF_TOKEN or ~/.cache/huggingface/token")
    return tok


def fetch(langs) -> None:
    """Download the shards of each language not already present at their listed size."""
    import urllib.request
    tok = _token()

    def get(url):
        return urllib.request.urlopen(urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"}))
    for lang in langs:
        d = STACK / lang
        d.mkdir(parents=True, exist_ok=True)
        files = [(x["path"].split("/")[-1], x["size"]) for x in json.load(get(API + lang))]
        for name, size in files:
            p = d / name
            if p.is_file() and p.stat().st_size == size:
                continue
            part = p.with_suffix(".part")
            with get(URL + f"{lang}/{name}") as r, part.open("wb") as fh:
                while chunk := r.read(1 << 22):
                    fh.write(chunk)
            if part.stat().st_size != size:
                raise SystemExit(f"fetch: {lang}/{name}: {part.stat().st_size} bytes, the listing says {size}")
            part.rename(p)
            print(f"{lang}/{name}", flush=True)


def scan_shard(args) -> tuple[str, int, int]:
    import pyarrow.parquet as pq
    lang, shard = args
    out = SCAN / lang / (Path(shard).stem + ".jsonl")
    if out.exists():
        return shard, -1, -1
    out.parent.mkdir(parents=True, exist_ok=True)
    pf = pq.ParquetFile(shard)
    n = kept = 0
    tmp = out.with_suffix(".part")
    with tmp.open("w") as fh:
        for batch in pf.iter_batches(columns=["content", "max_stars_repo_name", "max_stars_repo_path",
                                              "max_stars_repo_head_hexsha", "max_stars_count"],
                                     batch_size=2000):
            d = batch.to_pydict()
            for text, repo, path, sha, stars in zip(d["content"], d["max_stars_repo_name"],
                                                    d["max_stars_repo_path"], d["max_stars_repo_head_hexsha"],
                                                    d["max_stars_count"]):
                n += 1
                if not text or not DIRECTIVE.search(text):
                    continue
                name = path if Path(path).suffix else path + EXT[lang]
                r = E.record(text, name, repo, sha or "", int(stars or 0))
                if not r.regions:
                    continue
                kept += 1
                fh.write(json.dumps({"repo": repo, "path": path,
                                     "regions": [[sorted(f), sorted(w)] for f, w in r.regions],
                                     "words": sorted(r.words), "features": sorted(r.features),
                                     "lines": list(r.lines), "sha": r.sha, "stars": r.stars}) + "\n")
    tmp.rename(out)
    return shard, n, kept


def load_records(everything: bool = False):
    """The scanned files; only application code (offload.engine.exposure.is_application) unless
    `everything`."""
    for f in sorted(SCAN.rglob("*.jsonl")):
        for ln in f.open():
            d = json.loads(ln)
            if not everything and not E.is_application(d["repo"], d["path"]):
                continue
            yield E.Record(d["repo"], d["path"],
                           [(frozenset(a), frozenset(b)) for a, b in d["regions"]],
                           frozenset(d["words"]), frozenset(d["features"]), tuple(d.get("lines", ())),
                           d.get("sha", ""), d.get("stars", 0))


def queue() -> list[dict]:
    from offload.engine import finding_rows as R
    from offload.engine.toolchains import registry
    import yaml
    local = {n for n, t in registry().toolchains.items() if t.machine == "tuolumne"}
    index = {e["file"]: e for e in yaml.safe_load((FINDINGS / "index.yaml").read_text())["findings"]}
    jobs = []
    for rel, sig in E.signatures(FINDINGS, CONTROLS).items():
        if not E.wants_controls(sig) or (CONTROLS / E.job_slug(rel) / "report.md").exists():
            continue
        text = (FINDINGS / rel).read_text(errors="replace")
        if sig is None and not any(r for r in E._parts_of(text, rel)):
            continue                      # no offload region: nothing to measure
        if "RESULT" not in text:
            continue                      # not in the harness's form: no run of it can pass
        named = E.named_compilers(index.get(rel), text)
        if named is None:
            continue
        job = E.control_job(rel, R.evidence_for(rel, text).repro(), local, named)
        if job:
            jobs.append(job)
    CONTROLS.mkdir(parents=True, exist_ok=True)
    QUEUE.write_text("".join(json.dumps(j) + "\n" for j in jobs))
    return jobs


def run_controls(minutes: float, per_job: float) -> None:
    import subprocess
    import time
    stop = time.time() + minutes * 60
    for ln in QUEUE.read_text().splitlines():
        j = json.loads(ln)
        out = CONTROLS / j["slug"]
        if (out / "report.md").exists() or (out / "failed.txt").exists():
            continue
        if time.time() + per_job * 60 > stop:
            print("time budget reached; rerun to continue", flush=True)
            return
        cmd = [sys.executable, "-I", str(ROOT / "tools" / "reduce.py"), "--program", str(FINDINGS / j["finding"]),
               "--name", Path(j["finding"]).stem, "--out", str(out), "--levels", "", "--max-controls", "12",
               "--budget-minutes", str(per_job), "--repeats", "1"]
        for t in j["targets"]:
            cmd += ["--target", t]
        if j.get("reference"):
            cmd += ["--reference", j["reference"]]
        out.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        try:
            r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=per_job * 120)
        except subprocess.TimeoutExpired:
            (out / "failed.txt").write_text(f"stopped after {per_job * 2} min\n")
            print(f"{j['finding']}: stopped after {per_job * 2} min", flush=True)
            continue
        kept = len(list((out / "controls").glob("*-control.*"))) if (out / "controls").is_dir() else 0
        if r.returncode != 0 or not (out / "report.md").exists():
            (out / "failed.txt").write_text(f"exit {r.returncode}\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
        print(f"{j['finding']}: exit {r.returncode}, {kept} controls, {(time.time() - t0) / 60:.1f} min", flush=True)


def table() -> dict:
    """The exposure table: per finding its signature and counts, from the stored scan and the
    generated controls."""
    recs = list(load_records())
    sigs = E.signatures(FINDINGS, CONTROLS)
    live = _live()
    gone = {r.repo for r in recs if live.get(f"{r.repo}@{r.sha}") != "ok"}
    got = E.count(sigs, recs, EXAMPLES, gone)
    rows = {}
    for name, s in sigs.items():
        if not E.measurable(s):
            rows[name] = {"measurable": False}
            continue
        req = s.parts if s.kind == "minimal" else s.requirements
        rows[name] = {"measurable": True, "kind": s.kind, **got[name], "ingredients": E.ingredients(s),
                      "signature": [{"features": sorted(p.features), "words": sorted(p.words),
                                     "file_features": sorted(p.file_features)} for p in req]}
    every = list(load_records(everything=True))
    meta = {"corpus": "bigcode/the-stack-dedup",
            "left_out": {"files": len(every) - len(recs),
                         "repos": len({r.repo for r in every}) - len({r.repo for r in recs}),
                         "why": "compiler and runtime source trees, and files under test directories"},
            "snapshot": "deduplicated; a 2022 snapshot of permissively licensed GitHub files",
            "langs": sorted(p.name for p in SCAN.iterdir() if p.is_dir()),
            "files": len(recs), "repos": len({r.repo for r in recs})}
    return {"meta": meta, "findings": rows}


def _live() -> dict:
    """repo@commit -> "ok" or "gone", from the last links check (results/exposure/links.json)."""
    return json.loads(LINKS.read_text()) if LINKS.is_file() else {}


def links() -> tuple[int, int]:
    """Check every commit a finding could link to (up to twice the examples shown, so a deleted
    one has a replacement) once, with the GitHub API; reads only. Returns (checked, gone)."""
    import subprocess
    recs = list(load_records())
    sigs = {k: s for k, s in E.signatures(FINDINGS, CONTROLS).items() if E.measurable(s)}
    want = {f"{x['repo']}@{x['url'].split('/blob/')[1].split('/')[0]}"
            for v in E.count(sigs, recs, 2 * EXAMPLES).values() for x in v.get("examples", [])}
    live = _live()
    for key in sorted(want - set(live)):
        repo, sha = key.split("@")
        r = subprocess.run(["gh", "api", f"repos/{repo}/commits/{sha}", "--silent"], capture_output=True)
        live[key] = "ok" if r.returncode == 0 else "gone"
    LINKS.write_text(json.dumps(live, indent=1, sort_keys=True) + "\n")
    return len(want), sum(1 for k in want if live[k] == "gone")


def render(t: dict) -> str:
    return json.dumps(t, indent=1, sort_keys=True) + "\n"


def stale() -> list[str]:
    """The committed table differs from the one the stored scan and controls give."""
    return [] if TABLE.is_file() and TABLE.read_text() == render(table()) else [str(TABLE.relative_to(ROOT))]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    fe = sub.add_parser("fetch")
    fe.add_argument("langs", nargs="+")
    s = sub.add_parser("scan")
    s.add_argument("langs", nargs="+")
    s.add_argument("--jobs", type=int, default=32)
    sub.add_parser("count")
    sub.add_parser("queue")
    sub.add_parser("links")
    cc = sub.add_parser("controls")
    cc.add_argument("--minutes", type=float, default=27)
    cc.add_argument("--per-job", type=float, default=4)
    a = ap.parse_args(argv)
    if a.cmd == "fetch":
        fetch(a.langs)
        return 0
    if a.cmd == "scan":
        work = [(lang, str(p)) for lang in a.langs for p in sorted((STACK / lang).glob("*.parquet"))]
        with ProcessPoolExecutor(a.jobs) as ex:
            for shard, n, kept in ex.map(scan_shard, work):
                print(f"{Path(shard).parent.name}/{Path(shard).name}: "
                      + ("done before" if n < 0 else f"{kept} of {n} files"), flush=True)
        return 0
    if a.cmd == "queue":
        jobs = queue()
        print(f"{len(jobs)} findings queued in {QUEUE.relative_to(ROOT)}")
        return 0
    if a.cmd == "links":
        n, g = links()
        print(f"{n} commits checked, {g} gone; {LINKS.relative_to(ROOT)}")
        return 0
    if a.cmd == "controls":
        run_controls(a.minutes, a.per_job)
        return 0
    t = table()
    TABLE.write_text(render(t))
    m = [r for r in t["findings"].values() if r["measurable"]]
    print(f"{t['meta']['files']} offload files in {t['meta']['repos']} repositories; {len(m)} of "
          f"{len(t['findings'])} findings measurable, {sum(1 for r in m if r['repos'])} seen in at least one "
          f"repository; wrote {TABLE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
