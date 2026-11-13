program fuzz_prog
  implicit none
  integer, parameter :: n = 48, m = 8
  type :: rec_t
    integer :: o1(n)
  end type rec_t
  type(rec_t) :: dr
  integer, allocatable :: ib(:)
  integer :: ic(n, m)
  integer :: i, j, p1, t1
  integer(8) :: cs
  allocate(ib(n))
  do i = 1, n
    ib(i) = mod(i * 51 + 10, 101) - 15
  end do
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 8 * j) * 55 + 11, 211) - 18
    end do
  end do
  dr%o1 = 0
  p1 = -6
  !$omp target map(tofrom: dr%o1) map(to: ic)
    !$omp teams distribute private(t1)
    do i = n, 1, -1
      t1 = 0
      dr%o1(i) = mod((mod((ic((mod(((i * 2) + 6), n) + 1), (mod(((i * 3) + 3), m) + 1)) + t1), 7) - &
          & ior((2 + ib(i)), mod(p1, 7))), 1009)
    end do
  !$omp end target
  cs = 0
  do i = 1, n
    cs = modulo(cs * 31_8 + int(dr%o1(i), 8), 2147483629_8)
  end do
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
