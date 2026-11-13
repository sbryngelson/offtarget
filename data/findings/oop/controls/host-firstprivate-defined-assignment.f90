! control for oop-assignfinal-firstprivate: the same firstprivate(x) on a host parallel construct (one change: parallel for target)
! fortran-oop assignfinal/firstprivate (OpenMP 5.2, free-form Fortran):
! firstprivate(x) on a target construct initializes the new list item as if by the type-bound
!   defined assignment
! spec: OpenMP 5.2 §5.4.4 p.113 l.3-6 (firstprivate initialization by a compatible type-bound defined
!   assignment); OpenMP 5.2 §1.2.6 p.19 l.1-3 (type-bound procedures accessed in a target region
!   appear in a declare target directive)
! legality: defined
! expected (computed by compliance/oop_gen.py): r1= 1, r2= 5
module oop_m
  implicit none
  integer, parameter :: n = 64
  type ct
    integer :: v = 0
    integer :: copies = 0
  contains
    procedure :: asg => ct_asg
    generic :: assignment(=) => asg
  end type ct
contains
  subroutine ct_asg(a, b)
    !$omp declare target
    class(ct), intent(inout) :: a
    class(ct), intent(in) :: b
    a%v = b%v
    a%copies = b%copies + 1
  end subroutine ct_asg
end module oop_m

program oop
  use omp_lib
  use oop_m
  implicit none
  integer :: host_flag
  logical :: ok
  integer :: r1, r2
  type(ct) :: x
  host_flag = 1
  !$omp target map(from: host_flag)
  host_flag = merge(1, 0, omp_is_initial_device())
  !$omp end target
  x%v = 5
  x%copies = 0
  !$omp parallel firstprivate(x) num_threads(1)
  r1 = x%copies
  r2 = x%v
  !$omp end parallel
  ok = .true.
  ok = ok .and. (r1 == 1)
  ok = ok .and. (r2 == 5)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0)', 'r2= ', r2
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
