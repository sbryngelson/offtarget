! # Finding (leads): CCE 19 stops with a run-time error on a Fortran OpenMP program with a collapse clause, a defaultmap clause and
!   a device clause
!
! - toolchains and modes that fail: cce19 (CCE 19.0.0), cce20 (CCE 20.0.2); modes: unified, copy; -O2
! - build: ftn -fopenmp -O2
! - failure: wrong_answer (check=fail)
! - observed: `Unhandled Reduction!!!`; identical signature on 4 of 4 failing cells
! - expected: compiles and prints `checksum= 580626142` with `check=pass`
! - rule: a conforming program runs to completion: "The collapse clause associates one or more loops with the directive on which it
!   appears for the purpose of identifying the portion of the depth of the canonical loop nest to which to apply the semantics of
!   the directive." (OpenMP 5.2 §4.4.3 p.93 l.23-25); "The defaultmap clause determines the implicit data-mapping or data-sharing
!   attribute of certain variables that are referenced in a target construct, in accordance with the rules given in Section 5.8.1."
!   (OpenMP 5.2 §5.8.7 p.161 l.14-16); "The device clause identifies the target device that is associated with a device construct."
!   (OpenMP 5.2 §13.2 p.276 l.11)
! - other families: afar (AFAR 24.3.0), afar244 (AFAR 24.4.0), gcc (GCC 16.2.0) run the file correctly (site rows, check case
!   site-fuzz--cce19-collapse-defaultmap-device-run-error); cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4) fail it another way, e.g.
!   `ftn-7256 ftn: WARNING KP1, File = site-fuzz--cce19-collapse-defaultmap-device-run-error.f90, Line = 176`
! - programs (1): g1x0-o3:511
! - legality: the rules engine accepts it (offload.engine.prerun.rules_witness); afar, afar244 run it correctly in the confirmer's
!   runs (tools/confirm.py case); the legality verdict is computed (tools/review/review.py mechanical)
! - releases: CCE 19.0.0 and 20.0.2 fail it the same way; CCE 21.0.3 and 21.0.4 fail it another way
module fuzz_amod
  implicit none
contains
  integer function ga1(x)
    !$omp declare target
    integer, intent(in) :: x
    ga1 = mod(((iand(x, 1023) * 4) + 45), 1013)
  end function ga1
end module fuzz_amod
!@file fuzz_bmod.f90
module fuzz_bmod
  use fuzz_amod, only: ga1
  implicit none
contains
  integer function gb1(x)
    !$omp declare target
    integer, intent(in) :: x
    gb1 = mod((ga1(x) + (x * 5)), 2003)
  end function gb1
end module fuzz_bmod
!@file fuzz_ext.f90
integer function ge1(x)
  implicit none
  integer, intent(in) :: x
  !$omp declare target
  ge1 = mod((max(x, 28) - 5), 997)
end function ge1
!@file fuzz_prog.f90
program fuzz_prog
  use omp_lib, only: omp_get_default_device, omp_is_initial_device
  use fuzz_amod, only: ga1
  use fuzz_bmod, only: gb1
  implicit none
  interface
    integer function ge1(x)
      !$omp declare target
      integer, intent(in) :: x
    end function ge1
  end interface
  integer, parameter :: n = 24, m = 5
  type :: nd_t
    integer :: k(n)
    real(8) :: w(n)
  end type nd_t
  type :: rec_t
    integer :: a(n)
    real(8) :: b(n)
    integer, allocatable :: q(:)
    integer, pointer :: pc(:)
    type(nd_t) :: nd
  end type rec_t
  type(rec_t) :: dr
  integer :: ia(n)
  integer, allocatable :: ib(:)
  integer, allocatable :: ic(:, :)
  integer, allocatable :: o1(:, :)
  integer :: o2(n)
  integer, allocatable :: o3(:)
  double precision :: xr8(n)
  complex :: xz4(n)
  complex(kind=8) :: xz8(n)
  character(len=4) :: xc(n)
  integer(1) :: xk1(n)
  integer(2) :: xk2(n)
  character(len=8) :: xs
  real(8) :: r1b
  integer, target :: tgc(n)
  integer :: i, j, jj, p1, r1a, hf1, r2a, hf2, r3a, dev
  logical :: lt, lpar
  integer(8) :: cs
  allocate(ib(n))
  allocate(ic(n, m))
  allocate(o1(n, m))
  allocate(o3(n))
  allocate(dr%q(n))
  dr%pc => tgc
  do i = 1, n
    ia(i) = mod(i * 26 + 0, 97) - 45
  end do
  do i = 1, n
    ib(i) = mod(i * 31 + 42, 97) - 10
  end do
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 1 * j) * 51 + 20, 30011) - 215
    end do
  end do
  do i = 1, n
    xr8(i) = real(mod(i * 57 + 4, 97) - 44, 8) * 0.5d0
    xz4(i) = cmplx(mod(i * 4 + 1, 97) - 21, mod(i * 1, 17) - 8, 4)
    xz8(i) = cmplx(mod(i * 21 + 8, 1009) - 4, mod(i * 8, 17) - 8, 8)
    xc(i) = achar(65 + mod(i * 8, 26)) // achar(97 + mod(i + 24, 26)) // achar(48 + mod(i, 10)) // &
        & '#'
    xk1(i) = int(mod(i * 21 + 32, 127), 1)
    xk2(i) = int(mod(i * 53 + 40, 16001) - 8000, 2)
    dr%a(i) = mod(i * 31 + 5, 211) - 78
    dr%b(i) = real(mod(i * 27 + 39, 211) - 78, 8) * 0.5_8
    dr%nd%k(i) = mod(i * 14 + 4, 97) - 41
    dr%nd%w(i) = real(mod(i * 57 + 41, 97) - 47, 8) * 0.5_8
    dr%q(i) = mod(i * 40 + 50, 1009) - 146
    tgc(i) = mod(i * 7 + 32, 211) - 11
  end do
  xs = 'LqmppVwF'
  o1 = 0
  o2 = 0
  o3 = 0
  p1 = 6
  r1a = 212
  hf1 = 0
  r2a = -1
  hf2 = 0
  r3a = 2
  r1b = (-14.5d0)
  lt = .true.
  lpar = .false.
  dev = omp_get_default_device()
  ! fuzz: kernels
  !$omp target data map(to: dr, ia, ib, ic, xc, xk1, xk2, xr8, xs, xz4, xz8) map(tofrom: o1, o2, o3)
    call kp1(ib, o1, xk1, xk2, dr)
    call kp2(o2, dr)
    do i = 1, n
      dr%q(i) = dr%q(i) + 6
    end do
    !$omp target update to(dr%q)
    call kp3(ia, ic, o1, o3, xz8, dr, p1)
  !$omp end target data
  ! fuzz: checksum
  cs = 0
  cs = modulo(cs * 31_8 + int(r1a, 8), 2147483629_8)
  cs = modulo(cs * 31_8 + int(r1b * 64, 8), 2147483629_8)
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o1(i, j), 8), 2147483629_8)
    end do
  end do
  cs = modulo(cs * 31_8 + int(r2a, 8), 2147483629_8)
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o2(i), 8), 2147483629_8)
  end do
  cs = modulo(cs * 31_8 + int(r3a, 8), 2147483629_8)
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o3(i), 8), 2147483629_8)
  end do
  print '(a,i0)', 'checksum= ', cs
  print '(a,i0,a,a)', 'RESULT ran_on_host=', max(hf1, hf2, 0), ' check=', 'pass'
contains
  subroutine kp1(ib, o1, xk1, xk2, dr, zopt)
    integer, intent(inout) :: ib(n)
    integer, intent(inout) :: o1(:, :)
    integer(1), intent(inout) :: xk1(n)
    integer(2), intent(inout) :: xk2(n)
    type(rec_t), intent(inout) :: dr
    integer, intent(in), optional :: zopt(:)
    integer :: i, j, jj, t1
    !$omp target map(present, to: dr%nd%w) map(present, tofrom: dr%nd%k) map(tofrom: hf1) &
    !$omp& map(tofrom: r1a) map(tofrom: r1b) defaultmap(present: aggregate) map(to: zopt)
      hf1 = merge(1, 0, omp_is_initial_device())
      !$omp parallel loop collapse(2) reduction(ieor: r1a) reduction(+: r1b) private(t1) &
      !$omp& num_threads(8)
      do i = 1, n
        do j = 1, m
          t1 = (mod(int(dr%nd%w((mod(((i * 4) + 6), n) + 1))), 1000) + 35)
          o1(i, j) = dr%nd%k(i)
          r1a = ieor(r1a, iand(mod(ior(int(xk2(i)), 38), 13), 255))
          r1b = r1b + (real(mod(merge(ib(i), dr%nd%k((25 - i)), int(xk1(i)) < ib(19)), 97), 8) * &
              & 0.5d0)
        end do
      end do
    !$omp end target
  end subroutine kp1
  subroutine kp2(o2, dr)
    integer, intent(inout) :: o2(n)
    type(rec_t), intent(inout) :: dr
    integer :: i, j, jj
    !$omp taskgroup task_reduction(*: r2a)
      !$omp target map(from: o2) map(present, tofrom: dr%q) map(to: dr%nd%k, dr%pc) &
      !$omp& map(tofrom: hf2) if(lt) in_reduction(*: r2a)
        hf2 = merge(1, 0, omp_is_initial_device())
        !$omp parallel do reduction(*: r2a)
        do i = 1, n
          o2(i) = mod(ge1(((i + dr%nd%k(5)) + (dr%pc(6) / 3))), 9973)
          r2a = r2a * merge(3, 1, mod(dr%q(i), 17) == 0)
        end do
      !$omp end target
    !$omp end taskgroup
  end subroutine kp2
  subroutine kp3(ia, ic, o1, o3, xz8, dr, p1)
    integer, intent(inout) :: ia(:)
    integer, intent(in) :: ic(n, m)
    integer, intent(inout) :: o1(:, :)
    integer, intent(inout) :: o3(:)
    complex(kind=8), intent(inout) :: xz8(n)
    type(rec_t), intent(inout) :: dr
    integer, value :: p1
    integer :: i, j, jj, t3
    !$omp target parallel loop map(close, tofrom: o3) map(present, to: dr%a, dr%nd%w) &
    !$omp& map(present, tofrom: dr%q) map(to: dr%pc, ic) map(tofrom: dr%nd%k, o1, p1) &
    !$omp& defaultmap(to: allocatable) device(device_num: dev) reduction(ior: r3a) private(t3) &
    !$omp& if(parallel: lpar)
    do i = 1, n
      t3 = (min((-4), dr%q(i)) + ((-4) * (-3)))
      o3(i) = merge(int(real(xz8(i))), ishft(iand((dr%nd%k(i) * 3), 1023), (-1)), &
          & iand((int(real(xz8(i))) - o1((mod(((i * 1) + 6), n) + 1), (mod(((i * 2) + 5), m) + &
          & 1))), ior(dr%q(i), nint(dr%nd%w(i)))) <= merge(ior(p1, dr%pc((25 - i))), mod((-4), &
          & 1000), (dr%pc((25 - i)) - dr%a((25 - i))) > iand(dr%a((25 - i)), ia((mod(((i * 3) + 1), &
          & n) + 1)))))
      r3a = ior(r3a, iand((min(ic(i, (mod(((i * 5) + 3), m) + 1)), t3) * 2), 255))
    end do
    !$omp end target parallel loop
  end subroutine kp3
end program fuzz_prog

! site:
! title: CCE: run error with collapse, defaultmap and device
! summary: CCE 19 stops with a run-time error on a Fortran OpenMP program with a collapse clause, a defaultmap clause and a device
! + clause.
! end site
