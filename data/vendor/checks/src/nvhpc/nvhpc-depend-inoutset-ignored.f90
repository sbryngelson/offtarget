program p
  implicit none
  integer :: w(64), b(64), j, sp, spin(1)
  w = 0
  b = 0
  !$omp target nowait map(tofrom: w) map(from: spin) depend(inoutset: w)
    sp = 1
    do j = 1, 20000000
      sp = mod(7*sp + j, 1000003)
    end do
    spin(1) = sp
    do j = 1, 64
      w(j) = j
    end do
  !$omp end target
  !$omp target nowait map(to: w) map(from: b) depend(in: w)
    do j = 1, 64
      b(j) = w(j)
    end do
  !$omp end target
  !$omp taskwait
  print *, 'sum(b)', sum(b), '(expected 2080)'
end program p
