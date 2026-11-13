! (copy mode for the whole catalog): AFAR does not perform the
! runtime error termination of the present map-type-modifier at
! HSA_XNACK=1 (unified memory).
! a was never mapped, so on entry to the region it is not present and
! "runtime error termination is performed" (5.2 §5.8.3 p.152); the
! program has no requires directive, so unified memory does not change
! the rule.
! Expected: an error termination before the end (no "reached the end").
! Observed (tuolumne, MI300A, 2026-10-22, 3 runs each, -O2,
! OMP_TARGET_OFFLOAD=mandatory):
! - AFAR amdflang 24.0.0git at HSA_XNACK=1: "reached the end: b1= 2" (the
!   region runs on the shared data); at HSA_XNACK=0: "omptarget message:
!   device mapping required by 'present' map type modifier does not exist"
!   and error termination, as required. AFAR amdclang (C programs) the same.
! - CCE 19.0.0, 20.0.2, 21.0.3: error termination in both modes ("Variable
!   not found in present table").
! The catalog's map.present negative probes (Fortran and C, 5.2 and 6.0)
! read wrong at HSA_XNACK=1 and correct at HSA_XNACK=0 on AFAR.
! AFAR: amdflang -fopenmp --offload-arch=gfx942 -O2
! Run:  OMP_TARGET_OFFLOAD=mandatory HSA_XNACK=1 ./a.out
program p
  implicit none
  integer :: a(64), b(64)
  a = 1
  b = 0
  !$omp target map(present, to: a) map(from: b)
    b = a + 1
  !$omp end target
  print *, 'reached the end: b1=', b(1)
end program p
! site:
! title: AFAR offload runtime at HSA_XNACK=1: omp_target_is_present returns false after target enter data, and map(present) of an
! + absent item does not terminate
! control: ../vendor/checks/src/afar/control/afar-xnack1-present-not-enforced-control.f90 run at HSA_XNACK=0
! same_as: afar-xnack1-target-is-present
! end site
