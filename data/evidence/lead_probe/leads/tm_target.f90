! lead 3: RESULT line in a program with a target region
program tmt
  use omp_lib
  implicit none
  logical :: ok
  integer :: host_flag, x
  host_flag = 1
  x = 0
  !$omp target map(from: host_flag) map(tofrom: x)
  host_flag = merge(1, 0, omp_is_initial_device())
  x = 7
  !$omp end target
  ok = (x == 7)
  print *, 'RESULT ran_on_host=', host_flag, ' check=', trim(merge('pass', 'fail', ok))
  print *, 'RESULT2 ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
end program tmt
