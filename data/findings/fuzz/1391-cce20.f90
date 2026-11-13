! Minimized by compliance.fuzz_min from fuzz seed 1391 (fuzz-1).
! toolchain: cce20 (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: ice (ice: INTERNAL COMPILER ERROR: "ACC - barrier/reset/protected last private not supported" (v_mt_translate.c, line
!   5607, version <v>))
! expected: compiles
! observed: internal compiler error: ice: INTERNAL COMPILER ERROR:  "ACC - barrier/reset/protected last private not supported"
!   (/workspace/crayftn/pdgcs/v_mt_translate.c, line 5607, version 668d73f
! Legal OpenMP 5.2: offload.engine.prerun.check accepts it (rerun: offload.engine.rules with the
!   race rule and the restriction checks, and the AFAR flang front end, not under test here); no
!   compiler under test, gfortran or gcc is a legality witness.
! also fails on: cce19, cce21
program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 32, m = 8
  integer :: i, j, lp1, t1
  integer(8) :: cs
  lp1 = 0
  ! fuzz: kernels
  !$omp target
    !$omp parallel
      !$omp do lastprivate(lp1) private(t1)
      do i = 1, n
        do j = 1, m
          t1 = 0
          lp1 = 0
        end do
      end do
    !$omp end parallel
  !$omp end target
  ! fuzz: checksum
  cs = 0
  cs = modulo(cs * 31_8 + int(lp1, 8), 2147483629_8)
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', 0
end program fuzz_prog
! site:
! title: ftn: internal compiler error "ACC - barrier/reset/protected last private not supported" for linear and lastprivate on a
! + loop in a target region
! same_as: catalog/cce-linear-lastprivate-ice
! end site
