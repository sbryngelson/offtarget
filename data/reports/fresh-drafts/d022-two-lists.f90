! Fresh-022 variant: two list-directed PRINTs of literals.
! Expected: Hello, then world
program reproducer
  implicit none
  !$omp target
  print *, "Hello,"
  print *, "world"
  !$omp end target
end program reproducer
