! # Draft finding: data/reports/fuzz-stress-audit/r4-declare-target-scalar-control.f90 on cce21
!
! - compiler: cce21
! - toolchain: cce21; arch: gfx942; machine: tuolumne; memory mode: copy; opt: -O2
! - program: file data/reports/fuzz-stress-audit/r4-declare-target-scalar-control.f90 (f90, version 52, sha256 28c79fb1fd5b8dc7)
! - expected: g= 203 dev= 1 (trusted; metamorphic + model)
! - actual: wrong_answer g= 101 dev= 1 (expected g= 203 dev= 1)
! - verdict: compiler_bug by rule R20-runtime-bug: a legal program fails at run time, deterministically, against an expected value
!   from two or more independent sources with an executed witness, and another toolchain, mode, arch or the elision gives the
!   expected value
! - reason: expected trusted g= 203 dev= 1 (metamorphic + model): metamorphic + model agree; witnesses: afar/gfx942/copy,
!   cce19/gfx942/copy, cce20/gfx942/copy
! - citations: RUL-DERIVED-NEEDS-EXECUTION (rulings.md); RUL-WITNESS-PER-MODE (rulings.md);
!   RUL-SAME-COMPILER-RUNS (rulings.md); RUL-PRESENCE-WITNESS (rulings.md); RUL-METAMORPHIC-OTHER-FAMILY
!   (rulings.md)
! - legality: legal: read against the spec (audit and re-review); checked by scope, offload.engine.rules, flang (no checker of
!   the family under test)
! - witnesses: afar/gfx942/copy, cce19/gfx942/copy, cce20/gfx942/copy
! - withdrawn: none
!
! Audit, candidate 4, CONTROL (explicit map(tofrom: g)) of a declare target module scalar.
! Basis (N3): g appears in an enter clause (the 5.0 declare target(list) form), so its
! corresponding list item "is never removed from those device data environments as if its reference count
! was initialized to positive infinity" (5.2 §5.8.4 p.159 l.10-14; 5.0 §2.12.7 p.182 l.19-22). On entry to the
! target region the storage is present and its count is not one, so no new list item is created and no
! "to" transfer happens (5.2 §5.8.3 p.153 l.1-17, steps 1-3); on exit the count is not one, so no "from"
! transfer happens and an infinite count is not decremented (p.153 l.31-35, p.154 l.1-11). The region therefore reads and
! writes the declare target copy (101 -> 203), and "target update from(g)" returns 203. This is the same
! result as the implicit form (5.2 §5.8.1 p.148 l.9-11 treats it "as if" this map clause appeared). No
! restriction forbids an explicit map of a declare target variable (5.2 §5.8.3 p.156-157, §7.8 p.205,
! §7.8.1 p.206, §13.8 p.286-287). Expected: g= 203 dev= 1. CCE 21 without the map (r4-declare-target-
! scalar.f90) gives 203; CCE 19/20, AFAR and NVHPC give 203 with the map.
module dt_scalar_m
  implicit none
  integer(8) :: g
  !$omp declare target(g)
end module dt_scalar_m
program declare_target_scalar
  use omp_lib
  use dt_scalar_m
  implicit none
  integer :: dev
  g = 101
  dev = -1
  !$omp target update to(g)
  !$omp target map(tofrom: dev, g)
    g = 2 * g + 1
    dev = merge(0, 1, omp_is_initial_device())
  !$omp end target
  !$omp target update from(g)
  print '(a,i0,a,i0)', 'g= ', g, ' dev= ', dev
end program declare_target_scalar
! site:
! title: ftn: write to a declare target module scalar named in map(tofrom:) is lost
! control: ../vendor/checks/src/cce/control/cce21-declare-target-scalar-map-write-lost-control.f90 g not in the map clause
! + (implicitly
! + tofrom)
! end site
