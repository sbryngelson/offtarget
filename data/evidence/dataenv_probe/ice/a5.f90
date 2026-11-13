program fuzz_prog
  use omp_lib, only: omp_get_thread_num, omp_is_initial_device
  implicit none
  integer, parameter :: n = 200, m = 4
  type :: nd_t
  end type nd_t
  type :: rec_t
    type(nd_t) :: nd
  end type rec_t
  type :: el_t
  end type el_t
  type(rec_t) :: dr
  type(el_t) :: ds(n)
  integer, allocatable :: o1(:)
  character(len=8) :: xs
  integer :: i, j
  integer(8) :: cs
  allocate(o1(n))
  xs = 'CgsklFig'
  o1 = 0
  ! fuzz: kernels
  !$omp target exit data map(delete: xs)
  ! fuzz: checksum
  cs = 0
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o1(i), 8), 2147483629_8)
  end do
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', 0
contains
  subroutine kp1(o1, dr, zopt)
    integer, intent(inout) :: o1(:)
    type(rec_t), intent(inout) :: dr
    integer, intent(in), optional :: zopt(:)
  end subroutine kp1
end program fuzz_prog
