! Shorter forms of fuzz/s1-9443-afar.f90 (AFAR
! present abort at HSA_XNACK=1 for map(close, present, to: xk1) inside a
! target data construct that maps xk1). Legal: target data maps xk1, so
! the present modifier is satisfied (5.2 §5.8.3); close is a hint.
! expected: check=pass
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
