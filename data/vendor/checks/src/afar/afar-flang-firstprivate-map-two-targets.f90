program p
  implicit none
  integer :: a(10), i, p1
  p1 = 3
  !$omp target firstprivate(p1) map(from: a)
    do i = 1, 10
      a(i) = p1
    end do
  !$omp end target
  !$omp target map(to: p1) map(tofrom: a)
    do i = 1, 10
      a(i) = a(i) + p1
    end do
  !$omp end target
  print *, 'a(3) =', a(3)
end program p
