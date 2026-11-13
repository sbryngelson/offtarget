# Fuzz campaign `n1x0`

Csmith-style random OpenMP 5.2 Fortran offload programs (offload.engine.fuzz, generator `fuzz-4s50`, base-language groups: alloc, declare, derived, multitu, types (offload.engine.fuzz_base)), run on every toolchain at -O2, HSA_XNACK=0 (AMD) and separate memory (NVHPC), OMP_TARGET_OFFLOAD=mandatory; reference: the Python model of each program, checked against a host run (OMP_TARGET_OFFLOAD=disabled, a reference only; see the appendix 'Host reference checks' for the programs whose host run failed or disagreed). Machine-readable: results/fuzz/n1x0/summary.json.

## Size and timing

- programs generated: 1000; legal and run: 1000 (judged: 992; noncompliant, excluded from every count below: 8); generator rejects: 0; worker crashes: 0
- sessions (4, some concurrent; the times are not a wall time): n1x0-00: 1958 s with 12 workers, n1x0-01: 1953 s with 12 workers, n1x0-nvhpc: 5207 s with 1 worker, n1x0-nvhpc269: 3939 s with 1 worker; 36.0 s per program and worker, all toolchains and repeats included
- programs whose device results agree with the model on every toolchain: 26

## Notes

- Two executables of seed 72 from the first, stopped attempt of this campaign (21:47-21:51 on 2026-10-24) kept running on wingtip GPUs 0 and 1 until the next morning, so every NVHPC program of n0x0 (21:51-22:44) and n1x0 (22:39/22:44-00:11) shared its GPU with a spinning stray. A second look found no effect on the classes: the 17 timeouts are the same seeds on both releases, agreeing programs run in about 0.5 s, and each timeout reached the 60 s limit twice. Seed 72 itself is a timeout on both releases (rerun by the restarted campaign). Fixed in offload/engine/harness.py (a run cannot outlive its runner).

## Classes per toolchain

Rejections (compile_reject) are features a toolchain does not support, not failures. Flaky = the repeats differed (counted in the worst class).

| class | afar | cce19 | cce20 | cce21 | nvhpc | nvhpc269 |
|---|---|---|---|---|---|---|
| agree | 527 | 332 | 459 | 382 | 43 | 43 |
| compile_reject | 358 | 424 | 221 | 263 | 909 | 909 |
| ice | 7 | 176 | 244 | 243 | 2 | 2 |
| wrong_code | 15 | 26 (4 flaky) | 44 (6 flaky) | 46 (4 flaky) | 6 | 6 |
| host_fallback | 0 | 0 | 0 | 0 | 0 | 0 |
| timeout | 0 | 15 | 0 | 1 | 17 | 17 |
| run_error | 85 | 19 | 24 | 57 | 15 | 15 |
| harness_error | 0 | 0 | 0 | 0 | 0 | 0 |

## Base-language features

Per base-language feature (offload.engine.fuzz_base): the programs that have it, and per toolchain agree / compile_reject / ice / wrong_code / run_error (other classes in parentheses when present).

| feature | programs | afar | cce19 | cce20 | cce21 | nvhpc | nvhpc269 |
|---|---|---|---|---|---|---|---|
| al:allocatable_component | 573 | 310/193/3/7/60 | 188/242/106/17/10 (10) | 265/120/145/28/15 | 220/150/144/30/29 | 22/525/1/4/10 (11) | 22/525/1/4/10 (11) |
| al:allocatable_output_component | 48 | 28/15/0/0/5 | 17/20/7/2/1 (1) | 23/8/13/2/2 | 19/10/13/2/4 | 0/43/0/2/2 (1) | 0/43/0/2/2 (1) |
| al:allocatable_scalar | 613 | 333/218/4/10/48 | 203/262/104/19/13 (12) | 283/139/144/32/15 | 236/166/143/34/34 | 23/567/1/5/9 (8) | 23/567/1/5/9 (8) |
| al:depend_section | 92 | 28/39/0/1/24 | 30/36/16/1/1 (8) | 42/25/21/3/1 | 36/28/21/6/0 (1) | 1/84/1/0/6 | 1/84/1/0/6 |
| al:dummy:allocatable | 133 | 58/52/5/2/16 | 34/62/31/5/1 | 47/29/44/11/2 | 30/37/43/7/16 | 7/119/1/1/0 (5) | 7/119/1/1/0 (5) |
| al:dummy:assumed_length | 12 | 3/6/0/0/3 | 0/11/1/0/0 | 4/5/3/0/0 | 3/5/3/0/1 | 0/12/0/0/0 | 0/12/0/0/0 |
| al:dummy:assumed_shape | 294 | 151/113/7/2/21 | 71/142/60/10/10 (1) | 105/72/88/20/9 | 71/86/87/13/37 | 12/270/1/3/4 (4) | 12/270/1/3/4 (4) |
| al:dummy:char_len | 23 | 8/10/0/0/5 | 3/15/5/0/0 | 7/6/8/2/0 | 5/7/8/0/3 | 1/22/0/0/0 | 1/22/0/0/0 |
| al:dummy:explicit | 189 | 80/76/3/0/30 | 43/91/35/11/7 (2) | 66/46/54/13/10 | 38/53/54/11/33 | 7/174/1/3/1 (3) | 7/174/1/3/1 (3) |
| al:dummy:intent_in | 247 | 117/96/4/2/28 | 58/119/52/9/7 (2) | 84/66/72/16/9 | 55/80/71/10/31 | 6/229/1/4/2 (5) | 6/229/1/4/2 (5) |
| al:dummy:intent_inout | 355 | 175/132/7/3/38 | 89/168/68/16/12 (2) | 131/85/100/26/13 | 84/102/99/19/51 | 16/323/1/4/4 (7) | 16/323/1/4/4 (7) |
| al:dummy:intent_out | 31 | 18/8/2/2/1 | 8/11/6/4/2 | 12/5/8/4/2 | 5/5/8/5/8 | 2/28/0/0/0 (1) | 2/28/0/0/0 (1) |
| al:dummy:optional | 33 | 18/12/1/0/2 | 8/20/3/1/1 | 12/12/5/2/2 | 9/14/5/1/4 | 1/30/1/0/0 (1) | 1/30/1/0/0 (1) |
| al:dummy:pointer | 31 | 14/11/0/0/6 | 9/15/4/1/2 | 14/9/5/1/2 | 10/11/5/0/5 | 1/29/0/0/1 | 1/29/0/0/1 |
| al:dummy:value | 23 | 8/11/1/1/2 | 5/10/6/1/1 | 5/6/8/3/1 | 3/7/8/1/4 | 1/20/0/1/0 (1) | 1/20/0/1/0 (1) |
| al:kernel_in_internal_procedure | 381 | 191/138/7/3/42 | 98/180/71/17/13 (2) | 146/88/106/26/15 | 95/105/105/19/57 | 18/346/1/5/4 (7) | 18/346/1/5/4 (7) |
| al:optional_absent_in_map | 125 | 44/39/2/1/39 | 28/54/28/6/8 (1) | 48/26/38/5/8 | 1/30/38/0/56 | 7/112/0/0/1 (5) | 7/112/0/0/1 (5) |
| al:pointer_component | 628 | 342/219/3/11/53 | 214/258/114/17/15 (10) | 291/136/153/30/18 | 243/161/153/32/38 (1) | 27/578/0/5/11 (7) | 27/578/0/5/11 (7) |
| al:pointer_output:alloc | 181 | 83/78/0/2/18 | 49/86/34/5/3 (4) | 72/46/51/7/5 | 62/51/51/9/8 | 5/170/0/0/2 (4) | 5/170/0/0/2 (4) |
| al:pointer_output:target | 179 | 78/76/1/2/22 | 65/77/24/5/4 (4) | 88/41/37/7/6 | 79/46/37/8/9 | 1/174/0/1/2 (1) | 1/174/0/1/2 (1) |
| al:strided_update | 42 | 16/23/1/0/2 | 0/41/0/0/0 (1) | 0/42/0/0/0 | 0/42/0/0/0 | 0/42/0/0/0 | 0/42/0/0/0 |
| al:structure_dummy | 339 | 164/130/7/3/35 | 84/165/63/12/13 (2) | 126/82/97/19/15 | 82/95/96/15/51 | 15/311/0/3/4 (6) | 15/311/0/3/4 (6) |
| al:target_attribute | 536 | 284/198/3/7/44 | 183/225/98/9/11 (10) | 255/114/136/17/14 | 209/138/135/21/33 | 20/502/0/2/6 (6) | 20/502/0/2/6 (6) |
| dc:call:ga1 | 119 | 60/48/1/1/9 | 27/59/27/1/3 (2) | 37/35/35/8/4 | 35/38/35/8/3 | 4/113/0/0/1 (1) | 4/113/0/0/1 (1) |
| dc:call:gb1 | 100 | 53/35/1/1/10 | 27/46/20/2/2 (3) | 44/20/29/5/2 | 33/23/29/4/11 | 3/92/0/0/4 (1) | 3/92/0/0/4 (1) |
| dc:call:gd1 | 70 | 29/33/1/1/6 | 16/41/11/1/0 (1) | 26/25/18/1/0 | 21/25/18/1/5 | 0/69/0/0/1 | 0/69/0/0/1 |
| dc:call:gd2 | 84 | 37/34/1/2/10 | 23/46/11/3/1 | 35/25/16/6/2 | 27/31/16/6/4 | 0/82/0/0/1 (1) | 0/82/0/0/1 (1) |
| dc:call:ge1 | 80 | 30/39/1/1/9 | 18/36/18/1/1 (6) | 25/25/27/2/1 | 22/26/26/2/4 | 0/75/0/0/1 (4) | 0/75/0/0/1 (4) |
| dc:call:gm0 | 119 | 56/48/0/3/12 | 29/61/21/3/2 (3) | 40/37/33/5/4 | 32/40/32/5/9 (1) | 3/112/0/1/1 (2) | 3/112/0/1/1 (2) |
| dc:call:gs1 | 71 | 35/29/0/0/7 | 14/35/16/3/0 (3) | 25/19/23/4/0 | 19/20/23/5/4 | 2/67/1/0/1 | 2/67/1/0/1 |
| dc:call_across_modules | 608 | 325/215/5/11/52 | 202/255/119/15/10 (7) | 273/140/159/26/10 | 219/170/159/27/33 | 20/561/2/5/7 (13) | 20/561/2/5/7 (13) |
| dc:declare_mapper:default | 239 | 124/76/3/4/32 | 73/114/42/5/1 (4) | 120/54/55/9/1 | 98/64/55/6/16 | 11/218/1/1/2 (6) | 11/218/1/1/2 (6) |
| dc:declare_mapper:named | 340 | 177/125/2/5/31 | 102/135/71/12/13 (7) | 138/68/98/17/19 | 124/83/97/18/17 (1) | 10/316/0/1/8 (5) | 10/316/0/1/8 (5) |
| dc:declare_reduction | 152 | 0/152/0/0/0 | 0/134/16/0/0 (2) | 0/123/29/0/0 | 0/124/28/0/0 | 0/152/0/0/0 | 0/152/0/0/0 |
| dc:declare_reduction_available | 569 | 252/266/6/7/38 | 155/277/107/16/6 (8) | 209/186/144/21/9 | 174/202/143/22/28 | 24/525/1/1/8 (10) | 24/525/1/1/8 (10) |
| dc:declare_target_array | 827 | 436/297/6/12/76 | 282/361/135/22/14 (13) | 389/192/190/38/18 | 314/231/189/40/52 (1) | 31/770/1/5/9 (11) | 31/770/1/5/9 (11) |
| dc:declare_target_enter | 552 | 296/191/3/9/53 | 183/234/96/15/11 (13) | 256/119/138/26/13 | 205/144/137/29/37 | 27/507/2/3/6 (7) | 27/507/2/3/6 (7) |
| dc:declare_target_output | 259 | 136/94/2/2/25 | 73/130/41/3/3 (9) | 109/63/71/10/6 | 88/73/70/12/16 | 11/240/0/2/3 (3) | 11/240/0/2/3 (3) |
| dc:declare_target_structure | 614 | 323/223/5/10/53 | 200/259/114/17/13 (11) | 271/133/163/30/17 | 223/162/162/29/38 | 25/565/2/4/7 (11) | 25/565/2/4/7 (11) |
| dc:declare_target_to | 376 | 195/144/4/6/27 | 131/164/65/9/6 (1) | 174/90/88/16/8 | 149/107/88/14/17 (1) | 12/349/0/3/4 (8) | 12/349/0/3/4 (8) |
| dc:device_function_reads_module_var | 593 | 310/217/3/10/53 | 203/258/100/14/10 (8) | 280/135/142/24/12 | 227/162/141/27/35 (1) | 23/550/1/3/7 (9) | 23/550/1/3/7 (9) |
| dc:map_with_named_mapper | 50 | 19/24/0/1/6 | 1/23/14/0/12 | 1/13/18/0/18 | 12/14/18/1/5 | 0/50/0/0/0 | 0/50/0/0/0 |
| dc:static_init | 489 | 260/177/3/8/41 | 171/210/76/17/9 (6) | 237/115/104/21/12 | 195/139/103/22/29 (1) | 0/489/0/0/0 | 0/489/0/0/0 |
| decl:allocatable_char | 242 | 122/91/2/6/21 | 66/117/47/3/5 (4) | 106/60/64/7/5 | 81/72/63/9/17 | 12/220/1/2/4 (3) | 12/220/1/2/4 (3) |
| decl:allocatable_complex4 | 252 | 134/91/2/1/24 | 99/102/38/5/6 (2) | 123/53/58/10/8 | 107/66/57/7/15 | 7/236/1/3/1 (4) | 7/236/1/3/1 (4) |
| decl:allocatable_complex8 | 252 | 145/83/2/3/19 | 88/104/44/8/4 (4) | 115/62/57/13/5 | 99/70/57/14/12 | 13/226/1/2/5 (5) | 13/226/1/2/5 (5) |
| decl:allocatable_int1 | 265 | 131/100/2/4/28 | 92/119/39/10/4 (1) | 128/63/57/12/5 | 102/75/57/12/18 (1) | 13/246/0/0/2 (4) | 13/246/0/0/2 (4) |
| decl:allocatable_int2 | 265 | 137/99/2/2/25 | 85/116/51/10/2 (1) | 115/65/64/16/5 | 97/75/64/15/14 | 18/238/1/1/5 (2) | 18/238/1/1/5 (2) |
| decl:allocatable_int8 | 264 | 143/92/2/4/23 | 80/119/49/7/5 (4) | 119/55/67/15/8 | 103/70/67/14/10 | 6/248/1/2/4 (3) | 6/248/1/2/4 (3) |
| decl:allocatable_logical | 248 | 123/88/3/5/29 | 76/112/51/3/3 (3) | 105/60/68/11/4 | 87/68/67/10/16 | 9/236/0/0/2 (1) | 9/236/0/0/2 (1) |
| decl:allocatable_real4 | 231 | 110/94/1/4/22 | 69/106/40/8/4 (4) | 99/58/55/13/6 | 83/69/55/11/13 | 11/209/0/1/4 (6) | 11/209/0/1/4 (6) |
| decl:allocatable_real8 | 352 | 185/127/2/5/33 | 110/154/66/11/7 (4) | 156/82/87/17/10 | 131/96/87/17/21 | 19/316/1/3/5 (8) | 19/316/1/3/5 (8) |
| decl:explicit_char | 384 | 198/142/3/5/36 | 114/176/75/9/2 (8) | 177/80/106/16/5 | 153/92/106/17/15 (1) | 11/356/1/3/6 (7) | 11/356/1/3/6 (7) |
| decl:explicit_complex4 | 377 | 208/130/2/5/32 | 121/163/68/10/5 (10) | 176/82/92/18/9 | 150/93/92/20/21 (1) | 21/338/1/4/7 (6) | 21/338/1/4/7 (6) |
| decl:explicit_complex8 | 373 | 182/147/3/9/32 | 116/173/58/9/8 (9) | 172/85/89/17/10 | 141/98/88/18/28 | 17/339/0/3/7 (7) | 17/339/0/3/7 (7) |
| decl:explicit_int1 | 383 | 206/144/2/7/24 | 121/168/71/8/5 (10) | 172/88/102/17/4 | 150/102/101/15/15 | 14/356/0/2/5 (6) | 14/356/0/2/5 (6) |
| decl:explicit_int2 | 358 | 200/130/3/3/22 | 129/146/65/9/5 (4) | 174/70/92/16/6 | 134/89/91/21/22 (1) | 10/333/1/3/5 (6) | 10/333/1/3/5 (6) |
| decl:explicit_int8 | 340 | 187/110/3/7/33 | 128/133/56/8/8 (7) | 175/65/78/15/7 | 150/78/77/11/23 (1) | 19/304/1/2/7 (7) | 19/304/1/2/7 (7) |
| decl:explicit_logical | 383 | 205/142/3/7/26 | 125/161/74/13/6 (4) | 175/84/97/20/7 | 143/100/97/22/20 (1) | 14/349/2/3/6 (9) | 14/349/2/3/6 (9) |
| decl:explicit_real4 | 364 | 188/140/3/2/31 | 115/166/65/13/3 (2) | 161/94/88/15/6 | 136/109/88/14/17 | 14/332/1/4/7 (6) | 14/332/1/4/7 (6) |
| decl:explicit_real8 | 537 | 284/195/4/10/44 | 178/229/96/13/11 (10) | 254/115/138/18/12 | 206/140/137/23/30 (1) | 15/499/1/4/8 (10) | 15/499/1/4/8 (10) |
| dt:aos | 602 | 334/207/4/9/48 | 207/253/111/12/12 (7) | 285/126/154/21/16 | 246/148/153/16/38 (1) | 28/548/0/3/11 (12) | 28/548/0/3/11 (12) |
| dt:component:aos:integer | 602 | 334/207/4/9/48 | 207/253/111/12/12 (7) | 285/126/154/21/16 | 246/148/153/16/38 (1) | 28/548/0/3/11 (12) | 28/548/0/3/11 (12) |
| dt:component:aos:real8 | 362 | 201/127/2/4/28 | 126/162/56/5/8 (5) | 175/84/83/8/12 | 147/102/82/7/23 (1) | 18/326/0/2/8 (8) | 18/326/0/2/8 (8) |
| dt:component:nested:integer | 614 | 317/233/4/10/50 | 214/257/109/13/11 (10) | 294/135/153/19/13 | 241/158/152/24/38 (1) | 29/562/1/4/9 (9) | 29/562/1/4/9 (9) |
| dt:component:nested:real8 | 369 | 180/152/2/4/31 | 128/167/59/5/5 (5) | 174/91/87/9/8 | 141/106/86/12/23 (1) | 19/335/0/2/7 (6) | 19/335/0/2/7 (6) |
| dt:component:struct:integer | 992 | 527/358/7/15/85 | 332/424/176/26/19 (15) | 459/221/244/44/24 | 382/263/243/46/57 (1) | 43/909/2/6/15 (17) | 43/909/2/6/15 (17) |
| dt:component:struct:real8 | 589 | 306/223/3/7/50 | 196/270/97/10/10 (6) | 269/148/138/19/15 | 221/176/137/22/32 (1) | 25/542/0/2/10 (10) | 25/542/0/2/10 (10) |
| dt:default_init | 352 | 185/131/4/4/28 | 109/147/67/12/9 (8) | 154/82/88/19/9 | 123/99/87/18/25 | 12/328/0/1/7 (4) | 12/328/0/1/7 (4) |
| dt:map:component_section | 198 | 102/79/2/0/15 | 54/98/33/2/7 (4) | 76/58/47/9/8 | 64/66/46/13/8 (1) | 7/182/0/2/2 (5) | 7/182/0/2/2 (5) |
| dt:map:components | 540 | 270/214/3/12/41 | 155/249/102/13/12 (9) | 219/137/146/25/13 | 174/160/145/28/32 (1) | 21/500/0/4/5 (10) | 21/500/0/4/5 (10) |
| dt:map:implicit | 478 | 236/183/4/7/48 | 143/210/96/13/5 (11) | 205/111/137/17/8 | 169/128/136/16/28 (1) | 16/441/1/2/11 (7) | 16/441/1/2/11 (7) |
| dt:map:mod:always | 67 | 35/28/1/0/3 | 17/28/17/0/3 (2) | 24/14/23/1/5 | 22/17/23/3/2 | 3/57/0/1/2 (4) | 3/57/0/1/2 (4) |
| dt:map:mod:close | 85 | 36/38/1/0/10 | 17/46/14/0/6 (2) | 24/26/23/4/8 | 23/31/23/3/5 | 0/85/0/0/0 | 0/85/0/0/0 |
| dt:map:mod:mapper(mmap) | 50 | 19/24/0/1/6 | 1/23/14/0/12 | 1/13/18/0/18 | 12/14/18/1/5 | 0/50/0/0/0 | 0/50/0/0/0 |
| dt:map:mod:present | 49 | 25/19/1/0/4 | 12/24/10/1/1 (1) | 14/16/15/3/1 | 11/17/15/4/2 | 0/49/0/0/0 | 0/49/0/0/0 |
| dt:map:whole | 370 | 182/150/2/5/31 | 101/174/67/8/13 (7) | 145/93/97/16/19 | 123/112/96/18/20 (1) | 11/346/0/1/6 (6) | 11/346/0/1/6 (6) |
| dt:nested | 614 | 317/233/4/10/50 | 214/257/109/13/11 (10) | 294/135/153/19/13 | 241/158/152/24/38 (1) | 29/562/1/4/9 (9) | 29/562/1/4/9 (9) |
| dt:out:dr | 121 | 66/45/0/1/9 | 42/54/19/2/1 (3) | 58/27/31/3/2 | 48/29/31/4/8 (1) | 3/110/0/1/3 (4) | 3/110/0/1/3 (4) |
| dt:out:dr%nd | 46 | 14/28/0/0/4 | 10/27/6/1/1 (1) | 16/16/11/1/2 | 10/18/11/2/5 | 1/44/0/1/0 | 1/44/0/1/0 |
| dt:out:ds | 52 | 27/18/0/3/4 | 16/22/9/3/1 (1) | 22/11/14/4/1 | 20/12/14/2/4 | 2/50/0/0/0 | 2/50/0/0/0 |
| dt:scalar_component | 598 | 318/217/5/7/51 | 196/251/108/22/10 (11) | 275/129/149/33/12 | 226/153/148/32/39 | 23/554/1/3/8 (9) | 23/554/1/3/8 (9) |
| dt:struct | 992 | 527/358/7/15/85 | 332/424/176/26/19 (15) | 459/221/244/44/24 | 382/263/243/46/57 (1) | 43/909/2/6/15 (17) | 43/909/2/6/15 (17) |
| dt:target_update_component | 123 | 53/52/2/1/15 | 17/78/22/1/2 (3) | 26/62/30/3/2 | 21/64/30/3/5 | 1/121/1/0/0 | 1/121/1/0/0 |
| mt:external_function | 588 | 307/226/6/4/45 | 199/253/103/13/10 (10) | 272/137/148/20/11 | 230/158/147/22/31 | 22/538/0/4/11 (13) | 22/538/0/4/11 (13) |
| mt:file_set | 992 | 527/358/7/15/85 | 332/424/176/26/19 (15) | 459/221/244/44/24 | 382/263/243/46/57 (1) | 43/909/2/6/15 (17) | 43/909/2/6/15 (17) |
| mt:module_chain | 615 | 326/232/5/10/42 | 207/265/103/17/12 (11) | 288/137/148/27/15 | 246/159/147/29/34 | 28/563/1/4/11 (8) | 28/563/1/4/11 (8) |
| mt:module_file | 857 | 457/307/6/12/75 | 295/363/147/24/15 (13) | 404/189/204/41/19 | 333/229/203/41/50 (1) | 37/787/2/6/13 (12) | 37/787/2/6/13 (12) |
| mt:submodule | 602 | 343/207/4/5/43 | 206/247/111/15/12 (11) | 285/130/147/25/15 | 241/153/147/25/36 | 28/553/1/3/7 (10) | 28/553/1/3/7 (10) |
| out:char | 24 | 10/9/2/0/3 | 0/22/1/0/0 (1) | 11/6/4/1/2 | 8/6/4/2/4 | 0/23/1/0/0 | 0/23/1/0/0 |
| out:complex4 | 63 | 31/26/0/1/5 | 21/32/7/1/0 (2) | 31/17/11/3/1 | 29/19/11/3/1 | 2/59/0/1/0 (1) | 2/59/0/1/0 (1) |
| out:complex8 | 56 | 23/27/0/0/6 | 19/27/8/0/0 (2) | 28/10/14/3/1 | 22/11/14/4/5 | 4/49/0/1/1 (1) | 4/49/0/1/1 (1) |
| out:int1 | 56 | 23/28/0/3/2 | 12/33/10/1/0 | 20/20/13/3/0 | 16/21/13/4/2 | 0/56/0/0/0 | 0/56/0/0/0 |
| out:int2 | 78 | 33/33/2/1/9 | 27/34/17/0/0 | 37/15/23/2/1 | 28/16/23/6/5 | 0/78/0/0/0 | 0/78/0/0/0 |
| out:int8 | 68 | 34/28/1/2/3 | 21/30/9/2/2 (4) | 31/14/15/5/3 | 31/16/15/4/2 | 1/64/0/0/2 (1) | 1/64/0/0/2 (1) |
| out:logical | 61 | 25/25/1/2/8 | 14/30/13/3/1 | 23/17/16/4/1 | 19/17/16/6/2 (1) | 0/59/0/0/2 | 0/59/0/0/2 |
| out:real4 | 56 | 29/21/1/0/5 | 16/29/8/2/0 (1) | 26/18/9/3/0 | 22/19/9/3/3 | 2/52/0/0/1 (1) | 2/52/0/0/1 (1) |
| out:real8 | 122 | 55/53/0/3/11 | 35/55/19/4/6 (3) | 54/28/29/5/6 | 43/34/29/8/8 | 1/117/0/1/0 (3) | 1/117/0/1/0 (3) |
| real_kind_conversion | 48 | 25/20/0/0/3 | 15/24/6/0/1 (2) | 23/14/9/0/2 | 18/18/9/0/3 | 3/42/0/1/1 (1) | 3/42/0/1/1 (1) |
| red:complex4:+ | 39 | 19/14/0/0/6 | 15/18/4/0/1 (1) | 20/11/7/0/1 | 17/12/7/0/2 (1) | 0/36/0/0/3 | 0/36/0/0/3 |
| red:complex4:clause | 33 | 15/13/0/0/5 | 12/16/3/0/1 (1) | 16/10/6/0/1 | 13/11/6/0/2 (1) | 0/32/0/0/1 | 0/32/0/0/1 |
| red:complex4:plain | 7 | 5/1/0/0/1 | 3/2/1/0/1 | 4/1/1/0/1 | 4/1/1/0/1 | 0/5/0/0/2 | 0/5/0/0/2 |
| red:complex8:+ | 41 | 19/18/0/1/3 | 12/17/8/1/2 (1) | 17/6/15/1/2 | 14/8/15/2/2 | 1/37/0/0/3 | 1/37/0/0/3 |
| red:complex8:clause | 32 | 15/14/0/1/2 | 10/14/5/1/1 (1) | 14/5/11/1/1 | 12/6/11/1/2 | 0/30/0/0/2 | 0/30/0/0/2 |
| red:complex8:critical | 1 | 0/1/0/0/0 | 0/0/0/0/0 (1) | 0/0/1/0/0 | 0/0/1/0/0 | 0/1/0/0/0 | 0/1/0/0/0 |
| red:complex8:plain | 10 | 4/5/0/0/1 | 2/4/3/0/1 | 3/1/5/0/1 | 2/2/5/1/0 | 1/8/0/0/1 | 1/8/0/0/1 |
| red:int1:atomic | 2 | 1/1/0/0/0 | 0/2/0/0/0 | 1/1/0/0/0 | 1/1/0/0/0 | 0/2/0/0/0 | 0/2/0/0/0 |
| red:int1:clause | 25 | 9/13/0/1/2 | 6/15/3/0/1 | 9/11/4/0/1 | 8/12/4/0/1 | 0/25/0/0/0 | 0/25/0/0/0 |
| red:int1:iand | 3 | 0/1/0/1/1 | 2/1/0/0/0 | 2/1/0/0/0 | 2/1/0/0/0 | 0/3/0/0/0 | 0/3/0/0/0 |
| red:int1:ieor | 5 | 3/2/0/0/0 | 1/4/0/0/0 | 2/3/0/0/0 | 2/3/0/0/0 | 0/5/0/0/0 | 0/5/0/0/0 |
| red:int1:ior | 9 | 4/5/0/0/0 | 1/6/1/0/1 | 3/4/1/0/1 | 2/4/1/1/1 | 0/9/0/0/0 | 0/9/0/0/0 |
| red:int1:max | 7 | 4/2/0/0/1 | 4/3/0/0/0 | 5/2/0/0/0 | 4/3/0/0/0 | 0/7/0/0/0 | 0/7/0/0/0 |
| red:int1:min | 11 | 6/4/0/1/0 | 4/4/3/0/0 | 3/3/4/1/0 | 3/4/4/0/0 | 0/11/0/0/0 | 0/11/0/0/0 |
| red:int1:plain | 7 | 7/0/0/0/0 | 5/1/1/0/0 | 4/1/1/1/0 | 3/2/1/1/0 | 0/7/0/0/0 | 0/7/0/0/0 |
| red:int2:atomic | 1 | 0/1/0/0/0 | 0/1/0/0/0 | 0/1/0/0/0 | 0/1/0/0/0 | 0/1/0/0/0 | 0/1/0/0/0 |
| red:int2:clause | 24 | 11/10/0/0/3 | 5/14/4/0/0 (1) | 10/6/8/0/0 | 7/7/8/1/1 | 0/24/0/0/0 | 0/24/0/0/0 |
| red:int2:critical | 2 | 0/0/0/1/1 | 0/0/2/0/0 | 0/0/2/0/0 | 0/0/2/0/0 | 0/2/0/0/0 | 0/2/0/0/0 |
| red:int2:iand | 7 | 3/1/0/1/2 | 1/2/4/0/0 | 2/1/4/0/0 | 2/1/4/0/0 | 0/7/0/0/0 | 0/7/0/0/0 |
| red:int2:ieor | 7 | 3/4/0/0/0 | 2/4/0/0/0 (1) | 4/2/1/0/0 | 3/2/1/0/1 | 0/7/0/0/0 | 0/7/0/0/0 |
| red:int2:ior | 8 | 2/5/0/0/1 | 0/6/1/0/0 (1) | 1/4/3/0/0 | 0/5/3/0/0 | 0/8/0/0/0 | 0/8/0/0/0 |
| red:int2:max | 6 | 5/1/0/0/0 | 1/3/2/0/0 | 2/1/3/0/0 | 2/1/3/0/0 | 0/6/0/0/0 | 0/6/0/0/0 |
| red:int2:min | 9 | 4/4/0/0/1 | 2/6/1/0/0 | 4/1/4/0/0 | 3/1/4/1/0 | 0/9/0/0/0 | 0/9/0/0/0 |
| red:int2:plain | 5 | 4/1/0/0/0 | 1/2/2/0/0 | 2/0/3/0/0 | 2/0/3/0/0 | 0/5/0/0/0 | 0/5/0/0/0 |
| red:int8:+ | 8 | 3/4/0/0/1 | 1/4/2/1/0 | 1/2/3/2/0 | 1/2/3/2/0 | 0/8/0/0/0 | 0/8/0/0/0 |
| red:int8:atomic | 4 | 1/2/0/1/0 | 0/3/1/0/0 | 0/1/2/1/0 | 0/1/2/1/0 | 0/4/0/0/0 | 0/4/0/0/0 |
| red:int8:clause | 23 | 9/11/0/0/3 | 7/11/3/0/1 (1) | 9/9/4/0/1 | 6/9/4/0/4 | 0/22/0/0/0 (1) | 0/22/0/0/0 (1) |
| red:int8:critical | 1 | 0/1/0/0/0 | 0/0/1/0/0 | 0/0/1/0/0 | 0/0/1/0/0 | 0/1/0/0/0 | 0/1/0/0/0 |
| red:int8:iand | 8 | 4/2/0/1/1 | 3/3/2/0/0 | 3/1/4/0/0 | 0/1/4/0/3 | 0/7/0/0/0 (1) | 0/7/0/0/0 (1) |
| red:int8:ieor | 5 | 2/1/0/0/2 | 0/4/1/0/0 | 1/2/1/1/0 | 1/2/1/1/0 | 0/5/0/0/0 | 0/5/0/0/0 |
| red:int8:ior | 2 | 0/1/0/0/1 | 0/1/1/0/0 | 0/0/2/0/0 | 0/0/2/0/0 | 0/2/0/0/0 | 0/2/0/0/0 |
| red:int8:max | 8 | 3/4/0/0/1 | 3/4/1/0/0 | 3/4/1/0/0 | 3/4/1/0/0 | 0/7/1/0/0 | 0/7/1/0/0 |
| red:int8:min | 6 | 3/3/0/0/0 | 0/1/3/0/1 (1) | 1/2/2/0/1 | 1/2/2/0/1 | 0/6/0/0/0 | 0/6/0/0/0 |
| red:int8:plain | 7 | 4/1/0/0/2 | 0/3/3/1/0 | 0/1/4/2/0 | 0/1/4/2/0 | 0/6/1/0/0 | 0/6/1/0/0 |
| red:logical:.and. | 10 | 6/4/0/0/0 | 4/2/4/0/0 | 4/2/4/0/0 | 3/2/4/0/1 | 0/10/0/0/0 | 0/10/0/0/0 |
| red:logical:.eqv. | 6 | 3/2/0/1/0 | 2/3/1/0/0 | 3/1/2/0/0 | 3/1/2/0/0 | 0/6/0/0/0 | 0/6/0/0/0 |
| red:logical:.neqv. | 10 | 6/4/0/0/0 | 5/4/1/0/0 | 6/1/2/0/1 | 6/1/2/1/0 | 1/8/0/1/0 | 1/8/0/1/0 |
| red:logical:.or. | 6 | 3/3/0/0/0 | 1/2/1/2/0 | 1/2/1/2/0 | 1/2/1/2/0 | 0/5/0/0/0 (1) | 0/5/0/0/0 (1) |
| red:logical:atomic | 3 | 1/2/0/0/0 | 0/1/2/0/0 | 0/0/3/0/0 | 0/0/3/0/0 | 0/3/0/0/0 | 0/3/0/0/0 |
| red:logical:clause | 18 | 8/9/0/1/0 | 8/7/2/1/0 | 10/4/2/1/1 | 10/4/2/2/0 | 1/15/0/1/0 (1) | 1/15/0/1/0 (1) |
| red:logical:critical | 1 | 1/0/0/0/0 | 0/0/1/0/0 | 0/0/1/0/0 | 0/0/1/0/0 | 0/1/0/0/0 | 0/1/0/0/0 |
| red:logical:plain | 9 | 8/1/0/0/0 | 4/3/1/1/0 | 4/2/2/1/0 | 3/2/2/1/1 | 0/9/0/0/0 | 0/9/0/0/0 |
| red:real4:+ | 10 | 3/6/0/0/1 | 1/7/2/0/0 | 1/4/5/0/0 | 1/4/5/0/0 | 0/10/0/0/0 | 0/10/0/0/0 |
| red:real4:atomic | 5 | 0/5/0/0/0 | 0/3/2/0/0 | 0/2/3/0/0 | 0/2/3/0/0 | 0/5/0/0/0 | 0/5/0/0/0 |
| red:real4:clause | 21 | 6/12/0/0/3 | 4/11/5/0/1 | 6/9/5/0/1 | 5/10/5/0/1 | 0/21/0/0/0 | 0/21/0/0/0 |
| red:real4:critical | 2 | 0/1/0/0/1 | 0/1/1/0/0 | 0/0/2/0/0 | 0/0/2/0/0 | 0/2/0/0/0 | 0/2/0/0/0 |
| red:real4:max | 13 | 4/8/0/0/1 | 3/9/1/0/0 | 4/6/3/0/0 | 3/6/3/0/1 | 0/13/0/0/0 | 0/13/0/0/0 |
| red:real4:min | 12 | 3/7/0/0/2 | 1/4/5/1/1 | 2/3/5/1/1 | 2/4/5/1/0 | 0/12/0/0/0 | 0/12/0/0/0 |
| red:real4:plain | 6 | 4/2/0/0/0 | 1/4/0/1/0 | 1/1/3/1/0 | 1/1/3/1/0 | 0/6/0/0/0 | 0/6/0/0/0 |
| red:real8:+ | 12 | 3/9/0/0/0 | 2/6/2/0/1 (1) | 3/4/4/0/1 | 3/5/4/0/0 | 1/11/0/0/0 | 1/11/0/0/0 |
| red:real8:atomic | 3 | 2/0/0/1/0 | 1/1/1/0/0 | 2/0/1/0/0 | 2/0/1/0/0 | 0/3/0/0/0 | 0/3/0/0/0 |
| red:real8:clause | 35 | 14/19/0/0/2 | 9/19/5/0/1 (1) | 14/11/8/0/2 | 13/12/8/0/2 | 1/32/0/1/0 (1) | 1/32/0/1/0 (1) |
| red:real8:critical | 1 | 0/1/0/0/0 | 0/1/0/0/0 | 0/1/0/0/0 | 0/1/0/0/0 | 0/1/0/0/0 | 0/1/0/0/0 |
| red:real8:max | 21 | 8/9/0/1/3 | 4/11/6/0/0 | 7/5/8/0/1 | 6/5/8/0/2 | 0/20/0/0/0 (1) | 0/20/0/0/0 (1) |
| red:real8:min | 19 | 8/10/0/0/1 | 5/11/3/0/0 | 9/6/4/0/0 | 7/7/4/1/0 | 0/17/0/2/0 | 0/17/0/2/0 |
| red:real8:plain | 10 | 3/6/0/0/1 | 1/6/3/0/0 | 2/3/5/0/0 | 0/4/5/1/0 | 0/9/0/1/0 | 0/9/0/1/0 |
| spell:double_precision | 418 | 214/150/4/8/42 | 133/171/87/14/6 (7) | 188/92/114/17/7 | 154/109/114/17/23 (1) | 17/383/2/5/4 (7) | 17/383/2/5/4 (7) |
| type:char | 614 | 314/230/3/11/56 | 180/282/121/12/7 (12) | 278/138/167/22/9 | 229/162/166/24/32 (1) | 23/564/2/5/10 (10) | 23/564/2/5/10 (10) |
| type:char_scalar | 614 | 314/230/3/11/56 | 180/282/121/12/7 (12) | 278/138/167/22/9 | 229/162/166/24/32 (1) | 23/564/2/5/10 (10) | 23/564/2/5/10 (10) |
| type:complex4 | 607 | 331/212/4/6/54 | 214/255/101/15/11 (11) | 289/128/146/28/16 | 246/152/145/27/36 (1) | 28/554/2/6/8 (9) | 28/554/2/6/8 (9) |
| type:complex8 | 595 | 315/214/5/12/49 | 197/262/96/17/12 (11) | 274/143/136/28/14 | 230/164/135/29/37 | 29/539/1/4/11 (11) | 29/539/1/4/11 (11) |
| type:int1 | 621 | 328/229/4/10/50 | 207/269/107/18/9 (11) | 289/141/154/28/9 | 244/166/153/26/31 (1) | 27/575/0/2/7 (10) | 27/575/0/2/7 (10) |
| type:int2 | 589 | 324/215/3/5/42 | 203/245/110/19/7 (5) | 273/127/147/31/11 | 219/156/146/33/34 (1) | 28/537/2/4/10 (8) | 28/537/2/4/10 (8) |
| type:int8 | 573 | 316/187/5/10/55 | 197/238/103/14/12 (9) | 276/114/142/27/14 | 235/140/141/23/33 (1) | 25/523/2/4/9 (10) | 25/523/2/4/9 (10) |
| type:logical | 604 | 318/217/5/11/53 | 195/259/118/16/9 (7) | 271/135/156/31/11 | 224/159/155/30/35 (1) | 23/558/2/3/8 (10) | 23/558/2/3/8 (10) |
| type:real4 | 573 | 287/227/3/6/50 | 177/259/105/20/7 (5) | 248/143/143/27/12 | 209/168/143/24/29 | 23/522/1/5/10 (12) | 23/522/1/5/10 (12) |
| type:real8 | 839 | 450/297/6/14/72 | 276/359/155/21/15 (13) | 390/187/212/31/19 | 321/222/211/36/48 (1) | 34/768/2/6/13 (16) | 34/768/2/6/13 (16) |
| view:char | 477 | 239/183/2/8/45 | 132/227/94/8/6 (10) | 212/106/134/18/7 | 176/124/133/19/24 (1) | 20/438/1/2/9 (7) | 20/438/1/2/9 (7) |
| view:complex4 | 382 | 197/147/1/2/35 | 122/168/74/6/5 (7) | 167/85/105/16/9 | 141/98/104/17/21 (1) | 17/352/1/2/5 (5) | 17/352/1/2/5 (5) |
| view:complex8 | 397 | 208/145/3/6/35 | 123/181/66/10/8 (9) | 170/103/96/18/10 | 138/118/95/18/28 | 19/362/0/0/8 (8) | 19/362/0/0/8 (8) |
| view:int1 | 427 | 222/164/3/5/33 | 130/192/77/12/6 (10) | 191/95/116/20/5 | 165/112/115/17/17 (1) | 21/394/0/1/5 (6) | 21/394/0/1/5 (6) |
| view:int2 | 380 | 196/150/2/2/30 | 116/169/78/9/3 (5) | 164/83/110/18/5 | 130/100/109/22/18 (1) | 19/344/1/1/8 (7) | 19/344/1/1/8 (7) |
| view:int8 | 362 | 185/130/3/6/38 | 111/153/77/7/7 (7) | 156/75/107/14/10 | 135/87/106/12/21 (1) | 16/331/1/1/7 (6) | 16/331/1/1/7 (6) |
| view:logical | 383 | 193/142/4/8/36 | 107/178/78/10/6 (4) | 159/89/106/20/9 | 130/104/106/19/23 (1) | 14/353/1/1/6 (8) | 14/353/1/1/6 (8) |
| view:real4 | 373 | 174/158/2/3/36 | 98/179/76/11/5 (4) | 145/98/105/16/9 | 119/114/105/16/19 | 14/341/0/1/7 (10) | 14/341/0/1/7 (10) |
| view:real8 | 737 | 376/282/4/12/63 | 230/333/135/14/14 (11) | 327/175/192/24/19 | 272/204/191/30/39 (1) | 30/677/1/3/12 (14) | 30/677/1/3/12 (14) |

## Known findings rediscovered

- cce19-target-parallel-guarded-loop (wrong code on cce19 in a program with a thread-0-guarded sequential loop in target parallel): 12 programs (seeds 59, 144, 225, 233, 340, 517, 701, 788, 887, 900, 908, 983)
- cce21-defaultmap-aggregate-flag (wrong code or host fallback on cce21 where cce20 agrees, in a program with a defaultmap clause; the finding's symptom: a map(tofrom) scalar is not copied back): 14 programs (seeds 10, 28, 111, 152, 299, 326, 373, 443, 504, 527, 563, 609)
- (control for the line above: the same without a defaultmap clause): 0 programs (seeds )
- cce21-in-reduction-taskwait-link (cce21 link failure on _cray$mt_taskwait): 41 programs (seeds 43, 55, 100, 127, 139, 172, 175, 211, 219, 229, 254, 292)
- cce19-target-parallel-single-ice / task ICE (CCE 'unhandled construct type'): 184 programs (seeds 17, 19, 21, 25, 32, 48, 52, 56, 58, 61, 62, 67)

## Distinct minimized failures

(none minimized yet)

## Wrong code (all programs)

- afar: 15 programs (seeds 32, 203, 333, 350, 410, 417, 435, 465, 482, 497, 552, 594, 610, 954, 964)
- cce19: 26 programs (seeds 18, 59, 100, 144, 165, 178, 219, 225, 233, 340, 431, 480, 517, 541, 580, 640, 701, 782, 788, 818)
- cce20: 44 programs (seeds 18, 30, 38, 43, 59, 63, 100, 123, 144, 165, 178, 188, 219, 220, 225, 233, 264, 300, 302, 340)
- cce21: 46 programs (seeds 10, 28, 38, 59, 63, 111, 123, 152, 165, 178, 188, 220, 225, 233, 264, 299, 302, 326, 340, 373)
- nvhpc: 6 programs (seeds 299, 485, 837, 868, 945, 972)
- nvhpc269: 6 programs (seeds 299, 485, 837, 868, 945, 972)

## Internal compiler errors (deduplicated by message)

| toolchain | programs | message | seeds |
|---|---|---|---|
| cce19 | 133 | ice: INTERNAL COMPILER ERROR: "unhandled construct type" (v_openmp.c, line 7617, version <v>) | 17, 19, 25, 48, 52 |
| cce20 | 125 | ice: INTERNAL COMPILER ERROR: "unhandled acc construct type" (v_openmp.c, line 7881, version <v>) | 17, 19, 21, 25, 32 |
| cce21 | 125 | ice: INTERNAL COMPILER ERROR: "unhandled acc construct type" (v_openmp.c, line 8265, version <v>) | 17, 19, 21, 25, 32 |
| cce20 | 57 | ice: INTERNAL COMPILER ERROR: "unhandled construct type" (v_openmp.c, line 7814, version <v>) | 62, 72, 90, 112, 122 |
| cce21 | 57 | ice: INTERNAL COMPILER ERROR: "unhandled construct type" (v_openmp.c, line 8197, version <v>) | 62, 72, 90, 112, 122 |
| cce20 | 50 | ice: INTERNAL COMPILER ERROR: "ACC - barrier/reset/protected last private not supported" (v_mt_translate.c, line 5607, version <v>) | 16, 36, 49, 69, 78 |
| cce21 | 50 | ice: INTERNAL COMPILER ERROR: "ACC - barrier/reset/protected last private not supported" (v_mt_translate.c, line 5798, version <v>) | 16, 36, 49, 69, 78 |
| cce19 | 34 | ice: INTERNAL COMPILER ERROR: "ACC - barrier/reset/protected last private not supported" (v_mt_translate.c, line 4874, version <v>) | 16, 36, 49, 78, 83 |
| cce20 | 4 | ice: ftn-2116 ftn: INTERNAL \| "optcg" was terminated due to receipt of signal 06: Aborted. | 92, 471, 645, 846 |
| cce19 | 3 | ice: INTERNAL COMPILER ERROR: "Unhandled expression type in get base or dv mem | 37, 621, 848 |
| cce20 | 3 | ice: INTERNAL COMPILER ERROR: "Unhandled expression type in get base or dv mem | 37, 621, 848 |
| cce21 | 3 | ice: INTERNAL COMPILER ERROR: "Unhandled expression type in get base or dv mem | 37, 621, 848 |
| cce21 | 3 | ice: ftn-2116 ftn: INTERNAL \| "optcg" was terminated due to receipt of signal 06: Aborted. | 471, 645, 846 |
| afar | 2 | afar FIR verification: 'omp.simd' op operand #0 must be variadic of OpenMP-compatible variable type, but got '!fir.box<!fir.array<?xi32>>' | 86, 949 |
| cce19 | 2 | ice: INTERNAL COMPILER ERROR: "Couldn't find an atomic update statement" (v_mt_translate_atomic.c, line 1703, version <v>) | 742, 995 |
| cce19 | 2 | ice: INTERNAL COMPILER ERROR: "Unhandled contexts must be fixed!!! | 327, 600 |
| cce20 | 2 | ice: INTERNAL COMPILER ERROR: "Couldn't find an atomic update statement" (v_mt_translate_atomic.c, line 1703, version <v>) | 742, 995 |
| cce20 | 2 | ice: INTERNAL COMPILER ERROR: "Unhandled contexts must be fixed!!! | 327, 600 |
| cce21 | 2 | ice: INTERNAL COMPILER ERROR: "Couldn't find an atomic update statement" (v_mt_translate_atomic.c, line 1702, version <v>) | 742, 995 |
| cce21 | 2 | ice: INTERNAL COMPILER ERROR: "Unhandled contexts must be fixed!!! | 327, 600 |
| afar | 1 | afar FIR verification: 'omp.simd' op operand #0 must be variadic of OpenMP-compatible variable type, but got '!fir.box<!fir.array<?x?xi16>>' | 714 |
| afar | 1 | afar FIR verification: 'omp.simd' op operand #0 must be variadic of OpenMP-compatible variable type, but got '!fir.box<!fir.array<?x?xi32>>' | 346 |
| afar | 1 | afar FIR verification: 'omp.simd' op operand #0 must be variadic of OpenMP-compatible variable type, but got '!fir.box<!fir.array<?x?xi64>>' | 898 |
| afar | 1 | afar FIR verification: 'omp.simd' op operand #1 must be variadic of OpenMP-compatible variable type, but got '!fir.box<!fir.array<?xi32>>' | 120 |
| afar | 1 | afar FIR verification: stride cannot be specified on an array section | 709 |
| cce19 | 1 | ice: INTERNAL COMPILER ERROR: "Error getting dope vector information" (v_dope_utl.c, line 931, version <v>) | 768 |
| cce19 | 1 | ice: ftn-2116 ftn: INTERNAL \| "optcg" was terminated due to receipt of signal 06: Aborted. | 846 |
| cce20 | 1 | ice: INTERNAL COMPILER ERROR: "Error getting dope vector information" (v_dope_utl.c, line 933, version <v>) | 768 |
| cce21 | 1 | ice: INTERNAL COMPILER ERROR: "Error getting dope vector information" (v_dope_utl.c, line 935, version <v>) | 768 |
| nvhpc | 1 | ice: NVFORTRAN-F-0155-Compiler failed to translate accelerator region (see -Minfo messages): Character local variable unsupported on device (fuzz_prog | 13 |
| nvhpc | 1 | ice: nvvmCompileProgram: failed with error 9: NVVM_ERROR_COMPILATION | 651 |
| nvhpc269 | 1 | ice: NVFORTRAN-F-0155-Compiler failed to translate accelerator region (see -Minfo messages): Character local variable unsupported on device (fuzz_prog | 13 |
| nvhpc269 | 1 | ice: nvvmCompileProgram: failed with error 9: NVVM_ERROR_COMPILATION | 651 |

## Run errors, timeouts, host fallbacks

| toolchain | class | programs | reason | seeds |
|---|---|---|---|---|
| cce21 | run_error | 56 | crash: SIGSEGV; without mandatory: crash: SIGSEGV | 7, 11, 18, 40, 44 |
| afar | run_error | 46 | crash: SIGABRT; without mandatory: crash: SIGABRT | 7, 11, 18, 35, 115 |
| afar | run_error | 39 | crash: SIGSEGV; without mandatory: crash: SIGSEGV | 2, 14, 62, 99, 134 |
| cce20 | run_error | 18 | crash: SIGABRT; without mandatory: crash: SIGABRT | 12, 65, 73, 218, 238 |
| nvhpc | timeout | 16 | timeout | 72, 126, 192, 315, 318 |
| nvhpc269 | timeout | 16 | timeout | 72, 126, 192, 315, 318 |
| cce19 | timeout | 15 | compile_timeout | 79, 196, 213, 237, 244 |
| nvhpc | run_error | 14 | exit_status: 1; without mandatory: exit_status: 1 | 6, 54, 99, 133, 223 |
| nvhpc269 | run_error | 14 | exit_status: 1; without mandatory: exit_status: 1 | 6, 54, 99, 133, 223 |
| cce19 | run_error | 13 | crash: SIGABRT; without mandatory: crash: SIGABRT | 12, 65, 186, 271, 412 |
| cce19 | run_error | 6 | exit_status: 1; without mandatory: exit_status: 1 | 75, 108, 380, 546, 943 |
| cce20 | run_error | 6 | exit_status: 1; without mandatory: exit_status: 1 | 75, 108, 380, 546, 943 |
| nvhpc | run_error | 1 | crash: SIGSEGV; without mandatory: crash: SIGSEGV | 57 |
| nvhpc269 | run_error | 1 | crash: SIGSEGV; without mandatory: crash: SIGSEGV | 57 |
| cce21 | run_error | 1 | exit_status: 1; without mandatory: exit_status: 1 | 278 |
| cce21 | timeout | 1 | timeout | 678 |
| nvhpc | timeout | 1 | compile_timeout | 888 |
| nvhpc269 | timeout | 1 | compile_timeout | 888 |

## Features and feature pairs most associated with failures

Among programs the toolchain compiled (or crashed on). Lift = the rate of the class among programs with the feature (pair) over the toolchain's overall rate; a pair is listed only when it beats both of its features alone by 25%.

### afar: wrong_code

Single features: split:target | teams | distribute | parallel | do simd (7/56, lift 5.28); base:out:int1 (3/28, lift 4.53); red:atomic (3/30, lift 4.23); clause:default:none (8/81, lift 4.17); dir:do simd (7/73, lift 4.05); base:dt:out:ds (3/34, lift 3.73); scalar:firstprivate (4/55, lift 3.07); split:target | teams | distribute | parallel | do (3/42, lift 3.02)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| clause:default:none + split:target \| teams \| distribute \| parallel \| do simd | 23 | 6 | 0.261 | 0.125 | 11.03 |
| clause:thread_limit + split:target \| teams \| distribute \| parallel \| do simd | 16 | 4 | 0.25 | 0.125 | 10.57 |
| body:call_declare_target + split:target \| teams \| distribute \| parallel \| do simd | 25 | 6 | 0.24 | 0.125 | 10.14 |
| map:mod:close + split:target \| teams \| distribute \| parallel \| do simd | 17 | 4 | 0.235 | 0.125 | 9.95 |
| base:dt:component:nested:real8 + split:target \| teams \| distribute \| parallel \| do simd | 18 | 4 | 0.222 | 0.125 | 9.39 |
| base:decl:explicit_complex8 + chain:target parallel do | 28 | 6 | 0.214 | 0.07 | 9.06 |
| chain:target teams distribute parallel do + clause:default:none | 19 | 4 | 0.211 | 0.099 | 8.9 |
| clause:thread_limit + red:clause:+ | 19 | 4 | 0.211 | 0.069 | 8.9 |

### afar: ice

Single features: clause:nontemporal (7/35, lift 18.11); split:target | parallel | do | simd (4/61, lift 5.94); base:al:dummy:allocatable (5/81, lift 5.59); split:target | simd (3/55, lift 4.94); chain:target parallel do simd (5/105, lift 4.31); chain:target teams distribute (3/67, lift 4.06); base:al:dummy:assumed_shape (7/181, lift 3.5); base:al:structure_dummy (7/209, lift 3.03)

| feature pair | programs | ice | rate | best single rate | lift |
|---|---|---|---|---|---|
| base:mt:external_function + clause:nontemporal | 15 | 6 | 0.4 | 0.2 | 36.23 |
| clause:nontemporal + loop:down | 16 | 6 | 0.375 | 0.2 | 33.96 |
| base:dc:declare_reduction_available + clause:nontemporal | 20 | 6 | 0.3 | 0.2 | 27.17 |
| base:dt:scalar_component + clause:nontemporal | 18 | 5 | 0.278 | 0.2 | 25.16 |
| clause:nontemporal + decl:explicit_rank1 | 26 | 7 | 0.269 | 0.2 | 24.38 |
| base:dt:default_init + clause:nontemporal | 15 | 4 | 0.267 | 0.2 | 24.15 |
| base:type:logical + clause:nontemporal | 19 | 5 | 0.263 | 0.2 | 23.83 |
| base:dc:declare_target_structure + clause:nontemporal | 20 | 5 | 0.25 | 0.2 | 22.64 |

### afar: run_error

Single features: base:al:optional_absent_in_map (39/86, lift 3.38); base:al:depend_section (24/53, lift 3.38); tasking:nowait_depend (41/93, lift 3.29); clause:schedule:auto (6/19, lift 2.36); red:clause:iand (11/35, lift 2.34); clause:if:simd (17/56, lift 2.26); base:al:dummy:pointer (6/20, lift 2.24); dir:teams loop (6/21, lift 2.13)

| feature pair | programs | run_error | rate | best single rate | lift |
|---|---|---|---|---|---|
| base:al:depend_section + base:decl:allocatable_real8 | 19 | 13 | 0.684 | 0.453 | 5.1 |
| clause:default:none + tasking:nowait_depend | 15 | 10 | 0.667 | 0.441 | 4.97 |
| base:dc:declare_mapper:default + tasking:nowait_depend | 26 | 17 | 0.654 | 0.441 | 4.88 |
| base:al:depend_section + dir:target parallel | 17 | 11 | 0.647 | 0.453 | 4.83 |
| base:decl:allocatable_real8 + tasking:nowait_depend | 36 | 23 | 0.639 | 0.441 | 4.77 |
| base:al:optional_absent_in_map + base:dc:declare_mapper:default | 22 | 14 | 0.636 | 0.453 | 4.75 |
| base:al:optional_absent_in_map + chain:target teams loop | 22 | 14 | 0.636 | 0.453 | 4.75 |
| base:al:allocatable_component + base:al:depend_section | 30 | 19 | 0.633 | 0.453 | 4.72 |

### cce19: wrong_code

Single features: guard:par_thread0 (10/41, lift 5.33); base:al:dummy:intent_out (4/20, lift 4.37); red:in_reduction:* (6/32, lift 4.1); guard:split_par_thread0 (3/19, lift 3.45); dir:teams distribute (3/26, lift 2.52); clause:in_reduction (7/62, lift 2.47); dir:taskgroup (7/62, lift 2.47); kernel:inred (7/62, lift 2.47)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| guard:par_thread0 + map:mod:always | 21 | 8 | 0.381 | 0.244 | 8.32 |
| base:type:logical + guard:par_thread0 | 20 | 7 | 0.35 | 0.244 | 7.65 |
| base:al:allocatable_component + guard:par_thread0 | 27 | 9 | 0.333 | 0.244 | 7.28 |
| base:type:complex4 + red:in_reduction:* | 18 | 6 | 0.333 | 0.188 | 7.28 |
| decl:allocatable_rank0 + guard:par_thread0 | 18 | 6 | 0.333 | 0.244 | 7.28 |
| base:dc:declare_target_to + guard:par_thread0 | 15 | 5 | 0.333 | 0.244 | 7.28 |
| base:decl:allocatable_complex8 + guard:par_thread0 | 15 | 5 | 0.333 | 0.244 | 7.28 |
| base:decl:allocatable_int8 + guard:par_thread0 | 15 | 5 | 0.333 | 0.244 | 7.28 |

### cce19: ice

Single features: guard:single (24/24, lift 3.23); phase:loop (23/23, lift 3.23); phase:single (49/50, lift 3.16); phase:do simd (42/43, lift 3.15); phase:nowait_barrier (29/30, lift 3.12); kernel:phase (77/80, lift 3.11); map:alloc (26/27, lift 3.11); phase:do (66/69, lift 3.09)

| feature pair | programs | ice | rate | best single rate | lift |
|---|---|---|---|---|---|
| clause:lastprivate + split:target \| teams \| distribute \| parallel \| do simd | 21 | 17 | 0.81 | 0.516 | 2.61 |
| clause:lastprivate + clause:proc_bind | 15 | 12 | 0.8 | 0.516 | 2.58 |
| dir:target parallel + split:target \| teams \| loop | 15 | 12 | 0.8 | 0.59 | 2.58 |
| red:clause + split:target \| parallel \| do | 15 | 12 | 0.8 | 0.543 | 2.58 |
| dir:target parallel + map:mod:close | 49 | 37 | 0.755 | 0.59 | 2.44 |
| base:al:dummy:allocatable + clause:device | 16 | 12 | 0.75 | 0.448 | 2.42 |
| base:dc:map_with_named_mapper + base:type:logical | 16 | 12 | 0.75 | 0.519 | 2.42 |
| base:dt:map:mod:mapper(mmap) + base:type:logical | 16 | 12 | 0.75 | 0.519 | 2.42 |

### cce19: run_error

Single features: base:dc:map_with_named_mapper (12/27, lift 13.29); base:dt:map:mod:mapper(mmap) (12/27, lift 13.29); base:dt:map:mod:close (6/39, lift 4.6); base:al:optional_absent_in_map (8/71, lift 3.37); red:clause:ior (3/33, lift 2.72); base:out:real8 (6/67, lift 2.68); clause:proc_bind (5/64, lift 2.34); base:dt:map:mod:always (3/39, lift 2.3)

| feature pair | programs | run_error | rate | best single rate | lift |
|---|---|---|---|---|---|
| base:dc:map_with_named_mapper + base:type:complex8 | 15 | 9 | 0.6 | 0.444 | 17.94 |
| base:dt:map:mod:mapper(mmap) + base:type:complex8 | 15 | 9 | 0.6 | 0.444 | 17.94 |
| base:dc:declare_target_enter + base:dc:map_with_named_mapper | 16 | 9 | 0.562 | 0.444 | 16.82 |
| base:dc:declare_target_enter + base:dt:map:mod:mapper(mmap) | 16 | 9 | 0.562 | 0.444 | 16.82 |
| base:dt:map:mod:close + base:view:complex8 | 15 | 5 | 0.333 | 0.154 | 9.96 |
| base:dc:declare_mapper:named + base:dt:map:mod:close | 20 | 6 | 0.3 | 0.154 | 8.97 |
| base:al:kernel_in_internal_procedure + base:dt:map:mod:close | 15 | 4 | 0.267 | 0.154 | 7.97 |
| base:al:structure_dummy + base:dt:map:mod:close | 15 | 4 | 0.267 | 0.154 | 7.97 |

### cce20: wrong_code

Single features: guard:par_thread0 (16/61, lift 4.6); red:in_reduction:* (11/48, lift 4.02); guard:split_par_thread0 (6/29, lift 3.63); defaultmap:to:scalar (3/16, lift 3.29); clause:in_reduction (16/89, lift 3.15); dir:taskgroup (16/89, lift 3.15); kernel:inred (16/89, lift 3.15); base:al:dummy:value (3/17, lift 3.09)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| base:al:dummy:intent_inout + red:in_reduction:* | 19 | 10 | 0.526 | 0.229 | 9.22 |
| base:al:kernel_in_internal_procedure + red:in_reduction:* | 19 | 10 | 0.526 | 0.229 | 9.22 |
| base:al:dummy:assumed_shape + red:in_reduction:+ | 17 | 8 | 0.471 | 0.17 | 8.25 |
| base:decl:allocatable_int2 + guard:par_thread0 | 17 | 7 | 0.412 | 0.262 | 7.22 |
| base:al:dummy:intent_inout + clause:in_reduction | 37 | 15 | 0.405 | 0.18 | 7.1 |
| base:al:dummy:intent_inout + dir:taskgroup | 37 | 15 | 0.405 | 0.18 | 7.1 |
| base:al:dummy:intent_inout + kernel:inred | 37 | 15 | 0.405 | 0.18 | 7.1 |
| base:al:kernel_in_internal_procedure + clause:in_reduction | 37 | 15 | 0.405 | 0.18 | 7.1 |

### cce20: ice

Single features: kernel:phase (109/109, lift 3.16); phase:do (95/95, lift 3.16); phase:single (62/62, lift 3.16); phase:do simd (61/61, lift 3.16); phase:masked (57/57, lift 3.16); phase:nowait_barrier (42/42, lift 3.16); map:alloc (39/39, lift 3.16); guard:single (35/35, lift 3.16)

| feature pair | programs | ice | rate | best single rate | lift |
|---|---|---|---|---|---|
| clause:lastprivate + split:target \| parallel \| do | 24 | 21 | 0.875 | 0.56 | 2.76 |
| dir:target parallel + scalar:tofrom | 23 | 19 | 0.826 | 0.634 | 2.61 |
| dir:target parallel + split:target \| parallel \| do | 17 | 14 | 0.824 | 0.634 | 2.6 |
| dir:target parallel + scalar:firstprivate | 27 | 22 | 0.815 | 0.634 | 2.57 |
| base:out:int2 + dir:target parallel | 15 | 12 | 0.8 | 0.634 | 2.53 |
| chain:target parallel do + wrap:target_data | 15 | 12 | 0.8 | 0.451 | 2.53 |
| red:clause + split:target \| parallel \| do | 27 | 21 | 0.778 | 0.56 | 2.46 |
| base:al:dummy:allocatable + chain:target parallel do | 17 | 13 | 0.765 | 0.451 | 2.42 |

### cce20: run_error

Single features: base:dc:map_with_named_mapper (18/37, lift 15.63); base:dt:map:mod:mapper(mmap) (18/37, lift 15.63); base:dt:map:mod:close (8/59, lift 4.36); base:dt:map:mod:always (5/53, lift 3.03); base:al:optional_absent_in_map (8/99, lift 2.6); red:clause:min (4/52, lift 2.47); split:target | teams | loop (7/94, lift 2.39); base:al:dummy:explicit (10/143, lift 2.25)

| feature pair | programs | run_error | rate | best single rate | lift |
|---|---|---|---|---|---|
| base:dc:map_with_named_mapper + base:type:int8 | 17 | 12 | 0.706 | 0.486 | 22.68 |
| base:dt:map:mod:mapper(mmap) + base:type:int8 | 17 | 12 | 0.706 | 0.486 | 22.68 |
| base:dc:declare_mapper:named + base:dt:map:mod:close | 26 | 8 | 0.308 | 0.136 | 9.88 |
| base:dt:map:mod:close + base:view:complex8 | 23 | 6 | 0.261 | 0.136 | 8.38 |
| base:decl:explicit_int8 + base:dt:map:mod:close | 16 | 4 | 0.25 | 0.136 | 8.03 |
| base:al:dummy:explicit + base:out:real8 | 17 | 4 | 0.235 | 0.07 | 7.56 |
| base:al:pointer_output:target + base:dt:map:mod:close | 17 | 4 | 0.235 | 0.136 | 7.56 |
| base:dt:map:mod:close + body:inner_seq_loop | 17 | 4 | 0.235 | 0.136 | 7.56 |

### cce21: wrong_code

Single features: guard:par_thread0 (17/60, lift 4.49); guard:split_par_thread0 (7/27, lift 4.11); red:atomic:+ (4/16, lift 3.96); dir:distribute parallel do (4/17, lift 3.73); base:al:dummy:intent_out (5/26, lift 3.05); red:in_reduction:* (5/26, lift 3.05); red:clause:ieor (8/44, lift 2.88); guard:target_seq (4/22, lift 2.88)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| base:dt:map:component_section + red:clause:ieor | 15 | 7 | 0.467 | 0.182 | 7.4 |
| decl:allocatable_rank0 + guard:par_thread0 | 25 | 11 | 0.44 | 0.283 | 6.97 |
| base:al:allocatable_scalar + guard:par_thread0 | 39 | 16 | 0.41 | 0.283 | 6.5 |
| base:dt:default_init + guard:par_thread0 | 23 | 9 | 0.391 | 0.283 | 6.2 |
| base:type:logical + guard:par_thread0 | 31 | 11 | 0.355 | 0.283 | 5.62 |
| base:dc:declare_target_structure + guard:split_par_thread0 | 17 | 6 | 0.353 | 0.259 | 5.59 |
| base:decl:allocatable_int2 + red:clause:ieor | 17 | 6 | 0.353 | 0.182 | 5.59 |
| base:al:dummy:intent_inout + clause:in_reduction | 20 | 7 | 0.35 | 0.17 | 5.55 |

### cce21: ice

Single features: kernel:phase (109/109, lift 3.0); phase:do (95/95, lift 3.0); phase:single (62/62, lift 3.0); phase:do simd (61/61, lift 3.0); phase:masked (57/57, lift 3.0); phase:nowait_barrier (42/42, lift 3.0); map:alloc (39/39, lift 3.0); guard:single (35/35, lift 3.0)

| feature pair | programs | ice | rate | best single rate | lift |
|---|---|---|---|---|---|
| clause:in_reduction + dir:target parallel | 18 | 16 | 0.889 | 0.642 | 2.67 |
| dir:target parallel + dir:taskgroup | 18 | 16 | 0.889 | 0.642 | 2.67 |
| dir:target parallel + kernel:inred | 18 | 16 | 0.889 | 0.642 | 2.67 |
| clause:lastprivate + split:target \| parallel \| do | 24 | 21 | 0.875 | 0.569 | 2.62 |
| dir:target parallel + red:in_reduction:+ | 15 | 13 | 0.867 | 0.667 | 2.6 |
| dir:target parallel + scalar:tofrom | 23 | 19 | 0.826 | 0.642 | 2.48 |
| base:dc:declare_target_to + clause:in_reduction | 17 | 14 | 0.824 | 0.553 | 2.47 |
| base:dc:declare_target_to + dir:taskgroup | 17 | 14 | 0.824 | 0.553 | 2.47 |

### cce21: run_error

Single features: base:al:optional_absent_in_map (56/95, lift 7.54); base:al:dummy:intent_out (8/26, lift 3.94); base:al:dummy:pointer (5/20, lift 3.2); base:al:dummy:value (4/16, lift 3.2); base:al:dummy:explicit (33/136, lift 3.1); base:out:char (4/18, lift 2.84); base:al:dummy:optional (4/19, lift 2.69); base:al:structure_dummy (51/244, lift 2.67)

| feature pair | programs | run_error | rate | best single rate | lift |
|---|---|---|---|---|---|
| base:al:optional_absent_in_map + clause:collapse | 18 | 16 | 0.889 | 0.589 | 11.37 |
| base:al:optional_absent_in_map + chain:target parallel loop | 15 | 12 | 0.8 | 0.589 | 10.23 |
| base:al:optional_absent_in_map + clause:num_teams | 24 | 19 | 0.792 | 0.589 | 10.12 |
| base:al:optional_absent_in_map + dir:loop | 28 | 22 | 0.786 | 0.589 | 10.05 |
| base:al:optional_absent_in_map + clause:dist_schedule | 16 | 12 | 0.75 | 0.589 | 9.59 |
| base:al:optional_absent_in_map + chain:target simd | 19 | 14 | 0.737 | 0.589 | 9.42 |
| base:al:structure_dummy + clause:bind:teams | 16 | 8 | 0.5 | 0.209 | 6.39 |
| base:al:dummy:intent_out + base:dc:declare_target_structure | 18 | 8 | 0.444 | 0.308 | 5.68 |

### nvhpc: wrong_code

Single features: base:al:dummy:intent_in (4/18, lift 3.07); base:al:dummy:explicit (3/15, lift 2.77); red:clause (4/21, lift 2.63); base:decl:allocatable_complex4 (3/16, lift 2.59); map:mod:always (3/20, lift 2.08); base:al:kernel_in_internal_procedure (5/35, lift 1.98); base:spell:double_precision (5/35, lift 1.98); map:section (3/22, lift 1.89)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| loop:up + red:clause | 15 | 4 | 0.267 | 0.19 | 3.69 |
| base:type:complex4 + red:clause | 16 | 4 | 0.25 | 0.19 | 3.46 |
| base:type:real4 + red:clause | 16 | 4 | 0.25 | 0.19 | 3.46 |
| base:al:kernel_in_internal_procedure + base:spell:double_precision | 17 | 4 | 0.235 | 0.143 | 3.25 |
| base:decl:explicit_complex4 + base:spell:double_precision | 17 | 4 | 0.235 | 0.143 | 3.25 |
| base:spell:double_precision + base:type:real4 | 17 | 4 | 0.235 | 0.143 | 3.25 |
| base:al:allocatable_scalar + base:al:kernel_in_internal_procedure | 22 | 5 | 0.227 | 0.143 | 3.14 |
| base:al:kernel_in_internal_procedure + base:type:complex4 | 22 | 5 | 0.227 | 0.143 | 3.14 |

### nvhpc: run_error

Single features: dir:simd (7/16, lift 2.42); base:dc:declare_mapper:named (8/24, lift 1.84); base:dt:map:implicit (11/37, lift 1.65); base:dt:default_init (7/24, lift 1.61); body:call_declare_target (9/32, lift 1.56); dir:parallel (5/19, lift 1.46); dir:target (14/56, lift 1.38); base:dt:map:whole (6/24, lift 1.38)

| feature pair | programs | run_error | rate | best single rate | lift |
|---|---|---|---|---|---|
| base:al:pointer_component + body:call_declare_target | 17 | 8 | 0.471 | 0.281 | 2.6 |
| base:dt:map:implicit + base:view:char | 17 | 8 | 0.471 | 0.297 | 2.6 |
| base:dc:declare_mapper:named + dir:target | 16 | 7 | 0.438 | 0.333 | 2.42 |
| base:dt:map:implicit + base:view:complex8 | 16 | 7 | 0.438 | 0.297 | 2.42 |
| base:al:allocatable_component + base:dt:map:implicit | 17 | 7 | 0.412 | 0.297 | 2.28 |
| base:dt:component:nested:real8 + base:dt:map:implicit | 17 | 7 | 0.412 | 0.297 | 2.28 |
| base:dt:component:struct:real8 + base:dt:map:implicit | 22 | 9 | 0.409 | 0.297 | 2.26 |
| base:dt:map:implicit + map:to | 20 | 8 | 0.4 | 0.297 | 2.21 |

### nvhpc269: wrong_code

Single features: base:al:dummy:intent_in (4/18, lift 3.07); base:al:dummy:explicit (3/15, lift 2.77); red:clause (4/21, lift 2.63); base:decl:allocatable_complex4 (3/16, lift 2.59); map:mod:always (3/20, lift 2.08); base:al:kernel_in_internal_procedure (5/35, lift 1.98); base:spell:double_precision (5/35, lift 1.98); map:section (3/22, lift 1.89)

| feature pair | programs | wrong_code | rate | best single rate | lift |
|---|---|---|---|---|---|
| loop:up + red:clause | 15 | 4 | 0.267 | 0.19 | 3.69 |
| base:type:complex4 + red:clause | 16 | 4 | 0.25 | 0.19 | 3.46 |
| base:type:real4 + red:clause | 16 | 4 | 0.25 | 0.19 | 3.46 |
| base:al:kernel_in_internal_procedure + base:spell:double_precision | 17 | 4 | 0.235 | 0.143 | 3.25 |
| base:decl:explicit_complex4 + base:spell:double_precision | 17 | 4 | 0.235 | 0.143 | 3.25 |
| base:spell:double_precision + base:type:real4 | 17 | 4 | 0.235 | 0.143 | 3.25 |
| base:al:allocatable_scalar + base:al:kernel_in_internal_procedure | 22 | 5 | 0.227 | 0.143 | 3.14 |
| base:al:kernel_in_internal_procedure + base:type:complex4 | 22 | 5 | 0.227 | 0.143 | 3.14 |

### nvhpc269: run_error

Single features: dir:simd (7/16, lift 2.42); base:dc:declare_mapper:named (8/24, lift 1.84); base:dt:map:implicit (11/37, lift 1.65); base:dt:default_init (7/24, lift 1.61); body:call_declare_target (9/32, lift 1.56); dir:parallel (5/19, lift 1.46); dir:target (14/56, lift 1.38); base:dt:map:whole (6/24, lift 1.38)

| feature pair | programs | run_error | rate | best single rate | lift |
|---|---|---|---|---|---|
| base:al:pointer_component + body:call_declare_target | 17 | 8 | 0.471 | 0.281 | 2.6 |
| base:dt:map:implicit + base:view:char | 17 | 8 | 0.471 | 0.297 | 2.6 |
| base:dc:declare_mapper:named + dir:target | 16 | 7 | 0.438 | 0.333 | 2.42 |
| base:dt:map:implicit + base:view:complex8 | 16 | 7 | 0.438 | 0.297 | 2.42 |
| base:al:allocatable_component + base:dt:map:implicit | 17 | 7 | 0.412 | 0.297 | 2.28 |
| base:dt:component:nested:real8 + base:dt:map:implicit | 17 | 7 | 0.412 | 0.297 | 2.28 |
| base:dt:component:struct:real8 + base:dt:map:implicit | 22 | 9 | 0.409 | 0.297 | 2.26 |
| base:dt:map:implicit + map:to | 20 | 8 | 0.4 | 0.297 | 2.21 |

## Compile rejections (features not supported)

### afar

| programs | message |
|---|---|
| 134 | not_implemented: error: loc(".f90":L:C): <path> not yet implemented: lastprivate clause in constructs other than simd/worksharing-loop/taskloop |
| 101 | link_undefined_symbol: ld.lld: error: undefined symbol: flang_rt_verbose_abort(char const*, ...) |
| 52 | not_implemented: loc(".f90":L:C): error: not yet implemented: Unhandled clause order in omp.wsloop operation |
| 36 | not_implemented: error: loc(".f90":L:C): <path> not yet implemented: Firstprivate is currently unsupported defaultmap behaviour |
| 22 | not_implemented: loc(".f90":L:C): error: not yet implemented: Unhandled clause order in omp.distribute operation |
| 12 | not_implemented: error: loc(".f90":L:C): <path> not yet implemented: lastprivate(conditional:) on simd construct |
| 1 | not_implemented: error: loc(".f90":L:C): <path> not yet implemented: lastprivate(conditional:) on do simd composite construct |

Features most associated with rejection: base:dc:declare_reduction (152/152); red:clause:padd (152/152); defaultmap:firstprivate:scalar (29/29); clause:order (101/102); clause:lastprivate:conditional (21/26); clause:lastprivate (182/242); red:clause:ior (47/75); split:target teams distribute (10/16)

### cce19

| programs | message |
|---|---|
| 112 | diagnostic: ftn-1370 ftn: ERROR , \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET. |
| 42 | not_implemented: Unsupported OpenMP construct Calls -- $udr_i_1FUZZ_DMOD |
| 29 | not_implemented: Unsupported OpenMP construct Fortran character -- xc |
| 25 | diagnostic: ftn-1370 ftn: ERROR KP1, \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET. |
| 24 | diagnostic: ftn-1370 ftn: ERROR , \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET PARALLEL. |
| 23 | diagnostic: ftn-1747 ftn: ERROR , \| The stride specified for array "DR" must not be greater than 1. Subarray references in the MAP clause must be to contiguous memory. |
| 23 | not_implemented: Unsupported OpenMP construct Calls -- __GET_DYNAMIC_TYPE |
| 17 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP DISTRIBUTE. |
| 15 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 14 | not_implemented: Unsupported OpenMP construct Calls -- $udr_c_0FUZZ_DMOD |
| 7 | diagnostic: ftn-1370 ftn: ERROR KP1, \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET PARALLEL. |
| 6 | diagnostic: ftn-1370 ftn: ERROR KP2, \| The THREAD_LIMIT clause is not allowed with directive !$OMP TARGET. |

Features most associated with rejection: base:al:strided_update (41/42); clause:num_teams:lower_bound (32/33); base:out:char (22/24); base:dc:declare_reduction (134/152); red:clause:padd (134/152); clause:thread_limit (234/295); clause:order (77/102); dir:target parallel loop (15/21)

### cce20

| programs | message |
|---|---|
| 57 | not_implemented: Unsupported OpenMP construct Calls -- $udr_i_1FUZZ_DMOD |
| 28 | not_implemented: Unsupported OpenMP construct Calls -- __GET_DYNAMIC_TYPE |
| 26 | diagnostic: ftn-1747 ftn: ERROR , \| The stride specified for array "DR" must not be greater than 1. Subarray references in the MAP clause must be to contiguous memory. |
| 22 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP DISTRIBUTE. |
| 19 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 18 | not_implemented: Unsupported OpenMP construct Calls -- $udr_c_0FUZZ_DMOD |
| 6 | diagnostic: ftn-1725 ftn: ERROR KP1, \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 6 | diagnostic: ftn-1747 ftn: ERROR , \| The stride specified for array "MS" must not be greater than 1. Subarray references in the MAP clause must be to contiguous memory. |
| 4 | diagnostic: ftn-1747 ftn: ERROR , \| The stride specified for array "IA" must not be greater than 1. Subarray references in the MAP clause must be to contiguous memory. |
| 4 | diagnostic: ftn-1725 ftn: ERROR KP2, \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 4 | diagnostic: ftn-1370 ftn: ERROR KP1, \| The ORDER clause is not allowed with directive !$OMP DISTRIBUTE. |
| 3 | diagnostic: ftn-1747 ftn: ERROR , \| The stride specified for array "IB" must not be greater than 1. Subarray references in the MAP clause must be to contiguous memory. |

Features most associated with rejection: base:al:strided_update (42/42); clause:num_teams:lower_bound (33/33); base:dc:declare_reduction (123/152); red:clause:padd (123/152); split:target | teams distribute (13/23); split:target teams distribute (9/16); clause:order (57/102); split:target | parallel do simd (10/18)

### cce21

| programs | message |
|---|---|
| 56 | not_implemented: Unsupported OpenMP construct Calls -- $udr_i_1FUZZ_DMOD |
| 41 | link_undefined_symbol: lld: error: undefined symbol: _cray$mt_taskwait |
| 28 | not_implemented: Unsupported OpenMP construct Calls -- __GET_DYNAMIC_TYPE |
| 26 | diagnostic: ftn-1747 ftn: ERROR , \| The stride specified for array "DR" in the MAP clause must not be greater than 1. |
| 22 | diagnostic: ftn-1370 ftn: ERROR , \| The ORDER clause is not allowed with directive !$OMP DISTRIBUTE. |
| 19 | not_implemented: Unsupported OpenMP construct Calls -- $udr_c_0FUZZ_DMOD |
| 19 | diagnostic: ftn-1725 ftn: ERROR , \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 6 | diagnostic: ftn-1725 ftn: ERROR KP1, \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 6 | diagnostic: ftn-1747 ftn: ERROR , \| The stride specified for array "MS" in the MAP clause must not be greater than 1. |
| 4 | diagnostic: ftn-1747 ftn: ERROR , \| The stride specified for array "IA" in the MAP clause must not be greater than 1. |
| 4 | diagnostic: ftn-1725 ftn: ERROR KP2, \| Unexpected syntax while parsing the DIRECTIVE statement : ")" was expected but found ":". |
| 4 | diagnostic: ftn-1370 ftn: ERROR KP1, \| The ORDER clause is not allowed with directive !$OMP DISTRIBUTE. |

Features most associated with rejection: base:al:strided_update (42/42); clause:num_teams:lower_bound (33/33); base:dc:declare_reduction (124/152); red:clause:padd (124/152); red:in_reduction:* (40/66); clause:in_reduction (66/113); dir:taskgroup (66/113); kernel:inred (66/113)

### nvhpc

| programs | message |
|---|---|
| 61 | not_implemented: NVFORTRAN-S-0155-Intrinsic not supported in initialization: mod (fuzz_dmod.f90: 29) |
| 59 | not_implemented: NVFORTRAN-S-0155-Intrinsic not supported in initialization: mod (fuzz_dmod.f90: 27) |
| 46 | not_implemented: NVFORTRAN-S-0155-Intrinsic not supported in initialization: mod (fuzz_dmod.f90: 30) |
| 43 | not_implemented: NVFORTRAN-S-0155-Intrinsic not supported in initialization: mod (fuzz_dmod.f90: 31) |
| 41 | not_implemented: NVFORTRAN-S-0155-Intrinsic not supported in initialization: mod (fuzz_dmod.f90: 28) |
| 39 | not_implemented: NVFORTRAN-S-0155-Intrinsic not supported in initialization: mod (fuzz_dmod.f90: 32) |
| 38 | not_implemented: NVFORTRAN-S-0155-Intrinsic not supported in initialization: mod (fuzz_dmod.f90: 25) |
| 35 | not_implemented: NVFORTRAN-S-0155-Intrinsic not supported in initialization: mod (fuzz_dmod.f90: 26) |
| 28 | not_implemented: NVFORTRAN-S-0155-Intrinsic not supported in initialization: mod (fuzz_dmod.f90: 33) |
| 26 | not_implemented: NVFORTRAN-W-0287-Unrecognized OpenMP directive - declare (fuzz_dmod.f90: 30) |
| 26 | not_implemented: NVFORTRAN-W-0287-Unrecognized OpenMP directive - declare (fuzz_dmod.f90: 32) |
| 23 | not_implemented: NVFORTRAN-W-0287-Unrecognized OpenMP directive - declare (fuzz_dmod.f90: 29) |

Features most associated with rejection: base:dc:static_init (489/489); map:mod:close (246/246); base:dc:declare_reduction (152/152); red:clause:padd (152/152); map:mod:present (133/133); clause:in_reduction (113/113); dir:taskgroup (113/113); kernel:inred (113/113)

### nvhpc269

| programs | message |
|---|---|
| 61 | not_implemented: NVFORTRAN-S-0155-Intrinsic not supported in initialization: mod (fuzz_dmod.f90: 29) |
| 59 | not_implemented: NVFORTRAN-S-0155-Intrinsic not supported in initialization: mod (fuzz_dmod.f90: 27) |
| 46 | not_implemented: NVFORTRAN-S-0155-Intrinsic not supported in initialization: mod (fuzz_dmod.f90: 30) |
| 43 | not_implemented: NVFORTRAN-S-0155-Intrinsic not supported in initialization: mod (fuzz_dmod.f90: 31) |
| 41 | not_implemented: NVFORTRAN-S-0155-Intrinsic not supported in initialization: mod (fuzz_dmod.f90: 28) |
| 39 | not_implemented: NVFORTRAN-S-0155-Intrinsic not supported in initialization: mod (fuzz_dmod.f90: 32) |
| 38 | not_implemented: NVFORTRAN-S-0155-Intrinsic not supported in initialization: mod (fuzz_dmod.f90: 25) |
| 35 | not_implemented: NVFORTRAN-S-0155-Intrinsic not supported in initialization: mod (fuzz_dmod.f90: 26) |
| 28 | not_implemented: NVFORTRAN-S-0155-Intrinsic not supported in initialization: mod (fuzz_dmod.f90: 33) |
| 26 | not_implemented: NVFORTRAN-W-0287-Unrecognized OpenMP directive - declare (fuzz_dmod.f90: 30) |
| 26 | not_implemented: NVFORTRAN-W-0287-Unrecognized OpenMP directive - declare (fuzz_dmod.f90: 32) |
| 23 | not_implemented: NVFORTRAN-W-0287-Unrecognized OpenMP directive - declare (fuzz_dmod.f90: 29) |

Features most associated with rejection: base:dc:static_init (489/489); map:mod:close (246/246); base:dc:declare_reduction (152/152); red:clause:padd (152/152); map:mod:present (133/133); clause:in_reduction (113/113); dir:taskgroup (113/113); kernel:inred (113/113)

## Generator rejects

Programs failing a legality check are never run. Causes (`rules`: a 5.2 rule of offload.engine.rules fired, a generator or rule bug; `flang`: AFAR flang's frontend refused a program the rules and gfortran accept; see the report for which of these are flang's errors):

| count | cause | seeds |
|---|---|---|

## Flaky results

- seed 63 cce20: wrong_code: checksum=1571965645 ran_on_host=0 expected=443005736 | wrong_code: checksum=689135237 ran_on_host=0 expected=443005736 | wrong_code: checksum=1138969482 ran_on_host=0 expected=443005736 | wrong_code: checksum=1138969482 ran_on_host=0 expected=443005736
- seed 63 cce21: wrong_code: checksum=1860519903 ran_on_host=0 expected=443005736 | wrong_code: checksum=1741664673 ran_on_host=0 expected=443005736 | wrong_code: checksum=1622809443 ran_on_host=0 expected=443005736 | wrong_code: checksum=570280007 ran_on_host=0 expected=443005736
- seed 144 cce19: wrong_code: checksum=366675347 ran_on_host=0 expected=1954551183 | wrong_code: checksum=850509825 ran_on_host=0 expected=1954551183 | wrong_code: checksum=557896235 ran_on_host=0 expected=1954551183 | wrong_code: checksum=366675347 ran_on_host=0 expected=1954551183
- seed 188 cce20: wrong_code: checksum=57130983 ran_on_host=0 expected=805342982 | wrong_code: checksum=1616426414 ran_on_host=0 expected=805342982 | wrong_code: checksum=2107462244 ran_on_host=0 expected=805342982 | wrong_code: checksum=1810731150 ran_on_host=0 expected=805342982
- seed 188 cce21: wrong_code: checksum=708190614 ran_on_host=0 expected=805342982 | wrong_code: checksum=1713578782 ran_on_host=0 expected=805342982 | wrong_code: checksum=57130983 ran_on_host=0 expected=805342982 | wrong_code: checksum=2107462244 ran_on_host=0 expected=805342982
- seed 220 cce20: wrong_code: checksum=1282544995 ran_on_host=0 expected=160939424 | wrong_code: checksum=1282544995 ran_on_host=0 expected=160939424 | wrong_code: checksum=2088072533 ran_on_host=0 expected=160939424 | wrong_code: checksum=1282544995 ran_on_host=0 expected=160939424
- seed 220 cce21: wrong_code: checksum=2088072533 ran_on_host=0 expected=160939424 | wrong_code: checksum=1282544995 ran_on_host=0 expected=160939424 | wrong_code: checksum=1282544995 ran_on_host=0 expected=160939424 | wrong_code: checksum=1282544995 ran_on_host=0 expected=160939424
- seed 225 cce19: wrong_code: checksum=341774218 ran_on_host=0 expected=679102078 | wrong_code: checksum=2138480923 ran_on_host=0 expected=679102078 | wrong_code: checksum=1112405736 ran_on_host=0 expected=679102078 | wrong_code: checksum=1718593251 ran_on_host=0 expected=679102078
- seed 225 cce20: wrong_code: checksum=394377840 ran_on_host=0 expected=679102078 | wrong_code: checksum=394377840 ran_on_host=0 expected=679102078 | wrong_code: checksum=1268169793 ran_on_host=0 expected=679102078 | wrong_code: checksum=394377840 ran_on_host=0 expected=679102078
- seed 821 cce20: wrong_code: checksum=606361513 ran_on_host=0 expected=832957351 | wrong_code: checksum=1685639739 ran_on_host=0 expected=832957351 | wrong_code: checksum=1685639739 ran_on_host=0 expected=832957351 | wrong_code: checksum=1696712562 ran_on_host=0 expected=832957351
- seed 821 cce21: wrong_code: checksum=617434336 ran_on_host=0 expected=832957351 | wrong_code: checksum=99940869 ran_on_host=0 expected=832957351 | wrong_code: checksum=617434336 ran_on_host=0 expected=832957351 | wrong_code: checksum=606361513 ran_on_host=0 expected=832957351
- seed 900 cce19: wrong_code: checksum=1202870376 ran_on_host=0 expected=260880893 | wrong_code: checksum=367486647 ran_on_host=0 expected=260880893 | wrong_code: checksum=644541959 ran_on_host=0 expected=260880893 | wrong_code: checksum=666385696 ran_on_host=0 expected=260880893
- seed 983 cce19: wrong_code: checksum=1027631008 ran_on_host=0 expected=841519176 | wrong_code: checksum=1052004270 ran_on_host=0 expected=841519176 | wrong_code: checksum=1638003714 ran_on_host=0 expected=841519176 | wrong_code: checksum=1425837822 ran_on_host=0 expected=841519176
- seed 983 cce20: wrong_code: checksum=2003971403 ran_on_host=0 expected=841519176 | wrong_code: checksum=2003971403 ran_on_host=0 expected=841519176 | wrong_code: checksum=37224843 ran_on_host=0 expected=841519176 | wrong_code: checksum=37224843 ran_on_host=0 expected=841519176

## Appendix: host reference checks (not offload findings)

Device offload only: host runs (OMP_TARGET_OFFLOAD=disabled) and the sequential elision are references for the expected value, never measurements of a toolchain. A host_path_failure below is recorded data (results/fuzz/<run>/summary.json), not an offload finding, and it counts nowhere in the tables above.

The reference host run (OMP_TARGET_OFFLOAD=disabled, the first toolchain that compiled) failed for 1 programs (host_ref_failed) and printed another checksum than the model for 12 (host_mismatch). For each, every toolchain whose build compiled ran it on the host (rebuilt and run twice: results/fuzz/n1x0/hostcheck.jsonl), and the sequential elision (offload.engine.expected) ran where it applies. Rule: **valid** when at least one of them prints the model's checksum; the host builds that ran and did not are `host_path_failure` records (a host-path compiler or runtime bug: out of scope, not an offload finding). **noncompliant** when none does (a generator or model defect): excluded from the findings and the tallies above. A toolchain whose build does not compile has no host build ('no host build'). Values are host checksums. Scope: only these programs had every toolchain's host build run; for the others only the reference toolchain's host run exists, so host_path_failure counts are a lower bound.

| seed | reference | ref tc | model | afar host | cce19 host | cce20 host | cce21 host | nvhpc host | nvhpc269 host | elision | validity | host_path_failure |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 227 | host_mismatch | cce19 | 930153208 | no build: compile_reject | 1905780238 | 1905780238 | 1905780238 | - | - | inapplicable: declare mapper; module variables (declare targ | noncompliant | - |
| 271 | host_mismatch | cce19 | 1371992384 | no build: compile_reject | 1406752632 | **1371992384** | **1371992384** | - | - | inapplicable: declare mapper; declare target variable; modul | valid | cce19 |
| 397 | host_mismatch | cce19 | 1893763377 | no build: compile_reject | 2090951601 | 2090951601 | no build: compile_reject | - | - | inapplicable: declare target variable; module variables (dec | noncompliant | - |
| 544 | host_mismatch | cce19 | 1868373421 | no build: compile_reject | 666731731 | 666731731 | no build: compile_reject | - | - | inapplicable: declare target variable; module variables (dec | noncompliant | - |
| 580 | host_mismatch | cce19 | 1773381408 | no build: compile_reject | 762087600 | **1773381408** | **1773381408** | - | - | inapplicable: declare mapper; declare target variable; modul | valid | cce19 |
| 602 | host_mismatch | afar | 886354534 | 2039467773 | **886354534** | **886354534** | **886354534** | - | - | inapplicable: declare target variable; floating-point reduct | valid | afar |
| 639 | host_mismatch | cce19 | 1964070968 | no build: compile_reject | 879310639 | 879310639 | 879310639 | - | - | inapplicable: declare mapper; declare target variable; modul | noncompliant | - |
| 640 | host_mismatch | cce19 | 965260611 | no build: compile_reject | 1527934883 | **965260611** | **965260611** | - | - | inapplicable: declare target variable; module variables (dec | valid | cce19 |
| 669 | host_ref_failed | afar | 1600762540 | crash: SIGABRT | no build: compile_reject | **1600762540** | **1600762540** | - | - | inapplicable: declare mapper; declare target variable; modul | valid | afar |
| 683 | host_mismatch | cce20 | 668796664 | no build: compile_reject | no build: compile_reject | 1257176480 | no build: compile_reject | - | - | inapplicable: declare target variable; module variables (dec | noncompliant | - |
| 840 | host_mismatch | cce20 | 1787002291 | no build: compile_reject | no build: compile_reject | 1445265582 | no build: compile_reject | - | - | inapplicable: declare mapper; declare target variable; modul | noncompliant | - |
| 966 | host_mismatch | afar | 364022541 | 1506652054 | no build: compile_reject | no build: ice | no build: ice | - | - | inapplicable: declare mapper; declare target variable; modul | noncompliant | - |
| 985 | host_mismatch | cce20 | 1668679914 | no build: compile_reject | no build: compile_reject | 212356655 | no build: compile_reject | - | - | inapplicable: declare target variable; module variables (dec | noncompliant | - |

### host_path_failure (valid programs; host-path failures, out of scope)

- afar: 2 programs (seeds 602, 669)
- cce19: 3 programs (seeds 271, 580, 640)

### Noncompliant programs (generator/model investigation)

No available host build prints the model's checksum. Their device classes (not counted anywhere above):

- seed 227: model 930153208; host afar no host build: compile_reject, cce19 1905780238, cce20 1905780238, cce21 1905780238, nvhpc -, nvhpc269 -; elision inapplicable: declare mapper; module variables (declare target visibility); user-defined reduction; device afar compile_reject, cce19 wrong_code, cce20 wrong_code, cce21 wrong_code, nvhpc compile_reject, nvhpc269 compile_reject
- seed 397: model 1893763377; host afar no host build: compile_reject, cce19 2090951601, cce20 2090951601, cce21 no host build: compile_reject, nvhpc -, nvhpc269 -; elision inapplicable: declare target variable; module variables (declare target visibility); present modifier; user-defined reduction; device afar compile_reject, cce19 wrong_code, cce20 wrong_code, cce21 compile_reject, nvhpc compile_reject, nvhpc269 compile_reject
- seed 544: model 1868373421; host afar no host build: compile_reject, cce19 666731731, cce20 666731731, cce21 no host build: compile_reject, nvhpc -, nvhpc269 -; elision inapplicable: declare target variable; module variables (declare target visibility); user-defined reduction; device afar compile_reject, cce19 wrong_code, cce20 wrong_code, cce21 compile_reject, nvhpc compile_reject, nvhpc269 compile_reject
- seed 639: model 1964070968; host afar no host build: compile_reject, cce19 879310639, cce20 879310639, cce21 879310639, nvhpc -, nvhpc269 -; elision inapplicable: declare mapper; declare target variable; module variables (declare target visibility); device afar compile_reject, cce19 wrong_code, cce20 wrong_code, cce21 wrong_code, nvhpc compile_reject, nvhpc269 compile_reject
- seed 683: model 668796664; host afar no host build: compile_reject, cce19 no host build: compile_reject, cce20 1257176480, cce21 no host build: compile_reject, nvhpc -, nvhpc269 -; elision inapplicable: declare target variable; module variables (declare target visibility); device afar compile_reject, cce19 compile_reject, cce20 agree, cce21 compile_reject, nvhpc compile_reject, nvhpc269 compile_reject
- seed 840: model 1787002291; host afar no host build: compile_reject, cce19 no host build: compile_reject, cce20 1445265582, cce21 no host build: compile_reject, nvhpc -, nvhpc269 -; elision inapplicable: declare mapper; declare target variable; module variables (declare target visibility); device afar compile_reject, cce19 compile_reject, cce20 agree, cce21 compile_reject, nvhpc compile_reject, nvhpc269 compile_reject
- seed 966: model 364022541; host afar 1506652054, cce19 no host build: compile_reject, cce20 no host build: ice, cce21 no host build: ice, nvhpc -, nvhpc269 -; elision inapplicable: declare mapper; declare target variable; module variables (declare target visibility); device afar agree, cce19 compile_reject, cce20 ice, cce21 ice, nvhpc compile_reject, nvhpc269 compile_reject
- seed 985: model 1668679914; host afar no host build: compile_reject, cce19 no host build: compile_reject, cce20 212356655, cce21 no host build: compile_reject, nvhpc -, nvhpc269 -; elision inapplicable: declare target variable; module variables (declare target visibility); present modifier; device afar compile_reject, cce19 compile_reject, cce20 wrong_code, cce21 compile_reject, nvhpc compile_reject, nvhpc269 compile_reject
