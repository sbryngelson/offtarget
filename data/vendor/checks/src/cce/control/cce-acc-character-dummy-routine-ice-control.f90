module wmod
  implicit none
contains
  integer function code(k, l)
    !$acc routine seq
    integer, intent(in) :: k, l
    code = k + l
  end function code
end module wmod

program wide_prog
  use openacc, only: acc_device_host, acc_on_device
  use wmod
  implicit none
  integer, parameter :: n = 64
  integer :: a(n), b(n), ref(n)
  character(len=8) :: s
  integer :: i, host_flag
  logical :: ok
  do i = 1, n
    a(i) = i
    b(i) = 0
    ref(i) = 97 + mod(i, 8) + 1
  end do
  host_flag = 1
  !$acc parallel loop copyin(a) copyout(b) copy(host_flag) private(s)
  do i = 1, n
    s = 'abcdefgh'
    b(i) = code(ichar(s(1:1)), mod(i, 8) + 1)
    if (i == 1) host_flag = merge(1, 0, acc_on_device(acc_device_host))
  end do
  ok = all(b == ref)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program wide_prog
