! Audit, candidate 3, CONTROL (present(g)): a module scalar in "declare create" written in a
! serial construct. A variable that appears in a data clause of a visible
! declare directive gets no implicit data attribute (OpenACC 3.4 §2.6.2 p.41,
! lines 1372-1373, 1381-1387), so the serial region updates the device copy,
! which "update self" brings back. Expected: g= 203
module acc_scalar_m
  implicit none
  integer(8) :: g
  !$acc declare create(g)
end module acc_scalar_m
program acc_declare_scalar
  use acc_scalar_m
  implicit none
  g = 101
  !$acc update device(g)
  !$acc serial present(g)
    g = 2 * g + 1
  !$acc end serial
  !$acc update self(g)
  print '(a,i0)', 'g= ', g
end program acc_declare_scalar
