! control for v-param-array-routine: the named-constant array
! declared in the declare target routine itself (not the module).
! expected: check=pass
module vpa_m
  implicit none
  real(8), parameter :: c(2) = [1.5d0, 2.5d0]
contains
  subroutine pick(i, x)
    !$omp declare target
    integer, intent(in) :: i
    real(8), intent(out) :: x
    real(8), parameter :: cl(2) = [1.5d0, 2.5d0]
    x = cl(i)
  end subroutine pick
end module vpa_m

program vpa
  use omp_lib
  use vpa_m
  implicit none
  integer :: k, bad, hk_host
  real(8) :: r(100)
  r = 0
  !$omp target teams distribute parallel do map(from: r)
  do k = 1, 100
    call pick(1 + mod(k, 2), r(k))
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
end program vpa
