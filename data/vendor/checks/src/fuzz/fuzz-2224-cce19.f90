program fuzz_prog
  implicit none
  integer, parameter :: n = 32, m = 2
  integer :: i, j
  integer(8) :: cs
  !$omp target
    !$omp masked
    !$omp end masked
  !$omp end target
  cs = 0
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
