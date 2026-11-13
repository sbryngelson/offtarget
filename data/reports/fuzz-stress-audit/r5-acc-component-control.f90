! Audit, candidate 5, CONTROL (copy(xc)): a derived-type variable's scalar component
! written in a serial construct. An aggregate variable with no visible data
! clause is treated as copy (OpenACC 3.4 §2.6.2 p.41, lines 1388-1391; a
! composite variable is an aggregate, glossary). Expected: c1= 203
program acc_component
  implicit none
  type :: t
    integer(8) :: c1
  end type t
  type(t) :: xc
  xc%c1 = 101
  !$acc serial copy(xc)
    xc%c1 = 2 * xc%c1 + 1
  !$acc end serial
  print '(a,i0)', 'c1= ', xc%c1
end program acc_component
