program p
  implicit none
  integer :: r, i
  r = 0
  !$omp taskgroup task_reduction(max: r)
    !$omp target in_reduction(max: r)
      do i = 1, 10
        r = max(r, i)
      end do
    !$omp end target
  !$omp end taskgroup
  print *, 'r =', r
end program p
