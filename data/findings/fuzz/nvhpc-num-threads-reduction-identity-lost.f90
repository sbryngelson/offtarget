! # Finding (parity-fuzz-c1): NVHPC: a reduction(*) (also max, iand) on the worksharing loop of a parallel region with
! # num_threads(2) in a target region gives 0
!
! - toolchains and modes that fail: nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9); modes: copy, managed; -O2
! - build: nvfortran -mp=gpu -gpu=cc80 -gpu=mem:separate -O2
! - failure: wrong_answer (check=fail)
! - observed: `r= 0` with `check=fail`; identical signature on 4 of 4 failing cells
! - expected: compiles and prints `r= 768` with `check=pass`
! - rule: "For each list item, a private copy is created for each implicit task or SIMD lane and is initialized with the initializer
!   value of the reduction-identifier. After the end of the region, the original list item is updated with the values of the private
!   copies using the combiner associated with the reduction-identifier." (5.2 §5.5.8 p.134 l.21-24); the initializer of * is 1
!   (Table 5.2), so r is 3 times 2**8 = 768 whatever the number of threads
! - vendor: on GPU targets the parallel construct supports "The num_threads, default, private, firstprivate, and shared clauses",
!   and "The reduction clause is supported. The optional modifier is not supported." (NVIDIA HPC Compilers User's Guide 26.9, Using
!   OpenMP, items 2.6 and 2.19.5; data/index/claims/nvidia-hpc-26.9-user-guide-openmp.txt)
! - same-compiler control: controls/nvhpc-num-threads-removed-control.f90 (one change from this file; correct on nvhpc (NVHPC
!   25.11), nvhpc269 (NVHPC 26.9); rows results/parity/nvc1/tuo.nt.jsonl, results/parity/nvc1/wt.nt.jsonl)
! - other families: afar (AFAR 24.3.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4) run the
!   file correctly (rows results/parity/nvc1/tuo.nt.jsonl)
! - variants: files next to the reduction in results/parity/nvc1/red/, rows results/parity/nvc1/wt.nt.jsonl (both releases, separate
!   and managed memory) and results/parity/nvc1/tuo.nt.jsonl: reduction(max: r) (nvhpc-num-threads-reduction-max-variant.f90) and
!   reduction(iand: r) (nvhpc-num-threads-reduction-iand-variant.f90) print `r= 0` too, as does the same loop written as target,
!   parallel num_threads(2) and do (nvhpc-num-threads-split-variant.f90); reduction(+: r) with num_threads(2)
!   (nvhpc-num-threads-reduction-sum-variant.f90) is correct. The reduction identifiers whose initializer is not 0 lose their result
! - gate and confirmer: 4 of 4 cells reproduce in all four environments (a-d; (c) on another node or GPU than (a); rows
!   results/parity/nvc1/gate_abd.nt.jsonl, results/parity/nvc1/gate_abd.nt.m2.jsonl, results/parity/nvc1/gate_c.nt.jsonl,
!   results/parity/nvc1/gate_c.nt.m2.jsonl, results/parity/nvc1/wt.nt.jsonl); campaign gate of the programs below: 2 cells, 2
!   confirmed in the four environments (a-d; (c) on another node or GPU; rows
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.abd.127721.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.c.210952.jsonl)
! - programs (1): par-c1-nvhpc-nvhpc269:2123
! - legality: the rules (offload.engine.rules) and AFAR's flang front end accept this file, its control and the variants above
!   (offload.engine.prerun.check on a Tuolumne compute node; results/parity/nvc1/prerun.nt.txt); AFAR 24.3.0 and CCE 19/20/21/21.0.4
!   compile and run all of them correctly with HSA_XNACK 0 and 1 (results/parity/nvc1/tuo.nt.jsonl). NVHPC is the compiler under
!   test and is not counted as a witness
program p
  implicit none
  integer :: r, i
  r = 3
  !$omp target parallel do map(tofrom: r) num_threads(2) reduction(*: r)
  do i = 1, 8
    r = r * 2
  end do
  !$omp end target parallel do
  print '(a,i0)', 'r= ', r
  print '(a,a)', 'RESULT ran_on_host=0 check=', merge('pass', 'fail', r == 768)
end program p

! site:
! title: num_threads with a * reduction gives 0
! summary: nvfortran -mp=gpu appears to behave incorrectly on a worksharing-loop reduction with *, max or iand in a parallel region
! + with num_threads(2) inside a target region: the result is 0. Without num_threads, or with a + reduction, the result is right.
! control: fuzz/controls/nvhpc-num-threads-removed-control.f90 one change from the finding; correct on nvhpc, nvhpc269
! end site
