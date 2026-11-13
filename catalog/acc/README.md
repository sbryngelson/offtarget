# catalog/acc/

The OpenACC 3.4 slice of the catalog. It covers device offload only and uses the layout of [../omp/](../omp/README.md). Each file has a header that says what its rows mean.

| file | content | kind |
|---|---|---|
| `skeleton.yaml` | directives and clauses from the TableGen dump in `data/index/seed/acc.json` | generated (`offload/engine/skeleton.py`) |
| `spec_overrides.yaml` | where the specification overrides the skeleton | hand-written |
| `clauses.yaml` | clause argument grammar, the source of the generated programs | hand-written |
| `semantic_atoms.yaml` | behaviour the spec defines that no clause syntax carries | hand-written |
| `rules.yaml` | restriction rules | hand-written |
| `claims.yaml` | vendor claims, ingested from the HPE `intro_openacc(7)` pages, the CCE 19.0.0 release notes and the OLCF Frontier guide | hand-written |
| `no_oracle.yaml`, `out_of_scope.yaml` | programs with no separating oracle and why; atoms outside the device-offload scope | hand-written |

The OpenACC slice has no `rules_coverage.yaml`, `derivations.yaml` or `memory_modes.yaml`. Only the OpenMP slice has files with those names.
