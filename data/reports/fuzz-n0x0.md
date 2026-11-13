# Fuzz campaign `n0x0`

Csmith-style random OpenMP 5.2 Fortran offload programs (offload.engine.fuzz, generator `fuzz-4s50`), run on every toolchain at -O2, HSA_XNACK=0 (AMD) and separate memory (NVHPC), OMP_TARGET_OFFLOAD=mandatory; reference: the Python model of each program, checked against a host run (OMP_TARGET_OFFLOAD=disabled, a reference only; see the appendix 'Host reference checks' for the programs whose host run failed or disagreed). Machine-readable: results/fuzz/n0x0/summary.json.

## Size and timing

- programs generated: 1000; legal and run: 1000 (judged: 1000; noncompliant, excluded from every count below: 0); generator rejects: 0; worker crashes: 0
- sessions (4, some concurrent; the times are not a wall time): n0x0-00: 1305 s with 12 workers, n0x0-01: 812 s with 12 workers, n0x0-nvhpc: 3163 s with 1 worker, n0x0-nvhpc269: 2850 s with 1 worker; 19.9 s per program and worker, all toolchains and repeats included
- programs whose device results agree with the model on every toolchain: 124

## Notes

- The NVHPC runs of n0x0 (21:51-22:44 on 2026-10-24) shared wingtip GPUs 0 and 1 with two stray executables of n1x0 seed 72 (see the n1x0 report); a second look found no effect on the classes.

## Classes per toolchain

Rejections (compile_reject) are features a toolchain does not support, not failures. Flaky = the repeats differed (counted in the worst class).

| class | afar | cce19 | cce20 | cce21 | nvhpc | nvhpc269 |
|---|---|---|---|---|---|---|
| agree | 736 | 485 | 626 | 543 | 161 | 167 |
| compile_reject | 240 | 302 | 69 | 138 | 785 | 785 |
| ice | 0 | 170 | 251 | 251 | 3 | 3 |
| wrong_code | 22 | 42 (12 flaky) | 54 (5 flaky) | 65 (2 flaky) | 21 | 14 |
| host_fallback | 0 | 0 | 0 | 0 | 0 | 0 |
| timeout | 0 | 1 | 0 | 0 | 15 | 16 (1 flaky) |
| run_error | 2 | 0 | 0 | 3 | 15 | 15 |
| harness_error | 0 | 0 | 0 | 0 | 0 | 0 |

## Known findings rediscovered

- cce19-target-parallel-guarded-loop (wrong code on cce19 in a program with a thread-0-guarded sequential loop in target parallel): 35 programs (seeds 13, 16, 20, 25, 34, 42, 60, 131, 163, 234, 241, 249)
- cce21-defaultmap-aggregate-flag (wrong code or host fallback on cce21 where cce20 agrees, in a program with a defaultmap clause; the finding's symptom: a map(tofrom) scalar is not copied back): 17 programs (seeds 28, 67, 102, 157, 233, 361, 388, 430, 518, 551, 601, 603)
- (control for the line above: the same without a defaultmap clause): 0 programs (seeds )
- cce21-in-reduction-taskwait-link (cce21 link failure on _cray$mt_taskwait): 69 programs (seeds 25, 33, 34, 42, 52, 72, 88, 142, 184, 197, 198, 202)
- cce19-target-parallel-single-ice / task ICE (CCE 'unhandled construct type'): 195 programs (seeds 1, 2, 11, 32, 38, 40, 51, 54, 56, 59, 62, 64)

## Distinct minimized failures

(none minimized yet)

## Wrong code (all programs)

- afar: 22 programs (seeds 11, 87, 121, 171, 193, 261, 268, 294, 314, 372, 401, 562, 594, 599, 620, 650, 700, 721, 831, 894)
- cce19: 42 programs (seeds 13, 14, 16, 20, 25, 34, 42, 60, 98, 131, 163, 209, 234, 241, 249, 275, 349, 357, 372, 393)
- cce20: 54 programs (seeds 13, 14, 16, 18, 20, 21, 22, 25, 34, 42, 60, 70, 106, 131, 163, 209, 234, 241, 249, 264)
- cce21: 65 programs (seeds 13, 14, 16, 18, 20, 21, 22, 28, 60, 67, 70, 102, 106, 131, 157, 163, 209, 233, 234, 241)
- nvhpc: 21 programs (seeds 47, 98, 103, 132, 136, 138, 205, 384, 416, 461, 468, 480, 557, 580, 585, 649, 765, 785, 794, 881)
- nvhpc269: 14 programs (seeds 98, 132, 136, 138, 205, 416, 461, 557, 585, 649, 785, 794, 881, 999)

## Internal compiler errors (deduplicated by message)

| toolchain | programs | message | seeds |
|---|---|---|---|
| cce19 | 129 | ice: INTERNAL COMPILER ERROR: "unhandled construct type" (v_openmp.c, line 7617, version <v>) | 1, 2, 11, 32, 51 |
| cce20 | 119 | ice: INTERNAL COMPILER ERROR: "unhandled acc construct type" (v_openmp.c, line 7881, version <v>) | 2, 38, 40, 54, 59 |
| cce21 | 119 | ice: INTERNAL COMPILER ERROR: "unhandled acc construct type" (v_openmp.c, line 8265, version <v>) | 2, 38, 40, 54, 59 |
| cce20 | 75 | ice: INTERNAL COMPILER ERROR: "unhandled construct type" (v_openmp.c, line 7814, version <v>) | 1, 11, 32, 51, 56 |
| cce21 | 75 | ice: INTERNAL COMPILER ERROR: "unhandled construct type" (v_openmp.c, line 8197, version <v>) | 1, 11, 32, 51, 56 |
| cce20 | 49 | ice: INTERNAL COMPILER ERROR: "ACC - barrier/reset/protected last private not supported" (v_mt_translate.c, line 5607, version <v>) | 31, 78, 100, 115, 134 |
| cce21 | 49 | ice: INTERNAL COMPILER ERROR: "ACC - barrier/reset/protected last private not supported" (v_mt_translate.c, line 5798, version <v>) | 31, 78, 100, 115, 134 |
| cce19 | 33 | ice: INTERNAL COMPILER ERROR: "ACC - barrier/reset/protected last private not supported" (v_mt_translate.c, line 4874, version <v>) | 31, 78, 100, 134, 136 |
| cce19 | 3 | ice: INTERNAL COMPILER ERROR: "Couldn't find an atomic update statement" (v_mt_translate_atomic.c, line 1703, version <v>) | 259, 477, 966 |
| cce20 | 3 | ice: INTERNAL COMPILER ERROR: "Couldn't find an atomic update statement" (v_mt_translate_atomic.c, line 1703, version <v>) | 259, 477, 966 |
| cce21 | 3 | ice: INTERNAL COMPILER ERROR: "Couldn't find an atomic update statement" (v_mt_translate_atomic.c, line 1702, version <v>) | 259, 477, 966 |
| cce19 | 2 | ice: INTERNAL COMPILER ERROR: "Mismatched last induction expression for last private operators" (v_mt_translate.c, line 871, version <v>) | 166, 958 |
| cce19 | 2 | ice: INTERNAL COMPILER ERROR: "Unhandled contexts must be fixed!!! | 385, 591 |
| cce20 | 2 | ice: INTERNAL COMPILER ERROR: "Mismatched last induction expression for last private operators" (v_mt_translate.c, line 901, version <v>) | 166, 958 |
| cce20 | 2 | ice: INTERNAL COMPILER ERROR: "Unhandled contexts must be fixed!!! | 385, 591 |
| cce21 | 2 | ice: INTERNAL COMPILER ERROR: "Mismatched last induction expression for last private operators" (v_mt_translate.c, line 911, version <v>) | 166, 958 |
| cce21 | 2 | ice: INTERNAL COMPILER ERROR: "Unhandled contexts must be fixed!!! | 385, 591 |
| cce19 | 1 | ice: INTERNAL COMPILER ERROR: "unhandled operator | 165 |
| cce20 | 1 | ice: INTERNAL COMPILER ERROR: "unhandled operator | 165 |
| cce21 | 1 | ice: INTERNAL COMPILER ERROR: "unhandled operator | 165 |
| nvhpc | 1 | ice: NVFORTRAN-W-0155-Compiler failed to translate accelerator region (see -Minfo messages): Missing branch target block (44) | 847 |
| nvhpc | 1 | ice: NVFORTRAN-W-0155-Compiler failed to translate accelerator region (see -Minfo messages): Missing branch target block (51) | 722 |
| nvhpc | 1 | ice: NVFORTRAN-W-0155-Compiler failed to translate accelerator region (see -Minfo messages): Missing branch target block (64) | 163 |
| nvhpc269 | 1 | ice: NVFORTRAN-W-0155-Compiler failed to translate accelerator region (see -Minfo messages): Missing branch target block (44) | 847 |
| nvhpc269 | 1 | ice: NVFORTRAN-W-0155-Compiler failed to translate accelerator region (see -Minfo messages): Missing branch target block (51) | 722 |
| nvhpc269 | 1 | ice: NVFORTRAN-W-0155-Compiler failed to translate accelerator region (see -Minfo messages): Missing branch target block (64) | 163 |

## Run errors, timeouts, host fallbacks

| toolchain | class | programs | reason | seeds |
|---|---|---|---|---|
| nvhpc269 | timeout | 16 | timeout | 97, 101, 179, 285, 372 |
| nvhpc | timeout | 15 | timeout | 97, 101, 179, 285, 386 |
| nvhpc | run_error | 14 | exit_status: 1; without mandatory: exit_status: 1 | 28, 78, 234, 287, 316 |
| nvhpc269 | run_error | 14 | exit_status: 1; without mandatory: exit_status: 1 | 28, 78, 234, 287, 316 |
| cce21 | run_error | 3 | exit_status: 1; without mandatory: exit_status: 1 | 353, 378, 501 |
| afar | run_error | 2 | crash: SIGABRT; without mandatory: crash: SIGABRT | 226, 414 |
| nvhpc | run_error | 1 | crash: SIGABRT; without mandatory: crash: SIGABRT | 107 |
| nvhpc269 | run_error | 1 | crash: SIGABRT; without mandatory: crash: SIGABRT | 107 |
| cce19 | timeout | 1 | compile_timeout | 427 |

## Features and feature pairs most associated with failures

Among programs the toolchain compiled (or crashed on). Lift = the rate of the class among programs with the feature (pair) over the toolchain's overall rate; a pair is listed only when it beats both of its features alone by 25%.

### afar: wrong_code

Single features: clause:schedule:auto (4/26, lift 5.31); split:target | teams | distribute | parallel | do simd (9/67, lift 4.64); clause:default:none (14/110, lift 4.4); dir:do simd (10/92, lift 3.75); clause:schedule:guided (3/28, lift 3.7); chain:target teams distribute parallel do simd (10/112, lift 3.08); clause:schedule (10/118, lift 2.93); split:target | teams | distribute | parallel | do (5/60, lift 2.88)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| clause:default:none + clause:schedule | 29 | 8 | 0.276 | 0.127 | 9.53 |
| clause:schedule:auto + dir:do | 15 | 4 | 0.267 | 0.154 | 9.21 |
| chain:target teams distribute parallel do + clause:default:none | 21 | 5 | 0.238 | 0.127 | 8.23 |
| clause:default:none + split:target \| teams \| distribute \| parallel \| do simd | 34 | 8 | 0.235 | 0.134 | 8.13 |
| clause:default:none + dir:do simd | 39 | 9 | 0.231 | 0.127 | 7.97 |
| clause:schedule + dir:target parallel | 22 | 5 | 0.227 | 0.085 | 7.85 |
| clause:default:none + wrap:host_update_to | 18 | 4 | 0.222 | 0.127 | 7.68 |
| dir:distribute + split:target \| parallel \| loop | 18 | 4 | 0.222 | 0.06 | 7.68 |

### cce19: wrong_code

Single features: guard:split_par_thread0 (12/21, lift 9.5); guard:par_thread0 (25/44, lift 9.44); guard:target_seq (7/23, lift 5.06); kernel:guard (36/157, lift 3.81); dir:parallel do simd (4/18, lift 3.69); guard:teams_team0 (6/28, lift 3.56); dir:distribute parallel do (3/17, lift 2.93); defaultmap:default:all (6/35, lift 2.85)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| dir:target + guard:par_thread0 | 28 | 21 | 0.75 | 0.568 | 12.46 |
| dir:distribute + guard:par_thread0 | 16 | 12 | 0.75 | 0.568 | 12.46 |
| guard:par_thread0 + scalar:implicit | 22 | 16 | 0.727 | 0.568 | 12.09 |
| decl:allocatable_rank2 + guard:target_seq | 16 | 7 | 0.438 | 0.304 | 7.27 |
| kernel:guard + tasking:nowait_depend | 27 | 11 | 0.407 | 0.229 | 6.77 |
| chain:target teams distribute parallel do simd + kernel:guard | 15 | 6 | 0.4 | 0.229 | 6.65 |
| clause:in_reduction + kernel:guard | 15 | 6 | 0.4 | 0.229 | 6.65 |
| dir:taskgroup + kernel:guard | 15 | 6 | 0.4 | 0.229 | 6.65 |

### cce19: ice

Single features: phase:nowait_barrier (49/49, lift 4.11); guard:masked (23/23, lift 4.11); phase:loop (21/21, lift 4.11); guard:single (16/16, lift 4.11); kernel:phase (86/87, lift 4.06); phase:do (73/74, lift 4.05); phase:do simd (50/51, lift 4.03); phase:masked (48/49, lift 4.02)

| feature pair | programs | ice | rate | best single rate | lift |
|---|---|---|---|---|---|
| dir:target parallel + wrap:host_update_to | 25 | 20 | 0.8 | 0.627 | 3.28 |
| clause:lastprivate + split:target \| parallel \| do | 25 | 19 | 0.76 | 0.416 | 3.12 |
| clause:lastprivate + split:target \| teams \| distribute \| parallel \| do simd | 20 | 14 | 0.7 | 0.416 | 2.87 |
| clause:firstprivate + clause:lastprivate | 19 | 13 | 0.684 | 0.416 | 2.81 |
| clause:lastprivate + clause:proc_bind | 22 | 15 | 0.682 | 0.416 | 2.8 |
| clause:lastprivate + dir:parallel | 83 | 52 | 0.627 | 0.416 | 2.57 |
| clause:lastprivate + dir:do | 67 | 42 | 0.627 | 0.416 | 2.57 |
| clause:lastprivate + split:target \| parallel \| do \| simd | 24 | 15 | 0.625 | 0.416 | 2.57 |

### cce20: wrong_code

Single features: guard:par_thread0 (34/62, lift 9.45); guard:split_par_thread0 (15/31, lift 8.34); guard:target_seq (9/31, lift 5.01); kernel:guard (47/216, lift 3.75); guard:teams_team0 (6/31, lift 3.34); defaultmap:default:all (9/47, lift 3.3); dir:parallel do simd (4/23, lift 3.0); split:target | parallel do (3/18, lift 2.87)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| dir:teams + guard:par_thread0 | 20 | 15 | 0.75 | 0.548 | 12.93 |
| guard:par_thread0 + scalar:implicit | 32 | 23 | 0.719 | 0.548 | 12.39 |
| dir:distribute + guard:par_thread0 | 21 | 15 | 0.714 | 0.548 | 12.31 |
| guard:target_seq + map:from | 18 | 8 | 0.444 | 0.29 | 7.66 |
| kernel:guard + split:target \| parallel \| do \| simd | 15 | 6 | 0.4 | 0.218 | 6.9 |
| kernel:guard + map:mod:present | 22 | 8 | 0.364 | 0.218 | 6.27 |
| kernel:guard + scalar:implied_tofrom | 22 | 8 | 0.364 | 0.218 | 6.27 |
| chain:target parallel do simd + kernel:guard | 25 | 9 | 0.36 | 0.218 | 6.21 |

### cce20: ice

Single features: kernel:phase (126/126, lift 3.71); phase:do (107/107, lift 3.71); phase:do simd (74/74, lift 3.71); phase:masked (70/70, lift 3.71); phase:single (70/70, lift 3.71); phase:nowait_barrier (65/65, lift 3.71); map:alloc (51/51, lift 3.71); guard:masked (34/34, lift 3.71)

| feature pair | programs | ice | rate | best single rate | lift |
|---|---|---|---|---|---|
| dir:target parallel + split:target \| simd | 18 | 16 | 0.889 | 0.659 | 3.3 |
| clause:lastprivate:conditional + dir:do | 17 | 15 | 0.882 | 0.69 | 3.27 |
| dir:target parallel + split:target \| teams \| loop | 18 | 15 | 0.833 | 0.659 | 3.09 |
| clause:lastprivate + split:target \| parallel \| do | 38 | 28 | 0.737 | 0.443 | 2.73 |
| clause:lastprivate + split:target \| teams \| loop | 18 | 12 | 0.667 | 0.443 | 2.47 |
| clause:lastprivate + clause:proc_bind | 34 | 22 | 0.647 | 0.443 | 2.4 |
| chain:target parallel do + red:clause:ior | 17 | 11 | 0.647 | 0.333 | 2.4 |
| clause:thread_limit + defaultmap:default:aggregate | 17 | 11 | 0.647 | 0.46 | 2.4 |

### cce21: wrong_code

Single features: guard:par_thread0 (31/54, lift 7.61); guard:split_par_thread0 (17/30, lift 7.51); guard:teams_team0 (10/30, lift 4.42); guard:target_seq (9/28, lift 4.26); defaultmap:firstprivate:scalar (4/15, lift 3.54); kernel:guard (51/204, lift 3.32); defaultmap:default:all (10/44, lift 3.01); red:atomic (12/61, lift 2.61)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| guard:par_thread0 + scalar:implicit | 26 | 20 | 0.769 | 0.574 | 10.2 |
| dir:distribute + guard:par_thread0 | 17 | 13 | 0.765 | 0.574 | 10.14 |
| body:inner_seq_loop + guard:teams_team0 | 16 | 7 | 0.438 | 0.333 | 5.8 |
| body:inner_seq_loop + dir:target simd | 15 | 6 | 0.4 | 0.15 | 5.3 |
| body:inner_seq_loop + split:target simd | 15 | 6 | 0.4 | 0.15 | 5.3 |
| defaultmap:tofrom:all + dir:target parallel | 15 | 6 | 0.4 | 0.163 | 5.3 |
| kernel:guard + split:target \| parallel \| do \| simd | 15 | 6 | 0.4 | 0.25 | 5.3 |
| chain:target teams distribute parallel do + kernel:guard | 21 | 8 | 0.381 | 0.25 | 5.05 |

### cce21: ice

Single features: kernel:phase (126/126, lift 3.43); phase:do (107/107, lift 3.43); phase:do simd (74/74, lift 3.43); phase:masked (70/70, lift 3.43); phase:single (70/70, lift 3.43); phase:nowait_barrier (65/65, lift 3.43); map:alloc (51/51, lift 3.43); guard:masked (34/34, lift 3.43)

| feature pair | programs | ice | rate | best single rate | lift |
|---|---|---|---|---|---|
| dir:target parallel + split:target \| simd | 18 | 16 | 0.889 | 0.683 | 3.05 |
| clause:in_reduction + dir:target parallel | 22 | 19 | 0.864 | 0.683 | 2.97 |
| dir:target parallel + dir:taskgroup | 22 | 19 | 0.864 | 0.683 | 2.97 |
| dir:target parallel + kernel:inred | 22 | 19 | 0.864 | 0.683 | 2.97 |
| clause:lastprivate + split:target \| parallel \| do | 37 | 28 | 0.757 | 0.463 | 2.6 |
| clause:in_reduction + loop:down | 15 | 11 | 0.733 | 0.543 | 2.52 |
| dir:taskgroup + loop:down | 15 | 11 | 0.733 | 0.543 | 2.52 |
| kernel:inred + loop:down | 15 | 11 | 0.733 | 0.543 | 2.52 |

### cce21: run_error

Single features: split:target | teams | distribute | parallel | do simd (3/92, lift 9.37); dir:do simd (3/119, lift 7.24); chain:target teams distribute parallel do simd (3/140, lift 6.16); clause:num_threads (3/240, lift 3.59); dir:distribute (3/314, lift 2.75); dir:teams (3/370, lift 2.33); dir:parallel (3/378, lift 2.28); decl:explicit_rank2 (3/497, lift 1.73)

| feature pair | programs | run_error | rate | best single rate | lift |
|---|---|---|---|---|---|
| clause:num_threads + split:target \| teams \| distribute \| parallel \| do simd | 37 | 3 | 0.081 | 0.033 | 23.3 |
| clause:num_threads + dir:do simd | 52 | 3 | 0.058 | 0.025 | 16.58 |
| chain:target teams distribute parallel do simd + clause:num_threads | 58 | 3 | 0.052 | 0.021 | 14.86 |
| decl:explicit_rank2 + split:target \| teams \| distribute \| parallel \| do simd | 65 | 3 | 0.046 | 0.033 | 13.26 |
| decl:explicit_rank1 + split:target \| teams \| distribute \| parallel \| do simd | 69 | 3 | 0.043 | 0.033 | 12.49 |
| map:to + split:target \| teams \| distribute \| parallel \| do simd | 73 | 3 | 0.041 | 0.033 | 11.81 |
| decl:explicit_rank2 + dir:do simd | 82 | 3 | 0.037 | 0.025 | 10.51 |
| clause:num_threads + dir:distribute | 94 | 3 | 0.032 | 0.013 | 9.17 |

### nvhpc: wrong_code

Single features: clause:lastprivate (10/31, lift 3.3); chain:target teams distribute parallel do (8/25, lift 3.28); split:target | teams | distribute | parallel | do (5/17, lift 3.01); chain:target teams distribute parallel do simd (5/21, lift 2.44); clause:num_threads (10/43, lift 2.38); dir:do simd (4/18, lift 2.28); clause:default:shared (4/20, lift 2.05); chain:target simd (4/22, lift 1.86)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| clause:num_threads + dir:parallel | 15 | 7 | 0.467 | 0.233 | 4.78 |
| clause:num_threads + dir:target | 23 | 10 | 0.435 | 0.233 | 4.45 |
| clause:num_threads + kernel:loop | 34 | 10 | 0.294 | 0.233 | 3.01 |
| dir:parallel + loop:step2 | 15 | 4 | 0.267 | 0.179 | 2.73 |
| body:call_declare_target + dir:teams | 19 | 5 | 0.263 | 0.143 | 2.69 |
| dir:parallel + dir:teams | 35 | 9 | 0.257 | 0.179 | 2.63 |
| dir:distribute + dir:parallel | 36 | 9 | 0.25 | 0.179 | 2.56 |
| dir:target + map:mod:always | 36 | 9 | 0.25 | 0.173 | 2.56 |

### nvhpc: ice

Single features: chain:target simd (3/22, lift 9.77); clause:collapse (3/30, lift 7.17); loop:down (3/79, lift 2.72); decl:allocatable_rank2 (3/156, lift 1.38); map:tofrom (3/164, lift 1.31); decl:explicit_rank1 (3/166, lift 1.3); map:implicit (3/169, lift 1.27); kernel:loop (3/178, lift 1.21)

| feature pair | programs | ice | rate | best single rate | lift |
|---|---|---|---|---|---|
| clause:collapse + loop:down | 16 | 3 | 0.188 | 0.1 | 13.44 |
| clause:collapse + decl:explicit_rank1 | 22 | 3 | 0.136 | 0.1 | 9.77 |
| clause:collapse + map:tofrom | 24 | 3 | 0.125 | 0.1 | 8.96 |
| decl:allocatable_rank2 + loop:down | 61 | 3 | 0.049 | 0.038 | 3.52 |
| decl:explicit_rank1 + loop:down | 61 | 3 | 0.049 | 0.038 | 3.52 |
| decl:allocatable_rank2 + decl:explicit_rank1 | 120 | 3 | 0.025 | 0.019 | 1.79 |
| decl:allocatable_rank2 + map:tofrom | 124 | 3 | 0.024 | 0.019 | 1.73 |
| map:implicit + map:tofrom | 128 | 3 | 0.023 | 0.018 | 1.68 |

### nvhpc: run_error

Single features: tasking:nowait_depend (12/19, lift 9.05); red:clause:ieor (4/16, lift 3.58); split:target | teams | distribute | parallel | do (3/17, lift 2.53); dir:do (6/36, lift 2.39); clause:collapse (5/30, lift 2.39); chain:target teams distribute (5/33, lift 2.17); chain:target parallel do simd (3/20, lift 2.15); clause:default:shared (3/20, lift 2.15)

| feature pair | programs | run_error | rate | best single rate | lift |
|---|---|---|---|---|---|
| loop:down + map:from | 20 | 6 | 0.3 | 0.121 | 4.3 |
| dir:parallel + dir:simd | 15 | 4 | 0.267 | 0.125 | 3.82 |
| body:call_declare_target + dir:distribute | 19 | 5 | 0.263 | 0.133 | 3.77 |
| clause:collapse + map:to | 21 | 5 | 0.238 | 0.167 | 3.41 |
| declare_target_function + dir:do | 21 | 5 | 0.238 | 0.167 | 3.41 |
| dir:distribute + dir:do | 21 | 5 | 0.238 | 0.167 | 3.41 |
| dir:do + dir:teams | 21 | 5 | 0.238 | 0.167 | 3.41 |
| clause:lastprivate + loop:down | 17 | 4 | 0.235 | 0.129 | 3.37 |

### nvhpc269: wrong_code

Single features: clause:lastprivate (7/31, lift 3.47); chain:target simd (4/22, lift 2.79); clause:safelen (3/20, lift 2.3); chain:target teams distribute parallel do simd (3/21, lift 2.19); scalar:implied_tofrom (3/21, lift 2.19); map:mod:always (7/52, lift 2.07); chain:target teams distribute parallel do (3/25, lift 1.84); wrap:target_data (4/36, lift 1.71)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| clause:lastprivate + decl:explicit_rank1 | 24 | 7 | 0.292 | 0.226 | 4.48 |
| body:call_declare_target + dir:teams | 19 | 4 | 0.211 | 0.102 | 3.23 |
| dir:teams + map:mod:always | 20 | 4 | 0.2 | 0.135 | 3.07 |
| chain:target teams distribute parallel do + map:to | 15 | 3 | 0.2 | 0.12 | 3.07 |
| clause:num_threads + map:from | 15 | 3 | 0.2 | 0.076 | 3.07 |
| dir:target + map:mod:always | 36 | 7 | 0.194 | 0.135 | 2.99 |
| chain:target teams distribute parallel do simd + decl:explicit_rank1 | 16 | 3 | 0.188 | 0.143 | 2.88 |
| clause:num_threads + loop:down | 16 | 3 | 0.188 | 0.076 | 2.88 |

### nvhpc269: ice

Single features: chain:target simd (3/22, lift 9.77); clause:collapse (3/30, lift 7.17); loop:down (3/79, lift 2.72); decl:allocatable_rank2 (3/156, lift 1.38); map:tofrom (3/164, lift 1.31); decl:explicit_rank1 (3/166, lift 1.3); map:implicit (3/169, lift 1.27); kernel:loop (3/178, lift 1.21)

| feature pair | programs | ice | rate | best single rate | lift |
|---|---|---|---|---|---|
| clause:collapse + loop:down | 16 | 3 | 0.188 | 0.1 | 13.44 |
| clause:collapse + decl:explicit_rank1 | 22 | 3 | 0.136 | 0.1 | 9.77 |
| clause:collapse + map:tofrom | 24 | 3 | 0.125 | 0.1 | 8.96 |
| decl:allocatable_rank2 + loop:down | 61 | 3 | 0.049 | 0.038 | 3.52 |
| decl:explicit_rank1 + loop:down | 61 | 3 | 0.049 | 0.038 | 3.52 |
| decl:allocatable_rank2 + decl:explicit_rank1 | 120 | 3 | 0.025 | 0.019 | 1.79 |
| decl:allocatable_rank2 + map:tofrom | 124 | 3 | 0.024 | 0.019 | 1.73 |
| map:implicit + map:tofrom | 128 | 3 | 0.023 | 0.018 | 1.68 |

### nvhpc269: run_error

Single features: tasking:nowait_depend (12/19, lift 9.05); red:clause:ieor (4/16, lift 3.58); split:target | teams | distribute | parallel | do (3/17, lift 2.53); dir:do (6/36, lift 2.39); clause:collapse (5/30, lift 2.39); chain:target teams distribute (5/33, lift 2.17); chain:target parallel do simd (3/20, lift 2.15); clause:default:shared (3/20, lift 2.15)

| feature pair | programs | run_error | rate | best single rate | lift |
|---|---|---|---|---|---|
| loop:down + map:from | 20 | 6 | 0.3 | 0.121 | 4.3 |
| dir:parallel + dir:simd | 15 | 4 | 0.267 | 0.125 | 3.82 |
| body:call_declare_target + dir:distribute | 19 | 5 | 0.263 | 0.133 | 3.77 |
| clause:collapse + map:to | 21 | 5 | 0.238 | 0.167 | 3.41 |
| declare_target_function + dir:do | 21 | 5 | 0.238 | 0.167 | 3.41 |
| dir:distribute + dir:do | 21 | 5 | 0.238 | 0.167 | 3.41 |
| dir:do + dir:teams | 21 | 5 | 0.238 | 0.167 | 3.41 |
| clause:lastprivate + loop:down | 17 | 4 | 0.235 | 0.129 | 3.37 |

## Compile rejections (features not supported)

### afar

| programs | message |
|---|---|
| 123 | not_implemented: error: loc("<path> <path> not yet implemented: lastprivate clause in constructs other than simd/worksharing-loop/taskloop |
| 50 | not_implemented: loc("<path> error: not yet implemented: Unhandled clause order in omp.wsloop operation |
| 24 | not_implemented: loc("<path> error: not yet implemented: Unhandled clause order in omp.distribute operation |
| 22 | not_implemented: error: loc("<path> <path> not yet implemented: Firstprivate is currently unsupported defaultmap behaviour |
| 18 | not_implemented: error: loc("<path> <path> not yet implemented: lastprivate(conditional:) on simd construct |
| 3 | not_implemented: error: loc("<path> <path> not yet implemented: lastprivate(conditional:) on do simd composite construct |

Features most associated with rejection: clause:order (96/96); defaultmap:firstprivate:scalar (18/18); clause:lastprivate:conditional (27/32); clause:lastprivate (161/231); split:target | parallel do (11/18); split:target | teams | distribute (47/92); split:target teams distribute (14/28); clause:schedule:static (22/45)

### cce19

| programs | message |
|---|---|
| 172 | diagnostic: ftn-1370 ftn: ERROR , \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET. |
| 46 | diagnostic: ftn-1370 ftn: ERROR , \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET PARALLEL. |
| 25 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP DISTRIBUTE. |
| 23 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 12 | diagnostic: ftn-1370 ftn: ERROR , \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET SIMD. |
| 6 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP TARGET TEAMS DISTRIBUTE. |
| 4 | diagnostic: ftn-1370 ftn: ERROR , \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET PARALLEL LOOP. |
| 3 | diagnostic: ftn-1310 ftn: ERROR , \| Object "I" is specified on the FIRSTPRIVATE clause. It must have a shared scope in the enclosing region. |
| 2 | not_implemented: Unsupported OpenMP construct Private of allocatables -- ib |
| 2 | not_implemented: Unsupported OpenMP construct Private of allocatables -- o1 |
| 1 | diagnostic: ftn-1964 ftn: ERROR , \| Variable "S1" must have its data mapping attribute explicitly declared because default map(none) was specified. |
| 1 | not_implemented: Unsupported OpenMP construct Private of allocatables -- ic |

Features most associated with rejection: clause:num_teams:lower_bound (32/32); clause:thread_limit (250/301); red:atomic:+ (9/16); clause:order (51/96); guard:single (17/33); split:target | teams | distribute (46/92); dir:teams loop (11/22); split:target | teams loop (11/22)

### cce20

| programs | message |
|---|---|
| 31 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 27 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP DISTRIBUTE. |
| 6 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP TARGET TEAMS DISTRIBUTE. |
| 4 | diagnostic: ftn-1310 ftn: ERROR , \| Object "I" is specified on the FIRSTPRIVATE clause. It must have a shared scope in the enclosing region. |
| 1 | diagnostic: ftn-1510 ftn: ERROR , \| Variable "I" must have its data scope explicitly declared because DEFAULT(NONE) was specified. |

Features most associated with rejection: clause:num_teams:lower_bound (32/32); clause:order (35/96); split:target teams distribute (10/28); split:target | teams | distribute (32/92); chain:target teams distribute (46/153); clause:num_teams (47/180); split:target teams | distribute (6/25); dir:target teams distribute (12/51)

### cce21

| programs | message |
|---|---|
| 69 | link_undefined_symbol: lld: error: undefined symbol: _cray$mt_taskwait |
| 31 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 27 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP DISTRIBUTE. |
| 6 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP TARGET TEAMS DISTRIBUTE. |
| 4 | diagnostic: ftn-1310 ftn: ERROR , \| Object "I" is specified on the FIRSTPRIVATE clause. It must have a shared scope in the enclosing region. |
| 1 | diagnostic: ftn-1510 ftn: ERROR , \| Variable "I" must have its data scope explicitly declared because DEFAULT(NONE) was specified. |

Features most associated with rejection: clause:num_teams:lower_bound (32/32); red:in_reduction:+ (40/60); clause:in_reduction (73/119); dir:taskgroup (73/119); kernel:inred (73/119); red:in_reduction:* (40/66); split:target teams distribute (12/28); clause:order (39/96)

### nvhpc

| programs | message |
|---|---|
| 15 | diagnostic: NVFORTRAN-S-0034-Syntax error at or near : (<path> 62) |
| 14 | diagnostic: NVFORTRAN-S-0034-Syntax error at or near : (<path> 56) |
| 14 | diagnostic: NVFORTRAN-S-0034-Syntax error at or near : (<path> 63) |
| 13 | diagnostic: NVFORTRAN-S-0034-Syntax error at or near : (<path> 58) |
| 13 | diagnostic: NVFORTRAN-S-0034-Syntax error at or near : (<path> 59) |
| 11 | diagnostic: NVFORTRAN-S-0034-Syntax error at or near : (<path> 68) |
| 11 | diagnostic: NVFORTRAN-S-0034-Syntax error at or near : (<path> 51) |
| 11 | diagnostic: NVFORTRAN-S-0034-Syntax error at or near : (<path> 44) |
| 10 | diagnostic: NVFORTRAN-S-0034-Syntax error at or near : (<path> 45) |
| 10 | diagnostic: NVFORTRAN-S-0034-Syntax error at or near : (<path> 50) |
| 9 | diagnostic: NVFORTRAN-S-0034-Syntax error at or near : (<path> 42) |
| 9 | diagnostic: NVFORTRAN-S-0034-Syntax error at or near : (<path> 57) |

Features most associated with rejection: map:mod:close (282/282); map:mod:present (127/127); clause:in_reduction (119/119); dir:taskgroup (119/119); kernel:inred (119/119); clause:nontemporal (82/82); red:in_reduction:* (66/66); red:in_reduction:+ (60/60)

### nvhpc269

| programs | message |
|---|---|
| 15 | diagnostic: NVFORTRAN-S-0034-Syntax error at or near : (<path> 62) |
| 14 | diagnostic: NVFORTRAN-S-0034-Syntax error at or near : (<path> 56) |
| 14 | diagnostic: NVFORTRAN-S-0034-Syntax error at or near : (<path> 63) |
| 13 | diagnostic: NVFORTRAN-S-0034-Syntax error at or near : (<path> 58) |
| 13 | diagnostic: NVFORTRAN-S-0034-Syntax error at or near : (<path> 59) |
| 11 | diagnostic: NVFORTRAN-S-0034-Syntax error at or near : (<path> 68) |
| 11 | diagnostic: NVFORTRAN-S-0034-Syntax error at or near : (<path> 51) |
| 11 | diagnostic: NVFORTRAN-S-0034-Syntax error at or near : (<path> 44) |
| 10 | diagnostic: NVFORTRAN-S-0034-Syntax error at or near : (<path> 45) |
| 10 | diagnostic: NVFORTRAN-S-0034-Syntax error at or near : (<path> 50) |
| 9 | diagnostic: NVFORTRAN-S-0034-Syntax error at or near : (<path> 42) |
| 9 | diagnostic: NVFORTRAN-S-0034-Syntax error at or near : (<path> 57) |

Features most associated with rejection: map:mod:close (282/282); map:mod:present (127/127); clause:in_reduction (119/119); dir:taskgroup (119/119); kernel:inred (119/119); clause:nontemporal (82/82); red:in_reduction:* (66/66); red:in_reduction:+ (60/60)

## Generator rejects

Programs failing a legality check are never run. Causes (`rules`: a 5.2 rule of offload.engine.rules fired, a generator or rule bug; `flang`: AFAR flang's frontend refused a program the rules and gfortran accept; see the report for which of these are flang's errors):

| count | cause | seeds |
|---|---|---|

## Flaky results

- seed 13 cce19: wrong_code: checksum=279056129 ran_on_host=0 expected=1984387845 | wrong_code: checksum=1741820630 ran_on_host=0 expected=1984387845 | wrong_code: checksum=111422627 ran_on_host=0 expected=1984387845 | wrong_code: checksum=427612897 ran_on_host=0 expected=1984387845
- seed 13 cce20: wrong_code: checksum=222544481 ran_on_host=0 expected=1984387845 | wrong_code: checksum=222544481 ran_on_host=0 expected=1984387845 | wrong_code: checksum=222544481 ran_on_host=0 expected=1984387845 | wrong_code: checksum=1948651100 ran_on_host=0 expected=1984387845
- seed 13 cce21: wrong_code: checksum=643921491 ran_on_host=0 expected=1984387845 | wrong_code: checksum=1065298501 ran_on_host=0 expected=1984387845 | wrong_code: checksum=1065298501 ran_on_host=0 expected=1984387845 | wrong_code: checksum=643921491 ran_on_host=0 expected=1984387845
- seed 60 cce19: wrong_code: checksum=950737074 ran_on_host=0 expected=774564267 | wrong_code: checksum=200415217 ran_on_host=0 expected=774564267 | wrong_code: checksum=756035346 ran_on_host=0 expected=774564267 | wrong_code: checksum=1183653958 ran_on_host=0 expected=774564267
- seed 163 cce19: wrong_code: checksum=1807014051 ran_on_host=0 expected=594933126 | wrong_code: checksum=1546167020 ran_on_host=0 expected=594933126 | wrong_code: checksum=19467643 ran_on_host=0 expected=594933126 | wrong_code: checksum=1129556314 ran_on_host=0 expected=594933126
- seed 163 cce20: wrong_code: checksum=1546167020 ran_on_host=0 expected=594933126 | wrong_code: checksum=1546167020 ran_on_host=0 expected=594933126 | wrong_code: checksum=984382261 ran_on_host=0 expected=594933126 | wrong_code: checksum=1546167020 ran_on_host=0 expected=594933126
- seed 241 cce19: wrong_code: checksum=674945519 ran_on_host=0 expected=923044499 | wrong_code: checksum=1626480022 ran_on_host=0 expected=923044499 | wrong_code: checksum=674945519 ran_on_host=0 expected=923044499 | wrong_code: checksum=1626480022 ran_on_host=0 expected=923044499
- seed 372 nvhpc269: timeout: timeout | agree: checksum=2119263646 ran_on_host=0
- seed 393 cce19: wrong_code: checksum=846675790 ran_on_host=0 expected=1410599432 | agree: checksum=1410599432 ran_on_host=0 | wrong_code: checksum=846675790 ran_on_host=0 expected=1410599432 | agree: checksum=1410599432 ran_on_host=0
- seed 407 cce19: wrong_code: checksum=1134950331 ran_on_host=0 expected=338234045 | wrong_code: checksum=951595428 ran_on_host=0 expected=338234045 | wrong_code: checksum=926746826 ran_on_host=0 expected=338234045 | wrong_code: checksum=1495340588 ran_on_host=0 expected=338234045
- seed 407 cce20: wrong_code: checksum=1684897878 ran_on_host=0 expected=338234045 | wrong_code: checksum=1718558222 ran_on_host=0 expected=338234045 | wrong_code: checksum=1651237534 ran_on_host=0 expected=338234045 | wrong_code: checksum=1651237534 ran_on_host=0 expected=338234045
- seed 407 cce21: wrong_code: checksum=1684897878 ran_on_host=0 expected=338234045 | wrong_code: checksum=1651237534 ran_on_host=0 expected=338234045 | wrong_code: checksum=1718558222 ran_on_host=0 expected=338234045 | wrong_code: checksum=1651237534 ran_on_host=0 expected=338234045
- seed 415 cce19: wrong_code: checksum=1287247469 ran_on_host=0 expected=551121403 | wrong_code: checksum=751966466 ran_on_host=0 expected=551121403 | wrong_code: checksum=1933747485 ran_on_host=0 expected=551121403 | wrong_code: checksum=846223677 ran_on_host=0 expected=551121403
- seed 415 cce20: wrong_code: checksum=269115161 ran_on_host=0 expected=551121403 | wrong_code: checksum=269115161 ran_on_host=0 expected=551121403 | wrong_code: checksum=269115161 ran_on_host=0 expected=551121403 | wrong_code: checksum=1617629240 ran_on_host=0 expected=551121403
- seed 467 cce19: wrong_code: checksum=1360452543 ran_on_host=0 expected=224568895 | wrong_code: checksum=1847410531 ran_on_host=0 expected=224568895 | wrong_code: checksum=1360452543 ran_on_host=0 expected=224568895 | wrong_code: checksum=1360452543 ran_on_host=0 expected=224568895
- seed 651 cce19: wrong_code: checksum=901868901 ran_on_host=0 expected=1826371849 | wrong_code: checksum=901868901 ran_on_host=0 expected=1826371849 | wrong_code: checksum=901868901 ran_on_host=0 expected=1826371849 | wrong_code: checksum=99713460 ran_on_host=0 expected=1826371849
- seed 909 cce19: wrong_code: checksum=1045203083 ran_on_host=0 expected=1418547638 | wrong_code: checksum=1045203083 ran_on_host=0 expected=1418547638 | wrong_code: checksum=1045203083 ran_on_host=0 expected=1418547638 | wrong_code: checksum=373725969 ran_on_host=0 expected=1418547638
- seed 925 cce19: wrong_code: checksum=223318447 ran_on_host=0 expected=1033123183 | wrong_code: checksum=2024920247 ran_on_host=0 expected=1033123183 | wrong_code: checksum=1350997328 ran_on_host=0 expected=1033123183 | wrong_code: checksum=1386295564 ran_on_host=0 expected=1033123183
- seed 992 cce19: wrong_code: checksum=786937634 ran_on_host=0 expected=358113607 | wrong_code: checksum=1608649111 ran_on_host=0 expected=358113607 | wrong_code: checksum=542414361 ran_on_host=0 expected=358113607 | wrong_code: checksum=1782951073 ran_on_host=0 expected=358113607
- seed 992 cce20: wrong_code: checksum=190796792 ran_on_host=0 expected=358113607 | wrong_code: checksum=1886174243 ran_on_host=0 expected=358113607 | wrong_code: checksum=1886174243 ran_on_host=0 expected=358113607 | wrong_code: checksum=190796792 ran_on_host=0 expected=358113607

## Appendix: host reference checks (not offload findings)

Device offload only: host runs (OMP_TARGET_OFFLOAD=disabled) and the sequential elision are references for the expected value, never measurements of a toolchain. A host_path_failure below is recorded data (results/fuzz/<run>/summary.json), not an offload finding, and it counts nowhere in the tables above.

The reference host run (OMP_TARGET_OFFLOAD=disabled, the first toolchain that compiled) failed for 0 programs (host_ref_failed) and printed another checksum than the model for 6 (host_mismatch). For each, every toolchain whose build compiled ran it on the host (rebuilt and run twice: results/fuzz/n0x0/hostcheck.jsonl), and the sequential elision (offload.engine.expected) ran where it applies. Rule: **valid** when at least one of them prints the model's checksum; the host builds that ran and did not are `host_path_failure` records (a host-path compiler or runtime bug: out of scope, not an offload finding). **noncompliant** when none does (a generator or model defect): excluded from the findings and the tallies above. A toolchain whose build does not compile has no host build ('no host build'). Values are host checksums. Scope: only these programs had every toolchain's host build run; for the others only the reference toolchain's host run exists, so host_path_failure counts are a lower bound.

| seed | reference | ref tc | model | afar host | cce19 host | cce20 host | cce21 host | nvhpc host | nvhpc269 host | elision | validity | host_path_failure |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 18 | host_mismatch | cce20 | 1947133868 | no build: compile_reject | no build: compile_reject | 540990624 | 540990624 | - | - | **checksum=1947133868** | valid | cce20, cce21 |
| 209 | host_mismatch | cce19 | 884471902 | no build: compile_reject | 1256899722 | 1256899722 | 1256899722 | - | - | **checksum=884471902** | valid | cce19, cce20, cce21 |
| 357 | host_mismatch | cce19 | 249542094 | no build: compile_reject | 1738638814 | 1738638814 | 1738638814 | - | - | **checksum=249542094** | valid | cce19, cce20, cce21 |
| 485 | host_mismatch | afar | 131415404 | 1033096498 | no build: compile_reject | no build: ice | no build: ice | - | - | **checksum=131415404** | valid | afar |
| 786 | host_mismatch | afar | 1933010909 | 2121212958 | **1933010909** | **1933010909** | **1933010909** | - | - | **checksum=1933010909** | valid | afar |
| 992 | host_mismatch | cce19 | 358113607 | no build: compile_reject | 192406149 | 192406149 | 192406149 | - | - | **checksum=358113607** | valid | cce19, cce20, cce21 |

### host_path_failure (valid programs; host-path failures, out of scope)

- afar: 2 programs (seeds 485, 786)
- cce19: 3 programs (seeds 209, 357, 992)
- cce20: 4 programs (seeds 18, 209, 357, 992)
- cce21: 4 programs (seeds 18, 209, 357, 992)

### Noncompliant programs (generator/model investigation)

(none)
