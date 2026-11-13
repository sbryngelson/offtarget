program p
  implicit none
  integer :: r, i
  r = 0
  !$omp target teams map(tofrom: r)
    !$omp loop reduction(+: r)
    do i = 1, 10
      r = r + i
    end do
  !$omp end target teams
  print *, 'r =', r
end program p
