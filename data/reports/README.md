# data/reports/

Generated tables and write-ups, and the run logs and probe programs behind them. Most files are produced by a step of `tools/regenerate.py` from measurements in `results/` (git-ignored); the step, the command and the staleness check for each are in [../../docs/tooling/regenerate.md](../../docs/tooling/regenerate.md). Do not edit a generated file by hand.

| files | what | read by code |
|---|---|---|
| `c-support-table.md`, `acc-support-table.md`, `acc-c-support-table.md`, `widen-support-table.md` and the `*_support_table.csv` copies | per atom and toolchain, the measured outcome against the vendor claim | the CSVs: the dashboard data |
| `confirm-validation.md`, `confirm-selfcheck.yaml`, `triage-2026-10.md`, `unlinked-bugs.md`, `rulings.md` | confirmer results, triage decisions and legality rulings | `confirm-selfcheck.yaml` by the confirmer's validate step; `rulings.md` by the rulings registry |
| `oracle-audit.md`, `expected-sources.md`, `gate-queue.md`, `gate-changes/*.tsv` | expected-value audits and the reproduction gate's decisions and changes | the gate report and batch-change tools |
| `fuzz-*.md`, `fuzz-stress.md`, `fuzz-stress-audit/`, `fuzz5-oop-afar/` | fuzz campaign reports and the programs behind them | `fuzz-base-language.md` by the fuzz tools and the dashboard data; `fuzz-stress-audit/` by the stress audit |
| `hecbench.md` | HeCBench campaign write-up | the campaign tools |
| `apps/`, `kbody-jobs/`, `kbody-observations/`, `nested-visibility/`, `harvest-known/`, `fresh-drafts/` | logs, reduced programs and job scripts from single investigations | `kbody-jobs/` by the kernel-body tools; the rest not read |

`rulings.md` is a hand-kept ledger of legality and spec-reading rulings, not a generated file.
