# The 16 AFAR run failures of the fuzz-5 oop sample

Question (fortran-oop report, concern 3): the base group `oop` of generator fuzz-5 (module `fuzz_omod`,
wrappers oo1..oo5: dispatch through `CLASS(ob_t)`, an override that calls the parent's binding through the
parent component, `SELECT TYPE`, `CLASS(*)`) produced 16 gate-confirmed AFAR failures (12 crashes, 4 wrong
answers) in the two sample runs `oop5-0` and `oop5-1` (results/fuzz/, seeds 1-300, base groups derived + oop,
HSA_XNACK=1), while every hand-written family program passes on AFAR. Is there an AFAR defect in dispatch,
`SELECT TYPE` or `CLASS(*)`?

**Answer: no.** None of the 16 depends on the oop group. They fall into three clusters, each of which is an AFAR
defect that is already filed (data/findings/fuzz/, data/findings/afar-xnack1-atomic-min-nested-parallel.f90).
No new finding is written. The generator is not at fault (the host runs agree with the model for all 16).

## Method

AFAR 24.3.0 (amdflang, `-fopenmp --offload-arch=gfx942 -O2`), MI300A, single-node pdebug jobs
(`compile-test-afar-oop-N`), HSA_XNACK=1 and 0, `OMP_TARGET_OFFLOAD=mandatory`; the reference is the host run of
the same binary (`OMP_TARGET_OFFLOAD=disabled`), which equals the generator's model for all 16 seeds.

1. The 16 programs regenerated (`tools/campaigns/fuzz.py gen --gen-version fuzz-5 --base-features derived oop`) and rerun
   twice in each mode.
2. The same 16 with the module `fuzz_omod` replaced by plain arithmetic functions of the same values (oo1..oo5
   as expressions, no types, no bindings): the failure is the same in all 16 (seed 165 aborts at HSA_XNACK=1 in
   this form and gives a wrong value in the original; both are failures, see cluster B).
3. Delta debugging (offload.engine.fuzz_min's candidate generators with an AFAR-only oracle: the failure must
   persist twice, the host must run, and for a wrong answer the one-thread and default-thread host runs must
   agree) of the 16, then by hand to the small programs in data/reports/fuzz5-oop-afar/. Run on the original
   programs with the module (seeds 157, 183, 231, 87) the reduction deletes every oop call and use.
4. One-change controls for every reduced program and the hand-written minimal programs, in both modes, on two
   nodes (node-1015 and node-1030: 123 results, identical).

Evidence that the oop group is not involved:

- 5 of the 16 never call an oop wrapper (166, 213, 231, 275, 294); the sample's failure rate is 11/227 (4.8%) for
  programs that call a wrapper and 5/73 (6.8%) for those that do not.
- The module replaced by arithmetic (step 2) gives the same outcome in 15 of 16 and a failure in the 16th.
- Dispatch through `CLASS(ob_t)` of a device-local object from `target teams distribute parallel do`, and the
  override calling the parent binding, are correct on AFAR in both modes, in the form the wrappers use
  (OOP_dispatch.f90, OOP_override_parent.f90; also `o%g(x)`, a mapped object, a type without default
  initialization, and a single-thread `target`).
- AFAR's 77 compile rejections in the sample (46 "lastprivate clause in construct", 13 + 5 "Unhandled clause
  order", 7 "Firstprivate ... defaultmap", 6 "lastprivate(conditional:)") name generic clauses, none the oop
  constructs.

## The 16 seeds

"expected" is the generator's model (= the host run). Cluster: A = `close` + `present` (HSA_XNACK=1 only), B =
`parallel firstprivate(i)` nested in a distribute loop, C = an atomic update with a right-hand side that depends
on the distribute index, in a parallel loop nested in it, with an array written (HSA_XNACK=1 only).

| run:seed | expected | cluster | campaign (x1) | rerun x1 / x0 of the full program | what is left after the reduction |
|---|---|---|---|---|---|
| oop5-0:33 | 954320942 | A | crash | abort 'present' / correct | `enter data` + empty `target map(close, present, tofrom: o3)` |
| oop5-0:35 | 149567192 | A | crash | abort 'present' / correct | `enter data` + empty `target map(close, present, from: o3)` |
| oop5-0:89 | 1176255082 | A | crash | abort 'present' / correct | `target data` + empty `target map(close, present, to: ic)` |
| oop5-0:121 | 378858110 | A | crash | abort 'present' / memory fault | A as above; behind it B (x0 fault, x1 writes lost) |
| oop5-1:166 | 1113807626 | A | crash | abort 'present' / correct | `enter data` + empty `target map(close, present, tofrom: dr)` |
| oop5-1:275 | 1634892729 | A | crash | abort 'present' / correct | the same on a derived-type scalar |
| oop5-1:288 | 925665451 | A | crash | abort 'present' / correct | `target data` + empty `target map(close, present, to: ib)` |
| oop5-1:294 | 1351038988 | A | crash | abort 'present' / wrong (1882109728) | A as above; at x0 a critical (cluster E in the notes) |
| oop5-0:87 | 1292090529 | B | wrong | wrong (1594718770) / wrong | `teams reduction(max)` + `parallel firstprivate(i)` + `do reduction(max)` |
| oop5-0:94 | 768826377 | B | wrong | wrong (1397669028) / wrong | `parallel firstprivate(i)` + `do` writing an allocatable array |
| oop5-1:157 | 1968601138 | B | crash | memory fault / wrong (1314527307) | `target teams map(close, to: o1)`, `parallel firstprivate(i)` |
| oop5-1:165 | 1706539464 | B | crash | wrong (1681794291) / memory fault | `target teams distribute`, `parallel firstprivate(i)`, allocatable written |
| oop5-1:167 | 452479802 | B | wrong | wrong (1214426127) / wrong (272935284) | the reduction form, as 87 |
| oop5-1:213 | 836173497 | B | wrong | wrong (2082155468) / memory fault | the reduction form under a `target data` region |
| oop5-1:183 | 1777406246 | C | crash | memory fault / correct | `atomic` min in `parallel do` in `target teams distribute`, allocatable written |
| oop5-1:231 | 981517140 | C | crash | memory fault / correct | atomic in `parallel`/`do` in `target`/`teams`/`distribute`, allocatable written |

Notes on the table. Seed 165 crashed in the campaign and gave a wrong value in two reruns at x1 (the outcome of
cluster B differs with the allocation). Seed 94 aborted once at exit at x1 after printing its (wrong) result and
not in five further runs: a flaky exit-time abort, not reduced. A ddmin step may empty a derived type, which makes
an object zero-sized; the A reductions of 275 did so, so cluster A's programs use the hand-written forms (the
derived-type form A_derived.f90 has components).

## Cluster A: `map(close, present)` after `target enter data` / inside `target data`, HSA_XNACK=1

- Defect: AFAR's runtime reports the item absent: `omptarget error: Call to getTargetPointer returned null pointer
  ('present' map type modifier)`, abort. HSA_XNACK=0 is correct. It does not depend on the item (array,
  allocatable, derived-type scalar) or on the data construct (enter data, target data); `close` alone and
  `present` alone are correct.
- Filed as: fuzz/158-afar.f90, fuzz/1131-afar.f90, fuzz/s1-9443-afar.f90 (the family also covers the oop5 rows).
- Reproducer: A_close_present.f90 (+ A_derived.f90, A_alloc.f90, A_targetdata.f90); controls A_ctl_present.f90
  (no `close`), A_ctl_close.f90 (no `present`), A_derived_ctl.f90. Expected `r1= 2` (`r1= 4` for A_derived).
- Legality: `present` of an item that an enclosing `target enter data` / `target data` mapped is satisfied
  (OpenMP 5.2 §5.8.3 p.152; `close` is a hint, as the filed findings state). offload.engine.rules accept; CCE 19, 20,
  21.0.3 and 21.0.4 compile all of them (a second front end that is not AFAR's).

## Cluster B: `parallel firstprivate(i)` nested in the distribute loop of a teams region

- Defect: the writes of the worksharing loop inside the parallel region are lost (r1 = 9 instead of 224: one
  element of 32) or give a wrong value at HSA_XNACK=1, and at HSA_XNACK=0 an explicit-shape array is written
  with a GPU memory fault (an allocatable array with an explicit map: lost writes in both modes; implicitly mapped,
  as in seeds 121 and 165, it faults at x0). The reduction forms (87, 167, 213)
  are the same defect: the same program without `firstprivate(i)` is correct in every case, so the `teams` and
  `do` reductions are not what fails.
- Filed as: fuzz/650-afar.f90 (also 87-afar, b3-94-afar, b1-268-afar, b2-52-afar); the memory-fault form at
  HSA_XNACK=0 is not described there (650's header and cells say "wrong").
- Reproducer: B_fp_combined.f90 (`target teams distribute`), B_fp_split.f90 (separate directives), B_fp_alloc.f90,
  B2_fp_reduction.f90; controls B_ctl_combined, B_ctl_split, B_ctl_alloc, B2_ctl_reduction (the
  `firstprivate(i)` clause removed: 224 / 224 / 8 in both modes). Expected `r1= 224` (`r1= 8`).
- Legality: a firstprivate clause on a parallel construct nested in a distribute loop (OpenMP 5.2 §5.4.4,
  §10.1, §11.5.1, §11.6); `i` is a private distribute iteration variable and is listed legitimately. rules accept;
  CCE compiles all.

## Cluster C: an atomic with an index-dependent right-hand side in a nested parallel loop, HSA_XNACK=1

- Defect: memory access fault ("Write access to a read-only page") at HSA_XNACK=1; HSA_XNACK=0 is correct.
- Filed as: afar-xnack1-atomic-min-nested-parallel.f90 (from fuzz/b1-183-afar.f90 and b2-183-afar.f90), and
  fuzz/b1-231-afar.f90 (and 916, b2-213 with a reduction).
- Reproducer: C_alloc_min.f90 (the filed shape with separate directives), C_int_modi_alloc.f90 (integer add),
  C_dp_modi_fixed.f90 (double precision add, explicit-shape array); controls C_fixed_min.f90, C_int_const_alloc.f90,
  C_dp_const_fixed.f90.
- Observation that goes beyond the filed header, from the 18-program matrix (type integer/double precision, right-hand
  side `1` / `mod(i, 97)` / `merge(3, 1, mod(ia(i), 5) == 0)`, array none/explicit/allocatable): nothing faults
  without a written array or with the constant right-hand side; with both, 7 of 8 combinations fault (all but
  integer + `mod(i, 97)` + explicit-shape). The header's statements that an atomic add is correct and an
  explicit-shape array is correct hold for a constant right-hand side in the combined form only: `r = r + mod(i, n)`
  in the filed program faults too (allocatable; the explicit-shape form of it is correct), and an explicit-shape
  array faults in the separate-directive form. The finding itself stands; its "Needed" line is narrower than the
  trigger.
- Legality: atomic update (OpenMP 5.2 §15.8.4), the written array and the scalar are disjoint across iterations.
  rules accept; CCE compiles C_alloc_min, C_int_modi_alloc and C_dp_modi_fixed.

## Notes: the cluster E critical (seed 294 at x0), the oop negatives

- Seed 294 at HSA_XNACK=0 (and 1 once `close, present` is out of the way) gives 1882109728 instead of 1351038988:
  an unnamed `critical` around `r = iand(r, ...)` in a `do` of `target parallel` does not exclude other threads.
  Reproducer E_critical.f90 (expected 256, observed 0 in both modes), control E_ctl_atomic.f90. Filed as
  fuzz/1936-afar.f90. Legality: rules only; CCE 19/20/21 stop with an internal error on `critical`
  (MT_CONTEXT_CRITICAL_SECTION) and NVHPC does not support it in a GPU region: no second front end.
- OOP_dispatch.f90 and OOP_override_parent.f90 are the oop negatives. They have no second front end (CCE cannot link device
  dispatch: cce-polymorphic-dispatch-device-link.f90; NVHPC rejects type-bound calls on the device).

## Files (data/reports/fuzz5-oop-afar/)

Each has the build, run, expected value, observed values in both modes, the control and the legality in its header.

- A: A_alloc.f90, A_close_present.f90, A_ctl_close.f90, A_ctl_present.f90, A_derived.f90, A_derived_ctl.f90, A_targetdata.f90
- B: B2_ctl_reduction.f90, B2_fp_reduction.f90, B_ctl_alloc.f90, B_ctl_combined.f90, B_ctl_split.f90, B_fp_alloc.f90, B_fp_combined.f90, B_fp_split.f90
- C: C_alloc_min.f90, C_dp_const_fixed.f90, C_dp_modi_fixed.f90, C_fixed_min.f90, C_int_const_alloc.f90, C_int_modi_alloc.f90
- E: E_critical.f90, E_ctl_atomic.f90
- OOP: OOP_dispatch.f90, OOP_override_parent.f90

## Limits

- No new finding, so no gate was run on these reproducers; their results are two nodes in the stated
  environments (both modes). The filed findings keep their own gate evidence.
- The delta debugging used AFAR's own host run as the reference; that is not a legality witness. Legality of the
  final programs is the rules witness plus the CCE compile (a front-end check only).
- Not reduced: the flaky exit abort of seed 94 (once in six runs).
