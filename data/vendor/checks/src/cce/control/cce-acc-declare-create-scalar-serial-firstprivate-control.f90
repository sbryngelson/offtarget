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
