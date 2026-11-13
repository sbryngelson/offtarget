#!/usr/bin/env python3
"""The C coverage review.

    # amdclang's frontend verdict on every C program: results/clang_check_c.jsonl
    python3 -I tools/campaigns/c_coverage.py clang [--workers 6]
    # the review page
    python3 -I tools/campaigns/c_coverage.py report

``report`` reads the catalog, the generator, the rules, the audit summaries,
the support tables, the baselines and results/clang_check_c.jsonl. The page
lists the atoms covered in both languages and in only one, the C programs
whose Fortran oracle did not carry over or whose evidence was relabelled,
the C rules, the triage of the C/C++ spec sentences, the C and Fortran
outcomes per toolchain, the omp_vv C baseline and the frontend cross-checks
(gcc -std=c11 for the base language, amdclang for OpenMP legality)."""
import argparse
import collections
import csv
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from offload.engine import c_gen  # noqa: E402
from offload.engine.catalog import slice_atoms  # noqa: E402

CLANG = ROOT / "results" / "clang_check_c.jsonl"
OUT = ROOT / "data" / "reports" / "c-coverage.md"
AUDIT_F = ROOT / "tests" / "data" / "oracle_audit_summary.json"
AUDIT_C = ROOT / "tests" / "data" / "oracle_audit_summary_c.json"
TABLE_F = ROOT / "results" / "support_table.csv"
TABLE_C = ROOT / "results" / "support_table_c.csv"
BASE_F = ROOT / "results" / "baseline.jsonl"
BASE_C = ROOT / "results" / "baseline_c.jsonl"
TOOLCHAINS = ("afar", "cce19", "cce20", "cce21")


def _programs():
    for v in c_gen.C_VERSIONS:
        yield from c_gen.all_c_programs(v)


def cmd_clang(args) -> int:
    from offload.engine import clang_oracle

    def one(p):
        v = int(p.id[3:5])
        rec = {"program_id": p.id, "version": v, "legal": p.legal,
               "violates": p.violates}
        try:
            chk = clang_oracle.syntax_check(p.source, v)
            rec.update(ok=chk.ok, errors=list(chk.errors), stage="ok")
        except clang_oracle.ClangError as e:
            rec.update(ok=None, errors=[e.message], stage=e.stage)
        return rec

    progs = list(_programs())
    with ThreadPoolExecutor(args.workers) as ex:
        recs = list(ex.map(one, progs))
    CLANG.write_text("".join(json.dumps(r) + "\n" for r in recs))
    c = collections.Counter((r["version"], r["legal"], r["ok"])
                            for r in recs)
    print(f"{len(recs)} programs -> {CLANG}")
    for k in sorted(c, key=str):
        print(*k, c[k])
    return 0


# --- report ---------------------------------------------------------------------------

def _md(s) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def _clip(s: str, n: int = 160) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n - 1] + "…"


def _table(head, rows) -> list[str]:
    out = ["| " + " | ".join(head) + " |",
           "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(_md(x) for x in r) + " |" for r in rows]
    return out + [""]


def _read_csv(path: Path) -> list[dict]:
    return list(csv.DictReader(open(path))) if path.exists() else []


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text().splitlines()
            if x.strip()]


def _atoms_section() -> list[str]:
    out = ["## Atoms", "",
           "An atom is covered in a language when the slice has it for "
           "that language (`catalog.slice_atoms(version, lang=...)`; the "
           "`langs` field of semantic_atoms.yaml and clauses.yaml, the "
           "`for` compounds in C, `begin declare target` C only).", ""]
    rows = []
    for v in c_gen.C_VERSIONS:
        f = set(slice_atoms(v, lang="f90"))
        c = set(slice_atoms(v, lang="c"))
        rows.append((f"{v // 10}.{v % 10}", len(f), len(c), len(f & c),
                     len(f - c), len(c - f)))
    out += _table(("version", "Fortran atoms", "C atoms", "both",
                   "Fortran only", "C only"), rows)
    for v in c_gen.C_VERSIONS:
        out += [f"Fortran-only atoms at {v // 10}.{v % 10}: " + ", ".join(
            f"`{a}`" for a in c_gen.fortran_only_atoms(v)) + ".", ""]
        out += [f"C-only atoms at {v // 10}.{v % 10}: " + ", ".join(
            f"`{a}`" for a in c_gen.c_only_atoms(v)) + ".", ""]
    out += ["Why Fortran only: `do` compounds (C has `for`); "
            "`workdistribute` (a Fortran construct, 6.0 §13.5, p.412); "
            "`defaultmap` categories `allocatable` and `character` and "
            "`default(shared: allocatable)` (Fortran variable categories); "
            "`linear` modifiers `ref` and `uval` (Fortran only, 5.2 §5.4.6); "
            "the `.eqv.`/`.neqv.` reduction identifiers; the `map` "
            "ref-modifiers `ref_ptee`, `ref_ptr`, `ref_ptr_ptee` (6.0 "
            "§7.9.5, p.279) and the `enter` modifier `automap` (6.0 "
            "§7.9.7, p.290). C only: the "
            "`for` compounds and the delimited `begin declare target` "
            "form.", ""]
    return out


def _programs_section(clang: list[dict]) -> list[str]:
    out = ["## Programs", "",
           "Each C program is a mechanical port of the Fortran program of "
           "the same atom (`offload.engine.f2c`, `offload.engine.c_gen`): same "
           "kernel, same oracle, same `RESULT ran_on_host=... check=...` "
           "line (printf), `omp_is_initial_device()` for the host flag. "
           "Every program is checked by `gcc -std=c11 -pedantic-errors "
           "-fsyntax-only` without `-fopenmp` (a stub `omp.h`; "
           "tests/engine/test_c.py) and by the C rules (a legal program violates "
           "none, an illegal one exactly its own).", ""]
    rows = []
    for v in c_gen.C_VERSIONS:
        ps = c_gen.all_c_programs(v)
        rows.append((f"{v // 10}.{v % 10}", sum(p.legal for p in ps),
                     sum(not p.legal for p in ps)))
    out += _table(("version", "legal programs", "illegal variants"), rows)
    out += ["### Edits (the Fortran oracle does not carry over)", ""]
    out += _table(("atom", "C program"),
                  [(f"`{a}`", r) for a, (r, _) in sorted(c_gen.C_EDITS.items())])
    out += ["### Labels (the port is faithful; its evidence is relabelled)",
            "", "Applied only where the Fortran program's evidence is "
            "audited; a C mutant that survives shows the effect is not "
            "observable by this program in C either, or not at all.", ""]
    out += _table(("atom", "evidence", "kind", "reason"),
                  [(f"`{a}`", e, k or "", _clip(r, 300))
                   for a, (e, k, r, _) in sorted(c_gen.C_LABELS.items())])
    out += ["### C-only illegal variants", ""]
    out += _table(("rule", "base atom"),
                  [(r, f"`{a}`") for r, (a, _) in
                   sorted(c_gen.C_ILLEGAL.items())])
    out += _clang_section(clang)
    return out


def _clang_section(clang: list[dict]) -> list[str]:
    out = ["### amdclang frontend (OpenMP legality opinion)", ""]
    if not clang:
        return out + ["Not run (`python3 -I tools/campaigns/c_coverage.py clang`).",
                      ""]
    out += ["`amdclang -fopenmp -fopenmp-version=<52|60> -fsyntax-only` on "
            "every C program (offload.engine.clang_oracle; AFAR drop). The "
            "spec decides: a legal program clang rejects is a clang gap or "
            "bug, an illegal one clang accepts is a missing diagnostic "
            "(restrictions need not be diagnosed).", ""]
    c = collections.Counter((r["version"], r["legal"],
                             {True: "accepted", False: "rejected",
                              None: r["stage"]}[r["ok"]]) for r in clang)
    rows = []
    for v in c_gen.C_VERSIONS:
        for legal in (True, False):
            rows.append((f"{v // 10}.{v % 10}", "legal" if legal else
                         "illegal", c[(v, legal, "accepted")],
                         c[(v, legal, "rejected")],
                         c[(v, legal, "timeout")] + c[(v, legal, "run")]))
    out += _table(("version", "programs", "clang accepts", "clang rejects",
                   "clang did not finish"), rows)
    bad = [r for r in clang if r["legal"] and r["ok"] is not True]
    expect = {p.id: p.expect for p in _programs()}
    if bad:
        out += ["Legal programs clang does not accept (a program marked "
                "*probe* must not compile: its error directive is fatal at "
                "compilation):", ""]
        out += _table(("program", "clang"),
                      [(r["program_id"] + (" *probe*" if expect.get(
                          r["program_id"], "result") != "result" else ""),
                        _clip("; ".join(r["errors"]) or r["stage"], 220))
                       for r in sorted(bad, key=lambda r: r["program_id"])])
    return out


def _rules_section() -> list[str]:
    import yaml
    from offload.engine.rules import default_rules
    rules = default_rules()
    by = collections.Counter(r.lang for r in rules)
    out = ["## Rules", "",
           f"{len(rules)} rule versions (one per rule and OpenMP version "
           f"of catalog/omp/rules.yaml): {by['both']} hold in both "
           f"languages, {by['f90']} are Fortran only (`lang: f90`), "
           f"{by['c']} are C only (`lang: c`, each with its spec sentence "
           "and citation).", ""]
    out += _table(("C rule", "check", "citation", "sentence"),
                  [(r.id, r.check, r.citation, _clip(r.text, 200))
                   for r in sorted(rules, key=lambda r: r.id)
                   if r.lang == "c"])
    out += ["Fortran-only rules: " + ", ".join(
        sorted(r.id for r in rules if r.lang == "f90")) + ".", ""]
    cov = yaml.safe_load(open(ROOT / "catalog/omp/rules_coverage.yaml"))
    tri = collections.Counter()
    for s in cov["sentences"]:
        if "c" in s:
            tri[(s["version"], s["c"]["class"])] += 1
    classes = sorted({k for _, k in tri})
    out += ["Triage of the C/C++ spec sentences (`c:` entries of "
            "catalog/omp/rules_coverage.yaml; `out_of_slice` includes the "
            "C++-only sentences):", ""]
    out += _table(("version",) + tuple(classes),
                  [(v,) + tuple(tri[(v, k)] for k in classes)
                   for v in sorted({v for v, _ in tri})])
    return out


def _audit_section() -> list[str]:
    out = ["## Mutation audit, Fortran and C", "",
           "Dispositions per atom (tests/data/oracle_audit_summary.json "
           "and tests/data/oracle_audit_summary_c.json; C audited on afar "
           "and cce19 at HSA_XNACK=0, -O2, the Fortran settings).", ""]
    f = json.loads(AUDIT_F.read_text())["versions"]
    c = json.loads(AUDIT_C.read_text())["versions"]
    for v in ("52", "60"):
        fv, cv = f.get(v, {}), c.get(v, {})
        disp = sorted({x["disposition"] for x in fv.values()} |
                      {x["disposition"] for x in cv.values()})
        cf = collections.Counter(x["disposition"] for x in fv.values())
        cc = collections.Counter(x["disposition"] for x in cv.values())
        out += [f"### {v[0]}.{v[1]}", ""]
        out += _table(("disposition", "Fortran", "C"),
                      [(d, cf[d], cc[d]) for d in disp])
        diff = []
        for a, x in sorted(cv.items()):
            fa = c_gen.fortran_atom(a)
            if fa in fv and fv[fa]["disposition"] != x["disposition"]:
                diff.append((f"`{a}`", fv[fa]["disposition"],
                             x["disposition"], _clip(x.get("reason", ""),
                                                      200)))
        if diff:
            out += ["Atoms whose disposition differs:", ""]
            out += _table(("atom", "Fortran", "C", "C reason"), diff)
    return out


def _outcomes_section() -> list[str]:
    tf, tc = _read_csv(TABLE_F), _read_csv(TABLE_C)
    out = ["## Outcomes per toolchain, Fortran and C", ""]
    if not tc:
        return out + ["No C support table (`python3 -I "
                      "tools/derive/support_table.py --lang c`).", ""]
    out += ["Legal programs at HSA_XNACK=1 (-O2), the outcome column of "
            "results/support_table.csv and results/support_table_c.csv "
            "(committed copy data/reports/c_support_table.csv; the C page "
            "data/reports/c-support-table.md).", ""]

    def key(r):
        return (r["version"], r["atom"], r["toolchain"])
    fmap = {key(r): r for r in tf if r["legal"] == "1" and r["xnack"] == "1"}
    crows = [r for r in tc if r["legal"] == "1" and r["xnack"] == "1"]
    outcomes = sorted({r["outcome"] for r in crows} |
                      {r["outcome"] for r in fmap.values()
                       if r["version"] in ("52", "60")})
    for v in ("52", "60"):
        rows = []
        for o in outcomes:
            cells = [o]
            for t in TOOLCHAINS:
                nf = sum(1 for r in fmap.values() if r["version"] == v and
                         r["toolchain"] == t and r["outcome"] == o)
                nc = sum(1 for r in crows if r["version"] == v and
                         r["toolchain"] == t and r["outcome"] == o)
                cells.append(f"{nf} / {nc}")
            rows.append(cells)
        out += [f"### {v[0]}.{v[1]} (Fortran / C)", ""]
        out += _table(("outcome",) + TOOLCHAINS, rows)
    diff = []
    for r in crows:
        fa = c_gen.fortran_atom(r["atom"])
        f = fmap.get((r["version"], fa, r["toolchain"]))
        if f and f["outcome"] != r["outcome"]:
            diff.append((r["version"], f"`{r['atom']}`", r["toolchain"],
                         f["outcome"], r["outcome"], _clip(r["reason"], 160)))
    pairs = collections.Counter((d[3], d[4]) for d in diff)
    out += [f"{len(diff)} atom/toolchain cells whose C outcome differs "
            "from the Fortran outcome of the same atom (the `for` "
            "compounds compared with the `do` ones), by pair:", ""]
    out += _table(("Fortran", "C", "cells"),
                  [(f, c, n) for (f, c), n in pairs.most_common()])
    out += ["The cells:", ""]
    out += _table(("version", "atom", "toolchain", "Fortran", "C",
                   "C reason"), sorted(diff))
    return out


def _baseline_section() -> list[str]:
    out = ["## omp_vv baseline, Fortran and C", ""]
    bf, bc = _read_jsonl(BASE_F), _read_jsonl(BASE_C)
    if not bc:
        return out + ["No C baseline yet.", ""]
    out += ["The omp_vv tests of the corpus run as in the Fortran "
            "baseline (same triage; the C tests compiled with the "
            "default OpenMP version, 5.1, or `-fopenmp-version` of a 5.2 "
            "or 6.0 spec directory, and `-I./ompvv -lm`). Headline mode "
            "(HSA_XNACK=1); pass / other.", ""]
    rows = []
    for name, b in (("Fortran", bf), ("C", bc)):
        for t in TOOLCHAINS:
            rs = [r for r in b if r["toolchain"] == t and r["xnack"] == 1
                  and r["repo"] == "omp_vv"]
            c = collections.Counter(r["status"] for r in rs)
            rows.append((name, t, len(rs), c["pass"],
                         ", ".join(f"{k} {n}" for k, n in sorted(c.items())
                                   if k != "pass")))
    out += _table(("language", "toolchain", "tests", "pass", "other"), rows)
    cmp_ = _read_csv(ROOT / "results" / "ompvv_compare_c.csv")
    if cmp_:
        flags = [r for r in cmp_ if r["flag"]]
        out += ["Atom-level cross-check (`python3 -I tools/derive/ompvv_compare.py "
                "--lang c`, results/ompvv_compare_c.csv): "
                f"{len(cmp_)} atom/toolchain/mode cells compared, "
                f"{len(flags)} flagged (candidates, not verdicts; see "
                "tools/derive/ompvv_compare.py):", ""]
        out += _table(("version", "toolchain", "atom", "ours",
                       "narrow suite pass/fail", "flag"),
                      [(r["version"], r["toolchain"], f"`{r['atom']}`",
                        r["ours"], f"{r['narrow_pass']}/{r['narrow_fail']}",
                        r["flag"]) for r in flags])
        out += ["Explained: target_parallel_loop is a probe-region program "
                "that fails through the shared declare target finding "
                "(clang-c-shared-declare-target-combined.c), which the "
                "suite test does not exercise; map.present on AFAR at "
                "HSA_XNACK=1 does not terminate (as in Fortran: the "
                "negative probe needs copy mode). Not investigated: map.always "
                "(our program is copy_mode_only, so its HSA_XNACK=1 pass is "
                "no evidence either way; the one narrow suite test fails "
                "on CCE) and map.iterator on AFAR (our program, oracle "
                "unaudited, passes; both narrow suite tests fail).", ""]
    return out


STATIC = """## Findings

C findings under data/findings/ (see data/findings/LOG.md):

- `clang-c-shared-declare-target-combined.c`: `shared(v)` of a declare
  target variable on a combined `target parallel` construct reads the
  host value (AFAR amdclang, CCE craycc 19/20/21; both are clang
  front ends).
- `cce-c-map-present-assert.c`: any `map(present, ...)` aborts in an
  assertion of the CCE C offload runtime (craycc 19/20/21).
- `afar-clang-requires-device-safesync-hang.c`: amdclang does not finish
  on `#pragma omp requires device_safesync` (6.0).
- `cce-c-parallel-for-in-target.c`: a `parallel for` nested in a target
  region runs one iteration with `schedule(static)` and loses the final
  values of lastprivate and linear items (CCE craycc 19/20/21); the C
  collapse, lastprivate, linear and schedule programs fail on CCE.
- `cce-c-dist-schedule-segv.c`: `dist_schedule(static)` without a chunk
  size crashes at HSA_XNACK=1 (CCE craycc 19/20/21).
- `cce-c-openmp45-device-link.c`: at `-fopenmp-version=45` craycc cannot
  link `omp_is_initial_device` in device code.
- `clang-c-linear-directive-name-hang.c`: `linear(x: for, step(2))` (6.0
  directive-name modifier) sends both clang front ends into an endless
  loop after twenty errors.

Also C-specific, not separate files: clang (both front ends) drops an
unknown clause, modifier or directive-name word with "extra tokens at the
end of '#pragma omp ...' are ignored" and compiles the rest (6.0
`replayable`, `transparent`, `nowait(do_not_synchronize)`, the `loop` of
`target loop` on CCE 19 and 20): the harness counts that as accepted_ignored. The
`device` clause runs on device 0 on CCE C as in Fortran, where ftn warns
that it ignores the clause and craycc is silent (wrong_answer in C,
accepted_ignored in Fortran).

## Rulings

- Separate C files (results/matrix_c.*, results/baseline_c.*,
  results/support_table_c.*, tests/data/oracle_audit_summary_c.json,
  data/reports/c-support-table.md); the
  Fortran files keep their names. Every support-table CSV gains a `lang`
  column, last, so existing column positions are unchanged.
- C programs get `-fopenmp-version=52|60` on every toolchain (the C front
  ends default to 5.1; Fortran keeps its flags).
- CCE C offload needs `-fopenmp-targets=amdgcn-amd-amdhsa
  -Xopenmp-target=amdgcn-amd-amdhsa -march=gfx942` (craycc `-fopenmp`
  alone builds host code; CCE 21 rejects `--offload-arch`).
- `main` plays the Fortran main program's part (e.g. the "program"
  scoping unit of requires-placement rules).
- C11 `_Atomic` has no spec sentence in the slice (atomic is outside
  it); `restrict` appears only in the declare reduction rule.
- `default(shared: allocatable)`, the map ref-modifiers and the enter
  `automap` modifier are Fortran only; the C forms omit them.
- A `begin declare target` ... `end declare target` region is not a
  nesting parent of the directives inside it.
- Faithful ports are kept where clang mis-compiles them (shared declare
  target variables on combined constructs): the failure is the
  toolchain's, and is a finding.
- Fortran oracles whose weakness the C audit exposed are left unchanged
  in Fortran (Fortran results unchanged by this task); the C programs
  carry the relabelling.
- The omp_vv C baseline compiles a test of the 4.5, 5.0 and 5.1 spec
  directories with the compiler's default (5.1), as the Fortran baseline
  uses the defaults, and a 5.2 or 6.0 test with `-fopenmp-version=52|60`.
  (A first run with the directory's version for every test failed 115
  tests on CCE because craycc at `-fopenmp-version=45` does not link
  `omp_is_initial_device` in device code: a finding.)
"""


def cmd_report(args) -> int:
    clang = _read_jsonl(CLANG)
    lines = ["# C coverage", "",
             "Generated by `python3 -I tools/campaigns/c_coverage.py report`. OpenMP "
             "5.2 and 6.0 target offload in C (C11, `#pragma omp`) on the "
             "same atoms, output contract and audit process as Fortran. "
             "OpenACC C and C++ are out of scope.", ""]
    lines += _atoms_section()
    lines += _programs_section(clang)
    lines += _rules_section()
    lines += _audit_section()
    lines += _outcomes_section()
    lines += _baseline_section()
    lines += STATIC.splitlines()
    OUT.write_text("\n".join(lines).rstrip() + "\n")
    print(f"-> {OUT}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("clang")
    c.add_argument("--workers", type=int, default=6)
    sub.add_parser("report")
    a = ap.parse_args(argv)
    return {"clang": cmd_clang, "report": cmd_report}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
