program fuzz_prog
  implicit none
  integer, parameter :: n = 100, m = 3
  integer, allocatable :: o1(:, :)
  integer :: i, j
  integer(8) :: cs
  allocate(o1(n, m))
  o1 = 0
  !$omp target teams distribute
  do i = 1, n
    !$omp parallel
      !$omp do
      do j = 1, m
        o1(i, j) = i
      end do
      !$omp end do
    !$omp end parallel
  end do
  cs = 0
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o1(i, j), 8), 2147483629_8)
    end do
  end do
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
