program fuzz_prog
  implicit none
  integer, parameter :: n = 100
  integer :: i, lp1
  integer(8) :: cs
  lp1 = 0
  !$omp target parallel do lastprivate(conditional: lp1)
  do i = 1, n
    if (mod(i, 3) == 0) lp1 = 0
  end do
  cs = 0
  cs = modulo(cs * 31_8 + int(lp1, 8), 2147483629_8)
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
