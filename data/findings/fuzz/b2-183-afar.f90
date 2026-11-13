! Minimized by compliance.fuzz_min from fuzz seed 183 (fuzz-3, base group derived).
! toolchain: afar (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: run_error (crash: SIGABRT): OFFLOAD ERROR: memory access fault ... Write access to a read-only page
! expected: RESULT checksum=0 (host reference cce19 and sequential elision; AFAR at HSA_XNACK=0 prints it)
! observed: GPU memory access fault at HSA_XNACK=1, THP on and off (flux, idle node); agrees at HSA_XNACK=0
! The derived types are left over (unused); hand-reduced: data/findings/afar-xnack1-atomic-min-nested-parallel.f90
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
  type :: nd_t
  end type nd_t
  type :: rec_t
    type(nd_t) :: nd
  end type rec_t
  type(rec_t) :: dr
  integer, allocatable :: o1(:, :)
  integer :: i, j, r1a
  integer(8) :: cs
  allocate(o1(n, m))
  o1 = 0
  r1a = 7
  ! fuzz: kernels
  !$omp target teams distribute map(always, tofrom: r1a)
  do i = 1, n
    !$omp parallel do
    do j = 1, m
      o1(i, j) = 0
      !$omp atomic
      r1a = min(r1a, mod(i, n))
    end do
    !$omp end parallel do
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
! title: amdflang at HSA_XNACK=1: atomic min in a parallel do nested in target teams distribute with an allocatable array faults
! + (write to a read-only page)
! same_as: afar-xnack1-atomic-min-nested-parallel
! end site
