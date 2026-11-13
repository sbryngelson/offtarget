#!/usr/bin/env python3
"""Harvest 2: Fortran and C OpenMP-offload and OpenACC programs from public
test suites, example collections and applications, in the Harvest form
.

Sources are untrusted and only read: clones in
harvest-src/t49c (HARVEST2_SRC) and corpus/gcc,
corpus/omp_examples, corpus/apps. Run with ``python3 -I`` from the repo root.
gomp: GCC's libgomp testsuite -> results/harvest2/gomp.jsonl and programs.
examples: the OpenMP Examples (outputs in catalog/harvest2_examples.yaml).
hand: hand-written drivers in HARVEST2_SRC/hand (files plus hand.yaml).
merge: all programs, deduplicated -> results/harvest2/programs.jsonl, src/.
rules: the pre-run rules witness (offload.engine.prerun), CPU only ->
results/harvest2/rules.jsonl.
split: 30% holdout by sha256 -> data/bench/harvest2-holdout (sealed), the rest
data/bench/harvest2. tables: the funnel and totals."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

SRC = Path(os.environ.get("HARVEST2_SRC",
                          "harvest-src/t49c"))
GCC = ROOT / "corpus" / "gcc"
EXAMPLES = ROOT / "corpus" / "omp_examples"
OUT = ROOT / "results" / "harvest2"
DEV = ROOT / "data" / "bench" / "harvest2"
HOLDOUT = ROOT / "data" / "bench" / "harvest2-holdout"


def _jl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines()
            if ln.strip()]


def _write_jl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n"
                            for r in rows))


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True,
                          errors="replace").stdout.strip()


# --- libgomp ---------------------------------------------------------------------------

def cmd_gomp(a) -> int:
    from offload.engine.harvest import convert as HC
    from offload.engine.harvest2 import gomp as G
    commit = _git(GCC, "rev-parse", "HEAD")
    ts = GCC / "libgomp" / "testsuite"
    dirty = _git(GCC, "status", "--porcelain", "--", "libgomp/testsuite")
    if dirty:
        print("corpus/gcc libgomp/testsuite has local changes: refused")
        return 1
    rows, progs = [], []
    for suite in G.SUITES:
        for p in sorted((ts / suite).rglob("*")):
            if not p.is_file():
                continue
            rel = str(p.relative_to(ts))
            lang = G.lang_of(rel)
            if lang in ("header", "other"):
                continue
            text = p.read_text(errors="replace")
            r = G.record(rel, text, commit)
            if lang in ("c", "f90"):
                body, incs = G.inline_includes(text, p)
            else:
                body, incs = text, []
            c = G.classify(r, body)
            if None in incs:
                c["reasons"].append("missing_include")
            row = {k: r[k] for k in ("id", "suite", "rel", "lang", "url",
                                     "prs")}
            row.update(model=c["model"], reasons=c["reasons"],
                       modes=c["modes"], flags=c["flags"],
                       includes=[i for i in incs if i])
            if not c["reasons"]:
                try:
                    prog = G.convert(r, body, incs)
                except HC.ConvertError as e:
                    row["reasons"] = [f"convert: {e}"]
                else:
                    prog["source_kind"] = "test-suite"
                    progs.append(prog)
                    row["program"] = prog["id"]
            rows.append(row)
    _write_jl(OUT / "gomp.jsonl", rows)
    _stage(progs, "gomp")
    kept = Counter(r["reasons"][0] if r["reasons"] else "kept" for r in rows)
    print(f"libgomp {commit[:12]}: {len(rows)} tests, {len(progs)} programs")
    for k, v in kept.most_common():
        print(f"  {v:5d} {k}")
    return 0


# --- the OpenMP Examples ---------------------------------------------------------------

def cmd_examples(a) -> int:
    import yaml
    from offload.engine.harvest import convert as HC
    from offload.engine.harvest2 import examples as E
    from offload.engine.harvest2 import gomp as G
    commit = _git(EXAMPLES, "rev-parse", "HEAD")
    table = yaml.safe_load((ROOT / "catalog" /
                            "harvest2_examples.yaml").read_text())["examples"]
    rows, progs = [], []
    for p in sorted([*EXAMPLES.glob("*/sources/*.c"),
                     *EXAMPLES.glob("*/sources/*.f90")]):
        rel = str(p.relative_to(EXAMPLES))
        text = p.read_text(errors="replace")
        if not E.selected(text):
            continue
        ent = table.get(rel)
        row = {"id": f"ompex/{rel}", "rel": rel,
               "lang": "c" if rel.endswith(".c") else "f90"}
        if ent is None:
            row["reasons"] = ["not in catalog/harvest2_examples.yaml"]
        elif ent.get("skip"):
            row["reasons"] = ["skip: " + ent["skip"]]
        else:
            body, incs = G.inline_includes(text, p)
            try:
                prog = E.convert(rel, body, ent, commit, incs)
            except HC.ConvertError as e:
                row["reasons"] = [f"convert: {e}"]
            else:
                progs.append(prog)
                row["reasons"] = []
                row["program"] = prog["id"]
        rows.append(row)
    missing = set(table) - {r["rel"] for r in rows}
    if missing:
        print("catalog entries that are no selected example:", sorted(missing))
        return 1
    _write_jl(OUT / "examples.jsonl", rows)
    _stage(progs, "examples")
    print(f"OpenMP Examples {commit[:12]}: {len(rows)} runnable device "
          f"examples, {len(progs)} programs")
    return 0


# --- AOMP's other suites ---------------------------------------------------------------

AOMP = SRC / "git" / "ROCm__aomp"


def cmd_aomp(a) -> int:
    """AOMP's Makefile suites beyond smoke/smoke-fails (the inventory, filters and converter) and test/fortran-map-tests."""
    from offload.engine.harvest import convert as HC
    from offload.engine.harvest import filters as HF
    from offload.engine.harvest import inventory as HI
    from offload.engine.harvest2 import aomp as A
    commit = _git(AOMP, "rev-parse", "HEAD")
    test = AOMP / "test"
    rows, progs = [], []
    for suite in A.SMOKE_SUITES:
        for d in sorted(p for p in (test / suite).iterdir() if p.is_dir()):
            mk = d / "Makefile"
            if not mk.is_file():
                continue
            rel = f"{suite}/{d.name}"
            files = {f.name: f.read_text(errors="replace")
                     for f in d.iterdir() if f.is_file() and
                     HI.lang_of(f.name) != "other"}
            r = HI.aomp_record(rel, mk.read_text(errors="replace"), files)
            r["commit"] = commit
            r["history"] = {}
            texts = {f"{rel}/{n}": t for n, t in files.items()}
            f = HF.classify(r, texts)
            row = {"id": r["id"], "suite": suite, "lang": r["lang"],
                   "model": r["model"], "reasons": f["reasons"],
                   "flags": f["flags"]}
            if f["keep"]:
                text = texts[r["files"][0]]
                lic = A.license_of(text)
                kept = [k for k, v in enumerate(f["variants"]) if v["keep"]]
                for n, k in enumerate(kept):
                    try:
                        c = HC.convert(r, n, r["variants"][k], text, len(kept),
                                       None)
                    except HC.ConvertError as e:
                        row["reasons"] = [f"convert: {e}"]
                        continue
                    src = A.relabel(c.source, c.lang)
                    src = src.replace(f"license: {r['license']}",
                                      f"license: {lic}", 1)
                    url = A.URL.format(commit=commit[:12], path=rel)
                    progs.append({
                        "id": c.id.replace("hv-aomp-", "h2-aomp-", 1),
                        "record": r["id"], "lang": c.lang, "model": c.model,
                        "version": c.version, "source": src,
                        "oracle": c.oracle, "checks": c.checks,
                        "prefixes": c.prefixes, "modes": list(c.modes),
                        "edits": c.edits, "grammar_errors": c.grammar_errors,
                        "url": url, "license": lic, "project": "ROCm/aomp",
                        "suite": suite, "commit": commit, "gpl": False,
                        "flags": f["flags"], "source_kind": "test-suite"})
                    row["program"] = progs[-1]["id"]
            rows.append(row)
    for p in sorted((test / "fortran-map-tests").iterdir()):
        if HI.lang_of(p.name) != "f90":
            continue
        rel = f"fortran-map-tests/{p.name}"
        text = p.read_text(errors="replace")
        r = A.map_test(rel, text, commit)
        row = {"id": r["id"], "suite": r["suite"], "lang": "f90",
               "model": "omp", "reasons": r["reasons"], "flags": []}
        if not r["reasons"]:
            try:
                prog = A.convert_map_test(r, text)
            except HC.ConvertError as e:
                row["reasons"] = [f"convert: {e}"]
            else:
                progs.append(prog)
                row["program"] = prog["id"]
        rows.append(row)
    _write_jl(OUT / "aomp.jsonl", rows)
    _stage(progs, "aomp")
    c = Counter(r["reasons"][0] if r["reasons"] else "kept" for r in rows)
    print(f"AOMP {commit[:12]}: {len(rows)} tests, {len(progs)} programs; "
          + ", ".join(f"{k} {v}" for k, v in c.most_common()))
    return 0


# --- hand-edited programs (training, examples, applications) ------------------------------

def _repo_root(spec: str) -> Path:
    """``git/<owner>__<name>`` (a clone under HARVEST2_SRC) or
    ``corpus/apps/<name>`` (the project's corpus)."""
    return (ROOT / spec) if spec.startswith("corpus/") else (SRC / spec)


def cmd_hand(a) -> int:
    import yaml
    from offload.engine.harvest import convert as HC
    from offload.engine.harvest2 import hand as H
    cat = yaml.safe_load((ROOT / "catalog" / "harvest2_hand.yaml").read_text())
    repos = cat["repos"]
    commits = {r: _git(_repo_root(v["root"]), "rev-parse", "HEAD")
               for r, v in repos.items()}
    rows, progs, bad = [], [], 0
    for e in cat["programs"]:
        rep = repos[e["repo"]]
        e = {**e, "commit": commits[e["repo"]],
             "license": e.get("license", rep["license"]),
             "kind": e.get("kind", rep.get("kind", "training"))}
        e["url"] = (f"https://github.com/{e['repo']}/blob/"
                    f"{e['commit'][:12]}/{e['path']}")
        f = _repo_root(rep["root"]) / e["path"]
        row = {"id": e["id"], "repo": e["repo"], "path": e["path"]}
        try:
            app = {q: (_repo_root(rep["root"]) / q).read_text(errors="replace")
                   for q in (e.get("append") or []) + (e.get("prepend") or [])}
            prog = H.convert(e, f.read_text(errors="replace"), app,
                             _repo_root(rep["root"]))
        except (H.EditError, HC.ConvertError, OSError) as x:
            row["reasons"] = [f"{type(x).__name__}: {x}"]
            bad += 1
        else:
            progs.append(prog)
            row["reasons"] = []
            row["program"] = prog["id"]
        rows.append(row)
    for r, v in repos.items():
        for path, why in (v.get("skipped") or {}).items():
            rows.append({"id": None, "repo": r, "path": path,
                         "reasons": [f"skip: {why}"]})
    _write_jl(OUT / "hand.jsonl", rows)
    _stage(progs, "hand")
    print(f"hand: {len(progs)} programs from {len(repos)} repositories; "
          f"{bad} entries failed")
    for r in rows:
        if r["reasons"] and not r["reasons"][0].startswith("skip"):
            print("  ", r["id"], r["reasons"][0][:150])
    return 1 if bad else 0


def _stage(progs: list[dict], source: str) -> None:
    """A source's programs -> results/harvest2/staged/<source>.jsonl (with
    their text)."""
    _write_jl(OUT / "staged" / f"{source}.jsonl", progs)


# --- merge and dedup -------------------------------------------------------------------

_RUNTIME_MARK = re.compile(r"^(?:/\* =====|! =====) self-check",
                           re.M)


def body_of(text: str) -> str:
    """A converted program without its header and self-check (what the
    overlap check compares)."""
    m = _RUNTIME_MARK.search(text)
    if m:
        text = text[:m.start()]
    return text


def _tokens(text: str, suffix: str, tmp: Path) -> list[str]:
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    import fresh_bench as FB
    lead = "//" if suffix == ".c" else "!"
    # drop a block comment header: program_tokens skips leading line comments
    text = re.sub(r"\A(?:#define _DEFAULT_SOURCE 1\n)?/\*.*?\*/\n", "",
                  body_of(text), count=1, flags=re.S)
    f = tmp / f"t{suffix}"
    f.write_text(text if not text.startswith(lead) else text)
    return FB.program_tokens(f)


def _known_programs() -> list[tuple[str, str, Path]]:
    """(set, id, path) of every earlier program the overlap check reads."""
    out = []
    for name in ("wild", "fresh", "fresh2", "harvest-known"):
        d = ROOT / "data" / "bench" / name
        for p in sorted([*d.glob("*.c"), *d.glob("*.f90")]):
            out.append((name, p.stem, p))
    for name, d in (("harvest-49a", ROOT / "results" / "harvest" / "src"),
                    ("harvest-known-src",
                     ROOT / "results" / "harvest-known" / "src")):
        if d.is_dir():
            for p in sorted([*d.glob("*.c"), *d.glob("*.f90")]):
                out.append((name, p.stem, p))
    return out


def cmd_merge(a) -> int:
    import tempfile
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    import fresh_bench as FB
    progs = []
    for f in sorted((OUT / "staged").glob("*.jsonl")):
        progs += _jl(f)
    progs.sort(key=lambda p: p["id"])
    ids = Counter(p["id"] for p in progs)
    dup_ids = [k for k, v in ids.items() if v > 1]
    if dup_ids:
        print("duplicate ids:", dup_ids[:10])
        return 1
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        ext = {"c": ".c", "f90": ".f90"}
        toks = {p["id"]: _tokens(p["source"], ext[p["lang"]], tmp)
                for p in progs}
        known = []
        for name, kid, path in _known_programs():
            known.append((name, kid, path.suffix,
                          _tokens(path.read_text(errors="replace"),
                                  path.suffix, tmp)))
    sh = {}

    def shingles(t):
        k = id(t)
        if k not in sh:
            sh[k] = {tuple(t[i:i + FB.SHINGLE])
                     for i in range(max(1, len(t) - FB.SHINGLE + 1))}
        return sh[k]

    def jac(x, y):
        a_, b_ = shingles(x), shingles(y)
        return len(a_ & b_) / len(a_ | b_) if a_ and b_ else 0.0
    # a duplicate is a program whose token stream (identifiers canonical,
    # directive lines kept: fresh_bench.program_tokens) equals another's;
    # The copy threshold (COPY_JACCARD) only records a near copy
    # (``similar``): two tests that differ in one construct (parallel and
    # kernels) are two programs here
    kept, dropped = [], []
    for p in progs:
        t = toks[p["id"]]
        e = ext[p["lang"]]
        hit, near = None, []
        for q in kept:
            if ext[q["lang"]] != e:
                continue
            if toks[q["id"]] == t and q["modes"] == p["modes"]:
                hit = ("harvest2", q["id"])
                break
            j = jac(t, toks[q["id"]])
            if j >= FB.COPY_JACCARD:
                near.append({"set": "harvest2", "id": q["id"],
                             "jaccard": round(j, 3)})
        if hit is None:
            for name, kid, suf, kt in known:
                if suf != e:
                    continue
                open_set = name in ("wild", "fresh", "fresh2", "harvest-known")
                if kt == t:
                    hit = (name, kid if open_set else "(withheld)")
                    break
                j = jac(t, kt)
                if j >= FB.COPY_JACCARD:
                    near.append({"set": name, "id": kid if open_set else
                                 "(withheld)", "jaccard": round(j, 3)})
        if hit:
            dropped.append({"id": p["id"], "copy_of": hit[1], "set": hit[0]})
        else:
            p["similar"] = sorted(near, key=lambda x: -x["jaccard"])[:5]
            kept.append(p)
    src = OUT / "src"
    src.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        f.unlink()
    rows = []
    for p in kept:
        f = p["id"] + ext[p["lang"]]
        (src / f).write_text(p["source"])
        row = {k: v for k, v in p.items() if k != "source"}
        row["file"] = f
        from offload.engine.harvest import convert as HC
        row["sha256"] = HC.hashlib.sha256(p["source"].encode()).hexdigest()
        # by code (comments and blanks ignored)
        row["code_key"] = HC.code_key(p["source"], p["lang"])
        row["holdout"] = HC.holdout_by_code(p["source"], p["lang"])
        rows.append(row)
    _write_jl(OUT / "programs.jsonl", rows)
    _write_jl(OUT / "duplicates.jsonl", dropped)
    by = Counter((r["lang"], r["model"]) for r in rows)
    print(f"{len(rows)} programs ({len(dropped)} duplicates dropped): " +
          ", ".join(f"{l}/{m} {n}" for (l, m), n in sorted(by.items())))
    return 0


# --- legality: the rules witness -------------------------------------------------------

def _rules_one(p: dict) -> dict:
    import time
    from offload.engine import prerun as PR
    text = (OUT / "src" / p["file"]).read_text()
    t0 = time.time()
    try:
        ok, why = PR.rules_witness((text, p["lang"], p["model"],
                                    p["version"] if p["model"] == "omp"
                                    else 34))
    except Exception as e:              # a checker crash is no verdict
        ok, why = None, [f"rules: crashed: {type(e).__name__}: {e}"[:300]]
    kind = "pass" if ok else (PR.refusal_kind(why) if ok is False
                              else "unreadable")
    return {"id": p["id"], "ok": ok, "kind": kind, "reasons": why,
            "sha256": p["sha256"], "seconds": round(time.time() - t0, 3)}


def cmd_rules(a) -> int:
    """offload.engine.prerun.rules_witness on every program (CPU only; the
    front-end witness is phase 2's, on a Tuolumne compute node)."""
    from multiprocessing import Pool
    progs = [p for p in _jl(OUT / "programs.jsonl")
             if (OUT / "src" / p["file"]).exists()]   # dev only once split
    if a.only:
        progs = [p for p in progs if p["id"] in set(a.only)]
    workers = int(os.environ.get("WORKERS", "8"))
    with Pool(workers) as pool:
        rows = pool.map(_rules_one, progs, chunksize=4)
    _write_jl(OUT / "rules.jsonl", rows)
    c = Counter(r["kind"] for r in rows)
    print(f"rules witness: {len(rows)} programs: " +
          ", ".join(f"{k} {v}" for k, v in c.most_common()))
    return 0


# --- the split ------------------------------------------------------------------------

def _case_row(p: dict, rule: dict | None) -> dict:
    ver = ("OpenACC 3.4" if p["model"] == "acc" else
           f"OpenMP {p['version'] // 10}.{p['version'] % 10}")
    row = {"file": p["path"], "url": p["url"], "commit": p["commit"],
           "license": p["license"], "copyleft": bool(p.get("copyleft")),
           "project": p["project"], "suite": p.get("suite", ""),
           "source_kind": p.get("source_kind", ""), "lang": p["lang"],
           "model": p["model"], "spec_version": ver, "oracle": p["oracle"],
           "checks": p["checks"], "modes": p["modes"],
           "expected": "check=pass",
           "rules": (rule or {}).get("kind", "pending"),
           "prerun": "pending: the AFAR front-end witness (phase 2, a "
                     "Tuolumne compute node)",
           "sha256": p["sha256"], "original_sha256": p.get("original_sha256", ""),
           "edits": p.get("edits", [])}
    if rule and rule.get("kind") != "pass":
        row["rules_reasons"] = [r[:300] for r in rule.get("reasons", [])[:3]]
    for k in ("prs", "flags", "similar"):
        if p.get(k):
            row[k] = p[k]
    return row


_LICENSE_TEXTS = {
    "GPL": ("COPYING3", SRC / "data" / "licenses" / "COPYING3"),  # git show HEAD:COPYING3 of corpus/gcc
    "CC-BY-SA": ("CC-BY-SA-4.0.md", SRC / "git" /
                 "OpenACCUserGroup__openacc_concept_strategies_book" /
                 "LICENSE.md"),
}


def _license_files(d: Path, rows: list[dict]) -> None:
    import shutil
    for key, (name, src) in _LICENSE_TEXTS.items():
        if any(r["copyleft"] and r["license"].startswith(key) for r in rows):
            (d / "copyleft").mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, d / "copyleft" / name)


def cmd_split(a) -> int:
    import yaml
    from offload.engine.harvest2 import split as SP
    if (HOLDOUT / "SEAL").exists():
        print("data/bench/harvest2-holdout is sealed: not rewritten")
        return 1
    rules = {r["id"]: r for r in _jl(OUT / "rules.jsonl")}
    progs = []
    for p in _jl(OUT / "programs.jsonl"):
        p["source"] = (OUT / "src" / p["file"]).read_text()
        progs.append(p)
    # the legality verdicts are phase 2's (both witnesses, a Tuolumne
    # compute node); a current rules verdict of a dev program is recorded
    rules = {i: r for i, r in rules.items()
             if r["sha256"] == next((p["sha256"] for p in progs
                                     if p["id"] == i), None)}
    plan = SP.plan(progs)
    sims = SP.dev_similar(plan)
    for p in plan:
        if p["set"] == "dev":
            p["similar"] = sims[p["id"]]
    commit = _git(ROOT, "rev-parse", "--short", "HEAD")
    for d in (DEV, HOLDOUT):
        d.mkdir(parents=True, exist_ok=True)
    dev_rows, hold_rows = [], []
    for p in plan:
        d = DEV if p["set"] == "dev" else HOLDOUT
        f = d / p["path"]
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(p["source"])
        row = _case_row(p, rules.get(p["id"]))
        if p["set"] == "dev":
            dev_rows.append({"id": p["id"], **row})
        else:
            hold_rows.append({"id": p["case"], "program": p["id"], **row})
    head = ("Harvest2 {what} (tools/campaigns/harvest2.py split at {commit})")
    (DEV / "cases.yaml").write_text(yaml.safe_dump(
        {"note": head.format(what="dev set", commit=commit),
         "cases": dev_rows}, sort_keys=False, width=100, allow_unicode=True))
    (HOLDOUT / "cases.yaml").write_text(yaml.safe_dump(
        {"note": head.format(what="holdout (sealed)", commit=commit),
         "cases": hold_rows}, sort_keys=False, width=100, allow_unicode=True))
    _license_files(DEV, dev_rows)
    _license_files(HOLDOUT, hold_rows)
    files = sorted(q for q in HOLDOUT.rglob("harvest2-holdout-*")
                   if q.suffix in (".c", ".f90"))
    (HOLDOUT / "SEAL").write_text(SP.seal_text(commit, files,
                                               HOLDOUT / "cases.yaml"))
    _write_jl(OUT / "split.jsonl", [
        {"id": p["id"], "set": p["set"], "path": p["path"],
         "case": p.get("case")} for p in plan])
    print(f"split at {commit}: {len(dev_rows)} dev, {len(hold_rows)} holdout "
          f"(sealed)")
    return cmd_isolate(a)


def cmd_isolate(a) -> int:
    """The holdout programs' run copies out of results/harvest2/src (which
    the wingtip lane's harvest2-rules step copies) into
    results/harvest2/holdout-src (Tuolumne only; phase 2's runs read it)."""
    split = {r["id"]: r for r in _jl(OUT / "split.jsonl")}
    dst = OUT / "holdout-src"
    dst.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in _jl(OUT / "programs.jsonl"):
        if split.get(p["id"], {}).get("set") == "holdout":
            f = OUT / "src" / p["file"]
            if f.exists():
                f.rename(dst / p["file"])
                n += 1
    print(f"{n} holdout programs moved to {dst}")
    return 0


# --- tables ---------------------------------------------------------------------------

def _source_of(pid: str) -> str:
    t = pid.split("-")[1]
    return {"gomp": "GCC libgomp testsuite", "ompex": "OpenMP Examples",
            "aomp": "ROCm/aomp (suites beyond smoke)"}.get(t, "training, examples, applications (hand)")


def table_lines() -> list[str]:
    """The generated tables: why tests were not
    converted, and the dev set only. No count taken before the split (a
    funnel of programs read, kept or converted would give the holdout's
    size; no holdout id, path, count or outcome in a dev document)."""
    import yaml
    split = {r["id"]: r for r in _jl(OUT / "split.jsonl")}
    dev = [p for p in _jl(OUT / "programs.jsonl")
           if split.get(p["id"], {}).get("set") == "dev"]
    rules = {r["id"]: r for r in _jl(OUT / "rules.jsonl")}
    out: list[str] = []
    out += ["### Why tests were not converted (first reason)", "",
            "| source | reason | tests |", "|---|---|---|"]
    for f, label in (("gomp.jsonl", "libgomp"), ("aomp.jsonl", "aomp"),
                     ("examples.jsonl", "Examples")):
        c = Counter(r["reasons"][0].split(":")[0] if r["reasons"] else None
                    for r in _jl(OUT / f))
        for k, v in c.most_common():
            if k:
                out.append(f"| {label} | {k} | {v} |")
    hand_skips = sum(1 for r in _jl(OUT / "hand.jsonl") if r["reasons"])
    out += [f"| hand | recorded skips (catalog/harvest2_hand.yaml) | {hand_skips} |", ""]
    out += ["### Dev programs by language and model", "",
            "| language | model | dev programs | rules: pass | rules: refused or unreadable |",
            "|---|---|---|---|---|"]
    for lang, model in (("f90", "omp"), ("f90", "acc"), ("c", "omp"), ("c", "acc")):
        ps = [p for p in dev if p["lang"] == lang and p["model"] == model]
        ok = sum(1 for p in ps if rules.get(p["id"], {}).get("kind") == "pass")
        L = "Fortran" if lang == "f90" else "C"
        M = "OpenMP" if model == "omp" else "OpenACC"
        out.append(f"| {L} | {M} | {len(ps)} | {ok} | {len(ps) - ok} |")
    out += ["", "### Dev programs by source and model", "",
            "| source | Fortran OpenMP | Fortran OpenACC | C OpenMP | C OpenACC |",
            "|---|---|---|---|---|"]
    bysrc = Counter((_source_of(p["id"]), p["lang"], p["model"]) for p in dev)
    for srcname in sorted({k[0] for k in bysrc}):
        out.append(f"| {srcname} | " + " | ".join(str(bysrc[(srcname, l, m)]) for l, m in
                   (("f90", "omp"), ("f90", "acc"), ("c", "omp"), ("c", "acc"))) + " |")
    out += ["", "### Rules witness on the dev programs", "",
            "| kind | programs |", "|---|---|"]
    for k, v in Counter(rules[p["id"]]["kind"] for p in dev
                        if p["id"] in rules).most_common():
        out.append(f"| {k} | {v} |")
    out.append("")
    cat = yaml.safe_load((ROOT / "catalog" / "harvest2_hand.yaml").read_text())
    out += ["### Hand-converted sources", "",
            "| repository | license | recorded skips |",
            "|---|---|---|"]
    # no per-repository program count: with a single-program repository a
    # dev count of 0 would name a holdout program's source
    for repo, v in cat["repos"].items():
        k = len(v.get("skipped") or {})
        out.append(f"| {repo} | {v['license'].split(' (')[0]} | {k} |")
    out.append("")
    return out


def cmd_tables(a) -> int:
    out = table_lines()
    doc = ROOT / "data" / "reports" / "harvest2.md"
    text = doc.read_text() if doc.exists() else ""
    a_, b_ = "<!-- tables:begin -->", "<!-- tables:end -->"
    block = a_ + "\n" + "\n".join(out) + b_
    if a_ in text and b_ in text:
        text = text[:text.index(a_)] + block + text[text.index(b_) + len(b_):]
    else:
        text = text + "\n" + block + "\n"
    doc.write_text(text)
    print("\n".join(out))
    return 0


# --- phase 2: the runs' tables (dev programs only) ---------------------------------------

def _hv():
    """tools/campaigns/harvest.py serving harvest2 (HARVEST_SET)."""
    os.environ["HARVEST_SET"] = "harvest2"
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    import harvest as HV
    assert HV.SET == "harvest2", "tools/campaigns/harvest.py was imported for another set"
    return HV


def results_tables(name: str = "main") -> list[str]:
    """Outcome classes per toolchain and mode, gate verdicts and confirmer
    verdicts of the dev programs (no holdout row is read into a table)."""
    HV = _hv()
    progs = {p["id"]: p for p in HV.load_programs()}
    dev = {i for i, p in progs.items() if not p["holdout"]}
    rs = [r for r in HV.rows(name) if r["program_id"] in dev]
    pre = HV.prerun_rows()
    out = ["### Pre-run check of the dev programs (rules and the AFAR front end)",
           "", "| verdict | programs |", "|---|---|"]
    c = Counter("pass" if pre[i]["ok"] else pre[i]["kind"] for i in dev
                if i in pre)
    out += [f"| {k} | {v} |" for k, v in c.most_common()] + [""]
    out += ["### Dev rows by toolchain and mode (outcome classes)", ""]
    cls = Counter((r["toolchain"], HV._mode_label(r["toolchain"], r["xnack"]),
                   HV._cls(r)) for r in rs)
    kinds = sorted({k[2] for k in cls})
    cols = sorted({(t, m) for t, m, _ in cls},
                  key=lambda x: (HV.TC_ORDER.index(x[0])
                                 if x[0] in HV.TC_ORDER else 99, x[1]))
    out += ["| toolchain | mode | " + " | ".join(kinds) + " |",
            "|---|---|" + "---|" * len(kinds)]
    for t, m in cols:
        out.append(f"| {t} | {m} | " + " | ".join(
            str(cls[(t, m, k)]) for k in kinds) + " |")
    out.append("")
    ver = HV.verdicts(name)
    gv = Counter(v["verdict"] for c_, v in ver.items()
                 if v["item"]["ident"] in dev)
    out += ["### Gate verdicts of the failing dev rows", "",
            "| verdict | rows |", "|---|---|"]
    out += [f"| {k} | {v} |" for k, v in gv.most_common()] + [""]
    conf = [r for r in _jl(OUT / name / "confirm.jsonl")
            if not r.get("holdout")]
    if conf:
        out += ["### Confirmer verdicts of the failing dev rows", "",
                "| verdict | rows |", "|---|---|"]
        out += [f"| {k} | {v} |" for k, v in
                Counter(r["verdict"] for r in conf).most_common()] + [""]
    return out


def cmd_results(a) -> int:
    out = results_tables(a.name)
    doc = ROOT / "data" / "reports" / "harvest2.md"
    text = doc.read_text()
    a_, b_ = "<!-- results:begin -->", "<!-- results:end -->"
    block = a_ + "\n## Runs (phase 2; dev programs only)\n\n" + \
        "\n".join(out) + b_
    if a_ in text and b_ in text:
        text = text[:text.index(a_)] + block + text[text.index(b_) + len(b_):]
    else:
        text = text + "\n" + block + "\n"
    if a.write:
        doc.write_text(text)
    print("\n".join(out))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gomp")
    sub.add_parser("examples")
    sub.add_parser("aomp")
    sub.add_parser("hand")
    sub.add_parser("merge")
    sub.add_parser("split")
    sub.add_parser("isolate")
    sub.add_parser("tables")
    p = sub.add_parser("results")
    p.add_argument("--name", default="main")
    p.add_argument("--write", action="store_true")
    p = sub.add_parser("rules")
    p.add_argument("--only", nargs="*")
    a = ap.parse_args(argv)
    return {"gomp": cmd_gomp, "examples": cmd_examples, "aomp": cmd_aomp, "hand": cmd_hand, "merge": cmd_merge, "rules": cmd_rules,
            "split": cmd_split, "isolate": cmd_isolate,
            "tables": cmd_tables, "results": cmd_results}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
