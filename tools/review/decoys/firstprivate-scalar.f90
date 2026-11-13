program p
  implicit none
  integer :: k
  k = 1
  !$omp target
  k = 2
  !$omp end target
  print '(a,i0)', 'k=', k
end program p
