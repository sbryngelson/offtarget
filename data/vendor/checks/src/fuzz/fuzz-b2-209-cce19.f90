program fuzz_prog
  implicit none
  integer, parameter :: n = 16
  integer :: i, jj, lp1, acc1
  integer(8) :: cs
  lp1 = 0
  !$omp target simd lastprivate(conditional: lp1) private(acc1, jj)
  do i = 1, n
    acc1 = 0
    if (mod(i, 2) == 0) lp1 = i
  end do
  cs = 0
  cs = modulo(cs * 31_8 + int(lp1, 8), 2147483629_8)
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
