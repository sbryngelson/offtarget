! Fresh-106 reduction: control: IF (x /= 1 .or. x > 5) STOP (two conditions, no ALLOCATED).
! Expected: x 11
program p
  implicit none
  integer :: x
  integer, allocatable :: j

  x = 1
  !$omp target map(tofrom: x)
    if (x /= 1 .or. x > 5) stop 1
    x = 11
  !$omp end target
  print *, 'x', x
end program p
