! control for v008-declare-create-alloc: a fixed-size module array
! in declare create.
! expected: check=pass
module v008_m
  implicit none
  real(8) :: buf(4096)
  !$acc declare create(buf)
end module v008_m

program c008f
  use openacc
  use v008_m
  implicit none
  integer, parameter :: n = 4096
  integer :: i, bad, hk_host
  !$acc parallel loop present(buf)
  do i = 1, n
    buf(i) = real(i, 8)
  end do
  !$acc update host(buf)
  bad = count(buf /= [(real(i, 8), i = 1, n)])
  hk_host = 1
  !$acc parallel num_gangs(1) copy(hk_host)
  if (.not. acc_on_device(acc_device_host)) hk_host = 0
  !$acc end parallel
  print '(a,i0)', 'bad = ', bad
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hk_host, ' check=', merge('pass', 'fail', bad == 0)
end program c008f
