# Fuzz campaign `c1`

Csmith-style random OpenMP 5.2 Fortran offload programs (offload.engine.fuzz, generator `fuzz-1`), run on every toolchain at -O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory; reference: the Python model of each program, checked against a host run (OMP_TARGET_OFFLOAD=disabled, a reference only; see the appendix 'Host reference checks' for the programs whose host run failed or disagreed). Machine-readable: results/fuzz/c1/summary.json.

## Size and timing

- programs generated: 2400; legal and run: 2400 (judged: 2398; noncompliant, excluded from every count below: 2); generator rejects: 0; worker crashes: 0
- campaign wall time: 11314 s with 4 workers (764 programs/hour; 28.2 s per program and worker, all toolchains and repeats included)
- programs whose device results agree with the model on every toolchain: 758

## Classes per toolchain

Rejections (compile_reject) are features a toolchain does not support, not failures. Flaky = the repeats differed (counted in the worst class).

| class | afar | cce19 | cce20 | cce21 |
|---|---|---|---|---|
| agree | 1720 | 1066 | 1502 | 1292 |
| compile_reject | 563 | 873 | 176 | 359 |
| ice | 4 | 373 | 587 | 587 |
| wrong_code | 58 (3 flaky) | 82 (24 flaky) | 125 (9 flaky) | 154 (9 flaky) |
| host_fallback | 0 | 0 | 0 | 0 |
| timeout | 0 | 3 | 0 | 0 |
| run_error | 53 | 1 | 8 | 6 |
| harness_error | 0 | 0 | 0 | 0 |

## Known findings rediscovered

- cce19-target-parallel-guarded-loop (wrong code on cce19 in a program with a thread-0-guarded sequential loop in target parallel): 70 programs (seeds 13, 20, 42, 60, 131, 234, 249, 275, 372, 407, 415, 467)
- cce21-defaultmap-aggregate-flag (wrong code or host fallback on cce21 where cce20 agrees, in a program with a defaultmap clause; the finding's symptom: a map(tofrom) scalar is not copied back): 39 programs (seeds 28, 67, 102, 157, 233, 361, 388, 430, 518, 551, 601, 603)
- (control for the line above: the same without a defaultmap clause): 1 programs (seeds 1576)
- cce21-in-reduction-taskwait-link (cce21 link failure on _cray$mt_taskwait): 183 programs (seeds 25, 33, 34, 42, 52, 72, 88, 142, 184, 197, 198, 202)
- cce19-target-parallel-single-ice / task ICE (CCE 'unhandled construct type'): 458 programs (seeds 1, 2, 11, 32, 38, 40, 51, 54, 56, 59, 62, 64)

## Distinct minimized failures

| file | toolchain | kind | also fails on | lines | expected | observed |
|---|---|---|---|---|---|---|
| `data/findings/fuzz/2224-cce19.f90` | cce19 | ice | cce20, cce21 | 48 -> 15 | compiles | internal compiler error: ice: INTERNAL COMPILER ERROR:  "unhandled construct type" (/workspace/crayftn/pdgcs/v_openmp.c, line 7617, version cc4d36e4ff3377d45f0e |
| `data/findings/fuzz/1540-afar.f90` | afar | ice | - | 50 -> 17 | compiles | internal compiler error: ice: error: verification of lowering to FIR failed |
| `data/findings/fuzz/958-cce20.f90` | cce20 | ice | afar, cce19, cce21 | 57 -> 26 | compiles | internal compiler error: ice: INTERNAL COMPILER ERROR:  "Mismatched last induction expression for last private operators" (/workspace/crayftn/pdgcs/v_mt_transla |
| `data/findings/fuzz/591-cce19.f90` | cce19 | ice | cce20, cce21 | 58 -> 29 | compiles | internal compiler error: ice: INTERNAL COMPILER ERROR:  "Unhandled contexts must be fixed!!! |
| `data/findings/fuzz/1391-cce20.f90` | cce20 | ice | cce19, cce21 | 59 -> 24 | compiles | internal compiler error: ice: INTERNAL COMPILER ERROR:  "ACC - barrier/reset/protected last private not supported" (/workspace/crayftn/pdgcs/v_mt_translate.c, l |
| `data/findings/fuzz/2334-cce19.f90` | cce19 | ice | cce20, cce21 | 65 -> 31 | compiles | internal compiler error: ice: INTERNAL COMPILER ERROR:  "Couldn't find an atomic update statement" (/workspace/crayftn/pdgcs/v_mt_translate_atomic.c, line 1703, |
| `data/findings/fuzz/165-cce19.f90` | cce19 | ice | afar, cce20, cce21 | 98 -> 37 | compiles | internal compiler error: ice: INTERNAL COMPILER ERROR:  "unhandled operator |
| `data/findings/fuzz/650-afar.f90` | afar | wrong_code | - | 54 -> 31 | the host reference checksum (host reference (afar/cce19) checksum=649664593) | device checksum=0 ran_on_host=0 |
| `data/findings/fuzz/700-afar.f90` | afar | wrong_code | - | 62 -> 33 | the host reference checksum (host reference (afar/cce19) checksum=785543890) | device checksum=1774038079 ran_on_host=0 |
| `data/findings/fuzz/87-afar.f90` | afar | wrong_code | - | 64 -> 34 | the host reference checksum (host reference (afar) checksum=748154768) | device checksum=0 ran_on_host=0 |
| `data/findings/fuzz/98-cce19.f90` | cce19 | wrong_code | - | 46 -> 20 | the host reference checksum (host reference (afar/cce20) checksum=1819295657) | device checksum=0 ran_on_host=0 |
| `data/findings/fuzz/536-cce19.f90` | cce19 | wrong_code | cce20, cce21 | 52 -> 24 | the host reference checksum (host reference (cce19/afar) checksum=716289326) | device checksum=820542974 ran_on_host=0 |
| `data/findings/fuzz/1936-afar.f90` | afar | wrong_code | - | 70 -> 47 | the host reference checksum (host reference (afar) checksum=2147483504) | device checksum=129 ran_on_host=0 |
| `data/findings/fuzz/1978-cce19.f90` | cce19 | wrong_code | - | 53 -> 21 | the host reference checksum (host reference (cce20/cce21) checksum=1879642524) | device checksum=0 ran_on_host=0 |
| `data/findings/fuzz/2014-cce19.f90` | cce19 | wrong_code | cce20, cce21 | 54 -> 32 | the host reference checksum (host reference (cce19/afar) checksum=0) | device checksum=1255704643 ran_on_host=0 |
| `data/findings/fuzz/16-cce20.f90` | cce20 | wrong_code | cce19, cce21 | 51 -> 25 | the host reference checksum (host reference (cce20/afar) checksum=535067391) | device checksum=32891495 ran_on_host=0 |
| `data/findings/fuzz/1749-cce20.f90` | cce20 | wrong_code | cce21 | 51 -> 20 | the host reference checksum (host reference (cce20/afar) checksum=63) | device checksum=3 ran_on_host=0 |
| `data/findings/fuzz/14-cce20.f90` | cce20 | wrong_code | cce19, cce21 | 65 -> 23 | the host reference checksum (host reference (cce20/afar) checksum=24) | device checksum=0 ran_on_host=0 |
| `data/findings/fuzz/1644-cce21.f90` | cce21 | wrong_code | - | 52 -> 18 | the host reference checksum (host reference (afar/cce19) checksum=20085) | device checksum=2147483614 ran_on_host=0 |
| `data/findings/fuzz/775-cce21.f90` | cce21 | wrong_code | - | 58 -> 20 | the host reference checksum (host reference (afar/cce19) checksum=255) | device checksum=4 ran_on_host=0 |
| `data/findings/fuzz/698-afar.f90` | afar | run_error | - | 61 -> 51 | runs to completion (the host run does) | device: fail crash: SIGABRT; host reference (afar/cce19) checksum=260035799 |
| `data/findings/fuzz/916-afar.f90` | afar | run_error | - | 63 -> 37 | runs to completion (the host run does) | device: fail crash: SIGABRT; host reference (afar/cce19) checksum=0 |
| `data/findings/fuzz/1131-afar.f90` | afar | run_error | - | 66 -> 34 | runs to completion (the host run does) | device: fail crash: SIGABRT; host reference (afar/cce19) checksum=0 |
| `data/findings/fuzz/158-afar.f90` | afar | run_error | - | 68 -> 49 | runs to completion (the host run does) | device: fail crash: SIGABRT; host reference (afar/cce19) checksum=0 |
| `data/findings/fuzz/1505-cce20.f90` | cce20 | run_error | - | 136 -> 64 | runs to completion (the host run does) | device: fail crash: SIGSEGV; host reference (cce20/afar) checksum=1148569567 |

Not minimized:

- seed 2224 cce20 ice: covered_by data/findings/fuzz/2224-cce19.f90
- seed 209 cce20 wrong_code: not_reproduced no toolchain's host run matches the model
- seed 16 cce21 wrong_code: covered_by data/findings/fuzz/16-cce20.f90
- seed 1749 cce21 wrong_code: covered_by data/findings/fuzz/1749-cce20.f90
- seed 1505 cce19 run_error: not_reproduced the failure does not reproduce: device: ok ; host reference (cce19/afar) checksum=613243018

## Wrong code (all programs)

- afar: 58 programs (seeds 11, 87, 121, 171, 193, 226, 261, 268, 372, 401, 414, 453, 562, 594, 599, 620, 650, 653, 700, 721)
- cce19: 82 programs (seeds 13, 14, 20, 42, 60, 98, 131, 234, 249, 275, 372, 393, 407, 415, 467, 531, 536, 568, 598, 648)
- cce20: 125 programs (seeds 13, 14, 16, 18, 20, 21, 22, 25, 34, 42, 60, 70, 106, 131, 163, 209, 234, 241, 249, 264)
- cce21: 154 programs (seeds 13, 14, 16, 18, 20, 21, 22, 28, 60, 67, 70, 102, 106, 131, 157, 163, 209, 233, 234, 241)

## Internal compiler errors (deduplicated by message)

| toolchain | programs | message | seeds |
|---|---|---|---|
| cce19 | 289 | ice: INTERNAL COMPILER ERROR: "unhandled construct type" (v_openmp.c, line 7617, version <v>) | 2, 11, 32, 51, 56 |
| cce20 | 275 | ice: INTERNAL COMPILER ERROR: "unhandled acc construct type" (v_openmp.c, line 7881, version <v>) | 2, 38, 40, 54, 59 |
| cce21 | 275 | ice: INTERNAL COMPILER ERROR: "unhandled acc construct type" (v_openmp.c, line 8265, version <v>) | 2, 38, 40, 54, 59 |
| cce20 | 182 | ice: INTERNAL COMPILER ERROR: "unhandled construct type" (v_openmp.c, line 7814, version <v>) | 1, 11, 32, 51, 56 |
| cce21 | 182 | ice: INTERNAL COMPILER ERROR: "unhandled construct type" (v_openmp.c, line 8197, version <v>) | 1, 11, 32, 51, 56 |
| cce20 | 114 | ice: INTERNAL COMPILER ERROR: "ACC - barrier/reset/protected last private not supported" (v_mt_translate.c, line 5607, version <v>) | 31, 78, 100, 115, 134 |
| cce21 | 114 | ice: INTERNAL COMPILER ERROR: "ACC - barrier/reset/protected last private not supported" (v_mt_translate.c, line 5798, version <v>) | 31, 78, 100, 115, 134 |
| cce19 | 71 | ice: INTERNAL COMPILER ERROR: "ACC - barrier/reset/protected last private not supported" (v_mt_translate.c, line 4874, version <v>) | 31, 78, 100, 134, 136 |
| cce20 | 9 | ice: INTERNAL COMPILER ERROR: "Couldn't find an atomic update statement" (v_mt_translate_atomic.c, line 1703, version <v>) | 259, 477, 966, 1237, 1466 |
| cce21 | 9 | ice: INTERNAL COMPILER ERROR: "Couldn't find an atomic update statement" (v_mt_translate_atomic.c, line 1702, version <v>) | 259, 477, 966, 1237, 1466 |
| cce19 | 8 | ice: INTERNAL COMPILER ERROR: "Couldn't find an atomic update statement" (v_mt_translate_atomic.c, line 1703, version <v>) | 259, 477, 966, 1237, 1466 |
| afar | 4 | afar FIR verification: 'omp.target' op SPMD kernel must capture an 'omp.loop_nest' operation | 1422, 1540, 1899, 2064 |
| cce19 | 3 | ice: INTERNAL COMPILER ERROR: "Unhandled contexts must be fixed!!! | 385, 591, 2253 |
| cce20 | 3 | ice: INTERNAL COMPILER ERROR: "Mismatched last induction expression for last private operators" (v_mt_translate.c, line 901, version <v>) | 166, 958, 1899 |
| cce20 | 3 | ice: INTERNAL COMPILER ERROR: "Unhandled contexts must be fixed!!! | 385, 591, 2253 |
| cce21 | 3 | ice: INTERNAL COMPILER ERROR: "Mismatched last induction expression for last private operators" (v_mt_translate.c, line 911, version <v>) | 166, 958, 1899 |
| cce21 | 3 | ice: INTERNAL COMPILER ERROR: "Unhandled contexts must be fixed!!! | 385, 591, 2253 |
| cce19 | 1 | ice: INTERNAL COMPILER ERROR: "Mismatched last induction expression for last private operators" (v_mt_translate.c, line 871, version <v>) | 1899 |
| cce19 | 1 | ice: INTERNAL COMPILER ERROR: "unhandled operator | 165 |
| cce20 | 1 | ice: INTERNAL COMPILER ERROR: "unhandled operator | 165 |
| cce21 | 1 | ice: INTERNAL COMPILER ERROR: "unhandled operator | 165 |

## Run errors, timeouts, host fallbacks

| toolchain | class | programs | reason | seeds |
|---|---|---|---|---|
| afar | run_error | 52 | crash: SIGABRT; without mandatory: crash: SIGABRT | 33, 35, 91, 115, 158 |
| cce20 | run_error | 7 | exit_status: 1; without mandatory: exit_status: 1 | 232, 564, 662, 786, 1197 |
| cce21 | run_error | 6 | exit_status: 1; without mandatory: exit_status: 1 | 564, 662, 786, 1197, 2087 |
| cce19 | timeout | 3 | compile_timeout | 427, 1314, 2056 |
| afar | run_error | 1 | crash: SIGABRT; without mandatory: crash: SIGSEGV | 314 |
| cce19 | run_error | 1 | crash: SIGSEGV; without mandatory: crash: SIGSEGV | 1505 |
| cce20 | run_error | 1 | crash: SIGABRT; without mandatory: crash: SIGABRT | 1505 |

## Features and feature pairs most associated with failures

Among programs the toolchain compiled (or crashed on). Lift = the rate of the class among programs with the feature (pair) over the toolchain's overall rate; a pair is listed only when it beats both of its features alone by 25%.

### afar: wrong_code

Single features: red:critical (16/26, lift 19.47); red:atomic:iand (4/23, lift 5.5); red:atomic:ieor (4/26, lift 4.87); clause:default:none (30/232, lift 4.09); split:target | teams | distribute | parallel | do simd (19/149, lift 4.03); dir:do simd (26/212, lift 3.88); split:target | teams | distribute | parallel | do (16/131, lift 3.86); clause:schedule:auto (8/66, lift 3.83)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| clause:default:none + scalar:tofrom | 30 | 10 | 0.333 | 0.129 | 10.55 |
| clause:default:none + split:target \| teams \| distribute \| parallel \| do | 31 | 10 | 0.323 | 0.129 | 10.21 |
| clause:default:shared + red:clause:ieor | 25 | 7 | 0.28 | 0.097 | 8.86 |
| scalar:firstprivate + split:target \| teams \| distribute \| parallel \| do | 25 | 7 | 0.28 | 0.122 | 8.86 |
| chain:target teams distribute parallel do + clause:default:none | 48 | 13 | 0.271 | 0.129 | 8.57 |
| clause:default:shared + red:clause:max | 26 | 7 | 0.269 | 0.086 | 8.52 |
| clause:default:none + clause:schedule:auto | 15 | 4 | 0.267 | 0.129 | 8.44 |
| clause:firstprivate + red:clause:ieor | 15 | 4 | 0.267 | 0.097 | 8.44 |

### afar: ice

Single features: clause:lastprivate:conditional (4/16, lift 114.69); split:target parallel do (4/38, lift 48.29); dir:target parallel do (4/57, lift 32.19); clause:lastprivate (4/172, lift 10.67); scalar:implied_tofrom (4/214, lift 8.57); chain:target parallel do (4/258, lift 7.11); dir:parallel do (3/281, lift 4.9); map:mod:close (3/462, lift 2.98)

| feature pair | programs | ice | rate | best single rate | lift |
|---|---|---|---|---|---|
| clause:lastprivate + dir:target parallel do | 15 | 4 | 0.267 | 0.07 | 122.33 |
| scalar:implied_tofrom + split:target parallel do | 19 | 4 | 0.211 | 0.105 | 96.58 |
| clause:num_threads + split:target parallel do | 15 | 3 | 0.2 | 0.105 | 91.75 |
| dir:target parallel do + map:mod:close | 16 | 3 | 0.188 | 0.07 | 86.02 |
| body:temp + dir:target parallel do | 20 | 3 | 0.15 | 0.07 | 68.81 |
| clause:num_threads + dir:target parallel do | 21 | 3 | 0.143 | 0.07 | 65.54 |
| decl:explicit_rank1 + split:target parallel do | 30 | 4 | 0.133 | 0.105 | 61.17 |
| dir:target parallel do + scalar:implied_tofrom | 30 | 4 | 0.133 | 0.07 | 61.17 |

### afar: run_error

Single features: map:mod:present (32/215, lift 5.15); dir:parallel do simd (5/40, lift 4.33); red:clause:iand (15/161, lift 3.23); clause:schedule:auto (6/66, lift 3.15); split:target | teams | distribute | parallel | do simd (13/149, lift 3.02); clause:schedule:guided (5/58, lift 2.98); map:mod:close (38/462, lift 2.85); chain:target teams distribute parallel do simd (21/259, lift 2.81)

| feature pair | programs | run_error | rate | best single rate | lift |
|---|---|---|---|---|---|
| map:mod:close + map:mod:present | 58 | 31 | 0.534 | 0.149 | 18.51 |
| map:mod:present + split:target \| parallel \| do | 19 | 7 | 0.368 | 0.149 | 12.76 |
| map:mod:present + red:clause:+ | 22 | 8 | 0.364 | 0.149 | 12.59 |
| clause:if:parallel + map:mod:present | 18 | 6 | 0.333 | 0.149 | 11.54 |
| clause:safelen + map:mod:present | 36 | 11 | 0.306 | 0.149 | 10.58 |
| map:mod:present + red:clause:iand | 23 | 7 | 0.304 | 0.149 | 10.54 |
| map:mod:present + red:clause:ior | 23 | 7 | 0.304 | 0.149 | 10.54 |
| map:mod:present + split:target \| simd | 28 | 8 | 0.286 | 0.149 | 9.89 |

### cce19: wrong_code

Single features: guard:par_thread0 (53/94, lift 10.49); guard:split_par_thread0 (21/47, lift 8.31); clause:private:loop_variable (9/38, lift 4.4); kernel:guard (71/343, lift 3.85); dir:target teams distribute parallel do (3/15, lift 3.72); dir:distribute parallel do simd (3/17, lift 3.28); dir:parallel do simd (6/36, lift 3.1); guard:target_seq (9/56, lift 2.99)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| guard:par_thread0 + tasking:nowait_depend | 21 | 16 | 0.762 | 0.564 | 14.17 |
| chain:target teams distribute parallel do + kernel:guard | 32 | 12 | 0.375 | 0.207 | 6.97 |
| dir:target parallel + guard:teams_team0 | 16 | 6 | 0.375 | 0.137 | 6.97 |
| kernel:guard + split:target \| teams \| distribute \| parallel \| do | 16 | 6 | 0.375 | 0.207 | 6.97 |
| clause:proc_bind + kernel:guard | 30 | 11 | 0.367 | 0.207 | 6.82 |
| clause:private:loop_variable + kernel:loop | 25 | 9 | 0.36 | 0.237 | 6.7 |
| clause:private:loop_variable + dir:target | 20 | 7 | 0.35 | 0.237 | 6.51 |
| kernel:guard + tasking:nowait_depend | 57 | 19 | 0.333 | 0.207 | 6.2 |

### cce19: ice

Single features: phase:nowait_barrier (95/95, lift 4.09); guard:masked (46/46, lift 4.09); guard:single (44/44, lift 4.09); red:critical (20/20, lift 4.09); kernel:phase (188/190, lift 4.05); phase:do simd (105/106, lift 4.05); phase:do (160/162, lift 4.04); phase:single (104/106, lift 4.01)

| feature pair | programs | ice | rate | best single rate | lift |
|---|---|---|---|---|---|
| dir:target parallel + split:target \| teams \| distribute \| parallel \| do simd | 27 | 23 | 0.852 | 0.628 | 3.48 |
| dir:target parallel + split:target \| parallel \| do | 19 | 16 | 0.842 | 0.628 | 3.44 |
| dir:target parallel + split:target \| teams \| loop | 30 | 25 | 0.833 | 0.628 | 3.41 |
| clause:lastprivate + clause:schedule:dynamic | 19 | 15 | 0.789 | 0.391 | 3.23 |
| clause:lastprivate:conditional + dir:parallel | 23 | 17 | 0.739 | 0.537 | 3.02 |
| clause:lastprivate + split:target \| teams \| distribute \| parallel \| do simd | 40 | 27 | 0.675 | 0.391 | 2.76 |
| clause:if:target + defaultmap:tofrom:allocatable | 15 | 10 | 0.667 | 0.306 | 2.73 |
| clause:schedule:static + clause:simdlen | 15 | 10 | 0.667 | 0.254 | 2.73 |

### cce20: wrong_code

Single features: guard:par_thread0 (82/150, lift 9.72); guard:split_par_thread0 (32/76, lift 7.48); clause:private:loop_variable (15/63, lift 4.23); kernel:guard (106/509, lift 3.7); split:target teams | distribute | parallel do (3/15, lift 3.56); dir:parallel do simd (10/55, lift 3.23); split:target | teams distribute | simd (5/28, lift 3.17); defaultmap:alloc:allocatable (3/17, lift 3.14)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| chain:target teams loop + guard:par_thread0 | 20 | 14 | 0.7 | 0.547 | 12.44 |
| dir:parallel + guard:split_par_thread0 | 22 | 13 | 0.591 | 0.421 | 10.5 |
| clause:private:loop_variable + dir:parallel | 18 | 10 | 0.556 | 0.238 | 9.88 |
| clause:if:target + guard:split_par_thread0 | 22 | 12 | 0.545 | 0.421 | 9.7 |
| dir:teams + guard:split_par_thread0 | 24 | 13 | 0.542 | 0.421 | 9.63 |
| guard:split_par_thread0 + map:section | 30 | 16 | 0.533 | 0.421 | 9.48 |
| dir:do + guard:split_par_thread0 | 15 | 8 | 0.533 | 0.421 | 9.48 |
| dir:simd + guard:split_par_thread0 | 15 | 8 | 0.533 | 0.421 | 9.48 |

### cce20: ice

Single features: kernel:phase (298/298, lift 3.79); phase:do (251/251, lift 3.79); phase:single (169/169, lift 3.79); phase:do simd (168/168, lift 3.79); phase:masked (155/155, lift 3.79); phase:nowait_barrier (151/151, lift 3.79); map:alloc (115/115, lift 3.79); phase:loop (82/82, lift 3.79)

| feature pair | programs | ice | rate | best single rate | lift |
|---|---|---|---|---|---|
| clause:lastprivate:conditional + scalar:firstprivate | 16 | 14 | 0.875 | 0.544 | 3.31 |
| dir:target parallel + split:target \| teams \| distribute \| parallel \| do simd | 38 | 31 | 0.816 | 0.628 | 3.09 |
| dir:target parallel + split:target \| parallel \| do | 36 | 29 | 0.806 | 0.628 | 3.05 |
| dir:target parallel + guard:teams_team0_pardo | 25 | 20 | 0.8 | 0.628 | 3.03 |
| clause:private:loop_variable + scalar:firstprivate | 15 | 12 | 0.8 | 0.635 | 3.03 |
| clause:lastprivate:conditional + split:target \| parallel \| do | 18 | 14 | 0.778 | 0.544 | 2.94 |
| clause:lastprivate:conditional + dir:parallel | 34 | 26 | 0.765 | 0.544 | 2.89 |
| clause:lastprivate:conditional + dir:do | 34 | 25 | 0.735 | 0.544 | 2.78 |

### cce20: run_error

Single features: clause:if:simd (3/192, lift 4.34); wrap:host_update_to (4/267, lift 4.16); chain:target teams distribute simd (4/324, lift 3.43); wrap:enter_exit_data (4/410, lift 2.71); loop:step2 (5/564, lift 2.46); dir:simd (6/695, lift 2.4); chain:target parallel do simd (3/347, lift 2.4); chain:target teams distribute parallel do simd (3/348, lift 2.39)

| feature pair | programs | run_error | rate | best single rate | lift |
|---|---|---|---|---|---|
| clause:if:simd + wrap:host_update_to | 36 | 3 | 0.083 | 0.016 | 23.15 |
| chain:target teams distribute simd + wrap:host_update_to | 53 | 3 | 0.057 | 0.015 | 15.72 |
| chain:target teams distribute simd + wrap:enter_exit_data | 59 | 3 | 0.051 | 0.012 | 14.12 |
| clause:if:simd + loop:step2 | 59 | 3 | 0.051 | 0.016 | 14.12 |
| clause:if:simd + clause:thread_limit | 65 | 3 | 0.046 | 0.016 | 12.82 |
| body:temp + clause:if:simd | 86 | 3 | 0.035 | 0.016 | 9.69 |
| dir:simd + wrap:host_update_to | 95 | 3 | 0.032 | 0.015 | 8.77 |
| clause:thread_limit + wrap:host_update_to | 96 | 3 | 0.031 | 0.015 | 8.68 |

### cce21: wrong_code

Single features: guard:par_thread0 (81/136, lift 7.89); guard:split_par_thread0 (34/73, lift 6.17); clause:private:loop_variable (15/60, lift 3.31); kernel:guard (118/482, lift 3.24); red:atomic:+ (7/29, lift 3.2); red:atomic:min (7/31, lift 2.99); guard:teams_team0 (17/76, lift 2.96); red:atomic:ior (4/18, lift 2.94)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| dir:simd + guard:split_par_thread0 | 15 | 10 | 0.667 | 0.466 | 8.83 |
| dir:teams + guard:split_par_thread0 | 24 | 15 | 0.625 | 0.466 | 8.28 |
| dir:parallel + guard:split_par_thread0 | 21 | 13 | 0.619 | 0.466 | 8.2 |
| dir:do + guard:split_par_thread0 | 15 | 9 | 0.6 | 0.466 | 7.94 |
| guard:split_par_thread0 + map:mod:close | 15 | 9 | 0.6 | 0.466 | 7.94 |
| body:inner_seq_loop + guard:split_par_thread0 | 32 | 19 | 0.594 | 0.466 | 7.86 |
| defaultmap:tofrom:scalar + kernel:guard | 15 | 8 | 0.533 | 0.245 | 7.06 |
| clause:private:loop_variable + dir:parallel | 16 | 8 | 0.5 | 0.25 | 6.62 |

### cce21: ice

Single features: kernel:phase (298/298, lift 3.47); phase:do (251/251, lift 3.47); phase:single (169/169, lift 3.47); phase:do simd (168/168, lift 3.47); phase:masked (155/155, lift 3.47); phase:nowait_barrier (151/151, lift 3.47); map:alloc (115/115, lift 3.47); phase:loop (82/82, lift 3.47)

| feature pair | programs | ice | rate | best single rate | lift |
|---|---|---|---|---|---|
| dir:target parallel + red:in_reduction:+ | 19 | 17 | 0.895 | 0.653 | 3.11 |
| clause:in_reduction + red:clause | 27 | 24 | 0.889 | 0.523 | 3.09 |
| dir:taskgroup + red:clause | 27 | 24 | 0.889 | 0.523 | 3.09 |
| kernel:inred + red:clause | 27 | 24 | 0.889 | 0.523 | 3.09 |
| red:clause + red:in_reduction:* | 17 | 15 | 0.882 | 0.469 | 3.06 |
| clause:lastprivate:conditional + scalar:firstprivate | 16 | 14 | 0.875 | 0.569 | 3.04 |
| clause:in_reduction + dir:target parallel | 44 | 37 | 0.841 | 0.653 | 2.92 |
| dir:target parallel + dir:taskgroup | 44 | 37 | 0.841 | 0.653 | 2.92 |

### cce21: run_error

Single features: wrap:host_update_to (4/240, lift 5.66); clause:if:simd (3/180, lift 5.66); chain:target teams distribute simd (3/294, lift 3.47); wrap:target_data (3/366, lift 2.79); wrap:enter_exit_data (3/372, lift 2.74); dir:simd (4/651, lift 2.09); loop:step2 (3/531, lift 1.92); clause:thread_limit (3/575, lift 1.77)

| feature pair | programs | run_error | rate | best single rate | lift |
|---|---|---|---|---|---|
| clause:if:simd + wrap:host_update_to | 34 | 3 | 0.088 | 0.017 | 29.99 |
| chain:target teams distribute simd + wrap:host_update_to | 49 | 3 | 0.061 | 0.017 | 20.81 |
| clause:if:simd + loop:step2 | 56 | 3 | 0.054 | 0.017 | 18.21 |
| clause:if:simd + clause:thread_limit | 61 | 3 | 0.049 | 0.017 | 16.71 |
| body:temp + clause:if:simd | 78 | 3 | 0.038 | 0.017 | 13.07 |
| clause:thread_limit + wrap:host_update_to | 87 | 3 | 0.034 | 0.017 | 11.72 |
| loop:step2 + wrap:host_update_to | 88 | 3 | 0.034 | 0.017 | 11.59 |
| dir:simd + wrap:host_update_to | 90 | 3 | 0.033 | 0.017 | 11.33 |

## Compile rejections (features not supported)

### afar

| programs | message |
|---|---|
| 316 | not_implemented: error: loc("<path> <path> not yet implemented: lastprivate clause in constructs other than simd/worksharing-loop/taskloop |
| 106 | not_implemented: loc("<path> error: not yet implemented: Unhandled clause order in omp.wsloop operation |
| 65 | not_implemented: loc("<path> error: not yet implemented: Unhandled clause order in omp.distribute operation |
| 34 | not_implemented: error: loc("<path> <path> not yet implemented: lastprivate(conditional:) on simd construct |
| 33 | not_implemented: error: loc("<path> <path> not yet implemented: Firstprivate is currently unsupported defaultmap behaviour |
| 9 | not_implemented: error: loc("<path> <path> not yet implemented: lastprivate(conditional:) on do simd composite construct |

Features most associated with rejection: defaultmap:firstprivate:scalar (28/28); clause:order (218/220); clause:lastprivate:conditional (57/73); clause:lastprivate (392/564); split:target | teams | distribute | parallel do (13/21); split:target | teams distribute | simd (18/30); split:target teams distribute | simd (10/17); red:atomic:ior (14/24)

### cce19

| programs | message |
|---|---|
| 376 | diagnostic: ftn-1370 ftn: ERROR , \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET. |
| 233 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : "scalar, aggregate, allocatable or pointer" was expected but found ")". |
| 86 | diagnostic: ftn-1370 ftn: ERROR , \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET PARALLEL. |
| 72 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 45 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP DISTRIBUTE. |
| 21 | diagnostic: ftn-1370 ftn: ERROR , \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET SIMD. |
| 8 | diagnostic: ftn-1370 ftn: ERROR , \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET PARALLEL LOOP. |
| 8 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP TARGET TEAMS DISTRIBUTE. |
| 6 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP TEAMS DISTRIBUTE. |
| 4 | diagnostic: ftn-1310 ftn: ERROR , \| Object "I" is specified on the FIRSTPRIVATE clause. It must have a shared scope in the enclosing region. |
| 3 | diagnostic: ftn-1964 ftn: ERROR , \| Variable "IA" must have its data mapping attribute explicitly declared because default map(none) was specified. |
| 3 | diagnostic: ftn-1964 ftn: ERROR , \| Variable "IC" must have its data mapping attribute explicitly declared because default map(none) was specified. |

Features most associated with rejection: defaultmap:default:all (114/114); clause:num_teams:lower_bound (96/96); defaultmap:tofrom:all (128/129); clause:thread_limit (582/681); defaultmap:firstprivate:allocatable (12/15); split:target | teams distribute | parallel do (12/18); split:target | teams | distribute | parallel do (13/21); defaultmap:firstprivate:scalar (17/28)

### cce20

| programs | message |
|---|---|
| 93 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 60 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP DISTRIBUTE. |
| 9 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP TARGET TEAMS DISTRIBUTE. |
| 7 | diagnostic: ftn-1310 ftn: ERROR , \| Object "I" is specified on the FIRSTPRIVATE clause. It must have a shared scope in the enclosing region. |
| 6 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP TEAMS DISTRIBUTE. |
| 1 | diagnostic: ftn-1510 ftn: ERROR , \| Variable "I" must have its data scope explicitly declared because DEFAULT(NONE) was specified. |

Features most associated with rejection: clause:num_teams:lower_bound (96/96); clause:order (85/220); split:target | teams | distribute (77/232); defaultmap:alloc:allocatable (7/24); chain:target teams distribute (111/386); split:target | teams | distribute | parallel do (6/21); clause:num_teams (126/478); split:target teams distribute (15/57)

### cce21

| programs | message |
|---|---|
| 183 | link_undefined_symbol: lld: error: undefined symbol: _cray$mt_taskwait |
| 93 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 60 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP DISTRIBUTE. |
| 9 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP TARGET TEAMS DISTRIBUTE. |
| 7 | diagnostic: ftn-1310 ftn: ERROR , \| Object "I" is specified on the FIRSTPRIVATE clause. It must have a shared scope in the enclosing region. |
| 6 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP TEAMS DISTRIBUTE. |
| 1 | diagnostic: ftn-1510 ftn: ERROR , \| Variable "I" must have its data scope explicitly declared because DEFAULT(NONE) was specified. |

Features most associated with rejection: clause:num_teams:lower_bound (96/96); red:in_reduction:+ (113/161); clause:in_reduction (202/311); dir:taskgroup (202/311); kernel:inred (202/311); red:in_reduction:* (103/167); clause:order (92/220); split:target | teams | distribute (88/232)

## Generator rejects

Programs failing a legality check are never run. Causes (`rules`: a 5.2 rule of offload.engine.rules fired, a generator or rule bug; `flang`: AFAR flang's frontend refused a program the rules and gfortran accept; see the report for which of these are flang's errors):

| count | cause | seeds |
|---|---|---|

## Flaky results

- seed 13 cce19: wrong_code: checksum=123275629 ran_on_host=0 expected=1984387845 | wrong_code: checksum=1554090580 ran_on_host=0 expected=1984387845 | wrong_code: checksum=608910893 ran_on_host=0 expected=1984387845 | wrong_code: checksum=1293147191 ran_on_host=0 expected=1984387845
- seed 13 cce20: wrong_code: checksum=359731438 ran_on_host=0 expected=1984387845 | wrong_code: checksum=1664461047 ran_on_host=0 expected=1984387845 | wrong_code: checksum=359731438 ran_on_host=0 expected=1984387845 | wrong_code: checksum=359731438 ran_on_host=0 expected=1984387845
- seed 60 cce19: wrong_code: checksum=1566900327 ran_on_host=0 expected=774564267 | wrong_code: checksum=597365335 ran_on_host=0 expected=774564267 | wrong_code: checksum=853689694 ran_on_host=0 expected=774564267 | wrong_code: checksum=1589658060 ran_on_host=0 expected=774564267
- seed 60 cce21: wrong_code: checksum=1808451939 ran_on_host=0 expected=774564267 | wrong_code: checksum=1808451939 ran_on_host=0 expected=774564267 | wrong_code: checksum=1808451939 ran_on_host=0 expected=774564267 | wrong_code: checksum=1665783220 ran_on_host=0 expected=774564267
- seed 163 cce20: wrong_code: checksum=984382261 ran_on_host=0 expected=594933126 | wrong_code: checksum=984382261 ran_on_host=0 expected=594933126 | wrong_code: checksum=1546167020 ran_on_host=0 expected=594933126 | wrong_code: checksum=984382261 ran_on_host=0 expected=594933126
- seed 393 cce19: wrong_code: checksum=846675790 ran_on_host=0 expected=1410599432 | wrong_code: checksum=846675790 ran_on_host=0 expected=1410599432 | agree: checksum=1410599432 ran_on_host=0 | agree: checksum=1410599432 ran_on_host=0
- seed 393 cce21: wrong_code: checksum=846675790 ran_on_host=0 expected=1410599432 | wrong_code: checksum=846675790 ran_on_host=0 expected=1410599432 | wrong_code: checksum=846675790 ran_on_host=0 expected=1410599432 | agree: checksum=1410599432 ran_on_host=0
- seed 407 cce19: wrong_code: checksum=371472292 ran_on_host=0 expected=338234045 | wrong_code: checksum=1018955170 ran_on_host=0 expected=338234045 | wrong_code: checksum=1737018052 ran_on_host=0 expected=338234045 | wrong_code: checksum=719644160 ran_on_host=0 expected=338234045
- seed 407 cce20: wrong_code: checksum=1651237534 ran_on_host=0 expected=338234045 | wrong_code: checksum=1684897878 ran_on_host=0 expected=338234045 | wrong_code: checksum=1651237534 ran_on_host=0 expected=338234045 | wrong_code: checksum=1684897878 ran_on_host=0 expected=338234045
- seed 407 cce21: wrong_code: checksum=1651237534 ran_on_host=0 expected=338234045 | wrong_code: checksum=1651237534 ran_on_host=0 expected=338234045 | wrong_code: checksum=1684897878 ran_on_host=0 expected=338234045 | wrong_code: checksum=1684897878 ran_on_host=0 expected=338234045
- seed 415 cce19: wrong_code: checksum=657709255 ran_on_host=0 expected=551121403 | wrong_code: checksum=1361072456 ran_on_host=0 expected=551121403 | wrong_code: checksum=895569026 ran_on_host=0 expected=551121403 | wrong_code: checksum=1245033883 ran_on_host=0 expected=551121403
- seed 467 cce19: wrong_code: checksum=2135675957 ran_on_host=0 expected=224568895 | wrong_code: checksum=1360452543 ran_on_host=0 expected=224568895 | wrong_code: checksum=963007586 ran_on_host=0 expected=224568895 | wrong_code: checksum=1360452543 ran_on_host=0 expected=224568895
- seed 599 afar: wrong_code: checksum=1220799746 ran_on_host=0 expected=1371072935 | agree: checksum=1371072935 ran_on_host=0 | wrong_code: checksum=1220799746 ran_on_host=0 expected=1371072935 | wrong_code: checksum=1220799746 ran_on_host=0 expected=1371072935
- seed 651 cce19: wrong_code: checksum=1346441447 ran_on_host=0 expected=1826371849 | wrong_code: checksum=1767818457 ran_on_host=0 expected=1826371849 | wrong_code: checksum=1329038404 ran_on_host=0 expected=1826371849 | wrong_code: checksum=1329038404 ran_on_host=0 expected=1826371849
- seed 726 afar: wrong_code: checksum=1183727319 ran_on_host=0 expected=1879922715 | wrong_code: checksum=696313782 ran_on_host=0 expected=1879922715 | wrong_code: checksum=888159702 ran_on_host=0 expected=1879922715 | wrong_code: checksum=1219313582 ran_on_host=0 expected=1879922715
- seed 819 cce19: wrong_code: checksum=135219162 ran_on_host=0 expected=1292972832 | wrong_code: checksum=135219162 ran_on_host=0 expected=1292972832 | wrong_code: checksum=135219162 ran_on_host=0 expected=1292972832 | wrong_code: checksum=1949359428 ran_on_host=0 expected=1292972832
- seed 819 cce20: wrong_code: checksum=1949359428 ran_on_host=0 expected=1292972832 | wrong_code: checksum=1949359428 ran_on_host=0 expected=1292972832 | wrong_code: checksum=135219162 ran_on_host=0 expected=1292972832 | wrong_code: checksum=135219162 ran_on_host=0 expected=1292972832
- seed 819 cce21: wrong_code: checksum=1949359428 ran_on_host=0 expected=1292972832 | wrong_code: checksum=135219162 ran_on_host=0 expected=1292972832 | wrong_code: checksum=1949359428 ran_on_host=0 expected=1292972832 | wrong_code: checksum=1949359428 ran_on_host=0 expected=1292972832
- seed 909 cce19: wrong_code: checksum=1246508091 ran_on_host=0 expected=1418547638 | wrong_code: checksum=1045203083 ran_on_host=0 expected=1418547638 | wrong_code: checksum=1045203083 ran_on_host=0 expected=1418547638 | wrong_code: checksum=1045203083 ran_on_host=0 expected=1418547638
- seed 925 cce19: wrong_code: checksum=893603392 ran_on_host=0 expected=1033123183 | wrong_code: checksum=893603392 ran_on_host=0 expected=1033123183 | wrong_code: checksum=893603392 ran_on_host=0 expected=1033123183 | wrong_code: checksum=1435742406 ran_on_host=0 expected=1033123183
- seed 992 cce19: wrong_code: checksum=1886174243 ran_on_host=0 expected=358113607 | wrong_code: checksum=523768146 ran_on_host=0 expected=358113607 | wrong_code: checksum=1886174243 ran_on_host=0 expected=358113607 | wrong_code: checksum=190796792 ran_on_host=0 expected=358113607
- seed 992 cce20: wrong_code: checksum=190796792 ran_on_host=0 expected=358113607 | wrong_code: checksum=1886174243 ran_on_host=0 expected=358113607 | wrong_code: checksum=190796792 ran_on_host=0 expected=358113607 | wrong_code: checksum=1886174243 ran_on_host=0 expected=358113607
- seed 992 cce21: wrong_code: checksum=190796792 ran_on_host=0 expected=358113607 | wrong_code: checksum=190796792 ran_on_host=0 expected=358113607 | wrong_code: checksum=1886174243 ran_on_host=0 expected=358113607 | wrong_code: checksum=190796792 ran_on_host=0 expected=358113607
- seed 1066 afar: wrong_code: checksum=446962081 ran_on_host=0 expected=1218329886 | wrong_code: checksum=446962081 ran_on_host=0 expected=1218329886 | wrong_code: checksum=521883058 ran_on_host=0 expected=1218329886 | wrong_code: checksum=521883058 ran_on_host=0 expected=1218329886
- seed 1079 cce19: wrong_code: checksum=616144878 ran_on_host=0 expected=2087568571 | wrong_code: checksum=84118958 ran_on_host=0 expected=2087568571 | wrong_code: checksum=1881055592 ran_on_host=0 expected=2087568571 | wrong_code: checksum=1950732949 ran_on_host=0 expected=2087568571
- seed 1079 cce21: wrong_code: checksum=1283672735 ran_on_host=0 expected=2087568571 | wrong_code: checksum=1632311947 ran_on_host=0 expected=2087568571 | wrong_code: checksum=1283672735 ran_on_host=0 expected=2087568571 | wrong_code: checksum=1632311947 ran_on_host=0 expected=2087568571
- seed 1137 cce19: wrong_code: checksum=835298145 ran_on_host=0 expected=1835534917 | wrong_code: checksum=1458237434 ran_on_host=0 expected=1835534917 | wrong_code: checksum=2107762438 ran_on_host=0 expected=1835534917 | wrong_code: checksum=1855682391 ran_on_host=0 expected=1835534917
- seed 1189 cce19: wrong_code: checksum=1596950006 ran_on_host=0 expected=12435193 | wrong_code: checksum=1138372825 ran_on_host=0 expected=12435193 | wrong_code: checksum=1138372825 ran_on_host=0 expected=12435193 | wrong_code: checksum=1138372825 ran_on_host=0 expected=12435193
- seed 1189 cce20: wrong_code: checksum=1596950006 ran_on_host=0 expected=12435193 | wrong_code: checksum=1138372825 ran_on_host=0 expected=12435193 | wrong_code: checksum=1138372825 ran_on_host=0 expected=12435193 | wrong_code: checksum=1138372825 ran_on_host=0 expected=12435193
- seed 1189 cce21: wrong_code: checksum=1596950006 ran_on_host=0 expected=12435193 | wrong_code: checksum=1138372825 ran_on_host=0 expected=12435193 | wrong_code: checksum=1138372825 ran_on_host=0 expected=12435193 | wrong_code: checksum=1596950006 ran_on_host=0 expected=12435193
- seed 1252 cce19: wrong_code: checksum=1147019088 ran_on_host=0 expected=1457307390 | wrong_code: checksum=749489850 ran_on_host=0 expected=1457307390 | wrong_code: checksum=643063756 ran_on_host=0 expected=1457307390 | wrong_code: checksum=356666045 ran_on_host=0 expected=1457307390
- seed 1252 cce20: wrong_code: checksum=2020794537 ran_on_host=0 expected=1457307390 | wrong_code: checksum=2020794537 ran_on_host=0 expected=1457307390 | wrong_code: checksum=751088426 ran_on_host=0 expected=1457307390 | wrong_code: checksum=751088426 ran_on_host=0 expected=1457307390
- seed 1267 cce19: wrong_code: checksum=694911187 ran_on_host=0 expected=1702817618 | wrong_code: checksum=339897307 ran_on_host=0 expected=1702817618 | wrong_code: checksum=1051644279 ran_on_host=0 expected=1702817618 | wrong_code: checksum=15609254 ran_on_host=0 expected=1702817618
- seed 1267 cce20: wrong_code: checksum=1186694974 ran_on_host=0 expected=1702817618 | wrong_code: checksum=627117910 ran_on_host=0 expected=1702817618 | wrong_code: checksum=1186694974 ran_on_host=0 expected=1702817618 | wrong_code: checksum=627117910 ran_on_host=0 expected=1702817618
- seed 1292 cce19: wrong_code: checksum=1547337018 ran_on_host=0 expected=546205317 | wrong_code: checksum=712269431 ran_on_host=0 expected=546205317 | wrong_code: checksum=758959829 ran_on_host=0 expected=546205317 | wrong_code: checksum=785392883 ran_on_host=0 expected=546205317
- seed 1292 cce20: wrong_code: checksum=865337229 ran_on_host=0 expected=546205317 | wrong_code: checksum=865337229 ran_on_host=0 expected=546205317 | wrong_code: checksum=1007456389 ran_on_host=0 expected=546205317 | wrong_code: checksum=865337229 ran_on_host=0 expected=546205317
- seed 1316 cce19: wrong_code: checksum=1952905437 ran_on_host=0 expected=182541506 | wrong_code: checksum=1952905437 ran_on_host=0 expected=182541506 | wrong_code: checksum=1952905437 ran_on_host=0 expected=182541506 | wrong_code: checksum=700634057 ran_on_host=0 expected=182541506
- seed 1522 cce21: wrong_code: checksum=43500501 ran_on_host=0 expected=1213312430 | wrong_code: checksum=43500501 ran_on_host=0 expected=1213312430 | wrong_code: checksum=43500501 ran_on_host=0 expected=1213312430 | wrong_code: checksum=784840886 ran_on_host=0 expected=1213312430
- seed 1749 cce19: wrong_code: checksum=1730271492 ran_on_host=0 expected=825214391 | wrong_code: checksum=1730271492 ran_on_host=0 expected=825214391 | wrong_code: checksum=1846266653 ran_on_host=0 expected=825214391 | wrong_code: checksum=1730271492 ran_on_host=0 expected=825214391
- seed 1750 cce19: wrong_code: checksum=28123268 ran_on_host=0 expected=1014533990 | wrong_code: checksum=96437434 ran_on_host=0 expected=1014533990 | wrong_code: checksum=96437434 ran_on_host=0 expected=1014533990 | wrong_code: checksum=28123268 ran_on_host=0 expected=1014533990
- seed 1904 cce19: wrong_code: checksum=1683782728 ran_on_host=0 expected=2057575056 | wrong_code: checksum=1333676902 ran_on_host=0 expected=2057575056 | wrong_code: checksum=1683782728 ran_on_host=0 expected=2057575056 | wrong_code: checksum=1683782728 ran_on_host=0 expected=2057575056
- seed 2233 cce19: wrong_code: checksum=878723410 ran_on_host=0 expected=373507815 | wrong_code: checksum=16359712 ran_on_host=0 expected=373507815 | wrong_code: checksum=1935545024 ran_on_host=0 expected=373507815 | wrong_code: checksum=1753727426 ran_on_host=0 expected=373507815
- seed 2233 cce21: wrong_code: checksum=2112960953 ran_on_host=0 expected=373507815 | wrong_code: checksum=878723410 ran_on_host=0 expected=373507815 | wrong_code: checksum=878723410 ran_on_host=0 expected=373507815 | wrong_code: checksum=2112960953 ran_on_host=0 expected=373507815
- seed 2271 cce19: wrong_code: checksum=701023322 ran_on_host=0 expected=1809896280 | wrong_code: checksum=1209068796 ran_on_host=0 expected=1809896280 | wrong_code: checksum=222665826 ran_on_host=0 expected=1809896280 | wrong_code: checksum=625650735 ran_on_host=0 expected=1809896280
- seed 2336 cce19: wrong_code: checksum=2122818007 ran_on_host=0 expected=1391446280 | wrong_code: checksum=2122818007 ran_on_host=0 expected=1391446280 | wrong_code: checksum=985439057 ran_on_host=0 expected=1391446280 | wrong_code: checksum=985439057 ran_on_host=0 expected=1391446280

## Appendix: host reference checks (not offload findings)

Device offload only: host runs (OMP_TARGET_OFFLOAD=disabled) and the sequential elision are references for the expected value, never measurements of a toolchain. A host_path_failure below is recorded data (results/fuzz/<run>/summary.json), not an offload finding, and it counts nowhere in the tables above.

The reference host run (OMP_TARGET_OFFLOAD=disabled, the first toolchain that compiled) failed for 8 programs (host_ref_failed) and printed another checksum than the model for 33 (host_mismatch). For each, every toolchain whose build compiled ran it on the host (rebuilt and run twice: results/fuzz/c1/hostcheck.jsonl), and the sequential elision (offload.engine.expected) ran where it applies. Rule: **valid** when at least one of them prints the model's checksum; the host builds that ran and did not are `host_path_failure` records (a host-path compiler or runtime bug: out of scope, not an offload finding). **noncompliant** when none does (a generator or model defect): excluded from the findings and the tallies above. A toolchain whose build does not compile has no host build ('no host build'). Values are host checksums. Scope: only these programs had every toolchain's host build run; for the others only the reference toolchain's host run exists, so host_path_failure counts are a lower bound.

| seed | reference | ref tc | model | afar host | cce19 host | cce20 host | cce21 host | elision | validity | host_path_failure |
|---|---|---|---|---|---|---|---|---|---|---|
| 18 | host_mismatch | cce20 | 1947133868 | no build: compile_reject | no build: compile_reject | 540990624 | 540990624 | **checksum=1947133868** | valid | cce20, cce21 |
| 58 | host_mismatch | afar | 168383631 | 1873972689 | no build: compile_reject | **168383631** | **168383631** | **checksum=168383631** | valid | afar |
| 209 | host_mismatch | cce20 | 884471902 | no build: compile_reject | no build: compile_reject | 1256899722 | 1256899722 | **checksum=884471902** | valid | cce20, cce21 |
| 287 | host_mismatch | afar | 999691455 | 1046228726 | no build: compile_reject | **999691455** | **999691455** | **checksum=999691455** | valid | afar |
| 357 | host_mismatch | cce20 | 249542094 | no build: compile_reject | no build: compile_reject | 1738638814 | 1738638814 | **checksum=249542094** | valid | cce20, cce21 |
| 485 | host_mismatch | afar | 131415404 | 1033096498 | no build: compile_reject | no build: ice | no build: ice | **checksum=131415404** | valid | afar |
| 596 | host_mismatch | afar | 44478817 | 151971086 | **44478817** | **44478817** | **44478817** | **checksum=44478817** | valid | afar |
| 786 | host_mismatch | afar | 1933010909 | 2121212958 | no build: compile_reject | **1933010909** | **1933010909** | inapplicable: defaultmap(present: all); present modifier | valid | afar |
| 992 | host_mismatch | cce19 | 358113607 | no build: compile_reject | 192406149 | 192406149 | 192406149 | **checksum=358113607** | valid | cce19, cce20, cce21 |
| 1003 | host_ref_failed | cce20 | 194921215 | no build: compile_reject | no build: compile_reject | **194921215** | **194921215** | **checksum=194921215** | valid | - |
| 1177 | host_mismatch | afar | 336215922 | 237226985 | **336215922** | **336215922** | **336215922** | **checksum=336215922** | valid | afar |
| 1283 | host_mismatch | cce19 | 1052722862 | no build: compile_reject | 687738131 | 687738131 | 687738131 | **checksum=1052722862** | valid | cce19, cce20, cce21 |
| 1331 | host_mismatch | afar | 1334481655 | 1857116449 | no build: ice | no build: ice | no build: ice | **checksum=1334481655** | valid | afar |
| 1380 | host_ref_failed | afar | 1715756943 | crash: SIGABRT | **1715756943** | **1715756943** | **1715756943** | **checksum=1715756943** | valid | afar |
| 1389 | host_mismatch | afar | 1782098496 | 251894404 | **1782098496** | **1782098496** | **1782098496** | **checksum=1782098496** | valid | afar |
| 1422 | host_mismatch | cce19 | 797498111 | no build: ice | 1447434787 | 1447434787 | 1447434787 | **checksum=797498111** | valid | cce19, cce20, cce21 |
| 1425 | host_mismatch | afar | 1271099994 | 1181077584 | **1271099994** | **1271099994** | **1271099994** | **checksum=1271099994** | valid | afar |
| 1436 | host_ref_failed | afar | 2000823492 | crash: SIGABRT | **2000823492** | **2000823492** | **2000823492** | **checksum=2000823492** | valid | afar |
| 1495 | host_mismatch | cce20 | 1810118554 | no build: compile_reject | no build: compile_reject | 316168193 | no build: compile_reject | **checksum=1810118554** | valid | cce20 |
| 1525 | host_mismatch | afar | 563900162 | 421583439 | no build: compile_reject | no build: compile_reject | no build: compile_reject | inapplicable: defaultmap(present: allocatable); present modi | noncompliant | - |
| 1540 | host_mismatch | cce19 | 998705850 | no build: ice | 515100083 | 515100083 | 515100083 | **checksum=998705850** | valid | cce19, cce20, cce21 |
| 1541 | host_mismatch | afar | 1223194404 | 2072414450 | **1223194404** | **1223194404** | **1223194404** | **checksum=1223194404** | valid | afar |
| 1563 | host_ref_failed | afar | 1220461453 | crash: SIGABRT | **1220461453** | **1220461453** | **1220461453** | **checksum=1220461453** | valid | afar |
| 1586 | host_mismatch | afar | 720866614 | 754587935 | no build: compile_reject | **720866614** | **720866614** | **checksum=720866614** | valid | afar |
| 1639 | host_mismatch | afar | 231062862 | 415726394 | no build: compile_reject | no build: compile_reject | no build: compile_reject | **checksum=231062862** | valid | afar |
| 1647 | host_ref_failed | afar | 1888228640 | crash: SIGABRT | **1888228640** | **1888228640** | **1888228640** | **checksum=1888228640** | valid | afar |
| 1656 | host_ref_failed | afar | 1839159977 | crash: SIGABRT | **1839159977** | **1839159977** | no build: compile_reject | **checksum=1839159977** | valid | afar |
| 1710 | host_mismatch | afar | 361888838 | 807266488 | **361888838** | **361888838** | **361888838** | **checksum=361888838** | valid | afar |
| 1759 | host_mismatch | cce20 | 1217412315 | no build: compile_reject | no build: compile_reject | 1687905659 | 1687905659 | inapplicable: present modifier | noncompliant | - |
| 1861 | host_ref_failed | afar | 312580273 | crash: SIGABRT | no build: compile_reject | **312580273** | no build: compile_reject | **checksum=312580273** | valid | afar |
| 1978 | host_mismatch | cce19 | 2140855743 | no build: compile_reject | 0 | **2140855743** | **2140855743** | inapplicable: present modifier | valid | cce19 |
| 1980 | host_mismatch | cce20 | 698744263 | no build: compile_reject | no build: compile_reject | 16734746 | 16734746 | **checksum=698744263** | valid | cce20, cce21 |
| 1999 | host_mismatch | afar | 923052659 | 269813778 | **923052659** | **923052659** | **923052659** | **checksum=923052659** | valid | afar |
| 2046 | host_mismatch | afar | 927804830 | 2125969237 | no build: compile_reject | **927804830** | **927804830** | **checksum=927804830** | valid | afar |
| 2052 | host_ref_failed | afar | 1828371198 | crash: SIGABRT | no build: compile_reject | **1828371198** | 1464445541 | **checksum=1828371198** | valid | afar, cce21 |
| 2064 | host_mismatch | cce19 | 330584662 | no build: ice | 458897573 | 458897573 | 458897573 | **checksum=330584662** | valid | cce19, cce20, cce21 |
| 2172 | host_mismatch | afar | 1139798633 | 59710419 | no build: compile_reject | **1139798633** | **1139798633** | **checksum=1139798633** | valid | afar |
| 2206 | host_mismatch | cce19 | 1555464820 | no build: compile_reject | 1564154882 | 1564154882 | 1564154882 | **checksum=1555464820** | valid | cce19, cce20, cce21 |
| 2300 | host_mismatch | afar | 1214389803 | 1103097569 | **1214389803** | **1214389803** | **1214389803** | **checksum=1214389803** | valid | afar |
| 2301 | host_mismatch | afar | 461676588 | 1653558941 | **461676588** | **461676588** | **461676588** | **checksum=461676588** | valid | afar |
| 2345 | host_mismatch | afar | 1070654593 | 1771349253 | no build: compile_reject | no build: ice | no build: ice | **checksum=1070654593** | valid | afar |

### host_path_failure (valid programs; host-path failures, out of scope)

- afar: 26 programs (seeds 58, 287, 485, 596, 786, 1177, 1331, 1380, 1389, 1425, 1436, 1541, 1563, 1586, 1639, 1647, 1656, 1710, 1861, 1999, 2046, 2052, 2172, 2300, 2301, 2345)
- cce19: 7 programs (seeds 992, 1283, 1422, 1540, 1978, 2064, 2206)
- cce20: 11 programs (seeds 18, 209, 357, 992, 1283, 1422, 1495, 1540, 1980, 2064, 2206)
- cce21: 11 programs (seeds 18, 209, 357, 992, 1283, 1422, 1540, 1980, 2052, 2064, 2206)

### Noncompliant programs (generator/model investigation)

No available host build prints the model's checksum. Their device classes (not counted anywhere above):

- seed 1525: model 563900162; host afar 421583439, cce19 no host build: compile_reject, cce20 no host build: compile_reject, cce21 no host build: compile_reject; elision inapplicable: defaultmap(present: allocatable); present modifier; device afar agree, cce19 compile_reject, cce20 compile_reject, cce21 compile_reject
- seed 1759: model 1217412315; host afar no host build: compile_reject, cce19 no host build: compile_reject, cce20 1687905659, cce21 1687905659; elision inapplicable: present modifier; device afar compile_reject, cce19 compile_reject, cce20 run_error, cce21 run_error
