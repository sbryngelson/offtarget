program fuzz_prog
  implicit none
  integer, parameter :: n = 100
  integer :: i, r1b
  integer(8) :: cs
  r1b = -1
  !$omp target
    !$omp do
    do i = 1, n
      !$omp atomic
      r1b = r1b * merge((-1), 1, mod(i, 13) == 0)
    end do
    !$omp end do
  !$omp end target
  cs = 0
  cs = modulo(cs * 31_8 + int(r1b, 8), 2147483629_8)
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
