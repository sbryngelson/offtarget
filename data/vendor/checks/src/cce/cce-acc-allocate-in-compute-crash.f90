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
  !$acc serial copyin(a) copyout(b) copy(host_flag)
    host_flag = merge(1, 0, acc_on_device(acc_device_host))
    block
      integer, allocatable :: w(:)
      allocate(w(n))
      w = 2*a + 1
      b = w
      deallocate(w)
    end block
  !$acc end serial
  ok = all(b == ref)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program wide_prog
