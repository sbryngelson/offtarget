! Kernel 2 of fuzz x0-alloc:197 alone: a target region
! with in_reduction(*: r) in a taskgroup with task_reduction(*: r) (OpenMP
! 5.2 §5.5.9, §5.5.10). Expected: r= -2
program p
  implicit none
  integer, parameter :: n = 16
  integer :: i, r, b(n)
  do i = 1, n
    b(i) = i
  end do
  r = 2
  !$omp taskgroup task_reduction(*: r)
    !$omp target map(to: b) in_reduction(*: r)
      do i = 1, n
        r = r * merge(-1, 1, mod(b(i), 16) == 0)
      end do
    !$omp end target
  !$omp end taskgroup
  print '(a,i0)', 'r= ', r
end program p
