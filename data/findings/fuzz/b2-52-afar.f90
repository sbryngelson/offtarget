! Minimized by compliance.fuzz_min from fuzz seed 52 (fuzz-3).
! toolchain: afar (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: wrong_code
! expected: the host reference checksum (host reference (cce19) checksum=1272193681)
! observed: device checksum=2115128177 ran_on_host=0
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
  integer, parameter :: n = 64, m = 2
  type :: nd_t
  end type nd_t
  type :: rec_t
    type(nd_t) :: nd
  end type rec_t
  type(rec_t) :: dr
  integer :: o3(n, m)
  integer :: i, j
  integer(8) :: cs
  o3 = 0
  ! fuzz: kernels
  !$omp target
    !$omp teams
      !$omp distribute
      do i = 1, n
        !$omp parallel firstprivate(i)
          !$omp do
          do j = m, 1, -1
            o3(i, j) = 1009
          end do
          !$omp end do
        !$omp end parallel
      end do
      !$omp end distribute
    !$omp end teams
  !$omp end target
  ! fuzz: checksum
  cs = 0
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o3(i, j), 8), 2147483629_8)
    end do
  end do
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', 0
end program fuzz_prog
! site:
! title: amdflang: a parallel region with firstprivate nested in a distribute loop loses the writes of its worksharing loop
! same_as: fuzz/650-afar
! end site
