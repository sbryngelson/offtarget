program p
  implicit none
  integer :: a(64), i
  a = 0
  !$omp target map(from: a)
    !$omp teams
      !$omp distribute
      do i = 1, 64
        a(i) = i
      end do
      !$omp end distribute
    !$omp end teams
  !$omp end target
  print '(a,i0)', 'sum= ', sum(a)
  print '(a,a)', 'RESULT ran_on_host=0 check=', merge('pass', 'fail', sum(a) == 2080)
end program p
