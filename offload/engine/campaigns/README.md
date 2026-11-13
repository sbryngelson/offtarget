# offload/engine/campaigns

Campaigns written against the interface in `offload/engine/campaign.py`. A campaign declares how its programs are generated and run. The shared steps then take it through generation, pre-run check, witness, legality, run, reproduction gate, confirmation, report and a findings plan.

Each module registers itself with `campaign.register` and is listed in `campaign.MODULES`. Run one with `tools/campaign.py NAME gen|run|gate|submit`.

- `nested.py` pointer-linked data structures mapped to the device, in C and Fortran, OpenMP 5.2 and OpenACC 3.4 (`nested_gen.py`; `docs/tooling/nested-data.md`).
- `oop.py` derived-type and object-oriented offload families (`oop_gen.py`). Its program list is fixed.
- `hecbench.py` ORNL HeCBench OpenMP benchmarks built and run on every toolchain and memory mode (builds and reports in `engine/hecbench*.py`).

Read `campaign.py` first, then the smallest module, `oop.py`.
