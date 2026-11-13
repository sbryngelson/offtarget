module mm
  implicit none
  integer, parameter :: n = 128
  type :: el_t
    integer :: u
  end type el_t
contains
  subroutine kp1(ia, o1, dsi)
    integer, allocatable, intent(inout) :: ia(:)
    integer, intent(inout) :: o1(:)
    integer, intent(in) :: dsi(:)
    integer :: i
    !$omp target map(tofrom: ia) map(tofrom: o1)
      do i = 1, n
        o1(i) = dsi(i)
      end do
    !$omp end target
  end subroutine kp1
end module mm
program p
  use mm
  implicit none
  type(el_t) :: ds(n)
  integer :: dsi(n)
  integer, allocatable :: ia(:)
  integer, pointer :: o1(:)
  integer :: i
  logical :: ok
  allocate(ia(n))
  ia = 1
  allocate(o1(n))
  do i = 1, n
    dsi(i) = mod(i * 26 + 31, 97) - 21
  end do
  o1 = 0
  call kp1(ia, o1, dsi)
  ok = .true.
  do i = 1, n
    ok = ok .and. o1(i) == mod(i * 26 + 31, 97) - 21
  end do
  if (ok) then
    print '(a)', 'RESULT check=pass'
  else
    print '(a)', 'RESULT check=fail'
  end if
end program p
