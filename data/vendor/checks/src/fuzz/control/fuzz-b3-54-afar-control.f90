program fuzz_prog
  implicit none
  integer, parameter :: n = 32, m = 5
  type :: rec_t
    integer, allocatable :: q(:)
  end type rec_t
  type(rec_t) :: dr
  integer, allocatable, target :: ic(:, :)
  integer, pointer :: o1(:)
  integer :: i, j, p1, hf1
  integer(8) :: cs
  allocate(ic(n, m))
  allocate(dr%q(n))
  allocate(o1(n))
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 8 * j) * 26 + 35, 97) - 30
    end do
  end do
  do i = 1, n
    dr%q(i) = mod(i * 6 + 6, 1009) - 171
  end do
  o1 = 0
  p1 = -3
  hf1 = 0
  !$omp target nowait depend(in: p1) depend(inout: hf1, ic, o1)
  !$omp end target
  !$omp taskwait
  cs = 0
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o1(i), 8), 2147483629_8)
  end do
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
