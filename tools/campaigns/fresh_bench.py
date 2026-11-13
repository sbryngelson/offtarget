#!/usr/bin/env python3
"""The fresh bug benchmark (data/bench/fresh/): a second in-the-wild set built like
data/bench/wild/ (same case format, same runners) from reports and in-source
workarounds that data/bench/wild does not contain. Nothing here runs the linter.

    python3 -I tools/campaigns/fresh_bench.py parse
    python3 -I tools/campaigns/fresh_bench.py legality          # -> results/fresh/legality.jsonl
    python3 -I tools/campaigns/fresh_bench.py run --toolchains afar cce19 [--modes ..] [--jobs N]
    python3 -I tools/campaigns/fresh_bench.py outcomes          # -> data/bench/fresh/outcomes.csv
    python3 -I tools/campaigns/fresh_bench.py summary           # -> data/bench/fresh/results.md
    python3 -I tools/campaigns/fresh_bench.py seal --commit C   # -> data/bench/fresh/SEAL
    python3 -I tools/campaigns/fresh_bench.py check-seal

Every command takes ``--bench DIR`` (default data/bench/fresh) and ``--out DIR``
(default results/<name of DIR>); ``--bench data/bench/fresh2`` builds the second set.
Cases are data/bench/fresh/fresh-NNN.<f90|c>; runs reuse tools/wild/wild_bench.py."""
from __future__ import annotations

import argparse
import contextlib
import csv
import dataclasses
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path[:0] = [str(ROOT / "tools" / a) for a in ("dataenv", "wild", "campaigns", "derive", "site", "repo", "lanes")] + [str(ROOT / "tools")]

FRESH = ROOT / "data" / "bench" / "fresh"
OUT = ROOT / "results" / "fresh"
# a case's OpenMP version for the version flags: 5.2 unless cases.yaml says
# ``omp_version: 60`` (read by version_60())
# compile failures the harness tables do not classify, read by hand from the
# compiler output: (case, toolchain) -> (outcome, reason)
HAND_CLASSIFIED: dict[tuple[str, str], tuple[str, str]] = {
    ("fresh-058", "nvhpc"): ("ice", "hand-read compiler output (NVHPC 25.11): "
                             "'nvfortran-Fatal-.../maintainers/fort2 TERMINATED by "
                             "signal 11'"),
    ("fresh-058", "nvhpc269"): ("ice", "hand-read compiler output (NVHPC 26.9):"
                                " 'nvfortran-Fatal-.../maintainers/fort2 TERMINATED "
                                "by signal 11'"),
    ("fresh-070", "nvhpc"):("ice", "hand-read compiler output (NVHPC 25.11): "
                             "'NVFORTRAN-S-0000-Internal compiler error. "
                             "flowgraph: node is zero' and 'NVFORTRAN-F-0000-"
                             "Internal compiler error. Invalid key for hash'"),
}

_KEYS = r"(fresh case|source|also|edits|expected|wild-opt|wild-opt-afar)"


# the task that built each sealed set (seal and summary text)
TASKS = {"fresh": ("38a", "the final unseen test of the linter", "38b"),
         "fresh2": ("40a", "the second sealed set, scored once in ",
                    "40e")}


def _task(name: str) -> tuple[str, str, str]:
    return TASKS.get(name, ("?", "a sealed set", "?"))


@contextlib.contextmanager
def use_bench(bench: Path | str | None = None, out: Path | str | None = None):
    """FRESH and OUT pointed at another set (``--bench``/``--out``) while
    the block runs, restored on exit. ``out`` defaults to
    results/<name of the bench directory>."""
    global FRESH, OUT
    saved = FRESH, OUT
    if bench is not None:
        FRESH = Path(bench).resolve()
        OUT = ROOT / "results" / FRESH.name
    if out is not None:
        OUT = Path(out).resolve()
    try:
        yield FRESH, OUT
    finally:
        FRESH, OUT = saved


def case_files(bench: Path | None = None) -> list[Path]:
    """The case files of a set: <name>-NNN.<f90|c>. The name is the prefix
    of the ids in the set's cases.yaml (fresh-* in data/bench/fresh, fresh2-* in
    data/bench/fresh2), so a copy of a set in a directory of another name keeps
    its case files; the directory's name when cases.yaml lists no case."""
    b = bench or FRESH
    name = b.name
    meta = b / "cases.yaml"
    if meta.is_file():
        import yaml
        d = yaml.safe_load(meta.read_text()) or {}
        cases = d.get("cases") if isinstance(d, dict) else d
        pre = {str(c["id"]).rsplit("-", 1)[0] for c in cases or ()
               if isinstance(c, dict) and c.get("id")}
        if len(pre) == 1:
            name = pre.pop()
    return sorted([*b.glob(f"{name}-*.f90"), *b.glob(f"{name}-*.c")])


def body_digest(path: Path) -> str:
    """sha256 of a reproducer without its header (the leading comment
    lines: wild case / fresh case, source, edits, ...) and with whitespace
    runs collapsed: the same program in two sets has the same digest."""
    lead = "//" if path.suffix == ".c" else "!"
    lines = path.read_text().splitlines()
    i = 0
    while i < len(lines) and lines[i].startswith(lead) and not (
            lines[i].startswith("!@file ") or lines[i].startswith("//@file ")):
        i += 1
    body = " ".join(" ".join(lines[i:]).split())
    return hashlib.sha256(body.encode()).hexdigest()


# --- overlap with other sets ----------------------------------
# body_digest only catches a program copied with its spelling; these catch a
# copy with renamed identifiers and a second report of the same defect.

_F_KW = frozenset("""
program end module contains subroutine function use implicit none integer real
double precision complex logical character type allocatable allocate deallocate
dimension intent in out inout parameter pointer target call do if then else
elseif endif enddo while select case return save data common optional present
associated nullify kind len public private interface procedure class extends
abstract print write read stop exit cycle where forall block associate value
result recursive pure elemental only sequence bind""".split())
_C_KW = frozenset("""
int long short float double char void unsigned signed const static extern
struct union typedef enum sizeof return if else for while do switch case break
continue default goto include define pragma restrict inline volatile auto
register main printf malloc free""".split())
_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d*)?(?:[eEdD][+-]?\d+)?"
                    r"(?:_\w+)?|\.\w+\.|\S")
# family groups: the AMD compilers are LLVM's
FAMILY_GROUP = {"llvm-clang": "llvm", "llvm-flang": "llvm", "amd-clang": "llvm",
                "amd-flang": "llvm", "amd-flang-classic": "llvm"}
PHASE_OF = {"reject": "compile", "ice": "compile", "link": "compile",
            "wrong": "offload", "crash": "offload", "hang": "offload"}
SHINGLE = 6            # tokens per shingle
COPY_JACCARD = 0.6     # a copy, whatever the reported family
FAMILY_JACCARD = 0.28  # a similar program of the same family group and phase
DEFECT_JACCARD = 0.5   # reported text or quoted diagnostic, same defect
_STOP = frozenset("the a an of in on is not and or to with for at by from as "
                  "this that be are was it its".split())


def program_tokens(path: Path) -> list[str]:
    """The program of a case file as a token stream: header and comments
    dropped, Fortran lower-cased, numbers N, strings S, identifiers ID
    (language keywords and every token of an OpenMP/OpenACC directive line
    kept), so that renaming variables does not change it."""
    c = path.suffix == ".c"
    lead = "//" if c else "!"
    lines = path.read_text(errors="replace").splitlines()
    i = 0
    while i < len(lines) and lines[i].startswith(lead) and \
            not lines[i].startswith(lead + "@file"):
        i += 1
    text = "\n".join(lines[i:])
    if c:
        text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    out: list[str] = []
    kw = _C_KW if c else _F_KW
    for ln in text.splitlines():
        s = ln.strip()
        if c:
            if s.startswith("//"):
                continue
            s = re.sub(r"//.*", "", s)
            directive = s.startswith("#pragma")
        else:
            low = s.lower()
            if low.startswith(("!$omp", "!$acc")):
                directive, s = True, s[1:]
            elif low.startswith("!"):
                continue
            else:
                directive, s = False, re.sub(r"!.*", "", s)
            s = s.lower()
        s = re.sub(r"\"[^\"]*\"|'[^']*'", " STR ", s)
        for t in _TOKEN.findall(s):
            if t == "STR":
                out.append("S")
            elif t[0].isdigit():
                out.append("N")
            elif re.match(r"[A-Za-z_]", t):
                out.append(t if directive or t.lower() in kw else "ID")
            else:
                out.append(t)
    return out


def program_similarity(a: list[str], b: list[str]) -> tuple[float, float]:
    """(Jaccard, containment) of the SHINGLE-token shingles of two token
    streams."""
    def sh(t):
        return {tuple(t[i:i + SHINGLE])
                for i in range(max(1, len(t) - SHINGLE + 1))}
    x, y = sh(a), sh(b)
    if not x or not y:
        return 0.0, 0.0
    n = len(x & y)
    return n / len(x | y), n / min(len(x), len(y))


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z_][a-z0-9_]+", text.lower())
            if w not in _STOP}


def _quoted(text: str) -> set[str]:
    q = re.findall(r'"([^"]{8,})"|\'([^\']{8,})\'|`([^`]{8,})`', text)
    return _words(" ".join(x for t in q for x in t if x))


def _jac(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _defect(c: dict) -> tuple:
    fam = FAMILY_GROUP.get(c.get("family"), c.get("family"))
    blame = {b.strip().lower() for b in str(c.get("blame") or "").split("|")
             if b.strip()}
    rep = str(c.get("reported") or "")
    return fam, PHASE_OF.get(c.get("failure")), blame, _words(rep), \
        _quoted(rep)


def overlaps(cases: list[dict], bench: Path,
             known: list[tuple[list[dict], Path]]) -> list[tuple]:
    """Cases of ``bench`` that another set already holds, as (id, other id,
    kind, score), kind one of
    * copy: the programs' token streams (identifiers canonical) have a
      shingle Jaccard of at least COPY_JACCARD, whatever the family;
    * similar_program: at least FAMILY_JACCARD, the same family group and
      the same phase (compile or offload);
    * same_defect: the same family group and phase, a blamed construct in
      common and the reported text, or its quoted diagnostic, with a word
      Jaccard of at least DEFECT_JACCARD.
    ``known`` is a list of (cases, directory) of the other sets."""
    toks: dict[Path, list[str]] = {}

    def tk(p):
        if p not in toks:
            toks[p] = program_tokens(p)
        return toks[p]
    hits = []
    for a in cases:
        pa = bench / a["file"]
        fa, ha, ba, wa, qa = _defect(a)
        for ks, kd in known:
            for b in ks:
                pb = kd / b["file"]
                fb, hb, bb, wb, qb = _defect(b)
                same = fa == fb and ha == hb and ha is not None
                if pa.suffix == pb.suffix and pa.is_file() and pb.is_file():
                    jac, _ = program_similarity(tk(pa), tk(pb))
                    if jac >= COPY_JACCARD:
                        hits.append((a["id"], b["id"], "copy", round(jac, 3)))
                    elif same and jac >= FAMILY_JACCARD:
                        hits.append((a["id"], b["id"], "similar_program",
                                     round(jac, 3)))
                if same and ba & bb:
                    d = max(_jac(wa, wb), _jac(qa, qb))
                    if d >= DEFECT_JACCARD:
                        hits.append((a["id"], b["id"], "same_defect",
                                     round(d, 3)))
    return hits


def header(path: Path) -> dict:
    """The header fields of a case file (its leading comment lines);
    ``wild case`` mirrors ``fresh case`` for tools/wild/wild_bench.py."""
    lead = "//" if path.suffix == ".c" else "!"
    out: dict = {"edits": []}
    in_edits = False
    for line in path.read_text().splitlines():
        if not line.startswith(lead) or line.startswith("!@file ") or \
                line.startswith("//@file "):
            break
        body = line[len(lead):].strip()
        m = re.match(_KEYS + r":\s*(.*)$", body)
        if m:
            key, val = m.group(1), m.group(2)
            in_edits = key == "edits"
            if key == "also":
                out.setdefault("also", []).append(val)
            elif key != "edits":
                out[key] = val
            elif val:
                out["edits"].append(val)
        elif in_edits and body:
            out["edits"].append(body)
    if "fresh case" in out:
        out["wild case"] = out["fresh case"]
    return out


def version_60(meta_path: Path | None = None) -> set[str]:
    """Ids of the cases that need the OpenMP 6.0 version flags
    (``omp_version: 60`` in cases.yaml)."""
    import yaml
    p = meta_path or FRESH / "cases.yaml"
    if not p.is_file():
        return set()
    return {c["id"] for c in yaml.safe_load(p.read_text())["cases"]
            if str(c.get("omp_version", "")) == "60"}


# toolchain/program combinations a compiler does not offer (the
# offload.engine.toolchains flag error): a cell of no outcome, as AFAR OpenACC
NO_SUPPORT = ("CCE supports OpenACC for Fortran only",
              "AFAR (amdflang) does not support OpenACC")


def _not_applicable(path: Path, toolchain: str, mode: str, why: str,
                    model: str) -> dict:
    return {"id": path.stem, "toolchain": toolchain, "mode": mode,
            "model": model, "outcome": "not_applicable", "reason": why,
            "runs": []}


def guarded_run_cell(orig):
    """wild_bench.run_cell, with a combination the toolchain does not
    support (a ValueError naming it, raised while building the flags)
    recorded as not_applicable instead of stopping the whole run."""
    def run_cell(path: Path, toolchain: str, mode: str) -> dict:
        try:
            return orig(path, toolchain, mode)
        except ValueError as e:
            if any(w in str(e) for w in NO_SUPPORT):
                import wild_bench as WB
                return _not_applicable(path, toolchain, mode, str(e),
                                       WB.model_of(path))
            raise
    return run_cell


@contextlib.contextmanager
def remote_roots(roots: dict[str, str], local: tuple[str, ...] = (),
                 prefixes: dict[str, str] | None = None,
                 envs: dict[str, dict[str, str]] | None = None):
    """offload.engine.confirm.machines.load with the ssh working copy of some
    machines replaced (``--root wingtip=/path``): the fresh runs use their
    own remote clone, which never holds the case files (the RemoteRunner
    sends each program on stdin). Machines in ``local`` (``--local tioga``,
    a batch job on that machine itself) run with the LocalRunner.
    ``prefixes`` replaces a machine's run_prefix (``--prefix
    wingtip='tools/jobs/wingtip_capped.sh nice -n 10'``: the capped slice) and
    ``envs`` adds to its exec environment (``--env
    wingtip:CUDA_VISIBLE_DEVICES=1``)."""
    from offload.engine.confirm import machines as M
    orig = M.load
    prefixes, envs = prefixes or {}, envs or {}

    def load(*a, **kw):
        ms = orig(*a, **kw)
        for name in set(roots) | set(prefixes) | set(envs):
            m = ms[name]
            acc = dict(m.access)
            if name in roots:
                acc["root"] = roots[name]
            if name in prefixes:
                acc["run_prefix"] = prefixes[name]
            if name in envs:
                acc["env"] = {**(acc.get("env") or {}), **envs[name]}
            ms[name] = dataclasses.replace(m, access=acc)
        for name in local:
            ms[name] = dataclasses.replace(ms[name], access="local")
        return ms
    M.load = load
    try:
        yield
    finally:
        M.load = orig


@contextlib.contextmanager
def fresh():
    """tools/wild/wild_bench.py with its paths, header reader and per-case tables
    pointed at the fresh set, restored on exit."""
    import wild_bench as WB
    saved = {k: getattr(WB, k) for k in
             ("BENCH", "OUT", "header", "case_files", "VERSION_60",
              "HAND_CLASSIFIED", "run_cell")}
    WB.BENCH, WB.OUT, WB.header = FRESH, OUT, header
    bench = FRESH
    WB.case_files = lambda: case_files(bench)
    WB.VERSION_60, WB.HAND_CLASSIFIED = version_60(), HAND_CLASSIFIED
    WB.run_cell = guarded_run_cell(saved["run_cell"])
    try:
        yield WB
    finally:
        for k, v in saved.items():
            setattr(WB, k, v)


def _kv(items) -> dict[str, dict[str, str]]:
    """``MACHINE:KEY=VALUE`` items -> {machine: {key: value}}."""
    out: dict[str, dict[str, str]] = {}
    for it in items or ():
        mach, kv = it.split(":", 1)
        k, v = kv.split("=", 1)
        out.setdefault(mach, {})[k] = v
    return out


def _remote(a):
    """remote_roots from a run/rerun/confirm command's options."""
    return remote_roots(dict(x.split("=", 1) for x in a.root),
                        tuple(getattr(a, "local", ()) or ()),
                        dict(x.split("=", 1) for x in a.prefix),
                        _kv(a.env))


def parse_ok(path: Path) -> bool:
    import wild_bench as WB
    return WB.parse_one(path)[0]


# --- outcome table -------------------------------------------------------------------

def outcome_rows(runs: Path, ids=None) -> list[tuple[str, str, str, str]]:
    """(case, toolchain, mode, outcome) per cell of results/fresh/runs/*.jsonl;
    a later line for the same cell (a rerun) replaces an earlier one. With
    ``ids``, only the cells of those cases (a case removed from the set
    keeps its run records but leaves the table)."""
    cells: dict[tuple[str, str, str], str] = {}
    for f in sorted(runs.glob("*.jsonl")):
        for ln in f.read_text().splitlines():
            if not ln.strip():
                continue
            r = json.loads(ln)
            if ids is not None and r["id"] not in ids:
                continue
            cells[(r["id"], r["toolchain"], r["mode"])] = reclassify(r)[0]
    return sorted((k[0], k[1], k[2], v) for k, v in cells.items())


def reclassify(r: dict) -> tuple[str, str]:
    """(outcome, reason) of a run record: an unclassified compile failure
    read by hand (HAND_CLASSIFIED) gets its hand class; a remote harness
    error that is a toolchain's unsupported combination is not_applicable."""
    if r["outcome"] == "harness_error" and \
            any(w in str(r.get("reason", "")) for w in NO_SUPPORT):
        return "not_applicable", next(w for w in NO_SUPPORT
                                      if w in r["reason"])
    if r["outcome"] == "harness_error" and \
            str(r.get("reason", "")).startswith("unclassified_compile") and \
            (r["id"], r["toolchain"]) in HAND_CLASSIFIED:
        return HAND_CLASSIFIED[(r["id"], r["toolchain"])]
    return r["outcome"], r.get("reason", "")


def write_outcomes(rows, out: Path) -> Path:
    with out.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["case", "toolchain", "mode", "outcome"])
        w.writerows(rows)
    return out


# --- seal ------------------------------------------------------------------------------

def digest(paths) -> str:
    """sha256 over the case files sorted by name: name, NUL, bytes, NUL."""
    h = hashlib.sha256()
    for p in sorted(paths, key=lambda q: q.name):
        h.update(p.name.encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def seal_text(commit: str, paths, meta: Path,
              outcomes: Path | None = None) -> str:
    """The SEAL of the set whose cases.yaml is ``meta`` (its directory's
    name gives the task and the case file pattern). With ``outcomes``
, the seal covers the ground truth too:
    ``outcomes_sha256`` of outcomes.csv, beside ``cases_yaml_sha256``."""
    paths = list(paths)
    name = meta.parent.name
    task, what, _ = _task(name)
    text = (
        f"# Task {task} seal of bench/{name} ({what})\n"
        f"commit: {commit}\n"
        f"cases: {len(paths)}\n"
        # the sealed text names the tool by its original path (tools/): the committed SEAL files say so
        f"method: sha256 over the case files ({name}-*.f90, {name}-*.c) sorted "
        "by name, each as name, NUL, bytes, NUL (tools/fresh_bench.py digest)\n"
        f"sha256: {digest(paths)}\n"
        f"cases_yaml_sha256: {hashlib.sha256(meta.read_bytes()).hexdigest()}\n")
    if outcomes is not None:
        text += ("outcomes_sha256: "
                 f"{hashlib.sha256(outcomes.read_bytes()).hexdigest()}\n")
    return text


def read_seal(path: Path) -> dict:
    d = {}
    for ln in path.read_text().splitlines():
        m = re.match(r"(commit|cases|sha256|cases_yaml_sha256|outcomes_sha256)"
                     r":\s*(\S+)", ln)
        if m:
            d[m.group(1)] = int(m.group(2)) if m.group(1) == "cases" \
                else m.group(2)
    return d


def check_seal(seal: Path, paths, meta: Path,
               outcomes: Path | None = None) -> list[str]:
    """What differs from the seal: the case files, cases.yaml and, when the
    seal records it, outcomes.csv."""
    s = read_seal(seal)
    paths = list(paths)
    errs = []
    if s.get("cases") != len(paths):
        errs.append(f"cases: sealed {s.get('cases')}, now {len(paths)}")
    if s.get("sha256") != digest(paths):
        errs.append("sha256 of the case files differs from the seal")
    if s.get("cases_yaml_sha256") != \
            hashlib.sha256(meta.read_bytes()).hexdigest():
        errs.append("sha256 of cases.yaml differs from the seal")
    if "outcomes_sha256" in s:
        if outcomes is None or not outcomes.is_file():
            errs.append("outcomes.csv is sealed but missing")
        elif s["outcomes_sha256"] != \
                hashlib.sha256(outcomes.read_bytes()).hexdigest():
            errs.append("sha256 of outcomes.csv differs from the seal")
    return errs


# --- summary ----------------------------------------------------------------------------

def summary(meta: dict, rows, legality: dict[str, str]) -> str:
    """Counts only (no case ids, contents or URLs): by project, family,
    model, language, legality, and outcome per toolchain and mode."""
    cases = meta["cases"]
    name = FRESH.name
    lines = [f"# data/bench/{name}: ground-truth summary (Task {_task(name)[0]})",
             "", f"{len(cases)} cases, {len(meta['excluded'])} reports "
             f"excluded. Counts only; the set is sealed (data/bench/{name}/SEAL).",
             ""]
    keys = ("project", "family", "model", "lang", "source_kind")
    if any("phase" in c for c in cases):
        keys += ("phase", "failure")
    for key in keys:
        c = Counter(x.get(key, "?") for x in cases)
        lines += [f"## By {key}", "", "| value | cases |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in sorted(c.items())]
        lines.append("")
    if legality:
        c = Counter(legality.get(x["id"], "not run") for x in cases)
        lines += ["## Legality (gate + hand decisions)", "",
                  "| legality | cases |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in sorted(c.items())]
        lines.append("")
    if rows:
        outs = sorted({r[3] for r in rows})
        cols = sorted({(r[1], r[2]) for r in rows})
        tab = Counter((r[1], r[2], r[3]) for r in rows)
        lines += ["## Outcomes per toolchain and mode (cells)", "",
                  "| toolchain | mode | " + " | ".join(outs) + " |",
                  "|---|---|" + "---|" * len(outs)]
        for tc, mode in cols:
            lines.append(f"| {tc} | {mode} | " + " | ".join(
                str(tab.get((tc, mode, o), 0)) for o in outs) + " |")
        lines.append("")
    return "\n".join(lines)


def legality_of(meta: dict, gate: Path) -> dict[str, str]:
    """Final legality per case: a hand decision in cases.yaml
    (``legality: {status: ..., basis: ...}``, as data/bench/wild) overrides the gate's status."""
    out = {}
    if gate.is_file():
        for ln in gate.read_text().splitlines():
            if ln.strip():
                r = json.loads(ln)
                out[r["id"]] = r.get("status", "unknown")
    for c in meta["cases"]:
        hand = c.get("legality")
        if isinstance(hand, dict) and hand.get("status"):
            out[c["id"]] = hand["status"]
    return out


def rerun(ids: list[str], toolchains: list[str], modes: list[str] | None,
          jobs: int) -> None:
    """Run the given cases again and append the records (a case file fixed
    after its first run); outcome_rows keeps the later record of a cell."""
    import wild_bench as WB
    from concurrent.futures import ThreadPoolExecutor
    from offload.engine.confirm import machines as M
    from offload.engine.toolchains import TOOLCHAINS
    paths = [p for p in case_files() if p.stem in set(ids)]
    for tcn in toolchains:
        machine = M.load()[TOOLCHAINS[tcn].machine]
        for mode in modes or list(machine.modes):
            if mode not in machine.modes:
                continue
            out = OUT / "runs" / f"{tcn}.{mode}.jsonl"
            with ThreadPoolExecutor(max_workers=jobs) as ex, \
                    out.open("a") as fh:
                for rec in ex.map(lambda p: WB.run_cell(p, tcn, mode), paths):
                    rec["rerun"] = True
                    fh.write(json.dumps(rec) + "\n")
                    fh.flush()
                    print(f"  {rec['id']} {tcn} {mode}: {rec['outcome']}",
                          flush=True)


FAIL_OK = ("correct_on_device", "unobservable", "not_applicable")


def confirm_candidates(rows, legality: dict[str, str],
                       reasons: dict[tuple[str, str, str], str]) -> list[dict]:
    """Failing cells of legal cases that are worth the confirmer: one per
    (case, compiler family), its first failing cell in (toolchain, mode)
    order, a not-implemented rejection left out. No linter is
    involved: whether a finding already covers the defect is the
    confirmer's own deduplication."""
    from offload.engine.confirm.machines import family_of
    seen, out = set(), []
    for cid, tc, mode, oc in sorted(rows):
        if legality.get(cid) != "legal" or oc in FAIL_OK:
            continue
        why = reasons.get((cid, tc, mode), "")
        if why.startswith("not_implemented"):
            continue
        fam = family_of(tc)
        if (cid, fam) in seen:
            continue
        seen.add((cid, fam))
        out.append({"id": cid, "toolchain": tc, "mode": mode, "family": fam,
                    "outcome": oc, "reason": why})
    return out


def run_confirm(cands: list[dict], jobs: int = 1,
                roots: dict[str, str] | None = None,
                prefixes: dict[str, str] | None = None,
                envs: dict[str, dict[str, str]] | None = None) -> None:
    """tools/confirm.py case --run --draft per candidate; the JSON result
    to results/fresh/confirm/ and each new draft directory renamed
    results/confirm/drafts/fresh-<name> (never promoted)."""
    import subprocess
    from concurrent.futures import ThreadPoolExecutor
    from offload.engine.confirm.draft import DRAFTS
    od = OUT / "confirm"
    od.mkdir(parents=True, exist_ok=True)
    byid = {p.stem: p for p in case_files()}
    v60 = version_60()

    def one(c):
        dst = od / f"{c['id']}.{c['toolchain']}.{c['mode']}.json"
        if dst.exists():
            return c["id"], "done before"
        p = byid[c["id"]]
        # the confirmer, with the same remote working copies as the runs
        launch = ("import runpy, sys; sys.path.insert(0, %r); "
                  "sys.path.insert(0, %r); import fresh_bench as FB; "
                  "sys.argv = sys.argv[1:]; "
                  "ctx = FB.remote_roots(%r, (), %r, %r); ctx.__enter__(); "
                  "runpy.run_path(sys.argv[0], run_name='__main__')"
                  % (str(ROOT), str(ROOT / "tools"), dict(roots or {}),
                     dict(prefixes or {}), dict(envs or {})))
        cmd = [sys.executable, "-I", "-c", launch,
               str(ROOT / "tools" / "confirm.py"), "case", str(p), "--toolchain", c["toolchain"], "--mode",
               c["mode"], "--version", "60" if c["id"] in v60 else
               ("34" if header_model(p) == "acc" else "52"),
               "--outcome", c["outcome"], "--reason", c["reason"][:200],
               "--run", "--draft"]
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           timeout=5400)
        text = r.stdout
        try:
            res = json.loads(text[text.index("{"):])
        except ValueError:
            res = {"error": (r.stderr or text)[-800:]}
        renamed = []
        for d in res.get("drafts", []) or []:
            src = Path(d)
            prefix = FRESH.name + "-"
            if src.is_dir() and not src.name.startswith(prefix):
                new = DRAFTS / (prefix + src.name)
                if new.exists():
                    import shutil
                    shutil.rmtree(new)
                src.rename(new)
                renamed.append(str(new))
        res["drafts_renamed"] = renamed
        dst.write_text(json.dumps(res, indent=1))
        return c["id"], f"{res.get('verdict')} {res.get('rule')}"

    with ThreadPoolExecutor(max_workers=jobs) as ex:
        for cid, msg in ex.map(one, cands):
            print(cid, msg, flush=True)


def header_model(path: Path) -> str:
    import wild_bench as WB
    return WB.model_of(path)


def build_parser() -> argparse.ArgumentParser:
    """The command line; every subcommand takes --bench and --out."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sp = ap.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--bench", help="the set's directory "
                        "(default data/bench/fresh)")
    common.add_argument("--out", help="its results directory (default "
                        "results/<name of --bench>)")

    def add(name: str) -> argparse.ArgumentParser:
        return sp.add_parser(name, parents=[common])

    add("parse")
    add("legality")
    r = add("run")
    r.add_argument("--toolchains", nargs="+", required=True)
    r.add_argument("--modes", nargs="+")
    r.add_argument("--jobs", type=int, default=4)
    r.add_argument("--only", nargs="+")
    r.add_argument("--root", nargs="*", default=[],
                   help="MACHINE=PATH: run in another remote working copy")
    r.add_argument("--local", nargs="*", default=[],
                   help="MACHINE: run its toolchains here (a batch job on it)")
    for x in (r,):
        x.add_argument("--prefix", nargs="*", default=[],
                       help="MACHINE=STR: its run_prefix (the capped slice)")
        x.add_argument("--env", nargs="*", default=[],
                       help="MACHINE:KEY=VALUE: added to its exec env")
    rr = add("rerun")
    rr.add_argument("--ids", nargs="+", required=True)
    rr.add_argument("--toolchains", nargs="+", required=True)
    rr.add_argument("--modes", nargs="+")
    rr.add_argument("--jobs", type=int, default=2)
    rr.add_argument("--root", nargs="*", default=[])
    rr.add_argument("--local", nargs="*", default=[])
    for x in (rr,):
        x.add_argument("--prefix", nargs="*", default=[])
        x.add_argument("--env", nargs="*", default=[])
    cf = add("confirm")
    cf.add_argument("--families", nargs="+", required=True)
    cf.add_argument("--jobs", type=int, default=1)
    cf.add_argument("--list", action="store_true")
    cf.add_argument("--root", nargs="*", default=[])
    cf.add_argument("--prefix", nargs="*", default=[])
    cf.add_argument("--env", nargs="*", default=[])
    add("outcomes")
    add("summary")
    s = add("seal")
    s.add_argument("--commit", required=True)
    add("check-seal")
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    with use_bench(a.bench, a.out):
        return _main(a)


def _main(a) -> int:
    name = FRESH.name
    rel = f"data/bench/{name}"
    import yaml
    with fresh() as WB:
        if a.cmd == "parse":
            bad = 0
            for p in case_files():
                ok, err = WB.parse_one(p)
                if not ok:
                    bad += 1
                    print(f"{p.name}: parse failed")
            print(f"{len(case_files()) - bad} of {len(case_files())} parse")
            return 1 if bad else 0
        if a.cmd == "legality":
            WB.legality(OUT / "legality.jsonl")
        elif a.cmd == "run":
            with _remote(a):
                WB.run(a.toolchains, a.modes, a.jobs, a.only)
        elif a.cmd == "rerun":
            with _remote(a):
                rerun(a.ids, a.toolchains, a.modes, a.jobs)
        elif a.cmd == "confirm":
            meta = yaml.safe_load((FRESH / "cases.yaml").read_text())
            leg = legality_of(meta, OUT / "legality.jsonl")
            reasons = {}
            for f in sorted((OUT / "runs").glob("*.jsonl")):
                for ln in f.read_text().splitlines():
                    if ln.strip():
                        r = json.loads(ln)
                        reasons[(r["id"], r["toolchain"], r["mode"])] = \
                            reclassify(r)[1]
            ids = {p.stem for p in case_files()}
            cands = [c for c in confirm_candidates(
                outcome_rows(OUT / "runs", ids), leg, reasons)
                if c["family"] in a.families]
            if a.list:
                for c in cands:
                    print(c["id"], c["toolchain"], c["mode"], c["outcome"])
                print(len(cands), "candidates")
            else:
                run_confirm(cands, a.jobs,
                            dict(x.split("=", 1) for x in a.root),
                            dict(x.split("=", 1) for x in a.prefix),
                            _kv(a.env))
        elif a.cmd == "outcomes":
            rows = outcome_rows(OUT / "runs", {p.stem for p in case_files()})
            write_outcomes(rows, FRESH / "outcomes.csv")
            print(f"{len(rows)} cells -> {rel}/outcomes.csv")
        elif a.cmd == "summary":
            meta = yaml.safe_load((FRESH / "cases.yaml").read_text())
            rows = outcome_rows(OUT / "runs", {p.stem for p in case_files()}) \
                if (OUT / "runs").is_dir() else []
            text = summary(meta, rows,
                           legality_of(meta, OUT / "legality.jsonl"))
            (FRESH / "results.md").write_text(text + "\n")
            print(f"{rel}/results.md")
        elif a.cmd == "seal":
            oc = FRESH / "outcomes.csv"
            (FRESH / "SEAL").write_text(seal_text(
                a.commit, case_files(), FRESH / "cases.yaml",
                oc if oc.is_file() else None))
            print(f"{rel}/SEAL")
        elif a.cmd == "check-seal":
            errs = check_seal(FRESH / "SEAL", case_files(),
                              FRESH / "cases.yaml", FRESH / "outcomes.csv")
            for e in errs:
                print(e)
            print("seal ok" if not errs else "SEAL BROKEN")
            return 1 if errs else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
