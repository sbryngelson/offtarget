! # Finding (parity-fuzz-s1): NVHPC: a teams distribute parallel do with reduction, lastprivate and default(none) crashes the
! # front end (fort1 killed by signal 11); without default(none), or with default(shared), it compiles and runs correctly
!
! - toolchains and modes that fail: nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9); modes: copy, managed; -O2
! - build: nvfortran -mp=gpu -gpu=cc80 -gpu=mem:separate -O2
! - failure: ice
! - observed: `nvfortran-Fatal-$NVHPC_25_11/compilers/bin/tools/fort1 TERMINATED by signal 11`; identical signature on 4 of 4
!   failing cells
! - expected: compiles and prints `suma= 36 r= 36` with `check=pass`
! - rule: "If data-sharing-attribute is none, each variable that is referenced in the construct and does not have a
!   predetermined data-sharing attribute must have its data-sharing attribute explicitly determined by being listed in a
!   data-sharing attribute clause." (5.2 §5.4.1 p.109 l.15-17): r and lp are listed in the reduction and lastprivate clauses, a
!   in shared, and the loop variable i is predetermined private, so the program meets the restriction
! - vendor: "The num_threads, default, private, firstprivate, and shared clauses" are supported on the parallel construct and
!   "The reduction clause is supported" (items 2.6 and 2.19.5); "The lastprivate clause is supported" on the worksharing loop
!   (item 2.9.2) (NVIDIA HPC Compilers User's Guide 26.9, Using OpenMP; data/index/claims/nvidia-hpc-26.9-user-guide-openmp.txt)
! - same-compiler control: controls/nvhpc-default-none-removed-control.f90 (one change from this file; correct on nvhpc (NVHPC
!   25.11), nvhpc269 (NVHPC 26.9); rows results/parity/nvs1/tuo.st.jsonl, results/parity/nvs1/wt.st.jsonl);
!   controls/nvhpc-default-shared-control.f90 (one change from this file; correct on nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9);
!   rows results/parity/nvs1/tuo.st.jsonl, results/parity/nvs1/wt.st.jsonl)
! - other families: cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4) run the file correctly
!   (rows results/parity/nvs1/tuo.st.jsonl); afar (AFAR 24.3.0) fail it another way: `not yet implemented: lastprivate clause in
!   constructs other than simd/worksharing-loop/taskloop` in its lowering (AFAR's own limit; the same on both controls and the
!   variant)
! - variants: files next to the reduction in results/parity/nvs1/red/, rows results/parity/nvs1/wt.st.jsonl (both releases,
!   separate and managed memory) and results/parity/nvs1/tuo.st.jsonl: default(none) kept and the reduction removed
!   (nvhpc-default-none-reduction-removed-variant.f90) compiles and is correct, so the crash needs the three clauses together.
!   The programs check the array and the reduction only: neither release copies the lastprivate value of a distribute loop back
!   (lp stays 0), the documented limit "The lastprivate clause is not supported" on distribute (item 2.9.4). The seed's simd,
!   firstprivate and num_threads clauses, its declare target module structure and its allocatable component are irrelevant
!   (exploration)
! - gate and confirmer: 4 of 4 cells reproduce in all four environments (a-d; (c) on another node or GPU than (a); rows
!   results/parity/nvs1/gate_abd.st.jsonl, results/parity/nvs1/gate_abd.st.m2.jsonl, results/parity/nvs1/gate_c.st.jsonl,
!   results/parity/nvs1/gate_c.st.m2.jsonl, results/parity/nvs1/wt.st.jsonl); campaign gate of the programs below: 2 cells, 2
!   confirmed in the four environments (a-d; (c) on another node or GPU; rows
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.abd.2465893.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.c.3354124.jsonl)
! - programs (1): par-s1-nvhpc-nvhpc269:8009
! - legality: the rules (offload.engine.rules) and AFAR's flang front end accept this file, its controls and the variant above
!   (offload.engine.prerun.check on a Tuolumne compute node; results/parity/nvs1/prerun.st.txt); CCE 19/20/21/21.0.4 compile and run
!   all of them correctly with HSA_XNACK 0 and 1 (results/parity/nvs1/tuo.st.jsonl); AFAR 24.3.0 stops on every one of them in
!   its lowering (`not yet implemented: lastprivate clause in constructs other than simd/worksharing-loop/taskloop`,
!   results/parity/nvs1/tuo.st.jsonl), AFAR's own limit. NVHPC is the compiler under test and is not counted as a witness
program p
  implicit none
  integer :: a(8), i, lp, r
  a = 0
  lp = 0
  r = 0
  !$omp target map(tofrom: a, r) map(from: lp)
    !$omp teams distribute parallel do reduction(+: r) lastprivate(lp) default(none) shared(a)
    do i = 1, 8
      a(i) = i
      r = r + i
      lp = i
    end do
    !$omp end teams distribute parallel do
  !$omp end target
  print '(a,i0,a,i0)', 'suma= ', sum(a), ' r= ', r
  print '(a,a)', 'RESULT ran_on_host=0 check=', merge('pass', 'fail', sum(a) == 36 .and. r == 36)
end program p

! site:
! title: default(none) with reduction and lastprivate: compiler crash
! summary: nvfortran -mp=gpu appears to behave incorrectly on a teams distribute parallel do construct that has a reduction, a
! + lastprivate and a default(none) clause: the front end is killed by signal 11. Without default(none), or with
! + default(shared), it compiles and runs correctly.
! control: fuzz/controls/nvhpc-default-none-removed-control.f90 one change from the finding; correct on nvhpc, nvhpc269
! control: fuzz/controls/nvhpc-default-shared-control.f90 one change from the finding; correct on nvhpc, nvhpc269
! end site
