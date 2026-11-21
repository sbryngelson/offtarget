program kasync
  use openacc, only: acc_on_device, acc_device_host
  implicit none
  integer, parameter :: n = 64
  integer :: i, r, hf
  r = 65535
  hf = 1
  !$acc kernels copy(hf)
    !$acc loop gang reduction(iand: r)
    do i = 1, n
      if (i == 1) hf = merge(1, 0, acc_on_device(acc_device_host))
      r = iand(r, i + 256)
    end do
  !$acc end kernels
  !$acc wait(1)

  print '(a,i0)', 'ok= ', merge(1, 0, r == 256)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hf, ' check=', merge('pass', 'fail', r == 256)
end program kasync
