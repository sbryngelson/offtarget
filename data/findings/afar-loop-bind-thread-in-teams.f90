! loop bind(thread) closely nested in teams (README.md). Expected: tot= 64 64 64 64,
! which CCE prints as `tot= 4*64` (a list-directed repeat count: the same values,
! a correction). Each team's mine is private (teams private(tm, mine)) and the loop's
! binding thread set is the encountering thread, so no race (offload.engine.prerun's race rule
! flags mine: a false positive).
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
! site:
! title: amdflang: loop bind(thread) closely nested in teams rejected ("BIND(TEAMS) must be specified")
! control: ../vendor/checks/src/afar/control/afar-loop-bind-thread-in-teams-control.f90 the loop directive removed (a plain DO
! + loop in
! + each team)
! end site
! spec (requirement): With bind(thread) the binding region of a loop construct is not defined.
! "if binding is thread then the binding region is not defined" (5.2 §11.7.1 p.258 l.24-25)
! spec (requirement): When the binding region is not defined, the binding thread set is the encountering thread, so
!   each thread executes all iterations of the loop it encounters.
! "If the binding region is not defined, then the binding thread set is the encountering thread." (5.2 §11.7.1 p.258
!   l.31-32)
! spec (requirement): The bind clause is required only when the loop construct is not nested inside another OpenMP
!   construct.
! "If a loop construct is not nested inside another OpenMP construct then the bind clause must be present." (5.2 §11.7
!   p.258 l.1-2)
! spec (this program): The loop bind(thread) is closely nested in teams, so each team's initial thread runs all 64
!   iterations on its private mine and tot is 64 for every team; amdflang rejects the construct with BIND(TEAMS) must
!   be specified.
