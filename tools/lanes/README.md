# tools/lanes

These scripts run CPU-only work on wingtip instead of in a Tuolumne batch job, and run the tests that wingtip leaves behind on Tioga. [wingtip](../../docs/tooling/wingtip.md) describes the procedure.

| file | role |
|---|---|
| `wingtip_offline.yaml` | the steps the lane can run: command, time limit, inputs, outputs |
| `wingtip_offline.py` | reads the manifest (plan, copy lists) |
| `wingtip_offline.sh` | entry point from a Tuolumne login node: `tools/lanes/wingtip_offline.sh --list`, `--dry-run STEP`, `STEP` |
| `wingtip_offline_run.sh` | the wingtip half, which runs inside `compliant.slice` with a time limit |
| `wingtip_sync.sh` | rsync the tree to wingtip (`push`) and fetch results (`pull`) |
| `wingtip_suite.py` | the test suite's CPU-only part, in parallel; writes the list left for Tuolumne |
| `run_tioga_suite.sh` | copy that list to Tioga, run it, pull the results back |
| `tioga_suite.py` | split the list by class and merge the Tioga results (`split`, `after`) |
| `tioga_suite_job.sh` | the Tioga job that `run_tioga_suite.sh` starts |
