! Minimized by compliance.fuzz_min from fuzz seed 94 (fuzz-3).
! toolchain: afar (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: wrong_code
! expected: the host reference checksum (host reference (elision) checksum=2012829416)
! observed: device checksum=0 ran_on_host=0
! Legal OpenMP 5.2: offload.engine.rules accepts it (offload.engine.prerun.check, rerun: with the
!   race rule and the restriction checks); nvfortran/nvc 26.9 and 25.11 (NVHPC, not under test
!   here) compile it; the check's other witness, the AFAR flang front end, is the compiler under
!   test and is not counted; no gfortran or gcc is a legality witness.
module fuzz_mod
  implicit none
contains
end module fuzz_mod
program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 32, m = 2
  type :: rec_t
    integer :: a(n)
    integer, allocatable :: q(:)
  end type rec_t
  type(rec_t) :: dr
  integer, allocatable :: ib(:)
  integer, allocatable :: o1(:, :)
  integer, pointer :: o2(:, :)
  integer :: s3(n)
  integer, allocatable :: s4(:)
  integer, target :: o2t(n, m)
  integer, target :: tgc(n)
  integer :: i, j
  integer(8) :: cs
  allocate(ib(n))
  allocate(o1(n, m))
  allocate(s4(n))
  allocate(dr%q(n))
  o2 => o2t
  do i = 1, n
    ib(i) = mod(i * 16 + 35, 30011) - 1727
  end do
  do i = 1, n
    dr%a(i) = mod(i * 5 + 17, 211) - 48
    dr%q(i) = mod(i * 50 + 39, 1009) - 500
    tgc(i) = mod(i * 55 + 22, 97) - 32
  end do
  o1 = 0
  o2 = 0
  s3 = 0
  s4 = 0
  ! fuzz: kernels
  !$omp target map(to: dr%a, ib)
    !$omp teams
      !$omp distribute
      do i = n, 1, -1
        !$omp parallel firstprivate(i)
          !$omp do
          do j = 1, m
            o1(i, j) = mod(mod(i, 13), 1009)
          end do
        !$omp end parallel
      end do
    !$omp end teams
  !$omp end target
  ! fuzz: checksum
  cs = 0
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o1(i, j), 8), 2147483629_8)
    end do
  end do
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o2t(i, j), 8), 2147483629_8)
    end do
  end do
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', 0
end program fuzz_prog
! site:
! title: amdflang: a parallel region with firstprivate nested in a distribute loop loses the writes of its worksharing loop
! same_as: fuzz/650-afar
! end site
