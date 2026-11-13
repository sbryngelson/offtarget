program fuzz_prog
  implicit none
  integer, parameter :: n = 48, m = 8
  integer, allocatable :: o1(:, :)
  integer :: i, j, r1a
  integer(8) :: cs
  allocate(o1(n, m))
  o1 = 0
  r1a = 65535
  !$omp target map(tofrom: r1a)
    !$omp teams reduction(iand: r1a)
      !$omp distribute
      do i = n, 1, -1
          do j = 1, m
            o1(i, j) = 0
            r1a = iand(r1a, i)
          end do
      end do
      !$omp end distribute
    !$omp end teams
  !$omp end target
  cs = 0
  cs = modulo(cs * 31_8 + int(r1a, 8), 2147483629_8)
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o1(i, j), 8), 2147483629_8)
    end do
  end do
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
