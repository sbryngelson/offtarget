! control for oop-assignfinal-final-dealloc: the family program oop-assignfinal-final-local (a non-allocatable local of
! the same finalizable type; no ALLOCATE/DEALLOCATE)
! fortran-oop assignfinal/final-local (OpenMP 5.2, free-form Fortran):
! a local object of a finalizable type in a declare target subroutine is finalized on return (the
!   final subroutine counts on the device)
! spec: Fortran 2018 7.5.6.3 (when finalization occurs); OpenMP 5.2 §1.2.6 p.19 (type-bound procedures
!   in declare target); OpenMP 5.2 §7.8.1 p.205-207 (declare target, procedures)
! legality: defined
! expected (computed by compliance/oop_gen.py): r1= 64, r2= 4160
module oop_m
  implicit none
  integer, parameter :: n = 64
  type ft
    integer :: v = 0
  contains
    final :: ft_fin
  end type ft
  integer :: fin_count = 0
  !$omp declare target to(fin_count)
contains
  subroutine ft_fin(o)
    !$omp declare target
    type(ft), intent(inout) :: o
    !$omp atomic update
    fin_count = fin_count + 1
  end subroutine ft_fin
  subroutine work(k, r)
    !$omp declare target
    integer, intent(in) :: k
    integer, intent(out) :: r
    type(ft) :: o
    o%v = k
    r = 2 * o%v
  end subroutine work
end module oop_m

program oop
  use omp_lib
  use oop_m
  implicit none
  integer :: host_flag
  logical :: ok
  integer :: r1, r2
  integer :: res(n), i
  host_flag = 1
  !$omp target map(from: host_flag)
  host_flag = merge(1, 0, omp_is_initial_device())
  !$omp end target
  fin_count = 0
  !$omp target update to(fin_count)
  !$omp target teams distribute parallel do map(tofrom: res)
  do i = 1, n
    call work(i, res(i))
  end do
  !$omp target update from(fin_count)
  r1 = fin_count
  r2 = sum(res)
  ok = .true.
  ok = ok .and. (r1 == 64)
  ok = ok .and. (r2 == 4160)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0)', 'r2= ', r2
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
