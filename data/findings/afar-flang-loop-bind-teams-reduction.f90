program p
  implicit none
  integer :: r, i
  r = 0
  !$omp target teams map(tofrom: r)
    !$omp loop bind(teams) reduction(+: r)
    do i = 1, 10
      r = r + i
    end do
  !$omp end target teams
  print *, 'r =', r
end program p
! site:
! title: amdflang: reduction on loop bind(teams) nested in a target teams region rejected
! control: ../vendor/checks/src/afar/control/afar-flang-loop-bind-teams-reduction-control.f90 bind(teams) removed (the loop binds
! + to the
! + teams
! + region by default)
! end site
! spec (requirement): The reduction clause is permitted on the loop construct.
! "bind, collapse, lastprivate, order, private, reduction" (5.2 §11.7 p.257 l.4)
! spec (requirement): The behavior of a reduction clause on a loop with bind(teams) is unspecified only when the loop
!   is not nested inside a teams construct (and executes on a non-host device); nested inside teams it is specified.
! "then the behavior of a reduction clause that appears on the corresponding loop construct is unspecified if the
!   construct is not nested inside a teams construct." (5.2 §11.7.1 p.259 l.5-7)
! spec (this program): The loop bind(teams) reduction(+: r) is strictly nested in the teams region of target teams,
!   the case the restriction leaves specified, so r must be 55; amdflang rejects the reduction.
