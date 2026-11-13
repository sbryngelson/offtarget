! Kernel 3 of fuzz x0-alloc:197 alone: target simd with
! iand and ieor reductions. Expected: r3a= 0 and r3b equal to ref3b
program p
  implicit none
  integer, parameter :: n = 16
  integer :: i, r3a, r3b, ref
  r3a = 65535
  r3b = 226
  !$omp target simd reduction(iand: r3a) reduction(ieor: r3b)
  do i = 1, n
    r3a = iand(r3a, iand(i * 3, 1048575))
    r3b = ieor(r3b, iand(mod(i, 1000), 255))
  end do
  ref = 226
  do i = 1, n
    ref = ieor(ref, i)
  end do
  print '(a,i0,a,i0,a,i0)', 'r3a= ', r3a, ' r3b= ', r3b, ' ref3b= ', ref
end program p
