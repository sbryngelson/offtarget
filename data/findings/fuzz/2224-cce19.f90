! Minimized by compliance.fuzz_min from fuzz seed 2224 (fuzz-1).
! toolchain: cce19 (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: ice (ice: INTERNAL COMPILER ERROR: "unhandled construct type" (v_openmp.c, line 7617, version <v>))
! expected: compiles
! observed: internal compiler error: ice: INTERNAL COMPILER ERROR:  "unhandled construct type" (/workspace/crayftn/pdgcs/v_openmp.c,
!   line 7617, version cc4d36e4ff3377d45f0e6e892b5dacd82009a0ca)
! Legal OpenMP 5.2: offload.engine.prerun.check accepts it (rerun: offload.engine.rules with the
!   race rule and the restriction checks, and the AFAR flang front end, not under test here); no
!   compiler under test, gfortran or gcc is a legality witness.
! also fails on: cce20, cce21
program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 32, m = 2
  integer :: i, j
  integer(8) :: cs
  ! fuzz: kernels
  !$omp target
    !$omp masked
    !$omp end masked
  !$omp end target
  ! fuzz: checksum
  cs = 0
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', 0
end program fuzz_prog
! site:
! title: ftn/craycc: constructs documented as unsupported in offload regions (single, masked, task, ordered, scan) give internal
! + compiler errors or device link failures instead of a diagnostic
! same_as: cce19-target-parallel-single-ice
! end site
