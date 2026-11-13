module fuzz_dmod
  implicit none
  type :: mt_t
  end type mt_t
end module fuzz_dmod
program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  use fuzz_dmod
  implicit none
  type :: rec_t
  end type rec_t
  type(rec_t) :: dr
  integer :: hf2
  !$omp target data map(tofrom: dr)
  !$omp end target data
contains
  subroutine kp1(dr)
    type(rec_t), intent(inout) :: dr
    !$omp target
      !$omp parallel
      !$omp end parallel
    !$omp end target
  end subroutine kp1
  subroutine kp2(ia, ic, xk1, xr8, dr, ms, p2)
    integer, intent(inout) :: ia(:)
    integer, allocatable, intent(inout) :: ic(:, :)
    integer(kind=1), intent(inout) :: xk1(:)
    real(kind=8), intent(in) :: xr8(:)
    type(rec_t), intent(inout) :: dr
    type(mt_t), intent(inout) :: ms
    integer, intent(in), optional :: p2
    !$omp target &
    !$omp& map(tofrom: hf2)
      !$omp masked
        hf2 = merge(1, 0, omp_is_initial_device())
      !$omp end masked
    !$omp end target
  end subroutine kp2
end program fuzz_prog
