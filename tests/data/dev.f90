program dev
  use omp_lib
  implicit none
  integer :: host_flag
  host_flag = 1
  !$omp target map(from: host_flag)
  if (omp_is_initial_device()) then
    host_flag = 1
  else
    host_flag = 0
  end if
  !$omp end target
  print '(a,i0)', 'ran_on_host=', host_flag
end program
