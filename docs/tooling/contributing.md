# Contributing

This page is the maintainers' reference for working on the tooling; it assumes the project's machines (Tuolumne,
Tioga, wingtip) and the git-ignored `results/` and `spec/`. An outside contributor starts from
[CONTRIBUTING.md](../../CONTRIBUTING.md) instead. It covers the layout, the standing rules that tests enforce, and the procedures for common changes: running tests, regenerating artifacts, adding a finding, a compiler or a campaign, and reducing a failing program. [setup.md](setup.md) covers setup.

## Scope and layout

The repository holds legal OpenMP and OpenACC device-offload programs (C and Fortran), the compiler issues found by running them on AMD (AFAR, Cray CCE), NVIDIA (NVHPC) and GCC offload toolchains, and a public issue site built from the findings. Only device offload is in scope.

A program counts as legal when the project's rules ([`offload/engine/rules.py`](../../offload/engine/rules.py)) and a front end of another compiler family both accept it. The compiler under test never decides legality. A compiler issue counts as a finding after it passes the reproduction gate and, where it makes sense, a one-change control (a variant of the program that differs by one change and passes).

The machines below are the maintainers' own. The catalog names them by hardware. Your own machines go in your local settings (see "Your machines and compilers" in [setup.md](setup.md)).

| machine | hardware | scheduler | access |
|---|---|---|---|
| Tuolumne | MI300A | flux | login nodes; compute nodes through flux |
| Tioga | MI250X | flux | `ssh tio` |
| wingtip | 4x A100 | none, shared | `ssh wingtip` |
| a Slurm cluster | MI300X (gfx942), MI350X (gfx950) | Slurm, whole nodes | `ssh amd`; AFAR only, copy memory, no XNACK |

| path | contents |
|---|---|
| `catalog/` | data: `omp/` and `acc/` grammar, rules and claims; `toolchains.yaml`, `machines.yaml`, `legality_witness.yaml`, `canaries.yaml`; `standing_rules_baseline.yaml`; `toolchain_names_allowlist.yaml` |
| `offload/engine/` | library: generators (`gen.py`, `c_gen.py`, `acc_gen.py`, `oop_gen.py`, `nested_gen.py`, `fuzz*.py`, `stress*.py`), `rules.py`, `prerun.py` (legality check), `harness.py` (compile and run), `gate.py` (reproduction gate), `toolchains.py`, `campaign.py` (campaign interface) with `campaigns/`, `confirm/` (verdict engine), `site/` |
| `tools/` | command-line entry points (`campaign.py`, `confirm.py`, `fuzz.py`, `gate.py`, `reduce.py`, `new_finding.py`, `regenerate.py`, `site_build.py`, `site_publish.sh`, ...), `jobs/` (job scripts) |
| `data/findings/` | one small program per compiler issue, with a header; `index.yaml`; `README.md`; `AUTHORING.md` |
| `data/vendor/` | draft report packets (`amd/`, `hpe/`, `nvidia/`) and `checks/`, which re-runs the cases per compiler (`run_checks.py`) |
| `docs/tooling/` | how-to pages: [setup](setup.md), [regenerate](regenerate.md), [wingtip](wingtip.md), [confirm](confirm.md), [site](site.md), [publishing](publishing.md), [dashboard-publish](dashboard-publish.md), [toolchains](toolchains.md), [nested-data](nested-data.md), [expected-behaviour](expected-behaviour.md) |
| `site/` | static site template (`templates/`, `static/`) and its committed inputs (`inputs/`, from `tools/site/site_inputs.py`) |
| `.github/workflows/site.yml` | builds, checks and deploys the site to GitHub Pages (CPU only) |
| `tests/` | pytest; `data/` holds captured compiler messages and audit summaries |
| `data/bench/` | benchmark sets of real-world programs; sealed sets are never read |
| `data/index/` | corpus index and vendor-claim snapshots |
| git-ignored | `results/` (measurements), `corpus/` (cloned test suites), `spec/` (specification PDFs); [setup.md](setup.md) says how to get them |

Work in your own git worktree. A worktree links `results/`, `corpus/` and `spec/` to the shared directories. Git ignores those links, so they are never committed.

## Standing rules

Rules a program can check are tests in `tests/cluster/test_standing_rules.py`. A failing test names the rule and the offender. Each rule is mechanical (a test decides), partly checked (a test covers what a program can see, and the rest is yours) or human-only. A row is a recorded result line of a run.

| rule id | rule | class | check |
|---|---|---|---|
| `no-ompvv-oracle` | omp_vv is untrusted: never a witness or an oracle | mechanical | no witness file, checker or legality line names omp_vv; behaviour in `tests/confirm/test_confirm_legality.py` |
| `no-gcc-witness` | gfortran and `gcc -fopenmp` are never a legality witness; GCC is a compiler under test only | mechanical | no checker command, script command line or finding `legality:` line uses GCC; behaviour in `tests/confirm/test_confirm.py` |
| `no-own-checker` | a compiler under test is never its own legality checker | mechanical | checkers in `catalog/machines.yaml` and `legality_witness.yaml` against the families of `catalog/toolchains.yaml`; a finding's legality line does not name a front end of its own family. Write "not counted" or "is the compiler under test" when you name such a front end |
| (shared front end) | AFAR and upstream llvm share a front end: neither witnesses the other | partly | `test_shared_front_ends_are_never_each_others_witness`; the confirmer enforces it in code |
| (gate) | a finding needs the gate, environments a to d | partly | `offload/engine/gate.py` judges; `gate-c-other-node` checks the stored rows |
| `gate-c-other-node` | the gate's environment (c) runs on another node (wingtip: another GPU) than (a) | mechanical | reads `results/gate/*/reruns`; skipped without `results/` |
| (control) | add a one-change control where it makes sense | human-only | judgement |
| (login nodes) | no compilers and no tests on login nodes | human-only | run on a compute node or the wingtip lane |
| `pdebug-batch` | batch work goes to pbatch; pdebug is interactive only | mechanical | scans `tools/**/*.sh`, Python strings and comments, `docs/*.md`, `vendor` |
| `pdebug-job-name` | a pdebug `flux run` or `flux alloc` carries `--job-name=compile-...` | mechanical | same scan |
| `pdebug-chained` | one foreground pdebug job at a time, never two in one line, script, document block or loop | mechanical | same scan |
| `bounded-waits` | every wait is bounded | partly | a shell `while true`, `while :`, `until` or any sleeping loop needs a deadline (`date +%s`, `$SECONDS`, `timeout`, a counter); a Python `while True` that sleeps needs a clock or attempt counter. Wrap `flux job attach` and ssh in `timeout` yourself |
| `wingtip-cap` | wingtip work goes through the cap scripts; the cap is never softened | mechanical | `tests/cluster/test_lanes.py` (everything under `tools/`) and `test_rule_wingtip_cap` (the vendor packet) |
| (wingtip etiquette) | free GPUs only, at most 4 compiles, `nice` | human-only | implemented in `tools/jobs/run_wingtip*.sh` |
| (lane reuse) | a wingtip lane with running work is never reused by another step | human-only | each step re-syncs the lane with `rsync --delete`; see [wingtip.md](wingtip.md) |
| (sealed sets) | sealed unscored sets stay on Tuolumne and are never read | partly | the copy side is tested (`tests/cluster/test_lanes.py`, `tests/bench/test_holdout_exposure.py`, `tests/bench/test_harvest_known.py`); scans never walk `data/bench/` |
| `no-shared-tree-git` | never `git stash`, `checkout`, `restore`, `reset` or `clean` in the shared tree | partly | no `tools/` or `offload/engine/` script runs one without `-C` to another tree |
| (worktree) | work in your own worktree; do not regenerate or install shared artifacts from it | human-only | |
| `no-tracked-symlink` | no tracked symlink at the repository root or with an absolute target | mechanical | the tree of HEAD; `.gitignore` names `/results`, `/spec`, `/corpus` |
| `no-ai-attribution` | no AI attribution lines in commit messages | mechanical | scans `git log`; skipped without history |
| `no-external-filing` | never file, report or post anything externally | partly | no `tools/` or `offload/engine/` code runs `gh` issue, pr or api writes, `curl` with a body, a mail command, `git push`, `requests.post` or `smtplib`. Reading with `gh issue list` is allowed |
| (vendor drafts) | vendor report drafts are never published | human-only | |
| `no-first-person` | site copy has no first person | mechanical | templates, scripts, strings in the site builder, every published `site:` field, the text of every built page |
| (site wording) | generated titles read "appears to behave incorrectly" or "appears not to support" | partly | `tests/site/test_site.py::test_generated_title_when_no_header_title`; hand-written text is yours |
| `site-cell-words` | cell words are exactly: behaves incorrectly, not supported, correct, unknown, n/a, fails another way | mechanical | `STATE_WORD` in `tools/site/site_build.py` and the word tables of `issues.js` and `canuse.js` |
| `no-module-pipe` | `module load` is never piped | mechanical | a pipe runs it in a subshell and the environment is lost |
| (toolchain list) | the toolchain list lives in `catalog/toolchains.yaml` only | mechanical | `tests/cluster/test_reports.py::test_no_hard_coded_toolchain_outside_the_catalog` |

The toolchain-list test scans Python strings, shell commands and JavaScript under `offload/engine/`, `tools/`, `site/` and `data/vendor/checks` for registered toolchain ids and versions. It allows the loader, the generated files and the ratchet `catalog/toolchain_names_allowlist.yaml` (one reason per file). Ids that are also family names (`afar`, `nvhpc`) are not scanned.

The human-only rules without a row id are small commits with terse messages, tests first, pushing only your own branch, and never merging to master.

### The ratchet

Offenders that existed when a rule's test was written are listed in `catalog/standing_rules_baseline.yaml`. Each entry has a rule, an offender and a reason. A rule's test fails on an offender that is missing from the file, and on an entry that is fixed but still listed. Fix new offenders and delete fixed entries, and never add entries. The file currently holds 3 `pdebug-job-name` entries and 1 `no-gcc-witness` entry.

Run the rule tests:

    WINGTIP_LANE=<lane> tools/lanes/wingtip_offline.sh tests tests/cluster/test_standing_rules.py

## Run the test suite

This is the maintainers' route; elsewhere, "Run the tests" in [CONTRIBUTING.md](../../CONTRIBUTING.md) applies.
Compilers and tests do not run on login nodes. CPU tests run on wingtip through the offline lane.

1. Pick a lane name that only you use, for example `export WINGTIP_LANE=mylane`. Every step re-syncs its lane with `rsync --delete`, so never run a step in a lane that has work running. Long GPU runs get their own lane.
2. From your worktree on a Tuolumne login node, run `tools/lanes/wingtip_offline.sh tests [tests/test_x.py ...]`. The login node only copies files and starts ssh. The command copies the tree and the inputs the step names (`tools/lanes/wingtip_offline.yaml`), runs `pytest -m "not gpu"` with xdist inside `compliant.slice`, and stops at the step's `limit` (3600 s for `tests`).
3. `tools/lanes/wingtip_offline.sh --list` shows the steps, and `--dry-run STEP` prints the plan without using ssh. A test that needs a git-ignored file skips and names the file. If the file should be an input of the `tests` step, the suite fails until you add it to `tools/lanes/wingtip_offline.yaml`.
4. The log `results/offline/tests.<lane>.<time>.log` has the full tracebacks. After a pass, `results/offline/suite/<lane>.<time>/` holds `wingtip.txt` (the tests that ran), `tuolumne.txt` (the tests left for Tuolumne), `failed.txt` and `summary.json`.
5. The tests left for Tuolumne (AFAR front end, GPU, application clones) run on a compute node as one foreground job:

       flux run -q pdebug -N1 -n1 -t 10m --job-name=compile-test-<what> python3 -I -m pytest $(cat results/offline/suite/<lane>.<time>/tuolumne.txt)

   Long runs go to pbatch, for example `flux batch -q pbatch -N1 -t 60 --setattr=thp=always --output=pytest.log --wrap 'python3 -I -m pytest -q'`. Allow about ten minutes of queue wait on pdebug. On Tuolumne, pass sealed-set tests by function-level id, without the `[...]` part.
6. Most ids in `tuolumne.txt` also run on Tioga. `tools/lanes/run_tioga_suite.sh results/offline/suite/<lane>.<time>` writes `tioga/tuolumne.txt`, which lists the ids that must still run on Tuolumne (MI300A device runs and sealed-set tests).

If `tests/cluster/test_reports.py` fails, a regenerated batch is stale. Rerun it as described next.

## Regenerate saved artifacts

[regenerate.md](regenerate.md) lists every generated file, its inputs and its currency check.

| command | effect |
|---|---|
| `python3 -I tools/regenerate.py --list` | the steps, with inputs and outputs |
| `python3 -I tools/regenerate.py --check [STEP ...]` | rebuilds each offline artifact, compares with the stored copy, writes nothing, exits 1 when stale |
| `tools/lanes/wingtip_offline.sh regen-check` | the same check on wingtip |
| `python3 -I tools/regenerate.py --offline` | reruns the offline steps; do not run it from a worktree on shared `results/` |

Measurement steps need a GPU. Use flux on Tuolumne (pbatch), `ssh tio` for Tioga, and `tools/jobs/run_wingtip.sh` for wingtip. Offline steps run on wingtip as `tools/lanes/wingtip_offline.sh [--env K=V] STEP`. The steps include `confirm-batch`, `widen-batch`, `confirm-decide`, `confirm-index`, `confirm-backlog`, `confirm-triage`, `confirm-validate`, `citations`, `site-inputs`, `site-build`, and `--list` shows the rest. `--env` passes only the variables a step lists under `env:` in `tools/lanes/wingtip_offline.yaml`. `--env INSTALL=1` installs `confirm-batch` output into shared `results/`. `--no-pull` leaves a step's outputs on wingtip, and a failed step copies nothing back.

After you edit a hand-written input (`catalog/*.yaml`, `data/findings/index.yaml`), the "Hand-edited inputs" section of [regenerate.md](regenerate.md) names the step to rerun from.

## Add a finding

The facts of a finding are generated from recorded result rows. You write only the judgement items. `data/findings/AUTHORING.md` is the full guide.

1. Reduce the failing program (see "Reduce a failing program") or reduce it by hand. Write one-change controls that pass. Run them, and run the gate for a campaign program, so that result rows exist.
2. From a compute node or a wingtip lane, draft the finding:

       python3 -I tools/new_finding.py REDUCTION.c --campaign NAME --rows ROWS.jsonl --control CTL.c --name SLUG --dir DIR

   `--write` also applies the `data/findings/index.yaml` entry, and the row in `data/findings/LOG.md`.
3. Replace every `TODO(human)` marker. These are the title, the specification citations with the quoted passage (verify them with `tools/repo/check_citations.py`), the legality statement and its witnesses (the evidence that the program is legal), and the site title and summary. A witness is never the compiler under test, gcc or gfortran. A draft that still has a marker fails `tools/repo/check_findings.py`.
4. Run `tools/repo/check_findings.py` and the findings tests. The script checks every header claim against the recorded rows, and a claim without a row fails. Existing violations are listed in `catalog/findings_claims_baseline.yaml`, which only shrinks.
5. Run the site matrix for the new case on every machine. Sync the new finding files to the wingtip lane and the Tioga copy first, or the rows come back as harness errors. Pack the rows, then regenerate the site inputs with `tools/lanes/wingtip_offline.sh site-inputs`. The finding's verified citations go into `site/inputs/citations.json`, and a build without them stops. Rebuild and check with `tools/site_publish.sh` (see "Build and check the site").

## Add a clause or construct to the catalog

The catalog is data plus generators. Each feature (an atom such as `omp.clause.map.always` or `omp.directive.target_teams`) has a program that is generated at run time from the data below, and no program file is committed. `offload.engine.catalog` loads the data and `slice_atoms(version, lang=...)` lists the atoms. Versions are 50, 52 and 60 for OpenMP and 34 for OpenACC.

1. Grammar. Add the clause to `catalog/omp/clauses.yaml` (OpenACC: `catalog/acc/clauses.yaml`) with one form per spec version that changed its syntax. A form has `since`, `syntax` (in the notation of the file header) and `citation` ("OpenMP 5.2 §x.y, p.n", the printed page). A directive comes from `catalog/omp/skeleton.yaml`, which `offload/engine/skeleton.py` builds from an `llvm-tblgen` dump. Correct a skeleton entry in `catalog/omp/spec_overrides.yaml`, not in the skeleton. Behaviour that no syntax form carries is a semantic atom in `catalog/omp/semantic_atoms.yaml`.
2. Restrictions. A rule the grammar cannot express goes in `catalog/omp/rules.yaml` (`catalog/acc/rules.yaml`) with the spec sentence verbatim and a predicate registered with `@predicate` in `offload/engine/rules.py`. For a run-time rule, use `null` and a `why`. Add the sentence to `catalog/omp/rules_coverage.yaml`. Each rule generates an illegal variant. Put the stem and its transform in `VIOLATIONS` in `offload/engine/gen.py`, or in `ILLEGAL` in `offload/engine/acc_gen.py`. C rules are in `offload/engine/c_rules.py`.
3. Program. For Fortran OpenMP, add a recipe in `offload/engine/gen_templates.py` (`clause_recipe` or `directive_recipe`; its docstring describes the frame, data and result line). `_recipe` in `offload/engine/gen.py` reaches it. For OpenACC, add `recipe` in `offload/engine/acc_gen.py`. For C, `offload/engine/c_gen.py` ports the Fortran program through `offload/engine/f2c.py`. Fix an unfaithful port with `C_EDITS`, relabel evidence with `C_LABELS`, and list an atom with no C program in `C_UNGENERATABLE` with a reason. An atom with no program at all goes in `UNGENERATABLE` of `gen.py`, with a reason. Record a program whose atom no single run separates from its absence in `catalog/omp/no_oracle.yaml`, and a host-only atom in `catalog/omp/out_of_scope.yaml`.
4. Check the program. `generate` refuses a program that does not parse, lacks its atom, or has the wrong set of violated rules:

       python3 -I -c "import sys; sys.path.insert(0, '.'); from offload.engine import gen; print(next(gen.generate(['omp.clause.aligned'], 52)).source)"

5. Tests. `tests/engine/test_generators.py`, `test_rules.py`, `test_coverage.py`, `test_catalog_consistency.py` and `test_skeleton.py` cover the data. `test_gen.py` (with a `gfortran -std=... -fsyntax-only` base-language check, no `-fopenmp`), `test_acc.py`, `test_c.py`, `test_acc_c.py` and `test_c50.py` cover the programs. A new 5.0 spelling also affects `docs/tooling/omp5-vs-52.md` (`tools/derive/omp50_delta.py`, test `tests/engine/test_findings.py`).
6. Regeneration. A new or changed program has no measurement. Run it on every toolchain and mode with `tools/campaigns/run_matrix.py rerun --xnack N --programs ID --why REASON`. `prune` drops the rows of programs that are no longer generated. Then follow [regenerate.md](regenerate.md) from `support-tables` through `validate`. A vendor claim in `catalog/omp/claims.yaml` or `catalog/acc/claims.yaml` starts at `claims`. For other hand-edited inputs, the table "Hand-edited inputs and what they invalidate" names the first step to rerun.

## The linter

The linter, its model and its tooling are kept on the `linter` branch.

## Add a compiler or a compiler release

`catalog/toolchains.yaml` names every toolchain. Its header documents each key, and [toolchains.md](toolchains.md) shows the current table. `offload/engine/toolchains.py` reads the file and is the only code that knows the list. The matrix, gate, confirmer, support tables, site data and campaign orders ask it. `tools/derive/toolchains_gen.py` writes the files that cannot read YAML at run time: `site/static/toolchains.js`, `tools/jobs/toolchains.sh` and `docs/tooling/toolchains.md`.

A release needs the catalog entry, the generated files and canaries (steps 1 to 4). A release of a vendor family (AFAR, CCE, NVHPC) also needs the vendor packet's recipe tables (step 5). A new family or vendor also needs message tables. Measuring the release takes runs, not configuration (step 6). `tests/cluster/test_reports.py::test_adding_a_compiler_is_a_config_edit` runs these steps on a copy of the catalog with fake compilers `cce99` and `nvhpc99`.

1. Add the entry under `toolchains:` in `catalog/toolchains.yaml`. Copy the nearest release and change `version`, `label`, `merged_key` and the recipe fields.
   - A CCE release needs `modules` (`cce`, `rocm`). An NVHPC or GCC release needs `install` (`default` and the overriding `env` variable), `fc`, `cc` and `env`.
   - A new family needs a `families:` entry: name, vendor, recipe `kind`, `message_table`, `compile_s`, and the `flags` templates per model and language. A new vendor also needs message tables in `offload/engine/harness.py`, captured under `tests/data/messages/`.
   - A new GPU or machine needs `arches:` here and the machine, with its memory modes and their site `target` ids, in `catalog/machines.yaml`.
   - Optional keys:
     - `regression_of`: a release measured only against another, such as `cce21_4`.
     - `twin_of`: the same release on another GPU, named base name plus the arch's `twin_suffix` (`afar_g90`) or base name, `_` and the machine (`afar_mi300x`).
     - `report_column: false`: leaves the release out of the support tables.
     - `lane`: which job scripts run it, one of the `lanes:` entries.
     - `mention_words`: for one release installed on several machines, as GCC is.
2. Regenerate the three files: `python3 -I tools/derive/toolchains_gen.py`. Until you do, `--check` and `tools/regenerate.py --check` report them stale.
3. Add canaries to `catalog/canaries.yaml`. Each toolchain gets one entry that names all five kinds (pass, ice, wrong, racy, hang). Copy the nearest release's entry until step 6 measures them. `python3 -I tools/derive/toolchains_gen.py --check-registry` must print `[]`. It runs `offload.engine.toolchains.check_registry()`, which checks the machine and its modes, the lane, the support-table column and the canaries. `offload/engine/canary.py` refuses a campaign on a toolchain without canaries.
4. Run the catalog tests on a lane:

       WINGTIP_LANE=<lane> tools/lanes/wingtip_offline.sh tests tests/cluster/test_toolchains.py tests/cluster/test_reports.py tests/site/test_site.py tests/engine/test_canary.py tests/cluster/test_reports.py tests/engine/test_findings.py

   These assert against the catalog, so a release passes them unchanged. Two tests pin measured facts that a release does not move: `test_cce21_4_is_a_pinned_regression_toolchain` and `test_labels_versions_and_twins_come_from_the_catalog`. Then run `tools/lanes/wingtip_offline.sh regen-check`. Every committed artifact stays as it is, and a new toolchain adds columns only once it has rows.
5. Vendor packet, for a vendor-family release. `data/vendor/checks/run_checks.py` (`CCE` holds the version and ROCm, `NV` the install) and `data/vendor/checks/render.py` (`VTC`, `ALLTC`, `TCNAME`) keep their own copy of the recipes, and `test_the_vendor_packet_tables_agree_with_the_catalog` fails until they name the release. Vendor claims go in `catalog/vendor_claims.yaml` (vendor, product, version), and release-note claims go in `catalog/omp/claims.yaml` and `catalog/acc/claims.yaml`. `tools/derive/claims.py ingest` regenerates `catalog/vendor_claims_generic.yaml`.
6. Measure. Record canary outcomes in `catalog/canaries.yaml` (`python3 -I tools/campaigns/gate.py canaries --help`). Do a smoke run through the harness with `tools/campaigns/run_matrix.py run --toolchains <id>`, then run the matrix and the gate. The job scripts validate the id against its lane with `tc_check` from `tools/jobs/toolchains.sh`, so a copy of the tree on Tioga, or the shared tree, must carry the new catalog first. An older copy stops with "tc_check: command not found" and exit code 2. Do not claim a finding before the gate.

   Campaigns behind the campaign interface (nested, oop, hecbench) take their toolchains from the catalog, so the release is in their targets at once, and `python3 -I tools/campaign.py list` shows them. Campaign drivers that list their own targets (`tools/campaigns/harvest.py`, `tools/dataenv/dataenv.py`, `tools/campaigns/widen.py`, `tools/derive/expected.py`) record what a campaign measured, and a new release there is a new campaign.
7. Update the pages that describe the machines. These are [setup.md](setup.md), [wingtip.md](wingtip.md), [confirm.md](confirm.md) ("Adding a machine") and `data/findings/LOG.md`.

Some names stay hard-coded, each with one reason in `catalog/toolchain_names_allowlist.yaml`: message tables keyed by the catalog's `message_table` id (`offload/engine/harness.py`, `report.py`), report prose that quotes finding names, the hand-verdict validation set, the vendor packet's recipe copy, campaign drivers not yet behind the interface, and job scripts that record what was run. The list only shrinks.

## Add a GPU architecture or a memory mode

Trying a new architecture on your own machine needs no code change. Describe it in your local settings (see `catalog/local.example.yaml`). The settings need an `arches:` entry, the machine, a toolchain with a `label` and `report_column: false`, and its `canaries`. Then measure the canaries with `tools/campaigns/gate.py canaries` and run `tools/reduce.py` against it. The tests ignore your settings.

Putting the architecture in the committed catalog is a catalog edit. A release on the new GPU is a twin of its MI300A toolchain (`twin_of`): it gets a cell column after that toolchain's MI300A modes in the support tables (`offload/engine/report.py`, `TWINS`) and a cell on its row of the feature-support page (`offload/engine/site/data.py`, `_atom_columns`). Only the gfx90a twin enters the portable verdict and the gfx90a difference classes. A twin named after its machine (MI300X, MI350X) is a support-table cell only: the confirmer reads none of its rows (`offload/engine/confirm/ingest.py`, `TABLE_ONLY`).

The catalog steps are:

1. `catalog/toolchains.yaml`, `arches:` gets the arch, its device name and `gpu:` (the vendor kind); a `twin_suffix` only if its twins are named after the arch.
2. `catalog/machines.yaml` gets the machine: `arch`, `device`, `headline_mode` and `modes`. A mode needs a `row_key` (unique on the machine), either `env` or `flags`, and the site's column `target`, `target_short` and `target_name`. `MODES` in `offload/engine/confirm/machines.py` lists the three memory modes; a fourth is a code change. A mode the machine lacks goes under `not_applicable` with the measured reason. Access settings stay in your local file.
3. The toolchains that run on it, canaries for each, then `python3 -I tools/derive/toolchains_gen.py` and `python3 -I tools/regenerate.py --check`.
4. Measure: a smoke run through the harness, then the matrix and the gate. Do not claim a finding before the gate.

`test_adding_a_compiler_is_a_config_edit` in `tests/cluster/test_reports.py` is the worked example for the catalog steps. It adds two fake releases (`cce99`, `nvhpc99`) to a copy of the catalog with no code edit and asserts what follows from them. Copy the `FAKE` entry in that file.

## Add a campaign

A campaign is one Python module behind the interface of `offload/engine/campaign.py` plus one line in its registry. `tools/campaign.py <name> <step>` runs any registered campaign through `gen`, `prerun`, `witness`, `legality`, `run`, `gate`, `report`, `cluster`, `confirm` and `findings-plan`, plus `submit` and `lane`. Each step calls the existing machinery (harness, `offload.engine.gate`, confirmer, finding tools). Submission conventions for the machines live in `tools/jobs/run_campaign.sh` (flux machines), `tools/jobs/run_wingtip_campaign.sh` (wingtip) and `tools/jobs/campaign_remote.sh` (copying).

Three campaigns are registered:

- `offload/engine/campaigns/nested.py` is a seeded random draw (C and Fortran, OpenMP and OpenACC; data in [nested-data.md](nested-data.md)).
- `offload/engine/campaigns/oop.py` is a hand-listed Fortran family.
- `offload/engine/campaigns/hecbench.py` covers real C and C++ code, the HeCBench `*-omp` benchmarks, as build recipes derived from their Makefiles. It has a dev half and a sealed holdout half. Its runner is `offload/engine/hecbench_run.py`, its companion tool is `tools/campaigns/hecbench.py` and its write-up is `data/reports/hecbench.md`.

The smallest complete campaign is the toy in `tests/toy_campaign.py`, which `tests/cluster/test_campaigns.py` runs end to end with a fake runner and no GPU. Copy it. `run`, `gate` and `submit` refuse a machine the campaign does not declare. `list` refuses a campaign whose declarations the catalog cannot satisfy, and says why.

1. Write `offload/engine/campaigns/<name>.py` from the toy.
   - A frozen program class with `id`, `lang` (`c` or `f90`), `model` (`omp` or `acc`), `version` (52 or 34), `source`, `expected` (a dict of the `name= value` lines the program prints, computed in Python, never by a compiler under test), `legality` (one of the campaign's labels), `why`, `cites` (specification citations as `catalog/dataenv_rules.yaml` writes them: version, section, page, lines, quote), optionally `modes` (memory modes the expected values hold in; default `("copy", "unified")`), and `harness()` returning a `offload.engine.gen.Program`.
   - A `Campaign` subclass with these members:
     - `name` gives the directory `results/<name>/` and the rows' `campaign` value.
     - `labels` is a subset of `defined`, `unspecified`, `illegal`, `pending`. Only a `defined` program's failure is gated and confirmed, unless `gated(p)` is overridden.
     - `caps = Capabilities(langs, models, families={machine: (family ids) or None}, regression=..., draw_options=(...))`.
     - `programs(seed, n, **opts)` must be deterministic. The generic layer stores the sources' hashes in `programs.jsonl` and refuses a later command whose regeneration differs.
   - Optional overrides, each with a default that reads the program's fields: `record`, `row_tags`, `gate_tags`, `parse_observed`, `short_id`, `mark`, `facets`, `not_a_verdict`, `fe_timeout_s`, `timeout_s`, `kind` / `prefix` / `signature` (the gate kind; default `<name>`, `<name>_`, `program`), `printed_values`, `compile_limit_s`. Further hooks used by hecbench: `make_runner`, `stored_programs`, `bind_run`, `src_name`, `gate_filter`, `is_sealed`, `sealed_runs`.
   - The last line is `CAMPAIGN = C.register(<Class>())`.

   Campaigns never name toolchains. They declare compiler families per machine and the registry resolves them, so a release added to the catalog is measured with no code change. `test_registered_campaigns_declare_toolchains_through_the_catalog_only` scans every campaign module for ids and versions.
2. Register it: add `"<name>": "offload.engine.campaigns.<name>"` to `MODULES` in `offload/engine/campaign.py`.
3. `python3 -I tools/campaign.py list` shows the campaign with its toolchains and modes per machine and its gate kind. Registering declares the kind to `offload.engine.gate` (`KINDS`, `VALUE_KINDS`, `COMPILE_LIMIT_S`). The prefix ends in `_` with no `-` (`tests/engine/test_findings.py`).
4. Write tests first: `tests/engine/test_<name>_gen.py` for the generator (determinism, expected values, every `defined` program accepted by `offload.engine.prerun.rules_witness`), modelled on `tests/engine/test_nested_oop.py`. `tests/cluster/test_campaigns.py` parametrizes over the registry. On a lane:

       WINGTIP_LANE=<lane> tools/lanes/wingtip_offline.sh tests tests/cluster/test_campaigns.py tests/engine/test_<name>_gen.py tests/cluster/test_reports.py tests/cluster/test_standing_rules.py tests/engine/test_findings.py

   The lane bundles HEAD and copies the manifest's inputs, so work in a worktree or a copy that is itself a git repository with `results/`, `corpus/` and `spec/` linked.
5. Legality. Every `defined` program passes two witnesses. One is `offload.engine.rules` (add restrictions to `offload/engine/rules.py`, or `EXTRA` in `offload/engine/prerun.py` with `EXTRA_CITES`). The other is a front end of another family. `prerun` uses AFAR's front end on Tuolumne. `witness` uses the independent checker of `catalog/machines.yaml` (NVHPC compile only, on wingtip inside the cap) or a CCE row that compiled. GCC and omp_vv are never witnesses. `legality` writes the per-program, per-family table. A program the specification leaves unspecified is an observation when a front end rejects it, never a finding.
6. Draw the programs (pure Python, any host):

       python3 -I tools/campaign.py <name> gen --name main --n N --seed S [--opt key=value ...]

   The output goes to `results/<name>/main/` (`meta.json`, `programs.jsonl`, `src/`). `--opt` keys must be among the campaign's `draw_options`.
7. Pre-run on Tuolumne with AFAR's front end, as batch work. `python3 -I tools/campaign.py <name> submit --machine tuolumne --steps prerun --limit-s 1200` prints the pbatch command (`tools/jobs/run_campaign.sh <name> prerun main ...`), and `--go` runs it. `--queue pdebug` prints the foreground form (one job, at most 30 minutes, named like a compile). Then run `python3 -I tools/campaign.py <name> witness --name main` (over ssh, inside the cap) and `legality`.
8. Runs and the gate, per machine. `submit` prints each machine's command from the shared job scripts.
   - Tuolumne: `submit --machine tuolumne --steps "run abd"` runs on pbatch, on one node. It is resumable and skips every cell that has a row. Then run `--steps c --not-host NODE` as a separate job placed off the node of (a). It adds `--requires=-host:NODE`, and the script refuses (c) on a node that holds reruns of (a). `--queue pdebug` shrinks the limit to the queue's longest job. `RUN_TCS`, `RUN_SHARD=k/m` and `GATE_STORED_ON` narrow a job, as in `tools/jobs/run_nested.sh`.
   - Tioga: `tools/jobs/campaign_remote.sh push tioga <name>` (a private copy under the `campaign_lanes` key of `catalog/toolchains.yaml`, with the stored pre-run), then `submit --machine tioga --steps run`. This is one foreground pdebug job at a time, at most 60 minutes, with `MACHINE=tioga`. `campaign_remote.sh pull tioga <name>` brings the rows back.
   - wingtip: `tools/jobs/campaign_remote.sh push wingtip <name>`, then `submit --machine wingtip`, then `pull`. The submission runs `tools/jobs/wingtip_capped.sh tools/jobs/run_wingtip_campaign.sh`, which applies the cap, uses two free GPUs, allows at most 2 workers per GPU and takes the run lock. Environment (c) runs on the other GPU.
9. On a compute node or a lane, run the following steps. The confirmer reads stored evidence only.
   - `report --name main` writes the summary and `matrix.md`.
   - `cluster` groups failures by toolchain, mode and signature, with shared facets.
   - `confirm` writes `confirm.jsonl`, with the confirmer's verdict per failing cell, the gate's verdict and the legality.
   - `findings-plan` writes `findings_plan.md`, with one entry per gate-confirmed cluster. An entry lists the cluster's programs and verdicts and the `tools/new_finding.py` command that drafts the finding once a person has reduced a program and made its controls.

   Findings live in `data/findings/<name>/`.
10. Write up in `data/reports/<name>.md`. If the campaign produces committed artifacts, add a row to [regenerate.md](regenerate.md) and a step to `tools/lanes/wingtip_offline.yaml`. Run the standing-rule tests before any GPU job.

Campaigns that run on their own drivers and job scripts:

| campaign | driver | what keeps it off the interface |
|---|---|---|
| fuzz | `tools/campaigns/fuzz.py`, `offload/engine/fuzz*.py` | own row format (`offload.engine.fuzz_exec`) and gate rerun (`rerun_fuzz`); generator version and base-language groups (`offload/engine/fuzz_base.py`); chunked run ids in `catalog/fuzz_campaigns.yaml`. Legality is the stored check (`COMPLIANT_FUZZ_CHECKS`) plus the base-language check `gfortran -std=f2008 -fsyntax-only`, never `-fopenmp` |
| dataenv | `tools/dataenv/dataenv.py`, `offload/engine/dataenv_gen.py` | programs from the rule table `catalog/dataenv_rules.yaml` with `opposite` oracle mutants and its own pre-run row (`dataenv_gen.prerun_check`); per-machine gate plan file and `--opposite` runs have no generic step |
| harvest, harvest2 | `tools/harvest*.py` | programs converted from untrusted clones through `inventory`, `filter`, `convert` and a sealed `holdout`; the draw is not a seeded function |
| kbody | `tools/campaigns/kbody.py` | nested's shape with its own gate loop over `gate_run.rerun_program` |
| stress, widen, catalog matrix, parity | `tools/campaigns/stress.py`, `widen.py`, `run_matrix.py`, `parity.py` | own row formats or runners (`offload.engine.stress_exec`, `offload.engine.run_matrix`); the gate reruns them through `offload.engine.gate_stored` |
| oop fuzz-5 sample | `tools/campaigns/oop.py fuzz-gate` | the sample is a fuzz campaign |

## Build and check the site

The site is built from committed data only (`MANIFEST` in `offload/engine/site/inputs.py`), so a clean clone without `results/` builds the same pages. When a finding is added or the dashboard's atom table (`results/dash/atoms.json`) changes, regenerate `site/inputs/` first, with `tools/lanes/wingtip_offline.sh site-inputs` or, where `results/` is present, `python3 -I tools/site/site_inputs.py`. `tools/regenerate.py --check site-inputs` reports it stale.

| command | effect |
|---|---|
| `tools/site_publish.sh OUT_DIR [--repo-url URL]` | builds the site and checks it; exit 0 only with 0 problems. `OUT_DIR` must be new or empty |
| `python3 -I tools/site/site_build.py results/site` | the build alone, on any host |
| `python3 -I tools/site/site_check.py results/site` | the check alone: links and leaks anywhere; the browser part needs node 22 and Chrome |

`site_publish.sh` needs node 22 and Chrome or Chromium, so run it on a Tuolumne compute node as one short foreground job (wingtip has no Chrome):

    flux run -q pdebug -N1 -n1 -t 20m --job-name=compile-test-site bash tools/site_publish.sh results/site-new

Put `bash` in front, because a compute node can refuse to exec a freshly written script by path. Add `--repo-url URL` once the repository is public. On GitHub the same two steps run in `.github/workflows/site.yml` and deploy to GitHub Pages. [publishing.md](publishing.md) describes turning that on, [site.md](site.md) describes the site and its data, and [dashboard-publish.md](dashboard-publish.md) covers the preview artifact.

## Queue etiquette

| machine | rule |
|---|---|
| Tuolumne (flux) | Batch work goes to pbatch. pdebug is for short attended work: one foreground `flux run -q pdebug -N1 -n1 -t <=60m --job-name=compile-<what>` at a time, never chained, never `flux batch`. Put scripts on Lustre; compute nodes do not see the login node's `/tmp`. Bound every wait |
| Tioga (`ssh tio`) | The account has pdebug and pci, no pbatch. Each build, smoke or subset step is one supervised foreground `flux run -q pdebug -N1 -n1 -t <=60m --job-name=compile-...` from the copy on `/p/vast1`, one at a time. `ssh -O check tio` tests the ssh master from a Tuolumne login node |
| wingtip (shared, no scheduler) | Everything runs inside `compliant.slice` through `tools/jobs/wingtip_cap.sh` or `tools/jobs/wingtip_capped.sh CMD`. Free GPUs only, one program per GPU (the run lock), at most 4 compiles across all users, `nice`. One step at a time per lane; a second step waits 30 s, then exits 75. Details in [wingtip.md](wingtip.md) |

Sealed benchmark sets (`data/bench/<set>/SEAL` not listed in `catalog/sealed_spent.yaml`) stay on Tuolumne and are never read. Tooling never files, reports or posts anything externally. Write drafts instead.

## Reduce a failing program

`tools/reduce.py` (library `offload/engine/reduce.py`) shrinks a failing program to a small reproducer and writes one-change controls, so that a person can go from a failing row to a draft finding. It runs where the compiler and GPU are and refuses a target the node cannot run.

Input is one of:

| input | options |
|---|---|
| a recorded row | `--from-row ROWS.jsonl --id ID`: a harness row's program id or file stem, or the seed of a fuzz campaign's `programs.jsonl`. Targets and signature come from the failing rows; `--target` narrows them |
| a fuzz seed | `--seed N --gen-version fuzz-1 --target nvhpc/0`: the program is regenerated and the first run's signature is used; it must fail |
| a file | `--program FILE --target cce21/1` |

A target is written `toolchain/mode`. For example, `nvhpc/0` is NVHPC in copy mode, `nvhpc269/2` is managed, and `afar/1` is `HSA_XNACK=1`. `--verify-target` adds targets that are checked only for the final program and the controls. The failure signature is the gate's outcome class plus the normalized message or self-check line, which `tools/repo/check_findings.py` compares as "identical signature".

Delta debugging runs at four levels. In order, they work on statements, lines and blocks; on directive clauses, list items and modifiers; on expressions and bounds; and on the cleanup of unused variables. A fuzz-format program uses the steps of `offload.engine.fuzz_min`, which never leave a read undefined. The statement step never deletes an assignment whose variable another line reads or that steers a loop.

A candidate is accepted only when:

- the legality witness accepts it (`offload.engine.prerun.rules_witness` checks grammar, restriction rules and the race rule, and never uses the compiler under test, gfortran or `gcc -fopenmp`);
- a device compute construct and a call of the host-execution flag stay;
- the run on every target is evidence: no harness error, no compile at the harness's time limit, no flaky row whose repeats disagree;
- the outcome class is the recorded one and the key is identical, where the key is:
  - for a compile failure, the normalized message;
  - for a crash, the signal and normalized first error line;
  - for a run error, the exit kind and normalized first error line;
  - for a timeout, the stage;
  - for a wrong answer, the self-check line and the names and values of the printed values that differ from the oracle.

The oracle is the sequential elision (gfortran without OpenMP, used as an output oracle only) or a host run of a toolchain from another family (`--reference elision|host:TC`). A fuzz program carries its own oracle. Its `RESULT checksum=` line is rewritten into the harness's `check=pass|fail` form against the elision's value, recomputed for each candidate. A wrong-answer reduction of a hand-written program without `--reference` is refused.

Every candidate run is a row in `OUT/candidates.jsonl`. A run is deterministic, and `--order-seed` shuffles the candidate order. It is resumable: rerun the same command, and it continues from `OUT/checkpoint.json`. A changed target list, level list, witness or signature is refused. It is bounded by `--budget-candidates` and `--budget-minutes`. From the reduced program the tool tries one-change edits of the directives (a clause, list item or modifier removed, two clauses swapped, the directive unwrapped, the construct shortened) and keeps those that are legal and pass on every `--target` and `--verify-target`.

The tool does not decide:

- whether the reduced program is a compiler defect (the gate and a person do);
- which facet of a program with several defects to keep;
- whether a value left by the block or expression steps is defined;
- the front-end witness (`offload.engine.prerun.check` needs AFAR's front end, so it runs on Tuolumne);
- the citation, title, legality sentence and site text.

`--no-witness` turns the legality witness off for exploration. The headers and report then say so, and the result is not a candidate finding.

Procedure:

1. Pick the input as above.
2. Run it on the target's machine.
   - wingtip (NVHPC, GCC sm_80): copy the tree to a private lane (an rsync of `git ls-files` to a directory under `/fastscratch`, as `tools/jobs/parity_remote.sh` does), then from the copy:

         setsid nohup tools/jobs/run_wingtip_reduce.sh --from-row results/.../programs.jsonl --id 2019 --target nvhpc/0 --target nvhpc269/0 --name nvhpc-2019 --out results/reduce/nvhpc-2019 --budget-minutes 60 > results/reduce/nvhpc-2019.log 2>&1 < /dev/null &

     The script sources the cap, waits a bounded time for a free GPU, holds the run lock and runs under `nice` with `COMPLIANT_RUN_SLOTS=1`. Check `nvidia-smi` first, and copy `results/reduce/<name>/` back with rsync afterwards. For a hand-written wrong-answer program, add `--reference elision` (Fortran) or `--reference host:TC`.
   - Tuolumne (AFAR, CCE), one foreground job of at most 30 minutes:

         flux run -q pdebug -N1 -n1 -t 30m --job-name=compile-reduce-<name> python3 -I tools/reduce.py --program FILE --target cce21/1 --name <name> --out results/reduce/<name> --budget-minutes 25

     Longer runs go to pbatch: `flux batch -q pbatch -N1 -t 120 --output=results/reduce/<name>.log --wrap 'python3 -I tools/reduce.py ... --budget-minutes 110'`. A run that stops at its budget resumes with the same command.
   - Tioga (gfx90a): `ssh tio`, then from the copy on `/p/vast1` one foreground `flux run -q pdebug -N1 -n1 -t 30m --job-name=compile-reduce-<name> python3 -I tools/reduce.py ...`.
3. Read `OUT/report.md` (lines before and after, steps, controls and where they pass, the budget) and `OUT/<name>.f90` or `.c`. Check that every variable it reads is set and that the failure is the intended one.
4. On Tuolumne, run the front-end witness on the reduction and the controls:

       flux run -q pdebug -N1 -n1 -t 10m --job-name=compile-prerun-<name> python3 -I -c "import sys; sys.path.insert(0, '.'); from offload.engine import prerun; [print(f, prerun.check((open(f).read(), 'f90'))) for f in sys.argv[1:]]" OUT/<name>.f90 OUT/controls/*.f90

   `python3 -I` leaves the working directory off `sys.path`, so the command inserts it. For a campaign program, also run the gate.
5. Draft the finding from the rows the tool wrote, as in "Add a finding": `python3 -I tools/new_finding.py OUT/<name>.f90 --campaign NAME --rows OUT/rows.jsonl --control OUT/controls/*.f90 --name SLUG --dir DIR`, then replace the `TODO(human)` items.

To extend the reducer, register a step in `offload/engine/reduce.py`:

    @RD.step("my-step", level=2, langs=("f90",), controls=True)
    def my_step(text: str, lang: str) -> list[RD.Candidate]: ...

`level` is 1 to 4 as above. `controls=True` makes its edits control candidates too. `only=` selects the programs it applies to, as the fuzz-format steps do. A new runner implements `check(targets)` and `run(text, lang, target, program_id) -> row` (see `FakeRunner` and `HarnessRunner`). Tests are in `tests/cluster/test_campaigns.py` and use the fake runner, no GPU.
