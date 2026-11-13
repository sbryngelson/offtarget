! # Draft finding: data/reports/fuzz-stress-audit/r1-target-scalar.f90 on afar
!
! - compiler: afar
! - toolchain: afar; arch: gfx942; machine: tuolumne; memory mode: copy; opt: -O2
! - program: file data/reports/fuzz-stress-audit/r1-target-scalar.f90 (f90, version 52, sha256 b1d59bfc76fdc1b7)
! - expected: rd= 101 s= 203 dev= 1 (trusted; metamorphic + model)
! - actual: wrong_answer rd= 101 s= 101 dev= 1 (expected rd= 101 s= 203 dev= 1)
! - verdict: compiler_bug by rule R20-runtime-bug: a legal program fails at run time, deterministically, against an expected value
!   from two or more independent sources with an executed witness, and another toolchain, mode, arch or the elision gives the
!   expected value
! - reason: expected trusted rd= 101 s= 203 dev= 1 (metamorphic + model): metamorphic + model agree; witnesses: cce19/gfx942/copy,
!   cce20/gfx942/copy, cce21/gfx942/copy
! - citations: RUL-DERIVED-NEEDS-EXECUTION (rulings.md); RUL-WITNESS-PER-MODE (rulings.md);
!   RUL-SAME-COMPILER-RUNS (rulings.md); RUL-PRESENCE-WITNESS (rulings.md); RUL-METAMORPHIC-OTHER-FAMILY
!   (rulings.md)
! - legality: legal: read against the spec (audit and re-review); checked by scope, offload.engine.rules (no checker of the
!   family under test)
! - witnesses: cce19/gfx942/copy, cce20/gfx942/copy, cce21/gfx942/copy
! - withdrawn: none
!
! Audit, candidate 1: a scalar with the TARGET attribute referenced
! in a target region is implicitly map(tofrom) (OpenMP 5.0 §2.19.7 p.315,
! 5.2 §5.8.1 p.149, 6.0 §7.9.3 p.277: "If a scalar variable has the TARGET,
! ALLOCATABLE or POINTER attribute then it is treated as if it had appeared
! in a map clause with a map-type of tofrom"). Expected: rd= 101 s= 203 dev= 1
program target_scalar_tofrom
  use omp_lib
  implicit none
  integer(8), target :: s
  integer(8) :: rd
  integer :: dev
  s = 101
  rd = -1
  dev = -1
  !$omp target map(tofrom: rd, dev)
    rd = s
    s = 2 * s + 1
    dev = merge(0, 1, omp_is_initial_device())
  !$omp end target
  print '(a,i0,a,i0,a,i0)', 'rd= ', rd, ' s= ', s, ' dev= ', dev
end program target_scalar_tofrom
! site:
! title: amdflang: scalar with the TARGET attribute is treated as firstprivate in a target region (device write lost)
! control: ../vendor/checks/src/afar/control/afar-target-scalar-implicit-firstprivate-control.f90 s mapped explicitly:
! + map(tofrom: rd,
! + dev, s)
! end site
