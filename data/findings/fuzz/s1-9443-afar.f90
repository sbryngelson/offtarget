! Minimized by compliance.fuzz_min from fuzz seed 9443 (fuzz-3).
! toolchain: afar (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: run_error (crash)
! message: 'present' map type modifier
! expected: runs to completion (the host run does)
! observed: device: fail crash: SIGABRT; host reference (cce21) checksum=0
! Legal OpenMP 5.2: offload.engine.rules accepts it (offload.engine.prerun.check, rerun: with the
!   race rule and the restriction checks); NVHPC is no witness: it rejects it
!   (NVFORTRAN-S-0034-Syntax error at or near :); the check's other
!   witness, the AFAR flang front end, is the compiler under test and is not counted; no gfortran
!   or gcc is a legality witness.
! also fails on: cce19
! Finding: AFAR aborts at HSA_XNACK=1 (SIGABRT, "Call to
! getTargetPointer returned null pointer ('present' map type modifier)")
! at an empty target construct with map(close, present, to: xk1), where
! the enclosing target data construct maps xk1 (an integer(1) array); at
! HSA_XNACK=0 AFAR runs it. CCE 19 also ends with exit status 1 in both
! modes; CCE 20 and 21 run it.
! Legal OpenMP 5.2: the target data construct makes xk1 present, so the
! present modifier is satisfied (5.2 §5.8.3); close is a hint.
! Observed (tuolumne, MI300A, -O2, 2026-10-23,
! results/t28_probe/rt/9443-afar.f90.*.json): AFAR SIGABRT at HSA_XNACK=1,
! "RESULT checksum=0" at HSA_XNACK=0; CCE 19 exit status 1 (both modes);
! CCE 20, 21 "RESULT checksum=0". Reduced from s1 seed 9443 by
! tools/campaigns/fuzz.py minimize-one (146 -> 82 lines). The present-modifier aborts
! are AFAR's largest unified-only group in the copy-mode comparison.
! Related: ../afar-xnack1-present-not-enforced.f90 (AFAR at HSA_XNACK=1
! does not enforce present for an absent item: the opposite symptom of the
! same unified-memory present handling).
! Shorter form (fix; written by hand from
! the 82-line reduction, which git history keeps): an integer(1) array
! alone in target data map(to: xk1) and an empty target with
! map(close, present, to: xk1) (data/evidence/dataenv_probe/short/c9443_a.f90).
! Observed (tuolumne, MI300A, -O2, 2026-10-23, results/t28_probe/short/
! c9443_a.f90.*.json): AFAR SIGABRT at HSA_XNACK=1, "RESULT check=pass" at
! HSA_XNACK=0; CCE 19, 20, 21 pass in both modes (CCE 19's exit status 1
! needs the longer form). Without close (c9443_b) AFAR passes: the close
! modifier is the trigger. Expected: "RESULT check=pass".
! Known defect: this is the AFAR close + present abort at
! HSA_XNACK=1 of fuzz/158-afar.f90 and fuzz/1131-afar.f90 (there after
! target enter data, here inside target data); not a new finding.
program p
  implicit none
  integer, parameter :: n = 100
  integer(1) :: xk1(n)
  integer :: i
  do i = 1, n
    xk1(i) = int(mod(i * 17 + 16, 127), 1)
  end do
  !$omp target data map(to: xk1)
    !$omp target map(close, present, to: xk1)
    !$omp end target
  !$omp end target data
  print '(a)', 'RESULT check=pass'
end program p
! site:
! title: AFAR offload runtime at HSA_XNACK=1: map(close, ...) breaks presence lookup and device access (abort, memory fault)
! control: ../vendor/checks/src/other/control/s1-9443-afar-control.f90 map(present, to: xk1) without the close modifier
! end site
