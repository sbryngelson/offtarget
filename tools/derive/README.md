# tools/derive

Scripts that compute tables and reports from results and committed inputs. Each is either part of the regeneration chain or a check on it, as [regenerate](../../docs/tooling/regenerate.md) explains.

| script | writes or checks |
|---|---|
| `support_table.py` | `results/support_table.md` and `.csv` |
| `rules_coverage.py` | `results/rules-coverage.md` |
| `ompvv_compare.py` | omp_vv baseline against the support table, per atom |
| `omp50_delta.py` | [omp5-vs-52](../../docs/tooling/omp5-vs-52.md) and [omp-50-vs-52-results](../../docs/tooling/omp-50-vs-52-results.md) |
| `expected.py` | independent expected values for fuzz and catalog programs ([expected behaviour](../../docs/tooling/expected-behaviour.md)) |
| `claims.py` | vendor claims in the generic format (`ingest`, `check`) |
| `finding_matrix.py` | the site's finding matrix: cases, run plan, pack (`cases`, `plan`, `pack`) |
| `toolchains_gen.py` | files generated from `catalog/toolchains.yaml` (`--check` for staleness) |
| `confirm_batch_changes.py` | changes in the confirmer's verdicts between rebuilds |
| `confirm_link_diff.py` | changes in the confirmer's finding links between two trees |
