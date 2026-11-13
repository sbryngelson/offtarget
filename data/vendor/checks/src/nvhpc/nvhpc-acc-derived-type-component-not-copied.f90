program acc_component
  implicit none
  type :: t
    integer(8) :: c1
  end type t
  type(t) :: xc
  xc%c1 = 101
  !$acc serial
    xc%c1 = 2 * xc%c1 + 1
  !$acc end serial
  print '(a,i0)', 'c1= ', xc%c1
end program acc_component
