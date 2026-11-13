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
  !$omp target map(to: a) map(from: b) map(tofrom: host_flag)
    host_flag = merge(1, 0, omp_is_initial_device())
    block
      integer :: w(n)
      w = 2*a + 1
      b = w
    end block
  !$omp end target
  ok = all(b == ref)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program wide_prog
