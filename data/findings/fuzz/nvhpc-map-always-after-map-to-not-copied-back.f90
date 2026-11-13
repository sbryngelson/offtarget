! # Finding (parity-fuzz-c1): NVHPC: a map clause with the always modifier (tofrom or from) that follows a map(to:) clause on the
! # same target directive is not copied back; its list items keep their host values
!
! - toolchains and modes that fail: nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9); modes: copy, managed; -O2
! - build: nvfortran -mp=gpu -gpu=cc80 -gpu=mem:separate -O2
! - failure: wrong_answer (check=fail)
! - observed: `r= 0 h= 0` with `check=fail`; identical signature on 4 of 4 failing cells
! - expected: compiles and prints `r= 5 h= 0` with `check=pass`
! - rule: on exit from the region, "If the reference count of the corresponding list item is one or if the always map-type-modifier
!   is specified, and if the map-type is from or tofrom, the original list item is updated as if the list item appeared in a from
!   clause on a target update directive." (5.2 §5.8.3 p.154 l.2-5): r is in a tofrom map with the always modifier and its reference
!   count is one, so the device value (a(5) = 5) must reach the host either way; the order of the map clauses on the directive
!   carries no meaning
! - vendor: "The map([[mapmod[,]...] maptype:] datalist) clause is supported. Of the map-type-modifiers, always is supported, close
!   is ignored, and mapper(mapid) is not supported." (NVIDIA HPC Compilers User's Guide 26.9, Using OpenMP, item 2.19.7;
!   data/index/claims/nvidia-hpc-26.9-user-guide-openmp.txt)
! - variants: files next to the reduction in results/parity/nvc1/red/, rows results/parity/nvc1/wt.al.jsonl (both releases, separate
!   and managed memory) and results/parity/nvc1/tuo.al.jsonl (AFAR and CCE correct on all of them): map(always, from: r)
!   (nvhpc-map-always-from-after-map-to-variant.f90), the always clause separated from the map(to:) clause by another map clause
!   (nvhpc-map-always-after-map-to-separated-variant.f90), two list items in the always clause, both lost
!   (nvhpc-map-always-after-map-to-two-items-variant.f90), and the write inside a parallel worksharing loop
!   (nvhpc-map-always-after-map-to-parallel-do-variant.f90) fail on both releases too
! - exploration (not result rows): the items of the always clause do arrive
!   on the device (a
!   mapped array summed there, a scalar read there); a preceding map(from:) or map(tofrom:) clause does not trigger the loss, a
!   preceding map(always, to:) clause does; scalars in map(always, tofrom:) with no preceding map(to:) clause are right with and
!   without teams or parallel regions. In c1 program 2019 the three kernels' reductions and arrays were wrong this way (a teams
!   reduction variable in map(always, tofrom:) after map(always, to:), the array of the same clause read as zeros); with the always
!   modifiers removed, or with the always clauses written first, the program prints its expected checksum on both releases
! - same-compiler control: controls/nvhpc-map-always-removed-control.f90 (one change from this file; correct on nvhpc (NVHPC 25.11),
!   nvhpc269 (NVHPC 26.9); rows results/parity/nvc1/tuo.al.jsonl, results/parity/nvc1/wt.al.jsonl);
!   controls/nvhpc-map-always-first-control.f90 (one change from this file; correct on nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9);
!   rows results/parity/nvc1/tuo.al.jsonl, results/parity/nvc1/wt.al.jsonl)
! - other families: afar (AFAR 24.3.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4) run the
!   file correctly (rows results/parity/nvc1/tuo.al.jsonl)
! - gate and confirmer: 4 of 4 cells reproduce in all four environments (a-d; (c) on another node or GPU than (a); rows
!   results/parity/nvc1/gate_abd.al.jsonl, results/parity/nvc1/gate_abd.al.m2.jsonl, results/parity/nvc1/gate_c.al.jsonl,
!   results/parity/nvc1/gate_c.al.m2.jsonl, results/parity/nvc1/wt.al.jsonl); campaign gate of the programs below: 2 cells, 2
!   confirmed in the four environments (a-d; (c) on another node or GPU; rows
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.abd.127709.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.c.210965.jsonl)
! - programs (1): par-c1-nvhpc-nvhpc269:2019
! - legality: the rules (offload.engine.rules) and AFAR's flang front end accept this file, both controls and the variants
!   (offload.engine.prerun.check on a Tuolumne compute node; results/parity/nvc1/prerun.al.txt); AFAR 24.3.0 and CCE 19/20/21/21.0.4
!   compile and run all of them correctly with HSA_XNACK 0 and 1 (results/parity/nvc1/tuo.al.jsonl). NVHPC is the compiler under
!   test and is not counted as a witness
program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer :: a(64)
  integer :: i, r, h
  a = [(i, i = 1, 64)]
  r = 0
  h = -1
  !$omp target map(to: a) map(always, tofrom: r) map(tofrom: h)
    h = merge(1, 0, omp_is_initial_device())
    r = a(5)
  !$omp end target
  print '(a,i0,a,i0)', 'r= ', r, ' h= ', h
  print '(a,i0,a,a)', 'RESULT ran_on_host=', merge(1, 0, h == 1), ' check=', merge('pass', 'fail', r == 5 .and. h == 0)
end program p

! site:
! title: map(always, tofrom:) after map(to:): not copied back
! summary: nvfortran -mp=gpu appears to behave incorrectly on a map clause with the always modifier (tofrom or from) that follows a
! + map(to:) clause on the same target directive: its list items are not copied back and keep their host values. Without the
! + modifier, or with the always clause written before the map(to:) clause, the result is right.
! control: fuzz/controls/nvhpc-map-always-removed-control.f90 one change from the finding; correct on nvhpc, nvhpc269
! control: fuzz/controls/nvhpc-map-always-first-control.f90 one change from the finding; correct on nvhpc, nvhpc269
! end site
