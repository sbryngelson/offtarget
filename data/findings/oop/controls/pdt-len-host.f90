! control for oop-pdt-len: the same program; one change: no target construct (the PDT work runs on the host)
! fortran-oop pdt/len (OpenMP 5.2, free-form Fortran):
! a derived type with a length type parameter (constant), its value read on the device
! spec: OpenMP 5.2 §5.8.3 p.151-155 (map clause); OpenMP 5.2 §5.8.3 p.155 l.5-7
! legality: defined
! expected (computed by compliance/oop_gen.py): r1= 16, r2= 1496
module oop_m
  implicit none
  integer, parameter :: n = 64
  type lv(m)
  integer, len :: m
  integer :: a(m)
  end type lv
end module oop_m

program oop
  use omp_lib
  use oop_m
  implicit none
  integer :: host_flag
  logical :: ok
  integer :: r1, r2
  type(lv(16)) :: x
  integer :: i
  host_flag = 1
  !$omp target map(from: host_flag)
  host_flag = merge(1, 0, omp_is_initial_device())
  !$omp end target
  do i = 1, 16
    x%a(i) = i
  end do
  r1 = x%m
  do i = 1, x%m
    x%a(i) = x%a(i) * x%a(i)
  end do
  r2 = sum(x%a)
  ok = .true.
  ok = ok .and. (r1 == 16)
  ok = ok .and. (r2 == 1496)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0)', 'r2= ', r2
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
