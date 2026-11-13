! control (fortran-oop family program oop-alloccomp-comp-only, correct on every CCE in both modes)
! fortran-oop alloccomp/comp-only (OpenMP 5.2, free-form Fortran):
! map(tofrom:) of the allocatable component alone
! spec: OpenMP 5.2 §5.8.3 p.151-155 (map clause); OpenMP 5.2 §13.8 p.286 l.27-28 (other referenced
!   elements of a mapped structure element are mapped too)
! legality: defined
! expected (computed by compliance/oop_gen.py): r1= 4160
module oop_m
  implicit none
  integer, parameter :: n = 64
  type vec
    integer :: n = 0
    integer, allocatable :: a(:)
  end type vec
end module oop_m

program oop
  use omp_lib
  use oop_m
  implicit none
  integer :: host_flag
  logical :: ok
  integer :: r1
  type(vec) :: x
  integer :: i
  host_flag = 1
  !$omp target map(from: host_flag)
  host_flag = merge(1, 0, omp_is_initial_device())
  !$omp end target
  allocate(x%a(n))
  x%n = n
  do i = 1, n
    x%a(i) = i
  end do
  !$omp target teams distribute parallel do map(tofrom: x%a)
  do i = 1, n
    x%a(i) = 2 * x%a(i)
  end do
  r1 = sum(x%a)
  ok = .true.
  ok = ok .and. (r1 == 4160)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
