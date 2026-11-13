! Control for alloc_32.f90: the same 2**32
! iterations and sum, without the array. Expected: s= 2164663527981
program p
  implicit none
  integer(8) :: i, nn, s
  nn = 2_8**32
  s = 0
  !$omp target teams distribute parallel do reduction(+: s)
  do i = 1, nn
    s = s + mod(i * 642, 1009_8)
  end do
  !$omp end target teams distribute parallel do
  print '(a,i0)', 's= ', s
end program p
