program gen_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer, allocatable, target :: a(:), b(:)
  integer :: ref(n)
  integer :: i, host_flag
  logical :: ok
  integer :: x
  allocate(a(n), b(n))
  do i = 1, n
    a(i) = i
    b(i) = 0
    ref(i) = 2*i + 1
  end do
  host_flag = 1
  x = 3
    host_flag = merge(1, 0, omp_is_initial_device())
    !$omp parallel do default(none) shared(a, b) linear(x: 1)
      do i = 1, n
        b(i) = 2*a(i) + 1 + (x - (1*i + 2))
        x = x + 1
      end do
    !$omp end parallel do
  ok = all(b == ref) .and. (x == 1*n + 3)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
  deallocate(a, b)
end program gen_prog
