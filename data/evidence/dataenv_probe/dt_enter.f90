! probe: a module variable in a declare target
! directive with the enter clause, the OpenMP 5.2 spelling of to ("The
! clause-name to may be used as a synonym for the clause-name enter",
! 5.2 §5.8.4 p.158; "The enter clause was added as a synonym for the to
! clause on the declare target directive", Appendix B.2 p.627). The device
! copy is initialized from the host value, updated by a target region and
! copied back with target update from.
! expected: check=pass
module m
  implicit none
  integer, parameter :: n = 16
  integer :: g(n) = 1
  !$omp declare target enter(g)
end module m
program p
  use m
  implicit none
  integer :: i
  logical :: ok
  !$omp target
  do i = 1, n
    g(i) = g(i) + i
  end do
  !$omp end target
  !$omp target update from(g)
  ok = .true.
  do i = 1, n
    ok = ok .and. g(i) == 1 + i
  end do
  if (ok) then
    print '(a)', 'RESULT check=pass'
  else
    print '(a)', 'RESULT check=fail'
  end if
end program p
