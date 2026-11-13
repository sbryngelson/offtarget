program fuzz_prog
  use omp_lib, only: omp_get_thread_num
  implicit none
  integer, parameter :: n = 48, m = 8
  integer, allocatable :: o1(:)
  integer :: i, j
  integer(8) :: cs
  allocate(o1(n))
  o1 = 0
  !$omp target parallel
    if (omp_get_thread_num() == 0) then
      do i = 1, n
        o1(i) = i
      end do
    end if
  !$omp end target parallel
  cs = 0
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o1(i), 8), 2147483629_8)
  end do
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
