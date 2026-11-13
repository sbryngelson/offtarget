program wide_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer :: a(n), b(n), ref(n)
  integer :: s, t
  integer :: i, host_flag
  logical :: ok
  do i = 1, n
    a(i) = i
    b(i) = 0
    ref(i) = 2*i + 1
  end do
  host_flag = 1
  s = 0
  !$omp parallel do private(t)
  do i = 1, n
    !$omp critical (wsum)
    t = s
    s = t + a(i)
    !$omp end critical (wsum)
    if (i == 1) host_flag = merge(1, 0, omp_is_initial_device())
  end do
  !$omp end parallel do
  ok = s == n*(n + 1)/2
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program wide_prog
