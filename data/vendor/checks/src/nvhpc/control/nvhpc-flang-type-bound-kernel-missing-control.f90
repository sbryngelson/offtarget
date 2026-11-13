module wmod
  implicit none
  type op_t
    integer :: k = 0
  contains
    procedure, nopass :: tw => tw_impl
  end type op_t
contains
  integer function tw_impl(x)
    !$omp declare target
    integer, intent(in) :: x
    tw_impl = 2*x + 1
  end function tw_impl
end module wmod

program wide_prog
  use omp_lib, only: omp_is_initial_device
  use wmod
  implicit none
  integer, parameter :: n = 64
  integer :: a(n), b(n), ref(n)
  type(op_t) :: op
  integer :: i, host_flag
  logical :: ok
  do i = 1, n
    a(i) = i
    b(i) = 0
    ref(i) = 2*i + 1
  end do
  host_flag = 1
  !$omp target teams distribute parallel do map(to: a, op) map(from: b) map(tofrom: host_flag)
  do i = 1, n
    b(i) = tw_impl(a(i))
    if (i == 1) host_flag = merge(1, 0, omp_is_initial_device())
  end do
  !$omp end target teams distribute parallel do
  ok = all(b == ref)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program wide_prog
