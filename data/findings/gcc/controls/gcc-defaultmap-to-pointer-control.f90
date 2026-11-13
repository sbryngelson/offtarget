program map_to_pointer
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer, pointer :: wp(:)
  integer :: b(n), zc(1)
  integer :: i, host_flag, changed
  logical :: shared_mem
  allocate(wp(n))
  wp = 0
  b = 0
  host_flag = 1
  zc = 0
  ! separate memory? (a write to a map(to:) array is visible on the host only when storage is shared)
  !$omp target map(to: zc)
    zc(1) = 1
  !$omp end target
  shared_mem = zc(1) == 1
  !$omp target map(from: b) map(tofrom: host_flag) map(to: wp)
    host_flag = merge(1, 0, omp_is_initial_device())
    do i = 1, n
      wp(i) = 2*i
      b(i) = wp(i) + 1
    end do
  !$omp end target
  changed = count(wp /= 0)
  print '(a,i0,a,i0,a,l1)', 'b(n)= ', b(n), ' host wp changed: ', changed, ' shared_mem= ', shared_mem
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', &
    merge('pass', 'fail', b(n) == 2*n + 1 .and. (shared_mem .or. changed == 0))
  deallocate(wp)
end program map_to_pointer
