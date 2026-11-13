program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 200
  integer, allocatable :: o3(:)
  integer :: i, r3a, hf3
  integer(8) :: cs
  allocate(o3(n))
  o3 = 0
  r3a = 45
  hf3 = 0
  call kp2(o3)
  cs = 0
  cs = modulo(cs * 31_8 + int(r3a, 8), 2147483629_8)
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o3(i), 8), 2147483629_8)
  end do
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', max(hf3, 0)
contains
  subroutine kp2(o3)
    integer, intent(inout) :: o3(n)
      !$omp target map(tofrom: hf3)
        hf3 = merge(1, 0, omp_is_initial_device())
        do i = 1, n
          o3(i) = 9973
        end do
      !$omp end target
  end subroutine kp2
end program fuzz_prog
