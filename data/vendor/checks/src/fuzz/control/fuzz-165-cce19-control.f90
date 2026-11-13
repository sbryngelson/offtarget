module fuzz_mod
  implicit none
contains
  integer function g1(x, y)
    !$omp declare target
    integer, intent(in) :: x, y
    g1 = mod(max((x + y), x), 97)
  end function g1
end module fuzz_mod
program fuzz_prog
  use omp_lib, only: omp_get_thread_num
  use fuzz_mod, only: g1
  implicit none
  integer, parameter :: n = 16, m = 2
  integer :: o1(n)
  integer :: i, j, lp1, t1
  logical :: lpar
  integer(8) :: cs
  o1 = 0
  lp1 = 0
  lpar = .true.
      !$omp parallel do lastprivate(conditional: lp1) private(t1)
      do i = n, 1, -1
        t1 = 0
        if (mod(i, 2) == 1) lp1 = i
      end do
  cs = 0
  cs = modulo(cs * 31_8 + int(lp1, 8), 2147483629_8)
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o1(i), 8), 2147483629_8)
  end do
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
