! # Finding (parity-fuzz-c1): NVHPC: a reduction on a combined target construct that also has defaultmap(to: scalar) is not copied
! # back; the reduction variable keeps its initial value on the host
!
! - toolchains and modes that fail: nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9); modes: copy, managed; -O2
! - build: nvfortran -mp=gpu -gpu=cc80 -gpu=mem:separate -O2
! - failure: wrong_answer (check=fail)
! - observed: `r= 0 h= 0` with `check=fail`; identical signature on 4 of 4 failing cells
! - expected: compiles and prints `r= 2080 h= 0` with `check=pass`
! - rule: "When specified, explicit data-environment attribute clauses on target directives determine the attributes for variables
!   referenced in a target construct. Otherwise, the first matching rule from the following list determines the implicit
!   data-mapping (or data-sharing) attribute" (5.2 §5.8.1 p.148 l.2-5); the first rule that matches r is "If a variable is the base
!   variable of a list item in a reduction, lastprivate or linear clause on a combined target construct then the list item is
!   treated as if it had appeared in a map clause with a map-type of tofrom if Section 17.2 specifies this behavior" (5.2 §5.8.1
!   p.148 l.12-14), which comes before the defaultmap rule (5.2 §5.8.1 p.148 l.18-19), and Section 17.2 does specify it: "If a list
!   item in a reduction clause on a combined target construct does not have the same base variable or base pointer as a list item
!   in a map clause on the construct, then the effect is as if the list item in the reduction clause appears as a list item in a
!   map clause with a map-type of tofrom" (5.2 §17.2 p.341 l.10-13). OpenMP 5.0 orders the rules the same way: "If a list item
!   appears in a reduction, lastprivate or linear clause on a combined target construct then it is treated as if it also appears
!   in a map clause with a map-type of tofrom" (5.0 §2.19.7 p.314 l.14-16) precedes its defaultmap rule (5.0 §2.19.7 p.314 l.20-21)
! - vendor: "The defaultmap clause is supported using OpenMP 5.0 semantics." and "The reduction clause is supported." (NVIDIA HPC
!   Compilers User's Guide 26.9, Using OpenMP, items 2.19.7 and 2.19.5; data/index/claims/nvidia-hpc-26.9-user-guide-openmp.txt)
! - variants: files next to the reduction in results/parity/nvc1/red/, rows results/parity/nvc1/wt.dm.jsonl (both releases, separate
!   and managed memory) and results/parity/nvc1/tuo.dm.jsonl: target teams distribute parallel do
!   (nvhpc-defaultmap-to-scalar-reduction-teams-variant.f90), target simd (nvhpc-defaultmap-to-scalar-reduction-simd-variant.f90)
!   and the seed's reduction(min:) with the same reduction on a nested simd loop
!   (nvhpc-defaultmap-to-scalar-reduction-min-nested-simd-variant.f90) lose the value too on both releases; with defaultmap(tofrom:
!   scalar) in place of defaultmap(to: scalar) (nvhpc-defaultmap-tofrom-scalar-reduction-variant.f90) the result is right. Not
!   evidence: with defaultmap(firstprivate: scalar) (nvhpc-defaultmap-firstprivate-scalar-reduction-variant.f90) both releases stop
!   in the LLVM optimizer (`opt: ... error: integer constant must have integer type`, a harness error) and AFAR's flang reports
!   "not yet implemented: Firstprivate is currently unsupported defaultmap behaviour"; a lead, not reduced
! - found by: c1 program par-c1-nvhpc-nvhpc269:962, whose campaign failure is the depend fault of
!   nvhpc-depend-implicit-map-illegal-address.f90 (error 719 at cuEventQuery); with its depend and nowait clauses removed it runs
!   and only r1a is wrong, the reduction(min: r1a) of a target parallel do with defaultmap(to: scalar)
!   (exploration, not rows). No campaign cell has this signature alone, so no programs are counted
!   here (962's
!   campaign cell is related to, and not counted in, the depend finding either)
! - same-compiler control: controls/nvhpc-defaultmap-to-scalar-removed-control.f90 (one change from this file; correct on nvhpc
!   (NVHPC 25.11), nvhpc269 (NVHPC 26.9); rows results/parity/nvc1/tuo.dm.jsonl, results/parity/nvc1/wt.dm.jsonl);
!   controls/nvhpc-defaultmap-to-scalar-reduction-mapped-control.f90 (one change from this file; correct on nvhpc (NVHPC 25.11),
!   nvhpc269 (NVHPC 26.9); rows results/parity/nvc1/tuo.dm.jsonl, results/parity/nvc1/wt.dm.jsonl)
! - other families: afar (AFAR 24.3.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2) run the file correctly (rows
!   results/parity/nvc1/tuo.dm.jsonl); cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4) fail it another way, e.g. `r= 2080 h= -1` with
!   `check=fail`
! - gate and confirmer: 4 of 4 cells reproduce in all four environments (a-d; (c) on another node or GPU than (a); rows
!   results/parity/nvc1/gate_abd.dm.jsonl, results/parity/nvc1/gate_abd.dm.m2.jsonl, results/parity/nvc1/gate_c.dm.jsonl,
!   results/parity/nvc1/gate_c.dm.m2.jsonl, results/parity/nvc1/wt.dm.jsonl)
! - legality: the rules (offload.engine.rules) and AFAR's flang front end accept this file, both controls and the four
!   defaultmap(to:)
!   and defaultmap(tofrom:) variants (offload.engine.prerun.check on a Tuolumne compute node;
!   results/parity/nvc1/prerun.dm.txt); AFAR
!   24.3.0 and CCE 19/20 compile and run the file, both controls and those four variants correctly with HSA_XNACK 0 and 1
!   (results/parity/nvc1/tuo.dm.jsonl). The firstprivate variant is not evidence: AFAR stops at "not yet implemented" and only CCE
!   19/20 run it. CCE 21/21.0.4 reduce r correctly on the file and every variant but do not copy back the explicitly mapped h
!   (`r= 2080 h= -1`): their documented defect cce21-defaultmap-aggregate-flag.f90 (a defaultmap clause on target stops the
!   copy-back of a map(tofrom:) scalar), not this one. NVHPC is the compiler under test and is not counted as a witness
program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer :: a(64)
  integer :: i, r, h
  a = [(i, i = 1, 64)]
  r = 0
  h = -1
  !$omp target parallel do map(to: a) map(tofrom: h) defaultmap(to: scalar) reduction(+: r)
  do i = 1, 64
    if (i == 1) h = merge(1, 0, omp_is_initial_device())
    r = r + a(i)
  end do
  !$omp end target parallel do
  print '(a,i0,a,i0)', 'r= ', r, ' h= ', h
  print '(a,i0,a,a)', 'RESULT ran_on_host=', merge(1, 0, h == 1), ' check=', merge('pass', 'fail', r == 2080 .and. h == 0)
end program p

! site:
! title: defaultmap(to: scalar) drops a reduction's copy-back
! summary: nvfortran -mp=gpu appears to behave incorrectly on a reduction on a combined target construct that also has
! + defaultmap(to: scalar): the reduction variable keeps its initial value on the host. Without the defaultmap clause, or with the
! + variable in a map(tofrom:) clause, the result is right.
! control: fuzz/controls/nvhpc-defaultmap-to-scalar-removed-control.f90 one change from the finding; correct on nvhpc, nvhpc269
! control: fuzz/controls/nvhpc-defaultmap-to-scalar-reduction-mapped-control.f90 one change from the finding; correct on nvhpc,
! + nvhpc269
! end site
