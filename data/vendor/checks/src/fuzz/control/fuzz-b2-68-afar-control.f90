program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 200, m = 8
  integer :: i, j, r3a, hf3
  logical :: lpar
  integer(8) :: cs
  r3a = 31
  hf3 = 0
  lpar = .true.
  !$omp target map(tofrom: hf3) map(tofrom: r3a)
    hf3 = merge(1, 0, omp_is_initial_device())
    !$omp parallel if(parallel: lpar)
      !$omp loop reduction(+: r3a)
      do i = 1, n
        do j = m, 1, -1
          r3a = r3a + 11
        end do
      end do
      !$omp end loop
    !$omp end parallel
  !$omp end target
  cs = 0
  cs = modulo(cs * 31_8 + int(r3a, 8), 2147483629_8)
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', max(hf3, 0)
end program fuzz_prog
