program p
  implicit none
  integer :: r, i
  r = 0
  !$omp taskgroup task_reduction(+: r)
    !$omp target in_reduction(+: r)
      do i = 1, 10
        r = r + i
      end do
    !$omp end target
  !$omp end taskgroup
  print *, 'r =', r
end program p
