program fuzz_prog
  implicit none
  integer, parameter :: n = 100, m = 8
  integer :: o1(n)
  integer :: i, j
  integer(8) :: cs
  o1 = 0
  !$omp target map(tofrom: o1) defaultmap(firstprivate: aggregate)
  do i = 1, n
    o1(i) = 1
  end do
  !$omp end target
  cs = 0
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o1(i), 8), 2147483629_8)
  end do
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
