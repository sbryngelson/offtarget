#!/usr/bin/env python3
"""Write results/rules-coverage.md.

Run from the project root: python3 -I tools/derive/rules_coverage.py

Reads catalog/omp/rules_coverage.yaml (the hand classification of every
extracted restriction sentence), catalog/omp/rules.yaml (the rules) and
tests/data/combination_matrix.json (tools/campaigns/combination_matrix.py). The prose
sections are in this script.
"""
import json
import sys
from collections import Counter, defaultdict
from itertools import groupby
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from offload.engine import spec_text  # noqa: E402
from offload.engine.combos import LEAVES  # noqa: E402
from offload.engine.coverage import CLASSES, SCOPE, load_coverage  # noqa: E402
from offload.engine.rules import PREDICATES, RULES_PATH  # noqa: E402

OUT = ROOT / "results" / "rules-coverage.md"
MATRIX = ROOT / "tests" / "data" / "combination_matrix.json"

INTRO = """\
# Restriction coverage

Of the compliance-catalog slice. The maintainer's priority: a "wrong
answer" is a compiler finding only if the program is legal, so every legal
program the generator emits must respect every static restriction of the
spec, not only the 56 rules of batch 1. This
document is the inventory of the restriction sentences of OpenMP 5.2 and
6.0 for the slice, how each is handled, the directive combination matrix,
and the re-validation of the generated programs.

## Summary

* **Inventory**: {n} candidate sentences ({n52} at 5.2, {n60} at 6.0) from
  {nsec} sections, each classified by hand (table below):
  {classes}.
* **New rules**: {nnew} rules ({nids} version entries) in
  `catalog/omp/rules.yaml` (now {nall} rules), each with its verbatim
  sentence (test-checked to occur in the cited section), a predicate in
  `offload/engine/rules.py` and a legal and an illegal unit program in
  `tests/engine/test_generators.py` (CASES). All `status: provisional`. Five batch 1
  predicates were extended (ledger below).
* **Combination matrix**: every order of 2 and 3 distinct leaves of
  {{target, teams, distribute, parallel, do, simd, loop}} (6.0: and
  workdistribute), as one compound directive and as explicitly nested
  constructs ({ncells} programs): the catalog (grammar and rules) agrees
  with an independent table of the spec's compound-name and nesting rules
  on every program except 12 6.0 compound names that Appendix D derives and
  the grammar does not know (stricter, not a legality risk). AFAR's
  frontend (`-fopenmp-version` 52/60, parse and semantic checks) **never
  rejects a program the catalog accepts**; it accepts {nflang} programs the
  catalog rejects (listed below: its checks are weaker).
* **Generated programs**: every legal program of both versions was
  re-validated against the full rule set. Two generator bugs were found
  and fixed (a runtime routine called directly in a teams region; an
  allocate clause without an allocator in a target region); 46 program
  sources changed (list below) and their matrix rows need a rerun.

## How the sentences were collected

`offload/engine/coverage.py` (`SCOPE`, `extract`) reads the page-tagged spec
text (`offload.engine.spec_text`, `results/spec_cache/openmp-<v>.txt`):

* for every construct, clause and directive of the slice
  (`catalog/omp/skeleton.yaml` slice directives and `slice_atoms`; scope
  "slice") and every construct a generated program uses outside the slice
  (single, task, taskwait, ordered, scan, declare simd, declare mapper,
  depobj, threadprivate, error; scope "used"), each bullet or paragraph of
  the section's Restrictions subsections, with its language banner;
* for the sections read whole (5.2 §4.4.1, §5.1.1, §17.1 to §17.5; 6.0
  §6.4.1, §7.1.1, §19.1 to §19.3: canonical loop nest form, predetermined
  data-sharing, nesting of regions, compound names and clauses), every
  sentence containing one of: must, shall, cannot, may not, at most
  once/one, only, restricted, not permitted, strictly nested, closely
  nested, may be, required, not allowed.

The script only finds candidates; every one was then classified by hand
in `catalog/omp/rules_coverage.yaml`. `tests/engine/test_generators.py` checks that
the YAML classifies exactly the extracted sentences, that each occurs
verbatim (whitespace aside) in its section, that its page lies in the
section, and that every referenced rule exists at that version. The
properties tables (unique, required, exclusive clauses and clause sets)
are the grammar's; the clause-set
sentences of 5.2 §3.2 / 6.0 §5.2 found three sets the grammar did not
enforce (target update {{to, from}}, scan, depobj), now rule
`clauseset-clause-001`. Two sentences the keyword scan cannot find were
encoded as well: "A scalar variable of integer type." (the canonical loop
variable, 5.2 §4.4.1 p.89, 6.0 §6.4.1 p.200: `loopvar-loop-003`) and the
6.0 Fortran intervening-code list (`cycle-loop-001`).

Classes: {classdefs}.

Sections in scope: {scope}.
"""

POINTS = """\
## Points for the maintainer

1. **6.0 worksharing nesting (`worksharing-nesting-001` at 6.0).** 6.0 has
   no normative "may not be closely nested" sentence; Appendix C
   (informative) states it and calls it a consequence of §13 ("Each
   work-distribution region must be encountered by all threads in the
   binding thread set or by none at all"), which the rule cites. A
   closely nested worksharing construct in a one-thread team is conforming
   by §13's letter and is still flagged.
2. **5.2 declare target placement (`declaretarget-placement-003`).** 5.2
   §7.8.1 (p.206): "If no clauses are specified or if a device_type clause
   is specified, the directive must appear in a specification part of a
   subroutine subprogram, function subprogram or interface body." Read
   literally it would confine `declare target enter(x) device_type(any)` in
   a module to subprograms; the rule applies it only to a directive with no
   list (no extended list and no enter/to/link clause), the 6.0
   declaration-associated form.
3. **6.0 compound names beyond the skeleton.** 6.0 §19.1 and its Appendix
   D grammar allow `teams parallel`, `parallel target`, `parallel simd`,
   `target teams parallel`, `teams parallel do`, `parallel target loop`
   and others (12 among the matrix's 2- and 3-leaf orders). Neither the
   catalog grammar (TableGen skeleton) nor AFAR's parser accepts them. They
   are legal programs the generator cannot emit; adding them is a grammar
   decision (spec override), not a restriction.
4. **A loop construct without an order clause is order(concurrent)** (5.2
   §11.7 p.257, 6.0 §13.8 p.423: "as if the order clause is present"), so
   `order-nesting-001` and the new `order-nesting-002` now apply to every
   loop construct: no target, do, task ... inside a loop region (5.2: at
   any depth; 6.0: strictly nested), and no runtime routine call in it.
   AFAR accepts such programs (matrix).
5. **Orphaned constructs of a main program** (`distribute-nesting-001`,
   `loop-nesting-002`): in a main program no caller can place an orphaned
   distribute or loop bind(teams) in a teams region, so it is now flagged.
6. **Runtime routines in a teams region.** 5.2 §10.2 lists
   omp_get_num_teams() and omp_get_team_num() as the only routine regions
   that may be strictly nested in a teams region; 6.0 §12.2 allows the
   teams-nestable routines, which are exactly those two (§22.1, §22.3;
   omp_is_initial_device, §24.9, is not one). The generator called
   omp_is_initial_device() directly in teams regions; fixed (below).
7. **Grammar findings (not changed here).** `induction` is missing on the
   `do` and `simd` leaves at 6.0 (6.0 §13.6.2 and §12.4 list it; the
   compounds have it), the 6.0 `+` directive-name separator is not
   accepted, and `copyprivate` is rejected on `end single`. All three make
   the grammar stricter, not more permissive.
8. **6.0 `aligned`: "Each list item must be an array"** (6.0 §7.12 p.301,
   Fortran). A C_PTR scalar, allowed at 5.2, is not allowed at 6.0
   (`aligned-clause-002`); a libgomp test (aligned1.f03) is flagged at 6.0.
"""

LEDGER = """\
## Changes to batch 1 rules (ledger)

* `teams-nesting-003`: also a runtime routine call other than
  omp_get_num_teams / omp_get_team_num in a teams body outside nested
  constructs (same sentence: "... omp_get_num_teams() regions, and
  omp_get_team_num() regions are the only OpenMP regions that may be
  strictly nested inside the teams region", 5.2 §10.2 p.232; 6.0 §12.2
  p.396, teams-nestable routines).
* `order-nesting-001`: a construct with a loop leaf and no order clause
  counts as order(concurrent) (5.2 §11.7 p.257: "If the order clause is not
  present, the behavior is as if an order clause that specifies concurrent
  appeared"; 6.0 §13.8 p.423); separating and declarative directives (scan)
  are not counted as constructs.
* `target-clause-001`: also calls to runtime routines in the region (the
  same sentence: "no OpenMP constructs or calls to OpenMP API runtime
  routines are allowed inside the corresponding target region").
* `distribute-nesting-001`, `loop-nesting-002`: an orphaned construct of a
  main program is flagged (point 5).
* `requires-clause-001`: a 6.0 entry (the same sentence, 6.0 §10.5.1.1
  p.357).
* `worksharing-nesting-001` has a 6.0 entry (point 1).
* The batch 1 unit cases of `reduction-clause-002/003/004` now include the
  scan directive that every inscan list item needs (`scan-clause-002`).

Parser (`offload.engine.rules.parse_program`), extended minimally and tested
through the CASES: the bounds (lb, ub, incr) and the intervening statement
count of each loop of a DO nest (`Assoc.loop_bounds`,
`Assoc.intervening`), the intrinsic type keyword, array spec and SAVE
attribute of declared names (`vtypes`, `arrays`, `saved`), the kind and
name of each program unit and subprogram (`units`) and the modules of USE
statements (`use_modules`).
"""

VALIDATION = """\
## Generated programs (step 4)

Every legal program of both versions (`offload.engine.gen.all_programs`) was
checked against the full rule set. Findings and their fixes:

* **Generator bug: omp_is_initial_device() in a teams region** (rule
  `teams-nesting-003`, point 6). Nine programs per version reported the
  device with `host_flag = merge(1, 0, omp_is_initial_device())` directly
  in a teams region (team 0's branch). Fix
  (`offload.engine.gen_templates.TEAMS_FLAG`): the report runs in a one-thread
  parallel region inside the teams region (`!$omp parallel num_threads(1)`;
  parallel is teams-nestable). The oracle is unchanged.
* **Generator bug: allocate without an allocator in a target region**
  (rule `allocate-clause-002`: "allocate clauses that appear on a target
  construct or on constructs in a target region must specify an
  allocator-simple-modifier or allocator-complex-modifier unless a requires
  directive with the dynamic_allocators clause is present in the same
  compilation unit", 5.2 §6.6 p.179, 6.0 §8.6 p.313). The `allocate(t)` and
  `allocate(align(8): t)` programs now carry `!$omp requires
  dynamic_allocators` and no longer need `uses_allocators` (5.2 §13.8
  p.286). CCE 19 does not implement dynamic_allocators: a new report
  confound (`offload.engine.report.CONFOUNDS`) keeps that rejection from
  counting against allocate. The oracle audit's mutants of the allocator
  forms (which remove the allocator) get the same requires
  (`offload.engine.mutate`), so they stay conforming.
* No rule was weakened to make a program pass. Two predicates were
  narrowed after the corpus check showed false positives, each against its
  sentence: `target-map-002` counts a mapped part of an element (`s%a%b`
  mapped, `s%a%b` referenced), and the storage rules do not treat a
  function name (its result variable) as a variable.

Programs whose source changed (46; their matrix rows need a rerun, legal
and illegal variants derived from them):

{changed}

The oracle audit was re-run in full after the change
(data/reports/oracle-audit.md, tests/data/oracle_audit_summary.json).

### Corpus check of the new rules

The new rules were run over the Fortran corpus (OpenMP Examples, OpenMP
V&V, AOMP, the GCC and the ROCm/LLVM flang test suites; read as text). In
the Examples (the 6.0 `assumption.2.f90` was a false positive of the
extended order-nesting-001, fixed: `assume` is an informational directive)
and V&V nothing fires except `declarative-placement-001` on two V&V tests
that put `!$omp requires` before the USE statements (genuine: 5.2 §8.2
p.211, 6.0 §5.1 p.156). In the compiler test suites the findings sit on
expected-error lines, or are genuine non-conformance the compilers accept
(e.g. `teams distribute simd linear(x)` of a non-loop variable in a flang
lowering test, distribute-clause-002; GCC's `omp_get_num_teams_dim`
extension called in a teams region).
"""


def esc(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def rules_added():
    data = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))["rules"]
    stems = [e["id"] for e in data]
    k = stems.index("worksharing-nesting-001")
    return [e for e in data[k:] if e["check"] == "static"]


def matrix_section() -> list[str]:
    cells = json.loads(MATRIX.read_text())
    meta, rows = cells["meta"], cells["cells"]
    out = ["## Directive combination matrix (step 3)", "",
           "`offload/engine/combos.py` builds, for every order of 2 and 3 "
           "distinct leaves, a compound-directive program (`!$omp a b c` "
           "over a DO loop when a leaf is loop-associated) and a nested one "
           "(each construct directly inside the previous; a loop "
           "construct's DO loop holds the next). Three verdicts per "
           "program:", "",
           "* **spec**: an independent table. Compound names: 5.2 §17.3 "
           "(\"If directive-name-A is ... then directive-name-B may be "
           "...\"); 6.0 the Appendix D grammar of §19.1 restricted to these "
           "leaves, with unique leaves and a conforming nesting. Nesting: "
           "the closest enclosing construct each leaf allows (`DIRECT`), "
           "the region-wide rules (simd, workdistribute, a device construct "
           "in a target region, and at 5.2 everything in a loop region), "
           "and the outermost construct of a main program (an orphaned "
           "distribute, workdistribute, or loop without bind is not "
           "conforming there).",
           "* **ours**: the grammar parses every directive and "
           "`offload.engine.rules.violations` is empty.",
           f"* **flang**: {meta['tool']}, run {meta['date']}.", ""]
    agg = Counter((r["version"], r["form"], r["spec"], r["ours"],
                   r["flang"] == "ok") for r in rows)
    out += ["| version | form | spec legal | ours legal | flang accepts | "
            "programs |", "|---|---|---|---|---|---|"]
    for (v, f, s, o, fl), n in sorted(agg.items()):
        yn = {True: "yes", False: "no"}
        out.append(f"| {v // 10}.{v % 10} | {f} | {yn[s]} | {yn[o]} | "
                   f"{yn[fl]} | {n} |")
    out += ["", "Every 'spec' and 'ours' verdict agrees except the 6.0 "
            "compound names of owner point 3 (spec yes, ours no). **No "
            "program that the catalog accepts is rejected by flang** (the "
            "definite-bug direction is empty).", ""]
    # 2-level grid per version
    for v in (52, 60):
        ls = LEAVES[v]
        by = {(tuple(r["order"]), r["form"]): r for r in rows
              if r["version"] == v and len(r["order"]) == 2}
        out += [f"### Two leaves, OpenMP {v // 10}.{v % 10}", "",
                "Row: outer (first) leaf; column: inner (second) leaf. `c`: "
                "the compound name is legal, `n`: the nesting is legal "
                "(spec, and ours agrees), `-`: neither; `!` marks a cell "
                "where flang accepts a program the spec and the catalog "
                "reject.", "",
                "| | " + " | ".join(ls) + " |",
                "|---|" + "---|" * len(ls)]
        for a in ls:
            cells_ = []
            for b in ls:
                if a == b:
                    cells_.append(" ")
                    continue
                c, n = by[((a, b), "combined")], by[((a, b), "nested")]
                s = ("c" if c["spec"] else "") + ("n" if n["spec"] else "")
                bang = any(not r["ours"] and r["flang"] == "ok"
                           for r in (c, n))
                cells_.append((s or "-") + ("!" if bang else ""))
            out.append(f"| **{a}** | " + " | ".join(cells_) + " |")
        out.append("")
    for v in (52, 60):
        for form in ("combined", "nested"):
            legal = [" ".join(r["order"]) for r in rows
                     if r["version"] == v and r["form"] == form
                     and len(r["order"]) == 3 and r["spec"]]
            out += [f"**Three leaves, {form}, legal at "
                    f"{v // 10}.{v % 10}** ({len(legal)}): "
                    + ", ".join(f"`{x}`" for x in legal) + ".", ""]
    out += ["### Where flang and the catalog disagree", "",
            "flang rejects, ours accepts: none.", "",
            "flang accepts, ours (and the spec) reject: AFAR's frontend does "
            "not check these restrictions:", ""]
    groups = defaultdict(list)
    for r in rows:
        if not r["ours"] and r["flang"] == "ok":
            key = r["ours_why"].split(",")[0].split(":")[0]
            groups[key].append(f"{r['version']}/{r['form'][0]} "
                               f"`{' '.join(r['order'])}`")
    for key, xs in sorted(groups.items()):
        out.append(f"* `{key}` ({len(xs)}): " + ", ".join(xs))
    out += ["", "(`52/n`: 5.2, nested form; `c`: compound form.) The "
            "`OMP52-distribute-nesting-001` and `loop-nesting-001` cells "
            "are orphaned constructs of a main program; the "
            "`order-nesting-001` cells put target or do in a loop region; "
            "the 5.2 `target loop` compound is a 6.0 name.", "",
            "6.0 compound names the spec allows and both the catalog and "
            "flang reject: " + ", ".join(
                f"`{' '.join(r['order'])}`" for r in rows
                if r["version"] == 60 and r["form"] == "combined"
                and r["spec"] and not r["ours"]) + ".", ""]
    return out


def main() -> int:
    rows = load_coverage()
    new = rules_added()
    cells = json.loads(MATRIX.read_text())["cells"]
    classes = Counter(r["class"] for r in rows)
    changed = json.loads((ROOT / "tests" / "data"
                          / "changed_programs_oop.json").read_text())
    scope = "; ".join(
        f"{v}: " + ", ".join(f"§{n}" + (" (used)" if s == "used" else "")
                             for n, _, s in sorted(
                                 SCOPE[v], key=lambda e: [int(x) for x in
                                                         e[0].split(".")]))
        for v in SCOPE)
    head = INTRO.format(
        n=len(rows), n52=sum(r["version"] == "5.2" for r in rows),
        n60=sum(r["version"] == "6.0" for r in rows),
        nsec=sum(len(s) for s in SCOPE.values()),
        classes=", ".join(f"{k} {classes[k]}" for k in CLASSES),
        nnew=len(new), nids=sum(len(e["spec"]) for e in new),
        nall=len(yaml.safe_load(RULES_PATH.read_text())["rules"]),
        ncells=len(cells),
        nflang=sum(not r["ours"] and r["flang"] == "ok" for r in cells),
        classdefs="; ".join(f"**{k}**: {v}" for k, v in CLASSES.items()),
        scope=scope)
    out = [head, POINTS, LEDGER]
    out += ["## Rules added since the first batch", "",
            "| rule | versions | checks (predicate) | citation |",
            "|---|---|---|---|"]
    for e in new:
        doc = " ".join((PREDICATES[e["predicate"]].__doc__ or "").split())
        cites = "; ".join(s["citation"] for s in e["spec"].values())
        vers = ", ".join(f"{int(v) // 10}.{int(v) % 10}" for v in e["spec"])
        out.append(f"| `{e['id']}` | {vers} | {esc(doc)} | {cites} |")
    out += ["", VALIDATION.format(changed=", ".join(
        f"`{x}`" for x in changed)), ""]
    out += matrix_section()
    out += ["## Inventory", "",
            "One row per extracted sentence, verbatim. Rule: the rule stem "
            "(`OMP52-` / `OMP60-` prefix per version) or `grammar`; for "
            "deferred sentences the reason, for the others a note.", ""]
    secs = {v: {s.number: s.title for s in spec_text.sections(v).values()}
            for v in ("5.2", "6.0")}
    for (v, sec), group in groupby(rows, key=lambda r: (r["version"],
                                                        r["section"])):
        group = list(group)
        out += [f"### {v} §{sec} {secs[v][sec]}" + (
            " (used by generated programs)" if group[0]["scope"] == "used"
            else ""), "",
            "| p. | lang | sentence | class | rule / reason |",
            "|---|---|---|---|---|"]
        for r in group:
            ref = r.get("rule", "")
            ref = f"`{ref}`" if ref else ""
            extra = r.get("why") or r.get("note") or ""
            ref = f"{ref} {esc(extra)}".strip()
            out.append(f"| {r['page']} | {r['language']} | {esc(r['text'])} "
                       f"| {r['class']} | {ref} |")
        out.append("")
    OUT.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(rows)} sentences, {len(new)} new rules)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
