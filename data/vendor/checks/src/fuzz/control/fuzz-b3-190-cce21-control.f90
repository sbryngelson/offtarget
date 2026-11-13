module fuzz_mod
  implicit none
contains
  integer function g1(x, y)
    !$omp declare target
    integer, intent(in) :: x, y
    g1 = 0
  end function g1
end module fuzz_mod
program fuzz_prog
  use fuzz_mod, only: g1
  implicit none
  integer, parameter :: n = 24, m = 3
  integer, allocatable :: as1
  allocate(as1)
  as1 = 46
  call kp1(as1)
  print '(a)', 'RESULT check=pass'
contains
  subroutine kp1(as1, zopt)
    integer, intent(inout) :: as1
    integer, intent(in), optional :: zopt(:)
    integer :: i, j, t1
    !$omp target private(t1)
    do i = 1, n
      do j = 1, m
        t1 = g1((-10), as1)
      end do
    end do
    !$omp end target
  end subroutine kp1
end program fuzz_prog
