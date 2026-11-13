program ord_tsimd
  use omp_lib
  implicit none
  integer, parameter :: n = 64
  integer :: a(n), b(n), i
  a = [(i, i = 1, n)]; b = 0
  !$omp target simd order(concurrent) map(to: a) map(from: b)
  do i = 1, n
    b(i) = 2*a(i) + 1
  end do
  !$omp end target simd
  print '(a,l1)', 'ord_tsimd ok=', all(b == 2*a + 1)
end program
