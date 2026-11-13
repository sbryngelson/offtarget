module dt_scalar_m
  implicit none
  integer(8) :: g
  !$omp declare target(g)
end module dt_scalar_m
program declare_target_scalar
  use omp_lib
  use dt_scalar_m
  implicit none
  integer :: dev
  g = 101
  dev = -1
  !$omp target update to(g)
  !$omp target map(tofrom: dev, g)
    g = 2 * g + 1
    dev = merge(0, 1, omp_is_initial_device())
  !$omp end target
  !$omp target update from(g)
  print '(a,i0,a,i0)', 'g= ', g, ' dev= ', dev
end program declare_target_scalar
