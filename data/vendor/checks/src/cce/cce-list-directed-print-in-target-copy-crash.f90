program reproducer
  implicit none
  !$omp target
  print *, "Hello, world!"
  !$omp end target
end program reproducer
