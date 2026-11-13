# Minimized fuzz findings (campaign `c1`)

Each file is a program of the fuzz campaign `c1` (generator `fuzz-1`,
seeds 1-2400; data/reports/fuzz-c1.md) minimized by `offload.engine.fuzz_min`
while the failure persisted and the program stayed legal (offload.engine.rules,
gfortran -std=f2008 -fsyntax-only, AFAR flang's frontend; each
header now carries the two-witness line of a rerun of offload.engine.prerun.check,
and an AFAR finding does not count AFAR's own front end; gfortran and gcc are
no legality witnesses). The generated programs print
`ran_on_host=` in their RESULT line as a constant 0, or as `max(hfN, 0)` of a
flag nothing sets (e.g. `650-afar.f90`, `b3-54-afar.f90`): it is not a measured
device flag; the vendor packets drop the field. The header says
the failing toolchain, the failure, and the host reference
(OMP_TARGET_OFFLOAD=disabled runs of the toolchains whose host run of the
original program matched the generator's model). File name:
`<seed>-<toolchain>.f90`. Run: `-O2`, `HSA_XNACK=1`,
`OMP_TARGET_OFFLOAD=mandatory` (offload/engine/toolchains.py recipes).

Cross-check (results/fuzz/c1/crosscheck.json): every wrong-code and
run-error file compiled and run on all four toolchains, device and host.
In each case the toolchains named "unaffected" print the host reference on
the device too. Status: provisional; found 2026-10-19 on AFAR 24.0.0git
(drop 24.3.0) and CCE 19.0.0, 20.0.2, 21.0.3 (MI300A).

Reference check. Three files were minimized
against a reference inside the failing compiler's family: `87-afar.f90` and
`1936-afar.f90` against AFAR's own host run (no CCE compiled them), and
`1978-cce19.f90` against CCE 20/21. The minimizer now never takes such a
reference (`offload.engine.fuzz_min.trusted_refs`: another family's host run,
or sequential elision), keeps the generator's `mod`/`iand` bounds and
rejects a candidate whose elided gfortran `-ftrapv` build traps. Sequential
elision of the three minimized files (gfortran and amdflang, no OpenMP)
prints the header's reference checksum (748154768, 2147483504, 1879642524)
and the `-ftrapv` build runs without a trap, so all three findings hold.

## Wrong code

| file(s) | toolchains | what |
|---|---|---|
| `536-cce19.f90`, `2014-cce19.f90`, `16-cce20.f90`, `1749-cce20.f90` | CCE 19, 20, 21 (AFAR correct) | the known guarded-loop bug (data/findings/cce19-target-parallel-guarded-loop.f90), rediscovered in four shapes: `target parallel` and `target` + `parallel`, writing an array or updating a mapped scalar (`r = r * 0`, `r = ior(r, i)`) in a sequential loop under `if (omp_get_thread_num() == 0)`. CCE's host runs are right |
| `14-cce20.f90` | CCE 19, 20, 21 | `lastprivate(lp1)` on `distribute parallel do simd` in `target teams map(tofrom: lp1)`: lp1 stays 0 on the device (expected the last iteration's value, 5.2 §5.4.5) |
| `98-cce19.f90`, `1978-cce19.f90` | CCE 19 only (host and device) | `defaultmap(firstprivate: aggregate)` with the array in an explicit `map(tofrom:)`/`map(always, from:)` clause: CCE 19 makes the array firstprivate, the writes are lost. defaultmap governs only implicitly determined attributes (5.2 §5.8.1, §5.8.7). CCE 20, 21 and AFAR are right |
| `1644-cce21.f90`, `775-cce21.f90` | CCE 21 only (host and device) | the CCE 21 defaultmap finding (data/findings/cce21-defaultmap-aggregate-flag.f90) for two more categories: `defaultmap(tofrom: allocatable)` and `defaultmap(tofrom: scalar)` on a target with `map(tofrom: r)`: the scalar's result is not copied back. In the campaign, 39 programs fail on CCE 21 and pass on CCE 20 with a defaultmap clause, 1 without |
| `650-afar.f90`, `700-afar.f90`, `87-afar.f90` | AFAR only | a `parallel` region with a `firstprivate` clause (of the distribute loop's index, or of a scalar) inside a `distribute` loop of `target teams`: the array writes of the nested worksharing loop are lost (all zero, or wrong elements) |
| `1936-afar.f90` | AFAR only (CCE: ICE) | `critical` in a worksharing loop in `target` + `parallel`, updating a mapped scalar with `ieor`: wrong value on the device |

## Run errors

| file(s) | toolchains | what |
|---|---|---|
| `1131-afar.f90`, `158-afar.f90` | AFAR only | `map(close, present, ...)` on a target region after `target enter data` mapped the array: the runtime reports the item absent and aborts (HSA_XNACK=1) |
| `698-afar.f90`, `916-afar.f90` (a correction: `698-afar.f90` not reproducible on AFAR 24.3.0) | AFAR only | a `parallel` (or `parallel do`) with reductions nested in a `distribute` loop of `teams` that also reduces: SIGABRT on the device |
| `1505-cce20.f90` (a correction: not reproducible on the current CCE 20.0.2) | CCE 20 only | a `do reduction(min: r)` in `target` + `parallel` whose update calls a declare-target function: SIGSEGV on the device |

## Internal compiler errors

| file | toolchains | message |
|---|---|---|
| `2224-cce19.f90` | CCE 19, 20, 21 | an empty `masked` construct in a target region: "unhandled construct type" (19) / "unhandled acc construct type" (20, 21); the same family as data/findings/cce19-target-parallel-single-ice.f90 (`single`, explicit tasks) |
| `958-cce20.f90` | CCE 19, 20, 21; AFAR (ICE too) | `lastprivate(conditional:)` on `target parallel do`: "Mismatched last induction expression for last private operators" |
| `1540-afar.f90` | AFAR | `lastprivate(conditional:)` on `target parallel do` with an empty loop body: "'omp.target' op SPMD kernel must capture an 'omp.loop_nest' operation", "verification of lowering to FIR failed" |
| `165-cce19.f90` | CCE 19, 20, 21; AFAR (ICE too) | `lastprivate(conditional:)` on a `parallel do` in a `target` with `depend`: "unhandled operator" |
| `591-cce19.f90` | CCE 19, 20, 21 | `teams distribute simd` with `lastprivate`, `private` and `nontemporal` in a target: "Unhandled contexts must be fixed!!!" |
| `1391-cce20.f90` | CCE 19, 20, 21 | `lastprivate` on a `do` (with an inner sequential loop) in `target` + `parallel`: "ACC - barrier/reset/protected last private not supported" |
| `2334-cce19.f90` | CCE 19, 20, 21 | `atomic` update `r = r * merge(-1, 1, mod(11, 13) == 0)` (a constant factor) in an orphaned `do` in `target`: "Couldn't find an atomic update statement" |

# Base-language campaigns (generator `fuzz-3`)

Campaigns `b1`-`b5` (300 programs each, one base-language group each:
data/reports/fuzz-base-language.md) and the control `b0` (no group: the
fuzz-2 programs of the same seeds). Files are named
`<run>-<seed>-<toolchain>.f90`. A program of these campaigns also passes
the definedness check (offload.engine.fuzz.check_defined); the minimizer
keeps it (each candidate must pass it) and never takes a reference from
the failing compiler's family. Files minimized before the minimizer
learned to shrink across files and kernel procedures were refined once
(`tools/campaigns/fuzz.py refine`). The "base-language?" column says whether the
reduced program still needs a base-language feature of its group (checked
by hand: the same program with the feature replaced by the plain integer
form).

## Stage 1 (`b1`, group types)

| file | toolchains | what | base-language? |
|---|---|---|---|
| `b1-22-cce20.f90` | CCE 19, 20, 21 (AFAR rejects lastprivate on distribute) | `lastprivate(lp1)` on `distribute` in `target teams`, with a nested `parallel do lastprivate(lp1)`: lp1 stays 0 on the device (expected 8, the last iteration's value; reference: sequential elision). Same family as `14-cce20.f90` (lastprivate on a composite `distribute parallel do simd`) | no (no typed item left) |
| `b1-121-afar.f90` | AFAR | `teams reduction(iand: r) firstprivate(p1)` with an empty body in a target region: r becomes 0 (expected unchanged, 1048575). Without the firstprivate clause, or with `+` or `ior`, AFAR is right. New | no |
| `b1-183-afar.f90` | AFAR | `atomic` `min` update in a `parallel do` nested in a `teams distribute` loop: wrong value. A new member of the AFAR nested-parallel-in-distribute family (`650-afar.f90`, `700-afar.f90`, `87-afar.f90`) | no |
| `b1-231-afar.f90` | AFAR | `atomic` update of a `double precision` scalar in a `do` of a `parallel` nested in a `distribute` loop: SIGABRT. The same with an integer scalar, so the abort family of `698-afar.f90`/`916-afar.f90` without a reduction | no (integer too) |
| `b1-268-afar.f90` | AFAR | `parallel firstprivate(i)` in a `distribute` loop loses the writes of its worksharing loop (known family `650-afar.f90`), here with `nint` of a double precision array | no |

Not minimized: seed 111 on AFAR (the wrong code did not reproduce).
Base-language observations without a wrong answer: CCE 19 rejects
character arrays in target regions ("Unsupported OpenMP construct Fortran
character", 18 programs; CCE 20 and 21 run them), and once a private
allocatable ("Private of allocatables"). Typed outputs, typed reductions
(real, complex, logical, integer(1/2/8), exact by construction) and
typed reads agree on every toolchain that compiles them, apart from the
OpenMP-level failures above.
## Stage 2 (`b2`, group derived)

| file | toolchains | what | base-language? |
|---|---|---|---|
| `b2-85-cce20.f90` | CCE 19, 20, 21 (AFAR right) | `map(tofrom: dr%o1)` (a component of a structure) with `defaultmap(firstprivate: aggregate)` on the same target: CCE makes `dr` firstprivate and the component's writes are lost (all zero). The component map gives `dr` an explicit data-mapping attribute (5.2 §5.8.1 treats a reference to a structure element as one to the structure; §13.8 requires every referenced element of a structure with a mapped element to be mapped), so defaultmap does not apply. The array form was a CCE 19-only finding (`98-cce19.f90`, fixed in CCE 20); for a structure component all three releases fail. Provisional: rests on reading a component map as an explicit attribute of the structure | yes (structure component) |
| `b2-68-afar.f90` | AFAR | `parallel if(parallel: lpar)` with `lpar = .false.` in a target region, holding a `loop reduction(+: r)` over a nested loop: r gets the contribution four times (70431 instead of 17631); in one of 16 gate runs (environment d, HSA_XNACK=1) AFAR printed 52831 (three times), so the count is not stable. With `lpar = .true.`, or `num_threads(1)` instead of the if clause, AFAR is right. New | no |
| `b2-183-afar.f90` | AFAR (HSA_XNACK=1 only) | `atomic` min update of a mapped scalar in a `parallel do` nested in `target teams distribute`, with an allocatable array written in the same loop: GPU memory access fault ("Write access to a read-only page") at HSA_XNACK=1 with THP on and off; correct at HSA_XNACK=0. Hand-reduced to `../afar-xnack1-atomic-min-nested-parallel.f90` (needs the allocatable write, the inner parallel do and the atomic min; an atomic add is correct). New (from the THP/memory-mode split) | no (the derived types are unused) |
| `b2-209-cce19.f90` | CCE 19, 20, 21 (AFAR does not implement it) | `lastprivate(conditional: lp1)` on `target simd` (implicitly `map(tofrom: lp1)`, 5.2 §17.2), assigned in the even iterations: lp1 stays 0 instead of 16 on the device and on the host fallback. Reference: sequential elision (the program was noncompliant until the analysis read structures; no host build prints the model value). The same failure as the disputed c1 seed 1283 (`target simd lastprivate(conditional:)` left at 0 on CCE 19-21). New | no (the structures are unused) |
| `b2-52-afar.f90` | AFAR | `parallel firstprivate(i)` in a `distribute` loop: the worksharing loop's writes are lost (known family `650-afar.f90`) | no |
| `b2-213-afar.f90` | AFAR | nested `parallel` + `do reduction(ieor: r)` in a `distribute` loop of `teams reduction(ieor: r)`: SIGABRT (known family `698-afar.f90`) | no |

Whole-structure, component and implicit maps of structures, nested
components and arrays of structures otherwise agree on every toolchain
that compiles them.

## Stage 3 (`b3`, group alloc)

Two generator defects were found here and fixed before the findings
below (the 41 affected programs were rerun
and their earlier results discarded): a scalar dummy declared
`intent(in)` while its kernel mapped it `tofrom`, and a `present`
modifier on a pointer component (the data region maps the structure,
not the pointer's target, so error termination was right). The second
caused most CCE 19/20 run errors of the first pass; its reproducer
(`b3-199`) was withdrawn.

| file | toolchains | what | base-language? |
|---|---|---|---|
| `b3-61-cce20.f90`, `b3-250-cce20.f90` | CCE 19, 20, 21 (AFAR does not implement the construct, a correction: CCE 21.0.3 and 21.0.4 compile them and fail like 19/20, wrong checksum or illegal address on rerun) | `taskgroup task_reduction(+: r)` + `target in_reduction(+: r)` inside an internal subroutine, the target region writing a whole array that is mapped implicitly (an explicit-shape or assumed-shape dummy) with a host-associated loop variable: the writes do not reach the host (wrong checksum on the device and on the host fallback; the reduction variable is not even updated). Reference: sequential elision, which now reads internal subroutines (the programs were noncompliant before: no host build prints the model value). Related to `b3-197-cce19.f90` (the same construct in a procedure, SIGABRT there). New | yes (kernel in an internal subroutine) |
| `b3-278-cce19.f90` | CCE 19, 20, 21 (a correction: CCE 21.0.3 and 21.0.4 fail it too, hipErrorIllegalAddress at HSA_XNACK 0 and 1, on rerun; AFAR right) | a structure with an allocatable component, implicitly mapped by a `target teams` region that reads the component (deep copy by the default mapper, 5.2 §5.8.3), with a `reduction(max: r)`: SIGABRT | yes (allocatable component) |
| `b3-190-cce21.f90` | CCE 21 only | a kernel in an internal subroutine whose target construct has `map(to: zopt)` for an absent optional dummy (5.2 §3.2.1: the clause is ignored for it) and calls a declare target function with an `intent(inout)` scalar dummy: SIGSEGV. 19 of the 29 b3 programs with an absent optional in a map clause crash on CCE 21 | yes (absent optional dummy) |
| `b3-9-cce21.f90`, `b3-45-cce21.f90` | CCE 21 and AFAR | `map(to: zopt)` for an absent optional dummy in an internal subroutine (5.2 §3.2.1: the clause is ignored for it), on a target region whose body is a `teams loop` or a `parallel` + `do private` inside a sequential loop, with nothing else mapped: SIGSEGV on both. The `b3-190-cce21.f90` family; these shorter forms crash AFAR too. Reference: sequential elision (now reads internal subroutines and absent optional dummies). | yes (absent optional dummy) |
| `b3-54-afar.f90` | AFAR (CCE right) | an empty `target nowait depend(in: p1) depend(inout: dr, hf1, ic, o1)` followed by `taskwait`, where `dr` has an allocatable component, `ic` is allocatable and `o1` a pointer: SIGSEGV. New | yes (allocatable component, pointer in depend) |
| `b3-94-afar.f90` | AFAR | `parallel firstprivate(i)` + `do` in a `distribute` loop: the writes are lost (all zero; known family `650-afar.f90`, as `b2-52-afar.f90`). Reference: sequential elision. | no |
| `b3-197-cce19.f90` | CCE 19, 20, 21 (a correction: CCE 21.0.3 and 21.0.4 compile it and fail like 19/20, on rerun; no in_reduction link failure) | `taskgroup task_reduction` + `target in_reduction` inside an internal subroutine whose assumed-shape and pointer dummies the target maps implicitly: SIGABRT | yes (assumed-shape/pointer dummies in a procedure) |
| `b3-188-cce19.f90` | CCE 19, 20, 21 | `distribute parallel do schedule(dynamic) dist_schedule(static, 16)` in a `target teams` inside an internal subroutine: internal compiler error "Unexpected schedule" (v_mt_translate.c), a message no earlier campaign showed | not checked (the kernel procedure stayed) |
| `b3-9-afar.f90`, hand-reduced to `../afar-nontemporal-assumed-shape-ice.f90` | AFAR | `nontemporal(o1)` on a `simd` where `o1` is an assumed-shape dummy: "verification of lowering to FIR failed": `'omp.simd' op operand #0 must be variadic of OpenMP-compatible variable type, but got '!fir.box<!fir.array<?x?xi32>>'` | yes (assumed-shape dummy) |

Not minimized at first (no reference outside the failing compiler's
family: another family's host build or sequential elision, which did not
read internal procedures or structures then): seeds 9, 45 (CCE 21), 54,
94 (AFAR), 271, 11 (CCE). Minimized 9, 45,
54 and 94 (above); 271 (CCE 19) timed out on the device instead of
giving its wrong value when rerun, so it was not reproduced; 11 (CCE 20)
has a present modifier, which elision does not apply to. Withdrawn: `b3-92` (the minimizer had deleted the explicit map of the
pointer component `dr%pc`, which leaves its association undefined; the
minimizer now keeps the maps of structure elements and pointer
components).

## Stage 4 (`b4`, group declare)

| file | toolchains | what | base-language? |
|---|---|---|---|
| `b4-86-cce19.f90` | CCE 19, 20 (CCE 21, AFAR right) | `map(mapper(mmap), tofrom: ms)` with a named `declare mapper(mmap: mt_t :: v) map(tofrom: v%a)` on `target teams`: SIGABRT. The same program with the default mapper (unnamed), or without the mapper modifier, runs. 8 of 13 b4 programs with a named mapper fail on CCE 20 | yes (declare mapper) |
| `../afar-udr-derived-type-link.f90` (hand-written from the b4 failures) | AFAR (CCE: not implemented) | `declare reduction(padd: pair_t: ...)` with an initializer on a derived type, used on `target teams distribute parallel do`: the device link fails (`ld.lld: undefined symbol: flang_rt_verbose_abort`, Fortran runtime I/O symbols referenced from `_FortranAInitialize` in the device image); 27 of the 39 b4 programs that use the reduction fail this way (the other 12 stop earlier at a not-yet-implemented message). CCE 19/20/21: "Unsupported OpenMP construct Calls -- $udr_..." | yes (user reduction on a derived type) |

| `b4-39-afar.f90` (a correction: not reproducible on AFAR 24.3.0) | AFAR | nested `parallel` + `do reduction(max: r) reduction(*: s)` in the `distribute` loop of `teams` with the same reductions, reading a structure `ms` of the module type with the default `declare mapper` (implicitly mapped): wrong value. The nested-reduction shape is the known AFAR abort family (`698-afar.f90`); whether the mapper matters was not checked (the reduction did not shrink further in 79 minutes) | not checked |

Not minimized (no reference outside the failing family): seeds 253
(CCE 19/20/21 wrong code) and 9 (AFAR run error).

Support gaps (compile rejections, not failures): CCE 19 and 20 reject the
5.2 spelling `declare target enter(...)` (172 programs each; the
deprecated `to` works, so half the programs use it); CCE 19/20/21 do not
implement user-defined reductions in target regions.

## Stage 5 (`b5`, group multitu)

Bundles of five to eight files (modules, a module chain, a submodule, an
external declare target function) compile one file at a time and link on
every toolchain; no failure needed the file split. The two AFAR wrong-code
programs specific to b5 (seeds 11, 167) could not be minimized: no CCE
build compiles them and sequential elision does not apply to bundles with
submodules.

# All groups combined (campaign `s1`, generator `fuzz-3`)

Campaign s1: seeds 1-10000 with all five base-language groups at once
(HSA_XNACK=1), and s1x0: seeds 1-2500 at HSA_XNACK=0; triage by the
confirmer (`tools/confirm.py batch`, agent decisions and spot checks in
catalog/triage_28.yaml; review data/reports/fuzz-s1.md). A finding is
promoted only for a confirmed compiler_bug verdict whose failure signature
no indexed finding has (offload/engine/confirm/findings.py); these are written
by hand from the confirmer's reductions, checked on all four toolchains
(results/t28_probe) and on Tioga's gfx90a twins, and indexed in
../index.yaml (they do not use the fuzz_min header format). File name:
`s1-<seed>-<toolchain>.f90` (the representative cell).

| file | toolchains | what | base-language? |
|---|---|---|---|
| `s1-6888-cce21.f90` | CCE 19, 20, 21 (AFAR right); MI300A and MI250X | `target update to(a(1:n:2))`: ftn-1747 "The stride specified for array ... must not be greater than 1". Strided sections are allowed in motion clauses since 5.0 (5.2 §5.9 p.165, §B.4 p.634); only map requires contiguous storage. New | no |
| `s1-2370-cce21.f90` | CCE 19, 20, 21 (AFAR right); MI300A and MI250X | `parallel do default(none) shared(a) firstprivate(i)` nested in a `teams distribute` loop over i: ftn-1510 for I (ftn-1310 "must have a shared scope in the enclosing region" in other programs). firstprivate on the combined construct makes i shared on the parallel leaf (5.2 §17.2 p.340); without firstprivate(i) all compile. New | no |
| `s1-8634-cce21.f90` | CCE 19, 20, 21 (AFAR right); MI300A and MI250X | a character scalar in `target enter data map(to: xs)` / `target exit data map(release: xs)` (or `map(delete: xs)`): internal compiler error, optcg killed by signal 11 (ftn-2116); in larger programs the same statements give "Unhandled expression type in get base or dv mem" (seed 8634) or "unexpected type in TYPE_DEREF" (seed 2952). Character arrays compile. New | yes (character scalar) |
| `s1-2592-cce21.f90` | CCE 19, 20, 21 (AFAR right); MI300A and MI250X | `taskgroup task_reduction(*: r)` + `target in_reduction(*: r)` reading `ichar(xs(1:1))` of a character dummy: internal compiler error "Should never reach this code (doehmke)" (v_mt_util_misc.c). With a constant instead of the substring it compiles. New | yes (character dummy) |
| `s1-3463-cce21.f90` | CCE 19, 20, 21 (AFAR right) | target construct in an internal subroutine mapping components of a structure dummy (`dr%a`, `dr%nd%k(1:n)`) with host-associated variables: internal compiler error "Error getting dope vector information" (v_dope_utl.c). Reduced by the confirmer and by line deletion to 106 lines, then by clause and list-item deletion to 49; a hand-written smaller form compiles. New | yes (structure dummy components) |
| `s1-6085-cce21.f90` | CCE 20, 21 (CCE 19 does not implement user reductions on the device) | `target teams loop map(always, tofrom: dr%pc) ... reduction(padd: rp2a)` (a pointer component, a declare reduction of a derived type): optcg killed by signal 6 (ftn-2116). Reduced to 130 lines, then by clause and list-item deletion to 56 (two empty target teams regions, one with the user reduction); hand-written smaller forms do not reproduce it. New | yes (pointer component, derived-type reduction) |
| `s1-9914-cce19.f90` | CCE 19 only (CCE 20, 21, AFAR compile in seconds) | the compile does not finish (over 300 s); target maps of structure components with thread_limit, a depend on a declare target array section, a default declare mapper. Fix: reduced to 33 lines (an empty target with thread_limit(1), an empty target with depend(out: go2(:)) on a declare target array, a submodule procedure). 93 CCE 19 compile timeouts in s1/s1x0. New | yes (structure components, module array) |
| `s1-91-cce21.f90` | CCE 21 (CCE 19, 20 in the campaign; AFAR right) | ftn-1510 "must have its data scope explicitly declared because DEFAULT(NONE) was specified" for a variable of a target region in an internal subroutine with no default clause; the default(none) is on an empty parallel in a sibling internal subroutine. Related to `../cce21-linear-modifier-default-none.f90` by its message only (no linear clause; a different construct). New | yes (internal subroutines) |
| `s1-6760-cce20.f90` (hand-written) | CCE 20 (CCE 19 unsupported: no claim; CCE 21, AFAR right) | `declare target enter(g)` on a module variable: ftn-1725 "INDIRECT, LINK, TO or DEVICE_TYPE was expected but found E". The CCE 20.0.0 release notes claim the new 5.2 declare target syntax, whose only new form is enter: compiler_bug for 7,099 CCE 20 cells of s1/s1x0 (R11 and decision D9). New | no |
| `s1-4339-afar.f90` (hand-written from the reduction) | AFAR at HSA_XNACK=1 only (CCE 19/20/21 right; AFAR right at HSA_XNACK=0) | `target map(close, tofrom: ia) map(tofrom: o1)` where ia is an allocatable dummy the region does not use and the region reads another assumed-shape dummy: SIGABRT (in the campaign "OFFLOAD ERROR: memory access fault ... Write access to a read-only page"). Without close, with an explicit-shape ia, or reading ia instead, AFAR is right. Representative of the s1 group "AFAR memory access fault" (59 cells; the group may hold other defects, so its cells are not linked as instances). New | no |
| `s1-7882-cce20.f90` | CCE 19, 20, 21 (AFAR right), both modes | `target map(present, tofrom: xc)` for an allocatable character(len=4) array mapped by the enclosing `target data`: exit status 1, "Variable not found in present table". Fix: reduced by hand to 23 lines (with a fixed-size array only CCE 19 fails). Related to `s1-8634-cce21.f90` (character scalar ICE): another construct and symptom. New | yes (character array) |
| `s1-9443-afar.f90` | AFAR at HSA_XNACK=1 only | empty `target map(close, present, to: xk1)` inside a `target data` that maps xk1: SIGABRT, present lookup fails ("getTargetPointer returned null pointer ('present' map type modifier)"); AFAR is right at HSA_XNACK=0, CCE 19/20/21 right (the 82-line reduction also failed on CCE 19). Fix: reduced by hand to 15 lines; without `close` AFAR passes, so it is the known close + present abort of `158-afar.f90` / `1131-afar.f90` (after `target enter data` there). Known | no |

Known findings the campaign reproduces on Tioga MI250X (new information):
`b2-209-cce19.f90` (CCE `target simd lastprivate(conditional:)` loses the
value): CCE 19, 20, 21 on gfx90a give lp=0 (data/evidence/dataenv_probe/
lpcond_simd_up.f90; mapping lp explicitly, or lastprivate without the
modifier, is correct on every CCE release, so the lost implicit
`map(tofrom)` of a conditional lastprivate item is the defect).

Run-time representatives reduced with `tools/campaigns/fuzz.py minimize-one` that are
known findings: s1 seed 3359 (CCE 19-21 wrong code: taskgroup
task_reduction + target in_reduction in an internal subroutine, the
`b3-61-cce20.f90`/`b3-250-cce20.f90` family), seed 7031 (CCE 21 wrong code
with defaultmap(alloc: aggregate) and a map(tofrom) scalar,
`../cce21-defaultmap-aggregate-flag.f90`), seed 8131 (AFAR SIGSEGV on an
empty target nowait with depend, `b3-54-afar.f90`), seed 8411 (AFAR
SIGABRT, "Failed to process data before launching the kernel", for
map(to: zopt) of an absent optional dummy, the `b3-9-cce21.f90` family).

## GCC 16.2 (coverage parity, 2026-10-28)

A 5000-program sample of the campaigns (catalog/parity_fuzz_sample.json: per generator version and base groups, chosen by
seed before any run) ran on gcc_g90 (MI250X) and gcc_sm80 (A100) with separate memory (results/parity/<machine>/). The
minimizer ran on Tioga (`tools/campaigns/fuzz.py minimize --xnack 0 --also afar_g90,...`; its legality checks through AFAR's front end
from /p/vast1), never on wingtip (no AFAR there), so failures seen on the A100 only are not minimized. Files of this
campaign: `par-<stratum>-<seed>-<toolchain>.f90` (minimized) and `gcc-*.f90` (hand reductions, indexed in index.yaml);
data/findings/LOG.md lists them.

NVHPC 25.11 and 26.9 ran the whole sample too (2026-11-03: strata c1 and s1 completed, 745 and 3081 programs per release;
separate memory, `tools/jobs/run_parity_wingtip.sh fuzz:<stratum>:nvhpc+nvhpc269`), and every failing cell went through the gate
(a, b, d on one GPU, (c) on another). s1 is 97% rejections of the `declare` base group's spellings (declare target enter,
declare mapper and reduction, `mod` in initialization expressions). The failures that are not rejections are CUDA illegal
address and misaligned address run errors, timeouts, wrong values and three known compile failures (Missing branch target,
Character local variable, fort1 signal 11), plus one new internal compiler error ("offset should not be overridden",
seed 9895). None is reduced yet; the clusters and candidates are in the coverage-parity report.

