program p
  implicit none
  integer :: i, x
  x = 0
  !$omp target teams distribute parallel do map(tofrom: x)
  do i = 1, 1000
    x = x + 1
  end do
  !$omp end target teams distribute parallel do
  print '(a,i0)', 'x=', x
end program p
