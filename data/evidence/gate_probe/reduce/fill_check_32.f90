! Localization for data/findings/cce21-alloc-2e32-sum-wrong.f90
! (after the findings reviewer's run): the same device fill of an integer(8)
! allocatable of 2**32 elements, then target update from and a check and sum
! on the host. Expected: s= 2164663527981 wrong= 0
program p
  implicit none
  integer(8) :: i, nn, s, wrong
  integer(8), allocatable :: big(:)
  nn = 2_8**32
  allocate(big(nn))
  big = -1
  !$omp target enter data map(alloc: big)
  !$omp target teams distribute parallel do
  do i = 1, nn
    big(i) = mod(i * 642, 1009_8)
  end do
  !$omp end target teams distribute parallel do
  !$omp target update from(big)
  !$omp target exit data map(delete: big)
  s = 0
  wrong = 0
  do i = 1, nn
    if (big(i) /= mod(i * 642, 1009_8)) wrong = wrong + 1
    s = s + big(i)
  end do
  print '(a,i0,a,i0,a,i0,a,i0)', 's= ', s, ' wrong= ', wrong, ' big(nn)= ', big(nn), &
      ' big(nn-256)= ', big(nn - 256)
  deallocate(big)
end program p
