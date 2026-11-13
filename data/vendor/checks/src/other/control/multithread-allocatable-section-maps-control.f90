program p
  implicit none
  integer, parameter :: n = 64
  integer, allocatable :: a(:), b(:)
  integer :: i, c, lo, hi, bad
  allocate(a(n), b(n))
  do i = 1, n
    a(i) = i
    b(i) = 0
  end do
  !$omp parallel do num_threads(1) private(lo, hi)
  do c = 1, 2
    lo = (c - 1)*32 + 1
    hi = c*32
    !$omp target map(to: a(lo:hi)) map(from: b(lo:hi))
      do i = lo, hi
        b(i) = 2*a(i) + 1
      end do
    !$omp end target
  end do
  !$omp end parallel do
  bad = 0
  do i = 1, n
    if (b(i) /= 2*i + 1) bad = bad + 1
  end do
  print *, 'bad=', bad
end program p
