! Fill and reduce an integer(8) allocatable of 2**32
! elements on the device (the stress program runtime.alloc-omp at
! 2**32): integer(8) indices and extents, so no index overflows; 2**32 * 8
! bytes on the host and on the device. Expected: s= 2164663527981 (the sum of
! mod(i*642, 1009), i = 1..2**32: 642 is invertible mod 1009, so each run of
! 1009 consecutive i adds 0 + 1 + ... + 1008 = 508536)
program p
  implicit none
  integer(8) :: i, nn, s
  integer(8), allocatable :: big(:)
  nn = 2_8**32
  s = 0
  allocate(big(nn))
  !$omp target enter data map(alloc: big)
  !$omp target teams distribute parallel do
  do i = 1, nn
    big(i) = mod(i * 642, 1009_8)
  end do
  !$omp end target teams distribute parallel do
  !$omp target teams distribute parallel do reduction(+: s)
  do i = 1, nn
    s = s + big(i)
  end do
  !$omp end target teams distribute parallel do
  !$omp target exit data map(delete: big)
  deallocate(big)
  print '(a,i0)', 's= ', s
end program p
