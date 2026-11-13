# data/evidence

Small experiments whose programs and output findings and reports cite as evidence; the files stay as they were run. They are not part of the `offload` tool. The `gate_probe/` scripts also build `catalog/gate_queue.yaml` and its report, and tests import them.

| folder | cited by |
|---|---|
| `acc_c_probe/` | three findings in `data/findings/`, `tests/cluster/` |
| `dataenv_probe/` | the fuzz findings in `data/findings/fuzz/`, `catalog/`, `data/reports/fuzz-stress.md` |
| `gate_probe/` | findings, `catalog/gate_queue.yaml`, `data/reports/gate-queue.md`, tests |
| `lead_probe/` | findings in `data/findings/` and `data/findings/stress/` |
| `triage_probe/` | findings in `data/findings/`, `data/reports/triage-2026-10.md` |
| `omp_vv_probe/` | `tools/jobs/run_omp_vv_probes.sh` |
