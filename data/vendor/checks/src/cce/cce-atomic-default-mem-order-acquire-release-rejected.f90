program gen_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  !$omp requires atomic_default_mem_order(release)
  integer, parameter :: n = 64
  integer, allocatable, target :: a(:), b(:)
  integer :: ref(n)
  integer :: i, host_flag
  logical :: ok
  allocate(a(n), b(n))
  do i = 1, n
    a(i) = i
    b(i) = 0
    ref(i) = 2*i + 1
  end do
  host_flag = 1
  !$omp target teams distribute parallel do map(to: a) map(from: b) map(tofrom: host_flag) &
  !$omp& default(none) shared(a, b, host_flag)
    do i = 1, n
      b(i) = 2*a(i) + 1
      if (i == 1) host_flag = merge(1, 0, omp_is_initial_device())
    end do
  !$omp end target teams distribute parallel do
  ok = all(b == ref)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
  deallocate(a, b)
end program gen_prog
