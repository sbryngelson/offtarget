program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer :: a(64)
  integer :: i, r, h
  a = [(i, i = 1, 64)]
  r = 0
  h = -1
  !$omp target map(to: a) map(tofrom: r) map(tofrom: h)
    h = merge(1, 0, omp_is_initial_device())
    r = a(5)
  !$omp end target
  print '(a,i0,a,i0)', 'r= ', r, ' h= ', h
  print '(a,i0,a,a)', 'RESULT ran_on_host=', merge(1, 0, h == 1), ' check=', merge('pass', 'fail', r == 5 .and. h == 0)
end program p
