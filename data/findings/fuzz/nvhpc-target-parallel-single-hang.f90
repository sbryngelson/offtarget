! # Finding (parity-fuzz-c1): NVHPC: a barrier inside a combined target parallel construct never completes (the end of a single, of
! # a worksharing loop, an explicit barrier); the same region as target containing parallel ends
!
! - toolchains and modes that fail: nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9); modes: copy, managed; -O2
! - build: nvfortran -mp=gpu -gpu=cc80 -gpu=mem:separate -O2
! - failure: timeout
! - observed: `RUN_TIMEOUT`: the program does not end and is killed at the harness limit (60 s) in every run
!   (OMP_TARGET_OFFLOAD=mandatory); identical signature on 4 of 4 failing cells
! - expected: compiles and prints `h= 0` with `check=pass`
! - rule: "An implicit barrier occurs at the end of a single region if the nowait clause is not specified." (5.2 §11.1 p.241 l.5-6),
!   and "The semantics of the combined constructs are identical to that of explicitly specifying the first construct containing one
!   instance of the second construct and no other statements." (5.2 §17.4 p.343 l.7-8): the program is a target region holding one
!   parallel region whose single ends in a barrier that every thread of the team reaches
! - vendor: "The barrier construct is supported." and "Implicit barriers are implemented." (NVIDIA HPC Compilers User's Guide 26.9,
!   Using OpenMP, items 2.17.2 and 2.17.3), single is listed with its private, firstprivate and nowait clauses (item 2.8.2), and
!   "Combined constructs are supported to the extent that the component constructs are themselves supported." (item 2.13;
!   data/index/claims/nvidia-hpc-26.9-user-guide-openmp.txt)
! - same-compiler control: controls/nvhpc-target-parallel-split-control.f90 (one change from this file; correct on nvhpc (NVHPC
!   25.11), nvhpc269 (NVHPC 26.9); rows results/parity/nvc1/tuo.bar.jsonl, results/parity/nvc1/wt.bar.jsonl);
!   controls/nvhpc-target-parallel-single-nowait-control.f90 (one change from this file; correct on nvhpc (NVHPC 25.11), nvhpc269
!   (NVHPC 26.9); rows results/parity/nvc1/tuo.bar.jsonl, results/parity/nvc1/wt.bar.jsonl)
! - other families: afar (AFAR 24.3.0) run the file correctly (rows results/parity/nvc1/tuo.bar.jsonl); cce19 (CCE 19.0.0), cce20
!   (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4) fail it another way, e.g. `Creating internal compiler error backtrace
!   (please wait):`
! - variants: files next to the reduction in results/parity/nvc1/red/, rows results/parity/nvc1/wt.bar.jsonl (both releases,
!   separate and managed memory) and results/parity/nvc1/tuo.bar.jsonl: an explicit barrier
!   (nvhpc-target-parallel-barrier-variant.f90) and the implicit barrier at the end of a worksharing loop
!   (nvhpc-target-parallel-do-variant.f90) in the same combined construct time out too
! - gate and confirmer: 4 of 4 cells reproduce in all four environments (a-d; (c) on another node or GPU than (a); rows
!   results/parity/nvc1/gate_abd.bar.jsonl, results/parity/nvc1/gate_abd.bar.m2.jsonl, results/parity/nvc1/gate_c.bar.jsonl,
!   results/parity/nvc1/gate_c.bar.m2.jsonl, results/parity/nvc1/wt.bar.jsonl); campaign gate of the programs below: 20 cells, 2
!   confirmed in the four environments (a-d; (c) on another node or GPU; rows
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.abd.127709.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.abd.127721.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.c.210952.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.c.210965.jsonl); the campaign gate's
!   verdict is confirmed for all 20 cells; the other 18 were rerun in (b) and (c) only (timeouts are not rerun in every environment)
! - programs (10): par-c1-nvhpc-nvhpc269:991, par-c1-nvhpc-nvhpc269:1182, par-c1-nvhpc-nvhpc269:1443, par-c1-nvhpc-nvhpc269:1678,
!   par-c1-nvhpc-nvhpc269:1731, par-c1-nvhpc-nvhpc269:1762, par-c1-nvhpc-nvhpc269:1794, par-c1-nvhpc-nvhpc269:1805,
!   par-c1-nvhpc-nvhpc269:2030, par-c1-nvhpc-nvhpc269:2228
! - legality: the rules (offload.engine.rules) and AFAR's flang front end accept this file, its controls and the variants above
!   (offload.engine.prerun.check on a Tuolumne compute node; results/parity/nvc1/prerun.bar.txt); AFAR 24.3.0 runs all of them
!   correctly
!   with HSA_XNACK 0 and 1 (results/parity/nvc1/tuo.bar.jsonl). CCE 19/20/21/21.0.4 stop with an internal compiler error on single
!   and barrier in a target region, their own documented failure (cce19-target-parallel-single-ice.f90), and run the
!   worksharing-loop variant correctly. NVHPC is the compiler under test and is not counted as a witness
program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer :: h
  h = -1
  !$omp target parallel map(tofrom: h)
    !$omp single
      h = merge(1, 0, omp_is_initial_device())
    !$omp end single
  !$omp end target parallel
  print '(a,i0)', 'h= ', h
  print '(a,i0,a,a)', 'RESULT ran_on_host=', merge(1, 0, h == 1), ' check=', merge('pass', 'fail', h == 0)
end program p

! site:
! title: barrier in combined target parallel: hang
! summary: nvfortran -mp=gpu appears to behave incorrectly on a barrier inside a combined target parallel construct (the end of a
! + single or of a worksharing loop, or an explicit barrier): the program never finishes. The same region written as target
! + containing parallel, or the single with nowait, finishes with the right result.
! control: fuzz/controls/nvhpc-target-parallel-split-control.f90 one change from the finding; correct on nvhpc, nvhpc269
! control: fuzz/controls/nvhpc-target-parallel-single-nowait-control.f90 one change from the finding; correct on nvhpc, nvhpc269
! end site
