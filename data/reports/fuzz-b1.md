# Fuzz campaign `b1`

Csmith-style random OpenMP 5.2 Fortran offload programs (offload.engine.fuzz, generator `fuzz-3`, base-language groups: types (offload.engine.fuzz_base)), run on every toolchain at -O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory; reference: the Python model of each program, checked against a host run (OMP_TARGET_OFFLOAD=disabled, a reference only; see the appendix 'Host reference checks' for the programs whose host run failed or disagreed). Machine-readable: results/fuzz/b1/summary.json.

## Size and timing

- programs generated: 300; legal and run: 300 (judged: 299; noncompliant, excluded from every count below: 1); generator rejects: 0; worker crashes: 0
- campaign wall time: 866 s with 8 workers (1247 programs/hour; 22.7 s per program and worker, all toolchains and repeats included)
- programs whose device results agree with the model on every toolchain: 74

## Classes per toolchain

Rejections (compile_reject) are features a toolchain does not support, not failures. Flaky = the repeats differed (counted in the worst class).

| class | afar | cce19 | cce20 | cce21 |
|---|---|---|---|---|
| agree | 208 | 105 | 174 | 151 |
| compile_reject | 79 | 133 | 25 | 43 |
| ice | 0 | 57 | 89 | 89 |
| wrong_code | 6 | 4 (1 flaky) | 11 (1 flaky) | 16 (1 flaky) |
| host_fallback | 0 | 0 | 0 | 0 |
| timeout | 0 | 0 | 0 | 0 |
| run_error | 6 | 0 | 0 | 0 |
| harness_error | 0 | 0 | 0 | 0 |

## Base-language features

Per base-language feature (offload.engine.fuzz_base): the programs that have it, and per toolchain agree / compile_reject / ice / wrong_code / run_error (other classes in parentheses when present).

| feature | programs | afar | cce19 | cce20 | cce21 |
|---|---|---|---|---|---|
| decl:allocatable_char | 70 | 55/12/0/3/0 | 21/33/16/0/0 | 42/5/23/0/0 | 39/8/23/0/0 |
| decl:allocatable_complex4 | 79 | 56/21/0/2/0 | 31/37/9/2/0 | 52/6/17/4/0 | 47/10/17/5/0 |
| decl:allocatable_complex8 | 85 | 61/21/0/2/1 | 33/33/19/0/0 | 52/5/26/2/0 | 46/10/26/3/0 |
| decl:allocatable_int1 | 73 | 53/15/0/3/2 | 27/29/15/2/0 | 44/3/22/4/0 | 41/5/22/5/0 |
| decl:allocatable_int2 | 74 | 50/22/0/2/0 | 26/31/16/1/0 | 42/7/19/6/0 | 36/13/19/6/0 |
| decl:allocatable_int8 | 81 | 58/20/0/2/1 | 24/38/17/2/0 | 46/5/25/5/0 | 40/11/25/5/0 |
| decl:allocatable_logical | 75 | 45/25/0/2/3 | 18/40/15/2/0 | 36/7/28/4/0 | 31/12/28/4/0 |
| decl:allocatable_real4 | 83 | 58/23/0/0/2 | 27/40/16/0/0 | 48/7/27/1/0 | 40/15/27/1/0 |
| decl:allocatable_real8 | 107 | 75/28/0/1/3 | 41/48/16/2/0 | 67/6/28/6/0 | 56/14/28/9/0 |
| decl:explicit_char | 121 | 82/32/0/3/4 | 39/63/16/3/0 | 71/12/30/8/0 | 58/23/30/10/0 |
| decl:explicit_complex4 | 113 | 81/27/0/2/3 | 34/53/24/2/0 | 60/9/39/5/0 | 54/14/39/6/0 |
| decl:explicit_complex8 | 111 | 76/29/0/4/2 | 37/54/19/1/0 | 64/8/34/5/0 | 57/13/34/7/0 |
| decl:explicit_int1 | 126 | 83/38/0/3/2 | 41/56/27/2/0 | 66/11/42/7/0 | 54/21/42/9/0 |
| decl:explicit_int2 | 110 | 81/27/0/1/1 | 41/49/19/1/0 | 66/5/35/4/0 | 59/11/35/5/0 |
| decl:explicit_int8 | 115 | 82/27/0/4/2 | 41/50/24/0/0 | 60/10/42/3/0 | 52/15/42/6/0 |
| decl:explicit_logical | 117 | 84/29/0/2/2 | 45/49/20/3/0 | 73/10/30/4/0 | 62/18/30/7/0 |
| decl:explicit_real4 | 106 | 67/32/0/4/3 | 34/45/25/2/0 | 59/7/35/5/0 | 50/15/35/6/0 |
| decl:explicit_real8 | 172 | 120/46/0/3/3 | 55/75/39/3/0 | 90/16/60/6/0 | 82/22/60/8/0 |
| out:char | 14 | 11/2/0/1/0 | 0/10/4/0/0 | 8/1/5/0/0 | 6/3/5/0/0 |
| out:complex4 | 21 | 12/7/0/1/1 | 9/11/0/1/0 | 17/0/3/1/0 | 16/0/3/2/0 |
| out:complex8 | 27 | 23/3/0/1/0 | 8/14/5/0/0 | 16/1/9/1/0 | 13/2/9/3/0 |
| out:int1 | 29 | 18/10/0/1/0 | 11/16/1/1/0 | 16/3/7/3/0 | 14/4/7/4/0 |
| out:int2 | 18 | 12/6/0/0/0 | 7/9/2/0/0 | 10/3/2/3/0 | 9/5/2/2/0 |
| out:int8 | 28 | 19/9/0/0/0 | 6/18/3/1/0 | 12/4/9/3/0 | 11/4/9/4/0 |
| out:logical | 17 | 11/6/0/0/0 | 3/11/1/2/0 | 8/2/5/2/0 | 8/2/5/2/0 |
| out:real4 | 25 | 17/7/0/0/1 | 6/15/4/0/0 | 16/2/7/0/0 | 14/4/7/0/0 |
| out:real8 | 32 | 23/8/0/1/0 | 11/11/9/1/0 | 16/1/13/2/0 | 14/2/13/3/0 |
| real_kind_conversion | 15 | 11/4/0/0/0 | 3/9/2/1/0 | 10/0/4/1/0 | 9/1/4/1/0 |
| red:complex4:+ | 16 | 8/7/0/1/0 | 4/11/1/0/0 | 7/3/4/2/0 | 5/3/4/4/0 |
| red:complex4:clause | 11 | 5/5/0/1/0 | 3/7/1/0/0 | 5/3/2/1/0 | 4/3/2/2/0 |
| red:complex4:critical | 1 | 0/0/0/1/0 | 0/1/0/0/0 | 0/0/1/0/0 | 0/0/1/0/0 |
| red:complex4:plain | 5 | 3/2/0/0/0 | 1/4/0/0/0 | 2/0/2/1/0 | 1/0/2/2/0 |
| red:complex8:+ | 9 | 8/0/0/0/1 | 3/4/2/0/0 | 5/1/3/0/0 | 4/2/3/0/0 |
| red:complex8:clause | 8 | 8/0/0/0/0 | 3/4/1/0/0 | 5/1/2/0/0 | 4/2/2/0/0 |
| red:complex8:plain | 2 | 1/0/0/0/1 | 0/1/1/0/0 | 1/0/1/0/0 | 1/0/1/0/0 |
| red:int1:clause | 9 | 4/4/0/0/1 | 1/5/3/0/0 | 2/2/4/1/0 | 2/2/4/1/0 |
| red:int1:iand | 3 | 1/2/0/0/0 | 0/2/1/0/0 | 0/0/3/0/0 | 0/0/3/0/0 |
| red:int1:ieor | 2 | 0/2/0/0/0 | 0/2/0/0/0 | 0/1/0/1/0 | 0/1/0/1/0 |
| red:int1:ior | 3 | 3/0/0/0/0 | 2/0/1/0/0 | 2/0/1/0/0 | 1/0/1/1/0 |
| red:int1:max | 1 | 0/1/0/0/0 | 0/1/0/0/0 | 0/1/0/0/0 | 0/1/0/0/0 |
| red:int1:min | 2 | 1/0/0/0/1 | 0/1/1/0/0 | 1/0/1/0/0 | 1/0/1/0/0 |
| red:int1:plain | 2 | 1/1/0/0/0 | 1/1/0/0/0 | 1/0/1/0/0 | 0/0/1/1/0 |
| red:int2:clause | 7 | 5/2/0/0/0 | 3/2/2/0/0 | 4/1/2/0/0 | 3/2/2/0/0 |
| red:int2:iand | 3 | 1/2/0/0/0 | 3/0/0/0/0 | 3/0/0/0/0 | 3/0/0/0/0 |
| red:int2:ieor | 2 | 1/1/0/0/0 | 0/1/1/0/0 | 0/1/1/0/0 | 0/1/1/0/0 |
| red:int2:ior | 1 | 0/1/0/0/0 | 0/1/0/0/0 | 0/1/0/0/0 | 0/1/0/0/0 |
| red:int2:max | 2 | 2/0/0/0/0 | 0/1/1/0/0 | 1/0/1/0/0 | 0/1/1/0/0 |
| red:int2:min | 1 | 1/0/0/0/0 | 1/0/0/0/0 | 1/0/0/0/0 | 1/0/0/0/0 |
| red:int2:plain | 1 | 0/1/0/0/0 | 1/0/0/0/0 | 1/0/0/0/0 | 1/0/0/0/0 |
| red:int8:+ | 1 | 1/0/0/0/0 | 1/0/0/0/0 | 1/0/0/0/0 | 1/0/0/0/0 |
| red:int8:clause | 7 | 6/0/0/1/0 | 3/4/0/0/0 | 4/1/2/0/0 | 3/2/2/0/0 |
| red:int8:ieor | 3 | 2/0/0/1/0 | 0/2/1/0/0 | 0/1/2/0/0 | 0/1/2/0/0 |
| red:int8:min | 4 | 4/0/0/0/0 | 2/2/0/0/0 | 3/0/1/0/0 | 2/1/1/0/0 |
| red:int8:plain | 1 | 1/0/0/0/0 | 0/0/1/0/0 | 0/0/1/0/0 | 0/0/1/0/0 |
| red:logical:.eqv. | 3 | 2/1/0/0/0 | 2/0/1/0/0 | 2/0/1/0/0 | 2/0/1/0/0 |
| red:logical:.neqv. | 3 | 3/0/0/0/0 | 2/1/0/0/0 | 2/0/0/1/0 | 1/1/0/1/0 |
| red:logical:.or. | 4 | 3/1/0/0/0 | 2/2/0/0/0 | 3/0/1/0/0 | 3/0/1/0/0 |
| red:logical:atomic | 1 | 1/0/0/0/0 | 1/0/0/0/0 | 1/0/0/0/0 | 1/0/0/0/0 |
| red:logical:clause | 7 | 5/2/0/0/0 | 5/1/1/0/0 | 6/0/1/0/0 | 5/1/1/0/0 |
| red:logical:plain | 2 | 2/0/0/0/0 | 0/2/0/0/0 | 0/0/1/1/0 | 0/0/1/1/0 |
| red:real4:+ | 3 | 0/3/0/0/0 | 0/0/3/0/0 | 0/0/3/0/0 | 0/0/3/0/0 |
| red:real4:atomic | 1 | 1/0/0/0/0 | 1/0/0/0/0 | 1/0/0/0/0 | 1/0/0/0/0 |
| red:real4:clause | 10 | 4/4/0/1/1 | 3/4/3/0/0 | 4/1/4/1/0 | 4/1/4/1/0 |
| red:real4:max | 4 | 1/2/0/0/1 | 1/1/2/0/0 | 2/0/2/0/0 | 2/0/2/0/0 |
| red:real4:min | 6 | 4/1/0/1/0 | 3/3/0/0/0 | 3/1/1/1/0 | 3/1/1/1/0 |
| red:real4:plain | 1 | 0/1/0/0/0 | 0/0/1/0/0 | 0/0/1/0/0 | 0/0/1/0/0 |
| red:real8:+ | 9 | 5/3/0/0/1 | 3/6/0/0/0 | 5/2/1/1/0 | 4/2/1/2/0 |
| red:real8:atomic | 3 | 1/1/0/0/1 | 0/2/1/0/0 | 1/0/2/0/0 | 1/0/2/0/0 |
| red:real8:clause | 10 | 5/5/0/0/0 | 5/5/0/0/0 | 6/3/0/1/0 | 5/4/0/1/0 |
| red:real8:max | 6 | 3/3/0/0/0 | 1/4/1/0/0 | 2/1/1/2/0 | 1/2/1/2/0 |
| red:real8:min | 3 | 1/2/0/0/0 | 1/2/0/0/0 | 1/1/0/1/0 | 1/1/0/1/0 |
| red:real8:plain | 3 | 3/0/0/0/0 | 0/3/0/0/0 | 1/1/0/1/0 | 0/1/0/2/0 |
| spell:double_precision | 145 | 101/38/0/3/3 | 53/64/27/1/0 | 87/15/38/5/0 | 77/22/38/8/0 |
| type:char | 183 | 131/43/0/5/4 | 60/90/30/3/0 | 107/17/51/8/0 | 92/30/51/10/0 |
| type:char_scalar | 183 | 131/43/0/5/4 | 60/90/30/3/0 | 107/17/51/8/0 | 92/30/51/10/0 |
| type:complex4 | 184 | 133/44/0/4/3 | 62/86/33/3/0 | 106/15/55/8/0 | 95/24/55/10/0 |
| type:complex8 | 182 | 126/48/0/5/3 | 67/78/36/1/0 | 108/12/56/6/0 | 96/22/56/8/0 |
| type:int1 | 186 | 127/49/0/6/4 | 64/77/42/3/0 | 103/13/62/8/0 | 88/25/62/11/0 |
| type:int2 | 176 | 126/46/0/3/1 | 64/76/34/2/0 | 104/11/53/8/0 | 92/21/53/10/0 |
| type:int8 | 182 | 132/41/0/6/3 | 60/80/40/2/0 | 98/15/62/7/0 | 84/26/62/10/0 |
| type:logical | 181 | 123/49/0/4/5 | 62/82/34/3/0 | 104/16/55/6/0 | 88/29/55/9/0 |
| type:real4 | 176 | 117/51/0/4/4 | 57/78/39/2/0 | 97/14/59/6/0 | 82/28/59/7/0 |
| type:real8 | 261 | 181/70/0/4/6 | 89/116/52/4/0 | 146/22/83/10/0 | 129/35/83/14/0 |
| view:char | 111 | 77/29/0/3/2 | 32/63/14/2/0 | 65/14/26/6/0 | 54/25/26/6/0 |
| view:complex4 | 80 | 56/22/0/2/0 | 22/43/13/2/0 | 43/11/22/4/0 | 37/18/22/3/0 |
| view:complex8 | 84 | 56/24/0/3/1 | 27/40/16/1/0 | 47/7/25/5/0 | 41/14/25/4/0 |
| view:int1 | 96 | 67/25/0/3/1 | 24/44/26/2/0 | 46/8/37/5/0 | 37/18/37/4/0 |
| view:int2 | 89 | 58/29/0/2/0 | 27/44/17/1/0 | 53/5/26/5/0 | 45/12/26/6/0 |
| view:int8 | 97 | 66/28/0/2/1 | 28/45/23/1/0 | 50/13/31/3/0 | 44/19/31/3/0 |
| view:logical | 83 | 57/22/0/2/2 | 26/37/18/2/0 | 45/8/27/3/0 | 36/16/27/4/0 |
| view:real4 | 87 | 56/29/0/1/1 | 23/41/22/1/0 | 44/7/33/3/0 | 37/15/33/2/0 |
| view:real8 | 114 | 73/36/0/3/2 | 28/61/23/2/0 | 56/16/37/5/0 | 49/23/37/5/0 |

## Known findings rediscovered

- cce19-target-parallel-guarded-loop (wrong code on cce19 in a program with a thread-0-guarded sequential loop in target parallel): 3 programs (seeds 70, 134, 264)
- cce21-defaultmap-aggregate-flag (wrong code or host fallback on cce21 where cce20 agrees, in a program with a defaultmap clause; the finding's symptom: a map(tofrom) scalar is not copied back): 6 programs (seeds 28, 48, 106, 131, 233, 265)
- (control for the line above: the same without a defaultmap clause): 0 programs (seeds )
- cce21-in-reduction-taskwait-link (cce21 link failure on _cray$mt_taskwait): 18 programs (seeds 21, 42, 52, 61, 72, 88, 142, 178, 184, 197, 198, 202)
- cce19-target-parallel-single-ice / task ICE (CCE 'unhandled construct type'): 69 programs (seeds 1, 11, 25, 32, 38, 40, 51, 54, 56, 58, 59, 62)

## Distinct minimized failures

| file | toolchain | kind | also fails on | lines | expected | observed |
|---|---|---|---|---|---|---|
| `data/findings/fuzz/b1-22-cce20.f90` | cce20 | wrong_code | cce19, cce21 | 144 -> 25 | the host reference checksum (host reference (elision) checksum=8) | device checksum=0 ran_on_host=0 |
| `data/findings/fuzz/b1-231-afar.f90` | afar | run_error | - | 109 -> 42 | runs to completion (the host run does) | device: fail crash: SIGABRT; host reference (cce20/elision) checksum=1450123117 |
| `data/findings/fuzz/b1-183-afar.f90` | afar | wrong_code | - | 100 -> 41 | the host reference checksum (host reference (cce19/elision) checksum=1123737439) | device checksum=1118127074 ran_on_host=0 |
| `data/findings/fuzz/b1-268-afar.f90` | afar | wrong_code | - | 81 -> 33 | the host reference checksum (host reference (cce19/elision) checksum=447891769) | device checksum=603216482 ran_on_host=0 |
| `data/findings/fuzz/b1-121-afar.f90` | afar | wrong_code | - | 135 -> 22 | the host reference checksum (host reference (cce19) checksum=1048575) | device checksum=0 ran_on_host=0 |

Not minimized:

- seed 111 afar wrong_code: not_reproduced the failure does not reproduce: device fail None host=None ref 163685360

## Wrong code (all programs)

- afar: 6 programs (seeds 111, 121, 183, 259, 261, 268)
- cce19: 4 programs (seeds 70, 134, 209, 264)
- cce20: 11 programs (seeds 16, 21, 22, 70, 134, 163, 209, 219, 249, 264, 286)
- cce21: 16 programs (seeds 16, 22, 28, 48, 70, 106, 131, 134, 163, 209, 219, 233, 249, 264, 265, 286)

## Internal compiler errors (deduplicated by message)

| toolchain | programs | message | seeds |
|---|---|---|---|
| cce20 | 48 | ice: INTERNAL COMPILER ERROR: "unhandled acc construct type" (v_openmp.c, line 7881, version <v>) | 1, 11, 25, 32, 38 |
| cce21 | 48 | ice: INTERNAL COMPILER ERROR: "unhandled acc construct type" (v_openmp.c, line 8265, version <v>) | 1, 11, 25, 32, 38 |
| cce19 | 43 | ice: INTERNAL COMPILER ERROR: "unhandled construct type" (v_openmp.c, line 7617, version <v>) | 11, 32, 51, 56, 62 |
| cce20 | 20 | ice: INTERNAL COMPILER ERROR: "unhandled construct type" (v_openmp.c, line 7814, version <v>) | 51, 54, 56, 62, 82 |
| cce21 | 20 | ice: INTERNAL COMPILER ERROR: "unhandled construct type" (v_openmp.c, line 8197, version <v>) | 51, 54, 56, 62, 82 |
| cce20 | 15 | ice: INTERNAL COMPILER ERROR: "ACC - barrier/reset/protected last private not supported" (v_mt_translate.c, line 5607, version <v>) | 26, 36, 43, 78, 100 |
| cce21 | 15 | ice: INTERNAL COMPILER ERROR: "ACC - barrier/reset/protected last private not supported" (v_mt_translate.c, line 5798, version <v>) | 26, 36, 43, 78, 100 |
| cce19 | 11 | ice: INTERNAL COMPILER ERROR: "ACC - barrier/reset/protected last private not supported" (v_mt_translate.c, line 4874, version <v>) | 36, 78, 100, 136, 161 |
| cce20 | 2 | ice: INTERNAL COMPILER ERROR: "Couldn't find an atomic update statement" (v_mt_translate_atomic.c, line 1703, version <v>) | 34, 111 |
| cce20 | 2 | ice: INTERNAL COMPILER ERROR: "Unhandled contexts must be fixed!!! | 14, 18 |
| cce21 | 2 | ice: INTERNAL COMPILER ERROR: "Couldn't find an atomic update statement" (v_mt_translate_atomic.c, line 1702, version <v>) | 34, 111 |
| cce21 | 2 | ice: INTERNAL COMPILER ERROR: "Unhandled contexts must be fixed!!! | 14, 18 |
| cce19 | 1 | ice: INTERNAL COMPILER ERROR: "Couldn't find an atomic update statement" (v_mt_translate_atomic.c, line 1703, version <v>) | 111 |
| cce19 | 1 | ice: INTERNAL COMPILER ERROR: "Unhandled contexts must be fixed!!! | 14 |
| cce19 | 1 | ice: INTERNAL COMPILER ERROR: "unhandled operator | 165 |
| cce20 | 1 | ice: INTERNAL COMPILER ERROR: "Mismatched last induction expression for last private operators" (v_mt_translate.c, line 901, version <v>) | 166 |
| cce20 | 1 | ice: INTERNAL COMPILER ERROR: "unhandled operator | 165 |
| cce21 | 1 | ice: INTERNAL COMPILER ERROR: "Mismatched last induction expression for last private operators" (v_mt_translate.c, line 911, version <v>) | 166 |
| cce21 | 1 | ice: INTERNAL COMPILER ERROR: "unhandled operator | 165 |

## Run errors, timeouts, host fallbacks

| toolchain | class | programs | reason | seeds |
|---|---|---|---|---|
| afar | run_error | 6 | crash: SIGABRT; without mandatory: crash: SIGABRT | 35, 55, 91, 115, 158 |

## Features and feature pairs most associated with failures

Among programs the toolchain compiled (or crashed on). Lift = the rate of the class among programs with the feature (pair) over the toolchain's overall rate; a pair is listed only when it beats both of its features alone by 25%.

### afar: wrong_code

Single features: red:clause:ieor (4/21, lift 6.98); clause:default:none (4/24, lift 6.11); split:target | teams | distribute | parallel | do simd (3/18, lift 6.11); dir:do simd (3/23, lift 4.78); clause:schedule (4/31, lift 4.73); red:clause:min (3/25, lift 4.4); chain:target teams distribute parallel do (3/26, lift 4.23); chain:target teams distribute parallel do simd (3/33, lift 3.33)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| base:type:int8 + red:clause:ieor | 15 | 4 | 0.267 | 0.19 | 9.78 |
| base:type:logical + clause:default:none | 15 | 4 | 0.267 | 0.167 | 9.78 |
| base:type:char + red:clause:ieor | 16 | 4 | 0.25 | 0.19 | 9.17 |
| base:type:char_scalar + red:clause:ieor | 16 | 4 | 0.25 | 0.19 | 9.17 |
| dir:target + red:clause:ieor | 16 | 4 | 0.25 | 0.19 | 9.17 |
| base:type:int1 + clause:schedule | 17 | 4 | 0.235 | 0.129 | 8.63 |
| clause:default:none + map:to | 17 | 4 | 0.235 | 0.167 | 8.63 |
| clause:schedule + decl:explicit_rank2 | 17 | 4 | 0.235 | 0.129 | 8.63 |

### afar: run_error

Single features: map:mod:present (5/28, lift 6.55); clause:default:none (3/24, lift 4.58); wrap:host_update_to (3/29, lift 3.79); clause:schedule (3/31, lift 3.55); dir:do (4/44, lift 3.33); wrap:enter_exit_data (3/38, lift 2.89); map:mod:close (5/73, lift 2.51); dir:teams (5/74, lift 2.48)

| feature pair | programs | run_error | rate | best single rate | lift |
|---|---|---|---|---|---|
| dir:teams + map:mod:present | 16 | 4 | 0.25 | 0.179 | 9.17 |
| map:implicit + map:mod:present | 21 | 5 | 0.238 | 0.179 | 8.73 |
| base:type:logical + map:mod:present | 17 | 4 | 0.235 | 0.179 | 8.63 |
| dir:parallel + map:mod:present | 17 | 4 | 0.235 | 0.179 | 8.63 |
| base:decl:allocatable_logical + dir:teams | 15 | 3 | 0.2 | 0.068 | 7.33 |
| base:type:logical + clause:default:none | 15 | 3 | 0.2 | 0.125 | 7.33 |
| clause:schedule + dir:teams | 15 | 3 | 0.2 | 0.097 | 7.33 |
| dir:do + map:mod:close | 15 | 3 | 0.2 | 0.091 | 7.33 |

### cce19: wrong_code

Single features: kernel:guard (3/36, lift 3.46); base:decl:explicit_char (3/58, lift 2.15); base:decl:explicit_logical (3/68, lift 1.83); decl:explicit_rank2 (3/76, lift 1.64); base:type:char (3/93, lift 1.34); base:type:char_scalar (3/93, lift 1.34); base:decl:explicit_real8 (3/97, lift 1.28); base:type:complex4 (3/98, lift 1.27)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| base:decl:explicit_logical + kernel:guard | 17 | 3 | 0.176 | 0.083 | 7.32 |
| base:decl:explicit_char + decl:explicit_rank2 | 22 | 3 | 0.136 | 0.052 | 5.66 |
| decl:allocatable_rank2 + kernel:guard | 24 | 3 | 0.125 | 0.083 | 5.19 |
| base:type:logical + kernel:guard | 26 | 3 | 0.115 | 0.083 | 4.79 |
| base:decl:explicit_char + base:type:complex4 | 27 | 3 | 0.111 | 0.052 | 4.61 |
| base:decl:explicit_char + base:type:int1 | 39 | 3 | 0.077 | 0.052 | 3.19 |
| base:type:complex4 + decl:explicit_rank2 | 41 | 3 | 0.073 | 0.039 | 3.04 |
| base:type:char + decl:explicit_rank2 | 43 | 3 | 0.07 | 0.039 | 2.9 |

### cce19: ice

Single features: kernel:phase (31/31, lift 2.91); phase:do (27/27, lift 2.91); phase:do simd (19/19, lift 2.91); phase:single (19/19, lift 2.91); phase:masked (15/15, lift 2.91); phase:nowait_barrier (15/15, lift 2.91); dir:target parallel (39/48, lift 2.37); clause:lastprivate (21/35, lift 1.75)

| feature pair | programs | ice | rate | best single rate | lift |
|---|---|---|---|---|---|
| clause:lastprivate + dir:parallel | 18 | 15 | 0.833 | 0.6 | 2.43 |
| base:type:int8 + clause:lastprivate | 19 | 15 | 0.789 | 0.6 | 2.3 |
| base:type:int2 + clause:lastprivate | 17 | 13 | 0.765 | 0.6 | 2.23 |
| base:view:int1 + clause:num_threads | 15 | 11 | 0.733 | 0.513 | 2.14 |
| base:view:int8 + dir:teams | 15 | 11 | 0.733 | 0.442 | 2.14 |
| base:view:real4 + dir:teams | 17 | 12 | 0.706 | 0.478 | 2.06 |
| base:type:real4 + tasking:nowait_depend | 16 | 11 | 0.688 | 0.536 | 2.0 |
| clause:num_threads + map:mod:close | 16 | 11 | 0.688 | 0.513 | 2.0 |

### cce20: wrong_code

Single features: guard:par_thread0 (7/20, lift 8.72); base:out:int2 (3/15, lift 4.98); defaultmap:tofrom:all (3/19, lift 3.93); kernel:guard (9/64, lift 3.5); scalar:implied_tofrom (4/32, lift 3.11); base:out:int8 (3/24, lift 3.11); base:out:int1 (3/26, lift 2.87); dir:target parallel (8/86, lift 2.32)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| base:type:int2 + guard:par_thread0 | 16 | 7 | 0.438 | 0.35 | 10.9 |
| base:decl:allocatable_int2 + kernel:guard | 16 | 5 | 0.312 | 0.141 | 7.78 |
| base:decl:allocatable_int2 + dir:target parallel | 20 | 6 | 0.3 | 0.093 | 7.47 |
| base:view:complex8 + kernel:guard | 16 | 4 | 0.25 | 0.141 | 6.23 |
| base:decl:explicit_char + kernel:guard | 25 | 6 | 0.24 | 0.141 | 5.98 |
| base:decl:explicit_real4 + kernel:guard | 22 | 5 | 0.227 | 0.141 | 5.66 |
| base:decl:allocatable_real8 + kernel:guard | 27 | 6 | 0.222 | 0.141 | 5.54 |
| kernel:guard + scalar:implicit | 27 | 6 | 0.222 | 0.141 | 5.54 |

### cce20: ice

Single features: kernel:phase (45/45, lift 3.08); phase:do (39/39, lift 3.08); phase:do simd (28/28, lift 3.08); phase:single (25/25, lift 3.08); phase:masked (24/24, lift 3.08); map:alloc (19/19, lift 3.08); phase:nowait_barrier (19/19, lift 3.08); dir:target parallel (61/86, lift 2.18)

| feature pair | programs | ice | rate | best single rate | lift |
|---|---|---|---|---|---|
| clause:num_threads + kernel:guard | 17 | 13 | 0.765 | 0.469 | 2.35 |
| base:decl:explicit_int8 + scalar:firstprivate | 16 | 12 | 0.75 | 0.467 | 2.31 |
| chain:target teams distribute parallel do + clause:lastprivate | 16 | 12 | 0.75 | 0.5 | 2.31 |
| clause:lastprivate + dir:loop | 16 | 12 | 0.75 | 0.5 | 2.31 |
| base:view:int8 + chain:target teams distribute parallel do | 15 | 11 | 0.733 | 0.385 | 2.26 |
| base:type:int8 + split:target \| teams \| distribute \| parallel \| do | 17 | 12 | 0.706 | 0.542 | 2.17 |
| clause:device + map:mod:close | 17 | 12 | 0.706 | 0.466 | 2.17 |
| scalar:firstprivate + scalar:implicit | 17 | 12 | 0.706 | 0.467 | 2.17 |

### cce21: wrong_code

Single features: guard:par_thread0 (7/18, lift 6.22); defaultmap:tofrom:all (5/16, lift 5.0); kernel:guard (12/61, lift 3.15); base:out:int8 (4/24, lift 2.67); scalar:implied_tofrom (5/31, lift 2.58); base:out:int1 (4/25, lift 2.56); scalar:implicit (11/83, lift 2.12); red:clause:min (4/32, lift 2.0)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| base:decl:explicit_char + kernel:guard | 23 | 7 | 0.304 | 0.197 | 4.87 |
| base:decl:explicit_real4 + kernel:guard | 20 | 6 | 0.3 | 0.197 | 4.8 |
| kernel:guard + scalar:implicit | 27 | 8 | 0.296 | 0.197 | 4.74 |
| kernel:guard + red:clause | 17 | 5 | 0.294 | 0.197 | 4.71 |
| base:decl:allocatable_real8 + kernel:guard | 25 | 7 | 0.28 | 0.197 | 4.48 |
| base:decl:allocatable_int2 + dir:target parallel | 18 | 5 | 0.278 | 0.12 | 4.44 |
| clause:device + kernel:guard | 15 | 4 | 0.267 | 0.197 | 4.27 |
| dir:teams + kernel:guard | 15 | 4 | 0.267 | 0.197 | 4.27 |

### cce21: ice

Single features: kernel:phase (45/45, lift 2.88); phase:do (39/39, lift 2.88); phase:do simd (28/28, lift 2.88); phase:single (25/25, lift 2.88); phase:masked (24/24, lift 2.88); map:alloc (19/19, lift 2.88); phase:nowait_barrier (19/19, lift 2.88); clause:in_reduction (14/19, lift 2.12)

| feature pair | programs | ice | rate | best single rate | lift |
|---|---|---|---|---|---|
| clause:num_threads + kernel:guard | 17 | 13 | 0.765 | 0.492 | 2.2 |
| base:decl:explicit_int8 + scalar:firstprivate | 16 | 12 | 0.75 | 0.512 | 2.16 |
| chain:target teams distribute parallel do + clause:lastprivate | 16 | 12 | 0.75 | 0.516 | 2.16 |
| clause:device + map:mod:close | 16 | 12 | 0.75 | 0.5 | 2.16 |
| clause:lastprivate + dir:loop | 16 | 12 | 0.75 | 0.516 | 2.16 |
| base:view:int8 + clause:device | 19 | 14 | 0.737 | 0.5 | 2.12 |
| base:view:int1 + scalar:firstprivate | 15 | 11 | 0.733 | 0.512 | 2.11 |
| base:view:int8 + chain:target teams distribute parallel do | 15 | 11 | 0.733 | 0.397 | 2.11 |

## Compile rejections (features not supported)

### afar

| programs | message |
|---|---|
| 42 | not_implemented: error: loc("<path> <path> not yet implemented: lastprivate clause in constructs other than simd/worksharing-loop/taskloop |
| 17 | not_implemented: loc("<path> error: not yet implemented: Unhandled clause order in omp.wsloop operation |
| 8 | not_implemented: loc("<path> error: not yet implemented: Unhandled clause order in omp.distribute operation |
| 5 | not_implemented: error: loc("<path> <path> not yet implemented: Firstprivate is currently unsupported defaultmap behaviour |
| 5 | not_implemented: error: loc("<path> <path> not yet implemented: lastprivate(conditional:) on simd construct |
| 2 | not_implemented: error: loc("<path> <path> not yet implemented: lastprivate(conditional:) on do simd composite construct |

Features most associated with rejection: clause:order (36/36); clause:lastprivate (57/72); split:target | teams | distribute | simd (16/28); red:clause:ior (9/16); split:target | teams | distribute (16/29); chain:target teams distribute (26/48); chain:target parallel do (22/41); split:target | teams | distribute | parallel | do (13/26)

### cce19

| programs | message |
|---|---|
| 38 | diagnostic: ftn-1370 ftn: ERROR , \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET. |
| 37 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : "scalar, aggregate, allocatable or pointer" was expected but found ")". |
| 18 | not_implemented: Unsupported OpenMP construct Fortran character -- xc |
| 13 | diagnostic: ftn-1370 ftn: ERROR , \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET PARALLEL. |
| 9 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 5 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP DISTRIBUTE. |
| 4 | diagnostic: ftn-1370 ftn: ERROR , \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET SIMD. |
| 2 | diagnostic: ftn-1370 ftn: ERROR , \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET PARALLEL LOOP. |
| 1 | not_implemented: Unsupported OpenMP construct Private of allocatables -- o1 |
| 1 | diagnostic: ftn-1310 ftn: ERROR , \| Object "I" is specified on the FIRSTPRIVATE clause. It must have a shared scope in the enclosing region. |
| 1 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP TARGET TEAMS DISTRIBUTE. |
| 1 | diagnostic: ftn-1964 ftn: ERROR , \| Variable "S1" must have its data mapping attribute explicitly declared because default map(none) was specified. |

Features most associated with rejection: defaultmap:tofrom:all (22/22); defaultmap:default:all (18/18); clause:thread_limit (71/81); split:target | teams | distribute (21/29); guard:par_thread0 (16/22); split:target | teams | loop (20/28); chain:target teams distribute (34/48); base:red:complex4:+ (11/16)

### cce20

| programs | message |
|---|---|
| 12 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 10 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP DISTRIBUTE. |
| 1 | diagnostic: ftn-1310 ftn: ERROR , \| Object "I" is specified on the FIRSTPRIVATE clause. It must have a shared scope in the enclosing region. |
| 1 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP TARGET TEAMS DISTRIBUTE. |
| 1 | diagnostic: ftn-1510 ftn: ERROR , \| Variable "I" must have its data scope explicitly declared because DEFAULT(NONE) was specified. |

Features most associated with rejection: clause:order (13/36); split:target | teams | distribute (9/29); clause:num_teams (16/53); split:target | teams | distribute | simd (8/28); chain:target teams distribute (13/48); chain:target teams distribute simd (9/45); red:clause:+ (8/40); base:red:complex4:+ (3/16)

### cce21

| programs | message |
|---|---|
| 18 | link_undefined_symbol: lld: error: undefined symbol: _cray$mt_taskwait |
| 12 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 10 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP DISTRIBUTE. |
| 1 | diagnostic: ftn-1310 ftn: ERROR , \| Object "I" is specified on the FIRSTPRIVATE clause. It must have a shared scope in the enclosing region. |
| 1 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP TARGET TEAMS DISTRIBUTE. |
| 1 | diagnostic: ftn-1510 ftn: ERROR , \| Variable "I" must have its data scope explicitly declared because DEFAULT(NONE) was specified. |

Features most associated with rejection: red:in_reduction:+ (11/20); clause:in_reduction (19/38); dir:taskgroup (19/38); kernel:inred (19/38); red:in_reduction:* (10/20); clause:order (15/36); split:target | teams | distribute (12/29); chain:target teams distribute (16/48)

## Generator rejects

Programs failing a legality check are never run. Causes (`rules`: a 5.2 rule of offload.engine.rules fired, a generator or rule bug; `flang`: AFAR flang's frontend refused a program the rules and gfortran accept; see the report for which of these are flang's errors):

| count | cause | seeds |
|---|---|---|

## Flaky results

- seed 70 cce19: wrong_code: checksum=1853134060 ran_on_host=0 expected=1883791451 | wrong_code: checksum=1620957353 ran_on_host=0 expected=1883791451 | wrong_code: checksum=1853134060 ran_on_host=0 expected=1883791451 | wrong_code: checksum=1474627896 ran_on_host=0 expected=1883791451
- seed 70 cce21: wrong_code: checksum=379828881 ran_on_host=0 expected=1883791451 | wrong_code: checksum=1928690490 ran_on_host=0 expected=1883791451 | wrong_code: checksum=379828881 ran_on_host=0 expected=1883791451 | wrong_code: checksum=1928690490 ran_on_host=0 expected=1883791451
- seed 163 cce20: wrong_code: checksum=72270292 ran_on_host=0 expected=661658633 | wrong_code: checksum=989236289 ran_on_host=0 expected=661658633 | wrong_code: checksum=72270292 ran_on_host=0 expected=661658633 | wrong_code: checksum=989236289 ran_on_host=0 expected=661658633

## Appendix: host reference checks (not offload findings)

Device offload only: host runs (OMP_TARGET_OFFLOAD=disabled) and the sequential elision are references for the expected value, never measurements of a toolchain. A host_path_failure below is recorded data (results/fuzz/<run>/summary.json), not an offload finding, and it counts nowhere in the tables above.

The reference host run (OMP_TARGET_OFFLOAD=disabled, the first toolchain that compiled) failed for 0 programs (host_ref_failed) and printed another checksum than the model for 6 (host_mismatch). For each, every toolchain whose build compiled ran it on the host (rebuilt and run twice: results/fuzz/b1/hostcheck.jsonl), and the sequential elision (offload.engine.expected) ran where it applies. Rule: **valid** when at least one of them prints the model's checksum; the host builds that ran and did not are `host_path_failure` records (a host-path compiler or runtime bug: out of scope, not an offload finding). **noncompliant** when none does (a generator or model defect): excluded from the findings and the tallies above. A toolchain whose build does not compile has no host build ('no host build'). Values are host checksums. Scope: only these programs had every toolchain's host build run; for the others only the reference toolchain's host run exists, so host_path_failure counts are a lower bound.

| seed | reference | ref tc | model | afar host | cce19 host | cce20 host | cce21 host | elision | validity | host_path_failure |
|---|---|---|---|---|---|---|---|---|---|---|
| 42 | host_mismatch | afar | 562252458 | 823593020 | no build: compile_reject | **562252458** | no build: compile_reject | **checksum=562252458** | valid | afar |
| 131 | host_mismatch | cce20 | 726417587 | no build: compile_reject | no build: compile_reject | 438076499 | 1853071036 | **checksum=726417587** | valid | cce20, cce21 |
| 209 | host_mismatch | cce19 | 706134207 | no build: compile_reject | 1054467371 | 1054467371 | 1054467371 | **checksum=706134207** | valid | cce19, cce20, cce21 |
| 212 | host_mismatch | afar | 1834514582 | 2068383424 | no build: compile_reject | **1834514582** | **1834514582** | **checksum=1834514582** | valid | afar |
| 243 | host_mismatch | afar | 1686279132 | 104304099 | no build: compile_reject | **1686279132** | **1686279132** | **checksum=1686279132** | valid | afar |
| 294 | host_mismatch | afar | 839761755 | 563732237 | no build: ice | no build: ice | no build: ice | inapplicable: present modifier | noncompliant | - |

### host_path_failure (valid programs; host-path failures, out of scope)

- afar: 3 programs (seeds 42, 212, 243)
- cce19: 1 programs (seeds 209)
- cce20: 2 programs (seeds 131, 209)
- cce21: 2 programs (seeds 131, 209)

### Noncompliant programs (generator/model investigation)

No available host build prints the model's checksum. Their device classes (not counted anywhere above):

- seed 294: model 839761755; host afar 563732237, cce19 no host build: ice, cce20 no host build: ice, cce21 no host build: ice; elision inapplicable: present modifier; device afar wrong_code, cce19 ice, cce20 ice, cce21 ice
