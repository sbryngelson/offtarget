program wide_prog
  use openacc, only: acc_device_host, acc_on_device
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
  !$acc parallel loop copyin(a) copyout(b) copy(host_flag)
  do i = 1, n
    if (a(i) < 0) stop 1
    b(i) = 2*a(i) + 1
    if (i == 1) host_flag = merge(1, 0, acc_on_device(acc_device_host))
  end do
  ok = all(b == ref)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program wide_prog
