program p
  implicit none
  integer, parameter :: n = 64
  integer, allocatable :: b(:)
  integer :: i, c, lo, hi, bad
  allocate(b(n))
  b = 0
  !$omp target enter data map(to: b)
  !$omp target
    do i = 1, n
      b(i) = 2*i + 1
    end do
  !$omp end target
  do c = 1, 4
    lo = (c - 1)*16 + 1
    hi = c*16
    !$omp target update from(b(lo:hi))
  end do
  !$omp target exit data map(release: b)
  bad = count(b /= [(2*i + 1, i = 1, n)])
  print *, 'bad=', bad
end program p
