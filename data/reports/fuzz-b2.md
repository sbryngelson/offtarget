# Fuzz campaign `b2`

Csmith-style random OpenMP 5.2 Fortran offload programs (offload.engine.fuzz, generator `fuzz-3`, base-language groups: derived (offload.engine.fuzz_base)), run on every toolchain at -O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory; reference: the Python model of each program, checked against a host run (OMP_TARGET_OFFLOAD=disabled, a reference only; see the appendix 'Host reference checks' for the programs whose host run failed or disagreed). Machine-readable: results/fuzz/b2/summary.json.

## Size and timing

- programs generated: 300; legal and run: 300 (judged: 300; noncompliant, excluded from every count below: 0); generator rejects: 0; worker crashes: 0
- campaign wall time: 1027 s with 8 workers (1052 programs/hour; 26.5 s per program and worker, all toolchains and repeats included)
- programs whose device results agree with the model on every toolchain: 95

## Classes per toolchain

Rejections (compile_reject) are features a toolchain does not support, not failures. Flaky = the repeats differed (counted in the worst class).

| class | afar | cce19 | cce20 | cce21 |
|---|---|---|---|---|
| agree | 207 | 137 | 183 | 165 |
| compile_reject | 72 | 114 | 19 | 35 |
| ice | 0 | 41 | 84 | 84 |
| wrong_code | 9 | 8 (2 flaky) | 14 (2 flaky) | 16 |
| host_fallback | 0 | 0 | 0 | 0 |
| timeout | 0 | 0 | 0 | 0 |
| run_error | 12 | 0 | 0 | 0 |
| harness_error | 0 | 0 | 0 | 0 |

## Base-language features

Per base-language feature (offload.engine.fuzz_base): the programs that have it, and per toolchain agree / compile_reject / ice / wrong_code / run_error (other classes in parentheses when present).

| feature | programs | afar | cce19 | cce20 | cce21 |
|---|---|---|---|---|---|
| dt:aos | 182 | 125/44/0/5/8 | 81/73/24/4/0 | 107/13/54/8/0 | 98/21/54/9/0 |
| dt:component:aos:integer | 182 | 125/44/0/5/8 | 81/73/24/4/0 | 107/13/54/8/0 | 98/21/54/9/0 |
| dt:component:aos:real8 | 108 | 73/27/0/4/4 | 49/44/13/2/0 | 65/8/31/4/0 | 61/12/31/4/0 |
| dt:component:nested:integer | 176 | 116/49/0/6/5 | 71/73/28/4/0 | 99/16/54/7/0 | 87/28/54/7/0 |
| dt:component:nested:real8 | 105 | 70/30/0/3/2 | 41/45/18/1/0 | 58/8/36/3/0 | 52/14/36/3/0 |
| dt:component:struct:integer | 300 | 207/72/0/9/12 | 137/114/41/8/0 | 183/19/84/14/0 | 165/35/84/16/0 |
| dt:component:struct:real8 | 185 | 127/46/0/6/6 | 83/73/25/4/0 | 113/10/54/8/0 | 103/19/54/9/0 |
| dt:default_init | 122 | 82/32/0/2/6 | 63/39/17/3/0 | 76/9/32/5/0 | 68/15/32/7/0 |
| dt:map:component_section | 33 | 24/7/0/1/1 | 8/14/10/1/0 | 12/2/17/2/0 | 9/5/17/2/0 |
| dt:map:components | 109 | 73/30/0/2/4 | 40/46/18/5/0 | 54/9/37/9/0 | 48/15/37/9/0 |
| dt:map:implicit | 168 | 117/40/0/5/6 | 78/66/22/2/0 | 103/9/52/4/0 | 93/17/52/6/0 |
| dt:map:mod:always | 27 | 20/5/0/2/0 | 10/11/6/0/0 | 12/0/14/1/0 | 8/3/14/2/0 |
| dt:map:mod:close | 26 | 17/7/0/1/1 | 11/9/6/0/0 | 16/2/7/1/0 | 13/5/7/1/0 |
| dt:map:mod:present | 22 | 13/6/0/0/3 | 5/12/4/1/0 | 10/3/7/2/0 | 7/6/7/2/0 |
| dt:map:whole | 123 | 84/27/0/5/7 | 56/45/19/3/0 | 73/8/36/6/0 | 64/16/36/7/0 |
| dt:nested | 176 | 116/49/0/6/5 | 71/73/28/4/0 | 99/16/54/7/0 | 87/28/54/7/0 |
| dt:out:dr | 58 | 44/13/0/0/1 | 27/19/11/1/0 | 34/4/18/2/0 | 30/7/18/3/0 |
| dt:out:dr%nd | 27 | 19/7/0/1/0 | 11/11/4/1/0 | 14/4/8/1/0 | 9/9/8/1/0 |
| dt:out:ds | 30 | 20/6/0/3/1 | 19/10/0/1/0 | 21/2/5/2/0 | 20/3/5/2/0 |
| dt:scalar_component | 199 | 133/50/0/6/10 | 93/76/26/4/0 | 119/17/57/6/0 | 109/25/57/8/0 |
| dt:struct | 300 | 207/72/0/9/12 | 137/114/41/8/0 | 183/19/84/14/0 | 165/35/84/16/0 |
| dt:target_update_component | 21 | 14/7/0/0/0 | 5/12/3/1/0 | 9/3/8/1/0 | 7/5/8/1/0 |
| out:real8 | 22 | 12/9/0/1/0 | 8/10/3/1/0 | 8/4/9/1/0 | 7/5/9/1/0 |
| view:real8 | 159 | 106/42/0/6/5 | 66/66/23/4/0 | 89/10/52/8/0 | 81/17/52/9/0 |

## Known findings rediscovered

- cce19-target-parallel-guarded-loop (wrong code on cce19 in a program with a thread-0-guarded sequential loop in target parallel): 5 programs (seeds 20, 44, 157, 275, 286)
- cce21-defaultmap-aggregate-flag (wrong code or host fallback on cce21 where cce20 agrees, in a program with a defaultmap clause; the finding's symptom: a map(tofrom) scalar is not copied back): 3 programs (seeds 67, 219, 277)
- (control for the line above: the same without a defaultmap clause): 0 programs (seeds )
- cce21-in-reduction-taskwait-link (cce21 link failure on _cray$mt_taskwait): 16 programs (seeds 21, 25, 33, 42, 43, 52, 61, 69, 142, 178, 184, 197)
- cce19-target-parallel-single-ice / task ICE (CCE 'unhandled construct type'): 69 programs (seeds 1, 11, 32, 34, 38, 40, 48, 51, 54, 56, 60, 62)

## Distinct minimized failures

| file | toolchain | kind | also fails on | lines | expected | observed |
|---|---|---|---|---|---|---|
| `data/findings/fuzz/b2-85-cce20.f90` | cce20 | wrong_code | cce19, cce21 | 63 -> 39 | the host reference checksum (host reference (afar) checksum=1901273453) | device checksum=0 ran_on_host=0 |
| `data/findings/fuzz/b2-52-afar.f90` | afar | wrong_code | - | 127 -> 43 | the host reference checksum (host reference (cce19) checksum=1272193681) | device checksum=2115128177 ran_on_host=0 |
| `data/findings/fuzz/b2-213-afar.f90` | afar | run_error | - | 98 -> 49 | runs to completion (the host run does) | device: fail crash: SIGABRT; host reference (cce19) checksum=797202134 |
| `data/findings/fuzz/b2-68-afar.f90` | afar | wrong_code | - | 107 -> 31 | the host reference checksum (host reference (cce19) checksum=17631) | device checksum=70431 ran_on_host=0 |
| `data/findings/fuzz/b2-209-cce19.f90` | cce19 | wrong_code | cce20, cce21 | 86 -> 27 | the host reference checksum (host reference (elision) checksum=16) | device checksum=0 ran_on_host=0 |

## Wrong code (all programs)

- afar: 9 programs (seeds 48, 52, 68, 80, 87, 91, 95, 247, 294)
- cce19: 8 programs (seeds 20, 27, 44, 85, 157, 209, 275, 286)
- cce20: 14 programs (seeds 16, 20, 22, 44, 70, 85, 104, 131, 157, 198, 209, 275, 286, 291)
- cce21: 16 programs (seeds 16, 20, 22, 44, 67, 70, 85, 104, 131, 157, 209, 219, 275, 277, 286, 291)

## Internal compiler errors (deduplicated by message)

| toolchain | programs | message | seeds |
|---|---|---|---|
| cce20 | 46 | ice: INTERNAL COMPILER ERROR: "unhandled acc construct type" (v_openmp.c, line 7881, version <v>) | 11, 32, 34, 38, 48 |
| cce21 | 46 | ice: INTERNAL COMPILER ERROR: "unhandled acc construct type" (v_openmp.c, line 8265, version <v>) | 11, 32, 34, 38, 48 |
| cce19 | 34 | ice: INTERNAL COMPILER ERROR: "unhandled construct type" (v_openmp.c, line 7617, version <v>) | 1, 38, 51, 54, 56 |
| cce20 | 23 | ice: INTERNAL COMPILER ERROR: "unhandled construct type" (v_openmp.c, line 7814, version <v>) | 1, 40, 56, 62, 71 |
| cce21 | 23 | ice: INTERNAL COMPILER ERROR: "unhandled construct type" (v_openmp.c, line 8197, version <v>) | 1, 40, 56, 62, 71 |
| cce20 | 14 | ice: INTERNAL COMPILER ERROR: "ACC - barrier/reset/protected last private not supported" (v_mt_translate.c, line 5607, version <v>) | 6, 26, 31, 115, 152 |
| cce21 | 14 | ice: INTERNAL COMPILER ERROR: "ACC - barrier/reset/protected last private not supported" (v_mt_translate.c, line 5798, version <v>) | 6, 26, 31, 115, 152 |
| cce19 | 7 | ice: INTERNAL COMPILER ERROR: "ACC - barrier/reset/protected last private not supported" (v_mt_translate.c, line 4874, version <v>) | 31, 159, 187, 242, 248 |
| cce20 | 1 | ice: INTERNAL COMPILER ERROR: "Couldn't find an atomic update statement" (v_mt_translate_atomic.c, line 1703, version <v>) | 259 |
| cce21 | 1 | ice: INTERNAL COMPILER ERROR: "Couldn't find an atomic update statement" (v_mt_translate_atomic.c, line 1702, version <v>) | 259 |

## Run errors, timeouts, host fallbacks

| toolchain | class | programs | reason | seeds |
|---|---|---|---|---|
| afar | run_error | 11 | crash: SIGABRT; without mandatory: crash: SIGABRT | 35, 66, 121, 176, 182 |
| afar | run_error | 1 | mandatory_failed_device_pass_without: crash: SIGABRT; without mandatory: ran_on_host=0 | 231 |

## Features and feature pairs most associated with failures

Among programs the toolchain compiled (or crashed on). Lift = the rate of the class among programs with the feature (pair) over the toolchain's overall rate; a pair is listed only when it beats both of its features alone by 25%.

### afar: wrong_code

Single features: clause:default:none (6/25, lift 6.08); split:target | teams | distribute | parallel | do simd (3/16, lift 4.75); clause:default:shared (3/23, lift 3.3); split:target | parallel | loop (3/23, lift 3.3); base:dt:out:ds (3/24, lift 3.17); dir:do simd (3/24, lift 3.17); chain:target teams distribute parallel do (3/25, lift 3.04); chain:target parallel do (3/27, lift 2.81)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| clause:default:none + decl:explicit_rank2 | 18 | 6 | 0.333 | 0.24 | 8.44 |
| clause:default:none + dir:distribute | 15 | 5 | 0.333 | 0.24 | 8.44 |
| clause:default:none + dir:parallel | 19 | 6 | 0.316 | 0.24 | 8.0 |
| base:dt:component:nested:integer + clause:default:none | 16 | 5 | 0.312 | 0.24 | 7.92 |
| base:dt:nested + clause:default:none | 16 | 5 | 0.312 | 0.24 | 7.92 |
| clause:default:none + dir:teams | 16 | 5 | 0.312 | 0.24 | 7.92 |
| clause:default:none + loop:down | 16 | 5 | 0.312 | 0.24 | 7.92 |
| clause:schedule + loop:down | 19 | 4 | 0.211 | 0.108 | 5.33 |

### afar: run_error

Single features: split:target | teams | distribute | parallel | do simd (4/16, lift 4.75); base:dt:map:mod:present (3/16, lift 3.56); map:mod:present (5/30, lift 3.17); dir:do simd (4/24, lift 3.17); red:clause:iand (4/24, lift 3.17); chain:target teams distribute parallel do (4/25, lift 3.04); red:clause:min (3/20, lift 2.85); clause:schedule (5/37, lift 2.57)

| feature pair | programs | run_error | rate | best single rate | lift |
|---|---|---|---|---|---|
| dir:teams + red:clause | 25 | 8 | 0.32 | 0.117 | 6.08 |
| dir:distribute + red:clause | 29 | 8 | 0.276 | 0.121 | 5.24 |
| base:dt:map:whole + chain:target teams distribute parallel do simd | 15 | 4 | 0.267 | 0.133 | 5.07 |
| base:dt:map:whole + red:clause:iand | 15 | 4 | 0.267 | 0.167 | 5.07 |
| red:clause + wrap:enter_exit_data | 15 | 4 | 0.267 | 0.113 | 5.07 |
| clause:schedule + declare_target_function | 20 | 5 | 0.25 | 0.135 | 4.75 |
| map:mod:present + map:to | 20 | 5 | 0.25 | 0.167 | 4.75 |
| dir:distribute + dir:do simd | 16 | 4 | 0.25 | 0.167 | 4.75 |

### cce19: wrong_code

Single features: kernel:guard (5/34, lift 3.42); chain:target teams distribute (3/21, lift 3.32); clause:lastprivate (4/35, lift 2.66); map:section (5/58, lift 2.0); base:dt:map:components (5/63, lift 1.85); dir:target parallel (3/43, lift 1.62); body:temp (4/59, lift 1.58); dir:distribute (4/59, lift 1.58)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| clause:lastprivate + decl:explicit_rank2 | 20 | 4 | 0.2 | 0.114 | 4.65 |
| kernel:guard + kernel:loop | 20 | 4 | 0.2 | 0.147 | 4.65 |
| kernel:guard + map:tofrom | 26 | 5 | 0.192 | 0.147 | 4.47 |
| base:dt:component:nested:integer + kernel:guard | 16 | 3 | 0.188 | 0.147 | 4.36 |
| base:dt:nested + kernel:guard | 16 | 3 | 0.188 | 0.147 | 4.36 |
| decl:explicit_rank2 + kernel:guard | 16 | 3 | 0.188 | 0.147 | 4.36 |
| clause:lastprivate + dir:distribute | 18 | 3 | 0.167 | 0.114 | 3.87 |
| clause:lastprivate + declare_target_function | 19 | 3 | 0.158 | 0.114 | 3.67 |

### cce19: ice

Single features: kernel:phase (26/26, lift 4.54); phase:do (23/23, lift 4.54); phase:single (16/16, lift 4.54); phase:loop (15/15, lift 4.54); dir:target parallel (29/43, lift 3.06); base:dt:map:component_section (10/19, lift 2.39); clause:proc_bind (10/19, lift 2.39); scalar:tofrom (10/20, lift 2.27)

| feature pair | programs | ice | rate | best single rate | lift |
|---|---|---|---|---|---|
| body:call_declare_target + dir:target parallel | 16 | 14 | 0.875 | 0.674 | 3.97 |
| base:dt:component:nested:real8 + body:call_declare_target | 15 | 8 | 0.533 | 0.321 | 2.42 |
| clause:lastprivate + dir:parallel | 17 | 9 | 0.529 | 0.314 | 2.4 |
| body:call_declare_target + loop:down | 20 | 10 | 0.5 | 0.321 | 2.27 |
| body:call_declare_target + map:from | 21 | 10 | 0.476 | 0.321 | 2.16 |
| body:call_declare_target + map:mod:close | 19 | 9 | 0.474 | 0.321 | 2.15 |
| base:dt:map:whole + chain:target parallel loop | 17 | 8 | 0.471 | 0.321 | 2.13 |
| base:dt:map:components + body:call_declare_target | 15 | 7 | 0.467 | 0.321 | 2.12 |

### cce20: wrong_code

Single features: guard:par_thread0 (7/16, lift 8.78); red:atomic (5/21, lift 4.78); kernel:guard (11/63, lift 3.5); chain:target parallel do (5/46, lift 2.18); chain:target teams distribute (4/38, lift 2.11); scalar:to (4/38, lift 2.11); clause:lastprivate (6/62, lift 1.94); dir:target parallel (8/84, lift 1.91)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| decl:allocatable_rank2 + red:atomic | 15 | 5 | 0.333 | 0.238 | 6.69 |
| dir:distribute + kernel:guard | 17 | 5 | 0.294 | 0.175 | 5.9 |
| kernel:guard + map:mod:always | 20 | 5 | 0.25 | 0.175 | 5.02 |
| kernel:guard + map:section | 21 | 5 | 0.238 | 0.175 | 4.78 |
| body:temp + kernel:guard | 22 | 5 | 0.227 | 0.175 | 4.56 |
| chain:target parallel do + dir:target parallel | 19 | 4 | 0.211 | 0.109 | 4.23 |
| dir:distribute + dir:target teams | 19 | 4 | 0.211 | 0.091 | 4.23 |
| dir:distribute + dir:target parallel | 25 | 5 | 0.2 | 0.095 | 4.01 |

### cce20: ice

Single features: kernel:phase (48/48, lift 3.35); phase:do (43/43, lift 3.35); phase:single (29/29, lift 3.35); phase:do simd (24/24, lift 3.35); phase:masked (24/24, lift 3.35); phase:nowait_barrier (22/22, lift 3.35); phase:loop (20/20, lift 3.35); map:alloc (19/19, lift 3.35)

| feature pair | programs | ice | rate | best single rate | lift |
|---|---|---|---|---|---|
| base:dt:map:component_section + map:from | 15 | 11 | 0.733 | 0.548 | 2.45 |
| base:dt:map:mod:always + declare_target_function | 15 | 10 | 0.667 | 0.519 | 2.23 |
| clause:num_threads + map:mod:always | 21 | 13 | 0.619 | 0.46 | 2.07 |
| map:from + wrap:host_update_to | 15 | 9 | 0.6 | 0.412 | 2.01 |
| base:dt:out:dr + kernel:guard | 17 | 10 | 0.588 | 0.429 | 1.97 |
| base:dt:component:nested:real8 + clause:num_threads | 19 | 11 | 0.579 | 0.46 | 1.94 |
| base:view:real8 + map:mod:present | 19 | 11 | 0.579 | 0.385 | 1.94 |
| base:view:real8 + clause:if:target | 26 | 15 | 0.577 | 0.356 | 1.93 |

### cce21: wrong_code

Single features: kernel:guard (13/59, lift 3.65); red:atomic (4/19, lift 3.49); defaultmap:tofrom:all (3/15, lift 3.31); dir:target teams (6/41, lift 2.42); scalar:to (5/37, lift 2.24); chain:target teams distribute (4/33, lift 2.01); scalar:tofrom (4/33, lift 2.01); chain:target parallel do (5/42, lift 1.97)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| kernel:guard + map:section | 20 | 6 | 0.3 | 0.22 | 4.97 |
| body:temp + kernel:guard | 21 | 6 | 0.286 | 0.22 | 4.73 |
| dir:target teams + map:section | 17 | 4 | 0.235 | 0.146 | 3.9 |
| chain:target parallel do + map:from | 18 | 4 | 0.222 | 0.119 | 3.68 |
| chain:target parallel do + dir:target parallel | 19 | 4 | 0.211 | 0.119 | 3.49 |
| base:dt:map:components + chain:target parallel do | 20 | 4 | 0.2 | 0.119 | 3.31 |
| base:dt:map:whole + dir:target teams | 15 | 3 | 0.2 | 0.146 | 3.31 |
| chain:target parallel do + scalar:implicit | 15 | 3 | 0.2 | 0.119 | 3.31 |

### cce21: ice

Single features: kernel:phase (48/48, lift 3.15); phase:do (43/43, lift 3.15); phase:single (29/29, lift 3.15); phase:do simd (24/24, lift 3.15); phase:masked (24/24, lift 3.15); phase:nowait_barrier (22/22, lift 3.15); phase:loop (20/20, lift 3.15); map:alloc (19/19, lift 3.15)

| feature pair | programs | ice | rate | best single rate | lift |
|---|---|---|---|---|---|
| clause:num_threads + map:mod:always | 19 | 13 | 0.684 | 0.492 | 2.16 |
| base:dt:out:dr + kernel:guard | 15 | 10 | 0.667 | 0.458 | 2.1 |
| clause:num_threads + map:mod:close | 23 | 15 | 0.652 | 0.492 | 2.06 |
| base:dt:component:nested:real8 + clause:num_threads | 17 | 11 | 0.647 | 0.492 | 2.04 |
| clause:num_threads + map:from | 27 | 17 | 0.63 | 0.492 | 1.99 |
| base:view:real8 + clause:if:target | 25 | 15 | 0.6 | 0.375 | 1.89 |
| map:from + wrap:host_update_to | 15 | 9 | 0.6 | 0.448 | 1.89 |
| base:dt:component:struct:real8 + split:target \| parallel \| do | 17 | 10 | 0.588 | 0.4 | 1.86 |

## Compile rejections (features not supported)

### afar

| programs | message |
|---|---|
| 41 | not_implemented: error: loc("<path> <path> not yet implemented: lastprivate clause in constructs other than simd/worksharing-loop/taskloop |
| 18 | not_implemented: loc("<path> error: not yet implemented: Unhandled clause order in omp.wsloop operation |
| 7 | not_implemented: error: loc("<path> <path> not yet implemented: Firstprivate is currently unsupported defaultmap behaviour |
| 4 | not_implemented: error: loc("<path> <path> not yet implemented: lastprivate(conditional:) on simd construct |
| 2 | not_implemented: loc("<path> error: not yet implemented: Unhandled clause order in omp.distribute operation |

Features most associated with rejection: clause:order (30/30); clause:lastprivate (47/72); split:target | teams | distribute | parallel | do (17/30); split:target | teams | distribute (18/32); split:target | parallel | do (14/27); chain:target teams distribute (24/48); split:target | teams | distribute | parallel | do simd (15/31); red:clause:ieor (12/25)

### cce19

| programs | message |
|---|---|
| 46 | diagnostic: ftn-1370 ftn: ERROR , \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET. |
| 31 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : "scalar, aggregate, allocatable or pointer" was expected but found ")". |
| 17 | diagnostic: ftn-1370 ftn: ERROR , \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET PARALLEL. |
| 6 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 4 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP DISTRIBUTE. |
| 4 | diagnostic: ftn-1370 ftn: ERROR , \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET SIMD. |
| 2 | diagnostic: ftn-1370 ftn: ERROR , \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET PARALLEL LOOP. |
| 1 | diagnostic: ftn-1510 ftn: ERROR , \| Variable "LPAR" must have its data scope explicitly declared because DEFAULT(NONE) was specified. |
| 1 | diagnostic: ftn-1964 ftn: ERROR , \| Variable "O3" must have its data mapping attribute explicitly declared because default map(none) was specified. |
| 1 | diagnostic: ftn-1964 ftn: ERROR , \| Variable "O1" must have its data mapping attribute explicitly declared because default map(none) was specified. |
| 1 | diagnostic: ftn-1964 ftn: ERROR , \| Variable "DR" must have its data mapping attribute explicitly declared because default map(none) was specified. |

Features most associated with rejection: defaultmap:tofrom:all (19/19); clause:thread_limit (82/100); split:target | teams | distribute (19/32); phase:do simd (15/26); base:dt:target_update_component (12/21); clause:order (17/30); split:target | teams | distribute | parallel | do (17/30); chain:target teams distribute (27/48)

### cce20

| programs | message |
|---|---|
| 10 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 7 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP DISTRIBUTE. |
| 1 | diagnostic: ftn-1510 ftn: ERROR , \| Variable "LPAR" must have its data scope explicitly declared because DEFAULT(NONE) was specified. |
| 1 | diagnostic: ftn-1964 ftn: ERROR , \| Variable "DR" must have its data mapping attribute explicitly declared because default map(none) was specified. |

Features most associated with rejection: clause:order (8/30); split:target | teams | distribute (8/32); clause:num_teams (11/50); defaultmap:tofrom:all (4/19); chain:target teams distribute (10/48); split:target | teams | distribute | parallel | do (6/30); guard:par_thread0 (4/20); wrap:host_update_to (8/41)

### cce21

| programs | message |
|---|---|
| 16 | link_undefined_symbol: lld: error: undefined symbol: _cray$mt_taskwait |
| 10 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 7 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP DISTRIBUTE. |
| 1 | diagnostic: ftn-1510 ftn: ERROR , \| Variable "LPAR" must have its data scope explicitly declared because DEFAULT(NONE) was specified. |
| 1 | diagnostic: ftn-1964 ftn: ERROR , \| Variable "DR" must have its data mapping attribute explicitly declared because default map(none) was specified. |

Features most associated with rejection: red:in_reduction:+ (10/18); clause:in_reduction (20/38); dir:taskgroup (20/38); kernel:inred (20/38); red:in_reduction:* (11/21); split:target | teams | distribute (11/32); clause:order (10/30); base:dt:out:dr%nd (9/27)

## Generator rejects

Programs failing a legality check are never run. Causes (`rules`: a 5.2 rule of offload.engine.rules fired, a generator or rule bug; `flang`: AFAR flang's frontend refused a program the rules and gfortran accept; see the report for which of these are flang's errors):

| count | cause | seeds |
|---|---|---|

## Flaky results

- seed 104 cce20: wrong_code: checksum=216725149 ran_on_host=0 expected=636539060 | wrong_code: checksum=216725149 ran_on_host=0 expected=636539060 | wrong_code: checksum=216725149 ran_on_host=0 expected=636539060 | wrong_code: checksum=2054769593 ran_on_host=0 expected=636539060
- seed 157 cce19: wrong_code: checksum=711869864 ran_on_host=0 expected=888858704 | wrong_code: checksum=132944151 ran_on_host=0 expected=888858704 | wrong_code: checksum=662197283 ran_on_host=0 expected=888858704 | wrong_code: checksum=78992502 ran_on_host=0 expected=888858704
- seed 286 cce19: wrong_code: checksum=2020901877 ran_on_host=0 expected=1922605397 | wrong_code: checksum=886259536 ran_on_host=0 expected=1922605397 | wrong_code: checksum=1938799031 ran_on_host=0 expected=1922605397 | wrong_code: checksum=1736559003 ran_on_host=0 expected=1922605397
- seed 286 cce20: wrong_code: checksum=467941113 ran_on_host=0 expected=1922605397 | wrong_code: checksum=2086858452 ran_on_host=0 expected=1922605397 | wrong_code: checksum=467941113 ran_on_host=0 expected=1922605397 | wrong_code: checksum=467941113 ran_on_host=0 expected=1922605397

## Appendix: host reference checks (not offload findings)

Device offload only: host runs (OMP_TARGET_OFFLOAD=disabled) and the sequential elision are references for the expected value, never measurements of a toolchain. A host_path_failure below is recorded data (results/fuzz/<run>/summary.json), not an offload finding, and it counts nowhere in the tables above.

The reference host run (OMP_TARGET_OFFLOAD=disabled, the first toolchain that compiled) failed for 1 programs (host_ref_failed) and printed another checksum than the model for 5 (host_mismatch). For each, every toolchain whose build compiled ran it on the host (rebuilt and run twice: results/fuzz/b2/hostcheck.jsonl), and the sequential elision (offload.engine.expected) ran where it applies. Rule: **valid** when at least one of them prints the model's checksum; the host builds that ran and did not are `host_path_failure` records (a host-path compiler or runtime bug: out of scope, not an offload finding). **noncompliant** when none does (a generator or model defect): excluded from the findings and the tallies above. A toolchain whose build does not compile has no host build ('no host build'). Values are host checksums. Scope: only these programs had every toolchain's host build run; for the others only the reference toolchain's host run exists, so host_path_failure counts are a lower bound.

| seed | reference | ref tc | model | afar host | cce19 host | cce20 host | cce21 host | elision | validity | host_path_failure |
|---|---|---|---|---|---|---|---|---|---|---|
| 18 | host_mismatch | afar | 2034078344 | 1504685184 | no build: compile_reject | **2034078344** | **2034078344** | **checksum=2034078344** | valid | afar |
| 27 | host_mismatch | cce19 | 222348608 | no build: compile_reject | 1261610837 | **222348608** | **222348608** | **checksum=222348608** | valid | cce19 |
| 73 | host_ref_failed | cce19 | 2012453265 | no build: compile_reject | exit_status: 1 | exit_status: 1 | exit_status: 1 | **checksum=2012453265** | valid | cce19, cce20, cce21 |
| 207 | host_mismatch | afar | 1846108214 | 859306340 | no build: compile_reject | **1846108214** | **1846108214** | **checksum=1846108214** | valid | afar |
| 209 | host_mismatch | cce19 | 1017055151 | no build: compile_reject | 1191221733 | 1191221733 | 1191221733 | **checksum=1017055151** | valid | cce19, cce20, cce21 |
| 246 | host_mismatch | afar | 1396416713 | 748746061 | **1396416713** | **1396416713** | **1396416713** | **checksum=1396416713** | valid | afar |

### host_path_failure (valid programs; host-path failures, out of scope)

- afar: 3 programs (seeds 18, 207, 246)
- cce19: 3 programs (seeds 27, 73, 209)
- cce20: 2 programs (seeds 73, 209)
- cce21: 2 programs (seeds 73, 209)

### Noncompliant programs (generator/model investigation)

(none)
