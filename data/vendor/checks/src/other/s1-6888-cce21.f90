program p
  implicit none
  integer, parameter :: n = 16
  integer :: a(n), i
  logical :: ok
  a = 0
  !$omp target enter data map(to: a)
  do i = 1, n
    a(i) = i
  end do
  !$omp target update to(a(1:n:2))
  !$omp target
  do i = 1, n
    a(i) = 2 * a(i)
  end do
  !$omp end target
  !$omp target exit data map(from: a)
  ok = .true.
  do i = 1, n
    if (mod(i, 2) == 1) ok = ok .and. a(i) == 2 * i
  end do
  if (ok) then
    print '(a)', 'RESULT check=pass'
  else
    print '(a)', 'RESULT check=fail'
  end if
end program p
