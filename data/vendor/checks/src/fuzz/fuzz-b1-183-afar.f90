module fuzz_mod
  implicit none
contains
end module fuzz_mod
program fuzz_prog
  implicit none
  integer, parameter :: n = 24, m = 2
  integer :: ic(n, m)
  integer, allocatable :: o1(:, :)
  integer :: i, j, r1a
  integer(8) :: cs
  allocate(o1(n, m))
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 1 * j) * 20 + 50, 30011) - 2834
    end do
  end do
  o1 = 0
  r1a = 7
  !$omp target teams distribute map(tofrom: r1a)
  do i = 1, n
    !$omp parallel do
    do j = 1, m
      o1(i, j) = iand(ic(i, (mod(((j * 3) + 1), m) + 1)), 255)
      !$omp atomic
      r1a = min(r1a, mod(i, n))
    end do
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
