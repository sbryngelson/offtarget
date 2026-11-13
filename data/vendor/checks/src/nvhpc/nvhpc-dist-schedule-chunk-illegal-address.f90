program p
  implicit none
  integer :: b(64), i
  b = 0
  !$omp target teams distribute parallel do map(from: b) num_teams(4) &
  !$omp& dist_schedule(static, 4)
  do i = 1, 64
    b(i) = i
  end do
  print *, 'sum', sum(b)
end program p
