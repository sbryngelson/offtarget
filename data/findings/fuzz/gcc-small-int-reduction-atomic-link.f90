! # Finding (GCC 16.2): GCC for amdgcn: a teams reduction(ieor) on an integer(kind=1) variable fails to link (__atomic_fetch_xor_1
!   undefined)
!
! - toolchains and modes that fail: gcc (GCC 16.2.0); modes: copy; -O2
! - build: gfortran -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx942 -O2
! - failure: rejected
! - observed: `ld: error: undefined symbol: __atomic_fetch_xor_1`; identical signature on 1 of 1 failing cells
! - expected: compiles, links and prints `RESULT ran_on_host=0 check=pass`
! - rule: ieor is a reduction identifier for any integer list item: "A reduction identifier is either a base language identifier, or
!   a user-defined operator, or one of the following operators: +, - (deprecated), *, .and., .or., .eqv., .neqv., or one of the
!   following intrinsic procedure names: max, min, iand, ior, ieor." (OpenMP 5.2 §5.5.1 p.124 l.22-24); no restriction excludes
!   integer kinds 1 or 2
! - other families: afar (AFAR 24.3.0), afar244 (AFAR 24.4.0) run the file correctly (site rows, check case
!   site-fuzz--gcc-small-int-reduction-atomic-link); cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE
!   21.0.4) fail it another way, e.g. `Creating internal compiler error backtrace (please wait):`
! - same-compiler control: controls/gcc-small-int-reduction-atomic-link-delete-clause-reduction-ieor-r2a-control.f90 (one change
!   from this file; correct on gcc (GCC 16.2.0); site rows, check case site-fuzz--gcc-small-int-reduction-atomic-link)
! - legality: legal by reading: teams reduction(ieor: r2a) on an integer(kind=1) scalar mapped implicitly in a target region, with
!   an empty teams body. The rules witness (offload.engine.prerun) accepts it, and other families' front ends compile and run it
!   correctly (the rows)
program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 200, m = 5
  integer(kind=1) :: r2a
  integer :: i, j, hf1
  integer(8) :: cs
  hf1 = 0
  r2a = 3_1
  ! fuzz: kernels
  !$omp target map(tofrom: hf1)
    !$omp masked
      hf1 = merge(1, 0, omp_is_initial_device())
    !$omp end masked
  !$omp end target
  !$omp target
    !$omp teams reduction(ieor: r2a)
    !$omp end teams
  !$omp end target
  ! fuzz: checksum
  cs = 0
  cs = modulo(cs * 31_8 + int(r2a, 8), 2147483629_8)
  print '(a,i0)', 'checksum= ', cs
  print '(a,i0,a,a)', 'RESULT ran_on_host=', max(hf1, 0), ' check=', merge('pass', 'fail', cs == 3_8)
end program fuzz_prog

! site:
! title: GCC: reduction on a 1- or 2-byte integer fails to link for AMD GPUs
! summary: GCC 16.2 lowers a teams reduction(ieor/iand/ior) on an integer(kind=1) or integer(kind=2) variable to
! + __atomic_fetch_*_1/_2 calls that its amdgcn offload target does not define, so the program does not link.
! control: fuzz/controls/gcc-small-int-reduction-atomic-link-delete-clause-reduction-ieor-r2a-control.f90 one change from the
! + finding; correct on gcc
! end site
