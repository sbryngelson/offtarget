program fuzz_prog
  use omp_lib, only: omp_get_thread_num
  implicit none
  integer, parameter :: n = 100, m = 8
  integer, allocatable :: ib(:)
  integer :: o1(n)
  integer :: i, j, r1a
  integer(8) :: cs
  allocate(ib(n))
  do i = 1, n
    ib(i) = mod(i * 18 + 43, 97) - 44
  end do
  o1 = 0
  r1a = -1
  !$omp target map(tofrom: r1a)
    !$omp parallel
      if (omp_get_thread_num() == 0) then
        do i = n, 1, -1
          r1a = r1a * 0
        end do
      end if
    !$omp end parallel
  !$omp end target
  cs = 0
  cs = modulo(cs * 31_8 + int(r1a, 8), 2147483629_8)
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o1(i), 8), 2147483629_8)
  end do
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
