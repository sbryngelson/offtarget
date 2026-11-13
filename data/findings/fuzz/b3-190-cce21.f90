! Minimized by compliance.fuzz_min from fuzz seed 190 (fuzz-3).
! toolchain: cce21 (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: run_error (crash: SIGSEGV)
! expected: runs to completion (the host run does)
! observed: device: fail crash: SIGSEGV; host reference (afar) checksum=0
! Legal OpenMP 5.2: offload.engine.prerun.check accepts it (rerun: offload.engine.rules with the
!   race rule and the restriction checks, and the AFAR flang front end, not under test here); no
!   compiler under test, gfortran or gcc is a legality witness.
module fuzz_mod
  implicit none
contains
  integer function g1(x, y)
    !$omp declare target
    integer, intent(in) :: x, y
    g1 = 0
  end function g1
end module fuzz_mod
program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  use fuzz_mod, only: g1
  implicit none
  integer, parameter :: n = 24, m = 3
  type :: rec_t
  end type rec_t
  type(rec_t) :: dr
  integer, allocatable, target :: ia(:)
  integer, target :: ib(n)
  integer, allocatable :: as1
  integer, allocatable :: o1(:, :)
  integer :: o2(n, m)
  integer :: i, j, jj
  integer(8) :: cs
  allocate(ia(n))
  allocate(o1(n, m))
  allocate(as1)
  do i = 1, n
    ia(i) = mod(i * 19 + 10, 101) - 23
  end do
  do i = 1, n
    ib(i) = mod(i * 32 + 7, 97) - 39
  end do
  as1 = 46
  o1 = 0
  o2 = 0
  ! fuzz: kernels
  call kp1(as1, ia, o1, dr)
  ! fuzz: checksum
  cs = 0
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o1(i, j), 8), 2147483629_8)
    end do
  end do
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o2(i, j), 8), 2147483629_8)
    end do
  end do
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', 0
contains
  subroutine kp1(as1, ia, o1, dr, zopt)
    integer, intent(inout) :: as1
    integer, intent(in) :: ia(n)
    integer, intent(inout) :: o1(n, m)
    type(rec_t), intent(inout) :: dr
    integer, intent(in), optional :: zopt(:)
    integer :: i, j, jj, t1
    !$omp target private(t1) map(to: zopt)
    do i = 1, n
      do j = 1, m
        t1 = g1((-10), as1)
      end do
    end do
    !$omp end target
  end subroutine kp1
  subroutine kp2(ib, o2)
    integer, intent(inout) :: ib(n)
    integer, intent(inout) :: o2(n, m)
    integer :: i, j, jj
  end subroutine kp2
end program fuzz_prog
! site:
! title: ftn: map(to: zopt) of an absent optional dummy in an internal subroutine crashes the run (SIGSEGV)
! control: ../vendor/checks/src/fuzz/control/fuzz-b3-190-cce21-control.f90 map(to: zopt) removed (the absent dummy is not named
! + in a map
! + clause)
! same_as: catalog/afar-flang-absent-optional-target-crash
! end site
