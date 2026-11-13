program t
  implicit none
  integer :: c, r
  r = 0
  !$omp target map(from: r)
    c = 7
      c = 42
    r = c
  !$omp end target
  print *, 'r=', r
end program
