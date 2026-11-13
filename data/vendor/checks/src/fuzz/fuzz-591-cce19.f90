program fuzz_prog
  implicit none
  integer, parameter :: n = 128, m = 8
  integer :: o1(n, m)
  integer :: i, j, lp1, t1
  integer(8) :: cs
  o1 = 0
  lp1 = 0
  !$omp target
    !$omp teams distribute simd lastprivate(lp1) private(t1) nontemporal(o1)
    do i = n, 1, -1
      do j = 1, m
        t1 = 0
        lp1 = 0
      end do
    end do
    !$omp end teams distribute simd
  !$omp end target
  cs = 0
  cs = modulo(cs * 31_8 + int(lp1, 8), 2147483629_8)
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o1(i, j), 8), 2147483629_8)
    end do
  end do
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
