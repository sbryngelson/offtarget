module m
  implicit none
  integer, parameter :: n = 16
  integer :: g(n) = 1
  !$omp declare target to(g)
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
