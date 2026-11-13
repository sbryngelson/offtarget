program p
  implicit none
  integer, parameter :: n = 8, m = 4
  integer :: a(n, m), i, j
  logical :: ok
  a = 0
  !$omp target map(tofrom: a)
  !$omp teams distribute default(none) shared(a) private(j)
  do i = 1, n
    !$omp parallel do default(none) shared(a) firstprivate(i)
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
