! probe: teams distribute default(none) over i, with a parallel
! do nested in it (no clause naming i). The iteration variable i
! of the distribute loop is predetermined private ("The loop iteration
! variable in any associated loop of a loop-associated construct is
! otherwise private", 5.2 §5.1.1 p.97), so default(none) does not need it
! listed (5.2 §5.4.1 p.109); firstprivate(i) on the combined parallel do
! applies to the worksharing leaf and "the effect is as if the shared
! clause with the same list item is applied to the parallel construct"
! (5.2 §17.2 p.340). Expected: a(i, j) = 10 * i + j.
! expected: check=pass
program p
  implicit none
  integer, parameter :: n = 8, m = 4
  integer :: a(n, m), i, j
  logical :: ok
  a = 0
  !$omp target map(tofrom: a)
  !$omp teams distribute default(none) shared(a) private(j)
  do i = 1, n
    !$omp parallel do shared(a)
    do j = 1, m
      a(i, j) = 10 * i + j
    end do
  end do
  !$omp end teams distribute
  !$omp end target
  ok = .true.
  do i = 1, n
    do j = 1, m
      ok = ok .and. a(i, j) == 10 * i + j
    end do
  end do
  if (ok) then
    print '(a)', 'RESULT check=pass'
  else
    print '(a)', 'RESULT check=fail'
  end if
end program p
