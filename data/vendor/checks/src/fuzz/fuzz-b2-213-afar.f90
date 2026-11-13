module fuzz_mod
  implicit none
contains
end module fuzz_mod
program fuzz_prog
  implicit none
  integer, parameter :: n = 32, m = 5
  type :: rec_t
    integer :: a(n)
  end type rec_t
  type :: el_t
  end type el_t
  type(rec_t) :: dr
  type(el_t) :: ds(n)
  integer, allocatable :: o1(:, :)
  integer :: i, j, r1a
  integer(8) :: cs
  allocate(o1(n, m))
  do i = 1, n
    dr%a(i) = mod(i * 23 + 28, 1009) - 305
  end do
  o1 = 0
  r1a = 145
    !$omp target map(tofrom: r1a)
      !$omp teams reduction(ieor: r1a)
        !$omp distribute
        do i = 1, n
          !$omp parallel
            !$omp do reduction(ieor: r1a)
            do j = 1, m, 2
              o1(i, j) = 0
              r1a = ieor(r1a, iand(dr%a(i), 1048575))
            end do
          !$omp end parallel
        end do
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
