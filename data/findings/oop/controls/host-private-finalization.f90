! control for oop-assignfinal-final-private: private(x) on a host parallel construct of one thread (one change: parallel for target)
! fortran-oop assignfinal/final-private (OpenMP 5.2, free-form Fortran):
! private(x) of a finalizable type on a target construct: the private copy is finalized at the end
!   of the region
! spec: OpenMP 5.2 §5.3 p.107 l.20-22 (finalization of a privatized list item at the end of the region);
!   Fortran 2018 7.5.6.3 (when finalization occurs); OpenMP 5.2 §1.2.6 p.19 (type-bound procedures
!   in declare target)
! legality: defined
! expected (computed by compliance/oop_gen.py): r1= 1
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
end module oop_m

program oop
  use omp_lib
  use oop_m
  implicit none
  integer :: host_flag
  logical :: ok
  integer :: r1
  type(ft) :: x
  host_flag = 1
  !$omp target map(from: host_flag)
  host_flag = merge(1, 0, omp_is_initial_device())
  !$omp end target
  fin_count = 0
  !$omp target update to(fin_count)
  !$omp parallel private(x) num_threads(1)
  x%v = 3
  !$omp end parallel
  r1 = fin_count
  ok = .true.
  ok = ok .and. (r1 == 1)
  print '(a,i0)', 'r1= ', r1
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program oop
