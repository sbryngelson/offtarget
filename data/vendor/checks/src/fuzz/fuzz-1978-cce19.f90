program fuzz_prog
  implicit none
  integer, parameter :: n = 24, m = 5
  integer :: o1(n)
  integer :: i, j, jj, acc1
  integer(8) :: cs
  o1 = 0
  !$omp target map(always, from: o1) defaultmap(firstprivate: aggregate) private(acc1, jj)
  do i = n, 1, -1
    acc1 = 0
    o1(i) = i
  end do
  !$omp end target
  cs = 0
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o1(i), 8), 2147483629_8)
  end do
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
