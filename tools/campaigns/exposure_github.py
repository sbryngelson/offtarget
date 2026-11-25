#!/usr/bin/env python3
"""Public offload code from GitHub's code search, for the exposure counts (tools/campaigns/exposure.py).

    python3 -I tools/campaigns/exposure_github.py search      # hits: repository, path, commit (resumable)
    python3 -I tools/campaigns/exposure_github.py fetch       # their files, pinned to the commit
    python3 -I tools/campaigns/exposure_github.py stars       # the repositories' stars

search runs every directive term over every source extension, split by file size until a query
has at most 1000 results (the search's cap), at most 10 queries a minute, through `gh api`
(reads only). fetch leaves out what is not application code (offload.engine.exposure
.is_application) and writes results/exposure/stack/github/<n>.jsonl.gz, which `exposure.py scan
github` reads like a Stack shard. Forks are not searched (the search's default)."""
from __future__ import annotations

import argparse
import gzip
import re
import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from offload.engine import exposure as E  # noqa: E402

OUT = ROOT / "results" / "exposure" / "github"
HITS = OUT / "hits.jsonl"
DONE = OUT / "done.txt"
STARS = OUT / "stars.json"
SHARDS = ROOT / "results" / "exposure" / "stack" / "github"
TERMS = ('"omp target"', '"acc parallel"', '"acc kernels"', '"acc data"', '"acc serial"')
EXTS = ("c", "h", "cpp", "cc", "cxx", "hpp", "f", "F", "f90", "F90", "f95", "f03", "f08", "fpp")
CAP, MAX_SIZE = 1000, 400_000
GAP_S = 6.5                     # 10 searches a minute


def _gh(path: str, **params) -> dict:
    args = ["gh", "api", "-X", "GET", path] + [x for k, v in params.items() for x in ("-f", f"{k}={v}")]
    for attempt in range(8):
        r = subprocess.run(args, capture_output=True, text=True)
        if r.returncode == 0:
            return json.loads(r.stdout)
        err = r.stderr + r.stdout
        if "rate limit" in err.lower() or re.search(r"HTTP (403|429|5\d\d)|timeout|connection", err, re.I):
            time.sleep(60 * (attempt + 1))
            continue
        raise RuntimeError(f"gh api {path}: {r.stderr.strip()[:300]}")
    raise RuntimeError(f"gh api {path}: still limited")


def _search(q: str, page: int = 1) -> dict:
    time.sleep(GAP_S)
    return _gh("search/code", q=q, per_page=100, page=page)


def _leaves(term: str, ext: str, lo: int = 0, hi: int = MAX_SIZE):
    """(query, total) slices of one term and extension, each with at most CAP results."""
    q = f"{term} extension:{ext} size:{lo}..{hi}"
    n = _search(q)["total_count"]
    if n <= CAP or hi - lo < 2:
        yield q, n
        return
    mid = (lo + hi) // 2
    yield from _leaves(term, ext, lo, mid)
    yield from _leaves(term, ext, mid + 1, hi)


def search() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    done = set(DONE.read_text().splitlines()) if DONE.is_file() else set()
    with HITS.open("a") as hits, DONE.open("a") as dn:
        for term in TERMS:
            for ext in EXTS:
                key = f"{term} {ext}"
                if key in done:
                    continue
                for q, n in _leaves(term, ext):
                    if not n or q in done:
                        continue
                    for page in range(1, min(10, (n + 99) // 100) + 1):
                        for it in _search(q, page).get("items", []):
                            ref = urllib.parse.parse_qs(urllib.parse.urlparse(it["url"]).query).get("ref", [""])[0]
                            hits.write(json.dumps({"repo": it["repository"]["full_name"], "path": it["path"],
                                                   "ref": ref}) + "\n")
                    hits.flush()
                    dn.write(q + "\n")
                    dn.flush()
                dn.write(key + "\n")
                dn.flush()
                print(f"{key}: done", flush=True)


def _raw(h: dict) -> dict | None:
    url = (f"https://raw.githubusercontent.com/{h['repo']}/{h['ref']}/"
           + urllib.parse.quote(h["path"]))
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return {"content": r.read().decode("utf-8", "replace"), "repo": h["repo"], "path": h["path"],
                        "sha": h["ref"]}
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(5 * (attempt + 1))
        except Exception:
            time.sleep(5 * (attempt + 1))
    return None


def fetch(per_shard: int = 2000, workers: int = 8) -> None:
    SHARDS.mkdir(parents=True, exist_ok=True)
    seen = set()
    for f in SHARDS.glob("*.jsonl.gz"):
        with gzip.open(f, "rt") as fh:
            seen |= {(d["repo"], d["path"]) for d in map(json.loads, fh)}
    want, keys = [], set(seen)
    for ln in HITS.read_text().splitlines():
        h = json.loads(ln)
        k = (h["repo"], h["path"])
        if k in keys or not h["ref"] or not E.is_application(h["repo"], h["path"]):
            continue
        keys.add(k)
        want.append(h)
    print(f"{len(want)} files to fetch ({len(seen)} already)", flush=True)
    n = len(list(SHARDS.glob("*.jsonl.gz")))
    with ThreadPoolExecutor(workers) as ex:
        for i in range(0, len(want), per_shard):
            got = [d for d in ex.map(_raw, want[i:i + per_shard]) if d]
            part = SHARDS / f"{n:05d}.jsonl.gz.part"
            with gzip.open(part, "wt") as fh:
                for d in got:
                    fh.write(json.dumps(d) + "\n")
            part.rename(SHARDS / f"{n:05d}.jsonl.gz")
            n += 1
            print(f"shard {n}: {len(got)} files", flush=True)


def stars() -> None:
    """The stars of every repository with a fetched file (one read each)."""
    have = json.loads(STARS.read_text()) if STARS.is_file() else {}
    repos = set()
    for f in SHARDS.glob("*.jsonl.gz"):
        with gzip.open(f, "rt") as fh:
            repos |= {d["repo"] for d in map(json.loads, fh)}
    for i, r in enumerate(sorted(repos - set(have))):
        try:
            have[r] = _gh(f"repos/{r}").get("stargazers_count", 0)
        except RuntimeError:
            have[r] = 0
        if i % 200 == 0:
            STARS.write_text(json.dumps(have, sort_keys=True))
    STARS.write_text(json.dumps(have, sort_keys=True))
    print(f"{len(have)} repositories", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=("search", "fetch", "stars"))
    a = ap.parse_args(argv)
    {"search": search, "fetch": fetch, "stars": stars}[a.cmd]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
