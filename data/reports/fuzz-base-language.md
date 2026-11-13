# Base-language axis of the fuzz generator

Generator `fuzz-3` (offload.engine.fuzz, offload.engine.fuzz_base) adds base-language groups to the Csmith-style OpenMP 5.2 offload generator, one group per stage, switchable per campaign (`tools/campaigns/fuzz.py run --base-features <group>`); without a group a fuzz-3 program is the fuzz-2 program of its seed, and fuzz-1/fuzz-2 seeds replay unchanged. Every program passes offload.engine.rules, gfortran -std=f2008 -fsyntax-only, AFAR flang's frontend, and the definedness check (the program without OpenMP built by gfortran with -fcheck=all, twice with different fills of uninitialised storage, must print the model's checksum both times); each parallel loop of the model is checked for races. The maintainer's host-run rule applies (a program that no host build or sequential elision prints the model's value for is noncompliant and left out). Campaigns: 300 programs each, toolchains afar, cce19, cce20, cce21, -O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory; per-campaign reports data/reports/fuzz-<run>.md, minimized reproducers data/findings/fuzz/<run>-<seed>-<toolchain>.f90 (triage: data/findings/fuzz/README.md).

## Campaigns

| run | stage | programs | judged | noncompliant | generator rejects | agree on all | wall s |
|---|---|---|---|---|---|---|---|
| `b0` | control: no base group (the fuzz-2 programs) | 300 | 300 | 0 | 0 | 76 | 2427 |
| `b1` | 1: element types and kinds | 300 | 299 | 1 | 0 | 74 | 866 |
| `b2` | 2: derived types | 300 | 300 | 0 | 0 | 95 | 1027 |
| `b3` | 3: allocatable, pointer, target, sections, procedures | 300 | 300 | 0 | 0 | 70 | 1995 |
| `b4` | 4: declare target, mapper, user reduction, modules | 300 | 297 | 3 | 0 | 23 | 2573 |
| `b5` | 5: multiple translation units | 300 | 299 | 1 | 0 | 87 | 2698 |
| `s1` | alloc, declare, derived, multitu, types | 10000 | 9924 | 70 | 5 | 758 | 31465 |

## Classes per stage and toolchain

Counts among the judged programs (rate of the judged in parentheses).

### agree

| run | afar | cce19 | cce20 | cce21 |
|---|---|---|---|---|
| `b0` | 202 (67%) | 114 (38%) | 174 (58%) | 155 (52%) |
| `b1` | 208 (70%) | 105 (35%) | 174 (58%) | 151 (51%) |
| `b2` | 207 (69%) | 137 (46%) | 183 (61%) | 165 (55%) |
| `b3` | 177 (59%) | 110 (37%) | 149 (50%) | 124 (41%) |
| `b4` | 173 (58%) | 37 (12%) | 57 (19%) | 134 (45%) |
| `b5` | 210 (70%) | 122 (41%) | 182 (61%) | 163 (55%) |
| `s1` | 5274 (53%) | 1271 (13%) | 1934 (19%) | 3652 (37%) |

### compile_reject

| run | afar | cce19 | cce20 | cce21 |
|---|---|---|---|---|
| `b0` | 80 (27%) | 125 (42%) | 20 (7%) | 37 (12%) |
| `b1` | 79 (26%) | 133 (44%) | 25 (8%) | 43 (14%) |
| `b2` | 72 (24%) | 114 (38%) | 19 (6%) | 35 (12%) |
| `b3` | 89 (30%) | 123 (41%) | 41 (14%) | 54 (18%) |
| `b4` | 107 (36%) | 228 (77%) | 193 (65%) | 72 (24%) |
| `b5` | 71 (24%) | 124 (41%) | 20 (7%) | 36 (12%) |
| `s1` | 3477 (35%) | 7687 (77%) | 6611 (67%) | 2797 (28%) |

### ice

| run | afar | cce19 | cce20 | cce21 |
|---|---|---|---|---|
| `b0` | 0 (0%) | 51 (17%) | 85 (28%) | 85 (28%) |
| `b1` | 0 (0%) | 57 (19%) | 89 (30%) | 89 (30%) |
| `b2` | 0 (0%) | 41 (14%) | 84 (28%) | 84 (28%) |
| `b3` | 3 (1%) | 51 (17%) | 84 (28%) | 84 (28%) |
| `b4` | 0 (0%) | 24 (8%) | 33 (11%) | 74 (25%) |
| `b5` | 0 (0%) | 48 (16%) | 87 (29%) | 87 (29%) |
| `s1` | 76 (1%) | 680 (7%) | 1036 (10%) | 2403 (24%) |

### wrong_code

| run | afar | cce19 | cce20 | cce21 |
|---|---|---|---|---|
| `b0` | 8 (3%) | 10 (3%) | 21 (7%) | 23 (8%) |
| `b1` | 6 (2%) | 4 (1%) | 11 (4%) | 16 (5%) |
| `b2` | 9 (3%) | 8 (3%) | 14 (5%) | 16 (5%) |
| `b3` | 5 (2%) | 14 (5%) | 24 (8%) | 17 (6%) |
| `b4` | 5 (2%) | 3 (1%) | 6 (2%) | 17 (6%) |
| `b5` | 8 (3%) | 5 (2%) | 10 (3%) | 13 (4%) |
| `s1` | 159 (2%) | 148 (1%) | 200 (2%) | 410 (4%) |

### run_error

| run | afar | cce19 | cce20 | cce21 |
|---|---|---|---|---|
| `b0` | 10 (3%) | 0 (0%) | 0 (0%) | 0 (0%) |
| `b1` | 6 (2%) | 0 (0%) | 0 (0%) | 0 (0%) |
| `b2` | 12 (4%) | 0 (0%) | 0 (0%) | 0 (0%) |
| `b3` | 26 (9%) | 2 (1%) | 2 (1%) | 21 (7%) |
| `b4` | 12 (4%) | 4 (1%) | 8 (3%) | 0 (0%) |
| `b5` | 10 (3%) | 0 (0%) | 0 (0%) | 0 (0%) |
| `s1` | 938 (9%) | 62 (1%) | 137 (1%) | 645 (6%) |

### timeout

| run | afar | cce19 | cce20 | cce21 |
|---|---|---|---|---|
| `b0` | 0 (0%) | 0 (0%) | 0 (0%) | 0 (0%) |
| `b1` | 0 (0%) | 0 (0%) | 0 (0%) | 0 (0%) |
| `b2` | 0 (0%) | 0 (0%) | 0 (0%) | 0 (0%) |
| `b3` | 0 (0%) | 0 (0%) | 0 (0%) | 0 (0%) |
| `b4` | 0 (0%) | 1 (0%) | 0 (0%) | 0 (0%) |
| `b5` | 0 (0%) | 0 (0%) | 0 (0%) | 0 (0%) |
| `s1` | 0 (0%) | 76 (1%) | 6 (0%) | 17 (0%) |

## Against the control

The control `b0` runs the same seeds without a base-language group (the fuzz-2 programs), so a stage's excess over it is what its group adds. Per toolchain: the stage's failure rate (wrong_code + run_error + timeout + host_fallback, among the judged programs the toolchain compiled) and, in parentheses, the control's.

| run | afar | cce19 | cce20 | cce21 |
|---|---|---|---|---|
| `b1` | 12/220 = 5% (8%) | 4/109 = 4% (8%) | 11/185 = 6% (11%) | 16/167 = 10% (13%) |
| `b2` | 21/228 = 9% (8%) | 8/145 = 6% (8%) | 14/197 = 7% (11%) | 16/181 = 9% (13%) |
| `b3` | 31/208 = 15% (8%) | 16/126 = 13% (8%) | 26/175 = 15% (11%) | 38/162 = 23% (13%) |
| `b4` | 17/190 = 9% (8%) | 8/45 = 18% (8%) | 14/71 = 20% (11%) | 17/151 = 11% (13%) |
| `b5` | 18/228 = 8% (8%) | 5/127 = 4% (8%) | 10/192 = 5% (11%) | 13/176 = 7% (13%) |
| `s1` | 1097/6371 = 17% (8%) | 286/1557 = 18% (8%) | 343/2277 = 15% (11%) | 1072/4724 = 23% (13%) |

## Copy mode (HSA_XNACK=0)

Each stage campaign run again on the same seeds at HSA_XNACK=0 (copy mode) in a flux allocation with THP on. The stage runs above used HSA_XNACK=1 on the interactive node with THP off, so a change here mixes the memory mode with THP (see the split below when present). Per run: seeds judged in both, noncompliant at HSA_XNACK=0, programs that agree on every toolchain at HSA_XNACK=0 (at HSA_XNACK=1 in parentheses), and the toolchain cells whose class changed.

| run | copy-mode run | seeds in both | noncompliant | agree on all | cells changed |
|---|---|---|---|---|---|
| `b1` | `x0-types` | 299 | 1 | 76 (74) | 8 |
| `b2` | `x0-derived` | 300 | 0 | 102 (95) | 13 |
| `b3` | `x0-alloc` | 300 | 0 | 69 (70) | 18 |
| `b4` | `x0-declare` | 297 | 3 | 24 (23) | 9 |
| `b5` | `x0-multitu` | 299 | 1 | 92 (87) | 11 |

- `b1`: afar: run_error -> agree 6; afar: wrong_code -> agree 1; cce21: wrong_code -> run_error 1
- `b2`: afar: run_error -> agree 11; afar: run_error -> wrong_code 1; afar: wrong_code -> agree 1
- `b3`: afar: agree -> run_error 4; afar: agree -> wrong_code 2; afar: run_error -> agree 2; afar: run_error -> wrong_code 2; cce19: agree -> run_error 1; cce19: agree -> wrong_code 1; cce19: run_error -> agree 1; cce20: agree -> wrong_code 1; cce20: run_error -> agree 1; cce20: wrong_code -> run_error 1; cce21: agree -> run_error 1; cce21: agree -> wrong_code 1
- `b4`: afar: run_error -> agree 5; afar: run_error -> wrong_code 1; afar: wrong_code -> agree 2; cce21: wrong_code -> timeout 1
- `b5`: afar: run_error -> agree 10; afar: wrong_code -> run_error 1

### THP or memory mode

AFAR seeds that crashed (SIGABRT) at HSA_XNACK=1 in the stage runs (interactive node, THP off) and agree at HSA_XNACK=0 (flux, THP on), run again on AFAR at HSA_XNACK=1 in two flux allocations on idle compute nodes, THP on and THP off. xnack1: crashes in both (the memory mode decides); thp: agrees only with THP on; load_or_flake: agrees in both (the stage run's crash came from the loaded node or is intermittent); other: any other pair.

| verdict | seeds |
|---|---|
| load_or_flake | 5 |
| xnack1 | 29 |

- load_or_flake: types 231, derived 121, derived 298, alloc 298, multitu 231
- xnack1: types 35, types 55, types 91, types 115, types 158, derived 35, derived 66, derived 176, derived 182, derived 183, derived 199, derived 213, derived 236, derived 268, alloc 30, declare 9, declare 35, declare 172, declare 275, declare 288, multitu 33, multitu 35, multitu 91, multitu 158, multitu 161, multitu 186, multitu 213, multitu 214, multitu 288

Runtime failure of the xnack1 seeds:

| failure | seeds | which | family |
|---|---|---|---|
| `device mapping required by 'present' map type modifier does not exist for host address` | 23 | types 35, types 55, types 91, types 115, types 158, derived 35, derived 176, derived 182, derived 199, derived 236, alloc 30, declare 35, declare 172, declare 275, declare 288, multitu 33, multitu 35, multitu 91, multitu 158, multitu 161, multitu 186, multitu 214, multitu 288 | known: `1131-afar.f90`, `158-afar.f90` (a present modifier after the item was mapped; HSA_XNACK=1 only) |
| `memory access fault: Write access to a read-only page` | 6 | derived 66, derived 183, derived 213, derived 268, declare 9, multitu 213 | 5 of 6 are the known nested-reduction family (`698-afar.f90`, `b2-213-afar.f90`); derived 183 has no reduction (`b2-183-afar.f90`); HSA_XNACK=1 only |

## Sequential elision

The programs built without OpenMP (gfortran and amdflang) against a sequential omp_lib and run on the host, where offload.engine.expected.elision_applicability proves that sequential execution gives the OpenMP result (ELISION_RULE; structures are tracked component by component, pointers as aliases of their targets, internal subroutines inlined). Elision is the model's independent partner: a value different from the model's is a model bug or an analysis bug until shown otherwise.

| run | programs | elision applies | = model | differs | no value | most frequent reasons it does not apply |
|---|---|---|---|---|---|---|
| `b0` | 300 | 254 | 254 | 0 | 0 | present modifier (46); defaultmap(present: aggregate) (5); defaultmap(present: allocatable) (1) |
| `b1` | 300 | 253 | 253 | 0 | 0 | present modifier (47); defaultmap(present: aggregate) (4); defaultmap(present: allocatable) (4) |
| `b2` | 300 | 232 | 232 | 0 | 0 | present modifier (68); defaultmap(present: aggregate) (2); defaultmap(present: allocatable) (1) |
| `b3` | 300 | 237 | 237 | 0 | 0 | present modifier (61); line N: actual argument o1 of kp1 is present on the device at the call (a copy-in/copy-out argument would not be) (4); defaultmap(present: aggregate) (2); defaultmap(present: allocatable) (2) |
| `b4` | 300 | 2 | 2 | 0 | 0 | module variables (declare target visibility) (291); declare target variable (290); user-defined reduction (184); declare mapper (182) |
| `b5` | 300 | 104 | 104 | 0 | 0 | module variables (declare target visibility) (182); present modifier (43); defaultmap(present: aggregate) (3); defaultmap(present: allocatable) (2) |
| `s1` | 9994 | 17 | 17 | 0 | 0 | module variables (declare target visibility) (9804); declare target variable (9512); user-defined reduction (5997); declare mapper (5945) |

## Coverage and rates by base-language feature

Per feature: programs with it; per toolchain the agree rate among those it compiled, then wrong_code / ice / run_error counts (compile rejections are features not supported, not failures). Features in fewer than 10 programs are listed by name only.

### `b0` (control)

| feature | programs | afar agree w/i/r | cce19 agree w/i/r | cce20 agree w/i/r | cce21 agree w/i/r |
|---|---|---|---|---|---|

### `b1` (1: element types and kinds)

| feature | programs | afar agree w/i/r | cce19 agree w/i/r | cce20 agree w/i/r | cce21 agree w/i/r |
|---|---|---|---|---|---|
| decl:allocatable_char | 70 | 95% 3/0/0 | 57% 0/16/0 | 65% 0/23/0 | 63% 0/23/0 |
| decl:allocatable_complex4 | 79 | 97% 2/0/0 | 74% 2/9/0 | 71% 4/17/0 | 68% 5/17/0 |
| decl:allocatable_complex8 | 85 | 95% 2/0/1 | 63% 0/19/0 | 65% 2/26/0 | 61% 3/26/0 |
| decl:allocatable_int1 | 73 | 91% 3/0/2 | 61% 2/15/0 | 63% 4/22/0 | 60% 5/22/0 |
| decl:allocatable_int2 | 74 | 96% 2/0/0 | 60% 1/16/0 | 63% 6/19/0 | 59% 6/19/0 |
| decl:allocatable_int8 | 81 | 95% 2/0/1 | 56% 2/17/0 | 61% 5/25/0 | 57% 5/25/0 |
| decl:allocatable_logical | 75 | 90% 2/0/3 | 51% 2/15/0 | 53% 4/28/0 | 49% 4/28/0 |
| decl:allocatable_real4 | 83 | 97% 0/0/2 | 63% 0/16/0 | 63% 1/27/0 | 59% 1/27/0 |
| decl:allocatable_real8 | 107 | 95% 1/0/3 | 69% 2/16/0 | 66% 6/28/0 | 60% 9/28/0 |
| decl:explicit_char | 121 | 92% 3/0/4 | 67% 3/16/0 | 65% 8/30/0 | 59% 10/30/0 |
| decl:explicit_complex4 | 113 | 94% 2/0/3 | 57% 2/24/0 | 58% 5/39/0 | 55% 6/39/0 |
| decl:explicit_complex8 | 111 | 93% 4/0/2 | 65% 1/19/0 | 62% 5/34/0 | 58% 7/34/0 |
| decl:explicit_int1 | 126 | 94% 3/0/2 | 59% 2/27/0 | 57% 7/42/0 | 51% 9/42/0 |
| decl:explicit_int2 | 110 | 98% 1/0/1 | 67% 1/19/0 | 63% 4/35/0 | 60% 5/35/0 |
| decl:explicit_int8 | 115 | 93% 4/0/2 | 63% 0/24/0 | 57% 3/42/0 | 52% 6/42/0 |
| decl:explicit_logical | 117 | 95% 2/0/2 | 66% 3/20/0 | 68% 4/30/0 | 63% 7/30/0 |
| decl:explicit_real4 | 106 | 91% 4/0/3 | 56% 2/25/0 | 60% 5/35/0 | 55% 6/35/0 |
| decl:explicit_real8 | 172 | 95% 3/0/3 | 57% 3/39/0 | 58% 6/60/0 | 55% 8/60/0 |
| out:char | 14 | 92% 1/0/0 | 0% 0/4/0 | 62% 0/5/0 | 55% 0/5/0 |
| out:complex4 | 21 | 86% 1/0/1 | 90% 1/0/0 | 81% 1/3/0 | 76% 2/3/0 |
| out:complex8 | 27 | 96% 1/0/0 | 62% 0/5/0 | 62% 1/9/0 | 52% 3/9/0 |
| out:int1 | 29 | 95% 1/0/0 | 85% 1/1/0 | 62% 3/7/0 | 56% 4/7/0 |
| out:int2 | 18 | 100% 0/0/0 | 78% 0/2/0 | 67% 3/2/0 | 69% 2/2/0 |
| out:int8 | 28 | 100% 0/0/0 | 60% 1/3/0 | 50% 3/9/0 | 46% 4/9/0 |
| out:logical | 17 | 100% 0/0/0 | 50% 2/1/0 | 53% 2/5/0 | 53% 2/5/0 |
| out:real4 | 25 | 94% 0/0/1 | 60% 0/4/0 | 70% 0/7/0 | 67% 0/7/0 |
| out:real8 | 32 | 96% 1/0/0 | 52% 1/9/0 | 52% 2/13/0 | 47% 3/13/0 |
| real_kind_conversion | 15 | 100% 0/0/0 | 50% 1/2/0 | 67% 1/4/0 | 64% 1/4/0 |
| red:complex4:+ | 16 | 89% 1/0/0 | 80% 0/1/0 | 54% 2/4/0 | 38% 4/4/0 |
| red:complex4:clause | 11 | 83% 1/0/0 | 75% 0/1/0 | 62% 1/2/0 | 50% 2/2/0 |
| red:real4:clause | 10 | 67% 1/0/1 | 50% 0/3/0 | 44% 1/4/0 | 44% 1/4/0 |
| red:real8:clause | 10 | 100% 0/0/0 | 100% 0/0/0 | 86% 1/0/0 | 83% 1/0/0 |
| spell:double_precision | 145 | 94% 3/0/3 | 65% 1/27/0 | 67% 5/38/0 | 63% 8/38/0 |
| type:char | 183 | 94% 5/0/4 | 65% 3/30/0 | 64% 8/51/0 | 60% 10/51/0 |
| type:char_scalar | 183 | 94% 5/0/4 | 65% 3/30/0 | 64% 8/51/0 | 60% 10/51/0 |
| type:complex4 | 184 | 95% 4/0/3 | 63% 3/33/0 | 63% 8/55/0 | 59% 10/55/0 |
| type:complex8 | 182 | 94% 5/0/3 | 64% 1/36/0 | 64% 6/56/0 | 60% 8/56/0 |
| type:int1 | 186 | 93% 6/0/4 | 59% 3/42/0 | 60% 8/62/0 | 55% 11/62/0 |
| type:int2 | 176 | 97% 3/0/1 | 64% 2/34/0 | 63% 8/53/0 | 59% 10/53/0 |
| type:int8 | 182 | 94% 6/0/3 | 59% 2/40/0 | 59% 7/62/0 | 54% 10/62/0 |
| type:logical | 181 | 93% 4/0/5 | 63% 3/34/0 | 63% 6/55/0 | 58% 9/55/0 |
| type:real4 | 176 | 94% 4/0/4 | 58% 2/39/0 | 60% 6/59/0 | 55% 7/59/0 |
| type:real8 | 261 | 95% 4/0/6 | 61% 4/52/0 | 61% 10/83/0 | 57% 14/83/0 |
| view:char | 111 | 94% 3/0/2 | 67% 2/14/0 | 67% 6/26/0 | 63% 6/26/0 |
| view:complex4 | 80 | 97% 2/0/0 | 59% 2/13/0 | 62% 4/22/0 | 60% 3/22/0 |
| view:complex8 | 84 | 93% 3/0/1 | 61% 1/16/0 | 61% 5/25/0 | 59% 4/25/0 |
| view:int1 | 96 | 94% 3/0/1 | 46% 2/26/0 | 52% 5/37/0 | 47% 4/37/0 |
| view:int2 | 89 | 97% 2/0/0 | 60% 1/17/0 | 63% 5/26/0 | 58% 6/26/0 |
| view:int8 | 97 | 96% 2/0/1 | 54% 1/23/0 | 60% 3/31/0 | 56% 3/31/0 |
| view:logical | 83 | 93% 2/0/2 | 57% 2/18/0 | 60% 3/27/0 | 54% 4/27/0 |
| view:real4 | 87 | 97% 1/0/1 | 50% 1/22/0 | 55% 3/33/0 | 51% 2/33/0 |
| view:real8 | 114 | 94% 3/0/2 | 53% 2/23/0 | 57% 5/37/0 | 54% 5/37/0 |

Fewer than 10 programs: red:complex4:critical (1); red:complex4:plain (5); red:complex8:+ (9); red:complex8:clause (8); red:complex8:plain (2); red:int1:clause (9); red:int1:iand (3); red:int1:ieor (2); red:int1:ior (3); red:int1:max (1); red:int1:min (2); red:int1:plain (2); red:int2:clause (7); red:int2:iand (3); red:int2:ieor (2); red:int2:ior (1); red:int2:max (2); red:int2:min (1); red:int2:plain (1); red:int8:+ (1); red:int8:clause (7); red:int8:ieor (3); red:int8:min (4); red:int8:plain (1); red:logical:.eqv. (3); red:logical:.neqv. (3); red:logical:.or. (4); red:logical:atomic (1); red:logical:clause (7); red:logical:plain (2); red:real4:+ (3); red:real4:atomic (1); red:real4:max (4); red:real4:min (6); red:real4:plain (1); red:real8:+ (9); red:real8:atomic (3); red:real8:max (6); red:real8:min (3); red:real8:plain (3)

Base-language features among the most associated with a failure class (lift over the toolchain's rate): cce19 wrong_code: decl:explicit_char (3/58, lift 2.15); cce19 wrong_code: decl:explicit_logical (3/68, lift 1.83); cce19 wrong_code: type:char (3/93, lift 1.34); cce19 wrong_code: type:char_scalar (3/93, lift 1.34); cce19 wrong_code: decl:explicit_real8 (3/97, lift 1.28); cce19 wrong_code: type:complex4 (3/98, lift 1.27); cce20 wrong_code: out:int2 (3/15, lift 4.98); cce20 wrong_code: out:int8 (3/24, lift 3.11); cce20 wrong_code: out:int1 (3/26, lift 2.87); cce21 wrong_code: out:int8 (4/24, lift 2.67); cce21 wrong_code: out:int1 (4/25, lift 2.56)

### `b2` (2: derived types)

| feature | programs | afar agree w/i/r | cce19 agree w/i/r | cce20 agree w/i/r | cce21 agree w/i/r |
|---|---|---|---|---|---|
| dt:aos | 182 | 91% 5/0/8 | 74% 4/24/0 | 63% 8/54/0 | 61% 9/54/0 |
| dt:component:aos:integer | 182 | 91% 5/0/8 | 74% 4/24/0 | 63% 8/54/0 | 61% 9/54/0 |
| dt:component:aos:real8 | 108 | 90% 4/0/4 | 77% 2/13/0 | 65% 4/31/0 | 64% 4/31/0 |
| dt:component:nested:integer | 176 | 91% 6/0/5 | 69% 4/28/0 | 62% 7/54/0 | 59% 7/54/0 |
| dt:component:nested:real8 | 105 | 93% 3/0/2 | 68% 1/18/0 | 60% 3/36/0 | 57% 3/36/0 |
| dt:component:struct:integer | 300 | 91% 9/0/12 | 74% 8/41/0 | 65% 14/84/0 | 62% 16/84/0 |
| dt:component:struct:real8 | 185 | 91% 6/0/6 | 74% 4/25/0 | 65% 8/54/0 | 62% 9/54/0 |
| dt:default_init | 122 | 91% 2/0/6 | 76% 3/17/0 | 67% 5/32/0 | 64% 7/32/0 |
| dt:map:component_section | 33 | 92% 1/0/1 | 42% 1/10/0 | 39% 2/17/0 | 32% 2/17/0 |
| dt:map:components | 109 | 92% 2/0/4 | 63% 5/18/0 | 54% 9/37/0 | 51% 9/37/0 |
| dt:map:implicit | 168 | 91% 5/0/6 | 76% 2/22/0 | 65% 4/52/0 | 62% 6/52/0 |
| dt:map:mod:always | 27 | 91% 2/0/0 | 62% 0/6/0 | 44% 1/14/0 | 33% 2/14/0 |
| dt:map:mod:close | 26 | 89% 1/0/1 | 65% 0/6/0 | 67% 1/7/0 | 62% 1/7/0 |
| dt:map:mod:present | 22 | 81% 0/0/3 | 50% 1/4/0 | 53% 2/7/0 | 44% 2/7/0 |
| dt:map:whole | 123 | 88% 5/0/7 | 72% 3/19/0 | 63% 6/36/0 | 60% 7/36/0 |
| dt:nested | 176 | 91% 6/0/5 | 69% 4/28/0 | 62% 7/54/0 | 59% 7/54/0 |
| dt:out:dr | 58 | 98% 0/0/1 | 69% 1/11/0 | 63% 2/18/0 | 59% 3/18/0 |
| dt:out:dr%nd | 27 | 95% 1/0/0 | 69% 1/4/0 | 61% 1/8/0 | 50% 1/8/0 |
| dt:out:ds | 30 | 83% 3/0/1 | 95% 1/0/0 | 75% 2/5/0 | 74% 2/5/0 |
| dt:scalar_component | 199 | 89% 6/0/10 | 76% 4/26/0 | 65% 6/57/0 | 63% 8/57/0 |
| dt:struct | 300 | 91% 9/0/12 | 74% 8/41/0 | 65% 14/84/0 | 62% 16/84/0 |
| dt:target_update_component | 21 | 100% 0/0/0 | 56% 1/3/0 | 50% 1/8/0 | 44% 1/8/0 |
| out:real8 | 22 | 92% 1/0/0 | 67% 1/3/0 | 44% 1/9/0 | 41% 1/9/0 |
| view:real8 | 159 | 91% 6/0/5 | 71% 4/23/0 | 60% 8/52/0 | 57% 9/52/0 |

Base-language features among the most associated with a failure class (lift over the toolchain's rate): afar wrong_code: dt:out:ds (3/24, lift 3.17); afar run_error: dt:map:mod:present (3/16, lift 3.56); cce19 wrong_code: dt:map:components (5/63, lift 1.85); cce19 ice: dt:map:component_section (10/19, lift 2.39)

### `b3` (3: allocatable, pointer, target, sections, procedures)

| feature | programs | afar agree w/i/r | cce19 agree w/i/r | cce20 agree w/i/r | cce21 agree w/i/r |
|---|---|---|---|---|---|
| al:allocatable_component | 185 | 80% 3/2/21 | 67% 8/27/1 | 59% 17/47/1 | 51% 11/47/16 |
| al:allocatable_scalar | 199 | 82% 3/1/21 | 62% 9/33/1 | 60% 15/52/1 | 53% 11/52/13 |
| al:depend_section | 33 | 65% 0/0/7 | 59% 0/7/0 | 48% 1/13/0 | 48% 1/13/0 |
| al:dummy:allocatable | 35 | 74% 0/3/2 | 47% 1/9/0 | 40% 4/14/0 | 21% 0/14/9 |
| al:dummy:assumed_shape | 103 | 85% 1/3/6 | 43% 9/23/1 | 47% 15/31/1 | 35% 4/31/16 |
| al:dummy:explicit | 64 | 75% 0/2/10 | 47% 7/12/0 | 52% 11/16/0 | 39% 3/16/11 |
| al:dummy:intent_in | 85 | 80% 1/2/9 | 50% 9/15/1 | 55% 13/19/1 | 39% 4/19/17 |
| al:dummy:intent_inout | 114 | 81% 1/3/11 | 45% 10/24/1 | 49% 16/33/1 | 35% 5/33/19 |
| al:dummy:intent_out | 13 | 83% 0/0/2 | 57% 1/2/0 | 64% 1/3/0 | 64% 0/3/1 |
| al:dummy:optional | 23 | 93% 0/1/0 | 44% 3/6/0 | 41% 3/10/0 | 20% 1/10/5 |
| al:dummy:pointer | 13 | 78% 0/1/1 | 62% 1/2/0 | 58% 3/2/0 | 36% 1/2/4 |
| al:dummy:value | 15 | 70% 1/0/2 | 56% 2/2/0 | 58% 2/3/0 | 11% 0/3/5 |
| al:kernel_in_internal_procedure | 117 | 80% 1/3/12 | 47% 10/24/1 | 50% 17/33/1 | 35% 6/33/20 |
| al:optional_absent_in_map | 36 | 52% 0/2/9 | 58% 4/4/0 | 56% 5/9/0 | 3% 0/9/20 |
| al:pointer_component | 182 | 82% 4/2/18 | 58% 9/34/1 | 56% 17/50/1 | 49% 11/50/14 |
| al:pointer_output:alloc | 66 | 79% 1/1/6 | 61% 3/10/0 | 56% 8/16/0 | 47% 5/16/6 |
| al:pointer_output:target | 66 | 72% 3/3/5 | 60% 3/11/2 | 57% 5/18/2 | 46% 3/18/8 |
| al:strided_update | 18 | 91% 0/0/1 | - 0/0/0 | - 0/0/0 | - 0/0/0 |
| al:structure_dummy | 79 | 78% 1/2/8 | 47% 7/18/0 | 47% 13/23/0 | 30% 4/23/16 |
| al:target_attribute | 169 | 84% 2/1/16 | 55% 9/34/2 | 54% 13/53/2 | 42% 12/53/17 |
| dt:component:struct:integer | 253 | 81% 5/2/26 | 63% 11/43/1 | 57% 21/69/1 | 50% 13/69/20 |
| dt:map:components | 175 | 79% 5/2/17 | 57% 9/32/1 | 52% 18/50/1 | 44% 10/50/17 |
| dt:map:implicit | 68 | 75% 0/1/9 | 57% 4/12/0 | 52% 5/21/0 | 46% 2/21/4 |
| dt:map:mod:always | 12 | 100% 0/0/0 | 57% 1/2/0 | 45% 3/3/0 | 45% 1/3/2 |
| dt:map:mod:close | 11 | 67% 1/1/0 | 75% 1/1/0 | 60% 1/3/0 | 50% 1/3/1 |
| dt:map:whole | 73 | 67% 4/1/10 | 59% 2/14/0 | 46% 6/24/0 | 37% 2/24/7 |
| dt:struct | 253 | 81% 5/2/26 | 63% 11/43/1 | 57% 21/69/1 | 50% 13/69/20 |
| dt:target_update_component | 30 | 88% 1/0/1 | 50% 1/5/0 | 50% 2/6/0 | 40% 0/6/3 |

Fewer than 10 programs: dt:map:mod:present (9)

Base-language features among the most associated with a failure class (lift over the toolchain's rate): afar wrong_code: dt:map:whole (4/45, lift 3.75); afar ice: al:dummy:allocatable (3/19, lift 11.11); afar ice: al:pointer_output:target (3/39, lift 5.41); afar ice: al:dummy:assumed_shape (3/67, lift 3.15); afar ice: al:dummy:intent_inout (3/78, lift 2.71); afar run_error: al:optional_absent_in_map (9/23, lift 3.18); afar run_error: al:depend_section (7/20, lift 2.84); cce19 wrong_code: al:optional_absent_in_map (4/19, lift 2.66); cce19 wrong_code: al:dummy:explicit (7/36, lift 2.46); cce19 wrong_code: al:dummy:optional (3/16, lift 2.37); cce19 wrong_code: al:dummy:intent_in (9/50, lift 2.28); cce21 run_error: al:optional_absent_in_map (20/30, lift 7.81); cce21 run_error: al:dummy:allocatable (9/29, lift 3.64); cce21 run_error: al:structure_dummy (16/61, lift 3.07); cce21 run_error: al:dummy:intent_in (17/66, lift 3.02); cce21 run_error: al:dummy:optional (5/20, lift 2.93); cce21 run_error: al:dummy:explicit (11/49, lift 2.63); cce21 run_error: al:kernel_in_internal_procedure (20/91, lift 2.57); cce21 run_error: al:dummy:intent_inout (19/88, lift 2.53)

### `b4` (4: declare target, mapper, user reduction, modules)

| feature | programs | afar agree w/i/r | cce19 agree w/i/r | cce20 agree w/i/r | cce21 agree w/i/r |
|---|---|---|---|---|---|
| dc:call:gd1 | 52 | 86% 1/0/3 | 50% 2/3/2 | 59% 1/4/2 | 56% 6/11/0 |
| dc:call:gd2 | 43 | 77% 1/0/5 | 30% 0/7/0 | 43% 0/8/0 | 39% 1/16/0 |
| dc:call:gm0 | 65 | 85% 2/0/4 | 20% 2/12/1 | 32% 1/15/1 | 37% 5/27/0 |
| dc:call_across_modules | 175 | 91% 3/0/7 | 53% 1/16/3 | 55% 2/22/4 | 56% 11/46/0 |
| dc:declare_mapper:default | 68 | 89% 1/0/4 | 53% 1/6/0 | 45% 2/10/0 | 49% 4/23/0 |
| dc:declare_mapper:named | 113 | 90% 2/0/5 | 58% 0/6/4 | 50% 1/11/8 | 63% 4/26/0 |
| dc:declare_reduction | 39 | - 0/0/0 | 0% 0/1/0 | 0% 0/2/0 | 0% 0/7/0 |
| dc:declare_reduction_available | 182 | 91% 4/0/6 | 52% 1/14/3 | 50% 2/20/7 | 60% 5/47/0 |
| dc:declare_target_array | 256 | 91% 4/0/11 | 50% 3/21/4 | 52% 5/30/7 | 58% 15/66/0 |
| dc:declare_target_enter | 168 | 90% 1/0/10 | - 0/0/0 | - 0/0/0 | 61% 8/41/0 |
| dc:declare_target_output | 73 | 88% 2/0/4 | 31% 0/6/2 | 39% 1/10/3 | 56% 4/20/0 |
| dc:declare_target_structure | 183 | 92% 5/0/5 | 48% 3/17/3 | 52% 6/22/4 | 57% 15/46/0 |
| dc:declare_target_to | 114 | 92% 4/0/2 | 52% 3/23/4 | 53% 6/32/7 | 53% 9/32/0 |
| dc:device_function_reads_module_var | 185 | 91% 3/0/8 | 45% 3/17/3 | 52% 4/22/5 | 58% 13/45/0 |
| dc:map_with_named_mapper | 38 | 79% 1/0/3 | 0% 0/4/4 | 0% 0/5/8 | 46% 2/13/0 |
| dc:static_init | 169 | 91% 1/0/8 | 51% 2/13/4 | 48% 4/19/7 | 58% 12/42/0 |
| dt:map:components | 58 | 86% 2/0/3 | 71% 1/3/0 | 50% 3/8/1 | 49% 5/15/0 |
| dt:map:implicit | 64 | 88% 2/0/2 | 42% 0/5/1 | 44% 0/8/2 | 44% 3/22/0 |
| dt:map:mod:close | 10 | 75% 1/0/0 | 0% 0/1/0 | 0% 0/2/1 | 29% 0/5/0 |
| dt:map:mod:mapper(mmap) | 38 | 79% 1/0/3 | 0% 0/4/4 | 0% 0/5/8 | 46% 2/13/0 |
| dt:map:whole | 58 | 82% 1/0/5 | 10% 0/5/4 | 7% 0/6/8 | 49% 4/17/0 |
| dt:target_update_component | 31 | 64% 1/0/4 | 38% 1/4/0 | 45% 1/4/1 | 50% 2/10/0 |

Fewer than 10 programs: dt:map:mod:always (9); dt:map:mod:present (6)

Base-language features among the most associated with a failure class (lift over the toolchain's rate): afar wrong_code: dc:declare_target_to (4/73, lift 2.08); afar run_error: dc:call:gd2 (5/26, lift 3.04); cce19 wrong_code: dc:device_function_reads_module_var (3/44, lift 1.57); cce19 ice: dc:call:gm0 (12/20, lift 1.73); cce19 run_error: dc:declare_mapper:named (4/26, lift 2.65); cce19 run_error: dc:static_init (4/39, lift 1.77); cce19 run_error: dc:declare_reduction_available (3/40, lift 1.29); cce20 wrong_code: dt:map:components (3/24, lift 2.17); cce20 ice: dc:call:gm0 (15/25, lift 1.89); cce20 ice: dc:declare_mapper:default (10/22, lift 1.43); cce20 run_error: dt:map:whole (8/15, lift 6.93); cce20 run_error: dc:declare_mapper:named (8/40, lift 2.6); cce21 wrong_code: dc:call:gd1 (6/39, lift 2.04)

### `b5` (5: multiple translation units)

| feature | programs | afar agree w/i/r | cce19 agree w/i/r | cce20 agree w/i/r | cce21 agree w/i/r |
|---|---|---|---|---|---|
| dc:call:ga1 | 58 | 86% 3/0/3 | 69% 1/8/0 | 64% 1/19/0 | 62% 1/19/0 |
| dc:call:gb1 | 30 | 85% 2/0/1 | 73% 0/4/0 | 75% 0/6/0 | 71% 0/6/0 |
| dc:call:ge1 | 39 | 97% 0/0/1 | 59% 0/7/0 | 47% 2/17/0 | 44% 2/17/0 |
| dc:call:gs1 | 41 | 91% 2/0/1 | 65% 0/7/0 | 61% 0/15/0 | 58% 0/15/0 |
| mt:external_function | 199 | 92% 6/0/6 | 70% 4/30/0 | 64% 7/60/0 | 61% 8/60/0 |
| mt:file_set | 299 | 92% 8/0/10 | 70% 5/48/0 | 65% 10/87/0 | 62% 13/87/0 |
| mt:module_chain | 176 | 92% 6/0/4 | 68% 2/29/0 | 63% 5/55/0 | 60% 6/55/0 |
| mt:module_file | 257 | 91% 8/0/9 | 71% 4/39/0 | 65% 8/76/0 | 62% 10/76/0 |
| mt:submodule | 181 | 91% 6/0/7 | 67% 2/32/0 | 62% 5/60/0 | 58% 7/60/0 |

### `s1` (alloc, declare, derived, multitu, types)

| feature | programs | afar agree w/i/r | cce19 agree w/i/r | cce20 agree w/i/r | cce21 agree w/i/r |
|---|---|---|---|---|---|
| al:allocatable_component | 5908 | 80% 85/50/638 | 57% 92/398/39 | 59% 118/592/88 | 51% 236/1431/390 |
| al:allocatable_output_component | 520 | 77% 6/3/61 | 45% 9/39/4 | 51% 12/54/15 | 44% 14/146/47 |
| al:allocatable_scalar | 5871 | 82% 90/51/549 | 59% 91/363/33 | 61% 115/572/81 | 52% 260/1357/389 |
| al:depend_section | 904 | 54% 11/2/210 | 38% 6/77/2 | 49% 13/115/7 | 47% 41/260/0 |
| al:dummy:allocatable | 1378 | 70% 34/21/197 | 47% 29/103/13 | 45% 40/167/34 | 30% 54/392/212 |
| al:dummy:assumed_length | 139 | 77% 2/3/11 | 0% 0/11/0 | 42% 2/21/0 | 33% 5/42/18 |
| al:dummy:assumed_shape | 3029 | 79% 71/68/270 | 50% 72/214/23 | 51% 96/332/46 | 34% 120/809/475 |
| al:dummy:char_len | 244 | 73% 5/4/26 | 15% 2/21/0 | 44% 4/33/1 | 30% 7/77/34 |
| al:dummy:explicit | 1953 | 70% 45/16/295 | 48% 41/153/11 | 49% 61/233/29 | 32% 66/537/305 |
| al:dummy:intent_in | 2549 | 73% 55/54/300 | 47% 56/183/22 | 49% 82/283/48 | 33% 94/690/382 |
| al:dummy:intent_inout | 3602 | 76% 79/67/416 | 51% 90/251/25 | 52% 115/390/58 | 34% 143/941/578 |
| al:dummy:intent_out | 317 | 75% 7/10/27 | 55% 6/19/4 | 53% 9/31/10 | 33% 17/74/60 |
| al:dummy:optional | 324 | 71% 10/9/39 | 38% 10/17/4 | 45% 10/33/7 | 27% 14/89/58 |
| al:dummy:pointer | 321 | 67% 9/7/49 | 62% 2/17/5 | 62% 4/27/9 | 39% 8/74/58 |
| al:dummy:value | 345 | 68% 10/6/45 | 47% 7/28/3 | 45% 11/45/6 | 26% 14/109/46 |
| al:kernel_in_internal_procedure | 3871 | 75% 81/69/465 | 52% 96/271/30 | 53% 121/412/66 | 36% 152/985/631 |
| al:optional_absent_in_map | 1382 | 53% 13/28/375 | 50% 46/103/6 | 56% 31/157/18 | 1% 3/367/627 |
| al:pointer_component | 5982 | 82% 90/46/544 | 58% 87/397/37 | 59% 116/594/80 | 51% 239/1434/392 |
| al:pointer_output:alloc | 1736 | 75% 32/17/188 | 63% 16/92/11 | 62% 24/161/27 | 51% 63/391/123 |
| al:pointer_output:target | 1695 | 77% 24/15/189 | 59% 14/95/10 | 60% 24/156/27 | 51% 61/401/111 |
| al:strided_update | 455 | 71% 10/8/58 | 0% 0/0/0 | - 0/0/0 | 0% 0/0/0 |
| al:structure_dummy | 3424 | 75% 76/62/407 | 49% 79/253/29 | 50% 111/382/64 | 34% 135/903/551 |
| al:target_attribute | 5218 | 82% 86/43/481 | 57% 77/365/34 | 58% 106/545/70 | 51% 220/1259/342 |
| dc:call:ga1 | 1141 | 80% 19/10/100 | 44% 9/97/11 | 46% 15/156/23 | 41% 38/359/57 |
| dc:call:gb1 | 786 | 77% 11/3/85 | 43% 8/73/4 | 50% 11/105/11 | 38% 30/252/48 |
| dc:call:gd1 | 777 | 78% 10/5/82 | 52% 7/56/3 | 52% 12/89/8 | 41% 33/239/46 |
| dc:call:gd2 | 738 | 77% 11/7/79 | 50% 8/55/4 | 49% 14/95/9 | 41% 34/223/39 |
| dc:call:ge1 | 833 | 76% 13/10/90 | 45% 15/58/3 | 50% 16/96/10 | 40% 27/252/46 |
| dc:call:gm0 | 1090 | 78% 27/7/103 | 48% 4/89/3 | 49% 16/130/13 | 41% 33/325/66 |
| dc:call:gs1 | 769 | 76% 15/4/87 | 46% 6/62/6 | 51% 11/97/10 | 43% 23/223/53 |
| dc:call_across_modules | 5909 | 81% 99/49/564 | 57% 77/410/38 | 59% 107/614/81 | 51% 236/1466/388 |
| dc:declare_mapper:default | 2357 | 78% 39/19/275 | 59% 36/162/3 | 62% 46/249/6 | 52% 83/572/144 |
| dc:declare_mapper:named | 3549 | 82% 56/28/320 | 52% 55/240/54 | 52% 76/368/118 | 51% 164/864/230 |
| dc:declare_reduction | 1510 | 0% 0/13/0 | 0% 0/65/0 | 0% 0/122/0 | 0% 0/286/0 |
| dc:declare_reduction_available | 5966 | 83% 80/46/468 | 55% 85/395/27 | 57% 101/615/56 | 49% 211/1430/341 |
| dc:declare_target_array | 8308 | 82% 135/63/781 | 56% 122/520/43 | 59% 167/800/96 | 51% 350/1994/544 |
| dc:declare_target_enter | 5546 | 82% 83/51/509 | - 0/0/0 | - 0/0/0 | 52% 220/1342/340 |
| dc:declare_target_output | 2463 | 80% 32/20/259 | 54% 36/136/12 | 57% 51/224/34 | 47% 141/589/181 |
| dc:declare_target_structure | 5988 | 82% 107/50/556 | 56% 83/401/28 | 58% 114/609/65 | 51% 229/1466/389 |
| dc:declare_target_to | 3731 | 81% 70/23/366 | 57% 131/575/47 | 59% 183/888/108 | 50% 161/889/265 |
| dc:device_function_reads_module_var | 5947 | 82% 104/36/561 | 56% 80/371/33 | 58% 119/571/72 | 51% 250/1414/403 |
| dc:map_with_named_mapper | 649 | 69% 11/6/93 | 11% 4/41/51 | 8% 2/71/108 | 43% 27/181/42 |
| dc:static_init | 4962 | 82% 80/27/458 | 57% 63/304/26 | 59% 100/470/59 | 52% 197/1184/322 |
| decl:allocatable_char | 2396 | 81% 37/21/234 | 50% 26/188/14 | 55% 37/274/39 | 49% 84/616/168 |
| decl:allocatable_complex4 | 2471 | 81% 40/19/246 | 60% 36/161/14 | 61% 45/242/32 | 52% 94/596/159 |
| decl:allocatable_complex8 | 2513 | 83% 34/20/233 | 60% 34/167/12 | 61% 48/248/36 | 53% 110/596/156 |
| decl:allocatable_int1 | 2517 | 82% 35/20/240 | 60% 32/146/13 | 61% 41/237/27 | 52% 104/618/157 |
| decl:allocatable_int2 | 2558 | 82% 38/14/244 | 54% 41/177/16 | 57% 56/267/36 | 52% 105/602/173 |
| decl:allocatable_int8 | 2589 | 80% 49/20/277 | 57% 37/175/14 | 59% 52/265/35 | 51% 107/643/169 |
| decl:allocatable_logical | 2511 | 80% 45/20/250 | 58% 32/170/11 | 60% 47/244/37 | 51% 94/610/169 |
| decl:allocatable_real4 | 2517 | 81% 47/18/245 | 56% 39/173/21 | 59% 47/262/40 | 51% 103/612/171 |
| decl:allocatable_real8 | 3551 | 80% 67/34/345 | 56% 47/251/26 | 57% 66/367/66 | 51% 143/852/243 |
| decl:explicit_char | 3635 | 82% 59/21/336 | 57% 48/248/15 | 59% 70/387/46 | 51% 165/894/231 |
| decl:explicit_complex4 | 3721 | 82% 46/29/355 | 58% 58/236/26 | 59% 82/363/54 | 52% 160/872/259 |
| decl:explicit_complex8 | 3687 | 81% 69/26/340 | 55% 52/251/23 | 58% 73/378/49 | 50% 156/894/258 |
| decl:explicit_int1 | 3687 | 81% 62/22/372 | 58% 61/251/15 | 59% 84/386/38 | 51% 149/902/235 |
| decl:explicit_int2 | 3742 | 83% 55/29/331 | 57% 52/268/20 | 58% 68/405/56 | 51% 157/929/229 |
| decl:explicit_int8 | 3715 | 82% 52/30/358 | 56% 64/260/22 | 58% 76/394/48 | 52% 141/907/232 |
| decl:explicit_logical | 3713 | 83% 57/29/317 | 57% 58/253/22 | 59% 75/383/47 | 51% 170/884/232 |
| decl:explicit_real4 | 3710 | 82% 52/31/334 | 60% 50/252/20 | 60% 72/385/49 | 51% 153/883/242 |
| decl:explicit_real8 | 5152 | 82% 85/39/494 | 56% 82/362/32 | 58% 113/563/62 | 51% 220/1273/311 |
| dt:aos | 5915 | 82% 89/46/574 | 58% 76/400/35 | 59% 107/624/78 | 51% 217/1442/415 |
| dt:component:aos:integer | 5915 | 82% 89/46/574 | 58% 76/400/35 | 59% 107/624/78 | 51% 217/1442/415 |
| dt:component:aos:real8 | 3529 | 83% 49/23/329 | 59% 40/239/21 | 60% 58/363/48 | 52% 127/867/237 |
| dt:component:nested:integer | 5977 | 81% 90/44/594 | 57% 90/402/34 | 59% 121/623/76 | 52% 249/1441/379 |
| dt:component:nested:real8 | 3594 | 82% 55/26/343 | 56% 44/256/25 | 59% 59/391/50 | 51% 139/886/240 |
| dt:component:struct:integer | 9924 | 82% 159/76/938 | 57% 148/680/62 | 58% 200/1036/137 | 51% 410/2403/645 |
| dt:component:struct:real8 | 5969 | 82% 94/39/546 | 57% 76/421/41 | 59% 102/628/87 | 51% 234/1462/387 |
| dt:default_init | 3631 | 81% 54/36/344 | 55% 52/270/27 | 57% 73/401/52 | 51% 158/879/238 |
| dt:map:component_section | 1796 | 80% 35/18/150 | 53% 17/120/11 | 52% 31/201/31 | 45% 63/477/111 |
| dt:map:components | 5528 | 81% 99/45/487 | 52% 76/392/30 | 53% 113/618/76 | 46% 214/1462/344 |
| dt:map:implicit | 4673 | 79% 92/32/483 | 54% 65/334/22 | 55% 102/548/48 | 46% 193/1235/307 |
| dt:map:mod:always | 799 | 73% 13/7/105 | 36% 6/73/18 | 40% 9/120/36 | 44% 30/258/41 |
| dt:map:mod:close | 922 | 64% 13/7/174 | 42% 10/64/15 | 46% 14/108/36 | 43% 30/268/55 |
| dt:map:mod:mapper(mmap) | 649 | 69% 11/6/93 | 11% 4/41/51 | 8% 2/71/108 | 43% 27/181/42 |
| dt:map:mod:present | 603 | 66% 10/6/105 | 47% 7/44/5 | 49% 10/62/16 | 43% 26/145/38 |
| dt:map:whole | 3787 | 76% 58/30/466 | 49% 43/262/56 | 51% 62/415/121 | 47% 151/1005/232 |
| dt:nested | 5977 | 81% 90/44/594 | 57% 90/402/34 | 59% 121/623/76 | 52% 249/1441/379 |
| dt:out:dr | 1243 | 80% 20/6/126 | 50% 20/85/11 | 53% 27/144/22 | 48% 52/314/85 |
| dt:out:dr%nd | 567 | 77% 7/6/63 | 49% 14/30/3 | 54% 14/58/13 | 45% 25/137/53 |
| dt:out:ds | 549 | 78% 11/5/58 | 55% 9/30/1 | 49% 22/55/11 | 45% 39/132/35 |
| dt:scalar_component | 5974 | 81% 93/46/581 | 56% 92/421/39 | 58% 121/629/87 | 51% 249/1450/388 |
| dt:struct | 9924 | 82% 159/76/938 | 57% 148/680/62 | 58% 200/1036/137 | 51% 410/2403/645 |
| dt:target_update_component | 1014 | 70% 20/12/137 | 36% 6/58/3 | 45% 10/93/10 | 37% 31/227/32 |
| mt:external_function | 5880 | 81% 99/46/556 | 57% 88/389/27 | 58% 129/609/64 | 51% 240/1453/376 |
| mt:file_set | 9924 | 82% 159/76/938 | 57% 148/680/62 | 58% 200/1036/137 | 51% 410/2403/645 |
| mt:module_chain | 5952 | 82% 92/43/554 | 55% 92/430/36 | 58% 114/633/81 | 52% 251/1406/384 |
| mt:module_file | 8631 | 82% 134/67/809 | 57% 139/593/55 | 58% 180/900/121 | 52% 366/2053/568 |
| mt:submodule | 5927 | 81% 100/46/567 | 55% 81/420/42 | 58% 113/629/83 | 51% 241/1420/391 |
| out:char | 277 | 75% 7/3/31 | 0% 0/18/0 | 51% 2/31/15 | 42% 9/70/34 |
| out:complex4 | 635 | 77% 8/4/68 | 56% 13/33/4 | 55% 18/56/11 | 50% 32/135/45 |
| out:complex8 | 585 | 82% 6/4/49 | 55% 6/36/3 | 56% 12/59/12 | 50% 23/141/36 |
| out:int1 | 655 | 77% 10/1/75 | 54% 6/40/3 | 55% 6/76/10 | 47% 23/164/50 |
| out:int2 | 672 | 80% 12/5/57 | 55% 2/42/5 | 62% 5/59/11 | 51% 25/162/41 |
| out:int8 | 654 | 74% 12/6/78 | 53% 10/46/4 | 57% 17/69/9 | 49% 29/155/43 |
| out:logical | 661 | 80% 15/5/57 | 54% 11/35/3 | 55% 17/64/11 | 51% 31/146/43 |
| out:real4 | 619 | 76% 15/5/64 | 65% 6/30/3 | 61% 13/52/8 | 49% 18/149/47 |
| out:real8 | 1128 | 75% 25/9/132 | 50% 18/81/9 | 57% 21/123/17 | 48% 55/253/95 |
| real_kind_conversion | 504 | 78% 8/2/53 | 65% 7/21/2 | 60% 13/36/10 | 48% 22/116/39 |
| red:complex4:+ | 360 | 69% 16/4/43 | 54% 6/20/4 | 58% 6/38/6 | 45% 26/82/23 |
| red:complex4:clause | 292 | 65% 10/4/39 | 64% 2/12/4 | 63% 2/27/5 | 52% 11/57/19 |
| red:complex4:plain | 67 | 87% 1/0/6 | 25% 4/4/0 | 46% 4/8/1 | 23% 16/22/5 |
| red:complex8:+ | 403 | 67% 14/3/60 | 62% 4/20/3 | 60% 7/38/6 | 46% 26/90/34 |
| red:complex8:clause | 329 | 65% 11/3/49 | 72% 1/13/2 | 68% 2/26/5 | 52% 11/65/29 |
| red:complex8:plain | 75 | 77% 1/0/11 | 28% 3/7/1 | 31% 5/12/1 | 27% 15/24/5 |
| red:int1:atomic | 45 | 74% 3/0/3 | 89% 0/1/0 | 71% 0/3/1 | 48% 2/7/3 |
| red:int1:clause | 272 | 72% 6/2/33 | 58% 1/13/3 | 67% 3/20/4 | 52% 11/48/20 |
| red:int1:iand | 78 | 76% 1/1/7 | 46% 0/5/0 | 62% 0/6/0 | 42% 3/19/3 |
| red:int1:ieor | 80 | 75% 3/1/9 | 61% 1/6/2 | 62% 1/8/3 | 52% 4/15/8 |
| red:int1:ior | 83 | 71% 4/0/10 | 58% 0/5/0 | 61% 1/8/0 | 53% 3/17/5 |
| red:int1:max | 94 | 73% 4/0/11 | 67% 0/5/1 | 62% 3/11/1 | 48% 5/23/5 |
| red:int1:min | 77 | 78% 3/0/6 | 47% 2/5/0 | 52% 3/7/1 | 37% 4/20/5 |
| red:int1:plain | 65 | 84% 3/0/5 | 44% 2/8/0 | 44% 4/11/0 | 35% 6/25/1 |
| red:int2:atomic | 26 | 80% 0/0/3 | 50% 1/0/0 | 50% 1/2/0 | 41% 1/6/3 |
| red:int2:clause | 268 | 72% 7/4/31 | 60% 1/15/0 | 60% 2/25/2 | 46% 9/65/20 |
| red:int2:critical | 12 | 22% 5/0/2 | 0% 0/3/0 | 0% 0/5/0 | 0% 0/11/0 |
| red:int2:iand | 77 | 74% 1/0/11 | 47% 0/9/0 | 48% 0/14/0 | 39% 2/26/6 |
| red:int2:ieor | 79 | 73% 4/0/9 | 39% 2/7/0 | 52% 2/10/0 | 45% 6/23/3 |
| red:int2:ior | 86 | 63% 3/3/13 | 100% 0/0/0 | 78% 0/4/0 | 45% 3/20/6 |
| red:int2:max | 78 | 71% 4/0/9 | 47% 1/6/0 | 48% 3/10/0 | 38% 3/26/5 |
| red:int2:min | 76 | 70% 3/1/10 | 36% 0/6/0 | 46% 0/11/3 | 38% 6/22/6 |
| red:int2:plain | 74 | 71% 1/0/16 | 33% 1/10/0 | 44% 2/16/1 | 34% 9/29/3 |
| red:int8:+ | 76 | 52% 5/1/13 | 35% 1/10/0 | 31% 3/15/0 | 27% 4/28/5 |
| red:int8:atomic | 47 | 67% 1/1/6 | 38% 1/2/0 | 54% 1/5/0 | 21% 7/14/2 |
| red:int8:clause | 264 | 68% 5/2/34 | 49% 2/17/0 | 59% 4/24/2 | 48% 6/57/21 |
| red:int8:critical | 11 | 25% 4/1/1 | 0% 0/4/0 | 0% 0/5/0 | 0% 0/10/0 |
| red:int8:iand | 65 | 71% 3/0/9 | 36% 1/3/0 | 59% 0/7/0 | 36% 3/18/8 |
| red:int8:ieor | 63 | 73% 0/0/9 | 40% 0/5/0 | 45% 1/9/2 | 41% 5/13/5 |
| red:int8:ior | 64 | 63% 0/2/9 | 29% 1/7/0 | 42% 3/12/0 | 40% 5/19/1 |
| red:int8:max | 72 | 68% 2/1/10 | 33% 2/5/1 | 50% 2/5/1 | 38% 4/18/7 |
| red:int8:min | 69 | 75% 0/0/8 | 33% 1/6/0 | 56% 1/6/1 | 30% 3/21/7 |
| red:int8:plain | 64 | 74% 0/0/11 | 0% 3/11/1 | 14% 5/18/2 | 10% 11/28/6 |
| red:logical:.and. | 100 | 73% 2/0/15 | 39% 0/9/0 | 45% 0/16/0 | 35% 2/41/5 |
| red:logical:.eqv. | 110 | 77% 6/1/9 | 42% 0/9/0 | 48% 0/16/1 | 38% 4/36/7 |
| red:logical:.neqv. | 95 | 77% 1/1/10 | 58% 0/5/1 | 54% 1/9/2 | 49% 4/22/5 |
| red:logical:.or. | 103 | 78% 1/0/12 | 32% 4/10/0 | 43% 4/12/0 | 40% 9/20/8 |
| red:logical:atomic | 42 | 54% 3/1/8 | 44% 0/4/0 | 55% 0/5/0 | 36% 1/12/5 |
| red:logical:clause | 268 | 74% 5/1/32 | 50% 3/15/1 | 57% 4/24/3 | 50% 10/56/16 |
| red:logical:plain | 66 | 94% 0/0/3 | 33% 1/7/0 | 29% 1/14/0 | 20% 7/34/4 |
| red:real4:+ | 129 | 78% 2/1/13 | 50% 4/7/0 | 58% 2/17/0 | 34% 13/36/12 |
| red:real4:atomic | 49 | 70% 1/0/5 | 55% 1/2/0 | 62% 0/5/0 | 26% 4/16/3 |
| red:real4:clause | 266 | 75% 8/2/25 | 64% 1/10/3 | 63% 3/22/4 | 48% 13/58/17 |
| red:real4:critical | 10 | 0% 3/0/3 | 0% 0/3/0 | 0% 0/5/0 | 0% 0/10/0 |
| red:real4:max | 149 | 74% 5/1/17 | 56% 2/6/1 | 57% 3/13/4 | 37% 14/37/9 |
| red:real4:min | 134 | 73% 6/0/13 | 50% 3/9/2 | 50% 5/13/2 | 46% 8/32/9 |
| red:real4:plain | 69 | 84% 0/0/9 | 30% 7/7/0 | 39% 7/10/2 | 25% 16/20/7 |
| red:real8:+ | 172 | 73% 4/2/14 | 53% 2/11/1 | 56% 1/19/1 | 46% 6/44/8 |
| red:real8:atomic | 60 | 78% 3/0/3 | 36% 2/4/0 | 44% 1/9/0 | 31% 6/19/3 |
| red:real8:clause | 382 | 80% 9/2/23 | 53% 0/26/4 | 55% 0/40/5 | 55% 8/84/13 |
| red:real8:critical | 22 | 42% 5/0/2 | 0% 0/3/0 | 0% 0/6/0 | 0% 0/17/0 |
| red:real8:max | 204 | 73% 10/1/18 | 40% 1/24/3 | 46% 1/32/4 | 41% 12/66/7 |
| red:real8:min | 195 | 78% 8/0/12 | 35% 2/13/0 | 43% 3/24/0 | 43% 8/59/4 |
| red:real8:plain | 73 | 70% 3/1/13 | 24% 3/10/0 | 34% 4/15/0 | 17% 12/39/2 |
| spell:double_precision | 4238 | 81% 76/41/406 | 57% 59/288/28 | 59% 86/443/69 | 52% 162/1018/286 |
| type:char | 5937 | 82% 94/40/560 | 55% 74/428/29 | 57% 107/650/82 | 50% 247/1487/389 |
| type:char_scalar | 5937 | 82% 94/40/560 | 55% 74/428/29 | 57% 107/650/82 | 50% 247/1487/389 |
| type:complex4 | 5928 | 82% 83/47/572 | 59% 88/386/40 | 60% 122/586/82 | 52% 250/1409/398 |
| type:complex8 | 5934 | 82% 101/45/550 | 57% 84/401/34 | 59% 116/594/80 | 51% 250/1425/396 |
| type:int1 | 5933 | 81% 94/41/581 | 59% 90/381/28 | 60% 122/593/65 | 51% 244/1453/374 |
| type:int2 | 6003 | 83% 89/39/543 | 56% 92/429/34 | 58% 121/648/87 | 51% 251/1466/378 |
| type:int8 | 6035 | 81% 94/49/603 | 57% 98/411/34 | 58% 122/628/80 | 52% 240/1486/385 |
| type:logical | 5938 | 82% 95/46/541 | 58% 88/406/30 | 59% 119/602/77 | 51% 252/1422/385 |
| type:real4 | 5926 | 82% 91/46/546 | 58% 86/414/38 | 59% 114/625/84 | 51% 246/1429/392 |
| type:real8 | 8304 | 81% 137/70/793 | 57% 122/582/54 | 58% 170/887/120 | 51% 339/2040/526 |
| view:char | 4507 | 82% 71/27/428 | 52% 51/336/23 | 55% 84/525/63 | 48% 192/1186/295 |
| view:complex4 | 3787 | 81% 52/25/372 | 55% 39/263/24 | 56% 69/412/54 | 48% 158/1011/243 |
| view:complex8 | 3799 | 81% 68/28/365 | 53% 47/277/23 | 56% 70/423/56 | 47% 153/1026/261 |
| view:int1 | 3841 | 80% 65/26/396 | 54% 55/267/21 | 55% 78/435/49 | 48% 161/1046/226 |
| view:int2 | 3878 | 81% 57/20/372 | 51% 54/311/20 | 53% 79/472/58 | 46% 161/1078/247 |
| view:int8 | 3860 | 80% 64/27/405 | 51% 55/302/25 | 53% 77/465/59 | 47% 150/1086/235 |
| view:logical | 3780 | 81% 61/25/366 | 52% 51/281/20 | 55% 75/439/50 | 47% 155/1019/232 |
| view:real4 | 3785 | 81% 56/21/378 | 52% 47/293/22 | 54% 66/458/55 | 45% 157/1048/245 |
| view:real8 | 7153 | 82% 113/48/684 | 55% 90/525/46 | 56% 135/807/96 | 49% 288/1849/451 |

Fewer than 10 programs: red:complex4:critical (8); red:complex8:critical (3); red:int1:critical (8); red:logical:critical (6)

Base-language features among the most associated with a failure class (lift over the toolchain's rate): afar wrong_code: red:int1:atomic (3/23, lift 5.29); afar wrong_code: red:int8:+ (5/40, lift 5.07); afar ice: red:int2:ior (3/51, lift 4.99); afar ice: al:dummy:intent_out (10/174, lift 4.88); afar run_error: al:depend_section (210/483, lift 2.99); afar run_error: al:optional_absent_in_map (375/892, lift 2.89); afar run_error: red:int8:+ (13/40, lift 2.23); afar run_error: dt:map:mod:close (174/545, lift 2.19); cce19 wrong_code: red:real4:plain (7/23, lift 4.6); cce19 wrong_code: al:dummy:optional (10/50, lift 3.02); cce19 run_error: dc:map_with_named_mapper (51/113, lift 16.28); cce19 run_error: dt:map:mod:mapper(mmap) (51/113, lift 16.28); cce19 run_error: dt:map:mod:always (18/165, lift 3.94); cce19 run_error: dt:map:mod:close (15/179, lift 3.02); cce19 run_error: al:dummy:optional (4/50, lift 2.89); cce19 run_error: al:dummy:pointer (5/63, lift 2.86); cce20 wrong_code: red:real4:plain (7/31, lift 3.74); cce20 wrong_code: red:complex8:plain (5/26, lift 3.19); cce20 run_error: dc:map_with_named_mapper (108/197, lift 13.26); cce20 run_error: dt:map:mod:mapper(mmap) (108/197, lift 13.26); cce20 run_error: out:char (15/99, lift 3.66); cce20 run_error: dt:map:mod:always (36/277, lift 3.14); cce20 run_error: dt:map:mod:close (36/294, lift 2.96); cce20 run_error: red:int2:min (3/26, lift 2.79); cce21 wrong_code: red:complex4:plain (16/56, lift 4.97); cce21 wrong_code: red:real4:plain (16/57, lift 4.88); cce21 wrong_code: red:complex8:plain (15/60, lift 4.35); cce21 wrong_code: red:int8:atomic (7/29, lift 4.2); cce21 wrong_code: red:int8:plain (11/50, lift 3.82); cce21 run_error: al:optional_absent_in_map (627/1007, lift 6.88); cce21 run_error: al:dummy:intent_out (60/226, lift 2.93); cce21 run_error: al:dummy:optional (58/223, lift 2.87); cce21 run_error: al:dummy:pointer (58/229, lift 2.8); cce21 run_error: al:kernel_in_internal_procedure (631/2751, lift 2.53); cce21 run_error: al:structure_dummy (551/2403, lift 2.53)

## Minimized reproducers

| run | file | toolchain | kind | also fails on | lines |
|---|---|---|---|---|---|
| `b1` | `data/findings/fuzz/b1-22-cce20.f90` | cce20 | wrong_code | cce19, cce21 | 144 -> 25 |
| `b1` | `data/findings/fuzz/b1-231-afar.f90` | afar | run_error | - | 109 -> 42 |
| `b1` | `data/findings/fuzz/b1-183-afar.f90` | afar | wrong_code | - | 100 -> 41 |
| `b1` | `data/findings/fuzz/b1-268-afar.f90` | afar | wrong_code | - | 81 -> 33 |
| `b1` | `data/findings/fuzz/b1-121-afar.f90` | afar | wrong_code | - | 135 -> 22 |
| `b1` | seed 111 | afar | wrong_code | - | not_reproduced: the failure does not reproduce: device fail None host=None ref 163685360 |
| `b2` | `data/findings/fuzz/b2-85-cce20.f90` | cce20 | wrong_code | cce19, cce21 | 63 -> 39 |
| `b2` | `data/findings/fuzz/b2-52-afar.f90` | afar | wrong_code | - | 127 -> 43 |
| `b2` | `data/findings/fuzz/b2-213-afar.f90` | afar | run_error | - | 98 -> 49 |
| `b2` | `data/findings/fuzz/b2-68-afar.f90` | afar | wrong_code | - | 107 -> 31 |
| `b2` | `data/findings/fuzz/b2-209-cce19.f90` | cce19 | wrong_code | cce20, cce21 | 86 -> 27 |
| `b3` | `data/findings/fuzz/b3-9-afar.f90` | afar | ice | - | 125 -> 85 |
| `b3` | `data/findings/fuzz/b3-278-cce19.f90` | cce19 | run_error | - | 84 -> 41 |
| `b3` | `data/findings/fuzz/b3-197-cce19.f90` | cce19 | run_error | cce20 | 141 -> 64 |
| `b3` | `data/findings/fuzz/b3-188-cce19.f90` | cce19 | ice | cce20, cce21 | 83 -> 62 |
| `b3` | `data/findings/fuzz/b3-190-cce21.f90` | cce21 | run_error | - | 127 -> 73 |
| `b3` | `data/findings/fuzz/b3-61-cce20.f90` | cce20 | wrong_code | cce19, cce21 | 168 -> 75 |
| `b3` | `data/findings/fuzz/b3-250-cce20.f90` | cce20 | wrong_code | cce19, cce21 | 153 -> 76 |
| `b3` | `data/findings/fuzz/b3-9-cce21.f90` | cce21 | run_error | afar | 125 -> 90 |
| `b3` | `data/findings/fuzz/b3-45-cce21.f90` | cce21 | run_error | afar | 138 -> 70 |
| `b3` | `data/findings/fuzz/b3-54-afar.f90` | afar | run_error | - | 117 -> 41 |
| `b3` | `data/findings/fuzz/b3-94-afar.f90` | afar | wrong_code | - | 176 -> 67 |
| `b3` | seed 92 | cce20 | wrong_code | - | withdrawn: minimizer defect: deleted the explicit map of the pointer component dr%pc (impli |
| `b3` | seed 11 | cce20 | wrong_code | - | not_reproduced: no reference outside the failing compiler family (another family's host run, or  |
| `b3` | seed 271 | cce19 | wrong_code | - | not_reproduced: the failure does not reproduce: device timeout None host=None ref 569481647 |
| `b4` | `data/findings/fuzz/b4-86-cce19.f90` | cce19 | run_error | cce20 | 167 -> 48 |
| `b4` | `data/findings/fuzz/b4-39-afar.f90` | afar | wrong_code | - | 154 -> 124 |
| `b4` | seed 253 | cce20 | wrong_code | - | not_reproduced: no reference outside the failing compiler family (another family's host run, or  |
| `b4` | seed 9 | afar | run_error | - | not_reproduced: no reference outside the failing compiler family (another family's host run, or  |
| `b5` | seed 11 | afar | wrong_code | - | not_reproduced: no reference outside the failing compiler family (another family's host run, or  |
| `b5` | seed 167 | afar | wrong_code | - | not_reproduced: no reference outside the failing compiler family (another family's host run, or  |
| `s1` | `data/findings/fuzz/s1-6888-cce21.f90` | cce21 | compile_reject | cce19, cce20 | 158 -> 29 |
| `s1` | `data/findings/fuzz/s1-2370-cce21.f90` | cce21 | compile_reject | cce19, cce20 | 222 -> 28 |
| `s1` | `data/findings/fuzz/s1-8634-cce21.f90` | cce21 | ice | cce19, cce20 | 151 -> 7 |
| `s1` | `data/findings/fuzz/s1-2592-cce21.f90` | cce21 | ice | cce19, cce20 | 189 -> 26 |
| `s1` | `data/findings/fuzz/s1-3463-cce21.f90` | cce21 | ice | cce19, cce20 | 252 -> 106 |
| `s1` | `data/findings/fuzz/s1-6085-cce21.f90` | cce21 | ice | cce20 | 216 -> 130 |

## Exclusions

What each group does not generate, because the model could not predict it or the spec leaves it open (offload.engine.fuzz_base EXCLUSIONS):

### types (stage 1: element types and kinds)

- floating-point values that are not exactly representable, floating-point division (other than by a power of two inside mod), transcendental intrinsics, products of two variables: the result would depend on rounding, contraction or reduction order
- product reductions of reals; max/min reductions of complex and any character reduction (not allowed by 5.2 §5.5.5)
- atomic updates of complex and character items
- character scalars referenced without an explicit map (5.2 defines a Fortran scalar variable to exclude character type, so the implicit rule for one is unclear; data/findings/afar-cce19-character-defaultmap.f90)
- logical values compared with == (not Fortran;.eqv. is used)
- lastprivate and in_reduction of typed items (integers only)

Sub-features (swarm): real4, real8, dp, complex4, complex8, logical, char, int1, int2, int8, typed_out, typed_red, typed_view, atomic_typed

### derived (stage 2: derived types)

- a structure mapped whole with from or alloc (it would copy back or leave undefined the components the kernel does not write)
- an array of structures mapped by component (ds(:)%u is not contiguous storage, 5.2 §5.8.3)
- structure elements in data-sharing or depend clauses (not variable or locator list items in Fortran, 5.2 §3.2.1)
- reductions, lastprivate or firstprivate of structure components
- polymorphic (class), parameterized and extended derived types

Sub-features (swarm): dt_nested, dt_aos, dt_scalar, dt_typed, dt_out, dt_whole, dt_comp, dt_implicit, dt_default_init, dt_section

### alloc (stage 3: allocatable, pointer, target, sections, procedures)

- a pointer component referenced while its structure is mapped whole or implicitly (association status undefined through the default mapper, 5.2 §5.8.3)
- pointers or allocatables changing association or allocation inside a data region, and allocatable or pointer arrays referenced implicitly through defaultmap (a firstprivate pointer would not map its target)
- non-contiguous array sections in map clauses (5.2 §5.8.3); strided sections only in target update
- dummy procedures (procedure arguments) called in a target region: an indirect call needs declare target indirect (5.2 §7.8.3), whose support the model cannot predict
- internal procedures holding a kernel of a nowait sequence (the dummies end before the target task)
- intent(in) dummies of arrays a kernel maps other than to (the copy back would define them)

Sub-features (swarm): al_ptr_out, al_target, al_alloc_scalar, al_comp_alloc, al_comp_ptr, al_stride_update, al_depend_section, al_proc, al_explicit_dummy, al_alloc_dummy, al_ptr_dummy, al_value, al_optional, al_optional_absent, al_intent_out, al_assumed_len

### declare (stage 4: declare target, mapper, user reduction, modules)

- declare target variables in map clauses or in data-sharing clauses other than shared (infinite reference count, 5.2 §5.8.1)
- link clauses and device_type(nohost/host)
- mappers that leave out a component a kernel references
- declare reduction with a combiner or initializer subroutine; user reductions in atomic/critical updates or in task reductions
- declare variant, metadirective and indirect calls

Sub-features (swarm): dc_modvar, dc_modvar_out, dc_static_init, dc_modtype, dc_mapper, dc_named_mapper, dc_udr, dc_calls, dc_chain, dc_enter

### multitu (stage 5: multiple translation units)

- a compile order other than the dependency order (modules before their users)
- kernels in procedures of other files (the kernels stay in the main program file; device functions cross files)
- common blocks, block data, and declare target on external variables

Sub-features (swarm): mt_chain, mt_submodule, mt_external, mt_amod


## All groups combined

Campaign `s1` (above, every table) runs all five groups at once on seeds
1-10000 at HSA_XNACK=1; `s1x0` runs seeds 1-2500 at HSA_XNACK=0. Its
review, with the confirmer's verdicts, the base-language x OpenMP feature
interactions against the single-group campaigns and the copy-mode
comparison, is data/reports/fuzz-s1.md. Generator defect G1 (fuzz-3: an
if(<leaf>:) variable missing from default(none) on a combined construct,
11 s1 programs and b5 seed 193, the same program as x0-multitu seed 193)
is fixed in generator fuzz-4 (the exclusions above are unchanged). The
fuzz-4 reruns: s1g4, s1g4x0, b5g4 and x0mg4 (x0-multitu seed 193 at HSA_XNACK=0; AFAR and CCE 19/20/21 all print the
model value, so the campaign's three CCE ftn-1510 rejections of it were
the generator defect).
