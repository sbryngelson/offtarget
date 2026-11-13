! Minimized by compliance.fuzz_min from fuzz seed 650 (fuzz-1).
! toolchain: afar (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: wrong_code
! expected: the host reference checksum (host reference (afar/cce19) checksum=649664593)
! observed: device checksum=0 ran_on_host=0
! also observed (reductions of this family, data/reports/fuzz5-oop-afar.md, cluster B): at HSA_XNACK=0 an
!   explicit-shape array written in the nested parallel region, and an implicitly mapped allocatable, fault
!   (GPU memory access fault) instead of giving a wrong value; the same program without firstprivate(i) is correct.
! Legal OpenMP 5.2: offload.engine.rules accepts it (offload.engine.prerun.check, rerun: with the
!   race rule and the restriction checks); nvfortran/nvc 26.9 and 25.11 (NVHPC, not under test
!   here) compile it; the check's other witness, the AFAR flang front end, is the compiler under
!   test and is not counted; no gfortran or gcc is a legality witness.
program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 100, m = 3
  integer, allocatable :: o1(:, :)
  integer :: i, j
  logical :: lt
  integer(8) :: cs
  allocate(o1(n, m))
  o1 = 0
  lt = .true.
  ! fuzz: kernels
  !$omp target teams distribute
  do i = 1, n
    !$omp parallel firstprivate(i)
      !$omp do
      do j = 1, m
        o1(i, j) = i
      end do
      !$omp end do
    !$omp end parallel
  end do
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
! control: ../vendor/checks/src/fuzz/control/fuzz-650-afar-control.f90 firstprivate(i) removed from the parallel construct
! end site
! spec (requirement): a firstprivate clause gives the construct a private, initialized copy of the named list item only, and an
!   array that a target region references and no clause names is mapped tofrom, so the writes of the worksharing loop in the
!   parallel region reach the shared array.
! "In addition, the new list item is initialized from the original list item that exists before the construct. The
!   initialization of the new list item is done once for each task that references the list item in any statement in the
!   construct. The initialization is done prior to the execution of the construct." (5.2 §5.4.4 p.112 l.11-14)
! "If a variable is not a scalar then it is treated as if it had appeared in a map clause with a map-type of tofrom." (5.2
!   §5.8.1 p.149 l.4-5)
! spec (this program): parallel firstprivate(i) with a worksharing do loop that stores o1(i, j) = i, nested in the distribute
!   loop of a target teams construct, must leave o1 filled; AFAR loses the writes (checksum 0, or a memory fault at HSA_XNACK=0),
!   while the same program without firstprivate(i) is correct.
