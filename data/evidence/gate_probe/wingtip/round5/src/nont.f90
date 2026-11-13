! Lastprivate on a composite distribute parallel do (nont).
! The sequentially last iteration (i = 200) sets lp = 200 (OpenMP 5.2
! §5.4.5; §17.2: the list item is also map(tofrom)). Expected: lp= 200
program p
  implicit none
  integer :: i, lp
  logical :: lpar
  lpar = .false.
  lp = 0
  !$omp target teams distribute parallel do lastprivate(lp)
  do i = 1, 200
    lp = i
  end do
  !$omp end target teams distribute parallel do
  print '(a,i0)', 'lp= ', lp
end program p
