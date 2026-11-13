program p
  implicit none
  integer, parameter :: n = 24, m = 2
  integer :: o1(n, m)
  integer :: i, j, r
  o1 = 0
  r = 7
  !$omp target teams distribute map(tofrom: r)
  do i = 1, n
    !$omp parallel do
    do j = 1, m
      o1(i, j) = 0
      !$omp atomic
      r = min(r, mod(i, n))
    end do
    !$omp end parallel do
  end do
  !$omp end target teams distribute
  print '(a,i0,a,i0)', 'r=', r, ' s=', sum(o1)
end program p
