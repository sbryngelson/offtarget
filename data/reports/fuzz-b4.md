# Fuzz campaign `b4`

Csmith-style random OpenMP 5.2 Fortran offload programs (offload.engine.fuzz, generator `fuzz-3`, base-language groups: declare (offload.engine.fuzz_base)), run on every toolchain at -O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory; reference: the Python model of each program, checked against a host run (OMP_TARGET_OFFLOAD=disabled, a reference only; see the appendix 'Host reference checks' for the programs whose host run failed or disagreed). Machine-readable: results/fuzz/b4/summary.json.

## Size and timing

- programs generated: 300; legal and run: 300 (judged: 297; noncompliant, excluded from every count below: 3); generator rejects: 0; worker crashes: 0
- campaign wall time: 2573 s with 7 workers (420 programs/hour; 49.9 s per program and worker, all toolchains and repeats included)
- programs whose device results agree with the model on every toolchain: 23

## Classes per toolchain

Rejections (compile_reject) are features a toolchain does not support, not failures. Flaky = the repeats differed (counted in the worst class).

| class | afar | cce19 | cce20 | cce21 |
|---|---|---|---|---|
| agree | 173 | 37 | 57 | 134 |
| compile_reject | 107 | 228 | 193 | 72 |
| ice | 0 | 24 | 33 | 74 |
| wrong_code | 5 (1 flaky) | 3 (1 flaky) | 6 (2 flaky) | 17 (3 flaky) |
| host_fallback | 0 | 0 | 0 | 0 |
| timeout | 0 | 1 | 0 | 0 |
| run_error | 12 | 4 | 8 | 0 |
| harness_error | 0 | 0 | 0 | 0 |

## Base-language features

Per base-language feature (offload.engine.fuzz_base): the programs that have it, and per toolchain agree / compile_reject / ice / wrong_code / run_error (other classes in parentheses when present).

| feature | programs | afar | cce19 | cce20 | cce21 |
|---|---|---|---|---|---|
| dc:call:gd1 | 52 | 25/23/0/1/3 | 7/38/3/2/2 | 10/35/4/1/2 | 22/13/11/6/0 |
| dc:call:gd2 | 43 | 20/17/0/1/5 | 3/33/7/0/0 | 6/29/8/0/0 | 11/15/16/1/0 |
| dc:call:gm0 | 65 | 34/25/0/2/4 | 4/45/12/2/1 (1) | 8/40/15/1/1 | 19/14/27/5/0 |
| dc:call_across_modules | 175 | 103/62/0/3/7 | 23/132/16/1/3 | 34/113/22/2/4 | 74/44/46/11/0 |
| dc:declare_mapper:default | 68 | 40/23/0/1/4 | 8/53/6/1/0 | 10/46/10/2/0 | 26/15/23/4/0 |
| dc:declare_mapper:named | 113 | 62/44/0/2/5 | 15/87/6/0/4 (1) | 20/73/11/1/8 | 51/32/26/4/0 |
| dc:declare_reduction | 39 | 0/39/0/0/0 | 0/38/1/0/0 | 0/37/2/0/0 | 0/32/7/0/0 |
| dc:declare_reduction_available | 182 | 97/75/0/4/6 | 21/142/14/1/3 (1) | 29/124/20/2/7 | 78/52/47/5/0 |
| dc:declare_target_array | 256 | 144/97/0/4/11 | 29/198/21/3/4 (1) | 45/169/30/5/7 | 111/64/66/15/0 |
| dc:declare_target_enter | 168 | 94/63/0/1/10 | 0/168/0/0/0 | 0/168/0/0/0 | 78/41/41/8/0 |
| dc:declare_target_output | 73 | 44/23/0/2/4 | 4/60/6/0/2 (1) | 9/50/10/1/3 | 31/18/20/4/0 |
| dc:declare_target_structure | 183 | 109/64/0/5/5 | 22/137/17/3/3 (1) | 35/116/22/6/4 | 81/41/46/15/0 |
| dc:declare_target_to | 114 | 67/41/0/4/2 | 33/50/23/3/4 (1) | 50/19/32/6/7 | 46/27/32/9/0 |
| dc:device_function_reads_module_var | 185 | 106/68/0/3/8 | 20/141/17/3/3 (1) | 34/120/22/4/5 | 81/46/45/13/0 |
| dc:map_with_named_mapper | 38 | 15/19/0/1/3 | 0/30/4/0/4 | 0/25/5/0/8 | 13/10/13/2/0 |
| dc:static_init | 169 | 93/67/0/1/8 | 20/130/13/2/4 | 28/111/19/4/7 | 75/40/42/12/0 |
| dt:map:components | 58 | 30/23/0/2/3 | 10/44/3/1/0 | 12/34/8/3/1 | 19/19/15/5/0 |
| dt:map:implicit | 64 | 30/30/0/2/2 | 5/52/5/0/1 (1) | 8/46/8/0/2 | 20/19/22/3/0 |
| dt:map:mod:always | 9 | 4/4/0/0/1 | 0/8/0/0/1 | 0/7/0/0/2 | 5/1/3/0/0 |
| dt:map:mod:close | 10 | 3/6/0/1/0 | 0/9/1/0/0 | 0/7/2/0/1 | 2/3/5/0/0 |
| dt:map:mod:mapper(mmap) | 38 | 15/19/0/1/3 | 0/30/4/0/4 | 0/25/5/0/8 | 13/10/13/2/0 |
| dt:map:mod:present | 6 | 2/2/0/1/1 | 0/4/1/0/1 | 0/3/1/0/2 | 5/0/1/0/0 |
| dt:map:whole | 58 | 27/25/0/1/5 | 1/48/5/0/4 | 1/43/6/0/8 | 20/17/17/4/0 |
| dt:target_update_component | 31 | 9/17/0/1/4 | 3/23/4/1/0 | 5/20/4/1/1 | 12/7/10/2/0 |

## Known findings rediscovered

- cce19-target-parallel-guarded-loop (wrong code on cce19 in a program with a thread-0-guarded sequential loop in target parallel): 2 programs (seeds 50, 142)
- cce21-defaultmap-aggregate-flag (wrong code or host fallback on cce21 where cce20 agrees, in a program with a defaultmap clause; the finding's symptom: a map(tofrom) scalar is not copied back): 4 programs (seeds 75, 142, 172, 219)
- (control for the line above: the same without a defaultmap clause): 0 programs (seeds )
- cce21-in-reduction-taskwait-link (cce21 link failure on _cray$mt_taskwait): 16 programs (seeds 25, 69, 97, 98, 117, 127, 128, 165, 178, 194, 197, 198)
- cce19-target-parallel-single-ice / task ICE (CCE 'unhandled construct type'): 59 programs (seeds 24, 32, 38, 40, 42, 48, 51, 56, 59, 60, 62, 67)

## Distinct minimized failures

| file | toolchain | kind | also fails on | lines | expected | observed |
|---|---|---|---|---|---|---|
| `data/findings/fuzz/b4-86-cce19.f90` | cce19 | run_error | cce20 | 167 -> 48 | runs to completion (the host run does) | device: fail crash: SIGABRT; host reference (afar) checksum=0 |
| `data/findings/fuzz/b4-39-afar.f90` | afar | wrong_code | - | 154 -> 124 | the host reference checksum (host reference (cce19) checksum=1462161356) | device checksum=617091188 ran_on_host=0 |

Not minimized:

- seed 253 cce20 wrong_code: not_reproduced no reference outside the failing compiler family (another family's host run, or sequential elision) matches the model
- seed 9 afar run_error: not_reproduced no reference outside the failing compiler family (another family's host run, or sequential elision) matches the model

## Wrong code (all programs)

- afar: 5 programs (seeds 39, 82, 169, 209, 213)
- cce19: 3 programs (seeds 50, 142, 253)
- cce20: 6 programs (seeds 50, 99, 198, 210, 253, 291)
- cce21: 17 programs (seeds 21, 44, 50, 75, 99, 142, 157, 163, 172, 210, 219, 227, 234, 249, 253, 288, 291)

## Internal compiler errors (deduplicated by message)

| toolchain | programs | message | seeds |
|---|---|---|---|
| cce21 | 37 | ice: INTERNAL COMPILER ERROR: "unhandled acc construct type" (v_openmp.c, line 8265, version <v>) | 24, 32, 38, 42, 48 |
| cce19 | 21 | ice: INTERNAL COMPILER ERROR: "unhandled construct type" (v_openmp.c, line 7617, version <v>) | 51, 56, 80, 82, 107 |
| cce21 | 21 | ice: INTERNAL COMPILER ERROR: "unhandled construct type" (v_openmp.c, line 8197, version <v>) | 40, 62, 71, 82, 107 |
| cce20 | 17 | ice: INTERNAL COMPILER ERROR: "unhandled acc construct type" (v_openmp.c, line 7881, version <v>) | 42, 51, 56, 80, 140 |
| cce21 | 14 | ice: INTERNAL COMPILER ERROR: "ACC - barrier/reset/protected last private not supported" (v_mt_translate.c, line 5798, version <v>) | 16, 22, 47, 78, 88 |
| cce20 | 10 | ice: INTERNAL COMPILER ERROR: "unhandled construct type" (v_openmp.c, line 7814, version <v>) | 62, 82, 107, 110, 125 |
| cce20 | 6 | ice: INTERNAL COMPILER ERROR: "ACC - barrier/reset/protected last private not supported" (v_mt_translate.c, line 5607, version <v>) | 22, 78, 88, 205, 251 |
| cce19 | 3 | ice: INTERNAL COMPILER ERROR: "ACC - barrier/reset/protected last private not supported" (v_mt_translate.c, line 4874, version <v>) | 22, 78, 251 |
| cce21 | 1 | ice: INTERNAL COMPILER ERROR: "Mismatched last induction expression for last private operators" (v_mt_translate.c, line 911, version <v>) | 191 |
| cce21 | 1 | ice: INTERNAL COMPILER ERROR: "unhandled operator | 276 |

## Run errors, timeouts, host fallbacks

| toolchain | class | programs | reason | seeds |
|---|---|---|---|---|
| cce20 | run_error | 8 | crash: SIGABRT; without mandatory: crash: SIGABRT | 11, 72, 86, 105, 134 |
| afar | run_error | 6 | crash: SIGABRT; without mandatory: crash: SIGABRT | 9, 35, 172, 231, 275 |
| afar | run_error | 6 | crash: SIGSEGV; without mandatory: crash: SIGSEGV | 33, 34, 87, 111, 136 |
| cce19 | run_error | 4 | crash: SIGABRT; without mandatory: crash: SIGABRT | 86, 134, 256, 298 |
| cce19 | timeout | 1 | compile_timeout | 282 |

## Features and feature pairs most associated with failures

Among programs the toolchain compiled (or crashed on). Lift = the rate of the class among programs with the feature (pair) over the toolchain's overall rate; a pair is listed only when it beats both of its features alone by 25%.

### afar: wrong_code

Single features: red:clause:* (3/15, lift 7.6); scalar:tofrom (3/26, lift 4.38); clause:default:none (3/31, lift 3.68); wrap:target_data (3/40, lift 2.85); red:clause (4/54, lift 2.81); loop:step2 (3/44, lift 2.59); dir:do (3/54, lift 2.11); base:dc:declare_target_to (4/73, lift 2.08)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| body:temp + scalar:tofrom | 15 | 3 | 0.2 | 0.115 | 7.6 |
| base:dc:declare_target_to + wrap:target_data | 16 | 3 | 0.188 | 0.075 | 7.12 |
| red:clause + wrap:target_data | 17 | 3 | 0.176 | 0.075 | 6.71 |
| base:dc:declare_reduction_available + clause:default:none | 18 | 3 | 0.167 | 0.097 | 6.33 |
| base:dc:declare_target_structure + scalar:tofrom | 18 | 3 | 0.167 | 0.115 | 6.33 |
| dir:target + scalar:tofrom | 19 | 3 | 0.158 | 0.115 | 6.0 |
| base:dc:declare_target_structure + clause:default:none | 20 | 3 | 0.15 | 0.097 | 5.7 |
| dir:do + loop:step2 | 20 | 3 | 0.15 | 0.068 | 5.7 |

### afar: run_error

Single features: tasking:nowait_depend (9/29, lift 4.91); map:mod:present (6/22, lift 4.32); wrap:host_update_to (5/24, lift 3.3); split:target | teams | distribute | parallel | do simd (3/15, lift 3.17); base:dc:call:gd2 (5/26, lift 3.04); chain:target teams distribute parallel do simd (4/22, lift 2.88); clause:dist_schedule (5/28, lift 2.83); chain:target parallel do (6/35, lift 2.71)

| feature pair | programs | run_error | rate | best single rate | lift |
|---|---|---|---|---|---|
| body:call_declare_target + tasking:nowait_depend | 16 | 8 | 0.5 | 0.31 | 7.92 |
| base:dc:declare_target_enter + tasking:nowait_depend | 19 | 8 | 0.421 | 0.31 | 6.67 |
| base:dc:static_init + tasking:nowait_depend | 17 | 7 | 0.412 | 0.31 | 6.52 |
| map:to + tasking:nowait_depend | 22 | 9 | 0.409 | 0.31 | 6.48 |
| base:dc:call_across_modules + tasking:nowait_depend | 15 | 6 | 0.4 | 0.31 | 6.33 |
| decl:allocatable_rank2 + map:mod:present | 15 | 6 | 0.4 | 0.273 | 6.33 |
| dir:teams + tasking:nowait_depend | 15 | 6 | 0.4 | 0.31 | 6.33 |
| map:mod:present + map:to | 16 | 6 | 0.375 | 0.273 | 5.94 |

### cce19: wrong_code

Single features: dir:do (3/21, lift 3.29); dir:target parallel (3/22, lift 3.14); dir:simd (3/24, lift 2.88); loop:down (3/29, lift 2.38); body:call_declare_target (3/40, lift 1.73); map:to (3/42, lift 1.64); decl:explicit_rank2 (3/43, lift 1.6); base:dc:device_function_reads_module_var (3/44, lift 1.57)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| body:call_declare_target + dir:do | 15 | 3 | 0.2 | 0.143 | 4.6 |
| decl:explicit_rank2 + dir:target parallel | 15 | 3 | 0.2 | 0.136 | 4.6 |
| dir:target + dir:target parallel | 15 | 3 | 0.2 | 0.136 | 4.6 |
| base:dc:declare_target_structure + loop:down | 16 | 3 | 0.188 | 0.103 | 4.31 |
| body:call_declare_target + dir:simd | 16 | 3 | 0.188 | 0.125 | 4.31 |
| dir:do + map:to | 16 | 3 | 0.188 | 0.143 | 4.31 |
| dir:target parallel + map:to | 16 | 3 | 0.188 | 0.136 | 4.31 |
| base:dc:device_function_reads_module_var + dir:target parallel | 17 | 3 | 0.176 | 0.136 | 4.06 |

### cce19: ice

Single features: kernel:phase (15/15, lift 2.88); dir:target parallel (17/22, lift 2.22); base:dc:call:gm0 (12/20, lift 1.73); clause:num_threads (10/18, lift 1.6); clause:lastprivate (9/17, lift 1.52); map:mod:always (9/19, lift 1.36); clause:device (8/17, lift 1.35); map:to (19/42, lift 1.3)

| feature pair | programs | ice | rate | best single rate | lift |
|---|---|---|---|---|---|
| base:dc:call_across_modules + body:call_declare_target | 23 | 14 | 0.609 | 0.45 | 1.75 |
| base:dc:declare_reduction_available + map:from | 19 | 10 | 0.526 | 0.351 | 1.51 |
| base:dc:call_across_modules + base:dc:device_function_reads_module_var | 22 | 11 | 0.5 | 0.386 | 1.44 |
| base:dc:declare_reduction_available + loop:down | 19 | 9 | 0.474 | 0.35 | 1.36 |

### cce19: run_error

Single features: clause:if:target (3/15, lift 3.45); base:dc:declare_mapper:named (4/26, lift 2.65); map:from (4/37, lift 1.86); loop:down (3/29, lift 1.78); base:dc:static_init (4/39, lift 1.77); dir:distribute (3/30, lift 1.73); base:dc:declare_reduction_available (3/40, lift 1.29); body:call_declare_target (3/40, lift 1.29)

| feature pair | programs | run_error | rate | best single rate | lift |
|---|---|---|---|---|---|
| base:dc:declare_mapper:named + base:dc:static_init | 16 | 4 | 0.25 | 0.154 | 4.31 |
| base:dc:static_init + map:from | 20 | 4 | 0.2 | 0.108 | 3.45 |
| dir:distribute + map:from | 16 | 3 | 0.188 | 0.108 | 3.23 |
| base:dc:device_function_reads_module_var + loop:down | 17 | 3 | 0.176 | 0.103 | 3.04 |
| base:dc:call_across_modules + dir:distribute | 19 | 3 | 0.158 | 0.1 | 2.72 |
| base:dc:declare_reduction_available + map:from | 19 | 3 | 0.158 | 0.108 | 2.72 |
| base:dc:static_init + dir:distribute | 19 | 3 | 0.158 | 0.103 | 2.72 |
| base:dc:static_init + loop:down | 19 | 3 | 0.158 | 0.103 | 2.72 |

### cce20: wrong_code

Single features: clause:proc_bind (4/17, lift 4.08); kernel:guard (4/23, lift 3.01); chain:target parallel do (3/22, lift 2.36); dir:target parallel (4/31, lift 2.24); base:dt:map:components (3/24, lift 2.17); clause:lastprivate (3/24, lift 2.17); loop:step2 (3/24, lift 2.17); clause:schedule (3/25, lift 2.08)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| base:dc:declare_target_structure + kernel:guard | 17 | 4 | 0.235 | 0.174 | 4.08 |
| decl:allocatable_rank2 + kernel:guard | 17 | 4 | 0.235 | 0.174 | 4.08 |
| decl:explicit_rank1 + kernel:guard | 18 | 4 | 0.222 | 0.174 | 3.85 |
| decl:allocatable_rank2 + dir:target parallel | 19 | 4 | 0.211 | 0.129 | 3.65 |
| base:dc:declare_target_structure + chain:target parallel do | 15 | 3 | 0.2 | 0.136 | 3.47 |
| base:dc:static_init + map:mod:always | 15 | 3 | 0.2 | 0.107 | 3.47 |
| body:temp + dir:do | 15 | 3 | 0.2 | 0.108 | 3.47 |
| chain:target parallel do + decl:allocatable_rank2 | 15 | 3 | 0.2 | 0.136 | 3.47 |

### cce20: ice

Single features: kernel:phase (19/19, lift 3.15); phase:do (18/18, lift 3.15); dir:target parallel (24/31, lift 2.44); base:dc:call:gm0 (15/25, lift 1.89); clause:lastprivate (14/24, lift 1.84); clause:num_threads (12/23, lift 1.64); clause:default:none (9/18, lift 1.58); base:dc:declare_mapper:default (10/22, lift 1.43)

| feature pair | programs | ice | rate | best single rate | lift |
|---|---|---|---|---|---|
| base:dc:device_function_reads_module_var + clause:lastprivate | 15 | 11 | 0.733 | 0.583 | 2.31 |
| base:dc:call_across_modules + body:call_declare_target | 32 | 18 | 0.562 | 0.426 | 1.77 |
| body:call_declare_target + map:mod:close | 16 | 9 | 0.562 | 0.426 | 1.77 |
| base:dc:call_across_modules + dir:do | 20 | 11 | 0.55 | 0.421 | 1.73 |
| map:mod:always + map:to | 20 | 11 | 0.55 | 0.429 | 1.73 |
| base:dc:call_across_modules + map:to | 38 | 18 | 0.474 | 0.379 | 1.49 |
| base:dc:declare_reduction_available + red:clause | 17 | 8 | 0.471 | 0.345 | 1.48 |
| base:dc:call_across_modules + dir:simd | 15 | 7 | 0.467 | 0.355 | 1.47 |

### cce20: run_error

Single features: base:dt:map:whole (8/15, lift 6.93); clause:if:target (5/23, lift 2.83); base:dc:declare_mapper:named (8/40, lift 2.6); clause:thread_limit (6/36, lift 2.17); scalar:implicit (5/30, lift 2.17); dir:loop (3/20, lift 1.95); loop:down (6/44, lift 1.77); body:temp (5/37, lift 1.76)

| feature pair | programs | run_error | rate | best single rate | lift |
|---|---|---|---|---|---|
| base:dc:declare_mapper:named + loop:down | 17 | 6 | 0.353 | 0.2 | 4.59 |
| base:dc:declare_mapper:named + scalar:implicit | 15 | 5 | 0.333 | 0.2 | 4.33 |
| base:dc:declare_mapper:named + dir:distribute | 19 | 6 | 0.316 | 0.2 | 4.11 |
| base:dc:declare_mapper:named + base:dc:declare_reduction_available | 23 | 7 | 0.304 | 0.2 | 3.96 |
| base:dc:declare_mapper:named + clause:thread_limit | 20 | 6 | 0.3 | 0.2 | 3.9 |
| base:dc:declare_mapper:named + map:from | 20 | 6 | 0.3 | 0.2 | 3.9 |
| clause:thread_limit + dir:distribute | 20 | 6 | 0.3 | 0.167 | 3.9 |
| base:dc:declare_mapper:named + body:temp | 17 | 5 | 0.294 | 0.2 | 3.82 |

### cce21: wrong_code

Single features: kernel:guard (12/48, lift 3.31); clause:proc_bind (7/34, lift 2.72); dir:parallel do (3/17, lift 2.34); dir:target parallel (11/68, lift 2.14); split:target | simd (3/19, lift 2.09); scalar:implicit (11/70, lift 2.08); base:dc:call:gd1 (6/39, lift 2.04); loop:step2 (8/53, lift 2.0)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| kernel:guard + scalar:implicit | 19 | 8 | 0.421 | 0.25 | 5.57 |
| kernel:guard + loop:step2 | 15 | 6 | 0.4 | 0.25 | 5.29 |
| base:dc:declare_target_structure + kernel:guard | 33 | 11 | 0.333 | 0.25 | 4.41 |
| dir:do + kernel:guard | 15 | 5 | 0.333 | 0.25 | 4.41 |
| kernel:guard + map:to | 38 | 12 | 0.316 | 0.25 | 4.18 |
| dir:target parallel + kernel:guard | 32 | 10 | 0.312 | 0.25 | 4.14 |
| kernel:guard + map:mod:always | 16 | 5 | 0.312 | 0.25 | 4.14 |
| base:dc:declare_target_to + clause:proc_bind | 17 | 5 | 0.294 | 0.206 | 3.89 |

### cce21: ice

Single features: kernel:phase (38/38, lift 3.04); phase:do (33/33, lift 3.04); phase:single (24/24, lift 3.04); phase:do simd (19/19, lift 3.04); map:alloc (17/17, lift 3.04); phase:masked (16/16, lift 3.04); phase:nowait_barrier (15/15, lift 3.04); dir:target parallel (51/68, lift 2.28)

| feature pair | programs | ice | rate | best single rate | lift |
|---|---|---|---|---|---|
| clause:default:none + clause:lastprivate | 15 | 12 | 0.8 | 0.564 | 2.43 |
| clause:lastprivate + dir:parallel | 33 | 26 | 0.788 | 0.564 | 2.4 |
| chain:target teams distribute parallel do + clause:lastprivate | 18 | 14 | 0.778 | 0.564 | 2.36 |
| clause:num_threads + map:section | 18 | 14 | 0.778 | 0.483 | 2.36 |
| clause:lastprivate + dir:do | 29 | 22 | 0.759 | 0.564 | 2.31 |
| base:dt:map:implicit + map:mod:close | 16 | 12 | 0.75 | 0.489 | 2.28 |
| clause:lastprivate + map:mod:always | 16 | 12 | 0.75 | 0.564 | 2.28 |
| clause:lastprivate + map:section | 16 | 12 | 0.75 | 0.564 | 2.28 |

## Compile rejections (features not supported)

### afar

| programs | message |
|---|---|
| 46 | not_implemented: error: loc("<path> <path> not yet implemented: lastprivate clause in constructs other than simd/worksharing-loop/taskloop |
| 27 | link_undefined_symbol: ld.lld: error: undefined symbol: flang_rt_verbose_abort(char const*, ...) |
| 16 | not_implemented: loc("<path> error: not yet implemented: Unhandled clause order in omp.wsloop operation |
| 8 | not_implemented: loc("<path> error: not yet implemented: Unhandled clause order in omp.distribute operation |
| 8 | not_implemented: error: loc("<path> <path> not yet implemented: Firstprivate is currently unsupported defaultmap behaviour |
| 1 | not_implemented: error: loc("<path> <path> not yet implemented: lastprivate(conditional:) on do simd composite construct |
| 1 | not_implemented: error: loc("<path> <path> not yet implemented: lastprivate(conditional:) on simd construct |

Features most associated with rejection: base:dc:declare_reduction (39/39); red:clause:padd (39/39); clause:order (34/34); clause:lastprivate (58/72); chain:target teams distribute (28/49); chain:target teams distribute parallel do (33/59); clause:firstprivate (16/29); base:dt:target_update_component (17/31)

### cce19

| programs | message |
|---|---|
| 172 | diagnostic: ftn-1725 ftn: ERROR FUZZ_DMOD, \| Unexpected syntax while parsing the DIRECTIVE statement : "INDIRECT, LINK, TO or DEVICE_TYPE" was expected but found "E". |
| 21 | diagnostic: ftn-1370 ftn: ERROR , \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET. |
| 15 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : "scalar, aggregate, allocatable or pointer" was expected but found ")". |
| 7 | not_implemented: Unsupported OpenMP construct Calls -- $udr_i_1FUZZ_DMOD |
| 3 | diagnostic: ftn-1370 ftn: ERROR , \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET SIMD. |
| 3 | diagnostic: ftn-1370 ftn: ERROR , \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET PARALLEL. |
| 2 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 2 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP TARGET TEAMS DISTRIBUTE. |
| 1 | diagnostic: ftn-1310 ftn: ERROR , \| Object "I" is specified on the FIRSTPRIVATE clause. It must have a shared scope in the enclosing region. |
| 1 | not_implemented: Unsupported OpenMP construct Calls -- $udr_c_0FUZZ_DMOD |
| 1 | diagnostic: ftn-1964 ftn: ERROR , \| Variable "IB" must have its data mapping attribute explicitly declared because default map(none) was specified. |

Features most associated with rejection: base:dc:declare_target_enter (168/168); defaultmap:default:all (21/21); defaultmap:tofrom:all (18/18); base:dc:declare_reduction (38/39); red:clause:padd (38/39); clause:thread_limit (92/103); split:target | parallel | loop (25/28); red:clause:ieor (23/26)

### cce20

| programs | message |
|---|---|
| 172 | diagnostic: ftn-1725 ftn: ERROR FUZZ_DMOD, \| Unexpected syntax while parsing the DIRECTIVE statement : "INDIRECT, LINK, TO or DEVICE_TYPE" was expected but found "E". |
| 12 | not_implemented: Unsupported OpenMP construct Calls -- $udr_i_1FUZZ_DMOD |
| 4 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 2 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP TARGET TEAMS DISTRIBUTE. |
| 1 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP DISTRIBUTE. |
| 1 | diagnostic: ftn-1310 ftn: ERROR , \| Object "I" is specified on the FIRSTPRIVATE clause. It must have a shared scope in the enclosing region. |
| 1 | not_implemented: Unsupported OpenMP construct Calls -- $udr_c_0FUZZ_DMOD |

Features most associated with rejection: base:dc:declare_target_enter (168/168); base:dc:declare_reduction (37/39); red:clause:padd (37/39); clause:order (27/34); clause:nontemporal (15/19); clause:dist_schedule (43/55); chain:target teams distribute simd (46/60); clause:num_teams (40/52)

### cce21

| programs | message |
|---|---|
| 21 | not_implemented: Unsupported OpenMP construct Calls -- $udr_i_1FUZZ_DMOD |
| 16 | link_undefined_symbol: lld: error: undefined symbol: _cray$mt_taskwait |
| 12 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 10 | not_implemented: Unsupported OpenMP construct Calls -- $udr_c_0FUZZ_DMOD |
| 6 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP DISTRIBUTE. |
| 3 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP TEAMS DISTRIBUTE. |
| 2 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP TARGET TEAMS DISTRIBUTE. |
| 2 | diagnostic: ftn-1310 ftn: ERROR , \| Object "I" is specified on the FIRSTPRIVATE clause. It must have a shared scope in the enclosing region. |

Features most associated with rejection: base:dc:declare_reduction (32/39); red:clause:padd (32/39); red:in_reduction:+ (11/16); clause:in_reduction (25/38); dir:taskgroup (25/38); kernel:inred (25/38); red:in_reduction:* (16/25); dir:parallel do (21/38)

## Generator rejects

Programs failing a legality check are never run. Causes (`rules`: a 5.2 rule of offload.engine.rules fired, a generator or rule bug; `flang`: AFAR flang's frontend refused a program the rules and gfortran accept; see the report for which of these are flang's errors):

| count | cause | seeds |
|---|---|---|

## Flaky results

- seed 209 afar: wrong_code: checksum=27423373 ran_on_host=0 expected=316801210 | wrong_code: checksum=241716955 ran_on_host=0 expected=316801210 | wrong_code: checksum=101358633 ran_on_host=0 expected=316801210 | wrong_code: checksum=1898795605 ran_on_host=0 expected=316801210
- seed 210 cce20: wrong_code: checksum=1286882937 ran_on_host=0 expected=1565548699 | wrong_code: checksum=527440643 ran_on_host=0 expected=1565548699 | wrong_code: checksum=2025399268 ran_on_host=0 expected=1565548699 | wrong_code: checksum=746902946 ran_on_host=0 expected=1565548699
- seed 210 cce21: wrong_code: checksum=639815532 ran_on_host=0 expected=1565548699 | wrong_code: checksum=488790870 ran_on_host=0 expected=1565548699 | wrong_code: checksum=812138434 ran_on_host=0 expected=1565548699 | wrong_code: checksum=2025399268 ran_on_host=0 expected=1565548699
- seed 227 cce21: wrong_code: checksum=2034960345 ran_on_host=0 expected=2109057738 | wrong_code: checksum=1622621454 ran_on_host=0 expected=2109057738 | wrong_code: checksum=981958355 ran_on_host=0 expected=2109057738 | wrong_code: checksum=1809466013 ran_on_host=0 expected=2109057738
- seed 253 cce19: wrong_code: checksum=1692818264 ran_on_host=0 expected=466632313 | wrong_code: checksum=1460311870 ran_on_host=0 expected=466632313 | wrong_code: checksum=977727372 ran_on_host=0 expected=466632313 | wrong_code: checksum=1109341326 ran_on_host=0 expected=466632313
- seed 253 cce20: wrong_code: checksum=1212444719 ran_on_host=0 expected=466632313 | wrong_code: checksum=947005858 ran_on_host=0 expected=466632313 | wrong_code: checksum=1197083962 ran_on_host=0 expected=466632313 | wrong_code: checksum=596035314 ran_on_host=0 expected=466632313
- seed 253 cce21: wrong_code: checksum=260425527 ran_on_host=0 expected=466632313 | wrong_code: checksum=332807406 ran_on_host=0 expected=466632313 | wrong_code: checksum=1721328825 ran_on_host=0 expected=466632313 | wrong_code: checksum=1297976402 ran_on_host=0 expected=466632313

## Appendix: host reference checks (not offload findings)

Device offload only: host runs (OMP_TARGET_OFFLOAD=disabled) and the sequential elision are references for the expected value, never measurements of a toolchain. A host_path_failure below is recorded data (results/fuzz/<run>/summary.json), not an offload finding, and it counts nowhere in the tables above.

The reference host run (OMP_TARGET_OFFLOAD=disabled, the first toolchain that compiled) failed for 1 programs (host_ref_failed) and printed another checksum than the model for 5 (host_mismatch). For each, every toolchain whose build compiled ran it on the host (rebuilt and run twice: results/fuzz/b4/hostcheck.jsonl), and the sequential elision (offload.engine.expected) ran where it applies. Rule: **valid** when at least one of them prints the model's checksum; the host builds that ran and did not are `host_path_failure` records (a host-path compiler or runtime bug: out of scope, not an offload finding). **noncompliant** when none does (a generator or model defect): excluded from the findings and the tallies above. A toolchain whose build does not compile has no host build ('no host build'). Values are host checksums. Scope: only these programs had every toolchain's host build run; for the others only the reference toolchain's host run exists, so host_path_failure counts are a lower bound.

| seed | reference | ref tc | model | afar host | cce19 host | cce20 host | cce21 host | elision | validity | host_path_failure |
|---|---|---|---|---|---|---|---|---|---|---|
| 73 | host_ref_failed | cce21 | 1553767691 | no build: compile_reject | no build: compile_reject | no build: compile_reject | exit_status: 1 | inapplicable: declare target variable; module variables (dec | noncompliant | - |
| 142 | host_mismatch | cce19 | 1351675492 | no build: compile_reject | 1829318839 | **1351675492** | 1453692640 | inapplicable: declare target variable; module variables (dec | valid | cce19, cce21 |
| 151 | host_mismatch | cce21 | 461652837 | no build: compile_reject | no build: compile_reject | no build: compile_reject | 1735219459 | inapplicable: declare target variable; module variables (dec | noncompliant | - |
| 224 | host_mismatch | afar | 1369493473 | 191642379 | no build: compile_reject | no build: compile_reject | **1369493473** | inapplicable: declare target variable; module variables (dec | valid | afar |
| 261 | host_mismatch | cce21 | 270150296 | no build: compile_reject | no build: compile_reject | no build: compile_reject | 1105002011 | inapplicable: declare mapper; declare target variable; modul | noncompliant | - |
| 287 | host_mismatch | afar | 1996319419 | 1432867068 | no build: compile_reject | no build: compile_reject | **1996319419** | inapplicable: declare mapper; declare target variable; modul | valid | afar |

### host_path_failure (valid programs; host-path failures, out of scope)

- afar: 2 programs (seeds 224, 287)
- cce19: 1 programs (seeds 142)
- cce21: 1 programs (seeds 142)

### Noncompliant programs (generator/model investigation)

No available host build prints the model's checksum. Their device classes (not counted anywhere above):

- seed 73: model 1553767691; host afar no host build: compile_reject, cce19 no host build: compile_reject, cce20 no host build: compile_reject, cce21 exit_status: 1; elision inapplicable: declare target variable; module variables (declare target visibility); device afar compile_reject, cce19 compile_reject, cce20 compile_reject, cce21 agree
- seed 151: model 461652837; host afar no host build: compile_reject, cce19 no host build: compile_reject, cce20 no host build: compile_reject, cce21 1735219459; elision inapplicable: declare target variable; module variables (declare target visibility); user-defined reduction; device afar compile_reject, cce19 compile_reject, cce20 compile_reject, cce21 wrong_code
- seed 261: model 270150296; host afar no host build: compile_reject, cce19 no host build: compile_reject, cce20 no host build: compile_reject, cce21 1105002011; elision inapplicable: declare mapper; declare target variable; module variables (declare target visibility); user-defined reduction; device afar compile_reject, cce19 compile_reject, cce20 compile_reject, cce21 agree
