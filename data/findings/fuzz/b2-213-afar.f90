! Minimized by compliance.fuzz_min from fuzz seed 213 (fuzz-3).
! toolchain: afar (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: run_error (crash: SIGABRT)
! expected: runs to completion (the host run does)
! observed: device: fail crash: SIGABRT; host reference (cce19) checksum=797202134
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
  integer, parameter :: n = 32, m = 5
  type :: rec_t
    integer :: a(n)
  end type rec_t
  type :: el_t
  end type el_t
  type(rec_t) :: dr
  type(el_t) :: ds(n)
  integer, allocatable :: o1(:, :)
  integer :: i, j, r1a
  integer(8) :: cs
  allocate(o1(n, m))
  do i = 1, n
    dr%a(i) = mod(i * 23 + 28, 1009) - 305
  end do
  o1 = 0
  r1a = 145
  ! fuzz: kernels
    !$omp target map(tofrom: r1a)
      !$omp teams reduction(ieor: r1a)
        !$omp distribute
        do i = 1, n
          !$omp parallel
            !$omp do reduction(ieor: r1a)
            do j = 1, m, 2
              o1(i, j) = 0
              r1a = ieor(r1a, iand(dr%a(i), 1048575))
            end do
          !$omp end parallel
        end do
      !$omp end teams
    !$omp end target
  ! fuzz: checksum
  cs = 0
  cs = modulo(cs * 31_8 + int(r1a, 8), 2147483629_8)
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
