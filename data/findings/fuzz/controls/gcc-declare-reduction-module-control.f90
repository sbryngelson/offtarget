! Control of fuzz/gcc-declare-reduction-module-not-found.f90: the declare reduction directive in the program's own
! specification part (compiles; correct on gcc_g90 and gcc_sm80).
module pair_m
  implicit none
  type :: pair_t
    integer :: a, b
  end type pair_t
end module pair_m

program udr_use_association
  use omp_lib, only: omp_is_initial_device
  use pair_m
  implicit none
  type(pair_t) :: s
  !$omp declare reduction(padd: pair_t: omp_out = &
  !$omp& pair_t(omp_out%a + omp_in%a, omp_out%b + omp_in%b)) &
  !$omp& initializer(omp_priv = pair_t(0, 0))
  integer :: i, host_flag
  s = pair_t(0, 0)
  host_flag = 1
  !$omp target teams distribute parallel do reduction(padd: s) map(tofrom: s, host_flag)
  do i = 1, 100
    if (i == 1) host_flag = merge(1, 0, omp_is_initial_device())
    s%a = s%a + i
    s%b = s%b + 1
  end do
  print '(a,i0,a,i0)', 's%a= ', s%a, ' s%b= ', s%b
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', s%a == 5050 .and. s%b == 100)
end program udr_use_association
