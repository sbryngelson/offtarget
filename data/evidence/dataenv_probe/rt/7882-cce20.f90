! Minimized by compliance.fuzz_min from fuzz seed 7882 (fuzz-3).
! toolchain: cce20 (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: run_error (exit_status)
! expected: runs to completion (the host run does)
! observed: device: fail exit_status: 1; host reference (afar) checksum=0
! Legal OpenMP 5.2: passes offload.engine.rules, gfortran -std=f2008 and AFAR flang's frontend.
!@file fuzz_dmod.f90
module fuzz_dmod
  implicit none
  integer, parameter :: nm = 48
  type :: pair_t
  end type pair_t
contains
end module fuzz_dmod
!@file fuzz_prog.f90
program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  use fuzz_dmod
  implicit none
  integer, parameter :: n = 48, m = 8
  type :: nd_t
  end type nd_t
  type :: rec_t
    type(nd_t) :: nd
  end type rec_t
  type :: el_t
  end type el_t
  type(rec_t) :: dr
  type(el_t) :: ds(n)
  integer, allocatable :: ia(:)
  integer, allocatable :: ib(:)
  integer :: ic(n, m)
  integer, allocatable :: as1
  complex(8), allocatable :: xz8(:)
  character(len=4), allocatable :: xc(:)
  integer(2), allocatable :: xk2(:)
  character(len=8) :: xs
  integer :: i, j, hf1
  integer(8) :: cs
  allocate(ia(n))
  allocate(ib(n))
  allocate(xz8(n))
  allocate(xc(n))
  allocate(xk2(n))
  allocate(as1)
  do i = 1, n
    ia(i) = mod(i * 40 + 9, 1009) - 167
  end do
  do i = 1, n
    ib(i) = mod(i * 43 + 19, 101) - 15
  end do
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 4 * j) * 24 + 28, 30011) - 10854
    end do
  end do
  do i = 1, n
    xz8(i) = cmplx(mod(i * 7 + 9, 97) - 16, mod(i * 9, 17) - 8, 8)
    xc(i) = achar(65 + mod(i * 33, 26)) // achar(97 + mod(i + 46, 26)) // achar(48 + mod(i, 10)) // &
        & '#'
    xk2(i) = int(mod(i * 30 + 35, 16001) - 8000, 2)
  end do
  xs = 'eTgfQpof'
  as1 = 35
  hf1 = 0
  ! fuzz: kernels
  !$omp target data map(to: as1, ia, ib, ic, xc, xk2, xs, xz8) map(tofrom: dr, ds)
    !$omp target map(present, tofrom: xc) map(tofrom: hf1)
      hf1 = merge(1, 0, omp_is_initial_device())
    !$omp end target
  !$omp end target data
  ! fuzz: checksum
  cs = 0
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', max(hf1, 0)
end program fuzz_prog
