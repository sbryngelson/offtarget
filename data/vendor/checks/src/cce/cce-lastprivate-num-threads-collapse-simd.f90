program p
  implicit none
  integer :: i, lp
  lp = 0
  !$omp target teams distribute parallel do lastprivate(lp) num_threads(2)
  do i = 1, 200
    lp = i
  end do
  !$omp end target teams distribute parallel do
  print '(a,i0)', 'lp= ', lp
end program p
