program lastprivate_collapse_simd
  implicit none
  integer :: i, j, lin
  integer(8) :: lp
  lp = 0
  !$omp target teams distribute parallel do simd collapse(2) private(lin) lastprivate(lp)
  do i = 1, 16
    do j = 1, 8
      lin = (i - 1) * 8 + j
      lp = lin
    end do
  end do
  !$omp end target teams distribute parallel do simd
  print '(a,i0)', 'lp= ', lp
end program lastprivate_collapse_simd
