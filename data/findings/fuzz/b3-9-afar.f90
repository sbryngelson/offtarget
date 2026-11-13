! Minimized by compliance.fuzz_min from fuzz seed 9 (fuzz-3).
! toolchain: afar (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: ice (afar FIR verification: 'omp.simd' op operand #0 must be variadic of OpenMP-compatible variable type, but got
!   '!fir.box<!fir.array<?x?xi32>>')
! expected: compiles
! observed: internal compiler error: ice: error: verification of lowering to FIR failed
! Legal OpenMP 5.2: offload.engine.rules accepts it (offload.engine.prerun.check, rerun: with the
!   race rule and the restriction checks); NVHPC is no witness: it rejects it
!   (NVFORTRAN-S-0034-Syntax error at or near identifier nontemporal); the
!   check's other witness, the AFAR flang front end, is the compiler under test and is not counted;
!   no gfortran or gcc is a legality witness.
program fuzz_prog
  use omp_lib, only: omp_get_default_device, omp_is_initial_device
  implicit none
  integer, parameter :: n = 200, m = 8
  type :: rec_t
    integer :: a(n)
    integer, allocatable :: q(:)
    integer, pointer :: pc(:)
  end type rec_t
  type(rec_t) :: dr
  integer, allocatable, target :: ia(:)
  integer :: ib(n)
  integer, allocatable :: ic(:, :)
  integer, pointer :: o1(:, :)
  integer, pointer :: o2(:)
  integer, target :: o1t(n, m)
  integer, target :: o2t(n)
  integer :: i, j, r1a, r1b, hf1, r2a, dev
  integer(8) :: cs
  allocate(ia(n))
  allocate(ic(n, m))
  allocate(dr%q(n))
  o1 => o1t
  o2 => o2t
  do i = 1, n
    ia(i) = mod(i * 4 + 15, 1009) - 376
  end do
  do i = 1, n
    ib(i) = mod(i * 3 + 7, 30011) - 3238
  end do
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 1 * j) * 60 + 5, 101) - 34
    end do
  end do
  do i = 1, n
    dr%a(i) = mod(i * 35 + 38, 97) - 36
    dr%q(i) = mod(i * 10 + 45, 211) - 86
  end do
  o1 = 0
  o2 = 0
  r1a = 2
  r1b = 3
  hf1 = 0
  r2a = 4
  dev = omp_get_default_device()
  ! fuzz: kernels
  ! fuzz: checksum
  cs = 0
  cs = modulo(cs * 31_8 + int(r1a, 8), 2147483629_8)
  cs = modulo(cs * 31_8 + int(r1b, 8), 2147483629_8)
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o1t(i, j), 8), 2147483629_8)
    end do
  end do
  cs = modulo(cs * 31_8 + int(r2a, 8), 2147483629_8)
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o2t(i), 8), 2147483629_8)
  end do
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', max(hf1, 0)
contains
  subroutine kp1(ib, o1, dr, zopt)
    integer, intent(in) :: ib(n)
    integer, intent(inout) :: o1(:, :)
    type(rec_t), intent(inout) :: dr
    integer, intent(in), optional :: zopt(:)
    !$omp target
    do i = n, 1, -1
      !$omp simd nontemporal(o1)
      do j = m, 1, -1
      end do
      !$omp end simd
    end do
    !$omp end target
  end subroutine kp1
  subroutine kp2(ia, ib, ic, o2, dr, zopt)
    integer, allocatable, intent(inout) :: ia(:)
    integer, intent(in) :: ib(n)
    integer, allocatable, intent(inout) :: ic(:, :)
    integer, intent(inout) :: o2(:)
    type(rec_t), intent(inout) :: dr
    integer, intent(in), optional :: zopt(:)
  end subroutine kp2
end program fuzz_prog
! site:
! title: amdflang: "verification of lowering to FIR failed" for nontemporal on an assumed-shape dummy
! same_as: afar-nontemporal-assumed-shape-ice
! end site
