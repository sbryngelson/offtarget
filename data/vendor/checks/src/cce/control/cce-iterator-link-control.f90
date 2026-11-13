program gen_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer, allocatable, target :: a(:), b(:)
  integer :: ref(n)
  integer :: i, host_flag
  logical :: ok
  integer :: k
  allocate(a(n), b(n))
  do i = 1, n
    a(i) = i
    b(i) = 0
    ref(i) = 2*(i + 10) + 1
  end do
  host_flag = 1
  !$omp target enter data map(to: a) map(alloc: b)
  do i = 1, n
    a(i) = a(i) + 10
  end do
  !$omp target update to(a)
  !$omp target map(to: a) map(from: b) map(tofrom: host_flag)
    host_flag = merge(1, 0, omp_is_initial_device())
    do i = 1, n
      b(i) = 2*a(i) + 1
    end do
  !$omp end target
  !$omp target update from(b(1:n))
  !$omp target exit data map(release: a, b)
  ok = all(b == ref)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
  deallocate(a, b)
end program gen_prog
