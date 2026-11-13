program p
  use omp_lib
  use, intrinsic :: iso_c_binding, only: c_loc
  implicit none
  integer, target :: a(64)
  integer :: d
  a = 1
  d = omp_get_default_device()
  !$omp target enter data map(to: a)
  print *, 'after enter data: present=', omp_target_is_present(c_loc(a), d)
  !$omp target exit data map(release: a)
  print *, 'after exit data: present=', omp_target_is_present(c_loc(a), d)
end program p
