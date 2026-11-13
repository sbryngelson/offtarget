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
  !$omp target teams distribute parallel do map(to: a) map(from: b) map(tofrom: host_flag)
  do i = 1, n
    if (a(i) < 0) b(i) = -1
    b(i) = 2*a(i) + 1
    if (i == 1) host_flag = merge(1, 0, omp_is_initial_device())
  end do
  !$omp end target teams distribute parallel do
  ok = all(b == ref)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program wide_prog
