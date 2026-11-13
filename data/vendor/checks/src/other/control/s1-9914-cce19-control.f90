module fuzz_dmod
  implicit none
  integer, parameter :: nm = 48
  integer :: go2(nm)
  !$omp declare target to(go2)
end module fuzz_dmod
module fuzz_smod
  implicit none
  interface
    module integer function gs1(x)
      integer, intent(in) :: x
    end function gs1
  end interface
end module fuzz_smod
submodule (fuzz_smod) fuzz_ssub
  implicit none
contains
  module integer function gs1(x)
    integer, intent(in) :: x
  end function gs1
end submodule fuzz_ssub
program fuzz_prog
  use fuzz_dmod
  implicit none
  !$omp target
  !$omp end target
  !$omp target depend(out: go2(:))
  !$omp end target
end program fuzz_prog
