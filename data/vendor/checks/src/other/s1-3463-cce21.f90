module fuzz_dmod
  implicit none
  type :: mt_t
  end type mt_t
  type :: pair_t
    integer :: x, y
  end type pair_t
  !$omp declare reduction(padd: pair_t: omp_out = pair_t(omp_out%x + omp_in%x, omp_out%y + omp_in%y)) &
  !$omp& initializer(omp_priv = pair_t(0, 0))
contains
end module fuzz_dmod
program fuzz_prog
  use omp_lib, only: omp_get_team_num, omp_get_thread_num
  use fuzz_dmod
  implicit none
  integer, parameter :: n = 48, m = 8
  type :: nd_t
    integer :: k(n)
  end type nd_t
  type :: rec_t
    type(nd_t) :: nd
  end type rec_t
contains
  subroutine kp2(ia, ib, ic, xs, xz4, xz8, dr, ms, zopt)
    integer, intent(inout) :: ia(:)
    integer, intent(in) :: ib(:)
    integer, intent(in) :: ic(n, m)
    character(len=*), intent(in) :: xs
    complex, intent(in) :: xz4(n)
    complex(kind=8), intent(in) :: xz8(n)
    type(rec_t), intent(inout) :: dr
    type(mt_t), intent(inout) :: ms
    integer, intent(in), optional :: zopt(:)
  end subroutine kp2
  subroutine kp3(ia, ib, o3, xc, dr)
    integer, intent(inout) :: ia(n)
    integer, intent(in) :: ib(n)
    integer, intent(inout) :: o3(n)
    character(len=4), intent(inout) :: xc(n)
    type(rec_t), intent(inout) :: dr
    !$omp target map(dr%nd%k(1:n))
      if (omp_get_team_num() == 0) then
      end if
    !$omp end target
  end subroutine kp3
end program fuzz_prog
