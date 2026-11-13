! # Finding (GCC 16.2, harvests): the same variable in two map clauses of one target construct is rejected
!
! - toolchains: gcc_g90 (GCC 16.2.0, AMD Instinct MI250X gfx90a, Tioga) and gcc_sm80 (GCC 16.2.0, NVIDIA A100 sm_80, wingtip);
!   separate memory only; -O2
! - build: gfortran -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx90a -O2 (gcc_g90);
!   -foffload=nvptx-none -foffload-options=nvptx-none=-march=sm_80 -foffload-options=nvptx-none=-latomic -O2 (gcc_sm80)
! - failure: rejected: Error: Symbol 'x' present on multiple clauses at (1)
! - observed: `Error: Symbol 'x' present on multiple clauses at (1)` at the target directive, on both targets
! - expected: compiles; prints `x= 112` and `RESULT ran_on_host=0 check=pass`
! - rule: "A list item may appear more than once in the map clauses that are specified on the same directive" (5.2 §5.8.3 p.151
!   l.14-15).
! - same-compiler control (compiles; correct, gcc_sm80: mandatory pass 5 of 5; unset pass 5 of 5; gcc_g90: mandatory pass 5 of 5;
!   unset pass 5 of 5 (results/parity/<machine>/<tc>/probes.jsonl)): the variable in one map clause, map(tofrom: x)
!   (controls/gcc-same-item-two-maps-control.f90).
! - GCC's documentation: no row of libgomp.texi's tables names it (undocumented). GCC's own development testsuite has programs of
!   this form (libgomp target-map-multi-*, harvested from gcc master 9e5dc385 into harvest2), so later GCC accepts it. On a target
!   data construct the same form ends in an internal compiler error instead (gcc-c-target-data-two-maps-ice.c).
! - other families: AFAR, CCE 19/20/21/21.0.4 and NVHPC 25.11/26.9 compile and run this file correctly (site matrix); on the
!   harvested programs AFAR and CCE are correct, NVHPC fails them another way. The site's finding matrix runs this file on every
!   compiler.
! - harvested programs (8 cells (5 gcc_g90, 3 gcc_sm80); gate: confirmed 8; confirmer: compiler_bug (R11-compile-rejection) 6, gate
!   only 2): h2-gomp-f-target-map-multi-1, h2-gomp-f-target-map-multi-4, h2-gomp-f-target-map-multi-5, sections-omp-1024-1,
!   sections-omp-64-1
! - legality: the pre-run check (offload.engine.prerun.check: the rules and AFAR's front end, two witnesses) accepts the harvested
!   programs. GCC is a compiler under test only and never a legality witness.
program map_same_item_twice
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer :: x, host_flag
  x = 111
  host_flag = 1
  ! the same list item in two map clauses of one construct
  !$omp target map(alloc: x) map(tofrom: x) map(tofrom: host_flag)
    host_flag = merge(1, 0, omp_is_initial_device())
    x = x + 1
  !$omp end target
  print '(a,i0)', 'x= ', x
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', x == 112)
end program map_same_item_twice
! site:
! title: The same variable in two map clauses of one target construct is rejected
! summary: OpenMP 5.2 allows a list item in more than one map clause of one directive. GCC 16.2 rejects a target construct
! + with map(alloc: x) map(tofrom: x) for both offload targets; its documentation does not list the gap.
! same_as: harvest/gcc-c-same-item-two-maps-rejected
! control: harvest/controls/gcc-same-item-two-maps-control.f90 the variable in one map clause, map(tofrom: x)
! end site
