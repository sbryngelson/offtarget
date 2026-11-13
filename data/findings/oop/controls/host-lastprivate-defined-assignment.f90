! control for oop-assignfinal-lastprivate: the same parallel do lastprivate(w) on the host (one change: no enclosing target)
! fortran-oop assignfinal/lastprivate (OpenMP 5.2, free-form Fortran):
! lastprivate(w) of a parallel do in a target region: the original is updated as if by the
!   type-bound defined assignment
! spec: OpenMP 5.2 §5.4.5 p.115 l.24-25 (lastprivate update by a type-bound defined assignment); OpenMP
!   5.2 §1.2.6 p.19 l.1-3 (type-bound procedures accessed in a target region appear in a declare
!   target directive)
! legality: defined
! expected (computed by compliance/oop_gen.py): r1= 64, r2= 1
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
  type(ct) :: w
  integer :: i
  host_flag = 1
  !$omp target map(from: host_flag)
  host_flag = merge(1, 0, omp_is_initial_device())
  !$omp end target
  w%v = -1
  w%copies = 0
  !$omp parallel do lastprivate(w)
  do i = 1, n
    w%v = i
    w%copies = 0
  end do
  r1 = w%v
  r2 = w%copies
  ok = .true.
  ok = ok .and. (r1 == 64)
  ok = ok .and. (r2 == 1)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0)', 'r2= ', r2
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
