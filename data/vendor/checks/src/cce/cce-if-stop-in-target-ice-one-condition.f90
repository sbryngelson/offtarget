program p
  implicit none
  integer :: x
  x = 1
  !$omp target map(tofrom: x)
    if (x /= 1) stop 1
    x = 11
  !$omp end target
  print *, 'x', x
end program p
