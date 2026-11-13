program wide_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer :: a(n), b(n), ref(n)
  integer :: t(4)
  integer :: i, host_flag
  logical :: ok
  do i = 1, n
    a(i) = i
    b(i) = 0
    ref(i) = 2*i + 1
  end do
  host_flag = 1
  !$omp target enter data map(to: a) map(alloc: b)
  !$omp target teams distribute parallel do defaultmap(present: aggregate) &
  !$omp& private(t) map(tofrom: host_flag)
  do i = 1, n
    t(1) = a(i)
    t(2) = 1
    t(3) = a(i)
    t(4) = 0
    b(i) = sum(t)
    if (i == 1) host_flag = merge(1, 0, omp_is_initial_device())
  end do
  !$omp end target teams distribute parallel do
  !$omp target exit data map(from: b) map(release: a)
  ok = all(b == ref)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program wide_prog
