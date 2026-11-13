program p
  implicit none
  integer, parameter :: n = 16
  character(len=4) :: o2(n)
  integer :: i, s
  o2 = ' '
  !$omp target teams map(from: o2)
    !$omp distribute
    do i = 1, n
      o2(i) = achar(64 + i)
    end do
    !$omp end distribute
  !$omp end target teams
  s = 0
  do i = 1, n
    s = s + ichar(o2(i)(1:1))
  end do
  print '(a,i0)', 's= ', s
  print '(a,a)', 'RESULT ran_on_host=0 check=', merge('pass', 'fail', s == 16 * 64 + 136)
end program p
