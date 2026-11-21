program pred
  use openacc, only: acc_on_device, acc_device_host
  implicit none
  integer, parameter :: n = 3, m = 8
  integer :: a(n), i, j, s, want, hf
  do i = 1, n
    a(i) = i
  end do
  want = 0
  do i = 1, n
    do j = 1, m
      want = want + a(i) + j
    end do
  end do
  s = 0
  hf = 0
  !$acc parallel copyin(a) copy(hf) copy(s)
    !$acc loop gang reduction(+: s)
    do i = 1, n
      do j = 1, m
        if (i == 1 .and. j == 1) hf = merge(1, 0, acc_on_device(acc_device_host))
        s = s + a(i) + j
      end do
    end do
  !$acc end parallel
  print '(a,i0,a,i0)', 's= ', s, ' want= ', want
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hf, ' check=', merge('pass', 'fail', s == want)
end program pred
