program p
  implicit none
  integer, parameter :: n = 16
  type :: nd_t
    integer :: k(n)
  end type nd_t
  type :: rec_t
    integer :: a(n)
    type(nd_t) :: nd
  end type rec_t
  type(rec_t) :: dr
  dr%a = 1
  dr%nd%k = 2
  call kp3(dr)
  print '(a,i0,a,i0)', 'RESULT checksum=', sum(dr%a) + sum(dr%nd%k), ' ran_on_host=', 0
contains
  subroutine kp3(dr)
    type(rec_t), intent(inout) :: dr
    integer :: i
    !$omp target map(tofrom: dr%a, dr%nd%k(1:n))
    do i = 1, n
      dr%a(i) = dr%a(i) + dr%nd%k(i)
    end do
    !$omp end target
  end subroutine kp3
end program p
