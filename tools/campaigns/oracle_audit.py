"""Run the oracle mutation audit and write data/reports/oracle-audit.md.

Run from anywhere; the script puts the project root on sys.path itself.

    python3 -I tools/campaigns/oracle_audit.py --versions 52 60 \
        --toolchains afar cce19 --workers 8 --out results/oracle_audit.jsonl
    python3 -I tools/campaigns/oracle_audit.py --versions 50 --reuse 52 --merge
    python3 -I tools/campaigns/oracle_audit.py --model acc --workers 8
    python3 -I tools/campaigns/oracle_audit.py --lang c --workers 6

Each legal, observable program at an audited evidence level and its mutant
(offload.engine.mutate.neutralise) run on each toolchain in copy mode at -O2. The
JSONL has one MutantResult per program and toolchain; ``--report-only``
rebuilds the report from it. Only a full run writes the committed reports and
summaries; other runs write ``<out>.partial.md`` and ``.partial.summary.json``.
"""
import argparse
import dataclasses
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine.catalog import slice_atoms  # noqa: E402
from offload.engine.gen import generate  # noqa: E402
from offload.engine.run_matrix import version_flags  # noqa: E402
from offload.engine.mutate import (ACC_CONSTRUCT_CLAUSES,  # noqa: E402
                               ACC_RENAMES, DISPOSITIONS, KILL_KINDS,
                               NO_MUTATION, REPLACEMENTS,
                               SEMANTIC_MUTATIONS_ACC, STATUSES,
                               MutantResult, audit, audit_programs,
                               audit_summary, body_sha, summarise)

MD = ROOT / "data" / "reports" / "oracle-audit.md"
SUMMARY = ROOT / "tests" / "data" / "oracle_audit_summary.json"
# The OpenACC audit's committed report and summary, and its full
# run (version, toolchains)
ACC_MD = ROOT / "data" / "reports" / "acc-oracle-audit.md"
ACC_SUMMARY = ROOT / "tests" / "data" / "acc_audit_summary.json"
FULL = {"omp": ([50, 52, 60], ["afar", "cce19"]), "acc": ([34], ["cce19"]),
        "c": ([50, 52, 60], ["afar", "cce19"]),  # C 5.0
        # OpenACC C (offload.engine.acc_c_gen) runs on NVHPC only
        "accc": ([34], ["nvhpc"])}
# The C audit's committed report and summary
C_MD = ROOT / "data" / "reports" / "oracle-audit-c.md"
C_SUMMARY = ROOT / "tests" / "data" / "oracle_audit_summary_c.json"
LANG = ["f90"]  # the language of this run (main sets it)
MODEL = ["omp"]  # The model of this run (main sets it)
# The OpenACC C audit's report and summary (a full run: nvhpc,
# separate memory)
ACC_C_MD = ROOT / "data" / "reports" / "acc-oracle-audit-c.md"
ACC_C_SUMMARY = ROOT / "tests" / "data" / "acc_audit_summary_c.json"

FAMILIES = [
    ("map types and modifiers", lambda d, c: c == "map"),
    ("data constructs (target data/enter/exit/update, declare target, "
     "device pointers)",
     lambda d, c: d in ("target_data", "target_enter_data",
                        "target_exit_data", "target_update",
                        "declare_target")
     or c in ("to", "from", "use_device_ptr", "use_device_addr",
              "is_device_ptr", "has_device_addr", "enter", "link", "local",
              "device_type", "indirect")),
    ("async and dependencies",
     lambda d, c: c in ("nowait", "depend", "nogroup", "transparent",
                        "replayable")),
    ("loop and team parameters",
     lambda d, c: c in ("collapse", "num_teams", "thread_limit",
                        "num_threads", "dist_schedule", "schedule",
                        "ordered", "order", "bind", "simdlen", "safelen",
                        "linear", "induction", "aligned", "nontemporal",
                        "proc_bind")),
    ("device selection", lambda d, c: c in ("device", "if")),
    ("defaultmap and data-sharing",
     lambda d, c: c in ("defaultmap", "default", "private", "firstprivate",
                        "lastprivate", "shared", "copyin")),
    ("reductions", lambda d, c: c in ("reduction", "in_reduction")),
    ("compute directives", lambda d, c: d is not None),
    ("other (allocators, error directive clauses, requires)",
     lambda d, c: True),
]


ACC_FAMILIES = [
    ("data clauses and data constructs",
     lambda d, c: d in ("data", "enter_data", "exit_data", "update",
                        "host_data", "declare")
     or c in ("copy", "copyin", "copyout", "create", "present", "no_create",
              "delete", "finalize", "device", "host", "self", "if_present",
              "deviceptr", "use_device", "attach", "detach", "link",
              "device_resident", "default")),
    ("async, wait and runtime directives",
     lambda d, c: d in ("wait", "set", "init", "shutdown")
     or c in ("async", "wait", "default_async", "device_num")),
    ("loop scheduling", lambda d, c: c in (
        "collapse", "gang", "worker", "vector", "seq", "independent", "auto",
        "tile", "num_gangs", "num_workers", "vector_length", "device_type")),
    ("data-sharing and reductions",
     lambda d, c: c in ("private", "firstprivate", "reduction")),
    ("atomic, routine and cache",
     lambda d, c: d in ("atomic", "routine", "cache")
     or c in ("read", "write", "update", "capture", "bind", "nohost")),
    ("compute constructs", lambda d, c: d is not None),
    ("other", lambda d, c: True),
]


def family(atom: str) -> str:
    parts = atom.split(".")
    d = parts[2] if parts[1] == "directive" else None
    c = parts[2] if parts[1] == "clause" else None
    for name, test in (ACC_FAMILIES if parts[0] == "acc" else FAMILIES):
        if test(d, c):
            return name
    return FAMILIES[-1][0]


def read(path: Path) -> list[MutantResult]:
    return [MutantResult(**json.loads(line))
            for line in Path(path).read_text().splitlines() if line.strip()]


def write(results, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in results:
            f.write(json.dumps(dataclasses.asdict(r)) + "\n")


def meta_path(out: Path) -> Path:
    """The run's metadata next to the JSONL (full run or not, timing)."""
    return out.with_suffix(".meta.json")


def complete(results, versions, toolchains) -> list[int]:
    """The versions for which `results` hold a result of every audited
    program as generated now (same body) on every toolchain."""
    have = {(r.version, r.program_id, r.toolchain): r.body_sha
            for r in results}
    return [v for v in versions
            if all(have.get((v, p.id, t)) == body_sha(p.source)
                   for p in audit_programs(v, lang=LANG[0])
                   for t in toolchains)]


def reusable(version: int, source: int, toolchains, earlier,
             only=None) -> dict:
    """{primary atom: [the `source` version's results]} for the
    audited programs of `version` whose body equals the `source` program of
    the same atom, when `earlier` holds a result of that body on every
    toolchain."""
    src = {p.primary_atom: p for p in audit_programs(source)}
    have = {(r.version, r.primary_atom, r.toolchain): r for r in earlier}
    out = {}
    for p in audit_programs(version, only):
        q = src.get(p.primary_atom)
        if q is None or body_sha(q.source) != body_sha(p.source):
            continue
        rs = [have.get((source, p.primary_atom, t)) for t in toolchains]
        if all(r is not None and r.body_sha == body_sha(q.source)
               for r in rs):
            out[p.primary_atom] = [dataclasses.replace(
                r, program_id=p.id, version=version,
                reused_from=r.program_id) for r in rs]
    return out


def reuse_caveat(toolchains, versions, source: int, lang: str = "f90"
                 ) -> str:
    """What the reused results were compiled with: the `source` version's
    flags, which differ from the reusing version's for a toolchain with a
    version flag (AFAR: -fopenmp-version=50 at 5.0, its default at 5.2);
    equal source text does not make the compiler's version-gated checks
    equal, so such reused results are approximations. A toolchain without
    a version flag (CCE) gets exact copies."""
    differ, exact = [], []
    for t in toolchains:
        for v in versions:
            if v == source:
                continue
            mine = version_flags(t, v, lang) or "default"
            theirs = version_flags(t, source, lang) or "default"
            (exact if mine == theirs else differ).append((t, v, mine,
                                                          theirs))
    parts = [f"reused {t} results were compiled with the version {source} "
             f"flags ({theirs}), not {t} {v}'s {mine}: a kill or an "
             f"original's status that only {t} shows for a reused version "
             f"{v} program was not measured at version {v}"
             for t, v, mine, theirs in differ]
    names = sorted({t for t, *_ in exact})
    if names:
        parts.append(f"{', '.join(names)} "
                     f"{'has' if len(names) == 1 else 'have'} the same "
                     f"flags at both versions: reused results exact")
    return "; ".join(parts)


def settings_with_reuse(meta: dict, toolchains) -> str:
    """The run's settings line with `reuse_caveat` appended when the run
    reused results of another version (idempotent)."""
    settings = meta.get("settings", "")
    src = meta.get("reused_from")
    if not src or not meta.get("reused_programs"):
        return settings
    note = reuse_caveat(toolchains, meta.get("versions", []), src,
                        meta.get("lang", "f90"))
    if not note or note in settings:
        return settings
    return f"{settings} ({note})"


def write_summary(results, meta: dict, path: Path) -> dict:
    """tests/data/oracle_audit_summary.json: per version and atom of every
    legal program, the audit status and the disposition
    (offload.engine.mutate.audit_summary)."""
    versions = sorted({r.version for r in results} | set(meta.get(
        "versions", [])))
    if LANG[0] == "c" and MODEL[0] == "acc":
        from offload.engine.acc_c_gen import all_acc_c_programs

        def programs(v):
            return all_acc_c_programs()  
    elif LANG[0] == "c":
        from offload.engine.c_gen import all_c_programs

        def programs(v):
            return all_c_programs(v)
    else:
        def programs(v):
            return list(generate(slice_atoms(v), v))
    doc = {"generated_by": "tools/campaigns/oracle_audit.py (Tasks 9c, 12, 15"
           + (", 20: C" if LANG[0] == "c" else "") + ")",
           "run": meta, "dispositions": DISPOSITIONS,
           "versions": {str(v): audit_summary(results, programs(v), v)
                        for v in versions}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    return doc


def _cell(text: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", text).replace("|", "\\|")
    return text if len(text) <= limit else text[:limit - 3] + "..."


def render(results: list[MutantResult], meta: dict,
           summary: dict | None = None, model: str = "omp") -> str:
    versions = sorted({r.version for r in results})
    families = ACC_FAMILIES if model == "acc" else FAMILIES
    tcs = sorted({r.toolchain for r in results})
    out = ["# Oracle mutation audit"
           + (" (OpenACC 3.4)" if model == "acc" else "")
           + (" (C)" if LANG[0] == "c" else ""), "",
           "Generated by `tools/campaigns/oracle_audit.py`; do not "
           "edit. "
           "Each legal, observable program with an audited evidence level "
           "(`construct`, `copy_mode_only`, `probe`) "
           "is run as generated (the ORIGINAL) and with its primary atom "
           "removed (the MUTANT, `offload.engine.mutate.neutralise`: a directive "
           "commented out with its end, a clause deleted from every "
           "directive carrying it, a modifier deleted from its clause, a "
           "form whose deletion would leave a default that still does the "
           "same thing replaced by one without the behaviour (table at the "
           "end), conforming fallbacks where a removal would leave an "
           "illegal directive; the reporting variables' clauses are never "
           "touched; see the module docstring). A check that still passes "
           "without the construct is no evidence that the construct "
           "works.", "",
           f"Settings: {meta.get('settings', '')}", "",
           "Status per program and toolchain: **killed** (original "
           "`correct_on_device`, mutant `wrong_answer` or "
           "`fell_back_to_host`), **survived** (both `correct_on_device`), "
           "**inconclusive** (original not `correct_on_device`, mutant "
           "rejected by the compiler, a mutant timeout, the compiler saying "
           "it ignored something, or a harness error), **not_applicable** "
           "(no mutation, see below). Per atom: **valid** (killed on at "
           "least one toolchain), **weak** (survived on every toolchain "
           "where it was conclusive), **unknown** (no conclusive result).",
           "",
           "Kill kinds: `check_fail` (the run completed and the check "
           "failed), `fell_back_to_host` (the run reported ran_on_host=1), "
           "`crash` (signal, non-zero exit, no RESULT line). Only "
           "`check_fail` shows that the check itself depends on the "
           "construct; atoms valid only through the other kinds are "
           "marked.", "",
           "Programs that need zero-copy memory run under HSA_XNACK=1 "
           "(marked `xnack=1`): there host and device memory coincide, so "
           "a `survived` there proves nothing about data motion.", ""]

    out += ["## Counts by status", "",
            "| version | toolchain | " + " | ".join(STATUSES) + " | total |",
            "|---|---|" + "---|" * (len(STATUSES) + 1)]
    for v in versions:
        for tc in tcs:
            c = Counter(r.status for r in results
                        if r.version == v and r.toolchain == tc)
            out.append(f"| {v / 10:.1f} | {tc} | "
                       + " | ".join(str(c[s]) for s in STATUSES)
                       + f" | {sum(c.values())} |")
    out.append("")

    out += ["## Kill kinds", "",
            "| version | toolchain | " + " | ".join(KILL_KINDS) + " |",
            "|---|---|" + "---|" * len(KILL_KINDS)]
    for v in versions:
        for tc in tcs:
            c = Counter(r.kill_kind for r in results if r.version == v
                        and r.toolchain == tc and r.status == "killed")
            out.append(f"| {v / 10:.1f} | {tc} | "
                       + " | ".join(str(c[k]) for k in KILL_KINDS) + " |")
    out.append("")

    sums = {v: summarise([r for r in results if r.version == v])
            for v in versions}
    kinds = defaultdict(set)
    xnack1 = set()
    for r in results:
        if r.status == "killed":
            kinds[(r.version, r.primary_atom)].add(r.kill_kind)
        if r.xnack == 1:
            xnack1.add((r.version, r.primary_atom))
    out += ["## Atom verdicts (observable programs)", "",
            "| version | valid | weak | unknown | of which not_applicable "
            "| total |", "|---|---|---|---|---|---|"]
    for v in versions:
        c = Counter(s["status"] for s in sums[v].values())
        na = sum(1 for s in sums[v].values() if s["not_applicable"])
        out.append(f"| {v / 10:.1f} | {c['valid']} | {c['weak']} | "
                   f"{c['unknown']} | {na} | {len(sums[v])} |")
    out.append("")

    mutation = {(r.version, r.primary_atom):
                re.sub(r"^removed \S+ \((.*)\)$", r"\1", r.mutation)
                for r in results}
    hint = defaultdict(dict)
    for r in results:
        hint[(r.version, r.primary_atom)][r.toolchain] = r

    def mark(v, atom) -> str:
        return " (xnack=1)" if (v, atom) in xnack1 else ""

    def rows(status: str):
        fam = defaultdict(list)
        for v in versions:
            for atom, s in sums[v].items():
                if s["status"] == status:
                    fam[family(atom)].append((v, atom, s))
        return fam

    out += ["## Weak atoms (survivors), by family", "",
            "The mutant passed (`correct_on_device`) on every toolchain "
            "where the result was conclusive: these oracles do not tell the "
            "construct from its absence (repaired them or marked them "
            "unverified; gives those no run can separate a no-oracle "
            "category). Some are inherently unobservable in "
            "one run (`nowait`, scheduling and SIMD hints: an "
            "implementation may ignore them conformingly).", ""]
    weak = rows("weak")
    for name, _ in families:
        if not weak.get(name):
            continue
        out += [f"### {name}", "",
                "| version | atom | " + " | ".join(tcs) + " | removed |",
                "|---|---|" + "---|" * len(tcs) + "---|"]
        for v, atom, s in weak[name]:
            out.append(f"| {v / 10:.1f} | `{atom}`{mark(v, atom)} | "
                       + " | ".join(s["toolchains"].get(t, "-") for t in tcs)
                       + f" | {_cell(mutation.get((v, atom), ''), 160)} |")
        out.append("")

    out += ["## Valid atoms, by family", "",
            "With the kill kinds in brackets; **only via** marks an atom "
            "whose kills are all `fell_back_to_host` or `crash` (the check "
            "itself never failed).", ""]
    valid = rows("valid")
    weakly = []
    for name, _ in families:
        if valid.get(name):
            items = []
            for v, a, _ in valid[name]:
                k = sorted(kinds[(v, a)])
                only = "check_fail" not in k
                if only:
                    weakly.append((v, a, k))
                items.append(f"`{a}`{mark(v, a)} ({v / 10:.1f}) "
                             f"[{', '.join(k)}]"
                             + (" **only via**" if only else ""))
            out += [f"- **{name}**: " + ", ".join(items)]
    out.append("")
    out += ["### Valid only through fell_back_to_host or crash kills", "",
            "| version | atom | kinds | removed |", "|---|---|---|---|"]
    out += [f"| {v / 10:.1f} | `{a}`{mark(v, a)} | {', '.join(k)} | "
            f"{_cell(mutation.get((v, a), ''), 160)} |" for v, a, k in weakly]
    out.append("")

    groups = {"original": [], "mutant": [], "other": []}
    for v in versions:
        for atom, s in sums[v].items():
            if s["status"] != "unknown" or s["not_applicable"]:
                continue
            rs = list(hint[(v, atom)].values())
            if all(r.original != "correct_on_device" for r in rs):
                groups["original"].append((v, atom))
            elif any(r.original == "correct_on_device" and
                     r.reason.startswith("mutant_compile_failure")
                     for r in rs):
                groups["mutant"].append((v, atom))
            else:
                groups["other"].append((v, atom))
    titles = {
        "original": "Unknown: original rejected or not correct on any "
                    "toolchain",
        "mutant": "Unknown: mutant non-conforming (rejected where the "
                  "original passed; needs a better mutation)",
        "other": "Unknown: other (mutant timeout, harness error, ignored)"}
    out += ["## Unknown atoms", "",
            "No conclusive result on any toolchain, split by cause. The "
            "cells show original -> mutant: a mutant that is "
            "`correct_on_device` without the construct suggests a weak "
            "oracle even though the original could not be judged.", "",
            "| cause | count |", "|---|---|"]
    out += [f"| {titles[g]} | {len(groups[g])} |" for g in groups]
    out.append("")
    for g, items in groups.items():
        out += [f"### {titles[g]} ({len(items)})", "",
                "| version | atom | " + " | ".join(f"{t} (original -> "
                                                   "mutant)" for t in tcs)
                + " |", "|---|---|" + "---|" * len(tcs)]
        for v, atom in items:
            cells = []
            for t in tcs:
                r = hint[(v, atom)].get(t)
                cells.append(f"{r.original or '-'} -> {r.mutant or '-'}"
                             if r else "-")
            out.append(f"| {v / 10:.1f} | `{atom}`{mark(v, atom)} | "
                       + " | ".join(cells) + " |")
        out.append("")

    out += ["## Inconclusive results", "",
            "| version | program | toolchain | reason |", "|---|---|---|---|"]
    for r in results:
        if r.status == "inconclusive":
            x1 = " (xnack=1)" if r.xnack == 1 else ""
            out.append(f"| {r.version / 10:.1f} | `{r.program_id}`{x1} | "
                       f"{r.toolchain} | {_cell(r.reason)} |")
    out.append("")

    if model == "acc":
        out += ["## OpenACC mutations", "",
                "Directive atoms: the directive commented out with its end. "
                "Clause atoms: every instance deleted (a directive left "
                "without its required clause, or a declare without any, is "
                "commented out). Feature atoms: the feature's piece deleted, "
                "else the clause carrying it. Besides:", "",
                "| atom | mutation | why |", "|---|---|---|"]
        out += [f"| `{a}` | renamed to {new} | {_cell(why, 400)} |"
                for a, (new, why) in ACC_RENAMES.items()]
        out += [f"| `{a}` | the atomic construct commented out | an atomic "
                "construct without its clause is atomic update, which the "
                "statements do not fit |" for a in sorted(
                    ACC_CONSTRUCT_CLAUSES)]
        out += [f"| `{a}` | {cl} added to {d} | {_cell(why, 400)} |"
                for a, (d, cl, why) in SEMANTIC_MUTATIONS_ACC.items()]
        out.append("")
        out += map_mode_section(_map_doc(), "acc")
        if summary is not None:
            out += render_dispositions(summary)
        return "\n".join(out)
    out += ["## Atoms without a mutation (`NO_MUTATION`)", "",
            "| atom | reason |", "|---|---|"]
    out += [f"| `{a}` | {_cell(w, 400)} |" for a, w in NO_MUTATION.items()]
    out += ["", "## Replaced forms (`REPLACEMENTS`)", "",
            "Deleting these forms would leave a default that still does what "
            "the form does, so the form is replaced (per directive; `*` = "
            "any other) by one without the behaviour; `delete clause` "
            "deletes the clause carrying it, `keep` leaves it (no weaker "
            "form exists there).", "",
            "| atom | replacement | why |", "|---|---|---|"]
    for a, (rule, why) in REPLACEMENTS.items():
        rep = ", ".join(f"{d}: " + ("delete clause" if r is None else r)
                        for d, r in rule.items())
        out.append(f"| `{a}` | {rep} | {_cell(why, 400)} |")
    out.append("")
    out += map_mode_section(_map_doc(), LANG[0])
    if summary is not None:
        out += render_dispositions(summary)
    return "\n".join(out)


MAP_SUMMARY = ROOT / "tests" / "data" / "map_audit_summary.json"


def _map_doc() -> dict | None:
    return json.loads(MAP_SUMMARY.read_text()) if MAP_SUMMARY.is_file() \
        else None


def map_mode_section(doc: dict | None, group: str) -> list[str]:
    """The map-mutant audit's result for this report's group
    (tools/campaigns/map_audit.py, tests/data/map_audit_summary.json): per version
    the atoms whose map mutants are caught in both memory modes, at
    HSA_XNACK=0 only, at HSA_XNACK=1 only or in neither, and the atoms
    caught at HSA_XNACK=0 only (a valid oracle of the mapping in copy
    mode, blind to it under unified memory)."""
    out = ["## Map mutants by memory mode", "",
           "The map mutants of every audited program (weaken the map "
           "types, swap to and from, drop the map clauses, drop target "
           "update) run at HSA_XNACK=0 "
           "and at HSA_XNACK=1. Per atom: caught (killed on some toolchain) "
           "in both modes, at X0 only, at X1 only, or in neither (a "
           "mutant survived); inconclusive: no conclusive run.", ""]
    vs = ((doc or {}).get("groups") or {}).get(group)
    if not vs:
        return out + ["No map-audit results."]
    caught = ("both", "x0_only", "x1_only", "neither", "inconclusive")
    out += ["| version | " + " | ".join(caught) + " |",
            "|---|" + "---|" * len(caught)]
    for v in sorted(vs, key=int):
        c = Counter(e["caught"] for e in vs[v].values())
        out.append(f"| {int(v) / 10:.1f} | "
                   + " | ".join(str(c[k]) for k in caught) + " |")
    out += ["", "Atoms caught at HSA_XNACK=0 only: "
            + ", ".join(f"`{a}` ({int(v) / 10:.1f})" for v in sorted(
                vs, key=int) for a, e in sorted(vs[v].items())
                if e["caught"] == "x0_only") + ".", ""]
    return out


def render_dispositions(summary: dict) -> list[str]:
    """The per-atom dispositions of every legal program (the committed
    tests/data/oracle_audit_summary.json): counts, the unverified atoms
    with their reasons, the unaudited ones, the atoms valid only through a
    host fallback or a crash."""
    vs = summary["versions"]
    names = list(DISPOSITIONS)
    run = summary.get("run", {})
    out = ["## Dispositions (all legal programs; Tasks 9c, 12)", "",
           "Every legal program's atom, from the summary committed as "
           "`tests/data/oracle_audit_summary.json` (run: "
           + ("one full audit" if run.get("full") else "NOT a full audit")
           + (" (versions " + ", ".join(str(v) for v in run["versions"])
              + " run now and merged into the earlier full results of the "
              "others" + (f"; {run['reused_programs']} programs reuse the "
                          f"version {run['reused_from']} results of the "
                          "same body: "
                          + reuse_caveat(
                              FULL[run.get("model", "omp")][1],
                              run["versions"], run["reused_from"],
                              run.get("lang", "f90"))
                          if run.get("reused_from") else "")
              + ")" if run.get("merged") and run.get("full") else "")
           + (f", started {run['started']}, {run.get('seconds', '?')} s "
              f"with {run.get('workers', '?')} workers"
              if run.get("started") else "")
           + "). An observable program whose evidence is `construct`, "
           "`copy_mode_only` or `probe` (a negative probe: it must end in "
           "the runtime's error termination) must be `valid` (the "
           "mutant killed on at least "
           "one toolchain) or `unaudited_no_passing_original` (no toolchain "
           "passes the original: nothing can be credited to a toolchain); "
           "(agreed) splits the former `unverified_*` "
           "dispositions: a program no single run can separate from its "
           "absence carries its category as evidence and disposition, with "
           "the spec sentence that makes it so (header lines `! no oracle "
           "(<kind>): <reason>` and `! basis: <citation>: \"<sentence>\"`, "
           "catalog/omp/no_oracle.yaml): `hint_only` (the support table "
           "reads 'accepted; conforms vacuously'), `implementation_defined` "
           "('implementation-defined'), `equivalent_default` ('equivalent to "
           "the default (no separable effect)'); `legality` is an atom whose "
           "oracle is an illegal variant (default(none)); `unverified_*` is "
           "reserved for atoms whose behaviour the spec fixes and whose "
           "deterministic oracle is possible but missing (`! unverified "
           "(<kind>): <reason>`, kind oracle_not_written or "
           "needs_other_infrastructure). None of them counts as supported; "
           "a rejection or a wrong answer keeps its outcome.", "",
           "| version | " + " | ".join(names) + " | total |",
           "|---|" + "---|" * (len(names) + 1)]
    for v in sorted(vs):
        c = Counter(e["disposition"] for e in vs[v].values())
        out.append(f"| {int(v) / 10:.1f} | "
                   + " | ".join(str(c[d]) for d in names)
                   + f" | {len(vs[v])} |")
    out.append("")
    groups = [("Atoms without a separating oracle",
               ("hint_only", "implementation_defined", "equivalent_default"),
               "the reason, then the spec basis (citation and sentence)"),
              ("Legality atoms (oracle: an illegal variant)", ("legality",),
               "the rule whose illegal variant is the oracle"),
              ("Unverified atoms (an oracle is possible but missing)",
               ("unverified_oracle_not_written",
                "unverified_needs_other_infrastructure"),
               "what is missing")]
    for title, disps, what in groups:
        out += [f"### {title}", "", f"Reason: {what}.", "",
                "| version | atom | disposition | reason |",
                "|---|---|---|---|"]
        for v in sorted(vs):
            for a, e in vs[v].items():
                if e["disposition"] in disps:
                    out.append(f"| {int(v) / 10:.1f} | `{a}` | "
                               f"{e['disposition']} | "
                               f"{_cell(e['reason'], 700)} |")
        out.append("")
    out += ["### Unaudited: no toolchain passes the original", "",
            "| version | atom | originals |", "|---|---|---|"]
    for v in sorted(vs):
        for a, e in vs[v].items():
            if e["disposition"] == "unaudited_no_passing_original":
                out.append(f"| {int(v) / 10:.1f} | `{a}` | "
                           f"{_cell(e['reason'], 200)} |")
    out += ["", "### Valid only through a host fallback or a crash", "",
            "| version | atom | kill kinds |", "|---|---|---|"]
    for v in sorted(vs):
        for a, e in vs[v].items():
            if e["disposition"] == "valid" and \
                    "check_fail" not in e["kill_kinds"]:
                out.append(f"| {int(v) / 10:.1f} | `{a}` | "
                           f"{', '.join(e['kill_kinds'])} |")
    bad = [(v, a, e["disposition"]) for v in sorted(vs)
           for a, e in vs[v].items() if e["observable"]
           and e["evidence"] in ("construct", "copy_mode_only", "probe")
           and e["disposition"] not in ("valid",
                                        "unaudited_no_passing_original")]
    out += ["", "### Postcondition violations", "",
            "Observable programs with evidence construct, copy_mode_only or "
            "probe "
            f"whose atom is neither valid nor unaudited: {len(bad)}.", ""]
    out += [f"- {int(v) / 10:.1f} `{a}`: {d}" for v, a, d in bad]
    out.append("")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model", choices=("omp", "acc"), default="omp",
                    help="acc: the OpenACC programs")
    ap.add_argument("--lang", choices=("f90", "c"), default="f90",
                    help="c: the C programs (OpenMP only)")
    ap.add_argument("--versions", type=int, nargs="+", default=None)
    ap.add_argument("--toolchains", nargs="+", default=None)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--xnack", type=int, default=0)
    ap.add_argument("--opt", default="-O2")
    ap.add_argument("--timeout", type=int, default=120,
                    help="run timeout per execution, seconds")
    ap.add_argument("--only", default=None,
                    help="regular expression on the primary atom")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--md", type=Path, default=None,
                    help="report path; default: the committed doc for a "
                    "full run, results/oracle_audit.partial.md otherwise")
    ap.add_argument("--merge", action="store_true",
                    help="merge the (partial, --only) run into --out: its "
                    "programs replace their earlier results")
    ap.add_argument("--report-only", action="store_true",
                    help="regenerate the Markdown from --out")
    ap.add_argument("--reuse", type=int, default=None,
                    help="copy the results of this version's program of "
                    "the same atom when the body is identical ("
                    "--versions 50 --reuse 52), from --out")
    ap.add_argument("--summary", type=Path, default=None,
                    help="per-atom summary JSON (dispositions); default: "
                    "the committed tests/data file for a full run, "
                    "results/oracle_audit.partial.summary.json otherwise")
    args = ap.parse_args(argv)
    LANG[0] = args.lang
    MODEL[0] = args.model
    full_versions, full_tcs = FULL[
        "accc" if args.lang == "c" and args.model == "acc"
        else "c" if args.lang == "c" else args.model]
    args.versions = args.versions or full_versions
    args.toolchains = args.toolchains or full_tcs
    acc = args.model == "acc"
    accc = acc and args.lang == "c"  
    args.out = args.out or ROOT / "results" / (
        "acc_oracle_audit_c.jsonl" if accc else
        "acc_oracle_audit.jsonl" if acc else "oracle_audit_c.jsonl"
        if args.lang == "c" else "oracle_audit.jsonl")
    md_full, summary_full = (ACC_C_MD, ACC_C_SUMMARY) if accc else (
        (ACC_MD, ACC_SUMMARY) if acc else (
            (C_MD, C_SUMMARY) if args.lang == "c" else (MD, SUMMARY)))
    from offload.engine.toolchains import NVIDIA_TOOLCHAINS
    if set(args.toolchains) <= set(NVIDIA_TOOLCHAINS):
        # the NVHPC memory mode, no XNACK
        mname = {0: "separate", 2: "managed"}.get(args.xnack, args.xnack)
        mode_text = (f"-gpu=mem:{mname} (NVHPC {mname} memory, row key "
                     f"{args.xnack})")
    else:
        mode_text = (f"HSA_XNACK={args.xnack} (copy mode; programs that need "
                     "zero-copy memory under HSA_XNACK=1)")

    def settings_for(versions, reused=None):
        return (f"{mode_text}, {args.opt}, one "
                f"repeat, run timeout {args.timeout} s (a timeout is run "
                f"once more), toolchains {', '.join(args.toolchains)}, "
                f"versions {', '.join(str(v) for v in versions)}, "
                "version flags as the matrix (run_matrix.for_version: "
                + "; ".join(f"{t} {v}: "
                            f"{version_flags(t, v, args.lang) or 'default'}"
                            for t in args.toolchains for v in versions)
                + ")" + (f"; {reused}" if reused else ""))
    settings = settings_for(args.versions)
    if args.report_only:
        results = read(args.out)
        mp = meta_path(args.out)
        meta = json.loads(mp.read_text()) if mp.exists() else {
            "full": False, "note": "no run metadata"}
        settings = settings_with_reuse(dict(meta, settings=meta.get(
            "settings", settings)), args.toolchains)
        meta["settings"] = settings
    else:
        only = None
        if args.only:
            pat = re.compile(args.only)
            only = lambda p: bool(pat.search(p.primary_atom))  # noqa: E731
        results = []
        earlier = read(args.out) if args.merge and args.out.exists() else []
        if args.merge:
            # Results of programs no longer audited (atoms out of
            # the device-offload scope, host+device patterns) are dropped
            current = {(v, p.id) for v in full_versions
                       for p in audit_programs(v, lang=args.lang)}
            earlier = [r for r in earlier
                       if (r.version, r.program_id) in current]
        source = read(args.out) if args.reuse and args.out.exists() else []
        reused_n = 0

        def merged(new):
            """`new` with the earlier results of other programs (--merge),
            written after each version so a crash keeps what is done."""
            done = {(r.version, r.program_id) for r in new}
            return sorted([r for r in earlier
                           if (r.version, r.program_id) not in done] + new,
                          key=lambda r: (r.version, r.program_id,
                                         r.toolchain))
        t0 = time.time()
        for v in args.versions:
            n = [0]

            def progress(msg):
                n[0] += 1
                print(f"[{time.time() - t0:7.0f}s] {v} #{n[0]} {msg}",
                      file=sys.stderr, flush=True)
            reuse = reusable(v, args.reuse, args.toolchains, source, only) \
                if args.reuse and args.reuse != v else {}
            run_only = only
            if reuse:
                def run_only(p, _only=only, _skip=set(reuse)):
                    return p.primary_atom not in _skip and (
                        _only is None or _only(p))
            results += audit(v, args.toolchains, xnack=args.xnack,
                             opt=args.opt, workers=args.workers,
                             only=run_only, timeout_s=args.timeout,
                             progress=progress, lang=args.lang)
            results += [r for rs in reuse.values() for r in rs]
            reused_n += len(reuse)
            write(merged(results), args.out)
        results = merged(results)
        print(f"audit: {len(results)} results in {time.time() - t0:.0f} s "
              f"with {args.workers} workers", file=sys.stderr)
        # A --merge run with --only is full when the merged
        # results cover every audited program as generated today
        plain = (args.only is None or args.merge) \
            and sorted(args.toolchains) == full_tcs \
            and args.xnack == 0 and args.opt == "-O2"
        # the versions the results (with what --merge kept) cover in full
        covered = set(args.versions) if plain and args.only is None \
            else set()
        if args.merge and plain:
            covered = set(complete(results, full_versions, full_tcs))
        if args.merge and sorted(covered) == full_versions:
            # the report describes the merged results, not this run alone
            settings = settings_for(
                full_versions, f"this run: versions "
                f"{', '.join(str(v) for v in args.versions)}, merged into "
                "the earlier results of the others"
                + (f"; {reused_n} programs reuse the version {args.reuse} "
                   "results of the same body (MutantResult.reused_from)"
                   if args.reuse else ""))
        if args.reuse and reused_n:
            settings = settings_with_reuse(
                {"settings": settings, "reused_from": args.reuse,
                 "reused_programs": reused_n, "versions": args.versions,
                 "lang": args.lang}, args.toolchains)
        meta = {"full": sorted(covered) == full_versions,
                "full_versions": sorted(covered),
                "reused_programs": reused_n, "reused_from": args.reuse,
                "model": args.model, "lang": args.lang,
                "settings": settings, "versions": sorted(args.versions),
                "started": time.strftime("%Y-%m-%dT%H:%M:%S",
                                         time.localtime(t0)),
                "seconds": round(time.time() - t0), "workers": args.workers,
                "only": args.only, "merged": args.merge}
        if args.merge and meta_path(args.out).exists():
            meta["merged_into"] = json.loads(meta_path(args.out).read_text())
            meta["merged_into"].pop("merged_into", None)
        meta_path(args.out).write_text(json.dumps(meta, indent=1) + "\n")
    # the committed summary and doc come from one full run only: any other
    # run writes next to the results unless told where
    full = bool(meta.get("full"))
    if args.md is None:
        args.md = md_full if full else args.out.with_suffix(".partial.md")
    if args.summary is None:
        args.summary = summary_full if full else args.out.with_suffix(
            ".partial.summary.json")
    if not full and (args.md.resolve() == md_full.resolve()
                     or args.summary.resolve() == summary_full.resolve()):
        ap.error("the committed report and summary are written only from "
                 "a full run (all versions and toolchains, no --only or "
                 "--merge, HSA_XNACK=0, -O2)")
    args.md.parent.mkdir(parents=True, exist_ok=True)
    doc = write_summary(results, meta, args.summary)
    args.md.write_text(render(results, {"settings": settings}, doc,
                              args.model))
    c = Counter((r.version, r.toolchain, r.status) for r in results)
    for k in sorted(c):
        print(*k, c[k])
    return 0


if __name__ == "__main__":
    sys.exit(main())
