submodule (fuzz_smod) fuzz_ssub
  implicit none
contains
  module integer function gs1(x)
    !$omp declare target
    integer, intent(in) :: x
    gs1 = mod(ieor(x, 224), 4093)
  end function gs1
end submodule fuzz_ssub
