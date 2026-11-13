program acc
  ! GCC smoke: OpenACC offload (-fopenacc): the sum and whether the compute
  ! region ran on the device (acc_on_device)
  use openacc
  implicit none
  integer, parameter :: n = 1000
  real :: a(n)
  integer :: i
  logical :: dev
  a = 1.0
  dev = .false.
  !$acc parallel loop copy(a) copy(dev)
  do i = 1, n
    a(i) = a(i) + i
    if (i == 1) dev = .not. acc_on_device(acc_device_host)
  end do
  if (sum(a) == n + n * (n + 1) / 2 .and. dev) then
    print '(a,f10.1,a,l1,a)', 'acc.f90 sum=', sum(a), ' on_device=', dev, ' PASS'
  else
    print '(a,f10.1,a,l1,a)', 'acc.f90 sum=', sum(a), ' on_device=', dev, ' FAIL'
    error stop 1
  end if
end program acc
