module gen_mod
  implicit none
  integer :: on_dev = 0
  !$omp declare target(on_dev)
end module gen_mod

program gen_prog
  use omp_lib, only: omp_is_initial_device
  use gen_mod
  implicit none
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
  !$omp target map(tofrom: host_flag)
    host_flag = merge(1, 0, omp_is_initial_device())
    on_dev = 1
  !$omp end target
  !$omp target map(to: a) map(from: b)
    b = 2*a + on_dev
  !$omp end target
  if (all(b == 2*a)) host_flag = 1
  ok = all(b == ref)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
  deallocate(a, b)
end program gen_prog
