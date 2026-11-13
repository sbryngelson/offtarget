# Regenerating the committed generated artifacts

This page lists every generated file in the repository, the order to rebuild them in, and the check that says whether each one is current. Most steps read measurements in `results/`, which Git ignores; [setup.md](setup.md) says how to get them. The driver is `tools/regenerate.py`:

```bash
python3 -I tools/regenerate.py --list              # the steps below, in order
python3 -I tools/regenerate.py --check             # is every offline artifact current?
python3 -I tools/regenerate.py --check witness  # one check, by name
python3 -I tools/regenerate.py --offline           # rerun the offline steps in order
```

`--check` rebuilds each offline artifact in memory or in a temporary directory and compares it with the stored copy. It writes nothing and exits 1 when an artifact is stale. A check whose inputs are missing prints `skipped` and names them. `tests/cluster/test_reports.py` runs it on the committed data and skips in a clone without `results/`. `--offline` does not publish the dashboard.

## Steps

Run the commands from the repository root. GPU steps need a compute node, for example `flux batch -q pbatch -N1 -t 60 --setattr=thp=always ...`. Offline steps run anywhere that has their inputs. The step names are those that `--list` and `--check` use, and a step with no check is marked `-`. A row is a recorded result line of a run.

| # | step | where | command | writes | check |
|---|---|---|---|---|---|
| 1 | `measure` | GPU node (Tioga over `ssh tio`; wingtip over `ssh wingtip`) | `tools/jobs/run_matrix_xnack1.sh`, `run_x0_full.sh`, `run_copy_subset.sh`, `run_copy_subset_c.sh`, `run_tioga.sh`, `tools/jobs/run_wingtip.sh` (merge with `tools/campaigns/run_matrix.py replace`); omp_vv baselines with `tools/campaigns/run_matrix.py` | `results/matrix*.jsonl`, `results/acc_matrix*.jsonl`, `results/baseline*.jsonl` | - |
| 2 | `audits` | GPU node | `tools/campaigns/oracle_audit.py`, `tools/campaigns/map_audit.py`, `tools/campaigns/presence_x1.py` | `tests/data/oracle_audit_summary*.json`, `acc_audit_summary*.json`, `map_audit*_summary.json`, `presence_x1_summary.json` | - |
| 3 | `expected-runs` | GPU node | `python3 -I tools/derive/expected.py catalog`; `... fuzz --run c1`; copy mode: `... xnack0-command` | `results/expected/*.jsonl` | - |
| 4 | `expected-report` | offline | `python3 -I tools/derive/expected.py report` | `data/reports/expected-sources.md` | `expected-report` |
| 5 | `claims` | offline | `python3 -I tools/derive/claims.py ingest` | `catalog/vendor_claims_generic.yaml` | `claims` |
| 6 | `toolchains-gen` | offline, after editing `catalog/toolchains.yaml` or `catalog/machines.yaml` | `python3 -I tools/derive/toolchains_gen.py` (`--check` lists stale files) | `site/static/toolchains.js`, `tools/jobs/toolchains.sh`, `docs/tooling/toolchains.md` | `toolchains-gen` |
| 7 | `support-tables` | offline | `python3 -I tools/derive/support_table.py`; `--lang c`; `--model acc`; `--model acc --lang c` | `results/support_table{,_c}.{md,csv}`, `results/acc_support_table*`, `data/reports/{c,acc,acc-c}-support-table.md`, `data/reports/{c,acc,acc_c}_support_table.csv` | `support-tables` |
| 8 | `widen-table` | offline, after the widened catalog's GPU runs | `python3 -I tools/campaigns/widen.py merge`, `audit-summary`, `expected`, `table` | `results/widen/matrix.jsonl`, `tests/data/widen_audit_summary{,_c}.json`, `results/expected/widen*.jsonl`, `data/reports/widen_support_table.csv`, `data/reports/widen-support-table.md` | `widen-table` |
| 9 | `fuzz` | GPU node, then offline | `tools/campaigns/fuzz.py` campaigns (`tools/jobs/run_fuzz_seeds.sh`); then `python3 -I tools/campaigns/fuzz.py report ...` | `results/fuzz/*`, `data/reports/fuzz-*.md` | - |
| 10 | `confirm-evidence` | GPU node (and Tioga over ssh) | `tools/jobs/run_confirm_shards.sh` (runs `confirm batch --run` in shards) | `results/confirm/shards/*.ev.*.jsonl`, `results/confirm/evidence.jsonl` | - |
| 11 | `confirm-batch` | compute node, offline, about 5 min | `flux batch -q pbatch -N1 -t 30 --setattr=thp=always --env=INSTALL=1 --output=results/confirm/shards/regen.log tools/jobs/run_regen_confirm.sh` (full and s1 batches in 8 shards each, then `confirm decide`) | `results/confirm/batch_full.jsonl`, `batch_s1.jsonl`, `batch_s1.final.jsonl` | `confirm-batch`, `decide` |
| 12 | `widen-batch` | compute node, offline, a few minutes | `tools/jobs/run_widen_confirm.sh` (stamps its inputs) | `results/confirm/batch_widen.jsonl`, `batch_widen.stamp.json` | `widen-batch` |
| 13 | `witness` | offline (ssh to the `witness_only` offload compilers of `catalog/machines.yaml`, if any) | `python3 -I tools/confirm.py witness` | `catalog/legality_witness.yaml` | `witness` |
| 14 | `index-scope` | offline | `python3 -I tools/confirm.py index --scope --write` | `data/findings/index.yaml` (`modes`, `arch`) | `index-scope` |
| 15 | `backlog` | offline | `python3 -I tools/confirm.py backlog --write` | `data/reports/unlinked-bugs.md` | `backlog` |
| 16 | `ompvv-compare` | offline | `python3 -I tools/derive/ompvv_compare.py`; `--lang c`; the omp_vv index rows come from `tools/campaigns/index_corpus.py` | `results/ompvv_compare{,_c}.csv`, `data/index/corpus_index.csv` | `ompvv-compare`, `ompvv-corpus` |
| 17 | `triage` | offline | `python3 -I tools/confirm.py triage` | `results/confirm/triage27b.jsonl`, `data/reports/triage-2026-10.md` (generated block), `docs/upstream.md` | `triage` |
| 18 | `validate` | offline | `python3 -I tools/confirm.py validate` | `data/reports/confirm-validation.md` | - |
| 19 | `dashboard` | offline, then publish | `python3 -I tools/site/dashboard_data.py OUT_DIR`, then publish each changed dataset ([dashboard-publish.md](dashboard-publish.md)) | the published datasets (not committed) | - |
| 20 | `site-inputs` | offline (`tools/lanes/wingtip_offline.sh site-inputs`) | `python3 -I tools/site/site_inputs.py` (feature support from `results/dash/atoms.json`; verified citations of the published findings from `results/spec_cache`) | `site/inputs/atoms.json.gz`, `site/inputs/citations.json` | `site-inputs` |

The site pages are built from committed data only. `tools/site_publish.sh OUT_DIR` builds them (see [publishing.md](publishing.md) and [site.md](site.md)), and on GitHub `.github/workflows/site.yml` does. The build needs node 22 and Chrome, and the pages are not committed.

### Steps without a `--list` entry

| artifact | command | writes |
|---|---|---|
| reproduction gate | `python3 -I tools/campaigns/gate.py apply-stored --campaign all` plans the reruns. Then `flux batch -q pbatch -N2 -t 60 --setattr=thp=always tools/jobs/run_gate.sh tuolumne 2400 24 catalog widen fuzz evidence`, resubmitted until nothing is left (a chunk starts no new row after 2400 s and resumes from earlier reruns; leave 20 minutes of walltime for rows still running). The same from Tioga's copy, and `tools/jobs/run_wingtip_gate.sh` ([wingtip.md](wingtip.md)). Then `python3 -I tools/campaigns/gate.py report` on a compute node (the pre-run checks need AFAR). | `results/gate/*/plan.jsonl`, `results/gate/*/reruns/`, `results/gate/verdicts.jsonl`, `data/reports/gate-changes/*.tsv` |
| C 5.0 and OpenACC C slices | `tools/jobs/run_tioga.sh` with `VERSIONS=50`; `tools/jobs/run_wingtip.sh matrix:c:<k>` with `VERSIONS=50`; merge with `run_matrix.py replace`. Audits: `tools/campaigns/oracle_audit.py --lang c --versions 50 --merge`, `tools/campaigns/map_audit.py run --lang c --versions 50`, `tools/campaigns/presence_x1.py --only c:50`, `tools/jobs/run_wingtip.sh audit:c:<k>` with `AUDIT_VERSIONS=50`, `tools/campaigns/nvhpc_audit.py --merge-versions`. Expected values: `tools/campaigns/c_slices.py expected --slice c50` and `--slice accc`. | `results/matrix_c.jsonl`, `results/acc_matrix_c.jsonl`, `results/expected/c50*.jsonl`, `results/expected/accc*.jsonl` |
| NVHPC 26.9 audit | `TC=nvhpc269 tools/jobs/run_wingtip.sh audit:<lang>:<k>`; `tools/campaigns/nvhpc_audit.py --toolchain nvhpc269 --raw DIR` (`--compare` lists dispositions that differ from 25.11) | `tests/data/*nvhpc269*.json` |
| fuzz 50-spelling samples | `tools/campaigns/fuzz.py merge` and `join` | `results/fuzz/n0x0`, `results/fuzz/n1x0`, `data/reports/fuzz-n0x0.md`, `data/reports/fuzz-n1x0.md` |
| OpenMP 5.0 delta | `tools/derive/omp50_delta.py` | `docs/tooling/omp5-vs-52.md` (test: `tests/engine/test_findings.py`) |
| skeleton, port equivalence | tests `tests/engine/test_generators.py`, `tests/confirm/test_confirm.py` | `catalog/omp/skeleton.yaml`, `catalog/omp/port_equivalence.yaml` |

## Order and dependencies

- Every campaign runner (`run_matrix.py run`, `widen.py run`, `fuzz.py run`, `stress.py sweep`) runs the canaries in `catalog/canaries.yaml` and writes them next to its output (`<file>.canaries.jsonl`, `<run>/canaries.jsonl`). The reports (`fuzz`, `support-tables`, `widen-table`, the stress report) stop when a canary changed (`offload.engine.canary.require_unchanged`).
- The gate reads the stored results (steps 1 to 10) and writes verdicts that the confirmer batches (11, 12) read. A cell whose verdict is not `confirmed` needs a human. `results/gate/verdicts.jsonl`, `offload/engine/gate.py` and `offload/engine/prerun.py` are inputs of the batch stamp, so `--check confirm-batch` reports the batch stale after a gate report. The failing rows of a new measurement have gate status `pending` until the gate runs over them.
- The `support-tables` step reads the measurements, the audit summaries, the presence summary, `catalog/mode_differences.yaml` and the claims (`claims`).
- `confirm-batch` reads the measurements, the stored evidence, the expected values, the findings index (for deduplication), the claims and the legality witnesses. `triage` reads the claim mismatches of the support tables and the batch.
- `index-scope` and `backlog` read the batch. A change to the findings index (or a promoted finding) changes the batch's deduplication, so rerun `confirm-batch` after it. One more pass reaches a fixed point, because the scope only grows.
- `widen-table` reads the widened matrix and audit summaries. `widen-batch` reads that matrix, the widened expected values and the stored results the full batch reads.


## The batch and witness cycle

Rule R12a applies when every family rejects a program, an independent checker accepts it, the spec is quoted and the vendor claims it. The verdict is a compiler bug. The rule reads `catalog/legality_witness.yaml`. `confirm witness` chooses the programs to witness from the batch, namely every catalog program decided by R12 or R12a. Both rules mean "every family rejects", so the set of programs does not depend on the witnesses and the cycle terminates.

1. Run `confirm-batch`.
2. Run `witness`.
3. If the witness file changed, rerun `confirm-batch` once. A witness is keyed by the sha256 of the program source, so a changed source needs a new row.

`--check witness` reports a program decided by R12 or R12a without a witness row for its current source, and a witness row for an old source.

## Hand-edited inputs and what they invalidate

| input | rerun from |
|---|---|
| `data/findings/index.yaml`, a new finding file | `confirm-batch` through `validate`; `site-inputs` when the finding is published on the site (its citations) |
| `results/dash/atoms.json` (from `dashboard`), `results/spec_cache` | `site-inputs` |
| `catalog/mode_differences.yaml` | `support-tables` (the report rejects a class its cells contradict; `tests/cluster/test_reports.py` checks that every entry still classifies a current difference), then `confirm-batch` through `validate` |
| `catalog/expected_triage.yaml`, `catalog/omp/derivations.yaml` | `expected-report`, then `confirm-batch` through `validate` |
| `catalog/triage_27b.yaml`, `catalog/upstream_status.yaml` | `triage` |
| `catalog/triage_28.yaml` | `confirm-batch` (`confirm decide`) |
| `catalog/later_forms.yaml`, `catalog/confirm_rules.yaml`, `catalog/rulings.yaml` | `confirm-batch` through `validate` |
| `catalog/omp/claims.yaml`, `catalog/acc/claims.yaml`, `catalog/vendor_claims.yaml` | `claims`, `support-tables`, then `confirm-batch` through `validate` |
| `catalog/unlinked_bugs.yaml` | `backlog` |
| `catalog/canaries.yaml` | New canary runs. The reports compare each campaign's canary rows with it. |
| `offload/engine/prerun.py`, the gate's verdicts | `confirm-batch` through `validate` |

## What `--check` does not cover

- The measurements (`measure`, `audits`, `expected-runs`, `fuzz`, `confirm-evidence`).
- The content of the confirmer batch. `--check confirm-batch` compares the inputs hash stamped by `tools/jobs/run_regen_confirm.sh` in `results/confirm/batch_full.stamp.json`. The hash covers the rules, registry, claims, later forms, machines, witnesses, expected triage, derivations, findings and `offload/engine/confirm` code. A change to any of them without a batch rerun is reported stale. To compare content, rerun `tools/jobs/run_regen_confirm.sh` without `INSTALL` and diff `results/confirm/shards/regen.full.jsonl` against `batch_full.jsonl`.
- `validate`. `tests/confirm/test_confirm_outputs.py` checks that the document has no unexplained row.
- `dashboard` and the site pages. `--check site-inputs` covers what the pages are built from.
