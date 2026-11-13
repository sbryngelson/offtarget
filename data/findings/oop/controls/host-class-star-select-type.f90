! control for oop-unlimited-classify: the same calls on the host (one change: no target construct)
! fortran-oop unlimited/classify (OpenMP 5.2, free-form Fortran):
! a CLASS(*) function classifying array elements of two derived types in a target teams distribute
!   parallel do
! spec: OpenMP 5.2 §7.8.1 p.205-207 (declare target, procedures); OpenMP 5.2 §5.3 p.107 l.17-19 (SELECT
!   TYPE in OpenMP regions); Fortran 2018 11.1.11 (SELECT TYPE)
! legality: defined
! expected (computed by compliance/oop_gen.py): r1= 320
module oop_m
  implicit none
  integer, parameter :: n = 64
  type pt
    integer :: a = 0
  end type pt
  type qt
    integer :: b = 0
  end type qt
contains
  integer function code_of(x)
    !$omp declare target
    class(*), intent(in) :: x
    select type (x)
      type is (integer)
        code_of = 1
      type is (pt)
        code_of = 2
      type is (qt)
        code_of = 3
      class default
        code_of = 0
    end select
  end function code_of
end module oop_m

program oop
  use omp_lib
  use oop_m
  implicit none
  integer :: host_flag
  logical :: ok
  integer :: r1
  type(pt) :: ps(n)
  type(qt) :: qs(n)
  integer :: i, tot
  host_flag = 1
  !$omp target map(from: host_flag)
  host_flag = merge(1, 0, omp_is_initial_device())
  !$omp end target
  tot = 0
  do i = 1, n
    tot = tot + code_of(ps(i)) + code_of(qs(i))
  end do
  r1 = tot
  ok = .true.
  ok = ok .and. (r1 == 320)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
