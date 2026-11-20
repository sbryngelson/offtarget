# Measure a new compiler release

The order of the runs that put a release of a family already in the catalog (AFAR 24.4.0 after 24.3.0) into the support tables, `offload can-use`, the finding headers and the site. The catalog edit itself is "Add a compiler or a compiler release" in [contributing.md](contributing.md); the generated files and their checks are in [regenerate.md](regenerate.md). Every run goes through the machine's scheduler ([contributing.md](contributing.md), "Queue etiquette"), never a login node.

A release on Tuolumne's MI300A is the headline toolchain. The same install on another GPU is a twin (`twin_of`), one per machine: MI250X, MI300X, MI350X. Each twin repeats steps 2 to 5 on its machine, in copy memory only.

| step | where | what it writes |
|---|---|---|
| 1. catalog entry, twins, canary entries | offline | `catalog/toolchains.yaml`, `catalog/canaries.yaml`, the three generated files |
| 2. canaries | GPU node, each machine | `results/gate/canaries/`, then the measured kinds in `catalog/canaries.yaml` |
| 3. catalog matrix | GPU node, each machine | raw result files, then the full result files |
| 4. reproduction gate | two GPU nodes, each machine | `results/gate/` |
| 5. site runs of the findings | GPU node, each machine, four environments | `data/vendor/checks/results/site-*.jsonl` |
| 6. derived files | offline, then a compute node for the confirmer batches | support tables, `releases` lines, site inputs |
| 7. new failures | offline, then the gate | `catalog/unlinked_bugs.yaml`, findings |
| 8. pages that list the releases | offline | `README.md`, `docs/scope.md`, `docs/provenance.md` |

## 1. Catalog

Follow steps 1 to 5 of the checklist in [contributing.md](contributing.md). Add the headline entry with a `merged_key` and one twin per other machine. Copy the nearest release's canary entry for each. `python3 -I tools/derive/toolchains_gen.py`, then `python3 -I tools/derive/toolchains_gen.py --check-registry` must print `[]`.

Every copy of the tree that runs jobs (Tioga's copy, the AMD cluster's) needs the new catalog before its first job: the job scripts check the toolchain against its lane with `tc_check` and stop with exit code 2 on an older copy.

## 2. Canaries

    python3 -I tools/campaigns/gate.py canaries --toolchains <id> --xnack 1 0 --out results/gate/canaries/<machine>.<id>.jsonl

One run per toolchain and machine (`--xnack 0` for a twin). Write the five measured kinds into the toolchain's entry in `catalog/canaries.yaml` with the result file named in the comment above it. A canary of the old release that the new one fixes (an ICE that now compiles) is replaced by a program that still shows the kind. A campaign refuses a toolchain without canaries.

## 3. Catalog matrix

One job per language (Fortran, C) and memory mode. Each writes raw files of its own, never the full result files:

    python3 -I tools/campaigns/run_matrix.py run --xnack <1|0> --toolchains <id> --versions 50 52 60 [--lang c] \
        --workers 16 --out <raw matrix file> --baseline-out <raw baseline file> [--resume]

`tools/jobs/run_x0_full.sh` is this command for copy mode (`TC=<id>`, `LANG_=f90|c`), `tools/jobs/run_tioga.sh` for the MI250X from Tioga's copy of the tree. A job cut short continues with `--resume`. A command run directly under `flux run` needs `--env=SPINDLE_FLUXOPT=disable` ([contributing.md](contributing.md), "Queue etiquette"); without it the harness stops at once.

Merge each raw file into the full result file of its language:

    python3 -I tools/campaigns/run_matrix.py replace --out <work copy of the full file> --inputs <raw files> --why "<release>"

`replace` adds the new toolchain's cells and keeps every other row; it refuses to shrink the file. Check the row counts, then put the work copy over the full file. OpenACC is run only for a family that has it (not AFAR).

## 4. Reproduction gate

    tools/jobs/run_gate.sh <machine> <limit seconds> <workers> catalog

on two nodes (the script's header has the submit line); repeat until nothing is left. Then

    python3 -I tools/campaigns/gate.py report --campaign catalog widen fuzz stress evidence findings

`report` rewrites the verdict file from the campaigns it is given, so it is always run over all of them. The new toolchain's failing rows are appended to the stored plan. Planning again over the stored rows (`apply-stored`), or giving a campaign that has reruns another budget, changes which rows are sampled and turns stored verdicts into unchecked ones; a campaign's `gate` refuses a changed budget.

## 5. Site runs of the findings

    python3 -I tools/derive/finding_matrix.py plan

lists the runs each machine still lacks: every finding's file and its controls on the new toolchain. Run them with `tools/jobs/run_site_matrix.sh <machine> <env>` for the environments a, b, c and d, (c) as a job of its own so that it lands on another node. Then

    python3 -I tools/derive/finding_matrix.py pack

writes the committed check rows. They are what the `releases` line of each finding header and the site's per-issue matrix read.

## 6. Derived files

    python3 -I tools/regenerate.py --offline
    python3 -I tools/regenerate.py --check
    python3 -I tools/repo/check_findings.py

`--offline` rewrites the support tables, the `releases` lines, the index scope, the list of bugs without a finding and the rest of the offline chain. `--check` names what is still stale: the confirmer batches after a catalog edit (`tools/jobs/run_regen_confirm.sh`, `tools/jobs/run_widen_confirm.sh`, on a compute node) and the site inputs (`python3 -I tools/site/site_inputs.py`, after the feature-support data is rebuilt). `python3 -m offload can-use <feature>` then shows the release's row, and a GPU it never ran on as `-`.

## 7. New failures

`data/reports/unlinked-bugs.md` lists the groups of confirmed catalog failures that no finding explains. `tests/confirm/test_confirm_outputs.py` fails on a group that is new or changed size until `catalog/unlinked_bugs.yaml` names it with a reason. A group that is a defect of the new release becomes a finding ([contributing.md](contributing.md), "Add a finding"): reduce, control, another family, the gate. A failure of the old release that the new one no longer shows needs no edit: the `releases` line states it. `catalog/expected_triage.yaml` and `catalog/mode_differences.yaml` name toolchains; a release that behaves as its predecessor is added to the same entries.

## 8. What a release does not rerun

The campaigns that record what was measured at the time (fuzz, stress, harvest, data environment, the widened catalog) are not rerun, and a finding header's facts stay those of its rows. The release appears in such a finding through its `releases` line (step 5). The nested and OOP campaigns take the release from the catalog; to extend a nested finding to it, run that finding's programs (`tools/campaigns/nested.py run --toolchains <id> --ids ...`), gate them without a budget (`tools/jobs/run_nested.sh abd`, then `c` on another node) and rebuild the finding (`tools/campaigns/nested_findings.py rebuild`).

Last, add the release to the lists in `README.md`, [scope.md](../scope.md) and [provenance.md](../provenance.md), and to the machine pages named in step 7 of the checklist.
