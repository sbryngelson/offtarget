program delete_only
  use openacc, only: acc_device_host, acc_on_device
  implicit none
  integer, parameter :: n = 64
  type :: holder
    integer, allocatable :: v(:)
  end type holder
  type(holder) :: h
  integer :: b(n)
  integer :: i, host_flag
  allocate(h%v(n))
  h%v = 1
  b = 0
  host_flag = 1
  !$acc enter data copyin(h)
  !$acc enter data copyin(h%v)
  !$acc parallel loop copyout(b) copy(host_flag) present(h)
  do i = 1, n
    if (i == 1) host_flag = merge(1, 0, acc_on_device(acc_device_host))
    b(i) = i + h%v(i)
  end do
  !$acc exit data delete(h%v)
  !$acc exit data delete(h)
  print '(a,i0)', 'sum= ', sum(b)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', sum(b) == 2144)
end program delete_only
