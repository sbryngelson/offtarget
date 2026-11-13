! The program of data/findings/cce21-in-reduction-assumed-shape-write-lost.f90:
! a target region with in_reduction(+: r) in a taskgroup with task_reduction(+: r), inside an
! internal procedure that maps two assumed-shape dummy arrays (r is not updated in the region).
! Expected: r= 3 y(16)= 32
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
    !$omp taskgroup task_reduction(+: r)
      !$omp target map(to: x) map(tofrom: y) in_reduction(+: r)
        do i = 1, n
          y(i) = 2 * x(i)
        end do
      !$omp end target
    !$omp end taskgroup
  end subroutine k
end program p
