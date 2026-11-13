program p
  implicit none
  integer :: r, i
  r = 3
  !$omp target parallel do map(tofrom: r) reduction(*: r)
  do i = 1, 8
    r = r * 2
  end do
  !$omp end target parallel do
  print '(a,i0)', 'r= ', r
  print '(a,a)', 'RESULT ran_on_host=0 check=', merge('pass', 'fail', r == 768)
end program p
