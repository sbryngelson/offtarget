! control for oop-poly-dispatch: the same program; one change: the region calls the binding on the TYPE objects
! (statically resolved) instead of through area_of's CLASS(shape) dummy
! fortran-oop poly/dispatch (OpenMP 5.2, free-form Fortran):
! dynamic dispatch of a deferred binding (abstract type) through a CLASS(shape) dummy on the
!   device
! spec: OpenMP 5.2 §1.2.6 p.19 l.1-3 (type-bound procedures accessed in a target region appear in a
!   declare target directive); OpenMP 5.2 §7.8.1 p.205-207 (declare target, procedures)
! legality: defined
! expected (computed by compliance/oop_gen.py): r1= 29
module oop_m
  implicit none
  integer, parameter :: n = 64
  type, abstract :: shape
    integer :: id = 0
  contains
    procedure(area_if), deferred :: area
  end type shape
  abstract interface
    integer function area_if(s)
      import :: shape
      class(shape), intent(in) :: s
    end function area_if
  end interface
  type, extends(shape) :: sq
    integer :: side = 0
  contains
    procedure :: area => sq_area
  end type sq
  type, extends(shape) :: rect
    integer :: w = 0, h = 0
  contains
    procedure :: area => rect_area
  end type rect
contains
  integer function sq_area(s)
    !$omp declare target
    class(sq), intent(in) :: s
    sq_area = s%side * s%side
  end function sq_area
  integer function rect_area(s)
    !$omp declare target
    class(rect), intent(in) :: s
    rect_area = s%w * s%h
  end function rect_area
  integer function area_of(s)
    !$omp declare target
    class(shape), intent(in) :: s
    area_of = s%area()
  end function area_of
end module oop_m

program oop
  use omp_lib
  use oop_m
  implicit none
  integer :: host_flag
  logical :: ok
  integer :: r1
  type(sq) :: q
  type(rect) :: rr
  host_flag = 1
  !$omp target map(from: host_flag)
  host_flag = merge(1, 0, omp_is_initial_device())
  !$omp end target
  q%side = 3
  rr%w = 4
  rr%h = 5
  !$omp target map(tofrom: q, rr) map(from: r1)
  r1 = q%area() + rr%area()
  !$omp end target
  ok = .true.
  ok = ok .and. (r1 == 29)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
