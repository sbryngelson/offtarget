program p
  implicit none
  integer, allocatable :: a(:), b(:)
  integer :: i
  allocate(a(64), b(64))
  a = [(i, i = 1, 64)]
  b = 0
  !$omp target map(to: a) map(from: b) defaultmap(tofrom)
    do i = 1, 64
      b(i) = a(i)
    end do
  !$omp end target
  print *, 'b(1)', b(1), 'b(64)', b(64), 'sum', sum(b), '(expected 1 64 2080)'
end program p
