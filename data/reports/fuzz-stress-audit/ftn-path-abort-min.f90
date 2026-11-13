! (F2): CCE 19 ftn -fopenmp -O2 -c of this file aborts (free(): invalid pointer)
! when the working directory is /tmp/<user>-stress/st-tu.plain-omp-12-1-abcd1234 (also the same name
! under /var/tmp), not in other directories (results/stress/ftnpath/exp1..exp4). Reduced from the
! 222-line tu.plain-omp-12-1 (ftn-path-abort-tu12.f90) at that fixed path; 136 lines, -O0 compiles.
! NOT A LEGAL PROGRAM (N8): it was reduced for the abort only, without regard to legality.
! `!$omp declare target(gv)` names an undeclared gv (5.2 §7.8.1 p.206 l.17-20) and several functions have
! undeclared results and dummies. A compiler crash on it is still a defect, but it is not a conformance
! test and is not promoted; the legal original is ftn-path-abort-tu12.f90.
! Explained by the split CIF record (data/findings/stress/cce-ftn-cif-record-split-abort.f90): the
! "-1" of the directory's "12-1-" falls at offset 1023 of an optimizer message record.
module st_util
  implicit none
  integer(8), parameter :: st_p = 2147483629_8
  type :: st_pair
    integer(8) :: u, v
  end type st_pair
contains
  subroutine st_cksum(a, n, cs)
    integer, intent(in) :: n
    integer(8), intent(in) :: a(n)
    integer(8), intent(out) :: cs
    integer :: i
  end subroutine st_cksum
end module st_util
module k0001_glob
  use st_util
  !$omp declare target(gv)
end module k0001_glob
module k0001_c12
  use st_util
contains
  function k0001_g12(x) result(r)
    !$omp declare target
    integer(8), intent(in) :: x
  end function k0001_g12
end module k0001_c12
module k0001_c11
  use st_util
  use k0001_glob
  use k0001_c12
  implicit none
contains
  function k0001_g11(x) result(r)
    !$omp declare target
    integer(8), intent(in) :: x
    integer(8) :: r
    r = k0001_g12(mod(x * 5, 1013_8) + 11) + 11
  end function k0001_g11
end module k0001_c11
module k0001_c10
  use k0001_c11
  implicit none
contains
  function k0001_g10(x) result(r)
    !$omp declare target
    integer(8), intent(in) :: x
    integer(8) :: r
    r = k0001_g11(mod(x * 5, 1013_8) + 10) + 10
  end function k0001_g10
end module k0001_c10
module k0001_c9
  use st_util
  use k0001_glob
  use k0001_c10
  implicit none
contains
  function k0001_g9(x) result(r)
    !$omp declare target
    integer(8), intent(in) :: x
    integer(8) :: r
    r = k0001_g10(mod(x * 5, 1013_8) + 9) + 9
  end function k0001_g9
end module k0001_c9
module k0001_c8
  use st_util
  use k0001_glob
  use k0001_c9
  implicit none
contains
  function k0001_g8(x) result(r)
    !$omp declare target
    integer(8), intent(in) :: x
    integer(8) :: r
    r = k0001_g9(mod(x * 5, 1013_8) + 8) + 8
  end function k0001_g8
end module k0001_c8
module k0001_c7
  use st_util
  use k0001_glob
  use k0001_c8
  implicit none
contains
  function k0001_g7(x) result(r)
    !$omp declare target
    integer(8), intent(in) :: x
    integer(8) :: r
    r = k0001_g8(mod(x * 5, 1013_8) + 7) + 7
  end function k0001_g7
end module k0001_c7
module k0001_c6
  use st_util
  use k0001_glob
  use k0001_c7
  implicit none
contains
  function k0001_g6(x) result(r)
    !$omp declare target
    integer(8), intent(in) :: x
    integer(8) :: r
    r = k0001_g7(mod(x * 5, 1013_8) + 6) + 6
  end function k0001_g6
end module k0001_c6
module k0001_c5
contains
  function k0001_g5(x) result(r)
  end function k0001_g5
end module k0001_c5
module k0001_c4
contains
  function k0001_g4(x) result(r)
  end function k0001_g4
end module k0001_c4
module k0001_c3
contains
  function k0001_g3(x) result(r)
  end function k0001_g3
end module k0001_c3
module k0001_c2
contains
  function k0001_g2(x) result(r)
  end function k0001_g2
end module k0001_c2
module k0001_c1
contains
  function k0001_g1(x) result(r)
  end function k0001_g1
end module k0001_c1
module st_kern
contains
  subroutine k0001(cs)
    do i = 1, 256
    end do
  end subroutine k0001
end module st_kern
program stress_main
end program stress_main
