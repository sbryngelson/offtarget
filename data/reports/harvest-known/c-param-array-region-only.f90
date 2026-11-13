! control for v-param-array-routine: a module named-constant array
! indexed in the target region itself, the module having no procedure (the
! earlier c-param-array-region.f90 kept the unused declare target routine)
! expected: check=pass
module vpo_m
  implicit none
  real(8), parameter :: c(2) = [1.5d0, 2.5d0]
end module vpo_m

program vpo
  use omp_lib
  use vpo_m
  implicit none
  integer :: k, bad, hk_host
  real(8) :: r(100)
  r = 0
  !$omp target teams distribute parallel do map(from: r)
  do k = 1, 100
    r(k) = c(1 + mod(k, 2))
  end do
  bad = 0
  do k = 1, 100
    if (r(k) /= c(1 + mod(k, 2))) bad = bad + 1
  end do
  hk_host = 1
  !$omp target map(tofrom: hk_host)
  if (.not. omp_is_initial_device()) hk_host = 0
  !$omp end target
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hk_host, ' check=', merge('pass', 'fail', bad == 0)
end program vpo
