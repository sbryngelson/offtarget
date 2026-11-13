! Fresh-106: control of d106-r2.f90: the same IF with an assignment instead of the STOP.
! Expected: x 11
program p
  implicit none
  integer :: x
  x = 1
  !$omp target map(tofrom: x)
    if (x /= 1 .or. x > 5) x = -100
    x = 11
  !$omp end target
  print *, 'x', x
end program p
