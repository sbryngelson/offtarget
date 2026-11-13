! Minimized by compliance.fuzz_min from fuzz seed 22 (fuzz-3).
! toolchain: cce20 (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: wrong_code
! expected: the host reference checksum (host reference (elision) checksum=8)
! observed: device checksum=0 ran_on_host=0
! Legal OpenMP 5.2: offload.engine.prerun.check accepts it (rerun: offload.engine.rules with the
!   race rule and the restriction checks, and the AFAR flang front end, not under test here); no
!   compiler under test, gfortran or gcc is a legality witness.
! also fails on: cce19, cce21
program fuzz_prog
  use omp_lib, only: omp_get_default_device, omp_get_thread_num, omp_is_initial_device
  implicit none
  integer, parameter :: n = 32, m = 3
  integer :: i, j, p2, lp1
  integer(8) :: cs
  p2 = 8
  lp1 = 0
  ! fuzz: kernels
  !$omp target teams map(tofrom: lp1)
    !$omp distribute lastprivate(lp1)
    do i = 1, n
      !$omp parallel do lastprivate(lp1)
      do j = m, 1, -1
        lp1 = p2
      end do
      !$omp end parallel do
    end do
    !$omp end distribute
  !$omp end target teams
  ! fuzz: checksum
  cs = 0
  cs = modulo(cs * 31_8 + int(lp1, 8), 2147483629_8)
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', 0
end program fuzz_prog
! site:
! title: craycc/ftn: lastprivate on distribute in a target region loses the final value, even with an explicit map
! same_as: stress/cce-c-distribute-lastprivate-lost
! end site
