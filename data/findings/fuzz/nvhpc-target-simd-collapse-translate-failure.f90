! # Finding (parity-fuzz-s1): NVHPC: a collapse clause on a combined target simd construct fails to translate ("Missing branch
! # target block"); target containing simd collapse, or target simd without collapse, compiles and runs correctly
!
! - toolchains and modes that fail: nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9); modes: copy, managed; -O2
! - build: nvfortran -mp=gpu -gpu=cc80 -gpu=mem:separate -O2
! - failure: ice
! - observed: `NVFORTRAN-W-0155-Compiler failed to translate accelerator region (see -Minfo messages): Missing branch target
!   block (<tmpdir>/nvhpc-target-simd-collapse-translate-failure.f90: 10)` followed by `NVFORTRAN-F-0704-Compilation aborted due
!   to previous errors.` (the rows' stderr; the harness's reason reads the F-0704 line); identical signature on 4 of 4 failing
!   cells
! - expected: compiles and prints `o1= -11.00` with `check=pass`
! - rule: "The collapse clause associates one or more loops with the directive on which it appears for the purpose of
!   identifying the portion of the depth of the canonical loop nest to which to apply the semantics of the directive." (5.2
!   §4.4.3 p.93 l.23-25), whose directives are "distribute, do, for, loop, simd, taskloop" (5.2 §4.4.3 p.93 l.21), and "If
!   directive-name-A is target then directive-name-B may be simd" (5.2 §17.3 p.342 l.22): collapse(2) on target simd applies the
!   simd semantics to the two-loop nest
! - vendor: "the simd construct is ignored for GPU targets" (item 2.9.3) and "Combined constructs are supported to the extent
!   that the component constructs are themselves supported." (item 2.13); the collapse clause is listed as supported on the
!   worksharing-loop, distribute and loop constructs (items 2.9.2, 2.9.4, 2.9.5) (NVIDIA HPC Compilers User's Guide 26.9, Using
!   OpenMP; data/index/claims/nvidia-hpc-26.9-user-guide-openmp.txt)
! - same-compiler control: controls/nvhpc-target-simd-no-collapse-control.f90 (one change from this file; correct on nvhpc (NVHPC
!   25.11), nvhpc269 (NVHPC 26.9); rows results/parity/nvs1/tuo.bt.jsonl, results/parity/nvs1/wt.bt.jsonl);
!   controls/nvhpc-target-simd-collapse-split-control.f90 (one change from this file; correct on nvhpc (NVHPC 25.11), nvhpc269
!   (NVHPC 26.9); rows results/parity/nvs1/tuo.bt.jsonl, results/parity/nvs1/wt.bt.jsonl)
! - other families: afar (AFAR 24.3.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4) run the
!   file correctly (rows results/parity/nvs1/tuo.bt.jsonl)
! - variants: files next to the reduction in results/parity/nvs1/red/, rows results/parity/nvs1/wt.bt.jsonl (both releases,
!   separate and managed memory) and results/parity/nvs1/tuo.bt.jsonl: the same loop nest as target teams distribute simd
!   collapse(2) (nvhpc-target-teams-distribute-simd-collapse-variant.f90) and as target parallel do simd collapse(2)
!   (nvhpc-target-parallel-do-simd-collapse-variant.f90) compiles and is correct; target simd collapse(2) with a reduction
!   (nvhpc-target-simd-collapse-reduction-variant.f90, the seed's shape) fails the same way. The seed's loop direction, complex
!   output and reduction are irrelevant (exploration). The same message appears on n0x0/n1x0 seeds 847, 722 and 163
!   (data/reports/fuzz-n0x0.md), not re-checked
! - gate and confirmer: 4 of 4 cells reproduce in all four environments (a-d; (c) on another node or GPU than (a); rows
!   results/parity/nvs1/gate_abd.bt.jsonl, results/parity/nvs1/gate_abd.bt.m2.jsonl, results/parity/nvs1/gate_c.bt.jsonl,
!   results/parity/nvs1/gate_c.bt.m2.jsonl, results/parity/nvs1/wt.bt.jsonl); campaign gate of the programs below: 2 cells, 2
!   confirmed in the four environments (a-d; (c) on another node or GPU; rows
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.abd.2476695.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.c.3482833.jsonl)
! - programs (1): par-s1-nvhpc-nvhpc269:9796
! - legality: the rules (offload.engine.rules) and AFAR's flang front end accept this file, its controls and the variants above
!   (offload.engine.prerun.check on a Tuolumne compute node; results/parity/nvs1/prerun.bt.txt); AFAR 24.3.0 and CCE 19/20/21/21.0.4
!   compile and run all of them correctly with HSA_XNACK 0 and 1 (results/parity/nvs1/tuo.bt.jsonl). NVHPC is the compiler under
!   test and is not counted as a witness
program p
  implicit none
  integer, parameter :: n = 16, m = 4
  integer :: ia(n), i, j
  real(4) :: o1(n, m)
  do i = 1, n
    ia(i) = mod(i * 22 + 1, 97) - 35
  end do
  o1 = 0.0
  !$omp target simd map(from: o1) map(to: ia) collapse(2)
  do i = 1, n
    do j = 1, m
      o1(i, j) = real(ia(i) + j, 4)
    end do
  end do
  !$omp end target simd
  print '(a,f0.2)', 'o1= ', o1(1, 1)
  print '(a,a)', 'RESULT ran_on_host=0 check=', merge('pass', 'fail', nint(o1(1, 1)) == ia(1) + 1)
end program p

! site:
! title: collapse on target simd: translation failure
! summary: nvfortran -mp=gpu appears to behave incorrectly on a combined target simd construct with a collapse clause: the
! + compile stops with "Compiler failed to translate accelerator region: Missing branch target block". The same loop nest as
! + target containing simd collapse(2), as target simd without collapse, or as target teams distribute simd collapse(2),
! + compiles and runs correctly.
! control: fuzz/controls/nvhpc-target-simd-no-collapse-control.f90 one change from the finding; correct on nvhpc, nvhpc269
! control: fuzz/controls/nvhpc-target-simd-collapse-split-control.f90 one change from the finding; correct on nvhpc, nvhpc269
! end site
