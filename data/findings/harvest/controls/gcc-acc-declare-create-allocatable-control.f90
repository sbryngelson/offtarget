! Control of harvest/gcc-acc-declare-create-allocatable-not-mapped.f90: the same program with an enter data create
! after the allocate statement (correct on gcc_g90 and gcc_sm80).
module declare_create_m
  implicit none
  integer, allocatable :: a(:)
  !$acc declare create(a)
end module declare_create_m

program declare_create_allocatable
  use openacc, only: acc_device_host, acc_on_device
  use declare_create_m
  implicit none
  integer, parameter :: n = 1000
  integer :: i, bad, host_flag
  allocate(a(n))
  !$acc enter data create(a)
  a = -1
  !$acc parallel loop present(a)
  do i = 1, n
    a(i) = i
  end do
  !$acc update host(a)
  bad = 0
  do i = 1, n
    if (a(i) /= i) bad = bad + 1
  end do
  host_flag = 1
  !$acc parallel num_gangs(1) copy(host_flag)
  if (.not. acc_on_device(acc_device_host)) host_flag = 0
  !$acc end parallel
  print '(a,i0)', 'bad= ', bad
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', bad == 0)
  deallocate(a)
end program declare_create_allocatable
