! NVHPC 25.11, NVIDIA A100 80GB PCIe (wingtip, sm_80), both memory modes: a
! target teams distribute parallel do with num_teams(4) and
! dist_schedule(static, 4) ends at run time with "Accelerator Fatal Error:
! call to cuMemcpyDtoHAsync returned error 700 (CUDA_ERROR_ILLEGAL_ADDRESS):
! Illegal address during kernel execution" (exit status 1).
! Spec: with dist_schedule(static, chunk_size) the iterations are divided
! into chunks that "are assigned to the initial teams of the league in a
! round-robin fashion in the order of the initial team number" (5.2
! §11.6.1 p.256); the program is legal.
! Vendor: "The private, firstprivate, collapse, and dist_schedule(static [
! ,chunksize]) clauses are supported" (HPC Compilers User's Guide 25.11
! §7.4, 2.9.4 Distribute Directives).
! Expected: "sum 2080".
! Observed (2026-10-24, nvfortran 25.11-0, -O2, OMP_TARGET_OFFLOAD=
! mandatory, two runs, the same): "Failing in Thread:1", the illegal
! address error at line 10, exit status 1. Without dist_schedule the
! program is correct.
! Found by the catalog (omp50/52/60-clause-dist_schedule-chunk_size:
! confirmer R20-runtime-bug); reduced by hand. The C port of the catalog
! program does not compile: nvc does not finish (compile timeout, 900 s;
! nvhpc-c-dist-schedule-chunk-compile-hang.c).
! NVHPC 26.9 (26.9-0, the latest release; rerun 2026-10-24 on wingtip with
! the same flags): still present -- the same: the illegal-address abort, exit 1, both modes.
! Fix (2026-10-24): rerun on 25.11 and 26.9 in both memory modes,
! each with its own runtime libraries (LD_LIBRARY_PATH = the release's
! compilers/lib; the first 26.9 runs had loaded 25.11's): still present
! on both releases, the same output.
! Coverage-parity fuzz, stratum c1 (2026-11-03): programs par-c1-nvhpc-nvhpc269:1052
! (dist_schedule(static, 1) on teams distribute parallel do in a target region) and :1389
! (dist_schedule(static, 2) on target teams distribute parallel do simd) end with this message
! (cuMemcpyDtoHAsync, error 700) on 25.11 and 26.9 (rows
! results/parity/wingtip/results/fuzz/par-c1-nvhpc-nvhpc269/programs.jsonl; the gate confirms
! all four cells in a-d, results/parity/wingtip/results/parity/gate/fuzz/verdicts.nvhpc-topup.jsonl).
! With dist_schedule(static) in place of the chunked form each gives the expected checksum
! (exploration runs on both releases). No separate finding.
! NVHPC: nvfortran -mp=gpu -gpu=cc80 -gpu=mem:separate -O2
! Run:   OMP_TARGET_OFFLOAD=mandatory ./a.out
program p
  implicit none
  integer :: b(64), i
  b = 0
  !$omp target teams distribute parallel do map(from: b) num_teams(4) &
  !$omp& dist_schedule(static, 4)
  do i = 1, 64
    b(i) = i
  end do
  print *, 'sum', sum(b)
end program p
! site:
! title: nvfortran -mp=gpu: dist_schedule(static, 4) on target teams distribute parallel do ends in CUDA_ERROR_ILLEGAL_ADDRESS
! control: ../vendor/checks/src/nvhpc/control/nvhpc-dist-schedule-chunk-illegal-address-control.f90 dist_schedule(static, 4) removed
! end site
