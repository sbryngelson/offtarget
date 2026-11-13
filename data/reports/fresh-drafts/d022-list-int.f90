! Fresh-022 variant: list-directed PRINT of an integer literal.
program reproducer
  implicit none
  !$omp target
  print *, 42
  !$omp end target
end program reproducer
