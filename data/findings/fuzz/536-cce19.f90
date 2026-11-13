! Minimized by compliance.fuzz_min from fuzz seed 536 (fuzz-1).
! toolchain: cce19 (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: wrong_code
! expected: the host reference checksum (host reference (cce19/afar) checksum=716289326)
! observed: device checksum=820542974 ran_on_host=0
! Legal OpenMP 5.2: offload.engine.prerun.check accepts it (rerun: offload.engine.rules with the
!   race rule and the restriction checks, and the AFAR flang front end, not under test here); no
!   compiler under test, gfortran or gcc is a legality witness.
! also fails on: cce20, cce21
program fuzz_prog
  use omp_lib, only: omp_get_thread_num, omp_is_initial_device
  implicit none
  integer, parameter :: n = 48, m = 8
  integer, allocatable :: o1(:)
  integer :: i, j
  integer(8) :: cs
  allocate(o1(n))
  o1 = 0
  ! fuzz: kernels
  !$omp target parallel
    if (omp_get_thread_num() == 0) then
      do i = 1, n
        o1(i) = i
      end do
    end if
  !$omp end target parallel
  ! fuzz: checksum
  cs = 0
  do i = 1, n
    cs = modulo(cs * 31_8 + int(o1(i), 8), 2147483629_8)
  end do
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', 0
end program fuzz_prog
! site:
! title: ftn -fopenmp: a sequential DO loop executed by one thread of a target parallel region runs only some of its iterations
! + (-O2)
! same_as: cce19-target-parallel-guarded-loop
! end site
