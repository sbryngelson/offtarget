! Minimized by compliance.fuzz_min from fuzz seed 121 (fuzz-3).
! toolchain: afar (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: wrong_code
! expected: the host reference checksum (host reference (cce19) checksum=1048575)
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
  integer, parameter :: n = 24, m = 3
  integer :: i, j, p1, r1a
  integer(8) :: cs
  p1 = -4
  r1a = 1048575
  ! fuzz: kernels
  !$omp target map(tofrom: r1a)
    !$omp teams reduction(iand: r1a) firstprivate(p1)
    !$omp end teams
  !$omp end target
  ! fuzz: checksum
  cs = 0
  cs = modulo(cs * 31_8 + int(r1a, 8), 2147483629_8)
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', 0
end program fuzz_prog
! site:
! title: amdflang: teams reduction(iand: r) with firstprivate and an empty body sets r to 0
! control: ../vendor/checks/src/fuzz/control/fuzz-b1-121-afar-control.f90 firstprivate(p1) removed from the teams construct
! end site
! spec (requirement): each private copy of a reduction list item is initialized with the initializer value of the reduction
!   identifier (for iand, all bits on), and at the end of the region the original list item is combined with the private copies,
!   so an empty teams region leaves the original value unchanged.
! "The reduction clause is a reduction scoping clause and a reduction participating clause, as described in Section 5.5.6 and
!   Section 5.5.7. For each list item, a private copy is created for each implicit task or SIMD lane and is initialized with the
!   initializer value of the reduction-identifier. After the end of the region, the original list item is updated with the values
!   of the private copies using the combiner associated with the reduction-identifier." (5.2 §5.5.8 p.134 l.20-24)
! "At the end of a region that corresponds to a construct for which the reduction clause was specified, the original list item
!   is updated by combining its original value with the final value of each of the private copies, using the combiner of the
!   specified reduction-identifier." (5.2 §5.5.8 p.135 l.7-10)
! spec (this program): teams reduction(iand: r1a) firstprivate(p1) with an empty body must leave r1a at 1048575 (iand with the
!   identity); AFAR returns 0, and the program is correct when firstprivate(p1) is removed.
