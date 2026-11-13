module fuzz_mod
  implicit none
contains
end module fuzz_mod
program fuzz_prog
  implicit none
  integer, parameter :: n = 24, m = 2
  type :: nd_t
  end type nd_t
  type :: rec_t
    type(nd_t) :: nd
  end type rec_t
  type(rec_t) :: dr
  integer, allocatable :: o1(:, :)
  integer :: i, j, r1a
  integer(8) :: cs
  allocate(o1(n, m))
  o1 = 0
  r1a = 7
  !$omp target teams distribute map(always, tofrom: r1a)
  do i = 1, n
    !$omp parallel do
    do j = 1, m
      o1(i, j) = 0
      !$omp atomic
      r1a = min(r1a, mod(i, n))
    end do
    !$omp end parallel do
  end do
  !$omp end target teams distribute
  cs = 0
  cs = modulo(cs * 31_8 + int(r1a, 8), 2147483629_8)
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o1(i, j), 8), 2147483629_8)
    end do
  end do
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
