! Fresh-046 variant: map(tofrom: data) on the construct, no enter/exit data.
module control_mod
  implicit none
  logical :: should_offload = .true.
end module

program test_if_bycopy
  use control_mod
  implicit none
  integer :: data(30000)
  integer :: i
  
  data = 0
  
  ! NOTE: Remove if or replace with a constant and it will work fine.
  !$omp target teams distribute parallel do map(tofrom: data) if (should_offload)
    do i = 1, 30000 ! 9000 -> 9001 seemed to be the break point where the crash becomes a lot more consistent
      data(i) = i
    end do
  !$omp end target teams distribute parallel do
  
  
  if (data(1) /= 1 .or. data(19600) /= 19600) then
    print *, "FAIL: data(1)=", data(1), " data(19600)=", data(19600)
    stop 1
  end if
  
  print *, "PASS"
end program
