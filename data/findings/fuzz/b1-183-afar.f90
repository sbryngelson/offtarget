! Minimized by compliance.fuzz_min from fuzz seed 183 (fuzz-3).
! toolchain: afar (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: wrong_code
! expected: the host reference checksum (host reference (cce19/elision) checksum=1123737439)
! observed: device checksum=1118127074 ran_on_host=0
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
  integer, parameter :: n = 24, m = 2
  integer :: ic(n, m)
  integer, allocatable :: o1(:, :)
  integer :: i, j, r1a
  integer(8) :: cs
  allocate(o1(n, m))
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 1 * j) * 20 + 50, 30011) - 2834
    end do
  end do
  o1 = 0
  r1a = 7
  ! fuzz: kernels
  !$omp target teams distribute map(tofrom: r1a)
  do i = 1, n
    !$omp parallel do
    do j = 1, m
      o1(i, j) = iand(ic(i, (mod(((j * 3) + 1), m) + 1)), 255)
      !$omp atomic
      r1a = min(r1a, mod(i, n))
    end do
  end do
  !$omp end target teams distribute
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
