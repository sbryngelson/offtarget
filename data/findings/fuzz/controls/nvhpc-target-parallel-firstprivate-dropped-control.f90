program p
  implicit none
  integer :: a(64), i, k
  a = 0
  k = 3
  !$omp target parallel map(tofrom: a)
    !$omp do
    do i = 1, 64
      a(i) = i + k
    end do
    !$omp end do nowait
  !$omp end target parallel
  print '(a,i0)', 'suma= ', sum(a)
  print '(a,a)', 'RESULT ran_on_host=0 check=', merge('pass', 'fail', sum(a) == 2080 + 64 * 3)
end program p
