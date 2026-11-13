! Minimized by compliance.fuzz_min from fuzz seed 9 (fuzz-3).
! toolchain: cce21 (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: run_error (crash: SIGSEGV)
! expected: runs to completion (the host run does)
! observed: device: fail crash: SIGSEGV; host reference (elision) checksum=185626446
! Legal OpenMP 5.2: offload.engine.prerun.check accepts it (rerun: offload.engine.rules with the
!   race rule and the restriction checks, and the AFAR flang front end, not under test here); no
!   compiler under test, gfortran or gcc is a legality witness.
! also fails on: afar
program fuzz_prog
  use omp_lib, only: omp_get_default_device, omp_is_initial_device
  implicit none
  integer, parameter :: n = 200, m = 8
  type :: rec_t
    integer :: a(n)
    integer, allocatable :: q(:)
    integer, pointer :: pc(:)
  end type rec_t
  type(rec_t) :: dr
  integer, allocatable, target :: ia(:)
  integer :: ib(n)
  integer, allocatable :: ic(:, :)
  integer, pointer :: o1(:, :)
  integer, pointer :: o2(:)
  integer, target :: o1t(n, m)
  integer, target :: o2t(n)
  integer, target :: tgc(n)
  integer :: i, j, jj, p1, p2, r1a, r1b, hf1, r2a, dev
  integer(8) :: cs
  allocate(ia(n))
  allocate(ic(n, m))
  allocate(dr%q(n))
  dr%pc => tgc
  o1 => o1t
  o2 => o2t
  do i = 1, n
    ia(i) = mod(i * 4 + 15, 1009) - 376
  end do
  do i = 1, n
    ib(i) = mod(i * 3 + 7, 30011) - 3238
  end do
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 1 * j) * 60 + 5, 101) - 34
    end do
  end do
  do i = 1, n
    dr%a(i) = mod(i * 35 + 38, 97) - 36
    dr%q(i) = mod(i * 10 + 45, 211) - 86
    tgc(i) = mod(i * 53 + 43, 1009) - 396
  end do
  o1 = 0
  o2 = 0
  p1 = -7
  p2 = 9
  r1a = 2
  r1b = 3
  hf1 = 0
  r2a = 4
  dev = omp_get_default_device()
  ! fuzz: kernels
  call kp2(ia, ib, ic, o2, dr)
  ! fuzz: checksum
  cs = 0
  cs = modulo(cs * 31_8 + int(r1a, 8), 2147483629_8)
  cs = modulo(cs * 31_8 + int(r1b, 8), 2147483629_8)
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o1t(i, j), 8), 2147483629_8)
    end do
  end do
  cs = modulo(cs * 31_8 + int(r2a, 8), 2147483629_8)
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o2t(i), 8), 2147483629_8)
  end do
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', max(hf1, 0)
contains
  subroutine kp1(ib, o1, dr, zopt)
    integer, intent(in) :: ib(n)
    integer, intent(inout) :: o1(:, :)
    type(rec_t), intent(inout) :: dr
    integer, intent(in), optional :: zopt(:)
    integer :: i, j, jj
  end subroutine kp1
  subroutine kp2(ia, ib, ic, o2, dr, zopt)
    integer, allocatable, intent(inout) :: ia(:)
    integer, intent(in) :: ib(n)
    integer, allocatable, intent(inout) :: ic(:, :)
    integer, intent(inout) :: o2(:)
    type(rec_t), intent(inout) :: dr
    integer, intent(in), optional :: zopt(:)
    integer :: i, j, jj
    !$omp target map(to: zopt)
      !$omp teams loop num_teams(64)
      do i = 1, n
      end do
    !$omp end target
  end subroutine kp2
end program fuzz_prog
! site:
! title: ftn: map(to: zopt) of an absent optional dummy in an internal subroutine crashes the run (SIGSEGV)
! same_as: fuzz/b3-190-cce21
! end site
