program p
  use omp_lib
  implicit none
  integer :: team(64), nt, i
  team = -1; nt = -1
  !$omp target teams distribute parallel do map(from: team, nt) num_teams(4) dist_schedule(static, 4)
  do i = 1, 64
    team(i) = omp_get_team_num()
    if (i == 1) nt = omp_get_num_teams()
  end do
  print '(a,i0,a,64(1x,i0))', 'nt=', nt, ' team:', team
end program p
