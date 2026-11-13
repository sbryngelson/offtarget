module fuzz_dmod
  implicit none
  type :: mt_t
  end type mt_t
  type :: pair_t
    integer :: x, y
  end type pair_t
  !$omp declare reduction(padd: pair_t: omp_out = pair_t(omp_out%x + omp_in%x, omp_out%y + omp_in%y)) &
  !$omp& initializer(omp_priv = pair_t(0, 0))
end module fuzz_dmod
module fuzz_smod
  implicit none
  interface
    module integer function gs1(x)
      integer, intent(in) :: x
    end function gs1
  end interface
end module fuzz_smod
submodule (fuzz_smod) fuzz_ssub
  implicit none
contains
  module integer function gs1(x)
    integer, intent(in) :: x
  end function gs1
end submodule fuzz_ssub
program fuzz_prog
  use fuzz_dmod
  implicit none
  integer, parameter :: n = 100, m = 5
  type :: rec_t
    integer, allocatable :: o1(:)
  end type rec_t
  type(pair_t) :: rp2a
  integer :: i, r1a
contains
  subroutine kp1(xr4, dr)
    real(4), allocatable, intent(in) :: xr4(:)
    type(rec_t), intent(inout) :: dr
    !$omp target teams map(tofrom: dr) reduction(min: r1a)
    !$omp end target teams
  end subroutine kp1
  subroutine kp2(ic, xk1, xr4, dr, ms)
    integer, intent(inout) :: ic(:, :)
    integer(1), allocatable, intent(in) :: xk1(:)
    real(4), intent(in) :: xr4(:)
    type(rec_t), intent(inout) :: dr
    type(mt_t), intent(inout) :: ms
    !$omp target teams loop reduction(padd: rp2a)
    do i = 1, n
    end do
  end subroutine kp2
end program fuzz_prog
