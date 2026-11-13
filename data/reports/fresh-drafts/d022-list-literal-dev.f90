! Fresh-022 variant: the literal PRINT plus a device write that
! is checked on the host (shows whether the region ran).
program reproducer
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer :: dev
  dev = -1
  !$omp target map(tofrom: dev)
  print *, "Hello, world!"
  dev = merge(0, 1, omp_is_initial_device())
  !$omp end target
  print *, 'dev=', dev
end program reproducer
