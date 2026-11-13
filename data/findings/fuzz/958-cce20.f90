! Minimized by compliance.fuzz_min from fuzz seed 958 (fuzz-1).
! toolchain: cce20 (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: ice (ice: INTERNAL COMPILER ERROR: "Mismatched last induction expression for last private operators" (v_mt_translate.c,
!   line 901, version <v>))
! expected: compiles
! observed: internal compiler error: ice: INTERNAL COMPILER ERROR:  "Mismatched last induction expression for last private
!   operators" (/workspace/crayftn/pdgcs/v_mt_translate.c, line 901, version 6
! Legal OpenMP 5.2: offload.engine.prerun.check accepts it (rerun: offload.engine.rules with the
!   race rule and the restriction checks, and the AFAR flang front end, not under test here); no
!   compiler under test, gfortran or gcc is a legality witness.
! also fails on: afar, cce19, cce21
module fuzz_mod
  implicit none
contains
  integer function g1(x, y)
    !$omp declare target
    integer, intent(in) :: x, y
    g1 = mod(x, 1009)
  end function g1
end module fuzz_mod
program fuzz_prog
  use fuzz_mod, only: g1
  implicit none
  integer, parameter :: n = 100, m = 8
  integer :: i, j, lp1
  integer(8) :: cs
  lp1 = 0
  ! fuzz: kernels
  !$omp target parallel do lastprivate(conditional: lp1)
  do i = 1, n
    if (mod(i, 3) == 0) lp1 = 0
  end do
  ! fuzz: checksum
  cs = 0
  cs = modulo(cs * 31_8 + int(lp1, 8), 2147483629_8)
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', 0
end program fuzz_prog
! site:
! title: ftn: internal compiler error for lastprivate(conditional:) on a parallel loop in a target region
! control: ../vendor/checks/src/fuzz/control/fuzz-958-cce20-control.f90 the same loop on the host (parallel do instead of target
! + parallel
! + do)
! same_as: fuzz/1540-afar
! end site
