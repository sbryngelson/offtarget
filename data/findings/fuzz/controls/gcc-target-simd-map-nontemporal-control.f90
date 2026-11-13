! Control of fuzz/gcc-target-simd-map-nontemporal-rejected.f90: the same construct without nontemporal (compiles; correct
! on gcc_g90 and gcc_sm80).
program target_simd_map_nontemporal
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer :: o(n), i, bad, host_flag
  o = 0
  host_flag = 1
  !$omp target map(tofrom: host_flag)
    host_flag = merge(1, 0, omp_is_initial_device())
  !$omp end target
  ! map applies to the target leaf, nontemporal to the simd leaf
  !$omp target simd map(tofrom: o)
  do i = 1, n
    o(i) = 2 * i
  end do
  bad = count(o /= [(2 * i, i = 1, n)])
  print '(a,i0)', 'bad= ', bad
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', bad == 0)
end program target_simd_map_nontemporal
