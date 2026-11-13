! Minimized by compliance.fuzz_min from fuzz seed 916 (fuzz-1).
! toolchain: afar (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: run_error (crash: SIGABRT)
! expected: runs to completion (the host run does)
! observed: device: fail crash: SIGABRT; host reference (afar/cce19) checksum=0
! Legal OpenMP 5.2: offload.engine.rules accepts it (offload.engine.prerun.check, rerun: with the
!   race rule and the restriction checks); nvfortran/nvc 26.9 and 25.11 (NVHPC, not under test
!   here) compile it; the check's other witness, the AFAR flang front end, is the compiler under
!   test and is not counted; no gfortran or gcc is a legality witness.
program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 48, m = 8
  integer, allocatable :: o1(:, :)
  integer :: i, j, r1a
  integer(8) :: cs
  allocate(o1(n, m))
  o1 = 0
  r1a = 65535
  ! fuzz: kernels
  !$omp target map(tofrom: r1a)
    !$omp teams reduction(iand: r1a)
      !$omp distribute
      do i = n, 1, -1
        !$omp parallel
          !$omp do reduction(iand: r1a)
          do j = 1, m
            o1(i, j) = 0
            r1a = iand(r1a, i)
          end do
          !$omp end do
        !$omp end parallel
      end do
      !$omp end distribute
    !$omp end teams
  !$omp end target
  ! fuzz: checksum
  cs = 0
  cs = modulo(cs * 31_8 + int(r1a, 8), 2147483629_8)
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o1(i, j), 8), 2147483629_8)
    end do
  end do
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', 0
end program fuzz_prog
! site:
! title: amdflang at HSA_XNACK=1: a parallel region with a reduction (or atomic) nested in a distribute loop of a reducing teams
! + region aborts
! control: ../vendor/checks/src/fuzz/control/fuzz-916-afar-control.f90 the inner parallel region and its do construct removed
! + (the team
! + runs the
! + j loop sequentially)
! end site
! spec (requirement): a reduction clause on a teams construct combines the private copy of every team into the original list
!   item at the end of the region, and a reduction clause on a worksharing loop requires the list item to be shared in the
!   enclosing parallel region and combines the threads' private copies, so nested reductions over the same variable are legal.
! "For the teams construct, one or more private copies of each list item are created for the initial task of each team in the
!   league, as if the private clause had been used. For the loop construct, private copies are created and used in the construct
!   according to the description and restrictions in Section 5.3. At the end of a region that corresponds to a construct for which
!   the reduction clause was specified, the original list item is updated by combining its original value with the final value of
!   each of the private copies, using the combiner of the specified reduction-identifier." (5.2 §5.5.8 p.135 l.4-10)
! "A list item that appears in a reduction clause on a worksharing construct must be shared in the parallel region to which a
!   corresponding worksharing region binds." (5.2 §5.5.8 p.135 l.26-27)
! spec (this program): teams reduction(iand: r1a) containing a distribute loop whose body has a parallel region with a do
!   reduction(iand: r1a) is legal (r1a is shared in the parallel region); AFAR at HSA_XNACK=1 aborts at run time (SIGABRT), and
!   the program is correct when the inner parallel region and its do construct are removed.
