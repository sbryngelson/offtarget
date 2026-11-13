! control (fortran-oop family program oop-pdt-kind, correct on every CCE in both modes)
! fortran-oop pdt/kind (OpenMP 5.2, free-form Fortran):
! a derived type with a kind type parameter (integer(8) components), map(tofrom:)
! spec: OpenMP 5.2 §5.8.3 p.151-155 (map clause); OpenMP 5.2 §5.8.3 p.155 l.5-7 (same type, type
!   parameters and rank)
! legality: defined
! expected (computed by compliance/oop_gen.py): r1= 8, r2= 36
module oop_m
  implicit none
  integer, parameter :: n = 64
  type kv(k)
  integer, kind :: k = 4
  integer(k) :: v(8)
  end type kv
end module oop_m

program oop
  use omp_lib
  use oop_m
  implicit none
  integer :: host_flag
  logical :: ok
  integer :: r1, r2
  type(kv(8)) :: x
  integer :: i
  host_flag = 1
  !$omp target map(from: host_flag)
  host_flag = merge(1, 0, omp_is_initial_device())
  !$omp end target
  do i = 1, 8
    x%v(i) = int(i, 8) * 1000000000_8
  end do
  !$omp target map(tofrom: x)
  do i = 1, 8
    x%v(i) = x%v(i) + i
  end do
  !$omp end target
  r1 = int(x%v(8) - 8000000000_8)
  r2 = int(mod(sum(x%v), 1000000_8))
  ok = .true.
  ok = ok .and. (r1 == 8)
  ok = ok .and. (r2 == 36)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0)', 'r2= ', r2
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
