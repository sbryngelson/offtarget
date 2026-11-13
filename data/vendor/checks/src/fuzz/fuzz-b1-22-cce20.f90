program fuzz_prog
  use omp_lib, only: omp_get_default_device, omp_get_thread_num
  implicit none
  integer, parameter :: n = 32, m = 3
  integer :: i, j, p2, lp1
  integer(8) :: cs
  p2 = 8
  lp1 = 0
  !$omp target teams map(tofrom: lp1)
    !$omp distribute lastprivate(lp1)
    do i = 1, n
      !$omp parallel do lastprivate(lp1)
      do j = m, 1, -1
        lp1 = p2
      end do
      !$omp end parallel do
    end do
    !$omp end distribute
  !$omp end target teams
  cs = 0
  cs = modulo(cs * 31_8 + int(lp1, 8), 2147483629_8)
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
