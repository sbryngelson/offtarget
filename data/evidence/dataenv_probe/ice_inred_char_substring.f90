! probe (s1 seed 2592, CCE 21 ICE "Should never reach this code
! (doehmke)", reduced by hand from the confirmer's reduction): a target
! region with in_reduction(*: r), inside a taskgroup task_reduction(*: r),
! reads a substring of a character dummy. Legal (5.2 §5.5.11 in_reduction
! on target, §12.5 taskgroup task_reduction). Without the substring
! (ichar(xs(1:1)) replaced by a constant) CCE compiles it.
! Expected: ichar('k') = 107 and mod(107, 13) = 3, so every factor is 1
! and r stays -1.
! expected: check=pass
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
