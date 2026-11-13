program fuzz_prog
  use omp_lib, only: omp_get_team_num, omp_get_thread_num
  implicit none
  integer, parameter :: n = 200, m = 2
  integer :: i, j, r1a
  integer(8) :: cs
  r1a = 4
  !$omp target map(tofrom: r1a) defaultmap(tofrom: scalar)
    if (omp_get_team_num() == 0) then
      do i = n, 1, -1
        r1a = ior(r1a, i)
      end do
    end if
  !$omp end target
  cs = 0
  cs = modulo(cs * 31_8 + int(r1a, 8), 2147483629_8)
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
