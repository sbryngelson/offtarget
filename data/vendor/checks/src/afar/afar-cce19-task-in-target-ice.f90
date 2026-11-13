program t
  implicit none
  integer :: c, r
  r = 0
  !$omp target map(from: r)
    c = 7
    !$omp task default(shared)
      c = 42
    !$omp end task
    !$omp taskwait
    r = c
  !$omp end target
  print *, 'r=', r
end program
