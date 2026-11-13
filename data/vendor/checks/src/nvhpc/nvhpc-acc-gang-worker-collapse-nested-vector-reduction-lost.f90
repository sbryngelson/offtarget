module test_mod
contains
subroutine test(A, sumA)
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
    end do
  end do
!$acc end parallel
end subroutine test
end module test_mod

program main
  use test_mod
  implicit none
  integer, parameter :: m = 1000, n = 1000, o = 10
  real(kind=8) :: A(m,n,o), sumA
  A = 1.0d0
  sumA = 0.0d0
  call test(A, sumA)
  if (sumA == real(m, 8)*n*o) then
    print *, 'pass', sumA
  else
    print *, 'fail', sumA, ' expected', real(m, 8)*n*o
  end if
end program main
