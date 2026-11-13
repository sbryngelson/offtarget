program t
  use omp_lib, only: omp_get_team_num
  implicit none
  integer, parameter :: n = 64
  integer :: tot(4), tm, mine, i
  tot = 0
  !$omp target map(tofrom: tot)
    !$omp teams num_teams(4) private(tm, mine)
      tm = omp_get_team_num()
      mine = 0
      !$omp loop bind(thread)
        do i = 1, n
          mine = mine + 1
        end do
      !$omp end loop
      tot(tm + 1) = mine
    !$omp end teams
  !$omp end target
  print *, 'tot=', tot
end program
