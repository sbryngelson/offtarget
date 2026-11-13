! Fresh-084 variant: vn_aux allocatable instead of automatic.
module sup
  implicit none
contains
  subroutine max_per_level(nb, nlev, vn, vmax)
    integer, intent(in) :: nb, nlev
    real(8), intent(in) :: vn(nb, nlev)
    real(8), intent(out) :: vmax(nlev)
    real(8), allocatable :: vn_aux(:,:)
    integer :: jb, jk
    allocate(vn_aux(nb, nlev))
    !$acc data copyin(vn) copyout(vn_aux)
    !$acc kernels
    vn_aux(:,:) = 0.0d0
    !$acc end kernels
    !$acc parallel loop collapse(2)
    do jk = 1, nlev
      do jb = 1, nb
        vn_aux(jb, jk) = abs(vn(jb, jk))
      end do
    end do
    !$acc end data
    do jk = 1, nlev
      vmax(jk) = maxval(vn_aux(:, jk))
    end do
  end subroutine max_per_level
end module sup

program main
  use sup
  implicit none
  real(8) :: vn(20, 5), vmax(5)
  integer :: jb, jk
  do jk = 1, 5
    do jb = 1, 20
      vn(jb, jk) = -real(jb * jk, 8)
    end do
  end do
  call max_per_level(20, 5, vn, vmax)
  if (all(vmax == [20.0d0, 40.0d0, 60.0d0, 80.0d0, 100.0d0])) then
    print *, 'wild-check: pass'
  else
    print *, 'wild-check: fail', vmax
  end if
end program main
