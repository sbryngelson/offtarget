! control for oop-alloccomp-parent-and-comp: the same program; one change: no map(to: x) beside map(tofrom: x%a)
! fortran-oop alloccomp/parent-and-comp (OpenMP 5.2, free-form Fortran):
! map(to:) of the structure and map(tofrom:) of its allocatable component on one construct
! spec: OpenMP 5.2 §5.8.3 p.151-155 (map clause); OpenMP 5.2 §5.8.3 p.151 l.29-37 (components from the
!   predefined default mapper); OpenMP 6.0 §B.5 p.909 l.35-37 (5.0: mapping of allocatable and
!   pointer components); OpenMP 5.2 §5.8.3 p.156 l.6-7
! legality: defined
! expected (computed by compliance/oop_gen.py): r1= 2528
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
    x%a(i) = x%a(i) + 7
  end do
  r1 = sum(x%a)
  ok = .true.
  ok = ok .and. (r1 == 2528)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
