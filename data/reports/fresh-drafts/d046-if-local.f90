! Fresh-046 variant: the if expression is a local logical, not a module variable.
module control_mod
  implicit none
  logical :: should_offload = .true.
end module

program test_if_bycopy
  implicit none
  logical :: should_offload
  integer :: data(30000)
  integer :: i
  
  should_offload = .true.
  data = 0
  !$omp target enter data map(alloc: data)
  
  ! NOTE: Remove if or replace with a constant and it will work fine.
  !$omp target teams distribute parallel do map(present, tofrom: data) if (should_offload)
    do i = 1, 30000 ! 9000 -> 9001 seemed to be the break point where the crash becomes a lot more consistent
      data(i) = i
    end do
  !$omp end target teams distribute parallel do
  
  !$omp target exit data map(from: data)
  
  if (data(1) /= 1 .or. data(19600) /= 19600) then
    print *, "FAIL: data(1)=", data(1), " data(19600)=", data(19600)
    stop 1
  end if
  
  print *, "PASS"
end program
