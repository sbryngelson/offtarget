! Minimized by compliance.fuzz_min from fuzz seed 9443 (fuzz-3).
! toolchain: afar (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: run_error (crash)
! expected: runs to completion (the host run does)
! observed: device: fail crash: SIGABRT; host reference (cce21) checksum=0
! Legal OpenMP 5.2: passes offload.engine.rules, gfortran -std=f2008 and AFAR flang's frontend.
!@file fuzz_dmod.f90
module fuzz_dmod
  implicit none
  integer, parameter :: nm = 100
  integer, private :: kk
  type :: gp_t
  end type gp_t
  type :: mt_t
  end type mt_t
  type :: pair_t
  end type pair_t
  integer :: gtab(nm) = [(mod(kk * 59 + 7, 1009) - 400, kk = 1, nm)]
  type(gp_t) :: gs
end module fuzz_dmod
!@file fuzz_prog.f90
program fuzz_prog
  use fuzz_dmod
  implicit none
  integer, parameter :: n = 100, m = 8
  type :: rec_t
  end type rec_t
  type(rec_t) :: dr
  type(mt_t) :: ms
  integer :: ia(n)
  integer :: ib(n)
  integer, allocatable :: ic(:, :)
  integer, allocatable :: as1
  real(4), allocatable :: xr4(:)
  complex(4), allocatable :: xz4(:)
  logical, allocatable :: xl(:)
  integer(1) :: xk1(n)
  integer(8) :: xk8(n)
  integer :: i, j
  integer(8) :: cs
  allocate(ic(n, m))
  allocate(xr4(n))
  allocate(xz4(n))
  allocate(xl(n))
  allocate(as1)
  do i = 1, n
    ia(i) = mod(i * 8 + 30, 211) - 50
  end do
  do i = 1, n
    ib(i) = mod(i * 58 + 16, 101) - 33
  end do
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 2 * j) * 57 + 27, 211) - 91
    end do
  end do
  do i = 1, n
    xr4(i) = real(mod(i * 55 + 22, 97) - 39, 4) * 0.5
    xz4(i) = cmplx(mod(i * 57 + 38, 1009) - 56, mod(i * 38, 17) - 8, 4)
    xl(i) = mod(i * 14 + 27, 3) == 0
    xk1(i) = int(mod(i * 17 + 16, 127), 1)
    xk8(i) = int(i, 8) * 1000000007_8 + int(16, 8)
  end do
  as1 = 11
  ! fuzz: kernels
  !$omp target data map(to: as1, dr, ia, ib, ic, ms, xk1, xk8, xl, xr4, xz4)
    !$omp target map(close, present, to: xk1)
    !$omp end target
  !$omp end target data
  ! fuzz: checksum
  cs = 0
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', 0
end program fuzz_prog
