! A reduction on a simd loop nested in a worksharing-loop reduction
! of the same variable, in a parallel region of a target region (nt4_simd).
! Each simd reduction combines into the do's private copy, which the do
! reduction combines into the original (OpenMP 5.2 §5.5.8, §5.5.3).
! Expected: r= 20800
program p
  implicit none
  integer :: i, j, r
  integer :: a(64)
  logical :: lpar
  lpar = .false.
  r = 0
  do i = 1, 64
    a(i) = i
  end do
  !$omp target map(tofrom: r) map(to: a)
  !$omp parallel num_threads(4)
  !$omp do reduction(+: r)
  do i = 1, 64
    !$omp simd reduction(+: r)
    do j = 1, 4
      r = r + a(i) * j
    end do
  end do
  !$omp end do
  !$omp end parallel
  !$omp end target
  print '(a,i0)', 'r= ', r
end program p
