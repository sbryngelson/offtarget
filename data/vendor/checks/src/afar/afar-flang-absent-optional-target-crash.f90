program wide_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer :: a(n), b(n), ref(n)
  integer :: i, host_flag
  logical :: ok
  do i = 1, n
    a(i) = i
    b(i) = 0
    ref(i) = 2*i + 1
  end do
  host_flag = 1
  call work(a, b, host_flag)
  ok = all(b == ref)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
contains
  subroutine work(x, y, hf, c)
    integer, intent(in) :: x(n)
    integer, intent(inout) :: y(n)
    integer, intent(inout) :: hf
    integer, intent(in), optional :: c(n)
    integer :: k
    !$omp target teams distribute parallel do map(to: x) map(tofrom: y, hf)
    do k = 1, n
      if (present(c)) then
        y(k) = x(k) + c(k)
      else
        y(k) = 2*x(k) + 1
      end if
      if (k == 1) hf = merge(1, 0, omp_is_initial_device())
    end do
    !$omp end target teams distribute parallel do
  end subroutine work
end program wide_prog
