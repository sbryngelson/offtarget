! Fresh-084 reduced (two dimensions): an automatic array w(nb, nl) in
! copyout on an OpenACC data region, written in a parallel loop collapse(2).
! Expected: s 3150.0
module m
  implicit none
contains
  subroutine fill(nb, nl, s)
    integer, intent(in) :: nb, nl
    real(8), intent(out) :: s
    real(8) :: w(nb, nl)
    integer :: i, k
    !$acc data copyout(w)
    !$acc parallel loop collapse(2)
    do k = 1, nl
      do i = 1, nb
        w(i, k) = i * k
      end do
    end do
    !$acc end data
    s = sum(w)
  end subroutine fill
end module m

program main
  use m
  implicit none
  real(8) :: s
  call fill(20, 5, s)
  print *, 's', s
end program main
