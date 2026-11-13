module m
  implicit none
  type :: pt
    real(8) :: x, y
  end type
contains
  pure real(8) function f(v)
    !$omp declare target
    real(8), intent(in) :: v
    f = 2d0 * v + 1d0
  end function
end module m
program data
  use m
  use omp_lib
  implicit none
  integer, parameter :: n = 2048
  real(8), allocatable :: b(:)
  type(pt) :: p
  integer :: i, nbad
  logical :: on_host
  allocate(b(n))
  b = [(dble(i), i = 1, n)]
  p = pt(1d0, 2d0)
  on_host = .true.
  !$omp target data map(tofrom: b) map(to: p)
  !$omp target teams distribute parallel do map(tofrom: on_host)
  do i = 1, n
    if (i == 3) on_host = omp_is_initial_device()
    b(i) = f(b(i)) + p%y
  end do
  !$omp end target data
  nbad = count(b /= [(2d0 * i + 3d0, i = 1, n)])
  if (nbad == 0 .and. .not. on_host) then
    print '(a,i0,a,l1,a)', 'data.f90 nbad=', nbad, ' on_host=', on_host, ' PASS'
  else
    print '(a,i0,a,l1,a)', 'data.f90 nbad=', nbad, ' on_host=', on_host, ' FAIL'
    error stop 1
  end if
end program data
