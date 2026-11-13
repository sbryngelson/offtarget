program fuzz_prog
  implicit none
  integer, parameter :: n = 32, m = 8
  integer :: i, j, lp1, t1
  integer(8) :: cs
  lp1 = 0
  !$omp target
    !$omp parallel
      !$omp do lastprivate(lp1) private(t1)
      do i = 1, n
        do j = 1, m
          t1 = 0
          lp1 = 0
        end do
      end do
    !$omp end parallel
  !$omp end target
  cs = 0
  cs = modulo(cs * 31_8 + int(lp1, 8), 2147483629_8)
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
