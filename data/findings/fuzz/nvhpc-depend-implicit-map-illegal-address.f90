! # Finding (parity-fuzz-c1): NVHPC: a target construct whose depend clause names an array that the construct maps only implicitly
! # ends in CUDA_ERROR_ILLEGAL_ADDRESS
!
! - toolchains and modes that fail: nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9); modes: copy, managed; -O2
! - build: nvfortran -mp=gpu -gpu=cc80 -gpu=mem:separate -O2
! - failure: run_error
! - observed: `Accelerator Fatal Error: call to cuEventQuery returned error 700 (CUDA_ERROR_ILLEGAL_ADDRESS): Illegal address during
!   kernel execution`, exit status 1, and the same without OMP_TARGET_OFFLOAD=mandatory (the rows' stderr; the harness's reason
!   reads `exit_status: 1; without mandatory: exit_status: 1`); identical signature on 4 of 4 failing cells
! - expected: compiles and prints `sum= 2080` with `check=pass`
! - rule: "If a variable is not a scalar then it is treated as if it had appeared in a map clause with a map-type of tofrom" (5.2
!   §5.8.1 p.149 l.4-5), and on a target construct "If a depend clause is present, it is associated with the target task" (5.2 §13.8
!   p.284 l.14-15): the depend clause orders the target task and does not change how `a` is mapped
! - vendor: "Any task-generating target construct can have depend and nowait clauses" (NVIDIA HPC Compilers User's Guide 26.9, Using
!   OpenMP, the mapping of depend and nowait to CUDA streams; data/index/claims/nvidia-hpc-26.9-user-guide-openmp.txt), and the
!   target
!   construct's depend clause is listed as supported (the guide's OpenMP subset, item 2.12.5)
! - same-compiler control: controls/nvhpc-depend-explicit-map-control.f90 (one change from this file; correct on nvhpc (NVHPC
!   25.11), nvhpc269 (NVHPC 26.9); rows results/parity/nvc1/tuo.dep.jsonl, results/parity/nvc1/wt.dep.jsonl);
!   controls/nvhpc-depend-removed-control.f90 (one change from this file; correct on nvhpc (NVHPC 25.11), nvhpc269 (NVHPC 26.9);
!   rows results/parity/nvc1/tuo.dep.jsonl, results/parity/nvc1/wt.dep.jsonl)
! - other families: afar (AFAR 24.3.0), cce19 (CCE 19.0.0), cce20 (CCE 20.0.2), cce21 (CCE 21.0.3), cce21_4 (CCE 21.0.4) run the
!   file correctly (rows results/parity/nvc1/tuo.dep.jsonl)
! - gate and confirmer: 4 of 4 cells reproduce in all four environments (a-d; (c) on another node or GPU than (a); rows
!   results/parity/nvc1/gate_abd.dep.jsonl, results/parity/nvc1/gate_abd.dep.m2.jsonl, results/parity/nvc1/gate_c.dep.jsonl,
!   results/parity/nvc1/gate_c.dep.m2.jsonl, results/parity/nvc1/wt.dep.jsonl); campaign gate of the programs below: 22 cells,
!   20 confirmed in the four environments (a-d; (c) on another node or GPU; rows
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.abd.127709.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.abd.127721.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.abd.2465893.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.abd.2476695.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.c.210952.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.c.210965.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.c.3354124.jsonl,
!   results/parity/wingtip/results/parity/gate/fuzz/reruns/wingtip.c.3482833.jsonl); the campaign gate's
!   verdict is confirmed for all 22 cells; the other 2 (1766 on both releases) were rerun in (b) and (c) only
! - programs (11): par-c1-nvhpc-nvhpc269:1014, par-c1-nvhpc-nvhpc269:1115, par-c1-nvhpc-nvhpc269:1147,
!   par-c1-nvhpc-nvhpc269:1274, par-c1-nvhpc-nvhpc269:1316, par-c1-nvhpc-nvhpc269:1766, par-c1-nvhpc-nvhpc269:1878,
!   par-c1-nvhpc-nvhpc269:2302, par-s1-nvhpc-nvhpc269:1984, par-s1-nvhpc-nvhpc269:2459, par-s1-nvhpc-nvhpc269:4050. The three s1
!   programs name an array the construct maps only implicitly (ds, ic, xr8) in a depend clause with nowait, fail with
!   cuEventQuery error 700 on both releases, and give the expected checksum with their depend and nowait clauses removed
! (exploration)
! - related, not counted: par-c1-nvhpc-nvhpc269:962 ends with error 719 (CUDA_ERROR_LAUNCH_FAILED) at cuEventQuery rather than 700,
!   and its depend lists name arrays that are present through an enclosing target data region (o1 also in an explicit map clause)
!   rather than arrays the construct maps implicitly; with depend and nowait removed it runs, with one wrong value that is the
!   defect of nvhpc-defaultmap-to-scalar-reduction-lost.f90 (exploration, not rows)
! - legality: the rules (offload.engine.rules) and AFAR's flang front end accept this file and both controls
!   (offload.engine.prerun.check on
!   a Tuolumne compute node; results/parity/nvc1/prerun.dep.txt); AFAR 24.3.0 and CCE 19/20/21/21.0.4 compile and run it correctly
!   with HSA_XNACK 0 and 1 (results/parity/nvc1/tuo.dep.jsonl). NVHPC is the compiler under test and is not counted as a witness
program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer :: a(64)
  integer :: i, s, host
  a = 0
  host = 1
  !$omp target map(tofrom: host) nowait depend(inout: a)
  do i = 1, 64
    a(i) = i
  end do
  if (omp_is_initial_device()) then
    host = 1
  else
    host = 0
  end if
  !$omp end target
  !$omp taskwait
  s = sum(a)
  print '(a,i0)', 'sum= ', s
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host, ' check=', merge('pass', 'fail', s == 2080)
end program p

! site:
! title: depend naming an implicitly mapped array: illegal address
! summary: nvfortran -mp=gpu appears to behave incorrectly when a target construct's depend clause names an array that the construct
! + maps only implicitly: the kernel ends in CUDA_ERROR_ILLEGAL_ADDRESS. With the array in a map clause, or without the depend
! + clause, the result is right.
! control: fuzz/controls/nvhpc-depend-explicit-map-control.f90 one change from the finding; correct on nvhpc, nvhpc269
! control: fuzz/controls/nvhpc-depend-removed-control.f90 one change from the finding; correct on nvhpc, nvhpc269
! end site
