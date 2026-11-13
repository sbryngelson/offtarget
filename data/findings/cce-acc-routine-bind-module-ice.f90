! OpenACC 3.4 §2.15.1 (routine bind): host_val is called on the device under
! the name dev_val. Legal. Expected output: 3 5 7 9 11 13 15 17
! (dev_val(x) = 2*x + 1). Compile: ftn -h acc -O2.
module m
  implicit none
contains
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
end module m

program t
  use m
  implicit none
  integer :: b(8), i
  !$acc parallel loop copyout(b)
  do i = 1, 8
    b(i) = host_val(i)
  end do
  print *, b
end program t
! site:
! title: ftn -h acc: internal compiler error "Object DEV_VAL is host associated to itself" for routine bind between two module
! + procedures
! control: ../vendor/checks/src/cce/control/cce-acc-routine-bind-module-ice-control.f90 the two functions as external procedures
! + instead of
! + module procedures
! end site
