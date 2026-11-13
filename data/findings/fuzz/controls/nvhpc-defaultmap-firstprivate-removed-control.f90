program p
  implicit none
  integer :: a(8), j, lp
  a = 0
  lp = 0
  !$omp target map(tofrom: a, lp)
    !$omp parallel do lastprivate(lp)
    do j = 1, 8
      a(j) = j
      lp = j
    end do
  !$omp end target
  print '(a,i0,a,i0)', 'suma= ', sum(a), ' lp= ', lp
  print '(a,a)', 'RESULT ran_on_host=0 check=', merge('pass', 'fail', sum(a) == 36 .and. lp == 8)
end program p
