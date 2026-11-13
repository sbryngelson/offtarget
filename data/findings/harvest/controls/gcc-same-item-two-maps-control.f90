! Control of harvest/gcc-same-item-two-maps-rejected.f90: the variable in one map clause, map(tofrom: x) (compiles;
! correct on gcc_g90 and gcc_sm80).
program map_same_item_once
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer :: x, host_flag
  x = 111
  host_flag = 1
  ! control: the list item in one map clause
  !$omp target map(tofrom: x) map(tofrom: host_flag)
    host_flag = merge(1, 0, omp_is_initial_device())
    x = x + 1
  !$omp end target
  print '(a,i0)', 'x= ', x
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', x == 112)
end program map_same_item_once
