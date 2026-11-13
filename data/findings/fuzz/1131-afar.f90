! Minimized by compliance.fuzz_min from fuzz seed 1131 (fuzz-1).
! toolchain: afar (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: run_error (crash: SIGABRT)
! expected: runs to completion (the host run does)
! observed: device: fail crash: SIGABRT; host reference (afar/cce19) checksum=0
! Legal OpenMP 5.2: offload.engine.rules accepts it (offload.engine.prerun.check, rerun: with the
!   race rule and the restriction checks); NVHPC is no witness: it rejects it
!   (NVFORTRAN-S-0034-Syntax error at or near :); the check's other
!   witness, the AFAR flang front end, is the compiler under test and is not counted; no gfortran
!   or gcc is a legality witness.
program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 16, m = 8
  integer, allocatable :: ia(:)
  integer :: ib(n)
  integer :: ic(n, m)
  integer :: o1(n)
  integer :: i, j
  integer(8) :: cs
  allocate(ia(n))
  do i = 1, n
    ia(i) = mod(i * 24 + 48, 30011) - 5205
  end do
  do i = 1, n
    ib(i) = mod(i * 24 + 3, 1009) - 72
  end do
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 9 * j) * 27 + 40, 211) - 68
    end do
  end do
  o1 = 0
  ! fuzz: kernels
  !$omp target enter data map(to: ia, ib, ic, o1)
  !$omp target map(close, present, to: ic)
  !$omp end target
  ! fuzz: checksum
  cs = 0
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o1(i), 8), 2147483629_8)
  end do
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', 0
end program fuzz_prog
! site:
! title: AFAR offload runtime at HSA_XNACK=1: map(close, ...) breaks presence lookup and device access (abort, memory fault)
! same_as: fuzz/s1-9443-afar
! end site
