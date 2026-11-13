! Minimized by compliance.fuzz_min from fuzz seed 87 (fuzz-1).
! toolchain: afar (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: wrong_code
! expected: the host reference checksum (host reference (afar) checksum=748154768)
! observed: device checksum=0 ran_on_host=0
! Legal OpenMP 5.2: offload.engine.rules accepts it (offload.engine.prerun.check, rerun: with the
!   race rule and the restriction checks); nvfortran/nvc 26.9 and 25.11 (NVHPC, not under test
!   here) compile it; the check's other witness, the AFAR flang front end, is the compiler under
!   test and is not counted; no gfortran or gcc is a legality witness.
program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 32, m = 3
  integer, allocatable :: o1(:, :)
  integer :: i, j, p1
  integer(8) :: cs
  allocate(o1(n, m))
  o1 = 0
  p1 = 4
  ! fuzz: kernels
  !$omp target
    !$omp teams firstprivate(p1)
      !$omp distribute
      do i = n, 1, -1
        !$omp parallel firstprivate(p1)
          !$omp do
          do j = 1, m, 2
            o1(i, j) = p1
          end do
          !$omp end do
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
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', 0
end program fuzz_prog
! site:
! title: amdflang: a parallel region with firstprivate nested in a distribute loop loses the writes of its worksharing loop
! same_as: fuzz/650-afar
! end site
