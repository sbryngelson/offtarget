! control for oop-section-element: the same program; one change: map(tofrom: v) (the whole array of structures, which
! maps every element's allocatable component through the default mapper) for the section v(2)%a(5:20)
! fortran-oop section/element (OpenMP 5.2, free-form Fortran):
! map(tofrom: v(2)%a(5:20)): a section of the allocatable component of an array element
! spec: OpenMP 5.2 §5.8.3 p.151 l.13 (structure elements and array sections are list items); §5.8.3
!   p.157 l.21-22
! legality: defined
! expected (computed by compliance/oop_gen.py): r1= 2880, r2= 2080
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
  type(vec) :: v(3)
  integer :: i, k
  host_flag = 1
  !$omp target map(from: host_flag)
  host_flag = merge(1, 0, omp_is_initial_device())
  !$omp end target
  do k = 1, 3
    allocate(v(k)%a(n))
    v(k)%n = n
    do i = 1, n
      v(k)%a(i) = i
    end do
  end do
  !$omp target teams distribute parallel do map(tofrom: v)
  do i = 5, 20
    v(2)%a(i) = v(2)%a(i) + 50
  end do
  r1 = sum(v(2)%a)
  r2 = sum(v(1)%a)
  ok = .true.
  ok = ok .and. (r1 == 2880)
  ok = ok .and. (r2 == 2080)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0)', 'r2= ', r2
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
