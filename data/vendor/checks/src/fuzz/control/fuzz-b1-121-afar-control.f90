program fuzz_prog
  implicit none
  integer :: p1, r1a
  integer(8) :: cs
  p1 = -4
  r1a = 1048575
  !$omp target map(tofrom: r1a)
    !$omp teams reduction(iand: r1a)
    !$omp end teams
  !$omp end target
  cs = 0
  cs = modulo(cs * 31_8 + int(r1a, 8), 2147483629_8)
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
