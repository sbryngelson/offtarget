program p
  implicit none
  integer, parameter :: n = 16
  character(len=8) :: xs
  integer :: r
  xs = 'kPACnWLl'
  r = -1
  call kp1(xs)
  if (r == -1) then
    print '(a)', 'RESULT check=pass'
  else
    print '(a,i0)', 'RESULT check=fail r=', r
  end if
contains
  subroutine kp1(xs)
    character(len=*), intent(in) :: xs
    integer :: i
    !$omp taskgroup task_reduction(*: r)
      !$omp target defaultmap(tofrom: scalar) in_reduction(*: r)
        do i = 1, n
          r = r * merge(-1, 1, mod(ichar(xs(1:1)), 13) == 0)
        end do
      !$omp end target
    !$omp end taskgroup
  end subroutine kp1
end program p
