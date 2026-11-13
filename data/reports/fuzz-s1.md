# Fuzz campaign s1: every base-language group combined

Generator `fuzz-3` with all five base-language groups at once (`types
derived alloc declare multitu`, offload.engine.fuzz_base), the way real codes
combine features; toolchains afar, cce19, cce20, cce21 (-O2,
OMP_TARGET_OFFLOAD=mandatory, THP always); Tuolumne MI300A (gfx942).

- `s1`: seeds 1-10000 at HSA_XNACK=1 (unified memory), run as twenty
  one-hour chunks s1-00 .. s1-19 (500 seeds each) and merged
  (`tools/campaigns/fuzz.py merge`; results/fuzz/s1).
- `s1x0`: seeds 1-2500 at HSA_XNACK=0 (copy mode), chunks s1x0-00 ..
  s1x0-04, merged (results/fuzz/s1x0).
- The confirmer names a program `s1:<seed>` in both (catalog/
  fuzz_campaigns.yaml), so a copy-mode cell finds the unified cell of the
  same seed.
- gfx90a (Tioga MI250X): not run for the campaign (see Concerns).

Triage: every failing cell went through the confirmer (`tools/confirm.py
batch`: legality gate, rules, collectors; compile cells offline from the
stored rows, run-time cells with runs on flux: repeats, the other memory
mode for seeds above 2500, metamorphic rewrites on the failing toolchain
and on another family's toolchain that ran the program), the host
check (`tools/campaigns/fuzz.py host-check`) and the sequential elision of every
program (`tools/campaigns/fuzz.py elide`). An agent (this task) decided only what
the rules left needs_human (catalog/triage_28.yaml `decisions`) and
re-read a seeded 10% of each verdict class (`spot_checks`); every
disagreement became a rule fix with a test and a rerun (in
data/reports/rulings.md).

## Summary

- Programs: s1 10,000 (9,994 legal by the generator's checks, 70 of them
  noncompliant by the host check), s1x0 2,500 (2,498 legal, 19
  noncompliant). 34,819 failing cells went through the confirmer (both
  modes, the fuzz-4 reruns included).
- Final verdicts (s1 and s1x0 cells, after the agent decisions; fix
  ): compiler_bug 17,217, unsupported 15,705, needs_human 1,778,
  our_bug 57 (generator defect G1), flaky 9, environment 1 (unified:
  compiler_bug 13,762, unsupported 12,558, needs_human 1,452; copy: 3,455,
  3,147, 326). The tables below give them per compiler and mode. Fix
  Moved CCE 20's 7,099 `enter` rejections from unsupported to
  compiler_bug (its 20.0.0 release note claims the new 5.2 declare target
  syntax: 4,502 by R11, 2,597 by decision D9), 29 presence/overlap aborts
  from R20 to R22 (AFAR at HSA_XNACK=1 no longer witnesses them; 18 of
  them then decided by D6 or D8), and 448 run-time "instance of" links to
  related (a fuzz instance needs a distinctive key construct or the
  finding's own runtime message).
- What drives the CCE compile rejections (CCE 19: 9,671 of the 12,403
  judged cells, 78%; CCE 20: 8,318, 67%): forms that OpenMP 5.1/5.2 added
  that CCE 19/20 do not claim, decided unsupported by rule R11c, and the
  5.2 spelling `declare target enter(...)`: 7,091 CCE 19 cells
  (unsupported, no claim) and 7,090 CCE 20 cells (compiler_bug: CCE
  20.0.0's release note claims the new 5.2 declare target syntax, whose
  only new form is enter). Every program that uses it (5,588 of 9,994 in
  s1; the generator spells it `to` in the others) is rejected by CCE 19
  and 20 at its first module, so no other construct of those programs is
  measured on them; CCE 21 claims `enter` (Fortran) and accepts it. Then
  thread_limit on target (5.1; CCE 19 only, 936 cells; CCE 19's own claim
  of it is C/C++ only), defaultmap's `all` category (5.2; CCE 19, 503),
  num_teams lower bounds (5.1; all three, 157/200/475), order on
  distribute (5.1; 143/187/409), and not-implemented messages (user
  reductions called on the device, polymorphic calls, character data;
  R05). Bugs among the rejections: CCE 19/20/21 reject strided array
  sections in `target update` (988 cells, new finding s1-6888), and
  false default(none)/defaultmap(none)/firstprivate diagnostics (new
  finding s1-2370 and decisions D2-D5). Without the enter programs CCE
  19 rejects 49% and CCE 20 24% (CCE 21 28%, AFAR 35%).
- New findings (data/findings/fuzz/s1-*.f90, one per distinct signature,
  each reduced and run on all four toolchains; the compile-time ones also
  on Tioga gfx90a where noted): CCE 19-21 reject strided target update
  (s1-6888); CCE 19-21 reject firstprivate(i) on a parallel do in a teams
  distribute loop (s1-2370); CCE false default(none) diagnostic across
  sibling internal subroutines (s1-91); CCE 19-21 ICE on a character
  scalar in target enter/exit data, three ICE messages (s1-8634); CCE 19-21
  ICE "Should never reach this code" on in_reduction with a character
  dummy substring (s1-2592); CCE 19-21 ICE "Error getting dope vector
  information" (s1-3463); CCE 20/21 optcg abort with a pointer-component
  map and a derived-type reduction (s1-6085); CCE 19 compile that does not
  finish (s1-9914); CCE 19-21 present-table failure for a character array
  mapped by target data (s1-7882); CCE 20 rejects `declare target enter`,
  which its release notes claim (s1-6760). s1-9443 (AFAR
  present abort at HSA_XNACK=1 with map(close, present) inside target
  data) reduced by hand to the known close + present abort
  of 158-afar/1131-afar. Four further run-time representatives reduced to
  known findings (b3-61/b3-250 in_reduction, cce21-defaultmap-aggregate-
  flag, b3-54 empty target nowait, b3-9 absent optional) six representatives of the largest groups that lost their instance
  links (CCE 21 SIGSEGV, AFAR SIGSEGV, AFAR "Failed to process data",
  AFAR and CCE 20 memory faults): five reduce to known families (absent
  optional map, b3-54, b4-86 named mapper), one (seed 4339) to an AFAR
  memory fault with map(close, ...) at HSA_XNACK=1 (see the task report).
- Interactions (pairs with at least 30 programs on each side): the
  strongest are CCE 19/20 wrong code for kernels in internal procedures
  (dummy arguments) with taskgroup task_reduction + target in_reduction
  (the known fuzz/b3-61 family; 50/93 and 86/157 programs fail, against
  9/172 and 16/275 with in_reduction outside an internal procedure and
  65/657, 87/1010 for the dummies without in_reduction); AFAR crashes for
  a named declare mapper with distribute (49/110, against 54/244 and
  389/1773); AFAR ICE for assumed-shape dummies with nontemporal (the
  known afar-nontemporal-assumed-shape-ice); CCE 21 wrong code for value
  dummies with reduction(+) (18/34). Full tables below.
- Copy mode (s1x0 against seeds 1-2500 of s1): failures only in copy mode
  AFAR 19, CCE 19 11, CCE 20 7, CCE 21 11 (CCE: GPU memory access faults
  and hipErrorIllegalAddress in copy mode; AFAR: present-modifier
  aborts); only in unified mode AFAR 43 (present-modifier aborts and GPU
  memory faults at HSA_XNACK=1), none for CCE.
- Generator defects: G1 (fuzz-3), default(none) on a combined construct
  without the variable of an if clause of a nested leaf (11 s1 programs,
  b5 seed 193), found from CCE's ftn-1510; fixed in fuzz-4, seeds rerun
  (s1g4, s1g4x0, b5g4: the CCE rejections go, new ICE and run-time cells
  appear and are confirmed like the others). No model disagreement with
  the sequential elision (it applies to 25 programs, all equal to the
  model). The 89 noncompliant programs are not generator bugs as far as
  checked: 51 use lastprivate(conditional:), where CCE's host fallback is
  wrong too (known finding b2-209) and AFAR does not implement it; the
  rest have host builds of one family only (needs_human).
- needs_human left: 1,778 cells, mostly run-time failures whose expected
  value has only the model as a source (the elision does not apply to
  programs with declare target variables, mappers or several files, and
  no other family ran the program to give a metamorphic source): AFAR
  crashes where CCE 19/20 reject `enter` and CCE 21 also fails. They are
  counted, not decided.


<!-- t28:begin (generated) -->
### Programs

| run | memory mode | programs | passed the legality checks | noncompliant (host check) |
|---|---|---|---|---|
| s1 | unified | 10000 | 9994 | 70 |
| s1x0 | copy | 2500 | 2498 | 19 |

Total 12500 programs, 12492 legal by the checks, 89 noncompliant (left out of the rates below).

### Outcome per compiler and memory mode

Outcome classes of the stored runs (a run_error with a signal is a crash; host_fallback is a region that reported a host run under OMP_TARGET_OFFLOAD=mandatory).

| mode | toolchain | programs | agree | compile_reject | ice | compile_timeout | wrong_code | crash | run_error | timeout | host_fallback | harness_error |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| unified | afar | 9924 | 5274 (53.1%) | 3477 (35.0%) | 76 (0.8%) |  | 159 (1.6%) | 938 (9.5%) |  |  |  |  |
| unified | cce19 | 9924 | 1271 (12.8%) | 7687 (77.5%) | 680 (6.9%) | 76 (0.8%) | 148 (1.5%) | 38 (0.4%) | 24 (0.2%) |  |  |  |
| unified | cce20 | 9924 | 1934 (19.5%) | 6611 (66.6%) | 1036 (10.4%) | 6 (0.1%) | 200 (2.0%) | 91 (0.9%) | 46 (0.5%) |  |  |  |
| unified | cce21 | 9924 | 3652 (36.8%) | 2797 (28.2%) | 2403 (24.2%) | 17 (0.2%) | 410 (4.1%) | 626 (6.3%) | 19 (0.2%) |  |  |  |
| copy | afar | 2479 | 1323 (53.4%) | 891 (35.9%) | 27 (1.1%) |  | 35 (1.4%) | 203 (8.2%) |  |  |  |  |
| copy | cce19 | 2479 | 321 (12.9%) | 1913 (77.2%) | 173 (7.0%) | 16 (0.6%) | 33 (1.3%) | 16 (0.6%) | 7 (0.3%) |  |  |  |
| copy | cce20 | 2479 | 480 (19.4%) | 1648 (66.5%) | 263 (10.6%) | 1 (0.0%) | 51 (2.1%) | 25 (1.0%) | 10 (0.4%) |  |  | 1 (0.0%) |
| copy | cce21 | 2479 | 913 (36.8%) | 687 (27.7%) | 607 (24.5%) | 3 (0.1%) | 99 (4.0%) | 153 (6.2%) | 16 (0.6%) | 1 (0.0%) |  |  |

### Confirmer verdicts per compiler and memory mode

Every failing cell (`tools/confirm.py batch`), after the agent decisions of catalog/triage_28.yaml for the cases the rules leave needs_human.

| mode | toolchain | failing cells | compiler_bug | unsupported | our_bug | flaky | environment | needs_human |
|---|---|---|---|---|---|---|---|---|
| unified | afar | 4721 | 1511 | 2530 | 7 | 6 |  | 667 |
| unified | cce19 | 8731 | 1066 | 7559 | 11 |  |  | 95 |
| unified | cce20 | 8063 | 7147 | 758 | 11 |  |  | 147 |
| unified | cce21 | 6340 | 4059 | 1723 | 11 | 1 |  | 546 |
| copy | afar | 1176 | 376 | 659 | 2 |  |  | 139 |
| copy | cce19 | 2182 | 274 | 1879 | 5 | 1 |  | 23 |
| copy | cce20 | 2020 | 1793 | 187 | 5 | 1 | 1 | 33 |
| copy | cce21 | 1586 | 1021 | 428 | 5 |  |  | 132 |

#### By rule

| toolchain | rule | decided by | cells |
|---|---|---|---|
| afar | R03-illegal | rules | 9 |
| afar | R05-unsupported | rules | 3189 |
| afar | R09-flaky | rules | 6 |
| afar | R10-compile-ice | rules | 105 |
| afar | R10b-own-link-or-hang | rules | 1257 |
| afar | R13c-fuzz-noncompliant-weak | rules | 2 |
| afar | R20-runtime-bug | rules | 488 |
| afar | R22-expected-weak | D8-crash-another-family-runs-it | 37 |
| afar | R22-expected-weak | rules | 791 |
| afar | R22b-expected-disputed-late | rules | 13 |
| cce19 | R03-illegal | rules | 16 |
| cce19 | R05-unsupported | rules | 598 |
| cce19 | R09-flaky | rules | 1 |
| cce19 | R10-compile-ice | rules | 854 |
| cce19 | R10b-own-link-or-hang | rules | 93 |
| cce19 | R11-compile-rejection | rules | 117 |
| cce19 | R11c-later-form-unclaimed | rules | 8840 |
| cce19 | R12b-compile-undecided | D1-strided-target-update | 98 |
| cce19 | R12b-compile-undecided | D3-default-none-false-diagnostic | 2 |
| cce19 | R12b-compile-undecided | D4-defaultmap-none-mapped-variable | 11 |
| cce19 | R12b-compile-undecided | D5-firstprivate-split-to-the-worksharing-leaf | 3 |
| cce19 | R13c-fuzz-noncompliant-weak | D6-cce-unhandled-reduction | 3 |
| cce19 | R13c-fuzz-noncompliant-weak | D7-cce-target-simd-lastprivate-conditional | 1 |
| cce19 | R13c-fuzz-noncompliant-weak | rules | 11 |
| cce19 | R20-runtime-bug | rules | 133 |
| cce19 | R22-expected-weak | D6-cce-unhandled-reduction | 12 |
| cce19 | R22-expected-weak | D8-crash-another-family-runs-it | 13 |
| cce19 | R22-expected-weak | rules | 103 |
| cce19 | R22b-expected-disputed-late | rules | 4 |
| cce20 | R01-environment | rules | 1 |
| cce20 | R03-illegal | rules | 16 |
| cce20 | R05-unsupported | rules | 558 |
| cce20 | R09-flaky | rules | 1 |
| cce20 | R10-compile-ice | rules | 1301 |
| cce20 | R10b-own-link-or-hang | rules | 7 |
| cce20 | R11-compile-rejection | rules | 4642 |
| cce20 | R11c-later-form-unclaimed | rules | 387 |
| cce20 | R12b-compile-undecided | D1-strided-target-update | 116 |
| cce20 | R12b-compile-undecided | D3-default-none-false-diagnostic | 6 |
| cce20 | R12b-compile-undecided | D4-defaultmap-none-mapped-variable | 2 |
| cce20 | R12b-compile-undecided | D5-firstprivate-split-to-the-worksharing-leaf | 6 |
| cce20 | R12b-compile-undecided | D9-cce20-declare-target-enter | 2597 |
| cce20 | R13c-fuzz-noncompliant-weak | D6-cce-unhandled-reduction | 5 |
| cce20 | R13c-fuzz-noncompliant-weak | D7-cce-target-simd-lastprivate-conditional | 3 |
| cce20 | R13c-fuzz-noncompliant-weak | rules | 13 |
| cce20 | R20-runtime-bug | rules | 216 |
| cce20 | R22-expected-weak | D6-cce-unhandled-reduction | 22 |
| cce20 | R22-expected-weak | D8-crash-another-family-runs-it | 17 |
| cce20 | R22-expected-weak | rules | 161 |
| cce20 | R22b-expected-disputed-late | rules | 6 |
| cce21 | R03-illegal | rules | 16 |
| cce21 | R05-unsupported | rules | 1265 |
| cce21 | R09-flaky | rules | 1 |
| cce21 | R10-compile-ice | rules | 3017 |
| cce21 | R10b-own-link-or-hang | rules | 701 |
| cce21 | R11-compile-rejection | rules | 366 |
| cce21 | R11c-later-form-unclaimed | rules | 886 |
| cce21 | R12b-compile-undecided | D1-strided-target-update | 246 |
| cce21 | R12b-compile-undecided | D2-default-none-loop-variable | 2 |
| cce21 | R12b-compile-undecided | D3-default-none-false-diagnostic | 24 |
| cce21 | R12b-compile-undecided | D4-defaultmap-none-mapped-variable | 5 |
| cce21 | R12b-compile-undecided | D5-firstprivate-split-to-the-worksharing-leaf | 18 |
| cce21 | R12b-compile-undecided | rules | 1 |
| cce21 | R13c-fuzz-noncompliant-weak | D6-cce-unhandled-reduction | 3 |
| cce21 | R13c-fuzz-noncompliant-weak | D7-cce-target-simd-lastprivate-conditional | 7 |
| cce21 | R13c-fuzz-noncompliant-weak | rules | 41 |
| cce21 | R20-runtime-bug | rules | 592 |
| cce21 | R22-expected-weak | D6-cce-unhandled-reduction | 18 |
| cce21 | R22-expected-weak | D8-crash-another-family-runs-it | 81 |
| cce21 | R22-expected-weak | rules | 630 |
| cce21 | R22b-expected-disputed-late | rules | 6 |

### What the compile rejections are

Each rejected cell by the verdict, the rule and its cause (the later form R11c names, else the diagnostic without positions and names); the twelve most frequent per toolchain.


#### afar (4453 rejected cells)

| cells | verdict | rule | cause |
|---|---|---|---|
| 1690 | unsupported | R05-unsupported | not_implemented: error: loc: <path> not yet implemented: lastprivate clause in constructs other than simd<path> |
| 1257 | compiler_bug | R10b-own-link-or-hang | link_undefined_symbol: ld.lld: error: undefined symbol: flang_rt_verbose_abort(char const*, ...) |
| 597 | unsupported | R05-unsupported | not_implemented: loc: error: not yet implemented: Unhandled clause order in omp.wsloop operation |
| 364 | unsupported | R05-unsupported | not_implemented: error: loc: <path> not yet implemented: Firstprivate is currently unsupported defaultmap behaviour |
| 314 | unsupported | R05-unsupported | not_implemented: loc: error: not yet implemented: Unhandled clause order in omp.distribute operation |
| 196 | unsupported | R05-unsupported | not_implemented: error: loc: <path> not yet implemented: lastprivate(conditional:) on simd construct |
| 14 | unsupported | R05-unsupported | not_implemented: error: loc: <path> not yet implemented: lowering symbol to HLFIR |
| 14 | unsupported | R05-unsupported | not_implemented: error: loc: <path> not yet implemented: lastprivate(conditional:) on do simd composite construct |
| 3 | our_bug | R03-illegal | not_implemented: error: loc: <path> not yet implemented: lastprivate clause in constructs other than simd<path> |
| 2 | our_bug | R03-illegal | not_implemented: error: loc: <path> not yet implemented: Firstprivate is currently unsupported defaultmap behaviour |
| 1 | our_bug | R03-illegal | link_undefined_symbol: ld.lld: error: undefined symbol: flang_rt_verbose_abort(char const*, ...) |
| 1 | our_bug | R03-illegal | not_implemented: loc: error: not yet implemented: Unhandled clause order in omp.distribute operation |

#### cce19 (9683 rejected cells)

| cells | verdict | rule | cause |
|---|---|---|---|
| 7100 | unsupported | R11c-later-form-unclaimed | later form declare-target-enter |
| 937 | unsupported | R11c-later-form-unclaimed | later form target-thread-limit |
| 503 | unsupported | R11c-later-form-unclaimed | later form defaultmap-all |
| 190 | unsupported | R05-unsupported | not_implemented: Unsupported OpenMP construct Calls -- $udr_i_NFUZZ_DMOD |
| 166 | unsupported | R05-unsupported | not_implemented: Unsupported OpenMP construct Fortran character -- xc |
| 157 | unsupported | R11c-later-form-unclaimed | later form num-teams-lower-bound |
| 143 | unsupported | R11c-later-form-unclaimed | later form distribute-order |
| 124 | unsupported | R05-unsupported | not_implemented: Unsupported OpenMP construct Calls -- __GET_DYNAMIC_TYPE |
| 98 | needs_human | R12b-compile-undecided | diagnostic: ftn-N ftn: ERROR The stride specified for array "X" must not be greater than N. Subarray references in the MAP clause must be to contiguou |
| 97 | compiler_bug | R11-compile-rejection | diagnostic: ftn-N ftn: ERROR The stride specified for array "X" must not be greater than N. Subarray references in the MAP clause must be to contiguou |
| 57 | unsupported | R05-unsupported | not_implemented: Unsupported OpenMP construct Calls -- $udr_c_NFUZZ_DMOD |
| 19 | unsupported | R05-unsupported | not_implemented: Unsupported OpenMP construct Fortran character -- xs |

#### cce20 (8330 rejected cells)

| cells | verdict | rule | cause |
|---|---|---|---|
| 4502 | compiler_bug | R11-compile-rejection | diagnostic: ftn-N ftn: ERROR Unexpected syntax while parsing the DIRECTIVE statement : "INDIRECT, LINK, TO or DEVICE_TYPE" was expected but found "X". |
| 2597 | needs_human | R12b-compile-undecided | diagnostic: ftn-N ftn: ERROR Unexpected syntax while parsing the DIRECTIVE statement : "INDIRECT, LINK, TO or DEVICE_TYPE" was expected but found "X". |
| 299 | unsupported | R05-unsupported | not_implemented: Unsupported OpenMP construct Calls -- $udr_i_NFUZZ_DMOD |
| 200 | unsupported | R11c-later-form-unclaimed | later form num-teams-lower-bound |
| 187 | unsupported | R11c-later-form-unclaimed | later form distribute-order |
| 169 | unsupported | R05-unsupported | not_implemented: Unsupported OpenMP construct Calls -- __GET_DYNAMIC_TYPE |
| 116 | needs_human | R12b-compile-undecided | diagnostic: ftn-N ftn: ERROR The stride specified for array "X" must not be greater than N. Subarray references in the MAP clause must be to contiguou |
| 115 | compiler_bug | R11-compile-rejection | diagnostic: ftn-N ftn: ERROR The stride specified for array "X" must not be greater than N. Subarray references in the MAP clause must be to contiguou |
| 79 | unsupported | R05-unsupported | not_implemented: Unsupported OpenMP construct Calls -- $udr_c_NFUZZ_DMOD |
| 15 | compiler_bug | R11-compile-rejection | diagnostic: ftn-N ftn: ERROR Variable "X" must have its data scope explicitly declared because DEFAULT(NONE) was specified. |
| 11 | unsupported | R05-unsupported | not_implemented: Unsupported OpenMP construct Deep privatization -- dr |
| 9 | our_bug | R03-illegal | diagnostic: ftn-N ftn: ERROR Unexpected syntax while parsing the DIRECTIVE statement : "INDIRECT, LINK, TO or DEVICE_TYPE" was expected but found "X". |

#### cce21 (3510 rejected cells)

| cells | verdict | rule | cause |
|---|---|---|---|
| 697 | unsupported | R05-unsupported | not_implemented: Unsupported OpenMP construct Calls -- $udr_i_NFUZZ_DMOD |
| 681 | compiler_bug | R10b-own-link-or-hang | link_undefined_symbol: lld: error: undefined symbol: _cray$mt_taskwait |
| 477 | unsupported | R11c-later-form-unclaimed | later form num-teams-lower-bound |
| 409 | unsupported | R11c-later-form-unclaimed | later form distribute-order |
| 373 | unsupported | R05-unsupported | not_implemented: Unsupported OpenMP construct Calls -- __GET_DYNAMIC_TYPE |
| 316 | compiler_bug | R11-compile-rejection | diagnostic: ftn-N ftn: ERROR The stride specified for array "X" in the MAP clause must not be greater than N. |
| 246 | needs_human | R12b-compile-undecided | diagnostic: ftn-N ftn: ERROR The stride specified for array "X" in the MAP clause must not be greater than N. |
| 166 | unsupported | R05-unsupported | not_implemented: Unsupported OpenMP construct Calls -- $udr_c_NFUZZ_DMOD |
| 29 | unsupported | R05-unsupported | not_implemented: Unsupported OpenMP construct Deep privatization -- dr |
| 28 | compiler_bug | R11-compile-rejection | diagnostic: ftn-N ftn: ERROR Variable "X" must have its data scope explicitly declared because DEFAULT(NONE) was specified. |
| 27 | needs_human | R12b-compile-undecided | diagnostic: ftn-N ftn: ERROR Variable "X" must have its data scope explicitly declared because DEFAULT(NONE) was specified. |
| 18 | needs_human | R12b-compile-undecided | diagnostic: ftn-N ftn: ERROR Object "X" is specified on the FIRSTPRIVATE clause. It must have a shared scope in the enclosing region. |

### Agent decisions (needs_human)

| decision | verdict | cells | basis |
|---|---|---|---|
| D1-strided-target-update | compiler_bug | 460 | CCE rejects target update to(x(1:n:2)) ("The stride specified for array ... in the MAP clause must not be greater than 1"); every diagnostic points at a target update statement (checked on all cases). Legal: "A stride expression may not be specified unless otherwise stated" (5.2 §3.2.5 p.66) and the data-motion clauses state it: "The list items may include array sections with stride expressions" (|
| D2-default-none-loop-variable | compiler_bug | 2 | CCE's ftn-1510 names the iteration variable of the loop associated with the enclosing teams distribute default(none) construct (checked on all cases); it is predetermined private ("The loop iteration variable in any associated loop of a loop-associated construct is otherwise private", 5.2 §5.1.1 p.97), and default(none) concerns only variables without a predetermined attribute (5.2 §5.4.1 p.109). |
| D3-default-none-false-diagnostic | compiler_bug | 32 | CCE's ftn-1510 says DEFAULT(NONE) was specified for a statement of a procedure none of whose enclosing constructs has a default clause (checked on every case: the statement's enclosing directives up to its procedure; e.g. s1 seed 91 kp2, a target parallel / masked region with no default clause). default(none) restricts only the variables referenced in its own construct (5.2 §5.4.1 p.109): a false  |
| D4-defaultmap-none-mapped-variable | compiler_bug | 18 | CCE's ftn-1964 ("must have its data mapping attribute explicitly declared because default map(none) was specified") names a variable that the target construct with defaultmap(none: aggregate) lists in a map clause, or a statement with no defaultmap(none) construct around it (checked on every case); 5.2 §5.8.7 p.162 requires only that such variables be listed in a data-environment attribute clause. |
| D5-firstprivate-split-to-the-worksharing-leaf | compiler_bug | 27 | parallel do default(none) shared(...) firstprivate(i) nested in a teams distribute loop over i: firstprivate on the combined construct applies to the worksharing leaf and "the effect is as if the shared clause with the same list item is applied to the parallel construct" (5.2 §17.2 p.340), so i is shared in the parallel region and the worksharing-construct restriction on items private in the bindi |
| D6-cce-unhandled-reduction | compiler_bug | 63 | CCE's own runtime prints "Unhandled Reduction!!!" during the run and the result is wrong (or the run aborts): the compiler/runtime declares that it did not perform a reduction of the legal program. No expected value is needed for that statement; the expected value is from the model only (the elision does not apply to these programs), hence R22/R13c. |
| D7-cce-target-simd-lastprivate-conditional | compiler_bug | 11 | Wrong answer on CCE of a program with target simd lastprivate(conditional: x) and x in no map clause: the known finding fuzz/b2-209-cce19.f90 (CCE loses the implicit map(tofrom) of a conditional lastprivate item on a combined target construct, 5.2 §17.2 p.340; the probes data/evidence/dataenv_probe/lpcond_simd_*.f90 show lp unchanged on CCE 19/20/21 at gfx942 and gfx90a, and correct with an explicit map or wi |
| D8-crash-another-family-runs-it | compiler_bug | 148 | A deterministic crash or runtime abort (signal, memory access fault, heap corruption, an offload runtime error) of a legal program that passed the definedness check (the sequential program with -fcheck=all, twice, prints the model value), while a toolchain of the other compiler family runs the same program to the model's value on the device in the same memory mode. No expected value is needed to c |
| D9-cce20-declare-target-enter | compiler_bug | 2597 | CCE 20 rejects `!$omp declare target enter(...)` (ftn-1725 "INDIRECT, LINK, TO or DEVICE_TYPE was expected but found E"); every diagnostic points at the enter keyword of a declare target directive (checked on all 2,597 s1 cells, 2,062 programs: line and column against the regenerated bundle file). The enter clause is the 5.2 spelling of to on declare target ("The clause-name to may be used as a sy |

Left needs_human: R12b-compile-undecided 1, R13c-fuzz-noncompliant-weak 67, R22-expected-weak 1685, R22b-expected-disputed-late 29


### Spot checks

| verdict class | groups agree | groups disagree | sampled cases agree | sampled cases disagree |
|---|---|---|---|---|
| compiler_bug | 69 | 1 | 950 | 0 |
| environment | 1 | 0 | 1 | 0 |
| flaky | 1 | 0 | 1 | 0 |
| needs_human | 0 | 2 | 0 | 0 |
| our_bug | 6 | 0 | 6 | 0 |
| unsupported | 31 | 1 | 2282 | 0 |
| unsupported_everywhere | 0 | 2 | 0 | 1 |

Disagreements (each became a rule fix and a rerun):

- `unsupported_everywhere|cce21|rejected|R12-every-family-rejects|diagnostic: ftn-N ftn: ERROR Object "X" is specified on the FIRSTPRIVATE clause. It must have a shared scope in the encl`: s1 seed 1150: AFAR rejects the order clause, CCE firstprivate(i), on the same parallel do; not every family rejecting one construct. Fixed: R12/R12a do not apply to fuzz programs (R12b, decision D5); rerun
- `unsupported_everywhere|cce21|rejected|R12-every-family-rejects|diagnostic: ftn-1747 strided target update`: (batch, 204 cells affected) the other families rejected the program at other statements (AFAR: lastprivate not implemented); fixed: R12 needed the same statement (first fix), then no R12 for fuzz programs; rerun (now D1)
- `unsupported|cce20|rejected|R11c-later-form-unclaimed|form defaultmap-all`: (batch, 1 cells affected) s1 seed 8174: the message names order on target teams distribute; fixed: forms named by the message first, else the column; rerun
- `compiler_bug|cce21|rejected|R11-compile-rejection|finding cce21-linear-modifier-default-none.f90`: (batch, 2 cells affected) verdict right, instance wrong: the programs have no linear clause; fixed: a diagnostic is an instance only with the finding's key constructs (related otherwise); rerun
- `needs_human|cce21|wrong_answer|R22-expected-weak|(metamorphic conflict)`: (batch, 420 cells affected) the failing compiler's own stable wrong value on the rewrites made the metamorphic source a conflict; fixed: a family is no metamorphic witness against itself; rerun (R20 for most)
- `needs_human|*|wrong_answer|R99-default|(metamorphic dispute)`: (batch, 222 cells affected) verdict right (needs_human), rule unnamed; added R22b; rerun

### Instances of known findings

Bug verdicts whose failure signature is an indexed finding's (offload/engine/confirm/findings.py).

| finding | toolchain | cells |
|---|---|---|
| s1-6760-cce20.f90 | cce20 | 4502 |
| afar-udr-derived-type-link.f90 | afar | 1257 |
| cce21-in-reduction-taskwait-link.f90 | cce21 | 681 |
| cce19-target-parallel-single-ice.f90 | cce19 | 645 |
| s1-6888-cce21.f90 | cce21 | 316 |
| 1391-cce20.f90 | cce20 | 194 |
| s1-6888-cce21.f90 | cce20 | 115 |
| s1-6888-cce21.f90 | cce19 | 97 |
| b3-9-afar.f90 | afar | 29 |
| s1-9443-afar.f90 | afar | 23 |
| b3-250-cce20.f90 | cce20 | 14 |
| s1-2370-cce21.f90 | cce21 | 12 |
| fortran-loop-bind-thread-in-parallel.f90 | cce21 | 10 |
| b3-250-cce20.f90 | cce19 | 9 |
| 1540-afar.f90 | afar | 8 |
| multithread-allocatable-section-maps.f90 | cce21 | 7 |
| s1-2370-cce21.f90 | cce20 | 7 |
| fortran-loop-bind-thread-in-parallel.f90 | afar | 5 |
| s1-2592-cce21.f90 | cce21 | 5 |
| defaultmap-none-loop-variable.f90 | cce19 | 4 |
| s1-91-cce21.f90 | cce20 | 4 |
| s1-91-cce21.f90 | cce21 | 4 |
| 958-cce20.f90 | cce20 | 3 |
| b3-250-cce20.f90 | cce21 | 3 |
| b3-9-cce21.f90 | cce21 | 3 |
| fortran-loop-bind-thread-in-parallel.f90 | cce20 | 3 |
| s1-2370-cce21.f90 | cce19 | 3 |
| s1-3463-cce21.f90 | cce20 | 3 |
| s1-3463-cce21.f90 | cce21 | 3 |
| b2-85-cce20.f90 | cce21 | 2 |
| b3-188-cce19.f90 | cce19 | 2 |
| b3-9-cce21.f90 | afar | 2 |
| defaultmap-none-loop-variable.f90 | cce21 | 2 |
| fortran-loop-bind-thread-in-parallel.f90 | cce19 | 2 |
| multithread-allocatable-section-maps.f90 | cce19 | 2 |
| s1-2592-cce21.f90 | cce20 | 2 |
| s1-3463-cce21.f90 | cce19 | 2 |
| 2334-cce19.f90 | cce19 | 1 |
| multithread-allocatable-section-maps.f90 | afar | 1 |
| multithread-allocatable-section-maps.f90 | cce20 | 1 |

### Feature pairs (base language x OpenMP)

Unified mode (s1). A pair is judged with at least 30 programs with both features and 30 with each feature without the other, among the programs the toolchain compiled; it is listed when its programs fail at least twice as often as either side alone and a one-sided Fisher test against the programs with exactly one of the two gives p < 0.01. "alone" columns: the same toolchain in the single-group campaigns (b1-b5 for the base feature, b0 and c1 for the OpenMP feature); "interaction yes" means neither feature fails that often there either. Features that always occur together are one row (joined with /).


#### run-time failure (wrong code, crash, run error)

#### afar: run-time failure (wrong code, crash, run error) (1090 of 6439 programs it did not reject, 16.9%); 13 pairs, 12 not explained by a feature alone
| base feature | OpenMP feature | both: fail/programs | base without the OpenMP feature | OpenMP feature without the base feature | base alone (b1-b5) | OpenMP alone (b0, c1) | p | interaction |
|---|---|---|---|---|---|---|---|---|
| base:dt:map:mod:mapper(mmap) / base:dc:map_with_named_mapper | dir:distribute | 49/110 (44.5%) | 54/244 | 389/1773 | 4/19 | 77/614 | 2.8e-07 | yes |
| base:red:int8:clause | dir:teams | 24/52 (46.2%) | 15/76 | 467/2210 | 1/7 | 84/766 | 6.0e-05 | yes |
| base:out:int8 | scalar:firstprivate | 20/41 (48.8%) | 70/334 | 100/512 | 0/19 | 32/370 | 6.2e-05 | yes |
| base:al:dummy:value | map:mod:close | 24/48 (50.0%) | 31/143 | 365/1479 | 3/10 | 65/523 | 1.5e-04 | no (explained alone) |
| base:decl:allocatable_real8 | dir:teams distribute | 26/74 (35.1%) | 383/2183 | 25/165 | 4/79 | 8/82 | 2.5e-04 | yes |
| base:al:allocatable_output_component | kernel:phase | 15/34 (44.1%) | 52/271 | 144/868 | 0/0 | 18/292 | 3.1e-04 | yes |
| base:al:structure_dummy | defaultmap:to:scalar | 21/47 (44.7%) | 457/2088 | 16/77 | 9/51 | 0/22 | 4.8e-04 | yes |
| base:red:int1:clause | clause:default:shared | 16/30 (53.3%) | 23/117 | 169/688 | 1/5 | 34/250 | 6.2e-04 | yes |
| base:out:char | dir:simd | 15/34 (44.1%) | 22/130 | 367/1911 | 1/12 | 39/603 | 8.3e-04 | yes |
| base:al:dummy:optional | clause:collapse | 18/42 (42.9%) | 30/158 | 226/1081 | 0/15 | 38/390 | 1.2e-03 | yes |
| base:dt:scalar_component | red:atomic:max | 17/49 (34.7%) | 652/3832 | 5/30 | 16/149 | 3/28 | 2.3e-03 | yes |
| base:dc:call:gs1 | dir:target simd | 13/30 (43.3%) | 89/414 | 55/329 | 3/32 | 6/136 | 3.0e-03 | yes |

#### cce19: run-time failure (wrong code, crash, run error) (210 of 2161 programs it did not reject, 9.7%); 33 pairs, 21 not explained by a feature alone
| base feature | OpenMP feature | both: fail/programs | base without the OpenMP feature | OpenMP feature without the base feature | base alone (b1-b5) | OpenMP alone (b0, c1) | p | interaction |
|---|---|---|---|---|---|---|---|---|
| base:al:dummy:intent_inout | dir:taskgroup / clause:in_reduction / kernel:inred | 50/93 (53.8%) | 65/657 | 9/172 | 11/64 | 7/189 | 1.4e-23 | yes |
| base:al:kernel_in_internal_procedure | dir:taskgroup / clause:in_reduction / kernel:inred | 50/94 (53.2%) | 76/734 | 9/171 | 11/66 | 7/189 | 7.5e-23 | yes |
| base:al:structure_dummy | dir:taskgroup / clause:in_reduction / kernel:inred | 45/84 (53.6%) | 63/628 | 14/181 | 7/47 | 7/189 | 1.1e-20 | yes |
| base:al:dummy:assumed_shape | dir:taskgroup / clause:in_reduction / kernel:inred | 41/75 (54.7%) | 54/542 | 18/190 | 10/58 | 7/189 | 6.0e-19 | yes |
| base:al:dummy:intent_in | dir:taskgroup / clause:in_reduction / kernel:inred | 36/66 (54.5%) | 42/429 | 23/199 | 10/50 | 7/189 | 3.7e-16 | yes |
| base:mt:module_file | kernel:guard | 92/441 (20.9%) | 102/1449 | 5/50 | 4/146 | 79/374 | 6.8e-15 | no (explained alone) |
| base:al:dummy:explicit | clause:in_reduction / dir:taskgroup / kernel:inred | 30/55 (54.5%) | 22/340 | 29/210 | 7/36 | 7/189 | 8.6e-15 | yes |
| base:al:dummy:intent_inout / base:al:kernel_in_internal_procedure | red:in_reduction:+ | 30/57 (52.6%) | 85/693 | 5/91 | 11/64 | 5/102 | 8.6e-13 | yes |
| base:al:dummy:intent_inout | red:in_reduction:* | 26/44 (59.1%) | 89/706 | 4/87 | 11/64 | 2/95 | 9.0e-13 | yes |
| base:al:dummy:assumed_shape | red:in_reduction:+ | 27/48 (56.2%) | 68/569 | 8/100 | 10/58 | 5/102 | 1.4e-12 | yes |
| base:al:structure_dummy | red:in_reduction:* | 24/39 (61.5%) | 84/673 | 6/92 | 7/47 | 2/95 | 1.9e-12 | yes |
| base:al:kernel_in_internal_procedure | red:in_reduction:* | 26/45 (57.8%) | 100/783 | 4/86 | 11/66 | 2/95 | 2.3e-12 | yes |

#### cce20: run-time failure (wrong code, crash, run error) (337 of 3307 programs it did not reject, 10.2%); 51 pairs, 34 not explained by a feature alone
| base feature | OpenMP feature | both: fail/programs | base without the OpenMP feature | OpenMP feature without the base feature | base alone (b1-b5) | OpenMP alone (b0, c1) | p | interaction |
|---|---|---|---|---|---|---|---|---|
| base:al:dummy:intent_inout | dir:taskgroup / clause:in_reduction / kernel:inred | 86/157 (54.8%) | 87/1010 | 16/275 | 17/98 | 15/328 | 2.8e-42 | yes |
| base:al:kernel_in_internal_procedure | dir:taskgroup / clause:in_reduction / kernel:inred | 87/161 (54.0%) | 100/1116 | 15/271 | 18/101 | 15/328 | 9.2e-42 | yes |
| base:al:structure_dummy | dir:taskgroup / clause:in_reduction / kernel:inred | 80/149 (53.7%) | 95/970 | 22/283 | 13/68 | 15/328 | 2.2e-35 | yes |
| base:al:dummy:assumed_shape | dir:taskgroup / clause:in_reduction / kernel:inred | 70/131 (53.4%) | 72/842 | 32/301 | 16/88 | 15/328 | 9.9e-32 | yes |
| base:al:dummy:intent_in | dir:taskgroup / clause:in_reduction / kernel:inred | 62/117 (53.0%) | 68/686 | 40/315 | 14/73 | 15/328 | 7.6e-25 | yes |
| base:al:dummy:intent_inout | red:in_reduction:* | 48/80 (60.0%) | 125/1087 | 8/142 | 17/98 | 10/176 | 9.1e-24 | yes |
| base:al:kernel_in_internal_procedure | red:in_reduction:* | 48/82 (58.5%) | 139/1195 | 8/140 | 18/101 | 10/176 | 5.2e-23 | yes |
| base:al:structure_dummy | red:in_reduction:* | 45/76 (59.2%) | 130/1043 | 11/146 | 13/68 | 10/176 | 1.0e-20 | yes |
| base:al:kernel_in_internal_procedure | red:in_reduction:+ | 48/90 (53.3%) | 139/1187 | 8/144 | 18/101 | 5/170 | 1.2e-20 | yes |
| base:al:dummy:intent_inout | red:in_reduction:+ | 47/88 (53.4%) | 126/1079 | 9/146 | 17/98 | 5/170 | 3.4e-20 | yes |
| base:al:dummy:explicit | dir:taskgroup / clause:in_reduction / kernel:inred | 49/95 (51.6%) | 41/540 | 53/337 | 11/56 | 15/328 | 1.1e-19 | yes |
| base:al:dummy:assumed_shape | red:in_reduction:+ | 41/75 (54.7%) | 101/898 | 15/159 | 16/88 | 5/170 | 2.6e-18 | yes |

#### cce21: run-time failure (wrong code, crash, run error) (1054 of 7109 programs it did not reject, 14.8%); 19 pairs, 14 not explained by a feature alone
| base feature | OpenMP feature | both: fail/programs | base without the OpenMP feature | OpenMP feature without the base feature | base alone (b1-b5) | OpenMP alone (b0, c1) | p | interaction |
|---|---|---|---|---|---|---|---|---|
| base:al:dummy:value | red:clause:+ | 18/34 (52.9%) | 42/195 | 97/735 | 5/9 | 14/233 | 5.5e-07 | yes |
| base:view:logical | clause:private:loop_variable | 30/101 (29.7%) | 356/2537 | 18/124 | 4/67 | 17/66 | 5.7e-05 | no (explained alone) |
| base:dt:component:nested:real8 | defaultmap:tofrom:allocatable | 25/80 (31.2%) | 354/2517 | 21/135 | 3/91 | 16/88 | 9.9e-05 | no (explained alone) |
| base:view:int1 | defaultmap:to:allocatable | 16/44 (36.4%) | 370/2701 | 7/44 | 4/78 | 1/16 | 1.7e-04 | yes |
| base:dt:out:dr%nd | clause:safelen | 21/60 (35.0%) | 57/330 | 165/1091 | 1/18 | 23/393 | 2.7e-04 | yes |
| base:red:logical:.or. | dir:distribute | 12/31 (38.7%) | 5/31 | 345/2524 | 0/4 | 61/817 | 5.4e-04 | yes |
| base:decl:allocatable_complex8 | dir:target parallel loop | 13/35 (37.1%) | 252/1799 | 17/116 | 3/75 | 8/67 | 6.8e-04 | yes |
| base:decl:allocatable_logical | dir:target parallel loop | 14/39 (35.9%) | 249/1757 | 16/112 | 4/63 | 8/67 | 7.1e-04 | yes |
| base:dc:declare_mapper:named / base:dc:declare_target_to | dir:teams distribute parallel do | 13/35 (37.1%) | 380/2538 | 7/49 | 4/81 | 3/26 | 1.2e-03 | yes |
| base:decl:explicit_char | red:atomic:max | 15/44 (34.1%) | 380/2572 | 9/59 | 10/98 | 4/33 | 1.3e-03 | yes |
| base:dc:static_init | red:atomic:iand | 14/42 (33.3%) | 505/3477 | 5/36 | 12/129 | 5/29 | 1.9e-03 | no (explained alone) |
| base:mt:module_chain | red:atomic:iand | 15/46 (32.6%) | 619/4200 | 4/32 | 6/152 | 5/29 | 1.9e-03 | no (explained alone) |

#### ICE

#### afar: ICE (75 of 6439 programs it did not reject, 1.2%); 175 pairs, 97 not explained by a feature alone
| base feature | OpenMP feature | both: fail/programs | base without the OpenMP feature | OpenMP feature without the base feature | base alone (b1-b5) | OpenMP alone (b0, c1) | p | interaction |
|---|---|---|---|---|---|---|---|---|
| base:al:dummy:assumed_shape | clause:nontemporal | 66/135 (48.9%) | 1/1768 | 0/238 | 3/67 | 0/138 | 4.2e-86 | yes |
| base:al:kernel_in_internal_procedure | clause:nontemporal | 66/157 (42.0%) | 2/2321 | 0/216 | 3/81 | 0/138 | 1.6e-85 | yes |
| base:al:dummy:intent_inout | clause:nontemporal | 65/152 (42.8%) | 1/2136 | 1/221 | 3/78 | 0/138 | 3.2e-83 | yes |
| base:al:structure_dummy | clause:nontemporal | 59/136 (43.4%) | 2/1999 | 7/237 | 2/51 | 0/138 | 1.4e-69 | yes |
| base:al:dummy:intent_in | clause:nontemporal | 52/116 (44.8%) | 1/1414 | 14/257 | 2/59 | 0/138 | 8.7e-54 | yes |
| base:al:dummy:assumed_shape | kernel:loop | 67/1590 (4.2%) | 0/313 | 8/3642 | 3/67 | 4/1721 | 2.1e-28 | no (explained alone) |
| base:al:dummy:assumed_shape | dir:simd | 53/624 (8.5%) | 14/1279 | 1/1321 | 3/67 | 0/603 | 6.0e-26 | no (explained alone) |
| base:al:dummy:intent_inout | dir:simd | 53/738 (7.2%) | 13/1550 | 1/1207 | 3/78 | 0/603 | 1.6e-24 | no (explained alone) |
| base:al:dummy:assumed_shape | dir:target | 60/1504 (4.0%) | 7/399 | 4/3519 | 3/67 | 1/1607 | 1.4e-23 | no (explained alone) |
| base:al:kernel_in_internal_procedure | kernel:loop | 68/2048 (3.3%) | 0/430 | 7/3184 | 3/81 | 4/1721 | 4.5e-23 | no (explained alone) |
| base:al:kernel_in_internal_procedure | dir:simd | 53/783 (6.8%) | 15/1695 | 1/1162 | 3/81 | 0/603 | 5.6e-23 | no (explained alone) |
| base:al:dummy:intent_inout | kernel:loop | 66/1899 (3.5%) | 0/389 | 9/3333 | 3/78 | 4/1721 | 1.3e-22 | no (explained alone) |

#### cce19: ICE (680 of 2161 programs it did not reject, 31.5%); 0 pairs, 0 not explained by a feature alone

#### cce20: ICE (1036 of 3307 programs it did not reject, 31.3%); 0 pairs, 0 not explained by a feature alone

#### cce21: ICE (2403 of 7109 programs it did not reject, 33.8%); 0 pairs, 0 not explained by a feature alone

### Copy mode (s1x0 against the same seeds of s1)

A cell fails when its class is not agree; compile rejections are the same in both modes and are compared like any class.

| toolchain | seeds in both modes | fail only in copy mode | their verdicts (copy cell) | fail only in unified mode | their verdicts (unified cell) |
|---|---|---|---|---|---|
| afar | 2479 | 19 | needs_human 14, compiler_bug 5 | 43 | needs_human 30, compiler_bug 12, flaky 1 |
| cce19 | 2479 | 11 | needs_human 6, compiler_bug 5 | 0 |  |
| cce20 | 2479 | 7 | compiler_bug 4, needs_human 3 | 0 |  |
| cce21 | 2479 | 11 | compiler_bug 6, needs_human 5 | 0 |  |

#### Class transitions (unified -> copy) of the cells that differ

| toolchain | unified | copy | cells |
|---|---|---|---|
| afar | crash | agree | 39 |
| afar | agree | crash | 17 |
| afar | crash | wrong_code | 6 |
| afar | wrong_code | agree | 4 |
| afar | wrong_code | crash | 3 |
| afar | agree | wrong_code | 2 |
| cce19 | agree | crash | 11 |
| cce19 | wrong_code | crash | 1 |
| cce20 | agree | crash | 7 |
| cce20 | compile_reject | harness_error | 1 |
| cce21 | agree | run_error | 8 |
| cce21 | agree | wrong_code | 2 |
| cce21 | agree | timeout | 1 |
| cce21 | crash | run_error | 1 |
<!-- t28:end -->
