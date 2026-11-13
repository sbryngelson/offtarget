program target_no_task
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer :: a(n), b(n)
  integer :: i, host_flag, bad
  do i = 1, n
    a(i) = i
    b(i) = 0
  end do
  host_flag = 1
    !$omp target map(to: a) map(from: b) map(tofrom: host_flag)
      host_flag = merge(1, 0, omp_is_initial_device())
      do i = 1, n
        b(i) = 2*a(i) + 1
      end do
    !$omp end target
  bad = count(b /= 2*[(i, i = 1, n)] + 1)
  print '(a,i0)', 'bad= ', bad
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', bad == 0)
end program target_no_task
