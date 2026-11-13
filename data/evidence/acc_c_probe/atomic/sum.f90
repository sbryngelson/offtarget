program p
  implicit none
  integer :: x, v
  x = 0
  !$acc parallel loop copy(x)
  do v = 1, 64
    !$acc atomic update
    x = x + v + 1
  end do
  print '(a,i0)', 'x=', x
end program p
