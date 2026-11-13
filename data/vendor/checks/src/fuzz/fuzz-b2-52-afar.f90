module fuzz_mod
  implicit none
contains
end module fuzz_mod
program fuzz_prog
  implicit none
  integer, parameter :: n = 64, m = 2
  type :: nd_t
  end type nd_t
  type :: rec_t
    type(nd_t) :: nd
  end type rec_t
  type(rec_t) :: dr
  integer :: o3(n, m)
  integer :: i, j
  integer(8) :: cs
  o3 = 0
  !$omp target
    !$omp teams
      !$omp distribute
      do i = 1, n
        !$omp parallel firstprivate(i)
          !$omp do
          do j = m, 1, -1
            o3(i, j) = 1009
          end do
          !$omp end do
        !$omp end parallel
      end do
      !$omp end distribute
    !$omp end teams
  !$omp end target
  cs = 0
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o3(i, j), 8), 2147483629_8)
    end do
  end do
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
