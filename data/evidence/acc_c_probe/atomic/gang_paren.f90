program p
  implicit none
  integer, parameter :: n = 64
  integer :: a(n), b(n), i
  do i = 1, n
    a(i) = i
    b(i) = 0
  end do
  !$acc parallel num_gangs(4) copyin(a) copy(b)
  !$acc loop gang
  do i = 1, n
    !$acc atomic update
    b(i) = b(i) + (2*a(i) + 1)
  end do
  !$acc end parallel
  print '(a,i0)', 'sum=', sum(b)
end program p
