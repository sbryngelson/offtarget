# catalog/omp/

The OpenMP slice of the catalog. It covers device offload only, in Fortran and C, for catalog versions 50, 52 and 60. Each file has a header that says what its rows mean. The OpenACC slice in [../acc/](../acc/README.md) has the same layout.

| file | content | kind |
|---|---|---|
| `skeleton.yaml` | directives, clauses and categories from LLVM's TableGen dump in `data/index/seed/omp.json` | generated (`offload/engine/skeleton.py`) |
| `spec_overrides.yaml` | where the specification overrides the skeleton | hand-written |
| `clauses.yaml` | clause argument grammar, the source of the generated programs | hand-written |
| `semantic_atoms.yaml` | behaviour the spec defines that no clause syntax carries | hand-written |
| `rules.yaml`, `rules_coverage.yaml` | restriction rules, and each candidate restriction sentence classified by hand | hand-written |
| `claims.yaml` | vendor claims, each with a quote from `data/index/claims/` | hand-written |
| `derivations.yaml`, `no_oracle.yaml`, `memory_modes.yaml` | expected results by hand derivation; programs with no separating oracle and why; the memory modes measured | hand-written |
| `out_of_scope.yaml` | atoms outside the device-offload scope | hand-written |
| `omp50_delta.yaml`, `port_equivalence.yaml` | what OpenMP 5.0 changes against 5.2 (see [../../docs/tooling/omp5-vs-52.md](../../docs/tooling/omp5-vs-52.md)); C ports whose Fortran derivation counts for them | hand-written |
