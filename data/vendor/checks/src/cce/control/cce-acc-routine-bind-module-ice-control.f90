integer function dev_val(x)
  !$acc routine seq
  integer, intent(in) :: x
  dev_val = 2*x + 1
end function dev_val
integer function host_val(x)
  !$acc routine seq bind(dev_val)
  integer, intent(in) :: x
  host_val = -x
end function host_val

program t
  implicit none
  interface
    integer function host_val(x)
      !$acc routine seq bind(dev_val)
      integer, intent(in) :: x
    end function host_val
  end interface
  integer :: b(8), i
  !$acc parallel loop copyout(b)
  do i = 1, 8
    b(i) = host_val(i)
  end do
  print *, b
end program t
