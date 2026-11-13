program p
  implicit none
  integer, parameter :: n = 100
  integer(1) :: xk1(n)
  integer :: i
  do i = 1, n
    xk1(i) = int(mod(i * 17 + 16, 127), 1)
  end do
  !$omp target data map(to: xk1)
    !$omp target map(close, present, to: xk1)
    !$omp end target
  !$omp end target data
  print '(a)', 'RESULT check=pass'
end program p
