! Fresh-022 variant: the literal PRINT plus a mapped integer written
! in the region (no omp_lib). Expected: Hello, world! then k= 1
program reproducer
  implicit none
  integer :: k
  k = 0
  !$omp target map(tofrom: k)
  print *, "Hello, world!"
  k = 1
  !$omp end target
  print *, 'k=', k
end program reproducer
