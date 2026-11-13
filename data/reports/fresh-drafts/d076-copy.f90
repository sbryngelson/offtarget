! Fresh-076 legal form: copy(sumA) on the parallel construct.
! Expected: wild-check: pass
module test_mod

contains

subroutine test(A,sumA)

  implicit none

  real(kind=8) :: A(:,:,:), sumA
  integer :: i, j, k

!$acc parallel copy(sumA)
!$acc loop gang worker collapse(2) reduction(+:sumA)
  do k = 1, size(A,3)
    do j = 1, size(A,2)
!$acc loop vector reduction(+:sumA)
      do i = 1, size(A,1)
        sumA = sumA + A(i,j,k)
      end do
!$acc end loop
    end do
  end do
!$acc end loop
!$acc end parallel

end subroutine test

end module test_mod

program main

  use test_mod

  implicit none

  integer, parameter :: m = 1000, n = 1000, o = 100, iter = 100
  real(kind=8) :: A(m,n,o), sumA
  integer :: i

  A = 0.000000001d0
  sumA = 0.0d0
  do i = 1, iter
    call test(A,sumA)
  end do

  write(0,*) "CHECK: ", sumA
  if (abs(sumA - 10.0d0) < 1.0d-6) then
    print *, 'wild-check: pass'
  else
    print *, 'wild-check: fail', sumA
  end if

end program main
