! control for oop-alloccomp-whole: the same program; one change: map(tofrom: x, x%a) (the component listed) for
! map(tofrom: x) (the component mapped by the predefined default mapper)
! fortran-oop alloccomp/whole (OpenMP 5.2, free-form Fortran):
! map(tofrom:) of a structure with an allocatable array component: the component's data is mapped
!   with it (deep copy)
! spec: OpenMP 5.2 §5.8.3 p.151 l.29-37 (components from the predefined default mapper); OpenMP 6.0 §B.5
!   p.909 l.35-37 (5.0: mapping of allocatable and pointer components); OpenMP 5.2 §5.8.2 p.150
!   (predefined default mapper)
! legality: defined
! expected (computed by compliance/oop_gen.py): r1= 10336, r2= 256
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
  integer :: r1, r2
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
  !$omp target teams distribute parallel do map(tofrom: x, x%a)
  do i = 1, n
    x%a(i) = 3 * x%a(i) + x%n
  end do
  r1 = sum(x%a)
  r2 = x%a(n)
  ok = .true.
  ok = ok .and. (r1 == 10336)
  ok = ok .and. (r2 == 256)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0)', 'r2= ', r2
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
