! Kernel 4 of fuzz x0-alloc:197 alone: task_reduction(+)
! and target in_reduction(+) in an internal subroutine on a host-associated
! variable. Expected: r= 139
program p
  implicit none
  integer :: r
  r = 3
  call kp1()
  print '(a,i0)', 'r= ', r
contains
  subroutine kp1()
    integer :: i
    !$omp taskgroup task_reduction(+: r)
      !$omp target in_reduction(+: r)
        do i = 1, 16
          r = r + i
        end do
      !$omp end target
    !$omp end taskgroup
  end subroutine kp1
end program p
