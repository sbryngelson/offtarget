program p
  implicit none
  character(len=8) :: xs(2)
  xs = 'abcdefgh'
  !$omp target enter data map(to: xs)
  !$omp target exit data map(release: xs)
  print '(a)', 'RESULT check=pass'
end program p
