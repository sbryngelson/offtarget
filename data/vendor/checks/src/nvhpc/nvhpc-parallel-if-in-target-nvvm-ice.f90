program p
  implicit none
  integer :: a(64), i
  logical :: use_par
  use_par = .false.
  a = 0
  !$omp target map(tofrom: a)
    !$omp parallel do if(use_par)
    do i = 1, 64
      a(i) = i
    end do
  !$omp end target
  print *, 'sum', sum(a)
end program p
