! # Finding (leads): CCE 20 gives a wrong result on a Fortran OpenMP program with an if clause, a num_threads clause and a reduction
!   clause
!
! - toolchains and modes that fail: cce20 (CCE 20.0.2); modes: unified, copy; -O2
! - build: ftn -fopenmp -O2
! - failure: wrong_answer (check=fail)
! - observed: `checksum= 690851396` with `check=fail`; identical signature on 2 of 2 failing cells
! - expected: compiles and prints `checksum= 715049471` with `check=pass`
! - rule: a conforming program's result is the one its constructs define: "If no directive-name-modifier is specified then the
!   effect is as if a directive-name-modifier was specified with the directive-name of the directive on which the clause appears."
!   (OpenMP 5.2 §3.4 p.72 l.11-12); "The num_threads clause specifies the desired number of threads to execute a parallel region."
!   (OpenMP 5.2 §10.1.2 p.227 l.23); "For each list item, a private copy is created for each implicit task or SIMD lane and is
!   initialized with the initializer value of the reduction-identifier." (OpenMP 5.2 §5.5.8 p.134 l.21-22)
! - other families: afar (AFAR 24.3.0), afar244 (AFAR 24.4.0), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4), gcc (GCC 16.2.0) run the
!   file correctly (site rows, check case site-fuzz--cce20-if-num-threads-reduction-wrong); cce19 (CCE 19.0.0) fail it another way,
!   e.g. `ftn-1370 ftn: ERROR FUZZ_PROG, File = site-fuzz--cce20-if-num-threads-reduction-wrong.f90, Line = 193, Column = 17`
! - programs (1): g1x0-o3:298
! - legality: the rules engine accepts it (offload.engine.prerun.rules_witness); afar, afar244, cce21 run it correctly in the
!   confirmer's runs (tools/confirm.py case); the legality verdict is computed (tools/review/review.py mechanical)
! - releases: CCE 19.0.0 fails it another way; CCE 20.0.2 fails it the same way; CCE 21.0.3 and 21.0.4 run it correctly
module fuzz_mod
  implicit none
contains
  integer function g1(x, y)
    !$omp declare target
    integer, intent(in) :: x, y
    g1 = mod((13 + (y * 3)), 9973)
  end function g1
  integer function g2(x, y)
    !$omp declare target
    integer, intent(in) :: x, y
    g2 = mod(((x + 7) - x), 1009)
  end function g2
end module fuzz_mod
!@file fuzz_amod.f90
module fuzz_amod
  implicit none
contains
  integer function ga1(x)
    !$omp declare target
    integer, intent(in) :: x
    ga1 = mod(((iand(x, 1023) * 6) + 27), 1013)
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
    gb1 = mod((ga1(x) + (x * 3)), 2003)
  end function gb1
end module fuzz_bmod
!@file fuzz_smod.f90
module fuzz_smod
  implicit none
  interface
    module integer function gs1(x)
      !$omp declare target
      integer, intent(in) :: x
    end function gs1
  end interface
end module fuzz_smod
!@file fuzz_ssub.f90
submodule (fuzz_smod) fuzz_ssub
  implicit none
contains
  module integer function gs1(x)
    !$omp declare target
    integer, intent(in) :: x
    gs1 = mod(ieor(x, 216), 4093)
  end function gs1
end submodule fuzz_ssub
!@file fuzz_ext.f90
integer function ge1(x)
  implicit none
  integer, intent(in) :: x
  !$omp declare target
  ge1 = mod((max(x, (-23)) - 9), 997)
end function ge1
!@file fuzz_prog.f90
program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  use fuzz_mod, only: g1, g2
  use fuzz_amod, only: ga1
  use fuzz_bmod, only: gb1
  use fuzz_smod, only: gs1
  implicit none
  interface
    integer function ge1(x)
      !$omp declare target
      integer, intent(in) :: x
    end function ge1
  end interface
  integer, parameter :: n = 48, m = 8
  type :: rec_t
    integer :: a(n)
    real(kind=8) :: b(n)
    integer :: s
    integer, allocatable :: q(:)
    integer, pointer :: pc(:)
  end type rec_t
  type :: el_t
    integer :: u
    real(kind=8) :: v
  end type el_t
  type(rec_t) :: dr
  type(el_t) :: ds(n)
  integer, allocatable :: ia(:)
  integer, allocatable :: ib(:)
  integer, allocatable :: ic(:, :)
  integer, allocatable :: as1
  integer :: o1(n, m)
  integer :: o2(n, m)
  double precision, allocatable :: xr8(:)
  complex(kind=8) :: xz8(n)
  logical, allocatable :: xl(:)
  integer(1), allocatable :: xk1(:)
  integer(kind=2) :: xk2(n)
  logical :: r1a
  logical :: r1b
  logical :: r2a
  integer, target :: tgc(n)
  integer :: i, j, jj, p1, hf1, r2b, hf2, t2
  logical :: lt
  integer(8) :: cs
  allocate(ia(n))
  allocate(ib(n))
  allocate(ic(n, m))
  allocate(xr8(n))
  allocate(xl(n))
  allocate(xk1(n))
  allocate(as1)
  allocate(dr%q(n))
  dr%pc => tgc
  do i = 1, n
    ia(i) = mod(i * 6 + 47, 211) - 74
  end do
  do i = 1, n
    ib(i) = mod(i * 57 + 43, 101) - 30
  end do
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 6 * j) * 43 + 13, 1009) - 120
    end do
  end do
  do i = 1, n
    xr8(i) = real(mod(i * 24 + 36, 1009) - 238, 8) * 0.5d0
    xz8(i) = cmplx(mod(i * 36 + 2, 97) - 42, mod(i * 2, 17) - 8, 8)
    xl(i) = mod(i * 18 + 29, 3) == 0
    xk1(i) = int(mod(i * 34 + 0, 127), 1)
    xk2(i) = int(mod(i * 22 + 44, 16001) - 8000, 2)
    dr%a(i) = mod(i * 21 + 11, 1009) - 220
    dr%b(i) = real(mod(i * 19 + 38, 101) - 33, 8) * 0.5_8
    ds(i)%u = mod(i * 61 + 37, 211) - 99
    ds(i)%v = real(mod(i * 61 + 22, 1009) - 342, 8) * 0.5_8
    dr%q(i) = mod(i * 37 + 18, 1009) - 182
    tgc(i) = mod(i * 42 + 14, 211) - 56
  end do
  dr%s = -14
  as1 = 35
  o1 = 0
  o2 = 0
  p1 = 7
  hf1 = 0
  r2b = 2
  hf2 = 0
  r1a = .false.
  r1b = .true.
  r2a = .true.
  lt = .true.
  ! fuzz: kernels
  !$omp target map(to: xk1, xr8) map(tofrom: dr, ic, o1(:, :), hf1, r1a, r1b) if(target: lt)
    !$omp teams reduction(.and.: r1a) reduction(.and.: r1b)
      !$omp distribute
      do i = 1, n
        if (i == 1) hf1 = merge(1, 0, omp_is_initial_device())
        !$omp parallel num_threads(8)
          !$omp do simd reduction(.and.: r1a) reduction(.and.: r1b)
          do j = m, 1, -1
            o1(i, j) = (ga1(ic(i, j)) * mod(ior(ior(int(aimag(xz8((mod(((i * 2) + 7), n) + 1)))), &
                & dr%q(i)), iand(int(xr8(i)), int(xk1((49 - i))))), 7))
            r1a = r1a .and. (merge(int(aimag(xz8((mod(((i * 2) + 7), n) + 1)))), int(xk1((49 - &
                & i))), 39 <= int(xk1((49 - i)))) /= (int(aimag(xz8((mod(((i * 2) + 7), n) + 1)))) &
                & + ds((mod(((i * 3) + 7), n) + 1))%u))
            r1b = r1b .and. ((dr%a(i) + dr%a((49 - i))) > dr%q((mod(((i * 2) + 1), n) + 1)))
          end do
        !$omp end parallel
      end do
      !$omp end distribute
    !$omp end teams
  !$omp end target
  !$omp target map(close, to: as1, xk2) map(to: ds, ib) map(tofrom: dr, o2(:, :), hf2, r2a, r2b) &
  !$omp& if(lt) thread_limit(8)
    hf2 = merge(1, 0, omp_is_initial_device())
    !$omp parallel num_threads(3)
      !$omp do reduction(.and.: r2a) reduction(*: r2b)
      do i = n, 1, -1
        !$omp simd reduction(.and.: r2a) reduction(*: r2b) private(t2)
        do j = 1, m
          t2 = mod(ieor(int(xk2(i)), dr%a(i)), 13)
          o2(i, j) = min(((as1 - dr%a(i)) * 3), p1)
          r2a = r2a .and. (ib((mod(((i * 2) + 1), n) + 1)) /= ds((49 - i))%u)
          r2b = r2b * merge(2, 1, mod(29, 11) == 0)
        end do
      end do
      !$omp end do
    !$omp end parallel
  !$omp end target
  ! fuzz: checksum
  cs = 0
  cs = modulo(cs * 31_8 + merge(1_8, 0_8, r1a), 2147483629_8)
  cs = modulo(cs * 31_8 + merge(1_8, 0_8, r1b), 2147483629_8)
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o1(i, j), 8), 2147483629_8)
    end do
  end do
  cs = modulo(cs * 31_8 + merge(1_8, 0_8, r2a), 2147483629_8)
  cs = modulo(cs * 31_8 + int(r2b, 8), 2147483629_8)
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o2(i, j), 8), 2147483629_8)
    end do
  end do
  print '(a,i0)', 'checksum= ', cs
  print '(a,i0,a,a)', 'RESULT ran_on_host=', max(hf1, hf2, 0), ' check=', merge('pass', 'fail', cs == 715049471_8)
end program fuzz_prog

! site:
! title: CCE: wrong with if, num_threads and reduction
! summary: CCE 20 gives a wrong result on a Fortran OpenMP program with an if clause, a num_threads clause and a reduction clause.
! end site
