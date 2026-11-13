program fuzz_prog
  implicit none
  integer, parameter :: n = 32, m = 3
  integer, allocatable :: o1(:, :)
  integer :: i, j, p1
  integer(8) :: cs
  allocate(o1(n, m))
  o1 = 0
  p1 = 4
  !$omp target
    !$omp teams firstprivate(p1)
      !$omp distribute
      do i = n, 1, -1
        !$omp parallel firstprivate(p1)
          !$omp do
          do j = 1, m, 2
            o1(i, j) = p1
          end do
          !$omp end do
        !$omp end parallel
      end do
    !$omp end teams
  !$omp end target
  cs = 0
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o1(i, j), 8), 2147483629_8)
    end do
  end do
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
