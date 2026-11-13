! variant of hk-040: target data use_device_ptr(cp), cp a C_PTR to
! an allocatable mapped with enter data; prints the host address of tab, the
! address omp_get_mapped_ptr returns (OpenMP 5.1 §18.8.11), the address the
! region sees, and the address of cp itself.
! expected: check=pass
program v040pp
  use iso_c_binding
  use omp_lib
  implicit none
  integer, parameter :: n = 1024
  integer, allocatable, target :: tab(:)
  type(c_ptr), target :: cp
  type(c_ptr) :: p_ptr, p_map
  integer :: hk_host
  allocate(tab(n))
  tab = 7
  !$omp target enter data map(to: tab)
  p_map = omp_get_mapped_ptr(c_loc(tab), omp_get_default_device())
  cp = c_loc(tab)
  !$omp target data use_device_ptr(cp)
  p_ptr = cp
  !$omp end target data
  !$omp target exit data map(delete: tab)
  print '(a,z0)', 'host   ', transfer(c_loc(tab), 0_c_intptr_t)
  print '(a,z0)', 'mapped ', transfer(p_map, 0_c_intptr_t)
  print '(a,z0)', 'seen   ', transfer(p_ptr, 0_c_intptr_t)
  print '(a,z0)', 'loc(cp) ', transfer(c_loc(cp), 0_c_intptr_t)
  hk_host = 1
  !$omp target map(tofrom: hk_host)
  if (.not. omp_is_initial_device()) hk_host = 0
  !$omp end target
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hk_host, ' check=', merge('pass', 'fail', c_associated(p_ptr, p_map))
end program v040pp
