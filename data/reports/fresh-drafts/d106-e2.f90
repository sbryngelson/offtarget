! Fresh-106 reduction: IF (ALLOCATED(j)) STOP in a target region.
! Expected: x 11
program p
  implicit none
  integer :: x
  integer, allocatable :: j

  x = 1
  !$omp target map(tofrom: x)
    if (allocated(j)) stop 1
    x = 11
  !$omp end target
  print *, 'x', x
end program p
