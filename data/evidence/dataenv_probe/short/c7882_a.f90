! Shorter forms of fuzz/s1-7882-cce20.f90 (CCE
! present-table failure for a character array mapped by an enclosing
! target data construct). Legal: target data maps xc, so the present
! modifier of the inner target is satisfied (5.2 §5.8.3).
! expected: check=pass
program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 48
  character(len=4), allocatable :: xc(:)
  integer :: i, hf1
  allocate(xc(n))
  do i = 1, n
    xc(i) = achar(65 + mod(i * 33, 26)) // 'b#c'
  end do
  hf1 = -1
  !$omp target data map(to: xc)
    !$omp target map(present, tofrom: xc) map(tofrom: hf1)
      hf1 = merge(1, 0, omp_is_initial_device())
    !$omp end target
  !$omp end target data
  if (hf1 == 0) then
    print '(a)', 'RESULT check=pass'
  else
    print '(a)', 'RESULT check=fail'
  end if
end program p
