! Fuzz x0-alloc:197 reduced: a target region with
! in_reduction(+: r), in a taskgroup with task_reduction(+: r), inside an
! internal procedure that maps two assumed-shape dummy arrays and a
! host-associated scalar h, which the region writes (OpenMP 5.2 §5.5.9,
! §5.5.10; §5.8.3: the dummies and h are mappable list items).
! Expected: r= 3 h= 1 y(16)= 32
program p
  implicit none
  integer, parameter :: n = 16
  integer :: a(n), b(n), r, h, i
  do i = 1, n
    a(i) = i
    b(i) = 0
  end do
  r = 3
  h = 0
  call k(a, b)
  print '(a,i0,a,i0,a,i0)', 'r= ', r, ' h= ', h, ' y(16)= ', b(n)
contains
  subroutine k(x, y)
    integer, intent(in) :: x(:)
    integer, intent(inout) :: y(:)
    integer :: i
    !$omp taskgroup task_reduction(+: r)
      !$omp target map(to: x) map(tofrom: y, h) in_reduction(+: r)
        h = 1
        do i = 1, n
          y(i) = 2 * x(i)
        end do
      !$omp end target
    !$omp end taskgroup
  end subroutine k
end program p
