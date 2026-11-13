module fuzz_amod
  implicit none
contains
  integer function ga1(x)
    !$omp declare target
    integer, intent(in) :: x
    ga1 = mod(((iand(x, 1023) * 3) + 35), 1013)
  end function ga1
end module fuzz_amod
