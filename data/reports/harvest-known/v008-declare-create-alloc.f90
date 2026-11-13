! variant of hk-008: a module allocatable in declare create,
! allocated on the host (which also allocates its device copy, OpenACC 3.4
! §2.13), written in a parallel loop under present(buf), copied back with
! update host. No host_data.
! expected: check=pass
module v008_m
  implicit none
  real(8), allocatable :: buf(:)
  !$acc declare create(buf)
end module v008_m

program v008
  use openacc
  use v008_m
  implicit none
  integer, parameter :: n = 4096
  integer :: i, bad, hk_host
  allocate(buf(n))
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
end program v008
