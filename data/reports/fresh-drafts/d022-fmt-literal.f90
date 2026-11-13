! Fresh-022 variant: formatted PRINT of the same literal.
program reproducer
  implicit none
  !$omp target
  print '(a)', "Hello, world!"
  !$omp end target
end program reproducer
