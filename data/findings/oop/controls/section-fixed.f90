! control (fortran-oop family program oop-section-fixed, correct on every CCE in both modes)
! fortran-oop section/fixed (OpenMP 5.2, free-form Fortran):
! map(tofrom: s%b(17:48)): a section of a fixed-size array component
! spec: OpenMP 5.2 §5.8.3 p.151 l.13 (structure elements and array sections are list items); §5.8.3
!   p.157 l.21-22; OpenMP 5.2 §13.8 p.286 l.27-28 (other referenced elements of a mapped structure
!   element are mapped too)
! legality: defined
! expected (computed by compliance/oop_gen.py): r1= 3120
module oop_m
  implicit none
  integer, parameter :: n = 64
  type fs
    integer :: b(n) = 0
    integer :: k = 0
  end type fs
end module oop_m

program oop
  use omp_lib
  use oop_m
  implicit none
  integer :: host_flag
  logical :: ok
  integer :: r1
  type(fs) :: s
  integer :: i
  host_flag = 1
  !$omp target map(from: host_flag)
  host_flag = merge(1, 0, omp_is_initial_device())
  !$omp end target
  do i = 1, n
    s%b(i) = i
  end do
  !$omp target teams distribute parallel do map(tofrom: s%b(17:48))
  do i = 17, 48
    s%b(i) = 2 * s%b(i)
  end do
  r1 = sum(s%b)
  ok = .true.
  ok = ok .and. (r1 == 3120)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
