program fuzz_prog
  use omp_lib, only: omp_get_thread_num
  implicit none
  integer, parameter :: n = 48, m = 8
  integer :: i, j, r1a
  integer(8) :: cs
  r1a = 2
  !$omp target parallel map(tofrom: r1a)
    if (omp_get_thread_num() == 0) then
      do i = 1, n, 2
        r1a = ior(r1a, i)
      end do
    end if
  !$omp end target parallel
  cs = 0
  cs = modulo(cs * 31_8 + int(r1a, 8), 2147483629_8)
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
