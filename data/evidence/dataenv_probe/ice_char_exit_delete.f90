! probe (s1 seed 8634, CCE 21 ICE "Unhandled expression type in
! get base or dv mem", minimized): target exit data map(delete:) of a
! character scalar that is not mapped. Legal: delete of a list item that
! is not present has no effect (5.2 §5.8.3), and a character scalar is a
! valid list item. Expected: compiles and prints check=pass.
! expected: check=pass
program p
  implicit none
  character(len=8) :: xs
  xs = 'abcdefgh'
  !$omp target exit data map(delete: xs)
  if (xs == 'abcdefgh') then
    print '(a)', 'RESULT check=pass'
  else
    print '(a)', 'RESULT check=fail'
  end if
end program p
