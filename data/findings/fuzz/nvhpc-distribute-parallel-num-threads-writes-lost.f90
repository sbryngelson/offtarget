! # Finding (parity-fuzz-c1): NVHPC 25.11: the writes of a worksharing loop in a parallel region with a num_threads clause nested in
! # a distribute loop never reach the array (26.9 correct)
!
! - toolchains and modes that fail: nvhpc (NVHPC 25.11); modes: copy, managed; -O2
! - build: nvfortran -mp=gpu -gpu=cc80 -gpu=mem:separate -O2
! - failure: wrong_answer (check=fail)
! - observed: `sum= 0 h= 0` with `check=fail`; identical signature on 2 of 2 failing cells
! - expected: compiles and prints `sum= 2432 h= 0` with `check=pass`
! - rule: "The num_threads clause specifies the desired number of threads to execute a parallel region." (5.2 §10.1.2 p.227 l.23)
!   and "If a variable is not a scalar then it is treated as if it had appeared in a map clause with a map-type of tofrom" (5.2
!   §5.8.1 p.149 l.4-5): the clause only sizes the team; o2 is shared by the teams, the distribute loop and the nested parallel
!   region, written by the worksharing loop and copied back when the target region ends
! - vendor: "The num_threads, default, private, firstprivate, and shared clauses are supported" (NVIDIA HPC Compilers User's Guide
!   26.9, Using OpenMP, item 2.6 Parallel Construct), "The distribute construct is supported within a teams construct." (item
!   2.9.4), and the guide's own example of "nested parallelism in the target teams distribute construct" (a parallel loop inside
!   it, with thread_limit recommended); item 2.20 says "nested teams or parallel regions in a target region are not supported",
!   which could also be read as excluding this form; the guide's own example and NVHPC 26.9's correct run of this file are the
!   reasons to read it as a second level of parallelism, and the program is legal by the specification either way
!   (data/index/claims/nvidia-hpc-26.9-user-guide-openmp.txt)
! - exploration (not result rows): num_threads(3), num_teams(2) on the
!   teams, do simd, an
!   allocatable o2 and an explicit map(tofrom: o2) all give sum= 0 on 25.11 and the right sum on 26.9
! - same-compiler control: controls/nvhpc-distribute-parallel-num-threads-removed-control.f90 (one change from this file; correct on
!   nvhpc (NVHPC 25.11); rows results/parity/nvc1/tuo.dp.jsonl, results/parity/nvc1/wt.dp.jsonl);
!   controls/nvhpc-distribute-parallel-removed-control.f90 (one change from this file; correct on nvhpc (NVHPC 25.11); rows
!   results/parity/nvc1/tuo.dp.jsonl, results/parity/nvc1/wt.dp.jsonl)
! - other families: afar (AFAR 24.3.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4), nvhpc269
!   (NVHPC 26.9) run the file correctly (rows results/parity/nvc1/gate_abd.dp.jsonl, results/parity/nvc1/gate_abd.dp.m2.jsonl,
!   results/parity/nvc1/gate_c.dp.jsonl, results/parity/nvc1/gate_c.dp.m2.jsonl, results/parity/nvc1/tuo.dp.jsonl,
!   results/parity/nvc1/wt.dp.jsonl)
! - gate and confirmer: 2 of 2 cells reproduce in all four environments (a-d; (c) on another node or GPU than (a); rows
!   results/parity/nvc1/gate_abd.dp.jsonl, results/parity/nvc1/gate_abd.dp.m2.jsonl, results/parity/nvc1/gate_c.dp.jsonl,
!   results/parity/nvc1/gate_c.dp.m2.jsonl, results/parity/nvc1/wt.dp.jsonl); campaign gate of the programs below: 2 cells, 2
!   confirmed in the four environments (a-d; (c) on another node or GPU; rows
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.abd.127709.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.abd.127721.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.c.210952.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.c.210965.jsonl)
! - programs (2): par-c1-nvhpc-nvhpc269:1098, par-c1-nvhpc-nvhpc269:1733
! - legality: the rules (offload.engine.rules) and AFAR's flang front end accept this file and both controls
!   (offload.engine.prerun.check on
!   a Tuolumne compute node; results/parity/nvc1/prerun.dp.txt); AFAR 24.3.0 and CCE 19/20/21/21.0.4 compile and run all three
!   correctly with HSA_XNACK 0 and 1 (results/parity/nvc1/tuo.dp.jsonl). NVHPC is the compiler under test and is not counted as a
!   witness (26.9 runs the file correctly, 25.11 does not)
program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 32, m = 4
  integer :: o2(n, m)
  integer :: i, j, h
  h = -1
  o2 = 0
  !$omp target map(tofrom: h)
  !$omp teams
  !$omp distribute
  do i = 1, n
    if (i == 1) h = merge(1, 0, omp_is_initial_device())
    !$omp parallel num_threads(1)
    !$omp do
      do j = 1, m
        o2(i, j) = i + j
      end do
    !$omp end do
    !$omp end parallel
  end do
  !$omp end teams
  !$omp end target
  print '(a,i0,a,i0)', 'sum= ', sum(o2), ' h= ', h
  print '(a,i0,a,a)', 'RESULT ran_on_host=', merge(1, 0, h == 1), ' check=', merge('pass', 'fail', sum(o2) == 2432 .and. h == 0)
end program p

! site:
! title: parallel num_threads inside distribute: writes lost (25.11)
! summary: nvfortran 25.11 -mp=gpu appears to behave incorrectly on a worksharing loop in a parallel region with a num_threads
! + clause nested in a distribute loop: the array it writes stays zero on the host. Without the num_threads clause, or without the
! + nested parallel region, the result is right; NVHPC 26.9 is correct.
! control: fuzz/controls/nvhpc-distribute-parallel-num-threads-removed-control.f90 one change from the finding; correct on nvhpc
! control: fuzz/controls/nvhpc-distribute-parallel-removed-control.f90 one change from the finding; correct on nvhpc
! end site
