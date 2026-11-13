program fuzz_prog
  implicit none
  integer, parameter :: n = 48
  call kp1()
  print '(a)', 'RESULT check=pass'
contains
  subroutine kp1()
    integer :: i
    !$omp target teams
      !$omp distribute parallel do schedule(dynamic) dist_schedule(static, 16)
      do i = 1, n
      end do
    !$omp end target teams
  end subroutine kp1
end program fuzz_prog
