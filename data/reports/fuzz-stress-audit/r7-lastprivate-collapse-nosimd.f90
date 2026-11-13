! Audit, candidate 7, CONTROL (no simd): lastprivate on target teams distribute parallel
! do simd with collapse(2) (race-free: lin is private). The sequentially last
! iteration (i=16, j=8) sets lp = 128 (OpenMP 5.2 §5.4.5; §17.2 p.339: the
! item is also map(tofrom)). Expected: lp= 128
program lastprivate_collapse_simd
  implicit none
  integer :: i, j, lin
  integer(8) :: lp
  lp = 0
  !$omp target teams distribute parallel do collapse(2) private(lin) lastprivate(lp)
  do i = 1, 16
    do j = 1, 8
      lin = (i - 1) * 8 + j
      lp = lin
    end do
  end do
  !$omp end target teams distribute parallel do
  print '(a,i0)', 'lp= ', lp
end program lastprivate_collapse_simd
