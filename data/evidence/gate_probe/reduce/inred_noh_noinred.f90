! One-change control of inred_noh.f90: the taskgroup task_reduction and
! the in_reduction clause removed. Expected: r= 3 y(16)= 32
program p
  implicit none
  integer, parameter :: n = 16
  integer :: a(n), b(n), r, i
  do i = 1, n
    a(i) = i
    b(i) = 0
  end do
  r = 3
  call k(a, b)
  print '(a,i0,a,i0)', 'r= ', r, ' y(16)= ', b(n)
contains
  subroutine k(x, y)
    integer, intent(in) :: x(:)
    integer, intent(inout) :: y(:)
    integer :: i
      !$omp target map(to: x) map(tofrom: y)
        do i = 1, n
          y(i) = 2 * x(i)
        end do
      !$omp end target
  end subroutine k
end program p
