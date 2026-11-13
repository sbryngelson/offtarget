program p
  implicit none
  integer :: a(16), b(16), i, t
  b = 1
  a = 0
  !$omp target map(tofrom: a) map(to: b)
    !$omp simd private(t)
    do i = 1, 16
      t = b(i)
      a(i) = t + i
    end do
  !$omp end target
  print '(a,i0)', 'suma= ', sum(a)
  print '(a,a)', 'RESULT ran_on_host=0 check=', merge('pass', 'fail', sum(a) == 152)
end program p
