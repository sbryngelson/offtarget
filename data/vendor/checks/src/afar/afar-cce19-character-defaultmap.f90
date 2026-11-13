program p
  implicit none
  character :: ch
  character(len=4) :: s
  integer :: k
  ch = 'a'; s = 'abcd'; k = 1
  !$omp target
  ch = 'b'; s = 'wxyz'; k = 2
  !$omp end target
  print '(a,a,a,a,a,i0)', 'ch=', ch, ' s=', s, ' k=', k
end program
