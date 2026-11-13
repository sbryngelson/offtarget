! # Finding (parity-fuzz-s1): NVHPC: a combined target simd construct written without its optional end directive is rejected
! # ("Illegal control structure - unterminated TARGET"); with the end directive, or as target containing simd, it compiles and
! # runs correctly
!
! - toolchains and modes that fail: nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9); modes: copy, managed; -O2
! - build: nvfortran -mp=gpu -gpu=cc80 -gpu=mem:separate -O2
! - failure: rejected
! - observed: `NVFORTRAN-S-0104-Illegal control structure - unterminated TARGET
!   (<tmpdir>/nvhpc-target-simd-no-end-directive-rejected.f90: 6)`; identical signature on 4 of 4 failing cells
! - expected: compiles and prints `suma= 152` with `check=pass`
! - rule: "For a loop-associated directive, the paired end directive is optional." (5.2 §3.1 p.52 l.26) and "If directive-name-A
!   is target then directive-name-B may be simd" (5.2 §17.3 p.342 l.22): the combined target simd construct is loop-associated
!   through its simd leaf, so `!$omp end target simd` may be left out
! - vendor: "the simd construct is ignored for GPU targets" (item 2.9.3) and "Combined constructs are supported to the extent
!   that the component constructs are themselves supported." (item 2.13) (NVIDIA HPC Compilers User's Guide 26.9, Using OpenMP;
!   data/index/claims/nvidia-hpc-26.9-user-guide-openmp.txt)
! - same-compiler control: controls/nvhpc-target-simd-end-directive-control.f90 (one change from this file; correct on nvhpc (NVHPC
!   25.11), nvhpc269 (NVHPC 26.9); rows results/parity/nvs1/tuo.ts.jsonl, results/parity/nvs1/wt.ts.jsonl);
!   controls/nvhpc-target-simd-split-no-end-directive-control.f90 (one change from this file; correct on nvhpc (NVHPC 25.11),
!   nvhpc269 (NVHPC 26.9); rows results/parity/nvs1/tuo.ts.jsonl, results/parity/nvs1/wt.ts.jsonl)
! - other families: afar (AFAR 24.3.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4) run the
!   file correctly (rows results/parity/nvs1/tuo.ts.jsonl)
! - variants: files next to the reduction in results/parity/nvs1/red/, rows results/parity/nvs1/wt.ts.jsonl (both releases,
!   separate and managed memory) and results/parity/nvs1/tuo.ts.jsonl: target parallel do
!   (nvhpc-target-parallel-do-no-end-directive-variant.f90) and target teams distribute
!   (nvhpc-target-teams-distribute-no-end-directive-variant.f90) without their end directives compile and are correct; with the
!   seed's simdlen(16) (nvhpc-target-simd-simdlen-no-end-directive-variant.f90) the compile stops first at "SIMDLEN, not yet
!   implemented". The s1 programs 888 and 3804 hold a target simd without its end directive, and in the campaign and its gate
!   the two bundles hung in every environment on both releases (20 of 20 compiles, class compile_timeout, this rejection in the
!   cells' stderr), so their cells carry another signature and are not counted here; one exploration compile of the 888 bundle
!   outside the harness ended with the rejection in under 150 s, and the bundle with `!$omp end target simd` added compiles. Two
!   other s1 bundles with this rejection do not hang: 8411 (counted below) and 3452, whose first diagnostic is SIMDLEN not
!   implemented (not counted). The compile hang is an unreduced lead
! - gate and confirmer: 4 of 4 cells reproduce in all four environments (a-d; (c) on another node or GPU than (a); rows
!   results/parity/nvs1/gate_abd.ts.jsonl, results/parity/nvs1/gate_abd.ts.m2.jsonl, results/parity/nvs1/gate_c.ts.jsonl,
!   results/parity/nvs1/gate_c.ts.m2.jsonl, results/parity/nvs1/wt.ts.jsonl); campaign gate of the programs below: 2 cells, 2
!   confirmed in the four environments (a-d; (c) on another node or GPU; rows
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.abd.2465893.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.c.3354124.jsonl)
! - programs (1): par-s1-nvhpc-nvhpc269:8411 (a target simd with device, reduction and map(always) clauses and no end directive;
!   both releases reject it with this message as the first diagnostic)
! - legality: the rules (offload.engine.rules) and AFAR's flang front end accept this file, its controls and the variants above
!   (offload.engine.prerun.check on a Tuolumne compute node; results/parity/nvs1/prerun.ts.txt); AFAR 24.3.0 and CCE 19/20/21/21.0.4
!   compile and run all of them correctly with HSA_XNACK 0 and 1 (results/parity/nvs1/tuo.ts.jsonl). NVHPC is the compiler under
!   test and is not counted as a witness
program p
  implicit none
  integer :: a(16), b(16), i, t
  b = 1
  a = 0
  !$omp target simd map(tofrom: a) map(to: b) private(t)
  do i = 1, 16
    t = b(i)
    a(i) = t + i
  end do
  print '(a,i0)', 'suma= ', sum(a)
  print '(a,a)', 'RESULT ran_on_host=0 check=', merge('pass', 'fail', sum(a) == 152)
end program p

! site:
! title: target simd without end directive: rejected
! summary: nvfortran -mp=gpu appears not to support a combined target simd construct written without its optional end directive:
! + the compile stops with "Illegal control structure - unterminated TARGET". With `!$omp end target simd`, as target containing
! + simd, or as target parallel do and target teams distribute without their end directives, it compiles and runs correctly.
! control: fuzz/controls/nvhpc-target-simd-end-directive-control.f90 one change from the finding; correct on nvhpc, nvhpc269
! control: fuzz/controls/nvhpc-target-simd-split-no-end-directive-control.f90 one change from the finding; correct on nvhpc,
! + nvhpc269
! end site
