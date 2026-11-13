program p
  implicit none
  integer, parameter :: n = 8
  character(len=4) :: xc(n)
  xc = 'abcd'
  !$omp target enter data map(to: xc)
  !$omp target exit data map(release: xc)
  print '(a)', 'RESULT check=pass'
end program p
