module glob
  implicit none
  integer(8) :: gv = 0
  !$omp declare target(gv)
end module glob
module c3
  use glob
  implicit none
contains
  function g3(x) result(r)
    !$omp declare target
    integer(8), intent(in) :: x
    integer(8) :: r
    r = x + gv
  end function g3
end module c3
module c2
  use glob
  use c3
  implicit none
contains
  function g2(x) result(r)
    !$omp declare target
    integer(8), intent(in) :: x
    integer(8) :: r
    r = g3(mod(x * 5, 1013_8) + 2) + 2
  end function g2
end module c2
module c1
  use glob
  use c2
  implicit none
contains
  function g1(x) result(r)
    !$omp declare target
    integer(8), intent(in) :: x
    integer(8) :: r
    r = g2(mod(x * 5, 1013_8) + 1) + 1
  end function g1
end module c1
program chain
  use glob
  use c1
  implicit none
  integer(8) :: out(256), s
  integer :: i
  gv = 77
  !$omp target update to(gv)
  out = 0
  !$omp target teams distribute parallel do map(tofrom: out)
  do i = 1, 256
    out(i) = g1(int(i, 8))
  end do
  !$omp end target teams distribute parallel do
  s = sum(out)
  print '(a,i0)', 'sum=', s
end program chain
