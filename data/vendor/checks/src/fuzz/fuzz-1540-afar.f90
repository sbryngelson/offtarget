program fuzz_prog
  implicit none
  integer, parameter :: n = 16
  integer :: i, lp1
  integer(8) :: cs
  lp1 = 0
  !$omp target parallel do lastprivate(conditional: lp1)
  do i = 1, n
  end do
  !$omp end target parallel do
  cs = 0
  cs = modulo(cs * 31_8 + int(lp1, 8), 2147483629_8)
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
