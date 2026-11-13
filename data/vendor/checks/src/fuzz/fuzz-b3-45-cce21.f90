program fuzz_prog
  implicit none
  integer, parameter :: n = 64, m = 5
  type :: rec_t
  end type rec_t
  type(rec_t) :: dr
  integer :: ib(n)
  integer, allocatable :: ic(:, :)
  integer, pointer :: o1(:)
  integer :: o2(n, m)
  integer, target :: o1t(n)
  integer :: i, j, jj, p2
  integer(8) :: cs
  allocate(ic(n, m))
  o1 => o1t
  do i = 1, n
    ib(i) = mod(i * 4 + 15, 1009) - 364
  end do
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 8 * j) * 29 + 24, 1009) - 73
    end do
  end do
  o1 = 0
  o2 = 0
  p2 = 8
  call kp2(ic, o2, dr, p2)
  cs = 0
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o1t(i), 8), 2147483629_8)
  end do
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o2(i, j), 8), 2147483629_8)
    end do
  end do
  print '(a,i0)', 'RESULT checksum=', cs
contains
  subroutine kp1(ib, ic, o1, dr, p2, zopt)
    integer, intent(in) :: ib(:)
    integer, allocatable, intent(in) :: ic(:, :)
    integer, pointer, intent(in) :: o1(:)
    type(rec_t), intent(inout) :: dr
    integer, value :: p2
    integer, intent(in), optional :: zopt(:)
    integer :: i, j, jj, acc1
  end subroutine kp1
  subroutine kp2(ic, o2, dr, p2, zopt)
    integer, intent(in) :: ic(:, :)
    integer, intent(inout) :: o2(:, :)
    type(rec_t), intent(inout) :: dr
    integer, intent(in), optional :: p2
    integer, intent(in), optional :: zopt(:)
    integer :: i, j, jj, t2
    !$omp target map(to: zopt)
    do i = 1, n
      !$omp parallel
        !$omp do private(t2)
        do j = m, 1, -1
          t2 = 0
        end do
        !$omp end do
      !$omp end parallel
    end do
    !$omp end target
  end subroutine kp2
end program fuzz_prog
