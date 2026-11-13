"""The map-mutant audit in both memory modes.

    # run (resumable: programs already in --out are skipped)
    python3 -I tools/campaigns/map_audit.py run --lang f90 --versions 52 \
        --toolchains afar --out results/map_audit/f90.52.afar.jsonl
    # report: results/map_audit/*.jsonl -> data/reports/map-mutant-audit.md
    python3 -I tools/campaigns/map_audit.py report
    # gfx90a (Tioga, HSA_XNACK=0): data/reports/map-mutant-audit-gfx90a.md
    python3 -I tools/campaigns/map_audit.py report-g90

Each program of the primary-atom oracle audit (offload.engine.mutate.
audit_programs) runs with its map mutants (offload.engine.mutate.map_mutants) on
each toolchain at HSA_XNACK=0 and 1. A mutant killed only at HSA_XNACK=0
marks a check that sees a mapping error in copy mode but not under unified
memory. ``report-g90`` also classifies every surviving mutant."""
import argparse
import dataclasses
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine.mutate import (MAP_KIND_TEXT, MAP_KINDS,  # noqa: E402
                               MapMutantResult, audit_programs, map_audit,
                               map_summary)

RESULTS = ROOT / "results" / "map_audit"
MD = ROOT / "data" / "reports" / "map-mutant-audit.md"
SUMMARY = ROOT / "tests" / "data" / "map_audit_summary.json"
FULL = {"f90": ([50, 52, 60], ["afar", "cce19"]),
        "c": ([50, 52, 60], ["afar", "cce19"]),  # C 5.0
        "acc": ([34], ["cce19"])}
CAUGHT = ("both", "x0_only", "x1_only", "neither", "inconclusive")


def read(path: Path) -> list[MapMutantResult]:
    return [MapMutantResult(**json.loads(ln))
            for ln in Path(path).read_text().splitlines() if ln.strip()]


def cmd_run(a) -> int:
    lang = "f90" if a.lang == "acc" else a.lang
    a.out.parent.mkdir(parents=True, exist_ok=True)
    done = {(r.version, r.program_id) for r in read(a.out)} \
        if a.out.exists() else set()
    meta = {"host": os.uname().nodename, "lang": a.lang,
            "versions": a.versions, "toolchains": a.toolchains,
            "modes": a.modes,
            "workers": a.workers, "flux_job": os.environ.get("FLUX_JOB_ID"),
            "thp": Path("/sys/kernel/mm/transparent_hugepage/enabled")
            .read_text().strip() if Path(
                "/sys/kernel/mm/transparent_hugepage/enabled").exists()
            else "", "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    t0 = time.time()
    n = 0
    for v in a.versions:
        todo = [p.id for p in audit_programs(v, lang=lang)
                if (v, p.id) not in done]
        for i in range(0, len(todo), a.batch):
            ids = set(todo[i:i + a.batch])
            rs = map_audit(v, a.toolchains, modes=a.modes,
                           workers=a.workers,
                           only=lambda p, _ids=ids: p.id in _ids,
                           timeout_s=a.timeout, lang=lang)
            with a.out.open("a") as f:
                for r in rs:
                    f.write(json.dumps(dataclasses.asdict(r)) + "\n")
            n += len(rs)
            print(f"[{time.time() - t0:6.0f}s] {v}: {i + len(ids)}/"
                  f"{len(todo)} programs, {n} results", file=sys.stderr,
                  flush=True)
    meta["seconds"] = round(time.time() - t0)
    meta["results"] = n
    mp = Path(str(a.out) + ".meta.json")
    old = json.loads(mp.read_text()) if mp.exists() else {"runs": []}
    old["runs"].append(meta)
    mp.write_text(json.dumps(old, indent=1) + "\n")
    return 0


def _group(lang: str, version: int) -> str:
    return "acc" if version == 34 else lang


def summary_doc(results: list[MapMutantResult]) -> dict:
    """{group: {version: map_summary}} (group f90, c or acc)."""
    out: dict = {}
    keys = sorted({(_group(r.lang, r.version), r.version) for r in results})
    for g, v in keys:
        rs = [r for r in results if _group(r.lang, r.version) == g
              and r.version == v]
        out.setdefault(g, {})[str(v)] = map_summary(rs)
    return out


def complete(results: list[MapMutantResult]) -> dict:
    """Per group: whether every audited program of every full version has
    a result on every full toolchain in both modes."""
    have = {(r.version, r.program_id, r.toolchain, r.xnack)
            for r in results}
    out = {}
    for g, (vs, tcs) in FULL.items():
        lang = "f90" if g == "acc" else g
        ok = True
        for v in vs:
            for p in audit_programs(v, lang=lang):
                from offload.engine.mutate import map_mutants
                if not map_mutants(p):
                    continue
                if not all((v, p.id, t, x) in have for t in tcs
                           for x in (0, 1)):
                    ok = False
        out[g] = ok
    return out


def render(results: list[MapMutantResult], doc: dict, full: dict) -> str:
    vname = {34: "OpenACC 3.4", 50: "5.0", 52: "5.2", 60: "6.0"}
    out = ["# Map-mutant audit by memory mode", "",
           "Generated by `tools/campaigns/map_audit.py report`; do not edit. For every "
           "program of the oracle audit (legal, observable, evidence "
           "construct, copy_mode_only or probe, device scope) the MAP "
           "MUTANTS below run with the original on each toolchain at "
           "HSA_XNACK=0 (copy mode: host and device memory separate) and "
           "at HSA_XNACK=1 (unified memory, the headline mode), -O2, one "
           "repeat (a timeout is run once more). Statuses as in the oracle "
           "audit (killed, survived, inconclusive). A kind **caught at X0 "
           "only** is a check that sees the mapping error in copy mode and "
           "is blind to it under unified memory: the program is a valid "
           "oracle of its mapping in copy mode only, which is why the "
           "support tables now carry the X0 column and the portable "
           "verdict.", "",
           "Mutants (applied to every directive outside the "
           "infrastructure: the probe, the shared-memory detector and the "
           "reporting variables' clauses are never touched):", ""]
    out += [f"- `{k}`: {MAP_KIND_TEXT[k]}." for k in MAP_KINDS]
    out += ["", "Complete runs (every audited program with a map mutant, "
            "every toolchain, both modes): "
            + ", ".join(f"{g} {'yes' if ok else 'NO'}"
                        for g, ok in full.items()) + ".", ""]
    out += ["## Status counts", "",
            "| group | version | toolchain | X | killed | survived | "
            "inconclusive |", "|---|---|---|---|---|---|---|"]
    c = Counter((_group(r.lang, r.version), r.version, r.toolchain, r.xnack,
                 r.status) for r in results)
    for g, v, t, x in sorted({k[:4] for k in c}):
        out.append(f"| {g} | {vname.get(v, v)} | {t} | {x} | "
                   + " | ".join(str(c[(g, v, t, x, s)]) for s in
                                ("killed", "survived", "inconclusive"))
                   + " |")
    out += ["", "## Which mode catches each kind (atoms)", "",
            "Per atom and kind: `both`, `x0_only`, `x1_only` or `neither` "
            "(killed on some toolchain in that mode; `neither`: a mutant "
            "ran conclusively and survived), `inconclusive` (no run of the "
            "kind was conclusive: the original was not correct, the "
            "mutant was illegal or rejected).", "",
            "| group | version | kind | " + " | ".join(CAUGHT) + " |",
            "|---|---|---|" + "---|" * len(CAUGHT)]
    for g in doc:
        for v, atoms in doc[g].items():
            for k in MAP_KINDS:
                cc = Counter(e["kinds"][k] for e in atoms.values()
                             if k in e["kinds"])
                if cc:
                    out.append(f"| {g} | {vname.get(int(v), v)} | `{k}` | "
                               + " | ".join(str(cc[x]) for x in CAUGHT)
                               + " |")
    out += ["", "## Atoms by mode (any kind)", "",
            "| group | version | " + " | ".join(CAUGHT) + " |",
            "|---|---|" + "---|" * len(CAUGHT)]
    for g in doc:
        for v, atoms in doc[g].items():
            cc = Counter(e["caught"] for e in atoms.values())
            out.append(f"| {g} | {vname.get(int(v), v)} | "
                       + " | ".join(str(cc[x]) for x in CAUGHT) + " |")
    out += ["", "## Per atom", "",
            "Each kind's mode; `-`: the program has nothing that kind "
            "changes.", "",
            "| group | version | atom | " + " | ".join(MAP_KINDS)
            + " | caught |", "|---|---|---|" + "---|" * len(MAP_KINDS)
            + "---|"]
    for g in doc:
        for v, atoms in doc[g].items():
            for atom, e in atoms.items():
                out.append(f"| {g} | {vname.get(int(v), v)} | `{atom}` | "
                           + " | ".join(e["kinds"].get(k, "-")
                                        for k in MAP_KINDS)
                           + f" | {e['caught']} |")
    out += ["", "## Mutants caught at HSA_XNACK=1 only", "",
            "A mapping error that only unified memory exposes (e.g. a "
            "mapped copy that hides the host's later write): listed for "
            "review.", "", "| group | version | program | kind | "
            "toolchain | mutant |", "|---|---|---|---|---|---|"]
    by = {}
    for r in results:
        by.setdefault((r.program_id, r.kind, r.toolchain), {})[r.xnack] = r
    for (pid, k, t), m in sorted(by.items()):
        if m.get(1) and m[1].status == "killed" and not (
                m.get(0) and m[0].status == "killed"):
            r = m[1]
            out.append(f"| {_group(r.lang, r.version)} | "
                       f"{vname.get(r.version, r.version)} | {pid} | {k} | "
                       f"{t} | {r.mutant}: "
                       f"{' '.join(r.reason.split())[:160]} |")
    return "\n".join(out) + "\n"


def cmd_report(a) -> int:
    results = []
    for p in sorted(a.results.glob("*.jsonl")):
        results += read(p)
    seen = Counter((r.version, r.program_id, r.kind, r.toolchain, r.xnack)
                   for r in results)
    dup = [k for k, n in seen.items() if n > 1]
    if dup:
        print(f"duplicated results: {len(dup)}, e.g. {dup[:3]}")
        return 1
    doc = summary_doc(results)
    full = complete(results)
    a.md.parent.mkdir(parents=True, exist_ok=True)
    a.md.write_text(render(results, doc, full))
    a.summary.parent.mkdir(parents=True, exist_ok=True)
    a.summary.write_text(json.dumps(
        {"generated_by": "tools/campaigns/map_audit.py", "complete": full,
         "groups": {g: {v: {atom: {k: e[k] for k in
                                   ("program", "kinds", "caught",
                                    "copy_mode_only")}
                            for atom, e in atoms.items()}
                        for v, atoms in vs.items()}
                    for g, vs in doc.items()}},
        indent=1, sort_keys=True) + "\n")
    c = Counter((_group(r.lang, r.version), r.xnack, r.status)
                for r in results)
    for k in sorted(c):
        print(*k, c[k])
    print("complete:", full)
    return 0


# --- The discrete GPU (gfx90a) -------------------------------------

G90_RESULTS = ROOT / "results" / "tioga" / "map_audit"
G90_MD = ROOT / "data" / "reports" / "map-mutant-audit-gfx90a.md"
G90_SUMMARY = ROOT / "tests" / "data" / "map_audit_g90_summary.json"
# On a discrete GPU a mapping error cannot hide behind shared memory, so a
# map mutant that survives there is one of these:
SURVIVOR_CLASSES = {
    "equivalent_probe": "the program is a negative or compile-time probe: "
                        "its verdict is the runtime's error termination or "
                        "a compile diagnostic, which the map types of its "
                        "other regions do not change (an equivalent "
                        "mutant)",
    "oracle_weakness_uninit": "the check reads an item the program maps "
                              "back (from or tofrom) but the host never "
                              "assigns before the region, and the mutant "
                              "drops or weakens that map: the check judges "
                              "it on uninitialized memory, so it may "
                              "survive by chance (detected mechanically, "
                              "offload.engine.mutate.uninit_affected; an oracle "
                              "weakness, hardening list data/reports/"
                              "uninit-from-scalars.txt)",
    "covered": "a stronger transfer change of the same program "
               "(weaken_map or swap_to_from) is killed on the same "
               "compiler, so the check sees mapping errors; this kind is "
               "neutral for the program: after drop_map the implicit maps "
               "(arrays, reduction and link items tofrom; scalars "
               "firstprivate with the host's own value, which the "
               "oracle_weakness_uninit rule has already checked) "
               "move the same data, a weakened or swapped map is followed "
               "by a target update that moves the data again, or a "
               "dropped update had a false if (a mechanical rule; the reasons "
               "were checked on samples, not per mutant)",
    "equivalent_implicit": "the mutant leaves the program's own implicit "
                           "mapping in charge and that moves the same data "
                           "(an equivalent mutant; reviewed)",
    "compiler_copies": "the compiler moves data the mutated map types do "
                       "not move (a compiler behaviour with a finding, not "
                       "a weakness of the check)",
    "oracle_weakness": "none of the above: the check misses a mapping "
                       "error a discrete GPU exposes; the program must be "
                       "fixed",
}
# reviewed survivors that no rule explains: (program patterns, compiler
# patterns (gfx942 names), kinds, class, why)
G90_REVIEWED = (
    (("omp5?-clause-defaultmap-tofrom", "omp60-clause-defaultmap-tofrom"),
     ("cce19",), ("drop_map",), "equivalent_implicit",
     "the target construct has defaultmap(tofrom): without the explicit "
     "map clauses a and b are mapped tofrom implicitly, the same "
     "transfers"),
    (("omp5?-clause-defaultmap-tofrom", "omp60-clause-defaultmap-tofrom"),
     ("cce19",), ("weaken_map", "swap_to_from"), "compiler_copies",
     "CCE 19 treats an array the construct maps explicitly (alloc, to, "
     "from) as tofrom when the construct also has defaultmap(tofrom): the "
     "finding's exit-direction program shows the device's writes reaching "
     "the host under map(alloc:) and map(to:) (separate storage shown "
     "in the same configuration without defaultmap) "
     "(data/findings/cce-defaultmap-tofrom-explicit-map.f90; MI250X and "
     "MI300A at HSA_XNACK=0; CCE 20 and AFAR correct). AFAR kills both "
     "mutants."),
)


def g90_index(results) -> dict:
    """(version, program, compiler, kind) -> result."""
    return {(r.version, r.program_id, r.toolchain, r.kind): r
            for r in results}


def survivor_class(r, by: dict, expect_of, uninit_of=lambda r: []
                   ) -> tuple[str, str]:
    """The class (SURVIVOR_CLASSES) and reason of a surviving map mutant;
    `expect_of(version, lang, program)` is the program's Program.expect,
    `uninit_of(result)` the uninitialized from-mapped items its mutant
    leaves without a copy-back (offload.engine.mutate.uninit_affected)."""
    from fnmatch import fnmatchcase
    from offload.engine.toolchains import base_name
    if expect_of(r.version, r.lang, r.program_id) != "result":
        return "equivalent_probe", SURVIVOR_CLASSES["equivalent_probe"]
    items = uninit_of(r)
    if items:
        return "oracle_weakness_uninit", ("the check reads "
                                          + ", ".join(items)
                                          + " (never set on the host)")
    for pats, tcs, kinds, cls, why in G90_REVIEWED:
        if any(fnmatchcase(r.program_id, p) for p in pats) and any(
                fnmatchcase(base_name(r.toolchain), t) for t in tcs) \
                and r.kind in kinds:
            return cls, why
    for k in ("weaken_map", "swap_to_from"):
        o = by.get((r.version, r.program_id, r.toolchain, k))
        if k != r.kind and o is not None and o.status == "killed":
            return "covered", f"{k} killed"
    return "oracle_weakness", SURVIVOR_CLASSES["oracle_weakness"]


def _expect_of():
    from functools import lru_cache

    @lru_cache(maxsize=None)
    def progs(version, lang):
        return {p.id: p.expect for p in audit_programs(
            version, lang="f90" if lang == "acc" else lang)}
    return lambda v, lang, pid: progs(v, lang).get(pid, "result")


def _uninit_of():
    """result -> the uninitialized from-mapped items its mutant leaves
    without a copy-back (offload.engine.mutate.uninit_affected), cached."""
    from functools import lru_cache
    from offload.engine.mutate import map_mutants, uninit_affected

    @lru_cache(maxsize=None)
    def progs(version, lang):
        return {p.id: p for p in audit_programs(
            version, lang="f90" if lang == "acc" else lang)}

    @lru_cache(maxsize=None)
    def items(version, lang, pid, kind):
        p = progs(version, lang).get(pid)
        m = map_mutants(p).get(kind) if p else None
        return tuple(uninit_affected(p.source, m.source)) if m else ()
    return lambda r: list(items(r.version, r.lang, r.program_id, r.kind))


def uninit_list() -> list[tuple[str, str, list[str]]]:
    """(language, program id, items) of every legal catalog program whose
    check reads a from-mapped item the host never sets (the hardening list), mechanically (offload.engine.mutate.uninit_from_items)."""
    from offload.engine.c_gen import all_c_programs
    from offload.engine.gen import all_programs
    from offload.engine.mutate import uninit_from_items
    out = []
    for lang, gen, vs in (("f90", all_programs, (50, 52, 60)),
                          ("c", all_c_programs, (50, 52, 60)),
                          ("acc", all_programs, (34,))):
        for v in vs:
            for p in gen(v):
                if p.legal:
                    it = uninit_from_items(p.source)
                    if it:
                        out.append((lang, p.id, it))
    return out


def render_g90(results, x0_results, expect_of, uninit_of=lambda r: []
               ) -> tuple[str, dict]:
    """(Markdown, summary) of the gfx90a map audit: status counts, the
    agreement with the same compiler's MI300A HSA_XNACK=0 status, and every
    survivor with its class."""
    from offload.engine.toolchains import base_name
    by = g90_index(results)
    x0 = {(r.version, r.program_id, r.toolchain, r.kind): r
          for r in x0_results if r.xnack == 0}
    c = Counter((_group(r.lang, r.version), r.version, r.toolchain, r.status)
                for r in results)
    agree, diffs = Counter(), []
    for k, r in sorted(by.items()):
        o = x0.get((k[0], k[1], base_name(k[2]), k[3]))
        if o is None:
            continue
        same = o.status == r.status
        agree["same" if same else "differ"] += 1
        if not same:
            diffs.append((r, o))
    surv = [(r, *survivor_class(r, by, expect_of, uninit_of)) for r in
            sorted(results, key=lambda r: (r.version, r.program_id,
                                           r.toolchain, r.kind))
            if r.status == "survived"]
    sc = Counter(cls for _, cls, _ in surv)
    vname = {34: "OpenACC 3.4", 50: "5.0", 52: "5.2", 60: "6.0"}
    out = ["# Map-mutant audit on the discrete GPU", "",
           "Generated by `tools/campaigns/map_audit.py report-g90`; do not edit. The "
           "map mutants of the audit (data/reports/"
           "map-mutant-audit.md) ran on Tioga's AMD Instinct MI250X "
           "(gfx90a, separate HBM, HSA_XNACK=0 only, maintainer ruling "
           "2026-10-22) with the gfx90a twins of AFAR and CCE 19 (OpenACC: "
           "CCE 19), -O2, one repeat. On a discrete GPU a missing or wrong "
           "map cannot be hidden by shared memory, so every map mutant the "
           "check can see should be killed; each survivor is classified "
           "below.", "",
           "## Status counts", "",
           "| group | version | toolchain | killed | survived | "
           "inconclusive |", "|---|---|---|---|---|---|"]
    for g, v, t in sorted({k[:3] for k in c}):
        out.append(f"| {g} | {vname.get(v, v)} | {t} | " + " | ".join(
            str(c[(g, v, t, s)]) for s in ("killed", "survived",
                                           "inconclusive")) + " |")
    out += ["", "## Agreement with MI300A copy mode", "",
            f"Of {sum(agree.values())} (program, kind, compiler) results "
            "with an MI300A HSA_XNACK=0 result of the same compiler "
            f"(results/map_audit/), {agree['same']} have the same status "
            f"and {agree['differ']} differ"
            + (":" if diffs else "."), ""]
    if diffs:
        out += ["| version | program | kind | compiler | MI300A X0 | gfx90a |",
                "|---|---|---|---|---|---|"]
        out += [f"| {vname.get(r.version, r.version)} | {r.program_id} | "
                f"{r.kind} | {base_name(r.toolchain)} | {o.status} | "
                f"{r.status} |" for r, o in diffs]
        out.append("")
    out += ["## Survivors", "",
            f"{len(surv)} surviving mutants: "
            + ", ".join(f"{'unclassified (oracle_weakness)' if k == 'oracle_weakness' else k} {sc[k]}"
                        for k in SURVIVOR_CLASSES) + ". "
            "Classes: " + "; ".join(f"**{k}**: {v}"
                                    for k, v in SURVIVOR_CLASSES.items())
            + ".", "",
            "| version | program | kind | toolchain | class | why |",
            "|---|---|---|---|---|---|"]
    for r, cls, why in surv:
        out.append(f"| {vname.get(r.version, r.version)} | {r.program_id} | "
                   f"{r.kind} | {r.toolchain} | {cls} | "
                   f"{why if cls not in ('equivalent_probe',) else ''} |")
    # The uninit weakness per toolchain and GPU/mode,
    # gfx90a and the MI300A audit (both modes) alike
    ucount = Counter()
    for label, rs in (("gfx90a X0", [r for r in results]),
                      ("MI300A X0", [r for r in x0_results if r.xnack == 0]),
                      ("MI300A X1", [r for r in x0_results if r.xnack == 1])):
        for r in rs:
            if r.status != "survived":
                continue
            ucount[(base_name(r.toolchain), label, "survived")] += 1
            if expect_of(r.version, r.lang, r.program_id) == "result" \
                    and uninit_of(r):
                ucount[(base_name(r.toolchain), label, "uninit")] += 1
    out += ["", "## Checks that read uninitialized from-mapped items", "",
            "Survivors whose check reads an item the program maps back "
            "but the host never assigns (oracle_weakness_uninit), per "
            "compiler and GPU/mode, out of all survivors there. Detected "
            "mechanically (offload.engine.mutate.uninit_affected); the same "
            "rule applied to the MI300A audit (results/map_audit/).", "",
            "| compiler | GPU / mode | survivors | oracle_weakness_uninit |",
            "|---|---|---|---|"]
    for t, label in sorted({k[:2] for k in ucount}):
        out.append(f"| {t} | {label} | {ucount[(t, label, 'survived')]} | "
                   f"{ucount[(t, label, 'uninit')]} |")
    hard = uninit_list()
    out += ["", "### Hardening list", "",
            f"{len(hard)} legal catalog programs whose check reads a "
            "from-mapped item the host never sets before the region "
            "(offload.engine.mutate.uninit_from_items; also in data/reports/"
            "uninit-from-scalars.txt). Initializing each item on the host "
            "to a value the check rejects makes a lost copy-back fail "
            "deterministically. The original programs are not affected "
            "(they copy the values back). Hardened every program "
            "of the list, which is empty since.", "",
            "| language | program | items |", "|---|---|---|"]
    out += [f"| {lang} | {pid} | {', '.join(it)} |" for lang, pid, it in hard]
    doc = {"generated_by": "tools/campaigns/map_audit.py report-g90",
           "status": {f"{g}|{v}|{t}|{s}": n
                      for (g, v, t, s), n in sorted(c.items())},
           "agree_with_x0": {"same": agree["same"],
                             "differ": agree["differ"]},
           "survivors": {k: sc[k] for k in SURVIVOR_CLASSES},
           "oracle_weakness": sorted({f"{r.program_id} {r.kind} "
                                      f"{r.toolchain}" for r, cls, _ in surv
                                      if cls == "oracle_weakness"}),
           "oracle_weakness_uninit": sorted({
               f"{r.program_id} {r.kind} {r.toolchain}" for r, cls, _ in surv
               if cls == "oracle_weakness_uninit"}),
           "uninit_by_toolchain": {f"{t}|{label}|{k}": n for (t, label, k), n
                                   in sorted(ucount.items())},
           "hardening_list": [f"{lang} {pid} {','.join(it)}"
                              for lang, pid, it in hard]}
    return "\n".join(out) + "\n", doc


def cmd_report_g90(a) -> int:
    results = []
    for p in sorted(a.results.glob("*.jsonl")):
        results += read(p)
    x0 = []
    for p in sorted(a.x0.glob("*.jsonl")):
        x0 += read(p)
    md, doc = render_g90(results, x0, _expect_of(), _uninit_of())
    a.md.write_text(md)
    a.uninit.write_text(
        "# Legal catalog programs whose check reads a\n"
        "# from-mapped item (map from/tofrom, OpenACC copy/copyout) that the\n"
        "# host never assigns before the region; a mutant (or compiler) that\n"
        "# loses the copy-back is judged on uninitialized memory. A\n"
        "# hardened all of them (the 140, less 10 C programs the\n"
        "# old detector over-listed, plus 2 it missed): each item starts at a\n"
        "# sentinel the check rejects; tests/engine/test_generators.py keeps this\n"
        "# list empty.\n"
        "# Generated by tools/campaigns/map_audit.py report-g90\n"
        "# (offload.engine.mutate.uninit_from_items). Columns: language program "
        "items\n" + "".join(f"{e}\n" for e in doc["hardening_list"]))
    a.summary.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: doc[k] for k in ("agree_with_x0", "survivors",
                                          "oracle_weakness",
                                          "uninit_by_toolchain")}, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--lang", choices=("f90", "c", "acc"), default="f90")
    r.add_argument("--versions", type=int, nargs="+", required=True)
    r.add_argument("--toolchains", nargs="+", required=True)
    r.add_argument("--workers", type=int, default=16)
    r.add_argument("--timeout", type=int, default=120)
    r.add_argument("--batch", type=int, default=24)
    r.add_argument("--modes", type=int, nargs="+", choices=(0, 1, 2),
                   default=[0, 1], help="HSA_XNACK values (the "
                   "gfx90a toolchains run 0 only)")
    r.add_argument("--out", type=Path, required=True)
    rp = sub.add_parser("report")
    rp.add_argument("--results", type=Path, default=RESULTS)
    rp.add_argument("--md", type=Path, default=MD)
    rp.add_argument("--summary", type=Path, default=SUMMARY)
    rg = sub.add_parser("report-g90")
    rg.add_argument("--results", type=Path, default=G90_RESULTS)
    rg.add_argument("--x0", type=Path, default=RESULTS)
    rg.add_argument("--md", type=Path, default=G90_MD)
    rg.add_argument("--summary", type=Path, default=G90_SUMMARY)
    rg.add_argument("--uninit", type=Path, default=ROOT / "data" / "reports"
                    / "uninit-from-scalars.txt")
    a = ap.parse_args(argv)
    return {"run": cmd_run, "report": cmd_report,
            "report-g90": cmd_report_g90}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
