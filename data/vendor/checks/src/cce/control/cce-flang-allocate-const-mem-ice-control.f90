program wide_prog
  use omp_lib, only: omp_is_initial_device
  use omp_lib, only: omp_const_mem_alloc
  implicit none
  integer, parameter :: n = 64
  integer :: a(n), b(n), ref(n)
  integer :: x
  integer :: i, host_flag
  logical :: ok
  do i = 1, n
    a(i) = i
    b(i) = 0
    ref(i) = i + 5
  end do
  host_flag = 1
  x = 5
  !$omp target teams distribute parallel do map(to: a) map(from: b) &
  !$omp& map(tofrom: host_flag) firstprivate(x)
  do i = 1, n
    b(i) = a(i) + x
    if (i == 1) host_flag = merge(1, 0, omp_is_initial_device())
  end do
  !$omp end target teams distribute parallel do
  ok = all(b == ref)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program wide_prog
