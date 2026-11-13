! Kernel 1 of fuzz x0-alloc:197 alone: a parallel loop
! with ior and iand reductions in a target region. Expected: r1a= 243 r1b= 0
program p
  implicit none
  integer, parameter :: n = 16, m = 3
  integer :: i, j, r1a, r1b
  r1a = 2
  r1b = 1048575
  !$omp target map(tofrom: r1a, r1b)
    !$omp parallel loop collapse(2) reduction(ior: r1a) reduction(iand: r1b) num_threads(3)
    do i = n, 1, -1
      do j = m, 1, -1
        r1a = ior(r1a, iand(i * 16 + j, 255))
        r1b = iand(r1b, iand(i + 250, 255))
      end do
    end do
  !$omp end target
  print '(a,i0,a,i0)', 'r1a= ', r1a, ' r1b= ', r1b
end program p
