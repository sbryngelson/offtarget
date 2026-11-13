program fuzz_prog
  implicit none
  integer, parameter :: n = 64, m = 5
  type :: rec_t
    integer, allocatable :: q(:)
  end type rec_t
  type(rec_t) :: dr
  integer, allocatable, target :: ib(:)
  integer :: ic(n, m)
  integer :: i, j, r1b
  integer(8) :: cs
  allocate(ib(n))
  allocate(dr%q(n))
  do i = 1, n
    ib(i) = mod(i * 42 + 15, 101) - 28
  end do
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 6 * j) * 19 + 21, 97) - 20
    end do
  end do
  do i = 1, n
    dr%q(i) = mod(i * 17 + 13, 1009) - 449
  end do
  r1b = -13
    !$omp target teams reduction(max: r1b)
      !$omp distribute
      do i = n, 1, -1
        do j = 1, m
          r1b = max(r1b, max((dr%q(i) / 8), (ic(8, (6 - j)) + ib(i))))
        end do
      end do
      !$omp end distribute
    !$omp end target teams
  cs = 0
  cs = modulo(cs * 31_8 + int(r1b, 8), 2147483629_8)
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
