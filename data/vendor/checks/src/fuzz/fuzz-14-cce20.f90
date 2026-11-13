program fuzz_prog
  implicit none
  integer, parameter :: n = 24, m = 8
  integer :: i, j, jj, lp1, acc1, t1
  logical :: lsimd
  integer(8) :: cs
  lp1 = 0
  lsimd = .false.
    !$omp target teams map(tofrom: lp1)
      !$omp distribute parallel do simd lastprivate(lp1) private(t1, acc1, jj) num_threads(8)
      do i = 1, n
        t1 = 0
        acc1 = 0
        lp1 = i
      end do
      !$omp end distribute parallel do simd
    !$omp end target teams
  cs = 0
  cs = modulo(cs * 31_8 + int(lp1, 8), 2147483629_8)
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
