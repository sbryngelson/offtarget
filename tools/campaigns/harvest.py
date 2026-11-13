#!/usr/bin/env python3
"""Harvest LLVM's offload runtime tests and AOMP's smoke tests and run them
through the legality check, the matrix, the reproduction gate and the
confirmer.

The clones (default harvest-src, pinned in
catalog/harvest_sources.yaml) are only read. Subcommands, run with
``python3 -I`` from the repository root:

* ``inventory``, ``filter``, ``convert``: tests and history, verdicts and
  reasons, self-checking programs -> results/harvest/{inventory,filtered,
  programs}.jsonl and src/;
* ``prerun``: the legality pre-check (a Tuolumne compute node);
* ``holdout``: the 30% holdout to data/bench/harvest-holdout;
* ``run``, ``gate``, ``verdicts``, ``report``: the matrix (campaign kind
  ``harvest``), the reproduction gate, the report."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

SRC = Path(os.environ.get("HARVEST_SRC", "harvest-src"))
LLVM = SRC / "llvm" / "llvm-project"
AOMP = SRC / "aomp" / "aomp"
# The harvest this run serves (HARVEST_SET, default the 49a
# harvest): its results/<set>, data/bench/<set>-holdout, catalog/<set>_copy_only.yaml
# and gate campaign kind <set> (build-directory prefix <set>_). The
# programs of harvest2 are made by tools/campaigns/harvest2.py.
SET = os.environ.get("HARVEST_SET", "harvest")
if SET not in ("harvest", "harvest2"):
    raise SystemExit(f"HARVEST_SET {SET!r}: harvest or harvest2")
KIND = SET
OUT = ROOT / "results" / SET
SOURCES = ROOT / "catalog" / "harvest_sources.yaml"


def _git(repo: Path, *args: str) -> str:
    """git in a clone, read only (no hooks run for log/show/ls-tree)."""
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True,
                          errors="replace").stdout


def pinned() -> dict:
    import yaml
    return yaml.safe_load(SOURCES.read_text())


def _jl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out = []
    for ln in path.read_text().splitlines():
        if ln.strip():
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                pass
    return out


def _write_jl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n"
                            for r in rows))


def _show(repo: Path, commit: str, path: str) -> str:
    return _git(repo, "show", f"{commit}:{path}")


def _tree(repo: Path, commit: str, path: str) -> list[str]:
    return [p for p in _git(repo, "ls-tree", "-r", "--name-only", commit,
                            path).splitlines() if p]


# --- inventory ------------------------------------------------------------------------

LOG_FMT = "--format=%x1ecommit%x1f%H%x1f%ad%x1f%B%x1f"


def llvm_inventory(commit: str) -> list[dict]:
    from offload.engine.harvest import history as H
    from offload.engine.harvest import inventory as I
    log = _git(LLVM, "log", "--no-renames", "--name-status", "--date=short",
               LOG_FMT, commit, "--", "offload/test",
               "openmp/libomptarget/test")
    hist = H.parse_log(log, roots=("offload/test/",
                                   "openmp/libomptarget/test/"))
    out = []
    for p in _tree(LLVM, commit, "offload/test"):
        rel = p[len("offload/test/"):]
        if "/Inputs/" in f"/{rel}" or I.lang_of(p) in ("header", "other"):
            continue
        text = _show(LLVM, commit, p)
        if "RUN:" not in text:
            continue
        r = I.llvm_record(rel, text)
        h = hist.get(rel, {})
        r["history"] = {"added": h.get("added"),
                        "fix_commits": h.get("fix_commits", []),
                        "commits": h.get("commits", 0)}
        r["commit"] = commit
        out.append(r)
    return out


def aomp_inventory(commit: str) -> list[dict]:
    from offload.engine.harvest import history as H
    from offload.engine.harvest import inventory as I
    # every test directory of every suite (smoke, smoke-fails, smoke-dev,
    # ...): a test keeps its history when it moves between suites
    log = _git(AOMP, "log", "--no-renames", "--name-status", "--date=short",
               LOG_FMT, commit, "--", "test")
    hist = H.parse_log(log, roots=("test/",), repo="aomp",
                       key_of=lambda p: p.split("/")[1]
                       if p.count("/") >= 2 and p.startswith("smoke")
                       else None)
    paths = _tree(AOMP, commit, "test/smoke") + \
        _tree(AOMP, commit, "test/smoke-fails")
    dirs: dict[str, list[str]] = {}
    for p in paths:
        parts = p.split("/")
        if len(parts) >= 4:
            dirs.setdefault("/".join(parts[1:3]), []).append(p)
    out = []
    for rel, files in sorted(dirs.items()):
        mk = f"test/{rel}/Makefile"
        if mk not in files:
            continue
        texts = {}
        for f in files:
            name = f[len(f"test/{rel}/"):]
            if I.lang_of(name) not in ("other",) or name == "Makefile":
                try:
                    texts[name] = _show(AOMP, commit, f)
                except subprocess.CalledProcessError:
                    pass
        r = I.aomp_record(rel, texts.pop("Makefile", ""), texts)
        r["files"] = [f"test/{f}" for f in r["files"]]
        h = hist.get(rel.split("/")[1], {})
        r["history"] = {"added": h.get("added"),
                        "fix_commits": h.get("fix_commits", []),
                        "commits": h.get("commits", 0)}
        r["tickets"] = H.name_tickets(r["name"])
        r["commit"] = commit
        out.append(r)
    return out


def aomp_issues() -> list[dict]:
    """AOMP's GitHub issues (read only, through gh), cached."""
    cache = OUT / "aomp_issues.json"
    if cache.is_file():
        return json.loads(cache.read_text())
    res = subprocess.run(["gh", "issue", "list", "-R", "ROCm/aomp", "--state",
                          "all", "--limit", "3000", "--json",
                          "number,title,body,state,url"],
                         capture_output=True, text=True, timeout=300)
    if res.returncode != 0:
        print("gh issue list failed:", res.stderr[:300])
        return []
    data = json.loads(res.stdout)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data))
    return data


def link_aomp_issues(records: list[dict], issues: list[dict]) -> None:
    """Each AOMP test's issues that name its directory."""
    import re
    for r in records:
        if r["source"] != "aomp":
            continue
        name = r["name"]
        # a generic name (atomic, class, devices) names no test: a test is
        # named by its path, or by a name with a number in it
        if re.search(r"\d", name) and len(name) >= 6:
            rx = re.compile(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])")
        else:
            rx = re.compile(r"smoke(?:-fails)?/" + re.escape(name) +
                            r"(?![\w-])")
        hits = [i for i in issues
                if rx.search((i.get("title") or "") + "\n" +
                             (i.get("body") or ""))]
        r["aomp_issues"] = [{"number": i["number"], "state": i["state"],
                             "title": i["title"][:120]} for i in hits]


def cmd_inventory(a) -> int:
    pin = pinned()
    recs = llvm_inventory(pin["llvm"]["commit"]) + \
        aomp_inventory(pin["aomp"]["commit"])
    if not a.no_issues:
        link_aomp_issues(recs, aomp_issues())
    _write_jl(OUT / "inventory.jsonl", recs)
    from collections import Counter
    print(len(recs), "tests;", dict(Counter((r["source"], r["lang"])
                                            for r in recs)))
    return 0


def _texts(r: dict) -> dict[str, str]:
    """The texts of a record's files at its pinned commit."""
    repo = LLVM if r["source"] == "llvm" else AOMP
    out = {}
    for f in r["files"]:
        try:
            out[f] = _show(repo, r["commit"], f)
        except subprocess.CalledProcessError:
            out[f] = ""
    return out


def cmd_filter(a) -> int:
    from collections import Counter
    from offload.engine.harvest import filters as F
    rows = []
    for r in _jl(OUT / "inventory.jsonl"):
        v = F.classify(r, _texts(r))
        v.update(source=r["source"], suite=r["suite"], lang=r["lang"])
        rows.append(v)
    _write_jl(OUT / "filtered.jsonl", rows)
    kept = [v for v in rows if v["keep"]]
    print(f"{len(rows)} tests, {len(kept)} kept;",
          dict(Counter((v["source"], v["lang"]) for v in kept)))
    print("primary reasons:", Counter(v["reasons"][0] for v in rows
                                      if not v["keep"]).most_common())
    return 0


def cmd_convert(a) -> int:
    """Each kept variant of each kept test as a program; a test that cannot
    be converted is recorded with the reason."""
    from collections import Counter
    from offload.engine.harvest import convert as C
    if (HOLDOUT / "SEAL").exists():
        # the sealed harvest's programs (and its holdout split) are frozen
        print(f"{HOLDOUT} is sealed: the conversion is frozen (a new harvest "
              "writes a new name)")
        return 1
    inv = {r["id"]: r for r in _jl(OUT / "inventory.jsonl")}
    rows, refused = [], []
    src = OUT / "src"
    src.mkdir(parents=True, exist_ok=True)
    for f in _jl(OUT / "filtered.jsonl"):
        if not f["keep"]:
            continue
        r = inv[f["id"]]
        text = _texts(r)[r["files"][0]]
        kept = [k for k, v in enumerate(f["variants"]) if v["keep"]]
        # Variants whose programs share their code
        # (and memory modes) are one program, before the holdout split
        kept, merged = C.distinct_variants(r, kept, text)
        for n, k in enumerate(kept):
            try:
                p = C.convert(r, n, r["variants"][k], text, len(kept),
                              f["bugfix"])
            except C.ConvertError as e:
                refused.append({"id": f["id"], "variant": k,
                                "reason": f"convert: {e}"})
                continue
            ext = ".c" if p.lang == "c" else ".f90"
            (src / (p.id + ext)).write_text(p.source)
            rows.append({"id": p.id, "record": p.record, "variant": k,
                         "lang": p.lang, "model": p.model,
                         "version": p.version, "oracle": p.oracle,
                         "checks": p.checks, "prefixes": p.prefixes,
                         "stderr": p.stderr, "modes": list(p.modes),
                         "edits": p.edits, "grammar_errors":
                         p.grammar_errors, "sha256": p.sha256,
                         "holdout": p.holdout, "file": p.id + ext,
                         "source": f["source"], "suite": f["suite"],
                         "bugfix": f["bugfix"], "flags": f["flags"],
                         "merged_variants": merged.get(k, []),
                         "code_sha256": C.code_key(p.source, p.lang)})
    ids = Counter(r["id"] for r in rows)
    dup = [i for i, n in ids.items() if n > 1]
    if dup:
        print("duplicate program ids:", dup)
        return 1
    _write_jl(OUT / "programs.jsonl", rows)
    _write_jl(OUT / "convert_refused.jsonl", refused)
    print(f"{len(rows)} programs ({sum(r['holdout'] for r in rows)} "
          f"holdout), {len(refused)} variants not converted:",
          Counter(x["reason"] for x in refused).most_common())
    print(Counter((r["source"], r["lang"], r["oracle"]) for r in rows))
    return 0


def load_programs(name: str = "programs.jsonl") -> list[dict]:
    return _jl(OUT / name)


def src_path(row: dict) -> Path:
    """A program's run copy: results/<set>/src, or for a holdout program of
    harvest2 results/harvest2/holdout-src (tools/campaigns/harvest2.py isolate)."""
    f = OUT / "src" / row["file"]
    if not f.exists() and (OUT / "holdout-src" / row["file"]).exists():
        return OUT / "holdout-src" / row["file"]
    return f


def harness_program(row: dict):
    """The offload.engine.gen.Program of a converted program row."""
    from offload.engine.gen import Program as HP
    text = src_path(row).read_text()
    modes = tuple(row["modes"])
    return HP(id=row["id"], lang=row["lang"], source=text,
              atoms=frozenset({f"harvest.{row['record']}"}),
              primary_atom=f"harvest.{row['record']}", legal=True,
              violates=None, observable=True,
              needs=("zero_copy",) if modes == ("unified",) else (),
              evidence="copy_mode_only" if modes == ("copy",)
              else "construct", model=row["model"])


# --- the legality pre-check -----------------------------------------------------------

class _Pre:
    """What offload.engine.prerun reads of a program."""

    def __init__(self, row: dict):
        self.id = row["id"]
        self.source = src_path(row).read_text()
        self.lang = row["lang"]
        self.model = row["model"]
        self.version = row["version"]


FRONTEND_TIMEOUT = 180     # a front end reads one of these in seconds


def _prerun_one(row: dict) -> dict:
    import time
    from offload.engine import prerun
    from offload.engine import toolchains as T
    if not os.path.exists(f"{T.AFAR_BIN}/amdclang"):
        # Tioga: the same AFAR release on /p/vast1 (no /p/lustre5 there)
        T.AFAR_BIN = T.AFAR_BIN_G90
    t0 = time.time()
    try:
        ok, why = prerun.check(_Pre(row), timeout_s=FRONTEND_TIMEOUT)
    except Exception as e:      # A checker crash is no verdict
        ok, why = False, [f"rules: cannot read it: crashed: "
                          f"{type(e).__name__}: {e}"[:300],
                          "witness unavailable: legality needs two witnesses"]
    return {"id": row["id"], "ok": ok, "reasons": why, "sha256": row["sha256"],
            "kind": "" if ok else prerun.refusal_kind(why),
            "seconds": round(time.time() - t0, 1),
            "node": os.uname().nodename}


def _v2_shas() -> dict[str, str]:
    """The program texts of the second conversion: rows and verdicts
    written before they named their text are of these."""
    return {p["id"]: p["sha256"] for p in _jl(OUT / "programs.v2.jsonl")}


def row_sha(r: dict, v2: dict) -> str | None:
    return r.get("sha256") or v2.get(r.get("program_id") or r.get("id"))


def prerun_rows() -> dict[str, dict]:
    """id -> the pre-run verdict of the program's current text (a verdict
    of another text is not one)."""
    shas = {p["id"]: p["sha256"] for p in load_programs()}
    # a verdict written before verdicts named their text is of the second
    # conversion's text (programs.v2.jsonl)
    v2 = {p["id"]: p["sha256"] for p in _jl(OUT / "programs.v2.jsonl")}
    out = {}
    for r in _jlp(OUT / "prerun.jsonl"):
        # a front end that timed out gave no verdict (checked again)
        if any("timed out" in w for w in r.get("reasons", [])):
            continue
        if (r.get("sha256") or v2.get(r["id"])) == shas.get(r["id"]):
            out[r["id"]] = r
    return out


def cmd_prerun(a) -> int:
    """offload.engine.prerun.check of every program (both witnesses: the rules
    and the AFAR front end, never a compiler on its own program; a
    Tuolumne compute node)."""
    from collections import Counter
    from concurrent.futures import ProcessPoolExecutor
    out = OUT / "prerun.jsonl"
    done = set(prerun_rows())
    todo = [r for r in load_programs() if r["id"] not in done]
    if a.shard:
        k, m = (int(v) for v in a.shard.split("/"))
        todo = todo[k::m]
    from concurrent.futures import as_completed
    print(f"{len(todo)} to check", flush=True)
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        for f in as_completed([pool.submit(_prerun_one, r) for r in todo]):
            _append(out, [f.result()])
    rows = prerun_rows()
    print(f"{len(rows)} checked, {sum(r['ok'] for r in rows.values())} pass;",
          Counter(r["kind"] for r in rows.values() if not r["ok"]))
    return 0


def prerun_ok() -> set[str]:
    return {i for i, r in prerun_rows().items() if r["ok"]}


# --- runs ---------------------------------------------------------------------------

# the targets and their modes (row keys: catalog/machines.yaml); managed
# memory (NVHPC row key 2) is the unified mode
MODE_NAME = {0: "copy", 1: "unified", 2: "unified"}
TARGETS = {"tuolumne": (["afar", "cce19", "cce20", "cce21"] +
                        (["cce21_4"] if SET == "harvest2" else []), [0, 1]),
           "tioga": (["afar_g90", "cce19_g90", "cce20_g90", "cce21_g90"],
                     [0]),
           "wingtip": (["nvhpc", "nvhpc269"], [0, 2])}
RUN_TIMEOUT = 120
COMPILE_TIMEOUT = 600
# the gate's measured over modelled rerun time of catalog-style programs
# (tools/campaigns/gate.py CALIBRATION["catalog"]): a harvested program is one
CALIBRATION = 0.23


def _parts(path: Path) -> list[Path]:
    """The base file, then its per-writer parts oldest first (the part names carry the node
    and pid, so name order is not time order: a retry must read after the row it replaces)."""
    return ([path] if path.is_file() else []) + sorted(
        path.parent.glob(f"{path.stem}.part.*{path.suffix}"),
        key=lambda p: (p.stat().st_mtime_ns, p.name))


def _jlp(path: Path) -> list[dict]:
    """A JSONL file and its per-writer parts (a torn line is skipped)."""
    out = []
    for p in _parts(path):
        out += _jl(p)
    return out


_LOCK = __import__("threading").Lock()


def _append(path: Path, rows: list[dict]) -> None:
    """Append to this process's own part of `path` (two nodes appending to
    one file interleave on NFS)."""
    part = path.parent / (f"{path.stem}.part.{os.uname().nodename}."
                          f"{os.getpid()}{path.suffix}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, open(part, "a") as fh:
        fh.write("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))


def model_supported(p: dict, toolchain: str) -> bool:
    """Whether a toolchain compiles the program's model at all
    (OpenACC: none on AFAR, Fortran only on CCE; harness.py refuses the
    rest). An unsupported pair is not applicable: no cell, no row."""
    if p.get("model") != "acc":
        return True
    if toolchain.startswith("afar"):
        return False
    if toolchain.startswith("cce") and p.get("lang") == "c":
        return False
    return True


def cells(progs: list[dict], toolchains, modes, ok: set,
          copy_only=None) -> list[tuple]:
    """(program row, toolchain, row key): a program that passed the
    pre-run check, in the modes its expected result holds in (a program of
    ``copy_only``, by default catalog/harvest_copy_only.yaml's, in copy
    mode only)."""
    from offload.engine.toolchains import TOOLCHAINS
    if copy_only is None:
        copy_only = load_copy_only()
    out = []
    for p in progs:
        if p["id"] not in ok:
            continue
        for t in toolchains:
            if not model_supported(p, t):
                continue
            tc = TOOLCHAINS[t]
            for x in modes:
                if x and p["id"] in copy_only:
                    continue
                if x in tc.xnack_modes and MODE_NAME[x] in p["modes"]:
                    out.append((p, t, x))
    return out


# --- tests that assume separate memory --------------------
# Many upstream tests check that a host write is not seen on the device (or
# the reverse) until a map or update moves it. With shared storage (AMD
# HSA_XNACK=1, NVHPC managed) the check legitimately fails. Such a dev
# program's unified and managed rows are not applicable: they are not run,
# not gated, not confirmed and not counted. The holdout is not listed (its
# outcomes stay sealed); the ruling scores it on copy cells
# only (catalog/harvest_holdout_excluded.yaml scored_modes).

COPY_ONLY = ROOT / "catalog" / f"{SET}_copy_only.yaml"


def separate_memory_programs(rs: list[dict]) -> set[str]:
    """Programs whose copy cell passes on some compiler while every
    unified or managed cell fails, on every compiler that ran one: the
    rows' evidence that the test assumes separate storage. A unified-memory
    defect shared by every compiler would look the same; a shared-mode
    failure on some compilers only is a candidate defect and is kept."""
    from collections import defaultdict
    copy_ok, shared = defaultdict(bool), defaultdict(list)
    for r in rs:
        c = _cls(r)
        if c == "harness_error":
            continue
        if r["xnack"] == 0:
            copy_ok[r["program_id"]] |= c == "correct_on_device"
        else:
            shared[r["program_id"]].append(c in FAIL_CLASSES)
    return {p for p, fs in shared.items() if copy_ok[p] and all(fs)}


def drop_not_applicable(rs: list[dict], copy_only) -> list[dict]:
    return [r for r in rs
            if not (r["xnack"] and r["program_id"] in copy_only)]


def copy_only_programs(rs: list[dict], pmap: dict) -> list[str]:
    """The dev programs of ``separate_memory_programs`` (never a holdout
    program: its outcomes stay sealed)."""
    return sorted(p for p in separate_memory_programs(rs)
                  if not pmap[p]["holdout"])


def cmd_copy_only(a) -> int:
    """Write catalog/harvest_copy_only.yaml from the run's rows."""
    import yaml
    pmap = {p["id"]: p for p in load_programs()}
    rs = rows(a.name, applicable=False)
    ids = copy_only_programs(rs, pmap)
    n = len(rs) - len(drop_not_applicable(rs, set(ids)))
    head = (
        "# (review I7): dev programs that assume separate host and device storage.\n"
        "# Their unified (AMD HSA_XNACK=1) and managed (NVHPC) rows are not applicable: not run, not gated,\n"
        "# not confirmed, not counted (tools/campaigns/harvest.py rows and cells). Written by\n"
        "# `tools/campaigns/harvest.py copy-only`. Criterion: the copy cell passes on some compiler and every unified or\n"
        "# managed cell fails on every compiler that ran one. Caveat: a unified-memory defect shared by every\n"
        "# compiler looks the same. Holdout programs are never listed (scored on copy cells only:\n"
        "# catalog/harvest_holdout_excluded.yaml scored_modes).\n")
    COPY_ONLY.write_text(head + yaml.safe_dump(
        {"rows_not_applicable": n, "programs": ids}, sort_keys=False))
    print(len(ids), "programs,", n, "unified/managed rows not applicable")
    return 0


def load_copy_only() -> set[str]:
    import yaml
    if not COPY_ONLY.exists():
        return set()
    return set((yaml.safe_load(COPY_ONLY.read_text()) or {}).get(
        "programs") or [])


def hv_value(stdout: str) -> str | None:
    """The failure value of a harvested program's run: its HV-FAIL line
    (which check failed), else the RESULT line's check."""
    import re
    m = re.findall(r"^HV-FAIL (.*)$", stdout or "", re.M)
    if m:
        return "check=fail " + " ".join(m[-1].split())[:120]
    m = re.findall(r"check=(pass|fail)", stdout or "")
    return f"check={m[-1]}" if m else None


def _run_one(job) -> dict:
    import dataclasses
    import time
    from offload.engine import harness, run_matrix
    from offload.engine.toolchains import TOOLCHAINS
    p, t, x, timeout_s = job
    hp = harness_program(p)
    tc = run_matrix.for_version(TOOLCHAINS[t], p["version"], p["lang"])
    t0 = time.time()
    try:
        r = harness.run_program(hp, tc, x, "-O2", timeout_s=timeout_s,
                                repeats=3, version=p["version"],
                                compile_timeout_s=COMPILE_TIMEOUT)
        d = dataclasses.asdict(r)
    except Exception as e:          # a harness failure, not the program's
        d = {"program_id": p["id"], "toolchain": t, "xnack": x,
             "outcome": "harness_error", "reason": f"harness: {e}"[:300]}
    d.update(campaign=KIND, kind=KIND, record=p["record"],
             sha256=p["sha256"],
             lang=p["lang"], mode=MODE_NAME[x], holdout=p["holdout"],
             oracle=p["oracle"], task_s=round(time.time() - t0, 1),
             value=hv_value(d.get("stdout", "")))
    d["stdout"] = (d.get("stdout") or "")[-6000:]
    d["stderr"] = (d.get("stderr") or "")[-4000:]
    return d


def cmd_run(a) -> int:
    """Compile and run the programs on this machine's toolchains through
    the harness (limits, whole-group kill, watchdog), resumable; the
    canaries first (offload.engine.canary)."""
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed
    ok = prerun_ok()
    if not ok:
        print("no program passed the pre-run check: run `prerun` first")
        return 2
    progs = load_programs()
    if a.ids:
        want = set(a.ids.split(","))
        progs = [p for p in progs if p["id"] in want]
    tcs = a.toolchains.split(",") if a.toolchains else TARGETS[a.machine][0]
    modes = [int(m) for m in a.modes.split(",")] if a.modes else \
        TARGETS[a.machine][1]
    d = OUT / a.name
    out = d / "rows.jsonl"
    shas = {p["id"]: p["sha256"] for p in progs}
    v2 = _v2_shas()
    done = {(r["program_id"], r["toolchain"], r["xnack"]) for r in _jlp(out)
            if (r.get("outcome") != "harness_error" or not a.retry_errors)
            and row_sha(r, v2) == shas.get(r["program_id"])}
    jobs = [(p, t, x, a.timeout) for p, t, x in cells(progs, tcs, modes, ok)
            if (p["id"], t, x) not in done]
    if a.shard:
        k, m = (int(v) for v in a.shard.split("/"))
        jobs = jobs[k::m]
    import threading
    can = None
    if a.canaries and (not a.shard or a.shard.startswith("0/")):
        # beside the runs (one more worker), not before them
        can = threading.Thread(target=_canaries, args=(d, tcs, modes))
        can.start()
    print(f"{len(jobs)} runs to do ({len(done)} done)", flush=True)
    end = time.time() + a.limit_s
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futs = [pool.submit(lambda j=j: None if time.time() > end
                            else _run_one(j)) for j in jobs]
        for f in as_completed(futs):
            r = f.result()
            if r is not None:
                _append(out, [r])
    if can is not None:
        can.join()
    print("done", flush=True)
    return 0


def _canaries(d: Path, tcs, modes) -> None:
    """The canaries of catalog/canaries.yaml on these toolchains and modes
    (every campaign runs them), in <run>/canaries.jsonl; only
    the (toolchain, mode) pairs not recorded yet."""
    from offload.engine import canary
    path = d / "canaries.jsonl"
    have = {(r.get("toolchain"), int(r.get("xnack", -1)))
            for r in (_jl(path) if path.is_file() else [])}
    for t in tcs:
        for x in modes:
            from offload.engine.toolchains import TOOLCHAINS
            if x not in TOOLCHAINS[t].xnack_modes or (t, x) in have:
                continue
            canary.add_to_campaign(path, [t], [x], RUN_TIMEOUT)


def rows(name: str, applicable: bool = True) -> list[dict]:
    """One row per (program, toolchain, row key): the last written of the
    program's current text (a row of an earlier conversion is dropped);
    with ``applicable``, without the shared-mode rows of the copy-only
    programs."""
    shas = {p["id"]: p["sha256"] for p in load_programs()}
    v2 = _v2_shas()
    last = {}
    for r in _jlp(OUT / name / "rows.jsonl"):
        if row_sha(r, v2) != shas.get(r["program_id"]):
            continue
        last[(r["program_id"], r["toolchain"], r["xnack"])] = r
    pm = {p["id"]: p for p in load_programs()}
    out = [r for r in last.values()
           if model_supported(pm.get(r["program_id"], {}), r["toolchain"])]
    return drop_not_applicable(out, load_copy_only()) if applicable else out


# --- the reproduction gate ----------------------------------------------------------
# The gate (offload.engine.gate) with the campaign kind ``harvest``
# (build-directory prefix harvest_, signatures per program): environments,
# gate_run.rerun_program, judge, plan and inherit, as in dataenv. A
# harvested program's wrong answer is keyed by its HV-FAIL line (which
# check failed: ``value``), on the stored row and on every rerun alike.

def _register():
    from offload.engine import gate as GT
    GT.register_kind(KIND, f"{KIND}_", "program")
    GT.COMPILE_LIMIT_S.setdefault(KIND, COMPILE_TIMEOUT)
    return GT


PASSING = ("correct_on_device", "unobservable", "harness_error")


def gate_items(name: str, machine: str | None = None) -> list[dict]:
    """The failing rows of a run as gate items (one machine, or all)."""
    from offload.engine.gate_stored import machine_of
    out = []
    for r in rows(name):
        if r["outcome"] in PASSING:
            continue
        m = machine_of(r["toolchain"])
        if machine and m != machine:
            continue
        out.append({**{k: r.get(k) for k in (
            "outcome", "reason", "flaky", "build_dir", "node",
            "toolchain_build", "toolchain", "xnack", "mode", "version",
            "lang", "record", "holdout")},
            "campaign": KIND, "kind": KIND, "machine": m,
            "ident": r["program_id"], "opt": "-O2",
            "timeout_s": RUN_TIMEOUT, "value": hv_value(r.get("stdout")),
            "stdout": (r.get("stdout") or "")[-400:],
            "compile_log": (r.get("stderr") or "")[-3000:],
            "cell": f"{KIND}|{r['program_id']}|{r['toolchain']}|"
                    f"{r['xnack']}"})
    return out


def gate_plan(items: list[dict], budget_s: float | None = None) -> dict:
    """offload.engine.gate.plan; without a budget one that covers every row."""
    GT = _register()
    total = sum(len(GT.ENVS) * GT.cost_s(it) for it in items) + 1
    return GT.plan(items, budget_s=total if budget_s is None else budget_s)


def _owner(it: dict, alloc: list[str]) -> str:
    """The node of the allocation that reruns (a), (b), (d) of a row: its
    own node when the allocation has it, else one chosen by the cell."""
    import zlib
    if it.get("node") in alloc:
        return it["node"]
    return alloc[zlib.crc32(it["cell"].encode()) % len(alloc)]


def _rerun_sha(r: dict, v4: dict) -> str | None:
    """The program text a rerun ran: its own record, else (reruns written
    before they named it) the fourth conversion's (programs.v4.jsonl)."""
    return r.get("sha256") or v4.get(r["cell"].split("|")[1])


def current_reruns(name: str) -> list[dict]:
    """The gate's reruns of the programs' current texts."""
    shas = {p["id"]: p["sha256"] for p in load_programs()}
    v4 = {p["id"]: p["sha256"] for p in _jl(OUT / "programs.v4.jsonl")}
    return [r for r in _jlp(OUT / name / "gate_reruns.jsonl")
            if _rerun_sha(r, v4) == shas.get(r["cell"].split("|")[1])]


def gate_priority(items: list[dict], progs: dict | None = None
                  ) -> dict[str, int]:
    """cell -> tier, the order the gate reruns rows in (the maintainer,
    2026-10-26): 0 the first row of a signature of a bug-fix test, 1 the
    other rows of bug-fix tests, 2 the first row of every other signature,
    3 the rest; a compile-time row that is not its signature's first can
    inherit its verdict, so it comes last (4)."""
    import hashlib
    GT = _register()
    if progs is None:
        progs = {p["id"]: p for p in load_programs()}
    first = {}
    for it in sorted(items, key=lambda r: hashlib.sha256(
            r["cell"].encode()).hexdigest()):
        first.setdefault(GT.signature(it), it["cell"])
    out = {}
    for it in items:
        bf = bool((progs.get(it["ident"]) or {}).get("bugfix"))
        lead = first[GT.signature(it)] == it["cell"]
        if bf:
            out[it["cell"]] = 0 if lead else 1
        elif lead:
            out[it["cell"]] = 2
        else:
            out[it["cell"]] = 4 if GT.inheritable(it) else 3
    return out


def c_other_node_items(items: list[dict], reruns: list[dict],
                       here: str) -> list[dict]:
    """The rows whose environment (c) has not yet run on
    a node other than their (a)'s and whose (a) did not run on this node
    (``here``): a (c) of one of them run here is a node change. Rows
    without an (a) rerun are left to the normal gate."""
    a_nodes: dict[str, set] = {}
    c_nodes: dict[str, set] = {}
    for r in reruns:
        if r.get("env") in ("a", "d") and r.get("node"):
            a_nodes.setdefault(r["cell"], set()).add(r["node"])
        elif r.get("env") == "c" and r.get("node"):
            c_nodes.setdefault(r["cell"], set()).add(r["node"])
    out = []
    for it in items:
        an = a_nodes.get(it["cell"])
        if not an or here in an:
            continue
        if c_nodes.get(it["cell"], set()) - an:
            continue
        out.append(it)
    return out


def cmd_gate(a) -> int:
    """Rerun this machine's failing rows in the gate's environments, in
    ``gate_priority`` order. Two-node jobs (``--alloc``): this node reruns
    (a), (b), (d) of the rows it owns (``_owner``: the row's node, else
    one chosen by the cell) and (c) of the others it did not run. Wingtip
    (``--shard K/2``): (a), (b), (d) of half K and (c) of the other half on
    this GPU. ``--envs`` limits the environments."""
    import hashlib
    import time
    from concurrent.futures import ThreadPoolExecutor
    from offload.engine import gate_run as GR
    from offload.engine import run_matrix
    from offload.engine.provenance import node
    from offload.engine.toolchains import TOOLCHAINS
    GT = _register()
    progs = {p["id"]: p for p in load_programs()}
    planned = gate_plan(gate_items(a.name, a.machine))
    items = [r for r in planned["rows"] if r["sample"] != "own"]
    tier = gate_priority(items)
    d = OUT / a.name
    d.mkdir(parents=True, exist_ok=True)
    (d / f"gate_plan.{a.machine}.json").write_text(json.dumps(
        {k: v for k, v in planned.items() if k != "rows"} |
        {"samples": {r["cell"]: r["sample"] for r in planned["rows"]},
         "tiers": tier}, indent=1, sort_keys=True))
    envs = set(a.envs.split(","))
    roles = []                      # (item, environments to run here)
    if a.alloc:
        alloc = a.alloc.split(",")
        here = node()
        for it in items:
            if _owner(it, alloc) == here:
                roles.append((it, {"a", "b", "d"} & envs))
            elif it.get("node") != here:
                roles.append((it, {"c"} & envs))
    elif a.shard:
        # a row's half is fixed by its cell, so later rows never move it
        import zlib
        k, m = (int(v) for v in a.shard.split("/"))
        for it in items:
            n = zlib.crc32(it["cell"].encode()) % m
            if n == k:
                roles.append((it, {"a", "b", "d"} & envs))
            elif n == (k + 1) % m:
                roles.append((it, {"c"} & envs))
    elif a.c_other_node:
        # (c) again, on a node other than (a)'s
        roles = [(it, {"c"}) for it in c_other_node_items(
            items, current_reruns(a.name), node())]
    else:
        roles = [(it, envs) for it in items]
    out = d / "gate_reruns.jsonl"
    done = {(r["cell"], r["env"]) for r in current_reruns(a.name)}
    if a.c_other_node:
        done = {k for k in done if k[1] != "c"}
    jobs = []
    for it, want in roles:
        es = [e for e in GT.environments(it, a.root or None)
              if e["env"] in want and (it["cell"], e["env"]) not in done]
        if os.environ.get("COMPLIANT_RUN_SLOTS"):
            # One host (wingtip): (c), "another node", runs on
            # the other GPU in another process while (a), (b), (d) of the
            # same row may run here; its build path gets the GPU's name so
            # the two never share a directory
            gpu = os.environ.get("CUDA_VISIBLE_DEVICES", "all")
            es = [{**e, "path": f"{e['path']}_gpu{gpu}"} if e["env"] == "c"
                  else e for e in es]
        if es:
            jobs.append((it, es))
    jobs.sort(key=lambda j: (tier[j[0]["cell"]], hashlib.sha256(
        j[0]["cell"].encode()).hexdigest()))
    est = sum(len(es) * GT.cost_s(it) for it, es in jobs)
    print(f"{len(planned['rows'])} failing rows, {len(jobs)} here, "
          f"{sum(len(j[1]) for j in jobs)} reruns; model {est / 3600:.1f} "
          f"serial h, calibrated {est * CALIBRATION / 3600:.1f}", flush=True)
    end = time.time() + a.limit_s

    def one(job):
        it, es = job
        p = progs[it["ident"]]
        tc = run_matrix.for_version(TOOLCHAINS[it["toolchain"]],
                                    p["version"], p["lang"])
        for e in es:
            if time.time() > end:
                return
            try:
                rr = GR.rerun_program(harness_program(p), tc,
                                      int(it["xnack"]), e, "-O2",
                                      timeout_s=RUN_TIMEOUT,
                                      compile_timeout_s=COMPILE_TIMEOUT)
            except Exception as x:  # One rerun's failure is no
                # verdict; the others go on (the row stays unchecked)
                print(f"rerun {it['cell']} {e['env']}: {x}", flush=True)
                continue
            if os.environ.get("COMPLIANT_RUN_SLOTS"):
                # one host (wingtip): (c) is another GPU
                rr["node"] = f"{rr.get('node', '')}:gpu" \
                    f"{os.environ.get('CUDA_VISIBLE_DEVICES', 'all')}"
            rr["value"] = hv_value(rr.get("stdout"))
            rr["tier"] = tier[it["cell"]]
            rr["sha256"] = p["sha256"]
            _append(out, [{**rr, "cell": it["cell"]}])
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        list(pool.map(one, jobs))
    return 0


def verdicts(name: str, budget_h: float | None = None) -> dict:
    """cell -> the gate's verdict record: offload.engine.gate.judge of the
    row's own reruns, then offload.engine.gate.inherit over the plan."""
    from collections import defaultdict
    GT = _register()
    reruns = defaultdict(list)
    for r in current_reruns(name):
        r = dict(r)
        r["value"] = hv_value(r.get("stdout"))
        reruns[r["cell"]].append(r)
    planned = gate_plan(gate_items(name),
                        budget_h * 3600 if budget_h else None)["rows"]
    judged = {}
    for it in planned:
        if not reruns.get(it["cell"]):
            continue
        try:
            judged[it["cell"]] = GT.judge(it, reruns[it["cell"]])
        except ValueError:
            pass
    final = GT.inherit(planned, {c: j["verdict"] for c, j in judged.items()})
    out = {}
    for it in planned:
        c = it["cell"]
        f = final.get(c, {"verdict": "unchecked", "inherited": False})
        rec = {**judged.get(c, {}), **f, "item": it, "sample": it["sample"],
               "n_reruns": len(reruns.get(c, []))}
        rec["own"] = c in judged and not f.get("inherited") and \
            f["verdict"] == judged[c]["verdict"]
        out[c] = rec
    return out


# --- the holdout ----------------------------------------------------------------------
# 30% of the programs (the lowest 30% of the sha256 space of the converted
# text, offload.engine.harvest.convert.holdout) are data/bench/harvest-holdout:
# opaque case files harvest-holdout-NNN.<c|f90> (numbered in program-id
# order), cases.yaml (provenance), then outcomes.csv and SEAL after the runs
# (tools/campaigns/fresh_bench.py's digest), sealed like data/bench/fresh2.

HOLDOUT = ROOT / "data" / "bench" / f"{SET}-holdout"
CASE_PREFIX = f"{SET}-holdout-"


def _upstream_url(rec: dict) -> str:
    if rec["source"] == "llvm":
        return (f"https://github.com/llvm/llvm-project/blob/"
                f"{rec['commit']}/{rec['path']}")
    return f"https://github.com/ROCm/aomp/tree/{rec['commit']}/{rec['path']}"


def holdout_cases() -> list[dict]:
    """The holdout's programs, numbered (pre-run refusals included: they
    are cases whose outcome is the refusal)."""
    progs = sorted((p for p in load_programs() if p["holdout"]),
                   key=lambda p: p["id"])
    return [{**p, "case": f"{CASE_PREFIX}{k:03d}"}
            for k, p in enumerate(progs, start=1)]


def cmd_holdout(a) -> int:
    import shutil
    import yaml
    inv = {r["id"]: r for r in _jl(OUT / "inventory.jsonl")}
    pre = prerun_rows()
    HOLDOUT.mkdir(parents=True, exist_ok=True)
    if (HOLDOUT / "SEAL").exists():
        print("data/bench/harvest-holdout is sealed: not rewritten")
        return 1
    cases = []
    for c in holdout_cases():
        rec = inv[c["record"]]
        ext = ".c" if c["lang"] == "c" else ".f90"
        shutil.copyfile(OUT / "src" / c["file"], HOLDOUT / (c["case"] + ext))
        add = (rec.get("history") or {}).get("added") or {}
        pr = pre.get(c["id"], {})
        cases.append({
            "id": c["case"], "file": c["case"] + ext, "program": c["id"],
            "url": _upstream_url(rec), "project": "llvm/llvm-project"
            if rec["source"] == "llvm" else "ROCm/aomp",
            "suite": rec["suite"], "commit": rec["commit"],
            "license": rec["license"], "lang": c["lang"], "model": c["model"],
            "omp_version": c["version"], "oracle": c["oracle"],
            "checks": c["checks"], "modes": c["modes"],
            "added": {"commit": add.get("commit", ""),
                      "date": add.get("date", ""),
                      "subject": add.get("subject", "")},
            "bugfix": c["bugfix"], "flags": c["flags"],
            "prerun": "pass" if pr.get("ok") else
            f"refused: {pr.get('kind', '?')}", "sha256": c["sha256"],
            "source_kind": "test-suite"})
    (HOLDOUT / "cases.yaml").write_text(yaml.safe_dump(
        {"cases": cases}, sort_keys=False, width=100))
    print(f"{len(cases)} holdout cases -> {HOLDOUT}")
    return 0


# --- the confirmer --------------------------------------------------------------------
# offload.engine.confirm's engine on every failing row, offline: the case's
# program is the converted file (kind "file", expected "check=pass"), the
# stored index is the harvest rows of every toolchain and mode (the other
# toolchains, the other mode, the other arch and the NVHPC families come
# from them; nothing is run), the gate's verdicts are the harvest gate's,
# and legality is the pre-run check's two witnesses: the rules and a front
# end not under test (AFAR's for a CCE or NVHPC case; for an AFAR case an
# NVHPC compile of the program in the matrix, the witness uses).

def _legality(p: dict, toolchain: str, pre: dict, by_prog: dict):
    from offload.engine.confirm.legality import Legality
    from offload.engine.confirm.machines import family_of
    r = pre.get(p["id"])
    if not r or not r["ok"]:
        return Legality("unknown", "the pre-run check refused it")
    if family_of(toolchain) != "afar":
        return Legality("legal", "two witnesses (offload.engine.prerun.check): "
                        "the rules and the AFAR front end, not under test")
    nv = [x for x in by_prog.get(p["id"], []) if x["toolchain"] in
          ("nvhpc", "nvhpc269") and x["outcome"] != "rejected" and
          not str(x.get("reason", "")).startswith(("ice", "compile"))]
    if nv:
        return Legality("legal", "two witnesses: the rules and NVHPC, which "
                        f"compiled it ({nv[0]['toolchain']}); the AFAR front "
                        "end is under test")
    return Legality("unknown", "an AFAR case: no front end not under test "
                    "compiled it (NVHPC rejected it or has no row)")


def confirm_context(name: str) -> dict:
    """The confirmer's inputs: the current rows, the programs, the pre-run
    verdicts of the programs' current texts from every writer's part
    (``prerun_rows``; the main file alone held
    stale and partial verdicts), the rows by program and the gate's
    verdicts."""
    from collections import defaultdict
    rs = rows(name)
    by_prog = defaultdict(list)
    for r in rs:
        by_prog[r["program_id"]].append(r)
    return {"rows": rs, "progs": {p["id"]: p for p in load_programs()},
            "pre": prerun_rows(), "by_prog": by_prog,
            "ver": verdicts(name)}


MISSING = {
    "R11-compile-rejection": "a check of the vendor's documented support "
    "for the rejected construct (an unsupported feature is not a defect), "
    "then a reduced reproducer",
    "R10b-own-link-or-hang": "a check of the vendor's documented support in "
    "offload regions (CCE lists the routines and constructs it supports "
    "there), then a reduced reproducer",
    "R10-compile-ice": "a reduced reproducer, deduplicated against the "
    "index's ICE signatures",
}


def candidates(conf: list[dict], pmap: dict, covered: set) -> list[dict]:
    """Fix: the non-holdout programs with a confirmer
    compiler_bug row that no finding covers (a confirmer link, or an
    upstream test of catalog/harvest_findings.yaml), with what promotion
    still needs."""
    from collections import defaultdict
    from offload.engine.confirm.machines import family_of
    by = defaultdict(list)
    for c in conf:
        if c.get("verdict") == "compiler_bug" and not c.get("holdout"):
            by[c["program"]].append(c)
    out = []
    for pid, cs in sorted(by.items()):
        rec = pmap[pid]["record"]
        if any(rec == u or u.endswith("/") and rec.startswith(u)
               for u in covered) or any(c.get("findings") for c in cs):
            continue
        rules = sorted({c["rule"] for c in cs})
        out.append({
            "test": rec,
            "families": sorted({family_of(c["toolchain"]) for c in cs}),
            "toolchains": sorted({c["toolchain"] for c in cs}),
            "rules": rules,
            "message": " ".join((cs[0].get("row_reason") or
                                 cs[0].get("reason") or "").split())[:160],
            "missing": "; ".join(MISSING.get(r, "a hand review")
                                 for r in rules)})
    return out


def covered_tests(d: dict) -> set[str]:
    """The upstream tests (a path, or a directory ending in /) the new and
    linked findings of catalog/harvest_findings.yaml name: an entry's word
    with a slash."""
    return {w for sec in ("new", "linked") for f in d.get(sec) or []
            for u in f.get("upstream") or [] for w in u.split() if "/" in w}


def cmd_candidates(a) -> int:
    """Write the candidates of catalog/harvest_findings.yaml."""
    import yaml
    path = ROOT / "catalog" / "harvest_findings.yaml"
    text = path.read_text()
    d = yaml.safe_load(text)
    covered = covered_tests(d)
    pmap = {p["id"]: p for p in load_programs()}
    reasons = {(r["program_id"], r["toolchain"]): r.get("reason", "")
               for r in rows(a.name)}
    conf = [{**c, "row_reason": reasons.get((c["program"], c["toolchain"]),
                                            "")}
            for c in _jl(OUT / a.name / "confirm.jsonl")]
    cs = candidates(conf, pmap, covered)
    head = text[:text.index("candidates:")]
    path.write_text(head + yaml.safe_dump({"candidates": cs},
                                          sort_keys=False, width=100))
    print(len(cs), "candidates")
    return 0


def confirm_todo(rows_, toolchains=None) -> list:
    """The failing rows the confirmer judges (coverage parity: of some
    toolchains only, the others' rows staying evidence)."""
    return [x for x in rows_ if x.outcome not in ("correct_on_device",
                                                  "unobservable",
                                                  "harness_error")
            and (not toolchains or x.toolchain in toolchains)]


def cmd_confirm(a) -> int:
    import dataclasses
    from collections import Counter
    from offload.engine import gate as GT
    from offload.engine.confirm import engine as EN
    from offload.engine.confirm import ingest as IG
    from offload.engine.confirm import programs as P
    from offload.engine.confirm.collectors import Context
    from offload.engine.confirm.store import Store
    _register()
    d = OUT / a.name
    cx = confirm_context(a.name)
    rs, progs, pre, by_prog, ver = (cx["rows"], cx["progs"], cx["pre"],
                                     cx["by_prog"], cx["ver"])
    # the gate verdicts as the confirmer reads them (kind "file")
    gv = d / "gate_verdicts.file.jsonl"
    with open(gv, "w") as fh:
        for c, v in ver.items():
            it = v["item"]
            fh.write(json.dumps({"cell": c, "kind": "file",
                                 "ident": it["ident"],
                                 "toolchain": it["toolchain"],
                                 "xnack": it["xnack"],
                                 "verdict": v["verdict"]}) + "\n")
    GT.VERDICTS_FILE = gv
    rows_ = []
    for r in rs:
        try:
            row = IG.row_of_result(r, f"results/{SET}/{a.name}/rows.jsonl")
        except KeyError:
            continue
        rows_.append(dataclasses.replace(row, kind="file"))
    ctx = Context(IG.Index(rows_), Store(d / "confirm_evidence.jsonl"),
                  allow_run=False)
    refs = {}
    out = []
    todo = confirm_todo(rows_, set(a.toolchains.split(","))
                        if a.toolchains else None)
    vby = {(v["item"]["ident"], v["item"]["toolchain"],
            IG._mode(v["item"]["toolchain"], v["item"]["xnack"])[1]):
           v["verdict"] for v in ver.values()}
    if a.only_confirmed:
        todo = [x for x in todo if vby.get((x.ident, x.toolchain, x.mode))
                == "confirmed"]
    for x in todo:
        p = progs[x.ident]
        if x.ident not in refs:
            refs[x.ident] = P.file_ref([str(src_path(p))],
                                       "check=pass", label=x.ident,
                                       version=p["version"])
        case = IG.case_of_row(x, refs[x.ident])
        try:
            res = EN.confirm(case, ctx, legality=_legality(
                p, x.toolchain, pre, by_prog), minimize=False, draft=False)
        except Exception as e:
            res = {"verdict": "error", "rule": "", "reason": f"{e}"[:300]}
        out.append({"program": x.ident, "toolchain": x.toolchain,
                    "mode": x.mode, "outcome": x.outcome,
                    "verdict": res.get("verdict"), "rule": res.get("rule"),
                    "reason": (res.get("reason") or "")[:400],
                    "gate": res.get("gate") or vby.get(
                        (x.ident, x.toolchain, x.mode)),
                    "findings": [f.get("file") for f in res.get(
                        "findings") or []],
                    "related": [f.get("file") for f in res.get(
                        "related") or []],
                    "legality": (res.get("legality") or {}).get("status"),
                    "holdout": p["holdout"]})
    _write_jl(d / "confirm.jsonl", out)
    print(len(out), "cases;", Counter(o["verdict"] for o in out))
    return 0


# --- the report -----------------------------------------------------------------------

REPORT = ROOT / "data" / "reports" / "harvest-llvm-aomp.md"
TC_ORDER = ["afar", "cce19", "cce20", "cce21", "afar_g90", "cce19_g90",
            "cce20_g90", "cce21_g90", "nvhpc", "nvhpc269"]
FAIL_CLASSES = ("rejected", "ice", "crash", "run_error", "timeout",
                "wrong_answer", "fell_back_to_host", "accepted_ignored")


def _cls(r: dict) -> str:
    from offload.engine import gate as GT
    return GT.outcome_class(r)


def _mode_label(tc: str, x: int) -> str:
    if tc.startswith("nvhpc"):
        return "separate" if x == 0 else "managed"
    return f"X{x}"


def summary(name: str) -> dict:
    """Every count of the funnel and the tables of the report."""
    from collections import Counter, defaultdict
    inv = _jl(OUT / "inventory.jsonl")
    filt = _jl(OUT / "filtered.jsonl")
    progs = load_programs()
    pmap = {p["id"]: p for p in progs}
    refused_conv = _jl(OUT / "convert_refused.jsonl")
    pre = prerun_rows()
    rs = rows(name)
    ver = verdicts(name) if rs else {}
    conf = _jl(OUT / name / "confirm.jsonl")
    s = {"inventory": Counter((r["source"], r["lang"]) for r in inv),
         "inventory_n": len(inv),
         "kept_tests": sum(f["keep"] for f in filt),
         "filtered": Counter(f["reasons"][0] for f in filt
                             if not f["keep"]),
         "filtered_all": Counter(x for f in filt if not f["keep"]
                                 for x in f["reasons"]),
         "programs": len(progs),
         "programs_by": Counter((p["source"], p["lang"], p["oracle"])
                                for p in progs),
         "holdout": sum(p["holdout"] for p in progs),
         "convert_refused": Counter(x["reason"] for x in refused_conv),
         "prerun_ok": sum(1 for p in progs if pre.get(p["id"], {}).get(
             "ok")),
         "prerun_refused": Counter(pre[p["id"]]["kind"] for p in progs
                                   if p["id"] in pre and
                                   not pre[p["id"]]["ok"]),
         "prerun_missing": sum(1 for p in progs if p["id"] not in pre),
         "cells": len(rs)}
    ok = {i for i, r in pre.items() if r["ok"]}
    have = {(r["program_id"], r["toolchain"], r["xnack"]) for r in rs}
    s["cells_planned"] = 0
    s["not_run"] = []
    for tcs, modes in TARGETS.values():
        want = {(p["id"], t, x) for p, t, x in cells(progs, tcs, modes, ok)}
        s["cells_planned"] += len(want)
        s["not_run"] += sorted(want - have)
    # outcome counts are of the dev programs only (holdout-inclusive totals less the dev tables named the
    # holdout's failing counts)
    def dev(pid):
        return pid in pmap and not pmap[pid]["holdout"]
    dev_rs = [r for r in rs if dev(r["program_id"])]
    dev_ver = {c: v for c, v in ver.items() if dev(c.split("|")[1])}
    dev_conf = [c for c in conf if not c.get("holdout")]
    per = defaultdict(Counter)
    for r in dev_rs:
        per[(r["toolchain"], r["xnack"])][_cls(r)] += 1
    s["per_cell"] = per
    co = load_copy_only()
    s["copy_only"] = len(co)
    s["not_applicable"] = len(rows(name, applicable=False)) - len(rs) \
        if co else 0
    s["dev_cells"] = len(dev_rs)
    s["failing_rows"] = sum(1 for r in dev_rs if _cls(r) in FAIL_CLASSES)
    s["harness_errors"] = sum(1 for r in dev_rs
                              if _cls(r) == "harness_error")
    s["gate"] = Counter(v["verdict"] for v in dev_ver.values())
    s["gate_own"] = Counter(v["verdict"] for v in dev_ver.values()
                            if v.get("own"))
    s["confirm"] = Counter(c["verdict"] for c in dev_conf)
    s["confirm_gated"] = Counter(c["verdict"] for c in dev_conf
                                 if c.get("gate") == "confirmed")
    s["linked"] = Counter(f for c in conf for f in c.get("findings") or [])
    s["ver"] = ver
    s["conf"] = conf
    s["rows"] = rs
    s["pmap"] = pmap
    s["pre"] = pre
    s["filt"] = {f["id"]: f for f in filt}
    return s


def program_status(s: dict) -> dict:
    """program -> {toolchain/mode label: (class, gate verdict)} of its
    failing cells, and whether every cell passed somewhere."""
    from collections import defaultdict
    out = defaultdict(dict)
    for r in s["rows"]:
        c = _cls(r)
        cell = f"harvest|{r['program_id']}|{r['toolchain']}|{r['xnack']}"
        v = s["ver"].get(cell, {}).get("verdict", "")
        out[r["program_id"]][f"{r['toolchain']} "
                             f"{_mode_label(r['toolchain'], r['xnack'])}"] \
            = (c, v)
    return out


def _md_table(head: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(x) for x in r) + " |" for r in rows]
    return out


REASON_TEXT = {
    "cpp": "C++ (counted, not run: the harness has no C++)",
    "cuda_hip": "CUDA or HIP source", "fixed_form": "fixed-form Fortran",
    "mixed_language": "C and Fortran in one test",
    "no_source": "no source the harness compiles",
    "multi_file": "more than one translation unit",
    "mixed_models": "OpenMP and OpenACC in one test",
    "host_only": "no device construct or device routine (host only)",
    "llvm_extension": "LLVM/AMD extension (ompx_*, builtins, attributes)",
    "arch_specific": "code under an offload-arch macro",
    "runtime_internals": "libomptarget internals (__tgt_*, __kmpc_*)",
    "nonspec_routine": "an omp_ routine in no OpenMP spec (llvm_omp_*, ...)",
    "ompt": "OMPT", "hip_cuda_interop": "HIP/CUDA interoperation",
    "mpi": "MPI", "needs_files": "reads an input file",
    "needs_args": "program arguments (Fortran)",
    "needs_other_tools": "build or check steps beyond compile, run, FileCheck",
    "llvm_libc": "LLVM GPU libc (REQUIRES libc, offload/test/libc)",
    "llvm_debug": "REQUIRES libomptarget-debug",
    "llvm_pgo": "REQUIRES pgo", "compile_only": "compile only (IR, diagnostics)",
    "sanitizer": "an offload sanitizer test (a deliberately erroneous program)",
    "llvm_machine": "REQUIRES large_allocation_memory_pool",
    "no_run": "no run step",
    "llvm_flag": "a compile flag with no standard meaning (-fopenmp-*, -mllvm, ...)",
    "llvm_env": "an LLVM/vendor runtime variable (LIBOMPTARGET_*, OFFLOAD_*, ...)",
    "needs_omp_env": "an OMP_* variable the harness cannot set per program",
    "host_fallback_test": "OMP_TARGET_OFFLOAD=disabled",
    "expects_failure": "the run must fail (checks an LLVM runtime message)",
    "target_specific": "a triple's own run or checks",
    "filecheck_unsupported": "FileCheck numeric or line variables",
    "checks_llvm_message": "CHECK lines on LLVM runtime or plugin output",
    "no_check_lines": "a FileCheck prefix with no lines"}


def _short(tc: str) -> str:
    return tc.replace("_g90", "g").replace("nvhpc269", "nv269")


def _families_passing(cells: dict) -> set:
    from offload.engine.confirm.machines import family_of
    return {family_of(k.split()[0]) for k, (c, _) in cells.items()
            if c == "correct_on_device"}


def render(name: str) -> str:
    """The harvest LLVM/AOMP report (counts and tables; the holdout's
    programs are counted, never named)."""
    from collections import Counter, defaultdict
    from offload.engine.confirm.machines import family_of
    s = summary(name)
    pin = pinned()
    stat = program_status(s)
    pm = s["pmap"]
    L = ["# Old offload bugs: LLVM offload tests and AOMP smoke tests on our "
         "compilers", "",
         "Generated by `python3 -I tools/campaigns/harvest.py report` "
         "(tools/campaigns/harvest.py, offload/engine/harvest/); do not edit. Sources: "
         f"llvm-project `offload/test` at {pin['llvm']['commit'][:12]} "
         "(history of `offload/test` and `openmp/libomptarget/test`), "
         f"ROCm/aomp `test/smoke` and `test/smoke-fails` at "
         f"{pin['aomp']['commit'][:12]} (catalog/harvest_sources.yaml). "
         "The 30% holdout (data/bench/harvest-holdout) is counted here and never "
         "named.", ""]
    # --- the funnel
    gate = s["gate"]
    L += ["## Funnel", ""]
    pmap = s["pmap"]
    L += _md_table(["stage", "count", "note"], [
        ["inventory (tests)", s["inventory_n"], ", ".join(
            f"{a} {b} {n}" for (a, b), n in sorted(s["inventory"].items()))],
        ["filtered out (tests)", s["inventory_n"] - s["kept_tests"],
         "by primary reason below"],
        ["kept (tests)", s["kept_tests"], ""],
        ["converted (programs: kept RUN variants)", s["programs"],
         f"not converted: {dict(s['convert_refused']) or 0}"],
        ["holdout (of the converted)", s["holdout"],
         "lowest 30% of the sha256 space of the program text"],
        ["refused by the pre-run check", sum(s["prerun_refused"].values()),
         ", ".join(f"{k} {n}" for k, n in s["prerun_refused"].most_common())],
        ["not checked (no verdict on the final text)", s["prerun_missing"],
         ""],
        ["run (passed the pre-run check)", s["prerun_ok"], ""],
        ["cells run (program x toolchain x mode)", s["cells"],
         f"of {s['cells_planned']}; not run: " + (", ".join(
             f"{pmap[i]['record'] if not pmap[i]['holdout'] else 'a holdout program'}"
             f" {t} {_mode_label(t, x)}" for i, t, x in s["not_run"])
             or "none") + (" (the harness call hung past its limits "
                           "for 40 minutes and was cancelled)"
                           if s["not_run"] else "")],
        ["not applicable (unified/managed rows of copy-only dev "
         "programs)", s["not_applicable"],
         f"{s['copy_only']} programs that assume separate memory "
         "(catalog/harvest_copy_only.yaml); not in the cells above"],
        ["failing rows (non-holdout, as every count below)",
         s["failing_rows"],
         f"harness errors (not counted): {s['harness_errors']}"],
        ["gate: confirmed (own reruns / inherited)",
         f"{s['gate_own'].get('confirmed', 0)} / "
         f"{gate.get('confirmed', 0) - s['gate_own'].get('confirmed', 0)}",
         ", ".join(f"{k} {n}" for k, n in gate.most_common()
                   if k != "confirmed")],
        ["confirmer: compiler_bug (of gate-confirmed rows)",
         s["confirm_gated"].get("compiler_bug", 0),
         ", ".join(f"{k} {n}" for k, n in s["confirm_gated"].most_common()
                   if k != "compiler_bug")],
    ])
    L += ["", "### Filtered tests by primary reason", ""]
    L += _md_table(["reason", "tests", "with this reason at all"], [
        [REASON_TEXT.get(k, k), n, s["filtered_all"].get(k, 0)]
        for k, n in s["filtered"].most_common()])
    L += ["", "Not reasons: the AOMP smoke-fails suite and upstream "
          "XFAIL/UNSUPPORTED on AMD or NVIDIA are kept and flagged.", ""]
    # --- per toolchain and mode
    L += ["## Per compiler and mode", "",
          "Outcome classes of the non-holdout cells "
          "(offload.engine.gate.outcome_class); "
          "`ok` correct on the device; gate verdicts of the failing rows "
          "(c confirmed, nd nondeterministic, env environment, nr not "
          "reproduced, u unchecked).", ""]
    rows_ = []
    vby = defaultdict(Counter)
    for c, v in s["ver"].items():
        it = v["item"]
        if pm.get(c.split("|")[1], {}).get("holdout", True):
            continue
        vby[(it["toolchain"], int(it["xnack"]))][v["verdict"]] += 1
    for (tc, x), cnt in sorted(s["per_cell"].items(), key=lambda k: (
            TC_ORDER.index(k[0][0]) if k[0][0] in TC_ORDER else 99,
            k[0][1])):
        fails = {k: n for k, n in cnt.items() if k in FAIL_CLASSES}
        vb = vby[(tc, x)]
        rows_.append([f"{tc} {_mode_label(tc, x)}", sum(cnt.values()),
                      cnt.get("correct_on_device", 0),
                      ", ".join(f"{k} {n}" for k, n in sorted(
                          fails.items(), key=lambda kv: -kv[1])),
                      cnt.get("harness_error", 0),
                      f"c {vb.get('confirmed', 0)}, nd "
                      f"{vb.get('nondeterministic', 0)}, env "
                      f"{vb.get('environment', 0)}, nr "
                      f"{vb.get('not_reproduced', 0)}, u "
                      f"{vb.get('unchecked', 0)}"])
    L += _md_table(["toolchain mode", "cells", "ok", "failing by class",
                    "harness errors", "gate"], rows_)
    # --- the headline: bug-fix tests still failing somewhere
    L += ["", "## Bug-fix tests still failing", "",
          "A program counts here when its test came with a bug fix (LLVM: "
          "the commit that added it fixes or names an issue, or its subject "
          "says fix, bug, crash, regression, wrong, miscompile or hang; "
          "AOMP: a ticket number in the test's name, an AOMP issue naming "
          "it, or an adding commit that reads as a fix) and at least one "
          "of its cells is a failure the gate confirmed on its own reruns. "
          "`passes on`: the families with a correct cell.", ""]
    head_rows = []
    for pid, cells in sorted(stat.items()):
        p = pm.get(pid)
        if not p or not p.get("bugfix"):
            continue
        conf_cells = {k: v for k, v in cells.items()
                      if v[0] in FAIL_CLASSES and v[1] == "confirmed"}
        if not conf_cells:
            continue
        if p["holdout"]:
            continue
        bf = p["bugfix"]
        head_rows.append([
            f"`{p['record']}`", f"{bf['kind']}"
            + (f" {', '.join(bf['refs'][:3])}" if bf.get("refs") else ""),
            "; ".join(f"{_short(k.split()[0])} {k.split()[1]} {c}"
                      for k, (c, _) in sorted(conf_cells.items())),
            ", ".join(sorted(_families_passing(cells))) or "none"])
    L += _md_table(["test", "bug fix", "confirmed failing cells",
                    "passes on"], head_rows)
    L += ["", "Holdout programs are neither named nor counted here (their "
          "outcomes are in the sealed outcomes.csv only).", ""]
    # --- every confirmed failure (non-holdout), per family
    L += ["## Confirmed failures by compiler family", "",
          "Failing cells the gate confirmed on their own reruns, non-holdout "
          "programs, grouped by program; the confirmer's verdict of the "
          "program's cells when it ran (compiler_bug, unsupported, ...).",
          ""]
    cv = defaultdict(Counter)
    for c in s["conf"]:
        cv[c["program"]][c["verdict"]] += 1
    for fam in ("afar", "cce", "nvhpc"):
        rows_ = []
        for pid, cells in sorted(stat.items()):
            p = pm.get(pid)
            if not p or p["holdout"]:
                continue
            cc = {k: v for k, v in cells.items()
                  if v[0] in FAIL_CLASSES and v[1] == "confirmed" and
                  family_of(k.split()[0]) == fam}
            if not cc:
                continue
            rows_.append([f"`{p['record']}`", ", ".join(sorted(
                {v[0] for v in cc.values()})), " ".join(sorted(
                    _short(k.split()[0]) + "/" + k.split()[1] for k in cc)),
                ", ".join(sorted(_families_passing(cells) - {fam})) or "-",
                ", ".join(f"{k} {n}" for k, n in cv[pid].most_common())])
        L += [f"### {fam} ({len(rows_)} programs)", ""]
        L += _md_table(["test", "classes", "cells", "other families "
                        "passing", "confirmer"], rows_) + [""]
    # --- the gate's unreached rows
    unchecked = [v["item"] for v in s["ver"].values()
                 if v["verdict"] == "unchecked"]
    L += ["## Rows the gate did not reach", "",
          f"{len(unchecked)} failing rows have no rerun of their own "
          "(`unchecked`)." + ("" if not unchecked else " They are listed "
                              "in results/harvest/main/unchecked.tsv."), ""]
    # --- the pre-run check
    pre = s["pre"]
    secs = sorted(r.get("seconds", 0) for r in pre.values()
                  if "seconds" in r)
    fo = sorted(pid for pid, r in pre.items() if r["kind"] == "frontend_only"
                and not pm.get(pid, {}).get("holdout"))
    L += ["## The pre-run check", "",
          "Two witnesses (offload.engine.prerun.check): the rules (grammar, "
          "restrictions, race rule) and the AFAR front end. Refused by kind: "
          + ", ".join(f"{k} {n}" for k, n in s["prerun_refused"].most_common())
          + ".", ""]
    if secs:
        L += [f"Per-check time (final verdicts with a timing): median "
              f"{secs[len(secs) // 2]:.1f} s, 90th percentile "
              f"{secs[int(len(secs) * 0.9)]:.1f} s, max {secs[-1]:.1f} s "
              f"over {len(secs)} checks.", ""]
    if fo:
        L += ["Candidate AFAR front-end defects (the rules accept, only the "
              "front end refuses; non-holdout): " + ", ".join(
                  f"`{pm[x]['record']}`" for x in fo) + ".", ""]
    L += findings_section(s)
    L += budget_section()
    L += LIMITS
    return "\n".join(L) + "\n"


def findings_section(s: dict) -> list[str]:
    """What the confirmed failures became (catalog/harvest_findings.yaml)
    and the existing findings the confirmer linked rows to."""
    import yaml
    from collections import defaultdict
    d = yaml.safe_load((ROOT / "catalog" / "harvest_findings.yaml")
                       .read_text()) or {}
    L = ["## Findings", ""]
    new = d.get("new") or []
    L += [f"New ({len(new)}, data/findings/harvest/):", ""]
    for f in new:
        L.append(f"- `{f['file']}`: upstream "
                 f"{', '.join(f.get('upstream') or []) or 'none'}"
                 + (f"; {f['note']}" if f.get("note") else ""))
    hand = d.get("linked") or []
    L += ["", f"Existing findings the harvested tests reproduce, linked by "
          f"hand ({len(hand)}):", ""]
    for f in hand:
        L.append(f"- `{f['finding']}` (upstream "
                 f"{', '.join(f.get('upstream', []))}): {f.get('note', '')}")
    progs = defaultdict(set)
    for c in s["conf"]:
        if c.get("gate") != "confirmed":
            continue
        for f in c.get("findings") or []:
            if not c.get("holdout"):
                progs[f].add(c["program"])
    L += ["", f"Linked by the confirmer ({len(progs)} existing findings; "
          "gate-confirmed rows whose signature an index entry matches):", ""]
    for f, ps in sorted(progs.items()):
        L.append(f"- `{f}`: " + ", ".join(
            f"`{s['pmap'][p]['record']}`" for p in sorted(ps)))
    uns = d.get("unsupported") or []
    L += ["", f"Vendor-documented unsupported ({len(uns)}; recorded, not "
          "findings):", ""]
    for u in uns:
        L.append(f"- {u['what']} ({u['doc']})")
    cand = d.get("candidates") or []
    if cand:
        L += ["", f"Candidates, confirmed by the gate and not promoted "
              f"({len(cand)}):", ""]
        L += _md_table(["test", "families", "rules", "message",
                        "promotion needs"],
                       [[f"`{c['test']}`", ", ".join(c["families"]),
                         ", ".join(r.split("-")[0] for r in c["rules"]),
                         c["message"].replace("|", "/")[:120], c["missing"]]
                        for c in cand])
    return L + [""]


def budget_section() -> list[str]:
    """The GPU-hours the ledgers record, by machine."""
    from collections import defaultdict
    tot = defaultdict(float)
    for f in sorted(OUT.glob("ledger*.jsonl")):
        for r in _jl(f):
            tot[r.get("machine", "?")] += float(r.get("gpu_h") or 0)
    return ["## GPU-hours", "",
            "Allocated GPU-hours (nodes x 4 x wall hours; wingtip: GPUs held "
            "x wall hours), from results/harvest/ledger*.jsonl, failed and "
            "cancelled jobs included: " + ", ".join(
                f"{m} {h:.1f}" for m, h in sorted(tot.items()))
            + f"; total {sum(tot.values()):.1f}.", ""]


LIMITS = [
    "## Limits", "",
    "- C and Fortran only (ruling of 2026-10-26): 281 C++ tests are counted, "
    "not run.",
    "- A filtered test is not looked at again: an LLVM-only flag or "
    "environment variable can hide a portable bug behind it.",
    "- The harness compiles at -O2; the LLVM tests run at -O0 (or -O3 with "
    "`compileopt`) upstream.",
    "- Fortran expected output is compared as values (commas, record "
    "boundaries and r*c repeat counts are processor-dependent in "
    "list-directed output, F2018 13.10.4), so CHECK-NEXT and CHECK-SAME read "
    "as CHECK in Fortran.",
    "- Many upstream tests assume separate host and device memory; at "
    "HSA_XNACK=1 and under NVHPC managed memory a copy-dependent expectation "
    "may fail legitimately (the findings use copy mode). A dev program "
    "whose copy cell passes on some compiler while every unified and managed "
    "cell fails is copy-only (`catalog/harvest_copy_only.yaml`): its "
    "shared-mode rows are not run, gated, confirmed or counted here. A "
    "unified-memory defect shared by every compiler would look the same. The "
    "holdout is scored on copy cells only.",
    "- The confirmer trusts a run-time expected value only with a second "
    "independent source (elision, a derivation, metamorphic runs); for a "
    "harvested test the upstream CHECK lines are one source, so run-time "
    "failures end needs_human (R22) and are promoted by hand with the spec "
    "text. It also calls a device link failure a compiler bug (R10b) where "
    "the vendor documents the routine or construct as unsupported in "
    "offload regions (listed above as unsupported).",
    "- AOMP smoke tests without FileCheck have their exit status as the "
    "only oracle: a wrong value they do not check is invisible.",
    "- Multi-file tests (12) and fixed-form Fortran (4) are not converted.",
    "- History follows a test across the 2024 move to offload/ by its path, "
    "not across renames inside offload/test.",
    ""]


def _original(text: str) -> str:
    """A converted program's text before its self-check (the CHECK lines
    are the original's; the self-check's own strings are not)."""
    return text.split("===== self-check")[0]


def crosscheck(name: str) -> dict:
    """The in-program verdict against the reference matcher
    (offload.engine.harvest.checks.match) on the output the program echoed
    (its last run's HV| lines), for every filecheck row with a RESULT
    line: {agree, disagree: [(program, toolchain, mode key, verdict)],
    skipped}."""
    import re
    from offload.engine.harvest import checks as K
    progs = {p["id"]: p for p in load_programs()}
    out = {"agree": 0, "disagree": [], "skipped": 0}
    cache = {}
    for r in rows(name):
        p = progs.get(r["program_id"])
        if not p or p["oracle"] != "filecheck":
            continue
        txt = r.get("stdout") or ""
        m = re.findall(r"^RESULT ran_on_host=[01] check=(pass|fail)", txt,
                       re.M)
        blocks = txt.split("RESULT ran_on_host=")
        if not m or len(blocks) < 2:
            out["skipped"] += 1
            continue
        lines = [ln[4:] for ln in blocks[-2].splitlines()
                 if ln.startswith("HV| ")]
        if len(lines) >= 300 or any(len(ln) >= 200 for ln in lines) or \
                len(txt) >= 5900:
            # the echo is cut (300 lines, 200 characters a line) or the
            # stored output clipped: not the output the program read
            out["skipped"] += 1
            continue
        if p["id"] not in cache:
            src = _original((OUT / "src" / p["file"]).read_text())
            cache[p["id"]] = K.parse_checks(src, tuple(p["prefixes"]))
        ok, _ = K.match(cache[p["id"]], "\n".join(lines) + "\n",
                        "c" if p["lang"] == "c" else "f90")
        if ok == (m[-1] == "pass"):
            out["agree"] += 1
        else:
            out["disagree"].append((p["id"], r["toolchain"], r["xnack"],
                                    m[-1]))
    return out


def cmd_report(a) -> int:
    s = summary(a.name)
    (OUT / a.name).mkdir(parents=True, exist_ok=True)
    (OUT / a.name / "summary.json").write_text(json.dumps(
        {k: (dict((str(kk), vv) for kk, vv in v.items())
             if hasattr(v, "items") else v)
         for k, v in s.items() if k not in ("ver", "conf", "rows", "pmap",
                                            "pre", "filt", "per_cell")},
        indent=1, sort_keys=True, default=str))
    print(json.dumps({k: (dict((str(kk), vv) for kk, vv in v.items())
                          if hasattr(v, "items") else v)
                      for k, v in s.items() if k in (
                          "inventory_n", "kept_tests", "programs",
                          "holdout", "prerun_ok", "prerun_refused",
                          "prerun_missing", "cells", "failing_rows",
                          "harness_errors", "gate", "gate_own", "confirm",
                          "confirm_gated")}, indent=1, default=str))
    if a.write:
        REPORT.write_text(render(a.name))
        print("->", REPORT)
    return 0


def holdout_outcomes(name: str) -> list[list]:
    """outcomes.csv rows of the holdout: case, toolchain, mode (copy,
    unified, managed), outcome (the harness outcome class; ``refused`` for
    a program the pre-run check refused, ``not_applicable`` for a mode its
    expected result does not hold in), gate (the gate's verdict of a
    failing row, else empty)."""
    from offload.engine.toolchains import TOOLCHAINS
    by = {(r["program_id"], r["toolchain"], r["xnack"]): r
          for r in rows(name)}
    ver = verdicts(name)
    pre = prerun_rows()
    out = []
    for c in holdout_cases():
        for m in TARGETS.values():
            for t in m[0]:
                for x in m[1]:
                    if x not in TOOLCHAINS[t].xnack_modes:
                        continue
                    mode = "managed" if x == 2 else MODE_NAME[x]
                    if MODE_NAME[x] not in c["modes"] or \
                            not model_supported(c, t):
                        out.append([c["case"], t, mode, "not_applicable",
                                    ""])
                        continue
                    if not pre.get(c["id"], {}).get("ok"):
                        out.append([c["case"], t, mode, "refused", ""])
                        continue
                    r = by.get((c["id"], t, x))
                    if r is None:
                        out.append([c["case"], t, mode, "not_run", ""])
                        continue
                    v = ver.get(f"{KIND}|{c['id']}|{t}|{x}", {})
                    out.append([c["case"], t, mode, _cls(r),
                                v.get("verdict", "")])
    return out


def cmd_seal(a) -> int:
    """outcomes.csv and SEAL of data/bench/harvest-holdout (once)."""
    import csv
    sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]
    import fresh_bench as FB
    if (HOLDOUT / "SEAL").exists() and "outcomes_sha256" in \
            (HOLDOUT / "SEAL").read_text():
        # harvest2 sealed its case files at the split (no outcomes yet):
        # the outcomes complete that seal once
        print("sealed already")
        return 1
    allowed = set()
    for m in a.allow_missing_machine or []:
        if m not in TARGETS:
            raise SystemExit(f"unknown machine {m!r} (one of {sorted(TARGETS)})")
        allowed |= set(TARGETS[m][0])
    rows_ = holdout_outcomes(a.name)
    # A cell may be missing only on a machine named for
    # it (harvest2: Tioga, where the holdout was never copied)
    missing = [r for r in rows_ if r[3] == "not_run" and r[1] not in allowed]
    if missing:
        print(f"{len(missing)} holdout cells not run off "
              f"{sorted(a.allow_missing_machine or []) or 'any named machine'}: "
              "not sealed")
        return 2
    with open(HOLDOUT / "outcomes.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["case", "toolchain", "mode", "outcome", "gate"])
        w.writerows(rows_)
    paths = sorted(p for p in HOLDOUT.rglob(f"{CASE_PREFIX}*")
                   if p.suffix in (".c", ".f90"))
    text = FB.seal_text(a.commit, paths, HOLDOUT / "cases.yaml",
                        HOLDOUT / "outcomes.csv")
    task = "49a" if SET == "harvest" else "49c"
    text = text.replace("# Task ? seal", f"# Task {task} seal", 1).replace(
        "(a sealed set)", "(the 30% holdout of the harvested tests)", 1)
    (HOLDOUT / "SEAL").write_text(text)
    print(text)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("inventory")
    p.add_argument("--no-issues", action="store_true")
    p.set_defaults(func=cmd_inventory)
    p = sub.add_parser("filter")
    p.set_defaults(func=cmd_filter)
    p = sub.add_parser("convert")
    p.set_defaults(func=cmd_convert)
    p = sub.add_parser("prerun")
    p.add_argument("--workers", type=int, default=32)
    p.add_argument("--retry-timeouts", action="store_true",
                   help="(kept for old scripts: timed-out checks are always "
                   "checked again)")
    p.add_argument("--shard")
    p.set_defaults(func=cmd_prerun)
    p = sub.add_parser("run")
    p.add_argument("--name", default="main")
    p.add_argument("--machine", choices=sorted(TARGETS), default="tuolumne")
    p.add_argument("--toolchains")
    p.add_argument("--modes")
    p.add_argument("--ids", help="program ids, comma separated")
    p.add_argument("--workers", type=int, default=16)
    p.add_argument("--timeout", type=int, default=RUN_TIMEOUT)
    p.add_argument("--limit-s", type=int, default=3000)
    p.add_argument("--shard")
    p.add_argument("--retry-errors", action="store_true")
    p.add_argument("--no-canaries", dest="canaries", action="store_false")
    p.set_defaults(func=cmd_run)
    p = sub.add_parser("confirm")
    p.add_argument("--name", default="main")
    p.add_argument("--only-confirmed", action="store_true")
    p.add_argument("--toolchains", help="judge only these toolchains' "
                   "rows (comma separated); the others stay evidence")
    p.set_defaults(func=cmd_confirm)
    p = sub.add_parser("report")
    p.add_argument("--name", default="main")
    p.add_argument("--write", action="store_true")
    p.set_defaults(func=cmd_report)
    p = sub.add_parser("seal")
    p.add_argument("--name", default="main")
    p.add_argument("--commit", required=True)
    p.add_argument("--allow-missing-machine", action="append",
                   help="a machine whose toolchains' cells may be not_run "
                   "(harvest2: tioga, by design); repeatable")
    p.set_defaults(func=cmd_seal)
    p = sub.add_parser("candidates")
    p.add_argument("--name", default="main")
    p.set_defaults(func=cmd_candidates)
    p = sub.add_parser("copy-only")
    p.add_argument("--name", default="main")
    p.set_defaults(func=cmd_copy_only)
    p = sub.add_parser("holdout")
    p.set_defaults(func=cmd_holdout)
    p = sub.add_parser("gate")
    p.add_argument("--name", default="main")
    p.add_argument("--machine", choices=sorted(TARGETS), default="tuolumne")
    p.add_argument("--envs", default="a,b,c,d")
    p.add_argument("--c-other-node", action="store_true",
                   help="rerun (c) of the rows whose (c) shared (a)'s node, here, when here is not (a)'s node")
    p.add_argument("--alloc", help="the allocation's nodes, comma "
                   "separated (two-node jobs)")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--shard")
    p.add_argument("--root", help="the gate's build root (default: "
                   "offload.engine.gate.gate_tmp)")
    p.add_argument("--limit-s", type=int, default=3000)
    p.set_defaults(func=cmd_gate)
    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
