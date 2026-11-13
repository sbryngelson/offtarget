program t
  use openacc
  implicit none
  integer :: a(8), i
  a = 1
  !$acc init
  !$acc parallel loop copy(a)
  do i = 1, 8
    a(i) = 2
  end do
  print *, 'ok', a(1)
  !$acc set default_async(2)
  !$acc parallel loop copy(a) async
  do i = 1, 8
    a(i) = 2
  end do
  !$acc wait(2)
  print *, 'ok', a(1), acc_get_default_async()
end program t
