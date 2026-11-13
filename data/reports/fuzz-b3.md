# Fuzz campaign `b3`

Csmith-style random OpenMP 5.2 Fortran offload programs (offload.engine.fuzz, generator `fuzz-3`, base-language groups: alloc (offload.engine.fuzz_base)), run on every toolchain at -O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory; reference: the Python model of each program, checked against a host run (OMP_TARGET_OFFLOAD=disabled, a reference only; see the appendix 'Host reference checks' for the programs whose host run failed or disagreed). Machine-readable: results/fuzz/b3/summary.json.

## Size and timing

- programs generated: 300; legal and run: 300 (judged: 300; noncompliant, excluded from every count below: 0); generator rejects: 0; worker crashes: 0
- campaign wall time: 1995 s with 4 workers (541 programs/hour; 37.1 s per program and worker, all toolchains and repeats included)
- programs whose device results agree with the model on every toolchain: 70

## Classes per toolchain

Rejections (compile_reject) are features a toolchain does not support, not failures. Flaky = the repeats differed (counted in the worst class).

| class | afar | cce19 | cce20 | cce21 |
|---|---|---|---|---|
| agree | 177 | 110 | 149 | 124 |
| compile_reject | 89 | 123 | 41 | 54 |
| ice | 3 | 51 | 84 | 84 |
| wrong_code | 5 | 14 (2 flaky) | 24 (1 flaky) | 17 (2 flaky) |
| host_fallback | 0 | 0 | 0 | 0 |
| timeout | 0 | 0 | 0 | 0 |
| run_error | 26 | 2 | 2 | 21 |
| harness_error | 0 | 0 | 0 | 0 |

## Base-language features

Per base-language feature (offload.engine.fuzz_base): the programs that have it, and per toolchain agree / compile_reject / ice / wrong_code / run_error (other classes in parentheses when present).

| feature | programs | afar | cce19 | cce20 | cce21 |
|---|---|---|---|---|---|
| al:allocatable_component | 185 | 102/57/2/3/21 | 73/76/27/8/1 | 94/26/47/17/1 | 77/34/47/11/16 |
| al:allocatable_scalar | 199 | 112/62/1/3/21 | 70/86/33/9/1 | 100/31/52/15/1 | 85/38/52/11/13 |
| al:depend_section | 33 | 13/13/0/0/7 | 10/16/7/0/0 | 13/6/13/1/0 | 13/6/13/1/0 |
| al:dummy:allocatable | 35 | 14/16/3/0/2 | 9/16/9/1/0 | 12/5/14/4/0 | 6/6/14/0/9 |
| al:dummy:assumed_shape | 103 | 57/36/3/1/6 | 25/45/23/9/1 | 41/15/31/15/1 | 27/25/31/4/16 |
| al:dummy:explicit | 64 | 36/16/2/0/10 | 17/28/12/7/0 | 29/8/16/11/0 | 19/15/16/3/11 |
| al:dummy:intent_in | 85 | 47/26/2/1/9 | 25/35/15/9/1 | 40/12/19/13/1 | 26/19/19/4/17 |
| al:dummy:intent_inout | 114 | 63/36/3/1/11 | 29/50/24/10/1 | 48/16/33/16/1 | 31/26/33/5/19 |
| al:dummy:intent_out | 13 | 10/1/0/0/2 | 4/6/2/1/0 | 7/2/3/1/0 | 7/2/3/0/1 |
| al:dummy:optional | 23 | 14/8/1/0/0 | 7/7/6/3/0 | 9/1/10/3/0 | 4/3/10/1/5 |
| al:dummy:pointer | 13 | 7/4/1/0/1 | 5/5/2/1/0 | 7/1/2/3/0 | 4/2/2/1/4 |
| al:dummy:value | 15 | 7/5/0/1/2 | 5/6/2/2/0 | 7/3/3/2/0 | 1/6/3/0/5 |
| al:kernel_in_internal_procedure | 117 | 65/36/3/1/12 | 31/51/24/10/1 | 50/16/33/17/1 | 32/26/33/6/20 |
| al:optional_absent_in_map | 36 | 12/13/2/0/9 | 11/17/4/4/0 | 18/4/9/5/0 | 1/6/9/0/20 |
| al:pointer_component | 182 | 108/50/2/4/18 | 61/77/34/9/1 | 86/28/50/17/1 | 73/34/50/11/14 |
| al:pointer_output:alloc | 66 | 31/27/1/1/6 | 20/33/10/3/0 | 30/12/16/8/0 | 24/15/16/5/6 |
| al:pointer_output:target | 66 | 28/27/3/3/5 | 24/26/11/3/2 | 33/8/18/5/2 | 25/12/18/3/8 |
| al:strided_update | 18 | 10/7/0/0/1 | 0/18/0/0/0 | 0/18/0/0/0 | 0/18/0/0/0 |
| al:structure_dummy | 79 | 40/28/2/1/8 | 22/32/18/7/0 | 32/11/23/13/0 | 18/18/23/4/16 |
| al:target_attribute | 169 | 103/47/1/2/16 | 56/68/34/9/2 | 80/21/53/13/2 | 60/27/53/12/17 |
| dt:component:struct:integer | 253 | 144/76/2/5/26 | 92/106/43/11/1 | 123/39/69/21/1 | 102/49/69/13/20 |
| dt:map:components | 175 | 90/61/2/5/17 | 56/77/32/9/1 | 74/32/50/18/1 | 60/38/50/10/17 |
| dt:map:implicit | 68 | 30/28/1/0/9 | 21/31/12/4/0 | 28/14/21/5/0 | 23/18/21/2/4 |
| dt:map:mod:always | 12 | 7/5/0/0/0 | 4/5/2/1/0 | 5/1/3/3/0 | 5/1/3/1/2 |
| dt:map:mod:close | 11 | 4/5/1/1/0 | 6/3/1/1/0 | 6/1/3/1/0 | 5/1/3/1/1 |
| dt:map:mod:present | 9 | 3/3/0/2/1 | 2/6/1/0/0 | 3/3/3/0/0 | 2/3/3/0/1 |
| dt:map:whole | 73 | 30/28/1/4/10 | 23/34/14/2/0 | 26/17/24/6/0 | 19/21/24/2/7 |
| dt:struct | 253 | 144/76/2/5/26 | 92/106/43/11/1 | 123/39/69/21/1 | 102/49/69/13/20 |
| dt:target_update_component | 30 | 15/13/0/1/1 | 6/18/5/1/0 | 8/14/6/2/0 | 6/15/6/0/3 |

## Known findings rediscovered

- cce19-target-parallel-guarded-loop (wrong code on cce19 in a program with a thread-0-guarded sequential loop in target parallel): 6 programs (seeds 16, 25, 44, 99, 106, 134)
- cce21-defaultmap-aggregate-flag (wrong code or host fallback on cce21 where cce20 agrees, in a program with a defaultmap clause; the finding's symptom: a map(tofrom) scalar is not copied back): 4 programs (seeds 27, 28, 152, 233)
- (control for the line above: the same without a defaultmap clause): 0 programs (seeds )
- cce21-in-reduction-taskwait-link (cce21 link failure on _cray$mt_taskwait): 13 programs (seeds 21, 25, 61, 69, 127, 178, 197, 198, 202, 245, 254, 285)
- cce19-target-parallel-single-ice / task ICE (CCE 'unhandled construct type'): 59 programs (seeds 2, 15, 17, 32, 40, 42, 47, 48, 51, 52, 54, 59)

## Distinct minimized failures

| file | toolchain | kind | also fails on | lines | expected | observed |
|---|---|---|---|---|---|---|
| `data/findings/fuzz/b3-9-afar.f90` | afar | ice | - | 125 -> 85 | compiles | internal compiler error: ice: error: verification of lowering to FIR failed |
| `data/findings/fuzz/b3-278-cce19.f90` | cce19 | run_error | - | 84 -> 41 | runs to completion (the host run does) | device: fail crash: SIGABRT; host reference (afar) checksum=144 |
| `data/findings/fuzz/b3-197-cce19.f90` | cce19 | run_error | cce20 | 141 -> 64 | runs to completion (the host run does) | device: fail crash: SIGABRT; host reference (afar) checksum=1030200169 |
| `data/findings/fuzz/b3-188-cce19.f90` | cce19 | ice | cce20, cce21 | 83 -> 62 | compiles | internal compiler error: ice: INTERNAL COMPILER ERROR:  "Unexpected schedule" (/workspace/crayftn/pdgcs/v_mt_translate.c, line 4112, version cc4d36e4ff3377d45f0 |
| `data/findings/fuzz/b3-190-cce21.f90` | cce21 | run_error | - | 127 -> 73 | runs to completion (the host run does) | device: fail crash: SIGSEGV; host reference (afar) checksum=0 |
| `data/findings/fuzz/b3-61-cce20.f90` | cce20 | wrong_code | cce19, cce21 | 168 -> 75 | the host reference checksum (host reference (elision) checksum=234479309) | device checksum=1451519883 ran_on_host=0 |
| `data/findings/fuzz/b3-250-cce20.f90` | cce20 | wrong_code | cce19, cce21 | 153 -> 76 | the host reference checksum (host reference (elision) checksum=1218074569) | device checksum=1312631914 ran_on_host=0 |
| `data/findings/fuzz/b3-9-cce21.f90` | cce21 | run_error | afar | 125 -> 90 | runs to completion (the host run does) | device: fail crash: SIGSEGV; host reference (elision) checksum=185626446 |
| `data/findings/fuzz/b3-45-cce21.f90` | cce21 | run_error | afar | 138 -> 70 | runs to completion (the host run does) | device: fail crash: SIGSEGV; host reference (elision) checksum=0 |
| `data/findings/fuzz/b3-54-afar.f90` | afar | run_error | - | 117 -> 41 | runs to completion (the host run does) | device: fail crash: SIGSEGV; host reference (elision) checksum=0 |
| `data/findings/fuzz/b3-94-afar.f90` | afar | wrong_code | - | 176 -> 67 | the host reference checksum (host reference (elision) checksum=2012829416) | device checksum=0 ran_on_host=0 |

Not minimized:

- seed 92 cce20 wrong_code: withdrawn minimizer defect: deleted the explicit map of the pointer component dr%pc (implicit map leaves its association undefined, 5.2 §5.8.3); the reduced program was not legal. Fixed in fuzz_min (pointer-component maps are kept)
- seed 11 cce20 wrong_code: not_reproduced no reference outside the failing compiler family (another family's host run, or sequential elision) matches the model
- seed 271 cce19 wrong_code: not_reproduced the failure does not reproduce: device timeout None host=None ref 569481647

## Wrong code (all programs)

- afar: 5 programs (seeds 94, 121, 150, 206, 226)
- cce19: 14 programs (seeds 14, 16, 25, 44, 69, 92, 99, 106, 127, 134, 191, 209, 245, 271)
- cce20: 24 programs (seeds 11, 14, 16, 21, 25, 44, 61, 69, 92, 97, 99, 106, 127, 134, 157, 191, 198, 202, 209, 210)
- cce21: 17 programs (seeds 11, 14, 16, 27, 28, 44, 99, 106, 134, 152, 157, 191, 209, 210, 233, 275, 283)

## Internal compiler errors (deduplicated by message)

| toolchain | programs | message | seeds |
|---|---|---|---|
| cce19 | 37 | ice: INTERNAL COMPILER ERROR: "unhandled construct type" (v_openmp.c, line 7617, version <v>) | 2, 15, 17, 32, 42 |
| cce20 | 33 | ice: INTERNAL COMPILER ERROR: "unhandled acc construct type" (v_openmp.c, line 7881, version <v>) | 42, 47, 52, 59, 62 |
| cce21 | 33 | ice: INTERNAL COMPILER ERROR: "unhandled acc construct type" (v_openmp.c, line 8265, version <v>) | 42, 47, 52, 59, 62 |
| cce20 | 25 | ice: INTERNAL COMPILER ERROR: "unhandled construct type" (v_openmp.c, line 7814, version <v>) | 2, 15, 17, 32, 40 |
| cce21 | 25 | ice: INTERNAL COMPILER ERROR: "unhandled construct type" (v_openmp.c, line 8197, version <v>) | 2, 15, 17, 32, 40 |
| cce20 | 23 | ice: INTERNAL COMPILER ERROR: "ACC - barrier/reset/protected last private not supported" (v_mt_translate.c, line 5607, version <v>) | 6, 22, 26, 31, 43 |
| cce21 | 23 | ice: INTERNAL COMPILER ERROR: "ACC - barrier/reset/protected last private not supported" (v_mt_translate.c, line 5798, version <v>) | 6, 22, 26, 31, 43 |
| cce19 | 11 | ice: INTERNAL COMPILER ERROR: "ACC - barrier/reset/protected last private not supported" (v_mt_translate.c, line 4874, version <v>) | 6, 26, 31, 114, 158 |
| afar | 2 | afar FIR verification: 'omp.simd' op operand #0 must be variadic of OpenMP-compatible variable type, but got '!fir.box<!fir.array<?x?xi32>>' | 9, 60 |
| afar | 1 | afar FIR verification: 'omp.simd' op operand #0 must be variadic of OpenMP-compatible variable type, but got '!fir.box<!fir.array<?xi32>>' | 18 |
| cce19 | 1 | ice: INTERNAL COMPILER ERROR: "Unexpected schedule" (v_mt_translate.c, line 4112, version <v>) | 188 |
| cce19 | 1 | ice: INTERNAL COMPILER ERROR: "Unhandled contexts must be fixed!!! | 18 |
| cce19 | 1 | ice: INTERNAL COMPILER ERROR: "unhandled operator | 165 |
| cce20 | 1 | ice: INTERNAL COMPILER ERROR: "Unexpected schedule" (v_mt_translate.c, line 4838, version <v>) | 188 |
| cce20 | 1 | ice: INTERNAL COMPILER ERROR: "Unhandled contexts must be fixed!!! | 18 |
| cce20 | 1 | ice: INTERNAL COMPILER ERROR: "unhandled operator | 165 |
| cce21 | 1 | ice: INTERNAL COMPILER ERROR: "Unexpected schedule" (v_mt_translate.c, line 5029, version <v>) | 188 |
| cce21 | 1 | ice: INTERNAL COMPILER ERROR: "Unhandled contexts must be fixed!!! | 18 |
| cce21 | 1 | ice: INTERNAL COMPILER ERROR: "unhandled operator | 165 |

## Run errors, timeouts, host fallbacks

| toolchain | class | programs | reason | seeds |
|---|---|---|---|---|
| cce21 | run_error | 20 | crash: SIGSEGV; without mandatory: crash: SIGSEGV | 9, 35, 45, 92, 97 |
| afar | run_error | 14 | crash: SIGABRT; without mandatory: crash: SIGABRT | 30, 35, 92, 126, 142 |
| afar | run_error | 12 | crash: SIGSEGV; without mandatory: crash: SIGSEGV | 38, 54, 62, 90, 99 |
| cce19 | run_error | 2 | crash: SIGABRT; without mandatory: crash: SIGABRT | 197, 278 |
| cce20 | run_error | 2 | crash: SIGABRT; without mandatory: crash: SIGABRT | 197, 278 |
| cce21 | run_error | 1 | exit_status: 1; without mandatory: exit_status: 1 | 278 |

## Features and feature pairs most associated with failures

Among programs the toolchain compiled (or crashed on). Lift = the rate of the class among programs with the feature (pair) over the toolchain's overall rate; a pair is listed only when it beats both of its features alone by 25%.

### afar: wrong_code

Single features: split:target | parallel | do (3/16, lift 7.91); clause:default:none (4/30, lift 5.63); chain:target parallel do (3/29, lift 4.37); chain:target teams distribute parallel do (3/29, lift 4.37); clause:num_threads (5/49, lift 4.31); base:dt:map:whole (4/45, lift 3.75); clause:schedule (4/46, lift 3.67); dir:do (5/61, lift 3.46)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| base:dt:map:whole + clause:schedule | 15 | 4 | 0.267 | 0.089 | 11.25 |
| clause:num_threads + scalar:implicit | 15 | 4 | 0.267 | 0.102 | 11.25 |
| clause:num_threads + dir:do | 20 | 5 | 0.25 | 0.102 | 10.55 |
| base:dt:map:whole + clause:num_threads | 17 | 4 | 0.235 | 0.102 | 9.93 |
| clause:default:none + dir:do | 17 | 4 | 0.235 | 0.133 | 9.93 |
| base:dt:map:whole + dir:do | 18 | 4 | 0.222 | 0.089 | 9.38 |
| body:call_declare_target + dir:do | 18 | 4 | 0.222 | 0.082 | 9.38 |
| base:dt:map:whole + body:call_declare_target | 15 | 3 | 0.2 | 0.089 | 8.44 |

### afar: ice

Single features: clause:nontemporal (3/15, lift 14.07); base:al:dummy:allocatable (3/19, lift 11.11); clause:num_teams (3/34, lift 6.21); base:al:pointer_output:target (3/39, lift 5.41); clause:schedule (3/46, lift 4.59); map:mod:always (3/66, lift 3.2); base:al:dummy:assumed_shape (3/67, lift 3.15); base:al:dummy:intent_inout (3/78, lift 2.71)

| feature pair | programs | ice | rate | best single rate | lift |
|---|---|---|---|---|---|
| base:al:dummy:allocatable + decl:allocatable_rank2 | 15 | 3 | 0.2 | 0.158 | 14.07 |
| base:al:pointer_output:target + clause:schedule | 15 | 3 | 0.2 | 0.077 | 14.07 |
| clause:num_teams + map:mod:always | 15 | 3 | 0.2 | 0.088 | 14.07 |
| base:al:dummy:assumed_shape + clause:num_teams | 17 | 3 | 0.176 | 0.088 | 12.41 |
| base:al:dummy:intent_inout + clause:schedule | 17 | 3 | 0.176 | 0.065 | 12.41 |
| base:al:kernel_in_internal_procedure + clause:schedule | 17 | 3 | 0.176 | 0.065 | 12.41 |
| base:al:pointer_output:target + map:mod:always | 18 | 3 | 0.167 | 0.077 | 11.72 |
| base:al:dummy:intent_inout + clause:num_teams | 19 | 3 | 0.158 | 0.088 | 11.11 |

### afar: run_error

Single features: split:target | teams | distribute | parallel | do simd (7/17, lift 3.34); base:al:optional_absent_in_map (9/23, lift 3.18); base:al:depend_section (7/20, lift 2.84); tasking:nowait_depend (12/35, lift 2.78); red:clause:ior (7/21, lift 2.71); dir:do simd (7/23, lift 2.47); red:clause:iand (5/17, lift 2.39); red:clause:ieor (5/18, lift 2.25)

| feature pair | programs | run_error | rate | best single rate | lift |
|---|---|---|---|---|---|
| base:al:allocatable_component + tasking:nowait_depend | 21 | 12 | 0.571 | 0.343 | 4.64 |
| map:from + tasking:nowait_depend | 20 | 10 | 0.5 | 0.343 | 4.06 |
| base:al:allocatable_scalar + base:al:optional_absent_in_map | 16 | 8 | 0.5 | 0.391 | 4.06 |
| decl:explicit_rank2 + dir:do simd | 15 | 7 | 0.467 | 0.304 | 3.79 |
| dir:do simd + loop:down | 15 | 7 | 0.467 | 0.304 | 3.79 |
| map:mod:close + tasking:nowait_depend | 15 | 7 | 0.467 | 0.343 | 3.79 |
| base:dt:map:implicit + dir:parallel | 17 | 7 | 0.412 | 0.225 | 3.34 |
| base:dt:map:implicit + red:clause | 20 | 8 | 0.4 | 0.225 | 3.25 |

### cce19: wrong_code

Single features: kernel:guard (8/32, lift 3.16); scalar:to (6/25, lift 3.03); base:al:optional_absent_in_map (4/19, lift 2.66); red:clause:min (3/15, lift 2.53); base:al:dummy:explicit (7/36, lift 2.46); dir:parallel do (4/21, lift 2.41); base:al:dummy:optional (3/16, lift 2.37); base:al:dummy:intent_in (9/50, lift 2.28)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| base:al:target_attribute + kernel:guard | 21 | 7 | 0.333 | 0.25 | 4.21 |
| base:al:dummy:intent_inout + body:inner_seq_loop | 15 | 5 | 0.333 | 0.158 | 4.21 |
| base:al:dummy:intent_inout + kernel:guard | 15 | 5 | 0.333 | 0.25 | 4.21 |
| base:al:kernel_in_internal_procedure + body:inner_seq_loop | 15 | 5 | 0.333 | 0.158 | 4.21 |
| base:al:dummy:intent_inout + map:mod:always | 19 | 6 | 0.316 | 0.156 | 3.99 |
| base:al:kernel_in_internal_procedure + map:mod:always | 19 | 6 | 0.316 | 0.152 | 3.99 |
| base:al:kernel_in_internal_procedure + kernel:guard | 16 | 5 | 0.312 | 0.25 | 3.95 |
| base:al:dummy:assumed_shape + map:mod:always | 17 | 5 | 0.294 | 0.155 | 3.72 |

### cce19: ice

Single features: kernel:phase (27/27, lift 3.47); phase:do (24/24, lift 3.47); phase:nowait_barrier (16/16, lift 3.47); phase:single (16/16, lift 3.47); dir:target parallel (30/45, lift 2.31); split:target | teams | distribute | parallel | do (10/20, lift 1.74); wrap:host_update_to (8/16, lift 1.74); clause:lastprivate (19/40, lift 1.65)

| feature pair | programs | ice | rate | best single rate | lift |
|---|---|---|---|---|---|
| clause:num_threads + dir:target parallel | 19 | 16 | 0.842 | 0.667 | 2.92 |
| clause:lastprivate + dir:do | 17 | 11 | 0.647 | 0.475 | 2.25 |
| clause:lastprivate + dir:parallel | 22 | 14 | 0.636 | 0.475 | 2.21 |
| clause:lastprivate + loop:down | 24 | 15 | 0.625 | 0.475 | 2.17 |
| base:al:dummy:assumed_shape + body:call_declare_target | 18 | 11 | 0.611 | 0.42 | 2.12 |
| base:al:dummy:intent_inout + body:call_declare_target | 18 | 11 | 0.611 | 0.42 | 2.12 |
| base:al:target_attribute + clause:if:target | 18 | 11 | 0.611 | 0.429 | 2.12 |
| base:al:structure_dummy + body:call_declare_target | 17 | 10 | 0.588 | 0.42 | 2.04 |

### cce20: wrong_code

Single features: clause:in_reduction (12/27, lift 4.8); dir:taskgroup (12/27, lift 4.8); kernel:inred (12/27, lift 4.8); red:in_reduction:* (6/15, lift 4.32); kernel:guard (12/50, lift 2.59); red:atomic (5/21, lift 2.57); body:inner_seq_loop (15/66, lift 2.45); red:clause:min (5/24, lift 2.25)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| base:al:dummy:assumed_shape + clause:in_reduction | 19 | 12 | 0.632 | 0.444 | 6.82 |
| base:al:dummy:assumed_shape + dir:taskgroup | 19 | 12 | 0.632 | 0.444 | 6.82 |
| base:al:dummy:assumed_shape + kernel:inred | 19 | 12 | 0.632 | 0.444 | 6.82 |
| base:al:dummy:intent_inout + clause:in_reduction | 19 | 12 | 0.632 | 0.444 | 6.82 |
| base:al:dummy:intent_inout + dir:taskgroup | 19 | 12 | 0.632 | 0.444 | 6.82 |
| base:al:dummy:intent_inout + kernel:inred | 19 | 12 | 0.632 | 0.444 | 6.82 |
| base:al:kernel_in_internal_procedure + clause:in_reduction | 19 | 12 | 0.632 | 0.444 | 6.82 |
| base:al:kernel_in_internal_procedure + dir:taskgroup | 19 | 12 | 0.632 | 0.444 | 6.82 |

### cce20: ice

Single features: kernel:phase (40/40, lift 3.08); phase:do (37/37, lift 3.08); phase:single (25/25, lift 3.08); phase:do simd (23/23, lift 3.08); phase:nowait_barrier (22/22, lift 3.08); phase:masked (19/19, lift 3.08); dir:target parallel (49/74, lift 2.04); split:target | teams | distribute | parallel | do (15/28, lift 1.65)

| feature pair | programs | ice | rate | best single rate | lift |
|---|---|---|---|---|---|
| clause:dist_schedule + clause:lastprivate | 15 | 13 | 0.867 | 0.508 | 2.67 |
| base:dt:map:whole + dir:target parallel | 18 | 15 | 0.833 | 0.662 | 2.57 |
| chain:target teams distribute parallel do + clause:lastprivate | 19 | 15 | 0.789 | 0.508 | 2.43 |
| clause:lastprivate + dir:do | 30 | 22 | 0.733 | 0.508 | 2.26 |
| clause:lastprivate + dir:parallel | 38 | 27 | 0.711 | 0.508 | 2.19 |
| clause:num_threads + map:section | 15 | 10 | 0.667 | 0.466 | 2.06 |
| map:section + scalar:tofrom | 15 | 10 | 0.667 | 0.469 | 2.06 |
| chain:target parallel do + clause:num_threads | 17 | 11 | 0.647 | 0.466 | 2.0 |

### cce21: wrong_code

Single features: red:atomic (4/18, lift 3.22); kernel:guard (10/46, lift 3.15); scalar:to (6/32, lift 2.71); body:inner_seq_loop (11/60, lift 2.65); chain:target teams distribute (3/19, lift 2.28); clause:num_teams (5/36, lift 2.01); clause:if:parallel (4/34, lift 1.7); clause:proc_bind (3/26, lift 1.67)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| body:inner_seq_loop + scalar:to | 16 | 6 | 0.375 | 0.188 | 5.43 |
| body:inner_seq_loop + kernel:guard | 19 | 7 | 0.368 | 0.217 | 5.33 |
| base:al:pointer_component + kernel:guard | 28 | 9 | 0.321 | 0.217 | 4.65 |
| body:call_declare_target + body:inner_seq_loop | 16 | 5 | 0.312 | 0.183 | 4.52 |
| base:al:target_attribute + kernel:guard | 27 | 8 | 0.296 | 0.217 | 4.29 |
| base:al:allocatable_component + scalar:to | 18 | 5 | 0.278 | 0.188 | 4.02 |
| body:inner_seq_loop + clause:thread_limit | 22 | 6 | 0.273 | 0.183 | 3.95 |
| body:inner_seq_loop + dir:target parallel | 22 | 6 | 0.273 | 0.183 | 3.95 |

### cce21: ice

Single features: kernel:phase (40/40, lift 2.93); phase:do (37/37, lift 2.93); phase:single (25/25, lift 2.93); phase:do simd (23/23, lift 2.93); phase:nowait_barrier (22/22, lift 2.93); phase:masked (19/19, lift 2.93); dir:target parallel (49/72, lift 1.99); red:atomic (10/18, lift 1.63)

| feature pair | programs | ice | rate | best single rate | lift |
|---|---|---|---|---|---|
| clause:dist_schedule + clause:lastprivate | 15 | 13 | 0.867 | 0.516 | 2.54 |
| chain:target teams distribute parallel do + clause:lastprivate | 18 | 15 | 0.833 | 0.516 | 2.44 |
| clause:lastprivate + dir:do | 30 | 22 | 0.733 | 0.516 | 2.15 |
| clause:lastprivate + dir:parallel | 38 | 27 | 0.711 | 0.516 | 2.08 |
| chain:target parallel do + clause:num_threads | 16 | 11 | 0.688 | 0.482 | 2.01 |
| clause:lastprivate + map:section | 24 | 16 | 0.667 | 0.516 | 1.95 |
| clause:num_threads + map:section | 15 | 10 | 0.667 | 0.482 | 1.95 |
| map:section + scalar:tofrom | 15 | 10 | 0.667 | 0.469 | 1.95 |

### cce21: run_error

Single features: base:al:optional_absent_in_map (20/30, lift 7.81); base:al:dummy:allocatable (9/29, lift 3.64); base:al:structure_dummy (16/61, lift 3.07); base:al:dummy:intent_in (17/66, lift 3.02); base:al:dummy:optional (5/20, lift 2.93); base:al:dummy:explicit (11/49, lift 2.63); base:al:kernel_in_internal_procedure (20/91, lift 2.57); base:al:dummy:intent_inout (19/88, lift 2.53)

| feature pair | programs | run_error | rate | best single rate | lift |
|---|---|---|---|---|---|
| base:al:dummy:intent_in + chain:target parallel loop | 15 | 7 | 0.467 | 0.258 | 5.47 |
| base:al:dummy:intent_inout + base:al:pointer_output:target | 15 | 7 | 0.467 | 0.216 | 5.47 |
| base:al:kernel_in_internal_procedure + base:al:pointer_output:target | 15 | 7 | 0.467 | 0.22 | 5.47 |
| base:al:dummy:allocatable + base:dt:map:components | 20 | 9 | 0.45 | 0.31 | 5.27 |
| base:al:structure_dummy + body:temp | 20 | 9 | 0.45 | 0.262 | 5.27 |
| base:al:dummy:assumed_shape + chain:target parallel loop | 18 | 8 | 0.444 | 0.205 | 5.21 |
| base:al:dummy:intent_inout + chain:target parallel loop | 18 | 8 | 0.444 | 0.216 | 5.21 |
| base:al:dummy:intent_inout + clause:shared | 18 | 8 | 0.444 | 0.216 | 5.21 |

## Compile rejections (features not supported)

### afar

| programs | message |
|---|---|
| 52 | not_implemented: error: loc("<path> <path> not yet implemented: lastprivate clause in constructs other than simd/worksharing-loop/taskloop |
| 17 | not_implemented: loc("<path> error: not yet implemented: Unhandled clause order in omp.wsloop operation |
| 9 | not_implemented: loc("<path> error: not yet implemented: Unhandled clause order in omp.distribute operation |
| 7 | not_implemented: error: loc("<path> <path> not yet implemented: Firstprivate is currently unsupported defaultmap behaviour |
| 3 | not_implemented: error: loc("<path> <path> not yet implemented: lastprivate(conditional:) on simd construct |
| 1 | not_implemented: error: loc("<path> <path> not yet implemented: lastprivate(conditional:) on do simd composite construct |

Features most associated with rejection: clause:order (32/32); clause:lastprivate (57/75); split:target | teams | distribute | simd (19/34); clause:schedule:runtime (13/24); red:atomic (15/28); chain:target teams distribute parallel do (31/60); split:target | parallel | do (17/33); chain:target teams distribute (20/39)

### cce19

| programs | message |
|---|---|
| 28 | diagnostic: ftn-1370 ftn: ERROR , \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET. |
| 25 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : "scalar, aggregate, allocatable or pointer" was expected but found ")". |
| 11 | diagnostic: ftn-1747 ftn: ERROR , \| The stride specified for array "DR" must not be greater than 1. Subarray references in the MAP clause must be to contiguous memory. |
| 11 | diagnostic: ftn-1370 ftn: ERROR , \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET PARALLEL. |
| 8 | diagnostic: ftn-1370 ftn: ERROR KP1, \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET. |
| 5 | diagnostic: ftn-1370 ftn: ERROR , \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET SIMD. |
| 5 | diagnostic: ftn-1725 ftn: ERROR KP1, \| Unexpected syntax while parsing the DIRECTIVE statement : "scalar, aggregate, allocatable or pointer" was expected but found ")". |
| 5 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 4 | diagnostic: ftn-1747 ftn: ERROR , \| The stride specified for array "IB" must not be greater than 1. Subarray references in the MAP clause must be to contiguous memory. |
| 3 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP DISTRIBUTE. |
| 3 | diagnostic: ftn-1725 ftn: ERROR KP1, \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 2 | diagnostic: ftn-1747 ftn: ERROR , \| The stride specified for array "IA" must not be greater than 1. Subarray references in the MAP clause must be to contiguous memory. |

Features most associated with rejection: defaultmap:tofrom:all (22/22); base:al:strided_update (18/18); defaultmap:default:all (16/16); clause:thread_limit (73/89); red:in_reduction:* (13/19); split:target | teams | distribute (17/26); clause:firstprivate (13/20); wrap:host_update_to (29/45)

### cce20

| programs | message |
|---|---|
| 12 | diagnostic: ftn-1747 ftn: ERROR , \| The stride specified for array "DR" must not be greater than 1. Subarray references in the MAP clause must be to contiguous memory. |
| 8 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 5 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP DISTRIBUTE. |
| 4 | diagnostic: ftn-1747 ftn: ERROR , \| The stride specified for array "IB" must not be greater than 1. Subarray references in the MAP clause must be to contiguous memory. |
| 3 | diagnostic: ftn-1725 ftn: ERROR KP1, \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 2 | diagnostic: ftn-1747 ftn: ERROR , \| The stride specified for array "IA" must not be greater than 1. Subarray references in the MAP clause must be to contiguous memory. |
| 1 | diagnostic: ftn-1310 ftn: ERROR KP1, \| Object "I" is specified on the FIRSTPRIVATE clause. It must have a shared scope in the enclosing region. |
| 1 | diagnostic: ftn-1510 ftn: ERROR KP1, \| Variable "S2" must have its data scope explicitly declared because DEFAULT(NONE) was specified. |
| 1 | diagnostic: ftn-1725 ftn: ERROR KP3, \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 1 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP TARGET TEAMS DISTRIBUTE. |
| 1 | diagnostic: ftn-1310 ftn: ERROR , \| Object "I" is specified on the FIRSTPRIVATE clause. It must have a shared scope in the enclosing region. |
| 1 | diagnostic: ftn-1370 ftn: ERROR KP1, \| The ORDER clause is not allowed with directive !$OMP TEAMS DISTRIBUTE. |

Features most associated with rejection: base:al:strided_update (18/18); wrap:host_update_to (21/45); base:dt:target_update_component (14/30); chain:target teams distribute (18/39); split:target | teams | distribute (12/26); defaultmap:tofrom:allocatable (6/16); clause:num_teams (21/59); wrap:target_data (20/62)

### cce21

| programs | message |
|---|---|
| 13 | link_undefined_symbol: lld: error: undefined symbol: _cray$mt_taskwait |
| 12 | diagnostic: ftn-1747 ftn: ERROR , \| The stride specified for array "DR" in the MAP clause must not be greater than 1. |
| 8 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 5 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP DISTRIBUTE. |
| 4 | diagnostic: ftn-1747 ftn: ERROR , \| The stride specified for array "IB" in the MAP clause must not be greater than 1. |
| 3 | diagnostic: ftn-1725 ftn: ERROR KP1, \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 2 | diagnostic: ftn-1747 ftn: ERROR , \| The stride specified for array "IA" in the MAP clause must not be greater than 1. |
| 1 | diagnostic: ftn-1310 ftn: ERROR KP1, \| Object "I" is specified on the FIRSTPRIVATE clause. It must have a shared scope in the enclosing region. |
| 1 | diagnostic: ftn-1510 ftn: ERROR KP1, \| Variable "S2" must have its data scope explicitly declared because DEFAULT(NONE) was specified. |
| 1 | diagnostic: ftn-1725 ftn: ERROR KP3, \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 1 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP TARGET TEAMS DISTRIBUTE. |
| 1 | diagnostic: ftn-1310 ftn: ERROR , \| Object "I" is specified on the FIRSTPRIVATE clause. It must have a shared scope in the enclosing region. |

Features most associated with rejection: base:al:strided_update (18/18); red:in_reduction:* (12/19); clause:in_reduction (20/34); dir:taskgroup (20/34); kernel:inred (20/34); split:target | teams | distribute (14/26); red:in_reduction:+ (9/17); chain:target teams distribute (20/39)

## Generator rejects

Programs failing a legality check are never run. Causes (`rules`: a 5.2 rule of offload.engine.rules fired, a generator or rule bug; `flang`: AFAR flang's frontend refused a program the rules and gfortran accept; see the report for which of these are flang's errors):

| count | cause | seeds |
|---|---|---|

## Flaky results

- seed 99 cce19: wrong_code: checksum=313523805 ran_on_host=0 expected=1173248158 | wrong_code: checksum=313523805 ran_on_host=0 expected=1173248158 | wrong_code: checksum=919817920 ran_on_host=0 expected=1173248158 | wrong_code: checksum=313523805 ran_on_host=0 expected=1173248158
- seed 99 cce21: wrong_code: checksum=313523805 ran_on_host=0 expected=1173248158 | wrong_code: checksum=859174522 ran_on_host=0 expected=1173248158 | wrong_code: checksum=313523805 ran_on_host=0 expected=1173248158 | wrong_code: checksum=859174522 ran_on_host=0 expected=1173248158
- seed 106 cce19: wrong_code: checksum=1010104773 ran_on_host=0 expected=812942855 | wrong_code: checksum=1010104773 ran_on_host=0 expected=812942855 | wrong_code: checksum=1604972828 ran_on_host=0 expected=812942855 | wrong_code: checksum=2088308335 ran_on_host=0 expected=812942855
- seed 210 cce20: wrong_code: checksum=1079831101 ran_on_host=0 expected=1566639662 | wrong_code: checksum=1269877813 ran_on_host=0 expected=1566639662 | wrong_code: checksum=1068139320 ran_on_host=0 expected=1566639662 | wrong_code: checksum=2100215347 ran_on_host=0 expected=1566639662
- seed 210 cce21: wrong_code: checksum=1617653027 ran_on_host=0 expected=1566639662 | wrong_code: checksum=1791761717 ran_on_host=0 expected=1566639662 | wrong_code: checksum=2100215347 ran_on_host=0 expected=1566639662 | wrong_code: checksum=1875093292 ran_on_host=0 expected=1566639662

## Appendix: host reference checks (not offload findings)

Device offload only: host runs (OMP_TARGET_OFFLOAD=disabled) and the sequential elision are references for the expected value, never measurements of a toolchain. A host_path_failure below is recorded data (results/fuzz/<run>/summary.json), not an offload finding, and it counts nowhere in the tables above.

The reference host run (OMP_TARGET_OFFLOAD=disabled, the first toolchain that compiled) failed for 0 programs (host_ref_failed) and printed another checksum than the model for 5 (host_mismatch). For each, every toolchain whose build compiled ran it on the host (rebuilt and run twice: results/fuzz/b3/hostcheck.jsonl), and the sequential elision (offload.engine.expected) ran where it applies. Rule: **valid** when at least one of them prints the model's checksum; the host builds that ran and did not are `host_path_failure` records (a host-path compiler or runtime bug: out of scope, not an offload finding). **noncompliant** when none does (a generator or model defect): excluded from the findings and the tallies above. A toolchain whose build does not compile has no host build ('no host build'). Values are host checksums. Scope: only these programs had every toolchain's host build run; for the others only the reference toolchain's host run exists, so host_path_failure counts are a lower bound.

| seed | reference | ref tc | model | afar host | cce19 host | cce20 host | cce21 host | elision | validity | host_path_failure |
|---|---|---|---|---|---|---|---|---|---|---|
| 61 | host_mismatch | cce20 | 1378142006 | no build: compile_reject | no build: compile_reject | 584836211 | no build: compile_reject | **checksum=1378142006** | valid | cce20 |
| 137 | host_mismatch | afar | 1310654026 | 1193640832 | **1310654026** | **1310654026** | **1310654026** | **checksum=1310654026** | valid | afar |
| 209 | host_mismatch | cce19 | 419320569 | no build: compile_reject | 1996115140 | 1996115140 | 1996115140 | **checksum=419320569** | valid | cce19, cce20, cce21 |
| 250 | host_mismatch | cce20 | 1259287656 | no build: compile_reject | no build: compile_reject | 609334106 | 609334106 | **checksum=1259287656** | valid | cce20, cce21 |
| 271 | host_mismatch | cce19 | 569481647 | no build: compile_reject | 630312081 | **569481647** | **569481647** | **checksum=569481647** | valid | cce19 |

### host_path_failure (valid programs; host-path failures, out of scope)

- afar: 1 programs (seeds 137)
- cce19: 2 programs (seeds 209, 271)
- cce20: 3 programs (seeds 61, 209, 250)
- cce21: 2 programs (seeds 209, 250)

### Noncompliant programs (generator/model investigation)

(none)
