module fuzz_mod
  implicit none
contains
  integer function g1(x)
    !$omp declare target
    integer, intent(in) :: x
    g1 = mod(ior(merge(4, x, x /= 4), 4), 97)
  end function g1
end module fuzz_mod
program fuzz_prog
  use fuzz_mod, only: g1
  implicit none
  integer, parameter :: n = 100, m = 8
  integer, allocatable :: ia(:)
  integer :: ib(n)
  integer :: i, j, r1a
  logical :: lt
  integer(8) :: cs
  allocate(ia(n))
  do i = 1, n
    ia(i) = mod(i * 4 + 30, 211) - 80
  end do
  do i = 1, n
    ib(i) = mod(i * 58 + 12, 97) - 31
  end do
  r1a = 15
  lt = .true.
  !$omp target map(tofrom: r1a)
    !$omp parallel
      !$omp do
      do i = 1, n
        do j = m, 1, -1
          !$omp critical
          r1a = ieor(r1a, ((ib((mod(((j * 1) + 2), n) + 1)) + ib(32)) - ia(i)))
          !$omp end critical
        end do
      end do
      !$omp end do
    !$omp end parallel
  !$omp end target
  cs = 0
  cs = modulo(cs * 31_8 + int(r1a, 8), 2147483629_8)
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
