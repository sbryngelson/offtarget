! Minimized by compliance.fuzz_min from fuzz seed 231 (fuzz-3).
! toolchain: afar (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: run_error (crash: SIGABRT)
! expected: runs to completion (the host run does)
! observed: device: fail crash: SIGABRT; host reference (cce20/elision) checksum=1450123117
! Legal OpenMP 5.2: offload.engine.rules accepts it (offload.engine.prerun.check, rerun: with the
!   race rule and the restriction checks); nvfortran/nvc 26.9 and 25.11 (NVHPC, not under test
!   here) compile it; the check's other witness, the AFAR flang front end, is the compiler under
!   test and is not counted; no gfortran or gcc is a legality witness.
module fuzz_mod
  implicit none
contains
end module fuzz_mod
program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 16, m = 3
  integer, allocatable :: o1(:, :)
  double precision :: r1b
  integer :: i, j
  integer(8) :: cs
  allocate(o1(n, m))
  o1 = 0
  r1b = (-21.0d0)
  ! fuzz: kernels
    !$omp target map(tofrom: r1b)
      !$omp teams
        !$omp distribute
        do i = n, 1, -1
          !$omp parallel
            !$omp do
            do j = 1, m
              o1(i, j) = 0
              !$omp atomic
              r1b = r1b + mod(i, 97)
            end do
          !$omp end parallel
        end do
        !$omp end distribute
      !$omp end teams
    !$omp end target
  ! fuzz: checksum
  cs = 0
  cs = modulo(cs * 31_8 + int(r1b * 64, 8), 2147483629_8)
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o1(i, j), 8), 2147483629_8)
    end do
  end do
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', 0
end program fuzz_prog
! site:
! title: amdflang at HSA_XNACK=1: a parallel region with a reduction (or atomic) nested in a distribute loop of a reducing teams
! + region aborts
! same_as: fuzz/916-afar
! end site
