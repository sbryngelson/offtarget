module fuzz_mod
  implicit none
contains
  integer function g1(x, y)
    !$omp declare target
    integer, intent(in) :: x, y
    g1 = mod(((x * mod(3, 3)) - x), 97)
  end function g1
  integer function g2(x, y)
    !$omp declare target
    integer, intent(in) :: x, y
    g2 = mod(ior(y, y), 1009)
  end function g2
end module fuzz_mod
program fuzz_prog
  use omp_lib, only: omp_get_default_device
  use fuzz_mod, only: g1, g2
  implicit none
  integer, parameter :: n = 48, m = 2
  integer :: ia(n)
  integer, allocatable :: ib(:)
  integer :: ic(n, m)
  integer :: o1(n)
  integer :: i, j
  integer(8) :: cs
  allocate(ib(n))
  do i = 1, n
    ia(i) = mod(i * 46 + 10, 211) - 53
  end do
  do i = 1, n
    ib(i) = mod(i * 15 + 21, 30011) - 9080
  end do
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 3 * j) * 30 + 28, 97) - 18
    end do
  end do
  o1 = 0
  !$omp target enter data map(to: ia, ib, ic, o1)
  !$omp target map(close, present, tofrom: ib(1:n))
  !$omp end target
  cs = 0
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o1(i), 8), 2147483629_8)
  end do
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
