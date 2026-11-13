module fuzz_mod
  implicit none
contains
end module fuzz_mod
program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 128, m = 5
  type :: rec_t
  end type rec_t
  type(rec_t) :: dr
  integer :: ia(n)
  integer, allocatable :: ib(:)
  integer, allocatable :: ic(:, :)
  integer, allocatable :: o1(:)
  integer, pointer :: o2(:)
  integer, target :: o2t(n)
  integer :: i, j, p1, r1a, hf1
  integer(8) :: cs
  allocate(ib(n))
  allocate(ic(n, m))
  allocate(o1(n))
  o2 => o2t
  do i = 1, n
    ia(i) = mod(i * 35 + 30, 1009) - 462
  end do
  do i = 1, n
    ib(i) = mod(i * 22 + 36, 30011) - 8252
  end do
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 6 * j) * 36 + 12, 30011) - 539
    end do
  end do
  o1 = 0
  o2 = 0
  p1 = -6
  r1a = -5
  hf1 = 0
  call kp1(ia, ib, ic, o1, dr, p1)
  cs = 0
  cs = modulo(cs * 31_8 + int(r1a, 8), 2147483629_8)
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o1(i), 8), 2147483629_8)
  end do
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o2t(i), 8), 2147483629_8)
  end do
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', max(hf1, 0)
contains
  subroutine kp1(ia, ib, ic, o1, dr, p1)
    integer, intent(in) :: ia(:)
    integer, intent(inout) :: ib(:)
    integer, intent(inout) :: ic(:, :)
    integer, intent(inout) :: o1(:)
    type(rec_t), intent(inout) :: dr
    integer, intent(in) :: p1
    !$omp taskgroup task_reduction(+: r1a)
      !$omp target map(tofrom: hf1) in_reduction(+: r1a)
        hf1 = merge(1, 0, omp_is_initial_device())
        do i = 1, n
          o1(i) = 1009
        end do
      !$omp end target
    !$omp end taskgroup
  end subroutine kp1
  subroutine kp2(ib, ic, o2, dr, zopt)
    integer, allocatable, intent(inout) :: ib(:)
    integer, intent(in) :: ic(:, :)
    integer, pointer, intent(in) :: o2(:)
    type(rec_t), intent(inout) :: dr
    integer, intent(in), optional :: zopt(:)
  end subroutine kp2
end program fuzz_prog
