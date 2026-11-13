program fuzz_prog
  implicit none
  integer, parameter :: n = 200, m = 2
  integer :: i, j, r1a
  integer(8) :: cs
  r1a = -15
  !$omp target map(tofrom: r1a) defaultmap(tofrom: allocatable)
    do i = n, 1, -1
      r1a = r1a + i
    end do
  !$omp end target
  cs = 0
  cs = modulo(cs * 31_8 + int(r1a, 8), 2147483629_8)
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
