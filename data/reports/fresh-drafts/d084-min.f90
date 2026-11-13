! Fresh-084 reduced: an automatic array in copyout on an OpenACC data
! region, written in a parallel loop. Expected: s 2080.0
module m
  implicit none
contains
  subroutine fill(n, s)
    integer, intent(in) :: n
    real(8), intent(out) :: s
    real(8) :: w(n)
    integer :: i
    !$acc data copyout(w)
    !$acc parallel loop
    do i = 1, n
      w(i) = i
    end do
    !$acc end data
    s = sum(w)
  end subroutine fill
end module m

program main
  use m
  implicit none
  real(8) :: s
  call fill(64, s)
  print *, 's', s
end program main
