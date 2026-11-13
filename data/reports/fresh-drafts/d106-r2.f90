! Fresh-106: IF (x /= 1 .or. x > 5) STOP directly in a target region (d106-e4 without the unused allocatable).
! Expected: x 11
program p
  implicit none
  integer :: x
  x = 1
  !$omp target map(tofrom: x)
    if (x /= 1 .or. x > 5) stop 1
    x = 11
  !$omp end target
  print *, 'x', x
end program p
