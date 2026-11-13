program wide_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer :: a(n), b(n), ref(n)
  integer :: i, host_flag
  logical :: ok
  do i = 1, n
    a(i) = i
    b(i) = 0
    ref(i) = 2*i + 1
  end do
  host_flag = 1
  !$omp target parallel map(to: a) map(tofrom: b, host_flag)
  !$omp sections
  !$omp section
  do i = 1, n/2
    b(i) = 2*a(i) + 1
  end do
  host_flag = merge(1, 0, omp_is_initial_device())
  !$omp section
  do i = n/2 + 1, n
    b(i) = a(i) + a(i) + 1
  end do
  !$omp end sections
  !$omp end target parallel
  ok = all(b == ref)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program wide_prog
