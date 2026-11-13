! Docs/findings/apps/cce20-device-link-infer-address-spaces-crash.f90: CONTROL: the index ranges as plain
! integer module variables (declare target) instead of components of a derived-type variable. Expected and
! observed on CCE 19, 20, 21 and AFAR (MI300A XNACK 1 and 0, MI250X): builds, bad= 0.
module glob
  implicit none
  integer, parameter :: wp = kind(1.d0)
  integer :: num_dims, num_fluids, sys_size
  integer :: cont_end, mom_beg, mom_end
  !$omp declare target (num_dims, num_fluids, sys_size, cont_end, mom_beg, mom_end)
end module glob

module fill
  use glob
  implicit none
  ! CCE's compile-time inlining off for the two helpers: they are inlined at the device link (LTO)
  !DIR$ INLINENEVER s_fill_density, s_fill_velocity
contains
  subroutine s_fill_density(L, lambda2, c, mf, drho, dp)
    !$omp declare target
    real(wp), dimension(sys_size), intent(inout) :: L
    real(wp), dimension(num_fluids), intent(in) :: mf, drho
    real(wp), intent(in) :: lambda2, c, dp
    integer :: i
    do i = 2, mom_beg
      L(i) = lambda2*(c*c*drho(i - 1) - mf(i - 1)*dp)
    end do
  end subroutine s_fill_density
  subroutine s_fill_velocity(L, lambda2, dvel)
    !$omp declare target
    real(wp), dimension(sys_size), intent(inout) :: L
    real(wp), dimension(num_dims), intent(in) :: dvel
    real(wp), intent(in) :: lambda2
    integer :: i
    do i = mom_beg + 1, mom_end
      L(i) = lambda2*dvel(i - cont_end)
    end do
  end subroutine s_fill_velocity
  subroutine s_outflow(lambda, L, c, mf, drho, dp, dvel)
    !$omp declare target
    real(wp), dimension(3), intent(in) :: lambda
    real(wp), dimension(sys_size), intent(inout) :: L
    real(wp), dimension(num_fluids), intent(in) :: mf, drho
    real(wp), dimension(num_dims), intent(in) :: dvel
    real(wp), intent(in) :: c, dp
    call s_fill_density(L, lambda(2), c, mf, drho, dp)
    call s_fill_velocity(L, lambda(2), dvel)
  end subroutine s_outflow
end module fill

program cce20_infer_address_spaces
  use fill
  implicit none
  integer, parameter :: nr = 64
  real(wp), allocatable :: out(:, :)
  real(wp) :: L(5), mf(2), drho(2), dvel(3)
  real(wp) :: lambda(3), c, dp, expect
  integer :: r, i, bad
  num_dims = 3; num_fluids = 2
  cont_end = num_fluids
  mom_beg = cont_end + 1; mom_end = cont_end + num_dims
  sys_size = mom_end
  !$omp target update to(num_dims, num_fluids, sys_size, cont_end, mom_beg, mom_end)
  allocate(out(sys_size, nr))
  out = 0
  !$omp target teams distribute parallel do private(L, mf, drho, dvel, lambda, c, dp, i) map(tofrom: out)
  do r = 1, nr
    do i = 1, num_fluids
      mf(i) = 0.5_wp*i
      drho(i) = 0.25_wp*i + r
    end do
    do i = 1, num_dims
      dvel(i) = 1._wp*i + r
    end do
    lambda = [1._wp, 2._wp, 3._wp]
    c = 2._wp; dp = 0.5_wp
    L = 0
    call s_outflow(lambda, L, c, mf, drho, dp, dvel)
    out(:, r) = L
  end do
  !$omp end target teams distribute parallel do
  bad = 0
  do r = 1, nr
    do i = 1, sys_size
      expect = 0
      if (i >= 2 .and. i <= 3) expect = 2*(4*(0.25_wp*(i - 1) + r) - 0.5_wp*(i - 1)*0.5_wp)
      if (i >= 4) expect = 2*(1._wp*(i - 2) + r)
      if (out(i, r) /= expect) bad = bad + 1
    end do
  end do
  print '(a,i0,a,5f8.2)', 'bad= ', bad, ' out(:,1)=', out(:, 1)
end program cce20_infer_address_spaces
