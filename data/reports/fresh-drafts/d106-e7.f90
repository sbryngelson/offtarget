! Fresh-106 reduction: IF (.NOT. ALLOCATED(j)) STOP with j allocated
! (mapped implicitly, so the branch is not taken).
! Expected: x 11
program p
  implicit none
  integer :: x
  integer, allocatable :: j
  allocate(j); j = 5
  x = 1
  !$omp target map(tofrom: x)
    if (.not. allocated(j)) stop 1
    x = 11
  !$omp end target
  print *, 'x', x
end program p
