! control for oop-poly-select-type: the same calls on the host (one change: no target construct)
! fortran-oop poly/select-type (OpenMP 5.2, free-form Fortran):
! a declare target subroutine with a CLASS(base_t) dummy and SELECT TYPE, called on the device
!   with mapped non-polymorphic objects of three types
! spec: OpenMP 5.2 §1.2.6 p.19 l.1-3 (type-bound procedures accessed in a target region appear in a
!   declare target directive); OpenMP 5.2 §7.8.1 p.205-207 (declare target, procedures); OpenMP 5.2
!   §5.3 p.107 l.17-19 (SELECT TYPE in OpenMP regions); Fortran 2018 11.1.11 (SELECT TYPE)
! legality: defined
! expected (computed by compliance/oop_gen.py): r1= 10, r2= 100, r3= -1
module oop_m
  implicit none
  integer, parameter :: n = 64
  type base_t
    integer :: a = 0
  end type base_t
  type, extends(base_t) :: ext1
    integer :: u = 0
  end type ext1
  type, extends(base_t) :: ext2
    integer :: v = 0
  end type ext2
contains
  subroutine bump(s)
    !$omp declare target
    class(base_t), intent(inout) :: s
    select type (s)
      type is (ext1)
        s%u = s%u + 10
      type is (ext2)
        s%v = s%v + 100
      class default
        s%a = -1
    end select
  end subroutine bump
end module oop_m

program oop
  use omp_lib
  use oop_m
  implicit none
  integer :: host_flag
  logical :: ok
  integer :: r1, r2, r3
  type(ext1) :: e1
  type(ext2) :: e2
  type(base_t) :: b0
  host_flag = 1
  !$omp target map(from: host_flag)
  host_flag = merge(1, 0, omp_is_initial_device())
  !$omp end target
  call bump(e1)
  call bump(e2)
  call bump(b0)
  r1 = e1%u
  r2 = e2%v
  r3 = b0%a
  ok = .true.
  ok = ok .and. (r1 == 10)
  ok = ok .and. (r2 == 100)
  ok = ok .and. (r3 == -1)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0)', 'r2= ', r2
  print '(a,i0)', 'r3= ', r3
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
