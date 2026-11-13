#!/usr/bin/env python3
"""Harvest known offload bugs from centre known-issues pages, the NVIDIA HPC
compilers forum, NVHPC release notes and open offload codes' workaround
history. Downloads go outside the repo (default
harvest-src/t49b); run with ``python3 -I`` from
outside it. Every network access is a read-only GET.

    python3 -I tools/campaigns/harvest_known.py STEP ARGS...

STEP: forum-fetch, forum-scan, centre-git [--src DIR]; centre-archive-fetch,
centre-scan; app-commits NAME..; app-issues OWNER/REPO; legality [--bench
DIR]; export; overlap; via49a run|gate ARGS; verdicts, summary, tables,
confirm RUNDIR...; probe FILE... --toolchains T --modes X; holdout RUNDIR...
--commit C. legality and confirm run on a compute node. via49a drives
tools/campaigns/harvest.py (or the pinned copy PIN_49A in
results/harvest-known/_harvest_49a.py)."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine.harvest_known import apps, cases, centres, forum  # noqa: E402

SRC = Path("harvest-src/t49b")
OUT = ROOT / "results" / "harvest-known"


def cmd_forum_fetch(a) -> int:
    """Listings, then every topic: highest title priority first (offload
    and defect words), two polite workers."""
    from concurrent.futures import ThreadPoolExecutor
    src = Path(a.src) / "nvforum"
    titles: dict[int, str] = {}
    for cat in forum.CATEGORIES:
        got = forum.fetch_category(cat, src / "list")
        print(f"category {cat}: {len(got)} topics", flush=True)
    for f in sorted((src / "list").glob("c*-p*.json")):
        titles.update(forum.listing_titles(json.loads(f.read_text())))
    ids = sorted(titles, key=lambda t: (-forum.title_priority(titles[t]), -t))
    (src / "ids.json").write_text(json.dumps(ids))
    todo = [t for t in ids if not (src / "topics" / f"t{t}.json").is_file()]
    print(f"{len(ids)} topics, {len(todo)} to fetch", flush=True)

    def one(tid):
        try:
            forum.fetch_topic(tid, src / "topics")
        except Exception as e:  # noqa: BLE001 - record and go on
            print(f"topic {tid}: {e}", flush=True)
    with ThreadPoolExecutor(max_workers=2) as ex:
        for k, _ in enumerate(ex.map(one, todo)):
            if k % 200 == 0:
                print(f"{k}/{len(todo)}", flush=True)
    return 0


def cmd_forum_scan(a) -> int:
    src = Path(a.src) / "nvforum" / "topics"
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for f in sorted(src.glob("t*.json")):
        try:
            rows.append(forum.topic_record(json.loads(f.read_text())))
        except (ValueError, KeyError) as e:
            print(f"{f.name}: {e}", file=sys.stderr)
    for r in rows:
        r["stage"] = forum.stage(r)
    with open(OUT / "forum-inventory.jsonl", "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    print(json.dumps(Counter(r["stage"] for r in rows), sort_keys=True))
    return 0


# --- centres ------------------------------------------------------------------------
# docs repositories (cloned into SRC/git) whose history is the archive
CENTRE_REPOS = {"olcf": "olcf-user-docs", "nersc": "nersc.gitlab.io",
                "alcf": "user-guides", "lumi": "lumi-userguide",
                "csc": "csc-user-guide"}
# pages whose known issues are built in at publication (OLCF: from JIRA)
ARCHIVE_PAGES = {
    "olcf": ["docs.olcf.ornl.gov/systems/frontier_user_guide.html",
             "docs.olcf.ornl.gov/systems/crusher_quick_start_guide.html",
             "docs.olcf.ornl.gov/systems/summit_user_guide.html",
             "docs.olcf.ornl.gov/systems/spock_quick_start_guide.html"],
    "nersc": ["docs.nersc.gov/current/",
              "docs.nersc.gov/development/programming-models/openmp/"
              "openmp/",
              "docs.nersc.gov/development/programming-models/openacc/"],
    "alcf": ["docs.alcf.anl.gov/aurora/known-issues/",
             "docs.alcf.anl.gov/polaris/known-issues/"],
    "lumi": ["docs.lumi-supercomputer.eu/helpdesk/issues/",
             "docs.lumi-supercomputer.eu/development/compiling/gpu/"],
}
PICKAXE = (r"(OpenACC|!\$acc|pragma acc|omp target|OpenMP offload|"
           r"offload|declare target|-mp=gpu|-hacc|fopenmp-targets|"
           r"offload-arch|nvfortran|crayftn|amdflang|CCE)")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True, errors="replace",
                          timeout=600).stdout


def _sections(name: str, text: str) -> list[dict]:
    if name.endswith(".rst"):
        return centres.rst_sections(text)
    if name.endswith((".html", ".htm")):
        return centres.html_sections(text)
    return centres.md_sections(text)


def cmd_centre_git(a) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for src, name in CENTRE_REPOS.items():
        repo = Path(a.src) / "git" / name
        log = _git(repo, "log", "--format=@@%H %ad", "--date=short",
                   "--name-only", "-G", PICKAXE, "--", "*.md", "*.rst")
        pairs: list[tuple[str, str, str]] = []
        cur = None
        for ln in log.splitlines():
            if ln.startswith("@@"):
                h, d = ln[2:].split()
                cur = (h, d)
            elif ln.strip() and cur:
                pairs.append((cur[0], cur[1], ln.strip()))
        n = 0
        for h, d, f in pairs:
            try:
                text = _git(repo, "show", f"{h}:{f}")
            except subprocess.CalledProcessError:
                continue   # deleted in this commit
            for sec in _sections(f, text):
                if centres.relevant(sec):
                    rows.append({"source": src, "page": f, "snapshot": d,
                                 "commit": h[:12], **sec})
                    n += 1
        print(f"{src}: {len(pairs)} file versions, {n} relevant sections",
              flush=True)
    with open(OUT / "centre-git-sections.jsonl", "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return 0


def cmd_centre_archive_fetch(a) -> int:
    dst = Path(a.src) / "web" / "archive"
    dst.mkdir(parents=True, exist_ok=True)
    for src, pages in ARCHIVE_PAGES.items():
        for page in pages:
            slug = re.sub(r"[^A-Za-z0-9]+", "_", page).strip("_")
            cdx = dst / f"{slug}.cdx.json"
            if not cdx.is_file():
                url = ("http://web.archive.org/cdx/search/cdx?url=" + page +
                       "&output=json&collapse=timestamp:6"
                       "&filter=statuscode:200")
                cdx.write_bytes(forum._get(url))
                time.sleep(3)
            try:
                snaps = [r[1] for r in json.loads(cdx.read_text() or
                                                  "[]")[1:]]
            except ValueError:
                snaps = []
            for ts in snaps:
                f = dst / f"{src}__{slug}__{ts}.html"
                if f.is_file():
                    continue
                try:
                    f.write_bytes(forum._get(
                        f"http://web.archive.org/web/{ts}id_/https://{page}"))
                except Exception as e:  # noqa: BLE001
                    print(f"{page} {ts}: {e}", flush=True)
                time.sleep(3)
            print(f"{src} {page}: {len(snaps)} snapshots", flush=True)
            live = dst / f"{src}__{slug}__live.html"
            if not live.is_file():
                try:
                    live.write_bytes(forum._get(f"https://{page}"))
                except Exception as e:  # noqa: BLE001
                    print(f"{page} live: {e}", flush=True)
    return 0


def cmd_centre_scan(a) -> int:
    rows: list[dict] = []
    for f in sorted((Path(a.src) / "web" / "archive").glob("*__*__*.html")):
        src, slug, ts = f.stem.split("__")
        snap = (time.strftime("%Y-%m-%d") if ts == "live" else
                f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}")
        for sec in centres.html_sections(f.read_text(errors="replace")):
            if centres.relevant(sec):
                rows.append({"source": src, "page": slug, "snapshot": snap,
                             **sec})
    gitrows = OUT / "centre-git-sections.jsonl"
    if gitrows.is_file():
        rows += [json.loads(x) for x in gitrows.read_text().splitlines()]
    ent = centres.union(rows)
    with open(OUT / "centre-inventory.jsonl", "w") as fh:
        for e in ent:
            fh.write(json.dumps(e) + "\n")
    print(json.dumps(Counter(e["source"] for e in ent), sort_keys=True))
    return 0


# --- applications -------------------------------------------------------------------

def cmd_app_commits(a) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name in a.names:
        repo = Path(a.src) / "git" / name
        recs = apps.parse_log(_git(repo, "log", "--format=%x1e%H %ad%n%B",
                                   "--date=short"))
        hits = [r for r in recs
                if apps.workaround_hit(r["subject"] + "\n" + r["body"])]
        for r in hits:
            r["prs"] = apps.pr_numbers(r["subject"])
        with open(OUT / f"app-commits-{name}.jsonl", "w") as fh:
            for r in hits:
                fh.write(json.dumps({"app": name, **r}) + "\n")
        print(f"{name}: {len(recs)} commits, {len(hits)} name a compiler "
              "or a workaround", flush=True)
    return 0


def cmd_app_issues(a) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for repo in a.names:
        slug = repo.replace("/", "__")
        dst = Path(a.src) / "github" / slug
        dst.mkdir(parents=True, exist_ok=True)
        f = dst / "issues.json"
        if not f.is_file():
            r = subprocess.run(["gh", "api", "--paginate", "--slurp",
                                f"repos/{repo}/issues?state=all&per_page=100"],
                               capture_output=True, text=True, timeout=1800)
            if r.returncode:
                print(f"{repo}: {r.stderr.strip()[:200]}", flush=True)
                continue
            f.write_text(r.stdout)
        pages = json.loads(f.read_text())
        items = [i for pg in pages for i in pg]
        recs = [apps.issue_record(i, repo) for i in items]
        with open(OUT / f"app-issues-{slug}.jsonl", "w") as fh:
            for r in recs:
                fh.write(json.dumps(r) + "\n")
        print(f"{repo}: {len(recs)} issues and PRs, "
              f"{sum(r['hit'] for r in recs)} name a compiler or a "
              "workaround", flush=True)
    return 0


# --- cases --------------------------------------------------------------------------
BENCH = ROOT / "data" / "bench" / "harvest-known"


def cmd_legality(a) -> int:
    bench = Path(a.bench)
    paths = sorted([*bench.glob("hk-*.f90"), *bench.glob("hk-*.c")])
    if a.only:
        paths = [p for p in paths if p.stem in set(a.only)]
    rows = cases.legality_rows(paths)
    out = OUT / "legality.jsonl"
    old = {}
    if out.is_file():
        old = {r["id"]: r for r in map(json.loads,
                                       out.read_text().splitlines())}
    old.update({r["id"]: r for r in rows})
    out.write_text("".join(json.dumps(old[k]) + "\n" for k in sorted(old)))
    for r in rows:
        print(r["id"], "ok" if r["ok"] else f"refused ({r['kind']})",
              "; ".join(r["reasons"])[:200], flush=True)
    return 0


def keep_moved(old: dict, rows: list[dict]) -> list[dict]:
    """``rows`` plus the earlier export's holdout programs that are no longer
    in the bench (``holdout`` moved them to the sealed set): their metadata
    only, so the tables count them; nothing reads the sealed directory, and
    their exported copies are deleted after the last run."""
    ids = {r["id"] for r in rows}
    return rows + [r for i, r in sorted(old.items())
                   if i not in ids and r.get("holdout")]


def cmd_export(a) -> int:
    """The cases as the runner reads them (results/harvest-known/:
    programs.jsonl, src/<file>, prerun.jsonl from legality.jsonl)."""
    import shutil
    bench = Path(a.bench)
    rows = cases.export_rows(bench)
    (OUT / "src").mkdir(parents=True, exist_ok=True)
    for r in rows:
        shutil.copyfile(bench / r["file"], OUT / "src" / r["file"])
    rows = keep_moved(programs(), rows)
    (OUT / "programs.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    leg = OUT / "legality.jsonl"
    pre = [json.loads(x) for x in leg.read_text().splitlines()] \
        if leg.is_file() else []
    ids = {r["id"] for r in rows}
    (OUT / "prerun.jsonl").write_text("".join(
        json.dumps({k: r[k] for k in ("id", "ok", "reasons", "kind")},
                   sort_keys=True) + "\n" for r in pre if r["id"] in ids))
    print(f"{len(rows)} programs ({sum(r['holdout'] for r in rows)} holdout),"
          f" {sum(r['ok'] for r in pre if r['id'] in ids)} pass the pre-run "
          "check", flush=True)
    return 0


# --- overlap with the other sets (the check, URL keys) --------------------------

def overlap_hits(bench: Path, others: list[tuple]) -> list[dict]:
    """Cases of ``bench`` another set already holds: the same source URL
    (cases.url_key), or a program overlap (tools/campaigns/fresh_bench.py
    overlaps: copy, similar_program, same_defect). ``others``: (name,
    directory, sealed); for a sealed set the other case's id is withheld."""
    import yaml
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    import fresh_bench as FB
    mine = yaml.safe_load((bench / "cases.yaml").read_text())["cases"]
    hits = []
    for name, d, sealed in others:
        meta = d / "cases.yaml"
        if not meta.is_file():
            continue
        theirs = yaml.safe_load(meta.read_text()).get("cases") or []
        keys = cases.known_keys([d])
        for c in mine:
            for u in [c.get("url"), *(c.get("also") or [])]:
                k = cases.url_key(u) if u else None
                if k and k in keys:
                    hits.append({"id": c["id"], "other": name, "kind": "url",
                                 "other_id": None if sealed else keys[k],
                                 "score": 1.0})
        for a_id, b_id, kind, score in FB.overlaps(mine, bench, [(theirs, d)]):
            hits.append({"id": a_id, "other": name, "kind": kind,
                         "other_id": None if sealed else b_id,
                         "score": score})
    return hits


def program_copies(bench: Path, src: Path, name: str) -> list[dict]:
    """The converted programs (results/harvest/src) as near-copies of
    a case: the token-shingle Jaccard (fresh_bench.program_tokens) at
    COPY_JACCARD or above."""
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    import fresh_bench as FB
    if not src.is_dir():
        return []
    theirs = [(p, FB.program_tokens(p)) for p in sorted(src.iterdir())
              if p.suffix in (".f90", ".c")]
    hits = []
    for p in sorted([*bench.glob("hk-*.f90"), *bench.glob("hk-*.c")]):
        tp = FB.program_tokens(p)
        for q, tq in theirs:
            if q.suffix != p.suffix:
                continue
            jac, _ = FB.program_similarity(tp, tq)
            if jac >= FB.COPY_JACCARD:
                hits.append({"id": p.stem, "other": name, "kind": "copy",
                             "other_id": q.stem, "score": round(jac, 3)})
    return hits


def cmd_overlap(a) -> int:
    bench = Path(a.bench)
    hits = overlap_hits(bench, [("wild", ROOT / "data" / "bench" / "wild", False),
                                ("fresh", ROOT / "data" / "bench" / "fresh", False),
                                ("fresh2", ROOT / "data" / "bench" / "fresh2", True)])
    hits += program_copies(bench, ROOT / "results" / "harvest" / "src",
                           "harvest-49a")
    (OUT / "overlap.jsonl").write_text(
        "".join(json.dumps(h, sort_keys=True) + "\n" for h in hits))
    for h in hits:
        print(h["id"], h["other"], h["kind"], h["other_id"] or "", h["score"])
    print(f"{len(hits)} overlaps, {len({h['id'] for h in hits})} cases")
    return 0


# --- verdicts and summaries ---------------------------------------------------------
PASSING = ("correct_on_device", "unobservable", "harness_error")
DROPPED = {"hk-009"}    # source held by data/bench/fresh2 (dropped after the runs began)


def last_rows(d: Path) -> list[dict]:
    last = {}
    for f in sorted(d.glob("rows*.jsonl")):
        for ln in f.read_text().splitlines():
            if ln.strip():
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                last[(r["program_id"], r["toolchain"], r["xnack"])] = r
    return list(last.values())


def applicable(rows: list[dict], progs: dict) -> list[dict]:
    """The rows whose memory mode the program's expected result holds in
    (programs.jsonl ``modes``; row key 0 copy, 1 and 2 unified)."""
    mode = {0: "copy", 1: "unified", 2: "unified"}
    return [r for r in rows if r["program_id"] not in progs or
            mode.get(r["xnack"]) in progs[r["program_id"]]["modes"]]


def programs() -> dict:
    f = OUT / "programs.jsonl"
    return {r["id"]: r for r in map(json.loads, f.read_text().splitlines())} \
        if f.is_file() else {}


def outcome_table(rows: list[dict], drop=DROPPED) -> dict:
    t: dict = {}
    for r in rows:
        if r["program_id"] in drop:
            continue
        t.setdefault((r["toolchain"], r["xnack"]), Counter())[r["outcome"]] += 1
    return t


def failing(rows: list[dict], drop=DROPPED) -> list[dict]:
    return sorted((r for r in rows if r["program_id"] not in drop and
                   r["outcome"] not in PASSING),
                  key=lambda r: (r["program_id"], r["toolchain"], r["xnack"]))


def cmd_verdicts(a) -> int:
    """For each run directory (results/harvest-known/<name>[.<machine>]):
    the failing rows as gate items (the gate_items), the plan, every
    rerun row's verdict (offload.engine.gate.judge) and the inherited or
    unchecked rest (offload.engine.gate.inherit) -> <dir>/verdicts.jsonl."""
    H = harvest49a()
    GT = H._register()
    for name in a.dirs:
        d = OUT / name
        items = H.gate_items(name)
        planned = H.gate_plan(items)["rows"]
        reruns: dict[str, list] = {}
        for r in H._jlp(d / "gate_reruns.jsonl"):
            reruns.setdefault(r["cell"], []).append(r)
        judged, own = {}, {}
        for it in planned:
            rr = reruns.get(it["cell"], [])
            try:
                j = GT.judge(it, rr)
            except ValueError as e:
                j = {"verdict": None, "why": str(e)}
            own[it["cell"]] = j
            if j.get("verdict"):
                judged[it["cell"]] = j["verdict"]
        inh = GT.inherit(planned, judged)
        out = []
        for it in planned:
            c = it["cell"]
            out.append({"cell": c, "program": it["ident"],
                        "toolchain": it["toolchain"], "xnack": it["xnack"],
                        "outcome": it["outcome"], "reason": it.get("reason"),
                        "value": it.get("value"), "sample": it.get("sample"),
                        "verdict": inh.get(c, {}).get("verdict"),
                        "inherited": inh.get(c, {}).get("inherited"),
                        "judge": own.get(c), "holdout": it.get("holdout")})
        (d / "verdicts.jsonl").write_text(
            "".join(json.dumps(x, sort_keys=True) + "\n" for x in out))
        print(name, Counter(x["verdict"] for x in out))
    return 0


def cmd_summary(a) -> int:
    progs = programs()
    for name in a.dirs:
        d = OUT / name
        rows = applicable(last_rows(d), progs)
        v = {}
        vf = d / "verdicts.jsonl"
        if vf.is_file():
            v = {x["cell"]: x for x in map(json.loads,
                                            vf.read_text().splitlines())}
        print(f"== {name}: {len(rows)} rows")
        for (tc, x), c in sorted(outcome_table(rows).items()):
            print(f"  {tc:10s} x{x} " + ", ".join(
                f"{k} {n}" for k, n in sorted(c.items())))
        for r in failing(rows):
            cell = f"harvest|{r['program_id']}|{r['toolchain']}|{r['xnack']}"
            vv = v.get(cell, {}).get("verdict") or "-"
            print(f"  FAIL {r['program_id']} {r['toolchain']} x{r['xnack']} "
                  f"{r['outcome']} [{vv}] {(r.get('reason') or '')[:110]}")
    return 0


def cmd_probe(a) -> int:
    """Each file (a variant or control of a candidate; the case file format)
    through the harness (offload.engine.harness.run_program: limits, whole-group
    kill, RESULT line) on the given toolchains and row keys; one JSON line
    per cell to --out (default results/harvest-known/probes.jsonl)."""
    import dataclasses
    import re as _re
    from offload.engine import harness, run_matrix
    from offload.engine.gen import Program as HP
    from offload.engine.toolchains import TOOLCHAINS
    out = Path(a.out) if a.out else OUT / "probes.jsonl"
    for f in map(Path, a.files):
        text = f.read_text()
        lang = cases.lang_of(f)
        model = "acc" if _re.search(r"^\s*(!\$acc|#\s*pragma\s+acc)", text,
                                    _re.M | _re.I) else "omp"
        version = 34 if model == "acc" else a.version
        hp = HP(id=f.stem, lang=lang, source=text,
                atoms=frozenset({f"harvest.{f.stem}"}),
                primary_atom=f"harvest.{f.stem}", legal=True, violates=None,
                observable=True, model=model)
        for t in a.toolchains.split(","):
            tc = run_matrix.for_version(TOOLCHAINS[t], version, lang)
            for x in (int(m) for m in a.modes.split(",")):
                if x not in TOOLCHAINS[t].xnack_modes:
                    continue
                r = dataclasses.asdict(harness.run_program(
                    hp, tc, x, a.opt, timeout_s=a.timeout, repeats=a.repeats,
                    version=version, compile_timeout_s=600))
                r.update(file=str(f), opt=a.opt)
                with open(out, "a") as fh:
                    fh.write(json.dumps(r) + "\n")
                print(f"{f.name} {t} x{x} {a.opt}: {r['outcome']} | "
                      f"{(r.get('reason') or '')[:100]} | "
                      f"{' '.join((r.get('stdout') or '').split())[-160:]}",
                      flush=True)
    return 0


MODE = {0: "copy (HSA_XNACK=0 / separate)", 1: "HSA_XNACK=1", 2: "managed"}
OUTCOMES = ("correct_on_device", "fell_back_to_host", "rejected", "ice",
            "wrong_answer", "crash", "harness_error", "unobservable")


def render_tables(dirs: list[str]) -> str:
    """Markdown: outcomes per toolchain and row key over the run
    directories (every program, the holdout included), and every failing
    cell of a non-holdout program with its gate verdict (the report:
    the holdout is counted, never named)."""
    progs = programs()   # the bench and the moved holdout (keep_moved)
    allrows, verd = [], {}
    for name in dirs:
        d = OUT / name
        allrows += last_rows(d)
        vf = d / "verdicts.jsonl"
        if vf.is_file():
            verd.update({x["cell"]: x for x in map(
                json.loads, vf.read_text().splitlines())})
    allrows = applicable([r for r in allrows if r["program_id"] in progs],
                         progs)
    t = outcome_table(allrows)
    cols = [o for o in OUTCOMES if any(c.get(o) for c in t.values())]
    out = ["| toolchain | row key | cells | " + " | ".join(cols) + " |",
           "|---|---|---|" + "---|" * len(cols)]
    for (tc, x), c in sorted(t.items()):
        out.append(f"| {tc} | {MODE.get(x, x)} | {sum(c.values())} | " +
                   " | ".join(str(c.get(o, 0)) for o in cols) + " |")
    out += ["", "| case | source | toolchain | row key | outcome | gate | reason |",
            "|---|---|---|---|---|---|---|"]
    for r in failing(allrows):
        if progs[r["program_id"]].get("holdout"):
            continue
        cell = f"harvest|{r['program_id']}|{r['toolchain']}|{r['xnack']}"
        v = verd.get(cell, {})
        why = " ".join((r.get("reason") or "").split())[:90].replace("|", "/")
        out.append(f"| {r['program_id']} | {progs[r['program_id']]['source']}"
                   f" | {r['toolchain']} | {r['xnack']} | {r['outcome']} | "
                   f"{v.get('verdict') or '-'}"
                   f"{' (inherited)' if v.get('inherited') else ''} | {why} |")
    return "\n".join(out) + "\n"


def cmd_tables(a) -> int:
    print(render_tables(a.dirs), end="")
    return 0


def confirm_rows(rows: list[dict]) -> list:
    """The run rows as the confirmer's stored evidence (kind "file"):
    offload.engine.confirm.ingest.row_of_result, whose outcome is the class
    (an ICE, a crash, a run error), not the harness outcome."""
    import dataclasses
    from offload.engine.confirm import ingest as IG
    out = []
    for r in rows:
        try:
            row = IG.row_of_result(r, "results/harvest-known/rows.jsonl")
        except KeyError:
            continue
        out.append(dataclasses.replace(row, kind="file"))
    return out


def gate_verdict_records(verdicts: list[dict]) -> list[dict]:
    """The gate verdicts (verdicts.jsonl rows) as offload.engine.gate reads them
    from a file (kind "file")."""
    return [{"cell": v["cell"], "kind": "file", "ident": v["program"],
             "toolchain": v["toolchain"], "xnack": v["xnack"],
             "verdict": v["verdict"]} for v in verdicts if v.get("verdict")]


def confirm_out(out: str | None) -> Path:
    """Where confirm writes its verdict file, evidence and results (by
    default results/harvest-known; coverage parity writes its own)."""
    return Path(out) if out else OUT


def judged(toolchain: str, toolchains) -> bool:
    """Whether confirm judges a row of `toolchain` (all when no filter; the
    others' rows stay evidence)."""
    return not toolchains or toolchain in toolchains


def cmd_confirm(a) -> int:
    """The confirmer (offload.engine.confirm.engine, stored evidence only, no
    runs) on every failing cell of the run directories: the
    rows as stored evidence with their outcome classes, the gate verdicts
    as a verdict file, the legality from the pre-run check ->
    results/harvest-known/confirm.jsonl."""
    from collections import Counter
    from offload.engine import gate as GT
    from offload.engine.confirm import engine as EN
    from offload.engine.confirm import ingest as IG
    from offload.engine.confirm import programs as P
    from offload.engine.confirm.collectors import Context
    from offload.engine.confirm.legality import Legality
    from offload.engine.confirm.store import Store
    H = harvest49a()
    H._register()
    progs = programs()
    pre = {}
    for ln in (OUT / "prerun.jsonl").read_text().splitlines():
        r = json.loads(ln)
        pre[r["id"]] = r
    runs, ver = [], []
    for name in a.dirs:
        runs += applicable(last_rows(OUT / name), progs)
        vf = OUT / name / "verdicts.jsonl"
        if vf.is_file():
            ver += [json.loads(x) for x in vf.read_text().splitlines()]
    dest = confirm_out(getattr(a, "out", None))
    dest.mkdir(parents=True, exist_ok=True)
    tcs = set(a.toolchains.split(",")) if getattr(a, "toolchains", None) \
        else None
    gv = dest / "gate_verdicts.file.jsonl"
    gv.write_text("".join(json.dumps(x) + "\n" for x in
                          gate_verdict_records(ver)))
    GT.VERDICTS_FILE = gv
    rows_ = confirm_rows([r for r in runs if r["program_id"] in progs])
    ctx = Context(IG.Index(rows_), Store(dest / "confirm_evidence.jsonl"),
                  allow_run=False)
    nv_ok = {r["program_id"] for r in runs if r["toolchain"] in
             ("nvhpc", "nvhpc269") and r["outcome"] != "rejected"}
    vby = {(v["program"], v["toolchain"], v["xnack"]): v["verdict"] for v in ver}
    xof = {(r["program_id"], r["toolchain"]): {} for r in runs}
    for r in runs:
        xof[(r["program_id"], r["toolchain"])][
            IG._mode(r["toolchain"], r["xnack"])[1]] = r["xnack"]
    refs, out = {}, []
    for x in rows_:
        if x.outcome in PASSING or not judged(x.toolchain, tcs):
            continue
        p = progs[x.ident]
        if x.ident not in refs:
            refs[x.ident] = P.file_ref([str(OUT / "src" / p["file"])],
                                       "check=pass", label=x.ident,
                                       version=p["version"])
        if not pre.get(x.ident, {}).get("ok"):
            leg = Legality("unknown", "the pre-run check refused it")
        elif not x.toolchain.startswith("afar"):
            leg = Legality("legal", "two witnesses (offload.engine.prerun.check): "
                           "the rules and the AFAR front end, not under test")
        elif x.ident in nv_ok:
            leg = Legality("legal", "two witnesses: the rules and NVHPC, "
                           "which compiled it; the AFAR front end is under test")
        else:
            leg = Legality("unknown", "an AFAR case that NVHPC did not compile")
        try:
            res = EN.confirm(IG.case_of_row(x, refs[x.ident]), ctx,
                             legality=leg, minimize=False, draft=False)
        except Exception as e:   # one cell's error is a row, not a stop
            res = {"verdict": "error", "rule": "", "reason": f"{e}"[:300]}
        xn = xof.get((x.ident, x.toolchain), {}).get(x.mode)
        out.append({"cell": f"harvest|{x.ident}|{x.toolchain}|{xn}",
                    "program": x.ident, "toolchain": x.toolchain,
                    "mode": x.mode, "outcome": x.outcome,
                    "verdict": res.get("verdict"), "rule": res.get("rule"),
                    "reason": (res.get("reason") or res.get("rationale")
                               or "")[:400],
                    "gate": vby.get((x.ident, x.toolchain, xn)),
                    "findings": [f.get("file") for f in
                                 res.get("findings") or []],
                    "related": [f.get("file") for f in
                                res.get("related") or []],
                    "legality": (res.get("legality") or {}).get("status"),
                    "holdout": bool(p.get("holdout"))})
    (dest / "confirm.jsonl").write_text(
        "".join(json.dumps(o, sort_keys=True) + "\n" for o in out))
    print(len(out), "cells;", Counter(o["verdict"] for o in out))
    return 0


HOLDOUT = ROOT / "data" / "bench" / "harvest-known-holdout"
MODE_NAME = {0: "copy", 1: "unified", 2: "managed"}


def holdout_names(progs: dict) -> dict:
    """hk id -> harvest-known-holdout-NNN (the holdout ids in order)."""
    hids = sorted(i for i, p in progs.items() if p.get("holdout"))
    return {pid: f"harvest-known-holdout-{k:03d}"
            for k, pid in enumerate(hids, start=1)}


def holdout_outcomes(progs: dict, runs: list[dict], verdicts: dict,
                     pre: dict | None = None) -> list[list]:
    """outcomes.csv rows of the holdout: case,
    toolchain, mode (copy, unified, managed), outcome (the harness outcome
    class; ``refused`` for a program the pre-run check refused,
    ``not_applicable`` for a mode its expected result does not hold in,
    ``not_run``), gate (the gate's verdict of the row, else empty).
    ``verdicts``: cell -> verdict."""
    from offload.engine import gate as GT
    from offload.engine.toolchains import TOOLCHAINS
    names = holdout_names(progs)
    by = {(r["program_id"], r["toolchain"], r["xnack"]): r for r in runs}
    want = {0: "copy", 1: "unified", 2: "unified"}
    out = []
    for pid, case in sorted(names.items(), key=lambda kv: kv[1]):
        p = progs[pid]
        for t in p["toolchains"]:
            for x in TOOLCHAINS[t].xnack_modes:
                mode = MODE_NAME[x]
                if want[x] not in p["modes"]:
                    out.append([case, t, mode, "not_applicable", ""])
                    continue
                if pre is not None and not pre.get(pid, {}).get("ok"):
                    out.append([case, t, mode, "refused", ""])
                    continue
                r = by.get((pid, t, x))
                if r is None:
                    out.append([case, t, mode, "not_run", ""])
                    continue
                out.append([case, t, mode, GT.outcome_class(r),
                            verdicts.get(f"harvest|{pid}|{t}|{x}") or ""])
    return out


def write_seal(hold: Path, outcomes: list[list], commit: str) -> str:
    """outcomes.csv (header case,toolchain,mode,outcome,gate) and the SEAL of
    ``hold`` (tools/campaigns/fresh_bench.py digest of the case files, cases.yaml and
    outcomes.csv hashes). Reads the case files and cases.yaml as bytes for
    their hashes only."""
    import csv
    import hashlib
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    import fresh_bench as FB
    with open(hold / "outcomes.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["case", "toolchain", "mode", "outcome", "gate"])
        w.writerows(outcomes)
    paths = sorted([*hold.glob("harvest-known-holdout-*.f90"),
                    *hold.glob("harvest-known-holdout-*.c")])
    seal = (f"# seal of bench/{hold.name} (the known-issues "
            f"harvest's 30% holdout)\ncommit: {commit}\ncases: {len(paths)}\n"
            "method: sha256 over the case files (harvest-known-holdout-*.f90, "
            # the sealed text names the tool by its original path (tools/): the committed SEAL files say so
            "harvest-known-holdout-*.c) sorted by name, each as name, NUL, "
            "bytes, NUL (tools/fresh_bench.py digest)\n"
            f"sha256: {FB.digest(paths)}\n"
            "cases_yaml_sha256: "
            f"{hashlib.sha256((hold / 'cases.yaml').read_bytes()).hexdigest()}\n"
            "outcomes_sha256: "
            f"{hashlib.sha256((hold / 'outcomes.csv').read_bytes()).hexdigest()}\n")
    (hold / "SEAL").write_text(seal)
    return seal


def split_holdout(bench: Path, hold: Path, rows: list[dict],
                  runs: list[dict], commit: str, progs: dict,
                  verdicts: dict) -> int:
    """Move the holdout cases (``rows``: export_rows)
    from ``bench`` to ``hold`` as harvest-known-holdout-NNN (in program
    order), with cases.yaml (the program's metadata and its hk id), then
    outcomes.csv and the SEAL (write_seal; holdout_outcomes of ``progs``,
    ``runs`` and the gate ``verdicts``). ``bench``'s cases.yaml keeps the
    rest and a count. Refuses when ``hold`` is sealed."""
    import hashlib
    import yaml
    if (hold / "SEAL").exists():
        raise SystemExit(f"{hold} is sealed: not rewritten")
    hold.mkdir(parents=True, exist_ok=True)
    meta = yaml.safe_load((bench / "cases.yaml").read_text())
    byid = {c["id"]: c for c in meta["cases"]}
    names = holdout_names({r["id"]: r for r in rows if r["id"] in byid})
    out = []
    for pid, cid in sorted(names.items(), key=lambda kv: kv[1]):
        c = dict(byid[pid])
        ext = Path(c["file"]).suffix
        src = bench / c["file"]
        lead = "//" if ext == ".c" else "!"
        text = src.read_text().replace(f"{lead} fresh case: {pid}",
                                       f"{lead} fresh case: {cid}", 1)
        (hold / (cid + ext)).write_text(text)
        src.unlink()
        c.update(id=cid, file=cid + ext, program=pid,
                 sha256=hashlib.sha256(text.encode()).hexdigest())
        out.append(c)
    (hold / "cases.yaml").write_text(yaml.safe_dump({"cases": out},
                                                    sort_keys=False, width=100))
    meta["cases"] = [c for c in meta["cases"] if c["id"] not in names]
    meta["holdout"] = {"cases": len(out), "directory": f"data/bench/{hold.name}",
                       "rule": "sha256 of the case file text in the lowest 30% "
                       "of the hash space"}
    (bench / "cases.yaml").write_text(yaml.safe_dump(meta, sort_keys=False,
                                                     width=100))
    write_seal(hold, holdout_outcomes(progs, runs, verdicts), commit)
    return len(out)


def _runs_and_verdicts(dirs: list[str]) -> tuple[list[dict], dict]:
    runs, ver = [], {}
    for name in dirs:
        runs += last_rows(OUT / name)
        vf = OUT / name / "verdicts.jsonl"
        if vf.is_file():
            for x in map(json.loads, vf.read_text().splitlines()):
                ver[x["cell"]] = x["verdict"]
    return runs, ver


def cmd_holdout(a) -> int:
    rows = [json.loads(x) for x in
            (OUT / "programs.jsonl").read_text().splitlines()]
    runs, ver = _runs_and_verdicts(a.dirs)
    n = split_holdout(BENCH, HOLDOUT, rows, runs, a.commit,
                      {r["id"]: r for r in rows}, ver)
    print(f"{n} holdout cases -> {HOLDOUT}")
    return 0


def cmd_reseal(a) -> int:
    """Rewrite outcomes.csv and the SEAL of the sealed holdout from the
    final runs and gate verdicts (the semantics). The
    case files and cases.yaml are hashed, not read; prints counts only."""
    from collections import Counter
    progs = programs()
    pre = {}
    for ln in (OUT / "prerun.jsonl").read_text().splitlines():
        r = json.loads(ln)
        pre[r["id"]] = r
    runs, ver = _runs_and_verdicts(a.dirs)
    rows = holdout_outcomes(progs, runs, ver, pre)
    write_seal(HOLDOUT, rows, a.commit)
    print(len(rows), "rows;", sorted(Counter(r[3] for r in rows).items()),
          sorted(Counter(r[4] for r in rows if r[4]).items()))
    return 0


PIN_49A = "dc3f411"


def harvest49a():
    """The tools/campaigns/harvest.py as a module, its OUT and ROOT set to
    this task's results directory and tree."""
    import importlib.util
    # always the pinned commit, also once tools/campaigns/harvest.py is merged
    path = OUT / "_harvest_49a.py"
    if not path.is_file():
        OUT.mkdir(parents=True, exist_ok=True)
        path.write_text(_git(ROOT, "show", f"{PIN_49A}:tools/campaigns/harvest.py"))
    spec = importlib.util.spec_from_file_location("harvest49a", path)
    H = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(H)
    H.ROOT, H.OUT = ROOT, OUT
    return H


def run_groups(rows: list[dict], machine_tcs: list[str]) -> list[tuple]:
    """(toolchains, ids) calls that cover each program on the toolchains of
    this machine that compile it."""
    from offload.engine.toolchains import TOOLCHAINS
    by: dict[tuple, list[str]] = {}
    for tc in machine_tcs:
        # a program's toolchain list names the families it was exported
        # for; GCC (added later, coverage parity) compiles OpenMP and
        # OpenACC in both languages, so it takes every program
        every = TOOLCHAINS[tc].kind == "gcc"
        ids = tuple(r["id"] for r in rows
                    if every or tc in r["toolchains"])
        if ids:
            by.setdefault(ids, []).append(tc)
    return [(tcs, list(ids)) for ids, tcs in by.items()]


def shard_rows(rows: list[dict], shard: str) -> list[dict]:
    import zlib
    k, m = (int(v) for v in shard.split("/"))
    return [r for r in rows if zlib.crc32(r["id"].encode()) % m == k]


def cmd_via49a(a) -> int:
    H = harvest49a()
    args = list(a.args)
    if args and args[0] == "--":
        args = args[1:]
    if not args or args[0] != "run":
        return H.main(args)
    import argparse as _ap
    p = _ap.ArgumentParser()
    p.add_argument("--machine", default="tuolumne")
    p.add_argument("--toolchains")
    p.add_argument("--ids")
    p.add_argument("--shard")
    known, rest = p.parse_known_args(args[1:])
    rows = [json.loads(x) for x in
            (OUT / "programs.jsonl").read_text().splitlines()]
    if known.ids:
        want = set(known.ids.split(","))
        rows = [r for r in rows if r["id"] in want]
    if known.shard:
        # by program id, fixed whatever the other shard has done: --shard
        # slices the cells not done yet, which two shards that read
        # the results at different times (one group after another) see
        # differently, so cells fall between them
        rows = shard_rows(rows, known.shard)
    tcs = known.toolchains.split(",") if known.toolchains else \
        H.TARGETS[known.machine][0]
    rc = 0
    for group, ids in run_groups(rows, tcs):
        print(f"run {','.join(group)}: {len(ids)} programs", flush=True)
        rc |= H.main(["run", "--machine", known.machine, "--toolchains",
                      ",".join(group), "--ids", ",".join(ids), *rest])
    return rc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("forum-fetch", "forum-scan", "centre-git",
                 "centre-archive-fetch", "centre-scan"):
        p = sub.add_parser(name)
        p.add_argument("--src", default=str(SRC))
    for name in ("app-commits", "app-issues"):
        p = sub.add_parser(name)
        p.add_argument("names", nargs="+")
        p.add_argument("--src", default=str(SRC))
    p = sub.add_parser("legality")
    p.add_argument("--bench", default=str(BENCH))
    p.add_argument("--only", nargs="*")
    p = sub.add_parser("export")
    p.add_argument("--bench", default=str(BENCH))
    for name in ("verdicts", "summary", "tables", "confirm"):
        p = sub.add_parser(name)
        p.add_argument("dirs", nargs="+")
        if name == "confirm":
            p.add_argument("--out", help="directory of the outputs "
                           "(default results/harvest-known)")
            p.add_argument("--toolchains", help="judge only these "
                           "toolchains' rows (comma separated)")
    p = sub.add_parser("holdout")
    p.add_argument("dirs", nargs="+")
    p.add_argument("--commit", required=True)
    p = sub.add_parser("reseal")
    p.add_argument("dirs", nargs="+")
    p.add_argument("--commit", required=True)
    p = sub.add_parser("probe")
    p.add_argument("files", nargs="+")
    p.add_argument("--toolchains", required=True)
    p.add_argument("--modes", default="0,1")
    p.add_argument("--opt", default="-O2")
    p.add_argument("--version", type=int, default=52)
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--out")
    p = sub.add_parser("overlap")
    p.add_argument("--bench", default=str(BENCH))
    p = sub.add_parser("via49a")
    p.add_argument("args", nargs=argparse.REMAINDER)
    a = ap.parse_args(argv)
    return {"forum-fetch": cmd_forum_fetch,
            "forum-scan": cmd_forum_scan,
            "centre-git": cmd_centre_git,
            "centre-archive-fetch": cmd_centre_archive_fetch,
            "centre-scan": cmd_centre_scan,
            "app-commits": cmd_app_commits,
            "app-issues": cmd_app_issues,
            "legality": cmd_legality,
            "export": cmd_export,
            "via49a": cmd_via49a,
            "overlap": cmd_overlap,
            "verdicts": cmd_verdicts,
            "summary": cmd_summary,
            "probe": cmd_probe,
            "tables": cmd_tables,
            "confirm": cmd_confirm,
            "holdout": cmd_holdout,
            "reseal": cmd_reseal}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
