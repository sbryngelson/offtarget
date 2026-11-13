! # Finding (parity-fuzz-s1): NVHPC: defaultmap(firstprivate: scalar) on a target construct whose parallel do has a lastprivate
! # clause stops the compile with an internal compiler error ("offset should not be overridden"); without the clause, or with
! # defaultmap(tofrom: scalar), it compiles and runs correctly
!
! - toolchains and modes that fail: nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9); modes: copy, managed; -O2
! - build: nvfortran -mp=gpu -gpu=cc80 -gpu=mem:separate -O2
! - failure: rejected
! - observed: `NVFORTRAN-F-0000-Internal compiler error. offset should not be overridden     321
!   (<tmpdir>/nvhpc-defaultmap-firstprivate-lastprivate-ice.f90: 12)`; identical signature on 4 of 4 failing cells
! - expected: compiles and prints `suma= 36 lp= 8` with `check=pass`
! - rule: "If implicit-behavior is firstprivate, the attribute is a data-sharing attribute of firstprivate." (5.2 §5.8.7 p.162
!   l.5-6): the clause sets the implicit attribute of the scalars the construct does not list; here lp is mapped explicitly and
!   the loop variable is predetermined private, so the clause changes no variable's attribute
! - vendor: "The defaultmap clause is supported using OpenMP 5.0 semantics" (NVIDIA HPC Compilers User's Guide 26.9, Using
!   OpenMP, item 2.12.5; data/index/claims/nvidia-hpc-26.9-user-guide-openmp.txt); firstprivate is a 5.0 implicit-behavior
! - same-compiler control: controls/nvhpc-defaultmap-firstprivate-removed-control.f90 (one change from this file; correct on nvhpc
!   (NVHPC 25.11), nvhpc269 (NVHPC 26.9); rows results/parity/nvs1/tuo.dm.jsonl, results/parity/nvs1/wt.dm.jsonl);
!   controls/nvhpc-defaultmap-tofrom-lastprivate-control.f90 (one change from this file; correct on nvhpc (NVHPC 25.11), nvhpc269
!   (NVHPC 26.9); rows results/parity/nvs1/tuo.dm.jsonl, results/parity/nvs1/wt.dm.jsonl)
! - other families: cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4) run the file correctly (rows
!   results/parity/nvs1/tuo.dm.jsonl); afar (AFAR 24.3.0) fail it another way, e.g. `LLVM ERROR: aborting`
! - variants: files next to the reduction in results/parity/nvs1/red/, rows results/parity/nvs1/wt.dm.jsonl (both releases,
!   separate and managed memory) and results/parity/nvs1/tuo.dm.jsonl: the lastprivate variable left unmapped, so that the
!   defaultmap applies to it (nvhpc-defaultmap-firstprivate-lastprivate-unmapped-variant.f90), fails the same way; the combined
!   target teams distribute parallel do with the same clauses (nvhpc-defaultmap-firstprivate-lastprivate-combined-variant.f90)
!   compiles but does not copy the lastprivate value back (lp = 0 on 26.9, an uninitialized value on 25.11), the documented
!   limit "The lastprivate clause is not supported" on distribute (item 2.9.4). The seed's kernel nests the parallel do
!   lastprivate in teams distribute lastprivate and adds schedule(dynamic, 7); without the defaultmap the seed's shape is
!   rejected for the dynamic schedule on 25.11 ("Only static schedule kind is supported for GPU") and compiles on 26.9
!   (exploration)
! - gate and confirmer: 4 of 4 cells reproduce in all four environments (a-d; (c) on another node or GPU than (a); rows
!   results/parity/nvs1/gate_abd.dm.jsonl, results/parity/nvs1/gate_abd.dm.m2.jsonl, results/parity/nvs1/gate_c.dm.jsonl,
!   results/parity/nvs1/gate_c.dm.m2.jsonl, results/parity/nvs1/wt.dm.jsonl); campaign gate of the programs below: 2 cells, 2
!   confirmed in the four environments (a-d; (c) on another node or GPU; rows
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.abd.2465893.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.abd.2476695.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.c.3354124.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.c.3482833.jsonl)
! - programs (1): par-s1-nvhpc-nvhpc269:9895; the same ICE message is in the stderr of seed 1555's cells on both releases
!   (defaultmap(firstprivate: scalar) on a target construct with do lastprivate inside), whose first diagnostic is the
!   unrecognized declare directive of its module, so it is not counted
! - legality: the rules (offload.engine.rules) and AFAR's flang front end accept this file, its controls and the variants above
!   (offload.engine.prerun.check on a Tuolumne compute node; results/parity/nvs1/prerun.dm.txt); CCE 19/20/21/21.0.4 compile and run
!   this file, its controls and the unmapped variant correctly with HSA_XNACK 0 and 1 (results/parity/nvs1/tuo.dm.jsonl); AFAR
!   24.3.0 runs both controls correctly and stops on every file with defaultmap(firstprivate: scalar) in its lowering ("not yet
!   implemented", results/parity/nvs1/tuo.dm.jsonl), AFAR's own limit. NVHPC is the compiler under test and is not counted as a
!   witness
program p
  implicit none
  integer :: a(8), j, lp
  a = 0
  lp = 0
  !$omp target map(tofrom: a, lp) defaultmap(firstprivate: scalar)
    !$omp parallel do lastprivate(lp)
    do j = 1, 8
      a(j) = j
      lp = j
    end do
  !$omp end target
  print '(a,i0,a,i0)', 'suma= ', sum(a), ' lp= ', lp
  print '(a,a)', 'RESULT ran_on_host=0 check=', merge('pass', 'fail', sum(a) == 36 .and. lp == 8)
end program p

! site:
! title: defaultmap(firstprivate: scalar) with lastprivate: ICE
! summary: nvfortran -mp=gpu appears to behave incorrectly on a target construct with defaultmap(firstprivate: scalar) that
! + contains a parallel do with a lastprivate clause: the compile stops with the internal compiler error "offset should not be
! + overridden". Without the defaultmap clause, or with defaultmap(tofrom: scalar), it compiles and runs correctly.
! control: fuzz/controls/nvhpc-defaultmap-firstprivate-removed-control.f90 one change from the finding; correct on nvhpc, nvhpc269
! control: fuzz/controls/nvhpc-defaultmap-tofrom-lastprivate-control.f90 one change from the finding; correct on nvhpc, nvhpc269
! end site
