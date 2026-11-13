! Message probe (not a catalog program): a target region calls an external
! procedure that is not declare target (link_main.f90 link_ext.f90).
program p
  implicit none
  integer :: x
  integer, external :: ext_fn
  x = 0
  !$omp target map(tofrom: x)
  x = ext_fn(1)
  !$omp end target
  print *, x
end program p
