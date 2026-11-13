module fuzz_mod
  implicit none
contains
  integer function g1(x, y)
    !$omp declare target
    integer, intent(in) :: x, y
    g1 = mod(iand(max(7, x), y), 1009)
  end function g1
end module fuzz_mod
program fuzz_prog
  use fuzz_mod, only: g1
  implicit none
  integer, parameter :: n = 24, m = 2
  integer, allocatable :: ia(:)
  integer, allocatable :: o1(:)
  integer, allocatable :: o2(:, :)
  integer, allocatable :: o3(:, :)
  integer :: i, j, p1, r3b
  logical :: lpar
  integer(8) :: cs
  allocate(ia(n))
  allocate(o1(n))
  allocate(o2(n, m))
  allocate(o3(n, m))
  do i = 1, n
    ia(i) = mod(i * 24 + 3, 211) - 93
  end do
  o1 = 0
  o2 = 0
  o3 = 0
  p1 = -5
  r3b = 78
  lpar = .false.
  !$omp target map(tofrom: r3b)
    !$omp parallel if(parallel: lpar)
      !$omp do reduction(min: r3b)
      do i = n, 1, -1
        do j = m, 1, -1
          o3(i, j) = o2(i, j)
          r3b = min(r3b, g1(o2(i, (mod(((j * 7) + 6), m) + 1)), p1))
        end do
      end do
    !$omp end parallel
  !$omp end target
  cs = 0
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o1(i), 8), 2147483629_8)
  end do
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o2(i, j), 8), 2147483629_8)
    end do
  end do
  cs = modulo(cs * 31_8 + int(r3b, 8), 2147483629_8)
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o3(i, j), 8), 2147483629_8)
    end do
  end do
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
