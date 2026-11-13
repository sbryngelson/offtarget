program p
  implicit none
  integer, parameter :: n = 16
  character(len=8) :: xs
  integer :: r
  xs = 'kPACnWLl'
  r = -1
  call kp1(xs)
  print '(a,i0,a,i0)', 'RESULT checksum=', r, ' ran_on_host=', 0
contains
  subroutine kp1(xs)
    character(len=*), intent(in) :: xs
    integer :: i
    !$omp taskgroup task_reduction(*: r)
      !$omp target defaultmap(tofrom: scalar) in_reduction(*: r)
        do i = 1, n
          r = r * merge(-1, 1, mod(7, 13) == 0)
        end do
      !$omp end target
    !$omp end taskgroup
  end subroutine kp1
end program p
