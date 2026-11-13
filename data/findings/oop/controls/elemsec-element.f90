! control (fortran-oop family program oop-elemsec-element, correct on every CCE in both modes)
! fortran-oop elemsec/element (OpenMP 5.2, free-form Fortran):
! map(tofrom: vk(5)): one element of an array of structures
! spec: OpenMP 5.2 §5.8.3 p.151 l.13 (structure elements and array sections are list items); §5.8.3
!   p.157 l.21-22; OpenMP 5.2 §5.8.3 p.151-155 (map clause)
! legality: defined
! expected (computed by compliance/oop_gen.py): r1= 610, r2= 40, r3= 0
module oop_m
  implicit none
  integer, parameter :: n = 64
  type dc
    integer :: g(20) = 0
    integer :: i = 0
  end type dc
end module oop_m

program oop
  use omp_lib
  use oop_m
  implicit none
  integer :: host_flag
  logical :: ok
  integer :: r1, r2, r3
  type(dc) :: vk(5)
  integer :: l
  host_flag = 1
  !$omp target map(from: host_flag)
  host_flag = merge(1, 0, omp_is_initial_device())
  !$omp end target
  !$omp target map(tofrom: vk(5))
  do l = 1, 20
    vk(5)%g(l) = 20 + l
  end do
  vk(5)%i = 40
  !$omp end target
  r1 = sum(vk(5)%g)
  r2 = vk(5)%i
  r3 = sum(vk(4)%g)
  ok = .true.
  ok = ok .and. (r1 == 610)
  ok = ok .and. (r2 == 40)
  ok = ok .and. (r3 == 0)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0)', 'r2= ', r2
  print '(a,i0)', 'r3= ', r3
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
