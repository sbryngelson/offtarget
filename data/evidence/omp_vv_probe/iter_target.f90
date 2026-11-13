program iter_target
  use omp_lib
  implicit none
  integer, parameter :: n = 64
  integer :: w(n), i, host_flag
  w = 1; host_flag = 1
  !$omp target map(iterator(k = 1:n), tofrom: w(k)) map(tofrom: host_flag)
    host_flag = merge(1, 0, omp_is_initial_device())
    do i = 1, n
      w(i) = 2
    end do
  !$omp end target
  print '(a,i0,a,i0,a,i0)', 'iter_target ran_on_host=', host_flag, ' sum=', sum(w), ' want=', 2*n
end program
