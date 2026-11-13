module fuzz_dfun
  use fuzz_dmod
  implicit none
contains
  integer function gd1(x)
    !$omp declare target
    integer, intent(in) :: x
    gd1 = mod((x + gtab((mod(abs(x), nm) + 1))), 1009)
  end function gd1
end module fuzz_dfun
