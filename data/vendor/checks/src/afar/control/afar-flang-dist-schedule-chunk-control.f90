program gen_prog
  use omp_lib, only: omp_get_num_teams, omp_get_team_num, omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer, allocatable, target :: a(:), b(:)
  integer :: ref(n)
  integer :: i, host_flag
  logical :: ok
  integer :: team(n), nt
  logical :: dok
  allocate(a(n), b(n))
  do i = 1, n
    a(i) = i
    b(i) = 0
    ref(i) = 2*i + 1
  end do
  host_flag = 1
  team = -1
  nt = -1
  !$omp target teams distribute parallel do map(to: a) map(from: b) map(from: team, nt) &
  !$omp& map(tofrom: host_flag) default(none) shared(a, b, team, nt, host_flag) num_teams(1) &
  !$omp& dist_schedule(static, 4)
    do i = 1, n
      b(i) = 2*a(i) + 1
      team(i) = omp_get_team_num()
      if (i == 1) nt = omp_get_num_teams()
      if (i == 1) host_flag = merge(1, 0, omp_is_initial_device())
    end do
  !$omp end target teams distribute parallel do
  dok = .true.
  do i = 1, n
    dok = dok .and. team(i) == mod((i - 1)/4, nt)
  end do
  ok = all(b == ref) .and. (nt >= 1) .and. dok
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', ok)
  deallocate(a, b)
end program gen_prog
