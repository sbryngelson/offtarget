# Fuzz campaign `b0`

Csmith-style random OpenMP 5.2 Fortran offload programs (offload.engine.fuzz, generator `fuzz-3`), run on every toolchain at -O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory; reference: the Python model of each program, checked against a host run (OMP_TARGET_OFFLOAD=disabled, a reference only; see the appendix 'Host reference checks' for the programs whose host run failed or disagreed). Machine-readable: results/fuzz/b0/summary.json.

## Size and timing

- programs generated: 300; legal and run: 300 (judged: 300; noncompliant, excluded from every count below: 0); generator rejects: 0; worker crashes: 0
- campaign wall time: 2427 s with 7 workers (445 programs/hour; 56.2 s per program and worker, all toolchains and repeats included)
- programs whose device results agree with the model on every toolchain: 76

## Classes per toolchain

Rejections (compile_reject) are features a toolchain does not support, not failures. Flaky = the repeats differed (counted in the worst class).

| class | afar | cce19 | cce20 | cce21 |
|---|---|---|---|---|
| agree | 202 | 114 | 174 | 155 |
| compile_reject | 80 | 125 | 20 | 37 |
| ice | 0 | 51 | 85 | 85 |
| wrong_code | 8 | 10 (3 flaky) | 21 (2 flaky) | 23 (1 flaky) |
| host_fallback | 0 | 0 | 0 | 0 |
| timeout | 0 | 0 | 0 | 0 |
| run_error | 10 | 0 | 0 | 0 |
| harness_error | 0 | 0 | 0 | 0 |

## Known findings rediscovered

- cce19-target-parallel-guarded-loop (wrong code on cce19 in a program with a thread-0-guarded sequential loop in target parallel): 8 programs (seeds 13, 20, 42, 60, 131, 234, 249, 275)
- cce21-defaultmap-aggregate-flag (wrong code or host fallback on cce21 where cce20 agrees, in a program with a defaultmap clause; the finding's symptom: a map(tofrom) scalar is not copied back): 5 programs (seeds 28, 67, 102, 157, 233)
- (control for the line above: the same without a defaultmap clause): 0 programs (seeds )
- cce21-in-reduction-taskwait-link (cce21 link failure on _cray$mt_taskwait): 17 programs (seeds 25, 33, 34, 42, 52, 72, 88, 142, 184, 197, 198, 202)
- cce19-target-parallel-single-ice / task ICE (CCE 'unhandled construct type'): 67 programs (seeds 1, 2, 11, 32, 38, 40, 51, 54, 56, 59, 62, 64)

## Distinct minimized failures

(none minimized yet)

## Wrong code (all programs)

- afar: 8 programs (seeds 11, 87, 121, 171, 193, 226, 261, 268)
- cce19: 10 programs (seeds 13, 14, 20, 42, 60, 98, 131, 234, 249, 275)
- cce20: 21 programs (seeds 13, 14, 16, 18, 20, 21, 22, 25, 34, 42, 60, 70, 106, 131, 163, 209, 234, 241, 249, 264)
- cce21: 23 programs (seeds 13, 14, 16, 18, 20, 21, 22, 28, 60, 67, 70, 102, 106, 131, 157, 163, 209, 233, 234, 241)

## Internal compiler errors (deduplicated by message)

| toolchain | programs | message | seeds |
|---|---|---|---|
| cce20 | 40 | ice: INTERNAL COMPILER ERROR: "unhandled acc construct type" (v_openmp.c, line 7881, version <v>) | 2, 38, 40, 54, 59 |
| cce21 | 40 | ice: INTERNAL COMPILER ERROR: "unhandled acc construct type" (v_openmp.c, line 8265, version <v>) | 2, 38, 40, 54, 59 |
| cce19 | 39 | ice: INTERNAL COMPILER ERROR: "unhandled construct type" (v_openmp.c, line 7617, version <v>) | 2, 11, 32, 51, 56 |
| cce20 | 26 | ice: INTERNAL COMPILER ERROR: "unhandled construct type" (v_openmp.c, line 7814, version <v>) | 1, 11, 32, 51, 56 |
| cce21 | 26 | ice: INTERNAL COMPILER ERROR: "unhandled construct type" (v_openmp.c, line 8197, version <v>) | 1, 11, 32, 51, 56 |
| cce20 | 16 | ice: INTERNAL COMPILER ERROR: "ACC - barrier/reset/protected last private not supported" (v_mt_translate.c, line 5607, version <v>) | 31, 78, 100, 115, 134 |
| cce21 | 16 | ice: INTERNAL COMPILER ERROR: "ACC - barrier/reset/protected last private not supported" (v_mt_translate.c, line 5798, version <v>) | 31, 78, 100, 115, 134 |
| cce19 | 10 | ice: INTERNAL COMPILER ERROR: "ACC - barrier/reset/protected last private not supported" (v_mt_translate.c, line 4874, version <v>) | 31, 78, 100, 134, 136 |
| cce19 | 1 | ice: INTERNAL COMPILER ERROR: "Couldn't find an atomic update statement" (v_mt_translate_atomic.c, line 1703, version <v>) | 259 |
| cce19 | 1 | ice: INTERNAL COMPILER ERROR: "unhandled operator | 165 |
| cce20 | 1 | ice: INTERNAL COMPILER ERROR: "Couldn't find an atomic update statement" (v_mt_translate_atomic.c, line 1703, version <v>) | 259 |
| cce20 | 1 | ice: INTERNAL COMPILER ERROR: "Mismatched last induction expression for last private operators" (v_mt_translate.c, line 901, version <v>) | 166 |
| cce20 | 1 | ice: INTERNAL COMPILER ERROR: "unhandled operator | 165 |
| cce21 | 1 | ice: INTERNAL COMPILER ERROR: "Couldn't find an atomic update statement" (v_mt_translate_atomic.c, line 1702, version <v>) | 259 |
| cce21 | 1 | ice: INTERNAL COMPILER ERROR: "Mismatched last induction expression for last private operators" (v_mt_translate.c, line 911, version <v>) | 166 |
| cce21 | 1 | ice: INTERNAL COMPILER ERROR: "unhandled operator | 165 |

## Run errors, timeouts, host fallbacks

| toolchain | class | programs | reason | seeds |
|---|---|---|---|---|
| afar | run_error | 10 | crash: SIGABRT; without mandatory: crash: SIGABRT | 33, 35, 91, 115, 158 |

## Features and feature pairs most associated with failures

Among programs the toolchain compiled (or crashed on). Lift = the rate of the class among programs with the feature (pair) over the toolchain's overall rate; a pair is listed only when it beats both of its features alone by 25%.

### afar: wrong_code

Single features: split:target | teams | distribute | parallel | do simd (4/20, lift 5.5); clause:default:none (6/31, lift 5.32); dir:do simd (4/23, lift 4.78); clause:schedule (6/35, lift 4.71); split:target | teams | distribute | parallel | do (3/20, lift 4.12); red:clause:ieor (3/21, lift 3.93); chain:target teams distribute parallel do simd (4/30, lift 3.67); red:clause:min (3/26, lift 3.17)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| clause:default:none + red:clause | 15 | 5 | 0.333 | 0.194 | 9.17 |
| clause:schedule + red:clause | 16 | 5 | 0.312 | 0.171 | 8.59 |
| clause:default:none + dir:distribute | 21 | 6 | 0.286 | 0.194 | 7.86 |
| clause:schedule + dir:distribute | 18 | 5 | 0.278 | 0.171 | 7.64 |
| clause:default:none + dir:parallel | 22 | 6 | 0.273 | 0.194 | 7.5 |
| clause:default:none + dir:teams | 22 | 6 | 0.273 | 0.194 | 7.5 |
| clause:default:none + loop:step2 | 15 | 4 | 0.267 | 0.194 | 7.33 |
| clause:schedule + dir:teams | 19 | 5 | 0.263 | 0.171 | 7.24 |

### afar: run_error

Single features: map:mod:present (9/30, lift 6.6); split:target | simd (4/20, lift 4.4); clause:lastprivate (3/16, lift 4.12); wrap:enter_exit_data (6/40, lift 3.3); map:mod:close (9/61, lift 3.25); chain:target simd (5/34, lift 3.24); clause:default:none (4/31, lift 2.84); wrap:host_update_to (4/31, lift 2.84)

| feature pair | programs | run_error | rate | best single rate | lift |
|---|---|---|---|---|---|
| dir:parallel + map:mod:present | 15 | 6 | 0.4 | 0.3 | 8.8 |
| map:mod:present + wrap:enter_exit_data | 15 | 6 | 0.4 | 0.3 | 8.8 |
| map:implicit + map:mod:present | 23 | 9 | 0.391 | 0.3 | 8.61 |
| map:mod:present + map:to | 21 | 8 | 0.381 | 0.3 | 8.38 |
| clause:safelen + map:mod:close | 15 | 5 | 0.333 | 0.148 | 7.33 |
| clause:thread_limit + map:mod:close | 16 | 5 | 0.312 | 0.148 | 6.88 |
| dir:parallel + wrap:enter_exit_data | 18 | 5 | 0.278 | 0.15 | 6.11 |
| clause:collapse + map:mod:close | 16 | 4 | 0.25 | 0.148 | 5.5 |

### cce19: wrong_code

Single features: kernel:guard (8/32, lift 4.38); scalar:implied_tofrom (3/20, lift 2.62); dir:target teams (4/27, lift 2.59); body:inner_seq_loop (4/33, lift 2.12); clause:lastprivate (5/44, lift 1.99); tasking:nowait_depend (3/27, lift 1.94); scalar:implicit (6/56, lift 1.88); chain:target teams distribute parallel do simd (3/31, lift 1.69)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| kernel:guard + map:from | 17 | 6 | 0.353 | 0.25 | 6.18 |
| dir:target + kernel:guard | 20 | 7 | 0.35 | 0.25 | 6.12 |
| kernel:guard + map:to | 24 | 8 | 0.333 | 0.25 | 5.83 |
| clause:lastprivate + scalar:implicit | 17 | 4 | 0.235 | 0.114 | 4.12 |
| dir:target parallel + map:mod:always | 17 | 4 | 0.235 | 0.089 | 4.12 |
| dir:target teams + map:to | 20 | 4 | 0.2 | 0.148 | 3.5 |
| clause:schedule + scalar:implicit | 15 | 3 | 0.2 | 0.107 | 3.5 |
| map:from + tasking:nowait_depend | 15 | 3 | 0.2 | 0.111 | 3.5 |

### cce19: ice

Single features: kernel:phase (29/29, lift 3.43); phase:do (27/27, lift 3.43); phase:do simd (19/19, lift 3.43); phase:nowait_barrier (18/18, lift 3.43); phase:masked (16/16, lift 3.43); phase:single (16/16, lift 3.43); dir:target parallel (34/45, lift 2.59); clause:dist_schedule (13/24, lift 1.86)

| feature pair | programs | ice | rate | best single rate | lift |
|---|---|---|---|---|---|
| clause:lastprivate + dir:parallel | 23 | 16 | 0.696 | 0.455 | 2.39 |
| clause:num_threads + map:from | 22 | 14 | 0.636 | 0.486 | 2.18 |
| clause:device + dir:parallel | 16 | 10 | 0.625 | 0.452 | 2.14 |
| clause:lastprivate + dir:do | 16 | 10 | 0.625 | 0.455 | 2.14 |
| chain:target simd + map:from | 15 | 8 | 0.533 | 0.41 | 1.83 |
| clause:shared + dir:teams | 15 | 8 | 0.533 | 0.31 | 1.83 |
| decl:explicit_rank2 + scalar:firstprivate | 15 | 8 | 0.533 | 0.407 | 1.83 |
| decl:explicit_rank2 + tasking:nowait_depend | 15 | 8 | 0.533 | 0.407 | 1.83 |

### cce20: wrong_code

Single features: guard:par_thread0 (12/21, lift 7.62); defaultmap:tofrom:allocatable (5/17, lift 3.92); kernel:guard (17/66, lift 3.43); defaultmap:default:all (4/18, lift 2.96); scalar:implied_tofrom (6/34, lift 2.35); dir:target teams (7/43, lift 2.17); dir:target parallel (12/83, lift 1.93); body:inner_seq_loop (9/64, lift 1.88)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| kernel:guard + scalar:implicit | 25 | 10 | 0.4 | 0.258 | 5.33 |
| kernel:guard + map:mod:always | 24 | 8 | 0.333 | 0.258 | 4.44 |
| dir:target teams + red:clause | 15 | 5 | 0.333 | 0.163 | 4.44 |
| kernel:guard + loop:down | 34 | 11 | 0.324 | 0.258 | 4.31 |
| dir:target teams + scalar:implicit | 19 | 6 | 0.316 | 0.163 | 4.21 |
| dir:target teams + map:mod:always | 16 | 5 | 0.312 | 0.163 | 4.17 |
| body:inner_seq_loop + dir:target parallel | 17 | 5 | 0.294 | 0.145 | 3.92 |
| map:mod:always + scalar:implied_tofrom | 17 | 5 | 0.294 | 0.176 | 3.92 |

### cce20: ice

Single features: kernel:phase (45/45, lift 3.29); phase:do (39/39, lift 3.29); phase:do simd (28/28, lift 3.29); phase:masked (25/25, lift 3.29); phase:single (24/24, lift 3.29); phase:nowait_barrier (23/23, lift 3.29); map:alloc (19/19, lift 3.29); dir:target parallel (57/83, lift 2.26)

| feature pair | programs | ice | rate | best single rate | lift |
|---|---|---|---|---|---|
| clause:proc_bind + map:from | 15 | 11 | 0.733 | 0.484 | 2.42 |
| clause:lastprivate + dir:loop | 18 | 13 | 0.722 | 0.464 | 2.38 |
| clause:device + clause:lastprivate | 17 | 12 | 0.706 | 0.464 | 2.33 |
| chain:target teams distribute parallel do simd + clause:lastprivate | 16 | 10 | 0.625 | 0.464 | 2.06 |
| clause:dist_schedule + dir:parallel | 16 | 10 | 0.625 | 0.469 | 2.06 |
| map:from + split:target \| simd | 16 | 10 | 0.625 | 0.423 | 2.06 |
| clause:lastprivate + dir:parallel | 37 | 23 | 0.622 | 0.464 | 2.05 |
| map:from + scalar:firstprivate | 23 | 14 | 0.609 | 0.468 | 2.01 |

### cce21: wrong_code

Single features: guard:par_thread0 (10/17, lift 6.73); defaultmap:tofrom:allocatable (6/15, lift 4.57); kernel:guard (17/62, lift 3.14); red:atomic (4/16, lift 2.86); defaultmap:default:all (4/18, lift 2.54); dir:target teams (8/40, lift 2.29); body:inner_seq_loop (10/61, lift 1.87); dir:target parallel (12/78, lift 1.76)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| kernel:guard + scalar:implicit | 22 | 9 | 0.409 | 0.274 | 4.68 |
| dir:target teams + scalar:implicit | 17 | 6 | 0.353 | 0.2 | 4.04 |
| kernel:guard + map:mod:always | 20 | 7 | 0.35 | 0.274 | 4.0 |
| dir:distribute + dir:target parallel | 18 | 6 | 0.333 | 0.154 | 3.81 |
| body:inner_seq_loop + dir:target parallel | 15 | 5 | 0.333 | 0.164 | 3.81 |
| body:inner_seq_loop + dir:target teams | 17 | 5 | 0.294 | 0.2 | 3.36 |
| dir:distribute + dir:target teams | 18 | 5 | 0.278 | 0.2 | 3.18 |
| chain:target parallel do + dir:distribute | 19 | 5 | 0.263 | 0.14 | 3.01 |

### cce21: ice

Single features: kernel:phase (45/45, lift 3.09); phase:do (39/39, lift 3.09); phase:do simd (28/28, lift 3.09); phase:masked (25/25, lift 3.09); phase:single (24/24, lift 3.09); phase:nowait_barrier (23/23, lift 3.09); map:alloc (19/19, lift 3.09); dir:target parallel (57/78, lift 2.26)

| feature pair | programs | ice | rate | best single rate | lift |
|---|---|---|---|---|---|
| clause:proc_bind + map:from | 15 | 11 | 0.733 | 0.484 | 2.27 |
| clause:lastprivate + dir:loop | 18 | 13 | 0.722 | 0.478 | 2.23 |
| clause:device + clause:lastprivate | 17 | 12 | 0.706 | 0.478 | 2.18 |
| chain:target teams distribute parallel do simd + clause:lastprivate | 15 | 10 | 0.667 | 0.478 | 2.06 |
| clause:dist_schedule + dir:parallel | 15 | 10 | 0.667 | 0.5 | 2.06 |
| map:from + split:target \| simd | 15 | 10 | 0.667 | 0.44 | 2.06 |
| clause:lastprivate + scalar:firstprivate | 17 | 11 | 0.647 | 0.512 | 2.0 |
| clause:lastprivate + dir:parallel | 36 | 23 | 0.639 | 0.478 | 1.98 |

## Compile rejections (features not supported)

### afar

| programs | message |
|---|---|
| 45 | not_implemented: error: loc("<path> <path> not yet implemented: lastprivate clause in constructs other than simd/worksharing-loop/taskloop |
| 14 | not_implemented: loc("<path> error: not yet implemented: Unhandled clause order in omp.wsloop operation |
| 7 | not_implemented: error: loc("<path> <path> not yet implemented: lastprivate(conditional:) on simd construct |
| 7 | not_implemented: error: loc("<path> <path> not yet implemented: Firstprivate is currently unsupported defaultmap behaviour |
| 5 | not_implemented: loc("<path> error: not yet implemented: Unhandled clause order in omp.distribute operation |
| 2 | not_implemented: error: loc("<path> <path> not yet implemented: lastprivate(conditional:) on do simd composite construct |

Features most associated with rejection: clause:order (26/26); clause:lastprivate (59/75); clause:schedule:static (8/15); red:in_reduction:+ (8/15); chain:target teams distribute (22/44); clause:schedule:runtime (9/18); chain:target parallel do (25/51); split:target | parallel | do (13/27)

### cce19

| programs | message |
|---|---|
| 51 | diagnostic: ftn-1370 ftn: ERROR , \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET. |
| 33 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : "scalar, aggregate, allocatable or pointer" was expected but found ")". |
| 17 | diagnostic: ftn-1370 ftn: ERROR , \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET PARALLEL. |
| 8 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 5 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP DISTRIBUTE. |
| 5 | diagnostic: ftn-1370 ftn: ERROR , \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET SIMD. |
| 3 | diagnostic: ftn-1370 ftn: ERROR , \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET PARALLEL LOOP. |
| 1 | diagnostic: ftn-1310 ftn: ERROR , \| Object "I" is specified on the FIRSTPRIVATE clause. It must have a shared scope in the enclosing region. |
| 1 | diagnostic: ftn-1964 ftn: ERROR , \| Variable "S1" must have its data mapping attribute explicitly declared because default map(none) was specified. |
| 1 | not_implemented: Unsupported OpenMP construct Private of allocatables -- ib |

Features most associated with rejection: defaultmap:default:all (19/19); clause:thread_limit (87/101); red:in_reduction:* (18/25); guard:par_thread0 (16/24); defaultmap:default:scalar (11/17); clause:num_teams (32/51); clause:bind:parallel (10/16); clause:order (16/26)

### cce20

| programs | message |
|---|---|
| 11 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 7 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP DISTRIBUTE. |
| 2 | diagnostic: ftn-1310 ftn: ERROR , \| Object "I" is specified on the FIRSTPRIVATE clause. It must have a shared scope in the enclosing region. |

Features most associated with rejection: split:target | teams | distribute (9/27); clause:num_teams (15/51); clause:order (7/26); chain:target teams distribute (11/44); clause:firstprivate (4/17); clause:dist_schedule (7/39); dir:distribute (16/121); chain:target teams distribute parallel do (7/53)

### cce21

| programs | message |
|---|---|
| 17 | link_undefined_symbol: lld: error: undefined symbol: _cray$mt_taskwait |
| 11 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 7 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP DISTRIBUTE. |
| 2 | diagnostic: ftn-1310 ftn: ERROR , \| Object "I" is specified on the FIRSTPRIVATE clause. It must have a shared scope in the enclosing region. |

Features most associated with rejection: red:in_reduction:+ (8/15); red:in_reduction:* (13/25); clause:in_reduction (19/38); dir:taskgroup (19/38); kernel:inred (19/38); split:target | teams | distribute (10/27); clause:order (9/26); chain:target teams distribute (14/44)

## Generator rejects

Programs failing a legality check are never run. Causes (`rules`: a 5.2 rule of offload.engine.rules fired, a generator or rule bug; `flang`: AFAR flang's frontend refused a program the rules and gfortran accept; see the report for which of these are flang's errors):

| count | cause | seeds |
|---|---|---|

## Flaky results

- seed 13 cce19: wrong_code: checksum=1483376103 ran_on_host=0 expected=1984387845 | wrong_code: checksum=111263557 ran_on_host=0 expected=1984387845 | wrong_code: checksum=1066189023 ran_on_host=0 expected=1984387845 | wrong_code: checksum=2124496815 ran_on_host=0 expected=1984387845
- seed 13 cce20: wrong_code: checksum=359731438 ran_on_host=0 expected=1984387845 | wrong_code: checksum=359731438 ran_on_host=0 expected=1984387845 | wrong_code: checksum=359731438 ran_on_host=0 expected=1984387845 | wrong_code: checksum=2085838057 ran_on_host=0 expected=1984387845
- seed 60 cce19: wrong_code: checksum=1998632822 ran_on_host=0 expected=774564267 | wrong_code: checksum=997298219 ran_on_host=0 expected=774564267 | wrong_code: checksum=1631314247 ran_on_host=0 expected=774564267 | wrong_code: checksum=1940340971 ran_on_host=0 expected=774564267
- seed 60 cce21: wrong_code: checksum=1665783220 ran_on_host=0 expected=774564267 | wrong_code: checksum=1380445782 ran_on_host=0 expected=774564267 | wrong_code: checksum=1237777063 ran_on_host=0 expected=774564267 | wrong_code: checksum=1380445782 ran_on_host=0 expected=774564267
- seed 163 cce20: wrong_code: checksum=984382261 ran_on_host=0 expected=594933126 | wrong_code: checksum=1546167020 ran_on_host=0 expected=594933126 | wrong_code: checksum=984382261 ran_on_host=0 expected=594933126 | wrong_code: checksum=984382261 ran_on_host=0 expected=594933126
- seed 234 cce19: wrong_code: checksum=770242366 ran_on_host=0 expected=286364019 | wrong_code: checksum=770242366 ran_on_host=0 expected=286364019 | wrong_code: checksum=770242366 ran_on_host=0 expected=286364019 | wrong_code: checksum=49700853 ran_on_host=0 expected=286364019

## Appendix: host reference checks (not offload findings)

Device offload only: host runs (OMP_TARGET_OFFLOAD=disabled) and the sequential elision are references for the expected value, never measurements of a toolchain. A host_path_failure below is recorded data (results/fuzz/<run>/summary.json), not an offload finding, and it counts nowhere in the tables above.

The reference host run (OMP_TARGET_OFFLOAD=disabled, the first toolchain that compiled) failed for 0 programs (host_ref_failed) and printed another checksum than the model for 4 (host_mismatch). For each, every toolchain whose build compiled ran it on the host (rebuilt and run twice: results/fuzz/b0/hostcheck.jsonl), and the sequential elision (offload.engine.expected) ran where it applies. Rule: **valid** when at least one of them prints the model's checksum; the host builds that ran and did not are `host_path_failure` records (a host-path compiler or runtime bug: out of scope, not an offload finding). **noncompliant** when none does (a generator or model defect): excluded from the findings and the tallies above. A toolchain whose build does not compile has no host build ('no host build'). Values are host checksums. Scope: only these programs had every toolchain's host build run; for the others only the reference toolchain's host run exists, so host_path_failure counts are a lower bound.

| seed | reference | ref tc | model | afar host | cce19 host | cce20 host | cce21 host | elision | validity | host_path_failure |
|---|---|---|---|---|---|---|---|---|---|---|
| 18 | host_mismatch | cce20 | 1947133868 | no build: compile_reject | no build: compile_reject | 540990624 | 540990624 | **checksum=1947133868** | valid | cce20, cce21 |
| 58 | host_mismatch | afar | 168383631 | 1873972689 | no build: compile_reject | **168383631** | **168383631** | **checksum=168383631** | valid | afar |
| 209 | host_mismatch | cce20 | 884471902 | no build: compile_reject | no build: compile_reject | 1256899722 | 1256899722 | **checksum=884471902** | valid | cce20, cce21 |
| 287 | host_mismatch | afar | 999691455 | 1046228726 | no build: compile_reject | **999691455** | **999691455** | **checksum=999691455** | valid | afar |

### host_path_failure (valid programs; host-path failures, out of scope)

- afar: 2 programs (seeds 58, 287)
- cce20: 2 programs (seeds 18, 209)
- cce21: 2 programs (seeds 18, 209)

### Noncompliant programs (generator/model investigation)

(none)
