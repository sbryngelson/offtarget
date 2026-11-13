! variant of hk-040: only target data use_device_ptr(cp), cp a
! C_PTR to an allocatable mapped with enter data; compared with
! omp_get_mapped_ptr (OpenMP 5.1 §18.8.11).
! expected: check=pass
program v040p
  use iso_c_binding
  use omp_lib
  implicit none
  integer, parameter :: n = 1024
  integer, allocatable, target :: tab(:)
  type(c_ptr) :: cp, p_ptr, p_map
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
  hk_host = 1
  !$omp target map(tofrom: hk_host)
  if (.not. omp_is_initial_device()) hk_host = 0
  !$omp end target
  print '(a,l1)', 'same address: ', c_associated(p_ptr, p_map)
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hk_host, ' check=', merge('pass', 'fail', c_associated(p_ptr, p_map))
end program v040p
