! Minimized by compliance.fuzz_min from fuzz seed 61 (fuzz-3).
! toolchain: cce20 (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: wrong_code
! expected: the host reference checksum (host reference (elision) checksum=234479309)
! observed: device checksum=1451519883 ran_on_host=0
! Legal OpenMP 5.2: offload.engine.prerun.check accepts it (rerun: offload.engine.rules with the
!   race rule and the restriction checks, and the AFAR flang front end, not under test here); no
!   compiler under test, gfortran or gcc is a legality witness.
! also fails on: cce19, cce21
program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 200, m = 3
  type :: rec_t
  end type rec_t
  type(rec_t) :: dr
  integer, allocatable :: ia(:)
  integer, allocatable :: ib(:)
  integer, allocatable :: ic(:, :)
  integer :: o1(n)
  integer :: o2(n)
  integer, allocatable :: o3(:)
  integer :: i, j, p1, r3a, hf3
  integer(8) :: cs
  allocate(ia(n))
  allocate(ib(n))
  allocate(ic(n, m))
  allocate(o3(n))
  do i = 1, n
    ia(i) = mod(i * 25 + 45, 97) - 25
  end do
  do i = 1, n
    ib(i) = mod(i * 25 + 39, 211) - 4
  end do
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 2 * j) * 60 + 25, 101) - 8
    end do
  end do
  o1 = 0
  o2 = 0
  o3 = 0
  p1 = 6
  r3a = 45
  hf3 = 0
  ! fuzz: kernels
  call kp2(ib, o1, o2, o3, dr, p1)
  ! fuzz: checksum
  cs = 0
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o1(i), 8), 2147483629_8)
  end do
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o2(i), 8), 2147483629_8)
  end do
  cs = modulo(cs * 31_8 + int(r3a, 8), 2147483629_8)
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o3(i), 8), 2147483629_8)
  end do
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', max(hf3, 0)
contains
  subroutine kp1(ia, ic, o1, dr)
    integer, intent(inout) :: ia(n)
    integer, intent(inout) :: ic(n, m)
    integer, intent(inout) :: o1(n)
    type(rec_t), intent(inout) :: dr
  end subroutine kp1
  subroutine kp2(ib, o1, o2, o3, dr, p1)
    integer, intent(inout) :: ib(n)
    integer, intent(inout) :: o1(n)
    integer, intent(inout) :: o2(:)
    integer, intent(inout) :: o3(n)
    type(rec_t), intent(inout) :: dr
    integer, value :: p1
    !$omp taskgroup task_reduction(+: r3a)
      !$omp target map(tofrom: hf3) in_reduction(+: r3a)
        hf3 = merge(1, 0, omp_is_initial_device())
        do i = 1, n
          o3(i) = 9973
        end do
      !$omp end target
    !$omp end taskgroup
  end subroutine kp2
end program fuzz_prog
! site:
! title: ftn: a target construct with in_reduction in an internal subroutine loses the writes to an implicitly mapped dummy array
! control: ../vendor/checks/src/fuzz/control/fuzz-b3-61-cce20-control.f90 the taskgroup/task_reduction and the in_reduction
! + clause removed
! end site
! spec (requirement): an array that a target region references and no clause names is mapped tofrom, and an in_reduction clause
!   on a target construct maps the reduction list item tofrom with the always modifier, so the writes to the other arrays reach
!   the host.
! "If a variable is not a scalar then it is treated as if it had appeared in a map clause with a map-type of tofrom." (5.2
!   §5.8.1 p.149 l.4-5)
! "If a variable is the base variable of a list item in an in_reduction clause on a target construct then it is treated as if
!   the list item had appeared in a map clause with a map-type of tofrom and a map-type-modifier of always." (5.2 §5.8.1 p.148
!   l.15-17)
! spec (this program): the target region in an internal subroutine, with in_reduction(+: r3a) and map(tofrom: hf3), stores 9973
!   in the dummy array o3; CCE 19, 20 and 21 lose those writes (checksum differs from the host's), and the program is correct when
!   taskgroup, task_reduction and in_reduction are removed.
