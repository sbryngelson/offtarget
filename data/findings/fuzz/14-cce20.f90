! Minimized by compliance.fuzz_min from fuzz seed 14 (fuzz-1).
! toolchain: cce20 (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: wrong_code
! expected: the host reference checksum (host reference (cce20/afar) checksum=24)
! observed: device checksum=0 ran_on_host=0
! Legal OpenMP 5.2: offload.engine.prerun.check accepts it (rerun: offload.engine.rules with the
!   race rule and the restriction checks, and the AFAR flang front end, not under test here); no
!   compiler under test, gfortran or gcc is a legality witness.
! also fails on: cce19, cce21
program fuzz_prog
  implicit none
  integer, parameter :: n = 24, m = 8
  integer :: i, j, jj, lp1, acc1, t1
  logical :: lsimd
  integer(8) :: cs
  lp1 = 0
  lsimd = .false.
  ! fuzz: kernels
    !$omp target teams map(tofrom: lp1)
      !$omp distribute parallel do simd lastprivate(lp1) private(t1, acc1, jj) num_threads(8)
      do i = 1, n
        t1 = 0
        acc1 = 0
        lp1 = i
      end do
      !$omp end distribute parallel do simd
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
