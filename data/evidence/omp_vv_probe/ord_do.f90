program ord_do
  use omp_lib
  implicit none
  integer, parameter :: n = 64
  integer :: a(n), b(n), i, host_flag
  a = [(i, i = 1, n)]; b = 0; host_flag = 1
  !$omp target map(to: a) map(from: b) map(tofrom: host_flag)
    host_flag = merge(1, 0, omp_is_initial_device())
    !$omp parallel do order(concurrent)
    do i = 1, n
      b(i) = 2*a(i) + 1
    end do
    !$omp end parallel do
  !$omp end target
  print '(a,i0,a,l1)', 'ord_do ran_on_host=', host_flag, ' ok=', all(b == 2*a + 1)
end program
