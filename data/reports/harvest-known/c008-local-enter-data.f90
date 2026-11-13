! control for v008-declare-create-alloc: the allocatable is a
! local of the main program, made present with enter data create.
! expected: check=pass
program c008l
  use openacc
  implicit none
  integer, parameter :: n = 4096
  integer :: i, bad, hk_host
  real(8), allocatable :: buf(:)
  allocate(buf(n))
  !$acc enter data create(buf)
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
end program c008l
