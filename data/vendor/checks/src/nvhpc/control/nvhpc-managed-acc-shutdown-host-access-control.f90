program p
  implicit none
  integer, allocatable :: a(:)
  allocate(a(64))
  a = 1
  print *, 'after shutdown'
  flush(6)
  print *, 'sum', sum(a)
end program p
