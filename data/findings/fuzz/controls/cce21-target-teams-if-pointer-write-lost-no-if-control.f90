program fuzz_prog
  use omp_lib, only: omp_get_thread_num, omp_is_initial_device
  implicit none
  integer, parameter :: n = 24, m = 5
  integer, pointer :: o2(:)
  real(8), pointer :: o1(:)
  integer :: i, j, hf1, t2
  logical :: lt
  integer(8) :: cs
  allocate(o1(n))
  allocate(o2(n))
  o1 = 0
  o2 = 0
  hf1 = 0
  lt = .true.
  ! fuzz: kernels
  !$omp target map(tofrom: hf1)
    if (omp_get_thread_num() == 0) hf1 = merge(1, 0, omp_is_initial_device())
  !$omp end target
  !$omp taskwait
  do i = 1, n
  end do
  !$omp target teams
    !$omp loop private(t2)
    do i = 1, n
      t2 = 0
      o2(i) = 255
    end do
  !$omp end target teams
  ! fuzz: checksum
  cs = 0
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o1(i) * 64, 8), 2147483629_8)
  end do
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o2(i), 8), 2147483629_8)
  end do
  print '(a,i0)', 'checksum= ', cs
  print '(a,i0,a,a)', 'RESULT ran_on_host=', max(hf1, 0), ' check=', merge('pass', 'fail', cs == 1099183000_8)
end program fuzz_prog
