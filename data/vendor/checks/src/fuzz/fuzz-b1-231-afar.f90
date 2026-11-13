module fuzz_mod
  implicit none
contains
end module fuzz_mod
program fuzz_prog
  implicit none
  integer, parameter :: n = 16, m = 3
  integer, allocatable :: o1(:, :)
  double precision :: r1b
  integer :: i, j
  integer(8) :: cs
  allocate(o1(n, m))
  o1 = 0
  r1b = (-21.0d0)
    !$omp target map(tofrom: r1b)
      !$omp teams
        !$omp distribute
        do i = n, 1, -1
          !$omp parallel
            !$omp do
            do j = 1, m
              o1(i, j) = 0
              !$omp atomic
              r1b = r1b + mod(i, 97)
            end do
          !$omp end parallel
        end do
        !$omp end distribute
      !$omp end teams
    !$omp end target
  cs = 0
  cs = modulo(cs * 31_8 + int(r1b * 64, 8), 2147483629_8)
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o1(i, j), 8), 2147483629_8)
    end do
  end do
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
