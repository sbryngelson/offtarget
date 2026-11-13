program iter_enter
  use omp_lib
  implicit none
  integer, parameter :: n = 64
  integer :: w(n), i, k
  w = 1
  !$omp target enter data map(iterator(k = 1:n), to: w(k))
  !$omp target
    do i = 1, n
      w(i) = 2
    end do
  !$omp end target
  !$omp target exit data map(iterator(k = 1:n), from: w(k))
  print '(a,i0,a,i0)', 'iter_enter sum=', sum(w), ' want=', 2*n
end program
