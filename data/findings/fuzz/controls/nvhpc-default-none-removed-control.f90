program p
  implicit none
  integer :: a(8), i, lp, r
  a = 0
  lp = 0
  r = 0
  !$omp target map(tofrom: a, r) map(from: lp)
    !$omp teams distribute parallel do reduction(+: r) lastprivate(lp)
    do i = 1, 8
      a(i) = i
      r = r + i
      lp = i
    end do
    !$omp end teams distribute parallel do
  !$omp end target
  print '(a,i0,a,i0)', 'suma= ', sum(a), ' r= ', r
  print '(a,a)', 'RESULT ran_on_host=0 check=', merge('pass', 'fail', sum(a) == 36 .and. r == 36)
end program p
