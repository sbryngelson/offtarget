! # Finding (parity-fuzz-s1): NVHPC: the end directive of a distribute simd construct is rejected ("Syntax error at or near
! # identifier simd"); the construct without its end directive compiles and runs correctly
!
! - toolchains and modes that fail: nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9); modes: copy, managed; -O2
! - build: nvfortran -mp=gpu -gpu=cc80 -gpu=mem:separate -O2
! - failure: rejected
! - observed: `NVFORTRAN-S-0034-Syntax error at or near identifier simd (<tmpdir>/nvhpc-end-distribute-simd-rejected.f90: 11)`;
!   identical signature on 4 of 4 failing cells
! - expected: compiles and prints `sum= 2080` with `check=pass`
! - rule: "If directive-name-A is distribute then directive-name-B may be simd" (5.2 §17.3 p.342 l.17) names the composite
!   distribute simd construct; the directive-name of its paired end directive is "end directive-name unless otherwise specified"
!   (5.2 §3.1 p.49 l.14) and "For a loop-associated directive, the paired end directive is optional." (5.2 §3.1 p.52 l.26):
!   `!$omp end distribute simd` is the construct's end directive, which may be written or left out
! - vendor: "The distribute simd construct is treated as a distribute construct and is supported for GPU targets; valid
!   supported distribute clauses are accepted; simd clauses are ignored." (NVIDIA HPC Compilers User's Guide 26.9, Using OpenMP,
!   item 2.9.4; data/index/claims/nvidia-hpc-26.9-user-guide-openmp.txt)
! - same-compiler control: controls/nvhpc-distribute-simd-no-end-directive-control.f90 (one change from this file; correct on nvhpc
!   (NVHPC 25.11), nvhpc269 (NVHPC 26.9); rows results/parity/nvs1/tuo.ds.jsonl, results/parity/nvs1/wt.ds.jsonl);
!   controls/nvhpc-distribute-end-distribute-control.f90 (one change from this file; correct on nvhpc (NVHPC 25.11), nvhpc269 (NVHPC
!   26.9); rows results/parity/nvs1/tuo.ds.jsonl, results/parity/nvs1/wt.ds.jsonl)
! - other families: afar (AFAR 24.3.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4) run the
!   file correctly (rows results/parity/nvs1/tuo.ds.jsonl)
! - variants: files next to the reduction in results/parity/nvs1/red/, rows results/parity/nvs1/wt.ds.jsonl (both releases,
!   separate and managed memory) and results/parity/nvs1/tuo.ds.jsonl: the combined teams distribute simd with its end directive
!   (nvhpc-end-teams-distribute-simd-unmatched-variant.f90) is rejected with `NVFORTRAN-F-1225-Unmatched directive END - TEAMS
!   DISTRIBUTE`; the combined target teams distribute simd with its end directive
!   (nvhpc-end-target-teams-distribute-simd-variant.f90) compiles and is correct. The two s1 programs end their distribute simd
!   loops with the end directive (fuzz_prog.f90 lines 75 and 90 of seeds 9906 and 8744, the lines the compiler names)
! - gate and confirmer: 4 of 4 cells reproduce in all four environments (a-d; (c) on another node or GPU than (a); rows
!   results/parity/nvs1/gate_abd.ds.jsonl, results/parity/nvs1/gate_abd.ds.m2.jsonl, results/parity/nvs1/gate_c.ds.jsonl,
!   results/parity/nvs1/gate_c.ds.m2.jsonl, results/parity/nvs1/wt.ds.jsonl); campaign gate of the programs below: 4 cells, 4
!   confirmed in the four environments (a-d; (c) on another node or GPU; rows
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.abd.2465893.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.abd.2476695.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.c.3354124.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.c.3482833.jsonl)
! - programs (2): par-s1-nvhpc-nvhpc269:9906, par-s1-nvhpc-nvhpc269:8744; the same syntax error is in the stderr of seeds 2146,
!   3062 and 6056 (`!$omp end distribute simd`) and the Unmatched directive message of the variant in those of 671 and 5847
!   (`!$omp end teams distribute simd`), both releases, whose cells' first diagnostics are other rejections (an unrecognized
!   declare directive, a syntax error at `:`, thread_limit on target), so they are not counted
! - legality: the rules (offload.engine.rules) and AFAR's flang front end accept this file, its controls and the variants above
!   (offload.engine.prerun.check on a Tuolumne compute node; results/parity/nvs1/prerun.ds.txt); AFAR 24.3.0 and CCE 19/20/21/21.0.4
!   compile and run all of them correctly with HSA_XNACK 0 and 1 (results/parity/nvs1/tuo.ds.jsonl). NVHPC is the compiler under
!   test and is not counted as a witness
program p
  implicit none
  integer :: a(64), i
  a = 0
  !$omp target map(from: a)
    !$omp teams
      !$omp distribute simd
      do i = 1, 64
        a(i) = i
      end do
      !$omp end distribute simd
    !$omp end teams
  !$omp end target
  print '(a,i0)', 'sum= ', sum(a)
  print '(a,a)', 'RESULT ran_on_host=0 check=', merge('pass', 'fail', sum(a) == 2080)
end program p

! site:
! title: end distribute simd: syntax error
! summary: nvfortran -mp=gpu appears not to support the end directive of a distribute simd construct: `!$omp end distribute
! + simd` stops the compile with a syntax error at `simd`, and `!$omp end teams distribute simd` with "Unmatched directive END -
! + TEAMS DISTRIBUTE". The same construct without its end directive, or a distribute construct with its end directive, compiles
! + and runs correctly.
! control: fuzz/controls/nvhpc-distribute-simd-no-end-directive-control.f90 one change from the finding; correct on nvhpc, nvhpc269
! control: fuzz/controls/nvhpc-distribute-end-distribute-control.f90 one change from the finding; correct on nvhpc, nvhpc269
! end site
