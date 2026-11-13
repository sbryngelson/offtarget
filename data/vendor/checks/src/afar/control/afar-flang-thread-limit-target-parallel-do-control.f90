program p
  implicit none
  integer :: a(10), i
  a = 0
  !$omp target parallel do map(from: a)
  do i = 1, 10
    a(i) = i
  end do
  print *, 'a(3) =', a(3)
end program p
