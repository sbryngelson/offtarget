! Lastprivate on a composite distribute parallel do (collapsent2).
! The sequentially last iteration (i = 200) sets lp = 200 (OpenMP 5.2
! §5.4.5; §17.2: the list item is also map(tofrom)). Expected: lp= 200
program p
  implicit none
  integer :: i, j, lp
  logical :: lpar
  lpar = .false.
  lp = 0
  !$omp target teams distribute parallel do collapse(2) lastprivate(lp) num_threads(2)
  do i = 1, 20
    do j = 1, 10
      lp = (i - 1) * 10 + j
    end do
  end do
  !$omp end target teams distribute parallel do
  print '(a,i0)', 'lp= ', lp
end program p
