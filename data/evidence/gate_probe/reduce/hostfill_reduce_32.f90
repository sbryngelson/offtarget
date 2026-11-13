! Localization for data/findings/cce21-alloc-2e32-sum-wrong.f90:
! the array filled on the host, mapped with target enter data map(to:), and
! reduced on the device by the same reduction loop. Expected: s= 2164663527981
program p
  implicit none
  integer(8) :: i, nn, s
  integer(8), allocatable :: big(:)
  nn = 2_8**32
  s = 0
  allocate(big(nn))
  do i = 1, nn
    big(i) = mod(i * 642, 1009_8)
  end do
  !$omp target enter data map(to: big)
  !$omp target teams distribute parallel do reduction(+: s)
  do i = 1, nn
    s = s + big(i)
  end do
  !$omp end target teams distribute parallel do
  !$omp target exit data map(delete: big)
  deallocate(big)
  print '(a,i0)', 's= ', s
end program p
