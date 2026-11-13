! control (fortran-oop family program oop-tbp-override, correct on every CCE in both modes)
! fortran-oop tbp/override (OpenMP 5.2, free-form Fortran):
! an overridden binding called on objects of the base and the extended type, and through the
!   parent component
! spec: OpenMP 5.2 §1.2.6 p.19 l.1-3 (type-bound procedures accessed in a target region appear in a
!   declare target directive); OpenMP 5.2 §7.8.1 p.205-207 (declare target, procedures)
! legality: defined
! expected (computed by compliance/oop_gen.py): r1= 3, r2= 405, r3= 4
module oop_m
  implicit none
  integer, parameter :: n = 64
  type base_t
    integer :: a = 0
  contains
    procedure :: val => base_val
  end type base_t
  type, extends(base_t) :: ext_t
    integer :: b = 0
  contains
    procedure :: val => ext_val
  end type ext_t
contains
  integer function base_val(s)
    !$omp declare target
    class(base_t), intent(in) :: s
    base_val = s%a
  end function base_val
  integer function ext_val(s)
    !$omp declare target
    class(ext_t), intent(in) :: s
    ext_val = s%a * 100 + s%b
  end function ext_val
end module oop_m

program oop
  use omp_lib
  use oop_m
  implicit none
  integer :: host_flag
  logical :: ok
  integer :: r1, r2, r3
  type(base_t) :: b0
  type(ext_t) :: e
  host_flag = 1
  !$omp target map(from: host_flag)
  host_flag = merge(1, 0, omp_is_initial_device())
  !$omp end target
  b0%a = 3
  e%a = 4
  e%b = 5
  !$omp target map(tofrom: b0, e) map(from: r1, r2, r3)
  r1 = b0%val()
  r2 = e%val()
  r3 = e%base_t%val()
  !$omp end target
  ok = .true.
  ok = ok .and. (r1 == 3)
  ok = ok .and. (r2 == 405)
  ok = ok .and. (r3 == 4)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0)', 'r2= ', r2
  print '(a,i0)', 'r3= ', r3
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
