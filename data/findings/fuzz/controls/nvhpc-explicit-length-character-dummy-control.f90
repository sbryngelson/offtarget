program p
  implicit none
  integer :: r
  character(len=8) :: xs
  xs = 'NnLXCqNL'
  r = 0
  call kp1(xs, r)
  print '(a,i0)', 'r= ', r
  print '(a,a)', 'RESULT ran_on_host=0 check=', merge('pass', 'fail', r == ichar('N'))
contains
  subroutine kp1(xs, r)
    character(len=8), intent(in) :: xs
    integer, intent(inout) :: r
    !$omp target map(to: xs) map(tofrom: r)
    r = ichar(xs(1:1))
    !$omp end target
  end subroutine kp1
end program p
