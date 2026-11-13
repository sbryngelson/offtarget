program p
  implicit none
  integer, parameter :: n = 16, m = 4
  integer :: o1(n, m), i, j
  integer(8) :: cs
  o1 = 0
  call kp(o1)
  cs = sum(int(o1, 8))
  print '(a,i0)', 'RESULT checksum=', cs
contains
  subroutine kp(o1)
    integer, intent(inout) :: o1(:, :)
    integer :: i, j
    !$omp target teams distribute parallel do map(tofrom: o1)
    do i = 1, n
      !$omp simd
      do j = 1, m
        o1(i, j) = i + j
      end do
    end do
  end subroutine kp
end program p
