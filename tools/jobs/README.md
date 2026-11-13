# tools/jobs

Cluster job scripts, which use flux on Tuolumne and Tioga and run directly on wingtip. Each script's header has its submit line. The per-machine toolchain lists come from `toolchains.sh`, which `tools/derive/toolchains_gen.py` generates from `catalog/toolchains.yaml`. Do not edit it.

The regeneration chain ([regenerate](../../docs/tooling/regenerate.md)) uses:
`run_regen_confirm.sh`, `run_widen_confirm.sh`, `run_confirm_shards.sh`, `run_matrix_xnack1.sh`, `run_fuzz_seeds.sh`, `run_gate.sh`, `run_wingtip_gate.sh`.

The lane tests (`tests/cluster/`) use `wingtip_cap.sh` (sources the user-slice cap on wingtip), `wingtip_capped.sh` (runs one command inside it), `run_wingtip.sh`, `run_wingtip_gate.sh`, `run_mfc.sh`, `toolchains.sh`, and the offline lane in `tools/lanes/`.

Campaigns are submitted with `run_campaign.sh`, `run_wingtip_campaign.sh` and `campaign_remote.sh`. The last one pushes a private copy of the tree and pulls the results.

All other scripts are the run recipes of past campaigns (matrix and copy-mode runs, GCC, parity, nested-data, fortran-oop, wild, regression runs, audits). They record how those results were produced and are not part of the toolchain.
