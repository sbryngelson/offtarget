# tools/wild

Scripts for the in-the-wild benchmark, `data/bench/wild/`: bug cases taken from public reports and from workarounds in source code.

| script | role |
|---|---|
| `wild_bench.py` | run the cases: parse, legality, runs |
| `wild_split.py` | split cases into a dev half and a held-out half (`split.yaml`) |

`tools/jobs/run_wild.sh` runs them on a compute node.
