! stress: axis=tu.plain size=12 seed=1 model=omp layout=single
! generator: stress-1 rev 1
! language: Fortran 2018 free form; OpenMP 5.2 in 5.0 spellings
! kernel k0001:tu(depth=12,gv=77,n=256,variant=plain)
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
    cs = 0
    do i = 1, n
      cs = mod(cs + mod(a(i), st_p) * (mod(i, 7) + 1), st_p)
    end do
  end subroutine st_cksum
end module st_util
module k0001_glob
  use st_util
  implicit none
  integer(8) :: gv = 0
  !$omp declare target(gv)
end module k0001_glob
module k0001_c12
  use st_util
  use k0001_glob
  implicit none
contains
  function k0001_g12(x) result(r)
    !$omp declare target
    integer(8), intent(in) :: x
    integer(8) :: r
    r = x + gv
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
  use st_util
  use k0001_glob
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
  use st_util
  use k0001_glob
  use k0001_c6
  implicit none
contains
  function k0001_g5(x) result(r)
    !$omp declare target
    integer(8), intent(in) :: x
    integer(8) :: r
    r = k0001_g6(mod(x * 5, 1013_8) + 5) + 5
  end function k0001_g5
end module k0001_c5
module k0001_c4
  use st_util
  use k0001_glob
  use k0001_c5
  implicit none
contains
  function k0001_g4(x) result(r)
    !$omp declare target
    integer(8), intent(in) :: x
    integer(8) :: r
    r = k0001_g5(mod(x * 5, 1013_8) + 4) + 4
  end function k0001_g4
end module k0001_c4
module k0001_c3
  use st_util
  use k0001_glob
  use k0001_c4
  implicit none
contains
  function k0001_g3(x) result(r)
    !$omp declare target
    integer(8), intent(in) :: x
    integer(8) :: r
    r = k0001_g4(mod(x * 5, 1013_8) + 3) + 3
  end function k0001_g3
end module k0001_c3
module k0001_c2
  use st_util
  use k0001_glob
  use k0001_c3
  implicit none
contains
  function k0001_g2(x) result(r)
    !$omp declare target
    integer(8), intent(in) :: x
    integer(8) :: r
    r = k0001_g3(mod(x * 5, 1013_8) + 2) + 2
  end function k0001_g2
end module k0001_c2
module k0001_c1
  use st_util
  use k0001_glob
  use k0001_c2
  implicit none
contains
  function k0001_g1(x) result(r)
    !$omp declare target
    integer(8), intent(in) :: x
    integer(8) :: r
    r = k0001_g2(mod(x * 5, 1013_8) + 1) + 1
  end function k0001_g1
end module k0001_c1
module st_kern
  use st_util
  implicit none
contains
  subroutine k0001(cs)
    use k0001_c1
    use k0001_glob
    implicit none
    integer(8), intent(out) :: cs
    integer(8) :: out(256)
    integer :: i
    gv = 77
    !$omp target update to(gv)
    out = 0
    !$omp target teams distribute parallel do map(tofrom: out)
    do i = 1, 256
      out(i) = k0001_g1(int(i, 8))
    end do
    !$omp end target teams distribute parallel do
    call st_cksum(out, 256, cs)
  end subroutine k0001
end module st_kern
program stress_main
  use st_util
  use st_kern
  use omp_lib
  implicit none
  integer(8) :: cs, total
  integer :: onhost
  total = 0
  call k0001(cs)
  print '(a,i0)', 'K k0001 ', cs
  total = mod(total + cs, st_p)
  onhost = 1
  !$omp target map(tofrom: onhost)
  if (.not. omp_is_initial_device()) onhost = 0
  !$omp end target
  print '(a,i0,a,i0)', 'RESULT checksum=', total, ' ran_on_host=', onhost
end program stress_main
