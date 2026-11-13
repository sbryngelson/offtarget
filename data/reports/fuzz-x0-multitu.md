# Fuzz campaign `x0-multitu`

Csmith-style random OpenMP 5.2 Fortran offload programs (offload.engine.fuzz, generator `fuzz-3`, base-language groups: multitu (offload.engine.fuzz_base)), run on every toolchain at -O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory; reference: the Python model of each program, checked against a host run (OMP_TARGET_OFFLOAD=disabled, a reference only; see the appendix 'Host reference checks' for the programs whose host run failed or disagreed). Machine-readable: results/fuzz/x0-multitu/summary.json.

## Size and timing

- programs generated: 300; legal and run: 300 (judged: 299; noncompliant, excluded from every count below: 1); generator rejects: 0; worker crashes: 0
- campaign wall time: 412 s with 16 workers (2621 programs/hour; 21.5 s per program and worker, all toolchains and repeats included)
- programs whose device results agree with the model on every toolchain: 92

## Classes per toolchain

Rejections (compile_reject) are features a toolchain does not support, not failures. Flaky = the repeats differed (counted in the worst class).

| class | afar | cce19 | cce20 | cce21 |
|---|---|---|---|---|
| agree | 220 | 122 | 182 | 163 |
| compile_reject | 71 | 124 | 20 | 36 |
| ice | 0 | 48 | 87 | 87 |
| wrong_code | 7 (1 flaky) | 5 (2 flaky) | 10 (1 flaky) | 13 |
| host_fallback | 0 | 0 | 0 | 0 |
| timeout | 0 | 0 | 0 | 0 |
| run_error | 1 | 0 | 0 | 0 |
| harness_error | 0 | 0 | 0 | 0 |

## Base-language features

Per base-language feature (offload.engine.fuzz_base): the programs that have it, and per toolchain agree / compile_reject / ice / wrong_code / run_error (other classes in parentheses when present).

| feature | programs | afar | cce19 | cce20 | cce21 |
|---|---|---|---|---|---|
| dc:call:ga1 | 58 | 40/15/0/3/0 | 20/29/8/1/0 | 35/3/19/1/0 | 32/6/19/1/0 |
| dc:call:gb1 | 30 | 18/10/0/1/1 | 11/15/4/0/0 | 18/6/6/0/0 | 15/9/6/0/0 |
| dc:call:ge1 | 39 | 31/8/0/0/0 | 10/22/7/0/0 | 17/3/17/2/0 | 15/5/17/2/0 |
| dc:call:gs1 | 41 | 30/9/0/2/0 | 13/21/7/0/0 | 23/3/15/0/0 | 21/5/15/0/0 |
| mt:external_function | 199 | 148/45/0/6/0 | 79/86/30/4/0 | 119/13/60/7/0 | 108/23/60/8/0 |
| mt:file_set | 299 | 220/71/0/7/1 | 122/124/48/5/0 | 182/20/87/10/0 | 163/36/87/13/0 |
| mt:module_chain | 176 | 119/51/0/5/1 | 67/78/29/2/0 | 103/13/55/5/0 | 91/24/55/6/0 |
| mt:module_file | 257 | 184/65/0/7/1 | 103/111/39/4/0 | 155/18/76/8/0 | 139/32/76/10/0 |
| mt:submodule | 181 | 135/40/0/5/1 | 68/79/32/2/0 | 106/10/60/5/0 | 94/20/60/7/0 |

## Known findings rediscovered

- cce19-target-parallel-guarded-loop (wrong code on cce19 in a program with a thread-0-guarded sequential loop in target parallel): 4 programs (seeds 20, 157, 234, 249)
- cce21-defaultmap-aggregate-flag (wrong code or host fallback on cce21 where cce20 agrees, in a program with a defaultmap clause; the finding's symptom: a map(tofrom) scalar is not copied back): 3 programs (seeds 28, 67, 241)
- (control for the line above: the same without a defaultmap clause): 0 programs (seeds )
- cce21-in-reduction-taskwait-link (cce21 link failure on _cray$mt_taskwait): 16 programs (seeds 25, 33, 42, 43, 52, 69, 72, 88, 142, 184, 197, 198)
- cce19-target-parallel-single-ice / task ICE (CCE 'unhandled construct type'): 72 programs (seeds 1, 2, 11, 21, 32, 34, 38, 40, 48, 51, 54, 56)

## Distinct minimized failures

(none minimized yet)

## Wrong code (all programs)

- afar: 7 programs (seeds 11, 48, 82, 89, 121, 171, 226)
- cce19: 5 programs (seeds 20, 22, 157, 234, 249)
- cce20: 10 programs (seeds 16, 18, 20, 22, 106, 157, 163, 233, 234, 249)
- cce21: 13 programs (seeds 16, 18, 20, 22, 28, 67, 106, 157, 163, 233, 234, 241, 249)

## Internal compiler errors (deduplicated by message)

| toolchain | programs | message | seeds |
|---|---|---|---|
| cce20 | 41 | ice: INTERNAL COMPILER ERROR: "unhandled acc construct type" (v_openmp.c, line 7881, version <v>) | 2, 21, 34, 38, 40 |
| cce21 | 41 | ice: INTERNAL COMPILER ERROR: "unhandled acc construct type" (v_openmp.c, line 8265, version <v>) | 2, 21, 34, 38, 40 |
| cce19 | 40 | ice: INTERNAL COMPILER ERROR: "unhandled construct type" (v_openmp.c, line 7617, version <v>) | 2, 32, 34, 48, 51 |
| cce20 | 30 | ice: INTERNAL COMPILER ERROR: "unhandled construct type" (v_openmp.c, line 7814, version <v>) | 1, 11, 32, 56, 62 |
| cce21 | 30 | ice: INTERNAL COMPILER ERROR: "unhandled construct type" (v_openmp.c, line 8197, version <v>) | 1, 11, 32, 56, 62 |
| cce20 | 13 | ice: INTERNAL COMPILER ERROR: "ACC - barrier/reset/protected last private not supported" (v_mt_translate.c, line 5607, version <v>) | 6, 26, 78, 100, 134 |
| cce21 | 13 | ice: INTERNAL COMPILER ERROR: "ACC - barrier/reset/protected last private not supported" (v_mt_translate.c, line 5798, version <v>) | 6, 26, 78, 100, 134 |
| cce19 | 7 | ice: INTERNAL COMPILER ERROR: "ACC - barrier/reset/protected last private not supported" (v_mt_translate.c, line 4874, version <v>) | 78, 100, 134, 136, 187 |
| cce19 | 1 | ice: INTERNAL COMPILER ERROR: "unhandled operator | 165 |
| cce20 | 1 | ice: INTERNAL COMPILER ERROR: "Couldn't find an atomic update statement" (v_mt_translate_atomic.c, line 1703, version <v>) | 218 |
| cce20 | 1 | ice: INTERNAL COMPILER ERROR: "Mismatched last induction expression for last private operators" (v_mt_translate.c, line 901, version <v>) | 166 |
| cce20 | 1 | ice: INTERNAL COMPILER ERROR: "unhandled operator | 165 |
| cce21 | 1 | ice: INTERNAL COMPILER ERROR: "Couldn't find an atomic update statement" (v_mt_translate_atomic.c, line 1702, version <v>) | 218 |
| cce21 | 1 | ice: INTERNAL COMPILER ERROR: "Mismatched last induction expression for last private operators" (v_mt_translate.c, line 911, version <v>) | 166 |
| cce21 | 1 | ice: INTERNAL COMPILER ERROR: "unhandled operator | 165 |

## Run errors, timeouts, host fallbacks

| toolchain | class | programs | reason | seeds |
|---|---|---|---|---|
| afar | run_error | 1 | crash: SIGABRT; without mandatory: crash: SIGABRT | 167 |

## Features and feature pairs most associated with failures

Among programs the toolchain compiled (or crashed on). Lift = the rate of the class among programs with the feature (pair) over the toolchain's overall rate; a pair is listed only when it beats both of its features alone by 25%.

### afar: wrong_code

Single features: clause:default:none (6/27, lift 7.24); phase:do simd (3/20, lift 4.89); split:target | teams | distribute | parallel | do simd (3/21, lift 4.65); red:clause:ieor (3/22, lift 4.44); clause:schedule (4/32, lift 4.07); dir:do simd (3/24, lift 4.07); wrap:host_update_to (4/33, lift 3.95); phase:single (3/25, lift 3.91)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| body:call_declare_target + clause:default:none | 15 | 5 | 0.333 | 0.222 | 10.86 |
| clause:default:none + decl:explicit_rank2 | 19 | 6 | 0.316 | 0.222 | 10.29 |
| clause:default:none + dir:parallel | 19 | 6 | 0.316 | 0.222 | 10.29 |
| clause:default:none + dir:teams | 17 | 5 | 0.294 | 0.222 | 9.58 |
| clause:default:none + map:to | 21 | 6 | 0.286 | 0.222 | 9.31 |
| dir:parallel + dir:target parallel | 21 | 6 | 0.286 | 0.092 | 9.31 |
| clause:default:none + dir:distribute | 18 | 5 | 0.278 | 0.222 | 9.05 |
| clause:schedule + dir:distribute | 15 | 4 | 0.267 | 0.125 | 8.69 |

### cce19: wrong_code

Single features: kernel:guard (4/34, lift 4.12); scalar:tofrom (3/28, lift 3.75); body:inner_seq_loop (3/35, lift 3.0); dir:simd (3/54, lift 1.94); map:section (3/58, lift 1.81); map:from (4/78, lift 1.79); map:to (5/120, lift 1.46); dir:target (5/134, lift 1.31)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| base:mt:external_function + scalar:tofrom | 15 | 3 | 0.2 | 0.107 | 7.0 |
| map:from + scalar:tofrom | 15 | 3 | 0.2 | 0.107 | 7.0 |
| kernel:guard + map:from | 16 | 3 | 0.188 | 0.118 | 6.56 |
| dir:target + kernel:guard | 23 | 4 | 0.174 | 0.118 | 6.09 |
| kernel:guard + map:to | 27 | 4 | 0.148 | 0.118 | 5.19 |
| map:to + scalar:tofrom | 22 | 3 | 0.136 | 0.107 | 4.77 |
| body:inner_seq_loop + map:to | 23 | 3 | 0.13 | 0.086 | 4.57 |
| body:inner_seq_loop + decl:allocatable_rank2 | 24 | 3 | 0.125 | 0.086 | 4.38 |

### cce19: ice

Single features: kernel:phase (27/27, lift 3.65); phase:do (24/24, lift 3.65); phase:nowait_barrier (19/19, lift 3.65); phase:do simd (17/17, lift 3.65); phase:single (17/17, lift 3.65); dir:target parallel (38/49, lift 2.83); wrap:host_update_to (11/19, lift 2.11); kernel:guard (17/34, lift 1.82)

| feature pair | programs | ice | rate | best single rate | lift |
|---|---|---|---|---|---|
| kernel:guard + loop:down | 16 | 11 | 0.688 | 0.5 | 2.51 |
| body:call_declare_target + clause:num_threads | 21 | 12 | 0.571 | 0.375 | 2.08 |
| clause:num_threads + declare_target_function | 21 | 12 | 0.571 | 0.375 | 2.08 |
| clause:lastprivate + dir:parallel | 20 | 11 | 0.55 | 0.385 | 2.01 |
| body:call_declare_target + clause:if:target | 15 | 8 | 0.533 | 0.382 | 1.94 |
| clause:num_threads + map:mod:close | 15 | 8 | 0.533 | 0.375 | 1.94 |
| dir:parallel + map:mod:always | 19 | 10 | 0.526 | 0.375 | 1.92 |
| dir:parallel + map:mod:close | 18 | 9 | 0.5 | 0.356 | 1.82 |

### cce20: wrong_code

Single features: defaultmap:tofrom:allocatable (3/15, lift 5.58); dir:target simd (3/19, lift 4.41); guard:par_thread0 (3/19, lift 4.41); split:target simd (3/19, lift 4.41); scalar:tofrom (6/44, lift 3.8); kernel:guard (8/66, lift 3.38); clause:nontemporal (3/26, lift 3.22); scalar:implied_tofrom (3/32, lift 2.62)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| chain:target simd + scalar:tofrom | 16 | 4 | 0.25 | 0.136 | 6.98 |
| loop:down + scalar:tofrom | 21 | 5 | 0.238 | 0.136 | 6.64 |
| base:mt:external_function + scalar:tofrom | 27 | 6 | 0.222 | 0.136 | 6.2 |
| map:from + scalar:tofrom | 27 | 6 | 0.222 | 0.136 | 6.2 |
| map:section + scalar:tofrom | 18 | 4 | 0.222 | 0.136 | 6.2 |
| chain:target simd + loop:down | 19 | 4 | 0.211 | 0.085 | 5.87 |
| body:inner_seq_loop + scalar:tofrom | 15 | 3 | 0.2 | 0.136 | 5.58 |
| base:mt:external_function + clause:nontemporal | 16 | 3 | 0.188 | 0.115 | 5.23 |

### cce20: ice

Single features: kernel:phase (46/46, lift 3.21); phase:do (40/40, lift 3.21); phase:single (29/29, lift 3.21); phase:do simd (28/28, lift 3.21); phase:nowait_barrier (28/28, lift 3.21); phase:masked (22/22, lift 3.21); map:alloc (18/18, lift 3.21); phase:loop (15/15, lift 3.21)

| feature pair | programs | ice | rate | best single rate | lift |
|---|---|---|---|---|---|
| clause:num_threads + wrap:host_update_to | 15 | 11 | 0.733 | 0.541 | 2.35 |
| clause:lastprivate + dir:loop | 16 | 10 | 0.625 | 0.462 | 2.0 |
| map:section + split:target \| parallel \| do | 18 | 11 | 0.611 | 0.44 | 1.96 |
| clause:dist_schedule + clause:lastprivate | 15 | 9 | 0.6 | 0.462 | 1.92 |
| clause:lastprivate + tasking:nowait_depend | 15 | 9 | 0.6 | 0.462 | 1.92 |
| decl:explicit_rank2 + kernel:guard | 32 | 19 | 0.594 | 0.47 | 1.9 |
| clause:num_threads + kernel:guard | 22 | 13 | 0.591 | 0.47 | 1.89 |
| map:from + split:target \| simd | 17 | 10 | 0.588 | 0.393 | 1.89 |

### cce21: wrong_code

Single features: guard:par_thread0 (3/17, lift 3.57); dir:target simd (3/18, lift 3.37); split:target simd (3/18, lift 3.37); kernel:guard (10/63, lift 3.21); scalar:tofrom (6/42, lift 2.89); red:clause:* (3/24, lift 2.53); body:inner_seq_loop (8/65, lift 2.49); clause:nontemporal (3/25, lift 2.43)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| chain:target simd + scalar:tofrom | 15 | 4 | 0.267 | 0.143 | 5.39 |
| body:inner_seq_loop + kernel:guard | 28 | 7 | 0.25 | 0.159 | 5.06 |
| loop:down + scalar:tofrom | 20 | 5 | 0.25 | 0.143 | 5.06 |
| map:from + scalar:tofrom | 25 | 6 | 0.24 | 0.143 | 4.86 |
| kernel:guard + scalar:implicit | 21 | 5 | 0.238 | 0.159 | 4.82 |
| map:section + scalar:tofrom | 17 | 4 | 0.235 | 0.143 | 4.76 |
| base:mt:external_function + scalar:tofrom | 26 | 6 | 0.231 | 0.143 | 4.67 |
| chain:target simd + loop:down | 18 | 4 | 0.222 | 0.089 | 4.5 |

### cce21: ice

Single features: kernel:phase (46/46, lift 3.02); phase:do (40/40, lift 3.02); phase:single (29/29, lift 3.02); phase:do simd (28/28, lift 3.02); phase:nowait_barrier (28/28, lift 3.02); phase:masked (22/22, lift 3.02); map:alloc (18/18, lift 3.02); phase:loop (15/15, lift 3.02)

| feature pair | programs | ice | rate | best single rate | lift |
|---|---|---|---|---|---|
| map:section + split:target \| parallel \| do | 17 | 11 | 0.647 | 0.478 | 1.96 |
| clause:num_threads + map:mod:close | 24 | 15 | 0.625 | 0.469 | 1.89 |
| clause:if:target + kernel:guard | 16 | 10 | 0.625 | 0.492 | 1.89 |
| clause:lastprivate + dir:loop | 16 | 10 | 0.625 | 0.476 | 1.89 |
| map:from + split:target \| simd | 16 | 10 | 0.625 | 0.407 | 1.89 |
| clause:num_threads + kernel:guard | 21 | 13 | 0.619 | 0.492 | 1.87 |
| clause:lastprivate + dir:do | 23 | 14 | 0.609 | 0.476 | 1.84 |
| clause:dist_schedule + map:from | 20 | 12 | 0.6 | 0.421 | 1.81 |

## Compile rejections (features not supported)

### afar

| programs | message |
|---|---|
| 39 | not_implemented: error: loc(".f90":L:C): <path> not yet implemented: lastprivate clause in constructs other than simd/worksharing-loop/taskloop |
| 12 | not_implemented: loc(".f90":L:C): error: not yet implemented: Unhandled clause order in omp.wsloop operation |
| 7 | not_implemented: error: loc(".f90":L:C): <path> not yet implemented: Firstprivate is currently unsupported defaultmap behaviour |
| 6 | not_implemented: error: loc(".f90":L:C): <path> not yet implemented: lastprivate(conditional:) on simd construct |
| 5 | not_implemented: loc(".f90":L:C): error: not yet implemented: Unhandled clause order in omp.distribute operation |
| 2 | not_implemented: error: loc(".f90":L:C): <path> not yet implemented: lastprivate(conditional:) on do simd composite construct |

Features most associated with rejection: clause:order (26/26); clause:lastprivate (52/73); chain:target teams distribute (22/45); red:atomic (8/17); clause:schedule:dynamic (7/15); chain:target parallel do (21/46); clause:if:parallel (19/42); split:target | teams | distribute | simd (11/25)

### cce19

| programs | message |
|---|---|
| 51 | diagnostic: ftn-1370 ftn: ERROR , \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET. |
| 37 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : "scalar, aggregate, allocatable or pointer" was expected but found ")". |
| 15 | diagnostic: ftn-1370 ftn: ERROR , \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET PARALLEL. |
| 7 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 5 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP DISTRIBUTE. |
| 3 | diagnostic: ftn-1370 ftn: ERROR , \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET SIMD. |
| 3 | diagnostic: ftn-1370 ftn: ERROR , \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET PARALLEL LOOP. |
| 1 | diagnostic: ftn-1310 ftn: ERROR , \| Object "I" is specified on the FIRSTPRIVATE clause. It must have a shared scope in the enclosing region. |
| 1 | diagnostic: ftn-1964 ftn: ERROR , \| Variable "S1" must have its data mapping attribute explicitly declared because default map(none) was specified. |
| 1 | diagnostic: ftn-1510 ftn: ERROR , \| Variable "LSIMD" must have its data scope explicitly declared because DEFAULT(NONE) was specified. |

Features most associated with rejection: defaultmap:default:all (22/22); defaultmap:tofrom:all (15/15); clause:thread_limit (85/96); defaultmap:tofrom:scalar (11/15); clause:order (19/26); split:target | parallel | do (19/28); clause:num_teams (30/48); dir:target simd (13/21)

### cce20

| programs | message |
|---|---|
| 9 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP DISTRIBUTE. |
| 8 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 1 | diagnostic: ftn-1310 ftn: ERROR , \| Object "I" is specified on the FIRSTPRIVATE clause. It must have a shared scope in the enclosing region. |
| 1 | diagnostic: ftn-1510 ftn: ERROR , \| Variable "LSIMD" must have its data scope explicitly declared because DEFAULT(NONE) was specified. |
| 1 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP TEAMS DISTRIBUTE. |

Features most associated with rejection: clause:order (10/26); split:target | teams | distribute (8/28); chain:target teams distribute (12/45); clause:num_teams (12/48); base:dc:call:gb1 (6/30); defaultmap:tofrom:scalar (3/15); dir:teams distribute (3/16); map:mod:present (7/41)

### cce21

| programs | message |
|---|---|
| 16 | link_undefined_symbol: lld: error: undefined symbol: _cray$mt_taskwait |
| 9 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP DISTRIBUTE. |
| 8 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 1 | diagnostic: ftn-1310 ftn: ERROR , \| Object "I" is specified on the FIRSTPRIVATE clause. It must have a shared scope in the enclosing region. |
| 1 | diagnostic: ftn-1510 ftn: ERROR , \| Variable "LSIMD" must have its data scope explicitly declared because DEFAULT(NONE) was specified. |
| 1 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP TEAMS DISTRIBUTE. |

Features most associated with rejection: red:in_reduction:* (12/22); clause:in_reduction (18/38); dir:taskgroup (18/38); kernel:inred (18/38); clause:order (12/26); red:in_reduction:+ (7/17); split:target | teams | distribute (10/28); defaultmap:tofrom:scalar (5/15)

## Generator rejects

Programs failing a legality check are never run. Causes (`rules`: a 5.2 rule of offload.engine.rules fired, a generator or rule bug; `flang`: AFAR flang's frontend refused a program the rules and gfortran accept; see the report for which of these are flang's errors):

| count | cause | seeds |
|---|---|---|

## Flaky results

- seed 82 afar: wrong_code: checksum=1225805058 ran_on_host=0 expected=1216075456 | wrong_code: checksum=1225805058 ran_on_host=0 expected=1216075456 | wrong_code: checksum=1225805058 ran_on_host=0 expected=1216075456 | agree: checksum=1216075456 ran_on_host=0
- seed 157 cce19: wrong_code: checksum=833139913 ran_on_host=0 expected=1981506157 | wrong_code: checksum=1617109235 ran_on_host=0 expected=1981506157 | wrong_code: checksum=433595821 ran_on_host=0 expected=1981506157 | wrong_code: checksum=1232871425 ran_on_host=0 expected=1981506157
- seed 163 cce20: wrong_code: checksum=1381639600 ran_on_host=0 expected=662132359 | wrong_code: checksum=1381639600 ran_on_host=0 expected=662132359 | wrong_code: checksum=1943424359 ran_on_host=0 expected=662132359 | wrong_code: checksum=1943424359 ran_on_host=0 expected=662132359
- seed 234 cce19: wrong_code: checksum=2028989511 ran_on_host=0 expected=940867011 | wrong_code: checksum=661779088 ran_on_host=0 expected=940867011 | wrong_code: checksum=7231191 ran_on_host=0 expected=940867011 | wrong_code: checksum=661779088 ran_on_host=0 expected=940867011

## Appendix: host reference checks (not offload findings)

Device offload only: host runs (OMP_TARGET_OFFLOAD=disabled) and the sequential elision are references for the expected value, never measurements of a toolchain. A host_path_failure below is recorded data (results/fuzz/<run>/summary.json), not an offload finding, and it counts nowhere in the tables above.

The reference host run (OMP_TARGET_OFFLOAD=disabled, the first toolchain that compiled) failed for 0 programs (host_ref_failed) and printed another checksum than the model for 3 (host_mismatch). For each, every toolchain whose build compiled ran it on the host (rebuilt and run twice: results/fuzz/x0-multitu/hostcheck.jsonl), and the sequential elision (offload.engine.expected) ran where it applies. Rule: **valid** when at least one of them prints the model's checksum; the host builds that ran and did not are `host_path_failure` records (a host-path compiler or runtime bug: out of scope, not an offload finding). **noncompliant** when none does (a generator or model defect): excluded from the findings and the tallies above. A toolchain whose build does not compile has no host build ('no host build'). Values are host checksums. Scope: only these programs had every toolchain's host build run; for the others only the reference toolchain's host run exists, so host_path_failure counts are a lower bound.

| seed | reference | ref tc | model | afar host | cce19 host | cce20 host | cce21 host | elision | validity | host_path_failure |
|---|---|---|---|---|---|---|---|---|---|---|
| 18 | host_mismatch | cce20 | 1947133868 | no build: compile_reject | no build: compile_reject | 540990624 | 540990624 | **checksum=1947133868** | valid | cce20, cce21 |
| 209 | host_mismatch | cce20 | 884471902 | no build: compile_reject | no build: compile_reject | 1256899722 | 1256899722 | inapplicable: module variables (declare target visibility) | noncompliant | - |
| 246 | host_mismatch | afar | 12975581 | 912142175 | **12975581** | **12975581** | **12975581** | inapplicable: module variables (declare target visibility) | valid | afar |

### host_path_failure (valid programs; host-path failures, out of scope)

- afar: 1 programs (seeds 246)
- cce20: 1 programs (seeds 18)
- cce21: 1 programs (seeds 18)

### Noncompliant programs (generator/model investigation)

No available host build prints the model's checksum. Their device classes (not counted anywhere above):

- seed 209: model 884471902; host afar no host build: compile_reject, cce19 no host build: compile_reject, cce20 1256899722, cce21 1256899722; elision inapplicable: module variables (declare target visibility); device afar compile_reject, cce19 compile_reject, cce20 wrong_code, cce21 wrong_code
