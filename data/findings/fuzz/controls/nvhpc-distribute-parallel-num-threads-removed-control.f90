program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 32, m = 4
  integer :: o2(n, m)
  integer :: i, j, h
  h = -1
  o2 = 0
  !$omp target map(tofrom: h)
  !$omp teams
  !$omp distribute
  do i = 1, n
    if (i == 1) h = merge(1, 0, omp_is_initial_device())
    !$omp parallel
    !$omp do
      do j = 1, m
        o2(i, j) = i + j
      end do
    !$omp end do
    !$omp end parallel
  end do
  !$omp end teams
  !$omp end target
  print '(a,i0,a,i0)', 'sum= ', sum(o2), ' h= ', h
  print '(a,i0,a,a)', 'RESULT ran_on_host=', merge(1, 0, h == 1), ' check=', merge('pass', 'fail', sum(o2) == 2432 .and. h == 0)
end program p
