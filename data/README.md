# data/

Evidence, benchmark inputs and generated tables that the engine and the website read. The engine's configuration is in [../catalog/](../catalog/), not here. [../docs/how-it-works.md](../docs/how-it-works.md) shows how the pieces fit together, and [../docs/tooling/regenerate.md](../docs/tooling/regenerate.md) says how to rebuild the generated files.

| directory | role | kind |
|---|---|---|
| [findings/](findings/) | one reproducer per confirmed compiler defect, plus the findings index | evidence |
| [evidence/](evidence/) | the small experiments findings cite, with their output | evidence |
| [vendor/](vendor/) | the check programs that re-run each finding on each compiler and GPU, and their compact results | evidence, partly generated |
| [bench/](bench/) | benchmark sets; the public repository has only the programs findings name | input; the `*-holdout`, `fresh` and `fresh2` sets are sealed |
| [index/](index/) | directive tables from the compilers' sources, snapshots of the vendor documents behind claims, corpus index | input and generated |
| [licenses/](licenses/) | licence texts for the third-party programs under `bench/` | input |
| [reports/](reports/) | generated tables, run logs and write-ups | generated |

A sealed set is not opened until it has been scored once. [bench/README.md](bench/README.md) lists each set, and [../catalog/sealed_spent.yaml](../catalog/sealed_spent.yaml) lists the ones already scored. Raw measurements live in `results/`, which is git-ignored. The files here are committed subsets and summaries of them.
