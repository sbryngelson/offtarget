program fuzz_prog
  implicit none
  integer, parameter :: n = 100, m = 5
  integer, allocatable :: ia(:)
  integer, allocatable :: ib(:)
  integer, allocatable :: ic(:, :)
  integer :: o1(n, m)
  integer :: i, j, r1a, r1b, hf1
  integer(8) :: cs
  allocate(ia(n))
  allocate(ib(n))
  allocate(ic(n, m))
  do i = 1, n
    ia(i) = mod(i * 12 + 1, 1009) - 250
  end do
  do i = 1, n
    ib(i) = mod(i * 54 + 38, 211) - 26
  end do
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 6 * j) * 33 + 24, 1009) - 451
    end do
  end do
  o1 = 0
  r1a = -11
  r1b = 65535
  hf1 = 0
  !$omp target teams map(tofrom: hf1) reduction(max: r1a) reduction(iand: r1b)
    !$omp distribute dist_schedule(static, 2)
    do i = 1, n
      !$omp parallel do reduction(max: r1a) reduction(iand: r1b) num_threads(64) proc_bind(primary)
      do j = 1, m
        o1(i, j) = ia((mod(((j * 4) + 5), n) + 1))
        r1a = max(r1a, 0)
        r1b = iand(r1b, (ishft(iand(i, 1023), (-1)) + min(ic(i, (6 - j)), ic(i, (6 - j)))))
      end do
    end do
  !$omp end target teams
  cs = 0
  cs = modulo(cs * 31_8 + int(r1a, 8), 2147483629_8)
  cs = modulo(cs * 31_8 + int(r1b, 8), 2147483629_8)
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o1(i, j), 8), 2147483629_8)
    end do
  end do
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
