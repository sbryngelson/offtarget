# HeCBench: real-code failures for the linter (the `hecbench` campaign)

Why: the linter's weak spot is the lack of independent real-code failures.
HeCBench (https://github.com/ORNL/HeCBench, BSD-3-Clause, commit 8f44ff3e69fa003f870963045988190a275534cb)
has 367 `src/*-omp` benchmarks: C and C++ with OpenMP offload, no CUDA, with `Makefile.aomp`. This note
describes how they were turned into labelled test material, the sealed split, and the dev half's results.
It reports the **dev half only**.

Registered campaign: `hecbench` (`offload/engine/campaigns/hecbench.py`; build and run in
`offload/engine/hecbench_run.py`; the pure part in `offload/engine/hecbench.py`; the report rules in
`offload/engine/hecbench_report.py`; the companion tool `tools/campaigns/hecbench.py`). Tests: `tests/bench/test_hecbench*.py`,
`tests/lint/test_lint_hecbench_source.py`, `tests/bench/test_holdout_exposure.py` (the sealed half).

## Procedure (split and recipe rules fixed before the first full run; run limits tuned on a dev smoke; no per-benchmark tuning)

1. **Pin.** The clone is `corpus/apps/HeCBench-ornl` (git-ignored, shared tree), commit above.
   `tools/campaigns/hecbench.py check` verifies it.
2. **Recipe.** `tools/campaigns/hecbench.py derive` runs `make -n -B -f Makefile.aomp CC=HECB_CC CXX=HECB_CXX
   FC=HECB_FC OPTIMIZE=yes DEBUG=no VERIFY=no DEVICE=gpu run` in each benchmark directory (the compiler
   variables are markers, so no compiler runs) and reads the printed commands (`parse_dry_run`). Of the compile
   flags only `-D`, `-U`, `-I`, `-isystem`, `-include` and `-std=` are kept, of the link flags `-l` and `-L`.
   Every other flag (the vendor's offload flags, `-O`, `-g`, `-W`, `-f`, `-m`) is dropped and the toolchain's own
   flags from `catalog/toolchains.yaml` take its place, with `-O2` (the apps campaign's level). A `.c` source
   compiles with the C driver and a `.cpp` source with the C++ driver of the toolchain
   (`cxx` of the registry: `amdclang++`, `crayCC`, `nvc++`, `g++`; C's flag templates); a C++ standard flag is
   not passed to a C source. The distinct dropped flags are recorded per benchmark (`dropped`).
3. **Run command.** The arguments of the Makefile's `run` target. When the source reads a repeat-like count
   from `argv` (`repeat`, `iter`, `reps`, `loops` ... `= atoi(argv[k])`), that argument is replaced by 2 so a
   run takes seconds. Time limit: 30 s per run, 900 s per compile (a run is not repeated: the reproduction gate runs a failure
   again in four environments). The program runs in a directory that links the benchmark's own files;
   `OMP_TARGET_OFFLOAD=mandatory`. On AMD at most two programs run on one GPU at a time (`gpu_slot`), so a
   run's time is not the contention of the compiles around it; on wingtip the harness's run lock allows one
   per GPU.
4. **Exclusions** (reason recorded, not counted as failures; `offload.engine.hecbench.classify`): `no-recipe`
   (`make -n` printed no compile command), `cuda-only-dependency` (a CUDA, HIP, Thrust, cuBLAS ... include or
   library, `nvcc`/`hipcc` in the build), `needs-external-library` (MPI, OpenCV, FFTW, MKL ... include or any
   `-l` beyond libm/pthread), `needs-data-file` (an argument names a file that is not in the repository, or the
   program opens a literal input file that is not; `out*`/`result*` arguments are outputs), `other-language`
   (Fortran). One more rule is applied after the measurement, to every program alike
   (`non_compiler_programs`): a program whose every attempted cell fails to compile or link on a missing
   header or file, or on an undefined non-runtime symbol, is moved to the excluded programs.
5. **Oracle.** A run is correct when it exits 0, prints no failure text (`FAIL`, a non-zero `mismatch`
   count, "verification failed" ...) and agrees with the **serial host reference**: the same sources built
   with the host `gcc`/`g++` without OpenMP (pragmas ignored, `data/bench/hecbench/stubs/omp.h` replacing the
   runtime calls), run with the same arguments (90 s limit). If the reference prints `PASS`, the candidate must;
   otherwise the lines that carry a result word and no timing word are compared, numbers within 1e-3 relative.
   A benchmark whose reference does not build, run, or pass its own check has no oracle beyond the failure
   text (recorded per row as `oracle`). The reference is an output oracle, never a legality witness
   (docs/tooling/contributing.md section 2: no gcc/gfortran with -fopenmp as a witness; omp_vv is not used).
6. **Split.** Dev iff `sha256(directory name)` is even (`data/bench/hecbench/split.yaml`, committed with the dev ids
   and a hash of each sealed name, before the first run). The sealed half is
   `data/bench/hecbench-holdout/` (SEAL and recipes; its outcomes file is git-ignored), `catalog/hecbench_holdout_excluded.yaml`,
   and `tests/bench/test_holdout_exposure.py` (hashes only). `tools/campaign.py` refuses
   `report`, `cluster`, `confirm` and `findings-plan` on a run that holds any program of it (whatever its name), `tools/campaigns/hecbench.py report` refuses it, and
   `tools/campaigns/hecbench.py seal` writes the git-ignored outcomes file and the SEAL without printing anything about them.
7. **Matrix.** For every ok benchmark, every toolchain of the registry and every memory mode the machine
   defines (`caps.targets()`): Tuolumne AFAR, CCE 19, 20, 21 and 21.0.4, copy (HSA_XNACK=0) and unified
   (HSA_XNACK=1); Tioga AFAR, CCE 19, 20, 21 and GCC, copy; wingtip NVHPC 25.11 and 26.9 (separate and managed)
   and GCC, separate. On AMD one build serves both modes of a toolchain.
8. **Evidence.** A failing cell is evidence only if (a) the reproduction gate confirmed it (four environments;
   (a), (b), (d) on one node or GPU, (c) on another; compile failures of one signature inherit the verdict of
   the sampled ones, as everywhere) and (b) a compiler of another family ran the same program correctly in the
   cell's own memory mode (copy, or unified/managed). Everything else is
   *unconfirmed* with its reason. The compiler under test is never its own witness. A *failure signature* is
   (family, class, normalized message or check line).

## Licences

No HeCBench source is tracked. See THIRD_PARTY_NOTICES.md ("HeCBench") and `data/licenses/ORNL__HeCBench.LICENSE`.
Two licence classes are *withheld*: `gpl-style` (the README's list, or an own GNU or Mozilla licence file under
any of its usual names: LICENSE, LICENCE, COPYING) and `restricted` (an own licence file that forbids commercial
use or redistribution: "non-commercial use licence", "research use only", "academic use only"; a grant "for any
purpose, commercial or non-commercial" is permissive). Their benchmarks are tracked as ids with their licence
class and status only; their recipes stay in the git-ignored `results/hecbench/`, they are named in no licence
notice as redistributed material, and they are left out of the linter's `hecbench-dev` source. In the dev half
15 are `gpl-style` and 1 (`vanGenuchten-omp`, "Dhara Modeling Software, Non-Exclusive, Non-Commercial Use
License") is `restricted`. The review counted two non-commercial programs; the only other text with such a
word is the GPL's own "noncommercially" in a file named `LICENCE` (`lsqt-omp`), which the earlier classifier,
reading only `LICENSE`, took for BSD: it is `gpl-style` now (and is excluded anyway as needing a data file).

<!-- results:begin -->
## Results (dev half only)

Dev programs: 193. Recipe status: cuda-only-dependency 2, needs-data-file 18, needs-external-library 1, no-recipe 1, ok 171. Licence class: bsd3 136, gpl-style 15, own-permissive 41, restricted 1.

Moved to the excluded programs after the runs (a header or library is missing on every toolchain): 2.

### Outcome classes per toolchain and memory mode (cells of the programs that stay)

| toolchain | mode | built | ok | compile_reject | ice | link_failure | run_error | crash | timeout | wrong_answer | harness_error |
|---|---|---|---|---|---|---|---|---|---|---|---|
| afar | copy | 169 | 136 | 0 | 0 | 0 | 8 | 3 | 13 | 9 | 0 |
| afar | unified | 169 | 129 | 0 | 0 | 0 | 8 | 3 | 15 | 14 | 0 |
| afar_g90 | copy | 169 | 130 | 0 | 0 | 0 | 8 | 3 | 19 | 9 | 0 |
| cce19 | copy | 169 | 117 | 0 | 0 | 0 | 7 | 6 | 24 | 15 | 0 |
| cce19 | unified | 169 | 116 | 0 | 0 | 0 | 7 | 5 | 22 | 19 | 0 |
| cce19_g90 | copy | 169 | 111 | 0 | 0 | 0 | 7 | 6 | 31 | 14 | 0 |
| cce20 | copy | 166 | 114 | 0 | 0 | 0 | 7 | 5 | 24 | 16 | 0 |
| cce20 | unified | 168 | 113 | 0 | 0 | 0 | 7 | 5 | 25 | 18 | 0 |
| cce20_g90 | copy | 169 | 115 | 0 | 0 | 0 | 7 | 5 | 28 | 14 | 0 |
| cce21 | copy | 169 | 124 | 0 | 0 | 0 | 12 | 1 | 19 | 13 | 0 |
| cce21 | unified | 169 | 112 | 0 | 0 | 0 | 10 | 2 | 30 | 15 | 0 |
| cce21_4 | copy | 168 | 124 | 0 | 0 | 0 | 12 | 1 | 17 | 14 | 0 |
| cce21_4 | unified | 168 | 117 | 0 | 0 | 0 | 10 | 2 | 22 | 17 | 0 |
| cce21_g90 | copy | 169 | 116 | 0 | 0 | 0 | 11 | 1 | 30 | 11 | 0 |
| gcc_g90 | copy | 163 | 69 | 0 | 4 | 2 | 11 | 13 | 56 | 14 | 0 |
| gcc_sm80 | copy | 93 | 44 | 0 | 2 | 0 | 11 | 1 | 34 | 3 | 0 |
| nvhpc | copy | 95 | 61 | 2 | 3 | 0 | 6 | 1 | 19 | 8 | 0 |
| nvhpc | unified | 81 | 55 | 3 | 3 | 0 | 5 | 2 | 14 | 5 | 0 |
| nvhpc269 | copy | 77 | 54 | 3 | 2 | 0 | 3 | 1 | 12 | 7 | 0 |
| nvhpc269 | unified | 86 | 56 | 2 | 4 | 0 | 3 | 2 | 17 | 8 | 0 |

`built` is the cells whose compile and link succeeded. A compile that exceeds its limit is a `timeout`.

### Evidence

Gate verdicts of the failing cells (one per cell, compile failures inheriting by signature): confirmed 213, environment 18, nondeterministic 154, not_reproduced 29, unchecked 21.

Evidence cells (gate confirmed and a witness of another family in the same mode): 157 (49 without the 30 s time-outs). Unconfirmed failing cells: 815 (no compiler of another family ran the program correctly in this mode: 535; the gate did not confirm it (environment): 18; the gate did not confirm it (nondeterministic): 154; the gate did not confirm it (not_reproduced): 29; the gate did not confirm it (only environments a,b ran): 4; the gate did not confirm it (only environments a,b,c ran): 1; the gate did not confirm it (only environments a,b,d ran): 49; the gate did not confirm it (only environments c ran): 2; the gate did not confirm it (unchecked): 23).

### Failure signatures: 16 distinct, 7 with no finding of a matching message

| family | class | signature | programs | toolchains | existing finding (same message) | related (same family and class) |
|---|---|---|---|---|---|---|
| gcc | timeout | timeout | ace-omp, bezier-surface-omp, binomial-omp, boxfilter-omp, bspline-vgh-omp, burger-omp, che-omp, conversion-omp, divergence-omp, feynman-kac-omp, fhd-omp, gaussian-omp, goulash-omp, gpp-omp, grrt-omp, hausdorff-omp, hellinger-omp, ising-omp, lif-omp, overlay-omp, page-rank-omp, pnpoly-omp, randomAccess-omp, rmsnorm-rope-omp, simplemoc-omp, sph-omp, surfel-omp, winograd-omp | gcc_g90 | none | nested/gcc-acc-c-exit-data-of-a-pointer-array-element-target-hangs.c |
| cce | timeout | timeout | addBiasResidualLayerNorm-omp, aop-omp, axpby-omp, bezier-surface-omp, boxfilter-omp, burger-omp, convolutionSeparable-omp, doh-omp, gamma-correction-omp, hausdorff-omp, lif-omp, logprob-omp, nbody-omp, overlay-omp, page-rank-omp, reaction-omp, rotary-omp, scatterAdd-omp, sundials-omp, winograd-omp | cce19, cce19_g90, cce20, cce20_g90, cce21, cce21_4, cce21_g90 | none | clang-c-linear-directive-name-hang.c, fuzz/s1-9914-cce19.f90 |
| afar | timeout | timeout | burger-omp, f16sp-omp, gamma-correction-omp, rotary-omp, scatterAdd-omp | afar, afar_g90 | none | afar-clang-requires-device-safesync-hang.c, clang-c-linear-directive-name-hang.c |
| gcc | crash | SIGABRT: Memory access fault by GPU | dct8x8-omp, radixsort-omp, sobol-omp, sort-omp, upsample-omp | gcc_g90 | nested/gcc-c-declare-mapper-pointer-member-section-gpu-fault.c | oop/gcc-polymorphic-dispatch-abort.f90, oop/gcc-pdt-length-parameter-abort.f90 |
| afar | crash | SIGABRT: memory access fault by GPU | axpby-omp, sobol-omp, sort-omp | afar, afar_g90 | afar-xnack1-atomic-min-nested-parallel.f90, fuzz/s1-4339-afar.f90 | catalog/afar-flang-absent-optional-target-crash.f90, catalog/defaultmap-present-private-array-abort.f90, nested/afar-flang-pointer-root-allocatable-component-enter-data-fault.f90 |
| cce | crash | SIGABRT: Memory access fault by GPU | lci-omp, p4-omp, sobol-omp | cce19, cce19_g90, cce20, cce20_g90, cce21, cce21_4, cce21_g90 | catalog/cce-acc-stop-in-compute-crash.f90, catalog/cce-acc-allocate-in-compute-crash.f90, fresh/cce-list-directed-print-in-target-copy-crash.f90, harvest/cce-acc-declare-create-module-allocatable-xnack1-fault.f90, oop/cce-copy-alloc-component-section-fault.f90 | cce-acc-init-set-runtime-assert.f90, cce-c-map-present-assert.c, cce-c-dist-schedule-segv.c, catalog/cce-flang-stop-in-target-crash.f90 |
| gcc | crash | SIGABRT: GCN Kernel Aborted | crs-omp, p4-omp, tensorT-omp | gcc_g90 | none | oop/gcc-polymorphic-dispatch-abort.f90, oop/gcc-pdt-length-parameter-abort.f90, nested/gcc-c-declare-mapper-pointer-member-section-gpu-fault.c |
| gcc | ice | ice: ltoN: internal compiler error: Segmentation fault | addBiasResidualLayerNorm-omp, f16atomic-omp, gelu-omp | gcc_g90 | harvest/gcc-c-target-data-struct-pointer-section-ice.c | harvest/gcc-c-target-data-two-maps-ice.c, harvest/gcc-teams-simd-matmul-allocatable-ice.f90, stress/gcc-declare-target-allocatable-component-ice.f90, nested/gcc-c-always-on-pointer-member-section-ice.c |
| gcc | crash | SIGABRT: Aborted | aop-omp | gcc_g90 | nested/gcc-c-declare-mapper-pointer-member-section-gpu-fault.c | oop/gcc-polymorphic-dispatch-abort.f90, oop/gcc-pdt-length-parameter-abort.f90 |
| gcc | ice | tree-ssanames.cc:355 | f16sp-omp | gcc_g90 | hecbench/gcc-c-float16-array-in-target-lto-ice.c | harvest/gcc-c-target-data-two-maps-ice.c, harvest/gcc-c-target-data-struct-pointer-section-ice.c, harvest/gcc-teams-simd-matmul-allocatable-ice.f90, stress/gcc-declare-target-allocatable-component-ice.f90 |
| gcc | link_failure | diagnostic: <path> error: too few operands for instruction | popcount-omp | gcc_g90 | hecbench/gcc-c-swar-popcount-assembler-error.c | gcc/gcc-c-omp60-unimplemented-rejected.c, gcc/gcc-omp60-unimplemented-rejected.f90, gcc/gcc-c-omp60-undocumented-rejected.c, gcc/gcc-omp60-undocumented-rejected.f90 |
| gcc | link_failure | link_undefined_symbol: other symbol X | assert-omp | gcc_g90 | none | gcc/gcc-c-omp60-unimplemented-rejected.c, gcc/gcc-omp60-unimplemented-rejected.f90, gcc/gcc-c-omp60-undocumented-rejected.c, gcc/gcc-omp60-undocumented-rejected.f90 |
| gcc | run_error | exit_status=1: libgomp: OMP_TARGET_OFFLOAD is set to MANDATORY, but device | openmp-omp | gcc_g90 | gcc/gcc-c-target-in-task-mandatory-device-not-found.c, gcc/gcc-target-in-task-mandatory-device-not-found.f90 | gcc/gcc-acc-detach-delete-attach-underflow.f90, gcc/gcc-acc-c-detach-delete-attach-underflow.c, harvest/gcc-acc-declare-create-allocatable-not-mapped.f90, nested/gcc-acc-c-parent-and-shared-pointee-one-directive.c |
| gcc | run_error | exit_status=1: libgomp: internal libgomp cbuf error | flip-omp | gcc_g90 | none | gcc/gcc-c-target-in-task-mandatory-device-not-found.c, gcc/gcc-target-in-task-mandatory-device-not-found.f90, gcc/gcc-acc-detach-delete-attach-underflow.f90, gcc/gcc-acc-c-detach-delete-attach-underflow.c |
| gcc | run_error | exit_status=1: no runtime message | softmax-online-omp | gcc_g90 | none | gcc/gcc-c-target-in-task-mandatory-device-not-found.c, gcc/gcc-target-in-task-mandatory-device-not-found.f90, gcc/gcc-acc-detach-delete-attach-underflow.f90, gcc/gcc-acc-c-detach-delete-attach-underflow.c |
| nvhpc | ice | nvhpc NVC++-W--Compiler failed to translate accelerator region (see -Minfo messages): Missing branch | langford-omp | nvhpc269 | oop/nvhpc-polymorphic-dispatch-translate-failure.f90, fuzz/nvhpc-target-simd-collapse-translate-failure.f90 | nvhpc-acc-atomic-update-sum-fort2-crash.f90, nvhpc-c-acc-atomic-update-sum-ice.c, nvhpc-parallel-if-in-target-nvvm-ice.f90, nvhpc-c-parallel-for-firstprivate-in-target.c |
<!-- results:end -->

## Ingest (recipe statuses of the dev half; the sealed half was run and is sealed)

| status | dev programs |
|---|---|
| ok (a recipe, built and run by the campaign) | 171 |
| needs-data-file | 18 |
| needs-external-library | 1 |
| cuda-only-dependency | 2 |
| no-recipe (`make -n` printed no compile command) | 1 |
| other-language | 0 |
| split | 193 |

The split rule and the dev ids are in `data/bench/hecbench/split.yaml` (the sealed half by SHA-256 of the directory
name), committed before the first run. Dev licence classes: bsd3 136, own-permissive 41, gpl-style 15,
restricted 1. After withholding the 16 (`gpl-style` and `restricted`), 177 dev programs remain and **162 of them
have an ok recipe**; the outcome tables below still count the 171 ok recipes (the runs were made before the
classifier was corrected), and the linter source and the notices use the 162.

## Sealed half

The sealed half was run, on the same recipe procedure, and sealed. Nothing about it is reported here: no
coverage, count or outcome. Its outcomes file is not tracked (maintainer's decision on the review): it stays on disk in
the shared tree, git-ignored, and `data/bench/hecbench-holdout/SEAL` keeps its `outcomes_sha256`. Older commits of this
branch (960ba007, 4dcf7347, 81848b13) still hold the blob; if the maintainer wants it gone from history the branch
must be rebuilt before any merge (a squash of those three commits is possible, since the branch is unmerged: an
offer, not done). A run of the sealed half logs no count (`Run.sealed`), and every report command refuses a run
that holds any program of it, whatever its name.

## What was measured, and what is missing (dev half)

Programs attempted (ok recipes: 171; counts of programs with a row, not outcomes):

| toolchain | dev programs |
|---|---|
| AFAR, CCE 19, CCE 20, CCE 21, CCE 21.0.4, and Tioga AFAR, CCE 19/20/21, GCC | 171 |
| NVHPC 25.11 | 138 |
| NVHPC 26.9 | 134 |
| GCC sm_80 | 96 |

GPU-hours, from the job ledgers (`results/hecbench/ledger.jsonl` on each machine; every job at four GPUs a node
for its whole wall time, discarded first attempts included): Tuolumne 14.1, Tioga 2.9, wingtip 3.2, 20.3 in
all over three passes. (The earlier prose figures, 10.6 + 3.6 + 2.5, were estimates and did not add up to the
ledgers.) The cost is compile time (a C++ offload compile is 10 to 150 s; wingtip allows four compiles at
once), not GPU time.

- **Gate**: Tioga complete; Tuolumne and wingtip dev cells gated in chunks of at most 30 minutes (a, b, d on one
  node or GPU, c on another). Cells still missing an environment are counted *incomplete* (in the table above:
  "only environments ... ran"). Tioga's gate of the sealed half was not run.
- **wingtip**: the third pass's coverage chunk was skipped (two GPUs busy with other users' jobs), so NVHPC and
  GCC sm_80 coverage is that of the second pass.
- **A bug found on the way**: both memory modes of an AMD program share one build directory, so concurrent (a)
  reruns of the two modes collided (`FileExistsError`); each mode now reruns in its own directory (`_m<mode>`
  suffix), and a leftover directory is removed only under a gate name.
- **30 s time-outs**: not rerun with 120 s, so whether the three time-out signatures are hangs or slow kernels
  is open. 108 of the 157 evidence cells are such time-outs; the count without them is in the Evidence section.
- **Oracle**: not extended. 71 of the 171 ok dev programs have a reference check (52 self-check, 19 lines); the
  rest are judged by exit status and failure text only, so wrong answers on those are not found.

## Reading the evidence

- The evidence cells fall in **16 distinct failure signatures** (the table above). Releases and arch twins are
  merged, and signatures of one family over the same programs are merged across outcome classes (a GPU fault is
  a crash on CCE 19 and 20 and a runtime error on CCE 21: one signature). A signature is (family, class,
  normalized message). **Nine had no finding in `data/findings/index.yaml` with a matching message** when the runs were made; seven did. The reductions below added two findings, so the table above counts seven.
  The match is the same outcome class, a toolchain of the same family, and the finding's message as a pattern or,
  for a literal captured from one run, after both sides lose addresses, handles, node ids and numbers. A message
  match does not prove the same defect; the reduction task decides. Findings of the same family and outcome class
  that do not match are listed as *related*.
- Three signatures are time-outs at the 30 s limit; see above.
- Programs that fail on every compiler of the three AMD families are no evidence (a program's own bug, a missing
  data file found at run time, a mandatory-device program): most of the *no witness* cells. 27 of the 171 ok
  dev programs have no passing cell on any toolchain.
- 154 failing cells are `nondeterministic` at the gate (in the first pass most were wrong answers whose output
  differs between runs, and time-outs near the limit).
- No dev program fails to compile or link on AFAR or on any CCE. NVHPC has 10 compile rejections and 12 ICEs in
  the outcome table, GCC 6 ICEs and 2 link failures; one NVHPC 26.9 ICE reached the evidence list.
- The oracle is weak (above).

## Reductions (the nine signatures without a matching finding)

Each of the nine was taken to reduction on its failing toolchain with `tools/reduce.py` (the rules witness on every
step, the identical signature, the output oracle for a wrong answer). The reducer reads one C or Fortran file, so each
benchmark was first rewritten by hand as a plain C file with the same kernels (timing code and C++ containers removed,
sizes fixed, a device flag and a self-check added); its first run on the failing toolchain had to fail with the
recorded class. Every GCC signature fails on the MI250X build (Tioga), where the reductions ran, one foreground pdebug
job at a time. The budget was 3 jobs per reduction; the popcount reduction needed a fourth (the first
three stopped on the rewritten input and on the two tool limits below) and the runtime-abort reduction used its
three without settling. The reducer's output was then finished by hand where it had dropped a
mapping or the device flag, and every finished reproducer was run again: on the failing toolchains, with one-change
controls, in the gate's four environments (a, b, d on one node or GPU, c on another) and on every other family's
toolchain (Tuolumne AFAR and CCE 19, 20, 21, 21.0.4 in both memory modes; Tioga's AFAR and CCE builds; wingtip NVHPC
25.11 and 26.9 and GCC sm_80). The front-end witness (AFAR) accepted both reproducers and their controls. Rows:
`results/hecbench/red/`. A reproducer is a small program written for the finding; no benchmark source is tracked, and a
program of a withheld licence class was neither used nor reduced.

Two changes to the shared tools came out of it: the harness classifies an assembler error in GCC's own generated
offload assembly as the compiler's failure (`ice`), and the reducer no longer asks for an output oracle when a
candidate turns a compile failure into a wrong answer.

| signature | programs used | verdict | what the reduction showed |
|---|---|---|---|
| gcc ice `tree-ssanames.cc:355` | f16sp-omp | **finding** `hecbench/gcc-c-float16-array-in-target-lto-ice.c` | a target region that converts a mapped `_Float16` array to float stops lto1 (MI250X and A100). float elements compile. Other `_Float16` forms in a target region end in other lto1 internal errors (`mentions_vars_p`, a segmentation fault) on MI250X |
| gcc link `too few operands for instruction` | popcount-omp | **finding** `hecbench/gcc-c-swar-popcount-assembler-error.c` | the parallel-sum popcount loop makes GCC emit `v_bcnt_u32_b32 v4, v4` for gfx90a, which its assembler refuses; shifts and adds, `__builtin_popcountll` and A100 compile. The campaign recorded it as a link failure; the harness now calls it an `ice` |
| gcc link `other symbol X` | assert-omp | not a compiler issue, not published | reduced to `assert(...)` in a target region: the macro calls the host C library's `__assert_fail`, which has no device version in GCC's offload libraries. The specification asks for a device version of a function called in a target region (declare target) and says nothing about host library functions, so the link error is a missing library, not a violation |
| gcc run_error `internal libgomp cbuf error` | flip-omp | not a compiler issue, not published | reduced to one `target` with `map(to: d_strides[0:3], d_strides_contiguous[0:3])` where both pointers hold the same array. 5.2 §5.8.3 forbids two list items of one construct that share original storage (`catalog/omp/rules.yaml`); the rules witness cannot see the aliasing through pointers. With one pointer for both uses the program passes on GCC (gcc_g90) |
| gcc run_error `no runtime message` | softmax-online-omp | not a compiler issue, not published | the kernel indexes shared memory and strides by `block_size` and so assumes `block_size` threads in a team. GCC's amdgcn offload gives `num_threads(256)` 16 threads (measured), which the specification allows (the clause is an upper bound), and the program then computes a wrong softmax. A reduction against a host reference could not run: the host run of another family (CCE) fails the program's own self-check, since the kernel needs `block_size` threads |
| gcc crash `GCN Kernel Aborted` | the signature's programs of an allowed licence class | unreduced observation | one program (p4-omp) reproduces in a plain C rewrite at its original size, with the team-master/barrier messages of the libgomp GCN runtime, but the harness classed the candidates' runs both as SIGABRT and as wrong answers (`check=fail`), so the identical-signature rule is not met; the reduction stopped at its budget with the signature unsettled. The other program is five C++ sources (`crs-sycl` library files included) and the reducer takes one file |
| gcc timeout, cce timeout, afar timeout | 28, 20 and 5 programs | unreduced observations | a 30 s limit does not separate a hang from a slow kernel (the 120 s and 600 s reruns below show slow kernels, not hangs), so there is nothing to reduce to; a timeout reduction would reduce to "slow at 30 s" |

Result: 2 findings, 3 signatures judged not to be compiler issues (the reductions are the evidence), 4 unreduced
observations (3 time-outs, 1 runtime abort). The two findings are on the site; the other seven are not.

## The 30 s time-outs rerun at 120 s (dev half)

`tools/campaigns/hecbench.py t120` reruns the dev cells that timed out in a run (not in a compile) with a 120 s limit, on
the same toolchain and memory mode, into a run of its own (`t120`, beside the 30 s rows, which are not touched).
Withheld programs (15 `gpl-style`, 1 `restricted`) and the sealed half are left out. Up to four programs run on
one GPU at a time (two on wingtip, one per GPU), in a fixed shuffled order, so a job cut short covers every
signature. Cells per machine: 203 on Tuolumne, 156 on Tioga, 89 on wingtip.

| signature | timed-out cells | finished ok (slow kernel) | finished failing | still timing out | not rerun |
|---|---|---|---|---|---|
| CCE, Tuolumne (19, 20, 21, 21.0.4; both modes) | 176 | 84 | 21 (20 wrong answer, 1 crash) | 71 | 0 |
| AFAR, Tuolumne (both modes) | 27 | 13 | 1 (wrong answer) | 13 | 0 |
| CCE, Tioga (gfx90a twins) | 85 | 40 | 14 (12 wrong answer, 2 crash) | 31 | 0 |
| AFAR, Tioga | 19 | 11 | 2 (1 wrong answer, 1 crash) | 6 | 0 |
| GCC gfx90a (Tioga) | 52 | 18 | 3 (wrong answer) | 31 | 0 |
| GCC sm_80 (wingtip) | 31 | 12 | 4 (3 wrong answer, 1 run error) | 13 | 2 |
| NVHPC (wingtip) | 58 | 32 | 5 (wrong answer) | 16 | 5 |

All of Tuolumne and Tioga was rerun; wingtip, in three chunks of two GPUs, all but 7 cells (the budget was spent). Of
the 359 cells rerun on the AMD machines, 46 % finish within 120 s (slow kernels, or contention at 30 s, not
hangs); the others still time out there.

### Are they hangs?

The programs that still time out at 120 s on both AFAR and CCE on Tuolumne (f16sp, ldpc, metropolis, scan, sosfil,
storeKVCache, threadcpy; also convolution1D and dwconv) are not hangs. The six without a finding (ldpc,
metropolis, scan, sosfil, storeKVCache, threadcpy) were run once with a 600 s limit on AFAR (copy mode) and once on
CCE 21 (copy mode), six at a time in one pdebug job each (runs `t600`, `t600c`). **All twelve runs end**, in 38 to
228 s on AFAR and 35 to 307 s on CCE 21 (task time, compile included): the sweeps are long by design
(`storeKVCache` runs 150 configurations, `threadcpy` 15 configurations of 100 warm-up launches over 1 GB), and a
node running six of them while compiling is slow. At 120 s on a loaded node they are slow kernels, not hangs, so
**there is nothing to reduce** and no hang finding. Three of the twelve end in a failure of their own: `ldpc` and
`metropolis` fail the oracle on both families (their host reference does not agree with the device output: an
oracle matter, as for the cells with a weak reference), and `scan` on CCE 21 prints `FAIL` at 125 s where AFAR
passes. The last is the only candidate; it was not gated (a gate rerun at 125 s is four more such runs) and not
reduced.

### Gate of the cells that now fail differently

The cells that finished failing at 120 s and for which a compiler of another family ran the program correctly in
the same mode (`t120-gate-list`: 22 of the 47) were gated with the campaign interface (`tools/campaign.py hecbench
gate --name t120 --timeout 120`; a, b, d on one node or GPU, c on another; dev half only). Result: 1 confirmed,
20 nondeterministic, 1 not reproduced. The confirmed one is `softmax-online-omp` on GCC sm_80 (a run error with no
message), the program whose reduction above shows it assumes `block_size` threads in a team and is not a compiler
issue. The 20 nondeterministic are wrong answers (`FAIL` printed) on CCE (addBiasResidualLayerNorm, boxfilter,
burger, convolution1D, degrid, triad) and GCC (medianfilter, wedford, histogram) that differ from run to run; the
one not reproduced is `burger-omp` on NVHPC 26.9. **No new finding.**

### `scan` on CCE 21

`scan-omp` ends in `FAIL` on CCE 21 at 125 s where AFAR passes. Its kernel is `target teams num_teams(num_blocks)
thread_limit(N/2)` with a plain `parallel` inside (no `num_threads`), and an algorithm that indexes by
`omp_get_thread_num()` and synchronises with `omp barrier`, so it is correct only if the parallel region gets
exactly N/2 threads. `thread_limit` is an upper bound, and the number of threads of a `parallel` region without
`num_threads` is the implementation's choice (5.2 §4.4.1 and §9.2), as for `softmax-online`. Decided from the
source, not by a measurement of the thread count: **not a compiler issue** (a program that assumes an unspecified
thread count), and no gate-confirmed signature exists, so there was no reduction.

## Not done

Reduction of any failure beyond the above; the 7 wingtip cells not rerun at 120 s; the Tioga gate of the sealed
half; the rest of the NVIDIA cells (see the coverage table); an extended oracle; retraining (none).

## Linter source

`tools/lint/lint_train.py build --sources hecbench-dev` adds the dev half as the separate source `hecbench-dev`
(`hecbench_tasks`: programs that built, not `gpl-style` or `restricted`, with cells labelled by the usual
`cell_label` with the gate's verdict; the sealed half is dropped by construction). It is in `TD.SOURCE_KINDS` but
not in `TD.REAL`, so no existing study group changes; a default `build` does not include it. Nothing was
retrained. The table of this write-up's run was built before the classifier correction (it held the restricted
program) and is not installed or committed; rebuild before use.
