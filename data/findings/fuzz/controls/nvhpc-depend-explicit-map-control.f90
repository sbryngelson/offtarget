program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer :: a(64)
  integer :: i, s, host
  a = 0
  host = 1
  !$omp target map(tofrom: host, a) nowait depend(inout: a)
  do i = 1, 64
    a(i) = i
  end do
  if (omp_is_initial_device()) then
    host = 1
  else
    host = 0
  end if
  !$omp end target
  !$omp taskwait
  s = sum(a)
  print '(a,i0)', 'sum= ', s
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host, ' check=', merge('pass', 'fail', s == 2080)
end program p
