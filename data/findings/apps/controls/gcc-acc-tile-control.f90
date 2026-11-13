! Control of apps/gcc-acc-tile-partial-tiles-wrong.f90: collapse(2) in place of tile(32, 32) (correct on gcc_g90 and gcc_sm80).
program tile_partial
  use openacc, only: acc_device_host, acc_on_device
  implicit none
  integer, parameter :: n = 100
  integer :: a(n, n)
  integer :: i, j, bad, want, host_flag
  a = 0
  !$acc parallel loop collapse(2) copy(a)
  do j = 2, n - 1
    do i = 2, n - 1
      a(i, j) = a(i, j) + i + j
    end do
  end do
  host_flag = 1
  !$acc parallel num_gangs(1) copy(host_flag)
  if (.not. acc_on_device(acc_device_host)) host_flag = 0
  !$acc end parallel
  bad = 0
  do j = 1, n
    do i = 1, n
      want = 0
      if (i > 1 .and. i < n .and. j > 1 .and. j < n) want = i + j
      if (a(i, j) /= want) bad = bad + 1
    end do
  end do
  print '(a,i0)', 'bad= ', bad
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', bad == 0)
end program tile_partial
