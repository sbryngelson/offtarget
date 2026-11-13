program p
  implicit none
  integer :: a(64), b(64)
  a = 1
  b = 0
  !$omp target map(present, to: a) map(from: b)
    b = a + 1
  !$omp end target
  print *, 'reached the end: b1=', b(1)
end program p
