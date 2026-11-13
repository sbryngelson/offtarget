! Minimized by compliance.fuzz_min from fuzz seed 1936 (fuzz-1).
! toolchain: afar (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: wrong_code
! expected: the host reference checksum (host reference (afar) checksum=2147483504)
! observed: device checksum=129 ran_on_host=0
! Legal OpenMP 5.2: offload.engine.rules accepts it (offload.engine.prerun.check, rerun: with the
!   race rule and the restriction checks); NVHPC is no witness: it does not implement a feature the
!   program uses (NVFORTRAN-F-1196-OpenMP - omp critical is not supported in GPU
!   region); the check's other witness, the AFAR flang front end, is the compiler under test and is
!   not counted; no gfortran or gcc is a legality witness.
module fuzz_mod
  implicit none
contains
  integer function g1(x)
    !$omp declare target
    integer, intent(in) :: x
    g1 = mod(ior(merge(4, x, x /= 4), 4), 97)
  end function g1
end module fuzz_mod
program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  use fuzz_mod, only: g1
  implicit none
  integer, parameter :: n = 100, m = 8
  integer, allocatable :: ia(:)
  integer :: ib(n)
  integer :: i, j, r1a
  logical :: lt
  integer(8) :: cs
  allocate(ia(n))
  do i = 1, n
    ia(i) = mod(i * 4 + 30, 211) - 80
  end do
  do i = 1, n
    ib(i) = mod(i * 58 + 12, 97) - 31
  end do
  r1a = 15
  lt = .true.
  ! fuzz: kernels
  !$omp target map(tofrom: r1a)
    !$omp parallel
      !$omp do
      do i = 1, n
        do j = m, 1, -1
          !$omp critical
          r1a = ieor(r1a, ((ib((mod(((j * 1) + 2), n) + 1)) + ib(32)) - ia(i)))
          !$omp end critical
        end do
      end do
      !$omp end do
    !$omp end parallel
  !$omp end target
  ! fuzz: checksum
  cs = 0
  cs = modulo(cs * 31_8 + int(r1a, 8), 2147483629_8)
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', 0
end program fuzz_prog
! site:
! title: amdflang: an unnamed critical in a target parallel do does not exclude other threads (lost updates)
! same_as: catalog/afar-flang-critical-target-parallel-wrong
! end site
