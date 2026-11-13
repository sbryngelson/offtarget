! Fresh-046 variant: as d046-min.f90 on target teams (one statement
! loop in the teams region, run by every team: b(i) = i is idempotent).
! Expected: b(1) 1 b(64) 64 dev 1
module ctl
  implicit none
  logical :: on = .true.
end module ctl

program p
  use omp_lib, only: omp_is_initial_device
  use ctl
  implicit none
  integer :: b(64), i, dev
  b = 0
  dev = -1
  !$omp target teams map(tofrom: b, dev) if (on) num_teams(1)
  do i = 1, 64
    b(i) = i
    if (i == 1) dev = merge(0, 1, omp_is_initial_device())
  end do
  !$omp end target teams
  print *, 'b(1)', b(1), 'b(64)', b(64), 'dev', dev
end program p
