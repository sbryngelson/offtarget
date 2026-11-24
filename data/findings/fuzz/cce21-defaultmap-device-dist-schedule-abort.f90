! # Finding (leads): CCE 21 aborts at run time on a Fortran OpenMP program with a defaultmap clause, a device clause and a
!   dist_schedule clause
!
! - toolchains and modes that fail: cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4); modes: unified, copy; -O2
! - build: ftn -fopenmp -O2
! - failure: crash
! - observed: `RUN_FAIL` (killed by signal 11); identical signature on 4 of 4 failing cells
! - expected: compiles and prints `checksum= 357927534` with `check=pass`
! - rule: a conforming program runs to completion: "The defaultmap clause determines the implicit data-mapping or data-sharing
!   attribute of certain variables that are referenced in a target construct, in accordance with the rules given in Section 5.8.1."
!   (OpenMP 5.2 §5.8.7 p.161 l.14-16); "The device clause identifies the target device that is associated with a device construct."
!   (OpenMP 5.2 §13.2 p.276 l.11); "The dist_schedule clause specifies how iterations of associated loops of a distribute construct
!   are divided into contiguous non-empty subsets, called chunks, and how these chunks are distributed among the teams of the
!   league." (OpenMP 5.2 §11.6.1 p.256 l.13-15)
! - other families: afar (AFAR 24.3.0), afar244 (AFAR 24.4.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2) run the file correctly (site
!   rows, check case site-fuzz--cce21-defaultmap-device-dist-schedule-abort); gcc (GCC 16.2.0) fail it another way, e.g. `ld: error:
!   undefined symbol: __atomic_fetch_or_1`
! - programs (1): g1x0-o3:1861
! - legality: the rules engine accepts it (offload.engine.prerun.rules_witness); afar, afar244, cce19, cce20 run it correctly in the
!   confirmer's runs (tools/confirm.py case); the legality verdict is computed (tools/review/review.py mechanical)
program fuzz_prog
  use omp_lib, only: omp_get_default_device, omp_is_initial_device
  implicit none
  integer, parameter :: n = 200, m = 8
  type :: nd_t
    integer :: k(n)
  end type nd_t
  type :: rec_t
    integer :: a(n)
    integer :: s = 10
    integer, pointer :: pc(:)
    type(nd_t) :: nd
  end type rec_t
  type(rec_t) :: dr
  integer, allocatable :: ia(:)
  integer :: ib(n)
  integer :: ic(n, m)
  integer, allocatable :: as1
  integer, allocatable :: o1(:)
  integer, allocatable :: o2(:, :)
  real :: xr4(n)
  double precision :: xr8(n)
  complex(kind=4), allocatable :: xz4(:)
  integer(kind=1), allocatable :: xk1(:)
  integer(2), allocatable :: xk2(:)
  integer(1) :: r1a
  integer, target :: tgc(n)
  integer :: i, j, jj, p1, p2, hf1, r2a, hf2, dev
  integer(8) :: cs
  allocate(ia(n))
  allocate(xz4(n))
  allocate(xk1(n))
  allocate(xk2(n))
  allocate(o1(n))
  allocate(o2(n, m))
  allocate(as1)
  dr%pc => tgc
  do i = 1, n
    ia(i) = mod(i * 48 + 47, 30011) - 8890
  end do
  do i = 1, n
    ib(i) = mod(i * 12 + 48, 211) - 74
  end do
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 4 * j) * 52 + 39, 30011) - 579
    end do
  end do
  do i = 1, n
    xr4(i) = real(mod(i * 28 + 27, 97) - 33, 4) * 0.5
    xr8(i) = real(mod(i * 15 + 8, 97) - 40, 8) * 0.5d0
    xz4(i) = cmplx(mod(i * 10 + 6, 97) - 8, mod(i * 6, 17) - 8, 4)
    xk1(i) = int(mod(i * 55 + 13, 127), 1)
    xk2(i) = int(mod(i * 25 + 44, 16001) - 8000, 2)
    dr%a(i) = mod(i * 3 + 50, 211) - 55
    dr%nd%k(i) = mod(i * 19 + 47, 1009) - 55
    tgc(i) = mod(i * 57 + 27, 1009) - 177
  end do
  as1 = 39
  o1 = 0
  o2 = 0
  p1 = 1
  p2 = 9
  hf1 = 0
  r2a = 65535
  hf2 = 0
  r1a = 4_1
  dev = omp_get_default_device()
  ! fuzz: kernels
  call kp1(ia, ib, o1, xk1, xk2, p2)
  ! fuzz: checksum
  cs = 0
  cs = modulo(cs * 31_8 + int(r1a, 8), 2147483629_8)
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o1(i), 8), 2147483629_8)
  end do
  cs = modulo(cs * 31_8 + int(r2a, 8), 2147483629_8)
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o2(i, j), 8), 2147483629_8)
    end do
  end do
  print '(a,i0)', 'checksum= ', cs
  print '(a,i0,a,a)', 'RESULT ran_on_host=', max(hf1, hf2, 0), ' check=', 'pass'
contains
  subroutine kp1(ia, ib, o1, xk1, xk2, p2, zopt)
    integer, intent(inout) :: ia(:)
    integer, intent(in) :: ib(:)
    integer, intent(inout) :: o1(:)
    integer(kind=1), intent(inout) :: xk1(:)
    integer(2), intent(inout) :: xk2(:)
    integer, intent(in) :: p2
    integer, intent(in), optional :: zopt(:)
    integer :: i, j, jj, acc1
    !$omp target teams distribute map(from: o1) map(to: ib(1:n)) map(tofrom: xk1, xk2, hf1) &
    !$omp& reduction(ior: r1a) private(acc1, jj) dist_schedule(static, 5) map(to: zopt)
    do i = 1, n
      acc1 = 0
      r1a = ior(r1a, iand(xk1(160), int(iand(ishft(iand(p2, 1023), 0), 127), 1)))
    end do
    !$omp end target teams distribute
  end subroutine kp1
  subroutine kp2(o1, o2, xr8, p1, p2)
    integer, intent(inout) :: o1(:)
    integer, intent(inout) :: o2(:, :)
    double precision, intent(inout) :: xr8(:)
    integer, intent(in) :: p1
    integer, intent(in), optional :: p2
    integer :: i, j, jj
    !$omp target teams map(from: o2) map(to: p2) map(tofrom: o1, hf2) &
    !$omp& defaultmap(default: scalar) device(dev) reduction(iand: r2a)
      !$omp distribute parallel do reduction(iand: r2a) default(none) shared(hf2, o1, o2, xr8) &
      !$omp& private(j) firstprivate(p1, p2)
      do i = 1, n
        if (i == 1) hf2 = merge(1, 0, omp_is_initial_device())
      end do
    !$omp end target teams
  end subroutine kp2
end program fuzz_prog

! site:
! title: CCE: abort with defaultmap, device and dist_schedule
! summary: CCE 21 aborts at run time on a Fortran OpenMP program with a defaultmap clause, a device clause and a dist_schedule
! + clause.
! end site
