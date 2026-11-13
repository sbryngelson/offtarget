# Running on wingtip (shared NVIDIA host)

wingtip is a shared host with four A100 GPUs, reached with `ssh wingtip`. It has no scheduler. This page covers the resource cap that every project job runs under, the offline lane that runs CPU-only steps there, the Tioga test lane, and the GCC offload setup. The machine and toolchain data are in `catalog/machines.yaml` and `catalog/toolchains.yaml` ([toolchains.md](toolchains.md)).

## The resource cap

Every project job on wingtip runs inside one systemd user slice, `compliant.slice` (`~/.config/systemd/user/compliant.slice`). The slice caps all the jobs together:

    MemoryHigh=96G  MemoryMax=128G  MemorySwapMax=0  TasksMax=2048  CPUWeight=50  IOWeight=50

Lingering is enabled for the account (`loginctl enable-linger`), so the slice outlives the ssh session.

* A script that runs on wingtip starts with `. "$(dirname "$0")/wingtip_cap.sh" || exit 1` (`tools/jobs/wingtip_cap.sh`). The sourced file re-executes the script inside the slice. It does nothing on other hosts or when the script is already inside the slice. `tests/cluster/test_lanes.py` fails on a script under `tools/` that runs on wingtip without this line, and on any `|| true` after it. A script counts as running on wingtip if its name or directory says wingtip or it calls an NVHPC compiler.
* On a host named `wingtip*`, or one with `~/.config/systemd/user`, the script fails when the slice file or `systemd-run` is missing, instead of running uncapped.
* Remote commands from the confirmer and the legality witness are prefixed with the `access.cap` of `catalog/machines.yaml` (`tools/jobs/wingtip_capped.sh`). A test scans `offload/engine/` and `tools/` for Python that builds an ssh command without it.
* For a one-off command, run for example `tools/jobs/wingtip_capped.sh make -j2`.
* To reduce a failing NVHPC or GCC program, run `tools/jobs/run_wingtip_reduce.sh REDUCE_ARGS`. It runs `tools/reduce.py` on one free GPU ([contributing.md](contributing.md) describes reduction).
* To check the cap, run `systemctl --user status compliant.slice`. Inside a job, `cat /proc/self/cgroup` names `compliant.slice`.
* Jobs also follow these rules. They use free GPUs only, run one program per GPU through the per-GPU run lock (`COMPLIANT_RUN_SLOTS=1`), start at most four concurrent compiles across all users of the project, run under `nice`, and use each NVHPC release's own runtime libraries.

The cap protects the host from this project and does not limit other users.

## The reproduction gate and the canaries

* `tools/jobs/run_wingtip_gate.sh LIMIT_S WORKERS CAMPAIGN...` reruns the gate's planned NVHPC rows (`offload/engine/gate.py`, `tools/campaigns/gate.py run`) from a private copy of the tree. The gate checks that a failure reproduces, using rows recorded in several environments. The script uses two free GPUs, and stops if fewer are free, with at most two workers per GPU. On wingtip the gate's "another node" environment is another GPU of the same host (`one_host: true` in `machines.yaml`). Copy `results/gate/<campaign>/reruns/` back afterwards.
* Every campaign runner adds the canaries (`offload.engine.canary`). `python3 -I tools/campaigns/gate.py canaries --toolchains nvhpc nvhpc269 --xnack 0 2 --out FILE` measures them alone.
* The pre-run check (`offload.engine.prerun`) needs an AFAR front end, which wingtip lacks. A stress run on wingtip reads the stored verdict (`COMPLIANT_PRERUN_STORED=<run>/programs.jsonl`) and refuses programs that have none. A fuzz run reads stored legality checks (`COMPLIANT_FUZZ_CHECKS`).

## Offline lane

CPU-only steps run on wingtip instead of waiting for a batch node. Run the driver from a tree (the main tree or a worktree) on a Tuolumne login node:

```
tools/lanes/wingtip_offline.sh --list                     # steps, time limits, one-line purpose
tools/lanes/wingtip_offline.sh --dry-run STEP [ARGS]      # the plan; no ssh
tools/lanes/wingtip_offline.sh STEP [ARGS]                # run
tools/lanes/wingtip_offline.sh --env K=V STEP             # set a step variable
tools/lanes/wingtip_offline.sh --no-pull STEP             # leave the outputs on wingtip
tools/lanes/wingtip_offline.sh --trace --no-pull STEP     # report manifest gaps
tools/lanes/wingtip_offline.sh --setup                    # build the lane's Python environment, once
```

The driver only copies files and starts the step over ssh. The lane consists of four files:

* `tools/lanes/wingtip_offline.sh` is the driver.
* `tools/lanes/wingtip_offline.py` is the manifest side.
* `tools/lanes/wingtip_offline.yaml` is the manifest.
* `tools/lanes/wingtip_offline_run.sh` runs on wingtip.

**Steps.** The `steps:` key of the manifest lists them, and `--list` prints them. They fall into these groups: the regeneration check (`regen-check`), the confirmer (`confirm-batch`, `widen-batch`, `confirm-decide`, `confirm-index`, `confirm-backlog`, `confirm-triage`, `confirm-validate`), `citations`, `harvest2-rules`, the site (`site-inputs`, `site-build`) and `tests`.

**What stays on Tuolumne.** These stay on Tuolumne:

* anything that needs a GPU or a Tuolumne compiler
* the legality pre-check (`offload/engine/prerun.py`, which uses AFAR's front end)
* the gate report's review queue
* the dashboard datasets (`tools/site/dashboard_data.py` runs elided forms with amdflang and gfortran)
* the tests that the `tests` step leaves behind

**How a run works.**

1. Before copying anything, it checks that wingtip has `compliant.slice`, `systemd-run` and the lane's Python, and refuses to run if any is missing.
2. It copies the tree's tracked and new files as they are on disk, plus HEAD as a git bundle, to the lane directory `lane_root/<tree name>` (`WINGTIP_LANE` names another lane). It copies exactly the step's `inputs` under `results/`, `corpus/` and `spec/` to the shared `data_root`, and the lane's `results/`, `corpus/` and `spec/` link there. A directory input is mirrored, and files and globs are added. The manifest sets `data_root` and `lane_root`.
3. `wingtip_offline_run.sh` runs the step inside `compliant.slice`, under `nice -n 10` and `timeout --kill-after=10 LIMIT` (the step's `limit`). The lane's Python comes first on `PATH`, and `COMPLIANT_ROOT` is set to the lane.
4. After a successful run it copies the step's `outputs` back. Outputs under `results/` go into the main tree's `results/`, and the rest go into the tree. The log is `results/offline/<step>.<lane>.<time>.log`.

**Sealed sets.** The lane and `tools/lanes/wingtip_sync.sh` do not copy `data/bench/<set>/` when `data/bench/<set>/SEAL` exists and `catalog/sealed_spent.yaml` does not list the set as scored. A step input inside such a set is refused.

**Python.** `data_root/env` holds the lane's Python (micromamba, conda-forge), with the versions the tests expect plus pytest-xdist. `--setup` creates it.

**The guard.** Each run records the programs the step executes (strace, execve only). The step fails with exit 3 if it tried to run a program that wingtip does not have, such as an AFAR or CCE front end or anything under `/usr/tce`. A manifest entry `exec_guard: false` (used by `tests`) makes the guard only report.

**Keeping the manifest exact.** `--trace --no-pull STEP` runs the step under strace and names every gap when it returns. A gap is either a git-ignored file that the step opened or checked and the manifest does not name, or a file that the step looked up and did not find but this tree has. A run with gaps exits 4. Trace on a data directory that holds only the manifest's inputs. `tests/cluster/test_lanes.py` checks that every step's inputs exist in the tree and that its outputs are where the Tuolumne step writes them.

**Tests.** `tools/lanes/wingtip_offline.sh tests [TARGETS]` runs `tools/lanes/wingtip_suite.py` on wingtip. That runs `pytest -m "not gpu"` with xdist (`-n 16 --dist worksteal`; `--env WORKERS=N` changes the worker count), leaving out the tests named in the step's `tuolumne_tests`. Those tests need AFAR or CCE front ends, the harness node check for the fake gfx942 toolchains, the Tuolumne gfortran version, or the application clones. The `serial_tests` then run alone. The output goes to `results/offline/suite/<lane>.<time>/`:

| file | content |
|---|---|
| `wingtip.txt` | node ids that passed on wingtip |
| `tuolumne.txt` | node ids left for Tuolumne (GPU-marked, named, or skipped on wingtip) |
| `failed.txt`, `summary.json` | failures and totals |

Run the left-over tests with `python3 -I -m pytest $(cat tuolumne.txt)` in a batch job, or on Tioga (next section). The run fails if a test skipped because a git-ignored input was missing.

**Limits.** A lane runs one step at a time, enforced by a lock. A second run waits 30 s and then exits 75. All lanes share the data directory. A step's processes count against the slice caps together with every other project job on wingtip, so the suite defaults to 8 workers.

## Tests left for Tuolumne, on Tioga

Most of the tests in `tuolumne.txt` need only AFAR's front end, gfortran 13.3.1 or a git-ignored input, not an MI300A. Run this from a tree on a Tuolumne login node:

```
tools/lanes/run_tioga_suite.sh results/offline/suite/<run>
```

The script copies the tree to Tioga, starts ssh, and runs the tests in one foreground job (`flux run -q pdebug -N1 -n1 -t 60m`) from that copy, which is deleted at the end. The copy leaves out `results/`, `spec/`, every sealed set and every holdout set. It includes only the application sources that the `tioga-inputs` tests read.

`RULES` in `tools/lanes/tioga_suite.py` maps a node-id prefix to a class, and the longest matching prefix wins. An id with no rule stays on Tuolumne. The classes are:

| class | how it runs |
|---|---|
| `tioga` | as is (dashboard and site page checks, wild-bench parser, ROCm version record, spec text) |
| `tioga-afar` | with AFAR's run-time libraries on `LD_LIBRARY_PATH` (flang and clang oracles, legality tests, fuzz base programs) |
| `tioga-nogpu` | with `ROCR_VISIBLE_DEVICES` empty: the fake toolchains of these tests target gfx942 and the harness node check refuses them on gfx90a |
| `tioga-inputs` | with the application sources (test_apps) |
| `mi300a` | stays on Tuolumne: a gfx942 device run or `HSA_XNACK=1` |
| `sealed` | stays on Tuolumne: unscored sealed or holdout data |
| `skips` | skips on every machine until the machine list or spec level changes |

The four runnable classes run side by side in one job (`tools/lanes/tioga_suite_job.sh`, each pytest under `timeout`). The page checks start headless Chrome processes that outlive their tests, and the job script ends them. The results come back to `<run>/tioga/`. That directory holds `tioga.txt` (the ids that passed on Tioga), `failed.tsv`, and a new `tuolumne.txt` with every id that did not pass on Tioga plus the classes that stay.

The `tioga-nogpu` class tests the harness logic with the node check out of the way. It is not a run on the device. The ids that stay need the Tuolumne job.

## GCC with offloading (`gcc_sm80`; Tioga: `gcc_g90`)

GCC is a compiler under test only, never a legality witness (`catalog/toolchains.yaml` `families.gcc.under_test_only`).

* Build: `tools/jobs/gcc_offload_build.sh` builds GCC from the GCC 16.2.0 and newlib tarballs and nvptx-tools, which are fetched on Tuolumne. Use `TARGET=nvptx` for wingtip and amdgcn for Tioga. The build runs inside the cap.
* Flags on wingtip: `-fopenmp -foffload=nvptx-none -foffload-options=nvptx-none=-march=sm_80 -foffload-options=nvptx-none=-latomic`. OpenACC uses `-fopenacc`. At run time, put the install's `lib64` on `LD_LIBRARY_PATH` and CUDA's `bin` on `PATH`, so that `nvptx-as` can verify PTX. `GOMP_DEBUG=1` prints each kernel launch.
* Memory: GCC is used with separate memory only. It has no managed-memory option, and `requires unified_shared_memory` drops the A100 (no pageable memory access). The program then falls back to the host, which is an error under `OMP_TARGET_OFFLOAD=mandatory`.
* `-latomic` is needed on nvptx. Without it the offload link leaves unresolved the libatomic calls that GCC generates (`lastprivate(conditional)`, C `reduction(&&)` and `reduction(||)`). On amdgcn the build makes no device libatomic, so 1- and 2-byte atomic updates remain link failures in the fuzz rows. Both are observations, not findings.
* Lane: `tools/jobs/run_gcc_lane.sh` (`TC=gcc_sm80`) runs the smoke subset (`tools/campaigns/gcc_subset.py`) through the harness on one free GPU under the run lock, then runs the canaries if `CANARIES=1`. `tools/jobs/run_gcc_sweep.sh` runs the compile-only sweep and link probes, which need no GPU. The rows go to `results/gcc/gcc_sm80/` and are copied back to the main tree's `results/gcc/`.
* Tioga: use `TC=gcc_g90` and run one foreground `flux run -q pdebug` at a time, never chained.
