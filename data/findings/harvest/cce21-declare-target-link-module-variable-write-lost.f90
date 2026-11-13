! # Finding: CCE 21 ftn loses the target region's write to a module
! # variable in a declare target link clause that the target construct maps
! # tofrom (CCE 19 and 20 correct)
!
! - compilers: CCE ftn 21.0.3 and 21.0.4, -O2: this file on MI300A gfx942
!   (HSA_XNACK 0 and 1); the two AOMP tests it comes from also on MI250X
!   gfx90a with 21.0.3.
! - expected: v= 1 dev= T
! - actual: v= 0 dev= T (the region runs on the device; the original v keeps
!   its value), every run, both memory modes.
! - rule: the link clause "does not map the list items. Instead, they are
!   mapped according to the data-mapping rules described in Section 5.8"
!   (5.2 §5.8.5 p.159 l.24-27), so map(tofrom: v) on the target construct
!   maps v with a reference count of one and on exit "the original list item
!   is updated as if the list item appeared in a from clause on a target
!   update directive" (5.2 §5.8.3 p.154 l.3-5). OpenMP 4.5 already has the
!   link clause.
! - regression: CCE 19.0.0 and 20.0.2 print v= 1 dev= T (gfx942 both modes;
!   gfx90a).
! - same-compiler controls (CCE 21.0.3 and 21.0.4 correct, v= 1 dev= T):
!   the same map on an enclosing target data construct (target data
!   map(tofrom: v), then target without a map of v); v without the declare
!   target directive. (With enter(v) instead of link(v) v= 0 is the expected
!   result: the variable is present for the whole program and the exit update
!   happens only at a reference count of one, 5.2 §5.8.3 p.154 l.3-5; AFAR and
!   CCE 21 print v= 0, CCE 19 and 20 reject enter.)
! - other families: AFAR amdflang prints v= 1 dev= T (gfx942 X0 and X1,
!   gfx90a).
! - harvest: dev programs h2-aomp-smoke-fort-declare-target-link-2 and
!   h2-aomp-fortran-map-tests-even-basicer-example (data/bench/harvest2; AOMP
!   test/smoke-fort/declare-target-link-2 and
!   test/fortran-map-tests/even-basicer-example.f95), wrong_answer on CCE 21
!   only, gate confirmed on gfx90a.
! - legality: offload.engine.prerun.check accepts it (the rules with the race
!   rule, and the AFAR flang front end).
! CCE:  ftn -fopenmp -O2 (module load cce/<v> craype-accel-amd-gfx942 rocm/<r>;
!       module unload cray-mpich)
! Run:  OMP_TARGET_OFFLOAD=mandatory ./a.out
module m
  implicit none
  integer :: v = 0
  !$omp declare target link(v)
end module m
program p
  use m
  use omp_lib
  implicit none
  logical :: dev
  dev = .false.
  !$omp target map(tofrom: v) map(from: dev)
  v = 1
  dev = .not. omp_is_initial_device()
  !$omp end target
  print '(a,i0,a,l1)', 'v= ', v, ' dev= ', dev
  if (v == 1) then
    print '(a,i0,a)', 'RESULT ran_on_host=', merge(0, 1, dev), ' check=pass'
  else
    print '(a,i0,a)', 'RESULT ran_on_host=', merge(0, 1, dev), ' check=fail'
  end if
end program p
! site:
! title: ftn 21 loses a target region's write to a declare target link module variable mapped tofrom
! end site
