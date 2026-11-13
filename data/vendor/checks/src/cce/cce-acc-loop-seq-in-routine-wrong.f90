module wmod
  implicit none
contains
  subroutine rowsum(x, s)
    !$acc routine seq
    integer, intent(in) :: x(:)
    integer, intent(out) :: s
    integer :: k
    s = 0
    !$acc loop seq
    do k = 1, size(x)
      s = s + x(k)
    end do
  end subroutine rowsum
end module wmod

program wide_prog
  use openacc, only: acc_device_host, acc_on_device
  use wmod
  implicit none
  integer, parameter :: n = 64
  integer :: a(n), b(n), ref(n)
  integer :: a2(4, n)
  integer :: k
  integer :: i, host_flag
  logical :: ok
  do i = 1, n
    a(i) = i
    b(i) = 0
    ref(i) = 10*i
  end do
  do i = 1, n
    do k = 1, 4
      a2(k, i) = k*i
    end do
  end do
  host_flag = 1
  !$acc parallel loop copyin(a2) copyout(b) copy(host_flag)
  do i = 1, n
    call rowsum(a2(:, i), b(i))
    if (i == 1) host_flag = merge(1, 0, acc_on_device(acc_device_host))
  end do
  ok = all(b == ref)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program wide_prog
