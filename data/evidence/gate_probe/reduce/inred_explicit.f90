! Control for inred_assumed.f90 (explicit-shape dummies): a target region with
! in_reduction(+: r), in a taskgroup with task_reduction(+: r), inside a
! procedure whose assumed-shape dummy arrays it maps (OpenMP 5.2 §5.5.9,
! §5.5.10; assumed-shape arrays are mappable, §5.8.3).
! Expected: r= 139 y(16)= 32
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
    integer, intent(in) :: x(n)
    integer, intent(inout) :: y(n)
    integer :: i
    !$omp taskgroup task_reduction(+: r)
      !$omp target map(to: x) map(tofrom: y) in_reduction(+: r)
        do i = 1, n
          y(i) = 2 * x(i)
          r = r + x(i)
        end do
      !$omp end target
    !$omp end taskgroup
  end subroutine k
end program p
