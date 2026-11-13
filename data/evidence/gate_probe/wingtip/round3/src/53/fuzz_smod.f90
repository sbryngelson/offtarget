module fuzz_smod
  implicit none
  interface
    module integer function gs1(x)
      !$omp declare target
      integer, intent(in) :: x
    end function gs1
  end interface
end module fuzz_smod
