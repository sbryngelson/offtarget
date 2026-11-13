integer function ge1(x)
  implicit none
  integer, intent(in) :: x
  !$omp declare target
  ge1 = mod((max(x, 5) - 2), 997)
end function ge1
