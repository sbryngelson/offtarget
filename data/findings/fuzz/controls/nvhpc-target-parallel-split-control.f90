program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer :: h
  h = -1
  !$omp target map(tofrom: h)
  !$omp parallel
    !$omp single
      h = merge(1, 0, omp_is_initial_device())
    !$omp end single
  !$omp end parallel
  !$omp end target
  print '(a,i0)', 'h= ', h
  print '(a,i0,a,a)', 'RESULT ran_on_host=', merge(1, 0, h == 1), ' check=', merge('pass', 'fail', h == 0)
end program p
