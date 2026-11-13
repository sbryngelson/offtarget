! Minimized by compliance.fuzz_min from fuzz seed 39 (fuzz-3).
! toolchain: afar (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: wrong_code
! expected: the host reference checksum (host reference (cce19) checksum=1462161356)
! : not reproducible on the current install (AFAR 24.3.0; reruns,
!   data/vendor/README.md: held, not reproducible); kept as a record.
! observed: device checksum=617091188 ran_on_host=0
! Legal OpenMP 5.2: offload.engine.rules accepts it (offload.engine.prerun.check, rerun: with the
!   race rule and the restriction checks); NVHPC is no witness: it does not implement a feature the
!   program uses (NVFORTRAN-W-0287-Unrecognized OpenMP directive - declare); the
!   check's other witness, the AFAR flang front end, is the compiler under test and is not counted;
!   no gfortran or gcc is a legality witness.
module fuzz_dmod
  implicit none
  integer, parameter :: nm = 48
  type :: gp_t
    integer :: k(nm)
  end type gp_t
  type :: mt_t
    integer :: a(nm)
  end type mt_t
  type :: pair_t
    integer :: x
  end type pair_t
  integer :: gtab(nm)
  type(gp_t) :: gs
  !$omp declare target to(gtab, gs)
  !$omp declare mapper(mmap: mt_t :: v) map(tofrom: v%a)
contains
  integer function gm0(x)
    !$omp declare target
    integer, intent(in) :: x
    gm0 = 0
  end function gm0
end module fuzz_dmod
module fuzz_dfun
  use fuzz_dmod
  implicit none
contains
  integer function gd1(x)
    !$omp declare target
    integer, intent(in) :: x
    gd1 = mod(gtab((mod(abs(x), nm) + 1)), 1009)
  end function gd1
end module fuzz_dfun
module fuzz_mod
  implicit none
contains
  integer function g1(x)
    !$omp declare target
    integer, intent(in) :: x
    g1 = mod(mod(x, 7), 9973)
  end function g1
end module fuzz_mod
program fuzz_prog
  use omp_lib, only: omp_get_default_device, omp_is_initial_device
  use fuzz_mod, only: g1
  use fuzz_dmod
  use fuzz_dfun, only: gd1
  implicit none
  integer, parameter :: n = 48, m = 4
  type(mt_t) :: ms
  integer, allocatable :: ia(:)
  integer, allocatable :: ib(:)
  integer, allocatable :: ic(:, :)
  integer, allocatable :: o1(:)
  integer :: o2(n, m)
  integer :: i, j, p2, r1a, hf1, r2a, r2b, hf2, t2, dev
  integer(8) :: cs
  allocate(ia(n))
  allocate(ib(n))
  allocate(ic(n, m))
  allocate(o1(n))
  do i = 1, n
    ia(i) = mod(i * 46 + 48, 211) - 30
  end do
  do i = 1, n
    ib(i) = mod(i * 49 + 30, 30011) - 1444
  end do
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 7 * j) * 49 + 46, 1009) - 2
    end do
  end do
  do i = 1, n
    gtab(i) = mod(i * 51 + 9, 1009) - 215
    gs%k(i) = mod(i * 50 + 33, 211) - 100
    ms%a(i) = mod(i * 43 + 26, 101) - 50
  end do
  o1 = 0
  o2 = 0
  p2 = 8
  r1a = -78
  hf1 = 0
  r2a = -73
  r2b = 1
  hf2 = 0
  dev = omp_get_default_device()
  !$omp target update to(gtab, gs)
  ! fuzz: kernels
  !$omp target data map(to: ia, ib, ic) map(tofrom: o1, o2)
    !$omp target map(tofrom: p2, hf1, r1a) device(dev)
    !$omp end target
    !$omp target map(tofrom: r2a) map(tofrom: r2b)
      !$omp teams reduction(max: r2a) reduction(*: r2b) thread_limit(16) shared(hf2) &
      !$omp& private(i, j, t2)
        !$omp distribute
        do i = 1, n
          !$omp parallel proc_bind(primary)
            !$omp do reduction(max: r2a) reduction(*: r2b) private(t2)
            do j = 1, m
              t2 = i
              o2(i, j) = mod(mod(min((ib(i) + t2), (ib(i) + ms%a((49 - i)))), 7), 97)
              r2b = r2b * merge((-1), 1, mod(ms%a((49 - i)), 11) == 0)
            end do
          !$omp end parallel
        end do
        !$omp end distribute
      !$omp end teams
    !$omp end target
  !$omp end target data
  ! fuzz: checksum
  cs = 0
  cs = modulo(cs * 31_8 + int(r1a, 8), 2147483629_8)
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o1(i), 8), 2147483629_8)
  end do
  cs = modulo(cs * 31_8 + int(r2a, 8), 2147483629_8)
  cs = modulo(cs * 31_8 + int(r2b, 8), 2147483629_8)
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o2(i, j), 8), 2147483629_8)
    end do
  end do
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', max(hf1, hf2, 0)
end program fuzz_prog
! site:
! title: amdflang at HSA_XNACK=1: a parallel region with a reduction (or atomic) nested in a distribute loop of a reducing teams
! + region aborts
! same_as: fuzz/916-afar
! end site
