# tools/campaigns

Drivers for measurement campaigns, corpus harvests, audits and program generators. Most run with `python3 -I` from the repository root, and steps that compile or run need a compute node. The generic runner is `tools/campaign.py`, and the cluster submission scripts are in [../jobs/](../jobs/README.md). Run a script with `--help` to see its subcommands.

| role | scripts |
|---|---|
| matrix and baseline runs | `run_matrix.py` (run, rerun, merge, replace), `presence_x1.py`, `widen.py` (widened catalog) |
| reproduction gate | `gate.py` |
| generated program families | `fuzz.py`, `stress.py`, `kbody.py`, `nested.py`, `oop.py`, `combination_matrix.py` |
| expected values | `c_slices.py` |
| corpus harvest and ingestion | `harvest.py`, `harvest2.py`, `harvest_known.py`, `harvest_probe.py`, `hecbench.py`, `app_bench.py`, `fresh_bench.py`, `index_corpus.py` |
| audits | `oracle_audit.py`, `map_audit.py`, `nvhpc_audit.py`, `stress_audit.py`, `c_coverage.py` |
| GCC lane | `gcc_lane.py`, `gcc_compile_sweep.py`, `gcc_probe.py`, `gcc_subset.py`, `parity.py` |
| single-defect studies | `malloc_dd.py` (AFAR device malloc), `devtemps.py` (device heap temporaries), `nvhpc_managed_probe.py`, `ftn_cif_split.py` (CCE ftn CIF records) |
| nested-data findings | `nested_try.py` (hand-written reductions), `nested_findings.py` |

For campaign design, see [nested-data](../../docs/tooling/nested-data.md) and [expected behaviour](../../docs/tooling/expected-behaviour.md).
