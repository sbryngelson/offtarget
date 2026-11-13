program fuzz_prog
  use omp_lib, only: omp_get_default_device
  implicit none
  integer, parameter :: n = 32, m = 3
  integer :: o1(n, m)
  integer :: i, j
  logical :: lsimd
  integer(8) :: cs
  o1 = 0
  lsimd = .true.
  !$omp target
    !$omp teams
      !$omp distribute
      do i = 1, n, 2
        !$omp parallel firstprivate(i)
          !$omp do
          do j = 1, m
            o1(i, j) = j
          end do
        !$omp end parallel
      end do
    !$omp end teams
  !$omp end target
  cs = 0
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o1(i, j), 8), 2147483629_8)
    end do
  end do
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
