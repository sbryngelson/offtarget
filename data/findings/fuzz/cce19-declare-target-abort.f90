! # Finding (leads): CCE 19 aborts at run time on a Fortran OpenMP program with a declare target construct
!
! - toolchains and modes that fail: cce19 (CCE 19.0.0), cce20 (CCE 20.0.2); modes: copy; -O2
! - build: ftn -fopenmp -O2
! - failure: crash
! - observed: `Memory access fault by GPU node-7 (Agent handle: 0x4ca220) on address 0x48e000. Reason: Unknown.` (killed by signal
!   6); identical signature on 2 of 2 failing cells
! - expected: compiles and prints `checksum= 1775055809` with `check=pass`
! - rule: a conforming program runs to completion: "If the extended-list argument is specified, the effect is as if an enter clause
!   was specified with the extended-list as its argument." (OpenMP 5.2 §7.8.1 p.206 l.9-10)
! - other families: afar (AFAR 24.3.0), afar244 (AFAR 24.4.0), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4), gcc (GCC 16.2.0) run the
!   file correctly in unified mode (site rows, check case site-fuzz--cce19-declare-target-abort); cce21 (CCE 21.0.3), cce21_4 (CCE
!   21.0.4) fail it another way in copy mode, e.g. `ACC: libcrayacc/acc_hw_amd.c:1496 CRAY_ACC_ERROR -  hipStreamSynchronize
!   returned hipErrorIllegalAddress: 'an illegal memory access was encountered' f`
! - programs (1): g1x0-o3:1034
! - legality: the rules engine accepts it (offload.engine.prerun.rules_witness); afar, afar244, cce19 run it correctly in the
!   confirmer's runs (tools/confirm.py case); the legality verdict is computed (tools/review/review.py mechanical)
! - releases: CCE 19.0.0 and 20.0.2 fails it the same way on MI300A copy and runs it correctly on MI300A unified; CCE 21.0.3 and
!   21.0.4 fails it another way on MI300A copy and runs it correctly on MI300A unified
module fuzz_amod
  implicit none
contains
  integer function ga1(x)
    !$omp declare target
    integer, intent(in) :: x
    ga1 = 0
  end function ga1
end module fuzz_amod
!@file fuzz_prog.f90
program fuzz_prog
  use omp_lib, only: omp_get_thread_num, omp_is_initial_device
  use fuzz_amod, only: ga1
  implicit none
  integer, parameter :: n = 16, m = 2
  type :: nd_t
    integer :: k(n)
    integer, allocatable :: o1(:)
  end type nd_t
  type :: rec_t
    integer :: a(n)
    integer :: s
    integer, allocatable :: q(:)
    type(nd_t) :: nd
  end type rec_t
  type(rec_t) :: dr
  integer :: ia(n)
  integer :: ib(n)
  integer :: ic(n, m)
  double precision, allocatable :: xr8(:)
  complex(8) :: xz8(n)
  logical :: xl(n)
  character(len=4) :: xc(n)
  character(len=8) :: xs
  logical :: r1a
  integer :: i, j, jj, p1, p2, hf1, acc1, t1
  integer(8) :: cs
  allocate(xr8(n))
  allocate(dr%q(n))
  allocate(dr%nd%o1(n))
  do i = 1, n
    ia(i) = mod(i * 46 + 25, 1009) - 201
  end do
  do i = 1, n
    ib(i) = mod(i * 15 + 45, 97) - 38
  end do
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 7 * j) * 15 + 13, 30011) - 2145
    end do
  end do
  do i = 1, n
    xr8(i) = real(mod(i * 9 + 35, 101) - 27, 8) * 0.5d0
    xz8(i) = cmplx(mod(i * 60 + 38, 1009) - 218, mod(i * 38, 17) - 8, 8)
    xl(i) = mod(i * 47 + 17, 3) == 0
    xc(i) = achar(65 + mod(i * 28, 26)) // achar(97 + mod(i + 36, 26)) // achar(48 + mod(i, 10)) // &
        & '#'
    dr%a(i) = mod(i * 15 + 50, 1009) - 58
    dr%nd%k(i) = mod(i * 9 + 16, 1009) - 424
    dr%q(i) = mod(i * 56 + 49, 97) - 33
  end do
  xs = 'nrvAwMCw'
  dr%s = 32
  dr%nd%o1 = 0
  p1 = -5
  p2 = -6
  hf1 = 0
  r1a = .true.
  ! fuzz: kernels
  !$omp target map(tofrom: hf1)
      if (omp_get_thread_num() == 0) then
        hf1 = merge(1, 0, omp_is_initial_device())
        do i = 1, n
          dr%nd%o1(i) = mod((ga1(16) * 7), 13)
        end do
      end if
  !$omp end target
  ! fuzz: checksum
  cs = 0
  cs = modulo(cs * 31_8 + merge(1_8, 0_8, r1a), 2147483629_8)
  do i = 1, n
    cs = modulo(cs * 31_8 + int(dr%nd%o1(i), 8), 2147483629_8)
  end do
  print '(a,i0)', 'checksum= ', cs
  print '(a,i0,a,a)', 'RESULT ran_on_host=', max(hf1, 0), ' check=', merge('pass', 'fail', cs == 1775055809_8)
end program fuzz_prog

! site:
! title: CCE: abort with declare target
! summary: CCE 19 aborts at run time on a Fortran OpenMP program with a declare target construct.
! end site
