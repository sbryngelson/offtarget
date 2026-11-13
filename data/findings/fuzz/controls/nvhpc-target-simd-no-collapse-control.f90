program p
  implicit none
  integer, parameter :: n = 16, m = 4
  integer :: ia(n), i, j
  real(4) :: o1(n, m)
  do i = 1, n
    ia(i) = mod(i * 22 + 1, 97) - 35
  end do
  o1 = 0.0
  !$omp target simd map(from: o1) map(to: ia)
  do i = 1, n
    do j = 1, m
      o1(i, j) = real(ia(i) + j, 4)
    end do
  end do
  !$omp end target simd
  print '(a,f0.2)', 'o1= ', o1(1, 1)
  print '(a,a)', 'RESULT ran_on_host=0 check=', merge('pass', 'fail', nint(o1(1, 1)) == ia(1) + 1)
end program p
