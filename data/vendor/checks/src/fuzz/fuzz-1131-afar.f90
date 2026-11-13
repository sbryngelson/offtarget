program fuzz_prog
  implicit none
  integer, parameter :: n = 16, m = 8
  integer, allocatable :: ia(:)
  integer :: ib(n)
  integer :: ic(n, m)
  integer :: o1(n)
  integer :: i, j
  integer(8) :: cs
  allocate(ia(n))
  do i = 1, n
    ia(i) = mod(i * 24 + 48, 30011) - 5205
  end do
  do i = 1, n
    ib(i) = mod(i * 24 + 3, 1009) - 72
  end do
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 9 * j) * 27 + 40, 211) - 68
    end do
  end do
  o1 = 0
  !$omp target enter data map(to: ia, ib, ic, o1)
  !$omp target map(close, present, to: ic)
  !$omp end target
  cs = 0
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o1(i), 8), 2147483629_8)
  end do
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
