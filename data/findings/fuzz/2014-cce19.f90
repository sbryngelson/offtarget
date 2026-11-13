! Minimized by compliance.fuzz_min from fuzz seed 2014 (fuzz-1).
! toolchain: cce19 (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: wrong_code
! expected: the host reference checksum (host reference (cce19/afar) checksum=0)
! observed: device checksum=1255704643 ran_on_host=0
! Legal OpenMP 5.2: offload.engine.prerun.check accepts it (rerun: offload.engine.rules with the
!   race rule and the restriction checks, and the AFAR flang front end, not under test here); no
!   compiler under test, gfortran or gcc is a legality witness.
! also fails on: cce20, cce21
program fuzz_prog
  use omp_lib, only: omp_get_thread_num, omp_is_initial_device
  implicit none
  integer, parameter :: n = 100, m = 8
  integer, allocatable :: ib(:)
  integer :: o1(n)
  integer :: i, j, r1a
  integer(8) :: cs
  allocate(ib(n))
  do i = 1, n
    ib(i) = mod(i * 18 + 43, 97) - 44
  end do
  o1 = 0
  r1a = -1
  ! fuzz: kernels
  !$omp target map(tofrom: r1a)
    !$omp parallel
      if (omp_get_thread_num() == 0) then
        do i = n, 1, -1
          r1a = r1a * 0
        end do
      end if
    !$omp end parallel
  !$omp end target
  ! fuzz: checksum
  cs = 0
  cs = modulo(cs * 31_8 + int(r1a, 8), 2147483629_8)
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
